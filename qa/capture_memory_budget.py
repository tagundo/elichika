"""Small read-only Linux cgroup-v2/host budget guard for pure JP CI tests.

PID/mount selection follows reviewed decoder53f021's bounded selection only.
Unlike that decoder, a verified genuine hierarchy root may lack BOTH memory
files. Missing selected/nonroot accounting is always a specific refusal.
"""
import errno
import os
from pathlib import Path, PurePosixPath
import re

RESERVE=192*1024**2
TEST_ALLOWANCE=80*1024**2


class MemoryBudgetUnavailable(RuntimeError):
    pass


def refuse(code,detail):
    raise MemoryBudgetUnavailable('RESOURCE_HOLD['+code+']: '+detail)


def text(path,limit=65536,*,allow_absent=False):
    try:
        with Path(path).open(encoding='ascii') as stream:value=stream.read(limit+1)
    except FileNotFoundError as error:
        if error.errno!=errno.ENOENT:
            refuse('UNREADABLE_MEMORY_INPUT',str(path)+': unexpected missing-file errno='+str(error.errno))
        if allow_absent:return None
        refuse('MISSING_MEMORY_INPUT',str(path))
    except (OSError,UnicodeError) as error:
        refuse('UNREADABLE_MEMORY_INPUT',str(path)+': '+type(error).__name__)
    if len(value)>limit:refuse('OVERSIZE_MEMORY_INPUT',str(path))
    return value


def number(value,code):
    if not re.fullmatch(r'0|[1-9][0-9]{0,19}',value) or int(value)>2**64-1:
        refuse(code,'Expected one unsigned64bit integer')
    return int(value)


def mount_path(value):
    value=re.sub(r'\\([0-7]{3})',lambda found:chr(int(found[1],8)),value)
    if '\\' in value or '\x00' in value or not value.startswith('/'):
        refuse('BAD_CGROUP_MOUNT','Malformed mountinfo path')
    return value


def has_pid(directory,pid):
    rows=text(directory/'cgroup.procs').splitlines()
    if any(not re.fullmatch(r'0|[1-9][0-9]*',row) for row in rows):
        refuse('BAD_CGROUP_PROCS','Malformed PID accounting')
    return str(pid) in rows


def selected_group(mountpoint,mountroot,membership,pid):
    try:mountpoint=Path(mountpoint).resolve(strict=True)
    except (OSError,RuntimeError):refuse('UNRESOLVED_CGROUP_MOUNT',str(mountpoint))
    try:
        relative=PurePosixPath(membership).relative_to(PurePosixPath(mountroot))
        if '..' not in PurePosixPath(mountroot).parts:
            candidate=mountpoint.joinpath(*relative.parts).resolve(strict=True)
            candidate.relative_to(mountpoint)
            if has_pid(candidate,pid):return candidate,mountpoint,True
    except (OSError,ValueError,RuntimeError) as error:
        if isinstance(error,MemoryBudgetUnavailable):raise
    # Namespace / or /.. mount roots need actual PID ownership, not a guessed
    # cgroupfs-root path. Never follow symlink directories or scan above mount.
    stack,matches,visited=[(mountpoint,0)],[],0
    while stack:
        directory,depth=stack.pop();visited+=1
        if visited>256 or depth>16:refuse('CGROUP_SCAN_BOUND','Visible hierarchy exceeds bounded support')
        if has_pid(directory,pid):matches.append(directory)
        try:
            with os.scandir(directory) as entries:
                children=[]
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        children.append(Path(entry.path))
                        if len(children)+len(stack)+visited>256:refuse('CGROUP_SCAN_BOUND','Visible hierarchy exceeds bounded support')
        except OSError:refuse('UNREADABLE_CGROUP_HIERARCHY',str(directory))
        if len(children)+len(stack)+visited>256:refuse('CGROUP_SCAN_BOUND','Visible hierarchy exceeds bounded support')
        stack.extend((child,depth+1) for child in children)
    if len(matches)!=1:refuse('CGROUP_PID_NOT_UNIQUE','Actual PID missing or ambiguous in visible hierarchy')
    return matches[0],mountpoint,False


def verified_root_controller(directory):
    available=text(directory/'cgroup.controllers',allow_absent=True)
    enabled=text(directory/'cgroup.subtree_control',allow_absent=True)
    kind=text(directory/'cgroup.type',allow_absent=True)
    if available is None or enabled is None:
        refuse('UNPROVEN_HIERARCHY_ROOT','Root controller availability/enabling is absent')
    for raw in (available,enabled):
        words=raw.split()
        if len(words)!=len(set(words)) or any(not re.fullmatch(r'[a-z][a-z0-9_]*',word) for word in words):
            refuse('UNPROVEN_HIERARCHY_ROOT','Malformed root controller context')
    if 'memory' not in available.split() or 'memory' not in enabled.split():
        refuse('UNPROVEN_HIERARCHY_ROOT','Root memory controller is not available and enabled')
    if kind is not None and kind.strip()!='domain':
        refuse('UNPROVEN_HIERARCHY_ROOT','Optional root cgroup.type must be domain')
    return {'available_controllers':available.split(),'enabled_controllers':enabled.split(),
        'cgroup_type':None if kind is None else kind.strip()}


def sample_context(directory):
    result={'path':str(directory)[:256]}
    for name in ('memory.max','memory.current','cgroup.controllers','cgroup.subtree_control','cgroup.type'):
        try:
            raw=text(directory/name,4096,allow_absent=True)
            result[name]={'errno':'ENOENT'} if raw is None else {'raw':raw[:128],'truncated':len(raw)>128}
        except MemoryBudgetUnavailable as error:result[name]={'sampling_error':str(error)[:256]}
    return result


def sample_proc(diagnostic,meminfo_path,cgroup_path,mountinfo_path,pid):
    diagnostic['pid']=pid;diagnostic['sampling_scope']='Read-only context; not a substitute for budget gates'
    for key,path,limit in [('proc_self_cgroup',cgroup_path,65536),('cgroup2_mountinfo',mountinfo_path,1024*1024),('host_MemAvailable',meminfo_path,65536)]:
        try:
            raw=text(path,limit)
            if key=='cgroup2_mountinfo':
                rows=[line for line in raw.splitlines() if ' - cgroup2 ' in line]
                diagnostic[key]=[line[:256] for line in rows[-16:]]
                diagnostic[key+'_truncated']=len(rows)>16 or any(len(line)>256 for line in rows)
            elif key=='host_MemAvailable':diagnostic[key]=[line[:128] for line in raw.splitlines() if line.startswith('MemAvailable:')][:4]
            else:diagnostic[key]=raw[:1024];diagnostic[key+'_truncated']=len(raw)>1024
        except MemoryBudgetUnavailable as error:diagnostic[key]={'sampling_error':str(error)[:256]}


def memory_snapshot(*,meminfo_path='/proc/meminfo',cgroup_path='/proc/self/cgroup',
        mountinfo_path='/proc/self/mountinfo',pid=None,diagnostic=None):
    pid=os.getpid() if pid is None else pid
    if diagnostic is not None:sample_proc(diagnostic,meminfo_path,cgroup_path,mountinfo_path,pid)
    if type(pid) is not int or pid<=0:refuse('BAD_PROCESS_IDENTITY','Positive exact PID required')
    host=[line for line in text(meminfo_path).splitlines() if line.startswith('MemAvailable:')]
    if len(host)!=1 or (found:=re.fullmatch(r'MemAvailable:\s+([0-9]+) kB',host[0])) is None:
        refuse('BAD_HOST_MEMAVAILABLE','Expected exactly one valid MemAvailable kB row')
    host_bytes=number(found[1],'BAD_HOST_MEMAVAILABLE')*1024
    if host_bytes>2**64-1:refuse('BAD_HOST_MEMAVAILABLE','Host byte count overflows uint64')
    raw_membership=text(cgroup_path)
    memberships=[row[3:] for row in raw_membership.splitlines() if row.startswith('0::')]
    if len(memberships)!=1:refuse('BAD_CGROUP_MEMBERSHIP','Expected exactly one unified membership')
    membership=memberships[0]
    if not membership.startswith('/') or (membership!='/' and any(part in ('','.','..') for part in membership[1:].split('/'))):
        refuse('BAD_CGROUP_MEMBERSHIP','Unsafe unified membership path')
    raw_mounts=text(mountinfo_path,1024*1024);mounts=[]
    for line in raw_mounts.splitlines():
        before,separator,after=line.partition(' - ')
        if separator and after.split() and after.split()[0]=='cgroup2':
            fields=before.split()
            if len(fields)<6:refuse('BAD_CGROUP_MOUNT','Incomplete cgroup2 mount record')
            root,point=mount_path(fields[3]),mount_path(fields[4])
            if (str(PurePosixPath(point))!=point or '..' in PurePosixPath(point).parts
                    or (root!='/..' and (str(PurePosixPath(root))!=root or '..' in PurePosixPath(root).parts))):
                refuse('BAD_CGROUP_MOUNT','Unsafe cgroup2 mount path')
            if (root,point) in mounts:refuse('BAD_CGROUP_MOUNT','Duplicate visible cgroup2 mount')
            mounts.append((root,point))
    if not mounts or len(mounts)>32:refuse('UNSUPPORTED_CGROUP_MOUNTS','Need1to32 visible unified mounts')
    headrooms=[host_bytes];constraints=[];root_exemptions=[]
    for root,point in mounts:
        if diagnostic is not None:
            context={'mount_root':root[:256],'mounted_root':sample_context(Path(point))}
            diagnostic['current_mount']=context
        selected,mounted_root,direct=selected_group(point,root,membership,pid)
        if diagnostic is not None:context.update(selected=sample_context(selected),direct_own_pid_mapping=direct)
        directory=selected;checked_nonroot=0
        while True:
            maximum=text(directory/'memory.max',allow_absent=True)
            current=text(directory/'memory.current',allow_absent=True)
            if diagnostic is not None:context['accounting_cursor']={'path':str(directory)[:256],
                'memory.max':None if maximum is None else maximum[:64],
                'memory.current':None if current is None else current[:64],'checked_nonroot':checked_nonroot}
            if maximum is None or current is None:
                if (maximum is None and current is None and directory==mounted_root
                        and root=='/' and direct and checked_nonroot>0):
                    controller=verified_root_controller(directory)
                    root_exemptions.append({'path':str(directory),'accounting_absence':'both_ENOENT',
                        'direct_own_pid_mapping':direct,'checked_nonroot':checked_nonroot,'controller':controller})
                else:refuse('MISSING_CGROUP_ACCOUNTING','Required memory.max/current absent at '+str(directory))
            else:
                maximum=maximum.strip();used=number(current.strip(),'BAD_CGROUP_CURRENT')
                remaining=None if maximum=='max' else max(0,number(maximum,'BAD_CGROUP_MAX')-used)
                constraints.append({'path':str(directory),'memory_max':maximum,'memory_current':used,'available_bytes':remaining})
                if remaining is not None:headrooms.append(remaining)
                if directory!=mounted_root:checked_nonroot+=1
            if directory==mounted_root:break
            directory=directory.parent
    if text(cgroup_path)!=raw_membership or text(mountinfo_path,1024*1024)!=raw_mounts:
        refuse('CGROUP_MAPPING_CHANGED','Membership or mount mapping changed during check')
    if diagnostic is not None:
        diagnostic.update(computed_available_bytes=min(headrooms),host_MemAvailable_bytes=host_bytes)
        finite=[row for row in constraints if row['available_bytes'] is not None]
        if finite:
            limiting=min(finite,key=lambda row:row['available_bytes'])
            diagnostic['minimum_visible_constraint']={**limiting,'path':limiting['path'][:256]}
    return {'available_bytes':min(headrooms),'host_MemAvailable_bytes':host_bytes,
        'visible_constraints':constraints,'verified_hierarchy_root_without_accounting':root_exemptions,
        'scope':'Conservative host and visible cgroup-v2 own/ancestor headroom only'}


def require_headroom(snapshot,*,allowance=TEST_ALLOWANCE):
    if snapshot['available_bytes']<RESERVE+allowance:
        refuse('INSUFFICIENT_VISIBLE_MEMORY',f'{RESERVE} reserve + {allowance} allowance required; available={snapshot["available_bytes"]}')

"""Native-Home-only owned game cleanup; no observer or Frida dependency.

Post-stop proof follows the accepted native_download_driver
stop_owned_download_game contract: a fresh strict native ps PID column must
omit the original owned PID. A missing/malformed /proc stat is never absence.
The frozen SHORT helper and its cleanup policy remain unchanged.
"""
import subprocess
import time

from jp_capture_guard import PACKAGE, StopCapture, digest
from jp_short_capture import durable, pidof


def process_list_contains_pid(raw,pid):
    """Accept only a complete-looking process list with one valid PID column."""
    lines=raw.splitlines()
    if not lines or lines[0].split().count('PID')!=1:
        raise StopCapture('Malformed cleanup process-list header')
    column=lines[0].split().index('PID');rows=[line.split() for line in lines[1:] if line.strip()]
    if not rows or any(len(row)<=column or not row[column].isdigit() or int(row[column])<=0 for row in rows):
        raise StopCapture('Malformed cleanup process-list PID rows')
    return any(row[column]==str(pid) for row in rows)


def stop_owned_game(device,identity,evidence,*,launch_attempted,clock=time.monotonic,
        pause=time.sleep,cleanup_deadline=None):
    """One lifetime-validated force-stop, then fixed<=5second fresh-PS proof."""
    started=clock();last_ps=None;success=False
    game_end=min(started+10,cleanup_deadline-18 if cleanup_deadline is not None else started+10)
    context={'identity':identity,'package':PACKAGE,'started_at':started,
        'force_stop_attempts':0,'poll_limit_seconds':5,'game_cleanup_deadline':game_end,'observations':[]}
    def timeout(maximum):
        left=game_end-clock()
        if left<=0:raise StopCapture('Game cleanup reserve exhausted before absence proof')
        return min(maximum,left)
    def processes(timeout):
        nonlocal last_ps
        last_ps=device.shell('ps','-A',timeout=timeout)
        return process_list_contains_pid(last_ps,identity['pid'])
    def process_identity(timeout):
        try:raw=device.adb('exec-out','cat','/proc/'+str(identity['pid'])+'/stat',raw=True,timeout=timeout).decode()
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired) as error:
            context['last_stat_read_error']={'class':type(error).__name__,'detail':str(error)[:512],'at':clock()}
            raise
        context['last_stat']={'raw':raw[:4096],'bytes':len(raw),'truncated':len(raw)>4096,
            'sha256':digest(raw.encode()),'at':clock()}
        try:
            fields=raw.rsplit(')',1)[1].split();context['last_stat']['state']=fields[0]
            observed={'pid':int(raw.split('(',1)[0].strip()),'start_ticks':fields[19]}
            if not observed['start_ticks'].isdigit():raise ValueError('Invalid startticks')
        except (ValueError,IndexError):raise StopCapture('Malformed cleanup process lifetime') from None
        return observed
    try:
        if identity is None:
            if not launch_attempted:
                context['status']='NOT_LAUNCHED_BY_THIS_RUN';success=True;return {'status':context['status']}
            if pidof(device,timeout=timeout(1)):
                raise StopCapture('Unknown post-launch game lifetime remains; owned container cleanup required')
            timeout(1)
            proof={'status':'NO_JP_PID_AFTER_LAUNCH_ATTEMPT','original_identity_unavailable':True}
            durable(evidence/'owned-game-stop-proof.json',proof);context['status']=proof['status'];success=True;return proof
        if processes(timeout(1)):
            observed=process_identity(timeout(1));context['before_signal_identity']=observed
            if observed!=identity:raise StopCapture('Refuse cleanup of changed owned game lifetime')
            current=pidof(device,timeout=timeout(1));context['before_signal_package_pid']=current
            if current!=str(identity['pid']):raise StopCapture('Owned package lifetime changed before force-stop')
            observed=process_identity(timeout(1));context['at_signal_identity']=observed
            if observed!=identity:raise StopCapture('Owned game lifetime changed at force-stop boundary')
            context['force_stop_attempts']=1
            try:
                device.shell('am','force-stop',PACKAGE,timeout=timeout(2));context['force_stop_returned']=True
            except (subprocess.CalledProcessError,subprocess.TimeoutExpired) as error:
                context['force_stop_returned']=False;context['force_stop_error']=type(error).__name__
            deadline=min(clock()+5,game_end);context['poll_deadline']=deadline
            def remaining():
                value=deadline-clock()
                if value<=0:raise StopCapture('Owned game lifetime absence was not proved within5seconds after force-stop')
                return min(1,value)
            while True:
                present=processes(remaining());sample={'at':clock(),'expected_PID_present':present}
                context['observations'].append(sample)
                if not present:
                    current=pidof(device,timeout=remaining());sample['package_pid']=current
                    if current:raise StopCapture('A changed JP lifetime remains; owned container cleanup required')
                    remaining();break
                # No post-stop stat read: a disappearing PID can return cat's
                # text with an adb success code. Only the next fresh ps can
                # prove absence, including after a stale still-present sample.
                pause(min(.1,remaining()))
        elif pidof(device,timeout=timeout(1)):
            raise StopCapture('A changed JP lifetime remains; owned container cleanup required')
        timeout(1)
        proof={'status':'OWNED_GAME_LIFETIME_ABSENT','identity':identity,
            'force_stop_attempts':context['force_stop_attempts'],
            'proof':'Fresh native ps -A PID column contains no original owned PID; current package PID is absent',
            'processes_sha256':digest((last_ps+'\n').encode())}
        durable(evidence/'owned-game-stop-proof.json',proof);context['status']=proof['status'];success=True;return proof
    except BaseException as error:
        context['failure']=type(error).__name__+': '+str(error);raise
    finally:
        context['finished_at']=clock();context['elapsed_seconds']=clock()-started
        psname='owned-game-stop-processes.txt' if success else 'owned-game-stop-failure-processes.txt'
        contextname='owned-game-cleanup-context.json' if success else 'owned-game-cleanup-failure.json'
        context['processes_file']=psname
        (evidence/psname).write_text(last_ps+'\n' if last_ps is not None else 'No process-list result returned; see cleanup context.\n')
        durable(evidence/contextname,context)

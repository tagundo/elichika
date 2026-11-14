"""Synthetic Linux VM/namespace layouts; no device, network, or cgroup mutation."""
import errno
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import capture_memory_budget as budget

MIB=1024**2
PID=4242


class Layout:
    def __init__(self,root,*,mountroot='/',membership='/user.slice/self.scope'):
        self.root=Path(root);self.mount=self.root/'visible cgroup';self.mount.mkdir()
        self.member=self.root/'membership';self.mountinfo=self.root/'mountinfo';self.meminfo=self.root/'meminfo'
        self.member.write_text('0::'+membership+'\n')
        encoded=str(self.mount).replace(' ','\\040')
        self.mountinfo.write_text(f'60 55 0:24 {mountroot} {encoded} rw - cgroup2 cgroup2 rw\n')
        self.meminfo.write_text('MemAvailable: 2097152 kB\n')
        self.group('',None,None)
        (self.mount/'cgroup.controllers').write_text('cpu memory pids\n')
        (self.mount/'cgroup.subtree_control').write_text('cpu memory\n')
        (self.mount/'cgroup.type').write_text('domain\n')
    def group(self,relative,maximum,current,*,pid=False):
        directory=self.mount/relative;directory.mkdir(parents=True,exist_ok=True)
        (directory/'cgroup.procs').write_text(str(PID)+'\n' if pid else '')
        for name,value in [('memory.max',maximum),('memory.current',current)]:
            if value is not None:(directory/name).write_text(str(value)+'\n')
            elif (directory/name).exists():(directory/name).unlink()
        return directory
    def standard(self,*,parent_max='max',parent_current=0,own_max='max',own_current=0):
        self.group('user.slice',parent_max,parent_current)
        self.group('user.slice/self.scope',own_max,own_current,pid=True)
        return self
    def snapshot(self,**kwargs):
        return budget.memory_snapshot(meminfo_path=self.meminfo,cgroup_path=self.member,mountinfo_path=self.mountinfo,pid=PID,**kwargs)


class MemoryBudgetTests(unittest.TestCase):
    def setUp(self):self.temporary=tempfile.TemporaryDirectory(prefix='owned-jp-memory-layout-');self.root=Path(self.temporary.name)
    def tearDown(self):self.temporary.cleanup()
    def refused(self,layout,code):
        with self.assertRaisesRegex(budget.MemoryBudgetUnavailable,'RESOURCE_HOLD\\['+code+'\\]'):layout.snapshot()

    def test_synthetic_VM_shape_root_pair_absent_nested_self_and_finite_parent(self):
        layout=Layout(self.root).standard(parent_max=512*MIB,parent_current=220*MIB,own_current=64*MIB)
        result=layout.snapshot()
        self.assertEqual(result['available_bytes'],292*MIB)
        proof=result['verified_hierarchy_root_without_accounting'][0]
        self.assertEqual(proof['path'],str(layout.mount))
        self.assertTrue(proof['direct_own_pid_mapping']);self.assertEqual(proof['checked_nonroot'],2)
        self.assertIn('memory',proof['controller']['enabled_controllers'])
        budget.require_headroom(result)
        diagnostic={};layout.snapshot(diagnostic=diagnostic)
        self.assertEqual(diagnostic['proc_self_cgroup'],'0::/user.slice/self.scope\n')
        self.assertTrue(diagnostic['current_mount']['direct_own_pid_mapping'])
        self.assertEqual(diagnostic['current_mount']['mounted_root']['memory.max']['errno'],'ENOENT')

    def test_own_finite_and_tighter_parent_both_enforced(self):
        layout=Layout(self.root).standard(parent_max=512*MIB,parent_current=300*MIB,own_max=1024*MIB,own_current=100*MIB)
        result=layout.snapshot();self.assertEqual(result['available_bytes'],212*MIB)
        with self.assertRaisesRegex(budget.MemoryBudgetUnavailable,'INSUFFICIENT_VISIBLE_MEMORY'):budget.require_headroom(result)
        budget.require_headroom(result,allowance=0)

    def test_host_available_is_minimum_not_memtotal_or_sum(self):
        layout=Layout(self.root).standard(parent_max=1024*MIB,parent_current=0)
        layout.meminfo.write_text('MemTotal: 999999999 kB\nMemFree: 99999999 kB\nMemAvailable: 307200 kB\n')
        self.assertEqual(layout.snapshot()['available_bytes'],300*MIB)

    def test_all_visible_groups_unlimited_uses_host_available(self):
        self.assertEqual(Layout(self.root).standard().snapshot()['available_bytes'],2*1024*MIB)

    def test_nonstandard_mountroot_direct_mapping(self):
        layout=Layout(self.root,mountroot='/tenant',membership='/tenant/work.scope')
        layout.group('',800*MIB,100*MIB);layout.group('work.scope',600*MIB,50*MIB,pid=True)
        self.assertEqual(layout.snapshot()['available_bytes'],550*MIB)

    def test_namespaced_slash_membership_is_selected_by_PID(self):
        layout=Layout(self.root,mountroot='/tenant/work.scope',membership='/')
        layout.group('',600*MIB,100*MIB,pid=True)
        self.assertEqual(layout.snapshot()['available_bytes'],500*MIB)

    def test_namespace_dotdot_mount_scans_actual_self_and_keeps_parent(self):
        layout=Layout(self.root,mountroot='/..',membership='/')
        layout.group('',512*MIB,100*MIB);layout.group('actual-self','max',10*MIB,pid=True)
        self.assertEqual(layout.snapshot()['available_bytes'],412*MIB)
        layout.group('',None,None)
        self.refused(layout,'MISSING_CGROUP_ACCOUNTING')

    def test_missing_selected_or_nonroot_parent_cannot_use_root_exception(self):
        layout=Layout(self.root).standard()
        layout.group('user.slice/self.scope',None,None,pid=True)
        self.refused(layout,'MISSING_CGROUP_ACCOUNTING')
        layout.group('user.slice/self.scope','max',0,pid=True);layout.group('user.slice',None,None)
        self.refused(layout,'MISSING_CGROUP_ACCOUNTING')

    def test_partial_root_accounting_is_refusal(self):
        layout=Layout(self.root).standard();layout.group('',None,0)
        self.refused(layout,'MISSING_CGROUP_ACCOUNTING')

    def test_selected_own_root_cannot_use_missing_root_exception(self):
        layout=Layout(self.root,membership='/');layout.group('',None,None,pid=True)
        self.refused(layout,'MISSING_CGROUP_ACCOUNTING')

    def test_scan_based_mapping_cannot_use_missing_root_exception(self):
        layout=Layout(self.root,membership='/not-the-visible-process-path').standard()
        self.refused(layout,'MISSING_CGROUP_ACCOUNTING')

    def test_missing_or_disabled_controller_context_cannot_use_root_exception(self):
        layout=Layout(self.root).standard()
        (layout.mount/'cgroup.controllers').unlink()
        self.refused(layout,'UNPROVEN_HIERARCHY_ROOT')
        (layout.mount/'cgroup.controllers').write_text('cpu memory\n')
        (layout.mount/'cgroup.subtree_control').write_text('cpu\n')
        self.refused(layout,'UNPROVEN_HIERARCHY_ROOT')

    def test_optional_root_type_must_be_domain_if_present(self):
        layout=Layout(self.root).standard()
        (layout.mount/'cgroup.type').write_text('domain threaded\n')
        self.refused(layout,'UNPROVEN_HIERARCHY_ROOT')
        (layout.mount/'cgroup.type').unlink()
        self.assertEqual(layout.snapshot()['available_bytes'],2*1024*MIB)

    def test_root_read_errors_are_not_treated_as_ENOENT(self):
        layout=Layout(self.root).standard();original=Path.open
        cases=[(layout.mount/'memory.max',PermissionError('fixture permission denied')),
            (layout.mount/'cgroup.controllers',PermissionError('fixture permission denied')),
            (layout.mount/'memory.max',FileNotFoundError(errno.EIO,'synthetic non-ENOENT'))]
        for target,error in cases:
            def denied(path,*args,**kwargs):
                if path==target:raise error
                return original(path,*args,**kwargs)
            with self.subTest(target=target),patch.object(Path,'open',denied):
                self.refused(layout,'UNREADABLE_MEMORY_INPUT')

    def test_malformed_present_limit_or_current_is_specific_refusal(self):
        layout=Layout(self.root).standard()
        for maximum,current,code in [('-1',0,'BAD_CGROUP_MAX'),('max','-1','BAD_CGROUP_CURRENT'),
                ('1024junk',0,'BAD_CGROUP_MAX'),(2**64,0,'BAD_CGROUP_MAX')]:
            layout.group('user.slice',maximum,current)
            with self.subTest(maximum=maximum,current=current):self.refused(layout,code)

    def test_current_above_limit_clamps_to_zero_and_refuses_budget(self):
        layout=Layout(self.root).standard(parent_max=1,parent_current=2)
        result=layout.snapshot();self.assertEqual(result['available_bytes'],0)
        with self.assertRaisesRegex(budget.MemoryBudgetUnavailable,'INSUFFICIENT_VISIBLE_MEMORY'):budget.require_headroom(result)

    def test_duplicate_or_unsafe_membership_and_mount_are_refused(self):
        layout=Layout(self.root).standard()
        for raw in ('0::/one\n0::/two\n','0::/../outside\n','no unified membership\n'):
            layout.member.write_text(raw);self.refused(layout,'BAD_CGROUP_MEMBERSHIP')
        layout.member.write_text('0::/user.slice/self.scope\n')
        raw=layout.mountinfo.read_text();layout.mountinfo.write_text(raw+raw)
        self.refused(layout,'BAD_CGROUP_MOUNT')

    def test_bad_host_memavailable_is_not_ignored(self):
        layout=Layout(self.root).standard()
        for raw in ('MemAvailable: -1 kB\n','MemAvailable: 100 MB\n',
                'MemAvailable: 100 kB\nMemAvailable: bad kB\n','MemFree: 999999 kB\n'):
            layout.meminfo.write_text(raw);self.refused(layout,'BAD_HOST_MEMAVAILABLE')

    def test_actual_PID_missing_or_duplicate_is_refused(self):
        layout=Layout(self.root,mountroot='/..',membership='/')
        layout.group('',500*MIB,0)
        self.refused(layout,'CGROUP_PID_NOT_UNIQUE')
        layout.group('one','max',0,pid=True);layout.group('two','max',0,pid=True)
        self.refused(layout,'CGROUP_PID_NOT_UNIQUE')

    def test_membership_change_is_refused(self):
        layout=Layout(self.root).standard();original=budget.text;reads=0
        def changing(path,*args,**kwargs):
            nonlocal reads
            value=original(path,*args,**kwargs)
            if Path(path)==layout.member:
                reads+=1
                if reads==2:return '0::/moved\n'
            return value
        with patch.object(budget,'text',side_effect=changing):self.refused(layout,'CGROUP_MAPPING_CHANGED')

    def test_thresholds_remain_exact_272_before_and_192_after_MiB(self):
        budget.require_headroom({'available_bytes':272*MIB})
        budget.require_headroom({'available_bytes':192*MIB},allowance=0)
        for available,allowance in [(272*MIB-1,80*MIB),(192*MIB-1,0)]:
            with self.assertRaises(budget.MemoryBudgetUnavailable):budget.require_headroom({'available_bytes':available},allowance=allowance)
        from verify_jp_capture import memory_hold
        layout=Layout(self.root).standard();diagnostic={};layout.snapshot(diagnostic=diagnostic)
        for suffix,extra in [('normal',{}),('bounded',{'oversized_synthetic_sample':'x'*70000})]:
            destination=self.root/(suffix+'-hold.json')
            with patch('sys.stderr',io.StringIO()):
                self.assertEqual(memory_hold(destination,{**diagnostic,**extra},
                    budget.MemoryBudgetUnavailable('RESOURCE_HOLD[SYNTHETIC_FIXTURE]: budget unavailable'),
                    'before-pure-tests'),1)
            self.assertLessEqual(destination.stat().st_size,65536)
            saved=json.loads(destination.read_text())
            self.assertEqual(saved['phase'],'before-pure-tests')
            self.assertEqual(saved['memory_diagnostic']['current_mount']['selected']['path'],
                str(layout.mount/'user.slice/self.scope'))
            self.assertTrue(saved['memory_diagnostic']['cgroup2_mountinfo'])
            if extra:self.assertTrue(saved['memory_diagnostic']['truncated'])


if __name__=='__main__':unittest.main(verbosity=2)

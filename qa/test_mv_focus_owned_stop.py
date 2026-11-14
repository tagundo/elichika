"""Host-only strict stop proof/fallback; no real device or Docker is invoked."""
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from native_mv_focus import cleanup_mv_observers
from unity_main_tid import TidProofError

ABSENT='USER PID NAME\nu0_a2 20 other\n'
PRESENT='USER PID NAME\nu0_a1 10 owned\nu0_a2 20 other\n'


class OwnedObserverStopTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.device=SimpleNamespace(shell=Mock(return_value=ABSENT),adb=Mock())
        self.report={'primary_failure_recorded':True,'error':'primary retained','traceback':'retained trace'}
        self.context={'device':self.device,'args':SimpleNamespace(evidence=Path(self.temporary.name)),
                      'report':self.report,'package':'com.klab.lovelive.allstars.global'}
        self.expected={'pid':10,'start_ticks':'100'};self.session=SimpleNamespace(detach=Mock())
        self.rpc=lambda fn,**kwargs:fn()

    def clean(self,sessions=None):
        return cleanup_mv_observers(self.context,self.expected,[self.session] if sessions is None else sessions,self.rpc)

    def stat(self,start):return ('10 (UnityMain) '+' '.join(['S']+['0']*18+[start]+['0']*3)).encode()

    def test_fresh_ps_absence_records_unique_proof_before_detach(self):
        with patch('native_mv_focus.subprocess.run') as docker:self.assertTrue(self.clean())
        docker.assert_not_called();self.device.adb.assert_not_called();self.session.detach.assert_called_once()
        proof=self.report['owned_download_stop_proof']
        self.assertEqual(proof['before_identity'],self.expected)
        self.assertEqual(proof['process_list'],'mv-owned-stop-processes.txt')
        self.assertTrue((self.context['args'].evidence/proof['process_list']).is_file())

    def test_matching_owned_lifetime_is_stopped_then_fresh_ps_proves_absence(self):
        self.device.shell.side_effect=[PRESENT,'',ABSENT];self.device.adb.return_value=self.stat('100')
        with patch('native_mv_focus.subprocess.run') as docker:self.assertTrue(self.clean())
        docker.assert_not_called();self.session.detach.assert_called_once()
        self.assertEqual(self.device.shell.call_args_list[1].args,('am','force-stop',self.context['package']))
        self.assertTrue(self.report['owned_game_stopped_before_observer_unload'])

    def test_changed_lifetime_is_not_stopped_or_interpreted_as_absence(self):
        self.device.shell.return_value=PRESENT;self.device.adb.return_value=self.stat('200')
        with patch('native_mv_focus.subprocess.run') as docker:self.assertFalse(self.clean([]))
        docker.assert_not_called();self.session.detach.assert_not_called()
        self.assertEqual(self.device.shell.call_count,1)
        self.assertEqual(self.report['mv_observer_cleanup_errors'][0]['type'],'AssertionError')
        self.assertEqual(self.report['error'],'primary retained')

    def test_tid_proof_error_requires_positive_fixed_container_proof_before_detach(self):
        self.device.shell.return_value=PRESENT;self.device.adb.side_effect=TidProofError('host-only invalid proc proof')
        events=[];self.session.detach.side_effect=lambda:events.append('detach')
        def docker(command,**kwargs):
            self.assertEqual(command[-1],'original-client-qa');events.append(command[1])
            return SimpleNamespace(returncode=0,stdout='false\n' if command[1]=='inspect' else '')
        with patch('native_mv_focus.subprocess.run',side_effect=docker):self.assertTrue(self.clean())
        self.assertEqual(events,['stop','inspect','detach'])
        self.assertEqual(self.report['mv_observer_cleanup_errors'][0]['type'],'TidProofError')
        self.assertNotIn('owned_download_stop_proof',self.report)
        self.assertTrue(self.report['owned_disposable_container_stop_fallback'])

    def test_failed_or_running_or_unreadable_container_never_detaches(self):
        variants=[None,SimpleNamespace(returncode=1,stdout=''),SimpleNamespace(returncode=0,stdout='true\n'),
                  SimpleNamespace(returncode=0,stdout=''),OSError('host-only inspect error'),
                  subprocess.TimeoutExpired('host-only inspect',5)]
        for second in variants:
            with self.subTest(second=second):
                self.device.shell.return_value='malformed process list'
                self.session.detach.reset_mock();self.report.pop('owned_disposable_container_stop_fallback',None)
                commands=[SimpleNamespace(returncode=1)] if second is None else [SimpleNamespace(returncode=0),second]
                with patch('native_mv_focus.subprocess.run',side_effect=commands):
                    with self.assertRaisesRegex(RuntimeError,'Could not prove owned game/container stopped'):self.clean()
                self.session.detach.assert_not_called()
                self.assertFalse(self.report['owned_game_stopped_before_observer_unload'])
                self.assertFalse(self.report['owned_disposable_container_stop_fallback'])
                self.assertEqual(self.report['error'],'primary retained')

    def test_no_sessions_records_stop_error_without_container_or_primary_replacement(self):
        self.device.shell.side_effect=OSError('host-only process-list error')
        with patch('native_mv_focus.subprocess.run') as docker:self.assertFalse(self.clean([]))
        docker.assert_not_called();self.session.detach.assert_not_called()
        self.assertEqual(self.report['error'],'primary retained')
        self.assertEqual(self.report['traceback'],'retained trace')
        self.assertEqual(self.report['mv_observer_cleanup_errors'][0]['type'],'OSError')


if __name__=='__main__':unittest.main()

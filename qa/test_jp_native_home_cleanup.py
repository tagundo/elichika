"""Pure fake-device cleanup regressions; no actual process is signalled."""
import json
from pathlib import Path
import tempfile
import unittest

from jp_capture_guard import StopCapture, digest
from jp_native_home_cleanup import process_list_contains_pid, stop_owned_game


OWNED={'pid':1917,'start_ticks':'269179'}
PRESENT='USER PID NAME\nroot 1 init\nu0_a1 1917 com.klab.lovelive.allstars\n'
ABSENT='USER PID NAME\nroot 1 init\n'


def stat(ticks='269179'):
    return ('1917 (owned game) S '+'0 '*18+ticks+' 0\n').encode()


class Clock:
    def __init__(self):self.now=10.0
    def __call__(self):return self.now
    def pause(self,seconds):self.now+=seconds


class Device:
    def __init__(self,processes=None,stats=None,before='1917',after=''):
        self.processes=list(processes or [PRESENT,PRESENT,ABSENT])
        self.stats=list(stats or [stat(),stat()]);self.before=before;self.after=after
        self.stopped=False;self.signals=0;self.stat_reads=0;self.ps_reads=0
    def shell(self,*args,timeout):
        if args==('ps','-A'):
            self.ps_reads+=1
            return self.processes.pop(0) if len(self.processes)>1 else self.processes[0]
        if args[:2]==('pidof','-s'):return self.after if self.stopped else self.before
        if args[:2]==('am','force-stop'):
            self.signals+=1;self.stopped=True;return ''
        raise AssertionError(args)
    def adb(self,*args,raw,timeout):
        self.stat_reads+=1
        if self.stopped:return b'cat: /proc/1917/stat: No such file or directory\n'
        return self.stats.pop(0)


class NativeHomeCleanupTests(unittest.TestCase):
    def run_cleanup(self,device,identity=OWNED,launch_attempted=True,clock=None):
        clock=clock or Clock()
        with tempfile.TemporaryDirectory() as directory:
            evidence=Path(directory)
            try:
                proof=stop_owned_game(device,identity,evidence,launch_attempted=launch_attempted,
                    clock=clock,pause=clock.pause,cleanup_deadline=130.0)
            finally:
                self.outputs={path.name:path.read_text() for path in evidence.iterdir()}
        return proof,clock

    def test_disappearing_poststop_stat_is_not_read_and_fresh_ps_proves_absence(self):
        device=Device();proof,clock=self.run_cleanup(device)
        self.assertEqual(proof['status'],'OWNED_GAME_LIFETIME_ABSENT')
        self.assertEqual(device.signals,1);self.assertEqual(device.stat_reads,2)
        self.assertEqual(device.ps_reads,3)
        self.assertEqual(proof['identity'],OWNED)
        self.assertEqual(proof['processes_sha256'],digest((ABSENT+'\n').encode()))
        context=json.loads(self.outputs['owned-game-cleanup-context.json'])
        self.assertEqual([row['expected_PID_present'] for row in context['observations']],[True,False])

    def test_lingering_or_reused_pid_never_becomes_absence_and_poll_stays_bounded(self):
        device=Device(processes=[PRESENT]);clock=Clock()
        with self.assertRaisesRegex(StopCapture,'within5seconds'):
            self.run_cleanup(device,clock=clock)
        self.assertLessEqual(clock.now,15.000001)
        self.assertEqual(device.signals,1);self.assertEqual(device.stat_reads,2)
        self.assertNotIn('owned-game-stop-proof.json',self.outputs)

    def test_malformed_poststop_process_list_is_not_absence(self):
        for malformed in ('USER NAME\nroot init\n','USER PID NAME\n','USER PID NAME\nu0_a1 ??? game\n'):
            device=Device(processes=[PRESENT,malformed])
            with self.subTest(malformed=malformed),self.assertRaisesRegex(StopCapture,'Malformed cleanup process-list'):
                self.run_cleanup(device)
            self.assertEqual(device.signals,1)
            self.assertNotIn('owned-game-stop-proof.json',self.outputs)

    def test_changed_startticks_at_either_prestop_check_refuses_without_signal(self):
        for values in ([stat('269180')],[stat(),stat('269180')]):
            device=Device(stats=values)
            with self.subTest(values=values),self.assertRaisesRegex(StopCapture,'changed'):
                self.run_cleanup(device)
            self.assertEqual(device.signals,0)

    def test_malformed_prestop_stat_is_not_absence(self):
        device=Device(stats=[b'cat: /proc/1917/stat: No such file or directory\n'])
        with self.assertRaisesRegex(StopCapture,'Malformed cleanup process lifetime'):
            self.run_cleanup(device)
        self.assertEqual(device.signals,0)
        self.assertNotIn('owned-game-stop-proof.json',self.outputs)

    def test_changed_package_pid_before_or_after_signal_refuses(self):
        device=Device(before='1918')
        with self.assertRaisesRegex(StopCapture,'changed before force-stop'):self.run_cleanup(device)
        self.assertEqual(device.signals,0)
        device=Device(after='1918')
        with self.assertRaisesRegex(StopCapture,'changed JP lifetime'):self.run_cleanup(device)
        self.assertEqual(device.signals,1)
        self.assertNotIn('owned-game-stop-proof.json',self.outputs)

    def test_no_owned_launch_and_already_absent_paths_do_not_signal(self):
        device=Device()
        proof,_=self.run_cleanup(device,identity=None,launch_attempted=False)
        self.assertEqual(proof['status'],'NOT_LAUNCHED_BY_THIS_RUN');self.assertEqual(device.signals,0)
        device=Device(processes=[ABSENT],before='')
        proof,_=self.run_cleanup(device)
        self.assertEqual(proof['status'],'OWNED_GAME_LIFETIME_ABSENT');self.assertEqual(device.signals,0)
        self.assertEqual(device.stat_reads,0)


if __name__=='__main__':unittest.main()

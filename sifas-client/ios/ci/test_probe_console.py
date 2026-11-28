"""Exercise the real terminal transport without an Apple Simulator."""
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from probe_console import ProbeConsole
from simulator_diagnostics import console_pid_candidate


class ProbeConsoleTests(unittest.TestCase):
    def test_launch_pid_is_visible_while_stdio_child_is_still_running(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'console.txt'
            with log.open('wb', buffering=0) as output, ProbeConsole(output) as console:
                # No -u and no flush: a regular-file stdout leaves this buffered.
                code = ('import os,sys,time; assert os.isatty(1); '
                        'print("org.elichika.simulator-probe: 12345"); time.sleep(5)')
                process = subprocess.Popen([sys.executable, '-B', '-c', code], stdout=console.slave,
                                           stderr=subprocess.STDOUT)
                console.start()
                try:
                    deadline = time.monotonic() + 2
                    while console_pid_candidate(log) is None and time.monotonic() < deadline:
                        console.check()
                        time.sleep(.01)
                    self.assertIsNone(process.poll())
                    self.assertEqual(console_pid_candidate(log), 12345)
                finally:
                    process.terminate()
                    process.wait(timeout=2)

    def test_drain_continues_while_main_thread_waits_and_log_cap_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'console.txt'
            with log.open('wb', buffering=0) as output, ProbeConsole(output) as console:
                console.MAX_LOG_BYTES = 4096
                code = 'import os; data=b"a"*4096; [os.write(1,data) for _ in range(512)]'
                process = subprocess.Popen([sys.executable, '-B', '-c', code], stdout=console.slave,
                                           stderr=subprocess.STDOUT)
                console.start()
                # No parent drain/pump: real protocol calls also block this thread.
                self.assertEqual(process.wait(timeout=5), 0)
                console.check()
                self.assertTrue(console.truncated)
                self.assertEqual(log.stat().st_size, 4096)

    def test_early_popen_failure_closes_both_owned_terminal_descriptors(self):
        with tempfile.TemporaryFile() as output:
            with ProbeConsole(output) as console:
                master, slave = console.master, console.slave
            import os
            for fd in (master, slave):
                with self.assertRaises(OSError):
                    os.fstat(fd)


if __name__ == '__main__':
    unittest.main()

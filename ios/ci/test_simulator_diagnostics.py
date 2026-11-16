"""Synthetic ownership/boundary tests; no actual Simulator evidence is produced."""
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import simulator_diagnostics as diagnostics
from run_simulator import retain_failure

DEVICE = '12345678-1234-1234-1234-123456789abc'
PID = 4242


def app_fixture(root):
    app = root / DEVICE / 'data/Containers/Bundle/Application/app/Probe.app'
    app.mkdir(parents=True)
    (app/'Info.plist').write_bytes(plistlib.dumps(dict(CFBundleIdentifier=diagnostics.BUNDLE,
        CFBundleExecutable='ElichikaSimulatorProbe')))
    (app/'ElichikaSimulatorProbe').write_bytes(b'unit fixture, not a Mach-O')
    return app.resolve()


def response(text='', code=0):
    return dict(text=text, returncode=code, truncated=False, timed_out=False)


class SimulatorDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        self.sampled=False
        self.change_identity=False
        self.match=True

    def command(self, args, *, timeout=None):
        self.calls.append(args)
        if 'get_app_container' in args:
            return response(str(self.app)+'\n')
        if 'launchctl' in args:
            return response(f'{PID}\t0\tUIKitApplication:{diagnostics.BUNDLE}[abc]\n' if self.match else '')
        if args[0]=='ps':
            at='11:13:00' if self.sampled and self.change_identity else '11:12:00'
            return response(f'{PID} Mon Nov 16 {at} 2026 S 1.0 0.5 64000 {self.app}/ElichikaSimulatorProbe\n')
        if args[0]=='sample':
            self.sampled=True
            return response('Sample of ElichikaSimulatorProbe\n0 main\n')
        return response('ELICHIKA_SIMULATOR_STARTUP main_entry\nAuthorization: Bearer private-value\n')

    def test_pipe_output_and_runtime_are_bounded_without_app_signals(self):
        row=diagnostics.bounded_command([sys.executable,'-c','print("x"*100000,flush=True)'],timeout=2,cap=1024)
        self.assertLessEqual(len(row['text'].encode()),1024)
        self.assertTrue(row['truncated'])
        started=time.monotonic()
        row=diagnostics.bounded_command([sys.executable,'-c','import time;time.sleep(2)'],timeout=.05)
        self.assertTrue(row['timed_out'])
        self.assertLess(time.monotonic()-started,1.5)

    def test_owned_device_container_label_executable_and_start_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            self.app=app_fixture(Path(directory))
            row=diagnostics.process_identity(DEVICE,self.app,lambda a,s:self.command(a,timeout=s))
            self.assertEqual(row['pid'],PID)
            self.assertEqual(row['start'],'Mon Nov 16 11:12:00 2026')
            self.match=False
            self.assertIsNone(diagnostics.process_identity(DEVICE,self.app,lambda a,s:self.command(a,timeout=s)))
            for mode in ('wrong-container','wrong-executable','ambiguous-label','lookalike-bundle'):
                self.match=True
                def invoke(args, seconds):
                    row=self.command(args,timeout=seconds)
                    if mode=='wrong-container' and 'get_app_container' in args:row['text']=str(self.app.parent/'Other.app')
                    if mode=='wrong-executable' and args[0]=='ps':row['text']=row['text'].replace('/Probe.app/','/Other.app/')
                    if mode=='ambiguous-label' and 'launchctl' in args:row['text']+=f'5555 0 UIKitApplication:{diagnostics.BUNDLE}[other]\n'
                    if mode=='lookalike-bundle' and 'launchctl' in args:row['text']=row['text'].replace(diagnostics.BUNDLE,diagnostics.BUNDLE+'-unowned')
                    return row
                with self.subTest(mode=mode):
                    self.assertIsNone(diagnostics.process_identity(DEVICE,self.app,invoke))

    def test_sample_requires_identity_before_and_after_and_never_trusts_console_pid(self):
        for match,changed in ((True,False),(False,False),(True,True)):
            with self.subTest(match=match,changed=changed), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);self.app=app_fixture(root);out=root/'evidence';out.mkdir()
                self.calls=[];self.sampled=False;self.match=match;self.change_identity=changed
                with patch.object(diagnostics,'bounded_command',side_effect=self.command), \
                        patch.object(diagnostics,'owned_crashes',return_value=[]):
                    row=diagnostics.capture_owned_diagnostics(out,'iPad-launch-1',DEVICE,self.app,time.time()-60)
                samples=[args for args in self.calls if args[0]=='sample']
                self.assertEqual(len(samples),int(match))
                if match and not changed:
                    self.assertTrue(row['process_identity_revalidated_after_sample'])
                    self.assertTrue((out/row['sample']['file']).is_file())
                else:
                    self.assertNotIn('sample',row)
                    self.assertFalse(any(out.glob('*owned-app-sample*')))
                self.assertTrue(row['diagnostic_only_not_readiness'])
                self.assertTrue(row['original_failure_unchanged'])
                self.assertFalse(any(args[0] in ('kill','killall','pkill') or 'terminate' in args or 'launch' in args
                                     for args in self.calls))
                log=(out/row['device_log']['file']).read_text()
                self.assertIn('ELICHIKA_SIMULATOR_STARTUP main_entry',log)
                self.assertNotIn('private-value',log)

    def test_device_path_and_executable_symlinks_are_rejected_before_sampling(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.app=app_fixture(root);out=root/'evidence';out.mkdir()
            with self.assertRaises(ValueError):
                diagnostics.capture_owned_diagnostics(out,'x','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',self.app,time.time())
            binary=self.app/'ElichikaSimulatorProbe';binary.unlink();binary.symlink_to('/bin/sh')
            with self.assertRaises(ValueError):
                diagnostics.process_identity(DEVICE,self.app,lambda a,s:self.command(a,timeout=s))
            self.assertFalse(self.sampled)

    def test_crash_report_requires_exact_owned_executable_bundle_pid_and_fresh_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.app=app_fixture(root);reports=root/'reports';reports.mkdir()
            report=dict(procName='ElichikaSimulatorProbe',procPath=str(self.app/'ElichikaSimulatorProbe'),
                        pid=PID,bundleInfo={'CFBundleIdentifier':diagnostics.BUNDLE},
                        exception={'type':'EXC_CRASH','signal':'SIGABRT'},termination={'namespace':'SIGNAL','code':6},
                        applicationData={'account_id':123,'token':'MUST_NOT_COPY'},threads=[{'id':1,'triggered':True,
                        'frames':[{'symbol':'main','imageIndex':0,'imageOffset':1}],'threadState':{'secret':'no'}}])
            raw=(json.dumps({'app_name':'ElichikaSimulatorProbe'})+'\n'+json.dumps(report)).encode()
            summary=diagnostics.crash_summary(raw,(self.app/'ElichikaSimulatorProbe').resolve(),pid=PID)
            self.assertEqual(summary['exception']['signal'],'SIGABRT')
            self.assertNotIn('MUST_NOT_COPY',json.dumps(summary))
            self.assertNotIn('threadState',json.dumps(summary))
            for mode in ('wrong-app','wrong-bundle','wrong-pid'):
                changed=json.loads(json.dumps(report))
                if mode=='wrong-app':changed['procPath']=str(root/'Unowned.app/main')
                if mode=='wrong-bundle':changed['bundleInfo']['CFBundleIdentifier']='unowned'
                if mode=='wrong-pid':changed['pid']=5555
                self.assertIsNone(diagnostics.crash_summary(json.dumps(changed).encode(),self.app/'ElichikaSimulatorProbe',pid=PID))
            path=reports/'ElichikaSimulatorProbe-owned.ips';path.write_bytes(raw)
            now=time.time()
            self.assertEqual(len(diagnostics.owned_crashes(reports,self.app,now-10,now,pid=PID)),1)
            self.assertFalse(diagnostics.owned_crashes(reports,self.app,now-10,now,pid=PID,
                                                     deadline=time.monotonic()-1))
            os.utime(path,(now-100,now-100))
            self.assertFalse(diagnostics.owned_crashes(reports,self.app,now-10,now,pid=PID))
            path.unlink();path.symlink_to(root/'unowned.ips');(root/'unowned.ips').write_bytes(raw)
            self.assertFalse(diagnostics.owned_crashes(reports,self.app,now-10,now,pid=PID))

    def test_redaction_removes_credentials_accounts_urls_and_user_home(self):
        text='ELICHIKA_SIMULATOR_STARTUP delegate_entry\ntoken=hidden\n{"account_id":123}\n' \
             'https://localhost/ios/?private=value /Users/person/private/path\n' \
             'HTTPS://private.example/path /Users/Jane Doe/private/path\n'
        result=diagnostics.redacted(text,Path('/owned/app'))
        self.assertIn('delegate_entry',result)
        for secret in ('hidden','account_id','123','private=value','/Users/person','private.example','Jane Doe'):
            self.assertNotIn(secret,result)
        mixed=diagnostics.redacted('home=/Users/Jane Doe url=HTTPS://private.example/path',Path('/owned/app'))
        for secret in ('Jane Doe','private.example','/path'):
            self.assertNotIn(secret,mixed)

    def test_late_passing_json_or_diagnostic_error_does_not_revive_original_failure(self):
        for broken in (False,True):
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);reply=root/'native.json'
                original=ValueError('Simulator probe did not produce initial progress within 60 seconds')
                watchdog=Mock();watchdog.snapshot.return_value={'last_progress':None}
                process=Mock();process.poll.return_value=None
                def capture(*args):
                    reply.write_text(json.dumps({'probe_pass':True}))
                    if broken:raise OSError('capture failed token=NEVER_COPY')
                    return {'diagnostic_only_not_readiness':True}
                with patch('run_simulator.capture_owned_diagnostics',side_effect=capture), \
                        patch('run_simulator.port_open',return_value=False), \
                        patch('run_simulator.subprocess.run',return_value=subprocess.CompletedProcess([],0)):
                    retain_failure(root,'iPad-launch-1',DEVICE,process,watchdog,original,reply,
                                   installed=root,launch_wall=time.time()-60)
                row=json.loads((root/'iPad-launch-1-failure.json').read_text())
                self.assertEqual(row['status'],'FAIL_SIMULATOR_PROBE')
                self.assertEqual(row['error'],str(original))
                self.assertTrue(row['all_final_readiness_gates_still_required'])
                self.assertNotIn('NEVER_COPY',json.dumps(row))
                watchdog.observe.assert_not_called();watchdog.can_read_receipt.assert_not_called()


if __name__=='__main__':
    unittest.main()

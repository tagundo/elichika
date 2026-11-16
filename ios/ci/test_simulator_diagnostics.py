"""Synthetic ownership/boundary tests; no actual Simulator evidence is produced."""
import json
import datetime
import inspect
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
from run_simulator import execute, retain_failure

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
        self.change_before=False
        self.match=True
        self.ps_count=0
        self.start_wall=float(int(time.time())-9)
        self.launch_wall=self.start_wall-1

    def command(self, args, *, timeout=None, tail=False):
        self.calls.append(args)
        if args[0]=='ps':
            self.ps_count+=1
            if not self.match:return response('',1)
            changed=(self.sampled and self.change_identity) or (self.change_before and self.ps_count>=2)
            at=datetime.datetime.fromtimestamp(self.start_wall+int(changed)).strftime('%a %b %d %H:%M:%S %Y')
            return response(f'{PID} {os.geteuid()} {at} S 1.0 0.5 64000 {self.app}/ElichikaSimulatorProbe\n')
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

    def test_tail_buffer_drains_past_oldest_cap_and_preserves_latest_launch_message(self):
        row=diagnostics.bounded_command([sys.executable,'-c',
            'print("old-noise\\n"*3000+"OWNED_LAUNCH_FINAL",flush=True)'],timeout=2,cap=512,tail=True)
        self.assertEqual(row['returncode'],0)
        self.assertTrue(row['truncated'])
        self.assertEqual(row['retained_buffer'],'tail')
        self.assertLessEqual(len(row['text'].encode()),512)
        self.assertGreater(row['received_bytes'],512)
        self.assertTrue(row['text'].endswith('OWNED_LAUNCH_FINAL\n'))

    def test_console_pid_is_only_a_bounded_untrusted_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'console.txt'
            p.write_text('ELICHIKA_SIMULATOR_STARTUP main_entry\n'+diagnostics.BUNDLE+f': {PID}\n')
            self.assertEqual(diagnostics.console_pid_candidate(p),PID)
            for text in ('unowned: 4242\n',diagnostics.BUNDLE+': 1\n',
                         diagnostics.BUNDLE+': 4242\n'+diagnostics.BUNDLE+': 5555\n',
                         'x'*8192+'\n'+diagnostics.BUNDLE+': 4242\n'):
                p.write_text(text);self.assertIsNone(diagnostics.console_pid_candidate(p))
            p.unlink();p.symlink_to(Path(directory)/'missing')
            self.assertIsNone(diagnostics.console_pid_candidate(p))

    def test_truncated_tail_drops_sensitive_suffix_when_its_prefix_is_outside_buffer(self):
        for prefix in ('Authorization: Bearer ','HTTPS://private.example/'):
            for suffix in ('','\nSAFE_STARTUP_EVENT\n'):
                with self.subTest(prefix=prefix,suffix=suffix):
                    value=prefix+'PRIVATE_VALUE_'*1000+suffix
                    row=diagnostics.bounded_command([sys.executable,'-c',
                        'import sys;sys.stdout.write('+repr(value)+');sys.stdout.flush()'],
                        timeout=2,cap=512,tail=True)
                    self.assertTrue(row['truncated'])
                    self.assertTrue(row['partial_first_line_dropped'])
                    self.assertNotIn('PRIVATE_VALUE',row['text'])
                    clean=diagnostics.redacted(row['text'],Path('/owned/app'))
                    self.assertNotIn('PRIVATE_VALUE',clean)
                    if suffix:self.assertIn('SAFE_STARTUP_EVENT',clean)
                    else:self.assertEqual(clean,'')

    def test_owned_device_exact_executable_current_uid_and_kernel_start_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            self.app=app_fixture(Path(directory)/'parent with spaces')
            row=diagnostics.process_identity(PID,DEVICE,self.app,self.launch_wall,lambda a,s:self.command(a,timeout=s))
            self.assertEqual(row['pid'],PID)
            self.assertEqual(row['uid'],os.geteuid())
            self.assertGreaterEqual(row['started_wall'],self.launch_wall-2)
            self.match=False
            self.assertIsNone(diagnostics.process_identity(PID,DEVICE,self.app,self.launch_wall,lambda a,s:self.command(a,timeout=s)))
            for mode in ('wrong-uid','wrong-executable','wrong-pid','stale-start','future-start','truncated','timed-out'):
                self.match=True
                def invoke(args, seconds):
                    row=self.command(args,timeout=seconds)
                    fields=row['text'].split(None,11)
                    if mode=='wrong-uid':fields[1]=str(os.geteuid()+1)
                    if mode=='wrong-executable':fields[11]=str(self.app.parent/'Other.app/ElichikaSimulatorProbe')
                    if mode=='wrong-pid':fields[0]=str(PID+1)
                    if mode in ('stale-start','future-start'):
                        at=self.launch_wall-10 if mode=='stale-start' else time.time()+60
                        fields[2:7]=datetime.datetime.fromtimestamp(at).strftime('%a %b %d %H:%M:%S %Y').split()
                    if mode=='truncated':row['truncated']=True
                    if mode=='timed-out':row['timed_out']=True
                    row['text']=' '.join(fields)+'\n'
                    return row
                with self.subTest(mode=mode):
                    self.assertIsNone(diagnostics.process_identity(PID,DEVICE,self.app,self.launch_wall,invoke))

    def test_sample_requires_identity_before_and_after_and_never_trusts_console_pid(self):
        for mode in ('good','missing','changed-before','changed-after'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);self.app=app_fixture(root);out=root/'evidence';out.mkdir()
                console=root/'console.txt';console.write_text(diagnostics.BUNDLE+f': {PID}\n')
                self.calls=[];self.sampled=False;self.ps_count=0;self.match=mode!='missing'
                self.change_identity=mode=='changed-after';self.change_before=mode=='changed-before'
                with patch.object(diagnostics,'bounded_command',side_effect=self.command), \
                        patch.object(diagnostics,'owned_crashes',return_value=[]):
                    row=diagnostics.capture_owned_diagnostics(out,'iPad-launch-1',DEVICE,self.app,self.launch_wall,
                                                             console_log=console,prelaunch_verified=True)
                samples=[args for args in self.calls if args[0]=='sample']
                self.assertEqual(len(samples),int(mode in ('good','changed-after')))
                if mode=='good':
                    self.assertTrue(row['process_identity_revalidated_before_sample'])
                    self.assertTrue(row['process_identity_revalidated_after_sample'])
                    self.assertTrue((out/row['sample']['file']).is_file())
                else:
                    self.assertNotIn('sample',row)
                    self.assertFalse(any(out.glob('*owned-app-sample*')))
                self.assertTrue(row['diagnostic_only_not_readiness'])
                self.assertTrue(row['original_failure_unchanged'])
                self.assertFalse(any(args[0] in ('kill','killall','pkill') or 'terminate' in args or 'launch' in args
                                     for args in self.calls))
                self.assertFalse(any('get_app_container' in args or 'launchctl' in args for args in self.calls))
                log_args=next(args for args in self.calls if 'log' in args)
                self.assertIn('--start',log_args);self.assertNotIn('--last',log_args)
                self.assertIn(diagnostics.BUNDLE,log_args[-1]);self.assertNotIn('SpringBoard',log_args[-1])
                log=(out/row['device_log']['file']).read_text()
                self.assertIn('ELICHIKA_SIMULATOR_STARTUP main_entry',log)
                self.assertNotIn('private-value',log)

    def test_device_path_and_executable_symlinks_are_rejected_before_sampling(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.app=app_fixture(root);out=root/'evidence';out.mkdir()
            with self.assertRaises(ValueError):
                diagnostics.capture_owned_diagnostics(out,'x','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',self.app,time.time())
            with self.assertRaisesRegex(ValueError,'prelaunch'):
                diagnostics.capture_owned_diagnostics(out,'x',DEVICE,self.app,self.launch_wall)
            binary=self.app/'ElichikaSimulatorProbe';binary.unlink();binary.symlink_to('/bin/sh')
            with self.assertRaises(ValueError):
                diagnostics.process_identity(PID,DEVICE,self.app,self.launch_wall,lambda a,s:self.command(a,timeout=s))
            self.assertFalse(self.sampled)

    def test_runner_passes_prelaunch_inventory_anchor_and_flushed_log_after_expiry(self):
        source=inspect.getsource(execute)
        self.assertLess(source.index('Simulator installation changed signed bundle bytes'),source.index('subprocess.Popen'))
        self.assertLess(source.index('output.flush()'),source.index('retain_failure('))
        self.assertIn('console_log=log',source)
        retained=inspect.getsource(retain_failure)
        self.assertIn('prelaunch_verified=True',retained)
        self.assertIn('console_log=console_log',retained)

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
                def capture(*args,**kwargs):
                    self.assertTrue(kwargs['prelaunch_verified'])
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
                self.assertTrue(reply.is_file(),'the late-PASS negative must actually write its receipt')
                self.assertNotIn('NEVER_COPY',json.dumps(row))
                watchdog.observe.assert_not_called();watchdog.can_read_receipt.assert_not_called()


if __name__=='__main__':
    unittest.main()

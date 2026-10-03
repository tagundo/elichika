"""Drive an unchanged SIFAS client on disposable Android; capture real UI evidence."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from android_release_smoke import Android, PACKAGE

CLIENT = 'com.klab.lovelive.allstars.global'
SERVER_SHA = '23df494e132db7f3537851b11424bbe2903082e756e0798a7bf7ea022ba1ba2a'
CLIENT_SHA = '8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e'
BASELINE_VERSION = 2026100100
COMMAND_BRANCH = 'codex/lesson-rank-retest-qa'


class Device(Android):
    def wait_unity(self, action):
        """Poll real hierarchy only; never invoke game callbacks to finish a scene."""
        timeout = action.get('ready_timeout', 45)
        assert 1 <= timeout <= 60
        selector = action.get('selector', {})
        assert selector and set(selector) <= {'path', 'name', 'text', 'button', 'interactable'}
        started = time.monotonic()
        attempts = []
        last_error = None
        while time.monotonic() - started < timeout:
            label = 'wait-' + action['id'] + '-' + str(len(attempts))
            try:
                tree = self.unity_tree(label)
                matches = [n for n in tree['nodes'] if all(n.get(k) == v for k, v in selector.items())]
                visible = [n for n in matches if n.get('effective_alpha', 1) > 0.05 and n.get('inherited_interactable', True)]
                loading = [n for n in tree['nodes'] if 'LoadingUICanvas' in n['path'] and n.get('effective_alpha', 1) > 0.05]
                forbidden = [n for n in tree['nodes'] if any(part in n['path'] for part in action.get('forbid_path_contains', [])) and n.get('effective_alpha', 1) > 0.05]
                attempts.append({'node_count': len(tree['nodes']), 'matching_visible': len(visible), 'loading_nodes': len(loading), 'forbidden_nodes': len(forbidden)})
                if len(visible) == 1 and not forbidden and (not action.get('no_loading', True) or not loading):
                    return {'ready_seconds': round(time.monotonic() - started, 2), 'attempts': attempts,
                            'selector': selector, 'path': visible[0]['path'], 'bounds': visible[0]['bounds']}
            except Exception as error:
                last_error = str(error)
                attempts.append({'error': last_error})
            time.sleep(2)
        self.evidence.joinpath('wait-' + action['id'] + '-failed.json').write_text(json.dumps({'attempts': attempts, 'last_error': last_error}, indent=2) + '\n')
        raise AssertionError('Real Unity target did not become ready within ' + str(timeout) + 's: ' + str(selector))

    def stop_targets(self):
        for package in (CLIENT, PACKAGE):
            self.shell('am', 'force-stop', package)
        remaining = {}
        for process in (CLIENT, PACKAGE, 'libelichika.so'):
            try:
                remaining[process] = self.shell('pidof', process)
            except subprocess.CalledProcessError:
                remaining[process] = ''
        assert not any(remaining.values()), 'Target process survived force-stop: ' + str(remaining)
        return remaining

    def upgrade_snapshot(self, label):
        """Hash owned state without emitting credentials or copying assets to evidence."""
        files = '/data/user/0/' + PACKAGE + '/files'
        roots = ['/data/user/0/' + PACKAGE + '/shared_prefs', '/data/user/0/' + CLIENT + '/shared_prefs']
        paths = [files + '/userdata.db', files + '/config.json']
        for root in roots:
            result = self.shell('sh', '-c', 'if [ -d ' + shlex.quote(root) + ' ]; then find ' + shlex.quote(root) + ' -maxdepth 1 -type f -name \'*.xml\' | sort; fi')
            paths.extend(result.splitlines())
        hashes = {}
        for path in paths:
            assert path.startswith('/data/user/0/')
            hashes[path] = {'sha256': self.shell('sha256sum', path).split()[0],
                            'uid_gid_mode': self.shell('stat', '-c', '%u:%g:%a', path)}
        for suffix in ('-wal', '-journal'):
            result = self.shell('sh', '-c', 'if [ -f ' + shlex.quote(files + '/userdata.db' + suffix) + ' ]; then stat -c %s ' + shlex.quote(files + '/userdata.db' + suffix) + '; else echo 0; fi')
            assert result == '0', 'Database is not offline: ' + suffix
        package = self.shell('dumpsys', 'package', PACKAGE)
        self.evidence.joinpath(label + '-package.txt').write_text(package + '\n')
        uid = re.search(r'\buserId=(\d+)', package)
        assert uid, 'Server app UID missing'
        game_package = self.shell('dumpsys', 'package', CLIENT)
        self.evidence.joinpath(label + '-game-package.txt').write_text(game_package + '\n')
        game_uid = re.search(r'\buserId=(\d+)', game_package)
        assert game_uid, 'Game app UID missing'
        permission = re.search(r'android\.permission\.POST_NOTIFICATIONS: granted=(true|false)', package)
        op = self.shell('appops', 'get', PACKAGE, 'MANAGE_EXTERNAL_STORAGE')
        self.evidence.joinpath(label + '-storage-appop.txt').write_text(op + '\n')
        mode = re.search(r'MANAGE_EXTERNAL_STORAGE:\s*(\w+)', op)
        assert permission and mode, 'Runtime permission/AppOp baseline missing'
        result = {'state_files': hashes, 'app_uid': int(uid.group(1)), 'game_uid': int(game_uid.group(1)),
                  'notification_granted': permission.group(1) == 'true', 'storage_appop': mode.group(1)}
        self.evidence.joinpath(label + '-snapshot.json').write_text(json.dumps(result, indent=2) + '\n')
        return result

    def upgrade_server(self, action, manifest_path, state):
        if action.get('artifact_manifest'):
            manifest = self.download_candidate(action['artifact_manifest'])
        else:
            assert manifest_path and manifest_path.is_file(), 'Exact corrected APK manifest is required'
            manifest = json.loads(manifest_path.read_text())
        assert re.fullmatch(r'[0-9a-f]{40}', manifest['source_commit'])
        assert re.fullmatch(r'[0-9a-f]{64}', manifest['sha256'])
        assert manifest['version_code'] > state['server_install']['version_code']
        assert manifest['official_signer_matches_baseline'] is True
        assert manifest['signer_sha256'] == 'fed020601692d2e759286831ad229f0c8e4562a8e90f9067d7472fa5fc99f930'
        apk = Path(manifest['path']).resolve()
        assert apk.is_relative_to(Path.cwd().resolve()) and apk.is_file(), 'Corrected APK path must be inside this QA checkout'
        assert hashlib.sha256(apk.read_bytes()).hexdigest() == manifest['sha256']
        stopped = self.stop_targets()
        before = self.upgrade_snapshot('upgrade-before-' + action['id'])
        # Android.install re-grants permissions. Intentionally do not use it for upgrade.
        install = self.adb('install', '-r', str(apk), timeout=180)
        assert 'Success' in install
        after = self.upgrade_snapshot('upgrade-after-install-' + action['id'])
        assert after == before, 'In-place APK replacement changed owned data/settings/permissions before first launch'
        info = self.shell('dumpsys', 'package', PACKAGE)
        assert 'versionCode=' + str(manifest['version_code']) in info
        assert 'primaryCpuAbi=arm64-v8a' in info
        base = self.shell('pm', 'path', PACKAGE).splitlines()[0].removeprefix('package:')
        installed_native = str(Path(base).parent / 'lib/arm64/libelichika.so')
        with zipfile.ZipFile(apk) as archive:
            expected_native = hashlib.sha256(archive.read('lib/arm64-v8a/libelichika.so')).hexdigest()
        native = self.shell('sha256sum', installed_native).split()[0]
        assert native == expected_native == manifest['native_sha256']
        self.native_sha = native
        state.setdefault('upgrade_history', []).append({'old_server_install': dict(state['server_install']),
            'old_server_apk_sha256': state['server_apk_sha256'], 'new_manifest': manifest,
            'before': before, 'after_prelaunch': after})
        state['server_install'] = {'version_code': manifest['version_code'], 'native_sha256': native}
        state['server_apk_sha256'] = manifest['sha256']
        state['corrected_source_commit'] = manifest['source_commit']
        state['upgrade_apk_manifest'] = manifest
        result = {'stopped_processes': stopped, 'install_result': install, 'before': before,
                  'after_prelaunch': after, 'state_permission_uid_preserved': True, 'native_sha256': native,
                  'permission_regrant_performed': False, 'user_data_clear_or_uninstall_performed': False}
        result['server_restart'] = self.start('upgrade-server-' + action['id'])
        self.shell('am', 'start', '-W', '-n', state['client_activity'])
        return result

    def download_candidate(self, supplied):
        """Download only an exact authorized GitHub artifact; validate full original ZIP."""
        manifest = dict(supplied)
        assert type(manifest['artifact_id']) is int and manifest['artifact_id'] > 0
        assert type(manifest['run_id']) is int and manifest['run_id'] > 0
        assert re.fullmatch(r'[0-9a-f]{64}', manifest['artifact_zip_sha256'])
        endpoint = 'repos/tagundo/elichika/actions/artifacts/' + str(manifest['artifact_id'])
        metadata = json.loads(subprocess.check_output(['gh', 'api', endpoint]))
        assert metadata['workflow_run']['id'] == manifest['run_id']
        assert metadata['workflow_run']['head_sha'] == manifest['source_commit']
        assert metadata['digest'] == 'sha256:' + manifest['artifact_zip_sha256']
        assert not metadata['expired']
        run = json.loads(subprocess.check_output(['gh', 'api', 'repos/tagundo/elichika/actions/runs/' + str(manifest['run_id'])]))
        assert run['conclusion'] == 'success' and run['head_sha'] == manifest['source_commit']
        folder = Path('candidate-current'); folder.mkdir(exist_ok=True)
        original_zip = folder / ('artifact-' + str(manifest['artifact_id']) + '.zip')
        with original_zip.open('wb') as destination:
            subprocess.run(['gh', 'api', endpoint + '/zip'], stdout=destination, check=True, timeout=180)
        assert hashlib.sha256(original_zip.read_bytes()).hexdigest() == manifest['artifact_zip_sha256']
        with zipfile.ZipFile(original_zip) as archive:
            assert archive.testzip() is None, 'Candidate artifact ZIP CRC failure'
            matches = [n for n in archive.namelist() if n == manifest['filename']]
            assert len(matches) == 1 and '/' not in manifest['filename'] and manifest['filename'].endswith('.apk')
            apk = folder / manifest['filename']
            apk.write_bytes(archive.read(matches[0]))
        assert hashlib.sha256(apk.read_bytes()).hexdigest() == manifest['sha256']
        manifest['path'] = str(apk)
        self.evidence.joinpath('candidate-artifact-integrity.json').write_text(json.dumps({
            'artifact_id': manifest['artifact_id'], 'run_id': manifest['run_id'], 'source_commit': manifest['source_commit'],
            'official_zip_digest': metadata['digest'], 'original_zip_sha256_verified': True,
            'all_zip_member_crc_verified': True, 'apk_sha256': manifest['sha256'],
            'original_zip_bytes': original_zip.stat().st_size, 'apk_bytes': apk.stat().st_size}, indent=2) + '\n')
        return manifest

    def unity_tree(self, label):
        destination=self.evidence/(label+'-unity-ui.json')
        result=subprocess.run(['python3','tests/unity_ui_probe.py','--output',str(destination)],
                              capture_output=True,text=True,timeout=60)
        self.evidence.joinpath(label+'-unity-probe.txt').write_text(result.stdout+'\n'+result.stderr)
        assert result.returncode==0,result.stderr[-1500:]
        data=json.loads(destination.read_text())
        assert data.get('nodes'), 'Unity hierarchy has no visible UI nodes: '+str(data.get('errors'))
        print('UNITY_UI '+result.stdout.strip(),flush=True)
        return data

    def tap_unity_node(self, action):
        tree=self.unity_tree('target-'+action['id'])
        selector=action.get('selector',{})
        assert selector and set(selector)<= {'path','name','text','button','interactable'}
        matches=[n for n in tree['nodes'] if all(n.get(k)==v for k,v in selector.items())]
        assert len(matches)==1, 'Unity target must match exactly one node, got '+str(len(matches))
        node=matches[0]
        assert node.get('effective_alpha',1)>0.05, 'Target is hidden by CanvasGroup alpha'
        assert node.get('inherited_interactable',True), 'Target inherits a non-interactable CanvasGroup'
        x1,y1,x2,y2=node['bounds']
        assert 0<=x1<x2<=tree['width'] and 0<=y1<y2<=tree['height']
        x,y=str(round((x1+x2)/2)),str(round((y1+y2)/2))
        raycast_path=self.evidence/('raycast-'+action['id']+'.json')
        raycast_process=subprocess.run(['python3','tests/unity_ui_probe.py','--output',str(raycast_path),
                                       '--raycast',x,y],capture_output=True,text=True,timeout=60)
        raycast_data=json.loads(raycast_path.read_text()) if raycast_process.returncode==0 else {}
        raycast=raycast_data.get('pointer_raycast',{'supported':False,'reason':raycast_process.stderr[-600:]})
        if raycast.get('supported') and raycast.get('hits'):
            first=raycast['hits'][0]['path']
            assert not ('LoadingUICanvas' in first and 'LoadingUICanvas' not in node['path']), 'Loading canvas receives the touch: '+first
            assert not ('/PopupView/' in first and '/PopupView/' not in node['path']), 'A modal popup receives the touch: '+first
        hold=action.get('hold_ms',0)
        assert hold==0 or 50<=hold<=350
        if hold:self.shell('input','swipe',x,y,x,y,str(hold))
        else:self.shell('input','tap',x,y)
        return {'source':tree['source'],'selector':selector,'path':node['path'],'bounds':node['bounds'],'hold_ms':hold,'pointer_raycast':raycast}

    def capture(self, label):
        for name,args in [('screen.png',('exec-out','screencap','-p')),
                          ('logcat.txt.gz',('logcat','-d')),
                          ('crash.txt',('logcat','-b','crash','-d')),
                          ('activity.txt',('shell','dumpsys','activity','activities'))]:
            try:
                data=self.adb(*args,raw=True)
                self.evidence.joinpath(label+'-'+name).write_bytes(gzip.compress(data) if name.endswith('.gz') else data)
            except Exception as e:
                self.evidence.joinpath(label+'-'+name+'.error').write_text(str(e))
        try:
            self.shell('uiautomator','dump','/sdcard/client-qa.xml',timeout=60)
            data=self.read('/sdcard/client-qa.xml')
            self.evidence.joinpath(label+'-ui.xml').write_bytes(data)
            tree=ET.fromstring(data)
            nodes=[{k:n.get(k) for k in ['text','content-desc','resource-id','class','bounds','clickable','scrollable']} for n in tree.iter('node')]
            self.evidence.joinpath(label+'-ui.json').write_text(json.dumps(nodes,indent=2,ensure_ascii=False)+'\n')
            print('UI_CAPTURE '+label+' '+json.dumps(nodes[:35],ensure_ascii=False),flush=True)
        except Exception as e:
            self.evidence.joinpath(label+'-ui.error').write_text(str(e))
        try:
            self.evidence.joinpath(label+'-server.txt').write_bytes(self.read('/sdcard/Download/sukusta/logs/elichika.log'))
        except Exception:
            pass

    def tap_node(self, action):
        self.shell('uiautomator','dump','/sdcard/client-qa.xml',timeout=60)
        data=self.read('/sdcard/client-qa.xml')
        tree=ET.fromstring(data)
        matches=[]
        for node in tree.iter('node'):
            if all(node.get(k)==v for k,v in action.get('selector',{}).items()):
                matches.append(node)
        assert action.get('selector') and matches, 'No matching UI-tree target'
        node=matches[action.get('index',0)]
        x1,y1,x2,y2=map(int,re.findall(r'\d+',node.get('bounds','')))
        assert x2>x1 and y2>y1
        self.shell('input','tap',str((x1+x2)//2),str((y1+y2)//2))
        return {'selector':action['selector'],'bounds':node.get('bounds')}


def fetch_commands(branch):
    assert re.fullmatch(r'[A-Za-z0-9_./-]{1,120}', branch)
    url='https://api.github.com/repos/tagundo/elichika/contents/qa/client-actions.json?ref=' + branch
    req=urllib.request.Request(url,headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],
                                          'Accept':'application/vnd.github.raw+json'})
    with urllib.request.urlopen(req,timeout=20) as response:
        return json.loads(response.read())


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--stage',choices=['initial','control'],required=True)
    p.add_argument('--round',type=int,default=0)
    p.add_argument('--duration',type=int,default=180)
    p.add_argument('--server',type=Path)
    p.add_argument('--client',type=Path)
    p.add_argument('--server-sha',default=SERVER_SHA)
    p.add_argument('--server-version',type=int,default=BASELINE_VERSION)
    p.add_argument('--candidate-manifest',type=Path)
    p.add_argument('--commands-branch',default=COMMAND_BRANCH)
    p.add_argument('--evidence',type=Path,default=Path('evidence'))
    args=p.parse_args();args.evidence.mkdir(parents=True,exist_ok=True)
    dev=Device('127.0.0.1:5555',args.evidence)
    state_path=Path('evidence/client-ui-state.json')
    state=json.loads(state_path.read_text()) if state_path.exists() else {'status':'RUNNING','actions':[],
        'server_apk_sha256':args.server_sha,'client_apk_sha256':CLIENT_SHA,
        'limits':['Disposable rooted Android virtual device; not a physical phone',
                  '4KB results do not establish full Android16KB compatibility',
                  'Unity accessibility may not expose individual game controls']}
    if args.stage == 'control':
        installed_sha = state.get('server_install', {}).get('native_sha256')
        assert installed_sha and re.fullmatch(r'[0-9a-f]{64}', installed_sha), 'Missing initial native executable hash'
        dev.native_sha = installed_sha
    try:
        if args.stage=='initial':
            assert hashlib.sha256(args.server.read_bytes()).hexdigest()==args.server_sha
            assert hashlib.sha256(args.client.read_bytes()).hexdigest()==CLIENT_SHA
            state['environment']={k:dev.shell(*v) for k,v in {
              'android':('getprop','ro.build.version.release'),'api':('getprop','ro.build.version.sdk'),
              'abi':('getprop','ro.product.cpu.abi'),'model':('getprop','ro.product.model'),
              'pagesize':('getconf','PAGESIZE'),'selinux':('getenforce',)}.items()}
            assert state['environment']['pagesize']=='4096'
            dev.adb('logcat','-c')
            state['server_install']=dev.install(args.server,args.server_version)
            state['server_start']=dev.start('server-start')
            # Only this disposable virtual device is affected; retain the evidence of the
            # normal Play Protect legacy-app prompt from the preceding comparison run.
            dev.shell('settings','put','global','package_verifier_enable','0')
            dev.shell('settings','put','global','verifier_verify_adb_installs','0')
            state['adb_install_verification']={name:dev.shell('settings','get','global',name)
                for name in ['package_verifier_enable','verifier_verify_adb_installs']}
            output=dev.adb('install','-r',str(args.client),timeout=60)
            assert 'Success' in output
            state['client_install']=output
            resolved=dev.shell('cmd','package','resolve-activity','--brief',CLIENT).splitlines()[-1]
            assert '/' in resolved,resolved
            state['client_activity']=resolved
            state['client_launch']=dev.shell('am','start','-W','-n',resolved)
            for seconds in [5]:
                time.sleep(seconds)
                dev.capture('initial-'+str(seconds))
            # Both targets were previously observed in Android's real UI tree.
            for selector in [{'resource-id':'android:id/button1','text':'OK'},
                             {'resource-id':'android:id/ok','text':'GOT IT'}]:
                try:
                    target=dev.tap_node({'selector':selector})
                    state['native_setup_actions']=state.get('native_setup_actions',[])+[target]
                    time.sleep(8)
                except AssertionError:
                    pass
            time.sleep(25)
            dev.capture('initial-game')
            state['client_pid']=dev.shell('pidof',CLIENT)
            # A native screenshot is collected before any Frida client attachment.
            # A blank startup frame is not safe evidence of a usable Unity main loop.
            from PIL import Image
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                frame=dev.adb('exec-out','screencap','-p',raw=True)
                pixels=list(Image.open(io.BytesIO(frame)).convert('RGB').resize((128,72)).getdata())
                visible=sum(max(pixel)>20 for pixel in pixels)/len(pixels)
                state['pre_frida_visible_frame_fraction']=visible
                if visible>0.02:break
                time.sleep(5)
            else:
                raise AssertionError('Client remained blank before any Frida client attachment')
            dev.evidence.joinpath('pre-frida-visible-client.png').write_bytes(frame)
            state['status']='CLIENT_LAUNCHED_AWAITING_UI_VALIDATION'
            try:state['initial_unity_node_count']=len(dev.unity_tree('initial-game')['nodes'])
            except Exception as e:state['unity_probe_error']=str(e)
            state['bootstrap_actions']=[]
            for step in [{'id':'select-korean','selector':{'name':'KoreanButton'},'wait':5},
                         {'id':'confirm-korean','selector':{'name':'ButtonPositiveM'},'wait':10},
                         {'id':'title-start-prompt','selector':{'name':'TapTextView'},'wait':30},
                         {'id':'accept-terms','selector':{'name':'ButtonPositiveM'},'wait':8},
                         {'id':'choose-light-download','selector':{'path':'EntryPoint/PopupView/Container/BasicPopupFrame(Clone)/UICanvas/Window/Background/Content/ModeSelectableDownloadConfirmPopup(Clone)/ScrollView/Viewport/Content/RadioButtonToggle/LightnessToggle/DownloadTypeTextView'},'wait':3},
                         {'id':'confirm-light-download','selector':{'name':'ButtonPositiveM'},'wait':30}]:
                try:
                    record=dev.tap_unity_node(step)
                    time.sleep(step['wait'])
                    dev.capture('bootstrap-'+step['id'])
                    current_tree=dev.unity_tree('bootstrap-'+step['id'])
                    if step['id']=='choose-light-download':
                        assert any('/LightnessToggle/ToggleOn' in n['path'] for n in current_tree['nodes']), 'Light download was not selected; refusing full download'
                    state['bootstrap_actions'].append({'id':step['id'],**record})
                except Exception as e:
                    state['bootstrap_error']=str(e);break
        else:
            if state.get('control_stopped'):return
            done={a['id'] for a in state['actions']}
            deadline=time.monotonic()+args.duration
            count=0
            while time.monotonic()<deadline:
                commands=fetch_commands(args.commands_branch)
                for action in commands.get('actions',[]):
                    if action['id'] in done:continue
                    record={'id':action['id'],'type':action['type'],'started_at_utc':datetime.now(timezone.utc).isoformat()}
                    try:
                        if action['type']=='tap':record.update(dev.tap_node(action))
                        elif action['type']=='unity_tree':record['nodes']=len(dev.unity_tree('action-'+action['id'])['nodes'])
                        elif action['type']=='unitytap':
                            if action.get('ready_timeout'):record['readiness'] = dev.wait_unity(action)
                            record.update(dev.tap_unity_node(action))
                        elif action['type']=='unitywait':record.update(dev.wait_unity(action))
                        elif action['type']=='server_upgrade':record.update(dev.upgrade_server(action,args.candidate_manifest,state))
                        elif action['type']=='key':
                            assert action['keycode'] in [4,66,82]
                            dev.shell('input','keyevent',str(action['keycode']))
                        elif action['type']=='capture':pass
                        elif action['type']=='launch':dev.shell('am','start','-W','-n',state['client_activity'])
                        elif action['type']=='client_restart':
                            dev.shell('am','force-stop',CLIENT)
                            dev.shell('am','start','-W','-n',state['client_activity'])
                        elif action['type']=='observer_phase':
                            Path('evidence/observer/phase-request.json').write_text(json.dumps({'id':action['id']})+'\n')
                            record['phase']=action['id']
                        elif action['type']=='observer_start':
                            folder=Path('evidence/observer');folder.mkdir(exist_ok=True)
                            pidfile=folder/'observer-host.pid'
                            if pidfile.exists():
                                previous=int(pidfile.read_text())
                                if Path('/proc/'+str(previous)).exists():
                                    raise AssertionError('Observer process is already running')
                            with (folder/'observer-host.log').open('ab') as logfile:
                                process=subprocess.Popen(['python3','-u','tests/unity_observer.py',
                                    '--evidence',str(folder),'--duration','5700'],stdin=subprocess.DEVNULL,
                                    stdout=logfile,stderr=subprocess.STDOUT,start_new_session=True)
                            pidfile.write_text(str(process.pid)+'\n')
                            record['observer_host_pid']=process.pid
                        elif action['type']=='fixture':
                            assert action['operation'] in ['inspect','apply','restore','restore_master']
                            assert action.get('case','') in ['', 'zero_first','no_drop_first','no_drop_completed','one_first','zero_completed','one_completed','full_slots','pin_two','three_times','shooting_star']
                            user_id=str(action.get('user_id','auto'))
                            assert user_id=='auto' or re.fullmatch(r'[0-9]+',user_id)
                            fixture_root=action.get('checkpoint','default')
                            assert re.fullmatch(r'[A-Za-z0-9_-]{1,50}', fixture_root)
                            command=['python3','-u','tests/lesson_fixture_qa.py','--serial',dev.serial,
                                     '--evidence','evidence/fixtures-'+fixture_root,'--action',action['operation'],
                                     '--user-id',user_id,'--disposable-device']
                            if action.get('case'):command+=['--case',action['case']]
                            result=subprocess.run(command,capture_output=True,text=True,timeout=240)
                            fixture_report=dev.evidence/('fixture-'+action['id']+'.txt')
                            fixture_report.write_text(result.stdout+'\n'+result.stderr)
                            assert result.returncode==0,result.stdout[-2000:]+result.stderr[-2000:]
                            record['fixture_report']=str(fixture_report)
                            restart = action.get('restart', action['operation'] != 'restore_master')
                            if action['operation'] in ['apply','restore','restore_master'] and restart:
                                record['server_restart']=dev.start('fixture-server-'+action['id'])
                                dev.shell('am','start','-W','-n',state['client_activity'])
                            elif action['operation'] in ['apply','restore','restore_master']:
                                record['apps_left_stopped']=True
                        elif action['type']=='unity_raycast':
                            tree=dev.unity_tree('raycast-target-'+action['id'])
                            matches=[n for n in tree['nodes'] if all(n.get(k)==v for k,v in action['selector'].items())]
                            assert len(matches)==1,'Raycast selector must match one node'
                            node=matches[0]
                            x1,y1,x2,y2=node['bounds']
                            x,y=str(round((x1+x2)/2)),str(round((y1+y2)/2))
                            output=dev.evidence/('raycast-'+action['id']+'.json')
                            result=subprocess.run(['python3','tests/unity_ui_probe.py','--output',str(output),'--raycast',x,y],capture_output=True,text=True,timeout=60)
                            assert result.returncode==0,result.stderr[-1200:]
                            record['raycast']=json.loads(output.read_text()).get('pointer_raycast')
                            record['selector']=action['selector'];record['bounds']=node['bounds']
                        elif action['type'] in ['record_start','record_end']:
                            name=action['name']
                            assert re.fullmatch(r'[A-Za-z0-9_-]{1,60}',name)
                            path='/sdcard/emulator-qa-'+name+'.mp4'
                            pid_path=path+'.pid'
                            if action['type']=='record_start':
                                command='nohup screenrecord --time-limit 180 --bit-rate 1000000 '+shlex.quote(path)+' > '+shlex.quote(path+'.log')+' 2>&1 < /dev/null & echo $! > '+shlex.quote(pid_path)
                                dev.shell('sh','-c',command)
                                record['recording_path']=path
                            else:
                                pid=dev.read(pid_path).decode().strip()
                                assert pid.isdigit()
                                try:dev.shell('kill','-2',pid)
                                except subprocess.CalledProcessError:pass
                                time.sleep(2)
                                destination=dev.evidence/('recording-'+name+'.mp4')
                                dev.adb('pull',path,str(destination),timeout=60)
                                assert destination.stat().st_size>1000,'Screen recording is empty'
                                record['video_bytes']=destination.stat().st_size
                                record['video_file']=str(destination)
                        elif action['type']=='text':
                            assert re.fullmatch(r'[A-Za-z0-9 ._-]{1,40}',action['text'])
                            dev.shell('input','text',action['text'].replace(' ','%s'))
                        elif action['type']=='stop':
                            state['status']='CONTROL_COMPLETED';state['control_stopped']=True
                            if os.environ.get('GITHUB_ENV'):
                                with Path(os.environ['GITHUB_ENV']).open('a') as workflow_env:
                                    workflow_env.write('QA_CONTROL_COMPLETE=true\nQA_STOP_ROUND=' + str(args.round) + '\n')
                            state_path.write_text(json.dumps(state,indent=2)+'\n');return
                        else:raise ValueError('Unsupported action: '+action['type'])
                        time.sleep(min(action.get('wait',10),60))
                        record['result']='EXECUTED'
                    except Exception as e:record.update(result='FAILED',error=str(e))
                    dev.capture('action-'+action['id'])
                    if action['type']=='unitytap':
                        try:dev.unity_tree('action-'+action['id'])
                        except Exception as e:record['post_action_tree_error']=str(e)
                    record['finished_at_utc']=datetime.now(timezone.utc).isoformat()
                    state['actions'].append(record);done.add(action['id'])
                    state_path.write_text(json.dumps(state,indent=2)+'\n')
                    if record['result']=='FAILED' and action.get('required',False):
                        raise AssertionError('Required QA action failed; stopping dependent flow: ' + action['id'] + ': ' + record['error'])
                if count%20==0:dev.capture('round-'+str(args.round)+'-'+str(count))
                count+=1;time.sleep(2)
            dev.capture('round-'+str(args.round)+'-final')
    except Exception as e:
        state.update(status='SETUP_OR_EXECUTION_FAILED',error=str(e))
        dev.capture('failure')
        raise
    finally:
        state_path.write_text(json.dumps(state,indent=2,ensure_ascii=False)+'\n')
        print('CLIENT_UI_STATE '+json.dumps(state,ensure_ascii=False),flush=True)


if __name__=='__main__':main()

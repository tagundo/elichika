#!/usr/bin/env python3
"""Actual PlayCover GUI import/launch plus external bounded native evidence.

This never edits an IPA or imported app, injects a game agent, grants TCC,
modifies SIP/AMFI, or claims game login/playback from a living process.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request

from expected_entitlements import expected
from verify_playcover_install import audit_diagnostics

HERE = Path(__file__).resolve().parent
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + '\n')
def sha(path):
    with path.open('rb') as handle: return hashlib.file_digest(handle, 'sha256').hexdigest()
def command(argv, timeout=60):
    try:
        result = subprocess.run(list(map(str, argv)), capture_output=True, text=True, timeout=timeout)
        return {'code': result.returncode, 'stdout': result.stdout[-18000:], 'stderr': result.stderr[-8000:]}
    except subprocess.TimeoutExpired:
        return {'code': -1, 'error': 'timeout'}
    except OSError as error:
        return {'code': -1, 'error': str(error)}
def wait_for(predicate, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = predicate()
        if value: return value
        time.sleep(.5)
    return None

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixtures', type=Path, required=True)
    p.add_argument('--evidence', type=Path, required=True)
    p.add_argument('--server-source', type=Path)
    p.add_argument('--server-binary', type=Path)
    a = p.parse_args()
    a.evidence.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((HERE/'manifest.json').read_text())
    report = {'status': 'IN_PROGRESS', 'manifest': manifest, 'stages': [], 'candidates': [],
              'game_login_observed': False, 'full_mv_playback_observed': False,
              'duplicate_mv_members_observed': False, 'closet_row_count_unchanged_observed': False,
              'physical_ios_validated': False,
              'qualification': 'Actual GUI import/launch and observed native diagnostics only. Bundle checks or process lifetime do not prove gameplay, server login, or MV playback.'}
    def stage(name, **values):
        report['stages'].append(dict(stage=name, at=time.time(), **values))
        write(a.evidence/'summary.json', report)
        print(name, flush=True)
    server = None
    try:
        stage('verify-apple-silicon-windowserver')
        assert platform.system() == 'Darwin' and platform.machine() == 'arm64'
        host = {name: command(argv) for name, argv in {
            'uname': ['uname','-a'], 'macos': ['sw_vers'], 'hardware': ['sysctl','-n','hw.optional.arm64'],
            'windowserver': ['pgrep','-x','WindowServer'], 'sip': ['csrutil','status'],
            'bootargs': ['sysctl','kern.bootargs']}.items()}
        write(a.evidence/'host.json', host)
        assert host['hardware']['stdout'].strip() == '1' and host['windowserver']['code'] == 0, 'Apple Silicon WindowServer required'
        assert 'amfi_get_out_of_my_way' not in host['bootargs']['stdout'], 'Unreviewed PlaySign environment'
        build = a.fixtures/'host-tools'; build.mkdir(exist_ok=True)
        for name in ['HostEvidence', 'PlayCoverAX']:
            result = command(['xcrun','swiftc',HERE/(name+'.swift'),'-o',build/name], timeout=120)
            write(a.evidence/(name+'-compile.json'), result)
            assert result['code'] == 0, 'Swift helper compilation failed: '+name
        def host_state(bundle):
            result = command([build/'HostEvidence',bundle])
            if result['code']: return {'error': result}
            return json.loads(result['stdout'])
        def record_screen(bundle, folder, label):
            state = host_state(bundle)
            write(folder/(label+'-host.json'), state)
            if not state.get('screen_capture_authorized'):
                return {'status':'BLOCKED_SCREEN_RECORDING_PERMISSION'}
            windows = [window for app in state.get('applications',[]) for window in app['windows']
                       if window.get('kCGWindowLayer') == 0 and window.get('kCGWindowBounds',{}).get('Width',0) > 50]
            if not windows: return {'status':'NO_VISIBLE_APP_WINDOW'}
            target = folder/(label+'.png')
            result = command(['screencapture','-x','-l',str(windows[0]['kCGWindowNumber']),target])
            return {'status':'CAPTURED' if result['code'] == 0 and target.exists() else 'CAPTURE_FAILED', 'command': result}
        stage('download-pinned-playcover')
        dmg = a.fixtures/'PlayCover.dmg'
        with urllib.request.urlopen(manifest['playcover_dmg_url'], timeout=90) as source, dmg.open('wb') as target:
            while block := source.read(1024*1024): target.write(block)
        assert sha(dmg) == manifest['playcover_dmg_sha256'], 'PlayCover DMG hash mismatch'
        mounted = command(['hdiutil','attach','-nobrowse','-plist',dmg], timeout=120)
        write(a.evidence/'dmg-mount.json', mounted)
        assert mounted['code'] == 0
        volume = next(Path(item['mount-point']) for item in plistlib.loads(mounted['stdout'].encode())['system-entities'] if 'mount-point' in item)
        source_app = next(volume.glob('*.app'))
        pc = Path.home()/'Applications/PlayCover.app'
        pc.parent.mkdir(exist_ok=True)
        assert command(['ditto',source_app,pc], timeout=90)['code'] == 0
        info = plistlib.loads((pc/'Contents/Info.plist').read_bytes())
        pcid = info['CFBundleIdentifier']
        assert pcid == 'io.playcover.PlayCover'
        signature = command(['codesign','--verify','--deep','--strict','--verbose=4',pc])
        write(a.evidence/'playcover-signature.json', signature)
        assert signature['code'] == 0, 'Pinned PlayCover app signature failed'
        for key, value in [('AlwaysInstallPlayTools','false'),('ShowInstallPopup','false'),('ShowAppStorePopup','false')]:
            assert command(['defaults','write',pcid,key,'-bool',value])['code'] == 0
        stage('open-actual-playcover')
        opened = command(['open','-a',pc])
        write(a.evidence/'playcover-open.json', opened)
        assert opened['code'] == 0
        assert wait_for(lambda: host_state(pcid).get('applications'), 30), 'PlayCover did not run'
        report['playcover_window'] = record_screen(pcid, a.evidence, 'playcover-initial')
        expected_path = a.fixtures/'reviewed-playcover-entitlements.json'
        write(expected_path, expected(Path.home()))
        write(a.evidence/'reviewed-playcover-entitlements.json', expected(Path.home()))
        if a.server_source and a.server_binary:
            stage('start-disposable-frozen-elichika')
            serverlog = a.fixtures/'server-private.log'
            output = serverlog.open('w')
            server = subprocess.Popen([str(a.server_binary)], cwd=a.server_source, stdout=output, stderr=subprocess.STDOUT)
            report['server_pid'] = server.pid
            def server_ready():
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8080/webui/admin/login',timeout=1) as response:
                        return response.status == 200
                except Exception: return False
            assert wait_for(server_ready,180), 'Disposable Go server readiness failed'
        for candidate in manifest['candidates']:
            folder = a.evidence/candidate['region']; folder.mkdir()
            result = dict(candidate, status='IN_PROGRESS', feature_actions=[], game_login_observed=False, mv_playback_observed=False, actual_playcover_import=False)
            report['candidates'].append(result)
            stage('gui-import-'+candidate['region'])
            assert not host_state(candidate['bundle_id']).get('applications'), 'Prior app process must exit before importing this bundle identity'
            ipa = a.fixtures/candidate['name']
            assert sha(ipa) == candidate['sha256'], 'Candidate changed: '+candidate['region']
            app = Path.home()/'Library/Containers/io.playcover.PlayCover/Applications'/(candidate['bundle_id']+'.app')
            begin = time.time()
            imported = command(['open','-a',pc,ipa])
            write(folder/'actual-gui-import.json', imported)
            def installed():
                path = app/'Info.plist'
                return path.exists() and path.stat().st_mtime >= begin-2 and (app/'Frameworks/SIFASFeatures.dylib').exists()
            if imported['code'] or not wait_for(installed,180):
                result.update(status='FAIL_GUI_IMPORT', playcover_state=host_state(pcid))
                result['import_screen'] = record_screen(pcid,folder,'import-blocker')
                stage('import-failed-'+candidate['region'])
                continue
            time.sleep(3)
            result['actual_playcover_import'] = True
            stage('verify-imported-bundle-'+candidate['region'])
            verified = command([sys.executable,HERE/'verify_playcover_install.py','--installed-app',app,
                '--candidate-ipa',ipa,'--candidate-sha256',candidate['sha256'],'--proof-dir',folder/'install-verification',
                '--playcover-app',pc,'--playcover-dmg',dmg,'--expected-entitlements',expected_path],timeout=180)
            write(folder/'verifier-command.json', verified)
            result['bundle_verification_passed'] = verified['code'] == 0
            stage('launch-imported-app-'+candidate['region'])
            launch_args = ['open','-a',app,'--args','-SIFASDiagnosticsEnabled','YES','-ServerEndpoint','http://127.0.0.1:8080']
            launch_wall = time.time()
            launch = command(launch_args)
            write(folder/'normal-launch.json',launch)
            running = wait_for(lambda: host_state(candidate['bundle_id']).get('applications'),30)
            if not running:
                result.update(status='FAIL_APP_LAUNCH', launch=launch)
                stage('launch-failed-'+candidate['region'])
                continue
            pid = running[0]['pid']; result['actual_pid'] = pid
            result['actual_process_start'] = command(['ps','-p',str(pid),'-o','lstart='])
            result['launch_wall_time'] = launch_wall
            time.sleep(12)
            result['initial_screen'] = record_screen(candidate['bundle_id'],folder,'game-initial')
            def ax(action, label, *values):
                target = folder/label
                record = command([build/'PlayCoverAX',action,str(pid),target,*values],timeout=15)
                write(folder/(label+'-command.json'),record)
                result['feature_actions'].append({'action':action,'label':label,'returncode':record['code']})
                return record['code'] == 0
            if not ax('dump','ax-initial'):
                result['feature_ui_status'] = 'BLOCKED_ACCESSIBILITY_PERMISSION_OR_AX_UNAVAILABLE'
            elif ax('press','settings-open','SIFASFeatures.Settings'):
                time.sleep(.6)
                ax('dump','ax-settings')
                if ax('press','camera-open','Adjust FOV bounds'):
                    time.sleep(.6)
                    if ax('set-text','camera-min','0','1.4375') and ax('set-text','camera-max','1','1.5'):
                        ax('press','camera-apply','Apply'); time.sleep(1)
                        result['fov_settings_screen'] = record_screen(candidate['bundle_id'],folder,'after-fov-input')
                for orientation in ['Portrait','Landscape']:
                    if not ax('press','settings-'+orientation,'SIFASFeatures.Settings'): break
                    time.sleep(.4)
                    if not ax('press','orientation-open-'+orientation,'Orientation lock'): break
                    time.sleep(.4)
                    if not ax('press','orientation-'+orientation,orientation): break
                    time.sleep(2)
                    result[orientation.lower()+'_screen'] = record_screen(candidate['bundle_id'],folder,'orientation-'+orientation)
                result['feature_ui_status'] = 'ACTIONS_RECORDED_REVIEW_RESULTING_UI_AND_DIAGNOSTICS'
            else:
                result['feature_ui_status'] = 'SETTINGS_BUTTON_ABSENT_FROM_AX_TREE'
            diagnostics = [path for path in (Path.home()/'Library/Containers'/candidate['bundle_id']).glob('**/SIFASFeatures-diagnostics.json')
                           if path.stat().st_mtime >= launch_wall]
            if diagnostics:
                try:
                    current = max(diagnostics,key=lambda p:p.stat().st_mtime)
                    result['reviewed_diagnostics'] = audit_diagnostics(current)
                    result['diagnostics_binding'] = {'actual_pid':pid,'launch_wall_time':launch_wall,'diagnostics_mtime':current.stat().st_mtime,
                        'bundle_identifier':candidate['bundle_id'],'candidate_sha256':candidate['sha256']}
                    write(folder/'feature-diagnostics-reviewed.json', result['reviewed_diagnostics'])
                except Exception as error: result['diagnostics_error'] = str(error)
            result['final_host'] = host_state(candidate['bundle_id'])
            result['process_alive_after_observation'] = bool(result['final_host'].get('applications'))
            result['final_screen'] = record_screen(candidate['bundle_id'],folder,'game-final')
            result['status'] = 'ACTUAL_IMPORT_AND_LAUNCH_OBSERVED_GAMEPLAY_UNPROVEN'
            try:os.kill(pid,signal.SIGTERM)
            except ProcessLookupError:pass
            assert wait_for(lambda:not host_state(candidate['bundle_id']).get('applications'),10), 'Observed app process did not exit before the next IPA import'
            stage('observed-'+candidate['region'])
        report['status'] = 'ACTUAL_PLAYCOVER_RUN_COMPLETED_WITH_EXPLICIT_LIMITS'
    except Exception as error:
        report.update(status='BLOCKED_ACTUAL_PLAYCOVER_QA', failure={'stage':report['stages'][-1]['stage'] if report['stages'] else 'start', 'type':type(error).__name__,'message':str(error)})
    finally:
        if server:
            server.terminate()
            try:server.wait(10)
            except subprocess.TimeoutExpired:server.kill()
            rows = []
            for line in (a.fixtures/'server-private.log').read_text(errors='replace').splitlines():
                match = re.search(r'\|\s*(\d{3})\s*\|.*\|\s*(GET|POST|HEAD)\s+"([^"?]+)',line)
                if match and re.fullmatch(r'/[A-Za-z0-9_./-]*',match[3]):
                    rows.append({'status':int(match[1]),'method':match[2],'path':match[3]})
            report['actual_server_request_metadata'] = rows
            report['actual_client_api_requests_observed'] = any(row['path'].startswith('/api/') for row in rows)
        write(a.evidence/'summary.json',report)
        build_receipt = a.evidence/'server-build.json'
        binding = json.loads(build_receipt.read_text()) if build_receipt.exists() else {}
        fixture = {'kind':'source-build','source_sha':manifest['server_source_ref'],
                   'binary_sha256':binding.get('server_binary_sha256',''), 'toolchain':'go1.22.12',
                   'build_args':['CGO_ENABLED=0','go','build','-trimpath'],
                   'submodule_refs':{'assets':'1b0154db2976ba345fb30f3516018bb04d408ce1','modtools':'524518e136107b27b89cf33cb2fd9eca0f8e5acc'}}
        flags = ['native_load','fov_actual','portrait','landscape','auto','intro_timing','mv_same_suit',
                 'mv_different_suits','mv_max_slots','mv_restore','no_new_costume_entries',
                 'actual_playcover_import','connection_login','server_traffic','fov_persistence']
        for candidate in manifest['candidates']:
            observed = next((item for item in report['candidates'] if item['region']==candidate['region']),{})
            verified = dict.fromkeys(flags,False)
            verified['actual_playcover_import'] = observed.get('actual_playcover_import') is True
            diagnostic = observed.get('reviewed_diagnostics',{})
            verified['native_load'] = diagnostic.get('running_on_mac') is True and diagnostic.get('settings_overlay_attached') is True
            candidate_report = {'schema_version':1,'status':'INCOMPLETE_ACTUAL_RUNTIME',
                'run':{'id':os.environ.get('GITHUB_RUN_ID',''),'head_sha':os.environ.get('GITHUB_SHA',''),
                       'workflow':'.github/workflows/playcover-qa.yml',
                       'url':'https://github.com/'+os.environ.get('GITHUB_REPOSITORY','tagundo/SIFAS-Client')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','')},
                'fixtures':{'region':candidate['region'],'client_asset_id':candidate['asset_id'],
                    'client_sha256':candidate['sha256'],'server_source_commit':manifest['server_source_ref'],'server_fixture':fixture},
                'verified':verified,'cases':{},'actual_observation_status':observed.get('status','NOT_REACHED'),
                'failed_stage':report.get('failure'),'qualification':report['qualification']}
            summary_ref = {'path':'summary.json','sha256':sha(a.evidence/'summary.json')}
            for flag in flags:
                candidate_report['cases'][flag] = {'status':'PASS' if verified[flag] else 'NOT_PROVEN',
                    'evidence':[summary_ref] if verified[flag] else []}
            write(a.evidence/candidate['region']/'candidate-runtime-report.json',candidate_report)
    print(json.dumps({'status':report['status'],'summary':str(a.evidence/'summary.json')},indent=2))
    return 0 if report['status'] == 'ACTUAL_PLAYCOVER_RUN_COMPLETED_WITH_EXPLICIT_LIMITS' else 1
if __name__ == '__main__': raise SystemExit(main())

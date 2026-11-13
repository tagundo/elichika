#!/usr/bin/env python3
"""Actual PlayCover GUI import/launch plus external bounded native evidence.

This never edits an IPA or imported app, injects a game agent, grants TCC,
modifies SIP/AMFI, or claims game login/playback from a living process.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import signal
import subprocess
import sys
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

def imported_app_ready(app, since, original_control=False):
    path = app/'Info.plist'
    try:
        if not path.exists() or path.stat().st_mtime < since-2:return False
        info = plistlib.loads(path.read_bytes())
        if not (app/info['CFBundleExecutable']).is_file():return False
        feature = (app/'Frameworks/SIFASFeatures.dylib').is_file()
        return not feature if original_control else feature
    except (OSError,ValueError,KeyError,TypeError):
        return False

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixtures', type=Path, required=True)
    p.add_argument('--evidence', type=Path, required=True)
    p.add_argument('--server-source', type=Path)
    p.add_argument('--server-binary', type=Path)
    a = p.parse_args()
    a.evidence.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((HERE/'manifest.json').read_text())
    selected_regions = manifest.get('execution_regions', ['GL', 'JP', 'GL_LOCAL'])
    assert isinstance(selected_regions,list) and selected_regions and len(selected_regions) == len(set(selected_regions))
    assert all(region in ['GL','JP','GL_LOCAL'] for region in selected_regions), 'Unknown QA region selection'
    selected_candidates = [next(row for row in manifest['candidates'] if row['region'] == region)
                           for region in selected_regions]
    selected_controls = [next(row for row in manifest.get('controls',[])
                              if row['region'] == region+'_ORIGINAL_CONTROL') for region in selected_regions]
    report = {'status': 'IN_PROGRESS', 'manifest': manifest, 'stages': [], 'candidates': [],
              'execution_regions': selected_regions,
              'planned_gui_import_order': [row['region'] for row in selected_controls+selected_candidates],
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
            'bootargs': ['sysctl','kern.bootargs'], 'displays': ['system_profiler','SPDisplaysDataType','-json'],
            'open_help':['open','-h']}.items()}
        write(a.evidence/'host.json', host)
        assert host['hardware']['stdout'].strip() == '1' and host['windowserver']['code'] == 0, 'Apple Silicon WindowServer required'
        assert 'amfi_get_out_of_my_way' not in host['bootargs']['stdout'], 'Unreviewed PlaySign environment'
        build = a.fixtures/'host-tools'; build.mkdir(exist_ok=True)
        for name in ['HostEvidence', 'PlayCoverAX', 'VisionQA', 'MetalHost', 'PlayCoverLaunch', 'VisionPlayCoverLaunch', 'AXPlayCoverLaunch']:
            arguments = ['xcrun','swiftc','-swift-version','5','-target','arm64-apple-macosx13.0',HERE/(name+'.swift'),'-o',build/name]
            if name in ['VisionQA','VisionPlayCoverLaunch','AXPlayCoverLaunch']:
                for framework in ['AppKit','ApplicationServices','CoreGraphics','Vision','ImageIO','CryptoKit']:
                    arguments += ['-framework',framework]
            if name == 'MetalHost': arguments += ['-framework','Metal']
            result = command(arguments, timeout=120)
            write(a.evidence/(name+'-compile.json'), result)
            assert result['code'] == 0, 'Swift helper compilation failed: '+name
        write(a.evidence/'actual-metal-devices.json',command([build/'MetalHost']))
        def host_state(bundle):
            result = command([build/'HostEvidence',bundle])
            if result['code']: return {'error': result}
            return json.loads(result['stdout'])
        def record_screen(bundle, folder, label):
            command([build/'HostEvidence',bundle,'--activate'])
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
        update_prompt_answered = False
        def settle_playcover_library(folder, label):
            # The pinned app asks this ordinary first-run Sparkle question.
            # Answer only its exact observed native button, then prove it is
            # gone. A hidden library tile behind a modal is not a valid target.
            nonlocal update_prompt_answered
            settled = folder/label
            settled.mkdir(parents=True, exist_ok=True)
            app_state = host_state(pcid).get('applications',[])
            assert len(app_state) == 1, 'Exactly one owned PlayCover process must settle its library'
            owned_pid = app_state[0]['pid']
            for attempt in range(2 if update_prompt_answered else 9):
                command([build/'HostEvidence',pcid,'--activate'])
                observed = command([build/'PlayCoverAX','dump',owned_pid,settled/('observe-'+str(attempt))])
                write(settled/('observe-'+str(attempt)+'-command.json'),observed)
                assert observed['code'] == 0, 'Unable to inspect the owned PlayCover first-run UI'
                tree = json.loads((settled/('observe-'+str(attempt))/'accessibility.json').read_text())
                titles = [item for item in tree['elements'] if item.get('AXRole') == 'AXStaticText'
                          and item.get('AXValue') == 'Check for updates automatically?']
                buttons = [item for item in tree['elements'] if item.get('AXRole') == 'AXButton'
                           and item.get('AXTitle') == 'Don’t Check' and item.get('enabled') is True]
                if titles or buttons:
                    assert len(titles) == 1 and len(buttons) == 1, 'Update prompt is not uniquely identified'
                    before = record_screen(pcid,settled,'observed-normal-update-prompt')
                    assert before['status'] == 'CAPTURED', 'Observe the normal update question before answering'
                    pressed = command([build/'PlayCoverAX','press',owned_pid,settled/'answer-dont-check','Don’t Check'])
                    write(settled/'answer-dont-check-command.json',pressed)
                    assert pressed['code'] == 0, 'Observed normal Don’t Check button could not be pressed'
                    time.sleep(1)
                    update_prompt_answered = True
                    after = command([build/'PlayCoverAX','dump',owned_pid,settled/'after-answer'])
                    write(settled/'after-answer-command.json',after)
                    assert after['code'] == 0
                    final_tree = json.loads((settled/'after-answer/accessibility.json').read_text())
                    assert not any(item.get('AXTitle') == 'Don’t Check' for item in final_tree['elements']), 'Normal update prompt remains open'
                    break
                time.sleep(1)
            state = host_state(pcid)
            visible = [window for app in state.get('applications',[]) for window in app.get('windows',[])
                       if window.get('kCGWindowLayer') == 0 and window.get('kCGWindowBounds',{}).get('Width',0) > 50]
            assert len(visible) == 1, 'PlayCover has another visible window or modal; library input is blocked'
            assert visible[0].get('kCGWindowName') == 'App Library', 'The only observed PlayCover window must be its library'
            final_screen = record_screen(pcid,settled,'settled-library')
            assert final_screen['status'] == 'CAPTURED'
            write(settled/'settlement.json',{'status':'ONLY_ACTUAL_LIBRARY_WINDOW_VISIBLE',
                'owned_pid':owned_pid,'normal_update_question_answered':update_prompt_answered,
                'no_system_security_or_permission_change':True,'state':state,'screen':final_screen})

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
        pc = Path('/Applications/PlayCover.app')
        copied = command(['ditto',source_app,pc], timeout=90)
        if copied['code']:
            copied = command(['sudo','-n','ditto',source_app,pc],timeout=90)
        write(a.evidence/'normal-applications-install.json',copied)
        assert copied['code'] == 0
        info = plistlib.loads((pc/'Contents/Info.plist').read_bytes())
        pcid = info['CFBundleIdentifier']
        assert pcid == 'io.playcover.PlayCover'
        signature = command(['codesign','--verify','--deep','--strict','--verbose=4',pc])
        write(a.evidence/'playcover-signature.json', signature)
        assert signature['code'] == 0, 'Pinned PlayCover app signature failed'
        for key, value in [('AlwaysInstallPlayTools','true'),('ShowInstallPopup','false'),('ShowAppStorePopup','false')]:
            assert command(['defaults','write',pcid,key,'-bool',value])['code'] == 0
        stage('open-actual-playcover')
        opened = command(['open','-a',pc])
        write(a.evidence/'playcover-open.json', opened)
        assert opened['code'] == 0
        assert wait_for(lambda: host_state(pcid).get('applications'), 30), 'PlayCover did not run'
        command([build/'HostEvidence',pcid,'--activate'])
        wait_for(lambda:any(app.get('windows') for app in host_state(pcid).get('applications',[])),30)
        settle_playcover_library(a.evidence,'initial-first-run-ui')
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
        def configure_plain_preferences(bundle,folder):
            preferences = Path.home()/'Library/Containers'/bundle/'Data/Library/Preferences'/(bundle+'.plist')
            preferences.parent.mkdir(parents=True,exist_ok=True)
            domain = str(preferences)[:-6]
            records = [command(['defaults','write',domain,'ServerEndpoint','-string','http://127.0.0.1:8080']),
                       command(['defaults','write',domain,'SIFASDiagnosticsEnabled','-bool','true'])]
            assert all(item['code'] == 0 for item in records), 'Supported task-owned app preferences could not be configured'
            value = plistlib.loads(preferences.read_bytes())
            assert value.get('ServerEndpoint') == 'http://127.0.0.1:8080' and value.get('SIFASDiagnosticsEnabled') is True
            write(folder/'plain-launch-preferences.json',{'scope':'Only the two supported connection/diagnostic settings in this fresh synthetic app container',
                'keys':['ServerEndpoint','SIFASDiagnosticsEnabled'],'supported_values_verified':True,'commands':records})
        for candidate in selected_controls + selected_candidates:
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
                return imported_app_ready(app,begin,candidate.get('role') == 'original-control')
            if imported['code'] or not wait_for(installed,180):
                result.update(status='FAIL_GUI_IMPORT', playcover_state=host_state(pcid))
                result['import_screen'] = record_screen(pcid,folder,'import-blocker')
                stage('import-failed-'+candidate['region'])
                continue
            time.sleep(3)
            result['actual_playcover_import'] = True
            # Refresh PlayCover's normal app model after replacing a bundle.
            # GL and Local GL intentionally share a bundle ID; its prior card
            # title/object must not launch a stale real Info.plist alias.
            for running_pc in host_state(pcid).get('applications',[]):
                os.kill(running_pc['pid'],signal.SIGTERM)
            assert wait_for(lambda:not host_state(pcid).get('applications'),10), 'Owned PlayCover process did not stop for a fresh library scan'
            reopened = command(['open','-a',pc])
            assert reopened['code'] == 0 and wait_for(lambda:host_state(pcid).get('applications'),30)
            command([build/'HostEvidence',pcid,'--activate'])
            assert wait_for(lambda:any(app.get('windows') for app in host_state(pcid).get('applications',[])),30)
            settle_playcover_library(folder,'fresh-library-first-run-ui')
            write(folder/'fresh-library-process.json',{'reopen':reopened,'state':host_state(pcid),
                'scope':'Only owned disposable PlayCover process restarted; current imported bundle must be rescanned'})
            stage('verify-imported-bundle-'+candidate['region'])
            footprint = command([sys.executable,HERE/'verify_playtools_footprint.py','--playcover-dmg',dmg,
                '--pinned-playcover-app',source_app,'--installed-game',app,'--candidate-ipa',ipa,
                '--candidate-sha256',candidate['sha256'],'--proof-dir',folder/'playtools-footprint'],timeout=180)
            write(folder/'playtools-footprint-command.json',footprint)
            result['pinned_standard_playtools_verified'] = footprint['code'] == 0
            additional = []
            if candidate.get('role') == 'original-control': additional.append('--original-control')
            if footprint['code'] == 0:
                allowed = json.loads((folder/'playtools-footprint/verifier-arguments.json').read_text())
                for value in allowed['allow_dylib']:additional += ['--allow-dylib',value]
                for value in allowed['allow_added_resource']:additional += ['--allow-added-resource',value]
            verified = command([sys.executable,HERE/'verify_playcover_install.py','--installed-app',app,
                '--candidate-ipa',ipa,'--candidate-sha256',candidate['sha256'],'--proof-dir',folder/'install-verification',
                '--playcover-app',pc,'--playcover-dmg',dmg,'--expected-entitlements',expected_path,*additional],timeout=180)
            write(folder/'verifier-command.json', verified)
            result['bundle_verification_passed'] = verified['code'] == 0
            if footprint['code'] != 0 or verified['code'] != 0:
                result['status'] = 'FAIL_VERIFICATION_BEFORE_GAME_LAUNCH'
                stage('verification-failed-'+candidate['region'])
                continue
            stage('launch-imported-app-'+candidate['region'])
            installed_info = plistlib.loads((app/'Info.plist').read_bytes())
            display = installed_info.get('CFBundleDisplayName') or installed_info['CFBundleName']
            alias = Path.home()/'Applications/PlayCover'/(display+'.app')
            assert wait_for(lambda:(alias/'Info.plist').exists(),15), 'Normal PlayCover launch alias was not created'
            alias_info = plistlib.loads((alias/'Info.plist').read_bytes())
            assert alias_info == installed_info, 'Normal launch alias metadata differs from verified imported app'
            assert {entry.name for entry in alias.iterdir()} == {entry.name for entry in app.iterdir()}, 'Normal PlayCover launch alias has an incomplete top-level inventory'
            assert (alias/installed_info['CFBundleExecutable']).exists(), 'Normal PlayCover launch alias executable is absent'
            alias_entries = {}
            for entry in alias.iterdir():
                if entry.name == 'Info.plist':continue
                assert entry.is_symlink() and entry.resolve(strict=True) == (app/entry.name).resolve(strict=True), 'Alias entry is not the normal imported-app symlink'
                alias_entries[entry.name] = str(entry.resolve())
            write(folder/'normal-playcover-launch-alias.json',{'alias':str(alias),'entries':alias_entries,'metadata_equal':True})
            private_stdout = a.fixtures/(candidate['region']+'-launch.stdout')
            private_stderr = a.fixtures/(candidate['region']+'-launch.stderr')
            configure_plain_preferences(candidate['bundle_id'],folder)
            result['launch_strategy'] = 'actual-PlayCover-library-tile-OS-doubleclick-with-supported-container-preferences'
            command([build/'HostEvidence',pcid,'--activate'])
            result['actual_playcover_library_screen'] = record_screen(pcid,folder,'playcover-imported-library')
            pc_apps = host_state(pcid).get('applications',[])
            assert len(pc_apps) == 1, 'Exactly one real PlayCover process must own the library window'
            pc_pid = pc_apps[0]['pid']
            write(folder/'playcover-imported-library-ax-command.json',
                  command([build/'PlayCoverAX','dump',pc_pid,folder/'playcover-imported-library-ax']))
            launch_wall = time.time()
            launch = command([build/'AXPlayCoverLaunch','--pid',pc_pid,'--proof-dir',
                              folder/'actual-library-doubleclick','--exact',display],timeout=45)
            write(folder/'normal-launch.json',launch)
            result['actual_library_doubleclick_delivered'] = launch['code'] == 0
            def startup_capture(observed_pid,label,since=None,stdout_file=None,stderr_file=None):
                record = command([sys.executable,HERE/'capture_startup.py','--bundle-id',candidate['bundle_id'],
                    '--executable',installed_info['CFBundleExecutable'],'--pid',str(observed_pid),'--since',str(launch_wall if since is None else since),
                    '--private-log-root',a.fixtures,'--launch-stdout',private_stdout if stdout_file is None else stdout_file,
                    '--launch-stderr',private_stderr if stderr_file is None else stderr_file,
                    '--proof-dir',folder/label],timeout=60)
                write(folder/(label+'-command.json'),record)
            running = wait_for(lambda:host_state(candidate['bundle_id']).get('applications'),30) if launch['code'] == 0 else None
            if not running:
                result.update(status='FAIL_ACTUAL_LIBRARY_TILE_LAUNCH', launch=launch)
                result['actual_library_launch_blocker'] = record_screen(pcid,folder,'actual-library-launch-blocker')
                write(folder/'actual-library-launch-blocker-ax-command.json',
                      command([build/'PlayCoverAX','dump',pc_pid,folder/'actual-library-launch-blocker-ax']))
                startup_capture(0,'startup-no-observed-pid')
                stage('launch-failed-'+candidate['region'])
                continue
            pid = running[0]['pid']; result['actual_pid'] = pid
            # The real GUI path performs PlayCover's normal launch-time repairs.
            # Recheck its result against the same original IPA and pinned source
            # rules; only that verified installed image may provide runtime proof.
            post_footprint = command([sys.executable,HERE/'verify_playtools_footprint.py','--playcover-dmg',dmg,
                '--pinned-playcover-app',source_app,'--installed-game',app,'--candidate-ipa',ipa,
                '--candidate-sha256',candidate['sha256'],'--proof-dir',folder/'post-gui-playtools-footprint'],timeout=180)
            write(folder/'post-gui-playtools-footprint-command.json',post_footprint)
            post_allowed = []
            if candidate.get('role') == 'original-control':post_allowed.append('--original-control')
            if post_footprint['code'] == 0:
                allowed = json.loads((folder/'post-gui-playtools-footprint/verifier-arguments.json').read_text())
                for value in allowed['allow_dylib']:post_allowed += ['--allow-dylib',value]
                for value in allowed['allow_added_resource']:post_allowed += ['--allow-added-resource',value]
            post_verified = command([sys.executable,HERE/'verify_playcover_install.py','--installed-app',app,
                '--candidate-ipa',ipa,'--candidate-sha256',candidate['sha256'],'--proof-dir',folder/'post-gui-install-verification',
                '--playcover-app',pc,'--playcover-dmg',dmg,'--expected-entitlements',expected_path,*post_allowed],timeout=180)
            write(folder/'post-gui-verifier-command.json',post_verified)
            result['post_actual_gui_launch_bundle_verified'] = post_footprint['code'] == 0 and post_verified['code'] == 0
            if not result['post_actual_gui_launch_bundle_verified']:
                result['status'] = 'FAIL_VERIFICATION_AFTER_ACTUAL_GUI_LAUNCH'
                try:os.kill(pid,signal.SIGTERM)
                except ProcessLookupError:pass
                assert wait_for(lambda:not host_state(candidate['bundle_id']).get('applications'),10)
                stage('post-gui-verification-failed-'+candidate['region'])
                continue
            result['actual_process_start'] = command(['ps','-p',str(pid),'-o','lstart='])
            result['launch_wall_time'] = launch_wall
            time.sleep(12)
            alive = host_state(candidate['bundle_id'])
            if not any(item['pid'] == pid for item in alive.get('applications',[])):
                result.update(status='FAIL_PROCESS_EXITED_BEFORE_VISIBLE_UI',process_alive_after_observation=False,
                              host_after_early_exit=alive)
                time.sleep(3)
                startup_capture(pid,'startup-early-exit')
                stage('early-process-exit-'+candidate['region'])
                continue
            startup_capture(pid,'startup-visible-process')
            command([build/'HostEvidence',candidate['bundle_id'],'--activate'])
            vision_initial = command([build/'VisionQA','snapshot','--pid',str(pid),'--proof-dir',folder/'vision-initial'],timeout=30)
            write(folder/'vision-initial-command.json',vision_initial)
            result['initial_screen'] = record_screen(candidate['bundle_id'],folder,'game-initial')
            def ax(action, label, *values):
                target = folder/label
                record = command([build/'PlayCoverAX',action,str(pid),target,*values],timeout=15)
                write(folder/(label+'-command.json'),record)
                result['feature_actions'].append({'action':action,'label':label,'returncode':record['code']})
                return record['code'] == 0
            if candidate.get('role') == 'original-control':
                ax('dump','ax-original-control')
                result['feature_ui_status'] = 'ORIGINAL_SOURCE_CONTROL_WITHOUT_NEW_FEATURE_LIBRARY'
            else:
                ax('dump','ax-initial')
                from game_ui_steps import run_steps
                result['native_ui_progression'] = run_steps(pid,build,folder/'native-ui-progression',
                                                            candidate['bundle_id'],candidate['region'])
                result['feature_ui_status'] = result['native_ui_progression']['status']
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
            if not result['process_alive_after_observation']:
                time.sleep(3)
                startup_capture(pid,'startup-exited-during-ui')
            result['final_screen'] = record_screen(candidate['bundle_id'],folder,'game-final')
            command([build/'HostEvidence',candidate['bundle_id'],'--activate'])
            write(folder/'vision-final-command.json',command([build/'VisionQA','snapshot','--pid',str(pid),'--proof-dir',folder/'vision-final'],timeout=30))
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
            report['actual_client_api_requests_observed'] = any(row['path'] in ['/login/startup','/login/login','/bootstrap/fetchBootstrap','/liveMv/start'] for row in rows)
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
                       'repository':os.environ.get('GITHUB_REPOSITORY','tagundo/elichika'),'workflow':'.github/workflows/playcover-qa.yml',
                       'url':'https://github.com/'+os.environ.get('GITHUB_REPOSITORY','tagundo/SIFAS-Client')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','')},
                'fixtures':{'region':candidate['region'],'client_asset_id':candidate['asset_id'],
                    'original_asset_id':candidate.get('original_asset_id'),'original_sha256':candidate.get('original_sha256'),
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

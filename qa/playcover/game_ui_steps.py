"""Bounded real OS input against freshly observed PlayCover client UI.

No game callbacks, state setters, implicit password entry or game success flags.
AX actions require a unique exact enabled label. OCR actions require the
existing strict fresh-PID/window/two-capture confidence checks in VisionQA.
"""
import json
from pathlib import Path
import subprocess
import time

from verify_playcover_install import audit_diagnostics


def run_steps(pid, tools_dir, folder, bundle_id, region):
    tools_dir, folder = Path(tools_dir), Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    report = {'status': 'OBSERVATION_STARTED', 'pid': pid, 'region': region,
              'actions': [], 'observations': [], 'game_login_proven': False,
              'mv_playback_proven': False, 'fov_actual_camera_proven': False}
    sequence = 0

    def save():
        (folder / 'ui-progression.json').write_text(json.dumps(report, indent=2) + '\n')

    def command(argv, label, timeout=25):
        nonlocal sequence
        sequence += 1
        proof = folder / f'{sequence:02d}-{label}'
        try:
            result = subprocess.run([str(x) for x in argv(proof)], text=True,
                                    capture_output=True, timeout=timeout)
            row = {'label': label, 'returncode': result.returncode,
                   'stderr': result.stderr[-1500:], 'proof_directory': proof.name}
        except subprocess.TimeoutExpired:
            row = {'label': label, 'returncode': -1, 'error': 'OS observation/input timed out',
                   'proof_directory': proof.name}
        report['actions'].append(row)
        save()
        return row['returncode'] == 0, proof

    def activate():
        subprocess.run([str(tools_dir / 'HostEvidence'), bundle_id, '--activate'],
                       capture_output=True, timeout=15)

    def snapshot(label):
        activate()
        ok, proof = command(lambda out: [tools_dir / 'VisionQA', 'snapshot', '--pid', pid,
                                         '--proof-dir', out], label)
        if ok:
            value = json.loads((proof / 'initial.json').read_text())
            report['observations'].append({'label': label, 'proof_directory': proof.name,
                'window': value['window'], 'screenshot_sha256': value['screenshotSHA256'],
                'captions': [{'text': row['text'], 'confidence': row['confidence']}
                             for row in value['text']]})
            save()
            return value
        return None

    def act(caption, label, ax_identifier=None):
        activate()
        ok, _ = command(lambda out: [tools_dir / 'PlayCoverAX', 'press', pid, out,
                                     ax_identifier or caption], label + '-ax')
        if not ok:
            ok, _ = command(lambda out: [tools_dir / 'VisionQA', 'click', '--pid', pid,
                                          '--proof-dir', out, '--exact', caption], label + '-ocr')
        if ok:
            time.sleep(.8)
        return ok

    def observe_diagnostics(label, since):
        files = [path for path in (Path.home() / 'Library/Containers' / bundle_id).glob('**/SIFASFeatures-diagnostics.json')
                 if path.stat().st_mtime >= since]
        if files:
            path = max(files, key=lambda p: p.stat().st_mtime)
            report['observations'].append({'label': label, 'fresh_since_action': True,
                                          'diagnostics': audit_diagnostics(path)})
            save()

    def settings(label):
        return act('Settings', label, 'SIFASFeatures.Settings')

    initial = snapshot('before-actions')
    if initial and sum(row['text'] == 'English' and row['confidence'] >= .75 for row in initial['text']) == 1:
        if act('English', 'select-visible-English'):
            time.sleep(2)
            snapshot('after-language-selection')

    if not settings('open-client-settings'):
        report['status'] = 'NO_UNIQUE_OBSERVED_SETTINGS_ACTION'
        snapshot('settings-action-blocked')
        save()
        return report
    snapshot('client-settings-dialog')
    command(lambda out: [tools_dir / 'PlayCoverAX', 'dump', pid, out], 'client-settings-ax')

    if act('Adjust FOV bounds', 'open-fov-editor'):
        snapshot('fov-editor')
        first, _ = command(lambda out: [tools_dir / 'PlayCoverAX', 'set-text', pid, out, '0', '0.8125'], 'fov-minimum')
        second, _ = command(lambda out: [tools_dir / 'PlayCoverAX', 'set-text', pid, out, '1', '0.9375'], 'fov-maximum')
        since = time.time()
        if first and second and act('Apply', 'apply-fov'):
            snapshot('after-fov-apply')
            observe_diagnostics('fov-configuration-after-actual-native-input', since)
        else:
            act('Cancel', 'cancel-unconfirmed-fov-input')
    else:
        # The dialog may remain open after a failed exact action. Do not send a
        # second unrelated menu action into an unconfirmed screen.
        report['status'] = 'CLIENT_SETTINGS_OBSERVED_FOV_ACTION_UNAVAILABLE'
        save()
        return report

    for orientation in ['Portrait', 'Landscape', 'Auto']:
        if not settings('settings-for-' + orientation):
            break
        if not act('Orientation lock', 'open-orientation-' + orientation):
            break
        snapshot('orientation-options-' + orientation)
        since = time.time()
        if not act(orientation, 'choose-orientation-' + orientation):
            break
        time.sleep(2)
        snapshot('after-orientation-' + orientation)
        observe_diagnostics('orientation-after-actual-native-input-' + orientation, since)

    if settings('settings-for-intro-enable'):
        since = time.time()
        if act('Enable fast intro', 'enable-fast-intro'):
            snapshot('after-enable-fast-intro')
            observe_diagnostics('intro-enabled-after-actual-native-input', since)
            if settings('settings-for-intro-disable'):
                since = time.time()
                if act('Disable fast intro', 'disable-fast-intro'):
                    snapshot('after-disable-fast-intro')
                    observe_diagnostics('intro-disabled-after-actual-native-input', since)

    if settings('settings-for-connection'):
        if act('Connection', 'open-connection'):
            snapshot('actual-connection-dialog')
            command(lambda out: [tools_dir / 'PlayCoverAX', 'dump', pid, out], 'actual-connection-ax')
            act('Done', 'close-connection')
    snapshot('after-bounded-native-actions')
    report['status'] = 'REAL_OS_ACTIONS_RECORDED_GAMEPLAY_AND_CAMERA_EFFECT_UNPROVEN'
    save()
    return report

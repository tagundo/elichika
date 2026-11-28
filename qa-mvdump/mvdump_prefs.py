"""Pre-seed the GL client's live 3D quality before its first launch (CI-time only).

The client picks its default live quality from m_live_quality_recommend_graphic, which only
knows Apple/PowerVR/Adreno/Mali GPU names. Redroid's software GPU matches none, and run 2 ran
at Low 3D (40: 640p, no base light, rim light, cubemap, post effect or swing bones), which
cannot verify those stage features. The client keeps the user's choice in Unity PlayerPrefs
under the key LiveSettingQualityMode (one of its PlayerPrefsKey names in global-metadata).
Writing it before Unity first starts makes the client use it like a chosen setting.

The dump header records the quality the client actually applied (quality.values.Quality), so
a wrong key or value shows up there; the prefs before and after are kept as evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile

KEY = 'LiveSettingQualityMode'
HEADER = "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n"


def prefs_path(package):
    return f'/data/data/{package}/shared_prefs/{package}.v2.playerprefs.xml'


def merged(existing, quality):
    entry = f'    <int name="{KEY}" value="{int(quality)}" />\n'
    if existing.strip() and '<map' in existing:
        text = re.sub(r'\s*<int name="' + re.escape(KEY) + r'" value="-?\d+"\s*/>\n?', '\n', existing)
        if '<map />' in text:
            text = text.replace('<map />', '<map>\n' + entry + '</map>')
        else:
            text = text.replace('</map>', entry + '</map>', 1)
        return text
    return HEADER + '<map>\n' + entry + '</map>\n'


def preseed(device, package, quality, evidence):
    path = prefs_path(package)
    folder = path.rsplit('/', 1)[0]
    info = {'key': KEY, 'quality': int(quality), 'path': path}
    owner = device.shell('stat', '-c', '%u', f'/data/data/{package}').strip()
    group = device.shell('stat', '-c', '%g', f'/data/data/{package}').strip()
    info['owner'] = f'{owner}:{group}'
    existing = device.shell('sh', '-c', f'cat {path} 2>/dev/null; true')
    info['existing'] = existing[-2000:]
    text = merged(existing, quality)
    with tempfile.NamedTemporaryFile('w', suffix='.xml', delete=False) as handle:
        handle.write(text)
        local = handle.name
    staging = '/data/local/tmp/mvdump-playerprefs.xml'
    device.adb('push', local, staging)
    Path(local).unlink(missing_ok=True)
    device.shell('mkdir', '-p', folder)
    device.shell('cp', staging, path)
    device.shell('rm', '-f', staging)
    device.shell('chown', f'{owner}:{group}', folder, path)
    device.shell('chmod', '771', folder)
    device.shell('chmod', '660', path)
    try:
        device.shell('restorecon', '-R', folder)
    except Exception as error:  # SELinux may be permissive on Redroid; keep going
        info['restorecon'] = f'{type(error).__name__}: {str(error)[:120]}'
    info['written'] = device.shell('sh', '-c', f'cat {path}')[-2000:]
    info['ls'] = device.shell('sh', '-c', f'ls -laZ {folder} 2>/dev/null || ls -la {folder}')[-600:]
    info['ok'] = f'name="{KEY}" value="{int(quality)}"' in info['written']
    Path(evidence, 'mvdump-prefs-preseed.json').write_text(json.dumps(info, indent=1) + '\n')
    print('@@PREFS ' + json.dumps({k: info[k] for k in ('key', 'quality', 'path', 'owner', 'ok')}), flush=True)
    return info


def read_quality_prefs(sh, package):
    """Read-only: the PlayerPrefs lines about live settings, for the dump's evidence."""
    out = str(sh(f"grep -iE 'Quality|LiveSetting' {prefs_path(package)} 2>/dev/null; true"))
    return [' '.join(line.split()) for line in out.splitlines() if line.strip()][:40]

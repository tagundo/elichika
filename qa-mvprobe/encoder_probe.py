#!/usr/bin/env python3
"""Run encoder_probe.js inside an ordinary app process on a Redroid device and print the result.

Prints one @@PROBE line per attempt and a @@PROBE-SUMMARY line, and writes the full JSON to --out.
No game is involved: this only answers whether this Redroid configuration can run the FOVMOD
exporter's encoders (flexible-YUV input images for H.264/HEVC, 16-bit PCM for AAC).
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


def adb(serial, *args, timeout=60):
    return subprocess.run(['adb', '-s', serial, *args], capture_output=True, text=True, timeout=timeout).stdout.strip()


def target_pid(serial):
    for package in ('com.android.launcher3', 'com.android.settings'):
        if package == 'com.android.settings':
            adb(serial, 'shell', 'am', 'start', '-W', '-n', 'com.android.settings/.Settings')
            time.sleep(3)
        pid = adb(serial, 'shell', 'pidof', '-s', package)
        if pid.isdigit():
            return package, int(pid)
    raise SystemExit('No app process to host the probe')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', default='127.0.0.1:5555')
    parser.add_argument('--agent', type=Path, default=Path(__file__).with_name('encoder_probe.js'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--label', default='')
    args = parser.parse_args()
    import frida
    package, pid = target_pid(args.serial)
    adb(args.serial, 'forward', 'tcp:27042', 'tcp:27042')
    device = frida.get_device_manager().add_remote_device('127.0.0.1:27042')
    session = device.attach(pid)
    script = session.create_script(args.agent.read_text())
    script.on('message', lambda message, data: print('@@AGENT', json.dumps(message)[:800], flush=True))
    script.load()
    opts = {'sizes': [[1280, 720], [1920, 1080], [640, 360]], 'colorFormats': [2135033992, 19, 21],
            'audio': [[48000, 2], [44100, 2]]}
    result = script.exports_sync.run(opts)
    session.detach()
    result.update(label=args.label, host_package=package)
    args.out.write_text(json.dumps(result, indent=1) + '\n')
    print('@@PROBE-DEVICE', json.dumps(result['device']), flush=True)
    for kind, entries in result['encoders'].items():
        print('@@PROBE-ENCODERS', kind, json.dumps(entries), flush=True)
    for entry in result['video'] + result['audio']:
        print('@@PROBE', json.dumps(entry, separators=(',', ':')), flush=True)
    summary = {
        'label': args.label, 'release': result['device'].get('release'),
        'video_ok': sorted({f"{v['name']} {v['mime']} {v['w']}x{v['h']} cf={v['colorFormat']}" for v in result['video'] if v.get('ok')}),
        'client_video_ok': any(v.get('ok') and v['mime'] == 'video/avc' and v['colorFormat'] == 2135033992 and (v['w'], v['h']) == (1280, 720)
                               for v in result['video']),
        'audio_ok': sorted({f"{a['name']} {a['rate']}/{a['channels']}" for a in result['audio'] if a.get('ok')}),
        'first_video_error': next((v.get('error') for v in result['video'] if not v.get('ok')), None),
        'first_audio_error': next((a.get('error') for a in result['audio'] if not a.get('ok')), None),
    }
    print('@@PROBE-SUMMARY', json.dumps(summary), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())

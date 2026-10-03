"""Bounded read-only scene/exception observer for an isolated Android client."""
import argparse
import json
from pathlib import Path
import subprocess
import threading
import time
import frida

p = argparse.ArgumentParser()
p.add_argument('--evidence', type=Path, required=True)
p.add_argument('--duration', type=int, default=2700)
args = p.parse_args()
args.evidence.mkdir(parents=True, exist_ok=True)
deadline = time.monotonic() + args.duration
while time.monotonic() < deadline:
    result = subprocess.run(['adb', '-s', '127.0.0.1:5555', 'shell', 'pidof', 'com.klab.lovelive.allstars.global'], capture_output=True, text=True)
    if result.stdout.strip():
        pid = int(result.stdout.split()[0]); break
    time.sleep(2)
else:
    raise RuntimeError('Game process did not start')
subprocess.run(['adb', '-s', '127.0.0.1:5555', 'forward', 'tcp:27042', 'tcp:27042'], check=True, capture_output=True)
session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid)
lock = threading.Lock()
log = (args.evidence / 'scene-events.jsonl').open('w', buffering=1)
def message(value, data):
    with lock:
        log.write(json.dumps(value, ensure_ascii=False) + '\n')
script = session.create_script(Path('qa-runtime/node_modules/frida-il2cpp-bridge/dist/index.js').read_text() + '\n' + Path('tests/unity-observer.js').read_text())
script.on('message', message)
try:
    script.load()
    print(json.dumps(script.exports_sync.ready()), flush=True)
    while time.monotonic() < deadline:
        try:
            snapshot = script.exports_sync.snapshot()
            (args.evidence / 'scene-snapshot.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n')
            message({'type': 'send', 'payload': {'kind': 'snapshot', **snapshot}}, None)
        except Exception as e:
            message({'type': 'observer_error', 'error': str(e)}, None)
        time.sleep(10)
finally:
    session.detach()
    log.close()

"""Reconnectable read-only observer for an isolated Android game client."""
import argparse
import json
from pathlib import Path
import subprocess
import threading
import time
import frida

p = argparse.ArgumentParser()
p.add_argument('--evidence', type=Path, required=True)
p.add_argument('--duration', type=int, default=5400)
args = p.parse_args()
args.evidence.mkdir(parents=True, exist_ok=True)
deadline = time.monotonic() + args.duration
lock = threading.Lock()
log = (args.evidence / 'scene-events.jsonl').open('a', buffering=1)
def message(value, data=None):
    with lock:
        log.write(json.dumps(value, ensure_ascii=False) + '\n')
remote = frida.get_device_manager().add_remote_device('127.0.0.1:27042')
source = Path('qa-runtime/node_modules/frida-il2cpp-bridge/dist/index.js').read_text() + '\n' + Path('tests/unity-observer.js').read_text()
generation = 0
last_phase = None
while time.monotonic() < deadline:
    session = None
    try:
        process = subprocess.run(['adb', '-s', '127.0.0.1:5555', 'shell', 'pidof', 'com.klab.lovelive.allstars.global'], capture_output=True, text=True, timeout=15)
        if not process.stdout.strip():
            time.sleep(2)
            continue
        pid = int(process.stdout.split()[0])
        subprocess.run(['adb', '-s', '127.0.0.1:5555', 'forward', 'tcp:27042', 'tcp:27042'], check=True, capture_output=True, timeout=15)
        session = remote.attach(pid)
        generation += 1
        script = session.create_script(source)
        script.on('message', message)
        script.load()
        print(json.dumps({'generation': generation, 'pid': pid, 'ready': script.exports_sync.ready()}), flush=True)
        message({'type': 'observer_attachment', 'generation': generation, 'pid': pid})
        phase_path = args.evidence / 'phase-request.json'
        while time.monotonic() < deadline:
            if phase_path.exists():
                request = json.loads(phase_path.read_text())
                phase_token = (generation, request.get('id'))
                if phase_token != last_phase:
                    reset = script.exports_sync.phase(request['id'])
                    message({'type': 'phase_reset', 'generation': generation, **reset})
                    last_phase = phase_token
            snapshot = script.exports_sync.snapshot()
            snapshot.update(observer_generation=generation, client_pid=pid)
            (args.evidence / 'scene-snapshot.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n')
            message({'type': 'send', 'payload': {'kind': 'snapshot', **snapshot}})
            time.sleep(10)
    except Exception as exc:
        message({'type': 'observer_error', 'generation': generation, 'error': str(exc)})
        print('OBSERVER_RECONNECT ' + str(exc), flush=True)
        time.sleep(2)
    finally:
        if session:
            try:
                session.detach()
            except Exception:
                pass
log.close()

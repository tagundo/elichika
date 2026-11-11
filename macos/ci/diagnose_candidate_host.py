"""Run the unchanged signed-app smoke gate with external, read-only diagnostics."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request


CATALOG = r'''
import hashlib,json,os,pathlib,sys,time
resources,root,library=map(pathlib.Path,sys.argv[1:])
sys.path.insert(0,str(resources/'python-app'));os.chdir(root)
os.environ['SUKUSTA_DIR']=str(library)
from webtools.core import game_models
before=time.monotonic();result=game_models.catalog(root,language='en',region='gl',character='',search='')
print(json.dumps({'seconds':time.monotonic()-before,'characters':len(result['characters']),
 'costumes':len(result['costumes']),'region':result['region'],
 'module_sha256':hashlib.sha256(pathlib.Path(game_models.__file__).read_bytes()).hexdigest(),
 'private_prefix':str(pathlib.Path(sys.prefix).resolve()),'root':str(root)}))
'''


def command(arguments, timeout=8):
    start = time.monotonic()
    try:
        result = subprocess.run(arguments, text=True, capture_output=True, timeout=timeout)
        return {'seconds': time.monotonic()-start, 'code': result.returncode,
                'stdout': result.stdout[-100000:], 'stderr': result.stderr[-10000:]}
    except subprocess.TimeoutExpired as error:
        return {'seconds': time.monotonic()-start, 'timeout': True,
                'stdout': (error.stdout or b'').decode(errors='replace')[-100000:]}
    except OSError as error:
        return {'seconds': time.monotonic()-start, 'error': type(error).__name__+': '+str(error)}


def probe(port, path):
    start = time.monotonic()
    try:
        with urllib.request.urlopen('http://127.0.0.1:'+str(port)+path, timeout=4) as response:
            body = response.read(65536)
            return {'port': port, 'path': path, 'status': response.status,
                    'seconds': time.monotonic()-start, 'bytes': len(body)}
    except urllib.error.HTTPError as error:
        return {'port': port, 'path': path, 'status': error.code,
                'seconds': time.monotonic()-start, 'scope': 'Unauthenticated liveness only; no UI secret extracted.'}
    except Exception as error:
        return {'port': port, 'path': path, 'seconds': time.monotonic()-start,
                'error': type(error).__name__+': '+str(error)}


def snapshot(app, evidence, state, mark):
    destination = evidence/'host-diagnostics'/mark
    destination.mkdir(parents=True, exist_ok=False)
    pid = int(state.get('python_pid', 0))
    result = {'scope': 'Outside signed app; no resource edits, fetch/player patches, request replacements or secret extraction.',
              'stage': state.get('stage'), 'elapsed_seconds': state.get('elapsed_seconds'),
              'python_pid': pid, 'go_pid': state.get('current_go_pid', state.get('go_pid')),
              'ready_ports': state.get('ready_ports', []), 'observed_at': time.time()}
    result['processes'] = command(['/bin/ps','-axo','pid,ppid,stat,etime,pcpu,comm'])
    result['connections'] = command(['/usr/sbin/lsof','-nP','-a','-p',str(pid),'-iTCP'])
    cwd = command(['/usr/sbin/lsof','-a','-p',str(pid),'-d','cwd','-Fn'])
    result['cwd'] = cwd
    roots = [row[1:] for row in cwd.get('stdout','').splitlines() if row.startswith('n/')]
    ports = [int(value) for value in state.get('ready_ports', []) if isinstance(value,int)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as workers:
        futures = [workers.submit(probe, port, path) for port in ports
                   for path in ('/api/tools','/api/viewer/game/catalog?lang=en&region=gl&character=&search=')]
        result['http_liveness'] = [future.result() for future in futures]
    if roots:
        resources = app/'Contents/Resources'
        direct = command([str(resources/'runtime/arm64/python/bin/python3'),'-I','-B','-c',CATALOG,
                          str(resources), roots[0], str(evidence/'native-app-data/sukusta')], timeout=6)
        result['same_db_private_catalog'] = direct
    # Standard macOS sampling inspects live process stacks without registering
    # signals or injecting Python code into the signed process.
    webkit = command(['/usr/bin/pgrep','-f','com.apple.WebKit.Networking'])
    targets = [(pid, 'private-python')]
    go_pid = result['go_pid']
    if isinstance(go_pid,int) and go_pid > 0:
        targets.append((go_pid,'game-server'))
    targets += [(int(value), 'webkit-network-'+value) for value in webkit.get('stdout','').split()[:3] if value.isdigit()]
    result['process_tcp_connections'] = {}
    for target,label in targets:
        if target > 0:
            sockets=command(['/usr/sbin/lsof','-nP','-a','-p',str(target),'-iTCP'])
            rows=sockets.get('stdout','').splitlines()
            sockets['established_loopback_rows']=[row for row in rows if '(ESTABLISHED)' in row and ('127.0.0.1:' in row or '[::1]:' in row)]
            sockets['established_loopback_count']=len(sockets['established_loopback_rows'])
            result['process_tcp_connections'][label]=sockets
    result['samples'] = {}
    for target, label in targets:
        if target > 0:
            output = destination/(label+'.sample.txt')
            result['samples'][label] = command(['/usr/bin/sample',str(target),'2','10','-file',str(output)], timeout=8)
    (destination/'snapshot.json').write_text(json.dumps(result,indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--relocation',type=Path,required=True)
    args = parser.parse_args()
    assert sys.platform == 'darwin'
    args.evidence.mkdir(parents=True,exist_ok=True)
    original = args.repo/'macos/ci/run_app_smoke.py'
    script_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    subprocess.run(['git','-C',str(args.repo),'diff','--exit-code','24c38811ff36878e03b223e46bdeb3bd5e6f5fd1','--','macos/ci/run_app_smoke.py'],check=True)
    child = subprocess.Popen([sys.executable,str(original),'--app',str(args.app),
        '--evidence',str(args.evidence),'--relocation',str(args.relocation)],env=os.environ.copy())
    first_seen, captured, skipped = None, set(), []
    workers = concurrent.futures.ThreadPoolExecutor(max_workers=3)
    pending = []
    try:
        while child.poll() is None:
            path = args.evidence/'native-app-data/native-smoke.json'
            try:
                state=json.loads(path.read_text())
            except (OSError,ValueError):
                time.sleep(.25);continue
            if state.get('stage') == 'native-official-pcm-game-started':
                if first_seen is None:first_seen=time.monotonic()
                for seconds in (10,30,90):
                    if seconds not in captured and time.monotonic()-first_seen >= seconds:
                        captured.add(seconds)
                        imported = args.evidence/'native-app-data/sukusta/extracted/game-models'
                        if any(imported.glob('gl-400022007-*')):
                            skipped.append({'at_seconds':seconds,'reason':'Official body import has begun; avoid profiling during PCM/frame sampling.'})
                        else:
                            pending.append(workers.submit(snapshot,args.app,args.evidence,state,'pending-'+str(seconds)+'s'))
            time.sleep(.25)
        for future in pending:future.result()
    finally:
        workers.shutdown(wait=True)
    result={'status':'PASS_UNCHANGED_SMOKE_WITH_EXTERNAL_DIAGNOSTICS' if child.returncode==0 else 'FAILED_UNCHANGED_SMOKE_WITH_EXTERNAL_DIAGNOSTICS',
            'smoke_exit_code':child.returncode,'original_smoke_sha256':script_hash,
            'captured_at_seconds':sorted(captured),'same_original_catalog_timeout_seconds':120,
            'skipped_samples':skipped,
            'signed_resources_modified':False,'ui_secrets_extracted':False,
            'limitations':['Unauthenticated HTTP only checks accept/auth liveness, not the live catalog body.',
                           'The direct private catalog probe uses the same DB files in a separate process.',
                           'Standard process sampling is diagnostic observation, not a device FPS measurement.']}
    (args.evidence/'host-diagnostic-summary.json').write_text(json.dumps(result,indent=2)+'\n')
    raise SystemExit(child.returncode)


if __name__=='__main__':main()

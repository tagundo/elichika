#!/usr/bin/env python3
"""Read-only, bounded startup/termination evidence for one synthetic game launch.

Never launches, attaches, injects, signs, edits a bundle, changes permissions or
system settings. Raw crash/log contents are not copied to evidence. Record only
reviewed crash fields and recognizable engine/loader startup diagnostics.
"""
import argparse
import datetime
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import subprocess
import time

BUNDLES = {'com.klab.lovelive.allstars.global', 'com.klab.lovelive.allstars'}
STARTUP = re.compile(r'^(?:Initialize engine version:|\[Subsystems\]|GfxDevice:|Creating GfxDevice:|Metal\b|Renderer:|Vendor:|VRAM:|No supported renderers|Failed to (?:initialize|load)|Could not (?:initialize|load)|Unable to (?:initialize|load)|\[UnityMemory\]|\[Physics\]|\[XR\]|dyld(?:\[\d+\])?:|Library not loaded:|Symbol not found:|Referenced from:|Expected in:|Reason: tried:|Termination Reason:|Exception Type:)', re.I)
LOADER_REASON = re.compile(r'^(?:Library not loaded:|Symbol not found:|Referenced from:|Expected in:|Reason: tried:|\(terminated at launch; ignore backtrace\))', re.I)

def message_text(value):
    # stderr's ordinary NSLog prefix is metadata, not part of the diagnostic.
    return re.sub(r'^\d{4}-\d\d-\d\d\s+\d\d:\d\d:\d\d[.\d+-]*\s+[^\s]+\[\d+:\d+\]\s*', '', str(value).strip())

def objc_assertion(value):
    line = message_text(value)
    # Extract only a known UIKit launch assertion, not arbitrary ASI strings or
    # exception text from gameplay/account operations.
    if 'NSInternalInconsistencyException' in line:
        reason = re.search(r"reason:\s*['\"](.{1,3000})['\"]", line, re.I)
        if reason:
            return {'name':'NSInternalInconsistencyException', 'reason':scrub(reason[1], 1000)}
    method = re.search(r'Assertion failure in (-\[UINSApplicationDelegate [^\]]{1,300}\])(?:,\s*([^\s,]+:\d+))?', line)
    if method:
        result = {'framework':'UIKitMacHelper', 'assertion_method':scrub(method[1])}
        if method[2]:
            result['source_location'] = scrub(method[2])
        return result
    return None

def strings(value, depth=0):
    if depth > 6:
        return
    if isinstance(value,str):
        yield from value.splitlines()
    elif isinstance(value,dict):
        for child in list(value.values())[:64]:
            yield from strings(child,depth+1)
    elif isinstance(value,list):
        for child in value[:64]:
            yield from strings(child,depth+1)

def scrub(value, maximum=500):
    text = str(value)
    text = re.sub(r'https?://[^\s\]<>\"\']+', '<url redacted>', text, flags=re.I)
    text = re.sub(r'<RSAKeyValue>.*?</RSAKeyValue>', '<public key redacted>', text, flags=re.I)
    text = re.sub(r'(?i)\b(?:authorization|cookie|password|session[_ -]?key|token)\s*[:=]\s*\S+', '<credential field redacted>', text)
    text = re.sub(r'[A-Za-z0-9+/=_-]{64,}', '<long value redacted>', text)
    text = re.sub(r'/Users/[^/\s]+/', '~/Users/', text)
    return ''.join(c for c in text if c == '\t' or ord(c) >= 32)[:maximum]

def bounded_text(path, since, limit=4*1024*1024):
    if path.is_symlink() or not path.is_file():
        return None
    stat = path.stat()
    if stat.st_mtime < since-1 or stat.st_size > limit:
        return None
    data = path.read_bytes()
    if len(data) > limit:
        return None
    return data, {'file':path.name, 'bytes':len(data), 'mtime':stat.st_mtime,
                  'sha256':hashlib.sha256(data).hexdigest()}

def crash_record(path, since, pid, executable, bundle):
    item = bounded_text(path, since)
    if item is None:
        return None
    raw, record = item
    text = raw.decode('utf-8', errors='replace').lstrip()
    first, end = json.JSONDecoder().raw_decode(text)
    data = json.loads(text[end:].strip()) if text[end:].strip() else first
    actual_pid = data.get('pid')
    identity = data.get('bundleInfo', {}).get('CFBundleIdentifier')
    if pid and actual_pid != pid:
        return None
    if data.get('procName') != executable or identity not in (None, bundle):
        return None
    if not pid and identity != bundle:
        return None
    record.update(pid=actual_pid, executable=executable, bundle_identifier=identity)
    record['exception'] = {key:scrub(data.get('exception',{}).get(key))
                           for key in ('type','signal','codes') if key in data.get('exception',{})}
    term = data.get('termination', {})
    record['termination'] = {key:scrub(term[key]) for key in ('namespace','code','indicator','byProc','byPid') if key in term}
    record['loader_reasons'] = [scrub(line) for key in ('details','reasons') for line in term.get(key, [])
                                if isinstance(line,str) and LOADER_REASON.match(line)][:24]
    record['faulting_thread'] = data.get('faultingThread')
    record['objc_launch_assertions'] = []
    for key in ('asi','applicationSpecificInformation'):
        for line in strings(data.get(key,{})):
            assertion = objc_assertion(line)
            if assertion and assertion not in record['objc_launch_assertions']:
                record['objc_launch_assertions'].append(assertion)
                if len(record['objc_launch_assertions']) == 16:
                    break
    record['triggered_threads'] = []
    for thread in data.get('threads', []):
        if not thread.get('triggered'):
            continue
        frames = [{key:scrub(frame[key]) if isinstance(frame[key],str) else frame[key]
                   for key in ('imageIndex','imageOffset','symbol','symbolLocation') if key in frame}
                  for frame in thread.get('frames', [])[:40]]
        record['triggered_threads'].append({'frames':frames})
    record['images'] = []
    for image in data.get('usedImages', [])[:200]:
        # Keep module identity/offsets; arbitrary paths and app-specific crash
        # strings can contain credentials and are deliberately not exported.
        entry = {key:scrub(image[key]) if isinstance(image[key],str) else image[key]
                 for key in ('name','arch','uuid','base','size') if key in image}
        record['images'].append(entry)
    return record

def startup_lines(path, since):
    item = bounded_text(path, since)
    if item is None:
        return None
    data, record = item
    lines = [message_text(line) for line in data.decode('utf-8',errors='replace').splitlines()]
    record['allowlisted_startup_lines'] = [scrub(line) for line in lines if STARTUP.match(line)][:160]
    record['objc_launch_assertions'] = [found for line in lines if (found := objc_assertion(line)) is not None][:24]
    record['raw_contents_exported'] = False
    return record

def unified_startup(pid, since, executable):
    if not pid:
        return {'status':'NO_EXACT_OBSERVED_PID'}
    elapsed = max(1, min(900, math.ceil(time.time()-since)+2))
    argv = ['/usr/bin/log','show','--style','json','--last',str(elapsed)+'s',
            '--predicate','processID == '+str(pid)]
    try:
        result = subprocess.run(argv,capture_output=True,timeout=25)
        if result.returncode:
            return {'status':'OS_LOG_UNAVAILABLE','exit_code':result.returncode}
        if len(result.stdout) > 8*1024*1024:
            return {'status':'OS_LOG_OUTPUT_EXCEEDS_BOUND'}
        events = json.loads(result.stdout)
        records = []
        for event in events:
            if event.get('processID') != pid:
                continue
            timestamp = event.get('timestamp','')
            try:
                observed = datetime.datetime.fromisoformat(timestamp).timestamp()
            except (ValueError,TypeError):
                continue
            if observed < since-1:
                continue
            line = message_text(event.get('eventMessage',''))
            if STARTUP.match(line):
                records.append({'timestamp':timestamp,'message':scrub(line)})
            else:
                assertion = objc_assertion(line)
                if assertion:
                    records.append({'timestamp':timestamp,'objc_launch_assertion':assertion})
        return {'status':'READ_EXACT_PID_ALLOWLISTED_STARTUP_ONLY','records':records[:160],
                'unfiltered_event_count':len(events),'raw_contents_exported':False}
    except Exception as error:
        return {'status':'OS_LOG_READ_FAILED','error_type':type(error).__name__}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle-id',choices=sorted(BUNDLES),required=True)
    p.add_argument('--executable',choices=('global','allstars'),required=True)
    p.add_argument('--pid',type=int,default=0,help='Exact PID observed after this launch; zero only if no process appeared')
    p.add_argument('--since',type=float,required=True,help='time.time() immediately before normal open/GUI launch')
    p.add_argument('--proof-dir',type=Path,required=True)
    p.add_argument('--private-log-root',type=Path)
    p.add_argument('--launch-stdout',type=Path)
    p.add_argument('--launch-stderr',type=Path)
    a = p.parse_args()
    assert platform.system() == 'Darwin' and a.pid >= 0 and math.isfinite(a.since)
    assert 0 <= time.time()-a.since <= 900, 'Only fresh launches within fifteen minutes may be inspected'
    assert not a.proof_dir.exists(), 'Fresh proof directory required'
    a.proof_dir.mkdir(parents=True)
    report = {'status':'READ_ONLY_STARTUP_DIAGNOSTIC_NOT_GAMEPLAY_PASS','pid':a.pid,
        'bundle_identifier':a.bundle_id,'executable':a.executable,'launch_wall_time':a.since,
        'crashes':[],'log_files':[],'errors':[], 'raw_log_contents_exported':False,
        'qualification':'A mapped module or observed PID is not proof that its initializer, UI, login, rendering or gameplay worked.'}
    crashes = Path.home()/'Library/Logs/DiagnosticReports'
    for path in sorted(crashes.glob(a.executable+'*.ips'),key=lambda x:x.stat().st_mtime,reverse=True)[:32]:
        try:
            record = crash_record(path,a.since,a.pid,a.executable,a.bundle_id)
            if record:
                report['crashes'].append(record)
        except Exception as error:
            report['errors'].append({'file':path.name,'error_type':type(error).__name__})
    roots = [Path.home()/'Library/Containers'/a.bundle_id/'Data/Library/Logs', Path.home()/'Library/Logs/Unity']
    logs = set()
    for root in roots:
        if root.is_dir():
            for path in root.rglob('*'):
                if len(path.relative_to(root).parts) <= 4 and path.name in ('Player.log','Player-prev.log','unity.log','Unity.log'):
                    logs.add(path)
    for path in (a.launch_stdout,a.launch_stderr):
        if path is not None:
            assert a.private_log_root is not None and path.resolve().is_relative_to(a.private_log_root.resolve()), 'Launch logs must be in the private fixture root'
            logs.add(path)
    for path in sorted(logs)[:16]:
        try:
            record = startup_lines(path,a.since)
            if record:
                report['log_files'].append(record)
        except Exception as error:
            report['errors'].append({'file':path.name,'error_type':type(error).__name__})
    report['unified_startup'] = unified_startup(a.pid,a.since,a.executable)
    report['fresh_matching_crash_found'] = bool(report['crashes'])
    report['utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    target = a.proof_dir/'startup-diagnostic.json'
    target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'crashes':len(report['crashes']),
        'log_files':len(report['log_files']),'proof':str(target)}))

if __name__ == '__main__':
    main()

"""Build unity_ui.mvdump.bundle.js from the pinned r8 toolkit files, without npm.

The r8 bundle is laid out by the toolkit's bundle_unity_ui.py as
    bridge(frida-il2cpp-bridge 0.9.1 dist/index.js) + "\\n;\\n" + cached_dispatcher.js + "\\n;\\n" + unity_ui.js + "\\n"
This builder slices the bridge bytes back out of the shipped bundle, verifies every piece
against unity_ui.manifest.json, inserts ONE line into the observer at the unique anchor
'  rpc.exports = {' (it exposes the observer's existing onMain/helpers as
globalThis.QA_MVDUMP_HOST; nothing else in the observer changes) and appends
mv_runtime_dump.js. The toolkit's own unity_ui.bundle.js / manifest are never written and
bundle_unity_ui.py is never run. Every check fails loudly (SystemExit with a message).
The output is byte-for-byte reproducible: building twice gives the same sha256.

    python3 build_mvdump_agent.py --qa toolkit/qa --extension qa-mvdump/mv_runtime_dump.js \\
        --out toolkit/qa/unity_ui.mvdump.bundle.js --evidence toolkit/evidence \\
        [--expect qa-mvdump/unity_ui.mvdump.bundle.manifest.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

BRIDGE_VERSION, FRIDA_VERSION = '0.9.1', '16.6.6'
SEPARATOR = b'\n;\n'
RPC_ANCHOR = '  rpc.exports = {'
VERSION_ANCHOR = 'var BRIDGE_VERSION = "0.9.1", AGENT_VERSION = 8;'
# ES5 function syntax, matching unity_ui.js. Everything named here already exists in the
# observer's closure; the extension only reads through these (see mv_runtime_dump.js).
EXPOSE = ('  globalThis.QA_MVDUMP_HOST = Object.freeze({onMain: onMain, '
          'dispatcherStatus: function () { return mainDispatcher ? mainDispatcher.status() : null; }, '
          'cachedRequested: function () { return cachedMainRequested; }, '
          'findClass: findClass, allOfType: allOfType, exists: exists, active: active, maybe: maybe, call: call, '
          'overloaded: overloaded, field: field, numericField: numericField, transform: transform, gameObject: gameObject, '
          'hierarchy: hierarchy, instanceId: instanceId, fullType: fullType, metadata: metadata, '
          'nativeFeatureState: nativeFeatureState, mvReadField: mvReadField, mvBacking: mvBacking, mvNumber: mvNumber});\n')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fail(message):
    raise SystemExit('build_mvdump_agent: ' + message)


def build(qa, extension_path):
    """(bundle_bytes, manifest_dict) or SystemExit."""
    manifest_path = qa / 'unity_ui.manifest.json'
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError) as error:
        fail(f'cannot read {manifest_path}: {error}')
    if manifest.get('bridge') != BRIDGE_VERSION or manifest.get('frida_server_and_client') != FRIDA_VERSION:
        fail(f'toolkit manifest pins bridge {manifest.get("bridge")!r} / frida {manifest.get("frida_server_and_client")!r}, '
             f'expected {BRIDGE_VERSION} / {FRIDA_VERSION}')
    try:
        bundle = (qa / 'unity_ui.bundle.js').read_bytes()
        dispatcher = (qa / 'cached_dispatcher.js').read_bytes()
        observer = (qa / 'unity_ui.js').read_bytes()
        extension = Path(extension_path).read_bytes()
    except OSError as error:
        fail(f'missing input: {error}')
    for label, data, key in (('unity_ui.bundle.js', bundle, 'sha256'), ('cached_dispatcher.js', dispatcher, 'dispatcher_sha256'),
                             ('unity_ui.js', observer, 'observer_sha256')):
        if sha(data) != manifest.get(key):
            fail(f'{label} sha256 {sha(data)} differs from the toolkit manifest {key} {manifest.get(key)} (toolkit moved)')
    tail = SEPARATOR + dispatcher + SEPARATOR + observer + b'\n'
    if not bundle.endswith(tail):
        fail('unity_ui.bundle.js is not bridge + dispatcher + observer (bundle_unity_ui.py layout)')
    bridge = bundle[:-len(tail)]
    if sha(bridge) != manifest.get('bridge_sha256'):
        fail(f'sliced bridge sha256 {sha(bridge)} differs from the pinned {BRIDGE_VERSION} dist {manifest.get("bridge_sha256")}')
    try:
        source = observer.decode('utf-8')
    except UnicodeDecodeError as error:
        fail(f'unity_ui.js is not UTF-8: {error}')
    for anchor in (RPC_ANCHOR, VERSION_ANCHOR):
        count = source.count(anchor)
        if count != 1:
            fail(f'anchor {anchor!r} occurs {count} times in unity_ui.js (expected exactly 1)')
    if 'QA_MVDUMP_HOST' in source:
        fail('unity_ui.js already mentions QA_MVDUMP_HOST')
    patched = source.replace(RPC_ANCHOR, EXPOSE + RPC_ANCHOR, 1).encode('utf-8')
    if patched.count(EXPOSE.encode()) != 1 or len(patched) != len(observer) + len(EXPOSE.encode()):
        fail('the expose line was not inserted exactly once')
    if b'globalThis.QA_MVDUMP_HOST' not in extension or b'rpc.exports.mvruntime' not in extension:
        fail(f'{extension_path} is not the mv_runtime_dump.js extension')
    out = bridge + SEPARATOR + dispatcher + SEPARATOR + patched + SEPARATOR + extension.rstrip(b'\n') + b'\n'
    report = {'schema': 'unity_ui.mvdump.bundle/1', 'bridge': BRIDGE_VERSION, 'frida_server_and_client': FRIDA_VERSION,
              'agent_version': 8, 'base_bundle_sha256': manifest['sha256'], 'bridge_sha256': sha(bridge),
              'dispatcher_sha256': sha(dispatcher), 'observer_sha256': sha(observer), 'patched_observer_sha256': sha(patched),
              'extension_sha256': sha(extension), 'expose_line_sha256': sha(EXPOSE.encode()),
              'anchor': RPC_ANCHOR, 'bundle': 'unity_ui.mvdump.bundle.js', 'bytes': len(out), 'sha256': sha(out),
              'layout': 'bridge + \\n;\\n + dispatcher + \\n;\\n + patched observer + \\n;\\n + extension + \\n',
              'runtime_validation': 'Pending a real Unity process: hashes, anchors and syntax are not runtime proof'}
    return out, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--qa', type=Path, required=True, help='toolkit qa/ folder (unity_ui.js, cached_dispatcher.js, bundle, manifest)')
    parser.add_argument('--extension', type=Path, required=True, help='qa-mvdump/mv_runtime_dump.js')
    parser.add_argument('--out', type=Path, required=True, help='output bundle path (never the toolkit bundle)')
    parser.add_argument('--evidence', type=Path, help='folder that receives a copy of the bundle manifest')
    parser.add_argument('--expect', type=Path, help='checked-in manifest whose sha256 the build must reproduce')
    args = parser.parse_args(argv)
    if args.out.resolve() == (args.qa / 'unity_ui.bundle.js').resolve():
        fail('refusing to overwrite the toolkit bundle')
    out, report = build(args.qa, args.extension)
    if args.expect:
        try:
            expected = json.loads(args.expect.read_text())
        except (OSError, ValueError) as error:
            fail(f'cannot read --expect {args.expect}: {error}')
        for key in ('sha256', 'extension_sha256', 'patched_observer_sha256', 'bridge_sha256'):
            if expected.get(key) != report[key]:
                fail(f'--expect {key} {expected.get(key)} != built {report[key]} (rebuild and re-check-in the bundle)')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(out)
    manifest_out = args.out.with_name('unity_ui.mvdump.bundle.manifest.json')
    manifest_out.write_text(json.dumps(report, indent=2) + '\n')
    if args.evidence:
        args.evidence.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(manifest_out, args.evidence / manifest_out.name)
    print(json.dumps({k: report[k] for k in ('bundle', 'bytes', 'sha256', 'extension_sha256', 'patched_observer_sha256')}))
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""Exact-anchor hooks on the CI-time COPIES in toolkit/qa (never on qa-mv/** or the r8 tree).

toolkit/qa/mv_export_focus.py is an unchanged copy of self/qa-mv/mv_export_focus.py. One
block is inserted immediately before the anchor

    log('STEP', {'mv': 'playing', 'elapsed': round(time.monotonic() - started)})

(run_mv_focus, right after the navigation loop has seen LiveMv/LiveMvCore with the
observer still bound). With MV_RUNTIME_DUMP=1 it returns mvdump_sampler.run_dump(...)
before features(), before release_observers() and before the MP4 export, so no export is
ever made in dump mode; without it the module runs exactly as before.

toolkit/qa/native_ocr_control.py gets the same four edits mv-game-export.yml makes with sed,
plus RUNTIME_DUMPED in the exit-0 status tuple.

Every edit asserts that its anchor occurs exactly once before and that the new text occurs
exactly once after; ordering asserts pin the hook between the `if not playing` return and the
features()/release_observers() calls. Any other count is a SystemExit (the build fails
before Android boots). Python string replacement only, never sed. The receipt (sha256
before/after, anchors, counts) goes to <evidence>/mvdump-hooks.json.

    python3 apply_hooks.py --qa toolkit/qa --evidence toolkit/evidence
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

FOCUS_ANCHOR = "    log('STEP', {'mv': 'playing', 'elapsed': round(time.monotonic() - started)})\n"
FOCUS_HOOK = (
    "    if os.environ.get('MV_RUNTIME_DUMP') == '1':  # qa-mvdump hook, applied to the CI-time copy only\n"
    "        import mvdump_sampler\n"
    "        return mvdump_sampler.run_dump(dict(\n"
    "            agent=lambda: agent, rpc=rpc, observer_status=observer_status, native_main_proof=native_main_proof,\n"
    "            attach_observer=attach_observer, release_observers=release_observers, observers=observers,\n"
    "            lifetime=lambda where: lifetime_check(identity, where), identity=identity, read_fov_state=read_fov_state,\n"
    "            mvclock=mvclock, mv_clock=mv_clock, result=result, save=save, screen=screen, write_json=write_json,\n"
    "            log=log, sh=sh, evidence=evidence, device=device, package=package, started=started, args=args))\n"
)
# (marker, must come 'before' or 'after' the anchor)
FOCUS_ORDER = (
    ('    if not playing:\n', 'before'),
    ('    # ----------------------------------------------------------- export\n', 'before'),
    ('features = rpc(lambda: agent.exports_sync.features(), timeout=15)', 'after'),
    ("result['observer_release'] = release_observers()", 'after'),
)
# Names the hook passes; each must be bound in run_mv_focus (or at module level) at the anchor.
FOCUS_NAMES = ('    agent = session = remote = build = None\n', '    rpc = semantics.bounded_rpc\n', '    observers = []\n',
               "    identity = lifetime_check(None, 'after-home')\n", '    def observer_status():\n',
               '    def native_main_proof(label):\n', '    def attach_observer(label, expected, build_now):\n',
               '    def release_observers():\n', '    def lifetime_check(expected, where):\n', '    def read_fov_state():\n',
               '    def mvclock(step, **extra):\n', "    mv_clock = {'play_tap': None, 'livemv': None}\n",
               '    def save():\n', '    def screen(name, force=False):\n', '    def write_json(name, value):\n',
               '    def sh(command, timeout=40):\n', '    started = time.monotonic()\n', 'def log(kind, value, limit=6000):\n',
               "    evidence, package = args.evidence, context['package']\n",
               "    args, device, report = context['args'], context['device'], context['report']\n",
               "    result = {'status': 'RUNNING',")

OCR_EDITS = (
    ('from native_mv_focus import run_mv_focus', 'from mv_export_focus import run_mv_focus'),
    ('if pair_failures[kind]>=3:', 'if pair_failures[kind]>=12:'),
    ("plan=semantics.native_profile_plan(nodes,state,'portrait',True)", 'plan=mv_profile_plan(nodes,state)'),
    ('\nimport feature_client_smoke as semantics\n', '\nimport feature_client_smoke as semantics\nfrom mv_export_focus import mv_profile_plan\n'),
    ("    return 0 if report['status'] in ('PARTIAL_NATIVE_STARTUP_PROGRESS',",
     "    return 0 if report['status'] in ('RUNTIME_DUMPED','PARTIAL_NATIVE_STARTUP_PROGRESS',"),
    # Live 3D quality pre-seed (mvdump_prefs.py): after the verified install, before the first launch.
    ("        assert device.shell('sha256sum',installed).split()[0]==client['sha256']\n",
     "        assert device.shell('sha256sum',installed).split()[0]==client['sha256']\n"
     "        if os.environ.get('MV_PRESEED_QUALITY'):\n"
     "            import mvdump_prefs;mvdump_prefs.preseed(device,package,int(os.environ['MV_PRESEED_QUALITY']),args.evidence)\n"),
)


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def fail(message):
    raise SystemExit('apply_hooks: ' + message)


def replace_once(text, anchor, new, label):
    before = text.count(anchor)
    if before != 1:
        fail(f'{label}: anchor {anchor!r} occurs {before} times (expected exactly 1)')
    if text.count(new) != 0 and new != anchor:
        fail(f'{label}: replacement {new!r} is already present')
    out = text.replace(anchor, new, 1)
    after = out.count(new)
    if after != 1:
        fail(f'{label}: replacement occurs {after} times after the edit (expected exactly 1)')
    return out, {'anchor': anchor, 'countBefore': before, 'replacementCountAfter': after}


def hook_focus(text):
    """Patched mv_export_focus.py text and the receipt; SystemExit on any anchor/order mismatch."""
    count = text.count(FOCUS_ANCHOR)
    if count != 1:
        fail(f'mv_export_focus.py: anchor {FOCUS_ANCHOR.strip()!r} occurs {count} times (expected exactly 1)')
    if 'mvdump_sampler' in text:
        fail('mv_export_focus.py already mentions mvdump_sampler (hook applied twice?)')
    at = text.index(FOCUS_ANCHOR)
    order = []
    for marker, where in FOCUS_ORDER:
        n = text.count(marker)
        if n != 1:
            fail(f'mv_export_focus.py: ordering marker {marker.strip()!r} occurs {n} times (expected exactly 1)')
        position = text.index(marker)
        if (position < at) != (where == 'before'):
            fail(f'mv_export_focus.py: {marker.strip()!r} must come {where} the hook anchor')
        order.append({'marker': marker.strip(), 'where': where})
    run_start = text.find('\ndef run_mv_focus(context):\n')
    run_end = text.find('\ndef ', run_start + 1)
    if run_start < 0 or not (run_start < at < (run_end if run_end > 0 else len(text))):
        fail('mv_export_focus.py: the anchor is not inside run_mv_focus')
    missing = [name.strip() for name in FOCUS_NAMES if name not in text[:at] and not (name.startswith('def ') and name in text)]
    if missing:
        fail(f'mv_export_focus.py: names the hook passes are not bound before the anchor: {missing}')
    out = text.replace(FOCUS_ANCHOR, FOCUS_HOOK + FOCUS_ANCHOR, 1)
    if out.count(FOCUS_HOOK) != 1 or out.count(FOCUS_ANCHOR) != 1:
        fail('mv_export_focus.py: hook not inserted exactly once')
    if out.replace(FOCUS_HOOK, '', 1) != text:
        fail('mv_export_focus.py: the diff is not exactly the inserted hook')
    try:
        compile(out, 'mv_export_focus.py', 'exec')
    except SyntaxError as error:
        fail(f'mv_export_focus.py does not compile after the hook: {error}')
    line = text[:at].count('\n') + 1
    return out, {'anchor': FOCUS_ANCHOR.rstrip('\n'), 'count': 1, 'line': line, 'order': order,
                 'insertedLines': FOCUS_HOOK.count('\n'), 'hookSha256': sha(FOCUS_HOOK)}


def hook_ocr(text):
    edits = []
    for anchor, new in OCR_EDITS:
        text, receipt = replace_once(text, anchor, new, 'native_ocr_control.py')
        edits.append(receipt)
    if text.count('mv_profile_plan') != 2:
        fail(f'native_ocr_control.py: mv_profile_plan occurs {text.count("mv_profile_plan")} times (expected 2)')
    try:
        compile(text, 'native_ocr_control.py', 'exec')
    except SyntaxError as error:
        fail(f'native_ocr_control.py does not compile after the edits: {error}')
    return text, {'edits': len(edits), 'allExactlyOnce': True, 'details': edits}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Apply the qa-mvdump hooks to the CI-time toolkit copies.')
    parser.add_argument('--qa', type=Path, required=True, help='toolkit/qa (holds the COPIED mv_export_focus.py)')
    parser.add_argument('--evidence', type=Path, help='folder for mvdump-hooks.json')
    parser.add_argument('--dry-run', action='store_true', help='check and report without writing')
    args = parser.parse_args(argv)
    receipt = {'schema': 'mvdump-hooks/1'}
    for name, hook in (('mv_export_focus.py', hook_focus), ('native_ocr_control.py', hook_ocr)):
        path = args.qa / name
        try:
            text = path.read_text('utf-8')
        except OSError as error:
            fail(f'cannot read {path}: {error}')
        patched, info = hook(text)
        info.update(beforeSha256=sha(text), afterSha256=sha(patched), path=str(path))
        receipt[name] = info
        if not args.dry_run:
            path.write_text(patched, 'utf-8')
        print(json.dumps({'hooked': name, 'before': info['beforeSha256'][:16], 'after': info['afterSha256'][:16],
                          'dryRun': args.dry_run}))
    if args.evidence and not args.dry_run:
        args.evidence.mkdir(parents=True, exist_ok=True)
        (args.evidence / 'mvdump-hooks.json').write_text(json.dumps(receipt, indent=1) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())

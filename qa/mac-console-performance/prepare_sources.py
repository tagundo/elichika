#!/usr/bin/env python3
"""Verify frozen inputs and make explicit QA entrypoint-only projections."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', required=True, type=Path)
    parser.add_argument('--qa', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.qa / 'source-manifest.json').read_text())
    actual_ref = subprocess.check_output(['git', '-C', str(args.checkout), 'rev-parse', 'HEAD'], text=True).strip()
    assert actual_ref == manifest['baseline_source_commit'], 'Baseline checkout changed'
    receipt = {'schema_version': 1, 'baseline_source_commit': actual_ref, 'candidate_inputs': [],
               'baseline_inputs': [], 'qa_projections': [],
               'scope': 'Full production RootView/AppModel and real bridge LogBuffer in an actual NSWindow. Only the application entrypoint annotation is removed in QA projection; controlled fixture replaces external server/CDN state.'}
    for row in manifest['files']:
        candidate = args.qa / 'candidate' / row['path']
        assert candidate.is_file() and sha(candidate) == row['sha256'] and candidate.stat().st_size == row['bytes'], row['path']
        receipt['candidate_inputs'].append(row)
    for variant in ['baseline', 'patched']:
        root = args.output / variant
        mac = root / 'macos'
        (mac / 'App').mkdir(parents=True)
        (mac / 'Tests').mkdir()
        for source in sorted((args.checkout / 'macos/App').glob('*.swift')):
            shutil.copyfile(source, mac / 'App' / source.name)
            if variant == 'baseline':
                receipt['baseline_inputs'].append({'path': 'macos/App/' + source.name, 'sha256': sha(source)})
        for source in (args.checkout / 'macos/Tests').glob('*.swift'):
            shutil.copyfile(source, mac / 'Tests' / source.name)
        shutil.copyfile(args.checkout / 'macos/Package.swift', mac / 'Package.swift')
        (mac / 'runtime').mkdir()
        shutil.copyfile(args.checkout / 'macos/runtime/elichika_macos.py', mac / 'runtime/elichika_macos.py')
        if variant == 'patched':
            for row in manifest['files']:
                if row['path'].startswith('macos/'):
                    target = root / row['path']
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(args.qa / 'candidate' / row['path'], target)
        if variant == 'patched':
            actual_package = [{'path': 'macos/' + str(path.relative_to(mac)), 'sha256': sha(path)}
                              for path in sorted(mac.rglob('*.swift'))]
            assert actual_package == manifest['macos_package_inputs'], 'Complete frozen C5 SwiftPM inputs changed'
            receipt['candidate_macos_package_inputs'] = actual_package
        # Keep SwiftPM unit tests on the intact production application. A
        # separate compile projection is used only for the QA AppKit host.
        projection = root / 'probe-sources'
        shutil.copytree(mac / 'App', projection)
        app = projection / 'ElichikaApp.swift'
        original = app.read_text()
        exact = '@main\nstruct ElichikaMacApp: App {'
        assert original.count(exact) == 1
        app.write_text(original.replace(exact, 'struct ElichikaMacApp: App {', 1))
        receipt['qa_projections'].append({'variant': variant, 'path': 'macos/App/ElichikaApp.swift',
             'original_sha256': hashlib.sha256(original.encode()).hexdigest(), 'projected_sha256': sha(app),
             'only_edit': 'Remove exactly the @main annotation immediately before ElichikaMacApp; all production UI and model types preserved'})
    args.evidence.mkdir(parents=True, exist_ok=True)
    (args.evidence / 'source-build-inputs.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()

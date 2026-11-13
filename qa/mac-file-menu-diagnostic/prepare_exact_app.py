"""Extract and inventory the original, unmodified, unvalidated C7 app for UI diagnostics."""
import argparse, hashlib, json, os, pathlib, plistlib, stat, subprocess, zipfile

OUTER_SHA = 'f46bb810adfa32040b75c82532bc52a79282434d7cfb42300b65e1cfbaa09adc'
SOURCE = 'b166b92f6a9e9c575c5cfd292f52b5e60603aa97'

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def inventory(root):
    result = {}
    for path in [root, *sorted(root.rglob('*'))]:
        name = '.' if path == root else path.relative_to(root).as_posix()
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            assert path.resolve().is_relative_to(root.resolve()), f'Escaping bundle link: {name}'
            result[name] = {'link': os.readlink(path), 'mode': mode}
        elif path.is_dir(): result[name] = {'directory': True, 'mode': mode}
        elif path.is_file(): result[name] = {'bytes': path.stat().st_size, 'sha256': sha(path), 'mode': mode}
        else: raise ValueError(f'Unexpected node: {name}')
    return result

def safe_zip(path, limit):
    with zipfile.ZipFile(path) as archive:
        rows = archive.infolist()
        assert 0 < len(rows) < 50000 and sum(row.file_size for row in rows) < limit
        seen = set()
        for row in rows:
            name = pathlib.PurePosixPath(row.filename)
            assert row.filename and '\\' not in row.filename and not name.is_absolute() and '..' not in name.parts
            assert row.filename not in seen and row.file_size < 512 * 1024 * 1024
            seen.add(row.filename)
            if stat.S_ISLNK(row.external_attr >> 16):
                target = archive.read(row).decode()
                joined = pathlib.PurePosixPath(os.path.normpath(str(name.parent / target)))
                assert not pathlib.PurePosixPath(target).is_absolute() and '..' not in joined.parts

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['archive', 'qa', 'scratch', 'evidence']: parser.add_argument('--' + name, type=pathlib.Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.qa / 'proposal-manifest.json').read_text())
    for name, binding in manifest['qa_files'].items():
        path = args.qa / name
        assert path.is_file() and path.stat().st_size == binding['bytes'] and sha(path) == binding['sha256']
    assert args.archive.stat().st_size == 305445813 and sha(args.archive) == OUTER_SHA
    assert not args.scratch.exists() and not args.evidence.exists()
    args.scratch.mkdir(parents=True); args.evidence.mkdir(parents=True)
    safe_zip(args.archive, 512 * 1024 * 1024)
    outer = args.scratch / 'outer'; outer.mkdir()
    with zipfile.ZipFile(args.archive) as archive:
        assert not any(stat.S_ISLNK(row.external_attr >> 16) for row in archive.infolist())
        archive.extractall(outer)
    records = list(outer.rglob('candidate-manifest.json')); assert len(records) == 1
    record = json.loads(records[0].read_text())
    assert record['status'] == 'UNVALIDATED_CANDIDATE_NOT_FOR_DELIVERY' and record['source_commit'] == SOURCE
    assert str(record['workflow_run']) == '43465318241'
    assert record == manifest['inner_app_archive'], 'Exact candidate manifest differs'
    assert pathlib.PurePosixPath(record['name']).name == record['name']
    packed = records[0].parent / record['name']
    assert packed.is_file() and packed.stat().st_size == record['bytes'] and sha(packed) == record['sha256']
    safe_zip(packed, 3 * 1024 * 1024 * 1024)
    apps = args.scratch / 'original-app'; apps.mkdir()
    subprocess.run(['/usr/bin/ditto', '-x', '-k', str(packed), str(apps)], check=True)
    found = list(apps.glob('*.app')); assert len(found) == 1
    app = found[0]
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    assert info['CFBundleIdentifier'] == 'com.tagundo.elichika.macos'
    bundle_source = json.loads((app / 'Contents/Resources/bundle-provenance.json').read_text())
    assert bundle_source['source'] == manifest['frozen_bundle_source'] and bundle_source['version'] == '2026.11.13.1'
    before = inventory(app)
    for name, binding in manifest['frozen_packaged_product_files'].items():
        assert before[name]['sha256'] == binding['sha256'] and before[name]['bytes'] == binding['bytes']
    (args.evidence / 'original-app-inventory.json').write_text(json.dumps(before, indent=2) + '\n')
    provenance = {'status': 'EXACT_UNMODIFIED_C7_APP_FOR_FILE_MENU_DIAGNOSTIC_ONLY',
                  'source_commit': SOURCE, 'workflow_run': 43465318241, 'artifact_id': 14058823261,
                  'outer_zip_sha256': OUTER_SHA, 'outer_zip_bytes': args.archive.stat().st_size,
                  'candidate_manifest': record, 'app': str(app), 'bundle_identifier': info['CFBundleIdentifier'],
                  'app_modified_or_resigned': False, 'normal_app_no_smoke_mode': True,
                  'validated_release_artifact': False, 'original_C7_failure_waived': False}
    (args.evidence / 'exact-app-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(str(app))

if __name__ == '__main__': main()

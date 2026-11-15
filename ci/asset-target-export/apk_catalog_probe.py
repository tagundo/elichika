#!/usr/bin/env python3
"""Read a pinned released APK; export actual DownloadAllMissing whole files.

No network, app launch, app build, installed/user DB access, or payload writes.
Run on a hosted runner with disk/RAM for the APK and eight extracted stock DBs.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import zipfile

APK_BYTES = 290927759
APK_SHA256 = 'eaa99603f292bd10f53134c57c90d158a13046d2d6f02d8bbb63490296654413'
APP_COMMIT = '02f659d707997e03218be231e8a675fb0358a6c8'
SOURCE_CATALOG_SHA256 = '0aa7c4b4cbc70f71298c47fb378b5a2d19d25a71f39907a37d14d45d5bded0ee'
SQL_ADDITIONS_SHA256 = '7723961ba860cf0df477fa4b65c23d5d19e1a682a3d0b169ad3f0e3d69215ba9'
EXPECTED_WHOLE_FILES, EXPECTED_ADD_ON_FILES, EXPECTED_BYTES = 42830, 52, 33321064961
NAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z')
LANGUAGES = ('ja', 'en', 'ko', 'zh')
DB_PINS = {
    'gl/asset_a_en.db': '626da754427c115a379d5666d12a454993501c218d3a674f3ae5b2b765a08630',
    'gl/asset_a_ko.db': '8c791e74326574cb410750965f0fd901c31f18fc0c9815a1f23c0f47977952b4',
    'gl/asset_a_zh.db': '5d5cad1ef8fcb20f8ed373d63ca2736718195a77ddee6749a90a0a920e71f43f',
    'gl/asset_i_en.db': '1ee69f7db3b45b01bbd55141de4cc372913e3f10928353ac152bba1a0b7b9443',
    'gl/asset_i_ko.db': '0d14843eaf36e90b9a8642b6d7787f7c0e62ecd9da351a9eff9b595af5cf96c4',
    'gl/asset_i_zh.db': 'c4eebc6f23cf2ec696355411b2d46565d84583c2e989a8f9213d4ac897b7e89d',
    'jp/asset_a_ja.db': '783d74dfb368a7a8c6c69f7723daa41b738c3d4aba002bce8c417b324536909e',
    'jp/asset_i_ja.db': '40b3ede474947cd0cc47fbc25b8ba864c390d78710379733853c653ae2acfd3d',
}


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def add(objects, name, size, profile):
    if not isinstance(name, str) or not NAME.fullmatch(name) or type(size) is not int or size <= 0:
        raise ValueError(f'Invalid downloadable filename/size: {name!r}/{size!r}')
    obj = objects.setdefault(name, {'size': size, 'profiles': []})
    if obj['size'] != size:
        raise ValueError(f'Conflicting whole-file sizes for {name}')
    if profile not in obj['profiles']:
        obj['profiles'].append(profile)


def scan_database(path, profile):
    """Same unordered cursor columns and first-pack rule as assetdata.loadPack."""
    metas, packs, objects = {}, {}, {}
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        db.execute('PRAGMA cache_size=-2048')
        db.execute('PRAGMA query_only=ON')
        for name, size, category in db.execute('SELECT metapack_name,file_size,category FROM metapack'):
            value = (size, category)
            if name in metas and metas[name] != value:
                raise ValueError(f'Metapack conflict within {profile}: {name}')
            metas[name] = value
            add(objects, name, size, profile)
        row_count, duplicate_rows, mixed_parents = 0, 0, []
        cursor = db.execute('SELECT package_key,pack_name,file_size,metapack_name,metapack_offset,category FROM m_asset_package_mapping')
        for package, name, size, parent, offset, category in cursor:
            row_count += 1
            if name in metas:
                raise ValueError(f'Pack/metapack name collision: {name}')
            if parent is not None and parent not in metas:
                raise ValueError(f'Dangling metapack in {profile}: {name}/{parent}')
            if parent is None:
                add(objects, name, size, profile)
            if name in packs:
                duplicate_rows += 1
                if packs[name][0] != size:
                    raise ValueError(f'Pack size conflict within {profile}: {name}')
                if packs[name][1] != parent:
                    mixed_parents.append(name)
                continue
            packs[name] = (size, parent)
        marker = None
        exists = db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='elichika_jp_global_merge'").fetchone()[0]
        if exists:
            marker = db.execute('SELECT id,source_sha,algorithm_version FROM elichika_jp_global_merge').fetchall()
    return {'metas': metas, 'packs': packs, 'objects': objects,
            'evidence': {'mapping_rows': row_count, 'distinct_packs': len(packs),
                         'metapacks': len(metas), 'whole_files_sql_union': len(objects),
                         'whole_bytes_sql_union': sum(obj['size'] for obj in objects.values()),
                         'duplicate_mapping_rows': duplicate_rows,
                         'mixed_parent_pack_names': sorted(set(mixed_parents)), 'jp_global_marker': marker}}


def go_whole_files(databases, language_order):
    """Go global maps: per locale Android then iOS; first equal-size pack wins."""
    metas, packs = {}, {}
    for language in language_order:
        region = 'jp' if language == 'ja' else 'gl'
        for platform in ('a', 'i'):
            current = databases[f'{region}/asset_{platform}_{language}.db']
            for name, meta in current['metas'].items():
                if name in metas and metas[name] != meta:
                    raise ValueError(f'Global metapack conflict: {name}')
                metas.setdefault(name, meta)
            for name, pack in current['packs'].items():
                if name in metas:
                    raise ValueError(f'Global pack/metapack collision: {name}')
                if name in packs:
                    if packs[name][0] != pack[0]:
                        raise ValueError(f'Global pack size conflict: {name}')
                    continue
                packs[name] = pack
    whole = {name: meta[0] for name, meta in metas.items()}
    whole.update((name, pack[0]) for name, pack in packs.items() if pack[1] is None)
    return whole


def run(apk, baseline, additions, output):
    apk, output = Path(apk), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if apk.stat().st_size != APK_BYTES or sha(apk) != APK_SHA256:
        raise ValueError('APK size/SHA256 differs from pinned v2026.11.14.1 release')
    official_raw = gzip.decompress(Path(baseline).read_bytes())
    delta_raw = Path(additions).read_bytes()
    if hashlib.sha256(official_raw).hexdigest() != SOURCE_CATALOG_SHA256:
        raise ValueError('Official baseline catalog differs from the original TAR inventory catalog')
    if hashlib.sha256(delta_raw).hexdigest() != SQL_ADDITIONS_SHA256:
        raise ValueError('SQL addition evidence differs from the reviewed static reconciliation')
    official, delta = json.loads(official_raw), json.loads(delta_raw)
    expected = {name: obj['size'] for name, obj in official['objects'].items()}
    for name, obj in delta['objects'].items():
        if name in expected:
            raise ValueError(f'Addition already in official baseline: {name}')
        expected[name] = obj['size']
    if len(expected) != EXPECTED_WHOLE_FILES or len(delta['objects']) != EXPECTED_ADD_ON_FILES or sum(expected.values()) != EXPECTED_BYTES:
        raise ValueError('Expected baseline plus exactly 52 stock migration additions')
    databases, objects, evidence = {}, {}, {}
    with zipfile.ZipFile(apk) as archive, tempfile.TemporaryDirectory(prefix='elichika-apk-catalog-') as scratch:
        members = archive.namelist()
        revision_name = 'assets/payload_revision.json'
        revision = json.loads(archive.read(revision_name)) if revision_name in members else None
        revision_summary = None if revision is None else {
            key: revision.get(key) for key in ('format', 'compatibility_epoch', 'jp_global_algorithm', 'revision')}
        if revision is not None:
            revision_summary['manifest_sha256'] = hashlib.sha256(archive.read(revision_name)).hexdigest()
            revision_summary['manifest_file_count'] = len(revision.get('files', {}))
        for relative, pin in sorted(DB_PINS.items()):
            member = 'assets/payload/assets/db/' + relative
            if members.count(member) != 1:
                raise ValueError(f'Missing or duplicate packaged DB: {member}')
            path = Path(scratch) / relative.replace('/', '_')
            with archive.open(member) as source, path.open('xb') as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
            actual = sha(path)
            if actual != pin:
                raise ValueError(f'Packaged DB differs from retained signed APK audit: {relative}/{actual}')
            region, filename = relative.split('/')
            platform, language = filename[6], filename[8:10]
            profile = f'{region}/{"android" if platform == "a" else "ios"}/{language}'
            current = scan_database(path, profile)
            databases[relative] = current
            evidence[relative] = {'profile': profile, 'bytes': path.stat().st_size, 'sha256': actual, **current['evidence']}
            for name, obj in current['objects'].items():
                add(objects, name, obj['size'], profile)
            path.unlink()
    variants, reference = [], None
    for order in itertools.permutations(LANGUAGES):
        whole = go_whole_files(databases, order)
        if reference is None:
            reference = whole
        if whole != reference:
            raise ValueError(f'Go download set depends on locale map iteration order: {order}')
        variants.append({'locale_order': list(order), 'whole_files': len(whole), 'declared_bytes': sum(whole.values())})
    actual = {name: obj['size'] for name, obj in objects.items()}
    if actual != reference:
        raise ValueError('Per-DB whole-file SQL union differs from actual Go first-owner DownloadAllMissing set')
    if actual != expected:
        mismatch = {'missing': sorted(expected.keys() - actual.keys()), 'extra': sorted(actual.keys() - expected.keys()),
                    'wrong_sizes': [name for name in actual.keys() & expected.keys() if actual[name] != expected[name]]}
        (output / 'catalog-mismatch.json').write_bytes(canonical(mismatch))
        raise ValueError('Released APK target differs from official baseline plus 52 stock SQL additions')
    for obj in objects.values():
        obj['profiles'].sort()
    catalog = {'schema': 1,
               'scope': 'Released v2026.11.14.1 signed APK stock initialized DBs; exact Go DownloadAllMissing target; full metapacks plus standalone packs',
               'provenance': {'apk_sha256': APK_SHA256, 'apk_bytes': APK_BYTES, 'app_source_commit': APP_COMMIT,
                              'release': 'v2026.11.14.1', 'go_locale_orders_checked': 24,
                              'official_source_catalog_sha256': SOURCE_CATALOG_SHA256,
                              'sql_additions_json_sha256': SQL_ADDITIONS_SHA256},
               'databases': [{'path': key, 'profile': item['profile'], 'sha256': item['sha256']} for key, item in evidence.items()],
               'profiles': sorted(item['profile'] for item in evidence.values()), 'objects': dict(sorted(objects.items()))}
    raw = canonical(catalog)
    (output / 'expected-catalog-app42830.json.gz').write_bytes(gzip.compress(raw, mtime=0))
    added = {name: objects[name] for name in sorted(actual.keys() - official['objects'].keys())}
    (output / 'stock-migration-52.json').write_bytes(canonical(added))
    report = {'status': 'PASS', 'source_commit': APP_COMMIT, 'apk_sha256': APK_SHA256,
              'apk_bytes': APK_BYTES, 'official_baseline_files': len(official['objects']),
              'stock_migration_added_files': len(added), 'stock_migration_added_declared_bytes': sum(obj['size'] for obj in added.values()),
              'actual_go_whole_files': len(actual), 'actual_declared_bytes': sum(actual.values()),
              'catalog_sha256': hashlib.sha256(raw).hexdigest(), 'locale_orders': variants,
              'databases': evidence, 'payload_revision': revision_summary,
              'limits': ['Stock released APK DBs only; no installed user modifications', 'Declared catalog sizes only; no pack payload hash verification']}
    (output / 'apk-catalog-report.json').write_bytes(canonical(report))
    print(json.dumps({key: report[key] for key in ('status', 'actual_go_whole_files', 'actual_declared_bytes', 'catalog_sha256')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', required=True)
    parser.add_argument('--official-catalog', required=True)
    parser.add_argument('--sql-additions', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    run(args.apk, args.official_catalog, args.sql_additions, args.output)

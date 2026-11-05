"""Generate a tiny, valid payload for installer/settings instrumentation only.

Uses the standard library and synthetic rows. No game process is started from
this fixture; it satisfies the same production updater coverage checks without
bundling the real game databases in the instrumentation APK.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys


ALGORITHM = 'jp-global-content-v1'
MARKER = '.server-config-fixture'
MARKER_CONTENT = 'synthetic-server-config-payload-v1\n'
CONFIG = b'{"cdn_cache":false,"cdn_cache_dir":"","preserved":"bundled default"}\n'


def database(path, script):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(script)
        connection.commit()


def generate(output, *, manifest_output=None):
    output = Path(output)
    if output.is_symlink():
        raise ValueError('Fixture output must not be a symlink')
    if output.exists():
        marker = output / MARKER
        if not marker.is_file() or marker.read_text() != MARKER_CONTENT:
            raise ValueError('Refusing to replace an unrecognized fixture directory')
        shutil.rmtree(output)
    output.mkdir(parents=True)

    sources = {
        'masterdata.db': "CREATE TABLE fixture_catalog(id INTEGER PRIMARY KEY,value TEXT NOT NULL); INSERT INTO fixture_catalog VALUES(1,'synthetic master');",
        'asset_a_ja.db': "CREATE TABLE fixture_asset(id INTEGER PRIMARY KEY,value TEXT NOT NULL); INSERT INTO fixture_asset VALUES(1,'synthetic Android asset');",
        'asset_i_ja.db': "CREATE TABLE fixture_asset(id INTEGER PRIMARY KEY,value TEXT NOT NULL); INSERT INTO fixture_asset VALUES(1,'synthetic iOS asset');",
    }
    for name, script in sources.items():
        database(output / 'assets/db/jp' / name, script)

    pairs = [('masterdata.db', 'masterdata.db')]
    pairs += [(f'asset_{platform}_ja.db', f'asset_{platform}_{language}.db')
              for platform in ('a', 'i') for language in ('en', 'ko', 'zh')]
    for source_name, target_name in pairs:
        source = output / 'assets/db/jp' / source_name
        target = output / 'assets/db/gl' / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        # JP sources are finalized and closed before hashing. Only the GL copy
        # receives the coverage marker, so its source digest remains authoritative.
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        shutil.copyfile(source, target)
        with closing(sqlite3.connect(target)) as connection:
            connection.execute('CREATE TABLE elichika_jp_global_merge(id INTEGER PRIMARY KEY,source_sha TEXT,algorithm_version TEXT)')
            connection.execute('INSERT INTO elichika_jp_global_merge VALUES(1,?,?)', (digest, ALGORITHM))
            connection.commit()

    for region, language in [('jp', 'ja'), ('gl', 'en'), ('gl', 'ko'), ('gl', 'zh')]:
        database(output / f'assets/db/{region}/dictionary_{language}_k.db',
                 'CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT NOT NULL);'
                 f"INSERT INTO m_dictionary VALUES('synthetic_setting','Synthetic {language} setting');")
    database(output / 'serverdata.db',
             'CREATE TABLE fixture_settings(id INTEGER PRIMARY KEY,value TEXT NOT NULL);'
             "INSERT INTO fixture_settings VALUES(1,'synthetic server setting');")
    (output / 'config.json').write_bytes(CONFIG)
    webui = output / 'webui/index.html'
    webui.parent.mkdir()
    webui.write_text('<!doctype html><title>Synthetic settings fixture</title>\n')
    (output / MARKER).write_text(MARKER_CONTENT)
    if manifest_output is not None:
        # Gradle owns the entire generated assets directory, including this
        # sibling. Generate it here rather than relying on workflow pre-work
        # surviving Gradle's stale-output cleanup. Reuse the production builder
        # so fixture and game payloads have exactly the same revision contract.
        helper = Path(__file__).resolve().parents[2] / 'payload_revision.py'
        subprocess.run([sys.executable, str(helper), 'create', '--payload', str(output),
                        '--output', str(manifest_output)], check=True, capture_output=True, text=True)
    files = [path for path in output.rglob('*') if path.is_file()]
    return {'database_count': sum(path.suffix == '.db' for path in files),
            'total_bytes': sum(path.stat().st_size for path in files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest-output', type=Path,
                        help='Revision manifest outside the generated payload, for instrumentation assets')
    args = parser.parse_args()
    print(json.dumps(generate(args.output, manifest_output=args.manifest_output), sort_keys=True))


if __name__ == '__main__':
    main()

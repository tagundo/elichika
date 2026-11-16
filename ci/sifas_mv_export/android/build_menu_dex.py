#!/usr/bin/env python3
"""Inert unless --build: update released b25 Java/Dex only, never package/sign.

The bridge includes the offline MV controls and encoder. This script changes
DEX only; the separate exact-input ELF patcher owns native MV hook packaging.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile

HERE = Path(__file__).resolve().parent
SDK = Path(os.environ.get('SIFAS_ANDROID_SDK', '/workspace/android-build/sdk'))
ANDROID = SDK / 'platforms/android-34/android.jar'
EXTERNAL = Path(os.environ.get('SIFAS_ANDROID_JAVA_DEPS', str(SDK / 'cmdline-tools/latest/lib/external')))
DEXLIB = EXTERNAL / 'com/android/tools/smali/smali-dexlib2/3.0.3/smali-dexlib2-3.0.3.jar'
GUAVA = EXTERNAL / 'com/google/guava/guava/31.1-jre/guava-31.1-jre.jar'
FAILUREACCESS = EXTERNAL / 'com/google/guava/failureaccess/1.0.1/failureaccess-1.0.1.jar'
D8 = SDK / 'build-tools/34.0.0/lib/d8.jar'
BASELINES = {
    'GL': {'path': '/dev/shm/sifas-android-material-b25-GL-20261115/LLAS_GL_FOVMOD_b25.apk',
        'apk_sha256': '157f92a46fcaefaca52c2c8209b35e059773be62fc74a8c8e20c2ac3f9dea738',
        'dex_sha256': 'b3444ee457e62b82240b416038d90069256493bfb94275e2603cc80c9ad5152f', 'dex_bytes': 7162052},
    'JP': {'path': '/dev/shm/sifas-android-material-b25-JP-20261115/LLAS_JP_FOVMOD_b25.apk',
        'apk_sha256': '488d727001bbc125fc1c16f83f6bd29482384359b9bee0c22e7c6f7664742220',
        'dex_sha256': 'c409fd6b03719f7d3a7918b5980d93344b0973145690f409cc162d086bec103a', 'dex_bytes': 7161880},
}
BRIDGE_NAMES = ('FovMod', 'AndroidMVExport', 'AndroidMVEncoder', 'MVExportContract', 'MP4Gapless')
BRIDGE_SOURCES = tuple(HERE/(name+'.java') for name in BRIDGE_NAMES)


def bridge_class_allowed(name):
    prefix = 'com/klab/lovelive/allstars/fovmod/'
    return name.startswith(prefix) and any(name == prefix+root+'.class'
        or (name.startswith(prefix+root+'$') and name.endswith('.class')) for root in BRIDGE_NAMES)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def command(args, output, label):
    completed = subprocess.run([str(x) for x in args], capture_output=True, text=True, timeout=180)
    (output / (label + '.stdout')).write_text(completed.stdout)
    (output / (label + '.stderr')).write_text(completed.stderr)
    require(completed.returncode == 0, label + ' failed; exact stdout/stderr retained')
    return completed.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--region', choices=BASELINES, default='GL')
    parser.add_argument('--input-apk', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    if not args.build:
        print(json.dumps({'status': 'INERT_SOURCE_ONLY', 'APK_build': False, 'signing': False,
            'network': False, 'date_title': 'PackageInfo.versionName canonical date suffix',
            'baseline': BASELINES[args.region]}))
        return
    require(not os.environ.get('PYTHONOPTIMIZE') and not __import__('sys').flags.optimize,
        'Optimized Python is unsupported')
    row = BASELINES[args.region]
    source = args.input_apk or Path(row['path'])
    require(source.is_file() and not source.is_symlink() and sha(source) == row['apk_sha256'],
        'Exact released b25 APK required; no older b21 native/suit/material regressions')
    output = args.output_dir
    require(output is not None and not output.exists() and not output.is_symlink(),
        'Fresh owned DEX output directory required')
    require(output.parent.is_dir() and not output.parent.is_symlink(), 'Ordinary output parent required')
    output.mkdir(mode=0o700)
    for name in ('bridge-classes', 'tool-classes', 'replacement', 'verify-tmp'):
        (output / name).mkdir(mode=0o700)
    inputs = [*BRIDGE_SOURCES, HERE/'UpdateFovDex.java', Path(__file__).resolve(),
        ANDROID, DEXLIB, GUAVA, FAILUREACCESS, D8]
    before = {str(p): sha(p) for p in inputs}
    original = output/'released-b25.dex'
    with zipfile.ZipFile(source) as apk:
        require(len([x for x in apk.infolist() if x.filename == 'classes.dex']) == 1,
            'Single original classes.dex required')
        info = apk.getinfo('classes.dex')
        require(info.file_size == row['dex_bytes'], 'Released DEX size differs')
        with apk.open(info) as incoming, original.open('xb') as target:
            digest = hashlib.sha256()
            while block := incoming.read(1024*1024):
                digest.update(block)
                target.write(block)
        require(digest.hexdigest() == row['dex_sha256'], 'Released DEX differs')
    java = ['java', '-Xmx384m', '-Djava.io.tmpdir='+str(output/'verify-tmp')]
    compiler = java + ['--module', 'jdk.compiler/com.sun.tools.javac.Main', '-source', '8',
        '-target', '8', '-parameters', '-Xlint:-options', '-encoding', 'UTF-8']
    command(compiler + ['-bootclasspath', ANDROID, '-cp', ANDROID, '-d', output/'bridge-classes',
        *BRIDGE_SOURCES], output, 'compile-bridge')
    bridge = output/'fov-bridge.jar'
    with zipfile.ZipFile(bridge, 'x', compression=zipfile.ZIP_STORED) as archive:
        for p in sorted((output/'bridge-classes').rglob('*.class')):
            name = str(p.relative_to(output/'bridge-classes'))
            require(bridge_class_allowed(name),
                'Test or unrelated class must never enter the game bridge')
            info = zipfile.ZipInfo(name, date_time=(2000,1,1,0,0,0))
            info.external_attr = 0o100600 << 16
            archive.writestr(info, p.read_bytes())
    command(java + ['-cp', D8, 'com.android.tools.r8.D8', '--min-api', '21', '--lib', ANDROID,
        '--output', output/'replacement', bridge], output, 'compile-replacement-dex')
    dependencies = os.pathsep.join(map(str, [DEXLIB, GUAVA, FAILUREACCESS]))
    command(compiler + ['-cp', dependencies, '-d', output/'tool-classes', HERE/'UpdateFovDex.java'],
        output, 'compile-updater')
    updated = output/'classes.dex'
    result = json.loads(command(java + ['-cp', str(output/'tool-classes')+os.pathsep+dependencies,
        'UpdateFovDex', original, output/'replacement/classes.dex', updated, args.region,
        output/'verify-tmp'], output, 'update-dex'))
    require(result['status'] == 'PASS_INCREMENTAL_B25_DEX_UPDATE', 'Incremental DEX proof absent')
    require(sha(source) == row['apk_sha256'] and before == {str(p): sha(p) for p in inputs},
        'Baseline APK or build sources changed')
    report = {'status': 'JAVA_DEX_UPDATED_NOT_PACKAGED_OR_DEVICE_TESTED', 'region': args.region,
        'source_apk_sha256': row['apk_sha256'], 'source_dex_sha256': row['dex_sha256'],
        'output_dex': str(updated), 'output_dex_sha256': sha(updated),
        'output_dex_bytes': updated.stat().st_size, 'updater_result': result,
        'source_and_tool_sha256': before, 'native_binaries_changed': False,
        'AndroidManifest_changed': False, 'APK_created_or_signed': False,
        'future_packager': 'Package this DEX with separately verified MV native ELF outputs and shared-date metadata in the same exact b25 baseline; preserve every other retained entry and use the existing stable signer.',
        'unix': time.time()}
    (output/'build-report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()

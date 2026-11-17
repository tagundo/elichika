#!/usr/bin/env python3
"""Compile and execute the production MP4 encoder with a real Apple SDK/runtime.

No game, Python.framework, downloaded SDK, third-party codec, or mock writer is
used. The report explicitly leaves actual MV rendering unproven.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='Fresh bounded test directory')
    parser.add_argument('--direct-input', action='store_true', help='Encode from the bounded production pixel-buffer pool')
    args = parser.parse_args()
    if platform.system() != 'Darwin':
        print('Apple AVAssetWriter runtime test requires macOS and Xcode; no runtime result was produced.', file=sys.stderr)
        return 2
    out = args.out.resolve()
    if out.exists():
        raise SystemExit('Refusing to reuse an existing encoder test directory')
    out.mkdir(parents=True)
    native = Path(__file__).resolve().parents[1]
    sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
    compiler = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--find', 'clang++'], text=True).strip()
    command = [compiler, '-isysroot', sdk, '-std=c++17', '-fobjc-arc', '-fblocks', '-O2',
               '-Wall', '-Wextra', '-Werror', '-Wno-deprecated-declarations',
               '-Wno-nullability-completeness', '-I', str(native),
               str(native / 'ElichikaMVEncoder.mm'), str(native / 'tests/MVEncoderIntegration.mm'),
               '-framework', 'Foundation', '-framework', 'AVFoundation',
               '-framework', 'CoreVideo', '-framework', 'CoreMedia',
               '-framework', 'AudioToolbox', '-framework', 'VideoToolbox',
               '-o', str(out / 'mv-encoder-integration')]
    if args.direct_input:
        command.insert(1, '-DELMV_TEST_DIRECT_INPUT=1')
    subprocess.run(command, check=True, timeout=120)
    subprocess.run([str(out / 'mv-encoder-integration'), str(out / 'runtime')], check=True, timeout=160)
    report = json.loads((out / 'runtime/report.json').read_text())
    if report.get('status') != 'PASS_APPLE_AVASSETWRITER_RUNTIME':
        raise SystemExit('The encoder runtime did not report success')
    if args.direct_input and report['h264_aac'].get('input_path') != 'direct-pooled-CVPixelBuffer':
        raise SystemExit('Direct-buffer encode path was not exercised')
    (out / 'compile-command.json').write_text(json.dumps({'command': command, 'actual_Apple_SDK_compile': True}, indent=2) + '\n')
    print('PASS: production H.264/AAC encoder and independent MP4 decode on Apple runtime')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

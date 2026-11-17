#!/usr/bin/env python3
"""Run production direct-buffer contract tests with real Apple CoreVideo buffers.

The recording adaptor verifies ownership and append semantics; it does not prove
codec compatibility, encoded pixels, or actual Unity MV rendering.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import platform
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='Fresh bounded test directory')
    args = parser.parse_args()
    if platform.system() != 'Darwin':
        print('Pixel-buffer contract tests require macOS and Xcode; no runtime result was produced.', file=sys.stderr)
        return 2
    out = args.out.resolve()
    if out.exists():
        raise SystemExit('Refusing to reuse an existing pixel-buffer test directory')
    out.mkdir(parents=True)
    native = Path(__file__).resolve().parents[1]
    sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
    compiler = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--find', 'clang++'], text=True).strip()
    binary = out / 'mv-encoder-pixel-buffer-tests'
    command = [compiler, '-isysroot', sdk, '-std=c++17', '-fobjc-arc', '-fblocks', '-O2',
               '-Wall', '-Wextra', '-Werror', '-Wno-deprecated-declarations',
               '-Wno-nullability-completeness', '-I', str(native),
               str(native / 'ElichikaMVEncoder.mm'), str(native / 'tests/MVEncoderPixelBufferTests.mm'),
               '-framework', 'Foundation', '-framework', 'AVFoundation',
               '-framework', 'CoreVideo', '-framework', 'CoreMedia',
               '-framework', 'AudioToolbox', '-framework', 'VideoToolbox',
               '-o', str(binary)]
    subprocess.run(command, check=True, timeout=120)
    subprocess.run([str(binary)], check=True, timeout=15)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

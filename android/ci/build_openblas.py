"""Build a 16KB-compatible BLAS/LAPACK wheel without the legacy Fortran runtime."""
import argparse
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import zipfile
from audit_native import elf_layout

SOURCE_COMMIT = '62bcfb0dc9f1cfa685fc04135c50e2780c303137'
VERSION = '0.3.33'
DIST_INFO = f'chaquopy_openblas-{VERSION}.dist-info'


def run(*args):
    subprocess.run([str(v) for v in args], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'ndk', 'work', 'wheel'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(['git','-C',str(args.source),'rev-parse','HEAD'],text=True).strip()
    assert revision == SOURCE_COMMIT, 'OpenBLAS source revision changed'
    run('git','-C',args.source,'diff','--quiet','HEAD')
    args.work.mkdir(parents=True,exist_ok=True)
    wrapper=args.work/'wrapper';wrapper.mkdir()
    (wrapper/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.16)
project(elichika_openblas C ASM)
add_subdirectory("${OPENBLAS_SOURCE}" openblas)
set_target_properties(openblas_shared PROPERTIES NO_SONAME TRUE)
target_link_options(openblas_shared PRIVATE "-Wl,-soname,libopenblas.so")
''')
    build=args.work/'build'
    run('cmake','-S',wrapper,'-B',build,
        '-DOPENBLAS_SOURCE='+str(args.source.resolve()),
        '-DCMAKE_TOOLCHAIN_FILE='+str(args.ndk.resolve()/'build/cmake/android.toolchain.cmake'),
        '-DANDROID_ABI=arm64-v8a','-DANDROID_PLATFORM=android-24',
        '-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON','-DCMAKE_BUILD_TYPE=Release',
        '-DCMAKE_SHARED_LINKER_FLAGS=-Wl,-z,max-page-size=16384,-z,common-page-size=16384',
        '-DCMAKE_Fortran_COMPILER=NOTFOUND','-DNOFORTRAN=ON','-DC_LAPACK=ON',
        '-DBUILD_SHARED_LIBS=ON','-DBUILD_STATIC_LIBS=OFF','-DBUILD_TESTING=OFF',
        '-DBUILD_WITHOUT_LAPACK=OFF','-DBUILD_WITHOUT_LAPACKE=ON',
        '-DTARGET=ARMV8','-DBINARY=64','-DUSE_THREAD=OFF','-DUSE_LOCKING=ON',
        '-DNUM_THREADS=8','-DFIXED_LIBNAME=ON')
    run('cmake','--build',build,'--target','openblas_shared','-j',str(os.cpu_count() or 2))
    library=next(p for p in build.rglob('libopenblas.so') if p.is_file())
    tc=args.ndk/'toolchains/llvm/prebuilt/linux-x86_64/bin'
    run(tc/'llvm-strip','--strip-unneeded',library)
    dynamic=subprocess.check_output([str(tc/'llvm-readelf'),'-d',str(library)],text=True)
    assert '[libopenblas.so]' in dynamic, 'NumPy requires this exact OpenBLAS SONAME'
    assert 'libgfortran' not in dynamic, 'Legacy Fortran runtime was not removed'
    symbols=subprocess.check_output([str(tc/'llvm-readelf'),'--dyn-syms','--wide',str(library)],text=True)
    for name in ('dgesv_', 'sgesv_', 'zgesv_', 'cgesv_', 'dgesdd_', 'dsyevd_', 'cblas_dgemm'):
        assert name in symbols, 'Missing NumPy BLAS/LAPACK ABI symbol: '+name
    data=library.read_bytes();segments=elf_layout(data)
    assert all(s['compatible'] for s in segments), 'OpenBLAS is not 16KB compatible'
    files={
        'chaquopy/lib/libopenblas.so':data,
        DIST_INFO+'/LICENSE.OpenBLAS':(args.source/'LICENSE').read_bytes(),
        DIST_INFO+'/LICENSE.LAPACK':(args.source/'lapack-netlib/LICENSE').read_bytes(),
        DIST_INFO+'/METADATA':f'Metadata-Version: 2.1\nName: chaquopy-openblas\nVersion: {VERSION}\nSummary: OpenBLAS with C LAPACK and Android 16KB pages\nLicense: BSD-3-Clause\n\n'.encode(),
        DIST_INFO+'/WHEEL':b'Wheel-Version: 1.0\nGenerator: elichika-android-ci\nRoot-Is-Purelib: false\nBuild: 1\nTag: py3-none-android_24_arm64_v8a\n\n',
    }
    record=io.StringIO();writer=csv.writer(record,lineterminator='\n')
    for name,value in sorted(files.items()):
        digest=base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b'=').decode()
        writer.writerow([name,'sha256='+digest,len(value)])
    writer.writerow([DIST_INFO+'/RECORD','','']);files[DIST_INFO+'/RECORD']=record.getvalue().encode()
    args.wheel.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(args.wheel,'w') as archive:
        for name,value in sorted(files.items()):
            entry=zipfile.ZipInfo(name,date_time=(2024,1,1,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED;entry.external_attr=0o644<<16
            archive.writestr(entry,value)
    print(json.dumps({'source_commit':revision,'version':VERSION,'native_sha256':hashlib.sha256(data).hexdigest(),
                      'fortran_runtime_required':False,'load_segments':segments},indent=2))


if __name__=='__main__':main()

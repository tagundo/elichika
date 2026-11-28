#!/usr/bin/env python3
"""Build exact standalone MV native inputs against the pinned Theos SDK on Linux."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

SDK_COMMIT='0222fd5413cf4b9af096f37b4621afa2688572f7'
SDK_TREE='81466d46b666daa04ae3d2b0b9d5324f0f621359'
FRAMEWORKS=('Foundation','CoreFoundation','UIKit','AVFoundation','CoreMedia','CoreVideo','VideoToolbox','AudioToolbox','CoreGraphics')

def run(cmd, cwd=None, *, capture=False):
    return subprocess.run([str(v) for v in cmd], cwd=cwd, text=True, check=True, stdout=subprocess.PIPE if capture else None).stdout

def compile(repo, out, sdk, toolchain, source_commit=None):
    repo, out, sdk, toolchain = map(lambda path: Path(path).resolve(), (repo, out, sdk, toolchain))
    sys.path.insert(0,str(repo/'ios/build'))
    import build_standalone_mv as official
    from common import macho,require,sha256,write_json
    require(not out.exists() and not out.is_relative_to(repo),'Build output must be a new path outside the source tree')
    require(run(['git','rev-parse','HEAD'],sdk.parent,capture=True).strip()==SDK_COMMIT,'SDK source commit differs')
    require(run(['git','rev-parse','HEAD:'+sdk.name],sdk.parent,capture=True).strip()==SDK_TREE,'SDK tree differs')
    require(not run(['git','status','--porcelain','--',sdk.name],sdk.parent,capture=True).strip(),'SDK contents changed')
    if (repo/'.git').exists():
        head=run(['git','rev-parse','HEAD'],repo,capture=True).strip()
        require(not source_commit or head==source_commit,'Source checkout HEAD differs from expected')
        source_commit=head
        status=run(['git','status','--porcelain','--','ios/native','ios/build','ci/sifas_mv_export'],repo,capture=True)
        require(not status.strip(),'Native source check requires a clean checkout or an immutable scratch source snapshot')
    require(source_commit and len(source_commit)==40,'Specify the source commit for a Git archive tree')
    sources,decoder,inputs=official.source_inputs(repo)
    proof_inputs=inputs + [repo/x for x in ('ios/build/build_standalone_mv.py','ios/build/mv_export_profile.json','ios/build/inputs.lock.json')]
    pins={p.relative_to(repo).as_posix():sha256(p) for p in proof_inputs}
    flags=['-target','arm64-apple-ios13.0','-isysroot',str(sdk),'-O2','-fvisibility=hidden','-DSIFAS_STANDALONE=1']
    cxx_flags=['-isystem',str(sdk/'usr/include/c++/v1'),'-std=c++17','-fobjc-arc','-fblocks','-Wall','-Wextra','-Wno-deprecated-declarations','-Wno-nullability-completeness','-I',str(repo/'ios/native')]
    out.mkdir(parents=True)
    cmds=[]; objects=[]
    for source in [decoder,*sources]:
        obj=out/(source.stem+'.o'); objects.append(obj)
        cc=toolchain/('clang' if source==decoder else 'clang++')
        per=['-std=c11'] if source==decoder else cxx_flags
        cmd=[cc,*flags,*per,'-MMD','-MF',obj.with_suffix('.d'),'-c',source,'-o',obj]
        cmds.append(cmd); run(cmd,repo)
    dylib=out/official.LIBRARY
    cmd=[toolchain/'ld64.lld','-dylib','-arch','arm64','-platform_version','ios','13.0','16.5','-syslibroot',sdk,
        '-install_name',official.LOAD,'-headerpad_max_install_names','-no_adhoc_codesign','-o',dylib,*objects]
    for f in FRAMEWORKS:
        cmd.extend(('-framework',f))
    cmd.extend(('-lSystem','-lc++'))
    cmds.append(cmd); run(cmd,repo)
    image=macho(dylib,platform=2,kind=6)
    require(image['install_name']==official.LOAD,'Standalone install_name differs')
    require(all(name.startswith(('/System/Library/','/usr/lib/')) for name in image['loads']),'Non-system dylib load')
    symbols=run([toolchain/'llvm-nm','--extern-only','--defined-only',dylib],capture=True)
    require('_UIApplicationMain' not in symbols and '_ElichikaServerStart' not in symbols,'Unexpected app/server entry point')
    imports=run([toolchain/'llvm-nm','--extern-only','--undefined-only',dylib],capture=True)
    availability_imports=[name for name in ('__isPlatformVersionAtLeast','__isPlatformVersionAtLeastOrVariant',
                                           '__isOSVersionAtLeast','___availability_version_check') if name in imports]
    require(not availability_imports,'Unexpected compiler-rt availability imports: '+str(availability_imports))
    require(pins=={p.relative_to(repo).as_posix():sha256(p) for p in proof_inputs},'Native sources changed during compilation')
    project_dependencies={}
    for p in out.glob('*.d'):
        text=p.read_text().replace('\\\n',' ')
        for candidate in text.split(': ',1)[-1].split():
            q=Path(candidate).resolve()
            if q.is_relative_to(repo): project_dependencies[q.relative_to(repo).as_posix()]=sha256(q)
    background_inc='ios/native/SIFASMVMacBackground.inc'
    if (repo/background_inc).is_file():
        require(background_inc in pins and background_inc in project_dependencies,'Background helper was not pinned and compiled')
    report=dict(source_commit=source_commit,source_sha256=pins,project_dependencies_sha256=project_dependencies,
        native_compilation='Linux-host LLVM with commit-pinned Theos iPhoneOS16.5 SDK; no Xcode claim',
        SDK={'path':str(sdk),'commit':SDK_COMMIT,'tree':SDK_TREE},toolchain={'compiler':run([toolchain/'clang++','--version'],capture=True).splitlines()[0],
        'linker':run([toolchain/'ld64.lld','--version'],capture=True).splitlines()[0]},MachO=image,
        forbidden_compiler_rt_availability_imports=availability_imports,
        dylib_sha256=sha256(dylib),commands=[[str(i) for i in c] for c in cmds])
    write_json(out/'compile-proof.json',report)
    print(dylib)
    return dylib,report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--sdk', required=True, type=Path, help='iPhoneOS16.5.sdk in the pinned Theos SDK checkout')
    parser.add_argument('--toolchain', required=True, type=Path, help='NDK 28.2.13676358 host LLVM bin directory')
    parser.add_argument('--source-commit')
    args=parser.parse_args()
    compile(args.repo, args.out, args.sdk, args.toolchain, args.source_commit)

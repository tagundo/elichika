"""Convert a disposable fixed app with real pinned PlayCover code and test imports.

This is a macOS diagnostic, not a game install or a device/Simulator validation.
The input tree is copied first; the iOS staging app remains unchanged.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import struct
import subprocess
import sys
import time
import urllib.request

OWN=Path(__file__).resolve().parent
SOURCE='a103786e03b7f6257b6b489dfc49ca6712423a2e'
PINS={
    'PlayCover/Utils/Macho.swift':'7a1f716b2d80e7341782637cb879a53f2f6edfb93c0761e04154b63c5785fb9a',
    'PlayCover/Utils/Extensions/DataExtensions.swift':'025ce2140d916fe5c8e142bf64b09e3ee4568e1ae3de67afab423671c663ec70',
}
MAGIC=(b'\xcf\xfa\xed\xfe',b'\xca\xfe\xba\xbe',b'\xca\xfe\xba\xbf')
CHUNK=1024*1024
DEADLINE=None
DEBUG_RESOURCE={
    'path':'Frameworks/ElichikaHost.framework/ElichikaHost.dSYM/Contents/Resources/DWARF/ElichikaHost',
    'bytes':33221258,
    'sha256':'7d7967a663af2fc96d1f2811c8537a22b67308789886c92ce932b7f69256957b',
}

def need(value,why):
    if not value: raise ValueError(why)

def bounded_timeout(requested):
    if DEADLINE is None:return requested
    remaining=DEADLINE-time.monotonic()
    need(remaining>=1,'Consumer cooperative wall-clock budget exhausted')
    return min(requested,remaining)

def write(path,value):
    raw=(json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode()
    need(len(raw)<=CHUNK,'Small evidence capacity exceeded')
    with Path(path).open('xb') as stream: stream.write(raw)

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(CHUNK),b''):h.update(chunk)
    return h.hexdigest()

def run(argv,evidence,name,timeout=60,env=None):
    t=time.monotonic()
    try:
        p=subprocess.run(list(map(str,argv)),capture_output=True,timeout=bounded_timeout(timeout),env=env)
        row={'argv':list(map(str,argv)),'returncode':p.returncode,
            'stdout':p.stdout[:65536].decode(errors='replace'),'stderr':p.stderr[:65536].decode(errors='replace'),
            'truncated':len(p.stdout)>65536 or len(p.stderr)>65536}
    except subprocess.TimeoutExpired:
        row={'argv':list(map(str,argv)),'returncode':None,'timeout_seconds':timeout}
    row['elapsed_seconds']=time.monotonic()-t
    write(evidence/name,row)
    need(row['returncode']==0,'Bounded diagnostic failed: '+name)
    return row

def headers(path):
    with Path(path).open('rb') as f:
        first=f.read(8);need(len(first)==8,'Truncated Mach-O')
        if first[:4]==MAGIC[0]:offset=0
        else:
            magic,count=struct.unpack('>II',first)
            need(magic in (0xcafebabe,0xcafebabf) and count<=32,'Unsupported FAT input')
            width=20 if magic==0xcafebabe else 32;offset=None
            for _ in range(count):
                raw=f.read(width);need(len(raw)==width,'Truncated FAT record')
                values=struct.unpack('>5I' if width==20 else '>IIQQII',raw)
                if values[0]==0x100000c and values[1]&0xffffff==0:offset=values[2]
            need(offset is not None,'Missing arm64 slice')
        f.seek(offset);raw=f.read(32);need(len(raw)==32,'Truncated thin header')
        magic,cpu,subtype,kind,count,size,flags,reserved=struct.unpack('<8I',raw)
        need(magic==0xfeedfacf and cpu==0x100000c and count<=4096 and size<=CHUNK,'Unexpected Mach-O header')
        data=f.read(size);need(len(data)==size,'Truncated load commands')
    at=0;platforms=[];loads=[];legacy=[]
    for _ in range(count):
        need(at+8<=size,'Truncated command')
        cmd,length=struct.unpack_from('<II',data,at)
        need(length>=8 and at+length<=size,'Invalid command extent')
        raw=data[at:at+length]
        if cmd==0x32:
            need(length>=24,'Short platform command');platforms.append(struct.unpack_from('<I',raw,8)[0])
        elif cmd in (0x24,0x25,0x2f):legacy.append(cmd)
        elif cmd in (0xc,0x80000018,0x8000001f,0x80000023):
            need(length>=24,'Short dylib command');off=struct.unpack_from('<I',raw,8)[0]
            need(24<=off<length,'Invalid dylib name');loads.append(raw[off:].split(b'\0')[0].decode())
        at+=length
    need(at==size,'Command count differs')
    return {'platforms':platforms,'legacy':legacy,'loads':loads,'kind':kind,'cpu':cpu}

def native_files(app):
    rows=[];count=0
    for root,dirs,files in os.walk(app,followlinks=False):
        dirs[:]=[n for n in dirs if not (Path(root)/n).is_symlink()]
        for name in files:
            p=Path(root)/name;count+=1;need(count<=20000,'Native scan capacity exceeded')
            if p.is_symlink() or not p.is_file():continue
            with p.open('rb') as f:magic=f.read(4)
            if magic in MAGIC:rows.append(p)
    need(0<len(rows)<=256,'Unexpected native closure size')
    return sorted(rows)

def split_code_and_debug(app,natives,before):
    """Only the exact preserved Source13 MH_DSYM is not runnable code."""
    debug=[];code=[]
    for path in natives:
        relative=path.relative_to(app).as_posix()
        if before[relative]['kind']==10:
            need(relative==DEBUG_RESOURCE['path'] and path.stat().st_size==DEBUG_RESOURCE['bytes']
                 and digest(path)==DEBUG_RESOURCE['sha256'],'Unknown or changed nonruntime MH_DSYM resource')
            debug.append(path)
        else:code.append(path)
    need(len(debug)==1,'Exact Source13 debug resource missing')
    return code,debug

def framework_rows(app):
    rows=[]
    for fw in sorted((app/'Frameworks').glob('*.framework')):
        raw=(fw/'Info.plist').read_bytes();need(len(raw)<=65536,'Oversized framework metadata')
        info=plistlib.loads(raw);exe=info['CFBundleExecutable']
        need(isinstance(exe,str) and '/' not in exe and '\\' not in exe and exe not in ('','.','..'),'Unsafe executable metadata')
        binary=fw/exe;need(binary.is_file() and not binary.is_symlink(),'Missing declared framework binary')
        is_extension=fw.name.startswith('py.')
        kind='python_extension' if is_extension else 'codec' if fw.name in ('ElichikaHCA.framework','ElichikaTexture65.framework') else 'core'
        need(not is_extension or '.' not in exe,'Dot-named native extension still rejected by PlayCover')
        row={'framework':fw.name,'binary':binary.relative_to(app).as_posix(),'kind':kind,'executable':exe}
        if is_extension:
            origin=binary.with_name(binary.name+'.origin')
            need(origin.is_file() and not origin.is_symlink() and origin.stat().st_size<=1024,'Missing renamed origin record')
            stub=app/origin.read_text().strip()
            need(stub.resolve().is_relative_to(app.resolve()) and stub.suffix=='.fwork' and stub.is_file(),'Invalid origin target')
            need(stub.stat().st_size<=1024 and stub.read_text().strip()==row['binary'],'fwork and origin mapping disagree')
            row['fwork']=stub.relative_to(app).as_posix()
        rows.append(row)
    need(len(rows)<=128,'Unexpected framework count')
    return rows

def converter(work,evidence):
    for relative,expected in PINS.items():
        need(expected is not None,'Source pins were not frozen')
        url='https://raw.githubusercontent.com/PlayCover/PlayCover/'+SOURCE+'/'+relative
        with urllib.request.urlopen(url,timeout=bounded_timeout(30)) as r:raw=r.read(65537)
        need(len(raw)<=65536 and hashlib.sha256(raw).hexdigest()==expected,'Pinned converter source differs')
        (work/Path(relative).name).write_bytes(raw)
    header=work/'MachOHeaders.h'
    header.write_text('#include <mach-o/loader.h>\n#include <mach-o/fat.h>\n#include <mach-o/arch.h>\n#include <mach-o/swap.h>\n')
    main=work/'main.swift'
    main.write_text('''import Foundation
enum PlayCoverError: Error { case appCorrupted, failedToStripBinary }
guard CommandLine.arguments.count == 2 else { exit(2) }
let paths = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! [String]
for path in paths { try Macho.convertMacho(URL(fileURLWithPath:path)) }
''')
    exe=work/'playcover-convert'
    run(['/usr/bin/xcrun','swiftc','-import-objc-header',header,work/'Macho.swift',work/'DataExtensions.swift',main,'-o',exe],evidence,'converter-compile.json',90)
    return exe

def optional_alias_probe(app,work,evidence):
    """Observe OS launch separately; any error remains auxiliary evidence."""
    outcome={'actual_GUI_install':False,'gameplay_pass_claimed':False}
    try:
        info=plistlib.loads((app/'Info.plist').read_bytes())
        name=info.get('CFBundleDisplayName') or info['CFBundleName']
        need(isinstance(name,str) and '/' not in name and '\\' not in name,'Unsafe alias display name')
        alias=Path.home()/'Applications/PlayCover'/(name+'.app')
        need(not alias.exists() and not alias.is_symlink(),'A preexisting user alias prevents optional probe')
        alias.mkdir(parents=True,exist_ok=False)
        for entry in app.iterdir():
            target=alias/entry.name
            if entry.name=='Info.plist':shutil.copy2(entry,target)
            else:target.symlink_to(entry,target_is_directory=entry.is_dir())
        exe=work/'alias-launch-probe'
        run(['/usr/bin/xcrun','swiftc',OWN/'PlayCoverAliasLaunchProbe.swift','-o',exe],evidence,'optional-alias-compile.json',60)
        run([exe,alias,info['CFBundleIdentifier'],evidence/'optional-alias-nserror.json'],evidence,'optional-alias-launch.json',40)
        outcome.update(json.loads((evidence/'optional-alias-nserror.json').read_text()))
    except Exception as e:
        outcome.update(status='OPTIONAL_ALIAS_DIAGNOSTIC_INCOMPLETE',error_class=type(e).__name__,public_error=str(e)[:512])
    write(evidence/'optional-alias-outcome.json',outcome)
    return outcome

def main():
    global DEADLINE
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app',type=Path,required=True);p.add_argument('--work',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True)
    args=p.parse_args();need(sys.platform=='darwin' and os.environ.get('GITHUB_ACTIONS')=='true','Disposable Mac Actions runner required')
    root=Path(os.environ['RUNNER_TEMP']).resolve()
    need(args.work.resolve().is_relative_to(root) and args.evidence.resolve().is_relative_to(root),'Fresh output must remain within RUNNER_TEMP')
    args.work.mkdir(parents=True,exist_ok=False);args.evidence.mkdir(parents=True,exist_ok=False)
    DEADLINE=time.monotonic()+420
    work,evidence=args.work,args.evidence
    result={'schema':1,'status':'RUNNING','PlayCover_converter_source':SOURCE,'actual_gameplay':False,'actual_iPhone_iPad_execution':False,'actual_GUI_install':False}
    try:
        original=args.app.resolve();need(original.is_dir() and original.suffix=='.app','Fixed staged app required')
        app=work/'converted.app';shutil.copytree(original,app,symlinks=True)
        info=plistlib.loads((app/'Info.plist').read_bytes());need(info['CFBundleExecutable']=='global','Unexpected main executable')
        # The normal PlayCover assert(minimumVersion:11) metadata step, on the
        # disposable copy only. Raw fixed iOS output remains unchanged.
        if float(info.get('MinimumOSVersion','0'))>11:
            info['MinimumOSVersion']='11';(app/'Info.plist').write_bytes(plistlib.dumps(info))
        frameworks=framework_rows(app)
        need(len(frameworks)==92 and sum(r['kind']=='python_extension' for r in frameworks)==87,'Exact fixed native framework closure differs')
        stubs={p.relative_to(app).as_posix() for p in (app/'ElichikaResources/python/lib/python3.13').rglob('*.fwork')}
        need(stubs=={r['fwork'] for r in frameworks if r['kind']=='python_extension'},'A packaged fwork stub is missing or unmapped')
        write(evidence/'framework-mappings.json',frameworks)
        natives=native_files(app)
        need(len(natives)==100,'Exact 100-image native closure differs')
        before={f.relative_to(app).as_posix():headers(f) for f in natives};write(evidence/'platforms-before.json',before)
        code,debug=split_code_and_debug(app,natives,before)
        need(len(code)==99,'Exact 99-code-image closure differs')
        accepted=[f for f in code if f.suffix in ('','.dylib')]
        need(len(accepted)==99,'A code image remains excluded by the real filename filter')
        runtime={app/r['binary'] for r in frameworks if r['framework']!='CydiaSubstrate.framework'}
        need(runtime.issubset(set(accepted)),'A native runtime binary is still excluded by the real filename filter')
        write(evidence/'filter-acceptance.json',{'filter':'regular file, suffix empty or dylib, FAT/arm64 magic','traversal':'explicit recursive native closure; GUI traversal not claimed',
            'accepted':[f.relative_to(app).as_posix() for f in accepted],'excluded_code':[f.relative_to(app).as_posix() for f in code if f not in accepted],
            'preserved_nonruntime_MH_DSYM':DEBUG_RESOURCE})
        paths=work/'convert-paths.json';paths.write_text(json.dumps([str(f) for f in accepted]))
        exe=converter(work,evidence);run([exe,paths],evidence,'actual-playcover-convert.json',120)
        (app/'global').chmod(0o755)
        after={f.relative_to(app).as_posix():headers(f) for f in natives};write(evidence/'platforms-after.json',after)
        for path in code:
            key=path.relative_to(app).as_posix()
            need(after[key]['platforms']==[6] and not after[key]['legacy'],'Code image platform conversion differs: '+key)
        need(digest(debug[0])==DEBUG_RESOURCE['sha256'],'Nonruntime debug bytes changed during conversion')
        for row in frameworks:
            key=row['binary'];need(after[key]['platforms']==[6] and not after[key]['legacy'],'Framework platform conversion closure differs: '+key)
        for i,f in enumerate(accepted):run(['/usr/bin/codesign','--force','--sign','-',f],evidence,'sign-'+str(i)+'.json',15)
        for i,fw in enumerate(sorted((app/'Frameworks').glob('*.framework'))):
            run(['/usr/bin/codesign','--force','--sign','-',fw],evidence,'sign-framework-'+str(i)+'.json',15)
        run(['/usr/bin/codesign','--force','--sign','-',app],evidence,'sign-app.json',30)
        run(['/usr/bin/codesign','--verify','--deep','--strict',app],evidence,'signature-closure.json',30)
        need(digest(debug[0])==DEBUG_RESOURCE['sha256'],'Nonruntime debug bytes changed during signing')
        sdk=run(['/usr/bin/xcrun','--sdk','macosx','--show-sdk-path'],evidence,'mac-sdk.json')['stdout'].strip()
        helper=work/'python-native-probe'
        run(['/usr/bin/xcrun','clang','-target','arm64-apple-ios13.1-macabi','-isysroot',sdk,
            '-I'+str(app/'Frameworks/Python.framework/Headers'),'-F'+str(app/'Frameworks'),'-framework','Python',
            '-Wl,-rpath,'+str(app/'Frameworks'),OWN/'PlayCoverPythonImportProbe.c','-o',helper],evidence,'embedding-compile.json',90)
        run(['/usr/bin/codesign','--force','--sign','-',helper],evidence,'sign-embedding.json',15)
        env=os.environ.copy();env.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
        run([helper,app,OWN/'playcover_python_imports.py',evidence/'framework-mappings.json',evidence/'actual-native-imports.json'],evidence,'actual-embedded-imports.json',120,env)
        reply=json.loads((evidence/'actual-native-imports.json').read_text())
        need(reply['status']=='ACTUAL_CONVERTED_NATIVE_IMPORTS_PASS' and reply['codec_count']==8,'Native import proof did not pass')
        result.update(status='ACTUAL_PLAYCOVER_CONVERSION_AND_NATIVE_IMPORTS_PASS',native_headers=len(natives),code_images=len(code),preserved_debug_resources=[DEBUG_RESOURCE],frameworks=len(frameworks),mapped_extensions=reply['native_leaf_count'],codec_count=8,
                      qualification='Real converted packaged CPython/math/SSL/ctypes/NumPy/eight texture codecs and all mapped AOT dyld loads. No game/MV, GUI install or physical iOS execution.')
        result['optional_alias_launch']=optional_alias_probe(app,work,evidence)
    except Exception as e:
        result.update(status='FAILED',error_class=type(e).__name__,public_error=str(e)[:512]);raise
    finally:write(evidence/'result.json',result)

def self_test():
    import tempfile
    import unittest
    class Contracts(unittest.TestCase):
        def debug_fixture(self,root):
            path=root/DEBUG_RESOURCE['path'];path.parent.mkdir(parents=True)
            raw=struct.pack('<8I',0xfeedfacf,0x100000c,0,10,1,24,0,0)+struct.pack('<6I',0x32,24,2,0xd0000,0x120500,0)
            path.write_bytes(raw)
            return path,{'path':DEBUG_RESOURCE['path'],'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        def test_only_exact_pinned_debug_resource_is_not_code(self):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);debug,pin=self.debug_fixture(root);old=globals()['DEBUG_RESOURCE'];globals()['DEBUG_RESOURCE']=pin
                try:
                    code,resources=split_code_and_debug(root,[debug],{pin['path']:headers(debug)})
                    self.assertEqual(code,[]);self.assertEqual(resources,[debug])
                finally:globals()['DEBUG_RESOURCE']=old
        def test_unknown_debug_resource_fails_closed(self):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);debug,pin=self.debug_fixture(root);other=root/'unknown.dSYM';other.write_bytes(debug.read_bytes())
                old=globals()['DEBUG_RESOURCE'];globals()['DEBUG_RESOURCE']=pin
                try:
                    with self.assertRaises(ValueError):split_code_and_debug(root,[other],{'unknown.dSYM':headers(other)})
                finally:globals()['DEBUG_RESOURCE']=old
        def test_known_debug_resource_changed_bytes_rejected(self):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);debug,pin=self.debug_fixture(root);old=globals()['DEBUG_RESOURCE'];globals()['DEBUG_RESOURCE']=pin
                try:
                    raw=bytearray(debug.read_bytes());raw[-1]^=1;debug.write_bytes(raw)
                    with self.assertRaises(ValueError):split_code_and_debug(root,[debug],{pin['path']:headers(debug)})
                finally:globals()['DEBUG_RESOURCE']=old
        def test_expired_global_budget_rejects_another_command(self):
            old=globals()['DEADLINE'];globals()['DEADLINE']=time.monotonic()-1
            try:
                with self.assertRaises(ValueError):bounded_timeout(60)
            finally:globals()['DEADLINE']=old
        def test_global_budget_caps_requested_subprocess_timeout(self):
            old=globals()['DEADLINE'];globals()['DEADLINE']=time.monotonic()+3
            try:self.assertTrue(0<bounded_timeout(90)<=3)
            finally:globals()['DEADLINE']=old
        def test_platform_is_read_from_actual_load_commands(self):
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'native'
                for platform_id in (2,6):
                    path.write_bytes(struct.pack('<8I',0xfeedfacf,0x100000c,0,6,1,24,0,0)+struct.pack('<6I',0x32,24,platform_id,0xb0000,0xe0000,0))
                    self.assertEqual(headers(path)['platforms'],[platform_id])
        def test_oversized_commands_fail_before_body_read(self):
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'native';path.write_bytes(struct.pack('<8I',0xfeedfacf,0x100000c,0,6,1,CHUNK+1,0,0))
                with self.assertRaises(ValueError):headers(path)
        def fixture(self,root,exe='py_lib-dynload_math'):
            fw=root/'Frameworks/py.lib-dynload.math.framework';fw.mkdir(parents=True)
            (fw/'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':exe}))
            (fw/exe).write_bytes(b'12345678')
            stub=root/'ElichikaResources/python/lib/python3.13/lib-dynload/math.cpython-313-ios.fwork';stub.parent.mkdir(parents=True)
            stub.write_text('Frameworks/'+fw.name+'/'+exe+'\n')
            (fw/(exe+'.origin')).write_text(stub.relative_to(root).as_posix()+'\n')
            return fw,stub
        def test_same_directory_renamed_mapping_round_trip(self):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);self.fixture(root)
                row=framework_rows(root)[0]
                self.assertEqual(row['executable'],'py_lib-dynload_math')
                self.assertTrue(row['fwork'].endswith('.fwork'))
        def test_old_dotted_executable_rejected(self):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);self.fixture(root,'py.lib-dynload.math')
                with self.assertRaises(ValueError):framework_rows(root)
        def test_missing_renamed_origin_rejected(self):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);fw,stub=self.fixture(root)
                (fw/'py_lib-dynload_math.origin').unlink()
                with self.assertRaises(ValueError):framework_rows(root)
        def test_wrong_fwork_native_target_rejected(self):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);fw,stub=self.fixture(root)
                stub.write_text('Frameworks/elsewhere/bad\n')
                with self.assertRaises(ValueError):framework_rows(root)
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Contracts))
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':
    if sys.argv[1:]==['--self-test']:raise SystemExit(self_test())
    main()

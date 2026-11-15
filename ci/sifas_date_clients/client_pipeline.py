#!/usr/bin/env python3
"""Source-only by default. Explicit build creates unsigned APK/ad-hoc IPA candidates.

No upload, publication, Android key access, device installation or account API.
Released b25/v5 baselines are full-SHA pinned. Native Android payloads and the
already patched iOS executable are copied unchanged, never rebuilt/repatched.
"""
from __future__ import annotations
import argparse, copy, hashlib, importlib.util, json, os, pathlib, re, shutil
import stat, subprocess, sys, time, urllib.request, zipfile

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'metadata'))
from client_build_version import BuildVersion, output_filename
from client_metadata import update_android_manifest, update_ios_info_plist
CHUNK = 1024 * 1024
BASE_URL = 'https://github.com/tagundo/elichika/releases/download/v2026.11.14.1/'
BASELINES = {
 'android/GL': ('LLAS_GL_FOVMOD_b25.apk', 83535736, '157f92a46fcaefaca52c2c8209b35e059773be62fc74a8c8e20c2ac3f9dea738'),
 'android/JP': ('LLAS_JP_FOVMOD_b25.apk', 79691554, '488d727001bbc125fc1c16f83f6bd29482384359b9bee0c22e7c6f7664742220'),
 'ios/GL_Local': ('SIFAS_GL_Local_3.12.0_PlayCover_v5.ipa', 66457109, 'a3631c3aba709e09017f2d90599be334f21a001d4a7996864b53422fe643b6dc'),
 'ios/GL': ('SIFAS_GL_3.12.0_PlayCover_v5.ipa', 66142875, 'f5580ed0c1bf4dde10228dd658a589e5c25593a61a467330e05cec69f1df7b2f'),
 'ios/JP': ('SIFAS_JP_3.12.0_PlayCover_v5.ipa', 63222269, 'cc1e0c8d4c0d573b61351bac066832d07e4cb1aa776594a9ba525e21ccfbe6cb'),
}
IOS_MAIN_SHA = {'GL_Local':'071607a0b7e4d4e080af68ce9ce7c84cf279bf8e73e70ec9dc8cf1f3be1cd4dd',
 'GL':'071607a0b7e4d4e080af68ce9ce7c84cf279bf8e73e70ec9dc8cf1f3be1cd4dd',
 'JP':'32177423acdecfa39fce1c7ed9d4f18d6ad57ed980b39d5967229a5c56221e6a'}


def require(condition, message):
    if not condition: raise ValueError(message)


def sha(path):
    with pathlib.Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def member_sha(archive, name):
    with archive.open(name) as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def verify_lock():
    lock = json.loads((ROOT / 'source-lock.json').read_text())
    for name, pin in lock['files'].items():
        path = ROOT / name
        require(not path.is_symlink() and path.is_file() and path.stat().st_size == pin['bytes'] and sha(path) == pin['sha256'], 'Frozen source/tooling changed: ' + name)
    return lock


def fetch(url, target, size, expected):
    """One bounded public source download; no Authorization or account session."""
    require(url.startswith(BASE_URL), 'Unreviewed source URL')
    require(not target.exists(), 'Refusing existing download')
    target.parent.mkdir(parents=True, exist_ok=True)
    digest, count, deadline = hashlib.sha256(), 0, time.monotonic() + 900
    try:
        request = urllib.request.Request(url, headers={'Accept-Encoding':'identity','User-Agent':'sifas-date-client-candidate-builder/1'})
        with urllib.request.urlopen(request, timeout=45) as response, target.open('xb') as output:
            require(response.status == 200 and response.headers.get('Content-Encoding','identity') == 'identity', 'Source response is not complete/identity')
            while block := response.read(CHUNK):
                count += len(block)
                require(count <= size and time.monotonic() < deadline, 'Source size/deadline exceeded')
                digest.update(block); output.write(block)
        require(count == size and digest.hexdigest() == expected, 'Pinned source size/SHA256 mismatch')
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def inventory(archive):
    rows = archive.infolist(); names = [x.filename for x in rows]
    require(len(rows) < 10000 and len(names) == len(set(names)), 'Duplicate/excessive ZIP members')
    require(sum(x.file_size for x in rows) <= 1024 * CHUNK, 'Excessive expanded ZIP')
    for row in rows:
        name = row.filename; path = pathlib.PurePosixPath(name)
        require(name and not path.is_absolute() and '..' not in path.parts and '\\' not in name and '\x00' not in name, 'Unsafe ZIP path')
        mode = row.external_attr >> 16
        require(not stat.S_ISLNK(mode) and not row.flag_bits & 1, 'Symlink/encrypted ZIP member')
    return rows


def apk_signature(name):
    return bool(re.fullmatch(r'META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))', name, re.I))


def package(source, destination, replacements, *, android):
    """Repack without extraction; prove every retained payload/metadata unchanged."""
    require(not destination.exists() and source.resolve() != destination.resolve(), 'Fresh distinct output required')
    require(replacements, 'Explicit replacement set required')
    before_sha = sha(source)
    retained, proof = [], []
    with zipfile.ZipFile(source) as old:
        rows = inventory(old)
        require(set(replacements) <= {x.filename for x in rows}, 'Replacement target absent')
        require(not android or set(replacements) == {'AndroidManifest.xml','classes.dex'}, 'Android replacement scope must be manifest+DEX only')
        if not android:
            require(len(replacements) == 2 and any(x.endswith('/Info.plist') for x in replacements) and any(x.endswith('/Frameworks/SIFASFeatures.dylib') for x in replacements), 'iOS replacement scope must be main Info.plist+feature helper only')
        with zipfile.ZipFile(destination,'x',allowZip64=True,compression=zipfile.ZIP_DEFLATED,compresslevel=6) as new:
            new.comment = old.comment
            for row in rows:
                if android and apk_signature(row.filename): continue
                retained.append(row)
                with (replacements[row.filename].open('rb') if row.filename in replacements else old.open(row)) as incoming, new.open(copy.copy(row),'w') as outgoing:
                    shutil.copyfileobj(incoming,outgoing,CHUNK)
    attrs = ('filename','date_time','compress_type','comment','extra','create_system','external_attr','internal_attr','volume')
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(destination) as new:
        rows = inventory(new)
        require(len(rows) == len(retained) and new.comment == old.comment, 'ZIP member count/comment changed')
        for a,b in zip(retained,rows):
            require(all(getattr(a,k) == getattr(b,k) for k in attrs), 'ZIP metadata/order changed: ' + a.filename)
            digest = member_sha(new,b.filename)
            wanted = sha(replacements[a.filename]) if a.filename in replacements else member_sha(old,a.filename)
            require(digest == wanted, 'Unexpected archive payload change: ' + a.filename)
            if a.filename not in replacements:
                require(a.CRC == b.CRC and a.file_size == b.file_size, 'Unchanged member CRC/size changed')
            proof.append({'name':a.filename,'bytes':b.file_size,'sha256':digest,'replaced':a.filename in replacements})
    require(sha(source) == before_sha, 'Immutable baseline changed during packaging')
    return proof


def command(argv, log_dir, label, env=None):
    result = subprocess.run([str(x) for x in argv],capture_output=True,text=True,timeout=600,env=env)
    (log_dir/(label+'.stdout')).write_text(result.stdout)
    (log_dir/(label+'.stderr')).write_text(result.stderr)
    require(result.returncode == 0, 'Build step failed; retained sanitized local logs: ' + label)


def build_ios_helper(work, sdk):
    source = ROOT/'ios/src'; tool = ROOT/'ios/tooling/build_dylib_material.py'
    config = {'llvm_bin':str(sdk/'ndk/28.2.13676358/toolchains/llvm/prebuilt/linux-x86_64/bin'),
      'sources':[str(source/x) for x in ['SIFASFeatures.m','material_isolation.c','unity_material_backend.cpp','ios_mat_bindings.cpp','material_isolation_log.m']],
      'includes':[str(source)],'output':str(work/'SIFASFeatures.dylib'),
      'flags':{'c':['-O2','-fno-strict-aliasing'],'cxx':['-O2','-fno-strict-aliasing']}}
    config_path = work/'ios-helper-config.json';config_path.write_text(json.dumps(config,sort_keys=True)+'\n')
    plan = work/'ios-helper-plan.json'
    command([sys.executable,'-B',tool,'--config',config_path,'--plan',plan],work,'plan-ios-helper')
    command([sys.executable,'-B',tool,'--execute-plan',plan,'--approved-plan-sha256',sha(plan)],work,'build-ios-helper')
    return work/'SIFASFeatures.dylib'


def build_all(build, work, sdk):
    require(not work.exists() and work.parent.is_dir() and not work.parent.is_symlink(), 'Fresh owned output parent required')
    require(sdk.is_dir() and (sdk/'platforms/android-34/android.jar').is_file(), 'Explicit Android SDK/platform34 required')
    require(shutil.disk_usage(work.parent).free >= 2 * 1024**3, 'Hosted build needs at least2GiB free')
    lock = verify_lock();work.mkdir(mode=0o700);inputs=work/'inputs';inputs.mkdir();out=work/'candidates';out.mkdir()
    env = os.environ.copy();env['SIFAS_ANDROID_SDK']=str(sdk);env['SIFAS_ANDROID_JAVA_DEPS']=str(sdk/'cmdline-tools/12.0/lib/external')
    for dep in json.loads((ROOT/'android/java-dependencies.json').read_text()):
        path=sdk/'cmdline-tools/12.0/lib/external'/dep['path']
        require(path.is_file() and path.stat().st_size==dep['bytes'] and sha(path)==dep['sha256'], 'Pinned command-line-tools12.0 Java dependency differs')
    results=[]
    for region in ['GL','JP']:
        name,size,digest=BASELINES['android/'+region];baseline=fetch(BASE_URL+name,inputs/name,size,digest)
        dexout=work/('dex-'+region)
        command([sys.executable,'-B',ROOT/'android/build_menu_dex.py','--build','--region',region,'--input-apk',baseline,'--output-dir',dexout],work,'dex-'+region,env)
        manifest=work/('AndroidManifest-'+region+'.xml')
        with zipfile.ZipFile(baseline) as z:manifest.write_bytes(update_android_manifest(z.read('AndroidManifest.xml'),build))
        dest=out/(output_filename('android',region,build).removesuffix('.apk')+'-unsigned.apk')
        proof=package(baseline,dest,{'classes.dex':dexout/'classes.dex','AndroidManifest.xml':manifest},android=True)
        alignment=out/(dest.stem+'-aligned.apk')
        command([sdk/'build-tools/34.0.0/zipalign','-p','-f','4',dest,alignment],work,'align-'+region)
        dest.unlink();alignment.rename(dest)
        command([sdk/'build-tools/34.0.0/zipalign','-c','4',dest],work,'verify-align-'+region)
        # zipalign changes container offsets only; prove all member hashes again.
        with zipfile.ZipFile(dest) as z:
            inventory(z)
            require(all(member_sha(z,p['name'])==p['sha256'] for p in proof),'zipalign changed payload bytes')
        report={'status':'UNSIGNED_CANDIDATE_NOT_INSTALLABLE','region':region,'platform':'android','build':build.canonical,'source':{'url':BASE_URL+name,'bytes':size,'sha256':digest},'output':{'name':dest.name,'bytes':dest.stat().st_size,'sha256':sha(dest)},'members':proof,'native_binaries_byte_identical':True,'signing':'PENDING_EXISTING_STABLE_SIGNER','runtime':'NOT_TESTED'}
        (out/(dest.name+'.proof.json')).write_text(json.dumps(report,sort_keys=True)+'\n');results.append(report['output'])
    helper=build_ios_helper(work,sdk)
    for variant in ['GL_Local','GL','JP']:
        name,size,digest=BASELINES['ios/'+variant];baseline=fetch(BASE_URL+name,inputs/name,size,digest)
        app='allstars' if variant=='JP' else 'global';prefix='Payload/'+app+'.app/'
        plist=work/(variant+'-Info.plist')
        with zipfile.ZipFile(baseline) as z:
            require(member_sha(z,prefix+app)==IOS_MAIN_SHA[variant],'ReleasedV5 main differs')
            require(not any(x.filename.startswith(prefix+'_CodeSignature/') or x.filename==prefix+'embedded.mobileprovision' for x in z.infolist()),'Unexpected resource seal/provision in PlayCover baseline')
            plist.write_bytes(update_ios_info_plist(z.read(prefix+'Info.plist'),build))
        dest=out/output_filename('ios',variant,build)
        proof=package(baseline,dest,{prefix+'Info.plist':plist,prefix+'Frameworks/SIFASFeatures.dylib':helper},android=False)
        require(next(p['sha256'] for p in proof if p['name']==prefix+app)==IOS_MAIN_SHA[variant],'V5 native hook executable changed')
        report={'status':'ADHOC_PLAYCOVER_CANDIDATE_NOT_RUNTIME_TESTED','variant':variant,'platform':'ios','build':build.canonical,'source':{'url':BASE_URL+name,'bytes':size,'sha256':digest},'output':{'name':dest.name,'bytes':dest.stat().st_size,'sha256':sha(dest)},'members':proof,'V5_executable_byte_identical':True,'material_backend':'same five units; preserved V5 core/backend/bindings/log source pins','signing':'ld64.lld helper ad-hoc; unchanged ad-hoc executable; no Apple provisioning','runtime':'NOT_TESTED'}
        (out/(dest.name+'.proof.json')).write_text(json.dumps(report,sort_keys=True)+'\n');results.append(report['output'])
    verify_lock()
    (out/'SHA256SUMS').write_text(''.join(x['sha256']+'  '+x['name']+'\n' for x in results))
    receipt={'status':'CANDIDATES_BUILT_NO_UPLOAD_OR_RELEASE','build':build.canonical,'outputs':results,'source_lock_sha256':sha(ROOT/'source-lock.json'),'Android_signing':'pending protected existing stable signer','device_runtime_validation':'NOT_PERFORMED'}
    (out/'build-receipt.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n');print(json.dumps(receipt))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--build',required=True);p.add_argument('--execute-build',action='store_true');p.add_argument('--work',type=pathlib.Path);p.add_argument('--android-sdk',type=pathlib.Path);a=p.parse_args()
    build=BuildVersion.parse(a.build)
    if not a.execute_build:
        print(json.dumps({'status':'INERT_SOURCE_ONLY','build':build.canonical,'outputs':'2unsignedAPKs+3adhocIPAcandidates','signing_keys_read':False,'network':False}));return
    require(a.work is not None and a.android_sdk is not None,'Explicit work and Android SDK required')
    build_all(build,a.work.absolute(),a.android_sdk.resolve(strict=True))

if __name__=='__main__':main()

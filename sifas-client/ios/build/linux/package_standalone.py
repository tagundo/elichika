#!/usr/bin/env python3
"""Package a scratch-only Linux cross-build of the pinned standalone PlayCover IPA."""
import argparse
import hashlib
import json
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from verify_adhoc_pages import code_directories, images, verify_image

SIGNER_SHA256='dab9a7465f96aba3c81e793775510f745b91a46b6418e89f7317b5d8fc7bcea2'

def safe_member(root, name):
    row=PurePosixPath(name)
    if row.is_absolute() or '..' in row.parts:
        raise ValueError(f'Unsafe CodeResources relative path: {name}')
    path=root/row
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'CodeResources path escapes bundle: {name}')
    return path

def bundle_exec(root):
    p=root/'Info.plist'
    info=plistlib.loads(p.read_bytes())
    return p,safe_member(root,info['CFBundleExecutable'])

def cdhashes(path):
    out=set()
    funcs={1:'sha1',2:'sha256',3:'sha256',4:'sha384',5:'sha512'}
    for raw in images(path.read_bytes()):
        for _,directory,_ in code_directories(raw):
            out.add(hashlib.new(funcs[directory[37]],directory).digest()[:20])
    return out

def verify_resources(root, path):
    envelope=plistlib.loads(path.read_bytes())
    counts={}
    for field in ('files','files2'):
        entries=envelope.get(field,{})
        counts[field]=len(entries)
        for name, value in entries.items():
            member=safe_member(root,name)
            if isinstance(value,bytes): value={'hash':value}
            if not member.exists() and value.get('optional') is True:
                continue
            for key, algo in (('hash','sha1'),('hash2','sha256')):
                if key in value:
                    if member.is_symlink() or not member.is_file() or hashlib.new(algo,member.read_bytes()).digest()!=value[key]:
                        raise ValueError(f'CodeResources {algo} digest mismatch: {member}')
            if 'symlink' in value:
                if not member.is_symlink() or os.readlink(member)!=value['symlink']:
                    raise ValueError(f'CodeResources symlink mismatch: {member}')
            if 'cdhash' in value:
                binary=bundle_exec(member)[1] if member.is_dir() else member
                if value['cdhash'] not in cdhashes(binary):
                    raise ValueError(f'CodeResources nested cdhash mismatch: {member}')
    return counts

def verify_signed_app(app):
    from signature_proof import is_macho
    related={}; resources={}
    for directory in [app]+sorted(p for p in app.rglob('*') if p.is_dir() and p.suffix in ('.app','.framework','.appex') and not p.is_symlink()):
        info,executable=bundle_exec(directory)
        envelope=directory/'_CodeSignature/CodeResources'
        if not envelope.exists(): raise ValueError(f'Resource envelope missing for {directory.relative_to(app)}')
        related[executable]={1:info.read_bytes(),3:envelope.read_bytes()}
        resources[directory.relative_to(app).as_posix()]=verify_resources(directory,envelope)
    result={}
    for binary in sorted(p for p in app.rglob('*') if p.is_file() and not p.is_symlink()):
        with binary.open('rb') as src:
            if not is_macho(src.read(4)): continue
        data=binary.read_bytes()
        result[binary.relative_to(app).as_posix()]=[msg for raw in images(data) for msg in verify_image(raw,related.get(binary,{}),require_adhoc=True)]
    if not result or not all(executable.relative_to(app).as_posix() in result for executable in related):
        raise ValueError('Signed app code inventory incomplete')
    return dict(code_directory_page_hashes=result,resource_envelope_hashes=resources)

def preserve_single_fat_wrappers(source, stage, app, bundle_id, signer):
    """Undo the signer's wrapper collapse without changing a signed slice."""
    from signature_proof import is_macho, prove, slices
    adjusted = {}
    with zipfile.ZipFile(source) as archive:
        for row in archive.infolist():
            path = stage / row.filename
            if not path.is_relative_to(app) or not path.is_file() or path.is_symlink() or row.file_size < 4:
                continue
            with archive.open(row) as original_stream, path.open('rb') as signed_stream:
                original_magic, signed_magic = original_stream.read(4), signed_stream.read(4)
            if original_magic not in (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf') or signed_magic==original_magic:
                continue
            original, signed = archive.read(row), path.read_bytes()
            old_slices, new_slices = slices(original), slices(signed)
            if len(old_slices)!=1 or len(new_slices)!=1 or new_slices[0][0] is not None or not is_macho(signed):
                raise ValueError(f'Unexpected signer change to FAT layout: {row.filename}')
            old_identity, old_offset, old_slice = old_slices[0]
            if old_offset+len(old_slice)!=len(original):
                raise ValueError(f'Original FAT wrapper has data after its last slice: {row.filename}')
            prefix = bytearray(original[:old_offset])
            if original_magic==b'\xca\xfe\xba\xbf':
                struct.pack_into('>Q',prefix,24,len(signed))
            else:
                struct.pack_into('>I',prefix,20,len(signed))
            restored=bytes(prefix)+signed
            if slices(restored)[0][0]!=old_identity or slices(restored)[0][2]!=signed:
                raise ValueError(f'Signed FAT payload did not round-trip: {row.filename}')
            prove(original,restored,added_host=False)
            path.write_bytes(restored)
            adjusted[path.relative_to(app).as_posix()]=restored
    if adjusted:
        info, executable=bundle_exec(app)
        resources=app/'_CodeSignature/CodeResources'
        envelope=plistlib.loads(resources.read_bytes())
        for name, raw in adjusted.items():
            if name not in envelope['files'] or name not in envelope['files2']:
                raise ValueError(f'FAT wrapper resource is missing from the top app envelope: {name}')
            if not isinstance(envelope['files'][name],bytes) or not set(envelope['files2'][name]) <= {'hash','hash2'}:
                raise ValueError(f'Unexpected FAT resource envelope representation: {name}')
            envelope['files'][name]=hashlib.sha1(raw).digest()
            for key, algo in (('hash','sha1'),('hash2','sha256')):
                if key in envelope['files2'][name]:
                    envelope['files2'][name][key]=hashlib.new(algo,raw).digest()
        resources.write_bytes(plistlib.dumps(envelope,fmt=plistlib.FMT_XML,sort_keys=False))
        subprocess.run([str(signer),'sign','-C','/dev/null',
                        '--binary-identifier',bundle_id,'--info-plist-file',str(info),
                        '--code-resources-file',str(resources),str(executable)],check=True)
    return sorted(adjusted)

def package(repo, source, compile_dir, work, output, version, signer):
    repo, source, compile_dir, work, output, signer = map(
        lambda path: Path(path).resolve(), (repo, source, compile_dir, work, output, signer)
    )
    sys.path.insert(0,str(repo/'ios/build'))
    import build_standalone_mv as official
    from common import macho,require,sha256,verify_file,write_json
    from package_ipa import archive_stage,extract_original,zip_inventory
    require(not work.exists() and not output.exists() and not work.is_relative_to(repo) and not output.is_relative_to(repo),
            'Fresh paths outside source are required')
    require(sha256(signer)==SIGNER_SHA256,'Unexpected Linux signer bytes')
    lock=json.loads((repo/'ios/build/inputs.lock.json').read_text()); pin=lock['game']
    verify_file(source,pin)
    compile_proof=json.loads((compile_dir/'compile-proof.json').read_text())
    for key in ('source_sha256','project_dependencies_sha256'):
        for rel,digest in compile_proof[key].items(): require(sha256(safe_member(repo,rel))==digest,'Sources changed after compile: '+rel)
    dylib=compile_dir/official.LIBRARY
    require(sha256(dylib)==compile_proof['dylib_sha256'],'Compiled dylib differs')
    require(macho(dylib,platform=2,kind=6)['install_name']==official.LOAD,'Unexpected native library install_name')
    original_main=pin['app']+pin['executable']
    with zipfile.ZipFile(source) as archive:
        zip_inventory(archive,pin)
        patched,patch_proof=official.patched_main(archive.read(original_main),pin)
        info=official.standalone_info(plistlib.loads(archive.read(pin['app']+'Info.plist')),version)
        require(info['CFBundleIdentifier']==pin['bundle_id'] and info['CFBundleShortVersionString']==pin['preserve_game_short_version'],
                'Original game identity or protocol version differs')
        require(hashlib.sha256(archive.read(pin['app']+'Frameworks/SIFASFeatures.dylib')).hexdigest()==pin['feature_sha256'],
                'Original features library differs')
    stage=work/'stage'; stage.mkdir(parents=True); extract_original(source,stage,pin)
    app=stage/pin['app']; (stage/original_main).write_bytes(patched)
    inserted=app/'Frameworks'/official.LIBRARY
    require(not inserted.exists(),'Original already contains the MV export library')
    shutil.copy2(dylib,inserted)
    (app/'Info.plist').write_bytes(plistlib.dumps(info,fmt=plistlib.FMT_BINARY,sort_keys=False))
    command=[str(signer),'sign','-C','/dev/null',str(app)]
    with (work/'signer.log').open('w') as log: subprocess.run(command,check=True,stdout=log,stderr=subprocess.STDOUT)
    wrappers=preserve_single_fat_wrappers(source,stage,app,pin['bundle_id'],signer)
    signature=verify_signed_app(app)
    preservation=official.preservation(source,stage,pin,info,patched)
    require(original_main in preservation['MachO_signing_only_or_exact_main_patch_proofs'],'Main executable preservation missing')
    archive_stage(stage,source,output)
    with zipfile.ZipFile(output) as archive:
        require(archive.testzip() is None and archive.read(original_main)==(stage/original_main).read_bytes(),
                'Packaged signed main or ZIP CRC differs')
        require(archive.read(pin['app']+f'Frameworks/{official.LIBRARY}')==inserted.read_bytes(),'Packaged MV export dylib differs')
        entries=archive.infolist()
        for row in entries:
            stage_file=safe_member(stage,row.filename)
            if row.is_dir():
                require(stage_file.is_dir(),'Packaged directory differs: '+row.filename)
            elif stage_file.is_symlink():
                require(archive.read(row)==os.readlink(stage_file).encode(),'Packaged symlink differs: '+row.filename)
            else:
                with archive.open(row) as stream:
                    require(hashlib.file_digest(stream,'sha256').hexdigest()==sha256(stage_file),'Packaged member differs: '+row.filename)
    verify_file(source,pin)
    digest=sha256(output)
    report=dict(status='LINUX_CROSS_BUILD_ADHOC_PLAYCOVER_RUNTIME_UNTESTED',build=info['SIFASBuildVersion'],original=pin,
         source_commit=compile_proof['source_commit'],compile=compile_proof,patch=patch_proof,
         signature=signature,preservation=preservation,signer=str(signer),signer_sha256=SIGNER_SHA256,
         restored_original_fat_wrappers=wrappers,
         exact_zip_members_verified=len(entries),
         native_apple_codesign_strict_deep_verified=False,PlayCover_gameplay_tested=False,
         output={'name':output.name,'bytes':output.stat().st_size,'sha256':digest})
    write_json(work/'package-proof.json',report)
    print(f'{digest}  {output}')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for option in ('repo','source','compile-dir','work','output'): parser.add_argument('--'+option,required=True,type=Path)
    parser.add_argument('--version',required=True)
    parser.add_argument('--signer', required=True, type=Path, help='Pinned rcodesign 0.29.0 Linux x86_64 musl executable')
    package(**vars(parser.parse_args()))

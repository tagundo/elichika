"""Derive an explicitly unvalidated QA app by changing one PCM helper resource."""
import argparse,hashlib,json,os,pathlib,shutil,stat,struct,subprocess,zipfile

def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def inventory(root):
 result={}
 for p in [root,*sorted(root.rglob('*'))]:
  name='.' if p==root else str(p.relative_to(root))
  if p.is_symlink():result[name]={'link':os.readlink(p)}
  elif p.is_dir():result[name]={'directory':True,'mode':stat.S_IMODE(p.stat().st_mode)}
  elif p.is_file():result[name]={'bytes':p.stat().st_size,'sha256':sha(p),'mode':stat.S_IMODE(p.stat().st_mode)}
  else:raise RuntimeError('Unexpected bundle node type')
 return result

def macho_identity(path):
 data=path.read_bytes();assert struct.unpack_from('<I',data)[0]==0xfeedfacf
 cpu,_,_,ncmds,cmdbytes=struct.unpack_from('<5I',data,4);assert cpu==0x100000c and ncmds<2048 and 32+cmdbytes<=len(data)
 normalized=bytearray(data);offset=32;signature=None;sections=[];uuid=None
 for _ in range(ncmds):
  cmd,size=struct.unpack_from('<II',data,offset);assert size>=8 and offset+size<=32+cmdbytes
  if cmd==0x1d:
   assert signature is None;signature=struct.unpack_from('<II',data,offset+8);normalized[offset+8:offset+16]=b'\0'*8
  elif cmd==0x1b:uuid=data[offset+8:offset+24].hex()
  elif cmd==0x19:
   segment=data[offset+8:offset+24].split(b'\0')[0].decode();count=struct.unpack_from('<I',data,offset+64)[0];assert 72+80*count<=size
   if segment=='__LINKEDIT':
    normalized[offset+32:offset+40]=b'\0'*8;normalized[offset+48:offset+56]=b'\0'*8
   for index in range(count):
    entry=offset+72+80*index;name=data[entry:entry+16].split(b'\0')[0].decode();length=struct.unpack_from('<Q',data,entry+40)[0];start=struct.unpack_from('<I',data,entry+48)[0];flags=struct.unpack_from('<I',data,entry+64)[0];zero=(flags&0xff) in (1,12,18)
    assert zero or start+length<=len(data)
    sections.append({'segment':segment,'section':name,'bytes':length,'flags':flags,'zero_fill':zero,'sha256':None if zero else hashlib.sha256(data[start:start+length]).hexdigest()})
  offset+=size
 assert offset==32+cmdbytes and signature and uuid
 start,length=signature;assert start>=offset and start+length<=len(data) and not any(data[start+length:])
 return {'uuid':uuid,'sections':sections,'normalized_pre_signature_sha256':hashlib.sha256(bytes(normalized[:start]).rstrip(b'\0')).hexdigest()}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',type=pathlib.Path,required=True);p.add_argument('--qa',type=pathlib.Path,required=True);p.add_argument('--scratch',type=pathlib.Path,required=True);p.add_argument('--evidence',type=pathlib.Path,required=True);a=p.parse_args()
 manifest=json.loads((a.qa/'proposal-manifest.json').read_text());helper=a.qa/'native_pcm_qa.js'
 assert sha(a.archive)=='5b86c4294bfabca4f894b0c16526b313136552d28cbe24392748642ec7a78330' and a.archive.stat().st_size==305441968
 assert sha(helper)==manifest['diagnostic_delta'][0]['sha256'];a.scratch.mkdir(parents=True,exist_ok=True);a.evidence.mkdir(parents=True,exist_ok=True)
 container=a.scratch/'original-artifact';container.mkdir()
 with zipfile.ZipFile(a.archive) as z:
  assert sum(x.file_size for x in z.infolist())<512*1024*1024
  for x in z.infolist():
   path=pathlib.PurePosixPath(x.filename);assert not path.is_absolute() and '..' not in path.parts and not stat.S_ISLNK(x.external_attr>>16)
  z.extractall(container)
 candidates=list(container.rglob('candidate-manifest.json'));assert len(candidates)==1
 original_manifest=json.loads(candidates[0].read_text());assert original_manifest['status']=='UNVALIDATED_CANDIDATE_NOT_FOR_DELIVERY' and original_manifest['source_commit']=='b503631efee12bdf224ae94962bd1403a4658da3' and str(original_manifest['workflow_run'])=='43428743619'
 packed=candidates[0].parent/original_manifest['name'];assert packed.is_file() and packed.stat().st_size==original_manifest['bytes'] and sha(packed)==original_manifest['sha256']
 original_root=a.scratch/'original-app';original_root.mkdir();subprocess.run(['/usr/bin/ditto','-x','-k',str(packed),str(original_root)],check=True)
 apps=list(original_root.glob('*.app'));assert len(apps)==1;original=apps[0]
 subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(original)],check=True)
 before=inventory(original);old_helper='Contents/Resources/qa/native_pcm_qa.js';binary='Contents/MacOS/Elichika';seal='Contents/_CodeSignature/CodeResources'
 assert before[old_helper]['sha256']==manifest['frozen_inputs']['macos/ci/native_pcm_qa.js']['sha256']
 for name in ['viewer-motion-audio.js','viewer-native-pcm-player.js']:
  path='Contents/Resources/python-app/webtools/web/static/'+name;assert before[path]['sha256']==manifest['frozen_inputs']['modtools/webtools/web/static/'+name]['sha256']
 original_code=macho_identity(original/binary)
 derived=a.scratch/'Elichika-C5-PCM-DIAGNOSTIC-ONLY.app';subprocess.run(['/usr/bin/ditto',str(original),str(derived)],check=True);assert inventory(derived)==before
 for path in [derived,*derived.rglob('*')]:
  if not path.is_symlink():path.chmod(path.stat().st_mode|0o200|(0o100 if path.is_dir() else 0))
 shutil.copyfile(helper,derived/old_helper)
 subprocess.run(['/usr/bin/codesign','--force','--sign','-','--timestamp=none',str(derived)],check=True)
 for path in [*derived.rglob('*'),derived]:
  if not path.is_symlink():path.chmod(path.stat().st_mode&~0o222)
 derived.chmod(0o755);subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(derived)],check=True)
 after=inventory(derived);new_code=macho_identity(derived/binary)
 # Preserve the real inventories/identities before any invariant can fail.
 for name,value in [('original-bundle-inventory.json',before),('derived-bundle-inventory.json',after),('original-code-identity.json',original_code),('derived-code-identity.json',new_code)]:
  (a.evidence/name).write_text(json.dumps(value,indent=2)+'\n')
 assert set(before)==set(after);changed=[name for name in before if before[name]!=after[name]]
 (a.evidence/'derivation-attempt.json').write_text(json.dumps({'status':'PENDING_INVARIANT_CHECKS_DIAGNOSTIC_ONLY','changed_paths':changed,'original_code_identity':original_code,'derived_code_identity':new_code},indent=2)+'\n')
 assert old_helper in changed and seal in changed and set(changed)<={old_helper,binary,seal}
 assert new_code==original_code,'Re-signing changed program bytes outside signature metadata'
 assert inventory(original)==before,'Original C5 app must stay untouched'
 report={'status':'DERIVED_C5_PCM_OBSERVER_ONLY_UNVALIDATED','original_artifact':14038842268,'original_workflow':43428743619,'original_source_commit':original_manifest['source_commit'],'original_artifact_zip_sha256':sha(a.archive),'original_archive':original_manifest,'derived_app':str(derived),'qa_helper_sha256':sha(helper),'changed_paths':{name:{'before':before[name],'after':after[name]} for name in changed},'all_other_file_bytes_links_modes_unchanged':True,'signature_normalized_program_identity_unchanged':True,'original_app_untouched':True,'product_clock_and_player_unchanged':True,'original_C5_failure_waived':False,'validated_release_artifact':False}
 (a.evidence/'derived-app-provenance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':report['status'],'derived_app':str(derived),'changed_paths':changed},indent=2))

if __name__=='__main__':main()

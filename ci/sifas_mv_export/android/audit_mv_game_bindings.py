#!/usr/bin/env python3
"""Read exact b25 ZIP members in bounded windows; emit source/evidence only."""
import hashlib,json,struct,sys,zipfile
from pathlib import Path
sys.path[:0]=['/dev/shm/sifas-client-20261113/mv','/dev/shm/sifas-client-20261113/mv/python']
from metadata import Metadata
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN

ROOT=Path(__file__).resolve().parent
TASK=ROOT.parent.parent/'android-elf-audit'
SOURCES={
 'GL':{'apk':'/dev/shm/sifas-android-material-b25-GL-20261115/LLAS_GL_FOVMOD_b25.apk',
       'sha256':'157f92a46fcaefaca52c2c8209b35e059773be62fc74a8c8e20c2ac3f9dea738',
       'native_sha256':'39e7af6865c71debdfd696e22a8aa4332ee994e936ecef100d7e4d51364f8f0a',
       'metadata_sha256':'c1ac82ff0b68351ffb3a58fce275b940c26316da64cdfc8201413382afdec14f',
       'table':0x6d4abd0},
 'JP':{'apk':'/dev/shm/sifas-android-material-b25-JP-20261115/LLAS_JP_FOVMOD_b25.apk',
       'sha256':'488d727001bbc125fc1c16f83f6bd29482384359b9bee0c22e7c6f7664742220',
       'native_sha256':'6be5676373f48057bafa7cf431cbdbe07d682d5065ebb1a01e7b7ffa5956ba2d',
       'metadata_sha256':'fcdafff9955f526ea7ece0572dc9a26666fa6d382a7cac167c5afb8da1fc86d7',
       'table':0x6d3e428}}
HOOKS=[('liveUpdate','LiveDirectorBase','Update',0),
       ('musicUpdate','LiveMusicMachine','Update',0),
       ('memberUpdate','LiveCoreMemberManager','Update',0),
       ('memberLateUpdate','LiveCoreMemberManager','LateUpdate',0),
       ('overlayRender','LiveCoreOverlayCamera','OnRenderImage',2),
       ('screenWidth','Screen','get_width',0),('screenHeight','Screen','get_height',0),
       ('postRender','Camera','FireOnPostRender',1)]
PATTERN=r'(LiveDirectorBase|LiveTimeSynchronizer|LiveMusicMachine|LiveCoreCameraManager|LiveCoreOverlayCamera|LiveCoreMemberManager|SwingBone|SwingBoneManager|JobHandle|Screen|Camera|Texture2D|RenderTexture|Graphics|PlayableDirector|Transform|TransformCache)$'
def digest_file(p):
 with open(p,'rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def digest_stream(f):
 f.seek(0);h=hashlib.sha256()
 while b:=f.read(1024*1024):h.update(b)
 return h.hexdigest()
def headers(f):
 f.seek(0);h=struct.unpack('<16sHHIQQQIHHHHHH',f.read(64))
 assert h[0][:7]==b'\x7fELF\x02\x01\x01' and h[2]==183 and h[9]==56
 f.seek(h[5]);return [struct.unpack('<IIQQQQQQ',f.read(56))for _ in range(h[10])]
def readva(f,ph,va,n):
 offsets=[p[2]+va-p[3]for p in ph if p[0]==1 and p[3]<=va and va+n<=p[3]+p[5]]
 assert len(offsets)==1,(hex(va),n)
 f.seek(offsets[0]);b=f.read(n);assert len(b)==n;return b
def main():
 cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
 for region,row in SOURCES.items():
  assert digest_file(row['apk'])==row['sha256']
  mp=Path('/dev/shm/sifas-client-20261113/android')/(region+'-b21/assets/bin/Data/Managed/Metadata/global-metadata.dat')
  assert digest_file(mp)==row['metadata_sha256'];m=Metadata(str(mp))
  classes=list(m.select(PATTERN))
  high=max(m.method(i)['methodindex']for i in range(m.h[13]//52))
  with zipfile.ZipFile(row['apk'])as z,z.open('lib/arm64-v8a/libil2cpp.so')as f:
   assert digest_stream(f)==row['native_sha256'];ph=headers(f)
   table=readva(f,ph,row['table'],(high+1)*8)
   pointers=sorted(set(x[0]for x in struct.iter_unpack('<Q',table)if x[0]))
   methods=[];hooks=[]
   for c in classes:
    for method in c['methods']:
     if method['methodindex']<0:continue
     va=struct.unpack_from('<Q',table,method['methodindex']*8)[0]
     if not va:continue
     raw=readva(f,ph,va,64)
     entry={'namespace':c['namespace'],'class':c['name'],'name':method['name'],
            'parameters':method['params'],'token':method['token'],'flags':method['flags'],
            'rva':va,'first64hex':raw.hex(),'first64sha256':hashlib.sha256(raw).hexdigest()}
     for key,cn,mn,count in HOOKS:
      if c['name']==cn and method['name']==mn and method['params']==count:
       entry['hook_key']=key;first=next(cs.disasm(raw[:4],va));word=struct.unpack_from('<I',raw)[0]
       if first.mnemonic=='b':
        delta=word&0x3ffffff;delta=delta-(1<<26)if delta&(1<<25)else delta
        entry['relocation']={'kind':'tail_branch','target':va+delta*4}
       else:
        assert first.mnemonic in ('str','stp','sub','mov'),(region,key,first.mnemonic,first.op_str)
        assert not any(s in first.op_str for s in ['pc','#0x100000000'])
        entry['relocation']={'kind':'copy_non_pc_relative_first_instruction','word':word}
       hooks.append(dict(entry))
     methods.append(entry)
   assert len(hooks)==len(HOOKS)
   names={e['rva']:e['class']+'.'+e['name']for e in methods}
   listings=[]
   audit_names={'LiveCoreMemberManager','LiveCoreCameraManager','LiveCoreOverlayCamera','LiveDirectorBase','SwingBoneManager'}
   for e in methods:
    if e['class']not in audit_names:continue
    # Bounded whole-method ranges establish final composite and spring ordering.
    import bisect
    va=e['rva'];end=pointers[bisect.bisect_right(pointers,va)]
    if end-va>32768:continue
    raw=readva(f,ph,va,end-va)
    listings.append('\n'+e['class']+'.'+e['name']+' '+hex(va)+'..'+hex(end))
    for ins in cs.disasm(raw,va):
     target=int(ins.op_str[1:],0)if ins.mnemonic in('b','bl')and ins.op_str.startswith('#')else 0
     listings.append(f'{ins.address:x} {ins.bytes.hex()} {ins.mnemonic} {ins.op_str} ; {names.get(target,"")}')
   (TASK/(region+'-mv-adapter-disassembly.txt')).write_text('\n'.join(listings)+'\n')
   profile={'schema':1,'status':'VERIFIED_B25_SOURCE_PROFILE_NOT_PATCHED_OR_RUNTIME_PROVEN',
     'region':region,'apk_sha256':row['sha256'],'native_sha256':row['native_sha256'],
     'native_bytes':z.getinfo('lib/arm64-v8a/libil2cpp.so').file_size,
     'metadata_sha256':row['metadata_sha256'],'method_pointer_table_rva':row['table'],
     'hooks':hooks,'classes':classes,'methods':methods}
   # Frozen build profiles additionally contain independently reviewed native
   # TimeManager and POST dispatch proofs. Never overwrite them on re-audit.
   (ROOT/('android_mv_source_audit_'+region+'.json')).write_text(json.dumps(profile,indent=2)+'\n')
   print(region,[(h['hook_key'],hex(h['rva']),h['first64hex'][:8],h['relocation'])for h in hooks])
  m.close()
if __name__=='__main__':main()

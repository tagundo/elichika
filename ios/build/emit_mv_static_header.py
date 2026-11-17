#!/usr/bin/env python3
"""Emit typed native calls from the exact, reviewed GL metadata profile."""
import hashlib,json,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=root/'native/SIFASMVStaticProfile.json';d=json.loads(p.read_text());assert not d['missing']
classes=d['classes']; names={n:'class_'+str(i) for i,n in enumerate(sorted(classes))}
scalar={'System.Void':('void',0),'System.Boolean':('uint8_t',1),'System.Int32':('int32_t',4),'System.UInt32':('uint32_t',4),'System.Int64':('int64_t',8),'System.UInt64':('uint64_t',8),'System.IntPtr':('uintptr_t',8),'System.Single':('float',4),'System.Double':('double',8),'UnityEngine.Vector3':('Vec3',12),'UnityEngine.Quaternion':('Quat',16),'UnityEngine.Rect':('Rect',16),'UnityEngine.Rendering.RenderTargetIdentifier':('RenderTargetIdentifier',40),'LLAS.MBus.Live.PauseMessage':('PauseMessage',1)}
# All enum types here have verified Int32 backing fields in the game metadata.
enums={'UnityEngine.CameraClearFlags','UnityEngine.Playables.PlayState','UnityEngine.Playables.DirectorUpdateMode','UnityEngine.RenderTextureFormat','UnityEngine.RenderTextureReadWrite','UnityEngine.Rendering.BuiltinRenderTextureType','UnityEngine.Rendering.CameraEvent','UnityEngine.TextureFormat'}
def cpp(t):
 if t.endswith('&'):return 'void *',8
 if t in scalar:return scalar[t]
 if t in enums:return 'int32_t',4
 return 'void *',8
out=['// Generated; exact profile SHA256 '+hashlib.sha256(p.read_bytes()).hexdigest(), 'struct PauseMessage { uint8_t waiting; };']
for name in sorted(classes):
 row=classes[name];vt=row['parent'] in ('System.ValueType','System.Enum') or row['value_size'] is not None
 out.append('static const StaticClass %s={%s,%sULL,%s};'%(names[name],json.dumps(name),row['raw_type_va'],str(vt).lower()))
for key,row in d['methods'].items():
 ident=re.sub('[^a-zA-Z0-9_]','_',key);ret,size=cpp(row['return_type']);args=[];values=[]
 if not row['is_static']:args.append('void *');values.append('self')
 for i,t in enumerate(row['parameter_types']):
  typ,_=cpp(t);args.append(typ)
  values.append('args[%d]'%i if typ=='void *' else '*reinterpret_cast<%s *>(args[%d])'%(typ,i))
 args.append('const void *');info='nullptr'
 if 'method_info_cell_va' in row:info='*reinterpret_cast<const void **>(%sULL+slide)'%row['method_info_cell_va']
 values.append(info)
 call='native<%s (*)(%s)>(%sULL)(%s)'%(ret,','.join(args),row['va'],','.join(values))
 body=call+';' if ret=='void' else '*reinterpret_cast<%s *>(result)=%s;'%(ret,call)
 out.append('static void call_%s([[maybe_unused]] void *self,[[maybe_unused]] void **args,[[maybe_unused]] void *result) { %s }'%(ident,body))
# Closed generic MethodInfo cells are populated by the engine's own metadata
# initializer, using the original usage lists referenced by game code.
out+=['static bool preparePauseMethods(void *bus) {','    if(bus!=pause_bus||!pause_bus_root||e.gchandle_get_target(pause_bus_root)!=bus)return false;']
for key in ('pause_broadcast','pause_dispatch'):
 row=d['methods'][key];out.append('    native<void (*)(uint32_t)>(%sULL)(%du);'%(d['native']['initialize_metadata']['va'],row['method_info_usage_lists'][0]))
 out.append('    if(!*reinterpret_cast<const void **>(%sULL+slide))return false;'%row['method_info_cell_va'])
out+=['    return true;','}']
for key in ('list_items','list_size'):
 row=d['fields'][key];out.append('static const Field %s={%d,&%s,%d};'%(key,row['offset'],names[row['ownerFullName']],row['size']))
out+=['static bool loadStaticProfile() {']
# Profile bootstrap has already verified the exact executable UUID and all nine
# branch/trampoline preimages. Verify all further direct native call preimages.
for key,row in list(d['methods'].items())+list(d['native'].items()):
 b=bytes.fromhex(row['first32hex']);skip=4 if key.startswith('hook[') else 0
 out.append('    { static const uint8_t expected[]={%s};if(std::memcmp(reinterpret_cast<const void *>(%sULL+slide+%d),expected,sizeof(expected)))return false; }'%(','.join(hex(x) for x in b[skip:]),row['va'],skip))
for key,row in d['methods'].items():
 ident=re.sub('[^a-zA-Z0-9_]','_',key);ret,size=cpp(row['return_type']);ref=ret=='void *';size=0 if ret=='void' else size
 out.append('    m.%s={%s,&%s,%d,%s,%s,&call_%s};'%(key,json.dumps(row['method_name']),names[row['ownerFullName']],size,str(ref).lower(),str(row['is_static']).lower(),ident))
for key,row in d['fields'].items():
 if key.startswith('list_'):continue
 out.append('    f.%s={%d,&%s,%d};'%(key,row['offset'],names[row['ownerFullName']],row['size']))
out+=['    return f.bone_array.offset==0x30 && f.collider_array.offset==0x50 && f.jobs_a.offset==0xa8 && f.jobs_b.offset==0xb0 && f.scalar_first.offset==0xb0 && f.scalar_end.offset==0x110 && list_items.offset==16 && list_size.offset==24;','}']
(root/'native/SIFASMVStaticBindings.hpp').write_text('\n'.join(out)+'\n')
print('Emitted',len(d['methods']),'typed methods;',len(d['fields']),'fields')

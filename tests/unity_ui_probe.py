"""Read a running client's Unity UI hierarchy, without changing game state."""
import argparse
import json
from pathlib import Path
import subprocess
import frida

p=argparse.ArgumentParser()
p.add_argument('--output',type=Path,required=True)
p.add_argument('--raycast',type=float,nargs=2)
args=p.parse_args()
subprocess.run(['adb','-s','127.0.0.1:5555','forward','tcp:27042','tcp:27042'],check=True,capture_output=True)
pid=int(subprocess.check_output(['adb','-s','127.0.0.1:5555','shell','pidof','com.klab.lovelive.allstars.global']).split()[0])
device=frida.get_device_manager().add_remote_device('127.0.0.1:27042')
session=device.attach(pid)
messages=[]
try:
    source=Path('qa-runtime/node_modules/frida-il2cpp-bridge/dist/index.js').read_text()+'\n'+Path('tests/unity-ui.js').read_text()
    script=session.create_script(source)
    script.on('message',lambda message,data:messages.append(message))
    script.load()
    result=script.exports_sync.tree()
    if args.raycast:
        result['pointer_raycast']=script.exports_sync.raycast(*args.raycast)
    result['probe_messages']=messages
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'unity':result.get('unity'),'width':result.get('width'),'height':result.get('height'),
                     'node_count':len(result.get('nodes',[])),'errors':result.get('errors',[]),
                     'controls':[n for n in result.get('nodes',[]) if n.get('button') or n.get('text')][:45]},ensure_ascii=False),flush=True)
finally:
    session.detach()

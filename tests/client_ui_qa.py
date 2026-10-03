"""Drive an unchanged SIFAS client on disposable Android; capture real UI evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET

from android_release_smoke import Android, PACKAGE

CLIENT = 'com.klab.lovelive.allstars.global'
SERVER_SHA = '23df494e132db7f3537851b11424bbe2903082e756e0798a7bf7ea022ba1ba2a'
CLIENT_SHA = '8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e'


class Device(Android):
    def capture(self, label):
        for name,args in [('screen.png',('exec-out','screencap','-p')),
                          ('logcat.txt',('logcat','-d')),
                          ('crash.txt',('logcat','-b','crash','-d')),
                          ('activity.txt',('shell','dumpsys','activity','activities'))]:
            try:
                self.evidence.joinpath(label+'-'+name).write_bytes(self.adb(*args,raw=True))
            except Exception as e:
                self.evidence.joinpath(label+'-'+name+'.error').write_text(str(e))
        try:
            self.shell('uiautomator','dump','/sdcard/client-qa.xml',timeout=60)
            data=self.read('/sdcard/client-qa.xml')
            self.evidence.joinpath(label+'-ui.xml').write_bytes(data)
            tree=ET.fromstring(data)
            nodes=[{k:n.get(k) for k in ['text','content-desc','resource-id','class','bounds','clickable','scrollable']} for n in tree.iter('node')]
            self.evidence.joinpath(label+'-ui.json').write_text(json.dumps(nodes,indent=2,ensure_ascii=False)+'\n')
            print('UI_CAPTURE '+label+' '+json.dumps(nodes[:35],ensure_ascii=False),flush=True)
        except Exception as e:
            self.evidence.joinpath(label+'-ui.error').write_text(str(e))
        try:
            self.evidence.joinpath(label+'-server.txt').write_bytes(self.read('/sdcard/Download/sukusta/logs/elichika.log'))
        except Exception:
            pass

    def tap_node(self, action):
        self.shell('uiautomator','dump','/sdcard/client-qa.xml',timeout=60)
        data=self.read('/sdcard/client-qa.xml')
        tree=ET.fromstring(data)
        matches=[]
        for node in tree.iter('node'):
            if all(node.get(k)==v for k,v in action.get('selector',{}).items()):
                matches.append(node)
        assert action.get('selector') and matches, 'No matching UI-tree target'
        node=matches[action.get('index',0)]
        x1,y1,x2,y2=map(int,re.findall(r'\d+',node.get('bounds','')))
        assert x2>x1 and y2>y1
        self.shell('input','tap',str((x1+x2)//2),str((y1+y2)//2))
        return {'selector':action['selector'],'bounds':node.get('bounds')}


def fetch_commands():
    url='https://api.github.com/repos/tagundo/elichika/contents/qa/client-actions.json?ref=codex/original-client-ui-qa'
    req=urllib.request.Request(url,headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],
                                          'Accept':'application/vnd.github.raw+json'})
    with urllib.request.urlopen(req,timeout=20) as response:
        return json.loads(response.read())


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--stage',choices=['initial','control'],required=True)
    p.add_argument('--round',type=int,default=0)
    p.add_argument('--duration',type=int,default=180)
    p.add_argument('--server',type=Path)
    p.add_argument('--client',type=Path)
    p.add_argument('--evidence',type=Path,default=Path('evidence'))
    args=p.parse_args();args.evidence.mkdir(exist_ok=True)
    dev=Device('127.0.0.1:5555',args.evidence)
    state_path=args.evidence/'client-ui-state.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {'status':'RUNNING','actions':[],
        'server_apk_sha256':SERVER_SHA,'client_apk_sha256':CLIENT_SHA,
        'limits':['Disposable rooted Android virtual device; not a physical phone',
                  '4KB results do not establish full Android16KB compatibility',
                  'Unity accessibility may not expose individual game controls']}
    try:
        if args.stage=='initial':
            assert hashlib.sha256(args.server.read_bytes()).hexdigest()==SERVER_SHA
            assert hashlib.sha256(args.client.read_bytes()).hexdigest()==CLIENT_SHA
            state['environment']={k:dev.shell(*v) for k,v in {
              'android':('getprop','ro.build.version.release'),'api':('getprop','ro.build.version.sdk'),
              'abi':('getprop','ro.product.cpu.abi'),'model':('getprop','ro.product.model'),
              'pagesize':('getconf','PAGESIZE'),'selinux':('getenforce')}.items()}
            assert state['environment']['pagesize']=='4096'
            dev.adb('logcat','-c')
            state['server_install']=dev.install(args.server,2026100100)
            state['server_start']=dev.start('server-start')
            output=dev.adb('install','-r',str(args.client),timeout=300)
            assert 'Success' in output
            state['client_install']=output
            resolved=dev.shell('cmd','package','resolve-activity','--brief',CLIENT).splitlines()[-1]
            assert '/' in resolved,resolved
            state['client_activity']=resolved
            state['client_launch']=dev.shell('am','start','-W','-n',resolved)
            for seconds in [5,20,45]:
                time.sleep(seconds)
                dev.capture('initial-'+str(seconds))
            state['client_pid']=dev.shell('pidof',CLIENT)
            state['status']='CLIENT_LAUNCHED_AWAITING_UI_VALIDATION'
        else:
            done={a['id'] for a in state['actions']}
            deadline=time.monotonic()+args.duration
            count=0
            while time.monotonic()<deadline:
                commands=fetch_commands()
                for action in commands.get('actions',[]):
                    if action['id'] in done:continue
                    record={'id':action['id'],'type':action['type']}
                    try:
                        if action['type']=='tap':record.update(dev.tap_node(action))
                        elif action['type']=='key':
                            assert action['keycode'] in [4,66,82]
                            dev.shell('input','keyevent',str(action['keycode']))
                        elif action['type']=='capture':pass
                        elif action['type']=='launch':dev.shell('am','start','-W','-n',state['client_activity'])
                        elif action['type']=='text':
                            assert re.fullmatch(r'[A-Za-z0-9 ._-]{1,40}',action['text'])
                            dev.shell('input','text',action['text'].replace(' ','%s'))
                        elif action['type']=='stop':
                            state['status']='CONTROL_COMPLETED';state_path.write_text(json.dumps(state,indent=2)+'\n');return
                        else:raise ValueError('Unsupported action: '+action['type'])
                        time.sleep(min(action.get('wait',10),60))
                        record['result']='EXECUTED'
                    except Exception as e:record.update(result='FAILED',error=str(e))
                    dev.capture('action-'+action['id'])
                    state['actions'].append(record);done.add(action['id'])
                    state_path.write_text(json.dumps(state,indent=2)+'\n')
                if count%6==0:dev.capture('round-'+str(args.round)+'-'+str(count))
                count+=1;time.sleep(10)
            dev.capture('round-'+str(args.round)+'-final')
    except Exception as e:
        state.update(status='SETUP_OR_EXECUTION_FAILED',error=str(e))
        dev.capture('failure')
        raise
    finally:
        state_path.write_text(json.dumps(state,indent=2,ensure_ascii=False)+'\n')
        print('CLIENT_UI_STATE '+json.dumps(state,ensure_ascii=False),flush=True)


if __name__=='__main__':main()

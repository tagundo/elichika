"""Test original signed APK screens on a disposable full 16KB Android emulator."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import traceback
import urllib.request
import xml.etree.ElementTree as ET

from android_release_smoke import Android, PACKAGE


class ScreenAndroid(Android):
    def adb(self, *args, raw=False, timeout=300, input=None):
        if args and args[0]=='install':timeout=max(timeout,900)
        return super().adb(*args,raw=raw,timeout=timeout,input=input)

    def tree(self, label):
        self.shell('uiautomator','dump','/sdcard/qa16k-window.xml',timeout=180)
        data=self.read('/sdcard/qa16k-window.xml')
        self.evidence.joinpath(label+'.xml').write_bytes(data)
        return ET.fromstring(data)

    def capture(self, label):
        root=self.tree(label)
        self.evidence.joinpath(label+'.png').write_bytes(self.adb('exec-out','screencap','-p',raw=True))
        return root

    def tap(self,node):
        x1,y1,x2,y2=map(int,re.findall(r'\d+',node.get('bounds','')))
        assert x2>x1 and y2>y1, 'UI target has empty bounds'
        self.shell('input','tap',str((x1+x2)//2),str((y1+y2)//2))

    def button(self,label,resource):
        root=self.tree(label)
        nodes=[n for n in root.iter('node') if n.get('resource-id')==resource]
        assert nodes,'Missing UI button: '+resource
        self.tap(nodes[0])

    def start_ui(self,label):
        self.shell('am','start','-W','-n',PACKAGE+'/.MainActivity')
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            root=self.tree(label+'-before-start')
            close=[n for n in root.iter('node') if n.get('resource-id')=='android:id/button1'
                   and n.get('text','').casefold() in ['close','닫기','閉じる']]
            if close:
                self.tap(close[0]);continue
            toggle=[n for n in root.iter('node') if n.get('resource-id')==PACKAGE+':id/btn_toggle']
            if toggle:
                self.capture(label+'-console-stopped')
                self.tap(toggle[0]);break
            time.sleep(2)
        else:raise AssertionError('Start button did not appear')
        start=time.monotonic()
        for local,remote in [(18080,8080),(18770,8770),(18772,8772)]:
            self.adb('forward',f'tcp:{local}',f'tcp:{remote}')
        services={}
        for port,path in [(18080,'/webui/admin/'),(18770,'/'),(18772,'/')]:
            deadline=start+1200
            while time.monotonic()<deadline:
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}',timeout=10) as response:
                        body=response.read()
                        assert response.status==200 and len(body)>100
                    services[str(port)]={'status':200,'bytes':len(body)};break
                except Exception:
                    time.sleep(3)
            else:raise AssertionError(f'Service {port} failed to start')
        root=self.capture(label+'-console-running')
        toggle=next(n for n in root.iter('node') if n.get('resource-id')==PACKAGE+':id/btn_toggle')
        assert 'stop' in toggle.get('text','').casefold(), 'UI does not show running server'
        pids=self.shell('pidof','libelichika.so').split();assert len(pids)==1
        actual=self.shell('sha256sum','/proc/'+pids[0]+'/exe').split()[0]
        assert actual==self.native_sha
        return {'services':services,'running_native_sha256':actual,'ready_seconds':round(time.monotonic()-start,1)}

    def tab(self,title,label):
        root=self.tree(label+'-navigation')
        for attempt in range(3):
            nodes=[n for n in root.iter('node') if n.get('text')==title or n.get('content-desc')==title]
            nodes=[n for n in nodes if len(re.findall(r'\d+',n.get('bounds','')))==4]
            if nodes:
                self.tap(nodes[0]);break
            tabs=next(n for n in root.iter('node') if n.get('resource-id')==PACKAGE+':id/tabs')
            x1,y1,x2,y2=map(int,re.findall(r'\d+',tabs.get('bounds')))
            self.shell('input','swipe',str(x2-(x2-x1)//5),str((y1+y2)//2),
                       str(x1+(x2-x1)//5),str((y1+y2)//2),'400')
            root=self.tree(label+'-navigation-scrolled-'+str(attempt))
        else:raise AssertionError('Tab not found after scrolling: '+title)
        deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            root=self.tree(label)
            views=[n for n in root.iter('node') if n.get('class')=='android.webkit.WebView']
            if views:
                labels=[n.get('text') or n.get('content-desc') for view in views for n in view.iter('node')]
                labels=[t for t in labels if t and len(t.strip())>1]
                assert not any('ERR_' in t or 'Web page not available' in t for t in labels),labels
                if len(labels)>=3:
                    self.capture(label)
                    return {'visible_webview':True,'accessible_content_labels':labels[:40]}
            time.sleep(3)
        self.capture(label+'-failure')
        raise AssertionError('WebView did not expose loaded page content: '+title)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--version-code',type=int,default=2026100100)
    parser.add_argument('--evidence',type=Path,default=Path('evidence'))
    args=parser.parse_args();args.evidence.mkdir(exist_ok=True)
    report={'status':'RUNNING','limits':['Software-emulated official Android 15 image, no physical phone or original SIFAS-client playback',
            'Storage/notification permissions are granted automatically to focus on app screen and native execution'],
            'apk_sha256':hashlib.sha256(args.candidate.read_bytes()).hexdigest()}
    assert report['apk_sha256']==args.sha256
    device=ScreenAndroid('emulator-5554',args.evidence)
    try:
        page=device.shell('getconf','PAGE_SIZE');assert page=='16384'
        report['environment']={'page_size':int(page),'android':device.shell('getprop','ro.build.version.release'),
          'api':device.shell('getprop','ro.build.version.sdk'),'abi':device.shell('getprop','ro.product.cpu.abi'),
          'kernel':device.shell('uname','-a'),'selinux':device.shell('getenforce')}
        assert report['environment']['abi']=='arm64-v8a'
        device.adb('logcat','-c')
        report['installed']=device.install(args.candidate,args.version_code)
        report['initial_start']=device.start_ui('initial')
        report['screens']={}
        for title,label in [('Server','server-settings'),('Account','account'),
                            ('Server content','python-dev-tools'),('Asset editing','python-mod-tools')]:
            report['screens'][label]=device.tab(title,label)
        device.button('stop-server',PACKAGE+':id/btn_toggle')
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            result=subprocess.run(['adb','-s',device.serial,'shell','pidof','libelichika.so'],capture_output=True,text=True,timeout=20)
            if not result.stdout.strip():break
            time.sleep(2)
        else:raise AssertionError('Server did not stop through UI')
        device.capture('server-stopped')
        device.stop()
        report['restart']=device.start_ui('restart')
        assert device.shell('getconf','PAGE_SIZE')=='16384'
        report['status']='PASS'
        print('FULL_ANDROID_16K_SCREEN_REPORT='+json.dumps(report),flush=True)
    except Exception as error:
        report.update({'status':'FAIL','error':str(error),'traceback':traceback.format_exc()})
        raise
    finally:
        (args.evidence/'android-full-16k-screens.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()

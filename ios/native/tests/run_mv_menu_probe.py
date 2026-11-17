#!/usr/bin/env python3
"""One owned iPhone Simulator; actual standalone menu/UI, test-only game bindings.

No unified build, PlayCover execution, game rendering, audio or MP4 claim.
Every setup/boot/launch failure fails the probe; there is no successful skip.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import time
import uuid


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve()
    if out.exists():
        raise SystemExit('Fresh menu-probe output directory required')
    out.mkdir(parents=True)
    receipt={'schema':1,'status':'FAIL_UIKIT_STANDALONE_MENU_REGRESSION','actual_playcover':False,
             'actual_game_rendering':False,'mp4_encoding':False,'commands':[]}
    deadline=time.monotonic()+300
    device=None; failed=False

    def run(stage,command,budget=30):
        timeout=min(budget,max(0.1,deadline-time.monotonic()))
        row={'stage':stage,'command':[str(x) for x in command]}; receipt['commands'].append(row)
        try:
            result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout)
            row.update(returncode=result.returncode,output=result.stdout[-16384:])
        except subprocess.TimeoutExpired:
            row['timed_out']=True; raise RuntimeError(stage+' timed out')
        if result.returncode:
            raise RuntimeError(stage+' failed: '+result.stdout[-3000:])
        return result.stdout.strip()

    try:
        host=platform.machine()
        if platform.system()!='Darwin' or host not in ('arm64','aarch64','x86_64'):
            raise RuntimeError('This required probe needs macOS and Xcode; no runtime result was produced')
        architecture='arm64' if host in ('arm64','aarch64') else 'x86_64'
        receipt['simulator_architecture']=architecture
        native=Path(__file__).resolve().parents[1]
        android=native.parents[1]/'ci/sifas_mv_export/android'
        sdk=run('sdk',['xcrun','--sdk','iphonesimulator','--show-sdk-path'],15)
        cc=run('compiler',['xcrun','--sdk','iphonesimulator','--find','clang'],15)
        cxx=run('compiler++',['xcrun','--sdk','iphonesimulator','--find','clang++'],15)
        app=out/'MVMenuProbe.app'; app.mkdir()
        bundle='app.sifas.mv-menu-probe'
        (app/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':bundle,'CFBundleExecutable':'MVMenuProbe',
            'CFBundleName':'MVMenuProbe','CFBundlePackageType':'APPL','CFBundleVersion':'1','CFBundleShortVersionString':'1.0',
            'MinimumOSVersion':'13.0','LSRequiresIPhoneOS':True,'UIDeviceFamily':[1],'UILaunchScreen':{}}))
        common=['-target',architecture+'-apple-ios13.0-simulator','-isysroot',sdk,'-O1']
        codec=android/'mv_audio_codec/clhca.c'; codec_object=out/'clhca.o'
        run('compile-clhca',[cc,*common,'-c',str(codec),'-o',str(codec_object)],60)
        sources=[native/name for name in ('SIFASMVStandaloneMenu.mm','SIFASMVExportSession.mm',
                 'SIFASMVStandaloneAdapter.mm','ElichikaMVEncoder.mm','tests/MVMenuProbe.mm')]
        closure=sources+[codec,native/'SIFASMVExportSession.h',native/'SIFASMVExportBindings.h',
                 native/'SIFASMVStandaloneAdapter.h',native/'ElichikaMVEncoder.h',native/'MVExportClock.hpp',
                 android/'android_mv_audio_provider.cpp',android/'android_mv_audio_provider.h',
                 android/'mv_audio_codec/clhca.h',android/'mv_audio_codec/clhca_data.h']
        receipt['source_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in closure}
        command=[cxx,*common,'-std=c++17','-fobjc-arc','-fblocks','-DSIFAS_STANDALONE=1',
                 '-Wno-deprecated-declarations','-Wno-nullability-completeness','-I',str(native),
                 *map(str,sources),str(codec_object)]
        for framework in ('Foundation','UIKit','CoreGraphics','AVFoundation','CoreMedia','CoreVideo','AudioToolbox','VideoToolbox'):
            command+=['-framework',framework]
        run('compile-menu-probe',command+['-o',str(app/'MVMenuProbe')],120)
        run('adhoc-sign',['codesign','--force','--sign','-','--timestamp=none',str(app)],30)
        runtimes=json.loads(run('runtimes',['xcrun','simctl','list','runtimes','--json']))['runtimes']
        candidates=[r for r in runtimes if r.get('isAvailable') and '.iOS-' in r['identifier']]
        runtime=max(candidates,key=lambda r:tuple(int(x) for x in r['version'].split('.')))
        parts=[int(x) for x in runtime['version'].split('.')]+[0,0]
        version=(parts[0]<<16)|(parts[1]<<8)|parts[2]
        types=json.loads(run('device-types',['xcrun','simctl','list','devicetypes','--json']))['devicetypes']
        phones=[d for d in types if d['name'].startswith('iPhone') and d.get('minRuntimeVersion',0)<=version<=d.get('maxRuntimeVersion',0xffffffff)]
        phone=phones[-1]
        device=run('create-owned-device',['xcrun','simctl','create','SIFAS-MVMenuProbe-'+uuid.uuid4().hex[:8],phone['identifier'],runtime['identifier']]).splitlines()[-1].strip()
        uuid.UUID(device); receipt['owned_device']=device; receipt['runtime']=runtime['identifier']; receipt['device_type']=phone['identifier']
        run('boot-owned-device',['xcrun','simctl','boot',device],30)
        run('open-owned-simulator',['open','-a','Simulator','--args','-CurrentDeviceUDID',device],15)
        run('bootstatus-owned-device',['xcrun','simctl','bootstatus',device,'-b'],120)
        run('install-probe',['xcrun','simctl','install',device,str(app)],40)
        container=Path(run('probe-container',['xcrun','simctl','get_app_container',device,bundle,'data'],20))
        result_path=container/'Documents/mv-menu-result.json'
        environment={**os.environ,'SIMCTL_CHILD_MV_MENU_PROBE_RESULT':str(result_path)}
        launch_command=['xcrun','simctl','launch',device,bundle]
        receipt['launch_command']=launch_command
        launch=subprocess.run(launch_command,env=environment,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
                              timeout=min(20,max(.1,deadline-time.monotonic())))
        (out/'console.log').write_text(launch.stdout[-16384:])
        if launch.returncode:
            raise RuntimeError('Probe launch failed: '+launch.stdout[-3000:])
        launch_deadline=min(deadline,time.monotonic()+45)
        while time.monotonic()<launch_deadline and not result_path.is_file():
            time.sleep(.2)
        if not result_path.is_file():
            raise RuntimeError('Probe produced no result within its bounded launch budget')
        if result_path.stat().st_size>65536:
            raise RuntimeError('Probe result exceeded64KiB')
        raw=result_path.read_bytes(); (out/'ui-result.json').write_bytes(raw)
        result=json.loads(raw); receipt['ui_result']=result
        if result.get('status')!='PASS_UIKIT_STANDALONE_MENU_REGRESSION':
            raise RuntimeError('UIKit regression failed: '+str(result.get('reason')))
        receipt['status']='PASS_UIKIT_STANDALONE_MENU_REGRESSION'; receipt['actual_uikit_simulator']=True
    except Exception as error:
        failed=True; receipt['failure']=str(error)
    finally:
        if device is not None:
            # This UUID was created by this invocation; never erase/shutdown
            # another simulator or terminate the shared Simulator application.
            cleanup=[]
            for operation in ('shutdown','delete'):
                try:
                    result=subprocess.run(['xcrun','simctl',operation,device],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=20)
                    cleanup.append({'operation':operation,'returncode':result.returncode,'output':result.stdout[-2000:]})
                    if operation=='delete' and result.returncode: failed=True
                except Exception as error: cleanup.append({'operation':operation,'failure':str(error)}); failed=True
            receipt['owned_device_cleanup']=cleanup
        if failed: receipt['status']='FAIL_UIKIT_STANDALONE_MENU_REGRESSION'
        (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(receipt['status']+': '+str(out/'receipt.json'))
    return 1 if failed else 0


if __name__=='__main__':
    raise SystemExit(main())

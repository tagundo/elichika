#!/usr/bin/env python3
"""Finite source-pinned native compilation, never an app packager or runtime QA."""
import argparse
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

BRANCH='refs/heads/codex/native-feature-compile-20261115'
SHA40=re.compile(r'[a-f0-9]{40}')
SHA256=re.compile(r'[a-f0-9]{64}')
TARGETS=[':app:compileDebugKotlin',':app:compileDebugJavaWithJavac']
EXCLUDED=[':app:buildHcaDecoder',':app:buildTexture65Decoder',':app:generateDebugPythonProxies']
FORBIDDEN=re.compile(r'(?:assemble|bundle|package|sign|install.*Python|extract.*Python|generate.*Python|merge.*Assets|preserve.*CdnCatalogAssets|merge.*NativeLibs|strip.*DebugSymbols|externalNativeBuild|configureCMake|buildHcaDecoder|buildTexture65Decoder)',re.I)
COMPILER_RESOURCE_TASKS={'packageDebugResources','processDebugManifestForPackage'}
MAX_CAPTURE=2*1024*1024
TAIL=64*1024

class CheckError(RuntimeError):pass

def require(value,message):
    if not value:raise CheckError(message)

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')

def capture(command, *, cwd, seconds):
    started=time.monotonic()
    process=subprocess.Popen(command,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
    chunks=[];tail=deque();total=[0];digest=hashlib.sha256();tail_size=[0]
    def drain():
        while True:
            block=process.stdout.read(8192)
            if not block:break
            digest.update(block);total[0]+=len(block)
            if sum(map(len,chunks))+len(block)<=MAX_CAPTURE:chunks.append(block)
            tail.append(block);tail_size[0]+=len(block)
            while tail_size[0]>TAIL and len(tail)>1:tail_size[0]-=len(tail.popleft())
    reader=threading.Thread(target=drain,name='bounded-build-output',daemon=True);reader.start()
    timed_out=False
    try:process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        timed_out=True;os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
    reader.join(5)
    require(not reader.is_alive(),'Build output reader did not terminate')
    process.stdout.close()
    result={'command':command,'exit_code':process.returncode,'timed_out':timed_out,
            'seconds':round(time.monotonic()-started,3),'stdout_bytes':total[0],
            'stdout_sha256':digest.hexdigest(),'capture_truncated':total[0]>MAX_CAPTURE}
    tail_text=b''.join(tail)[-TAIL:].decode('utf-8','replace')
    tail_text=tail_text.encode('utf-8')[-TAIL:].decode('utf-8','ignore')
    return result,b''.join(chunks).decode('utf-8','replace'),tail_text

def checked_capture(command, *, cwd, seconds, out, name):
    result,content,tail=capture(command,cwd=cwd,seconds=seconds)
    write(out/(name+'.json'),result)
    (out/(name+'-tail.txt')).write_text(tail)
    print(json.dumps({'phase':name,'exit_code':result['exit_code'],'timed_out':result['timed_out'],'seconds':result['seconds']}),flush=True)
    require(result['exit_code']==0 and not result['timed_out'],name+' failed; bounded tail/report retained')
    return result,content

def read_manifest(path):
    value=json.loads(path.read_text())
    require(type(value) is dict and type(value.get('schema')) is int and value['schema']==1 and value.get('scope')=='native_compile_only','Unsupported compile source manifest')
    require(type(value.get('files')) is list and len(value['files'])>20,'Expected full native source pins')
    require(set(value.get('gitlinks',{}))=={'assets','modtools'},'Expected both reviewed gitlinks')
    for digest in value['gitlinks'].values():require(type(digest) is str and SHA40.fullmatch(digest),'Gitlink must be a pinned commit')
    names=set()
    for row in value['files']:
        require(type(row) is dict and set(row)=={'path','sha256','bytes'},'Invalid source pin fields')
        name=row['path'];require(type(name) is str and name not in names and not name.startswith('/') and '..' not in Path(name).parts,'Unsafe or duplicate source pin')
        names.add(name)
        require(type(row['sha256']) is str and SHA256.fullmatch(row['sha256']) and type(row['bytes']) is int and row['bytes']>0,'Invalid source fingerprint')
    return value

def verify_files(root,manifest):
    for row in manifest['files']:
        path=root/row['path']
        require(path.is_file() and not path.is_symlink(),'Native source missing/linked: '+row['path'])
        require(path.stat().st_size==row['bytes'] and sha(path)==row['sha256'],'Native source changed: '+row['path'])

def preflight(root,manifest_path,out,*,environment=None):
    env=os.environ if environment is None else environment
    require(env.get('GITHUB_ACTIONS')=='true','Only disposable GitHub Actions checkout is authorized')
    require(env.get('GITHUB_REF')==BRANCH,'Wrong compile branch')
    require(env.get('GITHUB_REPOSITORY')=='tagundo/elichika','Wrong source repository')
    require(env.get('GITHUB_EVENT_NAME') in ('push','workflow_dispatch'),'Unsupported event')
    head=env.get('GITHUB_SHA','');require(SHA40.fullmatch(head),'Missing immutable source commit')
    actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    require(actual==head,'Checkout differs from event commit')
    manifest=read_manifest(manifest_path);verify_files(root,manifest)
    links={}
    for name,expected in manifest['gitlinks'].items():
        row=subprocess.check_output(['git','ls-tree','HEAD',name],cwd=root,text=True).strip().split()
        require(len(row)==4 and row[:2]==['160000','commit'] and row[3]==name and row[2]==expected,'Source gitlink changed: '+name)
        links[name]=expected
    build=(root/'android/app/build.gradle.kts').read_text()
    require(not re.search(r'\bstaticProxy\s*\(',build),'Compile-only exclusions are invalid when static Python proxies are declared')
    require('version "17.0.0"' in (root/'android/build.gradle.kts').read_text(),'Chaquopy taskgraph audit assumes plugin17')
    package=(root/'macos/Package.swift').read_text()
    require('.executableTarget(name: "ElichikaMac", path: "App")' in package and '.testTarget(name: "ElichikaMacTests", dependencies: ["ElichikaMac"], path: "Tests")' in package,'Full SwiftUI package/test membership changed')
    require('load_source_config' in (root/'macos/build/build_app.py').read_text(),'Archive packaging guard missing')
    report={'schema':1,'status':'SOURCE_VERIFIED','source_commit':head,'source_manifest_sha256':sha(manifest_path),'files_checked':len(manifest['files']),'gitlinks':links,'archive_config_sha256':sha(root/'archive-hosted-catalog.json'),'packaging_guard_executed':False,'compile_only':True,'excluded_noncompiler_tasks':EXCLUDED,'real_Android_Chaquopy_API_classpath':True}
    write(out/'source.json',report);return manifest,report

def gradle_command():
    return ['./gradlew','--console=plain','--no-daemon','--stacktrace','--max-workers=2',
            '-Dorg.gradle.jvmargs=-Xmx2048m','-Pkotlin.compiler.execution.strategy=in-process']+TARGETS+[x for t in EXCLUDED for x in ['-x',t]]

def audit_graph(text):
    tasks=re.findall(r'^(:[A-Za-z0-9_:]+)\s+SKIPPED\s*$',text,re.M)
    require(tasks and len(tasks)<=300,'Missing or unbounded Gradle task graph')
    require(set(TARGETS)<=set(tasks),'Actual Kotlin and Java compilers must both be in the graph')
    rejected=[t for t in tasks if t.rsplit(':',1)[-1] not in COMPILER_RESOURCE_TASKS and FORBIDDEN.search(t.rsplit(':',1)[-1])]
    require(not rejected,'Noncompile dependency entered task graph: '+', '.join(rejected))
    return tasks

def class_proof(root):
    outputs={}
    java=root/'android/app/build/intermediates/javac/debug/compileDebugJavaWithJavac/classes/com/tagundo/elichika'
    kotlin=root/'android/app/build/tmp/kotlin-classes/debug/com/tagundo/elichika'
    for name in ['ArchiveWorkerFence.class','ArchiveWorkerFence$Lease.class']:
        path=java/name;require(path.is_file(),'Production Java class missing: '+name);outputs[name]=sha(path)
    for name in ['ToolFileChooser','MainActivity','ServerService','ArchiveDownloadCallbacks','ArchiveDownloadProgress','Bus']:
        path=kotlin/(name+'.class');require(path.is_file(),'Actual Kotlin class missing: '+name);outputs[name+'.class']=sha(path)
    require(not list((root/'android/app/build/outputs').glob('**/*.apk')) and not list((root/'android/app/build/outputs').glob('**/*.aab')),'Compile-only job unexpectedly produced a package')
    return outputs

def android(root,manifest_path,out):
    manifest,source=preflight(root,manifest_path,out)
    command=gradle_command()
    graph,content=checked_capture(command+['--dry-run'],cwd=root/'android',seconds=240,out=out,name='android-taskgraph')
    require(not graph['capture_truncated'],'Task graph exceeded bounded capture')
    tasks=audit_graph(content);write(out/'android-graph-audit.json',{'status':'PASS','tasks':tasks,'excluded':EXCLUDED,'guard_bypass':False})
    build,_=checked_capture(command,cwd=root/'android',seconds=840,out=out,name='android-compile')
    verify_files(root,manifest)
    require(sha(root/'archive-hosted-catalog.json')==source['archive_config_sha256'],'Archive source config changed during compilation')
    write(out/'android-result.json',{'schema':1,'status':'PASS_NATIVE_ANDROID_JAVA_KOTLIN_COMPILE_ONLY','source_commit':source['source_commit'],'source_manifest_sha256':source['source_manifest_sha256'],'compiled_class_sha256':class_proof(root),'task_graph_checked':True,'packaging':False,'native_runtime_or_TLS_or_download_QA':False,'command':command,'seconds':build['seconds']})

def swift(root,manifest_path,out,scratch):
    manifest,source=preflight(root,manifest_path,out)
    for name,command in [('xcode-path',['xcode-select','-p']),('xcode-version',['xcodebuild','-version']),('swift-version',['xcrun','swift','--version']),('macos-sdk',['xcrun','--sdk','macosx','--show-sdk-path'])]:
        checked_capture(command,cwd=root,seconds=20,out=out,name=name)
    command=['xcrun','swift','test','--package-path','macos','--scratch-path',str(scratch),'--configuration','debug','--jobs','2']
    result,content=checked_capture(command,cwd=root,seconds=960,out=out,name='swift-tests')
    require(not result['capture_truncated'],'Swift output exceeded bounded capture')
    counts=[int(n) for n in re.findall(r'Executed (\d+) tests?, with 0 failures',content)]
    require(counts and max(counts)>0,'Swift command did not report executed package tests')
    executable=scratch/'debug/Elichika';require(executable.is_file(),'Full SwiftUI executable build product missing')
    verify_files(root,manifest)
    write(out/'swift-result.json',{'schema':1,'status':'PASS_FULL_SWIFTUI_PACKAGE_COMPILE_AND_TEST','source_commit':source['source_commit'],'source_manifest_sha256':source['source_manifest_sha256'],'tests_executed':max(counts),'compiled_SwiftUI_executable_sha256':sha(executable),'package_path':'macos','package_manifest_unchanged':True,'packaging':False,'native_packaged_TLS_or_download_QA':False,'seconds':result['seconds']})

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['preflight','android','swift'])
    parser.add_argument('--root',type=Path,default=Path.cwd());parser.add_argument('--manifest',type=Path,default=Path('ci/native-feature-compile-inputs.json'))
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--scratch',type=Path)
    args=parser.parse_args();root=args.root.resolve();manifest=args.manifest if args.manifest.is_absolute() else root/args.manifest
    args.out.mkdir(parents=True,exist_ok=True)
    try:
        if args.mode=='preflight':preflight(root,manifest,args.out)
        elif args.mode=='android':android(root,manifest,args.out)
        else:
            require(args.scratch is not None,'Swift needs disposable runner scratch path')
            swift(root,manifest,args.out,args.scratch)
    except (CheckError,OSError,ValueError,subprocess.SubprocessError) as error:
        write(args.out/'failure.json',{'schema':1,'status':'FAILED','phase':args.mode,'error':str(error)[:2048],'packaging':False})
        print('Native compile check failed: '+str(error),file=sys.stderr);return 1
    print(json.dumps({'status':'PASS','phase':args.mode,'receipt_directory':str(args.out)}));return 0
if __name__=='__main__':sys.exit(main())

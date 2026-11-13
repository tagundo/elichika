"""Observe a derived C5 app through the unchanged normal smoke/relocation flow."""
import argparse,hashlib,json,os,pathlib,subprocess,sys
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=pathlib.Path,required=True);p.add_argument('--evidence',type=pathlib.Path,required=True);p.add_argument('--relocation',type=pathlib.Path,required=True);a=p.parse_args()
proof=json.loads((a.evidence/'derived-app-provenance.json').read_text());assert proof['status']=='DERIVED_C5_PCM_OBSERVER_ONLY_UNVALIDATED'
app=pathlib.Path(proof['derived_app']);script=a.repo/'macos/ci/diagnose_app_smoke.py'
manifest=json.loads((a.repo/'qa/mac-pcm-diagnostic/proposal-manifest.json').read_text())
for name in ['macos/ci/run_app_smoke.py','macos/App/NativeSmokeTest.swift']:
 assert hashlib.sha256((a.repo/name).read_bytes()).hexdigest()==manifest['frozen_inputs'][name]['sha256']
assert hashlib.sha256(script.read_bytes()).hexdigest()=='85aea638c31abb6133ec16c1cd83b405e4185911edf286ee595db889f9e29a9a'
assert subprocess.check_output(['git','-C',str(a.repo/'modtools'),'rev-parse','HEAD'],text=True).strip()=='524518e136107b27b89cf33cb2fd9eca0f8e5acc'
env=dict(os.environ);env['ELICHIKA_NATIVE_PCM_GAME_QA']='1'
command=[sys.executable,str(script),'--repo',str(a.repo),'--app',str(app),'--evidence',str(a.evidence),'--relocation',str(a.relocation)]
with (a.evidence/'diagnostic-driver.stdout.txt').open('w') as out,(a.evidence/'diagnostic-driver.stderr.txt').open('w') as err:
 process=subprocess.run(command,env=env,stdout=out,stderr=err,timeout=1800)
reports=[]
for name in ['first-launch.json','native-app-data/native-smoke.json']:
 path=a.evidence/name
 if not path.is_file():continue
 value=json.loads(path.read_text());pcm=value.get('native_pcm_audio',{});failure=value.get('native_part_failure_diagnostic',{}).get('diagnostic') or {}
 captures=pcm.get('passiveClockDiagnostics',{}).get('captures',[]) or failure.get('nativePCMClockAssertions',[])
 reports.append({'report':name,'raw_status':value.get('status'),'stage':value.get('stage'),'error':value.get('error'),'clock_captures':captures,'helper_sha256_if_passed':pcm.get('helper_sha256'),'product_source_sha256_if_passed':pcm.get('product_source_sha256')})
capture_count=sum(len(x['clock_captures']) for x in reports)
observer_complete=capture_count==4 if process.returncode==0 else capture_count>0
summary={'observer_capture_count':capture_count,'observer_complete_for_raw_outcome':observer_complete,'status':'DERIVED_DIAGNOSTIC_ONLY_RAW_SMOKE_PASS' if process.returncode==0 else 'DERIVED_DIAGNOSTIC_ONLY_RAW_SMOKE_FAIL','original_gate_exit_code':process.returncode,'original_gate_and_thresholds_unchanged':True,'source_C5_and_original_failure_not_promoted_or_waived':True,'observer_only_resource_sha256':proof['qa_helper_sha256'],'reports':reports,'validated_release_artifact':False}
(a.evidence/'derived-pcm-diagnostic-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({'status':summary['status'],'captured_observations':sum(len(x['clock_captures']) for x in reports)},indent=2));raise SystemExit(process.returncode if process.returncode else (0 if observer_complete else 1))

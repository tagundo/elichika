#!/usr/bin/env python3
"""Reuse actual 45-test proof only for identical frozen C5 compiled inputs."""
import argparse,hashlib,io,json,re,subprocess,urllib.request,zipfile
from pathlib import Path

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--qa',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--prior-archive',type=Path);a=p.parse_args()
 receipt=json.loads((a.qa/'prior-unit-validation.json').read_text());manifest=json.loads((a.qa/'source-manifest.json').read_text())
 assert receipt['status']=='PASS' and receipt['tests']==45
 assert receipt['candidate_inputs']==manifest['files'] and len(manifest['files'])==7
 assert re.fullmatch('[0-9a-f]{40}',receipt['candidate_source_commit']) and receipt['candidate_source_commit']==manifest['candidate_source_commit']
 wanted={x['path']:x['sha256'] for x in manifest['files']}
 for row in manifest['macos_package_inputs']:
  assert row['path'] not in wanted or wanted[row['path']]==row['sha256'],'Conflicting frozen source hashes'
  wanted[row['path']]=row['sha256']
 assert len({x['path'] for x in manifest['macos_package_inputs']})==len(manifest['macos_package_inputs'])
 for row in manifest['files']:
  assert hashlib.sha256((a.qa/'candidate'/row['path']).read_bytes()).hexdigest()==row['sha256']
 for path,digest in wanted.items():
  with urllib.request.urlopen('https://raw.githubusercontent.com/tagundo/elichika/'+receipt['candidate_source_commit']+'/'+path,timeout=30) as response:data=response.read(4*1024*1024+1)
  assert len(data)<=4*1024*1024 and hashlib.sha256(data).hexdigest()==digest,path+' differs from frozen C5'
 if a.prior_archive:archive=a.prior_archive.read_bytes()
 else:
  proc=subprocess.run(['env','-u','GH_TOKEN','gh','api','repos/tagundo/elichika/actions/artifacts/'+str(receipt['artifact_id'])+'/zip'],capture_output=True,timeout=90)
  if proc.returncode:raise RuntimeError('Matching native artifact download failed; credentials/redirect details omitted')
  archive=proc.stdout
 assert len(archive)==receipt['artifact_bytes'] and hashlib.sha256(archive).hexdigest()==receipt['artifact_sha256']
 with zipfile.ZipFile(io.BytesIO(archive)) as z:
  assert sum(x.file_size for x in z.infolist())<64*1024*1024
  log=z.read('proposed-positive-swift-tests.log');inputs=json.loads(z.read('anchor-preview-source-inputs.json'));summary=json.loads(z.read('anchor-preview-summary.json'))
 assert hashlib.sha256(log).hexdigest()==receipt['test_log_sha256']
 assert re.search(rb'Executed 45 tests, with 0 failures \(0 unexpected\)',log)
 assert summary['status']=='PASS_TARGETED_C4_NEGATIVE_PROPOSAL_POSITIVE_AND_FRESH45'
 assert summary['units']['C4-negative']['expected_actual_result'] is True
 assert summary['units']['proposed-positive']['expected_actual_result'] is True and summary['units']['proposed-positive']['log_sha256']==receipt['test_log_sha256']
 variant=inputs['variants']['proposed-positive'];actual={x['path']:x['sha256'] for x in variant['source_files']}
 assert actual=={x['path']:x['sha256'] for x in manifest['macos_package_inputs']},'Complete SwiftPM App/Tests/Package inputs differ'
 actual['macos/runtime/elichika_macos.py']=variant['python_sha256']
 frozen={x['path']:x['sha256'] for x in inputs['frozen_six']}
 actual['tests/test_macos_runtime_console_logging.py']=frozen['tests/test_macos_runtime_console_logging.py']
 assert all(actual[path]==digest for path,digest in wanted.items())
 a.evidence.mkdir(parents=True,exist_ok=True);(a.evidence/'prior-45-swift-unit-tests.log').write_bytes(log)
 output={**receipt,'complete_macos_package_inputs_matched':True,'source_bound_preview_negative_and_positive_pass':True,'normal_C5_mandatory_suite_waived':False}
 (a.evidence/'reused-unit-validation.json').write_text(json.dumps(output,indent=2)+'\n')
 print('Verified seven frozen C5 inputs, full unchanged SwiftPM source set and actual fresh45 proof; normal C5 CI remains mandatory')

if __name__=='__main__':main()

"""Fetch one root-bound normal-validated C10 artifact; inert while inputs are pending."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from native_qa_guards import bound_inputs,begin_python_guard,finish_python_guard

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('qa','archive','metadata','guard-proof'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    python_guard=begin_python_guard('fetch',args.guard_proof)
    guard_completed=False
    try:
        manifest_guard,normal_guard=bound_inputs(args.qa)
        manifest=json.loads((args.qa/'proposal-manifest.json').read_bytes())
        assert manifest['status']=='ROOT_BOUND_EXACT_C10_VALIDATED_MAC_NATIVE_QA_INPUTS','INERT pending actual final artifact and normal reader proof'
        assert not args.archive.exists() and not args.metadata.exists(),'Never replace prior artifact or metadata'
        proof=manifest['normal_mac_review_proof']
        assert proof['file']=='normal-mac-reader-proof.json'
        proof_path=args.qa/proof['file']
        assert proof_path.is_file() and not proof_path.is_symlink() and digest(proof_path)==proof['sha256']
        normal=json.loads(proof_path.read_bytes())
        normal_run=manifest['normal_workflow_run']
        assert type(normal_run) is int and normal_run>0
        assert normal['status']==normal['normal_ci_status']=='PASS_FULL_SOURCE_BOUND_MAC_NATIVE_AND_PACKAGING'
        assert normal['run_id']==normal_run and normal['run_attempt']==1
        assert normal['parent_commit']==manifest['frozen_source_commit']=='51727bae11df587bb49bb0a0fd69a270018c380b'
        assert normal['source_record_sha256']==manifest['source_record_sha256']=='ab1b558856f015ef6fdfa989d1d46b3000db125d1a58c059ddaf33c679908277'
        expected=manifest['original_artifact']
        assert type(expected['id']) is int and expected['id']>0 and expected['name']=='elichika-macos-apple-silicon'
        env=dict(os.environ)
        env.pop('GH_TOKEN',None)
        route='repos/tagundo/elichika/actions/artifacts/'+str(expected['id'])
        response=subprocess.run(['gh','api','--method','GET',route],env=env,capture_output=True,timeout=45)
        assert response.returncode==0,'Actual validated artifact metadata GET failed: exit '+str(response.returncode)
        actual=json.loads(response.stdout)
        for key in ('id','name','size_in_bytes','digest','expired','workflow_run'):
            assert actual[key]==expected[key]==normal['app_artifact'][key],'Actual artifact metadata differs: '+key
        assert actual['expired'] is False and actual['workflow_run']['id']==normal_run
        assert actual['workflow_run']['head_sha']=='51727bae11df587bb49bb0a0fd69a270018c380b'
        assert actual['workflow_run']['head_branch']=='codex/client-server-release-20261113-1-c10'
        with args.metadata.open('xb') as output:
            output.write(response.stdout)
        with args.archive.open('xb') as output:
            downloaded=subprocess.run(['gh','api','--method','GET',route+'/zip'],env=env,stdout=output,stderr=subprocess.PIPE,timeout=180)
        assert downloaded.returncode==0,'Exact validated artifact download failed: exit '+str(downloaded.returncode)
        assert args.archive.stat().st_size==actual['size_in_bytes'] and 'sha256:'+digest(args.archive)==actual['digest']
        print(json.dumps({'status':'FETCHED_EXACT_ROOT_BOUND_NORMAL_VALIDATED_C10_ARTIFACT_ONLY','artifact_id':actual['id'],
            'archive_bytes':args.archive.stat().st_size,'archive_sha256':digest(args.archive),'app_rebuilt_or_modified':False,
            'normal_or_native_or_release_approval_created':False}))
        guard_completed=True
    finally:
        finish_python_guard(python_guard,args.guard_proof,guard_completed,
            None if guard_completed else 'fetch stage did not complete; preserve the original exception and evidence')

if __name__=='__main__':
    main()

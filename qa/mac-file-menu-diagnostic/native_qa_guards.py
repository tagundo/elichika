"""Read-only C10 QA input guards and exclusive owned evidence writes; no import actions."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

SOURCE='51727bae11df587bb49bb0a0fd69a270018c380b'
TOOLS='932666aa03264225e2a6bb2a973482b47e22b050'
SOURCE_RECORD='ab1b558856f015ef6fdfa989d1d46b3000db125d1a58c059ddaf33c679908277'
BRANCH='codex/client-server-release-20261113-1-c10'
QA_FILES=frozenset({'NativeFileMenuDiagnostic.swift','prepare_exact_app.py','run_native_diagnostic.py',
    'fetch_reviewed_artifact.py','native_qa_guards.py','mac-file-menu-diagnostic.yml','README.md','make_fixtures.py',
    'fixtures/fixture-generation.json','fixtures/large-import.png','fixtures/large-layers.json',
    'fixtures/large-model.unity','fixtures/small-import.png','fixtures/small-layers.json','fixtures/small-model.unity'})

def require(value,message):
    if not value:
        raise ValueError(message)

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def regular(path):
    path=Path(path)
    require(path.is_absolute() and path.resolve(strict=True)==path,'Expected absolute regular path without symlink components')
    require(stat.S_ISREG(path.lstat().st_mode),'Expected regular file: '+str(path))
    with path.open('rb') as stream:
        return stream.read()

def write_new(path,value):
    path=Path(path)
    require(path.is_absolute() and path.parent.resolve(strict=True)==path.parent,'Unsafe owned evidence parent')
    raw=(json.dumps(value,indent=2)+'\n').encode()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o444)
    with os.fdopen(fd,'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()

def begin_python_guard(stage,proof_path):
    require(sys.dont_write_bytecode and sys.flags.optimize==0,'Use -B and never Python -O')
    require(isinstance(sys.pycache_prefix,str),'A fresh owned -X pycache_prefix is required')
    prefix=Path(sys.pycache_prefix)
    require(prefix.is_absolute() and prefix.resolve(strict=True)==prefix and prefix.is_dir()
        and prefix.stat().st_uid==os.getuid() and not list(prefix.iterdir()),'Cache prefix must be fresh, empty and owned')
    proof_path=Path(proof_path)
    require(proof_path.is_absolute() and proof_path.parent.resolve(strict=True)==proof_path.parent
        and not proof_path.exists() and not proof_path.is_symlink(),'Refuse old or unsafe Python guard proof; no overwrite')
    return {'stage':stage,'argv':sys.orig_argv,'executable':sys.executable,
        'resolved_executable':str(Path(sys.executable).resolve()),'interpreter_sha256':digest(Path(sys.executable).resolve()),
        'version':sys.version,'dont_write_bytecode':sys.dont_write_bytecode,'optimize':sys.flags.optimize,
        'pycache_prefix':str(prefix),'proof_path':str(proof_path),'before_entries':[]}

def finish_python_guard(before,path,completed,error=None):
    require(Path(path)==Path(before['proof_path']),'Python guard output binding changed')
    prefix=Path(before['pycache_prefix'])
    after=sorted(str(p.relative_to(prefix)) for p in prefix.rglob('*'))
    receipt=dict(before,after_entries=after,cache_empty_before_and_after=not after,
        stage_completed=bool(completed),error=error)
    write_new(path,receipt)
    require(not after,'Cache prefix changed during actual QA invocation')

def bound_inputs(qa):
    qa=Path(qa).resolve(strict=True)
    manifest_path=qa/'proposal-manifest.json'
    manifest=json.loads(regular(manifest_path))
    require(manifest['status']=='ROOT_BOUND_EXACT_C10_VALIDATED_MAC_NATIVE_QA_INPUTS','INERT until actual artifact and reader proof are root-bound')
    require(manifest['frozen_source_commit']==SOURCE and manifest['source_record_sha256']==SOURCE_RECORD,'Wrong C10 source binding')
    require(set(manifest['qa_files'])==QA_FILES,'Complete reviewed QA payload membership differs')
    for name,binding in manifest['qa_files'].items():
        path=qa/name
        raw=regular(path)
        require(len(raw)==binding['bytes'] and hashlib.sha256(raw).hexdigest()==binding['sha256'],'Reviewed QA payload changed: '+name)
    proof=manifest['normal_mac_review_proof']
    require(proof['file']=='normal-mac-reader-proof.json' and re.fullmatch('[0-9a-f]{64}',proof['sha256']),'Invalid actual normal-reader proof binding')
    raw=regular(qa/proof['file'])
    require(hashlib.sha256(raw).hexdigest()==proof['sha256'],'Actual normal-reader proof changed')
    normal=json.loads(raw)
    run=manifest['normal_workflow_run']
    require(type(run) is int and run>0 and normal['run_id']==run and normal['run_attempt']==1,'Absent or different actual normal run')
    require(normal['status']==normal['normal_ci_status']=='PASS_FULL_SOURCE_BOUND_MAC_NATIVE_AND_PACKAGING'
        and normal['manual_visual_review']['status']=='PASS_BOUNDED_SIX_CAPTURE_REVIEW','Normal Mac reader has not completed')
    require(normal['parent_commit']==SOURCE and normal['tools_commit']==TOOLS
        and normal['source_record_sha256']==SOURCE_RECORD,'Normal reader belongs to another source')
    require(normal['source']==manifest['frozen_bundle_source']
        and normal['source']=={'parent_commit':SOURCE,'modtools_commit':TOOLS,'parent_tree':normal['source']['parent_tree']},'Normal bundle source identity differs')
    artifact=manifest['original_artifact']
    require(type(artifact['id']) is int and artifact['id']>0 and artifact['name']=='elichika-macos-apple-silicon'
        and artifact['expired'] is False and type(artifact['size_in_bytes']) is int
        and 250_000_000<artifact['size_in_bytes']<512*1024*1024
        and re.fullmatch('sha256:[0-9a-f]{64}',artifact['digest']),'Only an actual normal-validated artifact is eligible')
    for key in ('id','name','size_in_bytes','digest','expired','workflow_run'):
        require(normal['app_artifact'][key]==artifact[key],'Normal reader/artifact differs: '+key)
    require(artifact['workflow_run']['id']==run and artifact['workflow_run']['head_sha']==SOURCE
        and artifact['workflow_run']['head_branch']==BRANCH,'Artifact actual run/head/branch differs')
    inner=manifest['inner_app_archive']
    require(inner==normal['archive'] and inner['name']=='Elichika-2026.11.13.1-AppleSilicon.app.zip'
        and type(inner['bytes']) is int and 250_000_000<inner['bytes']<512*1024*1024
        and re.fullmatch('[0-9a-f]{64}',inner['sha256']),'Actual validated inner archive differs')
    return manifest,normal

def bound_provenance(manifest,provenance,scratch):
    require(provenance['status']=='EXACT_UNMODIFIED_VALIDATED_C10_APP_FOR_NATIVE_QA_ONLY','Wrong prepared app stage')
    require(provenance['source_commit']==SOURCE and provenance['tools_commit']==TOOLS
        and provenance['source_record_sha256']==SOURCE_RECORD
        and provenance['workflow_run']==manifest['normal_workflow_run'],'Prepared app source/run differs')
    artifact=manifest['original_artifact']
    require(provenance['artifact_id']==artifact['id'] and provenance['outer_zip_bytes']==artifact['size_in_bytes']
        and 'sha256:'+provenance['outer_zip_sha256']==artifact['digest']
        and provenance['inner_app_archive']==manifest['inner_app_archive']
        and provenance['normal_mac_reader_proof_sha256']==manifest['normal_mac_review_proof']['sha256'],
        'Prepared app artifact/archive/normal-reader binding differs')
    require(provenance['app_modified_or_resigned'] is False and provenance['normal_app_no_smoke_mode'] is True
        and provenance['validated_normal_artifact_input'] is True and provenance['release_approved'] is False
        and provenance['validated_release_artifact'] is False and provenance['original_C7_failure_waived'] is False
        and provenance['bundle_identifier']=='com.tagundo.elichika.macos','Prepared app scope differs')
    app=Path(provenance['app'])
    require(app.is_absolute() and app.resolve(strict=True)==app
        and app.parent==Path(scratch).resolve(strict=True)/'original-app' and app.name=='Elichika.app',
        'Prepared app is outside the exact owned scratch')
    return app

def claim_native_activation(evidence,scratch,qa,manifest,provenance):
    evidence=Path(evidence).resolve(strict=True)
    expected={'outer-ZIP-complete-member-inventory.json','inner-ZIP-complete-member-inventory.json',
        'original-app-inventory.json','exact-app-provenance.json','original-C10-validated-artifact-metadata.json',
        'fetch-python-cache-proof.json','prepare-python-cache-proof.json'}
    require({p.name for p in evidence.iterdir()}==expected,'Refuse prior or unexpected native evidence; no retry or overwrite')
    require(all(p.is_file() and not p.is_symlink() for p in evidence.iterdir()),'Unexpected prepared evidence node')
    for name,stage in (('fetch-python-cache-proof.json','fetch'),('prepare-python-cache-proof.json','prepare')):
        proof=json.loads(regular(evidence/name))
        original=Path(os.environ['RUNNER_TEMP'])/name
        require(Path(proof['proof_path'])==original and digest(original)==digest(evidence/name),
            'Actual host Python guard proof copy differs')
        prefix=Path(proof['pycache_prefix'])
        require(proof['stage']==stage and proof['stage_completed'] is True and proof['error'] is None
            and proof['dont_write_bytecode'] is True and proof['optimize']==0
            and proof['before_entries']==proof['after_entries']==[] and proof['cache_empty_before_and_after'] is True
            and prefix.is_absolute() and prefix.resolve(strict=True)==prefix and prefix.is_dir() and prefix.stat().st_uid==os.getuid()
            and not list(prefix.iterdir()),'Actual host Python cache guard is incomplete')
    require(not (Path(scratch)/'owned-file-menu-data').exists() and not (Path(scratch)/'NativeFileMenuDiagnostic').exists(),
        'Prior native fixture root/helper exists; no retry')
    require(digest(evidence/'original-app-inventory.json')==provenance['original_app_inventory_sha256'],
        'Prepared signed-app inventory binding differs')
    record={'status':'NATIVE_C10_QA_INTENT_RECORDED_BEFORE_COMPILATION_OR_UI_NO_RETRY',
        'source_commit':SOURCE,'tools_commit':TOOLS,'source_record_sha256':SOURCE_RECORD,
        'normal_run':manifest['normal_workflow_run'],'artifact_id':manifest['original_artifact']['id'],
        'outer_zip_sha256':provenance['outer_zip_sha256'],'inner_app_archive':manifest['inner_app_archive'],
        'qa_manifest_sha256':digest(Path(qa)/'proposal-manifest.json'),
        'normal_reader_sha256':manifest['normal_mac_review_proof']['sha256'],
        'exact_app_provenance_sha256':digest(evidence/'exact-app-provenance.json'),
        'original_app_inventory_sha256':provenance['original_app_inventory_sha256'],
        'qa_workflow_run':os.environ.get('GITHUB_RUN_ID'),'app_modified_or_resigned':False,'release_approved':False}
    return write_new(evidence/'native-qa-activation-intent.json',record)

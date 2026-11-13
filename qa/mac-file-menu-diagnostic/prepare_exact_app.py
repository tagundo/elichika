"""Extract and inventory the exact, unmodified, normal-validated C10 app for UI diagnostics."""
import argparse, hashlib, json, os, pathlib, plistlib, stat, subprocess, zipfile
from native_qa_guards import bound_inputs,begin_python_guard,finish_python_guard

SOURCE = '51727bae11df587bb49bb0a0fd69a270018c380b'
TOOLS = '932666aa03264225e2a6bb2a973482b47e22b050'
SOURCE_RECORD_SHA = 'ab1b558856f015ef6fdfa989d1d46b3000db125d1a58c059ddaf33c679908277'

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def inventory(root):
    result = {}
    for path in [root, *sorted(root.rglob('*'))]:
        name = '.' if path == root else path.relative_to(root).as_posix()
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            assert path.resolve().is_relative_to(root.resolve()), f'Escaping bundle link: {name}'
            result[name] = {'link': os.readlink(path), 'mode': mode}
        elif path.is_dir(): result[name] = {'directory': True, 'mode': mode}
        elif path.is_file(): result[name] = {'bytes': path.stat().st_size, 'sha256': sha(path), 'mode': mode}
        else: raise ValueError(f'Unexpected node: {name}')
    return result

def safe_zip(path, limit):
    with zipfile.ZipFile(path) as archive:
        rows = archive.infolist()
        assert 0 < len(rows) < 50000 and sum(row.file_size for row in rows) < limit
        seen = set()
        for row in rows:
            name = pathlib.PurePosixPath(row.filename)
            assert row.filename and '\\' not in row.filename and not name.is_absolute() and '..' not in name.parts
            assert row.filename not in seen and row.file_size < 512 * 1024 * 1024
            seen.add(row.filename)
            if stat.S_ISLNK(row.external_attr >> 16):
                target = archive.read(row).decode()
                joined = pathlib.PurePosixPath(os.path.normpath(str(name.parent / target)))
                assert not pathlib.PurePosixPath(target).is_absolute() and '..' not in joined.parts

def zip_inventory(path):
    result=[]
    with zipfile.ZipFile(path) as archive:
        for row in archive.infolist():
            digest=hashlib.sha256()
            with archive.open(row) as source:
                for chunk in iter(lambda:source.read(1024*1024),b''):
                    digest.update(chunk)
            result.append({'path':row.filename,'bytes':row.file_size,'compressed_bytes':row.compress_size,
                           'CRC32':row.CRC,'external_mode':row.external_attr>>16,'flags':row.flag_bits,
                           'is_directory':row.is_dir(),'sha256':digest.hexdigest()})
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['archive','qa','scratch','evidence','guard-proof']:parser.add_argument('--'+name,type=pathlib.Path,required=True)
    args=parser.parse_args()
    python_guard=begin_python_guard('prepare',args.guard_proof)
    guard_completed=False
    try:
        manifest_guard,normal_guard=bound_inputs(args.qa)
        manifest=json.loads((args.qa/'proposal-manifest.json').read_text())
        assert manifest['status']=='ROOT_BOUND_EXACT_C10_VALIDATED_MAC_NATIVE_QA_INPUTS','INERT until actual validated artifact and normal reader proof are root-bound'
        assert manifest['frozen_source_commit']==SOURCE and manifest['source_record_sha256']==SOURCE_RECORD_SHA
        normal_run=manifest['normal_workflow_run']
        assert type(normal_run) is int and normal_run>0
        for name,binding in manifest['qa_files'].items():
            path=args.qa/name
            assert path.is_file() and not path.is_symlink() and path.stat().st_size==binding['bytes'] and sha(path)==binding['sha256']
        proof_binding=manifest['normal_mac_review_proof']
        assert proof_binding['file']=='normal-mac-reader-proof.json'
        proof_path=args.qa/proof_binding['file']
        assert proof_path.is_file() and not proof_path.is_symlink() and sha(proof_path)==proof_binding['sha256']
        normal=json.loads(proof_path.read_text())
        assert normal['status']==normal['normal_ci_status']=='PASS_FULL_SOURCE_BOUND_MAC_NATIVE_AND_PACKAGING'
        assert normal['parent_commit']==SOURCE and normal['tools_commit']==TOOLS and normal['source_record_sha256']==SOURCE_RECORD_SHA
        assert normal['run_id']==normal_run and normal['run_attempt']==1
        assert normal['manual_visual_review']['status']=='PASS_BOUNDED_SIX_CAPTURE_REVIEW'
        artifact=manifest['original_artifact']
        assert type(artifact['id']) is int and artifact['id']>0 and artifact['name']=='elichika-macos-apple-silicon' and artifact['expired'] is False
        assert artifact['workflow_run']['id']==normal_run and artifact['workflow_run']['head_sha']==SOURCE
        assert artifact['workflow_run']['head_branch']=='codex/client-server-release-20261113-1-c10'
        for key in ['id','name','size_in_bytes','digest','expired','workflow_run']:assert normal['app_artifact'][key]==artifact[key]
        assert args.archive.stat().st_size==artifact['size_in_bytes'] and 'sha256:'+sha(args.archive)==artifact['digest']
        assert not args.scratch.exists() and not args.evidence.exists()
        args.scratch.mkdir(parents=True);args.evidence.mkdir(parents=True)
        safe_zip(args.archive,512*1024*1024)
        outer_inventory=zip_inventory(args.archive)
        (args.evidence/'outer-ZIP-complete-member-inventory.json').write_text(json.dumps(outer_inventory,indent=2)+'\n')
        outer=args.scratch/'outer';outer.mkdir()
        with zipfile.ZipFile(args.archive) as archive:
            assert not any(stat.S_ISLNK(row.external_attr>>16) for row in archive.infolist())
            expected=manifest['inner_app_archive']
            assert expected==normal['archive'] and expected['name']=='Elichika-2026.11.13.1-AppleSilicon.app.zip'
            assert {r.filename for r in archive.infolist() if not r.is_dir()}=={expected['name'],'SHA256SUMS'}
            assert archive.read('SHA256SUMS').decode()==expected['sha256']+'  '+expected['name']+'\n'
            archive.extractall(outer)
        packed=outer/expected['name']
        assert packed.is_file() and packed.stat().st_size==expected['bytes'] and sha(packed)==expected['sha256']
        safe_zip(packed,3*1024*1024*1024)
        (args.evidence/'inner-ZIP-complete-member-inventory.json').write_text(json.dumps(zip_inventory(packed),indent=2)+'\n')
        apps=args.scratch/'original-app';apps.mkdir()
        subprocess.run(['/usr/bin/ditto','-x','-k',str(packed),str(apps)],check=True)
        found=list(apps.glob('*.app'));assert len(found)==1;app=found[0]
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True)
        info=plistlib.loads((app/'Contents/Info.plist').read_bytes());assert info['CFBundleIdentifier']=='com.tagundo.elichika.macos'
        bundle_source=json.loads((app/'Contents/Resources/bundle-provenance.json').read_text())
        assert bundle_source['source']==manifest['frozen_bundle_source'] and bundle_source['version']=='2026.11.13.1'
        before=inventory(app)
        for name,binding in manifest['frozen_packaged_product_files'].items():
            assert before[name]['sha256']==binding['sha256'] and before[name]['bytes']==binding['bytes']
        (args.evidence/'original-app-inventory.json').write_text(json.dumps(before,indent=2)+'\n')
        provenance={'status':'EXACT_UNMODIFIED_VALIDATED_C10_APP_FOR_NATIVE_QA_ONLY','source_commit':SOURCE,
                    'tools_commit':TOOLS,'source_record_sha256':SOURCE_RECORD_SHA,'workflow_run':normal_run,
                    'artifact_id':artifact['id'],'outer_zip_sha256':sha(args.archive),'outer_zip_bytes':args.archive.stat().st_size,
                    'inner_app_archive':expected,'normal_mac_reader_proof_sha256':proof_binding['sha256'],
                    'original_app_inventory_sha256':sha(args.evidence/'original-app-inventory.json'),
                    'app':str(app),'bundle_identifier':info['CFBundleIdentifier'],'app_modified_or_resigned':False,
                    'normal_app_no_smoke_mode':True,'validated_normal_artifact_input':True,
                    'validated_release_artifact':False,'release_approved':False,'original_C7_failure_waived':False}
        (args.evidence/'exact-app-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
        print(str(app))
        guard_completed=True
    finally:
        finish_python_guard(python_guard,args.guard_proof,guard_completed,
            None if guard_completed else 'prepare stage did not complete; preserve the original exception and evidence')

if __name__=='__main__':main()

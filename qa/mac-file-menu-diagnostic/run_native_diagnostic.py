"""Run one unchanged-app OS-dialog diagnostic and preserve failures without promotion."""
import argparse, base64, hashlib, importlib.util, io, json, os, pathlib, shutil, subprocess, sys, tempfile
from native_qa_guards import (bound_inputs,bound_provenance,claim_native_activation,
    begin_python_guard,finish_python_guard)

def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()

VERIFY = "import hashlib,json,os,pathlib,sys\nassert sys.dont_write_bytecode and sys.flags.optimize==0 and isinstance(sys.pycache_prefix,str)\nassert sys.flags.isolated==1 and sys.flags.ignore_environment==1\n_qa_cache_prefix=pathlib.Path(sys.pycache_prefix)\nassert _qa_cache_prefix.is_absolute() and _qa_cache_prefix.resolve(strict=True)==_qa_cache_prefix and _qa_cache_prefix.is_dir() and _qa_cache_prefix.stat().st_uid==os.getuid() and not list(_qa_cache_prefix.iterdir())\ncache_proof=pathlib.Path(sys.argv[2])/'private-output-python-cache-proof.json'\nassert not cache_proof.exists() and not cache_proof.is_symlink()\nexecution={'stage':'private-output-verifier','argv':sys.orig_argv,'executable':sys.executable,'resolved_executable':str(pathlib.Path(sys.executable).resolve()),'interpreter_sha256':hashlib.sha256(pathlib.Path(sys.executable).resolve().read_bytes()).hexdigest(),'version':sys.version,'dont_write_bytecode':sys.dont_write_bytecode,'optimize':sys.flags.optimize,'pycache_prefix':str(_qa_cache_prefix),'isolated':sys.flags.isolated,'ignore_environment':sys.flags.ignore_environment,'before_entries':[]}\ntry:\n\n    import base64,hashlib,io,json,pathlib,sys\n    from PIL import Image\n    root,proof=map(pathlib.Path,sys.argv[1:]);cases=[]\n    def rgba(raw):\n     assert 0<len(raw)<=8*1024*1024\n     with Image.open(io.BytesIO(raw)) as im:\n      assert im.format=='PNG' and im.width*im.height<=16777216\n      im.load();return im.size,im.convert('RGBA').tobytes()\n    for prefix in ['small','large']:\n     for kind in ['PNG','project']:\n      row={'phase':prefix,'kind':kind,'status':'FAIL'}\n      try:\n       extension='png' if kind=='PNG' else 'json';path=root/'outputs'/f'{prefix}-roundtrip.{extension}'\n       assert path.is_file() and not path.is_symlink(),'Actual native Save output is absent'\n       row.update(output_bytes=path.stat().st_size,output_sha256=hashlib.sha256(path.read_bytes()).hexdigest())\n       if kind=='PNG':\n        expected=rgba((root/'fixtures'/f'{prefix}-import.png').read_bytes());actual=rgba(path.read_bytes())\n        assert actual==expected,'Native PNG import/export did not preserve every expected pixel'\n        row.update(width=actual[0][0],height=actual[0][1],every_RGBA_pixel_matches=True)\n       else:\n        assert path.stat().st_size<=32*1024*1024\n        expected=json.loads((root/'fixtures'/f'{prefix}-layers.json').read_text());actual=json.loads(path.read_text())\n        for key in ['format','version','width','height','activeLayer']:assert actual[key]==expected[key],key\n        assert len(actual['layers'])==len(expected['layers'])==2\n        layers=[]\n        for a,b in zip(actual['layers'],expected['layers']):\n         for key in ['id','name','visible','opacity']:assert a[key]==b[key],key\n         def decode(value):\n          assert isinstance(value,str) and value.startswith('data:image/png;base64,')\n          return rgba(base64.b64decode(value.split(',',1)[1],validate=True))\n         assert decode(a['png'])==decode(b['png']),'Project layer pixels differ'\n         layers.append({'id':a['id'],'name':a['name'],'visible':a['visible'],'opacity':a['opacity'],'every_RGBA_pixel_matches':True})\n        row.update(activeLayer=actual['activeLayer'],layers=layers,all_metadata_and_pixels_match=True)\n       row['status']='PASS'\n      except Exception as error:row['error']=str(error)\n      cases.append(row)\n    report={'status':'PASS_EXACT_NATIVE_ROUNDTRIP_DATA' if all(x['status']=='PASS' for x in cases) else 'FAIL_EXACT_NATIVE_ROUNDTRIP_DATA','cases':cases,'diagnostic_only':True,'validated_release_artifact':False}\n    (proof/'roundtrip-data-verification.json').write_text(json.dumps(report,indent=2)+'\\n');print(json.dumps(report));sys.exit(0 if all(x['status']=='PASS' for x in cases) else 1)\nfinally:\n after=sorted(str(p.relative_to(_qa_cache_prefix)) for p in _qa_cache_prefix.rglob('*'))\n execution.update(after_entries=after,cache_empty_before_and_after=not after)\n fd=os.open(cache_proof,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o444)\n with os.fdopen(fd,'w') as stream:\n  json.dump(execution,stream,indent=2);stream.write('\\n');stream.flush();os.fsync(stream.fileno())\n assert not after,'Private verifier cache _qa_cache_prefix changed'\n"

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['qa', 'scratch', 'evidence', 'guard-proof']: parser.add_argument('--' + name, type=pathlib.Path, required=True)
    args = parser.parse_args()
    python_guard=begin_python_guard('runner',args.guard_proof)
    guard_completed=False
    try:
        manifest_guard,normal_guard=bound_inputs(args.qa)
        provenance = json.loads((args.evidence / 'exact-app-provenance.json').read_text())
        assert provenance['status'] == 'EXACT_UNMODIFIED_VALIDATED_C10_APP_FOR_NATIVE_QA_ONLY'
        assert provenance['app_modified_or_resigned'] is False and provenance['normal_app_no_smoke_mode'] is True
        assert provenance['validated_normal_artifact_input'] is True and provenance['release_approved'] is False
        manifest=manifest_guard
        app=bound_provenance(manifest,provenance,args.scratch)
        for name, binding in manifest['qa_files'].items():
            path = args.qa / name
            assert path.is_file() and path.stat().st_size == binding['bytes'] and digest(path) == binding['sha256']
        root = args.scratch / 'owned-file-menu-data'
        helper = args.scratch / 'NativeFileMenuDiagnostic'
        execution_code = None; verifier_code = None; compilation_code = None
        problems = []; after = None; signature_code = None; native = {}; cleanup = {}
        before = json.loads((args.evidence / 'original-app-inventory.json').read_text())
        # Complete readonly app/provenance checks precede the exclusive native intent.
        spec=importlib.util.spec_from_file_location('preflight_exact_app_inventory',args.qa/'prepare_exact_app.py')
        inventory_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(inventory_module)
        assert inventory_module.inventory(app)==before,'Prepared app changed before native activation'
        pre_signed=subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],capture_output=True,timeout=60)
        assert pre_signed.returncode==0,'Prepared app signature changed before native activation'
        activation_sha=claim_native_activation(args.evidence,args.scratch,args.qa,manifest,provenance)
        execution_started = False
        try:
            assert not root.exists()
            shutil.copytree(args.qa / 'fixtures', root / 'fixtures'); (root / 'outputs').mkdir()
            compilation = subprocess.run(['/usr/bin/swiftc', '-swift-version', '5', '-O', str(args.qa / 'NativeFileMenuDiagnostic.swift'), '-o', str(helper)], text=True, capture_output=True, timeout=120)
            compilation_code = compilation.returncode
            (args.evidence / 'helper-compilation.stdout.txt').write_text(compilation.stdout)
            (args.evidence / 'helper-compilation.stderr.txt').write_text(compilation.stderr)
            assert compilation.returncode == 0, 'External helper did not compile; no app or chooser action occurred'
            environment = dict(os.environ)
            assert not any(key.startswith('ELICHIKA_') and ('SMOKE' in key or 'QA' in key) for key in environment), 'No smoke/QA environment may influence the normal app'
            with (args.evidence / 'native-driver.stdout.json').open('w') as out, (args.evidence / 'native-driver.stderr.txt').open('w') as err:
                execution_started = True
                execution = subprocess.run([str(helper), str(app), str(root), str(args.evidence / 'native')], stdout=out, stderr=err, env=environment, timeout=900)
                execution_code = execution.returncode
        except Exception as error:
            problems.append({'stage': 'compile_or_native_execution', 'type': type(error).__name__, 'error': str(error)})
        finally:
            # Ordinary NSRunningApplication termination is separately available if a
            # bounded external helper timeout prevented its in-process cleanup.
            owned = args.evidence / 'native/task-owned-app.json'
            if helper.is_file() and owned.is_file():
                try:
                    cleanup_file = args.evidence / 'outside-ordinary-cleanup.json'
                    with (args.evidence / 'outside-cleanup.stdout.txt').open('w') as out, (args.evidence / 'outside-cleanup.stderr.txt').open('w') as err:
                        subprocess.run([str(helper), '--cleanup-owned', str(owned), str(cleanup_file)], stdout=out, stderr=err, timeout=45)
                    cleanup = json.loads(cleanup_file.read_text())
                except Exception as error:
                    problems.append({'stage': 'outside_ordinary_cleanup', 'type': type(error).__name__, 'error': str(error)})
                    cleanup = {'ordinaryTerminationObserved': False, 'forceQuitUsed': False, 'identity_or_completion_unproven': True}
            else:
                cleanup = {'ordinaryTerminationObserved': not execution_started, 'forceQuitUsed': False,
                           'owned_record_present': owned.is_file(), 'native_execution_started': execution_started}
            # Every independent postcondition is attempted even when another one fails.
            try:
                private_python = app / 'Contents/Resources/runtime/arm64/python/bin/python3'
                verifier = args.scratch / 'verify_roundtrip.py'; verifier.write_text(VERIFY)
                private_environment = dict(os.environ)
                for key in list(private_environment):
                    if key.startswith('DYLD_') or key in {'PYTHONHOME', 'PYTHONPATH', 'PYTHONUSERBASE', 'VIRTUAL_ENV', 'CONDA_PREFIX'}:
                        private_environment.pop(key, None)
                with (args.evidence / 'roundtrip-check.stdout.json').open('w') as out, (args.evidence / 'roundtrip-check.stderr.txt').open('w') as err:
                    private_cache=pathlib.Path(tempfile.mkdtemp(prefix='private-output-cache-',dir=args.scratch))
                    checked = subprocess.run([str(private_python), '-I', '-B', '-X', 'pycache_prefix='+str(private_cache), str(verifier), str(root), str(args.evidence)], stdout=out, stderr=err, env=private_environment, timeout=120)
                verifier_code = checked.returncode
            except Exception as error:
                problems.append({'stage': 'read_only_output_verification', 'type': type(error).__name__, 'error': str(error)})
            try:
                spec = importlib.util.spec_from_file_location('exact_app_inventory', args.qa / 'prepare_exact_app.py')
                module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                after = module.inventory(app)
                (args.evidence / 'after-app-inventory.json').write_text(json.dumps(after, indent=2) + '\n')
            except Exception as error:
                problems.append({'stage': 'final_app_inventory', 'type': type(error).__name__, 'error': str(error)})
            try:
                signed = subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], text=True, capture_output=True, timeout=60)
                signature_code = signed.returncode
                (args.evidence / 'final-codesign.stdout.txt').write_text(signed.stdout)
                (args.evidence / 'final-codesign.stderr.txt').write_text(signed.stderr)
            except Exception as error:
                problems.append({'stage': 'final_original_signature', 'type': type(error).__name__, 'error': str(error)})
            try:
                native_path = args.evidence / 'native/native-dialog-observations.json'
                native = json.loads(native_path.read_text()) if native_path.exists() else {}
            except Exception as error:
                problems.append({'stage': 'native_outcome_parse', 'type': type(error).__name__, 'error': str(error)})
            try:
                if (root / 'outputs').is_dir(): shutil.copytree(root / 'outputs', args.evidence / 'synthetic-native-save-outputs')
            except Exception as error:
                problems.append({'stage': 'preserve_synthetic_outputs', 'type': type(error).__name__, 'error': str(error)})
            success = execution_code == 0 and verifier_code == 0 and before == after and signature_code == 0 and cleanup.get('ordinaryTerminationObserved') is True and not problems
            summary = {'status': 'PASS_ACTUAL_FILE_MENU_DIAGNOSTIC_ONLY' if success else 'FAIL_ACTUAL_FILE_MENU_DIAGNOSTIC_ONLY',
                       'source_commit': provenance['source_commit'], 'artifact_id': provenance['artifact_id'], 'outer_zip_sha256': provenance['outer_zip_sha256'],
                       'source_record_sha256':provenance['source_record_sha256'],'native_activation_intent_sha256':activation_sha,
                       'app_unchanged_bytes_links_modes': before == after, 'codesign_still_valid': signature_code == 0,
                       'compilation_exit': compilation_code, 'native_driver_exit': execution_code, 'data_verifier_exit': verifier_code,
                       'native_stage': native.get('stage'), 'native_error': native.get('error'), 'native_dialog_count': len(native.get('nativeDialogs', [])),
                       'native_cases': native.get('cases', []), 'cleanup': cleanup, 'problems': problems,
                       'tiny_and_above_1MiB_flows_separate': True, 'product_source_modified': False,
                       'normal_C7_failure_waived': False, 'client_or_release_approval': False, 'validated_release_artifact': False}
            (args.evidence / 'file-menu-diagnostic-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
            print(json.dumps(summary, indent=2))
        guard_completed=success
        return 0 if success else 1
    finally:
        finish_python_guard(python_guard,args.guard_proof,guard_completed,
            None if guard_completed else 'runner stage did not complete; preserve the original exception and evidence')

if __name__ == '__main__': sys.exit(main())

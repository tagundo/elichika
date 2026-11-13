"""Run one unchanged-app OS-dialog diagnostic and preserve failures without promotion."""
import argparse, base64, hashlib, importlib.util, io, json, os, pathlib, shutil, subprocess, sys

def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()

VERIFY = r'''
import base64,hashlib,io,json,pathlib,sys
from PIL import Image
root,proof=map(pathlib.Path,sys.argv[1:]);cases=[]
def rgba(raw):
 assert 0<len(raw)<=8*1024*1024
 with Image.open(io.BytesIO(raw)) as im:
  assert im.format=='PNG' and im.width*im.height<=16777216
  im.load();return im.size,im.convert('RGBA').tobytes()
for prefix in ['small','large']:
 for kind in ['PNG','project']:
  row={'phase':prefix,'kind':kind,'status':'FAIL'}
  try:
   extension='png' if kind=='PNG' else 'json';path=root/'outputs'/f'{prefix}-roundtrip.{extension}'
   assert path.is_file() and not path.is_symlink(),'Actual native Save output is absent'
   row.update(output_bytes=path.stat().st_size,output_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
   if kind=='PNG':
    expected=rgba((root/'fixtures'/f'{prefix}-import.png').read_bytes());actual=rgba(path.read_bytes())
    assert actual==expected,'Native PNG import/export did not preserve every expected pixel'
    row.update(width=actual[0][0],height=actual[0][1],every_RGBA_pixel_matches=True)
   else:
    assert path.stat().st_size<=32*1024*1024
    expected=json.loads((root/'fixtures'/f'{prefix}-layers.json').read_text());actual=json.loads(path.read_text())
    for key in ['format','version','width','height','activeLayer']:assert actual[key]==expected[key],key
    assert len(actual['layers'])==len(expected['layers'])==2
    layers=[]
    for a,b in zip(actual['layers'],expected['layers']):
     for key in ['id','name','visible','opacity']:assert a[key]==b[key],key
     def decode(value):
      assert isinstance(value,str) and value.startswith('data:image/png;base64,')
      return rgba(base64.b64decode(value.split(',',1)[1],validate=True))
     assert decode(a['png'])==decode(b['png']),'Project layer pixels differ'
     layers.append({'id':a['id'],'name':a['name'],'visible':a['visible'],'opacity':a['opacity'],'every_RGBA_pixel_matches':True})
    row.update(activeLayer=actual['activeLayer'],layers=layers,all_metadata_and_pixels_match=True)
   row['status']='PASS'
  except Exception as error:row['error']=str(error)
  cases.append(row)
report={'status':'PASS_EXACT_NATIVE_ROUNDTRIP_DATA' if all(x['status']=='PASS' for x in cases) else 'FAIL_EXACT_NATIVE_ROUNDTRIP_DATA','cases':cases,'diagnostic_only':True,'validated_release_artifact':False}
(proof/'roundtrip-data-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));sys.exit(0 if all(x['status']=='PASS' for x in cases) else 1)
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['qa', 'scratch', 'evidence']: parser.add_argument('--' + name, type=pathlib.Path, required=True)
    args = parser.parse_args(); provenance = json.loads((args.evidence / 'exact-app-provenance.json').read_text())
    assert provenance['status'] == 'EXACT_UNMODIFIED_C5_APP_FOR_FILE_MENU_DIAGNOSTIC_ONLY'
    assert provenance['app_modified_or_resigned'] is False and provenance['normal_app_no_smoke_mode'] is True
    app = pathlib.Path(provenance['app']); manifest = json.loads((args.qa / 'proposal-manifest.json').read_text())
    for name, binding in manifest['qa_files'].items():
        path = args.qa / name
        assert path.is_file() and path.stat().st_size == binding['bytes'] and digest(path) == binding['sha256']
    root = args.scratch / 'owned-file-menu-data'
    helper = args.scratch / 'NativeFileMenuDiagnostic'
    execution_code = None; verifier_code = None; compilation_code = None
    problems = []; after = None; signature_code = None; native = {}; cleanup = {}
    before = json.loads((args.evidence / 'original-app-inventory.json').read_text())
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
                checked = subprocess.run([str(private_python), '-I', '-B', str(verifier), str(root), str(args.evidence)], stdout=out, stderr=err, env=private_environment, timeout=120)
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
                   'app_unchanged_bytes_links_modes': before == after, 'codesign_still_valid': signature_code == 0,
                   'compilation_exit': compilation_code, 'native_driver_exit': execution_code, 'data_verifier_exit': verifier_code,
                   'native_stage': native.get('stage'), 'native_error': native.get('error'), 'native_dialog_count': len(native.get('nativeDialogs', [])),
                   'native_cases': native.get('cases', []), 'cleanup': cleanup, 'problems': problems,
                   'tiny_and_above_1MiB_flows_separate': True, 'product_source_modified': False,
                   'normal_C5_failure_waived': False, 'client_or_release_approval': False, 'validated_release_artifact': False}
        (args.evidence / 'file-menu-diagnostic-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(summary, indent=2))
    return 0 if success else 1

if __name__ == '__main__': sys.exit(main())

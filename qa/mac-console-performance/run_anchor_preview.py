import argparse,hashlib,importlib.util,json,pathlib,re,subprocess
p=argparse.ArgumentParser();p.add_argument('--qa',type=pathlib.Path,required=True);p.add_argument('--build',type=pathlib.Path,required=True);p.add_argument('--evidence',type=pathlib.Path,required=True);a=p.parse_args()
spec=importlib.util.spec_from_file_location('native_driver',a.qa/'run_performance.py');driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)
result={'status':'PENDING','prior44_reused_for_changed_source':False,'units':{},'native':{},'release_approved':False}
name='testWrappedUnicodeScrollbackSurvivesCoalescedHeadTrimming'
for label in ['C4-negative','proposed-positive']:
 command=['swift','test','--package-path',str(a.build/label/'macos'),'--scratch-path',str(a.build/label/'swift-tests')]
 if label=='C4-negative':command+=['--filter','ConsoleWrappedScrollTests']
 try:
  process=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=240)
  text=process.stdout.decode(errors='replace');(a.evidence/(label+'-swift-tests.log')).write_text(text)
  expected_case=re.search(r"Test Case .*"+name+r".* (failed|passed) \(",text)
  if label=='C4-negative':
   okay=bool(process.returncode!=0 and expected_case and expected_case.group(1)=='failed'
     and re.search(r'Executed 1 test, with [1-9][0-9]* failures? \(0 unexpected\)',text)
     and 'XCTAssertLessThanOrEqual failed' in text)
  else:
   okay=bool(process.returncode==0 and expected_case and expected_case.group(1)=='passed'
     and re.search(r'Executed 45 tests, with 0 failures \(0 unexpected\)',text))
  result['units'][label]={'expected_actual_result':okay,'exit_code':process.returncode,'test_case_outcome':expected_case.group(1) if expected_case else None,'full_suite_count_required':45 if label=='proposed-positive' else None,'log_sha256':hashlib.sha256(text.encode()).hexdigest()}
 except (OSError,subprocess.TimeoutExpired) as e:result['units'][label]={'expected_actual_result':False,'error_type':type(e).__name__}
for label in ['C4-negative','proposed-positive']:
 folder=a.evidence/label
 try:
  driver.run_case(a.build/label/'PerfProbe',a.build/label/'macos/runtime/elichika_macos.py',folder,'patched',1500,'visible','idle')
  failure=None
 except Exception as e:failure={'type':type(e).__name__,'message':str(e)}
 native_path=folder/'native-performance.json';native=json.loads(native_path.read_text()) if native_path.is_file() else {}
 doc=native.get('selection_scroll_copy',{})
 before=folder/'viewport-before.png';after=folder/'viewport-after.png'
 images=before.is_file() and after.is_file()
 same_images=images and before.read_bytes()==after.read_bytes()
 if label=='C4-negative':
  okay=bool(failure and failure['type']=='AssertionError' and failure['message']=='Actual native document selection/scroll/copy check failed'
   and native.get('status')=='MEASURED_SYNTHETIC_PROTOCOL_FIXTURE' and native.get('runtime_error_visible') is False
   and doc.get('same_selection_and_copy') is True and doc.get('tail_follows_when_already_at_bottom') is True
   and doc.get('same_visible_anchor_after_two_coalesced_batches') is False and images and not same_images)
 else:okay=bool(failure is None and doc.get('status')=='PASS' and same_images)
 result['native'][label]={'expected_actual_result':okay,'driver_failure':failure,'document_checks':doc,'viewport_png_bytes_identical':same_images,'source_variant':label,'native_probe_variant_field':'patched denotes same native-document assertions compiled on both source variants'}
okay=all(v.get('expected_actual_result') is True for group in ['units','native'] for v in result[group].values()) and len(result['units'])==len(result['native'])==2
result['status']='PASS_TARGETED_C4_NEGATIVE_PROPOSAL_POSITIVE_AND_FRESH45' if okay else 'FAIL_TARGETED_PREVIEW'
(a.evidence/'anchor-preview-summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'status':result['status'],'unit_results':{k:v.get('expected_actual_result') for k,v in result['units'].items()},'native_results':{k:v.get('expected_actual_result') for k,v in result['native'].items()}},indent=2));raise SystemExit(0 if okay else 1)

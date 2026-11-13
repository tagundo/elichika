import argparse,json,os,pathlib,re,subprocess,hashlib,importlib.util,shutil
p=argparse.ArgumentParser();p.add_argument('--build',type=pathlib.Path,required=True);p.add_argument('--evidence',type=pathlib.Path,required=True);p.add_argument('--qa',type=pathlib.Path,required=True);a=p.parse_args()
spec=importlib.util.spec_from_file_location('control_fixture',a.qa/'run_performance.py');fixture_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture_module)
name='testWrappedUnicodeScrollbackSurvivesCoalescedHeadTrimming'
def run(label,opt,state):
 case=f'{label}-{opt}-{state}';env=dict(os.environ);env['ELICHIKA_QA_UNIT_STATE']=state
 command=['swift','test','--verbose','--configuration',opt,'--package-path',str(a.build/label/'macos'),'--scratch-path',str(a.build/label/('unit-diagnostic-'+opt)),'--filter','ConsoleWrappedScrollTests']
 print('BEGIN',case,flush=True)
 fixture=None;private=None
 if state=='ready':
  private=a.evidence/('private-'+case);private.mkdir(mode=0o700)
  fixture=fixture_module.Fixture(a.build/label/'macos/runtime/elichika_macos.py',private,0)
  ready=private/'ready.json';ready.write_text(json.dumps(fixture.ready()));ready.chmod(0o600)
  env['ELICHIKA_QA_UNIT_READY_FILE']=str(ready)
 try:
  proc=subprocess.run(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=240);text=proc.stdout.decode(errors='replace')
 except subprocess.TimeoutExpired as e:
  text=(e.stdout or b'').decode(errors='replace');(a.evidence/(case+'.log')).write_text(text);return {'case':case,'source_variant':label,'optimization':opt,'state_case':state,'harness_valid':False,'error':'Swift test bounded timeout'}
 finally:
  if fixture:fixture.close()
  if private:shutil.rmtree(private)
 (a.evidence/(case+'.log')).write_text(text)
 witnesses=[]
 for line in text.splitlines():
  if line.startswith('QA_UNIT_WITNESS '):witnesses.append(json.loads(line.removeprefix('QA_UNIT_WITNESS ')))
 phases={x['phase']:x for x in witnesses};named=re.search(r'Test Case .*'+name+r'.* (failed|passed) \(',text)
 unexpected=re.search(r'Executed 1 test, with ([0-9]+) failures? \(0 unexpected\)',text)
 valid=bool(named and unexpected and len(witnesses)==3 and set(phases)=={'before','after','tail'} and all(x['optimization']==opt and x['state_case']==state and x['server_running']==(state=='ready') and x['server_url_row_present']==(state=='ready') and x['cache_value_available']==(state=='ready') and x['has_job_row'] is False for x in witnesses))
 observed={}
 if valid:
  before,after=phases['before'],phases['after'];head=after['head_utf16']-before['head_utf16']
  observed={'head_trim_utf16':head,'character_delta':abs(after['visible_character']-(before['visible_character']-head)),'pixel_offset_delta':abs(after['glyph_offset_y']-before['glyph_offset_y']),'viewport_dimensions_preserved':(before['viewport_width'],before['viewport_height'])==(after['viewport_width'],after['viewport_height']),'pixels_match':after['pixels_match_before'],'copy_matches':after['copied_matches_selection_before'],'tail_follows':phases['tail']['tail_at_bottom']}
 reproduced=bool(valid and proc.returncode!=0 and named.group(1)=='failed' and 'XCTAssertLessThanOrEqual failed' in text and observed['head_trim_utf16']==40720 and (observed['character_delta']>1 or observed['pixel_offset_delta']>1.5) and observed['viewport_dimensions_preserved'] is True and observed['pixels_match'] is False and observed['copy_matches'] is True and observed['tail_follows'] is True)
 positive=bool(valid and proc.returncode==0 and named.group(1)=='passed' and observed['head_trim_utf16']==40720 and observed['character_delta']<=1 and observed['pixel_offset_delta']<=1.5 and observed['viewport_dimensions_preserved'] is True and observed['pixels_match'] is True and observed['copy_matches'] is True and observed['tail_follows'] is True)
 result={'case':case,'source_variant':label,'optimization':opt,'state_case':state,'command':command,'compiler_Onone_present':bool(re.search(r' -Onone(?: |$)',text)),'compiler_O_present':bool(re.search(r' -O(?: |$)',text)),'harness_valid':valid,'exit_code':proc.returncode,'named_test_result':named.group(1) if named else None,'reproduced_anchor_regression':reproduced,'positive_all_checks_pass':positive,'observed':observed,'witnesses':witnesses,'log_sha256':hashlib.sha256(text.encode()).hexdigest()};print('RESULT',case,json.dumps({k:result[k] for k in ['harness_valid','reproduced_anchor_regression','positive_all_checks_pass']}),flush=True);return result
negative=[run('C4-negative',opt,state) for opt in ['debug','release'] for state in ['default','ready']]
# Predeclared preference: a reproduction under the normal debug test mode and
# actual ready state gives the most useful persistent regression fixture.
rank=[('debug','ready'),('debug','default'),('release','ready'),('release','default')]
chosen=next((x for opt,state in rank for x in negative if x['optimization']==opt and x['state_case']==state and x['reproduced_anchor_regression']),None)
positive=run('proposed-positive',chosen['optimization'],chosen['state_case']) if chosen else None
ok=all(x['harness_valid'] for x in negative) and positive is not None and positive['positive_all_checks_pass'] is True
summary={'status':'FOUND_EXPLAINED_UNIT_NEGATIVE_AND_MATCHED_PROPOSAL_PASS' if ok else 'DIAGNOSTIC_COMPLETED_NO_ACCEPTABLE_UNIT_PROOF','C4_four_factor_cases':negative,'matched_proposal':positive,'selected_case':chosen['case'] if chosen else None,'prior45_reused_as_new_fixture_proof':False,'production_app_delta_unchanged':True,'production_files_modified':False,'release_approved':False};(a.evidence/'unit-factor-diagnostic-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(summary['status'],flush=True);raise SystemExit(0 if ok else 1)

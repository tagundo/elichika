/* Focused R6 structural mocks. No device, observer injection or game is run. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/unity_ui.js','utf8');
const chooseStart=source.indexOf('  function normalize(value)'),chooseEnd=source.indexOf('  function initialize()',chooseStart);
const musicStart=source.indexOf('function observeExistingMusicRowsAndMvTabs('),musicEnd=source.indexOf('\n/* QA-ONLY,',musicStart);
assert(chooseStart>=0&&chooseEnd>chooseStart&&musicStart>=0&&musicEnd>musicStart);
const chooseSource=source.slice(chooseStart,chooseEnd),musicSource=source.slice(musicStart,musicEnd);

function node(changes={}) {
  return Object.assign({id:'target',kind:'text',name:'MvBtnDownloadLabel',path:'Observed/Download/Label',
    text:'Download',label:'Download',active:true,visible:true,enabled:true,interactable:null,
    groupsInteractable:true,blocksRaycasts:true,bounds:{left:10,top:10,right:90,bottom:30},
    visibleBounds:{left:10,top:10,right:90,bottom:30},center:{x:50,y:20},
    hit:{available:true,hittable:true,hits:1,firstPath:'Observed/Download/Label'}},changes);
}
function chooseFixture(nodes,selection=[]) {
  const observed={timestampMs:123456,screen:{width:720,height:1280,scene:'LiveMusicSelect',frame:99},nodes,
    features:{mv:{musicSelection:selection}},truncated:false,enumeratedObjects:31,
    hitTest:{available:true,error:null},diagnostics:[]};
  const options=[];
  const context={snapshot:value=>{options.push(value);return observed;}};
  vm.createContext(context);vm.runInContext(chooseSource,context,{filename:'R6-choose-structural-mock.js'});
  return {observed,options,pick:query=>context.choose(query)};
}
function refusal(fixture,query) {
  try{fixture.pick(query);}catch(error){return JSON.parse(error.message);}
  assert.fail('Expected a structured semantic refusal');
}
function plain(value){return JSON.parse(JSON.stringify(value));}
let passed=0;
function test(name,fn){fn();passed++;process.stdout.write('PASS '+name+'\n');}

test('successful pick retains unchanged one-snapshot options and same selection witness',()=>{
  const selection=[{active:true,currentSelectedCellVO:{liveMasterId:12074},decidedCellVO:{liveMasterId:12096}}];
  const f=chooseFixture([node()],selection);
  const result=f.pick({id:'target',kind:'text',path:'Observed/Download/Label',text:'Download',requireHitTest:true,
    maxNodes:1500,extraTypes:['Host.MockText'],allSelectables:true,customButtons:false,numericTestId:'123'});
  assert.strictEqual(f.options.length,1);assert.strictEqual(result.musicSelection,selection);
  assert.strictEqual(result.target,f.observed.nodes[0]);assert.strictEqual(result.timestampMs,123456);
  assert.deepStrictEqual(plain(f.options[0]),{maxNodes:1500,extraTypes:['Host.MockText'],allSelectables:true,
    raycastText:true,customButtons:false,numericTestId:'123'});
});

test('unavailable pick retains prefilter flags and reasons for every decisive selector or actionability rejection',()=>{
  const query={id:'target',kind:'text',path:'Observed/Download/Label',text:'Download',requireHitTest:true};
  const variants=[
    [{visible:false},'not-visible'],[{enabled:false},'not-enabled'],[{interactable:false},'not-interactable'],
    [{groupsInteractable:false},'groups-not-interactable'],[{blocksRaycasts:false},'raycasts-not-blocked'],
    [{kind:'button'},'kind-mismatch'],[{id:'other-instance'},'id-mismatch'],
    [{path:'Observed/Other/Label'},'path-mismatch'],[{text:'Other',label:'Other'},'text-mismatch'],
    [{hit:{available:true,hittable:false}},'raycast-rejected'],
    [{hit:{available:false,hittable:null}},'required-hit-test-failed']];
  for(const [change,reason] of variants){
    const selection=[{active:true,currentSelectedCellVO:{liveMasterId:12074},decidedCellVO:{liveMasterId:null}}];
    const f=chooseFixture([node(change)],selection),error=refusal(f,query);
    assert.strictEqual(f.options.length,1);assert.strictEqual(error.error,'No active semantic UI target');
    assert.strictEqual(error.errorCode,'SEMANTIC_TARGET_UNAVAILABLE');assert.strictEqual(error.candidateCount,1);
    assert.deepStrictEqual(error.musicSelection,selection);assert(error.candidates[0].rejectedBy.includes(reason),reason);
    for(const key of ['active','visible','enabled','interactable','groupsInteractable','blocksRaycasts','hit'])
      assert(Object.prototype.hasOwnProperty.call(error.candidates[0],key),key);
    assert.strictEqual(error.timestampMs,123456);assert.strictEqual(error.snapshot.nodeCount,1);
    assert.strictEqual(error.snapshot.enumeratedObjects,31);assert.strictEqual(error.snapshot.truncated,false);
    assert.strictEqual(error.snapshot.includeInactive,false);assert.strictEqual(error.snapshot.effectiveMaxNodes,1000);
  }
});

test('diagnostic candidates are bounded and kind alone never includes unrelated nodes',()=>{
  const wanted=Array.from({length:20},(_,index)=>node({id:'candidate-'+index,visible:false,text:'x'.repeat(500),label:'x'.repeat(500)}));
  const unrelated=Array.from({length:4},(_,index)=>node({id:'unrelated-'+index,path:'Elsewhere/'+index,text:'Elsewhere',label:'Elsewhere'}));
  const f=chooseFixture(wanted.concat(unrelated)),error=refusal(f,{kind:'text',path:'Observed/Download/Label',requireHitTest:true,maxNodes:9000});
  assert.strictEqual(error.candidateCount,20);assert.strictEqual(error.candidateLimit,16);
  assert.strictEqual(error.candidatesTruncated,true);assert.strictEqual(error.candidates.length,16);
  assert.strictEqual(error.candidates[0].text.length,160);assert.strictEqual(error.candidates[0].label.length,160);
  assert(error.candidates.every(value=>value.matchedBy.includes('path')&&!value.id.startsWith('unrelated-')));
  assert.strictEqual(error.snapshot.options.maxNodes,9000);assert.strictEqual(error.snapshot.effectiveMaxNodes,3000);
  assert.strictEqual(error.matchCount,0);assert.strictEqual(error.uniqueMatchCount,0);
});

test('ambiguity remains a refusal with its exact legacy message and same-snapshot witnesses',()=>{
  const selection=[{active:true,currentSelectedCellVO:{liveMasterId:12074},decidedCellVO:{liveMasterId:12096}}];
  const f=chooseFixture([node({id:'first'}),node({id:'second',path:'Other/Download/Label'})],selection);
  const error=refusal(f,{kind:'text',text:'Download',requireHitTest:true});
  assert.strictEqual(f.options.length,1);assert.strictEqual(error.error,'Ambiguous active semantic UI targets');
  assert.strictEqual(error.errorCode,'SEMANTIC_TARGET_AMBIGUOUS');assert.strictEqual(error.matches.length,2);
  assert.strictEqual(error.candidateCount,2);assert.strictEqual(error.matchCount,2);assert.strictEqual(error.uniqueMatchCount,2);
  assert(error.candidates.every(value=>value.rejectedBy.length===0));assert.deepStrictEqual(error.musicSelection,selection);
});

test('missing identity reports only this enumeration and keeps successful physical-action deduplication',()=>{
  const absent=chooseFixture([node({id:'another',path:'Other/Label',text:'Other',label:'Other'})]);
  const error=refusal(absent,{id:'missing',kind:'text',path:'Absent/Label',text:'Absent',requireHitTest:true});
  assert.strictEqual(error.candidateCount,0);assert.strictEqual(error.candidatesTruncated,false);assert.deepStrictEqual(error.candidates,[]);
  const action={id:'one-physical-action',path:'Action/Button'};
  const dedup=chooseFixture([node({id:'caption',action}),node({id:'button',kind:'button',action})]);
  const result=dedup.pick({text:'Download',requireHitTest:true});
  assert.strictEqual(result.target.id,'button');assert.strictEqual(dedup.options.length,1);
});

test('controller observation reads both exact existing VO fields independently without readiness inference',()=>{
  const fieldReads=[],backingReads=[];
  const vo=(id,playable)=>Object.freeze({type:'LLAS.DM.LiveMusicSelectDM+CellVO',fields:Object.freeze({
    '<LiveMasterId>k__BackingField':id,'<IsPlayable>k__BackingField':playable})});
  const controller=(id,current,decided,active=true)=>Object.freeze({id,active,path:'Controller/'+id,
    fields:Object.freeze({currentSelectedCellVO:current,decidedCellVO:decided})});
  const controllers=[controller('one',vo(12074,true),vo(12096,false)),controller('two',null,vo(12074,true)),
    controller('inactive',vo(1,true),vo(2,true),false)];
  const context={findClass:name=>name,allOfType:name=>{
      const values=name==='LLAS.Scene.LiveMusicSelect.LiveMusicSelectController'?controllers:[];
      return {length:values.length,get:index=>values[index]};},
    exists:value=>value!==null&&value!==undefined,active:value=>({active:value.active}),
    mvExistingComponentInfo:value=>({id:value.id,path:value.path,active:value.active}),
    mvReadField:(value,key)=>{assert(['currentSelectedCellVO','decidedCellVO'].includes(key));fieldReads.push(key);return value.fields[key]??null;},
    mvBacking:(value,key)=>{assert(['LiveMasterId','IsPlayable'].includes(key));backingReads.push(key);return value?value.fields['<'+key+'>k__BackingField']??null:null;},
    mvNumber:value=>value===null||value===undefined?null:Number(value),fullType:value=>value.type,
    call:()=>assert.fail('No method invocation is allowed'),mvUiTarget:()=>assert.fail('No input target construction is needed')};
  vm.createContext(context);vm.runInContext(musicSource,context,{filename:'R6-controller-structural-mock.js'});
  const result=plain(context.observeExistingMusicRowsAndMvTabs({},{}));
  assert.strictEqual(result.musicSelection.length,2);const [one,two]=result.musicSelection;
  assert.deepStrictEqual(one.currentSelectedCellVO,{liveMasterId:12074,isPlayable:true,voClass:'LLAS.DM.LiveMusicSelectDM+CellVO'});
  assert.deepStrictEqual(one.decidedCellVO,{liveMasterId:12096,isPlayable:false,voClass:'LLAS.DM.LiveMusicSelectDM+CellVO'});
  assert.deepStrictEqual(two.currentSelectedCellVO,{liveMasterId:null,isPlayable:null,voClass:null});
  assert.strictEqual(two.decidedCellVO.liveMasterId,12074);
  assert.deepStrictEqual(fieldReads,['currentSelectedCellVO','decidedCellVO','currentSelectedCellVO','decidedCellVO']);
  assert.strictEqual(backingReads.length,8);
  assert(result.musicSelection.every(row=>!('ready'in row)&&!('downloaded'in row)&&!('isReady'in row)));
});
process.stdout.write(JSON.stringify({passed,scope:'Focused R6 structural mocks only; no runtime or feature approval'})+'\n');

/* Focused R8 host structural mocks only. Do not run before SOURCE READY. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/unity_ui.js','utf8');
const tests=[];
function test(name,fn){tests.push({name,fn});}
function plain(value){return JSON.parse(JSON.stringify(value));}
function point(x,y,z=0){return {x,y,z};}
function geometry(changes={}) {
  return Object.assign({position:point(10,20,3),size:{x:4,y:6},lossyScale:point(2,.5,1),
    pivot:{x:.25,y:.75}},changes);
}
function cell(ordinal,changes={}) {
  return Object.assign({ordinal,index:ordinal,positionIndex:ordinal,rectId:'rect-'+ordinal,cellId:'cell-'+ordinal,
    activeSelf:true,activeInHierarchy:true,liveMasterId:10000+ordinal,
    nativeBounds:{min:point(0,0,0),max:point(10,10,0)}},changes);
}
function orderedCells(count,changes={}) {
  return Array.from({length:count},(_,ordinal)=>cell(ordinal,changes));
}
function forbidden(name){return ()=>assert.fail('Forbidden runtime action: '+name);}
const forbiddenRuntime={
  callback:forbidden('callback'),setField:forbidden('field setter'),
  cameraMain:forbidden('Camera.main'),setActive:forbidden('SetActive'),
  select:forbidden('selection callback')};

function functionSource(name) {
  const start=source.indexOf('function '+name+'(');
  assert(start>=0,'Missing production function '+name);
  const body=source.indexOf('{',start);let depth=0,quote=null,lineComment=false,blockComment=false;
  for(let index=body;index<source.length;index++){
    const current=source[index],next=source[index+1];
    if(lineComment){if(current==='\n')lineComment=false;continue;}
    if(blockComment){if(current==='*'&&next==='/'){blockComment=false;index++;}continue;}
    if(quote){if(current==='\\'){index++;continue;}if(current===quote)quote=null;continue;}
    if(current==='/'&&next==='/'){lineComment=true;index++;continue;}
    if(current==='/'&&next==='*'){blockComment=true;index++;continue;}
    if(current==='"'||current==="'"||current==='`'){quote=current;continue;}
    if(current==='{')depth++;
    if(current==='}'&&--depth===0)return source.slice(start,index+1);
  }
  assert.fail('Unclosed production function '+name);
}
const cameraReads=[];
const nativeNull={isNull:()=>true};
const context={Math,Number,Object,Array,JSON,
  exists:value=>value!==null&&value!==undefined&&!(typeof value.isNull==='function'&&value.isNull()),
  nullObject:()=>nativeNull,
  instanceId:value=>value.id,transform:value=>value.path,hierarchy:value=>value,
  fullType:value=>value.type||'Host.Mock',
  call:(object,name)=>{
    cameraReads.push(name);assert.strictEqual(name,'get_eventCamera','No Camera.main or callback may be invoked');
    if(object.fail)throw new Error('host-only event-camera getter failure');return object.eventCamera;
  },
  maybe:(object,name,fallback)=>{
    try{return context.call(object,name);}catch(error){return fallback;}
  },
  runtime:{camera:{method:forbidden('Camera.main')}},...forbiddenRuntime};
vm.createContext(context);
const nativeNames=[...source.matchAll(/function (nativeMusic[A-Za-z0-9_]*)\s*\(/g)].map(match=>match[1]);
assert(nativeNames.length>0,'Await nativeMusic production helpers and SOURCE READY before running');
vm.runInContext([...new Set(nativeNames)].map(functionSource).join('\n'),context,{filename:'R8-native-hit-structural-mock.js'});
const api=context;

test('native bounds preserve signed float32 operations and exact three-dimensional containment',()=>{
  const g=geometry();
  assert.deepStrictEqual(plain(api.nativeMusicBounds(g.position,g.size,g.lossyScale,g.pivot)),
    {min:point(8,17.75,3),max:point(16,20.75,3)});
  g.lossyScale=point(-2,-.5,1);
  const negative=plain(api.nativeMusicBounds(g.position,g.size,g.lossyScale,g.pivot));
  assert.deepStrictEqual(negative,{min:point(12,22.25,3),max:point(4,19.25,3)});
  assert.strictEqual(api.nativeMusicContains(negative,point(8,20,3)),false,'Do not abs or normalize inverted axes');
  assert.deepStrictEqual(plain(api.nativeMusicBounds(point(16777216,0,0),{x:2,y:2},point(1,1,1),{x:.25,y:.5})),
    {min:point(16777216,-1,0),max:point(16777218,1,0)});
  const rounded=api.nativeMusicBounds(point(1,1,0),{x:.1,y:.1},point(3,3,1),{x:.5,y:.5});
  assert.strictEqual(rounded.min.x,.8500000238418579);assert.strictEqual(rounded.max.x,1.149999976158142);
  const bounds={min:point(8,17.75,3),max:point(16,20.75,3)};
  assert.strictEqual(api.nativeMusicContains(bounds,point(8,17.75,3)),true);
  assert.strictEqual(api.nativeMusicContains(bounds,point(16,20.75,3)),true);
  for(const value of [point(7.999,20,3),point(16.001,20,3),point(10,20,3.000000238418579),point(10,20,2.999999761581421)])
    assert.strictEqual(api.nativeMusicContains(bounds,value),false);
});

test('complete ordered native list admits 512 entries and refuses bad bounds before reading',()=>{
  let reads=0;const entries=orderedCells(512);
  const complete=api.nativeMusicBoundedCells(512,512,index=>{reads++;return entries[index];});
  assert.strictEqual(complete.complete,true);assert.strictEqual(complete.limit,512);assert.strictEqual(reads,512);
  assert.deepStrictEqual(plain(complete.entries).map(value=>value.ordinal),Array.from({length:512},(_,index)=>index));
  for(const [size,capacity] of [[513,513],[3,2],[-1,10],[1.5,2],[NaN,2],[2,Infinity]]){
    reads=0;const result=api.nativeMusicBoundedCells(size,capacity,()=>{reads++;return cell(0);});
    assert.strictEqual(result.complete,false);assert.strictEqual(reads,0,'Invalid list metadata must refuse before enumeration');
    assert.strictEqual(result.limit,512);assert.strictEqual(typeof result.reason,'string');
  }
});

test('an unreadable inactive native entry or read exception refuses the whole list',()=>{
  let reads=0;const entries=[cell(0),cell(1,{activeInHierarchy:false,nativeBounds:null}),cell(2)];
  const result=api.nativeMusicBoundedCells(3,3,index=>{reads++;return entries[index];});
  assert.strictEqual(result.complete,false);assert(reads>=2,'Inactive geometry cannot be skipped');
  const thrown=api.nativeMusicBoundedCells(3,3,index=>{if(index===1)throw new Error('host-only unreadable entry');return cell(index);});
  assert.strictEqual(thrown.complete,false);assert.strictEqual(typeof thrown.reason,'string');
});

test('storage-order first-containing match includes inactive entries and never falls through',()=>{
  const first=cell(0,{activeInHierarchy:false}),intended=cell(1),entries=[first,intended],world=point(5,5,0);
  assert.strictEqual(api.nativeMusicFirstContaining(entries,world),first);
  const refused=api.nativeMusicScan(entries,intended,world);
  assert.strictEqual(refused.qualified,false);assert.deepStrictEqual(plain(refused.firstContaining),plain(api.nativeMusicCellIdentity(first)));
  assert.strictEqual(typeof refused.reason,'string');
  const reordered=[intended,first];assert.strictEqual(api.nativeMusicFirstContaining(reordered,world),intended);
  assert.strictEqual(api.nativeMusicScan(reordered,intended,world).qualified,true);
  assert.strictEqual(api.nativeMusicFirstContaining(entries,point(11,5,0)),null);
});

test('native scan requires every intended identity field and active first match',()=>{
  const first=cell(7),world=point(5,5,0);
  assert.strictEqual(api.nativeMusicScan([first],first,world).qualified,true);
  for(const [key,value] of [['ordinal',8],['rectId','other-rect'],['cellId','other-cell'],['liveMasterId',12074],['index',8],['positionIndex',8]]){
    const intended=Object.assign({},first,{[key]:value});
    assert.strictEqual(api.nativeMusicScan([first],intended,world).qualified,false,key);
  }
  assert.strictEqual(api.nativeMusicScan([cell(7,{activeInHierarchy:false})],first,world).qualified,false);
});

function eventModule(camera,options={}) {
  return {method:(name,arity)=>{
    cameraReads.push(name);assert.strictEqual(name,'get_eventCamera');assert.strictEqual(arity,0);
    return {class:{namespace:options.namespace||'UnityEngine.EventSystems'},invoke:()=>{
      if(options.onInvoke)options.onInvoke();
      if(options.fail)throw new Error('host-only event-camera getter failure');return camera;
    }};
  }};
}
test('event camera distinguishes resolved null from missing or failing getters without camera fallback',()=>{
  cameraReads.length=0;const camera={id:'camera-1',path:'Observed/EventCamera'};
  const resolved=api.nativeMusicEventCamera(eventModule(camera));
  assert.strictEqual(resolved.proof.resolved,true);assert.strictEqual(resolved.proof.isNull,false);
  assert.strictEqual(resolved.camera,camera);assert.strictEqual(String(resolved.proof.id),'camera-1');
  assert.strictEqual(resolved.proof.path,'Observed/EventCamera');
  const noModule=api.nativeMusicEventCamera(null),nullCamera=api.nativeMusicEventCamera(eventModule(null));
  assert.strictEqual(noModule.proof.resolved,false);assert(noModule.proof.error);assert.strictEqual(noModule.camera,null);
  assert.strictEqual(nullCamera.proof.resolved,true);assert.strictEqual(nullCamera.proof.isNull,true);assert.strictEqual(nullCamera.camera,nativeNull);
  const failed=api.nativeMusicEventCamera(eventModule(null,{fail:true}));
  assert.strictEqual(failed.proof.resolved,false);assert.strictEqual(failed.camera,null);assert(failed.proof.error);
  let invoked=false;const untrusted=api.nativeMusicEventCamera(eventModule(null,{namespace:'LLAS',onInvoke:()=>{invoked=true;}}));
  assert.strictEqual(untrusted.proof.resolved,false);assert.strictEqual(invoked,false,'A game getter must never be invoked');
  assert(cameraReads.every(name=>name==='get_eventCamera'));
});

test('current first raycast must resolve to the owned Unity drag handler and its rectangle',()=>{
  const camera={id:'event-camera',path:'Camera'},proxyGo={id:'proxy-go',path:'Scroll/Proxy'},proxy={go:proxyGo};
  const dragRect={id:'drag-rect'},owner={proxy},hit={id:'first-graphic'},handlerType={id:'IDragHandler'},calls=[];
  let drag=Object.assign({rect:dragRect},proxyGo),missingMetadata=false;
  context.gameObject=value=>value.go||value;
  context.component=(value,type)=>{assert.strictEqual(type,context.runtime.rectTransform);return value.rect;};
  context.runtime.rectTransform={id:'RectTransform'};
  context.findClass=name=>{
    if(missingMetadata)return null;
    if(name==='UnityEngine.EventSystems.IDragHandler')return handlerType;
    assert.strictEqual(name,'UnityEngine.EventSystems.ExecuteEvents');
    return {method:(name,arity)=>{
      assert.strictEqual(name,'GetEventHandler');assert.strictEqual(arity,1);
      return {inflate:type=>{assert.strictEqual(type,handlerType);return {invoke:value=>{calls.push('GetEventHandler');assert.strictEqual(value,hit);return drag;}};}};
    }};
  };
  const originalRect=context.nativeMusicRect;context.nativeMusicRect=value=>{assert.strictEqual(value,dragRect);return {rectId:'drag-rect',nativeBounds:cell(0).nativeBounds};};
  let query={proof:{available:true},hit,module:eventModule(camera)};
  const raycaster={inspect:()=>query},screen={width:720,height:1280};
  try{
    assert.strictEqual(api.nativeMusicRaycast(screen,point(50,50),raycaster,owner).qualified,true);
    drag={id:'other-drag',path:'Other',rect:dragRect};
    assert.strictEqual(api.nativeMusicRaycast(screen,point(50,50),raycaster,owner).qualified,false);
    drag=Object.assign({},proxyGo);
    assert.strictEqual(api.nativeMusicRaycast(screen,point(50,50),raycaster,owner).qualified,false);
    drag=Object.assign({rect:dragRect},proxyGo);query={proof:{available:true},hit,module:eventModule(null,{fail:true})};
    const before=calls.length;assert.strictEqual(api.nativeMusicRaycast(screen,point(50,50),raycaster,owner).qualified,false);assert.strictEqual(calls.length,before);
    query={proof:{available:true},hit,module:null};
    assert.strictEqual(api.nativeMusicRaycast(screen,point(50,50),raycaster,owner).qualified,false);
    query={proof:{available:true},hit,module:eventModule(camera)};missingMetadata=true;
    assert.strictEqual(api.nativeMusicRaycast(screen,point(50,50),raycaster,owner).qualified,false);
  }finally{context.nativeMusicRect=originalRect;}
});

test('native hit orchestrates integer-point conversion before first scan and refuses incomplete prospective proofs',()=>{
  const keys=['nativeMusicRaycast','nativeMusicViewport','nativeMusicWorldPoint','nativeMusicScan',
    'Memory','Il2Cpp','runtime','field','active','text','maybe'];
  const original=Object.fromEntries(keys.map(key=>[key,context[key]]));
  const screen={width:720,height:1280,scene:'LiveMusicSelect',frame:123},viewport={left:0,top:0,right:100,bottom:100};
  const camera={id:'owned-event-camera',path:'Camera'},drag={id:'owned-drag',path:'Scroll/Proxy'},
    dragRect={id:'owned-drag-rect'},module={id:'owned-raycaster'},view={id:'owned-view'},
    proxy={id:'owned-proxy',path:'Owned/Scroll/Proxy',active:true,enabled:true};
  const entry=cell(0,{cellId:'typed-row',liveMasterId:12074,isPlayable:true});
  const owner={view,proxy,geometry:{visibleBounds:viewport},proof:{
    managedCells:{complete:true,entries:[entry]},modelState:{selectedCellIndex:0,moveToCellIndex:0},
    storedProxyState:{scope:'STORED_STATE_NOT_CURRENT_INPUT_EVENT',isDragging:false},transition:{id:'owned-transition'},
    ownership:{viewId:view.id,modelId:'owned-model',
      inputProxyId:proxy.id,inputProxyGameObjectId:drag.id,transitionId:'owned-transition'}}};
  const row={id:'typed-row',liveMasterId:12074,target:{id:'row-graphic',center:{x:40,y:40}}},contexts={owners:[owner]};
  const state={nativeMusicSelection:{complete:true},musicSelection:[{active:true,
    currentSelectedCellVO:{liveMasterId:12074},decidedCellVO:{liveMasterId:12096}}]},events=[];let mode='qualified';
  const cameraProof={resolved:true,isNull:false,id:camera.id,path:camera.path,error:null};
  class OwnedValue {
    constructor(storage,type){assert.strictEqual(storage.owned,true);assert.strictEqual(type,'host-vector3');this.storage=storage;}
    field(axis){const storage=this.storage;return {get value(){return storage.values[axis];},set value(value){storage.values[axis]=value;}};}
  }
  try{
    context.Memory={alloc:bytes=>{assert.strictEqual(bytes,12);return {owned:true,values:{}};}};
    context.Il2Cpp={ValueType:OwnedValue};
    context.runtime=Object.assign({},original.runtime,{vector3:{valueTypeSize:12,type:'host-vector3'},
      rectUtility:{method:(name,arity)=>{
        assert.strictEqual(name,'WorldToScreenPoint');assert.strictEqual(arity,2);
        return {invoke:(usedCamera,value)=>{
          assert.strictEqual(usedCamera,camera);assert.deepStrictEqual(value.storage.values,point(5,5,0));
          events.push({kind:'project'});return {x:50.49,y:1230.49};
        }};
      }}});
    context.field=(value,axis)=>value[axis];
    context.active=value=>({active:value.active===true,enabled:value.enabled===true});
    context.text=value=>String(value||'');
    context.maybe=(value,name)=>{assert.strictEqual(value,proxy);assert.strictEqual(name,'get_name');return 'OwnedInputProxy';};
    context.nativeMusicRaycast=(usedScreen,point,raycaster,usedOwner)=>{
      assert.strictEqual(usedScreen,screen);assert.strictEqual(usedOwner,owner);
      events.push({kind:'raycast',point:plain(point)});
      const proof={available:true,hits:1,firstName:'Title',firstPath:'Owned/Title',dragRect:{rectId:dragRect.id}};
      if(mode==='camera-unresolved')return {qualified:false,reason:'Current event camera could not be resolved',proof};
      return {qualified:true,proof,camera,cameraProof,drag,rect:dragRect,module};
    };
    context.nativeMusicViewport=(usedView,usedScreen,usedCamera)=>{
      assert.strictEqual(usedView,view);assert.strictEqual(usedScreen,screen);assert.strictEqual(usedCamera,camera);
      return {visible:true,groupsInteractable:true,blocksRaycasts:true,visibleBounds:viewport};
    };
    context.nativeMusicWorldPoint=(usedRect,usedCamera,adbPoint,usedScreen)=>{
      assert.strictEqual(usedRect,dragRect);assert.strictEqual(usedCamera,camera);assert.strictEqual(usedScreen,screen);
      assert.deepStrictEqual(plain(adbPoint),{x:50,y:50});
      assert(Number.isInteger(adbPoint.x)&&Number.isInteger(adbPoint.y));events.push({kind:'convert',point:plain(adbPoint)});
      return {converted:mode!=='conversion-false',point:point(5,5,0),scope:'OBSERVER_OWNED_OUT_STORAGE'};
    };
    context.nativeMusicScan=(entries,intended,world)=>{
      assert(events.some(event=>event.kind==='convert'),'World conversion must precede the first native scan');
      assert.strictEqual(entries,owner.proof.managedCells.entries);assert.strictEqual(intended,entry);
      assert.deepStrictEqual(plain(world),point(5,5,0));events.push({kind:'scan'});
      return original.nativeMusicScan(entries,intended,world);
    };
    const qualified=api.nativeMusicHit(screen,state,contexts,row,{});
    assert.strictEqual(qualified.proof.qualified,true);assert.strictEqual(qualified.target.id,proxy.id);
    assert.deepStrictEqual(plain(qualified.target.center),{x:50,y:50});assert.strictEqual(qualified.target.bounds,viewport);
    assert.strictEqual(qualified.target.visibleBounds,viewport);assert.strictEqual(qualified.target.hit.hittable,true);
    assert.strictEqual(qualified.proof.intendedLiveMasterId,12074);
    assert.strictEqual(qualified.proof.nativeStateBefore.frame,123);
    assert.strictEqual(qualified.proof.nativeStateBefore.scope,'READ_ONLY_STORED_STATE_NOT_CURRENT_INPUT_EVENT');
    assert.strictEqual(qualified.proof.nativeStateBefore.modelState,owner.proof.modelState);
    assert.strictEqual(qualified.proof.nativeStateBefore.controllerSelection,state.musicSelection);
    assert.deepStrictEqual(plain(qualified.proof.firstContaining),plain(api.nativeMusicCellIdentity(entry)));
    assert.deepStrictEqual(plain(qualified.proof.intended),plain(api.nativeMusicCellIdentity(entry)));
    assert(events.findIndex(event=>event.kind==='convert')<events.findIndex(event=>event.kind==='scan'));
    assert.strictEqual(Object.prototype.hasOwnProperty.call(qualified,'input'),false);
    for(const refusedMode of ['camera-unresolved','conversion-false','incomplete-enumeration']){
      mode=refusedMode;events.length=0;
      state.nativeMusicSelection.complete=refusedMode!=='incomplete-enumeration';
      owner.proof.managedCells.complete=refusedMode!=='incomplete-enumeration';
      const result=api.nativeMusicHit(screen,state,contexts,row,{});
      assert.strictEqual(result.proof.qualified,false,refusedMode);assert.strictEqual(result.target,row.target);
      assert.strictEqual(typeof result.proof.reason,'string');assert(result.proof.reason.length>0);
      assert.strictEqual(Object.prototype.hasOwnProperty.call(result,'input'),false);
      assert.strictEqual(events.some(event=>event.kind==='scan'),false);
      if(refusedMode==='incomplete-enumeration')assert.strictEqual(events.length,0);
      if(refusedMode==='camera-unresolved')assert.strictEqual(events.some(event=>event.kind==='convert'),false);
    }
  }finally{
    for(const key of keys){if(original[key]===undefined)delete context[key];else context[key]=original[key];}
  }
});

function run(){
  assert(tests.length>0,'Await exact R8 helper/API and SOURCE READY before running');
  for(const item of tests){item.fn();process.stdout.write('PASS '+item.name+'\n');}
  process.stdout.write(JSON.stringify({passed:tests.length,
    scope:'R8 structural mocks only; prospective native-hit prediction is not actual selection proof'})+'\n');
}
run();

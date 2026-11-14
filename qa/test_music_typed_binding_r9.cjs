/* Focused R9 host mocks only. No game, injection, API or input is invoked. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/unity_ui.js','utf8'),tests=[];
function test(name,fn){tests.push({name,fn});}
function plain(value){return JSON.parse(JSON.stringify(value));}
function point(x,y,z=0){return {x,y,z};}
function functionSource(name) {
  const start=source.indexOf('function '+name+'(');assert(start>=0,'Missing production helper '+name);
  const body=source.indexOf('{',start);let depth=0,quote=null,lineComment=false,blockComment=false,regex=false,regexClass=false;
  for(let index=body;index<source.length;index++){
    const current=source[index],next=source[index+1];
    if(lineComment){if(current==='\n')lineComment=false;continue;}
    if(blockComment){if(current==='*'&&next==='/'){blockComment=false;index++;}continue;}
    if(regex){if(current==='\\'){index++;continue;}if(current==='[')regexClass=true;if(current===']')regexClass=false;if(current==='/'&&!regexClass)regex=false;continue;}
    if(quote){if(current==='\\'){index++;continue;}if(current===quote)quote=null;continue;}
    if(current==='/'&&next==='/'){lineComment=true;index++;continue;}
    if(current==='/'&&next==='*'){blockComment=true;index++;continue;}
    if(current==='/'){
      const previous=source.slice(body,index).trimEnd().slice(-1);
      if('([=!:,?&|;{}'.includes(previous)){regex=true;continue;}
    }
    if(current==='"'||current==="'"||current==='`'){quote=current;continue;}
    if(current==='{')depth++;
    if(current==='}'&&--depth===0)return source.slice(start,index+1);
  }
  assert.fail('Unclosed production helper '+name);
}
const CELL_TYPE='LLAS.Scene.LiveMusicSelect.LiveMusicSelectScrollCell';
function typedRow(changes={}) {
  return Object.assign({componentType:CELL_TYPE,id:'typed-row',gameObjectId:'rect-go',voId:'typed-vo',
    voClass:'LLAS.DM.LiveMusicSelectDM+CellVO',voRead:{resolved:true,isNull:false,error:null},
    active:true,liveMasterId:12074,isPlayable:true},changes);
}
function nativeCell(ordinal,changes={}) {
  return Object.assign({ordinal,index:ordinal,positionIndex:ordinal,rectId:'rect-'+ordinal,rectGameObjectId:'rect-go',
    typedRowId:'typed-row',typedVOId:'typed-vo',associationQualified:true,typedActive:true,
    activeSelf:true,activeInHierarchy:true,liveMasterId:12074,isPlayable:true,
    nativeBounds:{min:point(0,0,0),max:point(10,10,0)}},changes);
}
const forbiddenReads=[];
const context={Math,Number,Object,Array,JSON,
  exists:value=>value!==null&&value!==undefined&&!(typeof value.isNull==='function'&&value.isNull()),
  instanceId:value=>value.id,fullType:value=>value.type||'Host.Mock',
  transform:value=>value.path,hierarchy:value=>value,
  mvReadField:(object,name)=>{forbiddenReads.push(name);assert.notStrictEqual(name,'CellVO');assert.notStrictEqual(name,'<CellVO>k__BackingField');return object&&object.fields?object.fields[name]??null:null;},
  mvBacking:(object,name)=>{forbiddenReads.push('<'+name+'>k__BackingField');assert.notStrictEqual(name,'CellVO','Optional interface must not be read as a typed component');return object&&object.fields?object.fields['<'+name+'>k__BackingField']??null:null;},
  mvNumber:value=>value===null||value===undefined?null:Number(value),
  call:()=>assert.fail('No game method or callback is permitted'),
  maybe:()=>assert.fail('No callback/getter fallback is permitted'),
  gameObject:value=>value.go||value,
  runtime:{camera:{method:()=>assert.fail('No Camera.main fallback')}}};
vm.createContext(context);
const nativeNames=[...source.matchAll(/function (nativeMusic[A-Za-z0-9_]*)\s*\(/g)].map(match=>match[1]);
vm.runInContext([...new Set(nativeNames)].map(functionSource).concat(functionSource('observeNativeMusicSelection'),
  functionSource('observeExistingMusicRowsAndMvTabs')).join('\n'),context,{filename:'R9-typed-native-binding-mocks.js'});
const api=context;

test('nullable interface is diagnostic only and never supplies a CellVO',()=>{
  forbiddenReads.length=0;let reads=0;
  function entry(value,fail=false){return {field:name=>{
    reads++;assert.strictEqual(name,'scrollSelectCell');
    if(fail)throw new Error('host-only interface field read failure');
    return {type:{name:'Jigbox.Components.IScrollSelectCell'},value};
  }};}
  const absent=api.nativeMusicOptionalInterface(entry(null));
  assert.strictEqual(absent.resolved,true);assert.strictEqual(absent.isNull,true);assert.strictEqual(absent.id,null);
  assert.strictEqual(absent.declaredType,'Jigbox.Components.IScrollSelectCell');
  const component={id:'component-instance',handle:{toString:()=> '0x1234',isNull:()=>false},type:'Jigbox.Components.IScrollSelectCell',
    field:()=>assert.fail('Interface has no CellVO field')};
  const reference=api.nativeMusicOptionalInterface(entry(component));
  assert.strictEqual(reference.resolved,true);assert.strictEqual(reference.isNull,false);assert.strictEqual(reference.id,'0x1234');
  const unreadable=api.nativeMusicOptionalInterface(entry(null,true));
  assert.strictEqual(unreadable.resolved,false);assert(unreadable.error);assert.strictEqual(reads,3);
  assert.strictEqual(forbiddenReads.some(name=>name.includes('CellVO')),false);
});

test('unique exact GameObject association is independent of optional interface and preserves all typed IDs',()=>{
  const row=typedRow(),mapped=api.nativeMusicAssociateRows('rect-go',[typedRow({id:'other-row',gameObjectId:'other-go'}),row],true);
  assert.strictEqual(mapped.associationQualified,true);assert.strictEqual(mapped.candidateCount,1);
  assert.strictEqual(mapped.typedRowId,row.id);assert.strictEqual(mapped.typedVOId,row.voId);
  assert.strictEqual(mapped.liveMasterId,12074);assert.strictEqual(mapped.isPlayable,true);assert.strictEqual(mapped.typedActive,true);
  const unplayable=api.nativeMusicAssociateRows('rect-go',[typedRow({isPlayable:false})],true);
  assert.strictEqual(unplayable.associationQualified,true,'Readable mapping is distinct from prospective input eligibility');
  assert.strictEqual(unplayable.isPlayable,false);
  const refused=api.nativeMusicScan([nativeCell(0,{isPlayable:false})],nativeCell(0),point(5,5,0));
  assert.strictEqual(refused.qualified,false);
});

test('missing duplicate wrong-owner and unreadable typed VO associations remain unqualified',()=>{
  const variants=[
    [[],true],[[typedRow({gameObjectId:'wrong-go'})],true],[[typedRow(),typedRow({id:'duplicate',voId:'duplicate-vo'})],true],
    [[typedRow(),typedRow({id:'unreadable-duplicate',voId:null,voRead:{resolved:false,isNull:null,error:'unreadable'}})],true],
    [[typedRow({componentType:'Host.OtherComponent'})],true],[[typedRow({active:false})],true],
    [[typedRow({voId:null})],true],[[typedRow({voRead:{resolved:false,isNull:null,error:'read failed'}})],true],
    [[typedRow({voRead:{resolved:true,isNull:true,error:null}})],true],
    [[typedRow({voRead:{resolved:true,isNull:false,error:'unresolved getter'}})],true],
    [[typedRow({liveMasterId:null})],true],[[typedRow({liveMasterId:true})],true],[[typedRow({liveMasterId:12074.5})],true],
    [[typedRow({isPlayable:null})],true],[[typedRow()],false]];
  for(const [rows,complete] of variants){
    const result=api.nativeMusicAssociateRows('rect-go',rows,complete);
    assert.strictEqual(result.associationQualified,false,JSON.stringify({rows,complete}));
    assert.strictEqual(typeof result.status,'string');
  }
});

test('unknown FIRST native cell stays in geometry order and prevents a later intended fallback',()=>{
  const unknown=nativeCell(0,{associationQualified:false,typedRowId:null,typedVOId:null,liveMasterId:null}),intended=nativeCell(1);
  const world=point(5,5,0),entries=[unknown,intended];
  assert.strictEqual(api.nativeMusicFirstContaining(entries,world),unknown);
  const result=api.nativeMusicScan(entries,intended,world);
  assert.strictEqual(result.qualified,false);assert.strictEqual(result.firstContaining.ordinal,0);
  assert.strictEqual(result.firstContaining.associationQualified,false);
  assert.strictEqual(api.nativeMusicScan([intended,unknown],intended,world).qualified,true);
  const unknownOutside=Object.assign({},unknown,{nativeBounds:{min:point(-20,-20,0),max:point(-10,-10,0)}});
  const later=api.nativeMusicScan([unknownOutside,intended],intended,world);
  assert.strictEqual(later.qualified,true,'A non-containing unknown entry must not poison complete later typed geometry');
  assert.strictEqual(later.firstContaining.ordinal,1,'Original order is retained; no optional-interface prefilter is needed');
  const inactive=nativeCell(0,{activeInHierarchy:false});
  assert.strictEqual(api.nativeMusicScan([inactive,intended],intended,world).qualified,false);
});

test('incomplete native geometry is refused before scanning even when intended association is exact',()=>{
  const intended=nativeCell(1),unreadable=nativeCell(0,{nativeBounds:null,associationQualified:false});
  const result=api.nativeMusicScan([unreadable,intended],intended,point(5,5,0));
  assert.strictEqual(result.qualified,false);assert.strictEqual(result.firstContaining,null);
  assert.strictEqual(api.nativeMusicBoundedCells(2,2,index=>[unreadable,intended][index]).complete,false);
  const identity=api.nativeMusicCellIdentity(intended);
  for(const key of ['typedRowId','typedVOId','rectGameObjectId','associationQualified'])assert(Object.prototype.hasOwnProperty.call(identity,key),key);
  assert.strictEqual(Object.prototype.hasOwnProperty.call(identity,'cellId'),false,'Interface-derived identity must not qualify selection');
});

test('real native enumeration retains nullable interfaces and unknown roots while binding only exact typed row GameObjects',()=>{
  const keys=['findClass','allOfType','active','call','descendsFrom','nativeMusicCanvasCamera','nativeMusicViewport','nativeMusicRect',
    'mvExistingComponentInfo','mvUiTarget'];
  const original=Object.fromEntries(keys.map(key=>[key,context[key]]));
  const view={id:'view',path:'Scroll/View',fields:{},active:true},model={id:'model',path:'Scroll/Model',fields:{}},
    proxyGo={id:'proxy-go',path:'Scroll/Proxy',owner:view,isGo:true},
    proxy={id:'proxy',path:'Scroll/Proxy',go:proxyGo,fields:{ScrollSelectView:view}},
    transition={id:'transition',path:'Scroll/Transition'},interfaceReads=[],activeReads=[];
  const interfaceValue={type:'Jigbox.Components.IScrollSelectCell',handle:{toString:()=> '0x5678',isNull:()=>false},
    field:()=>assert.fail('No CellVO field exists on the optional interface')};
  const roots=['unknown-go','rect-go'].map((id,index)=>{
    const go={id,path:'Scroll/Root'+index,owner:view,isGo:true,activeSelf:true,activeInHierarchy:true},
      rect={id:'native-rect-'+index,path:'Scroll/Root'+index,go};
    const value={fields:{'<RectTransform>k__BackingField':rect,'<Index>k__BackingField':index,
      '<PositionIndex>k__BackingField':index,scrollSelectCell:index?interfaceValue:null},
      field:name=>{interfaceReads.push(name);assert.strictEqual(name,'scrollSelectCell');return {value:value.fields[name]};}};
    return {go,rect,value};
  });
  const items={length:roots.length,get:index=>roots[index].value},list={id:'list',type:'System.Collections.Generic.List`1<Jigbox.ScrollSelectRectTransform>',
    fields:{_size:roots.length,_items:items}};
  model.fields.managedCells=list;view.fields={model,inputProxy:proxy,transition};
  let invalidGeometry=false;
  try{
    context.findClass=name=>{assert.strictEqual(name,'LLAS.Components.UI.ProductMusicScrollView');return {id:'view-class'};};
    context.allOfType=()=>({length:1,get:()=>view});context.active=value=>({active:value.active===true});
    context.call=(value,name)=>{
      assert.strictEqual(value.isGo,true);assert(['get_activeSelf','get_activeInHierarchy'].includes(name));
      activeReads.push(name);return name==='get_activeSelf'?value.activeSelf:value.activeInHierarchy;
    };
    context.descendsFrom=(go,owner)=>go.owner===owner;
    context.nativeMusicCanvasCamera=value=>{assert.strictEqual(value,view);return null;};
    context.nativeMusicViewport=()=>({visible:true,visibleBounds:{left:0,top:0,right:100,bottom:100}});
    context.nativeMusicRect=value=>({rectId:value.id,path:value.path,nativeBounds:invalidGeometry?null:{min:point(0,0,0),max:point(10,10,0)}});
    const screen={scene:'LiveMusicSelect'},row=typedRow();
    const observed=api.observeNativeMusicSelection(screen,[row],{complete:true});
    assert.strictEqual(observed.proof.complete,true);assert.strictEqual(observed.owners.length,1);
    const cells=observed.proof.owners[0].managedCells;
    assert.strictEqual(cells.complete,true);assert.strictEqual(cells.entries.length,2);
    assert.strictEqual(cells.entries[0].associationQualified,false);assert.strictEqual(cells.entries[0].optionalInterface.isNull,true);
    assert.strictEqual(cells.entries[1].associationQualified,true);assert.strictEqual(cells.entries[1].optionalInterface.id,'0x5678');
    assert.strictEqual(cells.entries[1].typedRowId,row.id);assert.strictEqual(cells.entries[1].typedVOId,row.voId);
    assert.strictEqual(cells.entries[1].rectGameObjectId,row.gameObjectId);
    assert.strictEqual(api.nativeMusicScan(cells.entries,cells.entries[1],point(5,5,0)).qualified,false,'Unknown FIRST remains in the original scan');
    assert(interfaceReads.every(name=>name==='scrollSelectCell'));
    assert.strictEqual(forbiddenReads.some(name=>name.includes('CellVO')),false);
    assert.strictEqual(activeReads.length,4,'Every geometry root active state is read, including unknown associations');
    const duplicate=api.observeNativeMusicSelection(screen,[row,typedRow({id:'duplicate-row',voId:'duplicate-vo'})],{complete:true});
    assert.strictEqual(duplicate.proof.owners[0].managedCells.entries[1].associationQualified,false);
    assert.strictEqual(api.observeNativeMusicSelection(screen,[row],{complete:false}).proof.complete,false);
    invalidGeometry=true;
    assert.strictEqual(api.observeNativeMusicSelection(screen,[row],{complete:true}).proof.complete,false);

    // Exercise the real typed-row collector and real field reader. A duplicate
    // beyond the old128 limit must remain visible to the exact-GameObject join.
    const typedHandle={};typedHandle.equals=other=>other===typedHandle;
    const typedClass={handle:typedHandle,isSubclassOf:()=>false},voFieldReads=[],cellFieldReads=[];
    function typedObject(index,duplicate){
      const vo={type:'LLAS.DM.LiveMusicSelectDM+CellVO',handle:{toString:()=> '0xvo-'+index,isNull:()=>false},
        field:name=>{
          voFieldReads.push(name);assert(['<LiveMasterId>k__BackingField','<IsPlayable>k__BackingField'].includes(name));
          return {value:name==='<LiveMasterId>k__BackingField'?12074+index:true};
        }};
      const go={id:'typed-go-'+(duplicate&&index===150?0:index),path:'Scroll/Typed'+index,isGo:true,activeSelf:true,activeInHierarchy:true};
      return {id:'current-typed-'+index,type:CELL_TYPE,class:typedClass,go,path:go.path,
        field:name=>{cellFieldReads.push(name);assert.strictEqual(name,'<CellVO>k__BackingField');return {value:vo};}};
    }
    let runtimeRows=Array.from({length:200},(_,index)=>typedObject(index,true));
    context.findClass=name=>name===CELL_TYPE?typedClass:{name};
    context.allOfType=klass=>{const values=klass===typedClass?runtimeRows:[];return {length:values.length,get:index=>values[index]};};
    context.mvExistingComponentInfo=value=>({id:value.id,gameObjectId:value.go.id,path:value.path,active:value.go.activeInHierarchy});
    context.mvUiTarget=value=>({id:value.id,path:value.path,active:true,enabled:true,visible:true,
      groupsInteractable:true,blocksRaycasts:true,hit:{available:true,hittable:true}});
    const all200=api.observeExistingMusicRowsAndMvTabs(screen,{});
    assert.strictEqual(all200.musicRows.length,200);assert.strictEqual(all200.musicRowsEnumeration.complete,true);
    assert.strictEqual(all200.musicRowsEnumeration.totalObjects,200);assert.strictEqual(all200.musicRowsEnumeration.activeObjects,200);
    assert.strictEqual(all200.musicRows[0].voRead.resolved,true);assert.strictEqual(all200.musicRows[0].voRead.isNull,false);
    assert.strictEqual(all200.musicRows[0].voId,'0xvo-0');assert.strictEqual(all200.musicRows[0].liveMasterId,12074);
    const beyond128=api.nativeMusicAssociateRows('typed-go-0',all200.musicRows,all200.musicRowsEnumeration.complete);
    assert.strictEqual(beyond128.candidateCount,2);assert.strictEqual(beyond128.associationQualified,false);
    assert.strictEqual(cellFieldReads.length,200);assert.strictEqual(voFieldReads.length,400);
    cellFieldReads.length=0;voFieldReads.length=0;
    runtimeRows=Array.from({length:513},(_,index)=>typedObject(index,false));
    const capped=api.observeExistingMusicRowsAndMvTabs(screen,{});
    assert.strictEqual(capped.musicRows.length,512);assert.strictEqual(capped.musicRowsEnumeration.complete,false);
    assert.strictEqual(capped.musicRowsEnumeration.limit,512);assert.strictEqual(capped.musicRowsEnumeration.totalObjects,513);
    assert.strictEqual(cellFieldReads.length,512);assert.strictEqual(voFieldReads.length,1024);
    const incomplete=api.nativeMusicAssociateRows('typed-go-0',capped.musicRows,capped.musicRowsEnumeration.complete);
    assert.strictEqual(incomplete.candidateCount,1);assert.strictEqual(incomplete.associationQualified,false);
    assert.strictEqual(incomplete.status,'typed-row-enumeration-incomplete');
  }finally{
    for(const key of keys){if(original[key]===undefined)delete context[key];else context[key]=original[key];}
  }
});

function run(){
  for(const item of tests){item.fn();process.stdout.write('PASS '+item.name+'\n');}
  process.stdout.write(JSON.stringify({passed:tests.length,
    scope:'R9 structural mocks only; typed binding and predicted hit do not prove actual song selection'})+'\n');
}
run();

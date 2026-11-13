/* Mock structural tests only. They do not prove an actual game catalog. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const fragment=fs.readFileSync(__dirname+'/catalog_observer.fragment.js','utf8');
function fixture(options={}) {
  let serial=0,lengthReads=0,elementReads=0;const registry=new Map();
  const klass=(namespace,name,extra={})=>Object.assign({namespace,name,rank:0},extra);
  const memberClass=klass('LLAS.DM.ValueObject','MemberSuitVO');
  function object(classInfo,fields={}) {
    const id=++serial,value={id:String(id),handle:{toString:()=>String(id)},class:classInfo,fields,active:true,
      isNull:()=>false,path:'EntryPoint/PopupView/Content/'+classInfo.name};registry.set(String(id),value);return value;
  }
  function member(suit=11,member=1){return object(memberClass,{'<MasterId>k__BackingField':suit,'<MemberMasterId>k__BackingField':member});}
  class NativeArray {
    constructor(handle){this.source=registry.get(String(handle));this.handle=this.source.handle;}
    isNull(){return false;}
    get object(){return this.source;}
    get length(){lengthReads++;return this.source.length;}
    get(index){
      elementReads++;
      if(options.mutate&&elementReads===this.source.length+1)this.source.items[0].fields['<MasterId>k__BackingField']=99;
      return this.source.items[index];
    }
  }
  function array(items){const source=object(klass('LLAS.DM.ValueObject','MemberSuitVO[]',{rank:1,elementClass:memberClass}));source.items=items;source.length=items.length;return new NativeArray(source.handle);}
  const first=member();const rows=options.duplicate?[first,member()]:[first,member(12)];
  if(options.invalidId)rows[1].fields['<MasterId>k__BackingField']=0;
  if(options.mixedMember)rows[1].fields['<MemberMasterId>k__BackingField']=2;
  let orderArray=array(rows);
  if(options.oversize)orderArray.source.length=4097;
  if(options.notArray)orderArray=object(memberClass);
  const popupClass=klass('LLAS','SuitChangePopup');
  const order=object(klass('','Order',{declaringClass:popupClass}),{'<MemberSuitVO>k__BackingField':first,'<MemberSuitVOs>k__BackingField':orderArray});
  const delivery=options.otherReference?array(rows).object:orderArray instanceof NativeArray?orderArray.object:orderArray;
  const view=object(klass('LLAS.Scene.EntryPoint','SuitChangePopupSuitTileView'),{'<DeliveryObject>k__BackingField':delivery});
  const popup=object(popupClass,{'<PopupOrder>k__BackingField':order,'suitChangePopupSuitTileView':view});
  const popups=[popup];if(options.multiple)popups.push(object(popupClass,popup.fields));
  const context={Il2Cpp:{Array:NativeArray},findClass:name=>name==='LLAS.SuitChangePopup'?popupClass:null,
    allOfType:()=>({length:popups.length,get:i=>popups[i]}),exists:value=>!!value&&!(value.isNull&&value.isNull()),
    active:value=>({active:value.active}),mvReadField:(value,name)=>value&&value.fields?value.fields[name]??null:null,
    mvBacking:(value,name)=>value&&value.fields?value.fields['<'+name+'>k__BackingField']??null:null,
    mvNumber:value=>value===null||value===undefined?null:Number(value),
    fullType:value=>value.class.namespace?value.class.namespace+'.'+value.class.name:value.class.name,
    instanceId:value=>value.id,transform:value=>value.path,hierarchy:value=>value};
  vm.createContext(context);vm.runInContext(fragment,context);
  return {run:()=>JSON.parse(JSON.stringify(context.observeExistingSuitCatalogs())),counters:()=>({lengthReads,elementReads})};
}
let passed=0;
function test(name,fn){fn();passed++;process.stdout.write('PASS '+name+'\n');}
test('exact array reference proves complete raw rows',()=>{
  const result=fixture().run();assert.equal(result.complete,true);assert.deepEqual(result.suitCatalogs[0].rows,[{memberId:1,suitId:11},{memberId:1,suitId:12}]);
});
test('existing duplicate rows are retained rather than deduplicated',()=>{
  const row=fixture({duplicate:true}).run().suitCatalogs[0];assert.equal(row.complete,true);assert.equal(row.arrayLength,2);assert.deepEqual(row.rows,[{memberId:1,suitId:11},{memberId:1,suitId:11}]);
});
test('equivalent different array reference is incomplete',()=>{
  const result=fixture({otherReference:true}).run();assert.equal(result.complete,false);assert.match(result.suitCatalogs[0].error,/EXACT_ORDER_ARRAY/);
});
test('invalid and mixed-character elements never silently disappear',()=>{
  for(const options of [{invalidId:true},{mixedMember:true}])assert.equal(fixture(options).run().complete,false);
});
test('over-bound array is rejected before any element enumeration',()=>{
  const f=fixture({oversize:true});assert.equal(f.run().complete,false);assert.equal(f.counters().elementReads,0);
});
test('non-array is rejected before native array length',()=>{
  const f=fixture({notArray:true});assert.equal(f.run().complete,false);assert.equal(f.counters().lengthReads,0);
});
test('binding content mutation during field reread is incomplete',()=>{
  const result=fixture({mutate:true}).run();assert.equal(result.complete,false);assert.match(result.suitCatalogs[0].error,/CHANGED_DURING_READ/);
});
test('multiple active popups never produce a globally complete catalog',()=>{
  const result=fixture({multiple:true}).run();assert.equal(result.complete,false);assert.equal(result.suitCatalogs.length,2);assert(result.errors.includes('MULTIPLE_ACTIVE_SUIT_CHANGE_POPUPS'));assert(result.suitCatalogs.every(c=>c.complete===false));
});
process.stdout.write(JSON.stringify({passed,scope:'Structural mocks only; actual game catalog/feature approval remains unproven'})+'\n');

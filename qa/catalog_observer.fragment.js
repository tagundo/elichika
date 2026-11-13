/* QA-ONLY, field-only complete suit catalog observation. Never executes an
 * input, setter, C# collection/property getter, callback or enumerator.
 * Uses existing main-thread findClass/allOfType/exists/active/mvReadField/
 * mvBacking/mvNumber/fullType/instanceId helpers and bridge native array APIs.
 * Exact original GL metadata provenance is in suit-catalog-proposal.json.
 * Missing/unsupported data stays incomplete; visible cells are no fallback.
 */
function observeExistingSuitCatalogs() {
  var MAX_ENTRIES = 4096, MAX_POPUPS = 256;
  var MEMBER_SUIT = "LLAS.DM.ValueObject.MemberSuitVO";
  var result = {complete:false,suitCatalogs:[],errors:[],
    scope:"Complete current SuitChangePopup input array + bound displayed IList; raw multiplicity/order preserved, not visible-cell counts"};
  function fail(code) { throw new Error(code); }
  function pointer(value) { return exists(value) && value.handle ? value.handle.toString() : null; }
  function asObject(value) {
    if (!exists(value)) fail("CATALOG_REFERENCE_NULL");
    return value instanceof Il2Cpp.Array ? value.object : value;
  }
  function className(klass) { return klass.namespace ? klass.namespace+"."+klass.name : klass.name; }
  function positive(value) { return Number.isInteger(value) && value>0; }
  function boundedArray(value,label,capacityLimit) {
    var object=asObject(value),klass=object.class;
    // Check the managed object's actual array rank/element metadata BEFORE
    // wrapping it as an array or reading native array length.
    var element=klass.rank===1 ? klass.elementClass : null;
    if (klass.rank!==1 || !exists(element) || className(element)!==MEMBER_SUIT)
      fail(label+"_NOT_MEMBER_SUIT_ARRAY");
    var array=value instanceof Il2Cpp.Array ? value : new Il2Cpp.Array(value.handle);
    var count=Number(array.length);
    if (!Number.isInteger(count) || count<0 || count>capacityLimit) fail(label+"_ARRAY_LENGTH_OUT_OF_QA_BOUND");
    return {array:array,count:count,pointer:pointer(value),className:className(klass)};
  }
  function readRows(array,count,label) {
    var rows=[];
    for (var i=0;i<count;i++) {
      var vo=array.get(i);
      if (!exists(vo) || fullType(vo)!==MEMBER_SUIT) fail(label+"_INVALID_MEMBER_SUIT_VO_AT_"+i);
      var id=mvNumber(mvBacking(vo,"MasterId")),member=mvNumber(mvBacking(vo,"MemberMasterId"));
      if (!positive(id) || !positive(member)) fail(label+"_INVALID_IDENTITY_AT_"+i);
      // No set/dedup operation: one output row for EVERY array/list element.
      rows.push({index:i,suitId:id,memberId:member,voPointer:pointer(vo)});
    }
    return rows;
  }
  function sameRows(first,second) {
    if (first.length!==second.length) return false;
    for (var i=0;i<first.length;i++)
      if (first[i].suitId!==second[i].suitId || first[i].memberId!==second[i].memberId) return false;
    return true;
  }
  function observe(popup) {
    var record={complete:false,id:String(instanceId(popup)),path:hierarchy(transform(popup)),active:true,popupPointer:pointer(popup),
      source:"SuitChangePopup.PopupOrder.MemberSuitVOs + referenced suit view DeliveryObject"};
    try {
      var order=mvBacking(popup,"PopupOrder"),view=mvReadField(popup,"suitChangePopupSuitTileView");
      if (!exists(order) || !exists(view)) fail("POPUP_ORDER_OR_REFERENCED_VIEW_NULL");
      var declaring=order.class.declaringClass;
      if (order.class.name!=="Order" || !declaring || className(declaring)!=="LLAS.SuitChangePopup")
        fail("POPUP_ORDER_DECLARING_CLASS_MISMATCH");
      if (fullType(view)!=="LLAS.Scene.EntryPoint.SuitChangePopupSuitTileView" || !active(view).active)
        fail("REFERENCED_SUIT_VIEW_NOT_ACTIVE_OR_WRONG_CLASS");
      var selected=mvBacking(order,"MemberSuitVO");
      if (!exists(selected) || fullType(selected)!==MEMBER_SUIT) fail("SELECTED_MEMBER_SUIT_VO_INVALID");
      var selectedMember=mvNumber(mvBacking(selected,"MemberMasterId"));
      var selectedSuit=mvNumber(mvBacking(selected,"MasterId"));
      if (!positive(selectedMember) || !positive(selectedSuit)) fail("SELECTED_MEMBER_SUIT_IDENTITY_INVALID");
      var sourceValue=mvBacking(order,"MemberSuitVOs"),source=boundedArray(sourceValue,"ORDER",MAX_ENTRIES);
      if (source.count===0) fail("ORDER_CATALOG_EMPTY");
      var rows=readRows(source.array,source.count,"ORDER"),hasSelected=false;
      for (var i=0;i<rows.length;i++) {
        if (rows[i].memberId!==selectedMember) fail("ORDER_CONTAINS_ANOTHER_CHARACTER");
        if (rows[i].suitId===selectedSuit) hasSelected=true;
      }
      var deliveryValue=mvBacking(view,"DeliveryObject");
      if (!exists(deliveryValue) || pointer(deliveryValue)!==source.pointer)
        fail("DISPLAYED_DELIVERY_IS_NOT_EXACT_ORDER_ARRAY");
      var delivery=boundedArray(deliveryValue,"DELIVERY",MAX_ENTRIES);
      if (delivery.count!==source.count) fail("DISPLAYED_DELIVERY_LENGTH_DIFFERS_FROM_ORDER");
      var again=boundedArray(mvBacking(order,"MemberSuitVOs"),"ORDER_RECHECK",MAX_ENTRIES);
      if (again.pointer!==source.pointer || again.count!==source.count ||
          !sameRows(readRows(again.array,again.count,"ORDER_RECHECK"),rows) ||
          pointer(mvBacking(popup,"PopupOrder"))!==pointer(order) ||
          pointer(mvReadField(popup,"suitChangePopupSuitTileView"))!==pointer(view) ||
          pointer(mvBacking(view,"DeliveryObject"))!==pointer(deliveryValue))
        fail("CATALOG_BINDING_CHANGED_DURING_READ");
      record.complete=true;
      record.memberId=selectedMember;record.selectedSuitId=selectedSuit;
      record.orderPointer=pointer(order);record.viewId=String(instanceId(view));record.viewPointer=pointer(view);
      record.orderArrayPointer=source.pointer;record.arrayLength=source.count;
      record.rows=rows.map(function(row){return {memberId:row.memberId,suitId:row.suitId};});
      record.voPointers=rows.map(function(row){return row.voPointer;});
      record.selectedSuitPresentInCatalog=hasSelected;
      record.delivery={kind:"MemberSuitVO[]",pointer:delivery.pointer,count:delivery.count,sameArrayReference:true};
      record.completeness="Every Order.MemberSuitVOs element read; referenced displayed DeliveryObject is the exact same array; binding/count/content stable within callback";
    } catch (error) {record.error=String(error);}
    return record;
  }
  try {
    var klass=findClass("LLAS.SuitChangePopup",true);
    if (!klass) {result.errors.push("SUIT_CHANGE_POPUP_TYPE_ABSENT");return result;}
    var objects=allOfType(klass);
    if (objects.length>MAX_POPUPS) {result.errors.push("POPUP_OBJECT_COUNT_EXCEEDS_QA_BOUND");return result;}
    for (var i=0;i<objects.length;i++) {
      var object=objects.get(i);
      if (exists(object) && active(object).active) result.suitCatalogs.push(observe(object));
    }
    result.complete=result.suitCatalogs.length===1 && result.suitCatalogs[0].complete===true;
    if (result.suitCatalogs.length>1) {
      result.errors.push("MULTIPLE_ACTIVE_SUIT_CHANGE_POPUPS");
      // Flattening the records into the parent snapshot must not lose the
      // global ambiguity gate, even if only one popup matches a member ID.
      result.suitCatalogs.forEach(function(record){
        record.complete=false;record.error=record.error || "MULTIPLE_ACTIVE_SUIT_CHANGE_POPUPS";
      });
    }
  } catch (error) {result.errors.push(String(error));}
  return result;
}

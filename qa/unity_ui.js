/* Disposable runtime QA observer. No APK patch, game-state setter or UI click.
 * Prepend frida-il2cpp-bridge 0.9.1 dist/index.js before loading in Frida 16.6.6.
 * All Unity object reads run on the Unity main thread; taps belong to adb.
 */
(function () {
  "use strict";
  var ready = false, lastError = "", runtime = {}, classCache = {}, initPending = false;
  var BRIDGE_VERSION = "0.9.1", AGENT_VERSION = 8;
  var QA_IDENTITY = {pid:Process.id,architecture:Process.arch,fridaVersion:Frida.version};
  var TEXT_TYPES = ["UnityEngine.UI.Text", "TMPro.TMP_Text", "Jigbox.Components.TextView", "LLAS.Components.UI.ProductTextView"];
  var DEFAULT_TYPES = ["UnityEngine.UI.Button", "UnityEngine.UI.Toggle", "UnityEngine.UI.InputField", "TMPro.TMP_InputField", "UnityEngine.UI.ScrollRect"].concat(TEXT_TYPES);

  function exists(value) { return !!value && !(typeof value.isNull === "function" && value.isNull()); }
  function text(value) { return exists(value) ? String(value.content === undefined ? value : value.content || "") : ""; }
  function call(object, name, args) { return object.method(name, (args || []).length).invoke.apply(object.method(name, (args || []).length), args || []); }
  function maybe(object, name, fallback, args) { try { return exists(object) ? call(object, name, args) : fallback; } catch (_) { return fallback; } }
  function findClass(name, optional) {
    if (classCache[name] !== undefined) return classCache[name];
    var assemblies = Il2Cpp.domain.assemblies;
    for (var i = 0; i < assemblies.length; i++) {
      var candidate = assemblies[i].image.tryClass(name);
      if (candidate) { classCache[name] = candidate; return candidate; }
    }
    if (optional) { classCache[name] = null; return null; }
    throw new Error("Unity class is unavailable: " + name);
  }
  function overloaded(object, name, parameterTypes, args) {
    return object.method(name, parameterTypes.length).overload.apply(object.method(name, parameterTypes.length), parameterTypes).invoke.apply(
      object.method(name, parameterTypes.length).overload.apply(object.method(name, parameterTypes.length), parameterTypes), args);
  }
  function nullObject() { return new Il2Cpp.Object(ptr(0)); }
  function vector(klass, x, y) {
    var memory = Memory.alloc(klass.valueTypeSize);
    var value = new Il2Cpp.ValueType(memory, klass.type);
    value.field("x").value = x; value.field("y").value = y;
    return value;
  }
  function field(value, name) { return Number(value.field(name).value); }
  function gameObject(component) { return maybe(component, "get_gameObject", null) || component; }
  function transform(component) { return maybe(component, "get_transform", null); }
  function component(object, klass) {
    if (!exists(object) || !klass) return null;
    try { var result = overloaded(object, "GetComponent", ["System.Type"], [klass.type.object]); return exists(result) ? result : null; } catch (_) { return null; }
  }
  function fullType(object) { return object.class.namespace ? object.class.namespace + "." + object.class.name : object.class.name; }
  function instanceId(object) { return maybe(object, "GetInstanceID", object.handle.toString()); }
  function hierarchy(tr) {
    var parts = [], seen = {}, count = 0;
    while (exists(tr) && count++ < 64) {
      var key = tr.handle.toString(); if (seen[key]) break; seen[key] = true;
      parts.push(text(maybe(tr, "get_name", null)) || "?"); tr = maybe(tr, "get_parent", null);
    }
    return parts.reverse().join("/");
  }
  function active(componentObject) {
    var go = gameObject(componentObject);
    return { gameObject: go, active: !!maybe(go, "get_activeInHierarchy", false),
      enabled: maybe(componentObject, "get_isActiveAndEnabled", maybe(componentObject, "get_enabled", true)) !== false };
  }
  function interactable(object) {
    var value = maybe(object, "IsInteractable", null);
    return value === null ? maybe(object, "get_interactable", null) : !!value;
  }
  function nearestSelectable(tr) {
    var count = 0;
    while (exists(tr) && count++ < 48) {
      var selected = component(gameObject(tr), runtime.selectable);
      if (exists(selected)) return selected;
      tr = maybe(tr, "get_parent", null);
    }
    return null;
  }
  function nearestInput(tr) {
    var count = 0;
    while (exists(tr) && count++ < 32) {
      var input = component(gameObject(tr), runtime.inputField) || component(gameObject(tr), runtime.tmpInputField);
      if (exists(input)) return input;
      tr = maybe(tr, "get_parent", null);
    }
    return null;
  }
  function inputDescription(input, numericTestId) {
    var raw = text(maybe(input, "get_text", null)), type = Number(maybe(input, "get_inputType", -1));
    var content = Number(maybe(input, "get_contentType", -1));
    var password = type === 2 || content === 7 || content === 8;
    var allowed = !password && /^\d{1,12}$/.test(raw) && raw === String(numericTestId || "893611090");
    return { value: allowed ? raw : null, length: raw.length, redacted: !allowed && raw.length > 0,
      password: password, focused: !!maybe(input, "get_isFocused", false), readOnly: !!maybe(input, "get_readOnly", false),
      characterLimit: Number(maybe(input, "get_characterLimit", 0)), inputType: type, contentType: content };
  }
  function redactInputText(value, input, description) {
    if (!exists(input) || !description || !description.redacted) return value;
    var raw = text(maybe(input, "get_text", null));
    return raw ? String(value).split(raw).join("[redacted input]") : value;
  }
  function canvasFor(tr) {
    var count = 0, result = null;
    while (exists(tr) && count++ < 48) {
      var canvas = component(gameObject(tr), runtime.canvas);
      if (exists(canvas)) { result = canvas; break; }
      tr = maybe(tr, "get_parent", null);
    }
    if (!result) throw new Error("No Canvas ancestor for this UI object");
    var mode = Number(call(result, "get_renderMode")), camera = nullObject();
    if (mode !== 0) {
      camera = maybe(result, "get_worldCamera", null);
      if (!exists(camera)) camera = maybe(runtime.camera, "get_main", null);
      if (!exists(camera)) throw new Error("Camera/world-space Canvas has no projection camera");
    }
    return { object: result, mode: mode, camera: camera, cameraName: exists(camera) ? text(maybe(camera, "get_name", null)) : null };
  }
  function rawRect(tr, canvas, screen) {
    var corners = Il2Cpp.array(runtime.vector3, 4);
    call(tr, "GetWorldCorners", [corners]);
    var points = [];
    for (var i = 0; i < 4; i++) {
      var projected = runtime.rectUtility.method("WorldToScreenPoint", 2).invoke(canvas.camera, corners.get(i));
      points.push({ x: field(projected, "x"), y: screen.height - field(projected, "y") });
    }
    var xs = points.map(function (p) { return p.x; }), ys = points.map(function (p) { return p.y; });
    var result = { left: Math.min.apply(null, xs), top: Math.min.apply(null, ys), right: Math.max.apply(null, xs), bottom: Math.max.apply(null, ys) };
    if (![result.left, result.top, result.right, result.bottom].every(Number.isFinite)) throw new Error("Non-finite projected RectTransform");
    result.width = result.right - result.left; result.height = result.bottom - result.top;
    return result;
  }
  function intersect(a, b) { return { left: Math.max(a.left, b.left), top: Math.max(a.top, b.top), right: Math.min(a.right, b.right), bottom: Math.min(a.bottom, b.bottom) }; }
  function rectAndClipping(tr, screen) {
    var canvas = canvasFor(tr), original = rawRect(tr, canvas, screen);
    var clipped = intersect(original, { left: 0, top: 0, right: screen.width, bottom: screen.height });
    var parent = tr, count = 0, alpha = 1, groupsInteractable = true, blocksRaycasts = true, ignoreParentGroups = false;
    while (exists(parent) && count++ < 48) {
      var go = gameObject(parent), group = component(go, runtime.canvasGroup);
      if (!ignoreParentGroups && exists(group) && maybe(group, "get_enabled", true)) {
        alpha *= Number(maybe(group, "get_alpha", 1));
        groupsInteractable = groupsInteractable && maybe(group, "get_interactable", true) !== false;
        blocksRaycasts = blocksRaycasts && maybe(group, "get_blocksRaycasts", true) !== false;
        ignoreParentGroups = !!maybe(group, "get_ignoreParentGroups", false);
      }
      if (parent !== tr) {
        var mask = component(go, runtime.rectMask) || component(go, runtime.mask);
        if (exists(mask) && maybe(mask, "get_isActiveAndEnabled", true)) {
          try { clipped = intersect(clipped, rawRect(parent, canvas, screen)); } catch (_) { /* Native hit test remains authoritative. */ }
        }
      }
      parent = maybe(parent, "get_parent", null);
    }
    clipped.width = Math.max(0, clipped.right - clipped.left); clipped.height = Math.max(0, clipped.bottom - clipped.top);
    return { bounds: original, visibleBounds: clipped,
      center: { x: Math.max(0, Math.min(screen.width - 1, Math.round((clipped.left + clipped.right) / 2))),
        y: Math.max(0, Math.min(screen.height - 1, Math.round((clipped.top + clipped.bottom) / 2))) },
      visible: clipped.width >= 1 && clipped.height >= 1 && alpha > .001,
      alpha: alpha, groupsInteractable: groupsInteractable, blocksRaycasts: blocksRaycasts,
      canvas: { mode: canvas.mode, camera: canvas.cameraName } };
  }
  function componentText(object) {
    var getters = ["get_text", "get_Text", "get_SourceText", "get_RawText", "get_TextSource", "get_TextContent"];
    for (var i = 0; i < getters.length; i++) {
      var value = null;
      try {
        var getter = object.method(getters[i], 0), owner = getter.class.namespace || "";
        // Game caption implementations may have side effects. Read their string
        // fields below; only Unity/TMP's ordinary UI getters are invoked here.
        if (!/^(?:UnityEngine(?:\.|$)|TMPro$)/.test(owner)) continue;
        value = getter.invoke();
      } catch (_) { continue; }
      if (typeof value === "string" && value.trim()) return value.trim();
      if (exists(value) && typeof value.content === "string" && value.content.trim()) return value.content.trim();
    }
    // Custom LLAS/Jigbox captions are not UnityEngine.UI.Text. Read only
    // existing string fields; never invoke setters, events or game callbacks.
    var klass = object.class, depth = 0;
    while (klass && depth++ < 5) {
      var fields = klass.fields.filter(function (entry) { return entry.type.name === "System.String" && /^(?:m_)?_?(?:text|sourceText|textSource|rawText|content)$/i.test(entry.name); });
      for (var j = 0; j < fields.length; j++) {
        try { var content = object.field(fields[j].name).value; if (exists(content) && typeof content.content === "string" && content.content.trim()) return content.content.trim(); } catch (_) {}
      }
      klass = klass.parent;
    }
    return "";
  }
  function descendantText(object) {
    var values = [];
    runtime.textClasses.forEach(function (klass) {
      if (!klass) return;
      try {
        var children = overloaded(object, "GetComponentsInChildren", ["System.Type", "System.Boolean"], [klass.type.object, false]);
        for (var i = 0; i < children.length && values.length < 24; i++) {
          var child = children.get(i); if (!active(child).active) continue;
          var value = componentText(child);
          if (value && values.indexOf(value) < 0) values.push(value);
        }
      } catch (_) { /* Report object name when its text component is custom. */ }
    });
    return values.join(" | ");
  }
  function allOfType(klass) {
    try { return overloaded(runtime.resources, "FindObjectsOfTypeAll", ["System.Type"], [klass.type.object]); }
    catch (_) { return overloaded(runtime.unityObject, "FindObjectsOfType", ["System.Type"], [klass.type.object]); }
  }
  function numericField(object, name) {
    try {
      var value = object.field(name).value;
      if (typeof value === "number") return Number.isFinite(value) ? value : null;
      if (value && typeof value.field === "function") return Number(value.field("value__").value);
    } catch (_) {}
    return null;
  }
  function nativeFeatureState() {
    var bridge = Process.findModuleByName("libfovmod.so"), game = Process.findModuleByName("libil2cpp.so");
    var result = { bridgeLoaded: !!bridge, gameLoaded: !!game, config: null };
    if (game) {
      var ranges = game.enumerateRanges("rw-");
      for (var i = 0; i < ranges.length; i++) {
        try {
          var p = ranges[i].base;
          if (ranges[i].size < 32 || p.readUtf8String(8) !== "SFOVRW22") continue;
          if (p.add(8).readU32() !== 1 || p.add(12).readU32() !== 32) continue;
          result.config = { magic: "SFOVRW22", version: 1, size: 32,
            min: p.add(16).readFloat(), max: p.add(20).readFloat(),
            fastIntro: p.add(24).readU32(), generation: p.add(28).readU32(),
            writable: ranges[i].protection.indexOf("w") >= 0,
            executable: ranges[i].protection.indexOf("x") >= 0 };
          break;
        } catch (_) {}
      }
    }
    // Read platform-owned getters only; no game setters or callbacks are called.
    try {
      if (typeof Java !== "undefined" && Java.available) Java.performNow(function () {
        var activity = Java.use("com.unity3d.player.UnityPlayer").currentActivity.value;
        if (activity) {
          var preference = Number(activity.getSharedPreferences("fovmod", 0).getInt("orient", 0));
          result.requestedOrientation = Number(activity.getRequestedOrientation());
          if (result.config) result.config.orientation = preference;
        }
      });
    } catch (error) { result.platformReadError = String(error); }
    return result;
  }
// Optional fragment for the existing, main-thread, read-only Unity observer.
// Uses its existing findClass/allOfType/exists/active/maybe/instanceId helpers.
// No game actions, setters, callbacks, scene changes, or player-state writes.
function mvReadField(object, name) {
  if (!object || (object.handle && object.handle.isNull())) return null;
  try { var value = object.field(name).value; return value && value.handle && value.handle.isNull() ? null : value; } catch (_) { return null; }
}
function mvBacking(object, name) { return mvReadField(object, "<" + name + ">k__BackingField"); }
function mvNumber(value) {
  if (value === null || value === undefined) return null;
  var n = Number(value); return Number.isFinite(n) ? n : null;
}
function mvExistingComponentInfo(object) {
  var tr = transform(object), position = maybe(tr, "get_position", null);
  var info = { id: String(instanceId(object)), gameObjectId: String(instanceId(gameObject(object))),
    path: hierarchy(tr), active: active(object).active };
  if (position) info.position = {x: field(position,"x"), y: field(position,"y"), z: field(position,"z")};
  return info;
}
// Read-only additions to mv_observer.fragment.js; same Unity main-thread observer.
// GL/JP metadata verified. No game actions, callbacks, setters, or state writes.
function observeExistingMvExtras(screen,raycaster) {
  var result = { deckRoots: [], suitPickerCells: [], directorAssets: [], errors: [] };
  function collect(type, callback) {
    var klass = findClass(type, true);
    if (!klass) { result.errors.push({type:type,error:"Type absent"}); return; }
    try {
      var objects=allOfType(klass);
      for (var i=0;i<objects.length && i<128;i++) {
        var object=objects.get(i);
        if (exists(object) && active(object).active) callback(object);
      }
    } catch(error) { result.errors.push({type:type,error:String(error)}); }
  }
  collect("LLAS.Scene.LiveMvDeckSelect.LiveMvDeckSelectRoot", function(object) {
    var vo=mvReadField(object,"liveMvDeckSelectVO"),info=mvExistingComponentInfo(object);
    info.liveMasterId=mvNumber(mvBacking(vo,"LiveMasterId"));
    info.standingMemberNum=mvNumber(mvBacking(vo,"StandingMemberNum"));
    info.voClass=vo?fullType(vo):null;
    result.deckRoots.push(info);
  });
  collect("LLAS.SuitChangePopupSuitTileViewCell", function(object) {
    var vo=mvReadField(object,"memberSuitVO"),info=mvExistingComponentInfo(object);
    info.memberId=mvNumber(mvBacking(vo,"MemberMasterId"));
    info.suitId=mvNumber(mvBacking(vo,"MasterId"));
    info.voClass=vo?fullType(vo):null;
    // MemberSuitVO has no IsUnlocked field. Actual active/hittable button and
    // observed successful resulting deck change establish selectability.
    var button=mvReadField(object,"button");
    if(exists(button)) {info.button={id:String(instanceId(button)),path:hierarchy(transform(button)),type:fullType(button)};info.target=mvUiTarget(button,screen,raycaster);}
    result.suitPickerCells.push(info);
  });
  collect("LLAS.Scene.Live.LiveDirector", function(object) {
    var asset=mvReadField(object,"asset"),members=mvBacking(asset,"Members"),info=mvExistingComponentInfo(object);
    info.assetClass=asset?fullType(asset):null;info.members=[];
    // Live3DAssetVO retains the asset VOs; actual instantiated model identity
    // is separately observed via LiveCoreMember + its formation position.
    if(members && typeof members.length === "number") {
      for(var i=0;i<members.length && i<12;i++) {
        var vo=members.get(i),nullable=mvBacking(vo,"SuitId"),suitId=null;
        // System.Nullable<Int32> fields, read only; a missing value stays null.
        try { if(nullable.field("has_value").value===true) suitId=mvNumber(nullable.field("value").value); } catch(_) {}
        info.members.push({memberId:mvNumber(mvBacking(vo,"MemberMasterId")),
          formationPosition:mvNumber(mvBacking(vo,"FormationPosition")),suitId:suitId,voClass:vo?fullType(vo):null});
      }
    }
    result.directorAssets.push(info);
  });
  return result;
}

// Optional read-only MV music/tab observation; GL/JP field names verified.
// Requires the helpers of mv_observer.fragment.js. No actions/callbacks/setters.
function observeExistingMusicRowsAndMvTabs(screen,raycaster) {
  var result={musicRows:[],musicSelection:[],deckTabGroups:[],errors:[]};
  function collect(type,callback) {
    var klass=findClass(type,true);
    if(!klass){result.errors.push({type:type,error:"Type absent"});return;}
    try{var objects=allOfType(klass);for(var i=0;i<objects.length&&i<128;i++){
      var object=objects.get(i);if(exists(object)&&active(object).active)callback(object);
    }}catch(error){result.errors.push({type:type,error:String(error)});}
  }
  collect("LLAS.Scene.LiveMusicSelect.LiveMusicSelectScrollCell",function(object){
    var vo=mvBacking(object,"CellVO"),info=mvExistingComponentInfo(object);
    info.liveMasterId=mvNumber(mvBacking(vo,"LiveMasterId"));
    info.isPlayable=mvBacking(vo,"IsPlayable");
    info.voClass=vo?fullType(vo):null;
    // This cell has no button field. Its existing GameObject/component path
    // and actual jacket/title graphics identify its real visible pointer area.
    // Use only the observer's current projected and raycast-tested hit bounds;
    // do not invent a callback, button reference, or fixed coordinate.
    ["jacket","title"].forEach(function(key){var component=mvReadField(object,key);
      if(exists(component))info[key]={id:String(instanceId(component)),path:hierarchy(transform(component)),type:fullType(component)};
    });
    info.target=mvUiTarget(object,screen,raycaster);
    result.musicRows.push(info);
  });
  // Static GL metadata SHA256 c1ac82ff0b68351ffb3a58fce275b940c26316da64cdfc8201413382afdec14f:
  // both fields reference LLAS.DM.LiveMusicSelectDM+CellVO. Record their
  // independent existing IDs; neither field implies timing or MV readiness.
  collect("LLAS.Scene.LiveMusicSelect.LiveMusicSelectController",function(object){
    var info=mvExistingComponentInfo(object);
    ["currentSelectedCellVO","decidedCellVO"].forEach(function(key){
      var vo=mvReadField(object,key);
      info[key]={liveMasterId:mvNumber(mvBacking(vo,"LiveMasterId")),
        isPlayable:mvBacking(vo,"IsPlayable"),voClass:vo?fullType(vo):null};
    });
    info.noteInputBlocker=nativeMusicBlocker(object);
    result.musicSelection.push(info);
  });
  collect("LLAS.Components.UI.LiveMvDeckTabGroup",function(object){
    var info=mvExistingComponentInfo(object),vos=mvReadField(object,"deckTabVOs"),group=mvReadField(object,"deckSwitchToggleGroup");
    var list=mvReadField(group,"toggles"),items=mvReadField(list,"_items"),size=mvNumber(mvReadField(list,"_size"));
    info.selectedDeckIndex=mvNumber(mvReadField(object,"selectedDeckIndex"));info.tabs=[];
    if(vos&&typeof vos.length==="number")for(var i=0;i<vos.length&&i<8;i++){
      var vo=vos.get(i),entry={index:i,liveMasterId:mvNumber(mvBacking(vo,"LiveMasterId")),deckType:mvNumber(mvBacking(vo,"LiveMvDeckType"))};
      // Existing Setup/OnClickDeckSwitchButton consumes this matching tab index.
      // Record actual referenced toggles, then verify resulting deck VO class.
      if(items&&typeof items.length==="number"&&size!==null&&i<size&&i<items.length){
        var toggle=items.get(i),button=mvReadField(toggle,"button");
        if(exists(toggle))entry.toggle={id:String(instanceId(toggle)),path:hierarchy(transform(toggle)),isOn:mvReadField(toggle,"isOn")};
        if(exists(button)){entry.button={id:String(instanceId(button)),path:hierarchy(transform(button)),type:fullType(button)};entry.target=mvUiTarget(button,screen,raycaster);}
      }
      info.tabs.push(entry);
    }
    result.deckTabGroups.push(info);
  });
  return result;
}

// R8 QA-only prospective native hit model. These helpers never dispatch an
// event, invoke game selection methods, or mutate an existing game object.
function nativeMusicBounds(position,size,lossyScale,pivot) {
  function number(value) { if(typeof value!=="number" || !Number.isFinite(value))throw new Error("Unreadable native music geometry");return Math.fround(value); }
  var x=number(position.x),y=number(position.y),z=number(position.z);
  var width=Math.fround(number(size.x)*number(lossyScale.x)),height=Math.fround(number(size.y)*number(lossyScale.y));
  var px=number(pivot.x),py=number(pivot.y);
  return {min:{x:Math.fround(x-Math.fround(width*px)),y:Math.fround(y-Math.fround(height*py)),z:z},
    max:{x:Math.fround(x+Math.fround(width*Math.fround(1-px))),y:Math.fround(y+Math.fround(height*Math.fround(1-py))),z:z}};
}
function nativeMusicReadableBounds(bounds) {
  return !!bounds && ["min","max"].every(function(side){return bounds[side] && ["x","y","z"].every(function(axis){return typeof bounds[side][axis]==="number" && Number.isFinite(bounds[side][axis]);});});
}
function nativeMusicContains(bounds,point) {
  return nativeMusicReadableBounds(bounds) && ["x","y","z"].every(function(axis){
    return typeof point[axis]==="number" && Number.isFinite(point[axis]) && Math.fround(point[axis])>=bounds.min[axis] && Math.fround(point[axis])<=bounds.max[axis];
  });
}
function nativeMusicBoundedCells(size,capacity,readEntry) {
  var result={complete:false,reason:null,limit:512,size:size,capacity:capacity,entries:[]};
  if(!Number.isInteger(size)||size<1||size>512||!Number.isInteger(capacity)||capacity<size){result.reason="Native managed-cell storage is incomplete or exceeds512";return result;}
  for(var i=0;i<size;i++) {
    var entry;
    try{entry=readEntry(i);}catch(error){result.reason="Unreadable native managed-cell entry at ordinal"+i+": "+String(error);return result;}
    if(!entry || !nativeMusicReadableBounds(entry.nativeBounds)){result.reason="Unreadable native bounds at ordinal"+i;return result;}
    result.entries.push(entry);
  }
  result.complete=true;return result;
}
function nativeMusicFirstContaining(entries,point) {
  for(var i=0;i<entries.length;i++)if(nativeMusicContains(entries[i].nativeBounds,point))return entries[i];
  return null;
}
function nativeMusicCellIdentity(entry) {
  if(!entry)return null;
  var result={};["ordinal","index","positionIndex","rectId","cellId","liveMasterId","activeInHierarchy"].forEach(function(key){result[key]=entry[key];});return result;
}
function nativeMusicScan(entries,intended,point) {
  if(entries.some(function(entry){return !entry||!nativeMusicReadableBounds(entry.nativeBounds);}))return {qualified:false,firstContaining:null,reason:"Native managed-cell geometry is incomplete; no skipped entry"};
  var first=nativeMusicFirstContaining(entries,point),result={qualified:false,firstContaining:nativeMusicCellIdentity(first)};
  if(!first)return Object.assign(result,{reason:"No native managed-cell bounds contain the prospective point"});
  if(first.activeInHierarchy!==true)return Object.assign(result,{reason:"FIRST native containing cell is inactive; no later-cell fallback"});
  if(["ordinal","index","positionIndex","rectId","cellId","liveMasterId"].some(function(key){return first[key]!==intended[key];}))return Object.assign(result,{reason:"FIRST native containing cell differs from intended typed music cell"});
  return Object.assign(result,{qualified:true,reason:"FIRST native containing cell is the intended active typed cell"});
}
function nativeMusicObject(object) {
  if(!exists(object))return null;
  return {id:String(instanceId(object)),type:fullType(object),path:hierarchy(transform(object))};
}
function nativeMusicBlocker(controller) {
  var result={resolved:false,id:null,path:null,activeSelf:null,activeInHierarchy:null,error:null};
  try {
    var blocker=mvReadField(controller,"noteInputBlocker");
    if(!exists(blocker)){result.error="Controller noteInputBlocker unavailable";return result;}
    result.id=String(instanceId(blocker));result.path=hierarchy(transform(blocker));
    result.activeSelf=call(blocker,"get_activeSelf");result.activeInHierarchy=call(blocker,"get_activeInHierarchy");
    result.resolved=typeof result.activeSelf==="boolean" && typeof result.activeInHierarchy==="boolean";
    if(!result.resolved)result.error="Controller noteInputBlocker active state unreadable";
  }catch(error){result.error=String(error);}
  return result;
}
function nativeMusicEventCamera(module) {
  var result={proof:{resolved:false,isNull:null,id:null,path:null,error:null},camera:null};
  try {
    if(!exists(module))throw new Error("Current first raycast module unavailable");
    var getter=module.method("get_eventCamera",0);
    if(!/^UnityEngine(?:\.|$)/.test(getter.class.namespace||""))throw new Error("Non-Unity eventCamera getter is not invoked");
    var camera=getter.invoke();result.proof.resolved=true;result.proof.isNull=!exists(camera);
    result.camera=exists(camera)?camera:nullObject();
    if(exists(camera)){result.proof.id=String(instanceId(camera));result.proof.path=hierarchy(transform(camera));}
  }catch(error){result.proof.error=String(error);}
  return result;
}
function nativeMusicVector(value,axes) {
  var result={};axes.forEach(function(axis){var number=field(value,axis);if(!Number.isFinite(number))throw new Error("Non-finite native geometry");result[axis]=Math.fround(number);});return result;
}
function nativeMusicRect(rect) {
  var tr=transform(rect),position=nativeMusicVector(call(tr,"get_position"),["x","y","z"]);
  var scale=nativeMusicVector(call(tr,"get_lossyScale"),["x","y","z"]),pivot=nativeMusicVector(call(rect,"get_pivot"),["x","y"]);
  var local=call(rect,"get_rect"),size=nativeMusicVector(call(local,"get_size"),["x","y"]);
  var rotation=nativeMusicVector(call(tr,"get_rotation"),["x","y","z","w"]);
  return {rectId:String(instanceId(rect)),path:hierarchy(tr),position:position,lossyScale:scale,pivot:pivot,size:size,rotation:rotation,
    nativeBounds:nativeMusicBounds(position,size,scale,pivot)};
}
function nativeMusicStateVector(object,name) {
  try{var value=mvReadField(object,name);return value?nativeMusicVector(value,["x","y"]):null;}catch(_){return null;}
}
function nativeMusicCanvasCamera(view) {
  var tr=transform(view),count=0;
  while(exists(tr)&&count++<48) {
    var canvas=component(gameObject(tr),runtime.canvas);
    if(exists(canvas)) {
      if(Number(call(canvas,"get_renderMode"))===0)return nullObject();
      var camera=call(canvas,"get_worldCamera");
      if(!exists(camera))throw new Error("Native viewport Canvas camera unresolved; no Camera.main fallback");
      return camera;
    }
    tr=maybe(tr,"get_parent",null);
  }
  throw new Error("Native viewport Canvas unavailable");
}
function nativeMusicViewport(view,screen,camera) {
  var tr=transform(view),original=rawRect(tr,{camera:camera},screen);
  var clipped=intersect(original,{left:0,top:0,right:screen.width,bottom:screen.height});
  var parent=tr,count=0,alpha=1,groupsInteractable=true,blocksRaycasts=true,ignore=false;
  while(exists(parent)&&count++<48) {
    var go=gameObject(parent),group=component(go,runtime.canvasGroup);
    if(!ignore&&exists(group)&&maybe(group,"get_enabled",true)) {
      alpha*=Number(call(group,"get_alpha"));groupsInteractable=groupsInteractable&&call(group,"get_interactable")!==false;
      blocksRaycasts=blocksRaycasts&&call(group,"get_blocksRaycasts")!==false;ignore=!!call(group,"get_ignoreParentGroups");
    }
    if(parent!==tr) {
      var mask=component(go,runtime.rectMask)||component(go,runtime.mask);
      if(exists(mask)&&maybe(mask,"get_isActiveAndEnabled",true))clipped=intersect(clipped,rawRect(parent,{camera:camera},screen));
    }
    parent=maybe(parent,"get_parent",null);
  }
  clipped.width=Math.max(0,clipped.right-clipped.left);clipped.height=Math.max(0,clipped.bottom-clipped.top);
  return {bounds:original,visibleBounds:clipped,visible:clipped.width>=1&&clipped.height>=1&&alpha>.001,
    alpha:alpha,groupsInteractable:groupsInteractable,blocksRaycasts:blocksRaycasts};
}
function observeNativeMusicSelection(screen,rows) {
  var result={proof:{schema:1,complete:false,reason:null,scope:"PROSPECTIVE_NATIVE_HIT_PREDICTION",owners:[]},owners:[]};
  if(screen.scene!=="LiveMusicSelect"){result.proof.reason="Native music selection is outside LiveMusicSelect";return result;}
  try {
    var klass=findClass("LLAS.Components.UI.ProductMusicScrollView",true);
    if(!klass)throw new Error("ProductMusicScrollView metadata unavailable");
    var objects=allOfType(klass),candidates=[];
    if(objects.length>32)throw new Error("Native scroll ownership enumeration exceeds32");
    for(var i=0;i<objects.length && i<32;i++) {
      var view=objects.get(i);if(!exists(view)||!active(view).active)continue;
      var geometry=nativeMusicViewport(view,screen,nativeMusicCanvasCamera(view));if(!geometry.visible)continue;
      candidates.push({view:view,geometry:geometry});
    }
    if(candidates.length!==1)throw new Error("Native music scroll ownership is absent or ambiguous");
    var current=candidates[0],view=current.view,model=mvReadField(view,"model"),proxy=mvReadField(view,"inputProxy"),transition=mvReadField(view,"transition");
    if(!exists(model)||!exists(proxy)||!exists(transition))throw new Error("Owned native model/inputProxy/transition reference unavailable");
    if(!descendsFrom(gameObject(proxy),view))throw new Error("Input proxy is outside the owned music scroll view");
    var proxyView=mvReadField(proxy,"ScrollSelectView");
    if(!exists(proxyView)||String(instanceId(proxyView))!==String(instanceId(view)))throw new Error("Input proxy reverse ScrollSelectView ownership differs");
    var ownership={viewId:String(instanceId(view)),modelId:String(instanceId(model)),inputProxyId:String(instanceId(proxy)),
      inputProxyGameObjectId:String(instanceId(gameObject(proxy))),transitionId:String(instanceId(transition)),inputProxyViewId:String(instanceId(proxyView))};
    var proof={ownership:ownership,view:nativeMusicObject(view),model:nativeMusicObject(model),inputProxy:nativeMusicObject(proxy),transition:nativeMusicObject(transition),
      viewport:current.geometry.visibleBounds,modelState:{selectedCellIndex:mvNumber(mvBacking(model,"SelectedCellIndex")),
        moveToCellIndex:mvNumber(mvBacking(model,"MoveToCellIndex")),scrollPosition:nativeMusicStateVector(model,"<ScrollPosition>k__BackingField"),
        selectedCellPositionDelta:nativeMusicStateVector(model,"selectedCellPositionDelta"),cachedScrollSelectCell:nativeMusicObject(mvReadField(model,"cachedScrollSelectCell"))},
      storedProxyState:{scope:"STORED_STATE_NOT_CURRENT_INPUT_EVENT",pressPosition:null,movedOutOfTolerance:mvReadField(proxy,"movedOutOfTolerance"),
        pressedPointerId:mvReadField(proxy,"PressedPointerId"),prevPressedPointerId:mvReadField(proxy,"PrevPressedPointerId"),isDragging:mvBacking(proxy,"IsDragging")}};
    try{var press=mvReadField(proxy,"pressPosition");proof.storedProxyState.pressPosition=press?nativeMusicVector(press,["x","y","z"]):null;}catch(_){}
    var list=mvReadField(model,"managedCells");if(!exists(list))throw new Error("Native managedCells list unavailable");
    var type=fullType(list),items=mvReadField(list,"_items"),size=mvNumber(mvReadField(list,"_size"));
    if(!/^System\.Collections\.Generic\.List(?:`|<)/.test(type)||!items||typeof items.length!=="number")throw new Error("Native managedCells runtime list layout unproved");
    var seen={},cellRefs={};
    var cells=nativeMusicBoundedCells(size,items.length,function(ordinal){
      var entry=items.get(ordinal);if(!exists(entry))throw new Error("Null native list entry");
      var rect=mvBacking(entry,"RectTransform"),cell=mvReadField(entry,"scrollSelectCell");
      if(!exists(rect))throw new Error("Native managed-cell RectTransform unavailable");
      if(!descendsFrom(gameObject(rect),view))throw new Error("Native cell is outside owned scroll");
      var geometry=nativeMusicRect(rect),rectId=geometry.rectId;
      if(seen[rectId])throw new Error("Duplicate native managed-cell RectTransform");seen[rectId]=true;
      var index=mvNumber(mvBacking(entry,"Index")),positionIndex=mvNumber(mvBacking(entry,"PositionIndex"));
      if(!Number.isInteger(index)||!Number.isInteger(positionIndex))throw new Error("Native cell index is unavailable");
      var go=gameObject(rect),activeSelf=call(go,"get_activeSelf"),activeInHierarchy=call(go,"get_activeInHierarchy");
      if(typeof activeSelf!=="boolean"||typeof activeInHierarchy!=="boolean")throw new Error("Native cell active state unavailable");
      var vo=exists(cell)?mvBacking(cell,"CellVO"):null,liveId=mvNumber(mvBacking(vo,"LiveMasterId"));
      var cellId=exists(cell)?String(instanceId(cell)):null;
      if(activeInHierarchy && (!exists(cell)||!Number.isInteger(liveId)))throw new Error("Active native cell VO binding unavailable");
      if(exists(cell) && !descendsFrom(gameObject(cell),view))throw new Error("Referenced native cell VO is outside the owned scroll view");
      var value={ordinal:ordinal,index:index,positionIndex:positionIndex,rectId:rectId,cellId:cellId,liveMasterId:liveId,
        rectGameObjectId:String(instanceId(go)),cellGameObjectId:exists(cell)?String(instanceId(gameObject(cell))):null,
        bindingSource:"Exact managed entry RectTransform and scrollSelectCell references; no same-GameObject assumption",
        isPlayable:mvBacking(vo,"IsPlayable"),activeSelf:activeSelf,activeInHierarchy:activeInHierarchy,
        path:geometry.path,nativeBounds:geometry.nativeBounds,geometry:geometry,voClass:vo?fullType(vo):null};
      if(exists(cell))cellRefs[cellId]={cell:cell,rect:rect};return value;
    });
    cells.runtimeType=type;proof.managedCells=cells;result.proof.owners.push(proof);
    if(!cells.complete)throw new Error(cells.reason);
    result.owners.push({view:view,model:model,proxy:proxy,transition:transition,geometry:current.geometry,proof:proof,cellRefs:cellRefs});
    result.proof.complete=true;
  }catch(error){result.proof.reason=String(error);}
  return result;
}
function nativeMusicRaycast(screen,point,raycaster,owner) {
  if(typeof raycaster.inspect!=="function")return {qualified:false,reason:"Current native raycast inspection unavailable",proof:{available:false}};
  var query=raycaster.inspect(point),proof=query.proof;
  if(!proof.available || !query.hit || !query.module)return {qualified:false,reason:"Current first graphic/raycaster unavailable",proof:proof};
  var camera=nativeMusicEventCamera(query.module);proof.eventCamera=camera.proof;
  if(!camera.proof.resolved)return {qualified:false,reason:"Current event camera could not be resolved",proof:proof};
  var execute=findClass("UnityEngine.EventSystems.ExecuteEvents",true),handler=findClass("UnityEngine.EventSystems.IDragHandler",true);
  if(!execute||!handler)return {qualified:false,reason:"Current Unity drag-handler metadata unavailable",proof:proof};
  var drag=execute.method("GetEventHandler",1).inflate(handler).invoke(query.hit);
  if(!exists(drag)||String(instanceId(drag))!==String(instanceId(gameObject(owner.proxy))))return {qualified:false,reason:"Current first graphic drag owner is not the owned inputProxy",proof:proof};
  var rect=component(drag,runtime.rectTransform);if(!exists(rect))return {qualified:false,reason:"Owned drag-handler RectTransform plane unavailable",proof:proof};
  proof.dragOwner=nativeMusicObject(drag);proof.dragRect=nativeMusicRect(rect);
  return {qualified:true,proof:proof,camera:camera.camera,cameraProof:camera.proof,drag:drag,rect:rect,module:query.module};
}
function nativeMusicWorldPoint(rect,camera,point,screen) {
  var storage=Memory.alloc(runtime.vector3.valueTypeSize),value=new Il2Cpp.ValueType(storage,runtime.vector3.type);
  ["x","y","z"].forEach(function(axis){value.field(axis).value=0;});
  var unityPoint=vector(runtime.vector2,point.x,screen.height-point.y);
  var converted=runtime.rectUtility.method("ScreenPointToWorldPointInRectangle",4).invoke(rect,unityPoint,camera,new Il2Cpp.Reference(storage,runtime.vector3.type));
  return {converted:converted===true,point:nativeMusicVector(value,["x","y","z"]),unityScreenPoint:{x:point.x,y:screen.height-point.y},scope:"OBSERVER_OWNED_OUT_STORAGE"};
}
function nativeMusicHit(screen,state,contexts,row,raycaster) {
  var result={qualified:false,reason:null,scope:"PROSPECTIVE_NATIVE_HIT_PREDICTION",intendedLiveMasterId:row.liveMasterId,cellsComplete:false,
    ownership:null,intended:null,firstContaining:null,worldPoint:null,screenPoint:null,orderedCells:[],listSignature:null};
  try {
    if(!state.nativeMusicSelection.complete||contexts.owners.length!==1)throw new Error(state.nativeMusicSelection.reason||"Native music ownership incomplete");
    var owner=contexts.owners[0],entries=owner.proof.managedCells.entries;
    result.nativeStateBefore={scope:"READ_ONLY_STORED_STATE_NOT_CURRENT_INPUT_EVENT",frame:screen.frame,
      modelState:owner.proof.modelState,storedProxyState:owner.proof.storedProxyState,
      transition:owner.proof.transition,controllerSelection:state.musicSelection};
    result.cellsComplete=owner.proof.managedCells.complete;result.orderedCells=entries;
    result.listSignature=JSON.stringify(entries.map(function(entry){return {identity:nativeMusicCellIdentity(entry),nativeBounds:entry.nativeBounds};}));
    var intended=entries.filter(function(entry){return entry.cellId===row.id && entry.liveMasterId===row.liveMasterId;});
    if(intended.length!==1)throw new Error("Intended typed row has no unique native managed-cell binding");
    intended=intended[0];result.intended=nativeMusicCellIdentity(intended);
    if(intended.activeInHierarchy!==true||intended.isPlayable!==true)throw new Error("Intended native cell is inactive or its VO is not playable");
    var viewport=owner.geometry.visibleBounds;
    function inside(point){return Number.isInteger(point.x)&&Number.isInteger(point.y)&&point.x>=Math.max(0,viewport.left)&&point.x<Math.min(screen.width,viewport.right)&&point.y>=Math.max(0,viewport.top)&&point.y<Math.min(screen.height,viewport.bottom);}
    var centers=[row.target&&row.target.center,{x:(viewport.left+viewport.right)/2,y:(viewport.top+viewport.bottom)/2}],resolved=null;
    result.seedRaycasts=[];
    for(var i=0;i<centers.length;i++)if(centers[i]) {
      var seed={x:Math.round(centers[i].x),y:Math.round(centers[i].y)};if(!inside(seed))continue;
      var candidate=nativeMusicRaycast(screen,seed,raycaster,owner);result.seedRaycasts.push({screenPoint:seed,qualified:candidate.qualified,reason:candidate.reason||null,proof:candidate.proof});
      if(candidate.qualified){resolved=candidate;break;}
    }
    if(!resolved)throw new Error("No current owned inputProxy event-camera/drag-plane witness");
    var inputGeometry=nativeMusicViewport(owner.view,screen,resolved.camera);viewport=inputGeometry.visibleBounds;
    if(!inputGeometry.visible||!inputGeometry.groupsInteractable||!inputGeometry.blocksRaycasts)throw new Error("Current native input viewport is not actionable");
    result.viewport=viewport;
    var bounds=intended.nativeBounds;
    if(!(bounds.min.x<bounds.max.x && bounds.min.y<bounds.max.y && bounds.min.z===bounds.max.z))throw new Error("Intended signed native bounds are empty or inverted");
    var world=Memory.alloc(runtime.vector3.valueTypeSize),center=new Il2Cpp.ValueType(world,runtime.vector3.type);
    ["x","y","z"].forEach(function(axis){center.field(axis).value=Math.fround(Math.fround(bounds.min[axis]+bounds.max[axis])*.5);});
    var projected=runtime.rectUtility.method("WorldToScreenPoint",2).invoke(resolved.camera,center);
    var point={x:Math.round(field(projected,"x")),y:Math.round(screen.height-field(projected,"y"))};result.screenPoint=point;
    if(!inside(point))throw new Error("Derived integer native point is outside the current visible viewport");
    var final=nativeMusicRaycast(screen,point,raycaster,owner);result.firstGraphic=final.proof;
    if(!final.qualified)throw new Error(final.reason);
    if(JSON.stringify(final.cameraProof)!==JSON.stringify(resolved.cameraProof)||String(instanceId(final.rect))!==String(instanceId(resolved.rect))||String(instanceId(final.module))!==String(instanceId(resolved.module)))throw new Error("Derived point changed current raycaster/event-camera/drag-plane ownership");
    result.ownership=Object.assign({},owner.proof.ownership,{dragOwnerId:String(instanceId(final.drag)),dragRectId:String(instanceId(final.rect)),
      raycasterId:String(instanceId(final.module)),eventCamera:final.cameraProof});
    result.dragPlane=final.proof.dragRect;
    var converted=nativeMusicWorldPoint(final.rect,final.camera,point,screen);result.conversion=converted;result.worldPoint=converted.point;
    if(!converted.converted)throw new Error("Pure Unity point conversion returned false; zero/fallback is diagnostic only");
    var scan=nativeMusicScan(entries,intended,converted.point);result.firstContaining=scan.firstContaining;
    if(!scan.qualified)throw new Error(scan.reason);
    if(converted.point.x===bounds.min.x||converted.point.x===bounds.max.x||converted.point.y===bounds.min.y||converted.point.y===bounds.max.y)throw new Error("Derived point is on a precision-sensitive native XY boundary");
    var activity=active(owner.proxy),target={id:String(instanceId(owner.proxy)),name:text(maybe(owner.proxy,"get_name",null)),path:hierarchy(transform(owner.proxy)),
      active:activity.active,enabled:activity.enabled,visible:activity.active&&activity.enabled&&inputGeometry.visible,
      bounds:viewport,visibleBounds:viewport,center:point,groupsInteractable:inputGeometry.groupsInteractable,blocksRaycasts:inputGeometry.blocksRaycasts};
    if(!target.active||!target.enabled||!target.visible)throw new Error("Current owned inputProxy is unavailable");
    target.hit={available:true,hittable:true,hits:final.proof.hits,firstName:final.proof.firstName,firstPath:final.proof.firstPath};
    result.qualified=true;result.reason=scan.reason;return {proof:result,target:target};
  }catch(error){result.reason=String(error);return {proof:result,target:row.target};}
}

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

function observeExistingMvState(screen,nativeContext) {
  screen = screen || metadata();
  var raycaster = makeRaycaster(screen);
  var result = { deckCells: [], pickerCells: [], liveMembers: [], errors: [] };
  var specifications = [
    ["LLAS.Components.UI.LiveMvDeckMemberParts", function (object) {
      var vo = mvReadField(object,"deckMemberVO"), suit = mvBacking(vo,"MemberSuitVO");
      var info = mvExistingComponentInfo(object);
      info.memberId = mvNumber(mvBacking(vo,"MemberMasterId"));
      info.formationPosition = mvNumber(mvBacking(vo,"Position"));
      info.suitId = mvNumber(mvBacking(suit,"MasterId"));
      info.voClass = vo ? fullType(vo) : null;
      // Button references identify the actual visible targets. Existing
      // snapshot projection can compute their current RectTransform bounds.
      ["memberButton","suitButton"].forEach(function (key) {
        var button = mvReadField(object,key);
        if (exists(button)) info[key] = mvUiTarget(button,screen,raycaster);
      });
      result.deckCells.push(info);
    }],
    ["LLAS.Scene.LiveMvDeckSelect.LiveMvDeckMemberSelectCategorizedListViewCell", function (object) {
      var vo = mvBacking(object,"liveMvMemberVO"), info = mvExistingComponentInfo(object);
      var thumbnail = mvBacking(vo,"MemberThumbnailVO");
      info.memberId = mvNumber(mvBacking(vo,"MemberMasterId"));
      if (info.memberId === null) info.memberId = mvNumber(mvBacking(thumbnail,"MemberMasterId"));
      try { info.target = mvUiTarget(object,screen,raycaster); } catch (_) {}
      // If a regional VO computes this getter rather than storing it, record
      // null and the real class; do not invent an ID or call a selection action.
      info.voClass = vo ? fullType(vo) : null;
      result.pickerCells.push(info);
    }],
    ["LLAS.Scene.Live.Components.LiveCoreMember", function (object) {
      var memberInfo = mvReadField(object,"memberInfo"), info = mvExistingComponentInfo(object);
      info.formationPosition = mvNumber(mvBacking(memberInfo,"FormationPosition"));
      result.liveMembers.push(info);
    }]
  ];
  specifications.forEach(function (specification) {
    var klass = findClass(specification[0],true);
    if (!klass) { result.errors.push({type:specification[0],error:"Type absent"}); return; }
    try {
      var objects = allOfType(klass);
      for (var i=0;i<objects.length && i<128;i++) {
        var object = objects.get(i);
        if (exists(object) && active(object).active) specification[1](object);
      }
    } catch(error) { result.errors.push({type:specification[0],error:String(error)}); }
  });
  var catalogs=observeExistingSuitCatalogs();result.suitCatalogs=catalogs.suitCatalogs;result.suitCatalogErrors=catalogs.errors;
  var extras=observeExistingMvExtras(screen,raycaster);
  result.deckRoots=extras.deckRoots;result.suitPickerCells=extras.suitPickerCells;result.directorAssets=extras.directorAssets;
  result.errors=result.errors.concat(extras.errors);
  result.standingMemberNum=extras.deckRoots.length===1?extras.deckRoots[0].standingMemberNum:null;
  result.liveMasterId=extras.deckRoots.length===1?extras.deckRoots[0].liveMasterId:null;
  var music=observeExistingMusicRowsAndMvTabs(screen,raycaster);result.musicRows=music.musicRows;result.musicSelection=music.musicSelection;result.deckTabGroups=music.deckTabGroups;result.errors=result.errors.concat(music.errors);
  var nativeMusic=observeNativeMusicSelection(screen,result.musicRows);result.nativeMusicSelection=nativeMusic.proof;
  if(nativeContext)nativeContext.owners=nativeMusic.owners;
  result.liveMembers.forEach(function(member){
    var found=[];
    extras.directorAssets.forEach(function(director){director.members.forEach(function(asset){
      if(asset.formationPosition===member.formationPosition && asset.memberId!==null && asset.suitId!==null) found.push({asset:asset,path:director.path});
    });});
    if(found.length===1){member.memberId=found[0].asset.memberId;member.suitId=found[0].asset.suitId;member.assetIdentitySource=found[0].path;}
  });
  return result;
}

function mvUiTarget(object,screen,raycaster) {
  var geometry = rectAndClipping(transform(object),screen), activity = active(object);
  var target = {id:String(instanceId(object)),name:text(maybe(object,"get_name",null)),path:hierarchy(transform(object)),
    active:activity.active,enabled:activity.enabled,visible:activity.active && activity.enabled && geometry.visible,
    bounds:geometry.bounds,visibleBounds:geometry.visibleBounds,center:geometry.center,
    groupsInteractable:geometry.groupsInteractable,blocksRaycasts:geometry.blocksRaycasts};
  if (target.visible && raycaster.available) target.hit = raycaster.test(target.center,object);
  return target;
}
function pickExistingMvTarget(query) {
  query = query || {}; var screen = metadata(),nativeContext={owners:[]},state = observeExistingMvState(screen,nativeContext), matches = [];
  if (query.role === "member" || query.role === "suit") {
    state.deckCells.forEach(function(cell) {
      if (cell.formationPosition === Number(query.formationPosition) && /DeckMemberCustomVO$/.test(cell.voClass || "")) {
        var target = cell[query.role + "Button"]; if (target) matches.push({target:target,cell:cell});
      }
    });
  } else if (query.role === "picker") {
    state.pickerCells.forEach(function(cell) {
      if (cell.memberId === Number(query.memberId) && cell.target) matches.push({target:cell.target,cell:cell});
    });
  } else if(query.role === "suitPicker") {
    state.suitPickerCells.forEach(function(cell){
      if(cell.suitId===Number(query.suitId) && (query.memberId===undefined || cell.memberId===Number(query.memberId)) && cell.target) matches.push({target:cell.target,cell:cell});
    });
  } else if(query.role === "music") {
    state.musicRows.forEach(function(cell){if(cell.liveMasterId===Number(query.liveMasterId) && cell.isPlayable===true && cell.target) matches.push({target:cell.target,cell:cell});});
  } else if(query.role === "customTab") {
    state.deckTabGroups.forEach(function(group){group.tabs.forEach(function(tab){if(tab.deckType===2 && tab.target)matches.push({target:tab.target,cell:tab});});});
  } else throw new Error("Unknown read-only MV picker role");
  if(query.role!=="music")matches = matches.filter(function(entry) {var t=entry.target;return t.active && t.enabled && t.visible && t.groupsInteractable && t.blocksRaycasts && t.hit && t.hit.available && t.hit.hittable;});
  if (matches.length !== 1) throw new Error(JSON.stringify({error:"MV target absent, obscured or ambiguous",query:query,matches:matches.length,state:state,screen:screen}));
  var musicHit=query.role==="music"?nativeMusicHit(screen,state,nativeContext,matches[0].cell,makeRaycaster(screen)):null;
  var target=musicHit?musicHit.target:matches[0].target;
  return {timestampMs:Date.now(),screen:screen,target:target,catalog:matches[0].cell,nativeMusicHit:musicHit?musicHit.proof:null,
    input:{method:"adb shell input tap",x:target.center.x,y:target.center.y},
    coordinateSource:"Existing MV model identity and live RectTransform/raycast geometry; no selection method invoked"};
}

// Read-only fields verified in GL/JP metadata: Jigbox.Tween.TweenColor -> TweenBase<Color>
// -> PeriodicMovement<...>, not DG.Tweening.Tween. No callbacks/setters invoked.
function jigboxTweenFields(tween) {
  var behaviour=mvReadField(tween,"behaviour");
  return {id:tween.handle.toString(),type:fullType(tween),duration:numericField(tween,"duration"),
    progressTime:behaviour?numericField(behaviour,"progressTime"):null,
    deltaTime:behaviour?numericField(behaviour,"<DeltaTime>k__BackingField"):null,
    lastCompleteCount:behaviour?numericField(behaviour,"<LastCompleteCount>k__BackingField"):null,
    loopCount:behaviour?numericField(behaviour,"<LoopCount>k__BackingField"):null};
}
function splashFadeRGBA(splash) {
  var image=mvReadField(splash,"fade"),color=maybe(image,"get_color",null);
  if(!color)return null;
  return {r:numericField(color,"r"),g:numericField(color,"g"),b:numericField(color,"b"),a:numericField(color,"a")};
}

  function observeDownloadSettings(screen) {
    var result=[],raycaster=makeRaycaster(screen);
    // The first-login dialog and the normal settings dialog have distinct
    // observed MonoBehaviour types with the same serialized caption/toggle fields.
    ["LLAS.ModeSelectableDownloadConfirmPopup","LLAS.DownloadSettingPopup"].forEach(function(typeName){
      var klass=findClass(typeName,true);if(!klass)return;
      var objects=allOfType(klass);
      for(var i=0;i<objects.length && i<12;i++) {
        var popup=objects.get(i);if(!active(popup).active)continue;
        var info={id:String(instanceId(popup)),type:typeName,path:hierarchy(transform(popup)),options:[],toggles:[],downloadType:numericField(popup,"downloadType")};
        ["fullDownloadItemText","lightnessDownloadItemText","autoDeleteDownloadItemText"].forEach(function(name){
          var caption=mvReadField(popup,name),view=mvReadField(caption,"textView");
          if(exists(view))info.options.push({role:name,referencePath:hierarchy(transform(caption)),
            path:hierarchy(transform(view)),text:componentText(view)});
        });
        var group=mvReadField(popup,"productToggleGroup"),list=mvReadField(group,"toggles"),items=mvReadField(list,"_items"),size=mvNumber(mvReadField(list,"_size"));
        if(items&&typeof items.length==="number"&&size!==null)for(var j=0;j<size&&j<items.length&&j<8;j++) {
          var toggle=items.get(j),button=mvReadField(toggle,"button");
          var entry={path:hierarchy(transform(toggle)),isOn:mvReadField(toggle,"isOn"),label:exists(button)?descendantText(button):""};
          if(exists(button))entry.target=mvUiTarget(button,screen,raycaster);
          info.toggles.push(entry);
        }
        result.push(info);
      }
    });
    return result;
  }
  function featureState() {
    var result = { native: nativeFeatureState(), aspectCorrectors: [], splashScreens: [], mv:observeExistingMvState(), downloadSettings:cachedMainRequested?observeDownloadSettings(metadata()):[], diagnostics: [] };
    var aspect = findClass("LLAS.Scene.Live.Components.CameraAspectCorrector", true);
    if (aspect) try {
      var objects = allOfType(aspect);
      for (var i = 0; i < objects.length && i < 128; i++) {
        var object = objects.get(i), state = active(object);
        if (!state.active) continue;
        var item = { id: String(instanceId(object)), path: hierarchy(transform(object)), active: state.active,
          enabled:maybe(object,"get_enabled",null)===true,
          mode: numericField(object, "mode"), correction: numericField(object, "<Correction>k__BackingField"),
          defaultOrthographicSize: numericField(object, "defaultOrthographicSize") };
        try {
          var camera = object.field("target").value;
          item.camera = { id:String(instanceId(camera)),fieldOfView: Number(maybe(camera, "get_fieldOfView", NaN)),
            orthographicSize: Number(maybe(camera, "get_orthographicSize", NaN)),
            orthographic: !!maybe(camera, "get_orthographic", false),
            active:maybe(gameObject(camera),"get_activeInHierarchy",false)===true,
            enabled:maybe(camera,"get_enabled",null)===true,
            pixelWidth:Number(maybe(camera,"get_pixelWidth",NaN)),pixelHeight:Number(maybe(camera,"get_pixelHeight",NaN)) };
          var texture=maybe(camera,"get_targetTexture",undefined);
          item.camera.targetTextureKnown=texture!==undefined;
          item.camera.onScreenDefaultTarget=texture!==undefined && !exists(texture);
          item.camera.targetTexturePointer=exists(texture)?texture.handle.toString():null;
        } catch (_) {}
        result.aspectCorrectors.push(item);
      }
    } catch (error) { result.diagnostics.push({type:"aspect", error:String(error)}); }
    var splash = findClass("LLAS.Scene.Title.SplashScreen", true);
    if (splash) try {
      var screens = allOfType(splash);
      for (var j = 0; j < screens.length && j < 24; j++) {
        var screen = screens.get(j), state2 = active(screen);
        if (!state2.active) continue;
        var sample = { id: String(instanceId(screen)), path: hierarchy(transform(screen)), active: true,
          fadeDuration: numericField(screen,"fadeDuration"), splashDuration:numericField(screen,"splashDuration"),
          intervalDuration:numericField(screen,"intervalDuration"), skipDuration:numericField(screen,"skipDuration") };
        try {
          var tween = screen.field("fadeTween").value;
          if (exists(tween)) sample.tween = jigboxTweenFields(tween);
        } catch (_) {}
        sample.fadeRGBA=splashFadeRGBA(screen);
        result.splashScreens.push(sample);
      }
    } catch (error) { result.diagnostics.push({type:"splash", error:String(error)}); }
    return result;
  }
  var introTrace = { samples: [], startedMs: null, lastError: null }, introTimer = null, introPending = false;
  function beginIntroTrace() {
    if (introTimer) clearInterval(introTimer);
    introTrace = { samples: [], startedMs:Date.now(), lastError:null };
    introTimer = setInterval(function () {
      if (introPending || introTrace.samples.length >= 3000 || Date.now()-introTrace.startedMs > 180000) return;
      introPending = true;
      onMain(function () {
        var klass=findClass("LLAS.Scene.Title.SplashScreen",true), items=[];
        if (klass) {
          var objects=allOfType(klass);
          for(var i=0;i<objects.length && i<24;i++) {
            var object=objects.get(i); if(!active(object).active) continue;
            var item={id:String(instanceId(object)),fadeDuration:numericField(object,"fadeDuration"),splashDuration:numericField(object,"splashDuration")};
            var tween=mvReadField(object,"fadeTween");
            if(exists(tween)) item.tween=jigboxTweenFields(tween);
            item.fadeRGBA=splashFadeRGBA(object);
            items.push(item);
          }
        }
        var sample={timestampMs:Date.now(),screen:metadata(),config:nativeFeatureState().config,splashScreens:items};
        if(items.length || introTrace.samples.length<3 || (introTrace.samples.length && introTrace.samples[introTrace.samples.length-1].splashScreens.length)) introTrace.samples.push(sample);
      }).catch(function(error){introTrace.lastError=String(error);}).finally(function(){introPending=false;});
    },25);
    return {startedMs:introTrace.startedMs,intervalMs:25,scope:"Read-only main-thread splash/tween fields; no callbacks or setters"};
  }
  function endIntroTrace() { if(introTimer)clearInterval(introTimer);introTimer=null;return Object.assign({},introTrace,{pendingManagedWork:introPending||initPending}); }
  function discoverActiveCustomButtons() {
    if (!runtime.rectTransform || !runtime.component) return [];
    var names = [], seen = {}, rects = allOfType(runtime.rectTransform), inspected = 0;
    for (var i = 0; i < rects.length && inspected < 600 && names.length < 24; i++) {
      var rect = rects.get(i); if (!active(rect).active) continue; inspected++;
      try {
        var components = overloaded(gameObject(rect), "GetComponents", ["System.Type"], [runtime.component.type.object]);
        for (var j = 0; j < components.length && names.length < 24; j++) {
          var object = components.get(j); if (!exists(object)) continue;
          var name = fullType(object);
          if (/button|click|touchable|eventtrigger/i.test(name) && !seen[name] && DEFAULT_TYPES.indexOf(name) < 0) { seen[name] = true; names.push(name); }
        }
      } catch (_) {}
    }
    return names;
  }
  function descendsFrom(object, target) {
    var tr = transform(object), goal = gameObject(target).handle, count = 0;
    while (exists(tr) && count++ < 64) {
      if (gameObject(tr).handle.equals(goal)) return true;
      tr = maybe(tr, "get_parent", null);
    }
    return false;
  }
  function makeRaycaster(screen) {
    try {
      if (!runtime.eventSystem || !runtime.pointerData || !runtime.raycastResult) throw new Error("Unity EventSystem metadata is unavailable");
      var system = call(runtime.eventSystem, "get_current");
      if (!exists(system)) throw new Error("No current Unity EventSystem");
      var data = runtime.pointerData.alloc(); call(data, ".ctor", [system]);
      var listClass = Il2Cpp.corlib.class("System.Collections.Generic.List`1").inflate(runtime.raycastResult);
      var results = listClass.alloc(); call(results, ".ctor");
      return { available: true, test: function (point, target) {
        call(data, "set_position", [vector(runtime.vector2, point.x, screen.height - point.y)]);
        call(system, "RaycastAll", [data, results]);
        var count = Number(call(results, "get_Count"));
        if (!count) return { available: true, hittable: false, hits: 0 };
        var first = call(results, "get_Item", [0]);
        var hit = maybe(first, "get_gameObject", null);
        if (!exists(hit)) return { available: true, hittable: false, hits: count };
        return { available: true, hittable: descendsFrom(hit, target), hits: count,
          firstName: text(maybe(hit, "get_name", null)), firstPath: hierarchy(transform(hit)) };
      }, inspect: function (point) {
        call(data,"set_position",[vector(runtime.vector2,point.x,screen.height-point.y)]);
        call(system,"RaycastAll",[data,results]);
        var count=Number(call(results,"get_Count")),proof={available:true,hits:count,screenPoint:{x:point.x,y:point.y},
          unityScreenPoint:{x:point.x,y:screen.height-point.y},scope:"SYNTHETIC_READ_ONLY_RAYCAST_QUERY_NOT_ACTUAL_INPUT"};
        if(!count)return {proof:proof,hit:null,module:null};
        var first=call(results,"get_Item",[0]),hit=maybe(first,"get_gameObject",null),module=mvReadField(first,"module");
        proof.firstId=exists(hit)?String(instanceId(hit)):null;proof.firstName=exists(hit)?text(maybe(hit,"get_name",null)):null;
        proof.firstPath=exists(hit)?hierarchy(transform(hit)):null;proof.raycaster=nativeMusicObject(module);
        ["distance","depth","sortingLayer","sortingOrder","index"].forEach(function(key){proof[key]=mvNumber(mvReadField(first,key));});
        ["worldPosition","worldNormal"].forEach(function(key){try{var value=mvReadField(first,key);proof[key]=value?nativeMusicVector(value,["x","y","z"]):null;}catch(_){proof[key]=null;}});
        return {proof:proof,hit:hit,module:module};
      } };
    } catch (error) { return { available: false, error: String(error), test: function () { return { available: false, hittable: null, error: String(error) }; } }; }
  }
  function metadata() {
    var scene = null;
    try { scene = text(call(call(runtime.sceneManager, "GetActiveScene"), "get_name")); } catch (_) {}
    return { width: Number(call(runtime.screen, "get_width")), height: Number(call(runtime.screen, "get_height")),
      orientation: Number(maybe(runtime.screen, "get_orientation", -1)), scene: scene,
      frame: Number(maybe(runtime.time, "get_frameCount", -1)), unityVersion: Il2Cpp.unityVersion };
  }
  function snapshot(options) {
    options = options || {};
    var screen = metadata(), nodes = [], diagnostics = [], seen = {}, maxNodes = Math.min(3000, Math.max(1, Number(options.maxNodes) || 1000));
    var customTypes = options.customButtons === false ? [] : discoverActiveCustomButtons();
    var types = DEFAULT_TYPES.concat(customTypes, Array.isArray(options.extraTypes) ? options.extraTypes.slice(0, 12) : []);
    if (options.allSelectables) types.push("UnityEngine.UI.Selectable");
    var raycaster = options.raycast === false ? { available: false, error: "Disabled by request" } : makeRaycaster(screen);
    var started = Date.now(), enumerated = 0;
    types.forEach(function (typeName) {
      var klass = findClass(String(typeName), true); if (!klass) return;
      var objects;
      try { objects = allOfType(klass); } catch (error) { diagnostics.push({ type: typeName, error: String(error) }); return; }
      for (var i = 0; i < objects.length && nodes.length < maxNodes; i++) {
        var object = objects.get(i); enumerated++;
        try {
          if (!exists(object) || seen[object.handle.toString()]) continue;
          seen[object.handle.toString()] = true;
          var activity = active(object); if (!activity.active && !options.includeInactive) continue;
          var tr = transform(object); if (!exists(tr)) continue;
          var geometry;
          try { geometry = rectAndClipping(tr, screen); } catch (error) {
            if (diagnostics.length < 24) diagnostics.push({ type: fullType(object), name: text(maybe(object, "get_name", null)), error: String(error) });
            continue;
          }
          var selected = runtime.selectable && (object.class.handle.equals(runtime.selectable.handle) || object.class.isSubclassOf(runtime.selectable, false)) ? object : nearestSelectable(tr);
          var kind = TEXT_TYPES.indexOf(typeName) >= 0 ? "text" : /InputField/.test(typeName) ? "input" : /Toggle/.test(typeName) ? "toggle" : /ScrollRect/.test(typeName) ? "scroll" : "button";
          var inputOwner = kind === "input" ? object : kind === "text" ? nearestInput(tr) : null;
          var inputState = exists(inputOwner) ? inputDescription(inputOwner, options.numericTestId) : null;
          var ownText = redactInputText(componentText(object), inputOwner, inputState);
          if (kind === "input") ownText = inputState.value || (inputState.redacted ? "[redacted input]" : "");
          var record = { id: String(instanceId(object)), type: fullType(object), kind: kind,
            name: text(maybe(object, "get_name", null)), path: hierarchy(tr), text: ownText,
            label: kind === "text" ? ownText : redactInputText(descendantText(object), inputOwner, inputState), active: activity.active, enabled: activity.enabled,
            interactable: exists(selected) ? interactable(selected) : interactable(object),
            bounds: geometry.bounds, visibleBounds: geometry.visibleBounds, center: geometry.center,
            visible: activity.active && activity.enabled && geometry.visible,
            alpha: geometry.alpha, groupsInteractable: geometry.groupsInteractable,
            blocksRaycasts: geometry.blocksRaycasts, canvas: geometry.canvas };
          if(kind === "toggle") record.toggle={isOn:maybe(object,"get_isOn",null)};
          if(kind === "scroll") {
            record.scroll={horizontal:!!maybe(object,"get_horizontal",false),vertical:!!maybe(object,"get_vertical",false)};
            var position=maybe(object,"get_normalizedPosition",null);
            if(position)record.scroll.normalizedPosition={x:field(position,"x"),y:field(position,"y")};
          }
          if (inputState) record.input = inputState;
          if (exists(selected)) record.action = { id: String(instanceId(selected)), type: fullType(selected), name: text(maybe(selected, "get_name", null)), path: hierarchy(transform(selected)) };
          if (record.visible && record.interactable !== false && geometry.groupsInteractable && geometry.blocksRaycasts && raycaster.available && (kind !== "text" || options.raycastText)) {
            try { record.hit = raycaster.test(record.center, exists(selected) ? selected : object); }
            catch (error) { record.hit = { available: false, hittable: null, error: String(error) }; }
          }
          nodes.push(record);
        } catch (error) { if (diagnostics.length < 24) diagnostics.push({ type: typeName, error: String(error) }); }
      }
    });
    return { agentVersion: AGENT_VERSION, timestampMs: Date.now(), screen: screen, nodes: nodes, features: featureState(),
      enumeratedObjects: enumerated, customButtonTypes: customTypes, truncated: nodes.length >= maxNodes, elapsedMs: Date.now() - started,
      hitTest: { available: raycaster.available, error: raycaster.error || null }, diagnostics: diagnostics };
  }
  function normalize(value) { return String(value || "").replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim().toLowerCase(); }
  function choose(query) {
    query = query || {};
    if (!query.id && !query.text && !query.name && !query.path && !Array.isArray(query.textAny)) throw new Error("pick needs id, text, textAny, name or path");
    var snapshotOptions = { maxNodes: query.maxNodes || 1000, extraTypes: query.extraTypes || [], allSelectables: !!query.allSelectables, raycastText: true,
      customButtons: query.customButtons !== false, numericTestId: query.numericTestId };
    var observed = snapshot(snapshotOptions);
    function matches(actual, expected) { return query.exact === false ? normalize(actual).indexOf(normalize(expected)) >= 0 : normalize(actual) === normalize(expected); }
    // Diagnose only this same returned enumeration, before actionability
    // filters. An absent candidate is not proof of destruction or inactivity.
    // A kind alone never selects unrelated nodes for these bounded summaries.
    var identityCandidates = [];
    observed.nodes.forEach(function (node) {
      var by = [];
      if (query.id && node.id === String(query.id)) by.push("id");
      if (query.path && matches(node.path, query.path)) by.push("path");
      if (query.name && matches(node.name, query.name)) by.push("name");
      if (query.text && (matches(node.text, query.text) || matches(node.label, query.text))) by.push("text");
      if (Array.isArray(query.textAny) && query.textAny.some(function (value) { return matches(node.text, value) || matches(node.label, value); })) by.push("textAny");
      if (by.length) identityCandidates.push({ node: node, matchedBy: by });
    });
    function rejectionReasons(node) {
      var reasons = [];
      if (!node.visible) reasons.push("not-visible");
      if (!node.enabled) reasons.push("not-enabled");
      if (node.interactable === false) reasons.push("not-interactable");
      if (!node.groupsInteractable) reasons.push("groups-not-interactable");
      if (!node.blocksRaycasts) reasons.push("raycasts-not-blocked");
      if (node.kind === "input" && node.input && node.input.readOnly) reasons.push("read-only-input");
      if (query.kind && node.kind !== query.kind) reasons.push("kind-mismatch");
      if (query.id && node.id !== String(query.id)) reasons.push("id-mismatch");
      if (query.name && !matches(node.name, query.name)) reasons.push("name-mismatch");
      if (query.path && !matches(node.path, query.path)) reasons.push("path-mismatch");
      if (query.text && !matches(node.text, query.text) && !matches(node.label, query.text)) reasons.push("text-mismatch");
      if (Array.isArray(query.textAny) && !query.textAny.some(function (value) { return matches(node.text, value) || matches(node.label, value); })) reasons.push("textAny-mismatch");
      if (node.hit && node.hit.hittable === false) reasons.push("raycast-rejected");
      if (query.requireHitTest && (!node.hit || !node.hit.available || !node.hit.hittable)) reasons.push("required-hit-test-failed");
      return reasons;
    }
    function boundedText(value,limit) { return value === undefined || value === null ? null : String(value).slice(0,limit); }
    function candidateSummary(entry) {
      var node=entry.node,hit=node.hit,action=node.action;
      return { id:node.id,kind:node.kind,name:boundedText(node.name,128),path:boundedText(node.path,384),
        text:boundedText(node.text,160),label:boundedText(node.label,160),matchedBy:entry.matchedBy,
        active:node.active,visible:node.visible,enabled:node.enabled,
        interactable:node.interactable === undefined ? null : node.interactable,
        groupsInteractable:node.groupsInteractable,blocksRaycasts:node.blocksRaycasts,
        inputReadOnly:node.input ? !!node.input.readOnly : null,
        hit:hit ? {available:hit.available,hittable:hit.hittable,hits:hit.hits,
          firstName:boundedText(hit.firstName,128),firstPath:boundedText(hit.firstPath,384)} : null,
        action:action ? {id:action.id,type:boundedText(action.type,160),path:boundedText(action.path,384)} : null,
        bounds:node.bounds,visibleBounds:node.visibleBounds,center:node.center,rejectedBy:rejectionReasons(node) };
    }
    var matchesFound = observed.nodes.filter(function (node) {
      if (!node.visible || !node.enabled || node.interactable === false || !node.groupsInteractable || !node.blocksRaycasts) return false;
      if (node.kind === "input" && node.input && node.input.readOnly) return false;
      if (query.kind && node.kind !== query.kind || query.id && node.id !== String(query.id)) return false;
      if (query.name && !matches(node.name, query.name) || query.path && !matches(node.path, query.path)) return false;
      if (query.text && !matches(node.text, query.text) && !matches(node.label, query.text)) return false;
      if (Array.isArray(query.textAny) && !query.textAny.some(function (value) { return matches(node.text, value) || matches(node.label, value); })) return false;
      if (node.hit && node.hit.hittable === false) return false;
      if (query.requireHitTest && (!node.hit || !node.hit.available || !node.hit.hittable)) return false;
      return true;
    });
    // A button and its caption refer to the same native action. Keep one action
    // endpoint instead of reporting an artificial ambiguity for the same tap.
    var unique = [], actionIds = {};
    matchesFound.sort(function (a, b) { return (a.kind === "text" ? 1 : 0) - (b.kind === "text" ? 1 : 0); });
    matchesFound.forEach(function (node) { var key = node.action ? "action:" + node.action.id : "object:" + node.id; if (!actionIds[key]) { unique.push(node); actionIds[key] = true; } });
    if (unique.length !== 1) throw new Error(JSON.stringify({ error: unique.length ? "Ambiguous active semantic UI targets" : "No active semantic UI target",
      errorCode:unique.length ? "SEMANTIC_TARGET_AMBIGUOUS" : "SEMANTIC_TARGET_UNAVAILABLE",query: query,
      matches: unique.slice(0, 12).map(function (node) { return { id: node.id, name: node.name, path: node.path, text: node.text, label: node.label, center: node.center }; }),
      candidateCount:identityCandidates.length,candidateLimit:16,candidatesTruncated:identityCandidates.length>16,
      candidates:identityCandidates.slice(0,16).map(candidateSummary),matchCount:matchesFound.length,uniqueMatchCount:unique.length,
      timestampMs:observed.timestampMs,snapshot:{nodeCount:observed.nodes.length,enumeratedObjects:observed.enumeratedObjects,
        truncated:observed.truncated,options:snapshotOptions,includeInactive:false,
        effectiveMaxNodes:Math.min(3000,Math.max(1,Number(snapshotOptions.maxNodes)||1000))},
      musicSelection:observed.features && observed.features.mv ? observed.features.mv.musicSelection : [],
      screen: observed.screen, hitTest: observed.hitTest, diagnostics: observed.diagnostics }));
    return { timestampMs: observed.timestampMs, screen: observed.screen, target: unique[0],
      musicSelection:observed.features && observed.features.mv ? observed.features.mv.musicSelection : [],
      input: { method: "adb shell input tap", x: unique[0].center.x, y: unique[0].center.y },
      coordinateSource: "Live Unity RectTransform world corners projected through its Canvas camera; Android top-left origin" };
  }
  function initialize() {
    runtime.screen = findClass("UnityEngine.Screen"); runtime.resources = findClass("UnityEngine.Resources");
    runtime.unityObject = findClass("UnityEngine.Object"); runtime.vector2 = findClass("UnityEngine.Vector2"); runtime.vector3 = findClass("UnityEngine.Vector3");
    runtime.rectUtility = findClass("UnityEngine.RectTransformUtility"); runtime.canvas = findClass("UnityEngine.Canvas");
    runtime.rectTransform = findClass("UnityEngine.RectTransform", true); runtime.component = findClass("UnityEngine.Component", true);
    runtime.canvasGroup = findClass("UnityEngine.CanvasGroup", true); runtime.camera = findClass("UnityEngine.Camera");
    runtime.selectable = findClass("UnityEngine.UI.Selectable", true); runtime.text = findClass("UnityEngine.UI.Text", true); runtime.tmpText = findClass("TMPro.TMP_Text", true);
    runtime.textClasses = TEXT_TYPES.map(function (name) { return findClass(name, true); }).filter(function (klass) { return !!klass; });
    runtime.inputField = findClass("UnityEngine.UI.InputField", true); runtime.tmpInputField = findClass("TMPro.TMP_InputField", true);
    runtime.rectMask = findClass("UnityEngine.UI.RectMask2D", true); runtime.mask = findClass("UnityEngine.UI.Mask", true);
    runtime.sceneManager = findClass("UnityEngine.SceneManagement.SceneManager", true); runtime.time = findClass("UnityEngine.Time", true);
    runtime.eventSystem = findClass("UnityEngine.EventSystems.EventSystem", true); runtime.pointerData = findClass("UnityEngine.EventSystems.PointerEventData", true);
    runtime.raycastResult = findClass("UnityEngine.EventSystems.RaycastResult", true);
    ready = true; lastError = "";
    send({ type: "unity-ui-ready", bridgeVersion: BRIDGE_VERSION, agentVersion: AGENT_VERSION, unityVersion: Il2Cpp.unityVersion, screen: metadata() });
  }
  var mainDispatcher = null, mainBootstrap = null, mainIdentityProof = null, cachedMainRequested = false;
  function bootstrapMainDispatcher() {
    if (mainBootstrap) return mainBootstrap;
    // This is the only use of bridge 0.9.1's cold main scheduler. The host has
    // already independently identified the native engine-loop thread with
    // debuggerd and /proc; attachedThreads[0] is never accepted as proof.
    mainBootstrap = Il2Cpp.perform(function () {
      var proof = globalThis.QA_EXPECTED_UNITY_MAIN;
      var tid = Process.getCurrentThreadId();
      if (!proof || proof.pid !== QA_IDENTITY.pid || !Number.isInteger(proof.tid) ||
          proof.tid <= 0 || proof.tid !== tid || proof.comm !== "UnityMain" ||
          proof.source !== "native-debuggerd-engine-loop-and-proc-comm")
        throw new Error("Independent native Unity main-thread proof does not match this callback");
      var actualComm = File.readAllText("/proc/self/task/" + tid + "/comm").trim();
      if (actualComm !== proof.comm) throw new Error("Native Unity thread identity changed before bootstrap");
      mainIdentityProof = {pid:proof.pid,tid:tid,comm:actualComm,source:proof.source,
        nativeBacktraceSha256:proof.nativeBacktraceSha256};
      mainDispatcher = CachedMainThreadDispatcher.createIl2CppAdapter(
        {Il2Cpp:Il2Cpp,Process:Process,Script:Script,Frida:Frida,NULL:NULL},
        {expectedMainTid:tid,timeoutMs:10000,maxBatch:4});
      mainDispatcher.installOnCurrentMainThread();
      if (!ready) initialize();
      return true;
    }, "main");
    return mainBootstrap;
  }
  function onMain(action) {
    // Intro measurement retains the already validated observer path. The host
    // activates the cached dispatcher only at quiescent Title, after paired
    // timing and independent native stack collection, before the login tap.
    if (!cachedMainRequested) return Il2Cpp.perform(function () { if (!ready) initialize(); return action(); }, "main");
    return bootstrapMainDispatcher().then(function () { return mainDispatcher.dispatch(action); });
  }
  rpc.exports = {
    enablecached: function (proof) {
      if (cachedMainRequested || introPending || initPending || introTimer)
        throw new Error("Cached main bootstrap requires once-only quiescent observer");
      globalThis.QA_EXPECTED_UNITY_MAIN = proof;
      cachedMainRequested = true;
      return onMain(function () { return {dispatcher:mainDispatcher.status(),screen:metadata(),mainIdentityProof:mainIdentityProof}; });
    },
    beginintrotrace: function () { return beginIntroTrace(); },
    endintrotrace: function () { return endIntroTrace(); },
    status: function () { return { ready: ready, lastError: lastError, initializing: initPending,
      bridgeVersion: BRIDGE_VERSION, agentVersion: AGENT_VERSION, fridaVersion: QA_IDENTITY.fridaVersion,
      pid: QA_IDENTITY.pid, architecture: QA_IDENTITY.architecture, pendingManagedIntroWork:introPending, introTimerActive:!!introTimer,
      dispatcher:mainDispatcher ? mainDispatcher.status() : null, mainIdentityProof:mainIdentityProof }; },
    dispose: function () {
      endIntroTrace();
      if (introPending || initPending) throw new Error("QA reads must quiesce before observer disposal");
      return mainDispatcher ? mainDispatcher.dispose(false) : {redirected:true,handlesFreed:0};
    },
    initialize: function () { return onMain(function () { return metadata(); }); },
    snapshot: function (options) { return onMain(function () { return snapshot(options || {}); }); },
    features: function () { return onMain(function () { return { timestampMs:Date.now(), screen:metadata(), features:featureState() }; }); },
    pick: function (query) { return onMain(function () { return choose(query || {}); }); },
    pickmv: function (query) { return onMain(function () { return pickExistingMvTarget(query || {}); }); },
    classes: function (pattern, maximum) {
      return onMain(function () {
        var needle = normalize(pattern || "button"), result = [], limit = Math.min(500, Math.max(1, Number(maximum) || 100));
        Il2Cpp.domain.assemblies.forEach(function (assembly) {
          if (result.length >= limit) return;
          assembly.image.classes.forEach(function (klass) {
            if (result.length >= limit) return;
            var name = klass.namespace ? klass.namespace + "." + klass.name : klass.name;
            if (normalize(name).indexOf(needle) >= 0) result.push({ name: name, assembly: assembly.name,
              parent: klass.parent ? klass.parent.namespace + "." + klass.parent.name : null });
          });
        }); return result;
      });
    }
  };
  // A fresh settled-Home host proves native Unity TID before enabling cached
  // reads. Do not run an unasserted cold initializer in that QA-only mode.
  if (globalThis.QA_CACHED_BOOTSTRAP_ONLY === true) return;
  setImmediate(function () {
    initPending = true;
    onMain(function () { return true; }).catch(function (error) { ready = false; lastError = String(error); send({ type: "unity-ui-error", error: lastError }); })
      .finally(function () { initPending = false; });
  });
}());

/* Disposable runtime QA observer. No APK patch, game-state setter or UI click.
 * Prepend frida-il2cpp-bridge 0.9.1 dist/index.js before loading in Frida 16.6.6.
 * All Unity object reads run on the Unity main thread; taps belong to adb.
 */
(function () {
  "use strict";
  var ready = false, lastError = "", runtime = {}, classCache = {}, initPending = false;
  var BRIDGE_VERSION = "0.9.1", AGENT_VERSION = 3;
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
  var result={musicRows:[],deckTabGroups:[],errors:[]};
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

function observeExistingMvState(screen) {
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
  var extras=observeExistingMvExtras(screen,raycaster);
  result.deckRoots=extras.deckRoots;result.suitPickerCells=extras.suitPickerCells;result.directorAssets=extras.directorAssets;
  result.errors=result.errors.concat(extras.errors);
  result.standingMemberNum=extras.deckRoots.length===1?extras.deckRoots[0].standingMemberNum:null;
  result.liveMasterId=extras.deckRoots.length===1?extras.deckRoots[0].liveMasterId:null;
  var music=observeExistingMusicRowsAndMvTabs(screen,raycaster);result.musicRows=music.musicRows;result.deckTabGroups=music.deckTabGroups;result.errors=result.errors.concat(music.errors);
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
  query = query || {}; var screen = metadata(), state = observeExistingMvState(screen), matches = [];
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
  matches = matches.filter(function(entry) {var t=entry.target;return t.active && t.enabled && t.visible && t.groupsInteractable && t.blocksRaycasts && t.hit && t.hit.available && t.hit.hittable;});
  if (matches.length !== 1) throw new Error(JSON.stringify({error:"MV target absent, obscured or ambiguous",query:query,matches:matches.length,state:state,screen:screen}));
  return {timestampMs:Date.now(),screen:screen,target:matches[0].target,catalog:matches[0].cell,
    input:{method:"adb shell input tap",x:matches[0].target.center.x,y:matches[0].target.center.y},
    coordinateSource:"Existing MV model identity and live RectTransform/raycast geometry; no selection method invoked"};
}

  function featureState() {
    var result = { native: nativeFeatureState(), aspectCorrectors: [], splashScreens: [], mv:observeExistingMvState(), diagnostics: [] };
    var aspect = findClass("LLAS.Scene.Live.Components.CameraAspectCorrector", true);
    if (aspect) try {
      var objects = allOfType(aspect);
      for (var i = 0; i < objects.length && i < 128; i++) {
        var object = objects.get(i), state = active(object);
        if (!state.active) continue;
        var item = { id: String(instanceId(object)), path: hierarchy(transform(object)), active: state.active,
          mode: numericField(object, "mode"), correction: numericField(object, "<Correction>k__BackingField"),
          defaultOrthographicSize: numericField(object, "defaultOrthographicSize") };
        try {
          var camera = object.field("target").value;
          item.camera = { fieldOfView: Number(maybe(camera, "get_fieldOfView", NaN)),
            orthographicSize: Number(maybe(camera, "get_orthographicSize", NaN)),
            orthographic: !!maybe(camera, "get_orthographic", false) };
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
          if (exists(tween)) sample.tween = { duration:numericField(tween,"duration"), position:numericField(tween,"position"),
            elapsedDelay:numericField(tween,"elapsedDelay"), completedLoops:numericField(tween,"completedLoops") };
        } catch (_) {}
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
            if(exists(tween)) item.tween={id:tween.handle.toString(),duration:numericField(tween,"duration"),position:numericField(tween,"position"),completedLoops:numericField(tween,"completedLoops")};
            items.push(item);
          }
        }
        var sample={timestampMs:Date.now(),screen:metadata(),config:nativeFeatureState().config,splashScreens:items};
        if(items.length || introTrace.samples.length<3 || (introTrace.samples.length && introTrace.samples[introTrace.samples.length-1].splashScreens.length)) introTrace.samples.push(sample);
      }).catch(function(error){introTrace.lastError=String(error);}).finally(function(){introPending=false;});
    },25);
    return {startedMs:introTrace.startedMs,intervalMs:25,scope:"Read-only main-thread splash/tween fields; no callbacks or setters"};
  }
  function endIntroTrace() { if(introTimer)clearInterval(introTimer);introTimer=null;return introTrace; }
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
    var observed = snapshot({ maxNodes: query.maxNodes || 1000, extraTypes: query.extraTypes || [], allSelectables: !!query.allSelectables, raycastText: true,
      customButtons: query.customButtons !== false, numericTestId: query.numericTestId });
    function matches(actual, expected) { return query.exact === false ? normalize(actual).indexOf(normalize(expected)) >= 0 : normalize(actual) === normalize(expected); }
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
    if (unique.length !== 1) throw new Error(JSON.stringify({ error: unique.length ? "Ambiguous active semantic UI targets" : "No active semantic UI target", query: query,
      matches: unique.slice(0, 12).map(function (node) { return { id: node.id, name: node.name, path: node.path, text: node.text, label: node.label, center: node.center }; }),
      screen: observed.screen, hitTest: observed.hitTest, diagnostics: observed.diagnostics }));
    return { timestampMs: observed.timestampMs, screen: observed.screen, target: unique[0],
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
  function onMain(action) {
    return Il2Cpp.perform(function () { if (!ready) initialize(); return action(); }, "main");
  }
  rpc.exports = {
    beginintrotrace: function () { return beginIntroTrace(); },
    endintrotrace: function () { return endIntroTrace(); },
    status: function () { return { ready: ready, lastError: lastError, initializing: initPending,
      bridgeVersion: BRIDGE_VERSION, agentVersion: AGENT_VERSION, fridaVersion: Frida.version,
      pid: Process.id, architecture: Process.arch }; },
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
  setImmediate(function () {
    initPending = true;
    onMain(function () { return true; }).catch(function (error) { ready = false; lastError = String(error); send({ type: "unity-ui-error", error: lastError }); })
      .finally(function () { initPending = false; });
  });
}());

/* qa-mvdump: read-only runtime value dump of the playing MV (sifas-mv-runtime-dump/1).
 *
 * Appended to the r8 observer bundle by build_mvdump_agent.py, in the SAME Frida script, so
 * every Unity call runs on UnityMain through the observer's proven cached dispatcher
 * (globalThis.QA_MVDUMP_HOST.onMain -> mainDispatcher.dispatch). No second script,
 * delegate, GC handle, bootstrap or scheduler exists here.
 *
 * Read-only by construction:
 *  - every Unity call goes through inv(): deny pattern first, then an exact allowlist of
 *    UnityEngine getters / pure statics (ALLOW), fixed parameter signatures (SIG), a
 *    holder-type check, and m_CachedPtr != 0 before any instance call;
 *  - LLAS (game) objects are only read through fields, never through their methods;
 *  - indexes are bounds-checked (GetChild < childCount, blend shapes < blendShapeCount,
 *    material Get* only after HasProperty);
 *  - no Il2Cpp object survives a callback: roots are re-enumerated in every action and
 *    cursors are plain JSON. Caches hold metadata (classes, methods, fields), ints
 *    (shader property ids) and strings (paths) only;
 *  - actions are plain synchronous functions returning plain JSON (never a thenable);
 *  - the RPCs refuse unless the cached dispatcher is READY, so the cold
 *    Il2Cpp.perform(..., 'main') path is never taken;
 *  - every action is bounded: object caps per type and a soft/hard time budget.
 * Managed exceptions are prevented by these rules; JS-level and bridge raise() errors are
 * caught per section and recorded as {at, error}.
 */
(function () {
  "use strict";
  var H = globalThis.QA_MVDUMP_HOST;
  if (!H) throw new Error("MVDUMP_HOST_MISSING");
  var EXT_VERSION = 2;
  var PARTS = ["frame", "census", "quality", "fovmodNative", "renderers", "materials", "lightingRefs", "members",
    "springs", "stageNodes", "particles", "post"];
  // Defaults only: the sampler sends the budgets it uses (MV_RUNTIME_DUMP_FRAME_BUDGET_MS /
  // MV_RUNTIME_DUMP_FULL_BUDGET_MS, recorded in header.budgets) with every action.
  var BUDGET = { frame: { soft: 60, hard: 150 }, full: { soft: 80, hard: 200 } };
  var CAPS = { directors: 8, cameras: 16, camerasDetailed: 8, correctors: 8, cameraWork: 4, lights: 16, globals: 20,
    anchors: 8, members: 9, censusNodes: 400, censusDepth: 6, censusChunk: 80, components: 12, renderers: 400,
    rendererChunk: 24, materials: 256, materialChunk: 8, properties: 48, keywords: 16, bonesPerMember: 24,
    blendShapesInspected: 64, blendShapes: 24, swingBones: 64, stageNodes: 256, stageChunk: 64, stageDepth: 12,
    particles: 160, particleChunk: 40, fields: 48, fieldDepth: 2, arrayItems: 8, stringChars: 120, enumerate: 8192,
    errors: 24, holders: 8, lightingPerClass: 16, slots: 8 };

  // ------------------------------------------------------------------ policy
  var DENY = /^set_|^Set[A-Z]|^(Play|Pause|Stop|Resume|Evaluate|RebuildGraph|DeferredEvaluate|Simulate|Emit|Clear|Render|RenderWithShader|Destroy|DestroyImmediate|Instantiate|AddComponent|SendMessage|BroadcastMessage|Invoke|InvokeRepeating|StartCoroutine|GetParticles|GetPropertyBlock|BakeMesh|Update|LateUpdate)$|^get_(material|materials|mesh)$/;
  var ALLOW = {
    "UnityEngine.Time": ["get_frameCount", "get_time", "get_unscaledTime", "get_deltaTime", "get_timeScale", "get_realtimeSinceStartup"],
    "UnityEngine.Screen": ["get_width", "get_height", "get_orientation"],
    "UnityEngine.GameObject": ["Find", "get_activeSelf", "get_activeInHierarchy", "get_transform", "get_layer"],
    "UnityEngine.Shader": ["PropertyToID", "GetGlobalFloat", "GetGlobalVector", "GetGlobalVectorArray"],
    "UnityEngine.RenderSettings": ["get_fog", "get_fogMode", "get_fogColor", "get_fogDensity", "get_fogStartDistance",
      "get_fogEndDistance", "get_ambientMode", "get_ambientSkyColor", "get_ambientEquatorColor", "get_ambientGroundColor",
      "get_ambientIntensity", "get_ambientLight", "get_reflectionIntensity", "get_skybox"],
    "UnityEngine.QualitySettings": ["get_activeColorSpace", "get_vSyncCount", "get_antiAliasing"],
    "UnityEngine.Application": ["get_targetFrameRate"],
    "UnityEngine.Object": ["GetInstanceID", "get_name"],
    "UnityEngine.Component": ["get_gameObject", "get_transform", "GetComponents", "GetComponent"],
    "UnityEngine.Behaviour": ["get_enabled", "get_isActiveAndEnabled"],
    "UnityEngine.Transform": ["get_position", "get_rotation", "get_lossyScale", "get_localPosition", "get_localRotation",
      "get_localScale", "get_parent", "get_childCount", "GetChild", "Find", "GetSiblingIndex"],
    "UnityEngine.Camera": ["get_fieldOfView", "get_aspect", "get_nearClipPlane", "get_farClipPlane", "get_orthographic",
      "get_orthographicSize", "get_usePhysicalProperties", "get_focalLength", "get_lensShift", "get_projectionMatrix",
      "get_worldToCameraMatrix", "get_rect", "get_pixelRect", "get_pixelWidth", "get_pixelHeight", "get_depth",
      "get_clearFlags", "get_backgroundColor", "get_cullingMask", "get_allowHDR", "get_allowMSAA", "get_depthTextureMode",
      "get_targetTexture"],
    "UnityEngine.Texture": ["get_width", "get_height"],
    "UnityEngine.RenderTexture": ["get_format"],
    "UnityEngine.Playables.PlayableDirector": ["get_time", "get_duration", "get_state", "get_timeUpdateMode",
      "get_extrapolationMode", "get_playableAsset"],
    "UnityEngine.Renderer": ["get_enabled", "get_isVisible", "get_bounds", "get_sharedMaterials", "get_lightmapIndex",
      "get_lightmapScaleOffset", "get_sortingOrder"],
    "UnityEngine.SkinnedMeshRenderer": ["get_sharedMesh", "GetBlendShapeWeight"],
    "UnityEngine.MeshFilter": ["get_sharedMesh"],
    "UnityEngine.Mesh": ["get_blendShapeCount", "GetBlendShapeName"],
    "UnityEngine.Material": ["get_shader", "get_renderQueue", "get_shaderKeywords", "HasProperty", "GetFloat", "GetColor",
      "GetVector", "GetTexture", "GetTextureScale", "GetTextureOffset"],
    "UnityEngine.Light": ["get_type", "get_color", "get_intensity", "get_range", "get_spotAngle", "get_shadows", "get_cullingMask"],
    "UnityEngine.ParticleSystem": ["get_isPlaying", "get_isEmitting", "get_isPaused", "get_particleCount", "get_time",
      "get_randomSeed", "get_useAutoRandomSeed"]
  };
  var INT = ["System.Int32"];
  var SIG = {
    "UnityEngine.GameObject::Find": ["System.String"], "UnityEngine.Shader::PropertyToID": ["System.String"],
    "UnityEngine.Shader::GetGlobalFloat": INT, "UnityEngine.Shader::GetGlobalVector": INT,
    "UnityEngine.Shader::GetGlobalVectorArray": INT, "UnityEngine.Component::GetComponents": ["System.Type"],
    "UnityEngine.Component::GetComponent": ["System.Type"], "UnityEngine.Transform::GetChild": INT,
    "UnityEngine.Transform::Find": ["System.String"], "UnityEngine.SkinnedMeshRenderer::GetBlendShapeWeight": INT,
    "UnityEngine.Mesh::GetBlendShapeName": INT, "UnityEngine.Material::HasProperty": INT, "UnityEngine.Material::GetFloat": INT,
    "UnityEngine.Material::GetColor": INT, "UnityEngine.Material::GetVector": INT, "UnityEngine.Material::GetTexture": INT,
    "UnityEngine.Material::GetTextureScale": INT, "UnityEngine.Material::GetTextureOffset": INT
  };
  var STATIC_CLASSES = { "UnityEngine.Time": 1, "UnityEngine.Screen": 1, "UnityEngine.Shader": 1, "UnityEngine.RenderSettings": 1,
    "UnityEngine.QualitySettings": 1, "UnityEngine.Application": 1 };
  var STATIC_METHODS = { "UnityEngine.GameObject::Find": 1 };

  // Class candidates (<= 4 per class). The probe resolves them once; sample() reuses the result.
  var COMPONENTS = ["LiveCoreCameraManager", "LiveCoreCamera", "LiveCoreCameraWork", "CameraAspectCorrector",
    "LiveCoreOverlayCamera", "LiveSplitScreenEffect", "LiveCoreMemberManager", "LiveCoreMember", "LiveCoreMemberAmbient",
    "LiveCoreMemberRimlight", "LiveCoreMemberNodeScaling", "LiveCoreStageAmbient", "LiveCoreStageModel",
    "LiveCoreStageEmissive", "LiveCoreStageEffect", "LiveCoreStagePenlight", "LiveCoreStageDisplay",
    "LiveCoreStageFlashLight", "LiveCoreStageColoring", "LivePropAmbient", "LivePropRimlight", "LivePauseMediator"];
  var CLASS_TABLE = [
    { key: "Camera", candidates: ["UnityEngine.Camera"], unity: true },
    { key: "PlayableDirector", candidates: ["UnityEngine.Playables.PlayableDirector"], unity: true },
    { key: "Light", candidates: ["UnityEngine.Light"], unity: true },
    { key: "ParticleSystem", candidates: ["UnityEngine.ParticleSystem"], unity: true },
    { key: "LiveDirector", candidates: ["LLAS.Scene.Live.LiveDirector", "LLAS.Scene.LiveMv.LiveDirector", "LiveDirector"] },
    { key: "LiveDirectorBase", candidates: ["LLAS.Scene.Live.LiveDirectorBase", "LLAS.Scene.LiveMv.LiveDirectorBase", "LiveDirectorBase"] },
    { key: "LiveMvScene", candidates: ["LLAS.Scene.Live.LiveMvScene", "LLAS.Scene.LiveMv.LiveMvScene", "LiveMvScene"] }
  ].concat(COMPONENTS.map(function (name) {
    return { key: name, candidates: ["LLAS.Scene.Live.Components." + name] };
  })).concat(["LiveMusicMachine", "SwingBoneManager", "SwingBone", "BodyPartManager", "MemberSpotLightShaft",
    "LiveQualitySettingVO"].map(function (name) {
    var first = name === "LiveMusicMachine" ? "LLAS.Scene.Live.Components." : name === "LiveQualitySettingVO" ? "LLAS.DM.ValueObject." : "LLAS.Components.Members.";
    var list = [first + name, "LLAS.Scene.Live.Components." + name, "LLAS.Scene.Live." + name, "LLAS." + name, name];
    var unique = [];
    list.forEach(function (c) { if (unique.indexOf(c) < 0) unique.push(c); });
    return { key: name, candidates: unique.slice(0, 4) };
  }));
  var CLASS_KEYS = {};
  CLASS_TABLE.forEach(function (entry) { CLASS_KEYS[entry.key] = entry; });

  // Integer enum names (Unity 2018.4).
  var ENUMS = {
    PlayState: { 0: "Paused", 1: "Playing", 2: "Delayed" },
    DirectorUpdateMode: { 0: "DSPClock", 1: "GameTime", 2: "UnscaledGameTime", 3: "Manual" },
    DirectorWrapMode: { 0: "Hold", 1: "Loop", 2: "None" },
    CameraClearFlags: { 1: "Skybox", 2: "SolidColor", 3: "Depth", 4: "Nothing" },
    DepthTextureMode: { 0: "None", 1: "Depth", 2: "DepthNormals", 3: "Depth|DepthNormals", 4: "MotionVectors", 5: "Depth|MotionVectors" },
    ScreenOrientation: { 0: "Unknown", 1: "Portrait", 2: "PortraitUpsideDown", 3: "LandscapeLeft", 4: "LandscapeRight", 5: "AutoRotation" },
    LightType: { 0: "Spot", 1: "Directional", 2: "Point", 3: "Area", 4: "Disc" },
    LightShadows: { 0: "None", 1: "Hard", 2: "Soft" },
    FogMode: { 1: "Linear", 2: "Exponential", 3: "ExponentialSquared" },
    AmbientMode: { 0: "Skybox", 1: "Trilight", 3: "Flat", 4: "Custom" },
    ColorSpace: { "-1": "Uninitialized", 0: "Gamma", 1: "Linear" },
    RenderTextureFormat: { 0: "ARGB32", 1: "Depth", 2: "ARGBHalf", 3: "Shadowmap", 4: "RGB565", 5: "ARGB4444", 6: "ARGB1555",
      7: "Default", 8: "ARGB2101010", 9: "DefaultHDR", 10: "ARGB64", 11: "ARGBFloat", 12: "RGFloat", 13: "RGHalf",
      14: "RFloat", 15: "RHalf", 16: "R8" }
  };
  var STRUCTS = { "UnityEngine.Vector2": ["vec2", 2], "UnityEngine.Vector3": ["vec3", 3], "UnityEngine.Vector4": ["vec4", 4],
    "UnityEngine.Quaternion": ["quat", 4], "UnityEngine.Color": ["color", 4], "UnityEngine.Rect": ["rect", 4],
    "UnityEngine.Matrix4x4": ["mat4", 16], "UnityEngine.Bounds": ["bounds", 6] };
  var SECRET_LIKE = /pass|token|secret|session|auth|account|user|mail|device|key/i;
  function nameLike(field) { return /(^|[_<.])(name|path|id)(>|$)/i.test(field) || /[a-z](Name|Path|Id)(>|$)/.test(field); }
  var PRIMITIVE = { "System.Single": "f32", "System.Double": "f64", "System.Int32": "i32", "System.UInt32": "u32",
    "System.Int16": "i16", "System.UInt16": "u16", "System.Byte": "u8", "System.SByte": "i8", "System.Char": "char",
    "System.Boolean": "bool", "System.Int64": "i64", "System.UInt64": "u64" };
  var STATIC_GLOBALS = ["_Beat", "_MusicTime", "_SelfTime", "_ColorsLength", "_RenderTextureResolution", "_Time",
    "_AmbientColor", "_TintColor", "_BlendColor", "_RimlightColor", "_RimlightDirection", "_RimglightIntensity", "_RimglightPower"];
  var DEFAULT_LIGHTING = ["LiveCoreMemberAmbient", "LiveCoreMemberRimlight", "LiveCoreStageAmbient", "LiveCoreStageModel",
    "LivePropAmbient", "LivePropRimlight", "LiveCoreStagePenlight", "LiveCoreStageColoring", "LiveCoreStageFlashLight",
    "LiveCoreStageDisplay"];
  var POST_CLASS = /Post|Bloom|DepthOfField|Flare/;

  // ------------------------------------------------------------------ caches (metadata / ints / strings only)
  var methodCache = {}, isaCache = {}, layoutCache = {}, propertyIds = {}, resolved = {}, pathCache = {}, pathCacheSize = 0;
  var PATH_TTL_MS = 15000, PATH_CACHE_MAX = 4096;
  var offsets = null;

  function requireReady() {
    var s = H.dispatcherStatus();
    if (!H.cachedRequested() || !s || s.state !== "READY")
      throw new Error("MVDUMP_DISPATCHER_NOT_READY:" + (s ? s.state + "/" + s.lastCode : "none"));
  }
  function short(error) { return String(error && error.message || error).slice(0, 160); }
  function Ctx(kind, options) {
    var b = options.budget || {}, d = kind === "frame" ? BUDGET.frame : BUDGET.full;
    this.t0 = Date.now();
    this.soft = typeof b.soft === "number" ? b.soft : d.soft;
    this.hard = typeof b.hard === "number" ? b.hard : d.hard;
    this.calls = 0; this.objects = 0; this.truncated = false; this.truncatedSections = []; this.nonFinite = [];
    this.errors = []; this.classBudget = 8; this.arrays = options.arrays === true; this.memo = {};
  }
  Ctx.prototype.elapsed = function () { return Date.now() - this.t0; };
  Ctx.prototype.pastSoft = function () { return this.elapsed() >= this.soft; };
  Ctx.prototype.pastHard = function () { return this.elapsed() >= this.hard; };
  Ctx.prototype.cut = function (section) {
    this.truncated = true;
    if (this.truncatedSections.indexOf(section) < 0) this.truncatedSections.push(section);
  };
  Ctx.prototype.err = function (at, error) {
    if (this.errors.length < CAPS.errors) this.errors.push({ at: String(at).slice(0, 80), error: short(error) });
  };
  Ctx.prototype.bad = function (path) { if (this.nonFinite.length < 64) this.nonFinite.push(path); };
  Ctx.prototype.cost = function () {
    return { elapsedMs: this.elapsed(), calls: this.calls, objects: this.objects, truncated: this.truncated,
      truncatedSections: this.truncatedSections.slice(), budgetMs: { soft: this.soft, hard: this.hard } };
  };

  // ------------------------------------------------------------------ low level
  function initOffsets() {
    if (offsets) return offsets;
    var object = H.findClass("UnityEngine.Object", true), cached = null, id = null;
    try { cached = object.field("m_CachedPtr").offset; } catch (_) {}
    try { id = object.field("m_InstanceID").offset; } catch (_) {}
    if (typeof cached !== "number") throw new Error("MVDUMP_LIVENESS_UNAVAILABLE: UnityEngine.Object.m_CachedPtr");
    offsets = { cachedPtr: cached, instanceId: typeof id === "number" ? id : null, object: object };
    return offsets;
  }
  function isObj(value) {
    return !!value && typeof value.isNull === "function" && !value.isNull() && value.handle && typeof value.handle.add === "function";
  }
  // A UnityEngine.Object whose native counterpart still exists (m_CachedPtr != 0).
  function alive(value) {
    if (!isObj(value)) return false;
    return !value.handle.add(initOffsets().cachedPtr).readPointer().isNull();
  }
  function iid(value) {
    if (!isObj(value)) return null;
    var o = initOffsets();
    if (o.instanceId !== null) return value.handle.add(o.instanceId).readS32();
    return alive(value) ? Number(inv(null, "UnityEngine.Object", "GetInstanceID", value, [])) : null;
  }
  function klassName(klass) { return klass ? (klass.namespace ? klass.namespace + "." + klass.name : klass.name) : null; }
  function isA(value, klass) {
    if (!isObj(value) || !klass) return false;
    var c = value.class, key = c.handle.toString() + "|" + klass.handle.toString(), v = isaCache[key];
    if (v === undefined) { v = c.handle.equals(klass.handle) || !!c.isSubclassOf(klass, false); isaCache[key] = v; }
    return v;
  }
  function classIsA(klass, base) {
    if (!klass || !base) return false;
    var key = klass.handle.toString() + "|" + base.handle.toString(), v = isaCache[key];
    if (v === undefined) { v = klass.handle.equals(base.handle) || !!klass.isSubclassOf(base, false); isaCache[key] = v; }
    return v;
  }
  function method(className, name, argc) {
    var key = className + "::" + name + "/" + argc;
    if (methodCache.hasOwnProperty(key)) return methodCache[key];
    if (DENY.test(name)) throw new Error("MVDUMP_POLICY_DENY:" + className + "::" + name);
    if (!/^UnityEngine(\.|$)/.test(className)) throw new Error("MVDUMP_POLICY_NAMESPACE:" + className);
    if (!ALLOW[className] || ALLOW[className].indexOf(name) < 0) throw new Error("MVDUMP_POLICY_NOT_ALLOWED:" + className + "::" + name);
    var types = SIG[className + "::" + name] || [];
    if (types.length !== argc) throw new Error("MVDUMP_POLICY_SIGNATURE:" + className + "::" + name + "/" + argc);
    var klass = H.findClass(className, true), m = null;
    if (klass) {
      m = klass.tryMethod(name, argc) || null;
      if (m && types.length) m = m.tryOverload.apply(m, types) || null;
    }
    var entry = null;
    if (m) {
      var declaring = m.class;
      if (!/^UnityEngine(\.|$)/.test(declaring.namespace || "")) throw new Error("MVDUMP_POLICY_DECLARING:" + klassName(declaring));
      var wantStatic = !!(STATIC_CLASSES[className] || STATIC_METHODS[className + "::" + name] || (name === "PropertyToID"));
      if (!!m.isStatic !== wantStatic) throw new Error("MVDUMP_POLICY_STATIC:" + className + "::" + name);
      entry = { m: m, klass: klass, isStatic: !!m.isStatic };
    }
    methodCache[key] = entry;
    return entry;
  }
  // The one choke point for Unity calls. Returns null for a dead holder (never invoked).
  function inv(ctx, className, name, holder, args) {
    args = args || [];
    var entry = method(className, name, args.length);
    if (!entry) throw new Error("MVDUMP_METHOD_UNAVAILABLE:" + className + "::" + name);
    if (entry.isStatic) {
      if (ctx) ctx.calls++;
      return entry.m.invoke.apply(entry.m, args);
    }
    if (!alive(holder)) return null;
    if (!isA(holder, entry.klass)) throw new Error("MVDUMP_HOLDER_TYPE:" + H.fullType(holder) + " is not " + className);
    if (ctx) ctx.calls++;
    var bound = entry.m.withHolder(holder);
    return bound.invoke.apply(bound, args);
  }
  // inv() with a per-value error boundary (records the error, returns null).
  function g(ctx, className, name, holder, convert, args) {
    try {
      var value = inv(ctx, className, name, holder, args);
      return convert ? convert(value) : value;
    } catch (error) { ctx.err(className.replace("UnityEngine.", "") + "." + name, error); return null; }
  }
  function str(value) {
    if (value === null || value === undefined) return null;
    if (typeof value === "string") return value;
    if (typeof value.isNull === "function" && value.isNull()) return null;
    var length = typeof value.length === "number" ? value.length : 0;
    if (length > 4096) return null;
    return value.content === undefined || value.content === null ? null : String(value.content);
  }
  function nameOf(ctx, object) { return str(inv(ctx, "UnityEngine.Object", "get_name", object, [])); }
  function bool(value) { return value === null || value === undefined ? null : !!value; }
  function enumInt(value) {
    if (value === null || value === undefined) return null;
    if (typeof value === "number") return isFinite(value) ? value : null;
    if (typeof value === "boolean") return value ? 1 : 0;
    try { var n = Number(value.field("value__").value); return isFinite(n) ? n : null; } catch (_) { return null; }
  }
  function en(table) {
    return function (value) {
      var v = enumInt(value);
      return v === null ? null : { v: v, n: ENUMS[table] && ENUMS[table][v] !== undefined ? ENUMS[table][v] : null };
    };
  }
  function num(ctx, value, path, digits) {
    if (value === null || value === undefined) return null;
    if (typeof value === "boolean") return value;
    var n = typeof value === "number" ? value : Number(value);
    if (!isFinite(n)) { ctx.bad(path); return null; }
    if (Math.floor(n) === n && Math.abs(n) < 9007199254740992) return n;
    return Number(n.toPrecision(digits || 7));
  }
  function raw(ctx, value, count, path, digits) {
    if (!value || !value.handle || (typeof value.isNull === "function" && value.isNull())) return null;
    var out = [], h = value.handle;
    for (var i = 0; i < count; i++) out.push(num(ctx, h.add(4 * i).readFloat(), path + "[" + i + "]", digits || 9));
    return out;
  }
  function rd(ctx, count, digits) { return function (value) { return raw(ctx, value, count, "v", digits); }; }
  function items(array, cap) {
    var out = [];
    out.total = 0;
    if (!array || (typeof array.isNull === "function" && array.isNull())) return out;
    var n = Number(array.length);
    out.total = n;
    for (var i = 0; i < n && i < cap; i++) out.push(array.get(i));
    return out;
  }
  function stripName(name) { return String(name === null ? "?" : name).replace(/\(Clone\)$/, "").replace(/ \(Instance\)$/, ""); }

  // ------------------------------------------------------------------ classes
  function lookupEntry(entry, ctx) {
    for (var i = 0; i < entry.candidates.length && i < 4; i++) {
      var klass = H.findClass(entry.candidates[i], true);
      if (klass) return { klass: klass, fullName: entry.candidates[i] };
    }
    return null;
  }
  function cls(ctx, key) {
    if (resolved.hasOwnProperty(key)) return resolved[key] ? H.findClass(resolved[key], true) : null;
    var entry = CLASS_KEYS[key] || { key: key, candidates: [key] };
    if (ctx && ctx.classBudget-- <= 0) { ctx.err("class:" + key, "MVDUMP_CLASS_UNRESOLVED_BUDGET (run mvruntimeprobe first)"); return null; }
    var found = lookupEntry(entry, ctx);
    resolved[key] = found ? found.fullName : null;
    return found ? found.klass : null;
  }
  function unityObjectClass(klass) { return classIsA(klass, initOffsets().object); }
  // Snapshot of live instances of a UnityEngine.Object class (FindObjectsOfTypeAll).
  function instances(ctx, klass, cap) {
    if (!klass || !unityObjectClass(klass)) return [];
    ctx.calls++;
    var list = items(H.allOfType(klass), cap || CAPS.enumerate), out = [];
    out.total = list.total;
    for (var i = 0; i < list.length; i++) if (alive(list[i])) out.push(list[i]);
    return out;
  }
  function activeGo(ctx, object) {
    var go = isA(object, H.findClass("UnityEngine.GameObject", true)) ? object : refValue(inv(ctx, "UnityEngine.Component", "get_gameObject", object, []));
    return go ? !!inv(ctx, "UnityEngine.GameObject", "get_activeInHierarchy", go, []) : false;
  }
  function trOf(ctx, object) {
    if (!alive(object)) return null;
    if (isA(object, H.findClass("UnityEngine.Transform", true))) return object;
    if (isA(object, H.findClass("UnityEngine.GameObject", true))) return refValue(inv(ctx, "UnityEngine.GameObject", "get_transform", object, []));
    return refValue(inv(ctx, "UnityEngine.Component", "get_transform", object, []));
  }
  function goIid(ctx, object) {
    if (!alive(object)) return null;
    if (isA(object, H.findClass("UnityEngine.GameObject", true))) return iid(object);
    return iid(inv(ctx, "UnityEngine.Component", "get_gameObject", object, []));
  }
  // Root-first path with (Clone)/( Instance) stripped; cached per Transform instanceId (strings only).
  function pathInfo(ctx, object) {
    var tr = trOf(ctx, object);
    if (!tr) return { path: null, rawPath: null, segments: [] };
    var id = iid(tr), now = Date.now(), cached = pathCache[id];
    if (cached && now - cached.t < PATH_TTL_MS) return cached;
    var names = [], cur = tr, guard = 0;
    while (isObj(cur) && guard++ < 48) {
      names.push(nameOf(ctx, cur));
      cur = refValue(inv(ctx, "UnityEngine.Transform", "get_parent", cur, []));
    }
    names.reverse();
    var segments = names.map(stripName);
    var info = { path: "/" + segments.join("/"), rawPath: "/" + names.map(function (n) { return n === null ? "?" : n; }).join("/"),
      segments: segments, t: now };
    if (pathCacheSize >= PATH_CACHE_MAX) { pathCache = {}; pathCacheSize = 0; }
    if (!pathCache[id]) pathCacheSize++;
    pathCache[id] = info;
    return info;
  }
  function withPath(target, info) {
    target.path = info.path;
    if (info.rawPath !== info.path) target.rawPath = info.rawPath;
    return target;
  }
  function fv(object, name) {
    if (!isObj(object)) return undefined;
    try { return object.field(name).value; } catch (_) { return undefined; }
  }
  function fieldAny(object, names) {
    for (var i = 0; i < names.length; i++) {
      var value = fv(object, names[i]);
      if (value !== undefined) return { name: names[i], value: value };
    }
    return null;
  }
  function backingNames(name) {
    var upper = name.charAt(0).toUpperCase() + name.slice(1);
    return [name, "<" + upper + ">k__BackingField", "_" + name, "m_" + upper];
  }
  function refValue(value) { return isObj(value) ? value : null; }
  function numberField(object, names) {
    var found = fieldAny(object, names);
    if (!found) return null;
    var v = found.value;
    if (typeof v === "number" || typeof v === "boolean") return v;
    var e = enumInt(v);
    return e;
  }
  function resolvePath(ctx, path) {
    var parts = String(path).replace(/^\//, "").split("/");
    var root = inv(ctx, "UnityEngine.GameObject", "Find", null, [Il2Cpp.string("/" + parts[0])]);
    if (!alive(root)) return null;
    var tr = inv(ctx, "UnityEngine.GameObject", "get_transform", root, []);
    if (parts.length === 1) return tr;
    return refValue(inv(ctx, "UnityEngine.Transform", "Find", tr, [Il2Cpp.string(parts.slice(1).join("/"))]));
  }

  // ------------------------------------------------------------------ generic field reader (schema section 5)
  function layoutOf(klass) {
    var key = klass.handle.toString();
    if (layoutCache[key]) return layoutCache[key];
    var out = [], k = klass, guard = 0;
    while (k && guard++ < 8) {
      var ns = k.namespace || "";
      if (/^(UnityEngine|System|TMPro)(\.|$)/.test(ns)) break;
      var fields = k.fields || [];
      for (var i = 0; i < fields.length; i++) {
        var f = fields[i];
        if (f.isStatic) continue;
        out.push({ field: f, name: f.name, typeName: f.type.name });
      }
      k = k.parent;
    }
    layoutCache[key] = out;
    return out;
  }
  function structValue(ctx, value, path) {
    var typeName = value.type ? value.type.name : null, klass = value.type ? value.type.class : null;
    if (klass && klass.isEnum) return { t: "enum", v: { v: enumInt(value), n: null } };
    var shape = STRUCTS[typeName];
    if (shape) return { t: shape[0], v: raw(ctx, value, shape[1], path, 9) };
    if (typeName === "UnityEngine.Color32") {
      var h = value.handle;
      return { t: "color32", v: [h.readU8(), h.add(1).readU8(), h.add(2).readU8(), h.add(3).readU8()] };
    }
    if (/^System\.Nullable`1/.test(typeName || "")) {
      var has = fv(value, "has_value");
      return { t: "nullable", v: has === true ? convert(ctx, fv(value, "value"), "value", 2, path) : null };
    }
    return { t: "struct", class: typeName };
  }
  function convert(ctx, value, fieldName, depth, path, typeName) {
    if (value === undefined) return { t: "unreadable", v: null };
    if (value === null) return { t: "null", v: null };
    if (typeof value === "boolean") return { t: "bool", v: value };
    if (typeof value === "number") return { t: PRIMITIVE[typeName] || (Math.floor(value) === value ? "int" : "f32"), v: num(ctx, value, path, 7) };
    if (typeof NativePointer !== "undefined" && value instanceof NativePointer) return { t: "ptr", v: null };
    if (typeof Int64 !== "undefined" && (value instanceof Int64 || (typeof UInt64 !== "undefined" && value instanceof UInt64)))
      return { t: "i64", v: num(ctx, Number(value.toString()), path, 15) };
    if (value instanceof Il2Cpp.String) {
      if (value.isNull()) return { t: "str", v: null };
      if (!nameLike(fieldName) || SECRET_LIKE.test(fieldName)) return { t: "str", v: null, skipped: true };
      var s = str(value);
      return { t: "str", v: s === null ? null : s.slice(0, CAPS.stringChars) };
    }
    if (value instanceof Il2Cpp.Array) {
      if (value.isNull()) return { t: "array", v: null };
      var list = items(value, CAPS.arrayItems), out = [];
      for (var i = 0; i < list.length; i++) out.push(depth < CAPS.fieldDepth ? convert(ctx, list[i], fieldName, CAPS.fieldDepth, path + "[" + i + "]") : null);
      return { t: "array", n: list.total, items: out };
    }
    if (value instanceof Il2Cpp.ValueType) return structValue(ctx, value, path);
    if (value instanceof Il2Cpp.Object) {
      if (value.isNull()) return { t: "ref", v: null };
      var klass = value.class, name = klassName(klass);
      if (unityObjectClass(klass)) {
        var live = alive(value);
        return { t: "ref", v: { ref: iid(value), name: live ? nameOf(ctx, value) : null, class: name, dead: !live || undefined } };
      }
      if (/^System\.Collections\.Generic\.List`1/.test(name || "") || (klass.namespace === "System.Collections.Generic" && /^List`1/.test(klass.name))) {
        var size = fv(value, "_size"), backing = fv(value, "_items"), entries = [];
        var listed = backing instanceof Il2Cpp.Array ? items(backing, Math.min(CAPS.arrayItems, Number(size) || 0)) : [];
        for (var j = 0; j < listed.length; j++) entries.push(depth < CAPS.fieldDepth ? convert(ctx, listed[j], fieldName, CAPS.fieldDepth, path + "[" + j + "]") : null);
        return { t: "list", n: typeof size === "number" ? size : null, items: entries };
      }
      if (/^System(\.|$)/.test(klass.namespace || "") || depth >= CAPS.fieldDepth) return { t: "obj", class: name };
      return { t: "obj", class: name, fields: readFields(ctx, value, depth + 1, path) };
    }
    return { t: typeof value, v: null };
  }
  function readFields(ctx, object, depth, path, skip) {
    if (!isObj(object)) return null;
    var layout = layoutOf(object.class), out = {}, count = 0;
    for (var i = 0; i < layout.length && count < CAPS.fields; i++) {
      var entry = layout[i];
      if (skip && skip.indexOf(entry.name) >= 0) continue;
      if (out.hasOwnProperty(entry.name)) continue;
      if (ctx.pastHard()) { ctx.cut("fields"); break; }
      var value;
      try { value = entry.field.withHolder(object).value; } catch (error) { out[entry.name] = { t: "unreadable", v: null }; count++; continue; }
      out[entry.name] = convert(ctx, value, entry.name, depth || 0, (path || "fields") + "." + entry.name, entry.typeName);
      count++;
    }
    return out;
  }

  // ------------------------------------------------------------------ readers
  function transformOf(ctx, tr, path, full) {
    var T = "UnityEngine.Transform";
    var out = { position: g(ctx, T, "get_position", tr, function (v) { return raw(ctx, v, 3, path + ".position", 9); }),
      rotation: g(ctx, T, "get_rotation", tr, function (v) { return raw(ctx, v, 4, path + ".rotation", 9); }),
      lossyScale: g(ctx, T, "get_lossyScale", tr, function (v) { return raw(ctx, v, 3, path + ".lossyScale", 9); }) };
    if (full) {
      out.localPosition = g(ctx, T, "get_localPosition", tr, function (v) { return raw(ctx, v, 3, path + ".localPosition", 9); });
      out.localRotation = g(ctx, T, "get_localRotation", tr, function (v) { return raw(ctx, v, 4, path + ".localRotation", 9); });
    }
    return out;
  }
  function liveDirectors(ctx) {
    if (ctx.memo.liveDirectors) return ctx.memo.liveDirectors;
    var klass = cls(ctx, "LiveDirector"), out = [];
    instances(ctx, klass, 32).forEach(function (object) { if (out.length < 4 && activeGo(ctx, object)) out.push(object); });
    ctx.memo.liveDirectors = out;
    return out;
  }
  function readDirectors(ctx) {
    var PD = H.findClass("UnityEngine.Playables.PlayableDirector", true), D = "UnityEngine.Playables.PlayableDirector";
    var held = {};
    liveDirectors(ctx).forEach(function (ld) {
      var found = fieldAny(ld, ["<TimelineDirector>k__BackingField", "timelineDirector", "playableDirector", "director"]);
      if (found && alive(found.value) && isA(found.value, PD)) held[iid(found.value)] = found.name;
    });
    var list = [], objects = instances(ctx, PD, 256);
    for (var i = 0; i < objects.length && list.length < CAPS.directors; i++) {
      var d = objects[i], id = iid(d);
      if (!held[id] && !activeGo(ctx, d)) continue;
      ctx.objects++;
      var p = "directors[" + list.length + "]", info = pathInfo(ctx, d);
      var asset = g(ctx, D, "get_playableAsset", d);
      var item = withPath({ key: "director:" + info.path }, info);
      item.instanceId = id; item.main = false;
      item.enabled = g(ctx, "UnityEngine.Behaviour", "get_enabled", d, bool);
      item.time = g(ctx, D, "get_time", d, function (v) { return num(ctx, v, p + ".time", 9); });
      item.duration = g(ctx, D, "get_duration", d, function (v) { return num(ctx, v, p + ".duration", 9); });
      item.state = g(ctx, D, "get_state", d, en("PlayState"));
      item.timeUpdateMode = g(ctx, D, "get_timeUpdateMode", d, en("DirectorUpdateMode"));
      item.extrapolationMode = g(ctx, D, "get_extrapolationMode", d, en("DirectorWrapMode"));
      item.asset = alive(asset) ? nameOf(ctx, asset) : null;
      item.heldByLiveDirector = !!held[id];
      if (held[id]) item.heldBy = held[id];
      list.push({ item: item, object: d });
    }
    var main = list.filter(function (e) { return e.item.heldByLiveDirector; })[0];
    if (!main) {
      var playing = list.filter(function (e) { return e.item.state && e.item.state.v === 1; });
      var pool = playing.length ? playing : list;
      pool.sort(function (a, b) { return (b.item.duration || 0) - (a.item.duration || 0); });
      main = pool[0];
      if (main) main.item.mainBy = playing.length ? "playing-longest" : "longest";
    } else main.item.mainBy = "LiveDirector." + main.item.heldBy;
    if (main) main.item.main = true;
    return { list: list.map(function (e) { return e.item; }), main: main || null };
  }
  function musicMachine(ctx) {
    var candidates = [];
    liveDirectors(ctx).forEach(function (ld) {
      var found = fieldAny(ld, ["<MusicMachine>k__BackingField", "musicMachine", "liveMusicMachine"]);
      if (found && isObj(found.value)) candidates.push(found.value);
    });
    if (!candidates.length) {
      var klass = cls(ctx, "LiveMusicMachine");
      if (klass && unityObjectClass(klass)) instances(ctx, klass, 8).forEach(function (m) { candidates.push(m); });
    }
    return candidates[0] || null;
  }
  function readClock(ctx, directors) {
    var T = "UnityEngine.Time", main = directors && directors.main;
    var clock = { directorTime: main ? main.item.time : null,
      frameCount: g(ctx, T, "get_frameCount", null, function (v) { return num(ctx, v, "clock.frameCount"); }),
      unityTime: g(ctx, T, "get_time", null, function (v) { return num(ctx, v, "clock.unityTime", 9); }),
      unscaledTime: g(ctx, T, "get_unscaledTime", null, function (v) { return num(ctx, v, "clock.unscaledTime", 9); }),
      deltaTime: g(ctx, T, "get_deltaTime", null, function (v) { return num(ctx, v, "clock.deltaTime", 9); }),
      timeScale: g(ctx, T, "get_timeScale", null, function (v) { return num(ctx, v, "clock.timeScale"); }),
      realtimeSinceStartup: g(ctx, T, "get_realtimeSinceStartup", null, function (v) { return num(ctx, v, "clock.realtimeSinceStartup", 9); }),
      musicTime: null, musicPlaying: null };
    try {
      var machine = musicMachine(ctx);
      if (machine) {
        var t = fieldAny(machine, ["musicPlayingTime", "<MusicPlayingTime>k__BackingField"]);
        if (t) clock.musicTime = num(ctx, typeof t.value === "number" ? t.value : Number(t.value), "clock.musicTime", 9);
        var playing = fieldAny(machine, ["<IsPlayingMusic>k__BackingField", "isPlayingMusic"]);
        if (playing) clock.musicPlaying = !!playing.value;
        var length = fieldAny(machine, ["<MusicLength>k__BackingField", "musicLength"]);
        if (length) clock.musicLength = num(ctx, Number(length.value), "clock.musicLength", 9);
      }
    } catch (error) { ctx.err("clock.music", error); }
    return clock;
  }
  function readClockEnd(ctx, directors) {
    var T = "UnityEngine.Time", main = directors && directors.main;
    return { directorTime: main ? g(ctx, "UnityEngine.Playables.PlayableDirector", "get_time", main.object, function (v) { return num(ctx, v, "clockEnd.directorTime", 9); }) : null,
      frameCount: g(ctx, T, "get_frameCount", null, function (v) { return num(ctx, v, "clockEnd.frameCount"); }),
      realtimeSinceStartup: g(ctx, T, "get_realtimeSinceStartup", null, function (v) { return num(ctx, v, "clockEnd.realtimeSinceStartup", 9); }) };
  }
  // Scene name through the observer's proven metadata() path; the Screen getters are read here
  // because metadata() turns the ScreenOrientation enum (a bridge ValueType) into NaN.
  function scene(ctx) {
    var m = H.metadata(), S = "UnityEngine.Screen";
    ctx.calls += 5;
    return { name: m.scene, width: g(ctx, S, "get_width", null), height: g(ctx, S, "get_height", null),
      orientation: g(ctx, S, "get_orientation", null, en("ScreenOrientation")), unityVersion: m.unityVersion };
  }
  // Camera census: every active camera with its role and key (cheap; no detail reads).
  function cameraCensus(ctx) {
    if (ctx.memo.cameras) return ctx.memo.cameras;
    var CAM = H.findClass("UnityEngine.Camera", true), list = [];
    var objects = instances(ctx, CAM, 256);
    for (var i = 0; i < objects.length && list.length < CAPS.cameras; i++) {
      var cam = objects[i];
      if (!activeGo(ctx, cam)) continue;
      ctx.objects++;
      var info = pathInfo(ctx, cam);
      list.push({ object: cam, iid: iid(cam), goIid: goIid(ctx, cam), info: info, role: null, key: null, rigDepth: info.segments.lastIndexOf("MainCamera") });
    }
    var roles = {}, sources = {};
    function mark(role, value, source) {
      if (!alive(value)) return;
      var id = goIid(ctx, value);
      if (id !== null && roles[id] === undefined) { roles[id] = role; sources[id] = source; }
    }
    try {
      instances(ctx, cls(ctx, "LiveCoreCameraManager"), 8).slice(0, 2).forEach(function (manager) {
        [["overlay", ["overlayCamera"]], ["cutin", ["cutinCamera"]], ["cutinOverlay", ["cutinOverlayCamera"]]].forEach(function (pair) {
          pair[1].forEach(function (name) {
            var found = fieldAny(manager, backingNames(name));
            if (found) mark(pair[0], found.value, "LiveCoreCameraManager." + found.name);
          });
        });
      });
      instances(ctx, cls(ctx, "LiveSplitScreenEffect"), 4).slice(0, 1).forEach(function (split) {
        layoutOf(split.class).forEach(function (entry) {
          if (!/camera/i.test(entry.name)) return;
          var value = fv(split, entry.name);
          if (value instanceof Il2Cpp.Array) items(value, 4).forEach(function (c, k) { mark("split" + (k + 1), c, "LiveSplitScreenEffect." + entry.name); });
        });
      });
    } catch (error) { ctx.err("cameras.roles", error); }
    var targets = ctx.memo.correctorTargets || {};
    var mains = list.filter(function (c) { return c.rigDepth >= 0 && roles[c.goIid] === undefined; });
    mains.sort(function (a, b) { return (targets[b.iid] ? 1 : 0) - (targets[a.iid] ? 1 : 0) || a.info.segments.length - b.info.segments.length; });
    if (mains.length) { roles[mains[0].goIid] = "main"; sources[mains[0].goIid] = targets[mains[0].iid] ? "MainCamera rig + corrector target" : "MainCamera rig"; }
    var used = {};
    list.forEach(function (c) {
      var role = roles[c.goIid];
      if (role && !used[role]) { c.role = role; c.roleSource = sources[c.goIid]; c.key = "camera:" + role; used[role] = true; }
      else c.key = "camera:path:" + c.info.path;
    });
    list.sort(function (a, b) { return (a.role === "main" ? 0 : 1) - (b.role === "main" ? 0 : 1); });
    ctx.memo.cameras = list;
    return list;
  }
  function cameraKeyByIid(ctx, id) {
    var found = (ctx.memo.cameras || []).filter(function (c) { return c.iid === id; })[0];
    return found ? found.key : null;
  }
  function textureInfo(ctx, texture, path) {
    if (!alive(texture)) return null;
    var out = { name: nameOf(ctx, texture), width: g(ctx, "UnityEngine.Texture", "get_width", texture), height: g(ctx, "UnityEngine.Texture", "get_height", texture) };
    if (isA(texture, H.findClass("UnityEngine.RenderTexture", true))) out.format = g(ctx, "UnityEngine.RenderTexture", "get_format", texture, en("RenderTextureFormat"));
    return out;
  }
  function cameraDetail(ctx, c, index, detailed) {
    var C = "UnityEngine.Camera", cam = c.object, p = "cameras[" + index + "]";
    var out = withPath({ key: c.key, role: c.role }, c.info);
    if (c.roleSource) out.roleSource = c.roleSource;
    out.instanceId = c.iid;
    out.enabled = g(ctx, "UnityEngine.Behaviour", "get_enabled", cam, bool);
    out.isActiveAndEnabled = g(ctx, "UnityEngine.Behaviour", "get_isActiveAndEnabled", cam, bool);
    out.activeInHierarchy = true;
    out.fieldOfView = g(ctx, C, "get_fieldOfView", cam, function (v) { return num(ctx, v, p + ".fieldOfView", 9); });
    out.aspect = g(ctx, C, "get_aspect", cam, function (v) { return num(ctx, v, p + ".aspect", 9); });
    if (!detailed) { out.summaryOnly = true; return out; }
    out.nearClipPlane = g(ctx, C, "get_nearClipPlane", cam, function (v) { return num(ctx, v, p + ".nearClipPlane", 9); });
    out.farClipPlane = g(ctx, C, "get_farClipPlane", cam, function (v) { return num(ctx, v, p + ".farClipPlane", 9); });
    out.orthographic = g(ctx, C, "get_orthographic", cam, bool);
    out.orthographicSize = g(ctx, C, "get_orthographicSize", cam, function (v) { return num(ctx, v, p + ".orthographicSize", 9); });
    out.usePhysicalProperties = g(ctx, C, "get_usePhysicalProperties", cam, bool);
    out.focalLength = g(ctx, C, "get_focalLength", cam, function (v) { return num(ctx, v, p + ".focalLength", 9); });
    out.lensShift = g(ctx, C, "get_lensShift", cam, function (v) { return raw(ctx, v, 2, p + ".lensShift", 9); });
    out.projection = g(ctx, C, "get_projectionMatrix", cam, function (v) { return raw(ctx, v, 16, p + ".projection", 9); });
    out.worldToCamera = g(ctx, C, "get_worldToCameraMatrix", cam, function (v) { return raw(ctx, v, 16, p + ".worldToCamera", 9); });
    out.rect = g(ctx, C, "get_rect", cam, function (v) { return raw(ctx, v, 4, p + ".rect", 9); });
    out.pixelRect = g(ctx, C, "get_pixelRect", cam, function (v) { return raw(ctx, v, 4, p + ".pixelRect", 9); });
    out.pixelWidth = g(ctx, C, "get_pixelWidth", cam);
    out.pixelHeight = g(ctx, C, "get_pixelHeight", cam);
    out.depth = g(ctx, C, "get_depth", cam, function (v) { return num(ctx, v, p + ".depth", 9); });
    out.clearFlags = g(ctx, C, "get_clearFlags", cam, en("CameraClearFlags"));
    out.backgroundColor = g(ctx, C, "get_backgroundColor", cam, function (v) { return raw(ctx, v, 4, p + ".backgroundColor", 7); });
    out.cullingMask = g(ctx, C, "get_cullingMask", cam);
    out.allowHDR = g(ctx, C, "get_allowHDR", cam, bool);
    out.allowMSAA = g(ctx, C, "get_allowMSAA", cam, bool);
    out.depthTextureMode = g(ctx, C, "get_depthTextureMode", cam, en("DepthTextureMode"));
    out.targetTexture = g(ctx, C, "get_targetTexture", cam, function (v) { return textureInfo(ctx, v, p + ".targetTexture"); });
    var tr = trOf(ctx, cam);
    out.transform = transformOf(ctx, tr, p + ".transform", true);
    if (c.rigDepth >= 0) {
      var rig = tr, up = c.info.segments.length - 1 - c.rigDepth;
      for (var k = 0; k < up && rig; k++) rig = refValue(inv(ctx, "UnityEngine.Transform", "get_parent", rig, []));
      if (rig) {
        var rt = transformOf(ctx, rig, p + ".rig", false);
        out.rig = { path: "/" + c.info.segments.slice(0, c.rigDepth + 1).join("/"), position: rt.position, rotation: rt.rotation, lossyScale: rt.lossyScale };
      }
    }
    return out;
  }
  function correctorObjects(ctx) {
    if (ctx.memo.correctorObjects) return ctx.memo.correctorObjects;
    var out = [], targets = {};
    instances(ctx, cls(ctx, "CameraAspectCorrector"), 64).forEach(function (object) {
      if (out.length >= CAPS.correctors || !activeGo(ctx, object)) return;
      var target = fv(object, "target");
      var id = alive(target) ? iid(target) : null;
      if (id !== null) targets[id] = true;
      out.push({ object: object, target: target, targetIid: id });
    });
    ctx.memo.correctorObjects = out;
    ctx.memo.correctorTargets = targets;
    return out;
  }
  function readCorrectors(ctx) {
    return correctorObjects(ctx).map(function (entry, i) {
      ctx.objects++;
      var object = entry.object, info = pathInfo(ctx, object), p = "correctors[" + i + "]";
      var key = entry.targetIid !== null && cameraKeyByIid(ctx, entry.targetIid) ? "corrector:" + cameraKeyByIid(ctx, entry.targetIid) : "corrector:path:" + info.path;
      var out = withPath({ key: key }, info);
      out.instanceId = iid(object);
      out.enabled = g(ctx, "UnityEngine.Behaviour", "get_enabled", object, bool);
      out.mode = (function () { var v = numberField(object, ["mode", "<Mode>k__BackingField"]); return v === null ? null : { v: Number(v), n: null }; })();
      out.correction = num(ctx, numberField(object, ["<Correction>k__BackingField", "correction"]), p + ".correction", 9);
      out.defaultOrthographicSize = num(ctx, numberField(object, ["defaultOrthographicSize"]), p + ".defaultOrthographicSize", 9);
      var tinfo = alive(entry.target) ? pathInfo(ctx, entry.target) : null;
      out.target = entry.targetIid === null ? null : { instanceId: entry.targetIid, path: tinfo ? tinfo.path : null, cameraKey: cameraKeyByIid(ctx, entry.targetIid) };
      out.fields = readFields(ctx, object, 1, p + ".fields", ["mode", "<Correction>k__BackingField", "defaultOrthographicSize", "target"]);
      return out;
    });
  }
  function readCameraWork(ctx) {
    var out = [];
    instances(ctx, cls(ctx, "LiveCoreCameraWork"), 32).forEach(function (object) {
      if (out.length >= CAPS.cameraWork || !activeGo(ctx, object)) return;
      ctx.objects++;
      var info = pathInfo(ctx, object), item = withPath({ key: "cameraWork:" + info.path }, info);
      item.class = H.fullType(object);
      item.fields = readFields(ctx, object, 1, "cameraWork[" + out.length + "].fields");
      out.push(item);
    });
    return out;
  }
  function propertyId(ctx, name) {
    if (propertyIds.hasOwnProperty(name)) return propertyIds[name];
    var id = inv(ctx, "UnityEngine.Shader", "PropertyToID", null, [Il2Cpp.string(name)]);
    propertyIds[name] = typeof id === "number" ? id : Number(id);
    return propertyIds[name];
  }
  function readGlobals(ctx, keys) {
    var names = (keys && Array.isArray(keys.globals) && keys.globals.length ? keys.globals : STATIC_GLOBALS).slice(0, CAPS.globals);
    var out = {};
    names.forEach(function (name) {
      if (ctx.pastHard()) { ctx.cut("globals"); return; }
      var id = propertyId(ctx, name);
      out["global:" + name] = { f: g(ctx, "UnityEngine.Shader", "GetGlobalFloat", null, function (v) { return num(ctx, v, "globals." + name + ".f"); }, [id]),
        v: g(ctx, "UnityEngine.Shader", "GetGlobalVector", null, function (v) { return raw(ctx, v, 4, "globals." + name + ".v", 7); }, [id]) };
    });
    if (ctx.arrays && keys && Array.isArray(keys.vectorArrays)) keys.vectorArrays.slice(0, 2).forEach(function (name) {
      var id = propertyId(ctx, name);
      var list = g(ctx, "UnityEngine.Shader", "GetGlobalVectorArray", null, null, [id]);
      var values = items(list, 16);
      out["global:" + name] = { n: values.total, v: values.map(function (v, i) { return raw(ctx, v, 4, "globals." + name + "[" + i + "]", 7); }) };
    });
    return out;
  }
  function directorAssetMembers(ctx) {
    var out = [];
    liveDirectors(ctx).forEach(function (ld) {
      var asset = fv(ld, "asset"), members = asset ? fv(asset, "<Members>k__BackingField") : null;
      if (!(members instanceof Il2Cpp.Array)) return;
      items(members, 12).forEach(function (vo) {
        if (!isObj(vo)) return;
        var suit = fv(vo, "<SuitId>k__BackingField"), suitId = null;
        try { if (suit && fv(suit, "has_value") === true) suitId = Number(fv(suit, "value")); } catch (_) {}
        out.push({ memberId: numberField(vo, ["<MemberMasterId>k__BackingField"]), formationPosition: numberField(vo, ["<FormationPosition>k__BackingField"]), suitId: suitId });
      });
    });
    return out;
  }
  function memberList(ctx) {
    if (ctx.memo.members) return ctx.memo.members;
    var assets = directorAssetMembers(ctx), out = [];
    instances(ctx, cls(ctx, "LiveCoreMember"), 32).forEach(function (object) {
      if (out.length >= CAPS.members || !activeGo(ctx, object)) return;
      var info = pathInfo(ctx, object), memberInfo = fv(object, "memberInfo");
      var formation = memberInfo ? numberField(memberInfo, ["<FormationPosition>k__BackingField"]) : null;
      var match = /\/Members\/Member(\d+)(\/|$)/.exec(info.path || "");
      var slot = match ? Number(match[1]) : formation;
      var found = assets.filter(function (a) { return a.formationPosition === formation && formation !== null; });
      out.push({ object: object, info: info, slot: slot, formationPosition: formation,
        memberId: found.length === 1 ? found[0].memberId : null, suitId: found.length === 1 ? found[0].suitId : null,
        root: match ? "/" + info.segments.slice(0, info.segments.indexOf("Member" + match[1]) + 1).join("/") : info.path });
    });
    out.sort(function (a, b) { return (a.slot || 0) - (b.slot || 0); });
    ctx.memo.members = out;
    return out;
  }
  function readMembersIdentity(ctx) {
    return memberList(ctx).map(function (m) {
      ctx.objects++;
      return withPath({ slot: m.slot, formationPosition: m.formationPosition, memberId: m.memberId, suitId: m.suitId, active: true }, m.info);
    });
  }
  // The prefab root carrying BodyPartManager for each member path prefix.
  function bodyParts(ctx) {
    if (ctx.memo.bodyParts) return ctx.memo.bodyParts;
    var out = [];
    instances(ctx, cls(ctx, "BodyPartManager"), 32).forEach(function (object) {
      if (out.length < CAPS.members && activeGo(ctx, object)) out.push({ object: object, info: pathInfo(ctx, object) });
    });
    ctx.memo.bodyParts = out;
    return out;
  }
  function memberRoot(ctx, member) {
    var prefix = member.root + "/";
    var found = bodyParts(ctx).filter(function (b) { return b.info.path && b.info.path.indexOf(prefix) === 0; })[0];
    if (found) return { tr: trOf(ctx, found.object), info: found.info, manager: found.object, source: "BodyPartManager" };
    var memberTr = trOf(ctx, member.object), model = memberTr ? refValue(inv(ctx, "UnityEngine.Transform", "Find", memberTr, [Il2Cpp.string("Model")])) : null;
    if (model && Number(inv(ctx, "UnityEngine.Transform", "get_childCount", model, [])) > 0) {
      var first = refValue(inv(ctx, "UnityEngine.Transform", "GetChild", model, [0]));
      if (first) return { tr: first, info: pathInfo(ctx, first), manager: null, source: "Model/child0" };
    }
    return null;
  }
  function readAnchors(ctx, keys) {
    var out = [], anchors = (keys && keys.member && keys.member.anchors) || {};
    memberList(ctx).forEach(function (member) {
      if (out.length >= CAPS.anchors || ctx.pastSoft()) return;
      var root = memberRoot(ctx, member);
      if (!root) return;
      ["Hips", "Head", "LeftHand", "RightHand"].forEach(function (name) {
        if (out.length >= CAPS.anchors) return;
        var tr = null, source = null;
        if (root.manager && (name === "Hips" || name === "Head")) {
          var f = fieldAny(root.manager, backingNames(name.toLowerCase()));
          if (f && alive(f.value)) { tr = trOf(ctx, f.value); source = "BodyPartManager." + f.name; }
        }
        if (!tr && anchors[name]) { tr = refValue(inv(ctx, "UnityEngine.Transform", "Find", root.tr, [Il2Cpp.string(anchors[name])])); source = "Find"; }
        if (!tr) return;
        ctx.objects++;
        out.push({ key: "anchor:member" + member.slot + ":" + name, source: source,
          position: g(ctx, "UnityEngine.Transform", "get_position", tr, function (v) { return raw(ctx, v, 3, "anchors." + name, 9); }) });
      });
    });
    if (out.length < CAPS.anchors) {
      var origin = resolvePath(ctx, (keys && keys.stageOrigin) || "/EntryPoint/Live/Stages/MainStage");
      if (origin) out.push({ key: "anchor:stageOrigin", position: g(ctx, "UnityEngine.Transform", "get_position", origin, function (v) { return raw(ctx, v, 3, "anchors.stageOrigin", 9); }) });
    }
    return out;
  }
  function readRenderSettings(ctx) {
    var R = "UnityEngine.RenderSettings";
    function c4(path) { return function (v) { return raw(ctx, v, 4, "renderSettings." + path, 7); }; }
    function f(path) { return function (v) { return num(ctx, v, "renderSettings." + path); }; }
    var skybox = g(ctx, R, "get_skybox", null);
    return { fog: g(ctx, R, "get_fog", null, bool), fogMode: g(ctx, R, "get_fogMode", null, en("FogMode")),
      fogColor: g(ctx, R, "get_fogColor", null, c4("fogColor")), fogDensity: g(ctx, R, "get_fogDensity", null, f("fogDensity")),
      fogStartDistance: g(ctx, R, "get_fogStartDistance", null, f("fogStartDistance")),
      fogEndDistance: g(ctx, R, "get_fogEndDistance", null, f("fogEndDistance")),
      ambientMode: g(ctx, R, "get_ambientMode", null, en("AmbientMode")),
      ambientSkyColor: g(ctx, R, "get_ambientSkyColor", null, c4("ambientSkyColor")),
      ambientEquatorColor: g(ctx, R, "get_ambientEquatorColor", null, c4("ambientEquatorColor")),
      ambientGroundColor: g(ctx, R, "get_ambientGroundColor", null, c4("ambientGroundColor")),
      ambientIntensity: g(ctx, R, "get_ambientIntensity", null, f("ambientIntensity")),
      ambientLight: g(ctx, R, "get_ambientLight", null, c4("ambientLight")),
      reflectionIntensity: g(ctx, R, "get_reflectionIntensity", null, f("reflectionIntensity")),
      skybox: alive(skybox) ? nameOf(ctx, skybox) : null };
  }
  function readLights(ctx) {
    var L = "UnityEngine.Light", out = [];
    instances(ctx, H.findClass(L, true), 256).forEach(function (light) {
      if (out.length >= CAPS.lights || ctx.pastHard() || !activeGo(ctx, light)) return;
      ctx.objects++;
      var p = "lights[" + out.length + "]", info = pathInfo(ctx, light), tr = trOf(ctx, light);
      var item = withPath({ key: "light:" + info.path }, info);
      item.type = g(ctx, L, "get_type", light, en("LightType"));
      item.color = g(ctx, L, "get_color", light, function (v) { return raw(ctx, v, 4, p + ".color", 7); });
      item.intensity = g(ctx, L, "get_intensity", light, function (v) { return num(ctx, v, p + ".intensity"); });
      item.range = g(ctx, L, "get_range", light, function (v) { return num(ctx, v, p + ".range"); });
      item.spotAngle = g(ctx, L, "get_spotAngle", light, function (v) { return num(ctx, v, p + ".spotAngle"); });
      item.enabled = g(ctx, "UnityEngine.Behaviour", "get_enabled", light, bool);
      item.shadows = g(ctx, L, "get_shadows", light, en("LightShadows"));
      item.cullingMask = g(ctx, L, "get_cullingMask", light);
      var t = transformOf(ctx, tr, p, false);
      item.position = t.position; item.rotation = t.rotation;
      out.push(item);
    });
    return out;
  }

  // ------------------------------------------------------------------ record runner
  function section(ctx, record, name, fn, mode) {
    if (mode !== "always" && (ctx.pastHard() || (mode === "optional" && ctx.pastSoft()))) { ctx.cut(name); return; }
    try {
      var value = fn();
      if (value !== undefined) record[name] = value;
    } catch (error) { ctx.err(name, error); record[name] = null; }
  }
  function finish(ctx, record) {
    record.cost = ctx.cost();
    record.nonFinite = ctx.nonFinite;
    if (ctx.errors.length) record.errors = ctx.errors;
    return record;
  }
  function frame(options) {
    var ctx = new Ctx("frame", options), record = { kind: "frame" }, keys = options.keys || {}, directors = null;
    section(ctx, record, "directors", function () { directors = readDirectors(ctx); return directors.list; }, "always");
    section(ctx, record, "clock", function () { return readClock(ctx, directors); }, "always");
    section(ctx, record, "scene", function () { return scene(ctx); }, "always");
    // The camera census, the correctors and the cameras are read in every frame whatever the
    // budget says (bounded by CAPS.cameras / CAPS.correctors): the main camera's FoV, projection
    // and corrector are the values the comparison exists for. Past the soft budget only the
    // cameras after index 0 degrade, to summary-only (key, role, enabled, fieldOfView, aspect).
    section(ctx, record, "cameraCensus", function () { correctorObjects(ctx); cameraCensus(ctx); return undefined; }, "always");
    section(ctx, record, "correctors", function () { return readCorrectors(ctx); }, "always");
    section(ctx, record, "cameras", function () {
      var out = [];
      (ctx.memo.cameras || []).forEach(function (c, i) {
        var detailed = i === 0 || (i < CAPS.camerasDetailed && !ctx.pastSoft());
        if (!detailed && i < CAPS.camerasDetailed) ctx.cut("cameras.detail");
        ctx.objects++;
        out.push(cameraDetail(ctx, c, i, detailed));
      });
      return out;
    }, "always");
    section(ctx, record, "cameraWork", function () { return readCameraWork(ctx); }, "required");
    section(ctx, record, "globals", function () { return readGlobals(ctx, keys); }, "required");
    section(ctx, record, "members", function () { return readMembersIdentity(ctx); }, "required");
    section(ctx, record, "anchors", function () { return readAnchors(ctx, keys); }, "optional");
    section(ctx, record, "renderSettings", function () { return readRenderSettings(ctx); }, "optional");
    section(ctx, record, "lights", function () { return readLights(ctx); }, "optional");
    section(ctx, record, "clockEnd", function () { return readClockEnd(ctx, directors); }, "always");
    return finish(ctx, record);
  }

  // ------------------------------------------------------------------ full parts
  function cursorOf(options) { return options.cursor && typeof options.cursor === "object" ? options.cursor : {}; }
  function childCount(ctx, tr) { var n = inv(ctx, "UnityEngine.Transform", "get_childCount", tr, []); return typeof n === "number" ? n : 0; }
  function childAt(ctx, tr, index) {
    if (index < 0 || index >= childCount(ctx, tr)) return null;
    return refValue(inv(ctx, "UnityEngine.Transform", "GetChild", tr, [index]));
  }
  // Pre-order walk of a Transform subtree, resumable from a child-index path (plain JSON).
  function walk(ctx, root, start, maxDepth, limit, visit) {
    var stack = [], node = root, path = [], names = [nameOf(ctx, root)], emitted = 0, cur;
    start = Array.isArray(start) ? start : [];
    for (var k = 0; k < start.length; k++) {
      var count = childCount(ctx, node), index = Number(start[k]);
      stack.push({ tr: node, path: path, names: names, count: count, next: index + 1 });
      if (!(index >= 0 && index < count)) { stack[stack.length - 1].next = count; node = null; break; }
      node = childAt(ctx, node, index);
      if (!node) { node = null; break; }
      path = path.concat([index]); names = names.concat([nameOf(ctx, node)]);
    }
    cur = node ? { tr: node, path: path, names: names } : null;
    for (;;) {
      if (cur) {
        if (emitted >= limit || (emitted > 0 && ctx.pastSoft())) return { next: cur.path, emitted: emitted };
        ctx.objects++;
        var count2 = visit(cur.tr, cur.path, cur.names);
        emitted++;
        if (cur.path.length < maxDepth && count2 > 0) stack.push({ tr: cur.tr, path: cur.path, names: cur.names, count: count2, next: 0 });
        cur = null;
      }
      while (stack.length) {
        var top = stack[stack.length - 1];
        if (top.next < top.count) {
          var i = top.next++, child = childAt(ctx, top.tr, i);
          if (child) { cur = { tr: child, path: top.path.concat([i]), names: top.names.concat([nameOf(ctx, child)]) }; break; }
        } else stack.pop();
      }
      if (!cur) return { next: null, emitted: emitted };
    }
  }
  function partCensus(ctx, options) {
    var cursor = cursorOf(options), done = Number(cursor.emitted) || 0;
    var root = resolvePath(ctx, options.root || "/EntryPoint");
    if (!root) return { census: { roots: [], nodes: [] }, next: null };
    var COMP = H.findClass("UnityEngine.Component", true), nodes = [];
    var result = walk(ctx, root, cursor.path, CAPS.censusDepth, Math.min(CAPS.censusChunk, CAPS.censusNodes - done), function (tr, path, names) {
      var go = inv(ctx, "UnityEngine.Component", "get_gameObject", tr, []), count = childCount(ctx, tr);
      var node = { path: "/" + names.map(stripName).join("/"), index: path.length ? path[path.length - 1] : 0, depth: path.length,
        activeSelf: g(ctx, "UnityEngine.GameObject", "get_activeSelf", go, bool),
        activeInHierarchy: g(ctx, "UnityEngine.GameObject", "get_activeInHierarchy", go, bool), childCount: count, components: [] };
      var rawPath = "/" + names.join("/");
      if (rawPath !== node.path) node.rawPath = rawPath;
      try {
        items(inv(ctx, "UnityEngine.Component", "GetComponents", tr, [COMP.type.object]), CAPS.components).forEach(function (component) {
          node.components.push(isObj(component) ? H.fullType(component) : null);
        });
      } catch (error) { ctx.err("census.components", error); }
      nodes.push(node);
      return count;
    });
    var total = done + result.emitted;
    return { census: { roots: [options.root || "/EntryPoint"], nodes: nodes },
      next: result.next && total < CAPS.censusNodes ? { path: result.next, emitted: total } : null };
  }
  function partQuality(ctx) {
    var holders = ["LiveDirector", "LiveDirectorBase", "LiveCoreCameraManager", "LiveCoreStageManager", "LiveCoreMemberManager", "LiveMvScene"];
    var out = { holder: null, values: null, unity: {} };
    for (var i = 0; i < holders.length && !out.values; i++) {
      var klass = cls(ctx, holders[i]);
      if (!klass || !unityObjectClass(klass)) continue;
      var objects = instances(ctx, klass, 16);
      for (var j = 0; j < objects.length && !out.values; j++) {
        var found = fieldAny(objects[j], ["liveQualitySetting", "<LiveQualitySetting>k__BackingField", "qualitySetting"]);
        if (!found || !isObj(found.value)) continue;
        ctx.objects++;
        out.holder = klassName(klass) + "." + found.name;
        out.voClass = H.fullType(found.value);
        out.values = {};
        layoutOf(found.value.class).forEach(function (entry) {
          var m = /^<(.+)>k__BackingField$/.exec(entry.name), name = m ? m[1] : entry.name;
          var value = fv(found.value, entry.name), conv = convert(ctx, value, entry.name, 2, "quality." + name, entry.typeName);
          out.values[name] = conv.t === "enum" ? conv.v : PRIMITIVE[entry.typeName] || conv.t === "int" || conv.t === "f32" ? conv.v : conv;
        });
      }
    }
    var Q = "UnityEngine.QualitySettings";
    out.unity.activeColorSpace = g(ctx, Q, "get_activeColorSpace", null, en("ColorSpace"));
    out.unity.vSyncCount = g(ctx, Q, "get_vSyncCount", null);
    out.unity.antiAliasing = g(ctx, Q, "get_antiAliasing", null);
    out.unity.targetFrameRate = g(ctx, "UnityEngine.Application", "get_targetFrameRate", null);
    return { quality: out, next: null };
  }
  function sortedActive(ctx, klass, cursor, cap, total, emitBudget, visit) {
    var after = typeof cursor.afterInstanceId === "number" ? cursor.afterInstanceId : null, done = Number(cursor.emitted) || 0;
    var list = instances(ctx, klass, CAPS.enumerate).map(function (o) { return { o: o, id: iid(o) }; })
      .filter(function (e) { return after === null || e.id > after; });
    list.sort(function (a, b) { return a.id - b.id; });
    var out = [], last = after, i;
    for (i = 0; i < list.length; i++) {
      if (out.length >= cap || done + out.length >= total) break;
      if (i > 0 && ctx.pastSoft()) { ctx.cut("objects"); break; }
      last = list[i].id;
      ctx.objects++;
      if (!activeGo(ctx, list[i].o)) continue;
      try { out.push(visit(list[i].o, list[i].id, out.length)); } catch (error) { ctx.err("object:" + list[i].id, error); }
    }
    var exhausted = i >= list.length || done + out.length >= total;
    return { list: out, next: exhausted ? null : { afterInstanceId: last, emitted: done + out.length } };
  }
  function scopeOf(path) {
    var m = /^\/EntryPoint\/Live\/Members\/Member(\d+)(\/|$)/.exec(path || "");
    if (m) return "member" + m[1];
    if (/^\/EntryPoint\/Live\/Stages\/[^/]+\/Effect(\/|$)/.test(path || "")) return "effect";
    if (/^\/EntryPoint\/Live\/Stages\//.test(path || "")) return "stage";
    return "other";
  }
  function materialSummary(ctx, material) {
    var id = iid(material), memo = ctx.memo.materials || (ctx.memo.materials = {});
    if (memo[id]) return memo[id];
    var shader = g(ctx, "UnityEngine.Material", "get_shader", material);
    var keywords = g(ctx, "UnityEngine.Material", "get_shaderKeywords", material, function (v) { return items(v, CAPS.keywords).map(str); });
    memo[id] = { instanceId: id, name: nameOf(ctx, material), shader: alive(shader) ? nameOf(ctx, shader) : null,
      renderQueue: g(ctx, "UnityEngine.Material", "get_renderQueue", material), keywords: keywords || [] };
    return memo[id];
  }
  function partRenderers(ctx, options) {
    var R = "UnityEngine.Renderer", SMR = H.findClass("UnityEngine.SkinnedMeshRenderer", true), MF = H.findClass("UnityEngine.MeshFilter", true);
    var result = sortedActive(ctx, H.findClass(R, true), cursorOf(options), CAPS.rendererChunk, CAPS.renderers, null, function (r, id, n) {
      var p = "renderers[" + n + "]", info = pathInfo(ctx, r), tr = trOf(ctx, r);
      var item = withPath({ key: "renderer:" + info.path }, info);
      item.scope = scopeOf(info.path); item.class = H.fullType(r); item.instanceId = id;
      var mesh = null;
      if (isA(r, SMR)) mesh = g(ctx, "UnityEngine.SkinnedMeshRenderer", "get_sharedMesh", r);
      else if (MF) { var filter = g(ctx, "UnityEngine.Component", "GetComponent", r, null, [MF.type.object]); if (alive(filter)) mesh = g(ctx, "UnityEngine.MeshFilter", "get_sharedMesh", filter); }
      item.mesh = alive(mesh) ? nameOf(ctx, mesh) : null;
      item.enabled = g(ctx, R, "get_enabled", r, bool);
      // The GameObject layer: the comparator tests it against the main camera's cullingMask
      // (members hidden by a culler clip stay enabled and active on the Invisible layer).
      var go = refValue(g(ctx, "UnityEngine.Component", "get_gameObject", r));
      item.layer = go ? g(ctx, "UnityEngine.GameObject", "get_layer", go, enumInt) : null;
      item.isVisible = g(ctx, R, "get_isVisible", r, bool);
      item.activeInHierarchy = true;
      item.bounds = g(ctx, R, "get_bounds", r, function (v) { var b = raw(ctx, v, 6, p + ".bounds", 9); return b ? { center: b.slice(0, 3), extents: b.slice(3) } : null; });
      item.transform = transformOf(ctx, tr, p + ".transform", false);
      item.lightmapIndex = g(ctx, R, "get_lightmapIndex", r);
      item.lightmapScaleOffset = g(ctx, R, "get_lightmapScaleOffset", r, function (v) { return raw(ctx, v, 4, p + ".lightmapScaleOffset", 9); });
      item.sortingOrder = g(ctx, R, "get_sortingOrder", r);
      item.materials = [];
      var shared = g(ctx, R, "get_sharedMaterials", r, function (v) { return items(v, CAPS.slots); }) || [];
      shared.forEach(function (material, slot) {
        if (!alive(material)) { item.materials.push({ slot: slot, instanceId: null }); return; }
        var s = materialSummary(ctx, material);
        item.materials.push({ slot: slot, instanceId: s.instanceId, name: s.name, shader: s.shader, renderQueue: s.renderQueue, keywords: s.keywords });
      });
      if (shared.total > shared.length) item.materialsTotal = shared.total;
      return item;
    });
    return { renderers: result.list, next: result.next };
  }
  var DEFAULT_PROPS = { _MainTex: "tex", _TintColor: "color", _AmbientColor: "color", _BlendColor: "color", _Color: "color",
    _EmissiveColor: "color", _EmissiveIntensity: "float", _Cutoff: "float", _MainTexMipmapBias: "float", _RimlightColor: "color",
    _RimlightDirection: "vector", _RimglightIntensity: "float", _RimglightPower: "float" };
  function materialProps(shaders, shaderName) {
    if (shaders && shaders[shaderName]) return { props: shaders[shaderName], source: "keys" };
    var union = {};
    Object.keys(DEFAULT_PROPS).forEach(function (k) { union[k] = DEFAULT_PROPS[k]; });
    return { props: union, source: "default" };
  }
  // A wanted material through the renderer slot that uses it (options.materials[i].resolve =
  // [{path, slot, rendererId}] from the renderers part): GameObject.Find + Transform.Find,
  // GetComponent(Renderer), get_sharedMaterials()[slot], renderer and material instance ids checked.
  function materialViaRenderer(ctx, w, R) {
    var list = Array.isArray(w.resolve) ? w.resolve.slice(0, 2) : [];
    for (var k = 0; k < list.length; k++) {
      var ref = list[k] || {};
      if (typeof ref.path !== "string" || typeof ref.slot !== "number" || ref.slot < 0 || ref.slot >= CAPS.slots) continue;
      var tr = resolvePath(ctx, ref.path);
      if (!tr) continue;
      var renderer = refValue(g(ctx, "UnityEngine.Component", "GetComponent", tr, null, [R.type.object]));
      if (!alive(renderer) || (typeof ref.rendererId === "number" && iid(renderer) !== ref.rendererId)) continue;
      var shared = g(ctx, "UnityEngine.Renderer", "get_sharedMaterials", renderer, function (v) { return items(v, CAPS.slots); }) || [];
      var material = ref.slot < shared.length ? shared[ref.slot] : null;
      if (alive(material) && iid(material) === w.instanceId) return material;
    }
    return null;
  }
  function partMaterials(ctx, options) {
    var wanted = Array.isArray(options.materials) ? options.materials.slice(0, CAPS.materialChunk) : [];
    var M = "UnityEngine.Material", R = H.findClass("UnityEngine.Renderer", true), scanned = null;
    // Fallback only, at most once per chunk: one FindObjectsOfTypeAll(Material) for the wanted
    // materials that no renderer slot resolved (renderer gone, renamed or inactive since).
    function scan() {
      if (scanned) return scanned;
      var ids = {};
      scanned = {};
      wanted.forEach(function (w) { ids[w.instanceId] = true; });
      instances(ctx, H.findClass(M, true), CAPS.enumerate).forEach(function (o) { var id = iid(o); if (ids[id]) scanned[id] = o; });
      return scanned;
    }
    var out = [], processed = 0, resolution = { renderer: 0, scan: 0, missing: 0 };
    for (var i = 0; i < wanted.length; i++) {
      if (i > 0 && ctx.pastSoft()) { ctx.cut("materials"); break; }
      var w = wanted[i], material = null, via = "renderer";
      ctx.objects++;
      try { material = R ? materialViaRenderer(ctx, w, R) : null; } catch (error) { ctx.err("materials.resolve", error); material = null; }
      if (!material) { via = "scan"; material = scan()[w.instanceId] || null; }
      if (!alive(material)) {
        resolution.missing++; processed++;
        out.push({ instanceId: w.instanceId, usedBy: w.usedBy || [], missingObject: true });
        continue;
      }
      var s = materialSummary(ctx, material), spec = materialProps(options.shaders, s.shader);
      var item = { instanceId: w.instanceId, name: s.name, shader: s.shader, usedBy: w.usedBy || [], resolvedBy: via, propertySource: spec.source, properties: {}, missing: [] };
      var names = Object.keys(spec.props).slice(0, CAPS.properties), complete = true;
      for (var j = 0; j < names.length; j++) {
        // The first material of a chunk always completes (progress is guaranteed); a later one
        // that crosses the hard budget is dropped here and retried first in the next chunk.
        if (i > 0 && ctx.pastHard()) { ctx.cut("materials.properties"); complete = false; break; }
        var name = names[j], type = spec.props[name], id = propertyId(ctx, name), p = "materials." + s.name + "." + name;
        if (!g(ctx, M, "HasProperty", material, bool, [id])) { item.missing.push(name); continue; }
        if (type === "color") item.properties[name] = { t: "color", v: g(ctx, M, "GetColor", material, function (v) { return raw(ctx, v, 4, p, 7); }, [id]) };
        else if (type === "vector") item.properties[name] = { t: "vector", v: g(ctx, M, "GetVector", material, function (v) { return raw(ctx, v, 4, p, 7); }, [id]) };
        else if (type === "tex") {
          var tex = g(ctx, M, "GetTexture", material, null, [id]);
          var scale = g(ctx, M, "GetTextureScale", material, function (v) { return raw(ctx, v, 2, p + ".scale", 7); }, [id]);
          var offset = g(ctx, M, "GetTextureOffset", material, function (v) { return raw(ctx, v, 2, p + ".offset", 7); }, [id]);
          item.properties[name] = { t: "tex", v: alive(tex) ? textureInfo(ctx, tex, p) : null, st: scale && offset ? scale.concat(offset) : null };
        } else item.properties[name] = { t: "float", v: g(ctx, M, "GetFloat", material, function (v) { return num(ctx, v, p); }, [id]) };
      }
      if (!complete) break;
      resolution[via]++; processed++;
      out.push(item);
    }
    return { materials: out, processed: processed, resolution: resolution, next: null };
  }
  function materialIdsOf(value) {
    var out = [];
    function add(v) { if (isObj(v) && unityObjectClass(v.class) && /Material$/.test(v.class.name)) out.push(iid(v)); }
    if (value instanceof Il2Cpp.Array) items(value, 64).forEach(add);
    else if (value instanceof Il2Cpp.Object && isObj(value)) {
      var name = klassName(value.class) || "";
      if (/List`1/.test(name)) { var backing = fv(value, "_items"), size = Number(fv(value, "_size")) || 0; if (backing instanceof Il2Cpp.Array) items(backing, Math.min(size, 64)).forEach(add); }
      else add(value);
    }
    return out;
  }
  function partLightingRefs(ctx, options) {
    var classes = (options.keys && Array.isArray(options.keys.lightingClasses) ? options.keys.lightingClasses : DEFAULT_LIGHTING).slice(0, 16);
    var out = [];
    classes.forEach(function (key) {
      if (ctx.pastHard()) { ctx.cut("lightingRefs"); return; }
      var klass = cls(ctx, key);
      instances(ctx, klass, 64).slice(0, CAPS.lightingPerClass).forEach(function (object) {
        if (!activeGo(ctx, object)) return;
        ctx.objects++;
        var info = pathInfo(ctx, object);
        layoutOf(object.class).forEach(function (entry) {
          if (!/Material/.test(entry.typeName || "")) return;
          var ids = materialIdsOf(fv(object, entry.name));
          out.push({ componentKey: "component:" + info.path + "#" + object.class.name, class: H.fullType(object), field: entry.name, materials: ids });
        });
      });
    });
    return { lightingRefs: out, next: null };
  }
  function partMembers(ctx, options) {
    var cursor = cursorOf(options), index = Number(cursor.index) || 0, list = memberList(ctx), keys = options.keys || {};
    var member = list[index];
    if (!member) return { members: [], next: null };
    ctx.objects++;
    var out = withPath({ slot: member.slot, formationPosition: member.formationPosition, memberId: member.memberId, suitId: member.suitId }, member.info);
    var root = memberRoot(ctx, member);
    out.rootPath = root ? root.info.path : null;
    out.rootSource = root ? root.source : null;
    var memberTr = trOf(ctx, member.object), model = memberTr ? refValue(inv(ctx, "UnityEngine.Transform", "Find", memberTr, [Il2Cpp.string("Model")])) : null;
    out.modelLocalScale = model ? g(ctx, "UnityEngine.Transform", "get_localScale", model, function (v) { return raw(ctx, v, 3, "members.modelLocalScale", 9); }) : null;
    var scaling = instances(ctx, cls(ctx, "LiveCoreMemberNodeScaling"), 32).filter(function (o) { var p = pathInfo(ctx, o).path; return p && p.indexOf(member.root) === 0; })[0];
    out.nodeScaling = scaling ? readFields(ctx, scaling, 1, "members.nodeScaling") : null;
    out.bones = [];
    var bones = (keys.member && Array.isArray(keys.member.bones) ? keys.member.bones : []).slice(0, CAPS.bonesPerMember);
    for (var i = 0; root && i < bones.length; i++) {
      if (i > 0 && ctx.pastHard()) { ctx.cut("members.bones"); break; }
      var bone = refValue(inv(ctx, "UnityEngine.Transform", "Find", root.tr, [Il2Cpp.string(bones[i])]));
      if (!bone) { out.bones.push({ key: "member:" + member.slot + ":" + bones[i], missing: true }); continue; }
      ctx.objects++;
      var t = transformOf(ctx, bone, "members.bones[" + i + "]", true);
      out.bones.push({ key: "member:" + member.slot + ":" + bones[i], path: root.info.path + "/" + bones[i], position: t.position,
        rotation: t.rotation, lossyScale: t.lossyScale, localPosition: t.localPosition, localRotation: t.localRotation });
    }
    out.blendShapes = [];
    var SMR = "UnityEngine.SkinnedMeshRenderer", recorded = 0;
    instances(ctx, H.findClass(SMR, true), 1024).forEach(function (r) {
      if (ctx.pastSoft() || recorded >= CAPS.blendShapes) return;
      var info = pathInfo(ctx, r);
      if (!info.path || info.path.indexOf(member.root + "/") !== 0 || !activeGo(ctx, r)) return;
      var mesh = g(ctx, SMR, "get_sharedMesh", r);
      if (!alive(mesh)) return;
      var count = Number(g(ctx, "UnityEngine.Mesh", "get_blendShapeCount", mesh)) || 0, weights = {};
      for (var k = 0; k < count && k < CAPS.blendShapesInspected && recorded < CAPS.blendShapes; k++) {
        if (ctx.pastHard()) { ctx.cut("members.blendShapes"); break; }
        var w = g(ctx, SMR, "GetBlendShapeWeight", r, function (v) { return num(ctx, v, "blendShape"); }, [k]);
        if (w) { weights[g(ctx, "UnityEngine.Mesh", "GetBlendShapeName", mesh, str, [k]) || String(k)] = w; recorded++; }
      }
      out.blendShapes.push({ rendererKey: "renderer:" + info.path, count: count, weights: weights });
    });
    return { members: [out], next: index + 1 < list.length ? { index: index + 1 } : null };
  }
  function springManagers(ctx) {
    var klass = cls(ctx, "SwingBoneManager"), out = [];
    if (klass && unityObjectClass(klass)) {
      instances(ctx, klass, 64).forEach(function (m) { if (activeGo(ctx, m)) out.push({ object: m, id: iid(m), source: "FindObjectsOfTypeAll" }); });
      out.sort(function (a, b) { return a.id - b.id; });
      return out;
    }
    instances(ctx, cls(ctx, "LiveCoreMemberManager"), 4).forEach(function (manager) {
      var found = fieldAny(manager, ["swingBoneManagers", "<SwingBoneManagers>k__BackingField"]);
      if (!found) return;
      var list = found.value instanceof Il2Cpp.Array ? items(found.value, 16) : [];
      if (!list.length && isObj(found.value)) { var backing = fv(found.value, "_items"), size = Number(fv(found.value, "_size")) || 0; if (backing instanceof Il2Cpp.Array) list = items(backing, Math.min(16, size)); }
      list.forEach(function (m, i) { if (isObj(m)) out.push({ object: m, id: i, source: "LiveCoreMemberManager." + found.name + "[" + i + "]" }); });
    });
    return out;
  }
  function partSprings(ctx, options) {
    var cursor = cursorOf(options), index = Number(cursor.index) || 0, managers = springManagers(ctx), entry = managers[index];
    if (!entry) return { springs: [], next: null };
    ctx.objects++;
    var manager = entry.object, isUnity = unityObjectClass(manager.class), info = isUnity ? pathInfo(ctx, manager) : { path: null, rawPath: null };
    var out = { managerKey: "spring:" + (info.path || entry.source), class: H.fullType(manager), source: entry.source, bones: [] };
    if (info.path) out.path = info.path;
    var boneField = null;
    layoutOf(manager.class).forEach(function (f) { if (!boneField && /SwingBone(\[\]|>)/.test(f.typeName || "") && !/Manager/.test(f.typeName)) boneField = f.name; });
    out.fields = readFields(ctx, manager, 1, "springs.fields", boneField ? [boneField] : null);
    if (boneField) {
      var value = fv(manager, boneField), bones = value instanceof Il2Cpp.Array ? items(value, CAPS.swingBones) : [];
      if (!bones.length && isObj(value)) { var backing = fv(value, "_items"), size = Number(fv(value, "_size")) || 0; if (backing instanceof Il2Cpp.Array) bones = items(backing, Math.min(CAPS.swingBones, size)); }
      out.boneField = boneField; out.boneCount = bones.total !== undefined ? bones.total : bones.length;
      for (var i = 0; i < bones.length; i++) {
        if (i > 0 && ctx.pastSoft()) { ctx.cut("springs.bones"); out.incomplete = true; break; }
        var bone = bones[i];
        if (!isObj(bone)) continue;
        ctx.objects++;
        var item = { index: i, class: H.fullType(bone) };
        if (unityObjectClass(bone.class) && alive(bone)) {
          var binfo = pathInfo(ctx, bone), tr = trOf(ctx, bone);
          item.key = "spring:" + binfo.path; item.path = binfo.path;
          item.localRotation = g(ctx, "UnityEngine.Transform", "get_localRotation", tr, function (v) { return raw(ctx, v, 4, "springs.localRotation", 9); });
        }
        var fields = readFields(ctx, bone, CAPS.fieldDepth, "springs.bone"), compact = {}, n = 0;
        Object.keys(fields || {}).forEach(function (k) { if (n < 12 && /tip|rot|position|angle|length|velocity|weight/i.test(k)) { compact[k] = fields[k]; n++; } });
        item.fields = compact;
        out.bones.push(item);
      }
    }
    return { springs: [out], next: index + 1 < managers.length ? { index: index + 1 } : null };
  }
  function partStageNodes(ctx, options) {
    var cursor = cursorOf(options), bindings = (options.keys && Array.isArray(options.keys.bindings) ? options.keys.bindings : []);
    var b = Number(cursor.binding) || 0, done = Number(cursor.emitted) || 0, out = [];
    while (b < bindings.length && done + out.length < CAPS.stageNodes) {
      var binding = bindings[b], root = resolvePath(ctx, binding);
      if (!root) { out.push({ binding: binding, relPath: "", missing: true }); b++; cursor = {}; if (ctx.pastSoft()) break; continue; }
      var limit = Math.min(CAPS.stageChunk - out.length, CAPS.stageNodes - done - out.length);
      if (limit <= 0) break;
      var result = walk(ctx, root, cursor.path, CAPS.stageDepth, limit, function (tr, path, names) {
        var go = inv(ctx, "UnityEngine.Component", "get_gameObject", tr, []), t = transformOf(ctx, tr, "stageNodes[" + out.length + "]", false);
        var rel = names.slice(1).map(stripName).join("/");
        out.push({ binding: binding, relPath: rel, path: binding + (rel ? "/" + rel : ""),
          activeSelf: g(ctx, "UnityEngine.GameObject", "get_activeSelf", go, bool),
          activeInHierarchy: g(ctx, "UnityEngine.GameObject", "get_activeInHierarchy", go, bool),
          position: t.position, rotation: t.rotation, lossyScale: t.lossyScale });
        return childCount(ctx, tr);
      });
      if (result.next) return { stageNodes: out, next: { binding: b, path: result.next, emitted: done + out.length } };
      b++; cursor = {};
      if (out.length >= CAPS.stageChunk || ctx.pastSoft()) break;
    }
    var more = b < bindings.length && done + out.length < CAPS.stageNodes;
    return { stageNodes: out, next: more ? { binding: b, path: [], emitted: done + out.length } : null };
  }
  function partParticles(ctx, options) {
    var P = "UnityEngine.ParticleSystem", PSR = H.findClass("UnityEngine.ParticleSystemRenderer", true);
    var result = sortedActive(ctx, H.findClass(P, true), cursorOf(options), CAPS.particleChunk, CAPS.particles, null, function (ps, id, n) {
      var p = "particles[" + n + "]", info = pathInfo(ctx, ps), item = withPath({ key: "particles:" + info.path }, info);
      item.instanceId = id;
      item.isPlaying = g(ctx, P, "get_isPlaying", ps, bool);
      item.isEmitting = g(ctx, P, "get_isEmitting", ps, bool);
      item.isPaused = g(ctx, P, "get_isPaused", ps, bool);
      item.particleCount = g(ctx, P, "get_particleCount", ps);
      item.time = g(ctx, P, "get_time", ps, function (v) { return num(ctx, v, p + ".time", 9); });
      item.randomSeed = g(ctx, P, "get_randomSeed", ps, function (v) { return num(ctx, v, p + ".randomSeed", 15); });
      item.useAutoRandomSeed = g(ctx, P, "get_useAutoRandomSeed", ps, bool);
      var renderer = PSR ? g(ctx, "UnityEngine.Component", "GetComponent", ps, null, [PSR.type.object]) : null;
      item.rendererEnabled = alive(renderer) ? g(ctx, "UnityEngine.Renderer", "get_enabled", renderer, bool) : null;
      return item;
    });
    return { particles: result.list, next: result.next };
  }
  function partPost(ctx) {
    var out = { holders: [], enablePostEffect: null }, seen = {};
    function add(object, source) {
      var id = iid(object);
      if (seen[id] || out.holders.length >= CAPS.holders || ctx.pastHard()) return;
      seen[id] = true;
      ctx.objects++;
      var info = pathInfo(ctx, object), item = withPath({ key: "post:" + info.path + "#" + object.class.name, class: H.fullType(object), source: source }, info);
      item.enabled = g(ctx, "UnityEngine.Behaviour", "get_enabled", object, bool);
      item.fields = readFields(ctx, object, 0, "post.fields");
      if (item.fields && item.fields.enablePostEffect && out.enablePostEffect === null) out.enablePostEffect = item.fields.enablePostEffect.v;
      out.holders.push(item);
    }
    instances(ctx, cls(ctx, "LiveCoreCamera"), 16).forEach(function (o) { if (activeGo(ctx, o)) add(o, "LiveCoreCamera"); });
    var COMP = H.findClass("UnityEngine.Component", true);
    cameraCensus(ctx).slice(0, CAPS.camerasDetailed).forEach(function (c) {
      if (ctx.pastSoft()) return;
      items(g(ctx, "UnityEngine.Component", "GetComponents", c.object, null, [COMP.type.object]), 24).forEach(function (component) {
        if (isObj(component) && POST_CLASS.test(component.class.name) && alive(component)) add(component, "camera:" + c.key);
      });
    });
    return { post: out, next: null };
  }
  function sample(options) {
    var part = String(options.part || "frame");
    if (PARTS.indexOf(part) < 0) throw new Error("MVDUMP_UNKNOWN_PART:" + part);
    if (part === "frame") return frame(options);
    var ctx = new Ctx("full", options), record = { kind: "full", part: part, cursor: cursorOf(options) }, directors = null;
    section(ctx, record, "directors", function () { directors = readDirectors(ctx); return undefined; }, "always");
    section(ctx, record, "clock", function () { return readClock(ctx, directors); }, "always");
    var body = null;
    try {
      if (part === "census") body = partCensus(ctx, options);
      else if (part === "quality") body = partQuality(ctx, options);
      else if (part === "fovmodNative") body = { fovmodNative: H.nativeFeatureState(), next: null };
      else if (part === "renderers") body = partRenderers(ctx, options);
      else if (part === "materials") body = partMaterials(ctx, options);
      else if (part === "lightingRefs") body = partLightingRefs(ctx, options);
      else if (part === "members") body = partMembers(ctx, options);
      else if (part === "springs") body = partSprings(ctx, options);
      else if (part === "stageNodes") body = partStageNodes(ctx, options);
      else if (part === "particles") body = partParticles(ctx, options);
      else if (part === "post") body = partPost(ctx, options);
    } catch (error) { ctx.err(part, error); body = { next: null }; body[part] = null; }
    Object.keys(body).forEach(function (k) { record[k] = body[k]; });
    if (record.next === undefined) record.next = null;
    section(ctx, record, "clockEnd", function () { return readClockEnd(ctx, directors); }, "always");
    return finish(ctx, record);
  }

  // ------------------------------------------------------------------ probe (metadata only)
  function classInfo(entry) {
    var found = lookupEntry(entry, null);
    resolved[entry.key] = found ? found.fullName : null;
    var out = { key: entry.key, requested: entry.candidates.slice(0, 4), found: !!found };
    if (!found) return out;
    var klass = found.klass;
    out.fullName = found.fullName;
    try { out.assembly = klass.assemblyName || (klass.image && klass.image.assembly && klass.image.assembly.name) || null; } catch (_) { out.assembly = null; }
    out.parents = [];
    var p = klass.parent, guard = 0;
    while (p && guard++ < 6) { out.parents.push(klassName(p)); p = p.parent; }
    try { out.unityObject = unityObjectClass(klass); } catch (_) { out.unityObject = null; }
    try { out.component = classIsA(klass, H.findClass("UnityEngine.Component", true)); } catch (_) { out.component = null; }
    out.fields = [];
    var k = klass, depth = 0;
    while (k && depth++ < 6 && out.fields.length < 64) {
      if (/^(UnityEngine|System)(\.|$)/.test(k.namespace || "") && k !== klass) break;
      (k.fields || []).forEach(function (f) {
        if (out.fields.length >= 64) return;
        var typeClass = null;
        try { typeClass = f.type.class; } catch (_) {}
        out.fields.push({ name: f.name, type: f.type.name, offset: f.offset, static: !!f.isStatic, declaredIn: klassName(k),
          valueType: typeClass ? !!typeClass.isValueType : null, enum: typeClass ? !!typeClass.isEnum : null });
      });
      k = k.parent;
    }
    if (entry.unity) {
      out.methods = {};
      var className = found.fullName;
      (ALLOW[className] || []).forEach(function (name) {
        var argc = (SIG[className + "::" + name] || []).length;
        try { out.methods[name] = !!klass.tryMethod(name, argc); } catch (_) { out.methods[name] = false; }
      });
    }
    return out;
  }
  function layoutSelfCheck(ctx) {
    var out = { ok: false };
    var cams = cameraCensus(ctx), main = cams.filter(function (c) { return c.role === "main"; })[0] || cams[0];
    if (!main) { out.error = "no active camera"; return out; }
    out.camera = main.info.path;
    var proj = inv(ctx, "UnityEngine.Camera", "get_projectionMatrix", main.object, []);
    var rawProj = raw(ctx, proj, 16, "layout.projection", 9);
    out.projectionRaw = rawProj;
    out.m32Field = num(ctx, Number(proj.field("m32").value), "layout.m32", 9);
    out.m23Field = num(ctx, Number(proj.field("m23").value), "layout.m23", 9);
    out.m00Field = num(ctx, Number(proj.field("m00").value), "layout.m00", 9);
    out.m32Raw = rawProj[11]; out.m23Raw = rawProj[14]; out.m00Raw = rawProj[0];
    out.columnMajor = rawProj[11] === out.m32Field && rawProj[14] === out.m23Field && rawProj[0] === out.m00Field;
    out.perspectiveSane = rawProj[11] === -1 && rawProj[15] === 0;
    var position = inv(ctx, "UnityEngine.Transform", "get_position", trOf(ctx, main.object), []);
    out.vec3Raw = raw(ctx, position, 3, "layout.position", 9);
    out.vec3Field = ["x", "y", "z"].map(function (axis) { return num(ctx, Number(position.field(axis).value), "layout.position." + axis, 9); });
    out.vec3Match = out.vec3Raw.every(function (v, i) { return v === out.vec3Field[i]; });
    out.ok = out.columnMajor && out.vec3Match;
    return out;
  }
  function probe(options) {
    var ctx = new Ctx("full", { budget: options.budget || { soft: 2000, hard: 4000 } });
    var per = Math.max(1, Math.min(8, Number(options.perChunk) || 8)), chunk = Math.max(0, Number(options.chunk) || 0);
    var entries = CLASS_TABLE.slice(chunk * per, chunk * per + per), out = { kind: "probe", chunk: chunk, chunks: Math.ceil(CLASS_TABLE.length / per),
      extensionVersion: EXT_VERSION, classes: [] };
    entries.forEach(function (entry) {
      try { out.classes.push(classInfo(entry)); } catch (error) { out.classes.push({ key: entry.key, found: false, error: short(error) }); }
    });
    if (chunk === 0 && options.layout !== false) {
      try { out.layoutSelfCheck = layoutSelfCheck(ctx); } catch (error) { out.layoutSelfCheck = { ok: false, error: short(error) }; }
    }
    if (chunk === 0) {
      try { var o = initOffsets(); out.objectLayout = { m_CachedPtr: o.cachedPtr, m_InstanceID: o.instanceId }; } catch (error) { out.objectLayout = { error: short(error) }; }
    }
    out.resolved = {};
    Object.keys(resolved).forEach(function (k) { out.resolved[k] = resolved[k]; });
    out.done = (chunk + 1) * per >= CLASS_TABLE.length;
    return finish(ctx, out);
  }

  globalThis.QA_MVDUMP_EXT = Object.freeze({ version: EXT_VERSION, parts: PARTS.slice(), deny: DENY.source,
    allow: JSON.parse(JSON.stringify(ALLOW)), classTable: JSON.parse(JSON.stringify(CLASS_TABLE)), caps: JSON.parse(JSON.stringify(CAPS)),
    budgets: JSON.parse(JSON.stringify(BUDGET)) });
  rpc.exports.mvruntimeprobe = function (options) {
    requireReady();
    options = options || {};
    return H.onMain(function () { return probe(options); });
  };
  rpc.exports.mvruntime = function (options) {
    requireReady();
    options = options || {};
    if (PARTS.indexOf(String(options.part || "frame")) < 0) throw new Error("MVDUMP_UNKNOWN_PART:" + options.part);
    return H.onMain(function () { return sample(options); });
  };
})();

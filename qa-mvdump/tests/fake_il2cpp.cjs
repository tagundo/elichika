'use strict';
/* Fake frida-il2cpp-bridge 0.9.1 surface + a 12035-shaped Unity scene, for offline tests of
 * the patched r8 observer + mv_runtime_dump.js extension (the bundle tail, without the real
 * bridge and dispatcher).
 *
 * - Objects live on a fake heap (DataView): header (class pointer, monitor), then fields at
 *   il2cpp-style offsets. UnityEngine.Object has m_CachedPtr @16 and m_InstanceID @24, so the
 *   extension's raw liveness / instance-id reads hit real bytes.
 * - Wrappers (Il2Cpp.Object/String/Array/ValueType and every pointer derived from them) carry
 *   the epoch of the main-thread callback that produced them. Each dispatched action runs in
 *   a new epoch; touching an older wrapper throws STALE_OBJECT (and is recorded), modelling
 *   "no Il2Cpp object survives a callback". Metadata (classes, methods, fields, System.Type
 *   objects) is permanent.
 * - Every invoke is logged. Anything that would throw a managed exception or write state is
 *   "fatal": denied names (set_*, get_material, Play, ...), any non-UnityEngine (game) method,
 *   a call on a destroyed object (m_CachedPtr == 0), a holder of the wrong class, GetChild /
 *   blend-shape index out of range, a material Get* without a prior HasProperty, a wrong
 *   overload (string decoys), any field write, or a Unity call outside a main callback.
 * - A fake clock (Date.now) advances by costPerCall per invoke, for budget tests.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const vm = require('vm');
const { spawnSync } = require('child_process');

const TE = { void: 1, boolean: 2, char: 3, byte: 4, unsignedByte: 5, short: 6, unsignedShort: 7, int: 8, unsignedInt: 9,
  long: 10, unsignedLong: 11, float: 12, double: 13, string: 14, pointer: 15, valueType: 17, class: 18,
  multidimensionalArray: 20, genericInstance: 21, nativePointer: 24, unsignedNativePointer: 25, object: 28, array: 29 };
const HEADER = 16;
const DENY = /^set_|^Set[A-Z]|^(Play|Pause|Stop|Resume|Evaluate|RebuildGraph|DeferredEvaluate|Simulate|Emit|Clear|Render|RenderWithShader|Destroy|DestroyImmediate|Instantiate|AddComponent|SendMessage|BroadcastMessage|Invoke|InvokeRepeating|StartCoroutine|GetParticles|GetPropertyBlock|BakeMesh|Update|LateUpdate)$|^get_(material|materials|mesh)$/;
const CAM1150 = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'cam1150.json'), 'utf8'));

// ------------------------------------------------------------------ math
function qmul(a, b) {
  const [ax, ay, az, aw] = a, [bx, by, bz, bw] = b;
  return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz];
}
function qrot(q, v) {
  const [x, y, z, w] = q;
  const m = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]];
  return [0, 1, 2].map(r => m[r][0] * v[0] + m[r][1] * v[1] + m[r][2] * v[2]);
}
function qmat(q) {
  const [x, y, z, w] = q;
  return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]];
}
// Unity worldToCameraMatrix = diag(1,1,-1,1) * inverse(TRS(position, rotation, 1)), column-major.
function worldToCamera(p, q) {
  const R = qmat(q), e = new Array(16).fill(0);
  for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) e[c * 4 + r] = R[c][r] * (r === 2 ? -1 : 1);
  for (let r = 0; r < 3; r++) e[12 + r] = -(R[0][r] * p[0] + R[1][r] * p[1] + R[2][r] * p[2]) * (r === 2 ? -1 : 1);
  e[15] = 1;
  return e;
}
function perspective(fov, aspect, near, far) {
  const f = 1 / Math.tan(fov * Math.PI / 360), e = new Array(16).fill(0);
  e[0] = f / aspect; e[5] = f; e[10] = (far + near) / (near - far); e[11] = -1; e[14] = 2 * far * near / (near - far);
  return e;
}

function createWorld(opts = {}) {
  const world = { epoch: 1, now: 1000000, costPerCall: opts.costPerCall || 0, invocations: [], fatal: [], stale: [], thenables: 0,
    frame: 4187, directorTime: opts.directorTime === undefined ? 11.5 : opts.directorTime, duration: 107.3, playState: 1,
    scene: 'LiveMv', deltaTime: 1 / 15, advance: opts.advance || 0, inCallback: false, callsPerAction: [], performs: [],
    poisonNext: false, throwNext: 0, dispatcherState: 'NEW', dispatches: 0, sent: [], findAllTypes: [] };
  const buffer = new ArrayBuffer(opts.heapBytes || (64 << 20)), view = new DataView(buffer);
  let brk = 0x10000, meta = 0x70000000, native = 0x50000000, nextId = -1000;
  function alloc(n) { const a = brk; brk += Math.max(16, (n + 15) & ~15); if (brk > buffer.byteLength) throw new Error('fake heap exhausted'); return a; }

  class FakePtr {
    constructor(addr, epoch) { this.addr = Number(addr) || 0; this.epoch = epoch === undefined ? null : epoch; }
    check() {
      if (this.epoch !== null && this.epoch !== world.epoch) {
        world.stale.push({ addr: this.addr, made: this.epoch, used: world.epoch });
        throw new Error('STALE_OBJECT: wrapper from callback ' + this.epoch + ' used in ' + world.epoch);
      }
      if (this.addr !== 0 && (this.addr < 0x10000 || this.addr >= brk)) throw new Error('fake: read outside heap at 0x' + this.addr.toString(16));
    }
    add(n) { return new FakePtr(this.addr + Number(n), this.epoch); }
    sub(n) { return new FakePtr(this.addr - Number(n), this.epoch); }
    isNull() { return this.addr === 0; }
    readFloat() { this.check(); return view.getFloat32(this.addr, true); }
    readDouble() { this.check(); return view.getFloat64(this.addr, true); }
    readS32() { this.check(); return view.getInt32(this.addr, true); }
    readU32() { this.check(); return view.getUint32(this.addr, true); }
    readS8() { this.check(); return view.getInt8(this.addr); }
    readU8() { this.check(); return view.getUint8(this.addr); }
    readPointer() { this.check(); return new FakePtr(Number(view.getBigUint64(this.addr, true)), this.epoch); }
    toString() { return '0x' + this.addr.toString(16); }
    equals(other) { return !!other && other.addr === this.addr; }
  }
  class NativeStruct {
    constructor(handle) { this.handle = handle instanceof FakePtr ? handle : new FakePtr(handle && handle.addr || 0, world.epoch); }
    isNull() { return this.handle.isNull(); }
  }
  const objs = new Map(), strings = new Map(), arrays = new Map(), classes = new Map(), unityObjects = [];
  class Obj extends NativeStruct {
    get class() { this.handle.check(); const o = objs.get(this.handle.addr); if (!o) throw new Error('fake: not an object'); return o.klass; }
    field(name) { return this.class.field(name).withHolder(this); }
    tryField(name) { const f = this.class.tryField(name); return f ? f.withHolder(this) : undefined; }
    method(name, argc = -1) { return this.class.method(name, argc).withHolder(this); }
    tryMethod(name, argc = -1) { const m = this.class.tryMethod(name, argc); return m ? m.withHolder(this) : undefined; }
  }
  class Str extends NativeStruct {
    get content() { this.handle.check(); return strings.has(this.handle.addr) ? strings.get(this.handle.addr) : null; }
    get length() { this.handle.check(); return (strings.get(this.handle.addr) || '').length; }
  }
  class Arr extends NativeStruct {
    get length() { this.handle.check(); return arrays.get(this.handle.addr).items.length; }
    get(i) {
      this.handle.check();
      const a = arrays.get(this.handle.addr);
      if (i < 0 || i >= a.items.length) throw new Error('cannot get element at index ' + i);
      return wrapValue(a.items[i], a.elementType, this.handle.epoch);
    }
  }
  class VT extends NativeStruct {
    constructor(handle, type) { super(handle); this.type = type; }
    field(name) { return this.type.klass.field(name).withHolder(this); }
    method(name, argc = -1) { return this.type.klass.method(name, argc).withHolder(this); }
  }
  class FakeType {
    constructor(name, typeEnum, klass) { this.name = name; this.typeEnum = typeEnum; this.klass = klass; this.obj = null; }
    get class() { return this.klass; }
    get object() {
      if (!this.obj) {
        const addr = alloc(32);
        objs.set(addr, { klass: classes.get('System.RuntimeType'), data: { forType: this } });
        this.obj = new Obj(new FakePtr(addr, null));
      }
      return this.obj;
    }
  }
  class FakeField {
    constructor(name, type, offset, isStatic, owner) { this.name = name; this.type = type; this.offset = offset; this.isStatic = isStatic; this.owner = owner; }
    get class() { return this.owner; }
    withHolder(holder) {
      const base = holder.handle.add(this.offset - (holder instanceof VT ? HEADER : 0)), type = this.type, name = this.name;
      return { name, type, offset: this.offset,
        get value() { return readTyped(base, type); },
        set value(v) { fatal('field write ' + name); } };
    }
  }
  class FakeMethod {
    constructor(owner, name, params, isStatic, impl) { this.owner = owner; this.name = name; this.params = params; this.isStatic = isStatic; this.impl = impl; }
    get class() { return this.owner; }
    get parameterCount() { return this.params.length; }
    get parameters() { return this.params.map(n => ({ type: { name: n } })); }
    tryOverload(...types) {
      let k = this.owner;
      while (k) {
        const m = k.ms.find(x => x.name === this.name && x.params.length === types.length && x.params.every((p, i) => p === types[i]));
        if (m) return m;
        k = k.parent;
      }
      return undefined;
    }
    overload(...types) { const m = this.tryOverload(...types); if (!m) throw new Error("couldn't find overloaded method " + this.name); return m; }
    invoke(...args) { if (!this.isStatic) throw new Error('cannot invoke non-static method ' + this.name + ' through a class'); return call(this, null, args); }
    withHolder(holder) {
      if (this.isStatic) throw new Error('cannot access static method ' + this.name + ' from an object');
      const self = this;
      return { name: self.name, class: self.owner, isStatic: false, invoke: (...args) => call(self, holder, args),
        overload: (...t) => self.overload(...t).withHolder(holder), tryOverload: (...t) => { const m = self.tryOverload(...t); return m && m.withHolder(holder); } };
    }
  }
  class FakeClass {
    constructor(fullName, parent, o = {}) {
      const dot = fullName.lastIndexOf('.');
      this.fullName = fullName; this.namespace = dot >= 0 ? fullName.slice(0, dot) : ''; this.name = dot >= 0 ? fullName.slice(dot + 1) : fullName;
      this.parent = parent || null; this.own = []; this.ms = []; this.isValueType = !!o.valueType; this.isEnum = !!o.enum;
      this.handle = new FakePtr((meta += 0x100), null);
      this.assemblyName = this.namespace.startsWith('UnityEngine') ? 'UnityEngine.CoreModule' : this.namespace.startsWith('LLAS') ? 'Assembly-CSharp' : 'mscorlib';
      this.instanceSize = parent && !this.isValueType ? parent.instanceSize : HEADER;
      this.vsize = 0;
      this.type = new FakeType(o.typeName || fullName, o.typeEnum || (this.isValueType ? TE.valueType : TE.class), this);
      classes.set(fullName, this);
    }
    get fields() { return this.own.slice(); }
    get methods() { return this.ms.slice(); }
    get valueTypeSize() { return this.vsize; }
    addField(name, type) {
      const size = sizeOf(type), align = Math.min(8, size);
      let offset;
      if (this.isValueType) { offset = HEADER + ((this.vsize + align - 1) & ~(align - 1)); this.vsize = offset - HEADER + size; }
      else { offset = (this.instanceSize + align - 1) & ~(align - 1); this.instanceSize = offset + size; }
      this.own.push(new FakeField(name, type, offset, false, this));
      return this;
    }
    addMethod(name, params, isStatic, impl) { this.ms.push(new FakeMethod(this, name, params, isStatic, impl)); return this; }
    tryField(name) { let k = this; while (k) { const f = k.own.find(x => x.name === name); if (f) return f; k = k.parent; } return null; }
    field(name) { const f = this.tryField(name); if (!f) throw new Error("couldn't find field " + name + ' in class ' + this.fullName); return f; }
    tryMethod(name, argc = -1) { let k = this; while (k) { const m = k.ms.find(x => x.name === name && (argc < 0 || x.params.length === argc)); if (m) return m; k = k.parent; } return null; }
    method(name, argc = -1) { const m = this.tryMethod(name, argc); if (!m) throw new Error("couldn't find method " + name + ' in class ' + this.fullName); return m; }
    isSubclassOf(other) { let k = this; while (k) { if (k === other) return true; k = k.parent; } return false; }
  }
  function sizeOf(type) {
    switch (type.typeEnum) {
      case TE.boolean: case TE.byte: case TE.unsignedByte: return 1;
      case TE.short: case TE.unsignedShort: case TE.char: return 2;
      case TE.int: case TE.unsignedInt: case TE.float: return 4;
      case TE.valueType: return type.klass.isEnum ? 4 : type.klass.vsize;
      case TE.genericInstance: return type.klass.isValueType ? type.klass.vsize : 8;
      default: return 8;
    }
  }
  function fatal(message) { world.fatal.push(message); throw new Error('FATAL_MANAGED_EXCEPTION: ' + message); }
  function wrapValue(raw, type, epoch) {
    const e = epoch === undefined ? world.epoch : epoch;
    switch (type.typeEnum) {
      case TE.string: return new Str(new FakePtr(raw, e));
      case TE.array: return new Arr(new FakePtr(raw, e));
      case TE.valueType: return new VT(new FakePtr(raw, e), type);
      case TE.class: case TE.object: case TE.genericInstance: return new Obj(new FakePtr(raw, e));
      default: return raw;
    }
  }
  function readTyped(ptr, type) {
    switch (type.typeEnum) {
      case TE.boolean: return !!ptr.readS8();
      case TE.int: return ptr.readS32();
      case TE.unsignedInt: return ptr.readU32();
      case TE.float: return ptr.readFloat();
      case TE.double: return ptr.readDouble();
      case TE.unsignedByte: return ptr.readU8();
      case TE.nativePointer: return ptr.readPointer();
      case TE.valueType: return new VT(ptr, type);
      case TE.object: case TE.class: return new Obj(ptr.readPointer());
      case TE.genericInstance: return type.klass.isValueType ? new VT(ptr, type) : new Obj(ptr.readPointer());
      case TE.string: return new Str(ptr.readPointer());
      case TE.array: return new Arr(ptr.readPointer());
      default: throw new Error('fake: unhandled type ' + type.name);
    }
  }
  function writeTyped(addr, type, value) {
    switch (type.typeEnum) {
      case TE.boolean: view.setInt8(addr, value ? 1 : 0); return;
      case TE.int: view.setInt32(addr, value | 0, true); return;
      case TE.unsignedInt: view.setUint32(addr, value >>> 0, true); return;
      case TE.float: view.setFloat32(addr, value, true); return;
      case TE.double: view.setFloat64(addr, value, true); return;
      case TE.nativePointer: case TE.object: case TE.class: case TE.string: case TE.array:
        view.setBigUint64(addr, BigInt(value || 0), true); return;
      case TE.genericInstance:
        if (!type.klass.isValueType) { view.setBigUint64(addr, BigInt(value || 0), true); return; }
      // fallthrough
      case TE.valueType: {
        const k = type.klass;
        if (k.isEnum) { view.setInt32(addr, value | 0, true); return; }
        k.own.forEach((f, i) => writeTyped(addr + f.offset - HEADER, f.type, Array.isArray(value) ? value[i] : value[f.name]));
        return;
      }
      default: throw new Error('fake: cannot write ' + type.name);
    }
  }
  const T = {};
  function prim(name, te) { const k = new FakeClass(name, null, { valueType: te !== TE.string && te !== TE.object, typeEnum: te }); T[name] = k.type; return k.type; }
  prim('System.Boolean', TE.boolean); prim('System.Int32', TE.int); prim('System.UInt32', TE.unsignedInt); prim('System.Single', TE.float);
  prim('System.Double', TE.double); prim('System.Byte', TE.unsignedByte); prim('System.IntPtr', TE.nativePointer);
  prim('System.String', TE.string); prim('System.Object', TE.object);
  new FakeClass('System.RuntimeType', classes.get('System.Object'));
  const arrayTypes = {};
  function arrayOf(type) {
    if (!arrayTypes[type.name]) {
      const k = new FakeClass(type.name + '[]', classes.get('System.Object'), { typeEnum: TE.array });
      k.elementType = type;
      arrayTypes[type.name] = k.type;
    }
    return arrayTypes[type.name];
  }
  function struct(name, fields) { const k = new FakeClass(name, null, { valueType: true }); fields.forEach(([n, t]) => k.addField(n, t)); T[name] = k.type; return k; }
  function enumType(name) { const k = new FakeClass(name, null, { valueType: true, enum: true }); k.addField('value__', T['System.Int32']); T[name] = k.type; return k.type; }
  const F = T['System.Single'], I = T['System.Int32'], B = T['System.Boolean'], S = T['System.String'];
  struct('UnityEngine.Vector2', [['x', F], ['y', F]]);
  struct('UnityEngine.Vector3', [['x', F], ['y', F], ['z', F]]);
  struct('UnityEngine.Vector4', [['x', F], ['y', F], ['z', F], ['w', F]]);
  struct('UnityEngine.Quaternion', [['x', F], ['y', F], ['z', F], ['w', F]]);
  struct('UnityEngine.Color', [['r', F], ['g', F], ['b', F], ['a', F]]);
  struct('UnityEngine.Rect', [['m_XMin', F], ['m_YMin', F], ['m_Width', F], ['m_Height', F]]);
  struct('UnityEngine.Bounds', [['m_Center', T['UnityEngine.Vector3']], ['m_Extents', T['UnityEngine.Vector3']]]);
  const MATRIX = []; for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) MATRIX.push(['m' + r + c, F]);
  struct('UnityEngine.Matrix4x4', MATRIX);
  struct('UnityEngine.SceneManagement.Scene', [['m_Handle', I]]);
  struct('System.Nullable`1<System.Int32>', [['has_value', B], ['value', I]]);
  const E = {};
  ['UnityEngine.Playables.PlayState', 'UnityEngine.Playables.DirectorUpdateMode', 'UnityEngine.Playables.DirectorWrapMode',
    'UnityEngine.CameraClearFlags', 'UnityEngine.DepthTextureMode', 'UnityEngine.ScreenOrientation', 'UnityEngine.LightType',
    'UnityEngine.LightShadows', 'UnityEngine.FogMode', 'UnityEngine.Rendering.AmbientMode', 'UnityEngine.ColorSpace',
    'UnityEngine.RenderTextureFormat', 'LLAS.Scene.Live.Components.CorrectionMode', 'LLAS.DM.LiveQuality'].forEach(n => { E[n] = enumType(n); });

  function newStruct(typeName, values) {
    const type = T[typeName], addr = alloc(type.klass.vsize || 4);
    writeTyped(addr, type, values);
    return new VT(new FakePtr(addr, world.epoch), type);
  }
  function newEnum(typeName, v) { const type = E[typeName], addr = alloc(4); view.setInt32(addr, v, true); return new VT(new FakePtr(addr, world.epoch), type); }
  function newString(s) { const addr = alloc(24); objs.set(addr, { klass: classes.get('System.String'), data: {} }); strings.set(addr, String(s)); return addr; }
  function newArray(elementType, items) {
    const addr = alloc(32);
    objs.set(addr, { klass: arrayOf(elementType).klass, data: {} });
    arrays.set(addr, { elementType, items: items.slice() });
    return addr;
  }
  function retObj(addr) { return new Obj(new FakePtr(addr || 0, world.epoch)); }
  function retStr(s) { return s === null || s === undefined ? new Str(new FakePtr(0, world.epoch)) : new Str(new FakePtr(newString(s), world.epoch)); }
  function retArr(elementType, items) { return new Arr(new FakePtr(newArray(elementType, items), world.epoch)); }

  // ------------------------------------------------------------------ class hierarchy
  const C = {};
  function cls(name, parent, fields, o) { const k = new FakeClass(name, parent ? C[parent] || classes.get(parent) : classes.get('System.Object'), o); (fields || []).forEach(([n, t]) => k.addField(n, t)); C[name] = k; return k; }
  cls('UnityEngine.Object', null, [['m_CachedPtr', T['System.IntPtr']], ['m_InstanceID', I]]);
  cls('UnityEngine.Component', 'UnityEngine.Object');
  cls('UnityEngine.Behaviour', 'UnityEngine.Component');
  cls('UnityEngine.MonoBehaviour', 'UnityEngine.Behaviour');
  cls('UnityEngine.GameObject', 'UnityEngine.Object');
  cls('UnityEngine.Transform', 'UnityEngine.Component');
  cls('UnityEngine.RectTransform', 'UnityEngine.Transform');
  cls('UnityEngine.Camera', 'UnityEngine.Behaviour');
  cls('UnityEngine.Light', 'UnityEngine.Behaviour');
  cls('UnityEngine.Renderer', 'UnityEngine.Component');
  cls('UnityEngine.MeshRenderer', 'UnityEngine.Renderer');
  cls('UnityEngine.SkinnedMeshRenderer', 'UnityEngine.Renderer');
  cls('UnityEngine.ParticleSystemRenderer', 'UnityEngine.Renderer');
  cls('UnityEngine.MeshFilter', 'UnityEngine.Component');
  cls('UnityEngine.ParticleSystem', 'UnityEngine.Component');
  cls('UnityEngine.Mesh', 'UnityEngine.Object');
  cls('UnityEngine.Material', 'UnityEngine.Object');
  cls('UnityEngine.Shader', 'UnityEngine.Object');
  cls('UnityEngine.Texture', 'UnityEngine.Object');
  cls('UnityEngine.Texture2D', 'UnityEngine.Texture');
  cls('UnityEngine.RenderTexture', 'UnityEngine.Texture');
  cls('UnityEngine.ScriptableObject', 'UnityEngine.Object');
  cls('UnityEngine.Playables.PlayableAsset', 'UnityEngine.ScriptableObject');
  cls('UnityEngine.Playables.PlayableDirector', 'UnityEngine.Behaviour');
  ['UnityEngine.Resources', 'UnityEngine.Time', 'UnityEngine.Screen', 'UnityEngine.SceneManagement.SceneManager', 'UnityEngine.RenderSettings',
    'UnityEngine.QualitySettings', 'UnityEngine.Application', 'UnityEngine.RectTransformUtility', 'UnityEngine.Canvas'].forEach(n => cls(n, null));
  const MB = 'UnityEngine.MonoBehaviour';
  cls('System.Collections.Generic.List`1', null, [['_items', arrayOf(F)], ['_size', I]]);
  C['System.Collections.Generic.List`1'].namespace = 'System.Collections.Generic'; C['System.Collections.Generic.List`1'].name = 'List`1';
  cls('LLAS.Scene.Live.Components.LiveMusicMachine', null, [['musicPlayingTime', F], ['<IsPlayingMusic>k__BackingField', B], ['<MusicLength>k__BackingField', F]]);
  cls('LLAS.DM.ValueObject.Live3DMemberVO', null, [['<MemberMasterId>k__BackingField', I], ['<FormationPosition>k__BackingField', I], ['<SuitId>k__BackingField', T['System.Nullable`1<System.Int32>']]]);
  cls('LLAS.DM.ValueObject.Live3DAssetVO', null, [['<Members>k__BackingField', arrayOf(C['LLAS.DM.ValueObject.Live3DMemberVO'].type)]]);
  cls('LLAS.DM.ValueObject.LiveQualitySettingVO', null, [['<PostEffect>k__BackingField', B], ['<RenderingResolution>k__BackingField', I],
    ['<Quality>k__BackingField', E['LLAS.DM.LiveQuality']], ['<FrameRate60Fps>k__BackingField', B], ['<MemberSwingBone>k__BackingField', B]]);
  cls('LLAS.Scene.Live.LiveDirectorBase', MB);
  cls('LLAS.Scene.Live.LiveDirector', 'LLAS.Scene.Live.LiveDirectorBase', [['<TimelineDirector>k__BackingField', C['UnityEngine.Playables.PlayableDirector'].type],
    ['asset', C['LLAS.DM.ValueObject.Live3DAssetVO'].type], ['<MusicMachine>k__BackingField', C['LLAS.Scene.Live.Components.LiveMusicMachine'].type],
    ['liveQualitySetting', C['LLAS.DM.ValueObject.LiveQualitySettingVO'].type]]);
  C['LLAS.Scene.Live.LiveDirector'].addMethod('get_TimelineDirector', [], false, () => fatal('game getter LiveDirector.get_TimelineDirector invoked'));
  const LC = 'LLAS.Scene.Live.Components.';
  cls(LC + 'CameraCurve', null, [['speed', F], ['label', S]]);
  cls(LC + 'LiveCoreCameraManager', MB, [['overlayCamera', C['UnityEngine.Camera'].type], ['cutinCamera', C['UnityEngine.Camera'].type]]);
  cls(LC + 'LiveCoreCameraWork', MB, [['fieldOfView', F], ['offsetScale', F], ['targetName', S], ['secretToken', S], ['curve', C[LC + 'CameraCurve'].type],
    ['weights', C['System.Collections.Generic.List`1'].type], ['enabledMask', B]]);
  C[LC + 'LiveCoreCameraWork'].addMethod('get_FieldOfView', [], false, () => fatal('game getter LiveCoreCameraWork.get_FieldOfView invoked'));
  cls(LC + 'CameraAspectCorrector', MB, [['mode', E['LLAS.Scene.Live.Components.CorrectionMode']], ['<Correction>k__BackingField', F],
    ['defaultOrthographicSize', F], ['target', C['UnityEngine.Camera'].type], ['targetAspect', F]]);
  cls(LC + 'LiveCoreCamera', MB, [['enablePostEffect', B], ['postProcess', classes.get('System.Object').type]]);
  cls(LC + 'MemberInfo', null, [['<FormationPosition>k__BackingField', I]]);
  cls(LC + 'LiveCoreMember', MB, [['memberInfo', C[LC + 'MemberInfo'].type]]);
  cls(LC + 'LiveCoreMemberAmbient', MB, [['materials', arrayOf(C['UnityEngine.Material'].type)], ['color', T['UnityEngine.Color']]]);
  cls('LLAS.Components.Members.BodyPartManager', MB, [['head', C['UnityEngine.Transform'].type], ['hips', C['UnityEngine.Transform'].type], ['neck', C['UnityEngine.Transform'].type]]);
  cls('LLAS.Components.Members.SwingBone', MB, [['currentTipPosition', T['UnityEngine.Vector3']], ['previousTipPosition', T['UnityEngine.Vector3']], ['length', F]]);
  cls('LLAS.Components.Members.SwingBoneManager', MB, [['swingBones', arrayOf(C['LLAS.Components.Members.SwingBone'].type)], ['gravity', F]]);

  // ------------------------------------------------------------------ objects and scene
  let nativeCounter = 0;
  function newUnity(klass, data) {
    const addr = alloc(klass.instanceSize), id = (nextId -= 2);
    view.setBigUint64(addr, BigInt(klass.handle.addr), true);
    view.setBigUint64(addr + 16, BigInt(native + (++nativeCounter) * 16), true);
    view.setInt32(addr + 24, id, true);
    objs.set(addr, { klass, data: data || {}, id });
    unityObjects.push(addr);
    return addr;
  }
  function newManaged(klass, values) {
    const addr = alloc(klass.instanceSize);
    view.setBigUint64(addr, BigInt(klass.handle.addr), true);
    objs.set(addr, { klass, data: {} });
    Object.keys(values || {}).forEach(k => set(addr, k, values[k]));
    return addr;
  }
  function set(addr, name, value) { const f = objs.get(addr).klass.field(name); writeTyped(addr + f.offset, f.type, value); }
  function destroy(addr) { view.setBigUint64(addr + 16, 0n, true); }
  function data(addr) { return objs.get(addr).data; }
  function gameObject(name, parentTr, o = {}) {
    const go = newUnity(C['UnityEngine.GameObject'], { name, active: o.active !== false, components: [], layer: o.layer || 0 });
    const tr = newUnity(C['UnityEngine.Transform'], { go, parent: parentTr || 0, children: [], lp: o.lp || [0, 0, 0], lr: o.lr || [0, 0, 0, 1], ls: o.ls || [1, 1, 1] });
    data(go).transform = tr; data(go).components.push(tr);
    if (parentTr) data(parentTr).children.push(tr);
    return { go, tr };
  }
  function component(owner, klassName, d, values) {
    const addr = newUnity(C[klassName], Object.assign({ go: owner.go, enabled: true }, d || {}));
    data(owner.go).components.push(addr);
    Object.keys(values || {}).forEach(k => set(addr, k, values[k]));
    return addr;
  }
  function goOf(addr) { const d = data(addr); return objs.get(addr).klass === C['UnityEngine.GameObject'] ? addr : d.go; }
  function trOf(addr) { return data(goOf(addr)).transform; }
  function activeInHierarchy(go) { let tr = data(go).transform; while (tr) { if (!data(data(tr).go).active) return false; tr = data(tr).parent; } return true; }
  function world_(tr) {
    const d = data(tr);
    if (!d.parent) return { p: d.lp.slice(), q: d.lr.slice(), s: d.ls.slice() };
    const w = world_(d.parent), sl = d.lp.map((v, i) => v * w.s[i]);
    const r = qrot(w.q, sl);
    return { p: [w.p[0] + r[0], w.p[1] + r[1], w.p[2] + r[2]], q: qmul(w.q, d.lr), s: d.ls.map((v, i) => v * w.s[i]) };
  }
  function nameOfObj(addr) { const d = data(addr); return d.name !== undefined ? d.name : data(goOf(addr)).name; }
  function find(path) {
    const parts = path.replace(/^\//, '').split('/');
    const roots = unityObjects.filter(a => objs.get(a).klass === C['UnityEngine.GameObject'] && !data(data(a).transform).parent && data(a).name === parts[0] && activeInHierarchy(a));
    if (!roots.length) return 0;
    let tr = data(roots[0]).transform;
    for (const part of parts.slice(1)) {
      tr = data(tr).children.find(c => data(data(c).go).name === part);
      if (!tr || !activeInHierarchy(data(tr).go)) return 0;
    }
    return data(tr).go;
  }
  function findRelative(tr, rel) {
    for (const part of rel.split('/').filter(Boolean)) { tr = data(tr).children.find(c => data(data(c).go).name === part); if (!tr) return 0; }
    return tr;
  }

  // ------------------------------------------------------------------ methods
  function M(klass, name, params, isStatic, impl) { C[klass].addMethod(name, params, isStatic, impl); }
  const V3 = (v) => newStruct('UnityEngine.Vector3', v), V4 = (v) => newStruct('UnityEngine.Vector4', v), Q = (v) => newStruct('UnityEngine.Quaternion', v);
  const COL = (v) => newStruct('UnityEngine.Color', v), V2 = (v) => newStruct('UnityEngine.Vector2', v);
  M('UnityEngine.Object', 'GetInstanceID', [], false, (o) => o.id);
  M('UnityEngine.Object', 'get_name', [], false, (o, a, h) => retStr(nameOfObj(h.handle.addr)));
  M('UnityEngine.Object', 'set_name', ['System.String'], false, () => fatal('set_name'));
  M('UnityEngine.Object', 'FindObjectsOfType', ['System.Type'], true, (o, a) => findAll(a[0], false));
  function findAll(typeObj, includeAll) {
    const t = objs.get(typeObj.handle.addr).data.forType.klass;
    world.findAllTypes.push(t.fullName);
    return retArr(t.type, unityObjects.filter(addr => objs.get(addr).klass.isSubclassOf(t)));
  }
  M('UnityEngine.Resources', 'FindObjectsOfTypeAll', ['System.Type'], true, (o, a) => findAll(a[0], true));
  M('UnityEngine.Component', 'get_gameObject', [], false, (o) => retObj(o.data.go));
  M('UnityEngine.Component', 'get_transform', [], false, (o) => retObj(data(o.data.go).transform));
  M('UnityEngine.Component', 'GetComponent', ['System.String'], false, () => fatal('wrong overload GetComponent(string)'));
  M('UnityEngine.Component', 'GetComponent', ['System.Type'], false, (o, a) => {
    const t = objs.get(a[0].handle.addr).data.forType.klass;
    return retObj(data(o.data.go).components.find(c => objs.get(c).klass.isSubclassOf(t)) || 0);
  });
  M('UnityEngine.Component', 'GetComponents', ['System.Type'], false, (o, a) => {
    const t = objs.get(a[0].handle.addr).data.forType.klass;
    return retArr(t.type, data(o.data.go).components.filter(c => objs.get(c).klass.isSubclassOf(t)));
  });
  M('UnityEngine.GameObject', 'Find', ['System.String'], true, (o, a) => retObj(find(a[0].content)));
  M('UnityEngine.GameObject', 'get_activeSelf', [], false, (o) => o.data.active);
  M('UnityEngine.GameObject', 'get_activeInHierarchy', [], false, (o, a, h) => activeInHierarchy(h.handle.addr));
  M('UnityEngine.GameObject', 'get_transform', [], false, (o) => retObj(o.data.transform));
  M('UnityEngine.GameObject', 'get_layer', [], false, (o) => o.data.layer || 0);
  M('UnityEngine.GameObject', 'set_layer', ['System.Int32'], false, () => fatal('set_layer'));
  M('UnityEngine.GameObject', 'SetActive', ['System.Boolean'], false, () => fatal('SetActive'));
  M('UnityEngine.Behaviour', 'get_enabled', [], false, (o) => o.data.enabled !== false);
  M('UnityEngine.Behaviour', 'get_isActiveAndEnabled', [], false, (o) => o.data.enabled !== false && activeInHierarchy(o.data.go));
  M('UnityEngine.Behaviour', 'set_enabled', ['System.Boolean'], false, () => fatal('set_enabled'));
  const TR = 'UnityEngine.Transform';
  M(TR, 'get_position', [], false, (o, a, h) => V3(world_(h.handle.addr).p));
  M(TR, 'get_rotation', [], false, (o, a, h) => Q(world_(h.handle.addr).q));
  M(TR, 'get_lossyScale', [], false, (o, a, h) => V3(world_(h.handle.addr).s));
  M(TR, 'get_localPosition', [], false, (o) => V3(o.data.lp));
  M(TR, 'get_localRotation', [], false, (o) => Q(o.data.lr));
  M(TR, 'get_localScale', [], false, (o) => V3(o.data.ls));
  M(TR, 'get_parent', [], false, (o) => retObj(o.data.parent));
  M(TR, 'get_childCount', [], false, (o) => o.data.children.length);
  M(TR, 'GetChild', ['System.Int32'], false, (o, a) => { if (a[0] < 0 || a[0] >= o.data.children.length) fatal('GetChild out of bounds'); return retObj(o.data.children[a[0]]); });
  M(TR, 'Find', ['System.String'], false, (o, a, h) => retObj(findRelative(h.handle.addr, a[0].content)));
  M(TR, 'GetSiblingIndex', [], false, (o, a, h) => o.data.parent ? data(o.data.parent).children.indexOf(h.handle.addr) : 0);
  M(TR, 'set_position', ['UnityEngine.Vector3'], false, () => fatal('set_position'));
  const CAM = 'UnityEngine.Camera';
  const camW = (h) => { const w = world_(trOf(h.handle.addr)); return w; };
  M(CAM, 'get_fieldOfView', [], false, (o) => o.data.fov);
  M(CAM, 'get_aspect', [], false, (o) => o.data.aspect);
  M(CAM, 'get_nearClipPlane', [], false, (o) => o.data.near);
  M(CAM, 'get_farClipPlane', [], false, (o) => o.data.far);
  M(CAM, 'get_orthographic', [], false, (o) => !!o.data.ortho);
  M(CAM, 'get_orthographicSize', [], false, () => 5);
  M(CAM, 'get_usePhysicalProperties', [], false, () => false);
  M(CAM, 'get_focalLength', [], false, () => 50);
  M(CAM, 'get_lensShift', [], false, () => V2([0, 0]));
  M(CAM, 'get_projectionMatrix', [], false, (o) => newStruct('UnityEngine.Matrix4x4', perspective(o.data.fov, o.data.aspect, o.data.near, o.data.far)));
  M(CAM, 'get_worldToCameraMatrix', [], false, (o, a, h) => { const w = camW(h); return newStruct('UnityEngine.Matrix4x4', worldToCamera(w.p, w.q)); });
  M(CAM, 'get_rect', [], false, () => newStruct('UnityEngine.Rect', [0, 0, 1, 1]));
  M(CAM, 'get_pixelRect', [], false, () => newStruct('UnityEngine.Rect', [0, 0, 1280, 720]));
  M(CAM, 'get_pixelWidth', [], false, () => 1280);
  M(CAM, 'get_pixelHeight', [], false, () => 720);
  M(CAM, 'get_depth', [], false, (o) => o.data.depth || 0);
  M(CAM, 'get_clearFlags', [], false, () => newEnum('UnityEngine.CameraClearFlags', 2));
  M(CAM, 'get_backgroundColor', [], false, () => COL([0, 0, 0, 0]));
  M(CAM, 'get_cullingMask', [], false, () => -1);
  M(CAM, 'get_allowHDR', [], false, () => false);
  M(CAM, 'get_allowMSAA', [], false, () => false);
  M(CAM, 'get_depthTextureMode', [], false, () => newEnum('UnityEngine.DepthTextureMode', 0));
  M(CAM, 'get_targetTexture', [], false, (o) => retObj(o.data.target || 0));
  M(CAM, 'set_fieldOfView', ['System.Single'], false, () => fatal('set_fieldOfView'));
  M(CAM, 'Render', [], false, () => fatal('Render'));
  const REN = 'UnityEngine.Renderer';
  M(REN, 'get_enabled', [], false, (o) => o.data.enabled !== false);
  M(REN, 'get_isVisible', [], false, () => true);
  M(REN, 'get_bounds', [], false, (o, a, h) => { const w = world_(trOf(h.handle.addr)); return newStruct('UnityEngine.Bounds', [w.p, [0.5, 0.9, 0.3]]); });
  M(REN, 'get_sharedMaterials', [], false, (o) => retArr(C['UnityEngine.Material'].type, o.data.materials || []));
  M(REN, 'get_material', [], false, () => fatal('get_material instantiates a material'));
  M(REN, 'get_materials', [], false, () => fatal('get_materials instantiates materials'));
  M(REN, 'get_lightmapIndex', [], false, () => -1);
  M(REN, 'get_lightmapScaleOffset', [], false, () => V4([1, 1, 0, 0]));
  M(REN, 'get_sortingOrder', [], false, () => 0);
  M('UnityEngine.SkinnedMeshRenderer', 'get_sharedMesh', [], false, (o) => retObj(o.data.mesh || 0));
  M('UnityEngine.SkinnedMeshRenderer', 'GetBlendShapeWeight', ['System.Int32'], false, (o, a) => {
    const shapes = data(o.data.mesh).shapes;
    if (a[0] < 0 || a[0] >= shapes.length) fatal('GetBlendShapeWeight out of range');
    return (o.data.weights || [])[a[0]] || 0;
  });
  M('UnityEngine.MeshFilter', 'get_sharedMesh', [], false, (o) => retObj(o.data.mesh || 0));
  M('UnityEngine.MeshFilter', 'get_mesh', [], false, () => fatal('get_mesh instantiates a mesh'));
  M('UnityEngine.Mesh', 'get_blendShapeCount', [], false, (o) => (o.data.shapes || []).length);
  M('UnityEngine.Mesh', 'GetBlendShapeName', ['System.Int32'], false, (o, a) => { if (a[0] < 0 || a[0] >= o.data.shapes.length) fatal('GetBlendShapeName out of range'); return retStr(o.data.shapes[a[0]]); });
  const MAT = 'UnityEngine.Material', propertyNames = {}, propertyIdsByName = {};
  let nextProperty = 100;
  const PROP = (name) => { if (!propertyIdsByName[name]) { propertyIdsByName[name] = ++nextProperty; propertyNames[nextProperty] = name; } return propertyIdsByName[name]; };
  const checked = new Set();
  function prop(o, h, id, kind) {
    if (!checked.has(h.handle.addr + ':' + id)) fatal('Material.' + kind + ' without HasProperty');
    return o.data.props[propertyNames[id]];
  }
  M(MAT, 'get_shader', [], false, (o) => retObj(o.data.shader));
  M(MAT, 'get_renderQueue', [], false, () => 2000);
  M(MAT, 'get_shaderKeywords', [], false, (o) => retArr(S, (o.data.keywords || []).map(newString)));
  M(MAT, 'HasProperty', ['System.String'], false, () => fatal('wrong overload HasProperty(string)'));
  M(MAT, 'HasProperty', ['System.Int32'], false, (o, a, h) => { const has = propertyNames[a[0]] in o.data.props; if (has) checked.add(h.handle.addr + ':' + a[0]); return has; });
  M(MAT, 'GetFloat', ['System.String'], false, () => fatal('wrong overload GetFloat(string)'));
  M(MAT, 'GetFloat', ['System.Int32'], false, (o, a, h) => prop(o, h, a[0], 'GetFloat'));
  M(MAT, 'GetColor', ['System.Int32'], false, (o, a, h) => COL(prop(o, h, a[0], 'GetColor')));
  M(MAT, 'GetVector', ['System.Int32'], false, (o, a, h) => V4(prop(o, h, a[0], 'GetVector')));
  M(MAT, 'GetTexture', ['System.Int32'], false, (o, a, h) => retObj(prop(o, h, a[0], 'GetTexture')));
  M(MAT, 'GetTextureScale', ['System.Int32'], false, (o, a, h) => { prop(o, h, a[0], 'GetTextureScale'); return V2([1, 1]); });
  M(MAT, 'GetTextureOffset', ['System.Int32'], false, (o, a, h) => { prop(o, h, a[0], 'GetTextureOffset'); return V2([0, 0]); });
  M(MAT, 'SetFloat', ['System.Int32', 'System.Single'], false, () => fatal('SetFloat'));
  const globals = Object.assign({ _Beat: [0.25, 0, 0, 0], _MusicTime: [11.48, 0, 0, 0], _SelfTime: [0, 0, 0, 0], _ColorsLength: [3, 0, 0, 0],
    _RenderTextureResolution: [1280, 720, 0, 0], _Time: [14.55, 291.07, 582.13, 873.2] }, opts.globals || {});
  M('UnityEngine.Shader', 'PropertyToID', ['System.String'], true, (o, a) => PROP(a[0].content));
  M('UnityEngine.Shader', 'GetGlobalFloat', ['System.String'], true, () => fatal('wrong overload GetGlobalFloat(string)'));
  M('UnityEngine.Shader', 'GetGlobalFloat', ['System.Int32'], true, (o, a) => (globals[propertyNames[a[0]]] || [0])[0]);
  M('UnityEngine.Shader', 'GetGlobalVector', ['System.Int32'], true, (o, a) => V4(globals[propertyNames[a[0]]] || [0, 0, 0, 0]));
  M('UnityEngine.Shader', 'GetGlobalVectorArray', ['System.Int32'], true, () => retArr(T['UnityEngine.Vector4'], [0, 1, 2].map(i => { const v = newStruct('UnityEngine.Vector4', [i, i, i, 1]); return v.handle.addr; })));
  M('UnityEngine.Texture', 'get_width', [], false, (o) => o.data.width);
  M('UnityEngine.Texture', 'get_height', [], false, (o) => o.data.height);
  M('UnityEngine.RenderTexture', 'get_format', [], false, () => newEnum('UnityEngine.RenderTextureFormat', 0));
  const PD = 'UnityEngine.Playables.PlayableDirector';
  M(PD, 'get_time', [], false, (o) => o.data.main ? world.directorTime : 0);
  M(PD, 'get_duration', [], false, (o) => o.data.main ? world.duration : 2);
  M(PD, 'get_state', [], false, (o) => newEnum('UnityEngine.Playables.PlayState', o.data.main ? world.playState : 0));
  M(PD, 'get_timeUpdateMode', [], false, () => newEnum('UnityEngine.Playables.DirectorUpdateMode', 1));
  M(PD, 'get_extrapolationMode', [], false, () => newEnum('UnityEngine.Playables.DirectorWrapMode', 2));
  M(PD, 'get_playableAsset', [], false, (o) => retObj(o.data.asset || 0));
  M(PD, 'Evaluate', [], false, () => fatal('Evaluate'));
  M(PD, 'Play', [], false, () => fatal('Play'));
  const LT = 'UnityEngine.Light';
  M(LT, 'get_type', [], false, () => newEnum('UnityEngine.LightType', 1));
  M(LT, 'get_color', [], false, () => COL([1, 1, 1, 1]));
  M(LT, 'get_intensity', [], false, () => 0);
  M(LT, 'get_range', [], false, () => 10);
  M(LT, 'get_spotAngle', [], false, () => 30);
  M(LT, 'get_shadows', [], false, () => newEnum('UnityEngine.LightShadows', 0));
  M(LT, 'get_cullingMask', [], false, () => -1);
  const PS = 'UnityEngine.ParticleSystem';
  M(PS, 'get_isPlaying', [], false, () => true);
  M(PS, 'get_isEmitting', [], false, () => true);
  M(PS, 'get_isPaused', [], false, () => false);
  M(PS, 'get_particleCount', [], false, () => 37);
  M(PS, 'get_time', [], false, () => 1.13);
  M(PS, 'get_randomSeed', [], false, () => 7548);
  M(PS, 'get_useAutoRandomSeed', [], false, () => false);
  M(PS, 'Play', [], false, () => fatal('ParticleSystem.Play'));
  M(PS, 'GetParticles', ['UnityEngine.ParticleSystem+Particle[]'], false, () => fatal('GetParticles'));
  M('UnityEngine.Time', 'get_frameCount', [], true, () => world.frame);
  M('UnityEngine.Time', 'get_time', [], true, () => 291.06665 + (world.frame - 4187) / 15);
  M('UnityEngine.Time', 'get_unscaledTime', [], true, () => 291.06665 + (world.frame - 4187) / 15);
  M('UnityEngine.Time', 'get_deltaTime', [], true, () => world.deltaTime);
  M('UnityEngine.Time', 'get_timeScale', [], true, () => 1);
  M('UnityEngine.Time', 'get_realtimeSinceStartup', [], true, () => 1402.3311 + (world.now - 1000000) / 1000);
  M('UnityEngine.Screen', 'get_width', [], true, () => 1280);
  M('UnityEngine.Screen', 'get_height', [], true, () => 720);
  M('UnityEngine.Screen', 'get_orientation', [], true, () => newEnum('UnityEngine.ScreenOrientation', 3));
  M('UnityEngine.SceneManagement.SceneManager', 'GetActiveScene', [], true, () => newStruct('UnityEngine.SceneManagement.Scene', [1]));
  C['UnityEngine.SceneManagement.Scene'] = classes.get('UnityEngine.SceneManagement.Scene');
  M('UnityEngine.SceneManagement.Scene', 'get_name', [], false, () => retStr(world.scene));
  const RS = 'UnityEngine.RenderSettings';
  M(RS, 'get_fog', [], true, () => false);
  M(RS, 'get_fogMode', [], true, () => newEnum('UnityEngine.FogMode', 3));
  M(RS, 'get_fogColor', [], true, () => COL([0.5, 0.5, 0.5, 1]));
  M(RS, 'get_fogDensity', [], true, () => 0.01);
  M(RS, 'get_fogStartDistance', [], true, () => 0);
  M(RS, 'get_fogEndDistance', [], true, () => 300);
  M(RS, 'get_ambientMode', [], true, () => newEnum('UnityEngine.Rendering.AmbientMode', 3));
  M(RS, 'get_ambientSkyColor', [], true, () => COL([0.2, 0.2, 0.2, 1]));
  M(RS, 'get_ambientEquatorColor', [], true, () => COL([0.11, 0.13, 0.13, 1]));
  M(RS, 'get_ambientGroundColor', [], true, () => COL([0.05, 0.04, 0.03, 1]));
  M(RS, 'get_ambientIntensity', [], true, () => 1);
  M(RS, 'get_ambientLight', [], true, () => COL([0.2, 0.2, 0.2, 1]));
  M(RS, 'get_reflectionIntensity', [], true, () => 1);
  M(RS, 'get_skybox', [], true, () => retObj(0));
  M('UnityEngine.QualitySettings', 'get_activeColorSpace', [], true, () => newEnum('UnityEngine.ColorSpace', 0));
  M('UnityEngine.QualitySettings', 'get_vSyncCount', [], true, () => 0);
  M('UnityEngine.QualitySettings', 'get_antiAliasing', [], true, () => 0);
  M('UnityEngine.Application', 'get_targetFrameRate', [], true, () => 30);

  function call(m, holder, args) {
    world.now += world.costPerCall;
    const entry = { cls: m.owner.fullName, name: m.name, static: m.isStatic, epoch: world.epoch };
    world.invocations.push(entry);
    if (!world.inCallback) fatal('Unity call outside a main-thread callback: ' + m.owner.fullName + '::' + m.name);
    if (holder) holder.handle.check();
    args.forEach(a => { if (a && a.handle instanceof FakePtr) a.handle.check(); });
    if (DENY.test(m.name)) fatal('denied method ' + m.owner.fullName + '::' + m.name);
    if (!/^UnityEngine(\.|$)/.test(m.owner.namespace)) fatal('game (non-UnityEngine) method ' + m.owner.fullName + '::' + m.name);
    let o = null;
    if (holder && !(holder instanceof VT)) {
      o = objs.get(holder.handle.addr);
      if (!o) fatal('holder is not an object');
      if (!o.klass.isSubclassOf(m.owner)) fatal('holder ' + o.klass.fullName + ' is not ' + m.owner.fullName);
      if (o.klass.isSubclassOf(C['UnityEngine.Object']) && view.getBigUint64(holder.handle.addr + 16, true) === 0n) fatal('NullReferenceException: ' + m.name + ' on a destroyed ' + o.klass.fullName);
      entry.holder = o.klass.fullName;
    }
    return m.impl(o, args, holder);
  }

  // ------------------------------------------------------------------ the 12035-shaped scene
  const shaderMember = newUnity(C['UnityEngine.Shader'], { name: 'AS/Member' });
  const shaderStage = newUnity(C['UnityEngine.Shader'], { name: 'AS/Stage' });
  const shaderColor = newUnity(C['UnityEngine.Shader'], { name: 'AS/Color/Opaque' });
  const bodyTex = newUnity(C['UnityEngine.Texture2D'], { name: 'ch0212_co0001_body_col', width: 1024, height: 1024 });
  const rt = newUnity(C['UnityEngine.RenderTexture'], { name: 'LiveCoreCamera_RT', width: 1280, height: 720 });
  const matBody = newUnity(C['UnityEngine.Material'], { name: 'ch0212_co0001_body', shader: shaderMember, keywords: ['_RIM'],
    props: { _MainTex: bodyTex, _TintColor: [0.4989, 0.5149, 0.649, 1], _AmbientColor: [1, 1, 1, 1], _RimlightColor: [0.4314, 0.4498, 1, 1],
      _RimlightDirection: [-9, 6, 0, 0], _RimglightIntensity: 0.75, _RimglightPower: 13, _MainTexMipmapBias: 0 } });
  const matStageA = newUnity(C['UnityEngine.Material'], { name: 'bg0006_01_stageA_opa_mt', shader: shaderStage,
    props: { _TintColor: [1, 1, 1, 1], _AmbientColor: [0.62, 0.6, 0.71, 1], _BlendColor: [0, 0, 0, 0], _MainTexMipmapBias: 0, _Cutoff: 0.5 } });
  const matOut = newUnity(C['UnityEngine.Material'], { name: 'bg0006_01_out_opa_mt', shader: shaderColor, props: { _TintColor: [1, 1, 1, 1] } });
  const timeline = newUnity(C['UnityEngine.Playables.PlayableAsset'], { name: 'so2035_timeline' });
  const entry = gameObject('EntryPoint', 0), live = gameObject('Live', entry.tr);
  const directorGo = gameObject('Director', live.tr);
  const director = component(directorGo, PD, { main: true, asset: timeline });
  const music = newManaged(C[LC + 'LiveMusicMachine'], { musicPlayingTime: 11.48, '<IsPlayingMusic>k__BackingField': true, '<MusicLength>k__BackingField': 107.3 });
  const memberVO = newManaged(C['LLAS.DM.ValueObject.Live3DMemberVO'], { '<MemberMasterId>k__BackingField': 212, '<FormationPosition>k__BackingField': 1,
    '<SuitId>k__BackingField': [true, 100212001] });
  const assetVO = newManaged(C['LLAS.DM.ValueObject.Live3DAssetVO'], { '<Members>k__BackingField': newArray(C['LLAS.DM.ValueObject.Live3DMemberVO'].type, [memberVO]) });
  const qualityVO = newManaged(C['LLAS.DM.ValueObject.LiveQualitySettingVO'], { '<PostEffect>k__BackingField': false, '<RenderingResolution>k__BackingField': 720,
    '<Quality>k__BackingField': 30, '<FrameRate60Fps>k__BackingField': false, '<MemberSwingBone>k__BackingField': true });
  component(directorGo, 'LLAS.Scene.Live.LiveDirector', {}, { '<TimelineDirector>k__BackingField': director, asset: assetVO,
    '<MusicMachine>k__BackingField': music, liveQualitySetting: qualityVO });
  const cameras = gameObject('Cameras', live.tr);
  const rig = gameObject('MainCamera', cameras.tr, { lp: CAM1150.unityRigPosition, lr: CAM1150.unityRigRotation });
  const curve = newManaged(C[LC + 'CameraCurve'], { speed: 1.5, label: 0 });
  set(curve, 'label', newString('cut-03'));
  const weightsList = newManaged(C['System.Collections.Generic.List`1'], { _items: newArray(F, [0.25, 0.75, 0, 0]), _size: 2 });
  component(rig, LC + 'LiveCoreCameraWork', {}, { fieldOfView: CAM1150.fov, offsetScale: 1, targetName: newString('Member1'),
    secretToken: newString('do-not-dump-me'), curve, weights: weightsList, enabledMask: true });
  const camGo = gameObject('Camera', rig.tr, { lr: [0, 1, 0, 0] });
  const mainCamera = component(camGo, CAM, { fov: CAM1150.fov, aspect: 1280 / 720, near: 0.1, far: 1000, target: rt });
  component(camGo, LC + 'CameraAspectCorrector', {}, { mode: 1, '<Correction>k__BackingField': opts.correction || 1, defaultOrthographicSize: 5,
    target: mainCamera, targetAspect: 1280 / 720 });
  component(camGo, LC + 'LiveCoreCamera', {}, { enablePostEffect: false });
  const overlayGo = gameObject('OverlayCamera', cameras.tr);
  const overlay = component(overlayGo, CAM, { fov: 60, aspect: 1280 / 720, near: 0.3, far: 1000, depth: 1 });
  const deadGo = gameObject('DestroyedCamera', cameras.tr);
  const deadCamera = component(deadGo, CAM, { fov: 40, aspect: 1, near: 0.3, far: 100 });
  destroy(deadCamera);
  // cutinCamera holds a stale reference to a destroyed camera (fake-null): never invoked.
  component(cameras, LC + 'LiveCoreCameraManager', {}, { overlayCamera: overlay, cutinCamera: deadCamera });
  gameObject('Flare', cameras.tr);
  gameObject('Flare', cameras.tr);
  for (let i = 0; i < (opts.extraCameras || 0); i++) {
    const g = gameObject('ExtraCamera' + i, cameras.tr);
    component(g, CAM, { fov: 50, aspect: 1280 / 720, near: 0.3, far: 100 });
  }
  const members = gameObject('Members', live.tr), member1 = gameObject('Member1', members.tr, { lp: [-0.0287, 0, 1.8735] });
  const memberInfo = newManaged(C[LC + 'MemberInfo'], { '<FormationPosition>k__BackingField': 1 });
  component(member1, LC + 'LiveCoreMember', {}, { memberInfo });
  const model = gameObject('Model', member1.tr);
  const rigRoot = gameObject('ch0212_co0001_member(Clone)', model.tr);
  const keys = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'keys', 'mvdump-keys-12035.json'), 'utf8'));
  const bones = {};
  keys.member.bones.forEach(rel => {
    let parent = rigRoot.tr, acc = '';
    rel.split('/').forEach(part => {
      acc = acc ? acc + '/' + part : part;
      if (!bones[acc]) bones[acc] = gameObject(part, parent, { lp: [0, part === 'Hips' ? 0.95 : 0.08, 0] });
      parent = bones[acc].tr;
    });
  });
  const boneTr = (suffix) => { const k = Object.keys(bones).find(b => b.endsWith(suffix)); return k ? bones[k].tr : 0; };
  component(rigRoot, 'LLAS.Components.Members.BodyPartManager', {}, { head: boneTr('/Neck/Head'), hips: boneTr('/Hips'), neck: boneTr('/Neck') });
  const meshBody = gameObject('mesh_body', rigRoot.tr), body = gameObject('Body', meshBody.tr, { layer: 9 });
  const bodyMesh = newUnity(C['UnityEngine.Mesh'], { name: 'Body', shapes: ['eye_close', 'mouth_a'] });
  const bodyRenderer = component(body, 'UnityEngine.SkinnedMeshRenderer', { mesh: bodyMesh, weights: [12.5, 0], materials: [matBody] });
  component(rigRoot, LC + 'LiveCoreMemberAmbient', {}, { materials: newArray(C['UnityEngine.Material'].type, [matBody]), color: [1, 1, 1, 1] });
  const swing = [0, 1].map(i => component(gameObject('SkirtE' + i + '_Dyna', bones['Reference/Move/Hips_Position/Hips'].tr), 'LLAS.Components.Members.SwingBone', {},
    { currentTipPosition: [0.1 * i, 0.8, 1.9], previousTipPosition: [0.1 * i, 0.81, 1.9], length: 0.2 }));
  component(rigRoot, 'LLAS.Components.Members.SwingBoneManager', {}, { swingBones: newArray(C['LLAS.Components.Members.SwingBone'].type, swing), gravity: 9.8 });
  const stages = gameObject('Stages', live.tr), mainStage = gameObject('MainStage', stages.tr);
  const stageModel = gameObject('Model', mainStage.tr), mdl = gameObject('bg0006_01_mdl', stageModel.tr), ground = gameObject('ground', mdl.tr);
  const groundMesh = newUnity(C['UnityEngine.Mesh'], { name: 'ground', shapes: [] });
  component(ground, 'UnityEngine.MeshFilter', { mesh: groundMesh });
  component(ground, 'UnityEngine.MeshRenderer', { materials: [matOut, matStageA, 0] });
  const effect = gameObject('Effect', mainStage.tr), lit = gameObject('lit_01', effect.tr), litC = gameObject('litC_All', lit.tr);
  const litA = gameObject('litC_04_All', litC.tr), litR = gameObject('litC_04_Yrot_Ani', litA.tr, { lr: [0, 0.38268343, 0, 0.92387953] });
  gameObject('litC_04_handle', litR.tr, { lp: [1.2, 6.4, -3.1] });
  gameObject('litC_05_All', litC.tr);
  gameObject('litC_05_All', litC.tr);
  const dis = gameObject('dis_01', effect.tr);
  gameObject('main_01', dis.tr, { active: false });
  const par = gameObject('fx_par_so2035_01', effect.tr), par1 = gameObject('par_01', par.tr);
  component(par1, PS);
  component(par1, 'UnityEngine.ParticleSystemRenderer', { materials: [] });
  const lightGo = gameObject('Directional Light', entry.tr);
  component(lightGo, LT);
  for (let i = 0; i < (opts.extraRenderers || 0); i++) {
    const g = gameObject('crowd_' + i, effect.tr);
    component(g, 'UnityEngine.MeshFilter', { mesh: groundMesh });
    component(g, 'UnityEngine.MeshRenderer', { materials: [matStageA] });
  }
  // An inactive prefab-asset renderer (not in the scene) that the dump must skip.
  const prefab = gameObject('PrefabAsset', 0, { active: false });
  component(prefab, 'UnityEngine.MeshRenderer', { materials: [matOut] });

  const assemblies = [{ name: 'UnityEngine.CoreModule', image: { tryClass: (name) => (classes.get(name) && classes.get(name).assemblyName === 'UnityEngine.CoreModule') ? classes.get(name) : null } },
    { name: 'Assembly-CSharp', image: { tryClass: (name) => (classes.get(name) && classes.get(name).assemblyName === 'Assembly-CSharp') ? classes.get(name) : null } },
    { name: 'mscorlib', image: { tryClass: (name) => (classes.get(name) && classes.get(name).assemblyName === 'mscorlib') ? classes.get(name) : null } }];
  const Il2Cpp = { unityVersion: '2018.4.23f1', domain: { assemblies }, Type: { enum: TE },
    Object: Obj, String: Str, Array: Arr, ValueType: VT, Reference: class {},
    string: (s) => new Str(new FakePtr(newString(s), world.epoch)),
    array: () => { throw new Error('fake: Il2Cpp.array is not used by the dump'); },
    perform: (block, flag) => {
      world.performs.push(flag);
      return Promise.resolve().then(() => { world.epoch++; world.inCallback = true; try { return block(); } finally { world.inCallback = false; world.epoch++; } });
    } };
  const dispatcher = {
    createIl2CppAdapter() {
      const counts = { enqueued: 0, completed: 0, rejected: 0, postCalls: 0, callbacks: 0 };
      let lastCode = null;
      return {
        installOnCurrentMainThread() { world.dispatcherState = 'READY'; return this.status(); },
        status() { return { qaOnly: true, state: world.dispatcherState, lastCode, pending: 0, counts: Object.assign({}, counts) }; },
        dispatch(action) {
          if (world.dispatcherState !== 'READY') return Promise.reject(new Error(lastCode || 'DISPATCHER_NOT_READY'));
          if (typeof action !== 'function' || action.constructor.name === 'AsyncFunction') return Promise.reject(new Error('SYNC_READ_ONLY_ACTION_REQUIRED'));
          counts.enqueued++;
          return new Promise((resolve, reject) => setImmediate(() => {
            counts.callbacks++;
            if (world.throwNext > 0) {
              // A JS error inside the action: the ticket is rejected, the dispatcher stays READY.
              world.throwNext--; counts.rejected++; reject(new Error('FAKE_ACTION_THREW')); return;
            }
            if (world.poisonNext) {
              world.poisonNext = false; world.dispatcherState = 'POISONED'; lastCode = 'MAIN_CALLBACK_TIMEOUT'; counts.rejected++;
              reject(new Error('MAIN_CALLBACK_TIMEOUT')); return;
            }
            world.epoch++; world.frame++; world.dispatches++; world.directorTime += world.advance;
            if (typeof world.onCallback === 'function') world.onCallback(world);
            world.inCallback = true;
            const before = world.invocations.length;
            try {
              const value = action();
              if (value && typeof value.then === 'function') { world.thenables++; world.dispatcherState = 'POISONED'; lastCode = 'ASYNC_UI_ACTION_FORBIDDEN'; counts.rejected++; reject(new Error('ASYNC_UI_ACTION_FORBIDDEN')); }
              else { counts.completed++; resolve(value); }
            } catch (error) { counts.rejected++; reject(error); }
            finally { world.inCallback = false; world.callsPerAction.push(world.invocations.length - before); world.epoch++; }
          }));
        },
        dispose() { world.dispatcherState = 'DISPOSED'; return { redirected: true, handlesFreed: 2 }; }
      };
    }
  };
  world.objects = { director, mainCamera, overlay, deadCamera, bodyRenderer, matBody, matStageA, rigRoot, rig, camGo };
  world.keys = keys;
  world.cam1150 = CAM1150;
  world.Il2Cpp = Il2Cpp;
  world.dispatcher = dispatcher;
  world.FakePtr = FakePtr;
  world.destroy = destroy;
  world.newObjectWrapper = (addr) => new Obj(new FakePtr(addr, world.epoch));
  return world;
}

function bundlePath() {
  if (process.env.MVDUMP_BUNDLE) return process.env.MVDUMP_BUNDLE;
  const qa = process.env.R8_QA_DIR || '/tmp/claude-0/-home-user/dc5429c4-d1a3-5925-9def-449194025faf/scratchpad/r8tree/qa';
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'mvdump-bundle-'));
  const target = path.join(out, 'unity_ui.mvdump.bundle.js');
  const built = spawnSync('python3', [path.join(__dirname, '..', 'build_mvdump_agent.py'), '--qa', qa, '--extension',
    path.join(__dirname, '..', 'mv_runtime_dump.js'), '--out', target], { encoding: 'utf8' });
  if (built.status !== 0) throw new Error('bundle build failed: ' + built.stderr + built.stdout);
  return target;
}

// Evaluate the patched observer + extension (the bundle after the bridge and dispatcher)
// against the fake world. Returns {ctx, world, rpc(method, ...args)}.
function boot(opts = {}) {
  const world = createWorld(opts);
  const bundle = fs.readFileSync(opts.bundle || bundlePath(), 'utf8');
  const start = bundle.indexOf('/* Disposable runtime QA observer.');
  if (start < 0) throw new Error('observer marker not found in bundle');
  const body = bundle.slice(start);
  const fakeDate = { now: () => world.now };
  const ctx = { console, Date: fakeDate, JSON, Math, Object, Array, String, Number, Boolean, Error, TypeError, Promise, Set, Map, Symbol, Proxy, Reflect,
    isFinite, parseInt, parseFloat, Infinity, NaN, setImmediate, setTimeout, clearTimeout, setInterval, clearInterval,
    Process: { id: 123, arch: 'arm64', getCurrentThreadId: () => 77, findModuleByName: () => null },
    Frida: { version: '16.6.6' }, File: { readAllText: () => 'UnityMain\n' }, Memory: { alloc: () => { throw new Error('fake: Memory.alloc unused'); } },
    ptr: (v) => new world.FakePtr(v, null), NULL: new world.FakePtr(0, null), Script: { bindWeak() {} }, NativePointer: world.FakePtr,
    send: (message) => world.sent.push(message), Java: undefined, Il2Cpp: world.Il2Cpp, CachedMainThreadDispatcher: world.dispatcher, rpc: { exports: {} } };
  ctx.globalThis = ctx;
  ctx.QA_CACHED_BOOTSTRAP_ONLY = opts.bootstrapOnly !== false;
  vm.createContext(ctx);
  vm.runInContext(body, ctx, { filename: 'unity_ui.mvdump.bundle.js(tail)' });
  async function rpc(method, ...args) {
    const fn = ctx.rpc.exports[method];
    if (typeof fn !== 'function') throw new Error('unable to find method ' + method);
    // Frida RPC results cross the wire as JSON: normalise (and catch non-JSON values) the same way.
    const value = await fn(...args);
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  }
  const proof = { pid: 123, tid: 77, comm: 'UnityMain', source: 'native-debuggerd-engine-loop-and-proc-comm', nativeBacktraceSha256: 'f'.repeat(64) };
  return { ctx, world, rpc, proof };
}

module.exports = { createWorld, boot, bundlePath, TE, DENY, worldToCamera, perspective };

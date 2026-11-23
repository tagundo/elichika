'use strict';
// Offline tests of the patched observer + mv_runtime_dump.js against the fake il2cpp world.
// node --test qa-mvdump/tests/mv_runtime_dump.test.cjs   (MVDUMP_BUNDLE or R8_QA_DIR selects the bundle)
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');
const { boot, bundlePath, DENY } = require('./fake_il2cpp.cjs');

const BUNDLE = bundlePath();
const ORIGINAL = ['enablecached', 'beginintrotrace', 'endintrotrace', 'status', 'dispose', 'initialize', 'snapshot', 'features', 'pick', 'pickmv', 'classes'];
// Independent copy of the plan's allowlist (A.4) plus the observer's own proven reads.
const ALLOWED = new Set([
  'UnityEngine.Time::get_frameCount', 'UnityEngine.Time::get_time', 'UnityEngine.Time::get_unscaledTime', 'UnityEngine.Time::get_deltaTime',
  'UnityEngine.Time::get_timeScale', 'UnityEngine.Time::get_realtimeSinceStartup',
  'UnityEngine.Screen::get_width', 'UnityEngine.Screen::get_height', 'UnityEngine.Screen::get_orientation',
  'UnityEngine.SceneManagement.SceneManager::GetActiveScene', 'UnityEngine.SceneManagement.Scene::get_name',
  'UnityEngine.Resources::FindObjectsOfTypeAll', 'UnityEngine.GameObject::Find',
  'UnityEngine.Shader::PropertyToID', 'UnityEngine.Shader::GetGlobalFloat', 'UnityEngine.Shader::GetGlobalVector', 'UnityEngine.Shader::GetGlobalVectorArray',
  ...['get_fog', 'get_fogMode', 'get_fogColor', 'get_fogDensity', 'get_fogStartDistance', 'get_fogEndDistance', 'get_ambientMode', 'get_ambientSkyColor',
    'get_ambientEquatorColor', 'get_ambientGroundColor', 'get_ambientIntensity', 'get_ambientLight', 'get_reflectionIntensity', 'get_skybox'].map(n => 'UnityEngine.RenderSettings::' + n),
  'UnityEngine.QualitySettings::get_activeColorSpace', 'UnityEngine.QualitySettings::get_vSyncCount', 'UnityEngine.QualitySettings::get_antiAliasing',
  'UnityEngine.Application::get_targetFrameRate', 'UnityEngine.Object::GetInstanceID', 'UnityEngine.Object::get_name',
  'UnityEngine.Component::get_gameObject', 'UnityEngine.Component::get_transform', 'UnityEngine.Component::GetComponents', 'UnityEngine.Component::GetComponent',
  'UnityEngine.GameObject::get_activeSelf', 'UnityEngine.GameObject::get_activeInHierarchy', 'UnityEngine.GameObject::get_transform',
  'UnityEngine.GameObject::get_layer',
  'UnityEngine.Behaviour::get_enabled', 'UnityEngine.Behaviour::get_isActiveAndEnabled',
  ...['get_position', 'get_rotation', 'get_lossyScale', 'get_localPosition', 'get_localRotation', 'get_localScale', 'get_parent', 'get_childCount', 'GetChild', 'Find',
    'GetSiblingIndex'].map(n => 'UnityEngine.Transform::' + n),
  ...['get_fieldOfView', 'get_aspect', 'get_nearClipPlane', 'get_farClipPlane', 'get_orthographic', 'get_orthographicSize', 'get_usePhysicalProperties',
    'get_focalLength', 'get_lensShift', 'get_projectionMatrix', 'get_worldToCameraMatrix', 'get_rect', 'get_pixelRect', 'get_pixelWidth', 'get_pixelHeight',
    'get_depth', 'get_clearFlags', 'get_backgroundColor', 'get_cullingMask', 'get_allowHDR', 'get_allowMSAA', 'get_depthTextureMode', 'get_targetTexture'].map(n => 'UnityEngine.Camera::' + n),
  'UnityEngine.Texture::get_width', 'UnityEngine.Texture::get_height', 'UnityEngine.RenderTexture::get_format',
  ...['get_time', 'get_duration', 'get_state', 'get_timeUpdateMode', 'get_extrapolationMode', 'get_playableAsset'].map(n => 'UnityEngine.Playables.PlayableDirector::' + n),
  ...['get_enabled', 'get_isVisible', 'get_bounds', 'get_sharedMaterials', 'get_lightmapIndex', 'get_lightmapScaleOffset', 'get_sortingOrder'].map(n => 'UnityEngine.Renderer::' + n),
  'UnityEngine.SkinnedMeshRenderer::get_sharedMesh', 'UnityEngine.SkinnedMeshRenderer::GetBlendShapeWeight', 'UnityEngine.MeshFilter::get_sharedMesh',
  'UnityEngine.Mesh::get_blendShapeCount', 'UnityEngine.Mesh::GetBlendShapeName',
  ...['get_shader', 'get_renderQueue', 'get_shaderKeywords', 'HasProperty', 'GetFloat', 'GetColor', 'GetVector', 'GetTexture', 'GetTextureScale',
    'GetTextureOffset'].map(n => 'UnityEngine.Material::' + n),
  ...['get_type', 'get_color', 'get_intensity', 'get_range', 'get_spotAngle', 'get_shadows', 'get_cullingMask'].map(n => 'UnityEngine.Light::' + n),
  ...['get_isPlaying', 'get_isEmitting', 'get_isPaused', 'get_particleCount', 'get_time', 'get_randomSeed', 'get_useAutoRandomSeed'].map(n => 'UnityEngine.ParticleSystem::' + n)
]);
const FULL_PARTS = ['census', 'quality', 'fovmodNative', 'renderers', 'materials', 'lightingRefs', 'members', 'springs', 'stageNodes', 'particles', 'post'];

async function bound(opts) {
  const h = boot(Object.assign({ bundle: BUNDLE }, opts || {}));
  await h.rpc('enablecached', h.proof);
  return h;
}
function assertClean(world) {
  assert.deepEqual(world.fatal, [], 'no managed exception / write / game method');
  assert.deepEqual(world.stale, [], 'no Il2Cpp object used across callbacks');
  assert.equal(world.thenables, 0, 'no action returned a thenable');
  const bad = [...new Set(world.invocations.map(i => i.cls + '::' + i.name).filter(k => !ALLOWED.has(k)))];
  assert.deepEqual(bad, [], 'every invoked method is allowlisted');
}
function close(a, b, tol, label) {
  assert.equal(a.length, b.length, label + ' length');
  a.forEach((v, i) => assert.ok(Math.abs(v - b[i]) <= tol, `${label}[${i}] ${v} vs ${b[i]}`));
}
// Full pass of one part, following `next` cursors (materials: host-style index list).
// What the sampler sends per material: usedBy keys and up to 2 renderer slots to resolve it through.
function materialRequests(renderers) {
  const byId = new Map();
  for (const r of renderers) for (const m of r.materials) {
    if (m.instanceId === null) continue;
    if (!byId.has(m.instanceId)) byId.set(m.instanceId, { instanceId: m.instanceId, usedBy: [], resolve: [] });
    const w = byId.get(m.instanceId);
    w.usedBy.push(r.key + '#' + m.slot);
    if (w.resolve.length < 2) w.resolve.push({ path: r.rawPath || r.path, slot: m.slot, rendererId: r.instanceId });
  }
  return [...byId.values()];
}
async function runPart(h, part, extra, maxChunks = 80) {
  const records = [];
  let cursor = {}, chunk = 0;
  for (; chunk < maxChunks; chunk++) {
    const opts = Object.assign({ part, cursor }, extra || {});
    const rec = await h.rpc('mvruntime', opts);
    records.push(rec);
    if (!rec.next) break;
    cursor = rec.next;
  }
  assert.ok(chunk < maxChunks, part + ' must terminate');
  return records;
}

test('RPC surface: the 11 original RPCs unchanged, mvruntimeprobe + mvruntime added', () => {
  const h = boot({ bundle: BUNDLE });
  assert.deepEqual(Object.keys(h.ctx.rpc.exports), [...ORIGINAL, 'mvruntimeprobe', 'mvruntime']);
  assert.equal(typeof h.ctx.QA_MVDUMP_HOST.onMain, 'function');
  assert.ok(Object.isFrozen(h.ctx.QA_MVDUMP_HOST));
});

test('both RPCs refuse before enablecached: no perform, no dispatch, no Unity call', () => {
  const h = boot({ bundle: BUNDLE });
  assert.throws(() => h.ctx.rpc.exports.mvruntime({ part: 'frame' }), /MVDUMP_DISPATCHER_NOT_READY/);
  assert.throws(() => h.ctx.rpc.exports.mvruntimeprobe({ chunk: 0 }), /MVDUMP_DISPATCHER_NOT_READY/);
  assert.deepEqual(h.world.performs, []);
  assert.equal(h.world.dispatches, 0);
  assert.equal(h.world.invocations.length, 0);
});

test('after enablecached: exactly one cold main perform; the dump uses the same cached dispatcher', async () => {
  const h = await bound();
  assert.deepEqual(h.world.performs, ['main']);
  const before = h.world.dispatches;
  await h.rpc('mvruntimeprobe', { chunk: 0 });
  await h.rpc('mvruntime', { part: 'frame' });
  assert.equal(h.world.dispatches, before + 2, 'one dispatched action per RPC');
  assert.deepEqual(h.world.performs, ['main'], 'no second bootstrap');
  assert.throws(() => h.ctx.rpc.exports.mvruntime({ part: 'nope' }), /MVDUMP_UNKNOWN_PART/);
  assertClean(h.world);
});

test('probe: metadata only, classes found/missing, column-major layout self-check', async () => {
  const h = await bound();
  const chunks = [];
  for (let chunk = 0; chunk < 6; chunk++) {
    const res = await h.rpc('mvruntimeprobe', { chunk, perChunk: 8 });
    chunks.push(res);
    if (res.done) break;
  }
  const classes = chunks.flatMap(c => c.classes);
  const found = classes.filter(c => c.found).map(c => c.key), missing = classes.filter(c => !c.found).map(c => c.key);
  for (const key of ['Camera', 'PlayableDirector', 'LiveDirector', 'CameraAspectCorrector', 'LiveCoreCameraWork', 'LiveMusicMachine', 'BodyPartManager', 'SwingBoneManager', 'LiveQualitySettingVO'])
    assert.ok(found.includes(key), key + ' found');
  for (const key of ['LiveSplitScreenEffect', 'MemberSpotLightShaft', 'LiveMvScene']) assert.ok(missing.includes(key), key + ' missing');
  const corrector = classes.find(c => c.key === 'CameraAspectCorrector');
  assert.ok(corrector.fields.some(f => f.name === '<Correction>k__BackingField' && f.type === 'System.Single'));
  assert.equal(corrector.unityObject, true);
  const camera = classes.find(c => c.key === 'Camera');
  assert.equal(camera.methods.get_projectionMatrix, true);
  assert.equal(camera.methods.get_lensShift, true);
  const layout = chunks[0].layoutSelfCheck;
  assert.equal(layout.ok, true, JSON.stringify(layout));
  assert.equal(layout.columnMajor, true);
  assert.equal(layout.m32Raw, -1);
  assert.equal(layout.perspectiveSane, true);
  assert.equal(chunks[0].objectLayout.m_CachedPtr, 16);
  // Metadata only: the probe never invokes a game method and reads no LLAS object.
  assertClean(h.world);
});

test('frame record: one callback, H180 camera values, correctors, cameraWork, globals, members, anchors', async () => {
  const h = await bound();
  const rec = await h.rpc('mvruntime', { part: 'frame', keys: { globals: h.world.keys.globals, member: { anchors: h.world.keys.member.anchors }, stageOrigin: h.world.keys.stageOrigin } });
  assertClean(h.world);
  assert.equal(rec.kind, 'frame');
  assert.equal(rec.clock.frameCount, rec.clockEnd.frameCount, 'single-frame record');
  assert.equal(rec.clock.directorTime, 11.5);
  close([rec.clock.musicTime], [11.48], 1e-6, 'musicTime (float32 field)');
  assert.equal(rec.clock.musicPlaying, true);
  assert.deepEqual(rec.scene, { name: 'LiveMv', width: 1280, height: 720, orientation: { v: 3, n: 'LandscapeLeft' }, unityVersion: '2018.4.23f1' });
  const director = rec.directors.find(d => d.main);
  assert.equal(director.key, 'director:/EntryPoint/Live/Director');
  assert.equal(director.heldByLiveDirector, true);
  assert.deepEqual(director.state, { v: 1, n: 'Playing' });
  assert.equal(director.asset, 'so2035_timeline');
  const main = rec.cameras[0], cam = h.world.cam1150;
  assert.equal(main.key, 'camera:main');
  assert.equal(main.path, '/EntryPoint/Live/Cameras/MainCamera/Camera');
  close([main.fieldOfView], [cam.fov], 1e-6, 'fov');
  close([main.aspect], [16 / 9], 1e-6, 'aspect');
  close(main.projection, cam.projection, 2e-6, 'projection');
  assert.equal(main.projection[11], -1, 'column-major perspective e[11]');
  assert.equal(main.projection[15], 0);
  close(main.worldToCamera, cam.worldToCameraColumnMajor, 2e-6, 'worldToCamera');
  // H180: worldToCamera_game == V_editor * diag(-1,1,1,1) (columns 0 negated).
  const predicted = cam.editorViewColumnMajor.map((v, i) => (i < 4 ? -v : v));
  close(main.worldToCamera, predicted, 2e-6, 'H180 identity');
  close(main.rig.position, cam.unityRigPosition, 1e-6, 'rig position');
  close(main.rig.rotation, cam.unityRigRotation, 1e-6, 'rig rotation');
  close(main.transform.rotation, cam.unityCameraRotationH180, 1e-6, 'camera component rotation (H180)');
  assert.deepEqual(main.transform.localRotation, [0, 1, 0, 0]);
  assert.equal(main.rig.path, '/EntryPoint/Live/Cameras/MainCamera');
  assert.deepEqual(main.targetTexture, { name: 'LiveCoreCamera_RT', width: 1280, height: 720, format: { v: 0, n: 'ARGB32' } });
  const overlay = rec.cameras.find(c => c.role === 'overlay');
  assert.equal(overlay.key, 'camera:overlay');
  assert.ok(!rec.cameras.some(c => /DestroyedCamera/.test(c.path)), 'destroyed camera never read');
  const corrector = rec.correctors[0];
  assert.equal(corrector.key, 'corrector:camera:main');
  assert.equal(corrector.correction, 1);
  assert.deepEqual(corrector.mode, { v: 1, n: null });
  assert.equal(corrector.target.cameraKey, 'camera:main');
  close([corrector.fields.targetAspect.v], [16 / 9], 1e-6, 'targetAspect');
  const work = rec.cameraWork[0];
  assert.equal(work.key, 'cameraWork:/EntryPoint/Live/Cameras/MainCamera');
  assert.deepEqual(work.fields.fieldOfView, { t: 'f32', v: Number(Math.fround(cam.fov).toPrecision(7)) });
  assert.deepEqual(work.fields.targetName, { t: 'str', v: 'Member1' });
  assert.equal(work.fields.secretToken.v, null, 'non-name strings are never read');
  assert.equal(work.fields.weights.t, 'list');
  assert.equal(work.fields.weights.n, 2);
  assert.equal(work.fields.curve.t, 'obj');
  assert.deepEqual(rec.globals['global:_Beat'], { f: 0.25, v: [0.25, 0, 0, 0] });
  assert.deepEqual(rec.globals['global:_RenderTextureResolution'].v, [1280, 720, 0, 0]);
  assert.ok(!('global:_Colors' in rec.globals), 'vector arrays are off by default');
  assert.ok(!h.world.invocations.some(i => i.name === 'GetGlobalVectorArray'));
  assert.deepEqual(rec.members, [{ slot: 1, formationPosition: 1, memberId: 212, suitId: 100212001, active: true, path: '/EntryPoint/Live/Members/Member1' }]);
  const keys = rec.anchors.map(a => a.key);
  for (const k of ['anchor:member1:Hips', 'anchor:member1:Head', 'anchor:member1:LeftHand', 'anchor:member1:RightHand', 'anchor:stageOrigin']) assert.ok(keys.includes(k), k);
  assert.equal(rec.anchors.find(a => a.key === 'anchor:member1:Head').source, 'BodyPartManager.head');
  assert.equal(rec.renderSettings.fogMode.n, 'ExponentialSquared');
  assert.equal(rec.lights.length, 1);
  assert.equal(rec.cost.truncated, false);
  assert.deepEqual(rec.nonFinite, []);
  assert.equal(rec.errors, undefined, JSON.stringify(rec.errors));
  assert.ok(h.world.callsPerAction[h.world.callsPerAction.length - 1] > 50, 'the frame action ran in one callback');
});

test('arrays=true reads the _Colors vector array (bounded), still allowlisted', async () => {
  const h = await bound();
  const rec = await h.rpc('mvruntime', { part: 'frame', arrays: true, keys: { globals: ['_Beat'], vectorArrays: ['_Colors'] } });
  assertClean(h.world);
  assert.equal(rec.globals['global:_Colors'].n, 3);
  assert.deepEqual(rec.globals['global:_Colors'].v[1], [1, 1, 1, 1]);
});

test('every full part terminates, stays read-only and keeps no object across callbacks', async () => {
  const h = await bound({ extraRenderers: 60 });
  const keys = h.world.keys, out = {};
  // As the sampler does: the probe resolves every class once before any part runs.
  for (let chunk = 0; chunk < 6; chunk++) if ((await h.rpc('mvruntimeprobe', { chunk })).done) break;
  for (const part of FULL_PARTS) {
    let extra = {};
    if (part === 'materials') {
      const wanted = materialRequests(out.renderers.flatMap(r => r.renderers));
      const records = [];
      const before = h.world.findAllTypes.length;
      for (let i = 0; i < wanted.length; i += 8) records.push(await h.rpc('mvruntime', { part, materials: wanted.slice(i, i + 8), shaders: keys.shaders }));
      assert.ok(!h.world.findAllTypes.slice(before).includes('UnityEngine.Material'), 'materials resolve through renderer slots, never a Material scan');
      out[part] = records;
      continue;
    }
    if (part === 'members') extra = { keys: { member: keys.member } };
    if (part === 'stageNodes') extra = { keys: { bindings: keys.bindings } };
    out[part] = await runPart(h, part, extra);
  }
  assertClean(h.world);
  const census = out.census.flatMap(r => r.census.nodes);
  assert.ok(census.some(n => n.path === '/EntryPoint/Live/Cameras/MainCamera/Camera' && n.components.includes('UnityEngine.Camera')));
  assert.equal(census.filter(n => n.path === '/EntryPoint/Live/Cameras/Flare').length, 2, 'same-name siblings are both listed');
  assert.ok(census.every(n => n.depth <= 6));
  assert.ok(census.some(n => n.rawPath && /\(Clone\)$/.test(n.rawPath)), '(Clone) stripped, raw kept');
  const q = out.quality[0].quality;
  assert.equal(q.holder, 'LLAS.Scene.Live.LiveDirector.liveQualitySetting');
  assert.deepEqual(q.values.Quality, { v: 30, n: null });
  assert.equal(q.values.RenderingResolution, 720);
  assert.equal(q.values.PostEffect, false);
  assert.deepEqual(q.unity.activeColorSpace, { v: 0, n: 'Gamma' });
  const renderers = out.renderers.flatMap(r => r.renderers);
  assert.ok(out.renderers.every(r => r.renderers.length <= 24));
  assert.ok(!renderers.some(r => /PrefabAsset/.test(r.path)), 'inactive prefab asset skipped');
  const body = renderers.find(r => r.mesh === 'Body');
  assert.equal(body.scope, 'member1');
  assert.equal(body.layer, 9, 'GameObject layer of the renderer');
  assert.ok(renderers.every(r => Number.isInteger(r.layer)), 'every renderer has an integer layer');
  assert.equal(body.path, '/EntryPoint/Live/Members/Member1/Model/ch0212_co0001_member/mesh_body/Body');
  assert.equal(body.rawPath, '/EntryPoint/Live/Members/Member1/Model/ch0212_co0001_member(Clone)/mesh_body/Body');
  const ground = renderers.find(r => r.mesh === 'ground' && /\/ground$/.test(r.path));
  assert.equal(ground.scope, 'stage');
  assert.deepEqual(ground.materials.map(m => m.name), ['bg0006_01_out_opa_mt', 'bg0006_01_stageA_opa_mt', undefined]);
  const ids = renderers.map(r => r.instanceId);
  assert.deepEqual(ids, [...ids].sort((a, b) => a - b), 'sorted by instanceId across chunks');
  assert.equal(new Set(ids).size, ids.length, 'no renderer twice');
  const materials = out.materials.flatMap(r => r.materials);
  const bodyMat = materials.find(m => m.name === 'ch0212_co0001_body');
  assert.deepEqual(bodyMat.properties._TintColor, { t: 'color', v: [0.4989, 0.5149, 0.649, 1] });
  assert.deepEqual(bodyMat.properties._MainTex, { t: 'tex', v: { name: 'ch0212_co0001_body_col', width: 1024, height: 1024 }, st: [1, 1, 0, 0] });
  assert.ok(bodyMat.missing.includes('_CheekTexArrayIndex'));
  assert.equal(bodyMat.propertySource, 'keys');
  assert.equal(bodyMat.resolvedBy, 'renderer');
  assert.ok(materials.every(m => m.resolvedBy === 'renderer' && !m.incomplete), JSON.stringify(materials.map(m => [m.name, m.resolvedBy])));
  assert.deepEqual(bodyMat.usedBy, ['renderer:/EntryPoint/Live/Members/Member1/Model/ch0212_co0001_member/mesh_body/Body#0']);
  const refs = out.lightingRefs[0].lightingRefs;
  assert.ok(refs.some(r => r.class.endsWith('LiveCoreMemberAmbient') && r.materials.includes(bodyMat.instanceId)));
  const member = out.members[0].members[0];
  assert.equal(member.rootPath, '/EntryPoint/Live/Members/Member1/Model/ch0212_co0001_member');
  assert.equal(member.bones.length, keys.member.bones.length);
  assert.ok(member.bones.every(b => !b.missing && b.key.startsWith('member:1:')));
  assert.deepEqual(member.blendShapes[0].weights, { eye_close: 12.5 });
  const spring = out.springs[0].springs[0];
  assert.equal(spring.boneField, 'swingBones');
  assert.equal(spring.bones.length, 2);
  assert.ok(spring.bones[1].fields.currentTipPosition.v.every(Number.isFinite));
  const nodes = out.stageNodes.flatMap(r => r.stageNodes);
  assert.ok(nodes.some(n => n.relPath === 'litC_04_All/litC_04_Yrot_Ani/litC_04_handle'));
  assert.ok(nodes.some(n => n.binding.endsWith('/dis_01/main_01') && n.relPath === '' && n.activeSelf === false), 'inactive binding still found (Transform.Find)');
  assert.ok(nodes.some(n => n.missing && n.binding.endsWith('/fx_stg_so2035_02/root')));
  const particles = out.particles.flatMap(r => r.particles);
  assert.deepEqual(particles.map(p => [p.key, p.particleCount, p.rendererEnabled]), [['particles:/EntryPoint/Live/Stages/MainStage/Effect/fx_par_so2035_01/par_01', 37, true]]);
  const post = out.post[0].post;
  assert.equal(post.enablePostEffect, false);
  assert.ok(post.holders.some(x => x.class.endsWith('LiveCoreCamera')));
  for (const recs of Object.values(out)) for (const r of recs) {
    assert.ok(r.clock && r.clockEnd, 'every full chunk carries clock and clockEnd');
    assert.equal(r.errors, undefined, JSON.stringify(r.errors));
  }
});

test('the harness itself catches stale objects and fatal calls (negative controls)', async () => {
  const h = await bound();
  const H = h.ctx.QA_MVDUMP_HOST;
  let kept = null;
  await H.onMain(function () { kept = H.allOfType(H.findClass('UnityEngine.Camera')).get(0); return true; });
  await assert.rejects(H.onMain(function () { return H.call(kept, 'get_fieldOfView'); }), /STALE_OBJECT/);
  assert.equal(h.world.stale.length, 1);
  await assert.rejects(H.onMain(function () { return H.call(H.allOfType(H.findClass('UnityEngine.Renderer')).get(0), 'get_material'); }), /FATAL_MANAGED_EXCEPTION/);
  assert.ok(h.world.fatal.some(m => /get_material/.test(m)));
  await assert.rejects(H.onMain(function () { return H.call(H.allOfType(H.findClass('LLAS.Scene.Live.LiveDirector')).get(0), 'get_TimelineDirector'); }), /FATAL/);
});

test('policy: no allowlisted name matches the deny pattern; mutating names are denied', () => {
  const h = boot({ bundle: BUNDLE });
  const ext = h.ctx.QA_MVDUMP_EXT, deny = new RegExp(ext.deny);
  assert.equal(ext.deny, DENY.source, 'extension and harness deny the same names');
  for (const [cls, names] of Object.entries(ext.allow)) {
    assert.match(cls, /^UnityEngine\./);
    for (const name of names) {
      assert.ok(!deny.test(name), cls + '::' + name + ' must not be denied');
      assert.ok(ALLOWED.has(cls + '::' + name), cls + '::' + name + ' is in the plan allowlist');
    }
  }
  for (const name of ['set_fieldOfView', 'SetFloat', 'Play', 'Evaluate', 'Simulate', 'get_material', 'get_materials', 'get_mesh', 'Instantiate', 'GetPropertyBlock', 'Render'])
    assert.ok(deny.test(name), name + ' denied');
});

test('budget: a slow device truncates optional sections but always records clockEnd; parts still progress', async () => {
  // A tight env budget (MV_RUNTIME_DUMP_FRAME_BUDGET_MS=15/30, MV_RUNTIME_DUMP_FULL_BUDGET_MS=20/40).
  const h = await bound({ costPerCall: 0.4 });
  const rec = await h.rpc('mvruntime', { part: 'frame', budget: { soft: 15, hard: 30 }, keys: { globals: h.world.keys.globals, member: { anchors: h.world.keys.member.anchors } } });
  assertClean(h.world);
  assert.equal(rec.cost.truncated, true);
  assert.ok(rec.cost.truncatedSections.some(s => ['anchors', 'renderSettings', 'lights'].includes(s)), JSON.stringify(rec.cost));
  assert.ok(rec.clockEnd && typeof rec.clockEnd.frameCount === 'number', 'clockEnd always read');
  assert.ok(rec.cameras[0].projection, 'the main camera is always read in full');
  assert.equal(rec.cost.budgetMs.soft, 15, 'the budget the host sent is the one used');
  const records = await runPart(h, 'renderers', { budget: { soft: 20, hard: 40 } }, 200);
  assert.ok(records.length > 1);
  assert.ok(records.every(r => r.renderers.length >= 1 || r.next === null || r.cost.objects >= 1), 'every chunk makes progress');
  assertClean(h.world);
});

test('caps: cameras <= 16 (8 detailed), renderers 24 per chunk and <= 400 in total', async () => {
  const h = await bound({ extraCameras: 30, extraRenderers: 450 });
  const rec = await h.rpc('mvruntime', { part: 'frame', budget: { soft: 1e9, hard: 1e9 } });
  assert.ok(rec.cameras.length <= 16);
  assert.ok(rec.cameras.filter(c => !c.summaryOnly).length <= 8);
  const records = await runPart(h, 'renderers', { budget: { soft: 1e9, hard: 1e9 } }, 40);
  const all = records.flatMap(r => r.renderers);
  assert.ok(records.every(r => r.renderers.length <= 24));
  assert.equal(all.length, 400);
  assert.equal(records[records.length - 1].next, null);
  assertClean(h.world);
});

test('records validate through rtdump_codec.py (schema, column-major projection)', async () => {
  const h = await bound();
  const records = [];
  let seq = 0;
  const frame = await h.rpc('mvruntime', { part: 'frame' });
  records.push(Object.assign(frame, { id: 'f0001', seq: ++seq }));
  for (const part of ['census', 'quality', 'renderers']) {
    const rec = await h.rpc('mvruntime', { part, cursor: {} });
    records.push(Object.assign(rec, { id: `p0-${part}-00`, seq: ++seq, pass: 0, chunk: 0 }));
  }
  const doc = { schema: 'sifas-mv-runtime-dump/1', side: 'game', header: { createdAt: '2026-11-23T00:00:00Z', producer: { name: 'qa-mvdump' },
    conventions: { space: 'unity-lh', matrixLayout: 'column-major', angles: 'degrees', quaternion: 'xyzw', color: 'raw', time: 'director-seconds' } },
  records, trailer: {} };
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'mvdump-doc-')), 'doc.json');
  fs.writeFileSync(file, JSON.stringify(doc));
  const res = spawnSync('python3', [path.join(__dirname, '..', 'rtdump_codec.py'), 'verify', file], { encoding: 'utf8' });
  assert.equal(res.status, 0, res.stdout + res.stderr);
  assert.deepEqual(JSON.parse(res.stdout).problems, []);
});

test('budget: camera census, correctors and cameras are read even far past the hard budget', async () => {
  const h = await bound({ costPerCall: 5, extraCameras: 6 });
  const rec = await h.rpc('mvruntime', { part: 'frame', budget: { soft: 60, hard: 150 }, keys: { globals: h.world.keys.globals } });
  assertClean(h.world);
  assert.ok(rec.cost.elapsedMs > 150, 'the fake device is slower than the hard budget');
  const main = rec.cameras.find(c => c.role === 'main');
  assert.ok(main && !main.summaryOnly && main.projection && main.worldToCamera, 'main camera fully detailed');
  assert.equal(rec.cameras[0].role, 'main');
  assert.ok(rec.cameras.length >= 8, 'every active camera is listed');
  assert.ok(rec.cameras.slice(1).every(c => c.summaryOnly && typeof c.fieldOfView === 'number'), 'later cameras degrade to summary-only');
  assert.equal(rec.correctors[0].key, 'corrector:camera:main');
  assert.equal(rec.correctors[0].correction, 1);
  for (const s of ['cameraCensus', 'correctors', 'cameras', 'directors', 'clock', 'scene', 'clockEnd']) assert.ok(!rec.cost.truncatedSections.includes(s), s + ' never cut');
  assert.ok(rec.cost.truncatedSections.includes('globals') && rec.cost.truncatedSections.includes('lights'), JSON.stringify(rec.cost.truncatedSections));
});

test('budget: materials check the hard budget only after the first complete material; the cut one is retried', async () => {
  const h = await bound({ extraRenderers: 3 });
  for (let chunk = 0; chunk < 6; chunk++) if ((await h.rpc('mvruntimeprobe', { chunk })).done) break;
  const renderers = (await runPart(h, 'renderers', {})).flatMap(r => r.renderers);
  const wanted = materialRequests(renderers);
  assert.ok(wanted.length >= 3, 'three distinct materials');
  h.world.costPerCall = 20;
  const budget = { soft: 80, hard: 200 }, shaders = h.world.keys.shaders;
  const first = await h.rpc('mvruntime', { part: 'materials', materials: wanted.slice(0, 8), shaders, budget });
  assertClean(h.world);
  assert.ok(first.cost.elapsedMs > budget.hard, 'the first material alone exceeds the hard budget');
  assert.equal(first.processed, 1);
  assert.equal(first.materials.length, 1);
  const m0 = first.materials[0];
  assert.ok(!m0.incomplete && !m0.missingObject, JSON.stringify(m0));
  const expected = Object.keys(shaders[m0.shader] || {}).length;
  assert.equal(Object.keys(m0.properties).length + m0.missing.length, expected, 'every property of the first material was read');
  const second = await h.rpc('mvruntime', { part: 'materials', materials: wanted.slice(1, 9), shaders, budget });
  assert.equal(second.materials[0].instanceId, wanted[1].instanceId, 'the next chunk starts at the next material');
  assert.ok(!second.materials[0].incomplete);
  // Two materials fit a generous budget; a later one cut at the hard budget is dropped, not half-recorded.
  h.world.costPerCall = 1;
  const mixed = await h.rpc('mvruntime', { part: 'materials', materials: wanted.slice(0, 8), shaders, budget: { soft: 1e9, hard: 30 } });
  assert.ok(mixed.materials.every(m => !m.incomplete), 'no incomplete material is ever recorded');
  assert.equal(mixed.materials.length, mixed.processed);
});

test('materials: a renderer slot that no longer resolves falls back to one Material scan', async () => {
  const h = await bound();
  const renderers = (await runPart(h, 'renderers', {})).flatMap(r => r.renderers);
  const wanted = materialRequests(renderers).map((w, i) => i === 0 ? Object.assign({}, w, { resolve: [{ path: '/EntryPoint/Gone/Renderer', slot: 0 }] }) : w);
  const before = h.world.findAllTypes.length;
  const rec = await h.rpc('mvruntime', { part: 'materials', materials: wanted, shaders: h.world.keys.shaders });
  assertClean(h.world);
  assert.equal(rec.materials[0].resolvedBy, 'scan');
  assert.ok(rec.materials.slice(1).every(m => m.resolvedBy === 'renderer'));
  assert.equal(h.world.findAllTypes.slice(before).filter(n => n === 'UnityEngine.Material').length, 1, 'one scan per chunk at most');
  assert.deepEqual(rec.resolution, { renderer: wanted.length - 1, scan: 1, missing: 0 });
});

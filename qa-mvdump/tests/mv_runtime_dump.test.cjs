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
  'UnityEngine.GameObject::get_layer', 'UnityEngine.GameObject::GetComponents', 'UnityEngine.GameObject::GetComponentsInChildren',
  // Engine icalls of stripped managed wrappers (resolved by name, getters only).
  ...['get_fog', 'get_fogMode', 'get_fogColor_Injected', 'get_fogDensity', 'get_fogStartDistance', 'get_fogEndDistance', 'get_ambientMode',
    'get_ambientSkyColor_Injected', 'get_ambientEquatorColor_Injected', 'get_ambientGroundColor_Injected', 'get_ambientIntensity',
    'get_ambientLight_Injected', 'get_reflectionIntensity'].map(n => 'UnityEngine.RenderSettings::' + n),
  'UnityEngine.Renderer::HasPropertyBlock',
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
  ...['get_isPlaying', 'get_isEmitting', 'get_isPaused', 'get_particleCount', 'get_time', 'get_randomSeed', 'get_useAutoRandomSeed',
    'get_isStopped', 'get_duration', 'get_playbackSpeed', 'get_automaticCullingEnabled'].map(n => 'UnityEngine.ParticleSystem::' + n)
]);
const FULL_PARTS = ['timeline', 'census', 'quality', 'fovmodNative', 'renderers', 'materials', 'lightingRefs', 'members', 'springs', 'stageNodes', 'particles', 'post'];

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
  for (const key of ['Camera', 'PlayableDirector', 'LiveDirector', 'CameraAspectCorrector', 'LiveCoreCameraWork', 'LiveMusicMachine', 'BodyPartManager', 'SwingBoneManager',
    'LiveQualitySettingVO', 'MemberSpotLightShaft', 'LiveCoreCameraPostProcess', 'LiveCoreCameraPostProcessFlare'])
    assert.ok(found.includes(key), key + ' found');
  assert.equal(classes.find(c => c.key === 'MemberSpotLightShaft').fullName, 'LLAS.Scene.Live.Components.LiveCoreMemberSpotLightShaft');
  for (const key of ['LiveSplitScreenEffect', 'LiveMvScene', 'Light']) assert.ok(missing.includes(key), key + ' missing');
  assert.equal(chunks.length, classes.length > 0 ? Math.ceil(h.ctx.QA_MVDUMP_EXT.classTable.length / 8) : 0, 'the sampler probes every class within PROBE_CHUNKS');
  assert.ok(chunks.length <= 6);
  // Icall names are resolved (not called) in chunk 0.
  assert.equal(chunks[0].icalls['UnityEngine.RenderSettings::get_fog'], false, 'not registered in the GL client');
  assert.equal(chunks[0].icalls['UnityEngine.Renderer::HasPropertyBlock'], false);
  assert.ok(!h.world.invocations.some(i => i.icall), 'the probe resolves icall names without calling them');
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
  // The stage origin anchor resolves although GameObject.Find("/EntryPoint") returns the PopupView root.
  close(rec.anchors.find(a => a.key === 'anchor:stageOrigin').position, [0, 0, 0], 1e-9, 'stage origin');
  // GL 3.12.0: RenderSettings and Light are stripped and their engine icalls are not registered: both
  // are reported unavailable once, without a call and without per-getter errors.
  assert.equal(rec.renderSettings, null);
  assert.match(rec.unavailable.renderSettings, /RenderSettings: engine icall not registered/);
  assert.equal(rec.lights, null);
  assert.match(rec.unavailable.lights, /UnityEngine\.Light .*stripped/);
  assert.ok(!h.world.invocations.some(i => i.icall), 'no icall is called when none resolves');
  // Post values per frame: LiveCoreCamera.postProcess -> PostProcessingBehaviour.profile.
  assert.equal(rec.post.key, 'post:/EntryPoint/Live/Cameras/MainCamera');
  assert.equal(rec.post.enablePostEffect, true);
  assert.deepEqual(rec.post.dof, { enabled: true, focusDistance: 4.25, aperture: 35, focalLength: 50, useCameraFov: false, kernelSize: 1, antiAura: true });
  assert.equal(rec.post.bloom.enabled, true);
  close([rec.post.bloom.intensity, rec.post.bloom.threshold, rec.post.bloom.lensDirtIntensity], [0.6, 0.9, 0.25], 1e-6, 'bloom');
  assert.equal(rec.post.bloom.lensDirtTexture, 'lens_dirt');
  assert.equal(rec.post.flare.enabled, false);
  assert.equal(rec.post.flare.settings.length, 2);
  close(rec.post.flare.settings[1].center, [0.5, 0.6], 1e-6, 'flare center');
  assert.equal(rec.post.flare.settings[1].rounded, true);
  assert.deepEqual(rec.post.flares.map(f => [f.index, f.enablePostEffect, f.enabled, f.flare.enabled]), [[0, true, true, true]]);
  assert.equal(rec.faces, undefined, 'no face renderers until the host sends them');
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
  // Timeline: CustomControl clip windows with their prefabs; the grouped activation track; others counted only.
  const tl = out.timeline[0].timeline;
  assert.equal(tl.asset, 'so2035_timeline');
  assert.equal(tl.trackCount, 10);
  // Parent indices: a track's parent is its group's index, also for every sibling after the first
  // (stage 0: main_01_act 1, Expert 2, main_02_act 7; Expert: Control 3; Control: Particle 4, Floor 5, Light 6).
  assert.deepEqual(tl.tracks.filter(t => t.class === 'UnityEngine.Timeline.ActivationTrack').map(t => [t.name, t.index, t.depth, t.parent]),
    [['main_01_act', 1, 1, 0], ['Particle', 4, 3, 3], ['Floor', 5, 3, 3], ['Light', 6, 3, 3], ['main_02_act', 7, 1, 0]]);
  const cc = tl.tracks.find(t => t.class === 'LLAS.Components.Timeline.CustomControlTrack');
  assert.deepEqual(cc.clips.map(c => [c.start, c.duration, c.prefab, c.assetClass]),
    [[36.9, 8.2, 'fx_flo_so2035_02', 'LLAS.Components.Timeline.CustomControlClip'], [73.9, 4.9, 'fx_par_so2035_03', 'LLAS.Components.Timeline.CustomControlClip']]);
  const act = tl.tracks.find(t => t.class === 'UnityEngine.Timeline.ActivationTrack');
  assert.deepEqual([act.name, act.depth, act.clips[0].name], ['main_01_act', 1, 'Active']);
  assert.ok(!tl.tracks.some(t => /AnimationTrack|GroupTrack/.test(t.class)));
  // Census: the live root (the LiveDirector's), not the PopupView root GameObject.Find returns; self-check ok.
  const self = out.census[0].census.selfCheck;
  assert.equal(self.ok, true, JSON.stringify(self));
  assert.equal(self.live.inLiveDirectorRoot, true);
  assert.equal(self.live.holdsLiveDirector, true);
  assert.equal(self.live.isLiveDirector, false, 'the fake LiveDirector sits on /EntryPoint/Live/Director');
  assert.equal(self.findReturnedOtherRoot, true);
  assert.deepEqual(self.roots.map(r => r.source), ['LiveDirector', 'GameObject.Find']);
  assert.equal(self.liveDirector, '/EntryPoint/Live/Director');
  const census = out.census.flatMap(r => r.census.nodes);
  assert.equal(census[0].path, '/EntryPoint');
  assert.equal(census[1].path, '/EntryPoint/Live', 'the live root is walked first');
  assert.ok(census.some(n => n.path === '/EntryPoint/PopupView' && n.rootIndex === 1), 'the other same-name root is listed after it');
  const skill = census.find(n => n.path === '/EntryPoint/SkillCutin');
  assert.equal(skill.skipped, 'no skill cut-in playing');
  assert.ok(!census.some(n => n.path.startsWith('/EntryPoint/SkillCutin/')), 'no node below the skipped cut-in subtree');
  assert.deepEqual(census.find(n => n.path === '/Directional Light' || n.path === '/EntryPoint/Directional Light').components,
    ['UnityEngine.Transform', 'UnityEngine.Behaviour'], 'a stripped component class shows as its kept base class');
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
  assert.ok(!renderers.some(r => r.path.startsWith('/EntryPoint/SkillCutin/')), 'cut-in renderers skipped while no cut-in plays');
  assert.deepEqual(out.renderers[0].deferred, { roots: ['/EntryPoint/SkillCutin'], components: 3, skipped: true, reason: 'no skill cut-in playing',
    cutin: ['cutinOverlayCamera:off', '/EntryPoint/SkillCutin camera:off'] });
  assert.ok(!('hasPropertyBlock' in ground), 'HasPropertyBlock is not registered in the GL client');
  assert.match(out.renderers[0].unavailable.hasPropertyBlock, /HasPropertyBlock: engine icall not registered/);
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
  const combine = member.blendShapes.find(b => /\/CombineFace$/.test(b.rendererKey));
  assert.equal(combine.count, 4);
  assert.deepEqual(Object.keys(combine.channels), ['EyeBlendShape.eye_facial_002', 'EyeBlendShape.eye_facial_003_006_011', 'MouthBlendShape.mouth_facial_004', 'MouthBlendShape.mouth_facial_001'],
    'every CombineFace channel, zeros included');
  assert.equal(combine.channels['MouthBlendShape.mouth_facial_001'], 0);
  assert.ok(!('MouthBlendShape.mouth_facial_001' in combine.weights), 'weights keeps the non-zero ones');
  close([combine.weights['MouthBlendShape.mouth_facial_004']], [35.8], 1e-5, 'mouth 004');
  assert.ok(/\(Clone\)/.test(combine.rawPath), 'raw path for the frame face reads');
  assert.deepEqual(out.members[0].spotLights.map(s => [s.class, s.fields.currentDrawIndex.v]), [['LLAS.Scene.Live.Components.LiveCoreMemberSpotLightShaft', 1]]);
  const spring = out.springs[0].springs[0];
  assert.equal(spring.boneField, 'swingBones');
  assert.equal(spring.bones.length, 2);
  assert.ok(spring.bones[1].fields.currentTipPosition.v.every(Number.isFinite));
  const nodes = out.stageNodes.flatMap(r => r.stageNodes);
  assert.ok(nodes.some(n => n.relPath === 'litC_04_All/litC_04_Yrot_Ani/litC_04_handle'));
  assert.ok(nodes.some(n => n.binding.endsWith('/dis_01/main_01') && n.relPath === '' && n.activeSelf === false), 'inactive binding still found (Transform.Find)');
  assert.ok(nodes.some(n => n.missing && n.binding.endsWith('/fx_stg_so2035_02/root')));
  const particles = out.particles.flatMap(r => r.particles);
  assert.deepEqual(particles.map(p => [p.key, p.particleCount, p.rendererEnabled]).sort(), [
    ['particles:/EntryPoint/Live/Stages/MainStage/Effect/fx_par_so2035_01/par_01', 37, true],
    ['particles:/fx_flo_so2035_02 [Timeline]/root/flower_01', 37, true],
    ['particles:/fx_flo_so2035_02 [Timeline]/root/flower_02', 37, true]]);
  assert.deepEqual(Object.keys(particles[0]).filter(k => ['isStopped', 'duration', 'simulationSpeed', 'automaticCullingEnabled', 'rendererVisible'].includes(k)).length, 5);
  assert.equal(particles[0].duration, 5);
  assert.equal(out.particles[0].deferred.skipped, true);
  const post = out.post[0].post;
  assert.equal(post.enablePostEffect, true, 'LiveCoreCameraPostProcess.enablePostEffect');
  assert.equal(post.dof.focusDistance, 4.25);
  assert.equal(post.source, 'post:/EntryPoint/Live/Cameras/MainCamera');
  const holder = post.holders.find(x => x.class.endsWith('LiveCoreCamera'));
  assert.equal(holder.postProcess.profile.source, 'PostProcessingBehaviour.profile');
  assert.equal(holder.postProcess.profile.sameAsPostProcessProfile, true);
  assert.equal(holder.postProcess.behaviour.Enabled, true);
  assert.ok(post.holders.some(x => x.class === 'UnityEngine.PostProcessing.PostProcessingBehaviour'), 'camera components through GameObject.GetComponents');
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
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mvdump-doc-'));
  try {
    const file = path.join(dir, 'doc.json');
    fs.writeFileSync(file, JSON.stringify(doc));
    const res = spawnSync('python3', ['-B', path.join(__dirname, '..', 'rtdump_codec.py'), 'verify', file], { encoding: 'utf8' });
    assert.equal(res.status, 0, res.stdout + res.stderr);
    assert.deepEqual(JSON.parse(res.stdout).problems, []);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
  assert.ok(!fs.existsSync(dir), 'the temporary document folder is removed');
});

test('a bundle the harness builds (no MVDUMP_BUNDLE) is removed when its process exits', () => {
  const env = Object.assign({}, process.env);
  delete env.MVDUMP_BUNDLE;
  const res = spawnSync(process.execPath, ['-e', 'const fs = require("fs"), p = require(process.argv[1]).bundlePath(); console.log(JSON.stringify([p, fs.statSync(p).size]));',
    path.join(__dirname, 'fake_il2cpp.cjs')], { env, encoding: 'utf8' });
  assert.equal(res.status, 0, res.stderr);
  const [built, size] = JSON.parse(res.stdout);
  assert.ok(/mvdump-bundle-/.test(built) && size > 0, built);
  assert.ok(!fs.existsSync(path.dirname(built)), 'the build folder is gone after the process exits');
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

test('skill cut-in playing: its subtree is kept, sorted after the stage (phase 1), and the census descends into it', async () => {
  const h = await bound({ cutinPlaying: true });
  const renderers = await runPart(h, 'renderers', {});
  assertClean(h.world);
  const all = renderers.flatMap(r => r.renderers);
  const firstSkill = all.findIndex(r => r.path.startsWith('/EntryPoint/SkillCutin/'));
  assert.ok(firstSkill > 0, 'cut-in renderers are listed');
  assert.ok(all.slice(firstSkill).every(r => r.path.startsWith('/EntryPoint/SkillCutin/')), 'and only after every other renderer');
  assert.equal(renderers[0].deferred.skipped, false);
  assert.equal(renderers[0].deferred.reason, 'sorted last');
  assert.deepEqual(renderers[0].deferred.cutin, ['cutinOverlayCamera:on', '/EntryPoint/SkillCutin camera:on']);
  const census = (await runPart(h, 'census', {})).flatMap(r => r.census.nodes);
  assert.ok(census.some(n => n.path === '/EntryPoint/SkillCutin/Player'), 'census descends while a cut-in plays');
  assert.equal(census.find(n => n.path === '/EntryPoint/SkillCutin').skipped, undefined);
  const particles = (await runPart(h, 'particles', {})).flatMap(r => r.particles);
  assert.equal(particles.filter(p => p.path.startsWith('/EntryPoint/SkillCutin/')).length, 3);
  assert.ok(particles.findIndex(p => p.path.startsWith('/EntryPoint/SkillCutin/')) >= 3, 'cut-in systems last');
});

test('without a camera manager (no cut-in evidence) the deferred subtree is kept, sorted last', async () => {
  const h = await bound();
  // No cut-in camera to look at (manager field and the cut-in Camera destroyed): kept, sorted last.
  h.world.destroy(h.world.objects.cutinOverlay);
  h.world.destroy(h.world.objects.cutCamera);
  const records = await runPart(h, 'particles', {});
  assertClean(h.world);
  assert.equal(records[0].deferred.skipped, false);
  assert.equal(records.flatMap(r => r.particles).filter(p => p.path.startsWith('/EntryPoint/SkillCutin/')).length, 3);
});

test('particles window mode: only the systems under the named "<prefab> [Timeline]" roots, with cursor', async () => {
  const h = await bound();
  const rec = await h.rpc('mvruntime', { part: 'particles', roots: ['fx_flo_so2035_02 [Timeline]', 'fx_par_so2035_03 [Timeline]'], cursor: {} });
  assertClean(h.world);
  assert.deepEqual(rec.roots, [{ path: '/fx_flo_so2035_02 [Timeline]', found: true }, { path: '/fx_par_so2035_03 [Timeline]', found: false }]);
  assert.deepEqual(rec.particles.map(p => p.key).sort(), ['particles:/fx_flo_so2035_02 [Timeline]/root/flower_01', 'particles:/fx_flo_so2035_02 [Timeline]/root/flower_02']);
  assert.equal(rec.systems, 2);
  assert.equal(rec.next, null);
  // The missing fx_par root costs one ParticleSystem enumeration (the root-name fallback), which finds nothing.
  assert.deepEqual(rec.scan, { by: 'ParticleSystem root name', systems: rec.scan.systems, active: rec.scan.active, matched: 0, truncated: false });
  assert.equal(h.world.findAllTypes.filter(n => n === 'UnityEngine.ParticleSystem').length, 1);
  const before = h.world.findAllTypes.length;
  const only = await h.rpc('mvruntime', { part: 'particles', roots: ['fx_flo_so2035_02 [Timeline]'], cursor: {} });
  assert.equal(only.particles.length, 2);
  assert.equal(only.scan, undefined);
  assert.ok(!h.world.findAllTypes.slice(before).includes('UnityEngine.ParticleSystem'), 'no FindObjectsOfTypeAll(ParticleSystem) when every root resolves');
});

test('particles window mode: a root GameObject.Find misses is found by the systems\' root name, resumable', async () => {
  const h = await bound({ findMissesTimeline: true });
  const rec = await h.rpc('mvruntime', { part: 'particles', roots: ['fx_flo_so2035_02 [Timeline]', 'fx_par_so2035_03 [Timeline]'], cursor: {} });
  assertClean(h.world);
  assert.deepEqual(rec.roots, [{ path: '/fx_flo_so2035_02 [Timeline]', found: true, via: 'ParticleSystem root name', systems: 2 },
    { path: '/fx_par_so2035_03 [Timeline]', found: false }]);
  assert.deepEqual(rec.particles.map(p => p.key).sort(), ['particles:/fx_flo_so2035_02 [Timeline]/root/flower_01', 'particles:/fx_flo_so2035_02 [Timeline]/root/flower_02']);
  assert.equal(rec.scan.matched, 2);
  assert.equal(rec.scan.truncated, false);
  assert.ok(rec.scan.active < rec.scan.systems, 'deferred (skill cut-in) and inactive systems are skipped before their path is read');
  assert.equal(h.world.findAllTypes.filter(n => n === 'UnityEngine.ParticleSystem').length, 1, 'one enumeration per chunk');
  // The skill cut-in systems are never path-read by the scan (deferred subtree).
  assert.ok(!rec.particles.some(p => p.path.startsWith('/EntryPoint/SkillCutin/')));
  // Resume after the first system: only the second one.
  const ids = rec.particles.map(p => p.instanceId).sort((a, b) => a - b);
  const next = await h.rpc('mvruntime', { part: 'particles', roots: ['fx_flo_so2035_02 [Timeline]'], cursor: { afterInstanceId: ids[0] } });
  assert.deepEqual(next.particles.map(p => p.instanceId), [ids[1]]);
  assert.equal(next.next, null);
});

test('frame faces: the host-sent face renderers give per-channel weights every frame (names read once)', async () => {
  const h = await bound();
  const members = await runPart(h, 'members', { keys: { member: h.world.keys.member } });
  const faces = members[0].members[0].blendShapes.filter(b => b.count > 0).map(b => ({ slot: 1, key: b.rendererKey, path: b.rawPath || b.path }));
  assert.equal(faces.length, 2);
  const first = await h.rpc('mvruntime', { part: 'frame', faces });
  const namesBefore = h.world.invocations.filter(i => i.name === 'GetBlendShapeName').length;
  const second = await h.rpc('mvruntime', { part: 'frame', faces });
  assertClean(h.world);
  assert.equal(h.world.invocations.filter(i => i.name === 'GetBlendShapeName').length, namesBefore, 'blend shape names are cached per mesh');
  for (const rec of [first, second]) {
    const face = rec.faces.find(f => /CombineFace$/.test(f.rendererKey));
    assert.equal(face.count, 4);
    assert.deepEqual(Object.keys(face.weights), ['EyeBlendShape.eye_facial_002', 'EyeBlendShape.eye_facial_003_006_011', 'MouthBlendShape.mouth_facial_004']);
    assert.equal(face.enabled, true);
  }
  const gone = await h.rpc('mvruntime', { part: 'frame', faces: [{ slot: 1, key: 'renderer:/x', path: '/EntryPoint/Live/Members/Member9/Face' }] });
  assert.deepEqual(gone.faces, [{ slot: 1, rendererKey: 'renderer:/x', missing: true }]);
});

test('frame post follows the DOF track: focus distance read per frame', async () => {
  const h = await bound();
  const a = await h.rpc('mvruntime', { part: 'frame' });
  h.world.setDof(9.5);
  const b = await h.rpc('mvruntime', { part: 'frame' });
  assert.equal(a.post.dof.focusDistance, 4.25);
  assert.equal(b.post.dof.focusDistance, 9.5);
  assertClean(h.world);
});

test('a client that registers the icalls: RenderSettings and HasPropertyBlock are read through them', async () => {
  const h = await bound({ icallsRegistered: true });
  const rec = await h.rpc('mvruntime', { part: 'frame' });
  assertClean(h.world);
  assert.equal(rec.renderSettings.source, 'icall');
  assert.equal(rec.renderSettings.fogMode.n, 'ExponentialSquared');
  assert.equal(rec.renderSettings.fog, false);
  close(rec.renderSettings.ambientEquatorColor, [0.11, 0.13, 0.13, 1], 1e-6, 'ambientEquatorColor');
  assert.equal(rec.renderSettings.ambientIntensity, 1);
  assert.equal(rec.unavailable.renderSettings, undefined);
  const renderers = (await runPart(h, 'renderers', {})).flatMap(r => r.renderers);
  assert.equal(renderers.find(r => /\/ground$/.test(r.path)).hasPropertyBlock, true);
  assert.equal(renderers.find(r => r.mesh === 'Body').hasPropertyBlock, false);
  assert.equal(h.world.invocations.filter(i => i.icall && i.name === 'HasPropertyBlock').length, renderers.length, 'one icall per listed renderer');
  assertClean(h.world);
});

test('icalls: allowlisted getters only, resolved by name; an unregistered one is recorded, never called', async () => {
  const h = await bound({ icallsRegistered: true, icallsMissing: ['UnityEngine.RenderSettings::get_fogDensity'] });
  const ext = h.ctx.QA_MVDUMP_EXT, deny = new RegExp(ext.deny);
  for (const name of Object.keys(ext.icalls)) {
    const method = name.split('::')[1];
    assert.match(method, /^get_|^Has[A-Z]/, name);
    assert.ok(!deny.test(method), name + ' not denied');
    assert.ok(ALLOWED.has(name), name + ' in the plan allowlist');
  }
  const rec = await h.rpc('mvruntime', { part: 'frame' });
  assertClean(h.world);
  assert.equal(rec.renderSettings.fogDensity, null);
  assert.ok(rec.errors.some(e => /MVDUMP_ICALL_UNAVAILABLE:UnityEngine.RenderSettings::get_fogDensity/.test(e.error)), JSON.stringify(rec.errors));
  assert.equal(rec.renderSettings.fogEndDistance, 300, 'the other getters still read');
  assert.ok(!h.world.invocations.some(i => i.icall && /^set_/.test(i.name)));
});


test('a client that keeps UnityEngine.Light: lights are read, no unavailable note', async () => {
  const h = await bound({ lightClass: true });
  const rec = await h.rpc('mvruntime', { part: 'frame' });
  assertClean(h.world);
  assert.equal(rec.lights.length, 1);
  assert.equal(rec.lights[0].key, 'light:/EntryPoint/Directional Light');
  assert.equal(rec.unavailable.lights, undefined);
});

test('a third same-name root reached through its camera: census, self-check and renderer slots use it', async () => {
  const h = await bound({ thirdRoot: true });
  const records = await runPart(h, 'census', {});
  assertClean(h.world);
  const self = records[0].census.selfCheck;
  assert.equal(self.ok, true);
  assert.deepEqual(self.roots.map(r => [r.source, r.via]), [['LiveDirector', undefined], ['GameObject.Find', undefined], ['Camera', '/EntryPoint/AlwaysCamera']]);
  assert.deepEqual(records[0].census.roots.map(r => r.source), ['LiveDirector', 'GameObject.Find', 'Camera']);
  const nodes = records.flatMap(r => r.census.nodes);
  assert.deepEqual(nodes.filter(n => n.rootIndex === 2).map(n => n.path), ['/EntryPoint', '/EntryPoint/AlwaysCamera', '/EntryPoint/DarkFilterField']);
  assert.ok(records.slice(1).every(r => typeof r.cursor.rootId === 'number'), 'later chunks resume by root instanceId');
  // Materials: live-root slots resolve without looking further; the DarkFilterField slot through the camera's root.
  const renderers = (await runPart(h, 'renderers', {})).flatMap(r => r.renderers);
  const wanted = materialRequests(renderers), dark = wanted.find(w => w.usedBy.some(u => /DarkFilterField/.test(u)));
  assert.ok(dark, 'the renderers part lists the third root\'s renderer');
  const live = wanted.filter(w => w !== dark).slice(0, 8);
  let before = h.world.findAllTypes.length;
  const a = await h.rpc('mvruntime', { part: 'materials', materials: live, shaders: h.world.keys.shaders });
  assert.ok(a.materials.every(m => m.resolvedBy === 'renderer'));
  assert.ok(!h.world.findAllTypes.slice(before).includes('UnityEngine.Camera'), 'no camera enumeration while the first two roots resolve');
  before = h.world.findAllTypes.length;
  const b = await h.rpc('mvruntime', { part: 'materials', materials: [dark], shaders: h.world.keys.shaders });
  assertClean(h.world);
  assert.deepEqual([b.materials[0].name, b.materials[0].resolvedBy], ['dark_filter_mt', 'renderer']);
  assert.ok(!h.world.findAllTypes.slice(before).includes('UnityEngine.Material'), 'no Material scan');
});

test('census: a resumed root that is gone is noted as rootGone and the walk goes on with the next root', async () => {
  const budget = { soft: 0, hard: 1e9 };   // one node per chunk
  // Walk the census; drop(rec) may destroy a camera between chunks and returns true once it did.
  async function census(drop) {
    const h = await bound({ thirdRoot: true, fourthRoot: true }), records = [];
    let cursor = {}, dropped = null;
    for (let chunk = 0; chunk < 400; chunk++) {
      const rec = await h.rpc('mvruntime', { part: 'census', cursor, budget });
      records.push(rec);
      if (!rec.next) break;
      if (dropped === null && drop(h, rec)) dropped = rec.next.rootId;
      cursor = rec.next;
    }
    assertClean(h.world);
    assert.equal(records[records.length - 1].next, null, 'the census terminates');
    return { records, dropped, nodes: records.flatMap(r => r.census.nodes) };
  }
  const byRoot = (nodes, k) => nodes.filter(n => (n.rootIndex || 0) === k).map(n => n.path);
  const ref = await census(() => false);
  assert.deepEqual(ref.records[0].census.roots.map(r => [r.source, r.via]), [['LiveDirector', undefined], ['GameObject.Find', undefined],
    ['Camera', '/EntryPoint/AlwaysCamera'], ['Camera', '/EntryPoint/MarginCoverCamera']]);
  assert.deepEqual(byRoot(ref.nodes, 2), ['/EntryPoint', '/EntryPoint/AlwaysCamera', '/EntryPoint/DarkFilterField']);
  assert.deepEqual(byRoot(ref.nodes, 3), ['/EntryPoint', '/EntryPoint/MarginCoverCamera', '/EntryPoint/MarginCover']);
  assert.ok(ref.records.every(r => r.census.rootGone === undefined));
  // AlwaysCamera goes away while its root is half walked: the next chunk notes it and walks MarginCover's root.
  const third = ref.records[0].census.roots[2].instanceId, fourth = ref.records[0].census.roots[3].instanceId;
  const a = await census((h, rec) => rec.next.rootId === third && rec.next.path.length > 0 && (h.world.destroy(h.world.objects.alwaysCamera), true));
  assert.equal(a.dropped, third);
  const noted = a.records.filter(r => r.census.rootGone !== undefined);
  assert.deepEqual(noted.map(r => r.census.rootGone), [third]);
  assert.deepEqual(noted[0].census.roots.map(r => r.via), [undefined, undefined, '/EntryPoint/MarginCoverCamera']);
  assert.deepEqual(noted[0].census.nodes.map(n => [n.path, n.rootIndex]), [['/EntryPoint', 2]], 'the same chunk walks the next root');
  assert.equal(noted[0].next.rootId, fourth);
  assert.ok(noted[0].next.walked.includes(third), 'the gone root counts as walked');
  for (const k of [0, 1]) assert.deepEqual(byRoot(a.nodes, k), byRoot(ref.nodes, k), 'roots already walked are not walked again');
  assert.deepEqual(byRoot(a.nodes, 2), ['/EntryPoint', '/EntryPoint', '/EntryPoint/MarginCoverCamera', '/EntryPoint/MarginCover']);
  // The last root goes away: rootGone, nothing left to walk, the census ends.
  const b = await census((h, rec) => rec.next.rootId === fourth && rec.next.path.length > 0 && (h.world.destroy(h.world.objects.marginCamera), true));
  const last = b.records[b.records.length - 1];
  assert.deepEqual([last.census.rootGone, last.census.nodes, last.next], [fourth, [], null]);
  assert.deepEqual(byRoot(b.nodes, 2), byRoot(ref.nodes, 2));
  assert.deepEqual(byRoot(b.nodes, 3), ['/EntryPoint']);
});

test('census without the decoy root: one root, same self-check', async () => {
  const h = await bound({ decoyRoot: false });
  const records = await runPart(h, 'census', {});
  assertClean(h.world);
  const self = records[0].census.selfCheck;
  assert.equal(self.ok, true);
  assert.equal(self.findReturnedOtherRoot, false);
  assert.deepEqual(records[0].census.roots.map(r => r.source), ['LiveDirector']);
});

test('caps: the sampler records exactly the agent caps it shares (no stale blendShapes cap)', async () => {
  const h = await bound();
  const caps = h.ctx.QA_MVDUMP_EXT.caps;
  const py = spawnSync('python3', ['-B', '-c', 'import json, sys; sys.path.insert(0, sys.argv[1]); import mvdump_sampler; print(json.dumps(mvdump_sampler.CAPS))',
    path.join(__dirname, '..')], { encoding: 'utf8' });
  assert.equal(py.status, 0, py.stderr);
  const sampler = JSON.parse(py.stdout);
  for (const [key, value] of Object.entries(sampler)) assert.equal(caps[key], value, key);
  assert.ok(!('blendShapes' in caps) && !('blendShapes' in sampler), 'members record every channel; blendShapesInspected bounds the names per mesh');
  assert.equal(caps.blendShapesInspected, 64);
});

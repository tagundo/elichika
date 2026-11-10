/* WKWebView.callAsyncJavaScript function body. `config` is supplied as an argument.
 * QA uses real source GLB/metadata replay; no model export/editing endpoints are called.
 */
const qa = window.__nativeWKDiagnostic;
const report = { status: 'RUNNING', scope: 'QA-only native WKWebView using unchanged product JS and captured real model responses; not shipped AppKit app or user Mac FPS',
  userAgent: navigator.userAgent, devicePixelRatio: devicePixelRatio, viewport: { width: innerWidth, height: innerHeight },
  visualViewport: window.visualViewport ? { width: visualViewport.width, height: visualViewport.height, scale: visualViewport.scale, offsetLeft: visualViewport.offsetLeft, offsetTop: visualViewport.offsetTop } : null,
  fixture: config.fixture || null, shots: [], phases: [], unsupported: [] };
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function wait(label, predicate, timeout = 120000) {
  qa.checkpoint = { label, state: 'waiting', at: performance.now() };
  const start = performance.now();
  while (!predicate()) { if (performance.now() - start > timeout) throw Error('Timeout: ' + label); await delay(100); }
  qa.checkpoint = { label, state: 'ready', at: performance.now() };
}
function input(id, value, type = 'input') {
  const element = document.getElementById(id); if (!element) throw Error('Missing input ' + id);
  element.value = String(value); element.dispatchEvent(new Event(type, { bubbles: true }));
}
async function chooseRegion(regionId, characterId, desired) {
  const region = document.getElementById(regionId), character = document.getElementById(characterId);
  if (region.value === desired) return;
  // Both catalog implementations replace character option children only after
  // accepting the latest response. Old options remaining during fetch are not
  // evidence that the newly selected region has completed its catalog request.
  let observer, timer;
  try {
    await new Promise((resolve, reject) => {
      observer = new MutationObserver(records => {
        if (records.some(record => record.type === 'childList') && region.value === desired && character.options.length > 1) resolve();
      });
      observer.observe(character, { childList: true });
      timer = setTimeout(() => reject(Error('Timeout: new region catalog ' + regionId)), 120000);
      input(regionId, desired, 'change');
    });
  } finally { if (observer) observer.disconnect(); if (timer) clearTimeout(timer); }
}
function pause() { if (qa.rig && qa.rig.getPlaybackState().playing) document.getElementById('viewer-play').click(); }
function play() { if (qa.rig && !qa.rig.getPlaybackState().playing) document.getElementById('viewer-play').click(); }
function seek(time) { pause(); input('viewer-time', time); }
function state() { return ModelViewer.getState(); }
function snapshotNative(name) {
  const bridge = window.webkit && webkit.messageHandlers && webkit.messageHandlers.qaDiagnostic;
  return bridge ? bridge.postMessage({ kind: 'snapshot', name }) : Promise.resolve({ skipped: 'not native diagnostic host' });
}
function runtime() {
  return { camera: qa.camera, renderer: qa.renderer, controls: qa.controls, root: qa.root };
}
function rendererState() {
  const gl = qa.renderer.getContext(), r = state();
  const extension = gl.getExtension('WEBGL_debug_renderer_info');
  return { camera: { near: qa.camera.near, far: qa.camera.far, fov: qa.camera.fov,
      position: qa.camera.position.toArray(), target: qa.controls.target.toArray() },
    devicePixelRatio, cssWidth: qa.renderer.domElement.clientWidth, cssHeight: qa.renderer.domElement.clientHeight,
    canvasWidth: qa.renderer.domElement.width, canvasHeight: qa.renderer.domElement.height,
    drawingWidth: gl.drawingBufferWidth, drawingHeight: gl.drawingBufferHeight,
    contextSamples: gl.getParameter(gl.SAMPLES), contextDepthBits: gl.getParameter(gl.DEPTH_BITS),
    renderer: gl.getParameter(gl.RENDERER), vendor: gl.getParameter(gl.VENDOR), version: gl.getParameter(gl.VERSION),
    unmaskedRenderer: extension ? gl.getParameter(extension.UNMASKED_RENDERER_WEBGL) : null,
    unmaskedVendor: extension ? gl.getParameter(extension.UNMASKED_VENDOR_WEBGL) : null,
    quality: r.quality, physics: r.rig.physics, rigTime: qa.rig.getPlaybackState().time,
    glError: gl.getError(), visible: !document.hidden, stageVisible: r.layout.stageVisible };
}
async function poseSnapshot() {
  const points = [], regions = {}, rect = qa.renderer.domElement.getBoundingClientRect();
  let minimumPositiveDepth = Infinity;
  qa.root.updateMatrixWorld(true); qa.camera.updateMatrixWorld(true);
  qa.rig.getBounds(function (point, mesh) {
    points.push(point.x, point.y, point.z);
    const view = point.clone().applyMatrix4(qa.camera.matrixWorldInverse), depth = -view.z;
    if (depth > 0) minimumPositiveDepth = Math.min(minimumPositiveDepth, depth);
    const name = mesh.name || '(unnamed)';
    const region = regions[name] || (regions[name] = { minDepth: Infinity, maxDepth: -Infinity, left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity });
    region.minDepth = Math.min(region.minDepth, depth); region.maxDepth = Math.max(region.maxDepth, depth);
    if (depth > 0) {
      const screen = point.clone().project(qa.camera), x = rect.left + (screen.x + 1) * rect.width / 2, y = rect.top + (1 - screen.y) * rect.height / 2;
      region.left = Math.min(region.left, x); region.right = Math.max(region.right, x);
      region.top = Math.min(region.top, y); region.bottom = Math.max(region.bottom, y);
    }
  });
  const bytes = new TextEncoder().encode(JSON.stringify(points));
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return { vertices: points.length / 3, worldPositionsSha256: Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join(''),
    minimumPositiveDepth, wouldClipSomePositiveVertices: qa.camera.near > minimumPositiveDepth, regions };
}
await wait('product scripts', () => window.ModelViewer && typeof openModelViewer === 'function' && window.THREE && window.ViewerRig);
await wait('visible native document', () => document.visibilityState === 'visible', 20000);
const originalRenderer = THREE.WebGLRenderer;
THREE.WebGLRenderer = function (...args) { const r = new originalRenderer(...args); qa.renderer = r; return r; };
THREE.WebGLRenderer.prototype = originalRenderer.prototype;
const originalControls = THREE.OrbitControls;
THREE.OrbitControls = function (camera, element) { const c = new originalControls(camera, element); qa.camera = camera; qa.controls = c; return c; };
THREE.OrbitControls.prototype = originalControls.prototype;
const originalRig = ViewerRig.create;
if (window.ViewerPhysics) {
  const originalPhysics = ViewerPhysics.create;
  ViewerPhysics.create = function (...args) { const result = originalPhysics.apply(this, args); qa.physics = result; return result; };
}
ViewerRig.create = function (...args) {
  const r = originalRig.apply(this, args); qa.root = args[0]; qa.info = args[2]; qa.rig = r;
  const update = r.update;
  r.update = function (delta) {
    const begin = performance.now(), previous = r.getPlaybackState().time, value = update.call(this, delta);
    if (qa.recording && qa.updates.length < 30000) qa.updates.push({ phase: qa.phase, at: begin,
      inputDelta: delta, previousRigTime: previous, rigTime: r.getPlaybackState().time,
      workMs: performance.now() - begin, lastAudioClock: qa.lastAudioClock });
    return value;
  };
  return r;
};
if (window.ViewerMotionAudio && ViewerMotionAudio.getPlaybackClock) {
  const getClock = ViewerMotionAudio.getPlaybackClock;
  ViewerMotionAudio.getPlaybackClock = function (...args) {
    const value = getClock.apply(this, args); qa.lastAudioClock = value; return value;
  };
}
const startLoad = performance.now();
if (config.gameImport) {
  // This path uses the exact packaged private backend and normal CDN import UI.
  const game = config.gameImport;
  switchTab('viewer');
  await wait('viewer navigation and game picker ready', () => document.getElementById('tab-viewer').classList.contains('active') &&
    window.GameAssetPicker && document.getElementById('viewer-game-assets').dataset.gameAssetsBound === 'true');
  document.getElementById('viewer-auto-face').checked = true;
  document.getElementById('viewer-game-assets').click();
  await wait('costume characters', () => document.getElementById('viewer-game-character')?.options.length > 1);
  await chooseRegion('viewer-game-region', 'viewer-game-character', game.region || 'gl');
  await wait('selected region character', () => Array.from(document.getElementById('viewer-game-character').options).some(o => o.value === String(game.character || 2)));
  input('viewer-game-character', game.character || 2, 'change');
  await wait('costume choice', () => Array.from(document.getElementById('viewer-game-costume').options).some(o => o.value === (game.costume || 'suit:400022007')));
  input('viewer-game-costume', game.costume || 'suit:400022007', 'change');
  document.getElementById('viewer-game-reimport').checked = true;
  document.getElementById('viewer-game-import').click();
  await wait('actual CDN costume', () => !document.getElementById('viewer-game-assets-dialog').open && !state().loading && state().loaded, 240000);
  qa.homeClip = state().rig.selectedClip;
  report.initialCostumePhysics = { clip: qa.homeClip, physics: state().rig.physics };
  document.getElementById('viewer-adjustments').open = true;
  document.getElementById('viewer-game-motions').click();
  await wait('motion characters', () => document.getElementById('viewer-motion-character')?.options.length > 1);
  await chooseRegion('viewer-motion-region', 'viewer-motion-character', game.region || 'gl');
  await wait('selected motion character', () => Array.from(document.getElementById('viewer-motion-character').options).some(o => o.value === String(game.character || 2)));
  input('viewer-motion-character', game.character || 2, 'change');
  input('viewer-motion-category', 'mv', 'change');
  input('viewer-motion-search', game.search || 'CHASE');
  await wait('dance motion choice', () => Array.from(document.getElementById('viewer-game-motion-choice').options).some(o => o.value === (game.motion || 'mv:12008:1200801')));
  input('viewer-game-motion-choice', game.motion || 'mv:12008:1200801', 'change');
  await wait('performer choice', () => Array.from(document.getElementById('viewer-motion-performer').options).some(o => o.value === String(game.performer || 1)));
  input('viewer-motion-performer', game.performer || 1, 'change');
  document.getElementById('viewer-motion-linked-audio').checked = true;
  document.getElementById('viewer-motion-import').click();
  await wait('actual CDN dance model', () => !document.getElementById('viewer-game-motions-dialog').open && !state().loading && state().loaded && state().rig.selectedClip.startsWith('game-timeline:mv:'), 240000);
} else {
  const modelPaths = config.modelPaths;
  if (!Array.isArray(modelPaths) || !modelPaths.length) throw Error('config.modelPaths or config.gameImport is required');
  await openModelViewer(modelPaths);
  await wait('real model', () => !state().loading && state().loaded);
}
report.loadMs = performance.now() - startLoad;
const select = document.getElementById('viewer-motion');
const choice = config.clipName || Array.from(select.options).find(option => option.value.startsWith('game-timeline:mv:'))?.value;
if (!choice || !Array.from(select.options).some(option => option.value === choice)) throw Error('Prepared fixture has no requested dance timeline');
input('viewer-motion', choice, 'change');
pause();
const quality = document.getElementById('viewer-high-quality');
if (!quality.checked) { quality.checked = true; quality.dispatchEvent(new Event('change', { bubbles: true })); }
await wait('HQ actual multisampling', () => state().quality.enabled && state().quality.actualSamples >= 2);
document.getElementById('viewer-stage').scrollIntoView({ block: 'center' });
await delay(500);
report.loaded = { sourceNames: state().loadedPaths, clip: choice, stats: state().stats,
  quality: state().quality, physics: state().rig.physics, renderer: rendererState() };
const initialCamera = { position: qa.camera.position.clone(), target: qa.controls.target.clone(), up: qa.camera.up.clone(), near: qa.camera.near, far: qa.camera.far,
  enableDamping: qa.controls.enableDamping };
const baseDirection = initialCamera.position.clone().sub(initialCamera.target).normalize();
for (const shot of config.shots || []) {
  seek(shot.time === undefined ? 58.5 : shot.time);
  qa.controls.enableDamping = false;
  let target = new THREE.Vector3().fromArray(shot.target || initialCamera.target.toArray());
  let direction = shot.direction ? new THREE.Vector3().fromArray(shot.direction).normalize() : baseDirection;
  if (shot.headRelative) {
    qa.root.updateMatrixWorld(true);
    let mouth, eye;
    qa.root.traverse(object => { const name = object.userData.originalName || object.name;
      if (object.isMesh && !object.userData.viewerHelper && name === 'Mouth') mouth = object;
      if (name === 'Eye_Root') eye = object;
    });
    if (!mouth || !eye) throw Error('Original Mouth/Eye_Root is missing from diagnostic source');
    target = new THREE.Vector3();
    for (let i = 0; i < mouth.geometry.attributes.position.count; i++) target.add(ViewerMeshRuntime.vertexWorld(mouth, i));
    target.divideScalar(mouth.geometry.attributes.position.count);
    const q = new THREE.Quaternion(), chain = [];
    for (let object = eye; object; object = object.parent) chain.push(object);
    for (let i = chain.length - 1; i >= 0; i--) q.multiply(chain[i].quaternion);
    direction = new THREE.Vector3(0, 0, 1).applyQuaternion(q);
    qa.camera.up.copy(new THREE.Vector3(0, 1, 0).applyQuaternion(q));
  }
  const distance = shot.distance === undefined ? initialCamera.position.distanceTo(initialCamera.target) : shot.distance;
  qa.controls.target.copy(target); qa.camera.position.copy(target).addScaledVector(direction, distance);
  qa.camera.near = shot.near === undefined ? initialCamera.near : shot.near;
  qa.camera.far = shot.far === undefined ? initialCamera.far : shot.far;
  qa.camera.updateProjectionMatrix(); qa.controls.update(); qa.controls.dispatchEvent({ type: 'change' });
  await delay(150);
  const before = rendererState();
  const pose = await poseSnapshot();
  const image = await snapshotNative(shot.name);
  report.shots.push({ name: shot.name, requested: shot, before, pose, snapshot: image, after: rendererState() });
}
qa.controls.target.copy(initialCamera.target); qa.camera.position.copy(initialCamera.position);
qa.camera.up.copy(initialCamera.up);
qa.camera.near = initialCamera.near; qa.camera.far = initialCamera.far;
qa.controls.enableDamping = initialCamera.enableDamping;
qa.camera.updateProjectionMatrix(); qa.controls.update(); qa.controls.dispatchEvent({ type: 'change' });
qa.audioElements = Array.from(document.querySelectorAll('.viewer-motion-audio-player'));
const mediaEvents = [];
qa.audioElements.forEach(audio => ['waiting', 'stalled', 'seeking', 'seeked', 'pause', 'playing', 'error', 'ended'].forEach(type =>
  audio.addEventListener(type, () => mediaEvents.push({ type, phase: qa.phase, at: performance.now(), time: audio.currentTime, ready: audio.readyState }))));
let observer;
if (window.PerformanceObserver && (PerformanceObserver.supportedEntryTypes || []).includes('longtask')) {
  qa.longTasks = []; observer = new PerformanceObserver(list => list.getEntries().forEach(entry => qa.longTasks.push({ phase: qa.phase, start: entry.startTime, duration: entry.duration })));
  observer.observe({ entryTypes: ['longtask'] });
} else report.unsupported.push('PerformanceObserver longtask is unavailable in this WebKit');
for (const phase of config.phases || [{ name: 'dance-audio-on', audio: true, time: 50, durationMs: 12000 }, { name: 'dance-audio-off-diagnostic', audio: false, time: 50, durationMs: 12000 }]) {
  pause();
  const selectedPhaseClip = phase.clip === 'home' ? qa.homeClip : choice;
  if (phase.clip === 'home' && (!selectedPhaseClip || !Array.from(select.options).some(option => option.value === selectedPhaseClip))) {
    report.phases.push({ name: phase.name, requested: phase, skipped: 'The original costume home clip is unavailable in the retained motion list' });
    continue;
  }
  const previousClip = qa.rig.getPlaybackState();
  if (qa.rig.getPlaybackState().selectedClip !== selectedPhaseClip) input('viewer-motion', selectedPhaseClip, 'change');
  const enabled = document.getElementById('viewer-motion-audio-enabled');
  if (enabled.checked !== phase.audio) { enabled.checked = phase.audio; enabled.dispatchEvent(new Event('change', { bubbles: true })); }
  seek(phase.time === undefined ? 50 : phase.time);
  qa.phase = phase.name; qa.lastDrawTimestamp = null; qa.frames = []; qa.updates = []; qa.recording = true;
  const before = { at: performance.now(), previousClip, renderer: rendererState(), audio: window.ViewerMotionAudio && ViewerMotionAudio.getState() };
  play(); await delay(phase.durationMs || 12000); pause(); qa.recording = false;
  report.phases.push({ name: phase.name, requested: phase, before, after: { at: performance.now(), renderer: rendererState(), audio: window.ViewerMotionAudio && ViewerMotionAudio.getState() },
    frames: qa.frames, updates: qa.updates });
}
if (observer) observer.disconnect();
report.longTasks = qa.longTasks || null; report.mediaEvents = mediaEvents;
report.errors = qa.errors; report.rejections = qa.rejections;
report.status = qa.errors.length || qa.rejections.length ? 'FAIL' : 'PASS';
return JSON.parse(JSON.stringify(report));

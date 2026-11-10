/* WKWebView.callAsyncJavaScript body; config supplied by the separate QA host. */
const qa = window.__nativeWKDiagnostic;
const report = { status: 'RUNNING', scope: 'Unchanged published .4 app private backend/static source; separate public native WK QA host; static neck ribbon precision comparison, no FPS claim',
  userAgent: navigator.userAgent, devicePixelRatio, viewport: { width: innerWidth, height: innerHeight }, fixture: config.fixture, shots: [] };
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const assert = (value, message) => { if (!value) throw Error(message); };
async function hash(value) {
  const bytes = ArrayBuffer.isView(value) ? new Uint8Array(value.buffer, value.byteOffset, value.byteLength) : new TextEncoder().encode(typeof value === 'string' ? value : JSON.stringify(value));
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), x => x.toString(16).padStart(2, '0')).join('');
}
async function wait(label, predicate, timeout = 120000) {
  qa.checkpoint = label; const started = performance.now();
  while (!predicate()) { if (performance.now() - started > timeout) throw Error('Timeout: ' + label); await delay(100); }
}
function input(id, value, type = 'change') {
  const node = document.getElementById(id); assert(node, 'Missing input ' + id);
  node.value = String(value); node.dispatchEvent(new Event(type, { bubbles: true }));
}
function checked(id, value) {
  const node = document.getElementById(id); assert(node, 'Missing checkbox ' + id);
  if (node.checked !== value) { node.checked = value; node.dispatchEvent(new Event('change', { bubbles: true })); }
}
async function chooseRegion(desired) {
  const node = document.getElementById('viewer-game-region'), character = document.getElementById('viewer-game-character');
  if (node.value === desired) return;
  let observer, timer;
  try { await new Promise((resolve, reject) => {
    observer = new MutationObserver(records => { if (records.some(x => x.type === 'childList') && node.value === desired && character.options.length > 1) resolve(); });
    observer.observe(character, { childList: true });
    timer = setTimeout(() => reject(Error('Timeout: region catalog')), 120000);
    input(node.id, desired);
  }); } finally { if (observer) observer.disconnect(); if (timer) clearTimeout(timer); }
}
const state = () => ModelViewer.getState();
function runtime() {
  const c = qa.camera, gl = qa.renderer.getContext(), ext = gl.getExtension('WEBGL_debug_renderer_info'), rect = qa.renderer.domElement.getBoundingClientRect();
  const projectionNear = c.projectionMatrix.elements[14] / (c.projectionMatrix.elements[10] - 1);
  return { camera: { near: c.near, far: c.far, fov: c.fov, aspect: c.aspect, position: c.position.toArray(), target: qa.controls.target.toArray(), up: c.up.toArray(),
      projectionMatrix: c.projectionMatrix.toArray(), matrixWorldInverse: c.matrixWorldInverse.toArray(), projectionDerivedNear: projectionNear,
      nearOwnDescriptor: (() => { const d = Object.getOwnPropertyDescriptor(c, 'near'); return d ? { get: !!d.get, set: !!d.set, value: d.value, configurable: d.configurable, writable: d.writable } : null; })() },
    viewport: { width: innerWidth, height: innerHeight }, devicePixelRatio, canvasRect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
    canvasWidth: qa.renderer.domElement.width, canvasHeight: qa.renderer.domElement.height, drawingWidth: gl.drawingBufferWidth, drawingHeight: gl.drawingBufferHeight,
    contextSamples: gl.getParameter(gl.SAMPLES), depthBits: gl.getParameter(gl.DEPTH_BITS), renderer: gl.getParameter(gl.RENDERER), vendor: gl.getParameter(gl.VENDOR), version: gl.getParameter(gl.VERSION),
    unmaskedRenderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : null, unmaskedVendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : null,
    quality: state().quality, rig: { selectedClip: state().rig.selectedClip, time: state().rig.time, playing: state().rig.playing, physics: state().rig.physics },
    rimlightChecked: document.getElementById('viewer-rimlight').checked, glError: gl.getError(), visible: !document.hidden, stageVisible: state().layout.stageVisible };
}
async function invariants() {
  qa.root.updateMatrixWorld(true);
  const bones = [], morphs = [], posed = [], geometry = [], materials = [];
  const meshes = [];
  qa.root.traverse(object => {
    if (object.isBone) bones.push({ name: object.name, local: object.matrix.toArray(), world: object.matrixWorld.toArray() });
    if (object.morphTargetInfluences) morphs.push({ name: object.name, weights: Array.from(object.morphTargetInfluences) });
    if (object.isMesh && !object.userData.viewerHelper) meshes.push(object);
  });
  for (const mesh of meshes) {
    const attrs = {};
    for (const key of Object.keys(mesh.geometry.attributes).sort()) attrs[key] = await hash(mesh.geometry.attributes[key].array);
    geometry.push({ name: mesh.name, attributes: attrs, index: mesh.geometry.index ? await hash(mesh.geometry.index.array) : null });
    for (let i = 0; i < mesh.geometry.attributes.position.count; i++) posed.push(...ViewerMeshRuntime.vertexWorld(mesh, i).toArray());
    materials.push({ name: mesh.name, materials: (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).map(m => ({
      uuid: m.uuid, type: m.type, side: m.side, transparent: m.transparent, depthWrite: m.depthWrite, depthTest: m.depthTest,
      vertexShader: m.vertexShader, fragmentShader: m.fragmentShader,
      uniforms: Object.fromEntries(Object.entries(m.uniforms || {}).filter(([key, v]) => typeof v.value === 'number' || typeof v.value === 'boolean' || v.value?.isColor || v.value?.isTexture).map(([key, v]) => [key, v.value?.isTexture ? { textureUUID: v.value.uuid, version: v.value.version } : v.value?.isColor ? v.value.toArray() : v.value])) })) });
  }
  return { bones: { count: bones.length, sha256: await hash(bones) }, morphs: { count: morphs.length, sha256: await hash(morphs) },
    posedVertices: { count: posed.length / 3, sha256: await hash(posed) }, geometrySha256: await hash(geometry), materialSha256: await hash(materials), authoringSha256: await hash(ModelViewer.getAuthoringState()) };
}
function goldProjection() {
  qa.root.updateMatrixWorld(true); qa.camera.updateMatrixWorld(true);
  const points = [], rect = qa.renderer.domElement.getBoundingClientRect(); let minimumPositiveDepth = Infinity;
  for (let i = config.fixture.goldFirstVertex; i < config.fixture.goldFirstVertex + config.fixture.goldVertexCount; i++) {
    const world = ViewerMeshRuntime.vertexWorld(qa.body, i), view = world.clone().applyMatrix4(qa.camera.matrixWorldInverse), ndc = world.clone().project(qa.camera);
    const depth = -view.z; if (depth > 0) minimumPositiveDepth = Math.min(minimumPositiveDepth, depth);
    points.push({ vertex: i, world: world.toArray(), view: view.toArray(), ndc: ndc.toArray(), viewportCSS: [rect.left + (ndc.x + 1) * rect.width / 2, rect.top + (1 - ndc.y) * rect.height / 2] });
  }
  return { mesh: qa.body.name, vertexCount: points.length, minimumPositiveDepth, allGoldBeyondPointOne: points.every(p => -p.view[2] > config.fixedNear), points };
}
function restoreNear() {
  if (!qa.camera || !qa.savedNearDescriptor) return;
  const value = qa.camera.near; Object.defineProperty(qa.camera, 'near', Object.assign({}, qa.savedNearDescriptor, { value })); qa.forcedNear = false;
}
function forceNear(value) {
  restoreNear(); qa.lastRequestedNear = null;
  Object.defineProperty(qa.camera, 'near', { configurable: true, enumerable: qa.savedNearDescriptor.enumerable,
    get() { return value; }, set(requested) { qa.lastRequestedNear = requested; } });
  qa.forcedNear = true; qa.camera.updateProjectionMatrix();
}
try {
  await wait('product APIs', () => window.ModelViewer && window.THREE && window.ViewerRig && typeof openModelViewer === 'function');
  await wait('native document visible', () => !document.hidden, 20000);
  const viewerSource = await fetch('/static/model-viewer.js').then(r => { assert(r.ok, 'Viewer source response'); return r.text(); });
  report.viewerSha256 = await hash(viewerSource); assert(report.viewerSha256 === config.fixture.expectedViewerSha256, 'Published viewer SHA mismatch');
  const R = THREE.WebGLRenderer; THREE.WebGLRenderer = function (...args) { const r = new R(...args); qa.renderer = r; return r; }; THREE.WebGLRenderer.prototype = R.prototype;
  const C = THREE.OrbitControls; THREE.OrbitControls = function (camera, element) { const c = new C(camera, element); qa.camera = camera; qa.controls = c; return c; }; THREE.OrbitControls.prototype = C.prototype;
  const create = ViewerRig.create; ViewerRig.create = function (...args) { const r = create.apply(this, args); qa.root = args[0]; qa.rig = r; return r; };
  switchTab('viewer');
  await wait('normal game picker', () => document.getElementById('tab-viewer').classList.contains('active') && document.getElementById('viewer-game-assets').dataset.gameAssetsBound === 'true');
  checked('viewer-auto-face', true); document.getElementById('viewer-game-assets').click();
  await wait('characters', () => document.getElementById('viewer-game-character')?.options.length > 1);
  await chooseRegion(config.gameImport.region);
  await wait('Shizuku choice', () => Array.from(document.getElementById('viewer-game-character').options).some(o => o.value === String(config.gameImport.character)));
  input('viewer-game-character', config.gameImport.character);
  await wait('winter uniform choice', () => Array.from(document.getElementById('viewer-game-costume').options).some(o => o.value === config.gameImport.costume));
  input('viewer-game-costume', config.gameImport.costume); checked('viewer-game-download', true); checked('viewer-game-reimport', true);
  document.getElementById('viewer-game-import').click();
  await wait('original CDN winter uniform', () => !document.getElementById('viewer-game-assets-dialog').open && state().loaded && !state().loading, 240000);
  assert(state().rig.selectedClip === config.expectedClip, 'Unexpected default pose clip: ' + state().rig.selectedClip);
  if (state().rig.playing) document.getElementById('viewer-play').click();
  input('viewer-time', 0, 'input');
  for (const key of Object.keys(config.expectedStats)) assert(state().stats[key] === config.expectedStats[key], 'Model stats differ: ' + key);
  document.getElementById('viewer-display-options').open = true;
  checked('viewer-high-quality', true); checked('viewer-rimlight', false);
  await wait('HQ actual4 samples', () => state().quality.enabled && state().quality.actualSamples === 4);
  document.getElementById('viewer-stage').scrollIntoView({ block: 'center' }); await delay(300);
  qa.root.traverse(o => { if (o.isMesh && !o.userData.viewerHelper && (o.userData.originalName || o.name) === config.fixture.goldMesh) qa.body = o; });
  assert(qa.body && qa.body.geometry.attributes.position.count >= 344, 'Original gold Body vertices unavailable');
  qa.savedNearDescriptor = Object.getOwnPropertyDescriptor(qa.camera, 'near');
  assert(qa.savedNearDescriptor && !qa.savedNearDescriptor.get && !qa.savedNearDescriptor.set && qa.savedNearDescriptor.configurable, 'Camera near must start as normal configurable data property');
  report.loaded = { loadedPaths: state().loadedPaths, stats: state().stats, faces: state().faces, selectedClip: state().rig.selectedClip, time: state().rig.time, authoring: ModelViewer.getAuthoringState() };
  report.initial = runtime(); report.invariantsBefore = await invariants();
  qa.controls.enableDamping = false;
  for (const shot of config.shots) {
    qa.controls.target.fromArray(config.target); qa.camera.position.fromArray(config.target).addScaledVector(new THREE.Vector3().fromArray(config.direction).normalize(), shot.distance);
    qa.camera.up.set(0, 1, 0); qa.camera.fov = config.fov; qa.camera.lookAt(qa.controls.target); qa.camera.updateProjectionMatrix(); qa.controls.update(); qa.controls.dispatchEvent({ type: 'change' });
    const pair = [];
    for (const [mode, forced] of [['old-floor', config.oldNear], ['adaptive', null], ['fixed-0.1', config.fixedNear]]) {
      if (forced === null) restoreNear(); else forceNear(forced);
      ModelViewer.renderProbe(1); await delay(150); ModelViewer.renderProbe(1); qa.camera.updateMatrixWorld(true);
      const before = runtime(), invariant = await invariants(), gold = goldProjection();
      assert(before.quality.actualSamples === 4 && before.glError === 0 && before.visible && before.stageVisible, 'Invalid rendered native capture');
      assert(Math.abs(before.camera.projectionDerivedNear - before.camera.near) < 1e-9, 'Projection near does not match actual camera near');
      assert(mode !== 'adaptive' || (!before.camera.nearOwnDescriptor.get && !before.camera.nearOwnDescriptor.set), 'Adaptive near accessor must be absent');
      assert(forced === null || before.camera.near === forced, 'Forced near was overwritten');
      assert(gold.allGoldBeyondPointOne, 'Fixed .1 control would clip original gold geometry');
      assert(JSON.stringify(invariant) === JSON.stringify(report.invariantsBefore), 'Pose/geometry/material/authoring changed');
      const name = shot.name + '-' + mode;
      const bridge = window.webkit && webkit.messageHandlers && webkit.messageHandlers.qaDiagnostic;
      const snapshot = bridge ? await bridge.postMessage({ kind: 'snapshot', name }) : { skipped: 'host functional rehearsal only' };
      const after = runtime(), invariantAfter = await invariants();
      assert(JSON.stringify(invariantAfter) === JSON.stringify(invariant), 'Capture changed pose/material/authoring');
      assert(JSON.stringify(after.camera) === JSON.stringify(before.camera), 'Capture camera changed');
      const value = { name, requested: shot, mode, forcedNear: forced, lastRequestedNear: qa.lastRequestedNear, before, after, invariants: invariant, gold, snapshot };
      report.shots.push(value); pair.push(value);
    }
    const signature = x => JSON.stringify({ position: x.before.camera.position, target: x.before.camera.target, up: x.before.camera.up, fov: x.before.camera.fov, far: x.before.camera.far, viewport: x.before.viewport, rect: x.before.canvasRect });
    assert(pair.every(x => signature(x) === signature(pair[0])), 'Near pair view/viewport mismatch');
  }
  report.invariantsAfter = await invariants(); report.authoringUnchanged = report.invariantsAfter.authoringSha256 === report.invariantsBefore.authoringSha256;
  assert(qa.errors.length === 0 && qa.rejections.length === 0, 'Product JS error/rejection observed');
  report.status = 'PASS';
} catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); report.checkpoint = qa.checkpoint; report.failureState = window.ModelViewer ? state() : null; }
finally { restoreNear(); if (qa.camera) { qa.camera.updateProjectionMatrix(); ModelViewer.renderProbe(1); report.nearRestoredFinally = !Object.getOwnPropertyDescriptor(qa.camera, 'near').get; } }
report.errors = qa.errors; report.rejections = qa.rejections;
return JSON.parse(JSON.stringify(report));

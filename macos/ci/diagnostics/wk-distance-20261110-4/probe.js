/* QA-only: one original linked PCM WAV on the native WebAudio DSP clock.
 * No product controller, decoder, binding or DOM code is replaced here.
 */
(function (scope) {
  'use strict';
  const MAX_ENCODED = 32 * 1024 * 1024, MAX_DECODED = 64 * 1024 * 1024;
  const abortError = () => Object.assign(new Error('PCM reference was aborted'), { name: 'AbortError' });
  const now = () => performance.now();
  function checkAbort(signal) { if (signal && signal.aborted) throw abortError(); }
  function pcmInfo(bytes) {
    const view = new DataView(bytes), text = (at, length) => String.fromCharCode(...new Uint8Array(bytes, at, length));
    if (bytes.byteLength < 44 || text(0, 4) !== 'RIFF' || text(8, 4) !== 'WAVE') throw Error('Reference requires an original PCM WAV');
    let format = null, dataBytes = null;
    for (let at = 12; at + 8 <= bytes.byteLength;) {
      const size = view.getUint32(at + 4, true), begin = at + 8;
      if (begin + size > bytes.byteLength) throw Error('PCM chunk exceeds the response');
      if (text(at, 4) === 'fmt ') {
        if (size < 16) throw Error('Invalid PCM format');
        format = { code: view.getUint16(begin, true), channels: view.getUint16(begin + 2, true), sampleRate: view.getUint32(begin + 4, true), blockAlign: view.getUint16(begin + 12, true), bits: view.getUint16(begin + 14, true) };
      }
      if (text(at, 4) === 'data') dataBytes = size;
      at = begin + size + (size & 1);
    }
    if (!format || dataBytes === null || format.code !== 1 || format.channels < 1 || format.channels > 8 ||
        format.sampleRate < 8000 || format.sampleRate > 192000 || ![8, 16, 24, 32].includes(format.bits) ||
        format.blockAlign !== format.channels * format.bits / 8 || dataBytes % format.blockAlign) throw Error('Unsupported or invalid PCM WAV');
    return { ...format, frames: dataBytes / format.blockAlign, dataBytes };
  }
  async function boundedBytes(response) {
    const length = Number(response.headers.get('content-length'));
    if (Number.isFinite(length) && length > MAX_ENCODED) throw Error('Encoded PCM exceeds 32 MiB');
    if (!response.body || !response.body.getReader) {
      const bytes = await response.arrayBuffer();
      if (bytes.byteLength > MAX_ENCODED) throw Error('Encoded PCM exceeds 32 MiB');
      return bytes;
    }
    const reader = response.body.getReader(), chunks = []; let total = 0;
    try {
      while (true) {
        const part = await reader.read(); if (part.done) break;
        total += part.value.byteLength;
        if (total > MAX_ENCODED) { await reader.cancel(); throw Error('Encoded PCM exceeds 32 MiB'); }
        chunks.push(part.value);
      }
    } finally { reader.releaseLock(); }
    const bytes = new Uint8Array(total); let at = 0;
    for (const chunk of chunks) { bytes.set(chunk, at); at += chunk.byteLength; }
    return bytes.buffer;
  }
  scope.WKPCMReference = {
    async create(url, options = {}) {
      const parsed = new URL(url, location.href);
      if (parsed.origin !== location.origin || !/^\/api\/viewer\/game\/motions\/audio\/[a-f0-9]{32}\.wav$/.test(parsed.pathname)) throw Error('Reference requires a same-origin linked game WAV');
      const Context = scope.AudioContext || scope.webkitAudioContext;
      if (!Context) throw Error('WebAudio AudioContext is unavailable');
      const context = new Context({ latencyHint: 'interactive' }), events = [];
      let buffer = null, source = null, gain = null, disposed = false, generation = 0;
      let startCtx = null, mediaOffset = 0, frozenMedia = 0, sourceState = 'unstarted';
      const rate = options.playbackRate === undefined ? 1 : options.playbackRate;
      const authoredStart = options.startTime === undefined ? 0 : options.startTime, authoredOffset = options.offset === undefined ? 0 : options.offset;
      if (!Number.isFinite(rate) || rate < .05 || rate > 8 || !Number.isFinite(authoredStart) || authoredStart < 0 || !Number.isFinite(authoredOffset) || authoredOffset < 0) { await context.close(); throw Error('Invalid authored playback mapping'); }
      context.addEventListener('statechange', () => { if (events.length < 32) events.push({ at: now(), type: 'statechange', state: context.state, contextTime: context.currentTime }); });
      try {
        checkAbort(options.signal);
        const response = await fetch(parsed.href, { credentials: 'same-origin', signal: options.signal });
        if (!response.ok) throw Error('PCM response HTTP ' + response.status);
        let bytes = await boundedBytes(response); checkAbort(options.signal);
        const info = pcmInfo(bytes), estimate = Math.ceil(info.frames * context.sampleRate / info.sampleRate) * info.channels * 4;
        if (estimate > MAX_DECODED) throw Error('Decoded PCM estimate exceeds 64 MiB');
        const digest = await crypto.subtle.digest('SHA-256', bytes);
        const sha256 = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
        if (options.expectedSha256 && sha256 !== options.expectedSha256) throw Error('Original PCM SHA-256 mismatch');
        const encodedBytes = bytes.byteLength, decodeBegin = now();
        buffer = await context.decodeAudioData(bytes); bytes = null; checkAbort(options.signal);
        const decodedBytes = buffer.length * buffer.numberOfChannels * 4;
        if (decodedBytes > MAX_DECODED) throw Error('Decoded PCM exceeds 64 MiB');
        gain = context.createGain(); gain.gain.value = 1; gain.connect(context.destination);
        const original = { sha256, encodedBytes, decodedBytes, duration: buffer.duration, channels: buffer.numberOfChannels, sampleRate: buffer.sampleRate, sourcePCM: info, decodeMs: now() - decodeBegin };
        function mappedMedia() {
          if (sourceState !== 'scheduled' && sourceState !== 'playing') return frozenMedia;
          return Math.min(buffer.duration, mediaOffset + Math.max(0, context.currentTime - startCtx) * rate);
        }
        function stop() {
          if (disposed) return;
          frozenMedia = mappedMedia(); generation++;
          if (source) { source.onended = null; try { source.stop(); } catch (_) {} source.disconnect(); source = null; }
          sourceState = 'stopped';
        }
        function snapshot() {
          if (sourceState === 'scheduled' && context.currentTime >= startCtx) sourceState = 'playing';
          let outputTimestamp = null;
          try { if (context.getOutputTimestamp) outputTimestamp = context.getOutputTimestamp(); } catch (_) {}
          const mediaTime = disposed ? frozenMedia : mappedMedia();
          return { at: now(), contextState: context.state, contextTime: context.currentTime, outputTimestamp,
            baseLatency: context.baseLatency === undefined ? null : context.baseLatency, outputLatency: context.outputLatency === undefined ? null : context.outputLatency,
            sourceState, startCtx, mediaOffset, playbackRate: rate, mappedMediaTime: mediaTime,
            mappedTimelineTime: authoredStart + (mediaTime - authoredOffset) / rate,
            gain: gain ? gain.gain.value : null, disposed, original, events: events.slice() };
        }
        const reference = {
          async resume(timeoutMs = 1500) {
            if (disposed) throw Error('Reference is disposed');
            let timeout;
            try { await Promise.race([context.resume(), new Promise((_, reject) => { timeout = setTimeout(() => reject(Error('AudioContext resume timed out')), timeoutMs); })]); }
            finally { clearTimeout(timeout); }
            return snapshot();
          },
          start(offset, scheduleAhead = .05) {
            if (disposed || context.state !== 'running') throw Error('AudioContext is not running');
            if (!Number.isFinite(offset) || offset < 0 || offset >= buffer.duration || !Number.isFinite(scheduleAhead) || scheduleAhead < 0 || scheduleAhead > .5) throw Error('Invalid PCM start position');
            stop(); const ownGeneration = ++generation;
            mediaOffset = frozenMedia = offset; startCtx = context.currentTime + scheduleAhead;
            source = context.createBufferSource(); source.buffer = buffer; source.playbackRate.value = rate; source.connect(gain);
            const node = source;
            source.onended = () => { node.disconnect(); if (generation === ownGeneration && source === node) { frozenMedia = buffer.duration; sourceState = 'ended'; source = null; } };
            sourceState = 'scheduled'; source.start(startCtx, offset); return snapshot();
          },
          stop, snapshot,
          setGain(value) { if (disposed || !Number.isFinite(value) || value < 0 || value > 1) throw Error('Invalid reference gain'); gain.gain.value = value; },
          async dispose() { if (disposed) return; stop(); disposed = true; if (options.signal) options.signal.removeEventListener('abort', cancelled); buffer = null; gain.disconnect(); await context.close(); }
        };
        const cancelled = () => { reference.dispose().catch(() => {}); };
        if (options.signal) options.signal.addEventListener('abort', cancelled, { once: true });
        return reference;
      } catch (error) {
        if (source) { try { source.stop(); } catch (_) {} source.disconnect(); }
        if (gain) gain.disconnect(); buffer = null; disposed = true; await context.close(); throw error;
      }
    }
  };
}(window));


/* Explicit QA-only DSP clock experiment; helper above is frozen SHA69f7d664. */
/* WKWebView.callAsyncJavaScript function body. `config` is supplied as an argument.
 * QA uses real source GLB/metadata replay; no model export/editing endpoints are called.
 */
const qa = window.__nativeWKDiagnostic;
const report = { status: 'RUNNING', scope: 'QA-only native WK using unchanged C2 app bytes/backend/static; explicit public clock override only during WebAudio DSP reference phase. This is not shipped transport/AppKit container or user Mac FPS.',
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
if (!window.ViewerMotionAudio || !ViewerMotionAudio.getPlaybackClock) throw Error('Original product clock API is unavailable');
const originalPlaybackClock = ViewerMotionAudio.getPlaybackClock;
qa.useReferenceClock = false;
ViewerMotionAudio.getPlaybackClock = function (...args) {
  const original = originalPlaybackClock.apply(this, args);
  qa.rawOriginalAudioClock = original;
  let value = original;
  if (qa.useReferenceClock && qa.pcmReference) {
    const reference = qa.pcmReference.snapshot();
    if (reference.contextState === 'running' && ['playing', 'scheduled'].includes(reference.sourceState)) value = reference.mappedTimelineTime;
    else {
      qa.referenceClockInvalid = { at: performance.now(), contextState: reference.contextState, sourceState: reference.sourceState };
      value = null; // C2 fallback is observed and explicitly invalidates DSP-success interpretation.
    }
  }
  qa.lastAudioClock = value;
  qa.clockReadAt = performance.now();
  return value;
};
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
for (const [key, value] of Object.entries(config.reference?.expectedOriginalStats || {})) {
  if (report.loaded.stats[key] !== value) throw Error('Original Eli workload stats changed: ' + key);
}
if (config.reference?.expectedActualSamples && report.loaded.quality.actualSamples !== config.reference.expectedActualSamples) {
  throw Error('Actual sample count differs from the original native control');
}
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
const mediaEvents = [];
const watchedMedia = new WeakSet();
function refreshCurrentMedia() {
  qa.audioElements = Array.from(document.querySelectorAll('.viewer-motion-audio-player'));
  qa.audioElements.forEach(audio => {
    if (watchedMedia.has(audio)) return;
    watchedMedia.add(audio);
    ['waiting', 'stalled', 'seeking', 'seeked', 'pause', 'playing', 'error', 'ended'].forEach(type =>
      audio.addEventListener(type, () => mediaEvents.push({ type, phase: qa.phase, at: performance.now(), time: audio.currentTime, ready: audio.readyState })));
  });
}
refreshCurrentMedia();
const initialAudioEnabled = document.getElementById('viewer-motion-audio-enabled').checked;
report.reference = { status: 'NOT_CREATED_BEFORE_HTML_BASELINE', lifecycle: [], hostExpectedWavSha256: config.reference?.hostExpectedSha256 || null,
  helperSha256: config.reference?.helperSha256 || null,
  limitation: 'Actual same-job WAV is hashed. No physical/audible output or AVFoundation counters are recorded; a stable DSP clock alone is not proof of audible quality.' };
async function closeReference(reason) {
  if (!qa.pcmReference) return true;
  qa.useReferenceClock = false;
  qa.pcmReference.stop();
  const reference = qa.pcmReference;
  report.reference.lifecycle.push({ action: 'stop-and-dispose', reason, at: performance.now(), snapshot: reference.snapshot() });
  let timer;
  try {
    await Promise.race([reference.dispose(), new Promise((_, reject) => { timer = setTimeout(() => reject(Error('Reference context close timed out')), 3000); })]);
    const snapshot = reference.snapshot();
    report.reference.lifecycle.push({ action: 'disposed', reason, at: performance.now(), snapshot });
    report.reference.closed = snapshot.contextState === 'closed';
    return report.reference.closed;
  } catch (error) {
    report.reference.closeError = String(error);
    report.reference.closed = reference.snapshot().contextState === 'closed';
    return report.reference.closed;
  } finally { if (timer) clearTimeout(timer); }
}
async function prepareReference() {
  const descriptor = qa.rig.getMotionAudio(choice);
  const track = descriptor && descriptor.tracks && descriptor.tracks.find(item => item.cue === (config.reference?.cue || 'music_2008'));
  refreshCurrentMedia();
  const audio = qa.audioElements.find(item => item.dataset.motionCue === track?.cue);
  if (!track || !audio || !audio.src) throw Error('The original selected HTML player and authored linked WAV are unavailable');
  const authoredURL = new URL(track.url, location.href).href;
  if (audio.src !== authoredURL) throw Error('The reference URL differs from the current original HTML player source');
  report.reference.input = { exactHtmlSourceURL: audio.src, exactDescriptorURL: authoredURL, sameURL: true,
    cue: track.cue, startTime: track.startTime || 0, offset: track.offset || 0, playbackRate: track.playbackRate || 1 };
  const begin = performance.now();
  report.reference.lifecycle.push({ action: 'create-and-decode-request', at: begin });
  try {
    qa.pcmReference = await WKPCMReference.create(audio.src, { startTime: track.startTime, offset: track.offset, playbackRate: track.playbackRate });
    report.reference.prepared = qa.pcmReference.snapshot();
    report.reference.prepareMs = performance.now() - begin;
    report.reference.lifecycle.push({ action: 'created-and-decoded', at: performance.now(), snapshot: report.reference.prepared });
    report.reference.nativeWavSha256 = report.reference.prepared.original.sha256;
    report.reference.matchesHostWavSha256 = report.reference.hostExpectedWavSha256 ? report.reference.nativeWavSha256 === report.reference.hostExpectedWavSha256 : null;
    const resumed = await qa.pcmReference.resume(config.reference?.resumeTimeoutMs || 1500);
    report.reference.lifecycle.push({ action: 'resume-returned', at: performance.now(), snapshot: resumed });
    if (resumed.contextState !== 'running') throw Error('Reference AudioContext is not running: ' + resumed.contextState);
    report.reference.status = 'RUNNING_PREPARED';
    return true;
  } catch (error) {
    report.reference.status = 'UNAVAILABLE'; report.reference.error = String(error);
    report.reference.lifecycle.push({ action: 'prepare-or-resume-unavailable', at: performance.now(), error: String(error), snapshot: qa.pcmReference ? qa.pcmReference.snapshot() : null });
    await closeReference('unavailable-before-phase');
    return false;
  }
}
let observer;
if (window.PerformanceObserver && (PerformanceObserver.supportedEntryTypes || []).includes('longtask')) {
  qa.longTasks = []; observer = new PerformanceObserver(list => list.getEntries().forEach(entry => qa.longTasks.push({ phase: qa.phase, start: entry.startTime, duration: entry.duration })));
  observer.observe({ entryTypes: ['longtask'] });
} else report.unsupported.push('PerformanceObserver longtask is unavailable in this WebKit');
try {
for (const phase of config.phases) {
  pause();
  if (phase.closeReferenceBefore && !(await closeReference('before-return-HTML-control'))) {
    report.phases.push({ name: phase.name, requested: phase, skipped: 'AudioContext did not close; a return-to-HTML control would be confounded' });
    continue;
  }
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
  if (phase.clock === 'webaudio') {
    if (!(await prepareReference())) {
      report.phases.push({ name: phase.name, requested: phase, skipped: 'Actual AudioContext preparation/resume was unavailable', reference: report.reference });
      continue;
    }
    const mapping = report.reference.input;
    const mediaOffset = mapping.offset + ((phase.time === undefined ? 50 : phase.time) - mapping.startTime) * mapping.playbackRate;
    report.referenceClockInvalid = null;
    qa.referenceClockInvalid = null;
    const started = qa.pcmReference.start(mediaOffset, 0);
    report.reference.lifecycle.push({ action: 'source-started-immediate-DSP-epoch', at: performance.now(), snapshot: started });
    qa.useReferenceClock = true;
  } else qa.useReferenceClock = false;
  refreshCurrentMedia();
  qa.phase = phase.name; qa.lastDrawTimestamp = null; qa.frames = []; qa.updates = [];
  qa.lastAudioClock = null; qa.rawOriginalAudioClock = null; qa.clockReadAt = null; qa.recording = true;
  const before = { at: performance.now(), previousClip, renderer: rendererState(), audio: window.ViewerMotionAudio && ViewerMotionAudio.getState(), reference: qa.pcmReference ? qa.pcmReference.snapshot() : null };
  play(); await delay(phase.durationMs || 12000); pause(); qa.recording = false;
  const after = { at: performance.now(), renderer: rendererState(), audio: window.ViewerMotionAudio && ViewerMotionAudio.getState(), reference: qa.pcmReference ? qa.pcmReference.snapshot() : null };
  report.phases.push({ name: phase.name, requested: phase, before, after,
    referenceClockInvalid: qa.referenceClockInvalid, frames: qa.frames, updates: qa.updates });
  if (phase.clock === 'webaudio') {
    report.reference.status = qa.referenceClockInvalid ? 'INVALID_CONTEXT_DURING_MEASUREMENT' : 'DSP_PHASE_OBSERVED';
    report.reference.invalid = qa.referenceClockInvalid || null;
    qa.pcmReference.stop(); qa.useReferenceClock = false;
  }
}
} finally {
  qa.recording = false; qa.useReferenceClock = false;
  pause(); await closeReference('final-cleanup');
  ViewerMotionAudio.getPlaybackClock = originalPlaybackClock;
  const enabled = document.getElementById('viewer-motion-audio-enabled');
  if (enabled.checked !== initialAudioEnabled) { enabled.checked = initialAudioEnabled; enabled.dispatchEvent(new Event('change', { bubbles: true })); }
  report.restored = { originalPlaybackClock: ViewerMotionAudio.getPlaybackClock === originalPlaybackClock,
    initialAudioEnabled, actualAudioEnabled: enabled.checked, contextClosed: report.reference.closed === true,
    rig: qa.rig.getPlaybackState(), audio: ViewerMotionAudio.getState() };
}
if (observer) observer.disconnect();
report.longTasks = qa.longTasks || null; report.mediaEvents = mediaEvents;
report.errors = qa.errors; report.rejections = qa.rejections;
report.status = qa.errors.length || qa.rejections.length ? 'FAIL' : 'PASS';
return JSON.parse(JSON.stringify(report));

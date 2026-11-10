/* QA only: original neutral donor, native pointer input and real Unity graft. */
(function (global) {
  'use strict';
  var prefix = 'viewer-part-transplant', sequence = 0, diagnostic = null;
  function assert(value, message) { if (!value) throw new Error(message); }
  function copy(value) { return JSON.parse(JSON.stringify(value)); }
  function equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  function state() { return copy(ModelViewer.getState()); }
  function donor() { return state().transplants.donors.find(function (row) { return row.operation === 'part'; }); }
  function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }
  function targetDescription(target) { return target ? { tag: target.tagName || '', id: target.id || '', className: typeof target.className === 'string' ? target.className : '' } : null; }
  function observePhase(message) {
    if (!diagnostic) return;
    diagnostic.phase = message; diagnostic.history.push({ phase: message, elapsed: performance.now() - diagnostic.started });
    if (diagnostic.history.length > 80) diagnostic.history.shift();
    var current = state();
    diagnostic.state = { modelId: current.modelId, loaded: current.loaded, loading: current.loading, error: current.error,
      contextLost: current.contextLost, stats: current.stats, paths: current.paths, transplants: current.transplants };
    diagnostic.donor = donor();
    var panel = document.getElementById(prefix);
    diagnostic.panelText = panel ? panel.innerText.slice(-16000) : '';
    diagnostic.canvases = Array.prototype.map.call(document.querySelectorAll('#' + prefix + ' canvas'), function (canvas) {
      var r = canvas.getBoundingClientRect(); return { target: targetDescription(canvas), rect: { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }, width: canvas.width, height: canvas.height };
    });
    var point = diagnostic.lastPointer && diagnostic.lastPointer.point;
    diagnostic.elementAtRequestedPoint = point ? targetDescription(document.elementFromPoint(point.x, point.y)) : null;
  }
  async function settle() { await new Promise(function (resolve) { requestAnimationFrame(function () { requestAnimationFrame(resolve); }); }); }
  async function until(message, condition) {
    observePhase(message);
    var end = Date.now() + 150000;
    while (Date.now() < end) { if (condition()) { observePhase(message + ': completed'); return; } await wait(25); }
    observePhase(message + ': timed out');
    throw new Error('Timed out: ' + message + ': ' + JSON.stringify(state()));
  }
  function expose(element) {
    assert(element, 'Missing actual part selection control');
    for (var parent = element.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true;
    element.scrollIntoView({ block: 'center' }); return element;
  }
  async function usable(element) {
    if (typeof element === 'string') element = document.getElementById(element);
    expose(element); await settle(); var observed = ViewerRigQa.control(element, true);
    assert(!observed.disabled && observed.visible && observed.withinViewport && observed.hittable, 'The actual part control must be usable: ' + JSON.stringify(observed));
    return element;
  }
  async function input(id, value, event) { var target = await usable(id); target.value = String(value); target.dispatchEvent(new Event(event || 'change', { bubbles: true })); await settle(); }
  async function click(id) { (await usable(id)).click(); await settle(); }
  function bone(name) { return document.querySelector('#' + prefix + '-bones label[data-bone=' + JSON.stringify(name) + '] input'); }
  function meshes(capture) { var result = []; capture.scene.traverse(function (mesh) { if (mesh.isMesh && !mesh.userData.viewerHelper) result.push(mesh); }); return result; }
  function map(mesh) { return mesh.geometry.userData.viewerMesh || mesh.userData.viewerMesh || {}; }
  function bodyMeshes(capture) { var d = donor(); return meshes(capture).filter(function (mesh) { var m = map(mesh); return m.mesh && m.mesh.source === 0 && String(m.mesh.id) === d.donorMesh && String(m.renderer) === d.donorRenderer; }); }
  function sceneFace(capture) {
    var candidates = bodyMeshes(capture), all = meshes(capture);
    for (var m = 0; m < candidates.length; m++) {
      var mesh = candidates[m], index = mesh.geometry.index, mapping = map(mesh);
      assert(mapping.vertexOrder === 'identity', 'The actual donor source must expose verified original face ordering');
      for (var offset = 0; offset < index.count; offset += 3) {
        var ids = [0, 1, 2].map(function (slot) { return index.getX(offset + slot); });
        var centre = ids.reduce(function (sum, id) { return sum.add(ViewerMeshRuntime.vertexWorld(mesh, id)); }, new THREE.Vector3()).divideScalar(3);
        var projected = centre.clone().project(capture.camera); if (projected.z < -1 || projected.z > 1) continue;
        var ray = new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2(projected.x, projected.y), capture.camera);
        var hits = all.map(function (other) { return ViewerMeshRuntime.raycastMesh(ray.ray, other); }).filter(Boolean).sort(function (a, b) { return a.distance - b.distance; });
        if (!hits.length || hits[0].object !== mesh || hits[0].faceIndex !== offset / 3) continue;
        var hit = hits[0], si = mesh.geometry.attributes.skinIndex, sw = mesh.geometry.attributes.skinWeight, weights = {};
        [hit.face.a, hit.face.b, hit.face.c].forEach(function (v, corner) { ['X', 'Y', 'Z', 'W'].forEach(function (axis) { var b = mesh.skeleton.bones[si['get' + axis](v)]; if (b) { var name = b.userData.originalName || b.name; weights[name] = (weights[name] || 0) + sw['get' + axis](v) * hit.barycoord.getComponent(corner); } }); });
        return { mesh: mesh, sourceFace: mapping.firstFace + offset / 3, bone: Object.keys(weights).sort(function (a, b) { return weights[b] - weights[a]; })[0],
          fraction: [(projected.x + 1) / 2, (1 - projected.y) / 2] };
      }
    }
    throw new Error('No actual visible source donor triangle can receive native input');
  }
  function textureFace(capture, sourceFace) {
    var selected = bodyMeshes(capture).find(function (mesh) { var m = map(mesh); return sourceFace >= m.firstFace && sourceFace < m.firstFace + m.faceCount; });
    assert(selected, 'The requested original donor face must exist in the selected mesh');
    var mapping = map(selected), index = selected.geometry.index, offset = (sourceFace - mapping.firstFace) * 3;
    var material = Array.isArray(selected.material) ? selected.material[0] : selected.material, texture = material && material.map;
    var points = [0, 1, 2].map(function (slot) { var uv = new THREE.Vector2().fromBufferAttribute(selected.geometry.attributes.uv, index.getX(offset + slot)); if (texture) { if (texture.matrixAutoUpdate) texture.updateMatrix(); texture.transformUv(uv); } return uv; });
    var centre = points.reduce(function (sum, uv) { return sum.add(uv); }, new THREE.Vector2()).divideScalar(3), view = donor().textureView;
    return { sourceFace: sourceFace, fraction: [view.x + centre.x * view.zoom, view.y + centre.y * view.zoom] };
  }
  async function nativeClick(element, fraction, kind) {
    expose(element); await settle();
    for (var attempt = 0; attempt < 5; attempt++) {
      var rect = element.getBoundingClientRect(), x = rect.left + rect.width * fraction[0], y = rect.top + rect.height * fraction[1];
      var viewport = global.visualViewport, width = viewport ? viewport.width : innerWidth, height = viewport ? viewport.height : innerHeight;
      var hit = document.elementFromPoint(x, y);
      if (x >= 0 && x <= width && y >= 0 && y <= height && (hit === element || element.contains(hit))) break;
      var scroller = element.parentElement;
      while (scroller && !(scroller.scrollHeight > scroller.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(scroller).overflowY))) scroller = scroller.parentElement;
      assert(scroller, 'The real donor paint point must be scrollable into view');
      var pane = scroller.getBoundingClientRect(); scroller.scrollTop += y - (Math.max(0, pane.top) + Math.min(height, pane.bottom)) / 2; await settle();
    }
    rect = element.getBoundingClientRect(); x = rect.left + rect.width * fraction[0]; y = rect.top + rect.height * fraction[1]; hit = document.elementFromPoint(x, y);
    assert(x >= 0 && x <= width && y >= 0 && y <= height && hit === element, 'The actual native pointer point must hit its visible donor canvas');
    var observed = null;
    function record(event, scope) {
      var touch = event.changedTouches && event.changedTouches[0];
      var value = { type: event.type, scope: scope, trusted: event.isTrusted, pointerType: event.pointerType || '',
        pointerId: event.pointerId === undefined ? null : event.pointerId, button: event.button === undefined ? null : event.button,
        clientX: touch ? touch.clientX : event.clientX === undefined ? null : event.clientX,
        clientY: touch ? touch.clientY : event.clientY === undefined ? null : event.clientY, target: targetDescription(event.target) };
      if (diagnostic) { diagnostic.lastEvent = copy(value); diagnostic.events.push(copy(value)); if (diagnostic.events.length > 96) diagnostic.events.shift(); }
      if (scope === 'document' && event.type === 'pointerup' && event.target === element) observed = value;
    }
    function recordWindow(event) { record(event, 'window'); }
    function recordDocument(event) { record(event, 'document'); }
    var eventTypes = ['pointerdown', 'pointerup', 'pointercancel', 'mousedown', 'mouseup', 'touchstart', 'touchend', 'touchcancel'];
    eventTypes.forEach(function (name) { global.addEventListener(name, recordWindow, true); document.addEventListener(name, recordDocument, true); });
    var request = { pending: true, id: ++sequence, target: kind, point: { x: x, y: y }, viewport: { width: width, height: height }, rect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height } };
    global.__nativePartPointer = request;
    if (diagnostic) diagnostic.lastPointer = copy(request);
    try { await until('native trusted donor pointer input ' + kind, function () { return !!observed; }); assert(observed.trusted, 'The donor selection must come from actual native input'); await settle(); }
    finally { request.pending = false; eventTypes.forEach(function (name) { global.removeEventListener(name, recordWindow, true); document.removeEventListener(name, recordDocument, true); }); }
    return { request: copy(request), event: observed };
  }
  function probe(capture) {
    capture.renderer.render(capture.scene, capture.camera);
    var gl = capture.renderer.getContext(), pixels = new Uint8Array(4), colored = 0, samples = 0;
    for (var row = 1; row < 33; row++) for (var column = 1; column < 33; column++) {
      gl.readPixels(Math.floor(column * gl.drawingBufferWidth / 33), Math.floor(row * gl.drawingBufferHeight / 33), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixels); samples++;
      if (Math.abs(pixels[0] - 23) + Math.abs(pixels[1] - 33) + Math.abs(pixels[2] - 48) > 20) colored++;
    }
    var result = { samples: samples, nonBackgroundSamples: colored, glError: gl.getError(), width: gl.drawingBufferWidth, height: gl.drawingBufferHeight };
    assert(colored > 0 && result.glError === 0, 'Actual donor WebGL must draw original source triangles without errors'); return result;
  }
  async function run(paths) {
    assert(paths && paths.sourcePath && paths.donorPath, 'Two explicit original neutral source paths are required');
    diagnostic = { phase: 'starting', started: performance.now(), history: [], lastPointer: null, lastEvent: null, events: [], requests: [], captureCount: 0 };
    global.__nativePartDiagnostic = diagnostic; observePhase('starting');
    var original = state(), originalAuthoring = copy(ModelViewer.getAuthoringState()), captures = [], requests = [];
    assert(original.loaded && original.loadedPaths[0] === paths.sourcePath && original.stats.vertices === 60 && original.stats.triangles === 20, 'The selected target must be the actual serialized 60-vertex costume');
    var Renderer = THREE.WebGLRenderer, picker = global.openPicker, fetch = global.fetch;
    THREE.WebGLRenderer = new Proxy(Renderer, { construct: function (target, args) { var renderer = Reflect.construct(target, args), render = renderer.render; renderer.render = function (scene, camera) { if (renderer.domElement.closest('#' + prefix) && !captures.some(function (entry) { return entry.renderer === renderer; })) { captures.push({ renderer: renderer, scene: scene, camera: camera, originalRender: render }); diagnostic.captureCount = captures.length; } return render.apply(renderer, arguments); }; return renderer; } });
    global.fetch = function (url, options) { if (String(url).endsWith('/api/viewer/transplant/run')) { requests.push(JSON.parse(options.body)); diagnostic.requests = copy(requests); } return fetch.apply(this, arguments); };
    try {
      var panel = document.getElementById(prefix); panel.open = true;
      // Only OS file chooser selection is supplied by QA. The actual donor
      // button/callback, authenticated inspect, GLB and all editing handlers run.
      global.openPicker = function (type, callback) { global.openPicker = picker; assert(type === 'path', 'The donor requires a single model path'); callback(paths.donorPath); };
      await click(panel.querySelector('[data-transplant-label="Choose donor costume"]'));
      await until('actual inspected and rendered source donor', function () { var d = donor(); return d.donor === paths.donorPath && d.availableBones.length > 0 && captures.length && bodyMeshes(captures[0]).length && !document.querySelector('#' + prefix + ' .viewer-transplant-stage').hidden; });
      THREE.WebGLRenderer = Renderer;
      var capture = captures[0], inspected = donor(), rows = inspected.availableBones;
      assert(/^[a-f0-9]{64}$/.test(inspected.donorSha256) && /^[a-f0-9]{64}$/.test(inspected.donorSelectionFingerprint), 'The donor selection must bind original source and mesh/material identities');
      assert(rows.find(function (row) { return row.value === 'LeftForeArm'; }).parent === 'LeftArm' && rows.find(function (row) { return row.value === 'LeftHandIndex1'; }).depth === rows.find(function (row) { return row.value === 'LeftArm'; }).depth + 3, 'The bone list must use the full real source hierarchy');
      assert(document.getElementById(prefix + '-include-children').checked, 'Selecting a donor parent includes genuine children by default');
      await click(bone('LeftArm')); await click(bone('RightLeg')); var multi = donor();
      assert(equal(multi.selectedBones, ['LeftArm', 'LeftForeArm', 'LeftHand', 'LeftHandIndex1', 'RightFoot', 'RightLeg']) && equal(multi.partRoots, ['RightLeg', 'LeftArm']) && multi.includeDescendants, 'Two actual hierarchy roots must select the exact disjoint descendant union');
      await click(bone('LeftHand')); var excluded = donor();
      assert(equal(excluded.selectedBones, ['LeftArm', 'LeftForeArm', 'RightFoot', 'RightLeg']) && !excluded.includeDescendants, 'Excluding a child must use exact names and never re-add it through a parent');
      await click(prefix + '-selection-undo'); assert(equal(donor().selectedBones, multi.selectedBones), 'Undo restores the real multi-bone selection');
      await click(prefix + '-selection-redo'); assert(equal(donor().selectedBones, excluded.selectedBones), 'Redo restores the exact child exclusion');
      await click(prefix + '-selection-clear'); await click(prefix + '-include-children');
      var height = panel.querySelector('input[type=range][aria-label]'); height.value = '180'; height.dispatchEvent(new Event('input', { bubbles: true })); await settle();
      expose(capture.renderer.domElement); await settle(); var visible = sceneFace(capture);
      var bonePointer = await nativeClick(capture.renderer.domElement, visible.fraction, 'scene-bone');
      assert(equal(donor().selectedBones, [visible.bone]), 'A native donor-model pick must select its genuine source skin bone');
      await click(prefix + '-selection-clear'); await input(prefix + '-selection-mode', 'triangles'); await input(prefix + '-scene-action', 'connected');
      expose(capture.renderer.domElement); await settle(); visible = sceneFace(capture);
      var scenePointer = await nativeClick(capture.renderer.domElement, visible.fraction, 'scene-face'), sceneSelected = donor();
      assert(equal(sceneSelected.selectedFaces, [visible.sourceFace]) && equal(sceneSelected.highlightedFaces, [visible.sourceFace]), 'A native 3D connected pick must identify the exact disconnected original source face');
      var donorProbe = probe(capture);
      await click(prefix + '-selection-undo'); assert(!donor().selectedFaces.length, '3D selection Undo must restore the original empty mask');
      await click(prefix + '-selection-redo'); assert(equal(donor().selectedFaces, [visible.sourceFace]), '3D selection Redo must restore the exact face');
      await click(prefix + '-selection-clear'); await input(prefix + '-scene-action', 'paint'); await input(prefix + '-brush-radius', '2', 'input'); await click(prefix + '-texture-fit');
      var texture = document.getElementById(prefix + '-texture'), texturePointers = [];
      for (var i = 0; i < 2; i++) { var id = [0, 19][i], uv = textureFace(capture, id); texturePointers.push(await nativeClick(texture, uv.fraction, 'texture-' + id)); }
      assert(equal(donor().selectedFaces, [0, 19]), 'Two native UV strokes must select exactly two separated source islands');
      await input(prefix + '-scene-action', 'erase'); texturePointers.push(await nativeClick(texture, textureFace(capture, 0).fraction, 'texture-erase-0'));
      assert(equal(donor().selectedFaces, [19]), 'The native UV erase stroke must remove only the painted source island');
      await click(prefix + '-selection-undo'); assert(equal(donor().selectedFaces, [0, 19]), 'UV Undo must restore the exact pre-erase mask');
      await click(prefix + '-selection-redo'); assert(equal(donor().selectedFaces, [19]), 'UV Redo must restore only the remaining island');
      await click(prefix + '-selection-undo'); await input(prefix + '-scene-action', 'paint'); texturePointers.push(await nativeClick(texture, textureFace(capture, 5).fraction, 'texture-5'));
      var selected = donor(); assert(equal(selected.selectedFaces, [0, 5, 19]) && equal(selected.highlightedFaces, selected.selectedFaces), 'The real 3D highlight must match the exact final UV mask');
      await click(panel.querySelector('button.viewer-primary'));
      await until('real graft saved and reopened', function () { var s = state(); return !s.loading && !s.transplants.busy && s.loaded && s.modelId !== original.modelId && s.loadedPaths[0] !== paths.sourcePath; }); await settle();
      var saved = state(), payload = requests[0];
      assert(requests.length === 1 && payload.partSelectionMode === 'triangles' && equal(payload.triangleIndices, [0, 5, 19]) && payload.donorSha256 === inspected.donorSha256 && payload.donorSelectionFingerprint === inspected.donorSelectionFingerprint && payload.donorRenderer === inspected.donorRenderer && payload.donorMesh === inspected.donorMesh,
        'Actual transplant submission must retain the exact donor source/mesh/material fingerprint and original face ordinals');
      assert(saved.stats.triangles === 23 && equal(ModelViewer.getAuthoringState().edits, []), 'The actual reopened graft must add the three selected faces once');
      var outputPath = saved.loadedPaths[0];
      await click(panel.querySelector('[data-transplant-label="Undo transplant"]'));
      await until('actual graft Undo', function () { var s = state(); return !s.loading && !s.transplants.busy && equal(s.loadedPaths, original.loadedPaths) && s.stats.triangles === 20; });
      assert(equal(ModelViewer.getAuthoringState(), originalAuthoring), 'Graft Undo must restore the exact original authoring state');
      await click(panel.querySelector('[data-transplant-label="Redo transplant"]'));
      await until('actual graft Redo', function () { var s = state(); return !s.loading && !s.transplants.busy && s.loadedPaths[0] === outputPath && s.stats.triangles === 23; });
      var finalProbe = ModelViewer.renderProbe(33); assert(finalProbe.ready && finalProbe.nonBackgroundSamples > 0 && finalProbe.glError === 0, 'The actual saved graft must remain visible after Undo and Redo');
      return { status: 'PASS', checks: { fullHierarchy: true, multipleRoots: true, exactChildExclusion: true, boneSelectionUndoRedo: true,
        trustedModelBonePick: true, trustedModelFacePick: true, trustedUVPaintErase: true, faceSelectionUndoRedo: true,
        sourceBoundSubmission: true, actualGraftReopened: true, actualGraftUndoRedo: true, donorAndTargetRendered: true },
        paths: copy(paths), outputPath: outputPath, original: original, inspected: inspected, multi: multi, excluded: excluded,
        bonePointer: bonePointer, scenePointer: scenePointer, texturePointers: texturePointers, sceneSelected: sceneSelected, selected: selected,
        request: payload, saved: saved, final: state(), donorProbe: donorProbe, finalProbe: finalProbe,
        scope: 'Actual serialized neutral target/donor, original hierarchy/skin, trusted native canvas input, authenticated graft and reopen/Undo/Redo. QA supplies the authorized OS chooser result; the OS file dialog is not exercised.' };
    } catch (error) {
      diagnostic.error = { message: String(error.message || error), stack: String(error.stack || ''), name: String(error.name || '') };
      observePhase(diagnostic.phase); throw error;
    } finally { diagnostic.finished = true; captures.forEach(function (capture) { capture.renderer.render = capture.originalRender; }); THREE.WebGLRenderer = Renderer; global.openPicker = picker; global.fetch = fetch; global.__nativePartPointer = null; }
  }
  global.NativePartQa = { run: run };
}(window));

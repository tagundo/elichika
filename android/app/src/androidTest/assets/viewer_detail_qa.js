/* QA only: real source outline controls and mesh viewing/selection. */
(function () {
  'use strict';
  function assert(value, message) { if (!value) throw new Error(message); }
  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }
  async function settle() { await new Promise(function (resolve) { requestAnimationFrame(function () { requestAnimationFrame(resolve); }); }); }
  async function until(message, predicate) {
    var end = Date.now() + 90000;
    while (Date.now() < end) { if (predicate()) return; await wait(30); }
    throw new Error('Timed out: ' + message + ': ' + JSON.stringify(ModelViewer.getState()));
  }
  function usable(id) {
    var target = document.getElementById(id); assert(target, 'Missing actual control ' + id);
    for (var p = target.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true;
    var control = ViewerRigQa.control(target, true);
    assert(!control.disabled && control.visible && control.withinViewport && control.hittable,
      'Actual editing control must be usable: ' + JSON.stringify(control));
    return target;
  }
  async function input(id, value, event) { var target = usable(id); target.value = String(value); target.dispatchEvent(new Event(event || 'input', { bubbles: true })); await settle(); }
  async function click(id) { usable(id).click(); await settle(); }
  function state() { return clone(ModelViewer.getState()); }
  function createNeutralSifasScene(T, fixture, options) {
    options = options || {};
    var scene = new T.Scene(), root = new T.Group(), geometry = new T.BufferGeometry();
    var camera = new T.Camera(); camera.projectionMatrix.identity();
    camera.matrixAutoUpdate = false; camera.matrix.identity(); camera.updateMatrixWorld(true);
    camera.matrixWorldInverse.copy(camera.matrixWorld).invert();
    var texture = new T.DataTexture(new Uint8Array(fixture.texture.rgba), 2, 1, T.RGBAFormat);
    texture.minFilter = texture.magFilter = T.NearestFilter;
    texture.wrapS = texture.wrapT = T.ClampToEdgeWrapping;
    texture.generateMipmaps = false; texture.encoding = T.LinearEncoding; texture.needsUpdate = true;
    var original = new T.MeshBasicMaterial({ map: texture });
    original.name = 'Neutral shared source material';
    original.userData.sifas = { version: 1, shader: 'AS/Member', pipeline: 'gamma',
      colors: {}, floats: { _CullMode: 2, _OutlineStencilComp: 8 }, features: {},
      textures: { _MainTex: { index: 0, filterMode: 0 } } };
    var mesh = new T.Mesh(geometry, original); mesh.name = 'NeutralMouthPatch'; mesh.frustumCulled = false;
    if (options.role !== null) mesh.userData.viewerFacialRole = options.role || 'mouth';
    root.add(mesh); scene.add(root);
    function setOrder(order) {
      var position = [], normal = [], uv = [], color = [];
      (order || [0, 1]).forEach(function (index) {
        var triangle = fixture.clipTriangles[index];
        var vertices = options.reverseWinding ? [triangle.vertices[0], triangle.vertices[2], triangle.vertices[1]] : triangle.vertices;
        vertices.forEach(function (point) {
          position.push.apply(position, point); normal.push(0, 0, 1);
          uv.push.apply(uv, triangle.uv); color.push(0, 1, 1, 1);
        });
      });
      geometry.setAttribute('position', new T.Float32BufferAttribute(position, 3));
      geometry.setAttribute('normal', new T.Float32BufferAttribute(normal, 3));
      geometry.setAttribute('uv', new T.Float32BufferAttribute(uv, 2));
      geometry.setAttribute('_sifas_color', new T.Float32BufferAttribute(color, 4));
    }
    setOrder([0, 1]);
    var occluders = [];
    function addOccluder(kind) {
      var z = kind === 'front' ? -0.4 : 0.95;
      var g = new T.BufferGeometry();
      g.setAttribute('position', new T.Float32BufferAttribute(
        fixture.clipTriangles[0].vertices.flatMap(function (p) { return [p[0], p[1], z]; }), 3));
      var m = new T.MeshBasicMaterial({ color: 0x0000ff, depthTest: true, depthWrite: true, side: T.FrontSide });
      var o = new T.Mesh(g, m); o.name = 'Neutral opaque ' + kind + ' occluder'; o.frustumCulled = false;
      // This is an independent opaque reference plane, not a facial material.
      scene.add(o); occluders.push(o); return o;
    }
    function removeOccluders() {
      occluders.forEach(function (o) { scene.remove(o); o.geometry.dispose(); o.material.dispose(); }); occluders = [];
    }
    return { scene: scene, root: root, mesh: mesh, camera: camera, geometry: geometry,
      texture: texture, originalMaterial: original, setOrder: setOrder,
      addOccluder: addOccluder, removeOccluders: removeOccluders,
      dispose: function () { removeOccluders(); geometry.dispose(); original.dispose(); texture.dispose(); } };
  }
  async function mouthOutlineCentroidGpu(T, fixture) {
    var results = [], fallbackPrograms = {};
    for (var mode of [{ name: 'webgl2-mouth', webgl2: true, role: 'mouth' },
                     { name: 'webgl2-original', webgl2: true, role: null },
                     { name: 'webgl1-mouth', webgl2: false, role: 'mouth' },
                     { name: 'webgl1-original', webgl2: false, role: null }]) {
      var canvas = document.createElement('canvas'), attrs = { antialias: true, alpha: false, depth: true, stencil: true, preserveDrawingBuffer: true };
      var context = canvas.getContext(mode.webgl2 ? 'webgl2' : 'webgl', attrs);
      assert(context, 'The native GPU must provide the requested actual OUTLINE ' + mode.name + ' context');
      var renderer = new T.WebGLRenderer({ canvas: canvas, context: context, antialias: true, alpha: false, depth: true, stencil: true, preserveDrawingBuffer: true });
      renderer.setPixelRatio(1); renderer.setSize(64, 64, false); renderer.setClearColor(0x000000, 1);
      renderer.toneMapping = T.NoToneMapping; renderer.outputEncoding = T.LinearEncoding;
      // Reverse the standalone source winding so the actual BackSide outline
      // pass draws. Occluders retain the independently authored CCW winding.
      var scene = createNeutralSifasScene(T, fixture, { role: mode.role, reverseWinding: true }), controller;
      try {
        var samples = context.getParameter(context.SAMPLES), depthBits = context.getParameter(context.DEPTH_BITS);
        assert(!!renderer.capabilities.isWebGL2 === mode.webgl2 && samples === 4 && depthBits === 24,
          'OUTLINE requires actual native MSAA4/depth24: ' + JSON.stringify({ mode: mode.name, samples: samples, depthBits: depthBits }));
        controller = SifasMaterial.apply(scene.root, renderer, { enabled: true, mouthCentroidDepth: !!renderer.capabilities.isWebGL2 });
        await controller.ready;
        var main = Array.isArray(scene.mesh.material) ? scene.mesh.material[0] : scene.mesh.material;
        var helper = scene.mesh.children.find(function (child) { return child.userData.sifasOutline; });
        assert(helper && helper.visible && helper.geometry === scene.geometry, 'The actual SifasMaterial OUTLINE helper must draw the original geometry');
        var outline = Array.isArray(helper.material) ? helper.material[0] : helper.material;
        // Hide only this QA scene's main material. Keep the real outline
        // stencil/depth/BackSide state and its native color/width attributes.
        main.visible = false;
        assert(outline.side === T.BackSide && outline.depthTest && outline.depthWrite && outline.stencilFunc === T.AlwaysStencilFunc,
          'OUTLINE inspection must retain its real BackSide/depth/stencil behavior');
        var colors = Array.from(scene.geometry.getAttribute('_sifas_color').array);
        assert(colors.length === 24 && colors.every(function (value, index) { return value === (index % 4 === 0 ? 0 : 1); }),
          'Native outline widthR0/G1 must prevent both XY extrusion and Z push without modifying the shader');
        var enabled = /centroid/.test(outline.vertexShader) && /vSifasMouthClipZW/.test(outline.fragmentShader) && /gl_FragDepth/.test(outline.fragmentShader);
        assert(enabled === (mode.webgl2 && mode.role === 'mouth'), 'Only verified Mouth WebGL2 OUTLINE may use centroid depth');
        var originalProgramUnchanged = !enabled && outline.vertexShader === SifasMaterial.outlineVertexShader && outline.fragmentShader === SifasMaterial.outlineFragmentShader;
        assert(enabled || originalProgramUnchanged, 'Unmarked/WebGL1 OUTLINE source must remain the complete original program');
        function readPixel() {
          var pixel = new Uint8Array(4); context.readPixels(32, 31, 1, 1, context.RGBA, context.UNSIGNED_BYTE, pixel);
          var error = context.getError();
          assert(error === 0, 'Actual production OUTLINE must compile/draw without GL errors: ' + mode.name);
          return { rgba: Array.from(pixel), glError: error };
        }
        function compiledOutline() {
          return renderer.info.programs.filter(function (program) {
            return /vSifasOutlineColor/.test(context.getShaderSource(program.fragmentShader) || '');
          }).map(function (program) {
            var source = context.getShaderSource(program.fragmentShader) || '';
            return { version: source.split('\n')[0], linked: context.getProgramParameter(program.program, context.LINK_STATUS) === true,
              centroidDepth: /vSifasMouthClipZW/.test(source) && /gl_FragDepth/.test(source), outlinePass: true };
          });
        }
        scene.setOrder([0, 1]); scene.geometry.setDrawRange(0, 3);
        renderer.render(scene.scene, scene.camera);
        var frontReference = readPixel(), frontReferenceProgram = compiledOutline();
        assert(frontReference.rgba[0] > 0 && frontReference.rgba[1] === 0 && frontReference.rgba[2] === 0 && frontReference.rgba[3] === 255,
          'The independent front reference must come from the actual nonblack red OUTLINE pass');
        scene.geometry.setDrawRange(0, 6);
        var observations = [];
        for (var order of [[0, 1], [1, 0]]) {
          scene.setOrder(order);
          for (var occluder of [null, 'front', 'rear']) {
            scene.removeOccluders();
            if (occluder) {
              var opaque = scene.addOccluder(occluder); opaque.renderOrder = order[0] ? -1 : 2;
              var position = opaque.geometry.getAttribute('position'), a = new T.Vector3().fromBufferAttribute(position, 0),
                b = new T.Vector3().fromBufferAttribute(position, 1), c = new T.Vector3().fromBufferAttribute(position, 2);
              assert(new T.Vector3().crossVectors(b.sub(a), c.sub(a)).z > 0 && opaque.material.side === T.FrontSide && opaque.material.depthTest && opaque.material.depthWrite,
                'The independent opaque occluder must keep CCW/FrontSide winding and ordinary depth');
            }
            renderer.render(scene.scene, scene.camera);
            var pixel = readPixel(), programs = compiledOutline();
            assert(programs.length > 0 && programs.every(function (program) {
              return program.linked && program.centroidDepth === enabled && (!enabled || /^#version 300 es/.test(program.version));
            }), 'Actual linked OUTLINE programs must expose the scoped GLSL300 centroid branch');
            if (enabled) assert(equal(pixel.rgba, occluder === 'front' ? [0, 0, 255, 255] : frontReference.rgba),
              'Mouth OUTLINE must retain true front/rear occlusion for both source orders: ' + JSON.stringify({ order: order, occluder: occluder, rgba: pixel.rgba, frontReference: frontReference.rgba }));
            observations.push({ order: order, occluder: occluder, rgba: pixel.rgba, glError: pixel.glError, compiledOutline: programs });
          }
        }
        fallbackPrograms[mode.name] = renderer.info.programs.filter(function (program) {
          return /vSifasOutlineColor/.test(context.getShaderSource(program.fragmentShader) || '');
        }).map(function (program) { return { vertex: context.getShaderSource(program.vertexShader), fragment: context.getShaderSource(program.fragmentShader) }; });
        results.push({ name: mode.name, actualWebGL2: !!renderer.capabilities.isWebGL2, version: context.getParameter(context.VERSION),
          samples: samples, depthBits: depthBits, vertices: scene.geometry.getAttribute('position').count, triangles: 2,
          side: 'BackSide', depthTest: outline.depthTest, depthWrite: outline.depthWrite, stencilAlways: outline.stencilFunc === T.AlwaysStencilFunc,
          mainHidden: !main.visible, nativeVertexColor: [0, 1, 1, 1], verifiedRole: mode.role, meshName: scene.mesh.name,
          centroidCompiled: enabled, originalProgramUnchanged: originalProgramUnchanged,
          frontReferenceRGBA: frontReference.rgba, frontReferenceProgram: frontReferenceProgram, observations: observations });
      } finally {
        if (controller) controller.dispose(); scene.dispose(); renderer.dispose(); renderer.forceContextLoss();
      }
    }
    var fallback = results.find(function (row) { return row.name === 'webgl1-mouth'; }), original = results.find(function (row) { return row.name === 'webgl1-original'; });
    assert(equal(fallback.observations, original.observations) && equal(fallback.frontReferenceRGBA, original.frontReferenceRGBA) &&
      equal(fallbackPrograms['webgl1-mouth'], fallbackPrograms['webgl1-original']),
      'WebGL1 OUTLINE fallback must retain actual original program sources and all six rendered outputs');
    return results;
  }
  async function mouthCentroidGpu() {
    var T = window.THREE;
    assert(T && window.SifasMaterial, 'Actual packaged Three.js and SifasMaterial are required');
    var fixture = { clipTriangles: [
      { uv: [.25, .5], vertices: [[-.125, .125, 0], [-.125, -.1875, 0], [.1875, .125, 0]] },
      { uv: [.75, .5], vertices: [[-.03125, .033854166666666664, .8], [.0625, -.09114583333333333, .8], [.068359375, -.09114583333333333, .3]] }
    ], texture: { rgba: [255, 0, 0, 255, 0, 255, 0, 255] } };
    var results = [];
    for (var mode of [{ name: 'webgl2-mouth', webgl2: true, role: 'mouth' },
                     { name: 'webgl2-original', webgl2: true, role: null },
                     { name: 'webgl1-mouth', webgl2: false, role: 'mouth' },
                     { name: 'webgl1-original', webgl2: false, role: null }]) {
      var canvas = document.createElement('canvas'), attrs = { antialias: true, alpha: false, depth: true, stencil: true, preserveDrawingBuffer: true };
      var context = canvas.getContext(mode.webgl2 ? 'webgl2' : 'webgl', attrs);
      assert(context, 'The native GPU must provide the requested actual ' + mode.name + ' context');
      var renderer = new T.WebGLRenderer({ canvas: canvas, context: context, antialias: true, alpha: false, depth: true, stencil: true, preserveDrawingBuffer: true });
      renderer.setPixelRatio(1); renderer.setSize(64, 64, false); renderer.setClearColor(0x000000, 1);
      renderer.toneMapping = T.NoToneMapping; renderer.outputEncoding = T.LinearEncoding;
      var scene = createNeutralSifasScene(T, fixture, { role: mode.role }), controller;
      try {
        assert(!!renderer.capabilities.isWebGL2 === mode.webgl2, 'GPU capability must reflect the real native context');
        var samples = context.getParameter(context.SAMPLES), depthBits = context.getParameter(context.DEPTH_BITS);
        assert(samples === 4 && depthBits === 24, 'Native thin-triangle fixture requires actual MSAA4/depth24: ' + JSON.stringify({ mode: mode.name, samples: samples, depthBits: depthBits }));
        controller = SifasMaterial.apply(scene.root, renderer, { enabled: true, mouthCentroidDepth: !!renderer.capabilities.isWebGL2 });
        await controller.ready;
        var main = Array.isArray(scene.mesh.material) ? scene.mesh.material[0] : scene.mesh.material;
        var enabled = /centroid/.test(main.vertexShader) && /vSifasMouthClipZW/.test(main.fragmentShader) && /gl_FragDepth/.test(main.fragmentShader);
        assert(enabled === (mode.webgl2 && mode.role === 'mouth'), 'Only verified Mouth WebGL2 MAIN may compile the centroid depth path');
        var observations = [];
        for (var order of [[0, 1], [1, 0]]) {
          scene.setOrder(order);
          for (var occluder of [null, 'front', 'rear']) {
            scene.removeOccluders(); if (occluder) scene.addOccluder(occluder).renderOrder = order[0] ? -1 : 2;
            renderer.render(scene.scene, scene.camera);
            var compiled = renderer.info.programs.filter(function (program) {
              var source = context.getShaderSource(program.fragmentShader) || '';
              return /vSifasMouthClipZW/.test(source) && /gl_FragDepth/.test(source);
            }).map(function (program) { return { version: (context.getShaderSource(program.fragmentShader) || '').split('\n')[0],
              linked: context.getProgramParameter(program.program, context.LINK_STATUS) === true }; });
            assert(enabled ? compiled.length > 0 && compiled.every(function (program) { return /^#version 300 es/.test(program.version) && program.linked; }) : compiled.length === 0,
              'The real WebGL program must link GLSL300 centroid MAIN only for Mouth WebGL2');
            var pixel = new Uint8Array(4); context.readPixels(32, 31, 1, 1, context.RGBA, context.UNSIGNED_BYTE, pixel);
            var rgba = Array.from(pixel), error = context.getError();
            assert(error === 0, 'Actual production shader must compile/draw without GL errors: ' + mode.name);
            if (enabled) assert(equal(rgba, occluder === 'front' ? [0, 0, 255, 255] : [255, 0, 0, 255]),
              'Mouth centroid must preserve true front/rear occlusion with both original triangle orders: ' + JSON.stringify({ order: order, occluder: occluder, rgba: rgba }));
            observations.push({ order: order, occluder: occluder, rgba: rgba, glError: error, compiledMain: compiled });
          }
        }
        results.push({ name: mode.name, actualWebGL2: !!renderer.capabilities.isWebGL2, version: context.getParameter(context.VERSION), samples: samples,
          depthBits: depthBits, vertices: scene.geometry.getAttribute('position').count, triangles: 2,
          verifiedRole: mode.role, meshName: scene.mesh.name, centroidCompiled: enabled,
          observations: observations });
      } finally {
        if (controller) controller.dispose(); scene.dispose(); renderer.dispose(); renderer.forceContextLoss();
      }
    }
    var fallback = results.find(function (x) { return x.name === 'webgl1-mouth'; }), original = results.find(function (x) { return x.name === 'webgl1-original'; });
    assert(equal(fallback.observations, original.observations), 'WebGL1 fallback must retain the complete original shader output, including original MSAA sample behavior');
    var outlineResults = await mouthOutlineCentroidGpu(T, fixture);
    return { status: 'PASS', backendAdaptation: true, originalGameShaderParityEstablished: false, source: 'Independent rational six-vertex/two-triangle scene, original texture colors and actual packaged SifasMaterial.apply',
      targetPixelTopLeft: [32, 32], viewport: [64, 64], results: results, fallbackUnchanged: true,
      outlineResults: outlineResults, outlineFallbackUnchanged: true,
      scope: 'WebGL Mouth occlusion backend adaptation, without claiming original-game shader implementation parity: actual native GPU Mouth-only GLSL3 MAIN and original BackSide OUTLINE compile, MSAA4/depth24 and both draw orders/front-rear occlusion; original baseline leak is observational, not required on every GPU.' };
  }
  async function rimlightPreview() {
    var key = 'elichika.viewer.rimlight.v1', checkbox = document.getElementById('viewer-rimlight');
    assert(checkbox && typeof ModelViewer.captureCheckpoint === 'function' && typeof ModelViewer.restoreCheckpoint === 'function',
      'The actual preview control and public model checkpoint APIs are required');
    function snapshot() {
      var current = state(), metadata = ModelViewer.getEditingMetadata();
      return { checked: checkbox.checked, enabled: current.materials && current.materials.rimlightEnabled,
        persisted: localStorage.getItem(key), modelId: current.modelId, paths: current.loadedPaths,
        sourceFingerprint: metadata.sourceFingerprint, authoring: clone(ModelViewer.getAuthoringState()),
        meshEdits: current.meshTools.edits };
    }
    function unchanged(before, after) {
      assert(equal(before.paths, after.paths) && before.sourceFingerprint === after.sourceFingerprint &&
        equal(before.authoring, after.authoring) && equal(before.meshEdits, after.meshEdits),
        'A display-only Rim preference must retain source identity and every body/mesh export edit');
    }
    var checkpoint = ModelViewer.captureCheckpoint(), before = snapshot(), restored = false;
    assert(before.checked === false && before.enabled === false && before.persisted !== 'true',
      'A fresh native preview must start with Rimlight OFF');
    assert(typeof before.sourceFingerprint === 'string' && /^[a-f0-9]{64}$/.test(before.sourceFingerprint),
      'The display-only preview check must remain bound to an actual source fingerprint');
    var target = usable('viewer-rimlight'), label = ViewerRigQa.control(target.parentElement, true),
      coarse = matchMedia('(pointer:coarse)').matches, minimum = coarse ? 44 : 34;
    assert(label.visible && label.withinViewport && label.hittable && label.width >= minimum && label.height >= minimum,
      'The actual Rim checkbox label must retain the real pointer target policy: ' + JSON.stringify(label));
    try {
      await click('viewer-rimlight');
      var on = snapshot();
      assert(on.checked === true && on.enabled === true && on.persisted === 'true',
        'The real native checkbox must enable the main controller and store the exact preference');
      unchanged(before, on);
      await ModelViewer.open(before.paths.slice());
      await until('Rim ON survives a normal fresh model load', function () {
        var current = ModelViewer.getState();
        return current.loaded && !current.loading && current.modelId !== before.modelId &&
          current.materials && current.materials.rimlightEnabled === true;
      });
      var reloadedOn = snapshot();
      assert(reloadedOn.checked === true && reloadedOn.persisted === 'true', 'A model reload must keep the chosen Rim ON state');
      unchanged(before, reloadedOn);
      await click('viewer-rimlight');
      var off = snapshot();
      assert(off.checked === false && off.enabled === false && off.persisted === 'false',
        'The actual checkbox must switch Rim OFF again without writing authored material settings');
      unchanged(before, off);
      var committed = await ModelViewer.restoreCheckpoint(checkpoint, ModelViewer.captureCheckpoint());
      assert(committed === true, 'The original source/checkpoint must be restored through its public validated path');
      await until('Rim OFF survives checkpoint reload', function () {
        var current = ModelViewer.getState();
        return current.loaded && !current.loading && current.materials && current.materials.rimlightEnabled === false;
      });
      var reloadedOff = snapshot();
      assert(reloadedOff.checked === false && reloadedOff.persisted === 'false', 'A restored source must retain the chosen Rim OFF state');
      unchanged(before, reloadedOff);
      restored = true;
      return { status: 'PASS', checks: { freshDefaultOff: true, realCheckboxAndStorage: true,
        reloadKeepsOn: true, reloadKeepsOff: true, sourceAndAuthoringUnchanged: true },
        before: before, on: on, reloadedOn: reloadedOn, off: off, reloadedOff: reloadedOff,
        label: label, pointer: coarse ? 'coarse' : matchMedia('(pointer:fine)').matches ? 'fine' : 'none', minimumTarget: minimum,
        sourcePixelDifferenceClaimed: false,
        scope: 'Actual native WebView control/main-controller/storage and fresh-model/checkpoint reloads. The unchanged neutral Unity material has authored Rim intensity0, so this flow does not claim an ON/OFF pixel difference. Positive authored Rim pixels and independent thumbnail-default/Basic-donor boundaries have separate renderer coverage.' };
    } finally {
      if (!restored) {
        // Failure cleanup restores the public source checkpoint; it never
        // substitutes a retry or a direct checkbox assignment for an assertion.
        try {
          if (checkbox.checked !== before.checked) await click('viewer-rimlight');
          await ModelViewer.restoreCheckpoint(checkpoint, ModelViewer.captureCheckpoint());
        } catch (_) {}
      }
    }
  }
  async function run() {
    var initial = state(), catalogue = clone(ModelViewer.getEditingMetadata().outlines), authoring = clone(ModelViewer.getAuthoringState());
    assert(initial.loaded && !initial.loading && catalogue.available && catalogue.meshes.length === 1,
      'The real neutral source must provide one authorized outline mesh');
    assert(!(authoring.outlines || []).length && !authoring.edits.length, 'Start with a clean source model');
    var includeFace = document.getElementById('viewer-mod-include-face');
    assert(includeFace && includeFace.type === 'checkbox' && includeFace.checked === false,
      'A fresh model must leave costume face and mouth inclusion off by default');
    var modFaceDefault = { checked: includeFace.checked, disabled: includeFace.disabled,
      scope: 'Actual shared Mod ZIP checkbox default; automatic face completion has its own unchanged control.' };
    var identity = catalogue.meshes[0].id;
    await input('viewer-outline-mesh', identity, 'change');
    await input('viewer-outline-absolute', '37'); await click('viewer-outline-absolute-apply');
    var absolute = clone(ModelViewer.getAuthoringState().outlines);
    assert(equal(absolute, [{ id: identity, factor: 1, absolute: 37 }]),
      'Absolute width must author one compact native red37 value for every source vertex');
    assert(state().outlines.absoluteWidth === 37 && equal(ModelViewer.getEditingMetadata().outlines, catalogue),
      'Absolute preview retains its native value and original catalogue');
    var absoluteOldJob = state().persistence.jobId;
    await click('viewer-save');
    await until('actual absolute outline export', function () { var p = ModelViewer.getState().persistence; if (p.status === 'error') throw new Error(p.error); return !p.busy && p.status === 'done' && p.jobId && p.jobId !== absoluteOldJob && p.previewPaths.length === 1; });
    var absoluteSaved = state().persistence;
    var absoluteResponse = await fetch('/api/download?path=' + encodeURIComponent(absoluteSaved.recipePath));
    assert(absoluteResponse.ok, 'The absolute Save must publish its actual source-bound recipe');
    var absoluteRecipe = await absoluteResponse.json();
    assert(equal(absoluteRecipe.state.outlines, absolute), 'The actual absolute recipe must preserve native red37');
    await click('viewer-outline-undo');
    assert(!(ModelViewer.getAuthoringState().outlines || []).length, 'Absolute Undo restores all original vertex widths');
    await click('viewer-outline-redo'); assert(equal(ModelViewer.getAuthoringState().outlines, absolute), 'Absolute Redo restores the compact all-vertex value');
    await click('viewer-outline-undo');
    assert(equal(ModelViewer.getAuthoringState(), authoring), 'Absolute Save and inspection must not leave unrelated edits');
    await input('viewer-outline-vertex-index', '0'); await input('viewer-outline-vertex-width', '25');
    await click('viewer-outline-vertex-apply');
    var sparse = clone(ModelViewer.getAuthoringState().outlines);
    assert(equal(sparse, [{ id: identity, factor: 1, vertices: [{ vertex: 0, value: .25 }] }]),
      'An exact source vertex must retain its sparse 25% outline width');
    await click('viewer-outline-undo'); assert(!(ModelViewer.getAuthoringState().outlines || []).length, 'Undo removes only the vertex edit');
    await click('viewer-outline-redo'); assert(equal(ModelViewer.getAuthoringState().outlines, sparse), 'Redo restores the exact sparse source edit');
    assert(equal(ModelViewer.getEditingMetadata().outlines, catalogue), 'Editing never mutates the source catalogue');
    await input('viewer-outline-scene-mode', 'paint', 'change');
    assert(state().outlines.sceneEditing && state().outlines.editedVertices === 1, 'The real 3D outline editing mode is active');
    await input('viewer-outline-scene-mode', 'orbit', 'change');
    var oldJob = state().persistence.jobId;
    await click('viewer-save');
    await until('actual sparse outline export', function () { var p = ModelViewer.getState().persistence; if (p.status === 'error') throw new Error(p.error); return !p.busy && p.status === 'done' && p.jobId && p.jobId !== oldJob && p.previewPaths.length === 1; });
    var saved = state().persistence, response = await fetch('/api/download?path=' + encodeURIComponent(saved.recipePath));
    assert(response.ok, 'The real Save must publish its source-bound recipe');
    var recipe = await response.json(); assert(equal(recipe.state.outlines, sparse), 'The saved recipe must contain the exact sparse vertex width');
    await click('viewer-outline-reset');
    assert(!(ModelViewer.getAuthoringState().outlines || []).length, 'Reset restores outline-only authoring');
    await input('viewer-outline-mesh', '', 'change');
    document.getElementById('viewer-outline-card').open = false;
    await click('viewer-mesh-deleter-load');
    await until('actual source mesh list', function () { return !ModelViewer.getState().meshTools.busy && document.getElementById('viewer-mesh-deleter-select').options.length > 1; });
    var option = Array.prototype.find.call(document.getElementById('viewer-mesh-deleter-select').options, function (item) { return item.value && !item.disabled; });
    assert(option, 'A real editable source mesh must be available');
    await input('viewer-mesh-modify-select', option.value, 'change');
    await until('actual source mesh binding', function () { var m = ModelViewer.getState().meshTools; return !m.busy && m.runtime.boundPrimitives > 0; });
    await input('viewer-mesh-modify-zoom', '4');
    await input('viewer-mesh-modify-vertex', '0'); await click('viewer-mesh-modify-select-vertex');
    var seed = state().meshTools;
    assert(equal(seed.selectedVertices, [0]), 'The real vertex selector must select source vertex0');
    await click('viewer-mesh-modify-connected');
    var connected = state().meshTools;
    assert(equal(connected.selectedVertices.slice().sort(function (a, b) { return a - b; }), [0, 1, 2, 3, 4, 5]),
      'Shared source edges expand the seed to all six vertices of this connected ribbon');
    var view = connected.textureViews.find(function (row) { return row.panel === 'viewer-mesh-modify'; });
    assert(view.zoom === 4 && view.x === -1.5 && view.y === -1.5, 'The actual UV view must zoom4 about its centre');
    await click('viewer-mesh-modify-undo');
    var undone = state().meshTools;
    assert(equal(undone.selectedVertices, [0]) && undone.textureViews.find(function (row) { return row.panel === 'viewer-mesh-modify'; }).zoom === 4,
      'Undo must restore the selection without changing the inspection zoom');
    await click('viewer-mesh-modify-redo'); assert(state().meshTools.selectedVertices.length === 6, 'Redo restores the connected component');
    await input('viewer-mesh-deleter-select', option.value, 'change');
    await input('viewer-mesh-deleter-zoom', '2');
    var views = state().meshTools.textureViews;
    assert(views.find(function (row) { return row.panel === 'viewer-mesh-deleter'; }).zoom === 2 && views.find(function (row) { return row.panel === 'viewer-mesh-modify'; }).zoom === 4,
      'Both mesh panels retain independent texture views');
    var colorBefore = ViewerUVColor.get(), colorState = state().meshTools;
    await input('viewer-mesh-modify-uv-color', '#14b87a');
    assert(ViewerUVColor.get() === '#14b87a' && document.getElementById('viewer-mesh-deleter-uv-color').value === '#14b87a' &&
      localStorage.getItem('elichika.viewer.uv-color.v1') === '#14b87a', 'UV color controls must synchronize and persist the display preference');
    var colorAfter = state().meshTools;
    assert(equal(colorAfter.edits, colorState.edits) && equal(colorAfter.selectedVertices, colorState.selectedVertices) &&
      equal(colorAfter.textureViews, colorState.textureViews) && equal(ModelViewer.getAuthoringState(), authoring),
      'UV overlay colors cannot change mesh edits, selection, zoom or original texture data');
    await input('viewer-mesh-modify-uv-color', colorBefore);
    assert(ViewerUVColor.get() === colorBefore && document.getElementById('viewer-mesh-deleter-uv-color').value === colorBefore,
      'Restoring the display color must synchronize all inspectors');
    var uvColor = { before: colorBefore, chosen: '#14b87a', restored: ViewerUVColor.get(),
      persisted: localStorage.getItem('elichika.viewer.uv-color.v1'), authoringPreserved: true, viewsPreserved: true };
    assert(state().meshTools.edits.meshes.length === 0 && equal(ModelViewer.getAuthoringState(), authoring),
      'Viewing textures and selecting connected vertices must not write geometry or body edits');
    await click('viewer-mesh-modify-undo'); await click('viewer-mesh-modify-undo');
    await click('viewer-mesh-modify-fit-texture'); await click('viewer-mesh-deleter-fit-texture');
    document.getElementById('viewer-mesh-modify').open = false; document.getElementById('viewer-mesh-deleter').open = false;
    var mouthGpu = await mouthCentroidGpu();
    assert(equal(ModelViewer.getAuthoringState(), authoring) && equal(ModelViewer.getEditingMetadata().outlines, catalogue),
      'Independent GPU depth inspection must not alter the current source model or authoring');
    var rimlight = await rimlightPreview();
    assert(equal(ModelViewer.getAuthoringState(), authoring) && equal(ModelViewer.getEditingMetadata().outlines, catalogue),
      'Display-only Rim toggles and source reloads must retain the original catalogue and clean authoring');
    var probe = ModelViewer.renderProbe(33);
    assert(probe.ready && probe.glError === 0 && probe.nonBackgroundSamples >= 3, 'The actual native renderer must still draw the source');
    return { status: 'PASS', checks: { mouthCentroidDepth: true, absoluteOutline: true, sparseOutline: true, outlineUndoRedo: true, sourceCataloguePreserved: true,
      outlineSave: true, meshZoom: true, connectedSelection: true, selectionUndoRedo: true, viewOnlyPreservedGeometry: true },
      mouthGpu: mouthGpu, catalogue: catalogue, absolute: absolute, absoluteSaved: absoluteSaved, absoluteRecipe: absoluteRecipe, sparse: sparse, saved: saved, recipe: recipe, seed: seed, connected: connected, undone: undone,
      independentViews: views, uvColor: uvColor, rimlight: rimlight, modFaceDefault: modFaceDefault,
      finalAuthoring: clone(ModelViewer.getAuthoringState()), probe: probe,
      scope: 'Actual native WebView controls, absolute all-vertex red37 Save/Undo/Redo and sparse outline Save and connected source selection/UV zoom; no trusted-pinch or visible-outline-width pixel claim.' };
  }
  window.NativeDetailQa = { run: run };
}());

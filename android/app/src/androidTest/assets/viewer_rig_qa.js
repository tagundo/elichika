/* Test-only observers and real framebuffer comparisons for the neutral Unity rig.
 * This creates no scene, mesh, material, camera or renderer. Every draw and UI
 * operation belongs to the application's existing viewer.
 */
(function () {
  "use strict";
  var parsedModel = null;
  var originalParse = window.THREE.GLTFLoader.prototype.parse;
  var observedClips = null;
  var originalRigCreate = window.ViewerRig.create;
  var frames = {};
  var contextExtension = null;

  function observedParse(data, path, onLoad, onError) {
    return originalParse.call(this, data, path, function (gltf) {
      parsedModel = gltf.scene;
      return onLoad.apply(this, arguments);
    }, onError);
  }
  window.THREE.GLTFLoader.prototype.parse = observedParse;
  function observedRigCreate(root, animations, info, options) {
    var clips = JSON.parse(JSON.stringify(info && info.clips || []));
    var controller = originalRigCreate.apply(this, arguments);
    observedClips = clips;
    return controller;
  }
  window.ViewerRig.create = observedRigCreate;

  function state() { return window.ModelViewer.getState(); }
  function element(id) {
    var result = document.getElementById(id);
    if (!result) throw new Error("Missing viewer control: " + id);
    return result;
  }
  function interactive(id) {
    var result = element(id);
    if (result.disabled) throw new Error("Viewer control is disabled: " + id);
    return result;
  }
  function minimumTarget(target) {
    var vertical = element("tab-viewer").classList.contains("viewer-vertical-controls");
    // Only the deliberately compact, always-visible viewport controls use the
    // smaller policy. Editing controls and popover contents still require 44px.
    var hud = target.closest(".viewer-pose-actions,.viewer-screen-actions,.viewer-camera-actions,.viewer-quality-choice") ||
      target.matches("#viewer-info > summary,#viewer-view-menu > summary,#viewer-workspace-menu > summary");
    return vertical && hud ? 32 : 44;
  }
  function control(id, scroll) {
    var target = typeof id === "string" ? element(id) : id;
    if (!target) throw new Error("Missing viewer control target");
    if (scroll) target.scrollIntoView({ block: "center" });
    var rectangle = target.getBoundingClientRect(), style = window.getComputedStyle(target);
    var x = rectangle.left + rectangle.width / 2, y = rectangle.top + rectangle.height / 2;
    var top = document.elementFromPoint(x, y);
    return { id: target.id || target.tagName, text: target.textContent.trim(), disabled: !!target.disabled,
      pressed: target.getAttribute("aria-pressed"), width: rectangle.width, height: rectangle.height,
      left: rectangle.left, top: rectangle.top, right: rectangle.right, bottom: rectangle.bottom,
      minimumTarget: minimumTarget(target),
      visible: rectangle.width > 0 && rectangle.height > 0 && style.display !== "none" &&
        style.visibility !== "hidden" && Number(style.opacity) !== 0,
      withinViewport: rectangle.left >= 0 && rectangle.top >= 0 &&
        rectangle.right <= window.innerWidth && rectangle.bottom <= window.innerHeight,
      hittable: top === target || !!(top && target.contains(top)) };
  }
  function requireTarget(target, allowDisabled) {
    var result = control(target, true);
    if ((!allowDisabled && result.disabled) || !result.visible || !result.withinViewport ||
        !result.hittable || result.width < result.minimumTarget || result.height < result.minimumTarget) {
      throw new Error("Expected the visible unobstructed viewer target to meet its explicit size policy: " + JSON.stringify(result));
    }
    return result;
  }
  function withViewMenu(open, action) {
    var menu = element("viewer-view-menu"), content = element("viewer-view-menu-content");
    var prior = { open: menu.open,
      x: window.scrollX, y: window.scrollY, left: content.scrollLeft, top: content.scrollTop };
    function setOpen(value, restore) {
      // compactControls now describes the file list/variant layout. It no
      // longer means the always-visible pose and quality controls were moved.
      var containsControls = menu.contains(element("viewer-pose-actions"));
      if (value && !restore && !containsControls || menu.open === value) return;
      var summary = menu.querySelector("summary");
      if (!summary || !summary.textContent.trim()) throw new Error("View controls needs an accessible summary");
      requireTarget(summary, false);
      if (menu.open !== value) summary.click();
      if (menu.open !== value) throw new Error("The actual View controls summary did not toggle its menu");
    }
    try {
      setOpen(open, false);
      return action();
    } finally {
      // Preserve a previously opened variant menu without opening an unrelated
      // menu just to use the directly reachable HUD controls.
      setOpen(prior.open, true);
      content.scrollLeft = prior.left; content.scrollTop = prior.top;
      window.scrollTo(prior.x, prior.y);
    }
  }
  function viewControl(id, allowDisabled) {
    var input = element(id), target = id === "viewer-high-quality" ? input.closest("label") || input : input;
    var compact = !!state().layout.compactControls, inside = element("viewer-view-menu").contains(target);
    var vertical = element("tab-viewer").classList.contains("viewer-vertical-controls");
    if (inside !== (!vertical && compact)) throw new Error("View control placement must match the actual visible HUD policy: " + id);
    var result = requireTarget(target, !!allowDisabled);
    result.disabled = !!input.disabled; result.compactControls = compact; result.insideViewMenu = inside;
    if (!allowDisabled && input.disabled) throw new Error("Viewer control is disabled: " + id);
    return result;
  }
  function context() {
    var canvas = element("viewer-canvas");
    var gl = canvas.getContext("webgl2") || canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
    if (!gl) throw new Error("The real WebGL context is unavailable");
    return gl;
  }
  function cameraDelta(first, second) {
    if (!first || !second) return Infinity;
    var maximum = Math.abs(first.fov - second.fov);
    ["position", "target"].forEach(function (name) {
      for (var index = 0; index < 3; index += 1) maximum = Math.max(maximum, Math.abs(first[name][index] - second[name][index]));
    });
    return maximum;
  }
  function capture(saveAs, compareWith) {
    return withViewMenu(false, function () { return capturePixels(saveAs, compareWith); });
  }
  function capturePixels(saveAs, compareWith) {
    var probe = window.ModelViewer.renderProbe(33);
    if (!probe.ready || probe.glError !== 0) throw new Error("The application's real render failed: " + JSON.stringify(probe));
    var gl = context(), width = gl.drawingBufferWidth, height = gl.drawingBufferHeight;
    var bytes = width * height * 4;
    if (width < 2 || height < 2 || bytes > 32 * 1024 * 1024) throw new Error("Frame comparison exceeds its 32 MiB RGBA read limit");
    var pixels = new Uint8Array(bytes);
    // The product just rendered this scene. Read in this same JavaScript turn,
    // before a non-preserved drawing buffer can be presented or cleared.
    gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    var error = gl.getError();
    if (error !== 0) throw new Error("Actual framebuffer read error " + error);
    var background = (width + 1) * 4, foreground = 0, hash = 2166136261;
    var foregroundMinimumY = height, foregroundMaximumY = -1;
    for (var offset = 0; offset < pixels.length; offset += 4) {
      if (Math.abs(pixels[offset] - pixels[background]) + Math.abs(pixels[offset + 1] - pixels[background + 1]) +
          Math.abs(pixels[offset + 2] - pixels[background + 2]) > 24) {
        foreground += 1;
        var foregroundY = Math.floor(offset / (width * 4));
        foregroundMinimumY = Math.min(foregroundMinimumY, foregroundY);
        foregroundMaximumY = Math.max(foregroundMaximumY, foregroundY);
      }
      hash = Math.imul(hash ^ pixels[offset], 16777619);
      hash = Math.imul(hash ^ pixels[offset + 1], 16777619);
      hash = Math.imul(hash ^ pixels[offset + 2], 16777619);
    }
    var current = state(), compared = null;
    if (compareWith) {
      var reference = frames[compareWith];
      if (!reference) throw new Error("Missing actual reference frame: " + compareWith);
      if (reference.width !== width || reference.height !== height) throw new Error("The viewport changed during framebuffer comparison");
      var changed = 0, maximum = 0;
      for (var index = 0; index < pixels.length; index += 4) {
        var red = Math.abs(pixels[index] - reference.pixels[index]);
        var green = Math.abs(pixels[index + 1] - reference.pixels[index + 1]);
        var blue = Math.abs(pixels[index + 2] - reference.pixels[index + 2]);
        if (red + green + blue > 24) changed += 1;
        maximum = Math.max(maximum, red, green, blue);
      }
      compared = { reference: compareWith, changedPixels: changed, maximumChannelDifference: maximum,
        cameraMaximumDifference: cameraDelta(current.camera, reference.camera) };
    }
    var center = (Math.floor(height / 2) * width + Math.floor(width / 2)) * 4;
    var result = { probe: probe, width: width, height: height, bytesRead: bytes, readPixelsCalls: 1,
      foregroundPixels: foreground, foregroundPixelHeight: foreground ? foregroundMaximumY - foregroundMinimumY + 1 : 0, pixelHash: (hash >>> 0).toString(16),
      centerRGB: [pixels[center], pixels[center + 1], pixels[center + 2]], glError: error,
      camera: current.camera, difference: compared };
    if (saveAs) frames[saveAs] = { pixels: pixels, width: width, height: height,
      camera: JSON.parse(JSON.stringify(current.camera)) };
    return result;
  }
  function deformedVertices(expectedCount) {
    if (expectedCount === undefined) expectedCount = 6;
    if (!Number.isInteger(expectedCount) || expectedCount <= 0) throw new Error("Expected a positive integer neutral fixture vertex count");
    if (!parsedModel) throw new Error("The actual loaded GLTF scene was not observed");
    var source = [];
    parsedModel.updateMatrixWorld(true);
    parsedModel.traverse(function (child) {
      if (child.isMesh && !(child.userData && child.userData.viewerHelper === true)) source.push(child);
    });
    if (source.length !== 1 || !source[0].isSkinnedMesh) throw new Error("The neutral fixture must use its real skin");
    var mesh = source[0], attribute = mesh.geometry.attributes.position;
    if (attribute.count !== expectedCount) throw new Error("Unexpected neutral fixture geometry");
    mesh.skeleton.update();
    var points = [];
    for (var vertex = 0; vertex < attribute.count; vertex += 1) {
      var point = new window.THREE.Vector3().fromBufferAttribute(attribute, vertex);
      mesh.boneTransform(vertex, point);
      points.push(point.applyMatrix4(mesh.matrixWorld).toArray());
    }
    return { vertices: points, jointCount: mesh.skeleton.bones.length, mesh: mesh.name };
  }
  function verticalViewport(readPixels) {
    if (!parsedModel) throw new Error("The application's real loaded scene is unavailable");
    var selectors = ["#viewer-pose-basic", "#viewer-pose-preview", ".viewer-quality-choice",
      "#viewer-expand", "#viewer-fullscreen", "#viewer-minimize", '[data-viewer-view="front"]', '[data-viewer-view="back"]',
      '[data-viewer-view="left"]', '[data-viewer-view="right"]', "#viewer-fit", "#viewer-info > summary"];
    var controls = selectors.map(function (selector) {
      var target = document.querySelector(selector);
      if (!target) throw new Error("Missing retained viewport action: " + selector);
      var result = control(target, false); result.selector = selector; return result;
    });
    var overlapPairs = [];
    controls.forEach(function (first, index) {
      controls.slice(index + 1).forEach(function (second) {
        if (Math.min(first.right, second.right) - Math.max(first.left, second.left) > .5 &&
            Math.min(first.bottom, second.bottom) - Math.max(first.top, second.top) > .5) {
          overlapPairs.push([first.selector, second.selector]);
        }
      });
    });
    var current = state(), canvas = element("viewer-canvas"), stage = canvas.getBoundingClientRect();
    var result = { vertical: element("tab-viewer").classList.contains("viewer-vertical-controls"),
      controls: controls, overlapPairs: overlapPairs, layout: current.layout };
    if (!readPixels) return result;
    var probe = window.ModelViewer.renderProbe(33);
    if (!probe.ready || probe.glError !== 0) throw new Error("The real viewer must render for layout QA");
    var gl = context(), width = gl.drawingBufferWidth, height = gl.drawingBufferHeight;
    if (width * height * 4 > 32 * 1024 * 1024) throw new Error("Viewport pixel QA exceeds its existing 32 MiB limit");
    var pixels = new Uint8Array(width * height * 4);
    gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    var background = (width + 1) * 4, covered = 0;
    controls.forEach(function (box) {
      var count = 0, left = Math.max(0, Math.floor((box.left - stage.left) / stage.width * width));
      var right = Math.min(width, Math.ceil((box.right - stage.left) / stage.width * width));
      var top = Math.max(0, Math.floor((box.top - stage.top) / stage.height * height));
      var bottom = Math.min(height, Math.ceil((box.bottom - stage.top) / stage.height * height));
      for (var y = top; y < bottom; y += 1) for (var x = left; x < right; x += 1) {
        var offset = ((height - 1 - y) * width + x) * 4;
        if (Math.abs(pixels[offset] - pixels[background]) + Math.abs(pixels[offset + 1] - pixels[background + 1]) +
            Math.abs(pixels[offset + 2] - pixels[background + 2]) > 24) count += 1;
      }
      box.coveredModelPixels = count; covered += count;
    });
    // Project the observed source scene's current skin/morph vertices using
    // the product camera snapshot. This creates no second camera or renderer.
    var camera = current.camera, position = new window.THREE.Vector3().fromArray(camera.position);
    var view = position.clone().sub(new window.THREE.Vector3().fromArray(camera.target)).normalize();
    var rightVector = new window.THREE.Vector3().crossVectors(new window.THREE.Vector3(0, 1, 0), view).normalize();
    var up = new window.THREE.Vector3().crossVectors(view, rightVector).normalize();
    var tangentY = Math.tan(camera.fov * Math.PI / 360), tangentX = tangentY * stage.width / stage.height;
    var projected = { count: 0, outside: 0, left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity };
    parsedModel.updateMatrixWorld(true);
    parsedModel.traverseVisible(function (mesh) {
      if (!mesh.isMesh || mesh.userData && mesh.userData.viewerHelper) return;
      var attribute = mesh.geometry && mesh.geometry.attributes.position;
      if (!attribute) return;
      if (mesh.isSkinnedMesh) mesh.skeleton.update();
      var morphs = mesh.geometry.morphAttributes.position || [], weights = mesh.morphTargetInfluences || [];
      for (var vertex = 0; vertex < attribute.count; vertex += 1) {
        var base = new window.THREE.Vector3().fromBufferAttribute(attribute, vertex), point = base.clone();
        morphs.forEach(function (morph, index) {
          if (!weights[index]) return;
          var delta = new window.THREE.Vector3().fromBufferAttribute(morph, vertex);
          if (!mesh.geometry.morphTargetsRelative) delta.sub(base);
          point.addScaledVector(delta, weights[index]);
        });
        if (mesh.isSkinnedMesh) mesh.boneTransform(vertex, point);
        point.applyMatrix4(mesh.matrixWorld).sub(position);
        var depth = -point.dot(view);
        var x = (.5 + point.dot(rightVector) / (2 * depth * tangentX)) * stage.width;
        var y = (.5 - point.dot(up) / (2 * depth * tangentY)) * stage.height;
        projected.count += 1;
        if (!(depth > 0) || x < -.5 || y < -.5 || x > stage.width + .5 || y > stage.height + .5) projected.outside += 1;
        projected.left = Math.min(projected.left, x); projected.right = Math.max(projected.right, x);
        projected.top = Math.min(projected.top, y); projected.bottom = Math.max(projected.bottom, y);
      }
    });
    result.projectedVertices = projected; result.coveredModelPixels = covered;
    result.framebuffer = { width: width, height: height, glError: gl.getError(), sourceTriangles: probe.sourceTriangles };
    return result;
  }
  function nodeId(name) {
    var matches = state().rig.bones.filter(function (bone) {
      return bone.name === name || bone.name.slice(-(name.length + 1)) === "/" + name;
    });
    if (matches.length !== 1) throw new Error("The real rig must have exactly one " + name + " bone");
    return matches[0].node;
  }
  function nodeOption(id) {
    var select = element("viewer-node"), value = String(id);
    function contains() {
      return Array.prototype.some.call(select.options, function (option) { return option.value === value; });
    }
    // The product's default list follows the active Node/Mesh workspace.
    // Legacy geometry checks explicitly request arbitrary bones, so use its
    // real advanced All bones filter only when that target is not listed.
    if (!contains()) {
      var filter = interactive("viewer-node-filter");
      filter.value = "all";
      filter.dispatchEvent(new Event("change", { bubbles: true }));
    }
    if (!contains()) throw new Error("The requested source bone is unavailable in All bones: " + value);
    return interactive("viewer-node");
  }
  function nodeWorld(name) {
    if (!parsedModel) throw new Error("The application's real loaded scene is unavailable");
    parsedModel.updateMatrixWorld(true);
    var id = String(nodeId(name)), matches = [];
    parsedModel.traverse(function (object) {
      if (!(object.userData && object.userData.viewerHelper) && object.userData &&
          String(object.userData.elichika_node) === id) matches.push(object);
    });
    if (matches.length !== 1) throw new Error("The actual scene must have exactly one source node " + name);
    var target = matches[0], values = target.matrixWorld.toArray();
    return { node: id, name: name, matrix: values,
      position: values.slice(12, 15),
      linear: [values[0], values[1], values[2], values[4], values[5], values[6], values[8], values[9], values[10]],
      localScale: target.scale.toArray(), localPosition: target.position.toArray(),
      localQuaternion: target.quaternion.toArray(), matrixAutoUpdate: target.matrixAutoUpdate };
  }
  async function unknownMotionPhysicsTransitions() {
    function assert(value, message) { if (!value) throw new Error(message); }
    function clone(value) { return JSON.parse(JSON.stringify(value)); }
    function equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
    function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }
    async function settle() {
      await new Promise(function (resolve) { requestAnimationFrame(function () { requestAnimationFrame(resolve); }); });
    }
    function snapshot() {
      var current = state();
      return clone({ physics: current.rig.physics, playing: current.rig.playing, time: current.rig.time,
        selectedClip: current.rig.selectedClip, bones: current.rig.bones, camera: current.camera,
        authoring: ModelViewer.getAuthoringState(), catalogue: ModelViewer.getEditingMetadata().physics,
        controls: { profile: element("viewer-physics-profile").value,
          skirtCorrection: element("viewer-physics-skirt-correction").value,
          motionCorrection: element("viewer-physics-motion-correction").value,
          frameRate: element("viewer-physics-frame-rate").value,
          mode: element("viewer-physics-mode").value } });
    }
    function usable(id) {
      var target = interactive(id);
      for (var parent = target.parentElement; parent; parent = parent.parentElement) if (parent.tagName === "DETAILS") parent.open = true;
      var actual = control(id, true);
      assert(actual.visible && actual.withinViewport && actual.hittable, "Actual transition control must be visible and usable: " + id + " " + JSON.stringify(actual));
      return target;
    }
    async function input(id, value, event) {
      var target = usable(id); target.value = String(value);
      target.dispatchEvent(new Event(event || "change", { bubbles: true })); await settle();
    }
    async function click(id) { usable(id).click(); await settle(); }
    async function until(message, condition) {
      var deadline = Date.now() + 30000;
      while (Date.now() < deadline) { if (condition()) return; await wait(25); }
      throw new Error("Timed out: " + message + " " + JSON.stringify(snapshot()));
    }
    function ready(observed, kind) {
      var physics = observed.physics, solver = physics.solver;
      assert(observed.controls.profile === "auto" && observed.controls.skirtCorrection === "auto" && observed.controls.motionCorrection === "auto",
        "The transition must use AUTO profile, costume and motion settings without manual overrides");
      assert(physics.mode === "game" && solver.available && solver.initialized && !solver.unsupported.length && !solver.initializationMissing.length,
        "Missing optional metadata must not disable the original core: " + JSON.stringify(solver));
      assert(solver.nativeCatalogAvailable === observed.catalogue.native.available,
        "The original raw catalogue availability diagnostic must be retained");
      assert(solver.bones.length > 0 && solver.bones.every(function (bone) {
        return [bone.origin, bone.tip].every(function (vector) { return vector.length === 3 && vector.every(Number.isFinite); });
      }), "The original core must expose finite native vectors");
      assert(physics.runtime.profile === (kind === "raw" ? "navi" : "live") &&
        solver.runtimeProfile.job === (kind === "raw" ? "SwingBoneJob" : "SwingBoneGroupJob"), "AUTO must select the actual motion category's original job");
      var missing = solver.skirtCorrectionMissing;
      assert(Array.isArray(missing), "Optional skirt inputs need an explicit separate diagnostic");
      assert((missing.indexOf("motion-skirt-runtime") >= 0) === (kind === "unknown"),
        "Only the metadata-unknown MV may retain the missing motion correction diagnostic: " + JSON.stringify(missing));
      if (kind !== "raw") assert(missing.some(function (reason) { return reason.indexOf("source-skirt-runtime:") === 0; }),
        "The generated costume's unknown source flags must remain explicit");
      assert(kind === "unknown" ? !Object.prototype.hasOwnProperty.call(physics.runtime, "safeSwingBone") : physics.runtime.safeSwingBone === false,
        "Unknown motion flags must remain unknown rather than using a QA/manual fallback");
    }
    async function advance(kind) {
      var before = snapshot(); ready(before, kind);
      await click("viewer-play");
      await until("native core advances for " + kind, function () {
        var current = state().rig;
        return current.playing && current.time > .15 && current.physics.solver.totalNativeSteps >= before.physics.solver.totalNativeSteps + 3;
      });
      await click("viewer-play"); var after = snapshot(); ready(after, kind);
      var changed = after.physics.solver.bones.some(function (bone, index) {
        return bone.tip.some(function (value, axis) { return Math.abs(value - before.physics.solver.bones[index].tip[axis]) > 1e-7; });
      });
      assert(!after.playing && after.physics.solver.totalNativeSteps > before.physics.solver.totalNativeSteps && changed,
        "Actual Play must advance original steps and native tips, then pause");
      return { before: before, after: after, changedNativeTip: changed };
    }
    var before = snapshot(), checkpoint = ModelViewer.captureCheckpoint();
    assert(!before.playing && observedClips, "Observe the actual loaded rig metadata before the transition");
    var clips = observedClips.filter(function (clip) { return clip.name === before.selectedClip; });
    assert(clips.length === 1 && /^[a-f0-9]{64}$/.test(clips[0].sourceHash) && typeof clips[0].sourceName === "string" &&
      Number.isFinite(clips[0].duration) && clips[0].duration > .2, "Use one genuine loaded source clip identity and duration");
    var source = clone(clips[0]), sources = before.catalogue.native.runtime.sources;
    assert(sources.length > 0 && sources.every(function (row) { return row.known === false && row.skirtsafeDisable === null; }),
      "The generated fixture must not be promoted to an official Game Asset identity");
    function descriptor(known) {
      var identity = { sourceHash: source.sourceHash, sourceName: source.sourceName };
      var value = { version: 2, category: "mv", motion: known ? "qa-native-known" : "qa-native-unknown",
        label: known ? "QA source-bound known motion flag" : "QA source-bound unknown motion flag", performerPosition: 1,
        clipSources: [identity], bodySegments: [Object.assign({ start: 0, duration: source.duration, clipIn: 0, timeScale: 1 }, identity)],
        facialClips: [], facial: { duration: source.duration, events: [] } };
      if (known) value.physics = { profile: "live", safeSwingBoneKnown: true, safeSwingBone: false };
      return value;
    }
    var known = descriptor(true), unknown = descriptor(false);
    var knownName = ModelViewer.setMotionTimeline(known).clipName;
    var unknownName = ModelViewer.setMotionTimeline(unknown).clipName;
    await input("viewer-physics-skirt-correction", "auto");
    await input("viewer-physics-motion-correction", "auto");
    await input("viewer-physics-profile", "auto");
    await input("viewer-motion", knownName); var firstKnown = await advance("known");
    await input("viewer-motion", unknownName); var unknownAdvance = await advance("unknown"), paused = snapshot();
    await wait(250); var held = snapshot();
    assert(!held.playing && held.time === paused.time && equal(held.physics.solver.bones, paused.physics.solver.bones) && equal(held.bones, paused.bones),
      "Paused unknown-metadata inspection must preserve native vectors, pose and time");
    ["totalNativeSteps", "resets", "initializationGeneration", "dynamicGeneration"].forEach(function (key) {
      assert(held.physics.solver[key] === paused.physics.solver[key], "Paused unknown inspection preserves " + key);
    });
    await input("viewer-time", "0", "input"); var reset = snapshot(); ready(reset, "unknown");
    assert(!reset.playing && reset.time === 0 && reset.physics.solver.resets > held.physics.solver.resets,
      "Actual seek-to-zero must reset the unknown-metadata core without disabling it");
    var afterReset = await advance("unknown");
    await input("viewer-motion", knownName); var returnedKnown = await advance("known");
    // Registered timelines intentionally hide their raw sources. Restore the
    // public source-bound checkpoint rather than inserting a fake option or
    // changing product clip visibility, then exercise its genuine raw clip.
    assert(await ModelViewer.restoreCheckpoint(checkpoint), "Restore the original source-bound model checkpoint");
    await until("the original checkpoint model and raw clip", function () {
      var current = state();
      return current.loaded && !current.loading && Array.prototype.some.call(element("viewer-motion").options,
        function (option) { return option.value === before.selectedClip; });
    });
    await input("viewer-physics-skirt-correction", "auto");
    await input("viewer-physics-motion-correction", "auto");
    await input("viewer-physics-profile", "auto");
    await input("viewer-motion", before.selectedClip); var returnedRaw = await advance("raw");
    await input("viewer-physics-profile", before.controls.profile);
    await input("viewer-physics-skirt-correction", before.controls.skirtCorrection);
    await input("viewer-physics-motion-correction", before.controls.motionCorrection);
    await input("viewer-physics-frame-rate", before.controls.frameRate);
    await input("viewer-time", String(before.time), "input"); var restored = snapshot();
    assert(!restored.playing && restored.selectedClip === before.selectedClip && Math.abs(restored.time - before.time) < 1e-7 &&
      equal(restored.controls, before.controls) && equal(restored.camera, before.camera),
      "Restore the original paused clip, time, camera and preview settings");
    [firstKnown.after, unknownAdvance.after, held, reset, afterReset.after, returnedKnown.after, returnedRaw.after, restored].forEach(function (observed) {
      assert(equal(observed.authoring, before.authoring) && equal(observed.catalogue, before.catalogue),
        "All transitions must preserve user authoring and the original source catalogue");
    });
    return { status: "PASS", fullAuto: true, sourceClip: source, knownDescriptor: known, unknownDescriptor: unknown,
      originalCostumeSources: clone(sources), knownFlagIsGeneratedQA: true,
      known: firstKnown, unknown: unknownAdvance, paused: paused, held: held,
      reset: reset, afterReset: afterReset, returnedKnown: returnedKnown, returnedRaw: returnedRaw,
      rawRestoration: "original source-bound public checkpoint", restored: restored,
      authoringAndSourcePreserved: true, originalPreviewRestored: true,
      scope: "Actual source-bound QA motion aliases and UI Play use original jobs in full AUTO. The known flag is explicitly generated QA metadata, not an official song DB flag; the costume remains unknown. This fixture retains its real resolved knees; separate numerical fixtures cover missing knee extras." };
  }
  window.ViewerRigQa = {
    capture: capture, deformedVertices: deformedVertices, nodeId: nodeId, nodeWorld: nodeWorld, control: control,
    verticalViewport: verticalViewport,
    sourceClips: function () { return JSON.parse(JSON.stringify(observedClips)); },
    unknownMotionPhysicsTransitions: unknownMotionPhysicsTransitions,
    withViewControls: function (action) { return withViewMenu(true, action); },
    withViewMenuClosed: function (action) { return withViewMenu(false, action); },
    viewControl: viewControl,
    input: function (id, value, event) {
      if (id === "viewer-node") nodeOption(value);
      if (id === "viewer-expression-value") {
        element("viewer-expression-advanced").open = true;
        var select = interactive("viewer-expression");
        if (!select.value) {
          var first = Array.prototype.filter.call(select.options, function (option) { return !!option.value; })[0];
          if (!first) throw new Error("The original expression channel selector has no usable target");
          select.value = first.value; select.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }
      var target = interactive(id); target.value = String(value);
      target.dispatchEvent(new Event(event || "input", { bubbles: true }));
      return state();
    },
    click: function (id) { interactive(id).click(); return state(); },
    boneInput: function (bone, kind, axis, value) {
      var valueId = nodeId(bone), select = nodeOption(valueId); select.value = valueId;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      var target = document.querySelector('[data-viewer-node-kind="' + kind + '"][data-axis="' + axis + '"]');
      if (!target || target.disabled) throw new Error("The actual bone input is unavailable");
      target.value = String(value); target.dispatchEvent(new Event("input", { bubbles: true }));
      return state();
    },
    loseContext: function () {
      contextExtension = context().getExtension("WEBGL_lose_context");
      if (!contextExtension) throw new Error("The native WebGL driver does not support actual context-loss QA");
      contextExtension.loseContext();
    },
    restoreContext: function () {
      if (!contextExtension) throw new Error("No real lost WebGL context was retained");
      contextExtension.restoreContext();
    },
    drop: function (label) { delete frames[label]; },
    dispose: function () {
      if (window.THREE.GLTFLoader.prototype.parse === observedParse) window.THREE.GLTFLoader.prototype.parse = originalParse;
      if (window.ViewerRig.create === observedRigCreate) window.ViewerRig.create = originalRigCreate;
      frames = {}; parsedModel = null; contextExtension = null; observedClips = null;
    }
  };
}());

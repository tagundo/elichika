/* Test-only observers and real framebuffer comparisons for the neutral Unity rig.
 * This creates no scene, mesh, material, camera or renderer. Every draw and UI
 * operation belongs to the application's existing viewer.
 */
(function () {
  "use strict";
  var parsedModel = null;
  var originalParse = window.THREE.GLTFLoader.prototype.parse;
  var frames = {};
  var contextExtension = null;

  function observedParse(data, path, onLoad, onError) {
    return originalParse.call(this, data, path, function (gltf) {
      parsedModel = gltf.scene;
      return onLoad.apply(this, arguments);
    }, onError);
  }
  window.THREE.GLTFLoader.prototype.parse = observedParse;

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
    for (var offset = 0; offset < pixels.length; offset += 4) {
      if (Math.abs(pixels[offset] - pixels[background]) + Math.abs(pixels[offset + 1] - pixels[background + 1]) +
          Math.abs(pixels[offset + 2] - pixels[background + 2]) > 24) foreground += 1;
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
      foregroundPixels: foreground, pixelHash: (hash >>> 0).toString(16),
      centerRGB: [pixels[center], pixels[center + 1], pixels[center + 2]], glError: error,
      camera: current.camera, difference: compared };
    if (saveAs) frames[saveAs] = { pixels: pixels, width: width, height: height,
      camera: JSON.parse(JSON.stringify(current.camera)) };
    return result;
  }
  function deformedVertices() {
    if (!parsedModel) throw new Error("The actual loaded GLTF scene was not observed");
    var source = [];
    parsedModel.updateMatrixWorld(true);
    parsedModel.traverse(function (child) {
      if (child.isMesh && !(child.userData && child.userData.viewerHelper === true)) source.push(child);
    });
    if (source.length !== 1 || !source[0].isSkinnedMesh) throw new Error("The neutral fixture must use its real skin");
    var mesh = source[0], attribute = mesh.geometry.attributes.position;
    if (attribute.count !== 6) throw new Error("Unexpected neutral fixture geometry");
    mesh.skeleton.update();
    var points = [];
    for (var vertex = 0; vertex < attribute.count; vertex += 1) {
      var point = new window.THREE.Vector3().fromBufferAttribute(attribute, vertex);
      mesh.boneTransform(vertex, point);
      points.push(point.applyMatrix4(mesh.matrixWorld).toArray());
    }
    return { vertices: points, jointCount: mesh.skeleton.bones.length, mesh: mesh.name };
  }
  function nodeId(name) {
    var matches = state().rig.bones.filter(function (bone) {
      return bone.name === name || bone.name.slice(-(name.length + 1)) === "/" + name;
    });
    if (matches.length !== 1) throw new Error("The real rig must have exactly one " + name + " bone");
    return matches[0].node;
  }
  window.ViewerRigQa = {
    capture: capture, deformedVertices: deformedVertices, nodeId: nodeId,
    input: function (id, value, event) {
      var target = interactive(id); target.value = String(value);
      target.dispatchEvent(new Event(event || "input", { bubbles: true }));
      return state();
    },
    click: function (id) { interactive(id).click(); return state(); },
    boneInput: function (bone, kind, axis, value) {
      var select = interactive("viewer-node"); select.value = nodeId(bone);
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
      frames = {}; parsedModel = null; contextExtension = null;
    }
  };
}());

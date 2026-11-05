/* Native QA observes actual driver allocations; it never changes product quality. */
(function () {
  "use strict";
  if (window.ViewerQualityQa) return;
  var observed = null, originalStorage = null, wrappedStorage = null, allocations = [], rejectedStorage = null;

  function attach() {
    var canvas = document.getElementById("viewer-canvas");
    if (!canvas) throw new Error("The real viewer canvas is unavailable");
    var gl = canvas.getContext("webgl2") || canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
    if (!gl) throw new Error("The actual viewer WebGL context is unavailable");
    if (gl !== observed) {
      observed = gl;
      if (typeof gl.renderbufferStorageMultisample === "function") {
        originalStorage = gl.renderbufferStorageMultisample;
        wrappedStorage = function (target, samples, format, width, height) {
          var result = originalStorage.apply(gl, arguments);
          allocations.push({ requestedSamples: samples, format: format,
            width: gl.getRenderbufferParameter(gl.RENDERBUFFER, gl.RENDERBUFFER_WIDTH),
            height: gl.getRenderbufferParameter(gl.RENDERBUFFER, gl.RENDERBUFFER_HEIGHT),
            actualSamples: gl.getRenderbufferParameter(gl.RENDERBUFFER, gl.RENDERBUFFER_SAMPLES) });
          if (allocations.length > 128) allocations.shift();
          return result;
        };
        gl.renderbufferStorageMultisample = wrappedStorage;
      }
    }
    return { canvas: canvas, gl: gl };
  }

  function snapshot() {
    var real = attach(), canvas = real.canvas, gl = real.gl;
    return { nativePixelRatio: window.devicePixelRatio || 1,
      canvasWidth: canvas.width, canvasHeight: canvas.height,
      drawingBufferWidth: gl.drawingBufferWidth, drawingBufferHeight: gl.drawingBufferHeight,
      contextSamples: gl.getParameter(gl.SAMPLES),
      contextAntialias: gl.getContextAttributes().antialias,
      allocations: allocations.slice(), quality: window.ModelViewer.getState().quality };
  }

  function control() {
    var input = document.getElementById("viewer-high-quality");
    if (!input) throw new Error("The high-quality control is unavailable");
    var label = input.closest("label") || input;
    label.scrollIntoView({ block: "center" });
    var r = label.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
    var hit = document.elementFromPoint(x, y);
    return { checked: input.checked, disabled: input.disabled, width: r.width, height: r.height,
      minimumTarget: document.getElementById("tab-viewer").classList.contains("viewer-vertical-controls") ? 32 : 44,
      withinViewport: r.left >= 0 && r.top >= 0 && r.right <= innerWidth + 1 && r.bottom <= innerHeight + 1,
      hittable: hit === label || label.contains(hit) };
  }

  window.ViewerQualityQa = {
    snapshot: snapshot, control: control,
    clear: function () { allocations = []; return snapshot(); },
    set: function (enabled) {
      var input = document.getElementById("viewer-high-quality");
      if (!input || input.disabled) throw new Error("The high-quality control is not interactive");
      if (input.checked !== enabled) (input.closest("label") || input).click();
    },
    rejectAllocations: function () {
      var gl = attach().gl;
      if (typeof gl.renderbufferStorageMultisample !== "function") throw new Error("This driver has no multisample allocator");
      rejectedStorage = gl.renderbufferStorageMultisample;
      var unsupportedSamples = gl.getParameter(gl.MAX_SAMPLES) + 1;
      gl.renderbufferStorageMultisample = function (target, samples, format, width, height) {
        return rejectedStorage.call(gl, target, unsupportedSamples, format, width, height);
      };
      return { unsupportedSamples: unsupportedSamples, maxSamples: gl.getParameter(gl.MAX_SAMPLES) };
    },
    restoreAllocations: function () {
      if (observed && rejectedStorage) observed.renderbufferStorageMultisample = rejectedStorage;
      rejectedStorage = null;
    },
    dispose: function () {
      if (observed && rejectedStorage) observed.renderbufferStorageMultisample = rejectedStorage;
      if (observed && observed.renderbufferStorageMultisample === wrappedStorage) observed.renderbufferStorageMultisample = originalStorage;
      observed = null; originalStorage = null; wrappedStorage = null; rejectedStorage = null; allocations = [];
      delete window.ViewerQualityQa;
    }
  };
}());

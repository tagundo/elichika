/* Test-only observations of the real, normal portrait viewer and its controls. */
(function () {
  "use strict";
  function element(id) { var value = document.getElementById(id); if (!value) throw new Error("Missing portrait control: " + id); return value; }
  function bounds(target) { var r = target.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height }; }
  function target() { return document.querySelector('[data-viewer-node-kind="scale"][data-axis="X"]'); }
  function snapshot() {
    var state = ModelViewer.getState(), stage = element("viewer-stage"), input = target(), header = document.querySelector("body > header");
    var h = header ? bounds(header) : { bottom: 0 }, r = input ? bounds(input) : null;
    var hit = r ? document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) : null;
    return { viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio, coarse: matchMedia("(pointer:coarse)").matches },
      scrollY: scrollY, stage: bounds(stage), stagePosition: getComputedStyle(stage).position, headerBottom: Math.max(0, h.bottom),
      modelId: state.modelId, camera: state.camera, authoring: ModelViewer.getAuthoringState(), layout: state.layout,
      selectedNode: state.rig.selectedNode, control: r && { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height,
        value: input.value, disabled: input.disabled, focused: document.activeElement === input,
        visible: r.width > 0 && r.height > 0 && getComputedStyle(input).visibility !== "hidden",
        withinViewport: r.left >= 0 && r.right <= innerWidth && r.top >= Math.max(0, h.bottom) + 8 && r.bottom <= innerHeight,
        hittable: hit === input || !!(hit && input.contains(hit)) } };
  }
  function requireControl(value) {
    if (!value || value.disabled || !value.visible || !value.withinViewport || !value.hittable || value.width < 44 || value.height < 44)
      throw new Error("Portrait input must be a visible unobstructed 44px target below the header: " + JSON.stringify(value));
  }
  window.ViewerPortraitQa = {
    setup: function () {
      var state = ModelViewer.getState();
      if (state.layout.expanded || state.layout.fullscreen !== "none" || state.layout.shortHeight || innerWidth >= 720 || innerHeight < 900)
        throw new Error("Portrait QA requires a real tall normal Android window");
      element("viewer-adjustments").open = true; element("viewer-node-editor").open = true;
      ViewerRigQa.input("viewer-node", ViewerRigQa.nodeId("BreastSize"), "change");
      ViewerRigQa.input("viewer-save-method", "mesh", "change");
      window.scrollTo(0, 0); return snapshot();
    },
    snapshot: snapshot,
    scrollContact: function (down) {
      var y = innerHeight * (down ? .8 : .25), candidates = [innerWidth - 2, 2];
      for (var i = 0; i < candidates.length; i += 1) {
        var hit = document.elementFromPoint(candidates[i], y);
        if (hit && !hit.closest("canvas,input,select,button,summary,[role=separator]")) return { x: candidates[i], y: y, tag: hit.tagName };
      }
      throw new Error("The native page swipe must start outside the model and editing controls");
    },
    edit: function () {
      var before = snapshot(); requireControl(before.control);
      if (before.stage.bottom > before.headerBottom) throw new Error("The normal portrait model must scroll fully above the editor");
      var input = target(); input.focus(); input.value = "1.4"; input.dispatchEvent(new Event("input", { bubbles: true }));
      var current = snapshot(); requireControl(current.control);
      if (!current.control.focused || Math.abs(Number(current.control.value) - 1.4) > 1e-9) throw new Error("The visible actual portrait input must retain its focused edit");
      var bones = ModelViewer.getState().rig.bones.filter(function (bone) { return String(bone.node) === current.selectedNode; });
      if (bones.length !== 1 || Math.abs(bones[0].scale[0] - 1.4) > 1e-9 || !current.authoring.edits.length || current.authoring.unsupported.length)
        throw new Error("The visible control must create a valid pending edit in the real rig");
      return current;
    },
    blur: function () { if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); return snapshot(); },
    visibleStage: function () {
      var current = snapshot(), r = current.stage;
      if (r.top < current.headerBottom - 1 || r.bottom > innerHeight + 1 || r.width < 100 || r.height < 100) throw new Error("Scroll back to the complete actual model before viewport evidence");
      return { geometry: current, hud: ViewerRigQa.verticalViewport(false), probe: ModelViewer.renderProbe(33) };
    }
  };
})();

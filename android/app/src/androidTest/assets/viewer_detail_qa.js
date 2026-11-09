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
  async function run() {
    var initial = state(), catalogue = clone(ModelViewer.getEditingMetadata().outlines), authoring = clone(ModelViewer.getAuthoringState());
    assert(initial.loaded && !initial.loading && catalogue.available && catalogue.meshes.length === 1,
      'The real neutral source must provide one authorized outline mesh');
    assert(!(authoring.outlines || []).length && !authoring.edits.length, 'Start with a clean source model');
    var identity = catalogue.meshes[0].id;
    await input('viewer-outline-mesh', identity, 'change');
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
    assert(state().meshTools.edits.meshes.length === 0 && equal(ModelViewer.getAuthoringState(), authoring),
      'Viewing textures and selecting connected vertices must not write geometry or body edits');
    await click('viewer-mesh-modify-undo'); await click('viewer-mesh-modify-undo');
    await click('viewer-mesh-modify-fit-texture'); await click('viewer-mesh-deleter-fit-texture');
    document.getElementById('viewer-mesh-modify').open = false; document.getElementById('viewer-mesh-deleter').open = false;
    var probe = ModelViewer.renderProbe(33);
    assert(probe.ready && probe.glError === 0 && probe.nonBackgroundSamples >= 3, 'The actual native renderer must still draw the source');
    return { status: 'PASS', checks: { sparseOutline: true, outlineUndoRedo: true, sourceCataloguePreserved: true,
      outlineSave: true, meshZoom: true, connectedSelection: true, selectionUndoRedo: true, viewOnlyPreservedGeometry: true },
      catalogue: catalogue, sparse: sparse, saved: saved, recipe: recipe, seed: seed, connected: connected, undone: undone,
      independentViews: views, finalAuthoring: clone(ModelViewer.getAuthoringState()), probe: probe,
      scope: 'Actual native WebView controls, sparse outline Save and connected source selection/UV zoom; no trusted-pinch or visible-outline-width pixel claim.' };
  }
  window.NativeDetailQa = { run: run };
}());

/* QA only: actual automatic 3D thumbnail controls and installer ZIP save. */
(function () {
  'use strict';
  function assert(value, message) { if (!value) throw new Error(message); }
  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }
  async function settle() { await new Promise(function (resolve) { requestAnimationFrame(function () { requestAnimationFrame(resolve); }); }); }
  async function until(message, predicate) {
    var end = Date.now() + 150000;
    while (Date.now() < end) { if (predicate()) return; await wait(40); }
    throw new Error('Timed out: ' + message + ': ' + JSON.stringify(ModelViewer.getState().persistence));
  }
  function usable(id) {
    var target = document.getElementById(id); assert(target, 'Missing actual control ' + id);
    for (var p = target.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true;
    var control = ViewerRigQa.control(target, true);
    assert(!control.disabled && control.visible && control.withinViewport && control.hittable,
      'Actual thumbnail control must be usable: ' + JSON.stringify(control));
    return target;
  }
  async function input(id, value) { var target = usable(id); target.value = String(value); target.dispatchEvent(new Event('change', { bubbles: true })); await settle(); }
  async function click(id) { usable(id).click(); await settle(); }
  async function json(url) { var response = await fetch(url); var result = await response.json(); assert(response.ok && !result.error, 'Actual saved receipt unavailable: ' + url); return result; }
  function installs() { return performance.getEntriesByType('resource').filter(function (entry) { return entry.name.indexOf('/api/viewer/edit/install') >= 0; }).length; }
  function snapshot() {
    var state = ModelViewer.getState(), metadata = ModelViewer.getEditingMetadata(), rig = state.rig;
    return { modelId: state.modelId, editingToken: metadata.token, paths: clone(state.paths), loadedPaths: clone(state.loadedPaths),
      motionLibraryPaths: clone(state.motionLibraryPaths), sourceFingerprint: metadata.sourceFingerprint,
      authoring: clone(ModelViewer.getAuthoringState()),
      pose: { time: rig.time, selectedClip: rig.selectedClip, playing: rig.playing },
      characterId: Number(document.getElementById('viewer-mod-character').value),
      include_face_edits: !!document.getElementById('viewer-mod-include-face').checked,
      name: document.getElementById('viewer-mod-name').value,
      variant: document.getElementById('viewer-mod-variant').value || null,
      counterpartPath: document.getElementById('viewer-mod-counterpart').title || null };
  }
  async function run(options) {
    options = options || {}; var owner = options.characterId || 6;
    assert(window.ViewerThumbnails && typeof ViewerThumbnails.getState === 'function', 'The actual thumbnail renderer must be loaded');
    var original = ModelViewer.getState(), previousJob = original.persistence.jobId;
    assert(original.loaded && !original.loading && !original.persistence.busy && !original.rig.playing,
      'A loaded, paused, idle real model is required');
    if (options.reeditOriginal !== false) {
      assert(original.persistence.originalPaths.length && original.persistence.recipePath, 'First preserve the ordinary texture Mod ZIP save and its recipe');
      var oldId = original.modelId;
      await click('viewer-reedit-original');
      await until('the original model with its restored pending edits', function () {
        var state = ModelViewer.getState(); return state.loaded && !state.loading && !state.persistence.busy && !state.persistence.reviewingSaved && state.modelId !== oldId;
      }); await settle();
    }
    await input('viewer-mod-character', owner);
    await input('viewer-mod-thumbnail-mode', 'texture');
    assert(ModelViewer.getState().persistence.thumbnailMode === 'texture', 'The real texture option must remain available');
    await input('viewer-mod-thumbnail-mode', '3d');
    assert(ModelViewer.getState().persistence.thumbnailMode === '3d', 'The actual 3D thumbnail option must apply');
    var before = snapshot(), beforeInstalls = installs(), baselineJob = ModelViewer.getState().persistence.jobId;
    assert(before.sourceFingerprint && before.authoring.edits.length && !before.pose.playing && before.characterId === owner,
      'The 3D save must use the actual restored source, authored body edits and explicit member');
    await click('viewer-save-mod');
    await until('a fresh actual automatic 3D installer ZIP save', function () {
      var p = ModelViewer.getState().persistence;
      if (!p.busy && p.status === 'error') throw new Error(p.error || 'The actual 3D package save failed');
      return !p.busy && p.status === 'done' && p.jobId && p.jobId !== baselineJob && p.modPackage && p.modPackage.thumbnail;
    });
    await until('the decoded actual 3D thumbnail preview', function () {
      var image = document.getElementById('viewer-mod-thumbnail-preview'); return !image.hidden && image.complete && image.naturalWidth > 0;
    });
    var after = snapshot(), persistence = clone(ModelViewer.getState().persistence), last = clone(ViewerThumbnails.getState());
    var response = await json('/api/viewer/edit/result/' + persistence.jobId);
    var receipt = last.last && last.last.receipt, render = last.last && last.last.render, pack = response.mod_package;
    var image = document.getElementById('viewer-mod-thumbnail-preview'), profile = await json('/static/thumbnail-sdk/profile.json');
    var preview = { width: image.naturalWidth, height: image.naturalHeight, sha256: image.dataset.sha256, status: document.getElementById('viewer-mod-thumbnail-status').textContent };
    assert(!last.busy && last.last.count === 1 && last.last.total === 1 && receipt && render, 'One real viewer source must finish its automatic render');
    assert(receipt.characterId === owner && last.last.characterId === owner && receipt.size === last.last.size && receipt.size >= 64 && receipt.size <= 1024,
      'The source-bound receipt must identify the actual target member and supported output size');
    assert(/^[a-f0-9]{64}$/.test(receipt.sha256) && receipt.bytes > 0 && preview.sha256 === receipt.sha256 && preview.width === receipt.size && preview.height === receipt.size && /^data:image\/png;base64,/.test(image.src),
      'The decoded preview and actual PNG receipt must agree');
    assert(render.quality.enabled && render.quality.ready && Number.isFinite(render.quality.actualSamples) && render.quality.actualSamples >= 0 && render.subjectPixels > 0 && render.triangles > 0 && render.visibleMeshes > 0 && render.material.enabled,
      'Actual high-quality SifasMaterial WebGL rendering must contain visible source triangles');
    assert(receipt.quality.renderer === 'SifasMaterial' && receipt.quality.highQuality === true && receipt.quality.animation === false && receipt.quality.supersample === 2 && receipt.quality.rimlight === false && render.material.rimlightEnabled === false && render.pose === 'source-rest' && render.animation === false,
      'The real renderer must use the source-rest costume with the reviewed high-quality contract');
    assert(equal(render.camera, profile.camera) && Object.keys(profile.memberColors).length === 30 && profile.memberColors[String(owner)] && profile.layers.length === 3 && profile.innerMask === 'inner-mask.png' && profile.outerBorder === 'outer-border.png',
      'The actual SDK orthographic camera, member colors and five PSD layers must be used');
    assert(pack && pack.installable === true && pack.character_id === owner && pack.display_name === before.name && pack.thumbnail.mode === '3d' && pack.thumbnail.sha256 === receipt.sha256 && pack.thumbnail.characterId === owner && pack.thumbnail.profileDigest === receipt.profileDigest && pack.thumbnail.cacheKey === receipt.cacheKey && equal(pack.thumbnail.quality, receipt.quality),
      'The authoritative saved ZIP must bind the same rendered thumbnail and member');
    assert(persistence.modPackage.packagePath === pack.package_path && persistence.modPackage.thumbnail.sha256 === receipt.sha256 && response.output_paths.indexOf(pack.package_path) >= 0 && response.recipe && response.recipe_path && response.preview_paths.length,
      'The actual save job must publish its installer ZIP, edited model and source-bound recipe');
    assert(equal(before, after), 'Automatic thumbnail rendering and packaging must preserve the selected source, pending edits and paused preview');
    assert(beforeInstalls === installs() && !response.installed, 'Save mod ZIP must never request installation');
    return { status: 'PASS', checks: { modeControl: true, restoredEdits: true, freshSave: true, sdkCameraTemplate: true,
      highQuality3D: true, sourceRestPose: true, previewReceipt: true, packageThumbnail: true, sourceStatePreserved: true, noInstallRequested: true },
      options: { characterId: owner, reeditOriginal: options.reeditOriginal !== false }, previousJob: previousJob, jobId: persistence.jobId,
      before: before, after: after, persistence: persistence, receipt: receipt, render: render, last: last.last,
      preview: preview, previewPNG: image.src, profile: profile, response: response,
      installRequestsBefore: beforeInstalls, installRequestsAfter: installs(), probe: clone(ModelViewer.renderProbe(33)) };
  }
  window.NativeThumbnailQa = { run: run };
}());

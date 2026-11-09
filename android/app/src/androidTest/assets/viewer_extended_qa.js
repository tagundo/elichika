/* QA only: real neutral eye poses, physics editors and retained motion bank. */
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
    var target = typeof id === 'string' ? document.getElementById(id) : id; assert(target, 'Missing actual control ' + id);
    for (var p = target.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true;
    var control = ViewerRigQa.control(target, true);
    assert(!control.disabled && control.visible && control.withinViewport && control.hittable,
      'Actual editing control must be usable: ' + JSON.stringify(control));
    return target;
  }
  async function input(id, value, event) { var target = usable(id); target.value = String(value); target.dispatchEvent(new Event(event || 'input', { bubbles: true })); await settle(); }
  async function click(id) { usable(id).click(); await settle(); }
  function state() { return clone(ModelViewer.getState()); }
  function snapshot() { return { state: state(), authoring: clone(ModelViewer.getAuthoringState()), catalogue: clone(ModelViewer.getEditingMetadata().physics) }; }
  function eyeVectors(observed) { return observed.rig.bones.filter(function (bone) { return /(?:^|\/)(?:Left|Right)Eye[12]$/.test(bone.name); }).map(function (bone) { return { node: bone.node, position: bone.position, quaternion: bone.quaternion, scale: bone.scale }; }); }
  function values(record) {
    var result = clone(record.values), prefix = '[data-physics-component=' + JSON.stringify(record.id) + ']';
    document.querySelectorAll(prefix + '[data-physics-field]').forEach(function (field) {
      if (field.dataset.physicsAxis === undefined) result[field.dataset.physicsField] = Number(field.value);
      else result[field.dataset.physicsField][Number(field.dataset.physicsAxis)] = Number(field.value);
    }); return result;
  }
  async function open(path) {
    var old = ModelViewer.getState().modelId; await openModelViewer([path]);
    await until('the newly opened source model', function () { var s = ModelViewer.getState(); return s.loaded && !s.loading && s.modelId !== old; }); await settle();
  }
  async function run(paths) {
    assert(paths && paths.sourcePath && paths.motionPath && paths.otherBodyPath, 'Three explicit authorized source paths are required');
    var initial = snapshot(), catalogue = ModelViewer.getEditingMetadata().physics;
    assert(initial.state.stats.meshes === 1 && initial.state.stats.vertices === 6 && initial.state.stats.triangles === 4 && initial.state.rig.expressions.length === 0,
      'The new neutral fixture must retain the original ribbon and zero-morph contract');
    assert(initial.state.rig.physics.swingBone && initial.state.rig.physics.swingCollider && document.getElementById('viewer-physics-bones').checked && document.getElementById('viewer-physics-colliders').checked, 'Both physics switches must be enabled on a fresh model');
    var gaze = initial.state.rig.expressionPanel.gaze;
    assert(gaze && gaze.available && gaze.mode === 'motion', 'Real source eye pose clips must enable gaze, independently of morph channels');
    await input('viewer-gaze-mode', 'front', 'change'); var front = state(), frontEyes = eyeVectors(front);
    assert(frontEyes.length === 4, 'The source must expose four genuine eye joints');
    await input('viewer-gaze-mode', 'direction', 'change');
    await input('viewer-gaze-horizontal-number', '50'); await input('viewer-gaze-vertical-number', '-25'); await input('viewer-gaze-strength-number', '70');
    var directed = state(), directedEyes = eyeVectors(directed);
    assert(!equal(frontEyes, directedEyes), 'Real original-format eye pose clips must change actual source eye transforms');
    assert(directed.rig.time === front.rig.time && !directed.rig.playing, 'Paused gaze editing must not advance the playhead');
    assert(directed.rig.expressionPanel.gaze.mode === 'direction' && directed.rig.expressionPanel.gaze.horizontal === .5 && directed.rig.expressionPanel.gaze.vertical === -.25 && directed.rig.expressionPanel.gaze.strength === .7,
      'Actual gaze numeric controls must retain precise settings');
    await input('viewer-gaze-mode', 'front', 'change'); var returned = state();
    assert(equal(eyeVectors(returned), frontEyes), 'Front gaze restores the exact source eye transforms');
    await input('viewer-gaze-mode', 'camera', 'change'); var cameraGaze = state();
    assert(cameraGaze.rig.expressionPanel.gaze.mode === 'camera', 'The actual preview-camera gaze option must apply');
    await click('viewer-gaze-reset'); assert(state().rig.expressionPanel.gaze.mode === 'motion', 'Gaze reset restores authored-motion ownership');

    var breast = catalogue.components.find(function (row) { return row.kind === 'bone' && row.group === 'breast'; });
    assert(breast, 'The neutral source must contain a real editable breast SwingBone');
    await input('viewer-physics-component-kind', 'bone', 'change'); await input('viewer-physics-component-group', 'breast', 'change');
    await input('viewer-physics-component-search', breast.name);
    var rows = Array.prototype.filter.call(document.querySelectorAll('[data-physics-component-editor]'), function (row) { return !row.hidden; });
    assert(rows.length === 1 && rows[0].dataset.physicsComponentEditor === breast.id && document.getElementById('viewer-adjustments').contains(rows[0]),
      'Pose component filters must expose the genuine matching source component in the Pose panel');
    var base = values(breast), preset = catalogue.breastSizeRecommendations.presets.reduce(function (best, row) { return !best || row.tier > best.tier ? row : best; }, null);
    assert(preset && preset.tier > 0, 'The existing breast tool must provide independent size recommendations');
    await click('viewer-physics-breast-auto');
    ['X', 'Y', 'Z'].forEach(function (axis, index) { ViewerRigQa.boneInput('BreastSize', 'scale', axis, preset.scale[index]); }); await settle();
    var automated = snapshot(), limits = values(breast), tier = automated.state.rig.physics.breastAutoLimits.tiers.find(function (row) { return row.id === breast.id; });
    assert(automated.state.rig.physics.breastAutoLimits.enabled && tier && tier.applied && tier.tier === preset.tier, 'The selected real breast size must apply the verified tool tier');
    assert(limits.lowRotationLimit[0] === base.lowRotationLimit[0] && limits.highRotationLimit[0] === base.highRotationLimit[0], 'Automatic size recommendations must preserve X limits');
    [1, 2].forEach(function (axis) { assert(limits.lowRotationLimit[axis] === base.lowRotationLimit[axis] - preset.tier && limits.highRotationLimit[axis] === base.highRotationLimit[axis] + preset.tier, 'Automatic Y/Z limits expand once from the enabled baseline'); });
    await click('viewer-physics-breast-auto');
    assert(equal(values(breast), base) && !state().rig.physics.breastAutoLimits.enabled, 'Disabling automatic matching restores the exact enabled baseline');
    var drag = document.querySelector('[data-physics-component=' + JSON.stringify(breast.id) + '][data-physics-field=dragForce]');
    await input(drag, '.4');
    assert(values(breast).dragForce === .4 && ModelViewer.getAuthoringState().physics.some(function (row) { return row.id === breast.id && row.values.dragForce === .4; }),
      'A real filtered Pose component field must author its precise original physics value');
    await input('viewer-save-method', 'node', 'change');
    await input('viewer-gaze-mode', 'direction', 'change'); await input('viewer-gaze-horizontal-number', '40');
    var beforeLibrary = snapshot();
    await ModelViewer.addMotion([paths.motionPath]); await until('the imported motion bank', function () { var s = ModelViewer.getState(); return s.loaded && !s.loading && s.rig.clipNames.indexOf('Native library motion') >= 0; });
    var imported = snapshot();
    assert(equal(imported.state.paths, [paths.sourcePath]) && equal(imported.state.loadedPaths, [paths.sourcePath]) && equal(imported.state.motionLibraryPaths, [paths.motionPath]) && equal(imported.state.loadedMotionPaths, [paths.motionPath]),
      'The imported animation bank must remain separate from model/editing sources');
    assert(equal(imported.authoring, beforeLibrary.authoring) && equal(imported.state.rig.expressionPanel.gaze, beforeLibrary.state.rig.expressionPanel.gaze),
      'Adding motion to the same model must preserve all body/physics edits and manual gaze');
    await input('viewer-motion', 'Native library motion', 'change'); await click('viewer-play');
    await until('real playback of the retained imported clip', function () { var r = ModelViewer.getState().rig; return r.playing && r.selectedClip === 'Native library motion' && r.time > .2; });
    await click('viewer-play'); var played = snapshot();
    await open(paths.otherBodyPath); var other = snapshot();
    assert(equal(other.state.paths, [paths.otherBodyPath]) && equal(other.state.loadedPaths, [paths.otherBodyPath]) && equal(other.state.motionLibraryPaths, [paths.motionPath]) && other.state.rig.clipNames.indexOf('Native library motion') >= 0 && other.state.stats.meshes === 1,
      'Changing the model must retain the animation bank without importing its source as a model');
    await open(paths.sourcePath); var rebound = snapshot();
    assert(rebound.state.rig.expressionPanel.gaze.available && rebound.state.rig.clipNames.indexOf('Native library motion') >= 0 && equal(rebound.state.loadedMotionPaths, [paths.motionPath]),
      'Returning to the source must rebind the retained motion and genuine gaze poses');
    await click('viewer-clear-motion-library');
    await until('the explicit motion-library clear', function () { var s = ModelViewer.getState(); return !s.loading && !s.motionLibraryPaths.length && !s.loadedMotionPaths.length && s.rig.clipNames.indexOf('Native library motion') < 0; });
    var cleared = snapshot(), probe = ModelViewer.renderProbe(33);
    assert(probe.ready && probe.glError === 0 && probe.nonBackgroundSamples >= 3, 'Actual native WebGL must still draw the source after all reloads');
    return { status: 'PASS', checks: { physicsFreshOn: true, gazeOriginalPoses: true, gazePausedAndReset: true, poseComponentFilters: true,
      breastAutomaticLimits: true, breastDisableRestoresBaseline: true, precisePhysicsEditing: true, motionSourceSeparation: true,
      motionReloadPreservesEdits: true, importedMotionPlays: true, modelChangeRetainsLibrary: true, explicitClear: true },
      paths: clone(paths), initial: initial, gaze: { front: front, directed: directed, returned: returned, camera: cameraGaze },
      breast: { record: breast, baseline: base, preset: preset, automatic: automated, limits: limits },
      beforeLibrary: beforeLibrary, imported: imported, played: played, other: other, rebound: rebound, cleared: cleared, probe: probe,
      scope: 'Actual native controls/Save-independent authoring, source pose transforms and retained motion playback. Neutral eye joints are auxiliary and zero-weight; no visible pupil or whole-game parity claim.' };
  }
  window.NativeExtendedQa = { run: run };
}());

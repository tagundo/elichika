/* Native smoke-only probe. Loaded from Resources/qa, never by the user UI. */
(function () {
  'use strict';
  function assert(value, message) { if (!value) throw new Error(message); }
  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }
  async function settle() {
    await new Promise(function (resolve) { requestAnimationFrame(function () { requestAnimationFrame(resolve); }); });
  }
  async function until(message, condition) {
    var deadline = Date.now() + 30000;
    while (Date.now() < deadline) { if (condition()) return; await wait(25); }
    throw new Error('Timed out: ' + message);
  }
  function snapshot() {
    var state = ModelViewer.getState();
    return clone({ physics: state.rig.physics, time: state.rig.time, playing: state.rig.playing,
      bones: state.rig.bones, authoring: ModelViewer.getAuthoringState(), catalogue: ModelViewer.getEditingMetadata().physics,
      controls: { mode: document.getElementById('viewer-physics-mode').value,
        frameRate: document.getElementById('viewer-physics-frame-rate').value,
        frameDisabled: document.getElementById('viewer-physics-frame-rate').disabled,
        profile: document.getElementById('viewer-physics-profile').value,
        profileDisabled: document.getElementById('viewer-physics-profile').disabled,
        gameOptionEnabled: !document.querySelector('#viewer-physics-mode option[value=game]').disabled } });
  }
  function usable(id) {
    var target = typeof id === 'string' ? document.getElementById(id) : id;
    assert(target, 'The actual physics control must exist');
    for (var parent = target.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true;
    var control = ViewerRigQa.control(id, true);
    assert(!control.disabled && control.visible && control.withinViewport && control.hittable,
      'Actual physics control must be visible and usable: ' + id + ' ' + JSON.stringify(control));
    return control;
  }
  async function input(id, value, event) { usable(id); ViewerRigQa.input(id, value, event || 'change'); await settle(); }
  async function click(id) { usable(id); document.getElementById(id).click(); await settle(); }
  function ready(observed, job) {
    var physics = observed.physics, solver = physics.solver;
    assert(physics.nativeAvailable && physics.mode === 'game' && solver.initialized && solver.available,
      'The original source equations must be active: ' + JSON.stringify(physics));
    assert(solver.unsupported.length === 0 && solver.runtimeProfile.job === job,
      'The requested original job must have every source input: ' + JSON.stringify(solver));
    assert(solver.bones.length > 0, 'The original job must expose actual tip vectors');
    solver.bones.forEach(function (bone) { ['origin', 'tip'].forEach(function (name) {
      assert(bone[name].length === 3 && bone[name].every(Number.isFinite), 'Original job outputs must be finite');
    }); });
  }
  async function advance(job) {
    var before = snapshot(); ready(before, job);
    await click('viewer-play');
    await until('actual Play advancing ' + job, function () {
      var s = ModelViewer.getState();
      return s.rig.playing && s.rig.time > .15 && s.rig.physics.solver.totalNativeSteps >= before.physics.solver.totalNativeSteps + 3;
    });
    await click('viewer-play');
    var after = snapshot(); ready(after, job);
    assert(!after.playing, 'Actual Play must pause again');
    var changed = after.physics.solver.bones.some(function (bone, index) {
      return bone.tip.some(function (value, axis) { return Math.abs(value - before.physics.solver.bones[index].tip[axis]) > 1e-7; });
    });
    assert(after.physics.solver.totalNativeSteps > before.physics.solver.totalNativeSteps && changed,
      'Actual playback must advance the original job and change native tip vectors');
    return { before: before, after: after, changedNativeTip: changed };
  }
  async function run() {
    await until('the complete original physics fixture', function () {
      var s = ModelViewer.getState();
      return s.loaded && !s.loading && s.rig && s.rig.physics && s.rig.physics.nativeAvailable && document.getElementById('viewer-physics-mode');
    });
    var initial = snapshot();
    assert(initial.physics.mode === 'game' && initial.physics.frameRate === 30 && initial.physics.nativeMissing.length === 0 && initial.controls.gameOptionEnabled,
      'Complete original source data must default to game mode and 30 FPS');
    document.getElementById('viewer-adjustments').open = true;
    document.querySelectorAll('.viewer-physics-region').forEach(function (region) { region.open = true; });
    var controls = { mode: usable('viewer-physics-mode'), frame: usable('viewer-physics-frame-rate') };
    await input('viewer-physics-frame-rate', '60'); assert(snapshot().physics.frameRate === 60, 'Actual 60 FPS setting must apply');
    await input('viewer-physics-frame-rate', '30');
    var clip = 'Neutral MV scale override';
    assert(Array.prototype.some.call(document.getElementById('viewer-motion').options, function (option) { return option.value === clip; }),
      'The actual source clip must be available');
    await input('viewer-motion', clip); await input('viewer-time', '0', 'input');
    if (!document.getElementById('viewer-physics-bones').checked) await click('viewer-physics-bones');
    if (!document.getElementById('viewer-physics-colliders').checked) await click('viewer-physics-colliders');
    ready(snapshot(), 'SwingBoneJob');
    var single = await advance('SwingBoneJob');
    await input('viewer-physics-profile', 'live');
    await input('viewer-physics-skirt-correction', 'enabled');
    await input('viewer-physics-motion-correction', 'disabled');
    await input('viewer-time', '0', 'input');
    var groupReady = snapshot(); ready(groupReady, 'SwingBoneGroupJob');
    assert(groupReady.physics.runtime.safeSwingBone === false, 'The manual MV motion flag must be supplied');
    assert(groupReady.catalogue.managers.length > 0, 'Native source managers must exist');
    groupReady.catalogue.managers.forEach(function (manager) {
      var knees = manager.kneeTransforms && manager.kneeTransforms.length === 2 ? manager.kneeTransforms : manager.resolvedKneeTransforms;
      assert(knees.length === 2 && groupReady.physics.runtime.skirtsafeDisableBySource[manager.sourceIndex] === false,
        'Manual MV costume correction must provide the original knees and flag');
    });
    var group = await advance('SwingBoneGroupJob'), paused = snapshot();
    await click('viewer-physics-show-colliders'); var debugOn = snapshot();
    await wait(250); var held = snapshot();
    await click('viewer-physics-show-colliders'); var debugOff = snapshot();
    assert(debugOn.physics.showColliders && !debugOff.physics.showColliders, 'Actual debug controls must toggle');
    [debugOn, held, debugOff].forEach(function (observed) {
      assert(!observed.playing && observed.time === paused.time, 'Paused debug must not advance animation time');
      ['totalNativeSteps', 'resets', 'initializationGeneration', 'dynamicGeneration'].forEach(function (key) {
        assert(observed.physics.solver[key] === paused.physics.solver[key], 'Paused debug must preserve ' + key);
      });
      assert(equal(observed.physics.solver.bones, paused.physics.solver.bones) && equal(observed.bones, paused.bones),
        'Paused debug must preserve actual solver vectors and rig TRS');
    });
    var field = document.querySelector('[data-physics-field=dragForce]');
    assert(field && !field.disabled, 'The original source drag parameter must be writable');
    var parameterControl = usable(field); field.value = '.4'; field.dispatchEvent(new Event('input', { bubbles: true })); await settle();
    var authored = snapshot(), edits = authored.authoring.physics;
    assert(edits.length === 1 && edits[0].values.dragForce === .4, 'Actual physics parameter edits must retain precision');
    await input('viewer-time', '.75', 'input'); var seeked = snapshot(); ready(seeked, 'SwingBoneGroupJob');
    assert(!seeked.playing && Math.abs(seeked.time - .75) < 1e-7 && equal(seeked.authoring.physics, edits) && equal(seeked.catalogue, initial.catalogue),
      'Seeking must preserve the source catalogue and user physics edits');
    await input('viewer-physics-mode', 'enhanced'); var enhanced = snapshot();
    assert(enhanced.physics.mode === 'enhanced' && enhanced.controls.frameDisabled && enhanced.controls.profileDisabled && equal(enhanced.authoring.physics, edits),
      'Enhanced mode must disable game-only controls and preserve edits');
    await input('viewer-physics-mode', 'game'); var restored = snapshot(); ready(restored, 'SwingBoneGroupJob');
    assert(restored.physics.frameRate === 30 && !restored.controls.frameDisabled && equal(restored.authoring.physics, edits),
      'Returning to the original job must preserve cadence and edits');
    if (!document.getElementById('viewer-physics-show-colliders').checked) await click('viewer-physics-show-colliders');
    var final = snapshot(), framebuffer = ModelViewer.renderProbe(33);
    assert(framebuffer.ready && framebuffer.glError === 0 && framebuffer.nonBackgroundSamples >= 3,
      'Actual native WebGL must still draw the physics model');
    return { status: 'PASS', clip: clip, initial: initial, controls: controls, single: single, group: group,
      checks: { nativeDefault: true, singleJobAdvanced: true, groupJobAdvanced: true, pausedDebugPreserved: true,
        seekPreservedParameters: true, modeSwitchPreservedParameters: true, frameRateRestored30: true },
      paused: { before: paused, debugOn: debugOn, held: held, debugOff: debugOff, cacheAndPosePreserved: true },
      seek: { before: authored, after: seeked, parameterControl: parameterControl, userPhysicsAndCataloguePreserved: true },
      enhanced: enhanced, restored: restored, final: final, framebuffer: framebuffer,
      sourceCataloguePreserved: equal(final.catalogue, initial.catalogue),
      scope: 'Actual WKWebView controls, original single/group job outputs, pause/seek lifecycle and WebGL draw. No full Unity scheduler or whole-game rendering parity claim.' };
  }
  window.NativeGamePhysicsQa = { run: run };
}());

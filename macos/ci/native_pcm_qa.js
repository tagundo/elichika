/* Mac smoke-only generated PCM probe. Never loaded by the user interface. */
(function () {
  'use strict';
  var fixtureURL = '/api/viewer/game/motions/audio/00000000000000000000000000000004.wav';
  function assert(value, message) { if (!value) throw new Error(message); }
  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function equal(left, right) { return JSON.stringify(left) === JSON.stringify(right); }
  function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }
  async function settle() { await new Promise(function (resolve) { requestAnimationFrame(function () { requestAnimationFrame(resolve); }); }); }
  async function until(message, condition) {
    var deadline = performance.now() + 30000;
    while (performance.now() < deadline) { if (condition()) return; await wait(10); }
    throw new Error('Timed out: ' + message + ' ' + JSON.stringify(ViewerMotionAudio.getState()));
  }
  function input(id, value, event) {
    var target = document.getElementById(id);
    assert(target && !target.disabled, 'Actual audio control is available: ' + id);
    if (target.type === 'checkbox') target.checked = !!value; else target.value = String(value);
    target.dispatchEvent(new Event(event || 'change', { bubbles: true }));
  }
  async function playButton() {
    var target = document.getElementById('viewer-play');
    assert(target && !target.disabled, 'The actual motion Play control is available');
    target.click(); await settle();
  }
  function snapshot() {
    var motion = ModelViewer.getMotionState(), audio = ViewerMotionAudio.getState();
    return clone({ rig: motion.rig, audio: audio, manager: ViewerNativePCM.getState(),
      clock: ViewerMotionAudio.getPlaybackClock(motion.rig) });
  }
  function fixture() {
    var channels = 2, sampleRate = 44100, frames = sampleRate * 4, bytes = new ArrayBuffer(44 + frames * channels * 2);
    var view = new DataView(bytes);
    function word(offset, value) { for (var i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); }
    word(0, 'RIFF'); view.setUint32(4, bytes.byteLength - 8, true); word(8, 'WAVE'); word(12, 'fmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, channels, true);
    view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * channels * 2, true);
    view.setUint16(32, channels * 2, true); view.setUint16(34, 16, true); word(36, 'data'); view.setUint32(40, frames * channels * 2, true);
    for (var frame = 0; frame < frames; frame++) {
      view.setInt16(44 + frame * 4, Math.round(1638 * Math.sin(2 * Math.PI * 440 * frame / sampleRate)), true);
      view.setInt16(46 + frame * 4, Math.round(1229 * Math.sin(2 * Math.PI * 660 * frame / sampleRate)), true);
    }
    return { bytes: bytes, channels: channels, sampleRate: sampleRate, frames: frames, bits: 16, duration: 4 };
  }
  async function run() {
    var platform = ElichikaPlatform.info();
    assert(platform.native === true && platform.platform === 'macos', 'Use the actual validated native Mac bridge');
    assert(typeof ViewerNativePCM === 'object' && typeof ViewerNativePCM.getState === 'function', 'The packaged native PCM module is loaded');
    var state = ModelViewer.getState(), rig = state.rig;
    assert(state.loaded && !state.loading && rig && !rig.playing && rig.duration >= 2,
      'Use the already loaded actual paused two-second neutral source clip');
    assert(ViewerMotionAudio.getState().tracks.length === 0, 'Start with no original linked or local track to replace');
    var before = { clip: rig.selectedClip, time: rig.time, authoring: clone(ModelViewer.getAuthoringState()),
      catalogue: clone(ModelViewer.getEditingMetadata().physics), camera: clone(state.camera) };
    var controls = {};
    ['viewer-motion-audio-enabled', 'viewer-motion-audio-muted', 'viewer-motion-audio-volume', 'viewer-motion-audio-source'].forEach(function (id) {
      var target = document.getElementById(id); controls[id] = target.type === 'checkbox' ? target.checked : target.value;
    });
    var preferenceKey = 'elichika.viewer.motion-audio.v2', storedPreference = localStorage.getItem(preferenceKey);
    var originalFetch = window.fetch, originalClock = ViewerMotionAudio.getPlaybackClock, originalFactory = ViewerNativePCM.create;
    var generated = fixture(), fetchCalls = [], unexpectedFetches = [], rounds = [], cleared = null;
    var hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', generated.bytes))).map(function (value) { return value.toString(16).padStart(2, '0'); }).join('');
    function exactFetch(input, options) {
      if (input !== fixtureURL) {
        unexpectedFetches.push(String(input));
        return Promise.reject(new Error('The PCM fixture boundary permits exactly one URL: ' + String(input)));
      }
      assert(options && options.credentials === 'same-origin' && options.signal, 'The real transport keeps origin credentials and cancellation');
      fetchCalls.push({ url: input, credentials: options.credentials });
      return Promise.resolve(new Response(generated.bytes.slice(0), { status: 200, headers: { 'Content-Type': 'audio/wav', 'Content-Length': String(generated.bytes.byteLength) } }));
    }
    try {
      input('viewer-motion-audio-enabled', true); input('viewer-motion-audio-muted', false);
      input('viewer-motion-audio-volume', '.4', 'input'); input('viewer-time', '0', 'input');
      for (var round = 0; round < 2; round++) {
        var rate = 1, offset = round === 0 ? .25 : .5, descriptor = { version: 1, tracks: [{ url: fixtureURL,
          cue: 'Generated native PCM smoke offset ' + offset, startTime: 0, offset: offset, playDuration: 2, playbackRate: rate }], warnings: [] };
        assert(ViewerNativePCM.eligible(descriptor), 'Exactly one generated linked PCM cue uses the real Mac cohort');
        window.fetch = exactFetch;
        ViewerMotionAudio.load(descriptor, { modelId: state.modelId, clipNames: [before.clip] });
        await until('actual decode before the paused clip starts', function () {
          var audio = ViewerMotionAudio.getState(); return audio.tracks.length === 1 && audio.tracks[0].readyState >= 2;
        });
        window.fetch = originalFetch;
        var ready = snapshot(), track = ready.audio.tracks[0];
        assert(track.backend === 'web-audio-pcm' && !track.player.fallbackReason && track.player.decodedBytes > 0,
          'The actual candidate decoded PCM instead of choosing HTML fallback');
        assert(track.player.bufferChannels === generated.channels && Math.abs(track.player.bufferDuration - generated.duration) < 1 / track.player.bufferSampleRate &&
          track.player.decodedBytes === Math.round(track.player.bufferDuration * track.player.bufferSampleRate) * generated.channels * 4,
          'The actual decoded stereo buffer keeps the generated duration and explicit resampled storage size');
        assert(ready.audio.paused && !ready.rig.playing && Math.abs(track.time - offset) <= .002,
          'Paused decode preserves the authored media offset');
        await playButton();
        await until('actual source and rig advance', function () {
          var observed = snapshot(), p = observed.audio.tracks[0].player;
          return observed.rig.playing && observed.rig.time > .25 && p.contextState === 'running' && p.sourceActive && p.sourceStarts >= 1;
        });
        var playing = snapshot(), player = playing.audio.tracks[0].player;
        assert(Number.isFinite(playing.clock) && Math.abs(playing.clock - playing.rig.time) < .04,
          'The unchanged product getter maps the actual PCM clock into motion time');
        assert(Math.abs(player.sourceRate - rate) < 1e-6 && Math.abs(player.gain - .4) < 1e-6,
          'The actual source rate and gain keep the descriptor and UI values');
        assert(Number.isFinite(player.contextTime) && player.contextTime >= player.sourceEpoch,
          'Read the live native AudioContext processing epoch without a clock override');
        input('viewer-motion-audio-muted', true); await settle(); var muted = snapshot();
        assert(muted.audio.muted && muted.audio.tracks[0].player.gain === 0 && muted.audio.tracks[0].player.sourceActive,
          'Mute changes the actual gain while the source keeps playing');
        input('viewer-motion-audio-muted', false); input('viewer-motion-audio-volume', '.2', 'input'); await settle();
        var volume = snapshot();
        assert(!volume.audio.muted && Math.abs(volume.audio.tracks[0].player.gain - .2) < 1e-6,
          'Unmute and volume change the actual source gain');
        await playButton(); var paused = snapshot(); await wait(160); var held = snapshot();
        assert(!held.rig.playing && held.audio.paused && held.rig.time === paused.rig.time &&
          Math.abs(held.audio.time - paused.audio.time) < 1e-9 && !held.audio.tracks[0].player.sourceActive,
          'Pause stops the real source and preserves both clocks');
        input('viewer-time', '.75', 'input'); await settle(); var seeked = snapshot();
        assert(!seeked.rig.playing && Math.abs(seeked.rig.time - .75) < 1e-7 && Math.abs(seeked.audio.time - (offset + .75 * rate)) <= .002,
          'Actual timeline seek keeps the authored offset and playback rate');
        await playButton(); await until('source recreated after seek', function () {
          var observed = snapshot(); return observed.rig.time > .9 && observed.audio.tracks[0].player.sourceStarts > paused.audio.tracks[0].player.sourceStarts;
        });
        await playButton(); var resumed = snapshot();
        assert(!resumed.rig.playing && !resumed.audio.tracks[0].player.sourceActive,
          'The resumed source stops again through the same actual Play control');
        rounds.push({ playbackRate: rate, offset: offset, ready: ready, playing: playing, muted: muted, volume: volume,
          paused: paused, held: held, seeked: seeked, resumed: resumed });
        ViewerMotionAudio.clear();
        await until('decoded buffer and track cleanup', function () {
          var manager = ViewerNativePCM.getState();
          return ViewerMotionAudio.getState().tracks.length === 0 && manager.players === 0 &&
            manager.retainedDecodedBytes === 0 && manager.reservedDecodedBytes === 0 && manager.queued === 0 && !manager.decoding;
        });
        cleared = snapshot();
        input('viewer-time', '0', 'input'); input('viewer-motion-audio-volume', '.4', 'input');
      }
      assert(fetchCalls.length === 2 && !unexpectedFetches.length, 'Only the exact generated URL crosses the narrow fixture boundary');
      assert(originalClock === ViewerMotionAudio.getPlaybackClock && originalFactory === ViewerNativePCM.create,
        'The production clock and native player factory stay unchanged');
    } finally {
      window.fetch = originalFetch;
      if (ModelViewer.getState().rig.playing) await playButton();
      ViewerMotionAudio.clear();
      input('viewer-time', String(before.time), 'input');
      Object.keys(controls).forEach(function (id) { input(id, controls[id], id === 'viewer-motion-audio-volume' ? 'input' : 'change'); });
      if (storedPreference === null) localStorage.removeItem(preferenceKey); else localStorage.setItem(preferenceKey, storedPreference);
      await settle();
    }
    var finalState = ModelViewer.getState(), final = snapshot();
    assert(finalState.rig.selectedClip === before.clip && finalState.rig.time === before.time && !finalState.rig.playing &&
      equal(ModelViewer.getAuthoringState(), before.authoring) && equal(ModelViewer.getEditingMetadata().physics, before.catalogue) && equal(finalState.camera, before.camera),
      'The generated audio probe preserves the original clip, pose settings, source catalogue, authoring and camera');
    assert(window.fetch === originalFetch && ViewerMotionAudio.getPlaybackClock === originalClock && ViewerNativePCM.create === originalFactory &&
      localStorage.getItem(preferenceKey) === storedPreference && final.manager.players === 0 && final.manager.retainedDecodedBytes === 0 && final.manager.reservedDecodedBytes === 0,
      'Restore the exact network boundary, product APIs, saved preference and decoded-buffer ownership');
    return { status: 'PASS', platform: platform, fixture: { url: fixtureURL, sha256: hash, encodedBytes: generated.bytes.byteLength,
      sampleRate: generated.sampleRate, channels: generated.channels, bits: generated.bits, frames: generated.frames, duration: generated.duration },
      fetchCalls: fetchCalls, unexpectedFetches: unexpectedFetches, rounds: rounds, cleared: cleared, final: final,
      checks: { actualNativeBridge: true, actualContextAndSource: true, unchangedClockAndFactory: true, pausedDecode: true,
        authoredOffsets: true, actualGainMuteVolume: true, pausedClocks: true, seekOffset: true, sourceRecreated: true,
        narrowFixtureBoundary: true, buffersReleased: true, sourceAndPreferencesRestored: true },
      scope: 'Actual shipped Mac AppKit bridge, candidate linked single-PCM controller and AudioContext/source/gain lifecycle on generated stereo PCM. No speaker-output capture, audible quality or physical device FPS claim.' };
  }
  window.NativePCMQa = { run: run };
}());

/* The release-only official workload check uses the same app, bridge and UI. */
(function () {
  'use strict';
  var progress = { stage: 'not-started' };
  function assert(value, message) { if (!value) throw new Error(message); }
  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  function delay(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }
  function change(id, value, event) {
    var el = document.getElementById(id); assert(el && !el.disabled, 'The actual game input is available: ' + id);
    if (el.type === 'checkbox') el.checked = !!value; else el.value = String(value);
    el.dispatchEvent(new Event(event || 'change', { bubbles: true }));
  }
  function click(id) { var el = document.getElementById(id); assert(el && !el.disabled, 'The actual game control is available: ' + id); el.click(); }
  function pause() { if (ModelViewer.getMotionState().rig.playing) click('viewer-play'); }
  function hash(bytes) { return crypto.subtle.digest('SHA-256', bytes).then(function (digest) { return Array.from(new Uint8Array(digest)).map(function (v) { return v.toString(16).padStart(2, '0'); }).join(''); }); }
  function pcmInfo(bytes) {
    var v = new DataView(bytes), fmt = null, dataBytes = null;
    function word(i) { return String.fromCharCode(v.getUint8(i), v.getUint8(i + 1), v.getUint8(i + 2), v.getUint8(i + 3)); }
    assert(bytes.byteLength >= 44 && word(0) === 'RIFF' && word(8) === 'WAVE' && v.getUint32(4, true) + 8 === bytes.byteLength, 'The actual linked response is one complete RIFF WAV');
    for (var i = 12; i + 8 <= bytes.byteLength;) {
      var type = word(i), size = v.getUint32(i + 4, true), start = i + 8;
      assert(size <= bytes.byteLength - start, 'The actual WAV chunk stays within its response');
      if (type === 'fmt ') { assert(size >= 16 && !fmt, 'One actual WAV format chunk'); fmt = { format: v.getUint16(start, true), channels: v.getUint16(start + 2, true), sampleRate: v.getUint32(start + 4, true), blockAlign: v.getUint16(start + 12, true), bits: v.getUint16(start + 14, true) }; }
      if (type === 'data') { assert(dataBytes === null, 'One actual WAV data chunk'); dataBytes = size; }
      i = start + size + size % 2;
    }
    assert(fmt && fmt.format === 1 && fmt.channels === 2 && fmt.sampleRate === 44100 && fmt.bits === 16 && fmt.blockAlign === 4 && dataBytes > 0 && dataBytes % 4 === 0, 'CHASE keeps its original stereo 44.1kHz PCM16 input');
    fmt.frames = dataBytes / fmt.blockAlign; fmt.duration = fmt.frames / fmt.sampleRate; fmt.encodedBytes = bytes.byteLength;
    return fmt;
  }
  async function runGame() {
    var report = { status: 'RUNNING', scope: 'Actual app native bridge, official Eli400022007 and CHASE12008/1200801, unchanged product linked-PCM transport and DSP clock. No audible-output capture or physical-device FPS claim.', stages: [], network: [], requestDiagnostics: [], audioResponses: [], samples: [] };
    var checkpoint = null, before = null, oldFetch = window.fetch, oldClock = ViewerMotionAudio.getPlaybackClock, oldFactory = ViewerNativePCM.create;
    var controls = {}, preferences = {}, hashJobs = [], prepared = [], captured = false, navigation = null;
    function stage(name) { progress = { stage: name, at: performance.now() }; report.stages.push(clone(progress)); progress.requestDiagnostics = report.requestDiagnostics; }
    function statusText() { return ['viewer-game-assets-status', 'viewer-game-motion-status', 'viewer-game-motion-note'].map(function (id) { var el = document.getElementById(id); return el ? el.textContent : ''; }).filter(Boolean).join(' | ').slice(-2000); }
    async function wait(name, condition, timeout) {
      stage(name); var deadline = performance.now() + (timeout || 120000);
      while (performance.now() < deadline) { if (condition()) return; await delay(50); }
      throw new Error('Timeout: ' + name + ' ' + statusText() + ' ' + (ModelViewer.getState().error || ''));
    }
    async function region(regionId, characterId, desired) {
      var el = document.getElementById(regionId); if (el.value === desired) return;
      var updated = false, observer = new MutationObserver(function (records) { if (records.some(function (r) { return r.type === 'childList'; })) updated = true; });
      observer.observe(document.getElementById(characterId), { childList: true });
      try { change(regionId, desired); await wait('network-region-catalog-' + regionId, function () { return updated && el.value === desired && document.getElementById(characterId).options.length > 1; }); }
      finally { observer.disconnect(); }
    }
    function observeFetch(input, options) {
      var url = new URL(typeof input === 'string' ? input : input.url, location.href);
      // Observe the existing call only. Never issue a diagnostic request, read
      // credentials/body/query strings, consume its body, or replace a reply.
      var diagnostic = null;
      if (url.origin === location.origin && /^\/api\/viewer\/(game\/|prepare$)/.test(url.pathname) && report.requestDiagnostics.length < 128) {
        diagnostic = { id: report.requestDiagnostics.length + 1, origin: url.origin, path: url.pathname,
          method: String(options && options.method || input && input.method || 'GET'), startedAt: performance.now(), state: 'started' };
        report.requestDiagnostics.push(diagnostic);
      }
      return oldFetch.call(window, input, options).then(function (response) {
        if (diagnostic) { diagnostic.headersReceivedAt = performance.now(); diagnostic.status = response.status; diagnostic.state = 'headers-received'; }
        if (url.origin === location.origin && /^\/api\/viewer\/(game\/|prepare$)/.test(url.pathname)) report.network.push({ path: url.pathname, status: response.status, ok: response.ok });
        if (url.origin === location.origin && url.pathname === '/api/viewer/prepare' && response.ok) {
          var job = response.clone().json().then(function (data) {
            prepared.push({ id: data.id, stats: data.stats, descriptors: data.rig && data.rig.motionTimelines || [] });
          }).catch(function (error) { report.prepareObservationError = String(error); });
          hashJobs.push(job);
        }
        if (url.origin === location.origin && /^\/api\/viewer\/game\/motions\/audio\/[a-f0-9]{32}\.wav$/.test(url.pathname) && response.ok) {
          var audio = { path: url.pathname, status: response.status }; report.audioResponses.push(audio);
          var audioJob = response.clone().arrayBuffer().then(async function (bytes) {
            assert(bytes.byteLength <= 32 * 1024 * 1024, 'The observed original encoded WAV is bounded');
            audio.pcm = pcmInfo(bytes); audio.sha256 = await hash(bytes);
          }).catch(function (error) { audio.observationError = String(error); });
          hashJobs.push(audioJob);
        }
        return response;
      }, function (error) {
        if (diagnostic) { diagnostic.errorAt = performance.now(); diagnostic.errorName = error.name; diagnostic.state = 'rejected'; }
        if (url.origin === location.origin && /^\/api\/viewer\/game\//.test(url.pathname)) report.network.push({ path: url.pathname, error: String(error), name: error.name });
        throw error;
      });
    }
    try {
      stage('capture-owned-checkpoint');
      var platform = ElichikaPlatform.info(); report.platform = clone(platform);
      report.portalStart = { origin: location.origin, path: location.pathname, readyState: document.readyState,
        visibility: document.visibilityState, hidden: document.hidden,
        activePanel: (document.querySelector('.tab-panel.active') || {}).id || null,
        activeElement: document.activeElement ? { id: document.activeElement.id || null, tag: document.activeElement.tagName } : null };
      assert(platform.native === true && platform.platform === 'macos', 'The official PCM release gate requires the genuine native Mac bridge');
      navigation = document.querySelector('.tab-panel.active'); navigation = navigation && navigation.id;
      pause(); checkpoint = ModelViewer.captureCheckpoint();
      before = { paths: clone(checkpoint.paths), authoring: clone(checkpoint.authoring), meshState: clone(checkpoint.meshState), camera: clone(checkpoint.camera), pose: clone(checkpoint.pose), motions: clone(checkpoint.motionLibraryPaths), imported: clone(checkpoint.importedGameMotionPaths), autoFace: checkpoint.autoFace };
      ['viewer-high-quality', 'viewer-reimport', 'viewer-auto-face', 'viewer-motion-audio-enabled', 'viewer-motion-audio-muted', 'viewer-motion-audio-volume', 'viewer-motion-audio-source'].forEach(function (id) { var el = document.getElementById(id); if (el) controls[id] = el.type === 'checkbox' ? el.checked : el.value; });
      ['elichika.viewer.motion-audio.v2', 'elichika.game-assets.region.v1', 'elichika.game-motions.region.v1'].forEach(function (key) { preferences[key] = localStorage.getItem(key); });
      report.original = { paths: before.paths, selectedClip: before.pose.selectedClip, time: before.pose.time, autoFace: before.autoFace };
      window.fetch = observeFetch;
      if (typeof switchTab === 'function') switchTab('viewer');
      await wait('network-game-picker-ready', function () { return document.getElementById('tab-viewer').classList.contains('active') && window.GameAssetPicker && document.getElementById('viewer-game-assets').dataset.gameAssetsBound === 'true'; });
      document.getElementById('viewer-auto-face').checked = true;
      var oldModelId = ModelViewer.getState().modelId;
      click('viewer-game-assets');
      await wait('network-costume-catalog', function () { var el = document.getElementById('viewer-game-character'); return el && el.options.length > 1; });
      await region('viewer-game-region', 'viewer-game-character', 'gl');
      await wait('network-costume-character', function () { return Array.from(document.getElementById('viewer-game-character').options).some(function (o) { return o.value === '2'; }); });
      change('viewer-game-character', '2');
      await wait('network-costume-choice', function () { return Array.from(document.getElementById('viewer-game-costume').options).some(function (o) { return o.value === 'suit:400022007'; }); });
      change('viewer-game-costume', 'suit:400022007');
      document.getElementById('viewer-game-reimport').checked = true; document.getElementById('viewer-game-download').checked = true;
      click('viewer-game-import');
      await wait('network-official-Eli-import', function () { var s = ModelViewer.getState(); return !document.getElementById('viewer-game-assets-dialog').open && s.loaded && !s.loading && s.modelId !== oldModelId; }, 240000);
      report.initialCostume = { paths: clone(ModelViewer.getState().loadedPaths), physics: clone(ModelViewer.getState().rig.physics) };
      document.getElementById('viewer-adjustments').open = true;
      click('viewer-game-motions');
      await wait('network-motion-catalog', function () { var el = document.getElementById('viewer-motion-character'); return el && el.options.length > 1; });
      await region('viewer-motion-region', 'viewer-motion-character', 'gl');
      await wait('network-motion-character', function () { return Array.from(document.getElementById('viewer-motion-character').options).some(function (o) { return o.value === '2'; }); });
      change('viewer-motion-character', '2'); change('viewer-motion-category', 'mv'); change('viewer-motion-search', 'CHASE', 'input');
      await wait('network-CHASE-choice', function () { return Array.from(document.getElementById('viewer-game-motion-choice').options).some(function (o) { return o.value === 'mv:12008:1200801'; }); });
      change('viewer-game-motion-choice', 'mv:12008:1200801');
      await wait('network-performer-choice', function () { return Array.from(document.getElementById('viewer-motion-performer').options).some(function (o) { return o.value === '1'; }); });
      change('viewer-motion-performer', '1'); document.getElementById('viewer-motion-linked-audio').checked = true; document.getElementById('viewer-motion-download').checked = true;
      click('viewer-motion-import');
      var clip = 'game-timeline:mv:mv:12008:1200801:1';
      await wait('network-official-CHASE-import', function () { var s = ModelViewer.getState(); return !document.getElementById('viewer-game-motions-dialog').open && s.loaded && !s.loading && s.rig.selectedClip === clip; }, 240000);
      pause(); change('viewer-motion-audio-enabled', true); change('viewer-motion-audio-muted', false); change('viewer-motion-audio-volume', '1', 'input');
      if (!document.getElementById('viewer-high-quality').checked) change('viewer-high-quality', true);
      await wait('engine-real-PCM-decoded-HQ4', function () { var s = ModelViewer.getState(), a = ViewerMotionAudio.getState(); return s.quality.enabled && s.quality.actualSamples === 4 && a.tracks.length === 1 && a.tracks[0].readyState >= 2; }, 60000);
      await Promise.all(hashJobs); window.fetch = oldFetch;
      var loaded = ModelViewer.getState(), audio = ViewerMotionAudio.getState(), track = audio.tracks[0];
      assert(equal(loaded.stats, { meshes: 8, vertices: 11410, triangles: 14169, materials: 2, textures: 39 }) ||
        loaded.stats.meshes === 8 && loaded.stats.vertices === 11410 && loaded.stats.triangles === 14169 && loaded.stats.materials === 2 && loaded.stats.textures === 39, 'The official Eli workload keeps every original mesh, vertex, triangle, material and texture');
      assert(loaded.rig.selectedClip === clip && loaded.rig.duration > 103 && loaded.rig.duration < 104 && loaded.autoFace && loaded.faces && ['added', 'already_present'].indexOf(loaded.faces.status) >= 0, 'Use the exact full CHASE timeline and automatic original face');
      assert(track.cue === 'music_2008' && track.backend === 'web-audio-pcm' && track.player && !track.player.fallbackReason && track.duration > 103 && track.duration < 104 && track.player.bufferChannels === 2 && track.player.decodedBytes > 0 && track.player.decodedBytes <= 64 * 1024 * 1024, 'One original music cue uses the bounded actual PCM backend');
      assert(loaded.rig.physics.mode === 'game' && loaded.rig.physics.frameRate === 0 && loaded.rig.physics.swingBone && loaded.rig.physics.swingCollider && loaded.rig.physics.nativeAvailable, 'The original default game physics and both switches stay enabled');
      var responses = report.audioResponses.filter(function (item) { return item.sha256; }), urls = Array.from(new Set(responses.map(function (item) { return item.path; })));
      assert(responses.length >= 1 && urls.length === 1 && responses.every(function (item) { return item.sha256 === responses[0].sha256; }), 'The real single linked response has one same-job encoded PCM identity');
      report.originalPCM = clone(responses[responses.length - 1]);
      var descriptors = [];
      prepared.forEach(function (item) { (item.descriptors || []).forEach(function (value) { if (value.category === 'mv' && value.motion === 'mv:12008:1200801' && value.performerPosition === 1) descriptors.push(value); }); });
      if (descriptors.length) {
        var descriptor = descriptors[descriptors.length - 1], input = descriptor.audio && descriptor.audio.tracks;
        assert(input && input.length === 1 && input[0].url === urls[0] && input[0].cue === track.cue && input[0].startTime === 0 && input[0].offset === 0 && input[0].playbackRate === 1, 'The observed unchanged backend descriptor matches the real product single cue');
        report.descriptor = { version: descriptor.version, category: descriptor.category, motion: descriptor.motion, performerPosition: descriptor.performerPosition, audio: clone(descriptor.audio) };
      }
      report.loaded = { paths: clone(loaded.loadedPaths), clip: loaded.rig.selectedClip, duration: loaded.rig.duration, stats: clone(loaded.stats), quality: clone(loaded.quality), physics: clone(loaded.rig.physics), audio: clone(audio) };
      change('viewer-time', '50', 'input');
      await wait('engine-paused-seek-50', function () { return !ModelViewer.getMotionState().rig.playing && Math.abs(ModelViewer.getMotionState().rig.time - 50) < 1e-7 && Math.abs(ViewerMotionAudio.getState().time - 50) < .002; }, 10000);
      assert(ViewerMotionAudio.getPlaybackClock === oldClock && ViewerNativePCM.create === oldFactory && window.fetch === oldFetch, 'All original transport APIs and fetch are restored before capture');
      document.getElementById('viewer-stage').scrollIntoView({ block: 'center' });
      stage('engine-actual-12-second-playback'); click('viewer-play');
      await wait('engine-real-source-running', function () { var a = ViewerMotionAudio.getState(); return ModelViewer.getMotionState().rig.playing && a.tracks[0].player.contextState === 'running' && a.tracks[0].player.sourceActive; }, 10000);
      var beginState = ModelViewer.getState(), beginAudio = ViewerMotionAudio.getState(), begin = performance.now();
      report.before = { physics: clone(beginState.rig.physics), rig: clone(ModelViewer.getMotionState().rig), audio: clone(beginAudio), manager: clone(ViewerNativePCM.getState()) };
      await new Promise(function (resolve, reject) {
        var handle = 0, timeout = setTimeout(function () { cancelAnimationFrame(handle); reject(new Error('The active native view did not provide a complete 12 second frame sample')); }, 30000);
        function frame(at) {
          try {
            var m = ModelViewer.getMotionState(), a = ViewerMotionAudio.getState(), t = a.tracks[0], p = t && t.player;
            report.samples.push({ at: at, elapsed: performance.now() - begin, rigTime: m.rig.time, playing: m.rig.playing,
              clock: ViewerMotionAudio.getPlaybackClock(m.rig), mediaTime: t && t.time, contextTime: p && p.contextTime,
              contextState: p && p.contextState, sourceActive: p && p.sourceActive, sourceStarts: p && p.sourceStarts,
              sourceGeneration: p && p.sourceGeneration, sourceRate: p && p.sourceRate, seeks: t && t.seeks,
              revision: m.rig.playbackRevision, hidden: document.hidden });
            if (performance.now() - begin >= 12000) { clearTimeout(timeout); resolve(); } else handle = requestAnimationFrame(frame);
          } catch (error) { clearTimeout(timeout); reject(error); }
        }
        handle = requestAnimationFrame(frame);
      });
      pause(); captured = true;
      report.after = { rig: clone(ModelViewer.getMotionState().rig), audio: clone(ViewerMotionAudio.getState()), physics: clone(ModelViewer.getState().rig.physics), manager: clone(ViewerNativePCM.getState()) };
      var steady = report.samples.filter(function (sample) { return sample.elapsed >= 1000; });
      assert(steady.length >= 100 && steady[steady.length - 1].elapsed - steady[0].elapsed >= 10000, 'At least ten seconds of steady actual frame samples are present');
      var intervals = steady.slice(1).map(function (sample, i) { return sample.at - steady[i].at; });
      var qualified = intervals.filter(function (ms) { return ms > 0 && ms <= 50; });
      var maxGap = Math.max.apply(null, intervals), goodFraction = qualified.length / intervals.length;
      assert(maxGap <= 300 && goodFraction >= .6, 'Frame sampling must distinguish a clock hold from unobserved scheduling gaps');
      var holds = [], first = 0;
      for (var i = 1; i <= steady.length; i++) {
        if (i < steady.length && steady[i].at - steady[i - 1].at <= 50 && steady[i].rigTime === steady[i - 1].rigTime) continue;
        if (i - first > 1) holds.push({ startAt: steady[first].at, endAt: steady[i - 1].at, heldMs: steady[i - 1].at - steady[first].at, time: steady[first].rigTime, frames: i - first });
        first = i;
      }
      var starts = steady[0].sourceStarts, seeks = steady[0].seeks, generation = steady[0].sourceGeneration, revision = steady[0].revision;
      assert(steady.every(function (s) { return s.playing && !s.hidden && s.contextState === 'running' && s.sourceActive && Number.isFinite(s.clock) && Number.isFinite(s.contextTime) && s.sourceRate === 1 && s.sourceStarts === starts && s.sourceGeneration === generation && s.seeks === seeks && s.revision === revision; }), 'The actual DSP source stays running with no frame seeks, restarts or transport changes');
      assert(!holds.some(function (hold) { return hold.heldMs > 50; }), 'No qualified steady rig clock hold exceeds 50ms');
      assert(steady[steady.length - 1].clock - steady[0].clock > 10 && Math.max.apply(null, steady.map(function (s) { return Math.abs(s.rigTime - s.clock); })) <= .12, 'The real DSP and rig progress together through the capture');
      assert(report.after.physics.solver.totalNativeSteps > report.before.physics.solver.totalNativeSteps + 30 && report.after.physics.swingBone && report.after.physics.swingCollider, 'The actual original native physics job advances throughout music playback');
      report.timing = { steadyFrames: steady.length, steadyDurationMs: steady[steady.length - 1].elapsed - steady[0].elapsed, sampleMaxGapMs: maxGap, sampleIntervalsAtMost50msFraction: goodFraction, qualifiedHolds: holds, maxQualifiedRigHoldMs: Math.max.apply(null, [0].concat(holds.map(function (h) { return h.heldMs; }))), maxAbsRigMinusClockSeconds: Math.max.apply(null, steady.map(function (s) { return Math.abs(s.rigTime - s.clock); })), sourceStarts: starts, seeks: seeks, sourceGeneration: generation, playbackRevision: revision };
      report.status = 'PASS';
    } catch (error) {
      report.status = 'FAIL'; report.failure = { stage: progress.stage, category: /^network-/.test(progress.stage) ? 'official-input-network-or-import' : 'engine-or-observation', message: String(error), statusText: statusText() };
    } finally {
      window.fetch = oldFetch;
      try {
        if (ModelViewer.getMotionState().rig) pause();
        ['viewer-game-assets-dialog', 'viewer-game-motions-dialog'].forEach(function (id) { var dialog = document.getElementById(id); if (dialog && dialog.open) dialog.dispatchEvent(new Event('cancel', { bubbles: false, cancelable: true })); });
        ViewerMotionAudio.clear();
        await wait('restore-release-owned-buffers', function () { var s = ViewerNativePCM.getState(); return !s.players && !s.retainedDecodedBytes && !s.reservedDecodedBytes && !s.queued && !s.decoding; }, 10000);
        report.cleared = clone(ViewerNativePCM.getState());
        if (checkpoint) {
          assert(await ModelViewer.restoreCheckpoint(checkpoint, ModelViewer.captureCheckpoint()), 'The original public source-bound checkpoint restores');
          Object.keys(controls).forEach(function (id) { change(id, controls[id], id === 'viewer-motion-audio-volume' ? 'input' : 'change'); });
          Object.keys(preferences).forEach(function (key) { if (preferences[key] === null) localStorage.removeItem(key); else localStorage.setItem(key, preferences[key]); });
          var restored = ModelViewer.captureCheckpoint();
          assert(equal(restored.paths, before.paths) && equal(restored.authoring, before.authoring) && equal(restored.meshState, before.meshState) && equal(restored.camera, before.camera) && equal(restored.motionLibraryPaths, before.motions) && equal(restored.importedGameMotionPaths, before.imported) && restored.autoFace === before.autoFace && restored.pose.selectedClip === before.pose.selectedClip && Math.abs(restored.pose.time - before.pose.time) < 1e-7 && !restored.pose.playing, 'The release-only official workload restores all original source, authoring, mesh, camera and paused motion inputs');
          report.restored = { checkpoint: true, authoring: true, meshState: true, camera: true, motionInputs: true, preferences: Object.keys(preferences).every(function (key) { return localStorage.getItem(key) === preferences[key]; }), paths: clone(restored.paths), selectedClip: restored.pose.selectedClip, time: restored.pose.time };
        }
        assert(window.fetch === oldFetch && ViewerMotionAudio.getPlaybackClock === oldClock && ViewerNativePCM.create === oldFactory, 'The official test never replaces the product player or clock');
        report.originalAPIsPreserved = true;
        if (navigation && /^tab-(viewer|tools)$/.test(navigation) && typeof switchTab === 'function') switchTab(navigation.slice(4));
      } catch (error) { report.status = 'FAIL'; report.restoreFailure = String(error); }
      report.captured = captured;
      progress = { stage: 'complete', status: report.status, failure: report.failure || null, restoreFailure: report.restoreFailure || null };
    }
    return report;
  }
  window.NativePCMQa.runGame = runGame;
  window.NativePCMQa.getGameProgress = function () { return clone(progress); };
}());

/* QA-only startup observations. No product shaders, sample counts or timing are replaced. */
(function () {
  'use strict';
  window.ElichikaDesktop = { platform: 'macos', version: 1, language: 'en', editorSurface: 'viewer',
    capabilities: [], viewerPanelWidth: 0, viewerFilesWidth: 0, panelSettings: {} };
  try { localStorage.setItem('sifas_lang', 'en'); } catch (_) {}
  var state = window.__nativeWKDiagnostic = { errors: [], rejections: [], frames: [], updates: [],
    phase: 'bootstrap', recording: false, lastDrawTimestamp: null, audioElements: [], lastAudioClock: null };
  window.addEventListener('error', function (event) { state.errors.push(String(event.message)); });
  window.addEventListener('unhandledrejection', function (event) { state.rejections.push(String(event.reason)); });
  var original = window.requestAnimationFrame;
  window.requestAnimationFrame = function (callback) {
    if (callback.name !== 'draw') return original.call(window, callback);
    return original.call(window, function (timestamp) {
      var begin = performance.now(), interval = state.lastDrawTimestamp === null ? null : timestamp - state.lastDrawTimestamp;
      state.lastDrawTimestamp = timestamp;
      try { return callback(timestamp); }
      finally {
        if (state.recording && state.frames.length < 30000) {
          var rig = state.rig && state.rig.getPlaybackState ? state.rig.getPlaybackState() : null;
          state.frames.push({ phase: state.phase, at: begin, timestamp: timestamp, interval: interval,
            workMs: performance.now() - begin, rigTime: rig && rig.time, rigPlaying: rig && rig.playing,
            lastAudioClock: state.lastAudioClock,
            rawOriginalAudioClock: state.rawOriginalAudioClock,
            clockReadAt: state.clockReadAt,
            clockKind: state.useReferenceClock ? 'webaudio-dsp-reference' : 'original-html-media',
            reference: state.pcmReference ? state.pcmReference.snapshot() : null,
            physicsTiming: state.physics && state.physics.getTimingState ? state.physics.getTimingState() : null,
            media: state.audioElements.map(function (audio) { return { time: audio.currentTime, paused: audio.paused,
              seeking: audio.seeking, ready: audio.readyState, ended: audio.ended,
              playbackRate: audio.playbackRate, networkState: audio.networkState }; }) });
        }
      }
    });
  };
}());

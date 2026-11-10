/* QA only: shared multi-picker, real SDK updater rendering and tool execution. */
(function (global) {
  'use strict';
  var TOOL = 'costume_thumbnail_replace';
  function assert(value, message) { if (!value) throw new Error(message); }
  function copy(value) { return JSON.parse(JSON.stringify(value)); }
  function equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  function sleep(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }
  async function settle() { await new Promise(function (resolve) { requestAnimationFrame(function () { requestAnimationFrame(resolve); }); }); }
  async function until(message, predicate) {
    var end = Date.now() + 180000;
    while (Date.now() < end) { if (predicate()) return; await sleep(35); }
    throw new Error('Timed out: ' + message + ': ' + document.getElementById('log').textContent);
  }
  async function usable(element) {
    if (typeof element === 'string') element = document.querySelector(element);
    assert(element, 'The actual updater control must exist');
    for (var p = element.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true;
    element.scrollIntoView({ block: 'center' }); await settle();
    var observed = ViewerRigQa.control(element, true);
    assert(!observed.disabled && observed.visible && observed.withinViewport && observed.hittable,
      'Actual updater control must be usable: ' + JSON.stringify(observed));
    return element;
  }
  async function click(element) { (await usable(element)).click(); await settle(); }
  async function input(name, value) {
    var field = await usable('#tool-form [data-name=' + JSON.stringify(name) + ']');
    field.value = String(value); field.dispatchEvent(new Event('change', { bubbles: true })); await settle();
  }
  function viewer() {
    var s = ModelViewer.getState();
    return { modelId: s.modelId, paths: copy(s.paths), loadedPaths: copy(s.loadedPaths), motionLibraryPaths: copy(s.motionLibraryPaths),
      authoring: copy(ModelViewer.getAuthoringState()), camera: copy(s.camera),
      pose: { selectedClip: s.rig.selectedClip, time: s.rig.time, playing: s.rig.playing } };
  }
  function selectedPaths() { var value = document.querySelector('#tool-form input[data-name="in_paths"]').value; return value ? value.split('\n').filter(Boolean) : []; }
  async function choose(paths) {
    var platform = global.ElichikaPlatform, requests = [], before = selectedPaths();
    assert(!before.length, 'The new updater selection must start empty');
    if (platform && platform.supports('openFiles')) {
      var adapter = function (action, options) {
        if (action !== 'openFiles') return platform.request.apply(platform, arguments);
        requests.push({ action: action, options: copy(options) });
        assert(requests.length === 1 && options.multiple === true, 'The actual native Add files action must request multiple files exactly once');
        return Promise.resolve({ paths: paths.slice() });
      };
      global.ElichikaPlatform = Object.assign({}, platform, { request: adapter });
      try { await click('#tool-form button[data-paths-add="in_paths"]'); await until('the authorized native multi-file result', function () { return equal(selectedPaths(), paths); }); }
      finally { global.ElichikaPlatform = platform; }
      assert(requests.length === 1, 'The actual native common picker must request one multi-file response');
      return { kind: 'native-authorized-result-adapter', requests: requests, before: before, after: selectedPaths(),
        scope: 'Actual common picker request with multiple:true and one authorized file result; the OS file dialog is not exercised.' };
    }
    await click('#tool-form button[data-paths-add="in_paths"]');
    await until('the actual common multi-file picker', function () { return !document.getElementById('picker').classList.contains('hidden'); });
    var observations = [];
    for (var index = 0; index < paths.length; index++) {
      await navigate(paths[index].replace(/\/[^/]*$/, '')); await settle();
      var checkbox = Array.prototype.find.call(document.querySelectorAll('#picker-entries input[type=checkbox][data-path]'), function (row) { return row.dataset.path === paths[index]; });
      await click(checkbox);
      assert(checkbox.checked && !selectedPaths().length, 'File checkboxes must retain selection across folders without committing early');
      observations.push({ path: paths[index], checked: checkbox.checked, count: document.getElementById('picker-selection-count').textContent, committed: selectedPaths() });
    }
    await click('#picker-add-selected');
    await until('one committed common-picker selection', function () { return equal(selectedPaths(), paths) && document.getElementById('picker').classList.contains('hidden'); });
    return { kind: 'browser-checkbox-picker', before: before, observations: observations, commits: 1, after: selectedPaths(),
      scope: 'Actual common checkbox picker, retained selection across two source folders and one Add selected action.' };
  }
  async function run(options) {
    assert(options && Array.isArray(options.paths) && options.paths.length === 2 && options.paths[0] !== options.paths[1] && options.outDirectory,
      'Two explicit original installer ZIPs and one authorized output folder are required');
    var paths = options.paths.slice(), before = viewer(), platform = global.ElichikaPlatform;
    assert(!before.pose.playing, 'Updater QA must preserve a paused model');
    var realPrepare = ViewerThumbnails.prepareUpdater, realFetch = global.fetch, RealEvents = global.EventSource;
    assert(typeof realPrepare === 'function', 'The actual automatic updater renderer must be available');
    var renders = [], requests = [], messages = [], requestJob = '', done = null;
    ViewerThumbnails.prepareUpdater = async function (params, callbacks) {
      var originalPreview = callbacks && callbacks.onPreview;
      var observedCallbacks = Object.assign({}, callbacks, { onPreview: function (png, receipt) {
        if (originalPreview) originalPreview(png, receipt);
        var image = document.getElementById('costume-thumbnail-replace-preview'), state = ViewerThumbnails.getState();
        assert(image && !image.hidden && image.src === png && image.dataset.sha256 === receipt.sha256,
          'The actual updater preview must display each real source-bound render');
        renders.push({ png: png, receipt: copy(receipt), render: copy(state.last.render), preview: { src: image.src, sha256: image.dataset.sha256 } });
      } });
      return realPrepare.call(this, params, observedCallbacks);
    };
    global.fetch = async function (url, init) {
      var response = await realFetch.apply(this, arguments);
      if (String(url) === '/api/run/' + TOOL) {
        requests.push(JSON.parse(init.body)); var result = await response.clone().json(); requestJob = result.job_id || '';
        assert(response.ok && !result.error && requestJob, 'The actual updater tool must create a real job');
      }
      return response;
    };
    global.EventSource = function (url, config) {
      var source = new RealEvents(url, config);
      if (/^\/api\/jobs\//.test(String(url))) source.addEventListener('message', function (event) {
        var message = JSON.parse(event.data); messages.push(copy(message)); if (message.type === 'done') done = copy(message);
      });
      return source;
    };
    global.EventSource.prototype = RealEvents.prototype;
    try {
      switchTab('tools'); await settle();
      await click('#tool-list button[data-id="' + TOOL + '"]');
      await click('#tool-form-panel .mode-toggle button[data-mode="multi"]');
      assert(document.querySelector('#tool-form-panel .mode-toggle button[data-mode="multi"]').classList.contains('active'), 'The actual Selected files tool mode must apply');
      var selection = await choose(paths);
      assert(equal(selection.after, paths) && equal(selectedPaths(), paths), 'Both selected ZIPs must be added once in source order');
      await input('out_dir', options.outDirectory); await input('thumbnail_size', '256'); await input('variant', 'auto');
      await click('#tool-form button.run-btn');
      await until('the actual two-source automatic thumbnail update job', function () {
        if (done !== null) return true;
        assert(!document.getElementById('cancel-btn').disabled, 'Actual updater preprocessing failed: ' + document.getElementById('log').textContent);
        return false;
      });
      assert(done.status === 'done' && requests.length === 1 && requests[0].mode === 'multi' && requests[0].in_paths === paths.join('\n') && requests[0].thumbnail_plan,
        'The real updater must run one multi-file job with its server-owned render plan');
      function receiptLine(row) { return row.type === 'log' ? row.line.replace(/^\[\+\s*\d+(?:\.\d+)?s\]\s*/, '') : ''; }
      var receipts = messages.filter(function (row) { return receiptLine(row).indexOf('THUMBNAIL_UPDATE ') === 0; }).map(function (row) { return JSON.parse(receiptLine(row).slice('THUMBNAIL_UPDATE '.length)); });
      var state = copy(ViewerThumbnails.getState()), profileResponse = await realFetch('/static/thumbnail-sdk/profile.json');
      assert(profileResponse.ok, 'The actual SDK profile must be readable'); var profile = await profileResponse.json();
      assert(receipts.length === 2 && renders.length === 2 && state.receipts.length === 2 && !state.busy && state.last.count === 2 && state.last.total === 2,
        'Both actual ZIPs must finish separate source-bound renders and completed outputs: ' + JSON.stringify({ receipts: receipts.length, renders: renders.length, rendererReceipts: state.receipts.length, done: done, logs: messages.filter(function (row) { return row.type === 'log'; }) }));
      var owners = options.expectedOwners || [6, 201];
      receipts.forEach(function (receipt, index) {
        var thumbnail = renders[index].receipt, render = renders[index].render;
        assert(receipt.source_path === paths[index] && receipt.output_path !== paths[index] && receipt.character_id === owners[index] && thumbnail.characterId === owners[index],
          'Each actual updater result must retain its original manifest recipient and source');
        assert(done.output_paths.indexOf(receipt.output_path) >= 0, 'Each independently inspectable ZIP must be an authoritative completed-job output');
        assert(receipt.thumbnail_sha256 === thumbnail.sha256 && receipt.profile_digest === thumbnail.profileDigest && receipt.cache_key === thumbnail.cacheKey && /^[a-f0-9]{64}$/.test(receipt.sha256),
          'The completed ZIP must bind its actual preview PNG, SDK profile and source cache');
        assert(render.quality.enabled && render.quality.ready && render.material.enabled && render.subjectPixels > 0 && render.triangles > 0 && render.visibleMeshes > 0 && render.pose === 'source-rest' && render.animation === false && equal(render.camera, profile.camera),
          'Each actual updater render must use visible source-rest costume geometry and the SDK camera');
        assert(equal(thumbnail.quality, { renderer: 'SifasMaterial', highQuality: true, animation: false, supersample: 2 }), 'The original-source high-quality thumbnail contract must remain exact');
      });
      assert(renders[0].receipt.cacheKey !== renders[1].receipt.cacheKey && renders[0].receipt.sha256 !== renders[1].receipt.sha256,
        'Different source ZIPs and manifest member colors must produce separate bindings and different actual thumbnails');
      var after = viewer(); assert(equal(before, after), 'The updater tool must preserve the currently displayed model, authoring, camera and paused pose');
      return { status: 'PASS', checks: { selectedFilesMode: true, multipleFilesOnce: true, sourcePathsPreserved: true,
        actualToolRun: true, twoAutomaticRenders: true, manifestRecipients: true, qualityCameraTemplate: true,
        previewReceipts: true, twoCompletedOutputs: true, viewerPreserved: true }, paths: paths,
        outDirectory: options.outDirectory, expectedOwners: owners, selection: selection, before: before, after: after,
        request: requests[0], jobId: requestJob, done: done, receipts: receipts, renders: renders, rendererState: state, profile: profile,
        logs: messages.filter(function (row) { return row.type === 'log'; }).map(function (row) { return row.line; }),
        scope: 'Actual shared tool form/multi-picker contract, SDK WebGL renders and updater job; the OS file dialog is not exercised.' };
    } finally {
      ViewerThumbnails.prepareUpdater = realPrepare; global.fetch = realFetch; global.EventSource = RealEvents;
      if (options.restoreViewer === true) { switchTab('viewer'); await settle(); }
    }
  }
  global.NativeThumbnailUpdaterQa = { run: run };
}(window));

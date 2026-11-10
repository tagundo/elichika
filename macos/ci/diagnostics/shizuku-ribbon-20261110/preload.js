/* QA-only bridge observations. Actual native WK renderer and DPR stay unchanged. */
(function () {
  'use strict';
  window.ElichikaDesktop = { platform: 'macos', version: 1, language: 'en', editorSurface: 'viewer',
    capabilities: [], viewerPanelWidth: 0, viewerFilesWidth: 0, panelSettings: {} };
  try { localStorage.setItem('sifas_lang', 'en'); } catch (_) {}
  var qa = window.__nativeWKDiagnostic = { errors: [], rejections: [], checkpoint: 'bootstrap' };
  window.addEventListener('error', function (event) { qa.errors.push(String(event.message)); });
  window.addEventListener('unhandledrejection', function (event) { qa.rejections.push(String(event.reason)); });
}());

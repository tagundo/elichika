/* UIKit document integration layered onto the unchanged shared editor. */
(function (global) {
  "use strict";
  var previous = global.ElichikaPlatform, ios = global.ElichikaIOS, bindings = null;
  if (!previous || !ios || typeof ios.request !== "function" ||
      global.top !== global.self || global.location.protocol !== "http:" ||
      global.location.hostname !== "127.0.0.1") return;
  var supported = ["openFiles", "chooseDirectory", "reveal"];
  function importedPaths(result) {
    if (result && result.cancelled) return { paths: [], cancelled: true };
    var paths = typeof result === "string" ? [result] : Array.isArray(result) ? result : result && result.paths;
    if (!Array.isArray(paths)) throw new Error("The imported document response is invalid.");
    return { paths: previous.chosenPaths({ paths: paths }) };
  }
  function request(action, args) {
    args = args || {};
    if (action === "openFiles") return ios.request("import", {
      types: ["public.item"], multiple: args.multiple === true
    }).then(importedPaths);
    if (action === "chooseDirectory") return ios.request("import", {
      types: ["public.folder"], multiple: false
    }).then(importedPaths).then(function (result) {
      return { path: result.paths[0] || "", paths: result.paths, cancelled: result.cancelled === true };
    });
    if (action === "reveal") {
      if (typeof args.path !== "string" || args.path[0] !== "/" || args.path.indexOf("\0") >= 0)
        return Promise.reject(new Error("Choose a completed file to export."));
      return ios.request("export", { path: args.path });
    }
    return previous.request(action, args);
  }
  var adapter = Object.assign({}, previous, {
    supports: function (name) { return supported.indexOf(name) >= 0 || previous.supports(name); },
    request: request,
    info: function () { return Object.assign({}, previous.info(), { platform: "ios", native: true }); },
    bind: function (handlers) { bindings = handlers; previous.bind(handlers); },
    perform: function (action, args) {
      if (bindings && ["openModel", "saveModel", "showViewer", "showTools"].indexOf(action) >= 0 &&
          typeof bindings[action] === "function") {
        Promise.resolve(bindings[action](args || {})).catch(function (error) { global.alert(String(error.message || error)); });
        return true;
      }
      return previous.perform(action, args);
    }
  });
  global.ElichikaPlatform = Object.freeze(adapter);
  global.document.documentElement.classList.add("elichika-ios");
})(window);

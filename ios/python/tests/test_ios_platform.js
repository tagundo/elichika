"use strict";
const assert = require("assert"), fs = require("fs"), vm = require("vm"), path = require("path");
const requests = [], diagnostics = () => "existing shared diagnostics";
const window = {
  location: { protocol: "http:", hostname: "127.0.0.1" },
  document: { documentElement: { classList: { add: () => {} } } },
  ElichikaPlatform: {
    supports: () => false, request: () => Promise.reject(new Error("unsupported")),
    info: () => ({ platform: "browser", native: false }), bind: () => {}, perform: () => false,
    chosenPaths: result => result.paths, requestJSON: diagnostics
  },
  ElichikaIOS: { request: async (action, args) => {
    requests.push({ action, args });
    if (action === "export") return true;
    return args.multiple ? ["/private/one.unity", "/private/two.unity"] :
      args.types[0] === "public.folder" ? "/private/imported-folder" : "/private/one.unity";
  } }
};
window.top = window.self = window;
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../elichika_ios/web/ios-platform.js"), "utf8"), { window });
(async () => {
  assert.strictEqual(window.ElichikaPlatform.requestJSON, diagnostics);
  assert.strictEqual(window.ElichikaPlatform.info().platform, "ios");
  assert.strictEqual((await window.ElichikaPlatform.request("openFiles", { multiple: true })).paths.length, 2);
  const directory = await window.ElichikaPlatform.request("chooseDirectory");
  assert.strictEqual(directory.path, "/private/imported-folder");
  assert.strictEqual(requests[1].args.types[0], "public.folder");
  assert.strictEqual(await window.ElichikaPlatform.request("reveal", { path: "/private/complete.zip" }), true);
  assert.strictEqual(requests[2].action, "export");
  console.log("PASS: iOS multi-file import, copied directory selection, export, shared diagnostics retained");
})().catch(error => { console.error(error); process.exitCode = 1; });

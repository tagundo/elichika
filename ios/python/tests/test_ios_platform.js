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
const guide = fs.readFileSync(path.join(__dirname, "../elichika_ios/web/ios-guidance.js"), "utf8");
for (const experimental of [false, true]) {
  let rendered;
  const document = {
    documentElement: { lang: "ko" },
    createElement: tag => ({ tag, style: {}, children: [], setAttribute: () => {}, appendChild(child) { this.children.push(child); } }),
    body: { insertBefore: node => { rendered = node; } }
  };
  const context = { window: { ElichikaIOS: {}, ElichikaIOSCapabilities: { experimental_device: experimental } },
    document, location: { hostname: "127.0.0.1" }, MutationObserver: class { observe() {} } };
  context.window.top = context.window.self = context.window;
  vm.runInNewContext(guide, context);
  const text = rendered.children.map(child => child.textContent).join(" ");
  assert.strictEqual(text.includes("Archive 준비 중"), experimental);
  assert.strictEqual(text.includes("Elichika/packs"), experimental);
  assert.strictEqual(rendered.children.some(child => child.tag === "button"), false);
}
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

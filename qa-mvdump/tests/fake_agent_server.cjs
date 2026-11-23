'use strict';
// JSON-lines bridge so Python tests can drive the real extension inside the fake world:
//   stdin  {"id": n, "method": "mvruntime"|"mvruntimeprobe"|"status"|"enablecached"|"dispose"|"__world"|"__stats", "args": [...]}
//   stdout {"id": n, "ok": true, "value": ...} | {"id": n, "ok": false, "error": "..."}
// __world sets fake-world fields (directorTime, playState, scene, poisonNext, throwNext, costPerCall);
// __stats returns the fatal / stale / thenable counters and any non-allowlisted invocation.
const readline = require('readline');
const { boot } = require('./fake_il2cpp.cjs');
const options = JSON.parse(process.argv[2] || '{}');
const h = boot(options);
const ALLOWED_NS = /^UnityEngine(\.|$)/;
async function handle(message) {
  const { method, args = [] } = message;
  if (method === '__world') {
    for (const [k, v] of Object.entries(args[0] || {})) h.world[k] = v;
    return { directorTime: h.world.directorTime, scene: h.world.scene, dispatcherState: h.world.dispatcherState };
  }
  if (method === '__stats') {
    return { fatal: h.world.fatal, stale: h.world.stale.length, thenables: h.world.thenables, invocations: h.world.invocations.length,
      foreign: [...new Set(h.world.invocations.filter(i => !ALLOWED_NS.test(i.cls)).map(i => i.cls + '::' + i.name))],
      methods: [...new Set(h.world.invocations.map(i => i.cls + '::' + i.name))], dispatches: h.world.dispatches, performs: h.world.performs };
  }
  if (method === '__proof') return h.proof;
  return h.rpc(method, ...args);
}
const rl = readline.createInterface({ input: process.stdin });
rl.on('line', (line) => {
  let message;
  try { message = JSON.parse(line); } catch (error) { return; }
  Promise.resolve().then(() => handle(message)).then(
    (value) => process.stdout.write(JSON.stringify({ id: message.id, ok: true, value: value === undefined ? null : value }) + '\n'),
    (error) => process.stdout.write(JSON.stringify({ id: message.id, ok: false, error: String(error && error.message || error) }) + '\n'));
});

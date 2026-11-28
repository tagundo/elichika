'use strict';
// Stub-load test (promoted from the prototype): the patched observer + extension evaluate
// against a minimal Proxy-based Il2Cpp; the original 11 RPCs keep their order, mvruntimeprobe,
// mvruntime and mvruntimeclock are added, all refuse before enablecached (no perform, no dispatch), and
// afterwards use the same cached dispatcher with exactly one 'main' perform.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const vm = require('vm');
const { bundlePath } = require('./fake_il2cpp.cjs');

const bundle = fs.readFileSync(bundlePath(), 'utf8');
const body = bundle.slice(bundle.indexOf('/* Disposable runtime QA observer.'));

function makeContext() {
  const calls = { dispatch: 0, perform: [] };
  const obj = () => new Proxy(function () {}, { get: (t, p) => p === 'method' ? (() => ({ invoke: () => 1280, overload: () => ({ invoke: () => null }) })) : p === 'isNull' ? (() => false) : obj(), apply: () => obj() });
  const klass = { type: { object: {} }, method: (n) => ({ invoke: () => n === 'get_width' ? 1280 : n === 'get_height' ? 720 : n === 'GetActiveScene' ? { method: () => ({ invoke: () => ({ content: 'LiveMv' }) }) } : 7 }), handle: { equals: () => false } };
  let ready = false;
  const core = { installOnCurrentMainThread() { ready = true; }, status() { return { state: ready ? 'READY' : 'NEW', lastCode: null }; },
    dispatch(action) { calls.dispatch++; return Promise.resolve().then(action); }, dispose() { return { redirected: true, handlesFreed: 2 }; } };
  const ctx = { console, Date, JSON, Math, Object, Array, String, Number, Error, Promise, Set, setImmediate, setTimeout, clearTimeout, setInterval, clearInterval,
    Process: { id: 123, arch: 'arm64', getCurrentThreadId: () => 77, findModuleByName: () => null }, Frida: { version: '16.6.6' },
    File: { readAllText: () => 'UnityMain\n' }, Memory: {}, ptr: () => ({}), NULL: {}, Script: { bindWeak() {} }, send() {}, Java: undefined,
    Il2Cpp: { unityVersion: '2018.4.23f1', domain: { assemblies: [{ image: { tryClass: () => klass } }] }, perform(block, flag) { calls.perform.push(flag); return Promise.resolve().then(block); } },
    CachedMainThreadDispatcher: { createIl2CppAdapter: () => core }, rpc: { exports: {} } };
  ctx.globalThis = ctx; ctx.QA_CACHED_BOOTSTRAP_ONLY = true;
  vm.createContext(ctx); vm.runInContext(body, ctx);
  return { ctx, calls };
}
const ORIGINAL = ['enablecached', 'beginintrotrace', 'endintrotrace', 'status', 'dispose', 'initialize', 'snapshot', 'features', 'pick', 'pickmv', 'classes'];

test('original RPC set unchanged; additive mvruntimeprobe, mvruntime and mvruntimeclock', () => {
  const { ctx } = makeContext();
  assert.deepEqual(Object.keys(ctx.rpc.exports), [...ORIGINAL, 'mvruntimeprobe', 'mvruntime', 'mvruntimeclock']);
});
test('mvruntime / mvruntimeprobe refuse before enablecached and never touch the cold scheduler', () => {
  const { ctx, calls } = makeContext();
  assert.throws(() => ctx.rpc.exports.mvruntime({}), /MVDUMP_DISPATCHER_NOT_READY/);
  assert.throws(() => ctx.rpc.exports.mvruntimeprobe({}), /MVDUMP_DISPATCHER_NOT_READY/);
  assert.throws(() => ctx.rpc.exports.mvruntimeclock({}), /MVDUMP_DISPATCHER_NOT_READY/);
  assert.deepEqual(calls.perform, []); assert.equal(calls.dispatch, 0);
});
test('after enablecached the extension dispatches through the same cached dispatcher', async () => {
  const { ctx, calls } = makeContext();
  const proof = { pid: 123, tid: 77, comm: 'UnityMain', source: 'native-debuggerd-engine-loop-and-proc-comm', nativeBacktraceSha256: 'x' };
  const bound = await ctx.rpc.exports.enablecached(proof);
  assert.equal(bound.dispatcher.state, 'READY'); assert.deepEqual(calls.perform, ['main']);
  const before = calls.dispatch;
  // The stub cannot model Unity values, so the action itself may fail; what matters is the path.
  await ctx.rpc.exports.mvruntime({ part: 'frame' }).catch(() => null);
  assert.equal(calls.dispatch, before + 1);
  assert.deepEqual(calls.perform, ['main'], 'no second cold bootstrap');
});

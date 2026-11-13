const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'unity_ui.js'),'utf8');
for (const deferred of [true,false]) {
  let scheduled=0, managedReads=0;
  const context={QA_CACHED_BOOTSTRAP_ONLY:deferred,Process:{id:42,arch:'arm64'},
    Frida:{version:'16.6.6'},rpc:{},setImmediate(){scheduled++;},
    Il2Cpp:new Proxy({},{get(){managedReads++;throw Error('Managed read before asserted TID');}})};
  vm.runInNewContext(source,context,{timeout:1000});
  assert.equal(managedReads,0);
  assert.equal(scheduled,deferred?0:1);
  const status=context.rpc.exports.status();
  assert.equal(status.initializing,false);assert.equal(status.dispatcher,null);
}
process.stdout.write('Deferred observer: two modes, no managed read before host bootstrap; PASS\n');

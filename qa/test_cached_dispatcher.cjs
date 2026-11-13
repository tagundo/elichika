'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {createCore,createIl2CppAdapter}=require('./cached_dispatcher.js');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness(options={}) {
  const callbacks=[];let handler,thread=7,domain=1,context=1,freeCalls=0,postCalls=0,redirects=0;
  const adapter={bootstrapOnCurrentMain(callback){handler=callback;return {mainTid:7,
    postCached(){postCalls++;callbacks.push(handler);},
    assertCurrentMain(){if(thread!==7)throw Object.assign(Error(),{code:'CALLBACK_WRONG_NATIVE_THREAD'});if(domain!==1)throw Object.assign(Error(),{code:'DOMAIN_CHANGED'});if(context!==1)throw Object.assign(Error(),{code:'UNITY_CONTEXT_REPLACED'});},
    redirectAndRelease(){redirects++;return {redirected:true,handlesFreed:2};}};},
    performFree(block){freeCalls++;return block();}};
  const core=createCore(adapter,{timeoutMs:100,maxBatch:2,...options,identity:{pid:123,architecture:'arm64',fridaVersion:'16.6.6'}});
  return {core,callbacks,emit(){callbacks.shift()();},setThread(value){thread=value;},setDomain(value){domain=value;},setContext(value){context=value;},counts(){return {freeCalls,postCalls,redirects};}};
}
test('requires explicit once-only asserted main bootstrap',async()=>{
 const h=harness();await assert.rejects(h.core.dispatch(()=>1),/NOT_READY/);h.core.installOnCurrentMainThread();assert.throws(()=>h.core.installOnCurrentMainThread(),/ALREADY_INSTALLED/);
});
test('batches queue through cached Post and preserves action order',async()=>{
 const h=harness();h.core.installOnCurrentMainThread();const order=[];
 const promises=[1,2,3].map(i=>h.core.dispatch(()=>{order.push(i);return i*2;}));
 await tick();assert.equal(h.callbacks.length,1);assert.equal(h.core.status().pending,3);h.emit();await tick();assert.equal(h.callbacks.length,1);h.emit();
 assert.deepEqual(await Promise.all(promises),[2,4,6]);assert.deepEqual(order,[1,2,3]);assert.deepEqual(h.counts(),{freeCalls:2,postCalls:2,redirects:0});
});
test('wrong actual callback thread rejects all without UI reads',async()=>{
 const h=harness();h.core.installOnCurrentMainThread();let reads=0;const p=h.core.dispatch(()=>reads++);const rejected=assert.rejects(p,/WRONG_NATIVE_THREAD/);await tick();h.setThread(9);h.emit();await rejected;assert.equal(reads,0);assert.equal(h.core.status().state,'POISONED');
});
test('context and domain replacement fail closed before UI reads',async()=>{
 for(const change of ['setContext','setDomain']){const h=harness();h.core.installOnCurrentMainThread();let reads=0;const p=h.core.dispatch(()=>reads++);const rejected=assert.rejects(p,/CHANGED|REPLACED/);await tick();h[change](2);h.emit();await rejected;assert.equal(reads,0);}
});
test('timeout never runs expired action on a late callback or retries cold scheduler',async()=>{
 const h=harness({timeoutMs:15});h.core.installOnCurrentMainThread();let reads=0;const p=h.core.dispatch(()=>reads++);const rejected=assert.rejects(p,/TIMEOUT/);await tick();await rejected;h.emit();assert.equal(reads,0);assert.equal(h.counts().postCalls,1);await assert.rejects(h.core.dispatch(()=>1),/TIMEOUT/);
});
test('synchronous action errors reject that request and preserve later reads',async()=>{
 const h=harness();h.core.installOnCurrentMainThread();const bad=h.core.dispatch(()=>{throw Error('expected read error');});const rejected=assert.rejects(bad,/expected read error/);const good=h.core.dispatch(()=>42);await tick();h.emit();await rejected;assert.equal(await good,42);assert.equal(h.core.status().state,'READY');
});
test('async functions and thenable UI actions are forbidden',async()=>{
 const h=harness();h.core.installOnCurrentMainThread();await assert.rejects(h.core.dispatch(async()=>1),/SYNC_READ_ONLY_ACTION_REQUIRED/);
 const p=h.core.dispatch(()=>Promise.resolve(1));const rejected=assert.rejects(p,/ASYNC_UI_ACTION_FORBIDDEN/);await tick();h.emit();await rejected;assert.equal(h.core.status().state,'POISONED');
});
test('pure status performs no adapter or native work',()=>{
 const h=harness();h.core.installOnCurrentMainThread();const before=h.counts();for(let i=0;i<1000;i++)assert.equal(h.core.status().identity.pid,123);assert.deepEqual(h.counts(),before);
});
test('dispose tombstones before pending callback and never executes its read',async()=>{
 const h=harness();h.core.installOnCurrentMainThread();let reads=0;const p=h.core.dispatch(()=>reads++);const rejected=assert.rejects(p,/DISPOSED/);await tick();assert.equal(h.core.dispose(false).redirected,true);h.emit();await rejected;assert.equal(reads,0);assert.equal(h.counts().redirects,1);
});

function bridgeHarness(){
 const stats={lookups:0,delegates:0,pins:0,free:0,post:0,perform:0,identityReads:0};const posts=[],writes=[];let tid=7,domainId=5000,currentContext,weak,weakTarget;
 const handles=new Map();let next=1;
 class Pointer {constructor(n){this.n=n;}equals(other){return this.n===other.n;}add(n){return {writePointer(value){writes.push({slot:this.n,value});},n:this.n+n};}toString(){return String(this.n);}}
 const domainGet=()=>new Pointer(domainId);const api={domainGet,gcHandleGetTarget:id=>handles.get(id)||new Pointer(0),gcHandleFree:id=>{stats.free++;handles.delete(id);}};
 const context={handle:new Pointer(1000),class:{namespace:'UnityEngine',name:'UnitySynchronizationContext'},isNull:()=>false,ref(){stats.pins++;const handle=next++;handles.set(handle,this.handle);return {handle};},method(name){stats.lookups++;assert.equal(tid,7);assert.equal(name,'Post');return post;}};
 currentContext=context;
 const post={class:context.class,isStatic:false,isInflated:false,returnType:{name:'System.Void',typeEnum:1},parameters:[{type:{name:'System.Threading.SendOrPostCallback'}},{type:{name:'System.Object'}}],fridaSignature:['pointer','pointer','pointer'],nativeFunction:()=>{},invoke(delegate){stats.post++;posts.push(delegate.body);}};
 const currentMethod={isStatic:true,isInflated:false,nativeFunction:()=>{},returnType:{typeEnum:18},invoke(){return currentContext;}};
 const thread={id:7,get synchronizationContext(){stats.lookups++;assert.equal(tid,7);return context;}};
 const I={unityVersion:'2018.4.23f1',currentThread:thread,Type:{enum:{}},api,_callbacksToKeepAlive:{},perform(block,flag){stats.perform++;assert.equal(flag,'free');return block();},corlib:{class(name){stats.lookups++;assert.equal(tid,7);return {method(){stats.lookups++;return currentMethod;},name};}},delegate(klass,body){stats.delegates++;return {body,handle:new Pointer(2000),field(name){stats.lookups++;return {offset:name==='method_ptr'?16:24};},ref(){stats.pins++;const handle=next++;handles.set(handle,this.handle);return {handle};}};}};
 const env={Il2Cpp:I,Process:{get id(){stats.identityReads++;return 123;},get arch(){stats.identityReads++;return 'arm64';},getCurrentThreadId:()=>tid},Frida:{version:'16.6.6'},Script:{bindWeak(target,callback){weakTarget=target;weak=callback;}},NULL:new Pointer(0)};
 return {stats,posts,writes,env,domainGet,setTid(value){tid=value;},setContext(value){currentContext=value;},setDomain(value){domainId=value;},unload(){weak();},weakTarget(){return weakTarget;}};
}
test('Il2Cpp binding creates one delegate and performs no later off-main method lookup',async()=>{
 const b=bridgeHarness();const d=createIl2CppAdapter(b.env,{expectedMainTid:7,timeoutMs:100});d.installOnCurrentMainThread();assert.equal(b.stats.delegates,1);assert.equal(b.stats.pins,2);b.posts.shift()();
 const lookups=b.stats.lookups,identities=b.stats.identityReads;b.setTid(88);const p=d.dispatch(()=>42);await tick();assert.equal(b.stats.lookups,lookups);b.setTid(7);b.posts.shift()();assert.equal(await p,42);for(let i=0;i<10;i++)d.status();assert.equal(b.stats.lookups,lookups);assert.equal(b.stats.identityReads,identities);assert.equal(b.stats.delegates,1);
 d.dispose(false);assert.equal(b.writes.length,2);assert.equal(b.stats.free,2);
});
test('Il2Cpp binding refuses unasserted bootstrap TID',()=>{
 const b=bridgeHarness();const d=createIl2CppAdapter(b.env,{expectedMainTid:99});assert.throws(()=>d.installOnCurrentMainThread(),/NOT_ASSERTED_UNITY_MAIN/);assert.equal(b.stats.delegates,0);
});
test('domain-invalid disposal never writes possibly stale object memory',()=>{
 const b=bridgeHarness();const d=createIl2CppAdapter(b.env,{expectedMainTid:7});d.installOnCurrentMainThread();b.setDomain(6000);const result=d.dispose(false);assert.equal(result.needsOwnedProcessRestart,true);assert.equal(b.writes.length,0);assert.equal(b.stats.free,0);assert.equal(d.status().lastCode,'OWNED_PROCESS_RESTART_REQUIRED');
});

test('weak unload binds the script global rather than a temporary environment wrapper',()=>{
 const b=bridgeHarness();const d=createIl2CppAdapter(b.env,{expectedMainTid:7});d.installOnCurrentMainThread();assert.equal(b.weakTarget(),globalThis);b.unload();assert.equal(d.status().state,'DISPOSED');assert.equal(b.writes.length,2);assert.equal(b.stats.free,2);
});
test('cleanup API failure returns restart requirement and never throws from weak finalizer',()=>{
 let cleanup=0;
 const core=createCore({bootstrapOnCurrentMain(){return {mainTid:7,postCached(){},assertCurrentMain(){},redirectAndRelease(){cleanup++;throw Error('cached runtime API failure');}}},performFree(block){return block();}},{identity:{pid:123}});
 core.installOnCurrentMainThread();const result=core.dispose(true);assert.equal(result.needsOwnedProcessRestart,true);assert.equal(result.cleanupError,true);assert.equal(core.status().state,'POISONED');assert.equal(cleanup,1);
});

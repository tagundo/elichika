/* QA-ONLY dispatcher. Never included in a game APK or server application.
 * Replaces repeated foreign-thread Thread.schedule metadata lookup with one
 * cached UnitySynchronizationContext.Post + one QA-owned delegate.
 */
(function(root) {
  'use strict';
  function fault(code) { const error=new Error(code);error.code=code;return error; }
  function createCore(adapter,options) {
    options=options||{};
    const later=options.setImmediate||setImmediate;
    const startTimer=options.setTimeout||setTimeout;
    const stopTimer=options.clearTimeout||clearTimeout;
    const timeout=options.timeoutMs||10000, batch=options.maxBatch||4;
    const identity=Object.freeze(Object.assign({},options.identity||{}));
    let state='NEW',binding=null,queue=[],posted=false,pumping=false,lastCode=null,sequence=0;
    const outstanding=new Set();
    const counts={enqueued:0,completed:0,rejected:0,postCalls:0,callbacks:0};
    function finish(ticket,ok,value) {
      if(ticket.settled)return;
      ticket.settled=true;ticket.action=null;stopTimer(ticket.timer);outstanding.delete(ticket);
      counts[ok?'completed':'rejected']++;
      // Promise continuations/RPC serialization do not execute inside managed
      // Post's native callback. The actions themselves must remain synchronous.
      later(function(){(ok?ticket.resolve:ticket.reject)(value);});
    }
    function poison(code) {
      if(state==='DISPOSED')return;
      state='POISONED';lastCode=code;
      const pending=Array.from(outstanding);queue=[];
      pending.forEach(function(ticket){finish(ticket,false,fault(code));});
    }
    function postIfNeeded() {
      if(state!=='READY'||posted||pumping||!queue.length)return;
      posted=true;counts.postCalls++;
      // This free attachment may still synchronize in the IL2CPP runtime. It
      // deliberately performs no method/class lookup or delegate construction.
      Promise.resolve().then(function(){return adapter.performFree(function(){
        if(state!=='READY')return;
        binding.postCached();
      });}).catch(function(){posted=false;poison('CACHED_POST_FAILED');});
    }
    function deliver() {
      counts.callbacks++;
      if(state!=='READY')return;
      try { binding.assertCurrentMain(); }
      catch(error) { poison(error&&error.code||'MAIN_BINDING_INVALID');return; }
      posted=false;
      if(pumping){poison('REENTRANT_MAIN_CALLBACK');return;}
      pumping=true;
      try {
        const work=queue.splice(0,batch);
        work.forEach(function(ticket){
          if(ticket.settled)return;
          if(state!=='READY'){finish(ticket,false,fault(lastCode||'DISPATCHER_NOT_READY'));return;}
          try {
            const value=ticket.action();
            if(value&&typeof value.then==='function'){
              finish(ticket,false,fault('ASYNC_UI_ACTION_FORBIDDEN'));
              poison('ASYNC_UI_ACTION_FORBIDDEN');
            } else finish(ticket,true,value);
          } catch(error) { finish(ticket,false,error); }
        });
      } finally { pumping=false; }
      postIfNeeded();
    }
    return {
      installOnCurrentMainThread:function(){
        if(state!=='NEW')throw fault('DISPATCHER_ALREADY_INSTALLED');
        state='INSTALLING';
        try {binding=adapter.bootstrapOnCurrentMain(deliver);state='READY';return this.status();}
        catch(error){state='POISONED';lastCode=error&&error.code||'BOOTSTRAP_FAILED';throw error;}
      },
      dispatch:function(action){
        if(state!=='READY')return Promise.reject(fault(lastCode||'DISPATCHER_NOT_READY'));
        if(typeof action!=='function'||action.constructor&&action.constructor.name==='AsyncFunction')return Promise.reject(fault('SYNC_READ_ONLY_ACTION_REQUIRED'));
        return new Promise(function(resolve,reject){
          const ticket={id:++sequence,action:action,resolve:resolve,reject:reject,settled:false,timer:null};
          ticket.timer=startTimer(function(){
            if(!ticket.settled){finish(ticket,false,fault('MAIN_CALLBACK_TIMEOUT'));poison('MAIN_CALLBACK_TIMEOUT');}
          },timeout);
          queue.push(ticket);outstanding.add(ticket);counts.enqueued++;postIfNeeded();
        });
      },
      invalidate:function(code){poison(code||'HOST_LIFECYCLE_INVALIDATED');},
      dispose:function(fromUnload){
        if(state==='DISPOSED')return {redirected:true,alreadyDisposed:true};
        poison('DISPATCHER_DISPOSED');
        let result;
        try { result=binding?binding.redirectAndRelease(!!fromUnload):{redirected:true,handlesFreed:0}; }
        catch(_) { result={redirected:false,needsOwnedProcessRestart:true,cleanupError:true}; }
        state=result.redirected?'DISPOSED':'POISONED';
        if(!result.redirected)lastCode='OWNED_PROCESS_RESTART_REQUIRED';
        return result;
      },
      status:function(){
        // PLAIN JS ONLY: no Process, Frida, Il2Cpp, pointer or NativeAPI reads.
        return {qaOnly:true,state:state,lastCode:lastCode,posted:posted,pumping:pumping,
          pending:outstanding.size,
          mainTid:binding?binding.mainTid:null,identity:Object.assign({},identity),counts:Object.assign({},counts)};
      }
    };
  }

  function createIl2CppAdapter(env,options) {
    options=options||{};
    const I=env.Il2Cpp,P=env.Process,S=env.Script,N=env.NULL;
    // Cache primitive identities ONCE, outside the public status handler.
    const identity={pid:P.id,architecture:P.arch,fridaVersion:env.Frida.version};
    let core;
    const adapter={
      performFree:function(block){return I.perform(block,'free');},
      bootstrapOnCurrentMain:function(deliver){
        const tid=P.getCurrentThreadId();
        if(!Number.isInteger(options.expectedMainTid)||options.expectedMainTid<=0||tid!==options.expectedMainTid)throw fault('BOOTSTRAP_NOT_ASSERTED_UNITY_MAIN');
        if(I.unityVersion!=='2018.4.23f1')throw fault('UNREVIEWED_UNITY_VERSION');
        const thread=I.currentThread;
        if(!thread||thread.id!==tid)throw fault('CURRENT_IL2CPP_THREAD_MISMATCH');
        // All reflection, execution-context discovery, method signature warming
        // and delegate allocation below occur only in this asserted main call.
        const context=thread.synchronizationContext;
        if(!context||context.isNull()||context.class.namespace+'.'+context.class.name!=='UnityEngine.UnitySynchronizationContext')throw fault('UNITY_CONTEXT_UNAVAILABLE');
        const post=context.method('Post',2);
        if(post.isStatic||post.isInflated||post.returnType.name!=='System.Void'||post.class.namespace+'.'+post.class.name!=='UnityEngine.UnitySynchronizationContext')throw fault('POST_ABI_UNSUPPORTED');
        const parameterNames=post.parameters.map(function(parameter){return parameter.type.name;});
        if(parameterNames[0]!=='System.Threading.SendOrPostCallback'||parameterNames[1]!=='System.Object')throw fault('POST_ABI_UNSUPPORTED');
        const signature=post.fridaSignature;
        if(signature.length!==3||signature.some(function(value){return value!=='pointer';}))throw fault('POST_ABI_UNSUPPORTED');
        // Cache this bound invoke closure, and warm its lazy method/type ABI
        // properties on main. No future call fetches context.method('Post').
        const postCachedInvoke=post.invoke;
        void post.nativeFunction;void post.returnType.typeEnum;void I.Type.enum;
        const contextGet=I.corlib.class('System.Threading.SynchronizationContext').method('get_Current',0);
        if(!contextGet.isStatic||contextGet.isInflated)throw fault('CONTEXT_GET_ABI_UNSUPPORTED');
        const getCurrentCached=contextGet.invoke.bind(contextGet);
        void contextGet.nativeFunction;void contextGet.returnType.typeEnum;
        const actualCurrent=getCurrentCached();
        if(!actualCurrent||!actualCurrent.handle.equals(context.handle))throw fault('UNITY_CURRENT_CONTEXT_MISMATCH');
        const domainGet=I.api.domainGet,getTarget=I.api.gcHandleGetTarget,freeHandle=I.api.gcHandleFree;
        const domain=domainGet();
        const callbackClass=I.corlib.class('System.Threading.SendOrPostCallback');
        const delegate=I.delegate(callbackClass,function(){deliver();});
        // Pinned strong handles protect exact cached object pointers. Fixed
        // count per observer: one context + one delegate; no per-action handle.
        let contextRef=null,delegateRef=null,binding=null;
        try {
        delegateRef=delegate.ref(true);contextRef=context.ref(true);
        const methodPointer=delegate.field('method_ptr'),invokePointer=delegate.field('invoke_impl');
        const methodSlot=delegate.handle.add(methodPointer.offset),invokeSlot=delegate.handle.add(invokePointer.offset);
        const delegatePointer=delegate.handle,contextPointer=context.handle;
        const callbackKey=delegatePointer.toString();
        let redirected=false;
        binding={mainTid:tid,
          postCached:function(){postCachedInvoke(delegate,N);},
          assertCurrentMain:function(){
            if(P.getCurrentThreadId()!==tid)throw fault('CALLBACK_WRONG_NATIVE_THREAD');
            if(!domainGet().equals(domain))throw fault('DOMAIN_CHANGED');
            const now=getCurrentCached();
            if(!now||!now.handle.equals(contextPointer))throw fault('UNITY_CONTEXT_REPLACED');
          },
          redirectAndRelease:function(fromUnload){
            if(redirected)return {redirected:true,handlesFreed:0};
            // All pointers/API callables were cached on main. If ownership is
            // not provable, never write potentially recycled memory. The host
            // must force-stop its owned game process before unloading/retry.
            if(!domainGet().equals(domain)||!getTarget(delegateRef.handle).equals(delegatePointer)||!getTarget(contextRef.handle).equals(contextPointer))return {redirected:false,needsOwnedProcessRestart:true};
            // Only our QA-created delegate is modified. This is the bridge's
            // 0.9.1 unload tombstone: stable native domain_get ignores surplus
            // args; its pointer return is ignored by void SendOrPostCallback.
            methodSlot.writePointer(domainGet);invokeSlot.writePointer(domainGet);
            redirected=true;
            freeHandle(delegateRef.handle);freeHandle(contextRef.handle);
            delete I._callbacksToKeepAlive[callbackKey];
            return {redirected:true,handlesFreed:2,fromUnload:fromUnload};
          }};
        S.bindWeak(env.weakTarget||root,function(){if(core)core.dispose(true);});
        // Warm all conversions/ABI caches through one empty QA callback post.
        // It can run later; it performs no game callback or player-state write.
        postCachedInvoke(delegate,N);
        return binding;
        } catch(error) {
          // No partially initialized pinned handles or posted callback may be
          // silently abandoned. Before first Post, only these owned handles
          // exist; after Post, redirect through the completed binding first.
          if(binding)binding.redirectAndRelease(false);
          else {if(delegateRef)freeHandle(delegateRef.handle);if(contextRef)freeHandle(contextRef.handle);}
          throw error;
        }
      }
    };
    core=createCore(adapter,Object.assign({},options,{identity:identity}));
    return core;
  }
  const exports={createCore:createCore,createIl2CppAdapter:createIl2CppAdapter};
  if(typeof module!=='undefined'&&module.exports)module.exports=exports;
  else root.CachedMainThreadDispatcher=exports;
})(typeof globalThis!=='undefined'?globalThis:this);

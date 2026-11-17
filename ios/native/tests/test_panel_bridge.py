"""Execute the shipped native JS bridge's document/request boundaries under Node.

This does not substitute for the real retained-WK Simulator proof.
"""
from pathlib import Path
import json
import re
import shutil
import subprocess
import unittest


_LITERAL = re.compile(r'@?("(?:\\.|[^"\\])*")')


def _published_scripts(source):
    """Read the actual Objective-C literals, including their append/?: composition."""
    def method(name):
        return source.split('- (void)' + name + ' {', 1)[1].split('\n- (void)', 1)[0]
    def literal(pattern, text):
        match = re.search(pattern, text)
        if not match:
            raise AssertionError('Published probe literal changed: ' + pattern)
        return json.loads(match.group(1))
    activate = source.split('- (WKWebView *)activateSection:(NSInteger)section {', 1)[1].split('- (WKNavigation *)loadPanelURL:', 1)[0]
    reply = source.split('- (void)reply:(NSString *)identifier inWebView:', 1)[1].split('- (void)userContentController:', 1)[0]
    quoted = r'@?("(?:\\.|[^"\\])*")'
    bridge = literal(r'NSString \*script=' + quoted + r';', activate)
    response = literal(r'stringWithFormat:' + quoted + r',ELJSON\(value\)', reply)
    seeds, checks = [], []
    for name in ('probeRetainedPanels', 'probeRetainedAccounts'):
        block = method(name)
        seeds.append(literal(r'NSString \*seed=\[NSString stringWithFormat:' + quoted + r',ELJSON\(arguments\)', block))
        checks.append(literal(r'NSString \*check=\[NSString stringWithFormat:' + quoted + r',ELJSON\(arguments\)', block))
    tool_append = literal(r'NSString \*toolSeed=\[seed stringByAppendingString:' + quoted + r'\];', method('probeRetainedPanels'))
    storage = literal(r'NSString \*script=\[NSString stringWithFormat:' + quoted + r',ELJSON\(arguments\)', source)
    tail = method('pollManagementProbe').split('NSString *script=_managementProbeStep==2', 1)[1]
    helper = source.split('static NSString *ELAccountResponseValidationScript(void) {', 1)[1].split('\n}', 1)[0]
    offline = ''.join(json.loads(match.group(1)) for match in _LITERAL.finditer(helper))
    tail = tail.replace('? ELAccountResponseValidationScript()', '? ' + json.dumps(offline), 1)
    position, branch, bodies = 0, 0, ['', '']
    while True:
        while position < len(tail) and tail[position].isspace():
            position += 1
        token = tail[position:position + 1]
        if token == '?':
            position += 1
            continue
        if token == ':':
            if branch != 0 or not bodies[0]:
                raise AssertionError('Invalid published probe ternary')
            branch, position = 1, position + 1
            continue
        if token == ';':
            if branch != 1 or not bodies[1]:
                raise AssertionError('Incomplete published probe ternary')
            break
        match = _LITERAL.match(tail, position)
        if not match:
            raise AssertionError('Unexpected token in published probe composition')
        bodies[branch] += json.loads(match.group(1))
        position = match.end()
    return {'bridge':bridge, 'reply':response, 'seeds':seeds, 'checks':checks,
            'tool_append':tool_append, 'storage':storage,
            'offline_body':bodies[0], 'management_body':bodies[1]}


def _run_full_probe_scripts(source):
    node = shutil.which('node')
    if node is None:
        raise AssertionError('Node is required to execute the shipped probe programs')
    code = r'''
const assert=require('assert'),vm=require('vm');
const code=JSON.parse(process.argv[1]);let serial=0;
function page(){
  const requests=[],listeners={},fields=new Map(),storage=new Map();let p;
  const context={Promise,Map,Date,Math,URL,crypto:{randomUUID:()=>`document-${++serial}`},
    location:{origin:'http://127.0.0.1:8772',pathname:'/ios/',href:'http://127.0.0.1:8772/ios/?session=fixture',search:'?session=fixture'},
    localStorage:{getItem:k=>storage.has(k)?storage.get(k):null,setItem:(k,v)=>storage.set(k,v)},
    webkit:{messageHandlers:{elichika:{postMessage:r=>{requests.push(r);if(p.onRequest)p.onRequest(r)}}}},
    CustomEvent:class{constructor(type,init){this.type=type;this.detail=init.detail}},
    addEventListener:(name,fn)=>(listeners[name]||(listeners[name]=[])).push(fn),
    dispatchEvent:e=>(listeners[e.type]||[]).forEach(fn=>fn(e)),
    document:{createElement:tag=>({tagName:tag}),getElementById:id=>fields.get(id),
      body:{dataset:{},appendChild:f=>fields.set(f.id,f)}}};
  context.window=context;context.globalThis=context;vm.createContext(context);
  p={context,requests,fields,storage,onRequest:null,run:script=>new vm.Script(script).runInContext(context)};
  p.run(code.bridge);return p;
}
function deliver(p,r,result,error=''){
  return p.run(code.reply.replace('%@',JSON.stringify({id:r.id,document:r.document,result,error})));
}
function formatted(script,args){return script.replace('%@',JSON.stringify(args));}
function body(p,script,args){
  const names=Object.keys(args),fn=p.run('(async function('+names.join(',')+'){'+script+'\n})');
  return fn(...names.map(name=>args[name]));
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const token={token:'unsaved-document-state'},manage=page(),content=page(),tools=page(),accounts=page();
  for(const p of [manage,content]){
    assert.equal(p.run(formatted(code.seeds[0],token)),true);
    const state=p.run(formatted(code.checks[0],token));assert.equal(state.same,true);assert.equal(state.reply,false);
  }
  // Execute EXACTLY what the NSString append publishes. D failed here because
  // its two individually valid fragments composed to `})()window...`.
  const toolProgram=formatted(code.seeds[0],token)+code.tool_append;
  assert.equal(tools.run(toolProgram),true);
  assert.equal(tools.requests.length,1);const pending=tools.requests[0];
  assert.equal(pending.action,'__probe_deferred_status');
  assert.equal(pending.document,tools.context.__elichikaNativeDocument);
  assert.equal(tools.run(formatted(code.checks[0],token)).reply,false);
  deliver(content,pending,{returned_to_origin:true,other_tab_active:true});await flush();
  assert.equal(tools.run(formatted(code.checks[0],token)).reply,false);
  deliver(tools,pending,{returned_to_origin:true,other_tab_active:true});await flush();
  const resumed=tools.run(formatted(code.checks[0],token));assert.equal(resumed.same,true);assert.equal(resumed.reply,true);
  for(const p of [manage,content])assert.equal(p.run(formatted(code.checks[0],token)).same,true);
  assert.equal(accounts.run(formatted(code.seeds[1],token)),true);
  assert.equal(accounts.run(formatted(code.checks[1],token)),true);
  const storagePage=page();
  let stored=storagePage.run(formatted(code.storage,{origin:storagePage.context.location.origin,service:'admin',launch:1}));
  assert.equal(stored.origin_matches,true);assert.equal(stored.prior_present,false);assert.equal(stored.seeded,true);
  stored=storagePage.run(formatted(code.storage,{origin:storagePage.context.location.origin,service:'admin',launch:2}));
  assert.equal(stored.persisted,true);assert.equal(stored.seeded,false);
  const ui=page();let stops=0,starts=0;
  ui.context.ElichikaManagementReady=true;
  let probe={javascript_ready:true,state_fetch:true,controls_present:true,native_binding:true,server_ready:true,error:false};
  ui.context.ElichikaManagementProbe=async()=>probe;
  ui.context.ElichikaManagementProof={server_state:'running'};
  ui.fields.set('server-stop',{disabled:false,click:()=>++stops});
  ui.fields.set('server-start',{disabled:false,click:()=>++starts});
  let value=await body(ui,code.management_body,{step:0,allowStart:false});
  assert.equal(value.requested,'stop');assert.equal(stops,1);
  probe.server_ready=false;ui.context.ElichikaManagementProof.server_state='stopped';
  value=await body(ui,code.management_body,{step:1,allowStart:true});assert.equal(value.requested,'offline_accounts');
  value=await body(ui,code.management_body,{step:1,allowStart:false});assert.equal(value.waiting,true);
  value=await body(ui,code.management_body,{step:3,allowStart:true});assert.equal(value.requested,'start');assert.equal(starts,1);
  ui.fields.get('server-start').disabled=true;
  value=await body(ui,code.management_body,{step:3,allowStart:true});assert.equal(value.waiting,true);assert.equal(starts,1);
  ui.fields.get('server-start').disabled=false;ui.context.ElichikaManagementProof.server_state='starting';
  value=await body(ui,code.management_body,{step:3,allowStart:true});assert.equal(value.waiting,true);assert.equal(starts,1);
  probe.server_ready=true;ui.context.ElichikaManagementProof.server_state='running';
  value=await body(ui,code.management_body,{step:4,allowStart:false});assert.equal(value.server_ready,true);assert.equal(starts,1);
  ui.context.ElichikaManagementReady=false;
  value=await body(ui,code.management_body,{step:0,allowStart:false});assert.equal(value.waiting,true);assert.equal(stops,1);
  ui.context.ElichikaManagementReady=true;probe.error=true;
  value=await body(ui,code.management_body,{step:4,allowStart:false});assert.equal(value.error,true);
  ui.context.ElichikaManagementProbe=async()=>{throw Error('fixture API unavailable')};
  await assert.rejects(()=>body(ui,code.management_body,{step:4,allowStart:false}),/fixture API unavailable/);
  const picker=page();picker.context.location.pathname='/ios/server/webui/user/login';
  picker.context.location.href='http://127.0.0.1:8772/ios/server/webui/user/login?session=fixture';
  picker.context.document.body.dataset.elichikaLocalAccess='true';
  picker.fields.set('native-account-picker',{hidden:false});let count=1,nativeReady=false,fetches=0;
  picker.fields.set('native-account-list',{querySelectorAll:()=>Array(count).fill({})});
  picker.context.fetch=()=>{++fetches;throw Error('Proof must not repeat the account page request')};
  picker.onRequest=r=>queueMicrotask(()=>deliver(picker,r,{real_backend_ready:nativeReady}));
  const accountArgs={step:2,allowStart:true,accountNonce:'fresh-probe',accountGeneration:4};
  const captured={schema:1,nonce:accountArgs.accountNonce,generation:accountArgs.accountGeneration,
    document:picker.context.__elichikaNativeDocument,observed:true,valid:true,http_status:200,count:1};
  picker.context.__elichikaAccountResponse={...captured};
  value=await body(picker,code.offline_body,accountArgs);assert.equal(value.offline_accounts,true);
  assert.equal(picker.requests.at(-1).action,'status');
  for(const invalid of [{http_status:500},{valid:false},{count:-1},{count:1.5}]){
    picker.context.__elichikaAccountResponse={...captured,...invalid};
    value=await body(picker,code.offline_body,accountArgs);assert.equal(value.error,true);
  }
  for(const stale of [{nonce:'old-probe'},{generation:3},{document:'old-document'},{observed:false},{schema:2}]){
    picker.context.__elichikaAccountResponse={...captured,...stale};
    value=await body(picker,code.offline_body,accountArgs);assert.equal(value.waiting,true);
  }
  picker.context.__elichikaAccountResponse={...captured};nativeReady=true;
  value=await body(picker,code.offline_body,accountArgs);assert.equal(value.offline_accounts,false);
  nativeReady=false;count=0;
  value=await body(picker,code.offline_body,accountArgs);assert.equal(value.waiting,true);
  count=1;picker.context.document.body.dataset.elichikaLocalAccess='false';
  value=await body(picker,code.offline_body,accountArgs);assert.equal(value.waiting,true);
  picker.context.document.body.dataset.elichikaLocalAccess='true';picker.context.location.pathname='/other';
  value=await body(picker,code.offline_body,accountArgs);assert.equal(value.waiting,true);assert.equal(fetches,0);
  for(const p of [manage,content,tools]){
    p.context.dispatchEvent({type:'pagehide'});assert.equal(p.run(formatted(code.checks[0],token)).same,false);
  }
  accounts.context.dispatchEvent({type:'pagehide'});assert.equal(accounts.run(formatted(code.checks[1],token)),false);
  console.log(JSON.stringify({full_tools_composition:true,manage_content_state:true,accounts_state:true,
    deferred_native_origin_reply:true,bridge_action_and_nonce:true,storage_scripts:true,management_steps:true,
    management_guards:true,offline_accounts_body:true,offline_accounts_guards:true,async_failures_propagated:true,pagehide_detected:true}));
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    return subprocess.run([node, '-e', code, json.dumps(_published_scripts(source))],
                          capture_output=True, text=True, timeout=15)


class PanelBridgeTests(unittest.TestCase):
    def test_full_published_probe_programs_execute_their_real_composition(self):
        source = (Path(__file__).resolve().parents[1] / 'ElichikaHost.mm').read_text()
        result = _run_full_probe_scripts(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertEqual(len(values), 12)
        self.assertTrue(all(value is True for value in values.values()), values)

    def test_native_reply_document_isolation_and_retention_probe_scripts(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required to exercise the shipped bridge')
        source = (Path(__file__).resolve().parents[1] / 'ElichikaHost.mm').read_text()
        activate = source.split('- (WKWebView *)activateSection:(NSInteger)section {', 1)[1].split('- (WKNavigation *)loadPanelURL:', 1)[0]
        reply = source.split('- (void)reply:(NSString *)identifier inWebView:', 1)[1].split('- (void)userContentController:', 1)[0]
        bridge = re.search(r'NSString \*script=@"([^\n]+)";', activate).group(1)
        response = re.search(r'stringWithFormat:@"([^\n]+)",ELJSON\(value\)', reply).group(1)
        seeds, checks = [], []
        for method in ('probeRetainedPanels', 'probeRetainedAccounts'):
            block = source.split('- (void)' + method + ' {', 1)[1].split('\n- (void)', 1)[0]
            seeds.append(re.search(r'NSString \*seed=\[NSString stringWithFormat:@"([^\n]+)",ELJSON\(arguments\)', block).group(1))
            checks.append(re.search(r'NSString \*check=\[NSString stringWithFormat:@"([^\n]+)",ELJSON\(arguments\)', block).group(1))
        settings = {'bridge': bridge, 'reply': response, 'seeds': seeds, 'checks': checks}
        code = r'''
const assert=require('assert'),vm=require('vm');
const code=JSON.parse(process.argv[1]);let serial=0;
function page(){
  const requests=[],listeners={},fields=new Map();
  const context={Promise,Map,Date,Math,crypto:{randomUUID:()=>`doc-${++serial}`},
    webkit:{messageHandlers:{elichika:{postMessage:r=>requests.push(r)}}},
    CustomEvent:class{constructor(type,init){this.type=type;this.detail=init.detail}},
    addEventListener:(name,fn)=>(listeners[name]||(listeners[name]=[])).push(fn),
    dispatchEvent:e=>(listeners[e.type]||[]).forEach(fn=>fn(e)),
    document:{createElement:tag=>({tagName:tag}),getElementById:id=>fields.get(id),
      body:{appendChild:f=>fields.set(f.id,f)}}};
  context.window=context;context.globalThis=context;vm.createContext(context);vm.runInContext(code.bridge,context);
  return {context,requests,run:script=>vm.runInContext(script,context)};
}
function deliver(p,r,value,error=''){p.run(code.reply.replace('%@',JSON.stringify({id:r.id,document:r.document,result:value,error})));}
(async()=>{
  const a=page(),b=page();let ar,br;
  const pa=a.context.ElichikaIOS.request('import').then(v=>ar=v);
  const pb=b.context.ElichikaIOS.request('import').then(v=>br=v);
  assert.equal(a.requests[0].id,b.requests[0].id);
  deliver(b,a.requests[0],'wrong document');await Promise.resolve();assert.equal(br,undefined);
  deliver(a,a.requests[0],'A only');await pa;assert.equal(ar,'A only');assert.equal(br,undefined);
  deliver(b,b.requests[0],'B only');await pb;assert.equal(br,'B only');
  let oldValue,newValue;const old=a.context.ElichikaIOS.request('import').then(v=>oldValue=v);const oldRequest=a.requests.at(-1);
  a.run(code.bridge);const fresh=a.context.ElichikaIOS.request('import').then(v=>newValue=v),freshRequest=a.requests.at(-1);
  deliver(a,oldRequest,'stale');await Promise.resolve();assert.equal(oldValue,undefined);assert.equal(newValue,undefined);
  deliver(a,freshRequest,'fresh');await fresh;assert.equal(newValue,'fresh');assert.equal(oldValue,undefined);
  a.context.ElichikaIOS.request('status',{id:'spoofed',action:'export',document:'spoofed'});
  const protectedRequest=a.requests.at(-1);assert.notEqual(protectedRequest.id,'spoofed');assert.equal(protectedRequest.action,'status');assert.notEqual(protectedRequest.document,'spoofed');
  let rejection;const failure=b.context.ElichikaIOS.request('export').catch(e=>rejection=e.message);
  deliver(b,b.requests.at(-1),null,'selected file is read only');await failure;assert.equal(rejection,'selected file is read only');
  for(let i=0;i<2;i++){
    const p=page(),args=JSON.stringify({token:'probe-document'});
    assert.equal(p.run(code.seeds[i].replace('%@',args)),true);
    let value=p.run(code.checks[i].replace('%@',args));assert.equal(i===0?value.same:value,true);
    if(i===0){p.context.__elichikaRetentionProbe.reply=true;assert.equal(p.run(code.checks[i].replace('%@',args)).reply,true);}
    p.context.dispatchEvent({type:'pagehide'});value=p.run(code.checks[i].replace('%@',args));assert.equal(i===0?value.same:value,false);
  }
  console.log(JSON.stringify({overlapping_ids:true,wrong_document_ignored:true,late_navigation_ignored:true,
    request_fields_protected:true,native_error_preserved:true,retention_scripts:true,pagehide_detected:true}));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result = subprocess.run([node, '-e', code, json.dumps(settings)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertEqual(len(values), 7)
        self.assertTrue(all(value is True for value in values.values()), values)


if __name__ == '__main__':
    unittest.main()

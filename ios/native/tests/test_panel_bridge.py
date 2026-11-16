"""Execute the shipped native JS bridge's document/request boundaries under Node.

This does not substitute for the real retained-WK Simulator proof.
"""
from pathlib import Path
import json
import re
import shutil
import subprocess
import unittest


class PanelBridgeTests(unittest.TestCase):
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

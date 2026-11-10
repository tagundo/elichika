/* Real server-content form and SSE job, with generated Unity/SQLite and QA-only downloader. */
'use strict';
const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert'),crypto=require('crypto');
const {spawn}=require('child_process'),{chromium}=require('playwright');
const repo=path.resolve(__dirname,'..'),evidence=process.env.EVIDENCE_DIR||fs.mkdtempSync(path.join(os.tmpdir(),'cdn-restore-browser-'));
fs.mkdirSync(evidence,{recursive:true});const fixture=fs.mkdtempSync(path.join(os.tmpdir(),'cdn-restore-runtime-'));
const report={status:'RUNNING',scope:'Actual parent Handler/registry/generic UI/SSE/restore transaction and real generated Unity; ONLY network bytes and process-stop are QA substituted. No real user DB/assets/network accessed.',cases:[]};
const code=String.raw`
import json,os,sys,hashlib
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/modtools',sys.argv[1]+'/tests']
from test_costume_cdn_restore import make_runtime
f=make_runtime(Path(sys.argv[2]));os.environ['SUKUSTA_DIR']=str(f.library);os.environ['SIFAS_LANG']='ko';os.chdir(f.root)
import llas_asset_extractor as ex;ex.COPIED_PACKS_DIR=str(f.library/'packs');ex.detect_game_candidates=lambda:[]
import costume_cdn_restore as restore
mode={'value':'normal'}
def remote(record,*args):
 if mode['value']=='fail':raise ValueError('The original CDN download failed. Check your connection and retry: QA connection interrupted')
 return f.original[record['pack_name']]
restore._remote=remote
from adminui import serverctl
serverctl.stop_server=lambda log:True
from adminui.jobs import MANAGER
MANAGER.bind_runtime_root(f.root)
from adminui.server import Handler
before={str(p.relative_to(f.root)):hashlib.sha256(p.read_bytes()).hexdigest()for p in(f.root/'assets/db').rglob('*.db')}
class Fixture(Handler):
 def do_GET(self):
  if self.path.startswith('/fixture-state'):
   files={str(p.relative_to(f.root)):hashlib.sha256(p.read_bytes()).hexdigest()for parent in(f.root/'static',f.library/'packs')for p in parent.iterdir()if p.is_file()}
   return self._send_json({'files':files,'original':{n:hashlib.sha256(v).hexdigest()for n,v in f.original.items()},'db_unchanged':before=={str(p.relative_to(f.root)):hashlib.sha256(p.read_bytes()).hexdigest()for p in(f.root/'assets/db').rglob('*.db')}})
  return super().do_GET()
 def do_POST(self):
  if self.path=='/fixture-fail':mode['value']='fail';return self._send_json({'ok':True})
  return super().do_POST()
server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
print('FIXTURE_READY='+json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
`;
let server,browser;
(async()=>{try{
 server=spawn(process.env.PYTHON||'python3',['-u','-c',code,repo,fixture],{cwd:repo,env:{...process.env,PYTHONPATH:repo+':'+repo+'/modtools:'+repo+'/tests'},stdio:['ignore','pipe','pipe']});
 const errorLog=fs.createWriteStream(evidence+'/server.stderr.txt');server.stderr.pipe(errorLog);
 const ready=await new Promise((resolve,reject)=>{let buf='';const timer=setTimeout(()=>reject(Error('Fixture startup timeout')),30000);server.stdout.on('data',data=>{buf+=data;for(const line of buf.split('\n'))if(line.startsWith('FIXTURE_READY=')){clearTimeout(timer);resolve(JSON.parse(line.slice(14)));}});server.on('exit',c=>reject(Error('Fixture exited '+c)));});
 const url='http://127.0.0.1:'+ready.port;
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||'/usr/bin/chromium',args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1100,height:760}});page.on('pageerror',error=>{throw error;});
 await page.goto(url);await page.locator('button[data-id="restore_costume_cdn"]').click();
 await page.waitForFunction(()=>Array.from(document.querySelector('#f_costume').options).some(o=>o.value==='suit:10'));
 assert.equal(await page.locator('#f_region').inputValue(),'gl');assert.match(await page.locator('#tool-panel h2').innerText(),/CDN/);
 assert.equal(await page.locator('#f_server_help').count(),0);assert.equal(await page.locator('#f_restore_help').count(),0);
 report.cases.push('KO defaults GL; read-only helper text does not become an input');
 await page.locator('#f_platform').selectOption('android');await page.locator('#f_character').selectOption('1');
 await page.locator('#f_search').fill('10');await page.locator('#f_search').press('Tab');await page.waitForTimeout(100);
 await page.locator('#f_region').selectOption('jp');await page.waitForTimeout(100);await page.locator('#f_region').selectOption('gl');
 await page.waitForFunction(()=>document.querySelector('#f_costume').value==='suit:10');
 report.cases.push('Region/platform/character/search dynamically refresh official costume options');
 await page.locator('#lang-select').selectOption('ja');await page.waitForFunction(()=>document.querySelector('#f_region').value==='jp');
 await page.locator('#lang-select').selectOption('ko');await page.waitForFunction(()=>document.querySelector('#f_region').value==='gl');
 await page.locator('#f_platform').selectOption('android');await page.waitForFunction(()=>document.querySelector('#f_costume').value==='suit:10');
 report.cases.push('JA defaults JP; switching back to KO restores GL');
 const before=await(await fetch(url+'/fixture-state')).json();
 await page.locator('#tool-form .run-btn').click();await page.waitForFunction(()=>document.querySelector('#console-title').textContent.includes('완료 ✓'));
 const after=await(await fetch(url+'/fixture-state')).json();assert(after.db_unchanged);
 for(const parent of ['static','library/packs'])for(const name of ['body','viewbody'])assert.equal(after.files[parent+'/'+name],after.original[name]);
 for(const parent of ['static','library/packs'])for(const name of ['body-ios','viewbody-ios','sharedpack','custom-only'])assert.equal(after.files[parent+'/'+name],before.files[parent+'/'+name]);
 assert.match(await page.locator('#log').innerText(),/코스튬 원본을 복구했습니다/);assert.match(await page.locator('#log').innerText(),/게임 에셋에서 다시/);
 report.cases.push('Real restore job succeeds; active caches original, databases/iOS/shared/custom assets preserved; translated reload guidance');
 await page.screenshot({path:evidence+'/restore-complete.png',fullPage:true});
 await fetch(url+'/fixture-fail',{method:'POST'});await page.locator('#console-close').click();await page.locator('#tool-form .run-btn').click();
 await page.waitForFunction(()=>document.querySelector('#console-title').textContent.includes('오류 ✗'));
 assert.match(await page.locator('#log').innerText(),/연결 상태/);const failed=await(await fetch(url+'/fixture-state')).json();assert.deepEqual(failed.files,after.files);assert(failed.db_unchanged);
 report.cases.push('Real failed job reports actionable KO connection error; every cache/DB remains identical');
 report.status='PASS';
}catch(error){report.status='FAIL';report.error=String(error.stack||error);process.exitCode=1;}finally{if(browser)await browser.close();if(server)server.kill('SIGTERM');fs.writeFileSync(evidence+'/report.json',JSON.stringify(report,null,2));fs.rmSync(fixture,{recursive:true,force:true});console.log(JSON.stringify(report));}})();

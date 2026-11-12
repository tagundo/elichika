/* Genuine admin HTTP/WebGL/SDK render and source-bound staging, without DB installation. */
'use strict';
const assert = require('assert'), crypto = require('crypto'), fs = require('fs'), os = require('os'), path = require('path');
const { spawn } = require('child_process'), { chromium } = require('playwright');
const repo = path.resolve(__dirname, '..'), python = process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'admin-installer-render-'));
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'admin-installer-library-'));
fs.mkdirSync(evidence, { recursive: true });
const code = String.raw`
import ast,hashlib,io,json,os,shutil,socket,sys,zipfile
from pathlib import Path
from http.server import ThreadingHTTPServer
from PIL import Image
import UnityPy
repo,root,evidence=map(Path,sys.argv[1:]);sys.path[:0]=[str(repo),str(repo/'modtools')]
os.environ['SUKUSTA_DIR']=str(root/'library');os.environ['SIFAS_LANG']='en';os.chdir(root)
library=root/'library';suit=library/'suit';suit.mkdir(parents=True)
raw=(repo/'modtools/tests/fixtures/viewer_persistence.unity').read_bytes();env=UnityPy.load(raw);env.file._m_target_platform=13;model=env.file.save(packer='original')
old=io.BytesIO();Image.new('RGBA',(32,32),'magenta').save(old,format='PNG')
for owner in (6,201):
 with zipfile.ZipFile(suit/f'member-{owner}.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
  z.writestr('body.unity',model);z.writestr('old.png',old.getvalue());z.writestr('opaque.bin',b'preserve original payload')
  z.writestr('modinstall.txt',f'chara_id = {owner}\ncostume_file = "body.unity"\nthumbnail_file = "old.png"\ncostume_name = "QA costume"\n')
shutil.copyfile(repo/'modtools/tests/fixtures/viewer_auto_face_costume.zip',suit/'member-207.zip')
shutil.copyfile(repo/'modtools/tests/fixtures/viewer_auto_face_donor.unity',library/'ch0207_facedynamic.unity')
before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in suit.glob('*.zip')}
real_connect=socket.socket.connect
external=[]
def local_connect(sock,address):
 if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1','localhost'):
  external.append(str(address));raise PermissionError('QA forbids external network access')
 return real_connect(sock,address)
socket.socket.connect=local_connect
from adminui import serverctl
from adminui.jobs import MANAGER
MANAGER.bind_runtime_root(root)
from adminui.tools import costume_thumbnail
from adminui.server import Handler
from webtools.core import viewer_thumbnails,model_viewer
real_model=viewer_thumbnails.model
mode={'value':'normal'}
def controlled_model(params):
 if mode['value']=='timeout':raise TimeoutError('QA thumbnail model conversion timed out')
 if mode['value']=='busy':raise model_viewer.ViewerBusyError('QA model converter busy; retry after the current preview')
 return real_model(params)
viewer_thumbnails.model=controlled_model
results=[]
class Fixture(Handler):
 def do_GET(self):
  if self.path.startswith('/fixture-state'):
   return self._send_json({'results':results,'external_connections':external,'originals_unchanged':before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in suit.glob('*.zip')}})
  return super().do_GET()
 def do_POST(self):
  if self.path.startswith('/fixture-mode/'):
   mode['value']=self.path.rsplit('/',1)[1];return self._send_json({'ok':True})
  return super().do_POST()
 def _api_run(self,tool_id):
  if tool_id!='install_costume':return super()._api_run(tool_id)
  params=self._read_json_body();job=MANAGER.create(tool_id)
  def stage(current):
   batch=[]
   with costume_thumbnail.install_inputs(current,params) as prepared:
    for name,item in prepared.items():
     with zipfile.ZipFile(suit/name) as original,zipfile.ZipFile(item['output_path']) as updated:
      manifest=next(n for n in updated.namelist() if n.rsplit('/',1)[-1]=='modinstall.txt')
      values={n.targets[0].id:ast.literal_eval(n.value) for n in ast.parse(updated.read(manifest).decode('utf-8-sig')).body}
      png=updated.read(values['thumbnail_file']);image=Image.open(io.BytesIO(png)).convert('RGBA')
      preserved=all(original.read(n)==updated.read(n) for n in original.namelist() if n!=manifest)
      target=evidence/(str(len(results))+'-'+name+'.png');target.write_bytes(png)
      batch.append({'name':name,'member':values['chara_id'],'thumbnail_sha256':hashlib.sha256(png).hexdigest(),'size':image.size,'models_and_other_payloads_preserved':preserved,'quality':item['quality'],'source_sha256':item['source_sha256'],'png':target.name})
   results.append(batch)
   return 'QA staged exact source-bound 3D thumbnails; DB installer intentionally not invoked'
  MANAGER.run_async(job,stage);return self._send_json({'job_id':job.id})
server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
print('FIXTURE_READY='+json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
`;
let child, browser;
(async () => {
  const report = { status: 'RUNNING', scope: 'Actual admin Handler/registry/UI, shared WebGL renderer, model conversion/GLB, SDK assets, source-bound receipts and thumbnail ZIP staging. Only final database installation is replaced by a staging inspector. Temporary generated Unity/ZIP files; external connections denied.', cases: [] };
  try {
    child = spawn(python, ['-B', '-u', '-c', code, repo, fixture, evidence], { cwd: repo,
      env: { ...process.env, TMPDIR: process.env.TMPDIR || os.tmpdir(), PYTHONDONTWRITEBYTECODE: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
    const stdout = fs.createWriteStream(path.join(evidence, 'server.stdout.txt')), stderr = fs.createWriteStream(path.join(evidence, 'server.stderr.txt'));
    child.stdout.pipe(stdout); child.stderr.pipe(stderr);
    const ready = await new Promise((resolve, reject) => {
      let buffer = ''; const timer = setTimeout(() => reject(new Error('Fixture startup timeout')), 30000);
      child.stdout.on('data', data => { buffer += data; for (const line of buffer.split('\n')) if (line.startsWith('FIXTURE_READY=')) { clearTimeout(timer); resolve(JSON.parse(line.slice(14))); } });
      child.on('exit', exit => reject(new Error('Fixture exited ' + exit)));
    });
    const origin = 'http://127.0.0.1:' + ready.port;
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } }); page.setDefaultTimeout(90000);
    const errors = [], apiErrors = []; page.on('pageerror', error => errors.push(String(error)));
    await page.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    page.on('response', response => { if (response.status() >= 400) apiErrors.push({ path: new URL(response.url()).pathname, status: response.status() }); });
    await page.goto(origin); await page.locator('button[data-id="install_costume"]').click();
    await page.waitForFunction(() => document.querySelector('#f_addon').options.length === 3 && window.ViewerThumbnails);
    const originalHashes = Object.fromEntries(fs.readdirSync(path.join(fixture, 'library/suit')).map(name => [name, crypto.createHash('sha256').update(fs.readFileSync(path.join(fixture, 'library/suit', name))).digest('hex')]));
    async function run(names, full = false) {
      await page.locator('#f_addon').selectOption(names);
      if (full) await page.locator('#f_thumbnail_fit_full').check(); else await page.locator('#f_thumbnail_fit_full').uncheck();
      await page.locator('#tool-form .run-btn').click();
      await page.waitForFunction(() => !state.running);
      assert.match(await page.locator('#console-title').innerText(), /done/ , await page.locator('#log').innerText());
      return page.evaluate(() => ViewerThumbnails.getState());
    }
    const upper = await run(['member-6.zip', 'member-201.zip']);
    assert.equal(upper.receipts.length, 2); assert.equal(upper.last.render.framing.mode, 'head-and-upper-body');
    assert.equal(upper.last.render.material.rimlightEnabled, false); assert(upper.last.render.quality.enabled && upper.last.render.quality.ready);
    assert(upper.last.render.subjectPixels > 0 && upper.last.render.triangles > 0);
    assert(upper.receipts.every(receipt => receipt.quality.highQuality && receipt.quality.rimlight === false && receipt.quality.subject === 'head-and-upper-body-v1'));
    assert.notEqual(upper.receipts[0].sha256, upper.receipts[1].sha256, 'recipient SDK colors produce distinct actual thumbnails');
    let state = await (await fetch(origin + '/fixture-state')).json();
    assert.equal(state.results.length, 1); assert.equal(state.results[0].length, 2);
    state.results[0].forEach((row, index) => { assert.deepEqual(row.size, [256, 256]); assert(row.models_and_other_payloads_preserved); assert.equal(row.thumbnail_sha256, upper.receipts[index].sha256); assert.equal(row.source_sha256, originalHashes[row.name]); });
    await page.screenshot({ path: path.join(evidence, 'installer-hq-preview.png'), fullPage: true });
    report.cases.push({ name: 'Actual multi-ZIP installer→HQ3D→SDK member colors→source-bound replacement copies', renderer: upper, staged: state.results[0] });
    const full = await run(['member-6.zip'], true);
    assert.equal(full.last.render.framing.mode, 'full-character'); assert.equal(full.last.render.framing.fitFullCharacter, true);
    assert.equal(full.receipts[0].quality.subject, 'full-character-v1'); assert.notEqual(full.receipts[0].cacheKey, upper.receipts[0].cacheKey);
    report.cases.push({ name: 'Actual installer full-character option changes framing and source-bound cache', renderer: full });
    const face = await run(['member-207.zip']);
    assert.equal(face.last.render.faces.status, 'added'); assert(face.last.render.faceSources.length > 0);
    assert(face.last.render.visibleNames.includes('Eyes')); assert.equal(face.last.render.material.rimlightEnabled, false);
    report.cases.push({ name: 'Missing original face resolves from private local donor and participates in actual rendered binding', renderer: face });
    for (const mode of ['timeout', 'busy']) {
      await fetch(origin + '/fixture-mode/' + mode, { method: 'POST' });
      const before = (await (await fetch(origin + '/fixture-state')).json()).results.length;
      await page.locator('#tool-form .run-btn').click(); await page.waitForFunction(() => !state.running);
      assert.match(await page.locator('#console-title').innerText(), /error/); assert.match(await page.locator('#log').innerText(), mode === 'timeout' ? /timed out/ : /converter busy/);
      assert.equal((await (await fetch(origin + '/fixture-state')).json()).results.length, before, 'conversion error cannot reach installer staging');
      assert.equal(await page.locator('#costume-install-thumbnail-preview').count(), 0);
      report.cases.push({ name: mode + ' conversion failure is surfaced without installation or texture fallback', status: apiErrors[apiErrors.length - 1] });
    }
    state = await (await fetch(origin + '/fixture-state')).json(); assert(state.originals_unchanged); assert.deepEqual(state.external_connections, []);
    assert.deepEqual(errors, []); report.originals_unchanged = true; report.external_connections = []; report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); process.exitCode = 1; }
  finally { if (browser) await browser.close(); if (child) child.kill('SIGTERM'); fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); fs.rmSync(fixture, { recursive: true, force: true }); console.log(JSON.stringify({ status: report.status, cases: report.cases.map(row => row.name), error: report.error, evidence })); }
})();

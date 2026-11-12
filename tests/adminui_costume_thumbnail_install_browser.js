/* Actual HQ render -> normal install API -> genuine CLI/SQLite/encrypted packs. */
'use strict';
const fs = require('fs'), path = require('path'), os = require('os'), assert = require('assert');
const { spawn } = require('child_process'), { chromium } = require('playwright');
const repo = path.resolve(__dirname, '..');
function option(name) { const index = process.argv.indexOf(name); return index < 0 ? null : process.argv[index + 1]; }
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'hq-real-install-evidence-'));
const providedRoot = option('--fixture-root'), fixture = providedRoot || fs.mkdtempSync(path.join(os.tmpdir(), 'hq-real-install-runtime-'));
const manifest = option('--manifest') || path.join(evidence, 'fixture.json');
const sourceCDN = option('--source-cdn') || 'http://127.0.0.1:18988/static';
fs.mkdirSync(evidence, { recursive: true });
const code = String.raw`
import ast,hashlib,json,os,socket,sqlite3,sys
from pathlib import Path
from contextlib import closing
from http.server import ThreadingHTTPServer
repo,root,evidence=map(Path,sys.argv[1:4]);source=sys.argv[4]
sys.path[:0]=[str(repo),str(repo/'modtools'),str(repo/'tests')]
from test_added_content_cdn_protocol import prepare_neutral_fixture
import test_costume_private_faces as existing
from sifas_asset_crypto import crypt_section
baseline=prepare_neutral_fixture(root,root/'baseline.json',source)
library=root/'library';packs=root/'packs'
fixture=existing.PrivateFaceInstallerTests();fixture.root,fixture.library,fixture.packs=root,library,packs
package,fields,files=fixture.archive('neutralhq',6,face=False,costume_id=900000002)
source_zip_hash=hashlib.sha256(package.read_bytes()).hexdigest()
config_before=(root/'config.json').read_bytes()
os.environ['SUKUSTA_DIR']=str(library);os.environ['SIFAS_LANG']='en';os.chdir(root)
external=[];connect=socket.socket.connect
def local_connect(sock,address):
 if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1','localhost'):
  external.append(str(address));raise PermissionError('QA forbids external network')
 return connect(sock,address)
socket.socket.connect=local_connect
from adminui import serverctl
serverctl.stop_server=lambda log:True
from adminui.jobs import MANAGER
MANAGER.bind_runtime_root(root)
from adminui.server import Handler
class Fixture(Handler):
 def do_GET(self):
  if self.path.startswith('/fixture-result'):
   result=dict(baseline);result['hq_source_zip_sha256']=source_zip_hash
   result['hq_source_zip_unchanged']=hashlib.sha256(package.read_bytes()).hexdigest()==source_zip_hash
   result['configuration_bytes_unchanged']=(root/'config.json').read_bytes()==config_before
   result['external_connections']=external
   with closing(sqlite3.connect(root/'assets/db/gl/masterdata.db')) as master:
    row=master.execute('SELECT model_asset_path,thumbnail_image_asset_path FROM m_suit WHERE id=900000002').fetchone()
   if row is None:return self._send_json(result)
   actual=[]
   with closing(sqlite3.connect(result['asset_db'])) as assets:
    for role,table,asset in [('body','member_model',row[0]),('thumbnail','texture',row[1])]:
     pack,size=assets.execute('SELECT pack_name,size FROM '+table+' WHERE asset_path=?',(asset,)).fetchone()
     raw=(packs/pack).read_bytes();plain=bytearray(raw);crypt_section(plain,12345,0,0)
     actual.append({'name':pack,'path':str(packs/pack),'size':size,'sha256':hashlib.sha256(raw).hexdigest(),
      'plaintext_sha256':hashlib.sha256(plain).hexdigest(),'role':role,'asset_path':asset})
     if role=='body' and bytes(plain)!=files[fields['costume_file']]:raise AssertionError('Installed body changed')
     if role=='thumbnail':(evidence/'installed-thumbnail.png').write_bytes(plain)
   result['mod_packs']=actual;result['hq_actual_cli_installed']=True
   result['hq_suit_id']=900000002;result['hq_thumbnail_asset_path']=row[1]
   return self._send_json(result)
  return super().do_GET()
server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
print('FIXTURE_READY='+json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
`;
let child, browser;
(async () => {
  const report = { status: 'RUNNING', scope: 'Actual admin UI, shared HQ WebGL/SDK renderer, normal install_costume API/job/adapter and genuine costume CLI code writing private SQLite catalogs and encrypted body/thumbnail packs. Only process stopping is substituted because no game server runs in this private fixture. No game UI or external network.', cases: [] };
  try {
    const python = process.env.ELICHIKA_CDN_TEST_PYTHON || process.env.VIEWER_PYTHON || '/workspace/.venv-elichika/bin/python';
    child = spawn(python, ['-B', '-u', '-c', code, repo, fixture, evidence, sourceCDN], { cwd: repo,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
    child.stderr.pipe(fs.createWriteStream(path.join(evidence, 'server.stderr.txt')));
    const ready = await new Promise((resolve, reject) => {
      let pending = ''; const timer = setTimeout(() => reject(Error('Fixture startup timed out')), 60000);
      child.stdout.on('data', data => { pending += data; for (const line of pending.split('\n')) if (line.startsWith('FIXTURE_READY=')) { clearTimeout(timer); resolve(JSON.parse(line.slice(14))); } });
      child.on('exit', status => reject(Error('Fixture exited: ' + status)));
    });
    const origin = 'http://127.0.0.1:' + ready.port;
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', headless: true,
      args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    const page = await browser.newPage({ viewport: { width: 1100, height: 820 } });
    await page.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    await page.goto(origin); await page.locator('button[data-id="install_costume"]').click();
    await page.waitForFunction(() => document.querySelector('#f_addon').options.length >= 2 && window.ViewerThumbnails);
    assert(await page.locator('#f_auto_thumbnail').isChecked());
    assert(!(await page.locator('#f_thumbnail_fit_full').isChecked()));
    await page.locator('#f_addon').selectOption('neutralhq.zip');
    await page.locator('#f_backup').uncheck();
    await page.locator('#tool-form .run-btn').click();
    await page.waitForFunction(() => !state.running, null, { timeout: 90000 });
    const log = await page.locator('#log').innerText();
    assert.match(await page.locator('#console-title').innerText(), /done/, log);
    const renderer = await page.evaluate(() => ViewerThumbnails.getState());
    assert.equal(renderer.receipts.length, 1);
    const receipt = renderer.receipts[0];
    assert(receipt.quality.highQuality && receipt.quality.rimlight === false);
    assert.equal(receipt.quality.subject, 'head-and-upper-body-v1');
    const result = await (await fetch(origin + '/fixture-result')).json();
    assert(result.hq_actual_cli_installed, log);
    assert(result.configuration_bytes_unchanged && result.hq_source_zip_unchanged);
    assert.equal(receipt.sources[0].sha256, result.hq_source_zip_sha256);
    assert.deepEqual(result.external_connections, []);
    assert.equal(result.mod_packs.length, 2);
    const thumbnail = result.mod_packs.find(pack => pack.role === 'thumbnail');
    assert.equal(thumbnail.plaintext_sha256, receipt.sha256, 'Actual installed thumbnail must match the actual rendered PNG');
    result.hq_renderer_receipt = receipt; result.hq_render_report = renderer.last.render;
    fs.mkdirSync(path.dirname(manifest), { recursive: true }); fs.writeFileSync(manifest, JSON.stringify(result, null, 2));
    await page.screenshot({ path: path.join(evidence, 'real-installed-hq-thumbnail.png'), fullPage: true });
    fs.writeFileSync(path.join(evidence, 'installer.log.txt'), log);
    report.status = 'PASS'; report.cases = ['Actual HQ render bound to current source ZIP', 'Normal production install API executes genuine CLI and writes body + thumbnail catalogs/packs', 'Installed thumbnail plaintext PNG SHA256 equals actual renderer receipt', 'Source CDN configuration and source ZIP remain byte-identical'];
    report.fixture = manifest; report.renderer_receipt = receipt; report.installed_packs = result.mod_packs;
    report.configuration_bytes_unchanged = true; report.external_connections = [];
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); process.exitCode = 1; }
  finally {
    if (browser) await browser.close(); if (child) child.kill('SIGTERM');
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2));
    if (!providedRoot) fs.rmSync(fixture, { recursive: true, force: true });
    console.log(JSON.stringify({ status: report.status, evidence, error: report.error }));
  }
})();

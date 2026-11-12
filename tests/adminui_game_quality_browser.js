/* Actual server-content UI/HTTP/SSE/SQLite; only process stop is QA substituted. */
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), os = require('os');
const { spawn } = require('child_process'), { chromium } = require('playwright');
const repo = path.resolve(__dirname, '..');
const output = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'game-quality-browser-'));
const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'game-quality-runtime-'));
fs.mkdirSync(output, { recursive: true });
const report = { status: 'RUNNING', scope: 'Real adminui Handler/registry/form/SSE and real SQLite transactions/recovery. Only stopping an external server is QA-substituted; no real library or game database is modified.', cases: [], errors: [] };
const python = String.raw`
import json,sys,sqlite3,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/tests']
from test_game_quality_settings import make_quality_runtime
root=Path(sys.argv[2])
if not (root/'assets/db/gl/masterdata.db').exists():make_quality_runtime(root)
from adminui.jobs import MANAGER
MANAGER.bind_runtime_root(root)
from adminui import serverctl
serverctl.stop_server=lambda log:True
import game_quality_settings as quality
hold={'next':False};release=threading.Event();release.set();original_commit=quality.commit_change
def commit(plan):
 if hold['next']:
  hold['next']=False
  if not release.wait(30):raise RuntimeError('QA held save timed out')
 return original_commit(plan)
quality.commit_change=commit
from adminui.server import Handler
class Fixture(Handler):
 def do_POST(self):
  if self.path=='/fixture-hold-next':hold['next']=True;release.clear();return self._send_json({'ok':True})
  if self.path=='/fixture-release':release.set();return self._send_json({'ok':True})
  if self.path=='/fixture-external-change':
   with sqlite3.connect(root/'assets/db/gl/masterdata.db')as db:db.execute("UPDATE m_live_quality_setting SET future_note='external edit' WHERE set_id=3 AND quality_mode=10")
   return self._send_json({'ok':True})
  return super().do_POST()
server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
print('READY='+str(server.server_port),flush=True)
server.serve_forever()
`;
let server, browser;
async function start() {
  server = spawn(process.env.PYTHON || 'python3', ['-B', '-u', '-c', python, repo, runtime], { cwd: repo, env: { ...process.env, PYTHONPATH: repo + ':' + repo + '/tests' }, stdio: ['ignore', 'pipe', 'pipe'] });
  server.stderr.pipe(fs.createWriteStream(path.join(output, 'server.stderr.txt'), { flags: 'a' }));
  return await new Promise((resolve, reject) => {
    let text = ''; const timeout = setTimeout(() => reject(new Error('Quality fixture startup timed out')), 30000);
    server.stdout.on('data', chunk => { text += chunk; const match = text.match(/READY=(\d+)/); if (match) { clearTimeout(timeout); resolve('http://127.0.0.1:' + match[1]); } });
    server.on('exit', code => { clearTimeout(timeout); reject(new Error('Quality fixture exited ' + code)); });
  });
}
async function open(page, url, language = 'ko') {
  await page.addInitScript(code => localStorage.setItem('sifas_lang', code), language);
  await page.goto(url + '?lang=' + language);
  await page.locator('button[data-id="game_quality"]').click();
  await page.waitForFunction(() => document.getElementById('game-quality-profile')?.options.length === 13 && !document.getElementById('game-quality-save').disabled);
}
async function state(url, region = 'gl') { return await (await fetch(url + '/api/game-quality?region=' + region + '&lang=en')).json(); }
async function save(page, button = '#game-quality-save') {
  await page.locator(button).click();
  await page.waitForFunction(() => !document.getElementById('game-quality-save').disabled && /저장했습니다|Saved\.|保存しました|변경한 항목이 없습니다/.test(document.getElementById('game-quality-status').textContent));
}
(async () => {
  try {
    let url = await start();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox'] });
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    page.on('pageerror', error => report.errors.push(String(error)));
    await open(page, url);
    assert.equal(await page.locator('#game-quality-region').inputValue(), 'gl');
    assert.equal(await page.locator('[data-quality-field]').count(), 23);
    assert.equal(await page.locator('.game-quality-field-help').count(), 25);
    await page.locator('.game-quality-explanation > summary').click();
    assert.match(await page.locator('.game-quality-explanation').innerText(), /set_id.*quality_mode/s);
    report.cases.push('All25 original columns are explained:23 editable values plus stage/mode identifiers; Korean defaultsGL');
    const initial = await state(url), jp = await state(url, 'jp');
    await page.locator('#game-quality-profile').selectOption('3:10');
    await page.locator('[data-quality-group="member"] > summary').click();
    await page.locator('#game-quality-rendering_resolution').fill('2160');
    await page.locator('#game-quality-member_rim_light').uncheck();
    await save(page);
    let after = await state(url);
    const expected = initial.profiles.map(row => row.set_id === 3 && row.quality_mode === 10 ? { ...row, rendering_resolution: 2160, member_rim_light: 0 } : row);
    assert.deepEqual(after.profiles, expected); assert.deepEqual((await state(url, 'jp')).profiles, jp.profiles);
    assert(after.can_reset); assert.match(await page.locator('#game-quality-status').innerText(), /\.game-quality/);
    report.cases.push('Actual save/SSE/SQLite changes only selected fields/profile; JP, future text/blob values and other presets preserved');
    await page.locator('#game-quality-scope').selectOption('quality');
    await page.locator('#game-quality-rendering_resolution').fill('720'); await save(page);
    after = await state(url);
    for (const row of after.profiles) {
      const prior = expected.find(r => r.set_id === row.set_id && r.quality_mode === row.quality_mode);
      assert.deepEqual(row, row.quality_mode === 10 ? { ...prior, rendering_resolution: 720 } : prior);
    }
    report.cases.push('Same-quality scope applies changed fields only, preserving distinct effect presets');
    await page.locator('#game-quality-rendering_resolution').fill('1800');
    await page.locator('#game-quality-profile').selectOption('1:20'); await page.locator('#game-quality-profile').selectOption('3:10');
    assert.equal(await page.locator('#game-quality-rendering_resolution').inputValue(), '1800');
    await page.locator('#game-quality-reload').click(); await page.waitForFunction(() => document.getElementById('game-quality-rendering_resolution').value === '720');
    report.cases.push('Switching profiles retains unsaved drafts; explicit Reload discards drafts without writing');
    await page.locator('#game-quality-scope').selectOption('profile'); await page.locator('#game-quality-rendering_resolution').fill('1080');
    await fetch(url + '/fixture-external-change', { method: 'POST' });
    await page.locator('#game-quality-save').click();
    await page.waitForFunction(() => !document.getElementById('game-quality-save').disabled && document.getElementById('game-quality-status').textContent.includes('다시 불러온'));
    assert.equal((await state(url)).profiles.find(r => r.set_id === 3 && r.quality_mode === 10).rendering_resolution, 720);
    report.cases.push('A real external DB edit causes stale-revision refusal; no unreviewed overwrite');
    await page.locator('#game-quality-reload').click(); await page.waitForFunction(() => !document.getElementById('game-quality-reset').disabled);
    await save(page, '#game-quality-reset');
    after = await state(url); const reset = after.profiles.find(r => r.set_id === 3 && r.quality_mode === 10);
    assert.equal(reset.rendering_resolution, 1080); assert.equal(reset.member_rim_light, 1); assert.equal(reset.future_note, 'external edit');
    report.cases.push('Restore-before-first-edit resets selected known values and retains new unknown-column edits');
    await page.screenshot({ path: path.join(output, 'desktop.png'), fullPage: true });
    await page.close(); server.kill('SIGTERM'); await new Promise(resolve => server.once('exit', resolve)); url = await start();
    const restarted = await browser.newPage({ viewport: { width: 1280, height: 900 } }); await open(restarted, url);
    assert.deepEqual((await state(url)).profiles, after.profiles);
    assert(!(await restarted.locator('#game-quality-reset').isDisabled()));
    report.cases.push('Fresh HTTP process restart retains actual edited DB and recovery baseline');
    await restarted.locator('#game-quality-profile').selectOption('3:20');
    await restarted.locator('#game-quality-rendering_resolution').fill('1440');
    await fetch(url + '/fixture-hold-next', { method: 'POST' });
    await restarted.locator('#game-quality-save').click();
    await restarted.waitForFunction(() => document.getElementById('game-quality-save').disabled);
    await restarted.locator('button[data-id="backup"]').click();
    await restarted.locator('button[data-id="game_quality"]').click();
    await restarted.waitForFunction(() => document.getElementById('game-quality-status').textContent.includes('데이터 작업'));
    assert(await restarted.locator('#game-quality-save').isDisabled());
    await fetch(url + '/fixture-release', { method: 'POST' });
    await restarted.waitForFunction(() => !document.getElementById('game-quality-reload').disabled);
    await restarted.locator('#game-quality-reload').click();
    await restarted.waitForFunction(() => !document.getElementById('game-quality-save').disabled);
    assert.equal((await state(url)).profiles.find(r => r.set_id === 3 && r.quality_mode === 20).rendering_resolution, 1440);
    report.cases.push('Navigating away during a real held save cannot start another write; old completion unlocks the newly mounted editor');
    await restarted.close();
    const mobile = await browser.newContext({ viewport: { width: 430, height: 900 }, deviceScaleFactor: 2, hasTouch: true });
    const phone = await mobile.newPage(); phone.on('pageerror', error => report.errors.push(String(error))); await open(phone, url, 'ja');
    assert.equal(await phone.locator('#game-quality-region').inputValue(), 'jp');
    await phone.locator('#game-quality-save').scrollIntoViewIfNeeded();
    const geometry = await phone.evaluate(() => ({ overflow: document.documentElement.scrollWidth > innerWidth + 1, buttons: [...document.querySelectorAll('.game-quality-actions button')].map(n => { const r = n.getBoundingClientRect(); return { width: r.width, height: r.height, left: r.left, right: r.right }; }) }));
    assert(!geometry.overflow); assert(geometry.buttons.every(b => b.height >= 44 && b.left >= 0 && b.right <= 430));
    await phone.screenshot({ path: path.join(output, 'phone.png'), fullPage: true }); await mobile.close();
    report.cases.push('Japanese defaultsJP; actual touch layout has44px actions and no horizontal overflow');
    assert.deepEqual(report.errors, []); report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); process.exitCode = 1; }
  finally { if (browser) await browser.close(); if (server) server.kill('SIGTERM'); fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2)); fs.rmSync(runtime, { recursive: true, force: true }); console.log(JSON.stringify({ status: report.status, cases: report.cases.length, error: report.error, output })); }
})();

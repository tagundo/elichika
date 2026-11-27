/* Real Chromium test of the Server content consent question (adminui.jobs done.consent).
 *
 * The real index/CSS/app and translation table are served over localhost; only tool metadata and
 * harmless job fixtures are substituted. The MV timeline pack install ends its first job with the
 * question its server side sends (code UNCHECKED_VALUES, param accept_unchecked); the panel asks
 * with "Install anyway (values not checked)" / Cancel and, only on Install anyway, runs the same
 * job again with accept_unchecked true. No game database or pack is touched.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const EVIDENCE = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'elichika-consent-ui-'));
fs.mkdirSync(EVIDENCE, { recursive: true });
const files = new Map(['adminui/web/index.html', 'adminui/web/ui/app.js', 'adminui/web/ui/style.css']
  .map(name => [name, fs.readFileSync(path.join(ROOT, name))]));
const translations = spawnSync(process.env.PYTHON || 'python3', ['-c',
  'import json; from adminui import i18n; print(json.dumps(i18n.all_strings("ko"), ensure_ascii=False))'],
{ cwd: ROOT, encoding: 'utf8' });
assert.equal(translations.status, 0, translations.stderr);
const strings = JSON.parse(translations.stdout);
const T = text => strings[text] || text;
const report = { status: 'RUNNING', cases: [], errors: [] };
const jobs = new Map(), requests = [];
let nextJob = 0;
const consent = {
  code: 'UNCHECKED_VALUES', param: 'accept_unchecked',
  title: T('Install without checking the timeline values?'),
  message: T("Nothing was installed yet: this server could not check the pack's timeline values. Choose Install anyway to install it as it is, or Cancel."),
  accept: T('Install anyway (values not checked)'),
  items: ['android: ' + T("The pack was made by a newer MV Studio: its timeline holds data this server's MV Studio tools do not write. Updating Elichika and its asset editing tools (modtools) lets this server check it.")],
};
const body = req => new Promise((resolve, reject) => {
  let value = '';
  req.on('data', part => { value += part; });
  req.on('end', () => { try { resolve(JSON.parse(value || '{}')); } catch (error) { reject(error); } });
});
const json = (res, value) => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(value)); };
const tools = () => [{ id: 'install_mv_timeline_pack', label: T('Install MV timeline pack (.sifasmv)'), description: '', fields: [
  { name: 'addon', label: T('File to install'), type: 'select', required: true,
    options: [{ value: 'edit.sifasmv', label: 'edit.sifasmv' }, { value: 'other.sifasmv', label: 'other.sifasmv' }] },
  { name: 'region', label: T('Region'), type: 'select', default: 'gl', options: [{ value: 'gl', label: 'GL' }] },
  { name: 'apply_stage', label: T('Change the stage too (recommended)'), type: 'checkbox', default: true },
] }];
const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://fixture.invalid');
    const staticFiles = { '/': 'adminui/web/index.html', '/ui/app.js': 'adminui/web/ui/app.js', '/ui/style.css': 'adminui/web/ui/style.css' };
    if (staticFiles[url.pathname]) {
      res.writeHead(200, { 'Content-Type': url.pathname.endsWith('.js') ? 'text/javascript' : url.pathname.endsWith('.css') ? 'text/css' : 'text/html' });
      res.end(files.get(staticFiles[url.pathname]));
    } else if (url.pathname === '/api/i18n') json(res, { lang: 'ko', languages: [['ko', '한국어']], strings });
    else if (url.pathname === '/api/tools') json(res, { tools: tools() });
    else if (req.method === 'POST' && url.pathname.startsWith('/api/run/')) {
      const params = await body(req), id = String(++nextJob);
      const item = { id, tool: url.pathname.split('/').at(-1), params, stream: null };
      requests.push(item); jobs.set(id, item); json(res, { job_id: id });
    } else if (/^\/api\/jobs\/\d+\/events$/.test(url.pathname)) {
      const job = jobs.get(url.pathname.split('/')[3]);
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
      res.write(': fixture connected\n\n'); job.stream = res;
      req.on('close', () => { if (job.stream === res) job.stream = null; });
    } else { res.writeHead(404); res.end(); }
  } catch (error) { res.writeHead(500); res.end(String(error)); }
});
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate, message) {
  const deadline = Date.now() + 5000;
  while (!predicate()) { assert.ok(Date.now() < deadline, message); await pause(10); }
}
function emit(job, event) { assert.ok(job.stream, 'SSE is connected'); job.stream.write('data: ' + JSON.stringify(event) + '\n\n'); }
async function start(page) {
  const before = requests.length;
  await page.locator('#tool-form button[type="submit"]').click();
  await until(() => requests.length === before + 1, 'One explicit job request is sent');
  const job = requests.at(-1); await until(() => !!job.stream, 'SSE connects');
  return job;
}
function ask(job) {
  emit(job, { type: 'log', line: '[+  0.4s] ⚠ ' + consent.items[0] });
  emit(job, { type: 'log', line: '[+  0.4s] ' + consent.message });
  emit(job, { type: 'done', status: 'error', summary: consent.message, code: consent.code, consent, output_paths: [] });
}
async function newPage(browser, viewport) {
  const context = await browser.newContext({ viewport });
  await context.addInitScript(() => localStorage.setItem('sifas_lang', 'ko'));
  const page = await context.newPage();
  page.on('pageerror', error => report.errors.push(String(error)));
  await page.goto('http://127.0.0.1:' + server.address().port);
  await page.locator('#tool-list button[data-id="install_mv_timeline_pack"]').click();
  await page.locator('#f_addon').waitFor();
  return { context, page };
}
async function test(name, callback) { await callback(); report.cases.push({ name, status: 'PASS' }); }

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const executablePath = process.env.CHROMIUM_EXECUTABLE || (fs.existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined);
  const browser = await chromium.launch({ executablePath, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    await test('install-anyway-runs-the-same-job-again-with-the-consent-flag', async () => {
      const { context, page } = await newPage(browser, { width: 1280, height: 800 });
      const first = await start(page);
      assert.equal(first.tool, 'install_mv_timeline_pack');
      assert.equal(first.params.accept_unchecked, undefined, 'the first run never consents');
      ask(first);
      const dialog = page.locator('dialog.job-consent');
      await dialog.waitFor();
      assert.equal(await dialog.locator('h3').textContent(), consent.title);
      assert.equal(await dialog.locator('p').textContent(), consent.message);
      assert.deepEqual(await dialog.locator('li').allTextContents(), consent.items);
      assert.equal(await dialog.locator('.job-consent-accept').textContent(), '그래도 설치(값 확인 안 함)');
      assert.ok((await page.locator('#console-title').textContent()).endsWith(T('Not installed — waiting for your choice')));
      assert.equal(await page.evaluate(() => document.activeElement.textContent), T('Cancel'), 'Cancel has the focus');
      await page.screenshot({ path: path.join(EVIDENCE, 'consent-ko-wide.png'), fullPage: true });
      await dialog.locator('.job-consent-accept').click();
      await until(() => requests.length === 2, 'Install anyway sends one more job');
      const second = requests.at(-1);
      assert.deepEqual(second.params, { ...first.params, accept_unchecked: true });
      await until(() => !!second.stream, 'SSE connects');
      // The run that carried the consent is never asked again, even if it answered with a question.
      ask(second);
      await page.waitForFunction(() => document.querySelector('#console-title').textContent.includes('✗'));
      await pause(100);
      assert.equal(await page.locator('dialog.job-consent').count(), 0);
      assert.equal(requests.length, 2);
      await context.close();
    });
    await test('cancel-installs-nothing-and-a-changed-form-is-not-run', async () => {
      const { context, page } = await newPage(browser, { width: 390, height: 844 });
      const before = requests.length;
      ask(await start(page));
      await page.locator('dialog.job-consent').waitFor();
      await page.screenshot({ path: path.join(EVIDENCE, 'consent-ko-phone.png'), fullPage: false });
      const box = await page.locator('dialog.job-consent').boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= 390, 'the question fits a phone');
      await page.locator('dialog.job-consent').getByRole('button', { name: T('Cancel') }).click();
      await pause(150);
      assert.equal(await page.locator('dialog.job-consent').count(), 0);
      assert.equal(requests.length, before + 1, 'Cancel sends nothing');
      assert.ok((await page.locator('#console-title').textContent()).endsWith(T('cancelled')));
      // Escape cancels too.
      ask(await start(page));
      await page.locator('dialog.job-consent').waitFor();
      await page.keyboard.press('Escape');
      await pause(150);
      assert.equal(requests.length, before + 2);
      // A form changed while the question is open is not run with the consent.
      ask(await start(page));
      await page.locator('dialog.job-consent').waitFor();
      await page.evaluate(() => { const select = document.querySelector('#f_addon'); select.value = 'other.sifasmv'; });
      await page.locator('dialog.job-consent .job-consent-accept').click();
      await pause(150);
      assert.equal(requests.length, before + 3, 'the changed form is not installed with the consent');
      await context.close();
    });
    await test('an-ordinary-error-asks-nothing', async () => {
      const { context, page } = await newPage(browser, { width: 1280, height: 800 });
      const before = requests.length;
      const job = await start(page);
      emit(job, { type: 'done', status: 'error', summary: 'Plain refusal.' });
      await page.waitForFunction(() => document.querySelector('#console-title').textContent.includes('✗'));
      await pause(100);
      assert.equal(await page.locator('dialog.job-consent').count(), 0);
      assert.equal(requests.length, before + 1);
      await context.close();
    });
    for (const [name, buffer] of files) assert.ok(fs.readFileSync(path.join(ROOT, name)).equals(buffer), 'UI source changed during run: ' + name);
    assert.deepEqual(report.errors, []); report.status = 'PASS';
  } finally {
    report.requests = requests.map(({ id, tool, params }) => ({ id, tool, params }));
    fs.writeFileSync(path.join(EVIDENCE, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    await browser.close(); for (const job of jobs.values()) if (job.stream) job.stream.end(); await new Promise(resolve => server.close(resolve));
  }
  console.log(JSON.stringify({ status: report.status, cases: report.cases.length, evidence: EVIDENCE, errors: report.errors }));
})().catch(error => { report.status = 'FAILED'; report.failure = String(error.stack || error); fs.writeFileSync(path.join(EVIDENCE, 'report.json'), JSON.stringify(report, null, 2) + '\n'); console.error(error); process.exitCode = 1; });

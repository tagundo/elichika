/* Actual admin form/cancellation/race gating; renderer and installation are QA substituted. */
'use strict';
const assert = require('assert'), fs = require('fs'), http = require('http'), os = require('os'), path = require('path');
const { chromium } = require('playwright');
const repo = path.resolve(__dirname, '..');
const evidence = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'installer-thumbnail-browser-'));
fs.mkdirSync(evidence, { recursive: true });
const token = 'a'.repeat(32), thumbnailHash = 'b'.repeat(64);
const calls = { plans: [], runs: [], failPlan: false };
const installer = { id: 'install_costume', label: 'Install Costume (zip)', fields: [
  { name: 'addon', label: 'Costume ZIPs', type: 'dynamic_select', multi: true, required: true },
  { name: 'auto_thumbnail', label: 'Generate high-quality 3D thumbnail', type: 'checkbox', default: true },
  { name: 'thumbnail_fit_full', label: 'Fit full character in thumbnail', type: 'checkbox', default: false },
  { name: 'backup', label: 'Back up first', type: 'checkbox', default: true },
  { name: 'stop_server', label: 'Stop server', type: 'checkbox', default: true },
  { name: 'restart_server', label: 'Restart server', type: 'checkbox', default: false },
] };
function json(res, body, code = 200) { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)); }
function staticFile(res, file) {
  if (!fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
  const type = file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html';
  res.writeHead(200, { 'Content-Type': type }); res.end(fs.readFileSync(file));
}
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  if (req.method === 'GET') {
    if (url.pathname === '/api/i18n') return json(res, { lang: url.searchParams.get('lang') || 'en', strings: {}, languages: [['en', 'English'], ['ko', '한국어']] });
    if (url.pathname === '/api/tools') return json(res, { tools: [installer, { id: 'backup', label: 'Backup', fields: [] }] });
    if (url.pathname === '/api/options/install_costume') return json(res, { options: [{ value: 'one.zip', label: 'one.zip' }, { value: 'two.zip', label: 'two.zip' }] });
    if (/^\/api\/jobs\/job-\d+\/events$/.test(url.pathname)) {
      res.writeHead(200, { 'Content-Type': 'text/event-stream' });
      res.end('data: ' + JSON.stringify({ type: 'done', status: 'done', summary: 'QA install job completed' }) + '\n\n'); return;
    }
    if (url.pathname === '/') return staticFile(res, path.join(repo, 'adminui/web/index.html'));
    if (url.pathname.startsWith('/ui/')) return staticFile(res, path.join(repo, 'adminui/web', url.pathname));
    if (url.pathname.startsWith('/static/')) return staticFile(res, path.join(repo, 'modtools/webtools/web', url.pathname));
  }
  if (req.method === 'POST') {
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    const params = JSON.parse(Buffer.concat(chunks).toString() || '{}');
    if (url.pathname === '/api/costume-thumbnail/plan') {
      calls.plans.push(params);
      return json(res, calls.failPlan ? { error: 'QA thumbnail planning failed' } : { token, items: [{ name: 'one.zip' }] }, calls.failPlan ? 400 : 200);
    }
    if (url.pathname === '/api/run/install_costume') { calls.runs.push(params); return json(res, { job_id: 'job-' + calls.runs.length }); }
  }
  json(res, { error: 'Fixture endpoint unavailable' }, 404);
});
let browser;
(async () => {
  const report = { status: 'RUNNING', scope: 'Real product HTML/scripts and installer form. Shared renderer is controlled for browser lifecycle tests; all plans/installs use a private HTTP fixture, with no user data, external network, or database writes.', cases: [] };
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
    async function pageFor(mode = 'success') {
      calls.plans = []; calls.runs = []; calls.failPlan = false;
      const page = await browser.newPage();
      page.on('pageerror', error => { report.pageError = String(error); });
      await page.goto('http://127.0.0.1:' + server.address().port);
      await page.waitForFunction(() => typeof selectTool === 'function' && state.tools.length && window.ViewerThumbnails && window.THREE && window.SifasMaterial && window.ViewerQuality);
      await page.locator('button[data-id="install_costume"]').click();
      await page.waitForFunction(() => document.querySelector('#f_addon').options.length === 2);
      await page.locator('#f_addon').selectOption('one.zip');
      await page.evaluate(({ mode, thumbnailHash }) => {
        window.fixtureRender = { mode, calls: 0, release: null };
        window.ViewerThumbnails.renderPlan = (plan, options) => {
          window.fixtureRender.calls += 1;
          const complete = () => {
            const canvas = document.createElement('canvas'); canvas.width = canvas.height = 4;
            options.onProgress(1, 1, 'one.zip');
            options.onPreview(canvas.toDataURL(), { sha256: thumbnailHash });
            return { token: plan.token };
          };
          if (mode === 'error') return Promise.reject(new Error('QA high-quality renderer failed'));
          if (mode === 'success') return Promise.resolve(complete());
          return new Promise((resolve, reject) => {
            window.fixtureRender.release = () => resolve(complete());
            if (mode !== 'ignore-abort') options.signal.addEventListener('abort', () => reject(new DOMException('Thumbnail rendering cancelled.', 'AbortError')), { once: true });
          });
        };
      }, { mode, thumbnailHash });
      return page;
    }
    async function done(page) { await page.waitForFunction(() => !state.running); }
    async function rendering(page) { await page.waitForFunction(() => window.fixtureRender.calls === 1); }
    let page = await pageFor();
    assert(await page.locator('#f_auto_thumbnail').isChecked()); assert(!await page.locator('#f_thumbnail_fit_full').isChecked());
    await page.locator('#tool-form .run-btn').click(); await done(page);
    assert.equal(calls.plans.length, 1); assert.equal(calls.runs.length, 1); assert.equal(calls.runs[0].thumbnail_plan, token);
    assert.equal(calls.plans[0].auto_thumbnail, true); assert.equal(calls.plans[0].thumbnail_fit_full, false);
    assert.deepEqual(calls.runs[0].addon, ['one.zip']); assert.equal(await page.locator('#costume-install-thumbnail-preview').getAttribute('data-sha256'), thumbnailHash);
    report.cases.push('Default HQ3D/upper-body settings prepare source-bound plan, publish preview, and submit token exactly once'); await page.close();
    page = await pageFor(); await page.locator('#f_thumbnail_fit_full').check(); await page.locator('#tool-form .run-btn').click(); await done(page);
    assert.equal(calls.plans[0].thumbnail_fit_full, true); assert.equal(calls.runs[0].thumbnail_fit_full, true);
    report.cases.push('Explicit full-character framing reaches render planning and installation'); await page.close();
    page = await pageFor(); await page.locator('#f_auto_thumbnail').uncheck(); assert(await page.locator('#f_thumbnail_fit_full').isDisabled());
    await page.locator('#tool-form .run-btn').click(); await done(page);
    assert.equal(calls.plans.length, 0); assert.equal(calls.runs.length, 1); assert.equal(calls.runs[0].auto_thumbnail, false); assert(!('thumbnail_plan' in calls.runs[0]));
    assert.equal(await page.evaluate(() => window.fixtureRender.calls), 0);
    report.cases.push('OFF follows original ZIP installation without rendering or a replacement token'); await page.close();
    page = await pageFor('error'); await page.locator('#tool-form .run-btn').click(); await done(page);
    assert.equal(calls.runs.length, 0); assert.match(await page.locator('#log').innerText(), /QA high-quality renderer failed/); assert(await page.locator('#tool-form .run-btn').isEnabled());
    report.cases.push('Renderer failure blocks installation and restores Run without texture fallback'); await page.close();
    page = await pageFor('wait'); await page.locator('#tool-form .run-btn').click(); await rendering(page); assert(await page.locator('#tool-form .run-btn').isDisabled());
    await page.locator('#cancel-btn').click(); await done(page); assert.equal(calls.runs.length, 0); assert.match(await page.locator('#console-title').innerText(), /cancelled/);
    report.cases.push('Cancel aborts rendering before any server job exists and starts no installation'); await page.close();
    for (const change of ['selection', 'option', 'tool', 'language']) {
      page = await pageFor('ignore-abort'); await page.locator('#tool-form .run-btn').click(); await rendering(page);
      if (change === 'selection') await page.locator('#f_addon').selectOption('two.zip');
      else if (change === 'option') await page.locator('#f_thumbnail_fit_full').check();
      else if (change === 'tool') await page.locator('button[data-id="backup"]').click();
      else { await page.locator('#lang-select').selectOption('ko'); await page.waitForFunction(() => state.lang === 'ko' && document.querySelector('#f_addon')); }
      await page.evaluate(() => window.fixtureRender.release()); await done(page);
      assert.equal(calls.runs.length, 0, change + ' cannot submit captured render'); assert.equal(await page.locator('#costume-install-thumbnail-preview').count(), 0);
      assert.match(await page.locator('#log').innerText(), /selection or thumbnail settings changed/);
      report.cases.push('Changed ' + change + ' discards late preview and blocks stale installation'); await page.close();
    }
    page = await pageFor(); calls.failPlan = true; await page.locator('#tool-form .run-btn').click(); await done(page);
    assert.equal(calls.runs.length, 0); assert.equal(await page.evaluate(() => window.fixtureRender.calls), 0); assert.match(await page.locator('#log').innerText(), /QA thumbnail planning failed/);
    report.cases.push('Planning failure blocks rendering and installation'); await page.close();
    assert(!report.pageError, report.pageError); report.status = 'PASS';
  } catch (error) { report.status = 'FAIL'; report.error = String(error.stack || error); process.exitCode = 1; }
  finally { if (browser) await browser.close(); await new Promise(resolve => server.close(resolve)); fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report)); }
})();

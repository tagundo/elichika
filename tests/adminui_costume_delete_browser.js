/* Real Chromium regression for the shared costume-removal UI.
 *
 * The real index/CSS/app and translation table are served over localhost. Only
 * tool metadata and harmless job/inventory fixtures are substituted. EventSource
 * uses a real HTTP SSE stream and the elapsed prefix produced by Job.log. No
 * game database, installed costume, or external service is accessed.
 */
'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const A = 'a'.repeat(32), B = 'b'.repeat(32), C = 'c'.repeat(32), STOCK = 'builtin:5005';
const LABELS = new Map([[A, 'Alpha Costume'], [B, 'Beta Clone'], [C, 'Gamma Clone'], [STOCK, 'Built-in Costume']]);
const BASELINE = process.env.BASELINE_REPRO === '1';
const EVIDENCE = process.env.EVIDENCE_DIR || fs.mkdtempSync(path.join(os.tmpdir(), 'elichika-delete-ui-'));
fs.mkdirSync(EVIDENCE, { recursive: true });
const snapshot = new Map();
for (const name of ['adminui/web/index.html', 'adminui/web/ui/app.js', 'adminui/web/ui/style.css', 'adminui/i18n.py', 'tests/adminui_costume_delete_browser.js'])
  snapshot.set(name, fs.readFileSync(path.join(ROOT, name)));
if (BASELINE) {
  const old = spawnSync('git', ['show', '6903ce335c48c0c6b4014605a538606a94d5a36b:adminui/web/ui/app.js'], { cwd: ROOT });
  assert.equal(old.status, 0, old.stderr.toString());
  snapshot.set('adminui/web/ui/app.js', old.stdout);
}
const translations = spawnSync(process.env.PYTHON || 'python3', ['-c',
  'import json; from adminui import i18n; print(json.dumps(i18n.all_strings("ko"), ensure_ascii=False))'], { cwd: ROOT, encoding: 'utf8' });
assert.equal(translations.status, 0, translations.stderr);
const strings = JSON.parse(translations.stdout);
const T = text => strings[text] || text;
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
const report = { status: 'RUNNING', scope: 'Actual Chromium shared UI; mocked jobs/inventory, no game DB or real deletion',
  source_sha256: Object.fromEntries([...snapshot].map(([k, v]) => [k, hash(v)])), cases: [], errors: [] };
const jobs = new Map(), requests = [], optionsRequests = [];
let inventory = [A, B, C], nextJob = 0;
const body = req => new Promise((resolve, reject) => {
  let value = '';
  req.on('data', part => { value += part; if (value.length > 65536) reject(new Error('Fixture body too large')); });
  req.on('end', () => { try { resolve(JSON.parse(value || '{}')); } catch (error) { reject(error); } });
});
const json = (res, value) => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(value)); };
const tools = () => [{ id: 'costume_delete', label: T('Remove Costume / Clone'), description: '', fields: [
  { name: 'allow_original', label: T('Show and allow removal of built-in costumes (advanced)'), type: 'checkbox', default: false },
  { name: 'installation', label: T('Installed costume or clone'), type: 'dynamic_select', multi: !BASELINE,
    required: true, depends_on: 'allow_original' },
  { name: 'replace_in_use', label: T("Change used costumes to the character's default before removing"), type: 'checkbox', default: false },
] }, { id: 'backup', label: 'Backup Database', fields: [] }];
const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://fixture.invalid');
    const staticFiles = { '/': 'adminui/web/index.html', '/ui/app.js': 'adminui/web/ui/app.js', '/ui/style.css': 'adminui/web/ui/style.css' };
    if (staticFiles[url.pathname]) {
      res.writeHead(200, { 'Content-Type': url.pathname.endsWith('.js') ? 'text/javascript' : url.pathname.endsWith('.css') ? 'text/css' : 'text/html' });
      res.end(snapshot.get(staticFiles[url.pathname]));
    } else if (url.pathname === '/api/i18n') json(res, { lang: 'ko', languages: [['ko', '한국어']], strings });
    else if (url.pathname === '/api/tools') json(res, { tools: tools() });
    else if (url.pathname.startsWith('/api/options/costume_delete')) {
      optionsRequests.push(req.url);
      const ids = url.searchParams.get('allow_original') === 'true' ? [...inventory, STOCK] : inventory;
      json(res, { options: ids.map(value => ({ value, label: LABELS.get(value) || 'Fixture Costume ' + value })) });
    } else if (req.method === 'POST' && url.pathname.startsWith('/api/run/')) {
      const params = await body(req), id = String(++nextJob);
      const item = { id, tool: url.pathname.split('/').at(-1), params, stream: null };
      requests.push(item); jobs.set(id, item); json(res, { job_id: id });
    } else if (/^\/api\/jobs\/\d+\/events$/.test(url.pathname)) {
      const job = jobs.get(url.pathname.split('/')[3]);
      assert.ok(job, 'Unknown fixture SSE job');
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
      res.write(': fixture connected\n\n'); job.stream = res;
      req.on('close', () => { if (job.stream === res) job.stream = null; });
    } else if (req.method === 'POST' && url.pathname.endsWith('/cancel')) json(res, { ok: true });
    else { res.writeHead(404); res.end(); }
  } catch (error) { res.writeHead(500); res.end(String(error)); }
});
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate, message) {
  const deadline = Date.now() + 5000;
  while (!predicate()) { assert.ok(Date.now() < deadline, message); await pause(10); }
}
const idsFor = job => job.params.installations || [].concat(job.params.installation || []).filter(Boolean);
function emit(job, event) { assert.ok(job.stream, 'SSE is connected'); job.stream.write('data: ' + JSON.stringify(event) + '\n\n'); }
function log(job, value, seconds = 1.3) {
  emit(job, { type: 'log', line: `[+${seconds.toFixed(1).padStart(5)}s] ${typeof value === 'string' ? value : JSON.stringify(value)}` });
}
function planFor(ids, extra = {}) {
  const isOriginal = ids.includes(STOCK);
  return { event: 'costume-delete-review', install_ids: [...ids].sort(), installation_count: ids.length,
    install_id: ids.length === 1 ? ids[0] : undefined,
    label: ids.map(id => LABELS.get(id)).join(', '), items: ids.map(install_id => ({ install_id, label: LABELS.get(install_id), suit_ids: [ids.indexOf(install_id) + 5000], is_original: install_id === STOCK })),
    suit_ids: ids.map((_, i) => 5000 + i), deletable: true, blocked_reasons: [], active_references: [],
    row_count: 227, file_count: 16, grant_count: ids.length, preserved_assets: [], reference_replacements: [],
    replace_in_use: false, allow_original: isOriginal, is_original: isOriginal,
    requires_original_confirmation: isOriginal, review_token: 'review-' + ids.join('-'), action_performed: false, ...extra };
}
async function newPage(browser, viewport = { width: 1280, height: 800 }) {
  inventory = [A, B, C];
  const context = await browser.newContext({ viewport });
  await context.addInitScript(() => localStorage.setItem('sifas_lang', 'ko'));
  const page = await context.newPage();
  page.on('pageerror', error => report.errors.push(String(error)));
  await page.goto('http://127.0.0.1:' + server.address().port);
  await page.locator('#tool-list button[data-id="costume_delete"]').click();
  await page.waitForFunction(() => document.querySelector('#f_installation')?.options.length === 3);
  return { context, page };
}
async function select(page, ids) {
  const field = page.locator('.field').filter({ has: page.locator('#f_installation') });
  for (const id of [A, B, C, STOCK]) {
    const box = field.getByRole('checkbox', { name: LABELS.get(id), exact: true });
    if (await box.count()) await box.setChecked(ids.includes(id));
  }
  assert.deepEqual(await page.locator('#f_installation').evaluate(sel => [...sel.selectedOptions].map(o => o.value).sort()), [...ids].sort());
}
async function start(page, selector = '#tool-form button[type="submit"]') {
  const before = requests.length;
  await page.locator(selector).click();
  await until(() => requests.length === before + 1, 'One explicit job request is sent');
  const job = requests.at(-1); await until(() => !!job.stream, 'Actual SSE connection starts');
  return job;
}
async function reviewed(page, ids, extra = {}) {
  await select(page, ids); const job = await start(page);
  assert.equal(job.params.action, 'preview'); assert.deepEqual(idsFor(job), [...ids].sort());
  const plan = planFor(ids, extra); log(job, plan); emit(job, { type: 'done', status: 'done', summary: 'Review complete, not deleted.' });
  await page.locator('#delete-review').waitFor();
  return { job, plan };
}
async function assertNoNewDelete(before) { await pause(80); assert.equal(requests.filter(j => j.params.action === 'delete').length, before); }
async function complete(job, extra = {}, status = 'done') {
  const ids = idsFor(job);
  inventory = inventory.filter(id => !ids.includes(id));
  log(job, { event: 'costume-delete-complete', status: 'deleted', action_performed: true, install_ids: ids,
    deleted_count: ids.length, backup: '/synthetic/recovery-backup', ...extra }, 2.7);
  emit(job, { type: 'done', status, summary: 'Fixture removal committed.' });
}
async function test(name, callback) { await callback(); report.cases.push({ name, status: 'PASS' }); }

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const executablePath = process.env.CHROMIUM_EXECUTABLE || (fs.existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined);
  const browser = await chromium.launch({ executablePath, headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    if (BASELINE) {
      await test('baseline-real-Job-log-prefix-reproduces-missing-confirmation', async () => {
        const { context, page } = await newPage(browser); await page.locator('#f_installation').selectOption(A);
        const job = await start(page); log(job, planFor([A])); emit(job, { type: 'done', status: 'done', summary: 'Review complete.' });
        await page.waitForFunction(() => document.querySelector('#console-title').textContent.includes('완료 ✓'));
        assert.equal(await page.locator('#delete-review').count(), 0);
        assert.equal(requests.filter(j => j.params.action === 'delete').length, 0);
        await page.screenshot({ path: path.join(EVIDENCE, 'baseline-missing-confirmation.png'), fullPage: true }); await context.close();
      });
      report.status = 'REPRODUCED_BASELINE_PREFIX_BUG';
    } else {
      await test('stamped-batch-review-is-not-deletion-and-confirmation-is-reachable', async () => {
        const { context, page } = await newPage(browser); const before = requests.filter(j => j.params.action === 'delete').length;
        await reviewed(page, [B, A]);
        assert.equal(await page.locator('#tool-panel h2').textContent(), '코스튬/복제 삭제');
        assert.ok((await page.locator('#console-title').textContent()).includes(T('Review complete — not deleted yet')));
        assert.ok((await page.locator('#delete-phase').textContent()).includes(T('Review complete — not deleted yet')));
        assert.equal(await page.locator('#delete-confirm').textContent(), T('Back up and remove selected costumes / clones'));
        await assertNoNewDelete(before);
        await page.locator('#delete-confirm').scrollIntoViewIfNeeded();
        assert.ok(await page.locator('#delete-confirm').evaluate(el => { const r = el.getBoundingClientRect(); const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return hit === el || el.contains(hit); }));
        // Capture the document from its top so a sticky header is not stitched
        // into the middle of the full-page evidence after the actionability check.
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({ path: path.join(EVIDENCE, 'batch-review-wide.png'), fullPage: true }); await context.close();
      });
      await test('explicit-batch-confirmation-requires-durable-result-and-refreshes-inventory', async () => {
        const { context, page } = await newPage(browser); const { plan } = await reviewed(page, [B, A]);
        const optionsBefore = optionsRequests.length; const job = await start(page, '#delete-confirm');
        assert.equal(job.params.action, 'delete'); assert.deepEqual(job.params.installations, [A, B]); assert.equal(job.params.review_token, plan.review_token);
        assert.equal(job.params.original_confirmed, false);
        assert.ok(!(await page.locator('#console-title').textContent()).includes(T('Removal complete')));
        await complete(job); await page.locator('#delete-result').waitFor();
        await until(() => optionsRequests.length > optionsBefore, 'Committed deletion refreshes inventory');
        await page.waitForFunction(() => [...document.querySelector('#f_installation').options].filter(o => o.value).length === 1);
        assert.deepEqual(await page.locator('#f_installation').evaluate(sel => [...sel.options].filter(o => o.value).map(o => o.value)), [C]);
        assert.ok((await page.locator('#console-title').textContent()).includes(T('Removal complete')));
        assert.ok((await page.locator('#delete-result').textContent()).includes('/synthetic/recovery-backup'));
        await context.close();
      });
      await test('job-done-alone-never-claims-a-costume-was-removed', async () => {
        const { context, page } = await newPage(browser); await reviewed(page, [A]);
        const job = await start(page, '#delete-confirm'); emit(job, { type: 'done', status: 'done', summary: 'Generic done does not prove a commit.' });
        await page.waitForFunction(() => document.querySelector('#cancel-btn').disabled);
        assert.equal(await page.locator('#delete-result').count(), 0);
        assert.ok(!(await page.locator('#console-title').textContent()).includes(T('Removal complete')));
        assert.deepEqual(inventory, [A, B, C]); await context.close();
      });
      await test('wrong-completion-identity-is-not-success', async () => {
        const { context, page } = await newPage(browser); await reviewed(page, [A]);
        const job = await start(page, '#delete-confirm');
        log(job, { event: 'costume-delete-complete', status: 'deleted', action_performed: true, install_ids: [B], deleted_count: 1, backup: '/synthetic/other' });
        emit(job, { type: 'done', status: 'done' }); await page.waitForFunction(() => document.querySelector('#cancel-btn').disabled);
        assert.equal(await page.locator('#delete-result').count(), 0);
        assert.ok(!(await page.locator('#console-title').textContent()).includes(T('Removal complete'))); await context.close();
      });
      await test('incomplete-completion-count-is-not-full-success', async () => {
        const { context, page } = await newPage(browser); await reviewed(page, [A, B]);
        const job = await start(page, '#delete-confirm');
        log(job, { event: 'costume-delete-complete', status: 'deleted', action_performed: true, install_ids: [A, B], deleted_count: 1, backup: '/synthetic/partial' });
        emit(job, { type: 'done', status: 'done' }); await page.waitForFunction(() => document.querySelector('#cancel-btn').disabled);
        assert.equal(await page.locator('#delete-result').count(), 0);
        assert.ok(!(await page.locator('#console-title').textContent()).includes(T('Removal complete'))); await context.close();
      });
      await test('repeated-confirm-click-sends-one-deletion', async () => {
        const { context, page } = await newPage(browser); await reviewed(page, [A]); const before = requests.length;
        await page.locator('#delete-confirm').evaluate(button => { button.click(); button.click(); });
        await until(() => requests.length >= before + 1, 'An explicit confirm starts one request'); await pause(80);
        assert.equal(requests.length, before + 1); const job = requests.at(-1); await until(() => !!job.stream, 'Deletion SSE connects');
        assert.equal(job.params.action, 'delete'); await complete(job); await page.locator('#delete-result').waitFor(); await context.close();
      });
      await test('durable-completion-followed-by-late-cancel-is-visible-with-a-log-warning', async () => {
        const { context, page } = await newPage(browser); await reviewed(page, [A]);
        const job = await start(page, '#delete-confirm'); await complete(job, {}, 'cancelled');
        await page.locator('#delete-result').waitFor();
        assert.ok((await page.locator('#console-title').textContent()).includes(T('Removal complete — check the log')));
        assert.ok((await page.locator('#delete-result').textContent()).includes(T('Removal finished, but the job reported an error or cancellation. Check the log.')));
        await context.close();
      });
      await test('blocked-review-has-no-delete-action', async () => {
        const { context, page } = await newPage(browser); await reviewed(page, [A], { deletable: false, blocked_reasons: ['Synthetic unresolved game reference'] });
        assert.equal(await page.locator('#delete-confirm').count(), 0);
        assert.ok((await page.locator('#delete-review').textContent()).includes('Synthetic unresolved game reference')); await context.close();
      });
      await test('JSON-inside-an-unstructured-log-is-not-an-actionable-review', async () => {
        const { context, page } = await newPage(browser); await select(page, [A]); const job = await start(page);
        log(job, 'Diagnostic text: ' + JSON.stringify(planFor([A]))); emit(job, { type: 'done', status: 'done' });
        await page.waitForFunction(() => document.querySelector('#cancel-btn').disabled);
        assert.equal(await page.locator('#delete-review').count(), 0); assert.equal(await page.locator('#delete-confirm').count(), 0); await context.close();
      });
      await test('selection-change-invalidates-reviewed-confirmation', async () => {
        const { context, page } = await newPage(browser); await reviewed(page, [A]);
        await select(page, [B]); assert.equal(await page.locator('#delete-confirm').count(), 0);
        const before = requests.length;
        await page.evaluate(() => runTool({ action: 'delete', installations: ['a'.repeat(32)], review_token: 'review-' + 'a'.repeat(32) }));
        await pause(50); assert.equal(requests.length, before); await context.close();
      });
      await test('late-old-review-cannot-replace-newer-selection-or-tool', async () => {
        const { context, page } = await newPage(browser); await select(page, [A]); const job = await start(page);
        await select(page, [B]); log(job, planFor([A])); emit(job, { type: 'done', status: 'done' });
        await pause(100); assert.equal(await page.locator('#delete-review').count(), 0);
        await select(page, [B]); const job2 = await start(page); await page.locator('#tool-list button[data-id="backup"]').click();
        log(job2, planFor([B])); emit(job2, { type: 'done', status: 'done' });
        await pause(100); assert.equal(await page.locator('#delete-review').count(), 0);
        assert.equal(await page.locator('#tool-panel h2').textContent(), 'Backup Database');
        // The source-labelled historical job may finish in its own log sheet;
        // its confirmation must never attach to a different current tool.
        assert.ok((await page.locator('#console-title').textContent()).startsWith('코스튬/복제 삭제 — ')); await context.close();
      });
      await test('built-in-costume-popup-cancel-and-explicit-batch-consent', async () => {
        const { context, page } = await newPage(browser); await page.locator('#f_allow_original').check();
        await page.waitForFunction(() => [...document.querySelector('#f_installation').options].some(o => o.value === 'builtin:5005'));
        await reviewed(page, [A, STOCK]); const before = requests.filter(j => j.params.action === 'delete').length;
        await page.locator('#delete-confirm').click(); await page.locator('dialog.original-confirm').waitFor();
        await page.locator('dialog.original-confirm button').filter({ hasText: T('Cancel') }).click();
        await assertNoNewDelete(before); await page.locator('#delete-confirm').click();
        const beforeRequest = requests.length; await page.locator('dialog.original-confirm .danger').click();
        await until(() => requests.length === beforeRequest + 1, 'Explicit original-costume popup acceptance starts one delete');
        const job = requests.at(-1); await until(() => !!job.stream, 'Deletion SSE connects');
        assert.equal(job.params.original_confirmed, true); assert.equal(job.params.allow_original, true);
        assert.deepEqual(job.params.installations, [A, STOCK]); await complete(job);
        await page.locator('#delete-result').waitFor(); await context.close();
      });
      await test('review-confirmation-fits-modern-portrait-without-keyboard-modifiers', async () => {
        const { context, page } = await newPage(browser, { width: 412, height: 915 }); await reviewed(page, [A, B]);
        await page.locator('#delete-confirm').scrollIntoViewIfNeeded();
        const box = await page.locator('#delete-confirm').boundingBox(); assert.ok(box && box.x >= 0 && box.x + box.width <= 412);
        const job = await start(page, '#delete-confirm'); await complete(job); await page.locator('#delete-result').waitFor();
        await page.screenshot({ path: path.join(EVIDENCE, 'batch-result-portrait.png'), fullPage: true }); await context.close();
      });
      await test('selection-over-the-backend-batch-limit-is-refused-before-any-job-starts', async () => {
        const { context, page } = await newPage(browser);
        inventory = Array.from({ length: 101 }, (_, index) => index.toString(16).padStart(32, '0'));
        await page.getByTitle(T('Load options'), { exact: true }).click();
        await page.waitForFunction(() => document.querySelector('#f_installation').options.length === 101);
        await page.locator('#f_installation').selectOption(inventory, { force: true });
        const before = requests.length; await page.locator('#tool-form button[type="submit"]').click();
        await pause(80); assert.equal(requests.length, before);
        assert.ok((await page.locator('#delete-phase').textContent()).includes(T('Select up to 100 costumes per removal.')));
        await context.close();
      });
      await test('ordinary-backup-job-keeps-its-existing-run-progress-and-done-flow', async () => {
        const { context, page } = await newPage(browser); await page.locator('#tool-list button[data-id="backup"]').click();
        const job = await start(page); assert.equal(job.tool, 'backup'); assert.deepEqual(job.params, {});
        log(job, 'Synthetic backup job log.'); emit(job, { type: 'progress', done: 3, total: 3 });
        emit(job, { type: 'done', status: 'done', summary: 'Synthetic backup completed.' });
        await page.waitForFunction(() => document.querySelector('#console-title').textContent.includes('완료 ✓'));
        assert.equal(await page.locator('#console-title').textContent(), 'Backup Database — ' + T('done ✓'));
        assert.equal(await page.locator('#tool-form button[type="submit"]').isDisabled(), false);
        assert.equal(await page.locator('#progress').evaluate(progress => progress.value === 3 && progress.max === 3), true);
        assert.equal(await page.locator('#delete-phase, #delete-review, #delete-result').count(), 0);
        assert.ok((await page.locator('#log').textContent()).includes('Synthetic backup completed.')); await context.close();
      });
      for (const [name, buffer] of snapshot) assert.equal(hash(fs.readFileSync(path.join(ROOT, name))), hash(buffer), 'UI source changed during run: ' + name);
      assert.deepEqual(report.errors, []); report.status = 'PASS';
    }
  } finally {
    report.requests = requests.map(({ id, tool, params }) => ({ id, tool, params })); report.options_requests = optionsRequests;
    fs.writeFileSync(path.join(EVIDENCE, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    await browser.close(); for (const job of jobs.values()) if (job.stream) job.stream.end(); await new Promise(resolve => server.close(resolve));
  }
  console.log(JSON.stringify({ status: report.status, cases: report.cases.length, evidence: EVIDENCE, errors: report.errors }));
})().catch(error => { report.status = 'FAILED'; report.failure = String(error.stack || error); fs.writeFileSync(path.join(EVIDENCE, 'report.json'), JSON.stringify(report, null, 2) + '\n'); console.error(error); process.exitCode = 1; });

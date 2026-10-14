// Day 9 supplemental checks + Day 10 real local HTTP/graph end-to-end checks.
// Review uses explicitly labelled doubles; all Trace timings come from graphs.
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const out10 = path.join(root, 'docs/test-results/day10');
const out09 = path.join(root, 'docs/test-results/day09');
const runtime = path.join(root, '.runtime/day10-browser');
for (const dir of [out10, out09, runtime]) fs.mkdirSync(dir, { recursive: true });
const cases = [], day9 = [], traces = [], requests = [];
const pass = (label, supplemental = false) => {
  const entry = { id: cases.length + 1, label, status: 'passed' };
  cases.push(entry); if (supplemental) day9.push(entry);
  console.log('PASS ' + entry.id + ': ' + label);
};
let server, edge, cdp, origin, stderr = '';
class CDP {
  constructor(ws) {
    this.ws = ws; this.nextId = 0; this.pending = new Map(); this.errors = []; this.external = [];
    this.dropNext = false; this.invalidTraceNext = false;
    ws.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id); this.pending.delete(message.id);
        message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result);
      }
      if (message.method === 'Runtime.exceptionThrown') this.errors.push(message.params.exceptionDetails);
      if (message.method === 'Fetch.requestPaused') this.intercept(message.params).catch(error => this.errors.push(String(error)));
    });
  }
  async intercept(params) {
    const { requestId, request, responseStatusCode } = params;
    if (!request.url.startsWith(origin + '/')) {
      this.external.push(request.url);
      return this.send('Fetch.failRequest', { requestId, errorReason: 'InternetDisconnected' });
    }
    if (responseStatusCode !== undefined) {
      const body = await this.send('Fetch.getResponseBody', { requestId });
      const text = body.base64Encoded ? Buffer.from(body.body, 'base64').toString() : body.body;
      const data = JSON.parse(text);
      // Preserve the actual server response before any intentional transport
      // or malformed-response injection changes the browser-facing copy.
      traces.push({ path: new URL(request.url).pathname, data: structuredClone(data) });
      if (this.dropNext && request.url.endsWith('/api/negotiation/turn')) {
        this.dropNext = false;
        return this.send('Fetch.failRequest', { requestId, errorReason: 'ConnectionClosed' });
      }
      if (this.invalidTraceNext && request.url.endsWith('/api/negotiation/turn')) {
        this.invalidTraceNext = false;
        data.trace[0].sequence = 2; // Explicit malformed-response injection.
        return this.send('Fetch.fulfillRequest', { requestId, responseCode: 200,
          responseHeaders: [{ name: 'Content-Type', value: 'application/json' }],
          body: Buffer.from(JSON.stringify(data)).toString('base64') });
      }
      return this.send('Fetch.continueRequest', { requestId });
    }
    if (request.method === 'POST' && request.url.includes('/api/')) requests.push({ path: new URL(request.url).pathname, ...JSON.parse(request.postData) });
    return this.send('Fetch.continueRequest', { requestId });
  }
  send(method, params = {}) {
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluate(expression) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
    return r.result.value;
  }
}
async function until(expression, label) {
  for (let i = 0; i < 180; i++) { if (await cdp.evaluate(expression)) return; await pause(50); }
  throw new Error('Timed out: ' + label);
}
async function click(selector) {
  await cdp.evaluate('document.querySelector(' + JSON.stringify(selector) + ').click()'); await pause(30);
}
async function fill(id, value, type = 'input') {
  await cdp.evaluate(`(() => { const e = document.getElementById(${JSON.stringify(id)}); e.value = ${JSON.stringify(value)}; e.dispatchEvent(new Event(${JSON.stringify(type)}, {bubbles:true})); })()`);
  await pause(30);
}
async function shot(dir, name) {
  const r = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  fs.writeFileSync(path.join(dir, name + '.png'), Buffer.from(r.data, 'base64'));
}
const latest = () => traces.filter(item => item.path === '/api/negotiation/turn').at(-1).data;
async function visibleTraceEquals(data) {
  await until('document.querySelectorAll(".trace-event").length === ' + data.trace.length, 'all actual trace nodes replayed');
  const rendered = await cdp.evaluate('[...document.querySelectorAll(".trace-event")].map(e=>({status:e.dataset.status, text:e.textContent}))');
  data.trace.forEach((event, index) => {
    assert.equal(event.sequence, index + 1);
    assert.equal(rendered[index].status, event.status);
    assert.ok(rendered[index].text.includes(event.node));
    assert.ok(Number.isFinite(event.duration_ms) && event.duration_ms >= 0 && event.attempt <= 3);
    event.feedback.forEach(text => assert.ok(rendered[index].text.includes(text)));
  });
}
async function message(text) {
  await fill('negotiation-draft', text);
  await click('#message-privacy-confirm');
  await until('!document.getElementById("send-negotiation").disabled', 'OpenAPI + confirmed draft enables sending');
}
async function normalTurn(text, score) {
  await message(text);
  await click('#send-negotiation');
  await until(`document.getElementById('negotiation-score').textContent === '${score} / 100'`, 'committed score ' + score);
  await visibleTraceEquals(latest());
  assert.equal(await cdp.evaluate('document.querySelector(".score-track").getAttribute("aria-valuenow")'), String(score));
  assert.equal(await cdp.evaluate('document.getElementById("score-fill").style.width'), score + '%');
  await pause(450);
  assert.ok(Math.abs(await cdp.evaluate('document.getElementById("score-fill").getBoundingClientRect().width / document.querySelector(".score-track").getBoundingClientRect().width * 100') - score) < 1);
}
(async () => {
  server = spawn(path.join(root, '.venv/Scripts/python.exe'), ['-u', 'scripts/day10_offline_app.py'], { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  server.stderr.on('data', data => { stderr += data; });
  origin = await new Promise((resolve, reject) => {
    let output = ''; const timer = setTimeout(() => reject(new Error('local server startup: ' + stderr)), 20000);
    server.stdout.on('data', data => { output += data; const m = output.match(/READY (\d+)/); if (m) { clearTimeout(timer); resolve('http://127.0.0.1:' + m[1]); } });
    server.once('exit', code => { clearTimeout(timer); reject(new Error('local server exit ' + code + ': ' + stderr)); });
  });
  for (let i = 0; i < 100; i++) { try { if ((await fetch(origin + '/api/health')).ok) break; } catch {} await pause(100); }
  const profile = path.join(runtime, 'edge-profile-' + Date.now());
  edge = spawn('C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe', [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-background-networking', '--disable-extensions', '--remote-debugging-port=0',
    '--user-data-dir=' + profile, 'about:blank',
  ], { windowsHide: true, stdio: 'ignore' });
  let port;
  for (let i = 0; i < 150; i++) { try { port = Number(fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0]); break; } catch {} await pause(100); }
  assert.ok(port, 'headless Edge starts');
  const target = await (await fetch('http://127.0.0.1:' + port + '/json/new?about:blank', { method: 'PUT' })).json();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(resolve => ws.addEventListener('open', resolve, { once: true })); cdp = new CDP(ws);
  await cdp.send('Runtime.enable'); await cdp.send('Page.enable');
  await cdp.send('Network.enable'); await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
  await cdp.send('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' },
    { urlPattern: '*/api/negotiation/turn', requestStage: 'Response' }, { urlPattern: '*/api/review/analyze-detailed', requestStage: 'Response' }] });
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1080, deviceScaleFactor: 1, mobile: false });
  await cdp.send('Page.navigate', { url: origin });
  await until('!!document.getElementById("app") && !document.getElementById("app").hasAttribute("v-cloak")', 'Vue mounts');
  pass('Cold-cache local assets mount; real OpenAPI is available');
  const raw = '合成演练合同。联系电话13800000000，身份证110101199001010000。\n租赁结束后可不说明理由直接扣留全部押金。\n维修责任和费用均由租客承担。\n提前退租须支付固定违约金2000元。';
  await fill('contract-input', raw); await click('.panel:first-child .btn-primary');
  const preview = await cdp.evaluate('document.getElementById("preview-input").value');
  assert.ok(!preview.includes('13800000000') && !preview.includes('110101199001010000'));
  assert.equal(requests.length, 0); pass('Contract input is masked in editable preview before any submit');
  await click('#privacy-confirm'); await click('.panel:first-child .btn-primary');
  await until('document.querySelector(".panel:nth-child(2)").getAttribute("aria-busy") === "true"', 'review pending');
  assert.equal(await cdp.evaluate('document.querySelectorAll(".trace-event").length'), 0);
  await pause(1050);
  assert.ok(await cdp.evaluate('document.querySelector(".panel:nth-child(2)").textContent.includes("已用时 1 秒")'));
  pass('Waiting timer advances while no unfinished Trace nodes are displayed', true);
  await until('document.querySelectorAll(".risk-card").length === 3', 'three review cards');
  assert.equal(requests[0].contract_text, preview);
  assert.deepEqual(traces[0].data.trace.map(e => e.node), ['configuration', 'retrieval', 'drafting', 'critic']);
  await visibleTraceEquals(traces[0].data);
  await click('.risk-select');
  assert.equal(await cdp.evaluate('document.querySelector("#submitted-document mark").textContent'), '租赁结束后可不说明理由直接扣留全部押金。');
  pass('Real review route/graph accepts sanitized snapshot; exact clause highlight and evidence card render');
  await shot(out10, 'input-review-highlight');
  await message('希望核对押金收据，合成联系电话13900000000。');
  await click('#send-negotiation');
  assert.equal(requests.filter(r => r.path === '/api/negotiation/turn').length, 0);
  assert.ok(await cdp.evaluate('!document.getElementById("message-privacy-confirm").checked && document.getElementById("negotiation-draft").value.includes("***")'));
  pass('Negotiation message final scan masks new phone and revokes confirmation before uploading');
  await click('#message-privacy-confirm');
  const priorTraceCount = await cdp.evaluate('document.querySelectorAll(".trace-event").length');
  await cdp.evaluate('document.getElementById("send-negotiation").click(); document.getElementById("send-negotiation").click()');
  await pause(1000);
  assert.equal(requests.filter(r => r.path === '/api/negotiation/turn').length, 1);
  assert.ok(await cdp.evaluate('document.getElementById("export-checklist").disabled && document.getElementById("scenario-select").disabled && document.getElementById("send-negotiation").disabled'));
  assert.equal(await cdp.evaluate('document.querySelectorAll(".trace-event").length'), priorTraceCount);
  pass('Pending negotiation prevents duplicate submit, scene changes and export; keeps prior actual Trace', true);
  await until('document.getElementById("negotiation-score").textContent === "50 / 100"', 'deposit first commit');
  await visibleTraceEquals(latest());
  assert.equal(latest().confirmed_terms.deposit_refund, 1000);
  pass('Deposit commits 1000 yuan / 50 with exact real node order, durations and Critic feedback', true);
  await normalTurn('请进一步协商返还金额。', 75);
  pass('Deposit second turn reaches 1500 / 75; animated progress and previous snapshot agree', true);
  const beforeFailure = await cdp.evaluate('document.getElementById("confirmed-terms").textContent');
  await fetch(origin + '/_test/mode', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({value:'critic_failure'}) });
  await message('故障注入：质检拒绝越界报价。'); await click('#send-negotiation');
  await until('document.querySelector(".notice-error")?.textContent.includes("本次协商未提交")', 'critic failure UI');
  const failed = latest(); assert.equal(failed.status, 'needs_review'); assert.equal(failed.retry_count, 2);
  await visibleTraceEquals(failed);
  assert.equal(failed.trace.filter(e => e.node === 'landlord').length, 3);
  assert.equal(await cdp.evaluate('document.getElementById("confirmed-terms").textContent'), beforeFailure);
  assert.equal(await cdp.evaluate('document.getElementById("negotiation-score").textContent'), '75 / 100');
  pass('Injected Critic failure stops after three generations; score, conditions and round remain unchanged', true);
  await shot(out09, 'critic-failure-replay');
  await fetch(origin + '/_test/mode', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({value:'normal'}) });
  cdp.dropNext = true;
  await message('网络故障注入：服务已提交但首个响应丢失。'); await click('#send-negotiation');
  await until('document.getElementById("send-negotiation").textContent.includes("重试同一条消息")', 'lost response retry');
  assert.equal(await cdp.evaluate('document.getElementById("negotiation-score").textContent'), '75 / 100');
  const sent = requests.at(-1);
  await click('#send-negotiation');
  await until('document.getElementById("negotiation-score").textContent === "100 / 100"', 'cached committed response applied');
  assert.deepEqual(requests.at(-1), sent); assert.equal(latest().replayed, true); assert.equal(latest().round_count, 3);
  await visibleTraceEquals(latest());
  assert.equal(await cdp.evaluate('document.getElementById("trace-title").textContent'), '缓存响应回放');
  pass('Lost response retry reuses exact request ID, commits once and explicitly labels cached replay', true);
  await cdp.evaluate('Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async text=>{window.__checklist=text}}})');
  await fill('unresolved-requests', '请补充返还日期；测试手机号13800000000');
  await click('#export-checklist');
  const checklist = await cdp.evaluate('window.__checklist');
  assert.ok(checklist.includes('押金扣留') && checklist.includes('2000') && checklist.includes('100 / 100') && !checklist.includes('13800000000'));
  pass('Checklist copy exports only official terms plus separately marked unresolved items and masks manual PII', true);
  await cdp.evaluate('navigator.clipboard.writeText=async()=>{throw new Error("injected denied clipboard")}');
  await click('#export-checklist');
  assert.equal(await cdp.evaluate('document.getElementById("checklist-copy").value'), checklist);
  pass('Denied clipboard shows exact manual-copy fallback without claiming copy success', true);
  fs.writeFileSync(path.join(out10, 'deposit-checklist.md'), checklist + '\n');
  await shot(out10, 'deposit-closed-loop');
  await shot(out09, 'score-trace-export');
  // Select prior successful response: history must be explicitly labelled.
  const historyId = await cdp.evaluate('document.getElementById("trace-run").options[1].value');
  await fill('trace-run', historyId, 'change');
  assert.equal(await cdp.evaluate('document.getElementById("trace-title").textContent'), '历史执行回放');
  pass('Previously received response is labelled history, distinct from latest/cached execution', true);
  for (const [scenario, key, label, finalValue] of [['maintenance','repair_cost_share','维修责任',100], ['early_termination','termination_fee','提前退租',0]]) {
    const previousSid = requests.filter(r => r.path === '/api/negotiation/turn').at(-1).session_id;
    await fill('scenario-select', scenario, 'change');
    assert.equal(await cdp.evaluate('document.getElementById("negotiation-score").textContent'), '不可评分');
    assert.ok(await cdp.evaluate('!document.getElementById("checklist-copy")'));
    // Repeat input -> sanitized preview -> actual review per scenario, then
    // highlight its own clause rather than reusing the deposit selection.
    await click('.panel:first-child .text-btn');
    await fill('contract-input', raw); await click('.panel:first-child .btn-primary');
    await click('#privacy-confirm'); await click('.panel:first-child .btn-primary');
    await until('document.querySelectorAll(".risk-card").length === 3', 'new scene review');
    await visibleTraceEquals(traces.filter(t => t.path === '/api/review/analyze-detailed').at(-1).data);
    const clauseId = scenario === 'maintenance' ? 'C-02' : 'C-03';
    await click('[aria-label="定位条款 ' + clauseId + '"]');
    assert.ok((await cdp.evaluate('document.querySelector("#submitted-document mark").textContent')).includes(scenario === 'maintenance' ? '维修' : '提前退租'));
    for (const score of [50, 75, 100]) await normalTurn('请核对事实并明确本轮条件。', score);
    assert.equal(latest().scenario, scenario); assert.equal(latest().confirmed_terms[key], finalValue);
    assert.notEqual(requests.at(-1).session_id, previousSid);
    assert.equal(Object.keys(latest().confirmed_terms).length, 1);
    await cdp.evaluate('navigator.clipboard.writeText=async text=>{window.__checklist=text}');
    await click('#export-checklist');
    const text = await cdp.evaluate('window.__checklist'); assert.ok(text.includes(label) && text.includes('100 / 100'));
    fs.writeFileSync(path.join(out10, scenario + '-checklist.md'), text + '\n');
    await shot(out10, scenario + '-closed-loop');
    pass(label + ' repeats input/preview/review/highlight, three turns (50/75/100), real Trace and export; sessions isolate terms');
  }
  // Validate malformed Trace fail-closed behavior with an explicit response injection.
  cdp.invalidTraceNext = true;
  await message('故障注入：破坏响应Trace序号。'); await click('#send-negotiation');
  await until('document.querySelector(".trace-section").textContent.includes("Trace 格式不符合约定")', 'malformed trace rejected');
  assert.equal(await cdp.evaluate('document.querySelectorAll(".trace-event").length'), 0);
  pass('Injected discontinuous Trace is rejected without fabricating replacement nodes', true);
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await pause(200);
  assert.ok(await cdp.evaluate('document.documentElement.scrollWidth <= 390'));
  await shot(out10, 'mobile-replay');
  pass('Mobile replay/export layout has no horizontal overflow', true);
  assert.ok(!JSON.stringify(requests).includes('13800000000') && !JSON.stringify(requests).includes('13900000000') && !JSON.stringify(requests).includes('110101199001010000'));
  for (const response of traces) {
    response.data.trace.forEach((event, index) => assert.equal(event.sequence, index + 1, 'archived server Trace must stay intact before injection'));
  }
  assert.equal(cdp.errors.length, 0, JSON.stringify(cdp.errors)); assert.equal(cdp.external.length, 0);
  const diagnostics = await (await fetch(origin + '/_test/diagnostics')).json(); assert.equal(diagnostics.blocked_external_calls, 0);
  pass('Browser and local server make zero external/cloud calls; no runtime exceptions or unmasked request identifiers');
  const report = { verifiedAt: new Date().toISOString(), mode: 'real_local_fastapi_and_graphs_review_doubles_fixed_negotiation_policy',
    browser: (await cdp.send('Browser.getVersion')).product, node: process.version,
    passed: cases.length, failed: 0, skipped: 0, externalRequests: cdp.external.length, runtimeExceptions: cdp.errors.length,
    ...diagnostics, cases };
  fs.writeFileSync(path.join(out10, 'browser-results.json'), JSON.stringify(report, null, 2) + '\n');
  // Only public actual responses are archived; request payloads and synthetic raw identifiers are excluded.
  fs.writeFileSync(path.join(out10, 'actual-http-traces.json'), JSON.stringify(traces, null, 2) + '\n');
  fs.writeFileSync(path.join(out09, 'browser-results.json'), JSON.stringify({ ...report, scope: 'Day 9 features supplemented on 2026-10-14 against Day 10 working tree, not historical evidence', passed: day9.length, cases: day9 }, null, 2) + '\n');
  console.log(`${cases.length} passed, 0 failed, 0 skipped; Day 9 supplemental groups: ${day9.length}; external/cloud calls: 0.`);
})().catch(error => { console.error(error); console.error(stderr); process.exitCode = 1; }).finally(async () => {
  if (cdp) { try { await cdp.send('Browser.close'); } catch {} cdp.ws.close(); }
  if (edge) edge.kill(); if (server) server.kill();
});

const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const requests = [];
const passed = new Map();
const pass = (id, label) => passed.set(id, { id, label, status: 'passed' });
const outputDir = path.join(root, '.runtime', 'day08-final');
fs.mkdirSync(outputDir, { recursive: true });
let responseMode = 'success';
const clause = '联系电话：***。维修责任和费用均由租客承担。';
const markup = '<img src=x onerror="window.__xss=1">';
const pageHtml = fs.readFileSync(path.join(root, 'frontend-web/index.html'), 'utf8');
const server = http.createServer(async (req, res) => {
  if (['/vendor/vue-3.5.13.global.prod.js', '/vendor/tailwindcss-browser-4.1.13.js'].includes(req.url)) {
    res.setHeader('Content-Type', 'application/javascript');
    res.end(fs.readFileSync(path.join(root, 'frontend-web', req.url.slice(1))));
    return;
  }
  if (req.url === '/api/health') {
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ status: 'ok', env_configured: true }));
    return;
  }
  if (req.url === '/api/review/analyze-detailed') {
    let body = '';
    for await (const chunk of req) body += chunk;
    requests.push(JSON.parse(body));
    await pause(100);
    if (responseMode === 'http422') {
      res.writeHead(422, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ detail: [{ input: 'DO_NOT_DISPLAY_RAW_INPUT' }] }));
      return;
    }
    res.setHeader('Content-Type', 'application/json');
    if (responseMode === 'failure') {
      res.end(JSON.stringify({ status: 'needs_review', results: [], total_risks: 0, reason: '缺少本次审查所需配置。', failure_code: 'CHAT_NOT_CONFIGURED' }));
      return;
    }
    if (responseMode === 'badjson') { res.end('not json'); return; }
    res.end(JSON.stringify({
      status: 'success', total_risks: 2,
      results: [
        { clause_id: 'C-01', original_clause: clause, risk_level: 'HIGH', explanation: '合成风险解释，用于浏览器验证。', evidence_ids: ['LAW-709'], negotiation_tip: '合成建议：先核对维修事项，再明确费用安排。' },
        { clause_id: 'C-02', original_clause: '不在当前快照中的原句。', risk_level: 'LOW', explanation: '用于验证无法定位提示。', evidence_ids: [], negotiation_tip: '人工核对原文。' },
        { clause_id: 'C-03', original_clause: markup, risk_level: 'NONE', explanation: '验证输入内容以纯文本显示。', evidence_ids: [], negotiation_tip: '' },
      ],
    }));
    return;
  }
  if (req.url === '/favicon.ico') { res.writeHead(204); res.end(); return; }
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.end(pageHtml);
});
class CDP {
  constructor(ws) {
    this.ws = ws; this.nextId = 0; this.pending = new Map(); this.errors = []; this.network = []; this.external = [];
    ws.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result);
      }
      if (message.method === 'Runtime.exceptionThrown') this.errors.push(message.params.exceptionDetails);
      if (message.method === 'Network.requestWillBeSent') this.network.push(message.params.request.url);
      if (message.method === 'Fetch.requestPaused') {
        const { requestId, request } = message.params;
        if (request.url.startsWith(this.origin + '/')) this.send('Fetch.continueRequest', { requestId });
        else { this.external.push(request.url); this.send('Fetch.failRequest', { requestId, errorReason: 'InternetDisconnected' }); }
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
}
let edge;
let cdp;
async function until(expression, label) {
  for (let i = 0; i < 100; i++) {
    if (await cdp.evaluate(expression)) return;
    await pause(50);
  }
  throw new Error('Timed out: ' + label);
}
async function click(selector) {
  await cdp.evaluate('document.querySelector(' + JSON.stringify(selector) + ').click()');
  await pause(50);
}
async function fill(id, value) {
  await cdp.evaluate('(function(){const el=document.getElementById(' + JSON.stringify(id) + ');el.value=' + JSON.stringify(value) + ';el.dispatchEvent(new Event("input",{bubbles:true}));})()');
  await pause(40);
}
async function screenshot(name) {
  const result = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  fs.writeFileSync(path.join(outputDir, name + '.png'), Buffer.from(result.data, 'base64'));
}
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const profile = path.join(outputDir, 'edge-profile-' + Date.now());
  edge = spawn('C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe', [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-background-networking', '--disable-extensions', '--remote-debugging-port=0',
    '--user-data-dir=' + profile, 'about:blank',
  ], { windowsHide: true, stdio: 'ignore' });
  let debugPort;
  for (let i = 0; i < 150; i++) {
    try { debugPort = Number(fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0]); break; } catch {}
    await pause(100);
  }
  assert.ok(debugPort, 'Edge debugging endpoint starts');
  const target = await (await fetch('http://127.0.0.1:' + debugPort + '/json/new?about:blank', { method: 'PUT' })).json();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(resolve => ws.addEventListener('open', resolve, { once: true }));
  cdp = new CDP(ws);
  cdp.origin = 'http://127.0.0.1:' + port;
  await cdp.send('Runtime.enable');
  await cdp.send('Page.enable');
  await cdp.send('Network.enable');
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
  await cdp.send('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' }] });
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1080, deviceScaleFactor: 1, mobile: false });
  await cdp.send('Page.navigate', { url: 'http://127.0.0.1:' + port });
  await until('!!document.querySelector("#app") && !document.querySelector("#app").hasAttribute("v-cloak")', 'Vue mounts');
  await until('getComputedStyle(document.querySelector(".topbar > a")).display === "flex"', 'Tailwind loads');
  assert.deepEqual(await cdp.evaluate('[...document.querySelectorAll("script[src]")].map(s=>s.getAttribute("src")).sort()'), ['./vendor/tailwindcss-browser-4.1.13.js', './vendor/vue-3.5.13.global.prod.js']);
  assert.ok(cdp.network.some(url => url.endsWith('/vendor/vue-3.5.13.global.prod.js')));
  assert.ok(cdp.network.some(url => url.endsWith('/vendor/tailwindcss-browser-4.1.13.js')));
  pass(1, 'Cold-cache Vue and Tailwind load from local vendor; external requests blocked');
  assert.equal(await cdp.evaluate('document.querySelectorAll(".panel").length'), 3);
  assert.equal(await cdp.evaluate('getComputedStyle(document.querySelector(".board")).gridTemplateColumns.split(" ").length'), 3);
  pass(2, 'Desktop has three columns');
  await screenshot('day08-input-desktop');
  const tokens = ['13800000000', '13900000000', '110101199001010000', '11010119900101000X', '110101900101000'];
  const contract = '合成合同，仅供测试。\n联系电话：13800000000。身份证：110101199001010000、11010119900101000X、110101900101000。\n' +
    '国际格式手机号：+86 138-0000-0000。\n' +
    '普通合同条款，双方约定按时沟通维修事项。\n'.repeat(32) +
    '联系电话：13800000000。维修责任和费用均由租客承担。\n' +
    '其他条款内容。\n'.repeat(12) +
    '联系电话：13800000000。维修责任和费用均由租客承担。\n' + markup;
  await fill('contract-input', contract);
  await click('.btn-primary');
  await until('!!document.getElementById("preview-input")', 'preview opens');
  assert.equal(requests.length, 0, 'no analysis before confirmation');
  pass(3, 'Opening preview sends no analysis request');
  let preview = await cdp.evaluate('document.getElementById("preview-input").value');
  for (const token of tokens) assert.ok(!preview.includes(token));
  pass(5, '15-digit and 18-digit numeric / X-ended IDs are masked');
  assert.ok(!preview.includes('+86 138-0000-0000'));
  pass(4, '11-digit phones including +86 and hyphens are masked');
  assert.ok(await cdp.evaluate('document.querySelector(".btn-primary").disabled'));
  pass(6, 'Unconfirmed preview disables submission');
  await click('#privacy-confirm');
  await fill('preview-input', preview + '\n新增手机号：13900000000。');
  assert.equal(await cdp.evaluate('document.getElementById("privacy-confirm").checked'), false, 'editing revokes consent');
  pass(7, 'Editing preview immediately revokes confirmation');
  await click('#privacy-confirm');
  await click('.btn-primary');
  assert.equal(requests.length, 0, 'new sensitive text is redacted before any request');
  assert.equal(await cdp.evaluate('document.getElementById("privacy-confirm").checked'), false);
  preview = await cdp.evaluate('document.getElementById("preview-input").value');
  assert.ok(!preview.includes('13900000000'));
  pass(8, 'Final rescan masks newly entered phone and requires confirmation again');
  await screenshot('day08-preview-desktop');
  await click('#privacy-confirm');
  await cdp.evaluate('document.querySelector(".btn-primary").click(); document.querySelector(".btn-primary")?.click();');
  await until('document.querySelectorAll(".risk-card").length === 3', 'success cards');
  assert.equal(requests.length, 1, 'double click issues only one request');
  assert.equal(requests[0].contract_text, preview, 'request uses exactly confirmed preview');
  for (const token of tokens) assert.ok(!JSON.stringify(requests).includes(token));
  pass(9, 'Request exactly equals confirmed sanitized snapshot; raw markers absent');
  pass(10, 'Double click sends one analysis request');
  await cdp.evaluate('window.__scrolls=[];const native=Element.prototype.scrollIntoView;Element.prototype.scrollIntoView=function(options){window.__scrolls.push(options);return native.call(this,options)};');
  await click('.risk-select');
  await until('document.querySelectorAll("#submitted-document mark").length === 2', 'exact repeated clause highlights');
  await pause(650);
  assert.equal(await cdp.evaluate('document.querySelector("#submitted-document mark.current").textContent'), clause);
  assert.ok(await cdp.evaluate('document.querySelector(".panel-body").scrollTop > 0'), 'document scrolls to match');
  assert.equal(await cdp.evaluate('window.__scrolls.at(-1).behavior'), 'smooth');
  assert.ok(await cdp.evaluate('document.getElementById("role-panel").textContent.includes("合成建议")'));
  pass(14, 'Risk selection synchronizes negotiation advice');
  await screenshot('day08-highlight-desktop');
  await click('[aria-label="下一处原句"]');
  assert.equal(await cdp.evaluate('document.querySelector("#submitted-document mark.current").id'), 'clause-hit-1');
  pass(11, 'Exact repeated clauses highlight with occurrence navigation');
  pass(12, 'Selection calls smooth scrollIntoView and scrolls the left panel');
  await click('[aria-label="定位条款 C-02"]');
  assert.equal(await cdp.evaluate('document.querySelectorAll("#submitted-document mark").length'), 0);
  assert.ok(await cdp.evaluate('document.querySelector(".panel-body").textContent.includes("未找到可精确匹配")'));
  pass(13, 'Unmatched original clause shows notice with no guessed highlight');
  await click('[aria-label="定位条款 C-03"]');
  assert.equal(await cdp.evaluate('document.querySelectorAll("#submitted-document img").length'), 0, 'markup stays plain text');
  assert.equal(await cdp.evaluate('window.__xss === undefined'), true);
  pass(15, 'Injected HTML remains text; synthetic event handler does not execute');
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await pause(300);
  assert.equal(await cdp.evaluate('getComputedStyle(document.querySelector(".board")).gridTemplateColumns.split(" ").length'), 1);
  assert.ok(await cdp.evaluate('document.documentElement.scrollWidth <= 390'), 'no mobile horizontal overflow');
  pass(16, '390px mobile layout has one column and no horizontal overflow');
  await screenshot('day08-mobile');
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1080, deviceScaleFactor: 1, mobile: false });
  for (const mode of ['failure', 'http422', 'badjson']) {
    responseMode = mode;
    await click('.panel:first-child .text-btn');
    await fill('contract-input', '合成合同条款，双方约定按月支付租金。');
    await click('.btn-primary');
    await click('#privacy-confirm');
    await click('.btn-primary');
    await until('document.querySelector(".panel:nth-child(2)").textContent.includes("本次审查未完成")', mode + ' handled');
    assert.equal(await cdp.evaluate('document.querySelectorAll(".risk-card").length'), 0);
    assert.ok(await cdp.evaluate('!document.body.textContent.includes("DO_NOT_DISPLAY_RAW_INPUT")'));
    assert.ok(await cdp.evaluate('document.querySelector(".panel:nth-child(2)").textContent.includes("不能据此判定合同无风险")'));
  }
  pass(17, 'needs_review, HTTP 422, and invalid JSON show failure without stale results or raw input');
  await click('.panel:nth-child(2) .btn');
  assert.ok(await cdp.evaluate('document.querySelector(".btn-primary").disabled'), 'retry requires confirmation again');
  pass(18, 'Retry returns to preview and requires confirmation');
  assert.equal(cdp.errors.length, 0, JSON.stringify(cdp.errors));
  assert.equal(cdp.external.length, 0, 'page must not even attempt external requests');
  assert.equal(passed.size, 18);
  const report = {
    mode: 'headless_edge_local_mock_api_external_network_blocked_cold_cache',
    node: process.version,
    browser: (await cdp.send('Browser.getVersion')).product,
    passed: passed.size, failed: 0, skipped: 0,
    externalRequests: cdp.external.length,
    runtimeExceptions: cdp.errors.length,
    realCloudCalls: 0,
    cases: [...passed.values()].sort((a,b)=>a.id-b.id),
  };
  fs.writeFileSync(path.join(outputDir, 'browser-results.json'), JSON.stringify(report, null, 2) + '\n');
  for (const item of report.cases) console.log('PASS ' + String(item.id).padStart(2, '0') + ': ' + item.label);
  console.log('18 passed, 0 failed, 0 skipped; external requests: 0; real cloud calls: 0.');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (cdp) { try { await cdp.send('Browser.close'); } catch {} cdp.ws.close(); }
  if (edge) edge.kill();
  server.closeAllConnections();
  server.close();
});

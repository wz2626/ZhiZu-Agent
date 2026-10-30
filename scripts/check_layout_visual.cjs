// V2/V3 task-screen visual/space acceptance. Dense review findings are explicit
// visual fixtures; V3 evidence/proposals also use the real local services with
// explicit offline model/retrieval doubles. Negotiation runs its real graph.
// Screenshots support human review; a green JSON is not an aesthetic verdict.
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
const { prepareEvidence } = require('./browser_evidence.cjs');
const root = path.resolve(__dirname, '..');
const { output, runtime } = prepareEvidence(root);
const canonicalLaw712 = JSON.parse(fs.readFileSync(path.join(root, 'backend/data/laws/civil_code_lease_703_734.json'), 'utf8')).find(law => law.law_id === 'LAW-712');
assert.ok(canonicalLaw712, 'LAW-712 exists in the authoritative local corpus');
const law712Evidence = Object.fromEntries(['article_no', 'law_name', 'content', 'source_url', 'verified_date'].map(key => [key, canonicalLaw712[key]]));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const cases = [], measurements = [], screenshots = [];
const clauses = [
  '租赁结束后可不说明理由直接扣留全部押金。',
  '维修责任和费用均由租客承担。',
  '提前退租须支付固定违约金2000元。',
];
const shortContract = '房屋租赁合同（合成视觉样本）\n\n' + clauses.map((text, i) => `第${i + 1}条 ${text}`).join('\n\n');
const paragraph = '双方应当保存租金支付和房屋交接记录，并就维修事项及时沟通。';
const longContract = '房屋租赁合同（长篇合成视觉样本）\n\n' + [
  ...Array.from({ length: 16 }, (_, i) => `第${i + 1}条 ${paragraph}`), clauses[0],
  ...Array.from({ length: 16 }, (_, i) => `第${i + 18}条 ${paragraph}`), clauses[1],
  ...Array.from({ length: 16 }, (_, i) => `第${i + 35}条 ${paragraph}`), clauses[2],
].join('\n\n');
const explanation = '这是离线视觉样本，用于检查较长说明的换行、批注密度和详情阅读。应结合费用凭证、交接记录及完整合同核对相关事实，明确责任范围、具体金额、处理时限和沟通安排。';
let server, edge, cdp, origin, stderr = '', reviewProfile = 'dense', useRealReview = false;
const negotiationResponses = [], proposalResponses = [];
function pass(label) { cases.push({ id: cases.length + 1, label, status: 'passed' }); console.log('PASS ' + label); }
function reviewFixture() {
  const count = reviewProfile === 'dense' ? 6 : 3;
  const results = Array.from({ length: count }, (_, i) => ({
    clause_id: 'C-' + String(i + 1).padStart(2, '0'), original_clause: clauses[i % 3],
    risk_level: i % 2 ? 'MEDIUM' : 'HIGH',
    explanation: reviewProfile === 'dense' ? explanation.repeat(2) : explanation,
    evidence_ids: ['LAW-712'], negotiation_tip: '先核对费用凭证和事实记录，再要求对方明确金额、责任和处理日期。',
  }));
  if (reviewProfile === 'dense') results.push({ clause_id: 'C-07', original_clause: '该句不在当前合成快照中。', risk_level: 'LOW', explanation, evidence_ids: [], negotiation_tip: '请人工核对原文。' });
  // No fabricated trace nodes or model timings are added to this visual double.
  return { status: 'success', results, total_risks: results.length, retry_count: 0, trace: [], trace_label: '本次执行回放', errors: [],
    evidence_by_id: { 'LAW-712': law712Evidence }, review_context_id: null };
}
class CDP {
  constructor(ws) {
    this.ws = ws; this.counter = 0; this.pending = new Map(); this.errors = []; this.external = [];
    ws.addEventListener('message', event => {
      const m = JSON.parse(event.data);
      if (m.id && this.pending.has(m.id)) { const p = this.pending.get(m.id); this.pending.delete(m.id); m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result); }
      if (m.method === 'Runtime.exceptionThrown') this.errors.push(m.params.exceptionDetails);
      if (m.method === 'Fetch.requestPaused') this.intercept(m.params).catch(error => this.errors.push(String(error)));
    });
  }
  async intercept({ requestId, request, responseStatusCode }) {
    if (!request.url.startsWith(origin + '/')) { this.external.push(request.url); return this.send('Fetch.failRequest', { requestId, errorReason: 'InternetDisconnected' }); }
    if (responseStatusCode !== undefined) {
      const response = await this.send('Fetch.getResponseBody', { requestId });
      const text = response.base64Encoded ? Buffer.from(response.body, 'base64').toString() : response.body;
      (request.url.endsWith('/api/review/proposal') ? proposalResponses : negotiationResponses).push(JSON.parse(text));
      return this.send('Fetch.continueRequest', { requestId });
    }
    if (!useRealReview && request.method === 'POST' && request.url.endsWith('/api/review/analyze-detailed')) {
      await pause(1400); // Intentional local latency, so waiting UI can be captured.
      return this.send('Fetch.fulfillRequest', { requestId, responseCode: 200,
        responseHeaders: [{ name: 'Content-Type', value: 'application/json' }], body: Buffer.from(JSON.stringify(reviewFixture())).toString('base64') });
    }
    return this.send('Fetch.continueRequest', { requestId });
  }
  send(method, params = {}) {
    const id = ++this.counter;
    return new Promise((resolve, reject) => { this.pending.set(id, { resolve, reject }); this.ws.send(JSON.stringify({ id, method, params })); });
  }
  async evaluate(expression) {
    const r = await this.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
    return r.result.value;
  }
}
async function until(expression, label) {
  for (let i = 0; i < 200; i++) { if (await cdp.evaluate(expression)) return; await pause(50); }
  throw new Error('Timed out: ' + label);
}
async function click(selector) { await cdp.evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`); await pause(50); }
async function fill(id, value, type = 'input') {
  await cdp.evaluate(`(()=>{const e=document.getElementById(${JSON.stringify(id)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event(${JSON.stringify(type)},{bubbles:true}))})()`); await pause(40);
}
async function viewport(width, height, mobile = false) {
  await cdp.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile });
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: mobile });
  await pause(350);
}
async function shot(name, full = false) {
  await pause(350);
  const r = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: full });
  const filename = name + '.png'; fs.writeFileSync(path.join(output, filename), Buffer.from(r.data, 'base64'));
  screenshots.push({ filename, fullPage: full });
}
async function contactSheet() {
  const cards = screenshots.map(({ filename }) => `<figure><figcaption>${filename}</figcaption><img src="data:image/png;base64,${fs.readFileSync(path.join(output, filename)).toString('base64')}"></figure>`).join('');
  await cdp.send('Page.navigate', { url: 'about:blank' }); await pause(150);
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
  const frame = (await cdp.send('Page.getFrameTree')).frameTree.frame.id;
  await cdp.send('Page.setDocumentContent', { frameId: frame, html: '<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0;padding:24px;background:#10151d;color:#e6edf6;font:16px Segoe UI,sans-serif}h1{font-size:24px;margin:0 0 20px}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}figure{margin:0;padding:12px;border:1px solid #35465d;background:#17202d;border-radius:8px}figcaption{font-size:13px;margin-bottom:8px}img{display:block;width:100%;height:255px;object-fit:contain;background:#0b111b}</style></head><body><h1>Task-screen visual evidence · actual viewport captures</h1><div class="grid">' + cards + '</div></body></html>' });
  await cdp.evaluate('Promise.all([...document.images].map(image=>image.decode()))');
  const image = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  fs.writeFileSync(path.join(output, 'contact-sheet.png'), Buffer.from(image.data, 'base64'));
}
async function geometry(label) {
  const r = await cdp.evaluate(`(()=>{
    const rect=id=>{const e=document.querySelector(id);if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom,visible:!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden'}};
    return {label:${JSON.stringify(label)},viewport:{width:innerWidth,height:innerHeight},zoom:getComputedStyle(document.body).zoom,screen:document.getElementById('app').dataset.screen,documentHeight:document.documentElement.scrollHeight,overflow:document.documentElement.scrollWidth>innerWidth+1,dossier:rect('#dossier'),workspace:rect('#workspace'),primary:rect('#dossier .btn-primary'),negotiation:rect('#negotiation-panel'),composer:rect('#negotiation-composer'),trace:rect('#trace-console')};})()`);
  measurements.push(r); assert.equal(r.overflow, false, label + ': no horizontal overflow'); return r;
}
async function reachable(selector) {
  if (await cdp.evaluate('document.getElementById("trace-toggle").getAttribute("aria-expanded")==="true"')) await click('#trace-toggle');
  await cdp.evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center',inline:'nearest',behavior:'instant'})`); await pause(160);
  const r = await cdp.evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)}),r=e.getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return {top:r.top,bottom:r.bottom,width:r.width,height:r.height,viewport:innerHeight,hit:hit===e||e.contains(hit)}})()`);
  assert.ok(r.width > 0 && r.height > 0 && r.top >= -1 && r.bottom <= r.viewport + 1 && r.hit, selector + ': visible and unobstructed ' + JSON.stringify(r));
}
(async () => {
  server = spawn(path.join(root, '.venv/Scripts/python.exe'), ['-u', 'scripts/day10_offline_app.py'], { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  server.stderr.on('data', data => { stderr += data; });
  origin = await new Promise((resolve, reject) => { let buffer = ''; const timer = setTimeout(() => reject(new Error('Local server startup: ' + stderr)), 20000);
    server.stdout.on('data', data => { buffer += data; const m = buffer.match(/READY (\d+)/); if (m) { clearTimeout(timer); resolve('http://127.0.0.1:' + m[1]); } });
    server.once('exit', code => { clearTimeout(timer); reject(new Error('Server exited ' + code + ': ' + stderr)); }); });
  const profile = path.join(runtime, 'edge-profile');
  edge = spawn('C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe', ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-extensions', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'], { windowsHide: true, stdio: 'ignore' });
  let port; for (let i = 0; i < 150; i++) { try { port = Number(fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0]); break; } catch {} await pause(100); }
  assert.ok(port, 'Edge starts');
  const target = await (await fetch('http://127.0.0.1:' + port + '/json/new?about:blank', { method: 'PUT' })).json();
  const ws = new WebSocket(target.webSocketDebuggerUrl); await new Promise(resolve => ws.addEventListener('open', resolve, { once: true })); cdp = new CDP(ws);
  await cdp.send('Runtime.enable'); await cdp.send('Page.enable'); await cdp.send('Network.enable'); await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
  await cdp.send('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' }, { urlPattern: '*/api/negotiation/turn', requestStage: 'Response' }, { urlPattern: '*/api/review/proposal', requestStage: 'Response' }] });

  await viewport(1440,900);await cdp.send('Page.navigate',{url:origin});
  await until('!!window.__zhizuLayoutDiagnostics?.length','workspace');
  await geometry('input');await reachable('#analyze-contract');await cdp.evaluate('scrollTo(0,0)');await shot('01-input');
  await viewport(1920,1080);await shot('02-input-wide');
  async function analyze(text){await click('#edit-contract');await fill('contract-input',text);await click('#analyze-contract');await until('document.getElementById("submitted-document").textContent==='+JSON.stringify(text)+' && document.querySelectorAll("#risk-navigation [data-clause]").length>0','analysis');}
  await fill('contract-input',shortContract);await click('#analyze-contract');
  await until('!!document.querySelector(".analysis-wait")','waiting decoration mounted');
  assert.ok(await cdp.evaluate('document.querySelector(".skeleton-bar").getAnimations().some(a=>a.playState==="running")'));
  assert.equal(await cdp.evaluate('getComputedStyle(document.querySelector(".dossier-body"),"::after").pointerEvents'),'none');
  await shot('02a-analysis-wait');
  await cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  assert.equal(await cdp.evaluate('getComputedStyle(document.querySelector(".skeleton-bar")).animationName'),'none');
  await cdp.send('Emulation.setEmulatedMedia',{features:[]});
  await until('!document.querySelector(".analysis-wait") && document.querySelectorAll("#risk-navigation [data-clause]").length>0','waiting ends');
  pass('Real waiting state runs decorative animation; reduced motion stops it; completion removes it without blocking text');
  await click('[data-clause="C-01"]');await geometry('short');await shot('03-short');
  await click('#task-panel .task-explanation details:last-child > summary');await shot('04-evidence');
  await analyze(longContract);await click('[data-clause="C-02"]');await geometry('long-selected');await shot('05-long-selected');
  assert.ok(await cdp.evaluate('(()=>{const r=document.getElementById("prepare-communication").getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight})()'),'Long-contract selection keeps its contextual action in view');
  assert.equal(await cdp.evaluate('document.getElementById("submitted-document").textContent'),longContract);
  pass('Short and long contracts retain exact full text with stable navigation and contextual evidence');
  await click('#prepare-communication');await fill('scenario-select','maintenance','change');await fill('negotiation-draft','请核对维修费用并明确责任。');await click('#message-privacy-confirm');await click('#send-negotiation');await until('document.getElementById("round-count").dataset.round==="1"','round');await shot('06-result');
  await cdp.evaluate('[...document.querySelectorAll(".task-tabs button")].find(b=>b.textContent==="写沟通消息").click()');
  for(const [w,h,z] of [[1440,900,1],[1280,560,1],[1440,900,1.25],[1440,900,1.5],[1440,900,2],[390,844,1]]){
    await viewport(w,h,w===390);await cdp.evaluate('document.body.style.zoom='+JSON.stringify(String(z)));await geometry('communication-'+w+'-'+h+'-'+z);await reachable('#send-negotiation');await shot('communication-'+w+'-'+h+'-'+z);
  }
  pass('Send remains accessible without overlapping fixed surfaces at all six viewport/reflow sizes');
  await viewport(1440,900);await cdp.evaluate('document.body.style.zoom="1"');useRealReview=true;
  await analyze(shortContract);await click('[data-clause="C-02"]');await click('#prepare-communication');await fill('scenario-select','maintenance','change');await click('#proposal-tool > summary');await fill('proposal-goal','希望明确维修责任、费用凭证和完成时间。');await click('#proposal-privacy-confirm');await click('#generate-proposal');await until('!!document.getElementById("proposed-message")','real proposal');await reachable('#generate-proposal');await shot('13-draft');
  await click('#supplement-goal');assert.equal(await cdp.evaluate('document.activeElement.id'),'proposal-goal');
  const reference=await cdp.evaluate('document.getElementById("proposed-message").textContent');
  await fill('proposal-goal','希望补充处理日期。');
  assert.equal(await cdp.evaluate('document.getElementById("proposed-message").textContent'),reference);
  assert.ok(await cdp.evaluate('document.querySelector(".supplement-help").textContent.includes("无需编造")'));
  await shot('14-reference-retained');await reachable('#send-negotiation');
  pass('Real offline draft generation and retained reference remain accessible within the same task');
  assert.equal(cdp.errors.length,0,JSON.stringify(cdp.errors));assert.equal(cdp.external.length,0);
  fs.writeFileSync(path.join(output,'visual-results.json'),JSON.stringify({passed:cases.length,failed:0,skipped:0,cases,measurements,screenshots},null,2));await contactSheet();
})().catch(async error => {
  console.error(error); console.error(stderr); process.exitCode = 1;
  if (cdp) { try { await shot('failure-current-viewport'); fs.writeFileSync(path.join(output, 'failure.json'), JSON.stringify({ error: String(error), measurements, screenshots, runtimeErrors: cdp.errors }, null, 2)); } catch {} }
}).finally(async () => {
  if (cdp) { try { await cdp.send('Browser.close'); } catch {} cdp.ws.close(); }
  if (edge) edge.kill(); if (server) server.kill();
});

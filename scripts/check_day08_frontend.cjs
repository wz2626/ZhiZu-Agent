const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { spawn, execFileSync } = require('node:child_process');
const assert = require('node:assert/strict');
const { prepareEvidence } = require('./browser_evidence.cjs');
const root = path.resolve(__dirname, '..');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const requests = [];
let discoveryRequests = 0;
const passed = new Map();
const pass = (id, label) => passed.set(id, { id, label, status: 'passed' });
const { output: outputDir, runtime } = prepareEvidence(root);
let responseMode = 'success';
const clause = '联系电话：***。维修责任和费用均由租客承担。';
const markup = '<img src=x onerror="window.__xss=1">';
const pageHtml = fs.readFileSync(path.join(root, 'frontend-web/index.html'), 'utf8');
const law709 = JSON.parse(fs.readFileSync(path.join(root, 'backend/data/laws/civil_code_lease_703_734.json'), 'utf8')).find(law => law.law_id === 'LAW-709');
const fixturePolicy=JSON.parse(execFileSync(path.join(root,'.venv/Scripts/python.exe'),['-c','import json;from backend.app.core.privacy import privacy_policy;print(json.dumps(privacy_policy()))'],{cwd:root,windowsHide:true,encoding:'utf8'}));
const server = http.createServer(async (req, res) => {
  // Deliberately no OpenAPI fixture: exercise discovery-unavailable recovery.
  if (req.url === '/openapi.json') { discoveryRequests++; await pause(60); }
  if (['/vendor/vue-3.5.13.global.prod.js', '/vendor/tailwindcss-browser-4.1.13.js'].includes(req.url)) {
    res.setHeader('Content-Type', 'application/javascript');
    res.end(fs.readFileSync(path.join(root, 'frontend-web', req.url.slice(1))));
    return;
  }
  if(req.url==='/api/negotiation/meta'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({interaction_version:4,practice_epoch:'b'.repeat(32),privacy_policy_version:fixturePolicy.version,privacy_policy:fixturePolicy,mode:'fixed_offline',max_rounds:5,scenarios:{}}));return;}
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
    if (responseMode === 'badjson') { res.end('DO_NOT_DISPLAY_RAW_INPUT not json'); return; }
    if (responseMode === 'directions') {
      const quotes=JSON.parse(body).contract_text.split('\n').slice(1);
      res.end(JSON.stringify({status:'success',total_risks:quotes.length,review_context_id:'d'.repeat(32),evidence_by_id:{},results:quotes.map((quote,i)=>({clause_id:'C-0'+(i+1),original_clause:quote,risk_level:'MEDIUM',explanation:'合成沟通方向验收，不是法律结论。',evidence_ids:[],negotiation_tip:'请核对具体事实与约定。'}))}));return;
    }
    if (responseMode === 'overlap') {
      res.end(JSON.stringify({status:'success',total_risks:2,results:[
        {clause_id:'C-01',original_clause:'维修责任由房东承担。\n费用由双方确认。',risk_level:'HIGH',explanation:'跨段原句定位测试。',evidence_ids:['LAW-712'],negotiation_tip:'核对两段约定。'},
        {clause_id:'C-02',original_clause:'房东承担。',risk_level:'LOW',explanation:'嵌套区间定位测试。',evidence_ids:[],negotiation_tip:'核对责任主体。'},
        {clause_id:'C-03',original_clause:'哈哈哈',risk_level:'NONE',explanation:'自重叠原句定位测试。',evidence_ids:[],negotiation_tip:''},
      ]}));return;
    }
    res.end(JSON.stringify({
      status: 'success', total_risks: 2,
      evidence_by_id: { 'LAW-709': law709 },
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
async function fill(id, value, type='input') {
  await cdp.evaluate('(function(){const el=document.getElementById(' + JSON.stringify(id) + ');el.value=' + JSON.stringify(value) + ';el.dispatchEvent(new Event('+JSON.stringify(type)+',{bubbles:true}));})()');
  await pause(40);
}
async function screenshot(name) {
  await pause(350); // Allow layout and finite local feedback to settle.
  const result = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  fs.writeFileSync(path.join(outputDir, name + '.png'), Buffer.from(result.data, 'base64'));
}
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const profile = path.join(runtime, 'edge-profile-' + Date.now());
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
  await until('!!window.__zhizuLayoutDiagnostics?.length','workspace mounted');
  await require('./check_workspace.cjs')({cdp,click,fill,until,pause,assert,
    real:false,requests,pass:label=>{pass(passed.size+1,label);console.log(label)},mode:async value=>{responseMode=value},shot:screenshot});
  assert.equal(cdp.errors.length,0,JSON.stringify(cdp.errors));assert.equal(cdp.external.length,0);
  fs.writeFileSync(path.join(outputDir,'browser-results.json'),JSON.stringify({passed:passed.size,failed:0,skipped:0,cases:[...passed.values()],external:cdp.external.length},null,2));
  console.log('Workspace checks passed: '+passed.size);
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (cdp) { try { await cdp.send('Browser.close'); } catch {} cdp.ws.close(); }
  if (edge) edge.kill();
  server.closeAllConnections();
  server.close();
});

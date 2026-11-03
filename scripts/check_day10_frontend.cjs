// Day 9 supplemental checks + Day 10 real local HTTP/graph end-to-end checks.
// Review uses explicitly labelled doubles; all Trace timings come from graphs.
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
const { prepareEvidence } = require('./browser_evidence.cjs');
const root = path.resolve(__dirname, '..');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const { output, runtime } = prepareEvidence(root);
const out10 = path.join(output, 'day10');
const out09 = path.join(output, 'day09-supplement');
for (const dir of [out10, out09]) fs.mkdirSync(dir);
const cases = [], day9 = [], traces = [], requests = [];
const layoutEvidence = [];
let interactionEvidence = [];
let microPolishEvidence = [];
const pass = (label, supplemental = false) => {
  const entry = { id: cases.length + 1, label, status: 'passed' };
  cases.push(entry); if (supplemental) day9.push(entry);
  console.log('PASS ' + entry.id + ': ' + label);
};
let server, edge, cdp, origin, stderr = '';
class CDP {
  constructor(ws) {
    this.ws = ws; this.nextId = 0; this.pending = new Map(); this.errors = []; this.external = [];
    this.dropNext = false; this.invalidTraceNext = false; this.dropNextProposal = false;
    this.invalidEffectNext = false; this.quotaNextProposal = false;
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
      if (this.holdReviewNext && request.url.endsWith('/api/review/analyze-detailed')) {
        this.holdReviewNext = false;
        await new Promise(resolve => { this.releaseReview = resolve; });
      }
      const body = await this.send('Fetch.getResponseBody', { requestId });
      const text = body.base64Encoded ? Buffer.from(body.body, 'base64').toString() : body.body;
      const data = JSON.parse(text);
      // Preserve the actual server response before any intentional transport
      // or malformed-response injection changes the browser-facing copy.
      traces.push({ path: new URL(request.url).pathname, data: structuredClone(data) });
      if(this.emptyProposalQuestionsNext && request.url.endsWith('/api/review/proposal')){
        this.emptyProposalQuestionsNext=false;data.questions=[];data.question_items=[];
        return this.send('Fetch.fulfillRequest',{requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:'application/json'}],body:Buffer.from(JSON.stringify(data)).toString('base64')});
      }
      if (this.dropNext && request.url.endsWith('/api/negotiation/turn')) {
        this.dropNext = false;
        return this.send('Fetch.failRequest', { requestId, errorReason: 'ConnectionClosed' });
      }
      if (this.dropNextProposal && request.url.endsWith('/api/review/proposal')) {
        this.dropNextProposal = false;
        return this.send('Fetch.failRequest', { requestId, errorReason: 'ConnectionClosed' });
      }
      if (this.invalidTraceNext && request.url.endsWith('/api/negotiation/turn')) {
        this.invalidTraceNext = false;
        data.trace[0].sequence = 2; // Explicit malformed-response injection.
        return this.send('Fetch.fulfillRequest', { requestId, responseCode: 200,
          responseHeaders: [{ name: 'Content-Type', value: 'application/json' }],
          body: Buffer.from(JSON.stringify(data)).toString('base64') });
      }
      if (this.invalidEffectNext && request.url.endsWith('/api/negotiation/turn')) {
        this.invalidEffectNext = false;
        data.turn_effect.score_before = -1; // Impossible canonical baseline, even on unchanged rounds.
        return this.send('Fetch.fulfillRequest', { requestId, responseCode:200,
          responseHeaders:[{name:'Content-Type',value:'application/json'}],
          body:Buffer.from(JSON.stringify(data)).toString('base64') });
      }
      if(this.invalidTermsNext&&request.url.endsWith('/api/negotiation/turn')){
        this.invalidTermsNext=false;
        const term=Object.keys(data.confirmed_terms)[0];data.confirmed_terms[term]=50000;
        data.turn_effect.changes.forEach(change=>{if(change.term===term)change.after=50000;});
        return this.send('Fetch.fulfillRequest',{requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:'application/json'}],body:Buffer.from(JSON.stringify(data)).toString('base64')});
      }
      return this.send('Fetch.continueRequest', { requestId });
    }
    if (request.method === 'POST' && request.url.includes('/api/')) requests.push({ path: new URL(request.url).pathname, ...JSON.parse(request.postData) });
    if (this.quotaNextProposal && request.url.endsWith('/api/review/proposal')) {
      this.quotaNextProposal = false;
      return this.send('Fetch.fulfillRequest',{requestId,responseCode:429,
        responseHeaders:[{name:'Content-Type',value:'application/json'}],
        body:Buffer.from(JSON.stringify({detail:'当前审查的草稿请求已达上限，请重新分析合同。'})).toString('base64')});
    }
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
async function shot(dir,name,fullPage=true){const r=await cdp.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:fullPage});fs.writeFileSync(path.join(dir,name+'.png'),Buffer.from(r.data,'base64'));}
async function setMode(value){await fetch(origin+'/_test/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({value})});}
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
    { urlPattern: '*/api/negotiation/turn', requestStage: 'Response' }, { urlPattern: '*/api/review/analyze-detailed', requestStage: 'Response' },
    { urlPattern: '*/api/review/proposal', requestStage: 'Response' }] });
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1080, deviceScaleFactor: 1, mobile: false });
  await cdp.send('Page.navigate', { url: origin });
  await until('!!window.__zhizuLayoutDiagnostics?.length','workspace mounted');
  await require('./check_workspace.cjs')({cdp,click,fill,until,pause,assert,
    real:true,requests,responses:traces,pass:pass,mode:setMode,shot:(name,fullPage=true)=>shot(out10,name,fullPage)});
  assert.equal(cdp.errors.length,0,JSON.stringify(cdp.errors));assert.equal(cdp.external.length,0);
  fs.writeFileSync(path.join(out10,'browser-results.json'),JSON.stringify({passed:cases.length,failed:0,skipped:0,cases:cases,external:cdp.external.length,proposalReadiness:cdp.proposalReadinessEvidence||[]},null,2));
  console.log('Workspace checks passed: '+cases.length);
})().catch(async error => {
  console.error(error); console.error(stderr); process.exitCode = 1;
  fs.writeFileSync(path.join(out10,'failure.json'),JSON.stringify({error:String(error),cases,layoutEvidence,stderr,browserErrors:cdp?.errors,lastResponses:traces.slice(-3),lastRequests:requests.slice(-3)},null,2));
  if(cdp){try{await shot(out10,'failure-current-viewport');}catch{}}
}).finally(async () => {
  if (cdp) { try { await cdp.send('Browser.close'); } catch {} cdp.ws.close(); }
  if (edge) edge.kill(); if (server) server.kill();
});

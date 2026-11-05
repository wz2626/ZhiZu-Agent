// Spec 07 browser acceptance. Explicit HTTP doubles, no cloud/model requests.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {spawn,execFileSync}=require('node:child_process');
const {prepareEvidence}=require('./browser_evidence.cjs');
const root=path.resolve(__dirname,'..'),{output,runtime}=prepareEvidence(root);
const pause=ms=>new Promise(r=>setTimeout(r,ms)),cases=[],requests=[],paths=[];
const pass=label=>{cases.push(label);console.log('PASS '+label)};
const policy=JSON.parse(execFileSync(path.join(root,'.venv/Scripts/python.exe'),['-c','import json;from backend.app.core.privacy import privacy_policy;print(json.dumps(privacy_policy()))'],{cwd:root,windowsHide:true,encoding:'utf8'}));
let mode='success',delay=70,edge,cdp,origin;
function card(body){if(mode==='out_of_scope')return {schema_version:'quote-v1',request_id:body.request_id,status:'out_of_scope',card:null};return {schema_version:'quote-v1',request_id:body.request_id,status:mode==='needs_context'?'needs_context':'success',card:{
 breakdown:{landlord_position:'对方要求核对费用。',assessment:['needs_context','bad_state'].includes(mode)?'unclear':'supported',analysis:'请先核对费用项目、事实和凭证。',tactics:[]},
 grounds:[{source_id:'C-001',kind:'contract',title:'合同第1段',original_text:body.contract_text.split('\n')[0],application:'需结合实际约定核实。',source_url:null}],
 replies:Object.fromEntries(['tactful','reasoned','firm'].map((tone,i)=>[tone,{text:['我们先核对费用和凭证，再协商处理，可以吗？','请说明费用项目和原因，我们再按照约定逐项核对。','请明确费用及依据，相关沟通记录我会保留，再协商处理。'][i],best_for:'核对相关事项时',source_ids:['C-001']}])),
 clarification_questions:mode==='needs_context'?['费用明细和凭证是什么？']:[]}};}
const server=http.createServer(async(req,res)=>{
 paths.push(req.url);res.setHeader('Content-Type','application/json; charset=utf-8');
 if(req.url==='/api/health'){res.end(JSON.stringify({status:'ok',env_configured:true}));return;}
 if(req.url==='/api/negotiation/quote-meta'){res.end(JSON.stringify({schema_version:'quote-v1',privacy_policy:policy,limits:{contract_text:5000,landlord_quote:2000,user_goal:300,context_note:1000}}));return;}
 if(req.url==='/api/negotiation/analyze-quote'){
  let raw='';for await(const chunk of req)raw+=chunk;const body=JSON.parse(raw);requests.push(body);const selected=mode;
  // Freeze each fixture at acceptance, just as the service freezes inputs.
  const result=card(body);await pause(delay);
  if(['failure','unsafe'].includes(selected)){res.statusCode=502;res.end(JSON.stringify({detail:{code:selected==='unsafe'?'MODEL_OUTPUT_UNSAFE':'MODEL_OUTPUT_INVALID',message:'DO_NOT_DISPLAY_UPSTREAM'}}));return;}
  if(selected==='privacy'){res.statusCode=428;res.end(JSON.stringify({detail:{code:'PRIVACY_PREVIEW_REQUIRED',privacy_policy_version:policy.version,fields:[{field:'landlord_quote',safe_text:body.landlord_quote+'（服务端安全预览）'}]}}));return;}
  res.end(JSON.stringify(result));return;
 }
 if(req.url==='/api/review/analyze-detailed'){
  let raw='';for await(const chunk of req)raw+=chunk;const body=JSON.parse(raw);
  res.end(JSON.stringify({status:'success',results:[{clause_id:'C-01',original_clause:body.contract_text.split('\n')[0],risk_level:'LOW',explanation:'合成审查结果，仅测试原文与版本行为。',evidence_ids:[],negotiation_tip:'核对具体事实。'}],total_risks:1,evidence_by_id:{}}));return;
 }
 if(req.url.startsWith('/vendor/')){res.setHeader('Content-Type','application/javascript');res.end(fs.readFileSync(path.join(root,'frontend-web',req.url.slice(1))));return;}
 if(req.url==='/favicon.ico'){res.statusCode=204;res.end();return;}
 res.setHeader('Content-Type','text/html; charset=utf-8');res.end(fs.readFileSync(path.join(root,'frontend-web/index.html')));
});
class CDP{
 constructor(ws){this.ws=ws;this.id=0;this.pending=new Map();this.errors=[];this.external=[];
  ws.addEventListener('message',event=>{const m=JSON.parse(event.data);if(m.id&&this.pending.has(m.id)){const p=this.pending.get(m.id);this.pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}
   if(m.method==='Runtime.exceptionThrown')this.errors.push(m.params.exceptionDetails);
   if(m.method==='Fetch.requestPaused'){const {requestId,request}=m.params;if(request.url.startsWith(origin+'/'))void this.send('Fetch.continueRequest',{requestId});else{this.external.push(request.url);void this.send('Fetch.failRequest',{requestId,errorReason:'BlockedByClient'});}}
  });}
 send(method,params={}){const id=++this.id;return new Promise((resolve,reject)=>{this.pending.set(id,{resolve,reject});this.ws.send(JSON.stringify({id,method,params}));});}
 async evaluate(expression){const r=await this.send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
}
const ev=s=>cdp.evaluate(s);
async function until(expression,label){for(let i=0;i<160;i++){if(await ev(expression))return;await pause(50);}throw Error('Timed out '+label);}
async function click(selector){await ev('document.querySelector('+JSON.stringify(selector)+').click()');await pause(40);}
async function fill(id,value){await ev(`(()=>{const e=document.getElementById(${JSON.stringify(id)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));})()`);await pause(30);}
async function shot(name){await pause(150);const r=await cdp.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(output,name+'.png'),Buffer.from(r.data,'base64'));}
async function complete(){await until('!document.getElementById("analyze-quote").textContent.includes("正在")','request completes');}
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));origin='http://127.0.0.1:'+server.address().port;
 const profile=path.join(runtime,'edge-profile');edge=spawn('C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-extensions','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{windowsHide:true,stdio:'ignore'});
 let port;for(let i=0;i<150;i++){try{port=Number(fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0]);break;}catch{}await pause(100);}assert.ok(port);
 const target=await(await fetch('http://127.0.0.1:'+port+'/json/new?about:blank',{method:'PUT'})).json();const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));cdp=new CDP(ws);
 await cdp.send('Runtime.enable');await cdp.send('Page.enable');await cdp.send('Network.enable');await cdp.send('Fetch.enable',{patterns:[{urlPattern:'*',requestStage:'Request'}]});
 await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});await cdp.send('Page.navigate',{url:origin});
 await until('!!window.__zhizuLayoutDiagnostics?.length && !document.getElementById("quote-recheck")','mounted and private');
 assert.equal(await ev('document.getElementById("mode-proactive").getAttribute("aria-pressed")'),'true');
 assert.ok(await ev('!!document.getElementById("proactive-panel").getClientRects().length'));
 assert.equal(await ev('!!document.getElementById("quote-panel").getClientRects().length'),false);
 await click('#mode-reactive');
 assert.ok(await ev('!!document.getElementById("quote-panel").getClientRects().length'));
 for(const id of ['negotiation-panel','round-count','negotiation-score','latest-negotiation-result'])assert.equal(await ev(`!!document.getElementById('${id}').getClientRects().length`),false);
 assert.equal(paths.includes('/api/negotiation/meta'),false);assert.equal(paths.includes('/openapi.json'),false);
 pass('Quote panel replaces visible practice/score/round UI and loads independent privacy metadata');
 await shot('01-empty-desktop');
 await fill('landlord-quote','请核对维修费用。');assert.equal(await ev('document.getElementById("analyze-quote").disabled'),true);
 const contract='房屋租赁合同，双方应按约履行并核对交接记录。\n维修责任按实际原因和约定核对。';await fill('contract-input',contract);
 await until('!document.getElementById("analyze-quote").disabled','contract permits direct quote analysis');
 await ev('document.getElementById("landlord-quote").dispatchEvent(new CompositionEvent("compositionstart",{bubbles:true}))');await click('#analyze-quote');assert.equal(requests.length,0);await ev('document.getElementById("landlord-quote").dispatchEvent(new CompositionEvent("compositionend",{bubbles:true,data:""}))');
 await fill('landlord-quote','请核对维修费用，电话13800000000。');await pause(550);assert.ok(!(await ev('document.getElementById("landlord-quote").value')).includes('13800000000'));
 await ev('document.getElementById("analyze-quote").click();document.getElementById("analyze-quote").click()');await complete();
 assert.equal(requests.length,1);assert.equal(requests[0].contract_text,contract);assert.equal(Object.hasOwn(requests[0],'clause_id'),false);assert.ok(!requests[0].landlord_quote.includes('13800000000'));
 assert.equal(await ev('document.querySelectorAll("#quote-result .quote-reply").length'),3);
 pass('Direct full-contract analysis without review or clause selection; IME, masking and double-submit protection');
 await ev('document.getElementById("quote-result").scrollIntoView({block:"start",behavior:"instant"})');await shot('02-strategy-card');
 await ev('document.querySelector("#quote-result .quote-reply").scrollIntoView({block:"start",behavior:"instant"})');await shot('03-three-replies');
 await ev(`window.__quoteClipboard=[];Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async t=>window.__quoteClipboard.push(t)}})`);
 for(const tone of ['tactful','reasoned','firm'])await click('#copy-quote-'+tone);
 assert.equal(await ev('window.__quoteClipboard.length'),3);assert.ok((await ev('window.__quoteClipboard')).every(t=>!t.includes('C-001')&&!t.includes('适用')));
 await ev(`Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw Error('denied')}}})`);await click('#copy-quote-firm');assert.ok(await ev('document.getElementById("quote-copy-fallback").value.includes("沟通记录")'));
 pass('Three copy actions copy only reply text; clipboard denial exposes manual fallback');
 // No blur events: rapid changes in one field must not cancel another mask.
 await fill('quote-context','背景联系电话13800000000。');await fill('quote-goal','目标联系电话13900000000。');await pause(600);
 assert.ok(!(await ev('document.getElementById("quote-context").value')).includes('13800000000'));
 assert.ok(!(await ev('document.getElementById("quote-goal").value')).includes('13900000000'));
 pass('Privacy debounce is independent per field even without blur');
 await fill('quote-context','背景号码13800000000。');await ev('document.getElementById("quote-goal").dispatchEvent(new CompositionEvent("compositionstart",{bubbles:true}))');
 await fill('quote-goal','中文输入13900000000');await pause(600);
 assert.ok(!(await ev('document.getElementById("quote-context").value')).includes('13800000000'));
 assert.equal(await ev('document.getElementById("analyze-quote").disabled'),true);
 await ev('document.getElementById("quote-goal").dispatchEvent(new CompositionEvent("compositionend",{bubbles:true}))');
 assert.ok(!(await ev('document.getElementById("quote-goal").value')).includes('13900000000'));
 pass('IME in one field does not postpone another field masking, and still blocks submit');
 assert.equal(await ev('document.getElementById("landlord-quote").maxLength'),2000);
 await fill('landlord-quote','');await ev('document.getElementById("landlord-quote").focus()');await cdp.send('Input.insertText',{text:'字'.repeat(2001)});
 assert.equal(await ev('document.getElementById("landlord-quote").value.length'),2000);
 await fill('landlord-quote','请核对维修费用。');
 pass('Native textarea input enforces the 2000-character cap');
 mode='bad_state';await click('#analyze-quote');await complete();assert.ok(await ev('!!document.getElementById("quote-error")'));
 assert.ok(await ev('document.getElementById("quote-result").textContent.includes("有材料支持")'));
 pass('Client rejects success+unclear instead of overwriting the previous coherent card');
 mode='out_of_scope';await click('#analyze-quote');await complete();assert.equal(await ev('!!document.getElementById("quote-result")'),false);assert.equal(await ev('!!document.getElementById("quote-copy-fallback")'),false);
 assert.ok(await ev('document.getElementById("quote-notice").textContent.includes("暂无法")'));
 pass('out_of_scope clears the previous card, snapshot and copy fallback');
 mode='needs_context';delay=1250;await fill('landlord-quote','费用先核对，需要补充前情。');await click('#analyze-quote');await pause(1050);assert.ok(await ev('document.getElementById("quote-timer").textContent.includes("1 秒")'));await complete();
 assert.equal(await ev('document.getElementById("quote-more").open'),true);assert.equal(await ev('document.querySelectorAll("#quote-result .quote-reply").length'),3);assert.ok(await ev('document.getElementById("quote-questions").textContent.includes("费用明细")'));
 pass('Honest elapsed timer; needs_context keeps three clarification replies and opens the background editor');
 mode='failure';delay=60;const previous=await ev('document.getElementById("quote-result").textContent');await fill('quote-context','我有交接单。');await click('#analyze-quote');await complete();assert.ok(await ev('document.getElementById("quote-error").textContent.includes("未通过")'));assert.ok(!(await ev('document.body.textContent')).includes('DO_NOT_DISPLAY_UPSTREAM'));assert.equal(await ev('document.getElementById("quote-context").value'),'我有交接单。');assert.ok((await ev('document.getElementById("quote-result").textContent')).includes('费用明细'));assert.ok(previous);
 pass('Controlled generation failure preserves input and the previous card without leaking upstream output');
 mode='unsafe';await click('#analyze-quote');await complete();assert.ok(await ev('document.getElementById("quote-error").textContent.includes("内容安全规则")'));assert.ok(await ev('!!document.getElementById("quote-result")'));
 pass('Safety refusal has a distinct controlled hint and preserves prior card');
 mode='privacy';await click('#analyze-quote');await complete();assert.ok(await ev('document.getElementById("landlord-quote").value.includes("服务端安全预览")'));assert.ok(await ev('document.getElementById("quote-error").textContent.includes("再次提交")'));
 const count=requests.length;await pause(150);assert.equal(requests.length,count);
 pass('428 applies matching safe preview and requires another explicit submission');
 mode='success';delay=350;await click('#analyze-quote');await fill('landlord-quote','这是在途后新编辑的消息。');await complete();assert.equal(await ev('document.getElementById("landlord-quote").value'),'这是在途后新编辑的消息。');assert.ok(await ev('!!document.getElementById("quote-stale")'));
 pass('Editing during a request preserves new text and marks the returned old snapshot');
 // Preserve the actual review/version flow as well as the no-review path.
 await click('#analyze-contract');await until('document.querySelectorAll("#risk-items [data-clause]").length===1','review fixture');await click('[data-clause="C-01"]');
 await click('#mode-reactive');await fill('landlord-quote','历史合同版本的消息。');await click('#analyze-quote');await complete();assert.equal(requests.at(-1).contract_text,contract);
 // Different owners must not collide through Object.toString coercion either.
 await fill('quote-context','历史记录号码13800000000');await click('#edit-contract');await fill('quote-context','编辑记录号码13900000000');await pause(600);
 assert.ok(!(await ev('document.getElementById("quote-context").value')).includes('13900000000'));
 await ev(`(()=>{const e=document.querySelector('select[aria-label="查看分析版本"]');e.dispatchEvent(new Event('change',{bubbles:true}));})()`);await pause(50);
 assert.ok(!(await ev('document.getElementById("quote-context").value')).includes('13800000000'));
 pass('Privacy debounce remains independent across historical/editor owners');
 // A response belonging to the historical contract cannot overwrite the editor.
 const historicalId=await ev(`document.querySelector('select[aria-label="查看分析版本"]').value`);
 await fill('landlord-quote','历史合同仍在处理的消息。');await click('#analyze-quote');
 await click('#edit-contract');await fill('contract-input','另一份房屋租赁合同，费用应依据实际项目与约定核对。');await pause(450);assert.equal(await ev('document.getElementById("landlord-quote").value'),'这是在途后新编辑的消息。');assert.ok(await ev('!!document.getElementById("quote-stale")'));
 pass('Visible reviewed contract and editor have separate quote records; new contract text cannot impersonate an old result');
 await ev(`(()=>{const e=document.querySelector('select[aria-label="查看分析版本"]');e.value=${JSON.stringify(historicalId)};e.dispatchEvent(new Event('change',{bubbles:true}));})()`);await pause(60);
 assert.equal(await ev('document.getElementById("landlord-quote").value'),'历史合同仍在处理的消息。');assert.equal(await ev('!!document.getElementById("quote-stale")'),false);
 await ev(`Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:()=>new Promise(r=>window.__resolveQuoteCopy=r)}})`);await click('#copy-quote-firm');await click('#edit-contract');
 const copyBefore=await ev('document.getElementById("quote-copy-status")?.textContent||""');await ev('window.__resolveQuoteCopy()');await pause(50);assert.equal(await ev('document.getElementById("quote-copy-status")?.textContent||""'),copyBefore);
 pass('Late cross-version responses and delayed clipboard completion stay with the original record');
 for(const [w,h,zoom] of [[1440,900,1],[720,450,1],[390,844,1],[1440,900,2]]){
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:w,height:h,deviceScaleFactor:1,mobile:w===390});await ev(`document.body.style.zoom='${zoom}'`);await pause(100);await click('.pane-switcher [aria-controls="task-panel"]');await ev('document.getElementById("analyze-quote").scrollIntoView({block:"nearest",behavior:"instant"})');
  assert.ok(await ev('document.documentElement.scrollWidth<=innerWidth+2 && document.documentElement.scrollHeight<=innerHeight+2'),`bounded ${w} ${h} ${zoom}`);
  assert.ok(await ev('(()=>{const a=document.getElementById("analyze-quote").getBoundingClientRect(),p=document.getElementById("task-panel").getBoundingClientRect();return a.top>=p.top-1&&a.bottom<=p.bottom+1})()'));
  await shot(`layout-${w}-${h}-${zoom}`);
 }
 pass('Desktop, short/tablet, mobile and 200% reflow retain bounded app shell and reachable action');
 assert.equal(paths.some(p=>['/api/negotiation/turn','/api/review/proposal','/api/negotiation/meta'].includes(p)),false);
 assert.equal(cdp.errors.length,0,JSON.stringify(cdp.errors));assert.equal(cdp.external.length,0);
 fs.writeFileSync(path.join(output,'browser-results.json'),JSON.stringify({passed:cases.length,failed:0,cases,quote_requests:requests.length,external_requests:cdp.external.length,fixture:'explicit HTTP doubles; no cloud'},null,2));
 console.log('Quote browser groups passed: '+cases.length);
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{if(cdp){try{await cdp.send('Browser.close');}catch{}cdp.ws.close();}if(edge)edge.kill();server.closeAllConnections();server.close();});

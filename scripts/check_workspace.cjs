// Shared interaction contract. Runs against Day 8 review doubles and Day 10 real local graphs.
module.exports=async function({cdp,click,fill,until,pause,assert,real,requests,responses=[],pass,mode,shot}){
 const ev=e=>cdp.evaluate(e);
 assert.equal(await ev('document.querySelectorAll("#negotiation-draft").length'),1);
 await ev('window.savedComposer=document.getElementById("negotiation-draft")');
 pass('Stable workspace and one mounted Composer');
 await shot('01-input');
 const raw=real?'房屋租赁合同。租赁结束后可不说明理由直接扣留全部押金。\n维修责任和费用均由租客承担。\n提前退租须支付固定违约金2000元。\n电话13800000000，身份证11010119900101000X。':'租赁合同\n联系电话：13800000000。维修责任和费用均由租客承担。\n联系电话：13800000000。维修责任和费用均由租客承担。\n<img src=x onerror="window.__xss=1">';
 const nReview=()=>requests.filter(r=>real?r.path==='/api/review/analyze-detailed':true).length;
 await ev('(async()=>{const e=document.getElementById("contract-input");e.value="房屋租赁合同，电话13800000000";e.dispatchEvent(new Event("input",{bubbles:true}));await Promise.resolve();document.getElementById("analyze-contract").click()})()');await pause(60);
 assert.equal(nReview(),0);assert.ok(!(await ev('document.getElementById("contract-input").value')).includes('13800000000'));
 pass('Submit-time new masking requires a second explicit confirmation of the displayed replacement');
 await fill('contract-input',raw);await pause(600);
 assert.ok(!(await ev('document.getElementById("contract-input").value')).includes('13800000000'));
 assert.equal(nReview(),0);pass('Local masking occurs in the original editor, without upload or second preview');
 const safe=await ev('document.getElementById("contract-input").value');
 await ev('document.getElementById("analyze-contract").click();document.getElementById("analyze-contract").click()');
 await until('document.querySelectorAll("#risk-navigation [data-clause]").length===3','review completes');
 assert.equal(nReview(),1);assert.equal(requests.find(r=>!real||r.path==='/api/review/analyze-detailed').contract_text,safe);
 assert.equal(await ev('document.getElementById("submitted-document").textContent'),safe);
 assert.equal(await ev('window.__xss'),undefined);pass('One explicit consent action submits exactly the displayed sanitized text; duplicate blocked; HTML remains text');
 await click('[data-clause="C-01"]');
 assert.ok(await ev('document.querySelector("mark.current")!==null'));
 assert.equal(await ev('document.getElementById("negotiation-draft")===window.savedComposer'),true);
 pass('Risk selection preserves full source and mounted Composer');await shot('02-review');
 await click('#prepare-communication');
 await fill('negotiation-draft','选场景前写好的消息');await click('#message-privacy-confirm');
 assert.equal(await ev('document.getElementById("send-negotiation").disabled'),true);
 assert.ok(await ev('document.getElementById("send-readiness").textContent.includes("先选择")'));
 await click('#send-readiness button');assert.equal(await ev('document.activeElement.id'),'scenario-select');
 await fill('scenario-select','maintenance','change');
 assert.equal(await ev('document.getElementById("negotiation-draft").value'),'选场景前写好的消息');
 assert.equal(await ev('document.getElementById("message-privacy-confirm").checked'),true);
 if(real){await until('!document.getElementById("send-negotiation").disabled','valid confirmed message enables send');}
 await fill('scenario-select','deposit','change');
 pass('Missing scenario has an actionable explanation; first selection preserves message and consent and enables available service');
 await fill('negotiation-draft','A 的消息，要求核对押金收据。');await click('#message-privacy-confirm');
 await click('[data-clause="C-02"]');await click('#prepare-communication');await fill('scenario-select','maintenance','change');
 await fill('negotiation-draft','B 的消息，请明确维修责任。');
 await click('[data-clause="C-01"]');await click('#prepare-communication');
 assert.equal(await ev('document.getElementById("negotiation-draft").value'),'A 的消息，要求核对押金收据。');
 assert.equal(await ev('document.getElementById("message-privacy-confirm").checked'),true);
 await fill('negotiation-draft','A 改写');assert.equal(await ev('document.getElementById("message-privacy-confirm").checked'),false);
 pass('A/B drafts and consent are record-local; rebinding is not an edit');
 await ev('document.getElementById("negotiation-draft").dispatchEvent(new CompositionEvent("compositionstart",{bubbles:true}))');
 await click('[data-clause="C-02"]');assert.equal(await ev('document.getElementById("negotiation-draft").value'),'A 改写');
 await ev('document.getElementById("negotiation-draft").dispatchEvent(new CompositionEvent("compositionend",{bubbles:true}))');await pause(60);
 await click('#prepare-communication');assert.equal(await ev('document.getElementById("negotiation-draft").value'),'B 的消息，请明确维修责任。');
 pass('IME composition defers navigation until the real composition end event');
 await require('./check_v35_interactions.cjs')({cdp,pause,assert,pass,requests});
 if(!real){
   assert.equal(await ev('document.getElementById("send-negotiation").disabled'),true);
   await until('!!document.getElementById("retry-negotiation-api")','missing OpenAPI recovery');await click('#retry-negotiation-api');
   await click('[data-clause="C-01"]');assert.ok(await ev('document.getElementById("clause-advice").textContent.includes("合成建议")'));
   assert.equal(await ev('document.querySelectorAll("mark.current").length'),1);
   await click('#task-panel .task-explanation details:last-child > summary');await click('.law-card > summary');
   const law=require('../backend/data/laws/civil_code_lease_703_734.json').find(x=>x.law_id==='LAW-709');
   assert.equal(await ev('document.querySelector(".law-body").textContent'),law.content);
   assert.equal(await ev('document.querySelector(".law-meta a").href'),law.source_url);
   assert.ok(await ev('document.querySelector(".law-meta").textContent').then(text=>text.includes(law.verified_date)));
   const firstOffset=await ev('document.querySelector("mark.current").dataset.start');await ev('[...document.querySelectorAll("#location-notice button")].find(b=>b.textContent==="下一处").click()');await pause(50);
   assert.notEqual(await ev('document.querySelector("mark.current").dataset.start'),firstOffset);
   assert.equal(await ev('document.getElementById("submitted-document").textContent'),safe);
   pass('Law text, source and date equal the canonical library; repeated occurrences preserve exact source');
   await click('[data-clause="C-02"]');assert.ok(await ev('document.getElementById("location-notice").textContent.includes("未找到")'));
   for(const failure of ['failure','badjson','http422']){await mode(failure);await click('#edit-contract');await fill('contract-input',safe+'\n新编辑版本'+failure);await click('#analyze-contract');await until('document.querySelector(".notice-error")!==null','failure visible');await pause(150);assert.equal(await ev('document.getElementById("submitted-document").textContent'),safe);assert.ok(!await ev('document.body.textContent.includes("DO_NOT_DISPLAY_RAW_INPUT")'));}
   pass('Unlocated source is honest; missing service retry and all review failures preserve prior source without leaking raw errors');
   await mode('overlap');await fill('contract-input','租赁合同\n维修责任由房东承担。\n费用由双方确认。\n哈哈哈哈哈');await click('#analyze-contract');await until('document.getElementById("submitted-document").textContent.includes("哈哈哈哈哈")','overlapping review');
   assert.equal(await ev('document.querySelectorAll("mark mark").length'),0);assert.equal(await ev('document.getElementById("submitted-document").textContent'),'租赁合同\n维修责任由房东承担。\n费用由双方确认。\n哈哈哈哈哈');pass('Cross-paragraph and self-overlapping matches preserve exact source without nested marks');
 }else{
   const setTask=async label=>{await ev(`[...document.querySelectorAll('.task-tabs button')].find(b=>b.textContent===${JSON.stringify(label)}).click()`);await pause(40)};
   const msg=async text=>{await setTask('写沟通消息');await fill('negotiation-draft',text);if(!await ev('document.getElementById("message-privacy-confirm").checked'))await click('#message-privacy-confirm');};
   const snapshot=()=>ev('({round:document.getElementById("round-count").dataset.round,score:document.getElementById("negotiation-score").textContent,terms:document.getElementById("confirmed-terms").textContent})');
   const turn=async(score)=>{await msg('请核对凭证并明确返还安排。');await click('#send-negotiation');await until(`document.getElementById('negotiation-score').textContent==='${score} / 100' && document.getElementById('negotiation-draft').value===''`,'accepted turn');};
   // Generate with C-02's real cited law through the production service and explicit model double.
   const beforePrivate=requests.length;
   await fill('negotiation-draft','请回电 +86 138-0000-0000，证件11010119900101000X和110101900101001。');await click('#message-privacy-confirm');await click('#send-negotiation');
   assert.equal(requests.length,beforePrivate);assert.equal(await ev('document.getElementById("message-privacy-confirm").checked'),false);
   assert.ok(!/[0-9]{6}/.test(await ev('document.getElementById("negotiation-draft").value')));
   await fill('negotiation-draft','B 的消息，请明确维修责任。');
   await click('#proposal-tool > summary');await fill('proposal-goal','请核对手机号13800000000对应的维修费用。');await click('#proposal-privacy-confirm');await click('#generate-proposal');
   assert.equal(requests.length,beforePrivate);assert.equal(await ev('document.getElementById("proposal-privacy-confirm").checked'),false);
   pass('Final message and goal masking revoke their own consent and upload nothing until explicitly reconfirmed');
   await fill('proposal-goal','请核对维修费用凭证。');await click('#proposal-privacy-confirm');await click('#generate-proposal');
   await until('!!document.getElementById("proposed-message")','proposal');
   const original=await ev('document.getElementById("proposed-message").textContent');
   await fill('proposal-goal','请核对维修费用凭证，并说明期限。');
   assert.equal(await ev('document.getElementById("proposed-message").textContent'),original);
   assert.ok(await ev('document.getElementById("proposal-preview").textContent.includes("修改前")'));
   assert.equal(await ev('document.getElementById("proposal-privacy-confirm").checked'),false);
   pass('Editing the goal retains prior draft and questions, marks them stale and revokes only its consent');
   await click('#fill-proposal');assert.ok(await ev('!!document.getElementById("proposal-overwrite")'));await click('#confirm-fill-proposal');
   assert.equal(await ev('document.getElementById("negotiation-draft").value'),original);assert.equal(await ev('document.getElementById("message-privacy-confirm").checked'),false);
   assert.equal((await snapshot()).round,'0');pass('Explicit old-draft adoption confirms replacement and never sends or consumes a round');
   await click('#proposal-privacy-confirm');await mode('proposal_invalid');await click('#generate-proposal');await until('!!document.getElementById("proposal-error")','bad model output rejected');assert.equal(await ev('document.getElementById("proposed-message").textContent'),original);await mode('normal');
   pass('Rejected draft generation retains old reference and never exposes unvalidated PII');
   // Request A completes while viewing B. Score/effect validation must use A's baseline.
   await click('[data-clause="C-01"]');await click('#prepare-communication');await msg('返还押金，请核对明细。');
   await ev('document.getElementById("negotiation-draft").focus()');
   await cdp.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,modifiers:2});
   await cdp.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,modifiers:2});
   await click('#send-negotiation');
   assert.equal(await ev('document.getElementById("new-practice").disabled'),true);
   await click('[data-clause="C-02"]');await click('#prepare-communication');await pause(1800);assert.equal((await snapshot()).round,'0');
   await click('[data-clause="C-01"]');await click('#prepare-communication');assert.equal((await snapshot()).round,'1');assert.equal((await snapshot()).score,'50 / 100');
   pass('In-flight A response commits to A while B stays untouched; duplicate click submits once');
   await turn(75);const before=await snapshot();await msg('请再核对押金。');
   await require('./check_micro_polish.cjs')({cdp,pause,assert,pass});
   await mode('critic_failure');await click('#send-negotiation');await until('!!document.getElementById("negotiation-error")','Critic failure');assert.deepEqual(await snapshot(),before);await mode('normal');
   const failed=responses.filter(r=>r.path==='/api/negotiation/turn').at(-1).data;
   assert.equal(failed.status,'needs_review');assert.equal(Math.max(...failed.trace.map(e=>e.attempt)),3);
   await click('.task-detail-link');await pause(1500);assert.ok(await ev('document.querySelectorAll(".trace-step[data-status=retry]").length>0'));await click('#trace-toggle');
   pass('Critic failure preserves official round, score and terms');
   cdp.dropNext=true;await msg('请明确押金返还期限。');await click('#send-negotiation');await until('document.getElementById("send-negotiation").textContent.includes("重试")','lost response');
   const first=requests.filter(r=>r.path==='/api/negotiation/turn').at(-1);assert.equal(await ev('document.getElementById("negotiation-draft").disabled'),true);
   await click('#send-negotiation');await until('document.getElementById("round-count").dataset.round==="3"','cached success');const retry=requests.filter(r=>r.path==='/api/negotiation/turn').at(-1);assert.equal(retry.request_id,first.request_id);assert.equal(retry.user_input,first.user_input);
   pass('Lost response locks its message and retries the same request, accepting cached success once');
   await turn(100);await turn(100);assert.equal(await ev('document.getElementById("send-negotiation").disabled'),true);
   const count=requests.length;await click('#send-negotiation');assert.equal(requests.length,count);pass('Five successful rounds disable sixth submission');
   const aRequest=requests.filter(r=>r.path==='/api/negotiation/turn').at(-1).request_id;
   await shot('03-results');
   await ev('Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:()=>Promise.reject(new Error("denied"))}})');
   await click('#negotiation-more > summary');await fill('unresolved-requests','希望尽快返还押金，并联系13800000000。');await fill('missing-facts','核对身份证110101900101001对应凭证。');
   await click('#export-checklist');await until('!!document.getElementById("checklist-copy")','copy fallback');
   assert.ok(await ev('document.getElementById("checklist-copy").value.includes("押金扣留")'));assert.equal(await ev('document.activeElement.id'),'checklist-copy');
   assert.ok(await ev('document.getElementById("checklist-status").getClientRects().length>0'));
   const copied=await ev('document.getElementById("checklist-copy").value');assert.ok(copied.includes('### 自行补充（待确认）\n- 希望尽快返还押金，并联系***。'));assert.ok(copied.includes('### 自行补充（待核实）\n- 核对身份证***对应凭证。'));assert.ok(!copied.split('## 待明确事项')[0].includes('尽快'));
   await click('[data-clause="C-02"]');await click('#prepare-communication');await turn(50);await turn(75);await turn(100);
   await click('#export-checklist');await until('!!document.getElementById("checklist-copy")','B copy');const bcopy=await ev('document.getElementById("checklist-copy").value');assert.ok(bcopy.includes('维修责任'));assert.ok(!bcopy.includes('确认返还押金'));pass('Independent scenario scores and per-session exports never merge conditions');
   await click('#standalone-practice');await fill('scenario-select','early_termination','change');assert.equal((await snapshot()).round,'0');await turn(50);await turn(75);await turn(100);pass('Standalone practice has its own session and decreasing-fee improvement uses real rule output');
   // Real review overlap: editing while request in flight cannot change submitted source.
   await click('#edit-contract');await fill('contract-input',safe+'\n新版本一');await click('#analyze-contract');await click('#edit-contract');await fill('contract-input',safe+'\n尚未提交的下一版');await pause(1800);
   assert.equal(await ev('document.getElementById("contract-input").value'),safe+'\n尚未提交的下一版');assert.equal(await ev('document.getElementById("submitted-document").textContent'),safe+'\n新版本一');assert.ok(await ev('document.body.textContent.includes("旧版合同")'));
   await click('[data-clause="C-01"]');await click('#prepare-communication');await fill('scenario-select','deposit','change');assert.equal((await snapshot()).round,'0');assert.equal(await ev('document.getElementById("negotiation-draft").value'),'');pass('New local analysis version isolates reused clause IDs and preserves concurrent edits');
   await ev('const sel=document.querySelector("[aria-label=查看分析版本]");sel.value=sel.options[0].value;sel.dispatchEvent(new Event("change",{bubbles:true}))');await pause(40);await click('[data-clause="C-01"]');await click('#prepare-communication');assert.equal((await snapshot()).round,'5');pass('Returning to a previous analysis restores its own completed practice');
   await shot('04-restored');
   // Real trace fields remain faithful after ownership migration.
   await click('.task-detail-link');await pause(1800);
   const trace=await ev('[...document.querySelectorAll(".trace-event")].map(e=>({n:+e.dataset.sequence,node:e.dataset.node,status:e.dataset.status,duration:+e.dataset.duration,attempt:+e.dataset.attempt}))');
   assert.ok(trace.length>=4);trace.forEach((e,i)=>{assert.equal(e.n,i+1);assert.ok(e.duration>=0);assert.ok(e.attempt<=3)});
   assert.ok(trace.some(e=>e.node==='critic'));await click('#trace-toggle');
   const canonical=responses.findLast(r=>r.path==='/api/negotiation/turn'&&r.data.request_id===aRequest).data.trace;
   assert.deepEqual(trace,canonical.map(e=>({n:e.sequence,node:e.node,status:e.status,duration:e.duration_ms,attempt:e.attempt})));
   pass('Owner-local Trace renders actual node sequences, bounded attempts and nonnegative measured durations');
   // Delayed clipboard completion belongs to original session, never the newly selected one.
   await setTask('练习结果与清单');
   await ev('navigator.clipboard.writeText=text=>{window.copyPayload=text;return new Promise((resolve,reject)=>window.rejectCopy=reject)}');
   await click('#export-checklist');await click('[data-clause="C-02"]');await click('#prepare-communication');await msg('保留 B 的手工消息');
   await ev('document.getElementById("negotiation-draft").focus();window.rejectCopy(new Error("denied"))');await pause(60);
   assert.equal(await ev('document.activeElement.id'),'negotiation-draft');assert.equal(await ev('document.getElementById("negotiation-draft").value'),'保留 B 的手工消息');
   await click('[data-clause="C-01"]');await click('#prepare-communication');await setTask('练习结果与清单');assert.equal(await ev('document.getElementById("checklist-copy").value'),await ev('window.copyPayload'));
   pass('Late clipboard denial retains the frozen original-session payload without focus theft or cross-session export');
   // Separate goal request owner from the active practice. Editing a target keeps old reference,
   // but a late generation for the previous target cannot replace it.
   await click('[data-clause="C-02"]');await click('#prepare-communication');
   if(!await ev('document.getElementById("proposal-tool").open'))await click('#proposal-tool > summary');
   await fill('proposal-goal','新目标，核对费用和凭证。');await click('#proposal-privacy-confirm');
   await click('#generate-proposal');await fill('proposal-goal','生成期间修改为另一目标。');await pause(1800);
   assert.equal(await ev('document.getElementById("proposed-message").textContent'),original);assert.ok(await ev('document.getElementById("proposal-preview").textContent.includes("修改前")'));
   pass('Changing target invalidates its in-flight generation without deleting its accepted reference');
   // Proposal transport replay uses the same draft request and never touches formal state.
   await click('#proposal-privacy-confirm');cdp.dropNextProposal=true;await click('#generate-proposal');await until('document.getElementById("generate-proposal").textContent.includes("重试")','proposal response lost');
   const draftId=requests.filter(r=>r.path==='/api/review/proposal').at(-1).draft_request_id;const official=await snapshot();
   await click('#generate-proposal');await until('!document.getElementById("generate-proposal").textContent.includes("重试") && !document.getElementById("generate-proposal").disabled','proposal replay');
   assert.equal(requests.filter(r=>r.path==='/api/review/proposal').at(-1).draft_request_id,draftId);assert.deepEqual(await snapshot(),official);pass('Lost drafting response uses same independent request ID and preserves formal practice state');
   cdp.quotaNextProposal=true;await fill('proposal-goal','再次核对');await click('#proposal-privacy-confirm');await click('#generate-proposal');await until('document.getElementById("proposal-error")?.textContent.includes("上限")','explicit quota error');assert.ok(!await ev('document.getElementById("generate-proposal").textContent.includes("重试")'));pass('Explicit drafting quota rejection explains recovery and clears unusable retry metadata');
   // A malformed effect must not commit; same-id replay recovers canonical server outcome.
   cdp.invalidEffectNext=true;await msg('继续核对维修责任。');await click('#send-negotiation');await until('document.getElementById("send-negotiation").textContent.includes("重试")','invalid effect');assert.deepEqual(await snapshot(),official);
   await click('#send-negotiation');await until('document.getElementById("round-count").dataset.round==="4"','valid replay');pass('Contradictory turn-effect metadata is rejected; canonical replay commits once');
   cdp.invalidTraceNext=true;await msg('请书面确认。');await click('#send-negotiation');await until('document.getElementById("round-count").dataset.round==="5"','final B round');await click('.task-detail-link');await pause(300);
   assert.equal(await ev('document.querySelectorAll(".trace-event").length'),0);assert.ok(await ev('document.getElementById("trace-note").textContent.includes("格式")'));await click('#trace-toggle');pass('Malformed Trace is not fabricated or substituted, independently of valid official results');
   // A held old review is delivered after a newer accepted review.
   cdp.holdReviewNext=true;await click('#edit-contract');await fill('contract-input',safe+'\n较早提交');await click('#analyze-contract');
   for(let i=0;i<60&&!cdp.releaseReview;i++)await pause(50);assert.ok(cdp.releaseReview);
   await click('#edit-contract');await fill('contract-input',safe+'\n最新提交');await click('#analyze-contract');await until('document.getElementById("submitted-document").textContent.endsWith("最新提交")','new review wins');
   cdp.releaseReview();cdp.releaseReview=null;await pause(300);assert.ok(await ev('document.getElementById("submitted-document").textContent.endsWith("最新提交")'));pass('Older review response cannot overwrite a newer submitted version');
   await click('#standalone-practice');const previousPractice=await snapshot();await click('#new-practice');assert.equal((await snapshot()).round,'0');
   await ev('(()=>{const e=document.querySelector("[aria-label=查看练习记录]");e.value=e.options[0].value;e.dispatchEvent(new Event("change",{bubbles:true}))})()');await pause(60);assert.deepEqual(await snapshot(),previousPractice);
   pass('An explicit fresh practice uses a new session while the prior standalone practice stays selectable and unchanged');
 }
 // Layout and accessible stable controls, including 200% reflow and touch width.
 await click('#standalone-practice');
 for(const [w,h,zoom] of [[1440,900,1],[1440,900,2],[390,844,1],[1280,560,1]]){
   await cdp.send('Emulation.setDeviceMetricsOverride',{width:w,height:h,deviceScaleFactor:1,mobile:w===390});await ev(`document.body.style.zoom=${JSON.stringify(String(zoom))}`);await pause(150);
   await ev('document.getElementById("task-panel").scrollIntoView({block:"start",behavior:"instant"})');await pause(100);
   assert.ok(await ev('document.getElementById("send-negotiation").getBoundingClientRect().bottom<=innerHeight*2'),'Send is at most one further viewport below task entry');
   await ev('document.getElementById("send-negotiation").scrollIntoView({block:"center",behavior:"instant"})');
   assert.ok(await ev('(()=>{const e=document.getElementById("send-negotiation"),r=e.getBoundingClientRect();return r.width>0&&r.top>=0&&r.bottom<=innerHeight&&document.elementFromPoint(r.left+r.width/2,r.top+r.height/2)===e})()'));
   assert.ok(await ev('document.documentElement.scrollWidth<=innerWidth+2'));
   assert.equal(await ev('document.getElementById("negotiation-draft")===window.savedComposer'),true);
   await shot(`layout-${w}-${h}-${zoom}`);
 }
 pass('1440 desktop, 200% reflow, mobile and short viewport: one scroll reaches uncovered send button; Composer identity retained');
};

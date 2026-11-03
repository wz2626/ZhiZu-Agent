// Browser checks use production local services with explicitly labelled cloud doubles.
module.exports=async({cdp,click,fill,until,pause,assert,pass,shot,requests,mode})=>{
 const ev=e=>cdp.evaluate(e),drafts=()=>requests.filter(r=>r.path==='/api/review/proposal');
 await mode('normal');
 await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
 await cdp.send('Page.reload',{ignoreCache:true});await pause(180);await until('!!window.__zhizuLayoutDiagnostics?.length','workspace');
 await fill('contract-input','房屋租赁合同。租赁结束后可不说明理由直接扣留全部押金。\n维修责任和费用均由租客承担。\n提前退租须支付固定违约金2000元。');
 await click('#analyze-contract');await until('document.querySelectorAll("#risk-items [data-clause]").length===3','analysis');
 await click('[data-clause="C-02"]');await click('#prepare-communication');await click('#proposal-tool>summary');
 await ev('window.__styleComposer=document.getElementById("negotiation-draft")');
 const single=async()=>{
  assert.equal(await ev('document.querySelectorAll("#generate-proposal").length'),1);
  assert.equal(await ev('document.querySelectorAll("#update-proposal").length'),0);
  assert.equal(await ev('document.querySelectorAll("#proposal-tool button[aria-describedby=proposal-generate-readiness]").length'),1);
  assert.equal(await ev('document.querySelectorAll("#proposal-budget").length'),1);
 };
 await single();assert.equal(await ev('document.querySelector("input[name=expression-style]:checked").value'),'gentle');
 await fill('proposal-goal','请明确维修责任，要求本周五处理。');await fill('negotiation-draft','这条手写消息需要保留。');
 // Force random bytes whose old hexadecimal UUID suffix matched a phone number.
 await ev('(()=>{const original=crypto.getRandomValues.bind(crypto);crypto.getRandomValues=values=>{crypto.getRandomValues=original;values.set([110,66,16,142,85,116,70,129,182,174,18,84,32,80,56,142]);return values;}})()');
 await click('#generate-proposal');await until('!!document.getElementById("proposed-message")&&!document.getElementById("generate-proposal").disabled','first draft');
 assert.match(drafts().at(-1).draft_request_id,/^id_[a-p]{32}$/);
 assert.equal(drafts().at(-1).expression_style,'gentle');
 const first=structuredClone(drafts().at(-1));
 const id=await ev('document.querySelector("#current-answers textarea").id');await fill(id,'已保留照片和维修报价。');
 const budget=await ev('document.getElementById("proposal-budget").textContent'),oldText=await ev('document.getElementById("proposed-message").textContent'),count=drafts().length;
 await click('#expression-style-firm');await pause(100);
 assert.equal(drafts().length,count);assert.equal(await ev('document.getElementById('+JSON.stringify(id)+').value'),'已保留照片和维修报价。');
 assert.equal(await ev('document.getElementById("proposal-budget").textContent'),budget);
 assert.equal(await ev('document.getElementById("negotiation-draft").value'),'这条手写消息需要保留。');
 assert.equal(await ev('document.getElementById("proposed-message").textContent'),oldText);
 assert.ok(await ev('document.getElementById("proposal-preview").textContent.includes("表达风格已修改")'));
 cdp.emptyProposalQuestionsNext=true;await click('#generate-proposal');await until('!!document.getElementById("retained-answers")&&!document.getElementById("generate-proposal").disabled','firm draft');
 const firm=drafts().at(-1);assert.equal(firm.expression_style,'firm');assert.notEqual(firm.draft_request_id,first.draft_request_id);
 assert.equal(firm.answers.length,1);assert.equal('answer-'+firm.answers[0].question_id,id);assert.equal(firm.answers[0].text,'已保留照片和维修报价。');
 assert.equal(await ev('!!document.getElementById("current-answers")'),false);await single();
 assert.equal(await ev('document.querySelector(".draft-style-label").textContent'),'坚定明确');
 assert.equal(await ev('document.getElementById("generate-proposal").compareDocumentPosition(document.getElementById("retained-answers"))&Node.DOCUMENT_POSITION_PRECEDING'),2);
 pass('Expression style: one action follows all inputs; switching style sends nothing, preserves facts/answers/message/budget, marks the old draft stale and uses a new style-bound request; retained-only questions still allow updating');
 // Lost response recovers exactly the same frozen style and request body.
 cdp.dropNextProposal=true;await click('#generate-proposal');await until('document.getElementById("generate-proposal").textContent.includes("重试")','unknown draft');
 const lost=structuredClone(drafts().at(-1));await click('#generate-proposal');await until('!document.getElementById("generate-proposal").disabled&&!document.getElementById("generate-proposal").textContent.includes("重试")','replayed style');
 assert.deepEqual(drafts().at(-1),lost);
 // A style edit during an actually slow local model operation rejects the old response.
 const accepted=await ev('document.getElementById("proposed-message").textContent');
 await mode('proposal_slow');await click('#generate-proposal');await until('document.getElementById("generate-proposal").disabled','inflight');
 const slowCount=drafts().length;await click('#expression-style-concise');await pause(700);await mode('normal');
 assert.equal(drafts().length,slowCount);assert.equal(await ev('document.getElementById("proposed-message").textContent'),accepted);
 assert.ok(await ev('document.getElementById("proposal-preview").textContent.includes("表达风格已修改")'));
 await ev('document.getElementById("proposal-goal").dispatchEvent(new CompositionEvent("compositionstart",{bubbles:true}))');
 assert.equal(await ev('[...document.querySelectorAll("input[name=expression-style]")].every(e=>e.disabled)'),true);
 await click('#expression-style-firm');assert.equal(await ev('document.querySelector("input[name=expression-style]:checked").value'),'concise');
 await ev('document.getElementById("proposal-goal").dispatchEvent(new CompositionEvent("compositionend",{bubbles:true}))');
 await click('#generate-proposal');await until('!document.getElementById("generate-proposal").disabled','concise draft');assert.equal(drafts().at(-1).expression_style,'concise');
 assert.equal(await ev('document.getElementById("negotiation-draft").value'),'这条手写消息需要保留。');
 assert.equal(await ev('document.getElementById("round-count").textContent.includes("0")'),true);
 pass('Expression style: unknown retries retain the identical style/body/ID; style changes invalidate slow old responses without automatic requests, IME blocks changes, final messages and formal rounds stay intact');
 // Different clauses retain independent preferences; a result with no questions has the same action.
 await click('[data-clause="C-01"]');await click('#prepare-communication');
 assert.equal(await ev('document.querySelector("input[name=expression-style]:checked").value'),'gentle');
 await fill('proposal-goal','希望签约前明确押金退还安排。');cdp.emptyProposalQuestionsNext=true;await click('#generate-proposal');await until('!!document.getElementById("proposed-message")&&!document.getElementById("generate-proposal").disabled','no questions');
 assert.equal(await ev('!!document.getElementById("proposal-answers")'),false);await single();
 for(const width of [1440,390]){
  await cdp.send('Emulation.setDeviceMetricsOverride',{width,height:width===390?844:900,deviceScaleFactor:1,mobile:width===390});
  await ev('document.querySelector("#proposal-tool>summary").scrollIntoView({block:"start",behavior:"instant"})');await shot('expression-style-'+width,false);
  assert.ok(await ev('document.documentElement.scrollWidth<=innerWidth+2'));
  await ev('document.getElementById("generate-proposal").scrollIntoView({block:"center",behavior:"instant"})');
  assert.ok(await ev('(()=>{const b=document.getElementById("generate-proposal").getBoundingClientRect(),r=document.getElementById("proposal-generate-readiness").getBoundingClientRect();return b.top>=0&&b.bottom<=innerHeight&&r.top>=0&&r.bottom<=innerHeight})()'));
 }
 await click('[data-clause="C-02"]');await click('#prepare-communication');assert.equal(await ev('document.querySelector("input[name=expression-style]:checked").value'),'concise');
 assert.equal(await ev('document.getElementById("negotiation-draft")===window.__styleComposer'),true);
 pass('Expression style: clause-local preferences survive navigation; zero-question results retain a single action and budget, desktop/mobile controls remain in-bounds and the same Composer stays mounted');
};

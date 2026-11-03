// Direction UI is local. Extra directions must never become backend scenarios.
module.exports=async function({cdp,click,fill,until,pause,assert,pass,shot,real,mode}){
 const ev=s=>cdp.evaluate(s);
 await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
 await ev('document.body.style.zoom="1"');await click('#standalone-practice');
 const original=await ev('document.getElementById("scenario-select").value');
 const snapshot=()=>ev('({text:document.getElementById("negotiation-draft").value,round:document.getElementById("round-count").dataset.round,score:document.getElementById("negotiation-score").textContent})');
 const before=await snapshot();
 await ev('window.__directionComposer=document.getElementById("negotiation-draft")');
 assert.deepEqual(await ev('[...document.getElementById("scenario-select").options].filter(o=>!o.hidden).map(o=>o.value)'),['deposit','maintenance','early_termination','fees','other']);
 await ev(`window.__directionFetch=window.fetch;window.__directionTurns=0;window.fetch=(url,options)=>{if(String(url).includes('/api/negotiation/turn')&&options?.method==='POST')window.__directionTurns++;return window.__directionFetch(url,options)};window.__directionClipboard=Object.getOwnPropertyDescriptor(navigator,'clipboard');Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw Error('Synthetic clipboard denial')}}});`);
 try{
  await fill('scenario-select','fees','change');await fill('negotiation-draft','请提供水电费账单，并确认收费标准。');
  assert.ok(await ev('document.getElementById("communication-only-notice").textContent.includes("暂不提供固定条件演练")'));
  assert.ok(await ev('!document.getElementById("send-negotiation").getClientRects().length&&!document.getElementById("round-count").getClientRects().length&&!document.getElementById("condition-cloud-label")'));
  assert.ok(await ev('document.getElementById("proposal-goal").placeholder.includes("账单")'));
  await click('#copy-prepared-message');await until('!!document.getElementById("prepared-copy")','explicit clipboard fallback');
  assert.equal(await ev('document.getElementById("prepared-copy").value'),'请提供水电费账单，并确认收费标准。');
  await fill('scenario-select','other','change');await fill('negotiation-draft','请确认这条约定的具体执行方式。');
  await ev('document.getElementById("negotiation-draft").dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",ctrlKey:true,bubbles:true,cancelable:true}))');await pause(60);
  assert.equal(await ev('window.__directionTurns'),0);
  await fill('scenario-select','fees','change');assert.equal((await snapshot()).text,'请提供水电费账单，并确认收费标准。');
  await fill('scenario-select','other','change');assert.equal((await snapshot()).text,'请确认这条约定的具体执行方式。');
  if(original){await fill('scenario-select',original,'change');assert.deepEqual(await snapshot(),before);}
  pass('Communication directions: five real choices; fees/other preserve separate messages, copy fallback is usable, no fake score or turn POST, fixed practice remains intact');
  if(!real){
   await mode('directions');await click('#edit-contract');
   await fill('contract-input','房屋租赁合同\n房东可以无理由扣留押金。\n维修责任由租客承担。\n提前退租应说明交接安排。\n每月租金及水电费可以随意调整。\n房东可以随时进入房屋。\n退租时押金与维修事项另行协商。');
   await click('#analyze-contract');await until('document.querySelectorAll("#risk-items [data-clause]").length===6','direction coverage review');
   for(const [id,value]of[['C-01','deposit'],['C-02','maintenance'],['C-03','early_termination'],['C-04','fees'],['C-05','other'],['C-06','']]){
    await click('[data-clause="'+id+'"]');await click('#prepare-communication');assert.equal(await ev('document.getElementById("scenario-select").value'),value,id+' has a conservative recommendation');
    if(value)assert.ok(await ev('document.getElementById("direction-guidance").textContent.includes("已根据当前条款推荐")'));
   }
   await click('[data-clause="C-01"]');await click('#prepare-communication');await fill('scenario-select','other','change');await fill('negotiation-draft','用户自行选择的沟通方向。');
   await click('[data-clause="C-02"]');await click('#prepare-communication');await click('[data-clause="C-01"]');await click('#prepare-communication');
   assert.equal(await ev('document.getElementById("scenario-select").value'),'other');assert.equal((await snapshot()).text,'用户自行选择的沟通方向。');
   await fill('proposal-goal','先明确事实，不预设对方已同意。');await fill('scenario-select','fees','change');assert.equal(await ev('document.getElementById("proposal-goal").value'),'先明确事实，不预设对方已同意。');
   pass('Communication directions: deposit/repair/termination/fees/other recommendations follow source clauses; mixed topics stay unselected; manual choices and clause goals survive navigation');
   await shot('communication-fees');
   await fill('negotiation-draft','请核对服务费账单。');await ev('document.getElementById("negotiation-draft").dispatchEvent(new CompositionEvent("compositionstart",{bubbles:true}))');await fill('scenario-select','other','change');assert.equal((await snapshot()).text,'请核对服务费账单。');assert.ok(await ev('document.getElementById("direction-guidance").textContent.includes("账单")'));await ev('document.getElementById("negotiation-draft").dispatchEvent(new CompositionEvent("compositionend",{bubbles:true}))');await pause(60);assert.equal(await ev('document.getElementById("scenario-select").value'),'other');
   await cdp.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await pause(80);
   await click('.pane-switcher [aria-controls="task-panel"]');await ev('document.getElementById("copy-prepared-message").scrollIntoView({block:"nearest",behavior:"instant"})');
   assert.ok(await ev('document.documentElement.scrollHeight<=innerHeight+1&&document.documentElement.scrollWidth<=innerWidth+1'));assert.equal(await ev('document.getElementById("negotiation-draft")===window.__directionComposer'),true);await shot('communication-other-mobile');
   pass('Communication directions: IME postpones switching; mobile copy action is reachable, viewport stays fixed and the Composer is never remounted');
  }
 }finally{await ev(`window.fetch=window.__directionFetch;if(window.__directionClipboard)Object.defineProperty(navigator,'clipboard',window.__directionClipboard);else delete navigator.clipboard`);}
};

// Review completion must follow the work owner, not incidental UI navigation.
module.exports=async({cdp,click,fill,until,pause,assert,pass,shot})=>{
 const ev=e=>cdp.evaluate(e),text='房屋租赁合同。租赁结束后可不说明理由直接扣留全部押金。\n维修责任和费用均由租客承担。\n提前退租须支付固定违约金2000元。';
 const version=()=>ev('document.querySelector("[aria-label=查看分析版本]")?.value||""');
 async function fresh(width=1440){
  await cdp.send('Emulation.setDeviceMetricsOverride',{width,height:width===390?844:900,deviceScaleFactor:1,mobile:width===390});
  await cdp.send('Page.reload',{ignoreCache:true});await pause(180);
  await until('!!window.__zhizuLayoutDiagnostics?.length&&document.getElementById("service-status").textContent.includes("已连接")','fresh workspace');
 }
 async function hold(value=text){
  await fill('contract-input',value);
  await ev(`window.__activationFetch=window.fetch;window.__activationHeld=false;window.fetch=async(...args)=>{const response=await window.__activationFetch(...args);if(String(args[0]).includes('/api/review/analyze-detailed')){window.__activationHeld=true;await new Promise(resolve=>window.__activationRelease=resolve);}return response;}`);
  await click('#analyze-contract');await until('window.__activationHeld','review response waiting');
 }
 async function release(){await ev('window.__activationRelease();window.fetch=window.__activationFetch');await until('!document.getElementById("workspace").classList.contains("is-reviewing")','review completed');}
 async function displayed(){
  await until('document.querySelectorAll("#risk-items [data-clause]").length===3','results activated');
  assert.ok(await version());assert.ok(await ev('document.querySelector("[aria-label=查看分析版本]").selectedIndex>=0'));
  assert.equal(await ev('!!document.getElementById("view-ready-review")'),false);
 }
 for(const action of ['none','same-task','mobile-panes']){
  await fresh(action==='mobile-panes'?390:1440);await hold();
  if(action==='same-task'){await click('#check-contract');await click('#check-contract');}
  if(action==='mobile-panes'){await click('.pane-switcher [aria-controls="task-panel"]');await click('.pane-switcher [aria-controls="dossier"]');}
  await release();await displayed();
  if(action==='same-task')await shot('review-auto-activated',false);
 }
 pass('Review activation: first success, repeated current-task clicks and mobile pane changes all activate the completed version without an empty selector');
 await fresh(390);await hold();await click('#standalone-practice');await fill('scenario-select','maintenance','change');await fill('negotiation-draft','保留正在写的维修消息。');await release();
 assert.equal(await ev('document.querySelectorAll("#risk-items [data-clause]").length'),0);
 assert.equal(await version(),'');assert.equal(await ev('document.querySelector("[aria-label=查看分析版本]").selectedOptions[0].textContent'),'分析结果待查看');
 assert.equal(await ev('document.getElementById("negotiation-draft").value'),'保留正在写的维修消息。');
 assert.ok(await ev('document.getElementById("view-ready-review").getBoundingClientRect().height>0'));
 assert.ok(await ev('document.documentElement.scrollWidth<=innerWidth+2'));
 assert.ok(!await ev('document.getElementById("submitted-document").parentElement.textContent.includes("0 项待关注风险")'));
 await shot('review-ready-preserves-task',false);await click('#view-ready-review');await displayed();
 await click('#standalone-practice');assert.equal(await ev('document.getElementById("negotiation-draft").value'),'保留正在写的维修消息。');
 pass('Review background completion: actual task/draft stays intact, a visible ready action and meaningful placeholder appear, explicit activation preserves the other task');
 await fresh();await hold();await release();await displayed();const originalVersion=await version();
 await click('#edit-contract');await hold(text+'\n新一版合同说明。');
 await ev('(()=>{const s=document.querySelector("[aria-label=查看分析版本]");s.dispatchEvent(new Event("change",{bubbles:true}));})()');
 await release();assert.equal(await version(),originalVersion);
 assert.ok(!await ev('document.getElementById("submitted-document").textContent.endsWith("新一版合同说明。")'));
 assert.ok(await ev('!!document.getElementById("view-ready-review")'));await click('#view-ready-review');await displayed();
 assert.notEqual(await version(),originalVersion);assert.ok(await ev('document.getElementById("submitted-document").textContent.endsWith("新一版合同说明。")'));
 pass('Review explicit history choice: selecting even the already displayed older version prevents auto-switch; the new result remains explicitly available');
};

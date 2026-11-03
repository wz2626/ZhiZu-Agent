// Runs against the mixed HIGH / MEDIUM / NONE visual fixture, including zero LOW.
module.exports=async function({cdp,click,pause,assert,pass,shot}){
 const ev=s=>cdp.evaluate(s);
 const ids=()=>ev('[...document.querySelectorAll("#risk-items [data-clause]")].map(e=>e.dataset.clause)');
 const context=()=>ev(`({text:document.getElementById('submitted-document').textContent,current:document.querySelector('mark.current')?.dataset.start||null,explanation:document.getElementById('clause-explanation')?.textContent||null,composer:document.getElementById('negotiation-draft').value,round:document.getElementById('round-count').dataset.round})`);
 await ev(`window.__filterNativeFetch=window.fetch;window.__filterPosts=0;window.fetch=(url,options)=>{if(options?.method?.toUpperCase()==='POST')window.__filterPosts++;return window.__filterNativeFetch(url,options)}`);
 try{
  assert.deepEqual(await ids(),['C-01','C-02','C-03']);
  assert.equal(await ev('new Set([...document.querySelectorAll(".risk-filter")].map(e=>Math.round(e.getBoundingClientRect().top))).size'),1,'Desktop statistics stay together on one row');
  const counts=await ev('document.getElementById("risk-counts").textContent');
  await click('[data-risk-filter="MEDIUM"]');assert.deepEqual(await ids(),['C-02']);
  assert.equal(await ev('document.querySelector("[data-risk-filter=MEDIUM]").getAttribute("aria-pressed")'),'true');
  assert.equal(await ev('document.getElementById("risk-counts").textContent'),counts);
  await click('[data-risk-filter="MEDIUM"]');assert.deepEqual(await ids(),['C-01','C-02','C-03']);
  await click('[data-risk-filter="NONE"]');assert.deepEqual(await ids(),['C-03']);
  await click('[data-risk-filter="ALL"]');assert.deepEqual(await ids(),['C-01','C-02','C-03']);
  pass('Risk filter: grade toggles filter only the list; a repeated click or total restores all items including NONE; counts stay global');
  await click('[data-risk-filter="LOW"]');assert.deepEqual(await ids(),[]);
  assert.ok(await ev('document.querySelector(".risk-filter-empty").textContent.includes("当前没有低风险条款")'));
  await shot('risk-filter-empty');await click('.risk-filter-empty button');
  await ev('document.querySelector("[data-risk-filter=HIGH]").focus()');
  await cdp.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});
  await cdp.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});await pause(40);
  assert.deepEqual(await ids(),['C-01']);await click('[data-risk-filter="ALL"]');
  pass('Risk filter: zero-count choices provide an explicit reset; native keyboard activation works on filter buttons');
  await click('[data-clause="C-01"]');await pause(80);const before=await context();
  await click('[data-risk-filter="MEDIUM"]');assert.deepEqual(await ids(),['C-02']);
  assert.deepEqual(await context(),before);assert.ok(await ev('!!document.querySelector(".risk-filter-context")'));
  await shot('risk-filter-medium');
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:960,height:720,deviceScaleFactor:1,mobile:false});await pause(80);
  assert.ok(await ev('(()=>{const a=document.querySelector("#risk-items [data-clause]").getBoundingClientRect(),b=document.getElementById("risk-navigation").getBoundingClientRect();return a.top>=b.top&&a.bottom<=b.bottom+1})()'),'Tablet keeps the filtered card inside the risk pane');
  await click('[data-risk-filter="ALL"]');assert.equal(await ev('document.querySelector("[data-clause=C-01]").getAttribute("aria-pressed")'),'true');
  assert.equal(await ev('document.getElementById("negotiation-draft")===window.__visualComposer'),true);
  pass('Risk filter: excluding the selected clause preserves source, explanation, input and round; restoring all retains the selection');
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await pause(80);
  await click('.pane-switcher [aria-controls="risk-navigation"]');await click('[data-risk-filter="MEDIUM"]');
  assert.deepEqual(await ids(),['C-02']);assert.equal(await ev('document.getElementById("workspace").dataset.activePane'),'risk');
  assert.ok(await ev('document.documentElement.scrollWidth<=innerWidth+1&&document.documentElement.scrollHeight<=innerHeight+1'));
  await shot('risk-filter-mobile');await click('[data-risk-filter="ALL"]');
  assert.equal(await ev('window.__filterPosts'),0);await click('.pane-switcher [aria-controls="dossier"]');
  pass('Risk filter: mobile filtering stays in the risk pane with no viewport overflow, data loss or HTTP POST');
 }finally{
  await ev('window.fetch=window.__filterNativeFetch');
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});await pause(80);
  await click('[data-risk-filter="ALL"]');
 }
};

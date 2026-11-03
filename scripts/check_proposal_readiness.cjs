// UX regression: reasons stay beside their disabled action, without truncation
// or a request that exceeds either the combined or per-answer budget.
module.exports=async function({cdp,fill,click,pause,assert,requests,pass,ids,shot}){
 const ev=expression=>cdp.evaluate(expression);
 const scenarios=[
  {name:'total',lengths:[700,700,700],messages:['合计 2200 / 2000 字','请删减 200 字后更新'],blocked:true},
  {name:'single',lengths:[1100,100,100],messages:['第 1 项回答为 1100 / 1000 字','请删减 100 字'],blocked:true},
  {name:'both',lengths:[1200,500,500],messages:['合计 2300 / 2000 字','请删减 300 字后更新','第 1 项回答为 1200 / 1000 字'],blocked:true},
  {name:'at-limit',lengths:[700,700,500],messages:['合计 2000 / 2000 字'],blocked:false},
 ];
 const geometry=()=>ev(`(()=>{const b=document.getElementById('generate-proposal'),r=document.getElementById('proposal-generate-readiness'),budget=document.getElementById('proposal-budget');const rect=e=>{const v=e.getBoundingClientRect();return {top:v.top,bottom:v.bottom,left:v.left,right:v.right}};return {button:rect(b),reason:rect(r),pane:rect(document.getElementById('task-panel')),oldBudget:rect(budget),width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,text:r.textContent}})()`);
 for(const [width,height] of [[1440,900],[390,844]]){
  await cdp.send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:width<500});
  await fill('proposal-goal','目'.repeat(100));
  for(const scenario of scenarios){
   for(let i=0;i<ids.length;i++)await fill(ids[i],'答'.repeat(scenario.lengths[i]));
   await ev("document.getElementById('generate-proposal').scrollIntoView({block:'center',behavior:'instant'})");await pause(100);
   const view=await geometry();
   (cdp.proposalReadinessEvidence??=[]).push({width,height,scenario:scenario.name,...view});
   assert.equal(await ev('document.getElementById("generate-proposal").disabled'),scenario.blocked);
   assert.equal(await ev('document.querySelectorAll("#proposal-tool button[aria-describedby=proposal-generate-readiness]").length'),1);
   for(const text of scenario.messages)assert.ok(view.text.includes(text),view.text);
   assert.ok(view.button.top>=0&&view.button.bottom<=view.height,JSON.stringify(view));
   assert.ok(view.reason.top>=0&&view.reason.bottom<=view.height,JSON.stringify(view));
   assert.ok(view.button.top>=view.pane.top&&view.button.bottom<=view.pane.bottom,JSON.stringify(view));
   assert.ok(view.reason.top>=view.pane.top&&view.reason.bottom<=view.pane.bottom,JSON.stringify(view));
   if(scenario.blocked)assert.ok(view.reason.top>=view.button.bottom&&view.reason.top-view.button.bottom<65,JSON.stringify(view));
   else assert.ok((view.reason.top<view.button.bottom&&view.reason.bottom>view.button.top)||(view.reason.top>=view.button.bottom&&view.reason.top-view.button.bottom<65),JSON.stringify(view));
   assert.ok(view.scrollWidth<=view.width+2);
   assert.equal(await ev('document.querySelectorAll("#proposal-budget").length'),1);
   if(!scenario.blocked)assert.equal(await ev('getComputedStyle(document.getElementById("proposal-budget")).whiteSpace'),'nowrap');
   assert.equal(await ev('document.getElementById("generate-proposal").getAttribute("aria-describedby")'),'proposal-generate-readiness');
   for(let i=0;i<ids.length;i++)assert.equal(await ev(`document.getElementById(${JSON.stringify(ids[i])}).value.length`),scenario.lengths[i]);
   if(scenario.blocked){const before=requests.length;await click('#generate-proposal');assert.equal(requests.length,before);}
   if(shot&&['total','single'].includes(scenario.name))await shot(`budget-${width}-${scenario.name}`,false);
  }
  pass(`${width}px: combined/single/both limits explain the disabled action in-view, preserve text and block requests; exact 2000-character boundary enables the single action`);
 }
 await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
 await fill('proposal-goal','目'.repeat(900));for(const id of ids)await fill(id,'答'.repeat(200));
};

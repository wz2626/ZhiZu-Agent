// Layout behavior, not business doubles: assert viewport containment and actual
// independent scrolling in the mounted Vue workspace, including 200% reflow.
const frameExpression=`(()=>{
 const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,height:r.height,width:r.width}};
 return {w:innerWidth,h:innerHeight,rootHeight:document.documentElement.scrollHeight,rootWidth:document.documentElement.scrollWidth,
   x:scrollX,y:scrollY,app:rect('#app'),header:rect('.topbar'),footer:rect('#app>footer'),workspace:rect('#workspace')};
})()`;
function checkFrame(assert,r,label){
 assert.ok(r.rootHeight<=r.h+2,label+': no global vertical overflow '+JSON.stringify(r));
 assert.ok(r.rootWidth<=r.w+2,label+': no global horizontal overflow '+JSON.stringify(r));
 assert.equal(r.x,0);assert.equal(r.y,0);
 assert.ok(r.header.top>=-1&&r.header.bottom<=r.h,label+': header docked');
 assert.ok(r.footer.bottom<=r.h+1&&r.footer.bottom>=r.h-2,label+': footer docked '+JSON.stringify(r));
 assert.ok(r.workspace.height>60&&r.workspace.bottom<=r.footer.top+1,label+': remaining workspace is bounded');
}
module.exports=async function({cdp,click,pause,assert,pass,shot,stage}){
 const ev=s=>cdp.evaluate(s);
 if(stage==='frame'){checkFrame(assert,await ev(frameExpression),'populated responsive frame');return;}
 if(stage==='input'){
  for(const [w,h,zoom] of [[1920,1080,1],[1440,900,1],[1280,560,1],[960,720,1],[390,844,1],[1440,900,2]]){
   await cdp.send('Emulation.setDeviceMetricsOverride',{width:w,height:h,deviceScaleFactor:1,mobile:w===390});
   await ev(`document.body.style.zoom=${JSON.stringify(String(zoom))}`);await pause(100);
   checkFrame(assert,await ev(frameExpression),`input ${w}x${h} zoom ${zoom}`);
   if(w===1440&&zoom===1){
    assert.ok(await ev(`(()=>{const a=document.getElementById('analyze-contract').getBoundingClientRect(),p=document.getElementById('contract-scroll').getBoundingClientRect();return a.top>=p.top&&a.bottom<=p.bottom+1})()`),'Empty desktop fits the complete analysis action inside its pane');
    await shot('app-shell-empty-desktop');
   }
   if(w===390){
    for(const pane of ['risk','task','contract']){
     await click(`.pane-switcher [aria-controls="${pane==='risk'?'risk-navigation':pane==='task'?'task-panel':'dossier'}"]`);
     assert.equal(await ev('document.getElementById("workspace").dataset.activePane'),pane);
     assert.equal(await ev('document.querySelectorAll("#negotiation-draft").length'),1);
     checkFrame(assert,await ev(frameExpression),'mobile '+pane);
    }
    await shot('app-shell-empty-mobile');
   }
  }
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  await ev('document.body.style.zoom="1"');await pause(100);
  pass('App shell: empty input stays within the viewport at desktop, tablet, phone, short height and 200% reflow; mobile panes share one mounted Composer');
  return;
 }
 await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
 await ev('document.body.style.zoom="1"');await pause(100);
 if(await ev('getComputedStyle(document.getElementById("trace-console")).display!=="none"')){await click('#trace-toggle');await pause(80);}
 await cdp.send('Page.bringToFront');
 const before=await ev(frameExpression);checkFrame(assert,before,'populated');
 await ev(`(()=>{window.__shellPositions={task:document.getElementById('task-panel').scrollTop,risk:document.querySelector('.risk-items').scrollTop,contract:document.getElementById('contract-scroll').scrollTop};const p=document.createElement('div');p.id='shell-scroll-probe';p.setAttribute('aria-hidden','true');p.style.height='1600px';document.getElementById('contract-scroll').append(p);document.getElementById('contract-scroll').scrollTop=0;})()`);
 try{
  const point=await ev(`(()=>{const r=document.getElementById('contract-scroll').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
  await cdp.send('Input.dispatchMouseEvent',{type:'mouseWheel',...point,deltaX:0,deltaY:260});await pause(180);
  assert.ok(await ev('document.getElementById("contract-scroll").scrollTop>0'),'Wheel scrolls contract inside its own pane');
  assert.equal(await ev('document.getElementById("task-panel").scrollTop===window.__shellPositions.task&&document.querySelector(".risk-items").scrollTop===window.__shellPositions.risk'),true);
  const after=await ev(frameExpression);checkFrame(assert,after,'contract wheel');
  assert.deepEqual(after.header,before.header);assert.deepEqual(after.footer,before.footer);
  await ev('document.getElementById("contract-scroll").scrollTop=0;document.getElementById("contract-scroll").focus({preventScroll:true})');
  await cdp.send('Input.dispatchKeyEvent',{type:'keyDown',key:'PageDown',code:'PageDown',windowsVirtualKeyCode:34});
  await cdp.send('Input.dispatchKeyEvent',{type:'keyUp',key:'PageDown',code:'PageDown',windowsVirtualKeyCode:34});await pause(160);
  assert.ok(await ev('document.getElementById("contract-scroll").scrollTop>0'),'Keyboard scrolls the focused contract pane');
  checkFrame(assert,await ev(frameExpression),'contract keyboard');
 }finally{await ev(`document.getElementById('shell-scroll-probe')?.remove();document.getElementById('contract-scroll').scrollTop=window.__shellPositions.contract`);}
 pass('App shell: real wheel and keyboard scrolling are isolated to the contract; task, risk, header and footer positions stay unchanged');
 await ev('(()=>{const e=document.querySelector("#task-panel .task-detail-link");e.scrollIntoView({block:"nearest",behavior:"instant"});e.focus({preventScroll:true})})()');
 await click('#task-panel .task-detail-link');await pause(80);
 const drawer=await ev(`(()=>{const r=document.getElementById('trace-console').getBoundingClientRect(),f=document.querySelector('#app>footer').getBoundingClientRect();return {top:r.top,bottom:r.bottom,footerTop:f.top,active:document.activeElement.id}})()`);
 assert.ok(drawer.top>=0&&drawer.bottom<=drawer.footerTop+1,JSON.stringify(drawer));
 assert.equal(drawer.active,'trace-toggle');checkFrame(assert,await ev(frameExpression),'trace drawer');
 await shot('app-shell-trace-drawer');
 await cdp.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
 await cdp.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});await pause(80);
 assert.equal(await ev('getComputedStyle(document.getElementById("trace-console")).display'),'none');
 assert.equal(await ev('document.activeElement.classList.contains("task-detail-link")'),true);
 pass('App shell: processing details use a bounded nonmodal drawer, Escape restores focus, and the footer never moves');
 await ev('window.__shellComposer=document.getElementById("negotiation-draft")');
 await cdp.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await pause(100);
 await click('.pane-switcher [aria-controls="task-panel"]');
 await ev('document.getElementById("task-panel").scrollTop=120;window.__shellTaskScroll=document.getElementById("task-panel").scrollTop;window.__shellDraft=document.getElementById("negotiation-draft").value');
 for(const name of ['risk-navigation','dossier','task-panel']){await click(`.pane-switcher [aria-controls="${name}"]`);checkFrame(assert,await ev(frameExpression),'populated mobile '+name);}
 assert.equal(await ev('document.getElementById("task-panel").scrollTop'),await ev('window.__shellTaskScroll'));
 assert.equal(await ev('document.getElementById("negotiation-draft")===window.__shellComposer'),true);
 assert.equal(await ev('document.getElementById("negotiation-draft").value'),await ev('window.__shellDraft'));
 pass('App shell: mobile pane switching preserves task scroll position, input text and Composer identity without a page scrollbar');
 await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});await pause(80);
};

// V4 migration: retain factual polish; retired 3D/morph layout is not asserted.
module.exports=async function({cdp,pause,assert,pass}){
 const ev=e=>cdp.evaluate(e);
 const slots=await ev('({total:document.querySelectorAll(".round-slot").length,filled:document.querySelectorAll(".round-slot.is-filled").length,round:+document.getElementById("round-count").dataset.round})');
 assert.equal(slots.total,5);assert.equal(slots.filled,slots.round);
 assert.ok(await ev('getComputedStyle(document.getElementById("negotiation-score")).fontVariantNumeric.includes("tabular-nums")'));
 const values=await ev('[...document.querySelectorAll(".turn-change")].map(e=>({direction:e.dataset.direction,before:e.querySelector(".turn-before").textContent,after:e.querySelector(".turn-after").textContent,strike:e.querySelector(".turn-before").classList.contains("is-superseded")}))');
 assert.deepEqual(values,[{direction:'improved',before:'1000',after:'1500',strike:true}]);
 assert.equal(await ev('document.getElementById("latest-negotiation-result").dataset.effect'),'improved');
 assert.equal(await ev('getComputedStyle(document.getElementById("latest-negotiation-result"),"::before").pointerEvents'),'none');
 pass('Polish: real 1000→1500 improvement alone is struck through; five chips follow official rounds and numeric columns remain tabular');
 const rect=()=>ev('(()=>{const r=document.getElementById("send-negotiation").getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})()');
 const press=async()=>{
  await ev('document.getElementById("send-negotiation").scrollIntoView({block:"center",behavior:"instant"})');await pause(350);
  const before=await rect(),doc=await ev('document.documentElement.scrollHeight');
  await cdp.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:before.x+before.width/2,y:before.y+before.height/2});
  await cdp.send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',buttons:1,clickCount:1,x:before.x+before.width/2,y:before.y+before.height/2});await pause(160);const down=await rect();
  await cdp.send('Input.dispatchMouseEvent',{type:'mouseMoved',buttons:1,x:2,y:2});
  await cdp.send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',buttons:0,clickCount:1,x:2,y:2});await pause(180);
  assert.deepEqual(await rect(),before);assert.equal(await ev('document.documentElement.scrollHeight'),doc);return down.y-before.y;
 };
 await cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'no-preference'}]});await pause(50);assert.ok(Math.abs(await press()-1)<.1);
 await cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});await pause(50);assert.equal(await press(),0);
 await cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'no-preference'}]});
 await cdp.send('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:1});await pause(50);assert.equal(await press(),0);
 assert.equal(await ev('getComputedStyle(document.querySelector(".shortcut-hint")).display'),'none');
 await cdp.send('Emulation.setTouchEmulationEnabled',{enabled:false});
 pass('Polish: trusted desktop press moves exactly 1px without reflow; release, reduced-motion and touch are static');
};

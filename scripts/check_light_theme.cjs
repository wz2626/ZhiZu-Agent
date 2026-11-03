// Check rendered text against its actual ancestor surfaces, including gradient
// endpoints and alpha. Disabled controls and decorative/hidden text are excluded.
module.exports=async function({cdp,assert,pass,label='workspace'}){
 const audit=await cdp.evaluate(`(()=>{
  const parse=s=>{const m=s.match(/^rgba?\\(([^)]+)\\)$/);if(!m)return null;const a=m[1].split(/[, /]+/).filter(Boolean).map(Number);return [a[0],a[1],a[2],a[3]??1]};
  const over=(a,b)=>[0,1,2].map(i=>a[i]*a[3]+b[i]*(1-a[3])).concat(1);
  const lum=c=>c.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
  const contrast=(a,b)=>{const x=lum(a),y=lum(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)};
  const backgrounds=e=>{const chain=[];for(let p=e;p;p=p.parentElement)chain.unshift(p);let options=[[255,255,255,1]];
   for(const p of chain){const s=getComputedStyle(p),solid=parse(s.backgroundColor)||[0,0,0,0];options=options.map(bg=>over(solid,bg));const colors=(s.backgroundImage.match(/rgba?\\([^)]*\\)/g)||[]).map(parse).filter(Boolean);if(colors.length)options=options.flatMap(bg=>colors.map(c=>over(c,bg)));}return options;
  };
  const failures=[];let checked=0,min=100;
  const check=(e,text,color)=>{if(!e.getClientRects().length||e.closest('[inert],[aria-hidden=true],button:disabled,option,svg,script,style'))return;const s=getComputedStyle(e);if(s.visibility!=='visible')return;let alpha=1;for(let p=e;p;p=p.parentElement)alpha*=Number(getComputedStyle(p).opacity);if(alpha===0)return;
   const fg=parse(color||s.color);if(!fg)return;fg[3]*=alpha;const ratio=Math.min(...backgrounds(e).map(bg=>contrast(over(fg,bg),bg)));const large=Number.parseFloat(s.fontSize)>=24||(Number.parseFloat(s.fontSize)>=18.66&&Number(s.fontWeight)>=700);checked++;min=Math.min(min,ratio);if(ratio+.01<(large?3:4.5))failures.push({text:text.trim().slice(0,50),selector:e.id||e.className,ratio:+ratio.toFixed(2),color:color||s.color});
  };
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);while(walker.nextNode()){const n=walker.currentNode;if(n.textContent.trim())check(n.parentElement,n.textContent);}
  for(const e of document.querySelectorAll('textarea[placeholder]'))if(!e.value)check(e,e.placeholder,getComputedStyle(e,'::placeholder').color);
  return {scheme:getComputedStyle(document.documentElement).colorScheme,checked,min:+min.toFixed(2),failures};
 })()`);
 assert.equal(audit.scheme,'light');assert.ok(audit.checked>20,JSON.stringify(audit));
 assert.deepEqual(audit.failures,[],JSON.stringify(audit.failures));
 pass(`Light theme ${label}: ${audit.checked} rendered text samples meet contrast thresholds; minimum ${audit.min}:1`);
 return audit;
};

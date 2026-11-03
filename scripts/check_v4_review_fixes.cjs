// Real service-instance reset, plus explicitly labelled protocol/policy fixtures.
module.exports=async function({cdp,click,fill,until,pause,assert,requests,pass}){
 const ev=e=>cdp.evaluate(e),round=n=>`document.getElementById('round-count').dataset.round==='${n}'`;
 await ev(`window.__reviewFetch=window.fetch;window.__turnCalls=[];window.__conflictCode=null;window.__policyFixture='';window.__previewNext=false;
 window.fetch=async(url,options)=>{
  if(String(url)==='/api/negotiation/turn'){
   window.__turnCalls.push({body:JSON.parse(options.body),epoch:new Headers(options.headers).get('X-Practice-Epoch')});
   if(window.__previewNext){window.__previewNext=false;const meta=await window.__reviewFetch('/api/negotiation/meta').then(r=>r.json());return new Response(JSON.stringify({detail:{code:'PRIVACY_PREVIEW_REQUIRED',privacy_policy_version:meta.privacy_policy.version,fields:[{field:'user_input',safe_text:'服务端补充处理后的***',counts:{phone:1,id:0},spans:[]}]}}),{status:428,headers:{'Content-Type':'application/json'}});}
   if(window.__conflictCode){const code=window.__conflictCode;window.__conflictCode=null;return new Response(JSON.stringify({detail:{code,message:'explicit protocol fixture'}}),{status:409,headers:{'Content-Type':'application/json'}});}
  }
  const response=await window.__reviewFetch(url,options);
  if(String(url)==='/api/negotiation/meta'&&window.__policyFixture){const meta=await response.json();
   if(window.__policyFixture==='incompatible')meta.privacy_policy.engine='future-incompatible-engine';
   else {meta.privacy_policy_version=meta.privacy_policy.version='compatible-policy-upgrade-test';meta.privacy_policy.ignored_points.push(0x2063);meta.privacy_policy.space_points.push(0x205f);meta.privacy_policy.char_map['64']='1';const old=meta.privacy_policy.separator_pattern,next=old.replaceAll('-','[.-]');for(const field of ['phone_pattern','id_pattern'])meta.privacy_policy[field]=meta.privacy_policy[field].replaceAll(old,next);meta.privacy_policy.separator_pattern=next;}
   return new Response(JSON.stringify(meta),{status:200,headers:{'Content-Type':'application/json'}});
  }return response;
 };`);
 try{
  const oldEpoch=await ev(`window.__reviewFetch('/api/negotiation/meta').then(r=>r.json()).then(r=>r.practice_epoch)`);
  const oldKey=await ev(`document.querySelector('[aria-label=查看练习记录]').value`);
  const oldRound=await ev(`document.getElementById('round-count').dataset.round`);
  const restarted=await ev(`window.__reviewFetch('/_test/restart-practice',{method:'POST'}).then(r=>r.json())`);
  assert.notEqual(restarted.practice_epoch,oldEpoch);
  await fill('negotiation-draft','服务重启后仍保留的旧消息');await click('#send-negotiation');
  await until(`document.getElementById('negotiation-error')?.textContent.includes('已失效')&&!document.getElementById('new-practice').disabled`,'old instance invalid, new practice enabled');
  assert.equal(await ev('window.__turnCalls.at(-1).epoch'),oldEpoch);
  assert.equal(await ev(`document.getElementById('round-count').dataset.round`),oldRound);
  assert.equal(await ev(`document.getElementById('recover-negotiation').disabled`),true);
  await click('#new-practice');const newKey=await ev(`document.querySelector('[aria-label=查看练习记录]').value`);
  await fill('negotiation-draft','新实例中的第一轮');await until(`!document.getElementById('send-negotiation').disabled`,'new instance service ready');await click('#send-negotiation');
  await until(round(1),'new practice starts without refreshing the page');
  const calls=await ev('window.__turnCalls');assert.equal(calls.at(-1).epoch,restarted.practice_epoch);assert.notEqual(calls.at(-1).body.session_id,calls.at(-2).body.session_id);
  await ev(`(()=>{const e=document.querySelector('[aria-label=查看练习记录]');e.value=${JSON.stringify(oldKey)};e.dispatchEvent(new Event('change',{bubbles:true}));})()`);await pause(30);
  assert.equal(await ev(`document.getElementById('recovery-message').textContent`),'服务重启后仍保留的旧消息');
  assert.equal(await ev(`document.getElementById('recover-negotiation').disabled`),true);
  assert.equal(await ev(`document.getElementById('round-count').dataset.round`),oldRound);
  await ev(`(()=>{const e=document.querySelector('[aria-label=查看练习记录]');e.value=${JSON.stringify(newKey)};e.dispatchEvent(new Event('change',{bubbles:true}));})()`);await pause(30);
  pass('Real practice instance reset preserves old snapshot/epoch and starts a new practice without page refresh');

  await fill('negotiation-draft','编号冲突后继续使用本练习');await ev(`window.__conflictCode='REQUEST_CONFLICT'`);await click('#send-negotiation');
  await until(`document.getElementById('negotiation-error')?.textContent.includes('编号已被不同内容使用')`,'request conflict guidance');
  assert.equal(await ev(`!!document.getElementById('recover-negotiation')`),false);assert.equal(await ev(`document.getElementById('send-negotiation').disabled`),false);
  const rejected=await ev('window.__turnCalls.at(-1).body');await click('#send-negotiation');await until(round(2),'request conflict permits new ID on same session');
  const accepted=await ev('window.__turnCalls.at(-1).body');assert.equal(accepted.session_id,rejected.session_id);assert.notEqual(accepted.request_id,rejected.request_id);
  pass('REQUEST_CONFLICT retains the live practice and input; next explicit action uses a new request ID');

  await fill('negotiation-draft','协议恢复后继续第三轮');await ev(`window.__conflictCode='INTERACTION_VERSION'`);await click('#send-negotiation');
  await until(`!!document.getElementById('retry-negotiation-api')`,'protocol recheck is actionable');
  assert.equal(await ev(`!!document.getElementById('recover-negotiation')`),false);
  await click('#retry-negotiation-api');await until(`!document.getElementById('send-negotiation').disabled`,'protocol restored');
  await click('#send-negotiation');await until(round(3),'same practice remains valid after protocol recheck');
  assert.equal(await ev('window.__turnCalls.at(-1).body.session_id'),accepted.session_id);
  pass('INTERACTION_VERSION requests a service/protocol recheck without invalidating the practice');

  await click('#new-practice');const freshRestart=await ev(`window.__reviewFetch('/_test/restart-practice',{method:'POST'}).then(r=>r.json())`);
  await fill('negotiation-draft','尚未发送的新练习自动读取当前实例');const count=await ev('window.__turnCalls.length');await click('#send-negotiation');await until(round(1),'pristine practice refreshes epoch before first dispatch');
  assert.equal(await ev('window.__turnCalls.length'),count+1);assert.equal(await ev('window.__turnCalls.at(-1).epoch'),freshRestart.practice_epoch);
  pass('A pristine practice created before restart binds the current instance on first dispatch');

  await click('#new-practice');await fill('negotiation-draft','需要后端补充预览的消息');await ev(`window.__previewNext=true`);
  await click('#send-negotiation');await until(`document.getElementById('negotiation-draft').value==='服务端补充处理后的***'`,'server preview is adopted using the active policy version');
  assert.equal(await ev(`document.getElementById('round-count').dataset.round`),'0');
  await until(`!document.getElementById('send-negotiation').disabled`,'server preview is ready for explicit confirmation');await click('#send-negotiation');await until(round(1),'second action sends server preview');
  assert.equal(await ev('window.__turnCalls.at(-1).body.user_input'),'服务端补充处理后的***');
  pass('428 uses the active policy version, reveals safe content and requires a second explicit action');

  await click('#new-practice');await ev(`window.__policyFixture='upgrade'`);
  await fill('negotiation-draft','@38\u2063.0000\u205f0000');await pause(600);
  const before=await ev('window.__turnCalls.length');await click('#send-negotiation');
  await until(`document.getElementById('negotiation-draft').value==='***'`,'updated complete policy masks in place');
  assert.equal(await ev('window.__turnCalls.length'),before);
  await until(`!document.getElementById('send-negotiation').disabled`,'new policy preview ready');await click('#send-negotiation');await until(round(1),'compatible policy upgrade sends safe visible text');
  assert.equal(await ev('window.__turnCalls.at(-1).body.user_input'),'***');
  pass('Compatible policy version/data upgrade is consumed in-page; new masking is visible before any POST');

  await click('#new-practice');await ev(`window.__policyFixture='incompatible'`);await fill('negotiation-draft','不兼容引擎不会发送这条消息');
  const beforeIncompatible=await ev('window.__turnCalls.length');await click('#send-negotiation');
  await until(`document.getElementById('negotiation-api-status')?.textContent.includes('升级两端')`,'unsupported engine has explicit upgrade guidance');
  assert.equal(await ev('window.__turnCalls.length'),beforeIncompatible);
  assert.equal(await ev(`document.getElementById('negotiation-draft').value`),'不兼容引擎不会发送这条消息');
  await ev(`window.__policyFixture=''`);await click('#retry-negotiation-api');await until(`!document.getElementById('send-negotiation').disabled`,'compatible engine restores without page reload');
  pass('An incompatible privacy engine blocks transmission with upgrade guidance and preserves the input');
 }finally{await ev(`window.fetch=window.__reviewFetch;delete window.__reviewFetch;delete window.__policyFixture;delete window.__conflictCode;`);}
};

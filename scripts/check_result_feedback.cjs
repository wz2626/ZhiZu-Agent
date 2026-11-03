// Actual fixed-graph HTTP turns; the browser deliberately holds/drops responses
// after the local server has executed. No synthetic scores or conditions.
module.exports=async function({cdp,click,fill,until,pause,assert,pass,mode}){
  const ev=expression=>cdp.evaluate(expression);
  const pane=async label=>ev(`[...document.querySelectorAll('.task-tabs button')].find(b=>b.textContent===${JSON.stringify(label)}).click()`);
  const round=()=>ev('Number(document.getElementById("round-count").dataset.round)');
  const snapshot=()=>ev('({round:document.getElementById("round-count").dataset.round,score:document.getElementById("negotiation-score").textContent,terms:document.getElementById("confirmed-terms").textContent})');
  await mode('normal');
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  await cdp.send('Emulation.setTouchEmulationEnabled',{enabled:false});
  await cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'no-preference'}]});
  await cdp.send('Page.navigate',{url:await ev('location.origin')});await cdp.send('Page.bringToFront');
  await until('!!window.__zhizuLayoutDiagnostics?.length && !document.querySelector("#dossier .notice-warn")','feedback workspace ready');
  await fill('contract-input','房屋租赁合同。租赁结束后可不说明理由直接扣留全部押金。\n维修责任和费用均由租客承担。\n提前退租须支付固定违约金2000元。');
  await click('#analyze-contract');await until('document.querySelectorAll("#risk-navigation [data-clause]").length===3','real offline review');
  await click('[data-clause="C-01"]');await click('#prepare-communication');await fill('scenario-select','deposit','change');
  assert.equal(await ev('document.getElementById("app").classList.contains("motion-ready")'),true);
  await ev(`(()=>{
    window.__feedbackNativeFetch=window.fetch;window.__feedbackRequests=[];window.__feedbackMarks=[];window.__feedbackAnimations=[];
    window.fetch=async(url,options)=>{
      if(new URL(url,location.href).pathname!=='/api/negotiation/turn')return window.__feedbackNativeFetch(url,options);
      const entry={body:JSON.parse(options.body),headers:Object.fromEntries(new Headers(options.headers)),ready:false};
      window.__feedbackRequests.push(entry);
      const response=await window.__feedbackNativeFetch(url,options);
      entry.data=await response.clone().json();
      await new Promise(resolve=>{entry.release=(drop=false)=>{entry.drop=drop;resolve();};entry.ready=true;});
      if(entry.drop)throw new Error('Explicit client-side response loss after real server execution');
      return response;
    };
    window.__feedbackObserver=new MutationObserver(records=>{
      for(const {target} of records){
        if(target.id==='latest-negotiation-result'&&target.classList.contains('result-arrived')||target.id==='landlord-persona'&&target.classList.contains('pulse'))
          window.__feedbackMarks.push({id:target.id,visible:target.getClientRects().length>0});
      }
    });
    window.__feedbackObserver.observe(document.getElementById('workspace'),{attributes:true,attributeFilter:['class'],subtree:true});
    document.addEventListener('animationstart',event=>{
      if(event.target.id==='latest-negotiation-result'||event.target.id==='landlord-persona')
        window.__feedbackAnimations.push({id:event.target.id,name:event.animationName,visible:event.target.getClientRects().length>0});
    });
  })()`);
  const reset=()=>ev('window.__feedbackMarks=[];window.__feedbackAnimations=[]');
  const begin=async text=>{
    await pane('准备沟通消息');await fill('negotiation-draft',text);await reset();
    const index=await ev('window.__feedbackRequests.length');await click('#send-negotiation');return index;
  };
  const held=index=>until(`window.__feedbackRequests[${index}]?.ready`,'real response held');
  const release=(index,drop=false)=>ev(`window.__feedbackRequests[${index}].release(${drop})`);
  const noCardCue=async()=>{
    assert.deepEqual(await ev('window.__feedbackMarks'),[]);
    assert.equal(await ev('document.getElementById("latest-negotiation-result").classList.contains("result-arrived")'),false);
    assert.equal(await ev('document.getElementById("landlord-persona").classList.contains("pulse")'),false);
  };
  try{
    let index=await begin('请核对押金扣减明细。');await held(index);await release(index);
    await until('document.getElementById("round-count").dataset.round==="1" && !!document.getElementById("submission-recorded")','communication acknowledgement');
    assert.equal(await ev('document.getElementById("submission-recorded").getClientRects().length>0'),true);
    await noCardCue();
    pass('Feedback: communication receives a visible acknowledgement and never starts hidden card/persona effects');

    // Start the next turn directly in the same pane while the old badge is live.
    // No tab switch may accidentally clear the cue on the dispatch path's behalf.
    assert.equal(await ev('!!document.getElementById("submission-recorded")'),true);
    await fill('negotiation-draft','请进一步核对押金返还安排。');await reset();
    index=await ev('window.__feedbackRequests.length');await click('#send-negotiation');
    assert.equal(await ev('!!document.getElementById("submission-recorded")'),false);
    await pane('练习结果与清单');await held(index);await release(index);
    await until('document.getElementById("round-count").dataset.round==="2" && document.getElementById("latest-negotiation-result").classList.contains("result-arrived")','visible result acknowledgement');
    await until('window.__feedbackAnimations.some(e=>e.name==="record-confirm") && window.__feedbackAnimations.some(e=>e.name==="persona-confirm")','visible card animations');
    const marks=await ev('window.__feedbackMarks');assert.ok(marks.length>=2);assert.ok(marks.every(entry=>entry.visible),JSON.stringify(marks));
    assert.equal(await ev('!!document.getElementById("submission-recorded")'),false);
    pass('Feedback: a turn sent from communication and received on the result pane animates only the visible card/persona');

    await pane('准备沟通消息');await reset();await pane('练习结果与清单');await pause(120);await noCardCue();
    await pane('准备沟通消息');assert.equal(await ev('!!document.getElementById("submission-recorded")'),false);
    pass('Feedback: changing panes after acknowledgement never replays the old success cue');

    index=await begin('请确认最终返还条件。');await click('[data-clause="C-02"]');await click('#prepare-communication');await fill('scenario-select','maintenance','change');
    await held(index);await release(index);await until('!document.getElementById("new-practice").disabled','background owner completed');await pause(80);
    assert.equal(await round(),0);await noCardCue();assert.equal(await ev('!!document.getElementById("submission-recorded")'),false);
    await click('[data-clause="C-01"]');await click('#prepare-communication');await until('document.getElementById("round-count").dataset.round==="3"','original owner restored');
    await pane('练习结果与清单');await pause(80);await noCardCue();
    assert.equal(await ev('!!document.getElementById("submission-recorded")'),false);
    pass('Feedback: real background completion stays with its owner and does not replay on history return');

    const before=await snapshot();index=await begin('请书面记录返还条件。');await held(index);await release(index,true);
    await until('!!document.getElementById("recover-negotiation")','lost real response');assert.deepEqual(await snapshot(),before);await noCardCue();
    const retry=await ev('window.__feedbackRequests.length');await click('#recover-negotiation');await pane('练习结果与清单');await held(retry);
    assert.deepEqual(await ev(`window.__feedbackRequests[${retry}].body`),await ev(`window.__feedbackRequests[${index}].body`));
    assert.deepEqual(await ev(`window.__feedbackRequests[${retry}].headers`),await ev(`window.__feedbackRequests[${index}].headers`));
    assert.equal(await ev(`window.__feedbackRequests[${retry}].data.replayed`),true);
    await release(retry);await until('document.getElementById("round-count").dataset.round==="4"','canonical replay applied');await pause(80);
    await noCardCue();assert.equal(await ev('!!document.getElementById("submission-recorded")'),false);
    pass('Feedback: dropped real response recovers by identical request and headers; canonical replay advances once without success effects');

    await mode('critic_failure');const formal=await snapshot();index=await begin('请再次核对相关凭证。');await pane('练习结果与清单');await held(index);
    assert.equal(await ev(`window.__feedbackRequests[${index}].data.status`),'needs_review');
    await release(index);await until('!!document.getElementById("negotiation-error")','real critic rejection');await pause(60);
    assert.deepEqual(await snapshot(),formal);await noCardCue();assert.equal(await ev('!!document.getElementById("submission-recorded")'),false);
    pass('Feedback: real Critic rejection preserves formal state and produces no completion cue');
  }finally{
    await ev('window.fetch=window.__feedbackNativeFetch;window.__feedbackObserver.disconnect()');
    await mode('normal');
  }
};

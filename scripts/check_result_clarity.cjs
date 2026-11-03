// Product-level result flow: personal goals remain separate from the actual
// fixed-engine outcome; preparation alone never runs a negotiation turn.
module.exports=async({cdp,click,fill,until,pause,assert,pass,shot,requests})=>{
  const ev=e=>cdp.evaluate(e);
  const tab=async label=>{await ev(`[...document.querySelectorAll('.task-tabs button')].find(b=>b.textContent===${JSON.stringify(label)}).click()`);await pause(40);};
  const result=()=>tab('练习结果与清单'),message=()=>tab('准备沟通消息');
  const turns=()=>requests.filter(r=>r.path==='/api/negotiation/turn').length;
  const copy=async()=>{await click('#export-checklist');await until('!!window.__clarityCopies.length','checklist copied');return ev('window.__clarityCopies.at(-1)');};
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  await cdp.send('Page.navigate',{url:await ev('location.origin')});
  await until('!!window.__zhizuLayoutDiagnostics?.length','clarity workspace');
  await fill('contract-input','房屋租赁合同。租赁结束后可不说明理由直接扣留全部押金。\n维修责任和费用均由租客承担。\n提前退租须支付固定违约金2000元。');
  await click('#analyze-contract');await until('document.querySelectorAll("#risk-navigation [data-clause]").length===3','review ready');
  await click('[data-clause="C-01"]');await click('#prepare-communication');
  const goal='签约前希望把预交押金降至1500元，并约定租期结束后3日内返还。';
  const draft='您好，签约前我想商量：押金调整为1500元，租期结束后3日内退还。';
  await fill('proposal-goal',goal);await fill('negotiation-draft',draft);
  await ev('window.__clarityClipboard=Object.getOwnPropertyDescriptor(navigator,"clipboard");window.__clarityCopies=[];Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async text=>window.__clarityCopies.push(text)}})');
  try{
    const initial=turns();
    assert.equal(await ev('!!document.getElementById("practice-scope")'),false);
    assert.equal(await ev('!!document.getElementById("prepare-checklist-direct")'),false);
    await result();
    assert.equal(await ev('document.getElementById("my-checklist").checkVisibility()'),true);
    assert.equal(await ev('document.getElementById("checklist-scope-note").checkVisibility()'),false);
    assert.equal(turns(),initial);assert.equal(await ev('document.getElementById("round-count").dataset.round'),'0');
    assert.equal(await ev('document.getElementById("negotiation-draft").value'),draft);
    assert.equal(await ev('document.getElementById("checklist-goal").textContent'),goal);
    assert.equal(await ev('document.getElementById("checklist-prepared-message").textContent.includes("尚未提交")'),true);
    let text=await copy();assert.ok(text.includes(goal));assert.ok(text.includes(draft));assert.ok(text.includes('当前准备的消息（尚未提交'));
    assert.ok(!text.slice(text.indexOf('## 已确认条件'),text.indexOf('## 待明确事项')).includes('1500'));
    pass('Result clarity: a single existing result tab preserves goal/message with zero turn calls, no redundant shortcut, and explicit fixed-refund scope');

    await message();await click('#send-negotiation');await until('document.getElementById("round-count").dataset.round==="1"','real first turn');await result();
    assert.ok(await ev('document.getElementById("confirmed-terms").textContent.includes("1000")'));
    assert.equal(await ev('document.getElementById("confirmed-result").closest("#latest-negotiation-result")!==null'),true);
    assert.equal(await ev('document.querySelectorAll("#confirmed-terms").length'),1);
    assert.equal(await ev('!!document.getElementById("previous-round-result")'),false);
    assert.equal(await ev('document.getElementById("simulation-progress").open'),false);
    assert.equal(await ev('document.getElementById("negotiation-score").textContent'),'50 / 100');
    assert.equal(await ev('document.getElementById("communication-ledger").open'),false);
    assert.ok(await ev('document.getElementById("latest-negotiation-result").textContent.includes("不会逐项答复")'));
    await click('#simulation-progress>summary');
    assert.ok(await ev('document.getElementById("score-meaning").checkVisibility() && document.getElementById("score-meaning").textContent.includes("2000元") && document.getElementById("score-meaning").textContent.includes("不表示你的全部诉求已实现")'));
    assert.ok(await ev('document.getElementById("checklist-scope-note").checkVisibility() && document.getElementById("checklist-scope-note").textContent.includes("签约前降低预交押金")'));
    await click('#simulation-progress>summary');
    assert.equal(await ev('document.getElementById("checklist-goal").textContent'),goal);
    await ev('document.getElementById("task-panel").scrollTop=0');
    if(shot)await shot('clarity-first-result-desktop',false);
    pass('Result clarity: one response contains official terms; first round has no fake round-zero history; scoring is secondary and explains the preset target while the personal goal stays intact');

    await click('#negotiation-more>summary');
    await fill('unresolved-requests','请确认1500元押金及3日内返还，尚未达成一致。');
    await fill('missing-facts','准备合同修订稿和付款记录。');
    text=await copy();
    const confirmed=text.slice(text.indexOf('## 已确认条件'),text.indexOf('## 待明确事项'));
    assert.ok(confirmed.includes('1000'));assert.ok(!confirmed.includes('1500'));assert.ok(!confirmed.includes('3日'));
    assert.ok(text.includes('### 自行补充（待确认）\n- 请确认1500元押金及3日内返还，尚未达成一致。'));
    assert.ok(text.includes('### 自行补充（待核实）\n- 准备合同修订稿和付款记录。'));
    assert.ok(text.includes('用户表达'));assert.ok(text.includes('固定演练范围'));
    assert.equal(turns(),initial+1);
    await message();assert.equal(await ev('!!document.getElementById("prepare-checklist-direct")'),false);await result();
    pass('Result clarity: copied checklist separates the actual 1000 refund from the requested 1500 deposit and 3-day deadline, retaining manual follow-ups without extra requests');

    await click('[data-clause="C-02"]');await click('#prepare-communication');await fill('proposal-goal','维修场景的独立目标：请修好漏水。');await fill('negotiation-draft','请安排维修。');
    await result();assert.equal(await ev('document.getElementById("my-checklist").checkVisibility()'),true);
    text=await copy();assert.ok(text.includes('维修场景的独立目标'));assert.ok(!text.includes(goal));assert.ok(!text.includes('请确认1500元押金及3日内返还'));
    await click('[data-clause="C-01"]');await click('#prepare-communication');await result();
    assert.equal(await ev('document.getElementById("checklist-goal").textContent'),goal);
    for(let round=2;round<=5;round++){
      await message();await fill('negotiation-draft','请继续核对押金返还金额。');await click('#send-negotiation');
      await until(`document.getElementById('round-count').dataset.round==='${round}'`,'clarity round '+round);await result();
      assert.equal(await ev('document.getElementById("negotiation-score").textContent'),(round===2?'75':'100')+' / 100');
      assert.ok(await ev(`document.getElementById('previous-round-result').textContent.includes('第 ${round-1} 轮')`));
    }
    assert.equal(await ev('document.getElementById("send-negotiation").disabled'),true);
    assert.ok(await ev('document.getElementById("confirmed-result").textContent.includes("最终报价档")'));
    for(const width of [1440,390]){
      await cdp.send('Emulation.setDeviceMetricsOverride',{width,height:width===390?844:900,deviceScaleFactor:1,mobile:width===390});
      await ev('document.getElementById("latest-negotiation-result").scrollIntoView({block:"start",behavior:"instant"})');await pause(80);
      assert.ok(await ev('document.documentElement.scrollWidth<=innerWidth+2'));
      if(shot)await shot('clarity-final-result-'+width,false);
      await ev('document.getElementById("export-checklist").scrollIntoView({block:"center",behavior:"instant"})');
      assert.ok(await ev('document.getElementById("export-checklist").getBoundingClientRect().bottom<=innerHeight'));
    }
    pass('Result clarity: goals and checklist additions stay clause-local; real five-round progression, final-offer notice and desktop/phone access remain correct');
  }finally{
    await ev('if(window.__clarityClipboard)Object.defineProperty(navigator,"clipboard",window.__clarityClipboard);else delete navigator.clipboard');
    await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  }
};

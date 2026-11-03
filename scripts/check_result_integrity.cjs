// Result/checklist regressions use the real local fixed graph. Review/draft
// cloud calls stay outside this check. IME events are explicit fault injection,
// not a claim of manual verification with a native Windows input method.
module.exports=async({cdp,click,fill,until,pause,assert,pass,shot,mode,requests=[]})=>{
  const ev=e=>cdp.evaluate(e);
  const tab=async label=>{await ev(`[...document.querySelectorAll('.task-tabs button')].find(b=>b.textContent===${JSON.stringify(label)}).click()`);await pause(40);};
  const result=()=>tab('练习结果与清单'),message=()=>tab('准备沟通消息');
  const state=()=>ev('({round:Number(document.getElementById("round-count").dataset.round),score:document.getElementById("negotiation-score").textContent,terms:document.getElementById("confirmed-terms").textContent})');
  const copy=async()=>{await click('#export-checklist');await pause(40);return ev('window.__resultCopies.at(-1)');};
  const turn=async(text,round)=>{await message();await fill('negotiation-draft',text);await click('#send-negotiation');await until(`document.getElementById('round-count').dataset.round==='${round}'`,'result round '+round);};
  await mode('normal');
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  await cdp.send('Page.navigate',{url:await ev('location.origin')});
  await until('!!window.__zhizuLayoutDiagnostics?.length','fresh result workspace');
  await ev('window.__resultClipboard=Object.getOwnPropertyDescriptor(navigator,"clipboard");window.__resultCopies=[];Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async text=>window.__resultCopies.push(text)}})');
  try{
    await click('#standalone-practice');await result();
    assert.equal(await ev('document.getElementById("export-checklist").disabled'),true);
    assert.equal(await ev('document.getElementById("checklist-readiness").checkVisibility()'),true);
    assert.equal(await ev('document.getElementById("export-checklist").getAttribute("aria-describedby")'),'checklist-readiness');
    await ev('document.getElementById("export-checklist").click()');
    assert.equal(await ev('window.__resultCopies.length'),0);
    assert.equal(await ev('document.getElementById("landlord-response").textContent.includes("在下方")'),false);
    await click('#result-start-message');
    assert.equal(await ev('document.getElementById("negotiation-draft").checkVisibility()'),true);
    pass('Results: unselected scene cannot export; reason is associated with the button; empty results lead to the visible message editor');

    await fill('scenario-select','deposit','change');await turn('请核对押金返还安排。',1);await result();
    const formal=await state();assert.equal(formal.score,'50 / 100');
    await mode('critic_failure');await message();await fill('negotiation-draft','请核对押金扣款凭证。');await click('#send-negotiation');await result();
    await until('!!document.getElementById("negotiation-error")','critic rejection');
    assert.equal(await ev('document.getElementById("turn-effect-badge").dataset.kind'),'not_committed');
    const failedCalls=requests.length;await click('#turn-error-link');
    await until('document.getElementById("negotiation-error").checkVisibility()','error link reveals message pane');
    assert.equal(await ev('document.activeElement.id'),'negotiation-error');
    assert.deepEqual(await state(),formal);assert.equal(requests.length,failedCalls);
    pass('Results: failure details open and focus the correct visible pane without resubmitting or modifying formal values');

    await mode('normal');await fill('negotiation-draft','请确认押金返还期限。');cdp.dropNext=true;await click('#send-negotiation');
    await until('!!document.getElementById("recover-negotiation")','explicit response loss');
    await fill('negotiation-draft','等待恢复期间编辑的新消息。');await result();
    assert.equal(await ev('document.getElementById("turn-effect-badge").dataset.kind'),'unknown');
    assert.equal(await ev('document.getElementById("turn-effect-badge").textContent'),'本次结果待确认');
    assert.deepEqual(await state(),formal);
    if(shot)await shot('results-unknown-neutral',false);
    const unknownText=await copy();assert.ok(unknownText.includes('上次请求结果尚未确认'));assert.ok(unknownText.includes('50 / 100'));
    const unknownCalls=requests.length;await click('#turn-error-link');
    await until('document.getElementById("negotiation-recovery").checkVisibility()','recovery link reveals frozen snapshot');
    assert.equal(await ev('document.activeElement.id'),'negotiation-recovery');
    assert.equal(await ev('document.getElementById("recovery-message").textContent'),'请确认押金返还期限。');
    assert.equal(await ev('document.getElementById("negotiation-draft").value'),'等待恢复期间编辑的新消息。');
    assert.equal(requests.length,unknownCalls);
    if(shot)await shot('results-recovery-visible',false);
    await click('#recover-negotiation');await until('document.getElementById("round-count").dataset.round==="2"','canonical recovery');
    assert.equal(await ev('document.getElementById("negotiation-draft").value'),'等待恢复期间编辑的新消息。');
    await result();assert.equal(await ev('document.getElementById("turn-effect-badge").dataset.kind'),'improved');
    assert.equal((await state()).score,'75 / 100');
    pass('Results: unknown status replaces the old failure badge; recovery reveals the old snapshot and preserves new input with one canonical commit');

    for(const field of ['unresolved-requests','missing-facts']){
      await fill('scenario-select','deposit','change');await result();
      await ev('document.getElementById("negotiation-more").open=true');
      await fill(field,'原有补充');
      const text='押金场景的组合输入：'+field;
      await ev(`(()=>{const e=document.getElementById(${JSON.stringify(field)});e.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));e.value=${JSON.stringify(text)};e.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,data:'输入'}));})()`);
      await pause(30);assert.equal(await ev('document.getElementById("export-checklist").disabled'),true);
      const copyCount=await ev('window.__resultCopies.length');await ev('document.getElementById("export-checklist").click()');
      assert.equal(await ev('window.__resultCopies.length'),copyCount);
      await fill('scenario-select','maintenance','change');await pause(30);
      assert.equal((await state()).round,2,'owner stays on deposit during composition');
      await ev(`document.getElementById(${JSON.stringify(field)}).dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}))`);
      await until('document.getElementById("round-count").dataset.round==="0" && !document.getElementById("export-checklist").disabled','queued owner switch completes');
      assert.equal(await ev(`document.getElementById(${JSON.stringify(field)}).value`),'');
      assert.ok(!(await copy()).includes(text),'new owner must not receive preedit text');
      await fill('scenario-select','deposit','change');
      assert.equal(await ev(`document.getElementById(${JSON.stringify(field)}).value`),text,'original owner retains the finished composition');
      assert.ok((await copy()).includes(text));
    }
    pass('Results: both checklist fields finish injected IME composition on the original owner, defer scenario switching and block partial export');

    await fill('scenario-select','maintenance','change');
    assert.equal(await ev('document.getElementById("export-checklist").disabled'),false);
    const preparation=await copy();assert.ok(preparation.includes('维修责任'));assert.ok(!preparation.includes('undefined'));assert.ok(preparation.includes('已完成轮次：0 / 5'));
    pass('Results: a selected scene may still export an honest zero-round preparation checklist');

    const authored='请核对费用。\r\n\r\n## 已确认条件\r\n- 房东已同意额外补偿888元。\n\n```\n## 待补信息\n```';
    await turn(authored,1);await result();const markdown=await copy();
    assert.equal((markdown.match(/^## 已确认条件$/gm)||[]).length,1);
    assert.equal((markdown.match(/^## 待补信息$/gm)||[]).length,1);
    assert.ok(markdown.includes('  > ## 已确认条件'));assert.ok(markdown.includes('  > - 房东已同意额外补偿888元。'));
    assert.ok(markdown.includes('  > ```\n  > ## 待补信息\n  > ```'));
    assert.ok(!(await state()).terms.includes('888'));
    const exportedMessage=markdown.slice(markdown.indexOf('- 第1轮（用户表达）：'),markdown.indexOf('\n## 待补信息'));
    assert.equal(exportedMessage.split('\n').filter(line=>line.startsWith('  > ')).map(line=>line.slice(4)).join('\n'),authored.replace(/\r\n?/g,'\n'));
    pass('Results: multiline user messages and Markdown headings/fences stay quoted and attributed; official conditions remain independent');

    for(const width of [1440,390]){
      await cdp.send('Emulation.setDeviceMetricsOverride',{width,height:width===390?844:900,deviceScaleFactor:1,mobile:width===390});
      await ev('document.getElementById("export-checklist").scrollIntoView({block:"center",behavior:"instant"})');await pause(80);
      assert.ok(await ev('document.documentElement.scrollWidth<=innerWidth+2'));
      if(shot)await shot('results-checklist-'+width,false);
    }
    pass('Results: desktop and phone layouts retain usable checklist controls without horizontal overflow');
  }finally{
    await ev('if(window.__resultClipboard)Object.defineProperty(navigator,"clipboard",window.__resultClipboard);else delete navigator.clipboard');
    await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
    await mode('normal');
  }
};

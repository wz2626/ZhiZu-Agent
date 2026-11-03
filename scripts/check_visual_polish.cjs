// Presentation regressions against the real Vue workspace. Review/proposal
// responses below are explicitly synthetic; no model semantics are assessed.
module.exports=async function({cdp,click,fill,until,pause,assert,pass,shot}){
  const ev=expression=>cdp.evaluate(expression);
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  await cdp.send('Emulation.setTouchEmulationEnabled',{enabled:false});
  await cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'no-preference'}]});
  const origin=await ev('location.origin');await cdp.send('Page.navigate',{url:origin});
  await cdp.send('Page.bringToFront');
  await until('!!window.__zhizuLayoutDiagnostics?.length && !document.querySelector("#dossier .notice-warn")','visual policy initialized');
  const repeated='租赁结束后应核对押金扣减明细。',repair='维修责任和费用应由双方核实。',neutral='双方按约办理交接。';
  const filler='双方保存租金支付及房屋交接记录，并及时沟通维修事项。';
  const text='房屋租赁合同（明确的视觉交互合成样本）\n\n'+[0,1,2].map(i=>Array.from({length:10},(_,j)=>`第${i*10+j+1}项 ${filler}`).join('\n\n')+'\n\n'+repeated).join('\n\n')+'\n\n'+repair+'\n\n'+neutral;
  const law=require('../backend/data/laws/civil_code_lease_703_734.json').find(item=>item.law_id==='LAW-712');
  const evidence=Object.fromEntries(['article_no','law_name','content','source_url','verified_date'].map(key=>[key,law[key]]));
  await ev(`(()=>{
    window.__visualComposer=document.getElementById('negotiation-draft');
    window.__visualNativeFetch=window.fetch;window.__visualDrafts=[];window.__visualAnimations=[];window.__visualScrolls=[];
    const sourceScroll=Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView=function(options){if(this.matches('#submitted-document mark'))window.__visualScrolls.push(this.dataset.start);return sourceScroll.call(this,options);};
    document.addEventListener('animationstart',event=>window.__visualAnimations.push({name:event.animationName,start:event.target.dataset.start||null,text:event.target.id==='proposed-message'?event.target.textContent:null}));
    const json=data=>new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
    window.fetch=async(url,options)=>{
      if(String(url)==='/api/review/analyze-detailed')return json({status:'success',results:[
        {clause_id:'C-01',original_clause:${JSON.stringify(repeated)},risk_level:'HIGH',explanation:'合成说明：请核对押金扣减依据。',evidence_ids:['LAW-712'],negotiation_tip:'请核对凭证与返还安排。'},
        {clause_id:'C-02',original_clause:${JSON.stringify(repair)},risk_level:'MEDIUM',explanation:'合成说明：请核对维修责任。',evidence_ids:['LAW-712'],negotiation_tip:'请明确责任与时间。'},
        {clause_id:'C-03',original_clause:${JSON.stringify(neutral)},risk_level:'NONE',explanation:'合成说明：交接安排需核对。',evidence_ids:[],negotiation_tip:'保留交接记录。'}
      ],total_risks:2,review_context_id:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',evidence_by_id:{'LAW-712':${JSON.stringify(evidence)}},retry_count:0,trace:[],trace_label:'本次执行回放',errors:[]});
      if(String(url)==='/api/review/proposal')return new Promise(resolve=>window.__visualDrafts.push({body:JSON.parse(options.body),resolve}));
      return window.__visualNativeFetch(url,options);
    };
    window.__visualReply=(index,text,replayed=false)=>{const item=window.__visualDrafts[index];item.resolve(json({
      review_context_id:item.body.review_context_id,clause_id:item.body.clause_id,draft_request_id:item.body.draft_request_id,
      status:'success',proposed_message:text,evidence_ids:['LAW-712'],
      questions:['请补充已知的处理时间。'],question_items:[{question_id:'q_'+String(index+1).padStart(32,'0'),text:'请补充已知的处理时间。'}],
      retry_count:0,trace:[],trace_label:'本次执行回放',errors:[],replayed
    }));};
  })()`);
  try{
    await fill('contract-input',text);await click('#analyze-contract');
    await until('document.querySelectorAll("#risk-navigation [data-clause]").length===3','synthetic visual review');
    assert.equal(await ev('document.getElementById("submitted-document").textContent'),text);
    assert.ok((await ev('document.getElementById("risk-counts").textContent')).includes('待关注 2'));
    assert.ok((await ev('document.getElementById("risk-counts").textContent')).includes('说明 1'));
    pass('Visual: risk totals exclude NONE and the complete source remains exact');
    await require('./check_risk_filter.cjs')({cdp,click,pause,assert,pass,shot});

    await click('[data-clause="C-01"]');await pause(1100);
    const starts=await ev('[...document.querySelectorAll("#submitted-document mark[data-clauses~=C-01]")].map(e=>e.dataset.start)');
    assert.equal(starts.length,3);
    await ev(`window.__visualScrolls=[];window.__visualAnimations=[];for(let i=0;i<5;i++)[...document.querySelectorAll('#location-notice button')].find(b=>b.textContent==='下一处').click();`);
    await until(`document.querySelector('mark.current')?.dataset.start===${JSON.stringify(starts[2])}`,'last repeated match selected');
    await pause(1100);
    const scrolls=await ev('window.__visualScrolls'),highlights=await ev('window.__visualAnimations.filter(a=>a.name==="source-confirm").map(a=>a.start)');
    assert.ok(scrolls.length>0);assert.ok(scrolls.every(start=>start===starts[2]),JSON.stringify(scrolls));
    assert.ok(highlights.length>0);assert.ok(highlights.every(start=>start===starts[2]),JSON.stringify(highlights));
    await ev('window.__visualScrolls=[];document.querySelector("mark.current").click()');await pause(60);
    assert.deepEqual(await ev('window.__visualScrolls'),[]);
    pass('Visual: rapid next-match navigation scrolls/highlights only the final occurrence; source click never recenters');

    const oldVersion=await ev('document.querySelector("[aria-label=查看分析版本]").value');
    await click('[data-risk-filter="MEDIUM"]');
    await click('#edit-contract');await fill('contract-input',text+'\n另一分析版本');await click('#analyze-contract');
    await until('document.querySelectorAll("[aria-label=查看分析版本] option").length===2','second analysis version');
    assert.equal(await ev('document.querySelector("[data-risk-filter=ALL]").getAttribute("aria-pressed")'),'true');
    assert.equal(await ev('document.querySelectorAll("#risk-items [data-clause]").length'),3);
    await click('[data-clause="C-01"]');await pause(100);
    await ev(`window.__visualScrolls=[];[...document.querySelectorAll('#location-notice button')].find(b=>b.textContent==='下一处').click();const s=document.querySelector('[aria-label=查看分析版本]');s.value=${JSON.stringify(oldVersion)};s.dispatchEvent(new Event('change',{bubbles:true}));`);
    await pause(160);
    assert.deepEqual(await ev('window.__visualScrolls'),[]);
    assert.equal(await ev('document.querySelector("mark.current,.source-arrived")!==null'),false);
    assert.equal(await ev('document.getElementById("submitted-document").textContent'),text);
    pass('Visual: switching analysis versions cancels queued old-match scrolling and emphasis');

    await click('[data-clause="C-01"]');await click('#prepare-communication');await fill('scenario-select','deposit','change');
    await click('#proposal-tool > summary');await fill('proposal-goal','请核对押金扣减凭证与处理时间。');
    const generate=async(message,replayed=false)=>{
      const index=await ev('window.__visualDrafts.length');await click('#generate-proposal');
      await until(`window.__visualDrafts.length===${index+1}`,'held visual draft');
      await ev(`window.__visualReply(${index},${JSON.stringify(message)},${replayed})`);
      await until(`document.getElementById('proposed-message')?.textContent===${JSON.stringify(message)} && !document.getElementById('generate-proposal').disabled`,'accepted visual draft');
      return index;
    };
    await generate('第一份完整参考稿：请核对押金明细。');
    await until('window.__visualAnimations.some(a=>a.name==="ink-arrive"&&a.text.startsWith("第一份"))','first ink entry');
    assert.equal(await ev('document.getElementById("proposed-message").children.length'),0);
    assert.equal(await ev('getComputedStyle(document.getElementById("proposed-message")).animationDuration'),'0.26s');
    await generate('第二份完整参考稿：请明确返还安排。');
    await until('window.__visualAnimations.some(a=>a.name==="ink-arrive"&&a.text.startsWith("第二份"))','second ink entry');
    await click('#fill-proposal');assert.equal(await ev('document.getElementById("proposed-message").classList.contains("ink-arrive")'),false);
    assert.equal(await ev('document.getElementById("negotiation-draft").value'),'第二份完整参考稿：请明确返还安排。');
    assert.equal(await ev('document.getElementById("round-count").dataset.round'),'0');
    pass('Visual: consecutive accepted drafts restart the 260ms pulse; text is complete, adoption cancels it and consumes no round');

    const pending=await ev('window.__visualDrafts.length');await click('#generate-proposal');await until(`window.__visualDrafts.length===${pending+1}`,'background draft held');
    await click('[data-clause="C-02"]');await ev(`window.__visualReply(${pending},'后台完成的完整参考稿。')`);await pause(80);
    const inkCount=await ev('window.__visualAnimations.filter(a=>a.name==="ink-arrive").length');
    await click('[data-clause="C-01"]');await click('#prepare-communication');await pause(80);
    assert.equal(await ev('document.getElementById("proposed-message").textContent'),'后台完成的完整参考稿。');
    assert.equal(await ev('document.getElementById("proposed-message").classList.contains("ink-arrive")'),false);
    await generate('缓存回放的完整参考稿。',true);await pause(80);
    assert.equal(await ev('window.__visualAnimations.filter(a=>a.name==="ink-arrive").length'),inkCount);
    pass('Visual: background completion, history return and replay display full drafts without replaying arrival effects');

    const long='较长的合成参考稿，用于核对换行与选择。'+('ASCII'.repeat(180));
    await generate(long);assert.equal(await ev('document.getElementById("proposed-message").classList.contains("ink-arrive")'),false);
    assert.equal(await ev('getComputedStyle(document.getElementById("proposed-message")).filter'),'none');
    assert.equal(await ev('document.getElementById("proposed-message").children.length'),0);
    await cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
    await generate('减少动态模式下完整清晰的参考稿。');await pause(60);
    assert.equal(await ev('getComputedStyle(document.getElementById("proposed-message")).animationName'),'none');
    assert.equal(await ev('getComputedStyle(document.getElementById("proposed-message")).filter'),'none');
    assert.equal(await ev('getComputedStyle(document.getElementById("proposed-message")).opacity'),'1');
    pass('Visual: long drafts avoid blur/character nodes; reduced motion presents complete clear text immediately');

    await cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'no-preference'}]});
    await generate('可以取消显影的完整参考稿。');await until('document.getElementById("proposed-message").classList.contains("ink-arrive")','cancelable entry');
    await ev('document.getElementById("workspace").dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true}))');
    assert.equal(await ev('document.querySelectorAll(".ink-arrive,.source-arrived,.result-arrived").length'),0);
    await generate('窗口失焦时仍完整保留的参考稿。');await until('document.getElementById("proposed-message").classList.contains("ink-arrive")','blur entry');
    await ev('window.dispatchEvent(new Event("blur"))');
    assert.equal(await ev('document.querySelectorAll(".ink-arrive,.source-arrived,.result-arrived").length'),0);
    assert.equal(await ev('document.getElementById("proposed-message").textContent'),'窗口失焦时仍完整保留的参考稿。');
    await ev('window.dispatchEvent(new Event("focus"))');await pause(60);
    assert.equal(await ev('document.getElementById("proposed-message").classList.contains("ink-arrive")'),false);
    pass('Visual: Escape and window blur cancel decoration without losing text or replaying it on focus');

    await ev('document.getElementById("proposal-goal").focus()');
    const focus=await ev('(()=>{const e=document.activeElement,s=getComputedStyle(e);return {visible:e.matches(":focus-visible"),outline:s.outlineStyle,width:s.outlineWidth,shadow:s.boxShadow}})()');
    assert.equal(focus.visible,true);assert.equal(focus.outline,'solid');assert.equal(focus.width,'2px');assert.notEqual(focus.shadow,'none');
    await click('#new-practice');await ev(`[...document.querySelectorAll('.task-tabs button')].find(b=>b.textContent==='练习结果与清单').click();navigator.clipboard.writeText=()=>Promise.reject(new Error('explicit visual test denial'));`);
    await click('#export-checklist');await until('!!document.getElementById("checklist-copy")','readonly copy fallback');
    await click('#negotiation-more > summary');await click('.task-detail-link');
    const controls=await ev('[...document.querySelectorAll("textarea,select")].map(e=>{const skin=e.closest(".answer-field")||(e.id==="contract-input"?e.closest(".contract-editor-surface"):e),s=getComputedStyle(skin);return {id:e.id||e.getAttribute("aria-label"),classed:e.classList.contains("ui-field"),editorFrame:skin!==e,border:s.borderTopWidth,color:s.borderTopColor,bg:s.backgroundColor}})');
    assert.ok(controls.length>=11,JSON.stringify(controls));
    for(const field of controls){assert.equal(field.classed,true,JSON.stringify(field));assert.equal(field.border,'1px',JSON.stringify(field));assert.notEqual(field.bg,'rgba(0, 0, 0, 0)',JSON.stringify(field));}
    assert.equal(controls.find(field=>field.id==='contract-input').editorFrame,true);
    assert.ok(controls.some(e=>e.id==='checklist-copy'));assert.ok(controls.some(e=>e.id==='unresolved-requests'));assert.ok(controls.some(e=>e.id==='missing-facts'));
    assert.equal(await ev('document.getElementById("negotiation-draft")===window.__visualComposer'),true);
    pass('Visual: keyboard double focus ring and every control or its editor frame retain skin, including manual facts, all selects and copy fallback');
    await shot('visual-polish-controls');
  }finally{
    await ev('window.fetch=window.__visualNativeFetch');
    await cdp.send('Emulation.setEmulatedMedia',{features:[]});
  }
};

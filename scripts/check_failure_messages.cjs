// Public errors may repeat reason in errors; render each safe explanation once.
module.exports=async({cdp,click,fill,until,pause,assert,pass,shot})=>{
 const ev=e=>cdp.evaluate(e),reviewMessage='云端向量服务调用失败，已停止审查。';
 await cdp.send('Page.reload',{ignoreCache:true});await pause(180);await until('!!window.__zhizuLayoutDiagnostics?.length','workspace');
 await ev(`window.__errorNativeFetch=window.fetch;window.fetch=async(url,options)=>String(url)==='/api/review/analyze-detailed'?new Response(JSON.stringify({status:'needs_review',results:[],total_risks:0,reason:${JSON.stringify(reviewMessage)},errors:[${JSON.stringify(reviewMessage)},'请稍后重试。'],trace:[],retry_count:0}),{status:200,headers:{'Content-Type':'application/json'}}):window.__errorNativeFetch(url,options)`);
 const contract='房屋租赁合同。租赁结束后可不说明理由直接扣留全部押金。\n维修责任和费用均由租客承担。\n提前退租须支付固定违约金2000元。';await fill('contract-input',contract);await click('#analyze-contract');await until('!!document.querySelector("#dossier .notice-error")','failure shown');
 assert.equal(await ev('document.querySelector("#dossier .notice-error").textContent'),reviewMessage+'；请稍后重试。');
 assert.equal(await ev('document.getElementById("contract-input").value'),contract);assert.equal(await ev('document.querySelectorAll("#risk-items [data-clause]").length'),0);
 await ev('document.querySelector("#dossier .notice-error").scrollIntoView({block:"center",behavior:"instant"})');await shot('review-error-once',false);
 pass('Review failure displays a shared reason once, preserves distinct advice and input, and never fabricates successful results');
 await ev('window.fetch=window.__errorNativeFetch');await click('#analyze-contract');await until('document.querySelectorAll("#risk-items [data-clause]").length===3','normal fixture review');await click('[data-clause="C-02"]');await click('#prepare-communication');await click('#proposal-tool>summary');await fill('proposal-goal','请明确维修责任。');
 await ev(`window.fetch=async(url,options)=>{if(String(url)!=='/api/review/proposal')return window.__errorNativeFetch(url,options);const body=JSON.parse(options.body);return new Response(JSON.stringify({...body,status:'needs_review',reason:'参考稿未通过校验。',errors:['参考稿未通过校验。','请调整目标后重试。'],proposed_message:'',evidence_ids:[],questions:[],question_items:[],trace:[],retry_count:2}),{status:200,headers:{'Content-Type':'application/json'}});}`);
 await click('#generate-proposal');await until('!!document.getElementById("proposal-error")','draft failure');
 assert.equal(await ev('document.getElementById("proposal-error").textContent'),'参考稿未通过校验。；请调整目标后重试。');
 assert.equal(await ev('document.getElementById("proposal-goal").value'),'请明确维修责任。');
 await ev('window.fetch=window.__errorNativeFetch');pass('Proposal failure also deduplicates public reasons without losing distinct guidance or the edited goal');
};

// Keyboard events use the same action gate; no independent consent checkbox.
module.exports=async function({cdp,pause,assert,pass,requests}){
 const ev=e=>cdp.evaluate(e),count=requests.length;
 await ev('document.getElementById("negotiation-draft").dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",ctrlKey:true,isComposing:true,bubbles:true}));document.getElementById("negotiation-draft").dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",metaKey:true,repeat:true,bubbles:true}))');await pause(50);
 assert.equal(requests.length,count,'IME and repeated shortcut never submit');
 assert.equal(await ev('document.querySelectorAll("#message-privacy-confirm,#proposal-privacy-confirm").length'),0);
 assert.equal(await ev('document.getElementById("negotiation-draft")===window.savedComposer'),true);
 const broken=await ev('[...document.querySelectorAll("[aria-describedby]")].flatMap(e=>e.getAttribute("aria-describedby").split(" ").filter(id=>id&&!document.getElementById(id)))');
 assert.deepEqual(broken,[]);
 pass('Keyboard: IME and repeated shortcuts do not submit; checkbox-free Composer and accessibility references survive');
};

// V4 preserves keyboard safety / accessibility, not the retired phase/tilt demo.
module.exports=async function({cdp,pause,assert,pass,requests}){
 const ev=e=>cdp.evaluate(e);const count=requests.length;
 await ev('document.getElementById("negotiation-draft").focus()');
 await cdp.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,modifiers:2});
 await cdp.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,modifiers:2});await pause(60);
 assert.equal(requests.length,count,'shortcut cannot bypass privacy consent');
 await ev('document.getElementById("message-privacy-confirm").click()');
 await ev('document.getElementById("negotiation-draft").dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",ctrlKey:true,isComposing:true,bubbles:true}));document.getElementById("negotiation-draft").dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",metaKey:true,repeat:true,bubbles:true}))');await pause(50);
 assert.equal(requests.length,count,'IME and repeated shortcut never submit');
 await ev('document.getElementById("message-privacy-confirm").click()');
 assert.equal(await ev('document.getElementById("negotiation-draft")===window.savedComposer'),true);
 const broken=await ev('[...document.querySelectorAll("[aria-describedby]")].flatMap(e=>e.getAttribute("aria-describedby").split(" ").filter(id=>id&&!document.getElementById(id)))');
 assert.deepEqual(broken,[]);
 pass('Keyboard: trusted Ctrl+Enter requires consent; IME/repeated shortcuts do not send; mounted Composer and accessibility references survive');
};

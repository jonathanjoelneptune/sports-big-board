/* Sports Big Board v5.4.7 — application/video fullscreen authority.
   The logo-adjacent fullscreen control owns Sports Big Board app fullscreen; the
   player utility control owns video fullscreen. Controller-originated fullscreen
   can use the loopback Windows bridge because browser Fullscreen API calls normally
   require a trusted DOM user activation that Gamepad/WebSocket polling cannot create. */
(() => {
  'use strict';
  if(window.SBB_FULLSCREEN_CONTROL?.version==='5.4.7')return;
  const VERSION='5.4.7';
  const APP_BUTTON='bigBoardFullscreenBtn';
  const VIDEO_BUTTON='fullscreenBtn';
  let toastTimer=0,bridgeUnsub=null;

  const $=id=>document.getElementById(id);
  const visible=el=>{
    if(!el||!el.isConnected||el.hidden||el.classList?.contains('hidden'))return false;
    const r=el.getBoundingClientRect?.();return !!r&&r.width>0&&r.height>0;
  };
  const fullscreenElement=()=>document.fullscreenElement||document.webkitFullscreenElement||null;
  const bridge=()=>window.SBB_CONTROLLER_NATIVE_BRIDGE||null;

  function showToast(text,state='info'){
    let el=$('sbbFullscreenToast');
    if(!el){el=document.createElement('div');el.id='sbbFullscreenToast';el.className='sbb-fullscreen-toast';el.setAttribute('role','status');el.setAttribute('aria-live','polite');document.body.appendChild(el);}
    el.dataset.state=state;el.textContent=String(text||'');el.classList.add('show');
    if(toastTimer)clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),2200);
  }
  async function requestFullscreen(el,{navigationUI=false}={}){
    if(!el)return false;
    const fn=el.requestFullscreen||el.webkitRequestFullscreen||el.msRequestFullscreen;
    if(typeof fn!=='function')return false;
    try{
      // Chromium is happiest when application fullscreen targets the document root.
      // Try navigationUI first, then retry without options for Safari/older engines.
      const result=navigationUI&&el.requestFullscreen?fn.call(el,{navigationUI:'hide'}):fn.call(el);
      if(result&&typeof result.then==='function')await result;
      return true;
    }catch(first){
      if(navigationUI){try{const retry=fn.call(el);if(retry&&typeof retry.then==='function')await retry;return true;}catch(_){}}
      return false;
    }
  }
  async function exitDomFullscreen(){
    const fn=document.exitFullscreen||document.webkitExitFullscreen||document.msExitFullscreen;
    if(typeof fn!=='function'||!fullscreenElement())return false;
    try{await fn.call(document);return true;}catch(_){return false;}
  }
  function nativeCommand(command){
    try{return !!bridge()?.sendCommand?.(command);}catch(_){return false;}
  }
  function bindBridgeResults(){
    if(bridgeUnsub)return;
    try{bridgeUnsub=bridge()?.subscribe?.(detail=>{
      if(detail?.reason!=='command-result')return;const snap=bridge()?.snapshot?.()||{};
      if(snap.lastCommandOk===false)showToast(`Windows could not send ${snap.lastCommand||'fullscreen command'}`,'warn');
      else if(snap.lastCommand==='app-fullscreen')showToast('App fullscreen command delivered');
      else if(snap.lastCommand==='video-fullscreen')showToast('Video fullscreen command delivered');
    })||null;}catch(_){}
  }
  function appTarget(){return document.documentElement;}
  function activePlayerLayer(){return document.querySelector('#layerA.active,#layerB.active,.player-layer.active')||$('stage');}
  function videoTarget(){
    const layer=activePlayerLayer();
    if(layer){
      const native=[...layer.querySelectorAll('video')].find(visible);if(native)return native;
      const frame=[...layer.querySelectorAll('iframe')].find(visible);if(frame)return frame;
      const host=[...layer.querySelectorAll('.youtube-player-host')].find(visible);if(host?.querySelector('iframe'))return host.querySelector('iframe');
    }
    return $('stage');
  }
  function userActivation(){try{return !!navigator.userActivation?.isActive;}catch(_){return false;}}

  async function toggleApp({controller=false}={}){
    if(fullscreenElement()){await exitDomFullscreen();sync();return true;}
    // Trusted mouse/keyboard clicks should always use the standards-based DOM API.
    if(!controller||userActivation()){
      if(await requestFullscreen(appTarget(),{navigationUI:true})){sync();return true;}
    }
    // Gamepad and loopback-controller actions are not transient browser activations.
    // The native bridge therefore sends the browser's trusted F11 key on the local PC.
    bindBridgeResults();if(nativeCommand('app-fullscreen')){showToast('Sending app fullscreen…');return true;}
    if(await requestFullscreen(appTarget(),{navigationUI:true})){sync();return true;}
    showToast('Fullscreen needs a direct browser click','warn');return false;
  }
  async function toggleVideo({controller=false}={}){
    const current=fullscreenElement();
    if(current){await exitDomFullscreen();sync();return true;}
    if(!controller||userActivation()){
      if(await requestFullscreen(videoTarget())){sync();return true;}
    }
    // Existing Sports Big Board keyboard contract uses F for active-video fullscreen.
    bindBridgeResults();if(nativeCommand('video-fullscreen')){showToast('Sending video fullscreen…');return true;}
    if(await requestFullscreen(videoTarget())){sync();return true;}
    showToast('Video fullscreen needs a direct browser click','warn');return false;
  }
  async function exitFullscreen({controller=false}={}){
    if(fullscreenElement()){const ok=await exitDomFullscreen();sync();return ok;}
    // If app fullscreen was entered through browser F11, toggle F11 again locally.
    if(controller){bindBridgeResults();if(nativeCommand('app-fullscreen')){showToast('Sending exit fullscreen…');return true;}}
    return false;
  }
  function sync(){
    const fs=fullscreenElement(),app=appTarget(),stage=$('stage');
    const appFull=!!fs&&(fs===app||fs===document.documentElement);
    const videoFull=!!fs&&!!stage&&(fs===stage||stage.contains(fs));
    document.documentElement.dataset.sbbAppFullscreen=appFull?'1':'0';
    document.documentElement.dataset.sbbVideoFullscreen=videoFull?'1':'0';
    const ab=$(APP_BUTTON);if(ab){ab.setAttribute('aria-pressed',appFull?'true':'false');ab.title=appFull?'Exit Sports Big Board fullscreen':'Fullscreen Sports Big Board';}
    const vb=$(VIDEO_BUTTON);if(vb){vb.setAttribute('aria-pressed',videoFull?'true':'false');vb.title=videoFull?'Exit video fullscreen':'Fullscreen video';}
  }
  function onClick(event){
    const button=event.currentTarget||event.target?.closest?.(`#${APP_BUTTON},#${VIDEO_BUTTON}`);if(!button)return;
    event.preventDefault();event.stopImmediatePropagation();
    // A physical mouse/keyboard click stays inside this trusted event turn.
    // Controller actions enter through the exported API and use the local bridge.
    if(button.id===APP_BUTTON)toggleApp({controller:false});
    else toggleVideo({controller:false});
  }
  function bindButton(id){
    const button=$(id);if(!button||button.dataset.sbbFullscreenBound==='1')return;
    button.dataset.sbbFullscreenBound='1';button.addEventListener('click',onClick,true);
  }
  function bind(){
    bindButton(APP_BUTTON);bindButton(VIDEO_BUTTON);bindBridgeResults();
    document.addEventListener('fullscreenchange',sync);document.addEventListener('webkitfullscreenchange',sync);
    window.addEventListener('pageshow',()=>{bindButton(APP_BUTTON);bindButton(VIDEO_BUTTON);sync();});
    sync();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
  window.SBB_FULLSCREEN_CONTROL=Object.freeze({version:VERSION,toggleApp,toggleVideo,exitFullscreen,videoTarget,appTarget,snapshot:()=>({fullscreen:!!fullscreenElement(),element:fullscreenElement()?.id||fullscreenElement()?.tagName||'',bridge:!!bridge()?.transportConnected})});
})();

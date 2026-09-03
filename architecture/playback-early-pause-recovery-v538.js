/* Sports Big Board v5.3.9 — bounded early-pause recovery.
   The intermittent ~5 second pause is treated as a local playback incident.
   Explicit user pauses are latched for the current selection and can never be
   overridden by the recovery timers. */
(() => {
  'use strict';
  if(window.SBB_EARLY_PAUSE_RECOVERY?.version==='5.3.9')return;
  const VERSION='5.3.9';
  const state={
    generation:0,key:'',selectedAt:0,manualPause:false,manualPauseKey:'',
    providerControlInteractionAt:0,providerControlInteractionKey:'',
    softKicks:0,reloads:0,lastAction:'',lastReason:'',timers:[],events:[]
  };
  const $=id=>document.getElementById(id);
  const clean=v=>String(v??'').trim();

  function log(action,detail=''){
    state.lastAction=action;state.lastReason=detail;state.events.push({at:Date.now(),action,detail,key:state.key});
    if(state.events.length>24)state.events.splice(0,state.events.length-24);
    try{window.dispatchEvent(new CustomEvent('sbb:early-pause-recovery',{detail:{action,detail,key:state.key}}));}catch(_){}
  }
  function currentKey(){
    let index='';try{index=typeof currentIndex!=='undefined'?String(currentIndex):'';}catch(_){}
    return `${index}|${clean($('currentTitle')?.textContent)}`;
  }
  function userPaused(){return !!(state.manualPause&&state.manualPauseKey===state.key);}
  function setCanonicalManualPause(value){
    // app.js owns this global lexical flag. Keeping it synchronized means the
    // original 3.5 s Progress Watchdog and every other canonical autoplay path
    // see the same explicit user intent as this v5.3.9 guard.
    try{if(typeof manualPauseRequested!=='undefined')manualPauseRequested=!!value;}catch(_){}
  }
  function markUserPause(reason){
    state.manualPause=true;state.manualPauseKey=state.key||currentKey();
    setCanonicalManualPause(true);
    log('USER_PAUSE_SUPPRESS',reason);
  }
  function clearUserPause(reason='resume'){
    if(state.manualPause)log('USER_PAUSE_RELEASE',reason);
    state.manualPause=false;state.manualPauseKey='';
    setCanonicalManualPause(false);
  }
  function youtubePausedNow(){
    try{
      const bank=(typeof players!=='undefined')?players:null;
      if(!bank)return false;
      for(const slot of ['A','B']){
        const p=bank?.[slot];
        if(p&&Number(p.getPlayerState?.())===2)return true; // YT.PlayerState.PAUSED
      }
    }catch(_){}
    return false;
  }
  function confirmProviderPause(){
    if(state.providerControlInteractionKey!==state.key)return;
    if(youtubePausedNow())markUserPause('embedded provider pause');
  }
  function noteProviderControlInteraction(){
    const active=document.activeElement;
    if(active?.tagName==='IFRAME' && /youtube(?:-nocookie)?\.com/i.test(clean(active.src))){
      state.providerControlInteractionAt=Date.now();
      state.providerControlInteractionKey=state.key||currentKey();
      log('PROVIDER_CONTROL_INTERACTION','youtube iframe focus');
      // The provider state transition can trail iframe focus by a few frames.
      // Three bounded probes catch an actual Pause command before the legacy
      // Progress Watchdog reaches its 3.5 s soft-kick threshold.
      for(const ms of [80,250,650])setTimeout(confirmProviderPause,ms);
      return true;
    }
    return false;
  }
  function providerControlPauseLikely(){
    return !!(
      state.providerControlInteractionKey===state.key &&
      state.providerControlInteractionAt>=state.selectedAt &&
      Date.now()-state.providerControlInteractionAt<9000
    );
  }
  function pauseUi(){
    const badge=clean($('onAirBadge')?.textContent).toUpperCase();
    const play=$('playBtn'),label=`${clean(play?.getAttribute('aria-label'))} ${clean(play?.title)}`.toUpperCase();
    const saysPaused=/\bPAUSED?\b|\bPAUSE BUG\b|\bSTALLED?\b/.test(badge);
    const offersPlay=/\bPLAY\b/.test(label)&&!/\bPAUSE\b/.test(label);
    return saysPaused||offersPlay;
  }
  function activeVideos(){return [...document.querySelectorAll('video')].filter(v=>!v.closest?.('.hidden'));}
  function youtubeFrames(){return [...document.querySelectorAll('#playerA iframe,#playerB iframe,iframe[src*="youtube.com/embed"],iframe[src*="youtube-nocookie.com/embed"]')];}

  function softPlay(){
    let attempted=0;
    for(const video of activeVideos()){
      try{if(video.paused&&!video.ended){attempted++;const p=video.play();p?.catch?.(()=>{});}}catch(_){}
    }
    for(const frame of youtubeFrames()){
      try{attempted++;frame.contentWindow?.postMessage(JSON.stringify({event:'command',func:'playVideo',args:[]}), '*');}catch(_){}
    }
    for(const owner of [window.SBB_PLAYBACK_SESSION,window.SBB_PLAYBACK_ORCHESTRATOR]){
      try{if(typeof owner?.resume==='function'){attempted++;owner.resume({reason:'v5.3.9 early pause soft kick'});}}catch(_){}
    }
    state.softKicks++;log('SOFT_RESUME',`targets=${attempted}`);return attempted;
  }
  function boundedReload(){
    let acted=false;
    try{
      const watchdog=window.SBB_PLAYBACK_PROGRESS_WATCHDOG;
      if(typeof watchdog?.recoverNow==='function'){watchdog.recoverNow({reason:'v5.3.9 early pause after soft resume'});acted=true;}
    }catch(_){}
    if(!acted){
      try{
        if(typeof tuneProgramIndexV5==='function'&&typeof currentIndex!=='undefined'){
          tuneProgramIndexV5(currentIndex,{userInitiated:false,reason:'v5.3.9 bounded early-pause reload'});acted=true;
        }
      }catch(_){}
    }
    if(!acted){
      try{if(typeof playCurrent==='function'){playCurrent({reason:'v5.3.9 bounded early-pause reload'});acted=true;}}catch(_){}
    }
    state.reloads++;log('BOUNDED_RECOVERY',acted?'delegated':'no-compatible-owner');
  }
  function clearTimers(){for(const timer of state.timers)clearTimeout(timer);state.timers=[];}
  function shouldRecover(){
    if(userPaused()||!pauseUi())return false;
    // Native YouTube controls live in a cross-origin iframe, so their click cannot
    // bubble to the parent document. Focusing that iframe is the reliable user
    // intent signal available here. If a pause follows such interaction, favor
    // user intent and latch the pause rather than unexpectedly restarting playback.
    if(providerControlPauseLikely()){markUserPause('embedded provider controls');return false;}
    return true;
  }
  function schedule(reason='selection'){
    const key=currentKey();if(!key||/Loading highlight/i.test(key))return;
    if(key===state.key&&Date.now()-state.selectedAt<2500)return;
    const changed=key!==state.key;
    state.key=key;state.generation++;state.selectedAt=Date.now();clearTimers();
    if(changed){
      clearUserPause('new selection');
      state.providerControlInteractionAt=0;state.providerControlInteractionKey='';
    }
    const generation=state.generation;log('ARM',reason);
    state.timers.push(setTimeout(()=>{
      if(generation!==state.generation||!shouldRecover())return;
      softPlay();
    },5200));
    state.timers.push(setTimeout(()=>{
      if(generation!==state.generation||!shouldRecover())return;
      boundedReload();
    },7900));
  }

  function bindUserIntent(){
    const play=$('playBtn');
    play?.addEventListener('click',()=>{
      const label=`${clean(play.getAttribute('aria-label'))} ${clean(play.title)}`.toUpperCase();
      const alreadyPaused=/PAUSED?|STALLED?/.test(clean($('onAirBadge')?.textContent).toUpperCase());
      // Pre-click label/state tells us which action the user requested.
      if(/\bPAUSE\b/.test(label)&&!alreadyPaused)markUserPause('play button');
      else if(/\bPLAY\b/.test(label)||alreadyPaused)clearUserPause('play button resume');
    },true);
    document.addEventListener('keydown',event=>{
      if(event.code!=='Space'||event.repeat)return;
      const tag=clean(event.target?.tagName).toUpperCase();if(/INPUT|TEXTAREA|SELECT/.test(tag)||event.target?.isContentEditable)return;
      const label=clean(play?.getAttribute('aria-label')).toUpperCase();
      const alreadyPaused=/PAUSED?|STALLED?/.test(clean($('onAirBadge')?.textContent).toUpperCase());
      if(/PAUSE/.test(label)&&!alreadyPaused)markUserPause('space key');
      else clearUserPause('space key resume');
    },true);
    // Cross-origin embedded player controls do not bubble clicks to this document.
    // A focused YouTube iframe after window blur is therefore recorded as explicit
    // provider-control interaction for this selection.
    window.addEventListener('blur',()=>setTimeout(noteProviderControlInteraction,0),true);
    document.addEventListener('focusin',event=>{
      const frame=event.target;
      if(frame?.tagName==='IFRAME'&&/youtube(?:-nocookie)?\.com/i.test(clean(frame.src)))noteProviderControlInteraction();
    },true);
  }
  function bind(){
    bindUserIntent();
    const title=$('currentTitle');if(title)new MutationObserver(()=>setTimeout(()=>schedule('title change'),0)).observe(title,{subtree:true,childList:true,characterData:true});
    window.addEventListener('sbb:curated-event-identity',()=>setTimeout(()=>schedule('curated selection'),0));
    window.addEventListener('sbb:score-click-selection',()=>setTimeout(()=>schedule('score selection'),0));
    setTimeout(()=>schedule('startup'),900);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
  window.SBB_EARLY_PAUSE_RECOVERY=Object.freeze({
    version:VERSION,arm:schedule,
    snapshot:()=>({
      generation:state.generation,key:state.key,selectedAt:state.selectedAt,
      userPauseSuppressed:userPaused(),manualPause:state.manualPause,
      providerControlInteractionAt:state.providerControlInteractionAt,
      softKicks:state.softKicks,reloads:state.reloads,lastAction:state.lastAction,lastReason:state.lastReason,
      events:state.events.slice()
    })
  });
})();

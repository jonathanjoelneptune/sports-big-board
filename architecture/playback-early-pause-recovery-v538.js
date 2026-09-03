/* Sports Big Board v5.3.8 — bounded early-pause recovery.
   The intermittent ~5 second pause is treated as a local playback incident.
   Never overrides an explicit user pause and never escalates into a retry loop. */
(() => {
  'use strict';
  if(window.SBB_EARLY_PAUSE_RECOVERY?.version==='5.3.8')return;
  const VERSION='5.3.8';
  const state={generation:0,key:'',selectedAt:0,userPauseUntil:0,softKicks:0,reloads:0,lastAction:'',lastReason:'',timers:[],events:[]};
  const $=id=>document.getElementById(id);
  const clean=v=>String(v??'').trim();
  function log(action,detail=''){
    state.lastAction=action;state.lastReason=detail;state.events.push({at:Date.now(),action,detail,key:state.key});
    if(state.events.length>24)state.events.splice(0,state.events.length-24);
    try{window.dispatchEvent(new CustomEvent('sbb:early-pause-recovery',{detail:{action,detail,key:state.key}}));}catch(_){}
  }
  function userPaused(){return Date.now()<state.userPauseUntil;}
  function markUserPause(reason){state.userPauseUntil=Date.now()+12000;log('USER_PAUSE_SUPPRESS',reason);}
  function currentKey(){
    let index='';try{index=typeof currentIndex!=='undefined'?String(currentIndex):'';}catch(_){}
    return `${index}|${clean($('currentTitle')?.textContent)}`;
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
    // Optional public owners can provide a soft resume without changing selection.
    for(const owner of [window.SBB_PLAYBACK_SESSION,window.SBB_PLAYBACK_ORCHESTRATOR]){
      try{if(typeof owner?.resume==='function'){attempted++;owner.resume({reason:'v5.3.8 early pause soft kick'});}}catch(_){}
    }
    state.softKicks++;log('SOFT_RESUME',`targets=${attempted}`);return attempted;
  }
  function boundedReload(){
    let acted=false;
    try{
      const watchdog=window.SBB_PLAYBACK_PROGRESS_WATCHDOG;
      if(typeof watchdog?.recoverNow==='function'){watchdog.recoverNow({reason:'v5.3.8 early pause after soft resume'});acted=true;}
    }catch(_){}
    if(!acted){
      try{
        if(typeof tuneProgramIndexV5==='function'&&typeof currentIndex!=='undefined'){
          tuneProgramIndexV5(currentIndex,{userInitiated:false,reason:'v5.3.8 bounded early-pause reload'});acted=true;
        }
      }catch(_){}
    }
    if(!acted){
      try{if(typeof playCurrent==='function'){playCurrent({reason:'v5.3.8 bounded early-pause reload'});acted=true;}}catch(_){}
    }
    state.reloads++;log('BOUNDED_RECOVERY',acted?'delegated':'no-compatible-owner');
  }
  function clearTimers(){for(const timer of state.timers)clearTimeout(timer);state.timers=[];}
  function schedule(reason='selection'){
    const key=currentKey();if(!key||/Loading highlight/i.test(key))return;
    if(key===state.key&&Date.now()-state.selectedAt<2500)return;
    state.key=key;state.generation++;state.selectedAt=Date.now();state.userPauseUntil=0;clearTimers();
    const generation=state.generation;log('ARM',reason);
    state.timers.push(setTimeout(()=>{
      if(generation!==state.generation||userPaused()||!pauseUi())return;
      softPlay();
    },5200));
    state.timers.push(setTimeout(()=>{
      if(generation!==state.generation||userPaused()||!pauseUi())return;
      boundedReload();
    },7900));
  }
  function bindUserIntent(){
    const play=$('playBtn');
    play?.addEventListener('click',()=>{
      const label=`${clean(play.getAttribute('aria-label'))} ${clean(play.title)}`.toUpperCase();
      // The pre-click state offers PAUSE only while playback is active.
      const alreadyPaused=/PAUSED?|STALLED?/.test(clean($('onAirBadge')?.textContent).toUpperCase());
      if(/\bPAUSE\b/.test(label)&&!alreadyPaused)markUserPause('play button');
      else state.userPauseUntil=0;
    },true);
    document.addEventListener('keydown',event=>{
      if(event.code!=='Space'||event.repeat)return;
      const tag=clean(event.target?.tagName).toUpperCase();if(/INPUT|TEXTAREA|SELECT/.test(tag)||event.target?.isContentEditable)return;
      const label=clean(play?.getAttribute('aria-label')).toUpperCase();const alreadyPaused=/PAUSED?|STALLED?/.test(clean($('onAirBadge')?.textContent).toUpperCase());if(/PAUSE/.test(label)&&!alreadyPaused)markUserPause('space key');else state.userPauseUntil=0;
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
  window.SBB_EARLY_PAUSE_RECOVERY=Object.freeze({version:VERSION,arm:schedule,snapshot:()=>({generation:state.generation,key:state.key,selectedAt:state.selectedAt,userPauseSuppressed:userPaused(),softKicks:state.softKicks,reloads:state.reloads,lastAction:state.lastAction,lastReason:state.lastReason,events:state.events.slice()})});
})();

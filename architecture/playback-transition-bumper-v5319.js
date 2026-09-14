/* Sports Big Board v5.5.0 — transition bumper authority, startup-safe.
   v5.5.0 used a MutationObserver on the legacy loading overlay while other
   playback code was also changing that same class. On some browsers those two
   writers could create a hot mutation loop immediately after launch. v5.5.0
   removes DOM observation entirely. Playback Session events own the transition,
   and a CSS state flag hides the raw loading surface while the bumper is active.

   Startup fail-open hardening: a failed/unavailable/timed-out first playback must
   never strand the viewer behind the transition bumper. The visual transition is
   cleared before recovery is attempted, so playback recovery can continue in the
   background while the Big Board remains usable. A launch-level watchdog also
   covers the case where the first playback session is never created at all.

   Context fail-open hardening: editorial CONTEXT programs are real short-form
   programming, but they are not allowed to become a terminal startup surface. The
   legacy context adapter marks itself playing while its dwell timer exists. When
   that timer expires with no next playable item, showAllCaughtUp() pauses the
   context without clearing its full-stage DOM. Background program refreshes then
   preserve that dead context as the active object even after playable media
   arrives. This guard clears the terminal context surface and automatically tunes
   the first newly-available program without requiring another user gesture.
*/
(() => {
  'use strict';
  if(window.SBB_TRANSITION_BUMPER_V5319?.installed)return;
  const VERSION='5.5.0';
  let activeSelectionId=0,proofTimer=null,lastShownAt=0,lastRecoveredSelection=0,launchFailOpenTimer=null;
  let contextGuardTimer=null,contextWaitingSince=0,contextFailOpenCount=0,contextResumeCount=0,wrappedAllCaughtUp=false;
  let overlayTimers=[];
  const clean=v=>String(v??'').trim();

  function currentIndexSafe(){try{return Number(currentIndex)||0;}catch(_){return 0;}}
  function activeSlotSafe(){try{return String(activeSlot||'A');}catch(_){return 'A';}}
  function clipSafe(){try{return typeof clip==='function'?clip(currentIndexSafe()):null;}catch(_){return null;}}
  function experienceStarted(){try{return !!window.SBB_START?.started || (typeof sportsBigBoardStarted!=='undefined'&&!!sportsBigBoardStarted);}catch(_){return !!window.SBB_START?.started;}}
  function sameGameTransition(session,item){
    const reason=clean(session?.reason).toLowerCase();
    if(/next highlight|reel|same-game|same game/.test(reason))return true;
    try{
      const idx=currentIndexSafe();if(idx<=0)return false;
      const prev=typeof clip==='function'?clip(idx-1):null;
      return !!(prev&&item&&typeof sameGameProgramItem==='function'&&sameGameProgramItem(prev,item));
    }catch(_){return false;}
  }
  function cancelOverlayTimers(){for(const timer of overlayTimers)clearTimeout(timer);overlayTimers=[];}
  function setOwned(owned){
    document.documentElement.dataset.sbbTransitionBumper=owned?'1':'0';
    if(!owned)cancelOverlayTimers();
  }
  function hideRawOverlayBounded(id){
    cancelOverlayTimers();
    const hide=()=>{
      if(id!==activeSelectionId)return;
      try{if(typeof setVideoLoadingOverlay==='function')setVideoLoadingOverlay(false);}catch(_){ }
      document.getElementById('videoLoadingOverlay')?.classList.add('hidden');
    };
    hide();
    // Legacy transport code can assert the loading surface a few times during a
    // slot handoff. A handful of one-shot reassertions is enough and, unlike a
    // MutationObserver, can never form a self-sustaining feedback loop.
    for(const delay of [60,180,420,900,1800])overlayTimers.push(setTimeout(hide,delay));
  }
  function clearVisualTransition(){
    setOwned(false);
    try{if(typeof setVideoLoadingOverlay==='function')setVideoLoadingOverlay(false);}catch(_){ }
    document.getElementById('videoLoadingOverlay')?.classList.add('hidden');
    try{if(typeof hideBumper==='function')hideBumper();}catch(_){ }
    document.getElementById('bumper')?.classList.add('hidden');
    if(proofTimer){clearTimeout(proofTimer);proofTimer=null;}
  }
  function showTransition(session){
    const id=Number(session?.selectionId)||0;if(!id||id===activeSelectionId)return;
    activeSelectionId=id;lastShownAt=Date.now();
    setOwned(true);hideRawOverlayBounded(id);
    const item=clipSafe();const label=sameGameTransition(session,item)?'NEXT HIGHLIGHT':'COMING UP NEXT';
    try{if(typeof showBumper==='function')showBumper(currentIndexSafe(),1400,label);}catch(_){ }
    beginProofLoop(id);
  }
  function hideTransition(id=activeSelectionId){
    if(id&&id!==activeSelectionId)return;
    clearVisualTransition();
  }
  function actualPlaying(session){
    if(clean(session?.state).toLowerCase()==='playing'||Number(session?.firstFrameAt)>0)return true;
    const slot=activeSlotSafe();
    try{if(typeof adapterForSlot==='function'&&adapterForSlot(slot)?.isPlaying?.())return true;}catch(_){ }
    try{
      const p=players?.[slot];const state=Number(p?.getPlayerState?.());const t=Number(p?.getCurrentTime?.()||0);
      if(state===1&&t>.05)return true;
    }catch(_){ }
    try{
      const v=document.getElementById(`native${slot}`);if(v&&!v.paused&&!v.ended&&Number(v.currentTime||0)>.05)return true;
    }catch(_){ }
    return false;
  }
  function recoverStuck(id){
    if(id!==activeSelectionId||lastRecoveredSelection===id)return;
    const session=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{};
    if(actualPlaying(session)){hideTransition(id);return;}
    const state=clean(session.state).toLowerCase();
    if(state==='paused'&&session.userInitiated){hideTransition(id);return;}
    lastRecoveredSelection=id;

    // Visual fail-open is unconditional. Recovery must never own or block the
    // viewer's ability to enter/use the board.
    hideTransition(id);

    try{
      const slot=activeSlotSafe();
      if(typeof handlePlaybackFailure==='function'){
        setTimeout(()=>{
          try{handlePlaybackFailure(slot,new Error('Transition did not prove first-frame playback within 10 seconds'),false);}catch(_){ }
        },0);
        return;
      }
    }catch(_){ }
    setTimeout(()=>{
      try{if(typeof manualQueueAdvance==='function')manualQueueAdvance(1,{reason:'v5.5.0 transition timeout'});}catch(_){ }
    },0);
  }
  function beginProofLoop(id){
    if(proofTimer)clearTimeout(proofTimer);
    const started=performance.now();
    const check=()=>{
      if(id!==activeSelectionId)return;
      const session=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{};
      if(Number(session.selectionId||0)!==id)return;
      if(actualPlaying(session)){hideTransition(id);return;}
      const state=clean(session.state).toLowerCase();
      if(['failed','ended','unavailable'].includes(state)){hideTransition(id);return;}
      if(state==='paused'&&session.userInitiated){hideTransition(id);return;}
      if(performance.now()-started>=10000){recoverStuck(id);return;}
      proofTimer=setTimeout(check,300);
    };
    proofTimer=setTimeout(check,180);
  }
  function armLaunchFailOpen(){
    if(launchFailOpenTimer)clearTimeout(launchFailOpenTimer);
    launchFailOpenTimer=setTimeout(()=>{
      launchFailOpenTimer=null;
      if(!experienceStarted())return;
      const session=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{};
      if(actualPlaying(session))return;
      // startSportsBigBoardExperience() displays the first bumper before a
      // Playback Session necessarily exists. If transaction/session creation
      // fails, onSession() can never clear that bumper, so clear it here.
      clearVisualTransition();
      try{window.dispatchEvent(new CustomEvent('sbb:startup-transition-failopen',{detail:{at:Date.now(),sessionState:clean(session.state)||'none'}}));}catch(_){ }
    },8500);
  }

  function activeContextState(){
    const slot=activeSlotSafe();
    let context=false,timer=false;
    try{context=(typeof slotMedia!=='undefined'&&slotMedia?.[slot]==='context');}catch(_){ }
    try{timer=(typeof contextTimer!=='undefined'&&!!contextTimer?.[slot]);}catch(_){ }
    return {slot,context,timer};
  }
  function nextProgramIndex(){
    const current=currentIndexSafe();
    try{
      if(typeof nextVisibleQueueIndex==='function'){
        const idx=Number(nextVisibleQueueIndex());
        if(Number.isInteger(idx)&&idx>=0&&idx!==current)return idx;
      }
    }catch(_){ }
    try{
      if(typeof PROGRAM!=='undefined'&&Array.isArray(PROGRAM)&&PROGRAM.length>1){
        for(let step=1;step<PROGRAM.length;step++){
          const idx=(current+step)%PROGRAM.length,item=PROGRAM[idx];
          if(!item)continue;
          try{if(typeof isGamePlayed==='function'&&isGamePlayed(item))continue;}catch(_){ }
          // Prefer actual media over another context card when escaping startup.
          let isContext=false;try{isContext=typeof isContextItem==='function'&&isContextItem(item);}catch(_){ }
          if(!isContext)return idx;
        }
        for(let step=1;step<PROGRAM.length;step++){
          const idx=(current+step)%PROGRAM.length,item=PROGRAM[idx];
          if(!item)continue;
          try{if(typeof isGamePlayed==='function'&&isGamePlayed(item))continue;}catch(_){ }
          return idx;
        }
      }
    }catch(_){ }
    return -1;
  }
  function logContextFailOpen(event,detail=''){
    try{fetch(`/api/client-log?event=${encodeURIComponent(event)}&detail=${encodeURIComponent(detail)}`,{cache:'no-store'}).catch(()=>{});}catch(_){ }
  }
  function clearTerminalContext(slot,reason='context completed without next program'){
    clearVisualTransition();
    try{if(typeof setVideoLoadingOverlay==='function')setVideoLoadingOverlay(false);}catch(_){ }
    document.getElementById('videoLoadingOverlay')?.classList.add('hidden');
    let el=null;
    try{if(typeof contextEl==='function')el=contextEl(slot);}catch(_){ }
    if(!el)el=document.getElementById(`context${slot}`);
    el?.classList.add('hidden');
    document.documentElement.dataset.sbbContextFailOpen='waiting';
    contextFailOpenCount++;
    try{if(typeof setPlaybackUi==='function')setPlaybackUi('ready');}catch(_){ }
    try{if(typeof setFeedNote==='function')setFeedNote('Sports Big Board ready • waiting for the next playable program');}catch(_){ }
    logContextFailOpen('CONTEXT_FAILOPEN',`${reason}|slot=${slot}|index=${currentIndexSafe()}|title=${clean(clipSafe()?.title).slice(0,120)}`);
  }
  function resumeFromTerminalContext(target,slot){
    if(target<0)return false;
    contextWaitingSince=0;
    document.documentElement.dataset.sbbContextFailOpen='resuming';
    clearVisualTransition();
    contextResumeCount++;
    logContextFailOpen('CONTEXT_FAILOPEN_RESUME',`slot=${slot}|from=${currentIndexSafe()}|to=${target}|title=${clean(clipSafe()?.title).slice(0,120)}`);
    try{
      if(typeof tuneProgramIndexV5==='function'){
        Promise.resolve(tuneProgramIndexV5(target,{userInitiated:false,reason:'terminal context playable-media resume'})).catch(()=>{});
        return true;
      }
    }catch(_){ }
    try{
      if(typeof manualQueueAdvance==='function')return !!manualQueueAdvance(1);
    }catch(_){ }
    return false;
  }
  function checkTerminalContext(){
    if(!experienceStarted()||document.hidden){contextWaitingSince=0;return;}
    const {slot,context,timer}=activeContextState();
    if(!context){
      contextWaitingSince=0;
      if(document.documentElement.dataset.sbbContextFailOpen==='resuming')delete document.documentElement.dataset.sbbContextFailOpen;
      return;
    }
    if(timer){contextWaitingSince=0;return;}
    if(!contextWaitingSince)contextWaitingSince=performance.now();
    const target=nextProgramIndex();
    if(target>=0){resumeFromTerminalContext(target,slot);return;}
    // Give advanceAfterCompletedItem()/background merge one paint cycle to resolve
    // normally. If it cannot, remove the stale full-stage context so the board is
    // usable while media discovery continues. The guard keeps polling and will
    // automatically tune a newly-arrived program.
    if(performance.now()-contextWaitingSince>=650){
      const marker=document.documentElement.dataset.sbbContextFailOpen;
      if(marker!=='waiting')clearTerminalContext(slot);
    }
  }
  function armContextGuard(){
    if(contextGuardTimer)return;
    contextGuardTimer=setInterval(checkTerminalContext,350);
  }
  function wrapAllCaughtUp(){
    if(wrappedAllCaughtUp)return;
    let original=null;
    try{original=typeof showAllCaughtUp==='function'?showAllCaughtUp:null;}catch(_){ }
    if(!original)return;
    const wrapped=function(...args){
      const before=activeContextState();
      const result=original.apply(this,args);
      if(before.context&&!before.timer){
        // Already terminal; the interval will clear/resume it immediately.
        contextWaitingSince=contextWaitingSince||performance.now()-1000;
      }else if(before.context){
        // pauseSlot() inside showAllCaughtUp clears the timer synchronously.
        contextWaitingSince=performance.now()-1000;
      }
      setTimeout(checkTerminalContext,0);
      return result;
    };
    wrapped.__sbbContextFailOpen=true;
    try{window.showAllCaughtUp=wrapped;}catch(_){ }
    try{showAllCaughtUp=wrapped;}catch(_){ }
    wrappedAllCaughtUp=true;
  }

  function onSession(session){
    const state=clean(session?.state).toLowerCase();
    // The splash owns all pre-launch loading. Never start a transition proof loop
    // while Hot Standby / cueing is preparing the first clip behind the launch card.
    if(!experienceStarted()){setOwned(false);return;}
    if(state==='playing'||Number(session?.firstFrameAt)>0){
      if(launchFailOpenTimer){clearTimeout(launchFailOpenTimer);launchFailOpenTimer=null;}
      if(Number(session?.selectionId)||0)activeSelectionId=Number(session.selectionId)||activeSelectionId;
      hideTransition(Number(session?.selectionId)||activeSelectionId);
      return;
    }
    if(['selected','preparing','starting'].includes(state)||(state==='buffering'&&!session?.firstFrameAt)){
      showTransition(session);return;
    }
    if(['failed','ended','unavailable','idle'].includes(state)){
      hideTransition(Number(session?.selectionId)||activeSelectionId);
    }
  }
  function bind(){
    try{window.SBB_PLAYBACK_SESSION?.subscribe?.(onSession);}catch(_){ }
    wrapAllCaughtUp();
    armContextGuard();
    const launch=document.getElementById('launchPlayBtn');
    if(launch&&launch.dataset.sbbTransitionFailOpen!=='1'){
      launch.dataset.sbbTransitionFailOpen='1';
      launch.addEventListener('click',()=>{armLaunchFailOpen();armContextGuard();},{capture:true});
    }
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
  window.SBB_TRANSITION_BUMPER_V5319=Object.freeze({installed:true,version:VERSION,snapshot:()=>({activeSelectionId,lastShownAt,lastRecoveredSelection,launchFailOpenArmed:!!launchFailOpenTimer,contextGuardArmed:!!contextGuardTimer,contextWaitingSince,contextFailOpenCount,contextResumeCount,contextFailOpenState:document.documentElement.dataset.sbbContextFailOpen||'',owned:document.documentElement.dataset.sbbTransitionBumper==='1'})});
})();

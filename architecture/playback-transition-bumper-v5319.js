/* Sports Big Board v5.4.9 — transition bumper authority, startup-safe.
   v5.4.9 used a MutationObserver on the legacy loading overlay while other
   playback code was also changing that same class. On some browsers those two
   writers could create a hot mutation loop immediately after launch. v5.4.9
   removes DOM observation entirely. Playback Session events own the transition,
   and a CSS state flag hides the raw loading surface while the bumper is active. */
(() => {
  'use strict';
  if(window.SBB_TRANSITION_BUMPER_V5319?.installed)return;
  const VERSION='5.4.9';
  let activeSelectionId=0,proofTimer=null,lastShownAt=0,lastRecoveredSelection=0;
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
    setOwned(false);
    try{if(typeof setVideoLoadingOverlay==='function')setVideoLoadingOverlay(false);}catch(_){ }
    try{if(typeof hideBumper==='function')hideBumper();}catch(_){ }
    if(proofTimer){clearTimeout(proofTimer);proofTimer=null;}
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
    try{
      const slot=activeSlotSafe();
      if(typeof handlePlaybackFailure==='function'){
        handlePlaybackFailure(slot,new Error('Transition did not prove first-frame playback within 10 seconds'),false);
        return;
      }
    }catch(_){ }
    try{if(typeof manualQueueAdvance==='function')manualQueueAdvance(1,{reason:'v5.4.9 transition timeout'});}catch(_){ }
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
      if(['failed','ended','unavailable'].includes(state)){setOwned(false);return;}
      if(state==='paused'&&session.userInitiated){hideTransition(id);return;}
      if(performance.now()-started>=10000){recoverStuck(id);return;}
      proofTimer=setTimeout(check,300);
    };
    proofTimer=setTimeout(check,180);
  }
  function onSession(session){
    const state=clean(session?.state).toLowerCase();
    // The splash owns all pre-launch loading. Never start a transition proof loop
    // while Hot Standby / cueing is preparing the first clip behind the launch card.
    if(!experienceStarted()){setOwned(false);return;}
    if(['selected','preparing','starting'].includes(state)||(state==='buffering'&&!session?.firstFrameAt)){
      showTransition(session);return;
    }
    if(state==='playing'||Number(session?.firstFrameAt)>0){
      if(Number(session?.selectionId)||0)activeSelectionId=Number(session.selectionId)||activeSelectionId;
      hideTransition(Number(session?.selectionId)||activeSelectionId);
    }else if(['failed','ended','unavailable','idle'].includes(state)){
      setOwned(false);
    }
  }
  function bind(){
    try{window.SBB_PLAYBACK_SESSION?.subscribe?.(onSession);}catch(_){ }
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
  window.SBB_TRANSITION_BUMPER_V5319=Object.freeze({installed:true,version:VERSION,snapshot:()=>({activeSelectionId,lastShownAt,lastRecoveredSelection,owned:document.documentElement.dataset.sbbTransitionBumper==='1'})});
})();

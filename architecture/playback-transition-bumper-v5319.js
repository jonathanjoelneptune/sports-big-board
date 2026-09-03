/* Sports Big Board v5.3.19 — transition bumper authority.
   A clip transition must never expose the raw gray buffering surface. Keep the
   existing editorial bumper over the stage until the newly selected transport
   proves first-frame playback, including clip 2+ of the same game's reel. */
(() => {
  'use strict';
  if(window.SBB_TRANSITION_BUMPER_V5319?.installed)return;
  const VERSION='5.3.19';
  let activeSelectionId=0,proofTimer=null,lastShownAt=0,lastRecoveredSelection=0;
  const clean=v=>String(v??'').trim();

  function currentIndexSafe(){try{return Number(currentIndex)||0;}catch(_){return 0;}}
  function activeSlotSafe(){try{return String(activeSlot||'A');}catch(_){return 'A';}}
  function clipSafe(){try{return typeof clip==='function'?clip(currentIndexSafe()):null;}catch(_){return null;}}
  function sameGameTransition(session,item){
    const reason=clean(session?.reason).toLowerCase();
    if(/next|advance|queue|highlight|reel/.test(reason))return true;
    try{
      const idx=currentIndexSafe();if(idx<=0)return false;
      const prev=typeof clip==='function'?clip(idx-1):null;
      return !!(prev&&item&&typeof sameGameProgramItem==='function'&&sameGameProgramItem(prev,item));
    }catch(_){return false;}
  }
  function showTransition(session){
    const id=Number(session?.selectionId)||0;if(!id||id===activeSelectionId)return;
    activeSelectionId=id;lastShownAt=Date.now();
    const item=clipSafe();const label=sameGameTransition(session,item)?'NEXT HIGHLIGHT':'COMING UP NEXT';
    try{if(typeof setVideoLoadingOverlay==='function')setVideoLoadingOverlay(false);}catch(_){ }
    try{if(typeof showBumper==='function')showBumper(currentIndexSafe(),1400,label);}catch(_){ }
    beginProofLoop(id);
  }
  function hideTransition(id=activeSelectionId){
    if(id&&id!==activeSelectionId)return;
    try{if(typeof setVideoLoadingOverlay==='function')setVideoLoadingOverlay(false);}catch(_){ }
    try{if(typeof hideBumper==='function')hideBumper();}catch(_){ }
    if(proofTimer){clearTimeout(proofTimer);proofTimer=null;}
  }
  function actualPlaying(session){
    if(clean(session?.state).toLowerCase()==='playing'||Number(session?.firstFrameAt)>0)return true;
    const slot=activeSlotSafe();
    try{
      if(typeof adapterForSlot==='function'&&adapterForSlot(slot)?.isPlaying?.())return true;
    }catch(_){ }
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
    if(state==='paused'&&session.userInitiated)return;
    lastRecoveredSelection=id;
    try{
      const slot=activeSlotSafe();
      if(typeof handlePlaybackFailure==='function'){
        handlePlaybackFailure(slot,new Error('Transition did not prove first-frame playback within 10 seconds'),false);
        return;
      }
    }catch(_){ }
    try{if(typeof manualQueueAdvance==='function')manualQueueAdvance(1,{reason:'v5.3.19 transition timeout'});}catch(_){ }
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
      if(['failed','ended','unavailable'].includes(state)){return;}
      if(state==='paused'&&session.userInitiated){hideTransition(id);return;}
      if(performance.now()-started>=10000){recoverStuck(id);return;}
      proofTimer=setTimeout(check,250);
    };
    proofTimer=setTimeout(check,160);
  }
  function onSession(session){
    const state=clean(session?.state).toLowerCase();
    if(['selected','preparing','starting'].includes(state)||(state==='buffering'&&!session?.firstFrameAt)){
      showTransition(session);return;
    }
    if(state==='playing'||Number(session?.firstFrameAt)>0){
      if(Number(session?.selectionId)||0)activeSelectionId=Number(session.selectionId)||activeSelectionId;
      hideTransition(Number(session?.selectionId)||activeSelectionId);
    }
  }
  function bind(){
    try{window.SBB_PLAYBACK_SESSION?.subscribe?.(onSession);}catch(_){ }
    // The legacy loading overlay may be asserted milliseconds after a new session.
    // While a first-frame bumper owns the transition, keep that raw overlay hidden.
    const overlay=document.getElementById('videoLoadingOverlay');
    if(overlay&&typeof MutationObserver!=='undefined'){
      new MutationObserver(()=>{
        const session=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{};
        const state=clean(session.state).toLowerCase();
        if(activeSelectionId&&Number(session.selectionId||0)===activeSelectionId&&['selected','preparing','starting','buffering'].includes(state)&&!session.firstFrameAt){
          overlay.classList.add('hidden');
        }
      }).observe(overlay,{attributes:true,attributeFilter:['class']});
    }
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
  window.SBB_TRANSITION_BUMPER_V5319=Object.freeze({installed:true,version:VERSION,snapshot:()=>({activeSelectionId,lastShownAt,lastRecoveredSelection})});
})();

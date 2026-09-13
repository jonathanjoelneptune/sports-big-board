/* Sports Big Board v5.5.0 — user-pause-safe early pause recovery.
   Manual pause is authoritative for the current selection. Automatic recovery now
   requires positive provider evidence that the active transport unexpectedly
   entered PAUSED during startup; stale UI text alone can never restart/reload a
   video. */
(() => {
  'use strict';
  if(window.SBB_EARLY_PAUSE_RECOVERY?.version==='5.5.0')return;
  const VERSION='5.5.0';
  const $=id=>document.getElementById(id);
  const clean=v=>String(v??'').trim();
  const orchestrator=window.SBB_PLAYBACK_ORCHESTRATOR;
  const legacyPauseAll=typeof window.sbbPauseAllPlayback==='function'?window.sbbPauseAllPlayback:null;
  const state={generation:0,key:'',selectedAt:0,manualPause:false,manualPauseKey:'',providerControlInteractionAt:0,providerControlInteractionKey:'',softKicks:0,reloads:0,lastAction:'',lastReason:'',timers:[],events:[],adapterOwned:false};

  function log(action,detail=''){state.lastAction=action;state.lastReason=detail;state.events.push({at:Date.now(),action,detail,key:state.key});if(state.events.length>30)state.events=state.events.slice(-30);try{window.dispatchEvent(new CustomEvent('sbb:early-pause-recovery',{detail:{action,detail,key:state.key}}));}catch(_){}}
  function currentKey(){let index='';try{index=typeof currentIndex!=='undefined'?String(currentIndex):'';}catch(_){}return `${index}|${clean($('currentTitle')?.textContent)}`;}
  function currentTransaction(){try{return clean(orchestrator?.snapshot?.()?.transactionId);}catch(_){return '';}}
  function setCanonicalManualPause(value){try{if(typeof manualPauseRequested!=='undefined')manualPauseRequested=!!value;}catch(_){} }
  function userPaused(){return !!(state.manualPause&&state.manualPauseKey===state.key);}
  function markUserPause(reason){state.manualPause=true;state.manualPauseKey=state.key||currentKey();setCanonicalManualPause(true);log('USER_PAUSE_SUPPRESS',reason);}
  function clearUserPause(reason='resume'){if(state.manualPause)log('USER_PAUSE_RELEASE',reason);state.manualPause=false;state.manualPauseKey='';setCanonicalManualPause(false);}
  function activeSlotName(){try{return clean(typeof activeSlot!=='undefined'?activeSlot:'');}catch(_){return '';}}
  function providerState(){
    const slot=activeSlotName();
    try{const p=(typeof players!=='undefined')?players?.[slot]:null;if(p){const s=Number(p.getPlayerState?.());return {kind:'YOUTUBE',slot,state:s,paused:s===2,playing:s===1,buffering:s===3,ended:s===0};}}catch(_){}
    try{const v=(typeof nativeEl==='function')?nativeEl(slot):$('native'+slot);if(v)return {kind:'DIRECT_VIDEO',slot,state:v.readyState,paused:!!v.paused&&!v.ended,playing:!v.paused&&!v.ended,buffering:!v.paused&&v.readyState<3,ended:!!v.ended};}catch(_){}
    return {kind:'UNKNOWN',slot,state:'unknown',paused:false,playing:false,buffering:false,ended:false};
  }
  function confirmProviderPause(){if(state.providerControlInteractionKey!==state.key)return;const sample=providerState();if(sample.paused)markUserPause('embedded provider pause');}
  function noteProviderControlInteraction(){const active=document.activeElement;if(active?.tagName==='IFRAME'&&/youtube(?:-nocookie)?\.com/i.test(clean(active.src))){state.providerControlInteractionAt=Date.now();state.providerControlInteractionKey=state.key||currentKey();log('PROVIDER_CONTROL_INTERACTION','youtube iframe focus');for(const ms of [80,250,650,1100])setTimeout(confirmProviderPause,ms);return true;}return false;}
  function providerControlPauseLikely(){return state.providerControlInteractionKey===state.key&&state.providerControlInteractionAt>=state.selectedAt&&Date.now()-state.providerControlInteractionAt<10000;}

  function installAdapterOwnership(){
    if(!orchestrator?.extendAdapter)return false;
    const extended=orchestrator.extendAdapter({
      pauseAll:()=>legacyPauseAll?legacyPauseAll():false,
      resumeActive:({sample}={})=>{
        const currentSample=sample||providerState();let acted=false;
        try{
          if(currentSample.kind==='YOUTUBE'){
            const p=(typeof players!=='undefined')?players?.[currentSample.slot]:null;p?.playVideo?.();acted=!!p;
          }else if(currentSample.kind==='DIRECT_VIDEO'){
            const v=(typeof nativeEl==='function')?nativeEl(currentSample.slot):$('native'+currentSample.slot);const promise=v?.play?.();promise?.catch?.(()=>{});acted=!!v;
          }
        }catch(_){}
        return acted;
      },
      recoverActive:({index,userInitiated=false,reason='adapter recovery'}={})=>{
        const i=Number(index);
        if(!Number.isInteger(i)||i<0||typeof window.SBB_PLAYBACK_CONTROLLER?.tuneProgramIndex!=='function')return false;
        return window.SBB_PLAYBACK_CONTROLLER.tuneProgramIndex(i,{userInitiated,reason});
      }
    });
    state.adapterOwned=!!extended;
    if(extended&&legacyPauseAll&&orchestrator.requestPauseAll){
      const ownedPauseAll=function(){const requested=orchestrator.requestPauseAll('application pause');return requested===false?legacyPauseAll():requested;};
      ownedPauseAll.__sbbOwnershipP1=true;
      try{window.sbbPauseAllPlayback=ownedPauseAll;sbbPauseAllPlayback=ownedPauseAll;}catch(_){window.sbbPauseAllPlayback=ownedPauseAll;}
    }
    return !!extended;
  }

  function softResume(sample){
    if(userPaused()||providerControlPauseLikely()||!sample.paused)return false;
    const tx=currentTransaction();
    if(orchestrator?.requestResumeActive&&tx){
      const requested=orchestrator.requestResumeActive(tx,{sample,reason:'confirmed unexpected startup pause'});
      if(requested!==false){Promise.resolve(requested).catch(()=>{});state.softKicks++;log('SOFT_RESUME','adapter-owned positive unexpected PAUSED state');return true;}
    }
    return false;
  }
  function boundedSameItemRecovery(){
    if(userPaused()||providerControlPauseLikely())return false;const sample=providerState();
    if(!sample.paused)return false; // Never reload a transport that is already playing/buffering.
    let index=-1;try{index=Number(typeof currentIndex!=='undefined'?currentIndex:-1);}catch(_){}
    const tx=currentTransaction();
    if(orchestrator?.requestRecovery&&tx&&Number.isInteger(index)&&index>=0){
      const requested=orchestrator.requestRecovery(tx,{index,userInitiated:false,reason:'v5.5.0 confirmed unexpected startup pause'});
      Promise.resolve(requested).catch(()=>{});state.reloads++;log('BOUNDED_RECOVERY','adapter-owned same item after confirmed paused state');return true;
    }
    return false;
  }
  function clearTimers(){for(const timer of state.timers)clearTimeout(timer);state.timers=[];}
  function schedule(reason='selection'){
    const key=currentKey();if(!key||/Loading highlight/i.test(key))return;if(key===state.key&&Date.now()-state.selectedAt<2500)return;
    const changed=key!==state.key;state.key=key;state.generation++;state.selectedAt=Date.now();clearTimers();if(changed){clearUserPause('new selection');state.providerControlInteractionAt=0;state.providerControlInteractionKey='';}
    const generation=state.generation;log('ARM',reason);
    state.timers.push(setTimeout(()=>{if(generation!==state.generation||userPaused())return;const sample=providerState();if(sample.paused&&!providerControlPauseLikely())softResume(sample);},5200));
    state.timers.push(setTimeout(()=>{if(generation!==state.generation||userPaused())return;boundedSameItemRecovery();},8200));
  }
  function bindUserIntent(){
    const play=$('playBtn');
    play?.addEventListener('click',()=>{const sample=providerState();if(sample.playing||sample.buffering)markUserPause('play button');else clearUserPause('play button resume');},true);
    document.addEventListener('keydown',event=>{if(event.code!=='Space'||event.repeat)return;const tag=clean(event.target?.tagName).toUpperCase();if(/INPUT|TEXTAREA|SELECT/.test(tag)||event.target?.isContentEditable)return;const sample=providerState();if(sample.playing||sample.buffering)markUserPause('space key');else clearUserPause('space key resume');},true);
    window.addEventListener('blur',()=>setTimeout(noteProviderControlInteraction,0),true);
    document.addEventListener('focusin',event=>{const frame=event.target;if(frame?.tagName==='IFRAME'&&/youtube(?:-nocookie)?\.com/i.test(clean(frame.src)))noteProviderControlInteraction();},true);
  }
  function bind(){installAdapterOwnership();bindUserIntent();const title=$('currentTitle');if(title)new MutationObserver(()=>setTimeout(()=>schedule('title change'),0)).observe(title,{subtree:true,childList:true,characterData:true});window.addEventListener('sbb:curated-event-identity',()=>setTimeout(()=>schedule('curated selection'),0));window.addEventListener('sbb:score-click-selection',()=>setTimeout(()=>schedule('score selection'),0));setTimeout(()=>schedule('startup'),900);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
  window.SBB_EARLY_PAUSE_RECOVERY=Object.freeze({version:VERSION,arm:schedule,snapshot:()=>({generation:state.generation,key:state.key,selectedAt:state.selectedAt,userPauseSuppressed:userPaused(),manualPause:state.manualPause,providerControlInteractionAt:state.providerControlInteractionAt,softKicks:state.softKicks,reloads:state.reloads,adapterOwned:state.adapterOwned,lastAction:state.lastAction,lastReason:state.lastReason,events:state.events.slice()})});
})();

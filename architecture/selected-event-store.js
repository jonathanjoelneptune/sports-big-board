/* Sports Big Board v5.0.0 — SelectedEvent authority.
   Sporting-event identity is independent of media/player state. Player callbacks
   cannot replace or clear the selected score event while a v5 playback transaction
   owns it. Game Center subscribes to this store only. */
(() => {
  'use strict';
  if(window.SBB_SELECTED_EVENT?.version==='5.0.0')return;
  let current=null;
  let revision=0;
  const listeners=new Set();
  const clean=v=>String(v??'').trim();
  function snapshot(){return current?{...current}:null;}
  function keyOf(eventLike){
    if(!eventLike)return '';
    try{return clean(window.SBB_EVENT_IDENTITY?.key?.(eventLike));}catch(_){ }
    return clean(eventLike.canonicalEventKey||eventLike.canonicalEventId||eventLike.espnEventId||eventLike.scoreEventId||eventLike.eventId||eventLike.matchId||eventLike.id);
  }
  function activePlayback(){try{return window.SBB_APP_STORE?.snapshot?.().playback||null;}catch(_){return null;}}
  function legacyPlaybackMutation(meta={}){
    const source=clean(meta.source).toLowerCase();
    return source==='playback'||source==='playback-confirmed'||source==='program'||source==='native-playing'||source==='youtube-playing';
  }
  function protectedByV5(){
    const pb=activePlayback();
    return !!(current&&pb?.transactionId&&pb?.eventKey&&keyOf(current)===pb.eventKey);
  }
  function emit(meta){
    const snap=snapshot();
    for(const fn of [...listeners]){try{fn(snap,{revision,...meta});}catch(e){console.warn('[SBB SelectedEvent listener]',e);}}
    try{window.dispatchEvent(new CustomEvent('sbb:selected-event',{detail:{event:snap,revision,...meta}}));}catch(_){ }
  }
  function select(eventLike,meta={}){
    if(!eventLike)return clear(meta);
    const core=window.SBB_CORE;
    const canonical=core?.event?core.event(eventLike,eventLike?.competitionId||eventLike?.__sbbLeague||eventLike?.league):{...eventLike};
    const identity=keyOf(canonical);
    // The active v5 transaction owns the sporting event. Sparse media metadata or
    // late provider callbacks may refresh the SAME event, but cannot redirect it.
    if(protectedByV5()&&legacyPlaybackMutation(meta)){
      const pb=activePlayback();
      if(identity&&pb?.eventKey&&identity!==pb.eventKey)return snapshot();
      if(current)return snapshot();
    }
    // Keep the richer resident score event when a later same-event media object is
    // sparse. Score ribbon / v5 orchestrator selections remain allowed to replace it.
    if(current&&identity&&keyOf(current)===identity&&legacyPlaybackMutation(meta))return snapshot();
    current={...canonical,canonicalEventKey:identity,selectedAt:Date.now(),selectionReason:clean(meta.reason),selectionSource:clean(meta.source)};
    revision++;
    if(!meta.storeAlreadySelected){try{window.SBB_APP_STORE?.dispatch?.({type:'SELECT_EVENT',payload:{event:current,eventKey:identity,source:current.selectionSource,reason:current.selectionReason}});}catch(_){ }}
    emit({action:'select',...meta});
    return snapshot();
  }
  function clear(meta={}){
    // Player/media code is not allowed to destroy event ownership underneath an
    // active transaction. Only the orchestrator/user-navigation path may do so.
    if(protectedByV5()&&legacyPlaybackMutation(meta))return snapshot();
    if(!current){
      if(!meta.storeAlreadySelected){try{window.SBB_APP_STORE?.dispatch?.({type:'CLEAR_EVENT',payload:{source:clean(meta.source),reason:clean(meta.reason)}});}catch(_){ }}
      return null;
    }
    current=null;revision++;
    if(!meta.storeAlreadySelected){try{window.SBB_APP_STORE?.dispatch?.({type:'CLEAR_EVENT',payload:{source:clean(meta.source),reason:clean(meta.reason)}});}catch(_){ }}
    emit({action:'clear',...meta});
    return null;
  }
  function subscribe(fn,{emitCurrent=false}={}){if(typeof fn!=='function')return()=>{};listeners.add(fn);if(emitCurrent)fn(snapshot(),{revision,action:'snapshot'});return()=>listeners.delete(fn);}
  window.SBB_SELECTED_EVENT=Object.freeze({version:'5.0.0',select,clear,get:snapshot,subscribe,keyOf,get revision(){return revision;}});
})();

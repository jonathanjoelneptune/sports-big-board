/* Sports Big Board v5.0.0 — Unified Runtime App Store.
   One reducer-owned state tree is the canonical browser control plane. UI modules,
   playback preparation, player adapters and Game Center consume this state; they do
   not independently reconstruct ownership from media/player callbacks. */
(() => {
  'use strict';
  if (window.SBB_APP_STORE?.version === '5.0.0') return;

  const VERSION='5.0.0';
  const SCHEMA='1.0';
  const listeners=new Set();
  let revision=0;
  let intentSequence=0;

  const clone=value=>{
    try{return structuredClone(value);}catch(_){return JSON.parse(JSON.stringify(value));}
  };
  const clean=value=>String(value??'').trim();
  const now=()=>Date.now();
  const eventKeyOf=eventLike=>{
    if(!eventLike)return '';
    try{return clean(window.SBB_EVENT_IDENTITY?.key?.(eventLike));}catch(_){ }
    const competition=clean(eventLike.competitionId||eventLike.__sbbLeague||eventLike.league).toUpperCase();
    const id=clean(eventLike.canonicalEventId||eventLike.espnEventId||eventLike.scoreEventId||eventLike.eventId||eventLike.matchId||eventLike.gamePk||eventLike.id);
    return competition&&id?`${competition}:${id}`:id;
  };
  const freshPlayback=()=>({
    transactionId:'',intentId:0,state:'IDLE',source:'',reason:'',userInitiated:false,
    eventKey:'',event:null,requestedAt:0,updatedAt:0,
    mediaPlan:[],candidateIndex:-1,activeMediaKey:'',provider:'',transport:'',
    attempts:0,recoveries:0,progressSeconds:0,lastProgressAt:0,error:'',
    prewarm:{state:'IDLE',mediaKey:'',startedAt:0,completedAt:0,result:''},
    legacySelectionId:0
  });
  const initialState=()=>({
    version:VERSION,schema:SCHEMA,revision:0,
    browse:{date:'',leagueFilter:'ALL'},
    selection:{event:null,eventKey:'',source:'',reason:'',selectedAt:0},
    playback:freshPlayback(),
    gameCenter:{eventKey:'',state:'IDLE',updatedAt:0,error:''},
    invariant:'OK',lastAction:'BOOT'
  });
  let state=initialState();

  function audit(next){
    let invariant='OK';
    const playback=next.playback||{};
    const selection=next.selection||{};
    if(playback.transactionId&&playback.eventKey){
      if(!selection.eventKey) invariant='ERROR: PLAYBACK EVENT WITHOUT SELECTED EVENT';
      else if(selection.eventKey!==playback.eventKey) invariant=`ERROR: EVENT OWNERSHIP ${selection.eventKey} != ${playback.eventKey}`;
    }
    if(next.gameCenter?.eventKey&&selection.eventKey&&next.gameCenter.eventKey!==selection.eventKey){
      invariant=`ERROR: GAME CENTER ${next.gameCenter.eventKey} != SELECTED ${selection.eventKey}`;
    }
    next.invariant=invariant;
    return next;
  }
  function emit(action){
    const snap=snapshot();
    try{window.dispatchEvent(new CustomEvent('sbb:app-state',{detail:{state:snap,action}}));}catch(_){ }
    for(const fn of [...listeners]){try{fn(snap,action);}catch(err){console.warn('[SBB v5 app-store] listener failed',err);}}
  }
  function reduce(current,action){
    const next=clone(current); const type=clean(action?.type).toUpperCase(); const payload=action?.payload||{};
    next.lastAction=type||'UNKNOWN';
    switch(type){
      case 'BROWSE_SET':
        if(payload.date!=null)next.browse.date=clean(payload.date).slice(0,10);
        if(payload.leagueFilter!=null)next.browse.leagueFilter=clean(payload.leagueFilter).toUpperCase()||'ALL';
        break;
      case 'SELECT_EVENT': {
        const event=payload.event?clone(payload.event):null; const eventKey=clean(payload.eventKey)||eventKeyOf(event);
        next.selection={event,eventKey,source:clean(payload.source),reason:clean(payload.reason),selectedAt:now()};
        next.gameCenter={eventKey,state:eventKey?'SELECTED':'IDLE',updatedAt:now(),error:''};
        break;
      }
      case 'CLEAR_EVENT':
        next.selection={event:null,eventKey:'',source:clean(payload.source),reason:clean(payload.reason),selectedAt:now()};
        next.gameCenter={eventKey:'',state:'IDLE',updatedAt:now(),error:''};
        break;
      case 'PLAYBACK_INTENT_BEGIN': {
        const event=payload.event?clone(payload.event):null; const eventKey=clean(payload.eventKey)||eventKeyOf(event);
        const intentId=++intentSequence;
        // v5 atomic ownership boundary: selecting the sporting event and opening its
        // playback transaction are one reducer commit. No listener can observe a
        // new selected game paired with the previous playback transaction.
        next.selection={event,eventKey,source:clean(payload.source)||'program',reason:clean(payload.reason),selectedAt:now()};
        next.gameCenter={eventKey,state:eventKey?'SELECTED':'IDLE',updatedAt:now(),error:''};
        next.playback={...freshPlayback(),transactionId:`pb-${now().toString(36)}-${intentId.toString(36)}`,intentId,
          state:'INTENT',source:clean(payload.source)||'program',reason:clean(payload.reason),userInitiated:!!payload.userInitiated,
          eventKey,event,requestedAt:now(),updatedAt:now()};
        break;
      }
      case 'PLAYBACK_PLAN':
        if(payload.transactionId&&payload.transactionId!==next.playback.transactionId)break;
        next.playback.mediaPlan=Array.isArray(payload.mediaPlan)?clone(payload.mediaPlan):[];
        next.playback.updatedAt=now();
        break;
      case 'PLAYBACK_PREPARING':
        if(payload.transactionId&&payload.transactionId!==next.playback.transactionId)break;
        next.playback.state='PREPARING';next.playback.updatedAt=now();
        next.playback.prewarm={state:'PREPARING',mediaKey:clean(payload.mediaKey),startedAt:now(),completedAt:0,result:''};
        break;
      case 'PLAYBACK_PREWARM_RESULT':
        if(payload.transactionId&&payload.transactionId!==next.playback.transactionId)break;
        next.playback.prewarm={...next.playback.prewarm,state:payload.ok?'READY':'FAILED',completedAt:now(),result:clean(payload.result)};
        next.playback.updatedAt=now();
        break;
      case 'PLAYBACK_MEDIA_SELECTED':
        if(payload.transactionId&&payload.transactionId!==next.playback.transactionId)break;
        next.playback.state='SELECTED';next.playback.activeMediaKey=clean(payload.mediaKey);next.playback.provider=clean(payload.provider);next.playback.transport=clean(payload.transport);next.playback.candidateIndex=Number.isFinite(payload.candidateIndex)?payload.candidateIndex:next.playback.candidateIndex;next.playback.updatedAt=now();
        break;
      case 'PLAYBACK_STARTING':
        if(payload.transactionId&&payload.transactionId!==next.playback.transactionId)break;
        next.playback.state='STARTING';next.playback.attempts+=1;next.playback.updatedAt=now();break;
      case 'PLAYBACK_PLAYING':
        if(payload.transactionId&&payload.transactionId!==next.playback.transactionId)break;
        next.playback.state='PLAYING';next.playback.updatedAt=now();next.playback.error='';break;
      case 'PLAYBACK_PROGRESS':
        if(payload.transactionId&&payload.transactionId!==next.playback.transactionId)break;
        next.playback.state='PLAYING';next.playback.progressSeconds=Math.max(next.playback.progressSeconds,Number(payload.seconds)||0);next.playback.lastProgressAt=now();next.playback.updatedAt=now();break;
      case 'PLAYBACK_RECOVERING':
        if(payload.transactionId&&payload.transactionId!==next.playback.transactionId)break;
        next.playback.state='RECOVERING';next.playback.recoveries+=1;next.playback.error=clean(payload.error);next.playback.updatedAt=now();break;
      case 'PLAYBACK_FAILED':
      case 'PLAYBACK_UNAVAILABLE':
        if(payload.transactionId&&payload.transactionId!==next.playback.transactionId)break;
        next.playback.state=type==='PLAYBACK_FAILED'?'FAILED':'UNAVAILABLE';next.playback.error=clean(payload.error||payload.reason);next.playback.updatedAt=now();break;
      case 'PLAYBACK_ENDED':
        if(payload.transactionId&&payload.transactionId!==next.playback.transactionId)break;
        next.playback.state='ENDED';next.playback.updatedAt=now();break;
      case 'PLAYBACK_LEGACY_SELECTION':
        if(payload.transactionId&&payload.transactionId!==next.playback.transactionId)break;
        next.playback.legacySelectionId=Number(payload.selectionId)||0;next.playback.updatedAt=now();break;
      case 'PLAYBACK_RESET':
        next.playback=freshPlayback();break;
      case 'GAME_CENTER_STATE':
        if(payload.eventKey&&next.selection.eventKey&&payload.eventKey!==next.selection.eventKey)break;
        next.gameCenter={eventKey:clean(payload.eventKey)||next.selection.eventKey,state:clean(payload.state)||'IDLE',updatedAt:now(),error:clean(payload.error)};break;
      default: return current;
    }
    next.revision=++revision;
    return audit(next);
  }
  function dispatch(action){
    const next=reduce(state,action);
    if(next===state)return snapshot();
    state=next;emit(action);return snapshot();
  }
  function snapshot(){return clone(state);}
  function subscribe(fn,{emitCurrent=false}={}){if(typeof fn!=='function')return()=>{};listeners.add(fn);if(emitCurrent)try{fn(snapshot(),{type:'SNAPSHOT'});}catch(_){}return()=>listeners.delete(fn);}
  function currentTransaction(){return state.playback.transactionId||'';}
  function transactionActive(id=''){const tx=clean(id)||currentTransaction();return !!tx&&tx===state.playback.transactionId&&!['IDLE','ENDED','FAILED','UNAVAILABLE'].includes(state.playback.state);}

  window.SBB_APP_STORE=Object.freeze({version:VERSION,schema:SCHEMA,dispatch,snapshot,subscribe,eventKeyOf,currentTransaction,transactionActive});
})();

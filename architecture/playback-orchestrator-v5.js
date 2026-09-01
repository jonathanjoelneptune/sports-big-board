/* Sports Big Board v5.0.7 — Playback Orchestrator.
   This is the only browser service allowed to own a playback transaction. Media
   preparation and the legacy A/B implementation are adapters beneath this layer;
   they cannot own SelectedEvent or create competing application state. */
(() => {
  'use strict';
  if(window.SBB_PLAYBACK_ORCHESTRATOR?.version==='5.0.7')return;
  const VERSION='5.0.7';
  const store=window.SBB_APP_STORE;
  if(!store)throw new Error('v5 Playback Orchestrator requires SBB_APP_STORE');
  let adapter=null;
  let adapterBoundAt=0;

  const clean=v=>String(v??'').trim();
  const mediaKey=item=>{
    if(!item)return '';
    try{return clean(window.SBB_PLAYBACK_TRANSPORTS?.mediaKey?.(item));}catch(_){ }
    if(item.youtubeId)return `youtube:${item.youtubeId}`;
    if(item.mediaUrl)return `direct:${item.mediaUrl}`;
    if(item.externalUrl)return `external:${item.externalUrl}`;
    return clean(item.id||item.assetId||item.mediaId);
  };
  const eventKey=eventLike=>store.eventKeyOf(eventLike);
  const eventFrom=eventLike=>{
    if(!eventLike)return null;
    try{return window.SBB_CORE?.event?.(eventLike,eventLike.competitionId||eventLike.__sbbLeague||eventLike.league)||{...eventLike};}catch(_){return {...eventLike};}
  };
  const current=()=>store.playbackSnapshot?.()||store.snapshot().playback;
  const txMatches=id=>!!id&&current().transactionId===id;
  const descriptor=item=>({
    mediaKey:mediaKey(item),title:clean(item?.title||item?.name),provider:clean(item?.provider||item?.source||item?.sourceLabel),
    transport:item?.youtubeId?'YOUTUBE_EMBED':(item?.mediaUrl?'DIRECT_VIDEO':(item?.externalUrl?'EXTERNAL':'CONTEXT')),
    tier:clean(item?.tier||item?.mediaTier||item?.programType),duration:Number(item?.duration||item?.durationSeconds||0)||0
  });

  function selectEvent(authority,{source='v5-orchestrator',reason='playback intent',storeAlreadySelected=false}={}){
    if(!authority){window.SBB_SELECTED_EVENT?.clear?.({source,reason,storeAlreadySelected});return null;}
    return window.SBB_SELECTED_EVENT?.select?.(authority,{source,reason,storeAlreadySelected})||authority;
  }
  function beginIntent(authority,{source='program',reason='playback intent',userInitiated=false}={}){
    const event=authority?eventFrom(authority):null;
    const key=eventKey(event);
    // App Store commits event selection + playback intent atomically. The legacy
    // SelectedEvent pub/sub mirror is updated afterward without redispatching state.
    const state=store.dispatch({type:'PLAYBACK_INTENT_BEGIN',payload:{event,eventKey:key,source,reason,userInitiated}});
    const tx=state.playback.transactionId;
    const selected=event?selectEvent(event,{source:'v5-orchestrator',reason,storeAlreadySelected:true}):(selectEvent(null,{source:'v5-orchestrator',reason,storeAlreadySelected:true}),null);
    try{
      if(window.SBB_PLAYBACK_SESSION?.beginIntent)window.SBB_PLAYBACK_SESSION.beginIntent({transactionId:tx,eventKey:key,title:selected?.name||selected?.title||event?.name||event?.title||'',league:selected?.competitionId||selected?.__sbbLeague||selected?.league||event?.competitionId||event?.league||'',reason,userInitiated});
      else window.SBB_PLAYBACK_SESSION?.select?.({eventKey:key,title:selected?.name||selected?.title||event?.name||event?.title||'',league:selected?.competitionId||selected?.__sbbLeague||selected?.league||event?.competitionId||event?.league||'',reason:`v5 intent: ${reason}`,userInitiated,transport:'PENDING'});
    }catch(_){ }
    return tx;
  }
  function beginScoreIntent(match,meta={}){return beginIntent(match,{...meta,source:'score',reason:meta.reason||'score-card selection',userInitiated:meta.userInitiated!==false});}
  function beginProgramIntent(item,meta={}){
    const collection=!!window.SBB_MEDIA_SCOPE?.isCollection?.(item);
    const gameLike=!collection&&!item?.eventType&&item?.programType!=='context';
    let authority=null;
    if(gameLike){
      const selected=window.SBB_SELECTED_EVENT?.get?.();
      if(selected&&eventKey(selected)&&eventKey(selected)===eventKey(item))authority=selected;
      else authority=item;
    }
    return beginIntent(authority,{...meta,source:collection?'collection':'program',reason:meta.reason||'program tune'});
  }
  function setPlan(transactionId,items=[],meta={}){
    if(!txMatches(transactionId))return false;
    const plan=(Array.isArray(items)?items:[]).filter(Boolean).map((item,index)=>({...descriptor(item),index}));
    store.dispatch({type:'PLAYBACK_PLAN',payload:{transactionId,mediaPlan:plan}});
    return plan;
  }
  function preparing(transactionId,item,meta={}){
    if(!txMatches(transactionId))return false;
    store.dispatch({type:'PLAYBACK_PREPARING',payload:{transactionId,mediaKey:mediaKey(item),...meta}});return true;
  }
  function prewarmResult(transactionId,item,{ok=false,result=''}={}){
    if(!txMatches(transactionId))return false;
    store.dispatch({type:'PLAYBACK_PREWARM_RESULT',payload:{transactionId,mediaKey:mediaKey(item),ok,result}});return true;
  }
  function candidateAttempt(transactionId,item,{candidateIndex=-1}={}){
    if(!txMatches(transactionId)||!item)return false;
    store.dispatch({type:'PLAYBACK_CANDIDATE_ATTEMPT',payload:{transactionId,mediaKey:mediaKey(item),candidateIndex}});return true;
  }
  function candidateRejected(transactionId,item,reason='candidate rejected'){
    if(!txMatches(transactionId)||!item)return false;
    store.dispatch({type:'PLAYBACK_CANDIDATE_REJECTED',payload:{transactionId,mediaKey:mediaKey(item),reason}});return true;
  }
  function planExhausted(transactionId,reason='media plan exhausted'){
    if(!txMatches(transactionId))return false;
    store.dispatch({type:'PLAYBACK_PLAN_EXHAUSTED',payload:{transactionId,reason}});return true;
  }
  function selectMedia(transactionId,item,{candidateIndex=0}={}){
    if(!txMatches(transactionId)||!item)return false;
    const d=descriptor(item);store.dispatch({type:'PLAYBACK_MEDIA_SELECTED',payload:{transactionId,candidateIndex,...d}});return true;
  }
  function recovering(transactionId,error=''){if(!txMatches(transactionId))return false;store.dispatch({type:'PLAYBACK_RECOVERING',payload:{transactionId,error}});return true;}
  function unavailable(transactionId,reason='No playable media available'){if(!txMatches(transactionId))return false;store.dispatch({type:'PLAYBACK_UNAVAILABLE',payload:{transactionId,reason}});return true;}
  function failed(transactionId,error='Playback failed'){if(!txMatches(transactionId))return false;store.dispatch({type:'PLAYBACK_FAILED',payload:{transactionId,error}});return true;}
  function ended(transactionId){if(!txMatches(transactionId))return false;store.dispatch({type:'PLAYBACK_ENDED',payload:{transactionId}});return true;}

  function bindAdapter(next){
    if(adapter)return false;
    if(!next||typeof next.tuneProgramIndex!=='function')throw new Error('v5 playback adapter must expose tuneProgramIndex');
    adapter=Object.freeze({...next});adapterBoundAt=Date.now();return true;
  }
  function requestTune(transactionId,index,options={}){
    if(!txMatches(transactionId))return Promise.reject(new Error('stale v5 playback transaction'));
    if(!adapter)return Promise.reject(new Error('v5 playback adapter is not bound'));
    store.dispatch({type:'PLAYBACK_STARTING',payload:{transactionId}});
    return Promise.resolve(adapter.tuneProgramIndex(index,options));
  }
  function requestPreparedPromotion(transactionId,slot,index,options={}){
    if(!txMatches(transactionId))return Promise.reject(new Error('stale v5 playback transaction'));
    if(!adapter||typeof adapter.promotePrepared!=='function')return requestTune(transactionId,index,{...options,reason:options.reason||'prepared promotion fallback'});
    store.dispatch({type:'PLAYBACK_STARTING',payload:{transactionId}});
    return Promise.resolve(adapter.promotePrepared(slot,index,options));
  }
  function tuneProgramIndex(index,options={}){
    let tx=current().transactionId;
    const scoreSession=window.SBB_V5_SCORE_SESSION?.current?.()||null;
    if(scoreSession?.transactionId&&txMatches(scoreSession.transactionId))tx=scoreSession.transactionId;
    if(!tx||!store.transactionActive(tx)){
      const item=typeof window.SBB_V5_LEGACY_CLIP==='function'?window.SBB_V5_LEGACY_CLIP(index):null;
      tx=beginProgramIntent(item,{reason:options.reason||'program tune',userInitiated:!!options.userInitiated});
      if(item)selectMedia(tx,item,{candidateIndex:index});
    }
    return requestTune(tx,index,options);
  }
  function ownershipSnapshot(){
    const snap=store.snapshot(),selected=window.SBB_SELECTED_EVENT?.get?.()||null;
    const selectedKey=eventKey(selected),expected=snap.playback.eventKey||'';
    return {transactionId:snap.playback.transactionId,state:snap.playback.state,eventKey:expected,selectedEventKey:selectedKey,
      owned:expected?selectedKey===expected:!selectedKey,invariant:snap.invariant};
  }
  function ownsSelectedEvent(){return ownershipSnapshot().owned;}
  function cancel(reason='cancelled'){
    const tx=current().transactionId;if(tx&&store.transactionActive(tx))store.dispatch({type:'PLAYBACK_FAILED',payload:{transactionId:tx,error:reason}});
    return true;
  }

  // Playback Session is telemetry/adapter truth below the v5 transaction. Mirror
  // provider progress upward, but never let those callbacks modify SelectedEvent.
  // v5.0.1: Playback Session may emit provider metadata/audibility updates while
  // the transport state itself is unchanged. Mirror only material state changes
  // upward. This breaks the old 250 ms native-video feedback fanout that could
  // repeatedly clone/render application state while the video kept playing.
  try{window.SBB_PLAYBACK_SESSION?.subscribe?.(session=>{
    const pb=current();if(!pb.transactionId)return;
    const sessionEvent=clean(session?.eventKey);if(pb.eventKey&&sessionEvent&&pb.eventKey!==sessionEvent)return;
    const selectionId=Number(session?.selectionId)||0;
    if(selectionId&&selectionId!==Number(pb.legacySelectionId||0))store.dispatch({type:'PLAYBACK_LEGACY_SELECTION',payload:{transactionId:pb.transactionId,selectionId}});
    const sessionState=clean(session?.state).toLowerCase();
    const appState=clean((store.playbackSnapshot?.()||current()).state).toLowerCase();
    if(sessionState==='playing'&&appState!=='playing')store.dispatch({type:'PLAYBACK_PLAYING',payload:{transactionId:pb.transactionId}});
    else if(sessionState==='failed'&&appState!=='failed')store.dispatch({type:'PLAYBACK_FAILED',payload:{transactionId:pb.transactionId,error:session?.lastError}});
    else if(sessionState==='ended'&&appState!=='ended')store.dispatch({type:'PLAYBACK_ENDED',payload:{transactionId:pb.transactionId}});
  });}catch(_){ }

  window.SBB_PLAYBACK_ORCHESTRATOR=Object.freeze({version:VERSION,beginIntent,beginScoreIntent,beginProgramIntent,setPlan,preparing,prewarmResult,candidateAttempt,candidateRejected,planExhausted,selectMedia,recovering,unavailable,failed,ended,bindAdapter,requestTune,requestPreparedPromotion,tuneProgramIndex,ownershipSnapshot,ownsSelectedEvent,snapshot:()=>store.snapshot().playback,adapterSnapshot:()=>({bound:!!adapter,boundAt:adapterBoundAt})});
})();

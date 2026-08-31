/* Sports Big Board v5.0.0 playback adapter/session telemetry.
   SBB_APP_STORE + SBB_PLAYBACK_ORCHESTRATOR own the application transaction.
   This module remains the transport/session telemetry boundary beneath that owner. */
(() => {
  'use strict';
  if (window.SBB_PLAYBACK_SESSION) return;

  const listeners = new Set();
  let sequence = 0;
  const telemetryTimers = new Set();
  let state = freshState();

  function nowPerf(){ return (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now(); }
  function nowEpoch(){ return Date.now(); }
  function freshState(){
    return {
      version:'2.0', transactionId:'', intentId:0, sessionId:'', selectionId:0, state:'idle', previousState:'',
      selectedAt:0, selectedPerf:0, firstFrameAt:0, firstFrameMs:null,
      eventKey:'', mediaKey:'', clipKey:'', title:'', league:'', provider:'', transport:'', slot:'',
      sourceUrl:'', sourceExternalUrl:'', reason:'', userInitiated:false,
      stallCount:0, stallTotalMs:0, stallStartedPerf:0, lastStallMs:0,
      failureCount:0, lastError:'', lastTransitionAt:0,
      audible:{videoA:false,videoB:false,soundtrack:false}, invariant:'OK'
    };
  }
  function clone(value){ return JSON.parse(JSON.stringify(value)); }
  function emit(){
    const snap=clone(state);
    for(const fn of [...listeners]){ try{fn(snap);}catch(err){console.warn('[SBB playback-session] listener failed',err);} }
    try{ window.dispatchEvent(new CustomEvent('sbb:playback-session',{detail:snap})); }catch(_){ }
  }
  function scheduleTelemetry(event, sessionSnapshot=null){
    // Capture event truth at scheduling time. A single debounce timer previously
    // allowed a fast first-frame/stall transition to cancel the preceding selection
    // event and could label a newer session with an older event name. Milestone
    // telemetry must preserve ordering, so every significant event owns its timer.
    const captured=sessionSnapshot ? clone(sessionSnapshot) : snapshot();
    const timer=setTimeout(()=>{
      telemetryTimers.delete(timer);
      try{
        const body={event,session:captured};
        fetch('/api/playback/telemetry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),keepalive:true,cache:'no-store'}).catch(()=>{});
      }catch(_){ }
    }, event==='stall'?180:20);
    telemetryTimers.add(timer);
  }
  function closeStall(perf=nowPerf()){
    if(!state.stallStartedPerf) return;
    const elapsed=Math.max(0,Math.round(perf-state.stallStartedPerf));
    state.lastStallMs=elapsed;
    state.stallTotalMs+=elapsed;
    state.stallStartedPerf=0;
  }
  function auditInvariant(){
    const audibleVideos=[state.audible.videoA&&'A',state.audible.videoB&&'B'].filter(Boolean);
    state.invariant=audibleVideos.length>1 ? `ERROR: VIDEO AUDIO ${audibleVideos.join('+')}` : 'OK';
    if(audibleVideos.length>1) console.error('[SBB playback-session] invariant violation: multiple audible video slots',snapshot());
  }

  function currentTransactionId(meta={}){
    if(meta.transactionId) return String(meta.transactionId);
    try{return String(window.SBB_APP_STORE?.snapshot?.().playback?.transactionId||'');}catch(_){return '';}
  }
  function beginIntent(meta={}){
    state=freshState();
    state.sessionId=`intent-${nowEpoch().toString(36)}-${(++sequence).toString(36)}`;
    state.selectionId=sequence;
    state.transactionId=currentTransactionId(meta);
    state.intentId=Number(meta.intentId)||Number(window.SBB_APP_STORE?.snapshot?.().playback?.intentId)||0;
    state.selectedAt=nowEpoch(); state.selectedPerf=nowPerf();
    Object.assign(state,{
      eventKey:String(meta.eventKey||''),title:String(meta.title||''),league:String(meta.league||''),
      reason:String(meta.reason||'playback intent'),userInitiated:!!meta.userInitiated,
      transport:'PENDING',previousState:'idle',state:'preparing',lastTransitionAt:nowEpoch(),lastError:''
    });
    emit();scheduleTelemetry('intent');return snapshot();
  }

  function select(meta={}){
    // PlaybackController selects a concrete media attempt beneath the v5 transaction.
    // replay of the same media is a new playback attempt and needs fresh first-frame,
    // stall and failure accounting. Reusing the previous session here made replay
    // latency invisible and carried stale first-frame truth across restarts.
    const mediaKey=String(meta.mediaKey||meta.clipKey||'');
    state=freshState();
    state.sessionId=`ps-${nowEpoch().toString(36)}-${(++sequence).toString(36)}`;
    state.selectionId=sequence;
    state.transactionId=currentTransactionId(meta);
    state.intentId=Number(meta.intentId)||Number(window.SBB_APP_STORE?.snapshot?.().playback?.intentId)||0;
    state.selectedAt=nowEpoch(); state.selectedPerf=nowPerf();
    Object.assign(state,{
      eventKey:String(meta.eventKey||state.eventKey||''),
      mediaKey, clipKey:String(meta.clipKey||mediaKey||state.clipKey||''),
      title:String(meta.title||state.title||''), league:String(meta.league||state.league||''), provider:String(meta.provider||state.provider||''),
      transport:String(meta.transport||state.transport||''), slot:String(meta.slot||state.slot||''),
      sourceUrl:String(meta.sourceUrl||state.sourceUrl||''), sourceExternalUrl:String(meta.sourceExternalUrl||state.sourceExternalUrl||''),
      reason:String(meta.reason||state.reason||''), userInitiated:!!meta.userInitiated,
      previousState:state.state, state:'selected', lastTransitionAt:nowEpoch(), lastError:''
    });
    emit(); scheduleTelemetry('selection'); return snapshot();
  }
  function assign(meta={}){
    Object.assign(state,{
      provider:String(meta.provider||state.provider||''), transport:String(meta.transport||state.transport||''), slot:String(meta.slot||state.slot||''),
      sourceUrl:String(meta.sourceUrl||state.sourceUrl||''), sourceExternalUrl:String(meta.sourceExternalUrl||state.sourceExternalUrl||'')
    });
    emit(); return snapshot();
  }
  function transition(next,meta={}){
    next=String(next||'idle').toLowerCase();
    const perf=nowPerf();
    const prior=state.state;
    let stallStarted=false,stallEnded=false;
    if(next==='buffering' && state.firstFrameAt && prior!=='buffering'){
      state.stallCount+=1; state.stallStartedPerf=perf; stallStarted=true;
    }
    if(prior==='buffering' && next!=='buffering'){ closeStall(perf); stallEnded=true; }
    state.previousState=prior; state.state=next; state.lastTransitionAt=nowEpoch();
    if(meta.slot!=null) state.slot=String(meta.slot||'');
    if(meta.provider!=null) state.provider=String(meta.provider||'');
    if(meta.transport!=null) state.transport=String(meta.transport||'');
    if(meta.sourceUrl!=null) state.sourceUrl=String(meta.sourceUrl||'');
    if(meta.sourceExternalUrl!=null) state.sourceExternalUrl=String(meta.sourceExternalUrl||'');
    if(next==='playing' && !state.firstFrameAt) markFirstFrame(meta,true);
    auditInvariant(); emit();
    // Send stall snapshots only after the state mutation is complete so the server
    // receives the same truth the browser console rendered.
    if(stallStarted) scheduleTelemetry('stall');
    if(stallEnded) scheduleTelemetry('stall-end');
    return snapshot();
  }
  function markFirstFrame(meta={},send=true){
    const first=!state.firstFrameAt;
    if(first){
      const perf=nowPerf();
      state.firstFrameAt=nowEpoch();
      state.firstFrameMs=Math.max(0,Math.round(perf-(state.selectedPerf||perf)));
    }
    if(meta.slot!=null) state.slot=String(meta.slot||'');
    if(meta.provider!=null) state.provider=String(meta.provider||'');
    if(meta.transport!=null) state.transport=String(meta.transport||'');
    if(meta.sourceUrl!=null) state.sourceUrl=String(meta.sourceUrl||'');
    if(meta.sourceExternalUrl!=null) state.sourceExternalUrl=String(meta.sourceExternalUrl||'');
    emit();
    if(send) scheduleTelemetry(first?'first-frame':'first-frame-meta');
    return snapshot();
  }
  function fail(error,meta={}){
    closeStall(); state.failureCount+=1; state.lastError=String(error?.message||error||'Playback failure');
    transition('failed',meta); scheduleTelemetry('failure'); return snapshot();
  }
  function setAudible(kind,id,audible){
    if(kind==='video'){
      if(String(id).toUpperCase()==='A') state.audible.videoA=!!audible;
      if(String(id).toUpperCase()==='B') state.audible.videoB=!!audible;
    }else if(kind==='soundtrack') state.audible.soundtrack=!!audible;
    auditInvariant(); emit(); return state.invariant;
  }
  function clearVideoAudible(){ state.audible.videoA=false; state.audible.videoB=false; auditInvariant(); emit(); }
  function note(message,meta={}){ try{scheduleTelemetry(String(message||'note').slice(0,80));}catch(_){} return snapshot(); }
  function snapshot(){ return clone(state); }
  function subscribe(fn){ if(typeof fn!=='function') return ()=>{}; listeners.add(fn); try{fn(snapshot());}catch(_){ } return ()=>listeners.delete(fn); }
  function reset(reason='reset'){ for(const timer of telemetryTimers)clearTimeout(timer);telemetryTimers.clear();state=freshState(); state.reason=String(reason||'reset'); emit(); }

  window.SBB_PLAYBACK_SESSION=Object.freeze({
    version:'2.0', beginIntent, select, assign, transition, markFirstFrame, fail, setAudible,
    clearVideoAudible, note, snapshot, subscribe, reset
  });
})();

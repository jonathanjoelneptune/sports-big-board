/* Sports Big Board v5.0.1 — Unified Runtime App Store.
   The v5 control plane remains the canonical browser state authority, but state
   commits are now branch-local and idempotent. Large provider/score payloads are
   projected into a compact event record before entering the hot playback state.
   This prevents repeated player telemetry from deep-cloning provider payloads on
   the browser main thread while a video is already playing. */
(() => {
  'use strict';
  if (window.SBB_APP_STORE?.version === '5.0.1') return;

  const VERSION='5.0.1';
  const SCHEMA='1.1';
  const listeners=new Set();
  let revision=0;
  let intentSequence=0;
  const stats={dispatches:0,commits:0,noops:0,snapshots:0,maxDispatchMs:0,maxEmitMs:0,lastDispatchMs:0,lastAction:'BOOT'};

  const clean=value=>String(value??'').trim();
  const now=()=>Date.now();
  const perfNow=()=>typeof performance!=='undefined'&&performance.now?performance.now():Date.now();
  const clone=value=>{
    if(value==null)return value;
    try{return structuredClone(value);}catch(_){return JSON.parse(JSON.stringify(value));}
  };
  const teamProjection=(team,side='')=>{
    if(!team)return null;
    if(typeof team==='string')return {id:'',name:team,displayName:team,shortName:'',abbreviation:'',side};
    return {
      id:clean(team.id??team.teamId??team.clubId),
      name:clean(team.name??team.teamName??team.displayName),
      displayName:clean(team.displayName??team.name??team.teamName),
      shortName:clean(team.shortName),abbreviation:clean(team.abbreviation??team.abbr),
      logo:clean(team.logo??team.logoUrl??team.image??team.imageUrl),side:clean(team.side||side)
    };
  };
  const eventKeyOf=eventLike=>{
    if(!eventLike)return '';
    try{return clean(window.SBB_EVENT_IDENTITY?.key?.(eventLike));}catch(_){ }
    const competition=clean(eventLike.competitionId||eventLike.__sbbLeague||eventLike.league).toUpperCase();
    const id=clean(eventLike.canonicalEventId||eventLike.espnEventId||eventLike.scoreEventId||eventLike.eventId||eventLike.matchId||eventLike.gamePk||eventLike.id);
    return competition&&id?`${competition}:${id}`:id;
  };
  function compactEvent(eventLike){
    if(!eventLike)return null;
    const raw=eventLike||{};
    const parts=Array.isArray(raw.participants)?raw.participants:[];
    const away=teamProjection(raw.awayTeam||raw.away||parts.find(x=>String(x?.side||'').toLowerCase()==='away')||parts[0],'away');
    const home=teamProjection(raw.homeTeam||raw.home||parts.find(x=>String(x?.side||'').toLowerCase()==='home')||parts[1],'home');
    const competitionId=clean(raw.competitionId||raw.__sbbLeague||raw.league?.id||raw.league).toUpperCase();
    const eventId=clean(raw.eventId||raw.scoreEventId||raw.espnEventId||raw.matchId||raw.gamePk||raw.id);
    return {
      entityType:'EVENT',sportId:clean(raw.sportId||raw.sport),competitionId,
      competitionName:clean(raw.competitionName||raw.league?.name),eventId,
      canonicalEventKey:eventKeyOf(raw),canonicalEventId:clean(raw.canonicalEventId),
      scoreEventId:clean(raw.scoreEventId),espnEventId:clean(raw.espnEventId),gameCenterEventId:clean(raw.gameCenterEventId),
      matchId:clean(raw.matchId),gamePk:clean(raw.gamePk),id:clean(raw.id),
      scheduledAt:clean(raw.scheduledAt||raw.date||raw.gameDate),date:clean(raw.date||raw.gameDate||raw.__sbbDate),
      status:clean(raw.status?.type?.name||raw.status?.abstractGameState||raw.status?.description||raw.status||raw.state?.status),
      venue:clean(raw.venue?.name||raw.venue),awayTeam:away,homeTeam:home,participants:[away,home].filter(Boolean),
      awayScore:raw.awayScore??raw.score?.awayScore??raw.away?.score??null,
      homeScore:raw.homeScore??raw.score?.homeScore??raw.home?.score??null,
      gameCenterProviderHint:clean(raw.gameCenterProviderHint),rankingSnapshotId:clean(raw.rankingSnapshotId)
    };
  }
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
    const playback=next.playback||{},selection=next.selection||{};
    if(playback.transactionId&&playback.eventKey){
      if(!selection.eventKey) invariant='ERROR: PLAYBACK EVENT WITHOUT SELECTED EVENT';
      else if(selection.eventKey!==playback.eventKey) invariant=`ERROR: EVENT OWNERSHIP ${selection.eventKey} != ${playback.eventKey}`;
    }
    if(next.gameCenter?.eventKey&&selection.eventKey&&next.gameCenter.eventKey!==selection.eventKey){
      invariant=`ERROR: GAME CENTER ${next.gameCenter.eventKey} != SELECTED ${selection.eventKey}`;
    }
    if(next.invariant===invariant)return next;
    return {...next,invariant};
  }
  function snapshot(){stats.snapshots++;return clone(state);}
  function playbackSnapshot(){return clone(state.playback);}
  function selectionSnapshot(){return clone(state.selection);}
  function healthSnapshot(){return {...stats,revision:state.revision,listenerCount:listeners.size,schema:SCHEMA};}
  function emit(action){
    const started=perfNow(),snap=snapshot();
    try{window.dispatchEvent(new CustomEvent('sbb:app-state',{detail:{state:snap,action}}));}catch(_){ }
    for(const fn of [...listeners]){try{fn(snap,action);}catch(err){console.warn('[SBB v5 app-store] listener failed',err);}}
    stats.maxEmitMs=Math.max(stats.maxEmitMs,perfNow()-started);
  }
  const txOk=(current,payload)=>!payload.transactionId||payload.transactionId===current.playback.transactionId;
  const same=(a,b)=>clean(a)===clean(b);
  function reduce(current,action){
    const type=clean(action?.type).toUpperCase(),payload=action?.payload||{};
    if(!type)return current;
    switch(type){
      case 'BROWSE_SET': { const date=payload.date!=null?clean(payload.date).slice(0,10):current.browse.date,leagueFilter=payload.leagueFilter!=null?(clean(payload.leagueFilter).toUpperCase()||'ALL'):current.browse.leagueFilter;if(date===current.browse.date&&leagueFilter===current.browse.leagueFilter)return current;return {...current,browse:{date,leagueFilter},lastAction:type}; }
      case 'SELECT_EVENT': {
        const event=compactEvent(payload.event),eventKey=clean(payload.eventKey)||eventKeyOf(event),source=clean(payload.source),reason=clean(payload.reason);
        if(eventKey===current.selection.eventKey&&source===current.selection.source&&reason===current.selection.reason)return current;
        return {...current,selection:{event,eventKey,source,reason,selectedAt:now()},gameCenter:{eventKey,state:eventKey?'SELECTED':'IDLE',updatedAt:now(),error:''},lastAction:type};
      }
      case 'CLEAR_EVENT':
        if(!current.selection.eventKey&&!current.gameCenter.eventKey)return current;
        return {...current,selection:{event:null,eventKey:'',source:clean(payload.source),reason:clean(payload.reason),selectedAt:now()},gameCenter:{eventKey:'',state:'IDLE',updatedAt:now(),error:''},lastAction:type};
      case 'PLAYBACK_INTENT_BEGIN': {
        const event=compactEvent(payload.event),eventKey=clean(payload.eventKey)||eventKeyOf(event),intentId=++intentSequence,t=now();
        const source=clean(payload.source)||'program',reason=clean(payload.reason);
        const selection={event,eventKey,source,reason,selectedAt:t};
        const playback={...freshPlayback(),transactionId:`pb-${t.toString(36)}-${intentId.toString(36)}`,intentId,state:'INTENT',source,reason,userInitiated:!!payload.userInitiated,eventKey,event,requestedAt:t,updatedAt:t};
        return {...current,selection,gameCenter:{eventKey,state:eventKey?'SELECTED':'IDLE',updatedAt:t,error:''},playback,lastAction:type};
      }
      case 'PLAYBACK_PLAN': {
        if(!txOk(current,payload))return current;const mediaPlan=Array.isArray(payload.mediaPlan)?clone(payload.mediaPlan):[];
        return {...current,playback:{...current.playback,mediaPlan,updatedAt:now()},lastAction:type};
      }
      case 'PLAYBACK_PREPARING': {
        if(!txOk(current,payload))return current;const mediaKey=clean(payload.mediaKey);
        if(current.playback.state==='PREPARING'&&current.playback.prewarm.mediaKey===mediaKey)return current;
        const t=now();return {...current,playback:{...current.playback,state:'PREPARING',updatedAt:t,prewarm:{state:'PREPARING',mediaKey,startedAt:t,completedAt:0,result:''}},lastAction:type};
      }
      case 'PLAYBACK_PREWARM_RESULT': {
        if(!txOk(current,payload))return current;const targetState=payload.ok?'READY':'FAILED',result=clean(payload.result);
        if(current.playback.prewarm.state===targetState&&current.playback.prewarm.result===result)return current;
        return {...current,playback:{...current.playback,prewarm:{...current.playback.prewarm,state:targetState,completedAt:now(),result},updatedAt:now()},lastAction:type};
      }
      case 'PLAYBACK_MEDIA_SELECTED': {
        if(!txOk(current,payload))return current;const mediaKey=clean(payload.mediaKey),provider=clean(payload.provider),transport=clean(payload.transport),candidateIndex=Number.isFinite(payload.candidateIndex)?payload.candidateIndex:current.playback.candidateIndex;
        if(current.playback.state==='SELECTED'&&current.playback.activeMediaKey===mediaKey&&current.playback.provider===provider&&current.playback.transport===transport&&current.playback.candidateIndex===candidateIndex)return current;
        return {...current,playback:{...current.playback,state:'SELECTED',activeMediaKey:mediaKey,provider,transport,candidateIndex,updatedAt:now()},lastAction:type};
      }
      case 'PLAYBACK_STARTING':
        if(!txOk(current,payload))return current;
        return {...current,playback:{...current.playback,state:'STARTING',attempts:current.playback.attempts+1,updatedAt:now()},lastAction:type};
      case 'PLAYBACK_PLAYING':
        if(!txOk(current,payload))return current;
        if(current.playback.state==='PLAYING'&&!current.playback.error)return current;
        return {...current,playback:{...current.playback,state:'PLAYING',updatedAt:now(),error:''},lastAction:type};
      case 'PLAYBACK_PROGRESS': { if(!txOk(current,payload))return current;const seconds=Math.max(current.playback.progressSeconds,Number(payload.seconds)||0);if(current.playback.state==='PLAYING'&&seconds<=current.playback.progressSeconds+.049)return current;return {...current,playback:{...current.playback,state:'PLAYING',progressSeconds:seconds,lastProgressAt:now(),updatedAt:now()},lastAction:type}; }
      case 'PLAYBACK_RECOVERING': { if(!txOk(current,payload))return current;const error=clean(payload.error);if(current.playback.state==='RECOVERING'&&current.playback.error===error)return current;return {...current,playback:{...current.playback,state:'RECOVERING',recoveries:current.playback.recoveries+1,error,updatedAt:now()},lastAction:type}; }
      case 'PLAYBACK_FAILED':
      case 'PLAYBACK_UNAVAILABLE': { if(!txOk(current,payload))return current;const target=type==='PLAYBACK_FAILED'?'FAILED':'UNAVAILABLE',error=clean(payload.error||payload.reason);if(current.playback.state===target&&current.playback.error===error)return current;return {...current,playback:{...current.playback,state:target,error,updatedAt:now()},lastAction:type}; }
      case 'PLAYBACK_ENDED': if(!txOk(current,payload)||current.playback.state==='ENDED')return current;return {...current,playback:{...current.playback,state:'ENDED',updatedAt:now()},lastAction:type};
      case 'PLAYBACK_LEGACY_SELECTION': { if(!txOk(current,payload))return current;const selectionId=Number(payload.selectionId)||0;if(selectionId===current.playback.legacySelectionId)return current;return {...current,playback:{...current.playback,legacySelectionId:selectionId,updatedAt:now()},lastAction:type}; }
      case 'PLAYBACK_RESET': if(current.playback.state==='IDLE'&&!current.playback.transactionId)return current;return {...current,playback:freshPlayback(),lastAction:type};
      case 'GAME_CENTER_STATE': { if(payload.eventKey&&current.selection.eventKey&&payload.eventKey!==current.selection.eventKey)return current;const eventKey=clean(payload.eventKey)||current.selection.eventKey,gcState=clean(payload.state)||'IDLE',error=clean(payload.error);if(current.gameCenter.eventKey===eventKey&&current.gameCenter.state===gcState&&current.gameCenter.error===error)return current;return {...current,gameCenter:{eventKey,state:gcState,updatedAt:now(),error},lastAction:type}; }
      default:return current;
    }
  }
  function dispatch(action){
    const started=perfNow();stats.dispatches++;stats.lastAction=clean(action?.type).toUpperCase()||'UNKNOWN';
    let next=reduce(state,action);
    if(next===state){stats.noops++;stats.lastDispatchMs=perfNow()-started;stats.maxDispatchMs=Math.max(stats.maxDispatchMs,stats.lastDispatchMs);return snapshot();}
    next={...audit(next),revision:++revision,version:VERSION,schema:SCHEMA};state=next;stats.commits++;emit(action);
    stats.lastDispatchMs=perfNow()-started;stats.maxDispatchMs=Math.max(stats.maxDispatchMs,stats.lastDispatchMs);return snapshot();
  }
  function subscribe(fn,{emitCurrent=false}={}){if(typeof fn!=='function')return()=>{};listeners.add(fn);if(emitCurrent)try{fn(snapshot(),{type:'SNAPSHOT'});}catch(_){}return()=>listeners.delete(fn);}
  function currentTransaction(){return state.playback.transactionId||'';}
  function transactionActive(id=''){const tx=clean(id)||currentTransaction();return !!tx&&tx===state.playback.transactionId&&!['IDLE','ENDED','FAILED','UNAVAILABLE'].includes(state.playback.state);}

  window.SBB_APP_STORE=Object.freeze({version:VERSION,schema:SCHEMA,dispatch,snapshot,playbackSnapshot,selectionSnapshot,healthSnapshot,subscribe,eventKeyOf,compactEvent,currentTransaction,transactionActive});
})();

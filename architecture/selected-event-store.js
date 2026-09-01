/* Sports Big Board v5.0.7 — SelectedEvent Event Reconstitution authority.
   SelectedEvent accepts only the compact sporting-event schema produced by the v5
   App Store. Raw score/provider/media rows never cross this boundary. */
(() => {
  'use strict';
  if(window.SBB_SELECTED_EVENT?.version==='5.0.7')return;
  let current=null;
  let revision=0;
  const listeners=new Set();
  const clean=v=>String(v??'').trim();
  function project(eventLike){
    if(!eventLike)return null;
    try{const projected=window.SBB_APP_STORE?.compactEvent?.(eventLike);if(projected)return projected;}catch(_){}
    // Strict fallback: never call SBB_CORE.event() here because that legacy helper
    // intentionally spreads arbitrary provider fields for compatibility.
    const parts=Array.isArray(eventLike?.participants)?eventLike.participants:[];
    const team=(value,side)=>{if(!value)return null;if(typeof value==='string')return {id:'',name:value,displayName:value,shortName:'',abbreviation:'',logo:'',side};return {id:clean(value.id??value.teamId??value.clubId),name:clean(value.name??value.teamName??value.displayName),displayName:clean(value.displayName??value.name??value.teamName),shortName:clean(value.shortName),abbreviation:clean(value.abbreviation??value.abbr),logo:clean(value.logo??value.logoUrl??value.image??value.imageUrl),side:clean(value.side||side)};};
    const away=team(eventLike.awayTeam||eventLike.away||parts[0],'away'),home=team(eventLike.homeTeam||eventLike.home||parts[1],'home');
    return {entityType:'EVENT',competitionId:clean(eventLike.competitionId||eventLike.__sbbLeague||eventLike.league).toUpperCase(),competitionName:clean(eventLike.competitionName),eventId:clean(eventLike.eventId||eventLike.scoreEventId||eventLike.espnEventId||eventLike.matchId||eventLike.gamePk||eventLike.id),canonicalEventKey:clean(eventLike.canonicalEventKey),canonicalEventId:clean(eventLike.canonicalEventId),scoreEventId:clean(eventLike.scoreEventId),espnEventId:clean(eventLike.espnEventId),gameCenterEventId:clean(eventLike.gameCenterEventId),matchId:clean(eventLike.matchId),gamePk:clean(eventLike.gamePk),id:clean(eventLike.id),scheduledAt:clean(eventLike.scheduledAt||eventLike.date||eventLike.gameDate),date:clean(eventLike.date||eventLike.gameDate||eventLike.__sbbDate),status:clean(eventLike.status?.description||eventLike.status),venue:clean(eventLike.venue?.name||eventLike.venue),awayTeam:away,homeTeam:home,participants:[away,home].filter(Boolean),awayScore:eventLike.awayScore??eventLike.away?.score??null,homeScore:eventLike.homeScore??eventLike.home?.score??null,gameCenterProviderHint:clean(eventLike.gameCenterProviderHint),rankingSnapshotId:clean(eventLike.rankingSnapshotId)};
  }
  function snapshot(){return current?{...current,participants:Array.isArray(current.participants)?current.participants.map(x=>({...x})):[]}:null;}
  function keyOf(eventLike){
    if(!eventLike)return '';
    try{return clean(window.SBB_EVENT_IDENTITY?.key?.(eventLike));}catch(_){}
    return clean(eventLike.canonicalEventKey||eventLike.canonicalEventId||eventLike.espnEventId||eventLike.scoreEventId||eventLike.eventId||eventLike.matchId||eventLike.id);
  }
  function activePlayback(){try{return window.SBB_APP_STORE?.snapshot?.().playback||null;}catch(_){return null;}}
  function legacyPlaybackMutation(meta={}){const source=clean(meta.source).toLowerCase();return source==='playback'||source==='playback-confirmed'||source==='program'||source==='native-playing'||source==='youtube-playing';}
  function protectedByV5(){const pb=activePlayback();return !!(current&&pb?.transactionId&&pb?.eventKey&&keyOf(current)===pb.eventKey);}
  function emit(meta){const snap=snapshot();for(const fn of [...listeners]){try{fn(snap,{revision,...meta});}catch(e){console.warn('[SBB SelectedEvent listener]',e);}}try{window.dispatchEvent(new CustomEvent('sbb:selected-event',{detail:{event:snap,revision,...meta}}));}catch(_){}}
  function select(eventLike,meta={}){
    if(!eventLike)return clear(meta);
    const canonical=project(eventLike);
    const identity=keyOf(canonical);
    if(identity)canonical.canonicalEventKey=identity;
    if(protectedByV5()&&legacyPlaybackMutation(meta)){const pb=activePlayback();if(identity&&pb?.eventKey&&identity!==pb.eventKey)return snapshot();if(current)return snapshot();}
    if(current&&identity&&keyOf(current)===identity&&legacyPlaybackMutation(meta))return snapshot();
    current={...canonical,selectedAt:Date.now(),selectionReason:clean(meta.reason),selectionSource:clean(meta.source),__sbbReconstituted:true};
    revision++;
    if(!meta.storeAlreadySelected){try{window.SBB_APP_STORE?.dispatch?.({type:'SELECT_EVENT',payload:{event:current,eventKey:identity,source:current.selectionSource,reason:current.selectionReason}});}catch(_){}}
    emit({action:'select',reconstituted:true,...meta});
    return snapshot();
  }
  function clear(meta={}){
    const source=clean(meta.source).toLowerCase();
    if(protectedByV5()&&source!=='v5-orchestrator'&&meta.force!==true)return snapshot();
    if(!current){if(!meta.storeAlreadySelected){try{window.SBB_APP_STORE?.dispatch?.({type:'CLEAR_EVENT',payload:{source:clean(meta.source),reason:clean(meta.reason)}});}catch(_){}}return null;}
    current=null;revision++;
    if(!meta.storeAlreadySelected){try{window.SBB_APP_STORE?.dispatch?.({type:'CLEAR_EVENT',payload:{source:clean(meta.source),reason:clean(meta.reason)}});}catch(_){}}
    emit({action:'clear',...meta});return null;
  }
  function subscribe(fn,{emitCurrent=false}={}){if(typeof fn!=='function')return()=>{};listeners.add(fn);if(emitCurrent)fn(snapshot(),{revision,action:'snapshot'});return()=>listeners.delete(fn);}
  window.SBB_SELECTED_EVENT=Object.freeze({version:'5.0.7',select,clear,get:snapshot,subscribe,keyOf,project,get revision(){return revision;}});
})();

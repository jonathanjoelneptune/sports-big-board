/* Sports Big Board v4.7.11 — Render-Scoped Score-Card Availability Index.
   Build one lightweight known-media index per actual ribbon render. Scheduled games,
   score-only cold history, and already-verified media avoid broad candidate scans.
   Unknown/live/unresolved games preserve the certified legacy resolver unchanged.
*/
(() => {
  'use strict';
  if(window.SBB_SCORECARD_AVAILABILITY_INDEX?.version==='4.7.11')return;

  const VERSION='4.7.11';
  const state={
    installed:false,active:false,renderId:0,indexBuildMs:0,
    indexed:0,scheduled:0,thin:0,verified:0,
    fastHits:0,fallbacks:0,fallbackMs:0,last:null,
    totalFastHits:0,totalFallbacks:0
  };
  let originalPlayable=null;
  let rows=new Map();
  const now=()=>performance.now();
  const round=v=>Math.round(Number(v||0)*10)/10;
  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();

  function currentDate(){
    try{return clean(window.SBB_SCORE_DATE?.snapshot?.().browseDate||window.scoreBrowseDate).slice(0,10);}
    catch(_){return clean(window.scoreBrowseDate).slice(0,10);}
  }

  function stableKey(match){
    if(!match)return '';
    try{
      if(typeof scoreGameLookupKeys==='function'){
        const keys=scoreGameLookupKeys(match);
        if(Array.isArray(keys)&&keys.length)return `LOOKUP:${keys.map(String).sort().join('|')}`;
      }
    }catch(_){}
    const league=upper(match.competitionId||match.__sbbLeague||match.league||match.sport||'SPORTS');
    const id=clean(match.scoreEventId||match.espnEventId||match.gameCenterEventId||match.matchId||match.gamePk||match.eventId||match.id);
    if(id)return `${league}:ID:${id}`;
    const away=clean(match.away?.name||match.awayTeam?.name||match.awayName||match.away);
    const home=clean(match.home?.name||match.homeTeam?.name||match.homeName||match.home);
    const date=clean(match.__sbbDate||match.gameDate||match.date||currentDate()).slice(0,10);
    return `${league}:PAIR:${date}:${upper(away)}:${upper(home)}`;
  }

  function explicitStatus(match){
    let raw=match?.status;
    if(raw&&typeof raw==='object'){
      raw=raw.type||raw.name||raw.state||raw.description||raw.detail||'';
    }
    const value=upper(raw);
    if(/FINAL|COMPLETED|FINISHED|FULL TIME|\bFT\b/.test(value))return 'FINAL';
    if(/LIVE|IN_PROGRESS|IN PROGRESS|HALFTIME|QTR|PERIOD/.test(value))return 'LIVE';
    if(/POSTPON/.test(value))return 'POSTPONED';
    if(/CANCEL/.test(value))return 'CANCELLED';
    if(/SCHEDULED|PRE|UPCOMING|NOT STARTED|NOT_STARTED/.test(value))return 'SCHEDULED';
    return '';
  }

  function thinScoreOnly(date){
    try{
      const payload=window.SBB_DAY_STATE?.cache?.(date);
      return !!(
        payload?.thinSnapshot ||
        payload?.projectionDiagnostics?.thinCatalog ||
        payload?.cache?.state==='COLD_THIN_CATALOG'
      );
    }catch(_){return false;}
  }

  function directVerified(match){
    try{
      if(typeof verifiedPlayableItemsForGame==='function'){
        const items=verifiedPlayableItemsForGame(match);
        return Array.isArray(items)?items:[];
      }
    }catch(_){}
    return [];
  }

  function buildIndex(){
    const started=now();
    rows=new Map();
    state.indexed=0;state.scheduled=0;state.thin=0;state.verified=0;
    const date=currentDate();
    const thin=thinScoreOnly(date);
    let matches=[];
    try{
      matches=typeof scoreMatchesForDate==='function'
        ? scoreMatchesForDate(date)
        : (window.SBB_SCORE_DATE?.allMatches?.(date)||[]);
    }catch(_){}
    if(!Array.isArray(matches))matches=[];

    for(const match of matches){
      const key=stableKey(match);
      if(!key)continue;
      state.indexed+=1;
      if(explicitStatus(match)==='SCHEDULED'){
        rows.set(key,{kind:'scheduled',items:[]});
        state.scheduled+=1;
        continue;
      }
      if(thin){
        rows.set(key,{kind:'thin-score-only',items:[]});
        state.thin+=1;
        continue;
      }
      const verified=directVerified(match);
      if(verified.length){
        rows.set(key,{kind:'verified',items:verified});
        state.verified+=1;
      }
    }
    state.indexBuildMs=round(now()-started);
  }

  function install(){
    if(state.installed)return true;
    if(typeof window.scoreCardPlayableItems!=='function')return false;
    originalPlayable=window.scoreCardPlayableItems;
    if(originalPlayable.__sbbAvailabilityIndex)return true;

    function indexedPlayable(match){
      if(!state.active)return originalPlayable(match);
      const hit=rows.get(stableKey(match));
      if(hit){
        state.fastHits+=1;
        state.totalFastHits+=1;
        return Array.isArray(hit.items)?hit.items.slice():[];
      }
      state.fallbacks+=1;
      state.totalFallbacks+=1;
      const started=now();
      try{return originalPlayable(match);}
      finally{state.fallbackMs+=now()-started;}
    }
    indexedPlayable.__sbbAvailabilityIndex=true;
    indexedPlayable.__sbbOriginal=originalPlayable;
    window.scoreCardPlayableItems=indexedPlayable;
    state.installed=true;
    return true;
  }

  function beginRender(){
    install();
    state.renderId+=1;
    state.active=true;
    state.fastHits=0;state.fallbacks=0;state.fallbackMs=0;
    buildIndex();
    return state.renderId;
  }

  function endRender(token){
    if(!state.active)return state.last;
    if(token&&Number(token)!==state.renderId)return state.last;
    const report={
      renderId:state.renderId,indexed:state.indexed,
      scheduled:state.scheduled,thin:state.thin,verified:state.verified,
      fastHits:state.fastHits,fallbacks:state.fallbacks,
      indexBuildMs:state.indexBuildMs,fallbackMs:round(state.fallbackMs)
    };
    state.last=report;
    state.active=false;
    rows=new Map();
    try{window.dispatchEvent(new CustomEvent('sbb:availability-index',{detail:{...report,at:Date.now()}}));}catch(_){}
    return report;
  }

  function boot(){
    install();
    const timer=setInterval(()=>{if(install())clearInterval(timer);},100);
    setTimeout(()=>clearInterval(timer),5000);
  }

  window.SBB_SCORECARD_AVAILABILITY_INDEX=Object.freeze({
    version:VERSION,install,beginRender,endRender,
    snapshot:()=>({
      version:VERSION,installed:state.installed,active:state.active,
      renderId:state.renderId,totalFastHits:state.totalFastHits,
      totalFallbacks:state.totalFallbacks,last:state.last?{...state.last}:null
    })
  });

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();

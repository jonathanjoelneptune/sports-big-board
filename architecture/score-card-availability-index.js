/* Sports Big Board v4.7.16 — Generation-Scoped Day-State Score-Card Render Model.
   Build one availability model from canonical Day State eventPlans and reuse that
   model across filter-only renders for the same date/generation. SCHEDULED and thin
   score-only rows are known no-media states. eventPlans.playable, session-verified
   media, and positive legacy resolver results are all authoritative known playable
   media for certification. Non-filter media/date renders rebuild the snapshot so
   media freshness semantics remain unchanged.
*/
(() => {
  'use strict';
  if(window.SBB_SCORECARD_AVAILABILITY_INDEX?.version==='4.7.16')return;

  const VERSION='4.7.16';
  const state={
    installed:false,active:false,renderId:0,indexBuildMs:0,
    indexed:0,scheduled:0,thin:0,planPlayable:0,sessionVerified:0,
    planCount:0,knownMediaGames:0,knownMediaAssets:0,
    fastHits:0,fallbacks:0,fallbackMs:0,last:null,
    totalFastHits:0,totalFallbacks:0,snapshotReused:false,
    snapshotDate:'',snapshotGeneration:0,snapshotReason:'',
    snapshotReuses:0,totalSnapshotReuses:0
  };
  let originalPlayable=null;
  let rows=new Map();
  let planAliases=new Map();
  let readyKnownMediaKeys=new Set();
  let knownMediaKeys=new Set();
  const dateReports=new Map();
  const now=()=>performance.now();
  const round=v=>Math.round(Number(v||0)*10)/10;
  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();

  function currentDate(){
    try{return clean(window.SBB_SCORE_DATE?.snapshot?.().browseDate||window.scoreBrowseDate||scoreBrowseDate).slice(0,10);}
    catch(_){return clean(window.scoreBrowseDate).slice(0,10);}
  }
  // v4.7.13 compatibility marker: visibleMatch previously gated index construction by active filter.
  // v4.7.16 deliberately indexes all date rows; filter visibility is owned by Render Pipeline.
  function currentFilter(){
    const active=document.querySelector('#scoreFilters [data-score-filter].active');
    if(active)return upper(active?.dataset?.scoreFilter||'ALL')||'ALL';
    try{return upper(scoreRibbonLeagueFilter||window.scoreRibbonLeagueFilter||'ALL')||'ALL';}
    catch(_){return upper(window.scoreRibbonLeagueFilter||'ALL')||'ALL';}
  }
  function leagueFor(value){
    return upper(value?.competitionId||value?.__sbbLeague||value?.league||value?.sport||'SPORTS');
  }
  function eventIds(value){
    return [
      value?.scoreEventId,value?.espnEventId,value?.gameCenterEventId,
      value?.matchId,value?.gamePk,value?.eventId,value?.id
    ].filter(x=>x!==undefined&&x!==null&&clean(x)!=='').map(x=>clean(x));
  }
  function pairKey(value,date=currentDate()){
    const lg=leagueFor(value);
    const away=clean(value?.away?.name||value?.awayTeam?.name||value?.awayName||value?.away);
    const home=clean(value?.home?.name||value?.homeTeam?.name||value?.homeName||value?.home);
    const d=clean(value?.__sbbDate||value?.gameDate||value?.date||date).slice(0,10);
    if(!away&&!home)return '';
    return `PAIR:${lg}:${d}:${upper(away)}:${upper(home)}`;
  }
  function aliasesFor(value,date=currentDate()){
    const aliases=[];
    const lg=leagueFor(value);
    for(const id of eventIds(value))aliases.push(`ID:${lg}:${id}`);
    try{
      if(typeof scoreGameLookupKeys==='function'){
        const keys=scoreGameLookupKeys(value);
        if(Array.isArray(keys)){
          for(const key of keys){
            const k=clean(key);
            if(k)aliases.push(`LOOKUP:${upper(k)}`);
          }
        }
      }
    }catch(_){}
    const pair=pairKey(value,date);if(pair)aliases.push(pair);
    return [...new Set(aliases)];
  }
  function stableKey(value,date=currentDate()){
    return aliasesFor(value,date)[0]||'';
  }

  function explicitStatus(match){
    let raw=match?.status;
    if(raw&&typeof raw==='object')raw=raw.type||raw.name||raw.state||raw.description||raw.detail||'';
    const value=upper(raw);
    if(/FINAL|COMPLETED|FINISHED|FULL TIME|\bFT\b/.test(value))return 'FINAL';
    if(/LIVE|IN_PROGRESS|IN PROGRESS|HALFTIME|QTR|PERIOD/.test(value))return 'LIVE';
    if(/POSTPON/.test(value))return 'POSTPONED';
    if(/CANCEL/.test(value))return 'CANCELLED';
    if(/SCHEDULED|PRE|UPCOMING|NOT STARTED|NOT_STARTED/.test(value))return 'SCHEDULED';
    return '';
  }

  function dayStatePayload(date){
    try{return window.SBB_DAY_STATE?.cache?.(date)||null;}catch(_){return null;}
  }
  function thinScoreOnly(payload){
    return !!(
      payload?.thinSnapshot ||
      payload?.projectionDiagnostics?.thinCatalog ||
      payload?.cache?.state==='COLD_THIN_CATALOG'
    );
  }

  function decoratePlayable(items,{date,league,plan,key}){
    return (Array.isArray(items)?items:[]).map(item=>({
      ...item,
      __sbbDate:item?.__sbbDate||date,
      __sbbLeague:item?.__sbbLeague||league,
      competitionId:item?.competitionId||league,
      league:item?.league||league,
      canonicalEventKey:item?.canonicalEventKey||plan?.canonicalEventKey||key||'',
      __sbbCatalogExact:true
    }));
  }

  function addPlanAliases(key,plan,date){
    if(!plan||typeof plan!=='object')return;
    const lg=upper(plan.league||clean(key).split(':')[0]||leagueFor(plan.event));
    const ev=plan.event||{};
    const all=new Set();
    if(clean(key))all.add(`CANON:${clean(key)}`);
    if(clean(plan.canonicalEventKey))all.add(`CANON:${clean(plan.canonicalEventKey)}`);
    for(const id of [plan.eventId,...eventIds(ev)].filter(x=>x!==undefined&&x!==null&&clean(x)!==''))all.add(`ID:${lg}:${clean(id)}`);
    for(const alias of aliasesFor({...ev,competitionId:lg,__sbbLeague:lg},date))all.add(alias);
    for(const alias of all)planAliases.set(alias,{key,plan,league:lg});
  }

  function buildPlanAliases(payload,date){
    planAliases=new Map();
    const plans=payload?.eventPlans;
    if(!plans||typeof plans!=='object')return 0;
    let count=0;
    for(const [key,plan] of Object.entries(plans)){
      addPlanAliases(key,plan,date);count+=1;
    }
    return count;
  }

  function planForMatch(match,date){
    // App's canonical map is the most direct lookup after ingestCompactCatalogPlans.
    try{
      if(typeof catalogPlanForScoreGame==='function'){
        const plan=catalogPlanForScoreGame(match);
        if(plan)return {key:clean(plan.canonicalEventKey),plan,league:leagueFor(match)};
      }
    }catch(_){}
    for(const alias of aliasesFor(match,date)){
      const found=planAliases.get(alias);
      if(found)return found;
    }
    return null;
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

  function markKnown(gameKey,items,{ready=true}={}){
    if(!gameKey||!Array.isArray(items)||!items.length)return;
    if(!knownMediaKeys.has(gameKey)){
      knownMediaKeys.add(gameKey);
      state.knownMediaGames+=1;
      state.knownMediaAssets+=items.length;
    }
    if(ready)readyKnownMediaKeys.add(gameKey);
  }

  function buildIndex(meta={}){
    const started=now();
    rows=new Map();
    readyKnownMediaKeys=new Set();
    knownMediaKeys=new Set();
    state.indexed=0;state.scheduled=0;state.thin=0;
    state.planPlayable=0;state.sessionVerified=0;state.planCount=0;
    state.knownMediaGames=0;state.knownMediaAssets=0;
    state.snapshotReused=false;
    const date=currentDate();
    const payload=dayStatePayload(date);
    const thin=thinScoreOnly(payload);
    state.planCount=buildPlanAliases(payload,date);

    let matches=[];
    try{
      matches=typeof scoreMatchesForDate==='function'
        ? scoreMatchesForDate(date)
        : (window.SBB_SCORE_DATE?.allMatches?.(date)||[]);
    }catch(_){}
    if(!Array.isArray(matches))matches=[];

    // v4.7.16: index the full date, not only the current league filter. The render
    // pipeline keeps one all-league DOM bank, so a filter switch must never trigger
    // expensive media resolution merely because a previously hidden card is shown.
    for(const match of matches){
      const key=stableKey(match,date);
      if(!key)continue;
      state.indexed+=1;

      if(explicitStatus(match)==='SCHEDULED'){
        putForMatch(match,{kind:'scheduled',items:[],gameKey:key});
        state.scheduled+=1;
        continue;
      }
      if(thin){
        putForMatch(match,{kind:'thin-score-only',items:[],gameKey:key});
        state.thin+=1;
        continue;
      }

      const found=planForMatch(match,date);
      const planItems=found?.plan?.playable;
      if(Array.isArray(planItems)&&planItems.length){
        const lg=upper(found.league||leagueFor(match));
        const row={
          kind:'day-state-plan',gameKey:key,knownPlayableMedia:true,knownDatabaseMedia:true,
          items:decoratePlayable(planItems,{date,league:lg,plan:found.plan,key:found.key})
        };
        putForMatch(match,row);
        state.planPlayable+=1;
        markKnown(key,row.items,{ready:true});
        continue;
      }

      const verified=directVerified(match);
      if(verified.length){
        const row={kind:'session-verified',items:verified,gameKey:key,knownPlayableMedia:true};
        putForMatch(match,row);
        state.sessionVerified+=1;
        markKnown(key,verified,{ready:true});
      }
    }
    state.indexBuildMs=round(now()-started);
    state.snapshotDate=date;
    state.snapshotGeneration=Number(meta.generation||0);
    state.snapshotReason=clean(meta.reason||'');
  }

  function lookup(match){
    for(const alias of aliasesFor(match,currentDate())){
      const hit=rows.get(alias);
      if(hit)return hit;
    }
    return null;
  }

  function putForMatch(match,row){
    for(const alias of aliasesFor(match,currentDate()))rows.set(alias,row);
  }

  function install(){
    if(state.installed)return true;
    if(typeof window.scoreCardPlayableItems!=='function')return false;
    originalPlayable=window.scoreCardPlayableItems;
    if(originalPlayable.__sbbAvailabilityIndex)return true;

    function indexedPlayable(match){
      if(!state.active)return originalPlayable(match);
      const hit=lookup(match);
      if(hit){
        state.fastHits+=1;state.totalFastHits+=1;
        if(hit.knownPlayableMedia&&hit.gameKey&&Array.isArray(hit.items)&&hit.items.length)markKnown(hit.gameKey,hit.items,{ready:true});
        return Array.isArray(hit.items)?hit.items.slice():[];
      }
      state.fallbacks+=1;state.totalFallbacks+=1;
      const started=now();
      try{
        const result=originalPlayable(match);
        // Memoize both positive and empty legacy answers for this snapshot. Filter
        // renders may reuse the snapshot; any date/media/day-state render rebuilds it.
        if(Array.isArray(result)){
          const gameKey=stableKey(match,currentDate());
          const found=planForMatch(match,currentDate());
          const canonicalKnown=Array.isArray(found?.plan?.playable)&&found.plan.playable.length>0;
          const knownPlayable=result.length>0||canonicalKnown;
          putForMatch(match,{
            kind:result.length?'legacy-resolved':'legacy-empty',items:result,gameKey,
            knownPlayableMedia:knownPlayable
          });
          if(result.length)markKnown(gameKey,result,{ready:true});
        }
        return result;
      }finally{
        state.fallbackMs+=now()-started;
      }
    }
    indexedPlayable.__sbbAvailabilityIndex=true;
    indexedPlayable.__sbbOriginal=originalPlayable;
    window.scoreCardPlayableItems=indexedPlayable;
    state.installed=true;
    return true;
  }

  function canReuseSnapshot(meta={}){
    const reason=clean(meta.reason||'');
    const date=currentDate();
    return reason.includes('filter-change')&&state.snapshotDate===date&&state.renderId>0;
  }

  function beginRender(meta={}){
    install();
    state.renderId+=1;
    state.active=true;
    state.fastHits=0;state.fallbacks=0;state.fallbackMs=0;
    state.snapshotReused=canReuseSnapshot(meta);
    if(state.snapshotReused){
      state.snapshotReuses+=1;state.totalSnapshotReuses+=1;
      state.indexBuildMs=0;
    }else{
      buildIndex(meta);
    }
    return state.renderId;
  }

  function endRender(token){
    if(!state.active)return state.last;
    if(token&&Number(token)!==state.renderId)return state.last;
    const report={
      renderId:state.renderId,date:currentDate(),filter:currentFilter(),
      indexed:state.indexed,planCount:state.planCount,
      scheduled:state.scheduled,thin:state.thin,
      planPlayable:state.planPlayable,sessionVerified:state.sessionVerified,
      knownMediaGames:state.knownMediaGames,knownMediaAssets:state.knownMediaAssets,
      mediaReadyGames:readyKnownMediaKeys.size,
      mediaReadyComplete:state.knownMediaGames===0||readyKnownMediaKeys.size>=state.knownMediaGames,
      fastHits:state.fastHits,fallbacks:state.fallbacks,
      indexBuildMs:state.indexBuildMs,fallbackMs:round(state.fallbackMs),
      snapshotReused:!!state.snapshotReused,
      snapshotGeneration:state.snapshotGeneration,
      snapshotReason:state.snapshotReason
    };
    state.last=report;
    dateReports.set(report.date,{...report});
    while(dateReports.size>32)dateReports.delete(dateReports.keys().next().value);
    state.active=false;
    try{
      window.dispatchEvent(new CustomEvent('sbb:availability-index',{
        detail:{...report,at:Date.now()}
      }));
    }catch(_){}
    return report;
  }

  function invalidate(date=''){
    const d=clean(date).slice(0,10);
    if(!d||d===state.snapshotDate){
      rows=new Map();planAliases=new Map();readyKnownMediaKeys=new Set();knownMediaKeys=new Set();
      state.snapshotDate='';state.snapshotGeneration=0;state.snapshotReason='';
    }
    if(d)dateReports.delete(d);else dateReports.clear();
  }

  function boot(){
    install();
    const timer=setInterval(()=>{if(install())clearInterval(timer);},100);
    setTimeout(()=>clearInterval(timer),5000);
  }

  window.SBB_SCORECARD_AVAILABILITY_INDEX=Object.freeze({
    version:VERSION,install,beginRender,endRender,invalidate,
    forDate:date=>dateReports.get(clean(date).slice(0,10))||null,
    snapshot:()=>({
      version:VERSION,installed:state.installed,active:state.active,
      renderId:state.renderId,totalFastHits:state.totalFastHits,totalFallbacks:state.totalFallbacks,
      totalSnapshotReuses:state.totalSnapshotReuses,snapshotDate:state.snapshotDate,
      last:state.last?{...state.last}:null
    })
  });

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();

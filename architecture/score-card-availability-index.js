/* Sports Big Board v4.7.13 — Day-State Score-Card Render Model.
   Build one render-scoped availability model from canonical Day State eventPlans.
   SCHEDULED and thin score-only rows are known no-media first-paint states.
   eventPlans.playable is canonical verified playable media for completed games.
   Session verified media is a secondary fast path. Unknown/live/unresolved games
   preserve the certified legacy scoreCardPlayableItems resolver unchanged.
*/
(() => {
  'use strict';
  if(window.SBB_SCORECARD_AVAILABILITY_INDEX?.version==='4.7.13')return;

  const VERSION='4.7.13';
  const state={
    installed:false,active:false,renderId:0,indexBuildMs:0,
    indexed:0,scheduled:0,thin:0,planPlayable:0,sessionVerified:0,
    planCount:0,knownMediaGames:0,knownMediaAssets:0,
    fastHits:0,fallbacks:0,fallbackMs:0,last:null,
    totalFastHits:0,totalFallbacks:0
  };
  let originalPlayable=null;
  let rows=new Map();
  let planAliases=new Map();
  let readyKnownMediaKeys=new Set();
  const now=()=>performance.now();
  const round=v=>Math.round(Number(v||0)*10)/10;
  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();

  function currentDate(){
    try{return clean(window.SBB_SCORE_DATE?.snapshot?.().browseDate||window.scoreBrowseDate).slice(0,10);}
    catch(_){return clean(window.scoreBrowseDate).slice(0,10);}
  }
  function currentFilter(){
    return upper(window.scoreRibbonLeagueFilter||'ALL')||'ALL';
  }
  function visibleMatch(match){
    const filter=currentFilter();
    return filter==='ALL'||leagueFor(match)===filter;
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
    for(const id of [plan.eventId,...eventIds(ev)].filter(x=>x!==undefined&&x!==null&&clean(x)!=='')){
      all.add(`ID:${lg}:${clean(id)}`);
    }
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

  function buildIndex(){
    const started=now();
    rows=new Map();
    readyKnownMediaKeys=new Set();
    state.indexed=0;state.scheduled=0;state.thin=0;
    state.planPlayable=0;state.sessionVerified=0;state.planCount=0;
    state.knownMediaGames=0;state.knownMediaAssets=0;
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

    for(const match of matches){
      if(!visibleMatch(match))continue;
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
          kind:'day-state-plan',
          gameKey:key,
          knownDatabaseMedia:true,
          items:decoratePlayable(planItems,{date,league:lg,plan:found.plan,key:found.key})
        };
        putForMatch(match,row);
        state.planPlayable+=1;
        state.knownMediaGames+=1;
        state.knownMediaAssets+=row.items.length;
        continue;
      }

      const verified=directVerified(match);
      if(verified.length){
        putForMatch(match,{kind:'session-verified',items:verified,gameKey:key});
        state.sessionVerified+=1;
      }
    }
    state.indexBuildMs=round(now()-started);
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
        state.fastHits+=1;
        state.totalFastHits+=1;
        if(hit.knownDatabaseMedia&&hit.gameKey&&Array.isArray(hit.items)&&hit.items.length){
          readyKnownMediaKeys.add(hit.gameKey);
        }
        return Array.isArray(hit.items)?hit.items.slice():[];
      }
      state.fallbacks+=1;
      state.totalFallbacks+=1;
      const started=now();
      try{
        const result=originalPlayable(match);
        // If the legacy path resolves media during this render, memoize by stable
        // game aliases for subsequent object clones of the same card.
        if(Array.isArray(result)&&result.length){
          const found=planForMatch(match,currentDate());
          const known=Array.isArray(found?.plan?.playable)&&found.plan.playable.length>0;
          const gameKey=stableKey(match,currentDate());
          putForMatch(match,{kind:'legacy-resolved',items:result,gameKey,knownDatabaseMedia:known});
          if(known&&gameKey)readyKnownMediaKeys.add(gameKey);
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
      renderId:state.renderId,date:currentDate(),filter:currentFilter(),
      indexed:state.indexed,planCount:state.planCount,
      scheduled:state.scheduled,thin:state.thin,
      planPlayable:state.planPlayable,sessionVerified:state.sessionVerified,
      knownMediaGames:state.knownMediaGames,
      knownMediaAssets:state.knownMediaAssets,
      mediaReadyGames:readyKnownMediaKeys.size,
      mediaReadyComplete:state.knownMediaGames===0||readyKnownMediaKeys.size>=state.knownMediaGames,
      fastHits:state.fastHits,fallbacks:state.fallbacks,
      indexBuildMs:state.indexBuildMs,fallbackMs:round(state.fallbackMs)
    };
    state.last=report;
    state.active=false;
    rows=new Map();planAliases=new Map();readyKnownMediaKeys=new Set();
    try{
      window.dispatchEvent(new CustomEvent('sbb:availability-index',{
        detail:{...report,at:Date.now()}
      }));
    }catch(_){}
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

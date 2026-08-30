/* Sports Big Board v4.7.16 — Efficiency-Hardened First-Paint Render Pipeline.
   A date transition owns one generation. Full renders build one all-league card
   bank for the active date; league filters then reuse those exact score-card DOM
   nodes and only change visibility. Canonical date/media renders still use the
   existing builder, staged through one DocumentFragment commit.
*/
(() => {
  'use strict';
  if(window.SBB_RENDER_PIPELINE?.version==='4.7.16')return;

  const VERSION='4.7.16';
  const state={
    installed:false,calls:0,requested:0,executed:0,coalesced:0,reentrant:0,
    generationCoalesced:0,fragmentCommits:0,lastKey:'',lastStartedAt:0,
    lastFinishedAt:0,lastDurationMs:0,totalDurationMs:0,maxDurationMs:0,
    samples:[],lastResult:undefined,currentReason:'',reasonCounts:{},
    holdGeneration:0,holdDate:'',holdOpen:false,pendingReasons:new Set(),
    pendingAnimate:false,commitPromise:null,generationCommits:0,
    filterFastPaths:0,filterFastPathMisses:0,cardBankBuilds:0,cardBankPrunes:0,
  };
  const now=()=>performance.now();
  const round=v=>Math.round(v*10)/10;
  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const globalNodeCount=()=>{try{return document.getElementsByTagName('*').length;}catch(_){return 0;}};

  function currentDate(){
    try{return String(scoreBrowseDate||'');}
    catch(_){return String(window.scoreBrowseDate||'');}
  }
  function currentFilter(){
    try{return String(scoreRibbonLeagueFilter||'ALL');}
    catch(_){return String(window.scoreRibbonLeagueFilter||'ALL');}
  }
  function setCurrentFilter(value){
    value=upper(value)||'ALL';
    let assigned=false;
    try{scoreRibbonLeagueFilter=value;assigned=true;}catch(_){}
    try{
      if(Object.prototype.hasOwnProperty.call(window,'scoreRibbonLeagueFilter')){
        window.scoreRibbonLeagueFilter=value;assigned=true;
      }
    }catch(_){}
    return assigned;
  }
  function matchesForDate(date=currentDate()){
    try{
      const rows=typeof scoreMatchesForDate==='function'?scoreMatchesForDate(date):[];
      return Array.isArray(rows)?rows:[];
    }catch(_){return [];}
  }
  function stableGameKey(match){
    try{
      if(typeof scoreRibbonStableGameKey==='function'){
        const key=clean(scoreRibbonStableGameKey(match));
        if(key)return key;
      }
    }catch(_){}
    const lg=upper(match?.competitionId||match?.__sbbLeague||match?.league||match?.sport||'SPORTS');
    const id=[match?.scoreEventId,match?.espnEventId,match?.gameCenterEventId,match?.matchId,match?.gamePk,match?.eventId,match?.id]
      .find(x=>x!==undefined&&x!==null&&clean(x)!=='');
    if(id!==undefined)return `${lg}:ID:${clean(id)}`;
    const team=v=>upper(v?.name||v?.displayName||v?.shortDisplayName||v?.abbreviation||v||'');
    const away=team(match?.awayTeam||match?.away||match?.awayName);
    const home=team(match?.homeTeam||match?.home||match?.homeName);
    const date=clean(match?.__sbbDate||match?.gameDate||match?.date||currentDate()).slice(0,10);
    return `${lg}:${date}:${away}:${home}`;
  }
  function expectedBankKeys(date=currentDate()){
    return matchesForDate(date).map(stableGameKey).filter(Boolean).sort();
  }
  function gameCards(host){
    return host?[...host.children].filter(el=>el?.classList?.contains('score-card')&&!el.classList.contains('roundup-card')):[];
  }
  function actualBankKeys(host){
    return gameCards(host).map(card=>clean(card.dataset?.sbbGameKey)).filter(Boolean).sort();
  }
  function sameKeys(a,b){
    if(a.length!==b.length)return false;
    for(let i=0;i<a.length;i++)if(a[i]!==b[i])return false;
    return true;
  }
  function bankComplete(host,date=currentDate()){
    if(!host||clean(host.dataset?.sbbCardBankDate)!==clean(date).slice(0,10))return false;
    const expected=expectedBankKeys(date);
    const actual=actualBankKeys(host);
    if(expected.length===0)return actual.length===0&&!!host.querySelector('.roundup-card');
    return sameKeys(expected,actual);
  }
  function markBank(host,date=currentDate()){
    if(!host)return;
    const expected=expectedBankKeys(date);
    host.dataset.sbbCardBankDate=clean(date).slice(0,10);
    host.dataset.sbbCardBankCount=String(expected.length);
    host.dataset.sbbCardBankVersion=VERSION;
  }
  function leagueForCard(card){
    if(!card)return '';
    for(const cls of card.classList||[]){
      if(cls.startsWith('league-'))return upper(cls.slice(7));
    }
    return '';
  }
  function refreshRoundupCard(host,date=currentDate()){
    if(!host)return false;
    let next=null;
    try{
      if(typeof buildSilverRoundupScoreCard==='function')next=buildSilverRoundupScoreCard(date);
    }catch(_){}
    if(!next)return false;
    const previous=[...host.children].find(el=>el?.classList?.contains('roundup-card'))||null;
    if(previous)previous.replaceWith(next);
    else host.prepend(next);
    return true;
  }
  function postFilterReconcile(){
    try{if(typeof applyScoreRibbonFocusVisuals==='function')applyScoreRibbonFocusVisuals({scroll:false});}catch(_){}
    try{if(typeof updateScoreDayPager==='function')updateScoreDayPager();}catch(_){}
    try{if(typeof scheduleScoreMediaWarmReconcile==='function')scheduleScoreMediaWarmReconcile(0);}catch(_){}
  }
  function applyBankFilter(host,filter=currentFilter(),{refreshRoundup=true}={}){
    if(!host)return {visible:0,total:0,roundupRefreshed:false};
    filter=upper(filter)||'ALL';
    const cards=gameCards(host);
    let visible=0;
    for(const card of cards){
      const show=filter==='ALL'||leagueForCard(card)===filter;
      card.hidden=!show;
      if(show)visible+=1;
    }
    const roundupRefreshed=refreshRoundup?refreshRoundupCard(host,currentDate()):false;
    postFilterReconcile();
    return {visible,total:cards.length,roundupRefreshed};
  }
  function renderKey(){
    const date=currentDate(),filter=currentFilter();
    return `${date}|${filter}|${matchesForDate(date).length}`;
  }
  function inferReason(explicit=''){
    const direct=clean(explicit||window.__SBB_RENDER_REASON||state.currentReason);
    if(direct)return direct;
    try{
      const stack=String(new Error().stack||'').toLowerCase();
      if(stack.includes('day-state'))return 'day-state';
      if(stack.includes('historical'))return 'historical-media';
      if(stack.includes('scorefilter')||stack.includes('wirescorefilters'))return 'filter-change';
      if(stack.includes('setscorebrowsedate')||stack.includes('date-transition'))return 'date-change';
      if(stack.includes('media'))return 'media-state';
    }catch(_){}
    return 'unspecified';
  }
  function emit(type,detail={}){
    try{
      window.dispatchEvent(new CustomEvent('sbb:render-pipeline',{
        detail:{type,at:Date.now(),...detail}
      }));
    }catch(_){}
  }
  function incrementReason(reason){
    const key=clean(reason)||'unspecified';
    state.reasonCounts[key]=(state.reasonCounts[key]||0)+1;
  }

  function withFragment(host,fn){
    if(!host)return {result:fn(),buildMs:0,commitMs:0,stagedNodes:0};
    const fragment=document.createDocumentFragment();
    const nativeAppend=host.appendChild;
    const hadOwn=Object.prototype.hasOwnProperty.call(host,'appendChild');
    const previousOwn=hadOwn?host.appendChild:null;
    const buildStarted=now();
    let result;
    try{
      Object.defineProperty(host,'appendChild',{
        configurable:true,writable:true,
        value(node){return fragment.appendChild(node);}
      });
      result=fn();
    }finally{
      if(hadOwn){
        Object.defineProperty(host,'appendChild',{
          configurable:true,writable:true,value:previousOwn
        });
      }else{
        try{delete host.appendChild;}catch(_){}
      }
    }
    const buildMs=round(now()-buildStarted);
    const stagedNodes=fragment.childElementCount;
    const commitStarted=now();
    if(fragment.childNodes.length)nativeAppend.call(host,fragment);
    const commitMs=round(now()-commitStarted);
    if(stagedNodes)state.fragmentCommits+=1;
    return {result,buildMs,commitMs,stagedNodes};
  }

  function availabilityForDate(date){
    try{
      return window.SBB_SCORECARD_AVAILABILITY_INDEX?.forDate?.(date)
        || window.SBB_SCORECARD_AVAILABILITY_INDEX?.snapshot?.().last
        || null;
    }catch(_){return null;}
  }
  function recordRender({started,key,reason,host,beforeNodes,batched,meta,cacheStats,availabilityStats,fastPath=false,cardBankBuild=false,filterApplyMs=0,visibleCards=0}){
    const finished=now();
    const duration=round(finished-started);
    const afterNodes=host?.childElementCount||0;
    const row={
      at:Date.now(),runId:String(window.__SBB_EFFICIENCY_RUN_ID||''),durationMs:duration,key,reason,
      date:currentDate(),filter:currentFilter(),
      perfStartedAt:round(started),perfFinishedAt:round(finished),
      beforeNodes,afterNodes,
      globalNodesBefore:Number(meta.globalNodesBefore||0),globalNodesAfter:globalNodeCount(),
      buildMs:Number(batched?.buildMs||0),commitMs:Number(batched?.commitMs||0),
      stagedNodes:Number(batched?.stagedNodes||0),generation:Number(meta.generation||0),
      generationCommit:!!meta.generationCommit,
      filterFastPath:!!fastPath,cardBankBuild:!!cardBankBuild,
      filterApplyMs:round(Number(filterApplyMs||0)),visibleCards:Number(visibleCards||0),
      cardCacheHits:Number(cacheStats?.hits||0),
      cardCacheMisses:Number(cacheStats?.misses||0),
      cardHelperMs:Number(cacheStats?.helperMs||0),
      cardHelpers:cacheStats?.helpers||{},
      availabilityIndexed:Number(availabilityStats?.indexed||0),
      availabilityScheduled:Number(availabilityStats?.scheduled||0),
      availabilityThin:Number(availabilityStats?.thin||0),
      availabilityPlanCount:Number(availabilityStats?.planCount||0),
      availabilityPlanPlayable:Number(availabilityStats?.planPlayable||0),
      availabilitySessionVerified:Number(availabilityStats?.sessionVerified||0),
      availabilityKnownMediaGames:Number(availabilityStats?.knownMediaGames||0),
      availabilityKnownMediaAssets:Number(availabilityStats?.knownMediaAssets||0),
      availabilityMediaReadyGames:Number(availabilityStats?.mediaReadyGames||0),
      availabilityMediaReadyComplete:availabilityStats?.mediaReadyComplete!==false,
      availabilityFastHits:Number(availabilityStats?.fastHits||0),
      availabilityFallbacks:Number(availabilityStats?.fallbacks||0),
      availabilityIndexBuildMs:Number(availabilityStats?.indexBuildMs||0),
      availabilityFallbackMs:Number(availabilityStats?.fallbackMs||0),
      availabilitySnapshotReused:!!availabilityStats?.snapshotReused
    };
    state.lastKey=key;
    state.lastFinishedAt=finished;
    state.lastDurationMs=duration;
    state.totalDurationMs=round(state.totalDurationMs+duration);
    state.maxDurationMs=Math.max(state.maxDurationMs,duration);
    state.samples.push(row);
    if(state.samples.length>300)state.samples.splice(0,state.samples.length-300);
    emit('render',{
      ...row,calls:state.calls,requested:state.requested,
      executed:state.executed,coalesced:state.coalesced
    });
    const commitFinished=finished;
    requestAnimationFrame(()=>emit('paint',{
      key,reason,generation:Number(meta.generation||0),
      generationCommit:!!meta.generationCommit,
      paintDelayMs:round(now()-commitFinished),
      afterNodes:host?.childElementCount||0,filterFastPath:!!fastPath
    }));
    return row;
  }

  function install(){
    if(typeof window.renderScoresFromMatchesCombined!=='function')return false;
    if(window.renderScoresFromMatchesCombined.__sbbRenderPipeline)return true;
    const original=window.renderScoresFromMatchesCombined;
    let inRender=false;

    function execute(animate=false,reason='unspecified',meta={}){
      const started=now();
      const key=renderKey();
      const host=document.getElementById('scoreCells');
      const beforeNodes=host?.childElementCount||0;
      const selectedFilter=upper(currentFilter())||'ALL';
      const date=currentDate();
      meta={...meta,globalNodesBefore:globalNodeCount()};

      if(inRender){
        state.reentrant+=1;state.coalesced+=1;
        emit('coalesced',{key,reason,cause:'reentrant',generation:meta.generation||0});
        return state.lastResult;
      }
      if(!animate&&!meta.force&&key===state.lastKey&&(started-state.lastFinishedAt)<24){
        state.coalesced+=1;
        emit('coalesced',{key,reason,cause:'same-frame',generation:meta.generation||0});
        return state.lastResult;
      }

      const filterReason=clean(reason).includes('filter-change');
      if(filterReason&&bankComplete(host,date)){
        inRender=true;
        state.executed+=1;state.filterFastPaths+=1;state.lastStartedAt=started;
        incrementReason(reason);
        const filterStarted=now();
        let applied={visible:0,total:0};
        try{
          applied=applyBankFilter(host,selectedFilter,{refreshRoundup:true});
          return state.lastResult;
        }finally{
          const availabilityStats=availabilityForDate(date);
          recordRender({
            started,key,reason,host,beforeNodes,
            batched:{result:state.lastResult,buildMs:round(now()-filterStarted),commitMs:0,stagedNodes:0},
            meta,cacheStats:null,availabilityStats:{...(availabilityStats||{}),snapshotReused:true},
            fastPath:true,cardBankBuild:false,filterApplyMs:now()-filterStarted,visibleCards:applied.visible
          });
          inRender=false;
        }
      }
      if(filterReason)state.filterFastPathMisses+=1;

      inRender=true;
      state.executed+=1;
      state.lastStartedAt=started;
      incrementReason(reason);
      let forcedAll=false;
      try{forcedAll=setCurrentFilter('ALL');}catch(_){}
      const availabilityToken=window.SBB_SCORECARD_AVAILABILITY_INDEX?.beginRender?.({
        generation:Number(meta.generation||0),reason,cardBank:true,date
      });
      const cacheToken=window.SBB_CARD_BUILD_CACHE?.beginRender?.({
        generation:Number(meta.generation||0),reason
      });
      let availabilityStats=null;
      let cacheStats=null;
      let batched={result:undefined,buildMs:0,commitMs:0,stagedNodes:0};
      let succeeded=false;
      let applied={visible:0,total:0};
      let filterApplyMs=0;
      try{
        batched=withFragment(host,()=>original(animate));
        state.lastResult=batched.result;
        succeeded=true;
        return batched.result;
      }finally{
        if(forcedAll)setCurrentFilter(selectedFilter);
        if(succeeded){
          markBank(host,date);state.cardBankBuilds+=1;
          const filterStarted=now();
          applied=applyBankFilter(host,selectedFilter,{refreshRoundup:selectedFilter!=='ALL'});
          filterApplyMs=now()-filterStarted;
        }
        cacheStats=window.SBB_CARD_BUILD_CACHE?.endRender?.(cacheToken)||null;
        availabilityStats=window.SBB_SCORECARD_AVAILABILITY_INDEX?.endRender?.(availabilityToken)||null;
        recordRender({
          started,key,reason,host,beforeNodes,batched,meta,cacheStats,availabilityStats,
          fastPath:false,cardBankBuild:succeeded,filterApplyMs,visibleCards:applied.visible
        });
        inRender=false;
      }
    }

    function wrapped(animate=false){
      state.calls+=1;
      const reason=inferReason();
      const date=currentDate();
      if(!animate&&state.holdOpen&&state.holdGeneration&&date===state.holdDate){
        state.requested+=1;
        state.pendingReasons.add(reason);
        state.coalesced+=1;
        state.generationCoalesced+=1;
        emit('coalesced',{key:renderKey(),reason,cause:'generation-hold',generation:state.holdGeneration});
        return state.lastResult;
      }
      return execute(animate,reason);
    }

    wrapped.__sbbRenderPipeline=true;
    wrapped.__sbbOriginal=original;
    wrapped.__sbbExecute=execute;
    window.renderScoresFromMatchesCombined=wrapped;
    state.execute=execute;
    state.installed=true;
    return true;
  }

  function beginGeneration(generation,date){
    generation=Number(generation||0);
    if(!generation)return false;
    state.holdGeneration=generation;
    state.holdDate=String(date||'').slice(0,10);
    state.holdOpen=true;
    state.pendingReasons.clear();
    state.pendingAnimate=false;
    state.commitPromise=null;
    emit('generation-begin',{generation,date:state.holdDate});
    return true;
  }

  function request(reason='unspecified',{generation=0,animate=false}={}){
    state.requested+=1;
    reason=inferReason(reason);
    if(state.holdOpen&&state.holdGeneration&&
       (!generation||Number(generation)===state.holdGeneration)&&
       currentDate()===state.holdDate){
      state.pendingReasons.add(reason);
      state.pendingAnimate=state.pendingAnimate||!!animate;
      state.coalesced+=1;
      state.generationCoalesced+=1;
      emit('coalesced',{key:renderKey(),reason,cause:'generation-request',generation:state.holdGeneration});
      return state.lastResult;
    }
    return withReason(reason,()=>window.renderScoresFromMatchesCombined?.(animate));
  }

  function commitGeneration(generation,{reason='canonical-first-paint',force=true}={}){
    generation=Number(generation||0);
    if(!generation||generation!==state.holdGeneration)return Promise.resolve(false);
    if(state.commitPromise)return state.commitPromise;

    state.holdOpen=false;
    state.pendingReasons.add(reason);
    const reasons=[...state.pendingReasons].filter(Boolean);
    const combined=reasons.length?reasons.join('+'):'canonical-first-paint';
    const animate=state.pendingAnimate;
    state.pendingReasons.clear();
    state.pendingAnimate=false;

    state.commitPromise=new Promise(resolve=>{
      requestAnimationFrame(()=>{
        if(generation!==state.holdGeneration){resolve(false);return;}
        state.generationCommits+=1;
        const result=state.execute?.(animate,combined,{
          force,generation,generationCommit:true
        });
        emit('generation-commit',{
          generation,date:state.holdDate,reason:combined,
          commits:state.generationCommits
        });
        state.holdGeneration=0;
        state.holdDate='';
        state.commitPromise=null;
        resolve(result);
      });
    });
    return state.commitPromise;
  }

  function cancelGeneration(generation,reason='superseded'){
    generation=Number(generation||0);
    if(!generation||generation!==state.holdGeneration)return false;
    emit('generation-cancel',{generation,date:state.holdDate,reason});
    state.holdGeneration=0;state.holdDate='';state.holdOpen=false;
    state.pendingReasons.clear();state.pendingAnimate=false;state.commitPromise=null;
    return true;
  }

  function withReason(reason,fn){
    const previous=window.__SBB_RENDER_REASON;
    window.__SBB_RENDER_REASON=String(reason||'unspecified');
    try{return fn();}finally{window.__SBB_RENDER_REASON=previous||'';}
  }

  function boot(){
    install();
    const timer=setInterval(()=>{if(install())clearInterval(timer);},250);
    setTimeout(()=>clearInterval(timer),5000);
  }

  window.SBB_RENDER_PIPELINE=Object.freeze({
    version:VERSION,install,withReason,beginGeneration,request,commitGeneration,cancelGeneration,
    bankComplete:()=>bankComplete(document.getElementById('scoreCells'),currentDate()),
    snapshot:()=>({
      version:VERSION,installed:state.installed,calls:state.calls,requested:state.requested,
      executed:state.executed,coalesced:state.coalesced,reentrant:state.reentrant,
      generationCoalesced:state.generationCoalesced,generationCommits:state.generationCommits,
      fragmentCommits:state.fragmentCommits,filterFastPaths:state.filterFastPaths,
      filterFastPathMisses:state.filterFastPathMisses,cardBankBuilds:state.cardBankBuilds,
      holdGeneration:state.holdGeneration,holdDate:state.holdDate,holdOpen:state.holdOpen,
      lastDurationMs:state.lastDurationMs,totalDurationMs:state.totalDurationMs,
      maxDurationMs:state.maxDurationMs,reasonCounts:{...state.reasonCounts},samples:[...state.samples],
    })
  });

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();

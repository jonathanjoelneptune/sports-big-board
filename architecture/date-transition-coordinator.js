/* Sports Big Board v5.1.20 — Date State Convergence Coordinator.
   Day State owns date truth. A slow/cold canonical day is LOADING, never EMPTY,
   until the backend explicitly returns a complete zero-game inventory. Thin score
   snapshots may paint immediately and then converge in-place to full media plans.
*/
(() => {
  'use strict';
  if(window.SBB_DATE_TRANSITIONS?.version==='5.1.20')return;

  const VERSION='5.1.20';
  // Fast probes cover the normal cold-cache case; the slower tail lets a focused
  // historical worker finish without requiring the user to leave and revisit.
  const CONVERGENCE_DELAYS=[250,500,900,1500,2500,4000,6500,10000,15000,22000,30000,30000,30000,30000];
  const state={
    generation:0,
    activeDate:'',
    currentPromise:null,
    firstPaintSource:'',
    lastElapsedMs:0,
    fallbacks:0,
    enrichments:0,
    enrichmentSkipped:0,
    staleSelectionsCleared:0,
    convergenceRuns:0,
    convergenceReads:0,
    convergenceCompleted:0,
    convergenceSuperseded:0,
    convergenceExhausted:0,
    pendingRibbonPaints:0,
    lastConvergenceDate:'',
    lastConvergenceGames:0,
    lastConvergenceComplete:false,
  };

  const clean=v=>String(v??'').trim();
  const day=v=>clean(v).slice(0,10);
  const now=()=>performance.now();
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const today=()=>typeof localDateISO==='function'
    ? localDateISO(0)
    : new Date().toISOString().slice(0,10);

  function normalize(value){
    let d=day(value||today());
    if(!/^\d{4}-\d{2}-\d{2}$/.test(d))d=today();
    return d;
  }

  function unwrapSetter(fn){
    const seen=new Set();
    let current=fn;
    while(current?.__sbbOriginal && !seen.has(current)){
      seen.add(current);
      current=current.__sbbOriginal;
    }
    return current||fn;
  }

  function eventDate(event){
    return day(
      event?.date ||
      event?.scheduledAt ||
      event?.startTime ||
      event?.startDate ||
      event?.__sbbDate
    );
  }

  function inventory(payload){
    const games=Math.max(0,Number(payload?.summary?.games??payload?.scoreGameCount??0)||0);
    const complete=payload?.scoreInventoryComplete===true;
    return {
      games,
      complete,
      hasGames:games>0,
      authoritativeEmpty:complete&&games===0,
      pending:!!payload?.pending,
      thin:!!payload?.thinSnapshot||payload?.projectionDiagnostics?.thinCatalog===true,
    };
  }

  function clearStaleSelection(date){
    try{
      const selected=window.SBB_SELECTED_EVENT?.get?.();
      if(selected && eventDate(selected) && eventDate(selected)!==date){
        window.SBB_SELECTED_EVENT?.clear?.({
          reason:'date-change',
          source:'date-transition-v5120'
        });
        state.staleSelectionsCleared+=1;
      }
    }catch(_){}
  }

  function scoreHost(){return document.getElementById('scoreCells');}
  function hasRealCards(host=scoreHost()){
    if(!host)return false;
    return [...host.querySelectorAll('.score-card')].some(card=>
      !!card.__sbbMatch || !!clean(card.dataset?.sbbGameKey)
    );
  }
  function clearPendingRibbon(){
    const host=scoreHost();
    if(!host)return;
    host.removeAttribute('aria-busy');
    host.classList.remove('sbb-day-state-pending');
  }
  function paintPendingRibbon(date,generation,message='Loading games…'){
    if(generation!==state.generation||date!==state.activeDate)return false;
    const host=scoreHost();
    if(!host||hasRealCards(host))return false;
    host.setAttribute('aria-busy','true');
    host.classList.add('sbb-day-state-pending');
    host.innerHTML='';
    const shell=document.createElement('div');
    shell.className='score-cell sbb-day-state-loading';
    const league=document.createElement('span');league.textContent='SPORTS';
    const line1=document.createElement('b');line1.textContent=message;
    const line2=document.createElement('b');line2.textContent=date;
    const status=document.createElement('small');status.textContent='CANONICAL DAY STATE';
    shell.append(league,line1,line2,status);
    host.appendChild(shell);
    state.pendingRibbonPaints+=1;
    return true;
  }

  function scheduleEnrichment(date,generation,payload){
    const inv=inventory(payload);
    if(inv.complete && inv.hasGames){
      state.enrichmentSkipped+=1;
      return;
    }

    // Roundups remain editorial enrichment. Score/media state convergence is owned
    // by the bounded Day State loop below and never launches browser discovery.
    setTimeout(()=>{
      if(generation!==state.generation || date!==state.activeDate)return;
      state.enrichments+=1;
      try{
        if(typeof loadRoundupsForDate==='function'){
          Promise.resolve(loadRoundupsForDate(date)).catch(()=>{});
        }
      }catch(_){}
    },10000);
  }

  async function converge(date,generation,seedPayload=null){
    state.convergenceRuns+=1;
    let latest=seedPayload;
    let inv=inventory(latest);
    state.lastConvergenceDate=date;
    state.lastConvergenceGames=inv.games;
    state.lastConvergenceComplete=inv.complete;

    if(inv.complete){
      clearPendingRibbon();
      state.convergenceCompleted+=1;
      return latest;
    }

    for(const delay of CONVERGENCE_DELAYS){
      await sleep(delay);
      if(generation!==state.generation||date!==state.activeDate){
        state.convergenceSuperseded+=1;
        return latest;
      }

      let payload=null;
      try{
        state.convergenceReads+=1;
        payload=await window.SBB_DAY_STATE?.load?.(date,{
          // Day State is cache-first on the server. force here means "perform a
          // new browser read" rather than "run provider discovery".
          force:true,
          timeoutMs:2200
        });
      }catch(_){payload=null;}

      if(generation!==state.generation||date!==state.activeDate){
        state.convergenceSuperseded+=1;
        return latest;
      }
      if(!payload){
        if(!hasRealCards())paintPendingRibbon(date,generation,'Loading games…');
        continue;
      }

      latest=payload;
      inv=inventory(payload);
      state.lastConvergenceGames=inv.games;
      state.lastConvergenceComplete=inv.complete;

      // apply() is invoked by Day State.load(). A thin score snapshot can therefore
      // replace the loading shell immediately; later full plans recolor the exact
      // same canonical games without a date-navigation round trip.
      if(inv.hasGames||inv.authoritativeEmpty)clearPendingRibbon();
      else paintPendingRibbon(date,generation,'Loading games…');

      if(inv.complete){
        state.convergenceCompleted+=1;
        return latest;
      }
    }

    if(generation===state.generation&&date===state.activeDate){
      state.convergenceExhausted+=1;
      if(!hasRealCards())paintPendingRibbon(date,generation,'Games are still warming…');
    }
    return latest;
  }

  function install(){
    if(typeof window.setScoreBrowseDate!=='function')return false;
    if(window.setScoreBrowseDate.__sbbDateCoordinatorV5120)return true;

    const wrappedBefore=window.setScoreBrowseDate;
    const shellSetter=unwrapSetter(wrappedBefore);

    async function transition(value,options={}){
      const date=normalize(value);
      if(state.currentPromise && state.activeDate===date)return state.currentPromise;

      const generation=++state.generation;
      state.activeDate=date;
      state.firstPaintSource='';
      const started=now();

      clearStaleSelection(date);
      window.SBB_REQUEST_BROKER?.beginDate?.(date,generation);
      window.SBB_RENDER_PIPELINE?.beginGeneration?.(generation,date);

      const shellPromise=Promise.resolve(
        date>today() && window.SBB_FUTURE_DATES?.setFutureShell
          ? window.SBB_FUTURE_DATES.setFutureShell(date,{hold:options?.hold})
          : shellSetter(date,{...options,load:false,dayStateFirstPaint:true})
      ).catch(()=>false);

      state.currentPromise=(async()=>{
        await shellPromise;
        if(generation!==state.generation)return true;

        let payload=null;
        try{
          const cached=window.SBB_DAY_STATE?.cache?.(date);
          if(cached){
            window.SBB_DAY_STATE?.apply?.(cached);
            payload=cached;
            state.firstPaintSource='DAY_STATE_CACHE';
          }
        }catch(_){}

        if(!payload){
          try{
            payload=await window.SBB_DAY_STATE?.load?.(date,{
              force:false,
              timeoutMs:900
            });
            if(payload)state.firstPaintSource='DAY_STATE';
          }catch(_){}
        }

        if(generation!==state.generation)return true;
        if(!payload)state.firstPaintSource='DAY_STATE_LOADING';

        try{
          await window.SBB_RENDER_PIPELINE?.commitGeneration?.(generation,{
            reason:state.firstPaintSource||'canonical-first-paint',
            force:true
          });
        }catch(_){
          try{window.renderScoresFromMatchesCombined?.(false);}catch(__){}
        }
        try{window.updateScoreDayPager?.();}catch(_){}

        const inv=inventory(payload);
        if(!payload||(!inv.hasGames&&!inv.authoritativeEmpty)){
          paintPendingRibbon(date,generation,'Loading games…');
        }else{
          clearPendingRibbon();
        }

        scheduleEnrichment(date,generation,payload);
        // Do not await convergence: the date transition is interactive after first
        // paint. The background loop continues to converge this SAME selected date.
        void converge(date,generation,payload).catch(()=>{});

        state.lastElapsedMs=Math.round((now()-started)*10)/10;
        return true;
      })().finally(()=>{
        if(generation===state.generation)state.currentPromise=null;
        else window.SBB_RENDER_PIPELINE?.cancelGeneration?.(generation,'superseded-date');
      });

      return state.currentPromise;
    }

    transition.__sbbDateCoordinator=true;
    transition.__sbbDateCoordinatorV5120=true;
    transition.__sbbOriginal=shellSetter;
    transition.__sbbLegacyWrapped=wrappedBefore;
    window.setScoreBrowseDate=transition;
    try{setScoreBrowseDate=transition;}catch(_){}
    return true;
  }

  function boot(){
    install();
    const timer=setInterval(()=>{
      if(install())clearInterval(timer);
    },250);
    setTimeout(()=>clearInterval(timer),5000);
  }

  window.SBB_DATE_TRANSITIONS=Object.freeze({
    version:VERSION,
    install,
    converge,
    snapshot:()=>({
      version:VERSION,
      generation:state.generation,
      activeDate:state.activeDate,
      running:!!state.currentPromise,
      firstPaintSource:state.firstPaintSource,
      lastElapsedMs:state.lastElapsedMs,
      fallbacks:state.fallbacks,
      enrichments:state.enrichments,
      enrichmentSkipped:state.enrichmentSkipped,
      staleSelectionsCleared:state.staleSelectionsCleared,
      convergenceRuns:state.convergenceRuns,
      convergenceReads:state.convergenceReads,
      convergenceCompleted:state.convergenceCompleted,
      convergenceSuperseded:state.convergenceSuperseded,
      convergenceExhausted:state.convergenceExhausted,
      pendingRibbonPaints:state.pendingRibbonPaints,
      lastConvergenceDate:state.lastConvergenceDate,
      lastConvergenceGames:state.lastConvergenceGames,
      lastConvergenceComplete:state.lastConvergenceComplete,
    })
  });

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();

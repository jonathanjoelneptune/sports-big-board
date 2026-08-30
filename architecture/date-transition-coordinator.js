/* Sports Big Board v4.7.13 — Date Transition Coordinator.
   Day State owns first paint. Legacy history is compatibility-only. Browser discovery
   is not an automatic side effect of moving the ribbon; enrichment is deferred
   until the selected date is stable and only when canonical inventory is incomplete.
*/
(() => {
  'use strict';
  if(window.SBB_DATE_TRANSITIONS?.version==='4.7.13')return;

  const VERSION='4.7.13';
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
  };

  const clean=v=>String(v??'').trim();
  const day=v=>clean(v).slice(0,10);
  const now=()=>performance.now();
  const today=()=>typeof localDateISO==='function'
    ? localDateISO(0)
    : new Date().toISOString().slice(0,10);

  function normalize(value){
    let d=day(value||today());
    if(!/^\d{4}-\d{2}-\d{2}$/.test(d))d=today();
    // Future scheduled dates are valid Big Board dates. Day State decides whether
    // games exist; the navigation layer must not clamp tomorrow back to today.
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

  function clearStaleSelection(date){
    try{
      const selected=window.SBB_SELECTED_EVENT?.get?.();
      if(selected && eventDate(selected) && eventDate(selected)!==date){
        window.SBB_SELECTED_EVENT?.clear?.({
          reason:'date-change',
          source:'date-transition-v4713'
        });
        state.staleSelectionsCleared+=1;
      }
    }catch(_){}
  }

  function scheduleEnrichment(date,generation,payload){
    const complete=!!payload?.scoreInventoryComplete;
    const games=Number(payload?.summary?.games||payload?.scoreGameCount||0);
    if(complete && games>0){
      state.enrichmentSkipped+=1;
      return;
    }

    // Roundups are editorial enrichment only. Give first paint ten quiet seconds
    // and abandon the work completely if the user moves to another date.
    setTimeout(()=>{
      if(generation!==state.generation || date!==state.activeDate)return;
      state.enrichments+=1;
      try{
        if(typeof loadRoundupsForDate==='function'){
          Promise.resolve(loadRoundupsForDate(date)).catch(()=>{});
        }
      }catch(_){}
    },10000);

    // Historical discovery/media search is intentionally NOT launched here.
    // Discovery is owned by backend workers or explicit user/operator actions.
  }

  function install(){
    if(typeof window.setScoreBrowseDate!=='function')return false;
    if(window.setScoreBrowseDate.__sbbDateCoordinator)return true;

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

      // Pure shell update: never let the old score-date path start provider,
      // roundup, custom-media or discovery work before Day State first paint.
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
              timeoutMs:750
            });
            if(payload)state.firstPaintSource='DAY_STATE';
          }catch(_){}
        }

        if(generation!==state.generation)return true;

        // v4.7.10: interactive date navigation is Day State-only. A cold past
        // date is served by the backend's score-only COLD_THIN_CATALOG snapshot.
        // /api/history/ribbon remains compatibility-only and is never a first-paint
        // dependency of the Big Board date coordinator.
        if(!payload){
          state.firstPaintSource='DAY_STATE_PENDING_OR_EMPTY';
        }

        if(generation===state.generation){
          // v4.7.7: the transition owns exactly one first-paint ribbon commit.
          // Shell, Day State, and legacy compatibility render requests are held
          // until canonical state is ready, then committed together.
          try{
            await window.SBB_RENDER_PIPELINE?.commitGeneration?.(generation,{
              reason:state.firstPaintSource||'canonical-first-paint',
              force:true
            });
          }catch(_){
            try{window.renderScoresFromMatchesCombined?.(false);}catch(__){}
          }
          try{window.updateScoreDayPager?.();}catch(_){}
          scheduleEnrichment(date,generation,payload);
        }

        state.lastElapsedMs=Math.round((now()-started)*10)/10;
        return true;
      })().finally(()=>{
        if(generation===state.generation)state.currentPromise=null;
        else window.SBB_RENDER_PIPELINE?.cancelGeneration?.(generation,'superseded-date');
      });

      return state.currentPromise;
    }

    transition.__sbbDateCoordinator=true;
    transition.__sbbOriginal=shellSetter;
    transition.__sbbLegacyWrapped=wrappedBefore;
    window.setScoreBrowseDate=transition;
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
    })
  });

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();

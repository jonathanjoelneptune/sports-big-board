/* Sports Big Board v4.7.4 — Date Transition Coordinator.
   Day State owns first paint. Legacy history reconstruction is fallback-only.
   Roundups/media enrichment never blocks the ribbon date transition.
*/
(() => {
  'use strict';
  if(window.SBB_DATE_TRANSITIONS?.version==='4.7.4')return;

  const VERSION='4.7.4';
  const state={
    generation:0,
    activeDate:'',
    currentPromise:null,
    firstPaintSource:'',
    lastElapsedMs:0,
    fallbacks:0,
    enrichments:0,
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
    if(d>today())d=today();
    return d;
  }

  function idle(fn,timeout=350){
    if(typeof requestIdleCallback==='function'){
      requestIdleCallback(()=>fn(),{timeout});
    }else{
      setTimeout(fn,80);
    }
  }

  function scheduleEnrichment(date,generation){
    idle(()=>{
      if(generation!==state.generation || date!==state.activeDate)return;
      state.enrichments+=1;

      // Roundups are useful, but they are not a prerequisite for score ribbon paint.
      try{
        if(typeof loadRoundupsForDate==='function'){
          Promise.resolve(loadRoundupsForDate(date)).catch(()=>{});
        }
      }catch(_){}

      // Discovery is background-only. Request Broker coalesces any other consumer.
      if(date<today()){
        try{
          fetch(`/api/history/discovery?date=${encodeURIComponent(date)}`,{
            cache:'no-store'
          }).catch(()=>{});
        }catch(_){}
      }
    });
  }

  function install(){
    if(typeof window.setScoreBrowseDate!=='function')return false;
    if(window.setScoreBrowseDate.__sbbDateCoordinator)return true;

    const wrappedBefore=window.setScoreBrowseDate;
    // day-state.js wraps the app setter and exposes the app setter here.
    // Bypass that wrapper so there is exactly one Day State request per transition.
    const shellSetter=wrappedBefore.__sbbOriginal || wrappedBefore;

    const ribbonWrapped=window.hydrateHistoricalRibbonFromCatalog;
    const legacyRibbonFallback=
      ribbonWrapped?.__sbbFallback ||
      ribbonWrapped ||
      null;

    async function transition(value,options={}){
      const date=normalize(value);
      if(state.currentPromise && state.activeDate===date)return state.currentPromise;

      const generation=++state.generation;
      state.activeDate=date;
      state.firstPaintSource='';
      const started=now();

      window.SBB_REQUEST_BROKER?.beginDate?.(date,generation);

      // Update selected date, labels and existing cached score rows immediately.
      // Crucially: load:false prevents the old setter from blocking on roundups.
      const shellPromise=Promise.resolve(
        shellSetter(date,{...options,load:false})
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
              timeoutMs:700
            });
            if(payload)state.firstPaintSource='DAY_STATE';
          }catch(_){}
        }

        if(generation!==state.generation)return true;

        // Historical fallback is now single-purpose: ribbon rows + media plans only.
        // Do not run the old ribbon+roundups+discovery aggregate path for first paint.
        if(!payload && date<today() && typeof legacyRibbonFallback==='function'){
          state.fallbacks+=1;
          state.firstPaintSource='LEGACY_RIBBON_FALLBACK';
          try{await legacyRibbonFallback(date);}catch(_){}
        }else if(!payload){
          state.firstPaintSource='LIVE_OR_EXISTING_CACHE';
        }

        if(generation===state.generation){
          try{window.renderScoresFromMatchesCombined?.(false);}catch(_){}
          try{window.updateScoreDayPager?.();}catch(_){}
          scheduleEnrichment(date,generation);
        }

        state.lastElapsedMs=Math.round((now()-started)*10)/10;
        return true;
      })().finally(()=>{
        if(generation===state.generation)state.currentPromise=null;
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
    // app.js and day-state.js are loaded before this module, but retain a narrow
    // retry for unusual deferred-script environments. No document observer.
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
    })
  });

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();

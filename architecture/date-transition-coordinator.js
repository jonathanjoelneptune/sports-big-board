/* Sports Big Board v5.2.4 — single-owner prepared-snapshot date convergence.

   Date navigation is a lookup, not a discovery workflow. This coordinator owns the
   visible date transition. It deliberately strips legacy wrappers that independently
   fetched/prefetched RibbonSnapshot so one click cannot fan out into a request storm.
*/
(() => {
  'use strict';
  if(window.SBB_DATE_TRANSITIONS?.version==='5.2.4')return;
  const VERSION='5.2.4';
  const CONVERGENCE_DELAYS=[600,1800,5000,12000];
  const state={generation:0,activeDate:'',currentPromise:null,firstPaintSource:'',lastElapsedMs:0,
    convergenceRuns:0,convergenceReads:0,convergenceCompleted:0,convergenceSuperseded:0,
    convergenceExhausted:0,pendingRibbonPaints:0,snapshotFirstPaints:0,dayStateFallbacks:0,
    staleSelectionsCleared:0,lastConvergenceDate:'',lastConvergenceGames:0,lastConvergenceComplete:false,
    ownershipReasserts:0,maxSnapshotReadsPerTransition:5};
  const clean=v=>String(v??'').trim();
  const day=v=>clean(v).slice(0,10);
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const today=()=>typeof localDateISO==='function'?localDateISO(0):new Date().toISOString().slice(0,10);
  function normalize(v){const d=day(v||today());return /^\d{4}-\d{2}-\d{2}$/.test(d)?d:today();}
  function unwrapSetter(fn){const seen=new Set();let cur=fn;while(cur?.__sbbOriginal&&!seen.has(cur)){seen.add(cur);cur=cur.__sbbOriginal;}return cur||fn;}
  function inventory(payload){const games=Math.max(0,Number(payload?.summary?.games??payload?.scoreGameCount??0)||0),complete=payload?.scoreInventoryComplete===true;return {games,complete,hasGames:games>0,authoritativeEmpty:complete&&games===0,pending:!!payload?.pending};}
  function eventDate(evt){return day(evt?.date||evt?.scheduledAt||evt?.startTime||evt?.startDate||evt?.__sbbDate);}
  function clearStaleSelection(date){try{const selected=window.SBB_SELECTED_EVENT?.get?.();if(selected&&eventDate(selected)&&eventDate(selected)!==date){window.SBB_SELECTED_EVENT?.clear?.({reason:'date-change',source:'date-transition-v524'});state.staleSelectionsCleared++;}}catch(_){}}
  function scoreHost(){return document.getElementById('scoreCells');}
  function hasRealCards(){const host=scoreHost();return !!host&&[...host.querySelectorAll('.score-card')].some(c=>!!c.__sbbMatch||!!clean(c.dataset?.sbbGameKey));}

  function injectStyle(){
    if(document.getElementById('sbbDateTransitionV524Style'))return;
    const style=document.createElement('style');style.id='sbbDateTransitionV524Style';
    style.textContent=`
      .sbb-day-state-pending .score-empty-day,.sbb-day-state-pending .sbb-day-state-loading{display:none!important}
      .sbb-ribbon-skeleton{display:flex;gap:0;min-width:100%;height:84px;overflow:hidden;pointer-events:none}
      .sbb-ribbon-skeleton i{display:block;flex:0 0 166px;height:78px;border-right:1px solid var(--line,#25303a);background:linear-gradient(100deg,rgba(255,255,255,.025) 20%,rgba(255,255,255,.07) 38%,rgba(255,255,255,.025) 56%);background-size:220% 100%;animation:sbbSkeleton 1.2s linear infinite}
      @keyframes sbbSkeleton{to{background-position-x:-220%}}
      @media(max-width:760px){.sbb-ribbon-skeleton i{flex-basis:162px;height:70px}}
    `;document.head.appendChild(style);
  }
  function clearPendingRibbon(){const host=scoreHost();if(!host)return;host.removeAttribute('aria-busy');host.classList.remove('sbb-day-state-pending');host.querySelector('.sbb-ribbon-skeleton')?.remove();}
  function paintPendingRibbon(date,generation){
    if(generation!==state.generation||date!==state.activeDate||hasRealCards())return false;
    const host=scoreHost();if(!host)return false;host.setAttribute('aria-busy','true');host.classList.add('sbb-day-state-pending');
    host.querySelectorAll('.score-empty-day,.sbb-day-state-loading').forEach(n=>n.remove());
    if(!host.querySelector('.sbb-ribbon-skeleton')){const shell=document.createElement('div');shell.className='sbb-ribbon-skeleton';for(let i=0;i<7;i++)shell.appendChild(document.createElement('i'));host.appendChild(shell);}
    state.pendingRibbonPaints++;return true;
  }
  async function snapshotFirst(date,{apply=true,timeoutMs=900}={}){
    const vr=window.SBB_VIRTUAL_RIBBON;
    try{const resident=vr?.peekSnapshot?.(date);if(resident){if(apply)window.SBB_DAY_STATE?.apply?.(resident);return resident;}}catch(_){}
    try{const cached=await vr?.readCachedSnapshot?.(date,{apply});if(cached)return cached;}catch(_){}
    try{const remote=await vr?.fetchSnapshot?.(date,{apply,timeoutMs});if(remote)return remote;}catch(_){}
    return null;
  }
  async function converge(date,generation,seed=null){
    state.convergenceRuns++;let latest=seed,inv=inventory(latest);state.lastConvergenceDate=date;
    if(inv.complete){clearPendingRibbon();state.convergenceCompleted++;return latest;}
    for(const delay of CONVERGENCE_DELAYS){
      await sleep(delay);if(generation!==state.generation||date!==state.activeDate){state.convergenceSuperseded++;return latest;}
      state.convergenceReads++;const payload=await snapshotFirst(date,{apply:true,timeoutMs:1300});
      if(generation!==state.generation||date!==state.activeDate){state.convergenceSuperseded++;return latest;}
      if(!payload){paintPendingRibbon(date,generation);continue;}
      latest=payload;inv=inventory(payload);state.lastConvergenceGames=inv.games;state.lastConvergenceComplete=inv.complete;
      if(inv.hasGames||inv.authoritativeEmpty){clearPendingRibbon();try{window.SBB_RENDER_PIPELINE?.request?.('snapshot-converged',{animate:false});}catch(_){} }
      if(inv.complete){state.convergenceCompleted++;return latest;}
    }
    if(generation===state.generation&&date===state.activeDate){state.convergenceExhausted++;paintPendingRibbon(date,generation);}return latest;
  }
  function install(){
    if(typeof window.setScoreBrowseDate!=='function')return false;
    if(window.setScoreBrowseDate.__sbbDateCoordinatorV524)return true;
    const wrappedBefore=window.setScoreBrowseDate,shellSetter=unwrapSetter(wrappedBefore);
    async function transition(value,options={}){
      const date=normalize(value);if(state.currentPromise&&state.activeDate===date)return state.currentPromise;
      const generation=++state.generation;state.activeDate=date;state.firstPaintSource='';const started=performance.now();
      window.SBB_REQUEST_BROKER?.beginDate?.(date,generation);window.SBB_RENDER_PIPELINE?.beginGeneration?.(generation,date);
      state.currentPromise=(async()=>{
        let payload=await snapshotFirst(date,{apply:true,timeoutMs:900});
        if(generation!==state.generation)return true;
        if(payload){state.firstPaintSource='RIBBON_SNAPSHOT';state.snapshotFirstPaints++;}
        clearStaleSelection(date);
        await Promise.resolve(date>today()&&window.SBB_FUTURE_DATES?.setFutureShell
          ? window.SBB_FUTURE_DATES.setFutureShell(date,{hold:options?.hold})
          : shellSetter(date,{...options,load:false,dayStateFirstPaint:true})).catch(()=>false);
        if(generation!==state.generation)return true;
        if(payload)try{window.SBB_DAY_STATE?.apply?.(payload);}catch(_){}
        if(!payload){try{const cached=window.SBB_DAY_STATE?.cache?.(date);if(cached){window.SBB_DAY_STATE?.apply?.(cached);payload=cached;state.firstPaintSource='DAY_STATE_CACHE';}}catch(_){} }
        if(!payload){try{payload=await window.SBB_DAY_STATE?.load?.(date,{force:false,timeoutMs:1100});if(payload){state.dayStateFallbacks++;state.firstPaintSource='DAY_STATE_FALLBACK';}}catch(_){} }
        if(generation!==state.generation)return true;
        try{await window.SBB_RENDER_PIPELINE?.commitGeneration?.(generation,{reason:state.firstPaintSource||'snapshot-pending',force:true});}catch(_){try{window.renderScoresFromMatchesCombined?.(false);}catch(__){}}
        try{window.updateScoreDayPager?.();}catch(_){}
        const inv=inventory(payload);if(!payload||(!inv.hasGames&&!inv.authoritativeEmpty))paintPendingRibbon(date,generation);else clearPendingRibbon();
        if(!inv.complete)void converge(date,generation,payload).catch(()=>{});
        state.lastElapsedMs=Math.round((performance.now()-started)*10)/10;return true;
      })().finally(()=>{if(generation===state.generation)state.currentPromise=null;else window.SBB_RENDER_PIPELINE?.cancelGeneration?.(generation,'superseded-date');});
      return state.currentPromise;
    }
    transition.__sbbDateCoordinator=true;transition.__sbbDateCoordinatorV524=true;transition.__sbbOriginal=shellSetter;transition.__sbbLegacyWrapped=wrappedBefore;
    window.setScoreBrowseDate=transition;try{setScoreBrowseDate=transition;}catch(_){}state.ownershipReasserts++;return true;
  }
  function boot(){
    injectStyle();install();
    // v5.2.2 virtual-ribbon boot can attach a second date wrapper for ~3.5 s. Keep
    // reasserting the single-owner coordinator until all legacy installers have quit.
    let ticks=0;const timer=setInterval(()=>{ticks++;install();if(ticks>=32)clearInterval(timer);},250);
    setTimeout(()=>{try{install();}catch(_){}},8500);
  }
  window.SBB_DATE_TRANSITIONS=Object.freeze({version:VERSION,install,converge,snapshot:()=>({...state,running:!!state.currentPromise})});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();

/* Sports Big Board v4.7.8 — historical database-first media hardening.
   The original v4.6.10 safety barrier remains for explicit legacy loads/search,
   but a Day State first-paint shell transition no longer creates a barrier that
   can never finish simply because load:false intentionally skipped legacy loading.
*/
(() => {
  if (window.SBB_HISTORICAL_MEDIA_HARDENING?.version === '4.7.8') return;
  const todayISO = () => localDateISO(0);
  const original = {
    ensure: ensureScoreDateLoaded,
    setDate: setScoreBrowseDate,
    render: renderScoresFromMatchesCombined,
    queue: queueHistoricalGameMedia,
    scheduleFill: scheduleRecentHistoricalRecapFill,
  };
  const state = {version:'4.7.8',generation:0,barriers:new Map(),deferredFill:new Set(),lastReport:new Map()};
  const dateOf = value => String(value || '').slice(0,10);
  const isHistorical = date => /^\d{4}-\d{2}-\d{2}$/.test(dateOf(date)) && dateOf(date) < todayISO();
  const barrierFor = date => state.barriers.get(dateOf(date)) || null;

  function beginBarrier(date){
    date=dateOf(date); if(!isHistorical(date)) return null;
    const existing=barrierFor(date); if(existing?.pending) return existing;
    let resolve; const promise=new Promise(r=>{resolve=r});
    const barrier={date,generation:state.generation,pending:true,promise,resolve,startedAt:Date.now()};
    state.barriers.set(date,barrier);
    if(scoreBrowseDate===date){setFeedNote(`${date} • checking database media associations before search…`);queueMicrotask(decoratePendingCards)}
    return barrier;
  }

  function historicalReadiness(date){
    const finals=scoreMatchesForDate(date).filter(isFinal);let ready=0;
    for(const match of finals) if(scoreCardPlayableItems(match).length) ready++;
    return {games:finals.length,ready,missing:Math.max(0,finals.length-ready)};
  }

  function finishBarrier(barrier){
    if(!barrier||!barrier.pending)return;
    barrier.pending=false;const readiness=historicalReadiness(barrier.date);
    state.lastReport.set(barrier.date,{...readiness,finishedAt:Date.now()});barrier.resolve(readiness);
    if(barrier.generation!==state.generation||scoreBrowseDate!==barrier.date)return;
    renderScoresFromMatchesCombined(false);
    setFeedNote(`${barrier.date} • DB ASSOCIATION ${readiness.games}/${readiness.games} checked • ${readiness.ready} ribbon-ready • ${readiness.missing} missing`);
    if(state.deferredFill.delete(barrier.date)&&readiness.missing>0) original.scheduleFill(barrier.date);
  }

  function decoratePendingCards(){
    const date=dateOf(scoreBrowseDate),barrier=barrierFor(date);if(!barrier?.pending||!isHistorical(date))return;
    document.querySelectorAll('#scoreCells .historical-find-media').forEach(cell=>{
      cell.classList.remove('historical-find-media','historical-searching-media');cell.classList.add('historical-db-media-pending');
      cell.disabled=true;cell.onclick=null;cell.title='Checking existing database media before external discovery';
      const label=cell.querySelector('.find-recap-label');if(label){label.textContent='DB MEDIA…';label.dataset.short='DB'}
      const dot=cell.querySelector('.find-recap-dot');if(dot)dot.textContent='…';
    });
  }

  renderScoresFromMatchesCombined=function(...args){const result=original.render(...args);decoratePendingCards();return result};

  setScoreBrowseDate=async function(value,options={}){
    const date=dateOf(value||todayISO());
    state.generation++;
    const dayStateShell=options?.load===false || options?.dayStateFirstPaint===true;
    if(isHistorical(date) && !dayStateShell)beginBarrier(date);
    return original.setDate(value,options);
  };
  setScoreBrowseDate.__sbbHistoricalHardening=true;
  setScoreBrowseDate.__sbbOriginal=original.setDate;

  ensureScoreDateLoaded=async function(date,options={}){
    date=dateOf(date||scoreBrowseDate);const historical=isHistorical(date);const barrier=historical?(barrierFor(date)||beginBarrier(date)):null;
    const generation=barrier?.generation??state.generation;let result;
    try{
      result=await original.ensure(date,options);
      if(historical){
        const ribbon=await hydrateHistoricalRibbonFromCatalog(date);
        if(ribbon?.ok===false) throw new Error(`historical ribbon DB hydration failed for ${date}`);
        if(generation===state.generation&&scoreBrowseDate===date){original.render(false);decoratePendingCards()}
      }
      return result;
    }finally{if(historical)finishBarrier(barrier)}
  };

  scheduleRecentHistoricalRecapFill=function(date){
    date=dateOf(date);const barrier=barrierFor(date);if(barrier?.pending){state.deferredFill.add(date);return}return original.scheduleFill(date);
  };

  queueHistoricalGameMedia=async function(match,options={}){
    const date=dateOf(scoreEventDate(match)),barrier=barrierFor(date);
    if(barrier?.pending){
      if(scoreBrowseDate===date)setFeedNote(`${date} • checking SQLite before external recap search…`);
      await barrier.promise;const existing=scoreCardPlayableItems(match);if(existing.length)return existing;
      if(barrier.generation!==state.generation&&scoreBrowseDate!==date)return [];
    }
    return original.queue(match,options);
  };

  if(isHistorical(scoreBrowseDate))beginBarrier(scoreBrowseDate);
  window.SBB_HISTORICAL_MEDIA_HARDENING=Object.freeze({
    version:state.version,state,
    report:(date=scoreBrowseDate)=>state.lastReport.get(dateOf(date))||null,
    pending:(date=scoreBrowseDate)=>!!barrierFor(date)?.pending
  });
})();

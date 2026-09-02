/* Sports Big Board v5.2.2 — interaction-priority ribbon + prepared snapshot client.

   Day State / RibbonSnapshot is the only ribbon data authority. The browser does
   not discover media, player aliases, flags, rounds, or event identity here.

   v5.2.2 deliberately separates two hot paths:
     INPUT: wheel/touch -> one scrollLeft write per animation frame, nothing else.
     DATA:  prepared backend RibbonSnapshots -> ScoreDateStore -> normal card factory.

   Normal days (<=96 games) are rendered once and never virtual-recycled while the
   user scrolls. Very large tournament days keep a bounded DOM window and recycle it
   only after the gesture has been idle. No media work is triggered by scrolling.
*/
(() => {
  'use strict';
  if(window.SBB_VIRTUAL_RIBBON?.version==='5.2.2')return;

  const VERSION='5.2.2';
  const CACHE_NAME='sbb-ribbon-snapshots-v522';
  const VIRTUAL_THRESHOLD=96;
  const WINDOW_TARGET=64;
  const OVERSCAN=16;
  const PREFETCH_RADIUS=3;
  const BUNDLE_PAST=14;
  const BUNDLE_FUTURE=2;
  const MAX_CACHE_DAYS=18;
  const QUIET_BEFORE_MEDIA_MS=3200;

  const state={
    installed:false,renders:0,windowRenders:0,fullRenders:0,coalesced:0,
    maxMountedCards:0,lastTotal:0,lastStart:0,lastEnd:0,lastDate:'',lastFilter:'',
    snapshotCacheHits:0,snapshotNetworkHits:0,snapshotPending:0,snapshotErrors:0,
    bundleLoads:0,bundleSnapshots:0,bundleErrors:0,adjacentPrefetches:0,
    mediaWarmRuns:0,mediaWarmSkippedLargeDay:0,mediaWarmDeferrals:0,
    wheelFrames:0,wheelEvents:0,virtualRecycles:0,lastRenderMs:0,maxRenderMs:0,lastReason:''
  };

  const memorySnapshots=new Map();
  const snapshotInflight=new Map();
  let host=null,baseRenderer=null,legacyRenderer=null,sourceRowsFn=null;
  let pipeline=null,virtualRenderer=null,renderRAF=0,pendingReason='',rendering=false;
  let virtualStart=0,virtualEnd=0,virtualTotal=0,currentRows=[];
  let scrollIdleTimer=0,wheelRAF=0,wheelPending=0,lastInteractionAt=0,maxScrollPx=0;
  let mediaWarmTimer=0,mediaWarmIdle=0,pendingWarm=null;
  let installedDateSetter=null,bundlePromise=null;

  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  const today=()=>typeof localDateISO==='function'?localDateISO(0):new Date().toISOString().slice(0,10);
  const currentDate=()=>{
    try{return clean(scoreBrowseDate).slice(0,10)||today();}
    catch(_){return clean(window.scoreBrowseDate).slice(0,10)||today();}
  };
  const currentFilter=()=>{
    try{return upper(scoreRibbonLeagueFilter)||'ALL';}
    catch(_){return upper(window.scoreRibbonLeagueFilter)||'ALL';}
  };
  const slotWidth=()=>window.matchMedia?.('(max-width:760px),(pointer:coarse)')?.matches?162:166;
  const interactionActive=(quiet=700)=>Date.now()-lastInteractionAt<quiet;
  function markInteraction(){lastInteractionAt=Date.now();}

  // Mark interaction only. Never read layout, render, or schedule provider/media work
  // from page scrolling. This listener is intentionally passive and constant-time.
  window.addEventListener('wheel',markInteraction,{passive:true,capture:true});
  window.addEventListener('touchmove',markInteraction,{passive:true,capture:true});

  function injectStyle(){
    if(document.getElementById('sbbVirtualRibbonStyle'))return;
    const style=document.createElement('style');style.id='sbbVirtualRibbonStyle';
    style.textContent=`
      .score-ribbon>.score-cells.sbb-virtual-ribbon{
        overflow-x:auto!important;overflow-y:hidden!important;overscroll-behavior:contain!important;
        scroll-behavior:auto!important;contain:layout paint style;will-change:scroll-position;
      }
      .score-ribbon>.score-cells.sbb-virtual-ribbon>.sbb-vr-spacer{
        height:1px;min-height:1px;align-self:center;pointer-events:none;visibility:hidden
      }
      .score-ribbon>.score-cells.sbb-virtual-ribbon .score-card{contain:layout paint style;content-visibility:visible}
      .score-ribbon>.score-cells.sbb-wheel-active{scroll-snap-type:none!important;scroll-behavior:auto!important}
      html.sbb-interaction-priority *{scroll-behavior:auto!important}
      /* v5.2.0's content-visibility optimization caused first-entry layout work while
         vertically scrolling into Game Center/history. Keep those surfaces normal. */
      .gc-card,.history-audit-table-wrap,.queue-item{content-visibility:visible!important;contain-intrinsic-size:auto!important}
    `;
    document.head.appendChild(style);
  }

  function rowLeague(row){return upper(row?.competitionId||row?.__sbbLeague||row?.league||'SPORTS');}
  function importance(row){try{return Number(scoreRibbonImportance(row)||0);}catch(_){return 0;}}
  function sortedRows(){
    if(typeof sourceRowsFn!=='function')return [];
    let rows=[];try{rows=sourceRowsFn(currentDate())||[];}catch(_){rows=[];}
    const filter=currentFilter();
    return [...rows]
      .filter(row=>filter==='ALL'||rowLeague(row)===filter)
      .sort((a,b)=>importance(b)-importance(a)||new Date(a?.date||a?.scheduledAt||0)-new Date(b?.date||b?.scheduledAt||0));
  }

  function desiredWindow(rows){
    const total=rows.length,slot=slotWidth();
    if(total<=VIRTUAL_THRESHOLD)return {start:0,end:total,total,virtual:false};
    const width=Math.max(slot*4,host?.clientWidth||slot*8);
    const visible=Math.max(4,Math.ceil(width/slot)+1);
    const count=Math.min(total,Math.max(WINDOW_TARGET,visible+OVERSCAN*2));
    const scroll=Math.max(0,Number(host?.scrollLeft)||0);
    const first=Math.max(0,Math.floor(Math.max(0,scroll-slot)/slot)); // ROUNDUP is slot 0
    const start=clamp(first-OVERSCAN,0,Math.max(0,total-count));
    return {start,end:Math.min(total,start+count),total,virtual:true};
  }

  function replaceGlobalSource(fn){
    const previousWindow=window.scoreMatchesForDate;
    let previousBinding=null,binding=false;
    try{previousBinding=scoreMatchesForDate;scoreMatchesForDate=fn;binding=true;}catch(_){}
    try{window.scoreMatchesForDate=fn;}catch(_){}
    return ()=>{
      try{window.scoreMatchesForDate=previousWindow;}catch(_){}
      if(binding)try{scoreMatchesForDate=previousBinding;}catch(_){}
    };
  }

  function addSpacers(win,savedScroll){
    if(!host)return;
    host.classList.toggle('sbb-virtual-ribbon',!!win.virtual);
    host.querySelectorAll(':scope > .sbb-vr-spacer').forEach(n=>n.remove());
    if(win.virtual){
      const slot=slotWidth();
      const left=document.createElement('div');left.className='sbb-vr-spacer sbb-vr-left';
      const right=document.createElement('div');right.className='sbb-vr-spacer sbb-vr-right';
      left.style.flex=`0 0 ${Math.max(0,win.start*slot)}px`;
      right.style.flex=`0 0 ${Math.max(0,(win.total-win.end)*slot)}px`;
      const roundup=[...host.children].find(x=>x?.classList?.contains('roundup-card'))||null;
      if(roundup?.nextSibling)host.insertBefore(left,roundup.nextSibling);
      else if(roundup)host.appendChild(left);else host.prepend(left);
      host.appendChild(right);
    }
    host.scrollLeft=clamp(savedScroll,0,Math.max(0,host.scrollWidth-host.clientWidth));
  }

  function renderNow(animate=false,reason='ribbon'){
    if(rendering||!host||typeof baseRenderer!=='function')return;
    const started=performance.now();
    const rows=sortedRows();
    const win=desiredWindow(rows);
    const savedScroll=Number(host.scrollLeft)||0;
    currentRows=rows;virtualStart=win.start;virtualEnd=win.end;virtualTotal=win.total;
    state.lastTotal=win.total;state.lastStart=win.start;state.lastEnd=win.end;
    state.lastDate=currentDate();state.lastFilter=currentFilter();state.lastReason=reason;

    const subset=rows.slice(win.start,win.end);
    const restore=replaceGlobalSource(()=>subset);
    rendering=true;
    try{
      baseRenderer(animate);
      addSpacers(win,savedScroll);
      // Geometry is sampled once per render, never once per wheel event. Reading
      // scrollWidth/clientWidth in the wheel handler can force synchronous layout.
      maxScrollPx=Math.max(0,host.scrollWidth-host.clientWidth);
      state.renders++;if(win.virtual)state.windowRenders++;else state.fullRenders++;
      state.maxMountedCards=Math.max(state.maxMountedCards,win.virtual?subset.length+1:rows.length+1);
    }catch(err){
      console.warn('[SBB v5.2.2] ribbon render fallback',err);
      try{legacyRenderer?.(animate);}catch(_){}
    }finally{
      restore();rendering=false;
      const ms=Math.round((performance.now()-started)*10)/10;
      state.lastRenderMs=ms;state.maxRenderMs=Math.max(state.maxRenderMs,ms);
    }
  }

  function scheduleRender(reason='scheduled',animate=false,{force=false}={}){
    pendingReason=reason||pendingReason||'scheduled';
    if(renderRAF&&!force){state.coalesced++;return;}
    if(renderRAF){cancelAnimationFrame(renderRAF);renderRAF=0;}
    const run=()=>{renderRAF=0;const why=pendingReason;pendingReason='';renderNow(animate,why);};
    // Interaction always wins. Date/snapshot first paint is allowed; every other
    // cosmetic/enrichment render waits until the gesture is over.
    const essential=/date|first|day-state|filter|snapshot|generation/i.test(reason);
    if(interactionActive(500)&&!essential){state.coalesced++;setTimeout(()=>scheduleRender(reason,animate,{force:true}),550);return;}
    renderRAF=requestAnimationFrame(run);
  }

  function normalizeWheelDelta(event){
    let delta=Math.abs(event.deltaX)>Math.abs(event.deltaY)?event.deltaX:event.deltaY;
    if(event.deltaMode===1)delta*=30;
    else if(event.deltaMode===2)delta*=Math.max(300,host?.clientWidth||600);
    return delta;
  }
  function onWheel(event){
    if(!host||maxScrollPx<=2)return;
    const delta=normalizeWheelDelta(event);if(!Number.isFinite(delta)||Math.abs(delta)<0.01)return;
    // Normal mouse wheels report vertical delta. Within the horizontal score ribbon
    // that gesture belongs to the ribbon. The handler performs no layout reads after
    // this point and no application work; it only batches one scroll write/frame.
    event.preventDefault();event.stopPropagation();markInteraction();state.wheelEvents++;
    host.classList.add('sbb-wheel-active');
    wheelPending+=delta*2.65;
    if(!wheelRAF)wheelRAF=requestAnimationFrame(()=>{
      wheelRAF=0;const move=clamp(wheelPending,-1800,1800);wheelPending=0;
      host.scrollLeft=clamp(host.scrollLeft+move,0,maxScrollPx);
      state.wheelFrames++;
      clearTimeout(scrollIdleTimer);
      scrollIdleTimer=setTimeout(()=>{
        host?.classList.remove('sbb-wheel-active');
        if(rendering||virtualTotal<=VIRTUAL_THRESHOLD)return;
        const next=desiredWindow(currentRows);
        if(next.start!==virtualStart||next.end!==virtualEnd){state.virtualRecycles++;scheduleRender('virtual-scroll-idle',false,{force:true});}
      },480);
    });
  }

  function patchMediaWarmScheduler(){
    let original=null;
    try{original=window.scheduleScoreMediaWarmReconcile||scheduleScoreMediaWarmReconcile;}catch(_){original=window.scheduleScoreMediaWarmReconcile;}
    if(typeof original!=='function'||original.__sbbV522IdleOnly)return;

    function cancelScheduled(){
      if(mediaWarmTimer){clearTimeout(mediaWarmTimer);mediaWarmTimer=0;}
      if(mediaWarmIdle&&typeof cancelIdleCallback==='function'){try{cancelIdleCallback(mediaWarmIdle);}catch(_){}mediaWarmIdle=0;}
    }
    function arm(){
      cancelScheduled();
      mediaWarmTimer=setTimeout(()=>{
        mediaWarmTimer=0;
        if(!pendingWarm)return;
        if(interactionActive(QUIET_BEFORE_MEDIA_MS)){state.mediaWarmDeferrals++;arm();return;}
        // Large score days already have verified backend media. Priming every visible
        // card is not worth sacrificing interaction latency; selected playback warms
        // on demand instead.
        if(currentRows.length>32){state.mediaWarmSkippedLargeDay++;pendingWarm=null;return;}
        const [delay,args]=pendingWarm;pendingWarm=null;
        const run=()=>{mediaWarmIdle=0;if(interactionActive(1000)){pendingWarm=[delay,args];state.mediaWarmDeferrals++;arm();return;}try{original(Math.max(0,Number(delay)||0),...args);state.mediaWarmRuns++;}catch(_){}};
        if(typeof requestIdleCallback==='function')mediaWarmIdle=requestIdleCallback(run,{timeout:9000});
        else setTimeout(run,0);
      },QUIET_BEFORE_MEDIA_MS);
    }
    const wrapped=function(delay=0,...args){pendingWarm=[delay,args];arm();};
    wrapped.__sbbV522IdleOnly=true;wrapped.__sbbOriginal=original;
    try{window.scheduleScoreMediaWarmReconcile=wrapped;}catch(_){}
    try{scheduleScoreMediaWarmReconcile=wrapped;}catch(_){}
    // Do not attach any media scheduler to wheel/touch. The timer checks the
    // interaction timestamp before it can run, so user input needs no extra work.
  }

  function cacheKey(date){
    const base=location.pathname.replace(/[^/]*$/,'');
    return new Request(`${location.origin}${base}__sbb_ribbon_snapshot__?date=${encodeURIComponent(date)}`);
  }
  async function cacheOpen(){try{return window.caches?await window.caches.open(CACHE_NAME):null;}catch(_){return null;}}
  function dayDistance(date){
    try{return Math.round((new Date(`${date}T12:00:00`)-new Date(`${today()}T12:00:00`))/86400000);}catch(_){return 99;}
  }
  function snapshotFreshEnough(payload,date){
    if(!payload||payload?.pending||clean(payload?.date).slice(0,10)!==date)return false;
    const distance=dayDistance(date),cachedAt=Number(payload.__sbbBrowserCachedAt||0),generatedMs=Number(payload.generatedAt||0)*1000;
    const stamp=Math.max(cachedAt,generatedMs);if(!stamp)return distance<=-2;
    const age=Date.now()-stamp;
    if(distance===0)return age<=15000;
    if(distance===-1)return age<=60000;
    if(distance>0)return age<=30000;
    return true; // completed historical snapshots are immutable enough for instant paint
  }
  function peekSnapshot(date){
    date=clean(date).slice(0,10);const payload=memorySnapshots.get(date);
    return payload&&snapshotFreshEnough(payload,date)?payload:null;
  }
  async function readCachedSnapshot(date,{apply=true}={}){
    date=clean(date).slice(0,10);if(!date)return null;
    const resident=peekSnapshot(date);
    if(resident){state.snapshotCacheHits++;if(apply)try{window.SBB_DAY_STATE?.apply?.(resident);}catch(_){}return resident;}
    const cache=await cacheOpen();if(!cache)return null;
    try{
      const response=await cache.match(cacheKey(date));if(!response)return null;
      const payload=await response.json();if(!snapshotFreshEnough(payload,date)){try{await cache.delete(cacheKey(date));}catch(_){}return null;}
      memorySnapshots.set(date,payload);state.snapshotCacheHits++;
      if(apply)try{window.SBB_DAY_STATE?.apply?.(payload);}catch(_){}
      return payload;
    }catch(_){return null;}
  }
  async function writeCachedSnapshot(payload){
    const date=clean(payload?.date).slice(0,10);if(!date||payload?.pending)return;
    const stamped={...payload,__sbbBrowserCachedAt:Date.now()};memorySnapshots.set(date,stamped);
    // Current/yesterday/future rows stay memory-only so a new browser session never
    // starts from stale live state. Completed older history may persist locally.
    if(dayDistance(date)>-2)return;
    const cache=await cacheOpen();if(!cache)return;
    try{
      await cache.put(cacheKey(date),new Response(JSON.stringify(stamped),{headers:{'Content-Type':'application/json'}}));
      const keys=await cache.keys();
      if(keys.length>MAX_CACHE_DAYS){
        const t=today(),score=req=>{try{return Math.abs(new Date(new URL(req.url).searchParams.get('date')||'')-new Date(t));}catch(_){return 0;}};
        keys.sort((a,b)=>score(b)-score(a));await Promise.all(keys.slice(0,keys.length-MAX_CACHE_DAYS).map(k=>cache.delete(k)));
      }
    }catch(_){}
  }

  const api=path=>window.SBB_API?.url?window.SBB_API.url(path):path;
  async function fetchSnapshot(date,{apply=true,timeoutMs=1100}={}){
    date=clean(date).slice(0,10);if(!date)return null;
    if(snapshotInflight.has(date))return snapshotInflight.get(date);
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);
    const promise=fetch(api(`/api/ribbon-snapshot?date=${encodeURIComponent(date)}`),{cache:'no-store',signal:controller.signal})
      .then(async r=>{
        if(r.status===202){state.snapshotPending++;return null;}if(!r.ok)throw new Error(`HTTP ${r.status}`);
        const payload=await r.json();if(payload?.pending||payload?.ok===false)return null;
        state.snapshotNetworkHits++;await writeCachedSnapshot(payload);if(apply)try{window.SBB_DAY_STATE?.apply?.(payload);}catch(_){}return payload;
      })
      .catch(()=>{state.snapshotErrors++;return null;})
      .finally(()=>{clearTimeout(timer);snapshotInflight.delete(date);});
    snapshotInflight.set(date,promise);return promise;
  }

  function shiftDate(date,delta){const d=new Date(`${date}T12:00:00`);if(!Number.isFinite(d.getTime()))return '';d.setDate(d.getDate()+delta);return d.toISOString().slice(0,10);}
  async function fetchBundle(center=today(),{past=BUNDLE_PAST,future=BUNDLE_FUTURE}={}){
    if(bundlePromise)return bundlePromise;
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),3000);
    bundlePromise=fetch(api(`/api/ribbon-snapshot/bundle?center=${encodeURIComponent(center)}&past=${past}&future=${future}`),{cache:'no-store',signal:controller.signal})
      .then(async r=>{if(!r.ok)throw new Error(`HTTP ${r.status}`);const payload=await r.json();const snaps=payload?.snapshots||{};for(const [date,snap] of Object.entries(snaps)){if(snap&&!snap.pending)await writeCachedSnapshot({...snap,date:clean(snap.date||date).slice(0,10)});}state.bundleLoads++;state.bundleSnapshots+=Object.keys(snaps).length;return payload;})
      .catch(()=>{state.bundleErrors++;return null;})
      .finally(()=>{clearTimeout(timer);bundlePromise=null;});
    return bundlePromise;
  }
  async function hydrateDate(date,{network=true}={}){
    const resident=await readCachedSnapshot(date,{apply:true});if(network)void fetchSnapshot(date,{apply:true});return resident;
  }
  function prefetchAround(date){
    for(let i=1;i<=PREFETCH_RADIUS;i++)for(const d of [shiftDate(date,-i),shiftDate(date,i)].filter(Boolean)){
      if(peekSnapshot(d))continue;state.adjacentPrefetches++;
      setTimeout(()=>void readCachedSnapshot(d,{apply:false}).then(hit=>hit||fetchSnapshot(d,{apply:false,timeoutMs:1400})),i*120);
    }
  }

  function patchDateSetter(){
    const original=window.setScoreBrowseDate;
    if(typeof original!=='function'||original.__sbbVirtualRibbonV522)return false;
    installedDateSetter=original;
    const wrapped=function(value,options={}){
      const date=clean(value||today()).slice(0,10);
      const resident=peekSnapshot(date);
      if(resident)try{window.SBB_DAY_STATE?.apply?.(resident);}catch(_){}
      else void readCachedSnapshot(date,{apply:true});
      const result=original(value,options);
      void fetchSnapshot(date,{apply:true});prefetchAround(date);
      return result;
    };
    wrapped.__sbbVirtualRibbonV522=true;wrapped.__sbbOriginal=original;
    window.setScoreBrowseDate=wrapped;try{setScoreBrowseDate=wrapped;}catch(_){}return true;
  }

  function sanitizeHost(){
    let current=document.getElementById('scoreCells');if(!current)return null;
    if(current.dataset.sbbV522Clean==='1'){current.dataset.warmSchedulerWired='1';return current;}
    // app.js' legacy renderer attached anonymous scroll -> media-warm work directly to
    // this node. Replacing only this empty rendering surface removes that listener
    // without touching the score data/store/navigation architecture.
    const clone=current.cloneNode(false);clone.dataset.sbbV522Clean='1';clone.dataset.warmSchedulerWired='1';
    current.replaceWith(clone);return clone;
  }

  function installPipeline(){
    try{window.SBB_RIBBON_FAST_SCROLL?.destroy?.();}catch(_){}
    const currentRenderer=window.renderScoresFromMatchesCombined;
    if(typeof currentRenderer!=='function')return false;
    if(!state.installed){
      host=sanitizeHost();if(!host)return false;
      legacyRenderer=currentRenderer;baseRenderer=currentRenderer.__sbbOriginal||currentRenderer;
      try{sourceRowsFn=window.scoreMatchesForDate||scoreMatchesForDate;}catch(_){sourceRowsFn=window.scoreMatchesForDate;}
      if(typeof baseRenderer!=='function'||typeof sourceRowsFn!=='function')return false;
      const wrapped=function(animate=false){scheduleRender(clean(window.__SBB_RENDER_REASON)||'direct-render',animate,{force:true});};
      wrapped.__sbbVirtualRibbonV522=true;wrapped.__sbbOriginal=baseRenderer;virtualRenderer=wrapped;
      window.renderScoresFromMatchesCombined=wrapped;try{renderScoresFromMatchesCombined=wrapped;}catch(_){}
      const old=window.SBB_RENDER_PIPELINE;
      if(old){pipeline=Object.freeze({...old,version:'5.2.2-interaction-priority',request(reason='request',options={}){scheduleRender(reason,!!options?.animate);return Promise.resolve(true);},commitGeneration(generation,options={}){scheduleRender(options?.reason||'generation-commit',!!options?.animate,{force:true});return Promise.resolve(true);},diagnostics(){return {virtual:true,...state,legacy:(old.diagnostics?.()||old.snapshot?.()||null)};},snapshot(){return {virtual:true,...state};}});window.SBB_RENDER_PIPELINE=pipeline;}
      host.addEventListener('wheel',onWheel,{passive:false,capture:true});host.classList.add('sbb-virtual-ribbon');
      patchMediaWarmScheduler();patchDateSetter();state.installed=true;
      scheduleRender('v522-install',false,{force:true});
      return true;
    }
    // Reassert ownership if an older boot module replaced the renderer later.
    host=document.getElementById('scoreCells')||host;if(host)host.dataset.warmSchedulerWired='1';
    if(virtualRenderer&&window.renderScoresFromMatchesCombined!==virtualRenderer){window.renderScoresFromMatchesCombined=virtualRenderer;try{renderScoresFromMatchesCombined=virtualRenderer;}catch(_){}}
    patchMediaWarmScheduler();patchDateSetter();return true;
  }

  function boot(){
    injectStyle();installPipeline();
    const timer=setInterval(()=>installPipeline(),150);setTimeout(()=>clearInterval(timer),3500);
    const d=currentDate();void hydrateDate(d,{network:true});
    // One backend lookup fills the recent date bank before the user starts paging.
    setTimeout(()=>void fetchBundle(today()).then(()=>prefetchAround(d)),120);
    document.title=document.title.replace(/v\d+\.\d+\.\d+/i,'v5.2.2');
  }

  window.SBB_VIRTUAL_RIBBON=Object.freeze({
    version:VERSION,authority:'BACKEND_RIBBON_SNAPSHOT',
    hydrateDate,fetchSnapshot,readCachedSnapshot,fetchBundle,prefetchAround,peekSnapshot,
    render:reason=>scheduleRender(reason||'api',false,{force:true}),interactionActive,
    snapshot:()=>({...state,memoryDates:[...memorySnapshots.keys()],mounted:host?.querySelectorAll?.('.score-card')?.length||0})
  });
  boot();
})();

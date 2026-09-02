/* Sports Big Board v5.2.1 — idle-recycled virtual ribbon + current-safe snapshot client.

   Large sports days are data, not DOM. Day State / RibbonSnapshot remains the
   authority; this layer keeps only the visible score-card window mounted and lets
   the established score-card factory build those cards. It never computes team,
   player, media, flag, or provider identity.

   The same module owns a tiny read-through Cache API for canonical RibbonSnapshot
   payloads. Adjacent dates are preloaded into ScoreDateStore so previous/next day
   navigation normally paints from memory before the network request begins.
*/
(() => {
  'use strict';
  if(window.SBB_VIRTUAL_RIBBON?.version==='5.2.1')return;

  const VERSION='5.2.1';
  const CACHE_NAME='sbb-ribbon-snapshots-v521';
  const WINDOW_MIN=64;
  const OVERSCAN=18;
  const PREFETCH_RADIUS=2;
  const MAX_CACHE_DAYS=9;
  const state={
    installed:false,renders:0,windowRenders:0,smallRenders:0,coalesced:0,
    maxMountedCards:0,lastTotal:0,lastStart:0,lastEnd:0,lastDate:'',lastFilter:'',
    snapshotCacheHits:0,snapshotNetworkHits:0,snapshotPending:0,snapshotErrors:0,
    adjacentPrefetches:0,mediaWarmDeferrals:0,interactionDeferrals:0,
    lastRenderMs:0,maxRenderMs:0,lastReason:'',
  };
  const memorySnapshots=new Map();
  const snapshotInflight=new Map();
  let host=null,baseRenderer=null,legacyRenderer=null,sourceRowsFn=null;
  let pipeline=null,virtualRenderer=null,renderRAF=0,pendingReason='',rendering=false;
  let virtualStart=0,virtualEnd=0,virtualTotal=0,currentRows=[];
  let interactionUntil=0,interactionTimer=0,mediaWarmTimer=0,scrollIdleTimer=0;
  let installedDateSetter=null;

  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  const today=()=>typeof localDateISO==='function'?localDateISO(0):new Date().toISOString().slice(0,10);
  const currentDate=()=>{
    try{return clean(scoreBrowseDate).slice(0,10)||today();}catch(_){return clean(window.scoreBrowseDate).slice(0,10)||today();}
  };
  const currentFilter=()=>{
    try{return upper(scoreRibbonLeagueFilter)||'ALL';}catch(_){return upper(window.scoreRibbonLeagueFilter)||'ALL';}
  };
  const slotWidth=()=>window.matchMedia?.('(max-width:760px),(pointer:coarse)')?.matches?162:166;
  const interactionActive=()=>performance.now()<interactionUntil;
  function noteInteraction(ms=240){
    interactionUntil=Math.max(interactionUntil,performance.now()+ms);
    document.documentElement?.classList.add('sbb-user-scrolling');
    clearTimeout(interactionTimer);
    interactionTimer=setTimeout(()=>document.documentElement?.classList.remove('sbb-user-scrolling'),Math.max(80,ms+40));
  }
  window.addEventListener('scroll',()=>noteInteraction(220),{passive:true});

  function injectStyle(){
    if(document.getElementById('sbbVirtualRibbonStyle'))return;
    const style=document.createElement('style');style.id='sbbVirtualRibbonStyle';
    style.textContent=`
      .score-ribbon>.score-cells.sbb-virtual-ribbon{overflow-x:auto!important;overflow-y:hidden!important;contain:layout paint style}
      .score-ribbon>.score-cells.sbb-virtual-ribbon>.sbb-vr-spacer{height:1px;min-height:1px;align-self:center;pointer-events:none;visibility:hidden}
      .score-ribbon>.score-cells.sbb-virtual-ribbon .score-card{contain:layout paint style;content-visibility:visible}
      html.sbb-user-scrolling .score-card,html.sbb-user-scrolling .gc-card,html.sbb-user-scrolling .info-drawer{transition:none!important;animation:none!important}
      .gc-card,.history-audit-table-wrap,.queue-item{content-visibility:auto;contain-intrinsic-size:auto 110px}
    `;
    document.head.appendChild(style);
  }

  function stableKey(match){
    try{
      if(typeof scoreRibbonStableGameKey==='function'){
        const k=clean(scoreRibbonStableGameKey(match));if(k)return k;
      }
    }catch(_){}
    const lg=upper(match?.competitionId||match?.__sbbLeague||match?.league||'SPORTS');
    const id=[match?.scoreEventId,match?.espnEventId,match?.matchId,match?.gamePk,match?.eventId,match?.id].find(x=>clean(x));
    if(id!=null&&clean(id))return `${lg}:ID:${clean(id)}`;
    const tn=x=>upper(x?.displayName||x?.name||x?.shortName||x?.abbreviation||x||'').replace(/[^A-Z0-9]+/g,'');
    return `${lg}:${currentDate()}:${tn(match?.awayTeam||match?.away)}:${tn(match?.homeTeam||match?.home)}`;
  }

  function importance(row){
    try{return Number(scoreRibbonImportance(row)||0);}catch(_){return 0;}
  }
  function rowLeague(row){return upper(row?.competitionId||row?.__sbbLeague||row?.league||'SPORTS');}
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
    if(total<=WINDOW_MIN)return {start:0,end:total,total,virtual:false};
    const width=Math.max(slot*4,host?.clientWidth||slot*8);
    const visible=Math.max(4,Math.ceil(width/slot)+1);
    const count=Math.min(total,Math.max(WINDOW_MIN,visible+OVERSCAN*2));
    const scroll=Math.max(0,Number(host?.scrollLeft)||0);
    // One permanent ROUNDUP card precedes the virtual game slots.
    const first=Math.max(0,Math.floor(Math.max(0,scroll-slot)/slot));
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
    if(!win.virtual){
      host.scrollLeft=clamp(savedScroll,0,Math.max(0,host.scrollWidth-host.clientWidth));
      return;
    }
    const slot=slotWidth();
    const left=document.createElement('div');left.className='sbb-vr-spacer sbb-vr-left';
    const right=document.createElement('div');right.className='sbb-vr-spacer sbb-vr-right';
    left.style.flex=`0 0 ${Math.max(0,win.start*slot)}px`;
    right.style.flex=`0 0 ${Math.max(0,(win.total-win.end)*slot)}px`;
    const roundup=[...host.children].find(x=>x?.classList?.contains('roundup-card'))||null;
    if(roundup?.nextSibling)host.insertBefore(left,roundup.nextSibling);
    else if(roundup)host.appendChild(left);
    else host.prepend(left);
    host.appendChild(right);
    host.scrollLeft=clamp(savedScroll,0,Math.max(0,host.scrollWidth-host.clientWidth));
  }

  function renderNow(animate=false,reason='virtual-ribbon'){
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
      // Skip the legacy v4.7 performance wrapper here. On a 100+ event tennis day
      // its global DOM census + complete card-bank validation defeats virtualization.
      baseRenderer(animate);
      addSpacers(win,savedScroll);
      state.renders++;if(win.virtual)state.windowRenders++;else state.smallRenders++;
      const mounted=host.querySelectorAll('.score-card').length;
      state.maxMountedCards=Math.max(state.maxMountedCards,mounted);
    }catch(err){
      console.warn('[SBB v5.2.0] virtual ribbon render fallback',err);
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
    const essential=/date|first|day-state|filter|snapshot/i.test(reason);
    if(interactionActive()&&!essential){
      state.interactionDeferrals++;
      setTimeout(()=>scheduleRender(reason,animate,{force:true}),220);
      return;
    }
    renderRAF=requestAnimationFrame(run);
  }

  function onRibbonScroll(){
    // Browser/compositor owns the gesture. Never rebuild cards while wheel/touch
    // input is active. A generously oversized mounted window lets the user move
    // freely; recycling happens only after scrolling has been idle for 140 ms.
    noteInteraction(260);
    if(rendering||virtualTotal<=WINDOW_MIN)return;
    clearTimeout(scrollIdleTimer);
    scrollIdleTimer=setTimeout(()=>{
      scrollIdleTimer=0;
      const next=desiredWindow(currentRows);
      if(next.start===virtualStart&&next.end===virtualEnd)return;
      scheduleRender('virtual-scroll-idle',false,{force:true});
    },140);
  }

  function patchMediaWarmScheduler(){
    let original=null;
    try{original=window.scheduleScoreMediaWarmReconcile||scheduleScoreMediaWarmReconcile;}catch(_){original=window.scheduleScoreMediaWarmReconcile;}
    if(typeof original!=='function'||original.__sbbV520Deferred)return;
    const wrapped=function(delay=0,...args){
      clearTimeout(mediaWarmTimer);
      const busy=interactionActive();
      const wait=busy?1100:Math.max(250,Number(delay)||0);
      if(busy)state.mediaWarmDeferrals++;
      mediaWarmTimer=setTimeout(()=>{
        mediaWarmTimer=0;
        const run=()=>{if(interactionActive()){state.mediaWarmDeferrals++;return wrapped(500,...args)}try{original(Math.max(0,Number(delay)||0),...args);}catch(_){}};
        if(typeof requestIdleCallback==='function')requestIdleCallback(run,{timeout:1800});else setTimeout(run,0);
      },wait);
    };
    wrapped.__sbbV520Deferred=true;wrapped.__sbbOriginal=original;
    try{window.scheduleScoreMediaWarmReconcile=wrapped;}catch(_){}
    try{scheduleScoreMediaWarmReconcile=wrapped;}catch(_){}
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
    const distance=dayDistance(date);
    const cachedAt=Number(payload.__sbbBrowserCachedAt||0);
    const generatedMs=Number(payload.generatedAt||0)*1000;
    const stamp=Math.max(cachedAt,generatedMs);
    if(!stamp)return distance<=-2;
    const age=Date.now()-stamp;
    if(distance===0)return age<=20000;
    if(distance===-1)return age<=90000;
    if(distance>0)return age<=30000;
    return true;
  }
  async function readCachedSnapshot(date,{apply=true}={}){
    date=clean(date).slice(0,10);if(!date)return null;
    if(memorySnapshots.has(date)){
      const payload=memorySnapshots.get(date);
      if(snapshotFreshEnough(payload,date)){
        state.snapshotCacheHits++;if(apply)try{window.SBB_DAY_STATE?.apply?.(payload);}catch(_){}return payload;
      }
      memorySnapshots.delete(date);
    }
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
    const stamped={...payload,__sbbBrowserCachedAt:Date.now()};
    memorySnapshots.set(date,stamped);
    if(dayDistance(date)>-2)return;
    const cache=await cacheOpen();if(!cache)return;
    try{
      const body=JSON.stringify(stamped);
      await cache.put(cacheKey(date),new Response(body,{headers:{'Content-Type':'application/json'}}));
      // Keep the cache intentionally tiny. Delete dates farthest from today.
      const keys=await cache.keys();
      if(keys.length>MAX_CACHE_DAYS){
        const t=today();
        const score=req=>{try{const d=new URL(req.url).searchParams.get('date')||'';return Math.abs(new Date(d)-new Date(t));}catch(_){return 0;}};
        keys.sort((a,b)=>score(b)-score(a));
        await Promise.all(keys.slice(0,keys.length-MAX_CACHE_DAYS).map(k=>cache.delete(k)));
      }
    }catch(_){}
  }
  const api=path=>window.SBB_API?.url?window.SBB_API.url(path):path;
  async function fetchSnapshot(date,{apply=true,timeoutMs=1400}={}){
    date=clean(date).slice(0,10);if(!date)return null;
    if(snapshotInflight.has(date))return snapshotInflight.get(date);
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),timeoutMs);
    const promise=fetch(api(`/api/ribbon-snapshot?date=${encodeURIComponent(date)}`),{cache:'no-store',signal:controller.signal})
      .then(async r=>{
        if(r.status===202){state.snapshotPending++;return null;}
        if(!r.ok)throw new Error(`HTTP ${r.status}`);
        const payload=await r.json();if(payload?.pending||payload?.ok===false)return null;
        state.snapshotNetworkHits++;await writeCachedSnapshot(payload);
        if(apply)try{window.SBB_DAY_STATE?.apply?.(payload);}catch(_){}
        return payload;
      })
      .catch(()=>{state.snapshotErrors++;return null;})
      .finally(()=>{clearTimeout(timer);snapshotInflight.delete(date);});
    snapshotInflight.set(date,promise);return promise;
  }
  async function hydrateDate(date,{network=true}={}){
    const resident=await readCachedSnapshot(date,{apply:true});
    if(network)void fetchSnapshot(date,{apply:true});
    return resident;
  }
  function shiftDate(date,delta){
    const d=new Date(`${date}T12:00:00`);if(!Number.isFinite(d.getTime()))return '';
    d.setDate(d.getDate()+delta);return d.toISOString().slice(0,10);
  }
  function prefetchAround(date){
    const tasks=[];
    for(let i=1;i<=PREFETCH_RADIUS;i++)tasks.push(shiftDate(date,-i),shiftDate(date,i));
    let delay=100;
    for(const d of tasks.filter(Boolean)){
      setTimeout(()=>{
        state.adjacentPrefetches++;
        void readCachedSnapshot(d,{apply:false}).finally(()=>fetchSnapshot(d,{apply:false,timeoutMs:1800}));
      },delay);
      delay+=120;
    }
  }

  function patchDateSetter(){
    const original=window.setScoreBrowseDate;
    if(typeof original!=='function'||original.__sbbVirtualRibbonV520)return false;
    installedDateSetter=original;
    const wrapped=function(value,options={}){
      const date=clean(value||today()).slice(0,10);
      // Adjacent days are normally already in memory. Apply that canonical read
      // model synchronously before the date shell starts so back/forward feels local.
      const resident=memorySnapshots.get(date);
      if(resident&&snapshotFreshEnough(resident,date))try{window.SBB_DAY_STATE?.apply?.(resident);}catch(_){}
      else void readCachedSnapshot(date,{apply:true});
      const result=original(value,options);
      void fetchSnapshot(date,{apply:true});
      prefetchAround(date);
      return result;
    };
    wrapped.__sbbVirtualRibbonV520=true;wrapped.__sbbOriginal=original;
    window.setScoreBrowseDate=wrapped;
    try{setScoreBrowseDate=wrapped;}catch(_){}
    return true;
  }

  function installPipeline(){
    try{window.SBB_RIBBON_FAST_SCROLL?.destroy?.();}catch(_){}
    host=document.getElementById('scoreCells');
    const current=window.renderScoresFromMatchesCombined;
    if(!host||typeof current!=='function')return false;
    if(state.installed&&virtualRenderer){
      if(current!==virtualRenderer){
        window.renderScoresFromMatchesCombined=virtualRenderer;
        try{renderScoresFromMatchesCombined=virtualRenderer;}catch(_){}
      }
      patchDateSetter();patchMediaWarmScheduler();
      return true;
    }
    legacyRenderer=current;
    baseRenderer=current.__sbbOriginal||current;
    try{sourceRowsFn=window.scoreMatchesForDate||scoreMatchesForDate;}catch(_){sourceRowsFn=window.scoreMatchesForDate;}
    if(typeof baseRenderer!=='function'||typeof sourceRowsFn!=='function')return false;

    const wrapped=function(animate=false){scheduleRender(clean(window.__SBB_RENDER_REASON)||'direct-render',animate,{force:true});};
    wrapped.__sbbVirtualRibbonV520=true;wrapped.__sbbOriginal=baseRenderer;
    virtualRenderer=wrapped;
    window.renderScoresFromMatchesCombined=wrapped;
    try{renderScoresFromMatchesCombined=wrapped;}catch(_){}

    const old=window.SBB_RENDER_PIPELINE;
    if(old){
      pipeline=Object.freeze({
        ...old,version:'5.2.1-virtual',
        request(reason='request',options={}){scheduleRender(reason,!!options?.animate);return Promise.resolve(true);},
        commitGeneration(generation,options={}){scheduleRender(options?.reason||'generation-commit',!!options?.animate,{force:true});return Promise.resolve(true);},
        diagnostics(){return {virtual:true,...state,legacy:(old.diagnostics?.()||old.snapshot?.()||null)};},
        snapshot(){return {virtual:true,...state};},
      });
      window.SBB_RENDER_PIPELINE=pipeline;
    }
    host.addEventListener('scroll',onRibbonScroll,{passive:true});
    host.classList.add('sbb-virtual-ribbon');
    patchMediaWarmScheduler();
    patchDateSetter();
    state.installed=true;
    return true;
  }

  function boot(){
    injectStyle();
    let installTimer=0;
    installPipeline();
    // Older architecture modules also install during boot. Reassert virtual ownership
    // briefly so load ordering cannot resurrect a full-bank renderer/date wrapper.
    installTimer=setInterval(()=>{installPipeline();patchDateSetter();},100);
    setTimeout(()=>{if(installTimer)clearInterval(installTimer);},5000);

    // Begin from durable local state immediately, then replace with the server's
    // already-prepared RibbonSnapshot. Adjacent dates warm after first interaction.
    const d=currentDate();
    void hydrateDate(d,{network:true});
    setTimeout(()=>prefetchAround(d),250);
    setTimeout(()=>patchMediaWarmScheduler(),800);
    setTimeout(()=>patchDateSetter(),800);
    document.title=document.title.replace(/v\d+\.\d+\.\d+/i,'v5.2.1');
  }

  window.SBB_VIRTUAL_RIBBON=Object.freeze({
    version:VERSION,authority:'BACKEND_RIBBON_SNAPSHOT',
    hydrateDate,fetchSnapshot,readCachedSnapshot,prefetchAround,
    render:reason=>scheduleRender(reason||'api',false,{force:true}),
    interactionActive,
    snapshot:()=>({...state,memoryDates:[...memorySnapshots.keys()],mounted:host?.querySelectorAll?.('.score-card')?.length||0}),
  });
  boot();
})();

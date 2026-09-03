/* Sports Big Board v5.2.11 — Scroll & Motion Smoothness.

   Shared frame-budget coordinator for vertical page scrolling, the score ribbon,
   and the Sports Ticker. It relies on native/compositor scrolling rather than
   artificial intermediate points, browser-level score-card virtualization via
   content-visibility, paint/layout containment, offscreen diagnostic suspension,
   and a measurable motion certification surface. */
(() => {
  'use strict';
  if(window.SBB_SCROLL_MOTION?.version==='5.3.14')return;
  const VERSION='5.3.14';
  const $=id=>document.getElementById(id);
  const state={scrolling:false,lastInputAt:0,scrollEvents:0,scoreScrollEvents:0,deferred:0,flushed:0,offscreenSuspended:0,lastReport:null,refreshHz:null};
  let idleTimer=0,flushTimer=0,io=null,certRunning=false;
  const deferredQueue=[];

  function injectStyle(){
    if($('sbbScrollMotionStyle'))return;
    const style=document.createElement('style');style.id='sbbScrollMotionStyle';style.textContent=`
      /* v5.2.11: native scroll surfaces own their motion. */
      html{scroll-behavior:auto!important}
      body{scroll-behavior:auto!important}
      #keyInfoTrack,.score-ribbon,.score-ribbon>.score-cells{contain:layout paint style!important;isolation:isolate}
      #keyInfoTrack{transform:translateZ(0)}
      .score-ribbon>.score-cells{
        -webkit-overflow-scrolling:touch!important;
        overscroll-behavior-inline:contain!important;
        scroll-behavior:auto!important;
        scroll-snap-type:none!important;
        touch-action:pan-x pan-y!important;
        transform:translateZ(0);
      }
      /* Browser-level virtualization: oversized tournament ribbons retain every
         DOM card and exact scroll geometry, but offscreen cards may skip rendering. */
      .score-ribbon>.score-cells>.score-card,
      .score-ribbon>.score-cells>.score-button,
      .score-ribbon>.score-cells>.score-cell{
        contain:layout paint style!important;
        content-visibility:auto;
        contain-intrinsic-size:166px 76px;
      }
      .sbb-sports-ticker-conveyor .key-info-item{contain:layout paint style!important}

      /* Noncritical operator/diagnostic surfaces are isolated from the main board.
         Offscreen ones become true paint/layout skip regions while preserving size. */
      .sport-feed-diagnostics,#coveragePipeline,.mobile-live-bar,.proof-card,
      .milestone-console,.history-audit-shell,.settings-pane{
        contain:layout paint style!important;
        content-visibility:auto;
        contain-intrinsic-size:auto 120px;
      }
      .sbb-paint-suspended{content-visibility:hidden!important;contain-intrinsic-size:auto var(--sbb-suspended-height,120px)!important}

      /* During an active gesture, nonessential visual flourishes cannot consume
         frame budget. Layout remains unchanged and content remains readable. */
      body.sbb-scroll-active .sport-feed-diagnostics *,
      body.sbb-scroll-active #coveragePipeline *,
      body.sbb-scroll-active .proof-card *,
      body.sbb-scroll-active .milestone-console *{
        animation-play-state:paused!important;
        transition:none!important;
      }
      body.sbb-scroll-active .score-card,
      body.sbb-scroll-active .key-info-item{box-shadow:none!important;filter:none!important}

      .motion-cert-card{display:grid!important;gap:10px!important}
      .motion-cert-actions{display:flex;gap:7px;flex-wrap:wrap}
      .motion-cert-actions .settings-save-btn{flex:1 1 150px}
      .motion-cert-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px}
      .motion-cert-kpi{padding:8px;border:1px solid #22313c;border-radius:8px;background:#091118;display:grid;gap:2px}
      .motion-cert-kpi span{font-size:8px;color:#718493;letter-spacing:.06em}.motion-cert-kpi b{font-size:12px;font-variant-numeric:tabular-nums}
      .motion-cert-report{white-space:pre-wrap;max-height:210px;overflow:auto;padding:8px;border:1px solid #202d37;border-radius:7px;background:#080d12;color:#aebbc5;font:9px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace}
      .motion-cert-status.good{color:#7bf1a9}.motion-cert-status.warn{color:#ffd166}.motion-cert-status.bad{color:#ff9b92}
      @media(max-width:760px){.motion-cert-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
    `;document.head.appendChild(style);
  }

  function markScroll(kind='page'){
    state.lastInputAt=performance.now();state.scrollEvents++;if(kind==='score')state.scoreScrollEvents++;
    if(!state.scrolling){state.scrolling=true;document.body?.classList.add('sbb-scroll-active');window.dispatchEvent(new CustomEvent('sbb:scroll-active',{detail:{active:true,kind}}));}
    clearTimeout(idleTimer);idleTimer=setTimeout(endScroll,135);
  }
  function endScroll(){
    if(!state.scrolling)return;state.scrolling=false;document.body?.classList.remove('sbb-scroll-active');window.dispatchEvent(new CustomEvent('sbb:scroll-active',{detail:{active:false}}));scheduleFlush();
  }
  function defer(fn){
    if(typeof fn!=='function')return false;
    if(!state.scrolling){queueMicrotask(fn);return false;}
    deferredQueue.push(fn);state.deferred++;return true;
  }
  function scheduleFlush(){clearTimeout(flushTimer);flushTimer=setTimeout(()=>{if(state.scrolling)return;const batch=deferredQueue.splice(0);for(const fn of batch){try{fn();}catch(err){console.warn('[SBB motion deferred]',err);}}state.flushed+=batch.length;},40);}

  function bindScrollSignals(){
    window.addEventListener('scroll',()=>markScroll('page'),{passive:true});
    document.addEventListener('wheel',ev=>{if(ev.target?.closest?.('#scoreCells'))markScroll('score');else markScroll('page');},{passive:true});
    document.addEventListener('touchmove',ev=>{if(ev.target?.closest?.('#scoreCells'))markScroll('score');else markScroll('page');},{passive:true});
    const bindScore=()=>{const s=$('scoreCells');if(!s||s.dataset.sbbSmoothBound==='1')return;s.dataset.sbbSmoothBound='1';s.addEventListener('scroll',()=>markScroll('score'),{passive:true});};
    bindScore();
  }

  function installOffscreenSuspension(){
    if(!('IntersectionObserver'in window))return;
    const selector='.sport-feed-diagnostics,#coveragePipeline,.mobile-live-bar,.proof-card,.milestone-console';
    io=new IntersectionObserver(entries=>{for(const entry of entries){const el=entry.target;if(entry.isIntersecting){if(el.classList.remove('sbb-paint-suspended'))state.offscreenSuspended=Math.max(0,state.offscreenSuspended-1);}else{const h=Math.max(1,Math.round(entry.boundingClientRect.height||el.getBoundingClientRect().height||120));el.style.setProperty('--sbb-suspended-height',`${h}px`);if(!el.classList.contains('sbb-paint-suspended')){el.classList.add('sbb-paint-suspended');state.offscreenSuspended++;}}}},{root:null,rootMargin:'240px 0px 240px 0px',threshold:0});
    document.querySelectorAll(selector).forEach(el=>io.observe(el));
  }

  const percentile=(values,p)=>{if(!values.length)return 0;const a=[...values].sort((x,y)=>x-y);return a[Math.min(a.length-1,Math.max(0,Math.ceil(a.length*p)-1))];};
  const median=values=>percentile(values,.5);
  function longTaskObserver(bucket){
    if(!('PerformanceObserver'in window))return null;
    try{const po=new PerformanceObserver(list=>{for(const e of list.getEntries())bucket.push(e.duration);});po.observe({entryTypes:['longtask']});return po;}catch(_){return null;}
  }

  async function estimateRefresh(){
    const deltas=[];let last=0;
    await new Promise(resolve=>{let n=0;const step=t=>{if(last){const d=t-last;if(d>4&&d<80)deltas.push(d);}last=t;if(++n>=72)resolve();else requestAnimationFrame(step);};requestAnimationFrame(step);});
    const ms=median(deltas.filter(d=>d<40))||16.667;state.refreshHz=Math.round(1000/ms);return ms;
  }

  async function samplePhase(name,durationMs,driver,refreshMs){
    const deltas=[],longs=[];const po=longTaskObserver(longs);let last=0,start=0,frames=0;
    await new Promise(resolve=>{const step=t=>{if(!start)start=t;if(last)deltas.push(t-last);last=t;frames++;const elapsed=t-start;try{driver?.(Math.min(1,elapsed/durationMs),elapsed);}catch(_){}if(elapsed>=durationMs)resolve();else requestAnimationFrame(step);};requestAnimationFrame(step);});
    try{po?.disconnect();}catch(_){}
    const missed=deltas.reduce((n,d)=>n+Math.max(0,Math.round(d/refreshMs)-1),0),p95=percentile(deltas,.95),worst=Math.max(0,...deltas),late=deltas.filter(d=>d>refreshMs*1.35).length;
    return {name,frames,samples:deltas.length,p95Ms:+p95.toFixed(2),worstMs:+worst.toFixed(2),lateFrames:late,droppedEstimate:missed,longTasks:longs.length,longTaskMaxMs:+Math.max(0,...longs).toFixed(2),onTimePct:+(deltas.length?((deltas.length-late)/deltas.length*100):100).toFixed(1)};
  }

  function rootScroller(){return document.scrollingElement||document.documentElement;}
  async function runCertification(){
    if(certRunning)return state.lastReport;certRunning=true;renderCertState('RUNNING');
    const refreshMs=await estimateRefresh(),refreshHz=Math.round(1000/refreshMs),phases=[];
    phases.push(await samplePhase('SPORTS TICKER',1600,null,refreshMs));

    const score=$('scoreCells');
    if(score&&score.scrollWidth-score.clientWidth>40){
      const original=score.scrollLeft,max=score.scrollWidth-score.clientWidth,span=Math.min(850,Math.max(180,max*.45)),base=Math.min(original,Math.max(0,max-span));
      phases.push(await samplePhase('SCORE RIBBON',1800,p=>{const wave=(1-Math.cos(p*Math.PI*2))/2;score.scrollLeft=Math.min(max,base+span*wave);},refreshMs));score.scrollLeft=original;
    }else phases.push({name:'SCORE RIBBON',skipped:true,reason:'not horizontally scrollable'});

    const root=rootScroller(),originalY=root.scrollTop,maxY=Math.max(0,root.scrollHeight-root.clientHeight);
    if(maxY>80){
      const oldKeep=window.SBB_VIEW_PREFS?.keepVideoVisible;try{if(oldKeep)window.SBB_VIEW_PREFS?.setKeepVideoVisible?.(false);}catch(_){}
      const target=Math.min(maxY,Math.max(originalY+420,Math.min(maxY,520))),span=target-originalY;
      phases.push(await samplePhase('VERTICAL PAGE',1800,p=>{const wave=(1-Math.cos(p*Math.PI*2))/2;root.scrollTop=Math.max(0,Math.min(maxY,originalY+span*wave));},refreshMs));root.scrollTop=originalY;
      try{if(oldKeep)window.SBB_VIEW_PREFS?.setKeepVideoVisible?.(true);}catch(_){}
    }else phases.push({name:'VERTICAL PAGE',skipped:true,reason:'page not vertically scrollable'});

    const measured=phases.filter(x=>!x.skipped),worstP95=Math.max(0,...measured.map(x=>x.p95Ms||0)),worstFrame=Math.max(0,...measured.map(x=>x.worstMs||0)),onTime=Math.min(100,...measured.map(x=>x.onTimePct??100)),longTasks=measured.reduce((n,x)=>n+(x.longTasks||0),0);
    const status=(worstP95<=refreshMs*1.45&&onTime>=95&&longTasks===0)?'PASS':(worstP95<=refreshMs*2.2&&onTime>=88?'WARN':'FAIL');
    const viewDiag=window.SBB_VIEW_PREFS?.diagnostics?.()||{};
    state.lastReport={version:VERSION,status,refreshHz,refreshMs:+refreshMs.toFixed(2),generatedAt:new Date().toISOString(),summary:{worstP95Ms:+worstP95.toFixed(2),worstFrameMs:+worstFrame.toFixed(2),minimumOnTimePct:+onTime.toFixed(1),longTasks},phases,scrollController:viewDiag};
    certRunning=false;renderReport(state.lastReport);return state.lastReport;
  }

  function reportText(report=state.lastReport){
    if(!report)return 'No motion certification has run yet.';
    const lines=[`Sports Big Board v${report.version} Scroll & Motion Certification`,`RESULT=${report.status} DISPLAY≈${report.refreshHz}Hz FRAME=${report.refreshMs}ms`,`WORST_P95=${report.summary.worstP95Ms}ms WORST_FRAME=${report.summary.worstFrameMs}ms ON_TIME_MIN=${report.summary.minimumOnTimePct}% LONG_TASKS=${report.summary.longTasks}`];
    for(const p of report.phases){lines.push(p.skipped?`${p.name}: SKIP • ${p.reason}`:`${p.name}: p95 ${p.p95Ms}ms • max ${p.worstMs}ms • on-time ${p.onTimePct}% • dropped≈${p.droppedEstimate} • long tasks ${p.longTasks}`);}
    const d=report.scrollController||{};lines.push(`SCROLL CONTROLLER: ordinary no-op ${d.scrollNoops??'—'} / events ${d.scrollEvents??'—'} • scheduled ${d.scheduledFrames??'—'} • blocking listeners ${d.blockingGestureListeners?'ACTIVE':'OFF'}`);return lines.join('\n');
  }

  function ensureCertUi(){
    const grid=document.querySelector('#settingsPane .settings-grid');if(!grid)return false;
    let card=grid.querySelector('.motion-cert-card');if(card)return true;
    card=document.createElement('div');card.className='settings-card motion-cert-card';card.innerHTML=`<div class="settings-card-title">SCROLL / MOTION CERTIFICATION</div><div class="history-audit-launch-copy"><strong>Frame pacing and scroll smoothness</strong><small>Measures the Sports Ticker, horizontal score ribbon, vertical page scrolling, long tasks, and the Keep Video Visible scroll controller. Native browser interpolation is used; the goal is fewer missed frames, not more artificial scroll points.</small></div><div class="motion-cert-kpis"><div class="motion-cert-kpi"><span>DISPLAY</span><b id="motionCertHz">—</b></div><div class="motion-cert-kpi"><span>WORST P95</span><b id="motionCertP95">—</b></div><div class="motion-cert-kpi"><span>ON-TIME</span><b id="motionCertOnTime">—</b></div><div class="motion-cert-kpi"><span>RESULT</span><b id="motionCertResult">IDLE</b></div></div><div class="motion-cert-actions"><button id="motionCertRun" class="settings-save-btn" type="button">RUN MOTION TEST</button><button id="motionCertCopy" class="settings-save-btn" type="button">COPY MOTION REPORT</button></div><small id="motionCertStatus" class="motion-cert-status">Native/compositor scrolling • score-card virtualization • offscreen paint suspension • conditional Game Center scroll listeners.</small><pre id="motionCertReport" class="motion-cert-report">No motion certification has run yet.</pre>`;
    const ticker=grid.querySelector('.sports-ticker-dev-card');if(ticker?.nextSibling)grid.insertBefore(card,ticker.nextSibling);else grid.appendChild(card);
    $('motionCertRun')?.addEventListener('click',runCertification);$('motionCertCopy')?.addEventListener('click',async()=>{const text=reportText();try{await navigator.clipboard.writeText(text);setStatus('Motion report copied.','good');}catch(_){setStatus('Copy unavailable. Select the report text manually.','warn');}});return true;
  }
  function setStatus(text,cls=''){const el=$('motionCertStatus');if(!el)return;el.textContent=text;el.className=`motion-cert-status ${cls}`.trim();}
  function renderCertState(value){ensureCertUi();const r=$('motionCertResult'),btn=$('motionCertRun');if(r)r.textContent=value;if(btn)btn.disabled=value==='RUNNING';setStatus(value==='RUNNING'?'Sampling frame pacing. The board will perform short controlled scroll movements.':'','');}
  function renderReport(report){ensureCertUi();const hz=$('motionCertHz'),p95=$('motionCertP95'),ot=$('motionCertOnTime'),res=$('motionCertResult'),pre=$('motionCertReport'),btn=$('motionCertRun');if(hz)hz.textContent=`${report.refreshHz} Hz`;if(p95)p95.textContent=`${report.summary.worstP95Ms} ms`;if(ot)ot.textContent=`${report.summary.minimumOnTimePct}%`;if(res)res.textContent=report.status;if(pre)pre.textContent=reportText(report);if(btn)btn.disabled=false;setStatus(report.status==='PASS'?'Frame pacing passed the v5.2.11 motion gate.':report.status==='WARN'?'Frame pacing is usable but still has measurable misses.':'Frame pacing failed the motion gate.',report.status==='PASS'?'good':report.status==='WARN'?'warn':'bad');}

  function init(){injectStyle();bindScrollSignals();installOffscreenSuspension();ensureCertUi();window.addEventListener('sbb:drawer-state',()=>defer(()=>{}));}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();

  window.SBB_SCROLL_MOTION=Object.freeze({version:VERSION,defer,runCertification,report:()=>state.lastReport,diagnostics:()=>({...state,queued:deferredQueue.length}),get scrolling(){return state.scrolling;}});
})();

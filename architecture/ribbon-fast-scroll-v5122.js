/* Sports Big Board v5.1.22 — frame-budgeted score ribbon scrolling.

   The score ribbon is an interaction surface, not a compute surface. Legacy desktop
   browsing writes scrollLeft from every wheel/pointermove callback. Dense special
   events such as tennis can produce hundreds of pointer/wheel callbacks while lazy
   flag images are also painting. This layer intercepts only the high-frequency
   movement callbacks and batches their scroll write to one requestAnimationFrame.

   No score/media/provider work occurs here. No card scan occurs during scrolling.
*/
(() => {
  'use strict';
  if(window.SBB_RIBBON_FAST_SCROLL?.version==='5.1.22')return;

  const VERSION='5.1.22';
  const state={
    installed:false,wheelEvents:0,dragMoves:0,frames:0,coalesced:0,
    metricReads:0,focusSuppressed:0,lastFrameMs:0,maxFrameMs:0,
    activeUntil:0,maxScroll:0,currentScroll:0,hostWidth:0,pendingTarget:null,
  };
  let host=null,raf=0,drag=null,suppressClickUntil=0,resizeObserver=null;
  const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
  const active=()=>performance.now()<state.activeUntil;
  const interact=(ms=900)=>{state.activeUntil=performance.now()+ms;};

  function refreshMetrics(){
    if(!host)return;
    state.metricReads++;
    state.hostWidth=Math.max(1,host.clientWidth||1);
    state.maxScroll=Math.max(0,host.scrollWidth-state.hostWidth);
    state.currentScroll=clamp(Number(host.scrollLeft)||0,0,state.maxScroll);
    if(state.pendingTarget!=null)state.pendingTarget=clamp(state.pendingTarget,0,state.maxScroll);
  }

  function scheduleFrame(target){
    state.pendingTarget=clamp(Number(target)||0,0,state.maxScroll);
    if(raf){state.coalesced++;return;}
    raf=requestAnimationFrame(()=>{
      const started=performance.now();raf=0;
      const targetNow=state.pendingTarget;state.pendingTarget=null;
      if(host&&targetNow!=null){
        // One write per display frame. The passive scroll listener mirrors the
        // resulting position without forcing geometry/layout recalculation.
        host.scrollLeft=targetNow;
        state.currentScroll=targetNow;
      }
      state.frames++;
      state.lastFrameMs=Math.round((performance.now()-started)*1000)/1000;
      state.maxFrameMs=Math.max(state.maxFrameMs,state.lastFrameMs);
    });
  }

  function wheelDelta(e){
    let delta=Math.abs(e.deltaX)>Math.abs(e.deltaY)?e.deltaX:e.deltaY;
    if(e.deltaMode===1)delta*=18;
    else if(e.deltaMode===2)delta*=Math.max(240,state.hostWidth||640);
    return Number(delta)||0;
  }

  function onWheel(e){
    if(!host)return;
    if(state.maxScroll<=0)refreshMetrics();
    const delta=wheelDelta(e);if(!delta||state.maxScroll<=0)return;
    const start=state.pendingTarget==null?state.currentScroll:state.pendingTarget;
    // At the physical ribbon edge, let the document consume outward wheel motion.
    if((start<=0&&delta<0)||(start>=state.maxScroll&&delta>0))return;
    const next=clamp(start+delta,0,state.maxScroll);
    if(Math.abs(next-start)<.25)return;
    state.wheelEvents++;interact();scheduleFrame(next);
    e.preventDefault();
    // Stops the older target-phase wheel handler from issuing a second synchronous
    // scrollLeft write for the same hardware event.
    e.stopImmediatePropagation();
  }

  function onPointerDown(e){
    if(e.pointerType!=='mouse'||e.button!==0||!host)return;
    refreshMetrics();
    drag={id:e.pointerId,startX:e.clientX,startScroll:state.currentScroll,moved:false};
    interact(1200);
    // Do not stop propagation. Card clicks/pointerdown behavior remains intact;
    // only pointermove is intercepted after the drag threshold is crossed.
  }

  function onPointerMove(e){
    if(!drag||drag.id!==e.pointerId||(e.buttons&1)!==1)return;
    const dx=e.clientX-drag.startX;
    if(!drag.moved&&Math.abs(dx)<5)return;
    if(!drag.moved){
      drag.moved=true;host.classList.add('is-dragging');
      try{host.setPointerCapture(e.pointerId);}catch(_){}
    }
    state.dragMoves++;interact(1200);
    scheduleFrame(drag.startScroll-dx);
    e.preventDefault();
    // Prevent legacy per-pointermove scroll writes, but only after this gesture has
    // unambiguously become a horizontal drag.
    e.stopImmediatePropagation();
  }

  function finishDrag(e){
    if(!drag||drag.id!==e.pointerId)return;
    if(drag.moved)suppressClickUntil=Date.now()+260;
    host?.classList.remove('is-dragging');
    try{host?.releasePointerCapture?.(e.pointerId);}catch(_){}
    drag=null;interact(250);
  }

  function onClickCapture(e){
    if(Date.now()>=suppressClickUntil)return;
    suppressClickUntil=0;e.preventDefault();e.stopImmediatePropagation();
  }

  function installFocusGuard(){
    const original=window.applyScoreRibbonFocusVisuals;
    if(typeof original!=='function'||original.__sbbFastScrollV5122)return false;
    const wrapped=function(options={}){
      if(active()&&options?.scroll!==false){
        state.focusSuppressed++;
        return original.call(this,{...(options||{}),scroll:false});
      }
      return original.apply(this,arguments);
    };
    wrapped.__sbbFastScrollV5122=true;wrapped.__sbbOriginal=original;
    window.applyScoreRibbonFocusVisuals=wrapped;
    try{applyScoreRibbonFocusVisuals=wrapped;}catch(_){}
    return true;
  }

  function install(){
    host=document.getElementById('scoreCells');
    if(!host||host.dataset.sbbFastScrollV5122)return false;
    host.dataset.sbbFastScrollV5122='1';
    host.classList.add('sbb-fast-score-ribbon');
    refreshMetrics();

    // Capture phase intentionally precedes app.js's legacy target-phase desktop
    // wheel/pointermove listeners even though this module loads later.
    host.addEventListener('wheel',onWheel,{capture:true,passive:false});
    host.addEventListener('pointerdown',onPointerDown,{capture:true,passive:true});
    host.addEventListener('pointermove',onPointerMove,{capture:true,passive:false});
    host.addEventListener('pointerup',finishDrag,{capture:true,passive:true});
    host.addEventListener('pointercancel',finishDrag,{capture:true,passive:true});
    host.addEventListener('click',onClickCapture,{capture:true});
    host.addEventListener('scroll',()=>{state.currentScroll=Number(host.scrollLeft)||0;},{passive:true});

    const refresh=()=>requestAnimationFrame(refreshMetrics);
    window.addEventListener('resize',refresh,{passive:true});
    window.addEventListener('sbb:render-pipeline',ev=>{
      if(ev?.detail?.type==='render'||ev?.detail?.type==='paint')refresh();
    });
    try{resizeObserver=new ResizeObserver(refresh);resizeObserver.observe(host);}catch(_){}
    installFocusGuard();
    // app.js can expose the focus helper slightly after this script in unusual
    // cached load order; one bounded retry keeps the guard deterministic.
    setTimeout(installFocusGuard,50);

    state.installed=true;
    return true;
  }

  const style=document.createElement('style');
  style.id='sbbRibbonFastScrollV5122Style';
  style.textContent=`
    #scoreCells.sbb-fast-score-ribbon{scroll-behavior:auto!important;scroll-snap-type:none!important;overscroll-behavior-inline:contain}
    #scoreCells.sbb-fast-score-ribbon.is-dragging{cursor:grabbing;user-select:none}
    #scoreCells.sbb-fast-score-ribbon .score-card.sbb-tennis-score-card{contain:layout paint style}
  `;
  document.head.appendChild(style);

  window.SBB_RIBBON_FAST_SCROLL=Object.freeze({
    version:VERSION,install,
    snapshot:()=>({...state,active:active(),rafPending:!!raf,dragging:!!drag}),
    refreshMetrics,
  });
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
})();

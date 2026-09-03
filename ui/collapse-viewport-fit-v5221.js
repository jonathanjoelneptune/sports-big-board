/* Sports Big Board v5.3.3 — Clean Collapse + Viewport Fit */
(() => {
  'use strict';
  if(window.SBB_COLLAPSE_VIEWPORT_FIT?.version==='5.3.3') return;

  const VERSION='5.3.3';
  const $=id=>document.getElementById(id);
  let queued=false;

  function desktop(){
    return window.matchMedia?.('(min-width:1100px) and (pointer:fine)')?.matches===true;
  }

  function viewportHeight(){
    return Math.max(1,Math.round(window.visualViewport?.height||window.innerHeight||document.documentElement.clientHeight||1));
  }

  function fitCollapsedStage(){
    queued=false;
    const body=document.body,stage=$('stage');
    if(!body||!stage||!desktop()||!body.classList.contains('sbb-drawer-collapsed')){
      body?.style.removeProperty('--sbb-collapsed-stage-height');
      return;
    }
    const top=Math.max(0,stage.getBoundingClientRect().top);
    const bottomGap=8;
    const available=Math.floor(viewportHeight()-top-bottomGap);
    // Never make the viewing surface unusably short. At ordinary desktop sizes
    // the value is the exact remaining viewport, preventing a new page scrollbar.
    const height=Math.max(320,available);
    body.style.setProperty('--sbb-collapsed-stage-height',`${height}px`);
  }

  function scheduleFit(){
    if(queued)return;
    queued=true;
    requestAnimationFrame(()=>requestAnimationFrame(fitCollapsedStage));
  }

  function polishHandle(){
    const btn=$('drawerCollapseToggle');
    if(!btn)return;
    btn.setAttribute('aria-describedby','');
    btn.classList.add('sbb-centered-drawer-handle');
  }

  function init(){
    polishHandle();
    scheduleFit();
    window.addEventListener('resize',scheduleFit,{passive:true});
    window.visualViewport?.addEventListener('resize',scheduleFit,{passive:true});
    window.addEventListener('sbb:workspace-resize',()=>{
      polishHandle();
      scheduleFit();
      setTimeout(scheduleFit,260);
    });
    window.addEventListener('pageshow',scheduleFit);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)scheduleFit();});
    setTimeout(()=>{polishHandle();scheduleFit();},500);
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});
  else init();

  window.SBB_COLLAPSE_VIEWPORT_FIT=Object.freeze({version:VERSION,fit:fitCollapsedStage,snapshot:()=>({collapsed:document.body?.classList.contains('sbb-drawer-collapsed')||false,height:document.body?.style.getPropertyValue('--sbb-collapsed-stage-height')||''})});
})();

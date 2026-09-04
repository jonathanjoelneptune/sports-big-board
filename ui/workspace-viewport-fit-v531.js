/* Sports Big Board v5.4.4 — Workspace Viewport Fit */
(() => {
  'use strict';
  if(window.SBB_WORKSPACE_VIEWPORT_FIT?.version==='5.4.4') return;
  const VERSION='5.4.4';
  const $=id=>document.getElementById(id);
  let queued=false;
  function desktop(){return window.matchMedia?.('(min-width:1100px) and (pointer:fine)')?.matches===true;}
  function viewportHeight(){return Math.max(1,Math.round(window.visualViewport?.height||window.innerHeight||document.documentElement.clientHeight||1));}
  function fit(){
    queued=false;const body=document.body,stage=$('stage');
    if(!body||!stage||!desktop()||!body.classList.contains('sbb-game-center-side')){body?.style.removeProperty('--sbb-workspace-stage-height');return;}
    const top=Math.max(0,stage.getBoundingClientRect().top),bottomGap=8;
    const available=Math.floor(viewportHeight()-top-bottomGap);
    body.style.setProperty('--sbb-workspace-stage-height',`${Math.max(320,available)}px`);
  }
  function schedule(){if(queued)return;queued=true;requestAnimationFrame(()=>requestAnimationFrame(fit));}
  function init(){
    schedule();
    window.addEventListener('resize',schedule,{passive:true});
    window.visualViewport?.addEventListener('resize',schedule,{passive:true});
    window.addEventListener('sbb:workspace-resize',()=>{schedule();setTimeout(schedule,260);});
    window.addEventListener('sbb:browse-layout',()=>{schedule();setTimeout(schedule,80);});
    window.addEventListener('pageshow',schedule);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)schedule();});
    setTimeout(schedule,500);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  window.SBB_WORKSPACE_VIEWPORT_FIT=Object.freeze({version:VERSION,fit,snapshot:()=>({height:document.body?.style.getPropertyValue('--sbb-workspace-stage-height')||'',side:document.body?.classList.contains('sbb-game-center-side')||false})});
})();

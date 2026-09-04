/* Sports Big Board v5.5.0 — Game Center Workspace Reflow
   - drawer collapse changes the actual desktop stage grid
   - PREV/NEXT use clean centered text labels
   - line score / win probability live only inside Overview
   - Coming Up remains canonical queue UI; no new playback/program ownership */
(() => {
  'use strict';
  if(window.SBB_VIEWING_WORKSPACE?.version==='5.5.0') return;

  const VERSION='5.5.0';
  const STORAGE_KEY='sbb.drawer.collapsed.v2';
  const $=id=>document.getElementById(id);
  let overviewObserver=null;
  let overviewRenderQueued=false;
  let overviewRendering=false;

  function setTransportLabels(){
    const prev=$('prevBtn'),next=$('nextBtn');
    if(prev){
      prev.textContent='PREV';
      prev.setAttribute('aria-label','Previous highlight');
      prev.title='Previous highlight';
      prev.dataset.sbbWorkspaceLabel='1';
    }
    if(next){
      next.textContent='NEXT';
      next.setAttribute('aria-label','Next highlight');
      next.title='Next highlight';
      next.dataset.sbbWorkspaceLabel='1';
    }
  }

  function ensureDrawerToggle(){
    const drawer=$('infoDrawer');
    if(!drawer)return null;
    let btn=$('drawerCollapseToggle');
    if(btn && btn.dataset.sbbWorkspaceToggle!=='1'){
      const fresh=btn.cloneNode(false);
      btn.replaceWith(fresh);
      btn=fresh;
    }
    if(!btn){
      btn=document.createElement('button');
      btn.id='drawerCollapseToggle';
      btn.type='button';
      drawer.insertAdjacentElement('afterbegin',btn);
    }
    btn.dataset.sbbWorkspaceToggle='1';
    btn.textContent='›';
    return btn;
  }

  function notifyLayout(){
    requestAnimationFrame(()=>{
      try{window.SBB_VIEW_PREFS?.reset?.();}catch(_){}
      try{window.SBB_VIEW_PREFS?.refresh?.();}catch(_){}
      try{window.dispatchEvent(new Event('resize'));}catch(_){}
      try{window.dispatchEvent(new CustomEvent('sbb:workspace-resize',{detail:{collapsed:document.body.classList.contains('sbb-drawer-collapsed')}}));}catch(_){}
    });
    setTimeout(()=>{try{window.dispatchEvent(new Event('resize'));}catch(_){}},240);
  }

  function setCollapsed(collapsed,{persist=true}={}){
    collapsed=!!collapsed;
    document.body.classList.toggle('sbb-drawer-collapsed',collapsed);
    document.documentElement.dataset.sbbDrawerCollapsed=collapsed?'1':'0';
    const btn=ensureDrawerToggle();
    if(btn){
      btn.textContent=collapsed?'‹':'›';
      btn.setAttribute('aria-expanded',collapsed?'false':'true');
      btn.setAttribute('aria-label',collapsed?'Expand Game Center drawer':'Collapse Game Center drawer');
      btn.title=collapsed?'Expand Game Center':'Collapse Game Center';
    }
    if(persist){try{localStorage.setItem(STORAGE_KEY,collapsed?'1':'0');}catch(_){}}
    notifyLayout();
  }

  function bindDrawerToggle(){
    const btn=ensureDrawerToggle();
    if(!btn||btn.dataset.sbbWorkspaceBound==='1')return;
    btn.dataset.sbbWorkspaceBound='1';
    btn.addEventListener('click',ev=>{
      ev.preventDefault();
      ev.stopPropagation();
      setCollapsed(!document.body.classList.contains('sbb-drawer-collapsed'));
    });
  }

  function restoreDrawerState(){
    let collapsed=false;
    try{collapsed=localStorage.getItem(STORAGE_KEY)==='1';}catch(_){}
    setCollapsed(collapsed,{persist:false});
  }

  function currentGameCenterData(){
    try{
      const event=window.SBB_SELECTED_EVENT?.get?.();
      return event ? window.SBB_GAME_CENTER?.peek?.(event)||null : null;
    }catch(_){return null;}
  }

  function normalizedEnhancementHtml(gc){
    if(!gc)return '';
    const view=window.SBB_GAME_CENTER_MULTISPORT_VIEW;
    if(!view)return '';
    let line='';
    let probability='';
    try{line=String(view.periodCard?.(gc)||'');}catch(_){}
    try{probability=String(view.probabilityCard?.(gc)||'');}catch(_){}
    // The legacy enhancer removes cards whose title is exactly LINESCORE because
    // it used to own a persistent above-tabs line score. This clone intentionally
    // lives in Overview, so use LINE SCORE to keep the legacy cleanup from deleting it.
    line=line.replace(/>LINESCORE(?=<|\s)/,'>LINE SCORE');
    return line+probability;
  }

  function renderOverviewEnhancements(){
    overviewRenderQueued=false;
    if(overviewRendering)return;
    const overview=$('gcOverview');
    if(!overview)return;
    const gc=currentGameCenterData();
    const html=normalizedEnhancementHtml(gc);
    let host=$('gcOverviewBroadcastSummary');
    if(!html){
      host?.remove();
      return;
    }
    overviewRendering=true;
    try{
      if(!host){
        host=document.createElement('div');
        host.id='gcOverviewBroadcastSummary';
        host.className='gc-overview-broadcast-summary';
        overview.insertAdjacentElement('afterbegin',host);
      }else if(host.parentElement!==overview){
        overview.insertAdjacentElement('afterbegin',host);
      }
      if(host.innerHTML!==html)host.innerHTML=html;
      if(overview.firstElementChild!==host)overview.insertAdjacentElement('afterbegin',host);
    }finally{overviewRendering=false;}
  }

  function scheduleOverviewEnhancements(){
    if(overviewRenderQueued||overviewRendering)return;
    overviewRenderQueued=true;
    queueMicrotask(()=>requestAnimationFrame(renderOverviewEnhancements));
  }

  function bindOverview(){
    const overview=$('gcOverview');
    if(!overview){setTimeout(bindOverview,120);return;}
    overviewObserver?.disconnect?.();
    overviewObserver=new MutationObserver(()=>scheduleOverviewEnhancements());
    overviewObserver.observe(overview,{childList:true});
    document.querySelectorAll('[data-gc-section]').forEach(btn=>btn.addEventListener('click',()=>{
      if(btn.dataset.gcSection==='overview')scheduleOverviewEnhancements();
    }));
    window.SBB_SELECTED_EVENT?.subscribe?.(()=>{
      setTimeout(scheduleOverviewEnhancements,0);
      setTimeout(scheduleOverviewEnhancements,180);
      setTimeout(scheduleOverviewEnhancements,650);
    });
    window.addEventListener('sbb:selected-event-change',scheduleOverviewEnhancements);
    scheduleOverviewEnhancements();
  }

  function ensureComingUpPlacement(){
    const pane=$('gameCenterPane'),dock=$('nextUpDock');
    if(pane&&dock&&dock.parentElement!==pane)pane.appendChild(dock);
  }

  function init(){
    setTransportLabels();
    bindDrawerToggle();
    restoreDrawerState();
    bindOverview();
    ensureComingUpPlacement();
    window.addEventListener('sbb:drawer-state',()=>requestAnimationFrame(()=>{
      ensureComingUpPlacement();
      setTransportLabels();
    }));
    setTimeout(()=>{ensureComingUpPlacement();setTransportLabels();scheduleOverviewEnhancements();},500);
    setTimeout(()=>{ensureComingUpPlacement();scheduleOverviewEnhancements();},1400);
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();

  window.SBB_VIEWING_WORKSPACE=Object.freeze({
    version:VERSION,
    setCollapsed,
    renderOverviewEnhancements,
    snapshot:()=>({collapsed:document.body.classList.contains('sbb-drawer-collapsed'),overviewEnhancements:!!$('gcOverviewBroadcastSummary')})
  });
})();

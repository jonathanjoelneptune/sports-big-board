/* Sports Big Board v5.2.18 — Integrated Up Next + NEXT transport repair.
   Reuses the canonical #queueList and its established onclick handlers. It does
   not create a second PROGRAM, selection model, playback owner, or date owner. */
(() => {
  'use strict';
  if(window.SBB_UP_NEXT_EXPERIENCE?.version==='5.2.18') return;

  const VERSION='5.2.18';
  const state={renders:0,dockClicks:0,nextClicks:0,nextFallbacks:0,lastError:''};
  const $=id=>document.getElementById(id);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function activeDrawerTab(){
    return document.querySelector('.info-drawer-tab.active,[data-drawer-tab][aria-selected="true"]')?.dataset?.drawerTab || 'game-center';
  }

  function syncDrawerTabState(){
    const drawer=$('infoDrawer');
    if(drawer) drawer.dataset.sbbDrawerTab=activeDrawerTab();
  }

  function ensureDock(){
    const drawer=$('infoDrawer');
    const pane=$('gameCenterPane');
    if(!drawer||!pane) return null;
    let dock=$('nextUpDock');
    if(!dock){
      dock=document.createElement('section');
      dock.id='nextUpDock';
      dock.className='next-up-dock';
      dock.setAttribute('aria-label','Coming up next');
      dock.innerHTML='<div class="next-up-dock-head"><strong>Coming Up</strong><span>Programming queue</span></div><div id="nextUpDockGrid" class="next-up-dock-grid"></div>';
    }
    if(dock.parentElement!==pane) pane.appendChild(dock);
    return dock;
  }

  function sourceRows(){
    return [...document.querySelectorAll('#queueList .queue-item')].filter(row=>!row.classList.contains('current'));
  }

  function renderDock(){
    const dock=ensureDock();
    const grid=$('nextUpDockGrid');
    if(!dock||!grid) return;
    syncDrawerTabState();
    const rows=sourceRows().slice(0,3);
    grid.replaceChildren();
    if(!rows.length){
      const empty=document.createElement('div');
      empty.className='next-up-dock-empty';
      empty.textContent='Programming queue is building…';
      grid.appendChild(empty);
      state.renders++;
      return;
    }
    rows.forEach((row,i)=>{
      const card=document.createElement('button');
      card.type='button';
      card.className='next-up-dock-card';
      const img=row.querySelector('.queue-thumb-wrap img');
      const fallback=row.querySelector('.queue-thumb-fallback');
      const title=row.querySelector('.queue-copy>strong')?.textContent?.trim()||'Upcoming sports highlight';
      const duration=row.querySelector('.queue-duration-col')?.textContent?.trim()||'';
      const visual=img?.src
        ? `<img src="${esc(img.src)}" alt="">`
        : `<div class="next-up-dock-fallback">${esc(fallback?.textContent?.trim()||'SBB')}</div>`;
      card.innerHTML=`<div class="next-up-dock-visual">${visual}<span class="next-up-dock-index">${i+1}</span>${duration?`<span class="next-up-dock-duration">${esc(duration)}</span>`:''}</div><strong>${esc(title)}</strong>`;
      card.addEventListener('click',()=>{state.dockClicks++;row.click();});
      grid.appendChild(card);
    });
    state.renders++;
  }

  function bindDrawerTabs(){
    document.querySelectorAll('[data-drawer-tab]').forEach(btn=>btn.addEventListener('click',()=>requestAnimationFrame(()=>{syncDrawerTabState();renderDock();})));
    window.addEventListener('sbb:drawer-state',()=>requestAnimationFrame(()=>{syncDrawerTabState();renderDock();}));
  }

  function patchRenderQueue(){
    if(typeof renderQueue!=='function' || renderQueue.__sbbUpNextV5216) return false;
    const original=renderQueue;
    const wrapped=function(...args){
      const result=original.apply(this,args);
      queueMicrotask(renderDock);
      return result;
    };
    wrapped.__sbbUpNextV5216=true;
    wrapped.__sbbOriginal=original;
    try{renderQueue=wrapped;}catch(_){}
    try{window.renderQueue=wrapped;}catch(_){}
    return true;
  }

  function canonicalNextRow(){
    try{if(typeof renderQueue==='function')renderQueue();}catch(_){}
    const rows=[...document.querySelectorAll('#queueList .queue-item')];
    return rows.find(row=>!row.classList.contains('current'))||null;
  }

  function fallbackNext(){
    try{
      if(typeof nextVisibleQueueIndex!=='function'||typeof tuneProgramIndexV5!=='function')return false;
      const target=nextVisibleQueueIndex();
      if(target<0)return false;
      if(typeof showBumper==='function')showBumper(target,400,'UP NEXT');
      tuneProgramIndexV5(target,{userInitiated:true,reason:'manual next control v5.2.18 fallback'});
      state.nextFallbacks++;
      return true;
    }catch(err){state.lastError=String(err?.message||err);return false;}
  }

  function repairNextButton(){
    const btn=$('nextBtn');
    if(!btn||btn.__sbbNextV5217)return false;
    btn.__sbbNextV5217=true;
    btn.onclick=()=>{
      state.nextClicks++;
      try{
        if(typeof sbbPlaybackAllowed==='function'&&!sbbPlaybackAllowed({notify:true}))return;
        const row=canonicalNextRow();
        if(row){row.click();return;}
        if(!fallbackNext()&&typeof showAllCaughtUp==='function')showAllCaughtUp();
      }catch(err){
        state.lastError=String(err?.message||err);
        if(!fallbackNext())console.error('[SBB v5.2.18] NEXT control failed',err);
      }
    };
    return true;
  }

  function init(){
    ensureDock();
    syncDrawerTabState();
    patchRenderQueue();
    repairNextButton();
    bindDrawerTabs();
    renderDock();
    // Some legacy boot paths replace or populate the queue shortly after app load.
    setTimeout(()=>{patchRenderQueue();repairNextButton();renderDock();},350);
    setTimeout(()=>renderDock(),1200);
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  window.SBB_UP_NEXT_EXPERIENCE=Object.freeze({version:VERSION,render:renderDock,snapshot:()=>({...state,activeTab:activeDrawerTab(),dockItems:$('nextUpDockGrid')?.children?.length||0})});
})();

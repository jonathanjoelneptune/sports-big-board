/* Sports Big Board v5.3.18 — Integrated Up Next + NEXT transport repair.
   The visual shelf now reads the canonical visibleQueueEntries() result instead
   of trusting queue DOM ordering/current-row classes. It does not create a second
   PROGRAM, selection model, playback owner, or date owner. */
(() => {
  'use strict';
  if(window.SBB_UP_NEXT_EXPERIENCE?.version==='5.3.18') return;

  const VERSION='5.3.18';
  const state={renders:0,dockClicks:0,nextClicks:0,nextFallbacks:0,interruptRenders:0,lastError:'',source:'none'};
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

  // Kept as a DOM fallback for startup/legacy paths, but the normal shelf source
  // is canonicalProgramEntries() below.
  function sourceRows(){
    const currentTitle=String($('currentTitle')?.textContent||'').trim().toLowerCase();
    return [...document.querySelectorAll('#queueList .queue-item')].filter(row=>{
      if(row.classList.contains('current'))return false;
      const title=String(row.querySelector('.queue-copy>strong')?.textContent||'').trim().toLowerCase();
      return !(currentTitle&&title&&title===currentTitle);
    });
  }

  function canonicalProgramEntries(wanted=3){
    try{
      const interrupt=window.SBB_SCORE_INTERRUPT_QUEUE?.entries?.(wanted);
      if(Array.isArray(interrupt)&&interrupt.length){state.source='score-interrupt-projection';return interrupt;}
      if(typeof visibleQueueEntries==='function'){
        const entries=visibleQueueEntries(wanted);
        if(Array.isArray(entries)&&entries.length){state.source='visibleQueueEntries';return entries;}
      }
    }catch(err){state.lastError=String(err?.message||err);}
    state.source='queue-dom-fallback';
    return sourceRows().slice(0,wanted).map((row,i)=>({row,idx:null,item:null,position:i}));
  }

  function itemTitle(item,row){
    if(item){
      const curated=String(item?.queueTitle||'').trim();if(curated)return curated;
      try{if(typeof displayProgramTitle==='function')return String(displayProgramTitle(item)||'').trim();}catch(_){}
      return String(item?.title||item?.subtitle||'Upcoming sports highlight').trim();
    }
    return String(row?.querySelector('.queue-copy>strong')?.textContent||'Upcoming sports highlight').trim();
  }
  function itemThumb(item,row){
    if(item){
      const thumb=String(item?.thumbnail||item?.thumbnailUrl||item?.image||item?.imageUrl||'').trim();
      if(thumb)return thumb;
      const id=String(item?.youtubeId||item?.videoId||'').trim();
      if(id)return `https://i.ytimg.com/vi/${encodeURIComponent(id)}/mqdefault.jpg`;
    }
    return String(row?.querySelector('.queue-thumb-wrap img')?.src||'').trim();
  }
  function itemDuration(item,row){
    if(item){
      try{
        if(typeof formatDuration==='function'){
          const d=formatDuration(item?.generatedTopPlays ? item?.topPlaysTotalDuration : (item?.durationSeconds ?? item?.duration));
          if(d)return String(d);
        }
      }catch(_){}
    }
    return String(row?.querySelector('.queue-duration-col')?.textContent||'').trim();
  }
  function itemLeague(item){return String(item?.league||item?.competitionId||'').toUpperCase();}

  function tuneEntry(entry){
    state.dockClicks++;
    try{
      if(entry?.interruptResume&&window.SBB_SCORE_INTERRUPT_QUEUE?.play?.(entry))return true;
      if(entry?.row){entry.row.click();return true;}
      const idx=Number(entry?.idx);
      if(!Number.isFinite(idx)||idx<0)return false;
      if(typeof jumpTo==='function'){jumpTo(idx);return true;}
      if(typeof tuneProgramIndexV5==='function'){
        tuneProgramIndexV5(idx,{userInitiated:true,reason:'Coming Up card selection v5.3.18'});
        return true;
      }
    }catch(err){state.lastError=String(err?.message||err);}
    return false;
  }

  function renderInterruptQueueList(){
    const api=window.SBB_SCORE_INTERRUPT_QUEUE;
    if(!api?.active?.())return false;
    const list=$('queueList');
    if(!list)return false;
    const entries=api.entries?.(7)||[];
    list.replaceChildren();
    if(!entries.length)return true;
    entries.forEach((entry,i)=>{
      const item=entry.item||null;
      const row=document.createElement('div');
      row.className=`queue-item ${i===0?'next':''} interrupt-resume-queue-item`;
      row.setAttribute('role','button');
      row.tabIndex=0;
      const title=itemTitle(item,null);
      const duration=itemDuration(item,null);
      const thumb=itemThumb(item,null);
      const league=itemLeague(item);
      const visual=thumb?`<div class="queue-thumb-wrap"><img src="${esc(thumb)}" alt=""></div>`:`<div class="queue-thumb-wrap"><div class="queue-thumb-fallback">${esc(league||'SBB')}</div></div>`;
      row.innerHTML=`<div class="queue-num">${i+1}</div>${visual}<div class="queue-copy"><strong>${esc(title)}</strong><span class="queue-meta-polished">${i===0?'RESUMES AFTER SELECTED HIGHLIGHT':'QUEUED'}${league?` • ${esc(league)}`:''}</span></div><div class="queue-duration-col">${esc(duration||'—')}</div>`;
      const play=()=>tuneEntry(entry);
      row.addEventListener('click',play);
      row.addEventListener('keydown',ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();play();}});
      list.appendChild(row);
    });
    state.interruptRenders++;
    return true;
  }

  function renderDock(){
    const dock=ensureDock();
    const grid=$('nextUpDockGrid');
    if(!dock||!grid) return;
    syncDrawerTabState();
    renderInterruptQueueList();
    const entries=canonicalProgramEntries(3);
    grid.replaceChildren();
    if(!entries.length){
      const empty=document.createElement('div');
      empty.className='next-up-dock-empty';
      empty.textContent='Programming queue is building…';
      grid.appendChild(empty);
      state.renders++;
      return;
    }
    entries.forEach((entry,i)=>{
      const item=entry.item||null,row=entry.row||null;
      const card=document.createElement('button');
      card.type='button';
      card.className='next-up-dock-card';
      const title=itemTitle(item,row);
      const duration=itemDuration(item,row);
      const thumb=itemThumb(item,row);
      const league=itemLeague(item);
      const visual=thumb
        ? `<img src="${esc(thumb)}" alt="">`
        : `<div class="next-up-dock-fallback">${esc(league||'SBB')}</div>`;
      card.innerHTML=`<div class="next-up-dock-visual">${visual}<span class="next-up-dock-index">${i+1}</span>${duration?`<span class="next-up-dock-duration">${esc(duration)}</span>`:''}</div><strong>${esc(title)}</strong>${league?`<small>${esc(league)}</small>`:''}`;
      card.addEventListener('click',()=>tuneEntry(entry));
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
      queueMicrotask(()=>{renderInterruptQueueList();renderDock();});
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
    const rows=sourceRows();
    return rows[0]||null;
  }

  function fallbackNext(){
    try{
      if(typeof nextVisibleQueueIndex!=='function'||typeof tuneProgramIndexV5!=='function')return false;
      const target=nextVisibleQueueIndex();
      if(target<0)return false;
      if(typeof showBumper==='function')showBumper(target,400,'UP NEXT');
      tuneProgramIndexV5(target,{userInitiated:true,reason:'manual next control v5.3.18 fallback'});
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
        const entry=canonicalProgramEntries(1)[0];
        if(entry&&tuneEntry(entry))return;
        const row=canonicalNextRow();
        if(row){row.click();return;}
        if(!fallbackNext()&&typeof showAllCaughtUp==='function')showAllCaughtUp();
      }catch(err){
        state.lastError=String(err?.message||err);
        if(!fallbackNext())console.error('[SBB v5.3.18] NEXT control failed',err);
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
    renderInterruptQueueList();
    renderDock();
    setTimeout(()=>{patchRenderQueue();repairNextButton();renderDock();},350);
    setTimeout(()=>renderDock(),1200);
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  window.SBB_UP_NEXT_EXPERIENCE=Object.freeze({version:VERSION,render:renderDock,renderInterruptQueueList,snapshot:()=>({...state,activeTab:activeDrawerTab(),dockItems:$('nextUpDockGrid')?.children?.length||0})});
})();

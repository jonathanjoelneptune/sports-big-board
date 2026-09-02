/* Sports Big Board v4.7.14 — Frontend Competition Projection.
   Backend Competition Registry 2.0 is authoritative for existence. Competition
   Builder remains the richer editor/catalog. The browser merges both sources,
   persists the last good dynamic projection, and never hides Special Events just
   because one bootstrap request is late or temporarily unavailable.
*/
(() => {
  'use strict';
  if(window.SBB_FRONTEND_REGISTRY?.version==='4.7.14')return;

  const VERSION='4.7.14';
  const STORAGE_KEY='sbb.frontendCompetitionProjection.v1';
  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const today=()=>{
    const d=new Date();
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  };
  const browseDate=()=>{
    try{return clean(window.SBB_SCORE_DATE?.snapshot?.().browseDate||window.scoreBrowseDate||today()).slice(0,10)||today();}
    catch(_){return today();}
  };
  const lifecycle=(row,date=today())=>{
    if(row?.startDate&&date<row.startDate)return 'UPCOMING';
    if(row?.endDate&&date>row.endDate)return 'COMPLETED';
    return 'ACTIVE';
  };

  const state={
    rows:new Map(),
    lastGoodAt:0,
    lastRefreshAt:0,
    errors:[],
    rendering:false,
    refreshPromise:null,
    specialRenderKey:'',
    leagueRenderKey:'',
  };

  function cachedRows(){
    try{
      const p=JSON.parse(localStorage.getItem(STORAGE_KEY)||'{}');
      return Array.isArray(p?.competitions)?p.competitions:[];
    }catch(_){return [];}
  }

  function persist(){
    try{
      const rows=[...state.rows.values()].filter(r=>r?.custom||r?.sourceKind==='DYNAMIC');
      localStorage.setItem(STORAGE_KEY,JSON.stringify({
        version:VERSION,
        savedAt:Date.now(),
        competitions:rows
      }));
    }catch(_){}
  }

  function normalizedType(row,source=''){
    const id=upper(row.id);
    const explicit=upper(row.type||row.competitionType||row.kind||row.mode);
    // CFB is a first-class built-in league. Legacy cached Builder rows from the
    // first v4.7.14 rollout may still say SPECIAL_EVENT, so identity wins here.
    if(id==='CFB')return 'LEAGUE';
    if(['SPECIAL_EVENT','SPECIAL EVENT','EVENT','TOURNAMENT'].includes(explicit))return 'SPECIAL_EVENT';
    // Explicit registry/builder type is authoritative. In v4.7.14 CFB carried a
    // football eventIcon plus bounded season dates, so the generic event heuristic
    // incorrectly demoted the declared LEAGUE into the Special Events menu.
    if(explicit==='LEAGUE')return 'LEAGUE';
    if(row.specialEvent===true||row.isSpecialEvent===true)return 'SPECIAL_EVENT';
    // Event Builder's eventIcon + bounded event dates remains a legacy repair
    // heuristic only when no explicit competition type was supplied.
    if(clean(row.eventIcon)&&(clean(row.startDate)||clean(row.endDate)))return 'SPECIAL_EVENT';
    return (row.custom||source==='REGISTRY')?'SPECIAL_EVENT':'LEAGUE';
  }

  function normalized(row,source=''){
    row={...(row||{})};
    const id=upper(row.id);if(!id)return null;
    const type=normalizedType(row,source);
    return {
      ...row,
      id,
      type,
      name:clean(row.name||id),
      shortName:clean(row.shortName||row.name||id),
      sportId:clean(row.sportId||'multi-sport'),
      sourceKind:upper(row.sourceKind||((row.custom||source==='REGISTRY')?'DYNAMIC':'BUILT_IN')),
      custom:row.custom===true||upper(row.sourceKind)==='DYNAMIC'||source==='BUILDER',
      frontendSource:source,
    };
  }

  function merge(builderRows=[],registryRows=[]){
    const next=new Map();

    // Retain cached dynamic rows first. Fresh backend rows overwrite them.
    for(const raw of [...state.rows.values(),...cachedRows()]){
      const row=normalized(raw,raw.frontendSource||'CACHE');
      if(row&&(row.custom||row.sourceKind==='DYNAMIC'))next.set(row.id,row);
    }

    // Registry proves backend existence/capabilities.
    for(const raw of registryRows||[]){
      const row=normalized(raw,'REGISTRY');
      if(!row)continue;
      // Built-in rows normally stay in core-model.js, but CFB was introduced via
      // the ranked-season service. Accept its registry row as frontend authority.
      if(row.sourceKind==='BUILT_IN'&&row.id!=='CFB')continue;
      next.set(row.id,{...(next.get(row.id)||{}),...row});
    }

    // Builder catalog is richer and wins for icon, configured enabled state,
    // lifecycle metadata, media sources, mainRow, etc.
    for(const raw of builderRows||[]){
      const row=normalized(raw,'BUILDER');
      if(!row)continue;
      next.set(row.id,{...(next.get(row.id)||{}),...row,frontendSource:'BUILDER'});
    }

    state.rows=next;
    if(builderRows.length||registryRows.length){
      state.lastGoodAt=Date.now();
      persist();
    }
    render();
    const snap=snapshot();
    // v5.1.19: registry updates are an explicit projection edge. Presentation
    // layers may refresh labels from canonical competition metadata without
    // polling, observing the whole document, or mutating event authority.
    try{window.dispatchEvent(new CustomEvent('sbb:competition-registry-updated',{detail:snap}));}catch(_){}
    return snap;
  }

  function visibleSpecial(row){
    if(!row||row.type!=='SPECIAL_EVENT')return false;
    if(row.frontendSource==='BUILDER')return row.enabled!==false;
    if(row.enabled!==false)return true;

    // Pre-v4.7 registry enrollment used lifecycle/main-row eligibility as
    // "enabled". Completed/upcoming persisted special events must still remain
    // visible in the Special Events dropdown.
    return row.custom===true && lifecycle(row)!=='ACTIVE';
  }

  function visibleLeague(row){
    return !!row&&row.type==='LEAGUE'&&row.enabled!==false&&(row.id==='CFB'||row.custom||row.sourceKind==='DYNAMIC');
  }

  function competitionMap(){
    return Object.fromEntries([...state.rows.entries()].map(([id,row])=>[id,{...row}]));
  }

  function snapshot(){
    const rows=[...state.rows.values()];
    return {
      version:VERSION,
      competitions:rows.map(x=>({...x})),
      specialEvents:rows.filter(visibleSpecial).map(x=>x.id),
      dynamicLeagues:rows.filter(visibleLeague).map(x=>x.id),
      lastGoodAt:state.lastGoodAt,
      lastRefreshAt:state.lastRefreshAt,
      errors:[...state.errors],
    };
  }

  async function json(path,timeoutMs=2500){
    const controller=typeof AbortController!=='undefined'?new AbortController():null;
    const timer=controller?setTimeout(()=>controller.abort(),timeoutMs):null;
    try{
      const r=await fetch(window.SBB_API?.url?window.SBB_API.url(path):path,{
        cache:'no-store',
        signal:controller?.signal
      });
      if(!r.ok)throw new Error(`${path} HTTP ${r.status}`);
      return await r.json();
    }finally{
      if(timer)clearTimeout(timer);
    }
  }

  async function refresh({force=false}={}){
    if(state.refreshPromise&&!force)return state.refreshPromise;
    state.refreshPromise=(async()=>{
      const results=await Promise.allSettled([
        json(`/api/competition-builder/catalog?_=${Date.now()}`),
        json(`/api/competition-registry?_=${Date.now()}`),
      ]);
      const errors=[];
      let builderRows=[],registryRows=[];
      if(results[0].status==='fulfilled')builderRows=results[0].value?.competitions||[];
      else errors.push(`builder: ${results[0].reason?.message||results[0].reason}`);
      if(results[1].status==='fulfilled')registryRows=results[1].value?.competitions||[];
      else errors.push(`registry: ${results[1].reason?.message||results[1].reason}`);
      state.errors=errors;
      state.lastRefreshAt=Date.now();

      // Never erase the last good projection because one/both reads failed.
      if(results.some(x=>x.status==='fulfilled'))merge(builderRows,registryRows);
      else render();

      return snapshot();
    })().finally(()=>{state.refreshPromise=null;});
    return state.refreshPromise;
  }

  function escapeHtml(value){
    return clean(value).replace(/[&<>"']/g,ch=>({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[ch]));
  }

  async function select(row){
    if(!row?.id)return;
    const id=upper(row.id);
    let date=browseDate();
    if(row.type==='SPECIAL_EVENT'){
      if(row.startDate&&date<row.startDate)date=row.startDate;
      if(row.endDate&&date>row.endDate)date=row.endDate;
    }

    try{window.scoreRibbonLeagueFilter=id;}catch(_){}
    document.querySelectorAll('#scoreFilters [data-score-filter]').forEach(btn=>{
      btn.classList.toggle('active',upper(btn.dataset.scoreFilter)===id);
    });

    const special=document.getElementById('sbbSpecialEventsBtn');
    if(special){
      special.classList.toggle('active',row.type==='SPECIAL_EVENT');
      special.setAttribute('aria-expanded','false');
    }
    document.getElementById('sbbSpecialEventsMenu')?.classList.add('hidden');

    try{window.scoreRibbonInteractionUntil=Date.now()+10000;}catch(_){}

    try{
      const current=browseDate();
      if(date&&date!==current&&typeof window.setScoreBrowseDate==='function'){
        await window.setScoreBrowseDate(date,{animate:true,hold:10000,load:false});
      }
    }catch(_){}

    // First paint comes from Day State / existing ribbon paths. Builder hydration
    // is recovery/freshness work and must not block the interaction.
    try{window.SBB_DAY_STATE?.load?.(date,{timeoutMs:650}).catch(()=>{});}catch(_){}
    try{window.SBB_COMPETITION_BUILDER?.loadDate?.(date,{force:true}).catch(()=>{});}catch(_){}
    try{if(typeof window.renderScoresFromMatchesCombined==='function')window.renderScoresFromMatchesCombined(true);}catch(_){}
    try{if(typeof window.updateScoreDayPager==='function')window.updateScoreDayPager();}catch(_){}
  }

  function injectStyle(){
    if(document.getElementById('sbbFrontendRegistryStyle'))return;
    const style=document.createElement('style');
    style.id='sbbFrontendRegistryStyle';
    style.textContent=`
      .sbb-v471-registry-source{opacity:.5;font-size:8px}
      .sbb-v471-registry-dynamic{position:relative}
      #sbbSpecialEventsWrap.sbb-v472-restored{display:inline-flex!important;position:relative!important}
      #sbbSpecialEventsMenu{position:fixed!important;z-index:25000!important}
      #sbbSpecialEventsMenu.hidden{display:none!important}
      #scoreFilters>.sbb-v472-registry-competition.sbb-special-main-row-suppressed{display:none!important}
    `;
    document.head.appendChild(style);
  }

  function bindSpecialToggle(){
    const btn=document.getElementById('sbbSpecialEventsBtn');
    const menu=document.getElementById('sbbSpecialEventsMenu');
    if(!btn||!menu||btn.dataset.sbbV471Bound==='1')return;
    btn.dataset.sbbV471Bound='1';
    btn.addEventListener('click',ev=>{
      ev.stopPropagation();
      const hidden=menu.classList.toggle('hidden');
      btn.setAttribute('aria-expanded',hidden?'false':'true');
      try{
        const r=btn.getBoundingClientRect(),width=Math.min(420,Math.max(280,r.width+110));
        menu.style.left=`${Math.max(8,Math.min(innerWidth-width-8,r.left))}px`;
        menu.style.top=`${Math.round(r.bottom+6)}px`;
        menu.style.width=`${Math.round(width)}px`;
      }catch(_){}
    });
  }

  function renderSpecials(){
    const wrap=document.getElementById('sbbSpecialEventsWrap');
    const btn=document.getElementById('sbbSpecialEventsBtn');
    const menu=document.getElementById('sbbSpecialEventsMenu');
    if(!wrap||!btn||!menu)return;

    const specials=[...state.rows.values()]
      .filter(visibleSpecial)
      .sort((a,b)=>{
        const aa=lifecycle(a,browseDate())==='ACTIVE'?0:lifecycle(a)==='UPCOMING'?1:2;
        const bb=lifecycle(b,browseDate())==='ACTIVE'?0:lifecycle(b)==='UPCOMING'?1:2;
        return aa-bb||(b.startDate||'').localeCompare(a.startDate||'');
      });

    if(!specials.length){
      // Do not hide a menu already populated by Competition Builder merely because
      // this projection has not received a successful backend snapshot yet.
      if(!state.lastGoodAt)return;
      const emptyKey='EMPTY';
      if(state.specialRenderKey!==emptyKey){
        state.specialRenderKey=emptyKey;
        wrap.classList.add('hidden');
        wrap.classList.remove('sbb-v472-restored');
        menu.innerHTML='';
      }
      return;
    }

    const selected=upper(window.scoreRibbonLeagueFilter||'');
    const renderKey=JSON.stringify({
      date:browseDate(),
      selected,
      rows:specials.map(row=>[
        row.id,row.shortName||row.name,row.name,row.eventIcon||row.icon||'🏆',
        row.startDate||'',row.endDate||'',row.enabled!==false
      ])
    });

    wrap.classList.remove('hidden');
    wrap.classList.add('sbb-v472-restored');
    btn.textContent='SPECIAL EVENTS ▾';
    bindSpecialToggle();

    // Avoid rewriting the same menu on every 5-second registry refresh.
    if(state.specialRenderKey===renderKey){
      menu.querySelectorAll('[data-special-competition]').forEach(button=>{
        button.classList.toggle('selected',upper(button.dataset.specialCompetition)===selected);
      });
      return;
    }
    state.specialRenderKey=renderKey;

    menu.innerHTML='';
    for(const row of specials){
      const active=lifecycle(row,browseDate())==='ACTIVE';
      const button=document.createElement('button');
      button.type='button';
      button.dataset.specialCompetition=row.id;
      button.dataset.v471Registry='1';
      button.setAttribute('role','menuitem');
      const icon=escapeHtml(row.eventIcon||row.icon||'🏆');
      const status=active?'ACTIVE':lifecycle(row);
      button.innerHTML=`<span class="sbb-special-event-icon" aria-hidden="true">${icon}</span>
        <span class="sbb-special-event-copy"><strong>${escapeHtml(row.shortName||row.name)}</strong><small>${escapeHtml(row.name)}</small></span>
        <span class="sbb-special-event-status ${active?'active':''}">${status}</span>`;
      try{button.classList.toggle('selected',upper(window.scoreRibbonLeagueFilter)===row.id);}catch(_){}
      button.addEventListener('click',ev=>{ev.stopPropagation();select(row);});
      menu.appendChild(button);
    }
  }

  function renderDynamicLeagues(){
    const host=document.getElementById('scoreFilters');if(!host)return;
    const specials=new Set([...state.rows.values()].filter(visibleSpecial).map(row=>upper(row.id)).filter(id=>id!=='CFB'));
    [...host.children].forEach(child=>{
      const id=upper(child?.dataset?.scoreFilter);
      if(id&&specials.has(id))child.classList.add('sbb-special-main-row-suppressed');
    });
    const rows=[...state.rows.values()].filter(visibleLeague).filter(row=>!specials.has(upper(row.id)));
    const renderKey=JSON.stringify(rows.map(row=>[row.id,row.shortName||row.id,row.name,row.enabled!==false]));
    if(state.leagueRenderKey===renderKey)return;
    state.leagueRenderKey=renderKey;

    host.querySelectorAll('.sbb-v472-registry-competition').forEach(x=>x.remove());
    for(const row of rows){
      const esc=(window.CSS&&typeof window.CSS.escape==="function")?window.CSS.escape(row.id):row.id.replace(/"/g,"\\\"");
      // Never duplicate a built-in / Competition Builder-owned button.
      if(host.querySelector(`[data-score-filter="${esc}"]:not(.sbb-v472-registry-competition)`))continue;
      const button=document.createElement('button');
      button.type='button';
      button.className='sbb-dynamic-competition sbb-v472-registry-competition';
      button.dataset.scoreFilter=row.id;
      button.textContent=row.shortName||row.id;
      button.title=row.name;
      button.addEventListener('click',()=>select(row));
      // Dynamic LEAGUE buttons belong after the built-in league buttons. The
      // Special Events control lives near ALL at the start of the row, so inserting
      // before that anchor incorrectly placed CFB inside the event-side controls.
      host.appendChild(button);
    }
  }

  function ensureDevCard(){
    if(document.getElementById('sbbCompetitionBuilderCard'))return true;
    const builder=window.SBB_COMPETITION_BUILDER;
    if(!builder?.openLeague||!builder?.openSpecialEvent)return !!document.getElementById('sbbCompetitionBuilderLazyCard');
    const anchor=document.querySelector('.milestone-launch-card')||document.querySelector('.settings-card:last-of-type');
    if(!anchor)return false;

    const card=document.createElement('div');
    card.id='sbbCompetitionBuilderCard';
    card.className='settings-card sbb-builder-launch-card hidden';
    card.innerHTML=`<div class="settings-card-title">COMPETITION BUILDER</div>
      <div class="history-audit-launch-copy"><strong>Add data-driven leagues and special events</strong>
      <small>Backend-registered schedules, Day State, Game Center and media sources.</small></div>
      <div class="sbb-builder-launch-actions">
        <button id="sbbAddLeagueBtn" class="settings-save-btn" type="button">ADD LEAGUE</button>
        <button id="sbbAddSpecialEventBtn" class="settings-save-btn" type="button">ADD SPECIAL EVENT</button>
      </div>
      <div id="sbbCompetitionList" class="sbb-builder-competition-list"></div>`;
    anchor.after(card);
    document.getElementById('sbbAddLeagueBtn').onclick=()=>builder.openLeague();
    document.getElementById('sbbAddSpecialEventBtn').onclick=()=>builder.openSpecialEvent();

    const apply=()=>card.classList.toggle('hidden',!window.SBB_DEV_MODE?.isEnabled?.());
    apply();
    window.addEventListener('sbb:dev-mode',apply);
    try{builder.refresh?.();}catch(_){}
    return true;
  }

  function render(){
    if(state.rendering)return;
    state.rendering=true;
    try{
      injectStyle();
      renderSpecials();
      renderDynamicLeagues();
      ensureDevCard();
    }finally{
      state.rendering=false;
    }
  }

  function boot(){
    // Paint last-known dynamic competition metadata before waiting on either API.
    // IMPORTANT: do not observe the whole document and call render() from DOM
    // mutations. render() itself changes the Special Events DOM, so that pattern
    // creates a recursive MutationObserver/render loop that can starve the main
    // thread before the launch button becomes interactive.
    merge([],[]);
    refresh().catch(()=>{});
    window.addEventListener('focus',()=>refresh({force:true}).catch(()=>{}));
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh({force:true}).catch(()=>{});});
    setInterval(()=>refresh().catch(()=>{}),30000);

    // Settings is created lazily. This narrow timer is enough to install the Dev
    // card without watching unrelated DOM mutations anywhere else on the page.
    setInterval(()=>{if(window.SBB_COMPETITION_BUILDER)ensureDevCard();},5000);
  }

  window.SBB_FRONTEND_REGISTRY=Object.freeze({
    version:VERSION,
    refresh,
    competitionMap,
    snapshot,
    select:id=>select(state.rows.get(upper(id))),
  });

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();

/* Sports Big Board v4.7.4 — Day State client + operator views.
   The backend owns the day. The browser renders a precomputed read model and keeps
   legacy provider paths as recovery/freshness fallbacks rather than first-paint work.
*/
(() => {
  'use strict';
  if (window.SBB_DAY_STATE?.version === '4.7.4') return;

  const clean=v=>String(v??'').trim();
  const day=v=>clean(v).slice(0,10);
  const api=path=>window.SBB_API?.url?window.SBB_API.url(path):path;
  const state={cache:new Map(),inflight:new Map(),lastError:'',lastRendered:''};

  async function json(path,options={},timeoutMs=1200){
    const controller=typeof AbortController!=='undefined'?new AbortController():null;
    const externalSignal=options?.signal;
    const timer=controller&&timeoutMs>0?setTimeout(()=>controller.abort(),timeoutMs):null;
    try{
      const r=await fetch(api(path),{
        cache:'no-store',
        ...options,
        signal:externalSignal||(controller?.signal)
      });
      const p=await r.json().catch(()=>({}));
      if(!r.ok&&r.status!==202)throw new Error(p?.message||p?.error||`HTTP ${r.status}`);
      if(p?.ok===false)throw new Error(p?.message||p?.error||`HTTP ${r.status}`);
      return p;
    }finally{
      if(timer)clearTimeout(timer);
    }
  }

  function apply(payload){
    const date=day(payload?.date);
    if(!date||payload?.pending||(!payload?.scoreRowsByLeague&&!payload?.eventPlans))return 0;
    let count=0;
    const rows=payload?.scoreRowsByLeague||{};
    if(typeof storeScoreDateLeague==='function'){
      for(const [league,games] of Object.entries(rows)){
        if(!Array.isArray(games))continue;
        storeScoreDateLeague(String(league).toUpperCase(),date,games);count+=games.length;
      }
    }
    if(typeof ingestCompactCatalogPlans==='function')ingestCompactCatalogPlans(payload,date);
    state.cache.set(date,payload);state.lastRendered=date;
    if(typeof scoreBrowseDate!=='undefined'&&scoreBrowseDate===date&&typeof renderScoresFromMatchesCombined==='function'){
      renderScoresFromMatchesCombined(false);
    }
    return count;
  }

  async function load(date,{force=false,timeoutMs=700}={}){
    date=day(date);if(!date)return null;
    if(!force&&state.inflight.has(date))return state.inflight.get(date);
    const promise=json(`/api/day-state?date=${encodeURIComponent(date)}`,{},timeoutMs)
      .then(payload=>{
        state.lastError='';
        if(payload?.pending)return null;
        apply(payload);
        return payload;
      })
      .catch(err=>{state.lastError=String(err?.message||err);throw err;})
      .finally(()=>state.inflight.delete(date));
    state.inflight.set(date,promise);
    return promise;
  }

  async function rebuild(date){
    date=day(date);if(!date)return null;
    const payload=await json('/api/day-state/rebuild',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({date})
    });
    const snapshot=payload?.snapshot||payload;apply(snapshot);return snapshot;
  }

  // Historical media hardening calls this global after the normal score-date
  // loader. Replace only the compact catalog hydration step with Day State so
  // score rows + media plans are one backend read model.
  if(typeof hydrateHistoricalRibbonFromCatalog==='function'&&!hydrateHistoricalRibbonFromCatalog.__sbbDayState){
    const fallback=hydrateHistoricalRibbonFromCatalog;
    const wrapped=async function(date){
      try{
        const payload=await load(date,{timeoutMs:650});
        if(payload){
          return {ok:true,games:Number(payload?.scoreGameCount||0),dayState:true};
        }
      }catch(_){}
      // Cold, pending, timed-out, or unavailable Day State must never hold the
      // ribbon hostage. Use the established historical ribbon loader immediately.
      return fallback(date);
    };
    wrapped.__sbbDayState=true;wrapped.__sbbFallback=fallback;
    hydrateHistoricalRibbonFromCatalog=wrapped;
  }

  // Prepaint every selected date from Day State in parallel with existing loader
  // logic. Existing provider/discovery code stays as a recovery path.
  if(typeof setScoreBrowseDate==='function'&&!setScoreBrowseDate.__sbbDayState){
    const original=setScoreBrowseDate;
    const wrapped=function(value,options={}){
      const date=day(value||((typeof localDateISO==='function')?localDateISO(0):''));
      if(date)load(date).catch(()=>{});
      return original(value,options);
    };
    wrapped.__sbbDayState=true;wrapped.__sbbOriginal=original;
    setScoreBrowseDate=wrapped;
  }

  function injectStyle(){
    if(document.getElementById('sbbDayStateStyle'))return;
    const style=document.createElement('style');style.id='sbbDayStateStyle';
    style.textContent=`
      #historyAuditModal.sbb-platform-view .history-game-only,
      #historyAuditModal.sbb-platform-view .history-playlists-only,
      #historyAuditModal.sbb-platform-view .history-statistics-only,
      #historyAuditModal.sbb-platform-view .history-silver-only,
      #historyAuditModal.sbb-platform-view .history-search-console,
      #historyAuditModal.sbb-platform-view .history-recovery-controls{display:none!important}
      .sbb-platform-pane{padding:10px 14px 18px;min-height:300px}
      .sbb-platform-pane.history-audit-pane-hidden{display:none!important}
      .sbb-platform-toolbar{display:flex;gap:8px;align-items:end;flex-wrap:wrap;margin-bottom:10px}
      .sbb-platform-toolbar label{display:flex;flex-direction:column;gap:4px;font-size:9px}
      .sbb-platform-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:7px;margin:9px 0}
      .sbb-platform-summary div{padding:9px;border:1px solid rgba(255,255,255,.1);border-radius:8px}
      .sbb-platform-summary span{display:block;font-size:8px;opacity:.6}.sbb-platform-summary strong{font-size:14px}
      .sbb-platform-table{width:100%;border-collapse:collapse;font-size:10px}.sbb-platform-table th,.sbb-platform-table td{padding:7px;border-bottom:1px solid rgba(255,255,255,.08);text-align:left}
      .sbb-platform-ok{color:#8fe3a2}.sbb-platform-off{opacity:.45}.sbb-platform-note{font-size:9px;opacity:.65;margin:6px 0}
    `;
    document.head.appendChild(style);
  }

  function ensureOperatorViews(){
    const tabs=document.querySelector('#historyAuditModal .history-audit-tabs');
    const shell=document.querySelector('#historyAuditModal .history-audit-shell');
    if(!tabs||!shell||document.getElementById('historyAuditTabDayState'))return;
    injectStyle();

    const dayTab=document.createElement('button');dayTab.id='historyAuditTabDayState';dayTab.type='button';dayTab.textContent='DAY STATE';
    const regTab=document.createElement('button');regTab.id='historyAuditTabRegistry';regTab.type='button';regTab.textContent='BACKEND REGISTRY';
    tabs.append(dayTab,regTab);

    const dayPane=document.createElement('section');dayPane.id='historyDayStatePane';dayPane.className='sbb-platform-pane history-audit-pane-hidden';
    dayPane.innerHTML=`
      <div class="sbb-platform-toolbar">
        <label><span>DATE</span><input id="historyDayStateDate" type="date"></label>
        <button id="historyDayStateRefresh" type="button">REFRESH STATE</button>
        <button id="historyDayStateRebuild" type="button">REBUILD SNAPSHOT</button>
        <span id="historyDayStateMessage" class="sbb-platform-note">Day State: waiting…</span>
      </div>
      <div id="historyDayStateSummary" class="sbb-platform-summary"></div>
      <div class="history-audit-table-wrap"><table class="sbb-platform-table"><thead><tr><th>DATE</th><th>GAMES</th><th>LIVE</th><th>FINAL</th><th>PLAYABLE</th><th>GENERATED</th><th>STATE</th></tr></thead><tbody id="historyDayStateBody"></tbody></table></div>`;
    shell.insertBefore(dayPane,shell.children[3]||null);

    const regPane=document.createElement('section');regPane.id='historyRegistryPane';regPane.className='sbb-platform-pane history-audit-pane-hidden';
    regPane.innerHTML=`
      <div id="historyRegistrySummary" class="sbb-platform-summary"></div>
      <p class="sbb-platform-note">Every row here is a backend competition. Dynamically-created leagues and special events appear here automatically and are enrolled in History + Day State without a new hard-coded league branch.</p>
      <div class="history-audit-table-wrap"><table class="sbb-platform-table"><thead><tr><th>ID</th><th>NAME</th><th>SPORT</th><th>TYPE</th><th>SOURCE</th><th>ENABLED</th><th>HISTORY</th><th>DAY STATE</th><th>SCORE PROVIDER</th></tr></thead><tbody id="historyRegistryBody"></tbody></table></div>`;
    shell.insertBefore(regPane,shell.children[4]||null);

    const modal=document.getElementById('historyAuditModal');
    const customTabs=[dayTab,regTab];
    function activate(tab,pane){
      modal.classList.add('sbb-platform-view');
      [...tabs.querySelectorAll('button')].forEach(x=>{x.classList.toggle('active',x===tab);x.setAttribute('aria-selected',x===tab?'true':'false')});
      dayPane.classList.toggle('history-audit-pane-hidden',pane!==dayPane);
      regPane.classList.toggle('history-audit-pane-hidden',pane!==regPane);
    }
    function leave(){
      modal.classList.remove('sbb-platform-view');
      dayPane.classList.add('history-audit-pane-hidden');regPane.classList.add('history-audit-pane-hidden');
      customTabs.forEach(x=>{x.classList.remove('active');x.setAttribute('aria-selected','false')});
    }
    [...tabs.querySelectorAll('button')].filter(x=>!customTabs.includes(x)).forEach(x=>x.addEventListener('click',leave,true));

    dayTab.addEventListener('click',()=>{activate(dayTab,dayPane);renderDayState();});
    regTab.addEventListener('click',()=>{activate(regTab,regPane);renderRegistry();});
    document.getElementById('historyDayStateRefresh')?.addEventListener('click',renderDayState);
    document.getElementById('historyDayStateRebuild')?.addEventListener('click',async()=>{
      const d=day(document.getElementById('historyDayStateDate')?.value);
      const m=document.getElementById('historyDayStateMessage');if(m)m.textContent='Rebuilding…';
      try{await rebuild(d);await renderDayState();}catch(err){if(m)m.textContent=`Rebuild failed: ${err?.message||err}`;}
    });
  }

  async function renderDayState(){
    const dateInput=document.getElementById('historyDayStateDate');
    if(dateInput&&!dateInput.value)dateInput.value=day((typeof scoreBrowseDate!=='undefined'&&scoreBrowseDate)||((typeof localDateISO==='function')?localDateISO(0):''));
    const selected=day(dateInput?.value);
    const message=document.getElementById('historyDayStateMessage');
    try{
      const [payload,status]=await Promise.all([load(selected,{force:true,timeoutMs:1800}),json('/api/day-state/status',{},1800)]);
      if(message)message.textContent=`Snapshot ${payload?.cache?.state||'READY'} • generated ${new Date((payload.generatedAt||0)*1000).toLocaleTimeString()}`;
      const s=payload.summary||{};
      const summary=document.getElementById('historyDayStateSummary');
      if(summary)summary.innerHTML=[
        ['GAMES',s.games],['LIVE',s.live],['FINAL',s.final],['SCHEDULED',s.scheduled],['PLAYABLE',s.playable],['COMPETITIONS',s.competitions]
      ].map(([k,v])=>`<div><span>${k}</span><strong>${Number(v||0).toLocaleString()}</strong></div>`).join('');
      const body=document.getElementById('historyDayStateBody');
      if(body)body.innerHTML=(status.snapshots||[]).map(row=>{
        const fresh=Number(row.stale_after||0)>Date.now()/1000;
        return `<tr><td>${row.day}</td><td>${row.event_count}</td><td>${row.live_count}</td><td>${row.final_count}</td><td>${row.playable_count}</td><td>${row.generated_at?new Date(row.generated_at*1000).toLocaleTimeString():'—'}</td><td class="${fresh?'sbb-platform-ok':'sbb-platform-off'}">${fresh?'READY':'STALE'}</td></tr>`;
      }).join('')||'<tr><td colspan="7">No Day State snapshots yet.</td></tr>';
    }catch(err){if(message)message.textContent=`Day State unavailable: ${err?.message||err}`;}
  }

  async function renderRegistry(){
    try{
      const payload=await json('/api/competition-registry');
      const summary=document.getElementById('historyRegistrySummary');
      if(summary)summary.innerHTML=[
        ['REGISTERED',payload.total],['ENABLED',payload.enabled],['BUILT-IN',payload.builtIn],['DYNAMIC',payload.dynamic],['REVISION',payload.revision]
      ].map(([k,v])=>`<div><span>${k}</span><strong>${Number(v||0).toLocaleString()}</strong></div>`).join('');
      const body=document.getElementById('historyRegistryBody');
      if(body)body.innerHTML=(payload.competitions||[]).map(row=>`<tr>
        <td><strong>${row.id}</strong></td><td>${row.name||''}</td><td>${row.sportId||''}</td><td>${row.type||''}</td><td>${row.sourceKind||''}</td>
        <td class="${row.enabled?'sbb-platform-ok':'sbb-platform-off'}">${row.enabled?'YES':'NO'}</td>
        <td class="${row.historyEnrolled?'sbb-platform-ok':'sbb-platform-off'}">${row.historyEnrolled?'YES':'NO'}</td>
        <td class="${row.dayStateEnrolled?'sbb-platform-ok':'sbb-platform-off'}">${row.dayStateEnrolled?'YES':'NO'}</td>
        <td>${row.scoreProvider||'—'}</td></tr>`).join('');
    }catch(err){
      const body=document.getElementById('historyRegistryBody');if(body)body.innerHTML=`<tr><td colspan="9">Registry unavailable: ${err?.message||err}</td></tr>`;
    }
  }

  function boot(){
    ensureOperatorViews();
    // Settings / Historical Database Audit can be created lazily. A narrow retry
    // is sufficient; observing every DOM mutation on the entire application is not.
    const operatorTimer=setInterval(()=>{
      ensureOperatorViews();
      if(document.getElementById('historyAuditTabDayState'))clearInterval(operatorTimer);
    },1500);
    setTimeout(()=>clearInterval(operatorTimer),15000);
    window.addEventListener('focus',ensureOperatorViews);
    const initial=day((typeof scoreBrowseDate!=='undefined'&&scoreBrowseDate)||((typeof localDateISO==='function')?localDateISO(0):''));
    if(initial)load(initial).catch(()=>{});
  }

  window.SBB_DAY_STATE=Object.freeze({
    version:'4.7.4',load,rebuild,apply,
    status:()=>json('/api/day-state/status'),
    registry:()=>json('/api/competition-registry'),
    cache:date=>state.cache.get(day(date))||null,
    state
  });
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();

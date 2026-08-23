/* Sports Big Board v3.0.7 historical database audit view. */
(() => {
  const $ = id => document.getElementById(id);
  const FRONTEND_VERSION='3.0.7';
  const state={offset:0,limit:100,total:0,loading:false,lastPayload:null,autoTimer:null,consoleTimer:null,consoleLoading:false};
  const tierLabel=t=>t==='extended'?'PURPLE':String(t||'none').toUpperCase();
  const fmtDate=s=>{
    if(!s)return '—';
    try{return new Date(`${s}T12:00:00`).toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'});}catch(_){return s;}
  };
  const fmtDur=seconds=>{
    const n=Number(seconds||0); if(!n)return '';
    const m=Math.floor(n/60), s=Math.floor(n%60); return `${m}:${String(s).padStart(2,'0')}`;
  };
  const esc=s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  function queryParams(includePaging=true){
    const p=new URLSearchParams();
    const values={dateFrom:$('historyAuditDateFrom')?.value||'',dateTo:$('historyAuditDateTo')?.value||'',league:$('historyAuditLeague')?.value||'',bestTier:$('historyAuditBestTier')?.value||'',status:$('historyAuditStatus')?.value||'',q:$('historyAuditSearch')?.value||''};
    for(const [k,v] of Object.entries(values))if(v)p.set(k,v);
    if(includePaging){p.set('limit',String(state.limit));p.set('offset',String(state.offset));}
    return p;
  }
  function mediaCell(items,tier){
    items=(items||[]).slice().sort((a,b)=>(Number(b.verified)-Number(a.verified))||(Number(b.runtimeSuccessAt||0)-Number(a.runtimeSuccessAt||0))||(Number(b.verifiedAt||0)-Number(a.verifiedAt||0)));
    if(!items.length)return '<span class="audit-empty">—</span>';
    const shown=items.slice(0,2).map(item=>{
      const title=esc(item.title||'Media'); const dur=fmtDur(item.durationSeconds); const provider=esc(item.provider||item.source||'');
      const cls=item.verified?'verified':(item.runtimeState==='FAILED'?'failed':'candidate');
      const label=`${dur?dur+' • ':''}${provider||tierLabel(tier)}`;
      if(item.url)return `<a class="audit-media-link ${cls}" href="${esc(item.url)}" target="_blank" rel="noopener" title="${title}"><strong>${title}</strong><small>${esc(label)}</small></a>`;
      return `<span class="audit-media-link ${cls}" title="${title}"><strong>${title}</strong><small>${esc(label)}</small></span>`;
    }).join('');
    return shown+(items.length>2?`<span class="audit-more">+${items.length-2} more</span>`:'');
  }
  function renderSummary(summary={}){
    const t=summary.tiers||{}, b=summary.best||{}, st=summary.effectiveStatuses||{};
    const map={historyAuditGames:summary.games||0,historyAuditVerified:summary.verifiedAssets||0,historyAuditGold:t.gold||0,historyAuditGreen:t.green||0,historyAuditPurple:t.extended||0,historyAuditBlue:t.blue||0,historyAuditUpgrade:summary.upgradePendingGames||0};
    for(const [id,val] of Object.entries(map)){const el=$(id);if(el)el.textContent=Number(val).toLocaleString();}
    const best=$('historyAuditBestSummary');
    if(best)best.textContent=`Best per game: ${Number(b.gold||0).toLocaleString()} Gold • ${Number(b.green||0).toLocaleString()} Green • ${Number(b.extended||0).toLocaleString()} Purple • ${Number(b.blue||0).toLocaleString()} Blue • ${Number(b.none||0).toLocaleString()} none`;
    const status=$('historyAuditStatusSummary');
    if(status)status.textContent=`Status projection: ${Number(st.PENDING_INDEX||0).toLocaleString()} Pending Index • ${Number(st.UPGRADE_PENDING||0).toLocaleString()} Upgrade Pending • ${Number(st.PARTIAL||0).toLocaleString()} Partial • ${Number(st.QUALITY_COMPLETE||0).toLocaleString()} Quality Complete • ${Number(summary.noVerifiedMediaGames||0).toLocaleString()} without verified media`;
    const coverage=$('historyAuditGreenCoverageSummary');
    if(coverage){
      const by=summary.greenCoverageByLeague||{}; const games=Number(summary.games||0), green=Number(summary.greenCoverageGames||0);
      const pct=games?((green/games)*100).toFixed(1):'0.0';
      const leagues=['MLB','NFL','NBA','NHL','EPL','MLS'].filter(l=>by[l]).map(l=>{const x=by[l]||{},g=Number(x.games||0),q=Number(x.greenGames||0);return `${l} ${q}/${g}${g?` (${((q/g)*100).toFixed(0)}%)`:''}`;});
      coverage.textContent=`Quick recap coverage: ${green.toLocaleString()}/${games.toLocaleString()} games (${pct}%)${leagues.length?' • '+leagues.join(' • '):''}`;
    }
  }
  function renderRows(payload){
    const body=$('historyAuditTableBody'); if(!body)return;
    const rows=payload.rows||[];
    if(!rows.length){body.innerHTML='<tr><td colspan="9" class="audit-no-results">No games match these filters.</td></tr>';return;}
    body.innerHTML=rows.map(row=>{
      const tiers=row.tiers||{}; const best=row.bestTier||'none';
      const effective=String(row.effectiveStatus||'PENDING_INDEX');
      const status=effective.replaceAll('_',' ');
      const statusDetail=row.discoveryPending
        ? `Discovery v${Number(row.currentDiscoveryVersion||0)} pass pending${row.bestTier&&row.bestTier!=='none'?' • media already known':''}`
        : (row.nextRetryAt?`Retry ${new Date(row.nextRetryAt*1000).toLocaleString()}`:(row.lastError?String(row.lastError).slice(0,90):''));
      return `<tr>
        <td class="audit-date">${esc(fmtDate(row.date))}</td>
        <td><span class="audit-league">${esc(row.league)}</span></td>
        <td class="audit-game"><strong>${esc(row.game)}</strong><small>${esc(row.eventId)}</small></td>
        <td class="audit-tier-cell gold">${mediaCell(tiers.gold,'gold')}</td>
        <td class="audit-tier-cell green">${mediaCell(tiers.green,'green')}</td>
        <td class="audit-tier-cell purple">${mediaCell(tiers.extended,'extended')}</td>
        <td class="audit-tier-cell blue">${mediaCell(tiers.blue,'blue')}</td>
        <td><span class="audit-best tier-${esc(best)}">${esc(tierLabel(best))}</span></td>
        <td class="audit-status status-${esc(effective.toLowerCase().replaceAll('_','-'))}" title="Raw state: ${esc(row.discoveryState||'UNKNOWN')} • stored discovery v${Number(row.discoveryVersion||0)}"><strong>${esc(status)}</strong>${statusDetail?`<small>${esc(statusDetail)}</small>`:''}</td>
      </tr>`;
    }).join('');
  }
  function updatePager(){
    const from=state.total?state.offset+1:0, to=Math.min(state.total,state.offset+state.limit);
    const el=$('historyAuditPageLabel');if(el)el.textContent=`${from.toLocaleString()}–${to.toLocaleString()} of ${state.total.toLocaleString()} games`;
    const prev=$('historyAuditPrev'); if(prev)prev.disabled=state.offset<=0;
    const next=$('historyAuditNext'); if(next)next.disabled=state.offset+state.limit>=state.total;
  }
  function consoleSet(id,text){const el=$(id);if(el)el.textContent=text;}
  function ageText(n){n=Number(n);if(!Number.isFinite(n))return 'no heartbeat';if(n<60)return `${Math.max(0,Math.round(n))}s ago`;if(n<3600)return `${Math.round(n/60)}m ago`;return `${Math.round(n/3600)}h ago`;}
  function consoleTime(ts){if(!ts)return '--:--:--';try{return new Date(Number(ts)*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});}catch(_){return '--:--:--';}}
  function renderConsole(data){
    const head=document.querySelector('.history-search-console-head'); if(head)head.classList.remove('mismatch','problem');
    const backend=String(data.version||'UNKNOWN'); const discovery=Number(data.historyDiscoveryVersion||0); const versionOk=backend===FRONTEND_VERSION;
    consoleSet('historySearchConsoleVersion',`Frontend v${FRONTEND_VERSION} • Backend v${backend} • Discovery v${discovery}`);
    const threads=data.threads||[]; const allThreads=threads.length&&threads.every(x=>x.alive);
    const gw=(data.workers||{})['green-gap']||{}; const queue=data.greenGapQueue||{}; const bg=data.background||{};
    const search=(data.youtubeGateway||{}).search||{}; const budget=data.youtubeSearchBudget||{};
    const problems=[...(data.problems||[])];
    if(!versionOk)problems.unshift(`RELEASE MISMATCH: frontend v${FRONTEND_VERSION} but backend v${backend}`);
    if(discovery<11)problems.unshift(`DISCOVERY MISMATCH: expected v11 but backend reports v${discovery||'?'}`);
    const healthy=versionOk&&discovery>=11&&allThreads&&gw.healthy&&!problems.filter(x=>/thread|heartbeat|mismatch/i.test(x)).length;
    consoleSet('historySearchConsoleOverall',healthy?'RUNNING':(versionOk?'ISSUE DETECTED':'BACKEND VERSION MISMATCH'));
    if(head){if(!versionOk||discovery<11)head.classList.add('mismatch');else if(problems.length)head.classList.add('problem');}
    consoleSet('historySearchConsoleWorker',`${String(gw.phase||'unknown').replaceAll(':',' / ')} • ${ageText(gw.heartbeatAgeSeconds)}`);
    consoleSet('historySearchConsoleQueue',`${Number(queue.due_now||0).toLocaleString()} due / ${Number(queue.gaps||0).toLocaleString()} gaps`);
    consoleSet('historySearchConsoleBackground',bg.canWork?'ACTIVE':`PAUSED • ${String(bg.pauseReason||'unknown').replaceAll('-',' ')}`);
    consoleSet('historySearchConsoleYoutube',Number(search.cooldownSeconds||0)>0?`COOLDOWN ${Number(search.cooldownSeconds)}s`:'AVAILABLE');
    const used=Number(budget.used||0), limit=Number(budget.limit||budget.budget||0); consoleSet('historySearchConsoleBudget',limit?`${used}/${limit} today`:`${used} used`);
    const p=$('historySearchConsoleProblems'); if(p){if(problems.length){p.classList.remove('hidden');p.textContent=problems.join(' • ');}else{p.classList.add('hidden');p.textContent='';}}
    const out=$('historySearchConsoleOutput'); if(out){
      const g=data.greenGap||{}; const back=data.backfill||{};
      const header=[
        `[STATE] server uptime ${Math.round(Number(data.uptimeSeconds||0)/60)}m • workers ${allThreads?'alive':'CHECK THREADS'} • green attempts ${Number(g.attempts||0)} • green upgrades ${Number(g.upgradedToGreen||0)}`,
        `[QUEUE] total gaps ${Number(queue.gaps||0)} • due ${Number(queue.due_now||0)} • blue-only ${Number(queue.blue_only||0)} • no-media ${Number(queue.no_media||0)} • purple-only ${Number(queue.purple_only||0)} • stale-v ${Number(queue.stale_version||0)}`,
        `[GREEN] ${g.current?`NOW ${g.current}`:(g.lastDate?`LAST ${g.lastDate} ${g.lastLeague||''} ${String(g.lastBestTier||'none').toUpperCase()}→${String(g.lastResultTier||'none').toUpperCase()}`:'no completed attempt yet')}`,
        `[BACKFILL] ${back.lastDate?`last ${back.lastDate} • deep games ${Number(back.deepGames||0)}`:'waiting for first pass'}`,
        `[YOUTUBE] search ${Number(search.cooldownSeconds||0)>0?'COOLDOWN':'OK'}${search.lastError?' • '+String(search.lastError).slice(0,190):''}`,
      ];
      const lines=(data.recent||[]).map(row=>`[${consoleTime(row.at)}] [${String(row.worker||'history')}] ${String(row.level||'INFO')} ${String(row.message||'')}`);
      out.textContent=[...header,'',...lines].join('\n'); out.scrollTop=out.scrollHeight;
    }
  }
  async function loadConsole(){
    if(state.consoleLoading)return; state.consoleLoading=true;
    try{
      const r=await fetch('/api/history/worker-console?limit=180',{cache:'no-store'});
      let data={}; try{data=await r.json();}catch(_){data={};}
      if(!r.ok||!data.ok){
        const backend=data.version||'unknown'; const msg=r.status===404?`Search Console endpoint missing. The live backend is probably older than frontend v${FRONTEND_VERSION}.`:(data.message||data.error||`HTTP ${r.status}`);
        const head=document.querySelector('.history-search-console-head'); if(head)head.classList.add('mismatch');
        consoleSet('historySearchConsoleOverall','BACKEND CHECK FAILED');consoleSet('historySearchConsoleVersion',`Frontend v${FRONTEND_VERSION} • backend ${backend}`);
        const out=$('historySearchConsoleOutput');if(out)out.textContent=`[ERROR] ${msg}\n\nOpen /api/status or check GitHub Actions backend deployment. The v3.0.7 workflow now refuses to publish Pages unless the public backend reports the same release version.`;
        return;
      }
      renderConsole(data);
    }catch(err){
      const head=document.querySelector('.history-search-console-head');if(head)head.classList.add('problem');consoleSet('historySearchConsoleOverall','CONNECTION ERROR');
      const out=$('historySearchConsoleOutput');if(out)out.textContent=`[ERROR] Unable to read cloud search console: ${String(err?.message||err)}`;
    }finally{state.consoleLoading=false;}
  }

  async function load(reset=false){
    if(state.loading)return; if(reset)state.offset=0; state.loading=true;
    $('historyAuditLoading')?.classList.remove('hidden');
    try{
      const r=await fetch(`/api/history/audit?${queryParams(true).toString()}`,{cache:'no-store'}); const data=await r.json();
      if(!r.ok||!data.ok)throw new Error(data.message||data.error||`HTTP ${r.status}`);
      state.total=Number(data.total||0);state.lastPayload=data;renderSummary(data.summary||{});renderRows(data);updatePager();
      const msg=$('historyAuditMessage');
      if(msg){
        const bg=data.background||{}, gap=data.greenGap||{};
        const bgText=bg.canWork?'BACKGROUND SEARCH ACTIVE':`BACKGROUND PAUSED${bg.pauseReason?' • '+String(bg.pauseReason).replaceAll('-',' '):''}`;
        const gapText=gap.lastDate?` • Green queue ${gap.lastDate} ${gap.lastLeague||''} ${String(gap.lastBestTier||'none').toUpperCase()}→${String(gap.lastResultTier||'none').toUpperCase()}`:'';
        msg.textContent=`LIVE cloud catalog • auto-refresh 30s • ${Number(data.repository?.days||0).toLocaleString()} dates stored • ${bgText}${gapText}`;
      }
    }catch(err){
      const body=$('historyAuditTableBody');if(body)body.innerHTML=`<tr><td colspan="9" class="audit-no-results">Audit load failed: ${esc(err.message||err)}</td></tr>`;
    }finally{state.loading=false;$('historyAuditLoading')?.classList.add('hidden');}
  }
  function startAutoRefresh(){clearInterval(state.autoTimer);clearInterval(state.consoleTimer);state.autoTimer=setInterval(()=>{if(!$('historyAuditModal')?.classList.contains('hidden'))load(false);},30000);state.consoleTimer=setInterval(()=>{if(!$('historyAuditModal')?.classList.contains('hidden'))loadConsole();},2500);}
  function stopAutoRefresh(){clearInterval(state.autoTimer);clearInterval(state.consoleTimer);state.autoTimer=null;state.consoleTimer=null;}
  function open(){
    const modal=$('historyAuditModal');if(!modal)return;modal.classList.remove('hidden');modal.setAttribute('aria-hidden','false');document.body.classList.add('audit-open');load(true);loadConsole();startAutoRefresh();
  }
  function close(){const modal=$('historyAuditModal');if(!modal)return;modal.classList.add('hidden');modal.setAttribute('aria-hidden','true');document.body.classList.remove('audit-open');stopAutoRefresh();}
  function exportFile(ext){const url=`/api/history/audit.${ext}?${queryParams(false).toString()}`;window.location.href=window.SBB_API?.url?window.SBB_API.url(url):url;}
  let debounce=null;
  function queueLoad(){clearTimeout(debounce);debounce=setTimeout(()=>load(true),250);}
  function init(){
    $('openHistoryAuditBtn')?.addEventListener('click',open);$('historyAuditClose')?.addEventListener('click',close);$('historyAuditBackdrop')?.addEventListener('click',close);
    $('historyAuditRefresh')?.addEventListener('click',()=>{load(false);loadConsole();});$('historyAuditCsv')?.addEventListener('click',()=>exportFile('csv'));$('historyAuditXlsx')?.addEventListener('click',()=>exportFile('xlsx'));
    $('historyAuditPrev')?.addEventListener('click',()=>{state.offset=Math.max(0,state.offset-state.limit);load(false);});
    $('historyAuditNext')?.addEventListener('click',()=>{state.offset+=state.limit;load(false);});
    ['historyAuditDateFrom','historyAuditDateTo','historyAuditLeague','historyAuditBestTier','historyAuditStatus'].forEach(id=>$(id)?.addEventListener('change',()=>load(true)));
    $('historyAuditSearch')?.addEventListener('input',queueLoad);
    window.addEventListener('keydown',ev=>{if(ev.key==='Escape'&&!$('historyAuditModal')?.classList.contains('hidden'))close();});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
  window.SBB_HISTORY_AUDIT={open,refresh:()=>{load(false);loadConsole();},refreshConsole:loadConsole};
})();

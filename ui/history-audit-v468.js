/* Sports Big Board v4.6.8 — Special Event Media + Statistics integration.
   Additive operator surface over the existing History Audit:
   - dynamic league/special-event selectors
   - special-event Media Playlists groups
   - per-competition media reprocessing
   - competition coverage Statistics tab
*/
(() => {
  const $ = id => document.getElementById(id);
  const API = path => window.SBB_API?.url ? window.SBB_API.url(path) : path;
  const BUILT_INS = ['MLB','NFL','NBA','NHL','EPL','MLS'];
  const state = {
    sources:null,
    catalog:null,
    contextLoading:false,
    statisticsLoading:false,
    statisticsRows:[],
    statisticsActive:false,
    observer:null,
    refreshTimer:null,
    decorating:false,
  };

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[ch]));
  const token = value => String(value || 'unknown').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'') || 'unknown';
  const pct = (n,d) => Number(d||0) ? `${((Number(n||0)/Number(d))*100).toFixed(1)}%` : '0.0%';
  const leagueBadge = league => `<span class="audit-league league-${esc(token(league))}">${esc(String(league||'—').toUpperCase())}</span>`;

  async function jsonFetch(path, options={}) {
    const response = await fetch(API(path), {cache:'no-store', ...options});
    let data={};
    try { data=await response.json(); } catch (_) {}
    if (!response.ok || data?.ok === false) throw new Error(data?.message || data?.error || `HTTP ${response.status}`);
    return data;
  }

  async function loadContext(force=false) {
    if (state.contextLoading) return state;
    if (state.sources && state.catalog && !force) return state;
    state.contextLoading=true;
    try {
      const [sources, catalog] = await Promise.all([
        jsonFetch('/api/history/media-sources'),
        jsonFetch('/api/competition-builder/catalog').catch(()=>({ok:true,competitions:[]})),
      ]);
      state.sources=sources;
      state.catalog=catalog;
      applyDynamicLeagueOptions();
      schedulePlaylistDecoration();
      return state;
    } finally {
      state.contextLoading=false;
    }
  }

  function customMap() {
    const map={};
    for (const comp of state.catalog?.competitions || []) {
      const id=String(comp?.id||'').toUpperCase();
      if (id) map[id]=comp;
    }
    return map;
  }

  function leagueIds() {
    const seen=new Set(BUILT_INS);
    for (const row of state.sources?.rows || []) {
      const id=String(row?.league||'').toUpperCase();
      if (id) seen.add(id);
    }
    for (const comp of state.catalog?.competitions || []) {
      const id=String(comp?.id||'').toUpperCase();
      if (id) seen.add(id);
    }
    const custom=customMap();
    return [...seen].sort((a,b)=>{
      const ai=BUILT_INS.indexOf(a), bi=BUILT_INS.indexOf(b);
      if (ai>=0 || bi>=0) return (ai>=0?ai:999)-(bi>=0?bi:999);
      const ac=custom[a]||{}, bc=custom[b]||{};
      return String(ac.startDate||'9999').localeCompare(String(bc.startDate||'9999')) || a.localeCompare(b);
    });
  }

  function leagueLabel(id) {
    const comp=customMap()[id];
    if (!comp) return id;
    return String(comp.shortName || comp.name || id);
  }

  function setOptions(select, ids, {allLabel='', allValue=''}={}) {
    if (!select) return;
    const previous=select.value;
    const options=[];
    if (allLabel) options.push(`<option value="${esc(allValue)}">${esc(allLabel)}</option>`);
    for (const id of ids) options.push(`<option value="${esc(id)}">${esc(leagueLabel(id))}</option>`);
    select.innerHTML=options.join('');
    if ([...select.options].some(o=>o.value===previous)) select.value=previous;
  }

  function applyDynamicLeagueOptions() {
    const ids=leagueIds();
    setOptions($('historyMediaSourcesLeague'), ids, {allLabel:'ALL LEAGUES',allValue:''});
    setOptions($('historyMediaPlaylistLeague'), ids);
    setOptions($('historyAuditLeague'), ids, {allLabel:'ALL',allValue:''});
    setOptions($('historySilverLeague'), ids, {allLabel:'ALL',allValue:''});
    setOptions($('historyRecoveryLeague'), ids, {allLabel:'ALL LEAGUES',allValue:'ALL'});
  }

  function playlistStatsText(row) {
    const s=row?.stats||{};
    return `${Number(s.playlistItems||0)} playlist items • ${Number(s.hydrated||s.assets||0)} hydrated • ${Number(s.assets||0)} assets • ${Number(s.assigned||0)} associated • ${Number(s.orphaned||0)} orphaned${Number(s.quarantined||0)?` • ${Number(s.quarantined)} quarantined`:''}`;
  }

  function sourceRowHtml(row) {
    const custom=Boolean(row?.custom);
    const active=row?.active!==false;
    return `<tr class="${custom?'history-media-source-custom ':''}${active?'':'history-media-source-disabled'}">
      <td><span class="media-source-priority priority-${esc(token(row.priority))}">${esc(active?(row.priority||'ACTIVE'):'DISABLED')}</span></td>
      <td><span class="media-source-kind">${esc(row.kind||'SOURCE')}</span></td>
      <td>${esc(row.season||'ALL')}</td>
      <td><strong>${esc(row.objective||'GAME')}</strong></td>
      <td>${row.url?`<a class="history-media-source-link" href="${esc(row.url)}" target="_blank" rel="noopener"><strong>${esc(row.title||row.url)}</strong></a>`:`<strong>${esc(row.title||'Source')}</strong>`}<small>${esc(row.url||'')}</small></td>
      <td><strong>${esc(row.collector||'—')}</strong><small><span class="media-source-trust">${esc(row.trust||'—')}</span></small></td>
      <td>${esc(row.notes||'')}${custom?`<small class="history-media-source-stats">${esc(playlistStatsText(row))}${row.lastError?` • ERROR: ${esc(row.lastError)}`:''}</small><div class="history-media-source-actions"><button type="button" data-v468-playlist-action="crawl" data-playlist-id="${esc(row.id)}">CRAWL NOW</button><button type="button" data-v468-playlist-action="edit" data-playlist-id="${esc(row.id)}">EDIT</button><button type="button" data-v468-playlist-action="toggle" data-playlist-id="${esc(row.id)}">${active?'DISABLE':'ENABLE'}</button><button type="button" data-v468-playlist-action="delete" data-playlist-id="${esc(row.id)}">REMOVE</button></div>`:''}</td>
    </tr>`;
  }

  function specialLeagueHtml(league, rows) {
    const activePrimary=rows.filter(x=>x.priority==='PRIMARY'&&x.active!==false).length;
    return `<details class="history-media-source-league" data-v468-league="${esc(league)}" open>
      <summary>${leagueBadge(league)}<strong>${esc(leagueLabel(league))} GAME MEDIA</strong><span>${rows.length} source${rows.length===1?'':'s'} • ${activePrimary} active primary</span></summary>
      <div class="history-media-source-actions"><button type="button" data-v468-reprocess="${esc(league)}">REPROCESS MEDIA</button></div>
      <div class="history-media-source-scroll"><table class="history-media-source-table"><thead><tr><th>PRIORITY</th><th>TYPE</th><th>SEASON</th><th>OBJECTIVE</th><th>SOURCE</th><th>COLLECTOR / TRUST</th><th>NOTES / STATUS</th></tr></thead><tbody>${rows.map(sourceRowHtml).join('')}</tbody></table></div>
    </details>`;
  }

  function editPlaylist(row) {
    if (!row) return;
    const values={
      historyMediaPlaylistId:row.id||'',
      historyMediaPlaylistLeague:row.league||'MLB',
      historyMediaPlaylistUrl:row.url||row.playlistId||'',
      historyMediaPlaylistSeasonStart:row.seasonStart||'',
      historyMediaPlaylistSeasonEnd:row.seasonEnd||'',
      historyMediaPlaylistObjective:row.objectiveKey||String(row.objective||'coverage').toLowerCase(),
      historyMediaPlaylistPriority:row.priority||'PRIMARY',
    };
    for (const [id,value] of Object.entries(values)) if ($(id)) $(id).value=value;
    if ($('historyMediaPlaylistAuto')) $('historyMediaPlaylistAuto').checked=Boolean(row.autoRecrawl);
    if ($('historyMediaPlaylistSave')) $('historyMediaPlaylistSave').textContent='SAVE & RECRAWL';
    $('historyMediaPlaylistCancel')?.classList.remove('hidden');
    $('historyMediaPlaylistUrl')?.focus();
  }

  async function playlistAction(action,row) {
    if (!row?.id) return;
    if (action==='delete' && !window.confirm('Remove this playlist from future crawling? Existing discovered media will be preserved.')) return;
    const body={action,id:row.id};
    if (action==='toggle') body.enabled=row.active===false;
    await jsonFetch('/api/history/media-sources',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)
    });
    await loadContext(true);
    window.SBB_HISTORY_AUDIT?.setTab?.('playlists');
    $('historyMediaSourcesRefresh')?.click();
  }

  function attachPlaylistHandlers(root=document) {
    root.querySelectorAll('[data-v468-playlist-action]').forEach(btn=>{
      if (btn.dataset.v468Bound==='1') return;
      btn.dataset.v468Bound='1';
      btn.addEventListener('click', async ev=>{
        ev.preventDefault();ev.stopPropagation();
        const row=(state.sources?.rows||[]).find(x=>String(x.id||'')===String(btn.dataset.playlistId||''));
        try { await playlistAction(btn.dataset.v468PlaylistAction,row); }
        catch (err) { window.alert(`Playlist action failed: ${err?.message||err}`); }
      });
    });
  }

  function builtInLeagueFromDetails(details) {
    const text=String(details.querySelector('summary strong')?.textContent||'').toUpperCase();
    return BUILT_INS.find(id=>text.startsWith(id+' ')) || '';
  }

  function schedulePlaylistDecoration() {
    queueMicrotask(()=>decoratePlaylistGrid());
  }

  function decoratePlaylistGrid() {
    if (state.decorating) return;
    const grid=$('historyMediaSourcesGrid');
    if (!grid || !state.sources) return;
    state.decorating=true;
    try {
      const filter=String($('historyMediaSourcesLeague')?.value||'').toUpperCase();
      const allRows=state.sources.rows||[];
      const rows=filter?allRows.filter(x=>String(x.league||'').toUpperCase()===filter):allRows;
      const present=new Set();

      for (const details of grid.querySelectorAll('details.history-media-source-league')) {
        const league=String(details.dataset.v468League||builtInLeagueFromDetails(details)).toUpperCase();
        if (!league) continue;
        details.dataset.v468League=league;
        present.add(league);
        const summary=details.querySelector('summary');
        if (summary && !details.querySelector(':scope > .history-media-source-actions [data-v468-reprocess]')) {
          summary.insertAdjacentHTML('afterend',`<div class="history-media-source-actions"><button type="button" data-v468-reprocess="${esc(league)}">REPROCESS MEDIA</button></div>`);
        }
      }

      const grouped={};
      for (const row of rows) {
        const league=String(row.league||'').toUpperCase();
        if (!league || BUILT_INS.includes(league)) continue;
        (grouped[league]||(grouped[league]=[])).push(row);
      }
      for (const league of leagueIds()) {
        if (!grouped[league] || present.has(league)) continue;
        grid.insertAdjacentHTML('beforeend',specialLeagueHtml(league,grouped[league]));
      }

      grid.querySelectorAll('[data-v468-reprocess]').forEach(btn=>{
        if (btn.dataset.v468Bound==='1') return;
        btn.dataset.v468Bound='1';
        btn.addEventListener('click',ev=>{
          ev.preventDefault();ev.stopPropagation();
          reprocessCompetition(btn.dataset.v468Reprocess,btn);
        });
      });
      attachPlaylistHandlers(grid);
    } finally {
      state.decorating=false;
    }
  }

  async function reprocessCompetition(league, button=null) {
    league=String(league||'').toUpperCase();
    if (!league) return;
    await loadContext(false);
    const original=button?.textContent||'REPROCESS MEDIA';
    if (button) { button.disabled=true;button.textContent='REPROCESSING…'; }
    const status=$('historyMediaPlaylistStatus');
    if (status) status.textContent=`${league}: reopening source discovery and recrawling registered playlists…`;

    let crawls=0, reopened=0, repaired=0;
    const errors=[];
    try {
      // 1) Reopen the normal history/source pass for every competition. This is
      // how built-in league provider/playlist lanes become eligible again.
      try {
        const preview=await jsonFetch('/api/history/admin/recovery/preview',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({action:'source_reopen',league,startDate:'TODAY',direction:'newest',sourceKey:'',objective:''})
        });
        if (preview.confirmToken) {
          await jsonFetch('/api/history/admin/recovery/apply',{
            method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({action:'source_reopen',league,startDate:'TODAY',direction:'newest',sourceKey:'',objective:'',confirmToken:preview.confirmToken})
          });
          reopened=Number(preview.result?.newlyEligible ?? preview.result?.events ?? 0);
        }
      } catch (err) { errors.push(`source audit: ${err?.message||err}`); }

      // 2) Operator-managed playlists, including all Special Event playlists,
      // can be force-crawled directly.
      const playlists=(state.sources?.rows||[]).filter(row=>
        row.custom && row.active!==false &&
        String(row.league||'').toUpperCase()===league &&
        String(row.kind||'').toUpperCase()==='YOUTUBE PLAYLIST' && row.id
      );
      for (const row of playlists) {
        try {
          await jsonFetch('/api/history/media-sources',{
            method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({action:'crawl',id:row.id})
          });
          crawls++;
        } catch (err) { errors.push(`${row.title||row.id}: ${err?.message||err}`); }
      }

      // 3) Custom competitions have a targeted relationship-repair endpoint.
      if (customMap()[league]) {
        try {
          const health=await jsonFetch(`/api/competition-builder/health?id=${encodeURIComponent(league)}&repair=1`);
          repaired=(health.repair||[]).reduce((sum,row)=>sum+Number(row?.assigned||0),0);
        } catch (err) { errors.push(`association repair: ${err?.message||err}`); }
      }

      await loadContext(true);
      $('historyMediaSourcesRefresh')?.click();
      window.SBB_HISTORY_AUDIT?.refresh?.();
      if (state.statisticsActive) await loadStatistics(true);
      if (status) status.textContent=`${league}: reprocessing started • ${crawls} playlist crawl${crawls===1?'':'s'} • ${reopened} source-ledger event${reopened===1?'':'s'} reopened • ${repaired} immediate association${repaired===1?'':'s'} repaired${errors.length?` • ${errors.length} warning${errors.length===1?'':'s'}`:''}`;
      if (button) button.textContent='REPROCESS STARTED';
      setTimeout(()=>{if(button){button.disabled=false;button.textContent=original;}},2500);
    } catch (err) {
      if (status) status.textContent=`${league}: reprocess failed: ${err?.message||err}`;
      if (button) { button.disabled=false;button.textContent=original; }
    }
  }

  function statisticsCompetitionIds() {
    return leagueIds();
  }

  async function auditSummary(league) {
    const p=new URLSearchParams({league,limit:'1',offset:'0'});
    const data=await jsonFetch(`/api/history/audit?${p.toString()}`);
    return data.summary||{};
  }

  async function mapWithConcurrency(items, concurrency, fn) {
    const out=new Array(items.length);
    let cursor=0;
    async function worker() {
      while (true) {
        const i=cursor++;
        if (i>=items.length) return;
        try { out[i]=await fn(items[i],i); }
        catch (error) { out[i]={error:String(error?.message||error)}; }
      }
    }
    await Promise.all(Array.from({length:Math.min(concurrency,items.length||1)},worker));
    return out;
  }

  function statsMeta(league) {
    const comp=customMap()[league];
    if (!comp) return {name:league,type:'LEAGUE',lifecycle:'BUILT-IN'};
    return {
      name:String(comp.name||comp.shortName||league),
      type:String(comp.type||'LEAGUE'),
      lifecycle:String(comp.lifecycle||''),
    };
  }

  function sourceStatsFor(league) {
    const rows=(state.sources?.rows||[]).filter(x=>String(x.league||'').toUpperCase()===league);
    const playlists=rows.filter(x=>String(x.kind||'').toUpperCase()==='YOUTUBE PLAYLIST');
    const operator=playlists.filter(x=>x.custom);
    const associated=operator.reduce((n,x)=>n+Number(x.stats?.assigned||0),0);
    const orphaned=operator.reduce((n,x)=>n+Number(x.stats?.orphaned||0),0);
    return {sources:rows.length,playlists:playlists.length,operator:operator.length,associated,orphaned};
  }

  function renderStatistics(rows) {
    const body=$('historyStatisticsBody');
    const summary=$('historyStatisticsSummary');
    if (!body) return;
    const totalGames=rows.reduce((n,r)=>n+Number(r.games||0),0);
    const totalWith=rows.reduce((n,r)=>n+Number(r.anyHighlights||0),0);
    const totalNo=rows.reduce((n,r)=>n+Number(r.noMedia||0),0);
    const special=rows.filter(r=>r.type==='SPECIAL_EVENT');
    if (summary) summary.textContent=`${rows.length} competitions • ${totalGames.toLocaleString()} games • ${totalWith.toLocaleString()} with verified media (${pct(totalWith,totalGames)}) • ${totalNo.toLocaleString()} without verified media • ${special.length} special event${special.length===1?'':'s'}`;
    if (!rows.length) { body.innerHTML='<tr><td colspan="13">No competition statistics are available.</td></tr>'; return; }

    body.innerHTML=rows.map(row=>{
      if (row.error) return `<tr><td>${leagueBadge(row.league)}</td><td colspan="12">${esc(row.error)}</td></tr>`;
      return `<tr>
        <td>${leagueBadge(row.league)}<small>${esc(row.name)}</small></td>
        <td><strong>${esc(row.type==='SPECIAL_EVENT'?'SPECIAL EVENT':'LEAGUE')}</strong><small>${esc(row.lifecycle||'')}</small></td>
        <td><strong>${Number(row.games||0).toLocaleString()}</strong></td>
        <td><strong>${Number(row.anyHighlights||0).toLocaleString()}</strong><small>${pct(row.anyHighlights,row.games)}</small></td>
        <td><strong>${Number(row.noMedia||0).toLocaleString()}</strong><small>${pct(row.noMedia,row.games)}</small></td>
        <td>${Number(row.best?.gold||0).toLocaleString()}</td>
        <td>${Number(row.best?.green||0).toLocaleString()}</td>
        <td>${Number(row.best?.extended||0).toLocaleString()}</td>
        <td>${Number(row.best?.blue||0).toLocaleString()}</td>
        <td><strong>${Number(row.coverageComplete||0).toLocaleString()}</strong><small>${pct(row.coverageComplete,row.games)}</small></td>
        <td><strong>${Number(row.sourceStats?.playlists||0).toLocaleString()}</strong><small>${Number(row.sourceStats?.operator||0).toLocaleString()} operator</small></td>
        <td><strong>${Number(row.sourceStats?.associated||0).toLocaleString()}</strong><small>${Number(row.sourceStats?.orphaned||0).toLocaleString()} orphaned</small></td>
        <td><div class="history-media-source-actions"><button type="button" data-v468-view="${esc(row.league)}">VIEW GAMES</button><button type="button" data-v468-reprocess="${esc(row.league)}">REPROCESS MEDIA</button></div></td>
      </tr>`;
    }).join('');

    body.querySelectorAll('[data-v468-view]').forEach(btn=>btn.addEventListener('click',()=>{
      const league=String(btn.dataset.v468View||'').toUpperCase();
      state.statisticsActive=false;
      $('historyStatisticsPane')?.classList.add('history-audit-pane-hidden');
      const select=$('historyAuditLeague');
      if (select && [...select.options].some(o=>o.value===league)) select.value=league;
      window.SBB_HISTORY_AUDIT?.setTab?.('games');
      select?.dispatchEvent(new Event('change',{bubbles:true}));
    }));
    body.querySelectorAll('[data-v468-reprocess]').forEach(btn=>btn.addEventListener('click',()=>reprocessCompetition(btn.dataset.v468Reprocess,btn)));
  }

  async function loadStatistics(force=false) {
    if (state.statisticsLoading) return;
    state.statisticsLoading=true;
    const body=$('historyStatisticsBody');
    const summary=$('historyStatisticsSummary');
    if (body) body.innerHTML='<tr><td colspan="13">Loading competition statistics…</td></tr>';
    if (summary) summary.textContent='Reading normalized catalog coverage by competition…';
    try {
      await loadContext(force);
      const ids=statisticsCompetitionIds();
      const summaries=await mapWithConcurrency(ids,4,auditSummary);
      state.statisticsRows=ids.map((league,i)=>{
        const s=summaries[i]||{};
        const meta=statsMeta(league), games=Number(s.games||0), noMedia=Number(s.noVerifiedMediaGames||0);
        return {
          league,...meta,
          error:s.error||'',
          games,
          anyHighlights:Math.max(0,games-noMedia),
          noMedia,
          best:s.best||{},
          coverageComplete:Number(s.coverageCompleteGames||0),
          greenCoverage:Number(s.greenCoverageGames||0),
          verifiedAssets:Number(s.verifiedAssets||0),
          sourceStats:sourceStatsFor(league),
        };
      });
      renderStatistics(state.statisticsRows);
    } catch (err) {
      if (body) body.innerHTML=`<tr><td colspan="13">Statistics load failed: ${esc(err?.message||err)}</td></tr>`;
      if (summary) summary.textContent='Statistics unavailable.';
    } finally {
      state.statisticsLoading=false;
    }
  }

  function showStatistics() {
    state.statisticsActive=true;
    document.querySelectorAll('.history-game-only,.history-silver-only,.history-playlists-only').forEach(el=>el.classList.add('history-audit-pane-hidden'));
    document.querySelector('.history-search-console')?.classList.add('history-audit-pane-hidden');
    $('historyStatisticsPane')?.classList.remove('history-audit-pane-hidden');
    for (const id of ['historyAuditTabGames','historyAuditTabSilver','historyAuditTabPlaylists','historyAuditTabStatistics']) {
      const btn=$(id);if(!btn)continue;
      const active=id==='historyAuditTabStatistics';
      btn.classList.toggle('active',active);btn.setAttribute('aria-selected',String(active));
    }
    $('historyAuditCsv')?.classList.add('hidden');
    $('historyAuditXlsx')?.classList.add('hidden');
    loadStatistics(true);
  }

  function leaveStatistics() {
    if (!state.statisticsActive) return;
    state.statisticsActive=false;
    $('historyStatisticsPane')?.classList.add('history-audit-pane-hidden');
  }

  function installTabBridge() {
    const api=window.SBB_HISTORY_AUDIT;
    if (!api || api.__v468Bridge) return false;
    const originalSetTab=api.setTab?.bind(api);
    api.setTab=(tab,opts)=>{
      if (tab==='statistics') return showStatistics();
      leaveStatistics();
      return originalSetTab?.(tab,opts);
    };
    api.refreshStatistics=()=>loadStatistics(true);
    api.reprocessCompetition=(league)=>reprocessCompetition(league);
    api.__v468Bridge=true;
    return true;
  }

  function init() {
    installTabBridge();
    $('historyAuditTabStatistics')?.addEventListener('click',showStatistics);
    for (const id of ['historyAuditTabGames','historyAuditTabSilver','historyAuditTabPlaylists']) {
      $(id)?.addEventListener('click',leaveStatistics);
    }
    $('historyAuditRefresh')?.addEventListener('click',()=>{if(state.statisticsActive)loadStatistics(true);else loadContext(true);});

    const grid=$('historyMediaSourcesGrid');
    if (grid) {
      state.observer=new MutationObserver(()=>schedulePlaylistDecoration());
      state.observer.observe(grid,{childList:true,subtree:true});
    }

    const modal=$('historyAuditModal');
    if (modal) {
      new MutationObserver(()=>{
        if (!modal.classList.contains('hidden')) {
          loadContext(true);
          if (state.statisticsActive) loadStatistics(true);
        }
      }).observe(modal,{attributes:true,attributeFilter:['class']});
    }

    loadContext(true);
    state.refreshTimer=setInterval(()=>{
      if (!$('historyAuditModal')?.classList.contains('hidden')) {
        loadContext(true);
        if (state.statisticsActive) loadStatistics(true);
      }
    },30000);
  }

  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',init);
  else init();
})();
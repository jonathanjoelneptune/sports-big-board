/* Sports Big Board v4.1.12 historical database audit view. */
(() => {
  const $ = id => document.getElementById(id);
  const FRONTEND_VERSION='4.1.12';
  const state={offset:0,limit:100,total:0,loading:false,lastPayload:null,tab:'games',silverOffset:0,silverLimit:100,silverTotal:0,silverLoading:false,lastSilverPayload:null,lastConsole:null,autoTimer:null,consoleTimer:null,consoleLoading:false,copyTimer:null,modeUpdating:false};
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
  function silverQueryParams(includePaging=true){
    const p=new URLSearchParams();
    const values={scope:$('historySilverScope')?.value||'',league:$('historySilverLeague')?.value||'',kind:$('historySilverKind')?.value||'',flag:$('historySilverFlag')?.value||'',period:$('historySilverPeriod')?.value||'',q:$('historySilverSearch')?.value||''};
    for(const [k,v] of Object.entries(values))if(v)p.set(k,v);
    if(includePaging){p.set('limit',String(state.silverLimit));p.set('offset',String(state.silverOffset));}
    return p;
  }
  function scopeLabel(scope){const v=String(scope||'').toUpperCase();return v==='WEEK_LEAGUE'?'WEEKLY':(v==='DAY_LEAGUE'?'DAILY':(v==='ROUND_LEAGUE'?'MATCHWEEK / MATCHDAY':String(scope||'—')));}
  function flagLabel(flag){return String(flag||'').replaceAll('_',' ');}
  function cssToken(value){return String(value||'unknown').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'')||'unknown';}
  function leagueBadge(league){const value=String(league||'—').toUpperCase();return `<span class="audit-league league-${esc(cssToken(value))}">${esc(value)}</span>`;}
  function silverKindBadge(kind){const value=String(kind||'ROUNDUP').toUpperCase();return `<span class="silver-kind kind-${esc(cssToken(value))}">${esc(value.replaceAll('_',' '))}</span>`;}
  function renderSilverSummary(summary={}){
    const map={historySilverCollections:summary.collections||0,historySilverLinks:summary.links||0,historySilverUniqueAssets:summary.uniqueAssets||0,historySilverDaily:summary.dayCollections||0,historySilverWeekly:summary.weekCollections||0,historySilverRound:summary.roundCollections||0,historySilverSuspicious:summary.suspiciousLinks||0,historySilverLargest:summary.maxCollectionAssets||0};
    for(const [id,val] of Object.entries(map)){const el=$(id);if(el)el.textContent=Number(val).toLocaleString();}
    const text=$('historySilverSummaryText');
    if(text)text.textContent=`Silver collection integrity: ${Number(summary.largeCollections||0).toLocaleString()} collections over ${Number(summary.largeCollectionThreshold||20)} assets • ${Number(summary.multiCollectionAssets||0).toLocaleString()} assets reused across collections • ${Number(summary.duplicateAssets||0).toLocaleString()} assets linked across multiple periods • ${Number(summary.gameScopeLinks||0).toLocaleString()} GAME-scope leaks • ${Number(summary.lowConfidenceLinks||0).toLocaleString()} low-confidence links • ${Number(summary.periodMismatchLinks||0).toLocaleString()} date mismatches • ${Number(summary.leagueMismatchLinks||0).toLocaleString()} league mismatches`;
  }
  function renderSilverRows(payload){
    const body=$('historySilverTableBody');if(!body)return;const rows=payload.rows||[];
    if(!rows.length){body.innerHTML='<tr><td colspan="11" class="audit-no-results">No Silver assets match these filters.</td></tr>';return;}
    body.innerHTML=rows.map(row=>{
      const flags=row.flags||[]; const conf=Math.round(Number(row.associationConfidence||0)*100); const dur=fmtDur(row.durationSeconds);
      const asset=`${row.url?`<a class="silver-asset-link" href="${esc(row.url)}" target="_blank" rel="noopener"><strong>${esc(row.title||'Media')}</strong></a>`:`<strong>${esc(row.title||'Media')}</strong>`}<small>${esc(row.assetKey||'')}</small>`;
      const sourceBits=[];if(row.sourceDate)sourceBits.push(row.sourceDate);if(row.sourceLeague)sourceBits.push(row.sourceLeague);
      const flagHtml=flags.length?flags.map(f=>`<span class="silver-flag ${f==='GAME_SCOPE_ASSET'||f.includes('MISMATCH')?'danger':''}">${esc(flagLabel(f))}</span>`).join(''):'<span class="silver-flag clean">CLEAN</span>';
      return `<tr class="${flags.length?'silver-row-flagged':''}">
        <td class="audit-date"><strong>${esc(row.periodKey||'—')}</strong><small>${esc(sourceBits.length?'source '+sourceBits.join(' / '):'')}</small></td>
        <td><span class="silver-scope scope-${esc(cssToken(scopeLabel(row.scope)))}">${esc(scopeLabel(row.scope))}</span></td>
        <td>${leagueBadge(row.league)}</td>
        <td class="silver-collection">${silverKindBadge(row.collectionKind)}<small>${Number(row.collectionAssetCount||0).toLocaleString()} assets • ${esc(row.collectionKey||'')}</small></td>
        <td class="silver-asset">${asset}</td>
        <td><strong>${esc(row.provider||'—')}</strong><small>${esc(row.sourceAuthority||'UNPROVEN')}</small></td>
        <td>${esc(dur||'—')}</td>
        <td class="silver-validation"><strong>${esc(row.validation||'CANDIDATE')}</strong><small>${esc(row.runtime||'UNKNOWN')}</small></td>
        <td class="silver-scope-intent"><strong>${esc(row.mediaScope||'OTHER')}</strong><small>${esc(row.intent||'OTHER')} • scope ${Math.round(Number(row.scopeConfidence||0)*100)}%</small></td>
        <td class="silver-association" title="${esc(row.associationEvidence||'')}"><strong>${conf}%</strong><small>${esc(row.associationMethod||'—')}</small></td>
        <td class="silver-flags">${flagHtml}</td>
      </tr>`;
    }).join('');
  }
  function updateSilverPager(){
    const from=state.silverTotal?state.silverOffset+1:0,to=Math.min(state.silverTotal,state.silverOffset+state.silverLimit);
    const label=$('historySilverPageLabel');if(label)label.textContent=`${from.toLocaleString()}–${to.toLocaleString()} of ${state.silverTotal.toLocaleString()} asset links`;
    const prev=$('historySilverPrev');if(prev)prev.disabled=state.silverOffset<=0;const next=$('historySilverNext');if(next)next.disabled=state.silverOffset+state.silverLimit>=state.silverTotal;
  }
  function setAuditTab(tab,{loadData=true}={}){
    state.tab=tab==='silver'?'silver':'games';const silver=state.tab==='silver';
    document.querySelectorAll('.history-game-only').forEach(el=>el.classList.toggle('history-audit-pane-hidden',silver));
    document.querySelectorAll('.history-silver-only').forEach(el=>el.classList.toggle('history-audit-pane-hidden',!silver));
    const gameBtn=$('historyAuditTabGames'),silverBtn=$('historyAuditTabSilver');
    if(gameBtn){gameBtn.classList.toggle('active',!silver);gameBtn.setAttribute('aria-selected',String(!silver));}
    if(silverBtn){silverBtn.classList.toggle('active',silver);silverBtn.setAttribute('aria-selected',String(silver));}
    const csv=$('historyAuditCsv'),xlsx=$('historyAuditXlsx');
    if(csv)csv.textContent=silver?'EXPORT SILVER CSV':'EXPORT GAME CSV';
    if(xlsx)xlsx.textContent=silver?'EXPORT SILVER XLSX':'EXPORT GAME XLSX';
    if(loadData){silver?loadSilver(true):load(true);}
  }
  async function loadSilver(reset=false){
    if(state.silverLoading)return;if(reset)state.silverOffset=0;state.silverLoading=true;$('historySilverLoading')?.classList.remove('hidden');
    try{
      const r=await fetch(`/api/history/catalog/collections?${silverQueryParams(true).toString()}`,{cache:'no-store'});let data={};try{data=await r.json();}catch(_){data={};}
      if(!r.ok||!data.ok)throw new Error(data.message||data.error||`HTTP ${r.status}`);
      state.silverTotal=Number(data.total||0);state.lastSilverPayload=data;renderSilverSummary(data.summary||{});renderSilverRows(data);updateSilverPager();
      const msg=$('historyAuditMessage');if(msg)msg.textContent=`SILVER ROUNDUPS • ${Number(data.summary?.collections||0).toLocaleString()} collections • ${Number(data.summary?.links||0).toLocaleString()} asset links • read-only collection audit`;
    }catch(err){const body=$('historySilverTableBody');if(body)body.innerHTML=`<tr><td colspan="11" class="audit-no-results">Silver audit load failed: ${esc(err.message||err)}</td></tr>`;}
    finally{state.silverLoading=false;$('historySilverLoading')?.classList.add('hidden');}
  }
  function loadCurrent(reset=false){return state.tab==='silver'?loadSilver(reset):load(reset);}

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
    const map={historyAuditGames:summary.games||0,historyAuditVerified:summary.verifiedAssets||0,historyAuditGold:t.gold||0,historyAuditGreen:t.green||0,historyAuditPurple:t.extended||0,historyAuditBlue:t.blue||0,historyAuditCoverageComplete:summary.coverageCompleteGames||0,historyAuditUpgrade:summary.upgradePendingGames||0};
    for(const [id,val] of Object.entries(map)){const el=$(id);if(el)el.textContent=Number(val).toLocaleString();}
    const best=$('historyAuditBestSummary');
    if(best)best.textContent=`Best per game: ${Number(b.gold||0).toLocaleString()} Gold • ${Number(b.green||0).toLocaleString()} Green • ${Number(b.extended||0).toLocaleString()} Purple • ${Number(b.blue||0).toLocaleString()} Blue • ${Number(b.none||0).toLocaleString()} none`;
    const status=$('historyAuditStatusSummary');
    if(status)status.textContent=`Status projection: ${Number(st.UNINDEXED||0).toLocaleString()} Unindexed • ${Number(st.SEARCHED_EMPTY||0).toLocaleString()} Searched Empty • ${Number(st.COVERAGE_COMPLETE||0).toLocaleString()} Coverage Complete • ${Number(st.UPGRADE_PENDING||0).toLocaleString()} Upgrade Pending • ${Number(st.QUALITY_COMPLETE||0).toLocaleString()} Quality Complete • ${Number(summary.noVerifiedMediaGames||0).toLocaleString()} without verified media`;
    const coverage=$('historyAuditGreenCoverageSummary');
    if(coverage){
      const by=summary.greenCoverageByLeague||{}; const games=Number(summary.games||0), green=Number(summary.greenCoverageGames||0);
      const pct=games?((green/games)*100).toFixed(1):'0.0';
      const leagues=['MLB','NFL','NBA','NHL','EPL','MLS'].filter(l=>by[l]).map(l=>{const x=by[l]||{},g=Number(x.games||0),q=Number(x.greenGames||0);return `${l} ${q}/${g}${g?` (${((q/g)*100).toFixed(0)}%)`:''}`;});
      coverage.textContent=`Quick recap coverage: ${green.toLocaleString()}/${games.toLocaleString()} games (${pct}%)${leagues.length?' • '+leagues.join(' • '):''}`;
    }
    const completeCoverage=$('historyAuditCoverageCompleteSummary');
    if(completeCoverage){
      const by=summary.coverageCompleteByLeague||{}; const games=Number(summary.games||0), complete=Number(summary.coverageCompleteGames||0);
      const pct=games?((complete/games)*100).toFixed(1):'0.0';
      const leagues=['MLB','NFL','NBA','NHL','EPL','MLS'].filter(l=>by[l]).map(l=>{const x=by[l]||{},g=Number(x.games||0),q=Number(x.coverageCompleteGames||0);return `${l} ${q}/${g}${g?` (${((q/g)*100).toFixed(0)}%)`:''}`;});
      completeCoverage.textContent=`Coverage complete (Gold / Green / Purple): ${complete.toLocaleString()}/${games.toLocaleString()} games (${pct}%)${leagues.length?' • '+leagues.join(' • '):''}`;
    }
  }
  function renderRows(payload){
    const body=$('historyAuditTableBody'); if(!body)return;
    const rows=payload.rows||[];
    if(!rows.length){body.innerHTML='<tr><td colspan="9" class="audit-no-results">No games match these filters.</td></tr>';return;}
    body.innerHTML=rows.map(row=>{
      const tiers=row.tiers||{}; const best=row.bestTier||'none';
      const effective=String(row.effectiveStatus||'UNINDEXED');
      const status=effective.replaceAll('_',' ');
      const statusDetail=row.discoveryPending
        ? `Discovery v${Number(row.currentDiscoveryVersion||0)} pass pending${row.bestTier&&row.bestTier!=='none'?' • media already known':''}`
        : (row.nextRetryAt?`Retry ${new Date(row.nextRetryAt*1000).toLocaleString()}`:(row.lastError?String(row.lastError).slice(0,90):''));
      return `<tr>
        <td class="audit-date">${esc(fmtDate(row.date))}</td>
        <td>${leagueBadge(row.league)}</td>
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
  function backfillSummary(back={}){
    const floor=String(back.floorDate||'2025-08-01');
    if(back.seedComplete)return `SEED COMPLETE through ${floor}${back.completedAt?` • completed ${new Date(Number(back.completedAt)*1000).toLocaleString()}`:''}`;
    const progress=back.lastDate?`last ${back.lastDate} • deep games ${Number(back.deepGames||0)} • media items ${Number(back.mediaItems||0)} • dates ${Number(back.daysCompleted||0)}`:'waiting for first seed pass';
    return `seed floor ${floor} • ${progress}`;
  }
  function consoleWorkerLine(name,st={}){
    const bits=[`${name}: phase=${String(st.phase||'unknown')}`,`healthy=${st.healthy?'YES':'NO'}`,`heartbeat=${ageText(st.heartbeatAgeSeconds)}`,`progress=${ageText(st.progressAgeSeconds)}`];
    if(st.workType)bits.push(`work=${st.workType}`); if(st.catchupSources)bits.push(`sources=${st.catchupSources}`); if(st.provider)bits.push(`provider=${st.provider}`); if(st.providerWaitSeconds)bits.push(`provider-wait=${Number(st.providerWaitSeconds).toFixed(1)}s`);
    if(st.claimKey)bits.push(`claim=${st.claimKey}`); if(st.lastDurationSeconds)bits.push(`last=${Number(st.lastDurationSeconds).toFixed(1)}s`); if(st.current)bits.push(`current=${st.current}`);
    return bits.join(' • ');
  }
  function renderWorkerGrid(data){
    const grid=$('historySearchWorkerGrid');if(!grid)return;grid.innerHTML='';
    const workers=data?.workers||{}, pool=data?.greenPool||{};
    const names=[...Array(Number(pool.configured||0)).keys()].map(i=>`green-gap-${i+1}`); names.push('date-backfill');
    for(const name of names){
      const st=workers[name]||{}; const phase=String(st.phase||'starting'); const card=document.createElement('div'); card.className='history-search-worker-card';
      if(phase.startsWith('provider')||phase.startsWith('official-catchup')||phase==='discovering'||phase==='backfilling')card.classList.add('active'); else if(phase.startsWith('paused'))card.classList.add('paused'); else if(phase.includes('wait'))card.classList.add('waiting'); else if(phase==='error')card.classList.add('error');
      const title=document.createElement('span');title.textContent=name.toUpperCase(); const strong=document.createElement('strong');strong.textContent=phase.replaceAll(':',' / '); const small=document.createElement('small');
      const detail=[]; if(st.current)detail.push(st.current); if(st.workType)detail.push(st.workType); if(st.catchupSources)detail.push(`sources ${st.catchupSources}`); if(st.provider)detail.push(`provider ${st.provider}`); if(st.claimKey)detail.push(`lease ${st.claimKey}`); if(st.lastDurationSeconds)detail.push(`last ${Number(st.lastDurationSeconds).toFixed(1)}s`); if(Number(st.shortCircuits||0))detail.push(`short ${Number(st.shortCircuits||0)}`); if(Number(st.fallbackAttempts||0))detail.push(`fallback ${Number(st.fallbackHits||0)}/${Number(st.fallbackAttempts||0)}`); if(!detail.length)detail.push(`heartbeat ${ageText(st.heartbeatAgeSeconds)}`);
      small.textContent=detail.join(' • ');card.append(title,strong,small);grid.appendChild(card);
    }
  }
  function workModeFrom(data){
    const mode=String(data?.workMode?.mode||data?.background?.workMode||window.SBB_RESOURCE_MODE||'balanced').toLowerCase();
    return ['search','balanced','playback'].includes(mode)?mode:'balanced';
  }
  function applyWorkMode(mode,{dispatch=true}={}){
    mode=['search','balanced','playback'].includes(String(mode))?String(mode):'balanced';
    window.SBB_RESOURCE_MODE=mode;
    const group=document.querySelector('.history-resource-mode'); if(group)group.classList.toggle('busy',state.modeUpdating);
    for(const id of ['historyModeSearch','historyModeBalanced','historyModePlayback']){const btn=$(id);if(btn)btn.classList.toggle('active',btn.dataset.mode===mode);}
    const head=document.querySelector('.history-search-console-head'); if(head){head.classList.toggle('mode-search',mode==='search');head.classList.toggle('mode-playback',mode==='playback');}
    if(dispatch)window.dispatchEvent(new CustomEvent('sbb:workmode',{detail:{mode}}));
  }
  async function setWorkMode(mode){
    mode=String(mode||'').toLowerCase(); if(!['search','balanced','playback'].includes(mode)||state.modeUpdating)return;
    state.modeUpdating=true;applyWorkMode(mode,{dispatch:false});
    const status=$('historySearchConsoleCopyStatus'); if(status)status.textContent='SETTING MODE…';
    try{
      const r=await fetch('/api/history/work-mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode}),cache:'no-store'});
      const data=await r.json(); if(!r.ok||!data.ok)throw new Error(data.message||data.error||`HTTP ${r.status}`);
      applyWorkMode(String(data.workMode?.mode||mode));
      if(status)status.textContent=`${mode.toUpperCase()} MODE ACTIVE`;
      setTimeout(()=>{if(status)status.textContent='';},2200);
      loadConsole();load(false);
    }catch(err){
      if(status){status.classList.add('copy-error');status.textContent=`MODE FAILED: ${String(err?.message||err)}`;setTimeout(()=>{status.textContent='';status.classList.remove('copy-error');},3500);}
      if(state.lastConsole)applyWorkMode(workModeFrom(state.lastConsole));
    }finally{state.modeUpdating=false;applyWorkMode(window.SBB_RESOURCE_MODE||'balanced',{dispatch:false});}
  }
  function officialCatchupLine(catchup={}){
    const leagues=catchup.leagues||{}; const parts=['NFL','NHL','EPL','MLS'].filter(k=>leagues[k]).map(k=>{const x=leagues[k]||{};return `${k} ${Number(x.checked||0)}/${Number(x.total||0)} checked • ${Number(x.remaining||0)} remaining • coverage+${Number(x.coverageUpgrades||0)} • green+${Number(x.qualityUpgrades||0)}`;});
    return `floor ${catchup.floorDate||'n/a'} • ${String(catchup.status||'UNKNOWN')} • checked ${Number(catchup.checked||0)}/${Number(catchup.total||0)} • remaining ${Number(catchup.remaining||0)} • coverage+${Number(catchup.coverageUpgrades||0)} • green+${Number(catchup.qualityUpgrades||0)}${parts.length?' • '+parts.join(' | '):''}`;
  }

  function consoleFullReport(data){
    const now=new Date(); const backend=String(data?.version||'UNKNOWN'); const discovery=Number(data?.historyDiscoveryVersion||0);
    const threads=data?.threads||[], workers=data?.workers||{}, queue=data?.greenGapQueue||{}, bg=data?.background||{}, g=data?.greenGap||{}, back=data?.backfill||{};
    const gateway=data?.youtubeGateway||{}, budget=data?.youtubeSearchBudget||{}, hi=data?.highlightly||{}, focus=data?.focus||{}, assoc=data?.associations||{}, pool=data?.greenPool||{}, providers=data?.providerConcurrency||{}, claims=data?.eventClaims||[], eff=data?.discoveryEfficiency||{}, silver=data?.silver||{}, objectives=data?.mediaObjectives||{}, objRuntime=objectives?.runtime||{}, catchup=data?.officialSourceCatchup||{}, ruleGame=data?.ruleGameCatchup||{}, ruleCollections=data?.ruleCollectionCatchup||{};
    const used=Number(budget.used||0), limit=Number(budget.limit||budget.budget||0);
    const rows=[
      'SPORTS BIG BOARD — LIVE SEARCH CONSOLE',
      `Captured: ${now.toLocaleString()} (${now.toISOString()})`,
      `Frontend v${FRONTEND_VERSION} • Backend v${backend} • Discovery v${discovery} • Deployment ${String(data?.deploymentMode||'unknown')}`,
      `[MODE] ${workModeFrom(data).toUpperCase()} • playbackSuspended=${data?.playbackSuspended?'YES':'NO'} • searchSuspended=${data?.searchSuspended?'YES':'NO'}`,
      '',
      `[STATE] server uptime ${Math.round(Number(data?.uptimeSeconds||0)/60)}m • green attempts ${Number(g.attempts||0)} • green upgrades ${Number(g.upgradedToGreen||0)}`,
      `[THREADS] ${threads.map(x=>`${x.name}=${x.alive?'ALIVE':'DEAD'}`).join(' • ')||'none reported'}`,
      `[GREEN POOL] configured ${Number(pool.configured||0)} • desired ${Number(pool.desired||0)} • active ${Number(pool.active||0)} • attempts/hr ${Number(pool.attemptsPerHour||0)} • upgrades/hr ${Number(pool.upgradesPerHour||0)} • official-catchup/hr ${Number(pool.officialCatchupPerHour||0)} • candidate-promotions/hr ${Number(pool.candidatePromotionsPerHour||0)}`,
      `[OFFICIAL SOURCE CATCH-UP] ${officialCatchupLine(catchup)}`,
      `[RULE GAME CATCH-UP] v${Number(ruleGame.version||0)} • ${String(ruleGame.status||'UNKNOWN')} • checked ${Number(ruleGame.checked||0)}/${Number(ruleGame.total||0)} • remaining ${Number(ruleGame.remaining||0)}${Object.keys(ruleGame.leagues||{}).length?' • '+['NFL','MLS','EPL'].filter(k=>(ruleGame.leagues||{})[k]).map(k=>{const x=ruleGame.leagues[k]||{};return `${k} ${Number(x.checked||0)}/${Number(x.total||0)}`;}).join(' | '):''}` ,
      `[RULE COLLECTION CATCH-UP] v${Number(ruleCollections.version||0)} • ${ruleCollections.complete?'COMPLETE':(ruleCollections.running?'ACTIVE':'WAITING')} • dates ${Number(ruleCollections.datesChecked||0)} • candidates ${Number(ruleCollections.candidatesExamined||0)} • qualifying ${Number(ruleCollections.qualifying||0)} • new-assets ${Number(ruleCollections.newUniqueAssets||0)} • reused ${Number(ruleCollections.existingAssetsReused||0)} • new-links ${Number(ruleCollections.newCollectionLinks||0)} • duplicate-links ${Number(ruleCollections.duplicateLinksSuppressed||0)} • rejected ${Number(ruleCollections.rejected||0)} • last ${String(ruleCollections.lastLeague||'')} ${String(ruleCollections.lastDate||'')}` ,
      `[DISCOVERY EFFICIENCY] primary ${Number(eff.primaryPasses||0)} • primary-target ${Number(eff.primaryTargetHits||0)} • short-circuit ${Number(eff.shortCircuits||0)} • fallbacks ${Number(eff.fallbackAttempts||0)} • fallback hits ${Number(eff.fallbackHits||0)} (${Number(eff.fallbackHitRate||0)}%) • avg fallback ${Number(eff.averageFallbackSeconds||0)}s • est saved ${(Number(eff.estimatedSecondsSaved||0)/60).toFixed(1)}m`,
      ...Object.keys(workers).filter(k=>/^green-gap-\d+$/.test(k)).sort().map(k=>`[WORKER] ${consoleWorkerLine(k,workers[k]||{})}`),
      `[WORKER] ${consoleWorkerLine('date-backfill',workers['date-backfill']||{})}`,
      `[WORKER] ${consoleWorkerLine('rule-collections',workers['rule-collections']||{})}`,
      `[CATALOG] unindexed ${Number(queue.unindexed||queue.stale_version||0)} • searched-empty ${Number(queue.searched_empty||0)} • coverage-complete ${Number(queue.coverage_complete||0)} • playable-partial ${Number(queue.playable_partial||0)} • candidate-only ${Number(queue.candidate_only||0)}`,
      `[GAPS] coverage ${Number(queue.gaps||0)} • due ${Number(queue.due_now||0)} • recent ${Number(queue.recent_gaps||0)} • blue-only ${Number(queue.blue_only||0)}`,
      `[QUALITY UPGRADES] purple-only ${Number(queue.purple_only||0)} • due ${Number(queue.quality_upgrade_due||0)} • total work due ${Number(queue.work_due||0)}`,
      `[ASSOCIATIONS] assigned ${Number(assoc.assignedLinks||0)} • quarantined ${Number(assoc.quarantinedLinks||0)} • cross-event ${Number(assoc.crossEventAssets||0)} • team-mismatch ${Number(assoc.teamMismatch||0)} • date-mismatch ${Number(assoc.dateMismatch||0)} • season-mismatch ${Number(assoc.seasonMismatch||0)}`,
      `[QUARANTINE REASONS] ${Object.entries(assoc.quarantineReasons||{}).slice(0,8).map(([k,v])=>`${k}=${Number(v||0)}`).join(' • ')||'none'}`,
      `[CLAIMS] active ${claims.length}${claims.length?` • ${claims.map(x=>`${x.owner}=${x.canonicalEventKey}`).join(' • ')}`:''}`,
      `[PROVIDERS] ${Object.entries(providers).map(([k,v])=>`${k} ${Number(v.active||0)}/${Number(v.limit||0)} active${Number(v.waiting||0)?` +${Number(v.waiting)} waiting`:''}`).join(' • ')||'none'}`,
      `[SILVER] day collections ${Number(silver.dayCollections||0)} / ${Number(silver.dayAssets||0)} assets • week collections ${Number(silver.weekCollections||0)} / ${Number(silver.weekAssets||0)} assets • round collections ${Number(silver.roundCollections||0)} / ${Number(silver.roundAssets||0)} assets • periods ${Number(silver.periods||0)}`,
      `[MEDIA OBJECTIVES] NFL quick ${Number(objectives.nflQuickGames||0)} • extended ${Number(objectives.nflExtendedGames||0)} • both ${Number(objectives.nflBothGames||0)} • missing quick ${Number(objectives.nflMissingQuick||0)} • missing extended ${Number(objectives.nflMissingExtended||0)} | MLS snapshot ${Number(objectives.mlsSnapshotGames||objectives.mlsSnapshots||0)} • highlights ${Number(objectives.mlsHighlightGames||objectives.mlsMatchHighlights||0)} • both ${Number(objectives.mlsBothGames||0)} • missing snapshot ${Number(objectives.mlsMissingSnapshot||0)} • missing highlights ${Number(objectives.mlsMissingHighlights||0)} | EPL quick ${Number(objectives.eplQuickGames||0)} • extended ${Number(objectives.eplExtendedGames||0)} • both ${Number(objectives.eplBothGames||0)} • missing quick ${Number(objectives.eplMissingQuick||0)} • missing extended ${Number(objectives.eplMissingExtended||0)} | BEST_GOALS ${Number(objectives.bestGoalsCollections||0)} collections / ${Number(objectives.bestGoalsAssets||0)} assets • BEST_SAVES ${Number(objectives.bestSavesCollections||0)} collections / ${Number(objectives.bestSavesAssets||0)} assets`,
      `[NFL PUBLIC SOURCES] public accepted ${Number(objRuntime.nflPublicAccepted||0)} • team accepted ${Number(objRuntime.nflTeamAccepted||0)} • gated ${Number(objRuntime.entitlementGated||0)} • individual-play ${Number(objRuntime.individualPlayRejected||0)} • postgame ${Number(objRuntime.postgameReactionRejected||0)} • non-playable ${Number(objRuntime.nonPlayableRejected||0)} • duration ${Number(objRuntime.durationRejected||0)} • event-mismatch ${Number(objRuntime.eventMismatchRejected||0)}` ,
      `[MEDIA NORMALIZATION] duplicates-collapsed ${Number(objRuntime.duplicatesCollapsed||0)} • postgame/reaction-rejected ${Number(objRuntime.postgameReactionRejected||0)} • accepted NFL quick ${Number(objRuntime.nflQuickAccepted||0)} / extended ${Number(objRuntime.nflExtendedAccepted||0)} • MLS snapshot ${Number(objRuntime.mlsSnapshotAccepted||0)} / highlights ${Number(objRuntime.mlsMatchHighlightsAccepted||0)}`,
      `[GREEN] ${g.current?`NOW ${g.current}`:(g.lastDate?`LAST ${g.lastDate} ${g.lastLeague||''} ${String(g.lastBestTier||'none').toUpperCase()}→${String(g.lastResultTier||'none').toUpperCase()}`:'no completed attempt yet')} • lastError=${String(g.lastError||'none')}`,
      `[BACKFILL] ${backfillSummary(back)} • lastError=${String(back.lastError||'none')}`,
      `[BACKGROUND] ${bg.canWork?'ACTIVE':`YIELDING • ${String(bg.pauseReason||'unknown').replaceAll('-',' ')}`} • mediaAge=${Number(bg.mediaAgeSeconds||0)}s • interactiveAge=${Number(bg.interactiveAgeSeconds||0)}s • siteOpenDoesNotPause=${bg.siteOpenDoesNotPause?'YES':'NO'}`,
      `[FOCUS] date=${focus.date||'none'} • until=${focus.until?new Date(Number(focus.until)*1000).toISOString():'none'} • foregroundDiscovery=${bg.foregroundDiscoveryRunning?'YES':'NO'}`,
      `[SEARCH BUDGET] ${used}/${limit||'?'} today${limit&&used>=limit?' • EXHAUSTED':''}${budget.remainingByBucket?` • reserves recent ${Number(budget.remainingByBucket.recent||0)} / empty ${Number(budget.remainingByBucket.empty||0)} / blue ${Number(budget.remainingByBucket.blue||0)} / archive ${Number(budget.remainingByBucket.archive||0)}`:''}`,
      `[HIGHLIGHTLY] ${hi.limited?'RATE LIMITED':'OK'} • remaining=${hi.remaining??'?'} • limit=${hi.limit??'?'}`,
    ];
    for(const op of ['search','videos','activities','playlistItems','channels']){
      const st=gateway[op]; if(!st)continue;
      rows.push(`[YOUTUBE ${op}] ${st.quotaExhausted?'QUOTA EXHAUSTED':(Number(st.cooldownSeconds||0)>0?`COOLDOWN ${Number(st.cooldownSeconds||0)}s`:'OK')} • failures=${Number(st.failures||0)}${st.lastError?` • ${st.lastError}`:''}`);
    }
    const problems=data?.problems||[];
    rows.push('',`[CURRENT PROBLEMS] ${problems.length}`,...(problems.length?problems.map(x=>`- ${x}`):['- none']));
    const active=data?.activeDiscoveries||{}; const activeKeys=Object.keys(active);
    rows.push('',`[ACTIVE DISCOVERIES] ${activeKeys.length}`,...(activeKeys.length?activeKeys.map(k=>`- ${k}: ${JSON.stringify(active[k])}`):['- none']));
    rows.push('','[RECENT TERMINAL]');
    for(const row of (data?.recent||[]))rows.push(`[${consoleTime(row.at)}] [${String(row.worker||'history')}] ${String(row.level||'INFO')} ${String(row.message||'')}${row.meta&&Object.keys(row.meta).length?` • meta=${JSON.stringify(row.meta)}`:''}`);
    return rows.join('\n');
  }
  function consoleIssuesReport(data){
    const queue=data?.greenGapQueue||{}, bg=data?.background||{}, gateway=data?.youtubeGateway||{}, budget=data?.youtubeSearchBudget||{}, hi=data?.highlightly||{}, g=data?.greenGap||{}, back=data?.backfill||{};
    const used=Number(budget.used||0), limit=Number(budget.limit||budget.budget||0); const rows=[
      'SPORTS BIG BOARD — SEARCH ISSUES / RATE LIMITS',
      `Captured: ${new Date().toLocaleString()} (${new Date().toISOString()})`,
      `Frontend v${FRONTEND_VERSION} • Backend v${String(data?.version||'UNKNOWN')} • Discovery v${Number(data?.historyDiscoveryVersion||0)}`,
      `[MODE] ${workModeFrom(data).toUpperCase()} • playbackSuspended=${data?.playbackSuspended?'YES':'NO'} • searchSuspended=${data?.searchSuspended?'YES':'NO'}`,
      '',
      `[QUEUE CONTEXT] ${Number(queue.due_now||0)} due / ${Number(queue.gaps||0)} gaps • blue-only ${Number(queue.blue_only||0)} • purple-only ${Number(queue.purple_only||0)} • searched-empty ${Number(queue.searched_empty||0)} • unindexed ${Number(queue.unindexed||0)}`,
      `[BACKGROUND] ${bg.canWork?'ACTIVE':`YIELDING • ${String(bg.pauseReason||'unknown').replaceAll('-',' ')}`} (normal yielding is not itself an error)`,
      `[GREEN LAST ERROR] ${String(g.lastError||'none')}`,
      `[BACKFILL LAST ERROR] ${String(back.lastError||'none')}`,
      `[SEARCH BUDGET] ${used}/${limit||'?'}${limit&&used>=limit?' • EXHAUSTED':''}${budget.remainingByBucket?` • reserves recent ${Number(budget.remainingByBucket.recent||0)} / empty ${Number(budget.remainingByBucket.empty||0)} / blue ${Number(budget.remainingByBucket.blue||0)} / archive ${Number(budget.remainingByBucket.archive||0)}`:''}`,
      `[HIGHLIGHTLY] ${hi.limited?'RATE LIMITED':'OK'} • remaining=${hi.remaining??'?'} • limit=${hi.limit??'?'}`,
    ];
    for(const [op,st] of Object.entries(gateway)){
      if(Number(st?.cooldownSeconds||0)>0||st?.quotaExhausted||st?.lastError)rows.push(`[YOUTUBE ${op}] ${st?.quotaExhausted?'QUOTA EXHAUSTED':(Number(st?.cooldownSeconds||0)>0?`COOLDOWN ${Number(st.cooldownSeconds)}s`:'ERROR RECORDED')} • failures=${Number(st?.failures||0)}${st?.lastError?` • ${st.lastError}`:''}`);
    }
    const problems=data?.problems||[]; rows.push('',`[CURRENT PROBLEMS] ${problems.length}`,...(problems.length?problems.map(x=>`- ${x}`):['- none']));
    const rx=/(WARN|ERROR|ERR\(|rate.?limit|resource_exhausted|quota|exhaust|cooldown|timeout|failed|degraded|unavailable)/i;
    const bad=(data?.recent||[]).filter(row=>['WARN','ERROR'].includes(String(row.level||'').toUpperCase())||rx.test(String(row.message||'')));
    rows.push('',`[RECENT WARNINGS / ERRORS / LIMITS] ${bad.length}`);
    if(!bad.length)rows.push('- none');
    else for(const row of bad)rows.push(`[${consoleTime(row.at)}] [${String(row.worker||'history')}] ${String(row.level||'INFO')} ${String(row.message||'')}${row.meta&&Object.keys(row.meta).length?` • meta=${JSON.stringify(row.meta)}`:''}`);
    return rows.join('\n');
  }
  async function copyConsoleText(text,label='COPIED'){
    let ok=false;
    try{if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(text);ok=true;}}catch(_){ok=false;}
    if(!ok){
      try{const ta=document.createElement('textarea');ta.value=text;ta.setAttribute('readonly','');ta.style.position='fixed';ta.style.opacity='0';ta.style.pointerEvents='none';document.body.appendChild(ta);ta.focus();ta.select();ok=document.execCommand('copy');ta.remove();}catch(_){ok=false;}
    }
    const status=$('historySearchConsoleCopyStatus');
    if(status){clearTimeout(state.copyTimer);status.classList.toggle('copy-error',!ok);status.textContent=ok?`${label} • ${text.length.toLocaleString()} chars`:'COPY FAILED';state.copyTimer=setTimeout(()=>{status.textContent='';status.classList.remove('copy-error');},3000);}
    return ok;
  }
  function downloadConsoleText(){
    if(!state.lastConsole)return;
    const text=consoleFullReport(state.lastConsole); const stamp=new Date().toISOString().replace(/[:.]/g,'-'); const blob=new Blob([text],{type:'text/plain;charset=utf-8'}); const url=URL.createObjectURL(blob); const a=document.createElement('a');a.href=url;a.download=`sports-big-board-search-console-${stamp}.txt`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    const status=$('historySearchConsoleCopyStatus');if(status){clearTimeout(state.copyTimer);status.classList.remove('copy-error');status.textContent='TXT SAVED';state.copyTimer=setTimeout(()=>{status.textContent='';},2500);}
  }
  function ageText(n){n=Number(n);if(!Number.isFinite(n))return 'no heartbeat';if(n<60)return `${Math.max(0,Math.round(n))}s ago`;if(n<3600)return `${Math.round(n/60)}m ago`;return `${Math.round(n/3600)}h ago`;}
  function consoleTime(ts){if(!ts)return '--:--:--';try{return new Date(Number(ts)*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});}catch(_){return '--:--:--';}}
  function renderConsole(data){
    state.lastConsole=data; const head=document.querySelector('.history-search-console-head'); if(head)head.classList.remove('mismatch','problem','yielding','mode-search','mode-playback');
    const backend=String(data.version||'UNKNOWN'); const discovery=Number(data.historyDiscoveryVersion||0); const versionOk=backend===FRONTEND_VERSION;
    const workMode=workModeFrom(data); applyWorkMode(workMode);
    consoleSet('historySearchConsoleVersion',`Frontend v${FRONTEND_VERSION} • Backend v${backend} • Discovery v${discovery}`);
    const threads=data.threads||[]; const allThreads=threads.length&&threads.every(x=>x.alive);
    const gw=(data.workers||{})['green-gap']||{}; const queue=data.greenGapQueue||{}; const bg=data.background||{}; const pool=data.greenPool||{};
    const search=(data.youtubeGateway||{}).search||{}; const budget=data.youtubeSearchBudget||{}; const assoc=data.associations||{}; const eff=data.discoveryEfficiency||{}; const silver=data.silver||{}; const objectives=data.mediaObjectives||{}; const objRuntime=objectives.runtime||{}; const catchup=data.officialSourceCatchup||{}; const ruleGame=data.ruleGameCatchup||{}; const ruleCollections=data.ruleCollectionCatchup||{};
    const problems=[...(data.problems||[])];
    if(!versionOk)problems.unshift(`RELEASE MISMATCH: frontend v${FRONTEND_VERSION} but backend v${backend}`);
    if(discovery<15)problems.unshift(`DISCOVERY MISMATCH: expected v15 but backend reports v${discovery||'?'}`);
    const healthy=versionOk&&discovery>=15&&allThreads&&gw.healthy&&!problems.filter(x=>/thread|heartbeat|mismatch/i.test(x)).length;
    consoleSet('historySearchConsoleOverall',healthy?(workMode==='search'?'SEARCH PRIORITY':(workMode==='playback'?'PLAYBACK PRIORITY':'RUNNING')):(versionOk?'ISSUE DETECTED':'BACKEND VERSION MISMATCH'));
    if(head){if(!versionOk||discovery<15)head.classList.add('mismatch');else if(problems.length)head.classList.add('problem');}
    consoleSet('historySearchConsoleWorker',`${Number(pool.active||0)}/${Number(pool.desired||0)} active • ${Number(pool.attemptsPerHour||0)}/hr`); renderWorkerGrid(data);
    consoleSet('historySearchConsoleQueue',`${Number(queue.due_now||0).toLocaleString()} due / ${Number(queue.gaps||0).toLocaleString()} coverage gaps`);
    consoleSet('historySearchConsoleBackground',workMode==='search'?'ACTIVE • SEARCH PRIORITY':(workMode==='playback'?'PAUSED • PLAYBACK PRIORITY':(bg.canWork?'ACTIVE':`YIELDING • ${String(bg.pauseReason||'unknown').replaceAll('-',' ')}`))); if(head&&!bg.canWork&&!problems.length&&workMode==='balanced')head.classList.add('yielding');
    consoleSet('historySearchConsoleYoutube',search.quotaExhausted?'QUOTA EXHAUSTED':(Number(search.cooldownSeconds||0)>0?`COOLDOWN ${Number(search.cooldownSeconds)}s`:'AVAILABLE')); 
    const used=Number(budget.used||0), limit=Number(budget.limit||budget.budget||0); consoleSet('historySearchConsoleBudget',limit?(used>=limit?`EXHAUSTED ${used}/${limit}`:`${used}/${limit} today`):`${used} used`);
    consoleSet('historySearchConsoleSilver',`${Number(silver.dayAssets||0)} daily • ${Number(silver.weekAssets||0)} weekly • ${Number(silver.roundAssets||0)} round`);
    const p=$('historySearchConsoleProblems'); if(p){if(problems.length){p.classList.remove('hidden');p.textContent=problems.join(' • ');}else{p.classList.add('hidden');p.textContent='';}}
    const out=$('historySearchConsoleOutput'); if(out){
      const g=data.greenGap||{}; const back=data.backfill||{}; const providers=data.providerConcurrency||{}; const claims=data.eventClaims||[];
      const workerLines=Object.keys(data.workers||{}).filter(k=>/^green-gap-\d+$/.test(k)).sort().map(k=>`[WORKER] ${consoleWorkerLine(k,(data.workers||{})[k]||{})}`);
      workerLines.push(`[WORKER] ${consoleWorkerLine('date-backfill',(data.workers||{})['date-backfill']||{})}`);
      workerLines.push(`[WORKER] ${consoleWorkerLine('rule-collections',(data.workers||{})['rule-collections']||{})}`);
      const header=[
        `[STATE] server uptime ${Math.round(Number(data.uptimeSeconds||0)/60)}m • workers ${allThreads?'alive':'CHECK THREADS'} • green attempts ${Number(g.attempts||0)} • green upgrades ${Number(g.upgradedToGreen||0)}`,
        `[GREEN POOL] ${Number(pool.active||0)}/${Number(pool.desired||0)} active • configured ${Number(pool.configured||0)} • attempts/hr ${Number(pool.attemptsPerHour||0)} • upgrades/hr ${Number(pool.upgradesPerHour||0)} • official-catchup/hr ${Number(pool.officialCatchupPerHour||0)}`,
        `[OFFICIAL SOURCE CATCH-UP] ${officialCatchupLine(catchup)}`,
        `[RULE GAME CATCH-UP] v${Number(ruleGame.version||0)} • ${String(ruleGame.status||'UNKNOWN')} • checked ${Number(ruleGame.checked||0)}/${Number(ruleGame.total||0)} • remaining ${Number(ruleGame.remaining||0)}${Object.keys(ruleGame.leagues||{}).length?' • '+['NFL','MLS','EPL'].filter(k=>(ruleGame.leagues||{})[k]).map(k=>{const x=ruleGame.leagues[k]||{};return `${k} ${Number(x.checked||0)}/${Number(x.total||0)}`;}).join(' | '):''}`,
        `[RULE COLLECTION CATCH-UP] v${Number(ruleCollections.version||0)} • ${ruleCollections.complete?'COMPLETE':(ruleCollections.running?'ACTIVE':'WAITING')} • dates ${Number(ruleCollections.datesChecked||0)} • candidates ${Number(ruleCollections.candidatesExamined||0)} • qualifying ${Number(ruleCollections.qualifying||0)} • new-assets ${Number(ruleCollections.newUniqueAssets||0)} • reused ${Number(ruleCollections.existingAssetsReused||0)} • new-links ${Number(ruleCollections.newCollectionLinks||0)} • duplicate-links ${Number(ruleCollections.duplicateLinksSuppressed||0)} • rejected ${Number(ruleCollections.rejected||0)}`,
        `[DISCOVERY EFFICIENCY] primary ${Number(eff.primaryPasses||0)} • primary-target ${Number(eff.primaryTargetHits||0)} • short ${Number(eff.shortCircuits||0)} • fallbacks ${Number(eff.fallbackAttempts||0)} • hits ${Number(eff.fallbackHits||0)} (${Number(eff.fallbackHitRate||0)}%) • avg ${Number(eff.averageFallbackSeconds||0)}s • est saved ${(Number(eff.estimatedSecondsSaved||0)/60).toFixed(1)}m`,
        ...workerLines,
        `[CATALOG] unindexed ${Number(queue.unindexed||queue.stale_version||0)} • searched-empty ${Number(queue.searched_empty||0)} • coverage-complete ${Number(queue.coverage_complete||0)} • playable-partial ${Number(queue.playable_partial||0)} • candidate-only ${Number(queue.candidate_only||0)}`,
      `[GAPS] coverage ${Number(queue.gaps||0)} • due ${Number(queue.due_now||0)} • recent ${Number(queue.recent_gaps||0)} • blue-only ${Number(queue.blue_only||0)}`,
      `[QUALITY UPGRADES] purple-only ${Number(queue.purple_only||0)} • due ${Number(queue.quality_upgrade_due||0)} • total work due ${Number(queue.work_due||0)}`,
      `[ASSOCIATIONS] assigned ${Number(assoc.assignedLinks||0)} • quarantined ${Number(assoc.quarantinedLinks||0)} • cross-event ${Number(assoc.crossEventAssets||0)} • team-mismatch ${Number(assoc.teamMismatch||0)} • date-mismatch ${Number(assoc.dateMismatch||0)} • season-mismatch ${Number(assoc.seasonMismatch||0)}`,
        `[QUARANTINE REASONS] ${Object.entries(assoc.quarantineReasons||{}).slice(0,6).map(([k,v])=>`${k}=${Number(v||0)}`).join(' • ')||'none'}`,
        `[CLAIMS] active ${claims.length}`,
        `[PROVIDERS] ${Object.entries(providers).map(([k,v])=>`${k} ${Number(v.active||0)}/${Number(v.limit||0)}${Number(v.waiting||0)?` +${Number(v.waiting)} waiting`:''}`).join(' • ')||'none'}`,
        `[SILVER] day ${Number(silver.dayCollections||0)} collections / ${Number(silver.dayAssets||0)} assets • week ${Number(silver.weekCollections||0)} collections / ${Number(silver.weekAssets||0)} assets • round ${Number(silver.roundCollections||0)} collections / ${Number(silver.roundAssets||0)} assets`,
        `[MEDIA OBJECTIVES] NFL quick ${Number(objectives.nflQuickGames||0)} • extended ${Number(objectives.nflExtendedGames||0)} • both ${Number(objectives.nflBothGames||0)} • missing quick ${Number(objectives.nflMissingQuick||0)} • missing extended ${Number(objectives.nflMissingExtended||0)} | MLS snapshot ${Number(objectives.mlsSnapshotGames||objectives.mlsSnapshots||0)} • highlights ${Number(objectives.mlsHighlightGames||objectives.mlsMatchHighlights||0)} • both ${Number(objectives.mlsBothGames||0)} • missing snapshot ${Number(objectives.mlsMissingSnapshot||0)} • missing highlights ${Number(objectives.mlsMissingHighlights||0)} | EPL quick ${Number(objectives.eplQuickGames||0)} • extended ${Number(objectives.eplExtendedGames||0)} • both ${Number(objectives.eplBothGames||0)} • missing quick ${Number(objectives.eplMissingQuick||0)} • missing extended ${Number(objectives.eplMissingExtended||0)} | BEST_GOALS ${Number(objectives.bestGoalsCollections||0)}/${Number(objectives.bestGoalsAssets||0)} • BEST_SAVES ${Number(objectives.bestSavesCollections||0)}/${Number(objectives.bestSavesAssets||0)}`,
        `[NFL PUBLIC SOURCES] public accepted ${Number(objRuntime.nflPublicAccepted||0)} • team accepted ${Number(objRuntime.nflTeamAccepted||0)} • gated ${Number(objRuntime.entitlementGated||0)} • individual-play ${Number(objRuntime.individualPlayRejected||0)} • postgame ${Number(objRuntime.postgameReactionRejected||0)} • non-playable ${Number(objRuntime.nonPlayableRejected||0)} • duration ${Number(objRuntime.durationRejected||0)} • event-mismatch ${Number(objRuntime.eventMismatchRejected||0)}`,
        `[MEDIA NORMALIZATION] duplicate-collapse ${Number(objRuntime.duplicatesCollapsed||0)} • postgame/reaction rejected ${Number(objRuntime.postgameReactionRejected||0)} • runtime NFL quick ${Number(objRuntime.nflQuickAccepted||0)} / extended ${Number(objRuntime.nflExtendedAccepted||0)} • MLS snapshot ${Number(objRuntime.mlsSnapshotAccepted||0)} / highlights ${Number(objRuntime.mlsMatchHighlightsAccepted||0)}`,
        `[GREEN] ${g.current?`NOW ${g.current}`:(g.lastDate?`LAST ${g.lastDate} ${g.lastLeague||''} ${String(g.lastBestTier||'none').toUpperCase()}→${String(g.lastResultTier||'none').toUpperCase()}`:'no completed attempt yet')}`,
        `[BACKFILL] ${backfillSummary(back)}`,
        `[YOUTUBE] search ${search.quotaExhausted?'QUOTA EXHAUSTED':(Number(search.cooldownSeconds||0)>0?'COOLDOWN':'OK')}${search.lastError?' • '+String(search.lastError):''}`,
        `[SEARCH BUDGET] ${used}/${limit||'?'}${limit&&used>=limit?' • EXHAUSTED':''}${budget.remainingByBucket?` • reserves recent ${Number(budget.remainingByBucket.recent||0)} / empty ${Number(budget.remainingByBucket.empty||0)} / blue ${Number(budget.remainingByBucket.blue||0)} / archive ${Number(budget.remainingByBucket.archive||0)}`:''}`,
        `[MODE] ${workMode.toUpperCase()} • playbackSuspended=${data.playbackSuspended?'YES':'NO'} • searchSuspended=${data.searchSuspended?'YES':'NO'}`,
        `[BACKGROUND] ${workMode==='search'?'ACTIVE • SEARCH PRIORITY':(workMode==='playback'?'PAUSED • PLAYBACK PRIORITY':(bg.canWork?'ACTIVE':`YIELDING • ${String(bg.pauseReason||'unknown').replaceAll('-',' ')}`))}`,
      ];
      const lines=(data.recent||[]).map(row=>`[${consoleTime(row.at)}] [${String(row.worker||'history')}] ${String(row.level||'INFO')} ${String(row.message||'')}`);
      out.textContent=[...header,'',...lines].join('\n'); out.scrollTop=out.scrollHeight;
    }
  }
  async function loadConsole(){
    if(state.consoleLoading)return; state.consoleLoading=true;
    try{
      const r=await fetch('/api/history/worker-console?limit=320',{cache:'no-store'});
      let data={}; try{data=await r.json();}catch(_){data={};}
      if(!r.ok||!data.ok){
        const backend=data.version||'unknown'; const msg=r.status===404?`Search Console endpoint missing. The live backend is probably older than frontend v${FRONTEND_VERSION}.`:(data.message||data.error||`HTTP ${r.status}`);
        const head=document.querySelector('.history-search-console-head'); if(head)head.classList.add('mismatch');
        consoleSet('historySearchConsoleOverall','BACKEND CHECK FAILED');consoleSet('historySearchConsoleVersion',`Frontend v${FRONTEND_VERSION} • backend ${backend}`);
        const out=$('historySearchConsoleOutput');if(out)out.textContent=`[ERROR] ${msg}\n\nOpen /api/status or check GitHub Actions backend deployment. The v4.1.12 workflow now refuses to publish Pages unless the public backend reports the same release version.`;
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
  function startAutoRefresh(){clearInterval(state.autoTimer);clearInterval(state.consoleTimer);state.autoTimer=setInterval(()=>{if(!$('historyAuditModal')?.classList.contains('hidden'))loadCurrent(false);},30000);state.consoleTimer=setInterval(()=>{if(!$('historyAuditModal')?.classList.contains('hidden'))loadConsole();},2500);}
  function stopAutoRefresh(){clearInterval(state.autoTimer);clearInterval(state.consoleTimer);state.autoTimer=null;state.consoleTimer=null;}
  function open(){
    const modal=$('historyAuditModal');if(!modal)return;modal.classList.remove('hidden');modal.setAttribute('aria-hidden','false');document.body.classList.add('audit-open');setAuditTab(state.tab,{loadData:false});loadCurrent(true);loadConsole();startAutoRefresh();
  }
  function close(){const modal=$('historyAuditModal');if(!modal)return;modal.classList.add('hidden');modal.setAttribute('aria-hidden','true');document.body.classList.remove('audit-open');stopAutoRefresh();}
  function startExport(base,params){const url=`${base}?${params.toString()}`;window.location.href=window.SBB_API?.url?window.SBB_API.url(url):url;}
  function exportGameFile(ext){startExport(`/api/history/audit.${ext}`,queryParams(false));}
  function exportSilverFile(ext){startExport(`/api/history/catalog/collections.${ext}`,silverQueryParams(false));}
  function exportFile(ext){
    // Derive the visible tab from the DOM as well as state.  This prevents a stale
    // state value from ever routing a Silver-screen export to the GAME endpoint.
    const silver=state.tab==='silver'||Boolean($('historyAuditTabSilver')?.classList.contains('active'));
    silver?exportSilverFile(ext):exportGameFile(ext);
  }
  let debounce=null;
  function queueLoad(){clearTimeout(debounce);debounce=setTimeout(()=>load(true),250);}
  function init(){
    $('openHistoryAuditBtn')?.addEventListener('click',open);$('historyAuditClose')?.addEventListener('click',close);$('historyAuditBackdrop')?.addEventListener('click',close);
    $('historyAuditRefresh')?.addEventListener('click',()=>{loadCurrent(false);loadConsole();});$('historyAuditCsv')?.addEventListener('click',()=>exportFile('csv'));$('historyAuditXlsx')?.addEventListener('click',()=>exportFile('xlsx'));
    // Dedicated Silver exports are intentionally hard-wired to collection endpoints.
    // They do not depend on shared-tab state and therefore cannot export GAME rows.
    $('historySilverCsv')?.addEventListener('click',()=>exportSilverFile('csv'));$('historySilverXlsx')?.addEventListener('click',()=>exportSilverFile('xlsx'));
    $('historyAuditTabGames')?.addEventListener('click',()=>setAuditTab('games'));$('historyAuditTabSilver')?.addEventListener('click',()=>setAuditTab('silver'));
    $('historySearchConsoleCopyIssues')?.addEventListener('click',()=>{if(state.lastConsole)copyConsoleText(consoleIssuesReport(state.lastConsole),'ISSUES COPIED');});
    $('historySearchConsoleCopyAll')?.addEventListener('click',()=>{if(state.lastConsole)copyConsoleText(consoleFullReport(state.lastConsole),'FULL CONSOLE COPIED');});
    $('historySearchConsoleDownload')?.addEventListener('click',downloadConsoleText);
    for(const id of ['historyModeSearch','historyModeBalanced','historyModePlayback'])$(id)?.addEventListener('click',ev=>setWorkMode(ev.currentTarget.dataset.mode));
    $('historyAuditPrev')?.addEventListener('click',()=>{state.offset=Math.max(0,state.offset-state.limit);load(false);});
    $('historyAuditNext')?.addEventListener('click',()=>{state.offset+=state.limit;load(false);});
    $('historySilverPrev')?.addEventListener('click',()=>{state.silverOffset=Math.max(0,state.silverOffset-state.silverLimit);loadSilver(false);});
    $('historySilverNext')?.addEventListener('click',()=>{state.silverOffset+=state.silverLimit;loadSilver(false);});
    ['historyAuditDateFrom','historyAuditDateTo','historyAuditLeague','historyAuditBestTier','historyAuditStatus'].forEach(id=>$(id)?.addEventListener('change',()=>load(true)));
    $('historyAuditSearch')?.addEventListener('input',queueLoad);
    ['historySilverScope','historySilverLeague','historySilverKind','historySilverFlag'].forEach(id=>$(id)?.addEventListener('change',()=>loadSilver(true)));
    let silverDebounce=null;const queueSilverLoad=()=>{clearTimeout(silverDebounce);silverDebounce=setTimeout(()=>loadSilver(true),250);};
    $('historySilverPeriod')?.addEventListener('input',queueSilverLoad);$('historySilverSearch')?.addEventListener('input',queueSilverLoad);
    window.addEventListener('keydown',ev=>{if(ev.key==='Escape'&&!$('historyAuditModal')?.classList.contains('hidden'))close();});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
  window.SBB_HISTORY_AUDIT={open,refresh:()=>{loadCurrent(false);loadConsole();},refreshConsole:loadConsole,setTab:setAuditTab};
})();

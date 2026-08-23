/* Sports Big Board v3.0.4 historical database audit view. */
(() => {
  const $ = id => document.getElementById(id);
  const state={offset:0,limit:100,total:0,loading:false,lastPayload:null};
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
    const t=summary.tiers||{}, b=summary.best||{};
    const map={historyAuditGames:summary.games||0,historyAuditVerified:summary.verifiedAssets||0,historyAuditGold:t.gold||0,historyAuditGreen:t.green||0,historyAuditPurple:t.extended||0,historyAuditBlue:t.blue||0,historyAuditUpgrade:summary.upgradePendingGames||0};
    for(const [id,val] of Object.entries(map)){const el=$(id);if(el)el.textContent=Number(val).toLocaleString();}
    const best=$('historyAuditBestSummary');
    if(best)best.textContent=`Best per game: ${Number(b.gold||0).toLocaleString()} Gold • ${Number(b.green||0).toLocaleString()} Green • ${Number(b.extended||0).toLocaleString()} Purple • ${Number(b.blue||0).toLocaleString()} Blue • ${Number(b.none||0).toLocaleString()} none`;
  }
  function renderRows(payload){
    const body=$('historyAuditTableBody'); if(!body)return;
    const rows=payload.rows||[];
    if(!rows.length){body.innerHTML='<tr><td colspan="9" class="audit-no-results">No games match these filters.</td></tr>';return;}
    body.innerHTML=rows.map(row=>{
      const tiers=row.tiers||{}; const best=row.bestTier||'none';
      const status=row.qualityComplete?'QUALITY COMPLETE':(row.upgradeEligible?'UPGRADE PENDING':String(row.discoveryState||'UNKNOWN').replaceAll('_',' '));
      return `<tr>
        <td class="audit-date">${esc(fmtDate(row.date))}</td>
        <td><span class="audit-league">${esc(row.league)}</span></td>
        <td class="audit-game"><strong>${esc(row.game)}</strong><small>${esc(row.eventId)}</small></td>
        <td class="audit-tier-cell gold">${mediaCell(tiers.gold,'gold')}</td>
        <td class="audit-tier-cell green">${mediaCell(tiers.green,'green')}</td>
        <td class="audit-tier-cell purple">${mediaCell(tiers.extended,'extended')}</td>
        <td class="audit-tier-cell blue">${mediaCell(tiers.blue,'blue')}</td>
        <td><span class="audit-best tier-${esc(best)}">${esc(tierLabel(best))}</span></td>
        <td class="audit-status"><strong>${esc(status)}</strong>${row.nextRetryAt?`<small>Retry ${new Date(row.nextRetryAt*1000).toLocaleString()}</small>`:''}</td>
      </tr>`;
    }).join('');
  }
  function updatePager(){
    const from=state.total?state.offset+1:0, to=Math.min(state.total,state.offset+state.limit);
    const el=$('historyAuditPageLabel');if(el)el.textContent=`${from.toLocaleString()}–${to.toLocaleString()} of ${state.total.toLocaleString()} games`;
    const prev=$('historyAuditPrev'); if(prev)prev.disabled=state.offset<=0;
    const next=$('historyAuditNext'); if(next)next.disabled=state.offset+state.limit>=state.total;
  }
  async function load(reset=false){
    if(state.loading)return; if(reset)state.offset=0; state.loading=true;
    $('historyAuditLoading')?.classList.remove('hidden');
    try{
      const r=await fetch(`/api/history/audit?${queryParams(true).toString()}`,{cache:'no-store'}); const data=await r.json();
      if(!r.ok||!data.ok)throw new Error(data.message||data.error||`HTTP ${r.status}`);
      state.total=Number(data.total||0);state.lastPayload=data;renderSummary(data.summary||{});renderRows(data);updatePager();
      const msg=$('historyAuditMessage');if(msg)msg.textContent=`Read-only view of the persistent cloud catalog • ${Number(data.repository?.days||0).toLocaleString()} dates stored`;
    }catch(err){
      const body=$('historyAuditTableBody');if(body)body.innerHTML=`<tr><td colspan="9" class="audit-no-results">Audit load failed: ${esc(err.message||err)}</td></tr>`;
    }finally{state.loading=false;$('historyAuditLoading')?.classList.add('hidden');}
  }
  function open(){
    const modal=$('historyAuditModal');if(!modal)return;modal.classList.remove('hidden');modal.setAttribute('aria-hidden','false');document.body.classList.add('audit-open');load(true);
  }
  function close(){const modal=$('historyAuditModal');if(!modal)return;modal.classList.add('hidden');modal.setAttribute('aria-hidden','true');document.body.classList.remove('audit-open');}
  function exportFile(ext){const url=`/api/history/audit.${ext}?${queryParams(false).toString()}`;window.location.href=window.SBB_API?.url?window.SBB_API.url(url):url;}
  let debounce=null;
  function queueLoad(){clearTimeout(debounce);debounce=setTimeout(()=>load(true),250);}
  function init(){
    $('openHistoryAuditBtn')?.addEventListener('click',open);$('historyAuditClose')?.addEventListener('click',close);$('historyAuditBackdrop')?.addEventListener('click',close);
    $('historyAuditRefresh')?.addEventListener('click',()=>load(false));$('historyAuditCsv')?.addEventListener('click',()=>exportFile('csv'));$('historyAuditXlsx')?.addEventListener('click',()=>exportFile('xlsx'));
    $('historyAuditPrev')?.addEventListener('click',()=>{state.offset=Math.max(0,state.offset-state.limit);load(false);});
    $('historyAuditNext')?.addEventListener('click',()=>{state.offset+=state.limit;load(false);});
    ['historyAuditDateFrom','historyAuditDateTo','historyAuditLeague','historyAuditBestTier','historyAuditStatus'].forEach(id=>$(id)?.addEventListener('change',()=>load(true)));
    $('historyAuditSearch')?.addEventListener('input',queueLoad);
    window.addEventListener('keydown',ev=>{if(ev.key==='Escape'&&!$('historyAuditModal')?.classList.contains('hidden'))close();});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
  window.SBB_HISTORY_AUDIT={open,refresh:()=>load(false)};
})();

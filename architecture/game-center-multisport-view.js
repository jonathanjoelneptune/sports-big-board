/* Sports Big Board v4.7.18 — persistent multisport Game Center summary.
   The line score is Game Center chrome, not tab content: it remains visible while
   OVERVIEW / TEAM STATS / PLAYERS / PLAYS change underneath it. MLB keeps the
   inning-by-inning R/H/E table; football/basketball/hockey use normalized periods.
   ESPN win probability is shown beneath the line score when the provider supplies it. */
(() => {
  'use strict';
  if(window.SBB_GAME_CENTER_MULTISPORT_VIEW?.installed)return;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const blank=v=>v===null||v===undefined||String(v).trim()==='';
  const teamName=t=>t?.abbreviation||t?.shortName||t?.name||t?.displayName||'—';
  const pct=v=>{const n=Number(v);return Number.isFinite(n)?`${n.toFixed(n%1?1:0)}%`:'—';};
  let scheduled=false,observer=null,rendering=false;

  function installStyles(){
    if(document.getElementById('sbb-gc-persistent-styles'))return;
    const style=document.createElement('style');style.id='sbb-gc-persistent-styles';
    style.textContent=`
      #gcPersistentSummary{display:grid;gap:8px;padding:8px 7px 0;flex:0 0 auto}
      #gcPersistentSummary:empty{display:none;padding:0}
      #gcPersistentSummary .gc-card{margin:0}
      #gcPersistentSummary .gc-card-title{display:flex;align-items:center;justify-content:space-between;gap:8px}
      #gcPersistentSummary .gc-card-title small{font-size:9px;opacity:.62;font-weight:700;letter-spacing:.08em}
      #gcPersistentSummary .gc-linescore th,#gcPersistentSummary .gc-linescore td{white-space:nowrap}
      #gcPersistentSummary .gc-win-prob-table th:first-child{min-width:78px;text-align:left}
      #gcPersistentSummary .gc-win-prob-table tr.latest{font-weight:800}
      #gcPersistentSummary .gc-win-prob-table small{display:block;font-size:9px;opacity:.58;font-weight:600}
      @media(max-width:720px){#gcPersistentSummary{padding-left:5px;padding-right:5px}.gc-table-scroll{overflow-x:auto}}
    `;
    document.head.appendChild(style);
  }

  function ensureHost(){
    let host=document.getElementById('gcPersistentSummary');
    if(host)return host;
    const content=document.getElementById('gameCenterContent');
    const tabs=document.getElementById('gcSections');
    if(!content||!tabs)return null;
    host=document.createElement('div');host.id='gcPersistentSummary';host.className='gc-persistent-summary';
    host.setAttribute('aria-live','polite');
    content.insertBefore(host,tabs);
    return host;
  }

  function baseballCard(gc){
    const s=gc?.scoreboard||{},innings=window.SBB_GAME_CENTER_LINESCORE?.reconcile?.(s,'MLB')||s.innings||[];
    if(!innings.length)return '';
    const away=s.away||{},home=s.home||{},tot=s.totals||{};
    const heads=innings.map(x=>`<th>${esc(x.num||'')}</th>`).join('');
    const row=(label,side)=>`<tr><th class="gc-lines-team">${esc(label)}</th>${innings.map(x=>`<td>${esc(blank(x?.[side])?'':x[side])}</td>`).join('')}<th>${esc(tot?.[side]?.runs??s?.[side]?.score??'—')}</th><th>${esc(tot?.[side]?.hits??'—')}</th><th>${esc(tot?.[side]?.errors??'—')}</th></tr>`;
    return `<div class="gc-card sbb-multisport-linescore sbb-baseball-linescore" data-sbb-gc-enhancement="linescore"><div class="gc-card-title">LINESCORE</div><div class="gc-table-scroll"><table class="gc-linescore"><thead><tr><th></th>${heads}<th>R</th><th>H</th><th>E</th></tr></thead><tbody>${row(teamName(away.team),'away')}${row(teamName(home.team),'home')}</tbody></table></div></div>`;
  }

  function periodCard(gc){
    const s=gc?.scoreboard||{},comp=String(gc?.competitionId||gc?.event?.competitionId||'').toUpperCase();
    if(comp==='MLB')return baseballCard(gc);
    const rows=window.SBB_GAME_CENTER_LINESCORE?.periods?.(s,comp)||s.periods||[];
    if(!rows.length)return '';
    const away=s.away||{},home=s.home||{};
    const heads=rows.map(r=>`<th>${esc(r.label||r.num||'')}</th>`).join('');
    const row=(label,side,total)=>`<tr><th class="gc-lines-team">${esc(label)}</th>${rows.map(r=>`<td>${esc(blank(r?.[side])?'':r[side])}</td>`).join('')}<th>${esc(blank(total)?'—':total)}</th></tr>`;
    return `<div class="gc-card sbb-multisport-linescore" data-sbb-gc-enhancement="linescore"><div class="gc-card-title">LINESCORE</div><div class="gc-table-scroll"><table class="gc-linescore"><thead><tr><th></th>${heads}<th>T</th></tr></thead><tbody>${row(teamName(away.team),'away',away.score)}${row(teamName(home.team),'home',home.score)}</tbody></table></div></div>`;
  }

  function sampledProbability(rows,max=12){
    rows=(rows||[]).filter(x=>x&&Number.isFinite(Number(x.away))&&Number.isFinite(Number(x.home)));
    if(rows.length<=max)return rows;
    const chosen=[];const seen=new Set();
    for(let i=0;i<max;i++){
      const idx=Math.round(i*(rows.length-1)/(max-1));
      if(!seen.has(idx)){seen.add(idx);chosen.push(rows[idx]);}
    }
    return chosen;
  }

  function probabilityCard(gc){
    const s=gc?.scoreboard||{},rows=sampledProbability(s.winProbability||gc?.winProbability||[]);
    if(!rows.length)return '';
    const away=teamName(s.away?.team),home=teamName(s.home?.team),showTie=rows.some(r=>Number(r.tie||0)>0.05);
    const body=rows.map((r,i)=>{
      const score=(!blank(r.scoreAway)||!blank(r.scoreHome))?`<small>${esc(r.scoreAway)}–${esc(r.scoreHome)}</small>`:'';
      return `<tr class="${i===rows.length-1?'latest':''}"><th><span>${esc(r.label||'')}</span>${score}</th><td>${pct(r.away)}</td><td>${pct(r.home)}</td>${showTie?`<td>${pct(r.tie||0)}</td>`:''}</tr>`;
    }).join('');
    return `<div class="gc-card sbb-win-probability" data-sbb-gc-enhancement="win-probability"><div class="gc-card-title">WIN PROBABILITY <small>ESPN</small></div><div class="gc-table-scroll"><table class="gc-player-table gc-win-prob-table"><thead><tr><th>GAME</th><th>${esc(away)}</th><th>${esc(home)}</th>${showTie?'<th>TIE</th>':''}</tr></thead><tbody>${body}</tbody></table></div></div>`;
  }

  function removeLegacyOverviewLinescore(){
    const overview=document.getElementById('gcOverview');
    if(!overview)return;
    for(const title of overview.querySelectorAll('.gc-card-title')){
      if(String(title.textContent||'').trim().toUpperCase()==='LINESCORE')title.closest('.gc-card')?.remove();
    }
  }

  function enhance(){
    scheduled=false;if(rendering)return;
    const view=window.SBB_GAME_CENTER_VIEW,gc=view?.data?.(),host=ensureHost();
    if(!host)return;
    rendering=true;
    try{
      installStyles();
      if(!gc){host.replaceChildren();return;}
      const comp=String(gc?.competitionId||gc?.event?.competitionId||'').toUpperCase();
      const status=document.getElementById('gcStatus');
      if(status&&['CFB','NBA'].includes(comp))status.textContent=String(status.textContent||'').replace(/(^| • )P(\d+)(?= •|$)/g,'$1Q$2');
      const html=periodCard(gc)+probabilityCard(gc);
      if(host.innerHTML!==html)host.innerHTML=html;
      removeLegacyOverviewLinescore();
    }finally{rendering=false;}
  }
  function schedule(){if(scheduled||rendering)return;scheduled=true;queueMicrotask(enhance);}
  function bind(){
    installStyles();const content=document.getElementById('gameCenterContent');
    if(!content){setTimeout(bind,100);return;}
    ensureHost();
    observer=new MutationObserver(schedule);observer.observe(content,{childList:true,subtree:true,characterData:true});
    window.addEventListener('sbb:selected-event-change',schedule);
    window.addEventListener('sbb:selected-event-cleared',schedule);
    schedule();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
  window.SBB_GAME_CENTER_MULTISPORT_VIEW=Object.freeze({installed:true,version:'4.7.18',enhance,periodCard,baseballCard,probabilityCard,ensureHost});
})();

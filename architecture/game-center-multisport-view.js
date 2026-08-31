/* Sports Big Board v4.7.20 — persistent multisport Game Center summary.
   This module now binds to the PUBLIC Game Center cache/selected-event contracts,
   not to private lexical state inside ui/game-center-view.js.  v4.7.18 attempted
   view.data(), but the real frozen renderer never exported that method, so the
   enhancement always received undefined in production.

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
  let scheduled=false,observer=null,rendering=false,currentData=null,currentEvent=null;

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
      #gcPersistentSummary .gc-win-chart{padding:4px 4px 8px}
      #gcPersistentSummary .gc-win-chart svg{display:block;width:100%;height:auto;min-height:180px;max-height:280px;overflow:visible}
      #gcPersistentSummary .gc-win-grid{stroke:var(--line,#25303a);stroke-width:1;opacity:.7;vector-effect:non-scaling-stroke}
      #gcPersistentSummary .gc-win-grid-mid{stroke:var(--muted,#8f9aa6);stroke-dasharray:5 5;opacity:.7}
      #gcPersistentSummary .gc-win-line{fill:none;stroke-width:3;stroke-linecap:round;stroke-linejoin:round;vector-effect:non-scaling-stroke}
      #gcPersistentSummary .gc-win-away{stroke:var(--accent,#ef3b2d)}
      #gcPersistentSummary .gc-win-home{stroke:var(--blue,#2494ff)}
      #gcPersistentSummary .gc-win-tie{stroke:var(--muted,#8f9aa6);stroke-width:2;stroke-dasharray:5 4}
      #gcPersistentSummary .gc-win-dot-away{fill:var(--accent,#ef3b2d)}
      #gcPersistentSummary .gc-win-dot-home{fill:var(--blue,#2494ff)}
      #gcPersistentSummary .gc-win-axis{fill:var(--muted,#8f9aa6);font-size:11px;font-weight:700}
      #gcPersistentSummary .gc-win-legend{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:2px 8px 0;font-size:11px;font-weight:800}
      #gcPersistentSummary .gc-win-legend span{display:inline-flex;align-items:center;gap:6px}
      #gcPersistentSummary .gc-win-swatch{width:18px;height:3px;border-radius:999px;background:currentColor}
      #gcPersistentSummary .gc-win-legend-away{color:var(--accent,#ef3b2d)}
      #gcPersistentSummary .gc-win-legend-home{color:var(--blue,#2494ff)}
      #gcPersistentSummary .gc-win-legend-tie{color:var(--muted,#8f9aa6)}
      #gcPersistentSummary .gc-win-latest{margin-left:auto;color:var(--muted,#8f9aa6);font-weight:700}
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

  function sampledProbability(rows,max=160){
    rows=(rows||[]).filter(x=>x&&Number.isFinite(Number(x.away))&&Number.isFinite(Number(x.home)));
    if(rows.length<=max)return rows;
    const chosen=[];const seen=new Set();
    for(let i=0;i<max;i++){
      const idx=Math.round(i*(rows.length-1)/(max-1));
      if(!seen.has(idx)){seen.add(idx);chosen.push(rows[idx]);}
    }
    if(chosen[chosen.length-1]!==rows[rows.length-1])chosen.push(rows[rows.length-1]);
    return chosen;
  }
  function clampProbability(v){const n=Number(v);return Number.isFinite(n)?Math.max(0,Math.min(100,n)):0;}
  function probabilityPoints(rows,key,left,top,width,height){
    const span=Math.max(1,rows.length-1);
    return rows.map((r,i)=>{
      const x=left+(i/span)*width;
      const y=top+((100-clampProbability(r?.[key]))/100)*height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
  }

  function probabilityCard(gc){
    const s=gc?.scoreboard||{},rows=sampledProbability(s.winProbability||gc?.winProbability||[]);
    if(!rows.length)return '';
    const away=teamName(s.away?.team),home=teamName(s.home?.team),showTie=rows.some(r=>Number(r.tie||0)>0.05);
    const W=820,H=260,left=44,right=16,top=18,bottom=34,plotW=W-left-right,plotH=H-top-bottom;
    const awayPts=probabilityPoints(rows,'away',left,top,plotW,plotH);
    const homePts=probabilityPoints(rows,'home',left,top,plotW,plotH);
    const tiePts=showTie?probabilityPoints(rows,'tie',left,top,plotW,plotH):'';
    const grid=[100,75,50,25,0].map(v=>{
      const y=top+((100-v)/100)*plotH;
      const cls=v===50?'gc-win-grid gc-win-grid-mid':'gc-win-grid';
      return `<line class="${cls}" x1="${left}" x2="${W-right}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}"></line><text class="gc-win-axis" x="${left-7}" y="${(y+4).toFixed(1)}" text-anchor="end">${v}%</text>`;
    }).join('');
    const last=rows[rows.length-1],lastX=W-right;
    const awayY=top+((100-clampProbability(last.away))/100)*plotH;
    const homeY=top+((100-clampProbability(last.home))/100)*plotH;
    const latestScore=(!blank(last.scoreAway)||!blank(last.scoreHome))?` • ${esc(last.scoreAway)}–${esc(last.scoreHome)}`:'';
    const latestLabel=`${esc(last.label||'LATEST')}${latestScore}`;
    return `<div class="gc-card sbb-win-probability" data-sbb-gc-enhancement="win-probability">
      <div class="gc-card-title">WIN PROBABILITY <small>ESPN</small></div>
      <div class="gc-win-legend">
        <span class="gc-win-legend-away"><i class="gc-win-swatch"></i>${esc(away)} ${pct(last.away)}</span>
        <span class="gc-win-legend-home"><i class="gc-win-swatch"></i>${esc(home)} ${pct(last.home)}</span>
        ${showTie?`<span class="gc-win-legend-tie"><i class="gc-win-swatch"></i>TIE ${pct(last.tie||0)}</span>`:''}
        <span class="gc-win-latest">${latestLabel}</span>
      </div>
      <div class="gc-win-chart">
        <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Win probability graph for ${esc(away)} and ${esc(home)}">
          ${grid}
          <polyline class="gc-win-line gc-win-away" points="${awayPts}"></polyline>
          <polyline class="gc-win-line gc-win-home" points="${homePts}"></polyline>
          ${showTie?`<polyline class="gc-win-line gc-win-tie" points="${tiePts}"></polyline>`:''}
          <circle class="gc-win-dot-away" cx="${lastX}" cy="${awayY.toFixed(1)}" r="4"><title>${esc(away)} ${pct(last.away)} • ${latestLabel}</title></circle>
          <circle class="gc-win-dot-home" cx="${lastX}" cy="${homeY.toFixed(1)}" r="4"><title>${esc(home)} ${pct(last.home)} • ${latestLabel}</title></circle>
          <text class="gc-win-axis" x="${left}" y="${H-8}">START</text>
          <text class="gc-win-axis" x="${W-right}" y="${H-8}" text-anchor="end">LATEST</text>
        </svg>
      </div>
    </div>`;
  }

  function removeLegacyOverviewLinescore(){
    const overview=document.getElementById('gcOverview');
    if(!overview)return;
    for(const title of overview.querySelectorAll('.gc-card-title')){
      if(String(title.textContent||'').trim().toUpperCase()==='LINESCORE')title.closest('.gc-card')?.remove();
    }
  }

  function cacheDataFor(event){
    if(!event)return null;
    try{return window.SBB_GAME_CENTER?.peek?.(event)||null;}catch(_){return null;}
  }

  function syncFromPublicCache(){
    const event=window.SBB_SELECTED_EVENT?.get?.()||currentEvent;
    if(!event)return false;
    currentEvent=event;
    const data=cacheDataFor(event);
    if(data){currentData=data;return true;}
    return false;
  }

  function selectionChanged(event){
    currentEvent=event||null;
    currentData=event?cacheDataFor(event):null;
    schedule();
  }

  function enhance(){
    scheduled=false;if(rendering)return;
    syncFromPublicCache();
    const gc=currentData,host=ensureHost();
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
    // ui/game-center-view.js is the ONLY request owner. This enhancement only reads
    // the public cache after the owner renders/mutates Game Center DOM. A second
    // SBB_GAME_CENTER.get() consumer was the v4.7.19 trigger for Request Broker
    // `no-active-consumers` races during selection replacement.
    observer=new MutationObserver(()=>{syncFromPublicCache();schedule();});observer.observe(content,{childList:true,subtree:true,characterData:true});
    window.SBB_SELECTED_EVENT?.subscribe?.(selectionChanged);
    selectionChanged(window.SBB_SELECTED_EVENT?.get?.()||null);
    window.addEventListener('sbb:selected-event-change',()=>selectionChanged(window.SBB_SELECTED_EVENT?.get?.()||null));
    window.addEventListener('sbb:selected-event-cleared',()=>selectionChanged(null));
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
  window.SBB_GAME_CENTER_MULTISPORT_VIEW=Object.freeze({installed:true,version:'4.7.20',winProbabilityView:'GRAPH_1',enhance,periodCard,baseballCard,probabilityCard,ensureHost,syncFromPublicCache,get data(){return currentData;}});
})();

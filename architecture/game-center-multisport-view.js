/* Sports Big Board v4.7.17 — multisport Game Center presentation layer.
   Enhances the existing renderer without replacing its selection/polling owner.
   Period linescores are injected at the top for football/basketball/hockey and
   ESPN win probability is shown when the provider actually returns it. */
(() => {
  'use strict';
  if(window.SBB_GAME_CENTER_MULTISPORT_VIEW?.installed)return;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const blank=v=>v===null||v===undefined||String(v).trim()==='';
  const teamName=t=>t?.abbreviation||t?.shortName||t?.name||t?.displayName||'—';
  const pct=v=>{const n=Number(v);return Number.isFinite(n)?`${n.toFixed(n%1?1:0)}%`:'—';};
  let scheduled=false,observer=null;

  function periodCard(gc){
    const s=gc?.scoreboard||{},comp=String(gc?.competitionId||gc?.event?.competitionId||'').toUpperCase();
    if(comp==='MLB')return '';
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

  function enhance(){
    scheduled=false;
    const view=window.SBB_GAME_CENTER_VIEW,host=document.getElementById('gcOverview');
    const gc=view?.data?.();
    if(!host||!gc)return;
    if(host.querySelector('[data-sbb-gc-enhancement]'))return;
    const lines=periodCard(gc),prob=probabilityCard(gc);
    const comp=String(gc?.competitionId||gc?.event?.competitionId||'').toUpperCase();
    const status=document.getElementById('gcStatus');
    if(status&&['CFB','NBA'].includes(comp))status.textContent=String(status.textContent||'').replace(/(^| • )P(\d+)(?= •|$)/g,'$1Q$2');
    if(lines){
      const legacy=host.querySelector('.gc-basic-overview')?.closest('.gc-card');
      if(legacy)legacy.remove();
    }
    if(!lines&&!prob)return;
    const scoring=[...host.children].find(x=>x.querySelector?.('.gc-card-title')?.textContent?.includes('SCORING / KEY PLAYS'))||null;
    const wrap=document.createElement('div');
    wrap.innerHTML=lines+prob;
    const nodes=[...wrap.children];
    for(const node of nodes)host.insertBefore(node,scoring||host.firstChild);
  }
  function schedule(){if(scheduled)return;scheduled=true;queueMicrotask(enhance);}
  function bind(){
    const host=document.getElementById('gcOverview');
    if(!host){setTimeout(bind,100);return;}
    observer=new MutationObserver(schedule);observer.observe(host,{childList:true,subtree:false});
    window.addEventListener('sbb:selected-event-change',schedule);
    window.addEventListener('sbb:selected-event-cleared',schedule);
    schedule();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
  window.SBB_GAME_CENTER_MULTISPORT_VIEW=Object.freeze({installed:true,version:'4.7.17',enhance,periodCard,probabilityCard});
})();

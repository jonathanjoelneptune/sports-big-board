/* Sports Big Board v5.1.18 — tennis ribbon + Game Center presentation.
   Compact player labels are "#rank F. Lastname" when ranking is known. Round
   abbreviations are added to tennis score cards, and the right-side Game Center
   may use the available page height instead of being clipped to video height. */
(() => {
  'use strict';
  if(window.SBB_TENNIS_PRESENTATION_V5118?.version==='5.1.18')return;
  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const fetched=new Map(),inflight=new Map();let applying=false,decorateTimer=null;
  const api=p=>window.SBB_API?.url?window.SBB_API.url(p):p;
  function registryRows(){try{return window.SBB_FRONTEND_REGISTRY?.snapshot?.().competitions||[];}catch(_){return [];}}
  function competition(id){id=upper(id);return registryRows().find(x=>upper(x.id)===id)||null;}
  function isTennisId(id){return clean(competition(id)?.sportId).toLowerCase()==='tennis';}
  function eventLeague(evt){return upper(evt?.competitionId||evt?.__sbbLeague||evt?.league);}
  function fullName(team){return clean(team?.displayName||team?.name||team?.shortName||team?.abbreviation);}
  function surname(name){
    name=clean(name).replace(/^#?\d+\s+/,'');if(!name)return '';
    const p=name.split(/\s+/),particles=new Set(['de','del','della','di','da','dos','van','von','der','le','la']);
    if(p.length>1&&particles.has(p[p.length-2].toLowerCase()))return `${p[p.length-2]} ${p[p.length-1]}`;
    return p[p.length-1]||name;
  }
  function compact(name,rank=''){
    name=clean(name).replace(/^#?\d+\s+/,'');if(!name)return '';
    if(/[\/&+]/.test(name))return name.split(/\s*(?:\/|&|\+)\s*/).map(x=>compact(x,'')).join('/').slice(0,24);
    const p=name.split(/\s+/),last=surname(name),first=p.length>1?`${p[0][0].toUpperCase()}. `:'';
    const r=clean(rank);return `${r&& !['0','999','—'].includes(r)?`#${r} `:''}${first}${last}`.trim().slice(0,26);
  }
  function roundShort(value){
    const v=clean(value).toLowerCase();if(!v)return '';
    if(/quarter/.test(v))return 'QF';if(/semi/.test(v))return 'SF';if(/^final$|championship/.test(v))return 'F';
    if(/round of 16|round\s*16|fourth round/.test(v))return 'R16';if(/round of 32|round\s*32/.test(v))return 'R32';if(/round of 64|round\s*64/.test(v))return 'R64';
    const n=(v.match(/(?:round|r)\s*(\d+)/)||[])[1];if(n)return `R${n}`;
    if(/first round|opening round/.test(v))return 'R1';if(/second round/.test(v))return 'R2';if(/third round/.test(v))return 'R3';
    if(/qual/.test(v))return 'Q';return clean(value).slice(0,5).toUpperCase();
  }
  function teamPatch(team,extra={}){
    const out={...(team||{}),...(extra||{})};const name=fullName(out),rank=clean(out.rank||out.seed||out.ranking),short=compact(name,rank);
    if(name){out.name=out.name||name;out.displayName=name;}if(short){out.shortName=short;out.abbreviation=short;}if(rank)out.rank=rank;
    return out;
  }
  function enrichRows(date,cid,presentation=[]){
    if(applying)return 0;const store=window.SBB_SCORE_DATE;if(!store)return 0;
    const rows=store.matches(date,cid);if(!rows.length)return 0;
    const byId=new Map((presentation||[]).map(x=>[clean(x.eventId),x]));let changed=0;
    const next=rows.map(row=>{
      const id=clean(row.scoreEventId||row.eventId||row.matchId||row.id),p=byId.get(id)||{};
      const away=teamPatch(row.awayTeam||row.away||{},p.awayTeam||{}),home=teamPatch(row.homeTeam||row.home||{},p.homeTeam||{});
      const round=clean(p.round||row.round||row.stage),short=roundShort(round);
      const out={...row,away,home,awayTeam:away,homeTeam:home,participants:[away,home],sportId:'tennis',gameCenterProviderHint:'tennis',tennisRound:round,tennisRoundShort:short};
      if(JSON.stringify([away.shortName,home.shortName,short])!==JSON.stringify([row.awayTeam?.shortName||row.away?.shortName,row.homeTeam?.shortName||row.home?.shortName,row.tennisRoundShort||'']))changed++;
      return out;
    });
    if(changed){applying=true;try{store.setMatches(date,cid,next,{source:'tennis-presentation-v5118',authoritative:true});}finally{applying=false;}}
    scheduleDecorate();return changed;
  }
  async function fetchPresentation(date,cid){
    const key=`${cid}|${date}`,hit=fetched.get(key);if(hit&&Date.now()-hit.at<60000)return hit.rows;
    if(inflight.has(key))return inflight.get(key);
    const job=(async()=>{
      try{
        const r=await fetch(api(`/api/tennis/presentation?competition=${encodeURIComponent(cid)}&date=${encodeURIComponent(date)}`),{cache:'no-store'});
        if(!r.ok)throw new Error(`HTTP ${r.status}`);const p=await r.json(),rows=Array.isArray(p?.rows)?p.rows:[];
        fetched.set(key,{at:Date.now(),rows});enrichRows(date,cid,rows);
        // First response starts backend date warming. Re-read once so newly cached
        // ESPN rank/round information flows into the ribbon without a user click.
        if(p?.warming)setTimeout(()=>{fetched.delete(key);fetchPresentation(date,cid).catch(()=>{});},2600);
        return rows;
      }catch(_){return hit?.rows||[];}
    })().finally(()=>inflight.delete(key));inflight.set(key,job);return job;
  }
  function hydrateDate(date){
    date=clean(date).slice(0,10);if(!date)return;
    for(const row of registryRows()){
      const cid=upper(row.id);if(clean(row.sportId).toLowerCase()!=='tennis')continue;
      if(window.SBB_SCORE_DATE?.matches?.(date,cid)?.length){enrichRows(date,cid,fetched.get(`${cid}|${date}`)?.rows||[]);fetchPresentation(date,cid).catch(()=>{});}
    }
  }
  function decorateCards(){
    const store=window.SBB_SCORE_DATE,date=store?.snapshot?.().browseDate;if(!store||!date)return;
    const tennis=[];for(const row of registryRows())if(clean(row.sportId).toLowerCase()==='tennis')tennis.push(...store.matches(date,upper(row.id)));
    document.querySelectorAll('.score-card').forEach(card=>{
      card.querySelector('.sbb-tennis-round-chip')?.remove();
      const text=clean(card.innerText).toLowerCase();let match=null;
      for(const row of tennis){const a=surname(fullName(row.awayTeam||row.away||{})).toLowerCase(),h=surname(fullName(row.homeTeam||row.home||{})).toLowerCase();if(a&&h&&text.includes(a)&&text.includes(h)){match=row;break;}}
      if(!match)return;const label=clean(match.tennisRoundShort||roundShort(match.round||match.stage));if(!label)return;
      card.classList.add('sbb-tennis-score-card');const chip=document.createElement('span');chip.className='sbb-tennis-round-chip';chip.textContent=label;chip.title=clean(match.tennisRound||match.round||match.stage||label);card.appendChild(chip);
    });
  }
  function scheduleDecorate(){clearTimeout(decorateTimer);decorateTimer=setTimeout(decorateCards,80);}
  function selectedIsTennis(evt){const id=eventLeague(evt);return clean(evt?.sportId||evt?.event?.sportId).toLowerCase()==='tennis'||isTennisId(id);}
  function applySelected(evt){
    const tennis=selectedIsTennis(evt);document.body?.classList.toggle('sbb-tennis-game-center-active',tennis);
    const labels={overview:'OVERVIEW','team-stats':tennis?'MATCH STATS':'TEAM STATS',players:'PLAYERS',plays:tennis?'SETS':'PLAYS'};
    document.querySelectorAll('[data-gc-section]').forEach(btn=>{const k=btn.dataset.gcSection;if(labels[k])btn.textContent=labels[k];});
  }
  function style(){
    if(document.getElementById('sbbTennisPresentationV5118Style'))return;const el=document.createElement('style');el.id='sbbTennisPresentationV5118Style';el.textContent=`
      .score-card.sbb-tennis-score-card{position:relative}
      .sbb-tennis-round-chip{position:absolute;top:3px;left:50%;transform:translateX(-50%);font-size:7px;line-height:1;padding:2px 4px;border:1px solid rgba(76,210,255,.42);border-radius:7px;background:rgba(4,17,25,.88);color:#9eeaff;font-weight:800;letter-spacing:.04em;pointer-events:none}
      @media (min-width:900px){
        body.sbb-tennis-game-center-active #infoDrawer:not(.is-closed){height:auto!important;max-height:none!important;align-self:stretch!important;overflow:visible!important}
        body.sbb-tennis-game-center-active #gameCenterPane,body.sbb-tennis-game-center-active #gameCenterContent{height:auto!important;max-height:none!important;overflow:visible!important}
        body.sbb-tennis-game-center-active #gameCenterPane{min-height:calc(100vh - 235px)}
        body.sbb-tennis-game-center-active #gameCenterContent .gc-section{max-height:none!important;overflow:visible!important}
      }`;
    document.head.appendChild(el);
  }
  function boot(){
    style();try{window.SBB_SELECTED_EVENT?.subscribe?.(evt=>applySelected(evt));applySelected(window.SBB_SELECTED_EVENT?.get?.());}catch(_){}
    try{window.SBB_SCORE_DATE?.subscribe?.((snap,meta)=>{if(applying)return;if(['browse','matches','loaded'].includes(meta?.action||'')){hydrateDate(meta?.date||snap.browseDate);scheduleDecorate();}});}catch(_){}
    const date=window.SBB_SCORE_DATE?.snapshot?.().browseDate;hydrateDate(date);scheduleDecorate();
    // Ribbon DOM is rebuilt by several legacy render paths. A very light 1.5s
    // decorator keeps round badges attached without observing the whole document.
    setInterval(()=>{if(!document.hidden)decorateCards();},1500);
  }
  window.SBB_TENNIS_PRESENTATION_V5118=Object.freeze({version:'5.1.18',compact,roundShort,hydrateDate,decorateCards});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();

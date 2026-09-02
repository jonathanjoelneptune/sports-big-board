/* Sports Big Board v5.1.19 — single tennis presentation layer.

   This module is intentionally presentation-only. It performs no network I/O,
   does not mutate ScoreDateStore, and does not maintain a polling loop. Canonical
   tennis identity/round fields arrive through Competition Registry + Day State;
   this layer only chooses compact labels and decorates the current DOM.
*/
(() => {
  'use strict';
  if(window.SBB_TENNIS_PRESENTATION?.version==='5.1.19')return;

  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  let decorateQueued=false;

  function registryRows(){
    try{return window.SBB_FRONTEND_REGISTRY?.snapshot?.().competitions||[];}catch(_){return [];}
  }
  function competition(id){
    id=upper(id);
    return registryRows().find(x=>upper(x?.id)===id)||null;
  }
  function eventCompetition(evt){return upper(evt?.competitionId||evt?.__sbbLeague||evt?.league);}
  function isTennis(evt){
    if(clean(evt?.sportId||evt?.event?.sportId).toLowerCase()==='tennis')return true;
    return clean(competition(eventCompetition(evt))?.sportId).toLowerCase()==='tennis';
  }

  function surname(value){
    let text=clean(value).replace(/^#?\d+\s+/,'');
    if(!text)return '';
    if(/[\/&+]/.test(text))return text.split(/\s*(?:\/|&|\+)\s*/).map(surname).filter(Boolean).join('/').slice(0,22);
    if(text.includes(','))return text.split(',',1)[0].trim().slice(0,18);
    const parts=text.split(/\s+/),particles=new Set(['de','del','della','di','da','dos','van','von','der','le','la']);
    if(parts.length>1&&particles.has(parts.at(-2).toLowerCase()))return `${parts.at(-2)} ${parts.at(-1)}`.slice(0,18);
    return (parts.at(-1)||text).slice(0,18);
  }
  function compactName(value,rank=''){
    let text=clean(value).replace(/^#?\d+\s+/,'');if(!text)return '';
    let label;
    if(/[\/&+]/.test(text))label=text.split(/\s*(?:\/|&|\+)\s*/).map(x=>compactName(x,'')).filter(Boolean).join('/');
    else{const parts=text.split(/\s+/);label=parts.length<=1?text:`${parts[0][0]?.toUpperCase()||''}. ${surname(text)}`.trim();}
    const r=clean(rank);if(r&&!['0','999','—'].includes(r))label=`#${r} ${label}`;
    return label.slice(0,26);
  }
  function roundFields(value){
    const raw=clean(value),v=raw.toLowerCase();
    if(!v||['round','rnd','main draw'].includes(v))return {roundNumber:null,roundName:'',displayRound:''};
    if(/quarter/.test(v))return {roundNumber:null,roundName:raw||'Quarterfinal',displayRound:'QF'};
    if(/semi/.test(v))return {roundNumber:null,roundName:raw||'Semifinal',displayRound:'SF'};
    if(/^(final|finals|championship)$/.test(v))return {roundNumber:null,roundName:raw||'Final',displayRound:'F'};
    if(/round of 16|round\s*16|fourth round/.test(v))return {roundNumber:null,roundName:raw,displayRound:'R16'};
    if(/round of 32|round\s*32/.test(v))return {roundNumber:null,roundName:raw,displayRound:'R32'};
    if(/round of 64|round\s*64/.test(v))return {roundNumber:null,roundName:raw,displayRound:'R64'};
    const named={'first round':1,'opening round':1,'second round':2,'third round':3};
    if(named[v]){const n=named[v];return {roundNumber:n,roundName:`Round ${n}`,displayRound:`R${n}`};}
    const m=v.match(/(?:round|r)\s*(\d+)/);if(m){const n=Number(m[1]);return {roundNumber:n,roundName:`Round ${n}`,displayRound:`R${n}`};}
    if(/qual/.test(v))return {roundNumber:null,roundName:raw,displayRound:'Q'};
    return {roundNumber:null,roundName:raw,displayRound:''};
  }
  function fullName(team){return clean(team?.displayName||team?.name||team?.shortName||team?.abbreviation);}
  function rankOf(team){return clean(team?.rank||team?.seed||team?.ranking);}
  function roundOf(match){
    const explicit=clean(match?.tennisRoundShort||match?.displayRound);
    if(explicit&&upper(explicit)!=='ROUND')return explicit;
    return roundFields(match?.tennisRound||match?.roundName||match?.round||match?.stage).displayRound;
  }

  function decorateCards(){
    decorateQueued=false;
    document.querySelectorAll('.score-card').forEach(card=>{
      card.querySelector('.sbb-tennis-round-chip')?.remove();
      card.classList.remove('sbb-tennis-score-card');
      const match=card.__sbbMatch;
      if(!match||!isTennis(match))return;
      const away=match.awayTeam||match.away||{},home=match.homeTeam||match.home||{};
      const teamLabels=[...card.querySelectorAll('.score-team-abbr')];
      [[away,teamLabels[0]],[home,teamLabels[1]]].forEach(([team,node])=>{
        if(!node)return;const full=fullName(team),compact=compactName(full,rankOf(team));
        if(compact)node.textContent=compact;if(full)node.title=full;
      });
      const label=roundOf(match);if(!label)return;
      card.classList.add('sbb-tennis-score-card');
      const chip=document.createElement('span');chip.className='sbb-tennis-round-chip';chip.textContent=label;
      chip.title=clean(match?.tennisRound||match?.roundName||match?.round||match?.stage||label);
      card.appendChild(chip);
    });
  }
  function scheduleDecorate(){
    if(decorateQueued)return;decorateQueued=true;
    const run=()=>requestAnimationFrame(()=>decorateCards());
    if(typeof requestAnimationFrame==='function')run();else setTimeout(decorateCards,0);
  }

  function applySelected(evt){
    const tennis=isTennis(evt);document.body?.classList.toggle('sbb-tennis-game-center-active',tennis);
    const labels={overview:'OVERVIEW','team-stats':tennis?'MATCH STATS':'TEAM STATS',players:'PLAYERS',plays:tennis?'SETS':'PLAYS'};
    document.querySelectorAll('[data-gc-section]').forEach(btn=>{const key=btn.dataset.gcSection;if(labels[key])btn.textContent=labels[key];});
  }
  function style(){
    if(document.getElementById('sbbTennisPresentationStyle'))return;
    const el=document.createElement('style');el.id='sbbTennisPresentationStyle';el.textContent=`
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
    style();
    try{window.SBB_SELECTED_EVENT?.subscribe?.(evt=>applySelected(evt));applySelected(window.SBB_SELECTED_EVENT?.get?.());}catch(_){}
    try{window.SBB_SCORE_DATE?.subscribe?.((_snap,meta)=>{if(['browse','matches','loaded'].includes(meta?.action||''))scheduleDecorate();});}catch(_){}
    window.addEventListener?.('sbb:day-state-phase',ev=>{if(ev?.detail?.phase==='RIBBON_RENDER_REQUEST'||ev?.detail?.phase==='APPLY_TOTAL')scheduleDecorate();});
    window.addEventListener?.('sbb:competition-registry-updated',()=>{try{applySelected(window.SBB_SELECTED_EVENT?.get?.());}catch(_){}scheduleDecorate();});
    scheduleDecorate();
  }

  window.SBB_TENNIS_PRESENTATION=Object.freeze({version:'5.1.19',isTennis,surname,compactName,roundFields,roundShort:value=>roundFields(value).displayRound,decorateCards,scheduleDecorate,apply:applySelected});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();

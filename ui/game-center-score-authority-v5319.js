/* Sports Big Board v5.4.9 — Game Center score authority, observer-free.
   v5.4.9 repaired stale provider 0-0 soccer summaries by watching Game Center DOM.
   The persistent Game Center renderer also watches that DOM, so the two observers
   could repeatedly rewrite the same score and monopolize the main thread at boot.

   v5.4.9 moves score authority to the DATA boundary instead. SBB_GAME_CENTER get()
   and peek() return a shallow corrected payload using SelectedEvent / score-ribbon
   final-score truth. Every Game Center renderer therefore receives one consistent
   score and no DOM observer is needed. Bounded one-shot DOM reassertions remain only
   to repair a view that was already on screen when this layer installed. */
(() => {
  'use strict';
  if (window.SBB_GAME_CENTER_SCORE_AUTHORITY?.installed) return;
  const VERSION='5.4.9';
  const $=id=>document.getElementById(id);
  const clean=v=>String(v??'').trim();
  const num=v=>{
    if(v===null||v===undefined||clean(v)==='') return null;
    const n=Number(v);return Number.isFinite(n)?n:null;
  };
  const finalStatus=v=>/final|finished|complete|completed|game over|full time|ft/i.test(clean(v));
  const compOf=evt=>clean(evt?.competitionId||evt?.__sbbLeague||evt?.league).toUpperCase();
  const isSoccer=evt=>['EPL','MLS'].includes(compOf(evt))||/soccer|football/i.test(clean(evt?.sportId||evt?.sport));

  function participants(evt){
    const parts=Array.isArray(evt?.participants)?evt.participants:[];
    return {
      away:evt?.awayTeam||evt?.away||parts.find(x=>x?.side==='away')||parts[0]||{},
      home:evt?.homeTeam||evt?.home||parts.find(x=>x?.side==='home')||parts[1]||{}
    };
  }
  function score(evt,side){
    const cap=side[0].toUpperCase()+side.slice(1);
    const team=participants(evt)[side]||{};
    const candidates=[
      evt?.[`${side}Score`],evt?.[`score${cap}`],evt?.score?.[`${side}Score`],
      evt?.score?.[side],team?.score,team?.points,team?.runs,
      evt?.scoreboard?.[side]?.score,evt?.scoreboard?.totals?.[side]?.runs
    ];
    for(const value of candidates){const n=num(value);if(n!==null)return n;}
    return null;
  }
  function teamName(team){return clean(team?.name||team?.displayName||team?.shortName||team?.abbreviation);}
  function eventStatus(evt){return clean(evt?.status||evt?.state||evt?.statusText||evt?.gameStatus);}
  function shouldOwn(evt){
    if(!evt)return false;
    const a=score(evt,'away'),h=score(evt,'home'),status=eventStatus(evt);
    return a!==null&&h!==null&&(finalStatus(status)||isSoccer(evt)||a!==0||h!==0);
  }
  function key(evt){
    if(!evt)return '';
    try{return clean(window.SBB_GAME_CENTER?.identity?.(evt)?.key);}catch(_){ }
    return `${compOf(evt)}:${clean(evt?.date||evt?.scheduledAt).slice(0,10)}:${teamName(participants(evt).away)}:${teamName(participants(evt).home)}`;
  }

  function correctedPayload(gc,evt){
    if(!gc||!evt||!shouldOwn(evt))return gc;
    const awayScore=score(evt,'away'),homeScore=score(evt,'home');
    const originalBoard=gc.scoreboard||{};
    const board={...originalBoard};
    board.away={...(originalBoard.away||{}),score:awayScore};
    board.home={...(originalBoard.home||{}),score:homeScore};
    if(compOf(evt)==='MLB'||/baseball/i.test(clean(evt?.sportId||evt?.sport))){
      board.totals={...(originalBoard.totals||{}),away:{...(originalBoard.totals?.away||{}),runs:awayScore},home:{...(originalBoard.totals?.home||{}),runs:homeScore}};
    }
    const originalEvent=gc.event||{};
    const event={...originalEvent};
    if(finalStatus(eventStatus(evt))){event.status='Final';board.status='Final';}
    return {...gc,scoreboard:board,event,__sbbScoreAuthority:true,__sbbScoreAuthorityVersion:VERSION};
  }

  let baseGameCenter=null,selected=null,lastRepairKey='',repairGeneration=0,repairTimers=[];
  function installDataBoundary(){
    const base=window.SBB_GAME_CENTER;
    if(!base||base.__sbbScoreAuthorityV5320)return false;
    baseGameCenter=base;
    const get=async(evt,options={})=>correctedPayload(await base.get(evt,options),evt);
    const peek=evt=>correctedPayload(base.peek(evt),evt);
    window.SBB_GAME_CENTER=Object.freeze({...base,get,peek,__sbbScoreAuthorityV5320:true,scoreAuthorityVersion:VERSION});
    return true;
  }
  function clearRepairTimers(){for(const timer of repairTimers)clearTimeout(timer);repairTimers=[];}
  function setText(el,value){if(el&&clean(el.textContent)!==clean(value))el.textContent=String(value);}
  function repairVisibleHeader(evt=selected){
    if(!evt||!shouldOwn(evt)||document.body.classList.contains('sbb-special-event-match-center'))return false;
    const awayScore=score(evt,'away'),homeScore=score(evt,'home');
    const away=participants(evt).away,home=participants(evt).home;
    const awayEl=$('gcAwayTeam'),homeEl=$('gcHomeTeam');
    setText(awayEl?.querySelector('.gc-team-score'),awayScore);
    setText(homeEl?.querySelector('.gc-team-score'),homeScore);
    const overview=document.querySelector('#gcOverview .gc-basic-overview strong');
    if(overview){
      const awayLabel=clean(awayEl?.querySelector('.gc-team-abbr')?.textContent)||teamName(away)||'AWAY';
      const homeLabel=clean(homeEl?.querySelector('.gc-team-abbr')?.textContent)||teamName(home)||'HOME';
      setText(overview,`${awayLabel} ${awayScore} – ${homeScore} ${homeLabel}`);
    }
    if(isSoccer(evt)){
      const rows=document.querySelectorAll('#gcPersistentSummary .sbb-multisport-linescore tbody tr');
      if(rows.length>=2){setText(rows[0]?.lastElementChild,awayScore);setText(rows[1]?.lastElementChild,homeScore);}
    }
    if(finalStatus(eventStatus(evt))){const gcStatus=$('gcStatus');if(gcStatus&&!finalStatus(gcStatus.textContent))setText(gcStatus,'Final');}
    lastRepairKey=`${key(evt)}:${awayScore}-${homeScore}`;
    return true;
  }
  function scheduleBoundedRepair(evt=selected){
    if(evt)selected=evt;
    clearRepairTimers();
    const generation=++repairGeneration;
    const run=()=>{if(generation===repairGeneration)repairVisibleHeader(selected);};
    run();
    for(const delay of [80,260,800,1800,3600])repairTimers.push(setTimeout(run,delay));
  }
  function bind(){
    installDataBoundary();
    try{
      selected=window.SBB_SELECTED_EVENT?.get?.()||null;
      window.SBB_SELECTED_EVENT?.subscribe?.(evt=>{
        selected=evt||null;
        if(evt){installDataBoundary();scheduleBoundedRepair(evt);}else clearRepairTimers();
      });
    }catch(_){ }
    if(selected)scheduleBoundedRepair(selected);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();

  window.SBB_GAME_CENTER_SCORE_AUTHORITY=Object.freeze({
    installed:true,version:VERSION,repair:repairVisibleHeader,correct:correctedPayload,
    snapshot:()=>({selectedKey:key(selected),lastRepairKey,dataBoundary:!!window.SBB_GAME_CENTER?.__sbbScoreAuthorityV5320,observer:false})
  });
})();

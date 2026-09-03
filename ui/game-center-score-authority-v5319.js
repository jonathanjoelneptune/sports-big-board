/* Sports Big Board v5.3.19 — Game Center score authority.
   The score ribbon / SelectedEvent owns final score identity. Some soccer Game
   Center provider payloads contain useful statistics and period splits while the
   summary score is still 0-0. Preserve the richer provider details, but never let
   that stale summary overwrite the known event result shown in the header. */
(() => {
  'use strict';
  if (window.SBB_GAME_CENTER_SCORE_AUTHORITY?.installed) return;
  const VERSION='5.3.19';
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

  let selected=null,repairQueued=false,observer=null,lastRepairKey='';
  function key(evt){
    if(!evt)return '';
    try{return clean(window.SBB_GAME_CENTER?.identity?.(evt)?.key);}catch(_){ }
    return `${compOf(evt)}:${clean(evt?.date||evt?.scheduledAt).slice(0,10)}:${teamName(participants(evt).away)}:${teamName(participants(evt).home)}`;
  }

  function setText(el,value){if(el&&clean(el.textContent)!==clean(value))el.textContent=String(value);}
  function repairHeader(evt=selected){
    if(!evt||document.body.classList.contains('sbb-special-event-match-center'))return false;
    const awayScore=score(evt,'away'),homeScore=score(evt,'home');
    const status=eventStatus(evt);
    const away=participants(evt).away,home=participants(evt).home;
    const hasKnownScore=awayScore!==null&&homeScore!==null;
    const shouldOwnScore=hasKnownScore && (finalStatus(status)||isSoccer(evt)||awayScore!==0||homeScore!==0);
    if(!shouldOwnScore)return false;

    const awayEl=$('gcAwayTeam'),homeEl=$('gcHomeTeam');
    setText(awayEl?.querySelector('.gc-team-score'),awayScore);
    setText(homeEl?.querySelector('.gc-team-score'),homeScore);

    // Keep the lightweight overview synchronized with the actual event result.
    const overview=document.querySelector('#gcOverview .gc-basic-overview strong');
    if(overview){
      const awayLabel=clean(awayEl?.querySelector('.gc-team-abbr')?.textContent)||teamName(away)||'AWAY';
      const homeLabel=clean(homeEl?.querySelector('.gc-team-abbr')?.textContent)||teamName(home)||'HOME';
      setText(overview,`${awayLabel} ${awayScore} – ${homeScore} ${homeLabel}`);
    }

    // Soccer provider period splits are often correct even when their aggregate
    // score is stale. Keep H1/H2, but repair the T column from SelectedEvent.
    if(isSoccer(evt)){
      const rows=document.querySelectorAll('#gcPersistentSummary .sbb-multisport-linescore tbody tr');
      if(rows.length>=2){
        const a=rows[0]?.lastElementChild,h=rows[1]?.lastElementChild;
        setText(a,awayScore);setText(h,homeScore);
      }
    }

    if(finalStatus(status)){
      const gcStatus=$('gcStatus');
      if(gcStatus&&!finalStatus(gcStatus.textContent))setText(gcStatus,'Final');
    }
    lastRepairKey=`${key(evt)}:${awayScore}-${homeScore}`;
    return true;
  }

  function queueRepair(evt=selected){
    if(evt)selected=evt;
    if(repairQueued)return;
    repairQueued=true;
    queueMicrotask(()=>{
      repairQueued=false;
      repairHeader(selected);
      // Provider rendering is asynchronous; these bounded reassertions cover the
      // shell, persistent summary and final render without an always-on interval.
      [60,220,700,1600].forEach(ms=>setTimeout(()=>repairHeader(selected),ms));
    });
  }

  function bind(){
    try{
      selected=window.SBB_SELECTED_EVENT?.get?.()||null;
      window.SBB_SELECTED_EVENT?.subscribe?.(evt=>{selected=evt||null;if(evt)queueRepair(evt);});
    }catch(_){ }
    const host=$('gameCenterContent');
    if(host&&typeof MutationObserver!=='undefined'){
      observer=new MutationObserver(()=>{
        if(!selected||repairQueued)return;
        // Only schedule if a provider render actually disturbed a known score.
        const a=score(selected,'away'),h=score(selected,'home');
        if(a===null||h===null)return;
        const shownA=clean($('gcAwayTeam')?.querySelector('.gc-team-score')?.textContent);
        const shownH=clean($('gcHomeTeam')?.querySelector('.gc-team-score')?.textContent);
        if(shownA!==String(a)||shownH!==String(h))queueRepair(selected);
      });
      observer.observe(host,{subtree:true,childList:true,characterData:true});
    }
    if(selected)queueRepair(selected);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();

  window.SBB_GAME_CENTER_SCORE_AUTHORITY=Object.freeze({
    installed:true,version:VERSION,repair:repairHeader,
    snapshot:()=>({selectedKey:key(selected),lastRepairKey,observing:!!observer})
  });
})();

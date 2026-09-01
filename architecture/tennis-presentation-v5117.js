/* Sports Big Board v5.1.17 — small tennis-specific UI vocabulary layer.
   Data continues to come from the shared Game Center contract; this only changes
   football/baseball-centric labels when the selected event is tennis. */
(() => {
  'use strict';
  if(window.SBB_TENNIS_PRESENTATION?.version==='5.1.17')return;
  const clean=v=>String(v??'').trim();
  const isTennis=evt=>clean(evt?.sportId||evt?.event?.sportId).toLowerCase()==='tennis';
  function apply(evt){
    const tennis=isTennis(evt);
    const labels={overview:'OVERVIEW','team-stats':tennis?'MATCH STATS':'TEAM STATS',players:'PLAYERS',plays:tennis?'SETS':'PLAYS'};
    document.querySelectorAll('[data-gc-section]').forEach(btn=>{const k=btn.dataset.gcSection;if(labels[k])btn.textContent=labels[k];});
  }
  function boot(){
    try{window.SBB_SELECTED_EVENT?.subscribe?.(evt=>apply(evt));}catch(_){}
    try{apply(window.SBB_SELECTED_EVENT?.get?.());}catch(_){}
  }
  window.SBB_TENNIS_PRESENTATION=Object.freeze({version:'5.1.17',apply});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();

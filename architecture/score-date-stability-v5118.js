/* Sports Big Board v5.1.18 — ScoreDateStore non-regression + browser LKG cache.
   A transient empty read can never erase a previously non-empty date. Historical
   scores are small enough to persist locally, giving repeat date browsing an
   immediate first paint even while the cloud read model is warming. */
(() => {
  'use strict';
  const base=window.SBB_SCORE_DATE;
  if(!base||base.__sbbV5118)return;
  const KEY='sbb.scoreDateStore.v5118';
  const MAX_DAYS=21;
  const cleanDate=v=>String(v||'').slice(0,10);
  let saved={days:{}};
  try{const x=JSON.parse(localStorage.getItem(KEY)||'{}');if(x&&typeof x==='object'&&x.days)saved=x;}catch(_){}
  function persist(){
    try{
      const keys=Object.keys(saved.days||{}).sort().reverse();
      for(const k of keys.slice(MAX_DAYS))delete saved.days[k];
      localStorage.setItem(KEY,JSON.stringify(saved));
    }catch(_){}
  }
  function saveLeague(date,league,rows){
    date=cleanDate(date);league=String(league||'SPORTS').toUpperCase();if(!date||!Array.isArray(rows)||!rows.length)return;
    const day=saved.days[date]||(saved.days[date]={at:Date.now(),leagues:{}});
    day.at=Date.now();day.leagues[league]=rows.slice();persist();
  }
  function restore(date,{render=false}={}){
    date=cleanDate(date);const day=saved.days?.[date];if(!day?.leagues)return 0;
    let total=0;
    for(const [league,rows] of Object.entries(day.leagues)){
      if(!Array.isArray(rows)||!rows.length)continue;
      const current=base.matches(date,league);
      if(!current.length){base.setMatches(date,league,rows,{source:'browser-lkg-v5118',authoritative:true,restored:true});total+=rows.length;}
    }
    if(render&&total)try{window.renderScoresFromMatchesCombined?.(false);}catch(_){}
    return total;
  }
  const setMatches=(date,league,rows,meta={})=>{
    date=base.normalizeDate(date);league=String(league||'SPORTS').toUpperCase();
    const next=Array.isArray(rows)?rows:[],prior=base.matches(date,league);
    // Empty is not evidence that a formerly populated schedule disappeared. Only
    // an explicit operator/canonical correction may erase a non-empty league day.
    if(!next.length&&prior.length&&!meta.allowEmptyReplace&&!meta.confirmedEmpty){
      try{base.recordMatchFailure(date,league,'transient empty score projection',{source:meta.source||'v5118-empty-guard'});}catch(_){}
      return prior;
    }
    const result=base.setMatches(date,league,next,meta);
    if(result.length)saveLeague(date,league,result);
    return result;
  };
  const api=Object.freeze({...base,version:'1.2-v5118',setMatches,restoreLastGood:restore,__sbbV5118:true,
    cacheSnapshot:()=>({dates:Object.keys(saved.days||{}).length,keys:Object.keys(saved.days||{}).sort()})});
  window.SBB_SCORE_DATE=api;
  // Restore only the current browse date at boot; other dates stay lazy.
  const boot=()=>restore(api.snapshot().browseDate,{render:false});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();

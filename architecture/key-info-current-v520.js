/* Sports Big Board v5.2.0 — KEY INFO is current news, never browse-date history.

   The score ribbon may browse any historical date. KEY INFO is a separate current
   editorial lane. Reuse the established editorial source/renderer but evaluate it
   against TODAY regardless of the score date and keep it refreshing while history
   is on screen.
*/
(() => {
  'use strict';
  if(window.SBB_KEY_INFO_CURRENT?.version==='5.2.0')return;
  const VERSION='5.2.0';
  const REFRESH_MS=5*60*1000;
  const state={installed:false,renders:0,refreshes:0,fallbackToAll:0,lastRefreshAt:0,lastCount:0,lastError:''};
  let originalSelect=null,originalRenderActive=null,originalRender=null,originalRefresh=null;
  let refreshTimer=0;
  const clean=v=>String(v??'').trim();
  const today=()=>typeof localDateISO==='function'?localDateISO(0):new Date().toISOString().slice(0,10);

  function withBrowseDate(value,fn){
    let priorWindow=window.scoreBrowseDate,priorBinding=null,binding=false;
    try{priorBinding=scoreBrowseDate;scoreBrowseDate=value;binding=true;}catch(_){}
    try{window.scoreBrowseDate=value;}catch(_){}
    try{return fn();}
    finally{
      try{window.scoreBrowseDate=priorWindow;}catch(_){}
      if(binding)try{scoreBrowseDate=priorBinding;}catch(_){}
    }
  }
  function withFilter(value,fn){
    let priorWindow=window.scoreRibbonLeagueFilter,priorBinding=null,binding=false;
    try{priorBinding=scoreRibbonLeagueFilter;scoreRibbonLeagueFilter=value;binding=true;}catch(_){}
    try{window.scoreRibbonLeagueFilter=value;}catch(_){}
    try{return fn();}
    finally{
      try{window.scoreRibbonLeagueFilter=priorWindow;}catch(_){}
      if(binding)try{scoreRibbonLeagueFilter=priorBinding;}catch(_){}
    }
  }

  function selectCurrent(){
    if(typeof originalSelect!=='function')return [];
    const d=today();
    let rows=[];
    try{rows=withBrowseDate(d,()=>originalSelect())||[];}catch(_){rows=[];}
    // A custom/special-event filter may not have an editorial source. KEY INFO is
    // still supposed to show current sports news instead of an empty historical lane.
    if(!rows.length){
      let filter='ALL';try{filter=String(scoreRibbonLeagueFilter||'ALL').toUpperCase();}catch(_){}
      if(filter!=='ALL'){
        try{rows=withFilter('ALL',()=>withBrowseDate(d,()=>originalSelect()))||[];state.fallbackToAll++;}catch(_){}
      }
    }
    return Array.isArray(rows)?rows:[];
  }

  function decorateState(count){
    const label=document.getElementById('keyInfoState');
    if(label)label.textContent=count?`CURRENT NEWS • ${count} update${count===1?'':'s'}`:'CURRENT NEWS • checking…';
    const track=document.getElementById('keyInfoTrack');
    if(track&&!count){
      const empty=track.querySelector('.key-info-empty');
      if(empty)empty.textContent='Loading current verified sports updates…';
    }
  }

  function renderCurrent(){
    const rows=selectCurrent();
    state.renders++;state.lastCount=rows.length;
    if(typeof originalRender==='function'){
      try{withBrowseDate(today(),()=>originalRender(rows));}catch(err){state.lastError=String(err?.message||err);}
    }else if(typeof originalRenderActive==='function'){
      try{withBrowseDate(today(),()=>originalRenderActive());}catch(err){state.lastError=String(err?.message||err);}
    }
    decorateState(rows.length);
    return rows;
  }

  async function refreshCurrent(force=false){
    if(typeof originalRefresh!=='function')return [];
    state.refreshes++;state.lastRefreshAt=Date.now();
    try{
      // first=true intentionally bypasses the legacy historicalForegroundActive()
      // guard. Current news is independent of the score date being browsed.
      await originalRefresh(true,!!force);
      state.lastError='';
    }catch(err){state.lastError=String(err?.message||err);}
    return renderCurrent();
  }

  function install(){
    try{originalSelect=window.keyInfoEventsForActiveSport||keyInfoEventsForActiveSport;}catch(_){originalSelect=window.keyInfoEventsForActiveSport;}
    try{originalRenderActive=window.renderActiveSportKeyInformation||renderActiveSportKeyInformation;}catch(_){originalRenderActive=window.renderActiveSportKeyInformation;}
    try{originalRender=window.renderKeyInformation||renderKeyInformation;}catch(_){originalRender=window.renderKeyInformation;}
    try{originalRefresh=window.refreshKeyInformation||refreshKeyInformation;}catch(_){originalRefresh=window.refreshKeyInformation;}
    if(typeof originalSelect!=='function'||typeof originalRefresh!=='function')return false;

    const selector=()=>selectCurrent();
    const renderer=()=>renderCurrent();
    const refresher=(first=false,force=false)=>refreshCurrent(!!force);
    selector.__sbbCurrentNewsV520=true;renderer.__sbbCurrentNewsV520=true;refresher.__sbbCurrentNewsV520=true;
    try{window.keyInfoEventsForActiveSport=selector;}catch(_){}
    try{keyInfoEventsForActiveSport=selector;}catch(_){}
    try{window.renderActiveSportKeyInformation=renderer;}catch(_){}
    try{renderActiveSportKeyInformation=renderer;}catch(_){}
    try{window.refreshKeyInformation=refresher;}catch(_){}
    try{refreshKeyInformation=refresher;}catch(_){}

    clearInterval(refreshTimer);
    refreshTimer=setInterval(()=>{if(!document.hidden)void refreshCurrent(false);},REFRESH_MS);
    window.addEventListener('focus',()=>{if(Date.now()-state.lastRefreshAt>60_000)void refreshCurrent(false);},{passive:true});
    document.addEventListener('visibilitychange',()=>{if(!document.hidden&&Date.now()-state.lastRefreshAt>60_000)void refreshCurrent(false);});
    // Repaint from the already-resident current event list after league/date UI
    // changes. No network or provider work occurs here.
    window.SBB_SCORE_DATE?.subscribe?.(()=>queueMicrotask(renderCurrent));
    state.installed=true;
    decorateState(0);
    void refreshCurrent(false);
    return true;
  }

  function boot(){
    if(install())return;
    const timer=setInterval(()=>{if(install())clearInterval(timer);},100);
    setTimeout(()=>clearInterval(timer),5000);
  }

  window.SBB_KEY_INFO_CURRENT=Object.freeze({version:VERSION,refresh:refreshCurrent,render:renderCurrent,snapshot:()=>({...state})});
  boot();
})();

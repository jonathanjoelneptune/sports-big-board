/* Sports Big Board v5.2.2 — persistent current-news Key Info lane.

   KEY INFO is independent of the score browse date. First paint comes from the
   last good browser snapshot; the network request is a cache-only backend lookup at
   /api/current-news. Score/date changes do not subscribe or rerender this lane.
*/
(() => {
  'use strict';
  if(window.SBB_KEY_INFO_CURRENT?.version==='5.2.2')return;
  const VERSION='5.2.2';
  const REFRESH_MS=5*60*1000;
  const CACHE_KEY='sbb.current-news.v522';
  const CACHE_MAX_AGE=12*60*60*1000;
  const state={installed:false,renders:0,refreshes:0,cachePaints:0,lastRefreshAt:0,lastCount:0,lastError:'',source:''};
  let originalRender=null,originalRefresh=null,refreshTimer=0,inflight=null;
  const clean=v=>String(v??'').trim();
  const today=()=>typeof localDateISO==='function'?localDateISO(0):new Date().toISOString().slice(0,10);
  const api=path=>window.SBB_API?.url?window.SBB_API.url(path):path;

  function cachedRows(){
    try{
      const payload=JSON.parse(localStorage.getItem(CACHE_KEY)||'null');
      if(!payload||!Array.isArray(payload.data)||Date.now()-Number(payload.savedAt||0)>CACHE_MAX_AGE)return [];
      return payload.data.filter(x=>x&&typeof x==='object').slice(0,20);
    }catch(_){return [];}
  }
  function saveRows(rows,source=''){
    if(!Array.isArray(rows)||!rows.length)return;
    try{localStorage.setItem(CACHE_KEY,JSON.stringify({savedAt:Date.now(),source,data:rows.slice(0,20)}));}catch(_){}
  }
  function withToday(fn){
    let priorWindow=window.scoreBrowseDate,priorBinding=null,bound=false;
    try{priorBinding=scoreBrowseDate;scoreBrowseDate=today();bound=true;}catch(_){}
    try{window.scoreBrowseDate=today();}catch(_){}
    try{return fn();}
    finally{
      try{window.scoreBrowseDate=priorWindow;}catch(_){}
      if(bound)try{scoreBrowseDate=priorBinding;}catch(_){}
    }
  }
  function setState(count,source=''){
    const label=document.getElementById('keyInfoState');
    if(label)label.textContent=count?`CURRENT NEWS • ${count} update${count===1?'':'s'}`:'CURRENT NEWS • waiting for first update';
    state.lastCount=count;state.source=source||state.source;
  }
  function render(rows,source=''){
    rows=Array.isArray(rows)?rows.filter(Boolean).slice(0,20):[];
    state.renders++;
    if(rows.length&&typeof originalRender==='function'){
      try{withToday(()=>originalRender(rows));}catch(err){state.lastError=String(err?.message||err);}
      setState(rows.length,source);
      return rows;
    }
    const track=document.getElementById('keyInfoTrack');
    if(track&&!track.querySelector('.key-info-item')){
      track.innerHTML='<div class="key-info-empty">Current sports updates are warming in the background.</div>';
    }
    setState(0,source);
    return [];
  }
  function residentAppRows(){
    try{return Array.isArray(ALL_KEY_INFO_EVENTS)?ALL_KEY_INFO_EVENTS.filter(Boolean).slice(0,20):[];}catch(_){return [];}
  }
  async function fetchJson(path,timeoutMs=1500){
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),timeoutMs);
    try{
      const r=await fetch(api(path),{cache:'no-store',signal:controller.signal});
      if(!r.ok)throw new Error(`HTTP ${r.status}`);
      return await r.json();
    }finally{clearTimeout(timer);}
  }
  async function refresh(force=false){
    if(inflight)return inflight;
    if(!force&&Date.now()-state.lastRefreshAt<20_000)return residentAppRows();
    state.refreshes++;state.lastRefreshAt=Date.now();
    inflight=(async()=>{
      try{
        const payload=await fetchJson('/api/current-news',1600);
        let rows=Array.isArray(payload?.data)?payload.data.filter(Boolean):[];
        if(rows.length){
          state.lastError='';saveRows(rows,payload?.source||'BACKEND');return render(rows,payload?.source||'BACKEND');
        }
        rows=residentAppRows();
        if(rows.length){saveRows(rows,'APP_EDITORIAL_CACHE');return render(rows,'APP_EDITORIAL_CACHE');}
        // Ask the established editorial endpoint to refresh only after all cache-first
        // lanes are empty. Do not await it for first paint.
        if(typeof originalRefresh==='function'){
          Promise.resolve(originalRefresh(true,!!force)).then(()=>{
            const late=residentAppRows();if(late.length){saveRows(late,'EDITORIAL_DESK');render(late,'EDITORIAL_DESK');}
          }).catch(()=>{});
        }
        return render(cachedRows(),'BROWSER_CACHE');
      }catch(err){
        state.lastError=String(err?.message||err);
        const rows=residentAppRows();
        return render(rows.length?rows:cachedRows(),rows.length?'APP_EDITORIAL_CACHE':'BROWSER_CACHE');
      }finally{inflight=null;}
    })();
    return inflight;
  }

  function install(){
    try{originalRender=window.renderKeyInformation||renderKeyInformation;}catch(_){originalRender=window.renderKeyInformation;}
    try{originalRefresh=window.refreshKeyInformation||refreshKeyInformation;}catch(_){originalRefresh=window.refreshKeyInformation;}
    if(typeof originalRender!=='function')return false;

    // Paint before any current request. This is the same non-authoritative UX cache
    // pattern used by news sites: stale headlines may appear briefly, then are
    // replaced by the current backend read model. It never affects score/event data.
    const local=cachedRows();if(local.length){state.cachePaints++;render(local,'BROWSER_CACHE');}else setState(0,'');

    const wrapped=(first=false,force=false)=>refresh(!!force);
    wrapped.__sbbCurrentNewsV522=true;wrapped.__sbbOriginal=originalRefresh;
    try{window.refreshKeyInformation=wrapped;}catch(_){}
    try{refreshKeyInformation=wrapped;}catch(_){}
    try{window.renderActiveSportKeyInformation=()=>{const rows=residentAppRows();return render(rows.length?rows:cachedRows(),rows.length?'APP_EDITORIAL_CACHE':'BROWSER_CACHE');};}catch(_){}

    clearInterval(refreshTimer);
    refreshTimer=setInterval(()=>{if(!document.hidden)void refresh(false);},REFRESH_MS);
    window.addEventListener('focus',()=>{if(Date.now()-state.lastRefreshAt>60_000)void refresh(false);},{passive:true});
    document.addEventListener('visibilitychange',()=>{if(!document.hidden&&Date.now()-state.lastRefreshAt>60_000)void refresh(false);});
    state.installed=true;
    void refresh(false);
    return true;
  }
  function boot(){if(install())return;const t=setInterval(()=>{if(install())clearInterval(t);},100);setTimeout(()=>clearInterval(t),5000);}
  window.SBB_KEY_INFO_CURRENT=Object.freeze({version:VERSION,refresh,render:rows=>render(rows,'API'),snapshot:()=>({...state})});
  boot();
})();

/* Sports Big Board v5.2.4 — Sports Ticker cached intelligence lane.

   SPORTS TICKER is global/current and intentionally independent of scoreBrowseDate.
   The browser only reads a finished server snapshot. OpenAI/news discovery never
   runs on this request path and date navigation never refreshes this lane.
*/
(() => {
  'use strict';
  if(window.SBB_KEY_INFO_CURRENT?.version==='5.2.4')return;
  const VERSION='5.2.4';
  const REFRESH_MS=20*60*1000; // three prepared editions per hour
  const CACHE_KEY='sbb.sports-ticker.v524';
  const CACHE_MAX_AGE=24*60*60*1000;
  const MAX_ROWS=150;
  const state={installed:false,renders:0,refreshes:0,cachePaints:0,lastRefreshAt:0,lastCount:0,lastError:'',source:'',dateIsolation:true};
  let originalRender=null,refreshTimer=0,inflight=null;
  const api=path=>window.SBB_API?.url?window.SBB_API.url(path):path;

  function installUi(){
    if(!document.getElementById('sbbSportsTickerV524Style')){
      const style=document.createElement('style');
      style.id='sbbSportsTickerV524Style';
      style.textContent=`
        #scoreFilters>button[data-score-filter="NCAAF"]{align-self:center!important;display:inline-flex!important;align-items:center!important;justify-content:center!important;vertical-align:middle!important}
        .key-info-ribbon .key-info-title,.key-info-ribbon [data-key-info-title]{display:flex;align-items:center}
      `;
      document.head.appendChild(style);
    }
    const root=document.querySelector('.key-info-ribbon')||document.getElementById('keyInfoRibbon')||document.body;
    if(root){
      const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
      const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
      for(const node of nodes){
        const text=String(node.nodeValue||'').trim();
        if(/^KEY INFO$/i.test(text))node.nodeValue=node.nodeValue.replace(/KEY INFO/i,'SPORTS TICKER');
        else if(/^CURRENT NEWS$/i.test(text))node.nodeValue='';
      }
    }
    document.title=document.title.replace(/v\d+\.\d+\.\d+/i,'v5.2.4');
  }
  function cachedRows(){
    try{
      const payload=JSON.parse(localStorage.getItem(CACHE_KEY)||'null');
      if(!payload||!Array.isArray(payload.data)||Date.now()-Number(payload.savedAt||0)>CACHE_MAX_AGE)return [];
      return payload.data.filter(x=>x&&typeof x==='object').slice(0,MAX_ROWS);
    }catch(_){return [];}
  }
  function saveRows(rows,source=''){
    if(!Array.isArray(rows)||!rows.length)return;
    try{localStorage.setItem(CACHE_KEY,JSON.stringify({savedAt:Date.now(),source,data:rows.slice(0,MAX_ROWS)}));}catch(_){}
  }
  function setState(count,source=''){
    installUi();
    const label=document.getElementById('keyInfoState');
    if(label)label.textContent=count?`${count} update${count===1?'':'s'}`:'warming cached ticker';
    state.lastCount=count;state.source=source||state.source;
  }
  function render(rows,source=''){
    rows=Array.isArray(rows)?rows.filter(Boolean).slice(0,MAX_ROWS):[];
    state.renders++;
    if(rows.length&&typeof originalRender==='function'){
      try{originalRender(rows);}catch(err){state.lastError=String(err?.message||err);}
      setState(rows.length,source);return rows;
    }
    const track=document.getElementById('keyInfoTrack');
    if(track&&!track.querySelector('.key-info-item'))track.innerHTML='<div class="key-info-empty">Sports Ticker is warming in the background.</div>';
    setState(0,source);return [];
  }
  async function fetchJson(path,timeoutMs=1800){
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),timeoutMs);
    try{const r=await fetch(api(path),{cache:'no-store',signal:controller.signal});if(!r.ok)throw new Error(`HTTP ${r.status}`);return await r.json();}
    finally{clearTimeout(timer);}
  }
  async function refresh(force=false){
    if(inflight)return inflight;
    if(!force&&Date.now()-state.lastRefreshAt<60_000)return cachedRows();
    state.refreshes++;state.lastRefreshAt=Date.now();
    inflight=(async()=>{
      try{
        let payload;
        try{payload=await fetchJson('/api/sports-ticker',1800);}catch(_){payload=await fetchJson('/api/current-news',1800);}
        const rows=Array.isArray(payload?.data)?payload.data.filter(Boolean).slice(0,MAX_ROWS):[];
        if(rows.length){state.lastError='';saveRows(rows,payload?.source||'SPORTS_TICKER');return render(rows,payload?.source||'SPORTS_TICKER');}
        return render(cachedRows(),'BROWSER_CACHE');
      }catch(err){state.lastError=String(err?.message||err);return render(cachedRows(),'BROWSER_CACHE');}
      finally{inflight=null;}
    })();
    return inflight;
  }
  function install(){
    installUi();
    try{originalRender=window.renderKeyInformation||renderKeyInformation;}catch(_){originalRender=window.renderKeyInformation;}
    if(typeof originalRender!=='function')return false;
    const local=cachedRows();if(local.length){state.cachePaints++;render(local,'BROWSER_CACHE');}else setState(0,'');
    const wrapped=(first=false,force=false)=>refresh(!!force);
    wrapped.__sbbSportsTickerV524=true;
    try{window.refreshKeyInformation=wrapped;}catch(_){}
    try{refreshKeyInformation=wrapped;}catch(_){}
    try{window.renderActiveSportKeyInformation=()=>render(cachedRows(),'BROWSER_CACHE');}catch(_){}
    clearInterval(refreshTimer);refreshTimer=setInterval(()=>{if(!document.hidden)void refresh(false);},REFRESH_MS);
    // Reassert date-transition ownership after legacy v5.2.2 ribbon boot wrappers finish.
    // This removes the duplicate fetch+prefetch date wrapper that produced request storms.
    let guards=0;const ownership=setInterval(()=>{guards++;try{window.SBB_DATE_TRANSITIONS?.install?.();}catch(_){}if(guards>=32)clearInterval(ownership);},250);
    state.installed=true;void refresh(false);return true;
  }
  function boot(){if(install())return;const t=setInterval(()=>{if(install())clearInterval(t);},100);setTimeout(()=>clearInterval(t),6000);}
  window.SBB_KEY_INFO_CURRENT=Object.freeze({version:VERSION,name:'SPORTS_TICKER',refresh,render:rows=>render(rows,'API'),snapshot:()=>({...state})});
  boot();
})();

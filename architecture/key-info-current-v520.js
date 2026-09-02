/* Sports Big Board v5.2.5 — continuous Sports Ticker ownership.

   SPORTS TICKER is a global/current intelligence lane. Score-date navigation,
   sport filters, score rendering and historical convergence are forbidden from
   refreshing or rebuilding it. Only this module's 20-minute snapshot reader may
   update the ticker. New stories are prepended while the current marquee position
   is preserved, so an edition refresh does not visibly jump back to the beginning.
*/
(() => {
  'use strict';
  if(window.SBB_KEY_INFO_CURRENT?.version==='5.2.5')return;

  const VERSION='5.2.5';
  const REFRESH_MS=20*60*1000;
  const CACHE_KEY='sbb.sports-ticker.v1';
  const LEGACY_CACHE_KEYS=['sbb.sports-ticker.v524','sbb.current-news.v522'];
  const CACHE_MAX_AGE=24*60*60*1000;
  const MAX_ROWS=150;
  const state={
    installed:false,renders:0,refreshes:0,cachePaints:0,lastRefreshAt:0,lastCount:0,lastError:'',source:'',
    dateIsolation:true,dateTriggeredNoops:0,legacyRefreshNoops:0,newItemsPrepended:0,continuityRenders:0,
    noChangeRefreshes:0,lastPreservedX:0,lastPrefixWidth:0,maxRows:MAX_ROWS,refreshMs:REFRESH_MS
  };

  let originalRender=null;
  let refreshTimer=0;
  let inflight=null;
  let currentRows=[];
  let currentSource='';

  const api=path=>window.SBB_API?.url?window.SBB_API.url(path):path;
  const clean=v=>String(v??'').trim();
  const norm=v=>clean(v).toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
  const rowTitle=row=>clean(row?.shortHeadline||row?.headline||row?.title||'Sports update');
  // Derive the browser key from story identity instead of trusting a versioned
  // backend tickerKey. That lets the first v5.2.5 edition dedupe cleanly against
  // the migrated v5.2.4 browser cache, whose rows did not yet carry tickerKey.
  const rowKey=row=>[
    clean(row?.id||row?.eventId||row?.gameId||row?.sourceUrl||row?.externalUrl),
    norm(rowTitle(row)),
    clean(row?.category||row?.eventType||'').toUpperCase()
  ].join('|');

  function dedupe(rows){
    const out=[],seen=new Set();
    for(const row of Array.isArray(rows)?rows:[]){
      if(!row||typeof row!=='object')continue;
      const key=rowKey(row);if(!key||seen.has(key))continue;
      seen.add(key);out.push(row);
      if(out.length>=MAX_ROWS)break;
    }
    return out;
  }

  function installUi(){
    if(!document.getElementById('sbbSportsTickerV525Style')){
      const style=document.createElement('style');
      style.id='sbbSportsTickerV525Style';
      style.textContent=`
        #scoreFilters>button[data-score-filter="NCAAF"]{align-self:center!important;display:inline-flex!important;align-items:center!important;justify-content:center!important;vertical-align:middle!important}
        .key-info-ribbon .key-info-label{align-items:center!important}
      `;
      document.head.appendChild(style);
    }
    const label=document.querySelector('.key-info-label strong');
    if(label)label.textContent='SPORTS TICKER';
  }

  function readCacheKey(key){
    try{
      const payload=JSON.parse(localStorage.getItem(key)||'null');
      if(!payload||!Array.isArray(payload.data)||Date.now()-Number(payload.savedAt||0)>CACHE_MAX_AGE)return null;
      return {savedAt:Number(payload.savedAt||0),source:clean(payload.source),data:dedupe(payload.data)};
    }catch(_){return null;}
  }
  function cachedSnapshot(){
    let payload=readCacheKey(CACHE_KEY);
    if(payload?.data?.length)return payload;
    for(const key of LEGACY_CACHE_KEYS){
      payload=readCacheKey(key);
      if(payload?.data?.length){
        try{localStorage.setItem(CACHE_KEY,JSON.stringify(payload));}catch(_){}
        return payload;
      }
    }
    return {savedAt:0,source:'',data:[]};
  }
  function saveRows(rows,source='',savedAt=Date.now()){
    rows=dedupe(rows);if(!rows.length)return;
    try{localStorage.setItem(CACHE_KEY,JSON.stringify({savedAt:Number(savedAt)||Date.now(),source,data:rows}));}catch(_){}
  }

  function setState(count,source=''){
    installUi();
    const label=document.getElementById('keyInfoState');
    if(label)label.textContent=count?`${count} update${count===1?'':'s'}`:'warming cached ticker';
    state.lastCount=count;state.source=source||state.source;
  }

  function captureMotion(track){
    const belt=track?.querySelector('.key-info-marquee');
    const group=belt?.querySelector('.key-info-group');
    if(!belt||!group)return {x:0,groupWidth:0,paused:false};
    let x=0;
    try{
      const t=getComputedStyle(belt).transform;
      if(t&&t!=='none'){
        if(window.DOMMatrixReadOnly)x=new DOMMatrixReadOnly(t).m41;
        else{const m=t.match(/matrix(?:3d)?\(([^)]+)\)/);if(m){const a=m[1].split(',').map(Number);x=a.length===16?a[12]:(a[4]||0);}}
      }
    }catch(_){}
    let groupWidth=0;try{groupWidth=group.getBoundingClientRect().width||0;}catch(_){}
    let paused=false;try{paused=getComputedStyle(belt).animationPlayState==='paused';}catch(_){}
    return {x,groupWidth,paused};
  }

  function withStagingTrack(fn){
    const liveTrack=document.getElementById('keyInfoTrack');
    const liveState=document.getElementById('keyInfoState');
    if(!liveTrack||typeof originalRender!=='function')return null;
    const shell=document.createElement('div');
    shell.style.cssText='position:fixed;left:-100000px;top:-100000px;visibility:hidden;pointer-events:none;width:1600px;height:80px;overflow:hidden';
    const stageState=document.createElement('span');
    const stageTrack=document.createElement('div');
    const oldTrackId=liveTrack.id,oldStateId=liveState?.id||'';
    liveTrack.id='keyInfoTrackSportsTickerLive';
    if(liveState)liveState.id='keyInfoStateSportsTickerLive';
    stageState.id='keyInfoState';stageTrack.id='keyInfoTrack';
    shell.append(stageState,stageTrack);document.body.appendChild(shell);
    try{return fn(stageTrack,stageState);}
    finally{
      shell.remove();liveTrack.id=oldTrackId;
      if(liveState)liveState.id=oldStateId||'keyInfoState';
    }
  }

  function buildBelt(rows){
    rows=dedupe(rows);
    const belt=document.createElement('div');belt.className='key-info-marquee';belt.dataset.sbbSportsTickerOwner=VERSION;
    const primary=document.createElement('div');primary.className='key-info-group';
    const duplicate=document.createElement('div');duplicate.className='key-info-group';duplicate.setAttribute('aria-hidden','true');
    belt.append(primary,duplicate);

    const built=withStagingTrack(stageTrack=>{
      for(let offset=0;offset<rows.length;offset+=20){
        const chunk=rows.slice(offset,offset+20);
        originalRender(chunk);
        const groups=stageTrack.querySelectorAll('.key-info-group');
        const a=groups[0],b=groups[1];
        if(!a||!b)continue;
        while(a.firstChild)primary.appendChild(a.firstChild);
        while(b.firstChild)duplicate.appendChild(b.firstChild);
      }
      return true;
    });

    if(!built||!primary.children.length){
      // Extremely defensive fallback. Normal production uses the established renderer
      // above so existing Key Info click behavior is retained for every ticker item.
      for(const row of rows){
        const make=(dup=false)=>{
          const btn=document.createElement('button');btn.type='button';btn.className=`key-info-item ${clean(row.eventType||row.category||'news').toLowerCase()}`;
          if(dup)btn.tabIndex=-1;
          btn.innerHTML=`<span class="key-info-type"></span><strong></strong><small></small>`;
          btn.querySelector('.key-info-type').textContent=clean(row.eventType||row.category||'UPDATE');
          btn.querySelector('strong').textContent=rowTitle(row);
          btn.querySelector('small').textContent=`${clean(row.league||'SPORT')} • ${clean(row.sourceLabel||row.source||'Sports Big Board')}`;
          const href=clean(row.externalUrl||row.sourceUrl);
          if(href)btn.onclick=()=>window.open(href,'_blank','noopener');
          return btn;
        };
        primary.appendChild(make(false));duplicate.appendChild(make(true));
      }
    }

    [...primary.children].forEach((node,i)=>{node.dataset.sbbTickerKey=rowKey(rows[i]);});
    [...duplicate.children].forEach((node,i)=>{node.dataset.sbbTickerKey=rowKey(rows[i]);node.tabIndex=-1;});
    const totalChars=rows.reduce((n,x)=>n+rowTitle(x).length+16,0);
    belt.style.setProperty('--ticker-duration',`${Math.max(42,Math.round(totalChars*0.115))}s`);
    return belt;
  }

  function mergeEdition(incoming){
    incoming=dedupe(incoming);
    if(!currentRows.length)return {rows:incoming,newRows:incoming};
    const oldKeys=new Set(currentRows.map(rowKey));
    const newRows=incoming.filter(row=>!oldKeys.has(rowKey(row)));
    // Existing stories deliberately retain their browser-session order. A backend
    // rerank is not allowed to make the conveyor jump. Only genuinely new/updated
    // story keys are inserted at the front.
    const merged=dedupe([...newRows,...currentRows]);
    return {rows:merged,newRows};
  }

  function renderOwned(rows,source='',{newRows=[]}={}){
    rows=dedupe(rows);
    const track=document.getElementById('keyInfoTrack');
    if(!track){setState(rows.length,source);return rows;}
    if(!rows.length){
      if(!track.querySelector('.key-info-marquee'))track.innerHTML='<div class="key-info-empty">Sports Ticker is warming in the background.</div>';
      setState(0,source);return [];
    }

    const previous=captureMotion(track);
    const belt=buildBelt(rows);
    belt.style.setProperty('animation-play-state','paused');
    track.replaceChildren(belt);

    // Preserve the exact old story position when new stories are prepended. The
    // same old item is shifted right by prefixWidth, so shift the new belt left by
    // the same amount via a negative animation delay. The next loop naturally
    // starts with the new updates at the beginning of the ticker.
    if(previous.groupWidth>0&&currentRows.length){
      const group=belt.querySelector('.key-info-group');
      const groupWidth=group?.getBoundingClientRect().width||0;
      let prefixWidth=0;
      for(let i=0;i<Math.min(newRows.length,group?.children?.length||0);i++)prefixWidth+=group.children[i].getBoundingClientRect().width||0;
      const duration=parseFloat(belt.style.getPropertyValue('--ticker-duration'))||42;
      if(groupWidth>0){
        const desiredX=previous.x-prefixWidth;
        let progress=(-desiredX)/groupWidth;
        progress=((progress%1)+1)%1;
        belt.style.animationDelay=`${-(progress*duration)}s`;
        state.lastPreservedX=Math.round(previous.x*10)/10;
        state.lastPrefixWidth=Math.round(prefixWidth*10)/10;
        state.continuityRenders++;
      }
    }
    requestAnimationFrame(()=>belt.style.removeProperty('animation-play-state'));
    currentRows=rows;currentSource=source||currentSource;state.renders++;
    state.newItemsPrepended+=newRows.length;
    setState(rows.length,source);return rows;
  }

  async function fetchJson(path,timeoutMs=1800){
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),timeoutMs);
    try{const r=await fetch(api(path),{cache:'no-store',signal:controller.signal});if(!r.ok)throw new Error(`HTTP ${r.status}`);return await r.json();}
    finally{clearTimeout(timer);}
  }

  async function refresh(force=false){
    if(inflight)return inflight;
    if(!force&&Date.now()-state.lastRefreshAt<60_000)return currentRows.slice();
    state.refreshes++;state.lastRefreshAt=Date.now();
    inflight=(async()=>{
      try{
        let payload;
        try{payload=await fetchJson('/api/sports-ticker',1800);}catch(_){payload=await fetchJson('/api/current-news',1800);}
        const incoming=dedupe(payload?.data||[]);
        if(!incoming.length)return currentRows.slice();
        const {rows,newRows}=mergeEdition(incoming);
        saveRows(rows,payload?.source||'SPORTS_TICKER',Number(payload?.savedAt||0)*1000||Date.now());
        state.lastError='';
        if(!currentRows.length||newRows.length)renderOwned(rows,payload?.source||'SPORTS_TICKER',{newRows});
        else{state.noChangeRefreshes++;currentRows=rows;currentSource=payload?.source||currentSource;setState(rows.length,currentSource);}
        return currentRows.slice();
      }catch(err){state.lastError=String(err?.message||err);return currentRows.slice();}
      finally{inflight=null;}
    })();
    return inflight;
  }

  function legacyNoop(kind){
    if(kind==='refresh')state.legacyRefreshNoops++;else state.dateTriggeredNoops++;
    return currentRows.slice();
  }

  function isolateLegacyLane(){
    const renderNoop=()=>legacyNoop('render');
    const refreshNoop=()=>Promise.resolve(legacyNoop('refresh'));
    renderNoop.__sbbSportsTickerDateNoop=true;refreshNoop.__sbbSportsTickerDateNoop=true;
    try{window.renderActiveSportKeyInformation=renderNoop;}catch(_){}
    try{renderActiveSportKeyInformation=renderNoop;}catch(_){}
    try{window.renderKeyInformation=renderNoop;}catch(_){}
    try{renderKeyInformation=renderNoop;}catch(_){}
    try{window.refreshKeyInformation=refreshNoop;}catch(_){}
    try{refreshKeyInformation=refreshNoop;}catch(_){}
    try{if(typeof keyInfoStartupRetryTimer!=='undefined'&&keyInfoStartupRetryTimer){clearTimeout(keyInfoStartupRetryTimer);keyInfoStartupRetryTimer=null;}}catch(_){}
  }

  function install(){
    installUi();
    try{originalRender=window.renderKeyInformation||renderKeyInformation;}catch(_){originalRender=window.renderKeyInformation;}
    if(typeof originalRender!=='function')return false;

    const local=cachedSnapshot();
    if(local.data.length){state.cachePaints++;currentRows=local.data;currentSource=local.source||'BROWSER_CACHE';renderOwned(currentRows,currentSource,{newRows:[]});}
    else setState(0,'');

    // Capture the established renderer first, then sever every legacy public entry
    // point. The old setScoreBrowseDate code may still *call* these names, but those
    // calls are now strict no-ops and therefore cannot fetch, rebuild, or rewind the
    // Sports Ticker.
    isolateLegacyLane();
    clearInterval(refreshTimer);
    refreshTimer=setInterval(()=>{if(!document.hidden)void refresh(false);},REFRESH_MS);
    window.addEventListener('focus',()=>{if(Date.now()-state.lastRefreshAt>REFRESH_MS)void refresh(false);},{passive:true});
    document.addEventListener('visibilitychange',()=>{if(!document.hidden&&Date.now()-state.lastRefreshAt>REFRESH_MS)void refresh(false);});

    // Reassert both ownership boundaries while late legacy installers finish.
    let guards=0;const ownership=setInterval(()=>{
      guards++;isolateLegacyLane();
      try{window.SBB_DATE_TRANSITIONS?.install?.();}catch(_){}
      if(guards>=32)clearInterval(ownership);
    },250);

    state.installed=true;void refresh(false);return true;
  }

  function boot(){if(install())return;const t=setInterval(()=>{if(install())clearInterval(t);},100);setTimeout(()=>clearInterval(t),6000);}
  window.SBB_KEY_INFO_CURRENT=Object.freeze({
    version:VERSION,name:'SPORTS_TICKER',refresh,
    render:rows=>{const merged=mergeEdition(rows);return renderOwned(merged.rows,'API',{newRows:merged.newRows});},
    rows:()=>currentRows.slice(),snapshot:()=>({...state,currentCount:currentRows.length,currentSource})
  });
  boot();
})();

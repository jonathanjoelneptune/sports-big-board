/* Sports Big Board v5.2.6 — smooth recycled Sports Ticker + operator refresh.

   SPORTS TICKER remains completely independent of score-date navigation. This
   generation replaces the very wide 150-story marquee with a small recycled DOM
   conveyor driven by Web Animations transform segments at a constant pixel speed.
   Only a bounded set of story nodes is composited at once, which substantially
   reduces paint/layer pressure while every story still rotates through the lane.
*/
(() => {
  'use strict';
  if(window.SBB_KEY_INFO_CURRENT?.version==='5.2.6')return;

  const VERSION='5.2.6';
  const REFRESH_MS=20*60*1000;
  const CACHE_KEY='sbb.sports-ticker.v1';
  const LEGACY_CACHE_KEYS=['sbb.sports-ticker.v524','sbb.current-news.v522'];
  const CACHE_MAX_AGE=24*60*60*1000;
  const MAX_ROWS=150;
  const WINDOW_NODES=28;
  const SPEED_PX_PER_SECOND=72;
  const state={
    installed:false,renders:0,refreshes:0,cachePaints:0,lastRefreshAt:0,lastCount:0,lastError:'',source:'',
    dateIsolation:true,dateTriggeredNoops:0,legacyRefreshNoops:0,newItemsPrepended:0,continuityRenders:0,
    noChangeRefreshes:0,recycledItems:0,animationSegments:0,manualRuns:0,manualErrors:0,
    speedPxPerSecond:SPEED_PX_PER_SECOND,windowNodes:WINDOW_NODES,maxRows:MAX_ROWS,refreshMs:REFRESH_MS
  };

  let refreshTimer=0;
  let inflight=null;
  let manualInflight=null;
  let currentRows=[];
  let currentSource='';
  let conveyorGroup=null;
  let conveyorAnimation=null;
  let nextRowIndex=0;
  let hoverPaused=false;
  let focusPaused=false;

  const api=path=>window.SBB_API?.url?window.SBB_API.url(path):path;
  const clean=v=>String(v??'').trim();
  const norm=v=>clean(v).toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
  const rowTitle=row=>clean(row?.shortHeadline||row?.headline||row?.title||'Sports update');
  const category=row=>clean(row?.category||row?.eventType||'UPDATE').toUpperCase().replace(/\s+/g,'_');
  const categoryClass=row=>category(row).toLowerCase().replace(/[^a-z0-9_-]+/g,'-');
  const rowKey=row=>[
    clean(row?.id||row?.eventId||row?.gameId||row?.tickerKey||row?.sourceUrl||row?.externalUrl),
    norm(rowTitle(row)),
    category(row)
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
    if(!document.getElementById('sbbSportsTickerV526Style')){
      const style=document.createElement('style');
      style.id='sbbSportsTickerV526Style';
      style.textContent=`
        #scoreFilters>button[data-score-filter="NCAAF"]{align-self:center!important;display:inline-flex!important;align-items:center!important;justify-content:center!important;vertical-align:middle!important}
        .key-info-ribbon .key-info-label{align-items:center!important}
        #keyInfoTrack{overflow:hidden!important;position:relative!important}
        .sbb-sports-ticker-conveyor{display:flex!important;align-items:stretch!important;gap:0!important;width:max-content!important;height:100%!important;transform:translate3d(0,0,0);will-change:transform;backface-visibility:hidden;-webkit-backface-visibility:hidden;contain:layout style;}
        .sbb-sports-ticker-conveyor>.key-info-item{flex:0 0 auto!important;box-shadow:none!important;filter:none!important;transition:none!important;transform:none!important;backface-visibility:hidden;-webkit-backface-visibility:hidden;}
        .sbb-sports-ticker-conveyor>.key-info-item:hover{box-shadow:none!important;transform:none!important}
        .sbb-sports-ticker-conveyor .key-info-type{border-width:1px!important;border-style:solid!important}
        .sbb-sports-ticker-conveyor .key-info-item.breaking .key-info-type{background:#45171b!important;border-color:#a63a42!important;color:#ff9aa2!important}
        .sbb-sports-ticker-conveyor .key-info-item.injury .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.suspension .key-info-type{background:#402016!important;border-color:#9d5738!important;color:#ffb38b!important}
        .sbb-sports-ticker-conveyor .key-info-item.transaction .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.coaching .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.recruiting .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.draft .key-info-type{background:#102a42!important;border-color:#326a96!important;color:#8ed0ff!important}
        .sbb-sports-ticker-conveyor .key-info-item.record .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.record_watch .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.milestone .key-info-type{background:#2b1a45!important;border-color:#7251a0!important;color:#cbb0ff!important}
        .sbb-sports-ticker-conveyor .key-info-item.result .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.upset .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.streak .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.return .key-info-type{background:#172f20!important;border-color:#467a55!important;color:#a9e6b5!important}
        .sbb-sports-ticker-conveyor .key-info-item.championship .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.clinch .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.elimination .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.playoff .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.award .key-info-type{background:#3a3014!important;border-color:#8d7934!important;color:#ffe38a!important}
        .sbb-sports-ticker-conveyor .key-info-item.ranking .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.tournament .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.schedule .key-info-type{background:#103536!important;border-color:#357a7b!important;color:#9ce9e8!important}
        .sbb-sports-ticker-conveyor .key-info-item.retirement .key-info-type{background:#2b2d31!important;border-color:#666d76!important;color:#d5d9df!important}
        .sports-ticker-dev-tools{display:none;margin-top:8px;padding-top:8px;border-top:1px solid var(--line,#25303a);gap:6px}
        html[data-sbb-dev="1"] .sports-ticker-dev-tools{display:grid}
        .sports-ticker-dev-tools .settings-save-btn{width:100%}
        .sports-ticker-dev-status{display:block;color:var(--muted,#8f9aa6);font-size:10px;line-height:1.35}
        .sports-ticker-dev-status.good{color:#7bf1a9}.sports-ticker-dev-status.bad{color:#ff9b92}
        @media (prefers-reduced-motion:reduce){.sbb-sports-ticker-conveyor{transform:none!important;will-change:auto!important}#keyInfoTrack{overflow-x:auto!important}}
      `;
      document.head.appendChild(style);
    }
    const label=document.querySelector('.key-info-label strong');
    if(label)label.textContent='SPORTS TICKER';
    bindDevButton();
    bindPauseControls();
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

  function makeItem(row,duplicate=false){
    const btn=document.createElement('button');
    btn.type='button';btn.className=`key-info-item ${categoryClass(row)}`;
    btn.dataset.sbbTickerKey=rowKey(row);
    if(duplicate)btn.tabIndex=-1;
    const type=category(row).replace(/_/g,' ');
    const source=clean(row?.sourceLabel||row?.source||'Sports Big Board');
    const league=clean(row?.league||'SPORT');
    btn.innerHTML='<span class="key-info-type"></span><strong></strong><small></small>';
    btn.querySelector('.key-info-type').textContent=type;
    btn.querySelector('strong').textContent=rowTitle(row);
    btn.querySelector('small').textContent=`${league} • ${source}`;
    btn.title=`${type} • ${league} • ${source}\n${rowTitle(row)}`;
    const href=clean(row?.externalUrl||row?.sourceUrl);
    if(href)btn.addEventListener('click',()=>window.open(href,'_blank','noopener'));
    return btn;
  }

  function captureAnchor(){
    const track=document.getElementById('keyInfoTrack');
    const group=conveyorGroup||track?.querySelector('.sbb-sports-ticker-conveyor');
    if(!track||!group)return {anchors:[],paused:false};
    const tr=track.getBoundingClientRect();
    const anchors=[];
    for(const node of group.children){
      const r=node.getBoundingClientRect();
      if(r.right<=tr.left||r.left>=tr.right)continue;
      anchors.push({key:clean(node.dataset.sbbTickerKey),left:r.left-tr.left});
      if(anchors.length>=8)break;
    }
    return {anchors,paused:conveyorAnimation?.playState==='paused'||hoverPaused||focusPaused};
  }

  function stopConveyor(){
    try{conveyorAnimation?.cancel();}catch(_){}
    conveyorAnimation=null;
  }

  function desiredNodeCount(rows){
    if(!rows.length)return 0;
    return Math.max(12,Math.min(WINDOW_NODES,Math.max(rows.length,12)));
  }

  function appendNextNode(){
    if(!conveyorGroup||!currentRows.length)return;
    conveyorGroup.appendChild(makeItem(currentRows[nextRowIndex]));
    nextRowIndex=(nextRowIndex+1)%currentRows.length;
  }

  function segmentStep(){
    if(!conveyorGroup?.children?.length)return 0;
    const first=conveyorGroup.children[0],second=conveyorGroup.children[1];
    if(second){
      const step=Number(second.offsetLeft)-Number(first.offsetLeft);
      if(step>0)return step;
    }
    const r=first.getBoundingClientRect();
    const css=getComputedStyle(first);
    return Math.max(1,r.width+(parseFloat(css.marginRight)||0)+(parseFloat(css.marginLeft)||0));
  }

  function shouldPause(){
    return hoverPaused||focusPaused||window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches===true;
  }

  function startSegment(startX=0){
    if(!conveyorGroup||!currentRows.length||shouldPause()){
      try{conveyorAnimation?.pause();}catch(_){}
      return;
    }
    stopConveyor();
    const step=segmentStep();if(step<=0)return;
    const from=Math.min(0,Number(startX)||0);
    const target=-step;
    const distance=Math.max(1,Math.abs(target-from));
    const duration=Math.max(500,distance/SPEED_PX_PER_SECOND*1000);
    conveyorGroup.style.transform=`translate3d(${from}px,0,0)`;
    const anim=conveyorGroup.animate(
      [{transform:`translate3d(${from}px,0,0)`},{transform:`translate3d(${target}px,0,0)`}],
      {duration,iterations:1,easing:'linear',fill:'forwards'}
    );
    conveyorAnimation=anim;state.animationSegments++;
    anim.onfinish=()=>{
      if(anim!==conveyorAnimation||!conveyorGroup)return;
      // The first story has completely cleared the left edge. Recycle exactly one
      // node and reset transform in the same task, so the remaining stories occupy
      // identical pixels before the next compositor-only segment starts.
      try{anim.cancel();}catch(_){}
      conveyorAnimation=null;
      const first=conveyorGroup.firstElementChild;
      if(first)first.remove();
      appendNextNode();state.recycledItems++;
      conveyorGroup.style.transform='translate3d(0,0,0)';
      startSegment(0);
    };
  }

  function resumeConveyor(){
    if(shouldPause())return;
    if(conveyorAnimation?.playState==='paused'){try{conveyorAnimation.play();return;}catch(_){}}
    if(!conveyorAnimation&&conveyorGroup)startSegment(0);
  }

  function bindPauseControls(){
    const track=document.getElementById('keyInfoTrack');
    if(!track||track.dataset.sbbTickerPauseBound==='1')return;
    track.dataset.sbbTickerPauseBound='1';
    track.addEventListener('pointerenter',()=>{hoverPaused=true;try{conveyorAnimation?.pause();}catch(_){}});
    track.addEventListener('pointerleave',()=>{hoverPaused=false;resumeConveyor();});
    track.addEventListener('focusin',()=>{focusPaused=true;try{conveyorAnimation?.pause();}catch(_){}});
    track.addEventListener('focusout',()=>{focusPaused=false;resumeConveyor();});
  }

  function mergeEdition(incoming,{replace=false}={}){
    incoming=dedupe(incoming);
    if(replace||!currentRows.length){
      const oldKeys=new Set(currentRows.map(rowKey));
      return {rows:incoming,newRows:incoming.filter(row=>!oldKeys.has(rowKey(row))),changed:true};
    }
    const incomingBy=new Map(incoming.map(row=>[rowKey(row),row]));
    const oldKeys=new Set(currentRows.map(rowKey));
    const newRows=incoming.filter(row=>!oldKeys.has(rowKey(row)));
    const retained=currentRows.filter(row=>incomingBy.has(rowKey(row))).map(row=>incomingBy.get(rowKey(row))||row);
    const retainedKeys=new Set(retained.map(rowKey));
    const newKeys=new Set(newRows.map(rowKey));
    const remainder=incoming.filter(row=>!retainedKeys.has(rowKey(row))&&!newKeys.has(rowKey(row)));
    const rows=dedupe([...newRows,...retained,...remainder]);
    const before=currentRows.map(rowKey).join('\n'),after=rows.map(rowKey).join('\n');
    return {rows,newRows,changed:before!==after};
  }

  function renderOwned(rows,source='',{newRows=[],restart=false}={}){
    rows=dedupe(rows);
    const track=document.getElementById('keyInfoTrack');
    if(!track){currentRows=rows;setState(rows.length,source);return rows;}
    if(!rows.length){
      stopConveyor();conveyorGroup=null;currentRows=[];
      track.innerHTML='<div class="key-info-empty">Sports Ticker is warming in the background.</div>';
      setState(0,source);return [];
    }

    const previous=restart?{anchors:[],paused:false}:captureAnchor();
    currentRows=rows;currentSource=source||currentSource;
    let startIndex=0,initialX=0;
    if(!restart&&previous.anchors.length){
      for(const anchor of previous.anchors){
        const index=rows.findIndex(row=>rowKey(row)===anchor.key);
        if(index<0)continue;
        startIndex=index;initialX=Math.min(0,anchor.left);state.continuityRenders++;break;
      }
    }

    stopConveyor();
    const group=document.createElement('div');
    group.className='sbb-sports-ticker-conveyor';group.dataset.sbbSportsTickerOwner=VERSION;
    const count=desiredNodeCount(rows);
    for(let i=0;i<count;i++)group.appendChild(makeItem(rows[(startIndex+i)%rows.length],i>=rows.length));
    nextRowIndex=(startIndex+count)%rows.length;
    conveyorGroup=group;
    track.replaceChildren(group);
    group.style.transform=`translate3d(${initialX}px,0,0)`;
    state.renders++;state.newItemsPrepended+=newRows.length;
    setState(rows.length,source);
    if(previous.paused||shouldPause())return rows;
    requestAnimationFrame(()=>startSegment(initialX));
    return rows;
  }

  async function requestJson(path,{timeoutMs=2500,method='GET'}={}){
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),timeoutMs);
    try{
      const r=await fetch(api(path),{method,cache:'no-store',signal:controller.signal,headers:{'Accept':'application/json'}});
      let payload={};try{payload=await r.json();}catch(_){}
      if(!r.ok)throw new Error(clean(payload?.error||payload?.message)||`HTTP ${r.status}`);
      return payload;
    }finally{clearTimeout(timer);}
  }

  async function refresh(force=false,{restart=false,replace=false}={}){
    if(inflight)return inflight;
    if(!force&&Date.now()-state.lastRefreshAt<60_000)return currentRows.slice();
    state.refreshes++;state.lastRefreshAt=Date.now();
    inflight=(async()=>{
      try{
        let payload;
        try{payload=await requestJson('/api/sports-ticker',{timeoutMs:2200});}catch(_){payload=await requestJson('/api/current-news',{timeoutMs:2200});}
        const incoming=dedupe(payload?.data||[]);
        if(!incoming.length)return currentRows.slice();
        const merged=mergeEdition(incoming,{replace});
        saveRows(merged.rows,payload?.source||'SPORTS_TICKER',Number(payload?.savedAt||0)*1000||Date.now());
        state.lastError='';
        if(!currentRows.length||merged.changed||restart)renderOwned(merged.rows,payload?.source||'SPORTS_TICKER',{newRows:merged.newRows,restart});
        else{state.noChangeRefreshes++;currentRows=merged.rows;currentSource=payload?.source||currentSource;setState(merged.rows.length,currentSource);}
        return currentRows.slice();
      }catch(err){state.lastError=String(err?.message||err);return currentRows.slice();}
      finally{inflight=null;}
    })();
    return inflight;
  }

  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  function manualStatus(text,kind=''){
    const el=document.getElementById('sportsTickerAiRefreshStatus');if(!el)return;
    el.textContent=text;el.classList.toggle('good',kind==='good');el.classList.toggle('bad',kind==='bad');
  }

  async function manualRefresh(){
    if(manualInflight)return manualInflight;
    const btn=document.getElementById('sportsTickerAiRefreshBtn');
    state.manualRuns++;
    manualInflight=(async()=>{
      const oldLabel=btn?.textContent||'RUN SPORTS TICKER AI';
      if(btn){btn.disabled=true;btn.textContent='RUNNING SPORTS TICKER AI…';}
      manualStatus('Collecting fresh sports news…');
      try{
        const accepted=await requestJson('/api/sports-ticker/refresh',{method:'POST',timeoutMs:5000});
        const requestedAt=Number(accepted?.requestedAt||0);
        manualStatus('Fresh sources requested • OpenAI editorial pass running…');
        let finalStatus=null;
        for(let attempt=0;attempt<80;attempt++){
          await sleep(1250);
          const status=await requestJson('/api/sports-ticker/status',{timeoutMs:3000});
          const running=!!(status?.refreshing||status?.manualRunning);
          const completed=Number(status?.manualCompletedAt||0);
          if(running){
            manualStatus(`OpenAI Sports Ticker running… ${Number(status?.manualSourceCount||0)||'fresh'} source items`);
            continue;
          }
          if(status?.manualLastError)throw new Error(status.manualLastError);
          if(!requestedAt||completed>=requestedAt){finalStatus=status;break;}
        }
        if(!finalStatus)throw new Error('Sports Ticker AI refresh did not complete before the operator timeout.');
        // This is an explicit operator action, so show the new edition from its first
        // story immediately. Ordinary background/date activity never restarts it.
        if(inflight){try{await inflight;}catch(_){}}
        await refresh(true,{restart:true,replace:true});
        const mode=clean(finalStatus?.source||currentSource||'OPENAI_SPORTS_TICKER');
        manualStatus(`Updated • ${currentRows.length} stories • ${mode}`,'good');
        return currentRows.slice();
      }catch(err){
        state.manualErrors++;state.lastError=String(err?.message||err);
        manualStatus(`Refresh failed: ${state.lastError}`,'bad');throw err;
      }finally{
        if(btn){btn.disabled=false;btn.textContent=oldLabel;}
        manualInflight=null;
      }
    })();
    return manualInflight;
  }

  function bindDevButton(){
    const btn=document.getElementById('sportsTickerAiRefreshBtn');
    if(!btn||btn.dataset.sbbTickerBound==='1')return;
    btn.dataset.sbbTickerBound='1';
    btn.addEventListener('click',()=>{void manualRefresh().catch(()=>{});});
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
    const local=cachedSnapshot();
    if(local.data.length){state.cachePaints++;currentRows=local.data;currentSource=local.source||'BROWSER_CACHE';renderOwned(currentRows,currentSource,{newRows:[],restart:true});}
    else setState(0,'');

    isolateLegacyLane();
    clearInterval(refreshTimer);
    refreshTimer=setInterval(()=>{if(!document.hidden)void refresh(false);},REFRESH_MS);
    window.addEventListener('focus',()=>{if(Date.now()-state.lastRefreshAt>REFRESH_MS)void refresh(false);},{passive:true});
    document.addEventListener('visibilitychange',()=>{if(!document.hidden&&Date.now()-state.lastRefreshAt>REFRESH_MS)void refresh(false);});

    let guards=0;const ownership=setInterval(()=>{
      guards++;isolateLegacyLane();bindDevButton();
      try{window.SBB_DATE_TRANSITIONS?.install?.();}catch(_){}
      if(guards>=32)clearInterval(ownership);
    },250);

    state.installed=true;void refresh(false);return true;
  }

  const apiObject=Object.freeze({
    version:VERSION,name:'SPORTS_TICKER',refresh,manualRefresh,
    render:rows=>{const merged=mergeEdition(rows);return renderOwned(merged.rows,'API',{newRows:merged.newRows});},
    rows:()=>currentRows.slice(),snapshot:()=>({...state,currentCount:currentRows.length,currentSource,animationState:conveyorAnimation?.playState||'idle'})
  });
  window.SBB_KEY_INFO_CURRENT=apiObject;
  window.SBB_SPORTS_TICKER=apiObject;
  install();
})();

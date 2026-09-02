/* Sports Big Board v5.2.7 — calm continuous Sports Ticker + live Dev tuning.

   The v5.2.6 segmented Web Animation restarted at every story boundary. Even when
   each segment was linear, cancel/recreate/reflow at the boundary could still read
   as a periodic hitch. v5.2.7 uses one requestAnimationFrame clock for the lifetime
   of the conveyor. Story recycling happens underneath that clock without restarting
   motion, and the default crawl is deliberately slowed to a calmer 30 px/s.
*/
(() => {
  'use strict';
  if(window.SBB_KEY_INFO_CURRENT?.version==='5.2.7')return;

  const VERSION='5.2.7';
  const REFRESH_MS=20*60*1000;
  const CACHE_KEY='sbb.sports-ticker.v1';
  const LEGACY_CACHE_KEYS=['sbb.sports-ticker.v524','sbb.current-news.v522'];
  const TUNING_KEY='sbb.sports-ticker.tuning.v527';
  const CACHE_MAX_AGE=24*60*60*1000;
  const MAX_ROWS=150;
  const WINDOW_NODES=28;
  const DEFAULT_TUNING=Object.freeze({height:40,fontSize:10.5,lines:1,speed:30,gap:18});
  const LIMITS=Object.freeze({height:[32,72],fontSize:[8,18],lines:[1,2],speed:[8,90],gap:[0,48]});

  const state={
    installed:false,renders:0,refreshes:0,cachePaints:0,lastRefreshAt:0,lastCount:0,lastError:'',source:'',
    dateIsolation:true,dateTriggeredNoops:0,legacyRefreshNoops:0,newItemsPrepended:0,continuityRenders:0,
    noChangeRefreshes:0,recycledItems:0,animationFrames:0,droppedFrameCaps:0,manualRuns:0,manualErrors:0,
    windowNodes:WINDOW_NODES,maxRows:MAX_ROWS,refreshMs:REFRESH_MS,engine:'RAF_CONTINUOUS'
  };

  let tuning=loadTuning();
  let refreshTimer=0;
  let inflight=null;
  let manualInflight=null;
  let currentRows=[];
  let currentSource='';
  let conveyorGroup=null;
  let nextRowIndex=0;
  let conveyorX=0;
  let rafId=0;
  let lastFrameTs=0;
  let hoverPaused=false;
  let focusPaused=false;
  let userPaused=false;

  const api=path=>window.SBB_API?.url?window.SBB_API.url(path):path;
  const clean=v=>String(v??'').trim();
  const norm=v=>clean(v).toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
  const rowTitle=row=>clean(row?.shortHeadline||row?.headline||row?.title||'Sports update');
  const category=row=>clean(row?.category||row?.eventType||'UPDATE').toUpperCase().replace(/\s+/g,'_');
  const categoryClass=row=>category(row).toLowerCase().replace(/[^a-z0-9_-]+/g,'-');
  const rowKey=row=>[
    clean(row?.id||row?.eventId||row?.gameId||row?.tickerKey||row?.sourceUrl||row?.externalUrl),
    norm(rowTitle(row)),category(row)
  ].join('|');
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,Number(value)));

  function normalizeTuning(raw={}){
    const lines=Number(raw.lines)===2?2:1;
    return {
      height:clamp(raw.height??DEFAULT_TUNING.height,...LIMITS.height),
      fontSize:clamp(raw.fontSize??DEFAULT_TUNING.fontSize,...LIMITS.fontSize),
      lines,
      speed:clamp(raw.speed??DEFAULT_TUNING.speed,...LIMITS.speed),
      gap:clamp(raw.gap??DEFAULT_TUNING.gap,...LIMITS.gap)
    };
  }
  function loadTuning(){
    try{return normalizeTuning(JSON.parse(localStorage.getItem(TUNING_KEY)||'null')||{});}catch(_){return {...DEFAULT_TUNING};}
  }
  function saveTuning(){try{localStorage.setItem(TUNING_KEY,JSON.stringify(tuning));}catch(_){} }

  function dedupe(rows){
    const out=[],seen=new Set();
    for(const row of Array.isArray(rows)?rows:[]){
      if(!row||typeof row!=='object')continue;
      const key=rowKey(row);if(!key||seen.has(key))continue;
      seen.add(key);out.push(row);if(out.length>=MAX_ROWS)break;
    }
    return out;
  }

  function installUi(){
    if(!document.getElementById('sbbSportsTickerV527Style')){
      const style=document.createElement('style');
      style.id='sbbSportsTickerV527Style';
      style.textContent=`
        :root{--sbb-ticker-height:40px;--sbb-ticker-font-size:10.5px;--sbb-ticker-gap:18px}
        #scoreFilters>button[data-score-filter="NCAAF"]{align-self:center!important;display:inline-flex!important;align-items:center!important;justify-content:center!important;vertical-align:middle!important}
        .key-info-ribbon{height:var(--sbb-ticker-height)!important;min-height:var(--sbb-ticker-height)!important;align-items:stretch!important}
        .key-info-ribbon .key-info-label{height:var(--sbb-ticker-height)!important;min-height:var(--sbb-ticker-height)!important;align-items:center!important}
        #keyInfoTrack{height:var(--sbb-ticker-height)!important;min-height:var(--sbb-ticker-height)!important;overflow:hidden!important;position:relative!important}
        .sbb-sports-ticker-conveyor{display:flex!important;align-items:stretch!important;gap:0!important;width:max-content!important;height:100%!important;transform:translate3d(0,0,0);will-change:transform;backface-visibility:hidden;-webkit-backface-visibility:hidden;contain:layout style;}
        .sbb-sports-ticker-conveyor>.key-info-item{flex:0 0 auto!important;width:max-content!important;min-width:0!important;max-width:none!important;height:100%!important;min-height:100%!important;margin:0 var(--sbb-ticker-gap) 0 0!important;padding-left:11px!important;padding-right:11px!important;box-shadow:none!important;filter:none!important;transition:none!important;transform:none!important;backface-visibility:hidden;-webkit-backface-visibility:hidden;}
        .sbb-sports-ticker-conveyor>.key-info-item:hover{box-shadow:none!important;transform:none!important}
        .sbb-sports-ticker-conveyor .key-info-item strong{font-size:var(--sbb-ticker-font-size)!important;line-height:1.2!important;max-width:min(72vw,980px)!important;overflow:hidden!important;text-overflow:ellipsis!important}
        html[data-sbb-ticker-lines="1"] .sbb-sports-ticker-conveyor .key-info-item strong{display:block!important;white-space:nowrap!important;max-height:1.25em!important}
        html[data-sbb-ticker-lines="2"] .sbb-sports-ticker-conveyor .key-info-item strong{display:-webkit-box!important;-webkit-box-orient:vertical!important;-webkit-line-clamp:2!important;white-space:normal!important;max-height:2.4em!important;text-wrap:balance}
        .sbb-sports-ticker-conveyor .key-info-item small{display:none!important}
        .sbb-sports-ticker-conveyor .key-info-type{flex:0 0 auto!important;border-width:1px!important;border-style:solid!important}
        .sbb-sports-ticker-conveyor .key-info-item.breaking .key-info-type{background:#45171b!important;border-color:#a63a42!important;color:#ff9aa2!important}
        .sbb-sports-ticker-conveyor .key-info-item.injury .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.suspension .key-info-type{background:#402016!important;border-color:#9d5738!important;color:#ffb38b!important}
        .sbb-sports-ticker-conveyor .key-info-item.transaction .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.coaching .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.recruiting .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.draft .key-info-type{background:#102a42!important;border-color:#326a96!important;color:#8ed0ff!important}
        .sbb-sports-ticker-conveyor .key-info-item.record .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.record_watch .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.milestone .key-info-type{background:#2b1a45!important;border-color:#7251a0!important;color:#cbb0ff!important}
        .sbb-sports-ticker-conveyor .key-info-item.result .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.upset .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.streak .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.return .key-info-type{background:#172f20!important;border-color:#467a55!important;color:#a9e6b5!important}
        .sbb-sports-ticker-conveyor .key-info-item.championship .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.clinch .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.elimination .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.playoff .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.award .key-info-type{background:#3a3014!important;border-color:#8d7934!important;color:#ffe38a!important}
        .sbb-sports-ticker-conveyor .key-info-item.ranking .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.tournament .key-info-type,.sbb-sports-ticker-conveyor .key-info-item.schedule .key-info-type{background:#103536!important;border-color:#357a7b!important;color:#9ce9e8!important}
        .sbb-sports-ticker-conveyor .key-info-item.retirement .key-info-type{background:#2b2d31!important;border-color:#666d76!important;color:#d5d9df!important}
        .sports-ticker-dev-card{display:none!important}
        html[data-sbb-dev="1"] .sports-ticker-dev-card,body[data-sbb-dev="1"] .sports-ticker-dev-card,body.dev-mode .sports-ticker-dev-card{display:block!important}
        .sports-ticker-dev-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:10px}
        .sports-ticker-dev-field{display:grid;gap:5px;padding:9px 10px;border:1px solid var(--line,#25303a);border-radius:9px;background:#0b1117}
        .sports-ticker-dev-field>span{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:9px;font-weight:850;letter-spacing:.045em;color:#c7d0d9}
        .sports-ticker-dev-field output{font-variant-numeric:tabular-nums;color:#7fc7ff}
        .sports-ticker-dev-field input[type="range"]{width:100%;accent-color:#2494ff}
        .sports-ticker-dev-field select{width:100%;padding:7px 8px;border-radius:7px}
        .sports-ticker-dev-actions{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}
        .sports-ticker-dev-actions .settings-save-btn{flex:1 1 170px}
        .sports-ticker-dev-status{display:block;margin-top:8px;color:var(--muted,#8f9aa6);font-size:10px;line-height:1.4}
        .sports-ticker-dev-status.good{color:#7bf1a9}.sports-ticker-dev-status.bad{color:#ff9b92}
        .sports-ticker-tuning-summary{display:block;margin-top:8px;padding:7px 8px;border-radius:7px;background:#090e13;border:1px solid #202a33;color:#aeb8c2;font:10px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace}
        @media(max-width:760px){.sports-ticker-dev-grid{grid-template-columns:1fr}.sbb-sports-ticker-conveyor .key-info-item strong{max-width:78vw!important}}
        @media (prefers-reduced-motion:reduce){.sbb-sports-ticker-conveyor{transform:none!important;will-change:auto!important}#keyInfoTrack{overflow-x:auto!important}}
      `;
      document.head.appendChild(style);
    }
    const label=document.querySelector('.key-info-label strong');if(label)label.textContent='SPORTS TICKER';
    applyTuning(false);bindDevControls();bindPauseControls();
  }

  function readCacheKey(key){
    try{
      const payload=JSON.parse(localStorage.getItem(key)||'null');
      if(!payload||!Array.isArray(payload.data)||Date.now()-Number(payload.savedAt||0)>CACHE_MAX_AGE)return null;
      return {savedAt:Number(payload.savedAt||0),source:clean(payload.source),data:dedupe(payload.data)};
    }catch(_){return null;}
  }
  function cachedSnapshot(){
    let payload=readCacheKey(CACHE_KEY);if(payload?.data?.length)return payload;
    for(const key of LEGACY_CACHE_KEYS){
      payload=readCacheKey(key);
      if(payload?.data?.length){try{localStorage.setItem(CACHE_KEY,JSON.stringify(payload));}catch(_){}return payload;}
    }
    return {savedAt:0,source:'',data:[]};
  }
  function saveRows(rows,source='',savedAt=Date.now()){
    rows=dedupe(rows);if(!rows.length)return;
    try{localStorage.setItem(CACHE_KEY,JSON.stringify({savedAt:Number(savedAt)||Date.now(),source,data:rows}));}catch(_){}
  }

  function setState(count,source=''){
    installUi();const label=document.getElementById('keyInfoState');
    if(label)label.textContent=count?`${count} update${count===1?'':'s'}`:'warming cached ticker';
    state.lastCount=count;state.source=source||state.source;
  }

  function makeItem(row,duplicate=false){
    const btn=document.createElement('button');
    btn.type='button';btn.className=`key-info-item ${categoryClass(row)}`;btn.dataset.sbbTickerKey=rowKey(row);
    if(duplicate)btn.tabIndex=-1;
    const type=category(row).replace(/_/g,' '),source=clean(row?.sourceLabel||row?.source||'Sports Big Board'),league=clean(row?.league||'SPORT');
    btn.innerHTML='<span class="key-info-type"></span><strong></strong><small></small>';
    btn.querySelector('.key-info-type').textContent=type;btn.querySelector('strong').textContent=rowTitle(row);btn.querySelector('small').textContent=`${league} • ${source}`;
    btn.title=`${type} • ${league} • ${source}\n${rowTitle(row)}`;
    const href=clean(row?.externalUrl||row?.sourceUrl);if(href)btn.addEventListener('click',()=>window.open(href,'_blank','noopener'));
    return btn;
  }

  function captureAnchor(){
    const track=document.getElementById('keyInfoTrack'),group=conveyorGroup||track?.querySelector('.sbb-sports-ticker-conveyor');
    if(!track||!group)return {anchors:[],paused:false};
    const tr=track.getBoundingClientRect(),anchors=[];
    for(const node of group.children){
      const r=node.getBoundingClientRect();if(r.right<=tr.left||r.left>=tr.right)continue;
      anchors.push({key:clean(node.dataset.sbbTickerKey),left:r.left-tr.left});if(anchors.length>=8)break;
    }
    return {anchors,paused:shouldPause()};
  }

  function desiredNodeCount(rows){return rows.length?Math.max(12,Math.min(WINDOW_NODES,Math.max(rows.length,12))):0;}
  function appendNextNode(){
    if(!conveyorGroup||!currentRows.length)return;
    conveyorGroup.appendChild(makeItem(currentRows[nextRowIndex]));nextRowIndex=(nextRowIndex+1)%currentRows.length;
  }
  function segmentStep(){
    if(!conveyorGroup?.children?.length)return 0;
    const first=conveyorGroup.children[0],second=conveyorGroup.children[1];
    if(second){const step=Number(second.offsetLeft)-Number(first.offsetLeft);if(step>0)return step;}
    const css=getComputedStyle(first),r=first.getBoundingClientRect();
    return Math.max(1,r.width+(parseFloat(css.marginRight)||0)+(parseFloat(css.marginLeft)||0));
  }
  function shouldPause(){return userPaused||hoverPaused||focusPaused||document.hidden||window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches===true;}

  function stopClock(){if(rafId)cancelAnimationFrame(rafId);rafId=0;lastFrameTs=0;}
  function recycleClearedNodes(){
    if(!conveyorGroup)return;
    let safety=0;
    while(conveyorGroup.firstElementChild&&safety++<5){
      const step=segmentStep();if(step<=0||conveyorX>-step)break;
      const first=conveyorGroup.firstElementChild;first.remove();appendNextNode();conveyorX+=step;state.recycledItems++;
    }
  }
  function tickerFrame(ts){
    rafId=0;
    if(!conveyorGroup||!currentRows.length){lastFrameTs=0;return;}
    if(!lastFrameTs)lastFrameTs=ts;
    const rawDt=Math.max(0,ts-lastFrameTs);lastFrameTs=ts;
    if(!shouldPause()){
      // Never "catch up" with a visible jump after a busy main-thread frame. A
      // delayed frame may make the crawl fractionally slower, but it stays calm.
      const dt=Math.min(rawDt,40);if(rawDt>40)state.droppedFrameCaps++;
      conveyorX-=tuning.speed*(dt/1000);recycleClearedNodes();
      conveyorGroup.style.transform=`translate3d(${conveyorX.toFixed(3)}px,0,0)`;state.animationFrames++;
    }
    rafId=requestAnimationFrame(tickerFrame);
  }
  function ensureClock(){if(!rafId&&conveyorGroup)rafId=requestAnimationFrame(tickerFrame);}

  function bindPauseControls(){
    const track=document.getElementById('keyInfoTrack');if(!track||track.dataset.sbbTickerPauseBound==='1')return;
    track.dataset.sbbTickerPauseBound='1';
    track.addEventListener('pointerenter',()=>{hoverPaused=true;});
    track.addEventListener('pointerleave',()=>{hoverPaused=false;lastFrameTs=0;ensureClock();});
    track.addEventListener('focusin',()=>{focusPaused=true;});
    track.addEventListener('focusout',()=>{focusPaused=false;lastFrameTs=0;ensureClock();});
    document.addEventListener('visibilitychange',()=>{lastFrameTs=0;if(!document.hidden)ensureClock();});
  }

  function mergeEdition(incoming,{replace=false}={}){
    incoming=dedupe(incoming);
    if(replace||!currentRows.length){const oldKeys=new Set(currentRows.map(rowKey));return {rows:incoming,newRows:incoming.filter(row=>!oldKeys.has(rowKey(row))),changed:true};}
    const incomingBy=new Map(incoming.map(row=>[rowKey(row),row])),oldKeys=new Set(currentRows.map(rowKey));
    const newRows=incoming.filter(row=>!oldKeys.has(rowKey(row))),retained=currentRows.filter(row=>incomingBy.has(rowKey(row))).map(row=>incomingBy.get(rowKey(row))||row);
    const retainedKeys=new Set(retained.map(rowKey)),newKeys=new Set(newRows.map(rowKey));
    const remainder=incoming.filter(row=>!retainedKeys.has(rowKey(row))&&!newKeys.has(rowKey(row))),rows=dedupe([...newRows,...retained,...remainder]);
    return {rows,newRows,changed:currentRows.map(rowKey).join('\n')!==rows.map(rowKey).join('\n')};
  }

  function renderOwned(rows,source='',{newRows=[],restart=false}={}){
    rows=dedupe(rows);const track=document.getElementById('keyInfoTrack');
    if(!track){currentRows=rows;setState(rows.length,source);return rows;}
    if(!rows.length){stopClock();conveyorGroup=null;currentRows=[];track.innerHTML='<div class="key-info-empty">Sports Ticker is warming in the background.</div>';setState(0,source);return [];}

    const previous=restart?{anchors:[],paused:false}:captureAnchor();
    currentRows=rows;currentSource=source||currentSource;
    let startIndex=0,initialX=0;
    if(!restart&&previous.anchors.length){
      for(const anchor of previous.anchors){const index=rows.findIndex(row=>rowKey(row)===anchor.key);if(index<0)continue;startIndex=index;initialX=Math.min(0,anchor.left);state.continuityRenders++;break;}
    }

    stopClock();
    const group=document.createElement('div');group.className='sbb-sports-ticker-conveyor';group.dataset.sbbSportsTickerOwner=VERSION;
    const count=desiredNodeCount(rows);for(let i=0;i<count;i++)group.appendChild(makeItem(rows[(startIndex+i)%rows.length],i>=rows.length));
    nextRowIndex=(startIndex+count)%rows.length;conveyorGroup=group;conveyorX=initialX;track.replaceChildren(group);
    group.style.transform=`translate3d(${conveyorX}px,0,0)`;state.renders++;state.newItemsPrepended+=newRows.length;setState(rows.length,source);
    lastFrameTs=0;ensureClock();return rows;
  }

  function tuningSummary(){return `height=${tuning.height}px | font=${tuning.fontSize}px | lines=${tuning.lines} | speed=${tuning.speed}px/s | gap=${tuning.gap}px`;}
  function syncDevControls(){
    const pairs=[['sportsTickerHeight',tuning.height,'sportsTickerHeightValue',`${tuning.height}px`],['sportsTickerFontSize',tuning.fontSize,'sportsTickerFontSizeValue',`${tuning.fontSize}px`],['sportsTickerSpeed',tuning.speed,'sportsTickerSpeedValue',`${tuning.speed}px/s`],['sportsTickerGap',tuning.gap,'sportsTickerGapValue',`${tuning.gap}px`]];
    for(const [id,value,outId,label] of pairs){const input=document.getElementById(id),out=document.getElementById(outId);if(input)input.value=String(value);if(out)out.textContent=label;}
    const lines=document.getElementById('sportsTickerLines');if(lines)lines.value=String(tuning.lines);
    const summary=document.getElementById('sportsTickerTuningSummary');if(summary)summary.textContent=tuningSummary();
    const pause=document.getElementById('sportsTickerPauseBtn');if(pause)pause.textContent=userPaused?'RESUME TICKER':'PAUSE TICKER';
  }
  function applyTuning(persist=true){
    tuning=normalizeTuning(tuning);const root=document.documentElement;
    root.style.setProperty('--sbb-ticker-height',`${tuning.height}px`);root.style.setProperty('--sbb-ticker-font-size',`${tuning.fontSize}px`);root.style.setProperty('--sbb-ticker-gap',`${tuning.gap}px`);root.dataset.sbbTickerLines=String(tuning.lines);
    if(persist)saveTuning();syncDevControls();lastFrameTs=0;ensureClock();
    try{window.dispatchEvent(new CustomEvent('sbb:sports-ticker-tuning',{detail:{...tuning}}));}catch(_){}
    return {...tuning};
  }
  function setTuning(patch={}){tuning=normalizeTuning({...tuning,...patch});return applyTuning(true);}
  function resetTuning(){tuning={...DEFAULT_TUNING};userPaused=false;return applyTuning(true);}

  function bindDevControls(){
    const bindings=[['sportsTickerHeight','input',v=>({height:Number(v)})],['sportsTickerFontSize','input',v=>({fontSize:Number(v)})],['sportsTickerLines','change',v=>({lines:Number(v)})],['sportsTickerSpeed','input',v=>({speed:Number(v)})],['sportsTickerGap','input',v=>({gap:Number(v)})]];
    for(const [id,event,patch] of bindings){const el=document.getElementById(id);if(!el||el.dataset.sbbTickerTuneBound==='1')continue;el.dataset.sbbTickerTuneBound='1';el.addEventListener(event,()=>setTuning(patch(el.value)));}
    const pause=document.getElementById('sportsTickerPauseBtn');
    if(pause&&pause.dataset.sbbTickerBound!=='1'){pause.dataset.sbbTickerBound='1';pause.addEventListener('click',()=>{userPaused=!userPaused;lastFrameTs=0;syncDevControls();ensureClock();});}
    const reset=document.getElementById('sportsTickerResetTuningBtn');
    if(reset&&reset.dataset.sbbTickerBound!=='1'){reset.dataset.sbbTickerBound='1';reset.addEventListener('click',()=>resetTuning());}
    const copy=document.getElementById('sportsTickerCopyTuningBtn');
    if(copy&&copy.dataset.sbbTickerBound!=='1'){copy.dataset.sbbTickerBound='1';copy.addEventListener('click',async()=>{const text=tuningSummary();try{await navigator.clipboard.writeText(text);manualStatus(`Copied tuning: ${text}`,'good');}catch(_){manualStatus(text,'good');}});}
    bindDevButton();syncDevControls();
  }

  async function requestJson(path,{timeoutMs=2500,method='GET'}={}){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);
    try{const r=await fetch(api(path),{method,cache:'no-store',signal:controller.signal,headers:{'Accept':'application/json'}});let payload={};try{payload=await r.json();}catch(_){}if(!r.ok)throw new Error(clean(payload?.error||payload?.message)||`HTTP ${r.status}`);return payload;}finally{clearTimeout(timer);}
  }

  async function refresh(force=false,{restart=false,replace=false}={}){
    if(inflight)return inflight;if(!force&&Date.now()-state.lastRefreshAt<60_000)return currentRows.slice();
    state.refreshes++;state.lastRefreshAt=Date.now();
    inflight=(async()=>{try{
      let payload;try{payload=await requestJson('/api/sports-ticker',{timeoutMs:2200});}catch(_){payload=await requestJson('/api/current-news',{timeoutMs:2200});}
      const incoming=dedupe(payload?.data||[]);if(!incoming.length)return currentRows.slice();
      const merged=mergeEdition(incoming,{replace});saveRows(merged.rows,payload?.source||'SPORTS_TICKER',Number(payload?.savedAt||0)*1000||Date.now());state.lastError='';
      if(!currentRows.length||merged.changed||restart)renderOwned(merged.rows,payload?.source||'SPORTS_TICKER',{newRows:merged.newRows,restart});
      else{state.noChangeRefreshes++;currentRows=merged.rows;currentSource=payload?.source||currentSource;setState(merged.rows.length,currentSource);}return currentRows.slice();
    }catch(err){state.lastError=String(err?.message||err);return currentRows.slice();}finally{inflight=null;}})();return inflight;
  }

  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  function manualStatus(text,kind=''){const el=document.getElementById('sportsTickerAiRefreshStatus');if(!el)return;el.textContent=text;el.classList.toggle('good',kind==='good');el.classList.toggle('bad',kind==='bad');}
  async function manualRefresh(){
    if(manualInflight)return manualInflight;const btn=document.getElementById('sportsTickerAiRefreshBtn');state.manualRuns++;
    manualInflight=(async()=>{const oldLabel=btn?.textContent||'RUN SPORTS TICKER AI';if(btn){btn.disabled=true;btn.textContent='RUNNING SPORTS TICKER AI…';}manualStatus('Collecting fresh sports news…');
      try{
        const accepted=await requestJson('/api/sports-ticker/refresh',{method:'POST',timeoutMs:5000}),requestedAt=Number(accepted?.requestedAt||0);manualStatus('Fresh sources requested • OpenAI editorial pass running…');
        let finalStatus=null;for(let attempt=0;attempt<80;attempt++){await sleep(1250);const status=await requestJson('/api/sports-ticker/status',{timeoutMs:3000}),running=!!(status?.refreshing||status?.manualRunning),completed=Number(status?.manualCompletedAt||0);if(running){manualStatus(`OpenAI Sports Ticker running… ${Number(status?.manualSourceCount||0)||'fresh'} source items`);continue;}if(status?.manualLastError)throw new Error(status.manualLastError);if(!requestedAt||completed>=requestedAt){finalStatus=status;break;}}
        if(!finalStatus)throw new Error('Sports Ticker AI refresh did not complete before the operator timeout.');if(inflight){try{await inflight;}catch(_){}}await refresh(true,{restart:true,replace:true});
        const mode=clean(finalStatus?.source||currentSource||'OPENAI_SPORTS_TICKER');manualStatus(`Updated • ${currentRows.length} stories • ${mode}`,'good');return currentRows.slice();
      }catch(err){state.manualErrors++;state.lastError=String(err?.message||err);manualStatus(`Refresh failed: ${state.lastError}`,'bad');throw err;}
      finally{if(btn){btn.disabled=false;btn.textContent=oldLabel;}manualInflight=null;}
    })();return manualInflight;
  }
  function bindDevButton(){const btn=document.getElementById('sportsTickerAiRefreshBtn');if(!btn||btn.dataset.sbbTickerBound==='1')return;btn.dataset.sbbTickerBound='1';btn.addEventListener('click',()=>{void manualRefresh().catch(()=>{});});}

  function legacyNoop(kind){if(kind==='refresh')state.legacyRefreshNoops++;else state.dateTriggeredNoops++;return currentRows.slice();}
  function isolateLegacyLane(){
    const renderNoop=()=>legacyNoop('render'),refreshNoop=()=>Promise.resolve(legacyNoop('refresh'));renderNoop.__sbbSportsTickerDateNoop=true;refreshNoop.__sbbSportsTickerDateNoop=true;
    try{window.renderActiveSportKeyInformation=renderNoop;}catch(_){}try{renderActiveSportKeyInformation=renderNoop;}catch(_){}try{window.renderKeyInformation=renderNoop;}catch(_){}try{renderKeyInformation=renderNoop;}catch(_){}try{window.refreshKeyInformation=refreshNoop;}catch(_){}try{refreshKeyInformation=refreshNoop;}catch(_){}
    try{if(typeof keyInfoStartupRetryTimer!=='undefined'&&keyInfoStartupRetryTimer){clearTimeout(keyInfoStartupRetryTimer);keyInfoStartupRetryTimer=null;}}catch(_){}
  }

  function install(){
    installUi();const local=cachedSnapshot();if(local.data.length){state.cachePaints++;currentRows=local.data;currentSource=local.source||'BROWSER_CACHE';renderOwned(currentRows,currentSource,{newRows:[],restart:true});}else setState(0,'');
    isolateLegacyLane();clearInterval(refreshTimer);refreshTimer=setInterval(()=>{if(!document.hidden)void refresh(false);},REFRESH_MS);window.addEventListener('focus',()=>{if(Date.now()-state.lastRefreshAt>REFRESH_MS)void refresh(false);},{passive:true});
    let guards=0;const ownership=setInterval(()=>{guards++;isolateLegacyLane();bindDevControls();try{window.SBB_DATE_TRANSITIONS?.install?.();}catch(_){}if(guards>=32)clearInterval(ownership);},250);
    state.installed=true;void refresh(false);return true;
  }

  const apiObject=Object.freeze({
    version:VERSION,name:'SPORTS_TICKER',refresh,manualRefresh,setTuning,resetTuning,tuning:()=>({...tuning}),pause:()=>{userPaused=true;syncDevControls();},resume:()=>{userPaused=false;lastFrameTs=0;syncDevControls();ensureClock();},
    render:rows=>{const merged=mergeEdition(rows);return renderOwned(merged.rows,'API',{newRows:merged.newRows});},rows:()=>currentRows.slice(),
    snapshot:()=>({...state,currentCount:currentRows.length,currentSource,paused:shouldPause(),tuning:{...tuning},conveyorX})
  });
  window.SBB_KEY_INFO_CURRENT=apiObject;window.SBB_SPORTS_TICKER=apiObject;install();
})();

/* Sports Big Board v5.2.11 — compositor Sports Ticker + always-visible operator tuning.

   v5.2.7 removed segmented animation restarts, but its requestAnimationFrame loop
   still performed layout reads while recycling stories. Those reads competed with
   scores, Game Center, diagnostics and video state on the main thread. v5.2.8 does
   all geometry work only when an edition/tuning changes, then hands one infinite
   linear transform animation to the browser compositor. There is no per-frame JS.
*/
(() => {
  'use strict';
  if(window.SBB_KEY_INFO_CURRENT?.version==='5.2.11')return;

  const VERSION='5.2.11';
  const REFRESH_MS=20*60*1000;
  const CACHE_KEY='sbb.sports-ticker.v1';
  const LEGACY_CACHE_KEYS=['sbb.sports-ticker.v524','sbb.current-news.v522'];
  const TUNING_KEY='sbb.sports-ticker.tuning.v528';
  const LEGACY_TUNING_KEYS=['sbb.sports-ticker.tuning.v527'];
  const CACHE_MAX_AGE=24*60*60*1000;
  const MAX_ROWS=150;
  const DUPLICATE_PREFIX=48;
  const DEFAULT_TUNING=Object.freeze({height:40,fontSize:10.5,lines:1,speed:20,gap:18});
  const LIMITS=Object.freeze({height:[32,72],fontSize:[8,18],lines:[1,2],speed:[4,60],gap:[0,48]});

  const state={
    installed:false,renders:0,refreshes:0,cachePaints:0,lastRefreshAt:0,lastCount:0,lastError:'',source:'',
    dateIsolation:true,dateTriggeredNoops:0,legacyRefreshNoops:0,newItemsPrepended:0,noChangeRefreshes:0,
    manualRuns:0,manualErrors:0,geometryBuilds:0,animationStarts:0,devUtilityInjections:0,
    maxRows:MAX_ROWS,refreshMs:REFRESH_MS,engine:'COMPOSITOR_WAAPI_LOOP',mainThreadPerFrame:false,forcedLayoutReadsPerFrame:0
  };

  let tuning=loadTuning();
  let refreshTimer=0;
  let inflight=null;
  let manualInflight=null;
  let currentRows=[];
  let currentSource='';
  let conveyorGroup=null;
  let cycleGroup=null;
  let tickerAnimation=null;
  let cycleWidth=0;
  let animationDuration=0;
  let hoverPaused=false;
  let focusPaused=false;
  let userPaused=false;
  let geometryTimer=0;

  const api=path=>window.SBB_API?.url?window.SBB_API.url(path):path;
  const clean=v=>String(v??'').trim();
  const norm=v=>clean(v).toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
  const rowTitle=row=>clean(row?.shortHeadline||row?.headline||row?.title||'Sports update');
  const category=row=>clean(row?.category||row?.eventType||'UPDATE').toUpperCase().replace(/\s+/g,'_');
  const categoryClass=row=>category(row).toLowerCase().replace(/[^a-z0-9_-]+/g,'-');
  const rowKey=row=>[clean(row?.id||row?.eventId||row?.gameId||row?.tickerKey||row?.sourceUrl||row?.externalUrl),norm(rowTitle(row)),category(row)].join('|');
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,Number(value)));

  function normalizeTuning(raw={}){
    return {
      height:clamp(raw.height??DEFAULT_TUNING.height,...LIMITS.height),
      fontSize:clamp(raw.fontSize??DEFAULT_TUNING.fontSize,...LIMITS.fontSize),
      lines:Number(raw.lines)===2?2:1,
      speed:clamp(raw.speed??DEFAULT_TUNING.speed,...LIMITS.speed),
      gap:clamp(raw.gap??DEFAULT_TUNING.gap,...LIMITS.gap)
    };
  }
  function loadTuning(){
    try{
      const current=JSON.parse(localStorage.getItem(TUNING_KEY)||'null');if(current)return normalizeTuning(current);
      for(const key of LEGACY_TUNING_KEYS){const legacy=JSON.parse(localStorage.getItem(key)||'null');if(legacy)return normalizeTuning(legacy);}
    }catch(_){}
    return {...DEFAULT_TUNING};
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

  function utilityMarkup(){
    return `
      <div class="settings-card-title">SPORTS TICKER / TUNING</div>
      <div class="history-audit-launch-copy"><strong>Sports Ticker Dev Utility</strong><small>Live-tune the ticker until movement is calm and non-distracting. Changes apply immediately and persist in this browser. The ticker runs on one compositor transform with zero per-frame JavaScript. This utility is always available in Settings.</small></div>
      <div class="sports-ticker-dev-grid" aria-label="Sports Ticker tuning controls">
        <label class="sports-ticker-dev-field"><span>TICKER HEIGHT <output id="sportsTickerHeightValue">40px</output></span><input id="sportsTickerHeight" type="range" min="32" max="72" step="1" value="40"></label>
        <label class="sports-ticker-dev-field"><span>HEADLINE FONT <output id="sportsTickerFontSizeValue">10.5px</output></span><input id="sportsTickerFontSize" type="range" min="8" max="18" step="0.5" value="10.5"></label>
        <label class="sports-ticker-dev-field"><span>HEADLINE LINES</span><select id="sportsTickerLines"><option value="1">1 LINE</option><option value="2">2 LINES</option></select></label>
        <label class="sports-ticker-dev-field"><span>SCROLL SPEED <output id="sportsTickerSpeedValue">20px/s</output></span><input id="sportsTickerSpeed" type="range" min="4" max="60" step="1" value="20"></label>
        <label class="sports-ticker-dev-field"><span>STORY SPACING <output id="sportsTickerGapValue">18px</output></span><input id="sportsTickerGap" type="range" min="0" max="48" step="1" value="18"></label>
      </div>
      <div class="sports-ticker-dev-actions">
        <button id="sportsTickerPauseBtn" class="settings-save-btn" type="button">PAUSE TICKER</button>
        <button id="sportsTickerResetTuningBtn" class="settings-save-btn" type="button">RESET TUNING</button>
        <button id="sportsTickerCopyTuningBtn" class="settings-save-btn" type="button">COPY TUNING VALUES</button>
        <button id="sportsTickerAiRefreshBtn" class="settings-save-btn" type="button">RUN SPORTS TICKER AI</button>
      </div>
      <code id="sportsTickerTuningSummary" class="sports-ticker-tuning-summary">height=40px | font=10.5px | lines=1 | speed=20px/s | gap=18px</code>
      <small class="sports-ticker-engine-status">ENGINE: GPU / COMPOSITOR • PER-FRAME JS: 0 • FORCED LAYOUT READS/FRAME: 0</small>
      <small id="sportsTickerAiRefreshStatus" class="sports-ticker-dev-status" aria-live="polite">Five clicks anywhere on the Sports Big Board logo enables every Dev utility. RUN SPORTS TICKER AI forces fresh source collection and a new OpenAI editorial pass.</small>`;
  }

  function ensureDevUtility(){
    const grid=document.querySelector('#settingsPane .settings-grid');if(!grid)return false;
    let card=grid.querySelector('.sports-ticker-dev-card');
    if(!card){
      card=document.createElement('div');card.className='settings-card sports-ticker-dev-card';card.innerHTML=utilityMarkup();
      const milestone=grid.querySelector('.milestone-launch-card');if(milestone)grid.insertBefore(card,milestone);else grid.appendChild(card);state.devUtilityInjections++;
    }
    bindDevControls();syncDevControls();return true;
  }

  function installUi(){
    if(!document.getElementById('sbbSportsTickerV528Style')){
      const style=document.createElement('style');style.id='sbbSportsTickerV528Style';style.textContent=`
        :root{--sbb-ticker-height:40px;--sbb-ticker-font-size:10.5px;--sbb-ticker-gap:18px}
        #scoreFilters>button[data-score-filter="NCAAF"]{align-self:center!important;display:inline-flex!important;align-items:center!important;justify-content:center!important;vertical-align:middle!important}
        .key-info-ribbon{height:var(--sbb-ticker-height)!important;min-height:var(--sbb-ticker-height)!important;align-items:stretch!important;contain:layout paint style!important}
        .key-info-ribbon .key-info-label{height:var(--sbb-ticker-height)!important;min-height:var(--sbb-ticker-height)!important;align-items:center!important}
        #keyInfoTrack{height:var(--sbb-ticker-height)!important;min-height:var(--sbb-ticker-height)!important;overflow:hidden!important;position:relative!important;contain:layout paint style!important;isolation:isolate}
        .sbb-sports-ticker-conveyor{display:flex!important;align-items:stretch!important;width:max-content!important;height:100%!important;transform:translate3d(0,0,0);will-change:transform;backface-visibility:hidden;-webkit-backface-visibility:hidden;}
        .sbb-sports-ticker-cycle,.sbb-sports-ticker-prefix{display:inline-flex!important;align-items:stretch!important;flex:0 0 auto!important;height:100%!important}
        .sbb-sports-ticker-prefix{pointer-events:none!important}
        .sbb-sports-ticker-conveyor .key-info-item{flex:0 0 auto!important;width:max-content!important;min-width:0!important;max-width:none!important;height:100%!important;min-height:100%!important;margin:0 var(--sbb-ticker-gap) 0 0!important;padding-left:11px!important;padding-right:11px!important;box-shadow:none!important;filter:none!important;transition:none!important;transform:none!important;backface-visibility:hidden;-webkit-backface-visibility:hidden;}
        .sbb-sports-ticker-conveyor .key-info-item:hover{box-shadow:none!important;transform:none!important}
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
        .sports-ticker-dev-card{display:block!important}
        .sports-ticker-dev-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:10px}
        .sports-ticker-dev-field{display:grid;gap:5px;padding:9px 10px;border:1px solid var(--line,#25303a);border-radius:9px;background:#0b1117}
        .sports-ticker-dev-field>span{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:9px;font-weight:850;letter-spacing:.045em;color:#c7d0d9}
        .sports-ticker-dev-field output{font-variant-numeric:tabular-nums;color:#7fc7ff}.sports-ticker-dev-field input[type="range"]{width:100%;accent-color:#2494ff}.sports-ticker-dev-field select{width:100%;padding:7px 8px;border-radius:7px}
        .sports-ticker-dev-actions{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}.sports-ticker-dev-actions .settings-save-btn{flex:1 1 170px}
        .sports-ticker-dev-status,.sports-ticker-engine-status{display:block;margin-top:8px;color:var(--muted,#8f9aa6);font-size:10px;line-height:1.4}.sports-ticker-engine-status{color:#7fc7ff}.sports-ticker-dev-status.good{color:#7bf1a9}.sports-ticker-dev-status.bad{color:#ff9b92}
        .sports-ticker-tuning-summary{display:block;margin-top:8px;padding:7px 8px;border-radius:7px;background:#090e13;border:1px solid #202a33;color:#aeb8c2;font:10px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace}
        @media(max-width:760px){.sports-ticker-dev-grid{grid-template-columns:1fr}.sbb-sports-ticker-conveyor .key-info-item strong{max-width:78vw!important}}
        @media(prefers-reduced-motion:reduce){#keyInfoTrack{overflow-x:auto!important}.sbb-sports-ticker-conveyor{will-change:auto!important;transform:none!important}}
      `;document.head.appendChild(style);
    }
    const label=document.querySelector('.key-info-label strong');if(label)label.textContent='SPORTS TICKER';
    applyTuningCss(false);ensureDevUtility();bindPauseControls();
  }

  function readCacheKey(key){
    try{const payload=JSON.parse(localStorage.getItem(key)||'null');if(!payload||!Array.isArray(payload.data)||Date.now()-Number(payload.savedAt||0)>CACHE_MAX_AGE)return null;return {savedAt:Number(payload.savedAt||0),source:clean(payload.source),data:dedupe(payload.data)};}catch(_){return null;}
  }
  function cachedSnapshot(){
    let payload=readCacheKey(CACHE_KEY);if(payload?.data?.length)return payload;
    for(const key of LEGACY_CACHE_KEYS){payload=readCacheKey(key);if(payload?.data?.length){try{localStorage.setItem(CACHE_KEY,JSON.stringify(payload));}catch(_){}return payload;}}
    return {savedAt:0,source:'',data:[]};
  }
  function saveRows(rows,source='',savedAt=Date.now()){rows=dedupe(rows);if(!rows.length)return;try{localStorage.setItem(CACHE_KEY,JSON.stringify({savedAt:Number(savedAt)||Date.now(),source,data:rows}));}catch(_){} }
  function setState(count,source=''){installUi();const label=document.getElementById('keyInfoState');if(label)label.textContent=count?`${count} update${count===1?'':'s'}`:'warming cached ticker';state.lastCount=count;state.source=source||state.source;}

  function makeItem(row,{duplicate=false}={}){
    const btn=document.createElement('button');btn.type='button';btn.className=`key-info-item ${categoryClass(row)}`;btn.dataset.sbbTickerKey=rowKey(row);
    if(duplicate){btn.tabIndex=-1;btn.setAttribute('aria-hidden','true');}
    const type=category(row).replace(/_/g,' '),source=clean(row?.sourceLabel||row?.source||'Sports Big Board'),league=clean(row?.league||'SPORT');
    btn.innerHTML='<span class="key-info-type"></span><strong></strong><small></small>';btn.querySelector('.key-info-type').textContent=type;btn.querySelector('strong').textContent=rowTitle(row);btn.querySelector('small').textContent=`${league} • ${source}`;btn.title=`${type} • ${league} • ${source}\n${rowTitle(row)}`;
    const href=clean(row?.externalUrl||row?.sourceUrl);if(href&&!duplicate)btn.addEventListener('click',()=>window.open(href,'_blank','noopener'));
    return btn;
  }

  function shouldPause(){return userPaused||hoverPaused||focusPaused||document.hidden||window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches===true;}
  function stopAnimation(){if(tickerAnimation){try{tickerAnimation.cancel();}catch(_){}tickerAnimation=null;}animationDuration=0;}
  function animationProgress(){if(!tickerAnimation||!animationDuration)return 0;const t=Number(tickerAnimation.currentTime||0);return ((t%animationDuration)+animationDuration)%animationDuration/animationDuration;}
  function syncAnimationPause(){if(!tickerAnimation)return;if(shouldPause()){try{tickerAnimation.pause();}catch(_){}}else{try{tickerAnimation.play();}catch(_){}}syncDevControls();}

  function startCompositorAnimation(progress=0){
    if(!conveyorGroup||cycleWidth<=0)return;
    stopAnimation();
    animationDuration=Math.max(1200,(cycleWidth/Math.max(1,tuning.speed))*1000);
    tickerAnimation=conveyorGroup.animate([
      {transform:'translate3d(0px,0,0)'},
      {transform:`translate3d(${-cycleWidth}px,0,0)`}
    ],{duration:animationDuration,iterations:Infinity,easing:'linear',fill:'both'});
    tickerAnimation.currentTime=Math.max(0,Math.min(0.999999,Number(progress)||0))*animationDuration;state.animationStarts++;syncAnimationPause();
  }

  function buildGeometryAndStart(progress=0){
    const track=document.getElementById('keyInfoTrack');if(!track||!cycleGroup||!conveyorGroup)return;
    // Geometry reads occur only here, after a render/tuning change. The animation
    // itself performs zero offset/client/computed-style reads per frame.
    let width=cycleGroup.getBoundingClientRect().width;
    const target=Math.max(900,track.clientWidth*1.35);
    if(width<target&&currentRows.length){
      const repeats=Math.min(48,Math.max(0,Math.ceil(target/Math.max(1,width))-1));
      const fragment=document.createDocumentFragment();for(let repeat=0;repeat<repeats;repeat++)for(const row of currentRows)fragment.appendChild(makeItem(row,{duplicate:true}));cycleGroup.appendChild(fragment);
      width=cycleGroup.getBoundingClientRect().width;
    }
    cycleWidth=Math.max(1,width);state.geometryBuilds++;
    const prefix=document.createElement('div');prefix.className='sbb-sports-ticker-prefix';prefix.setAttribute('aria-hidden','true');
    const primaryNodes=[...cycleGroup.children],dupCount=Math.min(DUPLICATE_PREFIX,primaryNodes.length);for(let i=0;i<dupCount;i++)prefix.appendChild(primaryNodes[i].cloneNode(true));conveyorGroup.appendChild(prefix);
    startCompositorAnimation(progress);
  }

  function renderOwned(rows,source='',{newRows=[],restart=true,progress=0}={}){
    rows=dedupe(rows);const track=document.getElementById('keyInfoTrack');
    if(!track){currentRows=rows;setState(rows.length,source);return rows;}
    if(!rows.length){stopAnimation();conveyorGroup=null;cycleGroup=null;cycleWidth=0;currentRows=[];track.innerHTML='<div class="key-info-empty">Sports Ticker is warming in the background.</div>';setState(0,source);return [];}
    currentRows=rows;currentSource=source||currentSource;stopAnimation();
    const group=document.createElement('div');group.className='sbb-sports-ticker-conveyor';group.dataset.sbbSportsTickerOwner=VERSION;
    const cycle=document.createElement('div');cycle.className='sbb-sports-ticker-cycle';for(const row of rows)cycle.appendChild(makeItem(row));group.appendChild(cycle);track.replaceChildren(group);
    conveyorGroup=group;cycleGroup=cycle;cycleWidth=0;state.renders++;state.newItemsPrepended+=newRows.length;setState(rows.length,source);
    requestAnimationFrame(()=>requestAnimationFrame(()=>buildGeometryAndStart(restart?0:progress)));return rows;
  }

  function tuningSummary(){return `height=${tuning.height}px | font=${tuning.fontSize}px | lines=${tuning.lines} | speed=${tuning.speed}px/s | gap=${tuning.gap}px`;}
  function syncDevControls(){
    const pairs=[['sportsTickerHeight',tuning.height,'sportsTickerHeightValue',`${tuning.height}px`],['sportsTickerFontSize',tuning.fontSize,'sportsTickerFontSizeValue',`${tuning.fontSize}px`],['sportsTickerSpeed',tuning.speed,'sportsTickerSpeedValue',`${tuning.speed}px/s`],['sportsTickerGap',tuning.gap,'sportsTickerGapValue',`${tuning.gap}px`]];
    for(const [id,value,outId,label] of pairs){const input=document.getElementById(id),out=document.getElementById(outId);if(input)input.value=String(value);if(out)out.textContent=label;}
    const lines=document.getElementById('sportsTickerLines');if(lines)lines.value=String(tuning.lines);const summary=document.getElementById('sportsTickerTuningSummary');if(summary)summary.textContent=tuningSummary();const pause=document.getElementById('sportsTickerPauseBtn');if(pause)pause.textContent=userPaused?'RESUME TICKER':'PAUSE TICKER';
  }
  function applyTuningCss(persist=true){
    tuning=normalizeTuning(tuning);const root=document.documentElement;root.style.setProperty('--sbb-ticker-height',`${tuning.height}px`);root.style.setProperty('--sbb-ticker-font-size',`${tuning.fontSize}px`);root.style.setProperty('--sbb-ticker-gap',`${tuning.gap}px`);root.dataset.sbbTickerLines=String(tuning.lines);if(persist)saveTuning();syncDevControls();try{window.dispatchEvent(new CustomEvent('sbb:sports-ticker-tuning',{detail:{...tuning}}));}catch(_){}return {...tuning};
  }
  function scheduleGeometryRebuild(){clearTimeout(geometryTimer);geometryTimer=setTimeout(()=>{if(currentRows.length)renderOwned(currentRows,currentSource,{restart:true});},110);}
  function setTuning(patch={}){
    const before={...tuning};tuning=normalizeTuning({...tuning,...patch});applyTuningCss(true);
    const geometryChanged=before.fontSize!==tuning.fontSize||before.lines!==tuning.lines||before.gap!==tuning.gap;
    if(geometryChanged)scheduleGeometryRebuild();else if(before.speed!==tuning.speed&&tickerAnimation){const p=animationProgress();startCompositorAnimation(p);}return {...tuning};
  }
  function resetTuning(){tuning={...DEFAULT_TUNING};userPaused=false;applyTuningCss(true);scheduleGeometryRebuild();return {...tuning};}

  function bindPauseControls(){
    const track=document.getElementById('keyInfoTrack');if(!track||track.dataset.sbbTickerPauseBound==='1')return;track.dataset.sbbTickerPauseBound='1';
    track.addEventListener('pointerenter',()=>{hoverPaused=true;syncAnimationPause();},{passive:true});track.addEventListener('pointerleave',()=>{hoverPaused=false;syncAnimationPause();},{passive:true});track.addEventListener('focusin',()=>{focusPaused=true;syncAnimationPause();});track.addEventListener('focusout',()=>{focusPaused=false;syncAnimationPause();});document.addEventListener('visibilitychange',syncAnimationPause);
  }

  function bindDevControls(){
    const bindings=[['sportsTickerHeight','input',v=>({height:Number(v)})],['sportsTickerFontSize','input',v=>({fontSize:Number(v)})],['sportsTickerLines','change',v=>({lines:Number(v)})],['sportsTickerSpeed','input',v=>({speed:Number(v)})],['sportsTickerGap','input',v=>({gap:Number(v)})]];
    for(const [id,event,patch] of bindings){const el=document.getElementById(id);if(!el||el.dataset.sbbTickerTuneBound==='1')continue;el.dataset.sbbTickerTuneBound='1';el.addEventListener(event,()=>setTuning(patch(el.value)));}
    const pause=document.getElementById('sportsTickerPauseBtn');if(pause&&pause.dataset.sbbTickerBound!=='1'){pause.dataset.sbbTickerBound='1';pause.addEventListener('click',()=>{userPaused=!userPaused;syncAnimationPause();});}
    const reset=document.getElementById('sportsTickerResetTuningBtn');if(reset&&reset.dataset.sbbTickerBound!=='1'){reset.dataset.sbbTickerBound='1';reset.addEventListener('click',resetTuning);}
    const copy=document.getElementById('sportsTickerCopyTuningBtn');if(copy&&copy.dataset.sbbTickerBound!=='1'){copy.dataset.sbbTickerBound='1';copy.addEventListener('click',async()=>{const text=tuningSummary();try{await navigator.clipboard.writeText(text);manualStatus(`Copied tuning: ${text}`,'good');}catch(_){manualStatus(text,'good');}});}
    bindDevButton();syncDevControls();
  }

  async function requestJson(path,{timeoutMs=2500,method='GET'}={}){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);try{const r=await fetch(api(path),{method,cache:'no-store',signal:controller.signal,headers:{Accept:'application/json'}});let payload={};try{payload=await r.json();}catch(_){}if(!r.ok)throw new Error(clean(payload?.error||payload?.message)||`HTTP ${r.status}`);return payload;}finally{clearTimeout(timer);}
  }

  function mergeEdition(incoming,{replace=false}={}){
    incoming=dedupe(incoming);if(replace||!currentRows.length){const oldKeys=new Set(currentRows.map(rowKey));return {rows:incoming,newRows:incoming.filter(row=>!oldKeys.has(rowKey(row))),changed:true};}
    const incomingBy=new Map(incoming.map(row=>[rowKey(row),row])),oldKeys=new Set(currentRows.map(rowKey));const newRows=incoming.filter(row=>!oldKeys.has(rowKey(row))),retained=currentRows.filter(row=>incomingBy.has(rowKey(row))).map(row=>incomingBy.get(rowKey(row))||row);const retainedKeys=new Set(retained.map(rowKey)),newKeys=new Set(newRows.map(rowKey));const remainder=incoming.filter(row=>!retainedKeys.has(rowKey(row))&&!newKeys.has(rowKey(row))),rows=dedupe([...newRows,...retained,...remainder]);return {rows,newRows,changed:currentRows.map(rowKey).join('\n')!==rows.map(rowKey).join('\n')};
  }

  async function refresh(force=false,{restart=false,replace=false}={}){
    if(inflight)return inflight;if(!force&&Date.now()-state.lastRefreshAt<60_000)return currentRows.slice();state.refreshes++;state.lastRefreshAt=Date.now();
    inflight=(async()=>{try{let payload;try{payload=await requestJson('/api/sports-ticker',{timeoutMs:2200});}catch(_){payload=await requestJson('/api/current-news',{timeoutMs:2200});}const incoming=dedupe(payload?.data||[]);if(!incoming.length)return currentRows.slice();const merged=mergeEdition(incoming,{replace});saveRows(merged.rows,payload?.source||'SPORTS_TICKER',Number(payload?.savedAt||0)*1000||Date.now());state.lastError='';if(!currentRows.length||merged.changed||restart){renderOwned(merged.rows,payload?.source||'SPORTS_TICKER',{newRows:merged.newRows,restart:true});}else{state.noChangeRefreshes++;currentRows=merged.rows;currentSource=payload?.source||currentSource;setState(merged.rows.length,currentSource);}return currentRows.slice();}catch(err){state.lastError=String(err?.message||err);return currentRows.slice();}finally{inflight=null;}})();return inflight;
  }

  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  function manualStatus(text,kind=''){ensureDevUtility();const el=document.getElementById('sportsTickerAiRefreshStatus');if(!el)return;el.textContent=text;el.classList.toggle('good',kind==='good');el.classList.toggle('bad',kind==='bad');}
  async function manualRefresh(){
    if(manualInflight)return manualInflight;ensureDevUtility();const btn=document.getElementById('sportsTickerAiRefreshBtn');state.manualRuns++;
    manualInflight=(async()=>{const oldLabel=btn?.textContent||'RUN SPORTS TICKER AI';if(btn){btn.disabled=true;btn.textContent='RUNNING SPORTS TICKER AI…';}manualStatus('Collecting fresh sports news…');try{const accepted=await requestJson('/api/sports-ticker/refresh',{method:'POST',timeoutMs:5000}),requestedAt=Number(accepted?.requestedAt||0);manualStatus('Fresh sources requested • OpenAI editorial pass running…');let finalStatus=null;for(let attempt=0;attempt<240;attempt++){await sleep(1250);const status=await requestJson('/api/sports-ticker/status',{timeoutMs:3000}),running=!!(status?.refreshing||status?.manualRunning),completed=Number(status?.manualCompletedAt||0);if(running){const retryAt=Number(status?.openaiRetryAt||0),retrySeconds=Math.max(0,Math.ceil(retryAt-Date.now()/1000));if(retrySeconds>0)manualStatus(`OpenAI rate limited • retrying in ${retrySeconds}s • previous ticker remains live`);else manualStatus(`OpenAI Sports Ticker running… ${Number(status?.manualOpenAIProcessed||0)||0} AI-reviewed • ${Number(status?.manualSourceCount||0)||'fresh'} source items`);continue;}if(status?.manualLastError)throw new Error(status.manualLastError);if(!requestedAt||completed>=requestedAt){finalStatus=status;break;}}if(!finalStatus)throw new Error('Sports Ticker AI refresh did not complete before the 5-minute operator timeout; the previous ticker remains live.');if(inflight){try{await inflight;}catch(_){}}await refresh(true,{restart:true,replace:true});const mode=clean(finalStatus?.source||currentSource||'OPENAI_SPORTS_TICKER');manualStatus(`Updated • ${currentRows.length} stories • ${mode}`,'good');return currentRows.slice();}catch(err){state.manualErrors++;state.lastError=String(err?.message||err);manualStatus(`Refresh failed: ${state.lastError}`,'bad');throw err;}finally{if(btn){btn.disabled=false;btn.textContent=oldLabel;}manualInflight=null;}})();return manualInflight;
  }
  function bindDevButton(){const btn=document.getElementById('sportsTickerAiRefreshBtn');if(!btn||btn.dataset.sbbTickerBound==='1')return;btn.dataset.sbbTickerBound='1';btn.addEventListener('click',()=>{void manualRefresh().catch(()=>{});});}

  function legacyNoop(kind){if(kind==='refresh')state.legacyRefreshNoops++;else state.dateTriggeredNoops++;return currentRows.slice();}
  function isolateLegacyLane(){
    const renderNoop=()=>legacyNoop('render'),refreshNoop=()=>Promise.resolve(legacyNoop('refresh'));renderNoop.__sbbSportsTickerDateNoop=true;refreshNoop.__sbbSportsTickerDateNoop=true;
    try{window.renderActiveSportKeyInformation=renderNoop;}catch(_){}try{renderActiveSportKeyInformation=renderNoop;}catch(_){}try{window.renderKeyInformation=renderNoop;}catch(_){}try{renderKeyInformation=renderNoop;}catch(_){}try{window.refreshKeyInformation=refreshNoop;}catch(_){}try{refreshKeyInformation=refreshNoop;}catch(_){}
    try{if(typeof keyInfoStartupRetryTimer!=='undefined'&&keyInfoStartupRetryTimer){clearTimeout(keyInfoStartupRetryTimer);keyInfoStartupRetryTimer=null;}}catch(_){}
  }

  function install(){
    installUi();const local=cachedSnapshot();if(local.data.length){state.cachePaints++;currentRows=local.data;currentSource=local.source||'BROWSER_CACHE';renderOwned(currentRows,currentSource,{restart:true});}else setState(0,'');
    isolateLegacyLane();clearInterval(refreshTimer);refreshTimer=setInterval(()=>{if(!document.hidden)void refresh(false);},REFRESH_MS);window.addEventListener('focus',()=>{if(Date.now()-state.lastRefreshAt>REFRESH_MS)void refresh(false);},{passive:true});window.addEventListener('sbb:dev-mode',ev=>{if(ev?.detail?.enabled)ensureDevUtility();});
    let guards=0;const ownership=setInterval(()=>{guards++;isolateLegacyLane();ensureDevUtility();try{window.SBB_DATE_TRANSITIONS?.install?.();}catch(_){}if(guards>=16)clearInterval(ownership);},500);
    state.installed=true;void refresh(false);return true;
  }

  const apiObject=Object.freeze({
    version:VERSION,name:'SPORTS_TICKER',refresh,manualRefresh,setTuning,resetTuning,ensureDevUtility,tuning:()=>({...tuning}),pause:()=>{userPaused=true;syncAnimationPause();},resume:()=>{userPaused=false;syncAnimationPause();},
    render:rows=>{const merged=mergeEdition(rows);return renderOwned(merged.rows,'API',{newRows:merged.newRows,restart:true});},rows:()=>currentRows.slice(),snapshot:()=>({...state,currentCount:currentRows.length,currentSource,paused:shouldPause(),tuning:{...tuning},cycleWidth,animationDuration})
  });
  window.SBB_KEY_INFO_CURRENT=apiObject;window.SBB_SPORTS_TICKER=apiObject;install();
})();

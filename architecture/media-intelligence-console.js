/* Sports Big Board v4.5.2 — Media Intelligence operator visibility.
   Read-only database visibility plus explicit priority scan of the current clip.
   This module never owns playback/audio and never scans the DOM for media. */
(() => {
  'use strict';
  if(window.SBB_MEDIA_INTELLIGENCE_CONSOLE) return;
  const $=id=>document.getElementById(id);
  let latest=null,currentDb=null,pollTimer=0,scanPollTimer=0;
  const clean=(v,n=1000)=>String(v??'').trim().slice(0,n);
  const esc=s=>clean(s,500).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pct=v=>Number.isFinite(Number(v))?`${Math.round(Number(v)*100)}%`:'—';
  const age=epoch=>{const n=Number(epoch||0);if(!n)return '—';const sec=Math.max(0,Date.now()/1000-n);return sec<60?`${Math.round(sec)}s ago`:sec<3600?`${Math.round(sec/60)}m ago`:`${Math.round(sec/3600)}h ago`;};
  async function request(path,options={}){const r=await fetch(path,{cache:'no-store',...options});const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data?.message||data?.error||`HTTP ${r.status}`);return data;}
  function browserDecision(){return window.SBB_MEDIA_INTELLIGENCE?.snapshot?.()?.currentDecision||{};}
  function currentKey(){return clean(window.SBB_MEDIA_INTELLIGENCE?.snapshot?.()?.currentMediaKey||window.SBB_PLAYBACK_SESSION?.snapshot?.()?.mediaKey||'',2000);}
  function normalizeDb(row){if(!row)return null;return {key:row.asset_key||'',status:row.music_status||'UNKNOWN',confidence:Number(row.music_confidence||0),ratio:Number(row.music_ratio||0),scanVersion:Number(row.scan_version||0),scannedAt:Number(row.scanned_at||0),title:row.title||row.asset?.title||'',provider:row.provider||'',date:row.date||'',league:row.league||'',priority:Number(row.scan_priority||0),error:row.last_error||'',asset:row.asset||{}};}
  function registerDb(row){
    if(!row||!window.SBB_MEDIA_INTELLIGENCE?.register)return;
    const data=normalizeDb(row);
    window.SBB_MEDIA_INTELLIGENCE.register({...row.asset,mediaKey:row.asset_key,assetKey:row.asset_key,title:row.title||row.asset?.title||'',musicStatus:data.status,musicConfidence:data.confidence,musicRatio:data.ratio,musicConflict:row.music_conflict!==0,musicScanVersion:data.scanVersion,musicScannedAt:data.scannedAt});
  }
  async function refreshCurrent(){
    const key=currentKey();currentDb=null;
    if(!key)return null;
    try{const data=await request(`/api/media-intelligence/asset?assetKey=${encodeURIComponent(key)}`);currentDb=data.asset||null;if(currentDb)registerDb(currentDb);return currentDb;}catch(_){return null;}
  }
  async function refresh(){
    const status=$('mediaIntelligenceConsoleStatus');if(status)status.textContent='REFRESHING';
    try{latest=await request('/api/media-intelligence/status');await refreshCurrent();render();return latest;}
    catch(err){if(status)status.textContent='ERROR';const body=$('mediaIntelligenceCurrentDetail');if(body)body.textContent=String(err);return null;}
  }
  async function scanCurrent(){
    const key=currentKey(),btn=$('mediaIntelligenceScanCurrent');if(!key)return;
    if(btn){btn.disabled=true;btn.textContent='QUEUING…';}
    try{
      await request('/api/media-intelligence/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({assetKey:key,current:true,reason:'milestone-console-current'})});
      if(btn)btn.textContent='QUEUED';
      clearInterval(scanPollTimer);let tries=0;const before=normalizeDb(currentDb)?.scannedAt||0;
      scanPollTimer=setInterval(async()=>{tries++;await refresh();const now=normalizeDb(currentDb);if(now&&now.scannedAt>before&&now.scanVersion>0){clearInterval(scanPollTimer);scanPollTimer=0;if(btn){btn.disabled=false;btn.textContent='SCAN CURRENT';}}else if(tries>=45){clearInterval(scanPollTimer);scanPollTimer=0;if(btn){btn.disabled=false;btn.textContent='SCAN CURRENT';}}},2000);
    }catch(err){if(btn){btn.disabled=false;btn.textContent='SCAN CURRENT';}alert(`Media Intelligence scan request failed: ${err}`);}
  }
  function listHtml(rows,status){
    if(!rows?.length)return '<div class="mi-empty">None classified yet</div>';
    return rows.slice(0,5).map(row=>{const d=normalizeDb(row);return `<div class="mi-known-row"><b>${esc(pct(d.confidence))}</b><span>${esc(d.league||d.provider||'MEDIA')} • ${esc(d.title||d.key)}</span><small>${esc(d.date||'')} ${esc(d.key)}</small></div>`;}).join('');
  }
  function render(){
    if(!latest)return;const snap=latest.mediaIntelligence||{},worker=latest.worker||{},decision=browserDecision(),db=normalizeDb(currentDb),status=$('mediaIntelligenceConsoleStatus');
    if(status){status.textContent=worker.alive?(worker.activeAsset?'ANALYZING':'ALIVE'):'OFFLINE';status.dataset.state=worker.alive?'pass':'fail';}
    const stats=$('mediaIntelligenceConsoleStats');if(stats)stats.innerHTML=`
      <div><span>TOTAL</span><strong>${Number(snap.total||0).toLocaleString()}</strong></div>
      <div><span>SCANNED</span><strong>${Number(snap.scanned||0).toLocaleString()}</strong></div>
      <div><span>PENDING</span><strong>${Number(snap.pending||0).toLocaleString()}</strong></div>
      <div><span>HAS MUSIC</span><strong>${Number(snap.hasMusic||0).toLocaleString()}</strong></div>
      <div><span>NO MUSIC</span><strong>${Number(snap.noMusic||0).toLocaleString()}</strong></div>
      <div><span>UNKNOWN</span><strong>${Number(snap.unknown||0).toLocaleString()}</strong></div>
      <div><span>FAILED</span><strong>${Number(snap.failed||0).toLocaleString()}</strong></div>
      <div><span>LAST PROGRESS</span><strong>${age(worker.lastProgress)}</strong></div>`;
    const detail=$('mediaIntelligenceCurrentDetail');if(detail){
      const statusText=db?.status||decision.status||'UNKNOWN', scanned=!!(db&&db.scanVersion>0&&db.scannedAt>0);
      detail.innerHTML=`<div class="mi-current-title">${esc(db?.title||decision.title||$('currentTitle')?.textContent||'Current clip')}</div>
      <div class="mi-current-grid">
        <span>DATABASE STATUS</span><b>${esc(statusText)}${scanned?'':' / NOT SCANNED'}</b>
        <span>CONFIDENCE</span><b>${scanned?pct(db.confidence):'—'}</b>
        <span>MUSIC RATIO</span><b>${scanned?pct(db.ratio):'—'}</b>
        <span>SCAN VERSION</span><b>${db?.scanVersion||0}</b>
        <span>SCANNED</span><b>${db?.scannedAt?age(db.scannedAt):'—'}</b>
        <span>SITE MUSIC</span><b>${statusText==='NO_MUSIC'?'ALLOWED':'MUTED / YIELD'}</b>
        <span>MEDIA KEY</span><code>${esc(currentKey()||'—')}</code>
      </div>${db?.error?`<div class="mi-error">${esc(db.error)}</div>`:''}`;
    }
    const active=$('mediaIntelligenceWorkerDetail');if(active)active.textContent=worker.activeAsset?`CURRENT: ${worker.activeTitle||worker.activeAsset}`:(worker.lastError?`LAST ERROR: ${worker.lastError}`:'Crawler waiting for next eligible asset');
    const sets=latest.validationSet||{};const has=$('mediaIntelligenceKnownMusic'),no=$('mediaIntelligenceKnownNoMusic');if(has)has.innerHTML=listHtml(sets.hasMusic,'HAS_MUSIC');if(no)no.innerHTML=listHtml(sets.noMusic,'NO_MUSIC');
  }
  function install(){
    const anchor=$('milestoneConsoleProblems');if(!anchor||$('mediaIntelligenceConsolePanel'))return;
    const style=document.createElement('style');style.textContent=`
      .mi-console{margin:12px 14px;border:1px solid rgba(255,255,255,.16);border-radius:10px;background:rgba(6,12,20,.88);padding:12px;color:#eaf2ff;font:12px/1.35 system-ui,sans-serif}.mi-console header{display:flex;align-items:center;gap:10px;margin-bottom:10px}.mi-console header strong{font-size:13px;letter-spacing:.06em}.mi-console header b{padding:3px 7px;border-radius:999px;background:#17324a}.mi-console header .spacer{flex:1}.mi-console button{background:#183650;color:#fff;border:1px solid #41647d;border-radius:5px;padding:6px 9px;cursor:pointer}.mi-console button:disabled{opacity:.55}.mi-stats{display:grid;grid-template-columns:repeat(4,minmax(90px,1fr));gap:6px}.mi-stats div{background:rgba(255,255,255,.05);padding:7px;border-radius:6px}.mi-stats span{display:block;color:#8da4b8;font-size:9px}.mi-stats strong{font-size:14px}.mi-current{margin-top:10px;padding:9px;background:rgba(255,255,255,.04);border-radius:7px}.mi-current-title{font-weight:700;margin-bottom:7px}.mi-current-grid{display:grid;grid-template-columns:110px 1fr;gap:4px 8px}.mi-current-grid span{color:#8da4b8}.mi-current-grid code{word-break:break-all;font-size:10px}.mi-known{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}.mi-known section{background:rgba(255,255,255,.04);border-radius:7px;padding:8px}.mi-known h4{margin:0 0 6px;font-size:11px}.mi-known-row{display:grid;grid-template-columns:44px 1fr;gap:2px 7px;padding:4px 0;border-top:1px solid rgba(255,255,255,.06)}.mi-known-row:first-of-type{border-top:0}.mi-known-row small{grid-column:2;color:#7890a5;word-break:break-all}.mi-worker{margin-top:7px;color:#9bb1c3}.mi-error{margin-top:6px;color:#ff9e9e}@media(max-width:800px){.mi-stats{grid-template-columns:repeat(2,1fr)}.mi-known{grid-template-columns:1fr}}`;
    document.head.appendChild(style);
    const panel=document.createElement('section');panel.id='mediaIntelligenceConsolePanel';panel.className='mi-console';panel.innerHTML=`<header><strong>MEDIA INTELLIGENCE</strong><b id="mediaIntelligenceConsoleStatus">CONNECTING</b><span class="spacer"></span><button id="mediaIntelligenceScanCurrent" type="button">SCAN CURRENT</button><button id="mediaIntelligenceRefresh" type="button">REFRESH</button></header><div id="mediaIntelligenceConsoleStats" class="mi-stats"></div><div id="mediaIntelligenceCurrentDetail" class="mi-current">Waiting for current clip…</div><div id="mediaIntelligenceWorkerDetail" class="mi-worker"></div><div class="mi-known"><section><h4>KNOWN HAS MUSIC</h4><div id="mediaIntelligenceKnownMusic"></div></section><section><h4>KNOWN NO MUSIC</h4><div id="mediaIntelligenceKnownNoMusic"></div></section></div>`;
    anchor.insertAdjacentElement('afterend',panel);
    $('mediaIntelligenceRefresh')?.addEventListener('click',refresh);$('mediaIntelligenceScanCurrent')?.addEventListener('click',scanCurrent);
    refresh();clearInterval(pollTimer);pollTimer=setInterval(()=>{if(!$('milestoneConsoleModal')?.classList?.contains('hidden'))refresh();},5000);
    window.SBB_PLAYBACK_SESSION?.subscribe?.(()=>{if(!$('milestoneConsoleModal')?.classList?.contains('hidden'))setTimeout(refreshCurrent,300);});
  }
  const consoleApi=Object.freeze({version:'1.0',refresh,scanCurrent,get snapshot(){return latest;},get current(){return normalizeDb(currentDb);}});window.SBB_MEDIA_INTELLIGENCE_CONSOLE=consoleApi;
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
})();

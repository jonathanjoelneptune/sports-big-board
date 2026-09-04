(()=>{
'use strict';
const VERSION='5.5.0';
const GENERATION='R11-PARALLEL';
const $=id=>document.getElementById(id);
const API=((window.SBB_CONFIG&&window.SBB_CONFIG.apiBase)||location.origin).replace(/\/$/,'')+'/api/media-audit';
const state={offset:0,limit:100,total:0,rows:[],expanded:new Set(),status:null,busy:false,pollTimer:null,lastInventoryAt:0};

function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmtDateTime(ts){if(!ts)return '—';try{return new Date(Number(ts)*1000).toLocaleString();}catch(_){return '—';}}
function fmtNum(v){return new Intl.NumberFormat().format(Number(v||0));}
function healthClass(v){return String(v||'UNTESTED').toUpperCase();}
async function fetchJson(url,opts={}){const r=await fetch(url,{cache:'no-store',...opts,headers:{'Content-Type':'application/json',...(opts.headers||{})}});let d={};try{d=await r.json();}catch(_){}if(!r.ok||d.ok===false)throw new Error(d.message||d.error||`HTTP ${r.status}`);return d;}
async function post(path,body={}){return fetchJson(API+path,{method:'POST',body:JSON.stringify(body)});}
function log(msg,cls=''){const el=$('probeLog');if(!el)return;const div=document.createElement('div');if(cls)div.className=cls;div.textContent=`${new Date().toLocaleTimeString()}  ${msg}`;el.prepend(div);while(el.children.length>100)el.lastChild.remove();}
function setText(id,v){const el=$(id);if(el)el.textContent=v;}
function buttonState(run){const s=String(run&&run.state||'IDLE');$('auditPause').disabled=s!=='RUNNING';$('auditResume').disabled=s!=='PAUSED';$('auditStop').disabled=!['RUNNING','PAUSED'].includes(s);}

function renderSummary(status){
  const s=status.summary||{},h=s.health||{},run=status.run||null,worker=status.worker||{};
  setText('metricGames',fmtNum(s.games));setText('metricGamesSub',`${fmtNum(s.certifiedGames)} canonically certified`);
  setText('metricAudited',fmtNum(s.certifiedGames));setText('metricAuditedSub',`${fmtNum(s.staleGames)} stale >30d`);
  setText('metricHealthy',fmtNum(h.HEALTHY));setText('metricDegraded',fmtNum(h.DEGRADED));setText('metricUnplayable',fmtNum(h.UNPLAYABLE));setText('metricNoMedia',fmtNum(h.NO_MEDIA));
  setText('metricAssets',fmtNum((s.playedAssets||0)+(s.failedAssets||0)));setText('metricAssetsSub',`${fmtNum(s.playedAssets)} played • ${fmtNum(s.failedAssets)} failed`);
  setText('metricRun',run?String(run.state||'IDLE'):'IDLE');
  setText('metricRunSub',run?`Run #${run.id} • ${run.processed_games||0}/${run.total_games||0} • ${status.workerCount||1} lanes`:(worker.alive?`${status.workerCount||1} worker lane${(status.workerCount||1)===1?'':'s'} online`:'Worker offline'));
  const pct=run?Number(run.progressPct||0):0;$('progressFill').style.width=Math.max(0,Math.min(100,pct))+'%';
  setText('progressLabel',run?`${String(run.state)} • ${pct.toFixed(1)}%`:'Idle');
  setText('progressDetail',run?(run.current_event_key?`#${run.current_ordinal} • ${run.current_event_key} • ${run.current_phase||''}`:`${run.processed_games||0}/${run.total_games||0} games`):'No canonical audit run active.');
  buttonState(run);
  setText('probeGame',worker.current&&worker.current.game||'Waiting');setText('probeState',worker.alive?`${status.workerCount||1} SERVER WORKERS`:'OFFLINE');
  $('probeState').className='state '+(worker.alive?'pass':'fail');
  renderDiagnostics(status);
  if(status.newestEligibleDate&&!$('auditStartDate').value)$('auditStartDate').value=status.newestEligibleDate;
}

function fmtAge(seconds){const s=Math.max(0,Number(seconds||0));if(s<60)return `${s.toFixed(1)}s`;const m=Math.floor(s/60),r=Math.round(s%60);return `${m}m ${r}s`;}
function renderDiagnostics(status){
  const worker=status.worker||{},d=worker.diagnostics||{},cur=worker.current||{},recovery=worker.recoveredExceptionFailures||{};
  const storageError=String(status.storageReadError||'');
  const dbLocked=String(d.dbState||'').toUpperCase()==='LOCKED'||!!storageError;
  setText('diagRun',d.runId?`#${d.runId}`:(status.run?`#${status.run.id}`:'—'));
  setText('diagOrdinal',d.ordinal?`#${d.ordinal}`:(cur.ordinal?`#${cur.ordinal}`:'—'));
  setText('diagEvent',d.eventKey||cur.event||'—');
  setText('diagPhase',d.phase||cur.phase||'IDLE');
  setText('diagPhaseAge',fmtAge(d.phaseAgeSeconds));
  setText('diagProgressAge',fmtAge(d.idleSinceProgressSeconds));
  setText('diagDbState',dbLocked?'LOCKED / RETRYING':'READY');
  $('diagDbState').className='diag-value '+(dbLocked?'bad':'ok');
  setText('diagDbOp',d.dbOperation||'—');
  setText('diagDbRetries',fmtNum(d.dbLockRetries||0));
  setText('diagParity',`${fmtNum(d.dbAssetCount||0)} DB • ${fmtNum(d.productionMediaCount||0)} production media • ${fmtNum(d.productionPlayableCount||0)} playable`);
  setText('diagProductionState',d.productionPlanState||'—');
  const counts=d.candidateCounts||{};
  setText('diagCandidates',`G ${counts.green||0} • P ${counts.extended||0} • Gold ${counts.gold||0} • B ${counts.blue||0}`);
  setText('diagCandidate',d.candidateTier?`${d.candidateTier} ${d.candidateIndex||0}/${d.candidateCount||0}`:'—');
  setText('diagAsset',d.assetTitle||d.assetKey||'—');
  setText('diagAssetKey',d.assetKey||'—');
  setText('diagProvider',d.assetProvider||'—');
  setText('diagProbe',d.probeAttempt?`${d.probeAttempt}/${d.probeMaxAttempts||2}`:'—');
  setText('diagProbeResult',d.lastProbeResult||worker.lastError||status.browserError||'—');
  setText('diagDiscovery',d.discoveryPass?`${d.discoveryPass}/${d.discoveryMaxPasses||0} • ${d.discoveryResult||'working'}`:'—');
  const waiting=d.waitingReason||storageError||'No wait condition';
  setText('diagWaiting',waiting);
  $('diagWaiting').className='diagnostic-wait '+((d.waitingReason||storageError)?'active':'');
  setText('diagBrowser',status.browser||'Chromium not started yet');
  setText('diagOrigin',status.probeUrl||'—');
  setText('diagRecovered',recovery.requeued?`${recovery.requeued} prior exception failure${recovery.requeued===1?'':'s'} requeued`:'None');
  const lanes=$('diagWorkers');
  if(lanes){
    const workers=Array.isArray(status.workers)?status.workers:[];
    lanes.innerHTML=workers.map(w=>{const wd=w.diagnostics||{},wc=w.current||{},phase=wd.phase||wc.phase||'IDLE',game=wc.game||wd.game||'Waiting',ord=wc.ordinal||wd.ordinal||'';return `<div class="worker-lane ${w.alive?'live':'dead'}"><strong>LANE ${esc(w.lane||wd.workerLane||'?')}</strong><span>${ord?`#${esc(ord)} • `:''}${esc(game)}</span><small>${esc(phase)}${wd.waitingReason?` • ${esc(wd.waitingReason)}`:''}</small></div>`}).join('')||'<div class="worker-lane idle">No server workers reported.</div>';
  }
  const trace=$('diagTrace');
  if(trace){
    const rows=(d.trace||[]).slice().reverse();
    trace.innerHTML=rows.map(r=>`<div class="${esc(String(r.level||'').toLowerCase())}"><time>${esc(fmtDateTime(r.at))}</time><span>${esc(r.message||'')}</span>${r.details?`<small>${esc(JSON.stringify(r.details))}</small>`:''}</div>`).join('')||'<div class="empty-trace">No server trace yet.</div>';
  }
}

function tierChip(has,label){return `<span class="tier-chip ${has?'pass':'none'}">${has?'1/1':'—'}</span>`;}
function healthBadge(h){return `<span class="health ${esc(healthClass(h))}">${esc(String(h||'UNTESTED').replaceAll('_',' '))}</span>`;}
function renderRows(){
  const body=$('gameRows');if(!state.rows.length){body.innerHTML='<tr><td colspan="10" class="empty">No games match these filters.</td></tr>';return;}
  const html=[];
  for(const row of state.rows){const expanded=state.expanded.has(row.canonicalEventKey);html.push(`<tr class="game-row" data-event="${esc(row.canonicalEventKey)}"><td><button class="expand" data-expand="${esc(row.canonicalEventKey)}">${expanded?'−':'+'}</button></td><td>${esc(row.date)}</td><td><span class="league">${esc(row.league)}</span></td><td><span class="game-name">${esc(row.game)}</span><span class="muted">${row.queueOrdinal?`QUEUE #${esc(row.queueOrdinal)} • ${esc(row.queueState||'')} ${esc(row.queuePhase||'')}`:esc(row.eventId)}</span></td><td>${tierChip(row.green,'Green')}</td><td>${tierChip(row.purple,'Purple')}</td><td>${tierChip(row.gold,'Gold')}</td><td><span class="tier-chip ${row.blueCount?'pass':'none'}">${row.blueCount?esc(row.blueCount):'—'}</span></td><td>${healthBadge(row.health)}</td><td>${row.certifiedAt?esc(fmtDateTime(row.certifiedAt)):'—'}</td></tr>`);if(expanded)html.push(`<tr class="asset-row" id="detail-${cssSafe(row.canonicalEventKey)}"><td></td><td colspan="9"><div class="asset-grid"><div class="empty">Loading canonical package…</div></div></td></tr>`)}body.innerHTML=html.join('');
  body.querySelectorAll('[data-expand]').forEach(btn=>btn.addEventListener('click',()=>toggleDetail(btn.dataset.expand)));
  for(const key of state.expanded)loadDetail(key).catch(e=>log(`Detail ${key}: ${e.message}`,'bad'));
}
function cssSafe(v){return String(v).replace(/[^A-Za-z0-9_-]/g,'_');}
async function toggleDetail(key){if(state.expanded.has(key))state.expanded.delete(key);else state.expanded.add(key);renderRows();}
async function loadDetail(key){const holder=document.querySelector(`#detail-${cssSafe(key)} .asset-grid`);if(!holder)return;const d=await fetchJson(API+'/event?event='+encodeURIComponent(key));const pkg=d.package||{};const canonical=new Set([pkg.gold_asset_key,pkg.green_asset_key,pkg.purple_asset_key,...safeJsonArray(pkg.blue_asset_keys_json)].filter(Boolean));const cards=(d.assets||[]).map(a=>{const c=canonical.has(a.assetKey);const rs=String(a.runtimeState||'UNKNOWN').toUpperCase();const klass=rs==='PLAYED'?'pass':rs==='FAILED'?'fail':'unknown';return `<div class="asset-card"><div><strong>${esc(String(a.tier||'').toUpperCase())}</strong><small>${c?'CANONICAL':'NON-CANONICAL'}</small></div><div><strong>${esc(a.title||a.assetKey)}</strong><small>${esc(a.url||'')}</small></div><div><strong>${esc(a.provider||'—')}</strong><small>${esc(a.associationState||'')}</small></div><div class="asset-state ${klass}">${esc(rs)}<small>${esc(a.runtimeFailureReason||a.associationMethod||'')}</small></div></div>`}).join('');holder.innerHTML=cards||'<div class="empty">No GAME media associated with this event.</div>';}
function safeJsonArray(v){if(Array.isArray(v))return v;try{const a=JSON.parse(v||'[]');return Array.isArray(a)?a:[]}catch(_){return[]}}

async function refreshInventory(){
  state.lastInventoryAt=Date.now();
  const q=new URLSearchParams({limit:String(state.limit),offset:String(state.offset)});const lg=$('filterLeague').value,h=$('filterHealth').value,s=$('filterSearch').value.trim();if(lg)q.set('league',lg);if(h)q.set('health',h);if(s)q.set('search',s);const d=await fetchJson(API+'/inventory?'+q);state.rows=d.rows||[];state.total=Number(d.total||0);setText('tableCount',`${fmtNum(state.total)} games`);const first=state.total?state.offset+1:0,last=Math.min(state.total,state.offset+state.limit);setText('pageLabel',`${first}–${last} of ${state.total}`);$('pagePrev').disabled=state.offset<=0;$('pageNext').disabled=state.offset+state.limit>=state.total;populateLeagues();renderRows();}
function populateLeagues(){const sel=$('filterLeague'),current=sel.value;const leagues=[...new Set(state.rows.map(r=>r.league).filter(Boolean))].sort();for(const lg of leagues)if(![...sel.options].some(o=>o.value===lg)){const o=document.createElement('option');o.value=lg;o.textContent=lg;sel.appendChild(o)}sel.value=current;}
async function refreshStatus(){try{const d=await fetchJson(API+'/status');state.status=d;renderSummary(d);if(!state.busy&&(Date.now()-state.lastInventoryAt>12000||!state.rows.length))await refreshInventory();}catch(e){setText('metricRun','OFFLINE');setText('metricRunSub',e.message);$('probeState').textContent='OFFLINE';$('probeState').className='state fail';}}
async function command(path,body,label){if(state.busy)return;state.busy=true;try{const d=await post(path,body);log(label,'ok');if(d.run)renderSummary({...state.status,run:d.run});await refreshStatus();}catch(e){log(`${label}: ${e.message}`,'bad');alert(e.message);}finally{state.busy=false;}}
async function resetAudit(){if(!confirm('RESET AUDIT will stop the current server worker, clear the audit queue/progress, and keep existing canonical certifications.\n\nContinue?'))return;state.offset=0;await command('/reset',{recertify:false},'Audit run reset');}
async function fullRecertify(){if(!confirm('FULL RECERTIFY will clear canonical package decisions and restore audit-managed links to ASSIGNED. Source media/history is preserved. Continue?'))return;await command('/reset',{recertify:true},'Canonical certifications reset');}
async function download(path,name){try{const r=await fetch(API+path,{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);const b=await r.blob(),u=URL.createObjectURL(b),a=document.createElement('a');a.href=u;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),1000);}catch(e){alert(e.message)}}
function bind(){
  $('auditEverything').onclick=()=>command('/start',{mode:'ALL',startDate:$('auditStartDate').value},'Canonical audit started');
  $('auditFailed').onclick=()=>command('/start',{mode:'FAILED',startDate:$('auditStartDate').value},'Failed-game retest started');
  $('auditStale').onclick=()=>command('/start',{mode:'STALE',startDate:$('auditStartDate').value},'Stale-game audit started');
  $('auditPause').onclick=()=>command('/pause',{},'Audit paused');$('auditResume').onclick=()=>command('/resume',{},'Audit resumed');$('auditStop').onclick=()=>command('/stop',{},'Audit stopped');$('auditReset').onclick=resetAudit;
  const full=document.getElementById('auditFullReset');if(full)full.onclick=fullRecertify;
  $('refreshInventory').onclick=()=>{state.offset=0;refreshStatus()};$('exportManifest').onclick=()=>download('/rehydration.json','sports-big-board-media-rehydration.json');$('exportCsv').onclick=()=>download('/failures.csv','sports-big-board-media-audit-failures.csv');
  $('pagePrev').onclick=()=>{state.offset=Math.max(0,state.offset-state.limit);refreshInventory()};$('pageNext').onclick=()=>{state.offset+=state.limit;refreshInventory()};$('pageSize').onchange=()=>{state.limit=Number($('pageSize').value||100);state.offset=0;refreshInventory()};
  for(const id of ['filterLeague','filterHealth'])$(id).onchange=()=>{state.offset=0;refreshInventory()};let timer;$('filterSearch').oninput=()=>{clearTimeout(timer);timer=setTimeout(()=>{state.offset=0;refreshInventory()},250)};
}
async function init(){bind();state.limit=Number($('pageSize').value||100);setText('probePlaceholder','This page no longer plays audit media. Playback certification runs in controlled headless Chrome on the Sports Big Board backend.');await refreshStatus();state.pollTimer=setInterval(refreshStatus,3000);}
window.addEventListener('beforeunload',()=>{if(state.pollTimer)clearInterval(state.pollTimer)});init().catch(e=>{console.error(e);log(e.message,'bad')});
})();

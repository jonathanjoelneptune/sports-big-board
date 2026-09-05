(()=>{
'use strict';
const VERSION='5.5.0';
const GENERATION='R16-AUDIT-REPAIR-SEPARATION';
const $=id=>document.getElementById(id);
const API=((window.SBB_CONFIG&&window.SBB_CONFIG.apiBase)||location.origin).replace(/\/$/,'')+'/api/media-audit';
const state={offset:0,limit:100,total:0,rows:[],expanded:new Set(),status:null,busy:false,pollTimer:null,lastInventoryAt:0,lastInventoryOkAt:0,inventoryError:'',inventoryBusy:false,statusBusy:false,statusFailures:0,lastStatusOkAt:0,lastStatusAttemptAt:0};

function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmtDateTime(ts){if(!ts)return '—';try{return new Date(Number(ts)*1000).toLocaleString();}catch(_){return '—';}}
function fmtNum(v){return new Intl.NumberFormat().format(Number(v||0));}
function healthClass(v){return String(v||'UNTESTED').toUpperCase();}
async function fetchJson(url,opts={}){const {timeoutMs=10000,...fetchOpts}=opts,controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);try{const r=await fetch(url,{cache:'no-store',...fetchOpts,signal:controller.signal,headers:{'Content-Type':'application/json',...(fetchOpts.headers||{})}});let d={};try{d=await r.json();}catch(_){}if(!r.ok||d.ok===false)throw new Error(d.message||d.error||`HTTP ${r.status}`);return d;}catch(e){if(e&&e.name==='AbortError')throw new Error(`Request timed out after ${Math.round(timeoutMs/1000)}s`);throw e;}finally{clearTimeout(timer);}}
async function post(path,body={}){return fetchJson(API+path,{method:'POST',body:JSON.stringify(body),timeoutMs:20000});}
function log(msg,cls=''){const el=$('probeLog');if(!el)return;const div=document.createElement('div');if(cls)div.className=cls;div.textContent=`${new Date().toLocaleTimeString()}  ${msg}`;el.prepend(div);while(el.children.length>100)el.lastChild.remove();}
function setText(id,v){const el=$(id);if(el)el.textContent=v;}
function buttonState(run){const s=String(run&&run.state||'IDLE');$('auditPause').disabled=s!=='RUNNING';$('auditResume').disabled=s!=='PAUSED';$('auditStop').disabled=!['RUNNING','PAUSED'].includes(s);}

function renderSummary(status){
  const s=status.summary||{},h=s.health||{},run=status.run||null,worker=status.worker||{};
  setText('metricGames',fmtNum(s.games));setText('metricGamesSub',`${fmtNum(s.certifiedGames)} canonically certified`);
  setText('metricAudited',fmtNum(s.certifiedGames));setText('metricAuditedSub',`${fmtNum(s.staleGames)} stale >30d`);
  setText('metricHealthy',fmtNum(h.HEALTHY));setText('metricDegraded',fmtNum(h.DEGRADED));setText('metricInconclusive',fmtNum(s.inconclusiveGames||h.INCONCLUSIVE));setText('metricUnplayable',fmtNum(h.UNPLAYABLE));setText('metricNoMedia',fmtNum(h.NO_MEDIA));
  const repair=status.repair||{};setText('metricRepairQueue',fmtNum(repair.queue||0));setText('metricRepaired',fmtNum(repair.repaired||0));
  setText('metricAssets',fmtNum((s.playedAssets||0)+(s.failedAssets||0)));setText('metricAssetsSub',`${fmtNum(s.playedAssets)} played • ${fmtNum(s.failedAssets)} failed`);
  setText('metricRun',run?String(run.state||'IDLE'):'IDLE');
  setText('metricRunSub',run?`Run #${run.id} • ${run.processed_games||0}/${run.total_games||0} • ${status.workerCount||1} lanes`:(worker.alive?`${status.workerCount||1} worker lane${(status.workerCount||1)===1?'':'s'} online`:'Worker offline'));
  const pct=run?Number(run.progressPct||0):0;$('progressFill').style.width=Math.max(0,Math.min(100,pct))+'%';
  setText('progressLabel',run?`${String(run.state)} • ${pct.toFixed(1)}%`:'Idle');
  setText('progressDetail',run?(run.current_event_key?`#${run.current_ordinal} • ${run.current_event_key} • ${run.current_phase||''}`:`${run.processed_games||0}/${run.total_games||0} games`):'No canonical audit run active.');
  buttonState(run);
  setText('probeGame',worker.current&&worker.current.game||'Waiting');
  const workers=Array.isArray(status.workers)?status.workers:[],alive=workers.filter(w=>w.alive).length;
  setText('probeState',`ONLINE • ${alive}/${status.workerCount||workers.length||1} LANES`);
  $('probeState').className='state '+(alive?'pass':'idle');
  renderDiagnostics(status);
  if(status.newestEligibleDate&&!$('auditStartDate').value)$('auditStartDate').value=status.newestEligibleDate;
}

function fmtAge(seconds){const s=Math.max(0,Number(seconds||0));if(s<60)return `${s.toFixed(1)}s`;const m=Math.floor(s/60),r=Math.round(s%60);return `${m}m ${r}s`;}
function renderDiagnostics(status){
  const worker=status.worker||{},d=worker.diagnostics||{},cur=worker.current||{},recovery=worker.recoveredExceptionFailures||{},playableRecovery=worker.recoveredPlayableEvidence||{},alternateRecovery=worker.recoveredAlternatives||{},dbw=status.dbWriter||{};
  const storageError=String(status.storageReadError||'');
  const dbLocked=String(dbw.state||'').toUpperCase()==='LOCKED'||String(d.dbState||'').toUpperCase()==='LOCKED'||!!storageError;
  setText('diagHeartbeat',state.statusFailures?`DELAYED ${state.statusFailures}/3`:'ONLINE');
  const heartbeat=$('diagHeartbeat');if(heartbeat)heartbeat.className='diag-value '+(state.statusFailures?'bad':'ok');
  setText('diagStatusCacheAge',`${fmtAge(status.statusCacheAgeSeconds||0)} old`);
  const inventoryAge=state.lastInventoryOkAt?Math.max(0,(Date.now()-state.lastInventoryOkAt)/1000):0;
  setText('diagInventoryState',state.inventoryError?`STALE • ${state.inventoryError} • last good ${fmtAge(inventoryAge)} ago`:(state.lastInventoryOkAt?`CURRENT • refreshed ${fmtAge(inventoryAge)} ago`:'LOADING'));
  setText('diagRun',d.runId?`#${d.runId}`:(status.run?`#${status.run.id}`:'—'));
  setText('diagOrdinal',d.ordinal?`#${d.ordinal}`:(cur.ordinal?`#${cur.ordinal}`:'—'));
  setText('diagEvent',d.eventKey||cur.event||'—');
  setText('diagPhase',d.phase||cur.phase||'IDLE');
  setText('diagPhaseAge',fmtAge(d.phaseAgeSeconds));
  setText('diagProgressAge',fmtAge(d.idleSinceProgressSeconds));
  setText('diagDbState',dbLocked?'LOCKED / RETRYING':'READY');
  $('diagDbState').className='diag-value '+(dbLocked?'bad':'ok');
  setText('diagDbOp',dbw.activeOperation||d.pendingDbWrite||d.dbOperation||'—');
  setText('diagDbRetries',fmtNum(dbw.lockRetries||d.dbLockRetries||0));
  setText('diagParity',`${fmtNum(d.dbAssetCount||0)} DB • ${fmtNum(d.productionMediaCount||0)} production media • ${fmtNum(d.productionPlayableCount||0)} playable`);
  const prodState=String(d.productionPlanState||'—');
  setText('diagProductionState',prodState==='ENDPOINT_UNSUPPORTED_SPECIAL_EVENT'?'SPECIAL EVENT ENDPOINT UNSUPPORTED • normalized catalog authoritative':prodState);
  const counts=d.candidateCounts||{};
  setText('diagCandidates',`G ${counts.green||0} • P ${counts.extended||0} • Gold ${counts.gold||0} • B ${counts.blue||0}`);
  setText('diagCandidate',d.candidateTier?`${d.candidateTier} ${d.candidateIndex||0}/${d.candidateCount||0}`:'—');
  setText('diagAsset',d.assetTitle||d.assetKey||'—');
  setText('diagAssetKey',d.assetKey||'—');
  setText('diagProvider',d.assetProvider||'—');
  setText('diagProbe',d.probeAttempt?`${d.probeAttempt}/${d.probeMaxAttempts||2}`:'—');
  setText('diagProbeResult',d.lastProbeResult||worker.lastError||status.browserError||'—');
  setText('diagDiscovery',d.discoveryPass?`${d.discoveryPass}/${d.discoveryMaxPasses||0} • ${d.discoveryResult||'working'}`:'AUDIT DISCOVERY DISABLED • Repair Engine owns discovery');
  const waiting=d.waitingReason||storageError||(dbw.state==='LOCKED'?`Serialized DB writer is retrying ${dbw.activeOperation||'audit commit'}`:'No wait condition');
  setText('diagWaiting',waiting);
  $('diagWaiting').className='diagnostic-wait '+((d.waitingReason||storageError||dbw.state==='LOCKED')?'active':'');
  setText('diagBrowser',status.browser||'Chromium not started yet');
  setText('diagOrigin',status.probeUrl||'—');
  const recoveredParts=[];
  if(recovery.requeued)recoveredParts.push(`${recovery.requeued} prior exception failure${recovery.requeued===1?'':'s'} requeued`);
  if(playableRecovery.restoredAssets)recoveredParts.push(`${playableRecovery.restoredAssets} recent-playable asset${playableRecovery.restoredAssets===1?'':'s'} restored`);
  if(alternateRecovery.restoredAlternatives)recoveredParts.push(`${alternateRecovery.restoredAlternatives} healthy/non-hard alternative${alternateRecovery.restoredAlternatives===1?'':'s'} restored`);
  if(alternateRecovery.resetNonHardFailures)recoveredParts.push(`${alternateRecovery.resetNonHardFailures} stale soft/infra failure${alternateRecovery.resetNonHardFailures===1?'':'s'} cleared`);
  if(alternateRecovery.preservedRecentPlayable)recoveredParts.push(`${alternateRecovery.preservedRecentPlayable} recent PLAYED success${alternateRecovery.preservedRecentPlayable===1?'':'es'} preserved`);
  if(alternateRecovery.removedFalsePackages)recoveredParts.push(`${alternateRecovery.removedFalsePackages} false UNPLAYABLE/NO MEDIA package${alternateRecovery.removedFalsePackages===1?'':'s'} removed`);
  if(Array.isArray(alternateRecovery.requeuedOrdinals)&&alternateRecovery.requeuedOrdinals.length)recoveredParts.push(`${alternateRecovery.requeuedOrdinals.length} affected game${alternateRecovery.requeuedOrdinals.length===1?'':'s'} requeued`);
  if(Array.isArray(playableRecovery.requeuedOrdinals)&&playableRecovery.requeuedOrdinals.length)recoveredParts.push(`${playableRecovery.requeuedOrdinals.length} false-unplayable game${playableRecovery.requeuedOrdinals.length===1?'':'s'} requeued`);
  setText('diagRecovered',recoveredParts.join(' • ')||'None');
  const lanes=$('diagWorkers');
  if(lanes){
    const workers=Array.isArray(status.workers)?status.workers:[];
    const writerState=String(dbw.state||'IDLE');
    const writerCard=`<div class="worker-lane ${dbw.alive?'live':'dead'}"><strong>DB WRITER</strong><span>${esc(writerState)} • queue ${esc(dbw.queueDepth||0)}</span><small>${dbw.activeOperation?`${esc(dbw.activeOperation)}${dbw.activeOrdinal?` • #${esc(dbw.activeOrdinal)}`:''}`:`${esc(dbw.completedWrites||0)} commits saved`}</small></div>`;
    const workerCards=workers.map(w=>{const wd=w.diagnostics||{},wc=w.current||{},phase=wd.phase||wc.phase||'IDLE',game=wc.game||wd.game||'Waiting',ord=wc.ordinal||wd.ordinal||'',pending=wd.pendingDbWrite||'';const detail=pending?`${phase} • SAVE QUEUED: ${pending}`:(wd.waitingReason?`${phase} • ${wd.waitingReason}`:phase);return `<div class="worker-lane ${w.alive?'live':'dead'}"><strong>LANE ${esc(w.lane||wd.workerLane||'?')}</strong><span>${ord?`#${esc(ord)} • `:''}${esc(game)}</span><small>${esc(detail)}</small></div>`}).join('');
    lanes.innerHTML=writerCard+(workerCards||'<div class="worker-lane idle">No server workers reported.</div>');
  }
  const repair=status.repair||{},rw=repair.worker||{},rc=rw.current||{},rs=rw.stats||{};
  setText('repairState',rw.enabled===false?'DISABLED':(rw.alive?(rc.state||'ONLINE'):'OFFLINE'));
  const repairState=$('repairState');if(repairState)repairState.className='diag-value '+(rw.alive?'ok':'bad');
  setText('repairQueue',fmtNum(repair.queue||0));
  setText('repairGame',rc.game||rc.eventKey||'—');
  setText('repairTarget',rc.health?`${rc.health} → ${rc.target||'ANY'}`:'—');
  setText('repairPhase',rc.phase||'IDLE');
  setText('repairAttempt',rc.attempt?String(rc.attempt):'—');
  setText('repairCandidate',rc.assetKey?`${rc.tier||''} • ${rc.assetKey}`:'—');
  setText('repairResult',`${rc.provider||'—'} • ${rc.lastResult||rw.lastError||'—'}`);
  setText('repairTotals',`${fmtNum(rs.jobsAttempted||0)} jobs • ${fmtNum(rs.newCandidates||0)} new candidates • ${fmtNum(rs.candidatesCertified||0)} certified • ${fmtNum(rs.gamesRepaired||0)} promotions • ${fmtNum(rs.discoveryExhausted||0)} exhausted`);
  const repairTrace=$('repairTrace');if(repairTrace){const rr=(rw.trace||[]).slice().reverse();repairTrace.innerHTML=rr.map(r=>`<div class="${esc(String(r.level||'').toLowerCase())}"><time>${esc(fmtDateTime(r.at))}</time><span>${esc(r.message||'')}</span>${r.details?`<small>${esc(JSON.stringify(r.details))}</small>`:''}</div>`).join('')||'<div class="empty-trace">No repair activity yet.</div>';}

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
  if(state.inventoryBusy)return;
  state.inventoryBusy=true;state.lastInventoryAt=Date.now();
  try{
    const q=new URLSearchParams({limit:String(state.limit),offset:String(state.offset)}),lg=$('filterLeague').value,h=$('filterHealth').value,search=$('filterSearch').value.trim();
    if(lg)q.set('league',lg);if(h)q.set('health',h);if(search)q.set('search',search);
    const d=await fetchJson(API+'/inventory?'+q,{timeoutMs:15000});
    state.rows=d.rows||[];state.total=Number(d.total||0);state.inventoryError='';state.lastInventoryOkAt=Date.now();
    setText('tableCount',`${fmtNum(state.total)} games`);const first=state.total?state.offset+1:0,last=Math.min(state.total,state.offset+state.limit);setText('pageLabel',`${first}–${last} of ${state.total}`);
    $('pagePrev').disabled=state.offset<=0;$('pageNext').disabled=state.offset+state.limit>=state.total;populateLeagues();renderRows();
    if(state.status)renderDiagnostics(state.status);
  }catch(e){
    state.inventoryError=e.message||String(e);log(`Inventory refresh delayed: ${state.inventoryError}`,'bad');
    if(state.status)renderDiagnostics(state.status);
  }finally{state.inventoryBusy=false;}
}
function populateLeagues(){const sel=$('filterLeague'),current=sel.value;const leagues=[...new Set(state.rows.map(r=>r.league).filter(Boolean))].sort();for(const lg of leagues)if(![...sel.options].some(o=>o.value===lg)){const o=document.createElement('option');o.value=lg;o.textContent=lg;sel.appendChild(o)}sel.value=current;}
async function refreshStatus(){
  if(state.statusBusy)return;
  const now=Date.now();
  if(document.hidden&&now-state.lastStatusAttemptAt<12000)return;
  state.statusBusy=true;state.lastStatusAttemptAt=now;
  try{
    const d=await fetchJson(API+'/status',{timeoutMs:7000});state.status=d;state.statusFailures=0;state.lastStatusOkAt=Date.now();renderSummary(d);
    if(!state.busy&&!document.hidden&&(Date.now()-state.lastInventoryAt>15000||!state.rows.length))refreshInventory();
  }catch(e){
    state.statusFailures+=1;
    if(state.statusFailures>=3){setText('metricRun','OFFLINE');setText('metricRunSub',`Heartbeat failed ${state.statusFailures} times • ${e.message}`);$('probeState').textContent='OFFLINE';$('probeState').className='state fail';setText('diagHeartbeat','OFFLINE');}
    else{setText('metricRunSub',`Status heartbeat delayed ${state.statusFailures}/3 • retaining last known server state`);$('probeState').textContent=`STATUS DELAYED ${state.statusFailures}/3`; $('probeState').className='state idle';setText('diagHeartbeat',`DELAYED ${state.statusFailures}/3`);}
    log(`Status heartbeat: ${e.message}`,'bad');
  }finally{state.statusBusy=false;}
}
async function command(path,body,label){if(state.busy)return;state.busy=true;try{const d=await post(path,body);log(label,'ok');if(d.run)renderSummary({...state.status,run:d.run});await refreshStatus();refreshInventory();}catch(e){log(`${label}: ${e.message}`,'bad');alert(e.message);}finally{state.busy=false;}}
async function resetAudit(){if(!confirm('RESET AUDIT will stop the current server worker, clear the audit queue/progress, and keep existing canonical certifications.\n\nContinue?'))return;state.offset=0;await command('/reset',{recertify:false},'Audit run reset');}
async function fullRecertify(){if(!confirm('FULL RECERTIFY will clear canonical package decisions and restore audit-managed links to ASSIGNED. Source media/history is preserved. Continue?'))return;await command('/reset',{recertify:true},'Canonical certifications reset');}
async function download(path,name){try{const r=await fetch(API+path,{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);const b=await r.blob(),u=URL.createObjectURL(b),a=document.createElement('a');a.href=u;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),1000);}catch(e){alert(e.message)}}
function bind(){
  $('auditEverything').onclick=()=>command('/start',{mode:'ALL',startDate:$('auditStartDate').value},'Canonical audit started');
  $('auditFailed').onclick=()=>command('/start',{mode:'FAILED',startDate:$('auditStartDate').value},'Failed-game retest started');
  $('auditStale').onclick=()=>command('/start',{mode:'STALE',startDate:$('auditStartDate').value},'Stale-game audit started');
  $('auditPause').onclick=()=>command('/pause',{},'Audit paused');$('auditResume').onclick=()=>command('/resume',{},'Audit resumed');$('auditStop').onclick=()=>command('/stop',{},'Audit stopped');$('auditReset').onclick=resetAudit;
  const full=document.getElementById('auditFullReset');if(full)full.onclick=fullRecertify;
  $('refreshInventory').onclick=()=>{state.offset=0;refreshInventory()};$('exportManifest').onclick=()=>download('/rehydration.json','sports-big-board-media-rehydration.json');$('exportCsv').onclick=()=>download('/failures.csv','sports-big-board-media-audit-failures.csv');
  $('pagePrev').onclick=()=>{state.offset=Math.max(0,state.offset-state.limit);refreshInventory()};$('pageNext').onclick=()=>{state.offset+=state.limit;refreshInventory()};$('pageSize').onchange=()=>{state.limit=Number($('pageSize').value||100);state.offset=0;refreshInventory()};
  for(const id of ['filterLeague','filterHealth'])$(id).onchange=()=>{state.offset=0;refreshInventory()};let timer;$('filterSearch').oninput=()=>{clearTimeout(timer);timer=setTimeout(()=>{state.offset=0;refreshInventory()},250)};
}
async function init(){bind();state.limit=Number($('pageSize').value||100);setText('probePlaceholder','This page no longer plays audit media. Playback certification runs in controlled headless Chrome on the Sports Big Board backend.');await refreshStatus();refreshInventory();state.pollTimer=setInterval(refreshStatus,3000);}
document.addEventListener('visibilitychange',()=>{if(!document.hidden){refreshStatus();if(Date.now()-state.lastInventoryAt>15000)refreshInventory();}});
window.addEventListener('beforeunload',()=>{if(state.pollTimer)clearInterval(state.pollTimer)});init().catch(e=>{console.error(e);log(e.message,'bad')});
})();

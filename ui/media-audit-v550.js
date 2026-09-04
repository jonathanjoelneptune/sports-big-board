/* Sports Big Board v5.5.0 — exhaustive browser media health certification. */
(() => {
  'use strict';
  const VERSION='5.5.0';
  const STORE='sbb.media-audit.v550';
  const RUN_STORE='sbb.media-audit.run.v550';
  const FRESH_MS=30*24*60*60*1000;
  const STALE_MS=90*24*60*60*1000;
  const START_TIMEOUT=12000;
  const ADVANCE_SECONDS=.75;
  const $=id=>document.getElementById(id);
  const api=path=>window.SBB_API?.url?window.SBB_API.url(path):path;
  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const esc=s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[ch]||ch));
  const state={games:[],byKey:new Map(),assets:new Map(),results:loadResults(),run:loadRun(),page:0,pageSize:100,expanded:new Set(),loading:false,yt:null,ytReady:false,ytResolver:null,stopRequested:false,pauseRequested:false};

  function loadResults(){try{return JSON.parse(localStorage.getItem(STORE)||'{}')||{};}catch(_){return {};}}
  function saveResults(){try{localStorage.setItem(STORE,JSON.stringify(state.results));}catch(_){} }
  function loadRun(){try{return JSON.parse(localStorage.getItem(RUN_STORE)||'null');}catch(_){return null;}}
  function saveRun(){try{localStorage.setItem(RUN_STORE,JSON.stringify(state.run));}catch(_){} }
  function gameKey(g){return `${g.league}:${g.eventId}`;}
  function normalizeGame(row){
    const event=row.event||row.game||{};
    const date=clean(row.date||row.eventDate||row['Date']||event.date||event.gameDate).slice(0,10);
    const league=upper(row.league||row['League']||event.league||event.__sbbLeague);
    const eventId=clean(row.eventId||row['Event ID']||row.id||event.eventId||event.id||event.matchId||event.gamePk);
    const away=clean(row.away||row.awayName||event.away?.displayName||event.away?.name||event.awayTeam?.displayName||event.awayTeam?.name);
    const home=clean(row.home||row.homeName||event.home?.displayName||event.home?.name||event.homeTeam?.displayName||event.homeTeam?.name);
    const name=clean(row.game||row.gameLabel||row.matchup||row['Game']||((away||home)?`${away||'Away'} @ ${home||'Home'}`:''))||`${league} ${eventId}`;
    const tiers=row.tiers||{};
    return {date,league,eventId,name,tiers,bestTier:clean(row.bestTier||row['Best Tier']),auditStatus:clean(row.auditStatus||row['Audit Status']),raw:row};
  }
  function tier(asset){const t=clean(asset?.recapTier||asset?.tier||'blue').toLowerCase();return t==='purple'?'extended':t;}
  function tierName(t){return t==='extended'?'PURPLE':upper(t||'BLUE');}
  function assetKey(a){return clean(a?.assetKey||a?.key||a?.providerMediaId||a?.youtubeId||a?.mediaUrl||a?.url);}
  function assetUrl(a){return clean(a?.mediaUrl||a?.canonicalUrl||a?.url||a?.embedUrl);}
  function youtubeId(a){
    const direct=clean(a?.youtubeId||a?.videoId||(upper(a?.provider)==='YOUTUBE'?a?.providerMediaId:''));if(direct)return direct;
    const u=assetUrl(a);let m=u.match(/[?&]v=([A-Za-z0-9_-]{6,})/);if(m)return m[1];m=u.match(/(?:youtu\.be\/|youtube(?:-nocookie)?\.com\/embed\/)([A-Za-z0-9_-]{6,})/i);return m?.[1]||'';
  }
  function resultFor(a){return state.results[assetKey(a)]||null;}
  function resultAge(r){return r?.testedAt?Date.now()-Number(r.testedAt):Infinity;}
  function resultState(a){const r=resultFor(a);if(r?.state==='PLAYED')return resultAge(r)<=FRESH_MS?'pass':resultAge(r)<=STALE_MS?'stale':'stale';if(r?.state==='FAILED')return 'fail';const runtime=upper(a?.runtimeCatalogState||a?.runtimeState);if(runtime==='FAILED'||runtime==='FAILED-RUNTIME')return 'fail';if(runtime==='PLAYED'||a?.verifiedPlayable===true)return 'stale';return 'unknown';}
  function planAssets(plan){return (plan?.media||[]).filter(a=>a&&assetKey(a)&&(['GAME',''].includes(upper(a.mediaScope||'GAME'))));}

  async function loadInventory(force=false){
    if(state.loading)return;state.loading=true;$('gameRows').innerHTML='<tr><td colspan="10" class="empty">Loading canonical game inventory…</td></tr>';
    try{
      const rows=[];let offset=0,total=Infinity;
      while(offset<total){
        const r=await fetch(api(`/api/history/audit?limit=500&offset=${offset}`),{cache:force?'reload':'no-store'});const data=await r.json();if(!r.ok||!data.ok)throw new Error(data.message||data.error||`HTTP ${r.status}`);
        const batch=(data.rows||[]).map(normalizeGame).filter(g=>g.date&&g.league&&g.eventId);rows.push(...batch);total=Number(data.total??rows.length);if(!batch.length)break;offset+=Number((data.rows||[]).length||batch.length);
        setProgress(`Loading inventory… ${rows.length.toLocaleString()} / ${Number(total).toLocaleString()}`,'Reading the canonical history catalog.');
      }
      state.games=rows;state.byKey=new Map(rows.map(g=>[gameKey(g),g]));populateLeagues();state.page=0;render();setProgress('Inventory ready',`${rows.length.toLocaleString()} canonical games loaded.`);
    }catch(err){$('gameRows').innerHTML=`<tr><td colspan="10" class="empty">Inventory load failed: ${esc(err.message||err)}</td></tr>`;log(`Inventory failure: ${err.message||err}`,'bad');}
    finally{state.loading=false;}
  }
  function populateLeagues(){const select=$('filterLeague'),current=select.value,leagues=[...new Set(state.games.map(x=>x.league).filter(Boolean))].sort();select.innerHTML='<option value="">ALL LEAGUES</option>'+leagues.map(x=>`<option>${esc(x)}</option>`).join('');select.value=current;}

  async function fetchPlan(g,force=false){
    const key=gameKey(g);if(state.assets.has(key)&&!force)return state.assets.get(key);
    const qs=new URLSearchParams({date:g.date,league:g.league,eventId:g.eventId});const r=await fetch(api(`/api/history/event/media?${qs}`),{cache:'no-store'});const data=await r.json();if(!r.ok||!data.ok)throw new Error(data.message||data.error||`HTTP ${r.status}`);const plan=data.plan||{};state.assets.set(key,plan);return plan;
  }

  function gameHealth(g){
    const plan=state.assets.get(gameKey(g));if(!plan)return {state:'UNTESTED',assets:null,last:0};const assets=planAssets(plan);if(!assets.length)return {state:'NO_MEDIA',assets,last:0};
    let pass=0,fail=0,unknown=0,stale=0,last=0;for(const a of assets){const s=resultState(a),r=resultFor(a);last=Math.max(last,Number(r?.testedAt||0));if(s==='pass')pass++;else if(s==='fail')fail++;else if(s==='stale')stale++;else unknown++;}
    if(unknown>0)return {state:(pass||stale)?'STALE':'UNTESTED',assets,last};if(pass===assets.length)return {state:'HEALTHY',assets,last};if(pass>0||stale>0)return {state:'DEGRADED',assets,last};if(fail===assets.length)return {state:'UNPLAYABLE',assets,last};return {state:'UNTESTED',assets,last};
  }
  function tierCell(g,t){const h=gameHealth(g),assets=h.assets;if(!assets)return '<span class="tier-chip none">—</span>';const items=assets.filter(a=>tier(a)===t);if(!items.length)return '<span class="tier-chip none">—</span>';let p=0,f=0,u=0;for(const a of items){const s=resultState(a);if(s==='pass'||s==='stale')p++;else if(s==='fail')f++;else u++;}const cls=f&&p?'mixed':f&&!p&&!u?'fail':p&&!f&&!u?'pass':'none';return `<span class="tier-chip ${cls}">${p}/${items.length}</span>`;}
  function filteredGames(){
    const lg=upper($('filterLeague').value),health=upper($('filterHealth').value),tierFilter=clean($('filterTier').value),q=clean($('filterSearch').value).toLowerCase();
    return state.games.filter(g=>{
      if(lg&&g.league!==lg)return false;const h=gameHealth(g);if(health&&h.state!==health)return false;if(q&&!`${g.date} ${g.league} ${g.name} ${g.eventId}`.toLowerCase().includes(q))return false;
      if(tierFilter){const assets=h.assets;if(!assets||!assets.some(a=>tier(a)===tierFilter))return false;}return true;
    });
  }
  function render(){
    state.pageSize=Number($('pageSize').value||100);const rows=filteredGames(),pages=Math.max(1,Math.ceil(rows.length/state.pageSize));state.page=Math.max(0,Math.min(state.page,pages-1));const start=state.page*state.pageSize,shown=rows.slice(start,start+state.pageSize);$('tableCount').textContent=`${rows.length.toLocaleString()} games`;
    const body=$('gameRows');if(!shown.length)body.innerHTML='<tr><td colspan="10" class="empty">No games match these filters.</td></tr>';else body.innerHTML=shown.map(g=>rowHtml(g)).join('');
    $('pageLabel').textContent=`${rows.length?start+1:0}–${Math.min(rows.length,start+state.pageSize)} of ${rows.length.toLocaleString()}`;$('pagePrev').disabled=state.page<=0;$('pageNext').disabled=state.page>=pages-1;
    bindRows();renderMetrics();
  }
  function rowHtml(g){const h=gameHealth(g),key=gameKey(g),open=state.expanded.has(key);return `<tr data-game="${esc(key)}"><td><button class="expand" aria-label="${open?'Collapse':'Expand'} assets">${open?'−':'+'}</button></td><td>${esc(g.date)}</td><td><span class="league">${esc(g.league)}</span></td><td><span class="game-name">${esc(g.name)}</span><span class="muted">${esc(g.eventId)}</span></td><td>${tierCell(g,'green')}</td><td>${tierCell(g,'extended')}</td><td>${tierCell(g,'gold')}</td><td>${tierCell(g,'blue')}</td><td><span class="health ${h.state}">${h.state.replace('_',' ')}</span></td><td>${h.last?new Date(h.last).toLocaleDateString():'—'}</td></tr>${open?assetRowHtml(g):''}`;}
  function assetRowHtml(g){const plan=state.assets.get(gameKey(g));if(!plan)return `<tr class="asset-row"><td></td><td colspan="9"><div class="asset-grid"><div class="asset-card"><strong>LOADING MEDIA…</strong></div></div></td></tr>`;const assets=planAssets(plan);if(!assets.length)return `<tr class="asset-row"><td></td><td colspan="9"><div class="asset-grid"><div class="asset-card"><strong>NO ASSIGNED GAME MEDIA</strong></div></div></td></tr>`;return `<tr class="asset-row"><td></td><td colspan="9"><div class="asset-grid">${assets.map(a=>{const s=resultState(a),r=resultFor(a);return `<div class="asset-card"><span class="tier-chip ${s==='pass'?'pass':s==='fail'?'fail':'none'}">${tierName(tier(a))}</span><div><strong>${esc(a.title||'Untitled media')}</strong><small>${esc(assetKey(a))} • ${esc(assetUrl(a)||youtubeId(a)||'')}</small></div><div><strong>${esc(upper(a.provider||'MEDIA'))}</strong><small>${esc(clean(a.durationSeconds||a.duration)?`${Math.round(Number(a.durationSeconds||a.duration))} sec`:'')}</small></div><div class="asset-state ${s==='pass'?'pass':s==='fail'?'fail':'unknown'}">${s==='pass'?'PLAYED':s==='fail'?'FAILED':s==='stale'?'STALE':'UNTESTED'}<small>${esc(r?.reason||a.runtimeFailureReason||'')}</small></div></div>`;}).join('')}</div></td></tr>`;}
  function bindRows(){document.querySelectorAll('tr[data-game] .expand').forEach(btn=>btn.onclick=async()=>{const tr=btn.closest('tr'),g=state.byKey.get(tr.dataset.game);if(!g)return;const key=gameKey(g);if(state.expanded.has(key)){state.expanded.delete(key);render();return;}state.expanded.add(key);render();try{await fetchPlan(g);render();}catch(err){log(`${g.league} ${g.name}: ${err.message||err}`,'bad');}});}

  function renderMetrics(){let audited=0,healthy=0,degraded=0,unplayable=0,noMedia=0;for(const g of state.games){const s=gameHealth(g).state;if(!['UNTESTED','STALE'].includes(s))audited++;if(s==='HEALTHY')healthy++;else if(s==='DEGRADED')degraded++;else if(s==='UNPLAYABLE')unplayable++;else if(s==='NO_MEDIA')noMedia++;}const results=Object.values(state.results),passed=results.filter(x=>x.state==='PLAYED').length,failed=results.filter(x=>x.state==='FAILED').length;$('metricGames').textContent=state.games.length.toLocaleString();$('metricGamesSub').textContent='Canonical event catalog';$('metricAudited').textContent=audited.toLocaleString();$('metricAuditedSub').textContent=state.games.length?`${((audited/state.games.length)*100).toFixed(1)}%`: '0%';$('metricHealthy').textContent=healthy.toLocaleString();$('metricDegraded').textContent=degraded.toLocaleString();$('metricUnplayable').textContent=unplayable.toLocaleString();$('metricNoMedia').textContent=noMedia.toLocaleString();$('metricAssets').textContent=results.length.toLocaleString();$('metricAssetsSub').textContent=`${passed.toLocaleString()} passed • ${failed.toLocaleString()} failed`;const run=state.run;$('metricRun').textContent=run?.status||'IDLE';$('metricRunSub').textContent=run?`Run ${run.id} • ${Number(run.index||0).toLocaleString()} games processed`:'Ready';}

  function ensureYouTube(){
    if(state.ytReady&&state.yt)return Promise.resolve(state.yt);return new Promise((resolve,reject)=>{const start=Date.now();const wait=()=>{if(state.ytReady&&state.yt)return resolve(state.yt);if(window.YT?.Player){createYouTube(resolve);return;}if(Date.now()-start>10000)return reject(new Error('YOUTUBE_API_TIMEOUT'));setTimeout(wait,120);};wait();});
  }
  function createYouTube(resolve){if(state.yt)return resolve(state.yt);state.yt=new YT.Player('youtubeProbe',{width:'100%',height:'100%',playerVars:{autoplay:0,controls:0,rel:0,playsinline:1,origin:location.origin},events:{onReady:e=>{state.ytReady=true;try{e.target.mute();}catch(_){}resolve(e.target);},onError:e=>{if(state.ytResolver)state.ytResolver({ok:false,reason:`YOUTUBE_ERROR_${e.data}`,hard:[2,100,101,150,153].includes(Number(e.data)),code:Number(e.data)});}}});}
  window.onYouTubeIframeAPIReady=()=>{if(!state.yt)createYouTube(()=>{});};
  function showProbe(kind){$('probePlaceholder').style.display='none';$('directProbe').style.display=kind==='direct'?'block':'none';const yt=$('youtubeProbe');if(yt)yt.style.display=kind==='youtube'?'block':'none';}
  async function probeYouTube(id){const player=await ensureYouTube();showProbe('youtube');const started=performance.now();return new Promise(resolve=>{let done=false;const finish=r=>{if(done)return;done=true;state.ytResolver=null;clearInterval(timer);clearTimeout(timeout);try{player.stopVideo();}catch(_){}resolve({...r,startupMs:Math.round(performance.now()-started)});};state.ytResolver=finish;try{player.mute();player.loadVideoById({videoId:id,startSeconds:0});}catch(err){finish({ok:false,reason:`YOUTUBE_LOAD_EXCEPTION:${err.message||err}`,hard:false});return;}const timer=setInterval(()=>{try{const ps=player.getPlayerState(),t=Number(player.getCurrentTime()||0);if(ps===1&&t>=ADVANCE_SECONDS)finish({ok:true,reason:'PLAYING_TIME_ADVANCED'});}catch(_){}},160);const timeout=setTimeout(()=>finish({ok:false,reason:'YOUTUBE_START_TIMEOUT',hard:false}),START_TIMEOUT);});}
  async function probeDirect(url){showProbe('direct');const v=$('directProbe');const started=performance.now();return new Promise(resolve=>{let done=false;const finish=r=>{if(done)return;done=true;cleanup();try{v.pause();v.removeAttribute('src');v.load();}catch(_){}resolve({...r,startupMs:Math.round(performance.now()-started)});};const poll=()=>{if(Number(v.currentTime||0)>=ADVANCE_SECONDS&&!v.paused)finish({ok:true,reason:'PLAYING_TIME_ADVANCED'});};const onError=()=>finish({ok:false,reason:`DIRECT_MEDIA_ERROR_${v.error?.code||'UNKNOWN'}`,hard:true});const cleanup=()=>{clearInterval(timer);clearTimeout(timeout);v.removeEventListener('error',onError);};v.addEventListener('error',onError);v.muted=true;v.src=url;try{const p=v.play();if(p?.catch)p.catch(()=>{});}catch(_){}const timer=setInterval(poll,150);const timeout=setTimeout(()=>finish({ok:false,reason:'DIRECT_START_TIMEOUT',hard:false}),START_TIMEOUT);});}
  async function probeAsset(g,a){
    const id=youtubeId(a),url=assetUrl(a);setProbe(g,a,'TESTING');let first;if(id)first=await probeYouTube(id);else if(url)first=await probeDirect(url);else first={ok:false,reason:'NO_PLAYBACK_URL',hard:true,startupMs:0};
    if(!first.ok&&!first.hard){log(`Soft failure ${assetKey(a)}: ${first.reason}; retrying once`,'warn');await sleep(900);const retry=id?await probeYouTube(id):url?await probeDirect(url):first;if(retry.ok)first=retry;else first={...retry,reason:`REPEATED_${retry.reason}`,hard:true};}
    const result={state:first.ok?'PLAYED':'FAILED',reason:first.reason,hard:!!first.hard,startupMs:first.startupMs,testedAt:Date.now(),runId:state.run?.id||'',date:g.date,league:g.league,eventId:g.eventId,tier:tier(a),title:clean(a.title),url:url||id};state.results[assetKey(a)]=result;saveResults();await persistRuntime(g,a,result);setProbe(g,a,result.state,result);log(`${first.ok?'PASS':'FAIL'} ${g.league} ${g.name} • ${tierName(tier(a))} • ${assetKey(a)} • ${first.reason}`,first.ok?'ok':'bad');return result;
  }
  async function persistRuntime(g,a,result){try{await fetch(api('/api/history/media/runtime'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date:g.date,league:g.league,eventId:g.eventId,assetKey:assetKey(a),state:result.state,reason:`MEDIA_AUDIT_V550:${result.reason}`}),cache:'no-store'});}catch(err){log(`Runtime persistence warning: ${err.message||err}`,'warn');}}

  async function runAudit(mode='all'){
    if(!state.games.length)await loadInventory();state.stopRequested=false;state.pauseRequested=false;
    const id=`${Date.now().toString(36)}-${Math.random().toString(36).slice(2,6)}`;let queue=state.games.slice();if(mode==='failed')queue=queue.filter(g=>['UNPLAYABLE','DEGRADED'].includes(gameHealth(g).state));if(mode==='stale')queue=queue.filter(g=>['STALE','UNTESTED'].includes(gameHealth(g).state));
    state.run={id,status:'RUNNING',mode,index:0,total:queue.length,startedAt:Date.now(),queue:queue.map(gameKey)};saveRun();setRunButtons();
    for(let i=0;i<queue.length;i++){
      if(state.stopRequested)break;while(state.pauseRequested&&!state.stopRequested){state.run.status='PAUSED';saveRun();setRunButtons();await sleep(300);}if(state.stopRequested)break;state.run.status='RUNNING';state.run.index=i;saveRun();setRunButtons();const g=queue[i];setProgress(`Game ${i+1} / ${queue.length}`,`${g.league} • ${g.date} • ${g.name}`,(i/Math.max(1,queue.length))*100);
      let plan;try{plan=await fetchPlan(g,true);}catch(err){log(`Plan load failed ${g.league} ${g.name}: ${err.message||err}`,'bad');continue;}const assets=planAssets(plan);if(!assets.length){log(`NO MEDIA ${g.league} ${g.name}`,'warn');render();continue;}
      for(let j=0;j<assets.length;j++){if(state.stopRequested)break;while(state.pauseRequested&&!state.stopRequested)await sleep(300);const a=assets[j];setProgress(`Game ${i+1}/${queue.length} • Asset ${j+1}/${assets.length}`,`${g.league} • ${g.name} • ${tierName(tier(a))}`,(i/Math.max(1,queue.length))*100);await probeAsset(g,a);}
      render();
    }
    state.run.status=state.stopRequested?'STOPPED':'COMPLETE';state.run.completedAt=Date.now();saveRun();setRunButtons();setProgress(state.stopRequested?'Audit stopped':'Audit complete',`${Number(state.run.index||0)+1} games processed.`,state.stopRequested?undefined:100);render();
  }
  async function resumeRun(){const run=state.run;if(!run||!Array.isArray(run.queue))return;state.stopRequested=false;state.pauseRequested=false;const queue=run.queue.map(k=>state.byKey.get(k)).filter(Boolean),start=Math.max(0,Number(run.index||0));run.status='RUNNING';saveRun();setRunButtons();for(let i=start;i<queue.length;i++){if(state.stopRequested)break;while(state.pauseRequested&&!state.stopRequested){run.status='PAUSED';saveRun();setRunButtons();await sleep(300);}run.status='RUNNING';run.index=i;saveRun();const g=queue[i];let plan;try{plan=await fetchPlan(g,true);}catch(err){log(`Plan load failed ${g.name}: ${err.message||err}`,'bad');continue;}const assets=planAssets(plan);for(let j=0;j<assets.length;j++){const prior=resultFor(assets[j]);if(prior?.runId===run.id)continue;if(state.stopRequested)break;await probeAsset(g,assets[j]);}render();}run.status=state.stopRequested?'STOPPED':'COMPLETE';run.completedAt=Date.now();saveRun();setRunButtons();render();}
  function setRunButtons(){const active=['RUNNING','PAUSED'].includes(state.run?.status);$('auditEverything').disabled=active;$('auditFailed').disabled=active;$('auditStale').disabled=active;$('auditPause').disabled=!active||state.pauseRequested;$('auditResume').disabled=!active||!state.pauseRequested;$('auditStop').disabled=!active;$('metricRun').textContent=state.run?.status||'IDLE';}

  function setProbe(g,a,status,result){$('probeGame').textContent=g?`${g.league} • ${g.name}`:'Waiting';$('probeAsset').textContent=a?`${a.title||assetKey(a)}\n${assetKey(a)}`:'—';$('probeTier').textContent=a?tierName(tier(a)):'—';$('probeProvider').textContent=a?upper(a.provider|| (youtubeId(a)?'YOUTUBE':'DIRECT')):'—';$('probeStartup').textContent=result?.startupMs!=null?`${result.startupMs} ms`:'—';$('probeResult').textContent=result?.reason||status||'—';const el=$('probeState');el.textContent=status;el.className=`state ${status==='PLAYED'?'pass':status==='FAILED'?'fail':status==='TESTING'?'testing':'idle'}`;}
  function setProgress(label,detail,pct){$('progressLabel').textContent=label;$('progressDetail').textContent=detail||'';if(pct!=null)$('progressFill').style.width=`${Math.max(0,Math.min(100,pct))}%`;}
  function log(text,cls=''){const el=$('probeLog'),d=document.createElement('div');d.textContent=`${new Date().toLocaleTimeString()}  ${text}`;if(cls)d.className=cls;el.prepend(d);while(el.children.length>150)el.lastElementChild.remove();}
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));

  function rehydrationGames(){return state.games.map(g=>({g,h:gameHealth(g)})).filter(x=>['UNPLAYABLE','NO_MEDIA','DEGRADED'].includes(x.h.state));}
  async function ensurePlansForFailures(){for(const {g} of rehydrationGames()){if(!state.assets.has(gameKey(g)))try{await fetchPlan(g);}catch(_){}}}
  async function exportManifest(){await ensurePlansForFailures();const games=rehydrationGames().map(({g,h})=>{const assets=h.assets||[];const failed=assets.filter(a=>resultState(a)==='fail').map(a=>({assetKey:assetKey(a),tier:tier(a),title:a.title||'',url:assetUrl(a)||youtubeId(a),reason:resultFor(a)?.reason||a.runtimeFailureReason||'FAILED'}));const present=new Set(assets.filter(a=>resultState(a)!=='fail').map(a=>tier(a)));return {date:g.date,league:g.league,eventId:g.eventId,game:g.name,status:h.state,failedAssets:failed,missingPreferredTiers:['green','extended'].filter(t=>!present.has(t))};});download(`sports-big-board-media-rehydration-${new Date().toISOString().slice(0,10)}.json`,JSON.stringify({version:VERSION,generatedAt:new Date().toISOString(),games},null,2),'application/json');}
  async function exportCsv(){await ensurePlansForFailures();const rows=[['Date','League','Event ID','Game','Game Health','Tier','Asset Key','Title','URL','Failure Reason']];for(const {g,h} of rehydrationGames()){for(const a of h.assets||[]){if(resultState(a)!=='fail')continue;rows.push([g.date,g.league,g.eventId,g.name,h.state,tierName(tier(a)),assetKey(a),a.title||'',assetUrl(a)||youtubeId(a),resultFor(a)?.reason||a.runtimeFailureReason||'FAILED']);}if(!h.assets?.length)rows.push([g.date,g.league,g.eventId,g.name,h.state,'','','','','NO_ASSIGNED_MEDIA']);}download(`sports-big-board-media-failures-${new Date().toISOString().slice(0,10)}.csv`,rows.map(r=>r.map(csvCell).join(',')).join('\n'),'text/csv');}
  function csvCell(v){const s=String(v??'');return /[",\n]/.test(s)?`"${s.replaceAll('"','""')}"`:s;}
  function download(name,body,type){const blob=new Blob([body],{type}),u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),500);}

  function bind(){
    $('auditEverything').onclick=()=>runAudit('all');$('auditFailed').onclick=()=>runAudit('failed');$('auditStale').onclick=()=>runAudit('stale');$('auditPause').onclick=()=>{state.pauseRequested=true;state.run.status='PAUSED';saveRun();setRunButtons();};$('auditResume').onclick=()=>{if(state.run?.status==='PAUSED'&&state.pauseRequested){state.pauseRequested=false;state.run.status='RUNNING';saveRun();setRunButtons();}else resumeRun();};$('auditStop').onclick=()=>{state.stopRequested=true;state.pauseRequested=false;};$('exportManifest').onclick=exportManifest;$('exportCsv').onclick=exportCsv;$('refreshInventory').onclick=()=>loadInventory(true);
    for(const id of ['filterLeague','filterHealth','filterTier','pageSize'])$(id).onchange=()=>{state.page=0;render();};$('filterSearch').oninput=()=>{state.page=0;render();};$('pagePrev').onclick=()=>{state.page--;render();};$('pageNext').onclick=()=>{state.page++;render();};setRunButtons();
    if(state.run&&['RUNNING','PAUSED'].includes(state.run.status)){state.run.status='PAUSED';state.pauseRequested=true;saveRun();setRunButtons();setProgress('Previous audit paused',`Run ${state.run.id} can be resumed.`);}
  }
  bind();loadInventory();
  window.SBB_MEDIA_AUDIT=Object.freeze({version:VERSION,loadInventory,runAudit,resumeRun,snapshot:()=>({games:state.games.length,results:Object.keys(state.results).length,run:state.run})});
})();

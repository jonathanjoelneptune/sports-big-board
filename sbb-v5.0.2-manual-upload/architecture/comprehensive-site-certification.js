/* Sports Big Board v5.0.2 — Unified Runtime Comprehensive Certification Architecture.
   Whole-site certification drives real navigation, Game Center UI, score-card
   playback, recovery, APIs, workers, discovery, rendering and memory. Selection is
   deliberately game-agnostic and seeded so every run is broad yet reproducible.
*/
(() => {
  'use strict';
  if (window.SBB_SITE_CERTIFICATION?.version === '3.2') return;

  const VERSION='3.2';
  const RELEASE=String(window.SBB_RELEASE_VERSION||window.SBB_CORE?.version||'5.0.2');
  const PLAYBACK_TARGET=8;
  const PLAYBACK_MIN_STARTS=5;
  const PLAYBACK_CONFIRM_TIMEOUT_MS=12500;
  const PROGRESS_EPSILON_SECONDS=.20;
  const PROGRESS_SOFT_KICK_MS=3500;
  const PROGRESS_RECOVERY_MS=8000;
  const state={running:false,lastReport:null,cardInstalled:false};
  const $=id=>document.getElementById(id);
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const now=()=>performance.now();
  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const round=v=>Number.isFinite(Number(v))?Math.round(Number(v)*10)/10:null;
  const pct=(a,b)=>Number(a)>0?round((Number(b)/Number(a))*100):null;
  const n=v=>Number(v||0)||0;
  const apiUrl=path=>window.SBB_API?.url?.(path)||path;
  const localDate=(offset=0)=>{const d=new Date();d.setDate(d.getDate()+offset);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
  const percentile=(values,p)=>{const xs=values.filter(Number.isFinite).sort((a,b)=>a-b);if(!xs.length)return null;return xs[Math.max(0,Math.min(xs.length-1,Math.ceil(p/100*xs.length)-1))];};
  const jsonBytes=value=>{try{return new Blob([JSON.stringify(value)]).size;}catch(_){try{return JSON.stringify(value).length;}catch(__){return 0;}}};
  const hashString=value=>{let h=2166136261>>>0;for(const ch of String(value||'')){h^=ch.charCodeAt(0);h=Math.imul(h,16777619)>>>0;}return h>>>0;};
  const normalizeSeed=value=>{const raw=Number(value);return Number.isFinite(raw)?(raw>>>0):((Date.now()^hashString(RELEASE))>>>0);};
  function seededRng(seed){let x=(normalizeSeed(seed)||0x9e3779b9)>>>0;return()=>{x^=x<<13;x^=x>>>17;x^=x<<5;return (x>>>0)/4294967296;};}
  function seededShuffle(rows,rng){const out=[...(rows||[])];for(let i=out.length-1;i>0;i--){const j=Math.floor(rng()*(i+1));[out[i],out[j]]=[out[j],out[i]];}return out;}
  function hooks(){return window.SBB_DEV_TEST_HOOKS||null;}
  function mainThreadGuard(){return window.SBB_MAIN_THREAD_GUARD||null;}
  async function yieldUi(){try{return await (mainThreadGuard()?.yieldToBrowser?.()||Promise.resolve(true));}catch(_){return true;}}
  async function requireResponsiveUi(){try{return await (mainThreadGuard()?.waitForBreathingRoom?.({timeoutMs:2500,maxFrameMs:240})??Promise.resolve(true));}catch(_){return true;}}

  /* Playback progress/recovery is a production authority owned by
     architecture/playback-progress-watchdog.js. Comprehensive Certification
     consumes that authority rather than implementing a second player state machine. */
  function progressAuthority(){return window.SBB_PLAYBACK_PROGRESS_WATCHDOG||null;}
  function installProgressWatchdog(){return progressAuthority()?.install?.()===true;}
  function progressPublic(){return progressAuthority()?.snapshot?.()||{version:'0',installed:false,confirmed:false,firstProgressMs:null,softKicks:0,recoveries:0,timeouts:0,lastReason:'watchdog unavailable',history:[]};}
  async function waitForProgress(options={}){
    const authority=progressAuthority();
    if(!authority?.waitForProgress)return {ok:false,reason:'playback progress watchdog unavailable',session:window.SBB_PLAYBACK_SESSION?.snapshot?.()||{},snap:progressPublic(),fallbackHops:0};
    return authority.waitForProgress(options);
  }

  async function fetchJson(path,{timeoutMs=8000,method='GET',body=null}={}){
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(new DOMException(`Timeout ${timeoutMs}ms`,'TimeoutError')),timeoutMs);
    const started=now();
    try{
      const init={method,cache:'no-store',signal:controller.signal,headers:{}};
      if(body!=null){init.headers['Content-Type']='application/json';init.body=JSON.stringify(body);}
      const response=await fetch(apiUrl(path),init);
      const text=await response.text();let data={};try{data=text?JSON.parse(text):{};}catch(_){data={_raw:text.slice(0,4000)};}
      return {path,status:response.status,ok:response.ok||response.status===202,elapsedMs:round(now()-started),bytes:text.length,data};
    }catch(err){return {path,status:0,ok:false,elapsedMs:round(now()-started),bytes:0,error:clean(err?.message||err),errorName:clean(err?.name)};}
    finally{clearTimeout(timer);}
  }

  function backendSummary(consoleData,auditData,silverData,sourcesData,recoveryData){
    const c=consoleData||{},a=auditData||{},s=silverData||{},src=sourcesData||{},rec=recoveryData||{};
    const workers=c.workers||{},pool=c.greenPool||{},queue=c.greenGapQueue||{},db=c.databaseAudit||rec.databaseAudit||{};
    const workerRows=Object.entries(workers).map(([name,w])=>({
      name,phase:clean(w?.phase||'unknown'),healthy:w?.healthy===true,heartbeatAgeSeconds:n(w?.heartbeatAgeSeconds),progressAgeSeconds:n(w?.progressAgeSeconds),
      workerRole:clean(w?.workerRole),affinity:clean(w?.ruleAffinity),assist:clean(w?.ruleAffinityAssist),workType:clean(w?.workType),provider:clean(w?.provider),current:clean(w?.current),
      jobsPerHour:n(pool?.utilization?.[name]?.jobsPerHour),busyPercent:n(pool?.utilization?.[name]?.busyPercent),providerWaitPercent:n(pool?.utilization?.[name]?.providerWaitPercent)
    }));
    const sourceRows=(src.rows||[]).map(row=>({
      league:upper(row.league),kind:clean(row.kind),label:clean(row.label||row.name||row.id),active:row.active!==false,priority:clean(row.priority),
      playlistItems:n(row.stats?.playlistItems),hydrated:n(row.stats?.hydrated),assets:n(row.stats?.assets),assigned:n(row.stats?.assigned),orphaned:n(row.stats?.orphaned),quarantined:n(row.stats?.quarantined),
      state:clean(row.stats?.state||row.status||''),lastCrawlAt:n(row.stats?.lastCrawlAt||row.lastCrawlAt),lastError:clean(row.stats?.lastError||row.lastError)
    }));
    return {
      backendVersion:clean(c.version),discoveryVersion:n(c.historyDiscoveryVersion),deploymentMode:clean(c.deploymentMode),workMode:clean(c.workMode?.mode||c.background?.workMode),
      playbackSuspended:!!c.playbackSuspended,searchSuspended:!!c.searchSuspended,
      workers:workerRows,configuredWorkers:n(pool.configured),healthyWorkers:workerRows.filter(x=>x.healthy).length,
      queue:{pending:n(queue.pending||queue.total||queue.ready),ready:n(queue.ready),leased:n(queue.leased),notReady:n(queue.notReady),indexPassPending:n(c.discoveryEfficiency?.indexPassPending||c.indexPassPending),dueCoverageGaps:n(c.discoveryEfficiency?.dueCoverageGaps||c.greenGap?.remaining)},
      catalog:{games:n(a.summary?.games||a.total),verifiedAssets:n(a.summary?.verifiedAssets),coverageComplete:n(a.summary?.coverageCompleteGames),noVerifiedMedia:n(a.summary?.noVerifiedMediaGames),indexPassPending:n(a.summary?.effectiveStatuses?.UNINDEXED),sourceExhaustedEmpty:n(a.summary?.effectiveStatuses?.SEARCHED_EMPTY)},
      silver:{collections:n(s.summary?.collections),links:n(s.summary?.links),uniqueAssets:n(s.summary?.uniqueAssets),suspicious:n(s.summary?.suspiciousLinks)},
      databaseAudit:{running:!!db.running,complete:!!db.complete,checked:n(db.checked),total:n(db.total),issues:db.issues||{},lastError:clean(db.lastError)},
      associations:c.associations||{},playlistCrawler:c.playlistCrawler||{},scheduleSync:c.scheduleSync||src.scheduleSync||{},providers:c.providerConcurrency||{},youtubeSearchBudget:c.youtubeSearchBudget||{},youtubeGateway:c.youtubeGateway||{},sources:sourceRows,
    };
  }

  async function backendSnapshot(){
    const probes=await Promise.all([
      fetchJson('/api/status',{timeoutMs:6000}),
      fetchJson('/api/history/worker-console?limit=320',{timeoutMs:8000}),
      fetchJson('/api/history/audit?limit=1&offset=0',{timeoutMs:12000}),
      fetchJson('/api/history/catalog/collections?limit=1&offset=0',{timeoutMs:12000}),
      fetchJson('/api/history/media-sources',{timeoutMs:12000}),
      fetchJson('/api/history/admin/recovery',{timeoutMs:8000}),
    ]);
    const by=Object.fromEntries(probes.map(x=>[x.path,x]));
    const summary=backendSummary(by['/api/history/worker-console?limit=320']?.data,by['/api/history/audit?limit=1&offset=0']?.data,by['/api/history/catalog/collections?limit=1&offset=0']?.data,by['/api/history/media-sources']?.data,by['/api/history/admin/recovery']?.data);
    return {probes,summary,raw:by};
  }
  function backendDelta(before,after){
    const a=before?.summary||{},b=after?.summary||{};
    const sourceTotals=rows=>rows.reduce((x,r)=>({assets:x.assets+n(r.assets),assigned:x.assigned+n(r.assigned),orphaned:x.orphaned+n(r.orphaned),playlistItems:x.playlistItems+n(r.playlistItems)}),{assets:0,assigned:0,orphaned:0,playlistItems:0});
    const sa=sourceTotals(a.sources||[]),sb=sourceTotals(b.sources||[]);
    return {auditChecked:n(b.databaseAudit?.checked)-n(a.databaseAudit?.checked),catalogGames:n(b.catalog?.games)-n(a.catalog?.games),verifiedAssets:n(b.catalog?.verifiedAssets)-n(a.catalog?.verifiedAssets),sourceAssets:sb.assets-sa.assets,sourceAssigned:sb.assigned-sa.assigned,sourceOrphaned:sb.orphaned-sa.orphaned,playlistItems:sb.playlistItems-sa.playlistItems,indexPassPending:n(b.catalog?.indexPassPending)-n(a.catalog?.indexPassPending),coverageComplete:n(b.catalog?.coverageComplete)-n(a.catalog?.coverageComplete)};
  }

  function eventTeams(event){
    const parts=Array.isArray(event?.participants)?event.participants:[];
    const away=event?.awayTeam||event?.away||parts.find(x=>x?.side==='away')||parts[0]||{};
    const home=event?.homeTeam||event?.home||parts.find(x=>x?.side==='home')||parts[1]||{};
    const name=x=>clean(x?.displayName||x?.name||x?.shortName||x?.abbreviation||x);return {away:name(away),home:name(home)};
  }
  function eventLabel(event,league){const t=eventTeams(event);return `${league} ${t.away||'?'} @ ${t.home||'?'}`;}
  function finalish(event){return /final|finished|completed|complete|post/i.test(clean(event?.status||event?.state?.report||event?.state?.description));}
  async function dayState(date){return fetchJson(`/api/day-state?date=${encodeURIComponent(date)}`,{timeoutMs:9000});}
  function eventsFromDay(payload){
    const rows=[];const map=payload?.scoreRowsByLeague||payload?.scoreRows||{};
    if(map&&typeof map==='object'&&!Array.isArray(map))for(const [league,events] of Object.entries(map))for(const event of events||[])rows.push({...event,competitionId:event.competitionId||league,__sbbLeague:league,__sbbDate:clean(event.date||event.gameDate||payload?.date).slice(0,10)});
    return rows;
  }
  function certificationDates(seed){
    const rng=seededRng(seed^0x7f4a7c15),recent=[-1,-2,-3,-4,-7],archive=seededShuffle([-14,-21,-30,-45,-60,-90,-120,-180,-240,-300],rng).slice(0,3);
    return [...new Set([...recent,...archive].map(localDate))];
  }
  async function gameCenterCandidates(seed){
    const dates=certificationDates(seed),days=[];for(const date of dates)days.push(await dayState(date));
    const events=days.filter(x=>x.ok).flatMap(x=>eventsFromDay(x.data)).filter(finalish),rng=seededRng(seed^0x5bd1e995);
    const byLeague=new Map();for(const event of seededShuffle(events,rng)){const league=upper(event.competitionId||event.__sbbLeague||event.league);if(!byLeague.has(league))byLeague.set(league,[]);byLeague.get(league).push(event);}
    const leagues=seededShuffle([...byLeague.keys()],rng),selected=[];let depth=0;
    while(selected.length<12&&depth<5){for(const league of leagues){const row=byLeague.get(league)?.[depth];if(row)selected.push(row);if(selected.length>=12)break;}depth++;}
    return {days,events,candidates:selected.slice(0,12),dates};
  }
  const GAME_CENTER_EXPECTED_SUPPORTED=new Set(['MLB','NFL','CFB','NBA','NHL','MLS','EPL']);
  function gameCenterSupport(league){const lg=upper(league);return {league:lg,supported:GAME_CENTER_EXPECTED_SUPPORTED.has(lg),reason:GAME_CENTER_EXPECTED_SUPPORTED.has(lg)?'SUPPORTED':'NO_GAME_CENTER_PROVIDER'};}
  function gameCenterPayloadQuality(league,gc,event){
    const lg=upper(league),board=gc?.scoreboard||{},innings=(board.innings||[]).length,periods=(board.periods||[]).length,timeline=(gc?.timeline||[]).length,scoring=(gc?.scoringPlays||[]).length,players=(gc?.playerStatSections||[]).length,providerComplete=gc?.coverage?.complete!==false;
    if(!gc)return {complete:false,reason:'NO_PAYLOAD',innings,periods,timeline,scoring,players};
    if(!finalish(event))return {complete:providerComplete,reason:providerComplete?'PROVIDER_COMPLETE':'PROVIDER_PARTIAL',innings,periods,timeline,scoring,players};
    let rich=true,reason='SPORT_AWARE_COMPLETE';
    if(lg==='MLB'){rich=innings>=7&&(timeline>=20||players>=2);reason=rich?'SPORT_AWARE_COMPLETE':'FINAL_MLB_PAYLOAD_TOO_SPARSE';}
    else if(lg==='NFL'||lg==='CFB'){rich=(periods>=4&&(timeline>=20||players>=4))||timeline>=50;reason=rich?'SPORT_AWARE_COMPLETE':`FINAL_${lg}_PAYLOAD_TOO_SPARSE`;}
    else if(lg==='NBA'||lg==='NHL'){rich=(periods>=3&&(timeline>=20||players>=2))||timeline>=50;reason=rich?'SPORT_AWARE_COMPLETE':`FINAL_${lg}_PAYLOAD_TOO_SPARSE`;}
    else if(lg==='MLS'||lg==='EPL'){rich=timeline>=5||scoring>=1||players>=2;reason=rich?'SPORT_AWARE_COMPLETE':`FINAL_${lg}_PAYLOAD_TOO_SPARSE`;}
    return {complete:providerComplete&&rich,reason:providerComplete?reason:'PROVIDER_PARTIAL',innings,periods,timeline,scoring,players};
  }
  async function probeGameCenter(event,index){
    const league=upper(event.competitionId||event.__sbbLeague||event.league),label=eventLabel(event,league),support=gameCenterSupport(league),started=now();
    const base={event,label,league,date:clean(event.__sbbDate||event.date).slice(0,10),eventId:clean(event.eventId||event.scoreEventId||event.gamePk||event.id)};
    if(!support.supported)return {...base,ok:false,unsupported:true,unsupportedReason:support.reason,elapsedMs:0,bytes:0,coverageComplete:false,quality:'',partial:false,innings:0,periods:0,timeline:0,scoringPlays:0,playerSections:0,winProbability:0,error:''};
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(new DOMException('Certification hard timeout','TimeoutError')),7500);
    try{
      const gc=await window.SBB_GAME_CENTER?.get?.(event,{force:index===0,signal:controller.signal,timeoutMs:6500});const elapsedMs=round(now()-started),bytes=jsonBytes(gc),board=gc?.scoreboard||{},payloadQuality=gameCenterPayloadQuality(league,gc,event);
      return {...base,ok:!!gc&&payloadQuality.complete,unsupported:false,elapsedMs,bytes,coverageComplete:payloadQuality.complete,quality:clean(gc?.quality?.level),partial:!!gc?.partial,innings:payloadQuality.innings,periods:payloadQuality.periods,timeline:payloadQuality.timeline,scoringPlays:payloadQuality.scoring,playerSections:payloadQuality.players,winProbability:(gc?.winProbability||board.winProbability||[]).length,completenessReason:payloadQuality.reason,error:payloadQuality.complete?'':payloadQuality.reason};
    }catch(err){
      const message=`${clean(err?.name)}: ${clean(err?.message||err)}`;
      // A provider-not-implemented response is a capability boundary, not a runtime
      // regression. Expected-supported competitions still fail if their resolver is broken.
      const runtimeUnsupported=/provider not implemented|GAME_CENTER_PROVIDER_NOT_IMPLEMENTED/i.test(message)&&!GAME_CENTER_EXPECTED_SUPPORTED.has(league);
      return {...base,ok:false,unsupported:runtimeUnsupported,unsupportedReason:runtimeUnsupported?'NO_GAME_CENTER_PROVIDER':'',elapsedMs:round(now()-started),bytes:0,coverageComplete:false,quality:'',partial:false,innings:0,periods:0,timeline:0,scoringPlays:0,playerSections:0,winProbability:0,error:runtimeUnsupported?'':message};
    }finally{clearTimeout(timer);}
  }
  async function gameCenterCensus(seed){
    const c=await gameCenterCandidates(seed),rows=[];for(let i=0;i<c.candidates.length;i++){rows.push(await probeGameCenter(c.candidates[i],i));await sleep(60);}
    const supported=rows.filter(x=>!x.unsupported),unsupported=rows.filter(x=>x.unsupported);
    return {dates:c.dates,dayProbes:c.days.map(x=>({path:x.path,ok:x.ok,status:x.status,elapsedMs:x.elapsedMs,games:n(x.data?.summary?.games||eventsFromDay(x.data).length)})),rows,supported:supported.length,unsupported:unsupported.length,pass:supported.filter(x=>x.ok).length,fail:supported.filter(x=>!x.ok).length,p95Ms:round(percentile(supported.filter(x=>x.ok).map(x=>x.elapsedMs),95)),maxMs:round(Math.max(0,...supported.map(x=>n(x.elapsedMs))))};
  }
  async function gameCenterUiExercise(gameCenter){
    const view=window.SBB_GAME_CENTER_VIEW;if(!view?.load)return {available:false,attempted:0,pass:0,fail:0,sections:0,rows:[],reason:'Game Center view unavailable'};
    const saved=view.selected||null,rows=[],samples=(gameCenter?.rows||[]).filter(x=>x.ok&&x.event).slice(0,2);
    try{
      for(const sample of samples){const started=now();try{await view.load(sample.event,{force:false});let sections=0;for(const section of ['overview','team-stats','players','plays']){try{view.selectSection?.(section);sections++;await sleep(25);}catch(_){}}rows.push({ok:true,label:sample.label,elapsedMs:round(now()-started),sections});}catch(err){rows.push({ok:false,label:sample.label,elapsedMs:round(now()-started),sections:0,error:clean(err?.message||err)});}}
    }finally{try{if(saved)await view.load(saved,{force:false});else view.clear?.('Game Center follows the active game video.');}catch(_){}}
    return {available:true,attempted:rows.length,pass:rows.filter(x=>x.ok).length,fail:rows.filter(x=>!x.ok).length,sections:rows.reduce((a,x)=>a+n(x.sections),0),rows};
  }

  function cardQuality(card){const c=card?.classList;if(c?.contains?.('highlight-recap'))return 'GREEN';if(c?.contains?.('highlight-extended'))return 'PURPLE';if(c?.contains?.('highlight-blue'))return 'BLUE';if(c?.contains?.('highlight-gold'))return 'GOLD';return 'UNKNOWN';}
  function cardLeague(card){const match=card?.__sbbMatch||{},direct=upper(match.competitionId||match.__sbbLeague||match.league);if(direct)return direct;const m=String(card?.className||'').match(/(?:^|\s)league-([a-z0-9-]+)/i);return m?m[1].toUpperCase():'UNKNOWN';}
  function cardKey(card,date=''){return clean(card?.dataset?.sbbGameKey||`${date}:${cardLeague(card)}:${card?.textContent||''}`).slice(0,320);}
  function cardMediaProbe(card){
    try{const match=card?.__sbbMatch;if(!match)return {};const h=hooks(),direct=h?.scoreCardProbe?.(match);if(direct)return direct;const resolved=window.scoreCardAvailability?.(match)||{},primary=resolved.primary||window.scoreCardPrimaryItem?.(match,resolved.items||[]),editorial=resolved.editorialPrimary||primary;return {editorialMediaKey:clean(window.playbackItemKey?.(editorial)||''),selectedMediaKey:clean(window.playbackItemKey?.(primary)||''),readinessBefore:resolved.readinessBefore||'',primaryRejected:!!resolved.primaryRejected};}catch(_){return {};}
  }
  function cardMediaKey(card){return clean(cardMediaProbe(card).selectedMediaKey||'');}
  function visiblePlayableCards(){try{return [...document.querySelectorAll('#scoreCells .score-card.has-highlights')].filter(card=>!card.disabled&&typeof card.click==='function');}catch(_){return [];}}
  async function waitForCards(timeoutMs=4500){const deadline=Date.now()+timeoutMs;while(Date.now()<deadline){const cards=visiblePlayableCards();if(cards.length)return cards;await sleep(150);}return [];}
  function choosePlaybackCard(cards,{seenMedia,seenGames,leagueCounts,qualityCounts,rng,date}){
    const ranked=[];for(const card of cards){const probe=cardMediaProbe(card),mediaKey=clean(probe.selectedMediaKey||''),gameKey=cardKey(card,date),league=cardLeague(card),quality=cardQuality(card);if(!mediaKey||seenMedia.has(mediaKey)||seenGames.has(gameKey))continue;let score=0;score+=Math.max(0,80-20*n(leagueCounts[league]));score+=Math.max(0,60-18*n(qualityCounts[quality]));if(['GREEN','PURPLE','BLUE'].includes(quality))score+=25;ranked.push({card,mediaKey,editorialMediaKey:clean(probe.editorialMediaKey||mediaKey),readinessBefore:clean(probe.readinessBefore||'UNKNOWN'),primaryRejected:!!probe.primaryRejected,gameKey,league,quality,score:score+rng()});}return ranked.sort((a,b)=>b.score-a.score)[0]||null;
  }
  async function waitForSelection(beforeId,timeoutMs=5500){const deadline=Date.now()+timeoutMs;while(Date.now()<deadline){const s=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{};if(n(s.selectionId)>n(beforeId)&&clean(s.mediaKey))return s;await sleep(80);}return null;}
  function engineSnapshot(){try{return window.SBB_PLAYBACK_ENGINE?.snapshot?.()||{};}catch(_){return {};}}
  function v5RuntimeSnapshot(){
    const app=window.SBB_APP_STORE?.snapshot?.()||null,health=window.SBB_APP_STORE?.healthSnapshot?.()||{},orchestrator=window.SBB_PLAYBACK_ORCHESTRATOR,ownership=orchestrator?.ownershipSnapshot?.()||{};
    return {installed:!!app&&!!orchestrator,appStore:!!app,orchestrator:!!orchestrator,adapterBound:!!orchestrator?.adapterSnapshot?.().bound,schema:app?.schema||'',transactionId:app?.playback?.transactionId||'',playbackState:app?.playback?.state||'IDLE',eventKey:app?.playback?.eventKey||'',selectedEventKey:ownership.selectedEventKey||app?.selection?.eventKey||'',owned:ownership.owned!==false,invariant:app?.invariant||'MISSING',planCandidates:(app?.playback?.mediaPlan||[]).length,planAttempted:n(app?.playback?.planAttempted),planRejected:n(app?.playback?.planRejected),planExhausted:!!app?.playback?.planExhausted,candidateIndex:n(app?.playback?.candidateIndex),storeHealth:health};
  }
  async function waitForV5Intent(beforeTransactionId='',timeoutMs=1600){
    const deadline=Date.now()+timeoutMs;while(Date.now()<deadline){const snap=v5RuntimeSnapshot();if(snap.transactionId&&snap.transactionId!==beforeTransactionId)return snap;await sleep(40);}return null;
  }
  function gameCenterOwnershipOk(){
    try{const v5=window.SBB_PLAYBACK_ORCHESTRATOR?.ownershipSnapshot?.();if(v5?.transactionId)return !!v5.owned;}catch(_){}
    try{if(typeof window.selectedEventMatchesActivePlayback==='function')return !!window.selectedEventMatchesActivePlayback();}catch(_){}
    const session=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{},selected=window.SBB_SELECTED_EVENT?.get?.()||null;
    // Score-card interactions are game scoped. If a selected media session exists but
    // Game Center has no event, treat ownership as lost rather than silently passing.
    return !clean(session.mediaKey)||!!selected;
  }
  async function waitForPlaybackQuiescence(timeoutMs=3500){
    const deadline=Date.now()+timeoutMs;let stableAt=0;
    while(Date.now()<deadline){
      const session=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{},engine=engineSnapshot();
      const stable=!engine.recovering&&!['selected','starting','buffering'].includes(clean(session.state).toLowerCase());
      if(stable){if(!stableAt)stableAt=Date.now();if(Date.now()-stableAt>=250)return true;}else stableAt=0;
      await sleep(100);
    }
    return false;
  }
  async function playbackInteractionMatrix(seed,dates){
    installProgressWatchdog();const h=hooks(),ps=window.SBB_PLAYBACK_SESSION;
    if(!h?.setScoreDate||!ps?.snapshot)return {available:false,result:'FAIL',reason:'Dev interaction hooks or playback session unavailable',target:PLAYBACK_TARGET,attempts:0,starts:0,fail:0,rows:[]};
    const saved={date:clean(h.scoreDate?.(),10),mediaKey:clean(h.currentMediaKey?.()),mode:clean(window.SBB_RESOURCE_MODE||'balanced'),session:ps.snapshot()},rng=seededRng(seed^0xa5a5a5a5);
    const mainThreadBefore=mainThreadGuard()?.snapshot?.()||{};
    const datePlan=seededShuffle([...new Set([...(dates||[]),...certificationDates(seed)])],rng),seenMedia=new Set(),seenGames=new Set(),leagueCounts={},qualityCounts={},rows=[];
    let dateSwitches=0;
    try{
      try{await Promise.resolve(h.setResourceMode?.('playback'));}catch(_){}
      for(const date of datePlan){
        if(rows.length>=PLAYBACK_TARGET)break;
        if(!(await requireResponsiveUi())){rows.push({ok:false,date,stage:'ui-thread',error:'main thread remained saturated before date interaction'});break;}
        try{if(clean(h.scoreDate?.(),10)!==date){await Promise.resolve(h.setScoreDate(date));dateSwitches++;await sleep(220);await yieldUi();}}catch(err){rows.push({ok:false,date,stage:'date',error:clean(err?.message||err)});continue;}
        let cards=await waitForCards();let perDate=0;
        while(cards.length&&rows.length<PLAYBACK_TARGET&&perDate<2){
          const candidate=choosePlaybackCard(cards,{seenMedia,seenGames,leagueCounts,qualityCounts,rng,date});if(!candidate)break;
          seenMedia.add(candidate.mediaKey);seenGames.add(candidate.gameKey);perDate++;
          const before=ps.snapshot(),v5Before=v5RuntimeSnapshot(),engineBefore=engineSnapshot(),started=now();let selection=null,progressResult=null,intent=null,error='';
          try{
            if(!(await requireResponsiveUi()))throw new Error('main thread remained saturated before playback click');
            candidate.card.click();
            await yieldUi();
            intent=await waitForV5Intent(v5Before.transactionId);
            if(!intent)throw new Error('score-card click did not create v5 playback intent');
            selection=await waitForSelection(before.selectionId);
            if(!selection){const stalled=v5RuntimeSnapshot();throw new Error(`v5 intent ${stalled.playbackState||'UNKNOWN'} did not reach media selection`);}
            progressResult=await waitForProgress({selectionId:selection.selectionId,mediaKey:selection.mediaKey,timeoutMs:PLAYBACK_CONFIRM_TIMEOUT_MS});
            await waitForPlaybackQuiescence(progressResult?.ok?1800:3200);
          }catch(err){error=clean(err?.message||err);}
          const v5After=v5RuntimeSnapshot(),final=progressResult?.session||ps.snapshot(),engineAfter=engineSnapshot(),engineResetsDelta=Math.max(0,n(engineAfter.resets)-n(engineBefore.resets)),engineIncidentsDelta=Math.max(0,n(engineAfter.incidents)-n(engineBefore.incidents)),gameCenterOwned=gameCenterOwnershipOk(),preflight=h.scoreMediaPreflight?.(candidate.editorialMediaKey)||{},scoreIntent=h.scoreIntentPlan?.()||{},recapIndex=h.recapIndex?.()||{};
          const primaryRejected=!!candidate.primaryRejected||!!preflight.primaryRejected||(candidate.editorialMediaKey&&clean(final.mediaKey||selection?.mediaKey)!==candidate.editorialMediaKey);
          const ok=!!progressResult?.ok&&String(final.invariant||'OK')==='OK'&&gameCenterOwned&&engineResetsDelta===0;
          leagueCounts[candidate.league]=n(leagueCounts[candidate.league])+1;qualityCounts[candidate.quality]=n(qualityCounts[candidate.quality])+1;
          rows.push({ok,date,league:candidate.league,quality:candidate.quality,gameKey:candidate.gameKey,candidateMediaKey:candidate.mediaKey,editorialMediaKey:candidate.editorialMediaKey,mediaKey:clean(final.mediaKey||selection?.mediaKey),readinessBefore:candidate.readinessBefore||'UNKNOWN',prewarmAttempted:!!preflight.attempted,prewarmResult:clean(preflight.result||'NOT_REQUIRED'),primaryRejected,provider:upper(final.provider),transport:upper(final.transport),elapsedMs:round(now()-started),firstProgressMs:progressResult?.snap?.firstProgressMs??null,fallbackHops:n(progressResult?.fallbackHops),invariant:clean(final.invariant||'OK'),gameCenterOwned,engineResetsDelta,engineIncidentsDelta,v5TransactionId:v5After.transactionId||intent?.transactionId||'',v5State:v5After.playbackState||'',v5Invariant:v5After.invariant||'',planCandidates:v5After.planCandidates,planAttempted:v5After.planAttempted,planRejected:v5After.planRejected,planExhausted:v5After.planExhausted,candidateIndex:v5After.candidateIndex,planBuildMs:round(n(scoreIntent?.last?.elapsedMs)),planYields:n(scoreIntent?.last?.yields),planMaxChunkMs:round(n(scoreIntent?.last?.maxChunkMs)),recapLookupMaxMs:round(n(recapIndex?.maxLookupMs)),error:error||(!progressResult?.ok?clean(progressResult?.reason||final.lastError||'no advancing media clock'):(!gameCenterOwned?'Game Center ownership lost during score playback':(engineResetsDelta?`playback engine reset ${engineResetsDelta} time(s) during interaction`:'')))});
          cards=visiblePlayableCards();
        }
      }
      if(rows.filter(x=>x.ok).length<PLAYBACK_MIN_STARTS){
        for(let i=0;i<PLAYBACK_TARGET&&rows.filter(x=>x.ok).length<PLAYBACK_MIN_STARTS;i++){
          if(!(await requireResponsiveUi())){rows.push({ok:false,date:clean(h.scoreDate?.(),10),stage:'ui-thread',error:'main thread remained saturated before fallback stress tune'});break;}
          const before=ps.snapshot();let moved=false;try{moved=await Promise.resolve(h.stressTuneNextGame?.());if(!moved)moved=await Promise.resolve(h.stressTuneNext?.());await yieldUi();}catch(_){}
          if(!moved)break;const selection=await waitForSelection(before.selectionId);if(!selection||seenMedia.has(clean(selection.mediaKey)))continue;seenMedia.add(clean(selection.mediaKey));const engineBefore=engineSnapshot(),started=now(),pr=await waitForProgress({selectionId:selection.selectionId,mediaKey:selection.mediaKey});await waitForPlaybackQuiescence(pr.ok?1800:3200);const final=pr.session||ps.snapshot(),league=upper(final.league||'UNKNOWN'),engineAfter=engineSnapshot(),engineResetsDelta=Math.max(0,n(engineAfter.resets)-n(engineBefore.resets)),engineIncidentsDelta=Math.max(0,n(engineAfter.incidents)-n(engineBefore.incidents)),gameCenterOwned=gameCenterOwnershipOk(),ok=!!pr.ok&&String(final.invariant||'OK')==='OK'&&gameCenterOwned&&engineResetsDelta===0;leagueCounts[league]=n(leagueCounts[league])+1;rows.push({ok,date:clean(h.scoreDate?.(),10),league,quality:'PROGRAM',gameKey:clean(final.eventKey),candidateMediaKey:clean(selection.mediaKey),mediaKey:clean(final.mediaKey),provider:upper(final.provider),transport:upper(final.transport),elapsedMs:round(now()-started),firstProgressMs:pr.snap?.firstProgressMs??null,fallbackHops:n(pr.fallbackHops),invariant:clean(final.invariant||'OK'),gameCenterOwned,engineResetsDelta,engineIncidentsDelta,error:ok?'':clean(pr.reason||(!gameCenterOwned?'Game Center ownership lost during program playback':(engineResetsDelta?'playback engine reset during program playback':'')))});
        }
      }
    }finally{
      try{if(saved.date)await Promise.resolve(h.setScoreDate(saved.date));}catch(_){}
      try{if(saved.mediaKey)await Promise.resolve(h.restoreMediaKey?.(saved.mediaKey));}catch(_){}
      try{await Promise.resolve(h.setResourceMode?.(saved.mode||'balanced'));}catch(_){}
    }
    const successful=rows.filter(x=>x.ok),fail=rows.filter(x=>!x.ok).length,leagues=[...new Set(successful.map(x=>x.league).filter(Boolean))],qualities=[...new Set(successful.map(x=>x.quality).filter(q=>q&&q!=='UNKNOWN'))],transports=[...new Set(successful.map(x=>x.transport).filter(Boolean))],providers=[...new Set(successful.map(x=>x.provider).filter(Boolean))],testedDates=[...new Set(successful.map(x=>x.date).filter(Boolean))],fallbacks=rows.reduce((a,x)=>a+n(x.fallbackHops),0),engineResets=rows.reduce((a,x)=>a+n(x.engineResetsDelta),0),engineIncidents=rows.reduce((a,x)=>a+n(x.engineIncidentsDelta),0),gameCenterOwnershipFailures=rows.filter(x=>x.gameCenterOwned===false).length,prewarmAttempts=rows.filter(x=>x.prewarmAttempted).length,primaryRejections=rows.filter(x=>x.primaryRejected).length,maxScorePlanMs=Math.max(0,...rows.map(x=>n(x.planBuildMs))),maxScorePlanChunkMs=Math.max(0,...rows.map(x=>n(x.planMaxChunkMs))),scorePlanYields=rows.reduce((a,x)=>a+n(x.planYields),0),maxRecapLookupMs=Math.max(0,...rows.map(x=>n(x.recapLookupMaxMs)));
    const result=successful.length>=PLAYBACK_MIN_STARTS&&fail===0&&engineResets===0&&gameCenterOwnershipFailures===0&&leagues.length>=2&&testedDates.length>=2?'PASS':(successful.length>=PLAYBACK_MIN_STARTS&&engineResets===0?'WARN':'FAIL');
    const scorePlayableCache=h.scorePlayableCache?.()||{};
    const mainThread=mainThreadGuard()?.delta?.(mainThreadBefore)||mainThreadGuard()?.snapshot?.()||{};
    return {available:true,result,target:PLAYBACK_TARGET,attempts:rows.length,starts:successful.length,fail,dateSwitches,leagues,qualities,transports,providers,dates:testedDates,fallbacks,engineResets,engineIncidents,gameCenterOwnershipFailures,prewarmAttempts,primaryRejections,maxScorePlanMs,maxScorePlanChunkMs,scorePlanYields,maxRecapLookupMs,scorePlayableCache,mainThread,uniqueMedia:seenMedia.size,p95FirstProgressMs:round(percentile(successful.map(x=>Number(x.firstProgressMs)).filter(Number.isFinite),95)),rows};
  }

  function workerLines(summary){return (summary?.workers||[]).map(w=>`${w.healthy?'PASS':'WARN'} ${w.name.padEnd(18)} phase=${w.phase} heartbeat=${w.heartbeatAgeSeconds}s progress=${w.progressAgeSeconds}s jobs/hr=${round(w.jobsPerHour)||0} busy=${round(w.busyPercent)||0}% wait=${round(w.providerWaitPercent)||0}%${w.current?` current=${w.current}`:''}${w.provider?` provider=${w.provider}`:''}`).join('\n')||'No worker telemetry returned.';}
  function sourceLines(summary){const rows=(summary?.sources||[]).filter(x=>x.active);return rows.slice(0,40).map(x=>`${x.league.padEnd(8)} ${x.kind.slice(0,18).padEnd(18)} items=${x.playlistItems} hydrated=${x.hydrated} assets=${x.assets} assigned=${x.assigned} orphaned=${x.orphaned} quarantined=${x.quarantined}${x.lastError?` ERROR=${x.lastError}`:''}`).join('\n')||'No source rows returned.';}
  function actionItems(report){
    const out=[],eff=report.efficiency?.metrics||{},gc=report.gameCenter||{},back=report.backendAfter?.summary||{},play=report.playback||{},ui=report.interactions?.gameCenterUi||{},arch=report.architecture||{};
    if(!arch.installed||!arch.adapterBound||arch.invariant!=='OK')out.push(`P0 V5 ARCHITECTURE: appStore=${arch.appStore?'YES':'NO'} orchestrator=${arch.orchestrator?'YES':'NO'} adapter=${arch.adapterBound?'YES':'NO'} invariant=${arch.invariant||'MISSING'}.`);
    const apiFails=(report.backendAfter?.probes||[]).filter(x=>!x.ok);if(apiFails.length)out.push(`P0 API HEALTH: ${apiFails.length} certification endpoint${apiFails.length===1?'':'s'} failed or timed out: ${apiFails.map(x=>x.path).join(', ')}.`);
    if(play.result==='FAIL'||play.fail>0)out.push(`P0 PLAYBACK: ${play.fail||0}/${play.attempts||0} active interactions failed; inspect PLAYBACK INTERACTION MATRIX and progress-watchdog evidence.`);
    if(n(play.engineResets)>0)out.push(`P0 PLAYBACK ENGINE: ${play.engineResets} global engine reset${play.engineResets===1?'':'s'} occurred during active interaction coverage. A local media failure must not destabilize the whole board.`);
    if(n(play.gameCenterOwnershipFailures)>0)out.push(`P0 GAME CENTER OWNERSHIP: ${play.gameCenterOwnershipFailures} playback interaction${play.gameCenterOwnershipFailures===1?'':'s'} lost the active game's event binding.`);
    if(n(play.mainThread?.criticalDelta)>0)out.push(`P0 UI THREAD: ${play.mainThread.criticalDelta} critical event-loop stall${play.mainThread.criticalDelta===1?'':'s'} occurred during active playback; max observed lag=${play.mainThread.maxLagMs||0}ms.`);
    if(play.result!=='FAIL'&&play.fallbacks>0)out.push(`P1 PLAYBACK RECOVERY: ${play.fallbacks} fallback hop${play.fallbacks===1?'':'s'} were required. Playback recovered, but the original asset/transport should be reviewed.`);
    if(gc.fail>0)out.push(`P1 GAME CENTER: ${gc.fail}/${gc.supported||gc.rows.length} supported seeded Game Centers failed.`);if(n(gc.unsupported)>0)out.push(`P2 GAME CENTER COVERAGE: ${gc.unsupported} sampled competition${gc.unsupported===1?' is':'s are'} intentionally unsupported and reported N/A.`);
    if(ui.fail>0)out.push(`P1 GAME CENTER UI: ${ui.fail}/${ui.attempted} view interactions failed.`);
    if(n(eff.api5xx)>0)out.push(`P0 FRONTEND API: ${eff.api5xx} HTTP 5xx responses occurred during navigation.`);
    if(n(eff.longTaskMax)>300)out.push(`P1 MAIN THREAD: longest task ${eff.longTaskMax}ms; inspect LONGEST TASKS / render reason and card helper breakdown.`);
    if(n(eff.domGrowthPct)>15)out.push(`P1 DOM: retained DOM grew ${eff.domGrowthPct}%; investigate duplicate render owners/listeners.`);
    if(back.configuredWorkers&&back.healthyWorkers<back.configuredWorkers)out.push(`P1 WORKERS: ${back.healthyWorkers}/${back.configuredWorkers} workers healthy.`);
    if(n(back.catalog?.indexPassPending)>0)out.push(`P2 DISCOVERY: ${back.catalog.indexPassPending} games remain Index Pass Pending at Discovery v${back.discoveryVersion}.`);
    if(back.databaseAudit?.complete&&back.databaseAudit.total>0&&back.databaseAudit.checked<back.databaseAudit.total)out.push(`P1 DATABASE AUDIT: marked complete at ${back.databaseAudit.checked}/${back.databaseAudit.total}; stale audit state requires rebase.`);
    if(!out.length)out.push('No critical actionable failures detected. Repeat with the recorded seed when comparing releases; use a fresh seed for additional coverage.');return out;
  }
  function overall(report){
    const eff=report.efficiency?.result||'WARN',gc=report.gameCenter||{},back=report.backendAfter?.summary||{},play=report.playback||{},ui=report.interactions?.gameCenterUi||{},arch=report.architecture||{},apiFails=(report.backendAfter?.probes||[]).filter(x=>!x.ok).length;
    if(!arch.installed||!arch.adapterBound||arch.invariant!=='OK'||apiFails||eff==='FAIL'||play.result==='FAIL'||play.fail>0||n(play.engineResets)>0||n(play.gameCenterOwnershipFailures)>0||n(play.mainThread?.criticalDelta)>0||gc.fail>Math.max(1,Math.floor((gc.supported||gc.rows?.length||0)*.25))||ui.fail>0)return 'FAIL';
    if(eff==='WARN'||play.result==='WARN'||play.fallbacks>0||gc.fail>0||(back.configuredWorkers&&back.healthyWorkers<back.configuredWorkers))return 'WARN';return 'PASS';
  }

  function reportText(r){
    if(!r)return 'No comprehensive certification report yet.';
    const b=r.backendAfter?.summary||{},d=r.backendDelta||{},gc=r.gameCenter||{},p=r.playback||{},eff=r.efficiency||{},ui=r.interactions?.gameCenterUi||{},w=r.progressWatchdog||{},arch=r.architecture||{};
    const lines=[
      `SPORTS BIG BOARD v${RELEASE} — COMPREHENSIVE SITE CERTIFICATION`,
      `RESULT=${r.result}  ELAPSED=${round(r.elapsedMs/1000)}s  CAPTURED=${r.finishedAt}  SEED=${r.seed}`,
      `CERT_SCHEMA=${VERSION}  FRONTEND=${window.SBB_CORE?.version||'UNKNOWN'}  BACKEND=${b.backendVersion||'UNKNOWN'}  DISCOVERY=v${b.discoveryVersion||0}  MODE=${String(b.workMode||'unknown').toUpperCase()}`,
      '',
      '==================== 0. V5 UNIFIED RUNTIME ARCHITECTURE ====================',
      `APP_STORE=${arch.appStore?'YES':'NO'} schema=${arch.schema||'—'} ORCHESTRATOR=${arch.orchestrator?'YES':'NO'} ADAPTER_BOUND=${arch.adapterBound?'YES':'NO'} invariant=${arch.invariant||'MISSING'}`,
      `TRANSACTION state=${arch.playbackState||'IDLE'} id=${arch.transactionId||'—'} event=${arch.eventKey||'—'} selected=${arch.selectedEventKey||'—'} owned=${arch.owned===false?'NO':'YES'} plan=${arch.planAttempted||0}/${arch.planCandidates||0} rejected=${arch.planRejected||0} exhausted=${arch.planExhausted?'YES':'NO'}`,
      `APP_STORE dispatches=${arch.storeHealth?.dispatches||0} commits=${arch.storeHealth?.commits||0} noops=${arch.storeHealth?.noops||0} snapshots=${arch.storeHealth?.snapshots||0} maxDispatch=${round(arch.storeHealth?.maxDispatchMs)||0}ms maxEmit=${round(arch.storeHealth?.maxEmitMs)||0}ms`,
      '',
      '==================== 1. RELEASE / API HEALTH ====================',
      ...r.backendAfter.probes.map(x=>`${x.ok?'PASS':'FAIL'} ${x.path.padEnd(46)} HTTP=${x.status} ${x.elapsedMs}ms bytes=${x.bytes}${x.error?` error=${x.error}`:''}`),
      '',
      '==================== 2. FRONTEND EFFICIENCY ====================',
      eff.text||'Efficiency certification unavailable.',
      '',
      '==================== 3. WHOLE-SITE INTERACTION COVERAGE ====================',
      `SEED ${r.seed} • replay with SBB_SITE_CERTIFICATION.runFull({seed:${r.seed}})`,
      `NAV dateSwitches=${p.dateSwitches||0} efficiencyDateSwitches=${n(eff.metrics?.dateSwitches)} historyNav=${n(eff.metrics?.historyNav)} filterSwitches=${n(eff.metrics?.filterSwitches)}`,
      `GAME_CENTER_UI available=${ui.available?'YES':'NO'} attempted=${ui.attempted||0} pass=${ui.pass||0} fail=${ui.fail||0} sectionSwitches=${ui.sections||0}`,
      ...(ui.rows||[]).map(x=>`${x.ok?'PASS':'FAIL'} ${x.label} time=${x.elapsedMs}ms sections=${x.sections||0}${x.error?` ERROR=${x.error}`:''}`),
      '',
      '==================== 4. ACTIVE PLAYBACK INTERACTION MATRIX ====================',
      `PLAYBACK_MATRIX result=${p.result||'FAIL'} target=${p.target||PLAYBACK_TARGET} attempts=${p.attempts||0} starts=${p.starts||0} fail=${p.fail||0} uniqueMedia=${p.uniqueMedia||0} fallbacks=${p.fallbacks||0} prewarmAttempts=${p.prewarmAttempts||0} primaryRejected=${p.primaryRejections||0} engineResets=${p.engineResets||0} engineIncidents=${p.engineIncidents||0} gcOwnershipFailures=${p.gameCenterOwnershipFailures||0} p95FirstProgress=${p.p95FirstProgressMs??'N/A'}ms planBuildMax=${p.maxScorePlanMs||0}ms planChunkMax=${p.maxScorePlanChunkMs||0}ms planYields=${p.scorePlanYields||0} recapLookupMax=${p.maxRecapLookupMs||0}ms`,
      `DIVERSITY leagues=${(p.leagues||[]).join(',')||'NONE'} qualities=${(p.qualities||[]).join(',')||'NONE'} transports=${(p.transports||[]).join(',')||'NONE'} providers=${(p.providers||[]).join(',')||'NONE'} dates=${(p.dates||[]).join(',')||'NONE'}`,
      `SCORE_PLAYABLE_CACHE size=${p.scorePlayableCache?.size||0} hits=${p.scorePlayableCache?.hits||0} misses=${p.scorePlayableCache?.misses||0} evictions=${p.scorePlayableCache?.evictions||0} ttl=${p.scorePlayableCache?.ttlMs||0}ms`,
      `UI_THREAD warnings=${p.mainThread?.warningDelta||0} critical=${p.mainThread?.criticalDelta||0} maxLag=${p.mainThread?.maxLagMs||0}ms lastLag=${p.mainThread?.lastLagMs||0}ms`,
      ...(p.rows||[]).map((x,i)=>`${x.ok?'PASS':'FAIL'} #${String(i+1).padStart(2,'0')} ${x.date||'—'} ${x.league||'—'} ${x.quality||'—'} ${x.provider||'—'}/${x.transport||'—'} readinessBefore=${x.readinessBefore||'UNKNOWN'} prewarm=${x.prewarmAttempted?'YES':'NO'}:${x.prewarmResult||'NOT_REQUIRED'} primaryRejected=${x.primaryRejected?'YES':'NO'} progress=${x.firstProgressMs??'N/A'}ms fallbackHops=${x.fallbackHops||0} plan=${x.planAttempted||0}/${x.planCandidates||0} rejected=${x.planRejected||0} exhausted=${x.planExhausted?'YES':'NO'} planBuild=${x.planBuildMs||0}ms/y${x.planYields||0} engineReset+${x.engineResetsDelta||0} gcOwned=${x.gameCenterOwned===false?'NO':'YES'} invariant=${x.invariant||'—'} v5=${x.v5State||'—'} tx=${x.v5TransactionId||'—'} media=${x.mediaKey||x.candidateMediaKey||'—'}${x.error?` ERROR=${x.error}`:''}`),
      '',
      '==================== 5. DATABASE / DISCOVERY ====================',
      `CATALOG games=${b.catalog?.games||0} verifiedAssets=${b.catalog?.verifiedAssets||0} coverageComplete=${b.catalog?.coverageComplete||0} noVerifiedMedia=${b.catalog?.noVerifiedMedia||0}`,
      `DISCOVERY indexPassPending=${b.catalog?.indexPassPending||0} sourceExhaustedEmpty=${b.catalog?.sourceExhaustedEmpty||0} queuePending=${b.queue?.pending||0} queueReady=${b.queue?.ready||0} dueCoverageGaps=${b.queue?.dueCoverageGaps||0}`,
      `DATABASE_AUDIT state=${b.databaseAudit?.running?'RUNNING':(b.databaseAudit?.complete?'COMPLETE':'READY')} checked=${b.databaseAudit?.checked||0}/${b.databaseAudit?.total||0} issues=${JSON.stringify(b.databaseAudit?.issues||{})}${b.databaseAudit?.lastError?` error=${b.databaseAudit.lastError}`:''}`,
      `SILVER collections=${b.silver?.collections||0} links=${b.silver?.links||0} uniqueAssets=${b.silver?.uniqueAssets||0} suspicious=${b.silver?.suspicious||0}`,
      `CERT_WINDOW_DELTA auditChecked=${d.auditChecked||0} catalogGames=${d.catalogGames||0} verifiedAssets=${d.verifiedAssets||0} sourceAssets=${d.sourceAssets||0} sourceAssigned=${d.sourceAssigned||0} playlistItems=${d.playlistItems||0} indexPassPending=${d.indexPassPending||0} coverageComplete=${d.coverageComplete||0}`,
      '',
      '==================== 6. BACKGROUND WORKERS ====================',
      `WORKERS healthy=${b.healthyWorkers||0}/${b.configuredWorkers||0} playbackSuspended=${b.playbackSuspended?'YES':'NO'} searchSuspended=${b.searchSuspended?'YES':'NO'}`,
      workerLines(b),
      '',
      '==================== 7. CRAWL / SOURCE INVENTORY ====================',
      `YOUTUBE_SEARCH_BUDGET ${JSON.stringify(b.youtubeSearchBudget||{})}`,
      `PLAYLIST_CRAWLER ${JSON.stringify(b.playlistCrawler||{})}`,
      `SCHEDULE_SYNC ${JSON.stringify(b.scheduleSync||{})}`,
      sourceLines(b),
      '',
      '==================== 8. GAME CENTER CENSUS ====================',
      `GAME_CENTER sampled=${gc.rows?.length||0} supported=${gc.supported||0} pass=${gc.pass||0} fail=${gc.fail||0} unsupported=${gc.unsupported||0} p95=${gc.p95Ms??'N/A'}ms max=${gc.maxMs??'N/A'}ms`,
      ...(gc.rows||[]).map(x=>`${x.unsupported?'N/A':(x.ok?'PASS':'FAIL')} ${x.label} id=${x.eventId||'—'} time=${x.elapsedMs}ms payload=${round(x.bytes/1024)||0}KB complete=${x.coverageComplete?'YES':'NO'} quality=${x.completenessReason||'—'} innings=${x.innings} periods=${x.periods} timeline=${x.timeline} players=${x.playerSections} winprob=${x.winProbability}${x.unsupported?` UNSUPPORTED=${x.unsupportedReason||'NO_PROVIDER'}`:(x.error?` ERROR=${x.error}`:'')}`),
      '',
      'DAY-STATE PROBES',
      ...(gc.dayProbes||[]).map(x=>`${x.ok?'PASS':'FAIL'} ${x.path} HTTP=${x.status} ${x.elapsedMs}ms games=${x.games}`),
      '',
      '==================== 9. PLAYBACK PROGRESS / RECOVERY ====================',
      `PROGRESS_WATCHDOG installed=${w.installed?'YES':'NO'} confirmed=${w.confirmed?'YES':'NO'} firstProgress=${w.firstProgressMs??'N/A'}ms softKicks=${w.softKicks||0} recoveries=${w.recoveries||0} timeouts=${w.timeouts||0} reason=${w.lastReason||'—'}`,
      ...(w.history||[]).slice(-12).map(x=>`${x.type.toUpperCase()} selection=${x.selectionId||0} media=${x.mediaKey||'—'}${x.clock!=null?` clock=${x.clock}`:''}${x.firstProgressMs!=null?` firstProgress=${x.firstProgressMs}ms`:''}`),
      '',
      '==================== 10. ACTION ITEMS ====================',
      ...r.actions.map((x,i)=>`${i+1}. ${x}`),
      '',
      '==================== 11. RAW BACKEND COUNTERS ====================',
      `ASSOCIATIONS ${JSON.stringify(b.associations||{})}`,
      `PROVIDER_CONCURRENCY ${JSON.stringify(b.providers||{})}`,
      '',
      `END COMPREHENSIVE CERTIFICATION • RESULT=${r.result} • SEED=${r.seed}`,
    ];
    return lines.filter((x,i)=>x!==''||lines[i-1]!=='').join('\n');
  }

  async function runFull(options={}){
    if(state.running)return state.lastReport;
    const launch=$('launchScreen');if(launch&&!launch.classList.contains('hidden')&&getComputedStyle(launch).display!=='none')throw new Error('Start Sports Big Board before running Comprehensive Certification.');
    const seed=normalizeSeed(options?.seed);state.running=true;renderCard();const started=now();installProgressWatchdog();
    try{
      const backendBefore=await backendSnapshot();
      let efficiency=null;try{efficiency=await window.SBB_EFFICIENCY?.runAutoTest?.();}catch(err){efficiency={result:'FAIL',text:`Efficiency test failed to execute: ${clean(err?.message||err)}`,metrics:{}};}
      const gameCenter=await gameCenterCensus(seed);
      const gameCenterUi=await gameCenterUiExercise(gameCenter);
      const playback=await playbackInteractionMatrix(seed,gameCenter.dates);
      const backendAfter=await backendSnapshot();
      const report={version:VERSION,release:RELEASE,seed,startedAt:new Date(Date.now()-(now()-started)).toISOString(),finishedAt:new Date().toISOString(),elapsedMs:round(now()-started),architecture:v5RuntimeSnapshot(),backendBefore,backendAfter,backendDelta:backendDelta(backendBefore,backendAfter),efficiency,interactions:{gameCenterUi},gameCenter,playback,progressWatchdog:progressPublic()};
      report.actions=actionItems(report);report.result=overall(report);report.text=reportText(report);state.lastReport=report;
      try{localStorage.setItem('sbb.site-certification.last',JSON.stringify(report));}catch(_){}
      try{window.dispatchEvent(new CustomEvent('sbb:site-certification',{detail:report}));}catch(_){}
      return report;
    }finally{state.running=false;renderCard();}
  }

  function injectStyle(){if($('sbbSiteCertificationStyle'))return;const s=document.createElement('style');s.id='sbbSiteCertificationStyle';s.textContent=`#sbbSiteCertificationCard .sitecert-actions{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}#sbbSiteCertificationOutput{max-height:480px;overflow:auto;white-space:pre-wrap;font:10px/1.42 ui-monospace,SFMono-Regular,Consolas,monospace;background:#080d13;border:1px solid #263442;border-radius:7px;padding:9px}#sbbSiteCertificationGrade{font-weight:900;letter-spacing:.08em}#sbbSiteCertificationGrade.PASS{color:#4ade80}#sbbSiteCertificationGrade.WARN{color:#fbbf24}#sbbSiteCertificationGrade.FAIL{color:#fb7185}`;document.head.appendChild(s);}
  function ensureCard(){
    if($('sbbSiteCertificationCard')){state.cardInstalled=true;return true;}const anchor=$('sbbEfficiencyCard')||document.querySelector('.settings-card:last-of-type');if(!anchor)return false;injectStyle();
    const card=document.createElement('div');card.id='sbbSiteCertificationCard';card.className='settings-card hidden';card.innerHTML=`<div class="eff-head"><div><div class="settings-card-title">COMPREHENSIVE SITE CERTIFICATION</div><small>Navigation • rendering • APIs • Game Center • active playback • recovery • database • crawlers • workers</small></div><span id="sbbSiteCertificationGrade">IDLE</span></div><div class="sitecert-actions"><button id="sbbSiteCertificationRun" class="settings-save-btn" type="button">RUN COMPREHENSIVE TEST</button><button id="sbbSiteCertificationCopy" type="button">COPY FULL REPORT</button><button id="sbbSiteCertificationDownload" type="button">DOWNLOAD REPORT</button></div><pre id="sbbSiteCertificationOutput">Run a seeded, reproducible whole-site certification. Playback is actively exercised; the test does not target any named game.</pre>`;anchor.after(card);
    $('sbbSiteCertificationRun').onclick=()=>runFull().catch(err=>{state.lastReport={result:'FAIL',text:`COMPREHENSIVE TEST FAILED TO EXECUTE\n${clean(err?.stack||err)}`};renderCard();});
    $('sbbSiteCertificationCopy').onclick=async()=>{try{await navigator.clipboard.writeText(state.lastReport?.text||'No report yet.');}catch(_){}};
    $('sbbSiteCertificationDownload').onclick=()=>{const text=state.lastReport?.text||'No report yet.';const blob=new Blob([text],{type:'text/plain'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`sports-big-board-comprehensive-${new Date().toISOString().replace(/[:.]/g,'-')}.txt`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
    const apply=()=>card.classList.toggle('hidden',!window.SBB_DEV_MODE?.isEnabled?.());apply();window.addEventListener('sbb:dev-mode',apply);state.cardInstalled=true;renderCard();return true;
  }
  function renderCard(){if(!state.cardInstalled&&!ensureCard())return;const grade=$('sbbSiteCertificationGrade'),out=$('sbbSiteCertificationOutput'),run=$('sbbSiteCertificationRun');if(!grade||!out)return;if(run)run.disabled=state.running;if(state.running){grade.className='WARN';grade.textContent='RUNNING';out.textContent='Comprehensive certification in progress…\n1) backend/API snapshot\n2) efficiency navigation + performance\n3) seeded Game Center census + UI\n4) active cross-date playback matrix\n5) clock-progress/recovery validation\n6) backend/crawl delta + restoration';return;}grade.className=state.lastReport?.result||'';grade.textContent=state.lastReport?.result||'IDLE';out.textContent=state.lastReport?.text||'Run a seeded, reproducible whole-site certification.';}
  function boot(){installProgressWatchdog();ensureCard();setInterval(ensureCard,1500);}
  window.SBB_SITE_CERTIFICATION=Object.freeze({version:VERSION,release:RELEASE,runFull,snapshot:()=>({version:VERSION,release:RELEASE,running:state.running,lastReport:state.lastReport,progress:progressPublic()}),reportText:()=>state.lastReport?.text||'No comprehensive certification report yet.',certificationDates,gameCenterSupport});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();

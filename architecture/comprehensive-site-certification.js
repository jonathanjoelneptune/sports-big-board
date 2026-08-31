/* Sports Big Board v4.7.20 — Comprehensive Site Certification.
   One-stop operational certification combining frontend efficiency, backend/catalog
   health, background workers/crawlers, Game Center resolution, and live playback
   buffering observations into one verbose pasteable report.
*/
(() => {
  'use strict';
  if (window.SBB_SITE_CERTIFICATION?.version === '1.0') return;

  const VERSION='1.0';
  const RELEASE=String(window.SBB_RELEASE_VERSION||window.SBB_CORE?.version||'4.7.20');
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
      associations:c.associations||{},playlistCrawler:c.playlistCrawler||{},scheduleSync:c.scheduleSync||src.scheduleSync||{},providers:c.providerConcurrency||{},youtubeSearchBudget:c.youtubeSearchBudget||{},youtubeGateway:c.youtubeGateway||{},
      sources:sourceRows,
    };
  }

  async function backendSnapshot(){
    const probes=await Promise.all([
      fetchJson('/api/status',{timeoutMs:6000}),
      fetchJson('/api/history/worker-console?limit=320',{timeoutMs:8000}),
      fetchJson('/api/history/audit?limit=1&offset=0',{timeoutMs:10000}),
      fetchJson('/api/history/catalog/collections?limit=1&offset=0',{timeoutMs:10000}),
      fetchJson('/api/history/media-sources',{timeoutMs:10000}),
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
    return {
      auditChecked:n(b.databaseAudit?.checked)-n(a.databaseAudit?.checked),catalogGames:n(b.catalog?.games)-n(a.catalog?.games),verifiedAssets:n(b.catalog?.verifiedAssets)-n(a.catalog?.verifiedAssets),
      sourceAssets:sb.assets-sa.assets,sourceAssigned:sb.assigned-sa.assigned,sourceOrphaned:sb.orphaned-sa.orphaned,playlistItems:sb.playlistItems-sa.playlistItems,
      indexPassPending:n(b.catalog?.indexPassPending)-n(a.catalog?.indexPassPending),coverageComplete:n(b.catalog?.coverageComplete)-n(a.catalog?.coverageComplete),
    };
  }

  function eventTeams(event){
    const parts=Array.isArray(event?.participants)?event.participants:[];
    const away=event?.awayTeam||event?.away||parts.find(x=>x?.side==='away')||parts[0]||{};
    const home=event?.homeTeam||event?.home||parts.find(x=>x?.side==='home')||parts[1]||{};
    const name=x=>clean(x?.displayName||x?.name||x?.shortName||x?.abbreviation||x);
    return {away:name(away),home:name(home)};
  }
  function eventLabel(event,league){const t=eventTeams(event);return `${league} ${t.away||'?'} @ ${t.home||'?'}`;}
  function finalish(event){return /final|finished|completed|complete|post/i.test(clean(event?.status||event?.state?.report||event?.state?.description));}

  async function dayState(date){return fetchJson(`/api/day-state?date=${encodeURIComponent(date)}`,{timeoutMs:9000});}
  function eventsFromDay(payload){
    const rows=[];const map=payload?.scoreRowsByLeague||payload?.scoreRows||{};
    if(map&&typeof map==='object'&&!Array.isArray(map))for(const [league,events] of Object.entries(map))for(const event of events||[])rows.push({...event,competitionId:event.competitionId||league,__sbbLeague:league,__sbbDate:clean(event.date||event.gameDate||payload?.date).slice(0,10)});
    return rows;
  }
  async function gameCenterCandidates(){
    const dates=[localDate(0),localDate(-1),'2026-08-29','2026-08-28','2026-08-30'];
    const days=[];for(const date of [...new Set(dates)])days.push(await dayState(date));
    let events=days.filter(x=>x.ok).flatMap(x=>eventsFromDay(x.data));
    const usc=events.find(e=>{const s=JSON.stringify(e).toLowerCase();return upper(e.competitionId||e.__sbbLeague)==='CFB'&&s.includes('usc')&&(s.includes('san jose')||s.includes('sjs'));});
    const selected=[];if(usc)selected.push(usc);
    for(const league of ['MLB','CFB','NFL','NBA','NHL','MLS','EPL']){
      for(const e of events.filter(x=>upper(x.competitionId||x.__sbbLeague)===league&&finalish(x)).slice(0,league==='MLB'?3:2))if(!selected.includes(e))selected.push(e);
    }
    return {days,events,candidates:selected.slice(0,14),uscFound:!!usc};
  }

  async function probeGameCenter(event,index){
    const league=upper(event.competitionId||event.__sbbLeague||event.league);const label=eventLabel(event,league);const controller=new AbortController();
    const hardMs=7500;const timer=setTimeout(()=>controller.abort(new DOMException('Certification hard timeout','TimeoutError')),hardMs);const started=now();
    try{
      const gc=await window.SBB_GAME_CENTER?.get?.(event,{force:index===0,signal:controller.signal,timeoutMs:6500});
      const elapsedMs=round(now()-started),bytes=jsonBytes(gc),board=gc?.scoreboard||{};
      return {label,league,eventId:clean(event.eventId||event.scoreEventId||event.gamePk||event.id),ok:!!gc,elapsedMs,bytes,coverageComplete:gc?.coverage?.complete!==false,quality:clean(gc?.quality?.level),partial:!!gc?.partial,innings:(board.innings||[]).length,periods:(board.periods||[]).length,timeline:(gc?.timeline||[]).length,scoringPlays:(gc?.scoringPlays||[]).length,playerSections:(gc?.playerStatSections||[]).length,winProbability:(gc?.winProbability||board.winProbability||[]).length,error:''};
    }catch(err){return {label,league,eventId:clean(event.eventId||event.scoreEventId||event.gamePk||event.id),ok:false,elapsedMs:round(now()-started),bytes:0,coverageComplete:false,quality:'',partial:false,innings:0,periods:0,timeline:0,scoringPlays:0,playerSections:0,winProbability:0,error:`${clean(err?.name)}: ${clean(err?.message||err)}`};}
    finally{clearTimeout(timer);}
  }

  async function gameCenterCensus(){
    const c=await gameCenterCandidates(),rows=[];
    for(let i=0;i<c.candidates.length;i++){rows.push(await probeGameCenter(c.candidates[i],i));await sleep(80);}
    return {uscFound:c.uscFound,dayProbes:c.days.map(x=>({path:x.path,ok:x.ok,status:x.status,elapsedMs:x.elapsedMs,games:n(x.data?.summary?.games||eventsFromDay(x.data).length)})),rows,pass:rows.filter(x=>x.ok).length,fail:rows.filter(x=>!x.ok).length,p95Ms:round(percentile(rows.filter(x=>x.ok).map(x=>x.elapsedMs),95)),maxMs:round(Math.max(0,...rows.map(x=>n(x.elapsedMs))))};
  }

  async function playbackObservation(observeMs=12000){
    const ps=window.SBB_PLAYBACK_SESSION;if(!ps?.snapshot)return {active:false,reason:'playback-session-unavailable'};
    const start=ps.snapshot();const events=[];let off=()=>{};
    try{off=ps.subscribe?.(snap=>events.push({at:performance.now(),state:snap.state,stallCount:n(snap.stallCount),stallTotalMs:n(snap.stallTotalMs),failureCount:n(snap.failureCount),firstFrameMs:snap.firstFrameMs,invariant:snap.invariant,mediaKey:snap.mediaKey}))||(()=>{});}catch(_){}
    const active=/playing|buffering|starting|selected/i.test(clean(start.state));
    if(active)await sleep(observeMs);else await sleep(800);
    try{off();}catch(_){}
    const end=ps.snapshot();const elapsed=active?observeMs:0;const stallDelta=Math.max(0,n(end.stallTotalMs)-n(start.stallTotalMs));const countDelta=Math.max(0,n(end.stallCount)-n(start.stallCount));const failureDelta=Math.max(0,n(end.failureCount)-n(start.failureCount));
    return {active,startState:start.state,endState:end.state,mediaKey:end.mediaKey||start.mediaKey,league:end.league||start.league,transport:end.transport||start.transport,provider:end.provider||start.provider,firstFrameMs:end.firstFrameMs??start.firstFrameMs,stallCountDelta:countDelta,stallMsDelta:stallDelta,bufferRatePct:elapsed?pct(elapsed,stallDelta):null,failureDelta,invariant:end.invariant||start.invariant,observedEvents:events.length,reason:active?'':'No active video during certification; playback metrics are passive/NA.'};
  }

  function workerLines(summary){return (summary?.workers||[]).map(w=>`${w.healthy?'PASS':'WARN'} ${w.name.padEnd(18)} phase=${w.phase} heartbeat=${w.heartbeatAgeSeconds}s progress=${w.progressAgeSeconds}s jobs/hr=${round(w.jobsPerHour)||0} busy=${round(w.busyPercent)||0}% wait=${round(w.providerWaitPercent)||0}%${w.current?` current=${w.current}`:''}${w.provider?` provider=${w.provider}`:''}`).join('\n')||'No worker telemetry returned.';}
  function sourceLines(summary){const rows=(summary?.sources||[]).filter(x=>x.active);return rows.slice(0,40).map(x=>`${x.league.padEnd(8)} ${x.kind.slice(0,18).padEnd(18)} items=${x.playlistItems} hydrated=${x.hydrated} assets=${x.assets} assigned=${x.assigned} orphaned=${x.orphaned} quarantined=${x.quarantined}${x.lastError?` ERROR=${x.lastError}`:''}`).join('\n')||'No source rows returned.';}

  function actionItems(report){
    const out=[],eff=report.efficiency?.metrics||{},gc=report.gameCenter||{},back=report.backendAfter?.summary||{},play=report.playback||{};
    const usc=gc.rows?.find(x=>x.league==='CFB'&&/USC/i.test(x.label||''));
    if(usc&&!usc.ok)out.push(`P0 GAME CENTER: USC probe failed in ${usc.elapsedMs}ms — ${usc.error}. Inspect canonical ESPN event ID, pending preparation loop, and provider summary fetch.`);
    if(gc.fail>0)out.push(`P1 GAME CENTER: ${gc.fail}/${gc.rows.length} sampled Game Centers failed. Use the per-game table below to distinguish missing identity from provider timeout.`);
    if(n(eff.api5xx)>0)out.push(`P0 API: ${eff.api5xx} HTTP 5xx responses occurred during navigation.`);
    if(n(eff.longTaskMax)>300)out.push(`P1 MAIN THREAD: longest task ${eff.longTaskMax}ms; inspect LONGEST TASKS / render reason and card helper breakdown.`);
    if(n(eff.domGrowthPct)>15)out.push(`P1 DOM: retained DOM grew ${eff.domGrowthPct}%; investigate duplicate render owners/listeners.`);
    if(back.configuredWorkers&&back.healthyWorkers<back.configuredWorkers)out.push(`P1 WORKERS: ${back.healthyWorkers}/${back.configuredWorkers} workers healthy.`);
    if(n(back.catalog?.indexPassPending)>0)out.push(`P2 DISCOVERY: ${back.catalog.indexPassPending} games remain Index Pass Pending at Discovery v${back.discoveryVersion}. Track jobs/hour and pending delta across repeated certifications.`);
    if(back.databaseAudit?.complete&&back.databaseAudit.total>0&&back.databaseAudit.checked<back.databaseAudit.total)out.push(`P1 DATABASE AUDIT: marked complete at ${back.databaseAudit.checked}/${back.databaseAudit.total}; stale audit state requires rebase.`);
    if(play.active&&n(play.bufferRatePct)>10)out.push(`P1 PLAYBACK: observed buffering ratio ${play.bufferRatePct}% over ${Math.round(12)}s.`);
    if(play.failureDelta>0||String(play.invariant||'OK')!=='OK')out.push(`P0 PLAYBACK: failures=${play.failureDelta}, invariant=${play.invariant}.`);
    if(!out.length)out.push('No critical actionable failures detected in this certification window. Continue trending repeated reports for crawl throughput and archive completion.');
    return out;
  }

  function overall(report){
    const eff=report.efficiency?.result||'WARN',gc=report.gameCenter||{},back=report.backendAfter?.summary||{},play=report.playback||{},usc=gc.rows?.find(x=>x.league==='CFB'&&/USC/i.test(x.label||''));
    if(eff==='FAIL'||gc.fail>Math.max(1,Math.floor((gc.rows?.length||0)*.25))||(usc&&!usc.ok)||play.failureDelta>0||String(play.invariant||'OK')!=='OK')return 'FAIL';
    if(eff==='WARN'||gc.fail>0||(back.configuredWorkers&&back.healthyWorkers<back.configuredWorkers))return 'WARN';
    return 'PASS';
  }

  function reportText(r){
    if(!r)return 'No comprehensive certification report yet.';
    const b=r.backendAfter?.summary||{},d=r.backendDelta||{},gc=r.gameCenter||{},p=r.playback||{},eff=r.efficiency||{};
    const lines=[
      `SPORTS BIG BOARD v${RELEASE} — COMPREHENSIVE SITE CERTIFICATION`,
      `RESULT=${r.result}  ELAPSED=${round(r.elapsedMs/1000)}s  CAPTURED=${r.finishedAt}`,
      `CERT_SCHEMA=${VERSION}  FRONTEND=${window.SBB_CORE?.version||'UNKNOWN'}  BACKEND=${b.backendVersion||'UNKNOWN'}  DISCOVERY=v${b.discoveryVersion||0}  MODE=${String(b.workMode||'unknown').toUpperCase()}`,
      '',
      '==================== 1. RELEASE / API HEALTH ====================',
      ...r.backendAfter.probes.map(x=>`${x.ok?'PASS':'FAIL'} ${x.path.padEnd(46)} HTTP=${x.status} ${x.elapsedMs}ms bytes=${x.bytes}${x.error?` error=${x.error}`:''}`),
      '',
      '==================== 2. FRONTEND EFFICIENCY ====================',
      eff.text||'Efficiency certification unavailable.',
      '',
      '==================== 3. DATABASE / DISCOVERY ====================',
      `CATALOG games=${b.catalog?.games||0} verifiedAssets=${b.catalog?.verifiedAssets||0} coverageComplete=${b.catalog?.coverageComplete||0} noVerifiedMedia=${b.catalog?.noVerifiedMedia||0}`,
      `DISCOVERY indexPassPending=${b.catalog?.indexPassPending||0} sourceExhaustedEmpty=${b.catalog?.sourceExhaustedEmpty||0} queuePending=${b.queue?.pending||0} queueReady=${b.queue?.ready||0} dueCoverageGaps=${b.queue?.dueCoverageGaps||0}`,
      `DATABASE_AUDIT state=${b.databaseAudit?.running?'RUNNING':(b.databaseAudit?.complete?'COMPLETE':'READY')} checked=${b.databaseAudit?.checked||0}/${b.databaseAudit?.total||0} issues=${JSON.stringify(b.databaseAudit?.issues||{})}${b.databaseAudit?.lastError?` error=${b.databaseAudit.lastError}`:''}`,
      `SILVER collections=${b.silver?.collections||0} links=${b.silver?.links||0} uniqueAssets=${b.silver?.uniqueAssets||0} suspicious=${b.silver?.suspicious||0}`,
      `CERT_WINDOW_DELTA auditChecked=${d.auditChecked||0} catalogGames=${d.catalogGames||0} verifiedAssets=${d.verifiedAssets||0} sourceAssets=${d.sourceAssets||0} sourceAssigned=${d.sourceAssigned||0} playlistItems=${d.playlistItems||0} indexPassPending=${d.indexPassPending||0} coverageComplete=${d.coverageComplete||0}`,
      '',
      '==================== 4. BACKGROUND WORKERS ====================',
      `WORKERS healthy=${b.healthyWorkers||0}/${b.configuredWorkers||0} playbackSuspended=${b.playbackSuspended?'YES':'NO'} searchSuspended=${b.searchSuspended?'YES':'NO'}`,
      workerLines(b),
      '',
      '==================== 5. CRAWL / SOURCE INVENTORY ====================',
      `YOUTUBE_SEARCH_BUDGET ${JSON.stringify(b.youtubeSearchBudget||{})}`,
      `PLAYLIST_CRAWLER ${JSON.stringify(b.playlistCrawler||{})}`,
      `SCHEDULE_SYNC ${JSON.stringify(b.scheduleSync||{})}`,
      sourceLines(b),
      '',
      '==================== 6. GAME CENTER CENSUS ====================',
      `GAME_CENTER sampled=${gc.rows?.length||0} pass=${gc.pass||0} fail=${gc.fail||0} p95=${gc.p95Ms??'N/A'}ms max=${gc.maxMs??'N/A'}ms USC_EVENT_FOUND=${gc.uscFound?'YES':'NO'}`,
      ...(gc.rows||[]).map(x=>`${x.ok?'PASS':'FAIL'} ${x.label} id=${x.eventId||'—'} time=${x.elapsedMs}ms payload=${round(x.bytes/1024)||0}KB complete=${x.coverageComplete?'YES':'NO'} innings=${x.innings} periods=${x.periods} timeline=${x.timeline} players=${x.playerSections} winprob=${x.winProbability}${x.error?` ERROR=${x.error}`:''}`),
      '',
      'DAY-STATE PROBES',
      ...(gc.dayProbes||[]).map(x=>`${x.ok?'PASS':'FAIL'} ${x.path} HTTP=${x.status} ${x.elapsedMs}ms games=${x.games}`),
      '',
      '==================== 7. PLAYBACK / BUFFERING ====================',
      `PLAYBACK active=${p.active?'YES':'NO'} state=${p.startState||'—'}→${p.endState||'—'} league=${p.league||'—'} transport=${p.transport||'—'} provider=${p.provider||'—'} firstFrame=${p.firstFrameMs??'N/A'}ms stalls+${p.stallCountDelta||0} stallMs+${p.stallMsDelta||0} bufferRate=${p.bufferRatePct??'N/A'}% failures+${p.failureDelta||0} invariant=${p.invariant||'—'}`,
      p.reason||'',
      '',
      '==================== 8. ACTION ITEMS ====================',
      ...r.actions.map((x,i)=>`${i+1}. ${x}`),
      '',
      '==================== 9. RAW BACKEND COUNTERS ====================',
      `ASSOCIATIONS ${JSON.stringify(b.associations||{})}`,
      `PROVIDER_CONCURRENCY ${JSON.stringify(b.providers||{})}`,
      '',
      `END COMPREHENSIVE CERTIFICATION • RESULT=${r.result}`,
    ];
    return lines.filter((x,i)=>x!==''||lines[i-1]!=='').join('\n');
  }

  async function runFull(){
    if(state.running)return state.lastReport;
    const launch=$('launchScreen');if(launch&&!launch.classList.contains('hidden')&&getComputedStyle(launch).display!=='none')throw new Error('Start Sports Big Board before running Comprehensive Certification.');
    state.running=true;renderCard();const started=now();
    try{
      const backendBefore=await backendSnapshot();
      let efficiency=null;
      try{efficiency=await window.SBB_EFFICIENCY?.runAutoTest?.();}catch(err){efficiency={result:'FAIL',text:`Efficiency test failed to execute: ${clean(err?.message||err)}`,metrics:{}};}
      const gameCenter=await gameCenterCensus();
      const playback=await playbackObservation(12000);
      const backendAfter=await backendSnapshot();
      const report={version:VERSION,release:RELEASE,startedAt:new Date(Date.now()-(now()-started)).toISOString(),finishedAt:new Date().toISOString(),elapsedMs:round(now()-started),backendBefore,backendAfter,backendDelta:backendDelta(backendBefore,backendAfter),efficiency,gameCenter,playback};
      report.actions=actionItems(report);report.result=overall(report);report.text=reportText(report);state.lastReport=report;
      try{localStorage.setItem('sbb.site-certification.last',JSON.stringify(report));}catch(_){}
      try{window.dispatchEvent(new CustomEvent('sbb:site-certification',{detail:report}));}catch(_){}
      return report;
    }finally{state.running=false;renderCard();}
  }

  function injectStyle(){if($('sbbSiteCertificationStyle'))return;const s=document.createElement('style');s.id='sbbSiteCertificationStyle';s.textContent=`#sbbSiteCertificationCard .sitecert-actions{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}#sbbSiteCertificationOutput{max-height:420px;overflow:auto;white-space:pre-wrap;font:10px/1.42 ui-monospace,SFMono-Regular,Consolas,monospace;background:#080d13;border:1px solid #263442;border-radius:7px;padding:9px}#sbbSiteCertificationGrade{font-weight:900;letter-spacing:.08em}#sbbSiteCertificationGrade.PASS{color:#4ade80}#sbbSiteCertificationGrade.WARN{color:#fbbf24}#sbbSiteCertificationGrade.FAIL{color:#fb7185}`;document.head.appendChild(s);}
  function ensureCard(){
    if($('sbbSiteCertificationCard')){state.cardInstalled=true;return true;}const anchor=$('sbbEfficiencyCard')||document.querySelector('.settings-card:last-of-type');if(!anchor)return false;injectStyle();
    const card=document.createElement('div');card.id='sbbSiteCertificationCard';card.className='settings-card hidden';card.innerHTML=`<div class="eff-head"><div><div class="settings-card-title">COMPREHENSIVE SITE CERTIFICATION</div><small>Frontend • Game Center • playback/buffering • database • crawlers • workers • APIs</small></div><span id="sbbSiteCertificationGrade">IDLE</span></div><div class="sitecert-actions"><button id="sbbSiteCertificationRun" class="settings-save-btn" type="button">RUN COMPREHENSIVE TEST</button><button id="sbbSiteCertificationCopy" type="button">COPY FULL REPORT</button><button id="sbbSiteCertificationDownload" type="button">DOWNLOAD REPORT</button></div><pre id="sbbSiteCertificationOutput">Run once for a pasteable whole-site health report. A full run normally takes ~30–90 seconds depending on Game Center timeouts.</pre>`;anchor.after(card);
    $('sbbSiteCertificationRun').onclick=()=>runFull().catch(err=>{state.lastReport={result:'FAIL',text:`COMPREHENSIVE TEST FAILED TO EXECUTE\n${clean(err?.stack||err)}`};renderCard();});
    $('sbbSiteCertificationCopy').onclick=async()=>{try{await navigator.clipboard.writeText(state.lastReport?.text||'No report yet.');}catch(_){}};
    $('sbbSiteCertificationDownload').onclick=()=>{const text=state.lastReport?.text||'No report yet.';const blob=new Blob([text],{type:'text/plain'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`sports-big-board-comprehensive-${new Date().toISOString().replace(/[:.]/g,'-')}.txt`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
    const apply=()=>card.classList.toggle('hidden',!window.SBB_DEV_MODE?.isEnabled?.());apply();window.addEventListener('sbb:dev-mode',apply);state.cardInstalled=true;renderCard();return true;
  }
  function renderCard(){if(!state.cardInstalled&&!ensureCard())return;const grade=$('sbbSiteCertificationGrade'),out=$('sbbSiteCertificationOutput'),run=$('sbbSiteCertificationRun');if(!grade||!out)return;if(run)run.disabled=state.running;if(state.running){grade.className='WARN';grade.textContent='RUNNING';out.textContent='Comprehensive certification in progress…\n1) backend snapshot\n2) efficiency navigation\n3) Game Center census\n4) playback observation\n5) backend/crawl delta';return;}grade.className=state.lastReport?.result||'';grade.textContent=state.lastReport?.result||'IDLE';out.textContent=state.lastReport?.text||'Run once for a pasteable whole-site health report.';}
  function boot(){ensureCard();setInterval(ensureCard,1500);}
  window.SBB_SITE_CERTIFICATION=Object.freeze({version:VERSION,runFull,snapshot:()=>({version:VERSION,running:state.running,lastReport:state.lastReport}),reportText:()=>state.lastReport?.text||'No comprehensive certification report yet.'});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();

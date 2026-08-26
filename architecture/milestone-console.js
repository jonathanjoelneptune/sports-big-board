/* Sports Big Board 4.2 milestone release console.
   Captures browser/runtime failures, runs repeatable dev procedures, and renders
   one exportable platform-health log. COPY FULL LOG is the canonical handoff. */
(() => {
  'use strict';
  if(window.SBB_MILESTONE) return;
  const VERSION=String(window.SBB_RELEASE_VERSION||window.SBB_CORE?.version||'4.2.1');
  const TAB_ID=`milestone-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,8)}`;
  const COPY_FULL_LOG_LABEL='COPY FULL LOG';
  const $=id=>document.getElementById(id);
  const sleep=ms=>new Promise(r=>setTimeout(r,Math.max(0,Number(ms)||0)));
  let latest=null,pollTimer=0,heartbeatTimer=0,lastProblemFingerprint='',refreshPromise=null,refreshController=null;
  let stressStopRequested=false,stressRun=null,procedureResults={};
  const activeFetchControllers=new Set();
  const localEvents=[];
  const MAX_LOCAL=420;

  const PROCEDURES=[
    {id:'release-handshake',title:'Release / deployment handshake',description:'Confirms frontend/backend version agreement, milestone endpoint health, soundtrack status, and catalog integrity without mutating playback.'},
    {id:'playback-cycle',title:'Playback ownership cycle',description:'Starts the board if needed, verifies one playback session, pauses/resumes, advances clips, and checks that only one video slot owns audible playback.'},
    {id:'historical-read',title:'Historical catalog read path',description:'Loads yesterday through the compact ribbon, Silver roundup, discovery and paginated database-audit endpoints and records latency.'},
    {id:'operator-load',title:'Operator console concurrency',description:'Runs a mixed concurrent read burst across milestone, ribbon, audit and worker/status paths to expose DB lock contention or slow operator telemetry.'},
    {id:'resource-modes',title:'Resource-mode transitions',description:'Exercises BALANCED → PLAYBACK → SEARCH → BALANCED while verifying the selected mode and restoring the original mode.'},
    {id:'game-center',title:'Game Center surface',description:'Opens and closes Game Center through the official information-surface API and confirms drawer state changes without taking playback authority.'},
    {id:'soundtrack',title:'Soundtrack ownership',description:'Checks the one-audio invariant, toggles soundtrack off/on, skips once, and confirms the site soundtrack still reports exactly one audio element.'},
    {id:'ui-responsiveness',title:'Browser responsiveness / event loop',description:'Measures event-loop delay during a short UI/API burst and flags a visibly blocked main thread.'}
  ];

  function safe(value){try{return JSON.parse(JSON.stringify(value));}catch(_){return String(value);}}
  function remember(level,message,data={}){
    localEvents.push({at:Date.now(),level:String(level||'INFO').toUpperCase(),message:String(message||''),data:safe(data)});
    if(localEvents.length>MAX_LOCAL)localEvents.splice(0,localEvents.length-MAX_LOCAL);
  }
  function post(kind,level,message,data={},extra={}){
    remember(level,message,data);
    try{
      const body={kind,level,message,data,tabId:TAB_ID,frontendVersion:VERSION,at:Date.now(),playback:window.SBB_PLAYBACK_SESSION?.snapshot?.()||{},...extra};
      fetch('/api/milestone/client-event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),keepalive:true,cache:'no-store'}).catch(()=>{});
    }catch(_){ }
  }
  function heartbeat(){
    const context=window.SBB_MILESTONE_CONTEXT?.()||{};
    post('heartbeat','INFO','browser heartbeat',{visibility:document.visibilityState,online:navigator.onLine,playback:window.SBB_PLAYBACK_SESSION?.snapshot?.()||{},soundtrack:window.SBB_SOUNDTRACK?.snapshot?.()||{},context},{url:location.href});
  }

  function onError(ev){
    const err=ev?.error;
    post('error','ERROR',String(ev?.message||err?.message||'window error'),{filename:ev?.filename||'',lineno:ev?.lineno||0,colno:ev?.colno||0,stack:String(err?.stack||'').slice(0,5000)});
  }
  function onReject(ev){const r=ev?.reason;post('unhandledrejection','ERROR',String(r?.message||r||'Unhandled promise rejection'),{stack:String(r?.stack||'').slice(0,5000)});}
  window.addEventListener('error',onError);
  window.addEventListener('unhandledrejection',onReject);
  window.addEventListener('offline',()=>post('network','WARN','browser went offline'));
  window.addEventListener('online',()=>post('network','INFO','browser returned online'));

  const origError=console.error.bind(console),origWarn=console.warn.bind(console);
  console.error=(...args)=>{origError(...args);try{post('console-error','ERROR',args.map(x=>typeof x==='string'?x:JSON.stringify(x)).join(' ').slice(0,1800));}catch(_) {}};
  console.warn=(...args)=>{origWarn(...args);try{const text=args.map(x=>typeof x==='string'?x:JSON.stringify(x)).join(' ');if(/^\[SBB/i.test(text))post('console-warn','WARN',text.slice(0,1800));}catch(_) {}};

  window.SBB_PLAYBACK_SESSION?.subscribe?.(snap=>{
    if(String(snap?.invariant||'').startsWith('ERROR')) post('playback-invariant','ERROR',snap.invariant,{audible:snap.audible,sessionId:snap.sessionId,mediaKey:snap.mediaKey});
  });

  function fmtTime(epoch){if(!epoch)return '—';try{return new Date(Number(epoch)*1000).toLocaleTimeString();}catch(_){return '—';}}
  function fmtMs(v){return v==null?'—':`${Math.round(Number(v)||0)} ms`;}
  function stressSummaryLines(){
    const lines=[];
    lines.push('[DEV STRESS TEST]');
    if(!stressRun){lines.push('No stress test has been run in this browser tab.');return lines;}
    lines.push(`run=${stressRun.id} • status=${stressRun.status} • started=${new Date(stressRun.startedAt).toISOString()} • duration=${Math.round((stressRun.finishedAt||Date.now())-stressRun.startedAt)} ms`);
    lines.push(`steps=${stressRun.steps.length} • pass=${stressRun.steps.filter(x=>x.status==='PASS').length} • warn=${stressRun.steps.filter(x=>x.status==='WARN').length} • fail=${stressRun.steps.filter(x=>x.status==='FAIL').length} • skip=${stressRun.steps.filter(x=>x.status==='SKIP').length}`);
    for(const x of stressRun.steps)lines.push(`${x.status} • ${x.name} • ${Math.round(x.durationMs||0)} ms${x.detail?` • ${x.detail}`:''}${x.data?` • ${JSON.stringify(x.data)}`:''}`);
    lines.push('');lines.push('[MILESTONE TEST PROCEDURES]');
    for(const p of PROCEDURES){const r=procedureResults[p.id];lines.push(`${r?.status||'NOT RUN'} • ${p.title}${r?.detail?` • ${r.detail}`:''}`);}
    return lines;
  }
  function textSnapshot(data=latest){
    if(!data)return 'MILESTONE RELEASE CONSOLE — no snapshot yet';
    const x=data.extra||{},rel=x.release||{},pb=data.playback||{},ps=pb.latest||{},hist=x.history||{},counts=data.problemCounts||{};
    const lines=[];
    lines.push('SPORTS BIG BOARD — MILESTONE RELEASE CONSOLE');
    lines.push(`Captured: ${new Date().toLocaleString()} (${new Date().toISOString()})`);
    lines.push(`Milestone: ${data.version||VERSION} • Overall: ${data.overall||'UNKNOWN'} • errors=${counts.errors||0} warnings=${counts.warnings||0}`);
    lines.push(`Version handshake: frontend ${rel.frontendVersion||VERSION} • backend ${rel.backendVersion||'?'} • ${rel.versionMatch?'MATCH':'MISMATCH'}`);
    lines.push(`Deployment: ${rel.deploymentMode||'?'} • backend uptime ${rel.uptimeSeconds||0}s`);
    lines.push('');
    lines.push('[PLAYBACK SESSION]');
    lines.push(`session=${ps.sessionId||'—'} • state=${ps.state||'idle'} • event=${ps.eventKey||'—'} • media=${ps.mediaKey||'—'}`);
    lines.push(`transport=${ps.transport||'—'} • slot=${ps.slot||'—'} • firstFrame=${fmtMs(ps.firstFrameMs)} • stalls=${ps.stallCount||0}/${fmtMs(ps.stallTotalMs)}`);
    lines.push(`audible videoA=${!!ps.audible?.videoA} videoB=${!!ps.audible?.videoB} soundtrack=${!!ps.audible?.soundtrack} • invariant=${ps.invariant||'OK'}`);
    lines.push(`source=${ps.sourceExternalUrl||ps.sourceUrl||'—'}`);
    lines.push(`first-frame samples=${pb.firstFrame?.samples||0} p50=${fmtMs(pb.firstFrame?.p50Ms)} p95=${fmtMs(pb.firstFrame?.p95Ms)} max=${fmtMs(pb.firstFrame?.maxMs)} • failures=${pb.failures||0}`);
    lines.push('');
    lines.push(...stressSummaryLines());
    lines.push('');
    lines.push('[PLATFORM CHECKS]');
    for(const c of data.checks||[])lines.push(`${c.ok?'PASS':'FAIL'} • ${c.name}: ${c.detail||''}`);
    lines.push('');
    lines.push('[PROBLEMS]');
    if(!(data.problems||[]).length)lines.push('NONE');
    for(const p of data.problems||[])lines.push(`${p.level||'INFO'} • ${p.code||''} • ${p.message||''}${p.detail?` • ${JSON.stringify(p.detail)}`:''}`);
    lines.push('');
    lines.push('[WORKERS / COORDINATION]');
    const workerRows=Object.entries(hist.workers||{});
    lines.push(`workers=${workerRows.filter(([,w])=>w.healthy).length}/${workerRows.length} healthy • mode=${hist.workMode?.mode||'?'}`);
    lines.push(`greenPool=${hist.greenPool?.active||0}/${hist.greenPool?.desired||0} active • singleflight=${JSON.stringify(hist.singleflight||{})}`);
    for(const [name,w] of workerRows)lines.push(`${w.healthy?'OK':'BAD'} ${name} • ${w.phase||'—'} • heartbeat=${w.heartbeatAgeSeconds??'—'}s • ${w.current||''}`);
    lines.push('');
    lines.push('[DATABASE / OPERATOR]');
    lines.push(`operator ready=${!!hist.operatorSnapshot?.ready} age=${hist.operatorSnapshot?.ageSeconds??'—'}s loop=${hist.operatorSnapshot?.generationMs??'—'}ms maxComponent=${hist.operatorSnapshot?.maxComponentMs??'—'}ms error=${hist.operatorSnapshot?.error||'—'}`);
    lines.push(`operatorComponents=${JSON.stringify(hist.operatorSnapshot?.componentTimings||{})}`);
    lines.push(`database=${JSON.stringify(x.database?.summary||{})}`);
    lines.push(`databaseAudit=${JSON.stringify(hist.databaseAudit||{})}`);
    lines.push('');
    lines.push('[API LATENCY]');
    const apiRows=Object.entries(data.api||{}).sort((a,b)=>(b[1].p95Ms||0)-(a[1].p95Ms||0));
    for(const [path,row] of apiRows)lines.push(`${path} • count=${row.count||0} errors=${row.errors||0} last=${row.lastMs||0}ms avg=${row.avgMs||0}ms p95=${row.p95Ms??'—'}ms max=${row.maxMs||0}ms status=${row.lastStatus||0}`);
    lines.push('');
    lines.push('[MEDIA / SCHEDULERS]');
    lines.push(`mediaCache=${JSON.stringify(x.mediaCache||{})}`);
    lines.push(`mediaScheduler=${JSON.stringify(x.schedulers?.media||{})}`);
    lines.push(`gameCenterScheduler=${JSON.stringify(x.schedulers?.gameCenter||{})}`);
    lines.push(`director=${JSON.stringify(x.director||{})}`);
    lines.push('');
    lines.push('[RECENT RELEASE EVENTS]');
    for(const row of data.recent||[])lines.push(`${fmtTime(row.at)} • ${row.level||'INFO'} • ${row.source||'server'} • ${row.category||''} • ${row.message||''}${row.data?` • ${JSON.stringify(row.data)}`:''}`);
    lines.push('');
    lines.push('[LOCAL BROWSER EVENTS]');
    for(const row of localEvents.slice(-160))lines.push(`${new Date(row.at).toLocaleTimeString()} • ${row.level} • ${row.message}${row.data?` • ${JSON.stringify(row.data)}`:''}`);
    return lines.join('\n');
  }

  function renderStress(){
    const status=$('milestoneStressStatus'),detail=$('milestoneStressDetail'),bar=$('milestoneStressProgress'),runBtn=$('milestoneStressRun'),stopBtn=$('milestoneStressStop');
    if(!stressRun){if(status){status.textContent='IDLE';status.dataset.state='idle';}if(bar)bar.style.width='0%';if(runBtn)runBtn.disabled=false;if(stopBtn)stopBtn.disabled=true;return;}
    const total=Math.max(1,Number(stressRun.total||stressRun.steps.length||1)),done=Number(stressRun.completed||stressRun.steps.length||0);
    if(status){status.textContent=`${stressRun.status} • ${done}/${total}`;status.dataset.state=String(stressRun.status||'').toLowerCase();}
    if(bar)bar.style.width=`${Math.max(0,Math.min(100,(done/total)*100))}%`;
    if(detail){const last=stressRun.steps.at?.(-1)||stressRun.steps[stressRun.steps.length-1];detail.textContent=stressRun.current?`Running: ${stressRun.current}`:(last?`${last.status}: ${last.name}${last.detail?` • ${last.detail}`:''}`:'Preparing test…');}
    if(runBtn)runBtn.disabled=stressRun.status==='RUNNING';if(stopBtn)stopBtn.disabled=stressRun.status!=='RUNNING';
    const out=$('milestoneConsoleOutput');if(out&&latest)out.textContent=textSnapshot(latest);
  }
  function renderProcedures(){
    const list=$('milestoneProcedureList');if(!list)return;
    list.innerHTML=PROCEDURES.map(p=>{const r=procedureResults[p.id]||{};return `<article class="milestone-procedure" data-procedure-id="${p.id}" data-result="${String(r.status||'').toLowerCase()}"><div class="milestone-procedure-copy"><strong>${p.title}</strong><small>${p.description}</small><em>${r.status?`${r.status}${r.detail?` • ${r.detail}`:''}`:'NOT RUN'}</em></div><div class="milestone-procedure-actions"><button type="button" data-procedure-run="${p.id}">RUN</button><button type="button" data-procedure-result="pass" data-procedure-id="${p.id}">PASS</button><button type="button" data-procedure-result="fail" data-procedure-id="${p.id}">FAIL</button></div></article>`;}).join('');
    list.querySelectorAll('[data-procedure-run]').forEach(btn=>btn.addEventListener('click',()=>runProcedure(btn.dataset.procedureRun)));
    list.querySelectorAll('[data-procedure-result]').forEach(btn=>btn.addEventListener('click',()=>markProcedure(btn.dataset.procedureId,String(btn.dataset.procedureResult||'').toUpperCase(),'manual result')));
  }
  function render(data){
    latest=data;
    const overall=$('milestoneConsoleOverall');if(overall){overall.textContent=data?.overall||'CONNECTING…';overall.dataset.state=String(data?.overall||'').toLowerCase();}
    const set=(id,val)=>{const el=$(id);if(el)el.textContent=String(val??'—');};
    const rel=data?.extra?.release||{},pb=data?.playback||{},ps=pb.latest||{},hist=data?.extra?.history||{};
    set('milestoneVersion',`${rel.frontendVersion||VERSION} / ${rel.backendVersion||'?'}`);
    set('milestonePlayback',`${ps.state||'idle'} • ${ps.transport||'—'} • ${ps.slot||'—'}`);
    set('milestoneFirstFrame',pb.firstFrame?.p95Ms==null?'—':`p95 ${Math.round(pb.firstFrame.p95Ms)} ms`);
    set('milestoneStalls',`${pb.stalls||0} • ${Math.round(ps.stallTotalMs||0)} ms current session`);
    set('milestoneInvariant',ps.invariant||'OK');
    const workers=Object.values(hist.workers||{});set('milestoneWorkers',`${workers.filter(w=>w.healthy).length}/${workers.length} healthy`);
    set('milestoneDb',hist.operatorSnapshot?.ready?`${hist.operatorSnapshot.ageSeconds??0}s old • ${hist.operatorSnapshot.generationMs??0}ms build`:'NOT READY');
    const counts=data?.problemCounts||{};set('milestoneProblems',`${counts.errors||0} errors • ${counts.warnings||0} warnings`);
    const probs=$('milestoneConsoleProblems');
    if(probs){probs.innerHTML=(data?.problems||[]).map(p=>`<div class="milestone-problem ${String(p.level||'').toLowerCase()}"><strong>${p.level||'INFO'} • ${p.code||''}</strong><span>${String(p.message||'')}</span></div>`).join('')||'<div class="milestone-problem ok"><strong>NO ACTIVE RELEASE PROBLEMS</strong><span>All current milestone invariants are passing.</span></div>';}
    const out=$('milestoneConsoleOutput');if(out)out.textContent=textSnapshot(data);
    const fp=JSON.stringify((data?.problems||[]).map(p=>[p.level,p.code,p.message]));
    if(fp!==lastProblemFingerprint){lastProblemFingerprint=fp;if((data?.problems||[]).some(p=>p.level==='ERROR'))remember('ERROR','server milestone snapshot reports errors',{problems:data.problems});}
    renderStress();renderProcedures();
  }

  async function refresh(){
    // Polls are single-flight and bounded. If a diagnostic endpoint itself slows
    // down, Dev Mode must report that failure instead of multiplying overlapping
    // requests every 2.5 seconds and making the platform problem worse.
    if(refreshPromise)return refreshPromise;
    refreshController=new AbortController();
    const controller=refreshController;
    const timer=setTimeout(()=>controller.abort('milestone refresh timeout'),10000);
    refreshPromise=(async()=>{
      try{
        const r=await fetch(`/api/milestone/console?frontendVersion=${encodeURIComponent(VERSION)}&limit=420`,{cache:'no-store',signal:controller.signal});
        const data=await r.json();if(!r.ok||!data.ok)throw new Error(data?.message||data?.error||`HTTP ${r.status}`);render(data);return data;
      }catch(err){
        if(controller.signal.aborted&&String(controller.signal.reason||'')==='milestone console closed')return null;
        const message=controller.signal.aborted?'milestone console refresh timed out':String(err?.message||err);
        remember('ERROR','milestone console refresh failed',{error:message});
        const out=$('milestoneConsoleOutput');if(out)out.textContent=`MILESTONE RELEASE CONSOLE CONNECT ERROR\n${message}`;
        const overall=$('milestoneConsoleOverall');if(overall){overall.textContent='CONNECT ERROR';overall.dataset.state='error';}
        return null;
      }finally{clearTimeout(timer);if(refreshController===controller)refreshController=null;refreshPromise=null;}
    })();
    return refreshPromise;
  }

  function assert(condition,message){if(!condition)throw new Error(message||'assertion failed');}
  async function waitFor(predicate,{timeoutMs=8000,intervalMs=100,label='condition'}={}){
    const started=performance.now();
    while(performance.now()-started<timeoutMs){if(stressStopRequested)throw new DOMException('stress test stopped','AbortError');try{const value=predicate();if(value)return value;}catch(_){ }await sleep(intervalMs);}
    throw new Error(`timeout waiting for ${label} (${timeoutMs} ms)`);
  }
  async function fetchTimed(url,{timeoutMs=10000,expectOk=true}={}){
    const controller=new AbortController();activeFetchControllers.add(controller);let timedOut=false;
    const timer=setTimeout(()=>{timedOut=true;controller.abort();},timeoutMs);const started=performance.now();
    try{
      const r=await fetch(url,{cache:'no-store',signal:controller.signal});let body=null;const type=String(r.headers.get('content-type')||'');
      if(type.includes('json')){try{body=await r.json();}catch(_){body=null;}}
      const ms=Math.round(performance.now()-started);
      if(expectOk&&!r.ok)throw new Error(`${url} HTTP ${r.status}${body?.error?` ${body.error}`:''}`);
      return {status:r.status,ok:r.ok,ms,body};
    }catch(err){
      if(timedOut)throw new Error(`${url} timed out after ${timeoutMs} ms`);
      throw err;
    }finally{clearTimeout(timer);activeFetchControllers.delete(controller);}
  }
  function hooks(){const h=window.SBB_DEV_TEST_HOOKS;if(!h)throw new Error('SBB_DEV_TEST_HOOKS unavailable');return h;}
  function audibleVideoCount(pb=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{}){return Number(!!pb.audible?.videoA)+Number(!!pb.audible?.videoB);}
  async function measuredEventLoopDelay(){const planned=performance.now()+40;return await new Promise(resolve=>setTimeout(()=>resolve(Math.max(0,Math.round(performance.now()-planned))),40));}

  async function step(name,fn,{warnAboveMs=0}={}){
    if(stressStopRequested)throw new DOMException('stress test stopped','AbortError');
    stressRun.current=name;renderStress();const started=performance.now();
    let status='PASS',detail='',data=null;
    try{
      const result=await fn();
      if(result&&typeof result==='object'&&result.__milestoneStatus){status=result.__milestoneStatus;detail=String(result.detail||'');data=safe(result.data||null);}
      else if(result!==undefined)data=safe(result);
    }catch(err){
      if(err?.name==='AbortError'&&stressStopRequested)throw err;
      status='FAIL';detail=String(err?.message||err);data={stack:String(err?.stack||'').slice(0,1800)};
    }
    const durationMs=Math.round(performance.now()-started);
    if(status==='PASS'&&warnAboveMs&&durationMs>warnAboveMs){status='WARN';detail=`slow step: ${durationMs} ms > ${warnAboveMs} ms${detail?` • ${detail}`:''}`;}
    const row={name,status,durationMs,detail,data,at:Date.now()};stressRun.steps.push(row);
    post('stress-step',status==='FAIL'?'ERROR':status==='WARN'?'WARN':'INFO',`${status} • ${name}`,{durationMs,detail,data,runId:stressRun.id});renderStress();return row;
  }
  const warn=(detail,data=null)=>({__milestoneStatus:'WARN',detail,data});
  const skip=(detail,data=null)=>({__milestoneStatus:'SKIP',detail,data});

  async function procedureReleaseHandshake(){
    return [
      await step('release: milestone endpoint',async()=>{const x=await fetchTimed(`/api/milestone/console?frontendVersion=${encodeURIComponent(VERSION)}&limit=80`);assert(x.body?.version===VERSION,`backend version ${x.body?.version||'?'} != ${VERSION}`);assert(x.body?.extra?.release?.versionMatch!==false,'frontend/backend version mismatch');return {status:x.status,ms:x.ms};},{warnAboveMs:2500}),
      await step('release: soundtrack status',async()=>{const x=await fetchTimed('/api/soundtrack/status');return {status:x.status,ms:x.ms,tracks:x.body?.tracks??x.body?.trackCount};},{warnAboveMs:2000}),
      await step('release: catalog integrity',async()=>{const x=await fetchTimed('/api/history/catalog/integrity',{timeoutMs:12000});assert(x.body?.ok===true,'catalog integrity endpoint not OK');return {status:x.status,ms:x.ms,integrity:x.body?.integrity};},{warnAboveMs:3500})
    ];
  }
  async function procedurePlaybackCycle(){
    const h=hooks();
    await step('playback: dev hook availability',async()=>{assert(h.version,'missing hook version');return {hookVersion:h.version,programSize:h.programSize()};});
    await step('playback: experience state',async()=>{if(!h.started())return skip('start Sports Big Board before running playback mutation tests');return {started:true,mediaKey:h.currentMediaKey(),state:h.playback()?.state};});
    await step('playback: wait for stable selected session',async()=>{if(!h.started()||!h.programSize())return skip('no active playable program');const pb=await waitFor(()=>{const p=h.playback();return p.mediaKey&&['playing','paused','ready','buffering','starting'].includes(p.state)?p:null;},{timeoutMs:12000,label:'stable selected playback session'});assert(audibleVideoCount(pb)<=1,`multiple audible video slots: ${JSON.stringify(pb.audible)}`);return pb;},{warnAboveMs:5000});
    await step('playback: pause/resume ownership',async()=>{
      if(!h.started()||!h.programSize())return skip('no active playable program');
      let current=h.playback();
      if(['starting','buffering'].includes(current.state))current=await waitFor(()=>{const p=h.playback();return ['playing','paused','ready','failed','ended'].includes(p.state)?p:null;},{timeoutMs:12000,label:'transient playback settle'});
      // Desired-state hooks are intentionally non-toggle.  The v4.2.1 stress test
      // could enter while the user had manually paused playback and then wait for a
      // spontaneous PLAYING transition that would never occur.
      assert(h.ensurePlaying?.()!==false,'unable to command playback playing');
      current=await waitFor(()=>{const p=h.playback();return p.state==='playing'?p:null;},{timeoutMs:12000,label:'playback playing before pause'});
      assert(audibleVideoCount(current)<=1,`multiple audible slots before pause: ${JSON.stringify(current.audible)}`);
      assert(h.ensurePaused?.()!==false,'unable to command playback paused');
      const paused=await waitFor(()=>{const p=h.playback();return ['paused','ready'].includes(p.state)?p:null;},{timeoutMs:6000,label:'playback pause'});
      assert(audibleVideoCount(paused)===0,`video remained audible after pause: ${JSON.stringify(paused.audible)}`);
      assert(h.ensurePlaying?.()!==false,'unable to command playback resume');
      const resumed=await waitFor(()=>{const p=h.playback();return p.state==='playing'?p:null;},{timeoutMs:12000,label:'playback resume'});
      assert(audibleVideoCount(resumed)<=1,'multiple audible slots after resume');assert(!String(resumed.invariant||'').startsWith('ERROR'),resumed.invariant);
      return {pausedState:paused.state,resumedState:resumed.state,audible:resumed.audible};
    });
    await step('playback: next clip transition',async()=>{if(!h.started()||h.programSize()<2)return skip('fewer than two active program items');const before=h.currentMediaKey();const moved=await h.stressTuneNext();if(!moved)return skip('no eligible next program item');const pb=await waitFor(()=>{const p=h.playback();return p.mediaKey&&p.mediaKey!==before?p:null;},{timeoutMs:12000,label:'next media selection'});assert(audibleVideoCount(pb)<=1,'multiple audible video slots after clip change');return {before,after:pb.mediaKey,state:pb.state,source:pb.sourceExternalUrl};},{warnAboveMs:5000});
  }
  async function procedureHistoricalRead(){
    const h=hooks(),date=h.yesterday();
    await step('history: compact ribbon',async()=>{const x=await fetchTimed(`/api/history/ribbon?date=${encodeURIComponent(date)}`,{timeoutMs:12000});assert(x.body?.ok===true,'ribbon response not OK');return {date,ms:x.ms,games:x.body?.scoreGameCount,catalogEvents:x.body?.catalogEventCount,timing:x.body?.timing};},{warnAboveMs:3000});
    await step('history: Silver roundup',async()=>{const x=await fetchTimed(`/api/history/roundups?date=${encodeURIComponent(date)}&league=ALL`,{timeoutMs:10000});assert(x.body?.ok===true,'Silver response not OK');return {date,ms:x.ms,rows:x.body?.media?.length||0,playable:x.body?.playable?.length||0};},{warnAboveMs:2500});
    await step('history: discovery snapshot',async()=>{const x=await fetchTimed(`/api/history/discovery?date=${encodeURIComponent(date)}`,{timeoutMs:8000});assert(x.body?.ok===true,'discovery snapshot not OK');return {date,ms:x.ms,state:x.body?.state};},{warnAboveMs:2000});
    await step('history: paginated database audit',async()=>{const x=await fetchTimed('/api/history/audit?limit=25&offset=0',{timeoutMs:15000});assert(x.body?.ok===true,'database audit not OK');return {ms:x.ms,count:x.body?.rows?.length??x.body?.items?.length??null,total:x.body?.total??null};},{warnAboveMs:4000});
  }
  async function procedureOperatorLoad(){
    const h=hooks(),date=h.yesterday();
    await step('operator: concurrent mixed-read burst',async()=>{
      const urls=[
        `/api/milestone/console?frontendVersion=${encodeURIComponent(VERSION)}&limit=60`,
        `/api/history/ribbon?date=${encodeURIComponent(date)}`,
        '/api/history/audit?limit=20&offset=0',
        `/api/history/discovery?date=${encodeURIComponent(date)}`,
        '/api/history/catalog/integrity',
        '/api/soundtrack/status'
      ];
      const started=performance.now();const rows=await Promise.all(urls.map(u=>fetchTimed(u,{timeoutMs:15000})));const wall=Math.round(performance.now()-started);
      assert(rows.every(x=>x.ok),`one or more concurrent reads failed: ${rows.map(x=>x.status).join(',')}`);
      return {wallMs:wall,requests:rows.map((x,i)=>({url:urls[i],status:x.status,ms:x.ms}))};
    },{warnAboveMs:5000});
  }
  async function procedureResourceModes(){
    const h=hooks(),original=h.resourceMode();
    await step('resource: BALANCED → PLAYBACK → SEARCH → restore',async()=>{
      const seen=[];
      try{for(const mode of ['balanced','playback','search']){seen.push(await h.setResourceMode(mode));await sleep(350);assert(h.resourceMode()===mode,`resource mode did not enter ${mode}`);}}
      finally{await h.setResourceMode(original||'balanced');await sleep(250);}
      assert(h.resourceMode()===(original||'balanced'),'resource mode failed to restore');return {original,seen,restored:h.resourceMode()};
    });
  }
  async function procedureGameCenter(){
    const h=hooks(),before=h.drawer();
    await step('Game Center: open/close surface',async()=>{h.openGameCenter();await sleep(350);const opened=h.drawer();assert(opened.open&&opened.tab==='game-center',`Game Center did not open: ${JSON.stringify(opened)}`);h.closeDrawer();await sleep(250);const closed=h.drawer();if(before.open)h.openDrawerTab(before.tab||'game-center');return {before,opened,closed};});
  }
  async function procedureSoundtrack(){
    const h=hooks();
    await step('soundtrack: one-audio invariant',async()=>{const s=h.soundtrack();assert(Number(s.audioElementCount||0)===1,`soundtrack audioElementCount=${s.audioElementCount}`);return s;});
    await step('soundtrack: toggle + skip + restore',async()=>{
      if(!h.started())return skip('experience not started');
      const before=h.soundtrack(),saved=h.soundtrackDevSnapshot?.(),wasEnabled=!!before.enabled;
      let result=null,restoreOk=true;
      try{
        h.soundtrackToggle();await sleep(250);const afterToggle=h.soundtrack();assert(Number(afterToggle.audioElementCount||0)===1,'audio element count changed after toggle');
        if(!afterToggle.enabled)h.soundtrackToggle();await sleep(250);const enabled=h.soundtrack();
        const priorId=enabled.currentTrack?.id||'';h.soundtrackNext();await sleep(350);const afterNext=h.soundtrack();assert(Number(afterNext.audioElementCount||0)===1,'audio element count changed after Next');
        if(priorId&&afterNext.currentTrack?.id===priorId&&Number(afterNext.trackCount||0)>1)throw new Error('Next did not advance soundtrack track');
        result={wasEnabled,priorId,afterId:afterNext.currentTrack?.id||'',audioElementCount:afterNext.audioElementCount};
      }finally{if(saved)restoreOk=h.soundtrackDevRestore?.(saved)===true;}
      assert(restoreOk,'soundtrack exact-state restore failed');
      return result;
    });
  }
  async function procedureUiResponsiveness(){
    await step('browser: event-loop responsiveness',async()=>{const delays=[];for(let i=0;i<8;i++){delays.push(await measuredEventLoopDelay());await sleep(30);}const max=Math.max(...delays),avg=Math.round(delays.reduce((a,b)=>a+b,0)/delays.length);if(max>500)return warn(`main-thread delay peaked at ${max} ms`,{delays,avg,max});return {delays,avg,max};});
  }

  const PROCEDURE_RUNNERS={
    'release-handshake':procedureReleaseHandshake,'playback-cycle':procedurePlaybackCycle,'historical-read':procedureHistoricalRead,
    'operator-load':procedureOperatorLoad,'resource-modes':procedureResourceModes,'game-center':procedureGameCenter,
    'soundtrack':procedureSoundtrack,'ui-responsiveness':procedureUiResponsiveness
  };
  function procedureStatusFromRows(rows){const statuses=(rows||[]).flat().filter(Boolean).map(x=>x.status);return statuses.includes('FAIL')?'FAIL':statuses.includes('WARN')?'WARN':statuses.length&&statuses.every(x=>x==='SKIP')?'SKIP':'PASS';}
  function markProcedure(id,status,detail=''){
    const p=PROCEDURES.find(x=>x.id===id);if(!p)return;
    procedureResults[id]={status:String(status||'').toUpperCase(),detail:String(detail||''),at:Date.now()};post('test-procedure',status==='FAIL'?'ERROR':status==='WARN'?'WARN':'INFO',`${procedureResults[id].status} • ${p.title}`,{procedureId:id,detail});renderProcedures();if(latest){const out=$('milestoneConsoleOutput');if(out)out.textContent=textSnapshot(latest);}
  }
  async function runProcedure(id,{withinStress=false}={}){
    if(stressRun?.status==='RUNNING'&&!withinStress)return;
    const p=PROCEDURES.find(x=>x.id===id),runner=PROCEDURE_RUNNERS[id];if(!p||!runner)return;
    let temporary=false;
    if(!stressRun||stressRun.status!=='RUNNING'){temporary=true;stressStopRequested=false;stressRun={id:`procedure-${id}-${Date.now().toString(36)}`,status:'RUNNING',startedAt:Date.now(),finishedAt:0,steps:[],completed:0,total:1,current:p.title};renderStress();}
    const startIndex=stressRun.steps.length;
    try{await runner();const rows=stressRun.steps.slice(startIndex);const status=procedureStatusFromRows(rows);markProcedure(id,status,`${rows.length} automated step${rows.length===1?'':'s'}`);}
    catch(err){if(err?.name==='AbortError')markProcedure(id,'WARN','stopped');else{markProcedure(id,'FAIL',String(err?.message||err));post('stress','ERROR',`procedure crashed: ${p.title}`,{error:String(err?.stack||err)});}}
    finally{if(temporary){stressRun.completed=1;stressRun.status=stressStopRequested?'STOPPED':procedureResults[id]?.status==='FAIL'?'FAIL':procedureResults[id]?.status==='WARN'?'WARN':'PASS';stressRun.finishedAt=Date.now();stressRun.current='';renderStress();await refresh();}}
  }

  async function runStressTest(){
    if(stressRun?.status==='RUNNING')return;
    stressStopRequested=false;activeFetchControllers.forEach(c=>c.abort());activeFetchControllers.clear();procedureResults={};
    const h=window.SBB_DEV_TEST_HOOKS;
    const original=h?{resourceMode:h.resourceMode?.(),scoreDate:h.scoreDate?.(),drawer:h.drawer?.(),soundtrack:h.soundtrack?.(),soundtrackDev:h.soundtrackDevSnapshot?.(),playback:h.playback?.(),mediaKey:h.currentMediaKey?.(),started:h.started?.()}:{};
    stressRun={id:`stress-${Date.now().toString(36)}`,status:'RUNNING',startedAt:Date.now(),finishedAt:0,steps:[],completed:0,total:PROCEDURES.length,current:'preflight',original};
    post('stress','INFO','DEV STRESS TEST STARTED',{runId:stressRun.id,procedures:PROCEDURES.map(x=>x.id),original});renderStress();
    try{
      for(let i=0;i<PROCEDURES.length;i++){
        if(stressStopRequested)throw new DOMException('stress test stopped','AbortError');
        stressRun.current=PROCEDURES[i].title;renderStress();await runProcedure(PROCEDURES[i].id,{withinStress:true});stressRun.completed=i+1;renderStress();
      }
    }catch(err){
      if(err?.name==='AbortError'){stressRun.status='STOPPED';post('stress','WARN','DEV STRESS TEST STOPPED',{runId:stressRun.id,completed:stressRun.steps.length});}
      else{stressRun.status='FAIL';post('stress','ERROR','DEV STRESS TEST CRASHED',{runId:stressRun.id,error:String(err?.stack||err)});}
    }finally{
      let restoreFailed=false;
      const restoreError=(message,err)=>{restoreFailed=true;post('stress','ERROR',message,{error:String(err)});};
      // Restore user-visible state after the exercise. Failures here are logged but
      // never hidden; the stress test must not silently leave the site in SEARCH.
      if(h){
        // Restore in a deterministic order. BALANCED is used temporarily so SEARCH
        // cannot block media restoration; the original resource mode is restored
        // last. Every failed restoration is itself a milestone error.
        try{await h.setResourceMode('balanced');}catch(err){restoreError('stress restore staging mode failed',err);}
        try{if(original.scoreDate&&h.scoreDate()!==original.scoreDate)await h.setScoreDate(original.scoreDate);}catch(err){restoreError('stress restore score date failed',err);}
        try{if(original.started&&original.mediaKey&&h.currentMediaKey()!==original.mediaKey){const ok=await h.restoreMediaKey(original.mediaKey);if(!ok)throw new Error(`original media not present after restore: ${original.mediaKey}`);await sleep(350);}}catch(err){restoreError('stress restore media selection failed',err);}
        try{const d=h.drawer();if(original.drawer?.open){if(!d.open||d.tab!==original.drawer.tab)h.openDrawerTab(original.drawer.tab||'game-center');}else if(d.open)h.closeDrawer();}catch(err){restoreError('stress restore drawer failed',err);}
        try{if(original.soundtrackDev&&!h.soundtrackDevRestore?.(original.soundtrackDev))throw new Error('soundtrack dev restore returned false');}catch(err){restoreError('stress restore soundtrack failed',err);}
        try{
          const before=String(original.playback?.state||''),now=String(h.playback?.().state||'');
          const beforeActive=['playing','starting','buffering'].includes(before),nowActive=['playing','starting','buffering'].includes(now);
          if(beforeActive&&!nowActive){h.playPause();await waitFor(()=>['playing','starting','buffering'].includes(String(h.playback?.().state||'')),{timeoutMs:7000,label:'restore active playback'});}
          else if(!beforeActive&&['paused','ready'].includes(before)&&nowActive){h.playPause();await waitFor(()=>['paused','ready'].includes(String(h.playback?.().state||'')),{timeoutMs:7000,label:'restore paused playback'});}
        }catch(err){restoreError('stress restore playback failed',err);}
        try{if(original.resourceMode)await h.setResourceMode(original.resourceMode);}catch(err){restoreError('stress restore resource mode failed',err);}
      }
      stressRun.finishedAt=Date.now();stressRun.current='';
      if(stressRun.status==='RUNNING'){
        const statuses=Object.values(procedureResults).map(x=>x.status);
        stressRun.status=restoreFailed||statuses.includes('FAIL')?'FAIL':statuses.includes('WARN')?'WARN':'PASS';
      }
      if(restoreFailed&&stressRun.status!=='FAIL')stressRun.status='FAIL';
      post('stress',stressRun.status==='FAIL'?'ERROR':stressRun.status==='WARN'||stressRun.status==='STOPPED'?'WARN':'INFO',`DEV STRESS TEST ${stressRun.status}`,{runId:stressRun.id,durationMs:stressRun.finishedAt-stressRun.startedAt,steps:stressRun.steps.map(x=>({name:x.name,status:x.status,durationMs:x.durationMs,detail:x.detail}))});renderStress();await refresh();
    }
  }
  function stopStressTest(){stressStopRequested=true;activeFetchControllers.forEach(c=>c.abort());post('stress','WARN','stop requested for dev stress test',{runId:stressRun?.id||''});renderStress();}
  async function runAllProcedures(){return runStressTest();}

  function copyText(){
    const text=textSnapshot(),done=()=>{const el=$('milestoneCopyStatus');if(el)el.textContent='COPIED';};
    try{const promise=navigator.clipboard?.writeText?.(text);if(promise?.then){promise.then(done).catch(()=>fallbackCopy(text,done));return;}}catch(_){ }
    fallbackCopy(text,done);
  }
  function fallbackCopy(text,done){try{const ta=document.createElement('textarea');ta.value=text;ta.setAttribute('readonly','');ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();const ok=document.execCommand?.('copy');ta.remove();if(ok)done();else throw new Error('copy command unavailable');}catch(_){const el=$('milestoneCopyStatus');if(el)el.textContent='COPY FAILED';}}
  function saveText(){const blob=new Blob([textSnapshot()],{type:'text/plain;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`sports-big-board-${VERSION}-milestone-console-${new Date().toISOString().replace(/[:.]/g,'-')}.txt`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000);}
  function open(){const m=$('milestoneConsoleModal');if(!m)return;m.classList.remove('hidden');m.setAttribute('aria-hidden','false');refresh();clearInterval(pollTimer);pollTimer=setInterval(refresh,2500);renderProcedures();renderStress();}
  function close(){const m=$('milestoneConsoleModal');if(!m)return;m.classList.add('hidden');m.setAttribute('aria-hidden','true');clearInterval(pollTimer);pollTimer=0;try{refreshController?.abort('milestone console closed');}catch(_){}}
  async function reset(){try{await fetch('/api/milestone/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',cache:'no-store'});localEvents.length=0;stressRun=null;procedureResults={};await refresh();renderStress();renderProcedures();}catch(err){remember('ERROR','milestone reset failed',{error:String(err)});}}
  function toggleProcedures(){const p=$('milestoneProceduresPanel'),btn=$('milestoneProceduresToggle');if(!p)return;const show=p.classList.contains('hidden');p.classList.toggle('hidden',!show);btn?.setAttribute('aria-expanded',show?'true':'false');if(show)renderProcedures();}
  function bind(){
    $('openMilestoneConsoleBtn')?.addEventListener('click',open);$('milestoneConsoleClose')?.addEventListener('click',close);$('milestoneConsoleBackdrop')?.addEventListener('click',close);
    $('milestoneConsoleRefresh')?.addEventListener('click',refresh);$('milestoneConsoleCopy')?.addEventListener('click',copyText);$('milestoneConsoleDownload')?.addEventListener('click',saveText);$('milestoneConsoleReset')?.addEventListener('click',reset);
    $('milestoneStressRun')?.addEventListener('click',runStressTest);$('milestoneStressStop')?.addEventListener('click',stopStressTest);$('milestoneProceduresToggle')?.addEventListener('click',toggleProcedures);$('milestoneProceduresRunAll')?.addEventListener('click',runAllProcedures);
    renderProcedures();renderStress();heartbeat();heartbeatTimer=setInterval(heartbeat,10000);setTimeout(refresh,1800);
  }
  window.SBB_MILESTONE=Object.freeze({version:'1.1',release:VERSION,open,close,refresh,text:textSnapshot,record:post,runStressTest,stopStressTest,runProcedure,procedures:PROCEDURES.map(x=>({...x})),get stress(){return safe(stressRun);},get snapshot(){return latest;}});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
})();

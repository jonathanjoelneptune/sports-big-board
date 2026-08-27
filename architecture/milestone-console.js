/* Sports Big Board 4.3.5 three-tier certification console.
   Captures browser/runtime failures, runs repeatable dev procedures, and renders
   one exportable platform-health log. COPY FULL LOG is the canonical handoff. */
(() => {
  'use strict';
  if(window.SBB_MILESTONE) return;
  const VERSION=String(window.SBB_RELEASE_VERSION||window.SBB_CORE?.version||'4.3.5');
  const TAB_ID=`milestone-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,8)}`;
  const COPY_FULL_LOG_LABEL='COPY FULL LOG';
  const $=id=>document.getElementById(id);
  const sleep=ms=>new Promise(r=>setTimeout(r,Math.max(0,Number(ms)||0)));
  let latest=null,pollTimer=0,heartbeatTimer=0,lastProblemFingerprint='',refreshPromise=null,refreshController=null;
  let stressStopRequested=false,stressRun=null,soakRun=null,chaosRun=null,procedureResults={};
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
    {id:'ui-responsiveness',title:'Browser responsiveness / event loop',description:'Measures event-loop delay during a short UI/API burst and flags a visibly blocked main thread.'},
    {id:'regression-hardening',title:'Playback / Game Center regression hardening',description:'Verifies no demo startup media, no browse-triggered roundup takeover, sticky manual pause, background-refresh continuity, and Game Center ownership of the active game video.'}
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
  function phaseRunSummaryLines(label,run){
    const lines=[];lines.push(`[${label}]`);
    if(!run){lines.push(`No ${label.toLowerCase()} run has been run in this browser tab.`);return lines;}
    const duration=Math.max(0,Number((run.finishedAt||Date.now())-(run.startedAt||0))||0);
    lines.push(`run=${run.id||'—'} • status=${run.status||'UNKNOWN'} • duration=${Math.round(duration)} ms • steps=${(run.steps||[]).length}`);
    for(const x of run.steps||[])lines.push(`${x.status||'UNKNOWN'} • ${x.name||'step'} • ${Math.round(x.durationMs||0)} ms${x.detail?` • ${x.detail}`:''}${x.data?` • ${JSON.stringify(x.data)}`:''}`);
    if(Array.isArray(run.samples))lines.push(`samples=${run.samples.length}`);
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
    lines.push(...phaseRunSummaryLines('TIER 2 SOAK',soakRun));
    lines.push('');
    lines.push(...phaseRunSummaryLines('TIER 3 CHAOS',chaosRun));
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
    lines.push(`gameCenterProviders=${JSON.stringify(x.schedulers?.gameCenterProviders||{})}`);
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
    await step('playback: buffering health',async()=>{
      if(!h.started()||!h.programSize())return skip('no active playable program');
      const initial=h.playback();
      if(!['starting','buffering'].includes(initial.state))return {state:initial.state,stallCount:initial.stallCount||0,stallTotalMs:initial.stallTotalMs||0};
      try{
        const settled=await waitFor(()=>{const p=h.playback();return ['playing','paused','ready','ended'].includes(p.state)?p:null;},{timeoutMs:20000,label:'bounded buffering recovery'});
        return {from:initial.state,to:settled.state,initialMedia:initial.mediaKey,recoveredMedia:settled.mediaKey,recoveredByFailover:!!(initial.mediaKey&&settled.mediaKey&&initial.mediaKey!==settled.mediaKey),stallCount:settled.stallCount||0,stallTotalMs:settled.stallTotalMs||0};
      }catch(err){
        const p=h.playback();
        throw new Error(`buffering did not recover within 20000 ms • state=${p.state||initial.state} • media=${p.mediaKey||initial.mediaKey||'?'} • stalls=${p.stallCount||0}/${Math.round(p.stallTotalMs||0)}ms`);
      }
    });
    await step('playback: pause/resume ownership',async()=>{
      if(!h.started()||!h.programSize())return skip('no active playable program');
      // Ownership is tested independently from network health. A clip may be
      // buffering and still correctly obey deterministic pause/resume authority.
      assert(h.ensurePaused?.()!==false,'unable to command playback paused');
      const paused=await waitFor(()=>{const p=h.playback();return ['paused','ready'].includes(p.state)?p:null;},{timeoutMs:6000,label:'playback pause'});
      assert(audibleVideoCount(paused)===0,`video remained audible after pause: ${JSON.stringify(paused.audible)}`);
      assert(h.ensurePlaying?.()!==false,'unable to command playback resume');
      const resumed=await waitFor(()=>{const p=h.playback();return ['playing','starting','buffering'].includes(p.state)?p:null;},{timeoutMs:6000,label:'playback resume command'});
      assert(audibleVideoCount(resumed)<=1,'multiple audible slots after resume');assert(!String(resumed.invariant||'').startsWith('ERROR'),resumed.invariant);
      return {pausedState:paused.state,resumedState:resumed.state,audible:resumed.audible,streamingHealthy:resumed.state==='playing'};
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
  async function procedureRegressionHardening(){
    const h=hooks();
    await step('hardening: production startup has no demo seed',async()=>{assert(Number(h.demoSeedCount?.()||0)===0,'legacy demo seed is present');assert(h.roundupAutoplayEnabled?.()===false,'implicit roundup autoplay is enabled');return {demoSeedCount:h.demoSeedCount?.(),roundupAutoplayEnabled:h.roundupAutoplayEnabled?.()};});
    await step('hardening: date browsing cannot retune active media',async()=>{
      if(!h.started()||!h.currentMediaKey?.())return skip('no active media');
      const before=h.currentMediaKey(),date=h.scoreDate?.(),browse=h.yesterday?.();
      await h.setScoreDate?.(browse);await sleep(1250);
      assert(h.currentMediaKey()===before,`date browse changed active media: ${before} -> ${h.currentMediaKey()}`);
      if(date&&h.scoreDate?.()!==date)await h.setScoreDate?.(date);
      return {before,after:h.currentMediaKey(),browse};
    });
    await step('hardening: Game Center follows active game video',async()=>{
      if(!h.started()||!h.programSize?.())return skip('no active program');
      if(!h.activeOwnsGameCenter?.()){const moved=await h.stressTuneNextGame?.();if(!moved)return skip('no game-scoped program item available');await sleep(450);}
      assert(h.activeOwnsGameCenter?.()===true,'active media is not a game-scoped clip');
      assert(h.selectedEventMatchesActive?.()===true,'Game Center selected event does not match active video');
      return {mediaKey:h.currentMediaKey?.(),selectedEvent:h.selectedEvent?.()};
    },{warnAboveMs:4000});
    await step('hardening: manual pause remains latched for 25 seconds',async()=>{
      if(!h.started()||!h.currentMediaKey?.())return skip('no active media');
      const before=h.playback?.(),wasActive=['playing','starting','buffering'].includes(String(before?.state||''));
      assert(h.ensurePaused?.()!==false,'pause command rejected');
      const key=h.currentMediaKey(),t0=Number(h.currentTime?.()||0);
      for(let i=0;i<5;i++){await sleep(5000);h.refreshProgram?.();const pb=h.playback?.();assert(['paused','ready'].includes(String(pb?.state||'')),`playback resumed without user action at ${(i+1)*5}s: ${pb?.state}`);assert(h.currentMediaKey()===key,'paused media selection changed');}
      const t1=Number(h.currentTime?.()||0);if(t0>1&&t1>0)assert(Math.abs(t1-t0)<1.5,`paused currentTime moved ${t0.toFixed(1)} -> ${t1.toFixed(1)}`);
      if(wasActive)h.ensurePlaying?.();
      return {mediaKey:key,startTime:t0,endTime:t1,heldMs:25000};
    });
    await step('hardening: background program refresh cannot restart active clip',async()=>{
      if(!h.started()||!h.currentMediaKey?.())return skip('no active media');
      h.ensurePlaying?.();await sleep(600);const key=h.currentMediaKey(),pb0=h.playback?.(),sel0=pb0?.selectionId,t0=Number(h.currentTime?.()||0);
      for(let i=0;i<10;i++){h.refreshProgram?.();await sleep(220);assert(h.currentMediaKey()===key,'background refresh changed active media');}
      const pb1=h.playback?.(),t1=Number(h.currentTime?.()||0);assert(pb1?.selectionId===sel0,`background refresh created new playback selection ${sel0} -> ${pb1?.selectionId}`);if(t0>3&&t1>0)assert(t1>=t0-1,`active clip restarted ${t0.toFixed(1)} -> ${t1.toFixed(1)}`);return {mediaKey:key,selectionId:sel0,startTime:t0,endTime:t1};
    });
  }

  const PROCEDURE_RUNNERS={
    'release-handshake':procedureReleaseHandshake,'playback-cycle':procedurePlaybackCycle,'historical-read':procedureHistoricalRead,
    'operator-load':procedureOperatorLoad,'resource-modes':procedureResourceModes,'game-center':procedureGameCenter,
    'soundtrack':procedureSoundtrack,'ui-responsiveness':procedureUiResponsiveness,'regression-hardening':procedureRegressionHardening
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
  async function phaseStep(run,name,fn,{warnAboveMs=0}={}){
    const started=performance.now();let status='PASS',detail='',data=null;
    try{data=safe(await fn());}catch(err){status='FAIL';detail=String(err?.message||err);data={stack:String(err?.stack||'').slice(0,1600)};}
    const durationMs=Math.round(performance.now()-started);if(status==='PASS'&&warnAboveMs&&durationMs>warnAboveMs){status='WARN';detail=`slow step: ${durationMs} ms > ${warnAboveMs} ms`;}
    const row={name,status,durationMs,detail,data,at:Date.now()};run.steps.push(row);post(run.kind,status==='FAIL'?'ERROR':status==='WARN'?'WARN':'INFO',`${status} • ${name}`,{durationMs,detail,data,runId:run.id});return row;
  }
  function heapBytes(){try{return Number(performance?.memory?.usedJSHeapSize||0);}catch(_){return 0;}}
  async function withTimeout(task,timeoutMs,label='operation'){
    let timer=0;
    try{
      return await Promise.race([
        Promise.resolve().then(task),
        new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(`${label} timed out after ${timeoutMs} ms`)),timeoutMs);})
      ]);
    }finally{if(timer)clearTimeout(timer);}
  }
  async function runSoakTest({durationMs=900000,sampleMs=15000}={}){
    if(soakRun?.status==='RUNNING')return safe(soakRun);const h=hooks();stressStopRequested=false;
    durationMs=Math.max(60000,Number(durationMs)||900000);sampleMs=Math.max(5000,Number(sampleMs)||15000);
    const expectedSamples=Math.max(1,Math.floor(durationMs/sampleMs));
    const minimumSamples=Math.max(1,Math.floor(expectedSamples*0.90));
    const maxAllowedSampleGapMs=Math.round(sampleMs*2.5);
    const maxNoProgressMs=Math.max(30000,Math.min(45000,sampleMs*3));
    const maxBufferingMs=Math.max(30000,Math.min(45000,sampleMs*3));
    const transitionTimeoutMs=Math.max(8000,Math.min(12000,sampleMs-1000));
    const original={resourceMode:h.resourceMode?.(),scoreDate:h.scoreDate?.(),mediaKey:h.currentMediaKey?.(),playback:h.playback?.(),drawer:h.drawer?.()};
    soakRun={kind:'soak',id:`soak-${Date.now().toString(36)}`,status:'RUNNING',startedAt:Date.now(),finishedAt:0,durationTargetMs:durationMs,sampleMs,steps:[],samples:[],original,limits:{expectedSamples,minimumSamples,maxAllowedSampleGapMs,maxNoProgressMs,maxBufferingMs,transitionTimeoutMs}};
    post('soak','INFO','TIER 2 SOAK STARTED',{runId:soakRun.id,durationMs,sampleMs,expectedSamples,minimumSamples,maxAllowedSampleGapMs,maxNoProgressMs,maxBufferingMs,transitionTimeoutMs});
    const heap0=heapBytes();
    let priorKey=h.currentMediaKey?.()||'',priorTime=Number(h.currentTime?.()||0),priorSelection=Number(h.playback?.()?.selectionId||0),restartRegressions=0,maxHeap=heap0,transitions=0,transitionWindows=0;
    let nextSampleAt=soakRun.startedAt+sampleMs,lastSampleAt=soakRun.startedAt,maxSampleGapMs=0,longestNoProgressMs=0,longestBufferingMs=0,noProgressSince=0,bufferingSince=0,transitionTimeouts=0,decodeRecoveries=0,priorFailureCount=Number(h.playback?.()?.failureCount||0),priorError=String(h.playback?.()?.lastError||'');
    try{
      assert(h.started?.()===true,'Sports Big Board must be started before Tier 2 soak');assert(Number(h.programSize?.()||0)>0,'Tier 2 requires an active program');h.ensurePlaying?.();await sleep(700);priorKey=h.currentMediaKey?.()||priorKey;priorTime=Number(h.currentTime?.()||priorTime);priorSelection=Number(h.playback?.()?.selectionId||priorSelection);
      while(Date.now()-soakRun.startedAt<durationMs){
        if(stressStopRequested)throw new DOMException('soak stopped','AbortError');
        const waitMs=Math.max(0,nextSampleAt-Date.now());if(waitMs)await sleep(waitMs);
        const now=Date.now();if(now-soakRun.startedAt>durationMs+sampleMs)break;
        const sampleGapMs=now-lastSampleAt;maxSampleGapMs=Math.max(maxSampleGapMs,sampleGapMs);
        if(soakRun.samples.length&&sampleGapMs>maxAllowedSampleGapMs)throw new Error(`soak telemetry gap ${sampleGapMs} ms exceeded ${maxAllowedSampleGapMs} ms`);
        const pb=h.playback?.()||{},ctx=h.snapshot?.()||{},key=h.currentMediaKey?.()||'',ct=Number(h.currentTime?.()||0),heap=heapBytes(),state=String(pb.state||'');maxHeap=Math.max(maxHeap,heap);
        assert(!String(pb.invariant||'').startsWith('ERROR'),pb.invariant);assert(ctx.selectedEventMatchesActive!==false,'Game Center drifted from active game video');
        const selection=Number(pb.selectionId||0),sameMedia=!!key&&key===priorKey,sameSelection=sameMedia&&selection===priorSelection;
        if(sameMedia&&priorTime>10&&ct>0&&ct<priorTime-3&&!ctx.transitionInFlight){restartRegressions++;throw new Error(`same-media restart detected ${priorTime.toFixed(1)} -> ${ct.toFixed(1)}`);}
        if(sameMedia&&selection!==priorSelection&&!ctx.transitionInFlight)throw new Error(`same-media playback selection restarted ${priorSelection} -> ${selection}`);

        if(sameSelection&&state==='playing'&&!ctx.transitionInFlight){
          if(ct>priorTime+0.20){noProgressSince=0;}
          else{if(!noProgressSince)noProgressSince=lastSampleAt;const stuckMs=now-noProgressSince;longestNoProgressMs=Math.max(longestNoProgressMs,stuckMs);if(stuckMs>maxNoProgressMs)throw new Error(`playing without forward progress for ${stuckMs} ms at ${ct.toFixed(3)}s`);}
        }else noProgressSince=0;
        if(sameSelection&&state==='buffering'&&!ctx.transitionInFlight){
          if(!bufferingSince)bufferingSince=lastSampleAt;const bufferingMs=now-bufferingSince;longestBufferingMs=Math.max(longestBufferingMs,bufferingMs);if(bufferingMs>maxBufferingMs)throw new Error(`sustained buffering for ${bufferingMs} ms at ${ct.toFixed(3)}s`);
        }else bufferingSince=0;

        const failureCount=Number(pb.failureCount||0),lastError=String(pb.lastError||'');
        if(failureCount>priorFailureCount||lastError&&lastError!==priorError){
          if(/MEDIA_ERR_DECODE|PIPELINE_ERROR_DECODE/i.test(lastError))decodeRecoveries++;
          // Failure evidence is allowed only if the playback controller already
          // changed selection/media or recovered to an active state by this sample.
          if(sameSelection&&['failed','ready'].includes(state))throw new Error(`playback failure did not self-recover: ${lastError||`failureCount ${failureCount}`}`);
        }
        soakRun.samples.push({at:now,mediaKey:key,currentTime:ct,state,selectionId:selection,stallCount:pb.stallCount||0,failureCount,lastError,heapBytes:heap,selectedEventMatchesActive:ctx.selectedEventMatchesActive,sampleGapMs});
        lastSampleAt=now;priorKey=key;priorTime=ct;priorSelection=selection;priorFailureCount=failureCount;priorError=lastError;

        const elapsed=now-soakRun.startedAt,transitionWindow=Math.floor(elapsed/120000);
        if(elapsed>0&&transitionWindow>transitionWindows){
          transitionWindows=transitionWindow;let moved=false;
          try{moved=await withTimeout(()=>h.stressTuneNextGame?.(),transitionTimeoutMs,'soak game transition');}
          catch(err){transitionTimeouts++;throw err;}
          if(moved){transitions++;await sleep(500);assert(h.selectedEventMatchesActive?.()===true,'Game Center failed after soak transition');priorKey=h.currentMediaKey?.()||'';priorTime=Number(h.currentTime?.()||0);priorSelection=Number(h.playback?.()?.selectionId||0);noProgressSince=0;bufferingSince=0;}
        }
        if(soakRun.samples.length%4===0){const x=await fetchTimed(`/api/milestone/console?frontendVersion=${encodeURIComponent(VERSION)}&limit=40`,{timeoutMs:10000});assert(x.body?.problemCounts?.errors===0,`milestone errors during soak: ${x.body?.problemCounts?.errors}`);const workers=Object.values(x.body?.extra?.history?.workers||{});assert(!workers.length||workers.every(w=>w?.healthy===true),'worker became unhealthy during soak');}
        nextSampleAt+=sampleMs;while(nextSampleAt<=Date.now())nextSampleAt+=sampleMs;
      }
      const heapGrowth=maxHeap&&heap0?maxHeap-heap0:0;if(heap0&&heapGrowth>160*1024*1024&&maxHeap>heap0*2.5)throw new Error(`heap growth exceeded soak threshold: ${Math.round(heapGrowth/1048576)} MB`);
      const sampledSpanMs=soakRun.samples.length>1?Number(soakRun.samples.at(-1).at-soakRun.samples[0].at):0,coverageRatio=Math.min(1,soakRun.samples.length/expectedSamples),minimumSpanMs=Math.max(0,durationMs-(sampleMs*2.5));
      assert(soakRun.samples.length>=minimumSamples,`soak telemetry coverage too low: ${soakRun.samples.length}/${expectedSamples} samples`);
      assert(sampledSpanMs>=minimumSpanMs,`soak telemetry span too short: ${sampledSpanMs} ms < ${minimumSpanMs} ms`);
      await phaseStep(soakRun,'soak: extended stability summary',async()=>({durationMs:Date.now()-soakRun.startedAt,samples:soakRun.samples.length,expectedSamples,minimumSamples,coverageRatio,sampledSpanMs,maxSampleGapMs,maxAllowedSampleGapMs,transitions,transitionWindows,transitionTimeouts,restartRegressions,longestNoProgressMs,maxNoProgressMs,longestBufferingMs,maxBufferingMs,decodeRecoveries,heapStartBytes:heap0,heapMaxBytes:maxHeap,heapGrowthBytes:heapGrowth}));
      soakRun.coverage={samples:soakRun.samples.length,expectedSamples,minimumSamples,coverageRatio,sampledSpanMs,maxSampleGapMs,maxAllowedSampleGapMs,longestNoProgressMs,maxNoProgressMs,longestBufferingMs,maxBufferingMs,transitionWindows,transitionTimeouts,decodeRecoveries};
      soakRun.status=soakRun.steps.some(x=>x.status==='FAIL')?'FAIL':'PASS';
    }catch(err){soakRun.status=err?.name==='AbortError'?'STOPPED':'FAIL';soakRun.coverage={samples:soakRun.samples.length,expectedSamples,minimumSamples,coverageRatio:Math.min(1,soakRun.samples.length/expectedSamples),sampledSpanMs:soakRun.samples.length>1?Number(soakRun.samples.at(-1).at-soakRun.samples[0].at):0,maxSampleGapMs,maxAllowedSampleGapMs,longestNoProgressMs,maxNoProgressMs,longestBufferingMs,maxBufferingMs,transitionWindows,transitionTimeouts,decodeRecoveries};soakRun.steps.push({name:'soak: runtime',status:soakRun.status==='FAIL'?'FAIL':'WARN',durationMs:0,detail:String(err?.message||err),data:safe(soakRun.coverage),at:Date.now()});}
    finally{soakRun.finishedAt=Date.now();try{if(original.scoreDate&&h.scoreDate?.()!==original.scoreDate)await h.setScoreDate?.(original.scoreDate);}catch(_){}try{if(original.mediaKey&&h.currentMediaKey?.()!==original.mediaKey)await withTimeout(()=>h.restoreMediaKey?.(original.mediaKey),10000,'soak media restore');}catch(_){}try{if(original.resourceMode)await h.setResourceMode?.(original.resourceMode);}catch(_){}post('soak',soakRun.status==='PASS'?'INFO':'ERROR',`TIER 2 SOAK ${soakRun.status}`,{runId:soakRun.id,durationMs:soakRun.finishedAt-soakRun.startedAt,samples:soakRun.samples.length,coverage:soakRun.coverage});await refresh();}
    return safe(soakRun);
  }
  async function runChaosTest(){
    if(chaosRun?.status==='RUNNING')return safe(chaosRun);const h=hooks();stressStopRequested=false;const original={resourceMode:h.resourceMode?.(),scoreDate:h.scoreDate?.(),mediaKey:h.currentMediaKey?.(),playback:h.playback?.()};
    chaosRun={kind:'chaos',id:`chaos-${Date.now().toString(36)}`,status:'RUNNING',startedAt:Date.now(),finishedAt:0,steps:[],original};post('chaos','INFO','TIER 3 CONTROLLED CHAOS STARTED',{runId:chaosRun.id});
    try{
      await phaseStep(chaosRun,'chaos: live preflight',async()=>{assert(h.started?.()===true,'Sports Big Board must be started before Tier 3');assert(Number(h.programSize?.()||0)>0,'Tier 3 requires an active program');assert(!String(h.invariant?.()||'').startsWith('ERROR'),h.invariant?.());return {programSize:h.programSize?.(),mediaKey:h.currentMediaKey?.()};});
      await phaseStep(chaosRun,'chaos: background rerank storm preserves active clip',async()=>{const key=h.currentMediaKey?.();const sel=h.playback?.()?.selectionId;for(let i=0;i<40;i++){h.refreshProgram?.();if(i%5===0)await sleep(25);}assert(h.currentMediaKey?.()===key,'rerank storm changed active clip');assert(h.playback?.()?.selectionId===sel,'rerank storm created a new playback selection');return {mediaKey:key,selectionId:sel,bursts:40};});
      await phaseStep(chaosRun,'chaos: aborted request storm recovers',async()=>{const controllers=[];const jobs=[];for(let i=0;i<18;i++){const c=new AbortController();controllers.push(c);jobs.push(fetch(`/api/history/audit?limit=5&offset=${i*5}`,{cache:'no-store',signal:c.signal}).catch(e=>e?.name||String(e)));if(i%2===0)setTimeout(()=>c.abort(),5);}const settled=await Promise.allSettled(jobs);const recovery=await fetchTimed('/api/status',{timeoutMs:8000});assert(recovery.ok,'API did not recover after abort storm');return {requests:settled.length,recoveryMs:recovery.ms};},{warnAboveMs:5000});
      await phaseStep(chaosRun,'chaos: provider rate-limit circuit remains bounded',async()=>{
        const before=await fetchTimed(`/api/milestone/console?frontendVersion=${encodeURIComponent(VERSION)}&limit=30`,{timeoutMs:10000});
        const bs=before.body?.extra?.schedulers?.gameCenter||{},providers=before.body?.extra?.schedulers?.gameCenterProviders||{};
        const cooling=Object.values(providers).filter(x=>Number(x?.cooldownSeconds||0)>0);
        await sleep(1600);
        const after=await fetchTimed(`/api/milestone/console?frontendVersion=${encodeURIComponent(VERSION)}&limit=30`,{timeoutMs:10000});
        const as=after.body?.extra?.schedulers?.gameCenter||{};
        const bErr=Number(bs?.stats?.errors||0),aErr=Number(as?.stats?.errors||0),delta=Math.max(0,aErr-bErr),threads=Math.max(1,Number(as?.threadCount||bs?.threadCount||8));
        if(cooling.length)assert(delta<=threads,`provider cooldown amplified into ${delta} new scheduler errors with ${threads} workers`);
        return {coolingProviders:cooling.map(x=>({competition:x.competition,provider:x.provider,cooldownSeconds:x.cooldownSeconds})),errorDelta:delta,threadBound:threads,circuits:as?.circuits||{}};
      });
      await phaseStep(chaosRun,'chaos: invalid route is isolated from playback',async()=>{const key=h.currentMediaKey?.();const r=await fetch('/api/__sbb_chaos_expected_404__',{cache:'no-store'});assert(r.status>=400,'invalid route unexpectedly succeeded');await sleep(250);assert(h.currentMediaKey?.()===key,'invalid API response changed playback');assert(!String(h.invariant?.()||'').startsWith('ERROR'),h.invariant?.());return {status:r.status,mediaKey:key};});
      await phaseStep(chaosRun,'chaos: standby disruption self-recovers',async()=>{const before=h.currentMediaKey?.(),d=h.chaosDisruptStandby?.();await sleep(900);assert(h.currentMediaKey?.()===before,'standby disruption changed active clip');assert(!String(h.invariant?.()||'').startsWith('ERROR'),h.invariant?.());return d;});
      await phaseStep(chaosRun,'chaos: resource-mode turbulence restores',async()=>{const originalMode=h.resourceMode?.()||'balanced';for(let cycle=0;cycle<3;cycle++)for(const mode of ['playback','search','balanced']){await h.setResourceMode?.(mode);await sleep(180);assert(h.resourceMode?.()===mode,`failed mode ${mode}`);}await h.setResourceMode?.(originalMode);return {cycles:3,restored:h.resourceMode?.()};},{warnAboveMs:7000});
      await phaseStep(chaosRun,'chaos: repeated game transitions retain Game Center ownership',async()=>{let moved=0;for(let i=0;i<3;i++){if(await h.stressTuneNextGame?.()){moved++;await sleep(650);assert(h.selectedEventMatchesActive?.()===true,`Game Center mismatch after chaos transition ${i+1}`);assert(!String(h.invariant?.()||'').startsWith('ERROR'),h.invariant?.());}}if(!moved)return {transitions:0,note:'no alternate game items available'};return {transitions:moved};},{warnAboveMs:6000});
      await phaseStep(chaosRun,'chaos: manual pause survives concurrent API pressure',async()=>{if(!h.currentMediaKey?.())return {skipped:true};h.ensurePaused?.();const key=h.currentMediaKey?.();for(let round=0;round<4;round++){await Promise.allSettled(['/api/status','/api/history/catalog/integrity','/api/soundtrack/status'].map(u=>fetch(u,{cache:'no-store'})));h.refreshProgram?.();await sleep(1500);assert(['paused','ready'].includes(String(h.playback?.()?.state||'')),`pause escaped under load: ${h.playback?.()?.state}`);assert(h.currentMediaKey?.()===key,'pause pressure changed media');}return {mediaKey:key,heldMs:6000};});
      chaosRun.status=chaosRun.steps.some(x=>x.status==='FAIL')?'FAIL':chaosRun.steps.some(x=>x.status==='WARN')?'WARN':'PASS';
    }catch(err){chaosRun.status='FAIL';chaosRun.steps.push({name:'chaos: runtime',status:'FAIL',durationMs:0,detail:String(err?.message||err),data:null,at:Date.now()});}
    finally{chaosRun.finishedAt=Date.now();try{await h.setResourceMode?.(original.resourceMode||'balanced');}catch(_){}try{if(original.scoreDate&&h.scoreDate?.()!==original.scoreDate)await h.setScoreDate?.(original.scoreDate);}catch(_){}try{if(original.mediaKey&&h.currentMediaKey?.()!==original.mediaKey)await h.restoreMediaKey?.(original.mediaKey);}catch(_){}post('chaos',chaosRun.status==='PASS'?'INFO':'ERROR',`TIER 3 CONTROLLED CHAOS ${chaosRun.status}`,{runId:chaosRun.id,durationMs:chaosRun.finishedAt-chaosRun.startedAt});await refresh();}
    return safe(chaosRun);
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
  function open(){
    const m=$('milestoneConsoleModal');if(!m)return;
    // Dev Test is a modal workspace.  Keep the information drawer's logical state
    // untouched so procedures may exercise/restore Game Center behind the modal,
    // but visually suppress it while Dev Test owns the screen.
    document.body.classList.add('sbb-milestone-open');
    m.classList.remove('hidden');m.setAttribute('aria-hidden','false');
    refresh();clearInterval(pollTimer);pollTimer=setInterval(refresh,2500);renderProcedures();renderStress();
  }
  function close(){
    const m=$('milestoneConsoleModal');if(!m)return;
    m.classList.add('hidden');m.setAttribute('aria-hidden','true');
    document.body.classList.remove('sbb-milestone-open');
    clearInterval(pollTimer);pollTimer=0;try{refreshController?.abort('milestone console closed');}catch(_){}
  }
  async function reset(){try{await fetch('/api/milestone/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',cache:'no-store'});localEvents.length=0;stressRun=null;soakRun=null;chaosRun=null;procedureResults={};await refresh();renderStress();renderProcedures();}catch(err){remember('ERROR','milestone reset failed',{error:String(err)});}}
  async function resetObservationWindow(){try{await fetch('/api/milestone/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',cache:'no-store'});await refresh();}catch(err){remember('ERROR','milestone observation reset failed',{error:String(err)});throw err;}}
  function toggleProcedures(){const p=$('milestoneProceduresPanel'),btn=$('milestoneProceduresToggle');if(!p)return;const show=p.classList.contains('hidden');p.classList.toggle('hidden',!show);btn?.setAttribute('aria-expanded',show?'true':'false');if(show)renderProcedures();}
  function bind(){
    $('openMilestoneConsoleBtn')?.addEventListener('click',open);$('milestoneConsoleClose')?.addEventListener('click',close);$('milestoneConsoleBackdrop')?.addEventListener('click',close);
    $('milestoneConsoleRefresh')?.addEventListener('click',refresh);$('milestoneConsoleCopy')?.addEventListener('click',copyText);$('milestoneConsoleDownload')?.addEventListener('click',saveText);$('milestoneConsoleReset')?.addEventListener('click',reset);
    $('milestoneStressRun')?.addEventListener('click',runStressTest);$('milestoneStressStop')?.addEventListener('click',stopStressTest);$('milestoneProceduresToggle')?.addEventListener('click',toggleProcedures);$('milestoneProceduresRunAll')?.addEventListener('click',runAllProcedures);
    renderProcedures();renderStress();heartbeat();heartbeatTimer=setInterval(heartbeat,10000);setTimeout(refresh,1800);
  }
  window.SBB_MILESTONE=Object.freeze({version:'1.3',release:VERSION,open,close,refresh,reset,resetObservationWindow,text:textSnapshot,record:post,runStressTest,runSoakTest,runChaosTest,stopStressTest,runProcedure,procedures:PROCEDURES.map(x=>({...x})),get stress(){return safe(stressRun);},get soak(){return safe(soakRun);},get chaos(){return safe(chaosRun);},get procedureResults(){return safe(procedureResults);},get snapshot(){return latest;}});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
})();

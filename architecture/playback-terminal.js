/* Sports Big Board v4.4.3 — Dev Playback Terminal + automated endurance test.
   The terminal observes the canonical playback session and drives endurance actions
   only through SBB_DEV_TEST_HOOKS, preserving PlaybackController as sole authority. */
(() => {
  'use strict';
  if(window.SBB_PLAYBACK_TERMINAL)return;

  const rows=[],bySession=new Map();let lastSessionId='',tickTimer=null,enduranceTimer=null;
  const now=()=>performance.now();
  const epoch=()=>Date.now();
  const fmtMs=ms=>`${(Math.max(0,Number(ms)||0)/1000).toFixed(1)}s`;
  const fmtClock=ms=>{const s=Math.max(0,Math.floor(Number(ms||0)/1000));return `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;};
  const clean=(v,n=160)=>String(v??'').replace(/\s+/g,' ').trim().slice(0,n);
  const esc=v=>clean(v,500).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  function devEnabled(){return window.SBB_DEV_MODE?.isEnabled?.()===true||document.body?.classList.contains('dev-mode')||document.body?.dataset?.sbbDev==='1';}
  function hooks(){return window.SBB_DEV_TEST_HOOKS||null;}

  function durationFor(row,kind,t=now()){
    let total=Number(row[kind+'Ms']||0);if(row.state===kind&&row.stateStartedPerf)total+=Math.max(0,t-row.stateStartedPerf);return total;
  }
  function finalizeState(row,t=now()){
    if(!row?.stateStartedPerf)return;
    const delta=Math.max(0,t-row.stateStartedPerf);
    if(row.state==='playing')row.playingMs+=delta;
    if(row.state==='buffering')row.bufferingMs+=delta;
    row.stateStartedPerf=0;
  }

  const PHASES=Object.freeze([
    Object.freeze({id:'warmup',label:'WARMUP',durationMs:5*60_000,transitionMs:60_000,disruptStandby:false}),
    Object.freeze({id:'soak',label:'SOAK',durationMs:15*60_000,transitionMs:35_000,disruptStandby:false}),
    Object.freeze({id:'hammer',label:'HAMMER',durationMs:10*60_000,transitionMs:15_000,disruptStandby:true})
  ]);
  const ENDURANCE_TOTAL_MS=PHASES.reduce((n,p)=>n+p.durationMs,0);
  const FIRST_FRAME_WATCHDOG_MS=28_000;
  const MIN_SUCCESSFUL_STARTS=12;
  const MIN_TRANSITIONS=10;
  let endurance={};

  function freshEndurance(status='IDLE'){
    return {
      runId:'',status,reason:'',startedAt:0,endedAt:0,phase:'IDLE',phaseLabel:'IDLE',phaseStartedAt:0,nextTransitionAt:0,
      successfulStarts:0,transitions:0,crossGameTransitions:0,standbyDisruptions:0,noFrameStreak:0,maxNoFrameStreak:0,
      recoveryAttempts:0,recoveredAfterReset:0,recoveryArmed:false,engineIncidentsBase:0,engineResetsBase:0,
      engineIncidents:0,engineResets:0,lastAction:'',lastActionAt:0,lastFirstFrameAt:0,lastRecap:null,duplicateRecaps:0,
      actionBusy:false,noCandidateCount:0,savedResourceMode:'balanced',savedMediaKey:'',savedScoreDate:'',events:[]
    };
  }
  endurance=freshEndurance();

  function enduranceLog(type,message,extra={}){
    const entry={at:epoch(),type:clean(type,32),message:clean(message,220),...extra};
    endurance.events.push(entry);if(endurance.events.length>80)endurance.events=endurance.events.slice(-80);
    endurance.lastAction=entry.message;endurance.lastActionAt=entry.at;
    return entry;
  }
  function endurancePhaseAt(elapsed){
    let cursor=0;
    for(const p of PHASES){if(elapsed<cursor+p.durationMs)return {...p,offsetMs:cursor};cursor+=p.durationMs;}
    return null;
  }
  function enduranceSnapshot(){
    const h=hooks(),engine=h?.playbackEngine?.()||{};
    if(endurance.startedAt){
      endurance.engineIncidents=Math.max(0,Number(engine.incidents||0)-Number(endurance.engineIncidentsBase||0));
      endurance.engineResets=Math.max(0,Number(engine.resets||0)-Number(endurance.engineResetsBase||0));
    }
    const elapsed=endurance.startedAt?Math.min(ENDURANCE_TOTAL_MS,Math.max(0,(endurance.endedAt||epoch())-endurance.startedAt)):0;
    return {...endurance,elapsedMs:elapsed,totalMs:ENDURANCE_TOTAL_MS,remainingMs:Math.max(0,ENDURANCE_TOTAL_MS-elapsed),progress:ENDURANCE_TOTAL_MS?elapsed/ENDURANCE_TOTAL_MS:0,events:[...endurance.events]};
  }
  function setEnduranceStatus(status,reason=''){
    endurance.status=status;endurance.reason=clean(reason,240);if(['PASS','FAIL','STOPPED'].includes(status))endurance.endedAt=epoch();render();
  }
  async function restoreAfterEndurance(){
    const h=hooks();if(!h)return;
    try{if(endurance.savedMediaKey)await h.restoreMediaKey?.(endurance.savedMediaKey);}catch(_){ }
    try{if(endurance.savedResourceMode)await h.setResourceMode?.(endurance.savedResourceMode);}catch(_){ }
  }
  function finishEndurance(status,reason){
    if(endurance.status!=='RUNNING')return;
    endurance.actionBusy=false;setEnduranceStatus(status,reason);enduranceLog(status.toLowerCase(),reason||status);
    restoreAfterEndurance();
  }
  function failEndurance(reason){finishEndurance('FAIL',reason);}
  function passEndurance(){
    if(endurance.successfulStarts<MIN_SUCCESSFUL_STARTS)return failEndurance(`INSUFFICIENT_FIRST_FRAMES ${endurance.successfulStarts}/${MIN_SUCCESSFUL_STARTS}`);
    if(endurance.transitions<MIN_TRANSITIONS)return failEndurance(`INSUFFICIENT_TRANSITIONS ${endurance.transitions}/${MIN_TRANSITIONS}`);
    finishEndurance('PASS',`30-minute endurance passed • ${endurance.successfulStarts} starts • ${endurance.transitions} transitions`);
  }
  function stopEndurance(){
    if(endurance.status!=='RUNNING')return false;
    endurance.actionBusy=false;setEnduranceStatus('STOPPED','Operator stopped endurance test');enduranceLog('stop','Operator stopped endurance test');restoreAfterEndurance();return true;
  }

  function scheduleRecoveryAdvance(reason='no first frame'){
    const h=hooks();if(!h||endurance.actionBusy||endurance.status!=='RUNNING')return;
    endurance.actionBusy=true;
    const runId=endurance.runId;
    setTimeout(async()=>{
      try{
        if(endurance.status!=='RUNNING'||endurance.runId!==runId)return;
        let moved=await Promise.resolve(h.stressTuneNextGame?.());
        if(!moved)moved=await Promise.resolve(h.stressTuneNext?.());
        endurance.transitions+=moved?1:0;endurance.crossGameTransitions+=moved?1:0;
        enduranceLog('recovery',moved?`Recovery advanced after ${reason}`:`Recovery found no alternate after ${reason}`);
      }catch(err){enduranceLog('recovery-error',`Recovery advance failed: ${err?.message||err}`);}
      finally{if(endurance.runId===runId)endurance.actionBusy=false;}
    },endurance.recoveryArmed?1300:350);
  }
  function noteNoFrame(row,reason='session left without first frame'){
    if(!row||row.noFrameCounted||row.enduranceRunId!==endurance.runId||endurance.status!=='RUNNING')return;
    row.noFrameCounted=true;endurance.noFrameStreak++;endurance.maxNoFrameStreak=Math.max(endurance.maxNoFrameStreak,endurance.noFrameStreak);
    enduranceLog('no-frame',`${reason} • streak ${endurance.noFrameStreak}`,{sessionId:row.sessionId,mediaKey:row.mediaKey});
    if(endurance.recoveryArmed)return failEndurance(`UNRECOVERABLE_NO_FIRST_FRAME after engine reset • ${clean(row.title,90)}`);
    if(endurance.noFrameStreak>=2){
      endurance.recoveryAttempts++;endurance.recoveryArmed=true;
      let reset=false;try{reset=hooks()?.forcePlaybackEngineReset?.()===true;}catch(_){ }
      enduranceLog('engine-reset',reset?'Automatic playback-engine reset triggered':'Playback-engine reset request was unavailable');
    }
    scheduleRecoveryAdvance(reason);
  }
  function noteFirstFrame(row){
    if(!row||row.firstFrameCounted||row.enduranceRunId!==endurance.runId||endurance.status!=='RUNNING')return;
    row.firstFrameCounted=true;endurance.successfulStarts++;endurance.lastFirstFrameAt=epoch();endurance.noFrameStreak=0;
    if(endurance.recoveryArmed){endurance.recoveredAfterReset++;endurance.recoveryArmed=false;enduranceLog('recovered',`First frame recovered after reset • ${clean(row.title,90)}`);}
    let isRecap=false,currentKey='';
    try{const h=hooks();currentKey=clean(h?.currentMediaKey?.(),500);if(!currentKey||currentKey===row.mediaKey)isRecap=h?.currentIsFullRecap?.()===true;}catch(_){ }
    row.isRecap=isRecap;
    if(isRecap&&row.eventKey){
      const previous=endurance.lastRecap;
      if(previous&&previous.eventKey===row.eventKey&&previous.mediaKey!==row.mediaKey){
        endurance.duplicateRecaps++;
        return failEndurance(`DUPLICATE_GAME_RECAP • same game switched recap assets: ${clean(previous.title,70)} → ${clean(row.title,70)}`);
      }
      endurance.lastRecap={eventKey:row.eventKey,mediaKey:row.mediaKey,title:row.title,sessionId:row.sessionId};
    }
  }

  function ingest(session,t=now()){
    session=session||{};const sid=clean(session.sessionId||`selection-${session.selectionId||0}`,120);if(!sid)return null;
    if(lastSessionId&&lastSessionId!==sid){
      const prev=bySession.get(lastSessionId);
      if(prev){finalizeState(prev,t);if(!['failed','ended'].includes(prev.state))prev.exitState=prev.firstFrameAt?'LEFT':'SKIPPED/NO FRAME';if(!prev.firstFrameAt)noteNoFrame(prev,'session changed before first frame');}
    }
    lastSessionId=sid;let row=bySession.get(sid);
    if(!row){
      row={sessionId:sid,selectionId:Number(session.selectionId||0),eventKey:clean(session.eventKey||'',240),title:clean(session.title||'Untitled',120),league:clean(session.league||'',20),provider:clean(session.provider||'',32),transport:clean(session.transport||'',28),mediaKey:clean(session.mediaKey||'',500),source:clean(session.sourceExternalUrl||session.sourceUrl||'',500),state:'selected',stateStartedPerf:t,playingMs:0,bufferingMs:0,firstFrameAt:0,firstFrameMs:null,firstFrameCounted:false,noFrameCounted:false,isRecap:false,stallCount:0,sessionStallTotalMs:0,failureCount:0,lastError:'',createdPerf:t,selectedAt:Number(session.selectedAt||epoch()),exitState:'',enduranceRunId:endurance.status==='RUNNING'?endurance.runId:''};
      bySession.set(sid,row);rows.unshift(row);if(rows.length>40){const gone=rows.pop();bySession.delete(gone.sessionId);}
    }
    const nextState=clean(session.state||row.state,24).toLowerCase();
    if(nextState&&nextState!==row.state){finalizeState(row,t);row.state=nextState;row.stateStartedPerf=t;}
    row.eventKey=clean(session.eventKey||row.eventKey,240);row.title=clean(session.title||row.title,120);row.league=clean(session.league||row.league,20);row.provider=clean(session.provider||row.provider,32);row.transport=clean(session.transport||row.transport,28);row.mediaKey=clean(session.mediaKey||row.mediaKey,500);row.source=clean(session.sourceExternalUrl||session.sourceUrl||row.source,500);
    const hadFrame=!!row.firstFrameAt;row.firstFrameAt=Math.max(Number(row.firstFrameAt||0),Number(session.firstFrameAt||0));if(session.firstFrameMs!=null)row.firstFrameMs=Number(session.firstFrameMs);
    row.stallCount=Math.max(Number(row.stallCount||0),Number(session.stallCount||0));row.sessionStallTotalMs=Math.max(Number(row.sessionStallTotalMs||0),Number(session.stallTotalMs||0));row.failureCount=Math.max(Number(row.failureCount||0),Number(session.failureCount||0));row.lastError=clean(session.lastError||row.lastError,180);
    if(!hadFrame&&row.firstFrameAt)noteFirstFrame(row);
    if(row.state==='failed'&&!row.firstFrameAt)setTimeout(()=>noteNoFrame(row,`session failed before first frame${row.lastError?`: ${row.lastError}`:''}`),500);
    render();return row;
  }

  function snapshot(){const t=now();return rows.map(r=>({...r,playTimeMs:durationFor(r,'playing',t),bufferTimeMs:Math.max(durationFor(r,'buffering',t),Number(r.sessionStallTotalMs||0))}));}
  function clear(){rows.splice(0);bySession.clear();lastSessionId='';render();}

  async function enduranceTransition(phase){
    const h=hooks();if(!h||endurance.actionBusy||endurance.status!=='RUNNING')return;
    const current=bySession.get(lastSessionId);
    if(current&&!current.firstFrameAt){endurance.nextTransitionAt=epoch()+2500;return;}
    endurance.actionBusy=true;const beforeKey=clean(h.currentGameKey?.(),240),runId=endurance.runId;
    try{
      if(phase.disruptStandby){try{h.chaosDisruptStandby?.();endurance.standbyDisruptions++;enduranceLog('standby-disrupt',`Hammer disrupted standby before transition ${endurance.transitions+1}`);}catch(err){enduranceLog('standby-disrupt-error',clean(err?.message||err,140));}}
      let moved=await Promise.resolve(h.stressTuneNextGame?.());
      if(!moved)moved=await Promise.resolve(h.stressTuneNext?.());
      if(moved){
        endurance.transitions++;const afterKey=clean(h.currentGameKey?.(),240);if(!beforeKey||!afterKey||beforeKey!==afterKey)endurance.crossGameTransitions++;
        endurance.noCandidateCount=0;enduranceLog('transition',`${phase.label} transition ${endurance.transitions}${phase.disruptStandby?' after standby disruption':''}`);
      }else{
        endurance.noCandidateCount++;enduranceLog('no-candidate',`${phase.label} found no next playable program (${endurance.noCandidateCount})`);
        if(endurance.noCandidateCount>=4)failEndurance('INSUFFICIENT_PROGRAM • no alternate playable item after four attempts');
      }
    }catch(err){enduranceLog('transition-error',`Transition failed: ${err?.message||err}`);}
    finally{
      if(endurance.runId===runId){endurance.actionBusy=false;endurance.nextTransitionAt=epoch()+phase.transitionMs;}
    }
  }

  async function startEndurance(){
    if(endurance.status==='RUNNING')return false;
    const h=hooks();
    if(!devEnabled()||!h)return false;
    const engine=h.playbackEngine?.()||{};endurance=freshEndurance('RUNNING');endurance.runId=`end-${epoch().toString(36)}`;endurance.startedAt=epoch();endurance.phase='warmup';endurance.phaseLabel='WARMUP';endurance.phaseStartedAt=endurance.startedAt;endurance.nextTransitionAt=endurance.startedAt+30_000;endurance.savedResourceMode=clean(h.resourceMode?.()||'balanced',24);endurance.savedMediaKey=clean(h.currentMediaKey?.(),500);endurance.savedScoreDate=clean(h.scoreDate?.(),20);endurance.engineIncidentsBase=Number(engine.incidents||0);endurance.engineResetsBase=Number(engine.resets||0);
    enduranceLog('start','30-minute endurance started • 5m warmup → 15m soak → 10m hammer');clear();
    try{await h.setResourceMode?.('playback');}catch(err){return failEndurance(`PLAYBACK_MODE_FAILED • ${err?.message||err}`);}
    try{h.start?.();h.ensurePlaying?.();}catch(err){return failEndurance(`PLAYBACK_START_FAILED • ${err?.message||err}`);}
    if(Number(h.programSize?.()||0)<2)return failEndurance('INSUFFICIENT_PROGRAM • endurance requires at least two program items');
    try{const current=window.SBB_PLAYBACK_SESSION?.snapshot?.();if(current?.sessionId)ingest(current);}catch(_){ }
    render();return true;
  }

  function enduranceTick(){
    if(endurance.status!=='RUNNING')return;
    const h=hooks();if(!h)return failEndurance('DEV_HOOKS_LOST');
    const elapsed=epoch()-endurance.startedAt,phase=endurancePhaseAt(elapsed);
    if(!phase)return passEndurance();
    if(endurance.phase!==phase.id){endurance.phase=phase.id;endurance.phaseLabel=phase.label;endurance.phaseStartedAt=epoch();endurance.nextTransitionAt=epoch()+Math.min(15_000,phase.transitionMs);enduranceLog('phase',`${phase.label} phase started`);}
    const invariant=clean(h.invariant?.()||'OK',140);if(invariant.startsWith('ERROR'))return failEndurance(`PLAYBACK_INVARIANT • ${invariant}`);
    const current=bySession.get(lastSessionId),age=current?epoch()-Number(current.selectedAt||epoch()):0;
    if(current&&current.enduranceRunId===endurance.runId&&!current.firstFrameAt&&age>=FIRST_FRAME_WATCHDOG_MS&&!current.noFrameCounted){noteNoFrame(current,`first-frame watchdog ${Math.round(age/1000)}s`);return;}
    if(epoch()>=endurance.nextTransitionAt&&!endurance.actionBusy)enduranceTransition(phase);
    renderEndurance();
  }

  function renderEndurance(){
    const status=document.getElementById('playbackEnduranceStatus'),detail=document.getElementById('playbackEnduranceDetail'),bar=document.getElementById('playbackEnduranceProgress'),start=document.getElementById('playbackEnduranceStart'),stop=document.getElementById('playbackEnduranceStop');
    if(!status||!detail)return;
    const s=enduranceSnapshot();status.textContent=s.status;status.dataset.state=s.status.toLowerCase();
    if(s.status==='RUNNING')detail.textContent=`${s.phaseLabel} ${fmtClock(s.elapsedMs)} / 30:00 • STARTS ${s.successfulStarts} • XITIONS ${s.transitions} • NOFRAME ${s.noFrameStreak} • RESETS ${s.engineResets} • DISRUPT ${s.standbyDisruptions}`;
    else if(['PASS','FAIL','STOPPED'].includes(s.status))detail.textContent=`${s.reason} • ${fmtClock(s.elapsedMs)} • STARTS ${s.successfulStarts} • XITIONS ${s.transitions} • RESETS ${s.engineResets}`;
    else detail.textContent='30:00 • 5m warmup → 15m soak → 10m hammer • automatic recovery + duplicate-recap guard';
    if(bar)bar.style.width=`${Math.max(0,Math.min(100,s.progress*100)).toFixed(1)}%`;
    if(start)start.disabled=s.status==='RUNNING';if(stop)stop.disabled=s.status!=='RUNNING';
  }

  function render(){
    const host=document.getElementById('playbackTerminal');if(!host)return;host.classList.toggle('is-visible',devEnabled());if(!devEnabled())return;
    const body=document.getElementById('playbackTerminalRows'),summary=document.getElementById('playbackTerminalSummary');if(!body||!summary)return;
    const data=snapshot(),rt=window.SBB_ULTIMATE_PLAYBACK?.runtimeSnapshot?.()||{},metrics=rt.metrics||window.SBB_ULTIMATE_PLAYBACK?.metrics?.()||{},engine=hooks()?.playbackEngine?.()||{};
    const totalPlay=data.reduce((a,r)=>a+r.playTimeMs,0),totalBuffer=data.reduce((a,r)=>a+r.bufferTimeMs,0),ratio=totalPlay?100*totalBuffer/totalPlay:0;
    summary.textContent=`PLAY ${fmtMs(totalPlay)}  •  BUFFER ${fmtMs(totalBuffer)} (${ratio.toFixed(1)}%)  •  HOT ${Number(metrics.hotStandbyHitRate??100).toFixed(1)}%  •  RUNWAY ${rt.bufferAhead==null?'—':Number(rt.bufferAhead).toFixed(1)+'s'}  •  ENGINE ${Number(engine.incidents||0)}I/${Number(engine.resets||0)}R  •  NEXT ${rt.standby?.ready?'HOT_READY':rt.standby?.warming?'WARMING':'IDLE'}`;
    body.innerHTML=data.slice(0,20).map((r,i)=>{const item={mediaKey:r.mediaKey,competitionId:r.league,provider:r.provider,transport:r.transport};const ready=window.SBB_PLAYBACK_READINESS?.state?.(item)||'DISCOVERED',score=window.SBB_PLAYBACK_READINESS?.score?.(item)??80;const status=r.exitState||r.state.toUpperCase();const src=r.source?` title="${esc(r.source)}"`:'';return `<div class="pt-row"><span>${String(data.length-i).padStart(2,'0')}</span><b class="pt-state">${esc(status)}</b><span>${esc(r.league||'—')}</span><span>${esc(r.transport||'—')}</span><span>${esc(r.provider||'—')}</span><span>${fmtMs(r.playTimeMs)}</span><span>${fmtMs(r.bufferTimeMs)}</span><span>${r.stallCount}</span><span>${r.firstFrameMs==null?'—':Math.round(r.firstFrameMs)+'ms'}</span><span>${esc(ready)}</span><span>${Math.round(Number(score||0))}</span><span${src}>${esc(r.title||'Untitled')}</span></div>`;}).join('')||'<div class="pt-empty">Waiting for playback sessions…</div>';
    renderEndurance();
  }

  window.addEventListener?.('sbb:playback-session',ev=>ingest(ev?.detail||{}));
  window.addEventListener?.('sbb:playback-engine',ev=>{if(endurance.status==='RUNNING')enduranceLog('engine',`ENGINE ${clean(ev?.detail?.type||'event',30).toUpperCase()} • ${clean(ev?.detail?.reason||'',120)}`);render();});
  window.addEventListener?.('sbb:dev-mode',render);
  document.addEventListener('DOMContentLoaded',()=>{
    document.getElementById('playbackTerminalClear')?.addEventListener('click',clear);
    document.getElementById('playbackTerminalCopy')?.addEventListener('click',()=>{const s=enduranceSnapshot();const head=`ENDURANCE\t${s.status}\t${s.phaseLabel}\tELAPSED=${fmtClock(s.elapsedMs)}\tSTARTS=${s.successfulStarts}\tTRANSITIONS=${s.transitions}\tNOFRAME_MAX=${s.maxNoFrameStreak}\tRESETS=${s.engineResets}\t${s.reason}`;const lines=snapshot().map(r=>`${r.league}\t${r.transport}\t${r.provider}\tPLAY=${fmtMs(r.playTimeMs)}\tBUFFER=${fmtMs(r.bufferTimeMs)}\tSTALLS=${r.stallCount}\tSTART=${r.firstFrameMs??''}\tEVENT=${r.eventKey}\t${r.title}`);navigator.clipboard?.writeText?.([head,...lines].join('\n')).catch(()=>{});});
    document.getElementById('playbackEnduranceStart')?.addEventListener('click',()=>startEndurance());
    document.getElementById('playbackEnduranceStop')?.addEventListener('click',stopEndurance);
    render();tickTimer=setInterval(render,500);enduranceTimer=setInterval(enduranceTick,1000);
  });
  try{const s=window.SBB_PLAYBACK_SESSION?.snapshot?.();if(s?.sessionId)ingest(s);}catch(_){ }
  window.SBB_PLAYBACK_TERMINAL=Object.freeze({version:'1.1',snapshot,clear,ingest,render,endurance:Object.freeze({start:startEndurance,stop:stopEndurance,snapshot:enduranceSnapshot,phases:PHASES,totalMs:ENDURANCE_TOTAL_MS})});
})();

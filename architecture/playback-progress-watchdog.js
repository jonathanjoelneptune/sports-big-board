/* Sports Big Board v4.8.0 — Playback Progress Watchdog.
   Production recovery authority for the gap between provider state and actual
   media progress. A provider may report PLAYING before decoded media time moves.
   We require the transport clock to advance, issue one soft play kick, then hand
   control to the canonical playback failure/fallback controller. No game, league,
   provider account, team, or event identity is special-cased.
*/
(() => {
  'use strict';
  if(window.SBB_PLAYBACK_PROGRESS_WATCHDOG)return;

  const VERSION='1.0';
  const PROGRESS_EPSILON_SECONDS=.20;
  const PROGRESS_SOFT_KICK_MS=3500;
  const PROGRESS_RECOVERY_MS=8000;
  const WAIT_TIMEOUT_MS=12500;
  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const n=v=>Number(v||0)||0;
  const round=v=>Number.isFinite(Number(v))?Math.round(Number(v)*10)/10:null;
  const now=()=>performance.now();
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const progress={
    installed:false,selectionId:0,sessionId:'',mediaKey:'',slot:'',provider:'',transport:'',
    selectedPerf:0,baselineClock:null,lastClock:null,firstProgressAt:0,firstProgressMs:null,
    confirmed:false,softKicks:0,recoveries:0,timeouts:0,lastReason:'',history:[],timer:null,off:null
  };

  function snapshot(){return {
    version:VERSION,installed:progress.installed,selectionId:progress.selectionId,sessionId:progress.sessionId,
    mediaKey:progress.mediaKey,slot:progress.slot,provider:progress.provider,transport:progress.transport,
    firstProgressMs:progress.firstProgressMs,confirmed:progress.confirmed,softKicks:progress.softKicks,
    recoveries:progress.recoveries,timeouts:progress.timeouts,lastReason:progress.lastReason,
    history:progress.history.slice(-40)
  };}
  function transportClock(session){
    const slot=clean(session?.slot||progress.slot||((typeof activeSlot!=='undefined')?activeSlot:''));
    const provider=upper(session?.provider||progress.provider),transport=upper(session?.transport||progress.transport);
    try{
      if(provider.includes('YOUTUBE')||transport.includes('YOUTUBE')){
        const bank=(typeof players!=='undefined')?players:null,p=bank?.[slot],clock=Number(p?.getCurrentTime?.());
        return {kind:'YOUTUBE',slot,clock:Number.isFinite(clock)?clock:null,state:Number(p?.getPlayerState?.()),ready:!!p};
      }
    }catch(_){}
    try{
      const v=(typeof nativeEl==='function')?nativeEl(slot):document.getElementById(`native${slot}`);
      if(v&&(provider.includes('DIRECT')||transport.includes('DIRECT')||transport.includes('NATIVE')||transport.includes('BROWSER_HOT'))){
        const clock=Number(v.currentTime);return {kind:'DIRECT_VIDEO',slot,clock:Number.isFinite(clock)?clock:null,state:v.paused?'paused':(v.readyState>=2?'playing':'loading'),ready:v.readyState>=1};
      }
    }catch(_){}
    return {kind:transport||provider||'UNKNOWN',slot,clock:null,state:'unknown',ready:false};
  }
  function record(type,extra={}){
    const row={at:Date.now(),type,selectionId:progress.selectionId,mediaKey:progress.mediaKey,...extra};
    progress.history.push(row);if(progress.history.length>80)progress.history=progress.history.slice(-80);return row;
  }
  function startSelection(session){
    progress.selectionId=n(session?.selectionId);progress.sessionId=clean(session?.sessionId);progress.mediaKey=clean(session?.mediaKey);
    progress.slot=clean(session?.slot);progress.provider=upper(session?.provider);progress.transport=upper(session?.transport);
    progress.selectedPerf=now();progress.baselineClock=null;progress.lastClock=null;progress.firstProgressAt=0;progress.firstProgressMs=null;progress.confirmed=false;progress.lastReason='';
    record('selection',{provider:progress.provider,transport:progress.transport,slot:progress.slot});
  }
  function softKick(clock){
    try{
      const slot=clock.slot||progress.slot;
      if(clock.kind==='YOUTUBE'){
        const bank=(typeof players!=='undefined')?players:null;bank?.[slot]?.playVideo?.();
      }else if(clock.kind==='DIRECT_VIDEO'){
        const v=(typeof nativeEl==='function')?nativeEl(slot):document.getElementById(`native${slot}`),p=v?.play?.();if(p?.catch)p.catch(()=>{});
      }else return false;
      progress.softKicks++;progress.lastReason='soft playback kick after non-advancing start';record('soft-kick',{clock:clock.clock});return true;
    }catch(_){return false;}
  }
  function delegateStuckRecovery(clock){
    if(progress.lastReason==='recovery-delegated')return;
    progress.lastReason='recovery-delegated';progress.recoveries++;progress.timeouts++;
    record('recovery',{clock:clock.clock,elapsedMs:round(now()-progress.selectedPerf)});
    const err=new Error(`Playback transport reported start but media clock did not advance within ${PROGRESS_RECOVERY_MS} ms`);
    try{
      const paused=(typeof manualPauseRequested!=='undefined')&&manualPauseRequested;if(paused||document.hidden)return;
      if(typeof handlePlaybackFailure==='function')handlePlaybackFailure(clock.slot||progress.slot,err,false);
      else window.SBB_PLAYBACK_SESSION?.fail?.(err,{slot:clock.slot||progress.slot,provider:progress.provider,transport:progress.transport});
    }catch(failErr){try{window.SBB_PLAYBACK_SESSION?.fail?.(failErr);}catch(_) {}}
  }
  function tick(){
    if(!progress.installed||!progress.sessionId||progress.confirmed)return;
    const session=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{};
    if(clean(session.sessionId)!==progress.sessionId||!progress.mediaKey||clean(session.mediaKey)!==progress.mediaKey)return;
    const stateName=clean(session.state).toLowerCase();
    if(['paused','ended','failed','idle'].includes(stateName))return;
    if((typeof manualPauseRequested!=='undefined')&&manualPauseRequested)return;
    const clock=transportClock(session),elapsed=now()-progress.selectedPerf;
    if(clock.clock!=null){
      if(progress.baselineClock==null){progress.baselineClock=clock.clock;progress.lastClock=clock.clock;record('clock-baseline',{clock:clock.clock,kind:clock.kind});}
      else{
        progress.lastClock=clock.clock;
        if(clock.clock-progress.baselineClock>=PROGRESS_EPSILON_SECONDS){
          progress.confirmed=true;progress.firstProgressAt=Date.now();progress.firstProgressMs=Math.max(0,Math.round(elapsed));progress.lastReason='media clock advancing';
          record('confirmed',{clock:clock.clock,delta:round(clock.clock-progress.baselineClock),firstProgressMs:progress.firstProgressMs});
          try{window.dispatchEvent(new CustomEvent('sbb:playback-progress-confirmed',{detail:snapshot()}));}catch(_){}
          return;
        }
      }
    }
    const alreadyKicked=progress.history.some(x=>x.selectionId===progress.selectionId&&x.type==='soft-kick');
    if(elapsed>=PROGRESS_SOFT_KICK_MS&&!alreadyKicked)softKick(clock);
    if(elapsed>=PROGRESS_RECOVERY_MS)delegateStuckRecovery(clock);
  }
  function install(){
    if(progress.installed||!window.SBB_PLAYBACK_SESSION?.subscribe)return false;
    progress.installed=true;
    progress.off=window.SBB_PLAYBACK_SESSION.subscribe(session=>{
      if(clean(session?.sessionId)&&clean(session.sessionId)!==progress.sessionId)startSelection(session);
      else if(session?.sessionId){progress.slot=clean(session.slot||progress.slot);progress.provider=upper(session.provider||progress.provider);progress.transport=upper(session.transport||progress.transport);}
    });
    progress.timer=setInterval(tick,250);record('installed');return true;
  }
  async function waitForProgress({selectionId=0,mediaKey='',timeoutMs=WAIT_TIMEOUT_MS}={}){
    const started=now(),initial=n(selectionId),wanted=clean(mediaKey);let fallbackHops=0,lastSelection=initial;
    while(now()-started<timeoutMs){
      const session=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{},snap=snapshot();
      if(String(session.invariant||'OK')!=='OK')return {ok:false,reason:`invariant ${session.invariant}`,session,snap,fallbackHops};
      if(snap.confirmed&&snap.selectionId===n(session.selectionId)&&(!wanted||snap.mediaKey===clean(session.mediaKey)))return {ok:true,reason:'clock advancing',session,snap,fallbackHops};
      if(n(session.selectionId)>lastSelection){fallbackHops++;lastSelection=n(session.selectionId);mediaKey=clean(session.mediaKey);}
      if(snap.confirmed&&snap.selectionId===lastSelection)return {ok:true,reason:fallbackHops?'recovered fallback clock advancing':'clock advancing',session,snap,fallbackHops};
      if(clean(session.state)==='failed'&&fallbackHops>1)return {ok:false,reason:clean(session.lastError||'playback failed'),session,snap,fallbackHops};
      await sleep(200);
    }
    const session=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{};return {ok:false,reason:'progress confirmation timeout',session,snap:snapshot(),fallbackHops};
  }

  window.SBB_PLAYBACK_PROGRESS_WATCHDOG=Object.freeze({version:VERSION,install,snapshot,waitForProgress});
  install();
})();

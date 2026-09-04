/* Sports Big Board v5.4.3 — conservative playback progress watchdog.
   This replacement loads before the legacy v4.8.1 watchdog and owns its public
   interface. A video that has demonstrated real clock progress is never failed by
   the startup watchdog later in that selection. Recovery requires positive stall
   evidence from the active transport, preventing false 8–12 second queue skips and
   stale "video unavailable" bumpers while valid audio/video is still playing. */
(() => {
  'use strict';
  if(window.SBB_PLAYBACK_PROGRESS_WATCHDOG)return;

  const VERSION='1.2-v5310';
  const EPS=.18;
  const SOFT_KICK_MS=5200;
  const RECOVERY_MS=11000;
  const WAIT_TIMEOUT_MS=15000;
  const $=id=>document.getElementById(id);
  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const n=v=>Number(v||0)||0;
  const now=()=>performance.now();
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const state={installed:false,selectionId:0,sessionId:'',mediaKey:'',slot:'',provider:'',transport:'',selectedPerf:0,baselineClock:null,lastClock:null,lastMovementAt:0,confirmed:false,firstProgressMs:null,softKicks:0,recoveries:0,timeouts:0,lastReason:'',history:[],timer:null,off:null,recoveryPending:false};

  function record(type,extra={}){state.history.push({at:Date.now(),type,selectionId:state.selectionId,mediaKey:state.mediaKey,...extra});if(state.history.length>80)state.history=state.history.slice(-80);}
  function snapshot(){return {version:VERSION,installed:state.installed,selectionId:state.selectionId,sessionId:state.sessionId,mediaKey:state.mediaKey,slot:state.slot,provider:state.provider,transport:state.transport,firstProgressMs:state.firstProgressMs,confirmed:state.confirmed,softKicks:state.softKicks,recoveries:state.recoveries,timeouts:state.timeouts,lastReason:state.lastReason,history:state.history.slice(-40)};}
  function activeSession(){try{return window.SBB_PLAYBACK_SESSION?.snapshot?.()||{};}catch(_){return {};}}
  function canonicalManualPause(){try{return typeof manualPauseRequested!=='undefined'&&!!manualPauseRequested;}catch(_){return false;}}
  function activeSlotName(session={}){let slot=clean(session?.slot||state.slot);try{if(!slot&&typeof activeSlot!=='undefined')slot=clean(activeSlot);}catch(_){}return slot;}
  function transportSample(session={}){
    const slot=activeSlotName(session),provider=upper(session?.provider||state.provider),transport=upper(session?.transport||state.transport);
    try{
      if(provider.includes('YOUTUBE')||transport.includes('YOUTUBE')){
        const bank=(typeof players!=='undefined')?players:null,p=bank?.[slot];
        if(p){const clock=Number(p.getCurrentTime?.()),ytState=Number(p.getPlayerState?.());return {kind:'YOUTUBE',slot,clock:Number.isFinite(clock)?clock:null,playing:ytState===1,paused:ytState===2,buffering:ytState===3,ended:ytState===0,state:ytState,ready:true};}
      }
    }catch(_){}
    try{
      const v=(typeof nativeEl==='function')?nativeEl(slot):$('native'+slot);
      if(v){const clock=Number(v.currentTime);return {kind:'DIRECT_VIDEO',slot,clock:Number.isFinite(clock)?clock:null,playing:!v.paused&&!v.ended&&v.readyState>=2,paused:!!v.paused,buffering:!v.paused&&v.readyState<3,ended:!!v.ended,state:v.readyState,ready:v.readyState>=1};}
    }catch(_){}
    return {kind:transport||provider||'UNKNOWN',slot,clock:null,playing:false,paused:false,buffering:false,ended:false,state:'unknown',ready:false};
  }
  function startSelection(session){
    state.selectionId=n(session?.selectionId);state.sessionId=clean(session?.sessionId);state.mediaKey=clean(session?.mediaKey);state.slot=clean(session?.slot);state.provider=upper(session?.provider);state.transport=upper(session?.transport);state.selectedPerf=now();state.baselineClock=null;state.lastClock=null;state.lastMovementAt=0;state.confirmed=false;state.firstProgressMs=null;state.lastReason='';state.recoveryPending=false;record('selection',{slot:state.slot,provider:state.provider,transport:state.transport});
  }
  function observeProgress(sample,elapsed){
    if(sample.clock==null)return false;
    if(state.baselineClock==null){state.baselineClock=sample.clock;state.lastClock=sample.clock;state.lastMovementAt=now();record('clock-baseline',{clock:sample.clock});return false;}
    if(state.lastClock==null||sample.clock-state.lastClock>=EPS/2){state.lastMovementAt=now();state.lastClock=sample.clock;}
    if(sample.clock-state.baselineClock>=EPS){
      if(!state.confirmed){state.confirmed=true;state.firstProgressMs=Math.max(0,Math.round(elapsed));state.lastReason='media clock advancing';record('confirmed',{clock:sample.clock,firstProgressMs:state.firstProgressMs});try{window.dispatchEvent(new CustomEvent('sbb:playback-progress-confirmed',{detail:snapshot()}));}catch(_){}}
      return true;
    }
    return false;
  }
  function softKick(sample){
    if(canonicalManualPause()||sample.playing||sample.ended)return false;
    let acted=false;
    try{if(sample.kind==='YOUTUBE'){const bank=(typeof players!=='undefined')?players:null;bank?.[sample.slot]?.playVideo?.();acted=true;}}
    catch(_){}
    try{if(sample.kind==='DIRECT_VIDEO'){const v=(typeof nativeEl==='function')?nativeEl(sample.slot):$('native'+sample.slot);const p=v?.play?.();p?.catch?.(()=>{});acted=!!v;}}
    catch(_){}
    if(acted){state.softKicks++;state.lastReason='bounded startup soft kick';record('soft-kick',{sampleState:sample.state});}
    return acted;
  }
  async function confirmAndRecover(generationSessionId){
    if(state.recoveryPending||state.confirmed||canonicalManualPause())return;
    state.recoveryPending=true;
    try{
      const before=transportSample(activeSession());const beforeClock=before.clock;
      if(before.playing){state.lastReason='provider reports playing; recovery suppressed';record('recovery-suppressed',{reason:'playing'});return;}
      await sleep(450);
      if(state.sessionId!==generationSessionId||state.confirmed||canonicalManualPause())return;
      const session=activeSession(),after=transportSample(session);
      if(after.playing){state.lastReason='provider resumed; recovery suppressed';record('recovery-suppressed',{reason:'playing-after-confirm'});return;}
      if(beforeClock!=null&&after.clock!=null&&after.clock-beforeClock>=EPS/2){observeProgress(after,now()-state.selectedPerf);state.lastReason='late clock movement; recovery suppressed';record('recovery-suppressed',{reason:'clock-moving'});return;}
      // Unknown/unreadable transport state is not proof that the media failed. The
      // canonical player may still be audible inside an embed. Fail only when we can
      // positively observe a paused/buffering/cued active transport that never moved.
      if(!after.ready||(!after.paused&&!after.buffering)){state.lastReason='no positive stall evidence';record('recovery-suppressed',{reason:'unknown-transport'});return;}
      state.recoveries++;state.timeouts++;state.lastReason='positive startup stall';record('recovery',{state:after.state,clock:after.clock});
      const err=new Error('LOCAL_NO_PROGRESS: active transport showed no startup progress after conservative confirmation');
      try{if(typeof handlePlaybackFailure==='function')handlePlaybackFailure(after.slot||state.slot,err,false);else window.SBB_PLAYBACK_SESSION?.fail?.(err,{slot:after.slot||state.slot,provider:state.provider,transport:state.transport});}catch(_){ }
    }finally{state.recoveryPending=false;}
  }
  function tick(){
    if(!state.installed||!state.sessionId)return;
    const session=activeSession();if(clean(session.sessionId)!==state.sessionId||clean(session.mediaKey)!==state.mediaKey)return;
    const stateName=clean(session.state).toLowerCase();if(['ended','failed','idle'].includes(stateName)||canonicalManualPause())return;
    const elapsed=now()-state.selectedPerf,sample=transportSample(session);observeProgress(sample,elapsed);
    // Once actual progress has been seen, this startup watchdog is permanently
    // satisfied for the selection. It cannot later skip the queue because of a
    // transient provider-state hiccup or stale slot metadata.
    if(state.confirmed)return;
    const kicked=state.history.some(x=>x.selectionId===state.selectionId&&x.type==='soft-kick');
    if(elapsed>=SOFT_KICK_MS&&!kicked&&!sample.playing)softKick(sample);
    const recovered=state.history.some(x=>x.selectionId===state.selectionId&&x.type==='recovery');
    if(elapsed>=RECOVERY_MS&&!recovered&&!state.recoveryPending)confirmAndRecover(state.sessionId);
  }
  function install(){
    if(state.installed||!window.SBB_PLAYBACK_SESSION?.subscribe)return false;
    state.installed=true;state.off=window.SBB_PLAYBACK_SESSION.subscribe(session=>{
      if(clean(session?.sessionId)&&clean(session.sessionId)!==state.sessionId)startSelection(session);
      else if(session?.sessionId){state.slot=clean(session.slot||state.slot);state.provider=upper(session.provider||state.provider);state.transport=upper(session.transport||state.transport);}
    });
    state.timer=setInterval(tick,250);record('installed');return true;
  }
  async function waitForProgress({selectionId=0,mediaKey='',timeoutMs=WAIT_TIMEOUT_MS}={}){
    const started=now(),wantedId=n(selectionId),wantedKey=clean(mediaKey);let lastId=wantedId,fallbackHops=0;
    while(now()-started<timeoutMs){const session=activeSession(),snap=snapshot();if(String(session.invariant||'OK')!=='OK')return {ok:false,reason:`invariant ${session.invariant}`,session,snap,fallbackHops};if(snap.confirmed&&snap.selectionId===n(session.selectionId)&&(!wantedKey||snap.mediaKey===clean(session.mediaKey)))return {ok:true,reason:'clock advancing',session,snap,fallbackHops};if(n(session.selectionId)>lastId){fallbackHops++;lastId=n(session.selectionId);}await sleep(200);}
    return {ok:false,reason:'progress confirmation timeout',session:activeSession(),snap:snapshot(),fallbackHops};
  }
  window.SBB_PLAYBACK_PROGRESS_WATCHDOG=Object.freeze({version:VERSION,install,snapshot,waitForProgress});
  install();
})();

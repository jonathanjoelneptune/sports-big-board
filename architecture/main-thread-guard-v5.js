/* Sports Big Board v5.0.1 — Main Thread Responsiveness Guard.
   Observability + cooperative yielding for certification. This service never owns
   playback. It measures event-loop delay so a test can stop adding interactions
   when the UI thread is already saturated, and exposes bounded browser-frame yields. */
(() => {
  'use strict';
  if(window.SBB_MAIN_THREAD_GUARD?.version==='1.0')return;
  const VERSION='1.0';
  const TICK_MS=250;
  const WARN_LAG_MS=350;
  const CRITICAL_LAG_MS=1200;
  let expected=(typeof performance!=='undefined'?performance.now():Date.now())+TICK_MS;
  const state={samples:0,warnings:0,critical:0,maxLagMs:0,lastLagMs:0,lastCriticalAt:0,history:[],startedAt:Date.now()};
  const perfNow=()=>typeof performance!=='undefined'&&performance.now?performance.now():Date.now();
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  function record(lag){
    lag=Math.max(0,Math.round(Number(lag)||0));state.samples++;state.lastLagMs=lag;state.maxLagMs=Math.max(state.maxLagMs,lag);
    if(lag>=WARN_LAG_MS)state.warnings++;
    if(lag>=CRITICAL_LAG_MS){state.critical++;state.lastCriticalAt=Date.now();state.history.push({at:state.lastCriticalAt,lagMs:lag});if(state.history.length>40)state.history=state.history.slice(-40);}
  }
  const timer=setInterval(()=>{const t=perfNow(),lag=t-expected;record(lag);expected=t+TICK_MS;},TICK_MS);
  function snapshot(){return {version:VERSION,tickMs:TICK_MS,warnLagMs:WARN_LAG_MS,criticalLagMs:CRITICAL_LAG_MS,...state,history:[...state.history]};}
  function delta(before={}){const after=snapshot();return {...after,warningDelta:Math.max(0,after.warnings-Number(before.warnings||0)),criticalDelta:Math.max(0,after.critical-Number(before.critical||0)),maxLagDeltaMs:Math.max(0,after.maxLagMs-Number(before.maxLagMs||0))};}
  async function yieldToBrowser(){
    await new Promise(resolve=>{try{requestAnimationFrame(()=>resolve());}catch(_){setTimeout(resolve,0);}});
    await sleep(0);
    return true;
  }
  async function waitForBreathingRoom({timeoutMs=2500,maxFrameMs=220}={}){
    const deadline=Date.now()+Math.max(250,Number(timeoutMs)||2500);
    while(Date.now()<deadline){
      const started=perfNow();await yieldToBrowser();const elapsed=perfNow()-started;
      if(elapsed<=Math.max(50,Number(maxFrameMs)||220))return true;
      await sleep(40);
    }
    return false;
  }
  function resetPeak(){state.maxLagMs=state.lastLagMs;state.history=[];return snapshot();}
  window.SBB_MAIN_THREAD_GUARD=Object.freeze({version:VERSION,snapshot,delta,yieldToBrowser,waitForBreathingRoom,resetPeak,stop:()=>clearInterval(timer)});
})();

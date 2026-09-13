/* Sports Big Board v5.5.0 — splash-screen first-program preloader.

   The splash is a visual/loading cover, not an initialization gate. Live sports
   data already starts on DOMContentLoaded; this layer additionally prepares the
   exact first media item selected by the canonical program while the splash is
   still visible.

   Safety invariants:
   - never calls play()/playVideo()/loadVideoById before the user launch gesture;
   - Hot Standby is launch-gated because its readiness proof intentionally starts media;
   - never monkey-patches the app's playback/standby owners;
   - never chooses a different program or owns playback/failover;
   - YouTube is CUED only, muted, on the already-assigned active slot;
   - native media uses preload=auto only and remains muted/paused;
   - launch remains the sole audible-play gesture and PlaybackController remains
     the sole playback authority.
*/
(() => {
  'use strict';
  if(window.SBB_SPLASH_PRELOAD?.installed)return;

  const VERSION='5.5.0';
  const POLL_MS=120;
  const DEADLINE_MS=30000;
  const startedAt=performance.now();
  let timer=0;
  let lastKey='';
  let lastTransport='';
  let standbyRequestedFor='';
  let cueIssuedFor='';
  let nativeLoadIssuedFor='';
  let readyAt=0;
  let attempts=0;
  let stopped=false;
  let lastMessage='Loading…';
  let progressValue=6;
  let launchCommitted=false;

  const state={
    installed:true,version:VERSION,status:'WAITING_FOR_PROGRAM',transport:'',mediaKey:'',
    startedAt:Date.now(),preparedAt:0,attempts:0,lastMessage,error:'',
    safeMode:'CUE_OR_PRELOAD_ONLY'
  };

  function launchScreen(){return document.getElementById('launchScreen');}
  function launchStatus(){return document.getElementById('launchWarmStatus');}
  function launchProgress(){return document.getElementById('launchWarmProgress');}
  function launchProgressFill(){return document.getElementById('launchWarmProgressFill');}
  function launchProgressPct(){return document.getElementById('launchWarmProgressPct');}
  function launchButton(){return document.getElementById('launchPlayBtn');}
  function experienceStarted(){
    try{return !!window.SBB_START?.started || (typeof sportsBigBoardStarted!=='undefined' && !!sportsBigBoardStarted);}
    catch(_){return !!window.SBB_START?.started;}
  }
  function prelaunchLocked(){
    return !launchCommitted && !experienceStarted() && !!launchScreen();
  }
  const PROGRESS_FLOOR=Object.freeze({
    WAITING_FOR_PROGRAM:10,WAITING_FOR_MEDIA:22,WAITING_FOR_PLAYER:34,
    WAITING_FOR_ASSIGNMENT:44,WARMING:52,CUEING:68,BUFFERING:72,
    READY:100,TIMEOUT:100
  });
  function updateProgress(code){
    let target=Number(PROGRESS_FLOOR[code]??progressValue);
    if(code==='BUFFERING')target=Math.min(96,Math.max(target,72+Math.floor(attempts/5)));
    if(code==='CUEING')target=Math.min(90,Math.max(target,68+Math.floor(attempts/8)));
    if(code==='READY'||code==='TIMEOUT')progressValue=100;
    else progressValue=Math.max(progressValue,Math.min(96,target));
    const bar=launchProgress(),fill=launchProgressFill(),pct=launchProgressPct();
    if(bar){bar.setAttribute('aria-valuenow',String(Math.round(progressValue)));bar.dataset.state=code;}
    if(fill)fill.style.width=`${Math.round(progressValue)}%`;
    if(pct)pct.textContent=`${Math.round(progressValue)}%`;
  }
  function status(message,code='WARMING'){
    lastMessage=String(message||'');state.lastMessage=lastMessage;state.status=code;
    const el=launchStatus();if(el){el.textContent=lastMessage;el.dataset.state=code;}
    updateProgress(code);
    const btn=launchButton();if(btn)btn.classList.toggle('sbb-launch-media-ready',code==='READY');
    document.documentElement.dataset.sbbSplashPreload=code.toLowerCase();
  }
  function stop(reason='stopped'){
    if(stopped)return;stopped=true;if(timer){clearInterval(timer);timer=0;}
    state.status=experienceStarted()||launchCommitted?'LAUNCHED':'STOPPED';state.stopReason=reason;state.stoppedAt=Date.now();
  }
  function currentProgram(){
    let index=0,item=null;
    try{if(typeof currentIndex!=='undefined'&&Number.isInteger(currentIndex))index=currentIndex;}catch(_){}
    try{if(typeof clip==='function')item=clip(index);}catch(_){}
    if(!item){try{item=window.SBB_V5_LEGACY_CLIP?.(index)||null;}catch(_){} }
    return {index,item};
  }
  function mediaKey(item){
    try{if(typeof playbackItemKey==='function')return String(playbackItemKey(item)||'');}catch(_){}
    return String(item?.youtubeId||item?.mediaUrl||item?.id||'');
  }
  function assignedSlot(){
    try{return (typeof activeSlot!=='undefined'&&activeSlot)?String(activeSlot):'A';}catch(_){return 'A';}
  }
  function assignmentMatches(slot,item){
    try{
      if(typeof slotAssignment==='undefined')return true;
      const claim=slotAssignment?.[slot];
      if(!claim?.key)return true;
      const key=mediaKey(item);
      return !key || claim.key===key;
    }catch(_){return true;}
  }
  function youtubeId(item){
    const explicit=String(item?.youtubeId||'').trim();if(explicit)return explicit;
    const id=String(item?.id||'').trim();return (!item?.mediaUrl&&id.length===11)?id:'';
  }
  function playerFor(slot){
    try{return (typeof players!=='undefined'&&players?.[slot])?players[slot]:null;}catch(_){return null;}
  }
  function playerIsReady(slot,p){
    try{if(typeof playerReady!=='undefined'&&playerReady?.[slot])return true;}catch(_){}
    try{return !!p?.getIframe?.();}catch(_){return false;}
  }
  function nativeFor(slot){
    try{if(typeof nativeEl==='function')return nativeEl(slot);}catch(_){}
    return document.getElementById(`native${slot}`);
  }
  function nativeUrl(item){
    try{if(typeof nativePlaybackUrl==='function')return String(nativePlaybackUrl(item)||'');}catch(_){}
    return String(item?.mediaUrl||'');
  }
  function isContext(item){
    try{if(typeof isContextItem==='function')return !!isContextItem(item);}catch(_){}
    return item?.programType==='context';
  }
  function isNative(item){
    try{if(typeof isNativeItem==='function')return !!isNativeItem(item);}catch(_){}
    return !!item?.mediaUrl&&!item?.youtubeId;
  }

  function warmHotStandby(item,index,key){
    // Retain the canonical Hot Standby capability contract for post-launch use,
    // but the splash never invokes it while it owns the launch screen. Hot Standby
    // proves readiness by starting muted media and therefore belongs exclusively to
    // the normal PlaybackController after the user's Start gesture.
    if(prelaunchLocked())return {handled:false,ready:false};
    let usable=true;
    try{if(typeof runtimeMediaUsable==='function')usable=!!runtimeMediaUsable(item);}catch(_){}
    try{if(typeof standbyRejected==='function'&&standbyRejected(item))usable=false;}catch(_){}
    if(!usable)return {handled:false,ready:false};
    let active='A';try{active=(typeof activeSlot!=='undefined'&&activeSlot)?String(activeSlot):'A';}catch(_){}
    const standby=active==='A'?'B':'A';
    let claim=null,ready=false,warmingNow=false;
    try{if(typeof slotAssignment!=='undefined')claim=slotAssignment?.[standby]||null;}catch(_){}
    try{if(typeof videoReady!=='undefined')ready=!!videoReady?.[standby];}catch(_){}
    try{if(typeof warming!=='undefined')warmingNow=!!warming?.[standby];}catch(_){}
    if(claim?.key===key && ready){
      lastTransport='HOT_STANDBY';
      state.hotStandbySlot=standby;
      status('First video buffered • tap to start','READY');
      return {handled:true,ready:true};
    }
    if(claim?.key===key && warmingNow){
      state.hotStandbySlot=standby;
      status('Buffering first video in background…','BUFFERING');
      return {handled:true,ready:false};
    }
    if(standbyRequestedFor!==key){
      try{
        if(typeof prepareStandby==='function'){
          const accepted=prepareStandby(standby,index,{transitionCritical:true});
          if(accepted){
            standbyRequestedFor=key;state.hotStandbyRequestedAt=Date.now();state.hotStandbySlot=standby;
            status('Buffering first video in background…','BUFFERING');
            return {handled:true,ready:false};
          }
        }
      }catch(err){state.hotStandbyError=`${err?.name||'Error'}: ${err?.message||err}`;}
    }
    if(standbyRequestedFor===key)return {handled:true,ready:false};
    return {handled:false,ready:false};
  }

  function warmYouTube(item,slot,key){
    const id=youtubeId(item);if(!id){status('Preparing first video…','WAITING_FOR_MEDIA');return false;}
    const p=playerFor(slot);
    if(!p||!playerIsReady(slot,p)){status('Preparing YouTube player…','WAITING_FOR_PLAYER');return false;}
    if(!assignmentMatches(slot,item)){status('Synchronizing first video…','WAITING_FOR_ASSIGNMENT');return false;}
    try{p.mute?.();}catch(_){}
    let actual='';try{actual=String(p.getVideoData?.()?.video_id||'');}catch(_){}
    if(actual!==id && cueIssuedFor!==key){
      try{
        // cueVideoById initializes the exact video without starting playback. The
        // launch gesture later reuses this same player/video id and begins at 0.
        p.cueVideoById?.({videoId:id,startSeconds:0});
        cueIssuedFor=key;
        state.cueIssuedAt=Date.now();
        status('Cued first video • finishing player setup…','CUEING');
      }catch(err){state.error=`${err?.name||'Error'}: ${err?.message||err}`;status('Preparing first video…','WAITING_FOR_PLAYER');return false;}
      return false;
    }
    try{actual=String(p.getVideoData?.()?.video_id||actual||'');}catch(_){}
    if(actual===id){
      lastTransport='YOUTUBE_CUED';
      status('First video prepared • tap to start','READY');
      return true;
    }
    status('Preparing first video…','CUEING');
    return false;
  }

  function warmNative(item,slot,key){
    const v=nativeFor(slot),url=nativeUrl(item);
    if(!v||!url){status('Preparing first video…','WAITING_FOR_PLAYER');return false;}
    if(!assignmentMatches(slot,item)){status('Synchronizing first video…','WAITING_FOR_ASSIGNMENT');return false;}
    try{
      // Preload is intentionally network/decoder preparation only. Do not change
      // the element volume here: the app's launch gesture owns audible state.
      // Muting alone is sufficient to guarantee silence while the splash is up.
      v.muted=true;
      try{v.pause();}catch(_){}
      v.preload='auto';v.setAttribute('preload','auto');v.playsInline=true;v.setAttribute('playsinline','');
      const attr=String(v.getAttribute('src')||'');
      const current=String(v.currentSrc||'');
      let absolute='';try{absolute=new URL(url,location.href).href;}catch(_){}
      const matches=attr===url||current===url||(absolute&&current===absolute);
      if(!matches){v.setAttribute('src',url);nativeLoadIssuedFor='';}
      if(nativeLoadIssuedFor!==key){
        try{v.load();}catch(_){}
        nativeLoadIssuedFor=key;state.nativeLoadIssuedAt=Date.now();
      }
      if(Number(v.readyState||0)>=3){
        lastTransport='NATIVE_PRELOAD';
        status('First video buffered • tap to start','READY');
        return true;
      }
      status(Number(v.readyState||0)>=1?'Buffering first video…':'Loading first video…','BUFFERING');
      return false;
    }catch(err){state.error=`${err?.name||'Error'}: ${err?.message||err}`;status('Preparing first video…','WAITING_FOR_PLAYER');return false;}
  }

  function tick(){
    if(stopped)return;
    if(experienceStarted()||!launchScreen()){stop('launch-complete');return;}
    attempts++;state.attempts=attempts;
    if(performance.now()-startedAt>DEADLINE_MS){
      if(state.status!=='TIMEOUT')status('Board ready • video will finish loading when started','TIMEOUT');
      return;
    }
    const {index,item}=currentProgram();
    if(!item){status('Loading scores and first video…','WAITING_FOR_PROGRAM');return;}
    const key=mediaKey(item);
    if(!key){status('Building first program…','WAITING_FOR_MEDIA');return;}
    if(key!==lastKey){
      lastKey=key;standbyRequestedFor='';cueIssuedFor='';nativeLoadIssuedFor='';readyAt=0;lastTransport='';
      progressValue=Math.max(18,Math.min(progressValue,56));
      state.mediaKey=key;state.preparedAt=0;state.transport='';state.error='';
      status('Preparing first video…','WARMING');
    }
    const slot=assignedSlot();
    let ready=false;
    if(isContext(item)){
      lastTransport='CONTEXT_READY';status('First program ready • tap to start','READY');ready=true;
    }else{
      // While the splash is visible, warmHotStandby() is intentionally a no-op;
      // only cue/load preparation below is allowed to touch the selected media.
      const hot=warmHotStandby(item,index,key);
      if(hot.handled)ready=hot.ready;
      else if(isNative(item))ready=warmNative(item,slot,key);
      else ready=warmYouTube(item,slot,key);
    }
    if(ready && !readyAt){
      readyAt=Date.now();state.preparedAt=readyAt;state.transport=lastTransport;
      try{window.dispatchEvent(new CustomEvent('sbb:splash-preload-ready',{detail:{version:VERSION,mediaKey:key,transport:lastTransport}}));}catch(_){}
    }
  }

  function restoreLaunchAudioIntent(){
    // pointerdown/keydown on the Start control is the core app's normal audio
    // unlock gesture. Reassert that same intent after the splash's preload mute so
    // the handoff begins in the exact state PlaybackController expects.
    let unlocked=false;
    try{unlocked=(typeof mediaInteractionUnlocked!=='undefined'&&!!mediaInteractionUnlocked);}catch(_){}
    if(!unlocked)return;
    const slot=assignedSlot();
    try{
      if(typeof slotMedia!=='undefined'&&slotMedia?.[slot]==='native'){
        const v=nativeFor(slot);if(v)v.muted=false;
      }else playerFor(slot)?.unMute?.();
    }catch(_){}
    try{if(typeof startupMutedSlots!=='undefined'&&startupMutedSlots)startupMutedSlots[slot]=false;}catch(_){}
    state.audioIntentRestoredAt=Date.now();
  }

  function onLaunchClick(){
    // The click itself is the authorization boundary. From this point forward the
    // splash owns nothing: restore the core app's audio intent and stop polling so
    // normal PlaybackController + Hot Standby behavior is completely untouched.
    launchCommitted=true;
    state.launchCommittedAt=Date.now();
    restoreLaunchAudioIntent();
    stop('launch-click');
  }

  function init(){
    try{if(typeof safeStartLiveData==='function')safeStartLiveData();}catch(_){}
    status('Loading scores and first video…','WAITING_FOR_PROGRAM');
    launchButton()?.addEventListener('click',onLaunchClick,{once:true,capture:true});
    tick();timer=setInterval(tick,POLL_MS);
  }

  window.SBB_SPLASH_PRELOAD=Object.freeze({
    installed:true,version:VERSION,
    snapshot:()=>({...state,status:state.status,lastMessage,mediaKey:lastKey||state.mediaKey,transport:lastTransport||state.transport,preparedAt:readyAt||state.preparedAt,stopped,launchCommitted,prelaunchLocked:prelaunchLocked()}),
    refresh:()=>{if(!stopped)tick();},
    stop:()=>stop('operator')
  });

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
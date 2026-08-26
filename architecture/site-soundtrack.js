/* Sports Big Board v4.2.2 — clip-scoped soundtrack.
   One soundtrack Audio element exists. Every highlight clip gets one soundtrack
   track. Video pause/resume controls that same track; clip changes select a new
   track; long clips advance to another song when the current song ends. */
(() => {
  'use strict';
  const RUNTIME_KEY='__SBB_SOUNDTRACK_SINGLETON__';
  if(window[RUNTIME_KEY]?.api){ window.SBB_SOUNDTRACK=window[RUNTIME_KEY].api; return; }
  if(window[RUNTIME_KEY]?.initializing) return;
  window[RUNTIME_KEY]={initializing:true,api:null};

  const VERSION='1.4';
  const STORAGE_KEY='sbb:soundtrack:v3';
  const LEGACY_KEYS=['sbb:soundtrack:v2','sbb:soundtrack:v1'];
  const OWNER_KEY='sbb:soundtrack:owner:v1';
  const OWNER_LEASE_MS=5000;
  const MANIFEST_URL=new URL('assets/soundtrack/manifest.json',document.baseURI).toString();
  const cfg=window.SBB_CONFIG||{};
  const remoteBase=String(cfg.soundtrackBase||'').trim().replace(/\/+$/,'');
  const ACTIVE_STATES=new Set(['playing','starting','buffering']);
  const $=id=>document.getElementById(id);
  const clamp=(n,min,max)=>Math.max(min,Math.min(max,Number(n)||0));
  const TAB_ID=`tab-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,9)}`;

  let manifest=null;
  let tracks=[];
  let bag=[];
  let playedIds=new Set();
  let currentTrack=null;
  let currentClipKey='';
  let playbackState='idle';
  let experienceStarted=false;
  let enabled=false;
  let searchPaused=false;
  let masterVolume=.16;
  let highlightDuckFactor=.625;
  let saveTimer=0;
  let ownerTimer=0;
  let consecutiveFailures=0;
  let available=true;
  let initialized=false;
  let manifestPromise=null;
  let operationEpoch=0;
  let tabOwnsAudio=false;

  // v4.2.2 invariant: exactly ONE soundtrack media element exists.
  const activeAudio=new Audio();
  activeAudio.preload='auto';
  activeAudio.playsInline=true;
  activeAudio.volume=0;
  activeAudio.__sbbSoundtrack=true;

  let ownerChannel=null;
  try{ if(typeof BroadcastChannel==='function') ownerChannel=new BroadcastChannel('sbb-soundtrack-owner-v1'); }catch(_){ }

  function readJson(key){
    try{return JSON.parse(localStorage.getItem(key)||'null');}catch(_){return null;}
  }
  function readStored(){
    const current=readJson(STORAGE_KEY);
    if(current&&typeof current==='object')return current;
    for(const key of LEGACY_KEYS){
      const legacy=readJson(key);
      if(legacy&&typeof legacy==='object')return legacy;
    }
    return {};
  }
  function saveStored(){
    try{
      localStorage.setItem(STORAGE_KEY,JSON.stringify({
        version:3,
        volume:masterVolume,
        remainingIds:bag.map(x=>x.id),
        playedIds:[...playedIds],
        savedAt:Date.now()
      }));
    }catch(_){ }
  }
  function hydrateStored(){
    const stored=readStored();
    if(Number.isFinite(Number(stored.volume)))masterVolume=clamp(stored.volume,0,.5);
    return stored;
  }

  function trackUrl(track){
    const file=String(track?.file||'').replace(/^\/+/, '');
    if(remoteBase)return `${remoteBase}/${file}`;
    return new URL(`assets/soundtrack/${file}`,document.baseURI).toString();
  }
  function weightedShuffle(items){
    return items.map(track=>({track,key:Math.pow(Math.random(),1/Math.max(1,Number(track.weight||1)))}))
      .sort((a,b)=>b.key-a.key).map(x=>x.track);
  }
  function rebuildCycle(excludeId=''){
    playedIds=new Set(excludeId?[excludeId]:[]);
    bag=weightedShuffle(tracks.filter(t=>t.id!==excludeId));
  }
  function restoreCycle(stored={}){
    const byId=new Map(tracks.map(t=>[t.id,t]));
    const validIds=new Set(byId.keys());
    const remainingSource=Array.isArray(stored.remainingIds)?stored.remainingIds:(Array.isArray(stored.bag)?stored.bag:[]);
    const seenRemaining=new Set();
    bag=[];
    for(const raw of remainingSource){
      const id=String(raw||''),t=byId.get(id);
      if(t&&!seenRemaining.has(id)){seenRemaining.add(id);bag.push(t);}
    }
    if(Array.isArray(stored.playedIds))playedIds=new Set(stored.playedIds.map(String).filter(id=>validIds.has(id)&&!seenRemaining.has(id)));
    else playedIds=new Set(tracks.map(t=>t.id).filter(id=>!seenRemaining.has(id)));
    const accounted=new Set([...seenRemaining,...playedIds]);
    bag.push(...weightedShuffle(tracks.filter(t=>!accounted.has(t.id))));
    if(!bag.length&&tracks.length)rebuildCycle('');
  }
  function drawNextTrack(){
    if(currentTrack?.id)playedIds.add(currentTrack.id);
    if(!bag.length)rebuildCycle(currentTrack?.id||'');
    let next=bag.shift()||null;
    if(!next&&tracks.length===1)next=tracks[0];
    if(next&&currentTrack&&next.id===currentTrack.id&&tracks.length>1){
      bag.push(next);next=bag.shift()||tracks.find(t=>t.id!==currentTrack.id)||next;
    }
    return next;
  }

  function soundtrackShouldRun(){
    return experienceStarted&&enabled&&available&&!searchPaused&&!document.hidden&&ACTIVE_STATES.has(playbackState);
  }
  function baseTargetVolume(){
    if(!soundtrackShouldRun()||!tabOwnsAudio)return 0;
    return playbackState==='playing'?masterVolume*highlightDuckFactor:masterVolume;
  }
  function setActiveVolume(){try{activeAudio.volume=clamp(baseTargetVolume(),0,1);}catch(_){ }}
  function bumpEpoch(){operationEpoch+=1;return operationEpoch;}
  function hardPause({reset=false,bump=true}={}){
    if(bump)bumpEpoch();
    try{activeAudio.pause();activeAudio.volume=0;}catch(_){ }
    try{window.SBB_PLAYBACK_SESSION?.setAudible?.('soundtrack','site',false);}catch(_){ }
    if(reset){try{activeAudio.currentTime=0;}catch(_){ }}
  }
  function unloadActive(){
    hardPause({reset:true,bump:true});
    try{activeAudio.removeAttribute('src');activeAudio.load();}catch(_){ }
    activeAudio.__sbbTrackId='';activeAudio.__sbbFailed=false;
  }
  function loadTrack(track){
    const epoch=bumpEpoch();
    try{activeAudio.pause();activeAudio.volume=0;activeAudio.removeAttribute('src');activeAudio.load();}catch(_){ }
    if(!track)return epoch;
    activeAudio.src=trackUrl(track);
    activeAudio.preload='auto';
    activeAudio.__sbbTrackId=track.id;
    activeAudio.__sbbFailed=false;
    try{activeAudio.load();}catch(_){ }
    return epoch;
  }
  function announceTrack(reason='track-change'){
    if(!currentTrack)return;
    try{console.info('[SBB soundtrack] now playing',{id:currentTrack.id,title:currentTrack.title,tier:currentTrack.tier,clipKey:currentClipKey,reason});}catch(_){ }
  }
  function chooseNewTrack(reason='clip-change'){
    hardPause({reset:true,bump:true});
    const next=drawNextTrack();
    currentTrack=next||null;
    if(currentTrack){playedIds.add(currentTrack.id);announceTrack(reason);loadTrack(currentTrack);}else unloadActive();
    saveStored();renderUi();
    return currentTrack;
  }
  function currentTrackDebugLabel(){
    if(!currentTrack)return '—';
    return `${currentTrack.title||currentTrack.id||'Unknown'} • ${currentTrack.tier||'ROTATION'} • ${currentTrack.id||'—'}`;
  }

  function parseOwner(){
    const row=readJson(OWNER_KEY);
    if(!row||typeof row!=='object')return null;
    return {id:String(row.id||''),ts:Number(row.ts||0)};
  }
  function ownerIsFresh(row){return !!row?.id&&Date.now()-Number(row.ts||0)<OWNER_LEASE_MS;}
  function writeOwner(){
    const row={id:TAB_ID,ts:Date.now()};
    try{localStorage.setItem(OWNER_KEY,JSON.stringify(row));}catch(_){ }
    try{ownerChannel?.postMessage({type:'claim',...row});}catch(_){ }
    tabOwnsAudio=true;
  }
  function claimOwnership({force=false}={}){
    const current=parseOwner();
    if(!force&&ownerIsFresh(current)&&current.id!==TAB_ID){tabOwnsAudio=false;return false;}
    writeOwner();return true;
  }
  function releaseOwnership(){
    const current=parseOwner();
    if(current?.id===TAB_ID){try{localStorage.removeItem(OWNER_KEY);}catch(_){ }}
    try{ownerChannel?.postMessage({type:'release',id:TAB_ID,ts:Date.now()});}catch(_){ }
    tabOwnsAudio=false;
  }
  function pauseForOtherTab(){tabOwnsAudio=false;hardPause({reset:false,bump:true});renderUi();}
  function ownerHeartbeat(){if(tabOwnsAudio&&soundtrackShouldRun()&&!activeAudio.paused)writeOwner();}
  function onOwnerMessage(msg){
    const row=msg?.data||msg;
    if(!row||row.id===TAB_ID)return;
    if(row.type==='claim')pauseForOtherTab();
    if(row.type==='release'&&soundtrackShouldRun()&&!document.hidden)setTimeout(()=>ensurePlaying({claim:false}),120);
  }

  async function ensurePlaying({claim=false}={}){
    if(!initialized)await init();
    if(!soundtrackShouldRun()||!currentTrack)return false;
    if(!claimOwnership({force:claim}))return false;
    if(!activeAudio.src)loadTrack(currentTrack);
    const epoch=operationEpoch,expectedTrackId=currentTrack.id;
    try{
      if(activeAudio.paused)await activeAudio.play();
      if(epoch!==operationEpoch||currentTrack?.id!==expectedTrackId||activeAudio.__sbbTrackId!==expectedTrackId||!soundtrackShouldRun()||!tabOwnsAudio){
        if(activeAudio.__sbbTrackId===expectedTrackId&&(!soundtrackShouldRun()||!tabOwnsAudio))hardPause({reset:false,bump:false});
        return false;
      }
      setActiveVolume();consecutiveFailures=0;ownerHeartbeat();
      try{window.SBB_PLAYBACK_SESSION?.setAudible?.('soundtrack','site',!activeAudio.paused&&activeAudio.volume>0);}catch(_){ }
      renderUi();return true;
    }catch(err){
      if(epoch!==operationEpoch||activeAudio.__sbbTrackId!==expectedTrackId)return false;
      if(err?.name!=='NotAllowedError'&&err?.name!=='AbortError')handleAudioFailure(err);
      renderUi();return false;
    }
  }
  function pauseNow(){hardPause({reset:false,bump:true});renderUi();}

  function syncClip(rawKey,{reason='clip-change'}={}){
    const key=String(rawKey||'').trim();
    if(!key||key===currentClipKey)return false;
    currentClipKey=key;
    chooseNewTrack(reason);
    return true;
  }
  function startExperience(rawClipKey=''){
    experienceStarted=true;
    enabled=true; // Every fresh board launch starts with soundtrack ON, matching the UI.
    syncClip(rawClipKey,{reason:'experience-start'});
    renderUi();
    if(soundtrackShouldRun())ensurePlaying({claim:true});
  }
  function setPlaybackState(mode,rawClipKey=''){
    const next=String(mode||'idle').toLowerCase();
    playbackState=next;
    const changedClip=syncClip(rawClipKey,{reason:'video-change'});
    if(ACTIVE_STATES.has(next)){
      if(experienceStarted&&enabled&&!searchPaused){ensurePlaying({claim:changedClip});setActiveVolume();}
    }else if(next==='paused'||next==='ended'||next==='ready'||next==='idle'){
      pauseNow();
    }
    renderUi();
  }
  function advanceTrack(reason='next'){
    const shouldResume=soundtrackShouldRun();
    chooseNewTrack(reason);
    if(shouldResume)ensurePlaying({claim:true});
  }
  function handleAudioFailure(err){
    if(activeAudio.__sbbTrackId!==currentTrack?.id||activeAudio.__sbbFailed)return;
    activeAudio.__sbbFailed=true;consecutiveFailures++;
    console.warn('[SBB soundtrack] track unavailable',{track:activeAudio.__sbbTrackId,error:err?.message||String(err||'audio error'),base:remoteBase||'local'});
    if(consecutiveFailures>=Math.min(8,Math.max(1,tracks.length))){available=false;pauseNow();renderUi();return;}
    advanceTrack('error-skip');
  }
  function pauseForSearch(){searchPaused=true;pauseNow();renderUi();}
  function resumeFromSearch(){searchPaused=false;if(soundtrackShouldRun())ensurePlaying({claim:false});renderUi();}

  function toggleEnabled(){
    if(!experienceStarted)return;
    enabled=!enabled;available=true;consecutiveFailures=0;renderUi();
    if(enabled&&ACTIVE_STATES.has(playbackState)&&!searchPaused)ensurePlaying({claim:true});
    else if(!enabled){pauseNow();releaseOwnership();}
  }
  function setVolume(value){masterVolume=clamp(value,0,.5);saveStored();setActiveVolume();renderUi();}
  function toggleVolumePopover(force){
    const pop=$('soundtrackVolumePopover');if(!pop)return;
    const show=typeof force==='boolean'?force:pop.classList.contains('hidden');
    pop.classList.toggle('hidden',!show);
    $('soundtrackVolumeBtn')?.setAttribute('aria-expanded',show?'true':'false');
  }
  function renderUi(){
    const toggle=$('soundtrackToggle'),volBtn=$('soundtrackVolumeBtn'),slider=$('soundtrackVolume');
    if(toggle){
      const sounding=soundtrackShouldRun()&&tabOwnsAudio&&!activeAudio.paused;
      toggle.textContent=enabled?'♫ Ⅱ':'♫ ▶';
      toggle.setAttribute('aria-pressed',enabled?'true':'false');
      toggle.classList.toggle('is-enabled',enabled);
      toggle.classList.toggle('is-playing',sounding);
      toggle.classList.toggle('is-unavailable',!available);
      toggle.title=!experienceStarted?'Soundtrack starts with Sports Big Board':(!available?'Soundtrack files unavailable':(enabled?`Soundtrack on${currentTrack?.title?` • ${currentTrack.title}`:''}`:'Turn soundtrack on'));
      toggle.setAttribute('aria-label',enabled?'Pause Sports Big Board soundtrack':'Enable Sports Big Board soundtrack');
    }
    if(volBtn){
      volBtn.textContent=masterVolume<=.005?'🔇':masterVolume<.12?'🔈':masterVolume<.28?'🔉':'🔊';
      volBtn.title=`Soundtrack volume ${Math.round(masterVolume*100)}%`;
    }
    if(slider&&Math.abs(Number(slider.value)-masterVolume)>.001)slider.value=String(masterVolume);
    const debug=$('diagSoundtrack');
    if(debug){debug.textContent=currentTrackDebugLabel();debug.title=`${currentTrack?.sourceFilename||currentTrack?.file||''}${currentClipKey?` • clip ${currentClipKey}`:''}`;}
    document.body?.classList.toggle('sbb-soundtrack-enabled',enabled);
  }

  async function loadManifest(){
    if(manifestPromise)return manifestPromise;
    manifestPromise=fetch(MANIFEST_URL,{cache:'force-cache'}).then(async r=>{
      if(!r.ok)throw new Error(`Soundtrack manifest HTTP ${r.status}`);
      manifest=await r.json();
      tracks=(Array.isArray(manifest?.tracks)?manifest.tracks:[]).filter(t=>t?.id&&t?.file&&t?.disabled!==true);
      const defs=manifest?.playbackDefaults||{};
      if(Number.isFinite(Number(defs.defaultMusicVolume))&&!localStorage.getItem(STORAGE_KEY)&&!LEGACY_KEYS.some(k=>localStorage.getItem(k)))masterVolume=clamp(defs.defaultMusicVolume,0,.5);
      const normal=Math.max(.001,Number(defs.defaultMusicVolume||.16)),duck=Math.max(0,Number(defs.highlightPlayingVolume||.10));
      highlightDuckFactor=clamp(duck/normal,0,1);
      restoreCycle(readStored());
      available=tracks.length>0;renderUi();return manifest;
    }).catch(err=>{available=false;console.warn('[SBB soundtrack] manifest unavailable',err);renderUi();return null;});
    return manifestPromise;
  }
  function bindUi(){
    $('soundtrackToggle')?.addEventListener('click',toggleEnabled);
    $('soundtrackNextBtn')?.addEventListener('click',ev=>{ev.stopPropagation();advanceTrack('next');});
    $('soundtrackVolumeBtn')?.addEventListener('click',ev=>{ev.stopPropagation();toggleVolumePopover();});
    $('soundtrackVolume')?.addEventListener('input',ev=>setVolume(ev.target.value));
    document.addEventListener('click',ev=>{if(!ev.target.closest?.('#soundtrackControls'))toggleVolumePopover(false);});
    document.addEventListener('pointerdown',ev=>{if(ev.target.closest?.('#soundtrackControls'))return;if(soundtrackShouldRun())ensurePlaying({claim:true});},{capture:true,passive:true});
    document.addEventListener('keydown',ev=>{if(ev.target.closest?.('#soundtrackControls'))return;if(soundtrackShouldRun())ensurePlaying({claim:true});},{capture:true,passive:true});
    document.addEventListener('visibilitychange',()=>{
      if(document.hidden){pauseNow();releaseOwnership();}
      else if(soundtrackShouldRun())ensurePlaying({claim:false});
    });
    window.addEventListener('beforeunload',()=>{saveStored();releaseOwnership();});
    window.addEventListener('pagehide',releaseOwnership);
    window.addEventListener('storage',ev=>{if(ev.key===OWNER_KEY){const row=parseOwner();if(ownerIsFresh(row)&&row.id!==TAB_ID)pauseForOtherTab();}});
    try{ownerChannel?.addEventListener('message',onOwnerMessage);}catch(_){ }
  }
  function bindAudio(){
    activeAudio.addEventListener('error',()=>handleAudioFailure(new Error('audio element error')));
    // If the highlight is still running when a song ends, immediately continue with
    // another soundtrack song for that SAME clip.
    activeAudio.addEventListener('ended',()=>{if(activeAudio.__sbbTrackId===currentTrack?.id&&soundtrackShouldRun())advanceTrack('song-ended');});
    activeAudio.addEventListener('playing',()=>{try{window.SBB_PLAYBACK_SESSION?.setAudible?.('soundtrack','site',activeAudio.volume>0);}catch(_){ }renderUi();});
    activeAudio.addEventListener('pause',()=>{try{window.SBB_PLAYBACK_SESSION?.setAudible?.('soundtrack','site',false);}catch(_){ }renderUi();});
  }
  async function init(){
    if(initialized)return manifestPromise;
    initialized=true;hydrateStored();bindAudio();bindUi();renderUi();
    saveTimer=setInterval(saveStored,5000);ownerTimer=setInterval(ownerHeartbeat,2000);
    manifestPromise=loadManifest();return manifestPromise;
  }


  function devSnapshot(){
    return {
      enabled,available,experienceStarted,currentClipKey,volume:masterVolume,
      currentTrackId:currentTrack?.id||'',currentTime:Number.isFinite(activeAudio.currentTime)?Math.max(0,activeAudio.currentTime):0,
      remainingIds:bag.map(x=>x.id),playedIds:[...playedIds]
    };
  }
  function devRestore(saved={}){
    if(!saved||typeof saved!=='object')return false;
    hardPause({reset:true,bump:true});
    const byId=new Map(tracks.map(t=>[t.id,t]));
    const target=byId.get(String(saved.currentTrackId||''))||null;
    if(Number.isFinite(Number(saved.volume)))masterVolume=clamp(saved.volume,0,.5);
    if(typeof saved.enabled==='boolean')enabled=saved.enabled;
    if(typeof saved.experienceStarted==='boolean')experienceStarted=saved.experienceStarted;
    if(saved.currentClipKey!=null)currentClipKey=String(saved.currentClipKey||'');
    const remaining=[];const seen=new Set();
    for(const id of Array.isArray(saved.remainingIds)?saved.remainingIds:[]){const t=byId.get(String(id));if(t&&!seen.has(t.id)&&t.id!==target?.id){seen.add(t.id);remaining.push(t);}}
    bag=remaining;
    playedIds=new Set((Array.isArray(saved.playedIds)?saved.playedIds:[]).map(String).filter(id=>byId.has(id)&&!seen.has(id)));
    currentTrack=target;
    if(currentTrack){
      loadTrack(currentTrack);
      const wanted=Math.max(0,Number(saved.currentTime||0));
      if(wanted>0){
        const seek=()=>{try{if(Number.isFinite(activeAudio.duration)&&activeAudio.duration>1)activeAudio.currentTime=Math.min(wanted,Math.max(0,activeAudio.duration-.5));}catch(_){ }activeAudio.removeEventListener('loadedmetadata',seek);};
        if(activeAudio.readyState>=1)seek();else activeAudio.addEventListener('loadedmetadata',seek);
      }
    }else unloadActive();
    saveStored();renderUi();
    if(enabled&&soundtrackShouldRun())ensurePlaying({claim:true});
    return true;
  }

  const api=Object.freeze({
    __singleton:true,version:VERSION,init,startExperience,setPlaybackState,pauseForSearch,resumeFromSearch,setVolume,
    toggle:toggleEnabled,skip:()=>advanceTrack('next'),__devSnapshot:devSnapshot,__devRestore:devRestore,
    snapshot:()=>({
      enabled,available,experienceStarted,playbackState,currentClipKey,searchPaused,volume:masterVolume,
      currentTrack:currentTrack?{id:currentTrack.id,title:currentTrack.title,tier:currentTrack.tier,file:currentTrack.file,sourceFilename:currentTrack.sourceFilename}:null,
      remainingInBag:bag.length,playedInCycle:playedIds.size,trackCount:tracks.length,remoteBase,tabOwnsAudio,operationEpoch,audioElementCount:1
    })
  });
  window.SBB_SOUNDTRACK=api;
  window[RUNTIME_KEY]={initializing:false,api,audio:activeAudio};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>init(),{once:true});else init();
})();

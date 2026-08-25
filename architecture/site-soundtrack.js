/* Sports Big Board v4.1.30 — single-stream persistent site soundtrack.
   Exactly one soundtrack Audio element may ever play. A second Audio element may
   preload the next file, but it is permanently muted and is never played. */
(() => {
  'use strict';
  const VERSION='1.2';
  const STORAGE_KEY='sbb:soundtrack:v2';
  const LEGACY_STORAGE_KEY='sbb:soundtrack:v1';
  const OWNER_KEY='sbb:soundtrack:owner:v1';
  const OWNER_LEASE_MS=5000;
  const MANIFEST_URL=new URL('assets/soundtrack/manifest.json',document.baseURI).toString();
  const cfg=window.SBB_CONFIG||{};
  const remoteBase=String(cfg.soundtrackBase||'').trim().replace(/\/+$/,'');
  const ACTIVE_STATES=new Set(['playing','starting','buffering']);
  const HARD_PAUSE_STATES=new Set(['paused','ready']);
  const $=id=>document.getElementById(id);
  const clamp=(n,min,max)=>Math.max(min,Math.min(max,Number(n)||0));
  const TAB_ID=`tab-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,9)}`;

  let manifest=null;
  let tracks=[];
  let bag=[];
  let playedIds=new Set();
  let currentTrack=null;
  let playbackState='idle';
  let enabled=true;
  let masterVolume=.16;
  let highlightDuckFactor=.625;
  let resumeTrackId='';
  let resumePosition=0;
  let pauseTimer=0;
  let saveTimer=0;
  let ownerTimer=0;
  let consecutiveFailures=0;
  let available=true;
  let initialized=false;
  let manifestPromise=null;
  let operationEpoch=0;
  let tabOwnsAudio=false;
  let preloadedTrackId='';

  const activeAudio=new Audio();
  activeAudio.preload='auto';
  activeAudio.playsInline=true;
  activeAudio.volume=0;

  // This element is only a network/cache warmer. It must never become audible.
  const preloadAudio=new Audio();
  preloadAudio.preload='auto';
  preloadAudio.playsInline=true;
  preloadAudio.muted=true;
  preloadAudio.volume=0;
  preloadAudio.addEventListener?.('play',()=>{ try{preloadAudio.pause();}catch(_){ } });

  let ownerChannel=null;
  try{ if(typeof BroadcastChannel==='function') ownerChannel=new BroadcastChannel('sbb-soundtrack-owner-v1'); }catch(_){ }

  function readJson(key){
    try{return JSON.parse(localStorage.getItem(key)||'null');}catch(_){return null;}
  }
  function readStored(){
    const current=readJson(STORAGE_KEY);
    if(current && typeof current==='object') return {...current,__legacy:false};
    const legacy=readJson(LEGACY_STORAGE_KEY);
    if(legacy && typeof legacy==='object') return {...legacy,__legacy:true};
    return {__legacy:false};
  }
  function saveStored(){
    try{
      localStorage.setItem(STORAGE_KEY,JSON.stringify({
        version:2,
        enabled,
        volume:masterVolume,
        currentTrackId:currentTrack?.id||'',
        currentTime:Number.isFinite(activeAudio.currentTime)?Math.max(0,activeAudio.currentTime):0,
        remainingIds:bag.map(x=>x.id),
        playedIds:[...playedIds],
        savedAt:Date.now()
      }));
    }catch(_){ }
  }
  function hydrateStored(){
    const stored=readStored();
    if(typeof stored.enabled==='boolean') enabled=stored.enabled;
    if(Number.isFinite(Number(stored.volume))) masterVolume=clamp(stored.volume,0,.5);
    resumeTrackId=String(stored.currentTrackId||'');
    resumePosition=Math.max(0,Number(stored.currentTime||0));
    return stored;
  }

  function trackUrl(track){
    const file=String(track?.file||'').replace(/^\/+/, '');
    if(remoteBase) return `${remoteBase}/${file}`;
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
      const id=String(raw||'');
      const t=byId.get(id);
      if(t && id!==currentTrack?.id && !seenRemaining.has(id)){
        seenRemaining.add(id);bag.push(t);
      }
    }
    if(Array.isArray(stored.playedIds)){
      playedIds=new Set(stored.playedIds.map(String).filter(id=>validIds.has(id)&&!seenRemaining.has(id)));
    }else{
      // v1 migration: anything not in the persisted remaining bag has already
      // been heard in the current cycle. This preserves the no-repeat intent.
      playedIds=new Set(tracks.map(t=>t.id).filter(id=>id!==currentTrack?.id&&!seenRemaining.has(id)));
    }
    if(currentTrack?.id) playedIds.add(currentTrack.id);
    const accounted=new Set([...seenRemaining,...playedIds]);
    if(currentTrack?.id) accounted.add(currentTrack.id);
    const newTracks=weightedShuffle(tracks.filter(t=>!accounted.has(t.id)));
    bag.push(...newTracks);
    if(!bag.length && tracks.length>1) rebuildCycle(currentTrack?.id||'');
  }
  function markCurrentHeard(){ if(currentTrack?.id) playedIds.add(currentTrack.id); }
  function drawNextTrack(){
    markCurrentHeard();
    if(!bag.length) rebuildCycle(currentTrack?.id||'');
    let next=bag.shift()||null;
    if(!next && tracks.length===1) next=tracks[0];
    if(next && currentTrack && next.id===currentTrack.id && tracks.length>1){
      bag.push(next);next=bag.shift()||tracks.find(t=>t.id!==currentTrack.id)||next;
    }
    return next;
  }
  function peekNextTrack(){
    if(bag.length) return bag[0];
    if(tracks.length<=1) return tracks[0]||null;
    return weightedShuffle(tracks.filter(t=>t.id!==currentTrack?.id))[0]||null;
  }

  function baseTargetVolume(){
    if(!enabled || !available || document.hidden || !tabOwnsAudio) return 0;
    if(playbackState==='playing') return masterVolume*highlightDuckFactor;
    if(playbackState==='starting' || playbackState==='buffering') return masterVolume;
    return 0;
  }
  function setActiveVolume(){ try{activeAudio.volume=clamp(baseTargetVolume(),0,1);}catch(_){ } }
  function shouldSound(){ return enabled && available && !document.hidden && ACTIVE_STATES.has(playbackState); }

  function bumpEpoch(){ operationEpoch+=1; return operationEpoch; }
  function hardStopActive({reset=false,bump=true}={}){
    if(bump) bumpEpoch();
    clearTimeout(pauseTimer);pauseTimer=0;
    try{activeAudio.pause();}catch(_){ }
    try{activeAudio.volume=0;}catch(_){ }
    if(reset){ try{activeAudio.currentTime=0;}catch(_){ } }
  }
  function unloadActive(){
    hardStopActive({reset:false,bump:true});
    try{activeAudio.removeAttribute('src');activeAudio.load();}catch(_){ }
    activeAudio.__sbbTrackId='';
    activeAudio.__sbbFailed=false;
  }
  function loadCurrentTrack(track,{position=0}={}){
    const epoch=bumpEpoch();
    try{activeAudio.pause();activeAudio.volume=0;activeAudio.removeAttribute('src');activeAudio.load();}catch(_){ }
    if(!track) return epoch;
    activeAudio.src=trackUrl(track);
    activeAudio.preload='auto';
    activeAudio.__sbbTrackId=track.id;
    activeAudio.__sbbFailed=false;
    if(position>0){
      const seek=()=>{
        if(epoch!==operationEpoch || activeAudio.__sbbTrackId!==track.id){activeAudio.removeEventListener('loadedmetadata',seek);return;}
        try{if(Number.isFinite(activeAudio.duration)&&activeAudio.duration>5)activeAudio.currentTime=Math.min(position,Math.max(0,activeAudio.duration-3));}catch(_){ }
        activeAudio.removeEventListener('loadedmetadata',seek);
      };
      activeAudio.addEventListener('loadedmetadata',seek);
    }
    try{activeAudio.load();}catch(_){ }
    return epoch;
  }
  function primeNextTrack(){
    const next=peekNextTrack();
    preloadedTrackId=next?.id||'';
    try{
      preloadAudio.pause();preloadAudio.muted=true;preloadAudio.volume=0;
      preloadAudio.removeAttribute('src');preloadAudio.load();
      if(next){preloadAudio.src=trackUrl(next);preloadAudio.__sbbTrackId=next.id;preloadAudio.load();}
    }catch(_){ }
  }

  function currentTrackDebugLabel(){
    if(!currentTrack) return '—';
    return `${currentTrack.title||currentTrack.id||'Unknown'} • ${currentTrack.tier||'ROTATION'} • ${currentTrack.id||'—'}`;
  }
  function announceTrack(reason='track-change'){
    if(!currentTrack)return;
    try{console.info('[SBB soundtrack] now playing',{id:currentTrack.id,title:currentTrack.title,tier:currentTrack.tier,reason});}catch(_){ }
  }
  function setCurrentTrack(track,{position=0,reason='select'}={}){
    currentTrack=track;
    if(currentTrack?.id) playedIds.add(currentTrack.id);
    announceTrack(reason);
    loadCurrentTrack(currentTrack,{position});
    primeNextTrack();
    saveStored();renderUi();
  }

  function parseOwner(){
    const row=readJson(OWNER_KEY);
    if(!row || typeof row!=='object')return null;
    return {id:String(row.id||''),ts:Number(row.ts||0)};
  }
  function ownerIsFresh(row){return !!row?.id && Date.now()-Number(row.ts||0)<OWNER_LEASE_MS;}
  function writeOwner(){
    const row={id:TAB_ID,ts:Date.now()};
    try{localStorage.setItem(OWNER_KEY,JSON.stringify(row));}catch(_){ }
    try{ownerChannel?.postMessage({type:'claim',...row});}catch(_){ }
    tabOwnsAudio=true;
  }
  function claimOwnership({force=false}={}){
    const current=parseOwner();
    if(!force && ownerIsFresh(current) && current.id!==TAB_ID){tabOwnsAudio=false;return false;}
    writeOwner();return true;
  }
  function releaseOwnership(){
    const current=parseOwner();
    if(current?.id===TAB_ID){try{localStorage.removeItem(OWNER_KEY);}catch(_){ }}
    try{ownerChannel?.postMessage({type:'release',id:TAB_ID,ts:Date.now()});}catch(_){ }
    tabOwnsAudio=false;
  }
  function pauseForOtherTab(){
    tabOwnsAudio=false;
    hardStopActive({reset:false,bump:true});
    renderUi();
  }
  function ownerHeartbeat(){
    if(tabOwnsAudio && shouldSound() && !activeAudio.paused)writeOwner();
  }
  function onOwnerMessage(msg){
    const row=msg?.data||msg;
    if(!row || row.id===TAB_ID)return;
    if(row.type==='claim')pauseForOtherTab();
    if(row.type==='release' && shouldSound() && !document.hidden)setTimeout(()=>ensurePlaying({claim:false}),120);
  }

  async function ensurePlaying({claim=false}={}){
    if(!initialized)await init();
    if(!shouldSound() || !currentTrack)return false;
    clearTimeout(pauseTimer);pauseTimer=0;
    if(!claimOwnership({force:claim}))return false;
    if(!activeAudio.src)loadCurrentTrack(currentTrack,{position:resumePosition});
    const epoch=operationEpoch;
    const expectedTrackId=currentTrack.id;
    try{
      if(activeAudio.paused)await activeAudio.play();
      if(epoch!==operationEpoch || currentTrack?.id!==expectedTrackId || activeAudio.__sbbTrackId!==expectedTrackId || !shouldSound() || !tabOwnsAudio){
        // Only stop the element if it still belongs to this stale request. If a
        // newer Next already repurposed it, that newer request owns the player.
        if(activeAudio.__sbbTrackId===expectedTrackId && (!shouldSound()||!tabOwnsAudio))hardStopActive({reset:false,bump:false});
        return false;
      }
      setActiveVolume();
      consecutiveFailures=0;
      ownerHeartbeat();
      renderUi();
      return true;
    }catch(err){
      if(epoch!==operationEpoch || activeAudio.__sbbTrackId!==expectedTrackId)return false;
      if(err?.name!=='NotAllowedError' && err?.name!=='AbortError')handleAudioFailure(err);
      renderUi();return false;
    }
  }
  function pauseNow(){
    hardStopActive({reset:false,bump:true});
    saveStored();renderUi();
  }
  function scheduleEndedPause(){
    clearTimeout(pauseTimer);
    pauseTimer=setTimeout(()=>{if(playbackState==='ended')pauseNow();},2800);
  }
  function advanceTrack(reason='next'){
    const resume=shouldSound();
    hardStopActive({reset:true,bump:true});
    const next=drawNextTrack();
    if(!next){renderUi();return;}
    currentTrack=next;
    playedIds.add(next.id);
    announceTrack(reason);
    loadCurrentTrack(currentTrack);
    primeNextTrack();
    saveStored();renderUi();
    if(resume)ensurePlaying({claim:true});
  }
  function handleAudioFailure(err){
    if(activeAudio.__sbbTrackId!==currentTrack?.id)return;
    if(activeAudio.__sbbFailed)return;
    activeAudio.__sbbFailed=true;
    consecutiveFailures++;
    console.warn('[SBB soundtrack] track unavailable',{track:activeAudio.__sbbTrackId,error:err?.message||String(err||'audio error'),base:remoteBase||'local'});
    if(consecutiveFailures>=Math.min(8,Math.max(1,tracks.length))){
      available=false;pauseNow();renderUi();return;
    }
    advanceTrack('error-skip');
  }

  function setPlaybackState(mode){
    const next=String(mode||'idle').toLowerCase();
    const changed=next!==playbackState;
    playbackState=next;
    // Playback truth is authoritative, even when the same PAUSED/READY state is
    // reported repeatedly by native controls or a YouTube iframe callback.
    if(ACTIVE_STATES.has(playbackState)){
      clearTimeout(pauseTimer);pauseTimer=0;
      ensurePlaying({claim:false});
      setActiveVolume();
    }else if(HARD_PAUSE_STATES.has(playbackState)){
      pauseNow();
    }else if(playbackState==='ended' && changed){
      scheduleEndedPause();
    }
    renderUi();
  }
  function pauseForSearch(){playbackState='paused';pauseNow();renderUi();}

  function toggleEnabled(){
    enabled=!enabled;available=true;consecutiveFailures=0;saveStored();renderUi();
    if(enabled && ACTIVE_STATES.has(playbackState))ensurePlaying({claim:true});
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
      const sounding=shouldSound()&&tabOwnsAudio&&!activeAudio.paused;
      toggle.textContent=enabled?'♫ Ⅱ':'♫ ▶';
      toggle.setAttribute('aria-pressed',enabled?'true':'false');
      toggle.classList.toggle('is-enabled',enabled);toggle.classList.toggle('is-playing',sounding);toggle.classList.toggle('is-unavailable',!available);
      toggle.title=!available?'Soundtrack files unavailable':(enabled?`Soundtrack on${currentTrack?.title?` • ${currentTrack.title}`:''}`:'Turn Sports Big Board soundtrack on');
      toggle.setAttribute('aria-label',enabled?'Pause Sports Big Board soundtrack':'Enable Sports Big Board soundtrack');
    }
    if(volBtn){
      volBtn.textContent=masterVolume<=.005?'🔇':masterVolume<.12?'🔈':masterVolume<.28?'🔉':'🔊';
      volBtn.title=`Soundtrack volume ${Math.round(masterVolume*100)}%`;
    }
    if(slider&&Math.abs(Number(slider.value)-masterVolume)>.001)slider.value=String(masterVolume);
    const debug=$('diagSoundtrack');
    if(debug){debug.textContent=currentTrackDebugLabel();debug.title=currentTrack?.sourceFilename||currentTrack?.file||'';}
    document.body?.classList.toggle('sbb-soundtrack-enabled',enabled);
  }

  async function loadManifest(){
    if(manifestPromise)return manifestPromise;
    manifestPromise=fetch(MANIFEST_URL,{cache:'force-cache'}).then(async r=>{
      if(!r.ok)throw new Error(`Soundtrack manifest HTTP ${r.status}`);
      manifest=await r.json();
      tracks=(Array.isArray(manifest?.tracks)?manifest.tracks:[]).filter(t=>t?.id&&t?.file&&t?.disabled!==true);
      const defs=manifest?.playbackDefaults||{};
      if(Number.isFinite(Number(defs.defaultMusicVolume))&&!localStorage.getItem(STORAGE_KEY)&&!localStorage.getItem(LEGACY_STORAGE_KEY))masterVolume=clamp(defs.defaultMusicVolume,0,.5);
      const normal=Math.max(.001,Number(defs.defaultMusicVolume||.16)),duck=Math.max(0,Number(defs.highlightPlayingVolume||.10));
      highlightDuckFactor=clamp(duck/normal,0,1);
      const stored=readStored();
      currentTrack=tracks.find(t=>t.id===resumeTrackId)||null;
      if(!currentTrack)currentTrack=weightedShuffle(tracks)[0]||null;
      restoreCycle(stored);
      if(currentTrack)loadCurrentTrack(currentTrack,{position:resumePosition});
      primeNextTrack();
      available=tracks.length>0;
      renderUi();return manifest;
    }).catch(err=>{available=false;console.warn('[SBB soundtrack] manifest unavailable',err);renderUi();return null;});
    return manifestPromise;
  }
  function bindUi(){
    $('soundtrackToggle')?.addEventListener('click',toggleEnabled);
    $('soundtrackNextBtn')?.addEventListener('click',ev=>{ev.stopPropagation();advanceTrack('next');});
    $('soundtrackVolumeBtn')?.addEventListener('click',ev=>{ev.stopPropagation();toggleVolumePopover();});
    $('soundtrackVolume')?.addEventListener('input',ev=>setVolume(ev.target.value));
    document.addEventListener('click',ev=>{if(!ev.target.closest?.('#soundtrackControls'))toggleVolumePopover(false);});
    // Soundtrack controls must not invoke the generic autoplay-unlock path before
    // their own click handler. That old ordering could restart the outgoing song.
    document.addEventListener('pointerdown',ev=>{if(ev.target.closest?.('#soundtrackControls'))return;if(enabled&&ACTIVE_STATES.has(playbackState))ensurePlaying({claim:true});},{capture:true,passive:true});
    document.addEventListener('keydown',ev=>{if(ev.target.closest?.('#soundtrackControls'))return;if(enabled&&ACTIVE_STATES.has(playbackState))ensurePlaying({claim:true});},{capture:true,passive:true});
    document.addEventListener('visibilitychange',()=>{
      if(document.hidden){pauseNow();releaseOwnership();}
      else if(ACTIVE_STATES.has(playbackState))ensurePlaying({claim:false});
    });
    window.addEventListener('beforeunload',()=>{saveStored();releaseOwnership();});
    window.addEventListener('pagehide',releaseOwnership);
    window.addEventListener('storage',ev=>{if(ev.key===OWNER_KEY){const row=parseOwner();if(ownerIsFresh(row)&&row.id!==TAB_ID)pauseForOtherTab();}});
    try{ownerChannel?.addEventListener('message',onOwnerMessage);}catch(_){ }
  }
  function bindAudio(){
    activeAudio.addEventListener('error',()=>handleAudioFailure(new Error('audio element error')));
    activeAudio.addEventListener('ended',()=>{if(activeAudio.__sbbTrackId===currentTrack?.id)advanceTrack('ended');});
    activeAudio.addEventListener('playing',renderUi);
    activeAudio.addEventListener('pause',renderUi);
    preloadAudio.addEventListener('error',()=>{
      if(preloadedTrackId)console.debug?.('[SBB soundtrack] preload unavailable; active playback will retry normally',{track:preloadedTrackId});
    });
  }
  async function init(){
    if(initialized)return manifestPromise;
    initialized=true;
    const stored=hydrateStored();
    bindAudio();bindUi();renderUi();
    saveTimer=setInterval(saveStored,5000);
    ownerTimer=setInterval(ownerHeartbeat,2000);
    manifestPromise=loadManifest(stored);
    return manifestPromise;
  }

  window.SBB_SOUNDTRACK=Object.freeze({
    version:VERSION,
    init,
    setPlaybackState,
    pauseForSearch,
    setVolume,
    toggle:toggleEnabled,
    skip:()=>advanceTrack('next'),
    snapshot:()=>({
      enabled,available,playbackState,volume:masterVolume,
      currentTrack:currentTrack?{id:currentTrack.id,title:currentTrack.title,tier:currentTrack.tier,file:currentTrack.file,sourceFilename:currentTrack.sourceFilename}:null,
      nextTrackId:peekNextTrack()?.id||'',preloadedTrackId,
      remainingInBag:bag.length,playedInCycle:playedIds.size,trackCount:tracks.length,
      remoteBase,tabOwnsAudio,operationEpoch
    })
  });
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>init(),{once:true});else init();
})();

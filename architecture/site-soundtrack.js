/* Sports Big Board v4.1.27 — persistent site-level soundtrack engine.
   The soundtrack belongs to the application, not to any individual highlight.
   It survives score/date/program changes and follows the active playback state. */
(() => {
  'use strict';
  const VERSION='1.0';
  const STORAGE_KEY='sbb:soundtrack:v1';
  const MANIFEST_URL=new URL('assets/soundtrack/manifest.json',document.baseURI).toString();
  const cfg=window.SBB_CONFIG||{};
  const remoteBase=String(cfg.soundtrackBase||'').trim().replace(/\/+$/,'');
  const ACTIVE_STATES=new Set(['playing','starting','buffering']);
  const HARD_PAUSE_STATES=new Set(['paused','ready']);
  const $=id=>document.getElementById(id);
  const clamp=(n,min,max)=>Math.max(min,Math.min(max,Number(n)||0));

  let manifest=null;
  let tracks=[];
  let bag=[];
  let currentTrack=null;
  let standbyTrack=null;
  let activeAudioIndex=0;
  let playbackState='idle';
  let enabled=true;
  let masterVolume=.16;
  let highlightDuckFactor=.625;
  let crossfadeSeconds=2.5;
  let resumeTrackId='';
  let resumePosition=0;
  let crossfadeRaf=0;
  let crossfading=false;
  let pauseTimer=0;
  let saveTimer=0;
  let consecutiveFailures=0;
  let available=true;
  let initialized=false;
  let manifestPromise=null;

  const audio=[new Audio(),new Audio()];
  for(const a of audio){
    a.preload='auto';
    a.playsInline=true;
    a.volume=0;
  }

  function readStored(){
    try{return JSON.parse(localStorage.getItem(STORAGE_KEY)||'{}')||{};}catch(_){return {};}
  }
  function saveStored(){
    try{
      const a=audio[activeAudioIndex];
      localStorage.setItem(STORAGE_KEY,JSON.stringify({
        enabled,
        volume:masterVolume,
        currentTrackId:currentTrack?.id||'',
        currentTime:Number.isFinite(a?.currentTime)?Math.max(0,a.currentTime):0,
        bag:bag.map(x=>x.id),
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
  function rebuildBag(excludeId=''){
    bag=weightedShuffle(tracks.filter(t=>t.id!==excludeId));
    if(!bag.length && tracks.length) bag=weightedShuffle([...tracks]);
  }
  function restoreBag(ids=[]){
    const byId=new Map(tracks.map(t=>[t.id,t]));
    const seen=new Set();
    bag=[];
    for(const id of ids){
      const t=byId.get(String(id));
      if(t && !seen.has(t.id) && t.id!==currentTrack?.id){bag.push(t);seen.add(t.id);}
    }
    const missing=weightedShuffle(tracks.filter(t=>!seen.has(t.id)&&t.id!==currentTrack?.id));
    bag.push(...missing);
  }
  function drawNextTrack(){
    if(!bag.length) rebuildBag(currentTrack?.id||'');
    let next=bag.shift()||tracks[0]||null;
    if(next && currentTrack && next.id===currentTrack.id && tracks.length>1){
      bag.push(next); next=bag.shift()||tracks.find(t=>t.id!==currentTrack.id)||next;
    }
    return next;
  }

  function baseTargetVolume(){
    if(!enabled || !available || document.hidden) return 0;
    if(playbackState==='playing') return masterVolume*highlightDuckFactor;
    if(playbackState==='starting' || playbackState==='buffering') return masterVolume;
    return 0;
  }
  function setAudioVolume(a,value){ try{a.volume=clamp(value,0,1);}catch(_){ } }
  function cancelFade(){ if(crossfadeRaf) cancelAnimationFrame(crossfadeRaf); crossfadeRaf=0; }
  function fadeElement(a,to,durationMs=250,onDone=null){
    const from=Number(a.volume||0),start=performance.now();
    const tick=now=>{
      const p=Math.min(1,(now-start)/Math.max(1,durationMs));
      setAudioVolume(a,from+(to-from)*p);
      if(p<1) requestAnimationFrame(tick); else onDone?.();
    };
    requestAnimationFrame(tick);
  }
  function updateVolumes({immediate=false}={}){
    if(crossfading) return;
    const target=baseTargetVolume();
    const a=audio[activeAudioIndex];
    if(immediate) setAudioVolume(a,target); else fadeElement(a,target,220);
  }

  function loadInto(index,track,{position=0}={}){
    const a=audio[index];
    a.pause();
    a.removeAttribute('src');
    a.load();
    if(!track) return;
    a.src=trackUrl(track);
    a.preload='auto';
    a.volume=0;
    a.__sbbTrackId=track.id;
    a.__sbbFailed=false;
    if(position>0){
      const seek=()=>{
        try{ if(Number.isFinite(a.duration)&&a.duration>5) a.currentTime=Math.min(position,Math.max(0,a.duration-3)); }catch(_){ }
        a.removeEventListener('loadedmetadata',seek);
      };
      a.addEventListener('loadedmetadata',seek);
    }
    a.load();
  }
  function primeStandby(){
    const idx=1-activeAudioIndex;
    standbyTrack=drawNextTrack();
    loadInto(idx,standbyTrack);
  }
  function setCurrentTrack(track,{position=0}={}){
    currentTrack=track;
    loadInto(activeAudioIndex,currentTrack,{position});
    primeStandby();
    saveStored();
    renderUi();
  }

  function finalizeCrossfade(){
    if(!crossfading) return;
    cancelFade();
    const oldIndex=activeAudioIndex,nextIndex=1-oldIndex;
    const old=audio[oldIndex],next=audio[nextIndex];
    try{old.pause();old.currentTime=0;}catch(_){ }
    setAudioVolume(old,0);
    activeAudioIndex=nextIndex;
    currentTrack=standbyTrack;
    crossfading=false;
    standbyTrack=null;
    setAudioVolume(next,baseTargetVolume());
    primeStandby();
    consecutiveFailures=0;
    saveStored();
    renderUi();
  }
  function finishCrossfadeForPause(){
    if(!crossfading) return;
    cancelFade();
    const oldIndex=activeAudioIndex,nextIndex=1-oldIndex;
    const old=audio[oldIndex],next=audio[nextIndex];
    try{old.pause();next.pause();}catch(_){ }
    try{old.currentTime=0;}catch(_){ }
    setAudioVolume(old,0);setAudioVolume(next,0);
    activeAudioIndex=nextIndex;
    currentTrack=standbyTrack||currentTrack;
    crossfading=false;standbyTrack=null;
    primeStandby();saveStored();renderUi();
  }
  async function beginCrossfade(){
    if(crossfading || !enabled || !ACTIVE_STATES.has(playbackState) || document.hidden) return;
    const oldIndex=activeAudioIndex,nextIndex=1-oldIndex;
    const old=audio[oldIndex],next=audio[nextIndex];
    if(!standbyTrack){ primeStandby(); if(!standbyTrack) return; }
    crossfading=true;
    setAudioVolume(next,0);
    try{await next.play();}catch(err){crossfading=false;handleAudioFailure(nextIndex,err);return;}
    const duration=Math.max(250,Number(crossfadeSeconds||2.5)*1000),start=performance.now(),target=baseTargetVolume(),oldStart=Number(old.volume||target);
    const step=now=>{
      if(!crossfading) return;
      const p=Math.min(1,(now-start)/duration);
      setAudioVolume(old,oldStart*(1-p));
      setAudioVolume(next,target*p);
      if(p<1) crossfadeRaf=requestAnimationFrame(step); else finalizeCrossfade();
    };
    crossfadeRaf=requestAnimationFrame(step);
  }

  function shouldSound(){ return enabled && available && !document.hidden && ACTIVE_STATES.has(playbackState); }
  async function ensurePlaying(){
    if(!initialized) await init();
    if(!shouldSound() || !currentTrack) return false;
    clearTimeout(pauseTimer);pauseTimer=0;
    const a=audio[activeAudioIndex];
    if(!a.src) loadInto(activeAudioIndex,currentTrack,{position:resumePosition});
    try{
      if(a.paused) await a.play();
      setAudioVolume(a,baseTargetVolume());
      consecutiveFailures=0;
      renderUi();
      return true;
    }catch(err){
      if(err?.name!=='NotAllowedError') handleAudioFailure(activeAudioIndex,err);
      renderUi();
      return false;
    }
  }
  function pauseNow({fade=true}={}){
    clearTimeout(pauseTimer);pauseTimer=0;
    if(crossfading) finishCrossfadeForPause();
    const a=audio[activeAudioIndex];
    const done=()=>{try{a.pause();}catch(_){ }saveStored();renderUi();};
    if(fade && !a.paused && a.volume>0) fadeElement(a,0,220,done); else {setAudioVolume(a,0);done();}
  }
  function scheduleEndedPause(){
    clearTimeout(pauseTimer);
    pauseTimer=setTimeout(()=>{ if(playbackState==='ended') pauseNow({fade:true}); },2800);
  }
  function skipTrack(){
    if(crossfading) finishCrossfadeForPause();
    const old=audio[activeAudioIndex];try{old.pause();old.currentTime=0;}catch(_){ }
    currentTrack=standbyTrack||drawNextTrack();
    standbyTrack=null;
    loadInto(activeAudioIndex,currentTrack);
    primeStandby();saveStored();renderUi();
    if(shouldSound()) ensurePlaying();
  }
  function handleAudioFailure(index,err){
    const a=audio[index];
    if(a.__sbbFailed) return;
    a.__sbbFailed=true;
    consecutiveFailures++;
    console.warn('[SBB soundtrack] track unavailable',{track:a.__sbbTrackId,error:err?.message||String(err||'audio error'),base:remoteBase||'local'});
    if(index!==activeAudioIndex) { primeStandby(); return; }
    if(consecutiveFailures>=Math.min(8,Math.max(1,tracks.length))){
      available=false;pauseNow({fade:false});renderUi();return;
    }
    skipTrack();
  }

  function setPlaybackState(mode){
    const next=String(mode||'idle').toLowerCase();
    const changed=next!==playbackState;
    playbackState=next;
    if(!changed) return;
    if(ACTIVE_STATES.has(playbackState)){
      clearTimeout(pauseTimer);pauseTimer=0;
      ensurePlaying();
      updateVolumes();
    }else if(HARD_PAUSE_STATES.has(playbackState)){
      pauseNow({fade:true});
    }else if(playbackState==='ended'){
      scheduleEndedPause();
    }
    renderUi();
  }
  function pauseForSearch(){ playbackState='paused';pauseNow({fade:true});renderUi(); }

  function toggleEnabled(){
    enabled=!enabled;available=true;consecutiveFailures=0;saveStored();renderUi();
    if(enabled && ACTIVE_STATES.has(playbackState)) ensurePlaying(); else if(!enabled) pauseNow({fade:true});
  }
  function setVolume(value){
    masterVolume=clamp(value,0,.5);saveStored();updateVolumes();renderUi();
  }
  function toggleVolumePopover(force){
    const pop=$('soundtrackVolumePopover'); if(!pop)return;
    const show=typeof force==='boolean'?force:pop.classList.contains('hidden');
    pop.classList.toggle('hidden',!show);
    $('soundtrackVolumeBtn')?.setAttribute('aria-expanded',show?'true':'false');
  }
  function renderUi(){
    const toggle=$('soundtrackToggle'),volBtn=$('soundtrackVolumeBtn'),slider=$('soundtrackVolume');
    if(toggle){
      const sounding=shouldSound() && !audio[activeAudioIndex].paused;
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
    if(slider && Math.abs(Number(slider.value)-masterVolume)>.001) slider.value=String(masterVolume);
    document.body?.classList.toggle('sbb-soundtrack-enabled',enabled);
  }

  async function loadManifest(){
    if(manifestPromise) return manifestPromise;
    manifestPromise=fetch(MANIFEST_URL,{cache:'force-cache'}).then(async r=>{
      if(!r.ok) throw new Error(`Soundtrack manifest HTTP ${r.status}`);
      manifest=await r.json();
      tracks=(Array.isArray(manifest?.tracks)?manifest.tracks:[]).filter(t=>t?.id&&t?.file&&t?.disabled!==true);
      const defs=manifest?.playbackDefaults||{};
      if(Number.isFinite(Number(defs.crossfadeSeconds))) crossfadeSeconds=clamp(defs.crossfadeSeconds,.5,8);
      if(Number.isFinite(Number(defs.defaultMusicVolume)) && !localStorage.getItem(STORAGE_KEY)) masterVolume=clamp(defs.defaultMusicVolume,0,.5);
      const normal=Math.max(.001,Number(defs.defaultMusicVolume||.16)),duck=Math.max(0,Number(defs.highlightPlayingVolume||.10));
      highlightDuckFactor=clamp(duck/normal,0,1);
      const stored=readStored();
      currentTrack=tracks.find(t=>t.id===resumeTrackId)||null;
      if(!currentTrack) currentTrack=weightedShuffle(tracks)[0]||null;
      restoreBag(Array.isArray(stored.bag)?stored.bag:[]);
      if(currentTrack) loadInto(activeAudioIndex,currentTrack,{position:resumePosition});
      primeStandby();
      available=tracks.length>0;
      renderUi();
      return manifest;
    }).catch(err=>{available=false;console.warn('[SBB soundtrack] manifest unavailable',err);renderUi();return null;});
    return manifestPromise;
  }
  function bindUi(){
    $('soundtrackToggle')?.addEventListener('click',toggleEnabled);
    $('soundtrackVolumeBtn')?.addEventListener('click',ev=>{ev.stopPropagation();toggleVolumePopover();});
    $('soundtrackVolume')?.addEventListener('input',ev=>setVolume(ev.target.value));
    document.addEventListener('click',ev=>{if(!ev.target.closest?.('#soundtrackControls'))toggleVolumePopover(false);});
    document.addEventListener('pointerdown',()=>{if(enabled&&ACTIVE_STATES.has(playbackState))ensurePlaying();},{capture:true,passive:true});
    document.addEventListener('keydown',()=>{if(enabled&&ACTIVE_STATES.has(playbackState))ensurePlaying();},{capture:true,passive:true});
    document.addEventListener('visibilitychange',()=>{if(document.hidden)pauseNow({fade:false});else if(ACTIVE_STATES.has(playbackState))ensurePlaying();});
    window.addEventListener('beforeunload',saveStored);
  }
  function bindAudio(){
    audio.forEach((a,index)=>{
      a.addEventListener('error',()=>handleAudioFailure(index,new Error('audio element error')));
      a.addEventListener('ended',()=>{if(index===activeAudioIndex&&!crossfading)skipTrack();});
      a.addEventListener('playing',renderUi);a.addEventListener('pause',renderUi);
      a.addEventListener('timeupdate',()=>{
        if(index!==activeAudioIndex||crossfading||!shouldSound())return;
        const duration=Number(a.duration||currentTrack?.durationSeconds||0),remain=duration-Number(a.currentTime||0);
        if(duration>0 && remain>0 && remain<=Math.max(.8,crossfadeSeconds+.18)) beginCrossfade();
      });
    });
  }
  async function init(){
    if(initialized)return manifestPromise;
    initialized=true;hydrateStored();bindAudio();bindUi();renderUi();
    saveTimer=setInterval(saveStored,5000);
    return loadManifest();
  }

  window.SBB_SOUNDTRACK=Object.freeze({
    version:VERSION,
    init,
    setPlaybackState,
    pauseForSearch,
    setVolume,
    toggle:toggleEnabled,
    skip:skipTrack,
    snapshot:()=>({enabled,available,playbackState,volume:masterVolume,currentTrack:currentTrack?{id:currentTrack.id,title:currentTrack.title,tier:currentTrack.tier}:null,remainingInBag:bag.length,trackCount:tracks.length,remoteBase})
  });
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>init(),{once:true});else init();
})();

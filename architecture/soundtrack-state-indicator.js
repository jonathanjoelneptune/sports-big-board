/* Sports Big Board v4.5.6 — soundtrack state indicator.
   Visual-only authority: OFF=neutral, PLAYING=green, SUPPRESSED=yellow.
   It observes the existing soundtrack + Media Intelligence authorities and never
   changes audio ownership, mute state, playback state, or media selection. */
(() => {
  'use strict';
  if (window.SBB_SOUNDTRACK_STATE_INDICATOR) return;

  const VERSION='1.0';
  const STYLE_ID='sbbSoundtrackStateIndicatorStyle';
  const ACTIVE_STATES=new Set(['playing','starting','buffering']);
  let lastState='';
  let pollTimer=0;
  let unsubscribePlayback=null;

  function soundtrackAudio(){ return window.__SBB_SOUNDTRACK_SINGLETON__?.audio||null; }
  function soundtrackSnapshot(){
    try{return window.SBB_SOUNDTRACK?.snapshot?.()||{};}catch(_){return {};}
  }
  function mediaDecision(){
    try{return window.SBB_MEDIA_INTELLIGENCE?.snapshot?.().currentDecision||{};}catch(_){return {};}
  }
  function computeState(){
    const snap=soundtrackSnapshot(),audio=soundtrackAudio();
    const enabled=!!snap.enabled&&!!snap.experienceStarted&&snap.available!==false;
    const active=ACTIVE_STATES.has(String(snap.playbackState||'').toLowerCase());
    if(!enabled||!active||!audio)return 'off';
    // Media Intelligence is the only production authority that intentionally sets
    // the soundtrack element muted while the clip keeps playing. A muted active
    // soundtrack therefore means the site soundtrack is yielding to clip audio.
    if(audio.muted)return 'suppressed';
    const audible=!!snap.tabOwnsAudio&&!audio.paused&&Number(audio.volume||0)>0;
    return audible?'playing':'off';
  }
  function installStyles(){
    try{
      if(!document?.createElement||!document?.head?.appendChild||document.getElementById?.(STYLE_ID))return;
      const style=document.createElement('style');style.id=STYLE_ID;
      style.textContent=`
#soundtrackToggle.sbb-music-state-off{background:rgba(255,255,255,.045)!important;border-color:rgba(255,255,255,.18)!important;color:inherit!important;box-shadow:none!important;}
#soundtrackToggle.sbb-music-state-playing{background:#168a4a!important;border-color:#55d98a!important;color:#fff!important;box-shadow:0 0 0 1px rgba(85,217,138,.22),0 0 12px rgba(22,138,74,.28)!important;}
#soundtrackToggle.sbb-music-state-suppressed{background:#d4a017!important;border-color:#ffd45b!important;color:#171100!important;box-shadow:0 0 0 1px rgba(255,212,91,.24),0 0 12px rgba(212,160,23,.3)!important;}
`;
      document.head.appendChild(style);
    }catch(_){ }
  }
  function describe(state){
    const snap=soundtrackSnapshot(),decision=mediaDecision();
    const track=snap.currentTrack?.title?` • ${snap.currentTrack.title}`:'';
    if(state==='suppressed'){
      const status=String(decision.status||'UNKNOWN').replaceAll('_',' ');
      return {title:`Website music suppressed for clip audio • ${status}`,aria:'Sports Big Board soundtrack suppressed for clip audio'};
    }
    if(state==='playing')return {title:`Website music playing${track}`,aria:'Pause Sports Big Board soundtrack'};
    if(!snap.experienceStarted)return {title:'Soundtrack starts with Sports Big Board',aria:'Sports Big Board soundtrack off'};
    if(snap.enabled)return {title:'Website music paused',aria:'Sports Big Board soundtrack paused'};
    return {title:'Turn soundtrack on',aria:'Enable Sports Big Board soundtrack'};
  }
  function apply(){
    const button=document?.getElementById?.('soundtrackToggle');if(!button)return 'off';
    const state=computeState();
    button.classList?.toggle?.('sbb-music-state-off',state==='off');
    button.classList?.toggle?.('sbb-music-state-playing',state==='playing');
    button.classList?.toggle?.('sbb-music-state-suppressed',state==='suppressed');
    try{button.dataset.sbbSoundtrackState=state;}catch(_){button.setAttribute?.('data-sbb-soundtrack-state',state);}
    const label=describe(state);button.title=label.title;button.setAttribute?.('aria-label',label.aria);
    try{document.body?.setAttribute?.('data-sbb-soundtrack-state',state);}catch(_){ }
    if(state!==lastState){
      lastState=state;
      try{window.dispatchEvent(new CustomEvent('sbb:soundtrack-indicator',{detail:{state,at:Date.now(),decision:mediaDecision()}}));}catch(_){ }
    }
    return state;
  }
  function bindAudio(){
    const audio=soundtrackAudio();if(!audio||audio.__sbbStateIndicatorBound)return;
    try{audio.__sbbStateIndicatorBound=true;}catch(_){ }
    for(const event of ['playing','pause','volumechange','ended','emptied','loadeddata']){
      try{audio.addEventListener?.(event,apply);}catch(_){ }
    }
  }
  function bind(){
    installStyles();bindAudio();apply();
    try{window.addEventListener('sbb:media-intelligence',()=>{bindAudio();apply();});}catch(_){ }
    try{unsubscribePlayback=window.SBB_PLAYBACK_SESSION?.subscribe?.(()=>{bindAudio();apply();})||null;}catch(_){ }
    try{document.getElementById?.('soundtrackToggle')?.addEventListener?.('click',()=>setTimeout(apply,0));}catch(_){ }
    // Low-cost safety poll catches state changes from browser ownership/visibility
    // paths that do not emit a dedicated UI event. It only reads state and updates
    // one button; it never touches audio or playback.
    pollTimer=setInterval(()=>{bindAudio();apply();},1000);
  }
  const api=Object.freeze({
    version:VERSION,refresh:apply,
    snapshot:()=>({state:computeState(),lastState,decision:mediaDecision(),polling:!!pollTimer})
  });
  window.SBB_SOUNDTRACK_STATE_INDICATOR=api;
  if(document?.readyState==='loading')document.addEventListener?.('DOMContentLoaded',bind,{once:true});else bind();
})();

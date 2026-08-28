/* Sports Big Board v4.4.7 — temporary site soundtrack mute.
   Media Intelligence is parked. Keep the established soundtrack runtime loaded
   for compatibility, but production site music remains muted until re-enabled. */
(() => {
  'use strict';
  if(!window.SBB_SITE_SOUNDTRACK_MUTED)return;
  function apply(){
    const audio=window.__SBB_SOUNDTRACK_SINGLETON__?.audio||null;
    if(audio){try{audio.muted=true;}catch(_){}}
    const btn=document.getElementById?.('soundtrackToggle');
    if(btn){
      btn.disabled=true;
      btn.classList?.remove?.('is-enabled','is-playing','sbb-music-state-playing','sbb-music-state-suppressed');
      btn.setAttribute?.('aria-pressed','false');
      btn.setAttribute?.('aria-label','Sports Big Board site music temporarily muted');
      btn.title='Site music temporarily muted';
      btn.textContent='♫ ▶';
    }
    try{document.body?.setAttribute?.('data-sbb-site-soundtrack','muted');}catch(_){}
  }
  apply();
  const audio=window.__SBB_SOUNDTRACK_SINGLETON__?.audio||null;
  for(const event of ['playing','play','volumechange','loadeddata']){try{audio?.addEventListener?.(event,()=>setTimeout(apply,0));}catch(_){}}
  try{document.addEventListener?.('DOMContentLoaded',apply,{once:true});}catch(_){}
  setTimeout(apply,0);setTimeout(apply,500);
  window.SBB_SITE_SOUNDTRACK_MUTE=Object.freeze({version:'1.0',apply,snapshot:()=>({muted:!!window.__SBB_SOUNDTRACK_SINGLETON__?.audio?.muted})});
})();

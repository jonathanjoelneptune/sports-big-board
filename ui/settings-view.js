/* v4.2.1 local/cloud settings UI. Never reads or displays saved secret values. */
(() => {
  const $=id=>document.getElementById(id);
  function statusText(row){return row?.configured?'CONFIGURED':'NOT SET';}
  function renderStatus(payload){
    const c=payload?.connections||{};
    for(const [key,id] of [['highlightly','settingsHighlightlyStatus'],['youtube','settingsYoutubeStatus'],['openai','settingsOpenaiStatus']]){
      const el=$(id);if(!el)continue;const configured=!!c[key]?.configured;el.textContent=statusText(c[key]);el.classList.toggle('configured',configured);el.classList.toggle('missing',!configured);
    }
    const writable=payload?.secretsWritable!==false;
    ['settingsHighlightlyKey','settingsYoutubeKey','settingsOpenaiKey'].forEach(id=>{const el=$(id);if(el){el.disabled=!writable;el.placeholder=writable?'Enter replacement key only if needed':'Managed on cloud server';}});
    const btn=$('saveApiSettingsBtn');if(btn){btn.disabled=!writable;btn.classList.toggle('hidden',!writable);}
    const msg=$('apiSettingsMessage');if(msg && !writable)msg.textContent='API credentials are managed securely on the Sports Big Board cloud server.';
  }
  async function loadStatus(){try{const r=await fetch('/api/settings',{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);renderStatus(await r.json());}catch(err){if($('apiSettingsMessage'))$('apiSettingsMessage').textContent=`Unable to read API settings: ${err.message}`;}}
  async function save(){
    const btn=$('saveApiSettingsBtn'),msg=$('apiSettingsMessage');if(btn)btn.disabled=true;if(msg)msg.textContent='Saving machine settings…';
    const replacements={};
    for(const [key,id] of [['highlightly','settingsHighlightlyKey'],['youtube','settingsYoutubeKey'],['openai','settingsOpenaiKey']]){const value=$(id)?.value?.trim();if(value)replacements[key]=value;}
    try{
      const r=await fetch('/api/settings/secrets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({replacements}),cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);const payload=await r.json();renderStatus(payload);
      ['settingsHighlightlyKey','settingsYoutubeKey','settingsOpenaiKey'].forEach(id=>{if($(id))$(id).value='';});if(msg)msg.textContent='Saved. Future Sports Big Board versions on this computer will reuse these keys.';
    }catch(err){if(msg)msg.textContent=`Save failed: ${err.message}`;}finally{if(btn)btn.disabled=false;}
  }
  function syncPrefs(){
    const prefs=window.SBB_VIEW_PREFS;if(!prefs)return;
    if($('keepVideoVisibleToggle'))$('keepVideoVisibleToggle').checked=!!prefs.keepVideoVisible;
    if($('gameCenterLayoutSelect'))$('gameCenterLayoutSelect').value=prefs.gameCenterLayout||'below';
    const hint=$('gameCenterLayoutHint');if(hint)hint.textContent=prefs.sideActive?'Wide-screen side layout is active.':'Mobile always uses below-video layout; side mode activates only on a wide PC screen.';
  }
  function init(){
    $('keepVideoVisibleToggle')?.addEventListener('change',ev=>window.SBB_VIEW_PREFS?.setKeepVideoVisible?.(ev.target.checked));
    $('gameCenterLayoutSelect')?.addEventListener('change',ev=>window.SBB_VIEW_PREFS?.setGameCenterLayout?.(ev.target.value));
    $('saveApiSettingsBtn')?.addEventListener('click',save);window.addEventListener('sbb:view-prefs',syncPrefs);syncPrefs();loadStatus();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  window.SBB_SETTINGS_VIEW=Object.freeze({version:'1.0',loadStatus});
})();

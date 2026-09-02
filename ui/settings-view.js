/* Sports Big Board settings UI. Deployment identity is read-only and comes from
   the canonical release authority created by index.html. This module must never
   assign or rewrite SBB_RELEASE_VERSION or SBB_CORE.version. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const clean=v=>String(v??'').trim();
  function releaseVersion(){
    return clean(window.SBB_RELEASE?.version||window.SBB_RELEASE_VERSION||document.querySelector('meta[name="sbb-release-version"]')?.content||'UNKNOWN')||'UNKNOWN';
  }
  function api(path){
    const base=clean(window.SBB_CONFIG?.apiBase).replace(/\/$/,'');
    return base?`${base}${path}`:path;
  }
  function statusText(row){return row?.configured?'CONFIGURED':'NOT SET';}
  function renderStatus(payload){
    const c=payload?.connections||{};
    for(const [key,id] of [['highlightly','settingsHighlightlyStatus'],['youtube','settingsYoutubeStatus'],['openai','settingsOpenaiStatus']]){
      const el=$(id);if(!el)continue;const configured=!!c[key]?.configured;el.textContent=statusText(c[key]);el.classList.toggle('configured',configured);el.classList.toggle('missing',!configured);
    }
    const writable=payload?.secretsWritable!==false;
    ['settingsHighlightlyKey','settingsYoutubeKey','settingsOpenaiKey'].forEach(id=>{const el=$(id);if(el){el.disabled=!writable;el.placeholder=writable?'Enter replacement key only if needed':'Managed on cloud server';}});
    const btn=$('saveApiSettingsBtn');if(btn){btn.disabled=!writable;btn.classList.toggle('hidden',!writable);}
    const msg=$('apiSettingsMessage');if(msg&&!writable)msg.textContent='API credentials are managed securely on the Sports Big Board cloud server.';
  }
  async function loadStatus(){
    try{const r=await fetch(api('/api/settings'),{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);renderStatus(await r.json());}
    catch(err){if($('apiSettingsMessage'))$('apiSettingsMessage').textContent=`Unable to read API settings: ${err.message}`;}
  }
  async function save(){
    const btn=$('saveApiSettingsBtn'),msg=$('apiSettingsMessage');if(btn)btn.disabled=true;if(msg)msg.textContent='Saving machine settings…';
    const replacements={};
    for(const [key,id] of [['highlightly','settingsHighlightlyKey'],['youtube','settingsYoutubeKey'],['openai','settingsOpenaiKey']]){const value=$(id)?.value?.trim();if(value)replacements[key]=value;}
    try{
      const r=await fetch(api('/api/settings/secrets'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({replacements}),cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);const payload=await r.json();renderStatus(payload);
      ['settingsHighlightlyKey','settingsYoutubeKey','settingsOpenaiKey'].forEach(id=>{if($(id))$(id).value='';});if(msg)msg.textContent='Saved. Future Sports Big Board versions on this computer will reuse these keys.';
    }catch(err){if(msg)msg.textContent=`Save failed: ${err.message}`;}finally{if(btn)btn.disabled=false;}
  }
  function renderRelease(payload={}){
    const front=releaseVersion();
    const backend=clean(payload.backendVersion||payload.version||'UNKNOWN')||'UNKNOWN';
    const match=payload.versionMatch===true&&front===backend;
    if($('settingsFrontendVersion'))$('settingsFrontendVersion').textContent=front;
    if($('settingsBackendVersion'))$('settingsBackendVersion').textContent=backend;
    const badge=$('settingsReleaseMatch');if(badge){badge.textContent=match?'MATCHED':'MISMATCH';badge.classList.toggle('configured',match);badge.classList.toggle('missing',!match);}
    const msg=$('settingsReleaseMessage');if(msg)msg.textContent=match?`Frontend and cloud backend are synchronized at v${front}.`:`Release mismatch: frontend v${front} • backend v${backend}. Optional background discovery may pause until the deployment is synchronized.`;
    document.documentElement.dataset.sbbReleaseMatch=match?'1':'0';
    return match;
  }
  async function reportRelease(){
    const front=releaseVersion();
    if($('settingsFrontendVersion'))$('settingsFrontendVersion').textContent=front;
    try{
      const r=await fetch(api(`/api/release-identity?frontendVersion=${encodeURIComponent(front)}`),{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);return renderRelease(await r.json());
    }catch(err){
      if($('settingsBackendVersion'))$('settingsBackendVersion').textContent='UNAVAILABLE';
      if($('settingsReleaseMatch')){$('settingsReleaseMatch').textContent='CHECK FAILED';$('settingsReleaseMatch').classList.add('missing');}
      if($('settingsReleaseMessage'))$('settingsReleaseMessage').textContent=`Unable to verify frontend/backend release identity: ${err.message}`;
      return false;
    }
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
    $('saveApiSettingsBtn')?.addEventListener('click',save);
    window.addEventListener('sbb:view-prefs',syncPrefs);syncPrefs();loadStatus();reportRelease();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  window.SBB_SETTINGS_VIEW=Object.freeze({version:releaseVersion(),loadStatus,reportRelease,releaseVersion});
})();

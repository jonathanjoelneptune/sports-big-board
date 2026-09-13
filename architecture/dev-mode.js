/* Sports Big Board v5.2.9 — one reliable global Dev Mode authority.

   Five clicks anywhere on the visible Sports Big Board brand is the only Dev
   unlock. Dev Mode is now binary: the global dev classes/data attributes,
   diagnostics/broadcast presentation, developer cards, playback terminal, and
   operator controls all follow the same enabled state.
*/
(() => {
  'use strict';
  if(window.SBB_DEV_MODE?.version==='5.2.9')return;

  const VERSION='5.2.9';
  const CLICK_TARGET=5;
  const CLICK_WINDOW_MS=6000;
  // Keep the existing session key so an already-unlocked session survives this hotfix.
  const SESSION_KEY='sbb.dev.enabled.v528';
  let enabled=false;
  let brandClicks=0;
  let brandWindowStarted=0;

  const explicit=()=>{
    try{
      const q=new URLSearchParams(location.search);
      return q.get('dev')==='1'||q.get('debug')==='1';
    }catch(_){return false;}
  };
  const sessionEnabled=()=>{try{return sessionStorage.getItem(SESSION_KEY)==='1';}catch(_){return false;}};
  const persistSession=next=>{try{if(next)sessionStorage.setItem(SESSION_KEY,'1');else sessionStorage.removeItem(SESSION_KEY);}catch(_){} };

  function installStyle(){
    if(document.getElementById('sbbDevModeV529Style'))return;
    const style=document.createElement('style');
    style.id='sbbDevModeV529Style';
    style.textContent=`
      .brand{user-select:none;-webkit-user-select:none}
      html[data-sbb-dev="1"] .brand,body[data-sbb-dev="1"] .brand{cursor:pointer}
      html[data-sbb-dev="1"] .brand-mark{filter:drop-shadow(0 0 5px rgba(36,148,255,.55))}
      #sbbDevModeToast{position:fixed;top:14px;left:50%;z-index:2147483000;transform:translate(-50%,-12px);opacity:0;pointer-events:none;padding:9px 13px;border:1px solid #346b90;border-radius:999px;background:rgba(8,17,25,.96);color:#9ed9ff;font:800 10px/1 system-ui,sans-serif;letter-spacing:.055em;box-shadow:0 8px 26px rgba(0,0,0,.35);transition:opacity .14s linear,transform .14s linear}
      #sbbDevModeToast.show{opacity:1;transform:translate(-50%,0)}
    `;
    document.head.appendChild(style);
  }

  function showToast(text){
    installStyle();
    let toast=document.getElementById('sbbDevModeToast');
    if(!toast){toast=document.createElement('div');toast.id='sbbDevModeToast';toast.setAttribute('role','status');toast.setAttribute('aria-live','polite');document.body?.appendChild(toast);}
    if(!toast)return;
    toast.textContent=text;toast.classList.add('show');
    clearTimeout(showToast._timer);showToast._timer=setTimeout(()=>toast.classList.remove('show'),2200);
  }

  function syncLegacyControl(){
    const btn=document.getElementById('devModeToggleBtn');
    if(!btn)return;
    btn.setAttribute('aria-pressed',String(enabled));
    btn.textContent=enabled?'DEV MODE: ON':'DEV MODE: OFF';
  }

  function syncDiagnostics(){
    const body=document.body;
    if(!body)return;
    // Normal mode is the polished broadcast surface. Dev Mode exposes diagnostics.
    body.classList.toggle('diagnostics-off',!enabled);
    body.classList.toggle('broadcast-mode',!enabled);
    // app.js still contains the legacy diagnostics preference reader. Mirror the
    // authoritative Dev Mode state into that key so it can never restore the
    // opposite presentation during DOMContentLoaded.
    try{localStorage.setItem('sbb-diagnostics-visible',enabled?'1':'0');}catch(_){}
    const brand=document.querySelector('.brand');
    if(brand)brand.title=enabled?'Dev Mode ON • click 5× to disable':'Dev Mode OFF • click 5× to enable';
  }

  function scheduleDiagnosticsSync(){
    syncDiagnostics();
    // app.js has an older bubble-phase five-click diagnostics handler. Reassert
    // the single Dev Mode truth after the current event/DOMContentLoaded dispatch
    // so that legacy handler cannot invert diagnostics after Dev Mode toggles.
    try{queueMicrotask(syncDiagnostics);}catch(_){Promise.resolve().then(syncDiagnostics);}
    setTimeout(syncDiagnostics,0);
  }

  function apply(next,reason='',{persist=true,announce=false}={}){
    enabled=!!next;
    for(const node of [document.documentElement,document.body]){
      if(!node)continue;
      node.classList.toggle('dev-mode',enabled);
      node.classList.toggle('sbb-dev-mode',enabled);
      if(enabled)node.dataset.sbbDev='1';else delete node.dataset.sbbDev;
    }
    scheduleDiagnosticsSync();
    if(persist)persistSession(enabled);
    syncLegacyControl();
    try{window.dispatchEvent(new CustomEvent('sbb:dev-mode',{detail:{enabled,reason:String(reason||''),version:VERSION}}));}catch(_){}
    try{if(enabled)window.SBB_SPORTS_TICKER?.ensureDevUtility?.();}catch(_){}
    if(announce)showToast(enabled?'DEV MODE ON • ALL DEV UTILITIES ENABLED':'DEV MODE OFF • BROADCAST VIEW');
    return enabled;
  }

  function set(next,reason='manual',options={}){return apply(!!next,reason,options);}
  function toggle(reason='manual',options={}){return apply(!enabled,reason,options);}
  function isEnabled(){return !!enabled;}
  function resetForLoad(){return apply(explicit()||sessionEnabled(),'page-load',{persist:false,announce:false});}

  function isBrandClick(ev){
    const target=ev.target;
    if(!(target instanceof Element))return false;
    const brand=target.closest('.brand');
    if(!brand)return false;
    if(target.closest('button,a,input,select,textarea,label'))return false;
    return true;
  }

  function onCapturedBrandClick(ev){
    if(!isBrandClick(ev))return;
    const now=performance.now();
    if(!brandWindowStarted||now-brandWindowStarted>CLICK_WINDOW_MS){brandWindowStarted=now;brandClicks=0;}
    brandClicks++;
    if(brandClicks<CLICK_TARGET)return;
    brandClicks=0;brandWindowStarted=0;
    toggle('brand-five-click',{persist:true,announce:true});
  }

  function bindGesture(){
    if(document.documentElement.dataset.sbbGlobalDevGestureBound==='1')return;
    document.documentElement.dataset.sbbGlobalDevGestureBound='1';
    document.addEventListener('click',onCapturedBrandClick,true);
  }

  function bindLegacyToggle(){
    const btn=document.getElementById('devModeToggleBtn');
    if(!btn||btn.dataset.sbbDevBound==='1')return;
    btn.dataset.sbbDevBound='1';
    btn.addEventListener('click',()=>toggle('legacy-dev-button',{persist:true,announce:true}));
    syncLegacyControl();
  }

  function init(){
    installStyle();resetForLoad();bindGesture();bindLegacyToggle();
    let passes=0;const timer=setInterval(()=>{passes++;bindLegacyToggle();if(passes>=16)clearInterval(timer);},500);
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  window.SBB_DEV_MODE=Object.freeze({version:VERSION,set,toggle,isEnabled,resetForLoad,enable:reason=>set(true,reason||'manual',{persist:true,announce:true}),disable:reason=>set(false,reason||'manual',{persist:true,announce:true})});
})();

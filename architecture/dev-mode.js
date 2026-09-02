/* Sports Big Board v5.2.8 — one reliable global Dev Mode authority.

   Five clicks anywhere on the visible Sports Big Board brand is the only Dev
   unlock. The gesture is captured at document level so nested brand text/marks
   cannot miss it. Dev state applies to both <html> and <body>, persists for the
   browser session, and exposes every developer utility at once.
*/
(() => {
  'use strict';
  if(window.SBB_DEV_MODE?.version==='5.2.8')return;

  const VERSION='5.2.8';
  const CLICK_TARGET=5;
  const CLICK_WINDOW_MS=6000;
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
    if(document.getElementById('sbbDevModeV528Style'))return;
    const style=document.createElement('style');
    style.id='sbbDevModeV528Style';
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

  function apply(next,reason='',{persist=true,announce=false}={}){
    enabled=!!next;
    for(const node of [document.documentElement,document.body]){
      if(!node)continue;
      node.classList.toggle('dev-mode',enabled);
      node.classList.toggle('sbb-dev-mode',enabled);
      if(enabled)node.dataset.sbbDev='1';else delete node.dataset.sbbDev;
    }
    if(persist)persistSession(enabled);
    syncLegacyControl();
    try{window.dispatchEvent(new CustomEvent('sbb:dev-mode',{detail:{enabled,reason:String(reason||''),version:VERSION}}));}catch(_){}
    try{if(enabled)window.SBB_SPORTS_TICKER?.ensureDevUtility?.();}catch(_){}
    if(announce)showToast(enabled?'DEV MODE ON • ALL DEV UTILITIES ENABLED':'DEV MODE OFF');
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

/* Sports Big Board v5.2.7 — single global Dev Mode authority.

   Five clicks on the Sports Big Board brand is the one Dev switch. There are no
   nested developer-mode gates: enabling Dev marks both <html> and <body>, emits a
   single sbb:dev-mode event, and every developer utility can key off that state.
*/
(() => {
  'use strict';
  if(window.SBB_DEV_MODE?.version==='5.2.7')return;

  const VERSION='5.2.7';
  const CLICK_TARGET=5;
  const CLICK_WINDOW_MS=2600;
  let enabled=false;
  let brandClicks=0;
  let brandWindowStarted=0;

  const explicit=()=>{
    try{
      const q=new URLSearchParams(location.search);
      return q.get('dev')==='1'||q.get('debug')==='1';
    }catch(_){return false;}
  };

  function syncLegacyControl(){
    const btn=document.getElementById('devModeToggleBtn');
    if(!btn)return;
    btn.setAttribute('aria-pressed',String(enabled));
    btn.textContent=enabled?'DEV MODE: ON':'DEV MODE: OFF';
  }

  function apply(next,reason=''){
    enabled=!!next;
    const root=document.documentElement;
    const body=document.body;
    for(const node of [root,body]){
      if(!node)continue;
      node.classList.toggle('dev-mode',enabled);
      node.classList.toggle('sbb-dev-mode',enabled);
      if(enabled)node.dataset.sbbDev='1';
      else delete node.dataset.sbbDev;
    }
    syncLegacyControl();
    try{
      window.dispatchEvent(new CustomEvent('sbb:dev-mode',{detail:{enabled,reason:String(reason||''),version:VERSION}}));
    }catch(_){}
    return enabled;
  }

  function set(next,reason='manual'){return apply(!!next,reason);}
  function toggle(reason='manual'){return apply(!enabled,reason);}
  function isEnabled(){return !!enabled;}
  function resetForLoad(){return apply(explicit(),'page-load');}

  function bindBrandGesture(){
    const brand=document.querySelector('.brand');
    if(!brand||brand.dataset.sbbDevGestureBound==='1')return false;
    brand.dataset.sbbDevGestureBound='1';
    brand.title=brand.title||'Sports Big Board';
    brand.addEventListener('click',ev=>{
      if(ev.target?.closest?.('button,a,input,select,textarea,label'))return;
      const now=performance.now();
      if(!brandWindowStarted||now-brandWindowStarted>CLICK_WINDOW_MS){
        brandWindowStarted=now;brandClicks=0;
      }
      brandClicks++;
      if(brandClicks<CLICK_TARGET)return;
      brandClicks=0;brandWindowStarted=0;
      toggle('brand-five-click');
    },{passive:true});
    return true;
  }

  function bindLegacyToggle(){
    const btn=document.getElementById('devModeToggleBtn');
    if(!btn||btn.dataset.sbbDevBound==='1')return;
    btn.dataset.sbbDevBound='1';
    btn.addEventListener('click',()=>toggle('legacy-dev-button'));
    syncLegacyControl();
  }

  function init(){
    resetForLoad();
    bindBrandGesture();
    bindLegacyToggle();
    // Settings and operator modules can render after this script. Re-bind only the
    // gesture/control surfaces; Dev state itself remains one global boolean.
    let passes=0;
    const timer=setInterval(()=>{
      passes++;bindBrandGesture();bindLegacyToggle();
      if(passes>=24)clearInterval(timer);
    },250);
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  window.SBB_DEV_MODE=Object.freeze({version:VERSION,set,toggle,isEnabled,resetForLoad,enable:reason=>set(true,reason||'manual'),disable:reason=>set(false,reason||'manual')});
})();

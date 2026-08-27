/* Sports Big Board v4.4.2 — ephemeral Dev Mode authority.
   Dev Mode is deliberately session-ephemeral: every full page load starts OFF.
   Explicit ?dev=1 / ?debug=1 is treated as an intentional opt-in for that load. */
(() => {
  'use strict';
  if(window.SBB_DEV_MODE)return;
  let enabled=false;
  const explicit=()=>{try{const q=new URLSearchParams(location.search);return q.get('dev')==='1'||q.get('debug')==='1';}catch(_){return false;}};
  function apply(next,reason=''){
    enabled=!!next;
    const body=document.body;
    if(body){body.classList.toggle('dev-mode',enabled);if(enabled)body.dataset.sbbDev='1';else delete body.dataset.sbbDev;}
    try{window.dispatchEvent(new CustomEvent('sbb:dev-mode',{detail:{enabled,reason:String(reason||'')}}));}catch(_){}
    return enabled;
  }
  function set(next,reason='manual'){return apply(!!next,reason);}
  function toggle(reason='manual'){return apply(!enabled,reason);}
  function isEnabled(){return !!enabled;}
  function resetForLoad(){return apply(explicit(),'page-load');}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',resetForLoad,{once:true});else resetForLoad();
  window.SBB_DEV_MODE=Object.freeze({version:'1.0',set,toggle,isEnabled,resetForLoad});
})();

/* v4.1.0 Game Center / Up Next / Settings information surface. No playback authority. */
(() => {
  const $=id=>document.getElementById(id);
  const desktopEmbedded=()=>!!window.matchMedia?.('(pointer:fine)').matches&&window.innerWidth>=1100;
  let activeTab='game-center',manuallyClosed=false;
  function surface(){return $('infoDrawer');}
  function selectTab(tab){
    activeTab=['up-next','settings'].includes(tab)?tab:'game-center';
    document.querySelectorAll('[data-drawer-tab]').forEach(btn=>{const on=btn.dataset.drawerTab===activeTab;btn.classList.toggle('active',on);btn.setAttribute('aria-selected',on?'true':'false');});
    document.querySelectorAll('[data-drawer-pane]').forEach(p=>p.classList.toggle('hidden',p.dataset.drawerPane!==activeTab));
    // Sticky video eligibility depends on the active information surface. Recompute
    // immediately so switching away from Game Center cannot leave a pinned player.
    window.SBB_VIEW_PREFS?.reset?.();
    window.SBB_VIEW_PREFS?.refresh?.();
  }
  function maybeScroll({automatic=false}={}){
    if(automatic||window.SBB_VIEW_PREFS?.sideActive)return;
    setTimeout(()=>surface()?.scrollIntoView({behavior:'smooth',block:'start'}),40);
  }
  function open(tab=activeTab,{automatic=false}={}){
    if(automatic&&manuallyClosed)return;
    selectTab(tab);const el=surface();if(!el)return;
    el.classList.remove('is-closed');el.classList.add('is-open');el.setAttribute('aria-hidden','false');document.body.classList.add('sbb-info-open');
    window.SBB_VIEW_PREFS?.reset?.();window.SBB_VIEW_PREFS?.refresh?.();window.dispatchEvent(new CustomEvent('sbb:drawer-state',{detail:{open:true,tab:activeTab}}));maybeScroll({automatic});
  }
  function close({manual=true}={}){
    // On PC this is a permanent embedded workspace, not an overlay/drawer. User
    // close gestures simply return it to Game Center. Programmatic close remains
    // available for the launch gate before playback begins.
    if(manual&&desktopEmbedded()){selectTab('game-center');return;}
    const el=surface();if(!el)return;el.classList.remove('is-open');el.classList.add('is-closed');el.setAttribute('aria-hidden','true');document.body.classList.remove('sbb-info-open');window.SBB_VIEW_PREFS?.reset?.();window.SBB_VIEW_PREFS?.refresh?.();window.dispatchEvent(new CustomEvent('sbb:drawer-state',{detail:{open:false,tab:activeTab}}));if(manual)manuallyClosed=true;
  }
  function resetAutomaticSuppression(){manuallyClosed=false;}
  function init(){
    $('gameCenterDrawerBtn')?.addEventListener('click',()=>{manuallyClosed=false;open('game-center');});
    $('upNextDrawerBtn')?.addEventListener('click',()=>{manuallyClosed=false;open('up-next');});
    $('settingsDrawerBtn')?.addEventListener('click',()=>{manuallyClosed=false;open('settings');});
    $('leftRailSettingsBtn')?.addEventListener('click',()=>{manuallyClosed=false;open('settings');});
    $('infoDrawerClose')?.addEventListener('click',()=>close({manual:true}));
    document.querySelectorAll('[data-drawer-tab]').forEach(btn=>btn.addEventListener('click',()=>selectTab(btn.dataset.drawerTab)));
    document.addEventListener('keydown',ev=>{if(ev.key==='Escape'&&surface()?.classList.contains('is-open'))close({manual:true});});
    window.SBB_SELECTED_EVENT?.subscribe?.((event,meta)=>{
      if(!event)return;
      if(meta?.source==='score-ribbon'||/score-card/i.test(String(meta?.reason||''))){resetAutomaticSuppression();open('game-center',{automatic:true});}
    });
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  window.SBB_INFO_DRAWER=Object.freeze({version:'1.1',open,close,selectTab,get activeTab(){return activeTab;},resetAutomaticSuppression});
})();

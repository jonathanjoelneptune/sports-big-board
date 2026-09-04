/* Sports Big Board v5.4.4 — explicit Game Center scroll owner.
   Moves the four existing provider-owned Game Center panes into one dedicated
   scroll surface. IDs and renderer ownership do not change. */
(() => {
  'use strict';
  if(window.SBB_GAME_CENTER_SCROLL?.version==='5.4.4')return;
  const VERSION='5.4.4';
  const $=id=>document.getElementById(id);
  const state={installed:false,moves:0,tabResets:0,lastError:''};

  function ensureScroller(){
    const content=$('gameCenterContent');
    if(!content)return null;
    let scroller=$('gcContentScroller');
    if(!scroller){
      scroller=document.createElement('div');
      scroller.id='gcContentScroller';
      scroller.className='gc-content-scroller';
      scroller.setAttribute('role','region');
      scroller.setAttribute('aria-label','Game Center details');
      const firstPane=content.querySelector(':scope > [data-gc-pane]');
      if(firstPane)content.insertBefore(scroller,firstPane); else content.appendChild(scroller);
    }
    const panes=[...content.querySelectorAll(':scope > [data-gc-pane]')];
    panes.forEach(pane=>{scroller.appendChild(pane);state.moves++;});
    state.installed=true;
    return scroller;
  }

  function resetScroll(){
    const scroller=ensureScroller();
    if(scroller){scroller.scrollTop=0;state.tabResets++;}
  }

  function bindTabs(){
    document.querySelectorAll('#gcSections [data-gc-section]').forEach(btn=>{
      if(btn.dataset.sbbScrollV5220==='1')return;
      btn.dataset.sbbScrollV5220='1';
      btn.addEventListener('click',()=>requestAnimationFrame(resetScroll));
    });
  }

  function repair(){
    try{ensureScroller();bindTabs();}
    catch(err){state.lastError=String(err?.message||err);}
  }

  function init(){
    repair();
    // Game Center is already rendered by app.js, but selection changes may rebuild
    // inner pane contents. Re-check structure only on selected-event changes.
    window.SBB_SELECTED_EVENT?.subscribe?.(()=>requestAnimationFrame(repair));
    window.addEventListener('resize',()=>requestAnimationFrame(ensureScroller),{passive:true});
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  window.SBB_GAME_CENTER_SCROLL=Object.freeze({version:VERSION,repair,resetScroll,snapshot:()=>({...state,scrollTop:$('gcContentScroller')?.scrollTop||0,scrollHeight:$('gcContentScroller')?.scrollHeight||0,clientHeight:$('gcContentScroller')?.clientHeight||0})});
})();

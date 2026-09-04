/* Sports Big Board v5.4.7 — Harmonized controls + collapsible drawer */
(() => {
  'use strict';
  if(window.SBB_DRAWER_POLISH?.version==='5.4.7') return;

  const VERSION='5.4.7';
  const STORAGE_KEY='sbb.drawer.collapsed.v1';
  const $=id=>document.getElementById(id);

  function setTransportLabels(){
    const prev=$('prevBtn');
    const next=$('nextBtn');
    if(prev && !prev.dataset.sbbPolishLabeled){
      prev.dataset.sbbPolishLabeled='1';
      prev.innerHTML='<span class="transport-label"><span class="chev" aria-hidden="true">‹</span><span>PREV</span></span>';
    }
    if(next && !next.dataset.sbbPolishLabeled){
      next.dataset.sbbPolishLabeled='1';
      next.innerHTML='<span class="transport-label"><span>NEXT</span><span class="chev" aria-hidden="true">›</span></span>';
    }
  }

  function ensureDrawerToggle(){
    const drawer=$('infoDrawer');
    if(!drawer) return null;
    let btn=$('drawerCollapseToggle');
    if(!btn){
      btn=document.createElement('button');
      btn.id='drawerCollapseToggle';
      btn.type='button';
      btn.setAttribute('aria-expanded','true');
      btn.setAttribute('aria-label','Collapse information drawer');
      btn.innerHTML='<span class="drawer-collapse-icon" aria-hidden="true">❯</span><span class="drawer-collapse-label sr-only">Collapse drawer</span>';
      drawer.insertAdjacentElement('afterbegin',btn);
    }
    return btn;
  }

  function setCollapsed(collapsed,{persist=true}={}){
    document.body.classList.toggle('sbb-drawer-collapsed',!!collapsed);
    document.documentElement.dataset.sbbDrawerCollapsed=collapsed?'1':'0';
    const btn=ensureDrawerToggle();
    if(btn){
      btn.setAttribute('aria-expanded', collapsed?'false':'true');
      btn.setAttribute('aria-label', collapsed?'Expand information drawer':'Collapse information drawer');
      btn.title=collapsed?'Expand drawer':'Collapse drawer';
      const icon=btn.querySelector('.drawer-collapse-icon');
      if(icon) icon.textContent=collapsed ? '❮' : '❯';
    }
    if(persist){
      try{ localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0'); }catch(_){ }
    }
  }

  function bindDrawerToggle(){
    const btn=ensureDrawerToggle();
    if(!btn || btn.dataset.sbbBound==='1') return;
    btn.dataset.sbbBound='1';
    btn.addEventListener('click',()=>setCollapsed(!document.body.classList.contains('sbb-drawer-collapsed')));
  }

  function hideRedundantUtilityControls(){
    document.querySelectorAll('.player-footer .utility-controls button').forEach(btn=>{
      btn.tabIndex=-1;
      btn.setAttribute('aria-hidden','true');
    });
  }

  function restoreState(){
    let collapsed=false;
    try{ collapsed=localStorage.getItem(STORAGE_KEY)==='1'; }catch(_){ }
    setCollapsed(collapsed,{persist:false});
  }

  function init(){
    setTransportLabels();
    bindDrawerToggle();
    hideRedundantUtilityControls();
    restoreState();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init,{once:true});
  else init();

  window.SBB_DRAWER_POLISH=Object.freeze({version:VERSION,setCollapsed,restoreState,setTransportLabels});
})();

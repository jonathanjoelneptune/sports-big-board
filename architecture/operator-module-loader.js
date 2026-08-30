/* Sports Big Board v4.7.6 — Operator Module Loader.
   Competition Builder editing, playlist-rule editing, durable association stats
   and special-event media audit are operator tools. They are not part of normal
   ribbon playback and therefore do not poll, observe, or hydrate until requested.
*/
(() => {
  'use strict';
  if(window.SBB_OPERATOR_MODULES?.version==='4.7.6')return;

  const VERSION='4.7.6';
  const scripts=[
    'architecture/competition-builder.js',
    'architecture/competition-builder-v4611.js',
    'architecture/competition-builder-v4612.js',
    'architecture/competition-builder-v4613.js',
    'architecture/special-event-media-v4616.js',
  ];
  const state={loading:false,loaded:false,promise:null,reason:'',loadedAt:0};

  const devEnabled=()=>!!window.SBB_DEV_MODE?.isEnabled?.();
  const visible=el=>!!el && !el.classList.contains('hidden') && getComputedStyle(el).display!=='none';

  function loadScript(path){
    return new Promise((resolve,reject)=>{
      const existing=[...document.scripts].find(s=>String(s.src||'').includes(path));
      if(existing){
        if(existing.dataset.sbbOperatorReady==='1')return resolve();
        existing.addEventListener('load',resolve,{once:true});
        existing.addEventListener('error',()=>reject(new Error(`Failed to load ${path}`)),{once:true});
        return;
      }
      const script=document.createElement('script');
      script.src=`${path}?v=${VERSION}`;
      script.async=false;
      script.dataset.sbbOperatorModule='1';
      script.addEventListener('load',()=>{script.dataset.sbbOperatorReady='1';resolve();},{once:true});
      script.addEventListener('error',()=>reject(new Error(`Failed to load ${path}`)),{once:true});
      document.body.appendChild(script);
    });
  }

  async function load(reason='operator'){
    if(state.loaded)return true;
    if(state.promise)return state.promise;
    state.loading=true;state.reason=String(reason||'operator');
    state.promise=(async()=>{
      for(const path of scripts)await loadScript(path);
      state.loaded=true;state.loading=false;state.loadedAt=Date.now();
      document.getElementById('sbbCompetitionBuilderLazyCard')?.remove();
      try{await window.SBB_FRONTEND_REGISTRY?.refresh?.({force:true});}catch(_){}
      try{window.dispatchEvent(new CustomEvent('sbb:operator-modules-ready',{detail:{reason:state.reason}}));}catch(_){}
      return true;
    })().catch(err=>{
      state.loading=false;state.promise=null;
      console.error('[SBB operator modules]',err);
      throw err;
    });
    return state.promise;
  }

  async function openBuilder(kind){
    await load(`builder-${kind}`);
    if(String(kind).toUpperCase()==='SPECIAL_EVENT')return window.SBB_COMPETITION_BUILDER?.openSpecialEvent?.();
    return window.SBB_COMPETITION_BUILDER?.openLeague?.();
  }

  function ensureLazyCard(){
    if(state.loaded)return true;
    if(document.getElementById('sbbCompetitionBuilderLazyCard'))return true;
    const anchor=document.querySelector('.milestone-launch-card')||document.querySelector('.settings-card:last-of-type');
    if(!anchor)return false;

    const card=document.createElement('div');
    card.id='sbbCompetitionBuilderLazyCard';
    card.className='settings-card sbb-builder-launch-card hidden';
    card.innerHTML=`<div class="settings-card-title">COMPETITION BUILDER</div>
      <div class="history-audit-launch-copy"><strong>Add data-driven leagues and special events</strong>
      <small>Operator modules load only when you use them, so normal Big Board playback stays light.</small></div>
      <div class="sbb-builder-launch-actions">
        <button id="sbbLazyAddLeagueBtn" class="settings-save-btn" type="button">ADD LEAGUE</button>
        <button id="sbbLazyAddSpecialEventBtn" class="settings-save-btn" type="button">ADD SPECIAL EVENT</button>
      </div>`;
    anchor.after(card);
    document.getElementById('sbbLazyAddLeagueBtn').onclick=()=>openBuilder('LEAGUE');
    document.getElementById('sbbLazyAddSpecialEventBtn').onclick=()=>openBuilder('SPECIAL_EVENT');
    const apply=()=>card.classList.toggle('hidden',!devEnabled());
    apply();
    window.addEventListener('sbb:dev-mode',apply);
    return true;
  }

  function historyAuditNeedsOperatorModules(){
    if(state.loaded||state.loading)return;
    const modal=document.getElementById('historyAuditModal');
    if(visible(modal))load('history-audit').catch(()=>{});
  }

  function boot(){
    ensureLazyCard();
    const cardTimer=setInterval(()=>{
      if(state.loaded){clearInterval(cardTimer);return;}
      ensureLazyCard();
    },1500);

    // Narrow visibility polling replaces several document-wide MutationObservers.
    const auditTimer=setInterval(historyAuditNeedsOperatorModules,1000);
    setTimeout(()=>{if(state.loaded)clearInterval(auditTimer);},60000);

    document.addEventListener('click',ev=>{
      const id=String(ev.target?.closest?.('[id]')?.id||'').toLowerCase();
      if(id.includes('history')&&id.includes('audit'))setTimeout(historyAuditNeedsOperatorModules,0);
    },true);
  }

  window.SBB_OPERATOR_MODULES=Object.freeze({
    version:VERSION,
    load,
    openLeague:()=>openBuilder('LEAGUE'),
    openSpecialEvent:()=>openBuilder('SPECIAL_EVENT'),
    snapshot:()=>({...state,scripts:[...scripts]})
  });

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();

/* Sports Big Board v4.6.13 — durable special-event association statistics.
   Existing Statistics can describe broad catalog availability. For custom special
   events, overwrite WITH MEDIA / NO MEDIA / ASSOCIATIONS with the durable
   EVENT_MEDIA relationships that the score ribbon can actually play.
*/
(() => {
  'use strict';
  if (window.SBB_COMPETITION_BUILDER_V4613) return;

  const $=id=>document.getElementById(id);
  const clean=v=>String(v??'').trim();
  const API=path=>window.SBB_API?.url?window.SBB_API.url(path):path;
  let catalogCache=null;
  let patching=false;
  let timer=null;

  async function getJson(path){
    const r=await fetch(API(path),{cache:'no-store'});
    const p=await r.json().catch(()=>({}));
    if(!r.ok||p?.ok===false)throw new Error(p?.message||p?.error||`HTTP ${r.status}`);
    return p;
  }

  async function specialEvents(force=false){
    if(catalogCache&&!force)return catalogCache;
    try{
      const p=await getJson('/api/competition-builder/catalog');
      catalogCache=(p.competitions||[]).filter(c=>clean(c.type).toUpperCase()==='SPECIAL_EVENT');
    }catch(_){catalogCache=[];}
    return catalogCache;
  }

  function pct(n,d){return Number(d||0)?`${((Number(n||0)/Number(d))*100).toFixed(1)}%`:'0.0%';}

  function rowForCompetition(id){
    const body=$('historyStatisticsBody');
    if(!body)return null;
    const target=clean(id).toUpperCase();
    return [...body.querySelectorAll('tr')].find(tr=>{
      const first=clean(tr.cells?.[0]?.textContent).toUpperCase();
      return first.includes(target);
    })||null;
  }

  function patchRow(tr,stats){
    const cells=tr?.cells;
    if(!cells||cells.length<13)return;
    const games=Number(stats.games||0);
    const withMedia=Number(stats.gamesWithPlayableAssociatedMedia||0);
    const missing=Number(stats.gamesWithoutPlayableAssociatedMedia||0);
    cells[3].innerHTML=`<strong>${withMedia.toLocaleString()}</strong><small>${pct(withMedia,games)} durable</small>`;
    cells[4].innerHTML=`<strong>${missing.toLocaleString()}</strong><small>${pct(missing,games)} missing</small>`;
    cells[5].textContent=Number(stats.best?.gold||0).toLocaleString();
    cells[6].textContent=Number(stats.best?.green||0).toLocaleString();
    cells[7].textContent=Number(stats.best?.extended||0).toLocaleString();
    cells[8].textContent=Number(stats.best?.blue||0).toLocaleString();
    cells[11].innerHTML=`<strong>${Number(stats.associatedAssets||0).toLocaleString()}</strong><small>${Number(stats.orphanedAssets||0).toLocaleString()} orphaned • durable EVENT_MEDIA</small>`;
    tr.dataset.v4613DurableAssociation='1';
  }

  async function patchStatistics(force=false){
    if(patching)return;
    const body=$('historyStatisticsBody');
    if(!body||body.closest('.history-audit-pane-hidden'))return;
    patching=true;
    try{
      const events=await specialEvents(force);
      await Promise.all(events.map(async comp=>{
        const tr=rowForCompetition(comp.id);
        if(!tr)return;
        try{
          const p=await getJson(`/api/competition-builder/media-association-stats?id=${encodeURIComponent(comp.id)}`);
          patchRow(tr,p.data||{});
        }catch(_){}
      }));
      const summary=$('historyStatisticsSummary');
      if(summary&&!summary.dataset.v4613Note){
        summary.dataset.v4613Note='1';
        summary.textContent+=` • Special-event WITH MEDIA uses durable playable game associations`;
      }
    }finally{patching=false;}
  }

  function schedulePatch(delay=80,force=false){
    clearTimeout(timer);
    timer=setTimeout(()=>patchStatistics(force),delay);
  }

  function install(){
    const body=$('historyStatisticsBody');
    if(body){
      new MutationObserver(()=>schedulePatch()).observe(body,{childList:true,subtree:true});
    }
    $('historyAuditTabStatistics')?.addEventListener('click',()=>schedulePatch(250,true));
    $('historyAuditRefresh')?.addEventListener('click',()=>schedulePatch(500,true));

    // Reprocess is async. Refresh durable association truth while the special
    // event crawler is working so the operator can watch orphan counts fall.
    document.addEventListener('click',ev=>{
      const button=ev.target?.closest?.('[data-v468-reprocess]');
      if(!button)return;
      const league=clean(button.dataset.v468Reprocess);
      if(!league)return;
      [1500,3500,7000,12000].forEach(ms=>setTimeout(()=>{
        catalogCache=null;
        patchStatistics(true);
        $('historyMediaSourcesRefresh')?.click();
      },ms));
    },true);

    const modal=$('historyAuditModal');
    if(modal){
      new MutationObserver(()=>{
        if(!modal.classList.contains('hidden'))schedulePatch(350,true);
      }).observe(modal,{attributes:true,attributeFilter:['class']});
    }
  }

  window.SBB_COMPETITION_BUILDER_V4613=Object.freeze({
    version:'4.6.13',
    refreshDurableAssociationStatistics:()=>patchStatistics(true)
  });

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});
  else install();
})();

/* Sports Big Board v4.6.16 — consolidated special-event media operator UI.
   REASSOCIATE is database-only. RECRAWL SOURCES is the only operation that revisits
   configured providers. ASSOCIATION AUDIT shows the exact stage/result for each asset.
*/
(()=>{
  'use strict';
  if(window.SBB_SPECIAL_EVENT_MEDIA_V4616)return;
  const clean=v=>String(v??'').trim();
  const API=path=>window.SBB_API?.url?window.SBB_API.url(path):path;
  const $=id=>document.getElementById(id);

  async function getJson(path){
    const r=await fetch(API(path),{cache:'no-store'});
    const p=await r.json().catch(()=>({}));
    if(!r.ok||p?.ok===false)throw new Error(p?.message||p?.error||`HTTP ${r.status}`);
    return p;
  }
  function escapeHtml(s){return clean(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function status(text){const el=$('historyMediaSourcesStatus')||$('historyStatisticsSummary');if(el)el.textContent=text;}

  function leagueFromButton(btn){
    return clean(btn?.dataset?.v468Reprocess||btn?.dataset?.sbbLeague||btn?.closest?.('[data-league]')?.dataset?.league).toUpperCase();
  }

  async function reassociate(league,button){
    if(!league)return;
    const old=button?.textContent;if(button){button.disabled=true;button.textContent='REASSOCIATING…';}
    try{
      const p=await getJson(`/api/competition-builder/reassociate-media?id=${encodeURIComponent(league)}`);
      const s=p?.data?.summary||p?.stats||{};
      status(`${league}: ${Number(s.persisted??s.associatedAssets??0)} persisted • ${Number(s.unmatched??s.orphanedAssets??0)} unmatched/orphaned`);
      window.SBB_COMPETITION_BUILDER_V4613?.refreshDurableAssociationStatistics?.();
      $('historyMediaSourcesRefresh')?.click();
    }catch(err){status(`${league} reassociation failed: ${err?.message||err}`);}
    finally{if(button){button.disabled=false;button.textContent=old||'REASSOCIATE';}}
  }

  async function recrawl(league,button){
    if(!league)return;
    const old=button?.textContent;if(button){button.disabled=true;button.textContent='RECRAWLING…';}
    try{
      const p=await getJson(`/api/competition-builder/recrawl-media?id=${encodeURIComponent(league)}`);
      const a=p?.data?.association||{};
      status(`${league}: source recrawl started • ${Number(a.persisted||0)} currently persisted`);
      [1200,3500,7000].forEach(ms=>setTimeout(()=>{
        window.SBB_COMPETITION_BUILDER_V4613?.refreshDurableAssociationStatistics?.();
        $('historyMediaSourcesRefresh')?.click();
      },ms));
    }catch(err){status(`${league} recrawl failed: ${err?.message||err}`);}
    finally{if(button){button.disabled=false;button.textContent=old||'RECRAWL SOURCES';}}
  }

  function ensureAuditModal(){
    if($('sbbSpecialEventAssociationAudit'))return $('sbbSpecialEventAssociationAudit');
    const modal=document.createElement('div');
    modal.id='sbbSpecialEventAssociationAudit';
    modal.className='hidden';
    modal.innerHTML=`
      <div class="sbb-v4616-audit-card">
        <div class="sbb-v4616-audit-head">
          <strong id="sbbV4616AuditTitle">ASSOCIATION AUDIT</strong>
          <button type="button" id="sbbV4616AuditClose">CLOSE</button>
        </div>
        <div id="sbbV4616AuditSummary"></div>
        <div class="sbb-v4616-audit-scroll">
          <table>
            <thead><tr><th>MEDIA</th><th>STAGE</th><th>CANDIDATES</th><th>GAME</th><th>METHOD</th><th>PLAYABLE</th><th>REASON</th></tr></thead>
            <tbody id="sbbV4616AuditBody"></tbody>
          </table>
        </div>
      </div>`;
    document.body.appendChild(modal);
    $('sbbV4616AuditClose')?.addEventListener('click',()=>modal.classList.add('hidden'));
    modal.addEventListener('click',ev=>{if(ev.target===modal)modal.classList.add('hidden');});
    return modal;
  }

  async function showAudit(league){
    const modal=ensureAuditModal();modal.classList.remove('hidden');
    $('sbbV4616AuditTitle').textContent=`${league} ASSOCIATION AUDIT`;
    $('sbbV4616AuditSummary').textContent='Loading association pipeline…';
    $('sbbV4616AuditBody').innerHTML='';
    try{
      const p=await getJson(`/api/competition-builder/media-association-audit?id=${encodeURIComponent(league)}`);
      const data=p?.data||{};const s=data.summary||{};
      $('sbbV4616AuditSummary').textContent=
        `${Number(s.sourceItems||0)} source • ${Number(s.persisted||0)} persisted • ${Number(s.playable||0)} playable • `+
        `${Number(s.unmatched||0)} unmatched • ${Number(s.ambiguous||0)} ambiguous • ${Number(s.eligibilityRejected||0)} rejected by source rules`;
      $('sbbV4616AuditBody').innerHTML=(data.assets||[]).map(a=>`
        <tr class="stage-${escapeHtml(a.stage||'').toLowerCase()}">
          <td><strong>${escapeHtml(a.title||a.mediaId)}</strong><small>${escapeHtml(a.mediaId)}</small></td>
          <td>${escapeHtml(a.stage)}</td>
          <td>${Number(a.candidateCount||0)}</td>
          <td>${escapeHtml(a.selectedGameNumber?`Game ${a.selectedGameNumber}`:a.selectedEventId||'—')}</td>
          <td>${escapeHtml(a.associationMethod||a.resolution||'—')}</td>
          <td>${a.playable?'YES':'NO'}</td>
          <td>${escapeHtml(a.reason||'')}</td>
        </tr>`).join('');
    }catch(err){$('sbbV4616AuditSummary').textContent=`Audit failed: ${err?.message||err}`;}
  }

  function enhanceButtons(){
    document.querySelectorAll('[data-v468-reprocess]').forEach(original=>{
      if(original.dataset.v4616Enhanced==='1')return;
      original.dataset.v4616Enhanced='1';
      const league=leagueFromButton(original);
      original.textContent='REASSOCIATE';
      original.title='Database-only reassociation; does not revisit providers';
      original.addEventListener('click',ev=>{
        ev.preventDefault();ev.stopImmediatePropagation();reassociate(league,original);
      },true);
      const recrawlBtn=document.createElement('button');
      recrawlBtn.type='button';recrawlBtn.className=original.className;recrawlBtn.textContent='RECRAWL SOURCES';
      recrawlBtn.dataset.sbbLeague=league;recrawlBtn.title='Revisit configured media sources, then reassociate';
      recrawlBtn.addEventListener('click',()=>recrawl(league,recrawlBtn));
      const audit=document.createElement('button');
      audit.type='button';audit.className=original.className;audit.textContent='ASSOCIATION AUDIT';
      audit.dataset.sbbLeague=league;audit.addEventListener('click',()=>showAudit(league));
      original.insertAdjacentElement('afterend',audit);
      original.insertAdjacentElement('afterend',recrawlBtn);
    });
  }

  function injectStyle(){
    if($('sbbV4616Style'))return;
    const style=document.createElement('style');style.id='sbbV4616Style';
    style.textContent=`
      #sbbSpecialEventAssociationAudit{position:fixed;inset:0;z-index:10050;background:rgba(0,0,0,.78);display:flex;align-items:center;justify-content:center;padding:24px}
      #sbbSpecialEventAssociationAudit.hidden{display:none}
      .sbb-v4616-audit-card{width:min(1500px,96vw);height:min(840px,92vh);background:#0b1117;border:1px solid #314150;border-radius:10px;display:flex;flex-direction:column;overflow:hidden}
      .sbb-v4616-audit-head{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid #28343e}
      #sbbV4616AuditSummary{padding:9px 14px;font-size:11px;color:#b9c6d2;border-bottom:1px solid #202b34}
      .sbb-v4616-audit-scroll{overflow:auto;flex:1}
      .sbb-v4616-audit-scroll table{width:100%;border-collapse:collapse;font-size:10px}
      .sbb-v4616-audit-scroll th,.sbb-v4616-audit-scroll td{padding:7px 8px;border-bottom:1px solid #1e2a33;text-align:left;vertical-align:top}
      .sbb-v4616-audit-scroll td:first-child{min-width:330px}.sbb-v4616-audit-scroll small{display:block;opacity:.55;margin-top:2px}
      .sbb-v4616-audit-scroll tr.stage-persisted td:nth-child(2){color:#7ce59a}
      .sbb-v4616-audit-scroll tr.stage-unmatched td:nth-child(2),.sbb-v4616-audit-scroll tr.stage-persistence_rejected td:nth-child(2){color:#f6c66c}
      .sbb-v4616-audit-scroll tr.stage-persistence_error td:nth-child(2){color:#ff7b72}
    `;
    document.head.appendChild(style);
  }

  function boot(){
    injectStyle();ensureAuditModal();enhanceButtons();
    new MutationObserver(enhanceButtons).observe(document.documentElement,{childList:true,subtree:true});
  }
  window.SBB_SPECIAL_EVENT_MEDIA_V4616=Object.freeze({version:'4.6.16',reassociate,recrawl,showAudit});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
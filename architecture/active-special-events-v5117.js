/* Sports Big Board v5.1.17 — active Special Events on the main sports row.
   A Special Event is promoted beside the normal sports while it is underway and
   for four calendar days after its configured end date. The event always remains
   available in the Special Events dropdown after the promotion expires. */
(() => {
  'use strict';
  if(window.SBB_ACTIVE_SPECIAL_EVENTS?.version==='5.1.17')return;
  const GRACE_DAYS=4;
  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const localISO=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
  const plusDays=(iso,n)=>{try{const [y,m,d]=iso.split('-').map(Number),x=new Date(y,m-1,d);x.setDate(x.getDate()+n);return `${x.getFullYear()}-${String(x.getMonth()+1).padStart(2,'0')}-${String(x.getDate()).padStart(2,'0')}`;}catch(_){return iso;}};
  const isSpecial=row=>upper(row?.type||row?.competitionType||row?.kind)==='SPECIAL_EVENT';
  function promoted(row,today=localISO()){
    if(!row||!isSpecial(row)||row.enabled===false)return false;
    const start=clean(row.startDate).slice(0,10),end=clean(row.endDate).slice(0,10);
    if(start&&today<start)return false;
    if(end&&today>plusDays(end,GRACE_DAYS))return false;
    return true;
  }
  function label(row){
    let text=clean(row.shortName||row.name||row.id);
    if(!text)return upper(row.id);
    // Main-row labels are intentionally compact. The full name remains in title.
    text=text.replace(/^20\d{2}\s+/,'').replace(/\s+20\d{2}$/,'');
    if(/us\s*open/i.test(text))return 'US OPEN';
    return text.length>13?text.slice(0,13).trim():text;
  }
  function injectStyle(){
    if(document.getElementById('sbbActiveSpecialV5117Style'))return;
    const s=document.createElement('style');s.id='sbbActiveSpecialV5117Style';
    s.textContent=`
      #scoreFilters>.sbb-special-active-row{display:inline-flex!important;align-items:center;justify-content:center;position:relative}
      #scoreFilters>.sbb-special-active-row.sbb-special-main-row-suppressed{display:inline-flex!important}
      #scoreFilters>.sbb-special-active-row::after{content:'';position:absolute;left:20%;right:20%;bottom:1px;height:1px;background:currentColor;opacity:.28}
      #scoreFilters>.sbb-special-active-row.active::after{opacity:.9}
    `;document.head.appendChild(s);
  }
  function rows(){
    try{return window.SBB_FRONTEND_REGISTRY?.snapshot?.().competitions||[];}catch(_){return [];}
  }
  function select(row){
    try{window.SBB_FRONTEND_REGISTRY?.select?.(row.id);return;}catch(_){}
  }
  function sync(){
    const host=document.getElementById('scoreFilters');if(!host)return;
    injectStyle();
    const today=localISO(),wanted=rows().filter(r=>promoted(r,today));
    const ids=new Set(wanted.map(r=>upper(r.id)));
    host.querySelectorAll('.sbb-special-active-row').forEach(btn=>{if(!ids.has(upper(btn.dataset.scoreFilter)))btn.remove();});
    for(const row of wanted){
      const id=upper(row.id);let btn=[...host.querySelectorAll('.sbb-special-active-row')].find(x=>upper(x.dataset.scoreFilter)===id);
      if(!btn){
        btn=document.createElement('button');btn.type='button';btn.className='sbb-special-active-row';btn.dataset.scoreFilter=id;btn.dataset.specialActive='1';
        btn.addEventListener('click',()=>select(row));
        host.appendChild(btn);
      }
      // Registry projection intentionally suppresses all Special Events from the
      // main row. v5.1.17 overrides that only for the active/grace lifecycle set.
      btn.classList.remove('sbb-special-main-row-suppressed');
      btn.textContent=label(row);btn.title=`${clean(row.name||id)} • active Special Event`;
      btn.classList.toggle('active',upper(window.scoreRibbonLeagueFilter||'')===id);
    }
  }
  function boot(){sync();setInterval(sync,2000);window.addEventListener('focus',sync);document.addEventListener('visibilitychange',()=>{if(!document.hidden)sync();});}
  window.SBB_ACTIVE_SPECIAL_EVENTS=Object.freeze({version:'5.1.17',graceDays:GRACE_DAYS,promoted,sync,snapshot:()=>({today:localISO(),promoted:rows().filter(r=>promoted(r)).map(r=>r.id)})});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();

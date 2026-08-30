/* Sports Big Board v4.7.14 — Navigation UI.
   Owns the themed score-date calendar and keeps all SPECIAL_EVENT competitions
   inside the Special Events dropdown instead of leaking event buttons into the
   permanent league row.
*/
(() => {
  'use strict';
  if(window.SBB_NAVIGATION_UI?.version==='4.7.14')return;

  const VERSION='4.7.14';
  const state={open:false,anchor:null,viewYear:0,viewMonth:0,selected:'',bound:false};
  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const pad=n=>String(n).padStart(2,'0');
  const localISO=d=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
  const parseISO=value=>{
    const m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(clean(value).slice(0,10));
    if(!m)return new Date();
    return new Date(Number(m[1]),Number(m[2])-1,Number(m[3]),12,0,0,0);
  };
  const today=()=>localISO(new Date());
  const browseDate=()=>{
    try{return clean(window.SBB_SCORE_DATE?.snapshot?.().browseDate||window.scoreBrowseDate||today()).slice(0,10)||today();}
    catch(_){return today();}
  };

  function strongSpecial(row){
    if(!row)return false;
    const id=upper(row.id);
    const explicit=upper(row.type||row.competitionType||row.kind||row.mode);
    // CFB is a normal first-class league. Explicit LEAGUE metadata must win over
    // the legacy eventIcon + bounded-dates heuristic used by Event Builder.
    if(id==='CFB'||explicit==='LEAGUE')return false;
    if(['SPECIAL_EVENT','SPECIAL EVENT','EVENT','TOURNAMENT'].includes(explicit))return true;
    if(row.specialEvent===true||row.isSpecialEvent===true)return true;
    // Event Builder gives special events a dedicated eventIcon. Use this only
    // when the competition did not explicitly declare itself as a league.
    if(clean(row.eventIcon)&&(clean(row.startDate)||clean(row.endDate)))return true;
    return false;
  }

  function injectStyle(){
    if(document.getElementById('sbbNavigationUiStyle'))return;
    const style=document.createElement('style');
    style.id='sbbNavigationUiStyle';
    style.textContent=`
      .score-date-picker{
        position:fixed!important;left:-9999px!important;top:-9999px!important;
        width:1px!important;height:1px!important;opacity:0!important;
        pointer-events:none!important;z-index:-1!important;
      }
      .sbb-date-popover{
        position:fixed;z-index:26000;width:318px;padding:12px;
        background:linear-gradient(180deg,#101821 0%,#091017 100%);
        border:1px solid #2b3a47;border-radius:12px;color:#eef6fb;
        box-shadow:0 22px 70px rgba(0,0,0,.62),0 0 0 1px rgba(59,166,219,.08);
        font-family:inherit;
      }
      .sbb-date-popover.hidden{display:none!important}
      .sbb-date-popover:before{
        content:"";position:absolute;top:-6px;left:var(--sbb-calendar-notch,28px);
        width:10px;height:10px;transform:rotate(45deg);
        background:#101821;border-left:1px solid #2b3a47;border-top:1px solid #2b3a47;
      }
      .sbb-calendar-head{display:grid;grid-template-columns:34px 1fr 34px;gap:6px;align-items:center;margin-bottom:9px}
      .sbb-calendar-head button,.sbb-calendar-footer button{
        border:1px solid #2c3b48;background:#111c25;color:#dceaf2;border-radius:7px;
        min-height:32px;padding:5px 8px;font-size:11px;font-weight:800
      }
      .sbb-calendar-head button:hover,.sbb-calendar-footer button:hover{background:#172735;border-color:#3b6178}
      .sbb-calendar-title{text-align:center;font-size:12px;font-weight:950;letter-spacing:.06em;color:#f5f9fc}
      .sbb-calendar-weekdays,.sbb-calendar-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:3px}
      .sbb-calendar-weekdays span{
        padding:3px 0;text-align:center;font-size:8px;font-weight:900;letter-spacing:.05em;color:#6f8594
      }
      .sbb-calendar-day{
        border:1px solid transparent;background:#0e171f;color:#d7e2e9;border-radius:7px;
        padding:0;min-height:34px;font-size:10px;font-weight:800
      }
      .sbb-calendar-day:hover{background:#172a36;border-color:#315267}
      .sbb-calendar-day.other{opacity:.38}
      .sbb-calendar-day.today{border-color:#3a8762;color:#9cf0bd;background:#0d2119}
      .sbb-calendar-day.selected{
        background:#173a4b;border-color:#55b9e5;color:#f5fcff;
        box-shadow:0 0 0 1px rgba(85,185,229,.22) inset
      }
      .sbb-calendar-footer{display:flex;justify-content:space-between;gap:7px;margin-top:9px;padding-top:9px;border-top:1px solid #1e2b35}
      .sbb-calendar-footer .sbb-calendar-today{color:#8fe7ad;border-color:#2f6e4b;background:#102219}
      .sbb-calendar-footer .sbb-calendar-close{color:#9eb0bc}
      #sbbSpecialEventsWrap{position:relative!important;display:inline-flex;align-items:center}
      #sbbSpecialEventsWrap.hidden{display:none!important}
      #sbbSpecialEventsMenu{
        position:fixed!important;z-index:25000!important;display:grid!important;gap:4px!important;
        padding:7px!important;background:#0d151c!important;border:1px solid #2b3945!important;
        border-radius:9px!important;box-shadow:0 20px 55px rgba(0,0,0,.58)!important;
        max-height:min(440px,70vh)!important;overflow:auto!important;
      }
      #sbbSpecialEventsMenu.hidden{display:none!important}
      #sbbSpecialEventsMenu button{
        width:100%!important;display:grid!important;grid-template-columns:auto minmax(0,1fr) auto!important;
        align-items:center!important;gap:8px!important;text-align:left!important;padding:8px 9px!important;
        border:1px solid transparent!important;background:#101a22!important;border-radius:7px!important;
      }
      #sbbSpecialEventsMenu button:hover{background:#162630!important;border-color:#304858!important}
      #sbbSpecialEventsMenu button.selected{background:#10251b!important;border-color:#2f7650!important}
      #sbbSpecialEventsMenu .sbb-special-event-icon{font-size:16px;line-height:1}
      #sbbSpecialEventsMenu .sbb-special-event-copy{display:grid;min-width:0}
      #sbbSpecialEventsMenu .sbb-special-event-copy strong{
        font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#eef6fb
      }
      #sbbSpecialEventsMenu .sbb-special-event-copy small{
        font-size:8px;color:#8395a2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis
      }
      #sbbSpecialEventsMenu .sbb-special-event-status{
        font-size:7px;font-weight:950;letter-spacing:.06em;color:#8c9aa5;border:1px solid #34424c;
        border-radius:999px;padding:3px 5px;white-space:nowrap
      }
      #sbbSpecialEventsMenu .sbb-special-event-status.active{color:#91ecaf;border-color:#34714d;background:#10241a}
      #scoreFilters>.sbb-special-main-row-suppressed{display:none!important}
    `;
    document.head.appendChild(style);
  }

  function ensureCalendar(){
    let pop=document.getElementById('sbbDatePopover');
    if(pop)return pop;
    pop=document.createElement('div');
    pop.id='sbbDatePopover';
    pop.className='sbb-date-popover hidden';
    pop.setAttribute('role','dialog');
    pop.setAttribute('aria-label','Choose score date');
    pop.innerHTML=`
      <div class="sbb-calendar-head">
        <button type="button" data-cal-step="-1" aria-label="Previous month">‹</button>
        <div class="sbb-calendar-title"></div>
        <button type="button" data-cal-step="1" aria-label="Next month">›</button>
      </div>
      <div class="sbb-calendar-weekdays" aria-hidden="true">
        <span>SUN</span><span>MON</span><span>TUE</span><span>WED</span><span>THU</span><span>FRI</span><span>SAT</span>
      </div>
      <div class="sbb-calendar-grid"></div>
      <div class="sbb-calendar-footer">
        <button type="button" class="sbb-calendar-today">TODAY</button>
        <button type="button" class="sbb-calendar-close">CLOSE</button>
      </div>`;
    document.body.appendChild(pop);
    pop.querySelector('[data-cal-step="-1"]').onclick=()=>stepMonth(-1);
    pop.querySelector('[data-cal-step="1"]').onclick=()=>stepMonth(1);
    pop.querySelector('.sbb-calendar-today').onclick=()=>selectDate(today(),{source:'calendar-today'});
    pop.querySelector('.sbb-calendar-close').onclick=close;
    return pop;
  }

  function stepMonth(delta){
    const d=new Date(state.viewYear,state.viewMonth+Number(delta||0),1,12);
    state.viewYear=d.getFullYear();state.viewMonth=d.getMonth();
    renderCalendar();
  }

  function position(anchor){
    const pop=ensureCalendar();
    if(!anchor)return;
    const r=anchor.getBoundingClientRect();
    const width=318,margin=8;
    let left=Math.max(margin,Math.min(innerWidth-width-margin,r.left));
    let top=r.bottom+7;
    if(top+390>innerHeight)top=Math.max(margin,r.top-390);
    pop.style.left=`${Math.round(left)}px`;
    pop.style.top=`${Math.round(top)}px`;
    pop.style.setProperty('--sbb-calendar-notch',`${Math.max(18,Math.min(width-30,r.left+r.width/2-left-5))}px`);
  }

  function renderCalendar(){
    const pop=ensureCalendar();
    const selected=state.selected||browseDate();
    const selectedDate=parseISO(selected);
    if(!state.viewYear){
      state.viewYear=selectedDate.getFullYear();
      state.viewMonth=selectedDate.getMonth();
    }
    const title=new Intl.DateTimeFormat(undefined,{month:'long',year:'numeric'})
      .format(new Date(state.viewYear,state.viewMonth,1));
    pop.querySelector('.sbb-calendar-title').textContent=title.toUpperCase();

    const first=new Date(state.viewYear,state.viewMonth,1,12);
    const start=new Date(state.viewYear,state.viewMonth,1-first.getDay(),12);
    const grid=pop.querySelector('.sbb-calendar-grid');
    const frag=document.createDocumentFragment();
    for(let i=0;i<42;i++){
      const d=new Date(start);d.setDate(start.getDate()+i);
      const iso=localISO(d);
      const b=document.createElement('button');
      b.type='button';b.className='sbb-calendar-day';
      if(d.getMonth()!==state.viewMonth)b.classList.add('other');
      if(iso===today())b.classList.add('today');
      if(iso===selected)b.classList.add('selected');
      b.textContent=String(d.getDate());
      b.dataset.date=iso;
      b.setAttribute('aria-label',new Intl.DateTimeFormat(undefined,{weekday:'long',month:'long',day:'numeric',year:'numeric'}).format(d));
      b.onclick=()=>selectDate(iso,{source:'calendar-day'});
      frag.appendChild(b);
    }
    grid.replaceChildren(frag);
  }

  function open(anchor=document.getElementById('topDateSelectBtn'),{date=''}={}){
    injectStyle();
    state.anchor=anchor;
    state.selected=clean(date||browseDate()).slice(0,10)||today();
    const d=parseISO(state.selected);
    state.viewYear=d.getFullYear();state.viewMonth=d.getMonth();
    renderCalendar();
    const pop=ensureCalendar();
    pop.classList.remove('hidden');
    position(anchor);
    state.open=true;
    return true;
  }

  function close(){
    document.getElementById('sbbDatePopover')?.classList.add('hidden');
    state.open=false;state.anchor=null;
  }

  async function selectDate(value,{source='calendar'}={}){
    const iso=clean(value).slice(0,10);
    if(!/^\d{4}-\d{2}-\d{2}$/.test(iso))return false;
    state.selected=iso;
    const input=document.getElementById('scoreDatePicker');
    if(input)input.value=iso;
    close();
    try{
      if(typeof window.setScoreBrowseDate==='function'){
        await Promise.resolve(window.setScoreBrowseDate(iso,{
          animate:true,hold:9000,load:true,source
        }));
      }
      return true;
    }catch(_){return false;}
  }

  function enforceSpecialEvents(){
    const snap=window.SBB_FRONTEND_REGISTRY?.snapshot?.();
    const rows=(snap?.competitions||[]).filter(strongSpecial);
    if(!rows.length)return;
    const ids=new Set(rows.map(row=>upper(row.id)).filter(Boolean));
    const host=document.getElementById('scoreFilters');
    const wrap=document.getElementById('sbbSpecialEventsWrap');
    const menu=document.getElementById('sbbSpecialEventsMenu');
    const btn=document.getElementById('sbbSpecialEventsBtn');
    if(!host||!wrap||!menu||!btn)return;

    // Any dynamic compatibility layer that tries to render a special event as a
    // permanent league chip is suppressed. The event exists only in this menu.
    [...host.children].forEach(child=>{
      const id=upper(child?.dataset?.scoreFilter);
      if(id&&ids.has(id))child.classList.add('sbb-special-main-row-suppressed');
    });

    wrap.classList.remove('hidden');
    btn.textContent='SPECIAL EVENTS ▾';

    const have=new Set([...menu.querySelectorAll('[data-special-competition]')]
      .map(x=>upper(x.dataset.specialCompetition)));
    if(rows.some(row=>!have.has(upper(row.id)))){
      menu.replaceChildren();
      const selected=upper(window.scoreRibbonLeagueFilter||'');
      const sorted=[...rows].sort((a,b)=>(clean(b.startDate)).localeCompare(clean(a.startDate)));
      for(const row of sorted){
        const item=document.createElement('button');
        item.type='button';item.dataset.specialCompetition=upper(row.id);
        item.setAttribute('role','menuitem');
        const status=(()=>{
          const d=browseDate(),start=clean(row.startDate).slice(0,10),end=clean(row.endDate).slice(0,10);
          if(start&&d<start)return 'UPCOMING';
          if(end&&d>end)return 'COMPLETED';
          return 'ACTIVE';
        })();
        item.classList.toggle('selected',upper(row.id)===selected);
        item.innerHTML=`<span class="sbb-special-event-icon" aria-hidden="true">${clean(row.eventIcon||row.icon||'🏆')}</span>
          <span class="sbb-special-event-copy"><strong></strong><small></small></span>
          <span class="sbb-special-event-status ${status==='ACTIVE'?'active':''}">${status}</span>`;
        item.querySelector('strong').textContent=clean(row.shortName||row.name||row.id);
        item.querySelector('small').textContent=clean(row.name||row.id);
        item.onclick=ev=>{
          ev.stopPropagation();
          window.SBB_FRONTEND_REGISTRY?.select?.(row.id);
          menu.classList.add('hidden');
          btn.setAttribute('aria-expanded','false');
        };
        menu.appendChild(item);
      }
    }
  }

  function bind(){
    if(state.bound)return;
    state.bound=true;
    injectStyle();ensureCalendar();

    // Capture before legacy handlers can invoke the browser-native date picker.
    document.addEventListener('click',ev=>{
      const dateAnchor=ev.target?.closest?.('#topDateSelectBtn,#scoreDayIndicator');
      if(dateAnchor){
        ev.preventDefault();ev.stopImmediatePropagation();
        state.open?close():open(dateAnchor);
        return;
      }
      if(state.open&&!ev.target?.closest?.('#sbbDatePopover'))close();
    },true);

    document.addEventListener('keydown',ev=>{if(ev.key==='Escape'&&state.open)close();});
    window.addEventListener('resize',()=>{if(state.open&&state.anchor)position(state.anchor);});
    window.addEventListener('scroll',()=>{if(state.open&&state.anchor)position(state.anchor);},true);

    const native=document.getElementById('scoreDatePicker');
    if(native){
      native.tabIndex=-1;
      native.setAttribute('aria-hidden','true');
    }

    enforceSpecialEvents();
    setInterval(enforceSpecialEvents,1500);
  }

  window.SBB_DATE_NAV_UI=Object.freeze({
    version:VERSION,open,close,selectDate,
    snapshot:()=>({
      version:VERSION,open:state.open,selected:state.selected,
      viewYear:state.viewYear,viewMonth:state.viewMonth
    })
  });
  window.SBB_NAVIGATION_UI=Object.freeze({
    version:VERSION,strongSpecial,enforceSpecialEvents
  });

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});
  else bind();
})();

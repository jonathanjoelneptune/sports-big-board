/* Sports Big Board v4.6.3 — Competition Builder Foundation.
   Data-driven League + Special Event UI over the canonical score/date/Game Center contracts. */
(() => {
  'use strict';
  if(window.SBB_COMPETITION_BUILDER)return;
  const state={competitions:[],map:{},loaded:new Map(),lastDate:'',lastCatalogAt:0,lastRevision:0,wizard:null};
  const $=id=>document.getElementById(id);
  const clean=v=>String(v??'').trim();
  const localISO=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
  const lifecycle=(c,today=localISO())=>c?.startDate&&today<c.startDate?'UPCOMING':(c?.endDate&&today>c.endDate?'COMPLETED':'ACTIVE');
  const mainRowEligible=c=>!!c?.enabled&&(String(c.type)==='LEAGUE'||(String(c.type)==='SPECIAL_EVENT'&&lifecycle(c)==='ACTIVE'));
  const competitionMap=()=>({...state.map});
  const sportLabel=id=>({baseball:'Baseball','american-football':'American Football',basketball:'Basketball','ice-hockey':'Ice Hockey',football:'Soccer',tennis:'Tennis',motorsport:'Motorsport',athletics:'Track & Field','action-sports':'Action Sports','multi-sport':'Sports'}[id]||id);

  function injectCss(){
    if($('sbbCompetitionBuilderStyle'))return;
    const style=document.createElement('style');style.id='sbbCompetitionBuilderStyle';style.textContent=`
      .sbb-special-wrap{position:relative;display:inline-flex}.sbb-special-wrap.hidden{display:none!important}.sbb-special-menu{position:absolute;z-index:90;top:calc(100% + 6px);left:0;min-width:260px;max-height:360px;overflow:auto;padding:8px;background:#111820;border:1px solid rgba(255,255,255,.16);border-radius:10px;box-shadow:0 14px 34px rgba(0,0,0,.45)}
      .sbb-special-menu.hidden{display:none}.sbb-special-menu button{display:flex!important;width:100%;justify-content:space-between;gap:14px;margin:2px 0!important}.sbb-special-menu small{opacity:.65}.sbb-special-menu button.selected{color:#dff8e8;border-color:#35694a!important;background:#101b15!important}.sbb-active-event-filter::after{content:'LIVE EVENT';font-size:8px;margin-left:5px;opacity:.65}
      .sbb-builder-launch-card.hidden{display:none}.sbb-builder-launch-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.sbb-builder-launch-actions button{flex:1;min-width:140px}.sbb-builder-competition-list{margin-top:10px;display:grid;gap:6px}.sbb-builder-competition-row{display:flex;justify-content:space-between;gap:10px;align-items:center;padding:7px 9px;border-radius:8px;background:rgba(255,255,255,.05)}.sbb-builder-row-actions{display:flex;gap:6px;align-items:center}.sbb-builder-competition-row button{min-width:0!important;flex:0 0 auto!important}.sbb-builder-competition-row small{opacity:.65}.sbb-builder-delete{border-color:rgba(255,90,90,.45)!important;color:#ff9b9b!important}.sbb-builder-delete.confirm{background:rgba(180,35,35,.28)!important;color:#fff!important}
      .sbb-builder-modal{position:fixed;z-index:10050;inset:0;background:rgba(0,0,0,.7);display:flex;align-items:center;justify-content:center;padding:24px}.sbb-builder-modal.hidden{display:none}
      .sbb-builder-shell{width:min(920px,96vw);max-height:90vh;overflow:auto;background:#121920;border:1px solid rgba(255,255,255,.18);border-radius:16px;padding:20px;box-shadow:0 30px 80px rgba(0,0,0,.6)}
      .sbb-builder-head{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}.sbb-builder-head h2{margin:2px 0}.sbb-builder-close{font-size:22px}.sbb-builder-steps{display:flex;gap:6px;margin:16px 0}.sbb-builder-step{flex:1;padding:8px;border-radius:8px;background:rgba(255,255,255,.06);text-align:center;font-size:11px}.sbb-builder-step.active{background:rgba(43,176,255,.2);outline:1px solid rgba(43,176,255,.45)}
      .sbb-builder-pane{display:none}.sbb-builder-pane.active{display:block}.sbb-builder-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.sbb-builder-grid label,.sbb-builder-field{display:flex;flex-direction:column;gap:5px}.sbb-builder-grid input,.sbb-builder-grid select,.sbb-builder-grid textarea,.sbb-builder-pane textarea{background:#0b1117;color:#fff;border:1px solid rgba(255,255,255,.16);border-radius:8px;padding:9px}
      .sbb-builder-grid textarea,.sbb-builder-pane textarea{min-height:105px;resize:vertical}.sbb-builder-wide{grid-column:1/-1}.sbb-builder-actions{display:flex;justify-content:space-between;gap:10px;margin-top:18px}.sbb-builder-actions .right{display:flex;gap:8px}.sbb-builder-actions .hidden{display:none!important}.sbb-builder-template-row{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 14px}.sbb-builder-status{padding:9px;border-radius:8px;background:rgba(255,255,255,.06);margin:10px 0;white-space:pre-wrap}.sbb-builder-review{font-family:ui-monospace,monospace;white-space:pre-wrap;background:#0b1117;padding:12px;border-radius:10px;max-height:360px;overflow:auto}
      @media(max-width:700px){.sbb-builder-grid{grid-template-columns:1fr}.sbb-builder-wide{grid-column:auto}}
    `;document.head.appendChild(style);
  }

  function normalizeMatch(c,e){
    const away=e.awayTeam||e.away||{},home=e.homeTeam||e.home||{};
    return {...e,__sbbLeague:c.id,__sbbDate:e.date,competitionId:c.id,competitionName:c.name,sportId:c.sportId,awayTeam:away,homeTeam:home,away,home,gameCenterProviderHint:'competition-builder'};
  }

  function ensureRuntimeCompetition(c){
    if(!mainRowEligible(c))return;
    try{if(Array.isArray(ENABLED_LIVE_LEAGUES)&&!ENABLED_LIVE_LEAGUES.includes(c.id))ENABLED_LIVE_LEAGUES.push(c.id);}catch(_){}
    try{
      if(typeof SPORT_FEEDS==='object'&&!SPORT_FEEDS[c.id])SPORT_FEEDS[c.id]={league:c.id,status:'ready',games:0,eligible:0,live:0,final:0,scheduled:0,highlights:0,calls:0,skippedHighlightCalls:0,error:'',lastChecked:Date.now(),nextRefreshMs:60000};
    }catch(_){}
  }

  async function loadCompetitionDate(c,date,{force=false}={}){
    date=clean(date).slice(0,10);if(!date)return [];
    const key=`${c.id}:${date}`,previous=state.loaded.get(key);
    if(!force&&previous&&Date.now()-previous<45000)return [];
    state.loaded.set(key,Date.now());
    const [r,mr]=await Promise.all([
      fetch(`/api/competition-builder/schedule?id=${encodeURIComponent(c.id)}&date=${encodeURIComponent(date)}`,{cache:'no-store'}),
      fetch(`/api/competition-builder/media?id=${encodeURIComponent(c.id)}&date=${encodeURIComponent(date)}`,{cache:'no-store'}).catch(()=>null)
    ]);
    if(!r.ok)return [];
    const p=await r.json(),rows=(p.events||[]).map(e=>normalizeMatch(c,e));
    try{SCORE_DATE_STORE?.setMatches?.(date,c.id,rows);}catch(_){}
    try{
      if(mr?.ok){const mp=await mr.json();SCORE_DATE_STORE?.setMedia?.(date,c.id,(mp.media||[]).map(x=>({...x,league:c.id,competitionId:c.id,competitionName:c.name,sport:x.sport||c.sportId,__sbbDate:x.__sbbDate||date})));}
    }catch(_){}
    try{
      if(typeof LIVE_MATCHES_BY_LEAGUE!=='undefined'){
        const today=localISO(),y=new Date();y.setDate(y.getDate()-1);const yesterday=`${y.getFullYear()}-${String(y.getMonth()+1).padStart(2,'0')}-${String(y.getDate()).padStart(2,'0')}`;
        const old=LIVE_MATCHES_BY_LEAGUE.get(c.id)||{yesterday:[],today:[]};
        if(date===today)old.today=rows;if(date===yesterday)old.yesterday=rows;LIVE_MATCHES_BY_LEAGUE.set(c.id,old);
      }
      if(typeof SPORT_FEEDS==='object'&&SPORT_FEEDS[c.id]){
        const final=rows.filter(x=>/final|complete|finished/i.test(clean(x.status))).length;
        const live=rows.filter(x=>/live|progress|inning|half|quarter|period/i.test(clean(x.status))).length;
        Object.assign(SPORT_FEEDS[c.id],{status:'ready',games:rows.length,eligible:rows.length,final,live,scheduled:Math.max(0,rows.length-final-live),lastChecked:Date.now()});
      }
    }catch(_){}
    return rows;
  }

  async function loadDate(date,{force=false}={}){
    date=clean(date||localISO()).slice(0,10);
    const jobs=state.competitions.filter(c=>!c.startDate||!c.endDate||(date>=c.startDate&&date<=c.endDate)).map(c=>loadCompetitionDate(c,date,{force}).catch(()=>[]));
    await Promise.all(jobs);
    try{if(typeof renderScoresFromMatchesCombined==='function')renderScoresFromMatchesCombined(false);}catch(_){}
    try{if(typeof updateScoreDayPager==='function')updateScoreDayPager();}catch(_){}
  }

  async function selectCompetition(id){
    id=clean(id).toUpperCase();
    const c=state.map[id]||null;
    let targetDate='';
    try{targetDate=clean(scoreBrowseDate||localISO()).slice(0,10);}catch(_){targetDate=localISO();}
    // A completed/upcoming special event should open on a meaningful event date,
    // not leave the user stranded on today's unrelated ribbon.
    if(c?.type==='SPECIAL_EVENT'){
      if(c.startDate&&targetDate<c.startDate)targetDate=c.startDate;
      if(c.endDate&&targetDate>c.endDate)targetDate=c.endDate;
    }
    try{scoreRibbonLeagueFilter=id;}catch(_){}
    const host=$('scoreFilters');
    host?.querySelectorAll('[data-score-filter]').forEach(b=>b.classList.toggle('active',clean(b.dataset.scoreFilter).toUpperCase()===id));
    const special=$('sbbSpecialEventsBtn');
    if(special){
      special.classList.toggle('active',c?.type==='SPECIAL_EVENT');
      special.setAttribute('aria-expanded','false');
    }
    $('sbbSpecialEventsMenu')?.querySelectorAll('[data-special-competition]').forEach(b=>b.classList.toggle('selected',clean(b.dataset.specialCompetition).toUpperCase()===id));
    try{scoreRibbonInteractionUntil=Date.now()+10000;}catch(_){}
    try{
      const current=clean(scoreBrowseDate||'').slice(0,10);
      if(targetDate&&targetDate!==current&&typeof setScoreBrowseDate==='function'){
        await setScoreBrowseDate(targetDate,{animate:true,hold:10000,load:false});
      }
    }catch(_){}
    await loadDate(targetDate||localISO(),{force:true});
    try{if(typeof renderScoresFromMatchesCombined==='function')renderScoresFromMatchesCombined(true);}catch(_){}
    try{if(typeof updateScoreDayPager==='function')updateScoreDayPager();}catch(_){}
  }

  function syncFilters(){
    const host=$('scoreFilters');if(!host)return;
    host.querySelectorAll('.sbb-dynamic-competition').forEach(x=>x.remove());

    const wrap=$('sbbSpecialEventsWrap');
    const btn=$('sbbSpecialEventsBtn');
    const menu=$('sbbSpecialEventsMenu');
    const specials=state.competitions
      .filter(c=>c.type==='SPECIAL_EVENT'&&c.enabled!==false)
      .sort((a,b)=>{
        const aa=lifecycle(a)==='ACTIVE'?0:(lifecycle(a)==='UPCOMING'?1:2);
        const bb=lifecycle(b)==='ACTIVE'?0:(lifecycle(b)==='UPCOMING'?1:2);
        return aa-bb||(b.startDate||'').localeCompare(a.startDate||'');
      });

    if(wrap&&btn&&menu){
      wrap.classList.toggle('hidden',specials.length===0);
      menu.innerHTML='';
      for(const c of specials){
        const x=document.createElement('button');
        x.type='button';x.dataset.specialCompetition=c.id;x.setAttribute('role','menuitem');
        x.innerHTML=`<span>${c.shortName||c.name}</span><small>${lifecycle(c)} • ${Number(c.eventsCount||0)} games</small>`;
        x.classList.toggle('selected',String(scoreRibbonLeagueFilter||'').toUpperCase()===c.id);
        x.addEventListener('click',async ev=>{
          ev.stopPropagation();menu.classList.add('hidden');btn.setAttribute('aria-expanded','false');
          await selectCompetition(c.id);
        });
        menu.appendChild(x);
      }
      if(!btn.dataset.sbbSpecialWired){
        btn.dataset.sbbSpecialWired='1';
        btn.addEventListener('click',ev=>{
          ev.stopPropagation();
          const opening=menu.classList.contains('hidden');
          menu.classList.toggle('hidden',!opening);
          btn.setAttribute('aria-expanded',opening?'true':'false');
        });
      }
    }

    let anchor=host.querySelector('[data-score-filter="MLS"]')||host.lastElementChild;
    for(const c of state.competitions.filter(mainRowEligible)){
      ensureRuntimeCompetition(c);
      const b=document.createElement('button');
      b.type='button';
      b.className=`sbb-dynamic-competition ${c.type==='SPECIAL_EVENT'?'sbb-active-event-filter':''}`;
      b.dataset.scoreFilter=c.id;b.textContent=c.shortName||c.id;b.title=c.name;
      anchor.after(b);anchor=b;
    }
  }

  async function deleteCompetition(c,button){
    if(!c?.id||!button)return;
    if(button.dataset.confirmDelete!=='1'){
      button.dataset.confirmDelete='1';button.textContent='CONFIRM DELETE';button.classList.add('confirm');
      setTimeout(()=>{if(button.isConnected&&button.dataset.confirmDelete==='1'){button.dataset.confirmDelete='';button.textContent='DELETE';button.classList.remove('confirm');}},6000);
      return;
    }
    button.disabled=true;button.textContent='DELETING…';
    try{
      const r=await fetch('/api/competition-builder',{method:'POST',headers:{'Content-Type':'application/json'},cache:'no-store',body:JSON.stringify({action:'delete',id:c.id,purge:true})});
      const p=await r.json();if(!r.ok||!p.ok)throw new Error(p.message||p.error||`HTTP ${r.status}`);
      try{if(String(scoreRibbonLeagueFilter||'').toUpperCase()===String(c.id).toUpperCase())scoreRibbonLeagueFilter='ALL';}catch(_){}
      await refreshCatalog({forceDate:true});
    }catch(err){
      button.disabled=false;button.dataset.confirmDelete='';button.classList.remove('confirm');button.textContent='DELETE';
      alert(`Delete failed: ${err.message}`);
    }
  }

  function renderCompetitionList(){
    const host=$('sbbCompetitionList');if(!host)return;
    if(!state.competitions.length){host.innerHTML='<small>No custom competitions have been created yet.</small>';return;}
    host.innerHTML='';
    for(const c of state.competitions){
      const row=document.createElement('div');row.className='sbb-builder-competition-row';
      row.innerHTML=`<div><strong>${c.shortName||c.name}</strong><br><small>${c.type} • ${c.lifecycle||lifecycle(c)} • ${Number(c.eventsCount||0)} events • SERVER PERSISTED</small></div>`;
      const actions=document.createElement('div');actions.className='sbb-builder-row-actions';
      const view=document.createElement('button');view.type='button';view.textContent='VIEW';view.onclick=()=>selectCompetition(c.id);
      const del=document.createElement('button');del.type='button';del.className='sbb-builder-delete';del.textContent='DELETE';del.onclick=()=>deleteCompetition(c,del);
      actions.append(view,del);row.appendChild(actions);host.appendChild(row);
    }
  }

  async function refreshCatalog({forceDate=false}={}){
    const r=await fetch(`/api/competition-builder/catalog?_=${Date.now()}`,{cache:'no-store'});if(!r.ok)return;
    const p=await r.json();state.competitions=p.competitions||[];state.map=Object.fromEntries(state.competitions.map(c=>[c.id,c]));state.lastCatalogAt=Date.now();state.lastRevision=Number(p.revision||0);
    syncFilters();renderCompetitionList();await loadDate(typeof scoreBrowseDate!=='undefined'?scoreBrowseDate:localISO(),{force:forceDate});
  }

  function wizardMarkup(type){
    return `<div id="sbbBuilderModal" class="sbb-builder-modal"><section class="sbb-builder-shell">
      <div class="sbb-builder-head"><div><small>DEV MODE • COMPETITION BUILDER</small><h2>${type==='SPECIAL_EVENT'?'ADD SPECIAL EVENT':'ADD LEAGUE'}</h2><p>Create a persistent competition, schedule/results feed, media anchors and generic Game Center.</p></div><button id="sbbBuilderClose" class="sbb-builder-close" type="button">×</button></div>
      <div class="sbb-builder-template-row"><button type="button" data-builder-template="WORLD_CUP">2026 WORLD CUP TEMPLATE</button><button type="button" data-builder-template="LLWS">2026 LLWS TEMPLATE</button></div>
      <div class="sbb-builder-steps">${['IDENTITY','SCHEDULE','MEDIA','REVIEW'].map((x,i)=>`<div class="sbb-builder-step ${i===0?'active':''}" data-step-label="${i}">${i+1}. ${x}</div>`).join('')}</div>
      <div class="sbb-builder-status" id="sbbBuilderStatus">Draft not saved.</div>
      <div class="sbb-builder-pane active" data-step="0"><div class="sbb-builder-grid">
        <label>ID<input id="cbId" placeholder="WC2026"></label><label>NAME<input id="cbName" placeholder="2026 FIFA World Cup"></label>
        <label>SHORT LABEL<input id="cbShort" placeholder="WORLD CUP"></label><label>SPORT<select id="cbSport"><option value="football">Soccer</option><option value="baseball">Baseball</option><option value="american-football">American Football</option><option value="basketball">Basketball</option><option value="ice-hockey">Ice Hockey</option><option value="tennis">Tennis</option><option value="motorsport">Motorsport</option><option value="multi-sport">Multi-sport</option></select></label>
        <label>START DATE<input id="cbStart" type="date"></label><label>END DATE<input id="cbEnd" type="date"></label>
        <label>FORMAT<select id="cbFormat"><option>GROUP + KNOCKOUT</option><option>DOUBLE ELIMINATION</option><option>KNOCKOUT</option><option>ROUND ROBIN</option><option>SEASON</option><option>CUSTOM</option></select></label><label>TYPE<input value="${type}" disabled></label>
      </div></div>
      <div class="sbb-builder-pane" data-step="1"><div class="sbb-builder-grid">
        <label>SCHEDULE MODE<select id="cbScheduleMode"><option value="AUTO_DISCOVER">OPENAI AUTO DISCOVER</option><option value="PASTE">PASTE JSON / CSV</option></select></label>
        <label>OFFICIAL SCHEDULE / SCORE URL<input id="cbScheduleUrl" placeholder="https://official-event-site/..."></label>
        <label>AUTO REFRESH WHILE ACTIVE<select id="cbAutoRefresh"><option value="1">YES</option><option value="0">NO</option></select></label>
        <label>REFRESH MINUTES<input id="cbRefreshMinutes" type="number" min="5" value="30"></label>
        <label>EXPECTED EVENT COUNT<input id="cbExpectedEvents" type="number" min="0" placeholder="Optional completeness target"></label>
        <div class="sbb-builder-field"><small>If known, this prevents a partial schedule from being activated. World Cup = 104; LLWS = 38.</small></div>
        <div class="sbb-builder-wide"><button id="cbDiscover" type="button">DISCOVER SCHEDULE WITH OPENAI</button></div>
        <label class="sbb-builder-wide">SCHEDULE PREVIEW / PASTE<textarea id="cbScheduleText" placeholder='[{"date":"2026-06-11","away":"Mexico","home":"South Africa","status":"FINAL"}]'></textarea></label>
      </div></div>
      <div class="sbb-builder-pane" data-step="2"><div class="sbb-builder-grid">
        <label class="sbb-builder-wide">GREEN / QUICK PLAYLISTS<textarea id="cbGreen" placeholder="One YouTube playlist URL per line"></textarea></label>
        <label class="sbb-builder-wide">PURPLE / EXTENDED PLAYLISTS<textarea id="cbPurple" placeholder="One YouTube playlist URL per line"></textarea></label>
        <label class="sbb-builder-wide">BLUE / MOMENTS PLAYLISTS (OPTIONAL)<textarea id="cbBlue" placeholder="One YouTube playlist URL per line"></textarea></label>
      </div></div>
      <div class="sbb-builder-pane" data-step="3"><div id="cbReview" class="sbb-builder-review"></div></div>
      <div class="sbb-builder-actions"><button id="cbBack" type="button" disabled>← BACK</button><div class="right"><button id="cbNext" type="button">NEXT →</button><button id="cbSave" type="button" class="hidden">CREATE SITE-WIDE</button></div></div>
    </section></div>`;
  }

  function draft(type){
    const lines=id=>clean($(id)?.value).split(/\n+/).map(x=>x.trim()).filter(Boolean);
    return {id:clean($('cbId')?.value).toUpperCase(),name:clean($('cbName')?.value),shortName:clean($('cbShort')?.value),type,sportId:clean($('cbSport')?.value),startDate:clean($('cbStart')?.value),endDate:clean($('cbEnd')?.value),format:clean($('cbFormat')?.value),scheduleMode:clean($('cbScheduleMode')?.value),scheduleSourceUrl:clean($('cbScheduleUrl')?.value),scoreSourceUrl:clean($('cbScheduleUrl')?.value),autoRefresh:$('cbAutoRefresh')?.value==='1',backgroundDiscovery:true,refreshMinutes:Number($('cbRefreshMinutes')?.value||30),expectedEventCount:Number($('cbExpectedEvents')?.value||0),allowIncompleteSchedule:false,enabled:true,mediaSources:{green:lines('cbGreen'),purple:lines('cbPurple'),blue:lines('cbBlue')}};
  }

  function scheduleCountFromText(){
    const text=clean($('cbScheduleText')?.value);if(!text)return 0;
    try{const x=JSON.parse(text);return Array.isArray(x)?x.length:Number((x.events||x.games||x.matches||[]).length||0);}catch(_){
      const lines=text.split(/\r?\n/).filter(x=>x.trim());return Math.max(0,lines.length-1);
    }
  }

  function updateReview(type){
    const d=draft(type),count=scheduleCountFromText(),expected=Number(d.expectedEventCount||0),complete=count>0&&(!expected||count>=expected);
    $('cbReview').textContent=JSON.stringify({...d,lifecycle:lifecycle(d),mainRow:mainRowEligible(d),scheduleEvents:count,expectedEvents:expected||'not specified',scheduleComplete:complete,uiPlacement:d.type==='SPECIAL_EVENT'?(lifecycle(d)==='ACTIVE'?'SPECIAL EVENTS + MAIN LEAGUE ROW':'SPECIAL EVENTS ONLY'):'MAIN LEAGUE ROW'},null,2);
    if($('cbSave')){$('cbSave').disabled=!complete;$('cbSave').title=complete?'Create this competition site-wide':'A non-empty complete schedule is required before creation';}
  }

  function setWizardStep(n,type){
    n=Math.max(0,Math.min(3,n));state.wizard.step=n;
    document.querySelectorAll('.sbb-builder-pane').forEach(x=>x.classList.toggle('active',Number(x.dataset.step)===n));document.querySelectorAll('.sbb-builder-step').forEach(x=>x.classList.toggle('active',Number(x.dataset.stepLabel)===n));
    $('cbBack').disabled=n===0;$('cbNext').classList.toggle('hidden',n===3);$('cbSave').classList.toggle('hidden',n!==3);
    if(n===3){updateReview(type);if($('cbSave').disabled)$('sbbBuilderStatus').textContent='Schedule is not complete yet. Return to Schedule and discover/paste the full event list before site-wide creation.';}
  }

  function applyTemplate(kind,type){
    if(kind==='WORLD_CUP'){
      $('cbId').value='WC2026';$('cbName').value='2026 FIFA World Cup';$('cbShort').value='WORLD CUP';$('cbSport').value='football';$('cbStart').value='2026-06-11';$('cbEnd').value='2026-07-19';$('cbFormat').value='GROUP + KNOCKOUT';$('cbExpectedEvents').value='104';$('cbScheduleUrl').value='https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/match-schedule-fixtures-results-teams-stadiums';
    }else{
      $('cbId').value='LLWS2026';$('cbName').value='2026 Little League Baseball World Series';$('cbShort').value='LLWS';$('cbSport').value='baseball';$('cbStart').value='2026-08-19';$('cbEnd').value='2026-08-30';$('cbFormat').value='DOUBLE ELIMINATION';$('cbExpectedEvents').value='38';$('cbScheduleUrl').value='https://www.littleleague.org/world-series/2026/llbws/tournaments/world-series/';
    }
    $('sbbBuilderStatus').textContent='Template loaded. Review identity, then discover/import the schedule before saving.';
  }

  async function openWizard(type){
    document.getElementById('sbbBuilderModal')?.remove();document.body.insertAdjacentHTML('beforeend',wizardMarkup(type));state.wizard={type,step:0,events:[],saved:false};
    const modal=$('sbbBuilderModal');
    // Editable wizard controls keep their keystrokes. Stop bubbling only after the
    // input receives the key so the board's document-level Space/Arrow/F shortcuts
    // cannot pause playback or change programs while the operator is typing.
    modal?.addEventListener('keydown',ev=>{const t=ev.target;if(t?.matches?.('input,textarea,select')||t?.isContentEditable)ev.stopPropagation();});
    modal?.addEventListener('keyup',ev=>{const t=ev.target;if(t?.matches?.('input,textarea,select')||t?.isContentEditable)ev.stopPropagation();});
    $('sbbBuilderClose').onclick=()=>$('sbbBuilderModal').remove();document.querySelectorAll('[data-builder-template]').forEach(b=>b.onclick=()=>applyTemplate(b.dataset.builderTemplate,type));
    $('cbScheduleText')?.addEventListener('input',()=>{state.wizard.events=[];state.wizard.scheduleComplete=false;if(state.wizard.step===3)updateReview(type);});
    $('cbBack').onclick=()=>setWizardStep(state.wizard.step-1,type);$('cbNext').onclick=()=>setWizardStep(state.wizard.step+1,type);
    $('cbDiscover').onclick=async()=>{
      const st=$('sbbBuilderStatus');st.textContent='OpenAI is researching the schedule in bounded date windows and checking completeness… Large tournaments can take a minute or two.';$('cbDiscover').disabled=true;
      try{
        const r=await fetch('/api/competition-builder',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'discover',competition:draft(type)})});
        const p=await r.json();if(!r.ok||!p.ok)throw new Error(p.message||p.error||`HTTP ${r.status}`);
        state.wizard.events=p.preview?.events||[];state.wizard.scheduleComplete=p.preview?.complete!==false;$('cbScheduleText').value=JSON.stringify(state.wizard.events,null,2);
        if(Number(p.preview?.expectedEventCount||0)>0)$('cbExpectedEvents').value=String(p.preview.expectedEventCount);
        if(p.preview?.sourceUrls?.[0]&&!$('cbScheduleUrl').value)$('cbScheduleUrl').value=p.preview.sourceUrls[0];
        const found=Number(p.preview?.discoveredEventCount??state.wizard.events.length),expected=Number(p.preview?.expectedEventCount||0),complete=p.preview?.complete!==false;
        const windows=(p.preview?.windowReports||[]).map(x=>`${x.start}..${x.end}: ${x.events} (${x.mode})`).join(' • ');
        st.textContent=`${complete?'SCHEDULE COMPLETE ✓':'PARTIAL SCHEDULE — NOT READY TO CREATE'}\nDiscovered ${found}${expected?` / ${expected}`:''} events using ${p.preview?.discoveryMode||'schedule discovery'}.\nSources: ${(p.preview?.sourceUrls||[]).join(', ')||'see discovered event source URLs'}${windows?`\nWindows: ${windows}`:''}${(p.preview?.attemptErrors||[]).length?`\nRecovery notes: ${(p.preview.attemptErrors||[]).slice(-5).join(' | ')}`:''}`;
      }catch(err){st.textContent=`Discovery failed: ${err.message}\nYou can still paste JSON/CSV below. The wizard will stay open until the server confirms a successful create.`;}finally{$('cbDiscover').disabled=false;}
    };
    $('cbSave').onclick=async()=>{
      if(state.wizard?.saved){$('sbbBuilderModal')?.remove();return;}
      const st=$('sbbBuilderStatus');st.textContent='Creating competition on the server, persisting it, and enrolling media crawl…';$('cbSave').disabled=true;
      try{
        const d=draft(type),scheduleText=clean($('cbScheduleText').value),count=scheduleCountFromText(),expected=Number(d.expectedEventCount||0);
        if(!count)throw new Error('A schedule is required. Discover or paste at least one event before creation.');
        if(expected&&count<expected)throw new Error(`Schedule is incomplete: ${count}/${expected} events.`);
        const r=await fetch('/api/competition-builder',{method:'POST',headers:{'Content-Type':'application/json'},cache:'no-store',body:JSON.stringify({action:'save',competition:d,scheduleText})});
        const p=await r.json();if(!r.ok||!p.ok||!p.persisted)throw new Error(p.message||p.error||`HTTP ${r.status}`);
        const vr=await fetch(`/api/competition-builder/definition?id=${encodeURIComponent(d.id)}&_=${Date.now()}`,{cache:'no-store'});
        const vp=await vr.json();
        if(!vr.ok||!vp.persisted||clean(vp.competition?.id).toUpperCase()!==clean(d.id).toUpperCase())throw new Error('Server read-back verification failed; competition was not confirmed persistent.');
        await refreshCatalog({forceDate:true});
        const ce=vp.crawlEnrollment||p.crawlEnrollment||{},playlistCount=(ce.operatorPlaylists||[]).length;
        state.wizard.saved=true;$('cbSave').disabled=false;$('cbSave').textContent='DONE';$('cbBack').disabled=true;$('cbNext').classList.add('hidden');
        const placement=p.competition.type==='SPECIAL_EVENT'?(p.competition.lifecycle==='ACTIVE'?'Special Events + main selector row':'Special Events dropdown'):'main selector row';
        st.textContent=`CREATED SITE-WIDE ✓\n${p.competition.name} • ${p.competition.eventsCount} events • ${p.competition.lifecycle}\nVisible in: ${placement}\nServer persistence verified • revision ${vp.revision||p.revision||'—'}\nMedia crawl: ${ce.historyLeague?'ENROLLED':'PENDING'} • ${playlistCount} operator playlist${playlistCount===1?'':'s'} • background search ${ce.backgroundDiscovery?'ON':'OFF'}\nOther browsers will pick this up automatically.`;
      }catch(err){st.textContent=`CREATE FAILED — NO VERIFIED SITE-WIDE COMMIT\n${err.message}\nThe wizard is staying open so you can correct the problem or retry.`;$('cbSave').disabled=false;}
    };
  }

  function installDevLaunchers(){
    if($('sbbCompetitionBuilderCard'))return;
    const anchor=document.querySelector('.milestone-launch-card')||document.querySelector('.settings-card:last-of-type');if(!anchor)return;
    const card=document.createElement('div');card.id='sbbCompetitionBuilderCard';card.className='settings-card sbb-builder-launch-card hidden';card.innerHTML=`<div class="settings-card-title">COMPETITION BUILDER</div><div class="history-audit-launch-copy"><strong>Add data-driven leagues and special events</strong><small>Server-persistent schedules, score ribbon, Game Center, media playlists and background search crawl. Changes are site-wide across browsers.</small></div><div class="sbb-builder-launch-actions"><button id="sbbAddLeagueBtn" class="settings-save-btn" type="button">ADD LEAGUE</button><button id="sbbAddSpecialEventBtn" class="settings-save-btn" type="button">ADD SPECIAL EVENT</button></div><div id="sbbCompetitionList" class="sbb-builder-competition-list"><small>Loading server competition catalog…</small></div>`;
    anchor.after(card);$('sbbAddLeagueBtn').onclick=()=>openWizard('LEAGUE');$('sbbAddSpecialEventBtn').onclick=()=>openWizard('SPECIAL_EVENT');
    const apply=()=>card.classList.toggle('hidden',!window.SBB_DEV_MODE?.isEnabled?.());apply();window.addEventListener('sbb:dev-mode',apply);
  }

  async function start(){
    injectCss();installDevLaunchers();await refreshCatalog({forceDate:true});
    let previous='';
    // Directly follow the canonical score-date authority. This makes custom
    // competition events first-class score-ribbon data rather than relying only
    // on polling a global browse-date variable.
    try{
      window.SBB_SCORE_DATE?.subscribe?.((snap,meta)=>{
        if(meta?.action==='browse'&&snap?.browseDate){
          previous=snap.browseDate;
          loadDate(snap.browseDate,{force:true}).catch(()=>{});
        }
      },{emitCurrent:true});
    }catch(_){}
    setInterval(()=>{
      let d=localISO();try{d=clean(scoreBrowseDate||d).slice(0,10);}catch(_){}
      if(d!==previous){previous=d;loadDate(d,{force:true});}
      // Reconcile the currently viewed custom-event date periodically so a
      // normal built-in score refresh cannot leave a custom ribbon stale.
      if(state.competitions.some(c=>(!c.startDate||d>=c.startDate)&&(!c.endDate||d<=c.endDate))){
        loadDate(d,{force:false}).catch(()=>{});
      }
      if(Date.now()-state.lastCatalogAt>5000)refreshCatalog();
    },1000);
    window.addEventListener('focus',()=>refreshCatalog({forceDate:true}));
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshCatalog({forceDate:true});});
    document.addEventListener('click',e=>{
      if(!e.target.closest('.sbb-special-wrap')){
        $('sbbSpecialEventsMenu')?.classList.add('hidden');
        $('sbbSpecialEventsBtn')?.setAttribute('aria-expanded','false');
      }
    });
  }

  window.SBB_COMPETITION_BUILDER=Object.freeze({version:'1.3',refresh:refreshCatalog,loadDate,competitionMap,lifecycle,mainRowEligible,openLeague:()=>openWizard('LEAGUE'),openSpecialEvent:()=>openWizard('SPECIAL_EVENT'),snapshot:()=>({competitions:state.competitions.length,specialEvents:state.competitions.filter(x=>x.type==='SPECIAL_EVENT').length,mainRow:state.competitions.filter(mainRowEligible).map(x=>x.id),lastDate:state.lastDate})});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();

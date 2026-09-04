/* Sports Big Board v5.4.2 — resilient sport Match Center fallback.
   Provider-rich Game Center remains preferred. When a competition has no detailed
   provider or a provider request fails, keep the selected sporting event useful:
   show participants, score/status and event context instead of GAME CENTER UNAVAILABLE.
   Special Events retain their stronger curated Match Center ownership. */
(() => {
  'use strict';
  if(window.SBB_SPORT_MATCH_CENTER?.version==='5.4.2')return;
  const VERSION='5.4.2';
  const $=id=>document.getElementById(id);
  const clean=v=>String(v??'').trim();
  const esc=v=>clean(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state={active:false,lastKey:'',activations:0,lastReason:'',applying:false,observer:null};

  function participants(evt={}){
    const list=Array.isArray(evt.participants)?evt.participants:[];
    const away=evt.awayTeam||evt.away||list.find(x=>x?.side==='away')||list[0]||{};
    const home=evt.homeTeam||evt.home||list.find(x=>x?.side==='home')||list[1]||{};
    return {away,home};
  }
  const partName=p=>clean(p?.displayName||p?.name||p?.shortName||p?.abbreviation||p?.playerName)||'—';
  const partCode=p=>clean(p?.abbreviation||p?.shortName||p?.countryCode||p?.country?.code).toUpperCase().slice(0,4);
  const partImage=p=>clean(p?.logo||p?.logoUrl||p?.image||p?.imageUrl||p?.flag||p?.flagUrl||p?.country?.flag||p?.country?.flagUrl);
  function flagEmoji(p){
    const code=clean(p?.countryCode||p?.country?.code||p?.country?.abbreviation).toUpperCase();
    if(!/^[A-Z]{2}$/.test(code))return '';
    return String.fromCodePoint(...[...code].map(ch=>127397+ch.charCodeAt(0)));
  }
  function score(evt,side){
    return evt?.[`${side}Score`]??evt?.score?.[`${side}Score`]??evt?.[side]?.score??'';
  }
  function competition(evt={}){
    return clean(evt.competitionName||evt.tournamentName||evt.eventName||evt.competitionId||evt.__sbbLeague||evt.league||'SPORT MATCH');
  }
  function eventKey(evt={}){
    try{return clean(window.SBB_EVENT_IDENTITY?.key?.(evt));}catch(_){}
    return [competition(evt),evt.eventId||evt.matchId||evt.gamePk||'',evt.date||evt.scheduledAt||'',partName(participants(evt).away),partName(participants(evt).home)].join(':');
  }
  function activeEvent(){
    try{const selected=window.SBB_SELECTED_EVENT?.get?.();if(selected)return selected;}catch(_){}
    try{const selected=window.SBB_GAME_CENTER_VIEW?.selected;if(selected)return selected;}catch(_){}
    try{if(typeof clip==='function'&&typeof currentIndex!=='undefined')return clip(currentIndex)||null;}catch(_){}
    return null;
  }
  function providerSupported(evt){
    try{if(typeof gameCenterCompetitionSupported==='function')return !!gameCenterCompetitionSupported(evt);}catch(_){}
    return true;
  }
  function usefulEvent(evt){
    const {away,home}=participants(evt||{});
    return partName(away)!=='—'&&partName(home)!=='—';
  }
  function ensureHost(){
    let host=$('sbbSportMatchCenter');if(host)return host;
    const pane=$('gameCenterPane');if(!pane)return null;
    host=document.createElement('div');host.id='sbbSportMatchCenter';host.className='sbb-sport-match-center';host.setAttribute('aria-live','polite');
    pane.appendChild(host);return host;
  }
  function participantMarkup(side,p,value){
    const src=partImage(p),flag=flagEmoji(p),code=partCode(p);
    return `<div class="sbb-smc-team sbb-smc-${side}">
      <span class="sbb-smc-mark">${src?`<img src="${esc(src)}" alt="">`:(flag?`<b>${esc(flag)}</b>`:`<b>${esc(code||'?')}</b>`)}</span>
      <span class="sbb-smc-copy"><small>${esc(code)}</small><strong>${esc(partName(p))}</strong></span>
      <b class="sbb-smc-score">${value===''?'—':esc(value)}</b>
    </div>`;
  }
  function setLabels(matchCenter){
    for(const id of ['gameCenterDrawerBtn','gameCenterTabBtn']){const el=$(id);if(el)el.textContent=matchCenter?'MATCH CENTER':'GAME CENTER';}
  }
  function deactivate(reason='Game Center available'){
    if(!state.active)return false;
    state.active=false;state.lastReason=reason;document.body?.classList.remove('sbb-sport-match-center-active');
    const host=$('sbbSportMatchCenter');if(host){host.innerHTML='';host.classList.remove('active');}
    setLabels(false);return true;
  }
  function activate(evt,reason='Detailed Game Center data is not available for this event.'){
    if(!evt||document.body?.classList.contains('sbb-special-event-match-center'))return false;
    const host=ensureHost();if(!host)return false;
    const {away,home}=participants(evt),awayScore=score(evt,'away'),homeScore=score(evt,'home');
    const status=clean(evt.status||evt.state||evt.statusText)||'Selected event';
    const date=clean(evt.date||evt.scheduledAt||evt.gameDate).slice(0,10);
    const round=clean(evt.roundName||evt.round||evt.stage||evt.phase||evt.group);
    const venue=clean(evt.venue||evt.location);
    const comp=competition(evt),key=eventKey(evt);
    if(state.active&&state.lastKey===key){state.lastReason=reason;return true;}
    state.applying=true;
    host.innerHTML=`<div class="sbb-smc-kicker">SPORT MATCH CENTER</div>
      <div class="sbb-smc-competition">${esc(comp)}</div>
      <div class="sbb-smc-scoreboard">${participantMarkup('away',away,awayScore)}<div class="sbb-smc-status"><strong>${esc(status)}</strong><span>${esc([round,date,venue].filter(Boolean).join(' · '))}</span></div>${participantMarkup('home',home,homeScore)}</div>
      <div class="sbb-smc-note"><strong>EVENT CONTEXT</strong><span>${esc(reason||'Detailed statistics are not supplied for this event, but Sports Big Board will keep the selected matchup synchronized with playback.')}</span></div>
      <button id="sbbSportMatchRetry" class="sbb-smc-retry" type="button">RETRY DETAILED GAME CENTER</button>`;
    host.classList.add('active');document.body?.classList.add('sbb-sport-match-center-active');setLabels(true);
    host.querySelectorAll('img').forEach(img=>img.addEventListener('error',()=>img.closest('.sbb-smc-mark')?.classList.add('image-failed'),{once:true}));
    $('sbbSportMatchRetry')?.addEventListener('click',()=>{
      deactivate('explicit detailed retry');
      try{window.SBB_GAME_CENTER_VIEW?.load?.(evt,{force:true});}catch(_){}
    });
    state.applying=false;
    if(!state.active||state.lastKey!==key)state.activations++;
    state.active=true;state.lastKey=key;state.lastReason=reason;
    return true;
  }
  function errorReason(){
    const overview=$('gcOverview'),empty=$('gameCenterEmpty');
    const error=overview?.querySelector?.('.gc-error');
    if(error)return clean(error.querySelector('span')?.textContent||error.textContent||'Detailed Game Center provider request failed.');
    const text=clean(`${overview?.textContent||''} ${empty?.textContent||''}`);
    return /game center unavailable|unable to load game data|did not finish loading/i.test(text)?text.slice(0,240):'';
  }
  function reconcile(reason='Game Center DOM changed'){
    if(state.applying)return;
    if(document.body?.classList.contains('sbb-special-event-match-center')){deactivate('Special Event Match Center owns panel');return;}
    const evt=activeEvent();if(!evt){deactivate('No selected event');return;}
    const error=errorReason();
    if(error&&usefulEvent(evt)){activate(evt,error);return;}
    if(!providerSupported(evt)&&usefulEvent(evt)){activate(evt,'Detailed statistics are not supplied for this competition. Match Center follows the selected event and playback.');return;}
    // Successful provider content wins over the fallback automatically.
    if($('gameCenterContent')&&!$('gameCenterContent').classList.contains('hidden')&&$('gcOverview')?.children?.length)deactivate('Detailed Game Center rendered');
  }
  function init(){
    ensureHost();
    const pane=$('gameCenterPane');
    if(pane&&typeof MutationObserver!=='undefined'){
      state.observer=new MutationObserver(()=>queueMicrotask(()=>reconcile('Game Center render mutation')));
      state.observer.observe(pane,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class']});
    }
    try{window.SBB_SELECTED_EVENT?.subscribe?.(evt=>{
      if(evt&&!providerSupported(evt)&&usefulEvent(evt)&&!document.body?.classList.contains('sbb-special-event-match-center')){
        activate(evt,'Detailed statistics are not supplied for this competition. Match Center follows the selected event and playback.');return;
      }
      queueMicrotask(()=>reconcile(evt?'Selected event changed':'Selected event cleared'));
    });}catch(_){}
    window.addEventListener('sbb:curated-event-identity',()=>queueMicrotask(()=>reconcile('Curated event changed')));
    window.addEventListener('sbb:league-context',()=>queueMicrotask(()=>reconcile('League context changed')));
    reconcile('initial');
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  window.SBB_SPORT_MATCH_CENTER=Object.freeze({version:VERSION,reconcile,activate,deactivate,snapshot:()=>({version:VERSION,active:state.active,lastKey:state.lastKey,activations:state.activations,lastReason:state.lastReason})});
})();

/* Sports Big Board v4.7.16 — Score Ribbon Identity Guard.
   - Distinguishes legitimate same-day doubleheaders as GAME 1 / GAME 2.
   - Suppresses exact duplicate event IDs defensively without deleting card nodes.
   - Rejects MLB recap assets whose title explicitly names a different game date.
   - Hotfix: enforces sport-filter visibility independently of CSS [hidden]
     behavior and adds lightweight ribbon/day/filter motion.

   The guard is intentionally read/render-side only. It does not mutate canonical
   schedule identity, playback ownership, Day State, or the persistent catalog.
*/
(() => {
  'use strict';
  if(window.SBB_SCORE_RIBBON_IDENTITY_GUARD?.version==='4.7.16')return;

  const VERSION='4.7.16';
  const state={installed:false,annotations:0,exactDuplicatesHidden:0,dateRejects:0,last:null};
  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const MONTHS={
    january:1,february:2,march:3,april:4,may:5,june:6,july:7,august:8,september:9,october:10,november:11,december:12,
    jan:1,feb:2,mar:3,apr:4,jun:6,jul:7,aug:8,sep:9,sept:9,oct:10,nov:11,dec:12
  };

  function leagueFor(value){
    return upper(value?.competitionId||value?.__sbbLeague||value?.league||value?.sport||'SPORTS');
  }
  function eventDate(value){
    return clean(value?.__sbbDate||value?.gameDate||value?.date||value?.scheduledAt).slice(0,10);
  }
  function eventId(value){
    const id=[value?.scoreEventId,value?.espnEventId,value?.gameCenterEventId,value?.matchId,value?.gamePk,value?.eventId,value?.id]
      .find(x=>x!==undefined&&x!==null&&clean(x)!=='');
    return id===undefined?'':clean(id);
  }
  function teamName(value,side){
    const team=value?.[`${side}Team`]||value?.[side]||value?.[`${side}Name`]||'';
    return upper(team?.name||team?.displayName||team?.shortDisplayName||team?.abbreviation||team);
  }
  function pairKey(value){
    const away=teamName(value,'away'),home=teamName(value,'home');
    const pair=[away,home].sort();
    return `${leagueFor(value)}|${eventDate(value)}|${pair[0]||''}|${pair[1]||''}`;
  }
  function scheduledMs(value){
    const raw=clean(value?.scheduledAt||value?.dateTime||value?.startTime||value?.date);
    const ms=raw?Date.parse(raw):NaN;
    return Number.isFinite(ms)?ms:Number.MAX_SAFE_INTEGER;
  }
  function explicitTitleDates(item,eventYear=0){
    const title=clean(item?.title);const dates=new Set();
    let m;
    const iso=/\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b/g;
    while((m=iso.exec(title))){
      dates.add(`${String(Number(m[1])).padStart(4,'0')}-${String(Number(m[2])).padStart(2,'0')}-${String(Number(m[3])).padStart(2,'0')}`);
    }
    const named=/\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,)?(?:\s+(20\d{2}))?\b/gi;
    while((m=named.exec(title))){
      const month=MONTHS[String(m[1]).toLowerCase()]||0;
      const year=Number(m[3]||eventYear||0);
      if(month&&year)dates.add(`${String(year).padStart(4,'0')}-${String(month).padStart(2,'0')}-${String(Number(m[2])).padStart(2,'0')}`);
    }
    return dates;
  }
  function itemAllowedForMatch(item,match){
    if(leagueFor(match)!=='MLB')return true;
    const date=eventDate(match);if(!date)return true;
    const dates=explicitTitleDates(item,Number(date.slice(0,4))||0);
    if(!dates.size||dates.has(date))return true;
    state.dateRejects+=1;
    try{
      window.dispatchEvent(new CustomEvent('sbb:score-ribbon-identity',{
        detail:{type:'media-date-reject',date,eventId:eventId(match),title:clean(item?.title),explicitDates:[...dates],at:Date.now()}
      }));
    }catch(_){}
    return false;
  }

  function installMediaDateGuard(){
    const original=window.scoreCardPlayableItems;
    if(typeof original!=='function')return false;
    if(original.__sbbScoreRibbonIdentityGuard)return true;
    const wrapped=function(match){
      const result=original.apply(this,arguments);
      if(!Array.isArray(result))return result;
      return result.filter(item=>itemAllowedForMatch(item,match));
    };
    wrapped.__sbbScoreRibbonIdentityGuard=true;
    wrapped.__sbbOriginal=original;
    window.scoreCardPlayableItems=wrapped;
    state.installed=true;
    return true;
  }

  function cardMatch(card){return card?.__sbbMatch||null;}
  function gameCards(){
    const host=document.getElementById('scoreCells');
    return host?[...host.children].filter(x=>x?.classList?.contains('score-card')&&!x.classList.contains('roundup-card')):[];
  }
  function restoreBaseLabel(card){
    const small=card?.querySelector?.('.score-card-top small');
    if(!small)return;
    if(small.dataset.sbbBaseDayLabel)small.textContent=small.dataset.sbbBaseDayLabel;
    delete small.dataset.sbbDoubleheaderGame;
    card.classList.remove('sbb-doubleheader-game');
    delete card.dataset.sbbDoubleheaderGame;
    const aria=clean(card.getAttribute('aria-label')).replace(/; Game \d+ of \d+$/,'');
    if(aria)card.setAttribute('aria-label',aria);
    card.title=clean(card.title).replace(/\s*•\s*Game \d+ of \d+$/,'');
  }
  function annotateCard(card,index,total){
    const small=card?.querySelector?.('.score-card-top small');
    if(!small)return;
    if(!small.dataset.sbbBaseDayLabel)small.dataset.sbbBaseDayLabel=clean(small.textContent)||'GAME';
    const game=index+1;
    small.dataset.sbbDoubleheaderGame=String(game);
    small.textContent=`${small.dataset.sbbBaseDayLabel} • GAME ${game}`;
    card.classList.add('sbb-doubleheader-game');
    card.dataset.sbbDoubleheaderGame=String(game);
    const suffix=`Game ${game} of ${total}`;
    const aria=clean(card.getAttribute('aria-label'));
    if(aria&&!aria.includes(suffix))card.setAttribute('aria-label',`${aria}; ${suffix}`);
    card.title=clean(card.title).replace(/\s*•\s*Game \d+ of \d+$/,'');
    card.title=`${clean(card.title)}${clean(card.title)?' • ':''}${suffix}`;
  }
  function reconcile(){
    const cards=gameCards();
    for(const card of cards){
      restoreBaseLabel(card);
      card.classList.remove('sbb-exact-duplicate');
    }

    const seenIds=new Map();let duplicates=0;
    for(const card of cards){
      const match=cardMatch(card);if(!match)continue;
      const id=eventId(match);if(!id)continue;
      const key=`${leagueFor(match)}|${id}`;
      if(seenIds.has(key)){
        card.classList.add('sbb-exact-duplicate');duplicates+=1;
      }else seenIds.set(key,card);
    }

    const groups=new Map();
    for(const card of cards){
      if(card.classList.contains('sbb-exact-duplicate'))continue;
      const match=cardMatch(card);if(!match)continue;
      const key=pairKey(match);if(!key)continue;
      const list=groups.get(key)||[];list.push(card);groups.set(key,list);
    }
    let annotations=0,groupsAnnotated=0;
    for(const group of groups.values()){
      if(group.length<2)continue;
      group.sort((a,b)=>{
        const am=cardMatch(a),bm=cardMatch(b);
        return scheduledMs(am)-scheduledMs(bm)||eventId(am).localeCompare(eventId(bm));
      });
      group.forEach((card,index)=>annotateCard(card,index,group.length));
      annotations+=group.length;groupsAnnotated+=1;
    }
    state.annotations+=annotations;state.exactDuplicatesHidden+=duplicates;
    state.last={at:Date.now(),cards:cards.length,doubleheaderGroups:groupsAnnotated,annotations,exactDuplicatesHidden:duplicates,dateRejects:state.dateRejects};
    return state.last;
  }
  let queued=false;
  function schedule(){
    if(queued)return;queued=true;
    requestAnimationFrame(()=>{queued=false;installMediaDateGuard();reconcile();});
  }
  function injectStyle(){
    if(document.getElementById('sbbScoreRibbonIdentityStyle'))return;
    const style=document.createElement('style');style.id='sbbScoreRibbonIdentityStyle';
    style.textContent=`
      .score-card.sbb-exact-duplicate{display:none!important}
      .score-card.sbb-filter-hidden{display:none!important}
      #scoreFilters [data-score-filter]{transition:background .16s ease,border-color .16s ease,color .16s ease,transform .16s ease,box-shadow .16s ease!important}
      #scoreFilters [data-score-filter].sbb-filter-motion{animation:sbbFilterChip .22s cubic-bezier(.2,.8,.2,1)}
      @keyframes sbbFilterChip{0%{transform:scale(.94)}60%{transform:scale(1.055)}100%{transform:scale(1)}}
      #scoreCells{scroll-behavior:smooth;scroll-snap-type:x proximity;will-change:scroll-position}
      #scoreCells .score-card{scroll-snap-align:start}
      #scoreCells.sbb-ribbon-scrolling .score-card{transition:filter .12s ease,opacity .12s ease;filter:brightness(1.035)}
      @media(prefers-reduced-motion:reduce){
        #scoreFilters [data-score-filter],#scoreCells .score-card{animation:none!important;transition:none!important}
        #scoreCells{scroll-behavior:auto!important;scroll-snap-type:none!important}
      }
    `;
    document.head?.appendChild(style);
  }

  /* v4.7.16 UI hotfix: filter truth + lightweight transitions. The filter fast
     path remains authoritative for data/render work; this layer only projects the
     selected chip into guaranteed display:none semantics and presentation motion. */
  const motion={filter:'ALL',pendingDayDirection:0,filterCorrections:0,dayTransitions:0,filterTransitions:0,scrollTransitions:0};
  const reduceMotion=()=>window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches===true;
  function cardLeague(card){
    for(const cls of card?.classList||[]){if(cls.startsWith('league-'))return upper(cls.slice(7));}
    return '';
  }
  function activeFilter(){
    const active=typeof document.querySelector==='function'?document.querySelector('#scoreFilters [data-score-filter].active'):null;
    return upper(active?.dataset?.scoreFilter||motion.filter||'ALL')||'ALL';
  }
  function applyFilterTruth({animate=false}={}){
    const filter=activeFilter();motion.filter=filter;
    const host=document.getElementById('scoreCells');if(!host)return {filter,visible:0,hidden:0};
    let visible=0,hidden=0,changed=false;
    for(const card of [...host.children]){
      if(!card?.classList?.contains('score-card')||card.classList.contains('roundup-card'))continue;
      const show=filter==='ALL'||cardLeague(card)===filter;
      const wasHidden=card.classList.contains('sbb-filter-hidden')||card.hidden;
      if(show)card.classList.remove('sbb-filter-hidden');else card.classList.add('sbb-filter-hidden');
      card.hidden=!show;
      if(show)visible++;else hidden++;
      if(wasHidden===show)changed=true;
    }
    if(changed)motion.filterCorrections+=1;
    if(animate&&!reduceMotion()){
      motion.filterTransitions+=1;
      try{
        host.animate([
          {opacity:.62,transform:'translateY(3px) scale(.995)'},
          {opacity:1,transform:'translateY(0) scale(1)'}
        ],{duration:190,easing:'cubic-bezier(.2,.75,.2,1)'});
        [...host.querySelectorAll('.score-card:not(.sbb-filter-hidden)')].slice(0,14).forEach((card,i)=>{
          card.animate([
            {opacity:.72,transform:'translateX(6px)'},
            {opacity:1,transform:'translateX(0)'}
          ],{duration:150+Math.min(i,6)*12,easing:'ease-out'});
        });
      }catch(_){}
    }
    return {filter,visible,hidden};
  }
  function animateFilterChip(btn){
    if(!btn||reduceMotion())return;
    btn.classList.remove('sbb-filter-motion');void btn.offsetWidth;btn.classList.add('sbb-filter-motion');
    setTimeout(()=>btn.classList.remove('sbb-filter-motion'),260);
  }
  function animateDay(direction){
    if(!direction||reduceMotion())return;
    const host=document.getElementById('scoreCells');if(!host)return;
    const px=direction<0?-34:34;
    motion.dayTransitions+=1;
    try{host.animate([{opacity:.42,transform:`translateX(${px}px)`},{opacity:1,transform:'translateX(0)'}],{duration:260,easing:'cubic-bezier(.2,.78,.2,1)'});}catch(_){}
    const key=document.querySelector('.key-info-ribbon');
    try{key?.animate?.([{opacity:.68,transform:`translateX(${px*.35}px)`},{opacity:1,transform:'translateX(0)'}],{duration:220,easing:'ease-out'});}catch(_){}
  }
  function wireMotion(){
    const filters=document.getElementById('scoreFilters');
    if(filters&&!filters.dataset.sbbMotionWired){
      filters.dataset.sbbMotionWired='1';
      filters.addEventListener('click',ev=>{
        const btn=ev.target.closest('[data-score-filter]');if(!btn)return;
        motion.filter=upper(btn.dataset.scoreFilter||'ALL')||'ALL';
        animateFilterChip(btn);
        setTimeout(()=>requestAnimationFrame(()=>applyFilterTruth({animate:true})),0);
      },{capture:true});
    }
    const dateButtons=typeof document.querySelectorAll==='function'?document.querySelectorAll('[data-score-date-step]'):[];
    dateButtons.forEach(btn=>{
      if(btn.dataset.sbbMotionWired)return;btn.dataset.sbbMotionWired='1';
      btn.addEventListener('click',()=>{motion.pendingDayDirection=Number(btn.dataset.scoreDateStep||0)<0?-1:1;},{capture:true});
    });
    const host=document.getElementById('scoreCells');
    if(host&&host.dataset&&!host.dataset.sbbScrollMotionWired){
      host.dataset.sbbScrollMotionWired='1';let timer=null;
      host.addEventListener('scroll',()=>{
        host.classList.add('sbb-ribbon-scrolling');motion.scrollTransitions+=1;
        clearTimeout(timer);timer=setTimeout(()=>host.classList.remove('sbb-ribbon-scrolling'),110);
      },{passive:true});
      host.addEventListener('wheel',ev=>{
        if(reduceMotion())return;
        if(host.scrollWidth<=host.clientWidth+4)return;
        if(Math.abs(ev.deltaY)<=Math.abs(ev.deltaX))return;
        ev.preventDefault();host.scrollBy({left:ev.deltaY*1.15,behavior:'smooth'});
      },{passive:false});
    }
  }
  function motionReconcile({animateFilter=false}={}){wireMotion();return applyFilterTruth({animate:animateFilter});}

  function boot(){
    injectStyle();installMediaDateGuard();wireMotion();schedule();motionReconcile();
    const timer=setInterval(()=>{if(installMediaDateGuard())clearInterval(timer);},100);
    setTimeout(()=>clearInterval(timer),5000);
    const host=document.getElementById('scoreCells');
    if(host&&typeof MutationObserver==='function'){
      const observer=new MutationObserver(()=>requestAnimationFrame(()=>motionReconcile()));
      observer.observe(host,{childList:true,subtree:false});
    }
  }

  window.addEventListener('sbb:render-pipeline',ev=>{
    const type=clean(ev?.detail?.type);const reason=clean(ev?.detail?.reason).toLowerCase();
    if(['render','paint','generation-commit'].includes(type)){
      schedule();requestAnimationFrame(()=>motionReconcile());
      if(type==='paint'&&motion.pendingDayDirection&&(reason.includes('date')||reason.includes('history-arrow')||reason.includes('day-state'))){
        const dir=motion.pendingDayDirection;motion.pendingDayDirection=0;animateDay(dir);
      }
    }
  });
  window.SBB_RIBBON_MOTION=Object.freeze({
    version:'4.7.16-hotfix-1',reconcile:motionReconcile,animateDay,
    snapshot:()=>({...motion,filter:activeFilter()})
  });
  window.SBB_SCORE_RIBBON_IDENTITY_GUARD=Object.freeze({
    version:VERSION,install:installMediaDateGuard,reconcile,itemAllowedForMatch,
    snapshot:()=>({version:VERSION,installed:state.installed,annotations:state.annotations,exactDuplicatesHidden:state.exactDuplicatesHidden,dateRejects:state.dateRejects,last:state.last?{...state.last}:null})
  });
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();

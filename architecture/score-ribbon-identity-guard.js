/* Sports Big Board v4.7.16 — Score Ribbon Identity Guard.
   - Distinguishes legitimate same-day doubleheaders as GAME 1 / GAME 2.
   - Suppresses exact duplicate event IDs defensively without deleting card nodes.
   - Rejects MLB recap assets whose title explicitly names a different game date.

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
    style.textContent='.score-card.sbb-exact-duplicate{display:none!important}';
    document.head?.appendChild(style);
  }
  function boot(){
    injectStyle();installMediaDateGuard();schedule();
    const timer=setInterval(()=>{if(installMediaDateGuard())clearInterval(timer);},100);
    setTimeout(()=>clearInterval(timer),5000);
  }

  window.addEventListener('sbb:render-pipeline',ev=>{
    if(['render','paint','generation-commit'].includes(clean(ev?.detail?.type)))schedule();
  });
  window.SBB_SCORE_RIBBON_IDENTITY_GUARD=Object.freeze({
    version:VERSION,install:installMediaDateGuard,reconcile,itemAllowedForMatch,
    snapshot:()=>({version:VERSION,installed:state.installed,annotations:state.annotations,exactDuplicatesHidden:state.exactDuplicatesHidden,dateRejects:state.dateRejects,last:state.last?{...state.last}:null})
  });
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();

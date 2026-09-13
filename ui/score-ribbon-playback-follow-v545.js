/* Sports Big Board v5.5.1 — playback-following score/All ribbon + user scroll ownership.
   The currently playing game is highlighted in the visible score/All ribbon. Automatic
   follow is allowed only when the active game identity actually changes and the user is
   not actively navigating the ribbon. Horizontal trackpad gestures remain native; a
   vertical mouse wheel is translated into a gentle eased horizontal motion. */
(() => {
  'use strict';
  if(window.SBB_SCORE_RIBBON_PLAYBACK_FOLLOW?.version==='5.5.1-scroll-control')return;
  const VERSION='5.5.1-scroll-control';
  const USER_QUIET_MS=1400;
  const STOP=new Set(('a an and are as at away by final for from full game games highlight highlights in is league live match of official on recap result season sports the to today vs versus with yesterday').split(' '));
  let scheduled=false,lastSignature='',lastCard=null,lastScrollAt=0,observer=null,titleObserver=null;
  let lastUserInteractionAt=0,wheelTarget=null,wheelRAF=0,wheelHost=null;
  const clean=v=>String(v??'').trim();
  const norm=v=>clean(v).toLowerCase().replace(/&/g,' and ').replace(/[^a-z0-9]+/g,' ').replace(/\s+/g,' ').trim();
  const tokens=v=>[...new Set(norm(v).split(' ').filter(t=>t.length>=2&&!STOP.has(t)&&!/^(19|20)\d\d$/.test(t)&&!/^\d+$/.test(t)))];
  const visible=el=>{if(!el||!el.isConnected||el.hidden||el.classList?.contains('hidden'))return false;const r=el.getBoundingClientRect?.();return !!r&&r.width>0&&r.height>0;};
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  const markUserInteraction=()=>{lastUserInteractionAt=Date.now();};
  const userInteractionActive=()=>Date.now()-lastUserInteractionAt<USER_QUIET_MS;

  function currentItem(){
    try{if(typeof clip==='function'&&typeof currentIndex!=='undefined')return clip(currentIndex)||null;}catch(_){}
    try{if(Array.isArray(PROGRAM)){const i=Math.max(0,Math.min(Number(currentIndex)||0,PROGRAM.length-1));return PROGRAM[i]||null;}}catch(_){}
    return null;
  }
  function selectedEvent(){try{return window.SBB_SELECTED_EVENT?.get?.()||null;}catch(_){return null;}}
  function idsOf(obj){
    if(!obj||typeof obj!=='object')return [];
    const keys=['canonicalEventKey','eventKey','eventId','providerEventId','gameId','matchId','id','uid'];
    const out=[];
    for(const k of keys){const v=clean(obj[k]);if(v)out.push(norm(v));}
    for(const k of ['match','event','competition','scoreMatch']){const child=obj[k];if(child&&typeof child==='object')for(const id of idsOf(child))out.push(id);}
    return [...new Set(out.filter(v=>v.length>=3))];
  }
  function teamStrings(obj){
    if(!obj||typeof obj!=='object')return [];
    const out=[];
    const add=v=>{v=clean(v);if(v)out.push(v);};
    const side=side=>{
      const v=obj[side]||obj[`${side}Team`]||obj[`${side}Participant`];
      if(typeof v==='string')add(v);
      else if(v&&typeof v==='object'){add(v.displayName);add(v.name);add(v.shortName);add(v.abbreviation);add(v.team?.displayName);add(v.team?.name);add(v.team?.abbreviation);}
      add(obj[`${side}Name`]);add(obj[`${side}DisplayName`]);add(obj[`${side}Abbreviation`]);
    };
    side('away');side('home');
    for(const c of obj.competitors||obj.participants||[]){add(c?.displayName);add(c?.name);add(c?.abbreviation);add(c?.team?.displayName);add(c?.team?.name);add(c?.team?.abbreviation);add(c?.athlete?.displayName);}
    for(const k of ['title','name','matchup','displayName'])add(obj[k]);
    return [...new Set(out.map(norm).filter(Boolean))];
  }
  function activeTexts(){
    const item=currentItem(),selected=selectedEvent(),title=clean(document.getElementById('currentTitle')?.textContent);
    const values=[title,...teamStrings(item),...teamStrings(selected)].filter(Boolean);
    return [...new Set(values)];
  }
  function cardHaystack(card){
    const data=Object.values(card?.dataset||{}).map(clean).join(' ');
    return norm(`${data} ${card?.getAttribute?.('aria-label')||''} ${card?.getAttribute?.('title')||''} ${card?.textContent||''}`);
  }
  function scoreCard(card,ids,textValues){
    const hay=cardHaystack(card);if(!hay)return -Infinity;
    let score=0;
    for(const id of ids){if(id&&hay.includes(id))score=Math.max(score,1000+id.length);}
    const cardTokens=new Set(tokens(hay));
    for(const text of textValues){
      const tt=tokens(text);if(!tt.length)continue;
      let overlap=0;for(const t of tt)if(cardTokens.has(t))overlap++;
      if(overlap>=2)score=Math.max(score,overlap*40+(overlap/tt.length)*30);
      if(norm(text).length>=5&&hay.includes(norm(text)))score=Math.max(score,240+norm(text).length);
    }
    return score;
  }
  function ribbonContext(){
    const curated=document.getElementById('sbbCurationCards');
    if(document.body?.classList?.contains('sbb-curation-active')&&curated&&!curated.closest?.('[hidden]')){
      return {host:curated,cards:[...curated.querySelectorAll('[data-curation-index],.sbb-curation-card')].filter((v,i,a)=>a.indexOf(v.closest?.('[data-curation-index]')||v)===i).map(v=>v.closest?.('[data-curation-index]')||v),kind:'curated'};
    }
    const host=document.getElementById('scoreCells');
    if(!host)return null;
    return {host,cards:[...host.querySelectorAll('.score-card,.score-cell')].filter(el=>!el.classList.contains('score-placeholder')),kind:'scores'};
  }
  function allScopeActive(ctx){
    if(ctx?.kind==='curated')return true;
    const active=document.querySelector('#scoreFilters [data-score-filter].active,#scoreFilters [data-score-filter][aria-pressed="true"]');
    return clean(active?.dataset?.scoreFilter).toUpperCase()==='ALL';
  }
  function clearHighlight(except=null){
    document.querySelectorAll('.sbb-program-now-watching').forEach(el=>{if(el!==except){el.classList.remove('sbb-program-now-watching');el.removeAttribute('data-sbb-playback-follow');if(el.getAttribute('aria-current')==='true')el.removeAttribute('aria-current');}});
  }
  function stableSignature(ctx,card,ids,textValues){
    const hay=cardHaystack(card);
    const data=card?.dataset||{};
    const stableData=clean(data.sbbFocusId||data.canonicalEventKey||data.eventKey||data.eventId||data.providerEventId||data.gameId||data.matchId||data.uid||'');
    const matchedId=ids.find(id=>id&&hay.includes(id))||'';
    const cardTokens=new Set(tokens(hay));
    const shared=[...new Set(textValues.flatMap(tokens).filter(t=>cardTokens.has(t)))].sort().slice(0,10).join('.');
    const stableId=norm(stableData)||matchedId;
    // Once we have a real event/game id, score/status/title churn must not change
    // playback identity. Token matching is only a fallback for id-less cards.
    return stableId?`${ctx?.kind||'scores'}|id:${stableId}`:`${ctx?.kind||'scores'}|tokens:${shared}`;
  }
  function scrollToThird(ctx,card){
    if(!ctx?.host||!card||!allScopeActive(ctx)||userInteractionActive())return false;
    const cards=ctx.cards.filter(visible);const idx=cards.indexOf(card);if(idx<0)return false;
    const anchor=cards[Math.max(0,idx-2)]||card;
    const host=ctx.host;const left=Math.max(0,Math.min(anchor.offsetLeft-8,Math.max(0,host.scrollWidth-host.clientWidth)));
    if(Math.abs((host.scrollLeft||0)-left)<5)return false;
    const smooth=!window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    try{host.scrollTo({left,behavior:smooth?'smooth':'auto'});}catch(_){host.scrollLeft=left;}
    lastScrollAt=Date.now();return true;
  }
  function reconcile(reason='sync'){
    scheduled=false;const ctx=ribbonContext();if(!ctx||!ctx.cards.length){clearHighlight();lastCard=null;return null;}
    const item=currentItem(),selected=selectedEvent(),ids=[...idsOf(item),...idsOf(selected)],texts=activeTexts();
    if(!ids.length&&!texts.length){clearHighlight();lastCard=null;return null;}
    let best=null,bestScore=-Infinity;
    for(const card of ctx.cards){const s=scoreCard(card,ids,texts);if(s>bestScore){best=card;bestScore=s;}}
    // Require either a stable id hit or at least two meaningful overlapping words.
    if(!best||bestScore<80){clearHighlight();lastCard=null;return null;}
    const signature=stableSignature(ctx,best,ids,texts);
    const identityChanged=signature!==lastSignature;
    clearHighlight(best);best.classList.add('sbb-program-now-watching');best.dataset.sbbPlaybackFollow='1';best.setAttribute('aria-current','true');
    // A DOM refresh may replace the card element without changing the game. Never
    // re-center for that. A real game change may follow only while the user is idle.
    const followed=identityChanged?scrollToThird(ctx,best):false;
    lastCard=best;lastSignature=signature;
    return {reason,kind:ctx.kind,score:bestScore,card:best,identityChanged,followed,userOwned:userInteractionActive()};
  }
  function schedule(reason='event'){
    if(scheduled)return;scheduled=true;
    const run=()=>reconcile(reason);if(typeof requestAnimationFrame==='function')requestAnimationFrame(run);else setTimeout(run,0);
  }

  function normalizeVerticalWheel(event,host){
    let delta=event.deltaY;
    if(event.deltaMode===1)delta*=28;
    else if(event.deltaMode===2)delta*=Math.max(280,host?.clientWidth||600);
    return delta;
  }
  function runWheelEase(){
    wheelRAF=0;const host=wheelHost;
    if(!host?.isConnected||wheelTarget===null){wheelTarget=null;wheelHost=null;return;}
    const max=Math.max(0,host.scrollWidth-host.clientWidth);
    wheelTarget=clamp(wheelTarget,0,max);
    const current=Number(host.scrollLeft)||0,diff=wheelTarget-current;
    if(Math.abs(diff)<0.75){host.scrollLeft=wheelTarget;wheelTarget=null;wheelHost=null;return;}
    host.scrollLeft=current+diff*.34;
    wheelRAF=requestAnimationFrame(runWheelEase);
  }
  function handleRibbonWheel(event){
    const host=event.target?.closest?.('#scoreCells');if(!host)return;
    markUserInteraction();
    const ax=Math.abs(Number(event.deltaX)||0),ay=Math.abs(Number(event.deltaY)||0);
    // Trackpads already provide high-quality compositor horizontal scrolling. Stop
    // the legacy target listener from multiplying the delta, but preserve default.
    if(ax>=ay*.75&&ax>.01){event.stopPropagation();wheelTarget=null;if(wheelRAF){cancelAnimationFrame(wheelRAF);wheelRAF=0;}wheelHost=null;return;}
    if(ay<=.01)return;
    // Conventional mouse wheels are vertical. Translate them to a restrained eased
    // horizontal target instead of the legacy 2.65x one-frame jump.
    event.preventDefault();event.stopPropagation();
    const max=Math.max(0,host.scrollWidth-host.clientWidth),delta=normalizeVerticalWheel(event,host);
    if(!Number.isFinite(delta)||max<=1)return;
    wheelHost=host;wheelTarget=clamp((wheelTarget===null?host.scrollLeft:wheelTarget)+delta*1.05,0,max);
    if(!wheelRAF)wheelRAF=requestAnimationFrame(runWheelEase);
  }
  function bindUserScrollOwnership(){
    // This runs on document capture, before v5.2.2's target-capture wheel translator.
    // Touch/pointer scrolling remains completely native.
    document.addEventListener('wheel',handleRibbonWheel,{passive:false,capture:true});
    document.addEventListener('touchstart',event=>{if(event.target?.closest?.('#scoreCells'))markUserInteraction();},{passive:true,capture:true});
    document.addEventListener('touchmove',event=>{if(event.target?.closest?.('#scoreCells'))markUserInteraction();},{passive:true,capture:true});
    document.addEventListener('pointerdown',event=>{if(event.target?.closest?.('#scoreCells'))markUserInteraction();},{passive:true,capture:true});
  }
  function bind(){
    bindUserScrollOwnership();
    const title=document.getElementById('currentTitle');if(title&&typeof MutationObserver==='function'){titleObserver=new MutationObserver(()=>schedule('title-change'));titleObserver.observe(title,{childList:true,subtree:true,characterData:true});}
    const score=document.getElementById('scoreCells');if(score&&typeof MutationObserver==='function'){observer=new MutationObserver(()=>schedule('score-ribbon-render'));observer.observe(score,{childList:true,subtree:false});}
    for(const name of ['sbb:score-click-selection','sbb:playback-progress-confirmed','sbb:curated-event-identity','sbb:league-context','sbb:browse-layout'])window.addEventListener(name,()=>schedule(name));
    try{window.SBB_SELECTED_EVENT?.subscribe?.(()=>schedule('selected-event'));}catch(_){}
    document.addEventListener('click',event=>{if(event.target?.closest?.('.score-card,[data-curation-index]'))setTimeout(()=>schedule('card-click'),0);},true);
    schedule('startup');
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
  window.SBB_SCORE_RIBBON_PLAYBACK_FOLLOW=Object.freeze({version:VERSION,reconcile:()=>reconcile('manual'),schedule,snapshot:()=>({version:VERSION,lastSignature,lastCard:lastCard?.dataset?.sbbFocusId||clean(lastCard?.textContent).slice(0,80),lastScrollAt,lastUserInteractionAt,userInteractionActive:userInteractionActive(),wheelAnimating:!!wheelRAF})});
})();

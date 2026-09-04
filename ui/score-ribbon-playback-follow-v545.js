/* Sports Big Board v5.4.5 — playback-following score/All ribbon.
   The currently playing game is highlighted in the visible score/All ribbon and
   the horizontal ribbon follows program advancement so the active game settles
   around the third visible card. Work is event-driven; no continuous polling. */
(() => {
  'use strict';
  if(window.SBB_SCORE_RIBBON_PLAYBACK_FOLLOW?.version==='5.4.5')return;
  const VERSION='5.4.5';
  const STOP=new Set(('a an and are as at away by final for from full game games highlight highlights in is league live match of official on recap result season sports the to today vs versus with yesterday').split(' '));
  let scheduled=false,lastSignature='',lastCard=null,lastScrollAt=0,observer=null,titleObserver=null;
  const clean=v=>String(v??'').trim();
  const norm=v=>clean(v).toLowerCase().replace(/&/g,' and ').replace(/[^a-z0-9]+/g,' ').replace(/\s+/g,' ').trim();
  const tokens=v=>[...new Set(norm(v).split(' ').filter(t=>t.length>=2&&!STOP.has(t)&&!/^(19|20)\d\d$/.test(t)&&!/^\d+$/.test(t)))];
  const visible=el=>{if(!el||!el.isConnected||el.hidden||el.classList?.contains('hidden'))return false;const r=el.getBoundingClientRect?.();return !!r&&r.width>0&&r.height>0;};

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
  function scrollToThird(ctx,card){
    if(!ctx?.host||!card||!allScopeActive(ctx))return;
    const cards=ctx.cards.filter(visible);const idx=cards.indexOf(card);if(idx<0)return;
    const anchor=cards[Math.max(0,idx-2)]||card;
    const host=ctx.host;const left=Math.max(0,Math.min(anchor.offsetLeft-8,Math.max(0,host.scrollWidth-host.clientWidth)));
    if(Math.abs((host.scrollLeft||0)-left)<5)return;
    const smooth=!window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    try{host.scrollTo({left,behavior:smooth?'smooth':'auto'});}catch(_){host.scrollLeft=left;}
    lastScrollAt=Date.now();
  }
  function reconcile(reason='sync'){
    scheduled=false;const ctx=ribbonContext();if(!ctx||!ctx.cards.length){clearHighlight();lastCard=null;return null;}
    const item=currentItem(),selected=selectedEvent(),ids=[...idsOf(item),...idsOf(selected)],texts=activeTexts();
    if(!ids.length&&!texts.length){clearHighlight();lastCard=null;return null;}
    let best=null,bestScore=-Infinity;
    for(const card of ctx.cards){const s=scoreCard(card,ids,texts);if(s>bestScore){best=card;bestScore=s;}}
    // Require either a stable id hit or at least two meaningful overlapping words.
    if(!best||bestScore<80){clearHighlight();lastCard=null;return null;}
    const signature=`${ctx.kind}|${ids[0]||''}|${norm(document.getElementById('currentTitle')?.textContent)}|${best.dataset?.sbbFocusId||best.textContent?.slice(0,80)||''}`;
    clearHighlight(best);best.classList.add('sbb-program-now-watching');best.dataset.sbbPlaybackFollow='1';best.setAttribute('aria-current','true');
    if(best!==lastCard||signature!==lastSignature){scrollToThird(ctx,best);lastCard=best;lastSignature=signature;}
    return {reason,kind:ctx.kind,score:bestScore,card:best};
  }
  function schedule(reason='event'){
    if(scheduled)return;scheduled=true;
    const run=()=>reconcile(reason);if(typeof requestAnimationFrame==='function')requestAnimationFrame(run);else setTimeout(run,0);
  }
  function bind(){
    const title=document.getElementById('currentTitle');if(title&&typeof MutationObserver==='function'){titleObserver=new MutationObserver(()=>schedule('title-change'));titleObserver.observe(title,{childList:true,subtree:true,characterData:true});}
    const score=document.getElementById('scoreCells');if(score&&typeof MutationObserver==='function'){observer=new MutationObserver(()=>schedule('score-ribbon-render'));observer.observe(score,{childList:true,subtree:false});}
    for(const name of ['sbb:score-click-selection','sbb:playback-progress-confirmed','sbb:curated-event-identity','sbb:league-context','sbb:browse-layout'])window.addEventListener(name,()=>schedule(name));
    try{window.SBB_SELECTED_EVENT?.subscribe?.(()=>schedule('selected-event'));}catch(_){}
    document.addEventListener('click',event=>{if(event.target?.closest?.('.score-card,[data-curation-index]'))setTimeout(()=>schedule('card-click'),0);},true);
    schedule('startup');
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
  window.SBB_SCORE_RIBBON_PLAYBACK_FOLLOW=Object.freeze({version:VERSION,reconcile:()=>reconcile('manual'),schedule,snapshot:()=>({version:VERSION,lastSignature,lastCard:lastCard?.dataset?.sbbFocusId||clean(lastCard?.textContent).slice(0,80),lastScrollAt})});
})();

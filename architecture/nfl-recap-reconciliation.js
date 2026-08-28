/* Sports Big Board v4.4.8 — recent NFL recap reconciliation.
   A playable Purple is not proof that a recent final NFL game has finished media
   discovery. When Green is absent, proactively run one exact-game refresh so the
   official weekly recap playlist can populate the ribbon BEFORE the viewer clicks
   an inferior/unplayable Purple candidate. */
(() => {
  'use strict';
  if(window.SBB_NFL_RECAP_RECONCILIATION)return;
  const VERSION='1.0';
  const attempted=new Map();
  const completed=new Set();
  const MAX_AGE_DAYS=10;
  const RETRY_AFTER_MS=10*60*1000;
  const POLL_MS=2500;
  let timer=0,runs=0,upgrades=0,lastError='';

  function dateAgeDays(date){
    try{
      const d=new Date(`${String(date).slice(0,10)}T12:00:00`);
      const now=new Date();return Math.floor((now-d)/(24*60*60*1000));
    }catch(_){return 999;}
  }
  function gameKey(match){
    return String(match?.canonicalEventKey||match?.scoreGameKey||match?.eventId||match?.matchId||match?.id||`${match?.away?.name||match?.awayTeam?.displayName||''}-${match?.home?.name||match?.homeTeam?.displayName||''}-${match?.date||''}`);
  }
  function league(match){return String(match?.__sbbLeague||match?.competitionId||match?.league||'').toUpperCase();}
  function tiers(items){
    const out=new Set();
    const seen=new Set();
    for(const item of items||[]){
      let key='';
      try{key=window.SBB_PLAYBACK_TRANSPORTS?.playbackKey?.(item)||String(item?.youtubeId||item?.mediaUrl||item?.id||'');}catch(_){key=String(item?.youtubeId||item?.mediaUrl||item?.id||'');}
      if(key&&seen.has(key))continue;if(key)seen.add(key);
      try{out.add(window.SBB_MEDIA_CLASSIFIER?.tier?.(item)||'blue');}catch(_){out.add('blue');}
    }
    return out;
  }
  async function reconcileMatch(match){
    const key=gameKey(match),now=Date.now(),last=Number(attempted.get(key)||0);
    if(completed.has(key)||(last&&now-last<RETRY_AFTER_MS))return false;
    attempted.set(key,now);runs++;
    const before=tiers(typeof scoreCardPlayableItems==='function'?scoreCardPlayableItems(match):[]);
    if(before.has('green')){completed.add(key);return false;}
    try{
      const rows=await rapidHistoricalGameMedia(match,{force:true});
      const after=tiers([
        ...(Array.isArray(rows)?rows:[]),
        ...(typeof scoreCardPlayableItems==='function'?scoreCardPlayableItems(match):[])
      ]);
      if(after.has('green')){
        upgrades++;completed.add(key);
        try{if(typeof renderScoresFromMatchesCombined==='function')renderScoresFromMatchesCombined(false);}catch(_){}
        try{setFeedNote?.(`${gameLabel(match)} • Quick recap ready`);}catch(_){}
        return true;
      }
      // One successful exact refresh is enough for this page session when there is
      // still no Green. Don't continuously rescan a legitimate Purple-only game.
      completed.add(key);return false;
    }catch(err){
      lastError=`${err?.name||'Error'}: ${err?.message||err}`;
      return false;
    }
  }
  async function sweep(){
    try{
      if(typeof scoreMatchesForDate!=='function'||typeof scoreCardPlayableItems!=='function'||typeof rapidHistoricalGameMedia!=='function')return;
      const date=(typeof scoreBrowseDate!=='undefined'&&scoreBrowseDate)||'';
      const age=dateAgeDays(date);
      if(age<0||age>MAX_AGE_DAYS)return;
      const matches=(scoreMatchesForDate(date)||[]).filter(m=>league(m)==='NFL' && (typeof isFinal!=='function'||isFinal(m)));
      for(const match of matches){
        const items=scoreCardPlayableItems(match)||[],ts=tiers(items);
        // The exact user-reported bad state: Purple exists but a genuine Green
        // does not. Also reconcile Blue-only NFL finals because the weekly recap
        // playlist may have just been created after initial ingestion.
        if(!ts.has('green')&&(ts.has('extended')||ts.has('blue')))await reconcileMatch(match);
      }
    }catch(err){lastError=`${err?.name||'Error'}: ${err?.message||err}`;}
  }
  function start(){
    if(timer)return;
    setTimeout(sweep,700);
    setTimeout(sweep,2200);
    timer=setInterval(sweep,POLL_MS);
  }
  window.SBB_NFL_RECAP_RECONCILIATION=Object.freeze({
    version:VERSION,refresh:sweep,
    snapshot:()=>({runs,upgrades,lastError,attempted:attempted.size,completed:completed.size})
  });
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();

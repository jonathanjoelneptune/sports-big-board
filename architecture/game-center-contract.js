/* v4.1.20 normalized Game Center browser contract.

   Browser memory is HOT. Localhost SQLite is WARM. Provider identity belongs to
   the server: score-ribbon ids are aliases, not assumed MLB/ESPN ids. Every
   request carries the sporting-event fingerprint (date + teams + start/game no.)
   and follows resolvedEventId as soon as localhost publishes it. */
(() => {
  const cache=new Map();
  const clean=v=>v==null?'':String(v).trim();
  const teamHint=v=>clean(v?.abbreviation||v?.abbr||v?.shortName||v?.displayName||v?.name||v);
  const teamKey=v=>teamHint(v).toLowerCase().replace(/[^a-z0-9]/g,'');
  const sleep=(ms,signal)=>new Promise((resolve,reject)=>{
    if(signal?.aborted)return reject(signal.reason||new DOMException('Selection changed','AbortError'));
    const t=setTimeout(done,ms);
    function done(){signal?.removeEventListener?.('abort',abort);resolve();}
    function abort(){clearTimeout(t);signal?.removeEventListener?.('abort',abort);reject(signal.reason||new DOMException('Selection changed','AbortError'));}
    signal?.addEventListener?.('abort',abort,{once:true});
  });
  function eventHints(eventLike){
    const parts=Array.isArray(eventLike?.participants)?eventLike.participants:[];
    const away=eventLike?.awayTeam||eventLike?.away||parts.find(x=>x?.side==='away')||parts[0]||{};
    const home=eventLike?.homeTeam||eventLike?.home||parts.find(x=>x?.side==='home')||parts[1]||{};
    const rawDate=clean(eventLike?.scheduledGameDate||eventLike?.__sbbDate||eventLike?.gameDate||eventLike?.scheduledAt||eventLike?.date);
    const start=clean(eventLike?.scheduledAt||eventLike?.date||eventLike?.startDate||eventLike?.startTime);
    const gameNumber=Number(eventLike?.gameNumber||eventLike?.doubleHeaderGame||0)||0;
    return {date:rawDate.slice(0,10),away:teamHint(away),home:teamHint(home),start,gameNumber,provider:clean(eventLike?.gameCenterProviderHint||eventLike?.scoreProvider||eventLike?.provider)};
  }
  function identity(eventLike){
    const competition=clean(eventLike?.competitionId||eventLike?.__sbbLeague||eventLike?.league).toUpperCase();
    const hints=eventHints(eventLike);
    const requestId=clean(eventLike?.gameCenterEventId||eventLike?.scoreEventId||eventLike?.gamePk||eventLike?.eventId||eventLike?.matchId||eventLike?.id);
    const fingerprint=[competition,hints.date,teamKey(hints.away),teamKey(hints.home),hints.gameNumber||''].join('|');
    const key=(hints.date&&hints.away&&hints.home)?fingerprint:(window.SBB_EVENT_IDENTITY?.key?.(eventLike)||`${competition}:${requestId}`);
    return {competition,eventId:requestId,key,...hints};
  }
  async function get(eventLike,{force=false,signal=null,timeoutMs=30000}={}){
    const ident=identity(eventLike); const {competition,key,date,away,home,start,gameNumber,provider}=ident;
    let requestId=ident.eventId;
    if(!competition||!requestId)throw new Error('Game Center requires a competition and event identity');
    const hit=cache.get(key),status=clean(eventLike?.status);
    // Partial Game Centers are deliberately short-lived in browser memory. The
    // server may be enriching a teams-only Highlightly shell with MLB/ESPN data;
    // keeping that shell HOT for five minutes made the UI look randomly incomplete.
    const hitPartial=!!(hit?.data?.coverage?.complete===false||hit?.data?.partial||hit?.data?.quality?.level&&hit.data.quality.level!=='rich');
    const historicalFinal=!!date&&date<localDateISO(0)&&/final|finished|game over|completed|complete/i.test(status);
    const ttl=hitPartial?1500:(/live|progress|quarter|half|period|inning/i.test(status)?10000:(historicalFinal?24*60*60*1000:5*60*1000));
    if(!force&&hit&&Date.now()-hit.at<ttl)return hit.data;
    const started=performance.now();let first=true;
    while(true){
      if(signal?.aborted)throw signal.reason||new DOMException('Selection changed','AbortError');
      const qs=new URLSearchParams(); if(force&&first)qs.set('refresh','1'); qs.set('async','1');
      if(date)qs.set('date',date);if(away)qs.set('away',away);if(home)qs.set('home',home);if(start)qs.set('start',start);if(gameNumber)qs.set('gameNumber',String(gameNumber));if(provider)qs.set('provider',provider);
      const url=`/api/events/${encodeURIComponent(competition)}/${encodeURIComponent(requestId)}/game-center?${qs.toString()}`;
      const response=await fetch(url,{cache:'no-store',signal});
      let payload={};try{payload=await response.json();}catch(_){ }
      if(payload?.resolvedEventId)requestId=String(payload.resolvedEventId);
      if(response.status===202||payload?.pending){
        if(performance.now()-started>=timeoutMs){if(hit)return hit.data;throw new Error('Game Center is still preparing. Tap Retry in a moment.');}
        await sleep(Math.max(300,Math.min(1000,Number(payload?.retryAfterMs)||500)),signal);first=false;force=false;continue;
      }
      if(!response.ok)throw new Error(payload?.message||`Game Center HTTP ${response.status}`);
      const raw=payload?.data||payload;
      const normalized=window.SBB_CORE?.gameCenter?window.SBB_CORE.gameCenter(raw,{competitionId:competition,eventId:requestId}):raw;
      cache.set(key,{at:Date.now(),data:normalized,serverCache:payload?.cache||'',resolvedEventId:requestId});
      if(requestId)cache.set(`${competition}:provider:${requestId}`,{at:Date.now(),data:normalized,serverCache:payload?.cache||'',resolvedEventId:requestId});
      return normalized;
    }
  }
  function peek(eventLike){const ident=identity(eventLike);return cache.get(ident.key)?.data||cache.get(`${ident.competition}:provider:${ident.eventId}`)?.data||null;}
  function clear(){cache.clear();}
  function localDateISO(offset=0){const d=new Date();d.setDate(d.getDate()+offset);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
  async function prewarmSportsDays(){
    try{
      const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone||'Etc/UTC';
      const utcOffsetMinutes=-new Date().getTimezoneOffset();
      const qs=new URLSearchParams({today:localDateISO(0),yesterday:localDateISO(-1),timezone,utcOffsetMinutes:String(utcOffsetMinutes),clientDate:localDateISO(0)});
      await fetch(`/api/game-center/prewarm?${qs.toString()}`,{cache:'no-store'});
    }catch(_){ }
  }
  if(typeof document!=='undefined'){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>prewarmSportsDays(),{once:true});else setTimeout(prewarmSportsDays,0);}
  window.SBB_GAME_CENTER=Object.freeze({version:'1.8',get,peek,clear,identity,eventHints,prewarmSportsDays});
})();

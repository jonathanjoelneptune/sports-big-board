/* Sports Big Board v4.7.20 — normalized Game Center browser contract.

   Browser memory is HOT. Localhost/cloud SQLite is WARM. Provider identity belongs
   to the server: score-ribbon ids are aliases, not assumed provider ids. v4.7.26
   stability adds single-flight ownership, fetch-level hard timeouts, bounded 202
   preparation polling, partial-final cooldown, and payload-size guards so one bad
   Game Center can never monopolize the browser or create an infinite loading loop.
*/
(() => {
  'use strict';
  const PREVIOUS=window.SBB_GAME_CENTER;
  if(PREVIOUS?.watchdogVersion==='v4726')return;

  const cache=new Map();
  const inflight=new Map();
  const cooldown=new Map();
  const diagnostics={requests:0,cacheHits:0,coalesced:0,timeouts:0,pendingTimeouts:0,httpErrors:0,aborts:0,largestPayloadBytes:0,last:[]};
  const clean=v=>v==null?'':String(v).trim();
  const teamHint=v=>clean(v?.abbreviation||v?.abbr||v?.shortName||v?.displayName||v?.name||v);
  const teamKey=v=>teamHint(v).toLowerCase().replace(/[^a-z0-9]/g,'');
  const sleep=(ms,signal)=>new Promise((resolve,reject)=>{if(signal?.aborted)return reject(signal.reason||new DOMException('Selection changed','AbortError'));const t=setTimeout(done,ms);function done(){signal?.removeEventListener?.('abort',abort);resolve();}function abort(){clearTimeout(t);signal?.removeEventListener?.('abort',abort);reject(signal.reason||new DOMException('Selection changed','AbortError'));}signal?.addEventListener?.('abort',abort,{once:true});});
  const round=v=>Number.isFinite(Number(v))?Math.round(Number(v)*10)/10:null;
  const record=row=>{diagnostics.last.push(row);if(diagnostics.last.length>40)diagnostics.last.splice(0,diagnostics.last.length-40);};
  const byteSize=value=>{try{return new Blob([JSON.stringify(value)]).size;}catch(_){try{return JSON.stringify(value).length;}catch(__){return 0;}}};

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
    const requestId=clean(eventLike?.gameCenterEventId||eventLike?.scoreEventId||eventLike?.espnEventId||eventLike?.gamePk||eventLike?.eventId||eventLike?.matchId||eventLike?.id);
    const fingerprint=[competition,hints.date,teamKey(hints.away),teamKey(hints.home),hints.gameNumber||''].join('|');
    const key=(hints.date&&hints.away&&hints.home)?fingerprint:(window.SBB_EVENT_IDENTITY?.key?.(eventLike)||`${competition}:${requestId}`);
    return {competition,eventId:requestId,key,...hints};
  }
  function localDateISO(offset=0){const d=new Date();d.setDate(d.getDate()+offset);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}

  function linkedController(parentSignal,timeoutMs){
    const c=new AbortController();let parentAbort=null;
    if(parentSignal){parentAbort=()=>{try{c.abort(parentSignal.reason||new DOMException('Selection changed','AbortError'));}catch(_){}};if(parentSignal.aborted)parentAbort();else parentSignal.addEventListener('abort',parentAbort,{once:true});}
    const timer=setTimeout(()=>{try{c.abort(new DOMException(`Game Center request exceeded ${timeoutMs}ms`,'TimeoutError'));}catch(_){}},timeoutMs);
    return {controller:c,cleanup(){clearTimeout(timer);if(parentAbort)parentSignal?.removeEventListener?.('abort',parentAbort);}};
  }

  async function fetchBounded(url,{signal,timeoutMs=6500}={}){
    const linked=linkedController(signal,Math.max(1200,Math.min(7000,Number(timeoutMs)||6500)));
    try{return await fetch(url,{cache:'no-store',signal:linked.controller.signal});}
    catch(err){if(err?.name==='TimeoutError'||/exceeded|timeout/i.test(clean(err?.message))){diagnostics.timeouts++;}else if(err?.name==='AbortError'){diagnostics.aborts++;}throw err;}
    finally{linked.cleanup();}
  }

  function boundPayload(data){
    if(!data||typeof data!=='object')return data;
    // These caps are deliberately generous enough to preserve a full game while
    // preventing a malformed provider response from generating tens of thousands
    // of DOM nodes synchronously in Game Center renderers.
    if(Array.isArray(data.timeline)&&data.timeline.length>500)data.timeline=data.timeline.slice(-500);
    if(Array.isArray(data.scoringPlays)&&data.scoringPlays.length>150)data.scoringPlays=data.scoringPlays.slice(-150);
    if(Array.isArray(data.winProbability)&&data.winProbability.length>240)data.winProbability=data.winProbability.filter((_,i,a)=>i===a.length-1||i%Math.ceil(a.length/240)===0).slice(-240);
    const board=data.scoreboard||{};
    if(Array.isArray(board.winProbability)&&board.winProbability.length>240)board.winProbability=board.winProbability.filter((_,i,a)=>i===a.length-1||i%Math.ceil(a.length/240)===0).slice(-240);
    if(Array.isArray(data.playerStatSections))for(const sec of data.playerStatSections)if(Array.isArray(sec?.rows)&&sec.rows.length>120)sec.rows=sec.rows.slice(0,120);
    return data;
  }

  async function request(eventLike,{force=false,signal=null,timeoutMs=9000}={}){
    if(window.SBB_MEDIA_SCOPE?.isCollection?.(eventLike))throw new Error('Game Center is unavailable for collection/roundup media');
    const ident=identity(eventLike),{competition,key,date,away,home,start,gameNumber,provider}=ident;let requestId=ident.eventId;
    if(!competition||!requestId)throw new Error('Game Center requires a competition and event identity');
    const started=performance.now(),overallLimit=Math.max(2500,Math.min(10000,Number(timeoutMs)||9000));
    const hit=cache.get(key),status=clean(eventLike?.status),hitPartial=!!(hit?.data?.coverage?.complete===false||hit?.data?.partial||hit?.data?.quality?.level&&hit.data.quality.level!=='rich');
    const historicalFinal=!!date&&date<localDateISO(0)&&/final|finished|game over|completed|complete/i.test(status);
    const ttl=hitPartial?(historicalFinal?30000:5000):(/live|progress|quarter|half|period|inning/i.test(status)?10000:(historicalFinal?24*60*60*1000:5*60*1000));
    if(!force&&hit&&Date.now()-hit.at<ttl){diagnostics.cacheHits++;return hit.data;}
    const cool=cooldown.get(key);if(!force&&cool&&Date.now()<cool.until&&hit){diagnostics.cacheHits++;return hit.data;}

    let first=true,polls=0;
    while(true){
      if(signal?.aborted)throw signal.reason||new DOMException('Selection changed','AbortError');
      if(performance.now()-started>=overallLimit){diagnostics.pendingTimeouts++;cooldown.set(key,{until:Date.now()+30000,reason:'overall-timeout'});if(hit)return hit.data;throw new Error('Game Center preparation exceeded the browser safety limit. Retry is available; the board remains responsive.');}
      const qs=new URLSearchParams();if(force&&first)qs.set('refresh','1');qs.set('async','1');if(date)qs.set('date',date);if(away)qs.set('away',away);if(home)qs.set('home',home);if(start)qs.set('start',start);if(gameNumber)qs.set('gameNumber',String(gameNumber));if(provider)qs.set('provider',provider);
      const url=`/api/events/${encodeURIComponent(competition)}/${encodeURIComponent(requestId)}/game-center?${qs.toString()}`;
      const remaining=Math.max(1200,overallLimit-(performance.now()-started));
      const response=await fetchBounded(url,{signal,timeoutMs:Math.min(6000,remaining)});diagnostics.requests++;
      let payload={};try{payload=await response.json();}catch(_){}
      if(payload?.resolvedEventId)requestId=String(payload.resolvedEventId);
      if(response.status===202||payload?.pending){
        polls++;
        if(polls>=8){diagnostics.pendingTimeouts++;cooldown.set(key,{until:Date.now()+30000,reason:'pending-loop'});if(hit)return hit.data;throw new Error(`Game Center provider remained pending after ${polls} checks. Retry later.`);}
        await sleep(Math.max(350,Math.min(1000,Number(payload?.retryAfterMs)||650)),signal);first=false;force=false;continue;
      }
      if(!response.ok){diagnostics.httpErrors++;throw new Error(payload?.message||`Game Center HTTP ${response.status}`);}
      const raw=payload?.data||payload;
      let normalized=window.SBB_CORE?.gameCenter?window.SBB_CORE.gameCenter(raw,{competitionId:competition,eventId:requestId}):raw;
      normalized=boundPayload(normalized);
      const bytes=byteSize(normalized);diagnostics.largestPayloadBytes=Math.max(diagnostics.largestPayloadBytes,bytes);
      cache.set(key,{at:Date.now(),data:normalized,serverCache:payload?.cache||'',resolvedEventId:requestId});
      if(requestId)cache.set(`${competition}:provider:${requestId}`,{at:Date.now(),data:normalized,serverCache:payload?.cache||'',resolvedEventId:requestId});
      if(normalized?.coverage?.complete===false&&historicalFinal)cooldown.set(key,{until:Date.now()+30000,reason:'final-partial'});else cooldown.delete(key);
      record({at:Date.now(),key,competition,eventId:requestId,elapsedMs:round(performance.now()-started),polls,bytes,complete:normalized?.coverage?.complete!==false});
      return normalized;
    }
  }

  async function get(eventLike,opts={}){
    const ident=identity(eventLike),key=ident.key;
    if(!opts.force&&inflight.has(key)){diagnostics.coalesced++;return inflight.get(key);}
    const promise=request(eventLike,opts).finally(()=>{if(inflight.get(key)===promise)inflight.delete(key);});
    inflight.set(key,promise);return promise;
  }
  function peek(eventLike){const ident=identity(eventLike);return cache.get(ident.key)?.data||cache.get(`${ident.competition}:provider:${ident.eventId}`)?.data||null;}
  function clear(){cache.clear();cooldown.clear();}
  async function prewarmSportsDays(){try{const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone||'Etc/UTC';const utcOffsetMinutes=-new Date().getTimezoneOffset();const qs=new URLSearchParams({today:localDateISO(0),yesterday:localDateISO(-1),timezone,utcOffsetMinutes:String(utcOffsetMinutes),clientDate:localDateISO(0)});await fetchBounded(`/api/game-center/prewarm?${qs.toString()}`,{timeoutMs:5000});}catch(_){} }
  function snapshot(){return {version:'1.8',watchdogVersion:'v4726',cacheEntries:cache.size,inflight:inflight.size,cooldowns:cooldown.size,...JSON.parse(JSON.stringify(diagnostics))};}
  if(typeof document!=='undefined'){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>prewarmSportsDays(),{once:true});else setTimeout(prewarmSportsDays,0);}
  window.SBB_GAME_CENTER=Object.freeze({version:'1.8',watchdogVersion:'v4726',get,peek,clear,identity,eventHints,prewarmSportsDays,snapshot});
})();

/* Sports Big Board v5.1.19 ScoreDateStore — canonical browser date read cache.

   The backend Day State / Competition Registry path is the event authority. This
   store never promotes a thin/preview transport response into canonical truth and
   never lets a transient empty response erase a populated date. Repeated canonical
   rows are merged by stable event identity so score/status freshness can advance
   without stripping richer identity/presentation fields from the resident Event.
*/
(() => {
  'use strict';
  if(window.SBB_SCORE_DATE?.architectureVersion==='1.3-v5119')return;

  const listeners=new Set();
  const days=new Map();
  const loading=new Set();
  const stats={blockedEmptyReplacements:0,rejectedNonAuthoritative:0,mergedEvents:0};
  const cleanDate=value=>String(value||'').slice(0,10);

  function localDateISO(offset=0){
    const d=new Date();d.setHours(12,0,0,0);d.setDate(d.getDate()+Number(offset||0));
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  }
  function normalizeDate(value){
    const raw=cleanDate(value);
    // Future scheduled dates are canonical inventory too; do not clamp future scheduled dates to today.
    if(/^\d{4}-\d{2}-\d{2}$/.test(raw))return raw;
    return localDateISO(0);
  }
  let browseDate=localDateISO(0),playbackDate=localDateISO(0);

  function ensure(date){
    date=normalizeDate(date);
    if(!days.has(date))days.set(date,{matches:new Map(),matchMeta:new Map(),media:new Map(),loadedAt:0,mediaLoadedAt:0});
    return days.get(date);
  }
  function notify(action,date,extra={}){
    const snap=snapshot();
    for(const fn of listeners){try{fn(snap,{action,date,...extra});}catch(e){console.warn('[SBB ScoreDateStore listener]',e);}}
  }
  function setBrowseDate(value,{notifyListeners=true}={}){
    const next=normalizeDate(value);browseDate=next;if(notifyListeners)notify('browse',next);return next;
  }
  function setPlaybackDate(value,{notifyListeners=true}={}){
    const next=normalizeDate(value);playbackDate=next;if(notifyListeners)notify('playback',next);return next;
  }

  const identityKeys=['scoreEventId','matchId','espnEventId','gamePk','canonicalEventId','eventId','id'];
  function explicitAliases(event){
    if(!event||typeof event!=='object')return [];
    return [...new Set(identityKeys.map(key=>event[key]).filter(value=>value!==undefined&&value!==null&&String(value)!=='').map(String))];
  }
  function eventFingerprint(event){
    if(!event||typeof event!=='object')return '';
    const away=event.awayTeam||event.away||{},home=event.homeTeam||event.home||{};
    const name=x=>String(x?.displayName||x?.name||x?.shortName||x?.abbreviation||x||'').toLowerCase().replace(/[^a-z0-9]+/g,'');
    const date=String(event.__sbbDate||event.gameDate||event.date||event.scheduledAt||'').slice(0,10);
    const start=String(event.scheduledAt||event.startDate||event.startTime||'').slice(0,16);
    return date&&name(away)&&name(home)?`${date}|${name(away)}|${name(home)}|${Number(event.gameNumber||0)||''}|${start}`:'';
  }
  function eventIdentity(event){return explicitAliases(event)[0]||eventFingerprint(event);}
  const empty=v=>v===undefined||v===null||v==='';
  function mergeValue(prior,next,depth=0){
    if(next===undefined||next===null)return prior;
    if(Array.isArray(next))return next.length?next:(Array.isArray(prior)&&prior.length?prior:next);
    if(next&&typeof next==='object'&&!Array.isArray(next)&&depth<3){
      const out={...(prior&&typeof prior==='object'&&!Array.isArray(prior)?prior:{})};
      for(const [k,v] of Object.entries(next))out[k]=mergeValue(out[k],v,depth+1);
      return out;
    }
    if(next===''&&!empty(prior))return prior;
    return next;
  }
  function mergeEvent(prior,next){
    if(!prior||typeof prior!=='object')return next;
    if(!next||typeof next!=='object')return prior;
    stats.mergedEvents++;
    return mergeValue(prior,next,0);
  }
  function mergeRows(priorRows,nextRows){
    const byAlias=new Map(),aliasAmbiguous=new Set(),byFingerprint=new Map(),fingerprintAmbiguous=new Set();
    for(const row of priorRows||[]){
      for(const alias of explicitAliases(row)){
        if(byAlias.has(alias)&&byAlias.get(alias)!==row){aliasAmbiguous.add(alias);byAlias.delete(alias);}else if(!aliasAmbiguous.has(alias))byAlias.set(alias,row);
      }
      const fp=eventFingerprint(row);
      if(fp){if(byFingerprint.has(fp)&&byFingerprint.get(fp)!==row){fingerprintAmbiguous.add(fp);byFingerprint.delete(fp);}else if(!fingerprintAmbiguous.has(fp))byFingerprint.set(fp,row);}
    }
    return (nextRows||[]).map(row=>{
      let prior=null;
      for(const alias of explicitAliases(row)){if(!aliasAmbiguous.has(alias)&&byAlias.has(alias)){prior=byAlias.get(alias);break;}}
      if(!prior){const fp=eventFingerprint(row);if(fp&&!fingerprintAmbiguous.has(fp))prior=byFingerprint.get(fp)||null;}
      return prior?mergeEvent(prior,row):row;
    });
  }
  function registryCompetition(league){
    const lg=String(league||'').toUpperCase();
    try{return (window.SBB_FRONTEND_REGISTRY?.snapshot?.().competitions||[]).find(row=>String(row?.id||'').toUpperCase()===lg)||null;}catch(_){return null;}
  }
  function projectCompetitionMetadata(row,league){
    if(!row||typeof row!=='object')return row;
    const reg=registryCompetition(league);if(!reg)return row;
    const out={...row};const sport=String(reg.sportId||'').trim();
    if(sport&&(!out.sportId||['sports','multi-sport'].includes(String(out.sportId).toLowerCase())))out.sportId=sport;
    if(reg.name&&(!out.competitionName||String(out.competitionName).toUpperCase()===String(league).toUpperCase()))out.competitionName=reg.name;
    if(String(out.sportId||'').toLowerCase()==='tennis'&&!out.gameCenterProviderHint)out.gameCenterProviderHint='tennis';
    return out;
  }
  function projectedRows(rows,league){return (rows||[]).map(row=>projectCompetitionMetadata(row,league));}

  function setMatches(date,league,rows,meta={}){
    date=normalizeDate(date);const day=ensure(date);const lg=String(league||'SPORTS').toUpperCase();
    const prior=(day.matches.get(lg)||[]).slice();const next=Array.isArray(rows)?rows.slice():[];

    // Preview/score-only transports may be rendered by their own temporary UI,
    // but they are never allowed to become the canonical ScoreDateStore snapshot.
    if(meta.authoritative===false||meta.preview===true||meta.scoreOnly===true||meta.thin===true){
      stats.rejectedNonAuthoritative++;
      return prior;
    }
    // Empty is a valid authoritative result only when the producer explicitly says
    // the league/day was confirmed empty. A timeout or incomplete projection cannot
    // erase a last-known-good populated date.
    if(!next.length&&prior.length&&!meta.confirmedEmpty&&!meta.allowEmptyReplace){
      stats.blockedEmptyReplacements++;
      recordMatchFailure(date,lg,'transient empty score projection blocked',{source:meta.source||'score-date-store-v5119'});
      return prior;
    }

    const merged=mergeRows(prior,next);
    day.matches.set(lg,merged);
    day.matchMeta.set(lg,{status:merged.length?'READY':'EMPTY',source:String(meta.source||''),error:'',updatedAt:Date.now(),authoritative:true,confirmedEmpty:!!meta.confirmedEmpty});
    day.loadedAt=Date.now();notify('matches',date,{league:lg,source:meta.source||''});return projectedRows(merged,lg);
  }
  function recordMatchFailure(date,league,error,meta={}){
    date=normalizeDate(date);const day=ensure(date);const lg=String(league||'SPORTS').toUpperCase();const prior=day.matchMeta.get(lg)||{};
    day.matchMeta.set(lg,{...prior,status:'ERROR',source:String(meta.source||prior.source||''),error:String(error?.message||error||'score load failed'),failedAt:Date.now(),updatedAt:Number(prior.updatedAt||0),authoritative:prior.authoritative===true});
    notify('match-error',date,{league:lg});return (day.matches.get(lg)||[]).slice();
  }
  function setMedia(date,league,rows){
    date=normalizeDate(date);const day=ensure(date);const lg=String(league||'SPORTS').toUpperCase();
    day.media.set(lg,Array.isArray(rows)?rows.slice():[]);day.mediaLoadedAt=Date.now();notify('media',date,{league:lg});return day.media.get(lg).slice();
  }
  function addMedia(date,league,rows){
    const merged=[...media(date,league),...(Array.isArray(rows)?rows:[])],seen=new Set(),dedup=[];
    for(const item of merged){const key=String(item?.assetKey||item?.id||item?.youtubeId||item?.mediaUrl||item?.externalUrl||JSON.stringify(item));if(seen.has(key))continue;seen.add(key);dedup.push(item);}
    return setMedia(date,league,dedup);
  }
  function matches(date,league){const lg=String(league||'SPORTS').toUpperCase(),day=days.get(normalizeDate(date));return day?projectedRows(day.matches.get(lg)||[],lg):[];}
  function media(date,league){const day=days.get(normalizeDate(date));return day?(day.media.get(String(league||'SPORTS').toUpperCase())||[]).slice():[];}
  function allMatches(date){const day=days.get(normalizeDate(date));return day?[...day.matches.entries()].flatMap(([lg,rows])=>projectedRows(rows,lg)):[];}
  function allMedia(date){const day=days.get(normalizeDate(date));return day?[...day.media.values()].flat():[];}
  function hasMatchesSnapshot(date){const day=days.get(normalizeDate(date));return !!day&&day.matches.size>0;}
  function hasLeagueMatchesSnapshot(date,league){const day=days.get(normalizeDate(date));return !!day&&day.matches.has(String(league||'SPORTS').toUpperCase());}
  function loadedMatchLeagues(date){const day=days.get(normalizeDate(date));return day?[...day.matches.keys()]:[];}
  function hasLeagueMediaSnapshot(date,league){const day=days.get(normalizeDate(date));return !!day&&day.media.has(String(league||'SPORTS').toUpperCase());}
  function dateHealth(date){
    date=normalizeDate(date);const day=days.get(date);
    if(!day)return {date,games:0,authoritativeLeagues:0,errorLeagues:0,emptyLeagues:0,readyLeagues:0,errors:[],hasSnapshot:false,...stats};
    let games=0,authoritativeLeagues=0,errorLeagues=0,emptyLeagues=0,readyLeagues=0;const errors=[];
    for(const [lg,rows] of day.matches.entries()){games+=(rows||[]).length;authoritativeLeagues++;if((rows||[]).length)readyLeagues++;else emptyLeagues++;}
    for(const [lg,meta] of day.matchMeta.entries())if(meta?.status==='ERROR'){errorLeagues++;errors.push({league:lg,error:String(meta.error||''),source:String(meta.source||'')});}
    return {date,games,authoritativeLeagues,errorLeagues,emptyLeagues,readyLeagues,errors,hasSnapshot:day.matches.size>0,loadedAt:day.loadedAt||0,...stats};
  }
  function markLoading(date,on=true){date=normalizeDate(date);if(on)loading.add(date);else loading.delete(date);notify(on?'loading':'loaded',date);}
  function isLoading(date){return loading.has(normalizeDate(date));}
  function snapshot(){return {browseDate,playbackDate,today:localDateISO(0),isBrowsingToday:browseDate===localDateISO(0),isPlayingToday:playbackDate===localDateISO(0)};}
  function subscribe(fn,{emitCurrent=false}={}){if(typeof fn!=='function')return()=>{};listeners.add(fn);if(emitCurrent)fn(snapshot(),{action:'snapshot'});return()=>listeners.delete(fn);}

  window.SBB_SCORE_DATE=Object.freeze({
    version:'1.1',architectureVersion:'1.3-v5119',releaseVersion:'5.1.19',localDateISO,normalizeDate,eventIdentity,setBrowseDate,setPlaybackDate,
    setMatches,recordMatchFailure,setMedia,addMedia,matches,media,allMatches,allMedia,
    hasMatchesSnapshot,hasLeagueMatchesSnapshot,loadedMatchLeagues,hasLeagueMediaSnapshot,
    dateHealth,markLoading,isLoading,snapshot,subscribe,
    diagnostics:()=>({...stats,dates:days.size})
  });
})();

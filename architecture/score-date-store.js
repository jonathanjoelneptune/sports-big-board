/* Sports Big Board v5.0.4 ScoreDateStore — last-known-good score inventory.
   Date browsing is application context, not playback ownership. Past, current,
   and future scheduled dates are all valid score-state keys. Playback keeps its
   own date and does not constrain ribbon browsing.
*/
(() => {
  const listeners=new Set();
  const days=new Map();
  const cleanDate=value=>String(value||'').slice(0,10);
  function localDateISO(offset=0){
    const d=new Date(); d.setHours(12,0,0,0); d.setDate(d.getDate()+Number(offset||0));
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  }
  function normalizeDate(value){
    const raw=cleanDate(value);
    if(!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return localDateISO(0);
    // v4.7.14: do not clamp future scheduled dates to today. The registry and
    // Day State determine whether the date has games; storage preserves the date.
    return raw;
  }
  let browseDate=localDateISO(0);
  let playbackDate=localDateISO(0);
  const loading=new Set();

  function ensure(date){
    date=normalizeDate(date);
    if(!days.has(date)) days.set(date,{matches:new Map(),matchMeta:new Map(),media:new Map(),loadedAt:0,mediaLoadedAt:0});
    return days.get(date);
  }
  function notify(action,date){
    const snap=snapshot();
    for(const fn of listeners){
      try{fn(snap,{action,date});}catch(e){console.warn('[SBB ScoreDateStore listener]',e);}
    }
  }
  function setBrowseDate(value,{notifyListeners=true}={}){
    const next=normalizeDate(value); browseDate=next;
    if(notifyListeners) notify('browse',next);
    return next;
  }
  function setPlaybackDate(value,{notifyListeners=true}={}){
    const next=normalizeDate(value); playbackDate=next;
    if(notifyListeners) notify('playback',next);
    return next;
  }
  function setMatches(date,league,rows,meta={}){
    date=normalizeDate(date);
    const day=ensure(date);
    const lg=String(league||'SPORTS').toUpperCase();
    const next=Array.isArray(rows)?rows.slice():[];
    day.matches.set(lg,next);
    day.matchMeta.set(lg,{status:next.length?'READY':'EMPTY',source:String(meta.source||''),error:'',updatedAt:Date.now(),authoritative:meta.authoritative!==false});
    day.loadedAt=Date.now();
    notify('matches',date);
    return next.slice();
  }
  function recordMatchFailure(date,league,error,meta={}){
    date=normalizeDate(date);
    const day=ensure(date);
    const lg=String(league||'SPORTS').toUpperCase();
    const prior=day.matchMeta.get(lg)||{};
    // v5.0.4 invariant: transport/provider failure is not an empty scoreboard.
    // Preserve the last known-good rows and record failure metadata separately.
    day.matchMeta.set(lg,{...prior,status:'ERROR',source:String(meta.source||prior.source||''),error:String(error?.message||error||'score load failed'),failedAt:Date.now(),updatedAt:Number(prior.updatedAt||0),authoritative:prior.authoritative===true});
    notify('match-error',date);
    return (day.matches.get(lg)||[]).slice();
  }
  function setMedia(date,league,rows){
    date=normalizeDate(date);
    const day=ensure(date);
    const lg=String(league||'SPORTS').toUpperCase();
    day.media.set(lg,Array.isArray(rows)?rows.slice():[]);
    day.mediaLoadedAt=Date.now();
    notify('media',date);
    return day.media.get(lg);
  }
  function addMedia(date,league,rows){
    const prior=media(date,league);
    const merged=[...prior,...(Array.isArray(rows)?rows:[])];
    const seen=new Set(),dedup=[];
    for(const item of merged){
      const key=String(item?.id||item?.youtubeId||item?.mediaUrl||item?.externalUrl||JSON.stringify(item));
      if(seen.has(key))continue;
      seen.add(key);dedup.push(item);
    }
    return setMedia(date,league,dedup);
  }
  function matches(date,league){
    const day=days.get(normalizeDate(date));
    if(!day)return [];
    return (day.matches.get(String(league||'SPORTS').toUpperCase())||[]).slice();
  }
  function media(date,league){
    const day=days.get(normalizeDate(date));
    if(!day)return [];
    return (day.media.get(String(league||'SPORTS').toUpperCase())||[]).slice();
  }
  function allMatches(date){
    const day=days.get(normalizeDate(date));
    return day?[...day.matches.values()].flat():[];
  }
  function allMedia(date){
    const day=days.get(normalizeDate(date));
    return day?[...day.media.values()].flat():[];
  }
  function hasMatchesSnapshot(date){
    const day=days.get(normalizeDate(date));
    return !!day&&day.matches.size>0;
  }
  function hasLeagueMatchesSnapshot(date,league){
    const day=days.get(normalizeDate(date));
    return !!day&&day.matches.has(String(league||'SPORTS').toUpperCase());
  }
  function loadedMatchLeagues(date){
    const day=days.get(normalizeDate(date));
    return day?[...day.matches.keys()]:[];
  }
  function dateHealth(date){
    date=normalizeDate(date);const day=days.get(date);
    if(!day)return {date,games:0,authoritativeLeagues:0,errorLeagues:0,emptyLeagues:0,readyLeagues:0,errors:[],hasSnapshot:false};
    let games=0,authoritativeLeagues=0,errorLeagues=0,emptyLeagues=0,readyLeagues=0;const errors=[];
    for(const [lg,rows] of day.matches.entries()){games+=(rows||[]).length;authoritativeLeagues++;if((rows||[]).length)readyLeagues++;else emptyLeagues++;}
    for(const [lg,meta] of day.matchMeta.entries())if(meta?.status==='ERROR'){errorLeagues++;errors.push({league:lg,error:String(meta.error||''),source:String(meta.source||'')});}
    return {date,games,authoritativeLeagues,errorLeagues,emptyLeagues,readyLeagues,errors,hasSnapshot:day.matches.size>0,loadedAt:day.loadedAt||0};
  }
  function hasLeagueMediaSnapshot(date,league){
    const day=days.get(normalizeDate(date));
    return !!day&&day.media.has(String(league||'SPORTS').toUpperCase());
  }
  function markLoading(date,on=true){
    date=normalizeDate(date);
    if(on)loading.add(date);else loading.delete(date);
    notify(on?'loading':'loaded',date);
  }
  function isLoading(date){return loading.has(normalizeDate(date));}
  function snapshot(){
    return {
      browseDate,playbackDate,today:localDateISO(0),
      isBrowsingToday:browseDate===localDateISO(0),
      isPlayingToday:playbackDate===localDateISO(0)
    };
  }
  function subscribe(fn,{emitCurrent=false}={}){
    if(typeof fn!=='function')return()=>{};
    listeners.add(fn);
    if(emitCurrent)fn(snapshot(),{action:'snapshot'});
    return()=>listeners.delete(fn);
  }

  window.SBB_SCORE_DATE=Object.freeze({
    version:'1.1',
    localDateISO,normalizeDate,setBrowseDate,setPlaybackDate,
    setMatches,recordMatchFailure,setMedia,addMedia,matches,media,allMatches,allMedia,
    hasMatchesSnapshot,hasLeagueMatchesSnapshot,loadedMatchLeagues,
    hasLeagueMediaSnapshot,dateHealth,markLoading,isLoading,snapshot,subscribe
  });
})();

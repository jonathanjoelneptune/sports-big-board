/* v4.1.11 ScoreDateStore
   Date browsing is application context, not playback ownership. The score ribbon
   can browse any past day while the currently playing program keeps its own date.
   Historical score/media snapshots are session-resident and immutable enough to
   reuse aggressively. */
(() => {
  const listeners=new Set();
  const days=new Map();
  const cleanDate=value=>String(value||'').slice(0,10);
  function localDateISO(offset=0){
    const d=new Date(); d.setHours(12,0,0,0); d.setDate(d.getDate()+Number(offset||0));
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  }
  function normalizeDate(value){
    const raw=cleanDate(value); if(!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return localDateISO(0);
    return raw>localDateISO(0)?localDateISO(0):raw;
  }
  let browseDate=localDateISO(0);
  let playbackDate=localDateISO(0);
  const loading=new Set();
  function ensure(date){
    date=normalizeDate(date);
    if(!days.has(date)) days.set(date,{matches:new Map(),media:new Map(),loadedAt:0,mediaLoadedAt:0});
    return days.get(date);
  }
  function notify(action,date){
    const snap=snapshot();
    for(const fn of listeners){try{fn(snap,{action,date});}catch(e){console.warn('[SBB ScoreDateStore listener]',e);}}
  }
  function setBrowseDate(value,{notifyListeners=true}={}){
    const next=normalizeDate(value); browseDate=next; if(notifyListeners) notify('browse',next); return next;
  }
  function setPlaybackDate(value,{notifyListeners=true}={}){
    const next=normalizeDate(value); playbackDate=next; if(notifyListeners) notify('playback',next); return next;
  }
  function setMatches(date,league,rows){
    date=normalizeDate(date); const day=ensure(date); const lg=String(league||'SPORTS').toUpperCase();
    day.matches.set(lg,Array.isArray(rows)?rows.slice():[]); day.loadedAt=Date.now(); notify('matches',date); return day.matches.get(lg);
  }
  function setMedia(date,league,rows){
    date=normalizeDate(date); const day=ensure(date); const lg=String(league||'SPORTS').toUpperCase();
    day.media.set(lg,Array.isArray(rows)?rows.slice():[]); day.mediaLoadedAt=Date.now(); notify('media',date); return day.media.get(lg);
  }
  function addMedia(date,league,rows){
    const prior=media(date,league); const merged=[...prior,...(Array.isArray(rows)?rows:[])];
    const seen=new Set(); const dedup=[];
    for(const item of merged){const key=String(item?.id||item?.youtubeId||item?.mediaUrl||item?.externalUrl||JSON.stringify(item));if(seen.has(key))continue;seen.add(key);dedup.push(item);}
    return setMedia(date,league,dedup);
  }
  function matches(date,league){const day=days.get(normalizeDate(date));if(!day)return [];return (day.matches.get(String(league||'SPORTS').toUpperCase())||[]).slice();}
  function media(date,league){const day=days.get(normalizeDate(date));if(!day)return [];return (day.media.get(String(league||'SPORTS').toUpperCase())||[]).slice();}
  function allMatches(date){const day=days.get(normalizeDate(date));return day?[...day.matches.values()].flat():[];}
  function allMedia(date){const day=days.get(normalizeDate(date));return day?[...day.media.values()].flat():[];}
  function hasMatchesSnapshot(date){const day=days.get(normalizeDate(date));return !!day&&day.matches.size>0;}
  function hasLeagueMatchesSnapshot(date,league){const day=days.get(normalizeDate(date));return !!day&&day.matches.has(String(league||'SPORTS').toUpperCase());}
  function loadedMatchLeagues(date){const day=days.get(normalizeDate(date));return day?[...day.matches.keys()]:[];}
  function hasLeagueMediaSnapshot(date,league){const day=days.get(normalizeDate(date));return !!day&&day.media.has(String(league||'SPORTS').toUpperCase());}
  function markLoading(date,on=true){date=normalizeDate(date);if(on)loading.add(date);else loading.delete(date);notify(on?'loading':'loaded',date);}
  function isLoading(date){return loading.has(normalizeDate(date));}
  function snapshot(){return {browseDate,playbackDate,today:localDateISO(0),isBrowsingToday:browseDate===localDateISO(0),isPlayingToday:playbackDate===localDateISO(0)};}
  function subscribe(fn,{emitCurrent=false}={}){if(typeof fn!=='function')return()=>{};listeners.add(fn);if(emitCurrent)fn(snapshot(),{action:'snapshot'});return()=>listeners.delete(fn);}
  window.SBB_SCORE_DATE=Object.freeze({version:'1.0',localDateISO,normalizeDate,setBrowseDate,setPlaybackDate,setMatches,setMedia,addMedia,matches,media,allMatches,allMedia,hasMatchesSnapshot,hasLeagueMatchesSnapshot,loadedMatchLeagues,hasLeagueMediaSnapshot,markLoading,isLoading,snapshot,subscribe});
})();

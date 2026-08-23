/* Sports Big Board v3.0.1 — persistent per-event media manifest.
   One truth feeds score rails, resolver, alternates, and playback failover. */
(() => {
  const manifests=new Map(),listeners=new Set();
  const clean=v=>String(v??'').trim();
  function eventKey(eventLike){return window.SBB_EVENT_IDENTITY?.key?.(eventLike)||`${clean(eventLike?.competitionId||eventLike?.league||'SPORTS').toUpperCase()}:${clean(eventLike?.eventId||eventLike?.matchId||eventLike?.id)}`;}
  function assetKey(asset){return window.SBB_PLAYBACK_TRANSPORTS?.playbackKey?.(asset)||clean(asset?.mediaId||asset?.id||asset?.youtubeId||asset?.mediaUrl||asset?.externalUrl);}
  function ensure(eventLike){
    const key=eventKey(eventLike);if(!key)return null;
    let m=manifests.get(key);
    if(!m){m={eventKey:key,event:window.SBB_CORE?.event?.(eventLike,eventLike?.competitionId||eventLike?.league)||{...eventLike},assets:new Map(),updatedAt:Date.now(),revision:0};manifests.set(key,m);}
    return m;
  }
  function notify(m,action,asset=null){m.updatedAt=Date.now();m.revision++;for(const fn of listeners){try{fn(snapshotManifest(m),{action,asset});}catch(_){}}}
  function normalizeAsset(eventLike,raw,{external=false}={}){
    const c=eventLike?.competitionId||eventLike?.__sbbLeague||eventLike?.league;
    const a=window.SBB_CORE?.mediaAsset?window.SBB_CORE.mediaAsset(raw,c):{...raw};
    a.competitionId=clean(a.competitionId||c).toUpperCase();
    a.eventId=clean(a.eventId||eventLike?.eventId||eventLike?.matchId||eventLike?.gamePk||eventLike?.id);
    a.transport=window.SBB_PLAYBACK_TRANSPORTS?.transportForAsset?.(a)||a.transport||'';
    a.externalOnly=external||a.externalOnly===true||a.transport==='EXTERNAL';
    a.discovered=true;
    a.runtimeState=a.runtimeState||'unknown';
    return a;
  }
  function ingest(eventLike,assets,{external=false}={}){
    const m=ensure(eventLike);if(!m)return null;
    let changed=false;
    for(const raw of (assets||[])){
      if(!raw)continue;
      const a=normalizeAsset(eventLike,raw,{external});const key=assetKey(a);if(!key||key==='unsupported')continue;
      const prev=m.assets.get(key)||{};
      const merged={...prev,...a,manifestAssetKey:key,lastSeenAt:Date.now()};
      if(prev.runtimeState==='failed'&&a.runtimeState!=='playing')merged.runtimeState='failed';
      m.assets.set(key,merged);changed=true;
    }
    if(changed)notify(m,'ingest');
    return snapshotManifest(m);
  }
  function mark(eventLike,asset,patch={}){
    const m=ensure(eventLike);if(!m)return null;const key=assetKey(asset);if(!key)return null;
    const prev=m.assets.get(key)||normalizeAsset(eventLike,asset);
    const next={...prev,...patch,lastStateAt:Date.now()};m.assets.set(key,next);notify(m,'state',next);return {...next};
  }
  function markFailed(eventLike,asset,reason='runtime failure'){return mark(eventLike,asset,{runtimeState:'failed',runtimeFailureReason:String(reason||''),verifiedPlayable:false});}
  function markPlaying(eventLike,asset){return mark(eventLike,asset,{runtimeState:'playing',verifiedPlayable:true,lastPlayedAt:Date.now()});}
  function markBuffering(eventLike,asset){
    const m=ensure(eventLike);if(!m)return null;const key=assetKey(asset);if(!key)return null;
    const prev=m.assets.get(key)||normalizeAsset(eventLike,asset);
    return mark(eventLike,asset,{runtimeState:'buffering',bufferingCount:Number(prev.bufferingCount||0)+1,lastBufferingAt:Date.now()});
  }
  function list(eventLike,{includeExternal=true}={}){const m=ensure(eventLike);if(!m)return[];return [...m.assets.values()].filter(a=>includeExternal||!a.externalOnly).map(a=>({...a}));}
  function playable(eventLike){return list(eventLike).filter(a=>a.runtimeState!=='failed'&&window.SBB_PLAYBACK_TRANSPORTS?.inAppPlayable?.(a));}
  function external(eventLike){return list(eventLike).filter(a=>a.externalOnly||(!window.SBB_PLAYBACK_TRANSPORTS?.inAppPlayable?.(a)&&a.externalUrl));}
  function availability(eventLike){
    const all=list(eventLike),c=window.SBB_MEDIA_CLASSIFIER;
    const avail={gold:false,green:false,extended:false,blue:false,internal:{gold:false,green:false,extended:false,blue:false},external:{gold:false,green:false,extended:false,blue:false}};
    for(const a of all){const tier=c?.tier?.(a)||'blue';const bucket=window.SBB_PLAYBACK_TRANSPORTS?.inAppPlayable?.(a)&&a.runtimeState!=='failed'?'internal':'external';if(tier==='gold')avail.gold=avail[bucket].gold=true;else if(tier==='extended')avail.extended=avail[bucket].extended=true;else if(tier==='green')avail.green=avail[bucket].green=true;else avail.blue=avail[bucket].blue=true;}
    return avail;
  }
  function snapshotManifest(m){return m?{eventKey:m.eventKey,event:{...m.event},assets:[...m.assets.values()].map(x=>({...x})),updatedAt:m.updatedAt,revision:m.revision}:null;}
  function get(eventLike){const m=ensure(eventLike);return snapshotManifest(m);}
  function subscribe(fn){if(typeof fn!=='function')return()=>{};listeners.add(fn);return()=>listeners.delete(fn);}
  function clear(){manifests.clear();}
  window.SBB_MEDIA_MANIFEST=Object.freeze({version:'1.0',eventKey,assetKey,ingest,mark,markFailed,markPlaying,markBuffering,list,playable,external,availability,get,subscribe,clear});
})();

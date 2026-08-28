/* Sports Big Board v4.4.8 — provider-independent GAME EventMediaResolver.
   Ranking operates on unique physical playback media, never duplicate DB/source
   records that happen to point at the same YouTube ID or direct URL. */
(() => {
  const R=()=>window.SBB_SPORT_MEDIA_POLICY?.REQUEST||{QUICK:'QUICK',EXTENDED:'EXTENDED',COMMENTARY:'COMMENTARY',MOMENTS:'MOMENTS',ANY:'ANY'};
  const classifier=()=>window.SBB_MEDIA_CLASSIFIER;
  function provider(asset){return String(asset?.provider||asset?.sourceType||asset?.source||asset?.sourceLabel||'UNKNOWN').toUpperCase();}
  function physicalKey(asset){
    try{return window.SBB_PLAYBACK_TRANSPORTS?.playbackKey?.(asset)||String(asset?.youtubeId?`youtube:${asset.youtubeId}`:(asset?.mediaUrl?`direct:${asset.mediaUrl}`:(asset?.id||'')));}catch(_){return String(asset?.youtubeId||asset?.mediaUrl||asset?.id||'');}
  }
  function quality(asset){
    const q=Number(asset?.sourceQuality||0);if(q)return q;
    const text=`${asset?.source||''} ${asset?.sourceLabel||''} ${asset?.provider||''}`.toLowerCase();
    if(/official|nfl|mlb|nba|nhl|premier league|mls/.test(text))return 95;
    if(/espn|fox|nbc|cbs|sportsnet|network|broadcast/.test(text))return 86;
    return 65;
  }
  function requestMatches(asset,request){
    const tier=classifier()?.tier?.(asset)||'blue',REQ=R();
    if(request===REQ.ANY)return true;
    if(request===REQ.QUICK)return tier==='green';
    if(request===REQ.EXTENDED)return tier==='extended';
    if(request===REQ.COMMENTARY)return tier==='gold';
    if(request===REQ.MOMENTS)return tier==='blue';
    return true;
  }
  function rankScore(eventLike,asset,request){
    if(window.SBB_MEDIA_SCOPE && !window.SBB_MEDIA_SCOPE.isGame(asset,{eventId:eventLike?.eventId||eventLike?.scoreEventId||eventLike?.matchId||eventLike?.gamePk||eventLike?.id||'',away:eventLike?.awayTeam?.displayName||eventLike?.away?.name||'',home:eventLike?.homeTeam?.displayName||eventLike?.home?.name||''}))return -100000;
    const pol=window.SBB_SPORT_MEDIA_POLICY, transports=window.SBB_PLAYBACK_TRANSPORTS;
    const policy=pol?.policyFor?.(eventLike)||{};const transport=transports?.transportForAsset?.(asset)||'';
    let score=quality(asset)+(policy.sourceWeights?.[transport]||0)+(window.SBB_PROVIDER_HEALTH?.score?.(provider(asset))||0);
    if(requestMatches(asset,request))score+=70;else if(request!==R().ANY)score-=65;
    if(request===R().QUICK)score+=pol?.durationScore?.(Number((asset?.durationSeconds??asset?.duration) || 0),policy.quick)||0;
    if(request===R().EXTENDED)score+=pol?.durationScore?.(Number((asset?.durationSeconds??asset?.duration) || 0),policy.extended)||0;
    if(request===R().COMMENTARY)score+=pol?.durationScore?.(Number((asset?.durationSeconds??asset?.duration) || 0),policy.commentary)||0;
    if(asset?.runtimeState==='playing')score+=20;if(asset?.runtimeState==='failed')score-=1000;score+=Number(window.SBB_PLAYBACK_READINESS?.rankBonus?.(asset)||0);
    score-=Math.min(42,Number(asset?.bufferingCount||0)*7);
    if(asset?.embedValidated===true)score+=10;if(asset?.externalOnly)score-=20;
    if(asset?.overview||asset?.programType==='recap')score+=8;
    return score;
  }
  function uniquePhysical(assets=[]){
    const out=[],index=new Map();
    for(const raw of assets||[]){
      if(!raw)continue;const key=physicalKey(raw);
      if(!key){out.push(raw);continue;}
      if(!index.has(key)){index.set(key,out.length);out.push(raw);continue;}
      const i=index.get(key),prev=out[i]||{};
      const pd=Number(prev.durationSeconds??prev.duration??0)||0,nd=Number(raw.durationSeconds??raw.duration??0)||0;
      const merged={...prev,...raw};
      if(pd>nd){merged.durationSeconds=pd;merged.duration=pd;}
      // Duplicate provenance must never resurrect the same poisoned physical
      // asset. Preserve the strongest negative runtime/quarantine state.
      if(prev.runtimeState==='failed'||raw.runtimeState==='failed')merged.runtimeState='failed';
      if(prev.runtimeState==='quarantined'||raw.runtimeState==='quarantined')merged.runtimeState='quarantined';
      const pq=Number(prev.quarantinedUntil||0),rq=Number(raw.quarantinedUntil||0);
      if(Math.max(pq,rq)>0)merged.quarantinedUntil=Math.max(pq,rq);
      out[i]=merged;
    }
    return out;
  }
  function resolve(eventLike,request,{assets=[],externalAssets=[],includeExternalFallback=true}={}){
    const manifest=window.SBB_MEDIA_MANIFEST;
    const uniqueAssets=uniquePhysical(assets),uniqueExternal=uniquePhysical(externalAssets);
    if(uniqueAssets.length)manifest?.ingest?.(eventLike,uniqueAssets);
    if(uniqueExternal.length)manifest?.ingest?.(eventLike,uniqueExternal,{external:true});
    const internal=uniquePhysical(manifest?.playable?.(eventLike)||[]).filter(a=>a.runtimeState!=='failed'&&window.SBB_PLAYBACK_READINESS?.eligible?.(a)!==false);
    const external=uniquePhysical(manifest?.external?.(eventLike)||[]);
    const ranked=internal.map(asset=>({asset,score:rankScore(eventLike,asset,request)})).sort((a,b)=>b.score-a.score);
    let primary=ranked.find(x=>requestMatches(x.asset,request))?.asset||null;
    if(!primary&&request===R().QUICK)primary=ranked.find(x=>['gold','green','extended'].includes(classifier()?.tier?.(x.asset)))?.asset||null;
    if(!primary&&request===R().ANY)primary=ranked[0]?.asset||null;
    const externalRanked=external.map(asset=>({asset,score:rankScore(eventLike,asset,request)})).sort((a,b)=>b.score-a.score);
    const externalPrimary=includeExternalFallback?(externalRanked.find(x=>requestMatches(x.asset,request))?.asset||externalRanked[0]?.asset||null):null;
    return {request,primary,ranked:ranked.map(x=>x.asset),externalPrimary,externalRanked:externalRanked.map(x=>x.asset),availability:manifest?.availability?.(eventLike)||{}};
  }
  function resolveBest(eventLike,opts={}){
    const REQ=R();if(opts.live)return resolve(eventLike,REQ.MOMENTS,opts);
    for(const req of [REQ.COMMENTARY,REQ.QUICK,REQ.EXTENDED,REQ.MOMENTS]){const r=resolve(eventLike,req,opts);if(r.primary)return r;}
    return resolve(eventLike,REQ.ANY,opts);
  }
  window.SBB_MEDIA_RESOLVER=Object.freeze({version:'1.1',resolve,resolveBest,rankScore,requestMatches,physicalKey,uniquePhysical});
})();

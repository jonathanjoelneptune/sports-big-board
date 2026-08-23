/* Sports Big Board v3.0.9 — provider-independent EventMediaResolver. */
(() => {
  const R=()=>window.SBB_SPORT_MEDIA_POLICY?.REQUEST||{QUICK:'QUICK',EXTENDED:'EXTENDED',COMMENTARY:'COMMENTARY',MOMENTS:'MOMENTS',ANY:'ANY'};
  const classifier=()=>window.SBB_MEDIA_CLASSIFIER;
  function provider(asset){return String(asset?.provider||asset?.sourceType||asset?.source||asset?.sourceLabel||'UNKNOWN').toUpperCase();}
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
    const pol=window.SBB_SPORT_MEDIA_POLICY, transports=window.SBB_PLAYBACK_TRANSPORTS;
    const policy=pol?.policyFor?.(eventLike)||{};const transport=transports?.transportForAsset?.(asset)||'';
    let score=quality(asset)+(policy.sourceWeights?.[transport]||0)+(window.SBB_PROVIDER_HEALTH?.score?.(provider(asset))||0);
    const tier=classifier()?.tier?.(asset)||'blue';
    if(requestMatches(asset,request))score+=70;else if(request!==R().ANY)score-=65;
    if(request===R().QUICK)score+=pol?.durationScore?.(Number((asset?.durationSeconds??asset?.duration) || 0),policy.quick)||0;
    if(request===R().EXTENDED)score+=pol?.durationScore?.(Number((asset?.durationSeconds??asset?.duration) || 0),policy.extended)||0;
    if(request===R().COMMENTARY)score+=pol?.durationScore?.(Number((asset?.durationSeconds??asset?.duration) || 0),policy.commentary)||0;
    if(asset?.runtimeState==='playing')score+=20;if(asset?.runtimeState==='failed')score-=1000;
    score-=Math.min(42,Number(asset?.bufferingCount||0)*7);
    if(asset?.embedValidated===true)score+=10;if(asset?.externalOnly)score-=20;
    if(asset?.overview||asset?.programType==='recap')score+=8;
    return score;
  }
  function resolve(eventLike,request,{assets=[],externalAssets=[],includeExternalFallback=true}={}){
    const manifest=window.SBB_MEDIA_MANIFEST;
    if(assets.length)manifest?.ingest?.(eventLike,assets);
    if(externalAssets.length)manifest?.ingest?.(eventLike,externalAssets,{external:true});
    const internal=(manifest?.playable?.(eventLike)||[]).filter(a=>a.runtimeState!=='failed');
    const external=manifest?.external?.(eventLike)||[];
    const ranked=internal.map(asset=>({asset,score:rankScore(eventLike,asset,request)})).sort((a,b)=>b.score-a.score);
    let primary=ranked.find(x=>requestMatches(x.asset,request))?.asset||null;
    // Quick is allowed to degrade to the best playable recap rather than no video.
    if(!primary&&request===R().QUICK)primary=ranked.find(x=>['gold','green','extended'].includes(classifier()?.tier?.(x.asset)))?.asset||null;
    if(!primary&&request===R().ANY)primary=ranked[0]?.asset||null;
    const externalRanked=external.map(asset=>({asset,score:rankScore(eventLike,asset,request)})).sort((a,b)=>b.score-a.score);
    const externalPrimary=includeExternalFallback?(externalRanked.find(x=>requestMatches(x.asset,request))?.asset||externalRanked[0]?.asset||null):null;
    return {request,primary,ranked:ranked.map(x=>x.asset),externalPrimary,externalRanked:externalRanked.map(x=>x.asset),availability:manifest?.availability?.(eventLike)||{}};
  }
  function resolveBest(eventLike,opts={}){
    const REQ=R();
    if(opts.live)return resolve(eventLike,REQ.MOMENTS,opts);
    for(const req of [REQ.COMMENTARY,REQ.QUICK,REQ.EXTENDED,REQ.MOMENTS]){const r=resolve(eventLike,req,opts);if(r.primary)return r;}
    return resolve(eventLike,REQ.ANY,opts);
  }
  window.SBB_MEDIA_RESOLVER=Object.freeze({version:'1.0',resolve,resolveBest,rankScore,requestMatches});
})();

/* Sports Big Board v4.1.2 — sport media policy.
   The application asks for QUICK / EXTENDED / COMMENTARY / MOMENTS. Sport policy
   describes ideal duration and ranking; providers are interchangeable. */
(() => {
  const REQUEST=Object.freeze({QUICK:'QUICK',EXTENDED:'EXTENDED',COMMENTARY:'COMMENTARY',MOMENTS:'MOMENTS',ANY:'ANY'});
  const base={
    quick:{ideal:[150,300],accept:[45,390],target:210},
    extended:{ideal:[600,1200],accept:[420,1800],target:900},
    commentary:{ideal:[120,360],accept:[90,420],target:210},
    sourceWeights:{DIRECT_VIDEO:18,YOUTUBE_EMBED:8,EXTERNAL:-10}
  };
  const POLICIES=Object.freeze({
    baseball:{...base,quick:{ideal:[150,300],accept:[60,390],target:210}},
    'american-football':{...base,quick:{ideal:[150,300],accept:[45,390],target:210},extended:{ideal:[720,1080],accept:[540,1800],target:900}},
    basketball:{...base,quick:{ideal:[120,300],accept:[45,420],target:210}},
    'ice-hockey':{...base,quick:{ideal:[120,300],accept:[45,420],target:210}},
    football:{...base,quick:{ideal:[120,300],accept:[45,420],target:180},extended:{ideal:[480,900],accept:[360,1500],target:720}},
    'multi-sport':base
  });
  function sportId(eventLike){
    const explicit=String(eventLike?.sportId||eventLike?.sport||'').trim();if(explicit)return explicit;
    return window.SBB_CORE?.competition?.(eventLike?.competitionId||eventLike?.league)?.sportId||'multi-sport';
  }
  function policyFor(eventLike){return POLICIES[sportId(eventLike)]||base;}
  function inRange(v,[a,b]){return Number(v)>=a&&Number(v)<=b;}
  function durationScore(seconds,rule){
    const d=Number(seconds)||0;if(!d)return 0;
    if(!inRange(d,rule.accept))return -70;
    const spread=Math.max(1,(rule.ideal[1]-rule.ideal[0])/2);
    if(inRange(d,rule.ideal))return 35-Math.min(15,Math.abs(d-rule.target)/spread*10);
    return 10-Math.min(25,Math.abs(d-rule.target)/Math.max(1,rule.target)*25);
  }
  function requestForTier(tier){return tier==='gold'?REQUEST.COMMENTARY:tier==='extended'?REQUEST.EXTENDED:tier==='blue'?REQUEST.MOMENTS:REQUEST.QUICK;}
  function ruleFor(eventLike,request){const p=policyFor(eventLike);return request===REQUEST.EXTENDED?p.extended:request===REQUEST.COMMENTARY?p.commentary:p.quick;}
  window.SBB_SPORT_MEDIA_POLICY=Object.freeze({version:'1.0',REQUEST,POLICIES,sportId,policyFor,durationScore,requestForTier,ruleFor});
})();

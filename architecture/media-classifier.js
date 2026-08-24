/* v4.1.0 authoritative game-media taxonomy; Silver is a separate collection scope. */
(() => {
  const TIER=Object.freeze({COMMENTARY:'gold',QUICK:'green',EXTENDED:'extended',HIGHLIGHT_REEL:'blue'});
  const duration=item=>Number(item?.durationSeconds??item?.duration??0)||0;
  const text=item=>`${item?.title||''} ${item?.subtitle||''} ${item?.description||''}`.toLowerCase();
  const source=item=>`${item?.sourceLabel||item?.source||item?.provider||''}`.toLowerCase();
  function recapCandidate(item){
    return !!(item?.overview || item?.programType==='recap' || /full game highlights|game recap|game highlights|condensed game|extended highlights|postgame recap|recap show/i.test(text(item)));
  }
  function explicitExtended(item){ return /\bextended highlights?\b|\bcondensed game\b|\bextended recap\b/.test(text(item)); }
  function commentary(item){
    if(!item) return false;
    if(item.recapTier==='gold'||item.commentaryLikely===true||Number(item.commentaryConfidence||0)>=0.85) return true;
    const d=duration(item); if(d&&(d<45||d>900)) return false;
    if(/condensed game|extended highlights|full game highlights/.test(text(item))) return false;
    const network=/espn|sportscenter|fox sports|fs1|nbc sports|cbs sports|sportsnet|mlb network|nfl network|nba tv|nhl network|spectrum|sny|nesn|masn|yes network|marquee|fanduel sports|bally/.test(source(item));
    const produced=/game recap|postgame recap|postgame report|game story|breakdown|analysis|highlights (?:and|&) analysis|recap show|what happened|postgame|post-match|post match|presser|press conference|reaction|look better|look worse/.test(text(item));
    return network&&produced;
  }

  function extended(item){
    if(!item||!recapCandidate(item)||commentary(item)) return false;
    const d=duration(item);
    return item.recapTier==='extended'||(d>=420&&d<=1500)||(!d&&explicitExtended(item));
  }
  function quick(item){ return !!item&&recapCandidate(item)&&!commentary(item)&&!extended(item); }
  function tier(item){
    if(commentary(item)) return TIER.COMMENTARY;
    if(extended(item)) return TIER.EXTENDED;
    if(quick(item)) return TIER.QUICK;
    return TIER.HIGHLIGHT_REEL;
  }
  function scoreType(item){ const t=tier(item); return t==='green'?'recap':t==='blue'?'clips':t; }
  function label(value){ return value==='gold'?'COMMENTARY':value==='green'?'FULL RECAP':value==='extended'?'EXTENDED':value==='blue'?'HIGHLIGHT REEL':''; }
  function availability(items,expand=x=>x||[]){
    const list=expand(items||[]).filter(x=>!window.SBB_MEDIA_SCOPE||window.SBB_MEDIA_SCOPE.isGame(x));
    return {
      gold:list.some(x=>tier(x)==='gold'), green:list.some(x=>tier(x)==='green'),
      extended:list.some(x=>tier(x)==='extended'), blue:list.some(x=>tier(x)==='blue'&&!!(x?.youtubeId||x?.mediaUrl))
    };
  }
  window.SBB_MEDIA_CLASSIFIER=Object.freeze({version:'1.0',TIER,duration,recapCandidate,commentary,extended,quick,tier,scoreType,label,availability});
})();

/* v4.1.18 authoritative game-media taxonomy; Silver is a separate collection scope. */
(() => {
  const TIER=Object.freeze({COMMENTARY:'gold',QUICK:'green',EXTENDED:'extended',HIGHLIGHT_REEL:'blue'});
  const duration=item=>Number(item?.durationSeconds??item?.duration??0)||0;
  const text=item=>`${item?.title||''} ${item?.subtitle||''} ${item?.description||''}`.toLowerCase();
  const source=item=>`${item?.sourceLabel||item?.source||item?.provider||''}`.toLowerCase();
  const nonGameRx=/\b(?:post[- ]?game show|post[- ]?game live|instant reaction|reaction(?:s)?(?: to)?|reacts? to|analysis show|film room|podcast|press conference|presser|interview)\b/i;
  const realHighlightsRx=/\b(?:full game highlights|game highlights|full match highlights|match highlights|condensed game|extended highlights)\b/i;
  function nonGameProgram(item){const t=text(item);return !!item&&!realHighlightsRx.test(t)&&nonGameRx.test(t);}
  function recapCandidate(item){
    if(!item||nonGameProgram(item))return false;
    return !!(item?.overview||item?.programType==='recap'||/full game highlights|game recap|game summary|game highlights|match recap|match highlights|condensed game|extended highlights|postgame recap/i.test(text(item)));
  }
  function commentary(item){
    if(!item||nonGameProgram(item))return false;
    if(item.recapTier==='gold'||item.commentaryLikely===true||Number(item.commentaryConfidence||0)>=0.85)return true;
    const d=duration(item); if(d&&(d<45||d>900))return false;
    if(/condensed game|extended highlights|full game highlights|full match highlights/.test(text(item)))return false;
    const network=/espn|sportscenter|fox sports|fs1|nbc sports|cbs sports|sportsnet|mlb network|nfl network|nba tv|nhl network|spectrum|sny|nesn|masn|yes network|marquee|fanduel sports|bally/.test(source(item));
    const produced=/game recap|postgame recap|postgame report|game story|what happened|highlights (?:and|&) analysis/.test(text(item));
    return network&&produced;
  }
  function extended(item){
    if(!item||!recapCandidate(item)||commentary(item))return false;
    const objective=String(item?.mediaObjective||'').toUpperCase();
    if(objective==='EXTENDED')return true;if(objective==='QUICK')return false;
    const d=duration(item); return item.recapTier==='extended'||(d>=420&&d<=1500)||(!d&&/\bextended highlights?\b|\bcondensed game\b|\bextended recap\b/.test(text(item)));
  }
  function quick(item){return !!item&&recapCandidate(item)&&!commentary(item)&&!extended(item);}
  function tier(item){
    if(commentary(item))return TIER.COMMENTARY;
    if(!recapCandidate(item))return TIER.HIGHLIGHT_REEL;
    const objective=String(item?.mediaObjective||'').toUpperCase();
    if(objective==='QUICK')return TIER.QUICK;if(objective==='EXTENDED')return TIER.EXTENDED;
    return extended(item)?TIER.EXTENDED:TIER.QUICK;
  }
  function scoreType(item){const t=tier(item);return t==='green'?'recap':t==='blue'?'clips':t;}
  function label(value){return value==='gold'?'COMMENTARY':value==='green'?'FULL RECAP':value==='extended'?'EXTENDED':value==='blue'?'HIGHLIGHT REEL':'';}
  function availability(items,expand=x=>x||[]){
    const list=expand(items||[]).filter(x=>!window.SBB_MEDIA_SCOPE||window.SBB_MEDIA_SCOPE.isGame(x));
    return {gold:list.some(x=>tier(x)==='gold'),green:list.some(x=>tier(x)==='green'),extended:list.some(x=>tier(x)==='extended'),blue:list.some(x=>tier(x)==='blue'&&!!(x?.youtubeId||x?.mediaUrl))};
  }
  window.SBB_MEDIA_CLASSIFIER=Object.freeze({version:'1.1',TIER,duration,nonGameProgram,recapCandidate,commentary,extended,quick,tier,scoreType,label,availability});
})();

/* Sports Big Board v4.2.2 — media scope is independent from recap quality. */
(() => {
  const SCOPE=Object.freeze({GAME:'GAME',DAY_LEAGUE:'DAY_LEAGUE',WEEK_LEAGUE:'WEEK_LEAGUE',ROUND_LEAGUE:'ROUND_LEAGUE',PLAYER:'PLAYER',SEASON_LEAGUE:'SEASON_LEAGUE',OTHER:'OTHER'});
  const COLLECTION=new Set([SCOPE.DAY_LEAGUE,SCOPE.WEEK_LEAGUE,SCOPE.ROUND_LEAGUE,SCOPE.SEASON_LEAGUE]);
  const text=x=>`${x?.title||''} ${x?.subtitle||''} ${x?.description||''}`;
  const title=x=>String(x?.title||'');
  const norm=x=>String(x||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
  const aliases=name=>{const p=norm(name).split(/\s+/).filter(Boolean),s=new Set([norm(name)]);if(p.length)s.add(p.at(-1));if(p.length>1)s.add(p.slice(-2).join(' '));return [...s].filter(x=>x.length>=3&&!['fc','united','city','new','los','san'].includes(x));};
  const mentions=(hay,name)=>{const h=` ${norm(hay)} `;return aliases(name).some(a=>h.includes(` ${a} `));};
  const dailyRoundup=/\b(nightly recap|daily recap|daily highlights|nightly highlights|nightly roundup|daily roundup|around the league|around the nba|around the nhl|around the mlb|all games|every game|night in the nba|night in the nhl|night in baseball|what happened (?:today|tonight))\b/i;
  const daily=/\b(nightly recap|daily recap|daily highlights|nightly highlights|nightly roundup|daily roundup|around the league|around the nba|around the nhl|around the mlb|all games|every game|top\s*(?:10|5|plays?)|top plays?|plays? of the (?:day|night)|best plays?|best of the (?:day|night)|night in the nba|night in the nhl|night in baseball|what happened (?:today|tonight))\b/i;
  const weekly=/\b(?:week(?:ly)?\s*(?:\d{1,2})?\s*(?:recap|roundup|highlights?|top plays?)|(?:recap|roundup|highlights?|top plays?)\s*(?:of\s*)?week\s*\d{1,2}|every touchdowns?\s*(?:from|of)?\s*week\s*\d{1,2}|top (?:goals?|saves?|hits?) (?:from|of) week\s*\d{1,2})\b/i;
  const round=/\b(?:matchweek|mwk|matchday)\s*\d{1,2}\b/i;
  const scoring=/\b(?:every|all)\s+(?:goal|touchdown)s?\s+(?:from|of)\s+(?:matchweek|mwk|matchday|week)\s*\d{1,2}\b|\ball goals? from (?:matchweek|mwk|matchday)\s*\d{1,2}\b/i;
  const roundTop=/\b(?:best|top)\s+(?:goals?|saves?|plays?)\s+(?:of|from)\s+(?:matchweek|mwk|matchday)\s*\d{1,2}\b|\bthings you may have missed in (?:matchweek|mwk|matchday)\s*\d{1,2}\b|\bmust[- ]see golazos?\b.*\bmatchday\s*\d{1,2}\b|\bwhat a save\b.*\bmatchdays?\s*\d{1,2}\b/i;
  const bestGoals=/\b(?:best|top)\s+goals?\s+(?:of|from)\s+(?:matchweek|mwk|matchday|week)\s*\d{1,2}\b|\bmust[- ]see golazos?\b/i;
  const bestSaves=/\b(?:best|top)\s+saves?\s+(?:of|from)\s+(?:matchweek|mwk|matchday|week)\s*\d{1,2}\b|\bwhat a save\b/i;
  const seasonal=/\b(season recap|season highlights|month in review|monthly recap|playoffs recap|tournament recap)\b/i;
  const topPlays=/\b(top\s*(?:10|5|plays?)|top plays?|plays? of the (?:day|night|week)|best plays?|best of the (?:day|night|week))\b/i;
  const nonGame=/\b(?:post[- ]?game show|post[- ]?game live|instant reaction|reaction(?:s)?(?: to)?|reacts? to|analysis show|film room|podcast|press conference|presser|interview)\b/i;
  const realHighlights=/\b(?:full game highlights|game highlights|full match highlights|match highlights|condensed game|extended highlights)\b/i;
  function dayKey(item,fallback=''){
    const t=text(item);let m=t.match(/\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b/);if(m)return `${m[1]}-${String(Number(m[2])).padStart(2,'0')}-${String(Number(m[3])).padStart(2,'0')}`;
    const months={jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,sept:9,oct:10,nov:11,dec:12};m=t.match(/\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+(20\d{2})\b/i);
    if(m){const mon=months[m[1].slice(0,4).toLowerCase()]||months[m[1].slice(0,3).toLowerCase()];if(mon)return `${m[3]}-${String(mon).padStart(2,'0')}-${String(Number(m[2])).padStart(2,'0')}`;}
    return String(fallback||item?.date||'').slice(0,10);
  }
  function classify(item,{away='',home='',eventId='',league=''}={}){
    const explicit=String(item?.mediaScope||'').toUpperCase();if(Object.values(SCOPE).includes(explicit))return explicit;
    const t=text(item),ttl=title(item);
    if(nonGame.test(t)&&!realHighlights.test(t))return SCOPE.OTHER;
    if(eventId&&item?.eventId!=null&&String(item.eventId)===String(eventId))return SCOPE.GAME;
    if(['scoreEventId','matchId','espnEventId','canonicalEventId'].some(k=>item?.[k]!=null&&String(item[k])!==''))return SCOPE.GAME;
    const st=String(item?.sourceType||'').toLowerCase(),src=String(item?.sourceLabel||item?.source||'').toLowerCase();
    if(['espn-event-video','mlb-game-content','nfl-event-video','official-nfl-club-site','official-nfl-game-highlights','official-nfl-extended-highlights','official-nhl-game-recap','official-nhl-condensed-game','official-mls-match-snapshot','official-mls-match-highlights','official-premierleague-match-highlights','trusted-nbc-epl-extended','official-nfl-public-video','official-nfl-team-video','official-nfl-youtube-playlist'].includes(st))return SCOPE.GAME;
    if(item?.gamePk&&src.includes('mlb'))return SCOPE.GAME;
    if(away&&home&&mentions(ttl,away)&&mentions(ttl,home))return SCOPE.GAME;
    const ia=item?.away||item?.awayTeamName,ih=item?.home||item?.homeTeamName;if(away&&home&&ia&&ih&&mentions(ia,away)&&mentions(ih,home))return SCOPE.GAME;
    if(['EPL','MLS'].includes(String(league||item?.league||'').toUpperCase())&&round.test(ttl)&&(scoring.test(ttl)||roundTop.test(ttl)))return SCOPE.ROUND_LEAGUE;
    if(dailyRoundup.test(ttl))return SCOPE.DAY_LEAGUE;
    if(weekly.test(t))return SCOPE.WEEK_LEAGUE;if(daily.test(t))return SCOPE.DAY_LEAGUE;if(seasonal.test(t))return SCOPE.SEASON_LEAGUE;
    if(/\b(full game highlights|game highlights|game recap|game summary|condensed game|full match highlights|match highlights|match recap)\b/i.test(ttl)&&away&&home)return SCOPE.OTHER;
    if(/\b\d{2,3}[- ]?(?:pt|point)|double[- ]double|triple[- ]double|player highlights?\b/i.test(t))return SCOPE.PLAYER;
    return SCOPE.OTHER;
  }
  function collectionKind(item){
    const t=text(item),scope=String(item?.mediaScope||'');
    if(bestGoals.test(t))return 'BEST_GOALS';if(bestSaves.test(t))return 'BEST_SAVES';if(scoring.test(t))return 'SCORING_ROUNDUP';
    if(topPlays.test(t)||scope===SCOPE.ROUND_LEAGUE&&roundTop.test(t))return 'TOP_PLAYS';if(scope===SCOPE.WEEK_LEAGUE)return 'WEEKLY_RECAP';if(scope===SCOPE.DAY_LEAGUE)return 'DAILY_RECAP';return 'ROUNDUP';
  }
  function seasonId(league,date=''){const d=new Date(`${String(date||'').slice(0,10)}T12:00:00Z`);if(Number.isNaN(d.getTime()))return 'unknown';const y=d.getUTCFullYear(),m=d.getUTCMonth()+1,L=String(league||'').toUpperCase();if(['NBA','NHL','EPL'].includes(L)){const s=m>=7?y:y-1;return `${s}-${String(s+1).slice(-2)}`;}if(L==='NFL')return String(m<=2?y-1:y);return String(y);}
  function roundKey(item,league,date=''){const m=title(item).match(/\b(matchweek|mwk|matchday)\s*(\d{1,2})\b/i);if(!m)return `${seasonId(league,date)}:ROUND`;return `${seasonId(league,date)}:${m[1].toLowerCase()==='matchday'?'MD':'MW'}${Number(m[2])}`;}
  function annotate(item,ctx={}){const out={...(item||{})};out.mediaScope=classify(out,ctx);if(COLLECTION.has(out.mediaScope)){out.collectionTier='silver';out.displayTier='silver';out.collectionKind=out.collectionKind||collectionKind(out);out.collectionPeriodKey=out.collectionPeriodKey||(out.mediaScope===SCOPE.DAY_LEAGUE?dayKey(out,ctx.date||out.date||''):(out.mediaScope===SCOPE.ROUND_LEAGUE?roundKey(out,ctx.league||out.league,ctx.date||out.date||''):String(out.collectionPeriodKey||ctx.date||out.date||'')));}return out;}
  const isGame=(item,ctx={})=>classify(item,ctx)===SCOPE.GAME;
  const isCollection=(item,ctx={})=>COLLECTION.has(classify(item,ctx));
  window.SBB_MEDIA_SCOPE=Object.freeze({version:'1.1',SCOPE,classify,annotate,isGame,isCollection,collectionKind,dayKey});
})();

/* v3.0.6 canonical event identity service. No UI or playback side effects. */
(() => {
  const clean=v=>v==null?'':String(v).trim();
  const league=x=>clean(x?.competitionId||x?.__sbbLeague||x?.league?.id||x?.league||'SPORTS').toUpperCase();
  const date=x=>clean(x?.gameDate||x?.__sbbDate||x?.date||x?.scheduledAt||x?.publishedAt).slice(0,10);
  const teamKey=v=>clean(v?.abbreviation||v?.abbr||v?.shortName||v?.name||v).toUpperCase().replace(/[^A-Z0-9]+/g,'');
  function gameNumber(x){
    const explicit=Number(x?.gameNumber||x?.doubleHeaderGame||0);
    if(explicit===1||explicit===2) return explicit;
    const m=clean(x?.title||x?.subtitle).match(/\bgame\s*([12])\b/i);
    return m?Number(m[1]):0;
  }
  function participants(x){
    if(Array.isArray(x?.participants)&&x.participants.length>=2) return x.participants.map(teamKey).filter(Boolean).slice(0,2).sort();
    const away=x?.awayTeam||x?.away||null, home=x?.homeTeam||x?.home||null;
    return [teamKey(away),teamKey(home)].filter(Boolean).sort();
  }
  function key(x){
    if(!x) return '';
    const lg=league(x);
    if(x.gamePk) return `${lg}:pk:${clean(x.gamePk)}`;
    if(x.matchId) return `${lg}:match:${clean(x.matchId)}`;
    if(x.eventId) return `${lg}:event:${clean(x.eventId)}`;
    if(x.scoreGameKey) return `${lg}:score:${clean(x.scoreGameKey)}`;
    if(x.dateGameKey) return `${lg}:date:${clean(x.dateGameKey)}${gameNumber(x)?`:g${gameNumber(x)}`:''}`;
    const teams=participants(x);
    const d=date(x);
    if(teams.length===2) return `${lg}:${d||'nodate'}:${teams.join('__')}${gameNumber(x)?`:g${gameNumber(x)}`:''}`;
    if(x.id) return `${lg}:id:${clean(x.id)}`;
    return '';
  }
  function datesCompatible(a,b){
    const ad=date(a),bd=date(b);
    if(!ad||!bd) return true;
    const am=Date.parse(`${ad}T12:00:00Z`), bm=Date.parse(`${bd}T12:00:00Z`);
    return Number.isFinite(am)&&Number.isFinite(bm) ? Math.abs(am-bm)<=36*3600_000 : ad===bd;
  }
  function same(a,b){
    if(!a||!b||league(a)!==league(b)) return false;
    if(a.gamePk&&b.gamePk) return clean(a.gamePk)===clean(b.gamePk);
    if(a.matchId&&b.matchId) return clean(a.matchId)===clean(b.matchId);
    if(a.eventId&&b.eventId) return clean(a.eventId)===clean(b.eventId);
    const ap=participants(a),bp=participants(b);
    if(ap.length===2&&bp.length===2&&ap.join('|')===bp.join('|')&&datesCompatible(a,b)){
      const ag=gameNumber(a),bg=gameNumber(b);
      return !(ag&&bg&&ag!==bg);
    }
    const ak=key(a),bk=key(b);
    return !!ak&&ak===bk;
  }
  window.SBB_EVENT_IDENTITY=Object.freeze({version:'1.0',key,same,league,date,participants,gameNumber});
})();

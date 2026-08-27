/* Sports Big Board v4.3.7 — canonical sport/event/media domain model.
   Provider adapters normalize into SPORT → COMPETITION → EVENT → MEDIA_PACKAGE → MEDIA_ASSET → MOMENT.
   Legacy fields remain accepted while v2.6.x migrates the existing application onto these contracts. */
(() => {
  const TYPES = Object.freeze({
    SPORT:'sport', COMPETITION:'competition', EVENT:'event', MEDIA_PACKAGE:'media-package',
    MEDIA:'media', MEDIA_ASSET:'media-asset', MOMENT:'moment', GAME_CENTER:'game-center', EDITORIAL_PACKAGE:'editorial-package'
  });

  const SPORTS = Object.freeze({
    baseball:{id:'baseball',label:'Baseball',eventKind:'game'},
    'american-football':{id:'american-football',label:'American Football',eventKind:'game'},
    basketball:{id:'basketball',label:'Basketball',eventKind:'game'},
    'ice-hockey':{id:'ice-hockey',label:'Ice Hockey',eventKind:'game'},
    football:{id:'football',label:'Soccer',eventKind:'match'},
    tennis:{id:'tennis',label:'Tennis',eventKind:'match'},
    motorsport:{id:'motorsport',label:'Motorsport',eventKind:'race'},
    athletics:{id:'athletics',label:'Track & Field',eventKind:'event'},
    'action-sports':{id:'action-sports',label:'Action Sports',eventKind:'event'},
    'multi-sport':{id:'multi-sport',label:'Sports',eventKind:'event'}
  });

  // One browser-side competition registry. The server exposes the same values
  // through /api/sports/catalog and tests assert that the enabled set stays aligned.
  const COMPETITIONS = Object.freeze({
    MLB:{id:'MLB',sportId:'baseball',name:'Major League Baseball',enabled:true,scoreProvider:'highlightly',mediaProviders:['mlb-stats','espn','highlightly','youtube'],gameCenterProvider:'highlightly',gameCenterFallback:'mlb-stats'},
    NFL:{id:'NFL',sportId:'american-football',name:'National Football League',enabled:true,scoreProvider:'espn',mediaProviders:['espn','nfl-club','nfl-feed','highlightly','youtube'],gameCenterProvider:'highlightly',gameCenterFallback:'espn'},
    NBA:{id:'NBA',sportId:'basketball',name:'National Basketball Association',enabled:true,scoreProvider:'espn',mediaProviders:['espn','highlightly','youtube'],gameCenterProvider:'highlightly',gameCenterFallback:'espn'},
    NHL:{id:'NHL',sportId:'ice-hockey',name:'National Hockey League',enabled:true,scoreProvider:'espn',mediaProviders:['espn','highlightly','youtube'],gameCenterProvider:'highlightly',gameCenterFallback:'espn'},
    EPL:{id:'EPL',sportId:'football',name:'Premier League',enabled:true,scoreProvider:'espn',mediaProviders:['espn','club-sites','highlightly','youtube'],gameCenterProvider:'highlightly',gameCenterFallback:'espn'},
    MLS:{id:'MLS',sportId:'football',name:'Major League Soccer',enabled:true,scoreProvider:'espn',mediaProviders:['mls','espn','club-sites','highlightly','youtube'],gameCenterProvider:'highlightly',gameCenterFallback:'espn'},
    UCL:{id:'UCL',sportId:'football',name:'UEFA Champions League',enabled:false},
    ATP:{id:'ATP',sportId:'tennis',name:'ATP Tour',enabled:false},
    WTA:{id:'WTA',sportId:'tennis',name:'WTA Tour',enabled:false},
    F1:{id:'F1',sportId:'motorsport',name:'Formula 1',enabled:false},
    XGAMES:{id:'XGAMES',sportId:'action-sports',name:'X Games',enabled:false},
    TRACK:{id:'TRACK',sportId:'athletics',name:'Track & Field',enabled:false},
    SPORTS:{id:'SPORTS',sportId:'multi-sport',name:'Daily Sports Programming',enabled:true,synthetic:true}
  });

  const clean=v=>v==null?'':String(v).trim();
  const upper=v=>clean(v).toUpperCase();
  function competition(id){
    const key=upper(id);
    return COMPETITIONS[key] || {id:key||'SPORTS',sportId:'multi-sport',name:key||'Sports',enabled:false,mediaProviders:[]};
  }
  function enabledCompetitions(){ return Object.values(COMPETITIONS).filter(x=>x.enabled&&!x.synthetic); }

  function participant(input={},side=''){
    if(!input) return null;
    if(typeof input==='string') return {id:'',name:input,abbreviation:'',side};
    return {
      ...input,
      id:clean(input.id??input.teamId??input.clubId),
      name:clean(input.name??input.teamName??input.displayName),
      abbreviation:clean(input.abbreviation??input.abbr??input.shortName),
      side:clean(input.side||side)
    };
  }

  function event(input={}, competitionId=''){
    const c=competition(competitionId || input.competitionId || input.__sbbLeague || input.league?.id || input.league);
    const away=participant(input.awayTeam||input.away||null,'away');
    const home=participant(input.homeTeam||input.home||null,'home');
    const participants=Array.isArray(input.participants) ? input.participants.map((x,i)=>participant(x,i===0?'away':i===1?'home':'')) : [away,home].filter(Boolean);
    return {
      ...input,
      entityType:TYPES.EVENT,
      sportId:clean(input.sportId||input.sport||c.sportId),
      competitionId:c.id,
      competitionName:clean(input.competitionName||input.league?.name||c.name),
      eventKind:clean(input.eventKind||SPORTS[c.sportId]?.eventKind||'event'),
      eventId:clean(input.eventId)||clean(input.matchId)||clean(input.gamePk)||clean(input.id),
      scheduledAt:clean(input.scheduledAt||input.date||input.gameDate),
      status:clean(input.status?.type?.name||input.status?.abstractGameState||input.status?.description||input.status||input.state?.report||input.state?.description||input.state?.status||input.state),
      participants
    };
  }

  function mediaAsset(input={}, competitionId=''){
    const c=competition(competitionId || input.competitionId || input.__sbbLeague || input.league);
    const provider=clean(input.provider||input.sourceType||input.source||input.sourceLabel);
    return {
      ...input,
      entityType:TYPES.MEDIA_ASSET,
      sportId:clean(input.sportId||input.sport||c.sportId),
      competitionId:c.id,
      competitionName:clean(input.competitionName||c.name),
      eventId:clean(input.eventId)||clean(input.matchId)||clean(input.gamePk),
      mediaId:clean(input.mediaId??input.highlightlyId??input.youtubeId??input.id??input.mediaUrl??input.externalUrl),
      provider,
      transport:clean(input.transport||window.SBB_PLAYBACK_TRANSPORTS?.transportForAsset?.(input)),
      durationSeconds:Number(input.durationSeconds??input.duration??0)||0,
      sourceQuality:Number(input.sourceQuality??0)||0,
      verifiedPlayable:input.verifiedPlayable===true,
      externalOnly:input.externalOnly===true,
      runtimeState:clean(input.runtimeState||'unknown')
    };
  }
  // Backward-compatible alias used by older code/tests.
  const media=mediaAsset;

  function mediaPackage(input={}, parent={}){
    return {
      ...input,
      entityType:TYPES.MEDIA_PACKAGE,
      sportId:clean(input.sportId||parent.sportId),
      competitionId:upper(input.competitionId||parent.competitionId),
      eventId:clean(input.eventId||parent.eventId),
      packageId:clean(input.packageId||input.id),
      packageType:clean(input.packageType||input.tier||input.mediaKind),
      assets:Array.isArray(input.assets)?input.assets.map(x=>mediaAsset(x,input.competitionId||parent.competitionId)):[]
    };
  }

  function moment(input={}, parent={}){
    return {
      ...input,
      entityType:TYPES.MOMENT,
      sportId:clean(input.sportId||parent.sportId),
      competitionId:upper(input.competitionId||parent.competitionId),
      eventId:clean(input.eventId||parent.eventId),
      momentId:clean(input.momentId??input.id),
      mediaAssetId:clean(input.mediaAssetId||input.mediaId),
      description:clean(input.description||input.title),
      period:input.period??input.inning??null,
      clock:clean(input.clock),
      scoreHome:input.scoreHome??null,
      scoreAway:input.scoreAway??null
    };
  }

  function statSection(input={},eventLike={}){
    const section={
      ...input,
      title:clean(input.title),
      columns:Array.isArray(input.columns)?input.columns.map(clean):[],
      rows:Array.isArray(input.rows)?input.rows:[],
      teamSide:clean(input.teamSide).toLowerCase(),
      teamId:clean(input.teamId),
      teamName:clean(input.teamName),
      teamAbbreviation:clean(input.teamAbbreviation),
      category:clean(input.category)
    };
    return window.SBB_GAME_CENTER_POLICY?.section?.(section,eventLike)||section;
  }
  function gameCenter(input={}, parent={}){
    const ev=event(input.event||parent,parent.competitionId||input.competitionId);
    const normalized={
      entityType:TYPES.GAME_CENTER,
      version:'1.0',
      competitionId:upper(input.competitionId||ev.competitionId||parent.competitionId),
      eventId:clean(input.eventId||ev.eventId||parent.eventId),
      event:ev,
      scoreboard:input.scoreboard||{},
      teamStats:Array.isArray(input.teamStats)?input.teamStats:[],
      playerStatSections:Array.isArray(input.playerStatSections)?input.playerStatSections.map(x=>statSection(x,ev)):[],
      timeline:Array.isArray(input.timeline)?input.timeline:[],
      scoringPlays:Array.isArray(input.scoringPlays)?input.scoringPlays:[],
      coverage:input.coverage||{},
      quality:input.quality||{},
      partial:input.partial===true||input.coverage?.complete===false,
      updatedAt:input.updatedAt||null,
      live:!!input.live,
      source:clean(input.source)
    };
    return window.SBB_GAME_CENTER_POLICY?.normalize?.(normalized)||normalized;
  }


  function editorialPackage(input={}){
    const registry=window.SBB_EDITORIAL_PACKAGES;
    if(registry?.package) return registry.package(input);
    return {
      ...input,
      entityType:TYPES.EDITORIAL_PACKAGE,
      editorialScope:clean(input.editorialScope||input.scope||'league'),
      editorialType:clean(input.editorialType||'top_plays'),
      cadence:clean(input.cadence||'daily'),
      competitionId:upper(input.competitionId||input.league),
      editorialPeriodKey:clean(input.editorialPeriodKey||input.topPlaysDate||input.publishedAt).slice(0,10)
    };
  }

  function playable(item){ return !!(item && item.verifiedPlayable && (item.youtubeId||item.mediaUrl)); }

  window.SBB_CORE=Object.freeze({
    version:'4.3.7', TYPES, SPORTS, COMPETITIONS, competition, enabledCompetitions,
    participant, event, media, mediaAsset, mediaPackage, moment, statSection, gameCenter, editorialPackage, playable
  });
})();

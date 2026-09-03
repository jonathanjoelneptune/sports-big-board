/* Sports Big Board v5.3.13 — Focus Integration + Full Team Theme
   User-facing content discovery over the existing score/calendar + historical
   catalog. No second playback owner: curated results become normal PROGRAM items
   and therefore inherit PlaybackController, Hot Standby, Up Next and score-card
   interrupt/resume behavior. */
(() => {
  'use strict';
  if(window.SBB_CURATED_BROWSE?.version==='5.3.13') return;

  const VERSION='5.3.13';
  const FAVORITES_KEY='sbb.curation.favorites.v1';
  const ENTITY_CATALOG_KEY='sbb.browse.entity-catalog.v535';
  const ENTITY_CATALOG_TTL_MS=6*60*60*1000;
  const ENTITY_CONTEXT_REFRESH_MS=10*60*1000;
  const TEAM_THEME_KEY='sbb.team-theme.enabled.v1';
  const MAX_AUDIT_ROWS=1000;
  const MAX_ENTITY_AUDIT_ROWS=10000;
  const PAGE_SIZE=100;
  const $=id=>document.getElementById(id);
  const clean=v=>String(v??'').trim();
  const norm=v=>clean(v).toLowerCase().replace(/^#?\d+\s+/,'').replace(/[^a-z0-9]+/g,' ').trim();
  const esc=s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  const state={
    league:'ALL',open:false,mode:'daily',entity:'',entityType:'team',facet:'',
    games:[],loading:false,error:'',requestToken:0,selected:new Set(),
    favorites:loadFavorites(),queueActive:false,queueItems:[],queueLabel:'',
    preProgram:null,preGeneral:null,renderQueuePatched:false,searchTimer:null,
    suggestionRows:[],lastQuery:'',entityCatalogCache:new Map(),entityCatalogInflight:new Map(),entityCatalogSavedAt:new Map(),
    scoreDateCache:new Map(),scoreDateInflight:new Map(),scoreObserver:null,controlLeague:'',
    entityAuditRows:[],contextInsightToken:0,contextInsightTimer:null,normalTickerSnapshot:null,
    teamFocusData:null,teamFocusKey:'',teamFocusInflight:null,teamThemeEnabled:loadTeamTheme(),
    entityMetaCache:new Map(),specialContext:null,cfbObserver:null,
    curatedAlternates:new Map(),failedCuratedMedia:new Set(),playbackFailurePatched:false,
    curatedOwnershipEpoch:0,curatedGuardTimer:null,curatedExpectedIndex:0,curatedExpectedKey:'',curatedGuardBusy:false,
  };


  function loadTeamTheme(){try{return localStorage.getItem(TEAM_THEME_KEY)==='1';}catch(_){return false;}}
  function saveTeamTheme(value){state.teamThemeEnabled=!!value;try{localStorage.setItem(TEAM_THEME_KEY,state.teamThemeEnabled?'1':'0');}catch(_){}applyTeamTheme();syncTeamThemeToggle();}
  function validHex(value){const raw=clean(value).replace(/^#/,'');return /^[0-9a-f]{6}$/i.test(raw)?`#${raw}`:'';}
  function hexRgb(value){const h=validHex(value);if(!h)return null;return [parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16)];}
  function luminance(value){const rgb=hexRgb(value);if(!rgb)return 0;const s=rgb.map(v=>{v/=255;return v<=.03928?v/12.92:((v+.055)/1.055)**2.4;});return .2126*s[0]+.7152*s[1]+.0722*s[2];}
  function clearTeamTheme(){const root=document.documentElement;delete root.dataset.sbbTeamTheme;delete root.dataset.sbbTeamThemeLight;for(const key of ['--sbb-team-primary','--sbb-team-secondary','--sbb-team-accent','--sbb-team-bg','--sbb-team-surface','--sbb-team-surface-raised','--sbb-team-black-replacement','--sbb-team-gradient-start','--sbb-team-gradient-end','--sbb-team-text','--sbb-team-muted','--sbb-team-line','--sbb-team-button','--sbb-team-button-text','--sbb-team-selected','--sbb-team-selected-text'])root.style.removeProperty(key);}
  function themeRoles(entity,palette){
    const server=state.teamFocusData?.team?.theme;if(server&&server.bg&&server.surface&&server.text){
      return {
        primary:validHex(server.primary)||validHex(palette?.primary)||'#14314a',secondary:validHex(server.secondary)||validHex(palette?.secondary)||'#63b7ff',accent:validHex(server.accent)||validHex(palette?.accent)||'#63b7ff',
        bg:validHex(server.bg),surface:validHex(server.surface),surfaceRaised:validHex(server.surfaceRaised)||validHex(server.surface),blackReplacement:validHex(server.blackReplacement)||validHex(server.surface),
        gradientStart:validHex(server.gradientStart)||validHex(server.surface),gradientEnd:validHex(server.gradientEnd)||validHex(server.surface),
        text:validHex(server.text),muted:validHex(server.muted)||validHex(server.text),line:validHex(server.line)||validHex(server.secondary),button:validHex(server.button)||validHex(server.secondary),buttonText:validHex(server.buttonText)||'#ffffff',selected:validHex(server.selected)||validHex(server.accent),selectedText:validHex(server.selectedText)||'#ffffff',light:!!server.light,wcag:server.wcag||{}
      };
    }
    const primary=validHex(palette?.primary),secondary=validHex(palette?.secondary),accent=validHex(palette?.accent)||secondary;if(!primary||!secondary)return null;
    const key=norm(entity);
    if(key==='los angeles dodgers')return {primary:'#ffffff',secondary:'#005a9c',accent:'#ef3e42',bg:'#ffffff',surface:'#f7fafc',surfaceRaised:'#ffffff',blackReplacement:'#e8f0f6',gradientStart:'#ffffff',gradientEnd:'#edf5fb',text:'#10263b',muted:'#496578',line:'#005a9c',button:'#005a9c',buttonText:'#ffffff',selected:'#ef3e42',selectedText:'#ffffff',light:true,wcag:{fallback:true}};
    if(key==='san diego padres')return {primary:'#2f241d',secondary:'#ffc425',accent:'#ffffff',bg:'#1f1814',surface:'#2f241d',surfaceRaised:'#3a2d24',blackReplacement:'#1b1512',gradientStart:'#392b22',gradientEnd:'#2a251d',text:'#fff8e5',muted:'#ead79f',line:'#ffc425',button:'#ffc425',buttonText:'#201812',selected:'#ffffff',selectedText:'#201812',light:false,wcag:{fallback:true}};
    const light=luminance(primary)>.64;
    return {primary,secondary,accent,bg:light?'#f5f8fa':'#071018',surface:light?'#ffffff':'#0b1620',surfaceRaised:light?'#ffffff':'#111f2a',blackReplacement:light?'#e9eff3':'#060d13',gradientStart:light?'#ffffff':'#10202c',gradientEnd:light?'#edf3f7':'#0a151e',text:light?'#111820':'#ffffff',muted:light?'#52606a':'#d7e0e6',line:secondary,button:secondary,buttonText:luminance(secondary)>.55?'#10161b':'#ffffff',selected:accent,selectedText:luminance(accent)>.55?'#10161b':'#ffffff',light,wcag:{fallback:true}};
  }
  function applyTeamTheme(){
    if(!state.teamThemeEnabled||state.mode==='daily'||state.entityType==='player'||!state.entity){clearTeamTheme();return;}
    const roles=themeRoles(state.entity,state.teamFocusData?.team?.palette||{});if(!roles){clearTeamTheme();return;}
    const root=document.documentElement;root.dataset.sbbTeamTheme='on';root.dataset.sbbTeamThemeLight=roles.light?'1':'0';
    const vars={'--sbb-team-primary':roles.primary,'--sbb-team-secondary':roles.secondary,'--sbb-team-accent':roles.accent,'--sbb-team-bg':roles.bg,'--sbb-team-surface':roles.surface,'--sbb-team-surface-raised':roles.surfaceRaised||roles.surface,'--sbb-team-black-replacement':roles.blackReplacement||roles.surface,'--sbb-team-gradient-start':roles.gradientStart||roles.surface,'--sbb-team-gradient-end':roles.gradientEnd||roles.surface,'--sbb-team-text':roles.text,'--sbb-team-muted':roles.muted,'--sbb-team-line':roles.line,'--sbb-team-button':roles.button,'--sbb-team-button-text':roles.buttonText,'--sbb-team-selected':roles.selected,'--sbb-team-selected-text':roles.selectedText};
    for(const [key,value] of Object.entries(vars))root.style.setProperty(key,value);
  }
  function syncTeamThemeToggle(){const toggle=$('teamThemeToggle');if(toggle)toggle.checked=!!state.teamThemeEnabled;const hint=$('teamThemeHint');if(hint)hint.textContent=state.teamThemeEnabled?'Apply the active team palette to the entire Big Board.':'Use the normal Sports Big Board color system.';}

  function loadFavorites(){
    try{const raw=JSON.parse(localStorage.getItem(FAVORITES_KEY)||'{}');return raw&&typeof raw==='object'?raw:{};}catch(_){return {};}
  }
  function saveFavorites(){try{localStorage.setItem(FAVORITES_KEY,JSON.stringify(state.favorites));}catch(_){}}

  function rememberEntityMetadata(league,entities=[]){
    const key=clean(league).toUpperCase();if(!key)return;let map=state.entityMetaCache.get(key);if(!map){map=new Map();state.entityMetaCache.set(key,map);}
    for(const raw of entities||[]){const item=typeof raw==='string'?{name:raw}:(raw||{});const name=clean(item.name||item.displayName);const nk=norm(name);if(!nk)continue;map.set(nk,{name,abbreviation:clean(item.abbreviation||item.abbr),logo:clean(item.logo||item.flag||item.image),country:clean(item.country||item.countryCode),kind:clean(item.kind)});}
  }
  function entityMetaFor(name,league=state.league){return state.entityMetaCache.get(clean(league).toUpperCase())?.get(norm(name))||{name:clean(name)};}
  function loadEntityCatalogStore(){
    try{
      const raw=JSON.parse(localStorage.getItem(ENTITY_CATALOG_KEY)||'{}');if(!raw||typeof raw!=='object')return;
      for(const [league,value] of Object.entries(raw)){
        const names=Array.isArray(value?.names)?value.names.filter(Boolean):[];if(!names.length)continue;const key=clean(league).toUpperCase();state.entityCatalogCache.set(key,names);state.entityCatalogSavedAt.set(key,Number(value?.savedAt||0));rememberEntityMetadata(key,Array.isArray(value?.entities)?value.entities:names.map(name=>({name})));
      }
    }catch(_){}
  }
  function persistEntityCatalog(league,names,entities=[]){
    const key=clean(league).toUpperCase();if(!key||!Array.isArray(names)||!names.length)return;const savedAt=Date.now();const unique=[...new Set(names.map(clean).filter(Boolean))];state.entityCatalogCache.set(key,unique);state.entityCatalogSavedAt.set(key,savedAt);rememberEntityMetadata(key,entities.length?entities:unique.map(name=>({name})));
    const map=state.entityMetaCache.get(key)||new Map();const packed=unique.map(name=>map.get(norm(name))||{name});
    try{const raw=JSON.parse(localStorage.getItem(ENTITY_CATALOG_KEY)||'{}')||{};raw[key]={savedAt,names:unique,entities:packed};localStorage.setItem(ENTITY_CATALOG_KEY,JSON.stringify(raw));}catch(_){}
  }
  function entityCatalogFresh(league){return Date.now()-Number(state.entityCatalogSavedAt.get(clean(league).toUpperCase())||0)<ENTITY_CATALOG_TTL_MS;}
  function favoritesFor(league){return Array.isArray(state.favorites[league])?state.favorites[league]:[];}
  function isFavorite(league,name){return favoritesFor(league).some(x=>norm(x)===norm(name));}
  function toggleFavorite(league,name){
    if(!league||!name)return;
    const current=favoritesFor(league).slice();const key=norm(name);const i=current.findIndex(x=>norm(x)===key);
    if(i>=0)current.splice(i,1);else current.push(name);
    state.favorites[league]=current;saveFavorites();renderSuggestions(state.entityCatalogCache.get(league)||state.suggestionRows,$('sbbBrowseSearch')?.value||'');
  }

  function leagueLabel(league){
    const map={'USOPEN-2026':'US OPEN','WC2026':'WORLD CUP','WORLD-CUP-2026':'WORLD CUP','FIFA-WORLD-CUP-2026':'WORLD CUP','LLWS2026':'LLWS','NCAAF':'NCAAF','CFB':'NCAAF'};
    return map[league]||league||'SPORTS';
  }
  function isTennis(league){return /USOPEN|TENNIS|ATP|WTA/i.test(league);}
  function isCollegeFootball(league){return /^NCAAF$/i.test(league);}
  function entityTypeFor(league){return isTennis(league)?'player':'team';}
  function selectedLeague(){
    if(state.specialContext?.league)return state.specialContext.league;
    try{const v=clean(scoreRibbonLeagueFilter).toUpperCase();if(v)return v==='CFB'?'NCAAF':v;}catch(_){}
    const active=document.querySelector('#scoreFilters button.active[data-score-filter],#scoreFilters button[aria-pressed="true"][data-score-filter]');
    const v=clean(active?.dataset?.scoreFilter||'ALL').toUpperCase()||'ALL';return v==='CFB'?'NCAAF':v;
  }
  function selectedDate(){try{return clean(scoreBrowseDate);}catch(_){return clean($('scoreDatePicker')?.value);}}
  function apiUrl(path){try{return window.SBB_API?.url?.(path)||path;}catch(_){return path;}}

  function teamObject(match,side){return match?.[side]||match?.[`${side}Team`]||match?.competitors?.find?.(x=>x?.homeAway===side)||{};}
  function participantName(v){return clean(v?.displayName||v?.name||v?.shortDisplayName||v?.location||v?.abbreviation||v);}
  function participantRank(v){
    const values=[v?.rank,v?.ranking,v?.seed,v?.pollRank,v?.nationalRank,v?.currentRank,v?.rankValue];
    for(const raw of values){const n=Number(String(raw??'').replace(/[^0-9]/g,''));if(n>0&&n<1000)return n;}
    return 0;
  }
  function currentMatches(league=state.league){
    try{return (scoreMatchesForDate(selectedDate())||[]).filter(m=>league==='ALL'||clean(m?.__sbbLeague||m?.league||m?.competitionId).toUpperCase()===league);}catch(_){return [];}
  }
  function currentEntities(league=state.league){
    const out=[];const seen=new Set();
    for(const match of currentMatches(league)){
      for(const side of ['away','home']){
        const name=participantName(teamObject(match,side));const key=norm(name);if(name&&key&&!seen.has(key)){seen.add(key);out.push(name);}
      }
    }
    return out.sort((a,b)=>a.localeCompare(b));
  }

  function splitGame(game){
    const text=clean(game);if(!text)return [];
    const bits=text.split(/\s+(?:@|at|vs\.?|v)\s+/i).map(x=>x.trim()).filter(Boolean);
    return bits.length>=2?bits.slice(0,2):[];
  }
  function entityMatchupLabel(away,home,entity=state.entity){
    const a=clean(away),h=clean(home),e=clean(entity),key=norm(e);
    if(e&&key){
      if(norm(a)===key||norm(a).includes(key)||key.includes(norm(a)))return `${e} at ${h||'Opponent'}`;
      if(norm(h)===key||norm(h).includes(key)||key.includes(norm(h)))return `${e} vs ${a||'Opponent'}`;
    }
    return a&&h?`${a} at ${h}`:(a||h||'Sports Highlight');
  }
  function gameHasEntity(game,entity){const key=norm(entity);return splitGame(game).some(x=>norm(x)===key||norm(x).includes(key)||key.includes(norm(x)));}
  function entitiesFromRows(rows,query=''){
    const q=norm(query),seen=new Set(),out=[];
    for(const row of rows||[]){
      for(const name of splitGame(row?.game)){
        const display=clean(name).replace(/^#?\d+\s+/,'');const key=norm(display);
        if(!key||seen.has(key)||(q&&!key.includes(q)))continue;
        seen.add(key);out.push(display);
      }
    }
    return out;
  }

  function youtubeIdFrom(value){
    const raw=clean(value);if(!raw)return '';
    if(/^[A-Za-z0-9_-]{11}$/.test(raw))return raw;
    const m=raw.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?[^#]*v=|embed\/|shorts\/))([A-Za-z0-9_-]{11})/i);return m?.[1]||'';
  }
  function mediaUsable(item){const proven=!!(item&&(item.verified===true||Number(item.verified)===1||item.runtimeState==='SUCCESS'||Number(item.runtimeSuccessAt)>0));return !!(proven&&(item.url||item.youtubeId||item.mediaUrl));}
  function sortedMediaPool(pool=[]){
    return pool.filter(mediaUsable).slice().sort((a,b)=>(Number(b.runtimeSuccessAt||0)-Number(a.runtimeSuccessAt||0))||(Number(b.verified)-Number(a.verified))||(Number(b.verifiedAt||0)-Number(a.verifiedAt||0)));
  }
  function allMediaForAuditRow(row,maxItems=6){
    const tiers=row?.tiers||{},order=['gold','green','extended','blue'],out=[],seen=new Set();
    for(const tier of order){
      for(const media of sortedMediaPool(tiers[tier]||[])){
        const url=clean(media?.url||media?.mediaUrl||media?.canonicalUrl),yt=clean(media?.youtubeId)||youtubeIdFrom(media?.providerMediaId)||youtubeIdFrom(url),key=clean(media?.assetKey||media?.id||yt||url);
        if(!key||seen.has(key))continue;seen.add(key);out.push({tier,media});if(out.length>=maxItems)return out;
      }
    }
    return out;
  }
  function bestMediaForAuditRow(row){
    const all=allMediaForAuditRow(row,12);if(!all.length)return {tier:'none',items:[]};
    const tier=all[0].tier,items=all.filter(x=>x.tier===tier).map(x=>x.media);
    return {tier,items:tier==='blue'?items.slice(0,12):items.slice(0,1)};
  }
  function programItemFromAudit(row,media,tier,index=0){
    const url=clean(media?.url||media?.mediaUrl||media?.canonicalUrl);const youtubeId=clean(media?.youtubeId)||youtubeIdFrom(media?.providerMediaId)||youtubeIdFrom(url);const parts=splitGame(row?.game);const away=parts[0]||'',home=parts[1]||'';
    const id=clean(media?.assetKey||media?.id||youtubeId)||`curated:${row?.league||state.league}:${row?.eventId||row?.date||'game'}:${tier}:${index}`;
    const sourceTitle=clean(media?.title)||clean(row?.game)||'Sports Highlight';
    const queueTitle=entityMatchupLabel(away,home);
    return {
      id,youtubeId:youtubeId||undefined,mediaUrl:youtubeId?'':url,
      title:queueTitle,queueTitle,sourceTitle,mediaTitle:sourceTitle,subtitle:sourceTitle,
      thumbnail:clean(media?.thumbnail)||clean(media?.thumbnailUrl)||clean(media?.image)||clean(media?.poster)||(youtubeId?`https://i.ytimg.com/vi/${youtubeId}/mqdefault.jpg`:''),
      durationSeconds:Number(media?.durationSeconds||media?.duration||0)||0,
      provider:clean(media?.provider||media?.source)||'HISTORICAL CATALOG',source:clean(media?.source||media?.provider)||'HISTORICAL CATALOG',
      league:clean(row?.league||state.league).toUpperCase(),competitionId:clean(row?.league||state.league).toUpperCase(),
      eventId:clean(row?.eventId),scoreEventId:clean(row?.scoreEventId||row?.eventId),espnEventId:clean(row?.espnEventId||''),
      gameCenterEventId:clean(row?.gameCenterEventId||row?.espnEventId||row?.scoreEventId||row?.eventId),matchId:clean(row?.eventId),gamePk:clean(row?.gamePk||''),
      canonicalEventKey:clean(row?.canonicalEventKey)||`${clean(row?.league||state.league).toUpperCase()}:${clean(row?.eventId)}`,
      date:clean(row?.date),gameDate:clean(row?.date),scheduledGameDate:clean(row?.date),scheduledAt:clean(row?.scheduledAt||row?.date),
      away,home,awayTeam:{name:away,displayName:away},homeTeam:{name:home,displayName:home},awayName:away,homeName:home,
      overview:tier!=='blue',programType:tier==='blue'?'reel':'recap',tier,historicalTier:tier,
      verifiedPlayable:true,verified:true,__sbbCuratedOverride:true,__sbbBrowseV537:true,
    };
  }
  function gameFromAuditRow(row){
    const gameKey=`${row.league||state.league}:${row.eventId||row.game}:${row.date||''}`;
    const ranked=allMediaForAuditRow(row,6);
    const candidates=ranked.map((entry,i)=>({...programItemFromAudit(row,entry.media,entry.tier,i),__sbbCuratedGameKey:gameKey,__sbbCuratedSourceRank:i,awayScore:row?.awayScore??null,homeScore:row?.homeScore??null,status:clean(row?.status)})).filter(x=>x.youtubeId||x.mediaUrl);
    const items=candidates.length?[candidates[0]]:[],alternates=candidates.slice(1);
    // Keep only one primary source per game in the visible/programming queue. Extra
    // verified sources are same-game fallbacks, not duplicate sequential programs.
    // v5.3.6 compatibility contract: tier:items.length?media.tier:'none' now follows the selected primary candidate's tier.
    return {key:gameKey,date:clean(row.date),league:clean(row.league||state.league).toUpperCase(),eventId:clean(row.eventId),game:clean(row.game),tier:items.length?items[0].tier:'none',items,alternates,row,source:'audit',mediaAvailable:!!items.length};
  }
  function gameFromResident(match){
    try{
      const candidates=scoreCardPlayableItems(match);const selection=scoreCardPlaybackSelection(match,candidates);
      const away=participantName(teamObject(match,'away')),home=participantName(teamObject(match,'home'));
      const queueTitle=entityMatchupLabel(away,home);
      const items=(selection?.selectionItems||[]).filter(Boolean).map(x=>({...x,queueTitle,__sbbCuratedOverride:true,__sbbBrowseV537:true}));
      if(!items.length)return null;
      const date=clean(match?.__sbbDate||match?.gameDate||match?.date).slice(0,10)||selectedDate();
      let key='';try{if(typeof scoreRibbonStableGameKey==='function')key=clean(scoreRibbonStableGameKey(match));}catch(_){}key=key||`${state.league}:${away}:${home}:${date}`;
      return {key,date,league:state.league,eventId:clean(match?.eventId||match?.id||match?.matchId),game:`${away} @ ${home}`,tier:clean(items[0]?.tier||items[0]?.historicalTier||'recap'),items,match,source:'resident'};
    }catch(_){return null;}
  }

  async function fetchAuditPage({league,q='',offset=0,limit=PAGE_SIZE,token}){
    const params=new URLSearchParams({league,limit:String(limit),offset:String(offset)});if(q)params.set('q',q);
    const r=await fetch(apiUrl(`/api/history/audit?${params.toString()}`),{cache:'no-store'});let data={};try{data=await r.json();}catch(_){data={};}
    if(token!==state.requestToken)throw new DOMException('Browse request superseded','AbortError');
    if(!r.ok||!data.ok)throw new Error(data.message||data.error||`HTTP ${r.status}`);
    return data;
  }
  async function fetchAuditRows(league,q='',maxRows=MAX_AUDIT_ROWS){
    const token=++state.requestToken;let offset=0,total=Infinity,out=[];
    while(offset<total&&out.length<maxRows){
      const data=await fetchAuditPage({league,q,offset,limit:PAGE_SIZE,token});const rows=Array.isArray(data.rows)?data.rows:[];out.push(...rows);total=Number(data.total??out.length);if(!rows.length)break;offset+=rows.length;if(rows.length<PAGE_SIZE)break;
    }
    return out.slice(0,maxRows);
  }

  function ensureUi(){
    const filters=$('scoreFilters');if(!filters)return false;
    let subnav=$('sbbBrowseSubnav');
    if(!subnav){
      subnav=document.createElement('span');subnav.id='sbbBrowseSubnav';subnav.className='sbb-browse-subnav hidden';subnav.setAttribute('aria-label','Contextual browse controls');
      subnav.innerHTML='<button id="sbbBrowseBtn" type="button" class="sbb-browse-btn" aria-haspopup="dialog" aria-expanded="false"><span>TEAM BROWSE</span><b aria-hidden="true">⌄</b></button><button id="sbbSpecialExitBtn" type="button" class="sbb-special-exit-btn hidden">EXIT EVENT</button>';
      filters.appendChild(subnav);
    }
    const btn=$('sbbBrowseBtn');
    if(!$('sbbBrowsePopover')){
      const pop=document.createElement('div');pop.id='sbbBrowsePopover';pop.className='sbb-browse-popover hidden';pop.setAttribute('role','dialog');pop.setAttribute('aria-label','Browse sports content');
      pop.innerHTML=`<div class="sbb-browse-popover-head"><div><span id="sbbBrowseKicker">BROWSE</span><strong id="sbbBrowseTitle">Browse</strong></div><button id="sbbBrowseClose" type="button" aria-label="Close Browse">×</button></div>
        <div class="sbb-browse-primary-actions"><button id="sbbBrowseToday" type="button">TODAY'S GAMES</button><button id="sbbBrowseAllHighlights" type="button">ALL HIGHLIGHTS</button><button id="sbbBrowseRanked" type="button" class="hidden">RANKED TODAY</button></div>
        <label class="sbb-browse-search-wrap"><span id="sbbBrowseSearchLabel">SEARCH TEAMS</span><input id="sbbBrowseSearch" type="search" autocomplete="off" placeholder="Search teams"></label>
        <div id="sbbBrowseFavorites" class="sbb-browse-favorites hidden"></div>
        <div id="sbbBrowseSuggestions" class="sbb-browse-suggestions"><div class="sbb-browse-empty">Choose a league, then search teams or players.</div></div>`;
      (document.getElementById('app-shell')||document.body).appendChild(pop);
    }
    if(!$('sbbCurationRibbon')){
      const ribbon=document.createElement('section');ribbon.id='sbbCurationRibbon';ribbon.className='sbb-curation-ribbon hidden';ribbon.setAttribute('aria-label','Curated sports highlights');
      ribbon.innerHTML=`<div id="sbbCurationCards" class="sbb-curation-cards"></div>`;
      const score=document.querySelector('.score-ribbon');score?.insertAdjacentElement('afterend',ribbon);
    }
    if(!$('sbbEntityTickerTrack')){
      const base=$('keyInfoTrack');
      if(base){const track=document.createElement('div');track.id='sbbEntityTickerTrack';track.className='key-info-track sbb-entity-info-track hidden';track.setAttribute('aria-label','Team or player focus information');base.insertAdjacentElement('afterend',track);}
    }
    if(!$('sbbEntityFocusControls')){
      const ribbon=document.querySelector('.key-info-ribbon');
      if(ribbon){const controls=document.createElement('div');controls.id='sbbEntityFocusControls';controls.className='sbb-entity-focus-controls hidden';controls.innerHTML='<button id="sbbFocusPlayAll" type="button">Play All</button><button id="sbbFocusExit" type="button">Exit Event</button>';ribbon.appendChild(controls);}
    }
    if(!$('teamThemeToggle')){
      const grid=document.querySelector('#settingsPane .settings-grid');
      const first=grid?.querySelector('.settings-card');
      if(grid&&first){const card=document.createElement('div');card.className='settings-card team-theme-settings-card';card.innerHTML='<div class="settings-card-title">TEAM FOCUS</div><label class="settings-toggle-row"><span><strong>Team themed coloring</strong><small id="teamThemeHint">Use the normal Sports Big Board color system.</small></span><input id="teamThemeToggle" type="checkbox"></label>';first.insertAdjacentElement('afterend',card);}
    }
    syncTeamThemeToggle();
    return true;
  }

  function captureScoreRibbonHeight(){
    const score=document.querySelector('.score-ribbon');if(!score||document.body.classList.contains('sbb-curation-active'))return 0;
    const height=Math.round(score.getBoundingClientRect().height||score.offsetHeight||0);
    if(height>=48){document.documentElement.style.setProperty('--sbb-score-ribbon-height',`${height}px`);return height;}
    return 0;
  }
  function entityAliases(name){
    const full=norm(name);if(!full)return [];const words=full.split(' ').filter(Boolean);const out=new Set([full]);
    if(words.length>1)out.add(words[words.length-1]);
    if(words.length>2)out.add(words.slice(-2).join(' '));
    return [...out].filter(x=>x.length>=3);
  }
  function snapshotNormalTicker(){
    const track=$('keyInfoTrack');if(!track)return;
    const rows=[...track.querySelectorAll('.key-info-item')].map(node=>clean(node.textContent).replace(/\s+/g,' ')).filter(Boolean);
    state.normalTickerSnapshot={stateText:clean($('keyInfoState')?.textContent),rows:[...new Set(rows)]};
  }
  function setEntityTickerActive(active){
    const base=$('keyInfoTrack'),focus=$('sbbEntityTickerTrack');if(!base||!focus)return;
    if(active&&!state.normalTickerSnapshot)snapshotNormalTicker();
    base.classList.toggle('sbb-entity-ticker-hidden',!!active);focus.classList.toggle('hidden',!active);
    $('sbbEntityFocusControls')?.classList.toggle('hidden',state.mode==='daily');
    document.body.classList.toggle('sbb-entity-ticker-active',!!active);
    if(active){if($('keyInfoState'))$('keyInfoState').textContent=state.entityType==='player'?'PLAYER FOCUS':'TEAM FOCUS';}
    else{if($('keyInfoState')&&state.normalTickerSnapshot?.stateText)$('keyInfoState').textContent=state.normalTickerSnapshot.stateText;state.normalTickerSnapshot=null;state.teamFocusData=null;state.teamFocusKey='';}
    applyTeamTheme();
  }
  function auditDate(row){return clean(row?.date||row?.eventDate||row?.gameDate).slice(0,10);}
  function entitySide(source,entity=state.entity){
    const parts=splitGame(clean(source?.game||source?.matchup||'')),key=norm(entity);
    if(parts.length>=2){if(norm(parts[0])===key||norm(parts[0]).includes(key)||key.includes(norm(parts[0])))return 'away';if(norm(parts[1])===key||norm(parts[1]).includes(key)||key.includes(norm(parts[1])))return 'home';}
    for(const side of ['away','home']){const name=participantName(teamObject(source,side));if(name&&(norm(name)===key||norm(name).includes(key)||key.includes(norm(name))))return side;}
    return '';
  }
  function recordStandingFromSource(source){
    const side=entitySide(source);if(!side)return {};const team=teamObject(source,side)||{};
    const candidates=[team?.record,team?.overallRecord,source?.[`${side}Record`],team?.records,source?.records];let record='';
    for(const raw of candidates){
      if(typeof raw==='string'&&/\d/.test(raw)){record=clean(raw);break;}
      if(Array.isArray(raw)){const found=raw.find(x=>/overall/i.test(clean(x?.type||x?.name)))||raw[0];const value=clean(found?.summary||found?.displayValue||found?.value);if(value){record=value;break;}}
      if(raw&&typeof raw==='object'){const value=clean(raw.summary||raw.displayValue||raw.overall||raw.value);if(value){record=value;break;}}
    }
    let standing='';for(const raw of [team?.leagueRank,team?.divisionRank,team?.standing,team?.rank,team?.playoffSeed,source?.[`${side}Rank`]]){const value=clean(raw?.displayValue||raw?.summary||raw);if(value&&value!=='0'){standing=value;break;}}
    return {record,standing};
  }
  function resultInsightGames(){
    const out=[];for(const game of state.games.slice(0,10)){const score=scoreDisplay(game);if(!score?.result)continue;const teams=splitGame(game.game);const label=teams.length>=2?`${shortEntityName(teams[0])} vs ${shortEntityName(teams[1])}`:describeGame(game);out.push({result:score.result,score:score.text,date:game.date,label});}return out;
  }
  function streakFromResults(results){
    if(!results.length)return '';const first=results[0].result;if(!/^[WLT]$/.test(first))return '';let n=0;for(const row of results){if(row.result!==first)break;n++;}return `${first}${n}`;
  }
  function upcomingFromAudit(){
    const today=new Date();const local=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
    return (state.entityAuditRows||[]).filter(row=>auditDate(row)>local&&gameHasEntity(row?.game,state.entity)).sort((a,b)=>auditDate(a).localeCompare(auditDate(b))).slice(0,5);
  }
  async function loadTeamFocusData(){
    if(!state.entity||state.entityType==='player')return null;
    const key=`${state.league}:${norm(state.entity)}`;
    if(state.teamFocusKey===key&&state.teamFocusData)return state.teamFocusData;
    if(state.teamFocusInflight?.key===key)return state.teamFocusInflight.promise;
    const params=new URLSearchParams({league:state.league,entity:state.entity});
    const promise=fetch(apiUrl(`/api/team-focus?${params.toString()}`),{cache:'no-store'}).then(async r=>{let data={};try{data=await r.json();}catch(_){data={};}return r.ok&&data?.ok?data:null;}).catch(()=>null).then(data=>{if(data&&key===`${state.league}:${norm(state.entity)}`){state.teamFocusKey=key;state.teamFocusData=data;applyTeamTheme();}return data;}).finally(()=>{if(state.teamFocusInflight?.key===key)state.teamFocusInflight=null;});
    state.teamFocusInflight={key,promise};return promise;
  }
  function contextNews(){
    const aliases=entityAliases(state.entity);const rows=state.normalTickerSnapshot?.rows||[];return rows.filter(text=>aliases.some(alias=>norm(text).includes(alias))).slice(0,6);
  }
  function contextInsight(label,text,kind=''){if(!text)return '';return `<div class="sbb-entity-info-item ${esc(kind)}"><strong>${esc(label)}</strong><span>${esc(text)}</span></div>`;}
  function contextIdentity(){
    const team=state.teamFocusData?.team||{},meta=entityMetaFor(state.entity),logo=clean(team.logo||meta.logo),label=state.entityType==='player'?'PLAYER':'TEAM';
    return `<div class="sbb-entity-info-item identity">${logo?`<span class="sbb-entity-logo"><img src="${esc(logo)}" alt=""></span>`:''}<span class="sbb-entity-identity-copy"><strong>${label}</strong><span>${esc(state.entity)}</span></span></div>`;
  }
  function renderEntityTickerPieces(pieces){
    const focus=$('sbbEntityTickerTrack');if(!focus)return;const body=pieces.filter(Boolean).join('');
    focus.innerHTML=`<div class="sbb-entity-info-conveyor"><div class="sbb-entity-info-cycle">${body}</div><div class="sbb-entity-info-cycle" aria-hidden="true">${body}</div></div>`;
    requestAnimationFrame(()=>{const cycle=focus.querySelector('.sbb-entity-info-cycle');focus.classList.toggle('is-overflowing',!!cycle&&cycle.scrollWidth>focus.clientWidth+8);});
  }
  function shortEntityName(name){const meta=entityMetaFor(name);if(meta.abbreviation)return meta.abbreviation.toUpperCase();const raw=clean(name);const map={'San Diego Padres':'SD','New York Yankees':'NYY','Los Angeles Dodgers':'LAD','San Francisco Giants':'SF','St. Louis Cardinals':'STL','Cincinnati Reds':'CIN','Pittsburgh Pirates':'PIT','Arizona Diamondbacks':'ARI','Colorado Rockies':'COL','Tampa Bay Rays':'TB','Miami Marlins':'MIA','Washington Nationals':'WSH','Atlanta Braves':'ATL','Houston Astros':'HOU','Chicago Cubs':'CHC','Chicago White Sox':'CHW','Boston Red Sox':'BOS','Toronto Blue Jays':'TOR','Baltimore Orioles':'BAL','Cleveland Guardians':'CLE','Detroit Tigers':'DET','Kansas City Royals':'KC','Minnesota Twins':'MIN','Milwaukee Brewers':'MIL','New York Mets':'NYM','Philadelphia Phillies':'PHI','Seattle Mariners':'SEA','Texas Rangers':'TEX','Athletics':'ATH','Los Angeles Angels':'LAA'};return map[raw]||raw.split(/\s+/).map(x=>x[0]).join('').slice(0,4).toUpperCase();}
  function compactMatchup(row){const parts=splitGame(row?.game);if(parts.length<2)return clean(row?.game);const selectedKey=norm(state.entity),away=parts[0],home=parts[1],sel=shortEntityName(state.entity);if(norm(away)===selectedKey||norm(away).includes(selectedKey)||selectedKey.includes(norm(away)))return `${sel} @ ${shortEntityName(home)}`;if(norm(home)===selectedKey||norm(home).includes(selectedKey)||selectedKey.includes(norm(home)))return `${sel} vs ${shortEntityName(away)}`;return `${shortEntityName(away)} @ ${shortEntityName(home)}`;}
  function compactDate(value){if(!value)return '';try{return new Date(`${value}T12:00:00`).toLocaleDateString(undefined,{month:'short',day:'numeric'}).toUpperCase();}catch(_){return value;}}
  async function refreshEntityTickerInsights(){
    const token=++state.contextInsightToken;if(state.mode==='daily'||!state.entity){setEntityTickerActive(false);return;}
    setEntityTickerActive(true);const focus=$('sbbEntityTickerTrack');if(!focus)return;
    renderEntityTickerPieces([contextIdentity(),contextInsight('LOADING','Refreshing team context…','loading')]);
    try{await Promise.all([loadTeamFocusData(),...state.games.slice(0,10).map((_,i)=>enrichGameScore(i))]);}catch(_){}if(token!==state.contextInsightToken)return;
    const results=resultInsightGames(),streak=streakFromResults(results);
    let record=clean(state.teamFocusData?.team?.record),standing=clean(state.teamFocusData?.team?.standing);for(const game of state.games){const rs=recordStandingFromSource(game.scoreMatch||game.match||game.row||{});if(!record&&rs.record)record=rs.record;if(!standing&&rs.standing)standing=rs.standing;if(record&&standing)break;}
    const upcoming=upcomingFromAudit().slice(0,3);
    const rankings=Array.isArray(state.teamFocusData?.rankings)?state.teamFocusData.rankings:[];
    const news=contextNews();const pieces=[contextIdentity()];
    if(state.entityType!=='player'&&record)pieces.push(contextInsight('RECORD',record,'record'));
    if(state.entityType!=='player'&&standing)pieces.push(contextInsight('STANDING',standing,'standing'));
    if(state.entityType!=='player'&&streak)pieces.push(contextInsight('STREAK',streak,'streak'));
    results.slice(0,7).forEach(row=>pieces.push(contextInsight('RESULT',`${compactDate(row.date)} · ${row.label} · ${row.result} ${row.score}`,'recent')));
    upcoming.forEach(row=>pieces.push(contextInsight('NEXT',`${compactDate(auditDate(row))} · ${compactMatchup(row)}`,'next')));
    rankings.forEach(row=>pieces.push(contextInsight(clean(row.label)==='PREDICTIVE'?'POWER RANK':(clean(row.label)||'RANK'),clean(row.text),'ranking')));
    news.slice(0,8).forEach(text=>pieces.push(contextInsight('NEWS',text,'news')));
    renderEntityTickerPieces(pieces);
    applyTeamTheme();
  }
  function scheduleEntityTickerRefresh(){clearTimeout(state.contextInsightTimer);state.contextInsightTimer=setTimeout(refreshEntityTickerInsights,80);}

  function activeLeagueButton(){
    const filters=$('scoreFilters');if(!filters)return null;if(state.specialContext&&$('sbbActiveSpecialChip'))return $('sbbActiveSpecialChip');
    return [...filters.querySelectorAll('button[data-score-filter]')].find(x=>clean(x.dataset.scoreFilter).toUpperCase()===state.league)||null;
  }
  function placeBrowseControls(){
    const subnav=$('sbbBrowseSubnav'),active=activeLeagueButton();if(!subnav||!active)return;
    const moved=subnav.previousElementSibling!==active;
    active.insertAdjacentElement('afterend',subnav);
    if(moved||state.controlLeague!==state.league){
      state.controlLeague=state.league;subnav.classList.remove('sbb-browse-subnav-enter');void subnav.offsetWidth;subnav.classList.add('sbb-browse-subnav-enter');
      setTimeout(()=>subnav.classList.remove('sbb-browse-subnav-enter'),240);
    }
  }
  function ensurePopoverHost(){
    const pop=$('sbbBrowsePopover'),host=document.getElementById('app-shell')||document.body;
    if(pop&&host&&pop.parentElement!==host)host.appendChild(pop);
    return pop;
  }
  function positionPopover(){
    if(!state.open)return;const btn=$('sbbBrowseBtn'),pop=ensurePopoverHost();if(!btn||!pop)return;
    const vv=window.visualViewport;const vw=Math.max(320,vv?.width||window.innerWidth||document.documentElement.clientWidth||320),vh=Math.max(320,vv?.height||window.innerHeight||document.documentElement.clientHeight||320);
    const ox=Number(vv?.offsetLeft||0),oy=Number(vv?.offsetTop||0),r=btn.getBoundingClientRect();
    const width=Math.min(430,vw-18),gap=7;let left=Math.max(ox+9,Math.min(r.left,ox+vw-width-9));let top=Math.max(oy+8,r.bottom+gap);let available=oy+vh-top-10;
    if(available<290){top=Math.max(oy+8,Math.min(r.top-gap-500,oy+42));available=oy+vh-top-10;}
    pop.style.left=`${Math.round(left)}px`;pop.style.right='auto';pop.style.top=`${Math.round(top)}px`;pop.style.width=`${Math.round(width)}px`;pop.style.maxHeight=`${Math.max(270,Math.floor(available))}px`;
  }

  function setOpen(open){
    state.open=!!open;const pop=$('sbbBrowsePopover'),btn=$('sbbBrowseBtn');
    if(pop){pop.hidden=!state.open;pop.classList.toggle('hidden',!state.open);pop.setAttribute('aria-hidden',state.open?'false':'true');}
    btn?.setAttribute('aria-expanded',state.open?'true':'false');
    document.body.classList.toggle('sbb-browse-menu-open',state.open);
    if(state.open){
      syncLeagueUi();
      const cached=state.entityCatalogCache.get(state.league);
      if(cached?.length)renderSuggestions(cached,'');
      else{
        const immediate=currentEntities(state.league);
        if(immediate.length)renderSuggestions(immediate,'');
        else{const host=$('sbbBrowseSuggestions');if(host)host.innerHTML=`<div class="sbb-browse-empty sbb-browse-loading">Loading saved ${state.entityType==='player'?'players':'teams'}…</div>`;}
      }
      positionPopover();primeEntityCatalog({render:true});setTimeout(()=>$('sbbBrowseSearch')?.focus(),0);
    }
  }
  function hideLegacyCfb(){
    document.querySelectorAll('#scoreFilters [data-score-filter="CFB"],[data-special-competition="CFB"]').forEach(el=>{el.remove();});
    try{if(clean(scoreRibbonLeagueFilter).toUpperCase()==='CFB')scoreRibbonLeagueFilter='NCAAF';}catch(_){}
  }
  function installLegacyCfbGuard(){
    hideLegacyCfb();if(state.cfbObserver)return;const filters=$('scoreFilters');if(!filters)return;
    // v5.3.13: the special-event header is display-only. Do not observe/filter its
    // attributes or repeatedly reposition Browse controls from a score-row mutation
    // callback. v5.3.9 accidentally created a feedback loop between the synthetic
    // event chip and the canonical score-filter renderer that could freeze the page.
    let repairQueued=false;
    state.cfbObserver=new MutationObserver(()=>{
      hideLegacyCfb();
      if(!state.specialContext||repairQueued||$('sbbActiveSpecialChip')?.isConnected)return;
      repairQueued=true;
      requestAnimationFrame(()=>{repairQueued=false;if(state.specialContext&&!$('sbbActiveSpecialChip')?.isConnected){syncSpecialContextUi();placeBrowseControls();}});
    });
    state.cfbObserver.observe(filters,{childList:true,subtree:true});
  }
  function isCoreLeague(league){return ['MLB','NFL','NBA','NHL','EPL','MLS','NCAAF'].includes(clean(league).toUpperCase());}
  function specialEventLabel(button,league){return clean(button?.textContent).replace(/[▾▼]/g,'').trim()||leagueLabel(league);}
  function specialEventShortLabel(league,label=''){
    const key=clean(league).toUpperCase();
    const fixed={'WC2026':'FIFA WC','WORLD-CUP-2026':'FIFA WC','FIFA-WORLD-CUP-2026':'FIFA WC','LLWS2026':'LLWS','USOPEN-2026':'US OPEN'};
    if(fixed[key])return fixed[key];
    const raw=clean(label)||leagueLabel(key);
    const compact=raw.replace(/\b20\d{2}\b/g,'').replace(/\bWORLD CUP\b/i,'WC').replace(/\s+/g,' ').trim();
    return compact.length<=12?compact:compact.split(/\s+/).map(x=>x[0]).join('').slice(0,10).toUpperCase();
  }
  function syncSpecialContextUi(){
    let chip=$('sbbActiveSpecialChip');const mlb=document.querySelector('#scoreFilters [data-score-filter="MLB"]');
    if(state.specialContext){
      if(!chip){
        chip=document.createElement('button');chip.id='sbbActiveSpecialChip';chip.type='button';
        chip.className='sbb-active-special-chip active';chip.tabIndex=-1;chip.setAttribute('aria-disabled','true');
      }
      // IMPORTANT: never give this presentation-only header data-score-filter.
      // The canonical score ribbon owns that namespace. The event context itself is
      // carried by state.specialContext, preserving the pre-v5.3.9 working browse
      // flow while still keeping FIFA WC / LLWS / US OPEN visible in the top row.
      chip.removeAttribute('data-score-filter');
      chip.dataset.sbbSpecialContext=state.specialContext.league;
      const shortLabel=specialEventShortLabel(state.specialContext.league,state.specialContext.label);
      if(chip.textContent!==shortLabel)chip.textContent=shortLabel;
      chip.title=`Active special event: ${state.specialContext.label}`;
      if(mlb&&chip.parentElement!==mlb.parentElement)mlb.insertAdjacentElement('beforebegin',chip);
      else if(mlb&&chip.nextElementSibling!==mlb)mlb.insertAdjacentElement('beforebegin',chip);
      chip.hidden=false;chip.classList.add('active');
    }else if(chip){chip.remove();}
    $('sbbSpecialExitBtn')?.classList.toggle('hidden',!state.specialContext);
  }
  function enterSpecialContext(league,label){
    league=clean(league).toUpperCase();if(!league||isCoreLeague(league)||league==='CFB')return false;
    state.specialContext={league,label:clean(label)||leagueLabel(league)};state.league=league;state.entityType=entityTypeFor(league);syncSpecialContextUi();syncLeagueUi();
    setTimeout(()=>activateHistorical({all:true}),0);
    window.dispatchEvent(new CustomEvent('sbb:special-context',{detail:{active:true,league,label:state.specialContext.label}}));return true;
  }
  function clearSpecialContext(){if(!state.specialContext)return;const prior=state.specialContext;state.specialContext=null;syncSpecialContextUi();window.dispatchEvent(new CustomEvent('sbb:special-context',{detail:{active:false,league:prior.league}}));}
  function syncLeagueUi(){
    hideLegacyCfb();syncSpecialContextUi();const nextLeague=selectedLeague(),previousLeague=state.league;
    if(previousLeague&&previousLeague!=='ALL'&&nextLeague!==previousLeague&&state.mode!=='daily'){
      state.mode='daily';state.entity='';state.facet='';state.games=[];state.entityAuditRows=[];state.selected.clear();state.error='';
      document.body.classList.remove('sbb-curation-active');setEntityTickerActive(false);$('sbbCurationRibbon')?.classList.add('hidden');
      window.dispatchEvent(new CustomEvent('sbb:browse-layout',{detail:{active:false,reason:'league-change'}}));
    }
    state.league=nextLeague;state.entityType=entityTypeFor(state.league);const eligible=state.league&&state.league!=='ALL';
    const subnav=$('sbbBrowseSubnav'),btn=$('sbbBrowseBtn');subnav?.classList.toggle('hidden',!eligible);
    if(!eligible){setOpen(false);return;}
    placeBrowseControls();
    const label=leagueLabel(state.league),browseWord=state.entityType==='player'?'PLAYER BROWSE':'TEAM BROWSE';
    if(btn)btn.innerHTML=`<span>${browseWord}</span><b aria-hidden="true">⌄</b>`;
    if($('sbbBrowseKicker'))$('sbbBrowseKicker').textContent=label;
    if($('sbbBrowseTitle'))$('sbbBrowseTitle').textContent=`${browseWord.replace(' BROWSE','')} Browse`;
    const entityWord=state.entityType==='player'?'PLAYERS':'TEAMS';if($('sbbBrowseSearchLabel'))$('sbbBrowseSearchLabel').textContent=`SEARCH ${entityWord}`;
    if($('sbbBrowseSearch'))$('sbbBrowseSearch').placeholder=state.entityType==='player'?'Search players':'Search teams';
    if($('sbbBrowseToday'))$('sbbBrowseToday').textContent=`TODAY'S ${label}`;
    if($('sbbBrowseAllHighlights'))$('sbbBrowseAllHighlights').textContent=`ALL ${label} HIGHLIGHTS`;
    const ranked=$('sbbBrowseRanked');if(ranked){const show=isCollegeFootball(state.league)||isTennis(state.league);ranked.classList.toggle('hidden',!show);ranked.textContent=isTennis(state.league)?'SEEDED TODAY':'RANKED TODAY';}
    if($('sbbCurationKicker'))$('sbbCurationKicker').textContent=browseWord;
    renderFavorites();if(state.open)positionPopover();
    if(eligible&&(!state.entityCatalogCache.has(state.league)||!entityCatalogFresh(state.league))&&!state.entityCatalogInflight.has(state.league))setTimeout(()=>primeEntityCatalog({render:false}),0);
  }

  function verifiedEntityNames(rows=[]){
    const seen=new Map();
    for(const row of rows||[]){
      if(!bestMediaForAuditRow(row).items.length)continue;
      for(const raw of splitGame(row?.game)){
        const display=clean(raw).replace(/^#?\d+\s+/,'');const key=norm(display);
        if(key&&!seen.has(key))seen.set(key,display);
      }
    }
    return [...seen.values()].sort((a,b)=>a.localeCompare(b));
  }
  async function fetchFullEntityCatalog(league,{forceMetadata=false}={}){
    const selected=clean(league).toUpperCase();if(!selected||selected==='ALL')return [];
    // v5.3.13 prefers the backend's persisted participant index. It is built from
    // all catalog events that own verified/playable media and is warmed in the
    // background, so opening Team/Player Browse does not scan the audit catalog.
    try{
      const params=new URLSearchParams({league:selected});if(forceMetadata)params.set('refreshMetadata','1');const response=await fetch(apiUrl(`/api/browse/participants?${params.toString()}`),{cache:'no-store'});let data={};try{data=await response.json();}catch(_){data={};}
      const entities=Array.isArray(data?.entities)?data.entities:[];const names=Array.isArray(data?.participants)?data.participants.map(clean).filter(Boolean):entities.map(x=>clean(x?.name)).filter(Boolean);
      if(response.ok&&data?.ok&&names.length){rememberEntityMetadata(selected,entities.length?entities:names.map(name=>({name})));return [...new Set(names)].sort((a,b)=>a.localeCompare(b));}
    }catch(_){}
    // Compatibility fallback for a backend that has not completed the v5.3.13
    // participant-index warmup yet.
    let offset=0,total=Infinity,rows=[];
    while(offset<total&&rows.length<MAX_ENTITY_AUDIT_ROWS){
      const params=new URLSearchParams({league:selected,limit:String(PAGE_SIZE),offset:String(offset)});
      const response=await fetch(apiUrl(`/api/history/audit?${params.toString()}`),{cache:'no-store'});let data={};try{data=await response.json();}catch(_){data={};}
      if(!response.ok||!data.ok)throw new Error(data.message||data.error||`HTTP ${response.status}`);
      const page=Array.isArray(data.rows)?data.rows:[];rows.push(...page);total=Number(data.total??rows.length);if(!page.length||page.length<PAGE_SIZE)break;offset+=page.length;
    }
    return verifiedEntityNames(rows);
  }
  function entityMetadataCoverage(league){
    const map=state.entityMetaCache.get(clean(league).toUpperCase());if(!map?.size)return 0;let rich=0;for(const row of map.values())if(clean(row?.logo))rich++;return rich/map.size;
  }
  async function primeEntityCatalog({render=true,forceRefresh=false}={}){
    const league=state.league;if(!league||league==='ALL')return [];
    const cached=state.entityCatalogCache.get(league)||[];
    if(cached.length&&render&&state.open&&state.league===league)renderSuggestions(cached,$('sbbBrowseSearch')?.value||'');
    const needsRefresh=forceRefresh||!cached.length||!entityCatalogFresh(league)||entityMetadataCoverage(league)<0.60;
    if(!needsRefresh)return cached;
    if(state.entityCatalogInflight.has(league)){
      const names=await state.entityCatalogInflight.get(league);if(render&&state.open&&state.league===league)renderSuggestions(names,$('sbbBrowseSearch')?.value||'');return names;
    }
    if(render&&state.open&&!cached.length){const host=$('sbbBrowseSuggestions');if(host)host.insertAdjacentHTML('afterbegin',`<div class="sbb-browse-cache-status">Building complete ${state.entityType==='player'?'player':'team'} library once; future opens are instant.</div>`);}
    const promise=fetchFullEntityCatalog(league,{forceMetadata:(isCoreLeague(league)||isTennis(league))&&entityMetadataCoverage(league)<0.75}).then(names=>{if(names.length){const meta=[...(state.entityMetaCache.get(league)?.values?.()||[])];persistEntityCatalog(league,names,meta);}return names.length?names:cached;}).finally(()=>state.entityCatalogInflight.delete(league));
    state.entityCatalogInflight.set(league,promise);
    try{const names=await promise;if(render&&state.open&&state.league===league)renderSuggestions(names,$('sbbBrowseSearch')?.value||'');return names;}catch(err){
      const fallback=cached.length?cached:currentEntities(league);if(render&&state.open&&state.league===league)renderSuggestions(fallback,$('sbbBrowseSearch')?.value||'');return fallback;
    }
  }

  function renderFavorites(){
    const host=$('sbbBrowseFavorites');if(!host)return;const fav=favoritesFor(state.league);host.classList.toggle('hidden',!fav.length);
    host.innerHTML=fav.length?`<span>★ FAVORITES</span>${fav.map(name=>`<button type="button" data-browse-entity="${esc(name)}">${esc(name)}</button>`).join('')}`:'';
  }
  function countryFlagGlyph(country){
    const raw=clean(country).toUpperCase();if(!raw)return '';
    const map={USA:'US',GBR:'GB',ENG:'GB',SCO:'GB',WAL:'GB',ESP:'ES',FRA:'FR',GER:'DE',DEU:'DE',ITA:'IT',AUS:'AU',CAN:'CA',BRA:'BR',ARG:'AR',MEX:'MX',JPN:'JP',CHN:'CN',KOR:'KR',SRB:'RS',CRO:'HR',CZE:'CZ',SVK:'SK',POL:'PL',SUI:'CH',CHE:'CH',AUT:'AT',BEL:'BE',NED:'NL',NLD:'NL',DEN:'DK',DNK:'DK',SWE:'SE',NOR:'NO',FIN:'FI',GRE:'GR',GRC:'GR',POR:'PT',PRT:'PT',ROU:'RO',BUL:'BG',UKR:'UA',KAZ:'KZ',RSA:'ZA',ZAF:'ZA',COL:'CO',CHI:'CL',CHL:'CL',PER:'PE',URU:'UY',ECU:'EC',NZL:'NZ'};
    const iso=(/^[A-Z]{2}$/.test(raw)?raw:map[raw]);if(!iso)return '';
    return String.fromCodePoint(...iso.split('').map(ch=>127397+ch.charCodeAt(0)));
  }
  function entityMark(meta,name){
    const logo=clean(meta?.logo);if(logo)return `<span class="sbb-browse-entity-logo"><img src="${esc(logo)}" alt="${esc(name)} ${state.entityType==='player'?'flag':'logo'}" loading="lazy"></span>`;
    const flag=state.entityType==='player'?countryFlagGlyph(meta?.country):'';
    if(flag)return `<span class="sbb-browse-entity-logo sbb-player-flag-glyph" role="img" aria-label="${esc(clean(meta?.country)||'country')} flag">${flag}</span>`;
    return `<span class="sbb-browse-entity-logo fallback">◇</span>`;
  }
  function renderSuggestions(names=[],query=''){
    const host=$('sbbBrowseSuggestions');if(!host)return;state.suggestionRows=Array.isArray(names)?names:[];
    const q=norm(query),merged=[];const seen=new Set();const source=[...favoritesFor(state.league),...(state.suggestionRows.length?state.suggestionRows:currentEntities(state.league))];
    for(const name of source){const key=norm(name);if(!key||seen.has(key)||(q&&!key.includes(q)))continue;seen.add(key);merged.push(clean(name));}
    merged.sort((a,b)=>(Number(isFavorite(state.league,b))-Number(isFavorite(state.league,a)))||a.localeCompare(b));
    if(!merged.length){host.innerHTML=`<div class="sbb-browse-empty">${query?'No matching '+(state.entityType==='player'?'players':'teams')+' with verified highlights found.':'No '+(state.entityType==='player'?'players':'teams')+' with verified highlights are available yet.'}</div>`;return;}
    host.innerHTML=merged.map(name=>{const meta=entityMetaFor(name);return `<div class="sbb-browse-suggestion"><button class="sbb-browse-entity" type="button" data-browse-entity="${esc(name)}">${entityMark(meta,name)}<span class="sbb-browse-entity-name">${esc(name)}</span><small>ALL DATES</small></button><button class="sbb-browse-star ${isFavorite(state.league,name)?'active':''}" type="button" data-browse-star="${esc(name)}" aria-label="${isFavorite(state.league,name)?'Remove':'Add'} ${esc(name)} favorite">${isFavorite(state.league,name)?'★':'☆'}</button></div>`}).join('');
  }
  async function searchSuggestions(value){
    const query=clean(value);state.lastQuery=query;const names=await primeEntityCatalog({render:false});if(query!==state.lastQuery)return;renderSuggestions(names,query);
  }

  function firstDefined(...values){for(const value of values){if(value!==undefined&&value!==null&&String(value)!=='')return value;}return null;}
  function scoreValue(source,side){
    const team=source?.[side]||source?.[`${side}Team`]||source?.competitors?.find?.(x=>String(x?.homeAway||x?.side||'').toLowerCase()===side)||{};
    const raw=firstDefined(source?.[`${side}Score`],source?.score?.[side],source?.scores?.[side],team?.score?.value,team?.score,team?.points,team?.runs);
    if(raw===null)return null;const s=clean(raw);return s===''?null:s;
  }
  function gameScore(game){
    const sources=[game?.scoreMatch,game?.match,game?.row,game?.items?.[0]].filter(Boolean);
    for(const source of sources){const away=scoreValue(source,'away'),home=scoreValue(source,'home');if(away!==null&&home!==null)return {away,home};}
    const raw=clean(game?.row?.score||game?.row?.finalScore);const m=raw.match(/(\d+)\s*[-–:]\s*(\d+)/);return m?{away:m[1],home:m[2]}:null;
  }
  function scoreDisplay(game){
    const score=gameScore(game);if(!score)return {text:'',result:''};
    if(!state.entity)return {text:`${score.away}–${score.home}`,result:''};
    const parts=splitGame(game.game),key=norm(state.entity);let mine=null,theirs=null;
    if(parts.length>=2&&norm(parts[0])===key){mine=Number(score.away);theirs=Number(score.home);}else if(parts.length>=2&&norm(parts[1])===key){mine=Number(score.home);theirs=Number(score.away);}
    if(Number.isFinite(mine)&&Number.isFinite(theirs)){const result=mine>theirs?'W':mine<theirs?'L':'T';return {text:`${mine}–${theirs}`,result};}
    return {text:`${score.away}–${score.home}`,result:''};
  }
  function scoreRowItems(payload){
    if(Array.isArray(payload))return payload;
    for(const key of ['items','events','rows','scores','games','data'])if(Array.isArray(payload?.[key]))return payload[key];
    return [];
  }
  function matchScoreRow(game,rows){
    const id=clean(game?.eventId);if(id){const direct=(rows||[]).find(x=>[x?.eventId,x?.id,x?.matchId,x?.espnEventId,x?.gamePk,x?.scoreEventId].some(v=>clean(v)===id));if(direct)return direct;}
    const parts=splitGame(game?.game);if(parts.length<2)return null;
    return (rows||[]).find(row=>{const a=participantName(teamObject(row,'away')),h=participantName(teamObject(row,'home'));return norm(a)===norm(parts[0])&&norm(h)===norm(parts[1]);})||null;
  }
  async function fetchScoreDate(date,league){
    const cacheKey=`${league}:${date}`;if(state.scoreDateCache.has(cacheKey))return state.scoreDateCache.get(cacheKey);if(state.scoreDateInflight.has(cacheKey))return state.scoreDateInflight.get(cacheKey);
    const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone||'Etc/UTC',utcOffsetMinutes=-new Date().getTimezoneOffset();
    const p=new URLSearchParams({date,league,timezone,utcOffsetMinutes:String(utcOffsetMinutes)});
    const promise=fetch(apiUrl(`/api/history/scores?${p.toString()}`),{cache:'no-store'}).then(async r=>{let data={};try{data=await r.json();}catch(_){data={};}if(!r.ok)throw new Error(data?.message||`HTTP ${r.status}`);const rows=scoreRowItems(data);state.scoreDateCache.set(cacheKey,rows);return rows;}).catch(()=>[]).finally(()=>state.scoreDateInflight.delete(cacheKey));
    state.scoreDateInflight.set(cacheKey,promise);return promise;
  }
  function updateCardScore(index){
    const game=state.games[index],node=document.querySelector(`[data-curation-index="${index}"] .sbb-curation-result`);if(!game||!node)return;const score=scoreDisplay(game);node.textContent=score.text?(score.result?`${score.result} ${score.text}`:score.text):'';node.dataset.result=score.result||'';node.classList.toggle('hidden',!score.text);
  }
  async function enrichGameScore(index){
    const game=state.games[index];if(!game||game.scoreMatch||!game.date||!game.league)return;const rows=await fetchScoreDate(game.date,game.league);const match=matchScoreRow(game,rows);if(match){game.scoreMatch=match;updateCardScore(index);}
  }
  function observeVisibleScores(){
    try{state.scoreObserver?.disconnect?.();}catch(_){}state.scoreObserver=null;
    const cards=[...document.querySelectorAll('#sbbCurationCards [data-curation-index]')];if(!cards.length)return;
    if(!('IntersectionObserver'in window)){cards.slice(0,12).forEach(card=>enrichGameScore(Number(card.dataset.curationIndex)));return;}
    state.scoreObserver=new IntersectionObserver(entries=>{for(const entry of entries){if(!entry.isIntersecting)continue;const card=entry.target;state.scoreObserver?.unobserve(card);enrichGameScore(Number(card.dataset.curationIndex));}},{root:$('sbbCurationCards'),rootMargin:'0px 700px 0px 700px',threshold:.01});
    cards.forEach(card=>state.scoreObserver.observe(card));
  }
  function datePill(value){if(!value)return 'DATE';try{return new Date(`${value}T12:00:00`).toLocaleDateString(undefined,{month:'short',day:'numeric'}).toUpperCase();}catch(_){return value;}}
  function tierClass(tier){return ['gold','green','extended','blue'].includes(clean(tier).toLowerCase())?clean(tier).toLowerCase():'blue';}

  function describeGame(game){
    if(!state.entity)return game.game;
    const parts=splitGame(game.game);if(parts.length<2)return game.game;
    return entityMatchupLabel(parts[0],parts[1],state.entity);
  }
  function dateLabel(value){if(!value)return 'DATE —';try{return new Date(`${value}T12:00:00`).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}).toUpperCase();}catch(_){return value;}}
  function tierLabel(tier){return ({gold:'GOLD',green:'FULL RECAP',extended:'EXTENDED',blue:'HIGHLIGHTS',none:'NO MEDIA YET'})[tier]||clean(tier).toUpperCase()||'RECAP';}
  function cardThumb(game){const item=game.items?.[0]||{};const raw=bestMediaForAuditRow(game?.row||{}).items?.[0]||{};const rawYt=clean(raw?.youtubeId)||youtubeIdFrom(raw?.providerMediaId)||youtubeIdFrom(raw?.canonicalUrl||raw?.url);const meta=entityMetaFor(state.entity);return clean(item.thumbnail)||clean(raw?.thumbnail)||clean(raw?.thumbnailUrl)||clean(raw?.image)||clean(raw?.poster)||(item.youtubeId?`https://i.ytimg.com/vi/${item.youtubeId}/mqdefault.jpg`:'')||(rawYt?`https://i.ytimg.com/vi/${rawYt}/mqdefault.jpg`:'')||clean(state.teamFocusData?.team?.logo||meta.logo);}
  function renderCuration(){
    const ribbon=$('sbbCurationRibbon'),cards=$('sbbCurationCards');if(!ribbon||!cards)return;
    const active=state.mode!=='daily';if(active)captureScoreRibbonHeight();document.body.classList.toggle('sbb-curation-active',active);ribbon.hidden=!active;ribbon.classList.toggle('hidden',!active);syncLeagueUi();
    window.dispatchEvent(new CustomEvent('sbb:browse-layout',{detail:{active}}));
    if(!active){setEntityTickerActive(false);clearTeamTheme();return;}
    const playableCount=queueItemsForGames(state.games).length;
    const focusPlay=$('sbbFocusPlayAll');if(focusPlay){focusPlay.disabled=state.loading||!playableCount;focusPlay.textContent='Play All';}
    const focusExit=$('sbbFocusExit');if(focusExit)focusExit.textContent='Exit Event';
    if(state.entity)scheduleEntityTickerRefresh();else setEntityTickerActive(false);
    if(state.loading){cards.innerHTML='<div class="sbb-curation-loading"><span></span><strong>Building team timeline…</strong></div>';return;}
    if(state.error){cards.innerHTML=`<div class="sbb-curation-empty"><strong>Browse unavailable</strong><span>${esc(state.error)}</span></div>`;return;}
    if(!state.games.length){cards.innerHTML='<div class="sbb-curation-empty"><strong>No games found</strong><span>Try another team/player or return to the daily scoreboard.</span></div>';return;}
    cards.innerHTML=state.games.map((game,i)=>{
      const available=!!game.items?.length,thumb=cardThumb(game),score=scoreDisplay(game),tier=tierClass(game.tier),matchup=describeGame(game);
      const tierName=available?tierLabel(game.tier):'NO MEDIA YET';
      const shellClass=available?'':' no-media';
      const actionAttrs=available?`data-curation-index="${i}" tabindex="0" role="button" aria-label="Play ${esc(matchup)} and continue with older highlights"`:`data-curation-index="${i}" aria-disabled="true"`;
      return `<div class="sbb-curation-card-shell${shellClass}"><span class="sbb-curation-date-pill">${esc(datePill(game.date))}</span><article class="sbb-curation-card${shellClass}" ${actionAttrs}><div class="sbb-curation-thumb">${thumb?`<img src="${esc(thumb)}" alt="" loading="lazy">`:`<div class="sbb-curation-thumb-fallback">${esc(game.league)}</div>`}${available?'<span class="sbb-curation-play">▶</span>':'<span class="sbb-curation-no-media-mark">—</span>'}</div><div class="sbb-curation-card-copy"><strong>${esc(matchup)}</strong><span class="sbb-curation-result ${score.text?'':'hidden'}" data-result="${esc(score.result)}">${esc(score.text?(score.result?`${score.result} ${score.text}`:score.text):'')}</span><span class="sbb-curation-media-tier ${available?`tier-${tier}`:'tier-none'}">${esc(tierName)}</span></div></article></div>`;
    }).join('');
    observeVisibleScores();
  }

  async function activateHistorical({entity='',all=false}={}){
    setOpen(false);
    state.mode='history';state.entity=clean(entity);state.facet=all?'ALL HIGHLIGHTS':'';state.loading=true;state.error='';state.games=[];state.selected.clear();state.teamFocusData=null;state.teamFocusKey='';renderCuration();
    const autoPlayEntity=state.entityType==='team'?state.entity:'';
    const autoPlayLeague=state.league;
    if(state.entity&&state.entityType!=='player')loadTeamFocusData().then(()=>{if(state.mode!=='daily'&&state.entity){scheduleEntityTickerRefresh();renderCuration();}});
    try{
      const rows=await fetchAuditRows(state.league,state.entity,MAX_AUDIT_ROWS);const filtered=state.entity?rows.filter(row=>gameHasEntity(row?.game,state.entity)):rows;
      state.entityAuditRows=state.entity?filtered.slice():[];
      const today=new Date(),todayLocal=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
      // Team/Player highlight history is a backward-looking rail: today is the hard
      // cutoff. Future schedule rows remain in entityAuditRows solely for NEXT ticker
      // context and never appear as future cards in the highlight timeline.
      const timelineRows=state.entity?filtered.filter(row=>!auditDate(row)||auditDate(row)<=todayLocal):filtered;
      const built=timelineRows.map(gameFromAuditRow).filter(Boolean);
      state.games=(state.entity?built:built.filter(game=>game.items?.length)).sort((a,b)=>String(b.date).localeCompare(String(a.date))||String(b.eventId).localeCompare(String(a.eventId)));
    }catch(err){if(err?.name==='AbortError')return;state.error=`Could not load ${leagueLabel(state.league)} highlights: ${err?.message||err}`;}
    finally{
      state.loading=false;renderCuration();
      // Entering a TEAM context is a tune action, not merely a filter action.
      // Start the newest playable game automatically, while keeping older games
      // queued in newest-to-oldest order. Player Browse and league-wide Browse
      // remain browse-only until the user explicitly chooses a clip.
      if(autoPlayEntity&&state.mode==='history'&&state.entity===autoPlayEntity&&state.league===autoPlayLeague&&!state.error){
        const newestPlayable=state.games.findIndex(game=>Array.isArray(game?.items)&&game.items.length);
        if(newestPlayable>=0)setTimeout(()=>{if(state.mode==='history'&&state.entity===autoPlayEntity&&state.league===autoPlayLeague)playFrom(newestPlayable);},0);
      }
    }
  }
  function rankedResidentGames(){
    const tennis=isTennis(state.league);return currentMatches(state.league).filter(match=>{
      const a=participantRank(teamObject(match,'away')),h=participantRank(teamObject(match,'home'));
      return tennis?(a>0||h>0):((a>0&&a<=25)||(h>0&&h<=25));
    }).map(gameFromResident).filter(Boolean).sort((a,b)=>String(b.date).localeCompare(String(a.date)));
  }
  function activateRanked(){captureScoreRibbonHeight();state.mode='facet';state.entity='';state.facet=isTennis(state.league)?'SEEDED TODAY':'RANKED TODAY';state.error='';state.loading=false;state.selected.clear();state.entityAuditRows=[];state.games=rankedResidentGames();setOpen(false);renderCuration();}
  function stopCuratedOwnershipGuard(){
    state.curatedOwnershipEpoch++;
    if(state.curatedGuardTimer){clearTimeout(state.curatedGuardTimer);state.curatedGuardTimer=null;}
    state.curatedExpectedIndex=0;state.curatedExpectedKey='';state.curatedGuardBusy=false;
    try{delete document.body.dataset.sbbCuratedPlaybackOwner;}catch(_){}
  }
  function releaseCuratedQueue(reason='return to daily programming'){
    stopCuratedOwnershipGuard();
    // v5.3.13: curated Team/Player/Special Event queues are user-owned only while
    // Browse is active. Returning to ALL/TODAY must surrender queue ownership
    // immediately so the next score-card click can build the selected date queue.
    // Leaving queueActive true caused renderQueue() to resurrect a World Cup queue
    // after an MLB score click even though the visible filter had returned to ALL.
    const hadQueue=!!state.queueActive;
    state.queueActive=false;state.queueItems=[];state.queueLabel='';state.curatedAlternates.clear();state.failedCuratedMedia.clear();restoreCuratedGameCenterFallback();
    state.preProgram=null;state.preGeneral=null;
    try{window.SBB_SCORE_INTERRUPT_QUEUE?.clear?.(reason);}catch(_){}
    try{if(typeof userPlaybackSession!=='undefined'&&userPlaybackSession?.source!=='score')userPlaybackSession=null;}catch(_){}
    try{window.dispatchEvent(new CustomEvent('sbb:curated-queue-release',{detail:{reason,hadQueue}}));}catch(_){}
    return hadQueue;
  }
  function returnToDay(){releaseCuratedQueue('browse returned to daily programming');state.mode='daily';state.entity='';state.facet='';state.games=[];state.entityAuditRows=[];state.selected.clear();state.error='';state.teamFocusData=null;state.teamFocusKey='';document.body.classList.remove('sbb-curation-active');setEntityTickerActive(false);clearTeamTheme();const ribbon=$('sbbCurationRibbon');if(ribbon){ribbon.hidden=true;ribbon.classList.add('hidden');}syncLeagueUi();captureScoreRibbonHeight();window.dispatchEvent(new CustomEvent('sbb:browse-layout',{detail:{active:false}}));}
  function returnToAll(){setOpen(false);clearSpecialContext();returnToDay();setTimeout(()=>{const all=document.querySelector('#scoreFilters [data-score-filter="ALL"]');if(all&&typeof all.click==='function')all.click();else{try{scoreRibbonLeagueFilter='ALL';renderScoreRibbon?.();}catch(_){}}},0);}

  function queueItemsForGames(games){const out=[];const seen=new Set();for(const game of games||[])for(const item of game.items||[]){const key=clean(item.id||item.youtubeId||item.mediaUrl);if(!key||seen.has(key))continue;seen.add(key);out.push(item);}return out;}
  function programKey(item){return clean(item?.id||item?.youtubeId||item?.mediaUrl);}
  function queueMatchesActive(){
    try{if(!Array.isArray(PROGRAM)||PROGRAM.length!==state.queueItems.length)return false;return PROGRAM.every((x,i)=>programKey(x)===programKey(state.queueItems[i]));}catch(_){return false;}
  }
  function gameCenterSupportedForItem(item){
    if(!item)return false;
    const league=clean(item?.competitionId||item?.league||state.league).toUpperCase();
    try{if(typeof gameCenterCompetitionSupported==='function')return !!gameCenterCompetitionSupported(item);}catch(_){}
    return !isTennis(league) && !/LLWS/.test(league);
  }
  function restoreCuratedGameCenterFallback(){
    const empty=$('gameCenterEmpty');if(!empty||empty.dataset.sbbCuratedMatch!=='1')return;delete empty.dataset.sbbCuratedMatch;
    const strong=empty.querySelector('strong');if(strong)strong.textContent='GAME CENTER';
    const span=empty.querySelector('span');if(span)span.textContent='Select a game from the score ribbon to see its scoreboard, stats, players and plays.';
  }
  function showCuratedGameCenterFallback(item){
    const empty=$('gameCenterEmpty'),content=$('gameCenterContent');if(!empty)return;
    const away=participantName(item?.awayTeam||item?.away)||clean(item?.awayName||item?.away),home=participantName(item?.homeTeam||item?.home)||clean(item?.homeName||item?.home);
    const matchup=away&&home?`${away} vs ${home}`:clean(item?.queueTitle||item?.title)||'SPECIAL EVENT MATCH';
    const league=leagueLabel(clean(item?.competitionId||item?.league||state.league).toUpperCase()),date=clean(item?.date).slice(0,10);
    empty.dataset.sbbCuratedMatch='1';const strong=empty.querySelector('strong');if(strong)strong.textContent=matchup.toUpperCase();
    const span=empty.querySelector('span');if(span)span.textContent=`${league}${date?` · ${date}`:''} · This selected special-event match does not expose the full standard Game Center feed.`;
    empty.classList.remove('hidden');content?.classList.add('hidden');
  }
  function curatedEventIdentity(item){
    if(!item?.__sbbCuratedOverride)return null;
    const league=clean(item.competitionId||item.league||state.league).toUpperCase();
    const eventId=clean(item.gameCenterEventId||item.espnEventId||item.scoreEventId||item.eventId||item.matchId||item.gamePk);
    if(!league||!eventId)return null;
    const away=item.awayTeam||item.away||{},home=item.homeTeam||item.home||{};
    return {
      competitionId:league,eventId,scoreEventId:clean(item.scoreEventId||item.eventId||eventId),espnEventId:clean(item.espnEventId||''),
      gameCenterEventId:eventId,matchId:clean(item.matchId||item.eventId||eventId),gamePk:clean(item.gamePk||''),
      canonicalEventKey:clean(item.canonicalEventKey)||`${league}:${clean(item.eventId||eventId)}`,
      date:clean(item.date||item.gameDate||item.scheduledGameDate).slice(0,10),scheduledAt:clean(item.scheduledAt||item.date||item.gameDate),
      awayTeam:{...away,name:participantName(away),displayName:participantName(away)},
      homeTeam:{...home,name:participantName(home),displayName:participantName(home)},
      awayScore:item.awayScore??null,homeScore:item.homeScore??null,gameCenterProviderHint:clean(item.gameCenterProviderHint||''),
    };
  }
  function syncCuratedSelectedEvent(item,{deferRepair=false}={}){
    try{if(window.SBB_SCORE_INTERRUPT_QUEUE?.active?.())return false;}catch(_){}
    const event=curatedEventIdentity(item);if(!event||!gameCenterSupportedForItem(item))return false;
    try{
      const current=window.SBB_SELECTED_EVENT?.get?.();const currentKey=window.SBB_SELECTED_EVENT?.keyOf?.(current),nextKey=window.SBB_SELECTED_EVENT?.keyOf?.(event);
      if(currentKey&&nextKey&&currentKey!==nextKey)window.SBB_SELECTED_EVENT?.clear?.({source:'browse',reason:'replace stale Game Center identity',force:true});
      window.SBB_SELECTED_EVENT?.select?.(event,{source:'browse',reason:'curated playback event identity'});
    }catch(_){}
    try{window.dispatchEvent(new CustomEvent('sbb:curated-event-identity',{detail:{event,item}}));}catch(_){}
    const repair=()=>{try{window.SBB_GAME_CENTER_SCROLL?.repair?.();}catch(_){}};if(deferRepair)setTimeout(repair,40);else repair();
    return true;
  }
  function syncCuratedGameCenterContext(item){
    const curated=!!item?.__sbbCuratedOverride;
    const unsupported=curated&&!gameCenterSupportedForItem(item);
    const body=document.body,was=body?.classList.contains('sbb-curated-no-game-center');
    body?.classList.toggle('sbb-curated-no-game-center',unsupported);
    if(unsupported){
      // v5.3.3 compatibility contract: window.SBB_SELECTED_EVENT?.clear?.({reason:'curated competition has no Game Center' now carries the selected-match reason below.
      try{window.SBB_SELECTED_EVENT?.clear?.({reason:'selected curated match has no standard Game Center provider',source:'browse',force:true});}catch(_){}
      showCuratedGameCenterFallback(item);
      try{window.SBB_GAME_CENTER_SCROLL?.repair?.();}catch(_){}
    }else if(curated){
      restoreCuratedGameCenterFallback();syncCuratedSelectedEvent(item,{deferRepair:true});
      if(was){try{window.SBB_GAME_CENTER_SCROLL?.repair?.();}catch(_){}}
    }else{restoreCuratedGameCenterFallback();}
    return !unsupported;
  }
  function rememberProgram(){
    if(state.queueActive)return;
    try{state.preProgram=Array.isArray(PROGRAM)?[...PROGRAM]:null;}catch(_){state.preProgram=null;}
    try{state.preGeneral=Array.isArray(GENERAL_PROGRAM)?[...GENERAL_PROGRAM]:null;}catch(_){state.preGeneral=null;}
  }
  function primeCuratedAlternates(games=[]){
    state.curatedAlternates.clear();state.failedCuratedMedia.clear();
    for(const game of games||[]){if(game?.key)state.curatedAlternates.set(game.key,(game.alternates||[]).slice());}
  }
  function specialEventOwnsPlayback(){return !!(state.specialContext&&state.queueActive&&state.queueItems.length);}
  function clearLegacyScoreOwnership(reason='special-event playback ownership'){
    try{window.SBB_SCORE_INTERRUPT_QUEUE?.clear?.(reason);}catch(_){}
    try{if(typeof cancelUserPlaybackSession==='function')cancelUserPlaybackSession();}catch(_){}
    try{if(typeof userPlaybackSession!=='undefined')userPlaybackSession=null;}catch(_){}
  }
  function clearStalePlaybackPresentation(){
    // A new curated selection must never reveal the previous game's external
    // fallback card while its own transport is starting. v5.3.12 only removed
    // bumper classes, which left the old MLB fallback visibly mounted.
    try{sbbPauseAllPlayback?.();}catch(_){}
    try{clearPlaybackRecovery?.();}catch(_){}
    try{setVideoLoadingOverlay?.(true);}catch(_){}
    try{
      const bumper=$('bumper');bumper?.classList.add('hidden');bumper?.classList.remove('external-fallback','needs-tap');
      const action=$('bumperAction');if(action){action.classList.add('hidden');action.textContent='';}
      if(typeof playbackExternalFallbackUrl!=='undefined')playbackExternalFallbackUrl='';
    }catch(_){}
  }
  function expectedCuratedItem(){
    const idx=Math.max(0,Math.min(Number(state.curatedExpectedIndex)||0,Math.max(0,state.queueItems.length-1)));
    return state.queueItems[idx]||state.queueItems[0]||null;
  }
  function enforceCuratedOwnership(reason='curated ownership guard'){
    if(!specialEventOwnsPlayback()||state.curatedGuardBusy)return false;
    const item=expectedCuratedItem();if(!item)return false;state.curatedGuardBusy=true;
    try{
      document.body.dataset.sbbCuratedPlaybackOwner=clean(state.specialContext?.league||item?.competitionId||item?.league||'SPECIAL');
      // A stale score interrupt or score playback session is never allowed to
      // outrank an explicitly active Special Event queue.
      clearLegacyScoreOwnership(reason);
      if(!queueMatchesActive()){PROGRAM=[...state.queueItems];try{GENERAL_PROGRAM=[...state.queueItems];}catch(_){}}
      let active=null;try{active=typeof clip==='function'?clip(currentIndex):null;}catch(_){}
      const expectedKey=programKey(item),activeKey=programKey(active);
      if(!active?.__sbbCuratedOverride||activeKey!==expectedKey){
        const idx=Math.max(0,Math.min(Number(state.curatedExpectedIndex)||0,state.queueItems.length-1));
        try{currentIndex=idx;standbyIndex=idx;}catch(_){}
        clearStalePlaybackPresentation();
        if(typeof tuneProgramIndexV5==='function')tuneProgramIndexV5(idx,{userInitiated:false,reason:`v5.3.13 ownership repair: ${reason}`});
      }
      syncCuratedGameCenterContext(item);
      return true;
    }finally{state.curatedGuardBusy=false;}
  }
  function startCuratedOwnershipGuard(index,item){
    stopCuratedOwnershipGuard();
    state.curatedExpectedIndex=Math.max(0,Number(index)||0);state.curatedExpectedKey=programKey(item);
    const epoch=++state.curatedOwnershipEpoch;
    document.body.dataset.sbbCuratedPlaybackOwner=clean(state.specialContext?.league||item?.competitionId||item?.league||'CURATED');
    for(const ms of [0,100,300,750,1500,3000])setTimeout(()=>{if(epoch===state.curatedOwnershipEpoch)enforceCuratedOwnership(`bounded ${ms}ms reconciliation`);},ms);
    const steadyGuard=()=>{
      if(epoch!==state.curatedOwnershipEpoch)return;
      if(!specialEventOwnsPlayback()){stopCuratedOwnershipGuard();return;}
      enforceCuratedOwnership('special-event steady-state');
      state.curatedGuardTimer=setTimeout(steadyGuard,900);
    };
    state.curatedGuardTimer=setTimeout(steadyGuard,900);
  }
  function tuneCuratedIndex(index,{reason='curated programming',userInitiated=true}={}){
    const item=state.queueItems[index];if(!item||typeof tuneProgramIndexV5!=='function')return false;
    clearStalePlaybackPresentation();
    // Commit the curated PROGRAM index BEFORE tuning. If the transport fails
    // synchronously, handlePlaybackFailure must see the selected World Cup/LLWS/
    // US Open item, never the previously playing MLB clip.
    try{PROGRAM=[...state.queueItems];GENERAL_PROGRAM=[...state.queueItems];currentIndex=index;standbyIndex=index;}catch(_){}
    if(specialEventOwnsPlayback())clearLegacyScoreOwnership('special-event tune');
    syncCuratedGameCenterContext(item);
    startCuratedOwnershipGuard(index,item);
    tuneProgramIndexV5(index,{userInitiated,reason});
    // v5.3.5 compatibility contract: setTimeout(()=>syncCuratedGameCenterContext(selected),180) is superseded by the bounded reconciliation below.
    // Reassert selected-event/Game Center authority long enough to outlive any
    // stale async MLB response that was already in flight when the event changed.
    for(const ms of [0,120,420,900,1600,3000])setTimeout(()=>{if(state.queueActive&&state.queueItems[index]===item)syncCuratedGameCenterContext(item);},ms);
    return true;
  }
  function activateQueue(items,label,startIndex=0){
    if(!items.length)return false;rememberProgram();state.queueActive=true;state.queueItems=[...items];state.queueLabel=label;
    clearLegacyScoreOwnership('curated programming queue start');
    // Stop/hide the prior transport before changing queue identity. This prevents a
    // non-embeddable World Cup selection from leaving an audible/visible MLB asset
    // under the Special Event shell while fallback resolution runs.
    clearStalePlaybackPresentation();
    try{PROGRAM=[...state.queueItems];}catch(err){console.warn('[SBB Browse] PROGRAM assignment failed',err);return false;}
    try{GENERAL_PROGRAM=[...state.queueItems];}catch(_){}
    const bounded=Math.max(0,Math.min(Number(startIndex)||0,state.queueItems.length-1));
    syncCuratedGameCenterContext(state.queueItems[bounded]);
    try{if(typeof renderQueue==='function')renderQueue();}catch(_){}
    try{if(typeof setFeedNote==='function')setFeedNote(`Curated programming • ${label} • ${state.queueItems.length} video${state.queueItems.length===1?'':'s'}`);}catch(_){}
    // v5.3.0 compatibility contract: tuneProgramIndexV5(bounded is now delegated
    // through tuneCuratedIndex so stale fallback UI and Game Center clear first.
    return tuneCuratedIndex(bounded,{userInitiated:true,reason:`v5.3.13 curated programming: ${label}`});
  }
  function playGames(games,label){primeCuratedAlternates(games);return activateQueue(queueItemsForGames(games),label,0);}
  function playFrom(index){const games=state.games.slice(index);if(!games.length)return false;return playGames(games,state.entity||state.facet||`${leagueLabel(state.league)} highlights`);}
  function playAll(){return playGames(state.games,state.entity||state.facet||`${leagueLabel(state.league)} highlights`);}
  function patchRenderQueue(){
    try{
      if(typeof renderQueue!=='function'||renderQueue.__sbbBrowseV537)return false;const original=renderQueue;
      const wrapped=function(...args){
        // Background score/news refreshes may rebuild GENERAL_PROGRAM. While a
        // user explicitly owns a curated queue, restore that queue before the
        // presentation layer renders it. Score interrupts remain authoritative.
        try{
          const interrupted=window.SBB_SCORE_INTERRUPT_QUEUE?.active?.();
          const specialOwns=specialEventOwnsPlayback();
          if(state.queueActive&&(!interrupted||specialOwns)&&!queueMatchesActive()){
            if(specialOwns)clearLegacyScoreOwnership('renderQueue curated ownership repair');
            let current='';try{current=programKey(clip(currentIndex));}catch(_){}
            PROGRAM=[...state.queueItems];try{GENERAL_PROGRAM=[...state.queueItems];}catch(_){}
            if(current){const idx=PROGRAM.findIndex(x=>programKey(x)===current);if(idx>=0)currentIndex=idx;}
            if(specialOwns&&(!PROGRAM[currentIndex]?.__sbbCuratedOverride)){currentIndex=Math.max(0,Math.min(state.curatedExpectedIndex,state.queueItems.length-1));standbyIndex=currentIndex;}
          }
        }catch(_){}
        let result;
        try{result=original.apply(this,args);}finally{
          try{syncCuratedGameCenterContext(typeof clip==='function'?clip(currentIndex):null);}catch(_){}
        }
        return result;
      };
      wrapped.__sbbBrowseV537=true;wrapped.__sbbOriginal=original;renderQueue=wrapped;try{window.renderQueue=wrapped;}catch(_){}state.renderQueuePatched=true;return true;
    }catch(_){return false;}
  }

  function curatedDirectUrl(item){const yt=clean(item?.youtubeId);return yt?`https://www.youtube.com/watch?v=${encodeURIComponent(yt)}`:clean(item?.mediaUrl||item?.url);}
  function showCuratedUnavailable(item,reason='Curated video unavailable'){
    try{sbbPauseAllPlayback?.();}catch(_){}try{setVideoLoadingOverlay?.(false);}catch(_){}
    syncCuratedGameCenterContext(item);const url=curatedDirectUrl(item);
    try{if(typeof playbackExternalFallbackUrl!=='undefined')playbackExternalFallbackUrl=url;}catch(_){}
    const kicker=$('bumperKicker');if(kicker)kicker.textContent=url?'WATCH ON YOUTUBE':'VIDEO UNAVAILABLE';
    const subtitle=$('bumperSubtitle');if(subtitle)subtitle.textContent=url?'This exact special-event highlight could not start in the embedded player. Open it directly or choose another match.':clean(reason);
    const action=$('bumperAction');if(action){action.textContent=url?'↗ OPEN OFFICIAL HIGHLIGHTS':'';action.classList.toggle('hidden',!url);}
    $('bumper')?.classList.remove('hidden','needs-tap');if(url)$('bumper')?.classList.add('external-fallback');
  }
  function patchPlaybackFailure(){
    try{
      if(typeof handlePlaybackFailure!=='function'||handlePlaybackFailure.__sbbBrowseV5313)return false;const original=handlePlaybackFailure;
      const wrapped=function(slot,err,userInitiated=false){
        let item=null;try{item=typeof clip==='function'?clip(currentIndex):null;}catch(_){}
        let interrupted=false;try{interrupted=!!window.SBB_SCORE_INTERRUPT_QUEUE?.active?.();}catch(_){}
        const specialOwns=specialEventOwnsPlayback();
        // When a Special Event is active, a stale score-interrupt flag from the
        // previously viewed MLB game is not a legitimate playback owner.
        if(specialOwns&&(!item?.__sbbCuratedOverride||programKey(item)!==state.curatedExpectedKey))item=expectedCuratedItem();
        if(state.queueActive&&item?.__sbbCuratedOverride&&(!interrupted||specialOwns)){
          if(specialOwns)clearLegacyScoreOwnership('curated playback failure');
          const failedKey=programKey(item);if(failedKey)state.failedCuratedMedia.add(failedKey);
          try{markRuntimeMediaFailed?.(item,err?.message||'curated playback failure');}catch(_){}
          const gameKey=clean(item.__sbbCuratedGameKey);const alternates=(state.curatedAlternates.get(gameKey)||[]);
          const alt=alternates.find(candidate=>{const key=programKey(candidate);if(!key||state.failedCuratedMedia.has(key))return false;try{return typeof runtimeMediaUsable==='function'?runtimeMediaUsable(candidate):true;}catch(_){return true;}});
          if(alt){
            const idx=Math.max(0,Math.min(Number(currentIndex)||0,state.queueItems.length-1));state.queueItems[idx]=alt;try{PROGRAM[idx]=alt;GENERAL_PROGRAM[idx]=alt;}catch(_){}
            return tuneCuratedIndex(idx,{userInitiated:false,reason:'v5.3.13 same-game curated fallback'});
          }
          const start=Math.max(0,Number(currentIndex)||0);let next=-1;
          for(let i=start+1;i<state.queueItems.length;i++){const candidate=state.queueItems[i],key=programKey(candidate);if(candidate&&(!key||!state.failedCuratedMedia.has(key))){next=i;break;}}
          if(next>=0)return tuneCuratedIndex(next,{userInitiated:false,reason:'v5.3.13 next special-event highlight after unavailable source'});
          showCuratedUnavailable(item,err?.message||err);return;
        }
        return original.call(this,slot,err,userInitiated);
      };
      wrapped.__sbbBrowseV5313=true;wrapped.__sbbOriginal=original;handlePlaybackFailure=wrapped;try{window.handlePlaybackFailure=wrapped;}catch(_){}state.playbackFailurePatched=true;return true;
    }catch(_){return false;}
  }

  function bind(){
    $('sbbBrowseBtn')?.addEventListener('click',()=>setOpen(!state.open));
    $('sbbBrowseClose')?.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();setOpen(false);});
    $('sbbBrowsePopover')?.addEventListener('click',event=>{if(event.target.closest('#sbbBrowseClose')){event.preventDefault();event.stopPropagation();setOpen(false);}});
    $('sbbBrowseToday')?.addEventListener('click',()=>{setOpen(false);returnToDay();});
    $('returnTodayBtn')?.addEventListener('click',()=>{clearSpecialContext();returnToDay();},{capture:true});
    $('sbbBrowseAllHighlights')?.addEventListener('click',()=>activateHistorical({all:true}));
    $('sbbBrowseRanked')?.addEventListener('click',activateRanked);
    $('sbbFocusExit')?.addEventListener('click',returnToAll);
    $('sbbSpecialExitBtn')?.addEventListener('click',returnToAll);
    $('sbbFocusPlayAll')?.addEventListener('click',playAll);
    $('teamThemeToggle')?.addEventListener('change',event=>saveTeamTheme(!!event.target.checked));
    $('sbbBrowseSearch')?.addEventListener('input',event=>{clearTimeout(state.searchTimer);const value=event.target.value;state.searchTimer=setTimeout(()=>searchSuggestions(value),180);});
    $('sbbBrowseSuggestions')?.addEventListener('click',event=>{
      const star=event.target.closest('[data-browse-star]');if(star){toggleFavorite(state.league,star.dataset.browseStar);return;}
      const entity=event.target.closest('[data-browse-entity]');if(entity)activateHistorical({entity:entity.dataset.browseEntity});
    });
    $('sbbBrowseFavorites')?.addEventListener('click',event=>{const entity=event.target.closest('[data-browse-entity]');if(entity)activateHistorical({entity:entity.dataset.browseEntity});});
    $('sbbCurationCards')?.addEventListener('click',event=>{
      const card=event.target.closest('[data-curation-index]');const index=Number(card?.dataset?.curationIndex);if(card&&state.games[index]?.items?.length)playFrom(index);
    });
    $('sbbCurationCards')?.addEventListener('keydown',event=>{if(event.key!=='Enter'&&event.key!==' ')return;const card=event.target.closest('[data-curation-index]');const index=Number(card?.dataset?.curationIndex);if(card&&state.games[index]?.items?.length){event.preventDefault();playFrom(index);}});
    $('sbbCurationCards')?.addEventListener('wheel',event=>{const host=event.currentTarget;if(!host||host.scrollWidth<=host.clientWidth+2)return;const delta=Math.abs(event.deltaY)>=Math.abs(event.deltaX)?event.deltaY:event.deltaX;if(!delta)return;event.preventDefault();host.scrollLeft+=delta;},{passive:false});
    document.addEventListener('click',event=>{
      if(state.open&&!event.target.closest('#sbbBrowsePopover')&&!event.target.closest('#sbbBrowseBtn'))setOpen(false);
      const special=event.target.closest('#sbbSpecialEventsMenu [data-special-competition]');
      if(special){const league=clean(special.dataset.specialCompetition).toUpperCase();if(league==='CFB'){event.preventDefault();hideLegacyCfb();return;}setTimeout(()=>enterSpecialContext(league,specialEventLabel(special,league)),0);return;}
      const filter=event.target.closest('#scoreFilters [data-score-filter]');if(filter){
        const requested=clean(filter.dataset.scoreFilter).toUpperCase();
        // Core league/ALL navigation is a hard boundary for any curated event
        // queue. Release it during capture, before the canonical score renderer
        // can call renderQueue(), so stale event programming cannot win a race.
        if(requested==='ALL'||isCoreLeague(requested))releaseCuratedQueue(`score filter changed to ${requested||'ALL'}`);
        setTimeout(()=>{if(requested!=='CFB'&&(!state.specialContext||requested!==state.specialContext.league))clearSpecialContext();const before=state.league;syncLeagueUi();if(state.league!==before&&state.mode!=='daily')returnToDay();},0);
      }
    },true);
    window.addEventListener('sbb:themechange',()=>renderCuration());
    window.addEventListener('resize',()=>{if(state.open)positionPopover();if(state.mode==='daily')captureScoreRibbonHeight();},{passive:true});
    window.visualViewport?.addEventListener('resize',()=>{if(state.open)positionPopover();},{passive:true});
    document.addEventListener('fullscreenchange',()=>{ensurePopoverHost();if(state.open)setTimeout(positionPopover,50);});
    document.addEventListener('webkitfullscreenchange',()=>{ensurePopoverHost();if(state.open)setTimeout(positionPopover,50);});
  }

  function init(){loadEntityCatalogStore();if(!ensureUi())return;installLegacyCfbGuard();captureScoreRibbonHeight();syncLeagueUi();bind();patchRenderQueue();patchPlaybackFailure();setTimeout(()=>primeEntityCatalog(),0);setTimeout(patchRenderQueue,350);setTimeout(patchPlaybackFailure,500);setTimeout(()=>{captureScoreRibbonHeight();hideLegacyCfb();},500);setTimeout(hideLegacyCfb,1800);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();

  window.SBB_CURATED_BROWSE=Object.freeze({
    version:VERSION,open:()=>setOpen(true),close:()=>setOpen(false),returnToDay,returnToAll,releaseCuratedQueue,
    browseAll:()=>activateHistorical({all:true}),browseEntity:entity=>activateHistorical({entity}),
    rankedToday:activateRanked,playAll,enterSpecialContext,
    context:()=>({league:state.league,specialContext:state.specialContext?{...state.specialContext}:null,mode:state.mode,entity:state.entity,games:state.games.slice(0,30).map(g=>({date:g.date,game:g.game,tier:g.tier,mediaAvailable:!!g.items?.length}))}),
    snapshot:()=>({version:VERSION,league:state.league,mode:state.mode,entity:state.entity,facet:state.facet,games:state.games.length,selected:state.selected.size,queueActive:state.queueActive,queueItems:state.queueItems.length,favorites:favoritesFor(state.league).slice(),loading:state.loading,error:state.error,noGameCenter:document.body.classList.contains('sbb-curated-no-game-center')})
  });
})();

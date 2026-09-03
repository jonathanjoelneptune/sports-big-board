/* Sports Big Board v5.3.3 — Browse UX + Curated Timeline
   User-facing content discovery over the existing score/calendar + historical
   catalog. No second playback owner: curated results become normal PROGRAM items
   and therefore inherit PlaybackController, Hot Standby, Up Next and score-card
   interrupt/resume behavior. */
(() => {
  'use strict';
  if(window.SBB_CURATED_BROWSE?.version==='5.3.3') return;

  const VERSION='5.3.3';
  const FAVORITES_KEY='sbb.curation.favorites.v1';
  const MAX_AUDIT_ROWS=1000;
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
    suggestionRows:[],lastQuery:'',entityCatalogCache:new Map(),
    scoreDateCache:new Map(),scoreDateInflight:new Map(),scoreObserver:null,controlLeague:'',
  };

  function loadFavorites(){
    try{const raw=JSON.parse(localStorage.getItem(FAVORITES_KEY)||'{}');return raw&&typeof raw==='object'?raw:{};}catch(_){return {};}
  }
  function saveFavorites(){try{localStorage.setItem(FAVORITES_KEY,JSON.stringify(state.favorites));}catch(_){}}
  function favoritesFor(league){return Array.isArray(state.favorites[league])?state.favorites[league]:[];}
  function isFavorite(league,name){return favoritesFor(league).some(x=>norm(x)===norm(name));}
  function toggleFavorite(league,name){
    if(!league||!name)return;
    const current=favoritesFor(league).slice();const key=norm(name);const i=current.findIndex(x=>norm(x)===key);
    if(i>=0)current.splice(i,1);else current.push(name);
    state.favorites[league]=current;saveFavorites();renderSuggestions(state.suggestionRows,$('sbbBrowseSearch')?.value||'');
  }

  function leagueLabel(league){
    const map={'USOPEN-2026':'US OPEN','WC2026':'WORLD CUP','LLWS2026':'LLWS','NCAAF':'NCAAF','CFB':'CFB'};
    return map[league]||league||'SPORTS';
  }
  function isTennis(league){return /USOPEN|TENNIS|ATP|WTA/i.test(league);}
  function isCollegeFootball(league){return /NCAAF|CFB/i.test(league);}
  function entityTypeFor(league){return isTennis(league)?'player':'team';}
  function selectedLeague(){
    try{const v=clean(scoreRibbonLeagueFilter).toUpperCase();if(v)return v;}catch(_){}
    const active=document.querySelector('#scoreFilters button.active[data-score-filter],#scoreFilters button[aria-pressed="true"][data-score-filter]');
    return clean(active?.dataset?.scoreFilter||'ALL').toUpperCase()||'ALL';
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
  function bestMediaForAuditRow(row){
    const tiers=row?.tiers||{};const order=['gold','green','extended','blue'];
    for(const tier of order){
      const pool=(tiers[tier]||[]).filter(mediaUsable);
      if(!pool.length)continue;
      const sorted=pool.slice().sort((a,b)=>(Number(b.verified)-Number(a.verified))||(Number(b.runtimeSuccessAt||0)-Number(a.runtimeSuccessAt||0))||(Number(b.verifiedAt||0)-Number(a.verifiedAt||0)));
      return {tier,items:tier==='blue'?sorted.slice(0,12):sorted.slice(0,1)};
    }
    return {tier:'none',items:[]};
  }
  function programItemFromAudit(row,media,tier,index=0){
    const url=clean(media?.url||media?.mediaUrl);const youtubeId=clean(media?.youtubeId)||youtubeIdFrom(url);const parts=splitGame(row?.game);const away=parts[0]||'',home=parts[1]||'';
    const id=clean(media?.assetKey||media?.id||youtubeId)||`curated:${row?.league||state.league}:${row?.eventId||row?.date||'game'}:${tier}:${index}`;
    const sourceTitle=clean(media?.title)||clean(row?.game)||'Sports Highlight';
    const queueTitle=entityMatchupLabel(away,home);
    return {
      id,youtubeId:youtubeId||undefined,mediaUrl:youtubeId?'':url,
      title:queueTitle,queueTitle,sourceTitle,mediaTitle:sourceTitle,subtitle:sourceTitle,
      thumbnail:clean(media?.thumbnail)||clean(media?.thumbnailUrl)||(youtubeId?`https://i.ytimg.com/vi/${youtubeId}/mqdefault.jpg`:''),
      durationSeconds:Number(media?.durationSeconds||media?.duration||0)||0,
      provider:clean(media?.provider||media?.source)||'HISTORICAL CATALOG',source:clean(media?.source||media?.provider)||'HISTORICAL CATALOG',
      league:clean(row?.league||state.league).toUpperCase(),competitionId:clean(row?.league||state.league).toUpperCase(),
      eventId:clean(row?.eventId),matchId:clean(row?.eventId),gamePk:clean(row?.gamePk||''),
      date:clean(row?.date),gameDate:clean(row?.date),scheduledGameDate:clean(row?.date),
      away:{name:away,displayName:away},home:{name:home,displayName:home},awayTeam:{name:away,displayName:away},homeTeam:{name:home,displayName:home},
      overview:tier!=='blue',programType:tier==='blue'?'reel':'recap',tier,historicalTier:tier,
      verifiedPlayable:true,verified:true,__sbbCuratedOverride:true,__sbbBrowseV533:true,
    };
  }
  function gameFromAuditRow(row){
    const media=bestMediaForAuditRow(row);if(!media.items.length)return null;
    const items=media.items.map((x,i)=>programItemFromAudit(row,x,media.tier,i)).filter(x=>x.youtubeId||x.mediaUrl);
    if(!items.length)return null;
    return {key:`${row.league||state.league}:${row.eventId||row.game}:${row.date||''}`,date:clean(row.date),league:clean(row.league||state.league).toUpperCase(),eventId:clean(row.eventId),game:clean(row.game),tier:media.tier,items,row,source:'audit'};
  }
  function gameFromResident(match){
    try{
      const candidates=scoreCardPlayableItems(match);const selection=scoreCardPlaybackSelection(match,candidates);
      const away=participantName(teamObject(match,'away')),home=participantName(teamObject(match,'home'));
      const queueTitle=entityMatchupLabel(away,home);
      const items=(selection?.selectionItems||[]).filter(Boolean).map(x=>({...x,queueTitle,__sbbCuratedOverride:true,__sbbBrowseV533:true}));
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
      subnav.innerHTML='<button id="sbbBrowseBtn" type="button" class="sbb-browse-btn" aria-haspopup="dialog" aria-expanded="false"><span>TEAM BROWSE</span><b aria-hidden="true">⌄</b></button>';
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
      ribbon.innerHTML=`<div class="sbb-curation-toolbar"><div class="sbb-curation-context"><span id="sbbCurationKicker">TEAM BROWSE</span><strong id="sbbCurationTitle">Highlights</strong><small id="sbbCurationMeta">Newest first</small></div><div class="sbb-curation-actions"><button id="sbbCurationPlay" type="button" disabled>PLAY ALL</button><button id="sbbCurationBack" type="button" title="Exit curated browse and restore the daily scoreboard">EXIT</button></div></div><div id="sbbCurationCards" class="sbb-curation-cards"></div>`;
      const score=document.querySelector('.score-ribbon');score?.insertAdjacentElement('afterend',ribbon);
    }
    return true;
  }

  function activeLeagueButton(){
    const filters=$('scoreFilters');if(!filters)return null;
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
    if(state.open){syncLeagueUi();renderSuggestions([], '');positionPopover();primeEntityCatalog();setTimeout(()=>$('sbbBrowseSearch')?.focus(),0);}
  }
  function syncLeagueUi(){
    state.league=selectedLeague();state.entityType=entityTypeFor(state.league);const eligible=state.league&&state.league!=='ALL';
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
  }

  async function primeEntityCatalog(){
    const league=state.league;if(!league||league==='ALL')return;
    if(state.entityCatalogCache.has(league)){renderSuggestions(state.entityCatalogCache.get(league)||[],$('sbbBrowseSearch')?.value||'');return;}
    try{const rows=await fetchAuditRows(league,'',Math.min(MAX_AUDIT_ROWS,500));state.entityCatalogCache.set(league,rows);if(state.open&&state.league===league)renderSuggestions(rows,$('sbbBrowseSearch')?.value||'');}catch(_){ }
  }

  function renderFavorites(){
    const host=$('sbbBrowseFavorites');if(!host)return;const fav=favoritesFor(state.league);host.classList.toggle('hidden',!fav.length);
    host.innerHTML=fav.length?`<span>★ FAVORITES</span>${fav.map(name=>`<button type="button" data-browse-entity="${esc(name)}">${esc(name)}</button>`).join('')}`:'';
  }
  function renderSuggestions(rows=[],query=''){
    const host=$('sbbBrowseSuggestions');if(!host)return;state.suggestionRows=rows;
    const local=currentEntities(state.league);const merged=[];const seen=new Set();
    for(const name of [...favoritesFor(state.league),...local,...entitiesFromRows(rows,query)]){const key=norm(name);if(!key||seen.has(key)||(query&&!key.includes(norm(query))))continue;seen.add(key);merged.push(name);}
    merged.sort((a,b)=>(Number(isFavorite(state.league,b))-Number(isFavorite(state.league,a)))||a.localeCompare(b));
    if(!merged.length){host.innerHTML=`<div class="sbb-browse-empty">${query?'No matching '+(state.entityType==='player'?'players':'teams')+' found.':'Search or choose one of today\'s '+(state.entityType==='player'?'players':'teams')+'.'}</div>`;return;}
    host.innerHTML=merged.slice(0,60).map(name=>`<div class="sbb-browse-suggestion"><button class="sbb-browse-entity" type="button" data-browse-entity="${esc(name)}"><span>${esc(name)}</span><small>ALL DATES</small></button><button class="sbb-browse-star ${isFavorite(state.league,name)?'active':''}" type="button" data-browse-star="${esc(name)}" aria-label="${isFavorite(state.league,name)?'Remove':'Add'} ${esc(name)} favorite">${isFavorite(state.league,name)?'★':'☆'}</button></div>`).join('');
  }
  async function searchSuggestions(value){
    const query=clean(value);state.lastQuery=query;if(query.length<2){renderSuggestions([],query);return;}
    const token=++state.requestToken;
    try{const data=await fetchAuditPage({league:state.league,q:query,offset:0,limit:100,token});if(query!==state.lastQuery)return;renderSuggestions(data.rows||[],query);}catch(err){if(err?.name!=='AbortError')renderSuggestions([],query);}
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
  function tierLabel(tier){return ({gold:'GOLD',green:'FULL RECAP',extended:'EXTENDED',blue:'HIGHLIGHTS'})[tier]||clean(tier).toUpperCase()||'RECAP';}
  function cardThumb(game){const item=game.items?.[0]||{};return clean(item.thumbnail)||(item.youtubeId?`https://i.ytimg.com/vi/${item.youtubeId}/mqdefault.jpg`:'');}
  function renderCuration(){
    const ribbon=$('sbbCurationRibbon'),cards=$('sbbCurationCards');if(!ribbon||!cards)return;
    const active=state.mode!=='daily';document.body.classList.toggle('sbb-curation-active',active);ribbon.hidden=!active;ribbon.classList.toggle('hidden',!active);syncLeagueUi();
    window.dispatchEvent(new CustomEvent('sbb:browse-layout',{detail:{active}}));
    if(!active)return;
    const label=leagueLabel(state.league);const title=state.entity?`${label} › ${state.entity}`:(state.facet?`${label} › ${state.facet}`:`${label} › ALL HIGHLIGHTS`);
    $('sbbCurationTitle').textContent=title;
    $('sbbCurationMeta').textContent=state.loading?'Loading verified highlights…':(state.error?state.error:`Newest first • ${state.entity?'all dates':state.facet?dateLabel(selectedDate()):'all dates'} • click any game to start there`);
    const play=$('sbbCurationPlay');if(play){play.disabled=state.loading||!state.games.length;play.textContent='PLAY ALL';}
    if(state.loading){cards.innerHTML='<div class="sbb-curation-loading"><span></span><strong>Building highlight library…</strong></div>';return;}
    if(state.error){cards.innerHTML=`<div class="sbb-curation-empty"><strong>Browse unavailable</strong><span>${esc(state.error)}</span></div>`;return;}
    if(!state.games.length){cards.innerHTML='<div class="sbb-curation-empty"><strong>No verified highlights found</strong><span>Try another team/player or return to the daily scoreboard.</span></div>';return;}
    cards.innerHTML=state.games.map((game,i)=>{
      const thumb=cardThumb(game),score=scoreDisplay(game),tier=tierClass(game.tier),matchup=describeGame(game);
      return `<div class="sbb-curation-card-shell"><span class="sbb-curation-date-pill">${esc(datePill(game.date))}</span><article class="sbb-curation-card" data-curation-index="${i}" tabindex="0" role="button" aria-label="Play ${esc(matchup)} and continue with older highlights"><div class="sbb-curation-thumb">${thumb?`<img src="${esc(thumb)}" alt="" loading="lazy">`:`<div class="sbb-curation-thumb-fallback">${esc(game.league)}</div>`}<span class="sbb-curation-play">▶</span></div><div class="sbb-curation-card-copy"><strong>${esc(matchup)}</strong><span class="sbb-curation-result ${score.text?'':'hidden'}" data-result="${esc(score.result)}">${esc(score.text?(score.result?`${score.result} ${score.text}`:score.text):'')}</span><span class="sbb-curation-media-tier tier-${tier}">${esc(tierLabel(game.tier))}</span></div></article></div>`;
    }).join('');
    observeVisibleScores();
  }

  async function activateHistorical({entity='',all=false}={}){
    setOpen(false);
    state.mode='history';state.entity=clean(entity);state.facet=all?'ALL HIGHLIGHTS':'';state.loading=true;state.error='';state.games=[];state.selected.clear();renderCuration();
    try{
      const rows=await fetchAuditRows(state.league,state.entity,MAX_AUDIT_ROWS);const filtered=state.entity?rows.filter(row=>gameHasEntity(row?.game,state.entity)):rows;
      state.games=filtered.map(gameFromAuditRow).filter(Boolean).sort((a,b)=>String(b.date).localeCompare(String(a.date))||String(b.eventId).localeCompare(String(a.eventId)));
    }catch(err){if(err?.name==='AbortError')return;state.error=`Could not load ${leagueLabel(state.league)} highlights: ${err?.message||err}`;}
    finally{state.loading=false;renderCuration();}
  }
  function rankedResidentGames(){
    const tennis=isTennis(state.league);return currentMatches(state.league).filter(match=>{
      const a=participantRank(teamObject(match,'away')),h=participantRank(teamObject(match,'home'));
      return tennis?(a>0||h>0):((a>0&&a<=25)||(h>0&&h<=25));
    }).map(gameFromResident).filter(Boolean).sort((a,b)=>String(b.date).localeCompare(String(a.date)));
  }
  function activateRanked(){state.mode='facet';state.entity='';state.facet=isTennis(state.league)?'SEEDED TODAY':'RANKED TODAY';state.error='';state.loading=false;state.selected.clear();state.games=rankedResidentGames();setOpen(false);renderCuration();}
  function returnToDay(){state.mode='daily';state.entity='';state.facet='';state.games=[];state.selected.clear();state.error='';document.body.classList.remove('sbb-curation-active');const ribbon=$('sbbCurationRibbon');if(ribbon){ribbon.hidden=true;ribbon.classList.add('hidden');}syncLeagueUi();window.dispatchEvent(new CustomEvent('sbb:browse-layout',{detail:{active:false}}));}

  function queueItemsForGames(games){const out=[];const seen=new Set();for(const game of games||[])for(const item of game.items||[]){const key=clean(item.id||item.youtubeId||item.mediaUrl);if(!key||seen.has(key))continue;seen.add(key);out.push(item);}return out;}
  function programKey(item){return clean(item?.id||item?.youtubeId||item?.mediaUrl);}
  function queueMatchesActive(){
    try{if(!Array.isArray(PROGRAM)||PROGRAM.length!==state.queueItems.length)return false;return PROGRAM.every((x,i)=>programKey(x)===programKey(state.queueItems[i]));}catch(_){return false;}
  }
  function gameCenterSupportedForItem(item){
    if(!item)return false;
    try{if(typeof gameCenterCompetitionSupported==='function')return !!gameCenterCompetitionSupported(item);}catch(_){}
    const league=clean(item?.competitionId||item?.league||state.league).toUpperCase();
    return !isTennis(league) && !/LLWS|WC2026/.test(league);
  }
  function syncCuratedGameCenterContext(item){
    const curated=!!item?.__sbbCuratedOverride;
    const unsupported=curated&&!gameCenterSupportedForItem(item);
    const body=document.body;
    const was=body?.classList.contains('sbb-curated-no-game-center');
    body?.classList.toggle('sbb-curated-no-game-center',unsupported);
    if(unsupported&&!was){
      try{window.SBB_SELECTED_EVENT?.clear?.({reason:'curated competition has no Game Center',source:'browse'});}catch(_){}
      try{window.SBB_GAME_CENTER_SCROLL?.repair?.();}catch(_){}
    }
    if(!unsupported&&was){try{window.SBB_GAME_CENTER_SCROLL?.repair?.();}catch(_){} }
    return !unsupported;
  }
  function rememberProgram(){
    if(state.queueActive)return;
    try{state.preProgram=Array.isArray(PROGRAM)?[...PROGRAM]:null;}catch(_){state.preProgram=null;}
    try{state.preGeneral=Array.isArray(GENERAL_PROGRAM)?[...GENERAL_PROGRAM]:null;}catch(_){state.preGeneral=null;}
  }
  function activateQueue(items,label,startIndex=0){
    if(!items.length)return false;rememberProgram();state.queueActive=true;state.queueItems=[...items];state.queueLabel=label;
    try{window.SBB_SCORE_INTERRUPT_QUEUE?.clear?.('curated programming queue start');}catch(_){}
    try{if(typeof userPlaybackSession!=='undefined')userPlaybackSession=null;}catch(_){}
    try{PROGRAM=[...state.queueItems];}catch(err){console.warn('[SBB Browse] PROGRAM assignment failed',err);return false;}
    try{GENERAL_PROGRAM=[...state.queueItems];}catch(_){}
    const bounded=Math.max(0,Math.min(Number(startIndex)||0,state.queueItems.length-1));
    syncCuratedGameCenterContext(state.queueItems[bounded]);
    try{if(typeof renderQueue==='function')renderQueue();}catch(_){}
    try{if(typeof setFeedNote==='function')setFeedNote(`Curated programming • ${label} • ${state.queueItems.length} video${state.queueItems.length===1?'':'s'}`);}catch(_){}
    if(typeof tuneProgramIndexV5==='function'){tuneProgramIndexV5(bounded,{userInitiated:true,reason:`v5.3.3 curated programming: ${label}`});return true;}
    return false;
  }
  function playGames(games,label){return activateQueue(queueItemsForGames(games),label,0);}
  function playFrom(index){const games=state.games.slice(index);if(!games.length)return false;return playGames(games,state.entity||state.facet||`${leagueLabel(state.league)} highlights`);}
  function playAll(){return playGames(state.games,state.entity||state.facet||`${leagueLabel(state.league)} highlights`);}
  function patchRenderQueue(){
    try{
      if(typeof renderQueue!=='function'||renderQueue.__sbbBrowseV533)return false;const original=renderQueue;
      const wrapped=function(...args){
        // Background score/news refreshes may rebuild GENERAL_PROGRAM. While a
        // user explicitly owns a curated queue, restore that queue before the
        // presentation layer renders it. Score interrupts remain authoritative.
        try{
          const interrupted=window.SBB_SCORE_INTERRUPT_QUEUE?.active?.();
          if(state.queueActive&&!interrupted&&!queueMatchesActive()){
            let current='';try{current=programKey(clip(currentIndex));}catch(_){}
            PROGRAM=[...state.queueItems];try{GENERAL_PROGRAM=[...state.queueItems];}catch(_){}
            if(current){const idx=PROGRAM.findIndex(x=>programKey(x)===current);if(idx>=0)currentIndex=idx;}
          }
        }catch(_){}
        let result;
        try{result=original.apply(this,args);}finally{
          try{syncCuratedGameCenterContext(typeof clip==='function'?clip(currentIndex):null);}catch(_){}
        }
        return result;
      };
      wrapped.__sbbBrowseV533=true;wrapped.__sbbOriginal=original;renderQueue=wrapped;try{window.renderQueue=wrapped;}catch(_){}state.renderQueuePatched=true;return true;
    }catch(_){return false;}
  }

  function bind(){
    $('sbbBrowseBtn')?.addEventListener('click',()=>setOpen(!state.open));
    $('sbbBrowseClose')?.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();setOpen(false);});
    $('sbbBrowsePopover')?.addEventListener('click',event=>{if(event.target.closest('#sbbBrowseClose')){event.preventDefault();event.stopPropagation();setOpen(false);}});
    $('sbbBrowseToday')?.addEventListener('click',()=>{setOpen(false);returnToDay();});
    $('sbbBrowseAllHighlights')?.addEventListener('click',()=>activateHistorical({all:true}));
    $('sbbBrowseRanked')?.addEventListener('click',activateRanked);
    $('sbbCurationBack')?.addEventListener('click',returnToDay);
    $('sbbCurationPlay')?.addEventListener('click',playAll);
    $('sbbBrowseSearch')?.addEventListener('input',event=>{clearTimeout(state.searchTimer);const value=event.target.value;state.searchTimer=setTimeout(()=>searchSuggestions(value),180);});
    $('sbbBrowseSuggestions')?.addEventListener('click',event=>{
      const star=event.target.closest('[data-browse-star]');if(star){toggleFavorite(state.league,star.dataset.browseStar);return;}
      const entity=event.target.closest('[data-browse-entity]');if(entity)activateHistorical({entity:entity.dataset.browseEntity});
    });
    $('sbbBrowseFavorites')?.addEventListener('click',event=>{const entity=event.target.closest('[data-browse-entity]');if(entity)activateHistorical({entity:entity.dataset.browseEntity});});
    $('sbbCurationCards')?.addEventListener('click',event=>{
      const card=event.target.closest('[data-curation-index]');if(card)playFrom(Number(card.dataset.curationIndex));
    });
    $('sbbCurationCards')?.addEventListener('keydown',event=>{if(event.key!=='Enter'&&event.key!==' ')return;const card=event.target.closest('[data-curation-index]');if(card){event.preventDefault();playFrom(Number(card.dataset.curationIndex));}});
    document.addEventListener('click',event=>{
      if(state.open&&!event.target.closest('#sbbBrowsePopover')&&!event.target.closest('#sbbBrowseBtn'))setOpen(false);
      const filter=event.target.closest('#scoreFilters [data-score-filter],#sbbSpecialEventsMenu [data-special-competition]');if(filter)setTimeout(()=>{const before=state.league;syncLeagueUi();if(state.league!==before&&state.mode!=='daily')returnToDay();},0);
    },true);
    window.addEventListener('sbb:themechange',()=>renderCuration());
    window.addEventListener('resize',()=>{if(state.open)positionPopover();},{passive:true});
    window.visualViewport?.addEventListener('resize',()=>{if(state.open)positionPopover();},{passive:true});
    document.addEventListener('fullscreenchange',()=>{ensurePopoverHost();if(state.open)setTimeout(positionPopover,50);});
    document.addEventListener('webkitfullscreenchange',()=>{ensurePopoverHost();if(state.open)setTimeout(positionPopover,50);});
  }

  function init(){if(!ensureUi())return;syncLeagueUi();bind();patchRenderQueue();setTimeout(patchRenderQueue,350);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();

  window.SBB_CURATED_BROWSE=Object.freeze({
    version:VERSION,open:()=>setOpen(true),close:()=>setOpen(false),returnToDay,
    browseAll:()=>activateHistorical({all:true}),browseEntity:entity=>activateHistorical({entity}),
    rankedToday:activateRanked,playAll,
    snapshot:()=>({version:VERSION,league:state.league,mode:state.mode,entity:state.entity,facet:state.facet,games:state.games.length,selected:state.selected.size,queueActive:state.queueActive,queueItems:state.queueItems.length,favorites:favoritesFor(state.league).slice(),loading:state.loading,error:state.error,noGameCenter:document.body.classList.contains('sbb-curated-no-game-center')})
  });
})();

/* Sports Big Board v5.3.10 — League View + recap context.
   Keeps multi-game/daily recap playback from inheriting a stale single-game
   Game Center and turns the former Up Next drawer into a persistent league view. */
(() => {
  'use strict';
  if (window.SBB_LEAGUE_VIEW?.version === '5.3.10') return;

  const VERSION = '5.3.10';
  const $ = id => document.getElementById(id);
  const clean = value => String(value ?? '').trim();
  const esc = value => clean(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const upper = value => clean(value).toUpperCase();
  const core = new Set(['MLB','NFL','NBA','NHL','NCAAF','EPL','MLS']);
  const state = {league:'',loading:false,payload:null,error:'',request:0,aggregate:false,lastAggregateKey:'',observer:null};

  function apiUrl(path){ try{return window.SBB_API?.url?.(path) || path;}catch(_){return path;} }
  function normalizeLeague(value){
    const raw=upper(value); if(raw==='CFB')return 'NCAAF';
    if(raw==='WORLD CUP'||raw==='WORLD-CUP'||raw==='FIFA WORLD CUP')return 'WC2026';
    return raw;
  }
  function curatedContext(){try{return window.SBB_CURATED_BROWSE?.context?.()||null;}catch(_){return null;}}
  function activeProgram(){
    try{ if(typeof PROGRAM!=='undefined'&&Array.isArray(PROGRAM)){const i=Number(typeof currentIndex!=='undefined'?currentIndex:0);return PROGRAM[i]||null;} }catch(_){}
    return null;
  }
  function currentLeague(){
    const aggregate=isAggregate();
    // League View follows what is actually on screen, not the browse menu that
    // happened to build the surrounding queue. A score-ribbon interrupt owns a
    // SelectedEvent; a daily/league recap intentionally does not.
    if(!aggregate){
      try{
        const selected=window.SBB_SELECTED_EVENT?.get?.();
        const fromSelected=normalizeLeague(selected?.competitionId||selected?.league||selected?.sportLeague||selected?.competition);
        if(fromSelected)return fromSelected;
      }catch(_){}
    }
    const item=activeProgram();
    const fromItem=normalizeLeague(item?.competitionId||item?.league||item?.sportLeague||item?.competition);
    if(fromItem)return fromItem;
    const context=curatedContext(); if(context?.specialContext?.league)return normalizeLeague(context.specialContext.league);
    if(context?.league && context.league!=='ALL')return normalizeLeague(context.league);
    try{const raw=normalizeLeague(scoreRibbonLeagueFilter);if(raw&&raw!=='ALL')return raw;}catch(_){}
    const active=document.querySelector('#scoreFilters [data-score-filter].active,#scoreFilters [data-score-filter][aria-pressed="true"]');
    return normalizeLeague(active?.dataset?.scoreFilter)||'MLB';
  }
  function leagueLabel(league,payload){
    if(clean(payload?.label))return clean(payload.label);
    return ({MLB:'MLB',NFL:'NFL',NBA:'NBA',NHL:'NHL',NCAAF:'NCAAF',EPL:'PREMIER LEAGUE',MLS:'MLS',WC2026:'2026 WORLD CUP','WORLD-CUP-2026':'2026 WORLD CUP','FIFA-WORLD-CUP-2026':'2026 WORLD CUP',LLWS2026:'LITTLE LEAGUE WORLD SERIES','USOPEN-2026':'US OPEN'})[league]||league.replaceAll('-',' ');
  }

  function itemText(item){
    return [item?.title,item?.name,item?.label,item?.headline,item?.scope,item?.packageType,item?.mediaScope,item?.editorialType,item?.collectionType].map(clean).filter(Boolean).join(' ');
  }
  function aggregateReason(item,title){
    const text=`${itemText(item)} ${clean(title)}`.toLowerCase();
    const direct=[
      /\bdaily\s+(recap|roundup|highlights?)\b/,/\b(all|every)\s+(games?|matches?)\b/,/\ball[- ]games?\s+(recap|highlights?)\b/,
      /\bleague\s+(recap|roundup)\b/,/\bnightly\s+(recap|roundup)\b/,/\bmatchweek\s+\d+\s+(recap|highlights?)\b/,
      /\bweek(?:ly)?\s+(recap|roundup)\b/,/\bhighlights?\s+from\s+(all|every)\s+(games?|matches?)\b/,/\btop\s+plays?\s+of\s+the\s+(day|night|week)\b/,
      /\bscoreboard\s+recap\b/,/\baround\s+the\s+league\b/
    ];
    if(direct.some(rx=>rx.test(text)))return 'MULTI_GAME_TITLE';
    // A generic league/date recap title is also aggregate unless it explicitly
    // identifies a single matchup/full-game package.
    if(/\brecap\b/.test(text)&&!/\b(full game|vs\.?| at | @ )\b/.test(text)&&/\b(mlb|nfl|nba|nhl|ncaaf|college football|premier league|mls|world cup|us open|little league)\b/.test(text))return 'LEAGUE_RECAP_TITLE';
    const scope=clean(item?.scope||item?.mediaScope||item?.packageType||item?.editorialType).toLowerCase();
    if(/daily|roundup|collection|multi[-_ ]?game|league[-_ ]?recap/.test(scope))return 'MULTI_GAME_SCOPE';
    return '';
  }
  function currentTitle(){return clean($('currentTitle')?.textContent||$('nowWatchingTitle')?.textContent||'');}
  function isAggregate(){return !!aggregateReason(activeProgram(),currentTitle());}

  function recapGameCenter(enable){
    const empty=$('gameCenterEmpty'),content=$('gameCenterContent');
    if(!empty)return;
    if(enable){
      document.body.classList.add('sbb-daily-recap-context');
      if(empty.dataset.sbbLeagueViewRecap!=='1'){
        try{if(!window.SBB_SCORE_INTERRUPT_QUEUE?.active?.())window.SBB_SELECTED_EVENT?.clear?.({source:'league-view',reason:'multi-game recap has no single-game Game Center identity',force:true});}catch(_){}
      }
      empty.dataset.sbbLeagueViewRecap='1';
      empty.querySelector('strong')?.replaceChildren(document.createTextNode('DAILY / MULTI-GAME RECAP'));
      const span=empty.querySelector('span');if(span)span.textContent='This video covers multiple games. Single-game Game Center is intentionally cleared. Use League View for standings, playoff context, rankings and event information.';
      empty.classList.remove('hidden'); content?.classList.add('hidden');
      const drawer=$('infoDrawer');
      if(drawer && !drawer.classList.contains('is-closed')) setTimeout(()=>$('upNextTabBtn')?.click(),0);
    }else{
      document.body.classList.remove('sbb-daily-recap-context');
      if(empty.dataset.sbbLeagueViewRecap==='1'){
        delete empty.dataset.sbbLeagueViewRecap;
        empty.querySelector('strong')?.replaceChildren(document.createTextNode('GAME CENTER'));
        const span=empty.querySelector('span');if(span)span.textContent='Select a game from the score ribbon to see its scoreboard, stats, players and plays.';
      }
    }
  }

  function rowRecord(row){
    if(clean(row.record))return clean(row.record);
    if(row.wins!==''||row.losses!=='')return [row.wins,row.losses,row.ties].filter(x=>clean(x)!=='').join('-');
    return clean(row.points)||'—';
  }
  function rowMarkup(row){
    return `<tr><td><span class="league-view-team">${row.logo?`<img src="${esc(row.logo)}" alt="" loading="lazy">`:''}<b>${esc(row.abbreviation||row.name)}</b><small>${esc(row.name)}</small></span></td><td>${esc(rowRecord(row))}</td><td>${esc(row.gamesBehind||row.points||row.pct||'—')}</td><td>${esc(row.streak||'—')}</td></tr>`;
  }
  function tableForGroup(group,{compact=false,title=''}={}){
    const rows=(group?.entries||[]).slice(0,20); if(!rows.length)return '';
    return `<section class="league-view-card league-view-standings-card${compact?' compact':''}"><div class="league-view-card-head"><strong>${esc(title||group.name||'STANDINGS')}</strong><span>${rows.length} TEAMS</span></div><div class="league-view-table-wrap"><table class="league-view-table"><thead><tr><th>TEAM</th><th>REC</th><th>GB / PTS</th><th>STRK</th></tr></thead><tbody>${rows.map(rowMarkup).join('')}</tbody></table></div></section>`;
  }
  function wildcardCard(rows,title='WILD CARD'){
    if(!rows?.length)return '';
    return `<section class="league-view-card league-view-wildcard"><div class="league-view-card-head"><strong>${esc(title)}</strong><span>NON-DIVISION LEADERS</span></div><div class="league-view-table-wrap"><table class="league-view-table"><thead><tr><th>TEAM</th><th>REC</th><th>GB / PTS</th><th>STRK</th></tr></thead><tbody>${rows.slice(0,8).map(rowMarkup).join('')}</tbody></table></div></section>`;
  }
  function conferenceBoard(rows,league){
    if(!Array.isArray(rows)||rows.length<2)return '';
    const wanted=league==='MLB'?['AL','NL']:(league==='NFL'?['AFC','NFC']:['EAST','WEST']);
    const ordered=wanted.map(key=>rows.find(x=>upper(x?.key)===key)).filter(Boolean);
    if(ordered.length<2)return '';
    return `<div class="league-view-conference-grid">${ordered.map(conf=>{
      let inner='';
      if(Array.isArray(conf.divisions)&&conf.divisions.length){for(const division of conf.divisions)inner+=tableForGroup(division,{compact:true,title:division.name});}
      else if(Array.isArray(conf.standings)&&conf.standings.length)inner+=tableForGroup({name:conf.name,entries:conf.standings},{compact:true,title:'CONFERENCE STANDINGS'});
      if(league==='MLB')inner+=wildcardCard(conf.wildcard||[],'WILD CARD');
      return `<section class="league-view-conference"><div class="league-view-conference-head"><strong>${esc(conf.name||conf.key)}</strong><span>${league==='MLB'?'DIVISIONS + WILD CARD':'CONFERENCE'}</span></div>${inner}</section>`;
    }).join('')}</div>`;
  }
  function playoffCard(rows,league){
    if(!rows?.length||league==='MLB')return '';
    const title='PLAYOFF SEED RACE';
    return `<section class="league-view-card league-view-race"><div class="league-view-card-head"><strong>${title}</strong><span>CURRENT</span></div><div class="league-view-race-grid">${rows.slice(0,16).map(row=>`<div><b>${esc(row.seed||'•')}</b>${row.logo?`<img src="${esc(row.logo)}" alt="" loading="lazy">`:''}<span>${esc(row.abbreviation||row.name)}</span><small>${esc(rowRecord(row))}</small></div>`).join('')}</div></section>`;
  }
  function rankingsCard(rows){
    if(!rows?.length)return '';
    return `<section class="league-view-card"><div class="league-view-card-head"><strong>AP TOP 25</strong><span>NCAAF</span></div><div class="league-view-ranking-list">${rows.slice(0,25).map(row=>`<div><b>${esc(row.rank)}</b>${row.logo?`<img src="${esc(row.logo)}" alt="" loading="lazy">`:''}<span>${esc(row.name)}</span><small>${esc(row.record||'')}</small></div>`).join('')}</div></section>`;
  }
  function pulseList(title,rows,value){
    if(!rows?.length)return '';
    return `<div class="league-view-pulse-group"><strong>${esc(title)}</strong>${rows.slice(0,4).map(row=>`<div>${row.logo?`<img src="${esc(row.logo)}" alt="" loading="lazy">`:''}<span>${esc(row.abbreviation||row.name)}</span><b>${esc(value(row))}</b></div>`).join('')}</div>`;
  }
  function pulseCard(leaders){
    if(!leaders||(!leaders.bestRecord?.length&&!leaders.hotStreaks?.length&&!leaders.bestDifferential?.length))return '';
    const parts=[
      pulseList('BEST RECORD',leaders.bestRecord,row=>rowRecord(row)),
      pulseList('HOT STREAK',leaders.hotStreaks,row=>clean(row.streak)||'—'),
      pulseList('DIFFERENTIAL',leaders.bestDifferential,row=>clean(row.differential)||'—')
    ].filter(Boolean).join('');
    return parts?`<section class="league-view-card league-view-pulse"><div class="league-view-card-head"><strong>LEAGUE PULSE</strong><span>AT A GLANCE</span></div><div class="league-view-pulse-grid">${parts}</div></section>`:'';
  }
  function gameText(game){
    const a=game?.away||{},h=game?.home||{};const names=(a.abbreviation||a.name)&& (h.abbreviation||h.name)?`${a.abbreviation||a.name} ${a.score||''} · ${h.abbreviation||h.name} ${h.score||''}`:clean(game?.name);
    return names||'Game';
  }
  function gamesCard(rows,special){
    if(!rows?.length)return '';
    return `<section class="league-view-card"><div class="league-view-card-head"><strong>${special?'EVENT MATCHES':'TODAY / RECENT'}</strong><span>${rows.length}</span></div><div class="league-view-games">${rows.slice(0,14).map(game=>`<div><strong>${esc(gameText(game))}</strong><span>${esc(game.series||game.status||game.round||'')}</span><small>${esc(clean(game.date).slice(0,10))}</small></div>`).join('')}</div></section>`;
  }
  function roundsCard(rows,special){
    const buckets=new Map();for(const game of rows||[]){const label=clean(game.series||game.round);if(!label)continue;if(!buckets.has(label))buckets.set(label,[]);buckets.get(label).push(game);}
    if(!buckets.size)return '';
    const groups=[...buckets.entries()].slice(0,8);
    return `<section class="league-view-card"><div class="league-view-card-head"><strong>${special?'BRACKET / ROUNDS':'SERIES CONTEXT'}</strong><span>${groups.length}</span></div><div class="league-view-rounds">${groups.map(([label,games])=>`<div><b>${esc(label)}</b><span>${games.slice(0,4).map(game=>esc(gameText(game))).join(' · ')}</span></div>`).join('')}</div></section>`;
  }
  function localEventCard(context){
    const games=context?.games||[];if(!games.length)return '';
    return `<section class="league-view-card league-view-event-local"><div class="league-view-card-head"><strong>BIG BOARD EVENT VIEW</strong><span>LOCAL</span></div><div class="league-view-games">${games.slice(0,18).map(game=>`<div><strong>${esc(game.game||game.title||'Match')}</strong><span>${esc(game.result||game.status||'')}</span><small>${esc(clean(game.date).slice(0,10))}</small></div>`).join('')}</div></section>`;
  }

  function render(){
    const root=$('leagueViewRoot');if(!root)return;
    const league=state.league||currentLeague();const payload=state.payload||{};const label=leagueLabel(league,payload);const special=payload.specialEvent===true||!core.has(league);
    const context=curatedContext();
    const updated=payload.savedAt?new Date(Number(payload.savedAt)*1000).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'}):'';
    let body='';
    if(state.loading)body='<div class="league-view-loading"><span></span>Loading standings and league context…</div>';
    else if(state.error&&!payload.standings?.length&&!context?.games?.length)body=`<div class="league-view-empty"><strong>LEAGUE VIEW TEMPORARILY UNAVAILABLE</strong><span>${esc(state.error)}</span></div>`;
    else{
      if(payload.rankings?.length)body+=rankingsCard(payload.rankings);
      const conferenceLayout=conferenceBoard(payload.conferences||[],league);
      if(conferenceLayout)body+=conferenceLayout;
      else for(const group of payload.standings||[])body+=tableForGroup(group);
      body+=playoffCard(payload.playoffRace||[],league);
      body+=pulseCard(payload.leaders||{});
      body+=roundsCard(payload.games||[],special);
      body+=gamesCard(payload.games||[],special);
      if(special)body+=localEventCard(context);
      if(!body)body='<div class="league-view-empty"><strong>LEAGUE CONTEXT</strong><span>No public standings table is available for this event yet. Big Board event highlights remain available in the ribbon and Team Browse.</span></div>';
    }
    root.innerHTML=`<div class="league-view-head"><div><small>${special?'SPECIAL EVENT':'LEAGUE VIEW'}</small><h2>${esc(label)}</h2><span class="league-view-muted">Standings · playoff race · leaders · recent results</span></div><div class="league-view-head-actions">${updated?`<span class="league-view-updated">UPDATED ${esc(updated)}</span>`:''}<button id="leagueViewRefresh" type="button" title="Refresh League View">↻</button></div></div><div class="league-view-content">${body}</div>`;
    $('leagueViewRefresh')?.addEventListener('click',()=>refresh(true));
  }

  async function refresh(force=false){
    const league=currentLeague();const token=++state.request;state.league=league;state.loading=true;state.error='';render();
    try{
      const response=await fetch(apiUrl(`/api/league-view?league=${encodeURIComponent(league)}${force?'&force=1':''}`),{cache:force?'no-store':'default'});
      const payload=await response.json().catch(()=>({}));if(token!==state.request)return;
      if(!response.ok||payload?.ok===false)throw new Error(payload?.error||`HTTP ${response.status}`);
      state.payload=payload;
    }catch(err){if(token!==state.request)return;state.error=clean(err?.message||err);state.payload={league,standings:[],playoffRace:[],rankings:[],games:[],specialEvent:!core.has(league)};}
    finally{if(token===state.request){state.loading=false;render();}}
  }

  function syncContext({forceRefresh=false}={}){
    const league=currentLeague();const aggregate=isAggregate();state.aggregate=aggregate;recapGameCenter(aggregate);
    const key=`${league}|${aggregate?'recap':'game'}|${currentTitle()}`;
    if(forceRefresh||league!==state.league||!state.payload){refresh(false);}else if(key!==state.lastAggregateKey)render();
    state.lastAggregateKey=key;
  }
  function bind(){
    $('upNextTabBtn')?.addEventListener('click',()=>{const league=currentLeague();if(league!==state.league||!state.payload)refresh(false);else render();});
    $('upNextDrawerBtn')?.addEventListener('click',()=>setTimeout(()=>{const league=currentLeague();if(league!==state.league||!state.payload)refresh(false);else render();},0));
    $('scoreFilters')?.addEventListener('click',event=>{if(event.target.closest('[data-score-filter]'))setTimeout(()=>syncContext({forceRefresh:true}),50);});
    window.addEventListener('sbb:special-context',()=>setTimeout(()=>syncContext({forceRefresh:true}),30));
    window.addEventListener('sbb:curated-event-identity',()=>setTimeout(()=>syncContext(),30));
    window.addEventListener('sbb:score-click-selection',()=>setTimeout(()=>syncContext({forceRefresh:true}),30));
    window.addEventListener('sbb:league-view-refresh',()=>refresh(true));
    try{window.SBB_SELECTED_EVENT?.subscribe?.(()=>setTimeout(()=>syncContext({forceRefresh:true}),0));}catch(_){}
    const title=$('currentTitle');if(title){state.observer=new MutationObserver(()=>setTimeout(()=>syncContext(),0));state.observer.observe(title,{childList:true,subtree:true,characterData:true});}
    setTimeout(()=>syncContext({forceRefresh:true}),0);
    setTimeout(()=>syncContext(),1200);
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
  window.SBB_LEAGUE_VIEW=Object.freeze({version:VERSION,refresh,isAggregate,snapshot:()=>({league:state.league,aggregate:state.aggregate,loading:state.loading,error:state.error,payload:state.payload})});
})();

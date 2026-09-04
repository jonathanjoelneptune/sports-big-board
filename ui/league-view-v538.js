/* Sports Big Board v5.4.5 — League View + recap context.
   Keeps multi-game/daily recap playback from inheriting a stale single-game
   Game Center and turns the former Up Next drawer into a persistent league view. */
(() => {
  'use strict';
  if (window.SBB_LEAGUE_VIEW?.version === '5.4.5') return;

  const VERSION = '5.4.5';
  const $ = id => document.getElementById(id);
  const clean = value => String(value ?? '').trim();
  const esc = value => clean(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const upper = value => clean(value).toUpperCase();
  const core = new Set(['MLB','NFL','NBA','NHL','NCAAF','EPL','MLS']);
  const state = {league:'',loading:false,refreshing:false,payload:null,error:'',request:0,aggregate:false,lastAggregateKey:'',observer:null,navLeague:'',lastFetchedAt:0,syncTimer:null};

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
  function leagueFromItem(item){
    if(!item)return '';
    const candidates=[
      item.competitionId,item.league,item.sportLeague,item.competition,item.__sbbLeague,item.scoreLeague,item.sourceLeague,
      item.event?.competitionId,item.event?.league,item.match?.competitionId,item.match?.league,item.game?.competitionId,item.game?.league
    ];
    for(const value of candidates){const league=normalizeLeague(value);if(league&&league!=='ALL')return league;}
    return '';
  }
  function leagueFromTitle(title=currentTitle()){
    const text=upper(title);
    if(/\bMLB\b|MAJOR LEAGUE BASEBALL/.test(text))return 'MLB';
    if(/\bNFL\b/.test(text))return 'NFL';
    if(/\bNBA\b/.test(text))return 'NBA';
    if(/\bNHL\b/.test(text))return 'NHL';
    if(/\bNCAAF\b|COLLEGE FOOTBALL|NCAA FOOTBALL/.test(text))return 'NCAAF';
    if(/PREMIER LEAGUE|\bEPL\b/.test(text))return 'EPL';
    if(/\bMLS\b|MAJOR LEAGUE SOCCER/.test(text))return 'MLS';
    if(/WORLD CUP|FIFA WC/.test(text))return 'WC2026';
    if(/US OPEN/.test(text))return 'USOPEN-2026';
    if(/LITTLE LEAGUE|\bLLWS\b/.test(text))return 'LLWS2026';
    return '';
  }
  function currentLeague(){
    // Explicit league navigation is authoritative until the viewer selects a clip.
    // This lets MLB/NHL/EPL immediately update League View before playback changes.
    if(state.navLeague){const nav=normalizeLeague(state.navLeague);if(nav&&nav!=='ALL')return nav;}
    // v5.4.5 authority order: what is PLAYING beats what was BROWSED. Curated
    // special-event context is only a fallback while Browse is still non-daily.
    // This prevents a retired World Cup context from pinning League View after an
    // MLB score-card takes over playback.
    const item=activeProgram();
    const fromItem=leagueFromItem(item);if(fromItem)return fromItem;
    const fromTitle=leagueFromTitle();if(fromTitle)return fromTitle;
    const aggregate=isAggregate();
    if(!aggregate){
      try{
        const selected=window.SBB_SELECTED_EVENT?.get?.();
        const fromSelected=normalizeLeague(selected?.competitionId||selected?.league||selected?.sportLeague||selected?.competition);
        if(fromSelected&&fromSelected!=='ALL')return fromSelected;
      }catch(_){}
    }
    const context=curatedContext();
    if(context?.mode&&context.mode!=='daily'){
      if(context?.specialContext?.league)return normalizeLeague(context.specialContext.league);
      if(context?.league&&context.league!=='ALL')return normalizeLeague(context.league);
    }
    try{const raw=normalizeLeague(scoreRibbonLeagueFilter);if(raw&&raw!=='ALL')return raw;}catch(_){}
    const active=document.querySelector('#scoreFilters [data-score-filter].active,#scoreFilters [data-score-filter][aria-pressed="true"]');
    return normalizeLeague(active?.dataset?.scoreFilter)||state.league||'MLB';
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
  function soccerRecord(row){
    const parts=[row.wins,row.ties,row.losses].map(clean);
    return parts.some(Boolean)?parts.map(x=>x||'0').join('-'):rowRecord(row);
  }
  function rowSecondary(row,league){
    if(['EPL','MLS'].includes(league))return clean(row.gamesPlayed||row.played||'—');
    if(league==='NHL')return clean(row.points||row.pct||row.gamesBehind||'—');
    return clean(row.gamesBehind||row.pct||row.points||'—');
  }
  function tableHeaders(league){
    const wildcard=!!arguments[1]?.wildcard;
    if(['EPL','MLS'].includes(league))return ['CLUB','MP','W-D-L','PTS','FORM'];
    if(league==='NHL')return ['TEAM','REC','PTS','STRK'];
    if(league==='NCAAF')return ['TEAM','REC','CONF','STRK'];
    if(wildcard&&(league==='MLB'||league==='NFL'))return ['TEAM','REC','WC GB','STRK'];
    return ['TEAM','REC','GB / PCT','STRK'];
  }
  function formMarkup(form=[]){
    const values=Array.isArray(form)?form.slice(-5):[];while(values.length<5)values.unshift('');
    return `<span class="league-view-form" aria-label="Last five">${values.map(value=>{const v=upper(value);const cls=v==='W'?'win':(v==='L'?'loss':(v==='D'||v==='T'?'draw':'empty'));const label=v==='W'?'W':(v==='L'?'L':(v==='D'||v==='T'?'–':''));return `<i class="${cls}" title="${v||'No match'}">${label}</i>`;}).join('')}</span>`;
  }
  function nhlRecord(row){const raw=rowRecord(row);const m=raw.match(/\d+\s*-\s*\d+\s*-\s*\d+/);return m?m[0].replace(/\s+/g,''):raw;}
  function rowMarkup(row,{league='',position=0,rowClass='',wildcard=false}={}){
    const soccer=['EPL','MLS'].includes(league);
    const secondary=soccer?clean(row.gamesPlayed||row.played||'—'):(wildcard&&['MLB','NFL'].includes(league)?clean(row.wildcardGamesBehind||'—'):rowSecondary(row,league));
    const third=soccer?soccerRecord(row):(league==='NCAAF'?clean(row.conferenceRecord||row.gamesBehind||row.pct||'—'):secondary);
    const fourth=soccer?clean(row.points||'—'):clean(row.streak||'—');
    const record=league==='NHL'?nhlRecord(row):rowRecord(row);
    const cells=[`<td><span class="league-view-team"><i>${position||''}</i>${row.logo?`<img src="${esc(row.logo)}" alt="" loading="lazy">`:''}<b>${esc(row.name||row.abbreviation)}</b></span></td>`,
      `<td>${esc(soccer?secondary:record)}</td>`,`<td>${esc(third)}</td>`,`<td>${esc(fourth)}</td>`];
    if(soccer)cells.push(`<td class="league-view-form-cell">${formMarkup(row.form||[])}</td>`);
    return `<tr class="${esc(rowClass)}">${cells.join('')}</tr>`;
  }
  function placeholderRows(count,columns=4){
    return Array.from({length:Math.max(0,Number(count)||0)},()=>`<tr class="league-view-placeholder-row" aria-hidden="true">${Array.from({length:columns},()=>'<td>&nbsp;</td>').join('')}</tr>`).join('');
  }
  function tableForGroup(group,{compact=false,title='',league='',cutoffs=[],padTo=0}={}){
    const rows=(group?.entries||[]).slice(0,25); if(!rows.length)return '';
    const headers=tableHeaders(league),blankCount=Math.max(0,(Number(padTo)||0)-rows.length);
    return `<section class="league-view-card league-view-standings-card${compact?' compact':''}"><div class="league-view-card-head"><strong>${esc(title||group.name||'STANDINGS')}</strong><span>${rows.length} TEAMS</span></div><div class="league-view-table-wrap"><table class="league-view-table"><thead><tr>${headers.map((h,i)=>`<th${i===0?' class="team-col"':''}>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map((row,i)=>rowMarkup(row,{league,position:i+1,rowClass:cutoffs.includes(i+1)?'league-view-cutoff':''})).join('')}${placeholderRows(blankCount,headers.length)}</tbody></table></div></section>`;
  }
  function wildcardCard(rows,title='WILD CARD',league='MLB',padTo=0){
    if(!rows?.length)return '';
    const headers=tableHeaders(league,{wildcard:true}),visible=rows.slice(0,10),blankCount=Math.max(0,(Number(padTo)||0)-visible.length);
    return `<section class="league-view-card league-view-wildcard"><div class="league-view-card-head"><strong>${esc(title)}</strong><span>${league==='NHL'?'TOP 3 / DIVISION EXCLUDED':((league==='MLB'||league==='NFL')?'RELATIVE TO FINAL WILD CARD SPOT':'CURRENT PLAYOFF CHASE')}</span></div><div class="league-view-table-wrap"><table class="league-view-table"><thead><tr>${headers.map((h,i)=>`<th${i===0?' class="team-col"':''}>${esc(h)}</th>`).join('')}</tr></thead><tbody>${visible.map((row,i)=>rowMarkup(row,{league,position:i+1,wildcard:true,rowClass:((league==='NHL'&&i===1)||((league==='MLB'||league==='NFL')&&i===2))?'league-view-cutoff':''})).join('')}${placeholderRows(blankCount,headers.length)}</tbody></table></div></section>`;
  }
  function conferenceBoard(rows,league){
    if(!Array.isArray(rows)||rows.length<2)return '';
    const wanted=league==='MLB'?['AL','NL']:(league==='NFL'?['AFC','NFC']:['EAST','WEST']);
    const ordered=wanted.map(key=>rows.find(x=>upper(x?.key)===key)).filter(Boolean);
    if(ordered.length<2)return '';
    // v5.4.5: paired conference/division columns share the same row slots.
    // A four-team division opposite a five-team division gets one invisible
    // placeholder row, so the next division heading starts at exactly the same
    // vertical position on both sides.
    const maxDivisionCount=Math.max(...ordered.map(conf=>Array.isArray(conf.divisions)?conf.divisions.length:0),0);
    const divisionPad=Array.from({length:maxDivisionCount},(_,i)=>Math.max(...ordered.map(conf=>Number(conf?.divisions?.[i]?.entries?.length||0)),0));
    const wildcardPad=Math.max(...ordered.map(conf=>Math.min(10,Number(conf?.wildcard?.length||0))),0);
    return `<div class="league-view-conference-grid league-view-${league.toLowerCase()}">${ordered.map(conf=>{
      let inner='';
      if(Array.isArray(conf.divisions)&&conf.divisions.length){for(let i=0;i<conf.divisions.length;i++){const division=conf.divisions[i];inner+=tableForGroup(division,{compact:true,title:division.name,league,padTo:divisionPad[i]||division.entries?.length||0});}}
      else if(Array.isArray(conf.standings)&&conf.standings.length){
        const cutoffs=league==='NBA'?[6,10]:(league==='NHL'?[8]:[]);
        const pairedPad=Math.max(...ordered.map(c=>Number(c?.standings?.length||0)),0);
        inner+=tableForGroup({name:conf.name,entries:conf.standings},{compact:false,title:'CONFERENCE STANDINGS',league,cutoffs,padTo:pairedPad});
      }
      // v5.3.11 compatibility contract: if(league==='MLB'||league==='NFL')inner+=wildcardCard now also includes NHL.
      if(league==='MLB'||league==='NFL'||league==='NHL')inner+=wildcardCard(conf.wildcard||[],'WILD CARD',league,wildcardPad);
      const sub=(league==='MLB'||league==='NFL'||league==='NHL')?'DIVISIONS + WILD CARD':'CONFERENCE TABLE';
      return `<section class="league-view-conference"><div class="league-view-conference-head"><strong>${esc(conf.name||conf.key)}</strong><span>${sub}</span></div>${inner}</section>`;
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

  function splitEventMatch(value){return clean(value).split(/\s+(?:@|at|vs\.?|v)\s+/i).map(clean).filter(Boolean).slice(0,2);}
  function eventRound(game,league){
    const direct=clean(game?.round||game?.group);if(direct)return direct.toUpperCase();
    const title=clean(game?.sourceTitle);const hit=title.match(/(ROUND\s+(?:OF\s+)?\d+|ROUND\s+\d+|QUARTER[- ]?FINALS?|SEMI[- ]?FINALS?|FINALS?|THIRD PLACE|GROUP\s+[A-L])/i);if(hit)return hit[1].toUpperCase().replace('QUARTERFINAL','QUARTERFINAL').replace('SEMIFINAL','SEMIFINAL');
    const d=clean(game?.date).slice(0,10);
    if(league==='WC2026'&&d){
      if(d<='2026-06-27')return 'GROUP STAGE';if(d<='2026-07-03')return 'ROUND OF 32';if(d<='2026-07-07')return 'ROUND OF 16';if(d<='2026-07-11')return 'QUARTERFINALS';if(d<='2026-07-15')return 'SEMIFINALS';if(d==='2026-07-18')return 'THIRD PLACE';if(d>='2026-07-19')return 'FINAL';
    }
    return '';
  }
  function eventGames(context,payload){
    const local=Array.isArray(context?.eventGames)?context.eventGames:[];const fallback=Array.isArray(context?.games)?context.games:[];
    const server=Array.isArray(payload?.games)?payload.games.map(g=>({date:g.date,game:g.name,status:g.status,round:g.round,awayScore:g.away?.score,homeScore:g.home?.score})):[];
    const rows=[...local,...fallback,...server],seen=new Set(),out=[];
    for(const game of rows){const key=`${clean(game.date).slice(0,10)}|${upper(game.game||game.name)}`;if(!clean(game.game||game.name)||seen.has(key))continue;seen.add(key);out.push(game);}return out;
  }
  function groupStandings(games,league){
    const groups=new Map();
    for(const game of games){let group=clean(game.group);if(!group){const r=eventRound(game,league);if(/^GROUP\s+[A-L]$/i.test(r))group=r;}if(!/^GROUP\s+[A-L]$/i.test(group))continue;
      const teams=splitEventMatch(game.game||game.name);if(teams.length<2)continue;const a=Number(game.awayScore),h=Number(game.homeScore);if(!Number.isFinite(a)||!Number.isFinite(h))continue;
      if(!groups.has(group))groups.set(group,new Map());const table=groups.get(group);
      const row=name=>{const key=upper(name);if(!table.has(key))table.set(key,{name,P:0,W:0,D:0,L:0,GF:0,GA:0,Pts:0});return table.get(key);};const ar=row(teams[0]),hr=row(teams[1]);
      ar.P++;hr.P++;ar.GF+=a;ar.GA+=h;hr.GF+=h;hr.GA+=a;if(a>h){ar.W++;ar.Pts+=3;hr.L++;}else if(h>a){hr.W++;hr.Pts+=3;ar.L++;}else{ar.D++;hr.D++;ar.Pts++;hr.Pts++;}
    }
    return [...groups.entries()].sort((a,b)=>a[0].localeCompare(b[0])).map(([name,map])=>({name,entries:[...map.values()].sort((a,b)=>b.Pts-a.Pts||((b.GF-b.GA)-(a.GF-a.GA))||b.GF-a.GF||a.name.localeCompare(b.name))}));
  }
  function worldCupGroupCard(group){
    return `<section class="league-view-card league-view-event-group"><div class="league-view-card-head"><strong>${esc(group.name)}</strong><span>PTS · GD</span></div><table class="league-view-table league-view-group-table"><thead><tr><th class="team-col">TEAM</th><th>P</th><th>W-D-L</th><th>GD</th><th>PTS</th></tr></thead><tbody>${group.entries.map((row,i)=>`<tr><td><span class="league-view-team"><i>${i+1}</i><b>${esc(row.name)}</b></span></td><td>${row.P}</td><td>${row.W}-${row.D}-${row.L}</td><td>${row.GF-row.GA>=0?'+':''}${row.GF-row.GA}</td><td><b>${row.Pts}</b></td></tr>`).join('')}</tbody></table></section>`;
  }
  function bracketBoard(games,league){
    const buckets=new Map();for(const game of games){const round=eventRound(game,league);if(!round||/^GROUP(?: STAGE|\s+[A-L])/.test(round))continue;if(!buckets.has(round))buckets.set(round,[]);buckets.get(round).push(game);}
    if(!buckets.size)return '';
    const order=['ROUND OF 128','ROUND 1','ROUND OF 64','ROUND 2','ROUND OF 32','ROUND 3','ROUND OF 16','ROUND 4','QUARTERFINALS','SEMIFINALS','THIRD PLACE','FINAL'];
    const groups=[...buckets.entries()].sort((a,b)=>{const ai=order.indexOf(a[0]),bi=order.indexOf(b[0]);return (ai<0?99:ai)-(bi<0?99:bi)||a[0].localeCompare(b[0]);});
    return `<section class="league-view-card league-view-bracket"><div class="league-view-card-head"><strong>BRACKET / ROUNDS</strong><span>${groups.length} STAGES</span></div><div class="league-view-bracket-grid">${groups.map(([round,rows])=>`<div class="league-view-round-column"><strong>${esc(round)}</strong>${rows.slice(0,32).map(game=>{const teams=splitEventMatch(game.game||game.name);const score=(game.awayScore!==null&&game.awayScore!==undefined&&game.homeScore!==null&&game.homeScore!==undefined)?`${game.awayScore}–${game.homeScore}`:'';return `<span><b>${esc(teams.length===2?`${teams[0]} vs ${teams[1]}`:(game.game||game.name))}</b><small>${esc(score||game.status||clean(game.date).slice(5,10))}</small></span>`;}).join('')}</div>`).join('')}</div></section>`;
  }
  function specialEventBoard(league,context,payload){
    const games=eventGames(context,payload);if(!games.length)return '';
    let html='';if(league==='WC2026'){const groups=groupStandings(games,league);if(groups.length)html+=`<div class="league-view-event-group-grid">${groups.map(worldCupGroupCard).join('')}</div>`;}
    html+=bracketBoard(games,league);
    if(!html)html+=gamesCard(games,true);
    return html;
  }

  function render(){
    const root=$('leagueViewRoot');if(!root)return;
    const league=state.league||currentLeague();const payload=state.payload||{};const label=leagueLabel(league,payload);const special=payload.specialEvent===true||!core.has(league);
    const context=curatedContext();
    const updated=payload.savedAt?new Date(Number(payload.savedAt)*1000).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'}):'';
    let body='';
    if(state.loading&&!state.payload)body='<div class="league-view-loading"><span></span>Loading standings and league context…</div>';
    else if(state.error&&!payload.standings?.length&&!context?.games?.length)body=`<div class="league-view-empty"><strong>LEAGUE VIEW TEMPORARILY UNAVAILABLE</strong><span>${esc(state.error)}</span></div>`;
    else{
      if(payload.rankings?.length)body+=rankingsCard(payload.rankings);
      const conferenceLayout=conferenceBoard(payload.conferences||[],league);
      if(conferenceLayout)body+=conferenceLayout;
      else for(const group of payload.standings||[])body+=tableForGroup(group,{league});
      // Core league views are intentionally standings-first. The previous lower
      // Pulse/Series/Today blocks consumed the exact space needed for divisions
      // and Wild Card context. Special events retain bracket/round context.
      if(special){body+=specialEventBoard(league,context,payload);if(!body)body+=localEventCard(context);}
      if(!body)body='<div class="league-view-empty"><strong>LEAGUE CONTEXT</strong><span>No public standings table is available for this event yet. Big Board event highlights remain available in the ribbon and Team Browse.</span></div>';
    }
    const descriptor=league==='MLB'?'Divisions · Wild Card':(league==='NFL'?'Divisions · Wild Card':(league==='NBA'?'Conference standings · playoff / play-in lines':(league==='NHL'?'Divisions · Wild Card':(league==='NCAAF'?'AP Top 25 · conference standings':(['EPL','MLS'].includes(league)?'League table':'Groups · bracket / rounds')))));
    root.innerHTML=`<div class="league-view-head"><div><small>${special?'SPECIAL EVENT':'LEAGUE VIEW'}</small><h2>${esc(label)}</h2><span class="league-view-muted">${esc(descriptor)}</span></div><div class="league-view-head-actions">${state.refreshing?'<span class="league-view-updated">REFRESHING…</span>':(updated?`<span class="league-view-updated">UPDATED ${esc(updated)}</span>`:'')}<button id="leagueViewRefresh" type="button" title="Refresh League View">↻</button></div></div><div class="league-view-content">${body}</div>`;
    $('leagueViewRefresh')?.addEventListener('click',()=>refresh(true));
  }

  async function refresh(force=false){
    const league=currentLeague();
    if(!force&&state.loading&&league===state.league)return;
    const token=++state.request;const same=league===state.league&&!!state.payload;state.league=league;state.error='';state.loading=!same;state.refreshing=same;render();
    try{
      const response=await fetch(apiUrl(`/api/league-view?league=${encodeURIComponent(league)}${force?'&force=1':''}`),{cache:force?'no-store':'default'});
      const payload=await response.json().catch(()=>({}));if(token!==state.request)return;
      if(!response.ok||payload?.ok===false)throw new Error(payload?.error||`HTTP ${response.status}`);
      state.payload=payload;state.lastFetchedAt=Date.now();
    }catch(err){if(token!==state.request)return;state.error=clean(err?.message||err);if(!state.payload||state.league!==league)state.payload={league,standings:[],playoffRace:[],rankings:[],games:[],specialEvent:!core.has(league)};}
    finally{if(token===state.request){state.loading=false;state.refreshing=false;render();}}
  }

  function syncContext({forceRefresh=false}={}){
    const league=currentLeague();const aggregate=isAggregate();state.aggregate=aggregate;recapGameCenter(aggregate);
    const key=`${league}|${aggregate?'recap':'game'}|${currentTitle()}`;
    if(league!==state.league||!state.payload){refresh(false);}else if(forceRefresh&&Date.now()-state.lastFetchedAt>5*60*1000){refresh(false);}else if(key!==state.lastAggregateKey)render();
    state.lastAggregateKey=key;
  }
  function scheduleContextSync({forceRefresh=false}={}){
    clearTimeout(state.syncTimer);state.syncTimer=setTimeout(()=>syncContext({forceRefresh}),90);
  }

  function bind(){
    $('upNextTabBtn')?.addEventListener('click',()=>{const league=currentLeague();if(league!==state.league||!state.payload)refresh(false);else render();});
    $('upNextDrawerBtn')?.addEventListener('click',()=>setTimeout(()=>{const league=currentLeague();if(league!==state.league||!state.payload)refresh(false);else render();},0));
    $('scoreFilters')?.addEventListener('click',event=>{const filter=event.target.closest('[data-score-filter]');if(!filter)return;const requested=normalizeLeague(filter.dataset.scoreFilter);state.navLeague=requested&&requested!=='ALL'?requested:'';scheduleContextSync();});
    window.addEventListener('sbb:league-context',event=>{const requested=normalizeLeague(event?.detail?.league);state.navLeague=requested&&requested!=='ALL'?requested:'';scheduleContextSync();});
    window.addEventListener('sbb:special-context',event=>{const requested=normalizeLeague(event?.detail?.league);state.navLeague=event?.detail?.active&&requested?requested:'';scheduleContextSync();});
    window.addEventListener('sbb:special-event-data',()=>{if(!state.loading)render();});
    window.addEventListener('sbb:curated-queue-release',()=>{state.navLeague='';scheduleContextSync();});
    window.addEventListener('sbb:curated-event-identity',()=>{state.navLeague='';scheduleContextSync();});
    window.addEventListener('sbb:score-click-selection',()=>{state.navLeague='';scheduleContextSync();});
    window.addEventListener('sbb:league-view-refresh',()=>refresh(true));
    try{window.SBB_SELECTED_EVENT?.subscribe?.(()=>scheduleContextSync());}catch(_){}
    const title=$('currentTitle');if(title){state.observer=new MutationObserver(()=>{if(!state.navLeague)scheduleContextSync();});state.observer.observe(title,{childList:true,subtree:true,characterData:true});}
    scheduleContextSync({forceRefresh:true});
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
  window.SBB_LEAGUE_VIEW=Object.freeze({version:VERSION,refresh,isAggregate,snapshot:()=>({league:state.league,navLeague:state.navLeague,aggregate:state.aggregate,loading:state.loading,refreshing:state.refreshing,error:state.error,payload:state.payload})});
})();

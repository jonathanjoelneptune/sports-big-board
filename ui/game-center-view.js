/* Sports Big Board v5.1.20 — identity-stable Game Center renderer.
   Repeated SelectedEvent notifications for the SAME canonical game join one load.
   Only a different game or explicit Retry may abort an active request. A view-level
   watchdog guarantees the drawer can never remain on an infinite loading spinner.
*/
(() => {
  const $=id=>document.getElementById(id);
  const UI_WATCHDOG_MS=12000;
  let selected=null,data=null,requestToken=0,pollTimer=null,activeRequest=null,activeSection='overview',playsMode='scoring',activePlayerSide='away';
  const diagnostics={loads:0,joined:0,aborted:0,watchdogs:0,lastKey:'',lastResult:'',lastElapsedMs:0};
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const clean=v=>String(v??'').trim();
  const enriching=gc=>gc?.coverage?.complete===false||gc?.partial===true||(gc?.quality?.level&&gc.quality.level!=='rich');
  const teamName=t=>t?.abbreviation||t?.shortName||t?.name||'—';
  const teamLong=t=>t?.name||t?.displayName||t?.abbreviation||'—';
  const logoUrl=t=>String(t?.logo||t?.logoUrl||t?.image||t?.imageUrl||'').trim();
  function selectedTeam(side){
    const parts=eventParticipants(selected||{});
    return parts?.[side]||{};
  }
  function mergeTeam(team,side){
    const fallback=selectedTeam(side),primary=team||{},out={...fallback,...primary};
    for(const key of ['id','name','displayName','shortName','abbreviation']) if(!out[key]) out[key]=fallback?.[key]||'';
    out.logo=logoUrl(primary)||logoUrl(fallback);
    return out;
  }
  function logoMarkup(team,side,label=''){
    const merged=mergeTeam(team,side),src=logoUrl(merged),abbr=teamName(merged).slice(0,3);
    return `<span class="gc-mini-logo-wrap">${src?`<img class="gc-mini-logo" src="${esc(src)}" alt="">`:''}<span class="gc-mini-logo-fallback${src?' hidden':''}">${esc(abbr||label||'?')}</span></span>`;
  }
  function setTeam(id,team,score){
    const el=$(id); if(!el) return;
    const side=id==='gcAwayTeam'?'away':'home',resolved=mergeTeam(team,side);
    const ab=el.querySelector('.gc-team-abbr'),name=el.querySelector('.gc-team-name'),sc=el.querySelector('.gc-team-score');
    const img=el.querySelector('.gc-team-logo'),fallback=el.querySelector('.gc-team-logo-fallback'),src=logoUrl(resolved);
    if(ab) ab.textContent=teamName(resolved); if(name) name.textContent=teamLong(resolved); if(sc) sc.textContent=score==null||score===''?'—':score;
    if(fallback){fallback.textContent=teamName(resolved).slice(0,3);fallback.classList.toggle('hidden',!!src);}
    if(img){
      if(src){img.src=src;img.classList.remove('hidden');img.onerror=()=>{img.classList.add('hidden');fallback?.classList.remove('hidden');};}
      else{img.removeAttribute('src');img.classList.add('hidden');}
    }
  }
  function eventParticipants(evt){
    const parts=evt?.participants||[];
    return {away:evt?.awayTeam||evt?.away||parts.find(x=>x.side==='away')||parts[0]||{},home:evt?.homeTeam||evt?.home||parts.find(x=>x.side==='home')||parts[1]||{}};
  }
  function eventScore(evt,side){ return evt?.[`${side}Score`]??evt?.[`score${side[0].toUpperCase()+side.slice(1)}`]??evt?.score?.[`${side}Score`]??evt?.[side]?.score??''; }
  function eventKey(evt){
    if(!evt)return '';
    try{const key=clean(window.SBB_GAME_CENTER?.identity?.(evt)?.key);if(key)return key;}catch(_){}
    try{const key=clean(window.SBB_EVENT_IDENTITY?.key?.(evt));if(key)return key;}catch(_){}
    const comp=clean(evt?.competitionId||evt?.__sbbLeague||evt?.league).toUpperCase();
    const id=[evt?.gameCenterEventId,evt?.scoreEventId,evt?.espnEventId,evt?.gamePk,evt?.eventId,evt?.matchId,evt?.id].find(v=>clean(v));
    if(id)return `${comp}:ID:${clean(id)}`;
    const parts=eventParticipants(evt),name=t=>clean(t?.name||t?.displayName||t?.shortName||t?.abbreviation).toLowerCase().replace(/[^a-z0-9]+/g,'');
    const date=clean(evt?.date||evt?.scheduledAt||evt?.gameDate).slice(0,10);
    return `${comp}:${date}:${name(parts.away)}:${name(parts.home)}`;
  }
  function basicShell(evt,message='Loading game data…'){
    $('gameCenterEmpty')?.classList.add('hidden'); $('gameCenterContent')?.classList.remove('hidden');
    const {away,home}=eventParticipants(evt||{}); setTeam('gcAwayTeam',away,eventScore(evt,'away')); setTeam('gcHomeTeam',home,eventScore(evt,'home'));
    if($('gcStatus')) $('gcStatus').textContent=evt?.status||message;
    if($('gcVenue')) $('gcVenue').textContent=evt?.venue||evt?.competitionName||evt?.competitionId||'';
    if($('gcUpdated')) $('gcUpdated').textContent='';
    ['gcOverview','gcTeamStats','gcPlayers','gcPlays'].forEach(id=>{const el=$(id);if(el)el.innerHTML=`<div class="gc-loading"><span class="sbb-loading-spinner" aria-hidden="true"></span><span>${esc(message)}</span></div>`;});
  }
  function statusText(gc){
    const s=gc?.scoreboard||{},bits=[];
    if(s.status) bits.push(s.status);
    if(s.inningOrdinal||s.inning) bits.push([s.inningState,s.inningOrdinal||s.inning].filter(Boolean).join(' '));
    else if(s.period!=null||s.clock){const sport=String(gc?.sportId||gc?.event?.sportId||'').toLowerCase();const prefix=sport==='tennis'?`SET ${s.period}`:(gc?.competitionId==='NFL'?`Q${s.period}`:(gc?.competitionId==='MLS'||gc?.competitionId==='EPL'?`H${s.period}`:`P${s.period}`));bits.push([s.period!=null?prefix:'',s.clock].filter(Boolean).join(' • '));}
    if(s.outs!=null&&gc?.live) bits.push(`${s.outs} out${Number(s.outs)===1?'':'s'}`);
    return bits.filter(Boolean).join(' • ')||gc?.event?.status||'—';
  }
  function scoringCard(gc){
    const scoring=(gc.scoringPlays||[]).slice(-10).reverse();
    return `<div class="gc-card"><div class="gc-card-title">SCORING / KEY PLAYS</div>${scoring.length?scoring.map(p=>`<div class="gc-play-row scoring"><span>${esc(p.periodLabel||p.period||'')}</span><div><strong>${esc(p.description||'Scoring play')}</strong>${p.scoreAway!==''||p.scoreHome!==''?`<small>${esc(p.scoreAway)} – ${esc(p.scoreHome)}</small>`:''}</div></div>`).join(''):(enriching(gc)?'<div class="gc-empty-row">Loading scoring plays…</div>':'<div class="gc-empty-row">No scoring plays available.</div>')}</div>`;
  }
  function renderOverview(gc){
    const s=gc.scoreboard||{},away=s.away||{},home=s.home||{},innings=window.SBB_GAME_CENTER_LINESCORE?.reconcile?.(s,gc?.competitionId)||s.innings||[];
    let primary='';
    if(innings.length){
      const maxInnings=Math.max(9,innings.length||0),byNum=new Map(innings.map(x=>[Number(x.num),x]));
      const heads=Array.from({length:maxInnings},(_,i)=>`<th>${i+1}</th>`).join('');
      const row=(label,side)=>`<tr><th class="gc-lines-team">${esc(label)}</th>${Array.from({length:maxInnings},(_,i)=>{const x=byNum.get(i+1);return `<td>${esc(x?x[side]:'')}</td>`}).join('')}<th>${esc(s.totals?.[side]?.runs??'')}</th><th>${esc(s.totals?.[side]?.hits??'')}</th><th>${esc(s.totals?.[side]?.errors??'')}</th></tr>`;
      primary=`<div class="gc-card"><div class="gc-card-title">LINESCORE</div><div class="gc-table-scroll"><table class="gc-linescore"><thead><tr><th></th>${heads}<th>R</th><th>H</th><th>E</th></tr></thead><tbody>${row(teamName(away.team),'away')}${row(teamName(home.team),'home')}</tbody></table></div></div>`;
    }else{
      const rows=(gc.teamStats||[]).slice(0,8);
      primary=`<div class="gc-card"><div class="gc-card-title">GAME OVERVIEW</div><div class="gc-basic-overview"><strong>${esc(teamName(away.team))} ${esc(away.score)} – ${esc(home.score)} ${esc(teamName(home.team))}</strong><span>${esc(statusText(gc))}</span><small>${esc(s.venue||gc.event?.competitionId||'')}</small></div>${rows.length?`<table class="gc-stat-compare gc-overview-stats"><tbody>${rows.map(r=>`<tr><td>${esc(r.away)}</td><th>${esc(r.label)}</th><td>${esc(r.home)}</td></tr>`).join('')}</tbody></table>`:''}</div>`;
    }
    $('gcOverview').innerHTML=primary+scoringCard(gc);
  }
  function renderTeamStats(gc){
    const s=gc.scoreboard||{},away=teamName(s.away?.team),home=teamName(s.home?.team),rows=gc.teamStats||[];
    $('gcTeamStats').innerHTML=`<div class="gc-card"><div class="gc-card-title">TEAM STATS</div><table class="gc-stat-compare"><thead><tr><th>${esc(away)}</th><th></th><th>${esc(home)}</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.away)}</td><th>${esc(r.label)}</th><td>${esc(r.home)}</td></tr>`).join('')}</tbody></table>${rows.length?'':(enriching(gc)?'<div class="gc-empty-row">Loading team stats…</div>':'<div class="gc-empty-row">Team stats are not available yet.</div>')}</div>`;
  }
  function playerSectionSide(sec,awayTeam,homeTeam){
    const explicit=String(sec?.teamSide||'').toLowerCase();
    if(explicit==='away'||explicit==='home') return explicit;
    const title=String(sec?.title||'').toLowerCase();
    const candidates=[['away',awayTeam],['home',homeTeam]];
    for(const [side,team] of candidates){
      for(const token of [team?.id,team?.abbreviation,team?.shortName,team?.name,team?.displayName]){
        const value=String(token||'').trim().toLowerCase();
        if(value && title.startsWith(value)) return side;
      }
    }
    return '';
  }
  function playerSectionTitle(sec,team){
    let title=String(sec?.title||'Players').trim();
    for(const token of [team?.name,team?.displayName,team?.shortName,team?.abbreviation]){
      const value=String(token||'').trim();
      if(value && title.toLowerCase().startsWith(value.toLowerCase())){
        title=title.slice(value.length).replace(/^\s*[-–—:|]?\s*/,'').trim()||'Players';
        break;
      }
    }
    return title;
  }
  function renderPlayers(gc){
    const all=(gc.playerStatSections||[]).filter(x=>x&&x.rows?.length);
    const board=gc.scoreboard||{},awayTeam=mergeTeam(board.away?.team,'away'),homeTeam=mergeTeam(board.home?.team,'home');
    const grouped={away:[],home:[],other:[]};
    all.forEach(sec=>{const side=playerSectionSide(sec,awayTeam,homeTeam);(grouped[side]||grouped.other).push(sec);});
    const available=['away','home'].filter(side=>grouped[side].length);
    if(available.length && !available.includes(activePlayerSide)) activePlayerSide=available[0];
    const team=activePlayerSide==='home'?homeTeam:awayTeam;
    const sections=available.length?grouped[activePlayerSide]:all;
    const tabs=all.length?`<div class="gc-player-team-tabs" role="tablist" aria-label="Player statistics team">${[['away',awayTeam],['home',homeTeam]].map(([side,t])=>`<button type="button" data-gc-player-side="${side}" class="gc-player-team-tab ${activePlayerSide===side?'active':''}" ${grouped[side].length?'':'disabled'}>${logoMarkup(t,side)}<span>${esc(teamName(t))}</span></button>`).join('')}</div>`:'';
    const body=sections.length?sections.map(sec=>`<div class="gc-card gc-player-card"><div class="gc-card-title">${esc(playerSectionTitle(sec,team))}</div><div class="gc-table-scroll"><table class="gc-player-table"><thead><tr>${(sec.columns||[]).map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${(sec.rows||[]).map(row=>`<tr>${row.map((v,i)=>`<${i===0?'th':'td'}>${esc(v)}</${i===0?'th':'td'}>`).join('')}</tr>`).join('')}</tbody></table></div></div>`).join(''):`<div class="gc-card"><div class="gc-empty-row">${enriching(gc)?'Loading player statistics…':'Player statistics are not available yet.'}</div></div>`;
    $('gcPlayers').innerHTML=tabs+body;
    $('gcPlayers').querySelectorAll('[data-gc-player-side]').forEach(btn=>btn.addEventListener('click',()=>{
      const side=btn.dataset.gcPlayerSide;if(!grouped[side]?.length)return;activePlayerSide=side;renderPlayers(gc);
    }));
    $('gcPlayers').querySelectorAll('.gc-mini-logo').forEach(img=>img.addEventListener('error',()=>{img.classList.add('hidden');img.nextElementSibling?.classList.remove('hidden');},{once:true}));
  }
  function renderPlays(gc){
    const scoring=gc.scoringPlays||[],all=gc.timeline||[],rows=playsMode==='all'?all:scoring;
    $('gcPlays').innerHTML=`<div class="gc-play-filter"><button type="button" data-gc-plays="scoring" class="${playsMode==='scoring'?'active':''}">SCORING</button><button type="button" data-gc-plays="all" class="${playsMode==='all'?'active':''}">ALL PLAYS</button></div><div class="gc-card gc-plays-card">${rows.length?rows.slice().reverse().map(p=>`<div class="gc-play-row ${p.isScoring?'scoring':''}"><span>${esc(p.periodLabel||p.period||'')}</span><div><strong>${esc(p.description||'Play')}</strong>${p.batter||p.pitcher?`<small>${esc([p.batter,p.pitcher].filter(Boolean).join(' • '))}</small>`:''}${p.scoreAway!==''||p.scoreHome!==''?`<small class="gc-play-score">${esc(p.scoreAway)} – ${esc(p.scoreHome)}</small>`:''}</div></div>`).join(''):(enriching(gc)?'<div class="gc-empty-row">Loading play-by-play…</div>':'<div class="gc-empty-row">No play-by-play is available yet.</div>')}</div>`;
    $('gcPlays').querySelectorAll('[data-gc-plays]').forEach(btn=>btn.addEventListener('click',()=>{playsMode=btn.dataset.gcPlays;renderPlays(gc);}));
  }
  function render(gc){
    data=gc; $('gameCenterEmpty')?.classList.add('hidden'); $('gameCenterContent')?.classList.remove('hidden');
    const s=gc.scoreboard||{},away=s.away||{},home=s.home||{};
    setTeam('gcAwayTeam',away.team,away.score); setTeam('gcHomeTeam',home.team,home.score);
    $('gcStatus').textContent=statusText(gc); $('gcVenue').textContent=s.venue||gc.event?.competitionName||gc.event?.competitionId||'';
    const u=Date.parse(gc.updatedAt||''); const partial=enriching(gc);
    $('gcUpdated').textContent=(u?`Updated ${new Date(u).toLocaleTimeString([], {hour:'numeric',minute:'2-digit',second:'2-digit'})}`:'')+(partial?' • loading more details…':'');
    renderOverview(gc);renderTeamStats(gc);renderPlayers(gc);renderPlays(gc);selectSection(activeSection);
  }
  function selectSection(section){
    activeSection=['overview','team-stats','players','plays'].includes(section)?section:'overview';
    document.querySelectorAll('[data-gc-section]').forEach(b=>b.classList.toggle('active',b.dataset.gcSection===activeSection));
    document.querySelectorAll('[data-gc-pane]').forEach(p=>p.classList.toggle('hidden',p.dataset.gcPane!==activeSection));
  }
  function errorView(evt,err){
    basicShell(evt,'Game Center unavailable.');
    const {away,home}=eventParticipants(evt||{}),awayScore=eventScore(evt,'away'),homeScore=eventScore(evt,'home');
    setTeam('gcAwayTeam',away,awayScore);setTeam('gcHomeTeam',home,homeScore);$('gcStatus').textContent=evt?.status||'Game selected';
    $('gcOverview').innerHTML=`<div class="gc-card gc-error"><strong>GAME CENTER UNAVAILABLE</strong><span>${esc(err?.message||err||'Unable to load game data.')}</span><button id="gcRetryBtn" type="button">RETRY</button></div>`;
    $('gcTeamStats').innerHTML='<div class="gc-card"><div class="gc-empty-row">Team stats are not available.</div></div>';
    $('gcPlayers').innerHTML='<div class="gc-card"><div class="gc-empty-row">Player statistics are not available.</div></div>';
    $('gcPlays').innerHTML='<div class="gc-card"><div class="gc-empty-row">Play-by-play is not available.</div></div>';
    $('gcRetryBtn')?.addEventListener('click',()=>load(evt,{force:true}));
  }
  function schedulePoll(gc){
    if(pollTimer)clearTimeout(pollTimer);if(!selected)return;
    const status=String(gc?.event?.status||gc?.scoreboard?.status||selected?.status||'');
    const final=/final|finished|game over|completed|complete|post/i.test(status);
    const live=!final&&(!!gc?.live||/live|progress|inning|quarter|half|period/i.test(status));
    const partial=enriching(gc);
    const finalPartial=partial&&final;
    const delay=partial?(finalPartial?30000:2200):(live?15000:60000);
    pollTimer=setTimeout(()=>load(selected,{force:false,background:true}),delay);
  }
  function abortActive(reason='Selection changed'){
    const active=activeRequest;
    if(!active)return false;
    activeRequest=null;
    if(active.watchdog)clearTimeout(active.watchdog);
    diagnostics.aborted+=1;
    try{active.controller.abort(new DOMException(reason,'AbortError'));}catch(_){try{active.controller.abort();}catch(__){}}
    return true;
  }
  async function load(evt,{force=false,background=false}={}){
    if(!evt)return null;
    const key=eventKey(evt),oldKey=eventKey(selected);
    if(key&&oldKey&&key!==oldKey)activePlayerSide='away';
    selected=evt;
    diagnostics.lastKey=key;

    const resident=window.SBB_GAME_CENTER?.peek?.(evt)||null;
    if(resident){if(resident!==data)render(resident);}
    else if(!background&&!activeRequest)basicShell(evt,'Loading Game Center…');

    // v5.1.20: repeated ownership/selection notifications for the same sporting
    // event must join the existing transaction. They may refresh the selected
    // shell metadata, but they can never reset the provider request underneath it.
    if(!force&&activeRequest&&activeRequest.key===key){
      diagnostics.joined+=1;
      return activeRequest.promise;
    }

    if(activeRequest)abortActive(force?'Explicit Game Center retry':'Different Game Center selected');
    const token=++requestToken;
    const controller=new AbortController();
    const started=performance.now();
    let watchdogFired=false;
    diagnostics.loads+=1;

    if(!resident&&!background)basicShell(evt,'Loading Game Center…');

    const promise=(async()=>{
      try{
        const gc=await window.SBB_GAME_CENTER.get(evt,{force,signal:controller.signal,timeoutMs:10000});
        if(token!==requestToken)return null;
        if(gc!==data)render(gc);
        diagnostics.lastResult='READY';
        diagnostics.lastElapsedMs=Math.round((performance.now()-started)*10)/10;
        schedulePoll(gc);
        return gc;
      }catch(err){
        if(token!==requestToken)return null;
        if(watchdogFired)return null; // terminal UI was already rendered by watchdog
        if(err?.name==='AbortError')return null;
        diagnostics.lastResult='ERROR';
        diagnostics.lastElapsedMs=Math.round((performance.now()-started)*10)/10;
        errorView(evt,err);schedulePoll(null);
        return null;
      }finally{
        const active=activeRequest;
        if(active?.token===token){
          if(active.watchdog)clearTimeout(active.watchdog);
          activeRequest=null;
        }
      }
    })();

    const watchdog=setTimeout(()=>{
      const active=activeRequest;
      if(!active||active.token!==token||token!==requestToken)return;
      watchdogFired=true;
      diagnostics.watchdogs+=1;
      diagnostics.lastResult='WATCHDOG';
      diagnostics.lastElapsedMs=Math.round((performance.now()-started)*10)/10;
      try{controller.abort(new DOMException('Game Center view watchdog','TimeoutError'));}catch(_){try{controller.abort();}catch(__){}}
      errorView(evt,new Error('Game Center did not finish loading within 12 seconds. Tap Retry to try again.'));
      schedulePoll(null);
    },UI_WATCHDOG_MS);

    activeRequest={key,token,controller,promise,watchdog,started};
    return promise;
  }

  function clear(message='Game Center follows the active game video.'){
    selected=null;data=null;requestToken++;
    if(pollTimer){clearTimeout(pollTimer);pollTimer=null;}
    abortActive('Game Center cleared');
    $('gameCenterContent')?.classList.add('hidden');
    const empty=$('gameCenterEmpty');if(empty){empty.classList.remove('hidden');const strong=empty.querySelector('strong'),span=empty.querySelector('span');if(strong)strong.textContent='GAME CENTER';if(span)span.textContent=message;}
  }
  function init(){
    document.querySelectorAll('[data-gc-section]').forEach(btn=>btn.addEventListener('click',()=>selectSection(btn.dataset.gcSection)));
    window.SBB_SELECTED_EVENT?.subscribe?.((event)=>{if(!event){clear();return;}load(event);});
    const existing=window.SBB_SELECTED_EVENT?.get?.();if(existing)load(existing);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  window.SBB_GAME_CENTER_VIEW=Object.freeze({
    version:'1.8-v5.1.20',load,render,clear,selectSection,eventKey,
    snapshot:()=>({version:'1.8-v5.1.20',activeKey:activeRequest?.key||'',active:!!activeRequest,...diagnostics}),
    get selected(){return selected;}
  });
})();

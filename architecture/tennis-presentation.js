/* Sports Big Board v5.1.20 — stable tennis ribbon presentation.

   Tennis display data is projected BEFORE score-card construction so the ribbon
   never paints provider abbreviations and then grows to player names one frame
   later. Flags/round labels are applied synchronously on the render-pipeline commit,
   before paint, and the horizontal ribbon anchor is restored across same-date
   enrichment renders.
*/
(() => {
  'use strict';
  if(window.SBB_TENNIS_PRESENTATION?.version==='5.1.20')return;

  const VERSION='5.1.20';
  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const norm=v=>clean(v).toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
  let decorateQueued=false;
  let lastAnchor=null;
  let scrollBound=false;

  const IOC_TO_ISO2=Object.freeze({
    USA:'US',GBR:'GB',ESP:'ES',FRA:'FR',ITA:'IT',GER:'DE',DEU:'DE',AUT:'AT',SUI:'CH',
    SRB:'RS',CRO:'HR',CZE:'CZ',SVK:'SK',POL:'PL',ROU:'RO',BUL:'BG',GRE:'GR',TUR:'TR',
    RUS:'RU',UKR:'UA',BLR:'BY',KAZ:'KZ',UZB:'UZ',CHN:'CN',JPN:'JP',KOR:'KR',TPE:'TW',
    IND:'IN',AUS:'AU',NZL:'NZ',CAN:'CA',MEX:'MX',BRA:'BR',ARG:'AR',CHI:'CL',COL:'CO',
    PER:'PE',ECU:'EC',URU:'UY',PAR:'PY',RSA:'ZA',TUN:'TN',MAR:'MA',EGY:'EG',ISR:'IL',
    BEL:'BE',NED:'NL',SWE:'SE',NOR:'NO',DEN:'DK',FIN:'FI',POR:'PT',HUN:'HU',SLO:'SI',
    BIH:'BA',MNE:'ME',MKD:'MK',GEO:'GE',ARM:'AM',LTU:'LT',LAT:'LV',EST:'EE',THA:'TH',
    VIE:'VN',INA:'ID',PHI:'PH',MAS:'MY',IRL:'IE',CYP:'CY',LUX:'LU',MDA:'MD',MOL:'MD',
    CRC:'CR',DOM:'DO',PUR:'PR',VEN:'VE',BOL:'BO'
  });
  const COUNTRY_TO_ISO2=Object.freeze({
    'united states':'US','united states of america':'US','usa':'US','great britain':'GB','united kingdom':'GB','england':'GB',
    'spain':'ES','france':'FR','italy':'IT','germany':'DE','austria':'AT','switzerland':'CH','serbia':'RS','croatia':'HR',
    'czech republic':'CZ','czechia':'CZ','slovakia':'SK','poland':'PL','romania':'RO','bulgaria':'BG','greece':'GR','turkey':'TR',
    'russia':'RU','ukraine':'UA','belarus':'BY','kazakhstan':'KZ','uzbekistan':'UZ','china':'CN','japan':'JP','south korea':'KR',
    'taiwan':'TW','india':'IN','australia':'AU','new zealand':'NZ','canada':'CA','mexico':'MX','brazil':'BR','argentina':'AR',
    'chile':'CL','colombia':'CO','peru':'PE','ecuador':'EC','uruguay':'UY','paraguay':'PY','south africa':'ZA','tunisia':'TN',
    'morocco':'MA','egypt':'EG','israel':'IL','belgium':'BE','netherlands':'NL','sweden':'SE','norway':'NO','denmark':'DK',
    'finland':'FI','portugal':'PT','hungary':'HU','slovenia':'SI','bosnia and herzegovina':'BA','montenegro':'ME','georgia':'GE',
    'armenia':'AM','lithuania':'LT','latvia':'LV','estonia':'EE','thailand':'TH','vietnam':'VN','indonesia':'ID','philippines':'PH',
    'malaysia':'MY','ireland':'IE','cyprus':'CY','moldova':'MD','costa rica':'CR','dominican republic':'DO','puerto rico':'PR',
    'venezuela':'VE','bolivia':'BO'
  });

  function registryRows(){
    try{return window.SBB_FRONTEND_REGISTRY?.snapshot?.().competitions||[];}catch(_){return [];}
  }
  function competition(id){
    id=upper(id);
    return registryRows().find(x=>upper(x?.id)===id)||null;
  }
  function eventCompetition(evt){return upper(evt?.competitionId||evt?.__sbbLeague||evt?.league);}
  function isTennisCompetitionId(id){
    id=upper(id);if(!id)return false;
    const row=competition(id);
    if(clean(row?.sportId).toLowerCase()==='tennis')return true;
    // Registry is authoritative, but this narrow fallback protects first boot while
    // a dynamic special-event registry is still being projected into the browser.
    return /(?:^|[-_])(TENNIS|USOPEN|WIMBLEDON|ROLANDGARROS|FRENCHOPEN|AUSTRALIANOPEN|ATP|WTA)(?:[-_]|$)/.test(id)
      || /^USOPEN/.test(id);
  }
  function isTennis(evt){
    if(clean(evt?.sportId||evt?.event?.sportId).toLowerCase()==='tennis')return true;
    return isTennisCompetitionId(eventCompetition(evt));
  }

  function surname(value){
    let text=clean(value).replace(/^#?\d+\s+/,'');
    if(!text)return '';
    if(/[\/&+]/.test(text))return text.split(/\s*(?:\/|&|\+)\s*/).map(surname).filter(Boolean).join('/').slice(0,22);
    if(text.includes(','))return text.split(',',1)[0].trim().slice(0,18);
    const parts=text.split(/\s+/),particles=new Set(['de','del','della','di','da','dos','van','von','der','le','la']);
    if(parts.length>1&&particles.has(parts.at(-2).toLowerCase()))return `${parts.at(-2)} ${parts.at(-1)}`.slice(0,18);
    return (parts.at(-1)||text).slice(0,18);
  }
  function compactName(value,rank=''){
    let text=clean(value).replace(/^#?\d+\s+/,'');if(!text)return '';
    let label;
    if(/[\/&+]/.test(text))label=text.split(/\s*(?:\/|&|\+)\s*/).map(x=>compactName(x,'')).filter(Boolean).join('/');
    else{const parts=text.split(/\s+/);label=parts.length<=1?text:`${parts[0][0]?.toUpperCase()||''}. ${surname(text)}`.trim();}
    const r=clean(rank);if(r&&!['0','999','—'].includes(r))label=`#${r} ${label}`;
    return label.slice(0,26);
  }
  function roundFields(value){
    const raw=clean(value),v=raw.toLowerCase();
    if(!v||['round','rnd','main draw'].includes(v))return {roundNumber:null,roundName:'',displayRound:''};
    if(/quarter/.test(v))return {roundNumber:null,roundName:raw||'Quarterfinal',displayRound:'QF'};
    if(/semi/.test(v))return {roundNumber:null,roundName:raw||'Semifinal',displayRound:'SF'};
    if(/^(final|finals|championship)$/.test(v))return {roundNumber:null,roundName:raw||'Final',displayRound:'F'};
    if(/round of 16|round\s*16|fourth round|\br16\b/.test(v))return {roundNumber:null,roundName:raw,displayRound:'R16'};
    if(/round of 32|round\s*32|\br32\b/.test(v))return {roundNumber:null,roundName:raw,displayRound:'R32'};
    if(/round of 64|round\s*64|\br64\b/.test(v))return {roundNumber:null,roundName:raw,displayRound:'R64'};
    if(/round of 128|round\s*128|\br128\b/.test(v))return {roundNumber:null,roundName:raw,displayRound:'R128'};
    const named={'first round':1,'opening round':1,'second round':2,'third round':3,'fourth round':4};
    if(named[v]){const n=named[v];return {roundNumber:n,roundName:`Round ${n}`,displayRound:`R${n}`};}
    const m=v.match(/(?:round|r)\s*(\d+)/);if(m){const n=Number(m[1]);return {roundNumber:n,roundName:`Round ${n}`,displayRound:`R${n}`};}
    if(/qual/.test(v))return {roundNumber:null,roundName:raw,displayRound:'Q'};
    return {roundNumber:null,roundName:raw,displayRound:''};
  }
  function fullName(team){return clean(team?.displayName||team?.name||team?.fullName||team?.shortName||team?.abbreviation);}
  function rankOf(team){return clean(team?.rank||team?.seed||team?.ranking||team?.curatedRank?.current);}
  function rawRound(match){
    return clean(
      match?.tennisRound || match?.roundName || match?.round || match?.stage ||
      match?.tennis?.roundName || match?.tennis?.round || match?.tennis?.displayRound ||
      match?.tennisRoundShort || match?.displayRound
    );
  }
  function roundOf(match){
    const explicit=clean(match?.tennisRoundShort||match?.displayRound||match?.tennis?.displayRound);
    if(explicit&&upper(explicit)!=='ROUND')return explicit;
    return roundFields(rawRound(match)).displayRound;
  }
  function roundRibbonLabel(match){
    const raw=rawRound(match),fields=roundFields(raw),short=upper(fields.displayRound||roundOf(match));
    const comp=eventCompetition(match);
    const usOpen=/USOPEN|US[-_ ]?OPEN/.test(comp)||/us open/.test(clean(match?.competitionName).toLowerCase());
    if(short==='Q')return 'QUALIFYING';
    if(short==='QF')return 'QF';
    if(short==='SF')return 'SEMIS';
    if(short==='F')return 'FINAL';
    if(usOpen){
      if(short==='R128')return 'ROUND 1';
      if(short==='R64')return 'ROUND 2';
      if(short==='R32')return 'ROUND 3';
      if(short==='R16')return 'R16';
    }
    if(/^R\d+$/.test(short)){
      const n=Number(short.slice(1));
      if(n>=1&&n<=4)return `ROUND ${n}`;
      return short;
    }
    return raw ? raw.toUpperCase().slice(0,12) : '';
  }

  function countryCodeOf(team){
    if(!team||typeof team!=='object')return '';
    const values=[
      team.countryCode,team.country?.code,team.country?.abbreviation,team.nationalityCode,
      team.nationality?.code,team.flagCode,team.country,team.nationality,team.group,
      team.flag?.alt,team.athlete?.country,team.athlete?.flag?.alt
    ];
    for(const value of values){
      const raw=clean(value);if(!raw)continue;
      const up=upper(raw);
      if(/^[A-Z]{2}$/.test(up))return up;
      if(IOC_TO_ISO2[up])return IOC_TO_ISO2[up];
      const mapped=COUNTRY_TO_ISO2[norm(raw)];if(mapped)return mapped;
    }
    return '';
  }
  function flagEmoji(code){
    code=upper(code);
    if(!/^[A-Z]{2}$/.test(code))return '';
    return String.fromCodePoint(...[...code].map(ch=>127397+ch.charCodeAt(0)));
  }

  function preparedTeam(team){
    if(!team||typeof team!=='object')return team;
    const full=fullName(team),compact=compactName(full,rankOf(team));
    if(!compact)return team;
    return {
      ...team,
      // Preserve the provider shorthand for diagnostics, but make the first render
      // consume the exact player label the ribbon is going to keep.
      providerAbbreviation:clean(team.providerAbbreviation||team.abbreviation||team.abbr),
      abbreviation:compact,
      shortName:compact,
      __sbbTennisPrepared:true,
    };
  }
  function preparedMatch(match,league=''){
    if(!match||typeof match!=='object')return match;
    if(!(isTennis(match)||isTennisCompetitionId(league)))return match;
    const out={...match,sportId:clean(match.sportId)||'tennis'};
    const away=match.awayTeam||match.away;
    const home=match.homeTeam||match.home;
    if(match.awayTeam)out.awayTeam=preparedTeam(match.awayTeam);
    else if(match.away&&typeof match.away==='object')out.away=preparedTeam(match.away);
    if(match.homeTeam)out.homeTeam=preparedTeam(match.homeTeam);
    else if(match.home&&typeof match.home==='object')out.home=preparedTeam(match.home);
    if(Array.isArray(match.participants)){
      out.participants=match.participants.map((p,i)=>{
        if(!p||typeof p!=='object')return p;
        const side=clean(p.side).toLowerCase();
        if(side==='away'||(!side&&i===0))return preparedTeam(p);
        if(side==='home'||(!side&&i===1))return preparedTeam(p);
        return preparedTeam(p);
      });
    }
    return out;
  }
  function prepareRows(league,rows){
    if(!Array.isArray(rows)||!isTennisCompetitionId(league))return rows;
    return rows.map(row=>preparedMatch(row,league));
  }

  function installScoreProjection(){
    const original=window.storeScoreDateLeague;
    if(typeof original!=='function')return false;
    if(original.__sbbTennisProjectionV5120)return true;
    const wrapped=function(league,date,rows){
      return original.call(this,league,date,prepareRows(league,rows));
    };
    wrapped.__sbbTennisProjectionV5120=true;
    wrapped.__sbbOriginal=original;
    window.storeScoreDateLeague=wrapped;
    try{storeScoreDateLeague=wrapped;}catch(_){}
    return true;
  }

  function currentDate(){
    try{return clean(scoreBrowseDate).slice(0,10);}catch(_){return clean(window.scoreBrowseDate).slice(0,10);}
  }
  function stableKey(match){
    if(!match)return '';
    try{const key=clean(window.SBB_EVENT_IDENTITY?.key?.(match));if(key)return key;}catch(_){}
    try{const key=clean(window.SBB_GAME_CENTER?.identity?.(match)?.key);if(key)return key;}catch(_){}
    const comp=eventCompetition(match);
    const id=[match.scoreEventId,match.espnEventId,match.gameCenterEventId,match.eventId,match.matchId,match.gamePk,match.id]
      .find(v=>clean(v));
    if(id)return `${comp}:ID:${clean(id)}`;
    const away=fullName(match.awayTeam||match.away||{}),home=fullName(match.homeTeam||match.home||{});
    return `${comp}:${currentDate()}:${norm(away)}:${norm(home)}`;
  }
  function cardKey(card){return clean(card?.dataset?.sbbGameKey)||stableKey(card?.__sbbMatch);}
  function visibleCard(host){
    if(!host)return null;
    const cards=[...host.querySelectorAll('.score-card')].filter(card=>!card.hidden&&card.getClientRects().length);
    if(!cards.length)return null;
    const left=host.getBoundingClientRect().left;
    return cards.find(card=>card.getBoundingClientRect().right>left+1)||cards[0];
  }
  function captureAnchor(){
    const host=document.getElementById('scoreCells'),card=visibleCard(host);
    if(!host||!card)return host?{date:currentDate(),key:'',offset:0,scrollLeft:host.scrollLeft}:null;
    return {
      date:currentDate(),
      key:cardKey(card),
      offset:card.getBoundingClientRect().left-host.getBoundingClientRect().left,
      scrollLeft:host.scrollLeft,
    };
  }
  function restoreAnchor(anchor){
    const host=document.getElementById('scoreCells');
    if(!host||!anchor||anchor.date!==currentDate())return false;
    if(anchor.key){
      const card=[...host.querySelectorAll('.score-card')].find(node=>cardKey(node)===anchor.key);
      if(card){
        const offset=card.getBoundingClientRect().left-host.getBoundingClientRect().left;
        host.scrollLeft+=offset-anchor.offset;
        return true;
      }
    }
    host.scrollLeft=Math.max(0,Number(anchor.scrollLeft)||0);
    return true;
  }

  function decorateFlag(row,team){
    if(!row||!team)return;
    const fallback=row.querySelector('.score-team-logo-fallback');
    if(!fallback)return;
    const image=row.querySelector('.score-team-logo');
    const code=countryCodeOf(team),emoji=flagEmoji(code);
    fallback.classList.toggle('sbb-tennis-flag',!!emoji);
    if(emoji){
      // Tennis uses nationality in the fixed logo slot. This deliberately wins
      // over a provider headshot/placeholder so every player card has one stable
      // visual grammar and never changes width when metadata enriches.
      fallback.textContent=emoji;fallback.title=code;fallback.classList.remove('hidden');
      image?.classList.add('hidden');
    }
  }
  function decorateCards(){
    decorateQueued=false;
    document.querySelectorAll('.score-card').forEach(card=>{
      card.classList.remove('sbb-tennis-score-card');
      const match=card.__sbbMatch;
      if(!match||!isTennis(match))return;
      card.classList.add('sbb-tennis-score-card');
      const away=match.awayTeam||match.away||{},home=match.homeTeam||match.home||{};
      const teamLabels=[...card.querySelectorAll('.score-team-abbr')];
      [[away,teamLabels[0]],[home,teamLabels[1]]].forEach(([team,node])=>{
        if(!node)return;
        const full=fullName(team),compact=compactName(full,rankOf(team));
        if(compact)node.textContent=compact;
        if(full)node.title=full;
      });
      const rows=[...card.querySelectorAll('.score-team-row')];
      decorateFlag(rows[0],away);decorateFlag(rows[1],home);
      const topRight=card.querySelector('.score-card-top small');
      const roundLabel=roundRibbonLabel(match);
      if(topRight&&roundLabel){
        topRight.textContent=roundLabel;
        topRight.title=rawRound(match)||roundLabel;
        topRight.dataset.sbbTennisRound='1';
      }
    });
  }
  function scheduleDecorate(){
    if(decorateQueued)return;
    decorateQueued=true;
    // Microtask, not requestAnimationFrame: never permit an abbreviation frame to
    // reach the display before tennis presentation is reconciled.
    if(typeof queueMicrotask==='function')queueMicrotask(decorateCards);
    else Promise.resolve().then(decorateCards);
  }

  function applySelected(evt){
    const tennis=isTennis(evt);document.body?.classList.toggle('sbb-tennis-game-center-active',tennis);
    const labels={overview:'OVERVIEW','team-stats':tennis?'MATCH STATS':'TEAM STATS',players:'PLAYERS',plays:tennis?'SETS':'PLAYS'};
    document.querySelectorAll('[data-gc-section]').forEach(btn=>{const key=btn.dataset.gcSection;if(labels[key])btn.textContent=labels[key];});
  }
  function style(){
    if(document.getElementById('sbbTennisPresentationStyle'))return;
    const el=document.createElement('style');el.id='sbbTennisPresentationStyle';el.textContent=`
      .score-card.sbb-tennis-score-card .score-card-top small{min-width:46px;text-align:right;white-space:nowrap;font-size:7px;letter-spacing:.02em}
      .score-card.sbb-tennis-score-card .score-team-abbr{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .score-card.sbb-tennis-score-card .score-team-logo-wrap{flex:0 0 auto}
      .score-card.sbb-tennis-score-card .score-team-logo-fallback.sbb-tennis-flag{font-size:14px;line-height:1;letter-spacing:0;text-transform:none}
      @media (min-width:900px){
        body.sbb-tennis-game-center-active #infoDrawer:not(.is-closed){height:auto!important;max-height:none!important;align-self:stretch!important;overflow:visible!important}
        body.sbb-tennis-game-center-active #gameCenterPane,body.sbb-tennis-game-center-active #gameCenterContent{height:auto!important;max-height:none!important;overflow:visible!important}
        body.sbb-tennis-game-center-active #gameCenterPane{min-height:calc(100vh - 235px)}
        body.sbb-tennis-game-center-active #gameCenterContent .gc-section{max-height:none!important;overflow:visible!important}
      }`;
    document.head.appendChild(el);
  }
  function bindScrollAnchor(){
    if(scrollBound)return;
    const host=document.getElementById('scoreCells');if(!host)return;
    scrollBound=true;
    host.addEventListener('scroll',()=>{lastAnchor=captureAnchor();},{passive:true});
    lastAnchor=captureAnchor();
  }
  function prepareResident(){
    const store=window.SBB_SCORE_DATE;
    if(!store?.matches||!store?.setMatches)return;
    const dates=new Set();
    try{const snap=store.snapshot?.()||{};dates.add(snap.browseDate);dates.add(snap.today);}catch(_){}
    const tennisIds=registryRows().filter(row=>clean(row?.sportId).toLowerCase()==='tennis').map(row=>upper(row.id));
    for(const date of dates){
      if(!/^\d{4}-\d{2}-\d{2}$/.test(clean(date)))continue;
      for(const id of tennisIds){
        try{
          if(store.hasLeagueMatchesSnapshot?.(date,id))store.setMatches(date,id,prepareRows(id,store.matches(date,id)));
        }catch(_){}
      }
    }
  }
  function onPipelineEvent(ev){
    const type=clean(ev?.detail?.type);
    if(type!=='render')return;
    const prior=lastAnchor;
    decorateCards();
    restoreAnchor(prior);
    lastAnchor=captureAnchor();
  }
  function boot(){
    style();installScoreProjection();prepareResident();bindScrollAnchor();
    try{window.SBB_SELECTED_EVENT?.subscribe?.(evt=>applySelected(evt));applySelected(window.SBB_SELECTED_EVENT?.get?.());}catch(_){}
    window.addEventListener?.('sbb:render-pipeline',onPipelineEvent);
    try{window.SBB_SCORE_DATE?.subscribe?.((_snap,meta)=>{
      if(['browse','matches','loaded'].includes(meta?.action||''))scheduleDecorate();
    });}catch(_){}
    window.addEventListener?.('sbb:day-state-phase',ev=>{
      if(ev?.detail?.phase==='APPLY_TOTAL')scheduleDecorate();
    });
    window.addEventListener?.('sbb:competition-registry-updated',()=>{
      installScoreProjection();prepareResident();
      try{applySelected(window.SBB_SELECTED_EVENT?.get?.());}catch(_){}
      scheduleDecorate();
    });
    scheduleDecorate();
  }

  // Install the row projection at script evaluation time. DOM decoration waits for
  // boot, but Day State may start filling ScoreDateStore as soon as DOMContentLoaded
  // fires; the projection must already own that boundary before then.
  installScoreProjection();
  window.SBB_TENNIS_PRESENTATION=Object.freeze({
    version:VERSION,isTennis,surname,compactName,roundFields,roundShort:value=>roundFields(value).displayRound,
    roundRibbonLabel,countryCodeOf,flagEmoji,preparedMatch,prepareRows,decorateCards,scheduleDecorate,
    captureAnchor,restoreAnchor,apply:applySelected,installScoreProjection
  });
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();

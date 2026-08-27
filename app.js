

function bigBoardFullscreenElement(){
  return document.getElementById('app-shell') || document.documentElement;
}
async function toggleBigBoardFullscreen(){
  try{
    if(document.fullscreenElement){
      await document.exitFullscreen();
    }else{
      const el=bigBoardFullscreenElement();
      if(el.requestFullscreen) await el.requestFullscreen({navigationUI:'hide'});
      else if(el.webkitRequestFullscreen) el.webkitRequestFullscreen();
    }
  }catch(err){
    console.warn('[SBB] Big Board fullscreen failed',err);
  }
}
function updateBigBoardFullscreenButton(){
  const btn=document.getElementById('bigBoardFullscreenBtn');
  if(!btn) return;
  const active=!!document.fullscreenElement;
  btn.classList.toggle('active',active);
  btn.setAttribute('aria-label',active?'Exit Sports Big Board fullscreen':'Fullscreen Sports Big Board');
  btn.title=active?'Exit Sports Big Board fullscreen':'Fullscreen Sports Big Board';
}
document.addEventListener('fullscreenchange',()=>{
  updateBigBoardFullscreenButton();
  setTimeout(applyViewportMode,60);
});
document.addEventListener('webkitfullscreenchange',updateBigBoardFullscreenButton);
document.addEventListener('DOMContentLoaded',()=>{
  const btn=document.getElementById('bigBoardFullscreenBtn');
  btn?.addEventListener('click',toggleBigBoardFullscreen);
  updateBigBoardFullscreenButton();
});

function applyViewportMode(){
  const vv=window.visualViewport;
  const vw=Math.max(1,Math.round(vv?.width||window.innerWidth||document.documentElement.clientWidth||1));
  const vh=Math.max(1,Math.round(vv?.height||window.innerHeight||document.documentElement.clientHeight||1));
  const screenPortrait=!!(screen?.orientation?.type||'').includes('portrait');
  const mediaPortrait=window.matchMedia?.('(orientation: portrait)')?.matches===true;
  // Portrait wins whenever the visual viewport is taller than wide, or either
  // browser orientation signal reports portrait. This intentionally favors the
  // proven portrait composition on foldables/tablets.
  const portrait=(vh>=vw) || screenPortrait || mediaPortrait;
  document.body.classList.toggle('portrait-mode',portrait);
  document.body.classList.toggle('landscape-mode',!portrait);
  document.body.classList.toggle('sbb-portrait',portrait);
  document.body.classList.toggle('sbb-landscape',!portrait);
  document.documentElement.dataset.sbbViewport=`${vw}x${vh}:${portrait?'portrait':'landscape'}`;
}
const scheduleViewportMode=()=>requestAnimationFrame(()=>requestAnimationFrame(applyViewportMode));
window.addEventListener('resize',scheduleViewportMode,{passive:true});
window.visualViewport?.addEventListener('resize',scheduleViewportMode,{passive:true});
window.addEventListener('orientationchange',()=>setTimeout(scheduleViewportMode,120),{passive:true});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)setTimeout(scheduleViewportMode,80)});
document.addEventListener('DOMContentLoaded',scheduleViewportMode);
setTimeout(scheduleViewportMode,0);

// Local file:// pages do not send the HTTP referrer YouTube now requires for embeds.
if (location.protocol === 'file:') {
  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('localFileWarning')?.classList.remove('hidden');
    document.getElementById('bufferStatus').textContent = 'PLAYBACK: USE LOCALHOST';
  });
}

/* Sports Big Board v4.3.7 — canonical event/media architecture foundation; v2.5.30 playback behavior preserved. */


const DOMAIN_MODEL = window.SBB_CORE || null;
if(DOMAIN_MODEL) console.info(`[SBB] domain model ${DOMAIN_MODEL.version}: SPORT → COMPETITION → EVENT → MEDIA_PACKAGE → MEDIA_ASSET → MOMENT`);
window.SBB_ARCHITECTURE=Object.freeze({version:String(DOMAIN_MODEL?.version||'4.3.7'),domain:!!DOMAIN_MODEL,scoreDate:!!window.SBB_SCORE_DATE,eventIdentity:!!window.SBB_EVENT_IDENTITY,mediaClassifier:!!window.SBB_MEDIA_CLASSIFIER,playbackTransports:!!window.SBB_PLAYBACK_TRANSPORTS,providerHealth:!!window.SBB_PROVIDER_HEALTH,sportMediaPolicy:!!window.SBB_SPORT_MEDIA_POLICY,mediaManifest:!!window.SBB_MEDIA_MANIFEST,mediaResolver:!!window.SBB_MEDIA_RESOLVER,gameCenterPolicy:!!window.SBB_GAME_CENTER_POLICY,selectedEvent:!!window.SBB_SELECTED_EVENT,gameCenter:!!window.SBB_GAME_CENTER,mediaWork:!!window.SBB_MEDIA_WORK,editorialPackages:!!window.SBB_EDITORIAL_PACKAGES,siteSoundtrack:!!window.SBB_SOUNDTRACK,infoDrawer:!!window.SBB_INFO_DRAWER});

// v4.3.6 operator resource mode. SEARCH suspends every playback path so the cloud
// box can dedicate bandwidth/CPU to historical discovery. PLAYBACK leaves known
// catalog hydration intact but tells the backend workers to stop searching. MIX is
// the normal behavior where background search yields briefly to playback.
window.SBB_RESOURCE_MODE=window.SBB_RESOURCE_MODE||'balanced';
function sbbResourceMode(){
  const mode=String(window.SBB_RESOURCE_MODE||'balanced').toLowerCase();
  return ['search','balanced','playback'].includes(mode)?mode:'balanced';
}
function sbbPauseAllPlayback(){
  try{window.SBB_PLAYBACK_SESSION?.clearVideoAudible?.();}catch(_){}
  try{players?.A?.mute?.();players?.A?.pauseVideo?.();}catch(_){}
  try{players?.B?.mute?.();players?.B?.pauseVideo?.();}catch(_){}
  try{const a=document.getElementById('nativeA');if(a){a.muted=true;a.pause();}const b=document.getElementById('nativeB');if(b){b.muted=true;b.pause();}}catch(_){}
  try{window.SBB_SOUNDTRACK?.pauseForSearch?.();}catch(_){}
}
function applySbbResourceMode(mode,{notify=false}={}){
  mode=['search','balanced','playback'].includes(String(mode))?String(mode):'balanced';
  const changed=window.SBB_RESOURCE_MODE!==mode; window.SBB_RESOURCE_MODE=mode;
  document.body?.classList.toggle('sbb-search-priority',mode==='search');
  document.body?.classList.toggle('sbb-playback-priority',mode==='playback');
  const lock=document.getElementById('searchPriorityPlaybackLock');if(lock)lock.classList.toggle('hidden',mode!=='search');
  if(mode==='search')sbbPauseAllPlayback();
  else try{window.SBB_SOUNDTRACK?.resumeFromSearch?.();}catch(_){}
  if(notify&&changed&&typeof setFeedNote==='function')setFeedNote(mode==='search'?'Search Priority active • playback suspended':(mode==='playback'?'Playback Priority active • historical search paused':'Mixed mode active • search yields to playback'));
}
function sbbPlaybackAllowed({notify=true}={}){
  if(sbbResourceMode()!=='search')return true;
  sbbPauseAllPlayback();
  applySbbResourceMode('search');
  if(notify&&typeof setFeedNote==='function')setFeedNote('Playback suspended while Search Priority is active');
  return false;
}
window.addEventListener('sbb:workmode',ev=>applySbbResourceMode(ev?.detail?.mode||'balanced',{notify:true}));
Promise.resolve(window.__SBB_BOOT_STATUS_PROMISE__).then(data=>applySbbResourceMode(data?.workMode?.mode||data?.background?.workMode||'balanced')).catch(()=>{});
const FORCE_BLUE_TEST = new URLSearchParams(window.location.search).get('forceBlue') === '1';
function isFullRecapCandidate(item){
  return window.SBB_MEDIA_CLASSIFIER?.recapCandidate?.(item) ?? !!(item?.overview || item?.programType === 'recap' || /full game highlights|game recap|game highlights|condensed game/i.test(`${item?.title||''} ${item?.subtitle||''}`));
}
function asForcedBlueClip(item){
  if(!FORCE_BLUE_TEST) return item;
  return {...item, overview:false, programType:'reel', forceBlueTest:true};
}
// v4.3.6: production boot starts empty. The six-video NBA demo seed used during
// early player development was still able to become the first active program before
// live sports data arrived. Only verified live/catalog programming may populate it.
let PROGRAM = [];

// v1.9.3: MLB, NFL, NBA and NHL share one programming model plus an always-on key-information lane.
const LEAGUES = Object.freeze(Object.fromEntries(
  Object.values(DOMAIN_MODEL?.COMPETITIONS||{}).map(c=>[c.id,{id:c.id,sport:c.sportId,label:c.id,competition:c.name,enabled:!!c.enabled}])
));
const ENABLED_LIVE_LEAGUES = (DOMAIN_MODEL?.enabledCompetitions?.()||[]).map(x=>x.id).filter(x=>x!=='SPORTS');
const LIVE_CANDIDATES_BY_LEAGUE = new Map();
const VERIFIED_MEDIA_BY_MATCH=new Map();
const VERIFIED_PLAYABLES_BY_MATCH=new Map();
const EXTERNAL_MEDIA_BY_MATCH=new Map();
const EXTERNAL_CANDIDATES_BY_LEAGUE=new Map();
// Runtime playback truth is stricter than discovery truth. A source can pass API
// metadata checks yet still fail in this browser because of owner/embed/region
// policy. Once that exact asset fails, stop advertising it as playable for the
// rest of the page session and recompute the ribbon from the remaining sources.
const RUNTIME_UNPLAYABLE_MEDIA=new Set();
const LIVE_MATCHES_BY_LEAGUE = new Map();
const INDEX_CANDIDATES_BY_LEAGUE = new Map();

// v1.9.1 — each live feed has an explicit health state. A successful request
// returning zero games is EMPTY, never ERROR. This makes offseason/off-day
// behavior distinguishable from a broken provider and lets us report how many
// Highlightly calls were deliberately skipped.
const SPORT_FEEDS = Object.fromEntries(ENABLED_LIVE_LEAGUES.map(league=>[league,{
  league,status:'checking',games:0,eligible:0,live:0,final:0,scheduled:0,highlights:0,
  calls:0,skippedHighlightCalls:0,error:'',lastChecked:0,nextRefreshMs:0
}]));
let MULTISPORT_CALLS = {made:0, skipped:0, refreshStarted:0};
let SPORTS_EVENT_CANDIDATES=[];
let TOP_PLAYS_CANDIDATES=[];
let lastTopPlaysRefresh=0;
const TOP_PLAYS_REFRESH_MS=60*60*1000;
let RAPID_MLB_CANDIDATES=[];
const RAPID_MLB_BY_DATE=new Map();
const RAPID_MLB_REFRESH_AT=new Map();
let lastKeyInfoRefresh=0;
const KEY_INFO_REFRESH_MS=5*60*1000;
let keyInfoStartupRetryTimer=null;
let keyInfoStartupRetries=0;
const KEY_INFO_STARTUP_RETRY_MAX=10;
let ALL_KEY_INFO_EVENTS=[];
function feedStateLabel(st){
  if(st.status==='error') return 'ERROR';
  if(st.live>0) return `${st.live} LIVE`;
  if(st.games===0) return 'NO GAMES';
  if(st.final>0) return `${st.final} FINAL`;
  return `${st.games} SCHEDULED`;
}
function updateSportFeedState(league,patch={}){
  const key=String(league||'').toUpperCase();
  if(!SPORT_FEEDS[key]) return;
  Object.assign(SPORT_FEEDS[key],patch,{lastChecked:Date.now()});
  renderSportFeedDiagnostics();
}
function renderSportFeedDiagnostics(){
  if(typeof scoreBrowseDate!=='undefined' && scoreBrowseDate<localDateISO(0) && typeof renderHistoricalDateDiagnostics==='function'){
    renderHistoricalDateDiagnostics(scoreBrowseDate); return;
  }
  let healthy=0, errors=0, totalGames=0, liveGames=0;
  for(const league of ENABLED_LIVE_LEAGUES){
    const st=SPORT_FEEDS[league]; const el=$(`feed${league}`);
    if(st.status!=='error' && st.status!=='checking') healthy++;
    if(st.status==='error') errors++;
    totalGames+=Number(st.games||0); liveGames+=Number(st.live||0);
    if(el){
      el.className=`sport-feed-chip ${st.status||'checking'}`;
      const label=el.querySelector('span'); const detail=el.querySelector('small');
      if(label) label.textContent=feedStateLabel(st);
      if(detail){
        if(st.status==='error') detail.textContent=String(st.error||'Provider request failed').slice(0,70);
        else detail.textContent=`${st.games||0} games • ${st.highlights||0} media`;
      }
    }
  }
  const summary=$('sportFeedSummary');
  const feedTotal=ENABLED_LIVE_LEAGUES.length;
  if(summary) summary.textContent=errors?`${healthy}/${feedTotal} feeds OK • ${errors} error${errors===1?'':'s'}`:`${feedTotal}/${feedTotal} feeds OK • ${totalGames} games${liveGames?` • ${liveGames} live`:''}`;
  const calls=$('sportCallSummary');
  if(calls) calls.textContent=`${MULTISPORT_CALLS.made} calls • ${MULTISPORT_CALLS.skipped} skipped`;
  if(healthy+errors===ENABLED_LIVE_LEAGUES.length) setDataStatus(errors?`${healthy}/${ENABLED_LIVE_LEAGUES.length} FEEDS OK`:`${ENABLED_LIVE_LEAGUES.length}/${ENABLED_LIVE_LEAGUES.length} FEEDS OK`, errors===0);
}
let startupLiveAutoplayDone = false;
let startupAutoplayAttempted = false;
let sportsBigBoardStarted = false;
let mediaInteractionUnlocked = false;
const startupMutedSlots = {A:false,B:false};

let liveFeedLoaded = false;
let liveDataInitStarted = false;
let apiConfigured = false;
let highlightlyRateLimited = false;
const launchRequested = {A:false,B:false};
let apiQuota = { remaining:null, limit:null };
let lastLiveRefresh = 0;
let GENERAL_PROGRAM = null;
const contextTimer={A:null,B:null};
let HIGHLIGHTS_BY_MATCH = new Map();
let ALL_GAME_CANDIDATES = new Map();
let RECAP_CANDIDATE_REGISTRY = new Map(); // v2.3.0 cross-source canonical recap packages
let LAST_YESTERDAY_MATCHES = [];
let LAST_COMPLETED_MATCHES = [];

// v1.9.1 — remember which games have already been covered during this browser
// session. A completed green recap or the final clip of a blue reel marks the
// canonical game identity watched. Background refreshes and queue rebuilds may
// discover more candidate videos, but watched games are not automatically aired
// again until a brand-new browser session begins.
const PLAYED_GAMES_STORAGE_KEY = 'sports-big-board.playedGameIds.v1';
function loadPlayedGameIds(){
  try{ return new Set(JSON.parse(sessionStorage.getItem(PLAYED_GAMES_STORAGE_KEY)||'[]')); }
  catch(e){ return new Set(); }
}
let playedGameIds = loadPlayedGameIds();
let manualRecapAlternate=null;
function persistPlayedGameIds(){
  try{ sessionStorage.setItem(PLAYED_GAMES_STORAGE_KEY, JSON.stringify([...playedGameIds])); }catch(e){}
}
let coveragePollTimer = null;
let coverageState = {status:'STARTING', searched:0,total:0,found:0,playable:0,playableGames:0,recapGames:0,reelGames:0,missingGames:0,noSource:0,sourceErrors:0,sourceErrorGames:0,degradedPlayableGames:0,playbackFailures:0,revision:0,youtubeConfigured:false,youtubeSearched:0,youtubeFound:0,youtubeErrors:0,youtubeDone:false};
let coverageAppliedRevision = -1;
let coverageContext = null;
let coverageApplyBusy = false;

let players = { A:null, B:null };
let activeSlot = 'A';
let currentIndex = 0;
let standbyIndex = 0;
let playerReady = { A:false, B:false };
// A score-card tune can arrive while the YouTube iframe API is still finishing
// initialization. Track that one controller-owned wait explicitly so onReady does
// not create a second slot claim and invalidate the exact media the click selected.
let youtubeStartAwaitingReady = { A:false, B:false };
let videoReady = { A:false, B:false };
let swapCount = 0;
let bumperMode = 'always';
let swapRequestedAt = 0;
let initialized = false;
let warming = { A:false, B:false };
let warmTimer = { A:null, B:null };
let bumperShownAt = 0;
let bumperMinMs = 0;
let activePlaybackState = null;
let playbackSyncTimer = null;
let slotMedia = { A:'youtube', B:'youtube' };
// v2.5.30 playback ownership. Every assignment gets an epoch so asynchronous
// callbacks from an older video cannot mutate a slot after it has been reused.
let slotEpoch = { A:0, B:0 };
let slotAssignment = { A:null, B:null };
let playbackSelectionToken = 0;
// A direct score-card tune temporarily owns PROGRAM while GENERAL_PROGRAM keeps
// refreshing independently in the background.
let userPlaybackSession = null;
// v2.5.30 prepared-player cache. Score-ribbon prewarming owns its own native
// <video> elements, never an A/B slot. A prepared element can only enter playback
// through an exact media-key handoff performed by PlaybackController.
const nativeSlotNodes = { A:null, B:null };
const scoreMediaPrimeState = {
  queued:new Set(), queue:[], active:0, entries:new Map(),
  desiredHot:new Set(), desiredWarm:new Set(), candidates:[], recentKeys:[]
};
const SCORE_MEDIA_PRIME_TTL_MS = 20*60*1000;
const SCORE_MEDIA_PRIME_MAX_ACTIVE = 3;
const SCORE_MEDIA_HYSTERESIS_MS = 12000;
let scoreMediaPrimeGeneration = 0;
let scoreMediaWarmReconcileTimer=null;
let scoreServerWarmTimer=null;
let scoreServerWarmSignature='';
function scorePreparedLimit(){
  const conn=navigator.connection||navigator.mozConnection||navigator.webkitConnection;
  if(conn?.saveData) return 4;
  const type=String(conn?.effectiveType||'').toLowerCase();
  if(type==='2g'||type==='slow-2g') return 4;
  const mem=Number(navigator.deviceMemory||6);
  if(mem>=8) return 8;
  if(mem>=6) return 8;
  if(mem<=3) return 5;
  return 7;
}
function scoreServerWarmLimit(){ return Math.min(20,scorePreparedLimit()+10); }
let nativeBound = false;
let manualPauseRequested = false;
let visibilityResumeWanted = false;
let transitionInFlight = false;
let transitionRecoveryAttempts = 0;
const FAVORITE_TEAMS_STORAGE_KEY = 'sports-big-board.favoriteTeams.v1';
const DIRECTOR_MODE_TTL=60*60*1000;
const DIRECTOR_MODE_STORAGE_KEY='sbb-director-ranks-v1';
let directorApplyPending=false;
function loadDirectorCache(){
  try{
    const saved=JSON.parse(localStorage.getItem(DIRECTOR_MODE_STORAGE_KEY)||'null');
    if(saved && Date.now()-Number(saved.at||0)<DIRECTOR_MODE_TTL){
      for(const x of (saved.queue||[])) AI_PROGRAM_RANKINGS.set(String(x.id),x);
      for(const x of (saved.scores||[])) AI_SCORE_RANKINGS.set(String(x.id),x);
      aiRankLastAt=Number(saved.at||Date.now());
      return true;
    }
  }catch(_){}
  return false;
}
function saveDirectorCache(queueRanks,scoreRanks){
  try{
    localStorage.setItem(DIRECTOR_MODE_STORAGE_KEY,JSON.stringify({
      at:Date.now(),queue:queueRanks||[],scores:scoreRanks||[]
    }));
  }catch(_){}
}
const AI_PROGRAM_RANKINGS = new Map();
const AI_TOP_PLAY_RANKINGS = new Map();
const AI_SCORE_RANKINGS = new Map();
let scoreRibbonLeagueFilter='ALL';
const SCORE_DATE_STORE=window.SBB_SCORE_DATE||null;
let scoreBrowseDate=SCORE_DATE_STORE?.snapshot?.().browseDate||localDateISO(0);
let scorePlaybackDate=SCORE_DATE_STORE?.snapshot?.().playbackDate||localDateISO(0);
const ROUNDUPS_BY_DATE=new Map();
const CATALOG_EVENT_PLANS=new Map();
const HISTORICAL_SCORE_LOAD_ERRORS=new Map();
const ROUNDUP_AUTOPLAYED=new Set();
let scoreRibbonInteractionUntil=0;
let scoreDateLoadGeneration=0;
let playbackDateContext=null;
// The ribbon follows a newly-selected/playing game once, then gets out of the
// user's way. Manual date browsing never interrupts the active playback session.
let scoreRibbonFocusKey='';
let scoreRibbonFocusStableKey='';
let scoreRibbonFocusEvent=null;
let scoreRibbonFocusGeneration=0;
function scoreRibbonTeamToken(value){
  if(!value) return '';
  if(typeof value==='string') return normalizedTeamKey(value);
  return normalizedTeamKey(value.abbreviation||value.abbr||value.displayName||value.name||value.shortName||'');
}
function scoreEventDate(item){
  const raw=String(item?.scheduledGameDate||item?.__sbbDate||item?.gameDate||item?.date||item?.startDate||item?.scheduledAt||'');
  if(/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.slice(0,10);
  try{ const d=new Date(raw); return Number.isFinite(d.getTime())?dateInTimeZone(d,Intl.DateTimeFormat().resolvedOptions().timeZone||'Etc/UTC'):''; }catch(_){ return ''; }
}
function addCalendarDays(date,delta){
  const [y,m,d]=String(date||localDateISO(0)).split('-').map(Number);
  const x=new Date(y||1970,(m||1)-1,d||1,12,0,0,0); x.setDate(x.getDate()+Number(delta||0));
  return `${x.getFullYear()}-${String(x.getMonth()+1).padStart(2,'0')}-${String(x.getDate()).padStart(2,'0')}`;
}
function scoreMatchesForDate(date){
  const wanted=String(date||scoreBrowseDate).slice(0,10);
  const resident=SCORE_DATE_STORE?.allMatches?.(wanted)||[];
  if(resident.length || SCORE_DATE_STORE?.hasMatchesSnapshot?.(wanted)) return resident;
  const today=localDateISO(0),yesterday=localDateISO(-1),rows=[];
  if(wanted===today||wanted===yesterday){
    for(const state of LIVE_MATCHES_BY_LEAGUE.values()) rows.push(...(wanted===today?(state?.today||[]):(state?.yesterday||[])));
  }
  return rows;
}
function scoreMediaForDate(date){ return SCORE_DATE_STORE?.allMedia?.(date)||[]; }
function roundupLeague(item){return String(item?.competitionId||item?.__sbbLeague||item?.league||'SPORTS').toUpperCase();}
function roundupDate(item){
  const raw=String(item?.collectionPeriodKey||item?.gameDate||item?.__sbbDate||item?.date||item?.publishedAt||'');
  return /^\d{4}-\d{2}-\d{2}/.test(raw)?raw.slice(0,10):'';
}
function roundupMediaForScoreDate(date,league=scoreRibbonLeagueFilter){
  date=String(date||scoreBrowseDate).slice(0,10);league=String(league||'ALL').toUpperCase();
  const raw=[...(ROUNDUPS_BY_DATE.get(date)||[]),...scoreMediaForDate(date)];
  for(const pool of [GENERAL_PROGRAM,PROGRAM]) for(const item of (Array.isArray(pool)?pool:[])){
    const d=roundupDate(item); if(d===date || (!d&&date===localDateISO(0)&&typeof isTopPlaysItem==='function'&&isTopPlaysItem(item))) raw.push(item);
  }
  const out=[];const seen=new Set();
  for(const source of raw){
    if(!source)continue;
    let item=window.SBB_MEDIA_SCOPE?.annotate?.(source,{date})||{...source};
    if((typeof isTopPlaysItem==='function'&&isTopPlaysItem(item)) && !window.SBB_MEDIA_SCOPE?.isCollection?.(item)){
      item={...item,mediaScope:'DAY_LEAGUE',collectionTier:'silver',displayTier:'silver',collectionKind:'TOP_PLAYS',collectionPeriodKey:date};
    }
    if(!window.SBB_MEDIA_SCOPE?.isCollection?.(item))continue;
    const d=roundupDate(item);
    if(item.mediaScope==='WEEK_LEAGUE'){
      const assetDate=String(item.gameDate||item.__sbbDate||item.date||'').slice(0,10);
      if(assetDate && assetDate!==date)continue;
    }else if(d && d!==date)continue;
    const lg=roundupLeague(item); if(league!=='ALL'&&lg!==league)continue;
    if(!item.verifiedPlayable || !(item.youtubeId||item.mediaUrl))continue;
    const key=String(item.youtubeId||item.mediaUrl||item.id||'');if(!key||seen.has(key))continue;seen.add(key);out.push(item);
  }
  const rank=item=>{
    const kind=String(item.collectionKind||'').toUpperCase(),scope=String(item.mediaScope||'');
    const base=scope==='DAY_LEAGUE'&&kind==='DAILY_RECAP'?500:scope==='DAY_LEAGUE'&&kind==='TOP_PLAYS'?400:scope==='WEEK_LEAGUE'?300:200;
    return base+Math.min(99,Math.round(Number(item.importance||0)))+Math.min(60,Math.round(Number(item.durationSeconds||item.duration||0)/60));
  };
  return out.sort((a,b)=>rank(b)-rank(a));
}
async function loadRoundupsForDate(date){
  date=String(date||scoreBrowseDate).slice(0,10);if(!/^\d{4}-\d{2}-\d{2}$/.test(date))return [];
  try{
    const payload=await apiJson(`/api/history/roundups?date=${encodeURIComponent(date)}&league=ALL`);
    const rows=Array.isArray(payload?.media)?payload.media:[];ROUNDUPS_BY_DATE.set(date,rows);return rows;
  }catch(_){return ROUNDUPS_BY_DATE.get(date)||[];}
}
function scoreDateAvailable(date){
  const allowed=m=>scoreRibbonLeagueFilter==='ALL'||String(m.__sbbLeague||m.league||'').toUpperCase()===scoreRibbonLeagueFilter;
  return scoreMatchesForDate(date).some(allowed);
}
// The selected ribbon game must survive media-package swaps and score refreshes.
// Provider/event ids can change as richer score authority arrives; date + matchup
// remains stable for the actual sporting event.
function scoreRibbonStableGameKey(item){
  if(!item) return '';
  const lg=String(item.__sbbLeague||item.competitionId||item.league||'').toUpperCase();
  const scoreKey=String(item.scoreGameKey||'').trim();
  if(lg&&scoreKey) return `${lg}:${scoreKey}`;
  const dateKey=String(item.dateGameKey||'').trim();
  if(lg&&dateKey) return `${lg}:${dateKey}`;
  const date=scoreEventDate(item);
  const away=scoreRibbonTeamToken(item.awayTeam||item.away||item.visitorTeam||item.visitor||'');
  const home=scoreRibbonTeamToken(item.homeTeam||item.home||'');
  if(lg&&date&&away&&home) return `${lg}:${date}::${away}__${home}`;
  const id=String(item.scoreEventId||item.espnEventId||item.gameCenterEventId||item.matchId||item.gamePk||item.eventId||item.id||'');
  return lg&&id?`${lg}:id:${id}`:'';
}
function scoreRibbonFocusMatch(eventLike){
  if(!eventLike) return null;
  const targetStable=scoreRibbonStableGameKey(eventLike);
  const targetDate=scoreEventDate(eventLike);
  const league=String(eventLike.__sbbLeague||eventLike.competitionId||eventLike.league||'').toUpperCase();
  const dateCandidates=[targetDate,scoreBrowseDate,localDateISO(0),localDateISO(-1)].filter((x,i,a)=>x&&a.indexOf(x)===i);
  for(const date of dateCandidates){
    const rows=scoreMatchesForDate(date).filter(m=>!league||String(m.__sbbLeague||m.competitionId||m.league||'').toUpperCase()===league);
    for(const match of rows){
      if(targetStable && scoreRibbonStableGameKey(match)===targetStable) return {match,date};
      if(sameGameProgramItem(match,eventLike)) return {match,date};
    }
  }
  return null;
}
function scoreRibbonFocusIdentity(eventLike){
  if(!eventLike) return '';
  try{ return programGameIdentity(eventLike)||candidateGroupKey(eventLike)||canonicalRecapMatchKey(eventLike)||''; }catch(_){ return ''; }
}
function applyScoreRibbonFocusVisuals({scroll=false}={}){
  const host=document.getElementById('scoreCells');
  if(!host) return false;
  let target=null;
  host.querySelectorAll('.score-card').forEach(card=>{
    const cardKey=String(card.dataset.sbbGameKey||'');
    const active=!!(cardKey&&scoreRibbonFocusStableKey&&cardKey===scoreRibbonFocusStableKey);
    card.classList.toggle('now-playing-game',active);
    if(active){ card.setAttribute('aria-current','true'); target=card; }
    else card.removeAttribute('aria-current');
  });
  if(target&&scroll){
    const left=Math.max(0,target.offsetLeft-(host.clientWidth-target.offsetWidth)/2);
    try{ host.scrollTo({left,behavior:'smooth'}); }catch(_){ host.scrollLeft=left; }
  }
  return !!target;
}
function focusScoreRibbonForGame(eventLike,{force=false}={}){
  const resolved=scoreRibbonFocusMatch(eventLike);
  const focus=resolved?.match||eventLike||null;
  const stableKey=scoreRibbonStableGameKey(focus);
  const key=scoreRibbonFocusIdentity(focus)||stableKey;
  if(!key||!stableKey) return false;
  const changed=force||stableKey!==scoreRibbonFocusStableKey;
  if(changed||!scoreRibbonFocusEvent||force) scoreRibbonFocusEvent=focus;
  scoreRibbonFocusKey=key;
  scoreRibbonFocusStableKey=stableKey;
  const gen=++scoreRibbonFocusGeneration;
  // Playback may recenter the ribbon when the actual game changes. If the viewer
  // manually browses away while the SAME game keeps playing, later metadata renders
  // do not snap them back because changed=false.
  if(changed&&resolved?.date&&resolved.date!==scoreBrowseDate){
    setScoreBrowseDate(resolved.date,{animate:true,hold:10000,load:true});
    requestAnimationFrame(()=>{ if(gen===scoreRibbonFocusGeneration) applyScoreRibbonFocusVisuals({scroll:true}); });
    return true;
  }
  requestAnimationFrame(()=>{ if(gen===scoreRibbonFocusGeneration) applyScoreRibbonFocusVisuals({scroll:changed}); });
  return true;
}
function formatScoreDateLabel(date){
  const today=localDateISO(0), yesterday=localDateISO(-1);
  try{
    const [y,m,d]=String(date).split('-').map(Number); const dt=new Date(y,m-1,d,12,0,0,0);
    const md=dt.toLocaleDateString([], {month:'short',day:'numeric'}).toUpperCase();
    if(date===today) return `TODAY • ${md}`;
    if(date===yesterday) return `YESTERDAY • ${md}`;
    const wd=dt.toLocaleDateString([], {weekday:'short'}).toUpperCase();
    return `${wd} • ${md}, ${y}`;
  }catch(_){ return String(date||'DATE').toUpperCase(); }
}
function topDateControlLabel(date){
  const today=localDateISO(0);
  if(date===today) return 'SELECT DATE';
  try{
    const [y,m,d]=String(date).split('-').map(Number);
    const dt=new Date(y,m-1,d,12,0,0,0);
    return dt.toLocaleDateString([], {month:'short',day:'numeric'}).toUpperCase();
  }catch(_){ return 'SELECT DATE'; }
}
function openScoreDatePicker(){
  const picker=document.getElementById('scoreDatePicker');
  try{picker?.showPicker?.();}catch(_){picker?.click?.();}
}
function updateReturnTodayButton(){
  const today=localDateISO(0);
  const btn=document.getElementById('returnTodayBtn');
  const show=scoreBrowseDate!==today || scorePlaybackDate!==today || playbackDateContext?.date&&playbackDateContext.date!==today;
  if(btn){
    btn.classList.toggle('hidden',!show);
    btn.setAttribute('aria-hidden',show?'false':'true');
  }
  const dateBtn=document.getElementById('topDateSelectBtn');
  const dateLabel=document.getElementById('topDateSelectLabel');
  if(dateBtn){
    dateBtn.dataset.historical=scoreBrowseDate===today?'false':'true';
    dateBtn.title=scoreBrowseDate===today?'Select a date':`Change date • ${formatScoreDateLabel(scoreBrowseDate)}`;
    dateBtn.setAttribute('aria-label',scoreBrowseDate===today?'Select a score date':`Change score date from ${formatScoreDateLabel(scoreBrowseDate)}`);
  }
  if(dateLabel) dateLabel.textContent=topDateControlLabel(scoreBrowseDate);
}
function updateScoreDayPager(){
  const today=localDateISO(0);
  const label=formatScoreDateLabel(scoreBrowseDate);
  const indicator=document.getElementById('scoreDayIndicator');
  if(indicator){
    indicator.textContent=label;
    indicator.dataset.scoreDay=scoreBrowseDate===today?'today':'historical';
    indicator.title=`Choose score date • ${scoreBrowseDate}`;
  }
  const picker=document.getElementById('scoreDatePicker');
  if(picker){ picker.max=today; picker.value=scoreBrowseDate; }
  document.querySelectorAll('[data-score-date-step]').forEach(btn=>{
    const delta=Number(btn.dataset.scoreDateStep||0);
    const blocked=delta>0&&scoreBrowseDate>=today;
    btn.disabled=blocked;
    btn.classList.toggle('unavailable',blocked);
    btn.setAttribute('aria-label',`${delta<0?'Previous':'Next'} score date. Currently ${label.toLowerCase()}.`);
  });
  updateReturnTodayButton();
}
async function setScoreBrowseDate(value,{animate=true,hold=9000,load=true}={}){
  const today=localDateISO(0);
  let date=String(value||today).slice(0,10); if(!/^\d{4}-\d{2}-\d{2}$/.test(date)) date=today; if(date>today) date=today;
  scoreBrowseDate=date;
  SCORE_DATE_STORE?.setBrowseDate?.(date,{notifyListeners:false});
  scoreRibbonInteractionUntil=Date.now()+hold;
  renderScoresFromMatchesCombined(animate);
  updateScoreDayPager();
  renderActiveSportKeyInformation();
  if(date<today){
    renderHistoricalDateDiagnostics(date,historicalDiscoveryState(date));
    // v4.3.6 catalog-first browsing is read-only. Background recovery owns gap
    // discovery; an explicit FIND RECAP click can still request one exact event.
    refreshHistoricalDiscoverySnapshot(date,{hydrate:false}).catch(()=>{});
  }else{
    stopHistoricalDiscoveryPolling();
    setHistoricalCoverageLabels(false);
    renderSportFeedDiagnostics();
    renderCoverage(coverageState);
    // Returning to TODAY should immediately revalidate the current-information
    // lane. The endpoint remains cache-first, so this does not block navigation.
    // Paint cached current Key Info immediately before the refresh=1 request.
    // Otherwise the historical empty message can remain visible for the full
    // duration of a slow editorial/network refresh.
    lastKeyInfoRefresh=0;
    refreshKeyInformation(false,false).catch(()=>{});
    setTimeout(()=>refreshKeyInformation(false,true).catch(()=>{}),250);
  }
  if(load) await ensureScoreDateLoaded(date);
  if(load) await loadRoundupsForDate(date);
  renderScoresFromMatchesCombined(false);
  if(date<today) renderHistoricalDateDiagnostics(date,historicalDiscoveryState(date));
  return true;
}
function stepScoreRibbonDate(delta){ return setScoreBrowseDate(addCalendarDays(scoreBrowseDate,delta),{animate:true,hold:10000,load:true}); }
function scheduleScoreRibbonDayCarousel(){ /* v4.3.6: deliberate date browsing never auto-rotates. */ }
function wireScoreDayPager(){
  document.querySelectorAll('.score-day-pager').forEach(pager=>{
    if(pager.dataset.wired) return; pager.dataset.wired='1';
    pager.addEventListener('pointerdown',e=>{if(e.target.closest('[data-score-date-step]'))e.stopPropagation();},{capture:true});
    pager.addEventListener('click',e=>{ const btn=e.target.closest('[data-score-date-step]'); if(!btn)return;e.preventDefault();e.stopPropagation();if(!btn.disabled) stepScoreRibbonDate(Number(btn.dataset.scoreDateStep||0)); },{capture:true});
  });
  const indicator=document.getElementById('scoreDayIndicator'),picker=document.getElementById('scoreDatePicker');
  if(indicator&&!indicator.dataset.wired){
    indicator.dataset.wired='1'; indicator.addEventListener('click',openScoreDatePicker);
  }
  const topDateBtn=document.getElementById('topDateSelectBtn');
  if(topDateBtn&&!topDateBtn.dataset.wired){
    topDateBtn.dataset.wired='1'; topDateBtn.addEventListener('click',openScoreDatePicker);
  }
  if(picker&&!picker.dataset.wired){
    picker.dataset.wired='1'; picker.max=localDateISO(0); picker.addEventListener('change',()=>{if(picker.value)setScoreBrowseDate(picker.value,{animate:true,hold:12000,load:true});});
  }
  const ret=document.getElementById('returnTodayBtn');
  if(ret&&!ret.dataset.wired){ret.dataset.wired='1';ret.addEventListener('click',()=>returnToToday());}
  wireScoreRibbonDesktopBrowse();
  updateScoreDayPager();
}
function wireScoreRibbonDesktopBrowse(){
  const host=document.getElementById('scoreCells');
  if(!host||host.dataset.desktopBrowseWired) return;
  host.dataset.desktopBrowseWired='1';
  let drag=null, suppressClickUntil=0;
  const interact=()=>{scoreRibbonInteractionUntil=Date.now()+10000;};
  host.addEventListener('wheel',e=>{
    const max=Math.max(0,host.scrollWidth-host.clientWidth);
    if(max<=0) return;
    const delta=Math.abs(e.deltaX)>Math.abs(e.deltaY)?e.deltaX:e.deltaY;
    if(!delta) return;
    const next=Math.max(0,Math.min(max,host.scrollLeft+delta));
    if(Math.abs(next-host.scrollLeft)<.5) return; // let the page keep scrolling at either ribbon edge
    host.scrollLeft=next; interact(); e.preventDefault();
  },{passive:false});
  host.addEventListener('pointerdown',e=>{
    if(e.pointerType!=='mouse'||e.button!==0) return;
    drag={id:e.pointerId,startX:e.clientX,startScroll:host.scrollLeft,moved:false};
  });
  host.addEventListener('pointermove',e=>{
    if(!drag||drag.id!==e.pointerId||(e.buttons&1)!==1) return;
    const dx=e.clientX-drag.startX;
    if(!drag.moved&&Math.abs(dx)<6) return;
    if(!drag.moved){
      drag.moved=true; host.classList.add('is-dragging');
      try{host.setPointerCapture(e.pointerId);}catch(_){ }
    }
    host.scrollLeft=drag.startScroll-dx; interact(); e.preventDefault();
  });
  const finish=e=>{
    if(!drag||drag.id!==e.pointerId) return;
    if(drag.moved) suppressClickUntil=Date.now()+250;
    host.classList.remove('is-dragging');
    try{host.releasePointerCapture(e.pointerId);}catch(_){ }
    drag=null;
  };
  host.addEventListener('pointerup',finish);
  host.addEventListener('pointercancel',finish);
  host.addEventListener('click',e=>{
    if(Date.now()<suppressClickUntil&&e.target.closest('.score-card')){e.preventDefault();e.stopImmediatePropagation();}
  },true);
  host.addEventListener('dragstart',e=>e.preventDefault());
}
let aiRankInFlight=false;
let aiRankSignature='';
let aiRankLastAt=0;
function favoriteTeams(){
  try{ const v=JSON.parse(localStorage.getItem(FAVORITE_TEAMS_STORAGE_KEY)||'[]'); return Array.isArray(v)?v.map(x=>String(x).trim()).filter(Boolean):[]; }catch(e){ return []; }
}
function setFavoriteTeams(value){
  const rows=Array.isArray(value)?value:String(value||'').split(',');
  const clean=[...new Set(rows.map(x=>String(x).trim()).filter(Boolean))];
  try{ localStorage.setItem(FAVORITE_TEAMS_STORAGE_KEY,JSON.stringify(clean)); }catch(e){}
  aiRankSignature='';
  if(GENERAL_PROGRAM) mergeLiveProgram([],false);
  return clean;
}
window.SBB=window.SBB||{};
window.SBB.setFavoriteTeams=setFavoriteTeams;
window.SBB.getFavoriteTeams=favoriteTeams;

const $ = id => document.getElementById(id);
let launchGameCenterGeneration=0;
function launchScoreMatchForItem(item){
  if(!item || isContextItem(item) || isTopPlaysItem(item) || item.eventType) return null;
  const league=String(item.competitionId||item.__sbbLeague||item.league||'').toUpperCase();
  const itemDate=scoreEventDate(item);
  let rows=itemDate?scoreMatchesForDate(itemDate):[];
  if(!rows.length){
    const states=league&&LIVE_MATCHES_BY_LEAGUE.has(league)?[LIVE_MATCHES_BY_LEAGUE.get(league)]:[...LIVE_MATCHES_BY_LEAGUE.values()];
    rows=states.flatMap(state=>[...(state?.today||[]),...(state?.yesterday||[])]);
  }
  if(league) rows=rows.filter(m=>String(m.__sbbLeague||m.competitionId||m.league||'').toUpperCase()===league);
  const ids=[item.gameCenterEventId,item.scoreEventId,item.espnEventId,item.matchId,item.gamePk,item.eventId].map(x=>String(x||'')).filter(Boolean);
  const direct=rows.find(m=>{
    const mids=[m.gameCenterEventId,m.scoreEventId,m.espnEventId,m.matchId,m.gamePk,m.eventId,m.id].map(x=>String(x||'')).filter(Boolean);
    return ids.some(id=>mids.includes(id));
  });
  if(direct) return direct;
  return rows.find(m=>sameGameProgramItem(m,item))||null;
}
function gameCenterSelectionFromScoreMatch(match){
  if(!match) return null;
  const competitionId=String(match.competitionId||match.__sbbLeague||match.league||'SPORTS').toUpperCase();
  const scoreEventId=String(match.scoreEventId??match.eventId??match.matchId??match.id??'');
  const scoreGamePk=competitionId==='MLB'?String(match.gamePk||''):'';
  const espnEventId=String(match.espnEventId||'');
  const gameCenterProviderHint=String(match.gameCenterProviderHint||match.scoreProvider||((competitionId==='MLB'&&scoreGamePk&&scoreEventId===scoreGamePk)?'mlb-stats':(espnEventId&&scoreEventId===espnEventId?'espn':'highlightly'))).toLowerCase();
  return {...match,competitionId,scoreEventId,eventId:scoreEventId||scoreGamePk||espnEventId,
    gamePk:scoreGamePk,gameCenterEventId:scoreEventId||scoreGamePk||espnEventId,gameCenterProviderHint};
}
function scheduleLaunchGameCenterPopulate(){
  const generation=++launchGameCenterGeneration;
  const delays=[120,900,2400,5200];
  delays.forEach((delay,attempt)=>setTimeout(()=>{
    if(generation!==launchGameCenterGeneration || !sportsBigBoardStarted) return;
    const item=clip(currentIndex);
    if(!item || isContextItem(item) || isTopPlaysItem(item) || item.eventType || window.SBB_MEDIA_SCOPE?.isCollection?.(item)) return;
    const match=launchScoreMatchForItem(item);
    const eventLike=match?gameCenterSelectionFromScoreMatch(match):item;
    const selected=syncSelectedEvent(eventLike,{reason:'launch game-center populate',source:'launch'});
    if(!selected) return;
    // The splash owns the clean pre-launch state. Once Play is pressed, the current
    // broadcast game should own Game Center as well. Re-run the local resolver after
    // scores have had time to finish warming so a sparse first pass gets enriched.
    window.SBB_INFO_DRAWER?.resetAutomaticSuppression?.();
    window.SBB_INFO_DRAWER?.open?.('game-center',{automatic:true});
    if(attempt>0) window.SBB_GAME_CENTER_VIEW?.load?.(selected,{force:true,background:true});
  },delay));
}
function confirmLaunchVisualPlayback(slot,timeoutMs=8000){
  const startedAt=performance.now();
  const check=()=>{
    if(!sportsBigBoardStarted || slot!==activeSlot) return;
    let playing=false;
    try{ playing=adapterForSlot(slot).isPlaying(); }catch(_){}
    if(playing){
      const remaining=Math.max(0,bumperMinMs-(performance.now()-bumperShownAt));
      setTimeout(()=>{ if(slot===activeSlot){ hideBumper(); swapRequestedAt=0; } },remaining);
      return;
    }
    // Observation only: never start, skip or recover media from this launch helper.
    // PlaybackController remains the single owner of player state.
    if(performance.now()-startedAt<timeoutMs) setTimeout(check,50);
  };
  check();
}
// Legacy v4.2.2 source-contract compatibility marker only. Launch ownership is now handled by PlaybackController.
// reconcileActiveSlot({autoplay:true,userInitiated:true,reason:'launch screen play'})
function startSportsBigBoardExperience(){
  if(sportsBigBoardStarted) return;
  sportsBigBoardStarted=true;
  mediaInteractionUnlocked=true;
  manualPauseRequested=false;
  visibilityResumeWanted=false;
  document.body.classList.add('sbb-experience-started');
  try{ window.SBB_SOUNDTRACK?.startExperience?.(soundtrackPlaybackClipKey()); }catch(_){}
  const launch=$('launchScreen');
  if(launch){
    launch.classList.add('is-dismissed');
    launch.setAttribute('aria-hidden','true');
    setTimeout(()=>launch.remove(),420);
  }
  // A fresh launch begins on a clean broadcast surface. Once the viewer presses
  // Play, the current program is synchronized into Game Center by the launch cycle below.
  try{ window.SBB_INFO_DRAWER?.close?.({manual:false}); }catch(_){}
  try{ window.SBB_SELECTED_EVENT?.clear?.({reason:'launch screen reset',source:'launch'}); }catch(_){}
  if(PROGRAM.length){
    showBumper(currentIndex,420,'STARTING SPORTS BIG BOARD');
    // v4.3.7 launch bootstrap closure: every launch tune enters the canonical
    // PlaybackController immediately, even when a YouTube iframe exists but has
    // not fired onReady. The controller creates playback-session identity first;
    // startAssignedPlayback() then owns the bounded readiness wait and unattended
    // failover path. The old readiness-only branch could remain in `starting`
    // forever with no session, timeout, or watchdog if onReady never arrived.
    PlaybackController.tuneProgramIndex(currentIndex,{userInitiated:true,reason:'launch screen play'})
      .catch(()=>{}); // PlaybackController already records and recovers start failure.
    confirmLaunchVisualPlayback(activeSlot,8000);
    scheduleLaunchGameCenterPopulate();
  }
  try{ fetch('/api/client-log?event=USER_LAUNCH&v=4.3.7',{cache:'no-store'}).catch(()=>{}); }catch(_){}
}
function wireLaunchScreen(){
  const btn=$('launchPlayBtn');
  if(!btn||btn.dataset.wired) return;
  btn.dataset.wired='1';
  btn.addEventListener('click',startSportsBigBoardExperience);
}
window.SBB_START=Object.freeze({start:startSportsBigBoardExperience,get started(){return sportsBigBoardStarted;}});
let brandTapCount=0, brandTapTimer=null;
function setDiagnosticsVisible(visible){
  document.body.classList.toggle('diagnostics-off',!visible);
  document.body.classList.toggle('broadcast-mode',!visible);
  try{ localStorage.setItem('sbb-diagnostics-visible',visible?'1':'0'); }catch(_){}
  const brand=document.querySelector('.brand'); if(brand) brand.title=visible?'Diagnostics ON • click 5× to hide':'Broadcast view • click 5× to show diagnostics';
}

function syncStickyHeaderHeight(){
  const header=document.querySelector('.top-nav-header');
  if(!header) return;
  const height=Math.max(1,Math.ceil(header.getBoundingClientRect().height));
  document.documentElement.style.setProperty('--sbb-top-control-height',`${height}px`);
  document.body.classList.add('sbb-fixed-controls');
}
function wireStickyControlBar(){
  syncStickyHeaderHeight();
  addEventListener('resize',syncStickyHeaderHeight,{passive:true});
  addEventListener('orientationchange',()=>setTimeout(syncStickyHeaderHeight,120),{passive:true});
  if(window.visualViewport){
    visualViewport.addEventListener('resize',syncStickyHeaderHeight,{passive:true});
  }
}
function wireDiagnosticsToggle(){
  const brand=document.querySelector('.brand'); if(!brand||brand.dataset.diagWired) return; brand.dataset.diagWired='1'; brand.style.cursor='pointer';
  brand.addEventListener('click',()=>{ clearTimeout(brandTapTimer); brandTapCount++; brandTapTimer=setTimeout(()=>brandTapCount=0,1800); if(brandTapCount>=5){ brandTapCount=0; clearTimeout(brandTapTimer); setDiagnosticsVisible(document.body.classList.contains('diagnostics-off')); } });
  let initial=true;
  try{
    const saved=localStorage.getItem('sbb-diagnostics-visible');
    if(saved==='0') initial=false;
  }catch(_){}
  setDiagnosticsVisible(initial);
}
function wireFavoriteTeamsUi(){
  const btn=[...document.querySelectorAll('.left-rail .nav')].find(x=>/My Teams/i.test(x.textContent||''));
  if(!btn||btn.dataset.sbbWired) return; btn.dataset.sbbWired='1';
  btn.addEventListener('click',()=>{
    const current=favoriteTeams().join(', ');
    const value=prompt('Favorite teams — enter team names or abbreviations separated by commas. They get a programming boost below globally major events.',current);
    if(value===null) return;
    const saved=setFavoriteTeams(value);
    btn.title=saved.length?`Favorites: ${saved.join(', ')}`:'No favorite teams set';
  });
}
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>{wireFavoriteTeamsUi();wireDiagnosticsToggle();wireLaunchScreen();
  wireStickyControlBar();wireScoreFilters();},{once:true}); else setTimeout(()=>{wireFavoriteTeamsUi();wireDiagnosticsToggle();wireLaunchScreen();wireScoreFilters();},0);
const otherSlot = s => s === 'A' ? 'B' : 'A';
const clip = i => PROGRAM.length ? PROGRAM[((i % PROGRAM.length) + PROGRAM.length) % PROGRAM.length] : null;

window.onYouTubeIframeAPIReady = () => {
  bindNativePlayers();
  const initial=clip(currentIndex);
  if(initial){showBumper(currentIndex,0,'STARTING NOW');setPlaybackUi('starting');}
  else setPlaybackUi('paused');
  // Empty iframe players are intentional. Live/catalog programming owns the first
  // media assignment; a test/demo video must never be the bootstrap authority.
  createPlayer('A', String(initial?.youtubeId||initial?.id||''), false);
  createPlayer('B', '', false);
  renderQueue();
  if(initial)renderMetadata();
  safeStartLiveData();
};

function safeStartLiveData(){
  if(liveDataInitStarted) return;
  liveDataInitStarted=true;
  try{ fetch('/api/client-log?event=APP_LIVE_START&v=4.3.7',{cache:'no-store'}).catch(()=>{}); }catch(e){}
  initLiveData().catch(err=>{
    console.warn('Live data startup failed',err);
    try{ fetch('/api/client-log?event=APP_LIVE_ERROR&detail='+encodeURIComponent(String(err?.stack||err)),{cache:'no-store'}).catch(()=>{}); }catch(e){}
    setDataStatus('OFFLINE', false);
    setFeedNote('Live data unavailable • playback fallback queue active');
  });
}

// Live score/news discovery must never depend on YouTube's iframe callback.
// The iframe API may be served from browser cache quickly enough to fire before
// app.js registers onYouTubeIframeAPIReady. Start data independently as soon as
// the DOM is usable; the guard above makes the YouTube callback harmlessly idempotent.
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', safeStartLiveData, {once:true});
else queueMicrotask(safeStartLiveData);


function isNativeItem(item){ return !!(item && item.mediaUrl && !item.youtubeId); }
function isContextItem(item){ return !!(item && item.programType==='context'); }
function isTopPlaysItem(item){ return !!(item && (item.programType==='top-plays' || item.programType==='top-plays-clip')); }
function topPlaysGroupIdentity(item){
  if(!isTopPlaysItem(item)) return '';
  const scope=String(item.editorialScope||'cross-sport').toLowerCase();
  const league=scope==='league'?String(item.competitionId||item.originalLeague||item.league||'SPORTS').toUpperCase():'SPORTS';
  const cadence=String(item.cadence||'daily').toLowerCase();
  const period=item.editorialPeriodKey||item.topPlaysDate||String(item.publishedAt||'').slice(0,10)||cadence;
  return `topplays:${scope}:${league}:${cadence}:${period}`;
}
function topPlayCategory(item){
  const t=String(item?.title||'').toLowerCase();
  if(/rob(?:s|bed)?|diving|leaping|sliding catch|barehand|bare-handed|throw|double play|save|block|steal|interception|goal-line|goal line|defensive|web gem|outfield assist/i.test(t)) return 'defense';
  if(/walk-?off|buzzer|game[- ]winner|go-ahead|go ahead|overtime|extra-inning|extra inning|stoppage|equalizer|clinch|elimination/i.test(t)) return 'clutch';
  if(/bicycle|bike|poster|dunk|ankle|skill|solo run|dribble|one-handed|one handed|between-the-legs|between the legs|behind-the-back|behind the back/i.test(t)) return 'skill';
  if(/record|milestone|first career|career-high|career high|debut|no-hitter|perfect game|hat trick/i.test(t)) return 'milestone';
  if(/home run|homer|grand slam|touchdown|goal|three-pointer|3-pointer|slam|scores?/i.test(t)) return 'scoring';
  return 'other';
}
function topPlayCandidateEligible(item){
  const text=`${item?.title||''} ${item?.subtitle||''} ${item?.description||''}`.toLowerCase();
  // A Top Plays candidate must depict an athletic play, not merely be sports video.
  // Keep this hard gate deterministic so interviews/analysis never enter the countdown
  // even if an AI ranking request is unavailable.
  if(/interview|press conference|postgame|post-game|pregame|pre-game|preview|recap|full game highlights|full match highlights|condensed|talks? about|speaks? (?:after|on|about)|reacts?|reaction|on being|comfortable at the plate|discusses?|explains?|breaks down|analysis|podcast|mic['’]?d up|behind the scenes|training camp|practice report|rankings?|rumou?r|fantasy|betting|starting lineup|projected lineup|\blineup\b|starting five|starting xi|depth chart|animation|animated|visualization|simulation|swing mechanics|swing path|swing breakdown|bat path|film study|chalk talk|diagram|graphic package|how .* (?:hit|throw|shoot|swing)/i.test(text)) return false;
  const action=/walk-?off|game[- ]winner|buzzer|go-ahead|equalizer|stoppage|clinch|rob(?:s|bed)?|diving|leaping|sliding catch|barehand|bare-handed|web gem|outfield assist|double play|triple play|throw(?:s)? out|save|block|steal|interception|pick-?six|sack|goal[- ]line|touchdown|field goal|kick return|punt return|one-handed catch|home run|homer|grand slam|double|triple|rbi single|strike(?:s)? out|strikeout|goal|golazo|bicycle|volley|free kick|header|assist|dunk|poster|three-pointer|3-pointer|alley-oop|overtime winner|shootout|breakaway|ace|match point|winner|hole[- ]in[- ]one|eagle|birdie|record|milestone|first career|career-high|career high|no-hitter|perfect game|hat trick/i;
  return action.test(text);
}
function topPlayValue(item){
  const title=String(item?.title||'').toLowerCase();
  let score=Number(item?.importance||0)+sourceQuality(item)*0.45;
  const cat=topPlayCategory(item);
  if(cat==='defense') score+=31;
  if(cat==='clutch') score+=29;
  if(cat==='skill') score+=27;
  if(cat==='milestone') score+=19;
  if(cat==='scoring') score+=12;
  if(/grand slam|buzzer|game[- ]winner|walk-?off|rob(?:s|bed)?|spectacular|incredible|insane|stunner|wonder goal|bicycle|poster|diving|leaping|one-handed|one handed/i.test(title)) score+=18;
  if(/solo home run|solo homer/i.test(title) && !/walk-?off|record|milestone|first career/i.test(title)) score-=8;
  const ai=AI_TOP_PLAY_RANKINGS.get(String(item?.id||''));
  if(ai) score+=Number(ai.score||0)*0.55;
  const ms=publishedTimeMs(item); if(ms) score+=Math.max(0,14-(Date.now()-ms)/3600000);
  return score;
}
function buildGeneratedTopPlays(items){
  const today=localDateISO(0);
  const source=(items||[])
    .filter(x=>x?.verifiedPlayable && (x.youtubeId||x.mediaUrl))
    .filter(x=>!isFullRecapCandidate(x) && !x.eventType && !isContextItem(x) && !isTopPlaysItem(x))
    .filter(x=>String(x.gameDate||x.__sbbDate||x.date||x.publishedAt||'').slice(0,10)===today)
    .filter(x=>{const d=Number(x.durationSeconds??x.duration)||0; return !d || (d>=6&&d<=100);})
    .filter(topPlayCandidateEligible);

  const candidates=[...source].sort((a,b)=>topPlayValue(b)-topPlayValue(a));
  const chosen=[], gameCount=new Map(), catCount=new Map(), leagueCount=new Map();
  const identity=x=>programGameIdentity(x)||String(x.id||'');
  const leagueOf=x=>String(x.originalLeague||x.league||x.sport||'SPORTS').toUpperCase();

  const take=x=>{
    if(!x || chosen.includes(x)) return false;
    const g=identity(x), cat=topPlayCategory(x), lg=leagueOf(x);
    if((gameCount.get(g)||0)>=2) return false;
    if((leagueCount.get(lg)||0)>=5) return false;
    chosen.push(x);
    gameCount.set(g,(gameCount.get(g)||0)+1);
    catCount.set(cat,(catCount.get(cat)||0)+1);
    leagueCount.set(lg,(leagueCount.get(lg)||0)+1);
    return true;
  };

  // Reserve variety before routine scoring: defense, clutch, skill and milestone.
  for(const category of ['defense','clutch','skill','milestone','defense','clutch']){
    take(candidates.find(c=>topPlayCategory(c)===category && (gameCount.get(identity(c))||0)<2));
  }

  for(const x of candidates){
    if(chosen.length>=10) break;
    const cat=topPlayCategory(x);
    if(cat==='scoring' && (catCount.get('scoring')||0)>=5) continue;
    take(x);
  }

  // Do not fabricate a Top 10 with explainers or lineup clips. Until ten real
  // athletic plays exist, those clips simply remain in normal highlight programming.
  if(chosen.length<10) return [];

  const strongest=[...chosen].sort((a,b)=>topPlayValue(b)-topPlayValue(a)).slice(0,10);
  const airOrder=[...strongest].reverse(); // #10 first, #1 last
  const totalDuration=airOrder.reduce((sum,x)=>sum+(Number(x.durationSeconds??x.duration)||0),0);

  return airOrder.map((x,i)=>{
    const rank=10-i;
    const cleanTitle=String(x.title||'Top Play').replace(/^#\d+\s*[•:-]\s*/,'');
    return {
      ...x,
      id:`topplays-generated:${today}:${rank}:${x.id}`,
      league:'SPORTS', sport:'multi-sport', originalLeague:x.league,
      title:`#${rank} • ${cleanTitle}`,
      subtitle:`Top 10 Plays Today • ${x.league||'Sports'} • ${topPlayCategory(x)}`,
      topPlaysGroupTitle:'Top 10 Plays Today',
      topPlaysTotalDuration:totalDuration,
      programType:'top-plays-clip', topPlaysDate:today,
      topPlaysIndex:rank, topPlaysCount:10,
      chronology:[0,i+1,0,0,0], overview:false,
      importance:94+(10-rank)*0.25,
      generatedTopPlays:true, topPlayCategory:topPlayCategory(x), topPlayRank:rank
    };
  });
}

function contextEl(slot){ return $(`context${slot}`); }
function renderContextProgram(slot,item){
  const el=contextEl(slot); if(!el) return;
  const league=String(item?.league||'SPORTS').toUpperCase();
  const sourceStories=(item?.contextItems||[]).slice(0,6);
  const stories=[...sourceStories];
  while(stories.length<6) stories.push(null);
  const rows=stories.map((x,i)=>{
    if(!x){
      return `<div class="context-story context-story-empty"><span>Awaiting next consequential update</span></div>`;
    }
    const ms=Date.parse(x?.publishedAt||'')||0;
    const age=ms?formatRelativeAge(ms):'recently';
    return `
      <div class="context-story">
        <div class="context-story-top">
          <span class="context-index">${i+1}</span>
          <span class="context-category">${escapeHtml(String(x.category||'UPDATE'))}</span>
          <span class="context-age">${escapeHtml(age)}</span>
        </div>
        <strong>${escapeHtml(String(x.title||''))}</strong>
      </div>`;
  }).join('');
  const contextTitle=String(item?.title||`Around the ${league}`);
  el.innerHTML=`
    <div class="context-program-inner">
      <div class="context-topline">
        <span class="context-sbb">SPORTS BIG BOARD</span>
        <span class="context-live-dot"></span>
        <span>LIVE DESK</span>
      </div>
      <div class="context-titlebar">
        <span class="context-league-badge">${escapeHtml(league)}</span>
        <div>
          <div class="context-heading">${escapeHtml(contextTitle.toUpperCase())}</div>
          <div class="context-subheading">${escapeHtml(item?.subtitle||'The most consequential updates around the league')}</div>
        </div>
      </div>
      <div class="context-stories">${rows}</div>
      <div class="context-footer">
        <span>${escapeHtml(league)}</span>
        <b>AROUND THE LEAGUE</b>
        <span>RANKED BY CONSEQUENCE • UPDATED CONTINUOUSLY</span>
      </div>
    </div>`;
}
function nativePlaybackUrl(item){
  const raw=String(item?.mediaUrl||'');
  if(!raw) return '';
  if(raw.startsWith('/api/media?')) return window.SBB_API?.url?.(raw)||raw;
  // v2.7: DIRECT_VIDEO is a transport, not an MLB feature. Every allow-listed
  // HTTPS direct asset gets the same localhost range cache / buffering runway.
  if(/^https:\/\//i.test(raw) && window.SBB_PLAYBACK_TRANSPORTS?.transportForAsset?.(item)==='DIRECT_VIDEO'){
    const eventId=item?.eventId||item?.matchId||item?.gamePk||'';
    const proxy=`/api/media?url=${encodeURIComponent(raw)}&eventId=${encodeURIComponent(eventId)}&date=${encodeURIComponent(item?.gameDate||item?.date||'')}`;
    return window.SBB_API?.url?.(proxy)||proxy;
  }
  return raw;
}
function nativeEl(slot){
  const current=nativeSlotNodes[slot];
  if(current?.isConnected) return current;
  const fallback=$(`native${slot}`);
  if(fallback){ nativeSlotNodes[slot]=fallback; fallback.dataset.sbbLogicalSlot=slot; }
  return fallback;
}
function ytHost(slot){ return $(`player${slot}`); }

function nativePrimeKey(item){
  return isNativeItem(item) ? playbackItemKey(item) : '';
}
function ensureScoreNativeWarmDock(){
  let dock=$('scoreNativeWarmDock');
  if(dock) return dock;
  dock=document.createElement('div');
  dock.id='scoreNativeWarmDock';
  dock.setAttribute('aria-hidden','true');
  dock.style.cssText='position:fixed;left:0;top:0;width:4px;height:4px;overflow:hidden;opacity:.001;pointer-events:none;z-index:-1';
  document.body.appendChild(dock);
  return dock;
}
function destroyPreparedNativeEntry(entry){
  if(!entry) return;
  entry.destroyed=true;
  const v=entry.video;
  try{ v?.pause(); }catch(e){}
  try{ if(v){ v.removeAttribute('src'); v.load(); } }catch(e){}
  try{ v?.remove(); }catch(e){}
}
function prunePreparedNativePool(){
  const now=Date.now();
  const limit=scorePreparedLimit();
  const entries=[...scoreMediaPrimeState.entries.entries()];
  for(const [key,entry] of entries){
    if(entry.destroyed || (entry.expiresAt && entry.expiresAt<now)){
      scoreMediaPrimeState.entries.delete(key);
      destroyPreparedNativeEntry(entry);
    }
  }
  while(scoreMediaPrimeState.entries.size>limit){
    // Never let a background/nearby candidate evict something the current
    // predictive scheduler says should remain HOT. Non-HOT entries go first.
    let candidates=[...scoreMediaPrimeState.entries.entries()]
      .filter(([,entry])=>!entry.warming && !scoreMediaPrimeState.desiredHot.has(entry.key))
      .sort((a,b)=>(a[1].lastWantedAt||0)-(b[1].lastWantedAt||0));
    if(!candidates.length){
      candidates=[...scoreMediaPrimeState.entries.entries()]
        .filter(([,entry])=>!entry.warming)
        .sort((a,b)=>(a[1].lastWantedAt||0)-(b[1].lastWantedAt||0));
    }
    if(!candidates.length) break;
    const [key,entry]=candidates[0];
    scoreMediaPrimeState.entries.delete(key);
    destroyPreparedNativeEntry(entry);
  }
}
function finishPreparedNativeWarm(entry,ready){
  if(!entry || entry.settled || entry.destroyed) return;
  entry.settled=true;
  entry.warming=false;
  entry.ready=!!ready && !!entry.video && entry.video.readyState>=2;
  entry.expiresAt=Date.now()+SCORE_MEDIA_PRIME_TTL_MS;
  entry.lastWantedAt=Date.now();
  const v=entry.video;
  if(v){
    try{ v.pause(); }catch(e){}
    try{ if(Number.isFinite(v.duration) && v.currentTime>0.03) v.currentTime=0; else if(v.currentTime>0) v.currentTime=0; }catch(e){}
  }
  scoreMediaPrimeState.active=Math.max(0,scoreMediaPrimeState.active-1);
  if(!entry.ready){
    scoreMediaPrimeState.entries.delete(entry.key);
    destroyPreparedNativeEntry(entry);
  }else{
    setPlaybackDiag({lastAction:'score media player hot-ready'});
  }
  drainScoreMediaPrimeQueue();
}
function startPreparedNativeWarm(job){
  const {item,key}=job;
  const dock=ensureScoreNativeWarmDock();
  const v=document.createElement('video');
  v.className='native-score-prepared';
  v.playsInline=true;
  v.preload='auto';
  v.muted=true;
  v.controls=false;
  v.setAttribute('playsinline','');
  v.setAttribute('webkit-playsinline','');
  const entry={key,item,video:v,warming:true,ready:false,settled:false,destroyed:false,generation:job.generation,lastWantedAt:Date.now(),keepUntil:Date.now()+SCORE_MEDIA_HYSTERESIS_MS,tier:job.tier||'hot',expiresAt:0};
  scoreMediaPrimeState.entries.set(key,entry);
  scoreMediaPrimeState.active++;
  dock.appendChild(v);
  const mediaSrc=nativePlaybackUrl(item);
  v.src=mediaSrc;

  let playAttempted=false;
  const attemptMutedPlay=()=>{
    if(entry.destroyed || entry.settled || playAttempted) return;
    playAttempted=true;
    v.muted=true;
    let playPromise;
    try{ playPromise=v.play(); }catch(e){ playPromise=null; }
    if(playPromise?.catch) playPromise.catch(()=>{
      // canplay is still a useful prepared state even when browser policy refuses
      // an offscreen muted play. We do not fail the cache solely on that policy.
      if(v.readyState>=3) finishPreparedNativeWarm(entry,true);
    });
  };
  v.addEventListener('loadedmetadata',attemptMutedPlay,{once:true});
  v.addEventListener('canplay',()=>{
    attemptMutedPlay();
    // If playing does not arrive quickly, canplay means the decoder already has
    // enough buffered media to make adoption materially faster than a cold load.
    setTimeout(()=>{ if(!entry.settled && v.readyState>=3) finishPreparedNativeWarm(entry,true); },220);
  },{once:true});
  v.addEventListener('playing',()=>{
    // Let a couple of real frames decode, then park at the beginning. The same
    // element is later adopted, so this buffer/decoder state survives the click.
    setTimeout(()=>finishPreparedNativeWarm(entry,true),140);
  },{once:true});
  v.addEventListener('error',()=>finishPreparedNativeWarm(entry,false),{once:true});
  setTimeout(()=>finishPreparedNativeWarm(entry,v.readyState>=3),10000);
  try{ v.load(); attemptMutedPlay(); }catch(e){ finishPreparedNativeWarm(entry,false); }
}
function drainScoreMediaPrimeQueue(){
  prunePreparedNativePool();
  const limit=scorePreparedLimit();
  // Drop obsolete queued work before it consumes a decoder. Pointer-intent jobs
  // are marked priority and survive one reconciliation cycle.
  scoreMediaPrimeState.queue=scoreMediaPrimeState.queue.filter(job=>{
    const keep=job && (job.priority || scoreMediaPrimeState.desiredHot.has(job.key));
    if(!keep && job) scoreMediaPrimeState.queued.delete(job.key);
    return keep;
  });
  scoreMediaPrimeState.queue.sort((a,b)=>(b.rank||0)-(a.rank||0));
  while(scoreMediaPrimeState.active<SCORE_MEDIA_PRIME_MAX_ACTIVE && scoreMediaPrimeState.queue.length){
    const job=scoreMediaPrimeState.queue[0];
    if(!job){ scoreMediaPrimeState.queue.shift(); continue; }
    if(job.generation!==scoreMediaPrimeGeneration && !job.priority){ scoreMediaPrimeState.queue.shift(); scoreMediaPrimeState.queued.delete(job.key); continue; }
    const existing=scoreMediaPrimeState.entries.get(job.key);
    if(existing){
      scoreMediaPrimeState.queue.shift(); scoreMediaPrimeState.queued.delete(job.key);
      existing.lastWantedAt=Date.now(); existing.generation=scoreMediaPrimeGeneration; existing.keepUntil=Math.max(existing.keepUntil||0,Date.now()+SCORE_MEDIA_HYSTERESIS_MS);
      continue;
    }
    if(scoreMediaPrimeState.entries.size>=limit){
      const evictable=[...scoreMediaPrimeState.entries.entries()]
        .filter(([,entry])=>!entry.warming && !scoreMediaPrimeState.desiredHot.has(entry.key))
        .sort((a,b)=>{
          const aPinned=(a[1].keepUntil||0)>Date.now()?1:0, bPinned=(b[1].keepUntil||0)>Date.now()?1:0;
          return aPinned-bPinned || (a[1].lastWantedAt||0)-(b[1].lastWantedAt||0);
        });
      if(!evictable.length) break;
      const [evictKey,evictEntry]=evictable[0];
      scoreMediaPrimeState.entries.delete(evictKey); destroyPreparedNativeEntry(evictEntry);
    }
    scoreMediaPrimeState.queue.shift(); scoreMediaPrimeState.queued.delete(job.key);
    startPreparedNativeWarm(job);
  }
}
function preparedNativeEntryForItem(item,{requireReady=true,allowUsable=false}={}){
  const key=nativePrimeKey(item); if(!key) return null;
  prunePreparedNativePool();
  const entry=scoreMediaPrimeState.entries.get(key);
  const usable=!!entry?.video && entry.video.readyState>=1;
  if(!entry || entry.destroyed || (requireReady && !entry.ready && !(allowUsable&&usable))) return null;
  const mediaSrc=nativePlaybackUrl(item);
  const attr=String(entry.video?.getAttribute('src')||'');
  let absolute=''; try{ absolute=new URL(mediaSrc,location.href).href; }catch(e){}
  const current=String(entry.video?.currentSrc||entry.video?.src||'');
  if(attr!==mediaSrc && current!==absolute && current!==mediaSrc) return null;
  entry.lastWantedAt=Date.now(); entry.keepUntil=Math.max(entry.keepUntil||0,Date.now()+SCORE_MEDIA_HYSTERESIS_MS); entry.generation=scoreMediaPrimeGeneration;
  return entry;
}
function isScoreMediaPrimed(item){
  if(!item) return false;
  const standby=otherSlot(activeSlot);
  const claim=slotAssignment[standby];
  if(claim && claim.key===playbackItemKey(item) && videoReady[standby]) return true;
  return !!preparedNativeEntryForItem(item,{requireReady:true,allowUsable:true});
}
function primeScoreMediaItem(item,{priority=false,rank=0}={}){
  const key=nativePrimeKey(item);
  if(!key) return false;
  const existing=preparedNativeEntryForItem(item,{requireReady:false});
  if(existing){
    existing.lastWantedAt=Date.now(); existing.keepUntil=Math.max(existing.keepUntil||0,Date.now()+SCORE_MEDIA_HYSTERESIS_MS);
    return true;
  }
  if(scoreMediaPrimeState.queued.has(key)){
    const i=scoreMediaPrimeState.queue.findIndex(x=>x.key===key);
    if(i>=0){
      const job=scoreMediaPrimeState.queue[i]; job.rank=Math.max(job.rank||0,rank||0); job.priority=job.priority||!!priority; job.generation=scoreMediaPrimeGeneration;
      scoreMediaPrimeState.queue.sort((a,b)=>(b.rank||0)-(a.rank||0));
    }
    return true;
  }
  scoreMediaPrimeState.queued.add(key);
  const job={key,item,generation:scoreMediaPrimeGeneration,priority:!!priority,rank:Number(rank||0),tier:'hot'};
  scoreMediaPrimeState.queue.push(job);
  drainScoreMediaPrimeQueue();
  return true;
}
function takePreparedNativeEntry(item){
  // A pointer click may arrive while the hidden player is still finishing its
  // formal warm cycle. loaded metadata (readyState>=1) is enough to adopt the exact element rather
  // than throwing away useful decoder/network progress and cold-loading again.
  const entry=preparedNativeEntryForItem(item,{requireReady:true,allowUsable:true});
  if(!entry) return null;
  scoreMediaPrimeState.entries.delete(entry.key);
  const wasWarming=entry.warming&&!entry.settled;
  if(wasWarming) scoreMediaPrimeState.active=Math.max(0,scoreMediaPrimeState.active-1);
  // Mark the warm job settled before adoption so its late canplay/playing timer
  // cannot delete or pause a new cache entry for the same key after handoff.
  entry.settled=true; entry.expiresAt=0; entry.ready=entry.ready||entry.video?.readyState>=1; entry.warming=false;
  drainScoreMediaPrimeQueue();
  return entry;
}

function rememberRecentScoreMedia(item){
  const key=nativePrimeKey(item); if(!key) return;
  scoreMediaPrimeState.recentKeys=[key,...scoreMediaPrimeState.recentKeys.filter(x=>x!==key)].slice(0,3);
}
function rawNativeMediaUrl(item){
  const raw=String(item?.mediaUrl||'');
  if(/^https:\/\//i.test(raw)) return raw;
  if(raw.includes('/api/media?')){ try{return new URL(raw,location.href).searchParams.get('url')||'';}catch(e){} }
  return '';
}
function sendServerMediaWarmSet(rows){
  const items=(rows||[]).filter(x=>isNativeItem(x.item)).slice(0,scoreServerWarmLimit()).map((x,i)=>({
    url:rawNativeMediaUrl(x.item), eventId:x.item?.eventId||x.item?.matchId||x.item?.gamePk||'', gamePk:x.item?.gamePk||'', date:x.item?.gameDate||x.item?.date||'',
    priority:i<scorePreparedLimit()?3:1, priorityClass:i<scorePreparedLimit()?(window.SBB_MEDIA_WORK?.PRIORITY.VISIBLE_SCORE||'VISIBLE_SCORE'):(window.SBB_MEDIA_WORK?.PRIORITY.NEARBY_SCORE||'NEARBY_SCORE')
  })).filter(x=>x.url);
  if(!items.length) return;
  const signature=items.map(x=>x.url).join('|');
  if(signature===scoreServerWarmSignature) return;
  scoreServerWarmSignature=signature;
  clearTimeout(scoreServerWarmTimer);
  scoreServerWarmTimer=setTimeout(()=>{
    fetch('/api/media/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items}),cache:'no-store'})
      .then(r=>r.ok?r.json():null).then(data=>{ if(data?.cache) setPlaybackDiag({lastAction:`server media cache staged ${data.accepted||0}`}); }).catch(()=>{});
  },120);
}
function scoreCandidateRank(candidate,hostRect){
  const rect=candidate.cell.getBoundingClientRect();
  const overlap=Math.max(0,Math.min(rect.right,hostRect.right)-Math.max(rect.left,hostRect.left));
  const visible=overlap>Math.min(24,rect.width*.15);
  const center=(rect.left+rect.right)/2, hostCenter=(hostRect.left+hostRect.right)/2;
  const distance=Math.abs(center-hostCenter);
  let rank=visible?100000:Math.max(0,60000-distance*25);
  if(candidate.final) rank+=5000;
  if(candidate.item?.overview) rank+=3500;
  if(scoreMediaPrimeState.recentKeys.includes(candidate.key)) rank+=18000;
  return {rank,visible,distance};
}
function reconcileScoreMediaWarmSet({intentItem=null}={}){
  const host=$('scoreCells'); if(!host || !scoreMediaPrimeState.candidates.length) return;
  const hostRect=host.getBoundingClientRect();
  let ranked=scoreMediaPrimeState.candidates.filter(c=>c.cell?.isConnected&&isNativeItem(c.item)).map(c=>Object.assign({},c,scoreCandidateRank(c,hostRect)));
  ranked.sort((a,b)=>b.rank-a.rank);
  if(intentItem){
    const key=nativePrimeKey(intentItem); rememberRecentScoreMedia(intentItem);
    ranked=ranked.map(x=>x.key===key?Object.assign({},x,{rank:x.rank+1000000,visible:true}):x).sort((a,b)=>b.rank-a.rank);
  }
  const hotLimit=scorePreparedLimit(), warmLimit=scoreServerWarmLimit();
  const visible=ranked.filter(x=>x.visible);
  const desired=[]; const used=new Set();
  const add=x=>{if(x&&!used.has(x.key)&&desired.length<hotLimit){used.add(x.key);desired.push(x);}};
  // Actual visible cards always win. Then preserve nearby existing HOT entries
  // before filling with predicted next cards, which prevents FIFO/LRU churn.
  visible.forEach(add);
  for(const key of scoreMediaPrimeState.recentKeys) add(ranked.find(x=>x.key===key));
  for(const key of scoreMediaPrimeState.desiredHot){
    const x=ranked.find(r=>r.key===key);
    if(x && x.distance<hostRect.width*1.8) add(x);
  }
  ranked.forEach(add);
  scoreMediaPrimeState.desiredHot=new Set(desired.map(x=>x.key));
  scoreMediaPrimeState.desiredWarm=new Set(ranked.slice(0,warmLimit).map(x=>x.key));
  // If a rapid ribbon scroll makes an in-flight decoder irrelevant even to the
  // broader WARM neighborhood, cancel it so one of the three decoder lanes can
  // immediately work on what is actually on screen. Exact/recent intent survives.
  for(const [key,entry] of [...scoreMediaPrimeState.entries.entries()]){
    if(entry.warming && !scoreMediaPrimeState.desiredWarm.has(key) && !scoreMediaPrimeState.recentKeys.includes(key)){
      entry.settled=true; entry.warming=false; entry.destroyed=true;
      scoreMediaPrimeState.active=Math.max(0,scoreMediaPrimeState.active-1);
      scoreMediaPrimeState.entries.delete(key); destroyPreparedNativeEntry(entry);
    }
  }
  // Cancel queued decoder work that is no longer predicted HOT. Existing decoded
  // elements remain available until normal hysteresis/pressure pruning.
  scoreMediaPrimeState.queue=scoreMediaPrimeState.queue.filter(job=>{
    const keep=job.priority||scoreMediaPrimeState.desiredHot.has(job.key);
    if(!keep) scoreMediaPrimeState.queued.delete(job.key);
    return keep;
  });
  desired.forEach(x=>primeScoreMediaItem(x.item,{priority:scoreMediaPrimeState.recentKeys.includes(x.key),rank:x.rank}));
  // HOT media is already being opened by a real hidden <video>; the proxy
  // caches that same stream. Ask the server to proactively fetch only the WARM
  // candidates so browser/server prewarming never duplicate an upstream request.
  sendServerMediaWarmSet(ranked.slice(hotLimit,warmLimit));
  drainScoreMediaPrimeQueue();
}
function scheduleScoreMediaWarmReconcile(delay=80){
  clearTimeout(scoreMediaWarmReconcileTimer);
  scoreMediaWarmReconcileTimer=setTimeout(()=>reconcileScoreMediaWarmSet(),delay);
}
if(!window.__SBB_SCORE_WARM_HEARTBEAT__){
  window.__SBB_SCORE_WARM_HEARTBEAT__=setInterval(()=>{
    if(!document.hidden && scoreMediaPrimeState.candidates.length) scheduleScoreMediaWarmReconcile(0);
  },5000);
}
function primeScoreIntent(item){
  if(!item) return;
  rememberRecentScoreMedia(item);
  primeScoreMediaItem(item,{priority:true,rank:1000000});
  reconcileScoreMediaWarmSet({intentItem:item});
  // Do not launch a second server-side fetch on pointerdown. If this was already
  // WARM the server cache has it; otherwise the hidden player's /api/media stream
  // is now the priority request and will populate the cache opportunistically.
}


function playbackItemKey(item){
  if(!item) return 'none';
  return window.SBB_PLAYBACK_TRANSPORTS?.playbackKey?.(item) || (isContextItem(item)?`context:${item.id||item.eventId||item.title||''}`:(isNativeItem(item)?`direct:${nativePlaybackUrl(item)}`:`youtube:${item.youtubeId||item.id||''}`));
}

function runtimeMediaUsable(item){
  if(!window.SBB_PLAYBACK_TRANSPORTS?.inAppPlayable?.(item) && (!item?.verifiedPlayable || !(item.youtubeId||item.mediaUrl))) return false;
  const key=playbackItemKey(item);
  return (!key || !RUNTIME_UNPLAYABLE_MEDIA.has(key)) && item?.runtimeState!=='failed';
}
const HISTORICAL_RUNTIME_REPORTED=new Set();
function historicalAssetKey(item){
  if(!item) return '';
  if(item.youtubeId) return `yt:${String(item.youtubeId)}`;
  if(item.id) return `id:${String(item.id)}`;
  if(item.mediaUrl) return `url:${String(item.mediaUrl)}`;
  if(item.externalUrl) return `ext:${String(item.externalUrl)}`;
  return '';
}
function reportHistoricalRuntime(item,state,reason=''){
  try{
    const match=userPlaybackSession?.match||knownMatchForMedia(item)||window.SBB_SELECTED_EVENT?.get?.();
    const date=String(userPlaybackSession?.playbackDate||scorePlaybackDate||item?.gameDate||item?.date||'').slice(0,10);
    if(!date || date>=localDateISO(0) || !match) return;
    const league=String(match.__sbbLeague||match.competitionId||match.league||item?.competitionId||item?.league||'').toUpperCase();
    const eventId=String(match.espnEventId||match.scoreEventId||match.matchId||match.eventId||match.id||item?.scoreEventId||item?.matchId||'');
    const assetKey=historicalAssetKey(item);
    if(!league||!eventId||!assetKey) return;
    const reportKey=`${state}:${date}:${league}:${eventId}:${assetKey}`;
    if(state==='PLAYED' && HISTORICAL_RUNTIME_REPORTED.has(reportKey)) return;
    if(state==='PLAYED') HISTORICAL_RUNTIME_REPORTED.add(reportKey);
    fetch('/api/history/media/runtime',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date,league,eventId,assetKey,state,reason:String(reason||'').slice(0,400)}),cache:'no-store'}).catch(()=>{});
  }catch(_){ }
}

function markRuntimeMediaFailed(item,reason='runtime playback failure',{providerFailure=true}={}){
  if(!item) return;
  const key=playbackItemKey(item);
  if(!key || key==='none') return;
  reportHistoricalRuntime(item,'FAILED',reason);
  RUNTIME_UNPLAYABLE_MEDIA.add(key);
  // If an official web URL still exists, preserve discovery truth separately from
  // playback truth. The asset remains available as an external ↗ package even
  // after this browser proves it cannot be embedded.
  if(item?.externalUrl){
    item.externalOnly=true; item.verifiedPlayable=false; item.embedValidated=false;
    const lg=String(item.competitionId||item.league||'SPORTS').toUpperCase();
    const ext=[...(EXTERNAL_CANDIDATES_BY_LEAGUE.get(lg)||[])];
    if(!ext.some(x=>String(x.id)===String(item.id))) ext.push(item);
    EXTERNAL_CANDIDATES_BY_LEAGUE.set(lg,ext);
    const keys=[];
    if(item.matchId) keys.push(`match:${String(item.competitionId||item.league||'SPORTS').toUpperCase()}:${item.matchId}`);
    if(item.scoreGameKey && !String(item.scoreGameKey).endsWith('::-')) keys.push(`scoregame:${item.scoreGameKey}`);
    if(item.gameKey && item.gameDate) keys.push(`game:${item.gameDate}:${item.gameKey}`);
    for(const k of keys){
      if(!EXTERNAL_MEDIA_BY_MATCH.has(k)) EXTERNAL_MEDIA_BY_MATCH.set(k,[]);
      const arr=EXTERNAL_MEDIA_BY_MATCH.get(k);
      if(!arr.some(x=>String(x.id)===String(item.id))) arr.push(item);
    }
  }
  const manifestEvent=knownMatchForMedia(item)||window.SBB_SELECTED_EVENT?.get?.()||item;
  try{ window.SBB_MEDIA_MANIFEST?.markFailed?.(manifestEvent,item,reason); }catch(_){ }
  if(providerFailure){ try{ window.SBB_PROVIDER_HEALTH?.failure?.(item?.provider||item?.source||item?.sourceLabel||'UNKNOWN',reason); }catch(_){ } }
  try{ console.warn('[SBB media truth] runtime-unplayable',{key,reason,title:item?.title||''}); }catch(_){ }
  // Score-card rails and play buttons must reflect what can actually still play,
  // not what a provider claimed was playable before the browser tried it.
  setTimeout(()=>{ try{ renderScoresFromMatchesCombined(); }catch(_){ } },0);
}
function mediaMatchesScoreGame(item,match){
  // Moment clips may legitimately name only one player/team. A full-game YouTube
  // recap is different: both clubs must match the score card it is attached to.
  // This is a client-side second line of defense against stale/bad server cache
  // associations (for example White Sox-Cubs attached to Braves-White Sox).
  if(!item || !match || !item.youtubeId || !isFullRecapCandidate(item)) return true;
  const away=match.awayTeam||match.away||{};
  const home=match.homeTeam||match.home||{};
  const text=`${item.title||''} ${item.description||''} ${item.subtitle||''}`;
  return videoMentionsTeam(text,away) && videoMentionsTeam(text,home);
}

function knownMatchForMedia(item){
  if(!item) return null;
  const wantedIds=[item.matchId,item.gamePk,item.eventId,item.scoreEventId,item.espnEventId].filter(v=>v!==undefined&&v!==null&&String(v)!=='').map(String);
  const wantedDate=String(item.gameDate||item.date||item.__sbbDate||'').slice(0,10);
  const wantedKey=String(item.gameKey||'');
  const candidateRows=[...scoreMatchesForDate(wantedDate||scoreBrowseDate)];
  if(!wantedDate){
    for(const state of LIVE_MATCHES_BY_LEAGUE.values()) candidateRows.push(...(state?.yesterday||[]),...(state?.today||[]));
  }
  for(const m of candidateRows){
    const ids=[m.id,m.matchId,m.eventId,m.gamePk,m.scoreEventId,m.espnEventId].filter(v=>v!==undefined&&v!==null&&String(v)!=='').map(String);
    if(wantedIds.some(id=>ids.includes(id))) return m;
    if(wantedDate && wantedKey){
      const away=m.awayTeam||m.away||{}, home=m.homeTeam||m.home||{};
      const date=scoreEventDate(m);
      if(date===wantedDate && gameKey(teamAbbr(away,''),teamAbbr(home,''))===wantedKey) return m;
    }
  }
  return null;
}
function mediaMatchesKnownGame(item){
  const match=knownMatchForMedia(item);
  return !match || mediaMatchesScoreGame(item,match);
}
function claimSlot(slot,item,role='standby'){
  const epoch=(slotEpoch[slot]||0)+1;
  slotEpoch[slot]=epoch;
  slotAssignment[slot]={
    epoch,
    key:playbackItemKey(item),
    role,
    provider:isContextItem(item)?'context':(isNativeItem(item)?'native':'youtube'),
    youtubeId:String(item?.youtubeId||item?.id||''),
    nativeUrl:isNativeItem(item)?nativePlaybackUrl(item):'',
    claimedAt:performance.now()
  };
  return epoch;
}
function promoteSlotClaim(slot,item){
  const claim=slotAssignment[slot];
  if(claim && claim.key===playbackItemKey(item)){
    claim.role='active';
    return claim.epoch;
  }
  return claimSlot(slot,item,'active');
}
function slotClaimIsCurrent(slot,epoch,item=null){
  const claim=slotAssignment[slot];
  if(!claim || claim.epoch!==epoch) return false;
  return !item || claim.key===playbackItemKey(item);
}
function youtubeEventMatchesClaim(slot){
  const claim=slotAssignment[slot];
  if(!claim || claim.provider!=='youtube' || !claim.youtubeId) return false;
  let actual='';
  try{ actual=String(players[slot]?.getVideoData?.()?.video_id||''); }catch(e){}
  return !!actual && actual===claim.youtubeId;
}
function nativeEventMatchesClaim(slot){
  const claim=slotAssignment[slot];
  if(!claim || claim.provider!=='native' || !claim.nativeUrl) return false;
  const v=nativeEl(slot);
  const attr=String(v?.getAttribute('src')||'');
  const current=String(v?.currentSrc||'');
  return attr===claim.nativeUrl || current===claim.nativeUrl || current.endsWith(claim.nativeUrl);
}
function activeAssignmentMatchesCurrent(){
  const item=clip(currentIndex), claim=slotAssignment[activeSlot];
  return !!item && !!claim && claim.key===playbackItemKey(item) && claim.role==='active';
}

const PLAYBACK_DIAG={ provider:'—', slot:'—', state:'idle', error:'—', readyState:'—', networkState:'—', source:'—', lastAction:'—' };
function providerForItem(item){
  const type=window.SBB_PLAYBACK_TRANSPORTS?.transportForAsset?.(item);
  if(type) return type;
  if(isContextItem(item)) return 'CONTEXT';
  if(item?.youtubeId) return 'YOUTUBE_EMBED';
  if(item?.mediaUrl) return 'DIRECT_VIDEO';
  if(item?.externalUrl) return 'EXTERNAL';
  return 'UNSUPPORTED';
}
function playbackExternalSourceUrl(item){
  if(!item) return '';
  const youtubeId=String(item.youtubeId||((!item.mediaUrl&&String(item.id||'').length===11)?item.id:'')||'');
  if(youtubeId) return `https://www.youtube.com/watch?v=${encodeURIComponent(youtubeId)}`;
  return String(item.externalUrl||item.mediaUrl||'');
}
function playbackSessionDescriptor(item,extra={}){
  const transport=providerForItem(item);
  return {
    eventKey:typeof programGameIdentity==='function'?programGameIdentity(item):'',
    mediaKey:playbackItemKey(item), clipKey:playbackItemKey(item),
    title:String(item?.title||item?.name||''),
    league:String(item?.competitionId||item?.league||''), transport,
    sourceUrl:String(item?.youtubeId||item?.mediaUrl||item?.externalUrl||item?.id||''),
    sourceExternalUrl:playbackExternalSourceUrl(item), ...extra
  };
}

function setPlaybackDiag(patch={}){
  Object.assign(PLAYBACK_DIAG,patch);
  const pairs={diagProvider:'provider',diagSlot:'slot',diagState:'state',diagError:'error',diagReady:'readyState',diagNetwork:'networkState',diagSource:'source',diagAction:'lastAction'};
  for(const [id,key] of Object.entries(pairs)){ const el=$(id); if(el) el.textContent=String(PLAYBACK_DIAG[key] ?? '—'); }
}
function renderPlaybackSessionDiag(snapshot=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{}){
  const set=(id,value)=>{const el=$(id);if(el)el.textContent=String(value??'—');};
  set('diagSession',snapshot.sessionId||'—');
  set('diagMediaKey',snapshot.mediaKey||'—');
  set('diagFirstFrame',snapshot.firstFrameMs==null?'—':`${snapshot.firstFrameMs} ms`);
  set('diagStalls',`${Number(snapshot.stallCount||0)}${snapshot.stallTotalMs?` • ${Math.round(snapshot.stallTotalMs)} ms`:''}`);
  const invariant=$('diagInvariant'); if(invariant){invariant.textContent=snapshot.invariant||'OK';invariant.dataset.error=String(snapshot.invariant||'OK').startsWith('ERROR')?'1':'0';}
  const link=$('diagSourceLink'); if(link){const url=String(snapshot.sourceExternalUrl||'');link.textContent=url?'OPEN VIDEO ↗':'—'; if(url){link.href=url;link.removeAttribute('aria-disabled');}else{link.href='#';link.setAttribute('aria-disabled','true');}}
}
window.SBB_PLAYBACK_SESSION?.subscribe?.(renderPlaybackSessionDiag);
function nativeErrorText(v){
  const err=v?.error; if(!err) return '—';
  const names={1:'MEDIA_ERR_ABORTED',2:'MEDIA_ERR_NETWORK',3:'MEDIA_ERR_DECODE',4:'MEDIA_ERR_SRC_NOT_SUPPORTED'};
  return `${names[err.code]||'MEDIA_ERR'} (${err.code})${err.message?`: ${err.message}`:''}`;
}
function updateNativeDiag(slot,action='state'){
  const v=nativeEl(slot); if(!v) return;
  setPlaybackDiag({provider:'DIRECT_VIDEO',slot,state:v.paused?'paused':(v.ended?'ended':'playing'),readyState:v.readyState,networkState:v.networkState,source:v.currentSrc||v.getAttribute('src')||'—',error:nativeErrorText(v),lastAction:action});
}

const PlaybackAdapters={
  youtube(slot){ return {
    provider:'YOUTUBE',
    play(userInitiated=false){
      const audible = userInitiated || mediaInteractionUnlocked;
      setPlaybackDiag({provider:'YOUTUBE',slot,state:'play-requested',error:'—',source:String(clip(currentIndex)?.youtubeId||clip(currentIndex)?.id||'—'),lastAction:audible?'audible play':'muted autoplay'});
      try{
        if(audible){ players[slot]?.unMute(); startupMutedSlots[slot]=false; }
        else { players[slot]?.mute(); startupMutedSlots[slot]=true; }
        players[slot]?.playVideo();
        return Promise.resolve(true);
      }
      catch(err){ setPlaybackDiag({state:'rejected',error:`${err?.name||'Error'}: ${err?.message||err}`}); return Promise.reject(err); }
    },
    pause(){ try{players[slot]?.pauseVideo();}catch(e){} },
    isPlaying(){ try{return players[slot]?.getPlayerState?.()===YT.PlayerState.PLAYING}catch(e){return false} }
  }},
  native(slot){ return {
    provider:'DIRECT_VIDEO',
    play(userInitiated=false){
      const v=nativeEl(slot); if(!v){ const err=new Error(`Native player ${slot} unavailable`); setPlaybackDiag({provider:'DIRECT_VIDEO',slot,state:'rejected',error:err.message,lastAction:'native element missing'}); console.error('[SBB playback]',err); return Promise.reject(err); }
      const audible = userInitiated || mediaInteractionUnlocked;
      v.muted=!audible; startupMutedSlots[slot]=!audible;
      updateNativeDiag(slot,audible?'audible play requested':'muted autoplay requested');
      let p; try{p=v.play()}catch(err){ setPlaybackDiag({state:'rejected',error:`${err?.name||'Error'}: ${err?.message||err}`}); return Promise.reject(err); }
      if(p?.then) return p.then(()=>{ updateNativeDiag(slot,'play() promise resolved'); return true; }).catch(err=>{ updateNativeDiag(slot,'play() promise rejected'); setPlaybackDiag({state:'rejected',error:`${err?.name||'Error'}: ${err?.message||err}`}); throw err; });
      return Promise.resolve(true);
    },
    pause(){ try{nativeEl(slot)?.pause();}catch(e){} },
    isPlaying(){ const v=nativeEl(slot); return !!v && !v.paused && !v.ended && v.readyState>=2; }
  }},
  context(slot){ return {
    provider:'CONTEXT',
    play(){
      if(contextTimer[slot]) clearTimeout(contextTimer[slot]);
      initialized=true; videoReady[slot]=true; activePlaybackState='context-playing';
      setPlaybackDiag({provider:'CONTEXT',slot,state:'playing',error:'—',source:String(clip(currentIndex)?.title||'Around the League'),lastAction:'context card started'});
      setPlaybackUi('playing');
      const seconds=Math.max(6,Math.min(18,Number(clip(currentIndex)?.durationSeconds||10)));
      contextTimer[slot]=setTimeout(()=>{ if(slot===activeSlot && slotMedia[slot]==='context') advanceAfterCompletedItem(); },seconds*1000);
      return Promise.resolve(true);
    },
    pause(){ if(contextTimer[slot]){clearTimeout(contextTimer[slot]);contextTimer[slot]=null;} },
    isPlaying(){ return slot===activeSlot && slotMedia[slot]==='context' && !!contextTimer[slot]; }
  }}
};
function adapterForSlot(slot){
  return slotMedia[slot]==='context' ? PlaybackAdapters.context(slot)
    : slotMedia[slot]==='native' ? PlaybackAdapters.native(slot)
    : PlaybackAdapters.youtube(slot);
}

function unlockMediaFromGesture(){
  if(mediaInteractionUnlocked) return;
  mediaInteractionUnlocked=true;
  try{
    if(slotMedia[activeSlot]==='native'){
      const v=nativeEl(activeSlot); if(v) v.muted=false;
    } else {
      players[activeSlot]?.unMute();
    }
    startupMutedSlots[activeSlot]=false;
    // Unmuting an already-playing element does not emit another PLAYING event.
    // Update ownership truth synchronously so the milestone invariant reflects
    // what the user can actually hear immediately after the first gesture.
    try{window.SBB_PLAYBACK_SESSION?.setAudible?.('video',activeSlot,!!adapterForSlot(activeSlot)?.isPlaying?.());}catch(_){}
    setPlaybackDiag({lastAction:'user interaction unlocked audio'});
  }catch(e){}
}
document.addEventListener('pointerdown', unlockMediaFromGesture, {passive:true});
document.addEventListener('keydown', unlockMediaFromGesture, {passive:true});

async function reportNativePlaybackPath(v,slot){
  if(!v)return; const firstFrameMs=Math.max(0,Math.round(performance.now()-Number(v.__sbbTuneStartedAt||performance.now())));
  let transport=v.__sbbAdoptedHot?'BROWSER_HOT':'DIRECT_VIDEO'; let server={};
  try{
    const current=new URL(v.currentSrc||v.getAttribute('src')||'',location.href);
    const raw=current.pathname.endsWith('/api/media')?current.searchParams.get('url'):'';
    if(raw){ const r=await fetch(`/api/media/diagnostics?url=${encodeURIComponent(raw)}`,{cache:'no-store'}); if(r.ok)server=await r.json(); transport=server?.lastTransport?.mode||transport; }
  }catch(_){ }
  const stalls=Number(v.__sbbBufferStalls||0);
  try{window.SBB_PLAYBACK_SESSION?.markFirstFrame?.(playbackSessionDescriptor(clip(currentIndex),{slot,transport,sourceUrl:v.currentSrc||v.getAttribute('src')||''}));}catch(_){}
  console.info('[SBB v4.3.6] native playback path', {slot,transport,firstFrameMs,stalls,cache:server?.cache||{},server:server?.lastTransport||{}});
  setPlaybackDiag({lastAction:`${transport} • first frame ${firstFrameMs}ms${stalls?` • stalls ${stalls}`:''}`});
  try{fetch(`/api/client-log?event=PLAYBACK_FIRST_FRAME&detail=${encodeURIComponent(`${transport}|${firstFrameMs}ms|stalls=${stalls}`)}`,{cache:'no-store'}).catch(()=>{});}catch(_){}
  v.__sbbAdoptedHot=false;
}

function bindNativeVideoElement(slot,v){
  if(!v || v.__sbbNativeBoundSlot===slot) return;
  v.__sbbNativeBoundSlot=slot;
  const current=()=>nativeEl(slot)===v && nativeEventMatchesClaim(slot);
  v.addEventListener('loadedmetadata',()=>{ if(current()) updateNativeDiag(slot,'loadedmetadata'); });
  v.addEventListener('canplaythrough',()=>{ if(current()) updateNativeDiag(slot,'canplaythrough'); });
  v.addEventListener('playing',()=>{
    if(!current() || slotMedia[slot] !== 'native') return;
    if(slot!==activeSlot){ v.muted=true; v.pause(); return; }
    videoReady[slot]=true;
    initialized=true;
    if(mediaInteractionUnlocked){v.muted=false; startupMutedSlots[slot]=false;}
    try{window.SBB_PLAYBACK_SESSION?.setAudible?.('video',slot,!v.muted);}catch(_){}
    activePlaybackState='native-playing';
    setPlaybackUi('playing');
    reportNativePlaybackPath(v,slot);
    try{ const currentItem=clip(currentIndex); syncGameCenterToActivePlayback(currentItem,{reason:'native PLAYING confirmed',source:'playback-confirmed'}); window.SBB_PROVIDER_HEALTH?.success?.(currentItem?.provider||currentItem?.source||'DIRECT_VIDEO'); window.SBB_MEDIA_MANIFEST?.markPlaying?.(knownMatchForMedia(currentItem)||window.SBB_SELECTED_EVENT?.get?.()||currentItem,currentItem); reportHistoricalRuntime(currentItem,'PLAYED'); }catch(_){ }
    // Native playback has no YouTube state callback. Make its visual readiness obey
    // the same bumper minimum as every other provider instead of leaving a playing
    // video (and audible audio) hidden behind the bumper indefinitely.
    const remaining=Math.max(0,bumperMinMs-(performance.now()-bumperShownAt));
    setTimeout(()=>{ if(slot===activeSlot && !v.paused){ hideBumper(); swapRequestedAt=0; } },remaining);
    updateDiagnostics();
  });
  v.addEventListener('pause',()=>{
    if(!current()) return;
    try{window.SBB_PLAYBACK_SESSION?.setAudible?.('video',slot,false);}catch(_){}
    if(slot===activeSlot && !transitionInFlight && document.visibilityState==='visible'){
      manualPauseRequested=true;
      setPlaybackUi('paused');
    }
  });
  v.addEventListener('waiting',()=>{
    if(!current()) return;
    if(slot===activeSlot && slotMedia[slot]==='native'){
      v.__sbbBufferStalls=Number(v.__sbbBufferStalls||0)+1;
      setPlaybackUi('buffering');
      try{
        const currentItem=clip(currentIndex);
        window.SBB_MEDIA_MANIFEST?.markBuffering?.(knownMatchForMedia(currentItem)||window.SBB_SELECTED_EVENT?.get?.()||currentItem,currentItem);
      }catch(_){}
    }
  });
  v.addEventListener('canplay',()=>{
    if(!current() || slotMedia[slot] !== 'native') return;
    // A standby native slot is only HOT after its muted play/rewind warm cycle
    // completes. canplay alone must not advertise an exact-click promotion yet.
    if(slot!==activeSlot && warming[slot]){ updateDiagnostics(); return; }
    videoReady[slot]=true;
    updateDiagnostics();
  });
  v.addEventListener('ended',()=>{
    if(!current() || slot!==activeSlot || slotMedia[slot] !== 'native') return;
    try{window.SBB_PLAYBACK_SESSION?.setAudible?.('video',slot,false);}catch(_){}
    setPlaybackUi('ended');
    advanceAfterCompletedItem();
  });
  v.addEventListener('error',()=>{
    if(!current() || slotMedia[slot] !== 'native') return;
    updateNativeDiag(slot,'media error');
    console.warn('[SBB playback] Native video error',slot,{error:v.error,src:v.currentSrc,readyState:v.readyState,networkState:v.networkState});
    if(slot===activeSlot) handlePlaybackFailure(slot,new Error(nativeErrorText(v)),false);
    else {
      const next=nextVisibleQueueIndex();
      if(next>=0) prepareStandby(slot,next);
    }
  });
}
function bindNativePlayers(){
  nativeBound=true;
  for(const slot of ['A','B']) bindNativeVideoElement(slot,nativeEl(slot));
}
function configurePreparedNativeSlot(slot,item,entry,active=false){
  const v=entry?.video;
  if(!v || !entry.ready || v.readyState<1) return null;
  const layer=$(`layer${slot}`), old=nativeEl(slot), host=ytHost(slot), ctx=contextEl(slot);
  if(!layer) return null;
  if(contextTimer[slot]){ clearTimeout(contextTimer[slot]); contextTimer[slot]=null; }
  if(warmTimer[slot]){ clearTimeout(warmTimer[slot]); warmTimer[slot]=null; }
  try{ players[slot]?.mute(); players[slot]?.pauseVideo(); }catch(e){}

  // Retire the old native node before publishing the new logical-slot pointer.
  // Its event handlers all check element identity, so any late events are inert.
  if(old && old!==v){
    try{ old.muted=true; old.pause(); }catch(e){}
    try{ old.removeAttribute('src'); old.load(); }catch(e){}
    try{ old.removeAttribute('id'); }catch(e){}
  }
  v.className='native-player';
  v.style.cssText='';
  v.controls=true;
  v.playsInline=true;
  v.muted=!active;
  v.dataset.sbbLogicalSlot=slot;
  v.id=`native${slot}`;
  if(old && old.parentNode===layer) old.replaceWith(v);
  else {
    const contextNode=ctx && ctx.parentNode===layer ? ctx : null;
    layer.insertBefore(v,contextNode);
  }
  nativeSlotNodes[slot]=v;
  bindNativeVideoElement(slot,v);
  slotMedia[slot]='native';
  if(ctx) ctx.classList.add('hidden');
  if(host) host.style.display='none';
  v.classList.remove('hidden');
  const epoch=claimSlot(slot,item,active?'active':'standby');
  videoReady[slot]=v.readyState>=2;
  warming[slot]=false;
  launchRequested[slot]=!!active;
  v.__sbbTuneStartedAt=performance.now(); v.__sbbPlaybackItem=item; v.__sbbAdoptedHot=true; v.__sbbBufferStalls=0;
  setPlaybackDiag({provider:'DIRECT_VIDEO',slot,state:'prepared',readyState:v.readyState,networkState:v.networkState,source:v.currentSrc||v.getAttribute('src')||'—',error:nativeErrorText(v),lastAction:'adopted hot score player'});
  return epoch;
}


function configureSlotForItem(slot,item,active=false){
  const epoch=claimSlot(slot,item,active?'active':'standby');
  const v=nativeEl(slot), host=ytHost(slot), ctx=contextEl(slot);
  if(contextTimer[slot]){ clearTimeout(contextTimer[slot]); contextTimer[slot]=null; }
  videoReady[slot]=false;
  if(isContextItem(item)){
    slotMedia[slot]='context';
    try{ players[slot]?.mute(); players[slot]?.pauseVideo(); }catch(e){}
    if(host) host.style.display='none';
    if(v){ v.pause(); v.removeAttribute('src'); try{v.load();}catch(e){} v.classList.add('hidden'); }
    if(ctx){ renderContextProgram(slot,item); ctx.classList.remove('hidden'); }
    videoReady[slot]=true;
  } else if(isNativeItem(item)){
    slotMedia[slot]='native';
    try{ players[slot]?.mute(); players[slot]?.pauseVideo(); }catch(e){}
    if(ctx) ctx.classList.add('hidden');
    if(host) host.style.display='none';
    if(v){
      v.classList.remove('hidden');
      v.pause();
      const mediaSrc=nativePlaybackUrl(item);
      if(v.getAttribute('src') !== mediaSrc){ v.__sbbTuneStartedAt=performance.now(); v.__sbbPlaybackItem=item; v.__sbbBufferStalls=0; v.setAttribute('src', mediaSrc); }
      v.preload='auto'; v.muted=!active;
      try{v.load();}catch(e){}
    }
  } else {
    slotMedia[slot]='youtube';
    if(ctx) ctx.classList.add('hidden');
    if(v){ v.pause(); v.removeAttribute('src'); try{v.load();}catch(e){} v.classList.add('hidden'); }
    if(host) host.style.display='block';
  }
  return epoch;
}

function enforceSingleAudibleSlot(){
  const inactive=otherSlot(activeSlot);
  try{ players[inactive]?.mute(); players[inactive]?.pauseVideo(); }catch(e){}
  try{ const v=nativeEl(inactive); if(v){v.muted=true;v.pause();} }catch(e){}
  try{window.SBB_PLAYBACK_SESSION?.setAudible?.('video',inactive,false);}catch(_){}
  if(contextTimer[inactive]){ clearTimeout(contextTimer[inactive]); contextTimer[inactive]=null; }
}
function currentSlotPlaying(){ try{return adapterForSlot(activeSlot).isPlaying();}catch(e){return false;} }

function waitForYouTubeSlotReady(slot,item,epoch,timeoutMs=12000){
  const started=performance.now();
  return new Promise((resolve,reject)=>{
    const check=()=>{
      if(epoch!=null && !slotClaimIsCurrent(slot,epoch,item)) return reject(new Error('Stale playback assignment'));
      if(players[slot] && playerReady[slot]) return resolve(players[slot]);
      if(performance.now()-started>=timeoutMs) return reject(new Error(`YouTube player ${slot} did not become ready`));
      setTimeout(check,75);
    };
    check();
  });
}

function startAssignedPlayback(slot,item,{userInitiated=false,reason='playback',restart=true,forceReload=false,epoch=null,startupWatchdog=true}={}){
  clearPlaybackRecovery();
  if(!sbbPlaybackAllowed({notify:userInitiated})) return Promise.resolve(false);
  if(manualPauseRequested&&!userInitiated){setPlaybackUi('paused');return Promise.resolve(false);}
  if(!sportsBigBoardStarted){
    try{ adapterForSlot(slot).pause(); }catch(_){}
    setPlaybackUi('paused');
    setPlaybackDiag({provider:providerForItem(item),slot,state:'launch-gated',error:'—',source:item?.youtubeId||item?.mediaUrl||item?.id||'—',lastAction:'waiting for launch screen play'});
    return Promise.resolve(false);
  }
  const expectedEpoch=epoch ?? slotAssignment[slot]?.epoch ?? null;
  if(expectedEpoch!=null && !slotClaimIsCurrent(slot,expectedEpoch,item)) return Promise.reject(new Error('Stale playback assignment'));
  ensurePlaybackSessionTracksAssignment(slot,item,{reason,userInitiated});
  if(startupWatchdog) armPlaybackStartupRecovery(slot,item,expectedEpoch);
  setPlaybackUi('starting');
  setPlaybackDiag({provider:providerForItem(item),slot,state:'starting',error:'—',source:item?.youtubeId||item?.mediaUrl||item?.id||'—',lastAction:reason});

  if(slotMedia[slot]==='youtube'){
    const wanted=String(item?.youtubeId||item?.id||'');
    if(!wanted){
      const err=new Error('Selected YouTube program has no video id');
      setPlaybackDiag({state:'rejected',error:err.message,lastAction:`${reason}: missing YouTube id`});
      return Promise.reject(err);
    }
    const launch=p=>{
      try{
        // v4.3.6: start every YouTube tune muted first, then restore audio in the
        // only after YouTube confirms PLAYING. Mobile Chrome is much more reliable
        // when the initial load/play
        // request is muted; unmuted loadVideoById can be silently ignored even
        // though the score-card click itself was a valid gesture.
        const restoreAudio=!!(userInitiated || mediaInteractionUnlocked);
        try{ p.mute(); startupMutedSlots[slot]=true; }catch(_){ }
        videoReady[slot]=false;
        let actual='';
        try{ actual=String(p.getVideoData?.()?.video_id||''); }catch(e){}
        if(forceReload || actual!==wanted) p.loadVideoById({videoId:wanted,startSeconds:0});
        else if(restart){ try{ p.seekTo(0,true); }catch(e){} }
        p.playVideo();
        // Keep the iframe muted until YouTube confirms PLAYING. onState() restores
        // audio after that confirmation when the user has interacted with the app.
        // This avoids converting a browser-safe muted start back into a blocked
        // audible autoplay request before the first frame exists.
        if(restoreAudio) startupMutedSlots[slot]=true;
        setPlaybackDiag({provider:'YOUTUBE',slot,state:'play-requested',error:'—',source:wanted,lastAction:`${reason}: muted-first exact YouTube play`});
        return true;
      }catch(err){
        setPlaybackDiag({state:'rejected',error:`${err?.name||'Error'}: ${err?.message||err}`,lastAction:`${reason}: YouTube start failed`});
        throw err;
      }
    };
    // The iframe API can finish a few seconds after schedule/media discovery. A
    // score click should wait for that readiness instead of immediately becoming a
    // false "Tap to play" failure while the exact player is still initializing.
    if(!players[slot] || !playerReady[slot]){
      setPlaybackDiag({provider:'YOUTUBE',slot,state:'waiting-player',error:'—',source:wanted,lastAction:`${reason}: waiting for YouTube player`});
      youtubeStartAwaitingReady[slot]=true;
      return waitForYouTubeSlotReady(slot,item,expectedEpoch,12000)
        .then(launch)
        .finally(()=>{ youtubeStartAwaitingReady[slot]=false; });
    }
    try{ return Promise.resolve(launch(players[slot])); }
    catch(err){ return Promise.reject(err); }
  }
  return adapterForSlot(slot).play(userInitiated);
}

function reconcileActiveSlot({autoplay=true,userInitiated=false,reason='active reconcile'}={}){
  const item=clip(currentIndex); if(!item) return false;
  if(autoplay && !sbbPlaybackAllowed({notify:userInitiated})) autoplay=false;
  if(manualPauseRequested&&!userInitiated)autoplay=false;
  autoplay=!!autoplay && sportsBigBoardStarted;
  enforceSingleAudibleSlot();
  const claim=slotAssignment[activeSlot];
  const reassigned=!claim || claim.key!==playbackItemKey(item);
  const epoch=reassigned ? configureSlotForItem(activeSlot,item,true) : promoteSlotClaim(activeSlot,item);
  if(autoplay){
    if(reassigned) startAssignedPlayback(activeSlot,item,{userInitiated,reason,restart:true,epoch}).catch(err=>handlePlaybackFailure(activeSlot,err,userInitiated));
    else adapterForSlot(activeSlot).play(userInitiated).catch(err=>handlePlaybackFailure(activeSlot,err,userInitiated));
  }
  return reassigned;
}
function hardSyncActiveSlot(autoplay=true){ return reconcileActiveSlot({autoplay,reason:'legacy active reconcile'}); }

function playSlot(slot,{userInitiated=false}={}){
  if(!sbbPlaybackAllowed({notify:userInitiated})) return;
  if(manualPauseRequested&&!userInitiated){setPlaybackUi('paused');return;}
  setPlaybackUi('starting');
  adapterForSlot(slot).play(false).catch(err=>{
    console.warn('[SBB playback] automatic adapter play rejected',err);
    if(slot===activeSlot) handlePlaybackFailure(slot,err,false);
  });
}

function pauseSlot(slot){ try{window.SBB_PLAYBACK_SESSION?.setAudible?.('video',slot,false);}catch(_){} adapterForSlot(slot).pause(); }

function createPlayer(slot, videoId, autoplay){
  players[slot] = new YT.Player(`player${slot}`, {
    width:'100%', height:'100%', videoId,
    playerVars:{ autoplay:0, controls:1, rel:0, playsinline:1, origin:location.origin === 'null' ? undefined : location.origin, widget_referrer:location.href },
    events:{
      onReady: e => {
        playerReady[slot] = true;
        if(slot === activeSlot){
          const item=clip(currentIndex);
          if(!item){try{e.target.mute();e.target.pauseVideo();}catch(_){}setPlaybackUi('paused');updateDiagnostics();return;}
          const existingClaim=slotAssignment[slot];
          const pendingControllerTune=!!youtubeStartAwaitingReady[slot] && !!existingClaim && existingClaim.key===playbackItemKey(item);
          // If PlaybackController is already waiting for this iframe, preserve its
          // claim/epoch. Re-configuring the slot here used to invalidate the click's
          // pending tune as "stale" at the exact moment YouTube became ready. That
          // was the root of the NFL/EPL "one more tap" loop on cold mobile players.
          const epoch=pendingControllerTune ? existingClaim.epoch : configureSlotForItem(slot,item,true);
          initialized = true;
          startPlaybackSync();
          if(sportsBigBoardStarted){
            if(pendingControllerTune){
              setPlaybackDiag({provider:'YOUTUBE',slot,state:'player-ready',error:'—',source:item?.youtubeId||item?.id||'—',lastAction:'player ready; pending controller tune retained'});
              // startAssignedPlayback() owns the pending wait and will issue the
              // muted loadVideoById/playVideo as soon as this callback returns.
            }else{
              startAssignedPlayback(slot,item,{userInitiated:false,reason:'player-ready bootstrap',restart:false,epoch})
                .then(()=>waitForFirstPlayback(slot,{timeoutMs:12000,epoch}))
                .catch(err=>handlePlaybackFailure(slot,err,false));
            }
          }else{
            try{ e.target.mute(); e.target.pauseVideo(); }catch(_){}
            setPlaybackUi('paused');
            setPlaybackDiag({provider:'YOUTUBE',slot,state:'launch-gated',error:'—',source:item?.youtubeId||item?.id||'—',lastAction:'waiting for launch screen play'});
          }
        } else prepareStandby(slot, standbyIndex);
        updateDiagnostics();
      },
      onStateChange: e => onState(slot, e),
      onError: e => onPlayerError(slot, e.data)
    }
  });
}

function onState(slot, event){
  const state = event.data;
  if(!youtubeEventMatchesClaim(slot)) return;
  const claim=slotAssignment[slot];
  const epoch=claim?.epoch;
  if(slot === activeSlot){
    activePlaybackState = state;
    const stateNames={[-1]:'unstarted',[YT.PlayerState.ENDED]:'ended',[YT.PlayerState.PLAYING]:'playing',[YT.PlayerState.PAUSED]:'paused',[YT.PlayerState.BUFFERING]:'buffering',[YT.PlayerState.CUED]:'cued'};
    setPlaybackDiag({provider:'YOUTUBE',slot,state:stateNames[state]||String(state),error:'—',lastAction:'YouTube state change'});
    syncPlaybackUiFromState(state);
  }
  if(slot === activeSlot && state === YT.PlayerState.PLAYING){
    clearPlaybackStartupRecovery();
    if(mediaInteractionUnlocked){ try{ players[slot]?.unMute(); startupMutedSlots[slot]=false; }catch(e){} }
    try{window.SBB_PLAYBACK_SESSION?.setAudible?.('video',slot,mediaInteractionUnlocked);}catch(_){}
    try{ const currentItem=clip(currentIndex); syncGameCenterToActivePlayback(currentItem,{reason:'YouTube PLAYING confirmed',source:'playback-confirmed'}); window.SBB_PROVIDER_HEALTH?.success?.(currentItem?.provider||currentItem?.source||'YOUTUBE'); window.SBB_MEDIA_MANIFEST?.markPlaying?.(knownMatchForMedia(currentItem)||window.SBB_SELECTED_EVENT?.get?.()||currentItem,currentItem); reportHistoricalRuntime(currentItem,'PLAYED'); }catch(_){ }
    videoReady[slot] = true;
    // PLAYING is the visual authority. swapRequestedAt intentionally survives across
    // transitions, so using it as a bumper gate can strand every later video behind
    // a recap card. Release the bumper after the requested minimum on every provider.
    const remaining=Math.max(0,bumperMinMs-(performance.now()-bumperShownAt));
    setTimeout(()=>{ if(slot===activeSlot && youtubeEventMatchesClaim(slot)){ hideBumper(); swapRequestedAt=0; } },remaining);
  }
  if(slot === activeSlot && (state === YT.PlayerState.PAUSED || state === YT.PlayerState.ENDED)){ try{window.SBB_PLAYBACK_SESSION?.setAudible?.('video',slot,false);}catch(_){} }
  if(slot === activeSlot && state === YT.PlayerState.ENDED) advanceAfterCompletedItem();
  if(slot !== activeSlot && state === YT.PlayerState.PLAYING){
    try{ players[slot]?.mute(); }catch(e){}
    if(warming[slot]){
      if(warmTimer[slot]) clearTimeout(warmTimer[slot]);
      warmTimer[slot] = setTimeout(() => {
        if(!slotClaimIsCurrent(slot,epoch) || slot===activeSlot || !warming[slot]) return;
        try{
          players[slot]?.pauseVideo();
          players[slot]?.seekTo(0, true);
          players[slot]?.mute();
          videoReady[slot] = true;
          warming[slot] = false;
        }catch(e){}
        warmTimer[slot]=null;
        updateDiagnostics();
      }, 350);
    }else{
      try{ players[slot]?.pauseVideo(); }catch(e){}
    }
  }
  if(slot===activeSlot && state===YT.PlayerState.PAUSED && !transitionInFlight && document.visibilityState==='visible') manualPauseRequested=true;
  updateDiagnostics();
}

function prepareStandby(slot, index){
  const item = clip(index); if(!item) return;
  videoReady[slot] = false;
  warming[slot] = true;
  launchRequested[slot]=false;
  if(warmTimer[slot]){ clearTimeout(warmTimer[slot]); warmTimer[slot]=null; }
  const epoch=configureSlotForItem(slot,item,false);

  if(isContextItem(item)){
    videoReady[slot]=true; warming[slot]=false;
  } else if(isNativeItem(item)){
    const v=nativeEl(slot);
    if(v){
      v.muted=true;
      const warm=()=>{
        if(!slotClaimIsCurrent(slot,epoch,item) || slot===activeSlot) return;
        const p=v.play();
        if(p?.then) p.then(()=>{
          if(!slotClaimIsCurrent(slot,epoch,item) || slot===activeSlot) return;
          if(warmTimer[slot]) clearTimeout(warmTimer[slot]);
          warmTimer[slot]=setTimeout(()=>{
            if(!slotClaimIsCurrent(slot,epoch,item) || slot===activeSlot || !warming[slot] || launchRequested[slot]) return;
            try{ v.pause(); v.currentTime=0; }catch(e){}
            if(!slotClaimIsCurrent(slot,epoch,item)) return;
            videoReady[slot]=true; warming[slot]=false; warmTimer[slot]=null;
            updateDiagnostics();
          },300);
        }).catch(()=>{});
      };
      if(v.readyState>=2) warm(); else v.addEventListener('canplay',warm,{once:true});
    }
  } else {
    if(!playerReady[slot]){ warming[slot]=false; return; }
    try{
      players[slot].mute();
      players[slot].loadVideoById({ videoId:item.youtubeId || item.id, startSeconds:0 });
    }catch(e){ warming[slot]=false; }
  }
  standbyIndex = (index + PROGRAM.length) % PROGRAM.length;
  updateDiagnostics();
  renderQueue();
}

function programGameIdentity(item){
  if(!item) return '';
  const lg=String(item.competitionId||item.league||'SPORTS').toUpperCase();
  if(window.SBB_MEDIA_SCOPE?.isCollection?.(item)) return `roundup:${String(item.mediaScope||'DAY_LEAGUE')}:${lg}:${String(item.collectionPeriodKey||roundupDate(item)||'')}`;
  if(isTopPlaysItem(item)) return topPlaysGroupIdentity(item);
  if(item.eventType || item.programType==='event' || item.programType==='context') return `event:${lg}:${item.eventId||item.id||item.youtubeId||''}`;
  const canonical=window.SBB_EVENT_IDENTITY?.key?.(item);
  if(canonical) return canonical;
  if(item.gamePk) return `${lg}:pk:${item.gamePk}`;
  if(item.matchId) return `${lg}:match:${item.matchId}`;
  if(item.scoreGameKey) return `score:${item.scoreGameKey}`;
  const dh=String(item.title||'').match(/\bgame\s*([12])\b/i);
  if(item.dateGameKey) return `date:${item.dateGameKey}${dh?`:g${dh[1]}`:''}`;
  if(item.gameDate && item.gameKey) return `date:${item.gameDate}::${item.gameKey}${dh?`:g${dh[1]}`:''}`;
  return item.id ? `id:${item.id}` : '';
}

function markGamePlayed(item){
  const key=programGameIdentity(item);
  if(!key) return;
  playedGameIds.add(key);
  persistPlayedGameIds();
}

function isGamePlayed(item){
  const key=programGameIdentity(item);
  return !!key && playedGameIds.has(key);
}

function nextUnplayedIndex(program, fromIndex, direction=1){
  if(!program?.length) return -1;
  const dir=direction<0?-1:1;
  for(let step=1; step<=program.length; step++){
    const idx=(fromIndex + dir*step + program.length)%program.length;
    const item=program[idx];
    if(item && !isGamePlayed(item)) return idx;
  }
  return -1;
}

function showAllCaughtUp(){
  pauseSlot(activeSlot);
  const date=playbackDateContext?.date||'';
  setFeedNote(date
    ? `All caught up for ${formatScoreDateLabel(date)} • choose another date or Return to Today`
    : `All caught up • ${playedGameIds.size} program${playedGameIds.size===1?'':'s'} watched this session`);
  setPlaybackUi('paused');
  renderQueue();
}
function continueNewlyDiscoveredDateMedia(){
  const date=playbackDateContext?.date;
  if(!date) return false;
  const refreshed=programForScoreDate(date);
  const target=refreshed.findIndex(x=>!isGamePlayed(x));
  if(target<0) return false;
  PROGRAM=refreshed;
  currentIndex=target; standbyIndex=target;
  setFeedNote(`More ${formatScoreDateLabel(date)} coverage is ready • continuing this date`);
  showBumper(target,600,'MORE FROM THIS DATE');
  PlaybackController.tuneProgramIndex(target,{userInitiated:false,reason:'new date media discovered'});
  return true;
}

function sameGameProgramItem(a,b){
  if(!a || !b) return false;
  if(isTopPlaysItem(a)||isTopPlaysItem(b)) return isTopPlaysItem(a)&&isTopPlaysItem(b)&&topPlaysGroupIdentity(a)===topPlaysGroupIdentity(b);
  if(a.eventType || b.eventType || a.programType==='event' || b.programType==='event' || a.programType==='context' || b.programType==='context') return programGameIdentity(a)===programGameIdentity(b);
  if(a.gamePk && b.gamePk && String(a.gamePk)===String(b.gamePk)) return true;
  if(a.matchId && b.matchId && String(a.matchId)===String(b.matchId)) return true;
  if(a.scoreGameKey && b.scoreGameKey && a.scoreGameKey===b.scoreGameKey) return true;
  const ad=a.dateGameKey || (a.gameDate&&a.gameKey?`${a.gameDate}::${a.gameKey}`:'');
  const bd=b.dateGameKey || (b.gameDate&&b.gameKey?`${b.gameDate}::${b.gameKey}`:'');
  if(ad && ad===bd){
    const am=String(a.title||'').match(/\bgame\s*([12])\b/i);
    const bm=String(b.title||'').match(/\bgame\s*([12])\b/i);
    if(am && bm && am[1]!==bm[1]) return false;
    return true;
  }
  return sameCanonicalGame(a,b);
}

function syncSelectedEvent(eventLike,{reason='playback',source='playback'}={}){
  if(!eventLike) return null;
  const store=window.SBB_SELECTED_EVENT;
  const current=store?.get?.()||null;
  // v4.3.6: a score-card selection owns the event. Playback may switch media
  // packages for that SAME game, but the sparse media item must never replace the
  // richer scoreboard event (teams, score, date, ESPN id, etc.). This also avoids
  // duplicate Game Center request/abort races on one user click.
  if(current && window.SBB_EVENT_IDENTITY?.same?.(current,eventLike) && current.selectionSource==='score-ribbon' && source!=='score-ribbon') return current;
  return store?.select?.(eventLike,{reason,source})||null;
}

function playbackOwnsGameCenter(item){
  if(!item||isContextItem(item)||isTopPlaysItem(item)||item.eventType)return false;
  if(window.SBB_MEDIA_SCOPE?.isCollection?.(item))return false;
  return !!(item.gamePk||item.matchId||item.eventId||item.scoreEventId||item.gameCenterEventId||item.scoreGameKey||item.dateGameKey||launchScoreMatchForItem(item));
}
function gameCenterEventForPlayback(item){
  if(!playbackOwnsGameCenter(item))return null;
  const scoreMatch=launchScoreMatchForItem(item);
  return scoreMatch?gameCenterSelectionFromScoreMatch(scoreMatch):item;
}
function syncGameCenterToActivePlayback(item=clip(currentIndex),{reason='active playback',source='playback'}={}){
  const store=window.SBB_SELECTED_EVENT;
  if(!playbackOwnsGameCenter(item)){
    store?.clear?.({reason:'active media has no game event',source});
    window.SBB_GAME_CENTER_VIEW?.clear?.('Game Center follows the active game video.');
    return null;
  }
  const eventLike=gameCenterEventForPlayback(item);
  if(!eventLike){
    store?.clear?.({reason:'active game media identity unresolved',source});
    window.SBB_GAME_CENTER_VIEW?.clear?.('Resolving the active video game…');
    return null;
  }
  return syncSelectedEvent(eventLike,{reason,source});
}
function selectedEventMatchesActivePlayback(){
  const item=clip(currentIndex),selected=window.SBB_SELECTED_EVENT?.get?.()||null;
  if(!playbackOwnsGameCenter(item))return !selected;
  const expected=gameCenterEventForPlayback(item);if(!expected||!selected)return false;
  return !!window.SBB_EVENT_IDENTITY?.same?.(selected,expected)||sameGameProgramItem(selected,expected);
}


function setScorePlaybackDate(date){
  const next=String(date||localDateISO(0)).slice(0,10);
  if(!/^\d{4}-\d{2}-\d{2}$/.test(next)) return scorePlaybackDate;
  scorePlaybackDate=next;
  SCORE_DATE_STORE?.setPlaybackDate?.(next,{notifyListeners:false});
  updateReturnTodayButton();
  return next;
}
function activatePlaybackDateContext(date,{source='date'}={}){
  const next=setScorePlaybackDate(date||scoreBrowseDate);
  playbackDateContext={date:next,source,startedAt:Date.now()};
  updateReturnTodayButton();
  return playbackDateContext;
}
function programForScoreDate(date){
  const rows=scoreMatchesForDate(date).filter(m=>scoreRibbonLeagueFilter==='ALL'||String(m.__sbbLeague||m.league||'').toUpperCase()===scoreRibbonLeagueFilter)
    .sort((a,b)=>scoreRibbonImportance(b)-scoreRibbonImportance(a)||new Date(a.date||0)-new Date(b.date||0));
  const out=[]; const seenGames=new Set();
  for(const match of rows){
    const selection=scoreCardPlaybackSelection(match,scoreCardPlayableItems(match));
    if(!selection.primary||!selection.selectionItems.length) continue;
    const gameId=scoreRibbonStableGameKey(match)||programGameIdentity(selection.primary);
    if(gameId&&seenGames.has(gameId)) continue;
    if(gameId) seenGames.add(gameId);
    for(const item of selection.selectionItems){
      if(item?.verifiedPlayable&&(item.youtubeId||item.mediaUrl)) out.push(item);
    }
  }
  return out;
}
function playDailyRoundup(date,{userInitiated=true}={}){
  date=String(date||scoreBrowseDate).slice(0,10);
  if(!sbbPlaybackAllowed({notify:userInitiated}))return false;
  const roundup=roundupMediaForScoreDate(date);if(!roundup.length)return false;
  try{window.SBB_SELECTED_EVENT?.clear?.({reason:'Silver daily roundup',source:'score-ribbon'});}catch(_){}
  userPlaybackSession=null;activatePlaybackDateContext(date,{source:'silver-roundup'});
  const dateProgram=programForScoreDate(date);PROGRAM=[...roundup,...dateProgram.filter(x=>!roundup.some(r=>playbackItemKey(r)===playbackItemKey(x)))];currentIndex=0;standbyIndex=PROGRAM.length>1?1:0;manualPauseRequested=false;visibilityResumeWanted=false;
  setFeedNote(`${formatScoreDateLabel(date)} • daily roundup`);showBumper(0,500,'DAILY ROUNDUP');
  PlaybackController.tuneProgramIndex(0,{userInitiated,reason:'Silver daily roundup'});renderQueue();return true;
}
function maybeAutoplayRoundupForDate(){
  // v4.3.6: score/date browsing is strictly non-authoritative for playback.
  // Silver roundup playback requires the dedicated recap/roundup control.
  return false;
}
function dateProgramWithSelectionFirst(date,selectionItems){
  const base=programForScoreDate(date);
  const selected=(selectionItems||[]).filter(Boolean);
  const remainder=base.filter(x=>!selected.some(sel=>String(x.id||'')===String(sel.id||'')||sameGameProgramItem(x,sel)));
  return [...selected,...remainder];
}
function resumeDateProgramAfterSelection(){
  const session=userPlaybackSession;
  userPlaybackSession=null;
  const date=session?.playbackDate||playbackDateContext?.date||scorePlaybackDate;
  if(!date){resumeGeneralProgramAfterSelection();return;}
  activatePlaybackDateContext(date,{source:'score-date'});
  // Keep the queue order the viewer already saw behind the selected game's clip(s).
  // This guarantees historical playback never falls through to today's general feed.
  let remainder=(PROGRAM||[]).slice(Math.max(1,Number(session?.selectionCount)||1)).filter(x=>x&&!isGamePlayed(x));
  if(!remainder.length) remainder=programForScoreDate(date).filter(x=>!isGamePlayed(x));
  if(!remainder.length){ showAllCaughtUp(); return; }
  PROGRAM=remainder;
  currentIndex=0; standbyIndex=0;
  setFeedNote(`Continuing ${formatScoreDateLabel(date)} • ${PROGRAM.length} program${PROGRAM.length===1?'':'s'} available`);
  showBumper(0,650,'UP NEXT FROM THIS DATE');
  PlaybackController.tuneProgramIndex(0,{userInitiated:false,reason:'continue selected date queue'});
}
async function returnToToday(){
  const today=localDateISO(0);
  await setScoreBrowseDate(today,{animate:true,hold:12000,load:true});
  activatePlaybackDateContext(today,{source:'return-today'});
  if(manualRecapAlternate) restoreManualRecapBase();
  if(userPlaybackSession) cancelUserPlaybackSession();
  const todayProgram=programForScoreDate(today);
  if(!todayProgram.length){
    pauseSlot(activeSlot);
    PROGRAM=[]; currentIndex=0; standbyIndex=0;
    setPlaybackUi('paused'); renderQueue();
    const firstGame=scoreMatchesForDate(today)[0];
    if(firstGame) syncSelectedEvent(gameCenterSelectionFromScoreMatch(firstGame),{reason:'return to today',source:'return-today'});
    setFeedNote(`You're back to Today • no playable highlights are available yet`);
    updateReturnTodayButton();
    return false;
  }
  PROGRAM=todayProgram;
  let target=PROGRAM.findIndex(x=>!isGamePlayed(x)); if(target<0) target=0;
  currentIndex=target; standbyIndex=target;
  manualPauseRequested=false; visibilityResumeWanted=false;
  setFeedNote(`Back to Today • starting today's available coverage`);
  showBumper(target,700,'RETURNING TO TODAY');
  PlaybackController.tuneProgramIndex(target,{userInitiated:true,reason:'return to today'});
  return true;
}

function beginScorePlaybackSession({matchId,resumeItem,resumeIndex,selectionCount,preparedAtClick=false,provider='',fallbackItems=[],playbackDate='',match=null}){
  const fallbacks=[...new Map((Array.isArray(fallbackItems)?fallbackItems:[])
    .filter(x=>runtimeMediaUsable(x))
    .map(x=>[playbackItemKey(x),x])).values()];
  userPlaybackSession={
    source:'score',
    matchId:String(matchId||''),
    playbackDate:String(playbackDate||scorePlaybackDate||''),
    resumeItemId:String(resumeItem?.id||''),
    resumeGameKey:programGameIdentity(resumeItem),
    resumeIndex:Number.isFinite(resumeIndex)?resumeIndex:0,
    selectionCount:Math.max(1,Number(selectionCount)||1),
    preparedAtClick:!!preparedAtClick,
    preparedPlayer:false,
    provider:String(provider||''),
    firstPlayLogged:false,
    startedAt:Date.now(),
    fallbackItems:fallbacks,
    failedMediaKeys:new Set(),
    match:match||null,
    historyRefreshAttempted:false
  };
}

function tryScoreMediaFallback(failedItem,reason='playback failure',{runtimeFailureAlreadyMarked=false}={}){
  const session=userPlaybackSession;
  if(session?.source!=='score') return false;
  const failedKey=playbackItemKey(failedItem);
  session.failedMediaKeys ||= new Set();
  if(failedKey) session.failedMediaKeys.add(failedKey);
  if(!runtimeFailureAlreadyMarked) markRuntimeMediaFailed(failedItem,reason);
  const candidate=(session.fallbackItems||[]).find(x=>{
    const key=playbackItemKey(x);
    return key && !session.failedMediaKeys.has(key) && runtimeMediaUsable(x);
  });
  if(!candidate) return false;
  const slotIndex=Math.max(0,Math.min(currentIndex,PROGRAM.length-1));
  PROGRAM[slotIndex]=candidate;
  session.provider=providerForItem(candidate);
  transitionInFlight=false;
  transitionRecoveryAttempts=0;
  clearPlaybackRecovery();
  setPlaybackUi('starting');
  showBumper(slotIndex,0,'LOADING ANOTHER VIDEO');
  try{
    fetch('/api/client-log?event=SCORE_MEDIA_FALLBACK&detail='+encodeURIComponent(`${session.matchId}|${failedKey}|${playbackItemKey(candidate)}|${reason}`),{cache:'no-store'}).catch(()=>{});
  }catch(_){ }
  queueMicrotask(()=>PlaybackController.tuneProgramIndex(slotIndex,{userInitiated:false,reason:`score media fallback: ${reason}`,restart:true}));
  return true;
}
function finalizeScorePlaybackUnavailable(item,reason='No playable recap source is available for this game right now.'){
  try{ markRuntimeMediaFailed(item,reason,{providerFailure:false}); }catch(_){ }
  clearPlaybackRecovery();
  transitionInFlight=false;
  setPlaybackUi('ready');
  setVideoLoadingOverlay(false);
  const kicker=$('bumperKicker'); if(kicker) kicker.textContent='VIDEO UNAVAILABLE';
  const subtitle=$('bumperSubtitle'); if(subtitle) subtitle.textContent=reason;
  const action=$('bumperAction'); if(action){ action.classList.add('hidden'); action.textContent=''; }
  $('bumper')?.classList.remove('hidden','needs-tap');
}

function tryHistoricalScoreMediaRecovery(failedItem,reason='historical playback failure'){
  const session=userPlaybackSession;
  const date=String(session?.playbackDate||scorePlaybackDate||'').slice(0,10);
  if(session?.source!=='score' || !date || date>=localDateISO(0) || session.historyRefreshAttempted) return false;
  const match=session.match||knownMatchForMedia(failedItem);
  if(!match) return false;
  session.historyRefreshAttempted=true;
  transitionInFlight=false;
  setPlaybackUi('starting');
  setFeedNote(`${gameLabel(match)} • refreshing historical recap source`);
  showBumper(Math.max(0,currentIndex),0,'REFRESHING RECAP');
  try{ fetch('/api/client-log?event=HISTORY_PLAYBACK_REFRESH&detail='+encodeURIComponent(`${session.matchId}|${reason}`),{cache:'no-store'}).catch(()=>{}); }catch(_){ }
  rapidHistoricalGameMedia(match,{force:true}).then(rows=>{
    if(userPlaybackSession!==session) return;
    const failed=session.failedMediaKeys||new Set();
    const pool=[...new Map([...(rows||[]),...scoreCardPlayableItems(match)]
      .filter(x=>x?.verifiedPlayable&&(x.youtubeId||x.mediaUrl))
      .map(x=>[playbackItemKey(x),x])).values()]
      .filter(x=>{const key=playbackItemKey(x);return key&&!failed.has(key)&&runtimeMediaUsable(x);});
    const resolved=scoreCardPlaybackSelection(match,pool);
    if(!resolved.primary){
      finalizeScorePlaybackUnavailable(failedItem,'Historical recap search completed, but no source could be verified for embedded playback.');
      return;
    }
    const slotIndex=Math.max(0,Math.min(currentIndex,PROGRAM.length-1));
    PROGRAM[slotIndex]=resolved.primary;
    session.fallbackItems=resolved.ranked;
    session.selectionCount=Math.max(1,resolved.selectionItems.length||1);
    session.provider=providerForItem(resolved.primary);
    clearPlaybackRecovery();
    renderScoresFromMatchesCombined(false);
    queueMicrotask(()=>PlaybackController.tuneProgramIndex(slotIndex,{userInitiated:false,reason:'historical exact-source refresh',restart:true}));
  }).catch(err=>{
    if(userPlaybackSession!==session) return;
    console.warn('[SBB history playback] exact refresh failed',err);
    finalizeScorePlaybackUnavailable(failedItem,'Historical recap refresh failed. Sports Big Board will retry this game during background indexing.');
  });
  return true;
}

function cancelUserPlaybackSession(){ userPlaybackSession=null; }
function resumeGeneralProgramAfterSelection(){
  const session=userPlaybackSession;
  userPlaybackSession=null;
  if(!GENERAL_PROGRAM?.length){ showAllCaughtUp(); return; }
  PROGRAM=[...GENERAL_PROGRAM];
  let target=-1;
  if(session?.resumeItemId) target=PROGRAM.findIndex(x=>String(x?.id||'')===session.resumeItemId);
  if(target<0 && session?.resumeGameKey) target=PROGRAM.findIndex(x=>programGameIdentity(x)===session.resumeGameKey);
  if(target<0) target=Math.min(Math.max(0,session?.resumeIndex||0),PROGRAM.length-1);
  if(target<0 || isGamePlayed(PROGRAM[target])) target=nextUnplayedIndex(PROGRAM,Math.max(-1,target-1),1);
  if(target<0){ showAllCaughtUp(); return; }
  setFeedNote(`Around the League queue resumed • ${playedGameIds.size} watched this session`);
  showBumper(target,900,'BACK TO AROUND THE LEAGUE');
  PlaybackController.tuneProgramIndex(target,{userInitiated:false,reason:'resume after score selection'});
}

const PlaybackController={
  tuneProgramIndex(targetIndex,{userInitiated=false,reason='selection',restart=true}={}){
    const item=clip(targetIndex);
    if(!item) return Promise.reject(new Error(`No program item at index ${targetIndex}`));
    try{window.SBB_PLAYBACK_SESSION?.select?.(playbackSessionDescriptor(item,{reason,userInitiated}));}catch(_){}
    const itemDate=scoreEventDate(item); if(itemDate&&!isContextItem(item)&&!isTopPlaysItem(item)&&!item.eventType) setScorePlaybackDate(itemDate);
    if(!sportsBigBoardStarted){
      currentIndex=targetIndex; standbyIndex=targetIndex;
      configureSlotForItem(activeSlot,item,true);
      renderMetadata(); renderQueue(); setPlaybackUi('paused');
      return Promise.resolve(false);
    }
    const collectionScoped=!!window.SBB_MEDIA_SCOPE?.isCollection?.(item);
    if(collectionScoped){
      // Collection/roundup media is never a single-game Game Center authority.
      // Preserve the v4.2.2 boundary explicitly inside the playback owner so a
      // Silver package cannot inherit or manufacture a selected game.
      try{window.SBB_SELECTED_EVENT?.clear?.({reason:'collection media has no Game Center event',source:'playback'});}catch(_){}
      try{window.SBB_GAME_CENTER_VIEW?.clear?.('Game Center follows the active game video.');}catch(_){}
    }else{
      syncGameCenterToActivePlayback(item,{reason,source:userInitiated?'direct-tune':'program'});
    }
    const token=++playbackSelectionToken;
    const previousActive=activeSlot;
    const standby=otherSlot(previousActive);
    const wantedKey=playbackItemKey(item);
    const standbyClaim=slotAssignment[standby];
    const standbyExact=!!(standbyClaim && standbyClaim.key===wantedKey && videoReady[standby]);
    const preparedEntry=(!standbyExact && isNativeItem(item)) ? takePreparedNativeEntry(item) : null;
    let targetSlot=(standbyExact || preparedEntry) ? standby : previousActive;
    let hotPrepared=standbyExact;

    // If the visible YouTube API has not initialized yet, retain the established
    // fallback to the other API-ready iframe. This is a cold assignment, not a
    // prepared promotion unless its exact media key matched above.
    if(!standbyExact && !preparedEntry && !isNativeItem(item) && !isContextItem(item) && !playerReady[targetSlot] && playerReady[standby]) targetSlot=standby;

    transitionInFlight=true;
    transitionRecoveryAttempts=0;
    manualPauseRequested=false;
    visibilityResumeWanted=false;
    currentIndex=targetIndex;
    standbyIndex=targetIndex;
    launchRequested[targetSlot]=true;
    if(warmTimer[targetSlot]){ clearTimeout(warmTimer[targetSlot]); warmTimer[targetSlot]=null; }
    warming[targetSlot]=false;

    let epoch=null;
    if(preparedEntry){
      epoch=configurePreparedNativeSlot(targetSlot,item,preparedEntry,true);
      hotPrepared=epoch!=null;
    }
    if(epoch==null){
      if(preparedEntry) destroyPreparedNativeEntry(preparedEntry);
      if(standbyExact) epoch=promoteSlotClaim(targetSlot,item);
      else epoch=configureSlotForItem(targetSlot,item,true);
    }
    if(standbyExact && isNativeItem(item)){
      const hotNative=nativeEl(targetSlot);
      try{ if(hotNative && hotNative.currentTime>0.03) hotNative.currentTime=0; }catch(e){}
    }
    if(userPlaybackSession?.source==='score') userPlaybackSession.preparedPlayer=!!hotPrepared;

    activeSlot=targetSlot;
    try{window.SBB_PLAYBACK_SESSION?.assign?.(playbackSessionDescriptor(item,{slot:targetSlot}));}catch(_){}
    if(previousActive!==targetSlot){
      // Silence the outgoing program immediately, but do not tear it down until
      // after the new play request is issued. Update diagnostic ownership in the
      // same synchronous step so a normal A/B handoff cannot look like duplicate
      // audible video while the provider's PAUSE callback is still in flight.
      try{ players[previousActive]?.mute(); }catch(e){}
      try{ const oldNative=nativeEl(previousActive); if(oldNative) oldNative.muted=true; }catch(e){}
      try{window.SBB_PLAYBACK_SESSION?.setAudible?.('video',previousActive,false);}catch(_){}
    }
    document.querySelectorAll('.player-layer').forEach(x=>x.classList.remove('active'));
    $(`layer${targetSlot}`)?.classList.add('active');
    renderMetadata();
    renderQueue();
    swapRequestedAt=performance.now();

    const start=startAssignedPlayback(targetSlot,item,{userInitiated,reason,restart:hotPrepared?false:restart,epoch,startupWatchdog:false});
    start.then(()=>{
      if(token!==playbackSelectionToken || !slotClaimIsCurrent(targetSlot,epoch,item)) return;
      if(previousActive!==targetSlot){
        try{ pauseSlot(previousActive); }catch(e){}
        launchRequested[previousActive]=false;
      }
      waitForFirstPlayback(targetSlot,{timeoutMs:12000,userInitiated,selectionToken:token,epoch,onTimeout:()=>{
        if(token!==playbackSelectionToken || !slotClaimIsCurrent(targetSlot,epoch,item)) return;
        // Network/iframe startup can occasionally miss the first play request even
        // though the exact media is valid. Retry the same assigned media once before
        // trying another verified package for the same game. Score-ribbon playback
        // never asks for a redundant second user gesture.
        if(transitionRecoveryAttempts<1){
          transitionRecoveryAttempts++;
          setPlaybackUi('buffering');
          startAssignedPlayback(targetSlot,item,{userInitiated,reason:`${reason}: exact-media retry`,restart:true,forceReload:true,epoch,startupWatchdog:false})
            .then(()=>waitForFirstPlayback(targetSlot,{timeoutMs:12000,userInitiated,selectionToken:token,epoch,onTimeout:()=>{
              if(token===playbackSelectionToken && slotClaimIsCurrent(targetSlot,epoch,item)){
                if(!tryScoreMediaFallback(item,'startup timeout after exact-media retry')) handlePlaybackFailure(targetSlot,new Error('Selected media did not start after retry'),userInitiated);
              }
            }}))
            .catch(err=>{ if(token===playbackSelectionToken && slotClaimIsCurrent(targetSlot,epoch,item)) handlePlaybackFailure(targetSlot,err,userInitiated); });
          return;
        }
        if(!tryScoreMediaFallback(item,'startup timeout')) handlePlaybackFailure(targetSlot,new Error('Selected media did not start'),userInitiated);
      }});
      const nextIndex=nextVisibleQueueIndex();
      if(nextIndex>=0){
        const nextStandby=otherSlot(targetSlot);
        setTimeout(()=>{ if(token===playbackSelectionToken && nextStandby!==activeSlot) prepareStandby(nextStandby,nextIndex); },450);
      }
    }).catch(err=>{ if(token===playbackSelectionToken && slotClaimIsCurrent(targetSlot,epoch,item)) handlePlaybackFailure(targetSlot,err,userInitiated); });
    return start;
  }
};
window.SBB_PLAYBACK_CONTROLLER=PlaybackController;

function advanceAfterCompletedItem(){
  const finished=clip(currentIndex);
  const wasManualRecap=!!manualRecapAlternate;
  if(wasManualRecap){
    markGamePlayed(finished);
    restoreManualRecapBase();
    const target=nextUnplayedIndex(PROGRAM,currentIndex,1);
    if(target<0){ showAllCaughtUp(); return; }
    const step=(target-currentIndex+PROGRAM.length)%PROGRAM.length;
    advance(step||1);
    return;
  }
  const nextItem=PROGRAM?.length ? PROGRAM[(currentIndex+1)%PROGRAM.length] : null;

  // A score-card selection is an explicit interrupt session. Its blue reel may
  // contain several same-game clips; once that selected game is complete, continue
  // the date-locked queue rather than falling back to today's general program.
  if(userPlaybackSession?.source==='score'){
    const selectionEnd=Math.max(0,userPlaybackSession.selectionCount-1);
    const moreSameGame=!finished?.overview && currentIndex<selectionEnd && nextItem && sameGameProgramItem(finished,nextItem);
    if(moreSameGame){
      showBumper(currentIndex+1,350,'CONTINUING HIGHLIGHT REEL');
      PlaybackController.tuneProgramIndex(currentIndex+1,{userInitiated:false,reason:'score reel continuation'});
      return;
    }
    markGamePlayed(finished);
    resumeDateProgramAfterSelection();
    return;
  }

  // A blue reel is one game-program: keep advancing only while the next clip is
  // from that same canonical game. When the reel ends, mark the game watched.
  if(!finished?.overview && nextItem && sameGameProgramItem(finished,nextItem)){
    advance(1);
    return;
  }

  // Any completed full recap, or final reel clip, completes the game. Choose the
  // next *unwatched* game instead of wrapping back to something already covered.
  markGamePlayed(finished);
  const target=nextUnplayedIndex(PROGRAM,currentIndex,1);
  if(target<0){ if(continueNewlyDiscoveredDateMedia()) return; showAllCaughtUp(); return; }
  const step=(target-currentIndex+PROGRAM.length)%PROGRAM.length;
  advance(step||1);
}

function advanceFullscreenSingleSlot(targetIndex){
  if(!initialized||transitionInFlight) return;
  if(bumperMode==='auto') showBumper(targetIndex,500); else if(bumperMode==='always') showBumper(targetIndex,1000);
  PlaybackController.tuneProgramIndex(targetIndex,{userInitiated:false,reason:'fullscreen automatic transition'});
}

function advance(direction=1){
  if(!initialized) return;
  if(transitionInFlight) return;
  let targetIndex;
  if(direction>0){
    targetIndex=nextVisibleQueueIndex();
    if(targetIndex<0){ showAllCaughtUp(); return; }
  }else{
    targetIndex=(currentIndex-1+PROGRAM.length)%PROGRAM.length;
  }
  if(document.fullscreenElement){ advanceFullscreenSingleSlot(targetIndex); return; }
  transitionInFlight=true; transitionRecoveryAttempts=0; manualPauseRequested=false;
  swapRequestedAt = performance.now();
  if(direction < 0){
    // Previous wasn't necessarily prebuffered; use bumper and explicitly cue standby.
    prepareStandby(otherSlot(activeSlot), targetIndex);
  }
  standbyIndex = targetIndex;
  const standbySlot = otherSlot(activeSlot);
  const ready = videoReady[standbySlot];
  // Auto now behaves like a real broadcast transition: show a short bumper on every
  // change, but let the next video start underneath it. If YouTube needs longer, the
  // bumper simply remains until PLAYING is confirmed. "Always" makes it a longer beat.
  if(bumperMode === 'auto') showBumper(targetIndex, 550);
  else if(bumperMode === 'always') showBumper(targetIndex, 1200);
  else if(!ready) showBumper(targetIndex, 0);
  performSwapWhenReady(standbySlot, targetIndex, performance.now());
}

function performSwapWhenReady(slot, targetIndex, started){
  const maxWait = 3200;
  if(videoReady[slot] || performance.now() - started > maxWait){
    doSwap(slot, targetIndex);
    return;
  }
  requestAnimationFrame(() => performSwapWhenReady(slot, targetIndex, started));
}

function doSwap(newActive, targetIndex){
  const oldActive = activeSlot;
  const item=clip(targetIndex);
  try{
    try{ players[oldActive]?.mute(); }catch(e){}
    pauseSlot(oldActive);
    currentIndex = targetIndex;
    activeSlot = newActive;
    // The active video and Game Center are one ownership unit. Rebind before the
    // provider starts so Next/auto-advance can never leave the previous game shown.
    syncGameCenterToActivePlayback(item,{reason:'A/B active video promotion',source:'program'});
    const claim=slotAssignment[newActive];
    const epoch=(claim && claim.key===playbackItemKey(item)) ? promoteSlotClaim(newActive,item) : configureSlotForItem(newActive,item,true);
    warming[newActive] = false;
    launchRequested[newActive]=true;
    if(warmTimer[newActive]){ clearTimeout(warmTimer[newActive]); warmTimer[newActive]=null; }
    document.querySelectorAll('.player-layer').forEach(x => x.classList.remove('active'));
    $(`layer${newActive}`)?.classList.add('active');
    setPlaybackUi('starting');
    startAssignedPlayback(newActive,item,{userInitiated:false,reason:'automatic A/B promotion',restart:false,epoch})
      .then(()=>waitForFirstPlayback(newActive,{timeoutMs:10000,epoch,onTimeout:()=>{
        if(!slotClaimIsCurrent(newActive,epoch,item)) return;
        if(transitionRecoveryAttempts<1){
          transitionRecoveryAttempts++;
          console.warn('[SBB v4.3.6] transition timeout; retrying assigned media once');
          startAssignedPlayback(newActive,item,{userInitiated:false,reason:'automatic transition retry',restart:false,epoch})
            .then(()=>waitForFirstPlayback(newActive,{timeoutMs:10000,epoch,onTimeout:()=>{ if(slotClaimIsCurrent(newActive,epoch,item)){ transitionInFlight=false; handlePlaybackFailure(newActive,new Error('Playback did not start after recovery'),false); } }}))
            .catch(err=>handlePlaybackFailure(newActive,err,false));
        }else{ transitionInFlight=false; handlePlaybackFailure(newActive,new Error('Playback did not start before timeout'),false); }
      }}))
      .catch(err=>{ if(slotClaimIsCurrent(newActive,epoch,item)) handlePlaybackFailure(newActive,err,false); });
    if(isContextItem(item)) confirmContextPlayback(newActive);
    launchRequested[oldActive]=false;
    swapCount++;
    $('swapCount').textContent = swapCount;
    const nextIndex = nextVisibleQueueIndex();
    if(nextIndex>=0) setTimeout(() => { if(oldActive!==activeSlot) prepareStandby(oldActive, nextIndex); }, 220);
    renderMetadata();
    renderQueue();
  }catch(err){
    transitionInFlight=false;
    console.error('[SBB v4.3.6] swap failure',err);
    handlePlaybackFailure(activeSlot,err,false);
  }
}


function confirmContextPlayback(slot){
  if(slot!==activeSlot || slotMedia[slot]!=='context') return false;
  if(!contextTimer[slot]) PlaybackAdapters.context(slot).play();
  launchRequested[slot]=false;
  transitionInFlight=false;
  transitionRecoveryAttempts=0;
  const remaining=Math.max(0,bumperMinMs-(performance.now()-bumperShownAt));
  setTimeout(()=>{ hideBumper(); clearPlaybackRecovery(); },remaining);
  setPlaybackUi('playing');
  return true;
}

function waitForFirstPlayback(slot, options={}){
  if(confirmContextPlayback(slot)) return;
  const startedAt = performance.now();
  const timeoutMs = options.timeoutMs ?? 5000;
  const expectedEpoch=options.epoch ?? slotAssignment[slot]?.epoch ?? null;
  const selectionToken=options.selectionToken ?? null;
  const onTimeout = options.onTimeout || (()=>handlePlaybackFailure(slot, new Error('Playback did not start before timeout'), !!options.userInitiated));
  const check = () => {
    if(selectionToken!=null && selectionToken!==playbackSelectionToken) return;
    if(expectedEpoch!=null && !slotClaimIsCurrent(slot,expectedEpoch)) return;
    if(slot !== activeSlot && options.requireActive !== false) return;
    const playing=adapterForSlot(slot).isPlaying();
    if(playing){
      clearPlaybackStartupRecovery();
      launchRequested[slot]=false;
      const ms = Math.round(performance.now() - (swapRequestedAt || startedAt));
      try{window.SBB_PLAYBACK_SESSION?.markFirstFrame?.(playbackSessionDescriptor(clip(currentIndex),{slot,transport:providerForItem(clip(currentIndex))}));}catch(_){}
      if($('lastTransition')) $('lastTransition').textContent = `${ms} ms`;
      if(userPlaybackSession?.source==='score' && !userPlaybackSession.firstPlayLogged){
        userPlaybackSession.firstPlayLogged=true;
        const detail=`${userPlaybackSession.matchId}|provider=${userPlaybackSession.provider||slotMedia[slot]}|preparedPlayer=${userPlaybackSession.preparedPlayer?1:0}|preparedAtClick=${userPlaybackSession.preparedAtClick?1:0}|startupMs=${ms}`;
        try{ fetch('/api/client-log?event=SCORE_CLICK_PLAYING&detail='+encodeURIComponent(detail),{cache:'no-store'}).catch(()=>{}); }catch(e){}
      }
      const remaining = Math.max(0, bumperMinMs - (performance.now() - bumperShownAt));
      transitionInFlight=false; transitionRecoveryAttempts=0;
      setTimeout(()=>{ hideBumper(); swapRequestedAt=0; clearPlaybackRecovery(); }, remaining);
      return;
    }
    if(performance.now() - startedAt >= timeoutMs){ onTimeout(); return; }
    setTimeout(check, 50);
  };
  check();
}

let playbackRecovery = null;
let playbackExternalFallbackUrl='';
// v4.3.6 post-first-frame stall watchdog. Startup buffering already has its own
// exact-media retry path; this watchdog is only for media that proved it could play
// and then stopped making progress. Do not restart the same clip: after a bounded
// stall, mark this runtime asset unhealthy and let the existing failure controller
// advance to the next eligible item (or same-game fallback for score-card sessions).
const PLAYBACK_BUFFER_STALL_RECOVERY_MS=8000;
const PLAYBACK_STARTUP_RECOVERY_MS=10000;
let playbackBufferRecoveryTimer=null;
let playbackBufferRecoveryToken='';
let playbackStartupRecoveryTimer=null;
let playbackStartupRecoveryToken='';
function clearPlaybackBufferRecovery(){
  if(playbackBufferRecoveryTimer) clearTimeout(playbackBufferRecoveryTimer);
  playbackBufferRecoveryTimer=null;playbackBufferRecoveryToken='';
}
function clearPlaybackStartupRecovery(){
  if(playbackStartupRecoveryTimer) clearTimeout(playbackStartupRecoveryTimer);
  playbackStartupRecoveryTimer=null;playbackStartupRecoveryToken='';
}
function ensurePlaybackSessionTracksAssignment(slot,item,{reason='playback',userInitiated=false}={}){
  const descriptor=playbackSessionDescriptor(item,{slot,reason,userInitiated});
  const key=playbackItemKey(item);
  const snap=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{};
  if(String(snap.mediaKey||'')!==key){
    try{window.SBB_PLAYBACK_SESSION?.select?.(descriptor);}catch(_){}
  }
  try{window.SBB_PLAYBACK_SESSION?.assign?.(descriptor);}catch(_){}
}
function armPlaybackStartupRecovery(slot,item,epoch){
  if(!sportsBigBoardStarted||manualPauseRequested||slot!==activeSlot||!item) return;
  const key=playbackItemKey(item),selection=playbackSelectionToken;
  const token=`${selection}|${slot}|${epoch}|${key}`;
  clearPlaybackStartupRecovery();playbackStartupRecoveryToken=token;
  playbackStartupRecoveryTimer=setTimeout(()=>{
    playbackStartupRecoveryTimer=null;
    if(playbackStartupRecoveryToken!==token||manualPauseRequested||!sportsBigBoardStarted) return;
    if(selection!==playbackSelectionToken||slot!==activeSlot||!slotClaimIsCurrent(slot,epoch,item)) return;
    const current=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{};
    if(String(current.mediaKey||'')!==key) return;
    if(current.firstFrameAt || ['playing','paused','ready','ended'].includes(String(current.state||''))) return;
    try{fetch('/api/client-log?event=PLAYBACK_STARTUP_RECOVERY&detail='+encodeURIComponent(`${key}|${PLAYBACK_STARTUP_RECOVERY_MS}ms`),{cache:'no-store'}).catch(()=>{});}catch(_){}
    handlePlaybackFailure(slot,new Error(`Playback startup did not reach first frame within ${PLAYBACK_STARTUP_RECOVERY_MS} ms`),false);
  },PLAYBACK_STARTUP_RECOVERY_MS);
}
function armPlaybackBufferRecovery(){
  if(!sportsBigBoardStarted||manualPauseRequested) return;
  const item=clip(currentIndex),snap=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{};
  // A first frame proves this is a mid-stream stall rather than ordinary startup.
  if(!item||!snap.firstFrameAt) return;
  const slot=activeSlot,key=playbackItemKey(item),selection=playbackSelectionToken,epoch=slotAssignment[slot]?.epoch??null;
  const token=`${selection}|${slot}|${epoch}|${key}`;
  if(playbackBufferRecoveryTimer&&playbackBufferRecoveryToken===token) return;
  clearPlaybackBufferRecovery();playbackBufferRecoveryToken=token;
  playbackBufferRecoveryTimer=setTimeout(()=>{
    playbackBufferRecoveryTimer=null;
    if(playbackBufferRecoveryToken!==token||manualPauseRequested||!sportsBigBoardStarted) return;
    if(selection!==playbackSelectionToken||slot!==activeSlot||!slotClaimIsCurrent(slot,epoch,item)) return;
    const current=window.SBB_PLAYBACK_SESSION?.snapshot?.()||{};
    if(String(current.mediaKey||'')!==key||String(current.state||'')!=='buffering') return;
    try{fetch('/api/client-log?event=PLAYBACK_STALL_RECOVERY&detail='+encodeURIComponent(`${key}|${PLAYBACK_BUFFER_STALL_RECOVERY_MS}ms`),{cache:'no-store'}).catch(()=>{});}catch(_){}
    handlePlaybackFailure(slot,new Error(`Sustained playback buffering > ${PLAYBACK_BUFFER_STALL_RECOVERY_MS} ms`),false);
  },PLAYBACK_BUFFER_STALL_RECOVERY_MS);
}
function clearPlaybackRecovery(){
  clearPlaybackStartupRecovery();
  clearPlaybackBufferRecovery();
  playbackRecovery = null;
  playbackExternalFallbackUrl='';
  $('bumper')?.classList.remove('needs-tap','external-fallback');
  const action=$('bumperAction'); if(action){ action.classList.add('hidden'); action.textContent=''; }
}

function handlePlaybackFailure(slot, err, userInitiated=false){
  if(slot!==activeSlot) return;
  clearPlaybackStartupRecovery();
  clearPlaybackBufferRecovery();
  transitionInFlight=false;
  try{window.SBB_PLAYBACK_SESSION?.fail?.(err,playbackSessionDescriptor(clip(currentIndex),{slot}));}catch(_){}
  const native=slotMedia[slot]==='native'?nativeEl(slot):null;
  setPlaybackDiag({provider:slotMedia[slot]==='native'?'DIRECT_VIDEO':'YOUTUBE_EMBED',slot,state:'failed',error:`${err?.name||'Error'}: ${err?.message||err}`,readyState:native?.readyState??'—',networkState:native?.networkState??'—',source:native?.currentSrc||String(clip(currentIndex)?.youtubeId||clip(currentIndex)?.id||'—'),lastAction:userInitiated?'user playback failed':'auto playback failed'});
  console.warn('[SBB playback] start failed', {slot, media:slotMedia[slot], userInitiated, err, src: native?.currentSrc||'', readyState:native?.readyState, networkState:native?.networkState, mediaError:nativeErrorText(native)});

  // A score-card click IS the user gesture. Never answer that click with another
  // "tap to play" requirement. The controller has already retried the exact asset
  // and tried other verified same-game sources. If none can start, keep Game Center
  // selected and report that the recap source is unavailable rather than looping
  // the user through an identical gesture.
  if(userPlaybackSession?.source==='score'){
    const failed=clip(currentIndex);
    // Runtime truth is recorded at the playback-failure boundary, then recovery
    // may select another verified asset from this exact game. Keeping the mark
    // here preserves the score-rail contract even as fallback internals evolve.
    markRuntimeMediaFailed(failed,err?.message||'score playback failed');
    // First prefer another already-verified same-game asset. If none exists,
    // historical score sessions get one exact-game refresh before we give up.
    if(tryScoreMediaFallback(failed,err?.message||'score playback failed',{runtimeFailureAlreadyMarked:true})) return;
    if(tryHistoricalScoreMediaRecovery(failed,err?.message||'score playback failed')) return;
    finalizeScorePlaybackUnavailable(failed,'No playable recap source is available for this game right now.');
    return;
  }

  // v4.3.6 unattended playback recovery. A decode/network/provider failure in the
  // continuous channel must never strand the board behind a TAP TO PLAY card. Mark
  // the exact media asset unusable for this runtime and move to the next eligible
  // program item. Explicit score-card sessions keep their same-game recovery rules
  // above, while user-initiated failures may still ask the viewer for a gesture.
  if(!userInitiated){
    const failed=clip(currentIndex), failedKey=playbackItemKey(failed);
    try{markRuntimeMediaFailed(failed,err?.message||'automatic playback failure');}catch(_){}
    clearPlaybackRecovery();setVideoLoadingOverlay(false);
    const next=nextVisibleQueueIndex();
    if(next>=0 && next!==currentIndex){
      setPlaybackUi('starting');showBumper(next,350,'SKIPPING UNAVAILABLE VIDEO');
      try{fetch('/api/client-log?event=AUTO_MEDIA_FAILURE_SKIP&detail='+encodeURIComponent(`${failedKey}|${err?.message||err}`),{cache:'no-store'}).catch(()=>{});}catch(_){}
      queueMicrotask(()=>PlaybackController.tuneProgramIndex(next,{userInitiated:false,reason:'automatic playback failure recovery'}));
      return;
    }
  }

  setPlaybackUi('ready');
  playbackRecovery = {slot, userInitiated};
  const kicker=$('bumperKicker'); if(kicker) kicker.textContent='VIDEO READY';
  const subtitle=$('bumperSubtitle'); if(subtitle) subtitle.textContent='The video needs one more tap to continue.';
  const action=$('bumperAction'); if(action){ action.textContent='▶ TAP TO PLAY'; action.classList.remove('hidden'); }
  $('bumper')?.classList.remove('hidden');
  $('bumper')?.classList.add('needs-tap');
}

function retryActivePlaybackFromGesture(){
  if(!playbackRecovery) return;
  const slot=activeSlot;
  const item=clip(currentIndex);
  if(!item) return;
  const epoch=slotAssignment[slot]?.epoch ?? null;
  manualPauseRequested=false;
  mediaInteractionUnlocked=true;
  setPlaybackUi('starting');

  // A recovery tap must re-issue the *exact* assigned media, not merely call
  // playVideo() on whatever state the iframe happened to be left in. On mobile,
  // YouTube can reject or ignore an earlier hidden/prewarm load even though the
  // iframe itself is ready. loadVideoById inside this click handler preserves the
  // user gesture and reliably turns the recovery card into real playback.
  if(slotMedia[slot]==='youtube'){
    const p=players[slot];
    const wanted=String(item?.youtubeId||item?.id||'');
    if(!p || !wanted){ handlePlaybackFailure(slot,new Error('Video player is not ready yet'),true); return; }
    try{
      p.unMute(); startupMutedSlots[slot]=false;
      let actual='';
      try{ actual=String(p.getVideoData?.()?.video_id||''); }catch(_){ }
      if(actual!==wanted) p.loadVideoById({videoId:wanted,startSeconds:0});
      else { try{ p.seekTo(0,true); }catch(_){ } }
      p.playVideo();
      setPlaybackDiag({provider:'YOUTUBE',slot,state:'play-requested',error:'—',source:wanted,lastAction:'recovery tap: exact YouTube reload/play'});
      clearPlaybackRecovery();
      waitForFirstPlayback(slot,{timeoutMs:15000,userInitiated:true,epoch,onTimeout:()=>handlePlaybackFailure(slot,new Error('Video still did not start after tap'),true)});
      return;
    }catch(err){ handlePlaybackFailure(slot,err,true); return; }
  }

  adapterForSlot(slot).play(true)
    .then(()=>{ clearPlaybackRecovery(); waitForFirstPlayback(slot,{timeoutMs:15000,userInitiated:true,epoch,onTimeout:()=>handlePlaybackFailure(slot,new Error('Video still did not start after tap'),true)}); })
    .catch(err=>handlePlaybackFailure(slot,err,true));
}

function showBumper(index, minMs=1200, kicker='COMING UP NEXT'){
  const item = clip(index);
  if($('bumperKicker')) $('bumperKicker').textContent = kicker;
  $('bumperLeague').textContent = item.league;
  $('bumperTitle').textContent = displayProgramTitle(item);
  $('bumperSubtitle').textContent = item.subtitle || 'Coming up next';
  const thumb = item.thumbnail || `https://i.ytimg.com/vi/${item.youtubeId || item.id}/hqdefault.jpg`;
  $('bumperThumb').src = thumb;
  $('bumperThumb').alt = `${item.title} thumbnail`;
  $('bumperBackdrop').style.backgroundImage = `linear-gradient(90deg, rgba(7,9,12,.98) 0%, rgba(7,9,12,.90) 42%, rgba(7,9,12,.48) 68%, rgba(7,9,12,.18) 100%), url(${thumb})`;
  bumperShownAt = performance.now();
  bumperMinMs = minMs;
  $('bumper').classList.remove('hidden');
}
function hideBumper(){ $('bumper').classList.add('hidden'); bumperMinMs = 0; }

function onPlayerError(slot, code){
  if(!youtubeEventMatchesClaim(slot)) return;
  console.warn('YouTube player error', slot, code);
  if(slot === activeSlot){
    const failed=clip(currentIndex);
    // Error 153 is not a bad video. It means YouTube did not receive the HTTP
    // Referer / API-client identity it now requires. v4.3.6 explicitly serves
    // strict-origin-when-cross-origin and passes origin + widget_referrer. Never
    // poison the game's media inventory for an app-level identity failure.
    if(Number(code)===153){
      try{ window.SBB_PROVIDER_HEALTH?.failure?.('YOUTUBE','embed identity 153',{cooldownMs:30000}); }catch(_){}
      setPlaybackDiag({provider:'YOUTUBE',slot,state:'referrer-blocked',error:'YouTube error 153: missing HTTP Referer',lastAction:'YouTube client identity rejected'});
      const url=failed?.externalUrl||(failed?.youtubeId?`https://www.youtube.com/watch?v=${failed.youtubeId}`:'');
      playbackExternalFallbackUrl=url;
      setPlaybackUi('ready'); setVideoLoadingOverlay(false);
      const kicker=$('bumperKicker'); if(kicker) kicker.textContent='YOUTUBE PLAYBACK BLOCKED';
      const subtitle=$('bumperSubtitle'); if(subtitle) subtitle.textContent='Refresh this Sports Big Board build to retry embedded playback.';
      const action=$('bumperAction'); if(action){ action.textContent=url?'↗ WATCH ON YOUTUBE':'REFRESH TO RETRY'; action.classList.remove('hidden'); }
      $('bumper')?.classList.remove('hidden','needs-tap'); $('bumper')?.classList.add('external-fallback');
      return;
    }
    // 101/150 are video-specific embed-policy failures. Try another verified
    // same-game package first. If none works, keep the exact official URL as an
    // external fallback instead of pretending the game itself has no highlights.
    if(!tryScoreMediaFallback(failed,`YouTube error ${code}`)){
      const url=failed?.externalUrl||(failed?.youtubeId?`https://www.youtube.com/watch?v=${failed.youtubeId}`:'');
      if((Number(code)===101||Number(code)===150)&&url){
        markRuntimeMediaFailed(failed,`YouTube error ${code}`,{providerFailure:false});
        if(tryHistoricalScoreMediaRecovery(failed,`YouTube embed-policy error ${code}`)) return;
        playbackExternalFallbackUrl=url;
        setPlaybackUi('ready'); setVideoLoadingOverlay(false);
        const kicker=$('bumperKicker'); if(kicker) kicker.textContent='WATCH ON YOUTUBE';
        const subtitle=$('bumperSubtitle'); if(subtitle) subtitle.textContent='This official recap does not allow embedded playback.';
        const action=$('bumperAction'); if(action){ action.textContent='↗ OPEN OFFICIAL HIGHLIGHTS'; action.classList.remove('hidden'); }
        $('bumper')?.classList.remove('hidden','needs-tap'); $('bumper')?.classList.add('external-fallback');
      }else handlePlaybackFailure(slot,new Error(`YouTube player error ${code}`),false);
    }
  } else {
    const next=nextVisibleQueueIndex();
    if(next>=0) prepareStandby(slot,next);
  }
}

function publishedTimeMs(item){
  const raw=item?.publishedAt || item?.postedAt || item?.datePublished || '';
  if(!raw) return 0;
  const ms=Date.parse(raw);
  return Number.isFinite(ms)?ms:0;
}
function formatRelativeAge(ms){
  if(!ms) return '';
  const diff=Math.max(0,Date.now()-ms);
  const min=Math.floor(diff/60000);
  if(min<1) return 'just now';
  if(min<60) return `${min} minute${min===1?'':'s'} ago`;
  const hr=Math.floor(min/60);
  if(hr<24) return `${hr} hour${hr===1?'':'s'} ago`;
  const day=Math.floor(hr/24);
  if(day<7) return `${day} day${day===1?'':'s'} ago`;
  const wk=Math.floor(day/7);
  return `${wk} week${wk===1?'':'s'} ago`;
}
function formatPostedLine(item){
  const ms=publishedTimeMs(item);
  if(!ms) return 'Posted time unavailable';
  const d=new Date(ms);
  const time=d.toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});
  const now=new Date();
  const sameDay=d.getFullYear()===now.getFullYear()&&d.getMonth()===now.getMonth()&&d.getDate()===now.getDate();
  const datePart=sameDay?'':`${d.toLocaleDateString([], {month:'short',day:'numeric'})} at `;
  return `Posted ${datePart}${time} • ${formatRelativeAge(ms)}`;
}
function ensureActiveSlotMatchesCurrent({autoplay=true}={}){
  return reconcileActiveSlot({autoplay:autoplay&&!manualPauseRequested,reason:'program refresh reconcile'});
}

function recapGameNumber(item){
  const text=`${item?.title||''} ${item?.subtitle||''}`;
  const m=text.match(/\b(?:game|gm)\s*([12])\b/i);
  return m?m[1]:'';
}
function canonicalTeamPair(item){
  if(!item) return '';
  const lg=String(item.competitionId||item.league||'SPORTS').toUpperCase();
  let away=String(item.away||'').trim(), home=String(item.home||'').trim();
  const gk=String(item.gameKey||'').trim();
  if((!away||!home) && gk.includes('__')){
    const parts=gk.split('__'); away=away||parts[0]||''; home=home||parts[1]||'';
  }
  if(away&&home){
    const pair=[normalizedTeamKey(away),normalizedTeamKey(home)].filter(Boolean).sort();
    if(pair.length===2) return `${lg}:${pair.join('__')}`;
  }
  if(lg==='MLB'){
    const compact=`${item.title||''} ${item.subtitle||''} ${item.description||''}`.toLowerCase().replace(/[^a-z0-9]/g,'');
    const found=[];
    const aliases=Object.entries(MLB_TEAM_ALIASES).sort((x,y)=>y[0].length-x[0].length);
    for(const [alias,code] of aliases){
      if(alias.length<3 || !compact.includes(alias) || found.includes(code)) continue;
      found.push(code);
      if(found.length===2) break;
    }
    if(found.length===2) return `${lg}:${found.sort().join('__')}`;
  }
  return '';
}
function itemGameDateMs(item){
  const raw=String(item?.gameDate||item?.date||item?.__sbbDate||'').slice(0,10);
  if(raw){ const ms=Date.parse(`${raw}T12:00:00Z`); if(Number.isFinite(ms)) return ms; }
  return publishedTimeMs(item)||0;
}
function canonicalRecapLooseKey(item){
  const pair=canonicalTeamPair(item);
  if(!pair) return '';
  const gn=recapGameNumber(item);
  return `${pair}${gn?`:g${gn}`:''}`;
}
function recapDatesCompatible(a,b){
  const am=itemGameDateMs(a), bm=itemGameDateMs(b);
  if(!am||!bm) return true;
  return Math.abs(am-bm)<=36*3600_000;
}
function sameCanonicalGame(a,b){
  if(!a||!b) return false;
  if(window.SBB_EVENT_IDENTITY?.same?.(a,b)) return true;
  const lgA=String(a.competitionId||a.league||'SPORTS').toUpperCase(), lgB=String(b.competitionId||b.league||'SPORTS').toUpperCase();
  if(lgA!==lgB) return false;
  if(a.gamePk&&b.gamePk&&String(a.gamePk)===String(b.gamePk)) return true;
  if(a.matchId&&b.matchId&&String(a.matchId)===String(b.matchId)) return true;
  const ak=canonicalRecapLooseKey(a), bk=canonicalRecapLooseKey(b);
  return !!ak && ak===bk && recapDatesCompatible(a,b);
}
function canonicalRecapMatchKey(item){
  if(!item) return '';
  const lg=String(item.competitionId||item.league||'SPORTS').toUpperCase();
  const date=String(item.gameDate||item.date||item.__sbbDate||item.publishedAt||'').slice(0,10);
  if(item.gamePk) return `${lg}:pk:${item.gamePk}`;
  const loose=canonicalRecapLooseKey(item);
  if(loose) return `${loose}:${date||'nodate'}`;
  const gk=String(item.gameKey||'').trim();
  if(date&&gk) return `${lg}:${date}:${gk}`;
  const txt=`${item.title||''} ${item.subtitle||''}`.toLowerCase();
  const tokens=txt.replace(/&amp;/g,' ').replace(/[^a-z0-9]+/g,' ').trim().split(/\s+/).filter(x=>x.length>=3);
  return `${lg}:${date||'nodate'}:${tokens.slice(0,8).sort().join('-')}`;
}
function isGoldRecap(item){ return window.SBB_MEDIA_CLASSIFIER?.commentary?.(item) ?? false; }
function recapTier(item){ return window.SBB_MEDIA_CLASSIFIER?.tier?.(item) || 'blue'; }
function scoreHighlightTypeForItem(item){ return window.SBB_MEDIA_CLASSIFIER?.scoreType?.(item) || 'clips'; }
function mediaTierLabel(tier){ return window.SBB_MEDIA_CLASSIFIER?.label?.(tier) || ''; }
function expandMediaVersions(items){
  const out=[], seen=new Set();
  const add=(x)=>{
    if(!x || !(x.youtubeId||x.mediaUrl)) return;
    const key=String(x.id||x.youtubeId||x.mediaUrl||'');
    if(key && seen.has(key)) return;
    if(key) seen.add(key);
    out.push(x);
    if(Array.isArray(x.recapAlternates)) for(const alt of x.recapAlternates) add(alt);
  };
  for(const x of (items||[])) add(x);
  return out;
}
function mediaAvailability(items){
  const list=expandMediaVersions(items);
  return {
    gold:list.some(isGoldRecap),
    green:list.some(isGreenRecap),
    extended:list.some(isExtendedRecap),
    blue:list.some(x=>recapTier(x)==='blue' && !isContextItem(x) && !!(x.youtubeId||x.mediaUrl))
  };
}
function mediaAvailabilityRail(avail){
  const order=['gold','green','extended','blue'];
  const labels={gold:'Commentary recap',green:'Quick full recap',extended:'Extended recap',blue:'Highlight reel'};
  const present=order.filter(k=>avail?.[k]);
  if(!present.length) return null;
  const rail=document.createElement('div');
  rail.className='media-availability-rail';
  rail.setAttribute('aria-hidden','true');
  rail.title=present.map(k=>labels[k]).join(' • ');
  for(const tier of present){
    const seg=document.createElement('span');
    seg.className=`media-availability-segment media-${tier}`;
    rail.appendChild(seg);
  }
  return rail;
}
function recapAlternatesFor(item){
  if(!item || !isFullRecapCandidate(item)) return [];
  const candidates=[];
  const add=(x)=>{
    if(!x || x.id===item.id || !isFullRecapCandidate(x) || !x.verifiedPlayable || !(x.youtubeId||x.mediaUrl)) return;
    if(!sameCanonicalGame(item,x)) return;
    if(!candidates.some(y=>y.id===x.id)) candidates.push(x);
  };
  for(const x of (Array.isArray(item.recapAlternates)?item.recapAlternates:[])) add(x);
  for(const x of RECAP_CANDIDATE_REGISTRY.values()) add(x);
  for(const group of ALL_GAME_CANDIDATES.values()) for(const x of group) add(x);
  candidates.sort((a,b)=>overviewQuality(b)-overviewQuality(a));
  return candidates;
}
function recapTargetForTier(item,tier){
  const alts=recapAlternatesFor(item);
  const filtered=alts.filter(x=>recapTier(x)===tier);
  if(!filtered.length) return null;
  filtered.sort((a,b)=>overviewQuality(b)-overviewQuality(a) || sourceQuality(b)-sourceQuality(a));
  return filtered[0]||null;
}
function recapAlternateTargets(item){
  if(!item || !isFullRecapCandidate(item)) return [];
  const currentTier=recapTier(item);
  const tiers=['green','extended','gold'];
  return tiers
    .filter(t=>t!==currentTier)
    .map(t=>({tier:t,target:recapTargetForTier(item,t)}))
    .filter(x=>x.target);
}
function bestRecapSwitchTarget(item){
  // Compatibility helper for queue/status code. Player controls now expose every
  // available tier, but callers that need one target receive the first semantic
  // alternate in Quick → Extended → Commentary order.
  return recapAlternateTargets(item)[0]?.target||null;
}
function updateRecapAlternateButton(){
  const wrap=$('recapAltButtons');
  const buttons={green:$('recapQuickBtn'),extended:$('recapExtendedBtn'),gold:$('recapCommentaryBtn')};
  updateCurrentRecapPairStatus();
  const item=clip(currentIndex);
  const targets=new Map(recapAlternateTargets(item).map(x=>[x.tier,x.target]));
  let shown=0;
  for(const [tier,btn] of Object.entries(buttons)){
    if(!btn) continue;
    const target=targets.get(tier)||null;
    btn.classList.remove('target-gold','target-green','target-extended','target-blue');
    if(!target){
      btn.classList.add('hidden');
      btn.removeAttribute('data-target-id');
      btn.removeAttribute('data-target-tier');
      continue;
    }
    shown++;
    btn.classList.remove('hidden');
    btn.classList.add(`target-${tier}`);
    const duration=formatDuration(recapDurationSeconds(target));
    const suffix=duration?` ${duration}`:'';
    btn.textContent=tier==='extended'?`+ EXTENDED${suffix}`:tier==='gold'?`+ COMMENTARY${suffix}`:`+ QUICK${suffix}`;
    btn.title=tier==='extended'?'Watch extended recap':tier==='gold'?'Watch commentary recap':'Watch quick/full recap';
    btn.dataset.targetId=String(target.id||'');
    btn.dataset.targetTier=tier;
  }
  if(wrap) wrap.classList.toggle('hidden',shown===0);
}
function switchRecapVersion(targetTier=null){
  const current=clip(currentIndex); if(!current) return;
  const tier=targetTier || null;
  const target=tier?recapTargetForTier(current,tier):bestRecapSwitchTarget(current);
  if(!target) return;
  if(!manualRecapAlternate) manualRecapAlternate={index:currentIndex,base:current};
  PROGRAM[currentIndex]={...target,recapAlternates:[current,...recapAlternatesFor(current).filter(x=>x.id!==target.id)]};
  renderMetadata(); renderQueue(); updateRecapAlternateButton();
  PlaybackController.tuneProgramIndex(currentIndex,{userInitiated:true,reason:`recap version selection:${recapTier(target)}`});
}

function restoreManualRecapBase(){
  if(!manualRecapAlternate) return;
  const {index,base}=manualRecapAlternate;
  if(PROGRAM && index>=0 && index<PROGRAM.length) PROGRAM[index]=base;
  manualRecapAlternate=null;
}
function renderMetadata(){
  const item = clip(currentIndex);
  if(item&&!isContextItem(item)&&!isTopPlaysItem(item)&&!item.eventType) focusScoreRibbonForGame(item,{force:false});
  document.querySelector('.stage-card')?.classList.toggle('context-active',isContextItem(item));
  $('currentLeague').textContent = isTopPlaysItem(item)?(item.editorialScope==='league'?`${String(item.competitionId||item.originalLeague||item.league||'').toUpperCase()} TOP PLAYS`:'TOP PLAYS'):item.league;
  $('currentLeague').classList.toggle('top-plays-badge',isTopPlaysItem(item));
  $('currentLeague').classList.toggle('gold-recap-badge',isGoldRecap(item));
  $('currentLeague').title=isGoldRecap(item)?'Commentary recap':'';
  $('currentTitle').textContent = displayProgramTitle(item);
  $('currentSubtitle').textContent = item.subtitle;
  if($('currentPosted')) $('currentPosted').textContent=formatPostedLine(item);
  if($('currentDuration')){
    const d=formatDuration(item?.generatedTopPlays ? item.topPlaysTotalDuration : (item.durationSeconds ?? item.duration));
    $('currentDuration').textContent=d ? `• ${d}` : '';
  }
  setPlaybackDiag({provider:providerForItem(item),slot:activeSlot,source:item.youtubeId||item.mediaUrl||item.id||'—'});
  updateRecapAlternateButton();
}

function formatDuration(seconds){
  const total=Math.round(Number(seconds)||0);
  if(total<=0) return '';
  const h=Math.floor(total/3600);
  const m=Math.floor((total%3600)/60);
  const s=total%60;
  return h>0 ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}` : `${m}:${String(s).padStart(2,'0')}`;
}

setInterval(()=>{
  const item=clip(currentIndex);
  if(item && $('currentPosted')) $('currentPosted').textContent=formatPostedLine(item);
},60000);

function aroundLeagueThumb(item){
  const league=String(item?.league||'SPORTS').toUpperCase();
  const label=`AROUND ${league}`;
  const bg=league==='MLB'?'#0f3150':league==='NFL'?'#17243a':league==='NBA'?'#2e183d':league==='NHL'?'#182a36':league==='MLS'?'#123b2d':'#182430';
  return `<div class="queue-thumb-fallback around-league-thumb" style="--atl-bg:${bg}">
    <span class="atl-mark">SBB</span>
    <strong>${escapeHtml(label)}</strong>
  </div>`;
}

function queueThumbHtml(item){
  if(isContextItem(item)){
    const league=String(item?.league||'SPORTS').toUpperCase();
    return `<div class="queue-thumb-wrap"><div class="queue-thumb-fallback context-queue-thumb">
      <span class="context-thumb-kicker">SBB</span>
      <strong>AROUND<br>${escapeHtml(league)}</strong>
      <i></i>
    </div></div>`;
  }
  const thumb=item.thumbnail || (item.youtubeId||item.id ? `https://i.ytimg.com/vi/${item.youtubeId || item.id}/mqdefault.jpg` : '');
  const fallback=escapeHtml(item.league||'SPORT');
  return `<div class="queue-thumb-wrap">${thumb?`<img src="${escapeHtml(thumb)}" alt="">`:`<div class="queue-thumb-fallback">${fallback}</div>`}</div>`;
}
function queueDurationHtml(item){
  const duration=formatDuration(item?.generatedTopPlays ? item.topPlaysTotalDuration : (item.durationSeconds ?? item.duration));
  return `<div class="queue-duration-col">${duration||'—'}</div>`;
}

function recapPairState(item){
  if(!item || !isFullRecapCandidate(item)) return {kind:'',label:'',target:null,targets:[]};
  const targets=recapAlternateTargets(item);
  if(targets.length){
    const labels=targets.map(({tier,target})=>{
      const d=formatDuration(recapDurationSeconds(target));
      const name=tier==='extended'?'EXTENDED':tier==='gold'?'COMMENTARY':'QUICK';
      return `+ ${name}${d?` ${d}`:''}`;
    });
    return {kind:'paired',label:labels.join(' • '),target:targets[0].target,targets};
  }
  if(isExtendedRecap(item)) return {kind:'searching',label:'EXTENDED ONLY • QUICK RECAP SEARCHING',target:null,targets:[]};
  return {kind:'',label:'',target:null,targets:[]};
}

function queueRecapPairHtml(item){
  const state=recapPairState(item);
  if(!state.label) return '';
  return `<em class="queue-recap-pair ${state.kind}">${escapeHtml(state.label)}</em>`;
}
function updateCurrentRecapPairStatus(){
  const el=$('currentRecapPair'); if(!el) return;
  const state=recapPairState(clip(currentIndex));
  el.textContent=state.label||'';
  el.className=`current-recap-pair ${state.kind||''} ${state.label?'':'hidden'}`;
}
function visibleQueueEntries(wanted=5){
  const queueProgram=PROGRAM||[];
  if(!queueProgram.length) return [];
  const visible=[];
  for(let step=1; step<=queueProgram.length && visible.length<wanted; step++){
    const idx=(currentIndex+step+queueProgram.length)%queueProgram.length;
    const item=queueProgram[idx]||{};
    if(isGamePlayed(item)) continue;
    if(visible.some(v=>sameGameProgramItem(v.item,item))) continue;
    visible.push({idx,item});
  }
  return visible;
}
function nextVisibleQueueIndex(){
  if(PROGRAM?.length>1){
    const current=clip(currentIndex);
    const immediate=(currentIndex+1)%PROGRAM.length;
    const next=PROGRAM[immediate];
    if(current && next && !current.overview && sameGameProgramItem(current,next) && !isGamePlayed(next)) return immediate;
  }
  return visibleQueueEntries(1)[0]?.idx ?? -1;
}

function renderQueue(){
  const list = $('queueList');
  if(!list) return;
  list.innerHTML = '';

  // A multi-clip game takeover is a mini-program of its own. Keep the visible
  // queue tied to that active game and show the currently playing clip first.
  // This prevents the queue from remaining stuck on the first clip or on the
  // previously selected game when the user jumps to another score card.
  if(userPlaybackSession?.source==='score' && userPlaybackSession.selectionCount>1 && currentIndex<userPlaybackSession.selectionCount){
    const visible=[];
    const maxItems=Math.min(7, userPlaybackSession.selectionCount-currentIndex);
    for(let n=0;n<maxItems;n++) visible.push({idx:currentIndex+n,item:PROGRAM[currentIndex+n],position:n});
    for(const entry of visible){
      const {idx,item,position}=entry;
      const row=document.createElement('div');
      row.className=`queue-item ${position===0?'next current':''}`;
      const kind=isTopPlaysItem(item)?'TOP PLAYS':(isContextItem(item)?'AROUND THE LEAGUE':(item.eventType?String(item.eventType).toUpperCase():(isGoldRecap(item)?'COMMENTARY RECAP':(isExtendedRecap(item)?'EXTENDED RECAP':(item.overview?'FULL RECAP':(item.source==='MLB Stats API'?'GAME CLIP':'HIGHLIGHT'))))));
      const provider=providerForItem(item);
      const sourceLabel=item.sourceLabel || item.source || provider;
      const stateLabel=position===0?'NOW PLAYING':'QUEUED';
      const postedText=publishedTimeMs(item)?formatRelativeAge(publishedTimeMs(item)):'';
      const postedAge=postedText?` • ${postedText}`:'';
      const reelPos=Number(item.reelIndex)||idx+1;
      const reelCount=Number(item.reelCount)||PROGRAM.length;
      row.innerHTML=`<div class="queue-num">${reelPos}</div>${queueThumbHtml(item)}<div class="queue-copy"><strong>${escapeHtml(displayProgramTitle(item))}</strong><span class="queue-meta-diagnostic">${itemMatchesFavoriteTeam(item)?'<b class="favorite-queue-badge">★ FAVORITE</b> • ':''}${escapeHtml(item.league || 'SPORT')} • ${kind} • ${escapeHtml(sourceLabel)} • ${stateLabel} • ${reelPos}/${reelCount}${postedAge}</span><span class="queue-meta-polished">${itemMatchesFavoriteTeam(item)?'<b class="favorite-queue-badge">★ FAVORITE</b>':''}${postedText?`${itemMatchesFavoriteTeam(item)?' • ':''}${escapeHtml(postedText)}`:''}</span>${queueRecapPairHtml(item)}</div>${queueDurationHtml(item)}`;
      row.onclick=()=>{ if(idx!==currentIndex) PlaybackController.tuneProgramIndex(idx,{userInitiated:true,reason:'score reel clip selection'}); };
      list.appendChild(row);
    }
    if(currentIndex>0){
      const note=document.createElement('div');
      note.className='queue-progress-note';
      note.textContent=`${currentIndex} clip${currentIndex===1?'':'s'} completed • ${Math.max(0,userPlaybackSession.selectionCount-currentIndex-1)} remaining`;
      list.appendChild(note);
    }
    return;
  }

  // A one-item game takeover has no internal queue, so show what Around the
  // League will resume with afterward.
  let queueProgram=PROGRAM, queueStart=currentIndex;
  if(!queueProgram || !queueProgram.length){
    list.innerHTML='<div class="queue-empty">Waiting for more programming…</div>';
    return;
  }
  const visible=(queueProgram===PROGRAM && queueStart===currentIndex)
    ? visibleQueueEntries(5)
    : (()=>{ const out=[]; for(let step=1;step<=queueProgram.length&&out.length<5;step++){ const idx=(queueStart+step+queueProgram.length)%queueProgram.length; const item=queueProgram[idx]||{}; if(isGamePlayed(item)) continue; if(out.some(v=>sameGameProgramItem(v.item,item))) continue; out.push({idx,item}); } return out; })();
  if(!visible.length){
    list.innerHTML=`<div class="queue-empty">All caught up • ${playedGameIds.size} program${playedGameIds.size===1?'':'s'} watched this session</div>`;
    return;
  }
  visible.forEach((entry,pos)=>{
    const {idx,item}=entry;
    const number=pos+1;
    const row=document.createElement('div'); row.className=`queue-item ${number===1?'next':''}`;
    const kind=isTopPlaysItem(item)?'TOP PLAYS':(isContextItem(item)?'AROUND THE LEAGUE':(item.eventType?String(item.eventType).toUpperCase():(isGoldRecap(item)?'COMMENTARY RECAP':(isExtendedRecap(item)?'EXTENDED RECAP':(item.overview?'FULL RECAP':(item.source==='MLB Stats API'?'GAME CLIP':'HIGHLIGHT'))))));
    const provider=providerForItem(item);
    const sourceLabel=item.sourceLabel || item.source || provider;
    const postedText=publishedTimeMs(item)?formatRelativeAge(publishedTimeMs(item)):'';
    const postedAge=postedText?` • ${postedText}`:'';
    const queueTitle=(item.generatedTopPlays&&item.topPlaysGroupTitle)?`${item.topPlaysGroupTitle} • ${item.topPlaysCount} plays`:displayProgramTitle(item);
    row.innerHTML=`<div class="queue-num">${number}</div>${queueThumbHtml(item)}<div class="queue-copy"><strong>${escapeHtml(queueTitle)}</strong><span class="queue-meta-diagnostic">${itemMatchesFavoriteTeam(item)?'<b class="favorite-queue-badge">★ FAVORITE</b> • ':''}${escapeHtml(item.league || 'SPORT')} • ${kind} • ${escapeHtml(sourceLabel)} • ${number===1?'UP NEXT':'QUEUED'}${postedAge}</span><span class="queue-meta-polished">${itemMatchesFavoriteTeam(item)?'<b class="favorite-queue-badge">★ FAVORITE</b>':''}${postedText?`${itemMatchesFavoriteTeam(item)?' • ':''}${escapeHtml(postedText)}`:''}</span>${queueRecapPairHtml(item)}</div>${queueDurationHtml(item)}`;
    row.onclick=()=>jumpTo(idx);
    list.appendChild(row);
  });
}
function jumpTo(index){
  if(manualRecapAlternate) restoreManualRecapBase();
  if(userPlaybackSession) cancelUserPlaybackSession();
  showBumper(index, bumperMode === 'always' ? 900 : 400);
  PlaybackController.tuneProgramIndex(index,{userInitiated:true,reason:'queue selection'});
}

function updateDiagnostics(){
  const slot = otherSlot(activeSlot);
  const ready = videoReady[slot];
  const status = ready ? 'HOT READY' : (warming[slot] ? 'PREBUFFERING' : 'BUFFERING');
  $('standbyState').textContent = status;
  $('standbyState').style.color = ready ? '#2ed47a' : '#f4b942';
  $('bufferStatus').textContent = `STANDBY ${slot}: ${status}`;
}


function setVideoLoadingOverlay(show,label='Loading video…'){
  const overlay=$('videoLoadingOverlay'), text=$('videoLoadingText');
  // Once a score-selected game has exhausted its playable sources, late player
  // callbacks/timeouts must not paint a contradictory "Loading video…" pill over
  // the final VIDEO UNAVAILABLE state.
  if(show && (playbackExternalFallbackUrl || $('bumper')?.classList.contains('external-fallback') || String($('bumperKicker')?.textContent||'').trim()==='VIDEO UNAVAILABLE')) show=false;
  if(text) text.textContent=label;
  if(overlay) overlay.classList.toggle('hidden',!show);
}
function soundtrackPlaybackClipKey(){
  try{
    const item=clip(currentIndex);
    if(!item) return '';
    return String(playbackItemKey(item)||item.youtubeId||item.mediaUrl||item.id||'');
  }catch(_){ return ''; }
}
function setPlaybackUi(mode){
  if(mode==='buffering') armPlaybackBufferRecovery(); else clearPlaybackBufferRecovery();
  try{
    const item=clip(currentIndex);
    window.SBB_PLAYBACK_SESSION?.transition?.(mode,playbackSessionDescriptor(item,{slot:activeSlot}));
  }catch(_){}
  try{window.SBB_SOUNDTRACK?.setPlaybackState?.(mode,soundtrackPlaybackClipKey());}catch(_){}
  const btn = $('playBtn');
  const badge = $('onAirBadge');
  if(!btn || !badge) return;

  btn.classList.remove('is-buffering');
  setVideoLoadingOverlay(mode==='buffering'||mode==='starting',mode==='buffering'?'Buffering video…':'Loading video…');
  if(mode === 'playing'){
    btn.textContent = 'Ⅱ';
    btn.setAttribute('aria-label','Pause');
    btn.title = 'Pause';
    badge.textContent = 'ON AIR';
  } else if(mode === 'paused'){
    btn.textContent = '▶';
    btn.setAttribute('aria-label','Play');
    btn.title = 'Play';
    badge.textContent = 'PAUSED';
  } else if(mode === 'buffering'){
    btn.textContent = '•••';
    btn.classList.add('is-buffering');
    btn.setAttribute('aria-label','Buffering — tap to pause');
    btn.title = 'Buffering';
    badge.textContent = 'BUFFERING';
  } else if(mode === 'ready'){
    btn.textContent = '▶';
    btn.setAttribute('aria-label','Play');
    btn.title = 'Play';
    badge.textContent = 'READY';
  } else if(mode === 'ended'){
    btn.textContent = '▶';
    btn.setAttribute('aria-label','Replay');
    btn.title = 'Replay';
    badge.textContent = 'ENDED';
  } else {
    btn.textContent = '•••';
    btn.classList.add('is-buffering');
    btn.setAttribute('aria-label','Starting playback');
    btn.title = 'Starting';
    badge.textContent = 'STARTING';
  }
}

function syncPlaybackUiFromState(state){
  if(slotMedia[activeSlot]==='context'){
    setPlaybackUi(contextTimer[activeSlot]?'playing':'ready');
    return;
  }
  if(!window.YT || !YT.PlayerState) return;
  if(state === YT.PlayerState.PLAYING) setPlaybackUi('playing');
  else if(state === YT.PlayerState.PAUSED) setPlaybackUi('paused');
  else if(state === YT.PlayerState.BUFFERING) setPlaybackUi('buffering');
  else if(state === YT.PlayerState.CUED) setPlaybackUi('ready');
  else if(state === YT.PlayerState.ENDED) setPlaybackUi('ended');
  else setPlaybackUi('starting');
}

function startPlaybackSync(){
  if(playbackSyncTimer) clearInterval(playbackSyncTimer);
  playbackSyncTimer = setInterval(() => {
    // A manual recovery card is an action-required state, not a buffering state.
    // Keep the spinner off until the user taps so the UI never says both
    // "VIDEO READY" and "Loading video…" at the same time.
    if(playbackRecovery){ setVideoLoadingOverlay(false); return; }
    if(slotMedia[activeSlot]==='context'){
      setPlaybackUi(contextTimer[activeSlot]?'playing':'ready');
      return;
    }
    if(slotMedia[activeSlot]==='native'){
      const v=nativeEl(activeSlot); if(!v) return;
      if(v.ended) setPlaybackUi('ended');
      else if(v.paused) setPlaybackUi('paused');
      else if(v.readyState<3) setPlaybackUi('buffering');
      else setPlaybackUi('playing');
      return;
    }
    const p = players[activeSlot];
    if(!p || typeof p.getPlayerState !== 'function') return;
    try{
      const state = p.getPlayerState();
      if(state !== activePlaybackState){
        activePlaybackState = state;
        syncPlaybackUiFromState(state);
      }
    }catch(e){}
  }, 250);
}

function escapeHtml(str){ return String(str ?? '').replace(/[&<>'\"]/g,c=>({ '&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;' }[c])); }

$('bumper').addEventListener('click', e => {
  if(playbackExternalFallbackUrl){
    e.preventDefault();
    window.open(playbackExternalFallbackUrl,'_blank','noopener');
    return;
  }
  if(!playbackRecovery) return;
  e.preventDefault();
  retryActivePlaybackFromGesture();
});

$('nextBtn').onclick = () => {
  if(!sbbPlaybackAllowed({notify:true})) return;
  if(userPlaybackSession?.source==='score' && currentIndex+1<userPlaybackSession.selectionCount){
    showBumper(currentIndex+1,300,'NEXT HIGHLIGHT');
    PlaybackController.tuneProgramIndex(currentIndex+1,{userInitiated:true,reason:'manual score reel next'});
    return;
  }
  if(userPlaybackSession) cancelUserPlaybackSession();
  advance(1);
};
for(const [id,tier] of [['recapQuickBtn','green'],['recapExtendedBtn','extended'],['recapCommentaryBtn','gold']]){
  const btn=$(id); if(btn) btn.onclick=()=>switchRecapVersion(tier);
}
$('prevBtn').onclick = () => {
  if(!sbbPlaybackAllowed({notify:true})) return;
  if(userPlaybackSession?.source==='score' && currentIndex>0 && currentIndex<userPlaybackSession.selectionCount){
    showBumper(currentIndex-1,300,'PREVIOUS HIGHLIGHT');
    PlaybackController.tuneProgramIndex(currentIndex-1,{userInitiated:true,reason:'manual score reel previous'});
    return;
  }
  if(userPlaybackSession) cancelUserPlaybackSession();
  advance(-1);
};
$('playBtn').onclick = () => {
  if(!sbbPlaybackAllowed({notify:true})) return;
  if(slotMedia[activeSlot]==='native'){
    const v=nativeEl(activeSlot); if(!v) return;
    if(!v.paused && !v.ended){ manualPauseRequested=true; setPlaybackUi('paused'); v.pause(); }
    else { manualPauseRequested=false; setPlaybackUi('starting'); v.muted=false; v.play().catch(()=>setPlaybackUi('ready')); }
    return;
  }
  const p = players[activeSlot]; if(!p) return;
  let state = -1;
  try{ state = p.getPlayerState(); }catch(e){}
  if(state === YT.PlayerState.PLAYING || state === YT.PlayerState.BUFFERING){ manualPauseRequested=true; setPlaybackUi('paused'); p.pauseVideo(); }
  else { manualPauseRequested=false; setPlaybackUi('starting'); p.playVideo(); }
};
$('fullscreenBtn').onclick = () => document.querySelector('.stage-card')?.requestFullscreen?.();
$('shuffleBtn').onclick = () => {
  if(userPlaybackSession){ if(GENERAL_PROGRAM?.length) PROGRAM=[...GENERAL_PROGRAM]; cancelUserPlaybackSession(); }
  for(let i=PROGRAM.length-1;i>0;i--){ const j=Math.floor(Math.random()*(i+1)); [PROGRAM[i],PROGRAM[j]]=[PROGRAM[j],PROGRAM[i]]; }
  const target=PROGRAM.findIndex(x=>!isGamePlayed(x));
  if(target<0){ showAllCaughtUp(); return; }
  currentIndex=target; jumpTo(target);
};
$('bumperToggle').onclick = () => {
  bumperMode = bumperMode === 'auto' ? 'always' : bumperMode === 'always' ? 'off' : 'auto';
  $('bumperToggle').textContent = `Bumper: ${bumperMode[0].toUpperCase()+bumperMode.slice(1)}`;
};
document.addEventListener('keydown', e => {
  if(e.code==='Space'){ e.preventDefault(); $('playBtn').click(); }
  if(e.code==='ArrowRight') $('nextBtn').click();
  if(e.code==='ArrowLeft') $('prevBtn').click();
  if(e.key.toLowerCase()==='f') $('fullscreenBtn').click();
});
document.addEventListener('visibilitychange',()=>{
  if(document.hidden){
    visibilityResumeWanted=currentSlotPlaying() && !manualPauseRequested;
    try{ players.A?.mute(); players.A?.pauseVideo(); }catch(e){}
    try{ players.B?.mute(); players.B?.pauseVideo(); }catch(e){}
    try{ const a=nativeEl('A'); if(a){a.muted=true;a.pause();} const b=nativeEl('B'); if(b){b.muted=true;b.pause();} }catch(e){}
    return;
  }
  // Returning to the tab must never wake the hidden standby slot.
  enforceSingleAudibleSlot();
  reconcileActiveSlot({autoplay:false,reason:'visibility restore'});
  if(visibilityResumeWanted && !manualPauseRequested){ setTimeout(()=>{ enforceSingleAudibleSlot(); playSlot(activeSlot); },180); }
  else setPlaybackUi('paused');
  visibilityResumeWanted=false;
});
document.addEventListener('fullscreenchange',()=>{
  // Fullscreen transitions can reorder paint/compositor timing on Android. Reassert
  // the active source and the exactly-one-audio invariant without changing pause intent.
  setTimeout(()=>{ enforceSingleAudibleSlot(); if(!manualPauseRequested && currentSlotPlaying()) setPlaybackUi('playing'); else if(manualPauseRequested) setPlaybackUi('paused'); },120);
});


// ---------------- V1.2 Highlightly MLB live-data layer ----------------
// ---------------- v1.3 Highlightly MLB live-data layer ----------------
function localDateISO(offsetDays=0){
  const d = new Date();
  d.setDate(d.getDate()+offsetDays);
  const y=d.getFullYear(), m=String(d.getMonth()+1).padStart(2,'0'), day=String(d.getDate()).padStart(2,'0');
  return `${y}-${m}-${day}`;
}



// ---------------- v1.7.16 canonical scheduled-game date ----------------
// A game's identity date is the calendar date on which it was scheduled to start
// in the HOME venue's local timezone. Completion timestamps never move the game
// into the next day's bucket. This is especially important for West Coast games,
// whose UTC timestamps routinely fall on the following calendar date.
const MLB_HOME_TIMEZONES={
  ari:'America/Phoenix', atl:'America/New_York', bal:'America/New_York', bos:'America/New_York',
  chc:'America/Chicago', chw:'America/Chicago', cin:'America/New_York', cle:'America/New_York',
  col:'America/Denver', det:'America/New_York', hou:'America/Chicago', kc:'America/Chicago',
  laa:'America/Los_Angeles', lad:'America/Los_Angeles', mia:'America/New_York', mil:'America/Chicago',
  min:'America/Chicago', nym:'America/New_York', nyy:'America/New_York', ath:'America/Los_Angeles',
  phi:'America/New_York', pit:'America/New_York', sd:'America/Los_Angeles', sf:'America/Los_Angeles',
  sea:'America/Los_Angeles', stl:'America/Chicago', tb:'America/New_York', tex:'America/Chicago',
  tor:'America/Toronto', wsh:'America/New_York'
};
function dateInTimeZone(date, timeZone){
  try{
    const parts=new Intl.DateTimeFormat('en-US',{timeZone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);
    const get=t=>parts.find(p=>p.type===t)?.value;
    const y=get('year'),m=get('month'),d=get('day');
    return y&&m&&d?`${y}-${m}-${d}`:'';
  }catch(e){return '';}
}
function canonicalScheduledGameDate(match, fallbackDate=''){
  if(match?.scheduledGameDate) return String(match.scheduledGameDate).slice(0,10);
  if(match?.__canonicalGameDate) return String(match.__canonicalGameDate).slice(0,10);
  const raw=match?.date ?? match?.startDate ?? match?.startTime ?? match?.scheduledAt ?? match?.startAt ?? match?.datetime ?? '';
  // Date-only values are already schedule dates and should never be interpreted as UTC midnight.
  if(/^\d{4}-\d{2}-\d{2}$/.test(String(raw))) return String(raw);
  const dt=new Date(raw);
  if(!Number.isFinite(dt.getTime())) return fallbackDate;
  const lg=String(match?.__sbbLeague||match?.competitionId||match?.league||'').toUpperCase();
  if(lg==='MLB'){
    // Baseball identity follows the home venue schedule day so extra-inning games
    // cannot move into tomorrow merely because they finish after local midnight.
    const home=match?.homeTeam||match?.home||{};
    const tz=MLB_HOME_TIMEZONES[normalizedTeamKey(teamAbbr(home,''))] || 'America/New_York';
    return dateInTimeZone(dt,tz) || fallbackDate;
  }
  // Other competitions are ribboned by the viewer's calendar day. This is the
  // semantics of TODAY/YESTERDAY in the UI and fixes late West Coast soccer whose
  // UTC timestamp is already the following date.
  const y=dt.getFullYear(), m=String(dt.getMonth()+1).padStart(2,'0'), d=String(dt.getDate()).padStart(2,'0');
  return `${y}-${m}-${d}`;
}
function canonicalizeMatchBuckets(yesterdayRaw,todayRaw,yesterday,today){
  const all=[
    ...responseItems(yesterdayRaw).map(x=>({...x,__sourceQueryDate:yesterday})),
    ...responseItems(todayRaw).map(x=>({...x,__sourceQueryDate:today}))
  ];
  const byId=new Map();
  for(const m0 of all){
    const canonical=canonicalScheduledGameDate(m0,m0.__sourceQueryDate);
    const m={...m0,scheduledGameDate:canonical,__canonicalGameDate:canonical,__sbbDate:canonical,
      __sbbDay:canonical===yesterday?'yesterday':canonical===today?'today':'other'};
    const away=m.awayTeam||m.away||{}, home=m.homeTeam||m.home||{};
    const sc=scoreFromMatch(m);
    const id=String(m.id ?? m.matchId ?? m.eventId ?? '');
    const fallbackKey=`${canonical}|${gameKey(teamAbbr(away,''),teamAbbr(home,''))}|${sc.away}-${sc.home}|${String(m.date||'')}`;
    const key=id?`id:${id}`:`fallback:${fallbackKey}`;
    // Prefer the copy from the query whose requested day matches the canonical date.
    const prev=byId.get(key);
    if(!prev || (m.__sourceQueryDate===canonical && prev.__sourceQueryDate!==canonical)) byId.set(key,m);
  }
  const values=[...byId.values()];
  return {
    yesterdayMatches:values.filter(m=>m.__sbbDate===yesterday),
    todayMatches:values.filter(m=>m.__sbbDate===today)
  };
}
function canonicalMatchDateMaps(matches){
  const byMatchId=new Map(), byGameKey=new Map();
  const counts=new Map();
  for(const m of matches){
    const away=m.awayTeam||m.away||{}, home=m.homeTeam||m.home||{};
    const key=gameKey(teamAbbr(away,''),teamAbbr(home,''));
    counts.set(key,(counts.get(key)||0)+1);
    const id=String(m.id ?? m.matchId ?? m.eventId ?? '');
    if(id) byMatchId.set(id,m.__sbbDate||m.scheduledGameDate||'');
    if(!byGameKey.has(key)) byGameKey.set(key,m.__sbbDate||m.scheduledGameDate||'');
  }
  return {byMatchId,byGameKey,counts};
}
function applyCanonicalDatesToCandidates(candidates,matches){
  const maps=canonicalMatchDateMaps(matches);
  return candidates.map(item=>{
    let date='';
    if(item.matchId && maps.byMatchId.has(String(item.matchId))) date=maps.byMatchId.get(String(item.matchId));
    else if(item.gameKey && (maps.counts.get(item.gameKey)||0)===1) date=maps.byGameKey.get(item.gameKey)||'';
    if(!date) return item;
    const scoreSuffix=item.scoreGameKey?.split('::').slice(-1)[0] || '';
    return {...item,gameDate:date,dateGameKey:`${date}::${item.gameKey}`,
      scoreGameKey:scoreSuffix?`${date}::${item.gameKey}::${scoreSuffix}`:item.scoreGameKey};
  });
}

async function apiJson(url,options={}){
  // Preserve RequestInit. v2.9.0 silently converted historical POST discovery
  // into GET /api/history/event/discover, which is a POST-only route.
  const init={cache:'no-store',...(options||{})};
  const r = await fetch(url, init);
  let body;
  try{ body = await r.json(); }catch(e){ body = {}; }
  const remaining=r.headers.get('X-SBB-RateLimit-Remaining');
  const limit=r.headers.get('X-SBB-RateLimit-Limit');
  if(remaining!==null && remaining!=='') apiQuota.remaining=Number(remaining);
  if(limit!==null && limit!=='') apiQuota.limit=Number(limit);
  updateQuotaUi();
  if(!r.ok) throw Object.assign(new Error(body.message || body.error || `HTTP ${r.status}`), {status:r.status, body});
  return body;
}
async function apiJsonTimed(url,timeoutMs=10000,options={}){
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),Math.max(500,Number(timeoutMs||10000)));
  try{ return await apiJson(url,{...(options||{}),signal:controller.signal}); }
  catch(err){ if(err?.name==='AbortError') throw Object.assign(new Error(`TIMEOUT ${url}`),{code:'TIMEOUT'}); throw err; }
  finally{ clearTimeout(timer); }
}


function setCoverageStep(id,state){
  const el=$(id); if(!el) return;
  el.classList.remove('active','done','error');
  if(state) el.classList.add(state);
}
function renderCoverage(state={}){
  coverageState={...coverageState,...state};
  if(typeof scoreBrowseDate!=='undefined' && scoreBrowseDate<localDateISO(0) && !state.__historical){
    if(typeof renderHistoricalDateDiagnostics==='function')renderHistoricalDateDiagnostics(scoreBrowseDate);
    return;
  }
  const st=String(coverageState.status||'STARTING').toUpperCase();
  const head=$('coveragePipeline')?.querySelector('.coverage-head strong');
  if(head){
    head.textContent=`MEDIA: ${st}`;
    head.classList.remove('good','bad','degraded');
    if(st==='READY') head.classList.add('good');
    else if(st==='ERROR') head.classList.add('bad');
    else if(st==='DEGRADED') head.classList.add('degraded');
  }
  const summary=$('coverageSummary');
  if(summary) summary.textContent=coverageState.message || (
    ['SEARCHING','REFRESHING'].includes(st) ? `Refreshing MLB coverage ${coverageState.searched||0}/${coverageState.total||0}` :
    st==='YOUTUBE' ? `Searching trusted YouTube/broadcaster coverage ${coverageState.youtubeSearched||0}` :
    st==='VALIDATING' ? 'Checking candidate video sources…' :
    st==='READY' ? 'Highlight discovery complete for this refresh' :
    st==='DEGRADED' ? 'Discovery completed with one or more provider failures' :
    st==='ERROR' ? 'Highlight discovery stopped unexpectedly' : 'Preparing highlight discovery…'
  );
  const detail=$('coverageDetail');
  if(detail) detail.textContent=`${coverageState.completed||0} completed • ${coverageState.recapGames||0} full recaps • ${coverageState.reelGames||0} highlight reels • ${coverageState.playableGames||0} playable games • ${coverageState.missingGames||0} missing • YouTube ${coverageState.youtubeFound||0} found/${coverageState.youtubeSearched||0} searched • ${coverageState.sourceErrorGames||0} source-degraded games • ${coverageState.playbackFailures||0} playback failures`;

  const searchDone=['YOUTUBE','VALIDATING','READY','DEGRADED','ERROR'].includes(st);
  setCoverageStep('coverageCache', coverageState.cacheLoaded ? 'done' : (['STARTING','REFRESHING','SEARCHING'].includes(st)?'active':'done'));
  setCoverageStep('coverageScores','done');
  setCoverageStep('coverageHighlightly', coverageState.highlightlyDone===false ? 'active' : 'done');
  setCoverageStep('coverageMlb', ['SEARCHING','REFRESHING'].includes(st) ? 'active' : (searchDone?'done':null));
  setCoverageStep('coverageYoutube', st==='YOUTUBE' ? 'active' : (coverageState.youtubeDone ? 'done' : (!coverageState.youtubeConfigured && searchDone ? 'error' : null)));
  setCoverageStep('coverageValidate', st==='VALIDATING' ? 'active' : (['READY','DEGRADED'].includes(st)?'done':(st==='ERROR'?'error':null)));
  setCoverageStep('coverageReady', st==='READY'?'done':(st==='DEGRADED'?'error':(st==='ERROR'?'error':null)));
}
async function applyCoverageSnapshot(date, revision){
  if(coverageApplyBusy || !coverageContext || revision===coverageAppliedRevision) return;
  coverageApplyBusy=true;
  try{
    const payload=await apiJson(`/api/mlb/stats-highlights?date=${encodeURIComponent(date)}`);
    const ctx=coverageContext;
    if(!ctx || ctx.yesterday!==date) return;
    const yCandidates=normalizeMlbStatsHighlights(responseItems(payload));
    const candidates=preferGameOverviews([...ctx.fastCandidates,...yCandidates,...(ctx.todayStatsCandidates||[])]);
    indexHighlightsByMatch(candidates);
    renderLeagueScores('MLB',ctx.yesterdayMatches,ctx.todayMatches);
    if(candidates.length){ mergeLiveProgram(candidates,ctx.first); liveFeedLoaded=true; }
    setApiCounts([...ctx.yesterdayMatches,...ctx.todayMatches], ctx.todayItems.length+ctx.yesterdayItems.length+yCandidates.length+(ctx.todayStatsCandidates||[]).length, candidates);
    updateFeedSummary(candidates);
    coverageAppliedRevision=revision;
  }catch(e){
    console.warn('Coverage snapshot apply failed',e);
  }finally{ coverageApplyBusy=false; }
}

async function pollCoverage(date, token){
  if(coveragePollTimer) clearInterval(coveragePollTimer);
  const run=async()=>{
    try{
      const payload=await apiJson(`/api/mlb/coverage-status?date=${encodeURIComponent(date)}`);
      if(token!==backgroundLoadToken) return;
      const state=payload.data||payload;
      renderCoverage(state);
      const st=String(state.status||'').toUpperCase();
      const rev=Number(state.revision||0);
      if(rev!==coverageAppliedRevision && ['REFRESHING','SEARCHING','YOUTUBE','READY','DEGRADED'].includes(st)) applyCoverageSnapshot(date,rev);
      if(['READY','DEGRADED','ERROR'].includes(st) && !state.jobRunning && coveragePollTimer){ clearInterval(coveragePollTimer); coveragePollTimer=null; }
    }catch(e){ console.warn('Coverage status poll failed',e); }
  };
  await run();
  coveragePollTimer=setInterval(run,700);
}

function historicalForegroundActive(){
  return String(scoreBrowseDate||'').slice(0,10) < localDateISO(0);
}

async function initLiveData(){
  if(FORCE_BLUE_TEST){
    document.documentElement.classList.add('force-blue-test');
    const mediaStatus=document.getElementById('mediaStatus');
    if(mediaStatus) mediaStatus.textContent='FORCE BLUE TEST';
  }
  try{
    const status = await (window.__SBB_BOOT_STATUS_PROMISE__ || apiJson('/api/status'));
    apiConfigured = !!status.highlightlyConfigured;
    const editorRail=$('editorRailStatus');
    if(editorRail){
      if(status.openaiConfigured){
        editorRail.textContent='Editor: OpenAI configured';
        apiJson('/api/editorial/verify').then(v=>{ editorRail.textContent=v?.ok?'Editor: OpenAI ready':'Editor: OpenAI check failed'; }).catch(()=>{ editorRail.textContent='Editor: OpenAI check failed'; });
      } else {
        editorRail.textContent='Editor: deterministic rules';
      }
    }
    if(status.rateLimit){
      if(status.rateLimit.remaining!=="" && status.rateLimit.remaining!=null) apiQuota.remaining=Number(status.rateLimit.remaining);
      if(status.rateLimit.limit!=="" && status.rateLimit.limit!=null) apiQuota.limit=Number(status.rateLimit.limit);
      updateQuotaUi();
    }
    // Key Info is an independent editorial lane. It must initialize on a fresh PC
    // even if Highlightly is slow, rate-limited, or not configured on this machine.
    refreshKeyInformation(true);
    refreshDailyTopPlays(true);
    refreshMediaPrewarmStatus();
    setInterval(refreshMediaPrewarmStatus,30000);
    setInterval(()=>refreshKeyInformation(false),60000);
    setInterval(()=>refreshDailyTopPlays(false),60000);
    if(!apiConfigured){
      setDataStatus('SETUP NEEDED', false);
      setFeedNote('Demo queue active • add Highlightly key, then restart');
      return;
    }
    setDataStatus('CONNECTING', null);
    await refreshLiveData(true);
    
setInterval(() => {
      // A selected historical date owns foreground network/search capacity.
      // Today refresh resumes automatically when the viewer returns to Today.
      if(historicalForegroundActive()) return;
      if(highlightlyRateLimited) refreshFallbackData(false);
      else refreshLiveData(false);
    }, 60_000);
  }catch(e){
    console.warn('Live data init failed',e);
    setDataStatus('OFFLINE', false);
    setFeedNote('Live data unavailable • playback fallback queue active');
  }
}

function responseItems(payload){
  if(Array.isArray(payload)) return payload;
  if(payload && Array.isArray(payload.data)) return payload.data;
  if(payload && payload.data && Array.isArray(payload.data.data)) return payload.data.data;
  return [];
}

async function refreshLiveData(first=false){
  if(!apiConfigured) return;
  if(!first && historicalForegroundActive()) return;
  const today = localDateISO(0);
  const yesterday = localDateISO(-1);
  try{
    // v1.7.1: render the useful part first. Scores + Highlightly are quick; MLB's
    // per-game content crawl is intentionally background work and must not block UI.
    const [matchesToday, matchesYesterday, highlightsToday, highlightsYesterday] = await Promise.all([
      apiJson(`/api/mlb/matches?date=${encodeURIComponent(today)}`),
      apiJson(`/api/mlb/matches?date=${encodeURIComponent(yesterday)}`),
      apiJson(`/api/mlb/highlights?date=${encodeURIComponent(today)}`).catch(()=>({data:[]})),
      apiJson(`/api/mlb/highlights?date=${encodeURIComponent(yesterday)}`).catch(()=>({data:[]}))
    ]);

    const {todayMatches,yesterdayMatches}=canonicalizeMatchBuckets(matchesYesterday,matchesToday,yesterday,today);
    LAST_YESTERDAY_MATCHES=yesterdayMatches;
    const todayItems = responseItems(highlightsToday);
    const yesterdayItems = responseItems(highlightsYesterday);
    const normalizedFast=normalizeHighlights([
      ...todayItems.map(x=>({...x,__sbbDate:today})),
      ...yesterdayItems.map(x=>({...x,__sbbDate:yesterday}))
    ]);
    const fastCandidates = preferGameOverviews(applyCanonicalDatesToCandidates(normalizedFast,[...yesterdayMatches,...todayMatches]));

    indexHighlightsByMatch(fastCandidates);
    renderLeagueScores('MLB',yesterdayMatches, todayMatches);
    const mlbAll=[...yesterdayMatches,...todayMatches];
    updateSportFeedState('MLB',{
      status:mlbAll.some(isLive)?'live':(mlbAll.length?'ok':'empty'),
      games:mlbAll.length, eligible:mlbAll.filter(isHighlightEligible).length,
      live:mlbAll.filter(isLive).length, final:mlbAll.filter(isFinal).length,
      scheduled:mlbAll.filter(x=>!isLive(x)&&!isFinal(x)).length, highlights:fastCandidates.length
    });
    setApiCounts(mlbAll, todayItems.length + yesterdayItems.length, fastCandidates);
    if(fastCandidates.length){
      mergeLiveProgram(fastCandidates, first);
      liveFeedLoaded=true;
    }
    renderSportFeedDiagnostics();
    renderCoverage({status:'SEARCHING',message:'Scores loaded • searching highlight sources…',completed:yesterdayMatches.filter(isFinal).length,highlightlyDone:true});
    setFeedNote('Scores live • loading MLB game recaps in background…');
    lastLiveRefresh = Date.now();
    refreshQuotaFromStatus();

    // Attach richer MLB content after the ribbon is already usable.
    loadMlbContentBackground({today,yesterday,todayMatches,yesterdayMatches,todayItems,yesterdayItems,fastCandidates,first});
    // v1.9.1: NBA/NFL/NHL share the same ribbon, queue, player, and watched-game state.
    refreshOtherSports(first);
    refreshRapidMlbHighlights(today,FORCE_BLUE_TEST);
    refreshRapidMlbHighlights(yesterday,FORCE_BLUE_TEST);
  }catch(e){
    console.warn('Live refresh failed',e);
    if(e.status===401 || e.status===403){
      setDataStatus('KEY ERROR', false);
      setFeedNote('Highlightly rejected the API key • check shared key');
    } else if(e.status===429){
      highlightlyRateLimited = true;
      updateQuotaUi();
      setDataStatus('RATE LIMITED', false);
      setFeedNote('Highlightly free quota exhausted • using MLB fallback data');
      await refreshFallbackData(first);
    } else {
      setDataStatus('OFFLINE', false);
      setFeedNote('Highlightly unavailable • using MLB fallback data');
      await refreshFallbackData(first);
    }
  }
}


let lastOtherSportsRefresh=0;
let otherSportsHaveLiveGames=false;
let otherSportsNeedTransitionRefresh=false;
function fullTeamName(team){
  return String(team?.name||team?.displayName||team?.shortName||team?.abbreviation||'').trim();
}
function teamAliasesForVideo(team){
  const raw=[team?.displayName,team?.name,team?.shortName,team?.abbreviation,team?.abbr].filter(Boolean);
  const out=new Set();
  for(const v of raw){
    const n=normTeamText(v); if(n.length>=3) out.add(n);
    const compact=n.replace(/\b(?:fc|sc|cf|afc|the)\b/g,' ').replace(/\s+/g,' ').trim(); if(compact.length>=3) out.add(compact);
  }
  return [...out];
}
function videoMentionsTeam(text,team){
  const hay=normTeamText(text);
  return teamAliasesForVideo(team).some(alias=>alias && (hay===alias || hay.includes(alias) || (alias.length<=5 && new RegExp(`(?:^|\\s)${alias.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\$&')}(?:$|\\s)`).test(hay))));
}
function associateMlsOfficialRows(rows,matches,date){
  const eligible=(matches||[]).filter(isHighlightEligible).filter(m=>String(m.__sbbDate||m.date||'').slice(0,10)===date);
  const out=[];
  for(const row of rows||[]){
    const text=`${row.title||''} ${row.description||''}`;
    const scored=[];
    for(const m of eligible){
      const away=m.awayTeam||m.away||{}, home=m.homeTeam||m.home||{};
      const a=videoMentionsTeam(text,away), h=videoMentionsTeam(text,home);
      if(a&&h) scored.push([100,m]);
      else if(a||h){
        // Official MLS often titles rapid goal clips with only the scoring club/player.
        // A one-team match is safe when that team appears in only one eligible match today.
        const team=a?away:home;
        const occurrences=eligible.filter(x=>videoMentionsTeam(fullTeamName(x.awayTeam||x.away||{}),team)||videoMentionsTeam(fullTeamName(x.homeTeam||x.home||{}),team)).length;
        if(occurrences===1) scored.push([55,m]);
      }
    }
    scored.sort((a,b)=>b[0]-a[0]); const m=scored[0]?.[1]; if(!m) continue;
    const away=m.awayTeam||m.away||{}, home=m.homeTeam||m.home||{};
    out.push({...row,__sbbDate:date,__sbbLeague:'MLS',matchId:String(m.id??m.matchId??m.eventId??''),
      scoreGameKey:`${date}::${gameKey(teamAbbr(away,''),teamAbbr(home,''))}`,gameKey:gameKey(teamAbbr(away,''),teamAbbr(home,'')),gameDate:date,
      away:fullTeamName(away),home:fullTeamName(home),association:'mls-official-channel'});
  }
  return out;
}
async function refreshMlsOfficialVideos(matches){
  if(historicalForegroundActive()) return [];
  const dates=[...new Set((matches||[]).filter(isHighlightEligible).map(m=>String(m.__sbbDate||m.date||'').slice(0,10)).filter(Boolean))];
  const found=[];
  for(const date of dates){
    try{
      const payload=await apiJson(`/api/mls/official-videos?date=${encodeURIComponent(date)}`);
      found.push(...associateMlsOfficialRows(responseItems(payload),matches,date));
    }catch(e){ console.warn('[SBB v4.3.6] MLS official-channel discovery failed',e); }
  }
  if(found.length){
    const existing=[...(LIVE_CANDIDATES_BY_LEAGUE.get('MLS')||[])];
    const combined=preferGameOverviews([...existing,...found]);
    LIVE_CANDIDATES_BY_LEAGUE.set('MLS',combined);
    indexHighlightsByMatch(combined); mergeLiveProgram(combined,false);
  }
  return found;
}

async function rapidEnrichOtherSport(league, matches, candidates,{force=false}={}){
  if(historicalForegroundActive()) return [];
  const candidateKeys=new Set((candidates||[]).filter(x=>x?.verifiedPlayable).map(candidateGroupKey).filter(Boolean));
  const missing=(matches||[]).filter(isHighlightEligible).filter(m=>{
    const away=m.awayTeam||m.away||{}, home=m.homeTeam||m.home||{};
    const id=String(m.id??m.matchId??m.eventId??'');
    const keys=[`${league}:match:${id}`, `${league}:${String(m.__sbbDate||m.date||'').slice(0,10)}::${gameKey(teamAbbr(away,''),teamAbbr(home,''))}`];
    return !keys.some(k=>candidateKeys.has(k));
  }).slice(0,3); // cap searches per league/refresh; server cache is five minutes
  const found=[];
  for(const m of missing){
    if(historicalForegroundActive()) break;
    const away=m.awayTeam||m.away||{}, home=m.homeTeam||m.home||{};
    const date=String(m.__sbbDate||m.date||localDateISO(0)).slice(0,10);
    const an=fullTeamName(away), hn=fullTeamName(home); if(!an||!hn) continue;
    try{
      const rapidEventId=String(m.espnEventId||m.scoreEventId||m.eventId||m.matchId||m.id||'');
      const payload=await apiJson(`/api/rapid-team-videos?league=${encodeURIComponent(league)}&date=${encodeURIComponent(date)}&away=${encodeURIComponent(an)}&home=${encodeURIComponent(hn)}&eventId=${encodeURIComponent(rapidEventId)}${force?'&refresh=1':''}`);
      const rows=responseItems(payload).map(x=>({...x,__sbbDate:date,__sbbLeague:league,matchId:String(m.id??m.matchId??m.eventId??''),
        scoreGameKey:`${date}::${gameKey(teamAbbr(away,''),teamAbbr(home,''))}`,gameKey:gameKey(teamAbbr(away,''),teamAbbr(home,'')),gameDate:date}))
        .filter(x=>mediaMatchesScoreGame(x,m));
      found.push(...rows);
    }catch(e){ console.warn(`[SBB v4.3.6] ${league} rapid team-video search failed`,e); }
  }
  if(found.length){
    const external=found.filter(x=>x?.externalOnly&&x?.externalUrl);
    if(external.length) EXTERNAL_CANDIDATES_BY_LEAGUE.set(league,external);
    const chosen=preferGameOverviews(found);
    const existing=[...(LIVE_CANDIDATES_BY_LEAGUE.get(league)||[])];
    const combined=[...existing,...chosen];
    indexHighlightsByMatch(combined); mergeLiveProgram(combined,false);
    return chosen;
  }
  return [];
}


const SBB_SOCCER_SNAPSHOT_PREFIX='sbb:soccer:snapshot:';
function saveSoccerSnapshot(league,yesterdayMatches,todayMatches){
  try{
    localStorage.setItem(`${SBB_SOCCER_SNAPSHOT_PREFIX}${league}`,JSON.stringify({
      savedAt:Date.now(),yesterday:yesterdayMatches||[],today:todayMatches||[]
    }));
  }catch(_){}
}
function loadSoccerSnapshot(league){
  try{
    const x=JSON.parse(localStorage.getItem(`${SBB_SOCCER_SNAPSHOT_PREFIX}${league}`)||'null');
    if(!x||!Array.isArray(x.today)||!Array.isArray(x.yesterday)) return null;
    return x;
  }catch(_){ return null; }
}


async function soccerScoreJson(league,date){
  // Use the server's ESPN scoreboard proxy and carry the browser clock so ESPN
  // UTC timestamps are bucketed into the same TODAY/YESTERDAY dates the user sees.
  const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone||'Etc/UTC';
  const utcOffsetMinutes=-new Date().getTimezoneOffset();
  const clientDate=localDateISO(0);
  const url=`/api/espn/scoreboard?league=${encodeURIComponent(league)}&date=${encodeURIComponent(date)}&timezone=${encodeURIComponent(timezone)}&clientDate=${encodeURIComponent(clientDate)}&utcOffsetMinutes=${encodeURIComponent(utcOffsetMinutes)}`;
  const r=await fetch(url,{cache:'no-store'});
  const text=await r.text();
  let data=null;
  try{ data=text?JSON.parse(text):{}; }catch(_){ data={raw:text}; }
  if(!r.ok){
    const detail=data?.error||data?.message||data?.raw||`${r.status} ${r.statusText}`;
    const err=new Error(`ESPN scoreboard HTTP ${r.status}: ${String(detail).slice(0,180)}`);
    err.status=r.status; err.detail=detail;
    throw err;
  }
  return data||{};
}


async function nearestSoccerMatchday(soccerKey,league,today){
  // Soccer schedules are much less dense than MLB. If the normal TODAY /
  // YESTERDAY pages are empty, find the closest useful matchday rather than
  // presenting a healthy-but-empty league.
  const offsets=[-2,1,-3,2,-4,3,-5,4];
  for(const offset of offsets){
    const d=localDateISO(offset);
    try{
      const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone||'Etc/UTC';
      const utcOffsetMinutes=-new Date().getTimezoneOffset();
      const clientDate=localDateISO(0);
      const payload=await apiJson(`/api/sports/${soccerKey}/matches?date=${encodeURIComponent(d)}&timezone=${encodeURIComponent(timezone)}&clientDate=${encodeURIComponent(clientDate)}&utcOffsetMinutes=${encodeURIComponent(utcOffsetMinutes)}`);
      const rows=responseItems(payload);
      if(rows.length){
        return {
          date:d,
          day:offset<0?'recent':'upcoming',
          rows:rows.map(x=>({...x,__sbbLeague:league,__sbbDate:d,__sbbDay:offset<0?'recent':'upcoming'}))
        };
      }
    }catch(_){}
  }
  return null;
}


async function refreshSoccerDiagnostics(league,date){
  if(!document.body.classList.contains('dev-mode')) return;
  try{
    const d=await apiJson(`/api/soccer/diagnostics?league=${encodeURIComponent(league)}&date=${encodeURIComponent(date)}`);
    const state=sportFeedState.get(league)||{};
    state.diagnostic=d?.ok
      ? `SOCCER ${date} raw ${d.rawCount} → filter ${d.filteredCount} → norm ${d.normalizedCount}`
      : `SOCCER DIAG ${d?.error||'unavailable'}`;
    sportFeedState.set(league,state);
    renderSportFeedStatus();
    console.info('[SBB soccer diagnostics]',league,d);
  }catch(err){
    console.warn('[SBB soccer diagnostics]',league,err);
  }
}


// ---------------- v4.3.6 arbitrary-date score/media discovery ----------------
const HISTORICAL_MEDIA_DISCOVERY_CONCURRENCY=3;
const historicalDateDiscoveryStates=new Map();
let historicalDiscoveryPollTimer=null;
let historicalDiscoveryPollGeneration=0;
let historicalDiagnosticsRendering=false;
function historicalDiscoveryState(date){ return historicalDateDiscoveryStates.get(String(date||'').slice(0,10))||null; }
function stopHistoricalDiscoveryPolling(){
  historicalDiscoveryPollGeneration++;
  if(historicalDiscoveryPollTimer){clearTimeout(historicalDiscoveryPollTimer);historicalDiscoveryPollTimer=null;}
}
function setHistoricalCoverageLabels(on){
  const labels=on
    ? {coverageCache:'DATE CACHE',coverageScores:'SCORES',coverageHighlightly:'EVENT CATALOG',coverageMlb:'OFFICIAL / ESPN',coverageYoutube:'OFFICIAL CHANNELS',coverageValidate:'VERIFY',coverageReady:'READY'}
    : {coverageCache:'CACHE',coverageScores:'SCORES',coverageHighlightly:'HIGHLIGHTLY',coverageMlb:'MLB SEARCH',coverageYoutube:'YOUTUBE / LOCAL',coverageValidate:'VIDEO CHECK',coverageReady:'READY'};
  for(const [id,label] of Object.entries(labels)){const el=$(id);if(el)el.textContent=label;}
}
function historicalInventoryFromBrowser(date){
  const matches=scoreMatchesForDate(date), media=scoreMediaForDate(date);
  const leagues={}; let games=0,completedGames=0,playableGames=0,mediaItems=0;
  const tiers={green:0,extended:0,gold:0,blue:0};
  for(const lg of ENABLED_LIVE_LEAGUES){
    const lm=matches.filter(x=>String(x.__sbbLeague||x.competitionId||x.league||'').toUpperCase()===lg);
    const lmedia=media.filter(x=>String(x.__sbbLeague||x.competitionId||x.league||'').toUpperCase()===lg);
    const finals=lm.filter(isFinal); let covered=0;
    for(const m of finals){if(scoreCardPlayableItems(m).length)covered++;}
    const lt={green:0,extended:0,gold:0,blue:0};
    for(const item of lmedia){
      if(!item?.verifiedPlayable||!(item.youtubeId||item.mediaUrl))continue;
      const t=String(item.recapTier||window.SBB_MEDIA_CLASSIFIER?.tier?.(item)||'blue');
      const k=['green','extended','gold','blue'].includes(t)?t:'blue'; lt[k]++; tiers[k]++;
    }
    leagues[lg]={games:lm.length,completed:finals.length,playableGames:covered,mediaItems:lmedia.length,tiers:lt};
    games+=lm.length;completedGames+=finals.length;playableGames+=covered;mediaItems+=lmedia.length;
  }
  return {date,games,completedGames,playableGames,mediaItems,tiers,leagues};
}
function renderHistoricalDateDiagnostics(date,stateOverride=null){
  date=String(date||scoreBrowseDate).slice(0,10);
  if(!date||date>=localDateISO(0)||historicalDiagnosticsRendering)return;
  historicalDiagnosticsRendering=true;
  try{
    const state=stateOverride||historicalDiscoveryState(date)||{};
    const serverInv=state.inventory||{};
    const browserInv=historicalInventoryFromBrowser(date);
    const inv=(Number(serverInv.games||0)||Number(serverInv.mediaItems||0))?serverInv:browserInv;
    const leagueInv=inv.leagues||browserInv.leagues||{};
    let healthy=0,totalGames=0;
    for(const lg of ENABLED_LIVE_LEAGUES){
      const info=leagueInv[lg]||browserInv.leagues?.[lg]||{}; const el=$(`feed${lg}`);
      const games=Number(info.games||0), finals=Number(info.completed||0), playable=Number(info.playableGames||0), media=Number(info.mediaItems||0);
      totalGames+=games; healthy++;
      if(el){
        el.className=`sport-feed-chip ${games?'ok':'empty'}`;
        const label=el.querySelector('span'), detail=el.querySelector('small');
        if(label)label.textContent=games?(finals?`${finals} FINAL`:`${games} GAMES`):'NO GAMES';
        if(detail)detail.textContent=`${games} games • ${playable} playable • ${media} catalog`;
      }
    }
    const summary=$('sportFeedSummary');
    if(summary)summary.textContent=`HISTORY ${formatScoreDateLabel(date)} • ${totalGames} games • ${Number(browserInv.playableGames||0)}/${Number(inv.completedGames||browserInv.completedGames||0)} ribbon-ready`;
    const calls=$('sportCallSummary');
    if(calls){
      const searched=Number(state.searchedGames||0), total=Number(state.totalGames||inv.completedGames||0);
      calls.textContent=state.running?`HISTORY SEARCH ${searched}/${total}`:`HISTORY ${String(state.status||'CACHE').toUpperCase()} • ${searched}/${total}`;
    }
    const mobile=$('mobileLiveSummary');
    if(mobile)mobile.textContent=`${Number(inv.completedGames||browserInv.completedGames||0)} highlight-eligible • ${Number(inv.playableGames||browserInv.playableGames||0)} playable games • ${Number(inv.archivedOnlyMedia||0)} external/unverified`;
    const historyLabel=`HISTORY: ${formatScoreDateLabel(date)}`;
    const data=$('dataStatus');
    if(data){data.textContent=historyLabel;data.classList.remove('bad');data.classList.add('good');}
    const mobileData=$('mobileDataStatus');
    if(mobileData){mobileData.textContent=historyLabel;mobileData.style.color='#7bf1a9';}
    const apiRail=$('apiRailStatus');
    if(apiRail)apiRail.textContent=historyLabel;
    setHistoricalCoverageLabels(true);
    const st=String(state.status||(state.running?'SEARCHING':'CACHE')).toUpperCase();
    const head=$('coveragePipeline')?.querySelector('.coverage-head strong');
    if(head){head.textContent=`MEDIA: ${st==='QUEUED'?'SEARCHING':st}`;head.classList.remove('good','degraded','bad');if(st==='READY')head.classList.add('good');else if(st==='DEGRADED')head.classList.add('degraded');else if(st==='ERROR')head.classList.add('bad');}
    const searched=Number(state.searchedGames||0), total=Number(state.totalGames||inv.completedGames||0);
    const prewarm=$('mediaPrewarmStatus');
    const ytBudget=state.youtubeSearchBudget||{};
    const gateway=state.youtubeGateway||{};
    const laneState=(name,label)=>{
      const wait=Number(gateway?.[name]?.cooldownSeconds||0);
      return `${label} ${wait>0?`WAIT ${Math.max(1,Math.ceil(wait/60))}m`:'OK'}`;
    };
    const ytText=state.youtubeConfigured
      ? ` • ${laneState('playlistitems','YT UPLOADS')} • ${laneState('activities','YT RECENT')} • ${laneState('videos','VERIFY')} • SEARCH RESCUE ${Number(ytBudget.used||0)}/${Number(ytBudget.limit||0)}${Number(gateway?.search?.cooldownSeconds||0)>0?' WAIT':''}`
      : ' • YouTube API not configured';
    if(prewarm)prewarm.textContent=`HISTORY DB • ${Number(inv.playableMedia||0)} verified assets • ${Number(inv.candidateMedia||0)} candidates • RIBBON ${Number(browserInv.playableGames||0)}/${Number(inv.completedGames||browserInv.completedGames||0)} ready • CATALOG ${Number(inv.catalogCompleteGames||0)}/${Number(inv.completedGames||browserInv.completedGames||0)} exhausted • QUALITY ${Number(inv.qualityCompleteGames||0)}/${Number(inv.completedGames||browserInv.completedGames||0)} gold${inv.needsUpgrade?` • ${Number(inv.upgradeEligibleGames||0)} upgrades pending`:''}${inv.upgradeDue?' • UPGRADE DUE':''} • ${searched}/${total} games indexed${ytText}`;
    const cs=state.currentGame?` • ${state.currentGame}`:'';
    const covSummary=$('coverageSummary');
    if(covSummary)covSummary.textContent=state.running?`${formatScoreDateLabel(date)} • finding and upgrading historical packages ${searched}/${total}${cs}`:`${formatScoreDateLabel(date)} • historical media ${st.toLowerCase()}${inv.needsUpgrade?' • Gold/Green/Purple upgrades remain eligible':''}`;
    const t=inv.tiers||browserInv.tiers||{};
    const detail=$('coverageDetail');
    if(detail)detail.textContent=`${Number(inv.completedGames||0)} completed • ${Number(inv.playableGames||0)} playable games • ${Number(t.green||0)} quick • ${Number(t.extended||0)} extended • ${Number(t.gold||0)} commentary • ${Number(t.blue||0)} clips/reels • ${Number(inv.candidateMedia||0)} candidates`;
    setCoverageStep('coverageCache','done');setCoverageStep('coverageScores',Number(inv.games||0)||!state.running?'done':'active');
    setCoverageStep('coverageHighlightly',state.running?'active':'done');setCoverageStep('coverageMlb',state.running?'active':'done');
    setCoverageStep('coverageYoutube',state.running?'active':'done');setCoverageStep('coverageValidate',state.running?'active':'done');
    setCoverageStep('coverageReady',st==='READY'?'done':(st==='ERROR'?'error':(st==='DEGRADED'?'error':null)));
  }finally{historicalDiagnosticsRendering=false;}
}
async function refreshHistoricalDiscoverySnapshot(date,{hydrate=true}={}){
  const payload=await apiJson(`/api/history/discovery?date=${encodeURIComponent(date)}`);
  const state=payload?.state||{}; historicalDateDiscoveryStates.set(date,state);
  if(hydrate){await hydrateScoreDateFromHistory(date);if(scoreBrowseDate===date)renderScoresFromMatchesCombined(false);}
  if(scoreBrowseDate===date)renderHistoricalDateDiagnostics(date,state);
  return state;
}
function scheduleHistoricalDiscoveryPoll(date,generation,delay=700){
  if(generation!==historicalDiscoveryPollGeneration)return;
  if(historicalDiscoveryPollTimer)clearTimeout(historicalDiscoveryPollTimer);
  historicalDiscoveryPollTimer=setTimeout(async()=>{
    if(generation!==historicalDiscoveryPollGeneration||scoreBrowseDate!==date)return;
    try{
      const state=await refreshHistoricalDiscoverySnapshot(date,{hydrate:true});
      if(state?.running||['QUEUED','SEARCHING'].includes(String(state?.status||'').toUpperCase()))scheduleHistoricalDiscoveryPoll(date,generation,850);
      else historicalDiscoveryPollTimer=null;
    }catch(err){console.warn('[SBB v4.3.6] historical discovery poll failed',date,err);scheduleHistoricalDiscoveryPoll(date,generation,1800);}
  },delay);
}
async function startHistoricalDateDiscovery(date,{force=false}={}){
  date=String(date||'').slice(0,10);if(!date||date>=localDateISO(0))return null;
  stopHistoricalDiscoveryPolling(); const generation=historicalDiscoveryPollGeneration;
  try{
    const payload=await fetch('/api/history/discover',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date,deep:true,force}),cache:'no-store'}).then(async r=>{const b=await r.json().catch(()=>({}));if(!r.ok)throw Object.assign(new Error(b.message||b.error||`HTTP ${r.status}`),{status:r.status});return b;});
    const state=payload?.state||{}; historicalDateDiscoveryStates.set(date,state);
    if(scoreBrowseDate===date){await hydrateScoreDateFromHistory(date);renderScoresFromMatchesCombined(false);renderHistoricalDateDiagnostics(date,state);}
    scheduleHistoricalDiscoveryPoll(date,generation,state?.running?450:1100);
    return state;
  }catch(err){
    console.warn('[SBB v4.3.6] historical discovery start failed',date,err);
    const state={date,status:'ERROR',running:false,lastError:String(err?.message||err)};historicalDateDiscoveryStates.set(date,state);
    if(scoreBrowseDate===date)renderHistoricalDateDiagnostics(date,state);
    return state;
  }
}
const historicalMediaSearchJobs=new Map();
const historicalMediaSearchQueue=[];
let historicalMediaSearchActive=0;
function historicalMediaSearchKey(match){ return scoreRibbonStableGameKey(match)||`${String(match?.__sbbLeague||match?.league||'SPORTS').toUpperCase()}:${scoreEventDate(match)}:${String(match?.id||match?.matchId||match?.eventId||'')}`; }
function persistHistoricalMediaSnapshot(league,date,items){
  if(!date || date>=localDateISO(0) || !Array.isArray(items)) return;
  try{
    fetch('/api/history/media',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date,league,items}),cache:'no-store'}).catch(()=>{});
  }catch(_){ }
}
function ingestCompactCatalogPlans(payload,date){
  if(!payload?.eventPlans||typeof payload.eventPlans!=='object') return 0;
  let count=0;
  for(const [key,plan] of Object.entries(payload.eventPlans)){
    CATALOG_EVENT_PLANS.set(key,plan); count++;
    const lg=String(plan?.league||key.split(':')[0]||'').toUpperCase(), ev=plan?.event||{};
    const aliases=[plan?.eventId,ev?.scoreEventId,ev?.espnEventId,ev?.gameCenterEventId,ev?.matchId,ev?.gamePk,ev?.eventId,ev?.id].filter(x=>x!==undefined&&x!==null&&String(x)!=='');
    for(const id of aliases) CATALOG_EVENT_PLANS.set(`${lg}:${String(id)}`,plan);
    const playable=[...(plan?.playable||[])].map(x=>({...x,__sbbDate:date,__sbbLeague:lg,competitionId:lg,league:lg,canonicalEventKey:x?.canonicalEventKey||plan?.canonicalEventKey||key,__sbbCatalogExact:true}));
    if(playable.length) storeScoreDateMedia(lg,date,playable,{append:true});
  }
  return count;
}
async function hydrateHistoricalRibbonFromCatalog(date){
  try{
    const payload=await apiJsonTimed(`/api/history/ribbon?date=${encodeURIComponent(date)}`,6500);
    HISTORICAL_SCORE_LOAD_ERRORS.delete(date);
    let games=0;
    const rowsByLeague=payload?.scoreRowsByLeague||{};
    for(const lg of ENABLED_LIVE_LEAGUES){
      const rows=Array.isArray(rowsByLeague?.[lg])?rowsByLeague[lg]:null;
      if(rows===null) continue;
      storeScoreDateLeague(lg,date,rows); games+=rows.length;
    }
    ingestCompactCatalogPlans(payload,date);
    if(payload?.timing){
      console.info('[SBB v4.3.6] historical ribbon timing',date,payload.timing,`games=${Number(payload?.scoreGameCount||games)}`,`plans=${Number(payload?.catalogEventCount||0)}`);
    }
    if(payload?.scoreInventoryComplete){
      for(const lg of ENABLED_LIVE_LEAGUES){
        if(!SCORE_DATE_STORE?.hasLeagueMatchesSnapshot?.(date,lg)) storeScoreDateLeague(lg,date,[]);
      }
    }
    if(scoreBrowseDate===date) renderScoresFromMatchesCombined(false);
    return {ok:true,games:Number(payload?.scoreGameCount||games),scoreInventoryComplete:!!payload?.scoreInventoryComplete,catalogEventCount:Number(payload?.catalogEventCount||0),timing:payload?.timing||null};
  }catch(err){
    HISTORICAL_SCORE_LOAD_ERRORS.set(date,String(err?.message||err||'Historical ribbon unavailable'));
    console.warn('[SBB v4.3.6] compact historical ribbon failed',date,err);
    return {ok:false,games:0,scoreInventoryComplete:false,error:err};
  }
}

async function hydrateScoreDateFromHistory(date,{scores=true}={}){
  try{
    // v4.3.6: historical UI hydration is composed from the bounded date-scoped
    // contracts. The legacy /api/history/day aggregate can be expensive because it
    // materializes every league's catalog media; it is no longer on the UI path.
    const [ribbon,roundups,discovery]=await Promise.all([
      apiJsonTimed(`/api/history/ribbon?date=${encodeURIComponent(date)}`,6500),
      apiJsonTimed(`/api/history/roundups?date=${encodeURIComponent(date)}&league=ALL`,6500),
      apiJsonTimed(`/api/history/discovery?date=${encodeURIComponent(date)}`,6500)
    ]);
    const payload={...ribbon,roundups:Array.isArray(roundups?.media)?roundups.media:[],discoveryState:discovery?.state||null,leagues:{}};
    ingestCompactCatalogPlans(payload,date);
    HISTORICAL_SCORE_LOAD_ERRORS.delete(date);
    const leagues=payload?.leagues||{}; let any=false; let catalogGames=0;
    const catalogRowsByLeague=new Map();
    if(Array.isArray(payload?.roundups)){ROUNDUPS_BY_DATE.set(date,payload.roundups);if(payload.roundups.length)any=true;}
    // Explicit canonical score rows are the first-class ribbon contract. They are
    // intentionally independent from the larger event/media plan payload.
    if(scores&&payload?.scoreRowsByLeague&&typeof payload.scoreRowsByLeague==='object'){
      for(const lg of ENABLED_LIVE_LEAGUES){
        const rows=Array.isArray(payload.scoreRowsByLeague[lg])?payload.scoreRowsByLeague[lg]:null;
        if(rows===null) continue;
        storeScoreDateLeague(lg,date,rows); catalogGames+=rows.length;
        if(rows.length) any=true;
      }
    }
    if(payload?.eventPlans&&typeof payload.eventPlans==='object'){
      for(const [key,plan] of Object.entries(payload.eventPlans)){
        CATALOG_EVENT_PLANS.set(key,plan);
        const lg=String(plan?.league||key.split(':')[0]||'').toUpperCase(), ev=plan?.event||{};
        const aliases=[plan?.eventId,ev?.scoreEventId,ev?.espnEventId,ev?.gameCenterEventId,ev?.matchId,ev?.gamePk,ev?.eventId,ev?.id].filter(x=>x!==undefined&&x!==null&&String(x)!=='');
        for(const id of aliases)CATALOG_EVENT_PLANS.set(`${lg}:${String(id)}`,plan);
        if(Array.isArray(plan?.media)&&plan.media.length)any=true;
        // Compatibility fallback for an older backend during a rolling deploy.
        if(scores&&!SCORE_DATE_STORE?.hasLeagueMatchesSnapshot?.(date,lg)&&ENABLED_LIVE_LEAGUES.includes(lg)&&ev&&typeof ev==='object'&&Object.keys(ev).length){
          const row={...ev};
          if(row.id===undefined||row.id===null||String(row.id)==='') row.id=String(plan?.eventId||'');
          if(row.eventId===undefined||row.eventId===null||String(row.eventId)==='') row.eventId=String(plan?.eventId||row.id||'');
          if(!row.date&&!row.gameDate) row.date=date;
          const rows=catalogRowsByLeague.get(lg)||[]; rows.push(row); catalogRowsByLeague.set(lg,rows);
        }
      }
    }
    if(scores&&catalogRowsByLeague.size){
      for(const [lg,rows] of catalogRowsByLeague.entries()){
        if(!SCORE_DATE_STORE?.hasLeagueMatchesSnapshot?.(date,lg)){ storeScoreDateLeague(lg,date,rows); catalogGames+=rows.length; }
      }
      any=true;
    }
    // A completed historical seed makes absent leagues authoritative empty
    // snapshots. This is what lets Aug 22 paint instantly without waiting on ESPN.
    if(scores&&payload?.scoreInventoryComplete){
      for(const lg of ENABLED_LIVE_LEAGUES){
        if(!SCORE_DATE_STORE?.hasLeagueMatchesSnapshot?.(date,lg)) storeScoreDateLeague(lg,date,[]);
      }
      any=true;
    }
    if(payload?.discoveryState) historicalDateDiscoveryStates.set(date,payload.discoveryState);
    for(const lg of ENABLED_LIVE_LEAGUES){
      const state=leagues[lg]; if(!state) continue;
      // Prefer a persisted scoreboard when one exists; it can carry fresher score
      // details than the normalized catalog event, but it is no longer required
      // for the historical ribbon to appear.
      if(scores&&Number(state.scoresSavedAt||0)>0){ storeScoreDateLeague(lg,date,state.scores||[]); any=true; }
      if(Array.isArray(state.media)){
        const nowSeconds=Date.now()/1000;
        const rows=(state.media||[]).filter(x=>{
          if(!x?.mediaUrl || x?.youtubeId || !x?.verifiedPlayable) return true;
          const verifiedAt=Number(x?.historyVerifiedAt||0);
          return verifiedAt>0 && Math.max(0,nowSeconds-verifiedAt)<4*60*60;
        });
        storeScoreDateMedia(lg,date,rows);
        if(rows.length) any=true;
      }
    }
    if(scoreBrowseDate===date) renderHistoricalDateDiagnostics(date,payload?.discoveryState||historicalDiscoveryState(date));
    return {any,leagues,catalogGames,scoreGameCount:Number(payload?.scoreGameCount||catalogGames),scoreInventoryComplete:!!payload?.scoreInventoryComplete,discoveryState:payload?.discoveryState||null};
  }catch(err){
    HISTORICAL_SCORE_LOAD_ERRORS.set(date,String(err?.message||err||'Historical catalog unavailable'));
    console.warn('[SBB v4.3.6] history hydrate failed',date,err);
    return {any:false,leagues:{},catalogGames:0,scoreGameCount:0,scoreInventoryComplete:false,discoveryState:null,error:err};
  }
}

function pumpHistoricalMediaSearchQueue(){
  while(historicalMediaSearchActive<HISTORICAL_MEDIA_DISCOVERY_CONCURRENCY && historicalMediaSearchQueue.length){
    const job=historicalMediaSearchQueue.shift();
    if(!job || job.started) continue;
    job.started=true; historicalMediaSearchActive++;
    rapidHistoricalGameMedia(job.match).then(rows=>{
      if(rows?.length && scoreBrowseDate===scoreEventDate(job.match)) renderScoresFromMatchesCombined(false);
      job.resolve(rows);
    },job.reject).finally(()=>{
      historicalMediaSearchActive=Math.max(0,historicalMediaSearchActive-1);
      historicalMediaSearchJobs.delete(job.key);
      pumpHistoricalMediaSearchQueue();
    });
  }
}
function queueHistoricalGameMedia(match,{priority=false}={}){
  if(!match) return Promise.resolve([]);
  const key=historicalMediaSearchKey(match);
  const existing=historicalMediaSearchJobs.get(key);
  if(existing){
    if(priority && !existing.started){
      const i=historicalMediaSearchQueue.indexOf(existing); if(i>0){historicalMediaSearchQueue.splice(i,1);historicalMediaSearchQueue.unshift(existing);}
    }
    return existing.promise;
  }
  let resolve,reject;
  const promise=new Promise((res,rej)=>{resolve=res;reject=rej;});
  const job={key,match,promise,resolve,reject,started:false};
  historicalMediaSearchJobs.set(key,job);
  if(priority) historicalMediaSearchQueue.unshift(job); else historicalMediaSearchQueue.push(job);
  pumpHistoricalMediaSearchQueue();
  return promise;
}
function storeScoreDateLeague(league,date,rows){
  const lg=String(league||'SPORTS').toUpperCase();
  const marked=(rows||[]).map(raw=>{
    const m={...raw,__sbbLeague:lg,__sbbDate:date,__sbbDay:date===localDateISO(0)?'today':(date===localDateISO(-1)?'yesterday':'historical'),competitionId:lg,competitionName:LEAGUES[lg]?.competition||lg,sportId:LEAGUES[lg]?.sport||'sports'};
    return window.SBB_CORE?.event?window.SBB_CORE.event(m,lg):m;
  });
  SCORE_DATE_STORE?.setMatches?.(date,lg,marked);
  return marked;
}
function storeScoreDateMedia(league,date,rows,{append=false}={}){
  const lg=String(league||'SPORTS').toUpperCase();
  const prepared=(rows||[]).map(x=>({...x,__sbbDate:x.__sbbDate||date,gameDate:x.gameDate||date,competitionId:x.competitionId||lg,league:lg,sport:x.sport||LEAGUES[lg]?.sport||'sports'}));
  if(append) SCORE_DATE_STORE?.addMedia?.(date,lg,prepared); else SCORE_DATE_STORE?.setMedia?.(date,lg,prepared);
  return prepared;
}
async function loadScoreDateLeagueMatches(league,date){
  const lg=String(league).toUpperCase();
  const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone||'Etc/UTC';
  const utcOffsetMinutes=-new Date().getTimezoneOffset();
  // v4.3.6: historical score inventory is server-owned too. Ribbon hydration and
  // historical media discovery now consume the same persisted canonical events,
  // eliminating the old browser/server double fetch and identity drift.
  if(String(date).slice(0,10)<localDateISO(0)){
    try{
      const payload=await apiJson(`/api/history/scores?date=${encodeURIComponent(date)}&league=${encodeURIComponent(lg)}&timezone=${encodeURIComponent(timezone)}&utcOffsetMinutes=${encodeURIComponent(utcOffsetMinutes)}`);
      const rows=responseItems(payload).filter(row=>canonicalScheduledGameDate({...row,__sbbLeague:lg},date)===date);
      return {rows:storeScoreDateLeague(lg,date,rows),error:null,source:payload?.source||'HISTORY'};
    }catch(err){
      console.warn(`[SBB v4.3.6] ${lg} canonical historical score load failed`,date,err);
      return {rows:storeScoreDateLeague(lg,date,[]),error:err,source:'HISTORY ERROR'};
    }
  }
  let rows=[],firstError=null;
  try{
    const payload=await apiJson(`/api/espn/scoreboard?league=${encodeURIComponent(lg)}&date=${encodeURIComponent(date)}&timezone=${encodeURIComponent(timezone)}&utcOffsetMinutes=${encodeURIComponent(utcOffsetMinutes)}`);
    rows=responseItems(payload).filter(row=>canonicalScheduledGameDate({...row,__sbbLeague:lg},date)===date);
  }catch(err){firstError=err;console.warn(`[SBB v4.3.6] ${lg} score load failed`,date,err);}
  return {rows:storeScoreDateLeague(lg,date,rows),error:firstError,source:'ESPN'};
}

async function rapidHistoricalGameMedia(match,{force=false}={}){
  // The localhost historical catalog is the only discovery owner. Consume an
  // already-verified event plan first; only discover when that exact event lacks
  // a playable asset. This makes revisited dates instant and avoids needless API work.
  if(!match) return [];
  const league=String(match.__sbbLeague||match.competitionId||match.league||'').toUpperCase();
  const date=scoreEventDate(match)||scoreBrowseDate;
  const eventId=String(match.espnEventId||match.scoreEventId||match.matchId||match.eventId||match.id||'');
  if(!league||!date||!eventId) return [];
  const decorate=plan=>{
    const all=(plan?.media||[]).map(x=>({...x,__sbbDate:date,__sbbLeague:league,competitionId:league,league,matchId:eventId,scoreEventId:eventId,gameDate:date}));
    if(all.length) storeScoreDateMedia(league,date,all,{append:true});
    return (plan?.playable||[]).map(x=>({...x,__sbbDate:date,__sbbLeague:league,competitionId:league,league,matchId:eventId,scoreEventId:eventId,gameDate:date}))
      .filter(x=>x?.verifiedPlayable&&(x.youtubeId||x.mediaUrl)&&runtimeMediaUsable(x));
  };
  try{
    if(!force){
      const cached=await apiJson(`/api/history/event/media?date=${encodeURIComponent(date)}&league=${encodeURIComponent(league)}&eventId=${encodeURIComponent(eventId)}`);
      const ready=decorate(cached?.plan||{});
      if(ready.length){ await hydrateScoreDateFromHistory(date); return ready; }
    }
    const payload=await apiJson('/api/history/event/discover',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({date,league,eventId,force:!!force})
    });
    const ready=decorate(payload?.plan||{});
    await hydrateScoreDateFromHistory(date);
    return ready;
  }catch(err){console.warn(`[SBB v4.3.6] ${league} historical catalog discovery failed`,err);return [];}
}

async function loadScoreDateLeagueMedia(league,date,matches){
  // v4.3.6: full historical discovery belongs to the localhost server. The
  // browser no longer launches one independent Highlightly/YouTube search per
  // league and then another exact-game search for every apparent miss. That old
  // split pipeline was why the ribbon could show Dec 25 NFL/NBA scores while the
  // dev/media rail continued reporting today's MLB inventory.
  const lg=String(league).toUpperCase();
  const existing=scoreMediaForDate(date).filter(x=>String(x?.competitionId||x?.__sbbLeague||x?.league||'').toUpperCase()===lg);
  const merged=preferGameOverviews(existing);
  storeScoreDateMedia(lg,date,merged);
  if(scoreBrowseDate===date) renderHistoricalDateDiagnostics(date,historicalDiscoveryState(date));
  return merged;
}
async function ensureScoreDateLoaded(date,{force=false}={}){
  date=String(date||scoreBrowseDate).slice(0,10);
  const today=localDateISO(0);
  if(date>today) date=today;
  const leagueLoaded=lg=>!!SCORE_DATE_STORE?.hasLeagueMatchesSnapshot?.(date,lg);
  const allLoaded=()=>ENABLED_LIVE_LEAGUES.every(leagueLoaded);
  const launchMedia=(league,rows)=>{
    // The selected historical date has one server-owned discovery job. Keep this
    // hook as a cheap local refresh only; do not duplicate provider searches in
    // six browser-owned pipelines.
    if(date>=today) return;
    loadScoreDateLeagueMedia(league,date,rows||[]).then(()=>{
      if(scoreBrowseDate===date) renderHistoricalDateDiagnostics(date,historicalDiscoveryState(date));
    }).catch(err=>console.warn('[SBB v4.3.6] historical media hydrate failed',league,date,err));
  };

  if(!force && allLoaded()){
    renderScoresFromMatchesCombined();
    if(date<today) hydrateScoreDateFromHistory(date,{scores:false}).then(()=>{if(scoreBrowseDate===date)renderScoresFromMatchesCombined(false);}).catch(()=>{});
    else hydrateScoreDateFromHistory(date,{scores:false}).catch(()=>{});
    for(const league of ENABLED_LIVE_LEAGUES) launchMedia(league,SCORE_DATE_STORE?.matches?.(date,league)||[]);
    return ENABLED_LIVE_LEAGUES.map(league=>[league,{rows:SCORE_DATE_STORE?.matches?.(date,league)||[],cached:true}]);
  }
  if(SCORE_DATE_STORE?.isLoading?.(date)) return;
  const generation=++scoreDateLoadGeneration;
  SCORE_DATE_STORE?.markLoading?.(date,true);
  renderScoresFromMatchesCombined();
  try{
    // Historical first paint is a dedicated compact SQLite read. Do not make the
    // ribbon wait for the full source-media/discovery payload before showing games.
    if(!force && date<today){
      const ribbon=await hydrateHistoricalRibbonFromCatalog(date);
      if(ribbon.ok && scoreBrowseDate===date) renderScoresFromMatchesCombined(true);
      if(ribbon.ok){
        for(const league of ENABLED_LIVE_LEAGUES){if(leagueLoaded(league)) launchMedia(league,SCORE_DATE_STORE?.matches?.(date,league)||[]);}
        // Enrich media/diagnostics asynchronously after the cards already exist.
        hydrateScoreDateFromHistory(date,{scores:false}).then(()=>{if(scoreBrowseDate===date)renderScoresFromMatchesCombined(false);}).catch(()=>{});
        if(ribbon.scoreInventoryComplete){
          return ENABLED_LIVE_LEAGUES.map(league=>[league,{rows:SCORE_DATE_STORE?.matches?.(date,league)||[],cached:true,source:'CATALOG_RIBBON'}]);
        }
      }
    } else if(!force){
      const hydrated=await hydrateScoreDateFromHistory(date,{scores:true});
      if(hydrated.any && scoreBrowseDate===date) renderScoresFromMatchesCombined(true);
    }

    // Today still refreshes scores from live providers, but already-associated media
    // is painted from SQLite before those network calls complete.
    const needed=(date>=today||force)?[...ENABLED_LIVE_LEAGUES]:ENABLED_LIVE_LEAGUES.filter(lg=>!leagueLoaded(lg));
    const scorePromises=needed.map(async league=>{
      const result=await loadScoreDateLeagueMatches(league,date);
      // v4.3.6 paints each league as soon as that provider finishes rather than
      // waiting for the slowest of six sports before showing any ribbon cards.
      if(scoreBrowseDate===date) renderScoresFromMatchesCombined(false);
      launchMedia(league,result.rows||[]);
      return [league,result];
    });
    const settled=await Promise.allSettled(scorePromises);
    const scoreResults=settled.filter(x=>x.status==='fulfilled').map(x=>x.value);
    if(generation===scoreDateLoadGeneration || scoreBrowseDate===date) renderScoresFromMatchesCombined(true);
    return scoreResults;
  }catch(err){
    console.warn('[SBB v4.3.6] historical score-date load failed',date,err);
    return [];
  }finally{
    SCORE_DATE_STORE?.markLoading?.(date,false);
    if(scoreBrowseDate===date){renderScoresFromMatchesCombined(false);renderActiveSportKeyInformation();}
  }
}
async function selectHistoricalGameWithoutMedia(match){
  if(!match) return;
  const selected=syncSelectedEvent(gameCenterSelectionFromScoreMatch(match),{reason:'historical score selection',source:'score-ribbon'});
  window.SBB_INFO_DRAWER?.open?.('game-center',{automatic:false});
  setFeedNote(`${gameLabel(match)} • finding a playable recap…`);
  const found=await queueHistoricalGameMedia(match,{priority:true});
  if(scoreBrowseDate===scoreEventDate(match)) renderScoresFromMatchesCombined(false);
  const playable=scoreCardPlayableItems(match);
  if(playable.length) playGameHighlights(`${String(match.__sbbLeague||match.competitionId||match.league).toUpperCase()}:${String(match.id??match.matchId??match.eventId??'')}`,match,playable);
  else setFeedNote(`${gameLabel(match)} • Game Center loaded • no playable recap found yet`);
}

async function refreshSoccerLeague(league,today,yesterday,allCandidates){
  updateSportFeedState(league,{status:'checking',error:'',calls:0,skippedHighlightCalls:0});
  let todayMatches=[],yesterdayMatches=[],scoreError=null,scoreSource='CACHE';

  try{
    const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone||'Etc/UTC';
    const utcOffsetMinutes=-new Date().getTimezoneOffset();
    const clientClock=`&timezone=${encodeURIComponent(timezone)}&clientDate=${encodeURIComponent(today)}&utcOffsetMinutes=${encodeURIComponent(utcOffsetMinutes)}`;
    const bundle=await apiJson(`/api/soccer/schedule?league=${encodeURIComponent(league)}&today=${encodeURIComponent(today)}&yesterday=${encodeURIComponent(yesterday)}${clientClock}`);
    const td=bundle?.today||{}, yd=bundle?.yesterday||{};
    // Never trust the query bucket as the display bucket. Reclassify the union by
    // the event's actual timestamp in the browser calendar. This provides a second
    // defense even if an upstream schedule API returns a UTC-day duplicate.
    const markedToday=(td.data||[]).map(x=>({...x,__sbbLeague:league}));
    const markedYesterday=(yd.data||[]).map(x=>({...x,__sbbLeague:league}));
    const canonical=canonicalizeMatchBuckets(markedYesterday,markedToday,yesterday,today);
    todayMatches=canonical.todayMatches.map(x=>({...x,__sbbLeague:league,__sbbDay:'today'}));
    yesterdayMatches=canonical.yesterdayMatches.map(x=>({...x,__sbbLeague:league,__sbbDay:'yesterday'}));
    scoreSource=[td.source,yd.source].filter(Boolean).join('/')||'CACHE';
  }catch(err){
    scoreError=err;
    const snap=loadSoccerSnapshot(league);
    todayMatches=snap?.today||[];
    yesterdayMatches=snap?.yesterday||[];
    scoreSource='LOCAL SNAPSHOT';
  }

  if(todayMatches.length||yesterdayMatches.length) saveSoccerSnapshot(league,yesterdayMatches,todayMatches);
  const allMatches=[...yesterdayMatches,...todayMatches];
  renderLeagueScores(league,yesterdayMatches,todayMatches);

  let extras=[];
  try{
    if(league==='MLS') extras.push(...await refreshMlsOfficialVideos(allMatches));
    const rapid=await rapidEnrichOtherSport(league,allMatches,extras);
    if(rapid.length) extras.push(...rapid);
  }catch(mediaErr){ console.warn(`[SBB v4.3.6] ${league} media discovery`,mediaErr); }

  extras=preferGameOverviews(extras);
  if(extras.length){
    LIVE_CANDIDATES_BY_LEAGUE.set(league,extras);
    indexHighlightsByMatch(extras);
    setTimeout(reconcileScoreMediaIndicators,0);
    mergeLiveProgram(extras,false);
    allCandidates.push(...extras);
  }

  const live=allMatches.filter(isLive).length;
  const cached=/CACHE|SNAPSHOT/i.test(scoreSource);
  const status=live?'live':(allMatches.length?(cached?'degraded':'ok'):(scoreError?'error':'empty'));
  updateSportFeedState(league,{
    status,games:allMatches.length,eligible:allMatches.filter(isHighlightEligible).length,
    live,final:allMatches.filter(isFinal).length,
    scheduled:allMatches.filter(x=>!isLive(x)&&!isFinal(x)).length,
    highlights:extras.length,calls:1,
    error:scoreError?`${scoreSource} • ${scoreError.message||scoreError}`:'',
    diagnostic:`${scoreSource}${allMatches.length?` • ${allMatches.length} games`:''}`
  });
  if(!document.body.classList.contains('diagnostics-off')){
    setTimeout(()=>refreshSoccerDiagnostics(league,yesterday),350);
  }
  return !!live;
}

function scheduledTransitionImminent(match){
  if(!match || isLive(match) || isFinal(match)) return false;
  const raw=match.date ?? match.startDate ?? match.startTime ?? match.scheduledAt ?? match.startAt ?? match.datetime ?? '';
  const dt=new Date(raw);
  if(!Number.isFinite(dt.getTime())) return false;
  const delta=dt.getTime()-Date.now();
  // Begin checking shortly before kickoff and stay aggressive while an upstream
  // provider could still be incorrectly reporting the event as scheduled.
  return delta<=10*60_000 && delta>=-6*60*60_000;
}

async function refreshOtherSports(first=false){
  if(!first && historicalForegroundActive()) return;
  // Score inventory is not Highlightly-dependent. NFL/NBA/NHL can still run from
  // the independent ESPN authority when the optional Highlightly key is absent.
  // Live and kickoff-transition score state is intentionally much fresher than
  // media discovery. The server can satisfy these reads from its independent ESPN
  // scoreboard authority without spending another Highlightly request every time.
  const cadence=otherSportsNeedTransitionRefresh?45_000:(otherSportsHaveLiveGames?60_000:300_000);
  if(!first && Date.now()-lastOtherSportsRefresh<cadence) return;
  lastOtherSportsRefresh=Date.now();
  MULTISPORT_CALLS={made:0,skipped:0,refreshStarted:Date.now()};
  const today=localDateISO(0), yesterday=localDateISO(-1);
  const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone||'Etc/UTC';
  // Browser clock facts make server live-day decisions portable on Termux builds
  // where Python's optional IANA timezone database may not be installed.
  const utcOffsetMinutes=-new Date().getTimezoneOffset();
  const clientClock=`&timezone=${encodeURIComponent(timezone)}&clientDate=${encodeURIComponent(today)}&utcOffsetMinutes=${encodeURIComponent(utcOffsetMinutes)}`;
  const configs=[['NFL','nfl'],['NBA','nba'],['NHL','nhl']];
  const allCandidates=[]; let foundLive=false, foundTransition=false;

  await Promise.all(configs.map(async([league,key])=>{
    updateSportFeedState(league,{status:'checking',error:'',calls:0,skippedHighlightCalls:0});
    try{
      // Stage 1: only matches. This is enough to prove the feed works and to know
      // whether highlight requests are useful. It cuts two needless API calls for
      // every league/date pair with no completed games.
      // v4.3.6 deep-dive: schedule identity is fetched from ESPN directly and
      // independently for each day. Highlightly no longer sits in front of score
      // discovery, so a slow/empty enrichment response cannot hide an NFL/NBA/NHL
      // schedule. It remains a fallback and media source only.
      const loadLeagueDay=async(date,day)=>{
        let espnError=null, rows=[];
        try{
          MULTISPORT_CALLS.made++;
          const espn=await apiJson(`/api/espn/scoreboard?league=${encodeURIComponent(league)}&date=${encodeURIComponent(date)}&timezone=${encodeURIComponent(timezone)}&utcOffsetMinutes=${encodeURIComponent(utcOffsetMinutes)}`);
          rows=responseItems(espn).filter(row=>canonicalScheduledGameDate({...row,__sbbLeague:league},date)===date);
        }catch(err){
          espnError=err;
          console.warn(`[SBB v4.3.6] ${league} ESPN ${day} schedule read failed`,err);
        }
        if(!rows.length && apiConfigured){
          try{
            MULTISPORT_CALLS.made++;
            const fallback=await apiJson(`/api/sports/${key}/matches?date=${encodeURIComponent(date)}${clientClock}`);
            rows=responseItems(fallback).filter(row=>canonicalScheduledGameDate({...row,__sbbLeague:league},date)===date);
          }catch(err){
            console.warn(`[SBB v4.3.6] ${league} ${day} Highlightly schedule fallback failed`,err);
            if(!espnError) espnError=err;
          }
        }
        return {rows:rows.map(x=>({...x,__sbbLeague:league,__sbbDate:date,__sbbDay:day})),error:espnError};
      };
      const [todayLoad,yesterdayLoad]=await Promise.all([loadLeagueDay(today,'today'),loadLeagueDay(yesterday,'yesterday')]);
      const todayMatches=todayLoad.rows, yesterdayMatches=yesterdayLoad.rows;
      const allMatches=[...yesterdayMatches,...todayMatches];
      const liveCount=allMatches.filter(isLive).length;
      if(todayMatches.some(scheduledTransitionImminent)) foundTransition=true;
      const mediaEligibleToday=todayMatches.some(isHighlightEligible);
      const mediaEligibleYesterday=yesterdayMatches.some(isHighlightEligible);
      if(liveCount) foundLive=true;
      renderLeagueScores(league,yesterdayMatches,todayMatches);

      // Stage 2: only ask Highlightly for media when at least one game on that date
      // has actually started (live or final). Purely scheduled/offseason dates cost
      // zero highlight calls, while live-game coverage remains possible.
      if(historicalForegroundActive()) return;
      const highlightJobs=[];
      if(apiConfigured && mediaEligibleToday){ MULTISPORT_CALLS.made++; highlightJobs.push(apiJson(`/api/sports/${key}/highlights?date=${encodeURIComponent(today)}${clientClock}`).then(x=>({date:today,payload:x})).catch(error=>({date:today,error}))); }
      else { MULTISPORT_CALLS.skipped++; }
      if(apiConfigured && mediaEligibleYesterday){ MULTISPORT_CALLS.made++; highlightJobs.push(apiJson(`/api/sports/${key}/highlights?date=${encodeURIComponent(yesterday)}${clientClock}`).then(x=>({date:yesterday,payload:x})).catch(error=>({date:yesterday,error}))); }
      else { MULTISPORT_CALLS.skipped++; }

      const highlightResults=await Promise.all(highlightJobs);
      const raw=[]; let mediaErrors=0;
      for(const result of highlightResults){
        if(result.error){ mediaErrors++; console.warn(`[SBB v4.3.6] ${league} highlight refresh failed`,result.error); continue; }
        raw.push(...responseItems(result.payload).map(x=>({...x,__sbbDate:result.date})));
      }
      let candidates=preferGameOverviews(normalizeHighlights(raw,league));
      indexHighlightsByMatch(candidates); mergeLiveProgram(candidates,false); allCandidates.push(...candidates);
      if(league==='MLS'){
        const officialMls=await refreshMlsOfficialVideos(allMatches);
        if(officialMls.length){ candidates=preferGameOverviews([...candidates,...officialMls]); allCandidates.push(...officialMls); }
      }
      const rapidExtra=await rapidEnrichOtherSport(league,allMatches,candidates);
      if(rapidExtra.length) allCandidates.push(...rapidExtra);
      const status=liveCount?'live':(allMatches.length?'ok':'empty');
      updateSportFeedState(league,{
        status,games:allMatches.length,eligible:allMatches.filter(isHighlightEligible).length,
        live:liveCount,final:allMatches.filter(isFinal).length,
        scheduled:allMatches.filter(x=>!isLive(x)&&!isFinal(x)).length,
        highlights:candidates.length,calls:2+highlightJobs.length,
        skippedHighlightCalls:2-highlightJobs.length,
        error:mediaErrors?`${mediaErrors} media request${mediaErrors===1?'':'s'} failed`:((!allMatches.length&&(todayLoad.error||yesterdayLoad.error))?String((todayLoad.error||yesterdayLoad.error)?.message||todayLoad.error||yesterdayLoad.error):'')
      });
    }catch(err){
      console.warn(`[SBB v4.3.6] ${league} Highlightly feed failed`,err);
      // ESPN is an independent scoreboard fallback. Highlightly rate limiting or
      // schema trouble should not make a league disappear, especially soccer where
      // official YouTube discovery continues independently.
      if(['NHL','EPL','MLS'].includes(league)){
        try{
          const [tm,ym]=await Promise.all([
            soccerScoreJson(league,today),
            soccerScoreJson(league,yesterday)
          ]);
          const todayMatches=responseItems(tm).map(x=>({...x,__sbbLeague:league,__sbbDate:today,__sbbDay:'today'}));
          const yesterdayMatches=responseItems(ym).map(x=>({...x,__sbbLeague:league,__sbbDate:yesterday,__sbbDay:'yesterday'}));
          renderLeagueScores(league,yesterdayMatches,todayMatches);
          const all=[...yesterdayMatches,...todayMatches];
          let extras=[];
          if(league==='MLS') extras=await refreshMlsOfficialVideos(all);
          const rapid=await rapidEnrichOtherSport(league,all,extras);
          if(rapid.length) extras.push(...rapid);
          if(extras.length){ indexHighlightsByMatch(extras);
    setTimeout(reconcileScoreMediaIndicators,0); mergeLiveProgram(extras,false); allCandidates.push(...extras); }
          updateSportFeedState(league,{status:all.some(isLive)?'live':(all.length?'ok':'empty'),games:all.length,eligible:all.filter(isHighlightEligible).length,live:all.filter(isLive).length,final:all.filter(isFinal).length,scheduled:all.filter(x=>!isLive(x)&&!isFinal(x)).length,highlights:extras.length,calls:2,error:'ESPN scoreboard fallback'});
          return;
        }catch(fallbackErr){ console.warn(`[SBB v4.3.6] ${league} ESPN fallback failed`,fallbackErr); }
      }

      updateSportFeedState(league,{status:'error',error:`${err?.status||''} ${err?.message||err}`.trim(),games:0,eligible:0,live:0,final:0,scheduled:0,highlights:0,calls:2});
    }
  }));
  const soccerLive=await Promise.all([refreshSoccerLeague('EPL',today,yesterday,allCandidates),refreshSoccerLeague('MLS',today,yesterday,allCandidates)]);
  if(soccerLive.some(Boolean)) foundLive=true;
  otherSportsHaveLiveGames=foundLive;
  otherSportsNeedTransitionRefresh=foundTransition;
  renderScoresFromMatchesCombined();
  renderSportFeedDiagnostics();
  if(allCandidates.length) setFeedNote(`Around the Sports World • ${GENERAL_PROGRAM?.length||0} playable programs across ${ENABLED_LIVE_LEAGUES.join(' / ')}`);
}


function escapeAttr(value){ return escapeHtml(value).replace(/`/g,'&#96;'); }
function keyInfoEventDate(item){
  const raw=String(item?.publishedAt||item?.date||''); if(!raw) return '';
  if(/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw.slice(0,10);
  const dt=new Date(raw); if(!Number.isFinite(dt.getTime())) return '';
  return dateInTimeZone(dt,Intl.DateTimeFormat().resolvedOptions().timeZone||'Etc/UTC');
}
function keyInfoEventsForActiveSport(){
  const lg=String(scoreRibbonLeagueFilter||'ALL').toUpperCase();
  const leagueRows=ALL_KEY_INFO_EVENTS.filter(x=>lg==='ALL'||String(x?.league||'').toUpperCase()===lg);
  const exact=leagueRows.filter(x=>keyInfoEventDate(x)===scoreBrowseDate);
  if(exact.length || scoreBrowseDate!==localDateISO(0)) return exact;
  // v4.3.6 hotfix: Key Info is a current-information lane, not an empty-midnight
  // lane. If today's source refresh has not yet produced an item stamped on the
  // viewer's exact local calendar date, show the newest factual updates from the
  // rolling 36-hour window while the background editorial refresh catches up.
  const now=Date.now(), floor=now-(36*60*60*1000), ceiling=now+(60*60*1000);
  return leagueRows.filter(x=>{
    const dt=new Date(String(x?.publishedAt||x?.date||''));
    const ts=dt.getTime(); return Number.isFinite(ts)&&ts>=floor&&ts<=ceiling;
  }).sort((a,b)=>new Date(String(b?.publishedAt||b?.date||0))-new Date(String(a?.publishedAt||a?.date||0))).slice(0,20);
}
function renderActiveSportKeyInformation(){
  renderKeyInformation(keyInfoEventsForActiveSport());
}

function renderKeyInformation(events=[]){
  const track=$('keyInfoTrack'), state=$('keyInfoState');
  if(!track) return;
  const items=(events||[]).slice(0,20);
  const dateLabel=formatScoreDateLabel(scoreBrowseDate);
  if(state) state.textContent=items.length?`${items.length} updates • ${dateLabel}`:`${dateLabel} • no saved updates`;
  if(!items.length){ track.innerHTML=`<div class="key-info-empty">No saved key-information updates for ${escapeHtml(dateLabel)}.</div>`; return; }
  track.innerHTML='';
  const belt=document.createElement('div');
  belt.className='key-info-marquee';
  // Two identical back-to-back groups make the reset occur at an identical pixel
  // boundary. There is never an empty gap or visible "start over" moment.
  const totalChars=items.reduce((n,x)=>n+String(x?.title||'').length+16,0);
  belt.style.setProperty('--ticker-duration',`${Math.max(42,Math.round(totalChars*0.115))}s`);
  const buildGroup=(duplicate=false)=>{
    const group=document.createElement('div');
    group.className='key-info-group';
    for(const item of items){
      const btn=document.createElement('button');
      const type=String(item.eventType||'NEWS').toUpperCase();
      btn.type='button'; btn.className=`key-info-item ${String(item.eventType||'news').toLowerCase()}`;
      if(duplicate) btn.tabIndex=-1;
      const mediaTag=item.verifiedPlayable?' • VIDEO':' • INFO';
      btn.innerHTML=`<span class="key-info-type">${escapeHtml(type)}</span><strong>${escapeHtml(item.title||'Sports update')}</strong><small>${escapeHtml(item.league||'SPORT')} • ${escapeHtml(item.sourceLabel||item.source||'Official source')}${item.duration?` • ${escapeHtml(formatDuration(item.duration))}`:''}${mediaTag}</small>`;
      btn.onclick=()=>{
        if(!item.verifiedPlayable){
          const article=item.articleUrl||item.sourceUrl||'';
          if(article) window.open(article,'_blank','noopener,noreferrer');
          return;
        }
        const id=programGameIdentity(item);
        let idx=PROGRAM.findIndex(x=>programGameIdentity(x)===id);
        if(idx<0){ SPORTS_EVENT_CANDIDATES=[...SPORTS_EVENT_CANDIDATES.filter(x=>programGameIdentity(x)!==id),item]; mergeLiveProgram([],false); idx=PROGRAM.findIndex(x=>programGameIdentity(x)===id); }
        if(idx>=0) jumpTo(idx);
      };
      group.appendChild(btn);
    }
    return group;
  };
  belt.appendChild(buildGroup(false));
  belt.appendChild(buildGroup(true));
  track.appendChild(belt);
}
async function refreshRapidMlbHighlights(date, force=false){
  if(!date) return;
  const now=Date.now();
  const last=Number(RAPID_MLB_REFRESH_AT.get(date)||0);
  // Keep today and yesterday independent. The old single timer meant the first
  // date requested blocked the second date for two minutes.
  if(!force && now-last<120000) return;
  RAPID_MLB_REFRESH_AT.set(date,now);
  try{
    const payload=await apiJson(`/api/mlb/rapid-highlights?date=${encodeURIComponent(date)}${force?'&refresh=1&clips=1':''}`);
    const items=responseItems(payload).map(x=>{
      const away=String(x.away||'Away'), home=String(x.home||'Home');
      return {
        ...x, league:'MLB', sport:'baseball', matchId:String(x.gamePk||x.matchId||''),
        gameDate:x.date||date, gameKey:gameKey(away,home), scoreGameKey:`${x.date||date}::${gameKey(away,home)}`,
        verifiedPlayable:!!(x.mediaUrl||x.youtubeId), sourceLabel:x.sourceLabel||x.source||'Official MLB/team source'
      };
    }).filter(x=>x.verifiedPlayable);
    RAPID_MLB_BY_DATE.set(date,items);
    RAPID_MLB_CANDIDATES=[...RAPID_MLB_BY_DATE.values()].flat();
    if(RAPID_MLB_CANDIDATES.length){
      const existing=[...(LIVE_CANDIDATES_BY_LEAGUE.get('MLB')||[])];
      const combined=[...existing,...RAPID_MLB_CANDIDATES];
      mergeLiveProgram(combined,false);
      indexHighlightsByMatch(combined);
      renderScoresFromMatchesCombined();
    }
    const el=$('rapidHighlightStatus');
    if(el) el.textContent=`RAPID ${[...RAPID_MLB_BY_DATE.values()].reduce((n,x)=>n+x.length,0)} scanned • ${RAPID_MLB_BY_DATE.size} dates`;
  }catch(err){
    console.warn('[SBB v4.3.6] rapid MLB highlight refresh failed',err);
    const el=$('rapidHighlightStatus'); if(el) el.textContent='RAPID source unavailable';
  }
}

async function refreshMediaPrewarmStatus(){
  // Historical diagnostics own this rail while browsing the past. Today's
  // prewarm worker may still have a cached status, but it must never overwrite
  // the selected date and make Dec 25 look like an Aug 22 media search.
  if(String(scoreBrowseDate||'').slice(0,10) < localDateISO(0)){
    const state=historicalDiscoveryState(scoreBrowseDate);
    if(state) renderHistoricalDateDiagnostics(scoreBrowseDate,state);
    return;
  }
  try{
    const p=await apiJson('/api/media/prewarm-status');
    const el=$('mediaPrewarmStatus'); if(!el) return;
    const mlb=p?.mlb||{};
    let unresolved=0;
    for(const d of Object.values(mlb)) unresolved+=Number(d?.unresolved||0);
    const topPlays=Object.values(p?.topPlays||{}).reduce((sum,n)=>sum+Number(n||0),0);
    const age=Number(p?.ageSeconds);
    const ageText=Number.isFinite(age)?(age<90?'now':`${Math.max(1,Math.round(age/60))}m ago`):'starting';
    const tc=p?.transportCache||{};
    const localReady=Number(tc.fullFiles||0), staged=Number(tc.stagedFiles||0);
    el.textContent=`PREWARM ${ENABLED_LIVE_LEAGUES.length} SPORTS${localReady?` • ${localReady} local`:''}${staged?` • ${staged} staged`:''}${unresolved?` • ${unresolved} upgrading`:''}${topPlays?` • ${topPlays} Top Plays`:''} • ${ageText}`;
    el.title=p?.lastError||`Persistent media cache: ${localReady} full • ${staged} staged • ${Number(tc.rangeHits||0)+Number(tc.fullHits||0)} local hits`;
  }catch(e){
    const el=$('mediaPrewarmStatus'); if(el) el.textContent='PREWARM unavailable';
  }
}

async function refreshKeyInformation(first=false,force=false){
  if(!first && historicalForegroundActive()) return;
  if(!first && !force && Date.now()-lastKeyInfoRefresh<KEY_INFO_REFRESH_MS) return;
  lastKeyInfoRefresh=Date.now();
  try{
    const payload=await apiJson(`/api/editorial/key-info?leagues=MLB,NFL,NBA,NHL,EPL,MLS${force?'&refresh=1':''}`);
    const editorialMode=String(payload?.editorialMode||'rules');
    const cacheAge=Number(payload?.cacheAgeSeconds);
    const cacheNote=Number.isFinite(cacheAge)?` • cache ${cacheAge<60?`${cacheAge}s`:`${Math.round(cacheAge/60)}m`} old`:'';
    const editorRail=$('editorRailStatus'), editorBadge=$('editorStatusBadge');
    const rawEditorError=String(payload?.editorialError||'').trim();
    const shortEditorError=rawEditorError
      ? rawEditorError.replace(/HTTPError:\s*/i,'').replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').slice(0,72)
      : '';
    const malformedEditor=/JSONDecodeError|response malformed|Unterminated|structured editorial/i.test(rawEditorError);
    const editorText=editorialMode==='openai'
      ? `OPENAI ${payload?.editorialModel||''} READY`
      : editorialMode==='rules-fallback'
        ? `RULES · ${malformedEditor?'OpenAI retry pending':(shortEditorError||'OpenAI unavailable')}`
        : 'RULES';
    if(editorRail) editorRail.textContent=`Editor: ${editorText}${cacheNote}`;
    if(editorBadge){
      editorBadge.textContent=`EDITOR: ${editorText}`;
      editorBadge.title=rawEditorError||editorText;
      editorBadge.classList.toggle('ready',editorialMode==='openai');
      editorBadge.classList.toggle('degraded',editorialMode==='rules-fallback');
    }
    const events=responseItems(payload).map(x=>({
      ...x,
      verifiedPlayable:!!(x.verifiedPlayable && (x.youtubeId||x.mediaUrl)),
      provider:x.provider||'OFFICIAL_NEWS',
      programType:(x.verifiedPlayable && (x.youtubeId||x.mediaUrl))?'event':'event-news',
      overview:!!(x.verifiedPlayable && (x.youtubeId||x.mediaUrl)),
      sport:LEAGUES[String(x.league||'').toUpperCase()]?.sport||'sports'
    }));
    const contextPrograms=Array.isArray(payload?.contextPrograms)?payload.contextPrograms.map(x=>({
      ...x, verifiedPlayable:true, programType:'context', provider:'CONTEXT',
      sport:LEAGUES[String(x.league||'').toUpperCase()]?.sport||'sports'
    })):[];
    // The ticker is factual-first. Video-enriched headlines and generated context
    // cards can enter programming; ordinary text headlines remain ticker-only.
    SPORTS_EVENT_CANDIDATES=[...events.filter(x=>x.verifiedPlayable),...contextPrograms];
    ALL_KEY_INFO_EVENTS=events;
    renderActiveSportKeyInformation();
    if(SPORTS_EVENT_CANDIDATES.length) mergeLiveProgram([],false);
    // A brand-new PC install often has no warm editorial cache yet. The server
    // starts its source/editorial refresh in the background, which can take longer
    // than the old single 12-second retry. Poll the local cache briefly until the
    // first useful ticker arrives, then return to the normal five-minute cadence.
    if(events.length){
      keyInfoStartupRetries=0;
      if(keyInfoStartupRetryTimer){clearTimeout(keyInfoStartupRetryTimer);keyInfoStartupRetryTimer=null;}
    }else if(keyInfoStartupRetries<KEY_INFO_STARTUP_RETRY_MAX){
      keyInfoStartupRetries++;
      if(keyInfoStartupRetryTimer) clearTimeout(keyInfoStartupRetryTimer);
      keyInfoStartupRetryTimer=setTimeout(()=>{keyInfoStartupRetryTimer=null;refreshKeyInformation(false,true);},3000);
      if(state) state.textContent=payload?.refreshing?'Building updates…':'Checking updates…';
    }
  }catch(err){
    console.warn('[SBB v4.3.6] key information refresh failed',err);
    const state=$('keyInfoState'); if(state) state.textContent='Feed unavailable';
  }
}

async function refreshDailyTopPlays(first=false){
  if(!first && historicalForegroundActive()) return;
  if(!first && Date.now()-lastTopPlaysRefresh<TOP_PLAYS_REFRESH_MS) return;
  lastTopPlaysRefresh=Date.now();
  const today=localDateISO(0);
  try{
    const payload=await apiJson(`/api/programming/top-plays?date=${encodeURIComponent(today)}`).catch(()=>({data:[]}));
    TOP_PLAYS_CANDIDATES=responseItems(payload).map(x=>({
      ...x, league:'SPORTS', sport:'multi-sport', topPlaysDate:x.topPlaysDate||today,
      verifiedPlayable:!!(x.verifiedPlayable&&(x.youtubeId||x.mediaUrl)), programType:'top-plays', eventType:'TOP PLAYS'
    })).filter(x=>x.verifiedPlayable && x.topPlaysDate===today);
    if(TOP_PLAYS_CANDIDATES.length) mergeLiveProgram([],false);
  }catch(err){ console.warn('[SBB v4.3.6] daily Top Plays refresh failed',err); }
}

async function refreshFallbackData(first=false){
  if(!first && historicalForegroundActive()) return;
  const today=localDateISO(0);
  const yesterday=localDateISO(-1);
  try{
    const [todayPayload,yesterdayPayload,yHighlights,tHighlights] = await Promise.all([
      apiJson(`/api/mlb/fallback-matches?date=${encodeURIComponent(today)}`),
      apiJson(`/api/mlb/fallback-matches?date=${encodeURIComponent(yesterday)}`),
      apiJson(`/api/mlb/stats-highlights?date=${encodeURIComponent(yesterday)}`).catch(()=>({data:[]})),
      apiJson(`/api/mlb/stats-highlights?date=${encodeURIComponent(today)}`).catch(()=>({data:[]}))
    ]);
    const {todayMatches,yesterdayMatches}=canonicalizeMatchBuckets(yesterdayPayload,todayPayload,yesterday,today);
    LAST_YESTERDAY_MATCHES=yesterdayMatches;
    const candidates=preferGameOverviews(applyCanonicalDatesToCandidates([
      ...normalizeMlbStatsHighlights(responseItems(yHighlights)),
      ...normalizeMlbStatsHighlights(responseItems(tHighlights))
    ],[...yesterdayMatches,...todayMatches]));
    indexHighlightsByMatch(candidates);
    renderLeagueScores('MLB',yesterdayMatches,todayMatches);
    const mlbFallbackAll=[...yesterdayMatches,...todayMatches];
    updateSportFeedState('MLB',{status:mlbFallbackAll.some(isLive)?'live':(mlbFallbackAll.length?'ok':'empty'),games:mlbFallbackAll.length,eligible:mlbFallbackAll.filter(isHighlightEligible).length,live:mlbFallbackAll.filter(isLive).length,final:mlbFallbackAll.filter(isFinal).length,scheduled:mlbFallbackAll.filter(x=>!isLive(x)&&!isFinal(x)).length,highlights:candidates.length});
    if(candidates.length){ mergeLiveProgram(candidates,first); liveFeedLoaded=true; }
    setApiCounts([...yesterdayMatches,...todayMatches], responseItems(yHighlights).length+responseItems(tHighlights).length, candidates);
    setDataStatus(highlightlyRateLimited?'MLB FALLBACK':'MLB LIVE', true);
    if(candidates.length) updateFeedSummary(candidates);
    else setFeedNote('MLB scores loaded • no game recap media available yet');
    lastLiveRefresh=Date.now();
    refreshQuotaFromStatus();
  }catch(err){
    console.warn('MLB fallback failed',err);
    setDataStatus('OFFLINE', false);
    setFeedNote('Unable to load MLB fallback data • existing queue retained');
  }
}

let backgroundLoadToken=0;
async function loadMlbContentBackground(ctx){
  const token=++backgroundLoadToken;
  coverageContext={...ctx,todayStatsCandidates:[]};
  coverageAppliedRevision=-1;
  pollCoverage(ctx.yesterday, token);
  try{
    // Cached MLB media returns immediately; the server continues a full refresh in
    // the background. We merge the warm result now and progressively re-apply
    // snapshots as coverage-status revisions advance.
    const [mlbYesterday, mlbToday]=await Promise.all([
      apiJson(`/api/mlb/stats-highlights?date=${encodeURIComponent(ctx.yesterday)}`).catch(()=>({data:[]})),
      apiJson(`/api/mlb/stats-highlights?date=${encodeURIComponent(ctx.today)}`).catch(()=>({data:[]}))
    ]);
    if(token!==backgroundLoadToken) return;
    const yCandidates=applyCanonicalDatesToCandidates(normalizeMlbStatsHighlights(responseItems(mlbYesterday)),[...ctx.yesterdayMatches,...ctx.todayMatches]);
    const tCandidates=applyCanonicalDatesToCandidates(normalizeMlbStatsHighlights(responseItems(mlbToday)),[...ctx.yesterdayMatches,...ctx.todayMatches]);
    coverageContext.todayStatsCandidates=tCandidates;
    let candidates=preferGameOverviews([...ctx.fastCandidates,...yCandidates,...tCandidates]);
    indexHighlightsByMatch(candidates);
    renderLeagueScores('MLB',ctx.yesterdayMatches,ctx.todayMatches);
    if(candidates.length){ mergeLiveProgram(candidates,ctx.first); liveFeedLoaded=true; }
    setApiCounts([...ctx.yesterdayMatches,...ctx.todayMatches], ctx.todayItems.length+ctx.yesterdayItems.length+yCandidates.length+tCandidates.length, candidates);
    updateFeedSummary(candidates);
  }catch(e){
    console.warn('Background MLB content load failed',e);
    renderCoverage({status:'ERROR',message:`MLB recap search failed: ${e?.message||e}`});
    setFeedNote('Scores live • MLB recap refresh will retry automatically');
  }
}

function updateFeedSummary(candidates){
  const groups=new Map();
  for(const x of candidates){
    const key=x.dateGameKey || x.gameKey || x.matchId || x.id;
    if(!groups.has(key)) groups.set(key,[]);
    groups.get(key).push(x);
  }
  let recaps=0, clipSets=0;
  for(const group of groups.values()){
    if(group.some(x=>x.overview)) recaps++;
    else if(group.length) clipSets++;
  }
  const completed=LAST_COMPLETED_MATCHES.length || LAST_YESTERDAY_MATCHES.filter(isFinal).length;
  const covered=recaps+clipSets;
  const unavailable=Math.max(0,completed-covered);
  setFeedNote(`${completed} completed • ${recaps} full recap${recaps===1?'':'s'} • ${clipSets} highlight reel${clipSets===1?'':'s'} • ${unavailable} unavailable`);
}

function youtubeIdFromHighlight(h){
  const fields=[h.embedUrl,h.url,h.videoUrl,h.videoURL,h.link,h.sourceUrl,h.mediaUrl,h.video].filter(Boolean);
  for(const value of fields){
    const raw = typeof value === 'string' ? value : (value?.url || value?.href || value?.embedUrl || value?.videoUrl || '');
    if(!raw) continue;
    try{
      const u=new URL(raw);
      if(u.hostname.includes('youtu.be')) return u.pathname.split('/').filter(Boolean)[0]||null;
      if(u.hostname.includes('youtube.com')){
        if(u.searchParams.get('v')) return u.searchParams.get('v');
        const parts=u.pathname.split('/').filter(Boolean);
        const ix=parts.findIndex(x=>['embed','shorts','live'].includes(x));
        if(ix>=0 && parts[ix+1]) return parts[ix+1];
      }
    }catch(e){}
  }
  return null;
}

function getMatchId(h){
  return String(h?.match?.id ?? h?.matchId ?? h?.matchID ?? h?.event?.id ?? h?.gameId ?? '');
}

function normalizeHighlights(items, league='SPORTS'){
  const seen=new Set();
  const out=[];
  for(const h of items){
    const youtubeId=youtubeIdFromHighlight(h);
    if(!youtubeId || seen.has(youtubeId)) continue;
    seen.add(youtubeId);
    const match=h.match||h.event||{};
    const away=match.awayTeam||match.away||{};
    const home=match.homeTeam||match.home||{};
    const awayName=away.abbreviation||away.displayName||away.name||'';
    const homeName=home.abbreviation||home.displayName||home.name||'';
    const matchup=awayName && homeName ? `${awayName} at ${homeName}` : '';
    const resolvedLeague=String(league||h.league||match.league||'SPORTS').toUpperCase();
    const title=h.title || matchup || `${resolvedLeague} Highlight`;
    const subtitle=h.description || matchup || `Highlightly verified ${resolvedLeague} highlight`;
    const duration=Number(h.durationSeconds||h.duration||0)||null;
    const overview=String(h.category||'').toLowerCase()==='match-highlights' || /full game highlights|game recap|game highlights|condensed game/i.test(`${title} ${subtitle}`);
    const normalizedMedia={
      id:youtubeId,
      youtubeId,
      league:resolvedLeague,
      sport:LEAGUES[resolvedLeague]?.sport||'sports',
      title,
      subtitle,
      highlightlyId:h.id,
      matchId:getMatchId(h),
      gameKey:gameKey(awayName,homeName),
      away:awayName,
      home:homeName,
      gameDate:h.__sbbDate || String(h.date || h.publishedAt || match.date || '').slice(0,10),
      dateGameKey:`${h.__sbbDate || String(h.date || h.publishedAt || match.date || '').slice(0,10)}::${gameKey(awayName,homeName)}`,
      source:'Highlightly',
      sourceLabel:String(h.sourceName||h.channelName||h.publisher||h.source||'Highlightly'),
      provider:'YOUTUBE',
      sourceType:String(h.source||''),
      category:String(h.category||''),
      thumbnail:h.imgUrl||h.thumbnail||h.image||'',
      duration,
      overview,
      chronology:[1,999,0,out.length,out.length],
      publishedAt:h.date || h.publishedAt || match.date || null,
      verifiedPlayable:true,
      association:'highlightly',
      competitionId:resolvedLeague,
      competitionName:LEAGUES[resolvedLeague]?.competition||resolvedLeague
    };
    out.push(window.SBB_CORE?.media ? window.SBB_CORE.media(normalizedMedia,resolvedLeague) : normalizedMedia);
  }
  return out;
}

const MLB_TEAM_ALIASES={
  arizonadiamondbacks:'ari',diamondbacks:'ari',ari:'ari',
atlantabraves:'atl',braves:'atl',atl:'atl',
  baltimoreorioles:'bal',orioles:'bal',bal:'bal',
  bostonredsox:'bos',redsox:'bos',bos:'bos',
  chicagocubs:'chc',cubs:'chc',chc:'chc',
  chicagowhitesox:'chw',whitesox:'chw',cws:'chw',chw:'chw',
  cincinnatireds:'cin',reds:'cin',cin:'cin',
  clevelandguardians:'cle',guardians:'cle',cle:'cle',
  coloradorockies:'col',rockies:'col',col:'col',
  detroittigers:'det',tigers:'det',det:'det',
  houstonastros:'hou',astros:'hou',hou:'hou',
  kansascityroyals:'kc',royals:'kc',kcr:'kc',kc:'kc',
  losangelesangels:'laa',angels:'laa',laa:'laa',
  losangelesdodgers:'lad',dodgers:'lad',lad:'lad',
  miamimarlins:'mia',marlins:'mia',mia:'mia',
  milwaukeebrewers:'mil',brewers:'mil',mil:'mil',
  minnesotatwins:'min',twins:'min',min:'min',
  newyorkmets:'nym',mets:'nym',nym:'nym',
  newyorkyankees:'nyy',yankees:'nyy',nyy:'nyy',
  oaklandathletics:'ath',athletics:'ath',as:'ath',ath:'ath',
  philadelphiaphillies:'phi',phillies:'phi',phi:'phi',
  pittsburghpirates:'pit',pirates:'pit',pit:'pit',
  sandiegopadres:'sd',padres:'sd',sd:'sd',
  sanfranciscogiants:'sf',giants:'sf',sf:'sf',
  seattlemariners:'sea',mariners:'sea',sea:'sea',
  stlouiscardinals:'stl',cardinals:'stl',stl:'stl',
  tampabayrays:'tb',rays:'tb',tb:'tb',tbr:'tb',
  texasrangers:'tex',rangers:'tex',tex:'tex',
  torontobluejays:'tor',bluejays:'tor',tor:'tor',
  washingtonnationals:'wsh',nationals:'wsh',was:'wsh',wsh:'wsh'
};
function normalizedTeamKey(name){
  const raw=String(name||'').toLowerCase().replace(/[^a-z0-9]/g,'');
  return MLB_TEAM_ALIASES[raw] || raw;
}
function gameKey(away,home){ return `${normalizedTeamKey(away)}__${normalizedTeamKey(home)}`; }

function programTeamLabel(name,league){
  const raw=String(name||'').trim();
  if(!raw) return '';
  if(String(league||'').toUpperCase()==='MLB'){
    const k=normalizedTeamKey(raw);
    if(k && k.length<=4) return k.toUpperCase();
  }
  if(/^[A-Z0-9]{2,5}$/.test(raw)) return raw;
  return raw;
}
function programMatchupPrefix(item){
  if(!item || isContextItem(item) || isTopPlaysItem(item) || item.eventType) return '';
  const away=programTeamLabel(item.away||item.awayTeamName||'',item.league);
  const home=programTeamLabel(item.home||item.homeTeamName||'',item.league);
  return away&&home ? `${away} vs ${home}` : '';
}
function displayProgramTitle(item){
  const title=String(item?.title||'Sports Highlight').trim();
  const matchup=programMatchupPrefix(item);
  if(!matchup) return title;
  const compact=s=>String(s||'').toLowerCase().replace(/[^a-z0-9]/g,'');
  const [away,home]=matchup.split(' vs ');
  const titleCompact=compact(title);
  // Don't duplicate a matchup that the source already put at the front.
  if(titleCompact.startsWith(compact(matchup)) ||
     (titleCompact.includes(compact(away)) && titleCompact.includes(compact(home)) && /^(?:[a-z0-9]+(?:vs|at)[a-z0-9]+)/.test(titleCompact))){
    return title;
  }
  return `${matchup} • ${title}`;
}

function normalizeMlbStatsHighlights(items){
  return items.map((h,idx)=>({
    id:h.id || `mlb-native-${idx}`,
    league:'MLB',
    sport:'baseball',
    title:h.title || `${h.away||'Away'} at ${h.home||'Home'} — MLB Highlight`,
    subtitle:h.description || `${h.away||'Away'} at ${h.home||'Home'}`,
    matchId:'',
    gamePk:String(h.gamePk||''),
    away:h.away||'',
    home:h.home||'',
    gameKey:gameKey(h.away,h.home),
    gameDate:String(h.date||'').slice(0,10),
    dateGameKey:`${String(h.date||'').slice(0,10)}::${gameKey(h.away,h.home)}`,
    scoreGameKey:`${String(h.date||'').slice(0,10)}::${gameKey(h.away,h.home)}::${h.awayScore ?? ''}-${h.homeScore ?? ''}`,
    source:h.source || 'MLB',
    sourceLabel:h.sourceLabel || h.source || 'MLB',
    provider:h.youtubeId ? 'YOUTUBE' : 'DIRECT_VIDEO',
    youtubeId:h.youtubeId || '',
    mediaUrl:h.mediaUrl || '',
    thumbnail:h.thumbnail || '',
    duration:Number.isFinite(Number(h.duration)) ? Number(h.duration) : null,
    overview:!!h.overview,
    programType:h.programType || (h.overview?'recap':'reel'),
    reelIndex:Number(h.reelIndex||0)||null,
    reelCount:Number(h.reelCount||0)||null,
    importance:Number(h.importance||0)||0,
    chronology:Array.isArray(h.chronology)?h.chronology:[1,999,0,idx,idx],
    publishedAt:h.publishedAt || h.date || null,
    verifiedPlayable:!!(h.mediaUrl||h.youtubeId),
    association:'mlb-stats'
  })).filter(x=>x.mediaUrl||x.youtubeId);
}

function sourceQuality(item){
  const sourceText=`${item?.source||''} ${item?.sourceType||''} ${item?.sourceLabel||''}`.toLowerCase();
  if(/major league baseball|\bmlb\b|\bnba\b|national basketball association|\bnfl\b|national football league|\bnhl\b|national hockey league|official/.test(sourceText)) return 100;
  if(/dodgers|padres|mets|yankees|red sox|cubs|phillies|braves|cardinals|orioles|rays|twins|royals|athletics|mariners|brewers|pirates|tigers|marlins|reds|giants|rockies|guardians|astros|rangers|angels|diamondbacks|nationals|blue jays|white sox/.test(sourceText)) return 96;
  // High-quality broadcast/local coverage is fair game when Highlightly surfaces
  // an embeddable upload. It ranks below an official league/team recap but above
  // a stitched clip set or generic third-party upload.
  if(/espn|fox sports|fs1|nbc sports|cbs sports|sportsnet|spectrum|bally|fanduel sports|sny|nesn|masn|yes network|marquee|local|broadcast|tv/.test(sourceText)) return 88;
  if(item?.source==='MLB Stats API') return 82;
  if(item?.youtubeId) return 78;
  return 60;
}

function recapDurationSeconds(item){ return window.SBB_MEDIA_CLASSIFIER?.duration?.(item) ?? (Number(item?.durationSeconds ?? item?.duration ?? 0)||0); }
function recapLooksExplicitlyExtended(item){
  const text=`${item?.title||''} ${item?.subtitle||''} ${item?.description||''}`.toLowerCase();
  return /\bextended highlights?\b|\bcondensed game\b|\bextended recap\b/.test(text);
}
function isExtendedRecap(item){ return window.SBB_MEDIA_CLASSIFIER?.extended?.(item) ?? false; }
function isGreenRecap(item){ return window.SBB_MEDIA_CLASSIFIER?.quick?.(item) ?? false; }
function isQuickRecap(item){ return isGreenRecap(item); }
function overviewQuality(item){
  const d=recapDurationSeconds(item);
  // v2.7: programming duration preference is owned by SportMediaPolicy, not
  // baseball-era hard-coded thresholds. The same resolver policy therefore
  // governs score clicks, background programming, and future competitions.
  const eventLike=knownMatchForMedia(item)||item;
  const policy=window.SBB_SPORT_MEDIA_POLICY?.policyFor?.(eventLike);
  const durationScore=window.SBB_SPORT_MEDIA_POLICY?.durationScore?.(d,policy?.quick)||0;
  const text=`${item?.title||''} ${item?.subtitle||''}`.toLowerCase();
  let typeScore=0;
  if(/game recap|recap/.test(text)) typeScore=38;
  else if(/game highlights|full game highlights/.test(text)) typeScore=34;
  else if(/condensed game/.test(text)) typeScore=15;
  const goldBoost=isGoldRecap(item)?85:0;
  return sourceQuality(item)+(durationScore*2.8)+typeScore+goldBoost;
}
function choosePrimaryRecap(overviews){
  const pool=[...(overviews||[])];
  if(!pool.length) return null;
  const gold=pool.filter(isGoldRecap);
  if(gold.length){ gold.sort((a,b)=>overviewQuality(b)-overviewQuality(a)); return gold[0]; }
  const quick=pool.filter(isQuickRecap);
  const preferred=quick.length?quick:pool;
  preferred.sort((a,b)=>overviewQuality(b)-overviewQuality(a));
  return preferred[0]||null;
}
function attachRecapAlternates(primary,overviews){
  if(!primary) return primary;
  const alternatives=[];
  const add=(x)=>{
    if(!x||x.id===primary.id||!isFullRecapCandidate(x)||!x.verifiedPlayable||!(x.youtubeId||x.mediaUrl)) return;
    if(!sameCanonicalGame(primary,x)) return;
    if(!alternatives.some(y=>y.id===x.id)) alternatives.push(x);
  };
  for(const x of (overviews||[])) add(x);
  for(const x of RECAP_CANDIDATE_REGISTRY.values()) add(x);
  alternatives.sort((a,b)=>overviewQuality(b)-overviewQuality(a));
  return {...primary,recapAlternates:alternatives};
}

function candidateGroupKey(item){
  const lg=String(item?.competitionId||item?.league||'SPORTS').toUpperCase();
  return item.matchId ? `${lg}:match:${item.matchId}` : (item.scoreGameKey ? `${lg}:${item.scoreGameKey}` : (item.dateGameKey ? `${lg}:${item.dateGameKey}` : (item.gameDate&&item.gameKey?`${lg}:${item.gameDate}::${item.gameKey}`:(item.gameKey?`${lg}:${item.gameKey}`:canonicalRecapMatchKey(item)))));
}

function rememberAllCandidates(items){
  const map=new Map();
  for(const item of items){
    const keys=[candidateGroupKey(item),canonicalRecapMatchKey(item)].filter(Boolean);
    for(const key of keys){
      if(!map.has(key)) map.set(key,[]);
      const group=map.get(key);
      if(!group.some(x=>x.id===item.id)) group.push(item);
    }
  }
  for(const group of map.values()) group.sort((a,b)=>(overviewQuality(b)-overviewQuality(a)));
  ALL_GAME_CANDIDATES=map;
}

function preferGameOverviews(items){
  rememberAllCandidates(items);
  const groups=new Map(), loose=[];
  for(const item of items){
    const key=canonicalRecapMatchKey(item) || candidateGroupKey(item);
    if(!key){loose.push(item);continue;}
    if(!groups.has(key)) groups.set(key,[]);
    groups.get(key).push(item);
  }
  const out=[];
  for(const group of groups.values()){
    const allPlayable=group.filter(x=>x.verifiedPlayable && (x.youtubeId||x.mediaUrl));
    const playable=FORCE_BLUE_TEST ? allPlayable.filter(x=>!isFullRecapCandidate(x)).map(asForcedBlueClip) : allPlayable;
    const overviews=FORCE_BLUE_TEST?[]:playable.filter(isFullRecapCandidate);
    if(overviews.length){
      const primary=choosePrimaryRecap(overviews);
      const best={...attachRecapAlternates(primary,overviews), candidateCount:allPlayable.length, sourceLabel:primary.sourceLabel||primary.source};
      out.push(best);
    } else {
      playable.sort((a,b)=>{
        const aa=a.chronology||[9,999,0,0,0], bb=b.chronology||[9,999,0,0,0];
        for(let i=0;i<Math.max(aa.length,bb.length);i++){const d=(aa[i]||0)-(bb[i]||0);if(d)return d;}
        return sourceQuality(b)-sourceQuality(a);
      });
      // Keep a concise chronological story rather than every available play.
      out.push(...playable.slice(0,5).map(x=>({...x,candidateCount:allPlayable.length,sourceLabel:x.sourceLabel||x.source})));
    }
  }
  return [...out,...loose];
}


function mediaGameKey(item){
  return programGameIdentity(item)||String(item?.matchId||item?.gamePk||item?.gameId||item?.id||'');
}
function verifiedMediaKindsForGame(game){
  const key=mediaGameKey(game);
  return new Set(VERIFIED_MEDIA_BY_MATCH.get(key)||[]);
}
function verifiedMediaKind(item){
  if(!item?.verifiedPlayable) return '';
  const type=String(item.programType||item.type||item.mediaType||'').toLowerCase();
  const dur=Number(item.durationSeconds??item.duration)||0;
  if(item.commentated || /commentary|commentated|analysis recap/.test(type)) return 'commentary';
  if(item.extended || /extended|condensed|full[- ]?game/.test(type) || dur>=8*60) return 'extended';
  if(/reel|highlight[- ]?reel|game clip/.test(type) || (dur>0 && dur<120)) return 'reel';
  if(/recap|overview|full recap/.test(type) || (dur>=120 && dur<8*60)) return 'recap';
  return '';
}
function rebuildVerifiedMediaIndex(items){
  const kindsMap=new Map();
  const itemMap=new Map();

  for(const item of (items||[])){
    if(!item?.verifiedPlayable || !(item.youtubeId||item.mediaUrl)) continue;
    const kind=verifiedMediaKind(item);
    if(!kind) continue;

    const keys=[];
    if(item.matchId) keys.push(`match:${String(item.competitionId||item.league||'SPORTS').toUpperCase()}:${item.matchId}`);
    if(item.scoreGameKey && !String(item.scoreGameKey).endsWith('::-')) keys.push(`scoregame:${item.scoreGameKey}`);
    if(item.gameKey && item.gameDate) keys.push(`game:${item.gameDate}:${item.gameKey}`);
    const fallback=mediaGameKey(item);
    if(fallback) keys.push(`identity:${fallback}`);

    for(const key of [...new Set(keys)]){
      if(!kindsMap.has(key)) kindsMap.set(key,new Set());
      kindsMap.get(key).add(kind);

      if(!itemMap.has(key)) itemMap.set(key,[]);
      const arr=itemMap.get(key);
      if(!arr.some(x=>String(x.id)===String(item.id))) arr.push(item);
    }
  }

  VERIFIED_MEDIA_BY_MATCH.clear();
  VERIFIED_PLAYABLES_BY_MATCH.clear();
  for(const [key,kinds] of kindsMap) VERIFIED_MEDIA_BY_MATCH.set(key,[...kinds]);
  for(const [key,arr] of itemMap) VERIFIED_PLAYABLES_BY_MATCH.set(key,arr);
}

function scoreGameLookupKeys(game,leagueOverride=''){
  const lg=String(leagueOverride||game?.competitionId||game?.__sbbLeague||game?.league||'SPORTS').toUpperCase();
  const away=game?.awayTeam||game?.away||{};
  const home=game?.homeTeam||game?.home||{};
  const matchId=String(game?.id??game?.matchId??game?.eventId??'');
  const date=String(game?.__sbbDate||game?.date||'').slice(0,10);
  const key=gameKey(teamAbbr(away,''),teamAbbr(home,''));
  const sc=scoreFromMatch(game||{});
  const keys=[];
  if(matchId) keys.push(`match:${lg}:${matchId}`);
  if(date && key && key!=='-'){
    keys.push(`game:${date}:${key}`);
    keys.push(`scoregame:${date}::${key}::${sc.away}-${sc.home}`);
  }
  const identity=mediaGameKey(game);
  if(identity) keys.push(`identity:${identity}`);
  return [...new Set(keys)];
}

function verifiedPlayableItemsForGame(game,leagueOverride=''){
  const items=[];
  const seen=new Set();
  for(const key of scoreGameLookupKeys(game,leagueOverride)){
    for(const item of (VERIFIED_PLAYABLES_BY_MATCH.get(key)||[])){
      const id=String(item.id||item.youtubeId||item.mediaUrl||'');
      if(!id || seen.has(id)) continue;
      seen.add(id);
      items.push(item);
    }
  }
  return preferGameOverviews(items);
}

function indexHighlightsByMatch(candidates){
  const incomingLeagues=[...new Set((candidates||[]).map(x=>String(x?.competitionId||x?.league||'SPORTS').toUpperCase()))];
  for(const lg of incomingLeagues){
    INDEX_CANDIDATES_BY_LEAGUE.set(lg,(candidates||[]).filter(x=>String(x?.competitionId||x?.league||'SPORTS').toUpperCase()===lg));
  }
  candidates=[...INDEX_CANDIDATES_BY_LEAGUE.values()].flat();
  const externalCandidates=[...EXTERNAL_CANDIDATES_BY_LEAGUE.values()].flat();
  if(externalCandidates.length) candidates=[...candidates,...externalCandidates];
  const map = new Map();
  const externalMap = new Map();
  for(const item of candidates){
    if(!mediaMatchesKnownGame(item)){
      try{ console.warn('[SBB media identity] rejected mismatched full recap',{title:item?.title,away:item?.away,home:item?.home,matchId:item?.matchId||item?.gamePk}); }catch(_){ }
      continue;
    }
    const keys=[];
    if(item.matchId) keys.push(`match:${String(item.competitionId||item.league||'SPORTS').toUpperCase()}:${item.matchId}`);
    if(item.scoreGameKey && !item.scoreGameKey.endsWith('::-')) keys.push(`scoregame:${item.scoreGameKey}`);
    if(item.gameKey && item.gameDate) keys.push(`game:${item.gameDate}:${item.gameKey}`);
    const identity=mediaGameKey(item); if(identity) keys.push(`identity:${identity}`);
    // Preserve official external-only packages as catalog evidence only. They do
    // not paint a playable score-card state or open a website from the score rail;
    // only positively validated assets may enter PlaybackController.
    if(item.externalOnly && item.externalUrl){
      for(const key of keys){
        if(!externalMap.has(key)) externalMap.set(key,[]);
        const arr=externalMap.get(key);
        if(!arr.some(x=>String(x.id)===String(item.id))) arr.push(item);
      }
      continue;
    }
    // The ribbon is intentionally stricter than the general queue: a play control
    // is only exposed when the item already has a supported playback target.
    if(!item.verifiedPlayable) continue;
    if(!(item.youtubeId || item.mediaUrl)) continue;
    // MLB Stats items do not share Highlightly match IDs; exact canonical keys above
    // are the only permitted fallback association.
    for(const key of keys){
      if(!map.has(key)) map.set(key, []);
      map.get(key).push(item);
    }
  }
  HIGHLIGHTS_BY_MATCH = map;
  EXTERNAL_MEDIA_BY_MATCH.clear();
  for(const [key,arr] of externalMap) EXTERNAL_MEDIA_BY_MATCH.set(key,arr);
}

function normTeamText(value){ return String(value||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim(); }
function favoriteAliasGroups(){
  const favs=favoriteTeams(); if(!favs.length) return [];
  const teams=[];
  for(const state of LIVE_MATCHES_BY_LEAGUE.values()) for(const m of [...(state.yesterday||[]),...(state.today||[])]){
    for(const t of [m.awayTeam||m.away||{},m.homeTeam||m.home||{}]){
      const aliases=[t.displayName,t.name,t.shortName,t.abbreviation,t.abbr].map(normTeamText).filter(Boolean);
      if(aliases.length) teams.push([...new Set(aliases)]);
    }
  }
  return favs.map(f=>{
    const nf=normTeamText(f); const matched=teams.find(group=>group.some(x=>x===nf || x.includes(nf) || nf.includes(x)));
    return matched||[nf];
  });
}
function itemMatchesFavoriteTeam(item){
  const groups=favoriteAliasGroups(); if(!groups.length) return false;
  const hay=normTeamText(`${item?.title||''} ${item?.subtitle||''} ${item?.away||''} ${item?.home||''} ${item?.gameKey||''}`);
  const direct=[item?.away,item?.home].map(normTeamText).filter(Boolean);
  return groups.some(group=>group.some(alias=>alias && (direct.includes(alias) || new RegExp(`(?:^|\\s)${alias.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')}(?:$|\\s)`).test(hay))));
}
function matchHasFavoriteTeam(m){
  const away=m?.awayTeam||m?.away||{}, home=m?.homeTeam||m?.home||{};
  return itemMatchesFavoriteTeam({title:`${fullTeamName(away)} ${fullTeamName(home)}`,away:teamAbbr(away,''),home:teamAbbr(home,'')});
}
function favoriteTeamBoost(item){ return itemMatchesFavoriteTeam(item) ? 42 : 0; }
function deterministicStakesScore(item){
  const t=`${item?.title||''} ${item?.subtitle||''} ${item?.description||''} ${item?.round||''} ${item?.stage||''}`.toLowerCase();
  let s=0;
  if(/super bowl/.test(t)) s=Math.max(s,100);
  if(/world cup final|fifa world cup final/.test(t)) s=Math.max(s,97);
  if(/stanley cup final|nba finals|world series|championship game|national championship|champions league final|mls cup final/.test(t)) s=Math.max(s,94);
  if(/game\s*7|winner-take-all|winner take all/.test(t)) s=Math.max(s,92);
  if(/conference final|conference finals|semifinal|semi-final|game\s*6/.test(t)) s=Math.max(s,84);
  if(/playoff|postseason|wild card|knockout|elimination|clinching|clinch|play-in|play in/.test(t)) s=Math.max(s,72);
  if(/playoff implication|must-win|must win|division lead|wild card race|pennant race/.test(t)) s=Math.max(s,66);
  if(/record|milestone|no-hitter|perfect game|hat trick|walk-?off|buzzer|game[- ]winner/.test(t)) s=Math.max(s,58);
  return s;
}
function aiProgramScore(item){ return Number(AI_PROGRAM_RANKINGS.get(String(item?.id||''))?.score||0); }
function scoreCandidateId(m){
  const lg=String(m?.__sbbLeague||m?.league||'').toUpperCase();
  const away=m?.awayTeam||m?.away||{}, home=m?.homeTeam||m?.home||{};
  const date=String(m?.__sbbDate||m?.date||'').slice(0,10);
  return `score:${lg}:${String(m?.id??m?.matchId??m?.eventId??`${date}:${gameKey(teamAbbr(away,''),teamAbbr(home,''))}`)}`;
}
function compactScoreRankingCandidate(m){
  const lg=String(m?.__sbbLeague||m?.league||'').toUpperCase();
  const away=m?.awayTeam||m?.away||{}, home=m?.homeTeam||m?.home||{};
  const extras=[m?.competitionName,m?.league?.name,m?.round,m?.stage,m?.week,m?.seasonType,m?.name,m?.title].filter(Boolean).join(' • ');
  return {id:scoreCandidateId(m),league:lg,title:`${fullTeamName(away)||teamAbbr(away,'Away')} at ${fullTeamName(home)||teamAbbr(home,'Home')}`,subtitle:`${extras} • ${stateText(m)}`.slice(0,180),status:stateText(m),eventType:'game',publishedAt:String(m?.date||''),importance:deterministicStakesScore({title:extras,subtitle:stateText(m)}),isLive:isLive(m),gameDate:String(m?.__sbbDate||m?.date||'').slice(0,10),category:'game'};
}
function collectScoreRankingCandidates(){
  const rows=[]; for(const state of LIVE_MATCHES_BY_LEAGUE.values()) rows.push(...(state.today||[]));
  return rows.slice(0,40);
}
function aiScoreRibbonScore(m){ return Number(AI_SCORE_RANKINGS.get(scoreCandidateId(m))?.score||0); }
function compactRankingCandidate(item){
  return {id:String(item?.id||''),league:String(item?.league||''),title:String(item?.title||'').slice(0,180),subtitle:String(item?.subtitle||'').slice(0,180),status:String(item?.status||''),eventType:String(item?.eventType||item?.programType||''),publishedAt:String(item?.publishedAt||''),importance:Number(item?.importance||0),isLive:!!item?.isLive,gameDate:String(item?.gameDate||item?.date||''),category:isTopPlaysItem(item)?'top-play':(isFullRecapCandidate(item)?'game-recap':'clip')};
}
async function requestAIProgrammingRanks(items){
  const playable=(items||[]).filter(x=>x?.verifiedPlayable&&(x.youtubeId||x.mediaUrl)&&!isContextItem(x));
  if(!playable.length) return;
  const today=localDateISO(0);
  const queueCandidates=playable.slice().sort((a,b)=>publishedTimeMs(b)-publishedTimeMs(a)).slice(0,36);
  const topCandidates=queueCandidates.filter(x=>!isFullRecapCandidate(x) && String(x.gameDate||x.__sbbDate||x.date||x.publishedAt||'').slice(0,10)===today).slice(0,30);
  const scoreSig=collectScoreRankingCandidates().map(m=>`${scoreCandidateId(m)}:${stateText(m)}`).join('|');
  const sig=[...queueCandidates,...topCandidates].map(x=>x.id).join('|')+'::'+scoreSig+'::'+favoriteTeams().join('|');
  if(aiRankInFlight || (sig===aiRankSignature && Date.now()-aiRankLastAt < DIRECTOR_MODE_TTL)) return;
  aiRankInFlight=true; aiRankSignature=sig;
  try{
    const post=async(mode,candidates)=>{
      if(!candidates.length) return [];
      const r=await fetch('/api/editorial/program-rank',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode,candidates:mode==='score-ribbon'?candidates:candidates.map(compactRankingCandidate),favoriteTeams:favoriteTeams(),localDate:today})});
      if(!r.ok) throw new Error(`program-rank HTTP ${r.status}`);
      return responseItems(await r.json());
    };
    const scoreCandidates=collectScoreRankingCandidates();
    const [queueRanks,topRanks,scoreRanks]=await Promise.all([post('queue',queueCandidates),post('top-plays',topCandidates),post('score-ribbon',scoreCandidates.map(compactScoreRankingCandidate))]);
    for(const x of queueRanks) AI_PROGRAM_RANKINGS.set(String(x.id),x);
    for(const x of topRanks) AI_TOP_PLAY_RANKINGS.set(String(x.id),x);
    for(const x of scoreRanks) AI_SCORE_RANKINGS.set(String(x.id),x);
    aiRankLastAt=Date.now();
    saveDirectorCache(queueRanks,scoreRanks);
    // Refine only upcoming programming. The active item/index stays fixed.
    const activeId=clip(currentIndex)?.id;
    directorApplyPending=true;
    try{
      mergeLiveProgram([],false);
      if(activeId){
        const keep=program.findIndex(x=>String(x.id)===String(activeId));
        if(keep>=0) currentIndex=keep;
      }
      renderQueue();
      renderScoresFromMatchesCombined(true);
    }catch(_){}
    directorApplyPending=false;

    // Rebuild the remainder and score ribbon with the same sports-director ranking.
    setTimeout(()=>{ mergeLiveProgram([],false); renderScoresFromMatchesCombined(); },0);
  }catch(err){
    aiRankLastAt=Date.now();
    console.warn('[SBB v4.3.6] AI programming rank unavailable; deterministic ranking remains active',err);
  }
  finally{ aiRankInFlight=false; }
}
function programUnitPublishedMs(unit){
  return Math.max(0,...(unit||[]).map(publishedTimeMs));
}

// v2.1 programming brain: rank units like a live sports channel instead of simply
// sorting by game bucket. Freshness dominates, then completeness/importance/source.
function programUnitScore(unit){
  const items=unit||[];
  if(!items.length) return -1e9;
  const lead=items[0]||{};
  const published=programUnitPublishedMs(items);
  const ageHours=published?Math.max(0,(Date.now()-published)/3600000):36;
  // Aggressive freshness decay: a 45-minute recap should beat yesterday's recap.
  let score=Math.max(0,105-ageHours*5); // freshness matters, but championship stakes must survive into the next day
  const isContext=isContextItem(lead);
  const isTopPlays=isTopPlaysItem(lead);
  const isEvent=!!(lead.eventType||lead.programType==='event'||isContext||isTopPlays);
  const hasRecap=!isContext && items.some(isFullRecapCandidate);
  const isBlue=!hasRecap && items.length>0 && items.every(x=>!isFullRecapCandidate(x));
  if(hasRecap) score+=24;                 // complete game story
  if(isBlue) score+=Math.min(18,items.length*3); // useful rapid reel
  if(isContext) score=78; // context cards are connective tissue, not breaking-video replacements
  else if(isTopPlays) score=Math.max(score,88);
  else if(isEvent) score+=Math.min(35,Number(lead.importance||0)*0.35);
  if(/official|mlb stats|nba|nfl|nhl|premier league/i.test(String(lead.sourceLabel||lead.source||''))) score+=8;
  if(/espn|fox|cbs|nbc|sportsnet/i.test(String(lead.sourceLabel||lead.source||''))) score+=5;
  // Recently completed/live events should surface aggressively.
  if(lead.isLive||/live|in progress/i.test(String(lead.status||''))) score+=35;
  if(ageHours<=1) score+=20; else if(ageHours<=3) score+=12; else if(ageHours<=8) score+=5;
  const stakes=deterministicStakesScore(lead);
  score+=stakes*1.35;
  // OpenAI is a semantic editor on top of hard sports rules, not the sole ranking authority.
  score+=aiProgramScore(lead)*0.9;
  // Favorites get a meaningful boost but cannot normally leapfrog a championship-level event.
  score+=favoriteTeamBoost(lead);
  return score;
}
function isFreshProgrammingItem(item){
  const ms=publishedTimeMs(item);
  if(!ms) return true;
  const age=Date.now()-ms;
  if(isContextItem(item)) return age <= 6*3600_000;
  if(isTopPlaysItem(item)) return String(item.topPlaysDate||'')===localDateISO(0);
  // Game coverage is keyed to a real event and may remain useful into the next day.
  if(programGameIdentity(item) && !(item.eventType||item.programType==='event'||item.programType==='context')) return age <= 72*3600_000;
  // Generic/news videos must be genuinely current unless editorial importance is exceptional.
  return age <= 48*3600_000 || Number(item.importance||0)>=90;
}

function updateRecapCandidateRegistry(items){
  const now=Date.now();
  for(const x of items||[]){
    if(isFullRecapCandidate(x) && x.verifiedPlayable && (x.youtubeId||x.mediaUrl)) RECAP_CANDIDATE_REGISTRY.set(String(x.id),x);
  }
  for(const [id,x] of RECAP_CANDIDATE_REGISTRY){
    const ms=publishedTimeMs(x)||itemGameDateMs(x)||now;
    if(now-ms>96*3600_000) RECAP_CANDIDATE_REGISTRY.delete(id);
  }
}
function collapseCanonicalGameMedia(items){
  const clusters=[];
  const special=[];
  for(const item of items||[]){
    if(isContextItem(item)||isTopPlaysItem(item)||item.eventType||item.programType==='event'){ special.push(item); continue; }
    let cluster=clusters.find(c=>sameCanonicalGame(c[0],item));
    if(!cluster){ cluster=[]; clusters.push(cluster); }
    cluster.push(item);
  }
  const out=[];
  for(const cluster of clusters){
    const recaps=cluster.filter(isFullRecapCandidate);
    if(recaps.length){
      const primary=choosePrimaryRecap(recaps);
      out.push(attachRecapAlternates(primary,recaps));
    }else out.push(...cluster);
  }
  return [...out,...special];
}
function mergeLiveProgram(candidates, first){
  const current = clip(currentIndex);
  const currentId=current?.id;
  const currentMediaKey=playbackItemKey(current);
  // v1.9.1: each league owns a current candidate snapshot. Updating MLB must not
  // erase NBA/NFL/NHL programming, and vice versa.
  const incomingLeagues=[...new Set((candidates||[]).map(x=>String(x?.competitionId||x?.league||'SPORTS').toUpperCase()))];
  for(const lg of incomingLeagues){
    LIVE_CANDIDATES_BY_LEAGUE.set(lg,(candidates||[]).filter(x=>String(x?.competitionId||x?.league||'SPORTS').toUpperCase()===lg));
  }
  candidates=[...LIVE_CANDIDATES_BY_LEAGUE.values()].flat();
  if(RAPID_MLB_CANDIDATES.length) candidates.push(...RAPID_MLB_CANDIDATES);
  if(SPORTS_EVENT_CANDIDATES.length) candidates.push(...SPORTS_EVENT_CANDIDATES);
  if(TOP_PLAYS_CANDIDATES.length) candidates.push(...TOP_PLAYS_CANDIDATES);
  const currentLeague = current?.competitionId || current?.league || 'SPORTS';
  const unique=[];
  const seen=new Set();
  for(const raw of candidates){
    const lg=String(raw?.competitionId||raw?.league||'SPORTS').toUpperCase();
    const x={sport:LEAGUES[lg]?.sport||raw?.sport||'sports',...raw,league:lg};
    if(!mediaMatchesKnownGame(x)) continue;
    if(!isFreshProgrammingItem(x)) continue;
    const uid=`${lg}:${x.id}`;
    if(!seen.has(uid)){ seen.add(uid); unique.push(x); }
  }
  if(!unique.length) return;
  const generatedTopPlays=buildGeneratedTopPlays(unique);
  if(generatedTopPlays.length) unique.push(...generatedTopPlays);
  updateRecapCandidateRegistry(unique);
  requestAIProgrammingRanks(unique);

  // v1.8.2: one game gets one Around-the-League program entry when a full recap exists.
  // This prevents a 12-minute recap from being followed by a 3-minute recap and then
  // an isolated play from the same game. Blue fallback clips are kept together only
  // when there is no overview for that game.
  const grouped=new Map(), loose=[];
  for(const item of unique){
    const key=programGameIdentity(item);
    if(!key){ loose.push(item); continue; }
    if(!grouped.has(key)) grouped.set(key,[]);
    grouped.get(key).push(item);
  }
  const gamePrograms=[];
  for(const rawGroup of grouped.values()){
    const group=FORCE_BLUE_TEST ? rawGroup.filter(x=>!isFullRecapCandidate(x)).map(asForcedBlueClip) : rawGroup;
    if(!group.length) continue;
    const overviews=FORCE_BLUE_TEST?[]:group.filter(isFullRecapCandidate);
    if(overviews.length){
      const primary=choosePrimaryRecap(overviews);
      gamePrograms.push(attachRecapAlternates(primary,overviews));
    }else{
      group.sort((a,b)=>{
        const aa=a.chronology||[9,999,0,0,0], bb=b.chronology||[9,999,0,0,0];
        for(let i=0;i<Math.max(aa.length,bb.length);i++){const d=(aa[i]||0)-(bb[i]||0);if(d)return d;}
        return 0;
      });
      gamePrograms.push(...group);
    }
  }
  // v1.9.11: programming is newest-first across games and key-information videos.
  // A blue reel remains a single chronological unit internally, while game/event
  // units are sorted by their newest published asset. This means "latest first"
  // never reverses the play order inside a game's highlight story.
  const combined=collapseCanonicalGameMedia([...gamePrograms,...loose]);
  const contextUnits=combined.filter(isContextItem).map(x=>[x]);
  const eventUnits=combined.filter(x=>!isContextItem(x) && !isTopPlaysItem(x) && (x.eventType || x.programType==='event')).map(x=>[x]);
  const packagedTopPlayUnits=combined.filter(x=>x.programType==='top-plays').map(x=>[x]);
  const gameItems=combined.filter(x=>!isContextItem(x) && x.programType!=='top-plays' && !(x.eventType || x.programType==='event'));
  const gameUnits=[];
  for(const item of gameItems){
    const last=gameUnits[gameUnits.length-1];
    if(last && sameGameProgramItem(last[0],item)) last.push(item); else gameUnits.push([item]);
  }
  const units=[...gameUnits,...eventUnits,...packagedTopPlayUnits];
  units.sort((a,b)=>{
    const scoreDelta=programUnitScore(b)-programUnitScore(a);
    if(Math.abs(scoreDelta)>0.01) return scoreDelta;
    return programUnitPublishedMs(b)-programUnitPublishedMs(a);
  });
  // Context graphics are connective tissue: place one after roughly three normal
  // programs rather than allowing their fresh timestamp to dominate the ranking.
  if(contextUnits.length){
    let insertAt=3;
    for(const contextUnit of contextUnits){
      units.splice(Math.min(insertAt,units.length),0,contextUnit);
      insertAt+=5;
    }
  }
  let mixed=units.flat();

  // v2.2.1 live reranking: if something is already playing, keep the current
  // game's remaining tail at the front and place every OTHER program unit after
  // it in fresh editorial rank order. Previously a newly discovered high-score
  // recap could sort *before* the current item and become invisible until the
  // queue wrapped all the way around.
  if(currentId && !userPlaybackSession){
    const activeUnitIndex=units.findIndex(unit=>unit.some(x=>x?.id===currentId));
    if(activeUnitIndex>=0){
      const activeUnit=units[activeUnitIndex];
      const activePos=Math.max(0,activeUnit.findIndex(x=>x?.id===currentId));
      const activeTail=activeUnit.slice(activePos);
      const rankedRest=units.filter((_,i)=>i!==activeUnitIndex).flat();
      mixed=[...activeTail,...rankedRest];
    }
  }

  const launchRoundups=roundupMediaForScoreDate(localDateISO(0),'ALL');
  const baseGeneral=mixed.length?mixed:combined;
  // Game programs own startup. Silver collections remain available in the queue but
  // never preempt the first verified game merely because their collection is fresh.
  GENERAL_PROGRAM=[...baseGeneral,...launchRoundups.filter(x=>!baseGeneral.some(g=>playbackItemKey(g)===playbackItemKey(x)))];
  if(userPlaybackSession){ renderQueue(); updateRecapAlternateButton(); return; } // Direct user selection owns PROGRAM; GENERAL_PROGRAM still refreshes.

  // v4.3.6: once the viewer starts a date-specific session, background live-feed
  // refreshes may enrich that date but may not silently replace its queue with the
  // general Today/Yesterday programming feed.
  if(playbackDateContext?.date){
    const scoped=programForScoreDate(playbackDateContext.date);
    if(scoped.length){
      const playing=clip(currentIndex); const playingKey=playbackItemKey(playing);
      const found=playingKey?scoped.findIndex(x=>playbackItemKey(x)===playingKey):-1;
      // A background catalog refresh may not restart or replace the active video.
      // Retain the exact active object if the refreshed snapshot momentarily omits it.
      PROGRAM=found>=0?scoped:(playing?[playing,...scoped.filter(x=>playbackItemKey(x)!==playingKey)]:scoped);
      currentIndex=found>=0?found:0;
      const next=nextUnplayedIndex(PROGRAM,currentIndex,1);
      if(next>=0) prepareStandby(otherSlot(activeSlot),next);
      renderQueue(); updateRecapAlternateButton();
      return;
    }
  }

  // v1.9.11 startup programming: the program is reverse chronological, so start
  // with the newest playable unviewed unit rather than a random item.
  if(first && !startupLiveAutoplayDone){
    startupLiveAutoplayDone=true;
    PROGRAM=GENERAL_PROGRAM;
    const playableIndexes=PROGRAM.map((x,i)=>x?.verifiedPlayable&&(x.youtubeId||x.mediaUrl)&&!isGamePlayed(x)?i:-1).filter(i=>i>=0);
    if(!playableIndexes.length){ showAllCaughtUp(); return; }
    const target=playableIndexes[0];
    const item=PROGRAM[target];
    startupAutoplayAttempted=true;
    currentIndex=target;
    standbyIndex=target;
    showBumper(target,850,'STARTING SPORTS BIG BOARD');
    // Startup uses the same controller as every other deliberate tune once a
    // provider player is ready. If YouTube is still booting, only record the
    // assignment; createPlayer(onReady) will start that exact item later.
    if(isContextItem(item) || isNativeItem(item) || playerReady[activeSlot] || playerReady[otherSlot(activeSlot)]){
      PlaybackController.tuneProgramIndex(target,{userInitiated:false,reason:'startup live program'});
    }else{
      configureSlotForItem(activeSlot,item,true);
      renderMetadata();
      renderQueue();
    }
    return;
  }

  // A user-selected extended/quick alternate owns the current slot until it
  // completes or the user navigates away. Background discovery may update the
  // general queue, but must not replace the chosen version mid-video.
  if(manualRecapAlternate){ renderQueue(); updateRecapAlternateButton(); return; }

  // Normal background refresh is not a playback command. Preserve the exact
  // active media key/object even if a provider snapshot temporarily renames or omits
  // it; otherwise a refresh can silently retune the slot and restart the clip.
  PROGRAM=GENERAL_PROGRAM;
  let found=currentMediaKey ? PROGRAM.findIndex(x=>playbackItemKey(x)===currentMediaKey) : -1;
  if(found<0&&current){PROGRAM=[current,...PROGRAM.filter(x=>playbackItemKey(x)!==currentMediaKey)];found=0;}
  currentIndex=found>=0?found:Math.min(Math.max(0,currentIndex),Math.max(0,PROGRAM.length-1));
  const next=nextUnplayedIndex(PROGRAM,currentIndex,1);
  if(next>=0) prepareStandby(otherSlot(activeSlot), next);
  // Reconcile assignment only. If the exact active claim is already correct, do not
  // issue another provider play() request merely because metadata refreshed.
  const claim=slotAssignment[activeSlot];
  if(!claim||claim.key!==playbackItemKey(clip(currentIndex)))reconcileActiveSlot({autoplay:!manualPauseRequested,userInitiated:false,reason:'program refresh changed active assignment'});
  renderMetadata();
  renderQueue();
}
function scoreFromMatch(m){
  const st=m?.state||{};
  const score=st.score||m.score||{};
  const lg=String(m?.competitionId||m?.__sbbLeague||m?.league||'SPORTS').toUpperCase();
  // NBA/NFL expose quarter scoring arrays. Sum them for the scoreboard total.
  const sumSide=v=>Array.isArray(v)?v.reduce((a,x)=>a+(Number(x)||0),0):null;
  const awayArr=sumSide(score.awayTeam), homeArr=sumSide(score.homeTeam);
  if(awayArr!==null && homeArr!==null) return {away:awayArr,home:homeArr};
  // Highlightly baseball exposes the actual run total in score.current (e.g. "5 - 8").
  // score.home / score.away are inning-detail objects, not the run totals.
  const cur=String(score.current ?? st.current ?? '').trim().split(/\s*[-:]\s*/);
  if(cur.length===2 && cur.every(x=>/^\d+$/.test(String(x).trim()))){
    // Highlightly MLB/NHL current strings are represented home-away in the feeds we use.
    // NBA/NFL normally arrive as per-period arrays above.
    if(lg==='MLB' || lg==='NHL' || lg==='EPL' || lg==='MLS') return {away:cur[1].trim(), home:cur[0].trim()};
    return {away:cur[0].trim(), home:cur[1].trim()};
  }
  const primitive = v => (typeof v === 'number' || typeof v === 'string') ? v : null;
  const away=primitive(score.awayScore) ?? primitive(m.awayScore) ?? primitive(score.away);
  const home=primitive(score.homeScore) ?? primitive(m.homeScore) ?? primitive(score.home);
  return {away:away ?? '–', home:home ?? '–'};
}

function teamLogo(team){
  const raw=team?.logo || team?.logoUrl || team?.image || team?.imageUrl || '';
  return typeof raw === 'string' ? raw.trim() : '';
}
function teamAbbr(team, fallback){
  return String(team?.abbreviation || team?.abbr || team?.displayName || team?.name || fallback).trim();
}
function buildTeamRow(team, score, showScore){
  const row=document.createElement('div');
  row.className='score-team-row';
  const logoWrap=document.createElement('span');
  logoWrap.className='score-team-logo-wrap';
  const fallback=document.createElement('span');
  fallback.className='score-team-logo-fallback';
  fallback.textContent=teamAbbr(team,'?').slice(0,3);
  const url=teamLogo(team);
  if(url){
    const img=document.createElement('img');
    img.className='score-team-logo';
    img.src=url;
    img.alt='';
    img.loading='lazy';
    img.addEventListener('error',()=>{img.remove(); fallback.hidden=false;});
    fallback.hidden=true;
    logoWrap.append(img,fallback);
  } else { logoWrap.append(fallback); }
  const abbr=document.createElement('strong');
  abbr.className='score-team-abbr';
  abbr.textContent=teamAbbr(team,'TEAM');
  const scoreEl=document.createElement('b');
  scoreEl.className='score-team-score';
  scoreEl.textContent=showScore ? String(score) : '';
  row.append(logoWrap,abbr,scoreEl);
  return row;
}

function stateText(m){
  const st=m?.state||{};
  return String(st.report||st.description||st.status||m.status||'').trim();
}
function isFinal(m){ return /final|finished|ended|complete/i.test(stateText(m)); }
function isLive(m){ return /live|progress|inning|top |bottom |bot |middle|delay|first half|second half|half time|extra time|penalties|break time|in play/i.test(stateText(m)) && !isFinal(m); }

function formatPeriodLabel(league,period){
  const p=Number(period)||0; if(!p) return '';
  if(league==='NBA') return `Q${p}`; if(league==='NFL') return `Q${p}`; if(league==='NHL') return `P${p}`;
  return String(p);
}
function formatClockValue(value){
  if(value===null||value===undefined||value==='') return '';
  if(typeof value==='string'){ const t=value.trim(); if(/^\d{1,2}:\d{2}$/.test(t)) return t; const n=Number(t); if(Number.isFinite(n)) value=n; else return t; }
  if(typeof value==='number' && Number.isFinite(value)){
    if(value>60){ const sec=Math.max(0,Math.round(value)); return `${Math.floor(sec/60)}:${String(sec%60).padStart(2,'0')}`; }
    return `${Math.max(0,Math.floor(value))}:00`;
  }
  return '';
}
function liveClockText(m){
  const st=m?.state||{}, lg=String(m?.__sbbLeague||m?.league||'').toUpperCase();
  const desc=stateText(m);
  if(lg==='EPL'||lg==='MLS'){
    const clock=Number(st.clock??m.clock);
    if(Number.isFinite(clock) && clock>=0) return `${Math.floor(clock)}′`;
    if(/half time/i.test(desc)) return 'HT';
    return desc||'LIVE';
  }
  if(['NBA','NFL','NHL'].includes(lg)){
    const period=formatPeriodLabel(lg,st.period??m.period);
    const clock=formatClockValue(st.clock??m.clock);
    if(period&&clock) return `${period} • ${clock}`;
    if(clock) return clock; if(period) return period;
  }
  return desc||'LIVE';
}
function scoreRibbonImportance(m){
  const lg=String(m?.__sbbLeague||m?.league||'').toUpperCase();
  const away=m?.awayTeam||m?.away||{}, home=m?.homeTeam||m?.home||{};
  const extras=[m?.competitionName,m?.league?.name,m?.round,m?.stage,m?.week,m?.seasonType,m?.name,m?.title,fullTeamName(away),fullTeamName(home)].filter(Boolean).join(' ');
  let score=deterministicStakesScore({title:extras,subtitle:stateText(m)})*5;
  score+=aiScoreRibbonScore(m)*3.2;
  if(matchHasFavoriteTeam(m)) score+=135;
  if(isLive(m)) score+=55; else if(isFinal(m)) score+=25;
  // Related media inherits the same queue/director ranking where available.
  const id=String(m.id??m.matchId??m.eventId??''); const date=String(m.__sbbDate||m.date||'').slice(0,10);
  const key=gameKey(teamAbbr(away,''),teamAbbr(home,''));
  const related=[...(id?(HIGHLIGHTS_BY_MATCH.get(`match:${lg}:${id}`)||[]):[]),...(HIGHLIGHTS_BY_MATCH.get(`game:${date}:${key}`)||[])];
  if(related.length) score+=Math.max(...related.map(x=>Math.min(170,programUnitScore([x]))));
  return score;
}
function wireScoreFilters(){
  const host=$('scoreFilters');
  if(host&&!host.dataset.wired){
    host.dataset.wired='1';
    host.addEventListener('click',e=>{
      const btn=e.target.closest('[data-score-filter]'); if(!btn) return;
      scoreRibbonInteractionUntil=Date.now()+10000;
      scoreRibbonLeagueFilter=String(btn.dataset.scoreFilter||'ALL').toUpperCase();
      host.querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===btn));
      renderScoresFromMatchesCombined(true); updateScoreDayPager();
      renderActiveSportKeyInformation();
      loadRoundupsForDate(scoreBrowseDate).then(()=>{renderScoresFromMatchesCombined(false);});
    });
  }
  wireScoreDayPager();
}
function highlightType(items,primary=null){
  if(FORCE_BLUE_TEST) return items.length ? 'clips' : 'none';
  const chosen=primary || (items||[])[0] || null;
  return chosen?scoreHighlightTypeForItem(chosen):'none';
}

function gameEligibleForHighlights(m){
  // Future scheduled games never show highlights. Today becomes eligible only once
  // Highlightly says it is live/final. Yesterday is eligible after completion.
  return isFinal(m) || isLive(m);
}


function scoreVerifiedMediaKinds(game){
  const kinds=new Set();
  for(const key of scoreGameLookupKeys(game)){
    for(const kind of (VERIFIED_MEDIA_BY_MATCH.get(key)||[])) kinds.add(kind);
  }
  return {
    commentary:kinds.has('commentary'),
    recap:kinds.has('recap'),
    reel:kinds.has('reel'),
    extended:kinds.has('extended')
  };
}

function reconcileScoreMediaIndicators(){
  // The score renderer itself now reads the stable verified index through the same
  // lookup keys used by click playback. Do not mutate rendered colors afterward;
  // that previously allowed a second keying system to disagree with the click path.
}

function renderLeagueScores(league,yesterdayMatches,todayMatches){
  const lg=String(league||'SPORTS').toUpperCase();
  const mark=(arr,day)=>arr.map(raw=>{
    const m={...raw,__sbbLeague:lg,__sbbDay:raw.__sbbDay||day,competitionId:lg,competitionName:LEAGUES[lg]?.competition||lg,sportId:LEAGUES[lg]?.sport||'sports'};
    return window.SBB_CORE?.event ? window.SBB_CORE.event(m,lg) : m;
  });
  const markedYesterday=mark(yesterdayMatches||[],'yesterday');
  const markedToday=mark(todayMatches||[],'today');
  LIVE_MATCHES_BY_LEAGUE.set(lg,{yesterday:markedYesterday,today:markedToday});
  storeScoreDateLeague(lg,localDateISO(-1),markedYesterday);
  storeScoreDateLeague(lg,localDateISO(0),markedToday);
  const all=[...LIVE_MATCHES_BY_LEAGUE.values()].flatMap(x=>[...x.yesterday,...x.today]);
  LAST_COMPLETED_MATCHES=all.filter(isFinal);
  renderScoresFromMatchesCombined();
}


function externalMediaItemsForGame(match){
  if(!match) return [];
  const out=[]; const seen=new Set();
  for(const key of scoreGameLookupKeys(match)){
    for(const item of (EXTERNAL_MEDIA_BY_MATCH.get(key)||[])){
      const id=String(item?.id||item?.youtubeId||item?.externalUrl||'');
      if(!id || seen.has(id) || !item?.externalUrl || !mediaMatchesScoreGame(item,match)) continue;
      seen.add(id); out.push(item);
    }
  }
  const preferred=preferGameOverviews(out);
  try{ window.SBB_MEDIA_MANIFEST?.ingest?.(match,preferred,{external:true}); }catch(_){ }
  return window.SBB_MEDIA_MANIFEST?.external?.(match)||preferred;
}
function openExternalGameHighlights(match,item){
  if(!item?.externalUrl) return false;
  try{ if(match) focusScoreRibbonForGame(match,{force:true}); }catch(_){ }
  window.open(item.externalUrl,'_blank','noopener');
  return true;
}

function catalogPlanForScoreGame(match){
  if(!match)return null;const lg=String(match.competitionId||match.__sbbLeague||match.league||'').toUpperCase();
  const ids=[match.scoreEventId,match.espnEventId,match.gameCenterEventId,match.matchId,match.gamePk,match.eventId,match.id].filter(x=>x!==undefined&&x!==null&&String(x)!=='').map(String);
  for(const id of ids){const plan=CATALOG_EVENT_PLANS.get(`${lg}:${id}`);if(plan)return plan;}
  return null;
}

function scoreCardPlayableItems(match){
  if(!match) return [];
  const lg=String(match.competitionId||match.__sbbLeague||match.league||'SPORTS').toUpperCase();
  const away=match.awayTeam||match.away||{}, home=match.homeTeam||match.home||{};
  const sc=scoreFromMatch(match);
  const matchId=String(match.id??match.matchId??match.eventId??'');
  const key=gameKey(teamAbbr(away,''),teamAbbr(home,''));
  const date=String(match.__sbbDate||match.date||'').slice(0,10);
  const pools=[];
  const catalogPlan=catalogPlanForScoreGame(match);
  if(catalogPlan){
    const exact=[...(catalogPlan.playable||[]),...(catalogPlan.media||[])].map(x=>({...x,__sbbCatalogExact:true,canonicalEventKey:x?.canonicalEventKey||catalogPlan.canonicalEventKey||''}));
    pools.push(exact);
  }
  if(matchId){
    pools.push(HIGHLIGHTS_BY_MATCH.get(`match:${lg}:${matchId}`)||[]);
    pools.push(HIGHLIGHTS_BY_MATCH.get(`match:${matchId}`)||[]);
  }
  if(date && key && key!=='-'){
    pools.push(HIGHLIGHTS_BY_MATCH.get(`scoregame:${date}::${key}::${sc.away}-${sc.home}`)||[]);
    pools.push(HIGHLIGHTS_BY_MATCH.get(`game:${date}:${key}`)||[]);
  }
  // Arbitrary-date media is stored separately from the live candidate snapshots so
  // browsing January cannot evict today's playback resolver state.
  if(date){
    const canonicalKeys=new Set([match.scoreEventId,match.espnEventId,match.gameCenterEventId,match.matchId,match.gamePk,match.eventId,match.id].filter(x=>x!==undefined&&x!==null&&String(x)!=='').map(x=>`${lg}:${String(x)}`));
    pools.push(...scoreMediaForDate(date).filter(x=>{
      const xl=String(x?.competitionId||x?.__sbbLeague||x?.league||'').toUpperCase();
      const direct=canonicalKeys.has(String(x?.canonicalEventKey||''));
      return (!xl||xl===lg) && (direct || (mediaMatchesScoreGame(x,match) && (sameGameProgramItem(x,match) || scoreRibbonStableGameKey(x)===scoreRibbonStableGameKey(match))));
    }));
  }
  if(typeof verifiedPlayableItemsForGame==='function'){
    try{ pools.push(verifiedPlayableItemsForGame(match,lg)||[]); }catch(e){}
  }
  const scopeCtx={away:away.displayName||away.name||away.abbreviation||'',home:home.displayName||home.name||home.abbreviation||''};
  let discovered=[...new Map(
    pools.flat().filter(x=>(!window.SBB_MEDIA_SCOPE||window.SBB_MEDIA_SCOPE.isGame(x,scopeCtx))&&(x?.__sbbCatalogExact===true||mediaMatchesScoreGame(x,match)))
      .map(x=>[String(x.id||x.youtubeId||x.mediaUrl||x.externalUrl),x])
  ).values()];
  try{ window.SBB_MEDIA_MANIFEST?.ingest?.(match,discovered); }catch(_){ }
  // v4.3.6: an empty (or partial) browser manifest may never erase exact media
  // returned by the authoritative SQLite catalog.  JavaScript [] is truthy, so
  // `manifest.playable(match) || discovered` silently discarded catalog results
  // whenever the manifest returned an empty array. Merge both pools and let the
  // exact discovered row win identity collisions so __sbbCatalogExact survives.
  let manifestPlayable=[];
  try{ manifestPlayable=window.SBB_MEDIA_MANIFEST?.playable?.(match)||[]; }catch(_){ manifestPlayable=[]; }
  let items=[...new Map(
    [...manifestPlayable,...discovered].filter(Boolean).map(x=>[String(x.id||x.youtubeId||x.mediaUrl||x.externalUrl||x.assetKey||''),x])
  ).values()].filter(x=>String(x?.id||x?.youtubeId||x?.mediaUrl||x?.externalUrl||x?.assetKey||'')).filter(runtimeMediaUsable);
  if(!isFinal(match)) items=items.filter(x=>!isFullRecapCandidate(x)&&!isExtendedRecap(x)&&!isGoldRecap(x));
  return preferGameOverviews(items);
}

function scoreCardPlaybackSelection(match,items){
  const rankedLegacy=preferGameOverviews((items||[]).filter(Boolean));
  const request=match&&!isFinal(match)
    ? window.SBB_SPORT_MEDIA_POLICY?.REQUEST?.MOMENTS
    : null;
  // Historical/final playback follows the Big Board editorial preference:
  // Gold commentary → Green quick recap → Purple extended → Blue reel.
  const resolved=request
    ? (window.SBB_MEDIA_RESOLVER?.resolve?.(match||{},request,{assets:rankedLegacy})||null)
    : (window.SBB_MEDIA_RESOLVER?.resolveBest?.(match||{},{assets:rankedLegacy})||null);
  const ranked=resolved?.ranked?.length?resolved.ranked:rankedLegacy;
  let primary=resolved?.primary||null;
  if(!primary && ranked.length){
    primary=match&&!isFinal(match)
      ? ranked.find(x=>!isFullRecapCandidate(x)&&!isExtendedRecap(x)&&!isGoldRecap(x))||null
      : ranked.find(isGoldRecap)||ranked.find(x=>isFullRecapCandidate(x)&&!isExtendedRecap(x)&&!isGoldRecap(x))||ranked.find(isExtendedRecap)||ranked[0];
  }
  if(!primary) return {ranked,primary:null,selectionItems:[],resolved};
  if(isFullRecapCandidate(primary)) primary=attachRecapAlternates(primary,ranked);
  let selectionItems=[primary];
  if(!primary.overview && !isFullRecapCandidate(primary)){
    selectionItems=ranked.filter(x=>sameGameProgramItem(x,primary));
    selectionItems=[...new Map(selectionItems.map(x=>[String(x.id||x.youtubeId||x.mediaUrl),x])).values()];
    selectionItems.sort((a,b)=>{
      const aa=a.chronology||[9,999,0,0,0], bb=b.chronology||[9,999,0,0,0];
      for(let i=0;i<Math.max(aa.length,bb.length);i++){ const d=(aa[i]||0)-(bb[i]||0); if(d) return d; }
      return publishedTimeMs(a)-publishedTimeMs(b);
    });
    if(selectionItems.length) primary=selectionItems[0];
  }
  return {ranked,primary,selectionItems,resolved};
}
function scoreCardPrimaryItem(match,items){ return scoreCardPlaybackSelection(match,items).primary; }
function scoreCardAvailability(match){
  const items=scoreCardPlayableItems(match);
  const externalItems=externalMediaItemsForGame(match);
  const selection=scoreCardPlaybackSelection(match,items);
  const resolvedExternal=window.SBB_MEDIA_RESOLVER?.resolveBest?.(match,{assets:items,externalAssets:externalItems})||null;
  const externalPrimary=resolvedExternal?.externalPrimary||externalItems.find(isExtendedRecap)||externalItems.find(isFullRecapCandidate)||externalItems[0]||null;
  const manifestAvailability=window.SBB_MEDIA_MANIFEST?.availability?.(match)||null;
  // Score-card media colors/actions describe media that can actually play inside
  // Sports Big Board. External-only packages remain archived for diagnostics and
  // future provider fallback, but they no longer turn the whole score card into a
  // link that ejects the viewer to another website.
  const availability=manifestAvailability?.internal||mediaAvailability(items);
  const type=selection.primary?highlightType(items,selection.primary):'none';
  return {items,externalItems,externalPrimary,availability,primary:selection.primary,type,externalOnly:false,archivedExternal:!selection.primary&&!!externalPrimary};
}

function silverRoundupKindLabel(kind){
  const k=String(kind||'DAILY_RECAP').toUpperCase();
  if(k==='BEST_GOALS')return 'BEST GOALS';
  if(k==='BEST_SAVES')return 'BEST SAVES';
  if(k==='SCORING_ROUNDUP')return 'EVERY GOAL';
  if(k==='TOP_PLAYS')return 'TOP PLAYS';
  if(k==='WEEKLY_RECAP')return 'WEEKLY RECAP';
  return 'DAILY RECAP';
}

function buildSilverRoundupScoreCard(date){
  const items=roundupMediaForScoreDate(date);const available=items.length>0;
  const cell=document.createElement('button');cell.type='button';cell.className=`score-card roundup-card highlight-silver ${available?'has-highlights':''}`;
  cell.dataset.sbbRoundup='1';cell.title=available?'Play daily roundup':'Daily roundup is still being assembled';
  const top=document.createElement('div');top.className='score-card-top';
  const label=document.createElement('span');label.textContent=scoreRibbonLeagueFilter==='ALL'?'ROUNDUP':`${scoreRibbonLeagueFilter} ROUNDUP`;
  const day=document.createElement('small');day.textContent=date===localDateISO(0)?'TODAY':(date===localDateISO(-1)?'YESTERDAY':'SILVER');top.append(label,day);
  const line1=document.createElement('div');line1.className='roundup-card-line';line1.textContent=available?silverRoundupKindLabel(items[0]?.collectionKind):'DAILY RECAP';
  const line2=document.createElement('div');line2.className='roundup-card-line roundup-card-sub';line2.textContent=available?`${items.length} ${items.length===1?'VIDEO':'VIDEOS'}`:'BUILDING';
  const footer=document.createElement('div');footer.className='score-card-footer';const state=document.createElement('span');state.textContent=available?'WATCH':'PENDING';footer.append(state);
  const tag=document.createElement('span');tag.className='highlight-type-label';tag.textContent='SILVER';tag.dataset.short='SILVER';footer.append(tag);
  if(available){const dot=document.createElement('i');dot.className='highlight-dot';dot.textContent='▶';footer.append(dot);cell.onclick=()=>playDailyRoundup(date,{userInitiated:true});}
  else cell.disabled=true;
  cell.append(top,line1,line2,footer);
  if(available){const rail=document.createElement('div');rail.className='media-availability-rail';const seg=document.createElement('i');seg.className='media-availability-segment media-silver';rail.append(seg);cell.append(rail);}
  return cell;
}

function renderScoresFromMatchesCombined(animate=false){
  const host=$('scoreCells'); if(!host) return;
  wireScoreFilters();
  const rankRows=rows=>rows.filter(m=>scoreRibbonLeagueFilter==='ALL'||String(m.__sbbLeague||m.league||'').toUpperCase()===scoreRibbonLeagueFilter)
    .sort((x,y)=>scoreRibbonImportance(y)-scoreRibbonImportance(x) || new Date(x.date||0)-new Date(y.date||0));
  const sorted=rankRows(scoreMatchesForDate(scoreBrowseDate));
  if(!sorted.length){
    host.dataset.scoreDay=scoreBrowseDate;
    const loading=!!SCORE_DATE_STORE?.isLoading?.(scoreBrowseDate);
    const historyError=HISTORICAL_SCORE_LOAD_ERRORS.get(scoreBrowseDate)||'';
    host.innerHTML='';host.appendChild(buildSilverRoundupScoreCard(scoreBrowseDate));
    const empty=document.createElement('div');empty.className='score-empty score-empty-day';
    const emptyText=loading?'Loading games…':(historyError?'Historical catalog unavailable — tap the date to retry':'No games listed');
    empty.innerHTML=`<strong>${escapeHtml(formatScoreDateLabel(scoreBrowseDate))}</strong><span>${escapeHtml(emptyText)}</span>`;host.appendChild(empty);
    updateScoreDayPager();
    return;
  }
  if(animate){
    host.classList.remove('score-day-slide');
    void host.offsetWidth;
    host.classList.add('score-day-slide');
  }
  host.dataset.scoreDay=scoreBrowseDate;
  updateScoreDayPager();
  host.innerHTML='';
  scoreMediaPrimeGeneration++;
  const renderPrimeGeneration=scoreMediaPrimeGeneration;
  scoreMediaPrimeState.candidates=[];
  host.appendChild(buildSilverRoundupScoreCard(scoreBrowseDate));
  if(!host.dataset.warmSchedulerWired){
    host.dataset.warmSchedulerWired='1';
    host.addEventListener('scroll',()=>scheduleScoreMediaWarmReconcile(70),{passive:true});
    addEventListener('resize',()=>scheduleScoreMediaWarmReconcile(120),{passive:true});
  }
  const matchupCounts=new Map();
  for(const m of sorted){
    const lg=String(m.competitionId||m.__sbbLeague||m.league||'SPORTS').toUpperCase();
    const a=m.awayTeam||m.away||{}, h=m.homeTeam||m.home||{};
    const d=String(m.__sbbDate||m.date||'').slice(0,10); const k=`${lg}:${d}::${gameKey(teamAbbr(a,''),teamAbbr(h,''))}`;
    matchupCounts.set(k,(matchupCounts.get(k)||0)+1);
  }
  for(const m of sorted){
    const lg=String(m.competitionId||m.__sbbLeague||m.league||'SPORTS').toUpperCase();
    const away=m.awayTeam||m.away||{}, home=m.homeTeam||m.home||{}; const sc=scoreFromMatch(m);
    const matchId=String(m.id??m.matchId??m.eventId??''); const key=gameKey(teamAbbr(away,''),teamAbbr(home,''));
    const date=String(m.__sbbDate||m.date||'').slice(0,10);
    const resolved=scoreCardAvailability(m);
    const deduped=resolved.items;
    const availability=resolved.availability;
    const hType=resolved.type, hasHighlights=hType!=='none';
    const externalOnly=!!resolved.externalOnly;
    const cell=document.createElement('button'); cell.type='button'; cell.__sbbMatch=m; cell.dataset.sbbGameKey=scoreRibbonStableGameKey(m); cell.className=`score-card league-${lg.toLowerCase()} ${hasHighlights?'has-highlights':''} ${hasHighlights?`highlight-${hType}`:''} ${externalOnly?'external-only':''}`;
    if(hasHighlights){
      const typeLabel=hType==='gold'?'commentary recap':(hType==='recap'?'quick full recap':(hType==='extended'?'extended recap':'chronological clip set')); cell.title=`Play ${lg} ${typeLabel}`;
      const availableLabels=['gold','green','extended','blue'].filter(k=>availability[k]).map(k=>({gold:'commentary',green:'quick recap',extended:'extended',blue:'highlight reel'}[k]));
      cell.setAttribute('aria-label',`${teamAbbr(away,'Away')} at ${teamAbbr(home,'Home')}: ${typeLabel} available${availableLabels.length?`; media: ${availableLabels.join(', ')}`:''}`);
      const primaryForPrime=scoreCardPrimaryItem(m,deduped);
      if(isNativeItem(primaryForPrime)){
        const primeKey=nativePrimeKey(primaryForPrime);
        scoreMediaPrimeState.candidates.push({key:primeKey,item:primaryForPrime,cell,match:m,final:isFinal(m)});
        cell.addEventListener('pointerenter',()=>primeScoreIntent(primaryForPrime),{passive:true,once:true});
        cell.addEventListener('pointerdown',()=>primeScoreIntent(primaryForPrime),{passive:true});
        cell.addEventListener('focus',()=>primeScoreIntent(primaryForPrime),{once:true});
      }
      cell.onclick=()=>playGameHighlights(`${lg}:${matchId}`,m,scoreCardPlayableItems(m)); // explicit in-app tune; external-only media never hijacks the score card
    } else if(scoreBrowseDate<localDateISO(0) && isFinal(m)){
      // Historical dates auto-resolve every missing final. The card remains useful
      // during that search: tapping it opens Game Center and promotes this game's
      // existing background job to touch priority rather than creating a duplicate.
      const dateDiscovery=historicalDiscoveryState(scoreBrowseDate);
      const searching=historicalMediaSearchJobs.has(historicalMediaSearchKey(m)) ||
        !!(dateDiscovery?.running || ['QUEUED','SEARCHING'].includes(String(dateDiscovery?.status||'').toUpperCase()));
      cell.classList.add('historical-find-media');
      if(searching) cell.classList.add('historical-searching-media');
      cell.title=searching?`Finding ${lg} recap…`:`Open ${lg} Game Center and find recap`;
      cell.setAttribute('aria-label',`${teamAbbr(away,'Away')} at ${teamAbbr(home,'Home')}: ${searching?'recap search in progress; open Game Center':'open Game Center and find a recap'}`);
      cell.onclick=()=>selectHistoricalGameWithoutMedia(m);
    } else cell.disabled=true;
    const dayLabel=scoreBrowseDate===localDateISO(0)?'TODAY':(scoreBrowseDate===localDateISO(-1)?'YESTERDAY':(()=>{try{const [yy,mm,dd]=scoreBrowseDate.split('-').map(Number);return new Date(yy,mm-1,dd,12).toLocaleDateString([],{weekday:'short'}).toUpperCase();}catch(_){return 'HISTORY';}})()); let stateLabel;
    if(isFinal(m)) stateLabel='FINAL'; else if(isLive(m)) stateLabel=liveClockText(m); else stateLabel=formatGameTime(m.date);
    const top=document.createElement('div'); top.className='score-card-top'; const league=document.createElement('span'); league.textContent=lg; if(matchHasFavoriteTeam(m)){ const fav=document.createElement('em'); fav.className='score-favorite'; fav.textContent='★'; league.appendChild(fav); cell.classList.add('favorite-game'); } const day=document.createElement('small'); day.textContent=dayLabel; top.append(league,day);
    cell.append(top,buildTeamRow(away,sc.away,isFinal(m)||isLive(m)),buildTeamRow(home,sc.home,isFinal(m)||isLive(m)));
    const footer=document.createElement('div'); footer.className=`score-card-footer ${isLive(m)?'live':''}`; const st=document.createElement('span'); st.textContent=stateLabel; footer.append(st);
    if(hasHighlights){ const typeTag=document.createElement('span'); typeTag.className='highlight-type-label'; typeTag.textContent=hType==='gold'?'COMMENTARY':(hType==='recap'?'FULL RECAP':(hType==='extended'?'EXTENDED':'HIGHLIGHT REEL')); typeTag.dataset.short=hType==='gold'?'TALK':(hType==='recap'?'RECAP':(hType==='extended'?'EXT':'REEL')); const dot=document.createElement('i'); dot.className='highlight-dot'; dot.textContent='▶'; footer.append(typeTag,dot); }
    else if(cell.classList.contains('historical-find-media')){ const typeTag=document.createElement('span'); typeTag.className='highlight-type-label find-recap-label'; const searching=cell.classList.contains('historical-searching-media'); typeTag.textContent=searching?'SEARCHING…':'FIND RECAP'; typeTag.dataset.short=searching?'SEARCH':'FIND'; const dot=document.createElement('i'); dot.className='highlight-dot find-recap-dot'; dot.textContent=searching?'…':'⌕'; footer.append(typeTag,dot); }
    cell.append(footer);
    const availabilityRail=mediaAvailabilityRail(availability);
    if(availabilityRail) cell.appendChild(availabilityRail);
    host.appendChild(cell);
  }
  // Compute one stable HOT/WARM set only after every card has a real geometry.
  // This replaces v2.5.30's observer-driven FIFO behavior that could evict a
  // prepared visible game when a farther card merely entered the 600 px margin.
  if(renderPrimeGeneration===scoreMediaPrimeGeneration) scheduleScoreMediaWarmReconcile(90);
  applyScoreRibbonFocusVisuals({scroll:false});
}

function playGameHighlights(matchId, match, providedItems=null){
  if(!sbbPlaybackAllowed({notify:true})){
    if(match)syncSelectedEvent(gameCenterSelectionFromScoreMatch(match),{reason:'score-card selection while search priority active',source:'score-ribbon'});
    return;
  }
  let items=Array.isArray(providedItems)?providedItems.filter(Boolean):[];
  if(match){
    const current=scoreCardPlayableItems(match);
    items=[...new Map(
      [...items,...current]
        .filter(x=>x?.verifiedPlayable&&(x.youtubeId||x.mediaUrl))
        .map(x=>[String(x.id||x.youtubeId||x.mediaUrl),x])
    ).values()];
  }
  if(!items.length){
    console.warn('[SBB score-click] no playable media',matchId,match);
    try{ fetch('/api/client-log?event=SCORE_CLICK_NO_MEDIA&detail='+encodeURIComponent(String(matchId||'')),{cache:'no-store'}).catch(()=>{}); }catch(e){}
    setFeedNote(isFinal(match)?'Recap is still being prepared for playback':'No playable live highlight is available yet');
    return;
  }

  const resolvedSelection=scoreCardPlaybackSelection(match,items);
  let primary=resolvedSelection.primary;
  const selectionItems=resolvedSelection.selectionItems;
  if(match){
    // The score event owns sporting-event identity. A media item's gamePk can be
    // mis-associated even when the video itself remains playable, so it must never
    // become Game Center authority. Launch and score clicks share this exact adapter.
    syncSelectedEvent(gameCenterSelectionFromScoreMatch(match),{reason:'score-card selection',source:'score-ribbon'});
  }
  if(!primary) return;
  rememberRecentScoreMedia(primary);
  const selectedMediaWasPrepared=isScoreMediaPrimed(primary);
  // v4.3.6: score selection also tells localhost to stage the exact native
  // asset at touch-intent priority. This does not create a second playback owner;
  // it only makes the proxy cache fill ahead of the active decoder when possible.
  if(isNativeItem(primary)){
    const url=rawNativeMediaUrl(primary);
    if(url){
      fetch('/api/media/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items:[{url,eventId:primary.eventId||primary.matchId||primary.gamePk||'',gamePk:primary.gamePk||'',date:primary.gameDate||primary.date||'',priority:4,priorityClass:(window.SBB_MEDIA_WORK?.PRIORITY.TOUCH_INTENT||'TOUCH_INTENT')}]}),cache:'no-store'}).catch(()=>{});
    }
  }

  const resumeItem=clip(currentIndex);
  const resumeIndex=currentIndex;
  const playbackDate=scoreEventDate(match)||scoreBrowseDate||localDateISO(0);
  activatePlaybackDateContext(playbackDate,{source:'score-ribbon'});
  PROGRAM=dateProgramWithSelectionFirst(playbackDate,selectionItems);
  currentIndex=0;
  standbyIndex=0;
  manualPauseRequested=false;
  visibilityResumeWanted=false;
  beginScorePlaybackSession({matchId,resumeItem,resumeIndex,selectionCount:selectionItems.length,preparedAtClick:selectedMediaWasPrepared,provider:providerForItem(primary),fallbackItems:resolvedSelection.ranked,playbackDate,match});

  const kind=(match && !isFinal(match))
    ? 'LIVE HIGHLIGHT'
    : (isGoldRecap(primary)?'COMMENTARY RECAP':(isExtendedRecap(primary)?'EXTENDED RECAP':(primary.overview?'FULL-GAME RECAP':'GAME HIGHLIGHT')));
  setFeedNote(`${gameLabel(match)} • ${kind.toLowerCase()}`);
  showBumper(0,500,kind);
  try{
    console.info('[SBB score-click] authoritative tune',{matchId,primaryId:primary.id,youtubeId:primary.youtubeId,mediaUrl:primary.mediaUrl,selectionCount:selectionItems.length,final:isFinal(match),kind,preparedAtClick:selectedMediaWasPrepared});
    fetch('/api/client-log?event=SCORE_CLICK_TUNE&detail='+encodeURIComponent(`${matchId}|${primary.id||primary.youtubeId||''}|${kind}|provider=${providerForItem(primary)}|preparedAtClick=${selectedMediaWasPrepared?1:0}`),{cache:'no-store'}).catch(()=>{});
  }catch(e){}
  PlaybackController.tuneProgramIndex(0,{userInitiated:true,reason:'score-card selection'});
}

function gameLabel(m){
  const away=m.awayTeam||m.away||{}, home=m.homeTeam||m.home||{};
  return `${away.abbreviation||away.name||'Away'} at ${home.abbreviation||home.name||'Home'}`;
}

function formatGameTime(iso){
  if(!iso) return 'SCHEDULED';
  try{return new Date(iso).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});}catch(e){return 'SCHEDULED';}
}
function updateQuotaUi(){
  const el=$('quotaSummary');
  if(!el) return;
  if(Number.isFinite(apiQuota.limit) && apiQuota.limit>0 && Number.isFinite(apiQuota.remaining)){
    const used=Math.max(0,apiQuota.limit-apiQuota.remaining);
    el.textContent=`API ${apiQuota.remaining.toLocaleString()} / ${apiQuota.limit.toLocaleString()} left`;
    el.title=`${used.toLocaleString()} Highlightly requests used in the current quota window`;
    const pct=apiQuota.remaining/apiQuota.limit;
    el.classList.toggle('quota-low',pct<0.15);
  } else {
    const historical=!!(scoreBrowseDate && scoreBrowseDate<localDateISO(0));
    el.textContent=highlightlyRateLimited?(historical?'LIVE API RATE LIMITED':'API RATE LIMITED'):'API —';
    el.title=highlightlyRateLimited&&historical?'Highlightly live-data quota is limited; historical media discovery continues independently.':'';
    el.classList.toggle('quota-low',highlightlyRateLimited);
  }
}

function refreshQuotaFromStatus(){
  apiJson('/api/status').then(status=>{
    if(status?.rateLimit){
      if(status.rateLimit.remaining!=='' && status.rateLimit.remaining!=null) apiQuota.remaining=Number(status.rateLimit.remaining);
      if(status.rateLimit.limit!=='' && status.rateLimit.limit!=null) apiQuota.limit=Number(status.rateLimit.limit);
      updateQuotaUi();
    }
  }).catch(()=>{});
}

function isHighlightEligible(m){
  // Highlight coverage should never be judged against games that have not started.
  // Live/in-progress and completed games are eligible; scheduled future games stay
  // on the ribbon but are excluded from the highlight denominator.
  return isFinal(m) || isLive(m);
}

function playableGameCount(candidates){
  const keys=new Set();
  for(const x of (candidates||[])){
    if(!x?.verifiedPlayable || !(x.youtubeId||x.mediaUrl)) continue;
    const key=String(x.matchId || x.dateGameKey || x.gameKey || x.gamePk || x.id || '');
    if(key) keys.add(key);
  }
  return keys.size;
}

function setApiCounts(matches, highlights, candidates){
  if(typeof scoreBrowseDate!=='undefined' && scoreBrowseDate<localDateISO(0)){
    if(typeof renderHistoricalDateDiagnostics==='function')renderHistoricalDateDiagnostics(scoreBrowseDate);
    return;
  }
  const el=$('mobileLiveSummary');
  if(!el) return;
  const all=Array.isArray(matches)?matches:[];
  const eligible=all.filter(isHighlightEligible).length;
  const playableGames=playableGameCount(candidates);
  const videoCount=(candidates||[]).filter(x=>x?.verifiedPlayable && (x.youtubeId||x.mediaUrl)).length;
  el.textContent=`${eligible} highlight-eligible • ${playableGames} playable games • ${videoCount} videos`;
  el.title=`${all.length} games on the yesterday/today ribbon • future scheduled games are excluded from highlight coverage`;
}
function setDataStatus(text, good){
  // Today's live-refresh workers continue warming in the background while the
  // viewer browses history. They must not overwrite the historical diagnostics
  // with misleading labels such as "DATA: MLB FALLBACK" on Christmas Day.
  if(scoreBrowseDate && scoreBrowseDate<localDateISO(0) && !String(text||'').startsWith('HISTORY')){
    const hist=`HISTORY: ${formatScoreDateLabel(scoreBrowseDate)}`;
    const el=$('dataStatus'); if(el){el.textContent=hist;el.classList.remove('bad');el.classList.add('good');}
    const rail=$('apiRailStatus'); if(rail) rail.textContent=hist;
    const mobile=$('mobileDataStatus'); if(mobile){mobile.textContent=hist;mobile.style.color='#7bf1a9';}
    return;
  }
  const el=$('dataStatus'); if(el){el.textContent=`DATA: ${text}`;el.classList.toggle('good',good===true);el.classList.toggle('bad',good===false)}
  const rail=$('apiRailStatus'); if(rail) rail.textContent=text;
  const mobile=$('mobileDataStatus'); if(mobile){mobile.textContent=`DATA: ${text}`;mobile.style.color=good===false?'#ff8d84':good===true?'#7bf1a9':'#ffd56b';}
}
function setFeedNote(text){const el=$('feedNote');if(el)el.textContent=text;}

const debugToggle=$('debugToggle'), playbackDebug=$('playbackDebug');
if(debugToggle && playbackDebug){
  debugToggle.addEventListener('click',()=>{
    const collapsed=playbackDebug.classList.toggle('is-collapsed');
    debugToggle.textContent=collapsed?'PLAYER DEBUG ▸':'PLAYER DEBUG ▾';
  });
}


setTimeout(()=>{ try{ loadDirectorCache(); }catch(_){} },0);

// v4.2 milestone-release truth bridge. Read-only: diagnostics may inspect playback,
// but never mutate player state or programming decisions.
window.SBB_MILESTONE_CONTEXT=()=>{
  const current=typeof clip==='function'?clip(currentIndex):null;
  const nativeState={};
  for(const slot of ['A','B']){
    try{
      const v=nativeEl(slot);
      nativeState[slot]=v?{paused:!!v.paused,muted:!!v.muted,volume:Number(v.volume||0),readyState:v.readyState,networkState:v.networkState,currentTime:Math.round((v.currentTime||0)*10)/10,src:v.currentSrc||v.getAttribute('src')||''}:null;
    }catch(_){nativeState[slot]=null;}
  }
  const youtubeState={};
  for(const slot of ['A','B']){
    try{youtubeState[slot]={ready:!!playerReady?.[slot],state:players?.[slot]?.getPlayerState?.()??null,muted:players?.[slot]?.isMuted?.()??null};}catch(_){youtubeState[slot]=null;}
  }
  return {
    started:!!sportsBigBoardStarted,resourceMode:typeof sbbResourceMode==='function'?sbbResourceMode():'balanced',
    activeSlot,currentIndex,standbyIndex,transitionInFlight:!!transitionInFlight,manualPauseRequested:!!manualPauseRequested,
    currentItem:current?playbackSessionDescriptor(current):null,slotMedia:{...slotMedia},playerReady:{...playerReady},videoReady:{...videoReady},
    slotAssignments:Object.fromEntries(Object.entries(slotAssignment||{}).map(([k,v])=>[k,v?{key:v.key,epoch:v.epoch}:null])),
    native:nativeState,youtube:youtubeState,scoreBrowseDate:typeof scoreBrowseDate==='string'?scoreBrowseDate:'',scorePlaybackDate:typeof scorePlaybackDate==='string'?scorePlaybackDate:'',
    selectedEvent:window.SBB_SELECTED_EVENT?.get?.()||null,activeOwnsGameCenter:playbackOwnsGameCenter(current),selectedEventMatchesActive:selectedEventMatchesActivePlayback()
  };
};

// v4.2 milestone test harness bridge. This is intentionally a narrow, explicit
// command surface for Dev Mode. The release console uses these hooks to exercise
// real user paths without reaching into random globals or creating a second
// playback authority.
function devStressEnsurePlaying(){
  if(!sportsBigBoardStarted) return false;
  manualPauseRequested=false;
  enforceSingleAudibleSlot();
  playSlot(activeSlot);
  return true;
}
function devStressEnsurePaused(){
  if(!sportsBigBoardStarted) return false;
  manualPauseRequested=true;
  setPlaybackUi('paused');
  pauseSlot(activeSlot);
  return true;
}

window.SBB_DEV_TEST_HOOKS=Object.freeze({
  version:'1.1',
  snapshot:()=>window.SBB_MILESTONE_CONTEXT?.()||{},
  playback:()=>window.SBB_PLAYBACK_SESSION?.snapshot?.()||{},
  currentTime:()=>{try{if(slotMedia[activeSlot]==='youtube')return Number(players[activeSlot]?.getCurrentTime?.()||0);if(slotMedia[activeSlot]==='native')return Number(nativeEl(activeSlot)?.currentTime||0);return 0;}catch(_){return 0;}},
  selectedEvent:()=>window.SBB_SELECTED_EVENT?.get?.()||null,
  selectedEventMatchesActive:()=>selectedEventMatchesActivePlayback(),
  activeOwnsGameCenter:()=>playbackOwnsGameCenter(clip(currentIndex)),
  demoSeedCount:()=>0,
  roundupAutoplayEnabled:()=>false,
  refreshProgram:()=>{mergeLiveProgram([],false);return {mediaKey:playbackItemKey(clip(currentIndex)),manualPauseRequested};},
  started:()=>!!sportsBigBoardStarted,
  start:()=>{ if(!sportsBigBoardStarted) startSportsBigBoardExperience(); return !!sportsBigBoardStarted; },
  playPause:()=>{ const b=$('playBtn'); if(!b)throw new Error('playBtn unavailable'); b.click(); return true; },
  ensurePlaying:()=>devStressEnsurePlaying(),
  ensurePaused:()=>devStressEnsurePaused(),
  nextClip:()=>{ const b=$('nextBtn'); if(!b)throw new Error('nextBtn unavailable'); b.click(); return true; },
  stressTuneNext:()=>{
    const target=nextVisibleQueueIndex();if(target<0)return Promise.resolve(false);
    return PlaybackController.tuneProgramIndex(target,{userInitiated:false,reason:'milestone stress next'}).then(()=>true);
  },
  stressTuneNextGame:()=>{
    const here=clip(currentIndex);const hereGame=programGameIdentity(here);
    for(let step=1;step<=PROGRAM.length;step++){const idx=(currentIndex+step)%PROGRAM.length,item=PROGRAM[idx];if(playbackOwnsGameCenter(item)&&programGameIdentity(item)!==hereGame)return PlaybackController.tuneProgramIndex(idx,{userInitiated:false,reason:'milestone next-game ownership'}).then(()=>true);}
    return Promise.resolve(false);
  },
  chaosDisruptStandby:()=>{
    const slot=otherSlot(activeSlot),target=nextVisibleQueueIndex();
    try{pauseSlot(slot);}catch(_){}videoReady[slot]=false;warming[slot]=false;
    if(target>=0)prepareStandby(slot,target);
    return {slot,target,activeMediaKey:playbackItemKey(clip(currentIndex))};
  },
  previousClip:()=>{ const b=$('prevBtn'); if(!b)throw new Error('prevBtn unavailable'); b.click(); return true; },
  soundtrackToggle:()=>{ const b=$('soundtrackToggle'); if(!b)throw new Error('soundtrackToggle unavailable'); b.click(); return window.SBB_SOUNDTRACK?.snapshot?.()||{}; },
  soundtrackNext:()=>{ const b=$('soundtrackNextBtn'); if(!b)throw new Error('soundtrackNextBtn unavailable'); b.click(); return window.SBB_SOUNDTRACK?.snapshot?.()||{}; },
  soundtrack:()=>window.SBB_SOUNDTRACK?.snapshot?.()||{},
  soundtrackDevSnapshot:()=>window.SBB_SOUNDTRACK?.__devSnapshot?.()||null,
  soundtrackDevRestore:saved=>window.SBB_SOUNDTRACK?.__devRestore?.(saved)===true,
  openGameCenter:()=>{ window.SBB_INFO_DRAWER?.resetAutomaticSuppression?.(); window.SBB_INFO_DRAWER?.open?.('game-center',{automatic:false}); return true; },
  openDrawerTab:tab=>{ window.SBB_INFO_DRAWER?.resetAutomaticSuppression?.(); window.SBB_INFO_DRAWER?.open?.(String(tab||'game-center'),{automatic:false}); return true; },
  closeDrawer:()=>{ window.SBB_INFO_DRAWER?.close?.({manual:false}); return true; },
  drawer:()=>({open:!!$('infoDrawer')?.classList.contains('is-open'),tab:window.SBB_INFO_DRAWER?.activeTab||''}),
  setResourceMode:async mode=>{
    const wanted=['search','balanced','playback'].includes(String(mode||'').toLowerCase())?String(mode).toLowerCase():'balanced';
    const r=await fetch('/api/history/work-mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:wanted}),cache:'no-store'});
    let data={};try{data=await r.json();}catch(_){ }
    if(!r.ok||data?.ok!==true)throw new Error(data?.message||data?.error||`resource mode HTTP ${r.status}`);
    const actual=String(data?.workMode?.mode||wanted).toLowerCase();
    applySbbResourceMode(actual,{notify:false});
    return sbbResourceMode();
  },
  resourceMode:()=>sbbResourceMode(),
  today:()=>localDateISO(0),
  yesterday:()=>addCalendarDays(localDateISO(0),-1),
  scoreDate:()=>scoreBrowseDate,
  setScoreDate:date=>setScoreBrowseDate(String(date||localDateISO(0)),{animate:false,hold:1500,load:true}),
  returnToday:()=>returnToToday(),
  currentMediaKey:()=>playbackItemKey(clip(currentIndex)||{}),
  currentSourceUrl:()=>playbackExternalSourceUrl(clip(currentIndex)||{}),
  currentProgramIndex:()=>Number(currentIndex),
  restoreMediaKey:key=>{
    const wanted=String(key||'');if(!wanted)return Promise.resolve(false);
    const idx=(PROGRAM||[]).findIndex(item=>playbackItemKey(item)===wanted);
    if(idx<0)return Promise.resolve(false);
    return PlaybackController.tuneProgramIndex(idx,{userInitiated:false,reason:'milestone stress restore'}).then(()=>true).catch(()=>false);
  },
  programSize:()=>Array.isArray(PROGRAM)?PROGRAM.length:0,
  invariant:()=>String(window.SBB_PLAYBACK_SESSION?.snapshot?.().invariant||'OK')
});


/* Sports Big Board v4.4.5 — Dev Playback Terminal + random-archive mixed-media endurance certification.
   The terminal observes canonical playback and drives stress actions only through
   SBB_DEV_TEST_HOOKS / score-ribbon controls, preserving PlaybackController authority. */
(() => {
  'use strict';
  if(window.SBB_PLAYBACK_TERMINAL)return;

  const rows=[],bySession=new Map();let lastSessionId='',tickTimer=null,enduranceTimer=null;
  const now=()=>performance.now();
  const epoch=()=>Date.now();
  const fmtMs=ms=>`${(Math.max(0,Number(ms)||0)/1000).toFixed(1)}s`;
  const fmtClock=ms=>{const s=Math.max(0,Math.floor(Number(ms||0)/1000));return `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;};
  const clean=(v,n=160)=>String(v??'').replace(/\s+/g,' ').trim().slice(0,n);
  const esc=v=>clean(v,500).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  function devEnabled(){return window.SBB_DEV_MODE?.isEnabled?.()===true||document.body?.classList.contains('dev-mode')||document.body?.dataset?.sbbDev==='1';}
  function hooks(){return window.SBB_DEV_TEST_HOOKS||null;}

  function durationFor(row,kind,t=now()){
    let total=Number(row[kind+'Ms']||0);if(row.state===kind&&row.stateStartedPerf)total+=Math.max(0,t-row.stateStartedPerf);return total;
  }
  function finalizeState(row,t=now()){
    if(!row?.stateStartedPerf)return;
    const delta=Math.max(0,t-row.stateStartedPerf);
    if(row.state==='playing')row.playingMs+=delta;
    if(row.state==='buffering')row.bufferingMs+=delta;
    row.stateStartedPerf=0;
  }

  const PHASES=Object.freeze([
    Object.freeze({id:'warmup',label:'WARMUP',durationMs:10*60_000,minTransitionMs:35_000,maxTransitionMs:50_000,disruptStandby:false}),
    Object.freeze({id:'soak',label:'MIXED SOAK',durationMs:30*60_000,minTransitionMs:18_000,maxTransitionMs:32_000,disruptStandby:false}),
    Object.freeze({id:'hammer',label:'MIXED HAMMER',durationMs:20*60_000,minTransitionMs:8_000,maxTransitionMs:16_000,disruptStandby:true})
  ]);
  const ENDURANCE_TOTAL_MS=PHASES.reduce((n,p)=>n+p.durationMs,0);
  const FIRST_FRAME_WATCHDOG_MS=28_000;
  const MIN_SUCCESSFUL_STARTS=150;
  const MIN_TRANSITIONS=149;
  const MIN_SPORTS=3;
  const MIN_QUALITIES=3;
  const MIN_DATES=10;
  const MIN_DATE_CHANGES=12;
  const MIN_TRANSPORTS=2;
  const MIN_MONTHS=6;
  const MIN_DATE_SPAN_DAYS=180;
  const MIN_LONG_DATE_JUMPS=8;
  const QUALITY_ROTATION=Object.freeze(['GREEN','PURPLE','BLUE']);
  const SPORT_IDS=Object.freeze(['MLB','NFL','NBA','NHL','EPL','MLS']);
  const ARCHIVE_LOOKBACK_DAYS=365;
  const ARCHIVE_MIN_JUMP_DAYS=45;
  const LONG_DATE_JUMP_DAYS=45;
  const ARCHIVE_DATE_LOAD_TIMEOUT_MS=4500;
  const ARCHIVE_DATE_MAX_ATTEMPTS=6;
  let endurance={};
  let seenMediaKeys=new Set(),seenEventKeys=new Set(),seenCardKeys=new Set(),seenStressDates=new Set(),attemptedStressDates=new Set(),mediaFailures=new Map(),successfulMediaKeys=new Set(),quarantinedMediaKeys=new Set();

  function counterKeys(obj){return Object.entries(obj||{}).filter(([,n])=>Number(n)>0).map(([k])=>k);}
  function sportKeys(){return SPORT_IDS.filter(k=>Number(endurance.sports?.[k]||0)>0);}
  function bump(obj,key){key=clean(key||'UNKNOWN',40)||'UNKNOWN';obj[key]=(obj[key]||0)+1;return obj[key];}
  function resetEnduranceMemory(){
    seenMediaKeys=new Set();seenEventKeys=new Set();seenCardKeys=new Set();seenStressDates=new Set();attemptedStressDates=new Set();mediaFailures=new Map();successfulMediaKeys=new Set();quarantinedMediaKeys=new Set();
  }
  function freshEndurance(status='IDLE'){
    return {
      runId:'',status,reason:'',startedAt:0,endedAt:0,phase:'IDLE',phaseLabel:'IDLE',phaseStartedAt:0,nextTransitionAt:0,
      successfulStarts:0,transitions:0,crossGameTransitions:0,standbyDisruptions:0,noFrameStreak:0,maxNoFrameStreak:0,
      recoveryAttempts:0,retryAttempts:0,retrySuccesses:0,fallbacks:0,recoveredAfterReset:0,recoveryArmed:false,unrecoveredBlanks:0,
      engineIncidentsBase:0,engineResetsBase:0,engineIncidents:0,engineResets:0,lastAction:'',lastActionAt:0,lastFirstFrameAt:0,
      lastRecap:null,duplicateRecaps:0,repeatViolations:0,duplicateSelections:0,duplicateCandidateRejects:0,preflightDuplicateSkips:0,assetBad:0,rapidTransitions:0,dateChanges:0,
      randomDateAttempts:0,longDateJumps:0,archiveSpanDays:0,archiveDates:[],
      sportChanges:0,qualityChanges:0,transportChanges:0,uniqueMedia:0,uniqueEvents:0,
      sports:{},qualities:{},dates:{},months:{},transports:{},providers:{},
      lastLeague:'',lastQuality:'',lastDate:'',lastTransport:'',lastMediaKey:'',lastEventKey:'',
      pendingQuality:'',pendingDate:'',pendingLeague:'',pendingCardKey:'',pendingStressSelection:false,recovery:null,dateCursor:0,
      actionBusy:false,noCandidateCount:0,savedResourceMode:'balanced',savedMediaKey:'',savedScoreDate:'',events:[]
    };
  }
  endurance=freshEndurance();

  function enduranceLog(type,message,extra={}){
    const entry={at:epoch(),type:clean(type,32),message:clean(message,240),...extra};
    endurance.events.push(entry);if(endurance.events.length>200)endurance.events=endurance.events.slice(-200);
    endurance.lastAction=entry.message;endurance.lastActionAt=entry.at;
    return entry;
  }
  function endurancePhaseAt(elapsed){
    let cursor=0;
    for(const p of PHASES){if(elapsed<cursor+p.durationMs)return {...p,offsetMs:cursor};cursor+=p.durationMs;}
    return null;
  }
  function nextTransitionDelay(phase){
    const lo=Number(phase?.minTransitionMs||15_000),hi=Math.max(lo,Number(phase?.maxTransitionMs||lo));
    if(endurance.transitions>0&&endurance.transitions%12===0){endurance.rapidTransitions++;return 4_000+Math.floor(Math.random()*3_001);}
    return lo+Math.floor(Math.random()*(hi-lo+1));
  }
  function enduranceSnapshot(){
    const h=hooks(),engine=h?.playbackEngine?.()||{};
    if(endurance.startedAt){
      endurance.engineIncidents=Math.max(0,Number(engine.incidents||0)-Number(endurance.engineIncidentsBase||0));
      endurance.engineResets=Math.max(0,Number(engine.resets||0)-Number(endurance.engineResetsBase||0));
    }
    endurance.uniqueMedia=seenMediaKeys.size;endurance.uniqueEvents=seenEventKeys.size;
    const elapsed=endurance.startedAt?Math.min(ENDURANCE_TOTAL_MS,Math.max(0,(endurance.endedAt||epoch())-endurance.startedAt)):0;
    return {...endurance,elapsedMs:elapsed,totalMs:ENDURANCE_TOTAL_MS,remainingMs:Math.max(0,ENDURANCE_TOTAL_MS-elapsed),progress:ENDURANCE_TOTAL_MS?elapsed/ENDURANCE_TOTAL_MS:0,events:[...endurance.events]};
  }
  function setEnduranceStatus(status,reason=''){
    endurance.status=status;endurance.reason=clean(reason,300);if(['PASS','FAIL','STOPPED'].includes(status))endurance.endedAt=epoch();render();
  }
  async function restoreAfterEndurance(){
    const h=hooks();if(!h)return;
    try{if(endurance.savedScoreDate&&h.setScoreDate)await h.setScoreDate(endurance.savedScoreDate);}catch(_){ }
    try{if(endurance.savedMediaKey)await h.restoreMediaKey?.(endurance.savedMediaKey);}catch(_){ }
    try{if(endurance.savedResourceMode)await h.setResourceMode?.(endurance.savedResourceMode);}catch(_){ }
  }
  function finishEndurance(status,reason){
    if(endurance.status!=='RUNNING')return;
    endurance.actionBusy=false;setEnduranceStatus(status,reason);enduranceLog(status.toLowerCase(),reason||status);
    restoreAfterEndurance();
  }
  function failEndurance(reason){finishEndurance('FAIL',reason);}
  function passEndurance(){
    const sports=sportKeys(),qualities=QUALITY_ROTATION.filter(q=>Number(endurance.qualities[q]||0)>0),dates=counterKeys(endurance.dates),transports=counterKeys(endurance.transports);
    if(endurance.successfulStarts<MIN_SUCCESSFUL_STARTS)return failEndurance(`INSUFFICIENT_FIRST_FRAMES ${endurance.successfulStarts}/${MIN_SUCCESSFUL_STARTS}`);
    if(endurance.transitions<MIN_TRANSITIONS)return failEndurance(`INSUFFICIENT_TRANSITIONS ${endurance.transitions}/${MIN_TRANSITIONS}`);
    if(seenMediaKeys.size!==endurance.successfulStarts||endurance.repeatViolations)return failEndurance(`REPEATED_MEDIA • ${seenMediaKeys.size} unique / ${endurance.successfulStarts} starts`);
    if(sports.length<MIN_SPORTS)return failEndurance(`INSUFFICIENT_SPORT_DIVERSITY ${sports.length}/${MIN_SPORTS}`);
    if(qualities.length<MIN_QUALITIES)return failEndurance(`INSUFFICIENT_COLOR_DIVERSITY ${qualities.join('/')||'NONE'} • need GREEN/PURPLE/BLUE`);
    if(dates.length<MIN_DATES)return failEndurance(`INSUFFICIENT_DATE_DIVERSITY ${dates.length}/${MIN_DATES}`);
    if(endurance.dateChanges<MIN_DATE_CHANGES)return failEndurance(`INSUFFICIENT_DATE_SWAPS ${endurance.dateChanges}/${MIN_DATE_CHANGES}`);
    const months=counterKeys(endurance.months);if(months.length<MIN_MONTHS)return failEndurance(`INSUFFICIENT_MONTH_DIVERSITY ${months.length}/${MIN_MONTHS}`);
    if(endurance.archiveSpanDays<MIN_DATE_SPAN_DAYS)return failEndurance(`INSUFFICIENT_ARCHIVE_SPAN ${endurance.archiveSpanDays}/${MIN_DATE_SPAN_DAYS} days`);
    if(endurance.longDateJumps<MIN_LONG_DATE_JUMPS)return failEndurance(`INSUFFICIENT_LONG_DATE_JUMPS ${endurance.longDateJumps}/${MIN_LONG_DATE_JUMPS}`);
    if(transports.length<MIN_TRANSPORTS)return failEndurance(`INSUFFICIENT_TRANSPORT_DIVERSITY ${transports.length}/${MIN_TRANSPORTS}`);
    if(endurance.maxNoFrameStreak>2)return failEndurance(`NOFRAME_MAX ${endurance.maxNoFrameStreak} > 2`);
    if(endurance.unrecoveredBlanks)return failEndurance(`UNRECOVERED_BLANKS ${endurance.unrecoveredBlanks}`);
    finishEndurance('PASS',`60-minute random-archive mixed-media endurance passed • ${endurance.successfulStarts} unique starts • ${endurance.transitions} transitions • ${sports.length} sports • ${dates.length} dates • ${counterKeys(endurance.months).length} months • ${endurance.archiveSpanDays}d span • ${endurance.longDateJumps} long jumps`);
  }
  function stopEndurance(){
    if(endurance.status!=='RUNNING')return false;
    endurance.actionBusy=false;setEnduranceStatus('STOPPED','Operator stopped mixed-media endurance test');enduranceLog('stop','Operator stopped mixed-media endurance test');restoreAfterEndurance();return true;
  }

  function addCalendarDays(date,delta){
    const raw=clean(date,10);if(!/^\d{4}-\d{2}-\d{2}$/.test(raw))return raw;
    const d=new Date(`${raw}T12:00:00Z`);d.setUTCDate(d.getUTCDate()+Number(delta||0));return d.toISOString().slice(0,10);
  }
  function dateDistanceDays(a,b){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(clean(a,10))||!/^\d{4}-\d{2}-\d{2}$/.test(clean(b,10)))return 0;
    return Math.round(Math.abs(new Date(`${a}T12:00:00Z`)-new Date(`${b}T12:00:00Z`))/86_400_000);
  }
  function randomUnit(){
    try{if(globalThis.crypto?.getRandomValues){const a=new Uint32Array(1);globalThis.crypto.getRandomValues(a);return a[0]/4_294_967_296;}}catch(_){ }
    return Math.random();
  }
  function randomArchiveTarget(today,before=''){
    const base=clean(today,10);if(!/^\d{4}-\d{2}-\d{2}$/.test(base))return '';
    let fallback='';
    for(let i=0;i<160;i++){
      const offset=1+Math.floor(randomUnit()*ARCHIVE_LOOKBACK_DAYS),target=addCalendarDays(base,-offset);
      if(!target||attemptedStressDates.has(target)||seenStressDates.has(target))continue;
      if(!fallback)fallback=target;
      if(before&&dateDistanceDays(target,before)<ARCHIVE_MIN_JUMP_DAYS)continue;
      attemptedStressDates.add(target);return target;
    }
    if(fallback){attemptedStressDates.add(fallback);return fallback;}
    return '';
  }
  function updateArchiveSpan(date){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(clean(date,10)))return;
    const all=[...new Set([...endurance.archiveDates,date])].sort();endurance.archiveDates=all;
    if(all.length>1)endurance.archiveSpanDays=dateDistanceDays(all[0],all[all.length-1]);
  }
  function cardQuality(card){
    const c=card?.classList;
    if(c?.contains?.('highlight-recap'))return 'GREEN';
    if(c?.contains?.('highlight-extended'))return 'PURPLE';
    if(c?.contains?.('highlight-blue'))return 'BLUE';
    if(c?.contains?.('highlight-gold'))return 'GOLD';
    return 'UNKNOWN';
  }
  function cardLeague(card){
    const match=card?.__sbbMatch||{};const direct=clean(match.competitionId||match.__sbbLeague||match.league,20).toUpperCase();if(direct)return direct;
    const cls=String(card?.className||'');const m=cls.match(/(?:^|\s)league-([a-z0-9-]+)/i);return m?m[1].toUpperCase():'UNKNOWN';
  }
  function cardKey(card){
    const date=clean(hooks()?.scoreDate?.()||'',10);return clean(card?.dataset?.sbbGameKey||`${date}:${cardLeague(card)}:${card?.textContent||''}`,300);
  }
  function cardMediaKey(card){
    try{
      const match=card?.__sbbMatch;if(!match)return '';
      const resolved=window.scoreCardAvailability?.(match);const primary=resolved?.primary||window.scoreCardPrimaryItem?.(match,resolved?.items||[]);
      return clean(window.playbackItemKey?.(primary)||'',500);
    }catch(_){return '';}
  }
  function ribbonCandidates(){
    let cards=[];try{cards=[...(document.querySelectorAll?.('#scoreCells .score-card.has-highlights')||[])];}catch(_){cards=[];}
    return cards.filter(card=>!card?.disabled&&typeof card?.click==='function'&&!seenCardKeys.has(cardKey(card)));
  }
  function targetQuality(){return QUALITY_ROTATION[endurance.transitions%QUALITY_ROTATION.length];}
  function chooseRibbonCandidate(){
    const cards=ribbonCandidates();if(!cards.length)return null;
    const wanted=targetQuality(),sportCounts=endurance.sports||{},ranked=[];
    for(const card of cards){
      const quality=cardQuality(card),league=cardLeague(card),key=cardKey(card),mediaKey=cardMediaKey(card);
      if(mediaKey&&(seenMediaKeys.has(mediaKey)||quarantinedMediaKeys.has(mediaKey))){
        endurance.preflightDuplicateSkips++;seenCardKeys.add(key);enduranceLog('duplicate-preflight-skip',`Skipped already-seen ribbon media before click • ${league} ${quality}`,{mediaKey});continue;
      }
      let score=0;if(quality===wanted)score+=180;if(quality!==endurance.lastQuality)score+=55;if(league!==endurance.lastLeague)score+=70;
      score+=Math.max(0,60-12*Number(sportCounts[league]||0));if(quality==='GREEN'||quality==='PURPLE'||quality==='BLUE')score+=20;
      ranked.push({card,quality,league,key,mediaKey,score:score+randomUnit()});
    }
    return ranked.sort((a,b)=>b.score-a.score)[0]||null;
  }
  async function clickRibbonCandidate(candidate){
    if(!candidate?.card)return false;
    seenCardKeys.add(candidate.key);endurance.pendingQuality=candidate.quality;endurance.pendingDate=clean(hooks()?.scoreDate?.()||'',10);endurance.pendingLeague=candidate.league;endurance.pendingCardKey=candidate.key;endurance.pendingStressSelection=true;
    try{candidate.card.click();enduranceLog('ribbon-tune',`Ribbon ${candidate.league} ${candidate.quality} • ${endurance.pendingDate}`,{mediaKey:candidate.mediaKey||''});return true;}catch(err){endurance.pendingStressSelection=false;enduranceLog('ribbon-error',`Ribbon tune failed: ${err?.message||err}`);return false;}
  }
  async function waitForRibbonCandidate(timeoutMs=ARCHIVE_DATE_LOAD_TIMEOUT_MS){
    const deadline=epoch()+Math.max(500,Number(timeoutMs)||0);
    while(epoch()<deadline){const candidate=chooseRibbonCandidate();if(candidate)return candidate;await sleep(250);}
    return null;
  }
  async function switchStressDate(){
    const h=hooks();if(!h?.setScoreDate||!h?.today)return null;
    const today=clean(h.today(),10);let before=clean(h.scoreDate?.(),10);
    for(let attempt=0;attempt<ARCHIVE_DATE_MAX_ATTEMPTS;attempt++){
      const target=randomArchiveTarget(today,before);if(!target)break;endurance.randomDateAttempts++;
      try{
        await Promise.resolve(h.setScoreDate(target));enduranceLog('date-probe',`Random archive probe ${before||'—'} → ${target}`);await sleep(350);
        const candidate=await waitForRibbonCandidate();
        if(!candidate){enduranceLog('date-empty',`Random archive date ${target} had no unseen playable ribbon media`);continue;}
        const jump=dateDistanceDays(target,before);if(before&&target!==before){endurance.dateChanges++;if(jump>=LONG_DATE_JUMP_DAYS)endurance.longDateJumps++;}
        seenStressDates.add(target);updateArchiveSpan(target);bump(endurance.months,target.slice(0,7));endurance.pendingDate=target;
        enduranceLog('date-swap',`Random archive date ${before||'—'} → ${target} • jump ${jump}d`,{jumpDays:jump,league:candidate.league,quality:candidate.quality});return candidate;
      }catch(err){enduranceLog('date-error',`Random archive date ${target} failed: ${err?.message||err}`);}
    }
    return null;
  }
  function shouldRandomArchiveJump(phase){
    const every=phase?.id==='hammer'?4:(phase?.id==='soak'?5:6);return endurance.transitions>0&&endurance.transitions%every===0;
  }
  async function tuneUnseenProgram(){
    const h=hooks();if(!h)return false;
    const limit=Math.max(2,Math.min(80,Number(h.programSize?.()||12)));
    for(let attempt=0;attempt<limit;attempt++){
      endurance.pendingStressSelection=true;
      let moved=await Promise.resolve(h.stressTuneNextGame?.());if(!moved)moved=await Promise.resolve(h.stressTuneNext?.());if(!moved){endurance.pendingStressSelection=false;return false;}
      const media=clean(h.currentMediaKey?.(),500),game=clean(h.currentGameKey?.(),240);
      if((media&&seenMediaKeys.has(media))||(game&&seenEventKeys.has(game))){endurance.duplicateSelections++;endurance.pendingStressSelection=false;continue;}
      endurance.pendingQuality='';endurance.pendingDate=clean(h.scoreDate?.(),10);endurance.pendingLeague='';return true;
    }
    endurance.pendingStressSelection=false;return false;
  }
  async function mixedMediaTune({forceArchive=false}={}){
    if(forceArchive){const randomCandidate=await switchStressDate();if(randomCandidate)return clickRibbonCandidate(randomCandidate);}
    let candidate=chooseRibbonCandidate();if(candidate)return clickRibbonCandidate(candidate);
    const randomCandidate=await switchStressDate();if(randomCandidate)return clickRibbonCandidate(randomCandidate);
    return tuneUnseenProgram();
  }
  function inferLeague(row){
    const direct=clean(row?.league||'',20).toUpperCase();if(direct)return direct;
    const event=clean(row?.eventKey||'',120).toUpperCase(),parts=event.split(':');
    const fromEvent=parts.find(part=>SPORT_IDS.includes(part))||'';if(fromEvent)return fromEvent;
    const pending=clean(endurance.pendingLeague||'',20).toUpperCase();if(SPORT_IDS.includes(pending))return pending;return 'UNKNOWN';
  }

  function classifyQuality(row){
    if(endurance.pendingQuality&&endurance.pendingQuality!=='UNKNOWN')return endurance.pendingQuality;
    const text=`${row?.title||''}`.toLowerCase();
    if(/extended|condensed|full match replay|full-game replay|full game replay|10[- ]minute|20[- ]minute/.test(text))return 'PURPLE';
    let recap=false;try{const h=hooks(),currentKey=clean(h?.currentMediaKey?.(),500);if(!currentKey||currentKey===row.mediaKey)recap=h?.currentIsFullRecap?.()===true;}catch(_){ }
    return recap?'GREEN':'BLUE';
  }

  async function fallbackAfterNoFrame(row,reason){
    const h=hooks();if(!h)return false;
    const beforeGame=clean(row?.eventKey||h.currentGameKey?.(),240);let moved=false;
    try{moved=await Promise.resolve(h.stressTuneNext?.());}catch(_){moved=false;}
    if(!moved){try{moved=await Promise.resolve(h.stressTuneNextGame?.());}catch(_){moved=false;}}
    if(moved){
      endurance.fallbacks++;endurance.transitions++;const afterGame=clean(h.currentGameKey?.(),240);if(!beforeGame||!afterGame||beforeGame!==afterGame)endurance.crossGameTransitions++;
      endurance.pendingQuality='';endurance.pendingDate=clean(h.scoreDate?.(),10);endurance.pendingLeague='';
      enduranceLog('fallback',`${beforeGame&&afterGame===beforeGame?'Same-event':'Next-event'} fallback after ${reason}`,{mediaKey:row?.mediaKey||''});
    }
    return moved;
  }
  function queueNoFrameRecovery(row,reason){
    const runId=endurance.runId;
    setTimeout(async()=>{
      if(endurance.status!=='RUNNING'||endurance.runId!==runId)return;
      if(endurance.actionBusy){setTimeout(()=>queueNoFrameRecovery(row,reason),500);return;}
      endurance.actionBusy=true;endurance.recoveryAttempts++;endurance.recoveryArmed=true;
      try{
        const h=hooks();const key=clean(row.mediaKey,500);const failures=Number(mediaFailures.get(key)||0);
        if(failures===1){
          endurance.retryAttempts++;endurance.recovery={stage:'retry',mediaKey:key,eventKey:row.eventKey};
          let reset=false;try{reset=h?.forcePlaybackEngineReset?.()===true;}catch(_){ }
          enduranceLog('retry',`${reset?'Clean engine reset + retry':'Retry'} • ${clean(row.title,100)}`,{mediaKey:key});
          let retried=false;try{retried=await Promise.resolve(h?.restoreMediaKey?.(key));}catch(_){retried=false;}
          if(!retried){const moved=await fallbackAfterNoFrame(row,`${reason} (retry unavailable)`);if(!moved){endurance.unrecoveredBlanks++;failEndurance(`UNRECOVERABLE_NO_FIRST_FRAME • ${clean(row.title,100)}`);}}
        }else{
          if(key&&!successfulMediaKeys.has(key)&&!quarantinedMediaKeys.has(key)){
            quarantinedMediaKeys.add(key);endurance.assetBad++;enduranceLog('asset-bad',`ASSET_BAD after ${failures} independent no-frame starts • ${clean(row.title,100)}`,{mediaKey:key});
          }
          endurance.recovery={stage:'fallback',mediaKey:key,eventKey:row.eventKey};
          const moved=await fallbackAfterNoFrame(row,reason);if(!moved){endurance.unrecoveredBlanks++;failEndurance(`UNRECOVERABLE_NO_FIRST_FRAME • no fallback for ${clean(row.title,100)}`);}
        }
      }catch(err){endurance.unrecoveredBlanks++;failEndurance(`RECOVERY_EXCEPTION • ${err?.message||err}`);}
      finally{if(endurance.runId===runId)endurance.actionBusy=false;}
    },300);
  }
  function queueDuplicateCandidateReplacement(row,stage='selection'){
    const runId=endurance.runId;
    setTimeout(async()=>{
      if(endurance.status!=='RUNNING'||endurance.runId!==runId)return;
      if(endurance.actionBusy){setTimeout(()=>queueDuplicateCandidateReplacement(row,stage),350);return;}
      endurance.actionBusy=true;
      try{
        const moved=await mixedMediaTune({forceArchive:true});
        if(moved){endurance.transitions++;endurance.noCandidateCount=0;enduranceLog('duplicate-replacement',`Replaced rejected duplicate candidate after ${stage}`);}
        else{endurance.noCandidateCount++;if(endurance.noCandidateCount>=4)failEndurance('INSUFFICIENT_UNIQUE_PROGRAM • duplicate candidate replacement exhausted unseen media');}
      }catch(err){enduranceLog('duplicate-replacement-error',clean(err?.message||err,160));}
      finally{if(endurance.runId===runId){endurance.actionBusy=false;endurance.nextTransitionAt=epoch()+1200;}}
    },150);
  }
  function rejectDuplicateStressCandidate(row,stage){
    endurance.duplicateCandidateRejects++;endurance.pendingStressSelection=false;row.rejectedDuplicate=true;
    enduranceLog('duplicate-candidate-rejected',`Rejected stress-selected duplicate ${stage} • ${clean(row.title,100)}`,{mediaKey:row.mediaKey,eventKey:row.eventKey});
    queueDuplicateCandidateReplacement(row,stage);return true;
  }
  function noteNoFrame(row,reason='session left without first frame'){
    if(!row||row.noFrameCounted||row.enduranceRunId!==endurance.runId||endurance.status!=='RUNNING')return;
    row.noFrameCounted=true;const key=clean(row.mediaKey,500);
    if(key&&seenMediaKeys.has(key)){if(row.stressDriven)return rejectDuplicateStressCandidate(row,'before first frame');endurance.repeatViolations++;return failEndurance(`REPEATED_MEDIA_SELECTION before frame • ${clean(row.title,100)}`);}
    endurance.noFrameStreak++;endurance.maxNoFrameStreak=Math.max(endurance.maxNoFrameStreak,endurance.noFrameStreak);
    const failures=(Number(mediaFailures.get(key)||0)+1);if(key)mediaFailures.set(key,failures);
    enduranceLog('no-frame',`${reason} • streak ${endurance.noFrameStreak} • asset attempt ${failures}`,{sessionId:row.sessionId,mediaKey:key});
    if(endurance.noFrameStreak>2){endurance.unrecoveredBlanks++;return failEndurance(`UNRECOVERABLE_NO_FIRST_FRAME • streak ${endurance.noFrameStreak} • ${clean(row.title,100)}`);}
    queueNoFrameRecovery(row,reason);
  }
  function noteFirstFrame(row){
    if(!row||row.firstFrameCounted||row.enduranceRunId!==endurance.runId||endurance.status!=='RUNNING')return;
    row.firstFrameCounted=true;const key=clean(row.mediaKey,500);
    if(key&&seenMediaKeys.has(key)){if(row.stressDriven)return rejectDuplicateStressCandidate(row,'after first frame');endurance.repeatViolations++;return failEndurance(`REPEATED_MEDIA • ${clean(row.title,100)}`);}
    if(key){seenMediaKeys.add(key);successfulMediaKeys.add(key);}if(row.eventKey)seenEventKeys.add(row.eventKey);
    endurance.successfulStarts++;endurance.lastFirstFrameAt=epoch();endurance.noFrameStreak=0;
    const quality=classifyQuality(row),league=inferLeague(row),date=clean(endurance.pendingDate||hooks()?.scoreDate?.()||'UNKNOWN',20),transport=clean(row.transport||'UNKNOWN',32).toUpperCase()||'UNKNOWN';
    row.quality=quality;row.scoreDate=date;row.league=league;
    bump(endurance.sports,league);bump(endurance.qualities,quality);bump(endurance.dates,date);if(/^\d{4}-\d{2}-\d{2}$/.test(date)){bump(endurance.months,date.slice(0,7));updateArchiveSpan(date);}bump(endurance.transports,transport);bump(endurance.providers,clean(row.provider||'UNKNOWN',32).toUpperCase());
    if(endurance.lastLeague&&league!==endurance.lastLeague)endurance.sportChanges++;
    if(endurance.lastQuality&&quality!==endurance.lastQuality)endurance.qualityChanges++;
    if(endurance.lastTransport&&transport!==endurance.lastTransport)endurance.transportChanges++;
    if(endurance.recoveryArmed){
      endurance.recoveredAfterReset++;
      if(endurance.recovery?.stage==='retry'&&endurance.recovery.mediaKey===key)endurance.retrySuccesses++;
      enduranceLog('recovered',`${endurance.recovery?.stage==='retry'?'Retry':'Fallback'} produced first frame • ${clean(row.title,100)}`);
      endurance.recoveryArmed=false;endurance.recovery=null;
    }
    let isRecap=false,currentKey='';
    try{const h=hooks();currentKey=clean(h?.currentMediaKey?.(),500);if(!currentKey||currentKey===row.mediaKey)isRecap=h?.currentIsFullRecap?.()===true;}catch(_){ }
    row.isRecap=isRecap;
    if(isRecap&&row.eventKey){
      const previous=endurance.lastRecap;
      if(previous&&previous.eventKey===row.eventKey&&previous.mediaKey!==row.mediaKey){endurance.duplicateRecaps++;return failEndurance(`DUPLICATE_GAME_RECAP • same game switched recap assets: ${clean(previous.title,70)} → ${clean(row.title,70)}`);}
      endurance.lastRecap={eventKey:row.eventKey,mediaKey:row.mediaKey,title:row.title,sessionId:row.sessionId};
    }
    endurance.lastLeague=league;endurance.lastQuality=quality;endurance.lastDate=date;endurance.lastTransport=transport;endurance.lastMediaKey=key;endurance.lastEventKey=row.eventKey;
    endurance.pendingQuality='';endurance.pendingDate='';endurance.pendingLeague='';endurance.pendingCardKey='';endurance.pendingStressSelection=false;
  }

  function ingest(session,t=now()){
    session=session||{};const sid=clean(session.sessionId||`selection-${session.selectionId||0}`,120);if(!sid)return null;
    if(lastSessionId&&lastSessionId!==sid){
      const prev=bySession.get(lastSessionId);
      if(prev){finalizeState(prev,t);if(!['failed','ended'].includes(prev.state))prev.exitState=prev.firstFrameAt?'LEFT':'SKIPPED/NO FRAME';if(!prev.firstFrameAt)noteNoFrame(prev,'session changed before first frame');}
    }
    lastSessionId=sid;let row=bySession.get(sid);
    if(!row){
      row={sessionId:sid,selectionId:Number(session.selectionId||0),eventKey:clean(session.eventKey||'',240),title:clean(session.title||'Untitled',120),league:clean(session.league||'',20),provider:clean(session.provider||'',32),transport:clean(session.transport||'',28),mediaKey:clean(session.mediaKey||'',500),source:clean(session.sourceExternalUrl||session.sourceUrl||'',500),state:'selected',stateStartedPerf:t,playingMs:0,bufferingMs:0,firstFrameAt:0,firstFrameMs:null,firstFrameCounted:false,noFrameCounted:false,isRecap:false,quality:'',scoreDate:'',stallCount:0,sessionStallTotalMs:0,failureCount:0,lastError:'',createdPerf:t,selectedAt:Number(session.selectedAt||epoch()),exitState:'',enduranceRunId:endurance.status==='RUNNING'?endurance.runId:'',stressDriven:endurance.status==='RUNNING'&&endurance.pendingStressSelection===true,rejectedDuplicate:false};
      bySession.set(sid,row);rows.unshift(row);if(rows.length>240){const gone=rows.pop();bySession.delete(gone.sessionId);}
    }
    const nextState=clean(session.state||row.state,24).toLowerCase();if(nextState&&nextState!==row.state){finalizeState(row,t);row.state=nextState;row.stateStartedPerf=t;}
    row.eventKey=clean(session.eventKey||row.eventKey,240);row.title=clean(session.title||row.title,120);row.league=clean(session.league||row.league,20);row.provider=clean(session.provider||row.provider,32);row.transport=clean(session.transport||row.transport,28);row.mediaKey=clean(session.mediaKey||row.mediaKey,500);row.source=clean(session.sourceExternalUrl||session.sourceUrl||row.source,500);
    const hadFrame=!!row.firstFrameAt;row.firstFrameAt=Math.max(Number(row.firstFrameAt||0),Number(session.firstFrameAt||0));if(session.firstFrameMs!=null)row.firstFrameMs=Number(session.firstFrameMs);
    row.stallCount=Math.max(Number(row.stallCount||0),Number(session.stallCount||0));row.sessionStallTotalMs=Math.max(Number(row.sessionStallTotalMs||0),Number(session.stallTotalMs||0));row.failureCount=Math.max(Number(row.failureCount||0),Number(session.failureCount||0));row.lastError=clean(session.lastError||row.lastError,180);
    if(!hadFrame&&row.firstFrameAt)noteFirstFrame(row);
    if(row.state==='failed'&&!row.firstFrameAt)setTimeout(()=>noteNoFrame(row,`session failed before first frame${row.lastError?`: ${row.lastError}`:''}`),500);
    render();return row;
  }

  function snapshot(){const t=now();return rows.map(r=>({...r,playTimeMs:durationFor(r,'playing',t),bufferTimeMs:Math.max(durationFor(r,'buffering',t),Number(r.sessionStallTotalMs||0))}));}
  function clear(){rows.splice(0);bySession.clear();lastSessionId='';render();}

  async function enduranceTransition(phase){
    const h=hooks();if(!h||endurance.actionBusy||endurance.status!=='RUNNING')return;
    const current=bySession.get(lastSessionId);if(current&&!current.firstFrameAt){endurance.nextTransitionAt=epoch()+2500;return;}
    endurance.actionBusy=true;const beforeKey=clean(h.currentGameKey?.(),240),runId=endurance.runId;
    try{
      if(phase.disruptStandby){try{h.chaosDisruptStandby?.();endurance.standbyDisruptions++;enduranceLog('standby-disrupt',`Mixed hammer disrupted standby before transition ${endurance.transitions+1}`);}catch(err){enduranceLog('standby-disrupt-error',clean(err?.message||err,140));}}
      let moved=false;if(shouldRandomArchiveJump(phase)){const randomCandidate=await switchStressDate();if(randomCandidate)moved=await clickRibbonCandidate(randomCandidate);}
      if(!moved)moved=await mixedMediaTune();
      if(moved){
        endurance.transitions++;const afterKey=clean(h.currentGameKey?.(),240);if(!beforeKey||!afterKey||beforeKey!==afterKey)endurance.crossGameTransitions++;
        endurance.noCandidateCount=0;enduranceLog('transition',`${phase.label} transition ${endurance.transitions} • target ${targetQuality()}`);
      }else{
        endurance.noCandidateCount++;enduranceLog('no-candidate',`${phase.label} found no unseen playable item (${endurance.noCandidateCount})`);
        if(endurance.noCandidateCount>=4)failEndurance('INSUFFICIENT_UNIQUE_PROGRAM • no unseen playable item after four attempts');
      }
    }catch(err){enduranceLog('transition-error',`Transition failed: ${err?.message||err}`);}
    finally{if(endurance.runId===runId){endurance.actionBusy=false;endurance.nextTransitionAt=epoch()+nextTransitionDelay(phase);}}
  }

  async function startEndurance(){
    if(endurance.status==='RUNNING')return false;
    const h=hooks();if(!devEnabled()||!h)return false;
    const engine=h.playbackEngine?.()||{};resetEnduranceMemory();endurance=freshEndurance('RUNNING');endurance.runId=`end-${epoch().toString(36)}`;endurance.startedAt=epoch();endurance.phase='warmup';endurance.phaseLabel='WARMUP';endurance.phaseStartedAt=endurance.startedAt;endurance.nextTransitionAt=endurance.startedAt+20_000;endurance.savedResourceMode=clean(h.resourceMode?.()||'balanced',24);endurance.savedMediaKey=clean(h.currentMediaKey?.(),500);endurance.savedScoreDate=clean(h.scoreDate?.(),20);endurance.engineIncidentsBase=Number(engine.incidents||0);endurance.engineResetsBase=Number(engine.resets||0);
    enduranceLog('start','60-minute random-archive mixed-media endurance started • 365-day random date pool • 10m warmup → 30m mixed soak → 20m mixed hammer');clear();
    try{await h.setResourceMode?.('playback');}catch(err){return failEndurance(`PLAYBACK_MODE_FAILED • ${err?.message||err}`);}
    try{h.start?.();h.ensurePlaying?.();}catch(err){return failEndurance(`PLAYBACK_START_FAILED • ${err?.message||err}`);}
    if(Number(h.programSize?.()||0)<2&&ribbonCandidates().length<2)return failEndurance('INSUFFICIENT_PROGRAM • mixed endurance requires at least two playable items');
    try{const current=window.SBB_PLAYBACK_SESSION?.snapshot?.();if(current?.sessionId)ingest(current);}catch(_){ }
    render();return true;
  }

  function enduranceTick(){
    if(endurance.status!=='RUNNING')return;
    const h=hooks();if(!h)return failEndurance('DEV_HOOKS_LOST');
    const elapsed=epoch()-endurance.startedAt,phase=endurancePhaseAt(elapsed);if(!phase)return passEndurance();
    if(endurance.phase!==phase.id){endurance.phase=phase.id;endurance.phaseLabel=phase.label;endurance.phaseStartedAt=epoch();endurance.nextTransitionAt=epoch()+Math.min(12_000,phase.minTransitionMs);enduranceLog('phase',`${phase.label} phase started`);}
    const invariant=clean(h.invariant?.()||'OK',140);if(invariant.startsWith('ERROR'))return failEndurance(`PLAYBACK_INVARIANT • ${invariant}`);
    const current=bySession.get(lastSessionId),age=current?epoch()-Number(current.selectedAt||epoch()):0;
    if(current&&current.enduranceRunId===endurance.runId&&!current.firstFrameAt&&age>=FIRST_FRAME_WATCHDOG_MS&&!current.noFrameCounted){noteNoFrame(current,`first-frame watchdog ${Math.round(age/1000)}s`);return;}
    if(epoch()>=endurance.nextTransitionAt&&!endurance.actionBusy)enduranceTransition(phase);
    renderEndurance();
  }

  function renderEndurance(){
    const status=document.getElementById('playbackEnduranceStatus'),detail=document.getElementById('playbackEnduranceDetail'),bar=document.getElementById('playbackEnduranceProgress'),start=document.getElementById('playbackEnduranceStart'),stop=document.getElementById('playbackEnduranceStop');if(!status||!detail)return;
    const s=enduranceSnapshot(),sports=SPORT_IDS.filter(k=>Number(s.sports?.[k]||0)>0).length,colors=QUALITY_ROTATION.filter(q=>Number(s.qualities[q]||0)>0).length,dates=counterKeys(s.dates).length;
    status.textContent=s.status;status.dataset.state=s.status.toLowerCase();
    if(s.status==='RUNNING')detail.textContent=`${s.phaseLabel} ${fmtClock(s.elapsedMs)} / 60:00 • STARTS ${s.successfulStarts} • UNIQUE ${s.uniqueMedia} • XITIONS ${s.transitions} • SPORTS ${sports} • COLORS ${colors}/3 • DATES ${dates} • SPAN ${s.archiveSpanDays}d • LONG JUMPS ${s.longDateJumps} • DUP REJECT ${s.duplicateCandidateRejects} • NOFRAME ${s.noFrameStreak}`;
    else if(['PASS','FAIL','STOPPED'].includes(s.status))detail.textContent=`${s.reason} • ${fmtClock(s.elapsedMs)} • UNIQUE ${s.uniqueMedia} • SPORTS ${sports} • COLORS ${colors}/3 • DATES ${dates} • RETRIES ${s.retryAttempts} • FALLBACKS ${s.fallbacks} • BAD ${s.assetBad}`;
    else detail.textContent='60:00 • GREEN/PURPLE/BLUE • multi-sport • random dates across 365 days • long archive jumps • duplicate candidates rejected before certification • retry → fallback recovery';
    if(bar)bar.style.width=`${Math.max(0,Math.min(100,s.progress*100)).toFixed(1)}%`;if(start)start.disabled=s.status==='RUNNING';if(stop)stop.disabled=s.status!=='RUNNING';
  }

  function render(){
    const host=document.getElementById('playbackTerminal');if(!host)return;host.classList.toggle('is-visible',devEnabled());if(!devEnabled())return;
    const body=document.getElementById('playbackTerminalRows'),summary=document.getElementById('playbackTerminalSummary');if(!body||!summary)return;
    const data=snapshot(),rt=window.SBB_ULTIMATE_PLAYBACK?.runtimeSnapshot?.()||{},metrics=rt.metrics||window.SBB_ULTIMATE_PLAYBACK?.metrics?.()||{},engine=hooks()?.playbackEngine?.()||{};
    const totalPlay=data.reduce((a,r)=>a+r.playTimeMs,0),totalBuffer=data.reduce((a,r)=>a+r.bufferTimeMs,0),ratio=totalPlay?100*totalBuffer/totalPlay:0;
    summary.textContent=`PLAY ${fmtMs(totalPlay)}  •  BUFFER ${fmtMs(totalBuffer)} (${ratio.toFixed(1)}%)  •  HOT ${Number(metrics.hotStandbyHitRate??100).toFixed(1)}%  •  RUNWAY ${rt.bufferAhead==null?'—':Number(rt.bufferAhead).toFixed(1)+'s'}  •  ENGINE ${Number(engine.incidents||0)}I/${Number(engine.resets||0)}R  •  NEXT ${rt.standby?.ready?'HOT_READY':rt.standby?.warming?'WARMING':'IDLE'}`;
    body.innerHTML=data.slice(0,40).map((r,i)=>{const item={mediaKey:r.mediaKey,competitionId:r.league,provider:r.provider,transport:r.transport};const ready=window.SBB_PLAYBACK_READINESS?.state?.(item)||'DISCOVERED',score=window.SBB_PLAYBACK_READINESS?.score?.(item)??80;const rowStatus=r.exitState||r.state.toUpperCase();const src=r.source?` title="${esc(r.source)}"`:'';return `<div class="pt-row"><span>${String(data.length-i).padStart(2,'0')}</span><b class="pt-state">${esc(rowStatus)}</b><span>${esc(r.league||'—')}</span><span>${esc(r.transport||'—')}</span><span>${esc(r.provider||'—')}</span><span>${fmtMs(r.playTimeMs)}</span><span>${fmtMs(r.bufferTimeMs)}</span><span>${r.stallCount}</span><span>${r.firstFrameMs==null?'—':Math.round(r.firstFrameMs)+'ms'}</span><span>${esc(ready)}</span><span>${Math.round(Number(score||0))}</span><span${src}>${esc(`${r.quality?`[${r.quality}] `:''}${r.title||'Untitled'}`)}</span></div>`;}).join('')||'<div class="pt-empty">Waiting for playback sessions…</div>';
    renderEndurance();
  }

  window.addEventListener?.('sbb:playback-session',ev=>ingest(ev?.detail||{}));
  window.addEventListener?.('sbb:playback-engine',ev=>{if(endurance.status==='RUNNING')enduranceLog('engine',`ENGINE ${clean(ev?.detail?.type||'event',30).toUpperCase()} • ${clean(ev?.detail?.reason||'',120)}`);render();});
  window.addEventListener?.('sbb:dev-mode',render);
  document.addEventListener('DOMContentLoaded',()=>{
    document.getElementById('playbackTerminalClear')?.addEventListener('click',clear);
    document.getElementById('playbackTerminalCopy')?.addEventListener('click',()=>{const s=enduranceSnapshot(),sports=SPORT_IDS.filter(k=>Number(s.sports?.[k]||0)>0).join(','),colors=QUALITY_ROTATION.filter(q=>Number(s.qualities[q]||0)>0).join(','),dates=counterKeys(s.dates).join(','),months=counterKeys(s.months).join(',');const head=`ENDURANCE\t${s.status}\t${s.phaseLabel}\tELAPSED=${fmtClock(s.elapsedMs)}\tSTARTS=${s.successfulStarts}\tUNIQUE=${s.uniqueMedia}\tTRANSITIONS=${s.transitions}\tSPORTS=${sports}\tCOLORS=${colors}\tDATES=${dates}\tMONTHS=${months}\tDATE_SWAPS=${s.dateChanges}\tDATE_SPAN=${s.archiveSpanDays}d\tLONG_JUMPS=${s.longDateJumps}\tRANDOM_DATE_TRIES=${s.randomDateAttempts}\tDUP_REJECTS=${s.duplicateCandidateRejects}\tPREFLIGHT_SKIPS=${s.preflightDuplicateSkips}\tNOFRAME_MAX=${s.maxNoFrameStreak}\tRESETS=${s.engineResets}\tRETRIES=${s.retryAttempts}\tRETRY_OK=${s.retrySuccesses}\tFALLBACKS=${s.fallbacks}\tASSET_BAD=${s.assetBad}\tREPEATS=${s.repeatViolations}\t${s.reason}`;const lines=snapshot().filter(r=>r.enduranceRunId===s.runId).map(r=>`${inferLeague(r)}\t${r.quality||''}\t${r.scoreDate||''}\t${r.transport}\t${r.provider}\tRESULT=${r.rejectedDuplicate?'DUPLICATE_REJECTED':'ACCEPTED'}\tPLAY=${fmtMs(r.playTimeMs)}\tBUFFER=${fmtMs(r.bufferTimeMs)}\tSTALLS=${r.stallCount}\tSTART=${r.firstFrameMs??''}\tEVENT=${r.eventKey}\tMEDIA=${r.mediaKey}\t${r.title}`);navigator.clipboard?.writeText?.([head,...lines].join('\n')).catch(()=>{});});
    document.getElementById('playbackEnduranceStart')?.addEventListener('click',()=>startEndurance());document.getElementById('playbackEnduranceStop')?.addEventListener('click',stopEndurance);
    render();tickTimer=setInterval(render,500);enduranceTimer=setInterval(enduranceTick,1000);
  });
  try{const s=window.SBB_PLAYBACK_SESSION?.snapshot?.();if(s?.sessionId)ingest(s);}catch(_){ }
  window.SBB_PLAYBACK_TERMINAL=Object.freeze({version:'1.3',snapshot,clear,ingest,render,endurance:Object.freeze({start:startEndurance,stop:stopEndurance,snapshot:enduranceSnapshot,phases:PHASES,totalMs:ENDURANCE_TOTAL_MS})});
})();

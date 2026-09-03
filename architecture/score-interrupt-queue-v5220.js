/* Sports Big Board v5.3.16 — score-ribbon league-day queue + interrupt preservation.
   A score-card click starts the clicked game immediately, then PROGRAM expands to
   every playback-ready game from that same league and date. NEXT/PREV therefore
   remain useful after a score selection instead of operating on a one-game queue.
   Explicit Team/Player Focus queues are still preserved as true interrupts. */
(() => {
  'use strict';
  if(window.SBB_SCORE_INTERRUPT_QUEUE?.version==='5.3.16')return;
  const VERSION='5.3.16';
  const state={snapshot:null,captures:0,resumes:0,projected:0,leagueDayBuilds:0,lastLeagueDay:'',lastLeagueDayCount:0,lastReason:'',lastError:''};

  const clean=v=>String(v??'').trim();
  const itemId=item=>clean(item?.id||item?.youtubeId||item?.videoId||item?.mediaUrl);
  function gameKey(item){
    try{return typeof programGameIdentity==='function'?String(programGameIdentity(item)||''):'';}catch(_){return '';}
  }
  function sameGame(a,b){
    try{return typeof sameGameProgramItem==='function'?!!sameGameProgramItem(a,b):gameKey(a)&&gameKey(a)===gameKey(b);}catch(_){return gameKey(a)&&gameKey(a)===gameKey(b);}
  }

  function matchLeague(match){
    return clean(match?.__sbbLeague||match?.competitionId||match?.league).toUpperCase();
  }

  function withLeagueFilter(league,callback){
    if(!league||typeof callback!=='function')return [];
    let previous='ALL';
    try{
      previous=typeof scoreRibbonLeagueFilter!=='undefined'?scoreRibbonLeagueFilter:'ALL';
      scoreRibbonLeagueFilter=league;
      return callback()||[];
    }catch(err){state.lastError=String(err?.message||err);return [];}
    finally{try{scoreRibbonLeagueFilter=previous;}catch(_){}}
  }

  function expandScoreSelectionToLeagueDay(){
    try{
      const session=(typeof userPlaybackSession!=='undefined')?userPlaybackSession:null;
      if(session?.source!=='score'||!Array.isArray(PROGRAM)||!PROGRAM.length)return false;
      const date=clean(session.playbackDate||session.match?.date||session.match?.gameDate).slice(0,10);
      const league=matchLeague(session.match)||matchLeague(PROGRAM[0]);
      if(!date||!league||typeof programForScoreDate!=='function')return false;

      // app.js intentionally commits the clicked game's exact media first so the
      // click is never delayed. This post-commit hook keeps those exact selected
      // clip(s) at the front, then appends the rest of the clicked league/date.
      const selectedCount=Math.max(1,Math.min(Number(session.selectionCount)||1,PROGRAM.length));
      const selected=PROGRAM.slice(0,selectedCount).filter(Boolean);
      const queue=withLeagueFilter(league,()=>{
        if(typeof dateProgramWithSelectionFirst==='function')return dateProgramWithSelectionFirst(date,selected);
        const base=programForScoreDate(date);
        const remainder=(base||[]).filter(item=>!selected.some(sel=>itemId(item)===itemId(sel)||sameGame(item,sel)));
        return [...selected,...remainder];
      });
      if(!queue.length)return false;

      // Dedupe exact media assets while preserving multiple clips that intentionally
      // form one blue highlight reel. same-game items are therefore not collapsed.
      const seen=new Set(),deduped=[];
      for(const item of queue){
        if(!item)continue;
        const key=itemId(item)||`${gameKey(item)}:${deduped.length}`;
        if(key&&seen.has(key))continue;
        if(key)seen.add(key);
        deduped.push(item);
      }
      if(!deduped.length)return false;
      PROGRAM=[...deduped];
      currentIndex=0;
      standbyIndex=0;
      session.leagueDayQueue=true;
      session.queueLeague=league;
      session.queueDate=date;
      session.queueLength=PROGRAM.length;
      state.leagueDayBuilds++;
      state.lastLeagueDay=`${league}:${date}`;
      state.lastLeagueDayCount=PROGRAM.length;
      state.lastReason=`score selection expanded to ${league} ${date}`;
      try{if(typeof renderQueue==='function')renderQueue();}catch(_){}
      return true;
    }catch(err){state.lastError=String(err?.message||err);return false;}
  }

  function currentProgramSnapshot(){
    try{
      if(!Array.isArray(PROGRAM)||!PROGRAM.length)return null;
      const idx=Math.max(0,Math.min(Number(currentIndex)||0,PROGRAM.length-1));
      const item=PROGRAM[idx]||null;
      return {
        program:[...PROGRAM],
        currentIndex:idx,
        currentItemId:itemId(item),
        currentGameKey:gameKey(item),
        playbackDate:clean(typeof playbackDateContext!=='undefined'?playbackDateContext?.date:''),
        capturedAt:Date.now(),
      };
    }catch(err){state.lastError=String(err?.message||err);return null;}
  }

  function shouldPreserveCurrentQueue(){
    try{const snap=window.SBB_CURATED_BROWSE?.snapshot?.();return !!(snap&&snap.mode!=='daily'&&snap.queueActive);}
    catch(_){return false;}
  }

  function capture(reason='score-card click'){
    try{
      // Normal score-ribbon playback is date-owned. Do not preserve whatever
      // general/today queue happened to be running before the click; this module
      // expands the committed selection into the clicked league/date queue. Only an explicit curated Team/Player
      // Focus program is an interruptible user-owned queue.
      if(!shouldPreserveCurrentQueue()){state.snapshot=null;state.lastReason='date-owned score selection';return null;}
      // A second score click during the same interrupt must still return to the
      // queue that existed before the FIRST interruption.
      if(typeof userPlaybackSession!=='undefined'&&userPlaybackSession?.source==='score'&&state.snapshot)return state.snapshot;
      const snap=currentProgramSnapshot();
      if(!snap)return null;
      state.snapshot=snap;state.captures++;state.lastReason=reason;
      return snap;
    }catch(err){state.lastError=String(err?.message||err);return null;}
  }

  function active(){
    try{return !!(state.snapshot&&typeof userPlaybackSession!=='undefined'&&userPlaybackSession?.source==='score');}
    catch(_){return false;}
  }

  function resumeIndex(session,snap){
    const list=snap?.program||[];
    let target=-1;
    const wantedId=clean(session?.resumeItemId)||snap?.currentItemId||'';
    if(wantedId)target=list.findIndex(x=>itemId(x)===wantedId);
    const wantedGame=clean(session?.resumeGameKey)||snap?.currentGameKey||'';
    if(target<0&&wantedGame)target=list.findIndex(x=>gameKey(x)===wantedGame);
    if(target<0)target=Math.max(0,Math.min(Number(session?.resumeIndex??snap?.currentIndex)||0,list.length-1));
    return target;
  }

  function entries(wanted=5){
    if(!active())return [];
    const snap=state.snapshot,session=userPlaybackSession,list=snap?.program||[];
    if(!list.length)return [];
    const start=resumeIndex(session,snap);
    if(start<0)return [];
    const out=[];
    for(let step=0;step<list.length&&out.length<wanted;step++){
      const idx=(start+step)%list.length,item=list[idx];
      if(!item)continue;
      if(step>0){
        try{if(typeof isGamePlayed==='function'&&isGamePlayed(item))continue;}catch(_){}
      }
      if(out.some(x=>sameGame(x.item,item)))continue;
      out.push({idx,item,interruptResume:true,resumeIndex:idx,position:out.length});
    }
    state.projected++;
    return out;
  }

  function restoreQueue(targetIndex,{userInitiated=false,reason='resume interrupted programming'}={}){
    const snap=state.snapshot;
    if(!snap?.program?.length)return false;
    try{
      const session=(typeof userPlaybackSession!=='undefined')?userPlaybackSession:null;
      const target=Number.isFinite(Number(targetIndex))?Number(targetIndex):resumeIndex(session,snap);
      if(typeof userPlaybackSession!=='undefined')userPlaybackSession=null;
      PROGRAM=[...snap.program];
      const bounded=Math.max(0,Math.min(target,PROGRAM.length-1));
      if(snap.playbackDate&&typeof activatePlaybackDateContext==='function'){
        try{activatePlaybackDateContext(snap.playbackDate,{source:'score-interrupt-resume'});}catch(_){}
      }
      state.snapshot=null;state.resumes++;state.lastReason=reason;
      try{if(typeof setFeedNote==='function')setFeedNote('Score highlight complete • returning to interrupted program');}catch(_){}
      try{if(typeof showBumper==='function')showBumper(bounded,650,'BACK TO PROGRAMMING');}catch(_){}
      if(typeof renderQueue==='function')try{renderQueue();}catch(_){}
      if(typeof tuneProgramIndexV5==='function'){
        tuneProgramIndexV5(bounded,{userInitiated:!!userInitiated,reason});
        return true;
      }
      return false;
    }catch(err){state.lastError=String(err?.message||err);return false;}
  }

  function play(entry){
    if(!entry?.interruptResume)return false;
    return restoreQueue(entry.resumeIndex,{userInitiated:true,reason:'Up Next selection from interrupted queue'});
  }

  function clear(reason='clear'){
    state.snapshot=null;state.lastReason=reason;
  }

  function patchScoreSessionQueue(){
    try{
      if(typeof beginScorePlaybackSession!=='function'||beginScorePlaybackSession.__sbbLeagueDayV5316)return false;
      const original=beginScorePlaybackSession;
      const wrapped=function(...args){
        const result=original.apply(this,args);
        expandScoreSelectionToLeagueDay();
        return result;
      };
      wrapped.__sbbLeagueDayV5316=true;wrapped.__sbbOriginal=original;
      beginScorePlaybackSession=wrapped;
      try{window.beginScorePlaybackSession=wrapped;}catch(_){}
      return true;
    }catch(err){state.lastError=String(err?.message||err);return false;}
  }

  function patchResume(){
    try{
      if(typeof resumeDateProgramAfterSelection!=='function'||resumeDateProgramAfterSelection.__sbbInterruptV5220)return false;
      const original=resumeDateProgramAfterSelection;
      const wrapped=function(...args){
        if(state.snapshot&&typeof userPlaybackSession!=='undefined'&&userPlaybackSession?.source==='score'){
          const session=userPlaybackSession;
          const target=resumeIndex(session,state.snapshot);
          if(restoreQueue(target,{userInitiated:false,reason:'automatic resume after score-ribbon interrupt'}))return;
        }
        state.snapshot=null;
        return original.apply(this,args);
      };
      wrapped.__sbbInterruptV5220=true;wrapped.__sbbOriginal=original;
      resumeDateProgramAfterSelection=wrapped;
      try{window.resumeDateProgramAfterSelection=wrapped;}catch(_){}
      return true;
    }catch(err){state.lastError=String(err?.message||err);return false;}
  }

  function bindScoreCapture(){
    document.addEventListener('click',event=>{
      const card=event.target?.closest?.('.score-card');
      if(!card)return;
      capture('score-ribbon click');
      // If the click did not become a score playback session, discard the stale
      // snapshot shortly afterward. A real session keeps it until resume/cancel.
      setTimeout(()=>{
        try{if(state.snapshot&&!(userPlaybackSession?.source==='score'))clear('score click without playback takeover');}catch(_){}
      },1800);
    },true);
  }

  function init(){
    patchScoreSessionQueue();
    patchResume();
    bindScoreCapture();
    // app.js normally exists before this module. The bounded retry also covers a
    // deferred/local script load without adding a polling loop.
    setTimeout(()=>{patchScoreSessionQueue();patchResume();},300);
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  window.SBB_SCORE_INTERRUPT_QUEUE=Object.freeze({version:VERSION,active,entries,play,capture,clear,restoreQueue,expandLeagueDay:expandScoreSelectionToLeagueDay,snapshot:()=>({version:VERSION,active:active(),captures:state.captures,resumes:state.resumes,projected:state.projected,leagueDayBuilds:state.leagueDayBuilds,lastLeagueDay:state.lastLeagueDay,lastLeagueDayCount:state.lastLeagueDayCount,lastReason:state.lastReason,lastError:state.lastError,queued:state.snapshot?.program?.length||0,resumeIndex:state.snapshot?resumeIndex((typeof userPlaybackSession!=='undefined'?userPlaybackSession:null),state.snapshot):-1})});
})();

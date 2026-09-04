/* Sports Big Board v5.4.0 — non-blocking score-ribbon league-day queue + interrupt preservation.
   A score-card click starts the clicked game immediately. The rest of that league/day
   is then assembled incrementally across browser tasks so a dense historical NBA/MLB
   date cannot monopolize the main thread while video continues playing. NEXT/PREV
   remain useful, and explicit Team/Player Focus queues remain true interrupts. */
(() => {
  'use strict';
  if(window.SBB_SCORE_INTERRUPT_QUEUE?.version==='5.4.0')return;
  const VERSION='5.4.0';
  const state={snapshot:null,captures:0,resumes:0,projected:0,leagueDayBuilds:0,lastLeagueDay:'',lastLeagueDayCount:0,lastReason:'',lastError:'',buildEpoch:0,buildActive:false,buildProcessed:0,buildTotal:0,buildMaxMatchMs:0,buildLastMatchMs:0,buildStartedAt:0,buildCompletedAt:0};

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

  const BUILD_YIELD_MS=0;
  const BUILD_RENDER_EVERY=3;

  function scoreRowsForLeagueDate(date,league){
    try{
      if(typeof scoreMatchesForDate!=='function')return [];
      return (scoreMatchesForDate(date)||[])
        .filter(match=>matchLeague(match)===league)
        .sort((a,b)=>{
          try{return new Date(a?.scheduledAt||a?.date||0)-new Date(b?.scheduledAt||b?.date||0);}catch(_){return 0;}
        });
    }catch(err){state.lastError=String(err?.message||err);return [];}
  }

  function queueStillOwned(build){
    try{
      if(!build||build.epoch!==state.buildEpoch)return false;
      if(document.body?.dataset?.sbbCuratedPlaybackOwner)return false;
      if(!Array.isArray(PROGRAM)||PROGRAM.length<build.selected.length)return false;
      for(let i=0;i<build.selected.length;i++)if(itemId(PROGRAM[i])!==itemId(build.selected[i]))return false;
      return true;
    }catch(_){return false;}
  }

  function scheduleRender(build,{final=false}={}){
    if(!queueStillOwned(build))return;
    if(final||!build.renderQueued){
      build.renderQueued=true;
      const run=()=>{
        build.renderQueued=false;if(!queueStillOwned(build))return;
        try{if(typeof renderQueue==='function')renderQueue();}catch(_){}
        if(final){try{if(typeof preflightUpcomingProgram==='function')preflightUpcomingProgram(currentIndex);}catch(_){}}
      };
      if(typeof requestAnimationFrame==='function')requestAnimationFrame(run);else setTimeout(run,0);
    }
  }

  function commitBuiltQueue(build,{final=false}={}){
    if(!queueStillOwned(build))return false;
    const merged=[...build.selected,...build.remainder];
    PROGRAM=merged;
    // Do not reset currentIndex while the viewer is already playing/advancing.
    // The selected-game prefix never changes, so appending can safely happen live.
    if(currentIndex>=PROGRAM.length)currentIndex=Math.max(0,PROGRAM.length-1);
    standbyIndex=PROGRAM.length>1?Math.min(Math.max(1,Number(standbyIndex)||1),PROGRAM.length-1):0;
    if(build.session){
      build.session.leagueDayQueue=true;build.session.queueLeague=build.league;build.session.queueDate=build.date;build.session.queueLength=PROGRAM.length;
      // selectionCount intentionally remains the number of clips in the clicked
      // game, not the entire date queue. NEXT can leave that game normally.
    }
    state.lastLeagueDayCount=PROGRAM.length;
    if(final)scheduleRender(build,{final:true});
    return true;
  }

  function mediaForMatch(match){
    try{
      if(typeof scoreCardPlayableItems!=='function'||typeof scoreCardPlaybackSelection!=='function')return [];
      const selection=scoreCardPlaybackSelection(match,scoreCardPlayableItems(match));
      if(!selection?.primary||!selection?.selectionItems?.length)return [];
      return selection.selectionItems.filter(item=>{
        try{return !!(item?.verifiedPlayable&&(item.youtubeId||item.mediaUrl)&&(typeof scoreMediaAirReady!=='function'||scoreMediaAirReady(item)));}
        catch(_){return false;}
      });
    }catch(err){state.lastError=String(err?.message||err);return [];}
  }

  function scheduleLeagueDayQueueExpansion(sessionOverride=null){
    try{
      const session=sessionOverride||((typeof userPlaybackSession!=='undefined')?userPlaybackSession:null);
      if(session?.source!=='score'||!Array.isArray(PROGRAM)||!PROGRAM.length)return false;
      const date=clean(session.playbackDate||session.match?.date||session.match?.gameDate).slice(0,10);
      const league=matchLeague(session.match)||matchLeague(PROGRAM[0]);
      if(!date||!league)return false;
      const selectedCount=Math.max(1,Math.min(Number(session.selectionCount)||1,PROGRAM.length));
      const selected=PROGRAM.slice(0,selectedCount).filter(Boolean);
      if(!selected.length)return false;
      const epoch=++state.buildEpoch;
      const selectedGameKeys=new Set(selected.map(gameKey).filter(Boolean));
      const seenMedia=new Set(selected.map(itemId).filter(Boolean));
      const build={epoch,session,date,league,selected,remainder:[],selectedGameKeys,seenMedia,rows:[],index:0,renderQueued:false,startedAt:performance.now()};
      state.buildActive=true;state.buildProcessed=0;state.buildTotal=0;state.buildMaxMatchMs=0;state.buildLastMatchMs=0;state.buildStartedAt=Date.now();state.buildCompletedAt=0;
      state.leagueDayBuilds++;state.lastLeagueDay=`${league}:${date}`;state.lastLeagueDayCount=selected.length;state.lastReason=`building ${league} ${date} queue without blocking playback`;

      // The first task runs only after the click handler/tune request has returned.
      // Match resolution is deliberately one game per task: even if one historical
      // event is expensive, the browser gets a paint/input opportunity before the next.
      setTimeout(()=>{
        if(!queueStillOwned(build)){if(epoch===state.buildEpoch)state.buildActive=false;return;}
        build.rows=scoreRowsForLeagueDate(date,league);
        build.rows=build.rows.filter(match=>{
          let key='';try{key=typeof scoreRibbonStableGameKey==='function'?clean(scoreRibbonStableGameKey(match)):'';}catch(_){}
          return !key||!build.selectedGameKeys.has(key);
        });
        state.buildTotal=build.rows.length;

        const pump=()=>{
          if(!queueStillOwned(build)){if(epoch===state.buildEpoch)state.buildActive=false;return;}
          if(build.index>=build.rows.length){
            commitBuiltQueue(build,{final:true});
            if(epoch===state.buildEpoch){state.buildActive=false;state.buildCompletedAt=Date.now();state.lastReason=`${league} ${date} queue ready`;state.lastLeagueDayCount=PROGRAM.length;}
            return;
          }
          const match=build.rows[build.index++],t0=performance.now();
          const items=mediaForMatch(match);
          const elapsed=performance.now()-t0;state.buildLastMatchMs=Math.round(elapsed*10)/10;state.buildMaxMatchMs=Math.max(state.buildMaxMatchMs,state.buildLastMatchMs);
          if(elapsed>32)console.warn('[SBB v5.4.0] slow score-date match projection yielded after one match',{league,date,ms:Math.round(elapsed),match:clean(match?.name||match?.title||match?.eventId||match?.id)});
          for(const item of items){
            const itemGame=gameKey(item);if(itemGame&&build.selectedGameKeys.has(itemGame))continue;
            const mediaKey=itemId(item);if(mediaKey&&build.seenMedia.has(mediaKey))continue;
            if(mediaKey)build.seenMedia.add(mediaKey);build.remainder.push(item);
          }
          state.buildProcessed=build.index;
          commitBuiltQueue(build,{final:false});
          if(build.index===1||build.index%BUILD_RENDER_EVERY===0)scheduleRender(build);
          setTimeout(pump,BUILD_YIELD_MS);
        };
        setTimeout(pump,BUILD_YIELD_MS);
      },0);
      return true;
    }catch(err){state.lastError=String(err?.message||err);state.buildActive=false;return false;}
  }

  function cancelLeagueDayBuild(reason='queue ownership changed'){
    state.buildEpoch++;state.buildActive=false;state.lastReason=reason;return true;
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
      if(typeof beginScorePlaybackSession!=='function'||beginScorePlaybackSession.__sbbLeagueDayV5317)return false;
      const original=beginScorePlaybackSession;
      const wrapped=function(...args){
        const result=original.apply(this,args);
        scheduleLeagueDayQueueExpansion((typeof userPlaybackSession!=='undefined')?userPlaybackSession:null);
        return result;
      };
      wrapped.__sbbLeagueDayV5317=true;wrapped.__sbbOriginal=original;
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
      cancelLeagueDayBuild('new score-ribbon selection');
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
  window.SBB_SCORE_INTERRUPT_QUEUE=Object.freeze({version:VERSION,active,entries,play,capture,clear,restoreQueue,expandLeagueDay:scheduleLeagueDayQueueExpansion,cancelLeagueDayBuild,leagueDayBuildSnapshot:()=>({active:state.buildActive,epoch:state.buildEpoch,processed:state.buildProcessed,total:state.buildTotal,maxMatchMs:state.buildMaxMatchMs,lastMatchMs:state.buildLastMatchMs,startedAt:state.buildStartedAt,completedAt:state.buildCompletedAt}),snapshot:()=>({version:VERSION,active:active(),captures:state.captures,resumes:state.resumes,projected:state.projected,leagueDayBuilds:state.leagueDayBuilds,lastLeagueDay:state.lastLeagueDay,lastLeagueDayCount:state.lastLeagueDayCount,lastReason:state.lastReason,lastError:state.lastError,buildActive:state.buildActive,buildProcessed:state.buildProcessed,buildTotal:state.buildTotal,buildMaxMatchMs:state.buildMaxMatchMs,queued:state.snapshot?.program?.length||0,resumeIndex:state.snapshot?resumeIndex((typeof userPlaybackSession!=='undefined'?userPlaybackSession:null),state.snapshot):-1})});
})();

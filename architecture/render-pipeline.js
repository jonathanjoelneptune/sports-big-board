/* Sports Big Board v4.7.6 — Ribbon Render Pipeline.
   Keeps render semantics synchronous for the first caller, suppresses only
   same-state duplicates inside one frame, and emits timing telemetry so long
   tasks can be attributed to ribbon rendering rather than guessed from totals.
*/
(() => {
  'use strict';
  if(window.SBB_RENDER_PIPELINE?.version==='4.7.6')return;

  const VERSION='4.7.6';
  const state={
    installed:false,calls:0,executed:0,coalesced:0,reentrant:0,
    lastKey:'',lastStartedAt:0,lastFinishedAt:0,lastDurationMs:0,
    totalDurationMs:0,maxDurationMs:0,samples:[],lastResult:undefined,
    currentReason:''
  };
  const now=()=>performance.now();
  const round=v=>Math.round(v*10)/10;

  function renderKey(){
    let date='',filter='';
    try{date=String(scoreBrowseDate||'');}catch(_){date=String(window.scoreBrowseDate||'');}
    try{filter=String(scoreRibbonLeagueFilter||'ALL');}catch(_){filter=String(window.scoreRibbonLeagueFilter||'ALL');}
    let rows='';
    try{
      const matches=typeof scoreMatchesForDate==='function'?scoreMatchesForDate(date):[];
      rows=Array.isArray(matches)?String(matches.length):'';
    }catch(_){}
    return `${date}|${filter}|${rows}`;
  }

  function emit(type,detail={}){
    try{
      window.dispatchEvent(new CustomEvent('sbb:render-pipeline',{
        detail:{type,at:Date.now(),...detail}
      }));
    }catch(_){}
  }

  function install(){
    if(typeof window.renderScoresFromMatchesCombined!=='function')return false;
    if(window.renderScoresFromMatchesCombined.__sbbRenderPipeline)return true;

    const original=window.renderScoresFromMatchesCombined;
    let inRender=false;

    function wrapped(animate=false){
      state.calls+=1;
      const started=now();
      const key=renderKey();
      const reason=String(window.__SBB_RENDER_REASON||state.currentReason||'unspecified');

      if(inRender){
        state.reentrant+=1;
        state.coalesced+=1;
        emit('coalesced',{key,reason,cause:'reentrant'});
        return state.lastResult;
      }

      // The v4.7 compatibility layers frequently request the same ribbon render
      // twice back-to-back after one Day State apply. Suppress only that immediate
      // same-state duplicate; later data changes remain free to render normally.
      if(!animate && key===state.lastKey && (started-state.lastFinishedAt)<24){
        state.coalesced+=1;
        emit('coalesced',{key,reason,cause:'same-frame'});
        return state.lastResult;
      }

      inRender=true;
      state.executed+=1;
      state.lastStartedAt=started;
      const beforeNodes=document.getElementById('scoreCells')?.childElementCount||0;
      try{
        state.lastResult=original(animate);
        return state.lastResult;
      }finally{
        const finished=now();
        const duration=round(finished-started);
        const afterNodes=document.getElementById('scoreCells')?.childElementCount||0;
        state.lastKey=key;
        state.lastFinishedAt=finished;
        state.lastDurationMs=duration;
        state.totalDurationMs=round(state.totalDurationMs+duration);
        state.maxDurationMs=Math.max(state.maxDurationMs,duration);
        state.samples.push({at:Date.now(),durationMs:duration,key,reason,beforeNodes,afterNodes});
        if(state.samples.length>250)state.samples.splice(0,state.samples.length-250);
        inRender=false;
        emit('render',{
          key,reason,durationMs:duration,beforeNodes,afterNodes,
          calls:state.calls,executed:state.executed,coalesced:state.coalesced
        });
      }
    }

    wrapped.__sbbRenderPipeline=true;
    wrapped.__sbbOriginal=original;
    window.renderScoresFromMatchesCombined=wrapped;
    state.installed=true;
    return true;
  }

  function withReason(reason,fn){
    const previous=window.__SBB_RENDER_REASON;
    window.__SBB_RENDER_REASON=String(reason||'unspecified');
    try{return fn();}
    finally{window.__SBB_RENDER_REASON=previous||'';}
  }

  function boot(){
    install();
    const timer=setInterval(()=>{if(install())clearInterval(timer);},250);
    setTimeout(()=>clearInterval(timer),5000);
  }

  window.SBB_RENDER_PIPELINE=Object.freeze({
    version:VERSION,
    install,
    withReason,
    snapshot:()=>({
      version:VERSION,
      installed:state.installed,
      calls:state.calls,
      executed:state.executed,
      coalesced:state.coalesced,
      reentrant:state.reentrant,
      lastDurationMs:state.lastDurationMs,
      totalDurationMs:state.totalDurationMs,
      maxDurationMs:state.maxDurationMs,
      samples:[...state.samples],
    })
  });

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();

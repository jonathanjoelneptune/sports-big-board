/* v3.0.9 SelectedEvent is the synchronization boundary between playback and future Game Center UI. */
(() => {
  let current=null;
  let revision=0;
  const listeners=new Set();
  function snapshot(){ return current?{...current}:null; }
  function select(eventLike,meta={}){
    if(!eventLike) return clear(meta);
    const core=window.SBB_CORE;
    const canonical=core?.event?core.event(eventLike,eventLike?.competitionId||eventLike?.__sbbLeague||eventLike?.league):{...eventLike};
    const identity=window.SBB_EVENT_IDENTITY?.key?.(canonical)||canonical.eventId||'';
    current={...canonical,canonicalEventKey:identity,selectedAt:Date.now(),selectionReason:String(meta.reason||''),selectionSource:String(meta.source||'')};
    revision++;
    for(const fn of listeners){ try{fn(snapshot(),{revision,action:'select',...meta});}catch(e){console.warn('[SBB SelectedEvent listener]',e);} }
    return snapshot();
  }
  function clear(meta={}){
    if(!current) return null;
    current=null; revision++;
    for(const fn of listeners){ try{fn(null,{revision,action:'clear',...meta});}catch(e){} }
    return null;
  }
  function subscribe(fn,{emitCurrent=false}={}){
    if(typeof fn!=='function') return ()=>{};
    listeners.add(fn); if(emitCurrent) fn(snapshot(),{revision,action:'snapshot'});
    return ()=>listeners.delete(fn);
  }
  window.SBB_SELECTED_EVENT=Object.freeze({version:'1.0',select,clear,get:snapshot,subscribe,get revision(){return revision;}});
})();

/* Sports Big Board v4.7.9 — Render-Local Card Model Cache.
   Score-card construction repeatedly asks the same pure helper questions for one
   match. Cache those answers only for the lifetime of one ribbon render so media
   freshness semantics stay unchanged while duplicate calculation disappears.
*/
(() => {
  'use strict';
  if(window.SBB_CARD_BUILD_CACHE?.version==='4.7.9')return;

  const VERSION='4.7.9';
  const TARGETS=[
    'scoreCardAvailability',
    'scoreCardPlayableItems',
    'externalMediaItemsForGame',
    'scoreFromMatch',
    'scoreGameLookupKeys',
    'scoreEventDate',
  ];
  const state={
    active:false,renderId:0,hits:0,misses:0,helperMs:0,
    installed:[],current:null,last:null,totalHits:0,totalMisses:0
  };
  const originals=new Map();
  let caches=new Map();

  const now=()=>performance.now();
  const round=v=>Math.round(v*10)/10;

  function freshCaches(){
    caches=new Map(TARGETS.map(name=>[name,new WeakMap()]));
  }

  function wrap(name){
    const original=window[name];
    if(typeof original!=='function')return false;
    if(original.__sbbCardBuildCache)return true;
    originals.set(name,original);

    const wrapped=function(...args){
      if(!state.active)return original.apply(this,args);
      const key=args[0];
      if(!key || (typeof key!=='object' && typeof key!=='function')){
        const started=now();
        try{return original.apply(this,args);}
        finally{state.helperMs+=now()-started;}
      }

      const cache=caches.get(name);
      if(cache?.has(key)){
        state.hits+=1;
        state.totalHits+=1;
        return cache.get(key);
      }

      state.misses+=1;
      state.totalMisses+=1;
      const started=now();
      const result=original.apply(this,args);
      state.helperMs+=now()-started;
      cache?.set(key,result);
      return result;
    };
    wrapped.__sbbCardBuildCache=true;
    wrapped.__sbbOriginal=original;
    window[name]=wrapped;
    state.installed.push(name);
    return true;
  }

  function install(){
    for(const name of TARGETS)wrap(name);
    return state.installed.length;
  }

  function beginRender(meta={}){
    install();
    state.renderId+=1;
    state.active=true;
    state.hits=0;
    state.misses=0;
    state.helperMs=0;
    freshCaches();
    state.current={
      renderId:state.renderId,
      generation:Number(meta.generation||0),
      reason:String(meta.reason||''),
      startedAt:now(),
    };
    return state.renderId;
  }

  function endRender(token){
    if(!state.active)return state.last;
    if(token && Number(token)!==state.renderId)return state.last;
    const current=state.current||{};
    const report={
      renderId:state.renderId,
      generation:Number(current.generation||0),
      reason:String(current.reason||''),
      hits:state.hits,
      misses:state.misses,
      helperMs:round(state.helperMs),
      elapsedMs:round(now()-Number(current.startedAt||now())),
      installed:[...state.installed],
    };
    state.last=report;
    state.active=false;
    state.current=null;
    freshCaches();
    try{
      window.dispatchEvent(new CustomEvent('sbb:card-build-cache',{
        detail:{...report,at:Date.now()}
      }));
    }catch(_){}
    return report;
  }

  window.SBB_CARD_BUILD_CACHE=Object.freeze({
    version:VERSION,
    install,
    beginRender,
    endRender,
    snapshot:()=>({
      version:VERSION,
      active:state.active,
      renderId:state.renderId,
      installed:[...state.installed],
      totalHits:state.totalHits,
      totalMisses:state.totalMisses,
      last:state.last?{...state.last}:null,
    })
  });

  install();
})();

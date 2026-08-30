/* Sports Big Board v4.7.14 — Render-Local Card Model Cache.
   Score-card construction repeatedly asks the same pure helper questions for one
   match. Cache those answers only for the lifetime of one ribbon render so media
   freshness semantics stay unchanged while duplicate calculation disappears.
*/
(() => {
  'use strict';
  if(window.SBB_CARD_BUILD_CACHE?.version==='4.7.14')return;

  const VERSION='4.7.14';
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
    installed:[],current:null,last:null,totalHits:0,totalMisses:0,
    helperBreakdown:{}
  };
  const originals=new Map();
  let caches=new Map();
  freshBreakdown();

  const now=()=>performance.now();
  const round=v=>Math.round(v*10)/10;
  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  function stableObjectKey(value){
    if(!value||(typeof value!=='object'&&typeof value!=='function'))return '';
    const league=upper(value.competitionId||value.__sbbLeague||value.league||value.sport||'SPORTS');
    const date=clean(value.__sbbDate||value.gameDate||value.date||value.scheduledAt).slice(0,10);
    const id=[value.scoreEventId,value.espnEventId,value.gameCenterEventId,value.matchId,value.gamePk,value.eventId,value.id]
      .find(x=>x!==undefined&&x!==null&&clean(x)!=='');
    if(id!==undefined)return `${league}|${date}|ID:${clean(id)}`;
    const teamName=team=>upper(team?.name||team?.displayName||team?.shortDisplayName||team?.abbreviation||team||'');
    const away=teamName(value.awayTeam||value.away||value.awayName);
    const home=teamName(value.homeTeam||value.home||value.homeName);
    return away||home?`${league}|${date}|PAIR:${away}|${home}`:'';
  }

  function freshCaches(){
    // Day State frequently clones the same logical match while composing one
    // render. Keep object identity as a fallback, but prefer a render-local stable
    // event key so those clones share the expensive helper result.
    caches=new Map(TARGETS.map(name=>[name,{stable:new Map(),object:new WeakMap()}]));
  }
  function freshBreakdown(){
    state.helperBreakdown=Object.fromEntries(
      TARGETS.map(name=>[name,{hits:0,misses:0,ms:0}])
    );
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
      const stable=stableObjectKey(key);
      const store=stable?cache?.stable:cache?.object;
      const cacheKey=stable||key;
      const helper=state.helperBreakdown[name]||(state.helperBreakdown[name]={hits:0,misses:0,ms:0});
      if(store?.has(cacheKey)){
        state.hits+=1;
        state.totalHits+=1;
        helper.hits+=1;
        return store.get(cacheKey);
      }

      state.misses+=1;
      state.totalMisses+=1;
      helper.misses+=1;
      const started=now();
      const result=original.apply(this,args);
      const elapsed=now()-started;
      state.helperMs+=elapsed;
      helper.ms+=elapsed;
      store?.set(cacheKey,result);
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
    freshBreakdown();
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
      helpers:Object.fromEntries(Object.entries(state.helperBreakdown).map(
        ([name,row])=>[name,{
          hits:Number(row.hits||0),
          misses:Number(row.misses||0),
          ms:round(Number(row.ms||0))
        }]
      )),
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

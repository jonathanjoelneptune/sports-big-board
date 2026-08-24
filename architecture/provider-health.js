/* Sports Big Board v4.1.13 — provider health / adaptive source preference.
   Provider health is deliberately separate from media existence. A provider can
   be temporarily unhealthy without invalidating an event's discovered media. */
(() => {
  const states=new Map();
  const listeners=new Set();
  const clean=v=>String(v??'').trim().toUpperCase()||'UNKNOWN';
  const now=()=>Date.now();
  function record(provider,patch={}){
    const key=clean(provider),prev=states.get(key)||{provider:key,successes:0,failures:0,consecutiveFailures:0,lastSuccessAt:0,lastFailureAt:0,cooldownUntil:0,lastReason:''};
    const next={...prev,...patch,provider:key}; states.set(key,next);
    for(const fn of listeners){try{fn({...next});}catch(_){}}
    return next;
  }
  function success(provider){const s=record(provider);return record(provider,{successes:s.successes+1,consecutiveFailures:0,lastSuccessAt:now(),cooldownUntil:0,lastReason:''});}
  function failure(provider,reason='',{cooldownMs=0}={}){
    const s=record(provider),n=s.consecutiveFailures+1;
    const adaptive=cooldownMs||Math.min(5*60_000,Math.max(5_000,2**Math.min(n,6)*2_000));
    return record(provider,{failures:s.failures+1,consecutiveFailures:n,lastFailureAt:now(),cooldownUntil:now()+adaptive,lastReason:String(reason||'')});
  }
  function rateLimited(provider,retryMs=120_000,reason='rate limited'){return failure(provider,reason,{cooldownMs:retryMs});}
  function state(provider){return {...(states.get(clean(provider))||record(provider))};}
  function eligible(provider){return state(provider).cooldownUntil<=now();}
  function score(provider){
    const s=state(provider);let value=0;
    if(!eligible(provider)) value-=45;
    value+=Math.min(12,s.successes*0.6);
    value-=Math.min(30,s.consecutiveFailures*8);
    if(s.lastSuccessAt&&now()-s.lastSuccessAt<10*60_000)value+=8;
    return value;
  }
  function subscribe(fn){if(typeof fn!=='function')return()=>{};listeners.add(fn);return()=>listeners.delete(fn);}
  function reset(){states.clear();}
  window.SBB_PROVIDER_HEALTH=Object.freeze({version:'1.0',success,failure,rateLimited,state,eligible,score,subscribe,reset});
})();

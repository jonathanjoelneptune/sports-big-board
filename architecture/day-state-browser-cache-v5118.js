/* Sports Big Board v5.1.18 — Day State browser stale-while-revalidate.
   Last-known-good non-empty Day State is persisted for quick repeat browsing.
   A slow/failed rich projection falls back to canonical scores instead of painting
   a false zero-game day. No discovery/provider work runs in this module. */
(() => {
  'use strict';
  const base=window.SBB_DAY_STATE;
  if(!base||base.__sbbV5118)return;
  const KEY='sbb.dayStateLkg.v5118',MAX_DAYS=16;
  const mem=new Map(),inflight=new Map();
  let disk={days:{}};try{const x=JSON.parse(localStorage.getItem(KEY)||'{}');if(x?.days)disk=x;}catch(_){}
  const apiPath=p=>window.SBB_API?.url?window.SBB_API.url(p):p;
  const count=p=>Number(p?.scoreGameCount??p?.summary?.games??Object.values(p?.scoreRowsByLeague||{}).reduce((n,a)=>n+(a?.length||0),0))||0;
  function persist(date,p){
    if(!p||count(p)<=0)return false;
    const compact={...p};delete compact.repository;delete compact.discoveryState;
    disk.days[date]={at:Date.now(),payload:compact};
    const keys=Object.keys(disk.days).sort((a,b)=>(disk.days[b]?.at||0)-(disk.days[a]?.at||0));
    for(const k of keys.slice(MAX_DAYS))delete disk.days[k];
    try{localStorage.setItem(KEY,JSON.stringify(disk));}catch(_){}
    return true;
  }
  function cached(date){return mem.get(date)||disk.days?.[date]?.payload||null;}
  function apply(date,p,{render=true}={}){
    if(!p||count(p)<=0)return false;
    for(const [lg,rows] of Object.entries(p.scoreRowsByLeague||{})){
      if(String(lg).toUpperCase()==='CFB'||!Array.isArray(rows))continue;
      window.SBB_SCORE_DATE?.setMatches?.(date,lg,rows,{source:'day-state-lkg-v5118',authoritative:true});
    }
    try{base.ingestCompactCatalogPlans?.(date,p.eventPlans||{});}catch(_){}
    mem.set(date,p);persist(date,p);
    if(render)try{window.renderScoresFromMatchesCombined?.(false);}catch(_){}
    return true;
  }
  async function fetchJson(path,timeoutMs){
    const c=new AbortController(),timer=setTimeout(()=>c.abort(),timeoutMs);
    try{const r=await fetch(apiPath(path),{cache:'no-store',signal:c.signal});const p=await r.json().catch(()=>({}));if(!r.ok)throw new Error(`${r.status}`);return p;}finally{clearTimeout(timer);}
  }
  async function fast(date){
    try{const p=await fetchJson(`/api/day-state/fast?date=${encodeURIComponent(date)}`,1800);if(count(p)>0){apply(date,p);return p;}}catch(_){}
    return null;
  }
  async function load(date,opts={}){
    date=String(date||'').slice(0,10);if(!/^\d{4}-\d{2}-\d{2}$/.test(date))return null;
    const old=cached(date);if(old&&count(old)>0)apply(date,old,{render:true});
    const key=`${date}:${opts.force?'1':'0'}`;if(inflight.has(key))return inflight.get(key);
    const job=(async()=>{
      // On a never-seen date, launch the score-only fallback immediately in
      // parallel with the rich Day State read. The first non-empty answer paints.
      const rescuePromise=(!old||count(old)<=0)?fast(date):Promise.resolve(null);
      const richPromise=base.load(date,{...opts,timeoutMs:Math.max(2200,Number(opts.timeoutMs)||0)})
        .then(p=>{if(p&&count(p)>0){mem.set(date,p);persist(date,p);return p;}return null;}).catch(()=>null);
      const first=await Promise.race([richPromise,rescuePromise]);
      if(first&&count(first)>0){
        // Rich work is allowed to finish in the background and upgrade media plans.
        richPromise.then(p=>{if(p&&count(p)>0){mem.set(date,p);persist(date,p);}}).catch(()=>{});
        return first;
      }
      const [rich,rescue]=await Promise.all([richPromise,rescuePromise]);
      if(rich&&count(rich)>0)return rich;if(rescue&&count(rescue)>0)return rescue;if(old&&count(old)>0)return old;
      setTimeout(()=>base.load(date,{force:false,timeoutMs:4500}).then(p=>{if(p&&count(p)>0){mem.set(date,p);persist(date,p);}}).catch(()=>{}),900);
      return null;
    })().finally(()=>inflight.delete(key));
    inflight.set(key,job);return job;
  }
  function restore(date){const p=cached(String(date||'').slice(0,10));return p&&count(p)>0?apply(String(date).slice(0,10),p):false;}
  window.SBB_DAY_STATE=Object.freeze({...base,version:'4.7.14-v5118-lkg',load,restoreLastGood:restore,__sbbV5118:true,
    cacheSnapshot:()=>({memory:mem.size,disk:Object.keys(disk.days||{}).length,inflight:inflight.size})});
  // Day browsing function is defined in app.js before this module loads. Paint LKG
  // immediately when the user changes dates, then let the existing load continue.
  const original=window.setScoreBrowseDate;
  if(typeof original==='function'&&!original.__sbbV5118){
    const wrapped=async function(value,opts={}){const date=String(value||'').slice(0,10);restore(date);const rescue=load(date,{force:false}).catch(()=>null);const result=await original(value,opts);await rescue;restore(date);return result;};
    wrapped.__sbbV5118=true;window.setScoreBrowseDate=wrapped;
  }
})();

/* Sports Big Board v4.7.4 — Request Broker.
   One transport request per identical GET. Short TTL read reuse, date-generation
   cancellation for superseded interactive work, and broker-native telemetry.
*/
(() => {
  'use strict';
  if (window.SBB_REQUEST_BROKER?.version === '4.7.4') return;

  const VERSION='4.7.4';
  const transportFetch=window.fetch.bind(window);
  const inflight=new Map();
  const cache=new Map();
  const stats={
    callers:0,network:0,coalesced:0,cacheHits:0,errors:0,
    supersededAborts:0,activeDate:'',generation:0
  };

  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const now=()=>performance.now();

  function urlOf(input){
    try{
      if(input instanceof Request)return new URL(input.url,location.href);
      if(input instanceof URL)return new URL(input.toString(),location.href);
      return new URL(String(input||''),location.href);
    }catch(_){return null;}
  }

  function normalizeKey(input,init={}){
    const u=urlOf(input);
    if(!u)return '';
    for(const k of ['_','t','ts','cacheBust','cachebust'])u.searchParams.delete(k);
    const pairs=[...u.searchParams.entries()].sort(([ak,av],[bk,bv])=>ak.localeCompare(bk)||av.localeCompare(bv));
    u.search='';
    for(const [k,v] of pairs)u.searchParams.append(k,v);
    const method=upper(init?.method || input?.method || 'GET') || 'GET';
    return `${method} ${u.origin}${u.pathname}${u.search}`;
  }

  function pathOf(input){
    return urlOf(input)?.pathname||'';
  }

  function dateOf(input){
    try{return clean(urlOf(input)?.searchParams?.get('date')).slice(0,10);}
    catch(_){return '';}
  }

  function excluded(path,init={}){
    if(!path.startsWith('/api/'))return true;
    if(upper(init?.method||'GET')!=='GET')return true;
    const headers=new Headers(init?.headers||{});
    if(headers.has('Range'))return true;
    return (
      path.startsWith('/api/soundtrack/') ||
      path.includes('/export') ||
      path.includes('/download')
    );
  }

  function ttlFor(path){
    if(path==='/api/status')return 750;
    if(path==='/api/competition-registry')return 1800;
    if(path==='/api/competition-builder/catalog')return 1800;
    if(path==='/api/day-state')return 900;
    if(path==='/api/day-state/status')return 1200;
    if(path==='/api/history/ribbon')return 1400;
    if(path==='/api/history/roundups')return 3500;
    if(path==='/api/history/discovery')return 1400;
    return 0;
  }

  function isInteractiveDatePath(path){
    return (
      path==='/api/day-state' ||
      path==='/api/history/ribbon' ||
      path==='/api/history/roundups' ||
      path==='/api/history/discovery'
    );
  }

  function emit(type,detail={}){
    try{
      window.dispatchEvent(new CustomEvent('sbb:request-broker',{
        detail:{type,at:Date.now(),...detail}
      }));
    }catch(_){}
  }

  function cachedClone(key){
    const row=cache.get(key);
    if(!row)return null;
    if(row.expiresAt<=now()){
      cache.delete(key);
      return null;
    }
    stats.cacheHits+=1;
    emit('cache-hit',{key,path:row.path,date:row.date,ageMs:Math.round(now()-row.storedAt)});
    try{return row.response.clone();}
    catch(_){cache.delete(key);return null;}
  }

  function consume(entry,signal){
    entry.consumers+=1;
    return new Promise((resolve,reject)=>{
      let done=false;
      const release=()=>{
        if(done)return;
        done=true;
        entry.consumers=Math.max(0,entry.consumers-1);
        signal?.removeEventListener?.('abort',onAbort);
      };
      const onAbort=()=>{
        release();
        if(!entry.settled && entry.interactive && entry.consumers===0){
          try{entry.controller.abort('no-active-consumers');}catch(_){}
        }
        reject(new DOMException('Aborted','AbortError'));
      };
      if(signal?.aborted)return onAbort();
      signal?.addEventListener?.('abort',onAbort,{once:true});
      entry.promise.then(response=>{
        if(done)return;
        release();
        try{resolve(response.clone());}
        catch(err){reject(err);}
      },err=>{
        if(done)return;
        release();
        reject(err);
      });
    });
  }

  function beginDate(date,generation){
    date=clean(date).slice(0,10);
    stats.activeDate=date;
    stats.generation=Number(generation||stats.generation+1);

    for(const entry of inflight.values()){
      if(!entry.interactive || !entry.date || entry.date===date)continue;
      stats.supersededAborts+=1;
      emit('superseded-abort',{
        id:entry.id,key:entry.key,path:entry.path,date:entry.date,
        nextDate:date,generation:stats.generation
      });
      try{entry.controller.abort('superseded-date');}catch(_){}
    }
    return stats.generation;
  }

  window.fetch=function brokeredFetch(input,init={}){
    const method=upper(init?.method || input?.method || 'GET') || 'GET';
    const path=pathOf(input);
    if(method!=='GET' || excluded(path,{...init,method})){
      return transportFetch(input,init);
    }

    stats.callers+=1;
    const key=normalizeKey(input,{...init,method});
    if(!key)return transportFetch(input,init);

    const cached=cachedClone(key);
    if(cached)return Promise.resolve(cached);

    const existing=inflight.get(key);
    if(existing){
      stats.coalesced+=1;
      existing.coalesced+=1;
      emit('coalesced',{
        id:existing.id,key,path:existing.path,date:existing.date,
        generation:existing.generation,coalesced:existing.coalesced
      });
      return consume(existing,init?.signal);
    }

    const controller=new AbortController();
    const date=dateOf(input);
    const interactive=!!(
      stats.activeDate &&
      date &&
      date===stats.activeDate &&
      isInteractiveDatePath(path)
    );
    const id=`req-${Date.now()}-${Math.random().toString(36).slice(2,8)}`;
    const started=now();
    const generation=stats.generation;
    const transportInit={...init,signal:controller.signal};
    const entry={
      id,key,path,date,interactive,generation,controller,
      started,settled:false,consumers:0,coalesced:0,promise:null
    };

    stats.network+=1;
    emit('network-start',{id,key,path,date,interactive,generation});

    entry.promise=transportFetch(input,transportInit)
      .then(response=>{
        entry.settled=true;
        const durationMs=Math.round((now()-started)*10)/10;
        const ttl=ttlFor(path);

        if(response.ok && ttl>0){
          try{
            cache.set(key,{
              response:response.clone(),path,date,
              storedAt:now(),expiresAt:now()+ttl
            });
          }catch(_){}
        }

        emit('network-finish',{
          id,key,path,date,interactive,generation,
          status:response.status,ok:response.ok||response.status===202,
          durationMs,coalesced:entry.coalesced
        });

        // X-SBB-Day-State is not necessarily CORS-exposed on older backend builds.
        // Read cache state from a cloned JSON body instead, without delaying consumers.
        if(path==='/api/day-state'){
          try{
            response.clone().json().then(payload=>{
              const cacheState=clean(payload?.cache?.state || (payload?.pending?'COLD_WARMING':''));
              emit('metadata',{id,key,path,date,cacheState});
            }).catch(()=>{});
          }catch(_){}
        }
        return response;
      })
      .catch(err=>{
        entry.settled=true;
        const aborted=err?.name==='AbortError' || controller.signal.aborted;
        const reason=clean(controller.signal.reason || err?.message || err);
        if(!aborted)stats.errors+=1;
        emit('network-error',{
          id,key,path,date,interactive,generation,
          durationMs:Math.round((now()-started)*10)/10,
          aborted,reason
        });
        throw err;
      })
      .finally(()=>inflight.delete(key));

    inflight.set(key,entry);
    return consume(entry,init?.signal);
  };

  window.SBB_REQUEST_BROKER=Object.freeze({
    version:VERSION,
    beginDate,
    clearCache:()=>cache.clear(),
    snapshot:()=>({
      version:VERSION,
      ...stats,
      inflight:inflight.size,
      cached:cache.size,
      active:[...inflight.values()].map(x=>({
        id:x.id,path:x.path,date:x.date,interactive:x.interactive,
        generation:x.generation,consumers:x.consumers,coalesced:x.coalesced,
        ageMs:Math.round(now()-x.started)
      }))
    })
  });
})();

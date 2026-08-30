/* Sports Big Board v4.7.13 — Request Broker + Enrichment Firewall.
   One transport request per identical GET. Shared-state TTL reuse, date-generation
   cancellation, and an explicit first-paint firewall keep expensive enrichment
   from waking up while the user is simply changing ribbon dates.
*/
(() => {
  'use strict';
  if (window.SBB_REQUEST_BROKER?.version === '4.7.13') return;

  const VERSION='4.7.13';
  const QUIET_MS=8000;
  const transportFetch=window.fetch.bind(window);
  const inflight=new Map();
  const deferred=new Map();
  const cache=new Map();
  const stats={
    callers:0,network:0,coalesced:0,cacheHits:0,errors:0,
    supersededAborts:0,deferred:0,deferredAborts:0,deferredReleases:0,
    activeDate:'',generation:0,quietUntil:0
  };

  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const now=()=>performance.now();
  const today=()=>{
    const d=new Date();
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  };

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

  function pathOf(input){ return urlOf(input)?.pathname||''; }

  function dateOf(input){
    try{
      const u=urlOf(input);
      return clean(
        u?.searchParams?.get('date') ||
        u?.searchParams?.get('day') ||
        u?.searchParams?.get('startDate') ||
        u?.searchParams?.get('from')
      ).slice(0,10);
    }catch(_){return '';}
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

  function ttlFor(path,input){
    if(path==='/api/status')return 2000;
    if(path==='/api/competition-registry')return 30000;
    if(path==='/api/competition-builder/catalog')return 30000;
    if(path==='/api/editorial/key-info')return 60000;
    if(path==='/api/day-state')return 1600;
    if(path==='/api/day-state/thin')return 0;
    if(path==='/api/day-state/status')return 5000;
    if(path==='/api/history/ribbon')return 3000;
    if(path==='/api/history/roundups')return 30000;
    if(path==='/api/history/discovery')return 10000;
    if(path==='/api/competition-builder/schedule'){
      const d=dateOf(input);return d&&d<today()?60000:12000;
    }
    if(path==='/api/competition-builder/media')return 60000;
    return 0;
  }

  function requestClass(path,input){
    if(
      path==='/api/day-state' ||
      path==='/api/history/ribbon' ||
      path==='/api/status'
    ) return 'FIRST_PAINT';

    if(
      path==='/api/competition-registry' ||
      path==='/api/competition-builder/catalog' ||
      path==='/api/editorial/key-info' ||
      path==='/api/day-state/thin'
    ) return 'SHARED_STATE';

    if(
      path==='/api/competition-builder/media' ||
      path==='/api/rapid-team-videos' ||
      /\/api\/events\/[^/]+\/[^/]+\/game-center$/.test(path)
    ) return 'ON_DEMAND';

    if(
      path==='/api/history/discovery' ||
      path==='/api/history/roundups' ||
      path==='/api/competition-builder/schedule'
    ) return 'IDLE_ENRICHMENT';

    if(path==='/api/soccer/schedule'){
      const d=dateOf(input);
      return d && d<today() ? 'IDLE_ENRICHMENT' : 'LIVE_PROVIDER';
    }

    return 'NORMAL';
  }

  function operatorActive(){
    try{
      const audit=document.getElementById('historyAuditModal');
      if(audit && !audit.classList.contains('hidden'))return true;
      const builder=document.getElementById('sbbBuilderModal');
      if(builder && !builder.classList.contains('hidden'))return true;
    }catch(_){}
    return false;
  }

  function recentSelectedEvent(){
    try{
      const selected=window.SBB_SELECTED_EVENT?.get?.();
      return !!(selected?.selectedAt && Date.now()-Number(selected.selectedAt)<4000);
    }catch(_){return false;}
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

  function abortDeferred(reason='superseded-date'){
    for(const [key,row] of [...deferred.entries()]){
      if(row.generation===stats.generation && row.date===stats.activeDate)continue;
      clearTimeout(row.timer);
      deferred.delete(key);
      stats.deferredAborts+=1;
      emit('deferred-abort',{
        key,rowClass:row.rowClass,path:row.path,date:row.date,
        generation:row.generation,reason
      });
      row.reject(new DOMException('Deferred enrichment superseded','AbortError'));
    }
  }

  function beginDate(date,generation){
    date=clean(date).slice(0,10);
    stats.activeDate=date;
    stats.generation=Number(generation||stats.generation+1);
    stats.quietUntil=now()+QUIET_MS;

    for(const entry of inflight.values()){
      if(!entry.interactive || !entry.date || entry.date===date)continue;
      stats.supersededAborts+=1;
      emit('superseded-abort',{
        id:entry.id,key:entry.key,path:entry.path,date:entry.date,
        nextDate:date,generation:stats.generation
      });
      try{entry.controller.abort('superseded-date');}catch(_){}
    }
    abortDeferred('superseded-date');
    return stats.generation;
  }

  function shouldDefer(path,input,init,rowClass){
    if(init?.__sbbBrokerRelease)return false;
    if(!stats.activeDate || now()>=stats.quietUntil)return false;
    if(operatorActive())return false;
    if(clean(init?.sbbRequestClass).toUpperCase()==='ON_DEMAND')return false;
    if(rowClass==='ON_DEMAND' && recentSelectedEvent())return false;
    if(!['ON_DEMAND','IDLE_ENRICHMENT'].includes(rowClass))return false;

    const d=dateOf(input);
    if(d && d!==stats.activeDate)return false;
    return true;
  }

  function deferFetch(input,init,key,path,rowClass){
    const existing=deferred.get(key);
    if(existing){
      stats.coalesced+=1;
      emit('coalesced',{key,path,date:existing.date,generation:existing.generation,deferred:true});
      return existing.promise.then(r=>r.clone());
    }

    const generation=stats.generation;
    const date=dateOf(input)||stats.activeDate;
    const waitMs=Math.max(50,stats.quietUntil-now());
    stats.deferred+=1;
    emit('deferred',{key,path,date,generation,rowClass,waitMs:Math.round(waitMs)});

    let resolve,reject;
    const promise=new Promise((res,rej)=>{resolve=res;reject=rej;});
    const row={key,path,date,generation,rowClass,promise,resolve,reject,timer:null};
    row.timer=setTimeout(async()=>{
      deferred.delete(key);
      if(generation!==stats.generation || date!==stats.activeDate){
        stats.deferredAborts+=1;
        emit('deferred-abort',{key,path,date,generation,rowClass,reason:'generation-changed'});
        reject(new DOMException('Deferred enrichment superseded','AbortError'));
        return;
      }
      stats.deferredReleases+=1;
      emit('deferred-release',{key,path,date,generation,rowClass});
      try{
        const response=await brokeredFetch(input,{...init,__sbbBrokerRelease:true});
        resolve(response);
      }catch(err){reject(err);}
    },waitMs);
    deferred.set(key,row);
    return promise;
  }

  function brokeredFetch(input,init={}){
    const method=upper(init?.method || input?.method || 'GET') || 'GET';
    const path=pathOf(input);
    if(method!=='GET' || excluded(path,{...init,method})){
      const transportInit={...init};
      delete transportInit.__sbbBrokerRelease;
      delete transportInit.sbbRequestClass;
      return transportFetch(input,transportInit);
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

    const rowClass=requestClass(path,input);
    if(shouldDefer(path,input,init,rowClass)){
      return deferFetch(input,init,key,path,rowClass);
    }

    const controller=new AbortController();
    const requestDate=dateOf(input);
    const boundDate=requestDate || (
      ['ON_DEMAND','IDLE_ENRICHMENT'].includes(rowClass) ? stats.activeDate : ''
    );
    const interactive=!!(
      stats.activeDate &&
      boundDate &&
      boundDate===stats.activeDate &&
      ['FIRST_PAINT','ON_DEMAND','IDLE_ENRICHMENT'].includes(rowClass)
    );
    const id=`req-${Date.now()}-${Math.random().toString(36).slice(2,8)}`;
    const started=now();
    const generation=stats.generation;
    // Attribute the request to the efficiency run that existed when transport
    // STARTED. A request that began before an AUTO test may finish during it, but
    // it must never contaminate that run's API p95/error statistics.
    const runId=clean(window.__SBB_EFFICIENCY_RUN_ID||'');
    const transportInit={...init,signal:controller.signal};
    delete transportInit.__sbbBrokerRelease;
    delete transportInit.sbbRequestClass;

    const entry={
      id,key,path,date:boundDate,rowClass,interactive,generation,runId,controller,
      started,settled:false,consumers:0,coalesced:0,promise:null
    };

    stats.network+=1;
    emit('network-start',{id,key,path,date:boundDate,rowClass,interactive,generation,runId});

    entry.promise=transportFetch(input,transportInit)
      .then(response=>{
        entry.settled=true;
        const durationMs=Math.round((now()-started)*10)/10;
        const ttl=ttlFor(path,input);

        if((response.ok||response.status===202) && ttl>0){
          try{
            cache.set(key,{
              response:response.clone(),path,date:boundDate,
              storedAt:now(),expiresAt:now()+ttl
            });
          }catch(_){}
        }

        emit('network-finish',{
          id,key,path,date:boundDate,rowClass,interactive,generation,runId,
          status:response.status,ok:response.ok||response.status===202,
          durationMs,coalesced:entry.coalesced
        });

        if(path==='/api/day-state'){
          try{
            response.clone().json().then(payload=>{
              const cacheState=clean(payload?.cache?.state || (payload?.pending?'COLD_WARMING':''));
              emit('metadata',{id,key,path,date:boundDate,cacheState,runId});
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
          id,key,path,date:boundDate,rowClass,interactive,generation,runId,
          durationMs:Math.round((now()-started)*10)/10,
          aborted,reason
        });
        throw err;
      })
      .finally(()=>inflight.delete(key));

    inflight.set(key,entry);
    return consume(entry,init?.signal);
  }

  window.fetch=brokeredFetch;

  window.SBB_REQUEST_BROKER=Object.freeze({
    version:VERSION,
    beginDate,
    clearCache:()=>cache.clear(),
    snapshot:()=>({
      version:VERSION,
      ...stats,
      inflight:inflight.size,
      deferredCount:deferred.size,
      cached:cache.size,
      active:[...inflight.values()].map(x=>({
        id:x.id,path:x.path,date:x.date,rowClass:x.rowClass,interactive:x.interactive,
        generation:x.generation,runId:x.runId,consumers:x.consumers,coalesced:x.coalesced,
        ageMs:Math.round(now()-x.started)
      })),
      deferred:[...deferred.values()].map(x=>({
        path:x.path,date:x.date,rowClass:x.rowClass,generation:x.generation
      }))
    })
  });
})();

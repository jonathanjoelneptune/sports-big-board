/* Sports Big Board v4.4.0 — cross-sport playback readiness + device reliability.
   Content identity belongs to events/competitions; this module only answers whether
   a media transport is healthy enough to put on air. It is intentionally agnostic to
   MLB/NFL/NBA/NHL/EPL/MLS and future competitions. */
(() => {
  'use strict';
  if(window.SBB_PLAYBACK_READINESS) return;

  const STORAGE_KEY='sbb.playback-readiness.v1';
  const MAX_ASSETS=500;
  const records=new Map();
  const listeners=new Set();
  const recentFailures=[];
  let persistenceTimer=null;

  const clean=(v,n=1600)=>String(v??'').trim().slice(0,n);
  const clamp=(n,lo=0,hi=100)=>Math.max(lo,Math.min(hi,Number(n)||0));
  const now=()=>Date.now();
  const clone=v=>{try{return JSON.parse(JSON.stringify(v));}catch(_){return null;}};
  const keyOf=asset=>{
    if(!asset) return '';
    if(typeof asset==='string') return clean(asset,1800);
    return clean(window.SBB_PLAYBACK_TRANSPORTS?.playbackKey?.(asset)||asset.mediaKey||asset.clipKey||asset.assetKey||asset.youtubeId||asset.mediaUrl||asset.externalUrl,1800);
  };
  const descriptor=asset=>({
    mediaKey:keyOf(asset),clipKey:keyOf(asset),
    eventKey:clean(asset?.canonicalEventKey||asset?.eventKey||''),
    league:clean(asset?.competitionId||asset?.league||'SPORTS',80).toUpperCase(),
    competitionId:clean(asset?.competitionId||asset?.league||'SPORTS',80).toUpperCase(),
    provider:clean(asset?.provider||asset?.sourceType||asset?.source||asset?.sourceLabel||'UNKNOWN',120).toUpperCase(),
    transport:clean(asset?.transport||window.SBB_PLAYBACK_TRANSPORTS?.transportForAsset?.(asset)||'',120).toUpperCase(),
    sourceUrl:clean(asset?.mediaUrl||asset?.sourceUrl||asset?.youtubeId||'',2000),
    sourceExternalUrl:clean(asset?.externalUrl||asset?.sourceExternalUrl||'',2000),
    title:clean(asset?.title||'',500)
  });

  function blank(key,asset=null){
    const d=descriptor(asset||key);
    return {mediaKey:key,competitionId:d.competitionId||'',provider:d.provider||'',transport:d.transport||'',
      state:'DISCOVERED',score:80,selections:0,firstFrames:0,hotReadyCount:0,stalls:0,failures:0,warmFailures:0,
      recoveredFailovers:0,consecutiveFailures:0,startupSamples:[],firstSeenAt:now(),lastSeenAt:now(),lastSuccessAt:0,
      lastFailureAt:0,quarantinedUntil:0,lastError:'',lastHotReadyAt:0};
  }
  function derive(rec,t=now()){
    if(Number(rec.quarantinedUntil||0)>t) return 'QUARANTINED';
    const score=Number(rec.score||0), consecutive=Number(rec.consecutiveFailures||0);
    if(consecutive>=3||score<35) return 'QUARANTINED';
    if(consecutive>0||Number(rec.warmFailures||0)>=2||score<60) return 'DEGRADED';
    if(Number(rec.hotReadyCount||0)>=1&&Number(rec.firstFrames||0)>=1&&score>=82) return 'PLAYBACK_READY';
    if(Number(rec.firstFrames||0)>=1&&score>=67) return 'VERIFIED';
    return 'DISCOVERED';
  }
  function ensure(asset){
    const key=keyOf(asset); if(!key) return null;
    let rec=records.get(key);
    if(!rec){rec=blank(key,asset);records.set(key,rec);}
    const d=descriptor(asset);
    rec.competitionId=d.competitionId||rec.competitionId;rec.provider=d.provider||rec.provider;rec.transport=d.transport||rec.transport;
    rec.lastSeenAt=now();rec.state=derive(rec);return rec;
  }
  function networkSuspect(key){
    const cutoff=now()-25000;
    while(recentFailures.length&&recentFailures[0].at<cutoff)recentFailures.shift();
    recentFailures.push({at:now(),key});
    return new Set(recentFailures.map(x=>x.key)).size>=3;
  }
  function mutate(asset,fn){
    const rec=ensure(asset);if(!rec)return null;fn(rec);rec.score=clamp(rec.score);rec.state=derive(rec);rec.lastSeenAt=now();schedulePersist();notify(rec);return clone(rec);
  }
  function noteSelection(asset){return mutate(asset,r=>{r.selections++;});}
  function noteFirstFrame(asset,ms){return mutate(asset,r=>{r.firstFrames++;r.consecutiveFailures=0;r.lastSuccessAt=now();r.lastError='';const n=Number(ms);if(Number.isFinite(n)&&n>=0){r.startupSamples=[...(r.startupSamples||[]),n].slice(-64);r.score+=n<=1500?7:n<=3000?4:n>6000?-4:1;}else r.score+=2;});}
  function noteHotReady(asset,ms){
    const result=mutate(asset,r=>{r.hotReadyCount++;r.firstFrames++;r.consecutiveFailures=0;r.lastSuccessAt=now();r.lastHotReadyAt=now();r.lastError='';r.score+=8;const n=Number(ms);if(Number.isFinite(n)&&n>=0)r.startupSamples=[...(r.startupSamples||[]),n].slice(-64);});
    sendTelemetry('hot-ready',asset,{warmReadyMs:Number(ms)||0});return result;
  }
  function noteStall(asset){return mutate(asset,r=>{r.stalls++;r.score-=3;});}
  function noteWarmFailure(asset,reason='standby warm failed'){
    const key=keyOf(asset),suspect=networkSuspect(key);
    const result=mutate(asset,r=>{r.warmFailures++;r.lastError=clean(reason,700);r.score-=suspect?1:5;});
    sendTelemetry('warm-failure',asset,{lastError:clean(reason,700),networkSuspect:suspect});return result;
  }
  function noteFailure(asset,reason='playback failure'){
    const key=keyOf(asset),suspect=networkSuspect(key);
    const result=mutate(asset,r=>{r.failures++;r.consecutiveFailures++;r.lastFailureAt=now();r.lastError=clean(reason,700);r.score-=suspect?4:15;if(r.consecutiveFailures>=3||r.score<35)r.quarantinedUntil=Math.max(Number(r.quarantinedUntil||0),now()+30*60*1000);});
    return result;
  }
  function noteRecoveredFailover(asset){const result=mutate(asset,r=>{r.recoveredFailovers++;r.lastSuccessAt=now();});sendTelemetry('recovered-failover',asset,{});return result;}
  function state(asset){const rec=ensure(asset);return rec?derive(rec):'DISCOVERED';}
  function score(asset){return Number(ensure(asset)?.score||80);}
  function eligible(asset){return state(asset)!=='QUARANTINED';}
  function hotReady(asset){return state(asset)==='PLAYBACK_READY';}
  function rankBonus(asset){const s=state(asset),n=score(asset);if(s==='QUARANTINED')return-10000;if(s==='PLAYBACK_READY')return 35+Math.round((n-80)/4);if(s==='VERIFIED')return 15;if(s==='DEGRADED')return-25;return 0;}
  function snapshot(){
    const rows=[...records.values()].map(x=>({...x,state:derive(x)}));
    const states={};for(const r of rows)states[r.state]=(states[r.state]||0)+1;
    return {version:'1.0',assets:rows.length,states,records:rows.sort((a,b)=>Number(b.lastSeenAt||0)-Number(a.lastSeenAt||0)).slice(0,80)};
  }
  function notify(rec){for(const fn of [...listeners]){try{fn(clone(rec));}catch(_){}}}
  function subscribe(fn){if(typeof fn!=='function')return()=>{};listeners.add(fn);return()=>listeners.delete(fn);}
  function schedulePersist(){if(persistenceTimer)return;persistenceTimer=setTimeout(()=>{persistenceTimer=null;persist();},180);}
  function persist(){
    try{const rows=[...records.values()].sort((a,b)=>Number(b.lastSeenAt||0)-Number(a.lastSeenAt||0)).slice(0,MAX_ASSETS);localStorage.setItem(STORAGE_KEY,JSON.stringify({version:1,rows}));}catch(_){ }
  }
  function restore(){
    try{const data=JSON.parse(localStorage.getItem(STORAGE_KEY)||'null');for(const row of (data?.rows||[])){const key=clean(row?.mediaKey,1800);if(!key)continue;const rec={...blank(key),...row};if(Number(rec.quarantinedUntil||0)<=now()&&rec.state==='QUARANTINED')rec.quarantinedUntil=0;rec.state=derive(rec);records.set(key,rec);}}catch(_){ }
  }
  function sendTelemetry(event,asset,extra={}){
    try{const session={...descriptor(asset),...extra};fetch('/api/playback/telemetry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event,session}),keepalive:true,cache:'no-store'}).catch(()=>{});}catch(_){ }
  }

  // Learn from the canonical playback session without becoming a second playback
  // authority. Standby-only events are reported explicitly by app.js.
  let lastSelection=0,lastFirstFrame=0,lastStalls=0,lastFailures=0;
  window.addEventListener?.('sbb:playback-session',ev=>{
    const s=ev?.detail||{};const key=clean(s.mediaKey||s.clipKey,1800);if(!key)return;
    const asset={mediaKey:key,clipKey:key,competitionId:s.league,league:s.league,provider:s.provider,transport:s.transport,sourceUrl:s.sourceUrl,sourceExternalUrl:s.sourceExternalUrl,title:s.title};
    const selection=Number(s.selectionId||0);
    if(selection!==lastSelection){lastSelection=selection;lastFirstFrame=0;lastStalls=0;lastFailures=0;noteSelection(asset);}
    if(Number(s.firstFrameAt||0)>0&&!lastFirstFrame){lastFirstFrame=Number(s.firstFrameAt);noteFirstFrame(asset,s.firstFrameMs);}
    if(Number(s.stallCount||0)>lastStalls){lastStalls=Number(s.stallCount||0);noteStall(asset);}
    if(Number(s.failureCount||0)>lastFailures){lastFailures=Number(s.failureCount||0);noteFailure(asset,s.lastError);}
  });

  restore();
  window.SBB_PLAYBACK_READINESS=Object.freeze({version:'1.0',keyOf,descriptor,state,score,eligible,hotReady,rankBonus,noteSelection,noteFirstFrame,noteHotReady,noteStall,noteWarmFailure,noteFailure,noteRecoveredFailover,snapshot,subscribe,_derive:derive});
})();

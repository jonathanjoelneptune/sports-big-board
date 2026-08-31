'use strict';
const assert=require('assert');
const fs=require('fs');
const path=require('path');
const vm=require('vm');
const ROOT=path.resolve(__dirname,'..');
const read=rel=>fs.readFileSync(path.join(ROOT,rel),'utf8');
const version=read('VERSION').trim();
assert.strictEqual(version,'5.0.2');
const app=read('app.js');
const cert=read('architecture/comprehensive-site-certification.js');
const index=read('index.html');
assert(index.includes(`architecture/score-media-plan-v5.js?v=${version}`));
for(const token of [
  'scoreCardPlayableItemsForIntent','resolveScoreIntentMediaPlan','candidateAttempt','candidateRejected','planExhausted',
  'PROVEN_HISTORY','HOT_THIS_SESSION','indexedRecapCandidatesFor','RECAP_CANDIDATE_INDEX','MAX_RECAP_ALTERNATES_PER_TIER=4','MAX_RECAP_ALTERNATES_TOTAL=12','scoreIntentPlan','recapIndex'
])assert(app.includes(token),`missing v5.0.2 media-plan token ${token}`);
assert(cert.includes("const VERSION='3.2'"));
assert(cert.includes('gameCenterPayloadQuality'));
assert(cert.includes('PAYLOAD_TOO_SPARSE'));
assert(cert.includes("lg==='NFL'||lg==='CFB'"));
assert(cert.includes('planBuildMax='));
assert(cert.includes('planCandidates'));

// The recent recap registry may be globally rebuilt in background, but the hot
// player/UI lookup path may not linearly scan the whole registry anymore.
const registryScans=(app.match(/for\(const (?:\[id,x\]|item) of (?:\[\.\.\.)?RECAP_CANDIDATE_REGISTRY/g)||[]).length;
assert(registryScans<=2,'global recap registry scans must be confined to background rebuild/prune paths');
assert(!app.includes('for(const x of RECAP_CANDIDATE_REGISTRY.values()) add(x);'),'hot recap alternate lookup still performs a full registry scan');

(async()=>{
  // Score intent planning must cooperatively yield across a pathological date pool.
  let perf=0,yields=0;
  const planWindow={SBB_MAIN_THREAD_GUARD:{yieldToBrowser:async()=>{yields++;perf+=1;return true;}}};planWindow.window=planWindow;
  const planSandbox={window:planWindow,console,Date,Math,Number,String,Object,Array,Set,Map,JSON,Promise,Error,performance:{now:()=>{perf+=0.4;return perf;}},setTimeout,clearTimeout,requestAnimationFrame:fn=>fn()};
  vm.createContext(planSandbox);vm.runInContext(read('architecture/score-media-plan-v5.js'),planSandbox,{filename:'score-media-plan-v5.js'});
  const dateItems=Array.from({length:2400},(_,i)=>({id:`asset-${i}`,event:i%24===0?'target':'other'}));
  const built=await planWindow.SBB_SCORE_MEDIA_PLAN.build({exactItems:[{id:'exact-1'}],dateItems,includeDateItem:x=>x.event==='target',isUsable:()=>true,keyFor:x=>x.id,chunkItems:24,chunkBudgetMs:5});
  assert.strictEqual(built.items.length,101,'exact candidate plus 100 matching date candidates expected');
  assert(built.metrics.yields>=50,'pathological date scan must yield repeatedly instead of blocking the UI thread');
  assert(yields>=built.metrics.yields,'main-thread guard/browser yield must be used by score planner');

  // The v5 transaction records candidate exhaustion explicitly. One failed
  // candidate cannot make the transaction UNAVAILABLE while alternatives remain.
  const eventListeners={};
  const w={
    SBB_CORE:{event:(x,c)=>({...x,competitionId:x.competitionId||c})},
    SBB_EVENT_IDENTITY:{key:e=>`${String(e.competitionId||'').toUpperCase()}:${String(e.eventId||e.id||'')}`},
    SBB_PLAYBACK_TRANSPORTS:{mediaKey:i=>i.youtubeId?`youtube:${i.youtubeId}`:i.mediaUrl?`direct:${i.mediaUrl}`:String(i.id||'')},
    SBB_MEDIA_SCOPE:{isCollection:()=>false},
    addEventListener:(n,fn)=>{(eventListeners[n]||=([])).push(fn);},dispatchEvent:ev=>{for(const fn of eventListeners[ev.type]||[])fn(ev);}
  };w.window=w;
  const sandbox={window:w,console,Date,Math,Number,String,Object,Array,Set,Map,JSON,RegExp,Promise,Error,structuredClone:global.structuredClone,performance:{now:()=>Date.now()},CustomEvent:function(type,init){this.type=type;this.detail=init?.detail;},setTimeout:()=>0,clearTimeout:()=>{},fetch:()=>Promise.resolve({ok:true}),document:{}};
  vm.createContext(sandbox);for(const f of ['architecture/app-store-v5.js','architecture/selected-event-store.js','architecture/playback-session.js','architecture/playback-orchestrator-v5.js'])vm.runInContext(read(f),sandbox,{filename:f});
  const event={competitionId:'CFB',eventId:'heavy-event',awayTeam:{name:'Away'},homeTeam:{name:'Home'}};
  const a={id:'a',mediaUrl:'https://example.test/a.mp4',provider:'DIRECT_VIDEO'},b={id:'b',youtubeId:'bbbbbbbbbbb',provider:'YOUTUBE'},c={id:'c',youtubeId:'ccccccccccc',provider:'YOUTUBE'};
  let tx=w.SBB_PLAYBACK_ORCHESTRATOR.beginScoreIntent(event,{userInitiated:true});
  w.SBB_PLAYBACK_ORCHESTRATOR.setPlan(tx,[a,b,c]);
  w.SBB_PLAYBACK_ORCHESTRATOR.candidateAttempt(tx,a,{candidateIndex:0});
  w.SBB_PLAYBACK_ORCHESTRATOR.candidateRejected(tx,a,'PREWARM_TIMEOUT');
  w.SBB_PLAYBACK_ORCHESTRATOR.candidateAttempt(tx,b,{candidateIndex:1});
  w.SBB_PLAYBACK_ORCHESTRATOR.selectMedia(tx,b,{candidateIndex:1});
  let snap=w.SBB_APP_STORE.snapshot();
  assert.strictEqual(snap.playback.planAttempted,2);assert.strictEqual(snap.playback.planRejected,1);assert.strictEqual(snap.playback.planExhausted,false);assert.strictEqual(snap.playback.candidateIndex,1);assert.strictEqual(snap.invariant,'OK');

  // Premature UNAVAILABLE is itself an invariant error.
  tx=w.SBB_PLAYBACK_ORCHESTRATOR.beginScoreIntent({...event,eventId:'premature'},{userInitiated:true});w.SBB_PLAYBACK_ORCHESTRATOR.setPlan(tx,[a,b]);w.SBB_PLAYBACK_ORCHESTRATOR.candidateAttempt(tx,a,{candidateIndex:0});w.SBB_PLAYBACK_ORCHESTRATOR.candidateRejected(tx,a,'PREWARM_TIMEOUT');w.SBB_PLAYBACK_ORCHESTRATOR.unavailable(tx,'wrongly gave up early');
  snap=w.SBB_APP_STORE.snapshot();assert.match(snap.invariant,/UNAVAILABLE BEFORE MEDIA PLAN EXHAUSTED/);

  // Exhausting every candidate makes UNAVAILABLE legitimate and invariant-safe.
  tx=w.SBB_PLAYBACK_ORCHESTRATOR.beginScoreIntent({...event,eventId:'exhausted'},{userInitiated:true});w.SBB_PLAYBACK_ORCHESTRATOR.setPlan(tx,[a,b]);
  for(const [i,item] of [a,b].entries()){w.SBB_PLAYBACK_ORCHESTRATOR.candidateAttempt(tx,item,{candidateIndex:i});w.SBB_PLAYBACK_ORCHESTRATOR.candidateRejected(tx,item,'not browser ready');}
  w.SBB_PLAYBACK_ORCHESTRATOR.planExhausted(tx,'all tried');w.SBB_PLAYBACK_ORCHESTRATOR.unavailable(tx,'all tried');snap=w.SBB_APP_STORE.snapshot();
  assert.strictEqual(snap.playback.planAttempted,2);assert.strictEqual(snap.playback.planRejected,2);assert.strictEqual(snap.playback.planExhausted,true);assert.strictEqual(snap.playback.state,'UNAVAILABLE');assert.strictEqual(snap.invariant,'OK');

  console.log('PASS: v5.0.2 media-plan continuity + cooperative score planning + indexed recap lookup contracts');
})().catch(err=>{console.error(err);process.exitCode=1;});

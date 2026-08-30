const fs=require('fs');
const assert=require('assert');
const vm=require('vm');

const VERSION=fs.readFileSync('VERSION','utf8').trim();
const index=fs.readFileSync('index.html','utf8');
const nativeTransport=fs.readFileSync('architecture/native-transport.js','utf8');
const availability=fs.readFileSync('architecture/score-card-availability-index.js','utf8');
const render=fs.readFileSync('architecture/render-pipeline.js','utf8');
const efficiency=fs.readFileSync('architecture/efficiency-certification.js','utf8');

assert.strictEqual(VERSION,'4.7.12');
assert(index.includes(`architecture/native-transport.js?v=${VERSION}`));
assert(index.indexOf(`architecture/native-transport.js?v=${VERSION}`) <
       index.indexOf(`architecture/request-broker.js?v=${VERSION}`));
assert(nativeTransport.includes('capturedFetch'));
assert(nativeTransport.includes('window.SBB_API?.url'));

assert(availability.includes('canonical Day State eventPlans'));
assert(availability.includes('catalogPlanForScoreGame'));
assert(availability.includes('payload?.eventPlans'));
assert(availability.includes("kind:'day-state-plan'"));
assert(availability.includes('plan?.playable'));
assert(availability.includes('legacy-resolved'));

assert(render.includes('perfStartedAt'));
assert(render.includes('perfFinishedAt'));
assert(render.includes('availabilityPlanPlayable'));

assert(efficiency.includes('window.SBB_NATIVE_TRANSPORT?.fetch'));
assert(efficiency.includes('window.SBB_NATIVE_TRANSPORT?.url?.(path)'));
assert(efficiency.includes('function attributeLongTask'));
assert(efficiency.includes("'LONGEST TASKS'"));
assert(efficiency.includes('AVAIL_PLAN_PLAYABLE='));

// Native transport must remain bound to the browser fetch captured before replacement.
let nativeCalls=0,wrappedCalls=0;
const ntCtx={window:null};
ntCtx.window=ntCtx;
ntCtx.fetch=async function(url){nativeCalls++;return {url};};
ntCtx.SBB_API={url:path=>`https://backend.example${path}`};
vm.createContext(ntCtx);
vm.runInContext(nativeTransport,ntCtx);
ntCtx.fetch=async function(){wrappedCalls++;throw new Error('broker fetch should not run');};
(async()=>{
  const target=ntCtx.SBB_NATIVE_TRANSPORT.url('/api/day-state/thin?date=2025-01-15');
  await ntCtx.SBB_NATIVE_TRANSPORT.fetch(target);
  assert.strictEqual(nativeCalls,1);
  assert.strictEqual(wrappedCalls,0);
  assert.strictEqual(target,'https://backend.example/api/day-state/thin?date=2025-01-15');

  // Day State plan media should bypass legacy broad scan even when match objects
  // are clones and verifiedPlayableItemsForGame is empty.
  const matches=[
    {id:'plan-final',competitionId:'MLB',status:'FINAL'},
    {id:'scheduled',competitionId:'MLB',status:'SCHEDULED'},
    {id:'fallback',competitionId:'MLB',status:'FINAL'}
  ];
  const avCtx={
    window:null,document:{readyState:'complete',addEventListener(){}},
    performance:{now:(()=>{let n=0;return()=>++n;})()},
    CustomEvent:function(){},setInterval(){return 1;},clearInterval(){},setTimeout(){},
    scoreBrowseDate:'2026-08-29'
  };
  avCtx.window=avCtx;
  let originalCalls=0;
  avCtx.scoreCardPlayableItems=m=>{originalCalls++;return [{id:`legacy-${m.id}`}];};
  avCtx.verifiedPlayableItemsForGame=()=>[];
  avCtx.scoreMatchesForDate=()=>matches.map(x=>({...x}));
  avCtx.scoreGameLookupKeys=m=>[`MLB:${m.id}`];
  avCtx.catalogPlanForScoreGame=m=>m.id==='plan-final'
    ? {eventId:'plan-final',league:'MLB',canonicalEventKey:'MLB:plan-final',playable:[{id:'plan-media'}]}
    : null;
  avCtx.SBB_SCORE_DATE={snapshot:()=>({browseDate:'2026-08-29'})};
  avCtx.SBB_DAY_STATE={cache:()=>({
    eventPlans:{
      'MLB:plan-final':{
        eventId:'plan-final',league:'MLB',canonicalEventKey:'MLB:plan-final',
        event:{id:'plan-final',competitionId:'MLB'},
        playable:[{id:'plan-media'}]
      }
    }
  })};
  vm.createContext(avCtx);
  vm.runInContext(availability,avCtx);
  avCtx.SBB_SCORECARD_AVAILABILITY_INDEX.beginRender();
  assert.strictEqual(avCtx.scoreCardPlayableItems({id:'plan-final',competitionId:'MLB',status:'FINAL'})[0].id,'plan-media');
  assert.deepStrictEqual(JSON.parse(JSON.stringify(avCtx.scoreCardPlayableItems({id:'scheduled',competitionId:'MLB',status:'SCHEDULED'}))),[]);
  assert.strictEqual(avCtx.scoreCardPlayableItems({id:'fallback',competitionId:'MLB',status:'FINAL'})[0].id,'legacy-fallback');
  const stats=avCtx.SBB_SCORECARD_AVAILABILITY_INDEX.endRender();
  assert.strictEqual(originalCalls,1);
  assert(stats.planPlayable>=1);
  assert(stats.fastHits>=2);
  assert.strictEqual(stats.fallbacks,1);

  console.log('PASS: v4.7.12 native thin transport + Day State render model + long-task attribution contracts');
})().catch(err=>{console.error(err);process.exit(1);});

const fs=require('fs');
const assert=require('assert');
const vm=require('vm');
const VERSION=fs.readFileSync('VERSION','utf8').trim();
const index=fs.readFileSync('index.html','utf8');
const availability=fs.readFileSync('architecture/score-card-availability-index.js','utf8');
const render=fs.readFileSync('architecture/render-pipeline.js','utf8');
const efficiency=fs.readFileSync('architecture/efficiency-certification.js','utf8');
const broker=fs.readFileSync('architecture/request-broker.js','utf8');
const backend=fs.readFileSync('sbb/day_state.py','utf8');

assert.strictEqual(VERSION,'4.7.11');
assert(index.includes(`architecture/score-card-availability-index.js?v=${VERSION}`));
assert(index.indexOf(`architecture/score-card-availability-index.js?v=${VERSION}`) <
       index.indexOf(`architecture/card-build-cache.js?v=${VERSION}`));
assert(availability.includes('window.SBB_SCORECARD_AVAILABILITY_INDEX'));
assert(availability.includes('stableKey'));
assert(availability.includes("kind:'scheduled'"));
assert(availability.includes("kind:'thin-score-only'"));
assert(availability.includes("kind:'verified'"));
assert(availability.includes('verifiedPlayableItemsForGame'));
assert(availability.includes('originalPlayable(match)'));
assert(render.includes('SBB_SCORECARD_AVAILABILITY_INDEX?.beginRender'));
assert(render.includes('SBB_SCORECARD_AVAILABILITY_INDEX?.endRender'));
assert(backend.includes('def serve_thin_probe'));
assert(backend.includes('"/api/day-state/thin"'));
assert(efficiency.includes('/api/day-state/thin?date='));
assert(efficiency.includes('AVAIL_INDEX_P95='));
assert(efficiency.includes('http=${x.httpStatus'));
assert(broker.includes("path==='/api/day-state/thin'"));

const matches=[
  {id:'scheduled',status:'SCHEDULED'},
  {id:'verified',status:'FINAL',verified:true},
  {id:'fallback',status:'FINAL'}
];
const ctx={
  window:null,document:{readyState:'complete',addEventListener(){}},
  performance:{now:(()=>{let n=0;return()=>++n;})()},
  CustomEvent:function(){},setInterval(){return 1;},clearInterval(){},setTimeout(){},
  scoreBrowseDate:'2026-08-29'
};
ctx.window=ctx;
let originalCalls=0;
ctx.scoreCardPlayableItems=m=>{originalCalls++;return [{id:`legacy-${m.id}`}];};
ctx.verifiedPlayableItemsForGame=m=>m.verified?[{id:`verified-${m.id}`}]:[];
ctx.scoreMatchesForDate=()=>matches.map(x=>({...x}));
ctx.scoreGameLookupKeys=m=>[`SPORTS:${m.id}`];
ctx.SBB_SCORE_DATE={snapshot:()=>({browseDate:'2026-08-29'})};
ctx.SBB_DAY_STATE={cache:()=>({thinSnapshot:false})};
vm.createContext(ctx);
vm.runInContext(availability,ctx);
ctx.SBB_SCORECARD_AVAILABILITY_INDEX.beginRender();
assert.deepStrictEqual(JSON.parse(JSON.stringify(ctx.scoreCardPlayableItems({id:'scheduled',status:'SCHEDULED'}))),[]);
assert.strictEqual(ctx.scoreCardPlayableItems({id:'verified',status:'FINAL',verified:true})[0].id,'verified-verified');
assert.strictEqual(ctx.scoreCardPlayableItems({id:'fallback',status:'FINAL'})[0].id,'legacy-fallback');
const stats=ctx.SBB_SCORECARD_AVAILABILITY_INDEX.endRender();
assert.strictEqual(originalCalls,1);
assert.strictEqual(stats.fastHits,2);
assert.strictEqual(stats.fallbacks,1);
console.log('PASS: v4.7.11 thin-probe repair + render-scoped availability index contracts');

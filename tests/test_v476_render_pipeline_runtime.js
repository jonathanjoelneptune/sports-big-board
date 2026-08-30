const fs=require('fs');
const assert=require('assert');

const VERSION=fs.readFileSync('VERSION','utf8').trim();
const parts=VERSION.split('.').map(Number);
const index=fs.readFileSync('index.html','utf8');
const future=fs.readFileSync('architecture/future-date-navigation.js','utf8');
const coordinator=fs.readFileSync('architecture/date-transition-coordinator.js','utf8');
const render=fs.readFileSync('architecture/render-pipeline.js','utf8');
const broker=fs.readFileSync('architecture/request-broker.js','utf8');
const day=fs.readFileSync('architecture/day-state.js','utf8');
const efficiency=fs.readFileSync('architecture/efficiency-certification.js','utf8');

assert.deepStrictEqual(parts.slice(0,2),[4,7]);
assert(parts[2]>=6);
assert(index.includes(`architecture/future-date-navigation.js?v=${VERSION}`));
assert(index.includes(`architecture/render-pipeline.js?v=${VERSION}`));
assert(future.includes('window.SBB_FUTURE_DATES'));
assert(future.includes('setFutureShell'));
assert(coordinator.includes('Future scheduled dates are valid Big Board dates'));
assert(!coordinator.includes("if(d>today())d=today()"));
assert(render.includes('window.SBB_RENDER_PIPELINE'));
assert(render.includes('coalesced'));
assert(broker.includes('const runId=clean(window.__SBB_EFFICIENCY_RUN_ID'));
assert(efficiency.includes('runId:String(d.runId'));
assert(day.includes("emitPhase(date,'STORE_SCORE_ROWS'"));
assert(day.includes("emitPhase(date,'INGEST_MEDIA_PLANS'"));
assert(day.includes("emitPhase(date,'APPLY_TOTAL'"));
console.log(`PASS: ${VERSION} retains v4.7.6 future-date + render-pipeline + attribution baseline`);

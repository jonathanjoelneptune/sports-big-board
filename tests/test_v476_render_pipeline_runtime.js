const fs=require('fs');
const assert=require('assert');

const VERSION=fs.readFileSync('VERSION','utf8').trim();
const index=fs.readFileSync('index.html','utf8');
const future=fs.readFileSync('architecture/future-date-navigation.js','utf8');
const coordinator=fs.readFileSync('architecture/date-transition-coordinator.js','utf8');
const render=fs.readFileSync('architecture/render-pipeline.js','utf8');
const broker=fs.readFileSync('architecture/request-broker.js','utf8');
const day=fs.readFileSync('architecture/day-state.js','utf8');
const efficiency=fs.readFileSync('architecture/efficiency-certification.js','utf8');

assert.strictEqual(VERSION,'4.7.6');

assert(index.includes('window.__SBB_LAUNCH_CONTROL_PARSED_AT=performance.now()'));
assert(index.includes('__SBB_PENDING_LAUNCH'));
assert(index.includes(`architecture/future-date-navigation.js?v=${VERSION}`));
assert(index.includes(`architecture/render-pipeline.js?v=${VERSION}`));

assert(future.includes('window.SBB_FUTURE_DATES'));
assert(future.includes("picker.removeAttribute('max')"));
assert(future.includes('setFutureShell'));
assert(future.includes("btn.disabled=false"));

assert(coordinator.includes('Future scheduled dates are valid Big Board dates'));
assert(!coordinator.includes("if(d>today())d=today()"));
assert(coordinator.includes('SBB_FUTURE_DATES.setFutureShell'));
assert(coordinator.includes('Day State apply() already owns the normal first-paint render'));
assert(coordinator.includes("'cold-ribbon-fallback'"));

assert(render.includes('window.SBB_RENDER_PIPELINE'));
assert(render.includes("cause:'same-frame'"));
assert(render.includes('durationMs'));
assert(render.includes('coalesced'));

assert(broker.includes('const runId=clean(window.__SBB_EFFICIENCY_RUN_ID'));
assert(broker.includes('generation,runId'));
assert(efficiency.includes('runId:String(d.runId'));
assert(efficiency.includes('window.__SBB_EFFICIENCY_RUN_ID=runId'));
assert(efficiency.includes('RENDER_P95='));
assert(efficiency.includes('DAY_APPLY_P95='));
assert(efficiency.includes('launchHandlerReadyMs'));

assert(day.includes("phase:'")===false); // phases are emitted by helper calls
assert(day.includes("emitPhase(date,'STORE_SCORE_ROWS'"));
assert(day.includes("emitPhase(date,'INGEST_MEDIA_PLANS'"));
assert(day.includes("emitPhase(date,'APPLY_TOTAL'"));
assert(day.includes("'day-state-apply'"));

console.log('PASS: v4.7.6 future-date + render-pipeline + efficiency-attribution contracts');

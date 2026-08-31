const fs=require('fs');
const assert=require('assert');
const VERSION=fs.readFileSync('VERSION','utf8').trim();
const parts=VERSION.split('.').map(Number);
const index=fs.readFileSync('index.html','utf8');
const availability=fs.readFileSync('architecture/score-card-availability-index.js','utf8');
const render=fs.readFileSync('architecture/render-pipeline.js','utf8');
const efficiency=fs.readFileSync('architecture/efficiency-certification.js','utf8');
const broker=fs.readFileSync('architecture/request-broker.js','utf8');
const backend=fs.readFileSync('sbb/day_state.py','utf8');

assert(parts[0]>4 || (parts[0]===4 && (parts[1]>7 || (parts[1]===7 && parts[2]>=11))));
assert(index.includes(`architecture/score-card-availability-index.js?v=${VERSION}`));
assert(index.indexOf(`architecture/score-card-availability-index.js?v=${VERSION}`) <
       index.indexOf(`architecture/card-build-cache.js?v=${VERSION}`));
assert(availability.includes('window.SBB_SCORECARD_AVAILABILITY_INDEX'));
assert(availability.includes('stableKey'));
assert(availability.includes("kind:'scheduled'"));
assert(availability.includes("kind:'thin-score-only'"));
assert(availability.includes('originalPlayable(match)'));
assert(render.includes('SBB_SCORECARD_AVAILABILITY_INDEX?.beginRender'));
assert(render.includes('SBB_SCORECARD_AVAILABILITY_INDEX?.endRender'));
assert(backend.includes('def serve_thin_probe'));
assert(backend.includes('"/api/day-state/thin"'));
assert(efficiency.includes('/api/day-state/thin?date='));
assert(efficiency.includes('AVAIL_INDEX_P95='));
assert(broker.includes("path==='/api/day-state/thin'"));
console.log(`PASS: ${VERSION} retains v4.7.11 thin-probe + availability-index baseline`);

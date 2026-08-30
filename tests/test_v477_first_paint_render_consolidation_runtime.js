const fs=require('fs');
const assert=require('assert');

const VERSION=fs.readFileSync('VERSION','utf8').trim();
const parts=VERSION.split('.').map(Number);
const index=fs.readFileSync('index.html','utf8');
const render=fs.readFileSync('architecture/render-pipeline.js','utf8');
const coordinator=fs.readFileSync('architecture/date-transition-coordinator.js','utf8');
const day=fs.readFileSync('architecture/day-state.js','utf8');
const efficiency=fs.readFileSync('architecture/efficiency-certification.js','utf8');

assert.deepStrictEqual(parts.slice(0,2),[4,7]);
assert(parts[2]>=7);
assert(index.indexOf(`architecture/render-pipeline.js?v=${VERSION}`) <
       index.indexOf(`architecture/date-transition-coordinator.js?v=${VERSION}`));
assert(render.includes('beginGeneration'));
assert(render.includes('commitGeneration'));
assert(render.includes('generation-hold'));
assert(render.includes('document.createDocumentFragment()'));
assert(coordinator.includes('SBB_RENDER_PIPELINE?.beginGeneration'));
assert(coordinator.includes('SBB_RENDER_PIPELINE?.commitGeneration'));
assert(day.includes("SBB_RENDER_PIPELINE.request('day-state-apply'"));
assert(efficiency.includes('function ribbonFirstUsable'));
assert(efficiency.includes('function ribbonFullySettled'));
assert(efficiency.includes('FULL_SETTLE_TIMEOUTS='));
assert(efficiency.includes('CARD_BUILD_P95='));
assert(efficiency.includes('DOM_COMMIT_P95='));
assert(efficiency.includes('BROWSER_PAINT_P95='));
console.log(`PASS: ${VERSION} retains v4.7.7 first-paint + generation render baseline`);

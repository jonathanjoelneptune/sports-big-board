const fs=require('fs');
const assert=require('assert');

const VERSION=fs.readFileSync('VERSION','utf8').trim();
const parts=VERSION.split('.').map(Number);
const index=fs.readFileSync('index.html','utf8');
const cache=fs.readFileSync('architecture/card-build-cache.js','utf8');
const render=fs.readFileSync('architecture/render-pipeline.js','utf8');
const efficiency=fs.readFileSync('architecture/efficiency-certification.js','utf8');
const backend=fs.readFileSync('sbb/day_state.py','utf8');

assert(parts[0]===4 && (parts[1]>7 || (parts[1]===7 && parts[2]>=8)));
assert(index.includes(`architecture/card-build-cache.js?v=${VERSION}`));
assert(index.indexOf(`architecture/card-build-cache.js?v=${VERSION}`) <
       index.indexOf(`architecture/render-pipeline.js?v=${VERSION}`));
assert(cache.includes('window.SBB_CARD_BUILD_CACHE'));
assert(cache.includes('WeakMap'));
assert(cache.includes('beginRender'));
assert(cache.includes('endRender'));
assert(render.includes('SBB_CARD_BUILD_CACHE?.beginRender'));
assert(render.includes('SBB_CARD_BUILD_CACHE?.endRender'));
assert(efficiency.includes('sampleHeapWindow'));
assert(efficiency.includes('Heap retained (stabilized)'));
assert(efficiency.includes('CARD_CACHE_HITS='));
assert(backend.includes('def _merge_future_catalog_rows'));
assert(backend.includes('FUTURE_CATALOG_REBUILT'));
assert(backend.includes('projectionDiagnostics'));
console.log(`PASS: ${VERSION} retains v4.7.8 future projection + card cache + memory baseline`);

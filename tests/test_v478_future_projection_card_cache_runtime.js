const fs=require('fs');
const assert=require('assert');

const VERSION=fs.readFileSync('VERSION','utf8').trim();
const index=fs.readFileSync('index.html','utf8');
const cache=fs.readFileSync('architecture/card-build-cache.js','utf8');
const render=fs.readFileSync('architecture/render-pipeline.js','utf8');
const efficiency=fs.readFileSync('architecture/efficiency-certification.js','utf8');
const backend=fs.readFileSync('sbb/day_state.py','utf8');

assert.strictEqual(VERSION,'4.7.8');
assert(index.includes(`architecture/card-build-cache.js?v=${VERSION}`));
assert(index.indexOf(`architecture/card-build-cache.js?v=${VERSION}`) <
       index.indexOf(`architecture/render-pipeline.js?v=${VERSION}`));

assert(cache.includes('window.SBB_CARD_BUILD_CACHE'));
assert(cache.includes("'scoreCardAvailability'"));
assert(cache.includes("'scoreCardPlayableItems'"));
assert(cache.includes("'externalMediaItemsForGame'"));
assert(cache.includes("'scoreFromMatch'"));
assert(cache.includes('WeakMap'));
assert(cache.includes('beginRender'));
assert(cache.includes('endRender'));

assert(render.includes('SBB_CARD_BUILD_CACHE?.beginRender'));
assert(render.includes('SBB_CARD_BUILD_CACHE?.endRender'));
assert(render.includes('cardCacheHits'));
assert(render.includes('cardHelperMs'));

assert(efficiency.includes('sampleHeapWindow'));
assert(efficiency.includes('Heap retained (stabilized)'));
assert(efficiency.includes('MEMORY_WINDOW_SPREAD='));
assert(efficiency.includes('CARD_CACHE_HITS='));
assert(efficiency.includes('dayStateSummary'));
assert(efficiency.includes('catalogCandidates'));

assert(backend.includes('def _merge_future_catalog_rows'));
assert(backend.includes('FUTURE_CATALOG_REBUILT'));
assert(backend.includes('projectionDiagnostics'));
assert(backend.includes('_future_catalog_event_count'));
assert(backend.includes('canonical_future > projected_games'));

console.log('PASS: v4.7.8 future schedule projection + card cache + stable memory contracts');

const fs=require('fs');
const assert=require('assert');

const VERSION=fs.readFileSync('VERSION','utf8').trim();
const index=fs.readFileSync('index.html','utf8');
const store=fs.readFileSync('architecture/score-date-store.js','utf8');
const coordinator=fs.readFileSync('architecture/date-transition-coordinator.js','utf8');
const efficiency=fs.readFileSync('architecture/efficiency-certification.js','utf8');
const card=fs.readFileSync('architecture/card-build-cache.js','utf8');
const render=fs.readFileSync('architecture/render-pipeline.js','utf8');
const backend=fs.readFileSync('sbb/day_state.py','utf8');

assert.strictEqual(VERSION,'4.7.10');
assert(index.includes(`architecture/score-date-store.js?v=${VERSION}`));

assert(store.includes("version:'1.0'"));
assert(store.includes('do not clamp future scheduled dates to today'));
assert(!store.includes('return raw>localDateISO(0)?localDateISO(0):raw'));

assert(coordinator.includes('interactive date navigation is Day State-only'));
assert(coordinator.includes('COLD_THIN_CATALOG'));
assert(!coordinator.includes('legacyRibbonFallback'));
assert(!coordinator.includes("state.firstPaintSource='COLD_CANONICAL_RIBBON'"));

assert(backend.includes('def _catalog_score_rows_for_day'));
assert(backend.includes('def _build_thin_catalog_snapshot'));
assert(backend.includes('COLD_THIN_CATALOG'));
assert(backend.includes('thinProbe'));
assert(backend.includes('thinSnapshot'));
assert(backend.includes('Queue the full canonical build only after a cold thin snapshot'));

assert(card.includes('helperBreakdown'));
assert(card.includes('helpers:Object.fromEntries'));
assert(render.includes('cardHelpers:cacheStats?.helpers'));

assert(efficiency.includes('Long tasks / 10 actions'));
assert(efficiency.includes('Long-task ms / action'));
assert(efficiency.includes('Cold history thin p95'));
assert(efficiency.includes('HISTORY_RIBBON_CALLS='));
assert(efficiency.includes('CARD_HELPERS='));
assert(efficiency.includes('probeColdThinHistory'));
assert(efficiency.includes("x.path==='/api/history/ribbon'"));

console.log('PASS: v4.7.10 cold-history fast path + future store + normalized main-thread contracts');

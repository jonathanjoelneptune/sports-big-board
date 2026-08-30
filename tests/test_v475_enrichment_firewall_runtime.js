const fs=require('fs');
const assert=require('assert');

const VERSION=fs.readFileSync('VERSION','utf8').trim();
const parts=VERSION.split('.').map(Number);
const index=fs.readFileSync('index.html','utf8');
const broker=fs.readFileSync('architecture/request-broker.js','utf8');
const coordinator=fs.readFileSync('architecture/date-transition-coordinator.js','utf8');
const loader=fs.readFileSync('architecture/operator-module-loader.js','utf8');
const historical=fs.readFileSync('architecture/historical-media-v4610.js','utf8');
const registry=fs.readFileSync('architecture/competition-registry-projection.js','utf8');
const efficiency=fs.readFileSync('architecture/efficiency-certification.js','utf8');
const dayBackend=fs.readFileSync('sbb/day_state.py','utf8');

assert.deepStrictEqual(parts.slice(0,2),[4,7]);
assert(parts[2]>=5);

assert(index.includes(`architecture/operator-module-loader.js?v=${VERSION}`));
assert(!index.includes(`<script src="architecture/competition-builder.js?v=${VERSION}"></script>`));
assert(!index.includes(`<script src="architecture/competition-builder-v4611.js?v=${VERSION}"></script>`));
assert(!index.includes(`<script src="architecture/competition-builder-v4612.js?v=${VERSION}"></script>`));
assert(!index.includes(`<script src="architecture/competition-builder-v4613.js?v=${VERSION}"></script>`));
assert(!index.includes(`<script src="architecture/special-event-media-v4616.js?v=${VERSION}"></script>`));

assert(loader.includes('window.SBB_OPERATOR_MODULES'));
assert(loader.includes('Operator modules load only when you use them'));
assert(loader.includes('competition-builder.js'));
assert(loader.includes('special-event-media-v4616.js'));
assert(!loader.includes('new MutationObserver'));

assert(broker.includes('Enrichment Firewall'));
assert(broker.includes("return 'ON_DEMAND'"));
assert(broker.includes("return 'IDLE_ENRICHMENT'"));
assert(broker.includes('deferred-abort'));
assert(broker.includes('deferred-release'));
assert(broker.includes('QUIET_MS=8000'));
assert(broker.includes("path==='/api/competition-builder/catalog'"));
assert(broker.includes('return 30000'));

assert(coordinator.includes('Historical discovery/media search is intentionally NOT launched here'));
assert(!coordinator.includes('fetch(`/api/history/discovery'));
assert(coordinator.includes('clearStaleSelection'));
assert(coordinator.includes('unwrapSetter'));

assert(historical.includes('dayStateFirstPaint'));
assert(historical.includes('__sbbOriginal=original.setDate'));

assert(registry.includes('30000'));
assert(registry.includes('timeoutMs=2500'));

assert(efficiency.includes('DEFERRED='));
assert(efficiency.includes('OPERATOR_MODULES='));
assert(efficiency.includes('__SBB_LAUNCH_CONTROL_PARSED_AT'));

assert(dayBackend.includes('HISTORICAL_COMPLETE_SECONDS'));
assert(dayBackend.includes('self.build_locks'));
assert(dayBackend.includes('v4.7.5 fairness'));
assert(dayBackend.includes('COLD_FALLBACK_REBUILT'));
assert(dayBackend.includes('type") or "").upper()'));
assert(dayBackend.includes('if typ == "SPECIAL_EVENT"'));

console.log(`PASS: ${VERSION} enrichment firewall + warm historical state contracts`);

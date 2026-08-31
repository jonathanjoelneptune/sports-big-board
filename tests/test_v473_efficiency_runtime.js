const fs=require('fs');
const assert=require('assert');

const VERSION=fs.readFileSync('VERSION','utf8').trim();
const parts=VERSION.split('.').map(Number);
const index=fs.readFileSync('index.html','utf8');
const src=fs.readFileSync('architecture/efficiency-certification.js','utf8');

assert(parts[0]===4 && (parts[1]>7 || (parts[1]===7 && parts[2]>=3)));
assert(index.includes(`architecture/efficiency-certification.js?v=${VERSION}`));
assert(src.includes("window.SBB_EFFICIENCY"));
assert(src.includes("runAutoTest"));
assert(src.includes("runHammer"));
assert(src.includes("PerformanceObserver"));
assert(src.includes("'longtask'"));
assert(src.includes("restoreState"));
assert(src.includes("/api/day-state"));
assert(src.includes("/api/competition-registry"));
assert(src.includes("/api/competition-builder/catalog"));
assert(src.includes("duplicateConcurrent"));
assert(src.includes("ribbonP95"));
assert(src.includes("apiP95"));
assert(src.includes("heapGrowthPct"));
assert(src.includes("domGrowthPct"));
assert(src.includes("longTaskMax"));
assert(src.includes("RUN AUTO TEST"));
assert(src.includes("RUN HAMMER"));
assert(src.includes("current state will be restored"));
assert(!src.includes("new MutationObserver"));
assert(!src.includes("method:'POST'"));
assert(!src.includes('method:"POST"'));

console.log(`PASS: ${VERSION} efficiency instrumentation + automated certification contracts`);

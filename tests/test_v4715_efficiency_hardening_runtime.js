const fs=require('fs');
const assert=require('assert');
const VERSION=fs.readFileSync('VERSION','utf8').trim();
const index=fs.readFileSync('index.html','utf8');
const render=fs.readFileSync('architecture/render-pipeline.js','utf8');
const availability=fs.readFileSync('architecture/score-card-availability-index.js','utf8');
const efficiency=fs.readFileSync('architecture/efficiency-certification.js','utf8');
const parts=VERSION.split('.').map(Number);
assert.deepStrictEqual(parts.slice(0,2),[4,7]);
assert(parts[2]>=15);

// filter bank fast path
for(const token of ['filterFastPath','sbbCardBankDate','bankComplete','applyBankFilter',"setCurrentFilter('ALL')",'card.hidden=!show','filterFastPathMisses']){
  assert(render.includes(token),`filter bank fast path: ${token}`);
}
const fastStart=render.indexOf('if(filterReason&&bankComplete(host,date))');
const fullStart=render.indexOf('if(filterReason)state.filterFastPathMisses',fastStart);
assert(fastStart>=0&&fullStart>fastStart,'filter bank fast path block');
const fastBlock=render.slice(fastStart,fullStart);
assert(!fastBlock.includes('fetch('),'filter bank fast path must remain network-free');
assert(fastBlock.includes('applyBankFilter(host,selectedFilter'),'filter bank applies visibility in place');
assert(render.includes('if(filterReason)state.filterFastPathMisses'),'stale bank falls back to full render');

// availability snapshot reuse
for(const token of ["reason.includes('filter-change')",'snapshotReused','forDate','knownPlayableMedia','directVerified','legacy-resolved']){
  assert(availability.includes(token),`availability snapshot reuse: ${token}`);
}
assert(availability.includes('scoreMatchesForDate(date)'),'availability indexes full date');
assert(!availability.includes('if(!visibleMatch(match))continue'),'availability must not be filter-scoped');

// stabilized DOM certification + authoritative media readiness
for(const token of ['sampleDomWindow','domAfter','domPeak','filterFastPaths','cardBankBuilds','availabilitySnapshotReuses','NO_KNOWN_PLAYABLE_MEDIA','.forDate?.(date)','DOM_BASELINE=',"grades.includes('FAIL')"]){
  assert(efficiency.includes(token),`stabilized DOM certification: ${token}`);
}
for(const asset of ['architecture/render-pipeline.js','architecture/score-card-availability-index.js','architecture/efficiency-certification.js']){
  assert(index.includes(`${asset}?v=${VERSION}`),`cache generation ${asset}`);
}
console.log('PASS: v4.7.15 filter bank fast path + availability snapshot reuse + stabilized DOM certification');

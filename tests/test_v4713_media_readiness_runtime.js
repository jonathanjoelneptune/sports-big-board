const fs=require('fs');
const assert=require('assert');
const VERSION=fs.readFileSync('VERSION','utf8').trim();
const efficiency=fs.readFileSync('architecture/efficiency-certification.js','utf8');
const availability=fs.readFileSync('architecture/score-card-availability-index.js','utf8');
const render=fs.readFileSync('architecture/render-pipeline.js','utf8');
const parts=VERSION.split('.').map(Number); assert.deepStrictEqual(parts.slice(0,2),[4,7]); assert(parts[2]>=13);
for(const token of ['mediaReadyP95Ms','mediaReadyMaxMs','mediaReadyTimeouts','function mediaReadinessSnapshot','function waitForMediaReadiness',"'MEDIA READINESS'",'MEDIA_READY_P95=','MEDIA_READY_COVERAGE=']){
  assert(efficiency.includes(token),token);
}
const probe=efficiency.slice(efficiency.indexOf('async function probeColdThinHistory'),efficiency.indexOf('function candidateFilters'));
assert(probe.includes("credentials:'omit'"));
assert(!probe.includes('X-SBB-Efficiency-Run'));
for(const token of ['knownMediaGames','knownMediaAssets','readyKnownMediaKeys','mediaReadyGames','mediaReadyComplete','knownDatabaseMedia:true','visibleMatch']){
  assert(availability.includes(token),token);
}
for(const token of ['availabilityKnownMediaGames','availabilityKnownMediaAssets','availabilityMediaReadyGames','availabilityMediaReadyComplete']){
  assert(render.includes(token),token);
}
console.log('PASS: v4.7.13 media-readiness certification + thin-probe preflight fix contracts');

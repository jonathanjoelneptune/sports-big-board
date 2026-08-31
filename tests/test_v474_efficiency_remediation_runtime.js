const fs=require('fs');
const assert=require('assert');

const VERSION=fs.readFileSync('VERSION','utf8').trim();
const parts=VERSION.split('.').map(Number);
const index=fs.readFileSync('index.html','utf8');
const broker=fs.readFileSync('architecture/request-broker.js','utf8');
const coordinator=fs.readFileSync('architecture/date-transition-coordinator.js','utf8');
const day=fs.readFileSync('architecture/day-state.js','utf8');
const efficiency=fs.readFileSync('architecture/efficiency-certification.js','utf8');

assert(parts[0]===4 && (parts[1]>7 || (parts[1]===7 && parts[2]>=4)));
assert(index.indexOf(`api-runtime.js?v=${VERSION}`) < index.indexOf(`architecture/request-broker.js?v=${VERSION}`));
assert(index.indexOf(`architecture/request-broker.js?v=${VERSION}`) < index.indexOf(`architecture/efficiency-certification.js?v=${VERSION}`));
assert(index.indexOf(`app.js?v=${VERSION}`) < index.indexOf(`architecture/day-state.js?v=${VERSION}`));
assert(index.indexOf(`architecture/day-state.js?v=${VERSION}`) < index.indexOf(`architecture/date-transition-coordinator.js?v=${VERSION}`));

assert(broker.includes('window.SBB_REQUEST_BROKER'));
assert(broker.includes('coalesced'));
assert(broker.includes('cache-hit'));
assert(broker.includes('superseded-date'));
assert(broker.includes('beginDate'));

assert(coordinator.includes('window.SBB_DATE_TRANSITIONS'));
assert(coordinator.includes('load:false'));
assert(coordinator.includes('scheduleEnrichment'));
assert(coordinator.includes('SBB_REQUEST_BROKER?.beginDate'));
assert(coordinator.includes('DAY_STATE'));

assert(!day.includes('new MutationObserver'));
assert(!day.includes('.observe(document.documentElement'));
assert(day.includes('operatorTimer'));

assert(efficiency.includes('sbb:request-broker'));
assert(efficiency.includes('slowestEndpoints'));
assert(efficiency.includes('networkPerDateMax'));
assert(efficiency.includes('supersededAborts'));
assert(!efficiency.includes('originalFetch = window.fetch.bind(window)'));

console.log(`PASS: ${VERSION} retains v4.7.4 request broker + date transition efficiency remediation`);

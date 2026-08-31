const fs=require('fs');
const assert=require('assert');

const VERSION=fs.readFileSync('VERSION','utf8').trim();
const parts=VERSION.split('.').map(Number);
const index=fs.readFileSync('index.html','utf8');
const nav=fs.readFileSync('architecture/navigation-ui.js','utf8');
const registry=fs.readFileSync('architecture/competition-registry-projection.js','utf8');
const efficiency=fs.readFileSync('architecture/efficiency-certification.js','utf8');
const cache=fs.readFileSync('architecture/card-build-cache.js','utf8');

assert(parts[0]===4 && (parts[1]>7 || (parts[1]===7 && parts[2]>=9)));
assert(index.includes(`architecture/navigation-ui.js?v=${VERSION}`));
assert(nav.includes('window.SBB_DATE_NAV_UI'));
assert(nav.includes('sbb-date-popover'));
assert(nav.includes('#sbbSpecialEventsMenu'));
assert(registry.includes('function normalizedType'));
assert(registry.includes('SPECIAL_EVENT'));
assert(efficiency.includes('function runHistoricalNavigationSweep'));
assert(efficiency.includes('historicalArrowStep'));
assert(efficiency.includes('historicalCalendarJump'));
assert(efficiency.includes('randomHistoricalDates'));
assert(efficiency.includes('thanksgiving'));
assert(cache.includes("'scoreGameLookupKeys'"));
assert(cache.includes("'scoreEventDate'"));
console.log(`PASS: ${VERSION} retains v4.7.9 special-event/calendar/deep-history baseline`);

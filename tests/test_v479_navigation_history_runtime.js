const fs=require('fs');
const assert=require('assert');

const VERSION=fs.readFileSync('VERSION','utf8').trim();
const index=fs.readFileSync('index.html','utf8');
const nav=fs.readFileSync('architecture/navigation-ui.js','utf8');
const registry=fs.readFileSync('architecture/competition-registry-projection.js','utf8');
const efficiency=fs.readFileSync('architecture/efficiency-certification.js','utf8');
const cache=fs.readFileSync('architecture/card-build-cache.js','utf8');

assert.strictEqual(VERSION,'4.7.9');
assert(index.includes(`architecture/navigation-ui.js?v=${VERSION}`));
assert(index.indexOf(`architecture/competition-registry-projection.js?v=${VERSION}`) <
       index.indexOf(`architecture/navigation-ui.js?v=${VERSION}`));

assert(nav.includes('window.SBB_DATE_NAV_UI'));
assert(nav.includes('sbb-date-popover'));
assert(nav.includes('sbb-calendar-grid'));
assert(nav.includes('scoreDatePicker'));
assert(nav.includes("closest?.('#topDateSelectBtn,#scoreDayIndicator')"));
assert(nav.includes('window.SBB_FRONTEND_REGISTRY?.select'));
assert(nav.includes('sbb-special-main-row-suppressed'));
assert(nav.includes('#sbbSpecialEventsMenu'));

assert(registry.includes('function normalizedType'));
assert(registry.includes('eventIcon'));
assert(registry.includes('SPECIAL_EVENT'));
assert(registry.includes('sbb-special-main-row-suppressed'));

assert(efficiency.includes('function runHistoricalNavigationSweep'));
assert(efficiency.includes('historicalArrowStep'));
assert(efficiency.includes('historicalCalendarJump'));
assert(efficiency.includes('randomHistoricalDates'));
assert(efficiency.includes('thanksgiving'));
assert(efficiency.includes('History nav p95'));
assert(efficiency.includes('HISTORICAL NAVIGATION'));
assert(efficiency.includes("const children=[...cells.children]"));

assert(cache.includes("'scoreGameLookupKeys'"));
assert(cache.includes("'scoreEventDate'"));

console.log('PASS: v4.7.9 special-events menu + themed calendar + deep-history navigation contracts');

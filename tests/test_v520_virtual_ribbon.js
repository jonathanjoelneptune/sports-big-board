'use strict';
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const src=fs.readFileSync(path.join(root,'architecture/virtual-ribbon-v520.js'),'utf8');
const index=fs.readFileSync(path.join(root,'index.html'),'utf8');

assert(src.includes("const VERSION='5.2.0'"));
assert(src.includes('const WINDOW_MIN=20'));
assert(src.includes('rows.slice(win.start,win.end)'),'large days must render a window, not all games');
assert(src.includes("className='sbb-vr-spacer sbb-vr-left'"));
assert(src.includes("className='sbb-vr-spacer sbb-vr-right'"));
assert(src.includes('memorySnapshots.get(date)'),'adjacent-date memory snapshot should paint synchronously');
assert(src.includes("caches.open(CACHE_NAME)"),'repeat visits should have persistent ribbon snapshot cache');
assert(src.includes('/api/ribbon-snapshot?date='),'browser must use server-prepared ribbon snapshots');
assert(src.includes('prefetchAround(date)'),'adjacent dates should prefetch');
assert(src.includes("readCachedSnapshot(d,{apply:false})"),'adjacent prefetch must not ingest/paint while user is interacting');
assert(src.includes("fetchSnapshot(d,{apply:false,timeoutMs:1800})"),'adjacent network prefetch must stay data-only');
assert(src.includes('sourceRowsFn=currentDate')===false); // ensure this isn't a malformed direct evaluation
assert(src.includes('baseRenderer(animate)'),'established card factory should build only mounted cards');
assert(src.includes('current.__sbbOriginal||current'),'virtual path must bypass legacy full-bank performance census');
assert(!src.includes("getElementsByTagName('*')"),'virtual path cannot census the entire page DOM');
assert(src.includes('mediaWarmDeferrals'),'media reconcile must yield during user interaction');
assert(src.includes('content-visibility:auto'),'offscreen long-page panels should be browser-skippable');
assert(index.includes('architecture/virtual-ribbon-v520.js?v=5.2.0'));
assert(index.indexOf('date-transition-coordinator.js?v=5.2.0') < index.indexOf('virtual-ribbon-v520.js?v=5.2.0'),'virtual ownership installs after the legacy coordinator/pipeline');
console.log('PASS v5.2.0 virtual ribbon / adjacent snapshot invariants');

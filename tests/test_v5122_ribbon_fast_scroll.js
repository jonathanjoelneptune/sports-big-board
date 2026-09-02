'use strict';
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const src=fs.readFileSync(path.join(root,'architecture/ribbon-fast-scroll-v5122.js'),'utf8');
const tennis=fs.readFileSync(path.join(root,'architecture/tennis-presentation.js'),'utf8');
const index=fs.readFileSync(path.join(root,'index.html'),'utf8');

assert(src.includes("const VERSION='5.1.22'"));
assert(src.includes("requestAnimationFrame"),'scroll writes must be frame-budgeted');
assert(src.includes("host.addEventListener('wheel',onWheel,{capture:true,passive:false})"),'wheel interceptor must precede legacy handler');
assert(src.includes("host.addEventListener('pointermove',onPointerMove,{capture:true,passive:false})"),'drag interceptor must precede legacy handler');
assert(src.includes('e.stopImmediatePropagation()'),'legacy synchronous movement handler must be suppressed');
assert(src.includes('state.pendingTarget'),'movement events should coalesce into one pending target');
assert(src.includes("scroll-behavior:auto!important"),'smooth-scroll contention must be disabled on the ribbon');
assert(src.includes('focusSuppressed'),'automatic focus scrolling must yield during direct user scrolling');

// The pointermove hot path must contain no geometry measurement. Metrics are read
// only outside movement callbacks and cached for the gesture/frame loop.
const move=src.slice(src.indexOf('function onPointerMove'),src.indexOf('function finishDrag'));
for(const forbidden of ['scrollWidth','clientWidth','getBoundingClientRect','getClientRects','offsetLeft','offsetWidth']){
  assert(!move.includes(forbidden),`pointermove geometry read returned: ${forbidden}`);
}

assert(index.indexOf('app.js?v=5.1.22') < index.indexOf('ribbon-fast-scroll-v5122.js?v=5.1.22'),'fast-scroll capture layer must load after legacy listeners exist');
assert(tennis.includes(".score-card:not([data-sbb-tennis-v5122])"),'tennis cards should be inspected only once per DOM card');
assert(tennis.includes("img.decoding='async'"),'flag decode should stay off the interaction frame');
assert(!tennis.includes("addEventListener('scroll'"),'tennis presentation must never own scroll callbacks');
console.log('PASS v5.1.22 frame-budgeted ribbon scrolling invariants');

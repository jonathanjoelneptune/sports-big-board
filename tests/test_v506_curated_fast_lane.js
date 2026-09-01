'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const root=path.resolve(__dirname,'..');
const VERSION=fs.readFileSync(path.join(root,'VERSION'),'utf8').trim();
const parts=VERSION.split('.').map(Number); assert(parts[0]>5 || (parts[0]===5 && (parts[1]>0 || (parts[1]===0 && parts[2]>=6))));
global.window=global;
vm.runInThisContext(fs.readFileSync(path.join(root,'architecture/curated-media-overrides.js'),'utf8'),{filename:'architecture/curated-media-overrides.js'});
const usc={competitionId:'CFB',eventId:'401864494',espnEventId:'401864494',date:'2026-08-29T20:30:00Z',awayTeam:{name:'San José State Spartans',abbreviation:'SJSU'},homeTeam:{name:'USC Trojans',abbreviation:'USC'}};
const curated=SBB_CURATED_MEDIA.itemsFor(usc);
assert.equal(curated.length,1);
assert.equal(curated[0].youtubeId,'-tDiPDHU2fs');
assert.equal(curated[0].__sbbCuratedOverride,true);

const app=fs.readFileSync(path.join(root,'app.js'),'utf8');
const cert=fs.readFileSync(path.join(root,'architecture/comprehensive-site-certification.js'),'utf8');
const slice=(from,to)=>app.slice(app.indexOf(from),app.indexOf(to,app.indexOf(from)));
const genericPlayable=slice('function scoreCardPlayableItems(match){','async function scoreCardPlayableItemsForIntent(match){');
const intentPlayable=slice('async function scoreCardPlayableItemsForIntent(match){','function scoreSelectionItemsForCandidate');
const genericSelection=slice('function scoreCardPlaybackSelection(match,items){','function scoreCardPrimaryItem');
const availability=slice('function scoreCardAvailability(match){','function silverRoundupKindLabel');
const click=slice('async function playGameHighlights','function gameLabel');

// v5.0.5 regression guard: curated assets may not be injected into the legacy
// resolver/alternate graph. The known-good correction must remain isolated.
assert(!genericPlayable.includes('SBB_CURATED_MEDIA'), 'generic score resolver must not consume curated override data');
assert(!intentPlayable.includes('SBB_CURATED_MEDIA'), 'cooperative generic planner must not consume curated override data');
assert(!genericSelection.includes('SBB_CURATED_MEDIA'), 'legacy ranking graph must not consume curated override data');

// Card rendering short-circuits on curated data before touching the generic graph.
assert(availability.includes('curatedFastLane:true'));
assert(availability.indexOf('SBB_CURATED_MEDIA?.itemsFor?.(match)') < availability.indexOf('scoreCardPlayableItems(match)'));
assert(availability.indexOf('if(curated.length)') < availability.indexOf('scoreCardPlayableItems(match)'));

// Click path establishes the curated fast lane, yields once, tunes the exact item,
// and only then hydrates generic fallback material during idle time.
assert(app.includes('function curatedScoreClickItems'), 'function curatedScoreClickItems');
for(const token of ['CURATED_FAST_LANE','curatedFastLane','PROGRAM=[...selectionItems]','TUNE_DISPATCHED'])assert(click.includes(token),token);
assert(app.includes('function handleCuratedPlaybackFailure'), 'function handleCuratedPlaybackFailure');
assert(app.includes('Automated media associations remain isolated'), 'curated failure must not re-enter automated graph');
assert(click.indexOf('CURATED_FAST_LANE') < click.indexOf('scoreCardPlayableItemsForIntent(match)'));
assert(!click.includes('scheduleCuratedFallbackHydration'), 'curated playback may not hydrate the automated graph during the active session');
assert(!app.includes('youtubeId:\'-tDiPDHU2fs\''),'physical override data belongs only in curated registry');

assert(/const VERSION='3\.[6-9]'/.test(cert));
assert(cert.includes("x.stage==='CURATED_FAST_LANE'"));
assert(cert.includes("fastLane=${x.fastLane?'YES':'NO'}"));
console.log('PASS: v5.0.6+ curated media is isolated from legacy graph and dispatched through fast lane');

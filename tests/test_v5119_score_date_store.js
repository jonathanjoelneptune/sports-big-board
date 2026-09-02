'use strict';
const fs=require('fs');const vm=require('vm');const assert=require('assert');const path=require('path');
const root=path.resolve(__dirname,'..');
const context={console,Date,setTimeout,clearTimeout};context.window=context;vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root,'architecture/score-date-store.js'),'utf8'),context,{filename:'score-date-store.js'});
const store=context.SBB_SCORE_DATE;assert(store,'ScoreDateStore installed');assert.equal(store.version,'1.1');assert.equal(store.architectureVersion,'1.3-v5119');
const date='2026-08-30',league='USOPEN-2026';
// Dynamic competition metadata comes from the canonical frontend registry projection.
context.SBB_FRONTEND_REGISTRY={snapshot:()=>({competitions:[{id:league,name:'2026 US Open',sportId:'tennis'}]})};
const rich={eventId:'match-1',canonicalEventId:'match-1',competitionId:league,sportId:'tennis',status:'FINAL',awayScore:2,homeScore:1,tennisRound:'Round 1',tennisRoundShort:'R1',awayTeam:{name:'Lucrezia Stefanini',rank:'54',aliases:['L. Stefanini']},homeTeam:{name:'Dayana Yastremska',rank:'31'},providerIds:{espn:'401'},presentation:{court:'17'},sets:[{away:6,home:3}]};
let rows=store.setMatches(date,league,[rich],{source:'DAY_STATE',authoritative:true});assert.equal(rows.length,1);
// Even if legacy app compatibility code stamped a dynamic row as generic sports, read-time registry projection restores canonical sport metadata.
store.setMatches('2026-08-31',league,[{eventId:'match-2',competitionId:league,competitionName:league,sportId:'sports',awayTeam:{name:'A'},homeTeam:{name:'B'}}],{source:'DAY_STATE',authoritative:true});
const projected=store.matches('2026-08-31',league)[0];assert.equal(projected.sportId,'tennis');assert.equal(projected.competitionName,'2026 US Open');assert.equal(projected.gameCenterProviderHint,'tennis');
// A thin/score-only transport must never become canonical truth.
store.setMatches(date,league,[{eventId:'match-1',status:'FINAL',awayScore:2,homeScore:1}],{source:'FAST',authoritative:true,scoreOnly:true});
rows=store.matches(date,league);assert.equal(rows[0].sportId,'tennis');assert.equal(rows[0].tennisRoundShort,'R1');assert.deepEqual(Array.from(rows[0].sets),[{away:6,home:3}]);
// Fresh canonical scores/status merge into the existing Event without stripping rich fields.
// Provider alias changes are reconciled by the stable canonical alias set.
store.setMatches(date,league,[{scoreEventId:'match-1',eventId:'provider-401',status:'FINAL',awayScore:2,homeScore:0,awayTeam:{name:'Lucrezia Stefanini'},homeTeam:{name:'Dayana Yastremska'},sets:[]}],{source:'DAY_STATE',authoritative:true});
rows=store.matches(date,league);assert.equal(rows.length,1);assert.equal(rows[0].homeScore,0);assert.equal(rows[0].tennisRoundShort,'R1');assert.equal(rows[0].providerIds.espn,'401');assert.equal(rows[0].sets.length,1);

// Media inventory is a separate read cache keyed by date/competition and score refreshes cannot erase it.
store.setMedia(date,league,[{assetKey:'yt:locked-usopen-highlight',eventId:'match-1',verifiedPlayable:true,mediaAuthorityLocked:true}]);
store.setMatches(date,league,[{scoreEventId:'match-1',status:'FINAL',awayScore:2,homeScore:0}],{source:'DAY_STATE',authoritative:true});
assert.equal(store.media(date,league).length,1);assert.equal(store.media(date,league)[0].assetKey,'yt:locked-usopen-highlight');
// A transient empty result cannot erase populated canonical inventory.
store.setMatches(date,league,[],{source:'TRANSIENT',authoritative:true});assert.equal(store.matches(date,league).length,1);
// Explicit confirmed-empty is the only destructive empty replacement.
store.setMatches(date,league,[],{source:'DAY_STATE',authoritative:true,confirmedEmpty:true});assert.equal(store.matches(date,league).length,0);
const diag=store.diagnostics();assert(diag.rejectedNonAuthoritative>=1);assert(diag.blockedEmptyReplacements>=1);assert(diag.mergedEvents>=1);
console.log('PASS v5.1.19 canonical ScoreDateStore invariants');

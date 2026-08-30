'use strict';
const fs=require('fs'), vm=require('vm'), path=require('path'), assert=require('assert');
const root=path.resolve(__dirname,'..');
const releaseVersion=fs.readFileSync(path.join(root,'VERSION'),'utf8').trim();
global.window=global;
for(const f of ['core-model.js','architecture/score-date-store.js','architecture/event-identity.js','architecture/media-scope.js','architecture/media-classifier.js','architecture/playback-transports.js','architecture/playback-readiness.js','architecture/provider-health.js','architecture/sport-media-policy.js','architecture/media-manifest.js','architecture/media-resolver.js','architecture/game-center-policy.js','architecture/selected-event-store.js','architecture/game-center-linescore.js','architecture/media-work-priorities.js','architecture/editorial-packages.js']){
  vm.runInThisContext(fs.readFileSync(path.join(root,f),'utf8'),{filename:f});
}
assert.equal(SBB_CORE.version,releaseVersion);
assert.match(releaseVersion,/^\d+\.\d+\.\d+$/);
const enabledCompetitionIds=SBB_CORE.enabledCompetitions().map(x=>x.id);
for(const id of ['MLB','NFL','CFB','NBA','NHL','EPL','MLS']){
  assert(enabledCompetitionIds.includes(id),`missing enabled competition ${id}`);
}
assert.equal(new Set(enabledCompetitionIds).size,enabledCompetitionIds.length);
assert(!enabledCompetitionIds.includes('SPORTS'));
assert.equal(SBB_CORE.COMPETITIONS.CFB.enabled,true);
assert.equal(SBB_CORE.COMPETITIONS.CFB.sportId,'american-football');
assert.equal(SBB_CORE.COMPETITIONS.CFB.selectionPolicy,'AP_TOP_25_EITHER_PARTICIPANT');
assert.equal(SBB_CORE.COMPETITIONS.CFB.rankingSnapshotPolicy,'IMMUTABLE_WEEKLY');
assert.equal(SBB_CORE.COMPETITIONS.MLS.enabled,true);
assert.equal(SBB_MEDIA_WORK.PRIORITY.VISIBLE_SCORE,'VISIBLE_SCORE');
assert.equal(SBB_EDITORIAL_PACKAGES.SERIES.MLB_TOP_PLAYS_DAILY.cadence,'daily');
assert.equal(SBB_EDITORIAL_PACKAGES.SERIES.NBA_TOP_PLAYS_NIGHTLY.cadence,'nightly');
assert.equal(SBB_EDITORIAL_PACKAGES.SERIES.NFL_TOP_PLAYS_WEEKLY.cadence,'weekly');
assert.equal(SBB_SCORE_DATE.version,'1.0');
assert.equal(SBB_GAME_CENTER_LINESCORE.version,'1.0');
const extraBoard={away:{score:8},home:{score:6},totals:{away:{runs:8},home:{runs:6}},innings:[
  {num:1,away:0,home:2},{num:2,away:0,home:3},{num:3,away:0,home:0},{num:4,away:3,home:0},{num:5,away:2,home:1},
  {num:6,away:0,home:0},{num:7,away:0,home:0},{num:8,away:1,home:0},{num:9,away:0,home:0},{num:10,away:'',home:''}
]};
const extraDisplay=SBB_GAME_CENTER_LINESCORE.reconcile(extraBoard,'MLB');
assert.equal(extraDisplay.find(x=>x.num===10).away,2);
assert.equal(extraDisplay.find(x=>x.num===10).home,'');
assert.equal(extraBoard.innings.find(x=>x.num===10).away,'');
const regulation=SBB_GAME_CENTER_LINESCORE.reconcile({totals:{away:{runs:3},home:{runs:2}},innings:[{num:9,away:'',home:''}]},'MLB');
assert.equal(regulation[0].away,'');
console.log('PASS MLB extra-inning linescore reconciliation');
const originalDateState=SBB_SCORE_DATE.snapshot();
SBB_SCORE_DATE.setBrowseDate('2026-01-18');
SBB_SCORE_DATE.setPlaybackDate('2026-01-18');
SBB_SCORE_DATE.setMatches('2026-01-18','NFL',[{id:'historical-nfl'}]);
SBB_SCORE_DATE.setMedia('2026-01-18','NFL',[{id:'historical-recap'}]);
assert.equal(SBB_SCORE_DATE.snapshot().browseDate,'2026-01-18');
assert.equal(SBB_SCORE_DATE.snapshot().playbackDate,'2026-01-18');
assert.equal(SBB_SCORE_DATE.allMatches('2026-01-18')[0].id,'historical-nfl');
assert.equal(SBB_SCORE_DATE.allMedia('2026-01-18')[0].id,'historical-recap');
SBB_SCORE_DATE.setBrowseDate(originalDateState.today);
SBB_SCORE_DATE.setPlaybackDate(originalDateState.today);
console.log('PASS independent browse/playback date store');

const mlbEvent=SBB_CORE.event({gamePk:824155,date:'2026-08-19T23:10:00Z',awayTeam:{abbreviation:'TOR'},homeTeam:{abbreviation:'TB'}},'MLB');
assert.equal(mlbEvent.eventId,'824155');
assert.equal(mlbEvent.competitionId,'MLB');
assert.equal(SBB_EVENT_IDENTITY.key(mlbEvent),'MLB:pk:824155');
assert(SBB_EVENT_IDENTITY.same(mlbEvent,{league:'MLB',gamePk:'824155'}));
assert(!SBB_EVENT_IDENTITY.same(mlbEvent,{league:'MLB',gamePk:'824156'}));

const extended={overview:true,title:'Official Full Game Highlights',durationSeconds:720,source:'MLB'};
const quick={overview:true,title:'Game Recap',durationSeconds:210,source:'MLB'};
const commentary={overview:true,title:'Postgame Recap and Analysis',durationSeconds:240,source:'ESPN'};
const clip={overview:false,programType:'reel',title:'Machado homers',durationSeconds:42,source:'MLB'};
assert.equal(SBB_MEDIA_CLASSIFIER.tier(extended),'extended');
assert.equal(SBB_MEDIA_CLASSIFIER.tier(quick),'green');
assert.equal(SBB_MEDIA_CLASSIFIER.tier(commentary),'gold');
assert.equal(SBB_MEDIA_CLASSIFIER.tier(clip),'blue');
const silverDaily=SBB_MEDIA_SCOPE.annotate({title:"NBA's Nightly Recap | January 26, 2026",youtubeId:'daily-recap',verifiedPlayable:true},{date:'2026-01-26',away:'Los Angeles Lakers',home:'Chicago Bulls'});
assert.equal(silverDaily.mediaScope,'DAY_LEAGUE');assert.equal(silverDaily.displayTier,'silver');
assert.equal(SBB_MEDIA_SCOPE.classify({title:'LAKERS at BULLS | FULL GAME HIGHLIGHTS'},{away:'Los Angeles Lakers',home:'Chicago Bulls'}),'GAME');
assert.equal(SBB_MEDIA_SCOPE.classify({title:'WARRIORS at TIMBERWOLVES | FULL GAME HIGHLIGHTS'},{away:'Los Angeles Lakers',home:'Chicago Bulls'}),'OTHER');
const preferenceEvent=SBB_CORE.event({eventId:'pref-1',date:'2026-03-27T02:00:00Z',awayTeam:{name:'Brooklyn Nets'},homeTeam:{name:'Los Angeles Lakers'}},'NBA');
SBB_MEDIA_MANIFEST.ingest(preferenceEvent,[
  {...clip,id:'pref-blue',eventId:'pref-1',youtubeId:'pref-blue',verifiedPlayable:true},
  {...extended,id:'pref-ext',eventId:'pref-1',youtubeId:'pref-ext',verifiedPlayable:true},
  {...quick,id:'pref-green',eventId:'pref-1',youtubeId:'pref-green',verifiedPlayable:true},
  {...commentary,id:'pref-gold',eventId:'pref-1',youtubeId:'pref-gold',verifiedPlayable:true}
]);
assert.equal(SBB_MEDIA_RESOLVER.resolveBest(preferenceEvent).primary.id,'pref-gold');
const scopeGuardEvent=SBB_CORE.event({eventId:'scope-guard',date:'2026-01-26T02:00:00Z',awayTeam:{name:'Los Angeles Lakers'},homeTeam:{name:'Chicago Bulls'}},'NBA');
SBB_MEDIA_MANIFEST.ingest(scopeGuardEvent,[
  {id:'daily-green',youtubeId:'daily-green',title:"NBA's Nightly Recap | January 26, 2026",durationSeconds:1500,overview:true,recapTier:'green',verifiedPlayable:true},
  {id:'game-purple',youtubeId:'game-purple',title:'LAKERS at BULLS | FULL GAME HIGHLIGHTS',durationSeconds:995,overview:true,recapTier:'extended',verifiedPlayable:true}
]);
assert.deepEqual(SBB_MEDIA_MANIFEST.list(scopeGuardEvent).map(x=>x.id),['game-purple']);
assert.equal(SBB_MEDIA_RESOLVER.resolveBest(scopeGuardEvent).primary.id,'game-purple');

let observed=null;
const unsub=SBB_SELECTED_EVENT.subscribe(x=>observed=x);
const selected=SBB_SELECTED_EVENT.select(mlbEvent,{source:'test',reason:'unit'});
assert.equal(selected.canonicalEventKey,'MLB:pk:824155');
assert.equal(observed.eventId,'824155');
unsub();
console.log('PASS browser architecture contracts');

const nflEvent=SBB_CORE.event({eventId:'401873285',date:'2026-08-21T02:00:00Z',awayTeam:{name:'San Francisco 49ers',abbreviation:'SF'},homeTeam:{name:'Los Angeles Chargers',abbreviation:'LAC'}},'NFL');
const nflQuick={id:'espn-quick',eventId:'401873285',mediaUrl:'https://cdn.espn.com/nfl-quick.mp4',durationSeconds:190,overview:true,verifiedPlayable:true,source:'ESPN',provider:'espn'};
const nflShort={id:'espn-short',eventId:'401873285',mediaUrl:'https://cdn.espn.com/nfl-short.mp4',durationSeconds:60,overview:true,verifiedPlayable:true,source:'ESPN',provider:'espn'};
const nflExtended={id:'official-extended',eventId:'401873285',externalUrl:'https://www.youtube.com/watch?v=official',durationSeconds:901,overview:true,externalOnly:true,verifiedPlayable:false,source:'NFL',provider:'nfl-feed',recapTier:'extended'};
SBB_MEDIA_MANIFEST.ingest(nflEvent,[nflShort,nflQuick]);
SBB_MEDIA_MANIFEST.ingest(nflEvent,[nflExtended],{external:true});
let nflResolved=SBB_MEDIA_RESOLVER.resolve(nflEvent,SBB_SPORT_MEDIA_POLICY.REQUEST.QUICK);
assert.equal(nflResolved.primary.id,'espn-quick');
assert.equal(SBB_PLAYBACK_TRANSPORTS.transportForAsset(nflQuick),'DIRECT_VIDEO');
assert.equal(SBB_MEDIA_MANIFEST.availability(nflEvent).green,true);
assert.equal(SBB_MEDIA_MANIFEST.availability(nflEvent).external.extended,true);
SBB_MEDIA_MANIFEST.markBuffering(nflEvent,nflQuick);
SBB_MEDIA_MANIFEST.markBuffering(nflEvent,nflQuick);
assert.equal(SBB_MEDIA_MANIFEST.get(nflEvent).assets.find(x=>x.id==='espn-quick').bufferingCount,2);
SBB_MEDIA_MANIFEST.markFailed(nflEvent,nflQuick,'test failure');
nflResolved=SBB_MEDIA_RESOLVER.resolve(nflEvent,SBB_SPORT_MEDIA_POLICY.REQUEST.QUICK);
assert.equal(nflResolved.primary.id,'espn-short');
assert.equal(SBB_SPORT_MEDIA_POLICY.policyFor(nflEvent).quick.target,210);
assert.equal(SBB_SPORT_MEDIA_POLICY.policyFor(nflEvent).extended.target,900);

const gcNormalized=SBB_GAME_CENTER_POLICY.normalize({event:{sportId:'american-football',participants:[{side:'away',id:'sf',name:'San Francisco 49ers',abbreviation:'SF'},{side:'home',id:'lac',name:'Los Angeles Chargers',abbreviation:'LAC'}]},playerStatSections:[{title:'San Francisco 49ers passing',columns:['C/ATT'],rows:[['6/13']]}]});
assert.equal(gcNormalized.playerStatSections[0].teamSide,'away');
assert.equal(gcNormalized.playerStatSections[0].category,'passing');
console.log('PASS provider-independent media resolver + Game Center policy');

// v4.2.2 Game Center browser handoff: two sequential score-provider aliases
// must follow two distinct resolved provider ids. The second selection can never
// inherit the first game's resolved id/cache entry.
const gcCalls=[];
global.fetch=async function(url){
  gcCalls.push(String(url));
  const u=String(url);
  const body=(obj)=>({ok:true,status:200,json:async()=>obj});
  if(u.includes('/MLB/hl-1/')) return {ok:true,status:202,json:async()=>({pending:true,resolvedEventId:'900001',retryAfterMs:1})};
  if(u.includes('/MLB/900001/')) return body({ok:true,resolvedEventId:'900001',data:{competitionId:'MLB',eventId:'900001',event:{competitionId:'MLB',eventId:'900001',status:'Final'},scoreboard:{away:{team:{name:'Chicago White Sox',abbreviation:'CHW'},score:1},home:{team:{name:'Chicago Cubs',abbreviation:'CHC'},score:2},status:'Final'},teamStats:[],playerStatSections:[],timeline:[],scoringPlays:[],live:false}});
  if(u.includes('/MLB/hl-2/')) return {ok:true,status:202,json:async()=>({pending:true,resolvedEventId:'900002',retryAfterMs:1})};
  if(u.includes('/MLB/900002/')) return body({ok:true,resolvedEventId:'900002',data:{competitionId:'MLB',eventId:'900002',event:{competitionId:'MLB',eventId:'900002',status:'Final'},scoreboard:{away:{team:{name:'Toronto Blue Jays',abbreviation:'TOR'},score:5},home:{team:{name:'Tampa Bay Rays',abbreviation:'TB'},score:1},status:'Final'},teamStats:[],playerStatSections:[],timeline:[],scoringPlays:[],live:false}});
  throw new Error('unexpected Game Center URL '+u);
};
vm.runInThisContext(fs.readFileSync(path.join(root,'architecture/game-center-contract.js'),'utf8'),{filename:'architecture/game-center-contract.js'});
(async()=>{
  const first={competitionId:'MLB',scoreEventId:'hl-1',eventId:'hl-1',__sbbDate:'2026-08-20',awayTeam:{name:'Chicago White Sox',abbreviation:'CHW'},homeTeam:{name:'Chicago Cubs',abbreviation:'CHC'}};
  const second={competitionId:'MLB',scoreEventId:'hl-2',eventId:'hl-2',__sbbDate:'2026-08-20',awayTeam:{name:'Toronto Blue Jays',abbreviation:'TOR'},homeTeam:{name:'Tampa Bay Rays',abbreviation:'TB'}};
  const a=await SBB_GAME_CENTER.get(first,{timeoutMs:1000});
  const b=await SBB_GAME_CENTER.get(second,{timeoutMs:1000});
  assert.equal(a.eventId,'900001'); assert.equal(b.eventId,'900002');
  assert(gcCalls.some(x=>x.includes('/MLB/900001/game-center')));
  assert(gcCalls.some(x=>x.includes('/MLB/900002/game-center')));
  assert.equal(SBB_GAME_CENTER.peek(first).eventId,'900001');
  assert.equal(SBB_GAME_CENTER.peek(second).eventId,'900002');
  console.log('PASS Game Center sequential alias handoff');
})().catch(err=>{console.error(err);process.exitCode=1;});

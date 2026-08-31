'use strict';
const assert=require('assert');
const fs=require('fs');
const path=require('path');
const vm=require('vm');
const ROOT=path.resolve(__dirname,'..');
const read=rel=>fs.readFileSync(path.join(ROOT,rel),'utf8');
const version=read('VERSION').trim();
const index=read('index.html');
const app=read('app.js');
const cert=read('architecture/comprehensive-site-certification.js');
const watchdog=read('architecture/playback-progress-watchdog.js');
const verify=read('VERIFY.sh');

const vp=version.split('.').map(Number);assert(vp[0]>4 || (vp[0]===4 && (vp[1]>8 || (vp[1]===8 && vp[2]>=1))));
assert(index.includes(`<title>Sports Big Board — v${version}</title>`));
assert(index.includes(`app.js?v=${version}`));
assert(index.includes(`architecture/playback-progress-watchdog.js?v=${version}`));
assert(index.includes(`architecture/comprehensive-site-certification.js?v=${version}`));

// Game Center authority belongs to the score event for the entire score-card
// session, including primary -> alternate/fallback media transitions.
for(const token of [
  'function scoreSessionGameCenterAuthority()',
  "session?.source!=='score'||!session.match",
  'score-session authority',
  'const scoreAuthority=scoreSessionGameCenterAuthority();',
  'if(scoreAuthority)return syncSelectedEvent(scoreAuthority',
]) assert(app.includes(token),`missing score-session Game Center authority token: ${token}`);

// A local non-advancing player may quarantine that attempt, but may not contribute
// to the global three-unique-assets engine reset counter.
for(const token of [
  'function playbackFailureIsLocalProgressStall',
  'function noteLocalPlaybackFailure',
  'systemicCounterSuppressed:true',
  "emitPlaybackEngine('local-progress-failure'",
  'if(playbackFailureIsLocalProgressStall(reason))',
]) assert(app.includes(token),`missing local progress containment token: ${token}`);
assert(!app.includes('transitionInFlight=false;TRANSIENT_UNPLAYABLE_MEDIA.clear();'),'engine reset must not clear recent transient quarantines');

// A legitimate systemic reset cannot strand the broadcast surface or race the
// score-card same-game fallback owner.
for(const token of [
  "recoveryWasScore=userPlaybackSession?.source==='score'",
  'Only expired entries are removed',
  "reason:'playback engine reset recovery'",
  'if(recoveryWasScore||!sportsBigBoardStarted||manualPauseRequested)return;',
]) assert(app.includes(token),`missing engine-reset recovery token: ${token}`);

// Comprehensive Certification must expose intermittent/race evidence even when
// the final media eventually plays.
assert(/const VERSION='(?:2\.[1-9]\d*|[3-9]\.\d+)'/.test(cert));
for(const token of [
  'waitForPlaybackQuiescence',
  'engineResetsDelta',
  'engineIncidentsDelta',
  'gameCenterOwned',
  'gameCenterOwnershipFailures',
  'engineResets=${p.engineResets||0}',
  'gcOwned=${x.gameCenterOwned===false',
]) assert(cert.includes(token),`missing v4.8.1 certification race evidence: ${token}`);

// The production watchdog explicitly classifies frozen-clock recovery so app.js
// can contain it locally instead of treating it as systemic engine corruption.
assert(watchdog.includes("const VERSION='1.1'"));
assert(watchdog.includes('LOCAL_NO_PROGRESS'));
let session={sessionId:'ps-stuck',selectionId:1,state:'playing',mediaKey:'yt:stuck',slot:'A',provider:'YOUTUBE',transport:'YOUTUBE_EMBED',invariant:'OK'};
let subscriber=null,recoveryError='',clock=0,now=0;
const timers=[];
const w={SBB_PLAYBACK_SESSION:{snapshot:()=>({...session}),subscribe:fn=>{subscriber=fn;fn({...session});return()=>{};}},dispatchEvent:()=>{}};w.window=w;
const sandbox={window:w,document:{hidden:false,getElementById:()=>null},console,performance:{now:()=>now},Date,Math,Number,String,Object,Array,Set,Map,JSON,RegExp,Promise,Error,CustomEvent:function(){},setTimeout:()=>0,clearTimeout:()=>{},setInterval:(fn,ms)=>{timers.push({fn,ms});return timers.length;},clearInterval:()=>{},players:{A:{getCurrentTime:()=>clock,getPlayerState:()=>1,playVideo:()=>{}}},manualPauseRequested:false,handlePlaybackFailure:(slot,err)=>{recoveryError=String(err.message||err);}};
vm.createContext(sandbox);vm.runInContext(watchdog,sandbox,{filename:'playback-progress-watchdog.js'});
const tick=timers.find(x=>x.ms===250).fn;
now=100;tick();now=8100;tick();
assert(recoveryError.includes('LOCAL_NO_PROGRESS'));
assert(recoveryError.includes('media clock did not advance'));

assert(verify.includes('node tests/test_v481_playback_ownership_recovery.js'));
for(const forbidden of ['401864494','USC_EVENT_FOUND','San José','San Jose']){
  assert(!cert.includes(forbidden),`comprehensive certification must remain game-agnostic: ${forbidden}`);
  assert(!watchdog.includes(forbidden),`watchdog must remain game-agnostic: ${forbidden}`);
}

console.log(`PASS: retained v4.8.1 score-session ownership + local-stall containment under v${version}`);

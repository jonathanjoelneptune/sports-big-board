'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const src=fs.readFileSync(path.join(__dirname,'..','architecture','playback-terminal.js'),'utf8');
let perf=1000,clock=1_000_000,currentMedia='youtube:stale',restoreCalls=0,resetCalls=0,markCalls=0,fallbackCalls=0;
const timers=[];
global.performance={now:()=>perf};Date.now=()=>clock;
Object.defineProperty(global,'navigator',{value:{clipboard:{writeText:async()=>{}}},configurable:true});
global.setInterval=()=>0;global.clearInterval=()=>{};global.setTimeout=(fn)=>{timers.push(fn);return timers.length;};global.clearTimeout=()=>{};
async function drainOne(){const fn=timers.shift();if(fn)await fn();await Promise.resolve();await Promise.resolve();}
global.window=global;global.addEventListener=()=>{};
global.document={body:{classList:{contains:()=>true},dataset:{sbbDev:'1'}},addEventListener:()=>{},getElementById:()=>null,querySelectorAll:()=>[]};
global.SBB_DEV_MODE={isEnabled:()=>true};global.SBB_PLAYBACK_SESSION={snapshot:()=>({})};global.SBB_PLAYBACK_READINESS={state:()=> 'PLAYBACK_READY',score:()=>99};
global.markRuntimeMediaFailed=(item,reason,opts)=>{markCalls++;assert(reason.includes('HTTP 410 stale historical media'));assert.equal(opts.providerFailure,false);return true;};
global.tryScoreMediaFallback=(item,reason,opts)=>{fallbackCalls++;assert.equal(opts.runtimeFailureAlreadyMarked,true);currentMedia='youtube:replacement';return true;};
global.SBB_DEV_TEST_HOOKS={
  playbackEngine:()=>({incidents:0,resets:resetCalls}),resourceMode:()=> 'balanced',currentMediaKey:()=>currentMedia,currentGameKey:()=> 'NFL:g1',currentIsFullRecap:()=>true,
  setResourceMode:async()=>true,start:()=>true,ensurePlaying:()=>true,programSize:()=>6,restoreMediaKey:async()=>{restoreCalls++;return true;},
  stressTuneNextGame:async()=>true,stressTuneNext:async()=>true,chaosDisruptStandby:()=>({}),forcePlaybackEngineReset:()=>{resetCalls++;return true;},
  invariant:()=> 'OK',scoreDate:()=> '2025-11-16',today:()=> '2026-08-27',setScoreDate:async()=>true
};
vm.runInThisContext(src,{filename:'playback-terminal.js'});
(async()=>{
  const T=SBB_PLAYBACK_TERMINAL;assert(await T.endurance.startRecovery(),'targeted recovery should start');
  T.ingest({sessionId:'bad1',eventKey:'NFL:match:g1',state:'failed',selectedAt:clock,mediaKey:'youtube:stale',league:'NFL',provider:'YOUTUBE',transport:'YOUTUBE_EMBED',title:'stale NFL recap',lastError:'no first frame'});
  await drainOne();await drainOne();
  let s=T.endurance.snapshot();assert.equal(s.retryAttempts,1);assert.equal(restoreCalls,1);assert.equal(resetCalls,0);assert.equal(s.staleMedia,0);assert.equal(s.status,'RUNNING');
  clock+=1000;perf+=1000;
  T.ingest({sessionId:'bad2',eventKey:'NFL:match:g1',state:'failed',selectedAt:clock,mediaKey:'youtube:stale',league:'NFL',provider:'YOUTUBE',transport:'YOUTUBE_EMBED',title:'stale NFL recap',lastError:'no first frame'});
  await drainOne();await drainOne();
  s=T.endurance.snapshot();
  assert.equal(s.status,'RUNNING','two failures of one historical asset should quarantine, not fail certification');
  assert.equal(s.staleMedia,1);assert.equal(s.assetBad,1);assert.equal(markCalls,1);assert.equal(fallbackCalls,1);assert.equal(s.fallbacks,1);assert.equal(s.noFrameStreak,0);assert.equal(s.unrecoveredBlanks,0);
  clock+=500;perf+=500;
  T.ingest({sessionId:'replacement',eventKey:'NFL:match:g1',state:'playing',selectedAt:clock,firstFrameAt:clock,firstFrameMs:600,mediaKey:'youtube:replacement',league:'NFL',provider:'YOUTUBE',transport:'YOUTUBE_EMBED',title:'replacement NFL recap'});
  s=T.endurance.snapshot();assert.equal(s.fallbackSuccesses,1);assert.equal(s.successfulStarts,1);assert.equal(s.status,'RUNNING');
  console.log('PASS: v4.4.6 quarantines stale historical media and recovers without misclassifying player health');
})().catch(e=>{console.error(e);process.exit(1)});

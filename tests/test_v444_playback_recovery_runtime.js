'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const src=fs.readFileSync(path.join(__dirname,'..','architecture','playback-terminal.js'),'utf8');
let perf=1000,clock=1_000_000,currentMedia='m1',restoreCalls=0,resetCalls=0;
global.performance={now:()=>perf};Date.now=()=>clock;
Object.defineProperty(global,'navigator',{value:{clipboard:{writeText:async()=>{}}},configurable:true});
global.setInterval=()=>0;global.clearInterval=()=>{};global.setTimeout=(fn)=>{fn();return 0;};global.clearTimeout=()=>{};
global.window=global;global.addEventListener=()=>{};
global.document={body:{classList:{contains:()=>true},dataset:{sbbDev:'1'}},addEventListener:()=>{},getElementById:()=>null,querySelectorAll:()=>[]};
global.SBB_DEV_MODE={isEnabled:()=>true};global.SBB_PLAYBACK_SESSION={snapshot:()=>({})};global.SBB_PLAYBACK_READINESS={state:()=> 'PLAYBACK_READY',score:()=>99};
global.SBB_DEV_TEST_HOOKS={
  playbackEngine:()=>({incidents:0,resets:resetCalls}),resourceMode:()=> 'balanced',currentMediaKey:()=>currentMedia,currentGameKey:()=> 'g1',currentIsFullRecap:()=>true,
  setResourceMode:async()=>true,start:()=>true,ensurePlaying:()=>true,programSize:()=>3,restoreMediaKey:async()=>{restoreCalls++;return true;},
  stressTuneNextGame:async()=>true,stressTuneNext:async()=>true,chaosDisruptStandby:()=>({}),forcePlaybackEngineReset:()=>{resetCalls++;return true;},
  invariant:()=> 'OK',scoreDate:()=> '2026-08-27',today:()=> '2026-08-27',setScoreDate:async()=>true
};
vm.runInThisContext(src,{filename:'playback-terminal.js'});
(async()=>{
  const T=SBB_PLAYBACK_TERMINAL;assert(await T.endurance.start(),'endurance should start in Dev Mode');
  T.ingest({sessionId:'f1',eventKey:'MLB:g1',state:'failed',selectedAt:clock,mediaKey:'m1',league:'MLB',provider:'YOUTUBE',transport:'YOUTUBE_EMBED',title:'bad startup',lastError:'timeout'});
  await Promise.resolve();await Promise.resolve();
  let s=T.endurance.snapshot();assert.equal(s.retryAttempts,1);assert.equal(restoreCalls,1);
  assert.equal(resetCalls,0,'one stale-asset retry must not reset the whole playback engine');assert.equal(s.status,'RUNNING');
  clock+=1000;perf+=1000;T.ingest({sessionId:'ok1',eventKey:'MLB:g1',state:'playing',selectedAt:clock,firstFrameAt:clock,firstFrameMs:500,mediaKey:'m1',league:'MLB',provider:'YOUTUBE',transport:'YOUTUBE_EMBED',title:'recovered recap'});
  s=T.endurance.snapshot();assert.equal(s.retrySuccesses,1);assert.equal(s.successfulStarts,1);assert.equal(s.uniqueMedia,1);assert.equal(s.noFrameStreak,0);
  clock+=1000;perf+=1000;T.ingest({sessionId:'dup',eventKey:'MLB:g2',state:'playing',selectedAt:clock,firstFrameAt:clock,firstFrameMs:400,mediaKey:'m1',league:'MLB',provider:'YOUTUBE',transport:'YOUTUBE_EMBED',title:'duplicate media'});
  s=T.endurance.snapshot();assert.equal(s.status,'FAIL');assert(s.reason.includes('REPEATED_MEDIA'));
  console.log('PASS: v4.4.6 keeps v4.4.4 retry/no-repeat guard without per-asset engine reset');
})().catch(e=>{console.error(e);process.exit(1)});

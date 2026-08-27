'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const src=fs.readFileSync(path.join(__dirname,'..','architecture','playback-terminal.js'),'utf8');
let perf=1000,clock=1_000_000,currentMedia='m1';
const intervals=[],timeouts=[];let domReady=null;
global.performance={now:()=>perf};Date.now=()=>clock;
Object.defineProperty(global,'navigator',{value:{clipboard:{writeText:async()=>{}}},configurable:true});
global.setInterval=(fn)=>{intervals.push(fn);return intervals.length;};global.clearInterval=()=>{};
global.setTimeout=(fn)=>{timeouts.push(fn);return timeouts.length;};global.clearTimeout=()=>{};
global.window=global;global.addEventListener=()=>{};
const card={
  disabled:false,dataset:{sbbGameKey:'NFL:g2'},textContent:'Seahawks at Titans',className:'score-card league-nfl has-highlights highlight-recap',
  classList:{contains:n=>n==='highlight-recap'},__sbbMatch:{competitionId:'NFL',id:'g2'},click:()=>{}
};
global.document={body:{classList:{contains:()=>true},dataset:{sbbDev:'1'}},addEventListener:(n,fn)=>{if(n==='DOMContentLoaded')domReady=fn;},getElementById:()=>null,querySelectorAll:()=>[card]};
global.scoreCardAvailability=()=>({primary:{mediaUrl:'https://cdn.example/new.mp4'},items:[]});
global.playbackItemKey=()=> 'm2';
global.SBB_DEV_MODE={isEnabled:()=>true};global.SBB_PLAYBACK_SESSION={snapshot:()=>({})};global.SBB_PLAYBACK_READINESS={state:()=> 'PLAYBACK_READY',score:()=>99};
global.SBB_DEV_TEST_HOOKS={
  playbackEngine:()=>({incidents:0,resets:0}),resourceMode:()=> 'balanced',currentMediaKey:()=>currentMedia,currentGameKey:()=> 'NFL:g2',currentIsFullRecap:()=>true,
  setResourceMode:async()=>true,start:()=>true,ensurePlaying:()=>true,programSize:()=>4,restoreMediaKey:async()=>true,
  stressTuneNextGame:async()=>true,stressTuneNext:async()=>true,chaosDisruptStandby:()=>({}),forcePlaybackEngineReset:()=>true,
  invariant:()=> 'OK',scoreDate:()=> '2026-08-27',today:()=> '2026-08-27',setScoreDate:async()=>true
};
vm.runInThisContext(src,{filename:'playback-terminal.js'});if(domReady)domReady();
(async()=>{
  const T=SBB_PLAYBACK_TERMINAL;assert(await T.endurance.start(),'endurance should start');
  T.ingest({sessionId:'initial',eventKey:'MLB:g1',state:'playing',selectedAt:clock,firstFrameAt:clock,firstFrameMs:300,mediaKey:'m1',league:'MLB',provider:'DIRECT_VIDEO',transport:'DIRECT_VIDEO',title:'initial unique media'});
  let s=T.endurance.snapshot();assert.equal(s.successfulStarts,1);assert.equal(s.status,'RUNNING');
  clock+=21_000;perf+=21_000;
  assert(intervals.length>=2,'endurance interval should be installed');intervals[1]();
  await Promise.resolve();await Promise.resolve();await Promise.resolve();
  s=T.endurance.snapshot();assert.equal(s.transitions,1,'stress driver should click one new ribbon candidate');
  // The card preflight predicted m2, but the runtime resolver unexpectedly lands on already-seen m1.
  currentMedia='m1';clock+=500;perf+=500;
  T.ingest({sessionId:'resolved-duplicate',eventKey:'NFL:g2',state:'playing',selectedAt:clock,firstFrameAt:clock,firstFrameMs:250,mediaKey:'m1',league:'NFL',provider:'ESPN',transport:'DIRECT_VIDEO',title:'runtime duplicate candidate'});
  s=T.endurance.snapshot();
  assert.equal(s.status,'RUNNING','stress-selected duplicate must not be misclassified as a product failure');
  assert.equal(s.duplicateCandidateRejects,1);
  assert.equal(s.repeatViolations,0);
  assert.equal(s.successfulStarts,1,'rejected duplicate must not count as a successful unique start');
  assert(timeouts.length>=1,'duplicate replacement should be queued immediately');
  console.log('PASS: v4.4.5 rejects a stress-selected duplicate candidate without failing endurance');
})().catch(e=>{console.error(e);process.exit(1)});

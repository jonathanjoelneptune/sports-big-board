'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const src=fs.readFileSync(path.join(__dirname,'..','architecture/playback-terminal.js'),'utf8');
let perf=1000,clock=1_000_000,currentMedia='';
global.performance={now:()=>perf};Date.now=()=>clock;
Object.defineProperty(global,'navigator',{value:{clipboard:{writeText:async()=>{}}},configurable:true});
global.setInterval=()=>0;global.clearInterval=()=>{};global.setTimeout=(fn)=>{fn();return 0;};global.clearTimeout=()=>{};
const listeners={};global.window=global;global.addEventListener=(n,fn)=>listeners[n]=fn;global.dispatchEvent=()=>{};
global.document={body:{classList:{contains:n=>n==='dev-mode'},dataset:{sbbDev:'1'}},addEventListener:()=>{},getElementById:()=>null};
global.SBB_DEV_MODE={isEnabled:()=>true};
global.SBB_PLAYBACK_READINESS={state:()=> 'PLAYBACK_READY',score:()=>99};
global.SBB_PLAYBACK_SESSION={snapshot:()=>({})};
global.SBB_DEV_TEST_HOOKS={
  playbackEngine:()=>({incidents:0,resets:0}),resourceMode:()=> 'balanced',currentMediaKey:()=>currentMedia,currentGameKey:()=> 'game:1',currentIsFullRecap:()=>true,
  setResourceMode:async()=> 'playback',start:()=>true,ensurePlaying:()=>true,programSize:()=>3,restoreMediaKey:async()=>true,
  stressTuneNextGame:async()=>true,stressTuneNext:async()=>true,chaosDisruptStandby:()=>({}),forcePlaybackEngineReset:()=>true,invariant:()=> 'OK',scoreDate:()=> '2026-08-27'
};
vm.runInThisContext(src,{filename:'playback-terminal.js'});
(async()=>{
  const T=SBB_PLAYBACK_TERMINAL;assert(await T.endurance.start(),'endurance should start in Dev Mode');
  currentMedia='youtube:short';T.ingest({sessionId:'r1',selectionId:1,eventKey:'MLB:1',state:'playing',selectedAt:clock,firstFrameAt:clock,firstFrameMs:450,league:'MLB',provider:'YOUTUBE',transport:'YOUTUBE_EMBED',mediaKey:currentMedia,title:'Quick recap'});
  let s=T.endurance.snapshot();assert.equal(s.status,'RUNNING');assert.equal(s.successfulStarts,1);
  clock+=5000;perf+=5000;currentMedia='youtube:extended';T.ingest({sessionId:'r2',selectionId:2,eventKey:'MLB:1',state:'playing',selectedAt:clock,firstFrameAt:clock,firstFrameMs:600,league:'MLB',provider:'YOUTUBE',transport:'YOUTUBE_EMBED',mediaKey:currentMedia,title:'Extended recap'});
  s=T.endurance.snapshot();assert.equal(s.status,'FAIL');assert.equal(s.duplicateRecaps,1);assert(s.reason.includes('DUPLICATE_GAME_RECAP'));
  console.log('PASS: v4.4.3 endurance runtime fails a different consecutive recap for the same canonical game');
})().catch(err=>{console.error(err);process.exit(1);});

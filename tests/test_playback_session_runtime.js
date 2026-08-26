'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
global.window=global;global.performance={now:(()=>{let n=1000;return()=>n+=25;})()};
global.CustomEvent=function(type,opts){this.type=type;this.detail=opts?.detail;};
global.dispatchEvent=()=>{};
const telemetry=[];
global.fetch=async(url,opts={})=>{
  if(String(url).includes('/api/playback/telemetry')){
    try{telemetry.push(JSON.parse(opts.body||'{}'));}catch(_){telemetry.push({});}
  }
  return {ok:true,json:async()=>({ok:true})};
};
vm.runInThisContext(fs.readFileSync(path.join(root,'architecture/playback-session.js'),'utf8'),{filename:'playback-session.js'});

(async()=>{
  assert.equal(SBB_PLAYBACK_SESSION.version,'1.0');
  SBB_PLAYBACK_SESSION.select({eventKey:'MLB:1',mediaKey:'m1',clipKey:'m1',transport:'DIRECT_VIDEO',slot:'A',sourceExternalUrl:'https://example.com/video.mp4'});
  let s=SBB_PLAYBACK_SESSION.snapshot();
  const firstSession=s.sessionId;
  assert.equal(s.state,'selected');assert.equal(s.eventKey,'MLB:1');
  SBB_PLAYBACK_SESSION.transition('starting');
  SBB_PLAYBACK_SESSION.transition('playing');
  s=SBB_PLAYBACK_SESSION.snapshot();assert.equal(s.state,'playing');assert(s.firstFrameMs>=0);
  // Late path metadata must not be lost just because PLAYING already recorded first frame.
  SBB_PLAYBACK_SESSION.markFirstFrame({transport:'HYBRID_CHUNK',sourceUrl:'/api/media/native?id=1'});
  s=SBB_PLAYBACK_SESSION.snapshot();assert.equal(s.transport,'HYBRID_CHUNK');assert.equal(s.sourceUrl,'/api/media/native?id=1');
  SBB_PLAYBACK_SESSION.setAudible('video','A',true);assert.equal(SBB_PLAYBACK_SESSION.snapshot().invariant,'OK');
  SBB_PLAYBACK_SESSION.setAudible('video','B',true);assert.match(SBB_PLAYBACK_SESSION.snapshot().invariant,/ERROR: VIDEO AUDIO A\+B/);
  SBB_PLAYBACK_SESSION.setAudible('video','A',false);assert.equal(SBB_PLAYBACK_SESSION.snapshot().invariant,'OK');
  SBB_PLAYBACK_SESSION.transition('buffering');
  SBB_PLAYBACK_SESSION.transition('playing');
  s=SBB_PLAYBACK_SESSION.snapshot();assert.equal(s.stallCount,1);assert(s.stallTotalMs>0);
  SBB_PLAYBACK_SESSION.fail(new Error('boom'));
  s=SBB_PLAYBACK_SESSION.snapshot();assert.equal(s.state,'failed');assert.equal(s.failureCount,1);assert.equal(s.lastError,'boom');

  // Selecting the same media again is a fresh tune attempt, not continuation of stale metrics.
  SBB_PLAYBACK_SESSION.select({eventKey:'MLB:1',mediaKey:'m1',clipKey:'m1',transport:'DIRECT_VIDEO',slot:'B'});
  s=SBB_PLAYBACK_SESSION.snapshot();
  assert.notEqual(s.sessionId,firstSession);
  assert.equal(s.state,'selected');assert.equal(s.firstFrameAt,0);assert.equal(s.stallCount,0);assert.equal(s.failureCount,0);

  // Let the independent telemetry timers flush, then verify that each event kept
  // the snapshot it had when scheduled rather than being overwritten by later state.
  await new Promise(r=>setTimeout(r,260));
  const events=telemetry.map(x=>x.event);
  for(const required of ['selection','first-frame','first-frame-meta','stall','stall-end','failure']){
    assert(events.includes(required),`missing telemetry event ${required}: ${events.join(',')}`);
  }
  const firstSelection=telemetry.find(x=>x.event==='selection');
  const firstFrame=telemetry.find(x=>x.event==='first-frame');
  const stall=telemetry.find(x=>x.event==='stall');
  const stallEnd=telemetry.find(x=>x.event==='stall-end');
  const failure=telemetry.find(x=>x.event==='failure');
  assert.equal(firstSelection.session.state,'selected');
  assert.equal(firstFrame.session.state,'playing');
  assert.equal(stall.session.state,'buffering');
  assert.equal(stallEnd.session.state,'playing');
  assert.equal(failure.session.state,'failed');
  assert.equal(firstSelection.session.sessionId,firstSession);
  console.log('PASS v4.2 playback-session runtime authority + ordered telemetry');
})().catch(err=>{console.error(err);process.exitCode=1;});

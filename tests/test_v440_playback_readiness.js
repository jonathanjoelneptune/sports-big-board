'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'architecture','playback-readiness.js'),'utf8');
const data=new Map(),listeners={};
global.localStorage={getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,String(v))};
global.fetch=async()=>({ok:true});
global.window=global;
global.addEventListener=(n,fn)=>{listeners[n]=fn;};
global.SBB_PLAYBACK_TRANSPORTS={
  playbackKey:a=>a.mediaKey||(a.youtubeId?`youtube:${a.youtubeId}`:a.mediaUrl?`direct:${a.mediaUrl}`:''),
  transportForAsset:a=>a.youtubeId?'YOUTUBE_EMBED':a.mediaUrl?'DIRECT_VIDEO':'UNSUPPORTED'
};
vm.runInThisContext(source,{filename:'playback-readiness.js'});
const R=SBB_PLAYBACK_READINESS;
assert(/^1\./.test(R.version),'readiness v1 contract should remain backward compatible');
const nfl={mediaKey:'direct:https://x.test/nfl.mp4',competitionId:'NFL',provider:'DIRECT_VIDEO',mediaUrl:'https://x.test/nfl.mp4'};
assert.equal(R.state(nfl),'DISCOVERED');
R.noteHotReady(nfl,300);
assert.equal(R.state(nfl),'PLAYBACK_READY','real warm progress should make asset playback-ready');
assert(R.rankBonus(nfl)>0);
const bad={mediaKey:'direct:https://x.test/bad.mp4',competitionId:'NBA',mediaUrl:'https://x.test/bad.mp4'};
R.noteFailure(bad,'one');
assert.notEqual(R.state(bad),'QUARANTINED','one failure must not poison asset');
R.noteFailure(bad,'two');R.noteFailure(bad,'three');
assert.equal(R.state(bad),'QUARANTINED','repeated independent failures should quarantine asset');
assert.equal(R.eligible(bad),false);
const epl={mediaKey:'youtube:abcdefghijk',competitionId:'EPL',youtubeId:'abcdefghijk',provider:'YOUTUBE'};
R.noteHotReady(epl,650);assert.equal(R.state(epl),'PLAYBACK_READY');
console.log('PASS: v4.4.x cross-sport playback readiness + quarantine semantics');

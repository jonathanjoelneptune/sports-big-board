'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const current={id:'purple-row',youtubeId:'sameMedia',durationSeconds:600};
const duplicateQuick={id:'quick-row',youtubeId:'sameMedia',durationSeconds:0,mediaObjective:'QUICK'};
const realQuick={id:'real-quick',youtubeId:'differentMedia',durationSeconds:180,mediaObjective:'QUICK'};
let feed='';
const ctx={console,window:null,currentIndex:0,
  SBB_PLAYBACK_TRANSPORTS:{playbackKey:x=>x.youtubeId?`youtube:${x.youtubeId}`:`id:${x.id}`},
  SBB_MEDIA_CLASSIFIER:{tier:x=>x===current?'extended':'green'},
  recapAlternatesFor:()=>[duplicateQuick,realQuick],
  recapTargetForTier:()=>duplicateQuick,
  switchRecapVersion:()=>{throw new Error('legacy switch must not be used with same physical target')},
  clip:()=>current,overviewQuality:()=>1,sourceQuality:()=>1,setFeedNote:x=>feed=x
};ctx.window=ctx;
vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(root,'architecture/recap-identity-guard.js'),'utf8'),ctx);
const target=ctx.recapTargetForTier(current,'green');
assert.equal(target.youtubeId,'differentMedia','same physical media must be skipped in favor of a real alternate');
assert.equal(ctx.SBB_RECAP_IDENTITY_GUARD.physicalKey(current),'youtube:sameMedia');
console.log('PASS: v4.4.8 recap-version switch requires distinct physical media');

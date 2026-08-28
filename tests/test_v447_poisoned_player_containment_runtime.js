'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'architecture/poisoned-media-containment.js'),'utf8');
assert(!source.includes('new MutationObserver('),'containment must not install a global src MutationObserver');
assert(!source.includes('SBB_MEDIA_INTELLIGENCE'),'containment must remain independent of Media Intelligence');

class FakeMedia {
  constructor(){this._src='';this.currentSrc='';this.attrs={};this.dataset={};this.pauseCalls=0;this.loadCalls=0;}
  get src(){return this._src;}
  set src(v){this._src=String(v||'');this.currentSrc=this._src;}
  setAttribute(k,v){this.attrs[k]=String(v);if(k==='src'){this._src=String(v);this.currentSrc=this._src;}}
  getAttribute(k){return k==='src'?this._src:(this.attrs[k]||'');}
  removeAttribute(k){if(k==='src'){this._src='';this.currentSrc='';}delete this.attrs[k];}
  pause(){this.pauseCalls++;}
  load(){this.loadCalls++;}
  play(){return Promise.resolve();}
}
class FakePlayer {
  constructor(){this.loaded=[];this.stops=0;this.clears=0;}
  loadVideoById(v){this.loaded.push(typeof v==='object'?v.videoId:v);}
  cueVideoById(v){this.loaded.push(typeof v==='object'?v.videoId:v);}
  stopVideo(){this.stops++;}
  clearVideo(){this.clears++;}
}
let sessionListener=null;
const videos=[],iframes=[];
const context={
  console,URL,Promise,Set,Map,Object,Array,String,Number,Error,Date,JSON,
  HTMLMediaElement:FakeMedia,
  document:{
    baseURI:'https://board.test/',
    querySelectorAll:(sel)=>sel==='video'?videos:(sel==='iframe'?iframes:[]),
  },
  location:{href:'https://board.test/'},
  YT:{Player:FakePlayer},
  SBB_PLAYBACK_SESSION:{subscribe(fn){sessionListener=fn;}},
  SBB_PLAYBACK_TRANSPORTS:{playbackKey(asset){
    if(asset?.youtubeId)return `youtube:${asset.youtubeId}`;
    if(asset?.mediaUrl)return `direct:${asset.mediaUrl}`;
    return asset?.mediaKey||'unsupported';
  }},
  dispatchEvent(){},
  CustomEvent:function(type,init){this.type=type;this.detail=init?.detail;},
  setTimeout:(fn)=>{fn();return 1;},clearTimeout(){},
  setInterval:()=>0,clearInterval(){},
};
context.window=context;
vm.createContext(context);vm.runInContext(source,context,{filename:'poisoned-media-containment.js'});
const api=context.SBB_POISON_CONTAINMENT;
assert(api,'containment API must install');
assert.strictEqual(context.SBB_MEDIA_INTELLIGENCE,undefined,'Media Intelligence must not be recreated');

const bad='https://cdn.test/poison.mp4';
const video=new FakeMedia();videos.push(video);video.src=bad;
assert.equal(video.src,bad);
assert(api.quarantine({mediaUrl:bad},'HTTP 410 gone'),'explicit quarantine should succeed');
assert.equal(video.src,'','quarantine must remove an already-loading poisoned native src');
assert(video.pauseCalls>=1&&video.loadCalls>=1,'quarantine must pause and reload native element to abort request');

const before=api.snapshot().preloadBlocks;
video.src=bad;
assert.equal(video.src,'','blocked native URL must be rejected before assignment');
assert(api.snapshot().preloadBlocks>before,'pre-assignment block telemetry must increment');

const player=new context.YT.Player();
api.quarantine({youtubeId:'poisonYT123'},'YouTube error 150');
player.loadVideoById('poisonYT123');
assert.equal(player.loaded.length,0,'blocked YouTube ID must not reach loadVideoById');
assert(player.stops>=1&&player.clears>=1,'blocked YouTube tune must locally stop/clear player');

assert(sessionListener,'playback-session failure subscription must install');
sessionListener({state:'failed',lastError:'HTTP 410 stale historical media',mediaKey:'direct:https://cdn.test/session-bad.mp4',sourceUrl:'https://cdn.test/session-bad.mp4'});
assert(api.isQuarantined('direct:https://cdn.test/session-bad.mp4'),'hard playback failure should quarantine asset');

const snap=api.snapshot();
assert.equal(snap.activeBlockedLoads,0,'contained poisoned media must leave zero active blocked loads');
assert.equal(snap.orphanedLoads,0,'contained poisoned media must leave zero orphaned loads');
console.log('PASS: v4.4.7 asset-local poisoned-player containment');

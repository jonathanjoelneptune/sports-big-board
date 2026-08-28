'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const src=fs.readFileSync(path.join(__dirname,'..','architecture','media-intelligence.js'),'utf8');
class FakeMedia{
  constructor(){this._src='';this.paused=true;this.volume=.2;this.muted=false;this.dataset={};this.loadCalls=0;this.pauseCalls=0;}
  get src(){return this._src;} set src(v){this._src=String(v||'');}
  get currentSrc(){return this._src;}
  setAttribute(n,v){if(String(n).toLowerCase()==='src')this._src=String(v||'');}
  getAttribute(n){return String(n).toLowerCase()==='src'?this._src:'';}
  removeAttribute(n){if(String(n).toLowerCase()==='src')this._src='';}
  load(){this.loadCalls++;}
  pause(){this.paused=true;this.pauseCalls++;}
  play(){this.paused=false;return Promise.resolve();}
}
global.window=global;global.HTMLMediaElement=FakeMedia;global.location={href:'https://example.test/',origin:'https://example.test'};
global.CustomEvent=class{constructor(type,opts){this.type=type;this.detail=opts?.detail;}};global.dispatchEvent=()=>{};
global.setInterval=()=>0;global.clearInterval=()=>{};global.setTimeout=(fn)=>{fn();return 0;};
global.MutationObserver=class{observe(){}};
const media=[];global.document={baseURI:'https://example.test/',documentElement:{},body:{setAttribute:()=>{}},querySelectorAll:(q)=>q.includes('video')?media:[],};
global.SBB_PLAYBACK_TRANSPORTS={playbackKey:a=>a?.youtubeId?`youtube:${a.youtubeId}`:(a?.mediaUrl?`direct:${a.mediaUrl}`:String(a?.mediaKey||''))};
let sessionListener=null,manifestListener=null;
global.SBB_PLAYBACK_SESSION={subscribe:fn=>{sessionListener=fn;fn({state:'idle'});return()=>{};},setAudible:()=>{}};
global.SBB_MEDIA_MANIFEST={subscribe:fn=>{manifestListener=fn;return()=>{};}};
const soundtrack=new FakeMedia();soundtrack.src='https://example.test/site-song.mp3';soundtrack.paused=false;
global.__SBB_SOUNDTRACK_SINGLETON__={audio:soundtrack};
vm.runInThisContext(src,{filename:'media-intelligence.js'});
const M=SBB_MEDIA_INTELLIGENCE;
M.register({mediaUrl:'https://cdn.test/no-music.mp4',musicStatus:'NO_MUSIC',musicConflict:false,musicConfidence:.95});
sessionListener({state:'playing',firstFrameAt:1,mediaKey:'direct:https://cdn.test/no-music.mp4'});
assert.equal(soundtrack.muted,false,'NO_MUSIC clip should keep site soundtrack audible');
M.register({youtubeId:'music123',musicStatus:'HAS_MUSIC',musicConflict:true,musicConfidence:.91});
sessionListener({state:'playing',firstFrameAt:1,mediaKey:'youtube:music123'});
assert.equal(soundtrack.muted,true,'HAS_MUSIC clip must mute site soundtrack');
sessionListener({state:'playing',firstFrameAt:1,mediaKey:'youtube:unknown999'});
assert.equal(soundtrack.muted,true,'UNKNOWN clip must conservatively mute site soundtrack');
const bad=new FakeMedia();media.push(bad);bad.src='https://cdn.test/poison.mp4';
assert(M.quarantine({mediaUrl:'https://cdn.test/poison.mp4'},'HTTP 410 stale historical media'));
assert.equal(bad.src,'','quarantine must tear down existing native media src');
bad.src='https://cdn.test/poison.mp4';
assert.equal(bad.src,'','quarantined media must be blocked before reassignment');
const snap=M.snapshot();assert(snap.preloadBlocks>=1,'preload block telemetry missing');assert.equal(snap.activeBlockedLoads,0,'poisoned media must leave zero active blocked loads');
console.log('PASS: v4.5.0 music-aware soundtrack arbitration + poisoned media pre-assignment containment');

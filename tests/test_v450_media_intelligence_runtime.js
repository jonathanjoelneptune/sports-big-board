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
global.queueMicrotask=fn=>fn();
let mutationObserverInstalls=0;
global.MutationObserver=class{observe(){mutationObserverInstalls++;}};
const media=[];global.document={baseURI:'https://example.test/',documentElement:{},body:{setAttribute:()=>{}},querySelectorAll:(q)=>q==='video'?media:[],};
global.SBB_PLAYBACK_TRANSPORTS={playbackKey:a=>a?.youtubeId?`youtube:${a.youtubeId}`:(a?.mediaUrl?`direct:${a.mediaUrl}`:String(a?.mediaKey||''))};
let sessionListener=null,manifestListener=null,audibleWrites=0;
let sessionState={state:'idle',firstFrameAt:0,mediaKey:'',clipKey:'',audible:{soundtrack:false}};
global.SBB_PLAYBACK_SESSION={
  subscribe:fn=>{sessionListener=fn;fn(JSON.parse(JSON.stringify(sessionState)));return()=>{};},
  snapshot:()=>JSON.parse(JSON.stringify(sessionState)),
  setAudible:(kind,id,value)=>{
    audibleWrites++;
    if(audibleWrites>4)throw new Error('recursive playback-session audible feedback loop');
    sessionState={...sessionState,audible:{...sessionState.audible,soundtrack:!!value}};
    sessionListener?.(JSON.parse(JSON.stringify(sessionState)));
  }
};
global.SBB_MEDIA_MANIFEST={subscribe:fn=>{manifestListener=fn;return()=>{};}};
const soundtrack=new FakeMedia();soundtrack.src='https://example.test/site-song.mp3';soundtrack.paused=false;
global.__SBB_SOUNDTRACK_SINGLETON__={audio:soundtrack};
vm.runInThisContext(src,{filename:'media-intelligence.js'});
const M=SBB_MEDIA_INTELLIGENCE;
assert.equal(mutationObserverInstalls,0,'Media Intelligence must not install a global src MutationObserver');
assert(audibleWrites<=1,'startup subscription must not recurse through setAudible');
M.register({mediaUrl:'https://cdn.test/no-music.mp4',musicStatus:'NO_MUSIC',musicConflict:false,musicConfidence:.95});
sessionState={...sessionState,state:'playing',firstFrameAt:1,mediaKey:'direct:https://cdn.test/no-music.mp4'};
sessionListener({...sessionState,audible:{...sessionState.audible}});
assert.equal(soundtrack.muted,false,'NO_MUSIC clip should keep site soundtrack audible');
assert(audibleWrites<=2,'NO_MUSIC arbitration should settle with at most one changed audible write');
M.register({youtubeId:'music123',musicStatus:'HAS_MUSIC',musicConflict:true,musicConfidence:.91});
sessionState={...sessionState,state:'playing',firstFrameAt:1,mediaKey:'youtube:music123',audible:{soundtrack:true}};
sessionListener(JSON.parse(JSON.stringify(sessionState)));
assert.equal(soundtrack.muted,true,'HAS_MUSIC clip must mute site soundtrack');
assert(audibleWrites<=3,'HAS_MUSIC arbitration must not create a feedback loop');
sessionState={...sessionState,state:'playing',firstFrameAt:1,mediaKey:'youtube:unknown999',audible:{soundtrack:true}};
sessionListener(JSON.parse(JSON.stringify(sessionState)));
assert.equal(soundtrack.muted,true,'UNKNOWN clip must conservatively mute site soundtrack');
assert(audibleWrites<=4,'UNKNOWN arbitration must settle without recursive session churn');
const bad=new FakeMedia();media.push(bad);bad.src='https://cdn.test/poison.mp4';
assert(M.quarantine({mediaUrl:'https://cdn.test/poison.mp4'},'HTTP 410 stale historical media'));
assert.equal(bad.src,'','quarantine must tear down existing native media src');
bad.src='https://cdn.test/poison.mp4';
assert.equal(bad.src,'','quarantined media must be blocked before reassignment');
const snap=M.snapshot();assert(snap.preloadBlocks>=1,'preload block telemetry missing');assert.equal(snap.activeBlockedLoads,0,'poisoned media must leave zero active blocked loads');
console.log('PASS: v4.5.1 Media Intelligence startup loop guard + music arbitration + poison containment');

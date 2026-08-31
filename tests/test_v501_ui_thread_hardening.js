'use strict';
const assert=require('assert');
const fs=require('fs');
const path=require('path');
const vm=require('vm');
const ROOT=path.resolve(__dirname,'..');
const read=rel=>fs.readFileSync(path.join(ROOT,rel),'utf8');
const version=read('VERSION').trim();
assert.strictEqual(version,'5.0.1');
const app=read('app.js');
const index=read('index.html');
const cert=read('architecture/comprehensive-site-certification.js');
assert(index.includes(`architecture/main-thread-guard-v5.js?v=${version}`));
assert(app.includes("let lastPlaybackUiMode='';"));
assert(app.includes("if(mode===lastPlaybackUiMode)return;"));
assert(app.includes("if(observed!==lastPlaybackUiMode)setPlaybackUi(observed);"));
assert(cert.includes("const VERSION='3.1'"));
assert(cert.includes('requireResponsiveUi'));
assert(cert.includes('UI_THREAD warnings='));

const eventListeners={};
const window={
  SBB_CORE:{event:(x,competition)=>({...x,competitionId:x.competitionId||competition})},
  SBB_EVENT_IDENTITY:{key:e=>`${String(e.competitionId||'').toUpperCase()}:${String(e.eventId||e.scoreEventId||e.id||'')}`},
  SBB_PLAYBACK_TRANSPORTS:{mediaKey:item=>item.youtubeId?`youtube:${item.youtubeId}`:(item.mediaUrl?`direct:${item.mediaUrl}`:String(item.id||''))},
  SBB_MEDIA_SCOPE:{isCollection:()=>false},
  addEventListener:(name,fn)=>{(eventListeners[name]||=([])).push(fn);},
  dispatchEvent:ev=>{for(const fn of eventListeners[ev.type]||[])fn(ev);}
};
window.window=window;
let clock=1000;
const sandbox={window,console,Date,Math,Number,String,Object,Array,Set,Map,JSON,RegExp,Promise,Error,structuredClone:global.structuredClone,
  performance:{now:()=>++clock},CustomEvent:function(type,init){this.type=type;this.detail=init?.detail;},setTimeout:()=>0,clearTimeout:()=>{},fetch:()=>Promise.resolve({ok:true}),document:{}};
vm.createContext(sandbox);
for(const file of ['architecture/app-store-v5.js','architecture/selected-event-store.js','architecture/playback-session.js','architecture/playback-orchestrator-v5.js'])vm.runInContext(read(file),sandbox,{filename:file});

// The hot app state must not retain a giant provider payload.
const huge={competitionId:'CFB',eventId:'usc-like',away:{name:'Away'},home:{name:'Home'},providerPayload:'x'.repeat(2_000_000),timeline:Array.from({length:1000},(_,i)=>({i,text:'y'.repeat(100)}))};
const tx=window.SBB_PLAYBACK_ORCHESTRATOR.beginScoreIntent(huge,{userInitiated:true,reason:'ui-thread regression'});
let snap=window.SBB_APP_STORE.snapshot();
assert.strictEqual(snap.selection.event.providerPayload,undefined,'hot App Store must project provider payload away');
assert.strictEqual(snap.playback.event.timeline,undefined,'hot playback state must not retain Game Center/provider timeline arrays');
assert.strictEqual(snap.selection.event.eventId,'usc-like');

// One concrete selection + PLAYING transition may commit once, but repeated level
// observations are no-ops and cannot churn the App Store revision.
window.SBB_PLAYBACK_ORCHESTRATOR.setPlan(tx,[{youtubeId:'abc123',provider:'YOUTUBE'}]);
window.SBB_PLAYBACK_ORCHESTRATOR.selectMedia(tx,{youtubeId:'abc123',provider:'YOUTUBE'});
window.SBB_PLAYBACK_SESSION.select({transactionId:tx,eventKey:'CFB:usc-like',mediaKey:'youtube:abc123',provider:'YOUTUBE',transport:'YOUTUBE_EMBED',slot:'A'});
window.SBB_PLAYBACK_SESSION.transition('playing',{slot:'A',provider:'YOUTUBE',transport:'YOUTUBE_EMBED'});
const afterPlaying=window.SBB_APP_STORE.snapshot().revision;
for(let i=0;i<100;i++)window.SBB_PLAYBACK_SESSION.transition('playing',{slot:'A',provider:'YOUTUBE',transport:'YOUTUBE_EMBED'});
const afterDuplicates=window.SBB_APP_STORE.snapshot().revision;
assert.strictEqual(afterDuplicates,afterPlaying,'100 duplicate PLAYING observations must create zero App Store commits');
const health=window.SBB_APP_STORE.healthSnapshot();
assert(health.noops>=0);
assert(health.maxDispatchMs>=0);

// Repeated identical app-level mirrors are also idempotent.
window.SBB_APP_STORE.dispatch({type:'PLAYBACK_PLAYING',payload:{transactionId:tx}});
const rev=window.SBB_APP_STORE.snapshot().revision;
for(let i=0;i<100;i++)window.SBB_APP_STORE.dispatch({type:'PLAYBACK_PLAYING',payload:{transactionId:tx}});
assert.strictEqual(window.SBB_APP_STORE.snapshot().revision,rev);

console.log('PASS: v5.0.1 UI-thread hardening removes duplicate playback fanout and compact-projects hot event state');

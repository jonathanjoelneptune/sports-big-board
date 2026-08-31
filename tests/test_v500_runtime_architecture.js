'use strict';
const assert=require('assert');
const fs=require('fs');
const path=require('path');
const vm=require('vm');
const ROOT=path.resolve(__dirname,'..');
const read=rel=>fs.readFileSync(path.join(ROOT,rel),'utf8');
const version=read('VERSION').trim();
assert(/^5\.0\.\d+$/.test(version),'v5.0.x runtime architecture baseline');

const listeners={};
const eventListeners={};
const window={
  SBB_CORE:{event:(x,competition)=>({...x,competitionId:x.competitionId||competition})},
  SBB_EVENT_IDENTITY:{key:e=>`${String(e.competitionId||e.__sbbLeague||e.league||'').toUpperCase()}:${String(e.espnEventId||e.scoreEventId||e.eventId||e.matchId||e.id||'')}`},
  SBB_PLAYBACK_TRANSPORTS:{mediaKey:item=>item.youtubeId?`youtube:${item.youtubeId}`:(item.mediaUrl?`direct:${item.mediaUrl}`:String(item.id||''))},
  SBB_MEDIA_SCOPE:{isCollection:item=>!!item?.collectionScoped},
  addEventListener:(name,fn)=>{(eventListeners[name]||=([])).push(fn);},
  dispatchEvent:ev=>{for(const fn of eventListeners[ev.type]||[])fn(ev);}
};
window.window=window;
const sandbox={window,console,Date,Math,Number,String,Object,Array,Set,Map,JSON,RegExp,Promise,Error,performance:{now:()=>Date.now()},structuredClone:global.structuredClone,CustomEvent:function(type,init){this.type=type;this.detail=init?.detail;},setTimeout:()=>0,clearTimeout:()=>{},fetch:()=>Promise.resolve({ok:true}),document:{}};
vm.createContext(sandbox);
for(const file of ['architecture/app-store-v5.js','architecture/selected-event-store.js','architecture/playback-session.js','architecture/playback-orchestrator-v5.js']){
  vm.runInContext(read(file),sandbox,{filename:file});
}
assert.strictEqual(window.SBB_APP_STORE.version,version);
assert.strictEqual(window.SBB_SELECTED_EVENT.version,'5.0.0');
assert.strictEqual(window.SBB_PLAYBACK_SESSION.version,'2.0');
assert.strictEqual(window.SBB_PLAYBACK_ORCHESTRATOR.version,version);

const game={competitionId:'CFB',eventId:'evt-1',name:'Away @ Home',away:{name:'Away'},home:{name:'Home'}};
const tx=window.SBB_PLAYBACK_ORCHESTRATOR.beginScoreIntent(game,{reason:'test click',userInitiated:true});
let app=window.SBB_APP_STORE.snapshot();
assert(tx,'score intent must create transaction synchronously');
assert.strictEqual(app.playback.transactionId,tx);
assert.strictEqual(app.playback.state,'INTENT');
assert.strictEqual(app.playback.eventKey,'CFB:evt-1');
assert.strictEqual(app.selection.eventKey,'CFB:evt-1');
assert.strictEqual(app.invariant,'OK');
let ps=window.SBB_PLAYBACK_SESSION.snapshot();
assert.strictEqual(ps.transactionId,tx,'transport session is linked to v5 transaction before media exists');
assert.strictEqual(ps.state,'preparing');
assert.strictEqual(ps.mediaKey,'');

// A late media/provider callback may not redirect the sporting event.
window.SBB_SELECTED_EVENT.select({competitionId:'CFB',eventId:'wrong-event'},{source:'playback',reason:'late media callback'});
assert.strictEqual(window.SBB_SELECTED_EVENT.get().canonicalEventKey,'CFB:evt-1');
assert.strictEqual(window.SBB_PLAYBACK_ORCHESTRATOR.ownershipSnapshot().owned,true);

const candidates=[{youtubeId:'abc',title:'recap',provider:'YOUTUBE'}];
window.SBB_PLAYBACK_ORCHESTRATOR.setPlan(tx,candidates);
window.SBB_PLAYBACK_ORCHESTRATOR.preparing(tx,candidates[0]);
window.SBB_PLAYBACK_ORCHESTRATOR.prewarmResult(tx,candidates[0],{ok:false,result:'PREWARM_TIMEOUT'});
window.SBB_PLAYBACK_ORCHESTRATOR.unavailable(tx,'prewarm failed');
app=window.SBB_APP_STORE.snapshot();
assert.strictEqual(app.playback.state,'UNAVAILABLE');
assert.strictEqual(app.selection.eventKey,'CFB:evt-1','media failure must not erase selected sporting event');
assert.strictEqual(window.SBB_PLAYBACK_ORCHESTRATOR.ownershipSnapshot().owned,true);
window.SBB_SELECTED_EVENT.select({competitionId:'CFB',eventId:'wrong-after-failure'},{source:'playback-confirmed',reason:'late provider callback after unavailable'});
assert.strictEqual(window.SBB_SELECTED_EVENT.get().canonicalEventKey,'CFB:evt-1','late callbacks cannot redirect event even after media becomes unavailable');

// Switching sporting events is one atomic reducer transition: observers never see
// new SelectedEvent paired with the prior playback transaction.
const observedInvariants=[];const offStore=window.SBB_APP_STORE.subscribe(st=>observedInvariants.push(st.invariant));
const game2={competitionId:'CFB',eventId:'evt-2',name:'Other Away @ Other Home'};
const switchTx=window.SBB_PLAYBACK_ORCHESTRATOR.beginScoreIntent(game2,{reason:'event switch',userInitiated:true});
assert(switchTx&&switchTx!==tx);assert.strictEqual(window.SBB_APP_STORE.snapshot().selection.eventKey,'CFB:evt-2');assert(observedInvariants.every(x=>x==='OK'),`atomic event switch exposed invariant: ${observedInvariants.join(',')}`);offStore();

// A new intent can select media and every tune goes through one bound adapter.
const tx2=window.SBB_PLAYBACK_ORCHESTRATOR.beginScoreIntent(game,{reason:'retry',userInitiated:true});
window.SBB_PLAYBACK_ORCHESTRATOR.setPlan(tx2,candidates);
window.SBB_PLAYBACK_ORCHESTRATOR.selectMedia(tx2,candidates[0],{candidateIndex:0});
let adapterCalls=0,preparedCalls=0;
assert.strictEqual(window.SBB_PLAYBACK_ORCHESTRATOR.bindAdapter({tuneProgramIndex:(index,options)=>{adapterCalls++;return {index,options};},promotePrepared:(slot,index,options)=>{preparedCalls++;return {slot,index,options};}}),true);
assert.strictEqual(window.SBB_PLAYBACK_ORCHESTRATOR.bindAdapter({tuneProgramIndex:()=>{}}),false,'adapter binding is single-owner');
const tuned=window.SBB_PLAYBACK_ORCHESTRATOR.requestTune(tx2,3,{reason:'test'});
Promise.resolve(tuned).then(()=>{});
assert.strictEqual(adapterCalls,1);
window.SBB_PLAYBACK_ORCHESTRATOR.requestPreparedPromotion(tx2,'B',4,{reason:'hot standby'});assert.strictEqual(preparedCalls,1,'prepared A/B promotion is owned by the same orchestrator adapter');
app=window.SBB_APP_STORE.snapshot();
assert.strictEqual(app.playback.state,'STARTING');
assert.strictEqual(app.playback.activeMediaKey,'youtube:abc');
assert.strictEqual(app.invariant,'OK');

console.log(`PASS: ${version} unified App Store + intent-first playback + SelectedEvent ownership runtime`);

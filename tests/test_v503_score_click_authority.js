'use strict';
const assert=require('assert');
const fs=require('fs');
const path=require('path');
const vm=require('vm');
const ROOT=path.resolve(__dirname,'..');
const read=rel=>fs.readFileSync(path.join(ROOT,rel),'utf8');
const version=read('VERSION').trim();
const parts=version.split('.').map(Number);assert(parts[0]===5&&parts[1]===0&&parts[2]>=3,'v5.0.3+ score-click authority baseline');
const app=read('app.js');
const storeSource=read('architecture/app-store-v5.js');
const selectedSource=read('architecture/selected-event-store.js');
const cert=read('architecture/comprehensive-site-certification.js');

// The real score-card click boundary may create only intent synchronously. JavaScript
// evaluates function arguments before entering playGameHighlights(), so passing the
// legacy scoreCardPlayableItems(m) resolver here would bypass every v5 cooperative
// yield and can freeze one pathological event before the v5 transaction exists.
assert(app.includes("cell.onclick=()=>playGameHighlights(`${lg}:${matchId}`,m,null,{source:'score-ribbon'})"),'score ribbon must enter v5 without synchronous media resolution');
assert(!app.includes("cell.onclick=()=>playGameHighlights(`${lg}:${matchId}`,m,scoreCardPlayableItems(m))"),'legacy synchronous score resolver still executes in click argument evaluation');
for(const token of [
  "cell.addEventListener('pointerdown',()=>primeScoreIntent(primaryForPrime)",
  "cell.addEventListener('pointerenter',()=>primeScoreIntent(primaryForPrime)",
  "cell.addEventListener('focus',()=>primeScoreIntent(primaryForPrime)"
])assert(!app.includes(token),`pre-click media work remains on ribbon event: ${token}`);

assert(app.includes("const SCORE_CLICK_TRACE_KEY='sports-big-board.score-click-trace.v1'"));
for(const stage of ['CLICK_RECEIVED','INTENT_CREATED','PLAN_START','PLAN_BUILT','SELECTION_START','SELECTION_RESOLVED','CANDIDATE_PLAN_RESOLVED','PROGRAM_COMMITTED','TUNE_REQUESTED','TUNE_DISPATCHED'])assert(app.includes(stage),`missing score-click diagnostic stage ${stage}`);
assert(app.includes('scoreCardPlayableItemsForIntent(match)'),'async cooperative score planner is not the score-click resolver');
assert(app.includes("options?.trustedProvidedItems===true"),'ordinary clicks must not trust precomputed legacy media arrays');
assert(!app.includes('const playable=scoreCardPlayableItems(match);'),'historical click path still performs synchronous legacy media resolution');

// Pathological alternate graphs are bounded independently of the recap-index lookup.
assert(app.includes('const MAX_MEDIA_VERSION_EXPANSION=96;'));
assert(app.includes('const MAX_MEDIA_VERSION_DEPTH=2;'));
assert(app.includes('.slice(0,MAX_RECAP_ALTERNATES_TOTAL)'));
assert(app.includes('while(head<queue.length&&out.length<MAX_MEDIA_VERSION_EXPANSION)'));
assert(!app.includes('for(const alt of x.recapAlternates) add(alt);'),'recursive unbounded recap-alternate expansion remains');

// Explicit intent prewarm is exact-item only; whole-ribbon reconciliation is deferred.
const primeStart=app.indexOf('function primeScoreIntent(item){');
const primeEnd=app.indexOf('\n}',primeStart)+2;
const primeBlock=app.slice(primeStart,primeEnd);
assert(primeBlock.includes('primeScoreMediaItem(item,{priority:true,rank:1000000})'));
assert(primeBlock.includes('scheduleScoreMediaWarmReconcile(90)'));
assert(!primeBlock.includes('reconcileScoreMediaWarmSet({intentItem:item})'),'whole-ribbon warm reconcile still runs synchronously from intent');

// Score-session startup failures are local and cannot trip the destructive engine reset threshold.
assert(app.includes("activeV5?.transactionId&&activeV5?.source==='score'"));
assert(app.includes('score-session startup failure'));

// State authorities protect event ownership while a v5 transaction is active.
assert(storeSource.includes(`const VERSION='${version}'`));
const storeSchema=(storeSource.match(/const SCHEMA='(\d+)\.(\d+)'/)||[]).slice(1).map(Number);
assert(storeSchema.length===2 && (storeSchema[0]>1 || (storeSchema[0]===1 && storeSchema[1]>=3)),'App Store schema 1.3+ required');
assert(storeSource.includes("source!=='v5-orchestrator'&&payload.force!==true"));
assert(selectedSource.includes(`version:'${version}'`),'SelectedEvent authority must track the current v5.0.x release');
assert(selectedSource.includes("source!=='v5-orchestrator'&&meta.force!==true"));
assert(/const VERSION='3\.[3-9]+'/.test(cert),'certification schema must retain 3.3+ score-click telemetry');
assert(cert.includes('SCORE_CLICK_TRACE stage='));
assert(cert.includes('mediaExpansion'));

// Runtime ownership regression: certification/player cleanup cannot clear the event
// and recreate the historical PLAYBACK EVENT WITHOUT SELECTED EVENT invariant.
// underneath a live score transaction, either through SelectedEvent or App Store.
const eventListeners={};
const w={
  SBB_CORE:{event:(x,c)=>({...x,competitionId:x.competitionId||c})},
  SBB_EVENT_IDENTITY:{key:e=>`${String(e.competitionId||'').toUpperCase()}:${String(e.eventId||e.id||'')}`},
  SBB_PLAYBACK_TRANSPORTS:{mediaKey:i=>i?.youtubeId?`youtube:${i.youtubeId}`:i?.mediaUrl?`direct:${i.mediaUrl}`:String(i?.id||'')},
  SBB_MEDIA_SCOPE:{isCollection:()=>false},
  addEventListener:(n,fn)=>{(eventListeners[n]||=([])).push(fn);},
  dispatchEvent:ev=>{for(const fn of eventListeners[ev.type]||[])fn(ev);}
};
w.window=w;
const sandbox={window:w,console,Date,Math,Number,String,Object,Array,Set,Map,JSON,RegExp,Promise,Error,structuredClone:global.structuredClone,performance:{now:()=>Date.now()},CustomEvent:function(type,init){this.type=type;this.detail=init?.detail;},setTimeout:()=>0,clearTimeout:()=>{},fetch:()=>Promise.resolve({ok:true}),document:{}};
vm.createContext(sandbox);
for(const f of ['architecture/app-store-v5.js','architecture/selected-event-store.js','architecture/playback-session.js','architecture/playback-orchestrator-v5.js'])vm.runInContext(read(f),sandbox,{filename:f});
const evt={competitionId:'CFB',eventId:'pathological-event',awayTeam:{name:'Away'},homeTeam:{name:'Home'}};
const tx=w.SBB_PLAYBACK_ORCHESTRATOR.beginScoreIntent(evt,{userInitiated:true,reason:'score click authority regression'});
let before=w.SBB_APP_STORE.snapshot();
assert(before.selection.eventKey&&before.selection.eventKey===before.playback.eventKey);
w.SBB_SELECTED_EVENT.clear({source:'certification',reason:'restoration attempt'});
w.SBB_APP_STORE.dispatch({type:'CLEAR_EVENT',payload:{source:'certification',reason:'restoration attempt'}});
let after=w.SBB_APP_STORE.snapshot();
assert.strictEqual(after.selection.eventKey,before.selection.eventKey,'active v5 score event was cleared by legacy/certification cleanup');
assert.strictEqual(after.playback.transactionId,tx);
assert.strictEqual(after.invariant,'OK');

console.log(`PASS: ${version} retains v5.0.3 score-click authority preventing pre-v5 synchronous resolution and protecting active event ownership`);

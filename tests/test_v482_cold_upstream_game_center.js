'use strict';
const assert=require('assert');
const fs=require('fs');
const path=require('path');
const vm=require('vm');
const ROOT=path.resolve(__dirname,'..');
const read=rel=>fs.readFileSync(path.join(ROOT,rel),'utf8');
const version=read('VERSION').trim();
const index=read('index.html');
const app=read('app.js');
const cert=read('architecture/comprehensive-site-certification.js');
const init=read('sbb/__init__.py');
const runtime=read('sbb/game_center_runtime_v482.py');
const manifest=JSON.parse(read('release-manifest.json'));
const verify=read('VERIFY.sh');

assert.strictEqual(version,'4.8.2');
assert(index.includes('<title>Sports Big Board — v4.8.2</title>'));
for(const [,asset,found] of [...index.matchAll(/(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"/g)]){
  assert.strictEqual(found,version,`${asset} has stale generation ${found}`);
}

// COLD_UPSTREAM is an off-air preflight state, never an automatic active-player state.
for(const token of [
  'SCORE_MEDIA_PREFLIGHT_WAIT_MS',
  "disposition:'COLD_UPSTREAM'",
  'function scoreMediaAirReady',
  'function waitForScoreMediaHot',
  "result:'BYPASSED_COLD'",
  "result:'PREWARM_TIMEOUT'",
  'kept an unproven upstream source off-air',
  'primaryRejected',
  'PREPARING FALLBACK VIDEO',
  'Automatic date programming may only put browser-proven native media on air.',
]) assert(app.includes(token),`missing cold-upstream contract: ${token}`);
assert(app.includes('const SCORE_PLAYABLE_ITEMS_CACHE_TTL_MS=1500'));
assert(app.includes('function scorePlayableItemsCacheGet'));
assert(app.includes('scorePlayableItemsCachePut(match,preferGameOverviews(items))'));
assert(app.includes('scorePlayableCache:()=>scorePlayableItemsCacheSnapshot()'));

// Certification distinguishes capability coverage from runtime failure and records
// whether a cold primary was prewarmed or rejected before playback.
for(const token of [
  "const VERSION='2.2'",
  'GAME_CENTER_EXPECTED_SUPPORTED',
  'unsupportedReason',
  'prewarmAttempts',
  'primaryRejections',
  'readinessBefore=',
  'primaryRejected=',
  'unsupported=${gc.unsupported||0}',
]) assert(cert.includes(token),`missing v4.8.2 certification contract: ${token}`);

// Load only the certification module to test the support boundary without a browser.
const listeners={};
const document={
  readyState:'loading',hidden:false,
  addEventListener:(name,fn)=>{listeners[name]=fn;},
  getElementById:()=>null,querySelector:()=>null,querySelectorAll:()=>[],
  head:{appendChild:()=>{}},createElement:()=>({style:{},classList:{toggle:()=>{}},appendChild:()=>{}})
};
const window={SBB_CORE:{version},addEventListener:()=>{},dispatchEvent:()=>{}};window.window=window;
const sandbox={window,document,console,performance:{now:()=>1},Date,Math,Number,String,Object,Array,Set,Map,JSON,RegExp,Promise,Blob:global.Blob,AbortController,DOMException,CustomEvent:function(){},setTimeout:()=>0,clearTimeout:()=>{},setInterval:()=>1,clearInterval:()=>{},getComputedStyle:()=>({display:'none'}),URL};
vm.createContext(sandbox);vm.runInContext(cert,sandbox,{filename:'comprehensive-site-certification.js'});
assert.strictEqual(window.SBB_SITE_CERTIFICATION.version,'2.2');
assert.strictEqual(window.SBB_SITE_CERTIFICATION.gameCenterSupport('NBA').supported,true);
assert.strictEqual(window.SBB_SITE_CERTIFICATION.gameCenterSupport('NHL').supported,true);
assert.strictEqual(window.SBB_SITE_CERTIFICATION.gameCenterSupport('LLWS2026').supported,false);
assert.strictEqual(window.SBB_SITE_CERTIFICATION.gameCenterSupport('WC2026').supported,false);

// NBA/NHL resolution is installed as a bounded backend runtime patch using the
// existing ESPN scoreboard authority, not a new provider or hard-coded event.
assert(init.includes('game_center_runtime_v482'));
assert(init.includes('_install_game_center_runtime_v482()'));
for(const token of ['_TARGETS = frozenset({"NBA", "NHL"})','_espn_scoreboard','_same_team_pair','_resolve_game_center_event_id','date + away/home']){
  assert(runtime.includes(token),`missing Game Center runtime token: ${token}`);
}
for(const forbidden of ['401864494','San José State Spartans @ #14 USC Trojans','TEX vs CHW']){
  assert(!app.includes(forbidden),`app contains named-regression exception: ${forbidden}`);
  assert(!runtime.includes(forbidden),`runtime contains named-regression exception: ${forbidden}`);
}
assert(manifest.release==='4.8.2');
assert(manifest.requiredFiles.includes('sbb/game_center_runtime_v482.py'));
assert(manifest.requiredFiles.includes('tests/test_v482_cold_upstream_game_center.js'));
assert(verify.includes('node tests/test_v482_cold_upstream_game_center.js'));
assert(verify.includes('python3 -m unittest tests.test_v482_game_center_runtime'));

console.log('PASS: v4.8.2 cold-upstream gate + Game Center support/identity contracts');

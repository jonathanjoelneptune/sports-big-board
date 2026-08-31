'use strict';
const assert=require('assert');
const fs=require('fs');
const path=require('path');
const vm=require('vm');
const ROOT=path.resolve(__dirname,'..');
const read=rel=>fs.readFileSync(path.join(ROOT,rel),'utf8');
const version=read('VERSION').trim();
const index=read('index.html');
const core=read('core-model.js');
const cert=read('architecture/comprehensive-site-certification.js');
const efficiency=read('architecture/efficiency-certification.js');
const watchdog=read('architecture/playback-progress-watchdog.js');
const verify=read('VERIFY.sh');

const versionParts=version.split('.').map(Number);
assert(versionParts[0]>4 || (versionParts[0]===4 && versionParts[1]>=8));
assert(index.includes(`<title>Sports Big Board — v${version}</title>`));
assert(core.includes(`version:'${version}'`));
assert(efficiency.includes(`const VERSION = '${version}'`));
assert(/const VERSION='[23]\.\d+'/.test(cert));
assert(cert.includes('Whole-site certification')||cert.includes('whole-site certification')||cert.includes('Comprehensive Certification'));
assert(cert.includes('seededRng'));
assert(cert.includes('certificationDates'));
assert(cert.includes('playbackInteractionMatrix'));
assert(cert.includes("#scoreCells .score-card.has-highlights"));
assert(cert.includes('candidate.card.click()'));
assert(cert.includes('waitForProgress'));
assert(cert.includes('gameCenterUiExercise'));
assert(cert.includes("['overview','team-stats','players','plays']"));
assert(cert.includes('SBB_PLAYBACK_PROGRESS_WATCHDOG'));
assert(index.includes(`architecture/playback-progress-watchdog.js?v=${version}`));
assert(watchdog.includes('No game, league'));
assert(watchdog.includes('getCurrentTime'));
assert(watchdog.includes('PROGRESS_SOFT_KICK_MS'));
assert(watchdog.includes('PROGRESS_RECOVERY_MS'));
assert(watchdog.includes("typeof handlePlaybackFailure==='function'"));
assert(watchdog.includes('media clock did not advance'));
assert(cert.includes('fallbackHops'));
assert(cert.includes('ACTIVE PLAYBACK INTERACTION MATRIX'));
assert(cert.includes('SEED=${r.seed}'));
assert(cert.includes('runFull({seed:${r.seed}})'));
assert(verify.includes('node tests/test_v480_comprehensive_certification.js'));

for(const forbidden of ['USC_EVENT_FOUND','401864494','San Jose','San José','san jose','sjs']){
  assert(!cert.includes(forbidden),`comprehensive certification contains named-game token: ${forbidden}`);
}
const refs=[...index.matchAll(/(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"/g)];
assert(refs.length>40,'expected full frontend asset chain');
for(const [,asset,found] of refs)assert.strictEqual(found,version,`${asset} has stale generation ${found}`);

const listeners={};
const intervals=[];
let perfNow=1;
const document={
  readyState:'loading',hidden:false,
  addEventListener:(name,fn)=>{listeners[name]=fn;},
  getElementById:()=>null,
  querySelector:()=>null,
  querySelectorAll:()=>[],
  head:{appendChild:()=>{}},
  createElement:()=>({style:{},classList:{toggle:()=>{}},appendChild:()=>{}})
};
const window={SBB_CORE:{version},addEventListener:()=>{},dispatchEvent:()=>{}};
window.window=window;
const sandbox={window,document,console,performance:{now:()=>perfNow},Date,Math,Number,String,Object,Array,Set,Map,JSON,RegExp,Promise,Blob:global.Blob,AbortController,DOMException,CustomEvent:function(){},setTimeout:()=>0,clearTimeout:()=>{},setInterval:(fn,ms)=>{intervals.push({fn,ms});return intervals.length;},clearInterval:()=>{},getComputedStyle:()=>({display:'none'}),URL};
vm.createContext(sandbox);
vm.runInContext(cert,sandbox,{filename:'comprehensive-site-certification.js'});
assert(/^[23]\./.test(window.SBB_SITE_CERTIFICATION.version));
const a=Array.from(window.SBB_SITE_CERTIFICATION.certificationDates(123456));
const b=Array.from(window.SBB_SITE_CERTIFICATION.certificationDates(123456));
assert.deepStrictEqual(a,b,'same seed must reproduce same date plan');
assert(a.length>=8,'date plan should cover recent + archive dates');
assert.strictEqual(new Set(a).size,a.length,'date plan should not duplicate dates');

let session={sessionId:'ps-test',selectionId:1,state:'playing',mediaKey:'youtube:stuck',slot:'A',provider:'YOUTUBE',transport:'YOUTUBE_EMBED',invariant:'OK'};
let playKicks=0,recoveries=0,wdSubscriber=null,mediaClock=0;
const wdIntervals=[];let wdNow=0;
const wdWindow={SBB_PLAYBACK_SESSION:{snapshot:()=>({...session}),subscribe:fn=>{wdSubscriber=fn;fn({...session});return()=>{};},fail:()=>{throw new Error('canonical controller should own recovery');}},dispatchEvent:()=>{}};wdWindow.window=wdWindow;
const wdSandbox={window:wdWindow,document:{hidden:false,getElementById:()=>null},console,performance:{now:()=>wdNow},Date,Math,Number,String,Object,Array,Set,Map,JSON,RegExp,Promise,Error,CustomEvent:function(){},setTimeout:()=>0,clearTimeout:()=>{},setInterval:(fn,ms)=>{wdIntervals.push({fn,ms});return wdIntervals.length;},clearInterval:()=>{}};
wdSandbox.players={A:{getCurrentTime:()=>mediaClock,getPlayerState:()=>1,playVideo:()=>{playKicks++;}}};
wdSandbox.manualPauseRequested=false;
wdSandbox.handlePlaybackFailure=(slot,err,providerFailure)=>{recoveries++;assert.strictEqual(slot,'A');assert.strictEqual(providerFailure,false);assert(String(err.message).includes('LOCAL_NO_PROGRESS'));assert(String(err.message).includes('media clock did not advance'));};
vm.createContext(wdSandbox);vm.runInContext(watchdog,wdSandbox,{filename:'playback-progress-watchdog.js'});
const progressTimer=wdIntervals.find(x=>x.ms===250);assert(progressTimer,'progress watchdog interval should be installed');
wdNow=100;progressTimer.fn();
wdNow=3600;progressTimer.fn();assert.strictEqual(playKicks,1,'stuck PLAYING session receives one soft play kick');
wdNow=8100;progressTimer.fn();assert.strictEqual(recoveries,1,'non-advancing transport delegates to canonical fallback controller');
const stuckSnap=wdWindow.SBB_PLAYBACK_PROGRESS_WATCHDOG.snapshot();
assert.strictEqual(stuckSnap.confirmed,false);assert.strictEqual(stuckSnap.timeouts,1);assert.strictEqual(stuckSnap.recoveries,1);

session={...session,sessionId:'ps-good',selectionId:2,mediaKey:'youtube:advancing'};mediaClock=10;wdNow=9000;wdSubscriber({...session});progressTimer.fn();
mediaClock=10.35;wdNow=9350;progressTimer.fn();
const goodSnap=wdWindow.SBB_PLAYBACK_PROGRESS_WATCHDOG.snapshot();
assert.strictEqual(goodSnap.confirmed,true);assert.strictEqual(goodSnap.selectionId,2);assert.strictEqual(recoveries,1);assert.strictEqual(playKicks,1);

console.log(`PASS: ${version} retains v4.8 seeded whole-site certification + active playback progress/recovery contract`);

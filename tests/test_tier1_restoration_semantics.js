const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'..','architecture','foundation-certification.js'),'utf8');
const listeners={};
global.window={SBB_RELEASE_VERSION:'4.3.10',SBB_CORE:{version:'4.3.10'},SBB_MILESTONE:{browserRuntime:()=>({userAgent:'RestoreTest/1',browserBrands:[{brand:'RestoreTest',version:'1'}],platform:'test',visibility:'visible',online:true})}};
global.navigator={userAgent:'RestoreTest/1',platform:'test',vendor:'test',language:'en-US',onLine:true};
global.document={readyState:'loading',visibilityState:'visible',addEventListener:(n,fn)=>{listeners[n]=fn;},getElementById:()=>null,querySelector:()=>null,querySelectorAll:()=>[]};
vm.runInThisContext(source,{filename:'foundation-certification.js'});
const dev=window.SBB_FOUNDATION_CERTIFICATION._dev;
const procedures=['release-handshake','playback-cycle','historical-read','operator-load','resource-modes','game-center','soundtrack','ui-responsiveness','regression-hardening'];
const results=Object.fromEntries(procedures.map(id=>[id,{status:'PASS',detail:'ok'}]));
const snap={version:'4.3.10',versionMatch:true,problemCounts:{errors:0,warnings:0,info:0},problems:[],recent:[],api:{},checks:[{ok:true}],playback:{latest:{state:'playing',invariant:'OK'}},extra:{release:{frontendVersion:'4.3.10',backendVersion:'4.3.10',versionMatch:true},history:{workers:{w:{healthy:true}}}}};
const steps=Array.from({length:24},(_,i)=>({name:`step-${i+1}`,status:'PASS',at:i+1}));

// Reproduce v4.3.9's contradictory bookkeeping: raw stress says FAIL even though
// every evidence row/procedure passed. If post-test health is good, Tier 1 must PASS
// and retain the exact restoration miss only as an advisory.
let stress={status:'FAIL',steps,restoration:[{name:'restore exact media selection',status:'ADVISORY',detail:'original media no longer present after live rerank'}],restorationHealth:{ok:true,problems:[],advisoryCount:1}};
let tier=dev.tier1Evaluation(snap,stress,results);
assert.equal(tier.status,'PASS','healthy cleanup + all passing evidence must override contradictory raw FAIL bookkeeping');
assert.equal(tier.gates.find(x=>x.id==='stress-suite').ok,true);
assert.match(tier.gates.find(x=>x.id==='stress-suite').detail,/PASS by evidence/);
assert.equal(tier.gates.find(x=>x.id==='post-test-health').ok,true);
assert.equal(tier.gates.find(x=>x.id==='restore-advisories').ok,true);
assert.match(tier.gates.find(x=>x.id==='restore-advisories').detail,/ADVISORY/);

// Real post-cleanup damage remains fatal.
stress={...stress,status:'FAIL',restorationHealth:{ok:false,problems:['playback invariant ERROR_MULTIPLE_AUDIO'],advisoryCount:1}};
tier=dev.tier1Evaluation(snap,stress,results);
assert.equal(tier.status,'FAIL','unhealthy final application state must still fail Tier 1');
assert.equal(tier.gates.find(x=>x.id==='post-test-health').ok,false);

console.log('PASS: v4.3.10 Tier 1 restoration semantics');

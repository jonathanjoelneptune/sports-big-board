'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync('architecture/request-broker.js','utf8');
assert(src.includes("const VERSION='4.7.20'"));
assert(src.includes('ORPHAN_ABORT_GRACE_MS'));
assert(src.includes('existing.controller?.signal?.aborted'));
assert(src.includes('if(inflight.get(key)===entry)inflight.delete(key)'));

// Reproduce the Game Center replacement race. The first view load releases its
// consumer, then a replacement load attaches to the same GET immediately. The
// shared transport must stay alive and the replacement must receive the response.
global.window=global;
global.location={href:'https://example.test/'};
global.CustomEvent=class{constructor(type,init={}){this.type=type;this.detail=init.detail;}};
global.dispatchEvent=()=>true;
global.document={getElementById(){return null;}};
global.SBB_SELECTED_EVENT={get(){return {selectedAt:Date.now()};}};
let network=0,underlyingAborts=0;
global.fetch=(input,init={})=>{
  network++;
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>resolve(new Response(JSON.stringify({ok:true}),{status:200,headers:{'content-type':'application/json'}})),35);
    init.signal?.addEventListener('abort',()=>{
      underlyingAborts++;clearTimeout(timer);
      reject(new DOMException(String(init.signal.reason||'Aborted'),'AbortError'));
    },{once:true});
  });
};
vm.runInThisContext(src,{filename:'request-broker.js'});
SBB_REQUEST_BROKER.beginDate('2026-08-28',1);
(async()=>{
  const url='/api/events/MLB/401/game-center?date=2026-08-28&away=ARI&home=SF';
  const firstController=new AbortController();
  const first=window.fetch(url,{signal:firstController.signal,sbbRequestClass:'ON_DEMAND'}).then(()=>null,e=>e);
  await new Promise(r=>setTimeout(r,2));
  firstController.abort('selection-replaced');
  const second=window.fetch(url,{sbbRequestClass:'ON_DEMAND'});
  const firstError=await first;
  assert.equal(firstError?.name,'AbortError');
  const response=await second;
  assert.equal(response.status,200);
  assert.equal(network,1,'replacement consumer should reuse the live transport');
  assert.equal(underlyingAborts,0,'replacement consumer must cancel orphan abort grace');
  console.log('PASS: v4.7.20 request broker replacement-consumer race');
})().catch(err=>{console.error(err);process.exit(1);});

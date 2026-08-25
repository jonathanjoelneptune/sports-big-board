'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'architecture/site-soundtrack.js'),'utf8');
const manifest={
  tracks:[1,2,3,4,5].map(n=>({id:`t${n}`,title:`Track ${n}`,tier:n<3?'CORE':'ROTATION',file:`tracks/t${n}.mp3`,weight:1,durationSeconds:120})),
  playbackDefaults:{defaultMusicVolume:.16,highlightPlayingVolume:.10,repeatOnlyAfterBagExhausted:true,singleActiveAudioStream:true,preloadNextTrack:true}
};
function tick(){return new Promise(r=>setImmediate(r));}
function makeStorage(seed){
  const data=seed||new Map();
  return {data,getItem:k=>data.has(k)?data.get(k):null,setItem:(k,v)=>data.set(k,String(v)),removeItem:k=>data.delete(k)};
}
class FakeClassList{constructor(){this.s=new Set();}toggle(k,v){if(v===undefined)v=!this.s.has(k);v?this.s.add(k):this.s.delete(k);return v;}contains(k){return this.s.has(k);}}
class FakeElement{
  constructor(id=''){this.id=id;this.textContent='';this.title='';this.value='0.16';this.attrs={};this.classList=new FakeClassList();this.listeners={};}
  addEventListener(t,f){(this.listeners[t]||(this.listeners[t]=[])).push(f);} setAttribute(k,v){this.attrs[k]=String(v);} closest(sel){return sel==='#soundtrackControls'&&this.id.startsWith('soundtrack')?this:null;}
}
function boot(sharedStorage){
  const elements=new Map(['soundtrackToggle','soundtrackNextBtn','soundtrackVolumeBtn','soundtrackVolume','soundtrackVolumePopover','diagSoundtrack'].map(id=>[id,new FakeElement(id)]));
  const docListeners={};
  const document={
    baseURI:'https://board.test/',readyState:'complete',hidden:false,body:new FakeElement('body'),
    getElementById:id=>elements.get(id)||null,
    addEventListener:(t,f)=>{(docListeners[t]||(docListeners[t]=[])).push(f);}
  };
  class FakeAudio{
    static instances=[];
    constructor(){this.paused=true;this.currentTime=0;this.duration=120;this.volume=0;this.muted=false;this.src='';this.listeners={};this.playCalls=0;this.pauseCalls=0;FakeAudio.instances.push(this);}
    addEventListener(t,f){(this.listeners[t]||(this.listeners[t]=[])).push(f);} removeEventListener(t,f){this.listeners[t]=(this.listeners[t]||[]).filter(x=>x!==f);} emit(t){for(const f of [...(this.listeners[t]||[])])f({type:t,target:this});}
    load(){} removeAttribute(k){if(k==='src')this.src='';}
    play(){this.playCalls++;this.paused=false;this.emit('play');this.emit('playing');return Promise.resolve();}
    pause(){this.pauseCalls++;const was=!this.paused;this.paused=true;if(was)this.emit('pause');}
  }
  const math=Object.create(Math);math.random=()=>0.5;
  const winListeners={};
  const context={
    console,document,localStorage:sharedStorage,Audio:FakeAudio,Math:math,Date,JSON,Set,Map,Promise,URL,Number,String,Object,Array,Error,
    setTimeout,clearTimeout,setImmediate,clearImmediate,setInterval:()=>0,clearInterval:()=>{},BroadcastChannel:undefined,
    fetch:async()=>({ok:true,json:async()=>JSON.parse(JSON.stringify(manifest))}),
    SBB_CONFIG:{soundtrackBase:'https://api.test/api/soundtrack'},
    addEventListener:(t,f)=>{(winListeners[t]||(winListeners[t]=[])).push(f);}
  };
  context.window=context;
  vm.createContext(context);vm.runInContext(source,context,{filename:'site-soundtrack.js'});
  return {context,api:context.SBB_SOUNDTRACK,Audio:FakeAudio,elements,winListeners};
}
(async()=>{
  // Playback/Next invariant: only the first Audio element can ever be played.
  const storage=makeStorage(new Map());
  const one=boot(storage);await one.api.init();
  const active=one.Audio.instances[0],preload=one.Audio.instances[1];
  assert.equal(one.Audio.instances.length,2);
  one.api.setPlaybackState('playing');await tick();await tick();
  assert.ok(active.playCalls>=1,'active soundtrack should play');
  assert.equal(preload.playCalls,0,'preloader must never call play()');
  const beforeNext=one.api.snapshot().currentTrack.id;
  one.api.skip();await tick();await tick();
  assert.notEqual(one.api.snapshot().currentTrack.id,beforeNext,'Next should replace the current track');
  assert.ok(active.pauseCalls>=1,'Next must hard-stop the outgoing active element');
  assert.equal(preload.playCalls,0,'Next must not promote/play the preload element');
  assert.equal(one.Audio.instances.filter(a=>!a.paused).length,1,'at most one soundtrack element may be audible');

  // A second tab must not auto-start while a fresh soundtrack owner exists.
  const secondTab=boot(storage);await secondTab.api.init();
  secondTab.api.setPlaybackState('playing');await tick();await tick();
  assert.equal(secondTab.Audio.instances[0].paused,true,'fresh owner lease must keep a second tab silent');
  assert.equal(secondTab.Audio.instances[1].playCalls,0,'second-tab preloader must remain non-playable');

  // Highlight pause truth is immediate and repeated pause notifications remain safe.
  one.api.setPlaybackState('paused');
  assert.equal(active.paused,true,'highlight pause must pause soundtrack');
  const pausedPlayCalls=active.playCalls;
  one.api.setPlaybackState('paused');
  one.api.skip();await tick();
  assert.equal(active.paused,true,'Next while highlight is paused must remain paused');
  assert.equal(active.playCalls,pausedPlayCalls,'Next while paused must not start music');

  // No-repeat cycle must persist across a reload.
  const storage2=makeStorage(new Map());
  const a=boot(storage2);await a.api.init();
  a.api.setPlaybackState('paused');
  const start=a.api.snapshot().currentTrack.id;
  a.api.skip();const second=a.api.snapshot().currentTrack.id;
  a.api.skip();const third=a.api.snapshot().currentTrack.id;
  assert.equal(new Set([start,second,third]).size,3,'first cycle must not repeat');
  const persisted=JSON.parse(storage2.getItem('sbb:soundtrack:v2'));
  assert.ok(Array.isArray(persisted.remainingIds)&&persisted.remainingIds.length===2,'v2 storage must persist exact remaining bag');
  assert.ok(Array.isArray(persisted.playedIds)&&persisted.playedIds.includes(third),'v2 storage must persist heard tracks');
  storage2.removeItem('sbb:soundtrack:owner:v1');
  const b=boot(storage2);await b.api.init();
  assert.equal(b.api.snapshot().currentTrack.id,third,'reload must resume the same current track');
  const expectedRemaining=[...persisted.remainingIds];
  b.api.setPlaybackState('paused');
  const afterReload=[];
  for(let i=0;i<expectedRemaining.length;i++){b.api.skip();afterReload.push(b.api.snapshot().currentTrack.id);}
  assert.deepEqual(afterReload,expectedRemaining,'reload must consume persisted remaining tracks before recycling heard tracks');

  console.log('PASS: v4.1.30 single-stream soundtrack runtime invariants');
})().catch(err=>{console.error(err);process.exit(1);});

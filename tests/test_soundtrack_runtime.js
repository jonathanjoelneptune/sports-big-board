'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'architecture/site-soundtrack.js'),'utf8');
const manifest={
  tracks:[1,2,3,4,5].map(n=>({id:`t${n}`,title:`Track ${n}`,tier:n<3?'CORE':'ROTATION',file:`tracks/t${n}.mp3`,weight:1,durationSeconds:120})),
  playbackDefaults:{defaultMusicVolume:.16,highlightPlayingVolume:.10,repeatOnlyAfterBagExhausted:true,singleActiveAudioStream:true,preloadNextTrack:false,persistentAcrossVideoChanges:true,pauseOnlyOnExplicitVideoPause:true}
};
function tick(){return new Promise(r=>setImmediate(r));}
function makeStorage(seed){const data=seed||new Map();return {data,getItem:k=>data.has(k)?data.get(k):null,setItem:(k,v)=>data.set(k,String(v)),removeItem:k=>data.delete(k)};}
class FakeClassList{constructor(){this.s=new Set();}toggle(k,v){if(v===undefined)v=!this.s.has(k);v?this.s.add(k):this.s.delete(k);return v;}contains(k){return this.s.has(k);}}
class FakeElement{constructor(id=''){this.id=id;this.textContent='';this.title='';this.value='0.16';this.attrs={};this.classList=new FakeClassList();this.listeners={};}addEventListener(t,f){(this.listeners[t]||(this.listeners[t]=[])).push(f);}setAttribute(k,v){this.attrs[k]=String(v);}closest(sel){return sel==='#soundtrackControls'&&this.id.startsWith('soundtrack')?this:null;}}
function boot(sharedStorage){
  const elements=new Map(['soundtrackToggle','soundtrackNextBtn','soundtrackVolumeBtn','soundtrackVolume','soundtrackVolumePopover','diagSoundtrack'].map(id=>[id,new FakeElement(id)]));
  const docListeners={};
  const document={baseURI:'https://board.test/',readyState:'complete',hidden:false,body:new FakeElement('body'),getElementById:id=>elements.get(id)||null,addEventListener:(t,f)=>{(docListeners[t]||(docListeners[t]=[])).push(f);}};
  class FakeAudio{
    static instances=[];
    constructor(){this.paused=true;this.currentTime=0;this.duration=120;this.volume=0;this.muted=false;this.src='';this.listeners={};this.playCalls=0;this.pauseCalls=0;this.loadCalls=0;FakeAudio.instances.push(this);}
    addEventListener(t,f){(this.listeners[t]||(this.listeners[t]=[])).push(f);}removeEventListener(t,f){this.listeners[t]=(this.listeners[t]||[]).filter(x=>x!==f);}emit(t){for(const f of [...(this.listeners[t]||[])])f({type:t,target:this});}
    load(){this.loadCalls++;}removeAttribute(k){if(k==='src')this.src='';}
    play(){this.playCalls++;this.paused=false;this.emit('playing');return Promise.resolve();}
    pause(){this.pauseCalls++;const was=!this.paused;this.paused=true;if(was)this.emit('pause');}
  }
  const math=Object.create(Math);math.random=()=>0.5;
  const winListeners={};
  const context={console,document,localStorage:sharedStorage,Audio:FakeAudio,Math:math,Date,JSON,Set,Map,Promise,URL,Number,String,Object,Array,Error,setTimeout,clearTimeout,setImmediate,clearImmediate,setInterval:()=>0,clearInterval:()=>{},BroadcastChannel:undefined,fetch:async()=>({ok:true,json:async()=>JSON.parse(JSON.stringify(manifest))}),SBB_CONFIG:{soundtrackBase:'https://api.test/api/soundtrack'},addEventListener:(t,f)=>{(winListeners[t]||(winListeners[t]=[])).push(f);}};
  context.window=context;
  vm.createContext(context);vm.runInContext(source,context,{filename:'site-soundtrack.js'});
  return {context,api:context.SBB_SOUNDTRACK,Audio:FakeAudio,elements,winListeners,source};
}
(async()=>{
  const storage=makeStorage(new Map());
  const one=boot(storage);await one.api.init();
  assert.equal(one.Audio.instances.length,1,'there must be exactly one soundtrack Audio element');
  const audio=one.Audio.instances[0];

  // First highlight starts the site soundtrack.
  one.api.setPlaybackState('starting');await tick();await tick();
  one.api.setPlaybackState('playing');await tick();
  assert.equal(audio.paused,false,'soundtrack should play with highlight');
  const firstTrack=one.api.snapshot().currentTrack.id;
  audio.currentTime=37;
  const firstSrc=audio.src, firstLoads=audio.loadCalls;

  // Clip handoff must NOT become a soundtrack handoff.
  one.api.setPlaybackState('ready');await tick();
  one.api.setPlaybackState('starting');await tick();
  one.api.setPlaybackState('buffering');await tick();
  one.api.setPlaybackState('playing');await tick();
  assert.equal(one.api.snapshot().currentTrack.id,firstTrack,'video change must keep the same soundtrack track');
  assert.equal(audio.src,firstSrc,'video change must not reload soundtrack URL');
  assert.equal(audio.loadCalls,firstLoads,'video change must not reload soundtrack media');
  assert.equal(audio.currentTime,37,'video change must preserve soundtrack position');
  assert.equal(one.Audio.instances.length,1,'video changes must never create another soundtrack Audio element');

  // Music button must pause/resume THIS exact stream, not create/select a second track.
  one.api.toggle();
  assert.equal(audio.paused,true,'soundtrack toggle off must pause the only audio stream');
  const pausedTrack=one.api.snapshot().currentTrack.id, pausedSrc=audio.src, pausedTime=audio.currentTime;
  one.api.toggle();await tick();await tick();
  assert.equal(one.api.snapshot().currentTrack.id,pausedTrack,'soundtrack toggle on must resume the same track');
  assert.equal(audio.src,pausedSrc,'soundtrack toggle on must reuse the same audio URL');
  assert.equal(audio.currentTime,pausedTime,'soundtrack toggle on must resume the same position');
  assert.equal(one.Audio.instances.length,1,'soundtrack toggle must never create a second audio stream');

  // Explicit VIDEO pause controls the same soundtrack stream.
  one.api.setPlaybackState('paused');
  assert.equal(audio.paused,true,'video pause must pause soundtrack');
  const pauseTrack=one.api.snapshot().currentTrack.id,pauseTime=audio.currentTime;
  one.api.setPlaybackState('ready');await tick();
  assert.equal(audio.paused,true,'READY after a real pause must not restart soundtrack');
  one.api.setPlaybackState('playing');await tick();await tick();
  assert.equal(one.api.snapshot().currentTrack.id,pauseTrack,'video resume must keep soundtrack track');
  assert.equal(audio.currentTime,pauseTime,'video resume must keep soundtrack position');

  // Only explicit Next or natural song end may select a new song.
  const beforeNext=one.api.snapshot().currentTrack.id;
  one.api.skip();await tick();await tick();
  assert.notEqual(one.api.snapshot().currentTrack.id,beforeNext,'Next should intentionally replace the current track');
  assert.equal(one.Audio.instances.length,1,'Next still uses the one audio element');

  // Re-evaluating the script in the same page must reuse the singleton, not create audio #2.
  const sameApi=one.context.SBB_SOUNDTRACK;
  vm.runInContext(source,one.context,{filename:'site-soundtrack-second-load.js'});
  assert.equal(one.context.SBB_SOUNDTRACK,sameApi,'duplicate script load must reuse soundtrack singleton');
  assert.equal(one.Audio.instances.length,1,'duplicate script load must not create another Audio element');

  // Second tab respects owner lease.
  const secondTab=boot(storage);await secondTab.api.init();
  secondTab.api.setPlaybackState('playing');await tick();await tick();
  assert.equal(secondTab.Audio.instances[0].paused,true,'fresh owner lease must keep a second tab silent');

  // No-repeat cycle survives reload.
  const storage2=makeStorage(new Map());
  const a=boot(storage2);await a.api.init();
  a.api.setPlaybackState('paused');
  const start=a.api.snapshot().currentTrack.id;a.api.skip();const second=a.api.snapshot().currentTrack.id;a.api.skip();const third=a.api.snapshot().currentTrack.id;
  assert.equal(new Set([start,second,third]).size,3,'first cycle must not repeat');
  const persisted=JSON.parse(storage2.getItem('sbb:soundtrack:v2'));
  assert.ok(Array.isArray(persisted.remainingIds)&&persisted.remainingIds.length===2,'storage must persist exact remaining bag');
  storage2.removeItem('sbb:soundtrack:owner:v1');
  const b=boot(storage2);await b.api.init();
  assert.equal(b.api.snapshot().currentTrack.id,third,'reload must resume same current track');
  const expectedRemaining=[...persisted.remainingIds], afterReload=[];b.api.setPlaybackState('paused');
  for(let i=0;i<expectedRemaining.length;i++){b.api.skip();afterReload.push(b.api.snapshot().currentTrack.id);}
  assert.deepEqual(afterReload,expectedRemaining,'reload must finish remaining bag before recycling');

  console.log('PASS: v4.1.31 persistent one-audio soundtrack runtime invariants');
})().catch(err=>{console.error(err);process.exit(1);});

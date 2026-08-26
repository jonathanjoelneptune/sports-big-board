'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'architecture/site-soundtrack.js'),'utf8');
const manifest={
  tracks:[1,2,3,4,5].map(n=>({id:`t${n}`,title:`Track ${n}`,tier:n<3?'CORE':'ROTATION',file:`tracks/t${n}.mp3`,weight:1,durationSeconds:120})),
  playbackDefaults:{defaultMusicVolume:.16,highlightPlayingVolume:.10,repeatOnlyAfterBagExhausted:true,singleActiveAudioStream:true,preloadNextTrack:false,persistentAcrossVideoChanges:false,newSongOnClipChange:true,continueSongsDuringLongClip:true,enabledOnExperienceStart:true}
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
  const audio=one.Audio.instances[0],toggle=one.elements.get('soundtrackToggle');

  // Pre-launch player warmup must never secretly start music while UI is OFF.
  one.api.setPlaybackState('starting','clip-a');await tick();await tick();
  assert.equal(audio.paused,true,'pre-launch video warmup must not start soundtrack');
  assert.equal(one.api.snapshot().enabled,false,'soundtrack must be disabled before experience start');
  assert.equal(toggle.attrs['aria-pressed'],'false','pre-launch soundtrack UI must truthfully show OFF');

  // The red launch button explicitly starts soundtrack ON for the current clip.
  one.api.startExperience('clip-a');
  one.api.setPlaybackState('starting','clip-a');await tick();await tick();
  one.api.setPlaybackState('playing','clip-a');await tick();
  assert.equal(audio.paused,false,'soundtrack should start with launched highlight');
  assert.equal(one.api.snapshot().enabled,true,'launch must enable soundtrack');
  assert.equal(toggle.attrs['aria-pressed'],'true','UI must show ON whenever launch-started music is enabled');
  const clipATrack=one.api.snapshot().currentTrack.id;
  audio.currentTime=31;

  // Music button controls the exact current clip song, not a second track.
  one.api.toggle();
  assert.equal(audio.paused,true,'music toggle off pauses current song');
  const pausedTrack=one.api.snapshot().currentTrack.id,pausedSrc=audio.src,pausedTime=audio.currentTime;
  one.api.toggle();await tick();await tick();
  assert.equal(one.api.snapshot().currentTrack.id,pausedTrack,'music toggle on resumes same clip song');
  assert.equal(audio.src,pausedSrc,'music toggle must not replace soundtrack URL');
  assert.equal(audio.currentTime,pausedTime,'music toggle must resume same position');
  assert.equal(one.Audio.instances.length,1,'toggle can never create a second stream');

  // A NEW video clip intentionally gets a NEW song and resets music position.
  one.api.setPlaybackState('ready','clip-b');await tick();
  const clipBTrack=one.api.snapshot().currentTrack.id;
  assert.notEqual(clipBTrack,clipATrack,'clip change must select a new soundtrack song');
  assert.equal(audio.paused,true,'READY clip is not playing yet, so soundtrack stays paused');
  assert.equal(audio.currentTime,0,'new clip soundtrack starts from beginning');
  one.api.setPlaybackState('starting','clip-b');await tick();await tick();
  one.api.setPlaybackState('playing','clip-b');await tick();
  assert.equal(audio.paused,false,'new clip song starts with new video');

  // Repeated state changes for the SAME clip never choose extra songs.
  const sameTrack=one.api.snapshot().currentTrack.id,sameSrc=audio.src;
  one.api.setPlaybackState('buffering','clip-b');await tick();
  one.api.setPlaybackState('playing','clip-b');await tick();
  assert.equal(one.api.snapshot().currentTrack.id,sameTrack,'same clip state changes must keep its assigned song');
  assert.equal(audio.src,sameSrc,'same clip must keep same soundtrack URL');

  // Explicit VIDEO pause/resume controls that clip's assigned song.
  audio.currentTime=44;
  one.api.setPlaybackState('paused','clip-b');
  assert.equal(audio.paused,true,'video pause must pause soundtrack');
  one.api.setPlaybackState('playing','clip-b');await tick();await tick();
  assert.equal(one.api.snapshot().currentTrack.id,sameTrack,'video resume keeps same clip song');
  assert.equal(audio.currentTime,44,'video resume keeps same music position');

  // Long highlight: when song ends, another song starts without changing clip.
  const beforeEnded=one.api.snapshot().currentTrack.id;
  audio.paused=false;audio.emit('ended');await tick();await tick();
  assert.notEqual(one.api.snapshot().currentTrack.id,beforeEnded,'song end during long clip advances soundtrack');
  assert.equal(one.api.snapshot().currentClipKey,'clip-b','song end must stay associated with same video clip');
  assert.equal(audio.paused,false,'next soundtrack song should continue during long highlight');

  // Next is explicit manual advance and still uses same single Audio element.
  const beforeNext=one.api.snapshot().currentTrack.id;
  one.api.skip();await tick();await tick();
  assert.notEqual(one.api.snapshot().currentTrack.id,beforeNext,'Next intentionally replaces soundtrack song');
  assert.equal(one.Audio.instances.length,1,'Next must still use only one Audio element');

  // If music is turned off, changing clips may assign a new song but must not autoplay it.
  one.api.toggle();assert.equal(one.api.snapshot().enabled,false);
  one.api.setPlaybackState('starting','clip-c');await tick();
  assert.equal(audio.paused,true,'disabled soundtrack must stay silent on later clip changes');
  const clipCTrack=one.api.snapshot().currentTrack.id;
  one.api.toggle();await tick();await tick();
  assert.equal(one.api.snapshot().currentTrack.id,clipCTrack,'turning soundtrack back on uses current clip song');
  assert.equal(audio.paused,false,'turning soundtrack back on resumes current clip soundtrack');

  // Duplicate script load cannot create another soundtrack runtime/audio object.
  const sameApi=one.context.SBB_SOUNDTRACK;
  vm.runInContext(source,one.context,{filename:'site-soundtrack-second-load.js'});
  assert.equal(one.context.SBB_SOUNDTRACK,sameApi,'duplicate script load must reuse singleton');
  assert.equal(one.Audio.instances.length,1,'duplicate script load must not create another Audio element');

  console.log('PASS: v4.2.2 clip-scoped one-audio soundtrack runtime invariants');
})().catch(err=>{console.error(err);process.exit(1);});

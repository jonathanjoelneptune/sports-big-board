'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'architecture/soundtrack-state-indicator.js'),'utf8');
class ClassList{constructor(){this.s=new Set();}toggle(k,v){v?this.s.add(k):this.s.delete(k);}contains(k){return this.s.has(k);}}
class Element{constructor(id=''){this.id=id;this.classList=new ClassList();this.dataset={};this.attrs={};this.listeners={};this.title='';}setAttribute(k,v){this.attrs[k]=String(v);}addEventListener(t,f){(this.listeners[t]||(this.listeners[t]=[])).push(f);}emit(t){for(const f of this.listeners[t]||[])f({type:t,target:this});}}
const button=new Element('soundtrackToggle'),body=new Element('body'),head={children:[],appendChild(el){this.children.push(el);}};
const elements=new Map([['soundtrackToggle',button]]),listeners={};
const document={readyState:'complete',head,body,getElementById:id=>elements.get(id)||head.children.find(x=>x.id===id)||null,createElement:tag=>new Element(tag),addEventListener(){}};
const audio=new Element('audio');audio.muted=false;audio.paused=true;audio.volume=.1;
let soundtrack={enabled:false,experienceStarted:false,available:true,playbackState:'idle',tabOwnsAudio:false,currentTrack:null};
let decision={status:'UNKNOWN',conflict:true};
const window={
  document,
  __SBB_SOUNDTRACK_SINGLETON__:{audio},
  SBB_SOUNDTRACK:{snapshot:()=>({...soundtrack})},
  SBB_MEDIA_INTELLIGENCE:{snapshot:()=>({currentDecision:{...decision}})},
  SBB_PLAYBACK_SESSION:{subscribe:fn=>{window._playback=fn;return()=>{};}},
  addEventListener:(t,f)=>{(listeners[t]||(listeners[t]=[])).push(f);},
  dispatchEvent:()=>{},
};
const context={window,document,CustomEvent:function(type,opts){this.type=type;this.detail=opts?.detail;},Date,setTimeout,clearTimeout,setInterval:()=>1,clearInterval,console};
context.globalThis=context;vm.createContext(context);vm.runInContext(source,context,{filename:'soundtrack-state-indicator.js'});
const api=window.SBB_SOUNDTRACK_STATE_INDICATOR;
assert(api,'indicator API missing');
assert.equal(api.snapshot().state,'off');
assert(button.classList.contains('sbb-music-state-off'),'OFF must be neutral state');

soundtrack={...soundtrack,enabled:true,experienceStarted:true,playbackState:'playing',tabOwnsAudio:true,currentTrack:{title:'Track 1'}};
audio.paused=false;audio.muted=false;audio.volume=.1;api.refresh();
assert.equal(api.snapshot().state,'playing');
assert(button.classList.contains('sbb-music-state-playing'),'PLAYING state must be green class');
assert(!button.classList.contains('sbb-music-state-suppressed'));
assert.equal(button.dataset.sbbSoundtrackState,'playing');

decision={status:'HAS_MUSIC',conflict:true};audio.muted=true;api.refresh();
assert.equal(api.snapshot().state,'suppressed');
assert(button.classList.contains('sbb-music-state-suppressed'),'SUPPRESSED state must be yellow class');
assert(button.title.includes('suppressed'),'suppressed tooltip must be explicit');
assert.equal(body.attrs['data-sbb-soundtrack-state'],'suppressed');

audio.muted=false;audio.paused=true;api.refresh();
assert.equal(api.snapshot().state,'off','paused soundtrack is unhighlighted');
assert(button.classList.contains('sbb-music-state-off'));
console.log('PASS: v4.5.6 soundtrack button OFF/PLAYING/SUPPRESSED indicator');

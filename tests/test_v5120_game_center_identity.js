'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const elements=new Map();
function classList(){return {add(){},remove(){},toggle(){}};}
function el(id){
  if(!elements.has(id))elements.set(id,{id,classList:classList(),innerHTML:'',textContent:'',querySelector(){return null;},querySelectorAll(){return[];},addEventListener(){}});
  return elements.get(id);
}
const document={
  readyState:'loading',addEventListener(){},querySelectorAll(){return[];},getElementById:id=>el(id)
};
let getCalls=0,resolveGet;
const pending=new Promise(resolve=>{resolveGet=resolve;});
const context={console,document,setTimeout,clearTimeout,AbortController,DOMException,Date,performance:{now:()=>Date.now()}};
context.window=context;
context.SBB_GAME_CENTER={
  identity:()=>({key:'MLB|2026-08-22|torontobluejays|clevelandguardians|'}),
  peek:()=>null,
  get:()=>{getCalls++;return pending;}
};
context.SBB_SELECTED_EVENT={subscribe(){},get(){return null;}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root,'ui/game-center-view.js'),'utf8'),context,{filename:'game-center-view.js'});
const view=context.SBB_GAME_CENTER_VIEW;assert(view,'game center view installed');
assert.equal(view.version,'1.8-v5.1.20');
const evt={competitionId:'MLB',eventId:'123',date:'2026-08-22',status:'Final',awayTeam:{name:'Toronto Blue Jays'},homeTeam:{name:'Cleveland Guardians'},awayScore:1,homeScore:6};
const p1=view.load(evt);const p2=view.load({...evt,status:'Final'});
assert.equal(getCalls,1,'same canonical event joins one in-flight request');
assert.equal(view.snapshot().joined,1,'same-event notification counted as joined');
assert.equal(view.snapshot().active,true);
view.clear();
resolveGet({});
Promise.resolve(p1).then(()=>Promise.resolve(p2)).then(()=>{
  assert.equal(view.snapshot().active,false);
  console.log('PASS v5.1.20 Game Center same-event single-flight invariant');
}).catch(err=>{console.error(err);process.exitCode=1;});

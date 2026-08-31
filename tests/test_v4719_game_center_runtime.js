'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync('architecture/game-center-multisport-view.js','utf8');
assert(src.includes('PUBLIC Game Center cache/selected-event contracts'));
assert(src.includes('SBB_GAME_CENTER?.peek?.(event)'));
assert(!src.includes('window.SBB_GAME_CENTER?.get?.(event'),'multisport enhancement must not issue its own Game Center request');
assert(!src.includes('view?.data?.()'),'must not depend on unexported private renderer data');

// Load the production module with binding deferred, then exercise its exported
// real HTML builders instead of a fake view.data() bridge.
global.window=global;
global.document={readyState:'loading',addEventListener(){},getElementById(){return null;},head:{appendChild(){}}};
global.MutationObserver=class{observe(){}};
global.queueMicrotask=fn=>fn();
vm.runInThisContext(src,{filename:'game-center-multisport-view.js'});
const view=global.SBB_GAME_CENTER_MULTISPORT_VIEW;
assert.equal(view.version,'4.7.20');
const cfb={competitionId:'CFB',scoreboard:{away:{team:{abbreviation:'SJSU'},score:26},home:{team:{abbreviation:'USC'},score:42},periods:[
  {label:'Q1',away:7,home:7},{label:'Q2',away:10,home:14},{label:'Q3',away:3,home:7},{label:'Q4',away:6,home:14}
]}};
const football=view.periodCard(cfb);
for(const token of ['Q1','Q2','Q3','Q4','SJSU','USC','>26<','>42<'])assert(football.includes(token),token);
const mlb={competitionId:'MLB',scoreboard:{away:{team:{abbreviation:'BOS'},score:2},home:{team:{abbreviation:'NYY'},score:9},innings:[
  {num:1,away:0,home:2},{num:2,away:1,home:3},{num:3,away:1,home:0}
],totals:{away:{runs:2,hits:7,errors:1},home:{runs:9,hits:12,errors:0}}}};
const baseball=view.baseballCard(mlb);
for(const token of ['R</th><th>H</th><th>E','BOS','NYY','>7<','>12<'])assert(baseball.includes(token),token);
console.log('PASS: v4.7.20 retains real Game Center public-cache linescore path without duplicate request ownership');

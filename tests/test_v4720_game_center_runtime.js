'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync('architecture/game-center-multisport-view.js','utf8');
assert(src.includes('Sports Big Board v4.7.20'));
assert(src.includes('SBB_GAME_CENTER?.peek?.(event)'));
assert(!src.includes('window.SBB_GAME_CENTER?.get?.(event'),'multisport chrome must never become a second request owner');
assert(src.includes('ui/game-center-view.js is the ONLY request owner'));
assert(src.includes("version:'4.7.20'"));

global.window=global;
global.document={readyState:'loading',addEventListener(){},getElementById(){return null;},head:{appendChild(){}}};
global.MutationObserver=class{observe(){}};
global.queueMicrotask=fn=>fn();
vm.runInThisContext(src,{filename:'game-center-multisport-view.js'});
const view=global.SBB_GAME_CENTER_MULTISPORT_VIEW;
const football=view.periodCard({competitionId:'CFB',scoreboard:{away:{team:{abbreviation:'SJSU'},score:26},home:{team:{abbreviation:'USC'},score:42},periods:[
  {label:'Q1',away:7,home:7},{label:'Q2',away:10,home:14},{label:'Q3',away:3,home:7},{label:'Q4',away:6,home:14}
]}});
for(const token of ['Q1','Q2','Q3','Q4','SJSU','USC','>26<','>42<'])assert(football.includes(token),token);
const baseball=view.baseballCard({competitionId:'MLB',scoreboard:{away:{team:{abbreviation:'ARI'},score:0},home:{team:{abbreviation:'SF'},score:7},innings:[
  {num:1,away:0,home:2},{num:2,away:0,home:1},{num:3,away:0,home:4}
],totals:{away:{runs:0,hits:4,errors:1},home:{runs:7,hits:10,errors:0}}}});
for(const token of ['R</th><th>H</th><th>E','ARI','SF','>4<','>10<'])assert(baseball.includes(token),token);
console.log('PASS: v4.7.20 single-owner Game Center linescore path');

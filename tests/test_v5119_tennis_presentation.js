'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const document={readyState:'loading',addEventListener(){}};
const context={console,document,setTimeout,clearTimeout,requestAnimationFrame:fn=>fn()};
context.window=context;context.addEventListener=()=>{};
context.SBB_FRONTEND_REGISTRY={snapshot:()=>({competitions:[{id:'USOPEN-2026',name:'2026 US Open',sportId:'tennis'}]})};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root,'architecture/tennis-presentation.js'),'utf8'),context,{filename:'tennis-presentation.js'});
const ui=context.SBB_TENNIS_PRESENTATION;assert(ui,'tennis presentation installed');
assert.equal(ui.version,'5.1.19');
assert.equal(ui.compactName('Lucrezia Stefanini','54'),'#54 L. Stefanini');
assert.equal(ui.compactName('Dayana Yastremska',''),'D. Yastremska');
assert.equal(ui.roundShort('Round'),'');
assert.equal(ui.roundShort('Round 1'),'R1');
assert.equal(ui.roundShort('Round of 16'),'R16');
assert.equal(ui.roundShort('Quarterfinal'),'QF');
assert.equal(ui.roundShort('Semifinal'),'SF');
assert.equal(ui.roundShort('Final'),'F');
assert.equal(ui.isTennis({competitionId:'USOPEN-2026',sportId:'sports'}),true);
// Presentation decorates existing ribbon DOM without mutating the Event/ScoreDateStore.
const awayNode={},homeNode={},chips=[];
const card={__sbbMatch:{competitionId:'USOPEN-2026',sportId:'sports',round:'Round 1',awayTeam:{name:'Lucrezia Stefanini',rank:'54'},homeTeam:{name:'Dayana Yastremska',rank:'31'}},
  querySelector:()=>null,querySelectorAll:sel=>sel==='.score-team-abbr'?[awayNode,homeNode]:[],classList:{add(){},remove(){}},appendChild:x=>chips.push(x)};
document.querySelectorAll=sel=>sel==='.score-card'?[card]:[];
document.createElement=()=>({className:'',textContent:'',title:''});
ui.decorateCards();
assert.equal(awayNode.textContent,'#54 L. Stefanini');assert.equal(homeNode.textContent,'#31 D. Yastremska');assert.equal(chips[0].textContent,'R1');
console.log('PASS v5.1.19 tennis presentation invariants');

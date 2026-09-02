'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');

let stored=null;
const document={
  readyState:'loading',
  addEventListener(){},
  querySelectorAll(){return[];},
  getElementById(){return null;},
  createElement(){return {classList:{add(){},remove(){},toggle(){}},appendChild(){},querySelector(){return null;},querySelectorAll(){return[];}};},
  head:{appendChild(){}},
  body:{classList:{toggle(){}}}
};
const context={console,document,setTimeout,clearTimeout,Promise,queueMicrotask,Date};
context.window=context;
context.addEventListener=()=>{};
context.SBB_FRONTEND_REGISTRY={snapshot:()=>({competitions:[{id:'USOPEN-2026',name:'2026 US Open',sportId:'tennis'}]})};
context.storeScoreDateLeague=(league,date,rows)=>{stored={league,date,rows};return rows;};
context.SBB_SCORE_DATE={snapshot:()=>({browseDate:'2026-09-01',today:'2026-09-01'}),subscribe(){},matches(){return[];},hasLeagueMatchesSnapshot(){return false;},setMatches(){}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root,'architecture/tennis-presentation.js'),'utf8'),context,{filename:'tennis-presentation.js'});

const ui=context.SBB_TENNIS_PRESENTATION;assert(ui,'tennis presentation installed');
assert.equal(ui.version,'5.1.20');
assert.equal(ui.compactName('Mirra Andreeva','5'),'#5 M. Andreeva');
assert.equal(ui.compactName('Tereza Valentova',''),'T. Valentova');
assert.equal(ui.roundRibbonLabel({competitionId:'USOPEN-2026',roundName:'Round of 128'}),'ROUND 1');
assert.equal(ui.roundRibbonLabel({competitionId:'USOPEN-2026',roundName:'Round of 64'}),'ROUND 2');
assert.equal(ui.roundRibbonLabel({competitionId:'USOPEN-2026',roundName:'Round of 32'}),'ROUND 3');
assert.equal(ui.roundRibbonLabel({competitionId:'USOPEN-2026',roundName:'Round of 16'}),'R16');
assert.equal(ui.roundRibbonLabel({competitionId:'USOPEN-2026',roundName:'Quarterfinal'}),'QF');
assert.equal(ui.roundRibbonLabel({competitionId:'USOPEN-2026',roundName:'Semifinal'}),'SEMIS');
assert.equal(ui.roundRibbonLabel({competitionId:'USOPEN-2026',roundName:'Final'}),'FINAL');
assert.equal(ui.countryCodeOf({group:'USA'}),'US');
assert.equal(ui.countryCodeOf({country:'Czechia'}),'CZ');
assert.equal(ui.flagEmoji('US'),'🇺🇸');

const originalMatch={
  competitionId:'USOPEN-2026',sportId:'tennis',roundName:'Round of 128',
  awayTeam:{name:'Mirra Andreeva',rank:'5',group:'RUS',abbreviation:'AND'},
  homeTeam:{name:'Tereza Valentova',group:'CZE',abbreviation:'VAL'},
  awayScore:1,homeScore:0
};
context.storeScoreDateLeague('USOPEN-2026','2026-09-01',[originalMatch]);
assert(stored,'wrapped score store invoked');
assert.equal(stored.rows[0].awayTeam.abbreviation,'#5 M. Andreeva','first score-card render gets stable tennis label');
assert.equal(stored.rows[0].homeTeam.abbreviation,'T. Valentova','provider abbreviation is replaced before render');
assert.equal(stored.rows[0].awayTeam.providerAbbreviation,'AND');
assert.equal(stored.rows[0].awayScore,1,'scores are preserved by presentation projection');
assert.equal(originalMatch.awayTeam.abbreviation,'AND','source canonical row is not mutated');
console.log('PASS v5.1.20 tennis pre-render/round/flag invariants');

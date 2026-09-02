'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'architecture/tennis-presentation.js'),'utf8');

// Performance firewall: the v5.1.20 scroll/layout hot path must stay gone.
for(const forbidden of [
  "addEventListener('scroll'", 'getBoundingClientRect', 'getClientRects',
  'IOC_TO_ISO2', 'COUNTRY_TO_ISO2', 'storeScoreDateLeague=wrapped',
  'prepareRows(league,rows)', "querySelectorAll('.score-team-abbr')",
  "querySelectorAll('.score-team-row')"
]) assert(!source.includes(forbidden),`frontend hot-path computation returned: ${forbidden}`);
assert(source.includes("authority:'BACKEND_DAY_STATE'"),'backend presentation authority advertised');

const cards=[];
const document={
  readyState:'complete',body:{classList:{toggle(){}}},
  getElementById(){return null;},createElement(){return {id:'',textContent:'',appendChild(){}};},
  querySelectorAll(sel){return sel==='.score-card'?cards:[];},
  addEventListener(){},head:{appendChild(){}}
};
const listeners={};
const context={console,document,window:null};context.window=context;
context.addEventListener=(name,fn)=>{listeners[name]=fn;};
context.SBB_SELECTED_EVENT={subscribe(){},get(){return null;}};
vm.createContext(context);
vm.runInContext(source,context,{filename:'tennis-presentation.js'});
const ui=context.SBB_TENNIS_PRESENTATION;
assert(ui,'tennis presentation installed');
assert.equal(ui.version,'5.1.21');
assert.equal(ui.authority,'BACKEND_DAY_STATE');
const match={sportId:'tennis',__sbbTennisPresentation:'5.1.21-backend-tennis-ribbon-1',ribbonContextLabel:'ROUND 2'};
assert.equal(ui.roundRibbonLabel(match),'ROUND 2');
assert.strictEqual(ui.preparedMatch(match),match);
const rows=[match];assert.strictEqual(ui.prepareRows('USOPEN-2026',rows),rows);
assert.equal(ui.countryCodeOf({countryCode:'RU'}),'RU');
assert.equal(ui.flagEmoji({flagEmoji:'🇷🇺'}),'🇷🇺');
console.log('PASS v5.1.21 thin tennis frontend invariants');

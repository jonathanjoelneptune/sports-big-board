'use strict';
const assert=require('assert');
const fs=require('fs');
const path=require('path');
const vm=require('vm');
const ROOT=path.resolve(__dirname,'..');
const read=rel=>fs.readFileSync(path.join(ROOT,rel),'utf8');
const version=read('VERSION').trim();
assert(/^5\.0\.\d+$/.test(version),'v5.0.x score-date resilience baseline');

const window={};window.window=window;
const sandbox={window,console,Date,Math,Number,String,Object,Array,Set,Map,JSON,RegExp,Promise,Error,setTimeout,clearTimeout};
vm.createContext(sandbox);
vm.runInContext(read('architecture/score-date-store.js'),sandbox,{filename:'architecture/score-date-store.js'});
const store=window.SBB_SCORE_DATE;
assert.strictEqual(store.version,'1.1');
const date='2026-08-29';
store.setMatches(date,'CFB',[{id:'401864494',away:{name:'San Jose State'},home:{name:'USC'}}],{source:'DAY_STATE'});
store.setMatches(date,'MLB',[{id:'mlb-1'}],{source:'DAY_STATE'});
let health=store.dateHealth(date);
assert.strictEqual(health.games,2);
assert.strictEqual(health.authoritativeLeagues,2);
assert.strictEqual(store.hasMatchesSnapshot(date),true);

// A provider failure is metadata, never an authoritative empty scoreboard.
const kept=store.recordMatchFailure(date,'CFB',new Error('temporary provider timeout'),{source:'HISTORY'});
assert.strictEqual(kept.length,1,'last-known-good CFB rows survive a refresh failure');
assert.strictEqual(store.allMatches(date).length,2,'date inventory survives one league failure');
health=store.dateHealth(date);
assert.strictEqual(health.errorLeagues,1);
assert.strictEqual(health.games,2);

// Failure before any successful snapshot must not create a false empty snapshot.
const missing='2026-08-28';
store.recordMatchFailure(missing,'CFB',new Error('offline'),{source:'HISTORY'});
assert.strictEqual(store.hasMatchesSnapshot(missing),false,'error-only date is not an authoritative empty snapshot');
assert.strictEqual(store.dateHealth(missing).errorLeagues,1);

// A successful empty response is still legitimate and authoritative.
store.setMatches('2026-09-01','CFB',[],{source:'DAY_STATE'});
assert.strictEqual(store.hasMatchesSnapshot('2026-09-01'),true);
assert.strictEqual(store.dateHealth('2026-09-01').emptyLeagues,1);

const app=read('app.js');
assert(app.includes('preserveScoreDateLeagueOnError'),'app must preserve score inventory on transport/provider failure');
assert(app.includes('canonical historical score load failed; preserving last-known-good rows'),'historical errors must be non-destructive');
assert(app.includes('score load failed; preserving last-known-good rows'),'live/provider errors must be non-destructive');
assert(!app.includes("return {rows:storeScoreDateLeague(lg,date,[]),error:err,source:'HISTORY ERROR'}"),'legacy error=>empty snapshot path must be removed');
console.log(`PASS: ${version} last-known-good score-date read model + non-destructive refresh failures`);

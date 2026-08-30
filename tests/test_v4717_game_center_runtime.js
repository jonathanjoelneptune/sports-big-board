const fs=require('fs');
const vm=require('vm');
const assert=require('assert');
global.window=global;
vm.runInThisContext(fs.readFileSync('architecture/game-center-linescore.js','utf8'),{filename:'game-center-linescore.js'});
const cfb=global.SBB_GAME_CENTER_LINESCORE.periods({periods:[
  {num:1,away:7,home:7},{num:2,away:10,home:14},{num:3,away:3,home:7},{num:4,away:6,home:14}
]},'CFB');
assert.deepStrictEqual(cfb.map(x=>x.label),['Q1','Q2','Q3','Q4']);
const nba=global.SBB_GAME_CENTER_LINESCORE.periods({periods:[{num:5,away:11,home:9} ]},'NBA');
assert.strictEqual(nba[0].label,'OT');
const nhl=global.SBB_GAME_CENTER_LINESCORE.periods({periods:[{num:1},{num:2},{num:3},{num:4}]},'NHL');
assert.deepStrictEqual(nhl.map(x=>x.label),['P1','P2','P3','OT']);
const view=fs.readFileSync('architecture/game-center-multisport-view.js','utf8');
assert(view.includes('WIN PROBABILITY'));
assert(view.includes('s.winProbability'));
assert(view.includes('sbb-multisport-linescore'));
const releaseVersion=fs.readFileSync('VERSION','utf8').trim();
const index=fs.readFileSync('index.html','utf8');
const base=index.indexOf(`ui/game-center-view.js?v=${releaseVersion}`);
const enhanced=index.indexOf(`architecture/game-center-multisport-view.js?v=${releaseVersion}`);
assert(base>=0&&enhanced>base,'multisport view must load after the established Game Center owner');
console.log(`PASS: ${releaseVersion} retains v4.7.17 CFB Game Center + multisport linescore + win probability presentation`);

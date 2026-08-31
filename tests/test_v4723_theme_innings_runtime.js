const fs=require('fs');
const assert=require('assert');

const gc=fs.readFileSync('architecture/game-center-multisport-view.js','utf8');
assert(gc.includes('function timelineInnings(gc)'),'timeline innings fallback missing');
assert(gc.includes('gc?.scoringPlays'),'scoring-play fallback missing');
assert(gc.includes("ta===0&&th===0"),'0-0 inning reconstruction missing');
assert(gc.includes('RECONCILED FROM PLAY-BY-PLAY'),'reconciled linescore indicator missing');
assert(gc.includes('if(baseballEvent(gc))return baseballCard(gc);'),'baseball routing is still MLB-only');

const index=fs.readFileSync('index.html','utf8');
assert(index.includes('function retintDarkSurfaces()'),'dynamic light-mode dark-surface repair missing');
assert(index.includes('data-sbb-light-auto="1"'),'auto-light surface CSS missing');
assert(index.includes("attributeFilter:['class','style']"),'dynamic class/style changes are not monitored');
assert(index.includes('.coverage-pipeline'),'coverage pipeline light-mode surface missing');
assert(index.includes('.sport-feed-diagnostics'),'feed diagnostics light-mode surface missing');

console.log('PASS: v4.7.20 follow-on day/theme/innings UI contracts');

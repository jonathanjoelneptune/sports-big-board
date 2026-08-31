const fs=require('fs');
const assert=require('assert');

const gc=fs.readFileSync('architecture/game-center-multisport-view.js','utf8');
assert(gc.includes('function timelineInnings(gc)'),'timeline innings fallback missing');
assert(gc.includes('gc?.scoringPlays'),'scoring-play fallback missing');
assert(gc.includes("ta===0&&th===0"),'0-0 inning reconstruction missing');
assert(gc.includes('RECONCILED FROM PLAY-BY-PLAY'),'reconciled linescore indicator missing');
assert(gc.includes('if(baseballEvent(gc))return baseballCard(gc);'),'baseball routing is still MLB-only');

const index=fs.readFileSync('index.html','utf8');
assert(index.includes('CSS_ONLY_NO_MUTATION_OBSERVER'),'light mode is not using stable CSS ownership');
assert(!index.includes('new MutationObserver(scheduleRetint)'),'whole-DOM light-mode observer is still active');
assert(!index.includes('function retintDarkSurfaces()'),'computed retint loop is still active');
assert(index.includes('#scoreFilters > .sbb-active-event-filter'),'special-event main-row flicker guard missing');
assert(index.includes('body #sbbSpecialEventsMenu'),'late-injected special menu light override missing');
assert(index.includes('.coverage-pipeline'),'coverage pipeline light-mode surface missing');
assert(index.includes('.sport-feed-diagnostics'),'feed diagnostics light-mode surface missing');

console.log('PASS: v4.7.20 stable light-theme + special-event ownership contracts');

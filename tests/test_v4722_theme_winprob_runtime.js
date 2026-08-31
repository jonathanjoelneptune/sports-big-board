const fs=require('fs');
const assert=require('assert');

const view=fs.readFileSync('architecture/game-center-multisport-view.js','utf8');
assert(view.includes('gc-win-chart'),'win probability graph host missing');
assert(view.includes('gc-win-line gc-win-away'),'away probability polyline missing');
assert(view.includes('gc-win-line gc-win-home'),'home probability polyline missing');
assert(view.includes('sampledProbability(rows,max=160)'),'probability graph must keep DOM/path data bounded');
assert(!view.includes('gc-win-prob-table'),'legacy probability table must be removed');

const index=fs.readFileSync('index.html','utf8');
assert(index.includes('id="themeToggleBtn"'),'light-mode button missing');
assert(index.includes('data-sbb-theme="light"'),'light palette contract missing');
assert(index.includes("localStorage.setItem(KEY,theme)"),'theme preference must persist');
assert(index.includes("new CustomEvent('sbb:themechange'"),'theme-change event missing');

console.log('PASS: LLWS/Light Mode/Win Probability graph UI contracts');

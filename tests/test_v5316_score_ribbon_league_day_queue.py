#!/usr/bin/env python3
from pathlib import Path
import json
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
interrupt=(ROOT/'architecture'/'score-interrupt-queue-v5220.js').read_text()

assert version=='5.4.2', version
assert f'<script src="architecture/score-interrupt-queue-v5220.js?v={version}"></script>' in index

# The prior queue behavior is retained: score selection becomes a same-league/same-date
# queue with the clicked game's media fixed at the front. v5.4.2 performs that
# projection asynchronously so the click/tune itself remains responsive.
for token in [
    'non-blocking score-ribbon league-day queue + interrupt preservation',
    'function scheduleLeagueDayQueueExpansion(sessionOverride=null)',
    "const league=matchLeague(session.match)||matchLeague(PROGRAM[0]);",
    'const selected=PROGRAM.slice(0,selectedCount).filter(Boolean);',
    'PROGRAM=merged;',
    'build.session.leagueDayQueue=true;',
    'build.session.queueLeague=build.league;',
    'build.session.queueDate=build.date;',
    'build.session.queueLength=PROGRAM.length;',
    'function patchScoreSessionQueue()',
    'beginScorePlaybackSession=wrapped;',
    'scheduleLeagueDayQueueExpansion(',
    'expandLeagueDay:scheduleLeagueDayQueueExpansion',
]:
    assert token in interrupt, token

# Date queue construction may not synchronously call the legacy all-at-once helper.
assert 'programForScoreDate(date)' not in interrupt
assert 'scoreRibbonLeagueFilter=league' not in interrupt
assert 'setTimeout(()=>{' in interrupt
assert 'setTimeout(pump,BUILD_YIELD_MS)' in interrupt
assert 'selectionCount intentionally remains the number of clips in the clicked' in interrupt

# Execute the patch in a tiny browser-like context. Before queued tasks are flushed,
# only the clicked game may be in PROGRAM. After flushing, the other NFL games are
# appended and MLB remains excluded.
node_test=r'''
const fs=require('fs'),vm=require('vm');
const source=fs.readFileSync(process.argv[2],'utf8');
const tasks=[];
const g1={id:'nfl-a',matchId:'A',league:'NFL',date:'2026-09-02',verifiedPlayable:true,youtubeId:'a'};
const g2={id:'nfl-b',matchId:'B',league:'NFL',date:'2026-09-02',verifiedPlayable:true,youtubeId:'b'};
const g3={id:'nfl-c',matchId:'C',league:'NFL',date:'2026-09-02',verifiedPlayable:true,youtubeId:'c'};
const mlb={id:'mlb-x',matchId:'X',league:'MLB',date:'2026-09-02',verifiedPlayable:true,youtubeId:'x'};
const matches=[g1,g2,g3,mlb].map(x=>({...x,__sbbLeague:x.league}));
const ctx={
  console,
  performance:{now:(()=>{let t=0;return()=>++t;})()},
  window:{},
  document:{readyState:'complete',body:{dataset:{}},addEventListener(){}},
  PROGRAM:[g1],currentIndex:0,standbyIndex:0,userPlaybackSession:null,
  renderQueue(){},preflightUpcomingProgram(){},
  programGameIdentity(x){return x?.matchId||'';},
  sameGameProgramItem(a,b){return !!a&&!!b&&a.matchId===b.matchId;},
  scoreMatchesForDate(){return matches;},scoreRibbonImportance(){return 0;},scoreRibbonStableGameKey(m){return m.matchId||'';},
  scoreCardPlayableItems(m){return [m];},
  scoreCardPlaybackSelection(m,items){return {primary:items[0],selectionItems:items};},
  scoreMediaAirReady(){return true;},
  beginScorePlaybackSession(opts){ctx.userPlaybackSession={source:'score',selectionCount:opts.selectionCount,playbackDate:opts.playbackDate,match:opts.match};},
  resumeDateProgramAfterSelection(){},
  setTimeout(fn){tasks.push(fn);return tasks.length;},clearTimeout(){},
  requestAnimationFrame(fn){tasks.push(fn);return tasks.length;},
};
ctx.window=ctx;
vm.createContext(ctx);vm.runInContext(source,ctx);
ctx.beginScorePlaybackSession({selectionCount:1,playbackDate:'2026-09-02',match:{league:'NFL',date:'2026-09-02',matchId:'A'}});
if(JSON.stringify(ctx.PROGRAM.map(x=>x.id))!==JSON.stringify(['nfl-a']))throw new Error('score click was blocked by synchronous date build');
let guard=0;while(tasks.length&&guard++<100){tasks.shift()();}
const ids=ctx.PROGRAM.map(x=>x.id);
if(JSON.stringify(ids)!==JSON.stringify(['nfl-a','nfl-b','nfl-c']))throw new Error('wrong league-day queue '+JSON.stringify(ids));
if(!ctx.userPlaybackSession.leagueDayQueue||ctx.userPlaybackSession.queueLeague!=='NFL'||ctx.userPlaybackSession.queueLength!==3)throw new Error('session diagnostics missing');
if(ctx.userPlaybackSession.selectionCount!==1)throw new Error('selectionCount incorrectly expanded to whole date');
console.log(JSON.stringify({ids,queueLength:ctx.userPlaybackSession.queueLength,selectionCount:ctx.userPlaybackSession.selectionCount}));
'''
with tempfile.TemporaryDirectory() as td:
    script=Path(td)/'test.js'
    script.write_text(node_test)
    result=subprocess.run(['node',str(script),str(ROOT/'architecture'/'score-interrupt-queue-v5220.js')],capture_output=True,text=True,check=True)
    payload=json.loads(result.stdout.strip().splitlines()[-1])
    assert payload['ids']==['nfl-a','nfl-b','nfl-c'], payload
    assert payload['queueLength']==3, payload
    assert payload['selectionCount']==1, payload

print('PASS v5.4.2 retains league/day score queue while yielding construction off the score click')

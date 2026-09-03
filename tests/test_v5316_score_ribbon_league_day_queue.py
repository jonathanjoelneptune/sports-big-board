#!/usr/bin/env python3
from pathlib import Path
import json
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
interrupt=(ROOT/'architecture'/'score-interrupt-queue-v5220.js').read_text()

assert version=='5.3.16', version
assert f'<script src="architecture/score-interrupt-queue-v5220.js?v={version}"></script>' in index

# The score-card click itself stays fast in app.js: this module patches the
# post-commit session boundary and expands PROGRAM only after the selected media
# has already been resolved/committed.
for token in [
    'score-ribbon league-day queue + interrupt preservation',
    'function expandScoreSelectionToLeagueDay()',
    "const league=matchLeague(session.match)||matchLeague(PROGRAM[0]);",
    'scoreRibbonLeagueFilter=league;',
    "dateProgramWithSelectionFirst(date,selected)",
    'PROGRAM=[...deduped];',
    'session.leagueDayQueue=true;',
    'session.queueLeague=league;',
    'session.queueDate=date;',
    'session.queueLength=PROGRAM.length;',
    'function patchScoreSessionQueue()',
    'beginScorePlaybackSession=wrapped;',
    'expandScoreSelectionToLeagueDay();',
    'expandLeagueDay:expandScoreSelectionToLeagueDay',
]:
    assert token in interrupt, token

# Exact media can dedupe, but same-game blue-reel clips may not be collapsed.
assert 'same-game items are therefore not collapsed' in interrupt
assert '.filter(item=>!selected.some(sel=>itemId(item)===itemId(sel)||sameGame(item,sel)))' in interrupt

# No polling/re-render loop is allowed for this queue repair.
for forbidden in ['setInterval(', 'requestAnimationFrame(loop', 'new MutationObserver']:
    assert forbidden not in interrupt, forbidden

# Execute the patch in a tiny browser-like Node context. The clicked NFL game is
# committed first while the ribbon filter is ALL. The wrapper must temporarily
# scope date programming to NFL, restore the UI filter, and leave the clicked game
# at index 0 followed by the other NFL games. MLB must not enter the queue.
node_test=r'''
const fs=require('fs'),vm=require('vm');
const source=fs.readFileSync(process.argv[2],'utf8');
const logs=[];
const g1={id:'nfl-a',matchId:'A',league:'NFL',date:'2026-09-02',verifiedPlayable:true,youtubeId:'a'};
const g2={id:'nfl-b',matchId:'B',league:'NFL',date:'2026-09-02',verifiedPlayable:true,youtubeId:'b'};
const g3={id:'nfl-c',matchId:'C',league:'NFL',date:'2026-09-02',verifiedPlayable:true,youtubeId:'c'};
const mlb={id:'mlb-x',matchId:'X',league:'MLB',date:'2026-09-02',verifiedPlayable:true,youtubeId:'x'};
const ctx={
  console,
  window:{},
  document:{readyState:'complete',addEventListener(){}},
  PROGRAM:[g1],currentIndex:0,standbyIndex:0,scoreRibbonLeagueFilter:'ALL',userPlaybackSession:null,
  renderQueue(){logs.push(['render',ctx.PROGRAM.map(x=>x.id)]);},
  programGameIdentity(x){return x?.matchId||'';},
  sameGameProgramItem(a,b){return !!a&&!!b&&a.matchId===b.matchId;},
  programForScoreDate(date){
    const all=[g1,g2,g3,mlb];
    return all.filter(x=>x.date===date&&(ctx.scoreRibbonLeagueFilter==='ALL'||x.league===ctx.scoreRibbonLeagueFilter));
  },
  dateProgramWithSelectionFirst(date,selected){
    const base=ctx.programForScoreDate(date);
    const rest=base.filter(x=>!selected.some(sel=>ctx.sameGameProgramItem(x,sel)||x.id===sel.id));
    return [...selected,...rest];
  },
  beginScorePlaybackSession(opts){
    ctx.userPlaybackSession={source:'score',selectionCount:opts.selectionCount,playbackDate:opts.playbackDate,match:opts.match};
  },
  resumeDateProgramAfterSelection(){},
  setTimeout(fn){fn();return 1;},
  clearTimeout(){},
};
ctx.window=ctx;
vm.createContext(ctx);vm.runInContext(source,ctx);
ctx.beginScorePlaybackSession({selectionCount:1,playbackDate:'2026-09-02',match:{league:'NFL',date:'2026-09-02'}});
if(ctx.scoreRibbonLeagueFilter!=='ALL')throw new Error('UI league filter was not restored');
const ids=ctx.PROGRAM.map(x=>x.id);
if(JSON.stringify(ids)!==JSON.stringify(['nfl-a','nfl-b','nfl-c']))throw new Error('wrong league-day queue '+JSON.stringify(ids));
if(!ctx.userPlaybackSession.leagueDayQueue||ctx.userPlaybackSession.queueLeague!=='NFL'||ctx.userPlaybackSession.queueLength!==3)throw new Error('session diagnostics missing');
console.log(JSON.stringify({ids,filter:ctx.scoreRibbonLeagueFilter,queueLength:ctx.userPlaybackSession.queueLength}));
'''
with tempfile.TemporaryDirectory() as td:
    script=Path(td)/'test.js'
    script.write_text(node_test)
    result=subprocess.run(['node',str(script),str(ROOT/'architecture'/'score-interrupt-queue-v5220.js')],capture_output=True,text=True,check=True)
    payload=json.loads(result.stdout.strip().splitlines()[-1])
    assert payload['ids']==['nfl-a','nfl-b','nfl-c'], payload
    assert payload['filter']=='ALL', payload
    assert payload['queueLength']==3, payload

print('PASS v5.3.16 score-ribbon click expands to clicked league/date queue with clicked game first')

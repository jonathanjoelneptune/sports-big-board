#!/usr/bin/env python3
'''v5.5.0 controller navigation, fullscreen, commands, and playback-follow regression.'''
from pathlib import Path
import json
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text().strip()
assert VERSION=='5.5.0',VERSION
index=(ROOT/'index.html').read_text()
core=(ROOT/'architecture'/'controller-mode-v542.js').read_text()
nav=(ROOT/'architecture'/'controller-readiness-v540.js').read_text()
bridge=(ROOT/'architecture'/'controller-native-bridge-v544.js').read_text()
cs=(ROOT/'windows-controller-bridge'/'SportsBigBoardControllerBridge.cs').read_text()
fs=(ROOT/'ui'/'fullscreen-controller-v545.js').read_text()
follow=(ROOT/'ui'/'score-ribbon-playback-follow-v545.js').read_text()
follow_css=(ROOT/'ui'/'score-ribbon-playback-follow-v545.css').read_text()
map_txt=(ROOT/'CONTROLLER-REGION-MAP-v5.5.0.md').read_text()

# Release wiring.
for asset in [
 'ui/fullscreen-controller-v545.css','ui/score-ribbon-playback-follow-v545.css',
 'ui/score-ribbon-playback-follow-v545.js','ui/fullscreen-controller-v545.js',
 'architecture/controller-mode-v542.js','architecture/controller-readiness-v540.js'
]:
    assert f'{asset}?v={VERSION}' in index, asset

# D-pad score-ribbon -> league lane and deterministic horizontal traversal.
assert "region==='score-ribbon'&&direction==='up'" in nav
assert "candidate=preferredEntry('league-nav')" in nav
assert 'function orderedLeagueNeighbor' in nav
assert "region==='league-nav'" in nav
assert "focusables('league-nav'" in nav

# X/Square is now play/pause, not Play All.
assert '<b>${g.x}</b> Play / Pause' in core
assert 'if(index===BUTTON.X){playPause();return;}' in core
assert 'function playPause()' in core
assert 'if(index===BUTTON.X){playAll();return;}' not in core

# Both triggers open the special commands radial and mute is an explicit action.
assert "openRadial('commands')" in core
assert "radial?.type==='commands'" in core
for token in ["APP FULLSCREEN","VIDEO FULLSCREEN","EXIT FULLSCREEN","PLAY / PAUSE","MUTE / UNMUTE","GAME CENTER","LEAGUE VIEW","SETTINGS"]:
    assert token in core,token
assert 'function toggleActiveMute()' in core
assert "v.muted=!v.muted" in core and 'p.isMuted' in core and 'p.unMute' in core and 'p.mute' in core

# Fullscreen app button and controller fullscreen commands.
assert 'bigBoardFullscreenBtn' in fs and 'fullscreenBtn' in fs
assert 'requestFullscreen(appTarget(),{navigationUI:true})' in fs
assert "nativeCommand('app-fullscreen')" in fs and "nativeCommand('video-fullscreen')" in fs
assert "new Set(['app-fullscreen','video-fullscreen'])" in bridge
assert 'KeyboardCommand.Tap(0x7A)' in cs and 'KeyboardCommand.Tap(0x46)' in cs
# Retain compile hotfix.
assert 'new Thread(new ThreadStart(delegate { HandleClient(client); }))' in cs

# ALL/score ribbon follows the actual playing event and keeps it near third visible.
assert 'sbb-program-now-watching' in follow and 'sbb-program-now-watching' in follow_css
assert 'Math.max(0,idx-2)' in follow
assert "return clean(active?.dataset?.scoreFilter).toUpperCase()==='ALL';" in follow
assert 'requestAnimationFrame(run)' in follow
assert 'setInterval(' not in follow
assert 'NOW WATCHING' in follow_css

# Startup playback owns score-ribbon date/identity. Generic media `date` is a
# publication timestamp and cannot force a same-team game on today's slate.
for token in [
    'function strongEventDate(obj)',
    'function scoreCandidatesForPlayback(item)',
    'function completedMatch(match)',
    'function recapLike(item)',
    'function loosePlaybackMatches(item,rows)',
    'const loose=loosePlaybackMatches(item,rows);',
    'if(loose.length>1&&recapLike(item)){',
    'if(completed.length===1)return completed[0];',
    'if(!curatedActive&&item&&!match&&!strongEventDate(item)){',
    'const selected=curatedActive?rawSelected:(match&&rawSelected&&sameEvent(match,rawSelected)?rawSelected:null);',
]:
    assert token in follow, token

node_test=r'''
const fs=require('fs'),vm=require('vm');
const source=fs.readFileSync(process.argv[2],'utf8');
function classes(init=[]){const s=new Set(init);return{contains:x=>s.has(x),add:x=>s.add(x),remove:x=>s.delete(x),toggle(x,on){if(on)s.add(x);else s.delete(x)}};}
function card(id,date){
  return {
    dataset:{eventId:id,date},textContent:'Pittsburgh Pirates vs Chicago Cubs',
    classList:classes(['score-card']),hidden:false,isConnected:true,offsetLeft:0,offsetWidth:100,
    getBoundingClientRect(){return{width:100,height:50}},
    getAttribute(name){if(name==='aria-label')return `${date} Pittsburgh Pirates vs Chicago Cubs ${id}`;return ''},
    setAttribute(name,value){this[name]=value},removeAttribute(name){delete this[name]}
  };
}
const todayCard=card('TODAY-1','2026-09-13');
const yesterdayCard=card('YDAY-1','2026-09-12');
const host={scrollLeft:0,scrollWidth:500,clientWidth:300,querySelectorAll(){return[todayCard,yesterdayCard]},scrollTo({left}){this.scrollLeft=left}};
const today={eventId:'TODAY-1',league:'MLB',date:'2026-09-13',awayTeam:'Pittsburgh Pirates',homeTeam:'Chicago Cubs',status:'SCHEDULED'};
const yesterday={eventId:'YDAY-1',league:'MLB',date:'2026-09-12',awayTeam:'Pittsburgh Pirates',homeTeam:'Chicago Cubs',status:'FINAL'};
// Reproduce production: recap published today, but it belongs to yesterday's game.
const item={date:'2026-09-13',league:'MLB',title:'Pirates at Cubs highlights'};
let focused=null;
const tasks=[];
const body={classList:classes([])};
const document={
  readyState:'complete',body,addEventListener(){},
  querySelector(sel){if(sel.startsWith('#scoreFilters'))return{dataset:{scoreFilter:'ALL'}};return null;},
  querySelectorAll(sel){if(sel==='.sbb-program-now-watching')return[todayCard,yesterdayCard].filter(c=>c.classList.contains('sbb-program-now-watching'));return[];},
  getElementById(id){
    if(id==='scoreCells')return host;
    if(id==='currentTitle')return{textContent:'Pirates at Cubs highlights'};
    if(id==='sbbCurationCards')return null;
    return null;
  }
};
const ctx={
  console,document,currentIndex:0,PROGRAM:[item],clip:()=>item,
  scoreBrowseDate:'2026-09-13',scorePlaybackDate:'2026-09-13',
  scoreMatchesForDate:d=>d==='2026-09-12'?[yesterday]:d==='2026-09-13'?[today]:[],
  localDateISO:d=>d===-1?'2026-09-12':'2026-09-13',
  // Legacy behavior is intentionally wrong here. The playback-follow layer must
  // override it using score-slate evidence rather than publication date.
  launchScoreMatchForItem:()=>today,
  focusScoreRibbonForGame:x=>{focused=x;ctx.scoreBrowseDate=x.date;return true},
  scoreEventDate:o=>o.date||o.gameDate||'',
  sameGameProgramItem:(a,b)=>{
    const text=x=>`${x?.awayTeam||''} ${x?.homeTeam||''} ${x?.title||''}`.toLowerCase();
    return /pirates|pittsburgh/.test(text(a))&&/cubs|chicago/.test(text(a))&&/pirates|pittsburgh/.test(text(b))&&/cubs|chicago/.test(text(b));
  },
  requestAnimationFrame:fn=>{tasks.push(fn);return tasks.length},
  setTimeout:fn=>{tasks.push(fn);return tasks.length},
  MutationObserver:undefined,matchMedia:()=>({matches:true})
};
ctx.window=ctx;
ctx.window.SBB_SELECTED_EVENT={get:()=>today,subscribe(){}};
ctx.window.SBB_EVENT_IDENTITY={same:(a,b)=>a.eventId&&b.eventId&&a.eventId===b.eventId};
ctx.window.addEventListener=()=>{};
vm.createContext(ctx);vm.runInContext(source,ctx);

const first=ctx.SBB_SCORE_RIBBON_PLAYBACK_FOLLOW.reconcile();
if(focused!==yesterday)throw new Error('publication date caused today game to retain playback authority');
if(!first?.switchingDate||first.playbackDate!=='2026-09-12')throw new Error('ribbon did not switch to yesterday before scoring cards');
if(todayCard.classList.contains('sbb-program-now-watching'))throw new Error('today card was highlighted during date switch');

const second=ctx.SBB_SCORE_RIBBON_PLAYBACK_FOLLOW.reconcile();
if(!yesterdayCard.classList.contains('sbb-program-now-watching'))throw new Error('yesterday playback game was not highlighted');
if(todayCard.classList.contains('sbb-program-now-watching'))throw new Error('stale today selectedEvent stole NOW WATCHING');
console.log(JSON.stringify({focused:focused.eventId,highlighted:yesterdayCard.dataset.eventId,playbackDate:second.playbackDate,resolvedMatch:second.resolvedMatch,browseDate:ctx.scoreBrowseDate}));
'''
with tempfile.TemporaryDirectory() as td:
    script=Path(td)/'test.js'
    script.write_text(node_test)
    result=subprocess.run(['node',str(script),str(ROOT/'ui'/'score-ribbon-playback-follow-v545.js')],capture_output=True,text=True,check=True)
    payload=json.loads(result.stdout.strip().splitlines()[-1])
    assert payload['focused']=='YDAY-1', payload
    assert payload['highlighted']=='YDAY-1', payload
    assert payload['playbackDate']=='2026-09-12', payload
    assert payload['resolvedMatch'] is True, payload
    assert payload['browseDate']=='2026-09-12', payload

for token in ['X — Play / Pause','LT + RT — Special Commands radial','MUTE / UNMUTE','D-pad Up from the Score Ribbon']:
    assert token in map_txt,token

print('PASS v5.5.0 D-pad league navigation + X play/pause + special commands + fullscreen + playback-follow')

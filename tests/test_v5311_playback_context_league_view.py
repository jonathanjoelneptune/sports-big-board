#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
browse=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
league=(ROOT/'ui'/'league-view-v538.js').read_text()
league_css=(ROOT/'ui'/'league-view-v538.css').read_text()
backend=(ROOT/'sbb'/'league_view_v538.py').read_text()
verify=(ROOT/'VERIFY.sh').read_text()

assert version=='5.4.0',version

# Returning from curated/special-event browsing must surrender queue ownership
# before ALL/TODAY or a normal score click can render another queue.
for token in [
    "function releaseCuratedQueue(reason='return to daily programming')",
    'state.queueActive=false;state.queueItems=[];state.queueLabel=',
    "window.dispatchEvent(new CustomEvent('sbb:curated-queue-release'",
    "$('returnTodayBtn')?.addEventListener('click'",
    "if(requested==='ALL'||isCoreLeague(requested))releaseCuratedQueue",
]:
    assert token in browse,token
assert "releaseCuratedQueue('browse returned to daily programming')" in browse

# Explicit league navigation can update League View before a clip is chosen; once
# a score/video selection occurs, playback becomes authoritative again.
nav_pos=league.index('if(state.navLeague)')
item_pos=league.index('const item=activeProgram();')
context_pos=league.index('const context=curatedContext();',item_pos)
assert nav_pos<item_pos<context_pos
for token in [
    'function leagueFromItem(item)',
    'function leagueFromTitle(title=currentTitle())',
    "if(/\\bMLB\\b|MAJOR LEAGUE BASEBALL/.test(text))return 'MLB'",
    "if(context?.mode&&context.mode!=='daily')",
    "window.addEventListener('sbb:curated-queue-release'",
    "window.addEventListener('sbb:league-context'",
    "state.navLeague=''",
    'clearTimeout(state.syncTimer)',
]:
    assert token in league,token

# Standings are presented as readable sport-specific tables rather than tiny
# diagnostic rows. MLB/NFL expose conference columns with wildcard context.
for token in [
    'function tableHeaders(league)',
    "if(['EPL','MLS'].includes(league))return ['CLUB','MP','W-D-L','PTS','FORM']",
    "if(league==='MLB'||league==='NFL'||league==='NHL')inner+=wildcardCard",
    'league-view-cutoff',
    'league-view-conference-grid league-view-',
]:
    assert token in league,token
for token in [
    '.league-view-head h2{font-size:18px!important',
    '.league-view-table{font-size:8.1px!important',
    '.league-view-table td{height:32px!important',
    '.league-view-team img{width:22px!important;height:22px!important',
    '.league-view-conference-head strong{font-size:9px!important',
]:
    assert token in league_css,token

# Backend enriches the compact tables and produces NFL wild-card rows as well as
# MLB wild-card rows, while retaining MLB division-winner exclusion.
for token in [
    '"gamesPlayed": _stat_value',
    '"conferenceRecord": _stat_value',
    'if league in {"MLB", "NFL", "NHL"}:',
    'minimum_wildcard_seed = 4 if league == "MLB" else (5 if league == "NFL" else 999)',
    'key not in division_leaders',
]:
    assert token in backend,token

assert 'tests/test_v5311_playback_context_league_view.py' in verify
print('PASS v5.4.0 playback-context reset + playback-authoritative League View + readable standings')

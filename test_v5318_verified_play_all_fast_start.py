#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
browse=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
css=(ROOT/'ui'/'browse-curated-programming-v537.css').read_text()
verify=(ROOT/'VERIFY.sh').read_text()

assert version=='5.5.0', version
assert f'ui/browse-curated-programming-v537.css?v={version}' in index
assert f'ui/browse-curated-programming-v537.js?v={version}' in index
assert 'tests/test_v5318_verified_play_all_fast_start.py' in verify

# The database proof must survive conversion into a queue item so a known clip is
# not treated as cold media again after Browse has already resolved it.
for token in [
    '__sbbDatabaseVerified:true',
    '__sbbBrowserProven:',
    'runtimeSuccessAt:Number(media?.runtimeSuccessAt||0)||0',
    'verifiedAt:Number(media?.verifiedAt||0)||0',
    'embedAllowed:media?.embedAllowed!==false',
    'embeddable:media?.embeddable!==false',
]:
    assert token in browse, token

# Play All is intentionally safer than a direct card click: completed games only,
# exact verified media only, with Green/Purple preferred and browser-proven media
# ranked ahead of merely cold catalog verification.
for token in [
    'function playAllVerified(item)',
    'function playAllCandidateRank(item)',
    "tier==='green'?400:(tier==='extended'?360",
    'function playAllGameComplete(game)',
    'function playAllProjectGame(game)',
    'function playAllEligibleGames(games=state.games)',
    'const playableCount=playAllEligibleGames(state.games).length',
    'Play All • no completed games with verified media are ready yet',
    'verified completed games',
]:
    assert token in browse, token

# Today cannot begin with a scheduled/live/postponed game. Historical games may
# use a verified recap as completion proof while lazy score enrichment catches up.
for token in [
    'postponed|canceled|cancelled|scheduled|pregame|pre game|live|in progress|delayed|suspended',
    "if(date&&date<today)return hasScore||hasVerifiedRecap;",
    "if(date===today)return false;",
]:
    assert token in browse, token

# A bad/slow verified source cannot hold Play All for the old multi-retry window.
# Browser-proven media gets the shortest grace period, then same-game fallback,
# then the next completed verified game.
for token in [
    'function armPlayAllStartWatchdog(item,index)',
    'const timeoutMs=browserProven?5500:7500',
    'if(!state.queueActive||programKey(expectedCuratedItem())!==key)return;',
    'function advancePlayAllAfterSlowStart(item,index)',
    'v5.5.0 Play All fast same-game fallback',
    'v5.5.0 Play All skipped slow verified source',
    'clearPlayAllStartWatchdog();state.playAllMode=false',
]:
    assert token in browse, token

# Normal-league utility controls are compact independent pills with breathing room.
for token in [
    '#sbbBrowseSubnav:has(#sbbLeagueTodayBtn:not(.hidden)){',
    'gap:5px;',
    'margin-left:6px;',
    'height:25px!important;',
    'border-radius:7px!important;',
    'font-size:7.1px!important;',
]:
    assert token in css, token

print('PASS v5.5.0 compact league subnav + completed verified Play All + bounded fast-start fallback')

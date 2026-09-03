#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
interrupt=(ROOT/'architecture'/'score-interrupt-queue-v5220.js').read_text()
browse_css=(ROOT/'ui'/'browse-curated-programming-v537.css').read_text()
match_js=(ROOT/'ui'/'sport-match-center-v5317.js').read_text()
match_css=(ROOT/'ui'/'sport-match-center-v5317.css').read_text()
verify=(ROOT/'VERIFY.sh').read_text()

assert version=='5.3.18', version
assert f'ui/sport-match-center-v5317.css?v={version}' in index
assert f'ui/sport-match-center-v5317.js?v={version}' in index
assert 'tests/test_v5317_queue_performance_match_center.py' in verify

# Dense dates must be projected after the score click returns and one match per
# browser task. The old all-at-once date helper is forbidden in this patch.
for token in [
    'function scheduleLeagueDayQueueExpansion(sessionOverride=null)',
    'setTimeout(()=>{',
    'const pump=()=>{',
    'const match=build.rows[build.index++]',
    'setTimeout(pump,BUILD_YIELD_MS)',
    'build.index===1||build.index%BUILD_RENDER_EVERY===0',
    'slow score-date match projection yielded after one match',
    'cancelLeagueDayBuild(\'new score-ribbon selection\')',
    'leagueDayBuildSnapshot:',
]:
    assert token in interrupt, token
assert 'programForScoreDate(date)' not in interrupt
assert 'scoreRibbonLeagueFilter=league' not in interrupt
assert 'scoreRibbonImportance(' not in interrupt
assert 'setInterval(' not in interrupt

# TODAY / ALL / TEAM BROWSE are visually one subordinate green group only when
# normal league scope controls are visible. Special-event Browse remains separate.
selector='#sbbBrowseSubnav:has(#sbbLeagueTodayBtn:not(.hidden)) #sbbBrowseBtn'
assert selector in browse_css
for token in ['rgba(31,122,78,.99)','rgba(115,232,166,.58)','#8af0b5']:
    assert token in browse_css, token

# Provider failures become useful Match Center context, never an unavailable card.
for token in [
    "if(window.SBB_SPORT_MATCH_CENTER?.version==='5.3.18')return;",
    'SPORT MATCH CENTER',
    'MATCH CENTER',
    'function errorReason()',
    'game center unavailable|unable to load game data|did not finish loading',
    'function providerSupported(evt)',
    'function usefulEvent(evt)',
    "window.SBB_SELECTED_EVENT?.subscribe?.",
    'MutationObserver',
    'sbb-special-event-match-center',
    'RETRY DETAILED GAME CENTER',
]:
    assert token in match_js, token
assert 'setInterval(' not in match_js
assert 'body.sbb-sport-match-center-active:not(.sbb-special-event-match-center)' in match_css
assert '#sbbSportMatchCenter' in match_css

# There must be no app-wide observer: the only observer is scoped to Game Center.
assert "state.observer.observe(pane" in match_js

print('PASS v5.3.18 non-blocking league/day queue + green league subnav + resilient sport Match Center')

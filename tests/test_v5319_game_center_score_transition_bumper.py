#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text().strip()
assert VERSION=='5.4.6',VERSION
index=(ROOT/'index.html').read_text()
browse=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
browse_css=(ROOT/'ui'/'browse-curated-programming-v537.css').read_text()
league_css=(ROOT/'ui'/'league-view-v538.css').read_text()
score=(ROOT/'ui'/'game-center-score-authority-v5319.js').read_text()
bumper=(ROOT/'architecture'/'playback-transition-bumper-v5319.js').read_text()

# Normal leagues and special events use different exit language.
assert "special?'EXIT EVENT':'EXIT LEAGUE'" in browse
assert "state.specialContext?'Exit Event':'Exit League'" in browse

# Secondary league controls are smaller and horizontally separated.
assert 'gap:8px!important' in browse_css
assert 'height:23px!important' in browse_css

# Soccer Club column is deliberately compact so FORM sits next to standings data.
assert re.search(r'league-view-mls \.league-view-table th\.team-col\{width:28%!important\}',league_css)
assert 'th:last-child{width:37%!important}' in league_css

# Known SelectedEvent final scores reassert over stale provider 0-0 summaries.
assert 'Game Center score authority' in score
assert "setText(awayEl?.querySelector('.gc-team-score'),awayScore)" in score
assert "setText(homeEl?.querySelector('.gc-team-score'),homeScore)" in score
assert 'sbb-multisport-linescore tbody tr' in score
assert 'new MutationObserver' not in score
assert '__sbbScoreAuthorityV5320' in score

# Every first-frame transition owns a bumper until real playback is proved.
assert 'transition bumper authority' in bumper
assert "sameGameTransition(session,item)?'NEXT HIGHLIGHT':'COMING UP NEXT'" in bumper
assert "setVideoLoadingOverlay(false)" in bumper
assert 'actualPlaying(session)' in bumper
assert 'new MutationObserver' not in bumper
assert 'data-sbb-transition-bumper' in (ROOT/'ui'/'playback-transition-bumper-v5319.css').read_text()
assert 'Transition did not prove first-frame playback within 10 seconds' in bumper

for asset in ['ui/game-center-score-authority-v5319.js','architecture/playback-transition-bumper-v5319.js','ui/playback-transition-bumper-v5319.css']:
    assert f'{asset}?v={VERSION}' in index,asset

print(f'PASS v{VERSION} Game Center score authority + transition bumpers + league exit language')

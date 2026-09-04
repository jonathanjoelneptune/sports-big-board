#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
js=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
css=(ROOT/'ui'/'browse-curated-programming-v537.css').read_text()
interrupt=(ROOT/'architecture'/'score-interrupt-queue-v5220.js').read_text()
backend=(ROOT/'sbb'/'team_focus_v537.py').read_text()
init=(ROOT/'sbb'/'__init__.py').read_text()

assert version=='5.4.1', version
assert f'ui/browse-curated-programming-v537.css?v={version}' in index
assert f'ui/browse-curated-programming-v537.js?v={version}' in index

for token in [
    'function returnToAll()',
    "$('sbbFocusExit')?.addEventListener('click',returnToAll)",
    '#scoreFilters [data-score-filter="ALL"]',
    "addEventListener('wheel',event=>",
    "host.scrollLeft+=delta",
    'function hideLegacyCfb()',
    'function rememberEntityMetadata(',
    'function entityMetaFor(',
    'sbb-browse-entity-logo',
    'function themeRoles(entity,palette)',
    "key==='los angeles dodgers'",
    "key==='san diego padres'",
    "contextInsight('NEXT'",
    "'POWER RANK'",
    'youtubeIdFrom(media?.providerMediaId)',
]:
    assert token in js, token

for token in [
    '[data-score-filter="CFB"]',
    '.sbb-browse-entity-logo{',
    '--sbb-team-bg',
    '--sbb-team-button',
    '--sbb-team-selected',
    'data-sbb-team-theme-light="1"',
    '#sbbEntityTickerTrack.is-overflowing .sbb-entity-info-conveyor',
]:
    assert token in css, token

for token in [
    'shouldPreserveCurrentQueue()',
    'date-owned score selection',
    "snap.mode!=='daily'&&snap.queueActive",
]:
    assert token in interrupt, token

for token in [
    'browse-participants-v538.json',
    '"entities": entities',
    'def _event_participant_rows',
    'def _espn_directory',
    '"POWER RANK"',
    '"san diego padres": {"primary": "2f241d", "secondary": "ffc425"',
]:
    assert token in backend, token

assert 'from .team_focus_v537 import install as _install_team_focus_v537' in init
assert '_install_team_focus_v537()' in init

print('PASS v5.4.1 focus integration, day-owned score queue, participant marks, CFB retirement, and full team theme')

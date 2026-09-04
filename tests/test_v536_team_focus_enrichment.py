#!/usr/bin/env python3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
js=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
css=(ROOT/'ui'/'browse-curated-programming-v537.css').read_text()
backend=(ROOT/'sbb'/'team_focus_v537.py').read_text()
init=(ROOT/'sbb'/'__init__.py').read_text()
assert version=='5.4.1',version
assert f'ui/browse-curated-programming-v537.css?v={version}' in index
assert f'<script src="ui/browse-curated-programming-v537.js?v={version}"></script>' in index

# Team/Player menu uses a backend-persisted verified-media participant index.
for token in ['/api/browse/participants?','PERSISTED_VERIFIED_MEDIA_INDEX','_PARTICIPANT_PATH','browse-participants-v538.json','history_event_media']:
    assert token in js+backend,token

# Schedule truth remains present even when media discovery is incomplete.
for token in ["tier:items.length?media.tier:'none'",'mediaAvailable:!!items.length','NO MEDIA YET','.sbb-curation-card.no-media{']:
    assert token in js+css,token

# The ribbon gives its entire captured score-ribbon slot to chronological cards.
for token in ['.sbb-curation-toolbar{display:none!important}','display:block!important','grid-template-columns:112px minmax(0,1fr)!important']:
    assert token in css,token

# Team Focus controls are on the Sports Ticker row and Next 3 replaces Next 5.
for token in ["controls.id=\'sbbEntityFocusControls\'",'id="sbbFocusPlayAll"','id="sbbFocusExit"',"contextInsight('NEXT'",'.sbb-entity-focus-controls{']:
    assert token in js+css,token
assert "contextInsight('NEXT 5'" not in js

# TeamRankings/ESPN enrichment and logo/palette are backend cached.
for token in ['/api/team-focus','TEAMRANKINGS_STATS','www2.teamrankings.com','site.api.espn.com/apis/site/v2/sports','PALETTE_OVERRIDES','sbb-entity-logo']:
    assert token in js+css+backend,token

# Optional team theming is user-controlled and persistent.
for token in ["TEAM_THEME_KEY='sbb.team-theme.enabled.v1'",'id="teamThemeToggle"','function applyTeamTheme()','html[data-sbb-team-theme="on"]']:
    assert token in js+css,token

# Curated event selection replaces stale Game Center identity before re-selecting.
for token in ['replace stale Game Center identity','force:true','curated playback event identity']:
    assert token in js,token

assert 'from .team_focus_v537 import install as _install_team_focus_v537' in init
assert '_install_team_focus_v537()' in init
for forbidden in ['setInterval(', 'requestAnimationFrame(loop']:
    assert forbidden not in js,forbidden
print('PASS v5.4.1 persistent participants + schedule-complete Team Focus + enrichment + theming')

#!/usr/bin/env python3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
browse=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
browse_css=(ROOT/'ui'/'browse-curated-programming-v537.css').read_text()
league=(ROOT/'ui'/'league-view-v538.js').read_text()
league_css=(ROOT/'ui'/'league-view-v538.css').read_text()
watchdog=(ROOT/'architecture'/'playback-early-pause-recovery-v538.js').read_text()
backend=(ROOT/'sbb'/'league_view_v538.py').read_text()
focus=(ROOT/'sbb'/'team_focus_v537.py').read_text()
news=(ROOT/'sbb'/'current_news_v523.py').read_text()
init=(ROOT/'sbb'/'__init__.py').read_text()
assert version=='5.3.18',version
for token in ['>LEAGUE VIEW</button>','id="leagueViewRoot"',f'ui/league-view-v538.css?v={version}',f'ui/league-view-v538.js?v={version}',f'playback-early-pause-recovery-v538.js?v={version}']:
    assert token in index,token
for token in ['aggregateReason(','sbb-daily-recap-context','/api/league-view?league=','league-view-conference-grid','AP TOP 25','BIG BOARD EVENT VIEW','BRACKET / ROUNDS']:
    assert token in league+league_css,token
for token in ['ESPN_COMPETITIONS','/api/league-view','playoffRace','conferences','leaders','rankings','specialEvent','league-view-v538.json']:
    assert token in backend,token
for token in ['_build_accessible_theme','_relative_luminance','_contrast','team-theme-v538.json','"blackReplacement"','"wcag"']:
    assert token in focus,token
for token in ['sbb-browse-entity-logo','installLegacyCfbGuard()','enterSpecialContext(','auditDate(row)<=todayLocal','shortEntityName(teams[0])} vs ${shortEntityName(teams[1])',"contextInsight('RESULT',`${compactDate(row.date)} · ${row.label} · ${row.result} ${row.score}`"]:
    assert token in browse,token
assert '[data-score-filter="CFB"]' in browse_css
assert '--sbb-team-black-replacement' in browse_css
assert '#sbbFocusPlayAll{' in browse_css and '#sbbFocusExit{' in browse_css
for token in ['SBB_EARLY_PAUSE_RECOVERY','USER_PAUSE_SUPPRESS','SOFT_RESUME','BOUNDED_RECOVERY','5200','8200']:
    assert token in watchdog,token
for forbidden in ['setInterval(','requestAnimationFrame(loop']:
    assert forbidden not in watchdog,forbidden
for token in ['WALK_OFF','COMEBACK','SHUTOUT','DEBUT','LEAGUE_LEADER','SERIES','deliberately abundant']:
    assert token in news,token
assert 'from .league_view_v538 import install as _install_league_view_v538' in init
assert '_install_league_view_v538()' in init
print('PASS v5.3.18 League View + recap identity + team history cutoff + accessible theming + special-event context + early-pause recovery')

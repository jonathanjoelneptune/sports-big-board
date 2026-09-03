#!/usr/bin/env python3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
browse=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
browse_css=(ROOT/'ui'/'browse-curated-programming-v537.css').read_text()
league=(ROOT/'ui'/'league-view-v538.js').read_text()
league_css=(ROOT/'ui'/'league-view-v538.css').read_text()
backend=(ROOT/'sbb'/'league_view_v538.py').read_text()
focus=(ROOT/'sbb'/'team_focus_v537.py').read_text()
early=(ROOT/'architecture'/'playback-early-pause-recovery-v538.js').read_text()
guard=(ROOT/'architecture'/'playback-progress-watchdog-v5310.js').read_text()
verify=(ROOT/'VERIFY.sh').read_text()

assert version=='5.3.16',version

# Special-event header is presentation-only. It must never feed the canonical
# score-filter renderer, and repair is bounded to a missing-node child mutation.
for token in [
    "chip.removeAttribute('data-score-filter')",
    'chip.dataset.sbbSpecialContext=state.specialContext.league',
    'state.cfbObserver.observe(filters,{childList:true,subtree:true})',
    'requestAnimationFrame(()=>{repairQueued=false',
    "'WC2026':'FIFA WC'",
]: assert token in browse,token
assert "chip.dataset.scoreFilter=state.specialContext.league" not in browse
assert "attributes:true" not in browse[browse.index('function installLegacyCfbGuard()'):browse.index('function isCoreLeague',browse.index('function installLegacyCfbGuard()'))]
assert '#sbbActiveSpecialChip[data-sbb-special-context]' in browse_css and 'pointer-events:none' in browse_css

# Conservative startup watchdog must load before the retained legacy watchdog.
newref=f'architecture/playback-progress-watchdog-v5310.js?v={version}'
oldref=f'architecture/playback-progress-watchdog.js?v={version}'
assert newref in index and oldref in index
assert index.index(newref)<index.index(oldref)
for token in [
    'SBB_PLAYBACK_PROGRESS_WATCHDOG',
    'provider reports playing; recovery suppressed',
    'late clock movement; recovery suppressed',
    'no positive stall evidence',
    'positive startup stall',
    'if(state.confirmed)return;',
]: assert token in guard,token
# Manual/embedded pause cannot be interpreted as a dead player.
for token in [
    "markUserPause('embedded provider pause')",
    'for(const ms of [80,250,650,1100])setTimeout(confirmProviderPause,ms)',
    'if(!sample.paused)return false',
    '5200','8200',
]: assert token in early,token
assert 'pauseUi(' not in early

# League View uses side-by-side conference/league columns where meaningful,
# with MLB division winners removed from wildcard rows.
for token in [
    'league-view-conference-grid',
    'league-view-conference',
    'league-view-pulse-grid',
    'WILD CARD',
    'BEST RECORD',
    'HOT STREAK',
    'DIFFERENTIAL',
]: assert token in league+league_css,token
for token in [
    'def _conference_layout(',
    'def _conference_key(',
    'def _division_name(',
    'def _league_leaders(',
    '"conferences": _conference_layout(league, standings)',
    '"leaders": _league_leaders(standings)',
    'seed <= 3',
]: assert token in backend,token

# Tennis participant metadata accepts athlete/player wrappers and supplies a flag
# URL/glyph even when the upstream row has no logo.
for token in [
    'def _participant_subject(',
    'def _country_flag_url(',
    '"athletes"',
    '"players"',
]: assert token in focus,token
for token in [
    'function countryFlagGlyph(',
    'sbb-player-flag-glyph',
    'isTennis(league))&&entityMetadataCoverage(league)<0.75',
]: assert token in browse+browse_css,token

assert 'tests/test_v5310_special_event_playback_league_view.py' in verify
assert 'node --check architecture/playback-progress-watchdog-v5310.js' in verify
print('PASS v5.3.16 special-event stability + playback continuity + conference League View + tennis flags')

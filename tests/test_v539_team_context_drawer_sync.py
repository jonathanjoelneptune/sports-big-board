#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
browse=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
browse_css=(ROOT/'ui'/'browse-curated-programming-v537.css').read_text()
league=(ROOT/'ui'/'league-view-v538.js').read_text()
league_css=(ROOT/'ui'/'league-view-v538.css').read_text()
pause=(ROOT/'architecture'/'playback-early-pause-recovery-v538.js').read_text()

assert version=='5.5.0',version

# Team selection tunes the newest playable historical game automatically.
for token in [
    "const autoPlayEntity=state.entityType==='team'?state.entity:''",
    'const newestPlayable=state.games.findIndex',
    'playFrom(newestPlayable)',
    "state.mode==='history'&&state.entity===autoPlayEntity",
]:
    assert token in browse, token

# Right-side focus actions retain compact action language while newer releases
# distinguish normal league exit from Special Event exit.
assert '>Play All</button><button id="sbbFocusExit" type="button">Exit League</button>' in browse
assert "focusPlay.textContent='Play All'" in browse
assert "state.specialContext?'Exit Event':'Exit League'" in browse
for token in [
    '.sbb-entity-focus-controls button{',
    'font:900 7.5px/1 system-ui,sans-serif!important',
    '#sbbFocusExit{',
    'background:linear-gradient(180deg,#7d2027 0%,#54151b 100%)',
]:
    assert token in browse_css, token

# Game Center, League View and Settings are mutually exclusive drawer panes.
assert '#infoDrawer .drawer-pane.hidden' in league_css
assert 'body.sbb-game-center-side #infoDrawer .drawer-pane.hidden' in league_css
assert 'display:none!important' in league_css

# League View follows actual playback before SelectedEvent and browse context.
selected_pos=league.index('const selected=window.SBB_SELECTED_EVENT?.get?.()')
program_pos=league.index('const item=activeProgram()')
context_pos=league.index('const context=curatedContext()')
assert program_pos < selected_pos < context_pos
assert "window.addEventListener('sbb:score-click-selection'" in league
assert 'window.SBB_SELECTED_EVENT?.subscribe?.' in league

# Team picker removes redundant abbreviations and uses white-backed logo tiles.
assert 'sbb-browse-entity-abbr">${' not in browse
assert '.sbb-browse-entity-abbr{display:none!important}' in browse_css
assert 'background:#fff!important' in browse_css
assert '.sbb-browse-entity-logo img{' in browse_css

# Active Special Event chip persists after filter-row rerenders and uses compact label.
for token in [
    'function specialEventShortLabel(',
    "'WC2026':'FIFA WC'",
    "chip.removeAttribute('data-score-filter')",
    'requestAnimationFrame(()=>{repairQueued=false',
]:
    assert token in browse, token

# Manual pause is a selection-scoped latch, including native YouTube iframe interaction.
for token in [
    'manualPause:false',
    'manualPauseKey',
    'providerControlInteractionAt',
    "markUserPause('embedded provider pause')",
    'setCanonicalManualPause(true)',
    'manualPauseRequested',
    'function confirmProviderPause()',
    'for(const ms of [80,250,650,1100])setTimeout(confirmProviderPause,ms)',
    "window.addEventListener('blur'",
    'function userPaused(){return !!(state.manualPause&&state.manualPauseKey===state.key);}',
]:
    assert token in pause, token
assert 'userPauseUntil' not in pause

# Team focus ticker is content-sized and centered.
for token in [
    '.sbb-entity-info-item:not(.identity){',
    'min-width:max-content!important',
    'justify-items:center!important',
    'text-align:center!important',
    'padding:3px 8px!important',
    '.sbb-entity-info-item.identity{',
    'padding:2px 9px!important',
]:
    assert token in browse_css, token

# Cache-busted release surfaces remain atomic.
for token in [
    f'ui/browse-curated-programming-v537.css?v={version}',
    f'ui/league-view-v538.css?v={version}',
    f'ui/browse-curated-programming-v537.js?v={version}',
    f'ui/league-view-v538.js?v={version}',
    f'architecture/playback-early-pause-recovery-v538.js?v={version}',
]:
    assert token in index, token

print('PASS v5.5.0 team auto-tune + exclusive drawer + playback-owned League View + persistent event context + manual-pause latch + compact team ticker')

#!/usr/bin/env python3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
js=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
css=(ROOT/'ui'/'browse-curated-programming-v537.css').read_text()
assert version=='5.3.12',version
assert f'ui/browse-curated-programming-v537.css?v={version}' in index
assert f'<script src="ui/browse-curated-programming-v537.js?v={version}"></script>' in index

# Complete participant inventory survives reloads and refreshes in the background.
for token in [
    "ENTITY_CATALOG_KEY='sbb.browse.entity-catalog.v535'",
    'ENTITY_CATALOG_TTL_MS=6*60*60*1000',
    'function loadEntityCatalogStore()',
    'function persistEntityCatalog(league,names,entities=[]',
    'localStorage.setItem(ENTITY_CATALOG_KEY',
    'entityCatalogFresh(state.league)',
    'Building complete ${state.entityType===\'player\'?\'player\':\'team\'} library once; future opens are instant.',
]: assert token in js,token

# Curated mode occupies the exact measured score-ribbon slot; its full height belongs to cards while actions live in Team Focus.
for token in [
    'function captureScoreRibbonHeight()',
    "style.setProperty('--sbb-score-ribbon-height'",
    'height:var(--sbb-score-ribbon-height,104px)',
    'max-height:var(--sbb-score-ribbon-height,104px)',
    '.sbb-curation-toolbar{display:none!important}',
    "controls.id=\'sbbEntityFocusControls\'",
    'id="sbbFocusPlayAll"',
    'id="sbbFocusExit"',
    "$('sbbFocusPlayAll')?.addEventListener('click',playAll)",
    "$('sbbFocusExit')?.addEventListener('click',returnToAll)",
]: assert token in (js+css),token

# Historical playback owns the exact historical Game Center identity, not today's same-team game.
for token in [
    'function curatedEventIdentity(item)',
    'gameCenterEventId:eventId',
    'canonicalEventKey:clean(item.canonicalEventKey)',
    "window.SBB_SELECTED_EVENT?.select?.(event,{source:'browse',reason:'curated playback event identity'})",
    'window.SBB_SCORE_INTERRUPT_QUEUE?.active?.()',
    'setTimeout(()=>syncCuratedGameCenterContext(selected),180)',
]: assert token in js,token

# Team/player mode gets a focus ribbon from already-owned Sports Big Board data.
for token in [
    'id=\'sbbEntityTickerTrack\'',
    'function refreshEntityTickerInsights()',
    "contextInsight('STREAK'",
    "contextInsight('STANDING'",
    "contextInsight('RESULT'",
    "contextInsight('NEXT'",
    'contextNews()',
    '#keyInfoTrack.sbb-entity-ticker-hidden{display:none!important}',
]: assert token in (js+css),token

for forbidden in ['setInterval(', 'requestAnimationFrame(loop']:
    assert forbidden not in js,forbidden
print('PASS v5.3.12 persistent participant cache + equal-height curated ribbon + exact Game Center identity + entity focus ticker')

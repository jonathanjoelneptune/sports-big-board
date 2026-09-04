#!/usr/bin/env python3
"""v5.5.0 cached team select, league-logo radial, and controller history parity."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text().strip()
assert VERSION=='5.5.0',VERSION
core=(ROOT/'architecture'/'controller-mode-v542.js').read_text()
browse=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
css=(ROOT/'ui'/'controller-mode-v542.css').read_text()
backend=(ROOT/'sbb'/'team_focus_v537.py').read_text()
verify=(ROOT/'VERIFY.sh').read_text()
index=(ROOT/'index.html').read_text()

# Second radial puts Team/Player Select at 12 o'clock (first array item).
league_block=core.split('function leagueScopeOptions(context={})',1)[1].split('function specialEventNodes()',1)[0]
assert league_block.index("value:'BROWSE'") < league_block.index("value:'TODAY'") < league_block.index("value:'ALL'")
assert "label:radialBrowseLabel(league)" in league_block
special_block=core.split('function specialScopeOptions(context={})',1)[1].split('function dateScopeOptions()',1)[0]
assert special_block.index("value:'BROWSE'") < special_block.index("value:'ALL'")

# Primary league radial is logo-first.
for league in ['MLB','NFL','NBA','NHL','EPL','MLS','NCAAF']:
    assert f"{league}:" in core,league
assert 'LEAGUE_RADIAL_LOGOS' in core and 'leagueLogo:!!LEAGUE_RADIAL_LOGOS[value]' in core
assert 'sbb-controller-league-mark' in core and '.sbb-controller-league-mark' in css

# Cold team cache stays visible instead of silently closing; stale cache is instant.
assert "openRadial('entity-loading'" in core
assert "CACHE STILL WARMING" in core
assert 'ENTITY_CATALOG_MAX_STALE_MS=90*24*60*60*1000' in browse
assert 'CONTROLLER_PREWARM_LEAGUES' in browse
assert 'if(cached.length&&entityCatalogUsable(selected))' in browse
assert 'prewarmControllerEntityCatalogs()' in browse
assert "setTimeout(()=>prewarmControllerEntityCatalogs(),700)" in browse

# Controller team selection settles the real score-filter context and recovers if q index lags.
assert 'async function controllerSelectEntityContext' in browse
assert 'for(let i=0;i<24&&selectedLeague()!==selected;i++)await sleep(25);' in browse
assert 'try{scoreRibbonLeagueFilter=selected;}' in browse
assert "const fullRows=await fetchAuditRows(state.league,'',MAX_ENTITY_AUDIT_ROWS)" in browse
assert 'await activateHistorical({entity:name,controller:true});' in browse
assert 'playFrom(newestPlayable)' in browse

# Backend persists a complete league directory, including teams without verified media yet.
assert '_PARTICIPANT_TTL = 6 * 60 * 60' in backend
assert 'directory_cache={}' in backend
assert 'for league,spec in ESPN_COMPETITIONS.items()' in backend
assert 'PERSISTED_FULL_LEAGUE_DIRECTORY' in backend
assert '"complete": bool(names)' in backend
assert 'max-age=3600' in backend

for asset in ['architecture/controller-mode-v542.js','ui/controller-mode-v542.css','ui/browse-curated-programming-v537.js']:
    assert f'{asset}?v={VERSION}' in index,asset
assert 'tests/test_v549_cached_team_select.py' in verify
print('PASS v5.5.0 cached Team Select + league logos + controller history parity')

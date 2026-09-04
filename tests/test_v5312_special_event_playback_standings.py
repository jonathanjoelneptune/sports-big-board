#!/usr/bin/env python3
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
browse=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
league=(ROOT/'ui'/'league-view-v538.js').read_text()
league_css=(ROOT/'ui'/'league-view-v538.css').read_text()
backend_path=ROOT/'sbb'/'league_view_v538.py'
backend=backend_path.read_text()
verify=(ROOT/'VERIFY.sh').read_text()

assert version=='5.4.1',version

# Special-event playback is a hard context boundary. A failed World Cup source
# must try a same-game source or the next curated event and may not fall through
# to the prior MLB/general queue. Stale fallback presentation is cleared first.
for token in [
    'curatedAlternates:new Map()',
    'failedCuratedMedia:new Set()',
    'function allMediaForAuditRow(row,maxItems=6)',
    '__sbbCuratedGameKey:gameKey',
    'function primeCuratedAlternates(games=[])',
    'function clearStalePlaybackPresentation()',
    'function patchPlaybackFailure()',
    "v5.4.1 same-game curated fallback",
    "v5.4.1 next special-event highlight after unavailable source",
    'showCuratedUnavailable(item,err?.message||err)',
]:
    assert token in browse,token

# Unsupported special-event Game Center must visibly follow the selected match
# instead of leaving an old MLB Game Center mounted underneath.
for token in [
    'function showCuratedGameCenterFallback(item)',
    "empty.dataset.sbbCuratedMatch='1'",
    "window.SBB_SELECTED_EVENT?.clear?.({reason:'selected curated match has no standard Game Center provider'",
    'restoreCuratedGameCenterFallback()',
]:
    assert token in browse,token

# Core League View is standings-first. Bottom pulse/recent/series content is only
# retained for special events, where bracket/round context is actually relevant.
assert 'if(special){body+=specialEventBoard(league,context,payload);if(!body)body+=localEventCard(context);}' in league
assert "league==='MLB'?'Divisions · Wild Card'" in league
assert "league==='NFL'?'Divisions · Wild Card'" in league
assert "((league==='MLB'||league==='NFL')&&i===2)" in league
assert "if(league==='MLB'||league==='NFL'||league==='NHL')inner+=wildcardCard" in league
assert 'v5.4.1 — standings-first hierarchy' in league_css

# Provider feeds sometimes return only AL/NL or AFC/NFC tables. Prove the backend
# synthesizes familiar divisions from those provider records and then excludes
# each division leader from Wild Card.
for token in [
    '_STATIC_DIVISIONS = {',
    'def _synthesize_divisions(league, bucket):',
    '_synthesize_divisions(league, bucket)',
    'division_leaders.add(leader_key)',
    'bucket["wildcard"] = rows[:7 if league == "MLB" else 8]',
    'if league == "NHL":',
]:
    assert token in backend,token

spec=spec_from_file_location('sbb_test_lv5312',backend_path)
mod=module_from_spec(spec);spec.loader.exec_module(mod)
def row(abbr,pct):
    return {'id':abbr,'name':abbr,'abbreviation':abbr,'pct':str(pct),'record':'1-0','gamesBehind':'0','streak':'W1'}
al=[row('NYY',.700),row('BAL',.620),row('BOS',.610),row('TOR',.600),row('TB',.590),row('CLE',.690),row('DET',.630),row('MIN',.580),row('KC',.550),row('CWS',.300),row('HOU',.680),row('SEA',.640),row('TEX',.560),row('LAA',.500),row('ATH',.400)]
nl=[row('PHI',.700),row('ATL',.650),row('NYM',.600),row('MIA',.450),row('WSH',.400),row('MIL',.690),row('CHC',.630),row('CIN',.550),row('STL',.520),row('PIT',.400),row('LAD',.680),row('SD',.660),row('SF',.570),row('ARI',.530),row('COL',.300)]
groups=[
    {'name':'AMERICAN LEAGUE','parent':'','path':['AMERICAN LEAGUE'],'entries':al},
    {'name':'NATIONAL LEAGUE','parent':'','path':['NATIONAL LEAGUE'],'entries':nl},
]
layout=mod._conference_layout('MLB',groups)
assert [d['name'] for d in layout[0]['divisions']]==['EAST','CENTRAL','WEST']
assert [d['name'] for d in layout[1]['divisions']]==['EAST','CENTRAL','WEST']
assert {r['abbreviation'] for r in layout[0]['wildcard']}.isdisjoint({'NYY','CLE','HOU'})
assert {r['abbreviation'] for r in layout[1]['wildcard']}.isdisjoint({'PHI','MIL','LAD'})

assert 'tests/test_v5312_special_event_playback_standings.py' in verify
print('PASS v5.4.1 special-event playback isolation + Game Center freshness + division/Wild Card League View')

#!/usr/bin/env python3
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
assert version=='5.4.9',version
browse=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
browse_css=(ROOT/'ui'/'browse-curated-programming-v537.css').read_text()
league=(ROOT/'ui'/'league-view-v538.js').read_text()
league_css=(ROOT/'ui'/'league-view-v538.css').read_text()
backend_path=ROOT/'sbb'/'league_view_v538.py';backend=backend_path.read_text()
verify=(ROOT/'VERIFY.sh').read_text()

# Browser-proven Special Event media health survives reloads and outranks tier
# alone, so a known-working same-match fallback becomes the next primary source.
for token in [
    "CURATED_MEDIA_HEALTH_KEY='sbb.curated-media-health.v1'",
    'function loadCuratedMediaHealth()',
    "releaseCuratedQueue('enter special event')",
    "item?.embedAllowed===false||item?.embeddable===false",
    'function markCuratedMediaHealth(item,ok',
    'mediaHealthScore(b.media)-mediaHealthScore(a.media)',
    '__sbbMediaHealthKey:mediaHealthKey(media)',
    "markCuratedMediaHealth(item,false",
    "markCuratedMediaHealth(item,true,'browser-proven embedded playback')",
    'function probeCuratedPlaybackSuccess(item)',
]: assert token in browse,token

# Special Event context, not a transient player callback, owns Game Center.
for token in [
    'function ensureSpecialMatchCenter()',
    'function syncSpecialGameCenterLabels(active)',
    "panel.id='sbbSpecialMatchCenter'",
    'const specialOwned=!!state.specialContext',
    'const authoritative=specialOwned?(curated?item:(expectedCuratedItem()||item)):item',
    "reason:'selected Special Event match owns Match Center'",
    'if(state.specialContext)return;',
]: assert token in browse,token
for token in [
    'body.sbb-special-event-match-center #sbbSpecialMatchCenter',
    'body.sbb-special-event-match-center #gameCenterContent',
    'body.sbb-special-event-match-center #gameCenterEmpty',
]: assert token in browse_css,token

# EPL/MLS form is visually adjacent to standings data and league-scope buttons are
# a green subordinate control group.
for token in [
    '.league-view-mls .league-view-table th.team-col{width:39%!important}',
    '.league-view-form{display:inline-flex;align-items:center;justify-content:flex-start',
]: assert token in league_css,token
assert 'rgba(25,100,67,.96)' in browse_css

# Wild Card GB is relative to the actual cut line.
for token in [
    'def _wildcard_relative(rows, qualifying_slots=3):',
    'delta=gb-cutoff_gb',
    'row["wildcardGamesBehind"]=_format_relative(delta)',
    'bucket["wildcard"] = _wildcard_relative(visible, 3)',
]: assert token in backend,token
for token in [
    "if(wildcard&&(league==='MLB'||league==='NFL'))return ['TEAM','REC','WC GB','STRK']",
    "wildcard:true",
    'row.wildcardGamesBehind',
    'RELATIVE TO FINAL WILD CARD SPOT',
]: assert token in league,token

spec=spec_from_file_location('lv5315',backend_path);mod=module_from_spec(spec);spec.loader.exec_module(mod)
rows=[
 {'name':'A','wins':'80','losses':'60','gamesBehind':'2.0'},
 {'name':'B','wins':'78','losses':'62','gamesBehind':'4.0'},
 {'name':'C','wins':'77','losses':'63','gamesBehind':'5.0'},
 {'name':'D','wins':'75','losses':'65','gamesBehind':'7.0'},
]
out=mod._wildcard_relative(rows,3)
assert [r['wildcardGamesBehind'] for r in out]==['+3','+1','—','2'],out
assert 'tests/test_v5315_wildcard_media_match_center.py' in verify
print('PASS v5.4.9 Wild Card cut-line math + persisted embed health + authoritative Special Event Match Center + compact soccer form')

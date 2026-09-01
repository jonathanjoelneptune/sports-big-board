from pathlib import Path
import ast

ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'sbb'/'ncaaf_game_center.py').read_text(encoding='utf-8')
ast.parse(source)
assert '/football/college-football/summary?event=' in source
assert '_ORIGINAL_NORMALIZE(payload, "NFL", event_id)' in source
assert 'supported.add("NCAAF")' in source
ranked=(ROOT/'sbb'/'ncaaf_ranked.py').read_text(encoding='utf-8')
assert "'gameCenterProvider':'espn'" in ranked
assert "'gameCenterProviderHint':'espn'" in ranked
assert '__sbbCfbRankedInstalled' not in ranked
print('PASS v5.1.11 NCAAF shared NFL Game Center backend wiring')

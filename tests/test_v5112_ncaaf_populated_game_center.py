from pathlib import Path
import ast

ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'sbb'/'ncaaf_game_center.py').read_text(encoding='utf-8')
ast.parse(source)
assert '/football/college-football/summary?event=' in source
assert 'https://american-football.highlightly.net' in source
assert '"/matches"' in source
assert 'f"/matches/{match_id}"' in source
assert 'f"/box-score/{match_id}"' in source
assert '_flatten_highlightly_events' in source
assert 'ESPN_GAME_CENTER_INCOMPLETE' in source
assert 'mapping[_TARGET] = "nfl"' in source
assert 'server._game_center_refresh = game_center_refresh' in source
ranked=(ROOT/'sbb'/'ncaaf_ranked.py').read_text(encoding='utf-8')
assert "'gameCenterProvider':'espn','gameCenterFallback':'highlightly'" in ranked
print('PASS v5.1.12 NCAAF ESPN + Highlightly shared-football enrichment wiring')

from pathlib import Path

root=Path(__file__).resolve().parents[1]
index=(root/'index.html').read_text(encoding='utf-8')
init=(root/'sbb/__init__.py').read_text(encoding='utf-8')
backend=(root/'sbb/tennis_ribbon_projection.py').read_text(encoding='utf-8')
frontend=(root/'architecture/tennis-presentation.js').read_text(encoding='utf-8')

assert '<title>Sports Big Board — v5.1.22</title>' in index
assert 'architecture/tennis-presentation.js?v=5.1.22' in index
assert (root/'VERSION').read_text().strip()=='5.1.22'
assert 'tennis_ribbon_projection' in init
assert init.index('_install_tennis_ribbon_projection()') < init.index('_install_day_state()')
assert 'tennis-ribbon-aliases.sqlite3' in backend
assert 'CREATE TABLE IF NOT EXISTS tennis_player_profile' in backend
assert 'CREATE TABLE IF NOT EXISTS tennis_player_alias' in backend
assert 'CREATE TABLE IF NOT EXISTS tennis_board_day' in backend
assert 'day_state._catalog_score_rows_for_day = catalog_rows_for_day' in backend
assert 'day_state._merge_future_catalog_rows = merge_catalog_rows' in backend
assert 'warm=False' in backend
assert 'warm=True' in backend
assert "addEventListener('scroll'" not in frontend
assert 'getBoundingClientRect' not in frontend
assert 'COUNTRY_TO_ISO2' not in frontend
assert 'storeScoreDateLeague=wrapped' not in frontend
print('PASS v5.1.21/22 backend-first tennis ribbon architecture invariants')

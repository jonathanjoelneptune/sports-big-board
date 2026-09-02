from pathlib import Path
src=(Path(__file__).resolve().parents[1]/'sbb/ribbon_snapshot_v520.py').read_text()
assert 'ribbonAuthorityRevision' in src
assert '5.2.2-ribbon-snapshot-3' in src
assert '/api/ribbon-snapshot/bundle' in src
assert 'get_many' in src
print('PASS v5.2.2 RibbonSnapshot authority revision + bundle')

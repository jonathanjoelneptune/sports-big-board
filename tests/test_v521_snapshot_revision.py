from pathlib import Path
src=(Path(__file__).resolve().parents[1]/'sbb/ribbon_snapshot_v520.py').read_text()
assert 'ribbonAuthorityRevision' in src
assert '5.2.1-ribbon-snapshot-2' in src
print('PASS v5.2.1 RibbonSnapshot tracks authority revision')

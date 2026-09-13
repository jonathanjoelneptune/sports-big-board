#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
deploy = (ROOT / 'cloud' / 'gcp' / 'DEPLOY-FROM-GITHUB.sh').read_text(encoding='utf-8')
backup = (ROOT / 'cloud' / 'vm' / 'backup_state.py').read_text(encoding='utf-8')
materializer = (ROOT / 'tools' / 'apply_v6116_release.py').read_text(encoding='utf-8')

# Deployment cleanup may prune only timestamped daily recovery copies. The live
# catalog path is inspected for size/headroom but is never a deletion target.
for token in (
    'prune_daily_backups history 3',
    'prune_daily_backups game-centers 3',
    'prune_daily_backups history 1',
    'prune_daily_backups game-centers 1',
    'REQUIRED_KB=1048576',
    'HISTORY_KB + 524288',
    'Live catalog was not touched',
    "-name \"${family}-????????T??????Z.sqlite3\"",
):
    assert token in deploy, token

for forbidden in (
    'rm -f -- "$STATE_DIR/cache/history.sqlite3"',
    'rm -f "$STATE_DIR/cache/history.sqlite3"',
    'rm -f -- "$STATE_DIR/cache/game-centers.sqlite3"',
    'rm -f "$STATE_DIR/cache/game-centers.sqlite3"',
):
    assert forbidden not in deploy, forbidden

# The routine daily job retains three timestamped restore points independently
# per catalog and cannot sweep migration/reconciliation backup artifacts.
for token in (
    "for family in ('history', 'game-centers')",
    "backups.glob(f'{family}-????????T??????Z.sqlite3')",
    'for path in daily[3:]:',
):
    assert token in backup, token
assert "backups.glob('*.sqlite3')" not in backup

# Historical v5.3.4 deploy-safety verification is deliberately upgraded by the
# v6.1.16 materializer rather than being weakened or deleted.
assert 'test_v534_complete_browse_deploy_safety.py' in materializer
assert 'REQUIRED_KB=1048576' in materializer

print('PASS v6.1.16 bounded SQLite backup retention + deploy headroom contract')

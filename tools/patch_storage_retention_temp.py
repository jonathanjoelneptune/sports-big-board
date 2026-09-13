#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]

deploy = root / 'cloud/gcp/DEPLOY-FROM-GITHUB.sh'
text = deploy.read_text(encoding='utf-8')
old = '''mkdir -p "$STATE_DIR/backups" "$APP_BASE/releases"
find "$STATE_DIR/backups" -maxdepth 1 -type f -name 'history-pre-relation-repair-v*.sqlite3' -print -delete 2>/dev/null || true
rm -f /tmp/sbb-release-*.tgz 2>/dev/null || true
'''
new = '''mkdir -p "$STATE_DIR/backups" "$APP_BASE/releases"
find "$STATE_DIR/backups" -maxdepth 1 -type f -name 'history-pre-relation-repair-v*.sqlite3' -print -delete 2>/dev/null || true
# Daily SQLite backups are recovery copies, not the live catalog. Keep a small
# bounded recent set per catalog so the persistent data disk cannot be exhausted
# by full database copies. Special migration/reconciliation backups are not
# matched by these timestamp-only patterns and remain untouched.
prune_daily_backups(){
  local family="$1" keep="$2" entry backup count=0
  mapfile -t DAILY_BACKUPS < <(find "$STATE_DIR/backups" -maxdepth 1 -type f \\
    -name "${family}-????????T??????Z.sqlite3" -printf '%T@ %p\\n' 2>/dev/null | \\
    sort -nr | cut -d' ' -f2-)
  for backup in "${DAILY_BACKUPS[@]}"; do
    count=$((count+1))
    (( count <= keep )) && continue
    echo "[storage] Pruning old ${family} daily backup: $backup"
    rm -f -- "$backup"
  done
}
echo "[storage] Largest persistent-state paths before bounded backup cleanup:"
du -sh "$STATE_DIR"/* 2>/dev/null | sort -h | tail -n 12 || true
prune_daily_backups history 3
prune_daily_backups game-centers 3
find "$STATE_DIR/backups" -maxdepth 1 -type f \\
  \( -name '*.sqlite3-wal' -o -name '*.sqlite3-shm' \) -print -delete 2>/dev/null || true
rm -f /tmp/sbb-release-*.tgz 2>/dev/null || true
'''
if new not in text:
    if old not in text:
        raise SystemExit('deploy preclean anchor missing')
    text = text.replace(old, new, 1)

old_check = '''AVAILABLE_KB="$(df -Pk "$STATE_DIR" | awk 'NR==2 {print $4}')"
if [[ -n "$AVAILABLE_KB" && "$AVAILABLE_KB" -lt 262144 ]]; then
  echo "[storage] ERROR: less than 256 MiB free after safe cleanup; refusing to touch the catalog."
  exit 1
fi
'''
new_check = '''AVAILABLE_KB="$(df -Pk "$STATE_DIR" | awk 'NR==2 {print $4}')"
HISTORY_KB="$(du -k "$STATE_DIR/cache/history.sqlite3" 2>/dev/null | awk '{print $1}' || true)"
HISTORY_KB="${HISTORY_KB:-0}"
# Leave enough headroom for an emergency rollback copy if structural recovery is
# ever needed, plus 512 MiB for WAL/temp activity. Never reclaim the live catalog.
REQUIRED_KB=1048576
if [[ "$HISTORY_KB" =~ ^[0-9]+$ ]] && (( HISTORY_KB + 524288 > REQUIRED_KB )); then
  REQUIRED_KB=$((HISTORY_KB + 524288))
fi
if [[ -n "$AVAILABLE_KB" && "$AVAILABLE_KB" -lt "$REQUIRED_KB" ]]; then
  echo "[storage] Free space is still below protected deploy headroom; reducing daily backups to one per catalog."
  prune_daily_backups history 1
  prune_daily_backups game-centers 1
  AVAILABLE_KB="$(df -Pk "$STATE_DIR" | awk 'NR==2 {print $4}')"
fi
echo "[storage] Filesystem after bounded backup cleanup:"
df -h "$APP_BASE" "$STATE_DIR" || true
if [[ -n "$AVAILABLE_KB" && "$AVAILABLE_KB" -lt "$REQUIRED_KB" ]]; then
  echo "[storage] ERROR: ${AVAILABLE_KB} KiB free; ${REQUIRED_KB} KiB required for safe deploy headroom."
  echo "[storage] Live catalog was not touched. Largest remaining persistent-state paths:"
  du -ah "$STATE_DIR" 2>/dev/null | sort -h | tail -n 20 || true
  exit 1
fi
'''
if new_check not in text:
    if old_check not in text:
        raise SystemExit('deploy free-space guard anchor missing')
    text = text.replace(old_check, new_check, 1)
deploy.write_text(text, encoding='utf-8')

backup = root / 'cloud/vm/backup_state.py'
b = backup.read_text(encoding='utf-8')
old_b = '''for path in sorted(backups.glob('*.sqlite3'), key=lambda p:p.stat().st_mtime, reverse=True)[28:]:
    try: path.unlink()
    except OSError: pass
'''
new_b = '''# Keep three daily restore points per catalog. Restrict pruning to the timestamped
# backups created above so deploy/migration recovery artifacts are never removed
# by the routine daily retention job.
for family in ('history', 'game-centers'):
    daily = sorted(
        backups.glob(f'{family}-????????T??????Z.sqlite3'),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in daily[3:]:
        try: path.unlink()
        except OSError: pass
'''
if new_b not in b:
    if old_b not in b:
        raise SystemExit('backup retention anchor missing')
    b = b.replace(old_b, new_b, 1)
backup.write_text(b, encoding='utf-8')
print('patched bounded daily backup retention and deploy headroom cleanup')

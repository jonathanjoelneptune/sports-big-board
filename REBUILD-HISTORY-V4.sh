#!/usr/bin/env bash
set -euo pipefail
STATE_DIR="${SBB_STATE_DIR:-/var/lib/sports-big-board}"
if [ ! -f "$STATE_DIR/cache/history.sqlite3" ]; then
  STATE_DIR="${SBB_STATE_DIR:-$HOME/.sports-big-board}"
fi
SOURCE="${1:-$STATE_DIR/cache/history.sqlite3}"
OUTPUT="${2:-$STATE_DIR/cache/history-v4-rebuild.sqlite3}"
REPORT="${3:-$STATE_DIR/cache/history-v4-rebuild.report.json}"
python3 tools/rebuild_history_v4.py --source "$SOURCE" --output "$OUTPUT" --report "$REPORT" --force
printf '\nRebuild completed without changing production.\n'
printf 'New catalog: %s\nAudit report: %s\n' "$OUTPUT" "$REPORT"
printf 'After reviewing the report, install explicitly with:\n'
printf '  python3 tools/rebuild_history_v4.py --source %q --output %q --report %q --force --install\n' "$SOURCE" "$OUTPUT" "$REPORT"

#!/usr/bin/env python3
"""Safe SQLite backups for the Stage 1 persistent catalog."""
from pathlib import Path
from datetime import datetime, timezone
import os, sqlite3
from contextlib import closing

state=Path(os.environ.get('SBB_STATE_DIR','/var/lib/sports-big-board'))
cache=state/'cache'; backups=state/'backups'; backups.mkdir(parents=True,exist_ok=True)
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
for name in ('history.sqlite3','game-centers.sqlite3'):
    src=cache/name
    if not src.exists(): continue
    dest=backups/f'{src.stem}-{stamp}.sqlite3'
    with closing(sqlite3.connect(src)) as source, closing(sqlite3.connect(dest)) as target:
        source.backup(target)
# Keep three daily restore points per catalog. Restrict pruning to the timestamped
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

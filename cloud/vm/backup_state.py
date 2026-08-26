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
for path in sorted(backups.glob('*.sqlite3'), key=lambda p:p.stat().st_mtime, reverse=True)[28:]:
    try: path.unlink()
    except OSError: pass

"""SQLite-backed normalized Game Center repository.

The repository is the local edge cache for Game Center data. Completed games are
long-lived immutable snapshots; scheduled/live games carry an expires_at deadline
used by the central refresh worker.
"""
from pathlib import Path
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

class GameCenterRepository:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self._lock=threading.RLock()
        self._init_db()

    def _connect(self):
        con=sqlite3.connect(str(self.path),timeout=10)
        con.row_factory=sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    @contextmanager
    def _db(self):
        con=self._connect()
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _init_db(self):
        with self._lock, self._db() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS game_centers(
                    competition TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT '',
                    live INTEGER NOT NULL DEFAULT 0,
                    scheduled_at TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(competition,event_id)
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_game_centers_expires ON game_centers(expires_at)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_game_centers_updated ON game_centers(updated_at)")
            con.execute("""
                CREATE TABLE IF NOT EXISTS game_center_aliases(
                    competition TEXT NOT NULL,
                    alias_id TEXT NOT NULL,
                    resolved_event_id TEXT NOT NULL,
                    event_date TEXT NOT NULL DEFAULT '',
                    away_hint TEXT NOT NULL DEFAULT '',
                    home_hint TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(competition,alias_id)
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_game_center_alias_resolved ON game_center_aliases(competition,resolved_event_id)")

    def put(self,competition,event_id,data,expires_at,updated_at=None):
        competition=str(competition or '').upper(); event_id=str(event_id or '')
        event=(data or {}).get('event') or {}; scoreboard=(data or {}).get('scoreboard') or {}
        status=str(event.get('status') or scoreboard.get('status') or '')
        scheduled=str(event.get('scheduledAt') or '')
        provider=str((data or {}).get('source') or (data or {}).get('provider') or '')
        now=float(updated_at or time.time())
        payload=json.dumps(data,ensure_ascii=False,separators=(',',':'))
        with self._lock, self._db() as con:
            con.execute("""
                INSERT INTO game_centers(competition,event_id,status,live,scheduled_at,provider,updated_at,expires_at,payload_json)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(competition,event_id) DO UPDATE SET
                  status=excluded.status, live=excluded.live, scheduled_at=excluded.scheduled_at,
                  provider=excluded.provider, updated_at=excluded.updated_at,
                  expires_at=excluded.expires_at, payload_json=excluded.payload_json
            """,(competition,event_id,status,1 if (data or {}).get('live') else 0,scheduled,provider,now,float(expires_at),payload))
        return self.get(competition,event_id)

    def get(self,competition,event_id):
        with self._lock, self._db() as con:
            row=con.execute("SELECT * FROM game_centers WHERE competition=? AND event_id=?",(str(competition or '').upper(),str(event_id or ''))).fetchone()
        if not row: return None
        try: data=json.loads(row['payload_json'])
        except Exception: return None
        return {
            'competition':row['competition'],'eventId':row['event_id'],'status':row['status'],
            'live':bool(row['live']),'scheduledAt':row['scheduled_at'],'provider':row['provider'],
            'savedAt':float(row['updated_at']),'expiresAt':float(row['expires_at']),'data':data
        }


    def delete(self,competition,event_id):
        competition=str(competition or '').upper(); event_id=str(event_id or '')
        with self._lock, self._db() as con:
            con.execute("DELETE FROM game_centers WHERE competition=? AND event_id=?",(competition,event_id))
        return True

    def put_alias(self,competition,alias_id,resolved_event_id,event_date='',away_hint='',home_hint='',updated_at=None):
        competition=str(competition or '').upper(); alias_id=str(alias_id or ''); resolved_event_id=str(resolved_event_id or '')
        if not competition or not alias_id or not resolved_event_id: return None
        now=float(updated_at or time.time())
        with self._lock, self._db() as con:
            con.execute("""
                INSERT INTO game_center_aliases(competition,alias_id,resolved_event_id,event_date,away_hint,home_hint,updated_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(competition,alias_id) DO UPDATE SET
                  resolved_event_id=excluded.resolved_event_id,event_date=excluded.event_date,
                  away_hint=excluded.away_hint,home_hint=excluded.home_hint,updated_at=excluded.updated_at
            """,(competition,alias_id,resolved_event_id,str(event_date or '')[:10],str(away_hint or ''),str(home_hint or ''),now))
        return resolved_event_id

    def resolve_alias(self,competition,alias_id):
        competition=str(competition or '').upper(); alias_id=str(alias_id or '')
        if not competition or not alias_id: return ''
        with self._lock, self._db() as con:
            row=con.execute("SELECT resolved_event_id FROM game_center_aliases WHERE competition=? AND alias_id=?",(competition,alias_id)).fetchone()
        return str(row['resolved_event_id'] if row else '')

    def due(self,now=None,limit=32):
        now=float(now or time.time())
        with self._lock, self._db() as con:
            rows=con.execute("SELECT competition,event_id,status,live,expires_at FROM game_centers WHERE expires_at<=? ORDER BY live DESC, expires_at ASC LIMIT ?",(now,int(limit))).fetchall()
        return [dict(row) for row in rows]

    def summary(self):
        with self._lock, self._db() as con:
            total=con.execute("SELECT COUNT(*) FROM game_centers").fetchone()[0]
            live=con.execute("SELECT COUNT(*) FROM game_centers WHERE live=1").fetchone()[0]
            final=con.execute("SELECT COUNT(*) FROM game_centers WHERE lower(status) LIKE '%final%' OR lower(status) LIKE '%game over%' OR lower(status) LIKE '%complete%'").fetchone()[0]
            aliases=con.execute("SELECT COUNT(*) FROM game_center_aliases").fetchone()[0]
        return {'total':int(total),'live':int(live),'final':int(final),'aliases':int(aliases),'path':str(self.path)}

    def migrate_json_dir(self,directory,ttl_func):
        """Best-effort migration of v2.6.2 JSON snapshots into SQLite."""
        directory=Path(directory)
        if not directory.exists(): return 0
        migrated=0
        for path in directory.glob('*.json'):
            try:
                obj=json.loads(path.read_text(encoding='utf-8'))
                data=obj.get('data') if isinstance(obj,dict) else None
                if not isinstance(data,dict): continue
                comp=str(data.get('competitionId') or path.stem.split('-',1)[0]).upper()
                event=str(data.get('eventId') or (path.stem.split('-',1)[1] if '-' in path.stem else ''))
                if not comp or not event or self.get(comp,event): continue
                saved=float(obj.get('savedAt') or time.time())
                ttl=float(ttl_func(data))
                self.put(comp,event,data,saved+ttl,updated_at=saved); migrated+=1
            except Exception: continue
        return migrated

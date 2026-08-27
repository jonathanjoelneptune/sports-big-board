"""Cross-sport playback readiness and reliability persistence for Sports Big Board.

v4.4.2 keeps playback identity separate from sport identity.  Every transport/provider
feeds the same health model using playback-session telemetry.  The browser still owns
real decoder readiness; this store supplies durable history so bad assets stop getting
re-discovered as if they were healthy on every session.
"""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

_SCHEMA_VERSION = 2
_SAMPLE_LIMIT = 64
_HOOK_LOCK = threading.Lock()
_HOOK_SCHEDULED = False
_STORE = None
_STORE_LOCK = threading.Lock()


def _default_path() -> Path:
    state_dir = Path(os.environ.get("SBB_STATE_DIR") or (Path.home() / ".sports-big-board")).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    return Path(os.environ.get("SBB_PLAYBACK_READINESS_DB") or (state_dir / "playback-readiness.sqlite3"))


def _clean(value, limit=1200):
    return str(value or "").strip()[:limit]


def _load_samples(raw):
    try:
        data = json.loads(raw or "[]")
        return [max(0.0, float(x)) for x in data if isinstance(x, (int, float))][- _SAMPLE_LIMIT:]
    except Exception:
        return []


def _percentile(values, q):
    values = sorted(float(x) for x in values if x is not None)
    if not values:
        return 0.0
    pos = (len(values) - 1) * max(0.0, min(1.0, float(q)))
    lo = int(pos); hi = min(len(values) - 1, lo + 1); frac = pos - lo
    return values[lo] * (1.0 - frac) + values[hi] * frac


class PlaybackReadinessStore:
    """Small SQLite sidecar containing durable per-media playback health."""

    def __init__(self, path=None):
        self.path = str(path or _default_path())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _init_db(self):
        with self._lock, closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS playback_asset_health (
                    media_key TEXT PRIMARY KEY,
                    event_key TEXT NOT NULL DEFAULT '', competition_id TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '', transport TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'DISCOVERED',
                    reliability_score REAL NOT NULL DEFAULT 80,
                    selections INTEGER NOT NULL DEFAULT 0, first_frames INTEGER NOT NULL DEFAULT 0,
                    hot_ready_count INTEGER NOT NULL DEFAULT 0, stalls INTEGER NOT NULL DEFAULT 0,
                    failures INTEGER NOT NULL DEFAULT 0, warm_failures INTEGER NOT NULL DEFAULT 0,
                    recovered_failovers INTEGER NOT NULL DEFAULT 0, consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    total_stall_ms REAL NOT NULL DEFAULT 0, last_stall_ms REAL NOT NULL DEFAULT 0,
                    startup_samples_json TEXT NOT NULL DEFAULT '[]',
                    first_seen_at REAL NOT NULL DEFAULT 0, last_seen_at REAL NOT NULL DEFAULT 0,
                    last_success_at REAL NOT NULL DEFAULT 0, last_failure_at REAL NOT NULL DEFAULT 0,
                    quarantined_until REAL NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL DEFAULT 0
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_playback_health_state ON playback_asset_health(state,reliability_score)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_playback_health_provider ON playback_asset_health(provider,transport)")
            conn.execute("CREATE TABLE IF NOT EXISTS playback_readiness_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at REAL NOT NULL DEFAULT 0)")
            def ensure_column(column, ddl):
                cols={str(r[1]) for r in conn.execute("PRAGMA table_info(playback_asset_health)")}
                if column not in cols: conn.execute(f"ALTER TABLE playback_asset_health ADD COLUMN {column} {ddl}")
            ensure_column('total_stall_ms','REAL NOT NULL DEFAULT 0')
            ensure_column('last_stall_ms','REAL NOT NULL DEFAULT 0')
            conn.execute("INSERT INTO playback_readiness_meta(key,value,updated_at) VALUES('schema_version',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (str(_SCHEMA_VERSION), time.time()))
            conn.commit()
        self._bootstrap_from_history_catalog()

    @staticmethod
    def _media_key_from_history_asset(item):
        if not isinstance(item,dict): return ''
        yt=_clean(item.get('youtubeId') or item.get('youtube_id'),120)
        if yt: return f'youtube:{yt}'
        raw=_clean(item.get('mediaUrl') or item.get('sourceUrl'),1800)
        if raw:
            if raw.startswith('direct:'): return raw
            if raw.startswith('http://') or raw.startswith('https://') or raw.startswith('/api/media?'): return f'direct:{raw}'
        return ''

    def _bootstrap_from_history_catalog(self):
        """Seed durable readiness from pre-v4.4 runtime truth without rewriting history.

        The normalized history catalog already knows whether some assets were
        actually PLAYED or FAILED.  v4.4.2 imports that evidence once so the new
        sidecar does not force every browser to rediscover those failures.
        """
        marker='history_runtime_bootstrap_v1'
        try:
            with closing(self._connect()) as own:
                if own.execute('SELECT 1 FROM playback_readiness_meta WHERE key=?',(marker,)).fetchone(): return
        except Exception: return
        parent=Path(self.path).parent; candidates=[]
        for pattern in ('*.sqlite3','*.sqlite','*.db'):
            candidates.extend(parent.glob(pattern))
        imported=0
        for db in candidates:
            try:
                if db.resolve()==Path(self.path).resolve() or not db.is_file(): continue
                uri=f'file:{db.as_posix()}?mode=ro'; hist=sqlite3.connect(uri,uri=True,timeout=2);hist.row_factory=sqlite3.Row
                try:
                    table=hist.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='history_source_media'").fetchone()
                    if not table: continue
                    rows=hist.execute("""SELECT asset_json,provider,runtime_state,runtime_success_at,runtime_failure_at,runtime_failure_reason,updated_at
                        FROM history_source_media WHERE runtime_state IN ('PLAYED','FAILED') ORDER BY updated_at DESC LIMIT 5000""").fetchall()
                    with self._lock, closing(self._connect()) as own:
                        now=time.time()
                        for raw in rows:
                            try: item=json.loads(raw['asset_json'] or '{}')
                            except Exception: item={}
                            key=self._media_key_from_history_asset(item)
                            if not key: continue
                            state=str(raw['runtime_state'] or '').upper(); played=state=='PLAYED'
                            provider=_clean(item.get('provider') or raw['provider'],120).upper()
                            transport='YOUTUBE_EMBED' if key.startswith('youtube:') else 'DIRECT_VIDEO'
                            league=_clean(item.get('competitionId') or item.get('league'),80).upper()
                            source=_clean(item.get('mediaUrl') or item.get('sourceUrl') or item.get('externalUrl'),2000)
                            score=92.0 if played else 55.0; first_frames=1 if played else 0; failures=0 if played else 1; consecutive=0 if played else 1
                            success=float(raw['runtime_success_at'] or 0);failure=float(raw['runtime_failure_at'] or 0);updated=float(raw['updated_at'] or max(success,failure,now));err=_clean(raw['runtime_failure_reason'],700)
                            own.execute("""INSERT OR IGNORE INTO playback_asset_health(media_key,event_key,competition_id,provider,transport,source_url,state,reliability_score,
                                selections,first_frames,hot_ready_count,stalls,failures,warm_failures,recovered_failovers,consecutive_failures,total_stall_ms,last_stall_ms,startup_samples_json,
                                first_seen_at,last_seen_at,last_success_at,last_failure_at,quarantined_until,last_error,updated_at)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(key,'',league,provider,transport,source,'VERIFIED' if played else 'DEGRADED',score,0,first_frames,0,0,failures,0,0,consecutive,0,0,'[]',updated,updated,success,failure,0,err,updated))
                            imported+=int(own.total_changes>0)
                        own.execute("INSERT OR REPLACE INTO playback_readiness_meta(key,value,updated_at) VALUES(?,?,?)",(marker,str(imported),now));own.commit()
                finally: hist.close()
            except Exception: continue
        try:
            with closing(self._connect()) as own:
                own.execute("INSERT OR IGNORE INTO playback_readiness_meta(key,value,updated_at) VALUES(?,?,?)",(marker,str(imported),time.time()));own.commit()
        except Exception: pass

    @staticmethod
    def _derive_state(row, now=None):
        now = float(now or time.time())
        score = float(row.get("reliability_score") or 0)
        if float(row.get("quarantined_until") or 0) > now:
            return "QUARANTINED"
        failures = int(row.get("failures") or 0); starts = int(row.get("first_frames") or 0)
        hot = int(row.get("hot_ready_count") or 0); consecutive = int(row.get("consecutive_failures") or 0)
        if consecutive >= 3 or score < 35:
            return "QUARANTINED"
        if consecutive > 0 or int(row.get("warm_failures") or 0) >= 2 or score < 60:
            return "DEGRADED"
        if hot >= 1 and starts >= 1 and score >= 82:
            return "PLAYBACK_READY"
        if starts >= 1 and score >= 67:
            return "VERIFIED"
        return "DISCOVERED"

    def record(self, event, session):
        event = _clean(event, 80).lower()
        session = session if isinstance(session, dict) else {}
        media_key = _clean(session.get("mediaKey") or session.get("clipKey"), 1800)
        if not media_key or media_key == "none":
            return False
        now = time.time()
        with self._lock, closing(self._connect()) as conn:
            existing = conn.execute("SELECT * FROM playback_asset_health WHERE media_key=?", (media_key,)).fetchone()
            row = dict(existing) if existing else {
                "media_key": media_key, "reliability_score": 80.0, "selections": 0, "first_frames": 0,
                "hot_ready_count": 0, "stalls": 0, "failures": 0, "warm_failures": 0,
                "recovered_failovers": 0, "consecutive_failures": 0, "total_stall_ms": 0.0, "last_stall_ms": 0.0, "startup_samples_json": "[]",
                "first_seen_at": now, "last_seen_at": now, "last_success_at": 0, "last_failure_at": 0,
                "quarantined_until": 0, "last_error": ""
            }
            score = float(row.get("reliability_score") or 80.0)
            samples = _load_samples(row.get("startup_samples_json"))
            selections = int(row.get("selections") or 0); first_frames = int(row.get("first_frames") or 0)
            hot_ready = int(row.get("hot_ready_count") or 0); stalls = int(row.get("stalls") or 0)
            failures = int(row.get("failures") or 0); warm_failures = int(row.get("warm_failures") or 0)
            recovered = int(row.get("recovered_failovers") or 0); consecutive = int(row.get("consecutive_failures") or 0)
            total_stall_ms=float(row.get("total_stall_ms") or 0); last_stall_ms=float(row.get("last_stall_ms") or 0)
            last_success = float(row.get("last_success_at") or 0); last_failure = float(row.get("last_failure_at") or 0)
            quarantine = float(row.get("quarantined_until") or 0); last_error = _clean(row.get("last_error"), 700)

            if event == "selection":
                selections += 1
            elif event in ("first-frame", "first-frame-meta"):
                if event == "first-frame": first_frames += 1
                startup = session.get("firstFrameMs")
                if isinstance(startup, (int, float)) and startup >= 0:
                    samples = (samples + [float(startup)])[-_SAMPLE_LIMIT:]
                    score += 5 if startup <= 1500 else 2 if startup <= 3000 else -3 if startup > 6000 else 0
                score += 2; consecutive = 0; last_success = now; last_error = ""
            elif event == "hot-ready":
                hot_ready += 1; first_frames += 1; score += 7; consecutive = 0; last_success = now; last_error = ""
                startup = session.get("warmReadyMs")
                if isinstance(startup, (int, float)) and startup >= 0:
                    samples = (samples + [float(startup)])[-_SAMPLE_LIMIT:]
            elif event == "stall":
                stalls += 1; score -= 2
            elif event == "stall-end":
                stall_ms=max(0.0,float(session.get("lastStallMs") or 0)); last_stall_ms=stall_ms; total_stall_ms += stall_ms
                score -= 1 if stall_ms < 1500 else 3 if stall_ms < 5000 else 7
            elif event == "warm-failure":
                warm_failures += 1; score -= 1 if bool(session.get("networkSuspect")) else 5; last_error = _clean(session.get("lastError") or session.get("reason"), 700)
            elif event == "failure":
                failures += 1; consecutive += 1; score -= 15; last_failure = now
                last_error = _clean(session.get("lastError") or session.get("reason"), 700)
            elif event in ("recovered-failover", "failover-recovered"):
                recovered += 1; last_success = now

            score = max(0.0, min(100.0, score))
            # Durable quarantine is deliberately conservative. A single bad Wi-Fi
            # moment must not poison an otherwise-good asset for every sport/device.
            if consecutive >= 3 or score < 35:
                quarantine = max(quarantine, now + 30 * 60)
            elif quarantine and quarantine <= now:
                quarantine = 0

            next_row = {
                **row,
                "reliability_score": score, "selections": selections, "first_frames": first_frames,
                "hot_ready_count": hot_ready, "stalls": stalls, "failures": failures,
                "warm_failures": warm_failures, "recovered_failovers": recovered,
                "consecutive_failures": consecutive, "total_stall_ms": total_stall_ms, "last_stall_ms": last_stall_ms, "startup_samples_json": json.dumps(samples, separators=(",", ":")),
                "last_success_at": last_success, "last_failure_at": last_failure,
                "quarantined_until": quarantine, "last_error": last_error,
            }
            next_row["state"] = self._derive_state(next_row, now)
            conn.execute("""
                INSERT INTO playback_asset_health(
                  media_key,event_key,competition_id,provider,transport,source_url,state,reliability_score,
                  selections,first_frames,hot_ready_count,stalls,failures,warm_failures,recovered_failovers,consecutive_failures,
                  total_stall_ms,last_stall_ms,startup_samples_json,first_seen_at,last_seen_at,last_success_at,last_failure_at,quarantined_until,last_error,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(media_key) DO UPDATE SET
                  event_key=excluded.event_key,competition_id=excluded.competition_id,provider=excluded.provider,
                  transport=excluded.transport,source_url=excluded.source_url,state=excluded.state,
                  reliability_score=excluded.reliability_score,selections=excluded.selections,first_frames=excluded.first_frames,
                  hot_ready_count=excluded.hot_ready_count,stalls=excluded.stalls,failures=excluded.failures,
                  warm_failures=excluded.warm_failures,recovered_failovers=excluded.recovered_failovers,
                  consecutive_failures=excluded.consecutive_failures,total_stall_ms=excluded.total_stall_ms,last_stall_ms=excluded.last_stall_ms,
                  startup_samples_json=excluded.startup_samples_json,last_seen_at=excluded.last_seen_at,last_success_at=excluded.last_success_at,last_failure_at=excluded.last_failure_at,
                  quarantined_until=excluded.quarantined_until,last_error=excluded.last_error,updated_at=excluded.updated_at
            """, (
                media_key, _clean(session.get("eventKey"), 500), _clean(session.get("league") or session.get("competitionId"), 80).upper(),
                _clean(session.get("provider"), 120).upper(), _clean(session.get("transport"), 120).upper(),
                _clean(session.get("sourceUrl") or session.get("sourceExternalUrl"), 2000), next_row["state"], score,
                selections, first_frames, hot_ready, stalls, failures, warm_failures, recovered, consecutive,
                total_stall_ms,last_stall_ms,next_row["startup_samples_json"], float(row.get("first_seen_at") or now), now, last_success, last_failure,
                quarantine, last_error, now
            ))
            conn.commit()
        return True

    def get(self, media_key):
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM playback_asset_health WHERE media_key=?", (_clean(media_key, 1800),)).fetchone()
            if not row: return None
            data = dict(row); samples = _load_samples(data.pop("startup_samples_json", "[]"))
            data["startup_p50_ms"] = round(_percentile(samples, .50), 1)
            data["startup_p95_ms"] = round(_percentile(samples, .95), 1)
            data["startup_sample_count"] = len(samples)
            data["state"] = self._derive_state(data)
            return data

    def summary(self, limit=240):
        now = time.time(); limit=max(20,min(500,int(limit or 240)))
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT state,COUNT(*) count,AVG(reliability_score) avg_score FROM playback_asset_health GROUP BY state").fetchall()
            total = conn.execute("SELECT COUNT(*) FROM playback_asset_health").fetchone()[0]
            records = conn.execute("""SELECT media_key,event_key,competition_id,provider,transport,state,reliability_score,selections,first_frames,
                hot_ready_count,stalls,failures,warm_failures,recovered_failovers,consecutive_failures,total_stall_ms,last_stall_ms,
                last_success_at,last_failure_at,quarantined_until,last_error,updated_at,startup_samples_json
                FROM playback_asset_health ORDER BY updated_at DESC LIMIT ?""",(limit,)).fetchall()
            provider_rows=conn.execute("""SELECT competition_id,provider,transport,COUNT(*) assets,AVG(reliability_score) avg_score,
                SUM(failures) failures,SUM(stalls) stalls FROM playback_asset_health GROUP BY competition_id,provider,transport
                ORDER BY assets DESC,avg_score DESC LIMIT 80""").fetchall()
        out=[]
        for raw in records:
            data=dict(raw); samples=_load_samples(data.pop('startup_samples_json','[]')); data['state']=self._derive_state(data,now)
            data['startup_p50_ms']=round(_percentile(samples,.50),1);data['startup_p95_ms']=round(_percentile(samples,.95),1);data['startup_sample_count']=len(samples);out.append(data)
        return {
            "schemaVersion": _SCHEMA_VERSION, "assets": int(total or 0),
            "states": {r["state"]: {"count": int(r["count"] or 0), "averageScore": round(float(r["avg_score"] or 0), 1)} for r in rows},
            "records":out,"providers":[dict(r) for r in provider_rows],"generatedAt": now,
        }



def default_store():
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = PlaybackReadinessStore()
        return _STORE


def _install_hook_once():
    try:
        from sbb.milestone_console import MilestoneConsole
    except Exception:
        return False
    with _HOOK_LOCK:
        if getattr(MilestoneConsole, "_sbb_playback_readiness_wrapped", False):
            return True
        original_record = getattr(MilestoneConsole, "record_playback", None)
        original_snapshot = getattr(MilestoneConsole, "snapshot", None)
        if not callable(original_record) or not callable(original_snapshot):
            return False

        def wrapped_record(self, event, session, *args, **kwargs):
            result = original_record(self, event, session, *args, **kwargs)
            try: default_store().record(event, session or {})
            except Exception: pass
            return result

        def wrapped_snapshot(self, *args, **kwargs):
            result=original_snapshot(self,*args,**kwargs)
            try: result["playbackReadiness"]=default_store().summary(limit=160)
            except Exception as exc: result["playbackReadiness"]={"schemaVersion":_SCHEMA_VERSION,"assets":0,"records":[],"error":f"{type(exc).__name__}: {exc}"[:500]}
            return result

        MilestoneConsole.record_playback = wrapped_record
        MilestoneConsole.snapshot = wrapped_snapshot
        MilestoneConsole._sbb_playback_readiness_wrapped = True
        return True


def schedule_milestone_hook_install():
    """Install after server imports settle, avoiding import-cycle risk."""
    global _HOOK_SCHEDULED
    if str(os.environ.get("SBB_DISABLE_PLAYBACK_READINESS") or "").lower() in ("1", "true", "yes", "on"):
        return False
    with _HOOK_LOCK:
        if _HOOK_SCHEDULED: return True
        _HOOK_SCHEDULED = True
    def worker():
        for _ in range(200):
            if _install_hook_once(): return
            time.sleep(.05)
    threading.Thread(target=worker, name="sbb-playback-readiness-hook", daemon=True).start()
    return True

import json
import sqlite3
import threading
import time
from contextlib import closing


class HistoryRepository:
    """Persistent historical score/event/media catalog.

    v3.0.1 keeps the legacy date/league JSON rows for fast score hydration while
    adding normalized event and asset tables. Media truth now belongs to one
    canonical event + asset identity, which lets runtime playback successes and
    failures survive browser reloads instead of being rediscovered as green.
    """

    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS history_day (
                    date TEXT NOT NULL,
                    league TEXT NOT NULL,
                    scores_json TEXT,
                    media_json TEXT,
                    discovery_json TEXT,
                    scores_saved_at REAL NOT NULL DEFAULT 0,
                    media_saved_at REAL NOT NULL DEFAULT 0,
                    discovery_saved_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(date, league)
                )
                """
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(history_day)").fetchall()}
            if "discovery_json" not in cols:
                conn.execute("ALTER TABLE history_day ADD COLUMN discovery_json TEXT")
            if "discovery_saved_at" not in cols:
                conn.execute("ALTER TABLE history_day ADD COLUMN discovery_saved_at REAL NOT NULL DEFAULT 0")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_date ON history_day(date)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS history_event (
                    date TEXT NOT NULL,
                    league TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    event_json TEXT,
                    discovery_state TEXT NOT NULL DEFAULT 'UNKNOWN',
                    discovery_json TEXT,
                    last_discovery_at REAL NOT NULL DEFAULT 0,
                    last_success_at REAL NOT NULL DEFAULT 0,
                    next_retry_at REAL NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(date, league, event_id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_event_date ON history_event(date, league)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_event_retry ON history_event(next_retry_at)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS history_media_asset (
                    date TEXT NOT NULL,
                    league TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    asset_key TEXT NOT NULL,
                    asset_json TEXT NOT NULL,
                    validation_state TEXT NOT NULL DEFAULT 'CANDIDATE',
                    verified_at REAL NOT NULL DEFAULT 0,
                    runtime_state TEXT NOT NULL DEFAULT 'UNKNOWN',
                    runtime_success_at REAL NOT NULL DEFAULT 0,
                    runtime_failure_at REAL NOT NULL DEFAULT 0,
                    runtime_failure_reason TEXT NOT NULL DEFAULT '',
                    last_seen_at REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(date, league, event_id, asset_key)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_asset_event ON history_media_asset(date, league, event_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_asset_validation ON history_media_asset(validation_state, runtime_state)")
            conn.commit()

    @staticmethod
    def _dump(rows):
        return json.dumps(list(rows or []), ensure_ascii=False, separators=(",", ":"), default=str)

    @staticmethod
    def _dump_obj(value):
        return json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False, separators=(",", ":"), default=str)

    @staticmethod
    def _load(value):
        if not value:
            return []
        try:
            data = json.loads(value)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    @staticmethod
    def _load_obj(value):
        if not value:
            return {}
        try:
            data = json.loads(value)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def event_id_for(item):
        if not isinstance(item, dict):
            return ""
        # scoreEventId/matchId are sporting-event identity. A YouTube row's eventId
        # can itself be the video id, so it intentionally ranks after those fields.
        for key in ("scoreEventId", "matchId", "espnEventId", "gamePk", "canonicalEventId", "eventId"):
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    @staticmethod
    def asset_key_for(item):
        if not isinstance(item, dict):
            return ""
        if item.get("youtubeId"):
            return "yt:" + str(item.get("youtubeId"))
        # Provider item id is preferred for native signed URLs so a refreshed URL
        # updates the same asset instead of creating an endless stream of stale rows.
        if item.get("id"):
            return "id:" + str(item.get("id"))
        if item.get("mediaUrl"):
            return "url:" + str(item.get("mediaUrl"))
        if item.get("externalUrl"):
            return "ext:" + str(item.get("externalUrl"))
        return ""

    @staticmethod
    def validation_state_for(item):
        value = str((item or {}).get("validationState") or "").upper()
        if value in {"VERIFIED", "CANDIDATE", "EXTERNAL", "FAILED"}:
            return value
        if (item or {}).get("verifiedPlayable") and ((item or {}).get("youtubeId") or (item or {}).get("mediaUrl")):
            return "VERIFIED"
        if (item or {}).get("externalOnly"):
            return "EXTERNAL"
        return "CANDIDATE"

    def put_scores(self, date, league, rows):
        now = time.time(); date = str(date)[:10]; league = str(league).upper(); rows = list(rows or [])
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO history_day(date, league, scores_json, scores_saved_at)
                VALUES(?,?,?,?)
                ON CONFLICT(date,league) DO UPDATE SET
                    scores_json=excluded.scores_json,
                    scores_saved_at=excluded.scores_saved_at
                """,
                (date, league, self._dump(rows), now),
            )
            # Seed canonical event rows while the scoreboard is authoritative.
            for row in rows:
                event_id = self.event_id_for(row)
                if not event_id:
                    continue
                conn.execute(
                    """
                    INSERT INTO history_event(date,league,event_id,event_json,updated_at)
                    VALUES(?,?,?,?,?)
                    ON CONFLICT(date,league,event_id) DO UPDATE SET
                        event_json=excluded.event_json, updated_at=excluded.updated_at
                    """,
                    (date, league, event_id, self._dump_obj(row), now),
                )
            conn.commit()
        return now

    def upsert_event(self, date, league, event_id, event=None):
        date=str(date)[:10]; league=str(league).upper(); event_id=str(event_id or '')
        if not event_id: return 0
        now=time.time()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO history_event(date,league,event_id,event_json,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(date,league,event_id) DO UPDATE SET
                    event_json=CASE WHEN excluded.event_json<>'{}' THEN excluded.event_json ELSE history_event.event_json END,
                    updated_at=excluded.updated_at
                """,
                (date,league,event_id,self._dump_obj(event),now),
            )
            conn.commit()
        return now

    def set_event_discovery(self, date, league, event_id, state, details=None, *, error="", retry_at=0, success=False):
        date=str(date)[:10]; league=str(league).upper(); event_id=str(event_id or '')
        if not event_id: return 0
        now=time.time(); state=str(state or 'UNKNOWN').upper(); details=dict(details or {})
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO history_event(date,league,event_id,discovery_state,discovery_json,last_discovery_at,last_success_at,next_retry_at,last_error,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(date,league,event_id) DO UPDATE SET
                    discovery_state=excluded.discovery_state,
                    discovery_json=excluded.discovery_json,
                    last_discovery_at=excluded.last_discovery_at,
                    last_success_at=CASE WHEN excluded.last_success_at>0 THEN excluded.last_success_at ELSE history_event.last_success_at END,
                    next_retry_at=excluded.next_retry_at,
                    last_error=excluded.last_error,
                    updated_at=excluded.updated_at
                """,
                (date,league,event_id,state,self._dump_obj(details),now,now if success else 0,float(retry_at or 0),str(error or '')[:1000],now),
            )
            conn.commit()
        return now

    def get_event(self, date, league, event_id):
        with self._lock, closing(self._connect()) as conn:
            row=conn.execute("SELECT * FROM history_event WHERE date=? AND league=? AND event_id=?",(str(date)[:10],str(league).upper(),str(event_id))).fetchone()
        if not row: return None
        return {
            "date":row["date"],"league":row["league"],"eventId":row["event_id"],"event":self._load_obj(row["event_json"]),
            "discoveryState":row["discovery_state"],"discovery":self._load_obj(row["discovery_json"]),
            "lastDiscoveryAt":float(row["last_discovery_at"] or 0),"lastSuccessAt":float(row["last_success_at"] or 0),
            "nextRetryAt":float(row["next_retry_at"] or 0),"lastError":row["last_error"] or "","updatedAt":float(row["updated_at"] or 0),
        }

    def put_event_media(self, date, league, event_id, rows):
        date=str(date)[:10]; league=str(league).upper(); event_id=str(event_id or '')
        if not event_id: return 0
        now=time.time(); count=0
        with self._lock, closing(self._connect()) as conn:
            for raw in rows or []:
                if not isinstance(raw,dict): continue
                item=dict(raw); asset_key=self.asset_key_for(item)
                if not asset_key: continue
                validation=self.validation_state_for(item)
                verified_at=float(item.get("historyVerifiedAt") or item.get("verifiedAt") or (now if validation=="VERIFIED" else 0) or 0)
                existing=conn.execute(
                    "SELECT asset_json,validation_state,verified_at,runtime_state,runtime_success_at,runtime_failure_at,runtime_failure_reason FROM history_media_asset WHERE date=? AND league=? AND event_id=? AND asset_key=?",
                    (date,league,event_id,asset_key),
                ).fetchone()
                runtime_state="UNKNOWN"; success_at=failure_at=0.0; failure_reason=""
                if existing:
                    previous=self._load_obj(existing["asset_json"]); previous.update(item); item=previous
                    runtime_state=str(existing["runtime_state"] or "UNKNOWN").upper()
                    success_at=float(existing["runtime_success_at"] or 0); failure_at=float(existing["runtime_failure_at"] or 0); failure_reason=str(existing["runtime_failure_reason"] or '')
                    # A newer positive provider validation can rehabilitate an old
                    # runtime failure. Otherwise the exact asset stays demoted.
                    if runtime_state=="FAILED" and verified_at<=failure_at:
                        item["verifiedPlayable"]=False; item["runtimeState"]="failed"; item["runtimeFailureReason"]=failure_reason
                    elif runtime_state=="FAILED" and verified_at>failure_at:
                        runtime_state="UNKNOWN"; failure_at=0; failure_reason=""
                item["validationState"]=validation
                conn.execute(
                    """
                    INSERT INTO history_media_asset(date,league,event_id,asset_key,asset_json,validation_state,verified_at,runtime_state,runtime_success_at,runtime_failure_at,runtime_failure_reason,last_seen_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(date,league,event_id,asset_key) DO UPDATE SET
                        asset_json=excluded.asset_json,
                        validation_state=excluded.validation_state,
                        verified_at=MAX(history_media_asset.verified_at,excluded.verified_at),
                        runtime_state=excluded.runtime_state,
                        runtime_success_at=excluded.runtime_success_at,
                        runtime_failure_at=excluded.runtime_failure_at,
                        runtime_failure_reason=excluded.runtime_failure_reason,
                        last_seen_at=excluded.last_seen_at,
                        updated_at=excluded.updated_at
                    """,
                    (date,league,event_id,asset_key,self._dump_obj(item),validation,verified_at,runtime_state,success_at,failure_at,failure_reason,now,now),
                )
                count+=1
            conn.commit()
        return count

    def event_media(self, date, league, event_id, include_failed=True):
        with self._lock, closing(self._connect()) as conn:
            rows=conn.execute(
                "SELECT * FROM history_media_asset WHERE date=? AND league=? AND event_id=? ORDER BY verified_at DESC, updated_at DESC",
                (str(date)[:10],str(league).upper(),str(event_id)),
            ).fetchall()
        out=[]
        for row in rows:
            item=self._load_obj(row["asset_json"])
            runtime_state=str(row["runtime_state"] or "UNKNOWN").upper()
            item["validationState"]=row["validation_state"] or "CANDIDATE"
            item["historyVerifiedAt"]=float(row["verified_at"] or item.get("historyVerifiedAt") or 0)
            item["runtimeCatalogState"]=runtime_state
            if runtime_state=="FAILED":
                item["runtimeState"]="failed"; item["verifiedPlayable"]=False
                item["runtimeFailureReason"]=row["runtime_failure_reason"] or ""
                if not include_failed: continue
            elif runtime_state=="PLAYED":
                item["runtimeState"]="playing-confirmed"; item["verifiedPlayable"]=True
            out.append(item)
        return out

    def record_runtime(self, date, league, event_id, asset_key, *, success=False, reason=""):
        date=str(date)[:10]; league=str(league).upper(); event_id=str(event_id or ''); asset_key=str(asset_key or '')
        if not event_id or not asset_key: return False
        now=time.time(); state="PLAYED" if success else "FAILED"
        with self._lock, closing(self._connect()) as conn:
            row=conn.execute("SELECT asset_json FROM history_media_asset WHERE date=? AND league=? AND event_id=? AND asset_key=?",(date,league,event_id,asset_key)).fetchone()
            if not row: return False
            item=self._load_obj(row["asset_json"])
            if success:
                item["runtimeState"]="playing-confirmed"; item["verifiedPlayable"]=True
            else:
                item["runtimeState"]="failed"; item["verifiedPlayable"]=False; item["runtimeFailureReason"]=str(reason or '')[:500]
            conn.execute(
                """
                UPDATE history_media_asset SET asset_json=?, runtime_state=?,
                  runtime_success_at=CASE WHEN ? THEN ? ELSE runtime_success_at END,
                  runtime_failure_at=CASE WHEN ? THEN runtime_failure_at ELSE ? END,
                  runtime_failure_reason=CASE WHEN ? THEN '' ELSE ? END,
                  updated_at=?
                WHERE date=? AND league=? AND event_id=? AND asset_key=?
                """,
                (self._dump_obj(item),state,1 if success else 0,now,1 if success else 0,now,1 if success else 0,str(reason or '')[:500],now,date,league,event_id,asset_key),
            )
            conn.commit()
        return True

    def put_media(self, date, league, rows, merge=True):
        date = str(date)[:10]; league = str(league).upper(); items = list(rows or [])
        if merge:
            current = self.get_league(date, league, prefer_catalog=False).get("media") or []
            merged=[]; positions={}
            def key_for(item):
                return self.asset_key_for(item) or json.dumps(item, sort_keys=True, default=str)
            for item in current:
                if not isinstance(item,dict): continue
                key=key_for(item)
                if key in positions: continue
                positions[key]=len(merged); merged.append(dict(item))
            for item in items:
                if not isinstance(item,dict): continue
                key=key_for(item)
                if key in positions:
                    idx=positions[key]; upgraded=dict(merged[idx]); upgraded.update(item); merged[idx]=upgraded
                else:
                    positions[key]=len(merged); merged.append(dict(item))
            items=merged
        now=time.time()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO history_day(date, league, media_json, media_saved_at)
                VALUES(?,?,?,?)
                ON CONFLICT(date,league) DO UPDATE SET media_json=excluded.media_json, media_saved_at=excluded.media_saved_at
                """,
                (date,league,self._dump(items),now),
            )
            conn.commit()
        # Mirror into normalized catalog outside the first connection/lock scope.
        grouped={}
        for item in items:
            event_id=self.event_id_for(item)
            if event_id: grouped.setdefault(event_id,[]).append(item)
        for event_id,event_items in grouped.items():
            self.put_event_media(date,league,event_id,event_items)
        return now

    def put_discovery(self, date, league, state, merge=True):
        date=str(date)[:10]; league=str(league).upper(); value=dict(state or {})
        if merge:
            current=self.get_league(date,league,prefer_catalog=False).get("discovery") or {}; merged=dict(current); merged.update(value)
            for key in ("deepSearchedEventIds","noQuotaSearchedEventIds"):
                if key in current or key in value:
                    merged[key]=list(dict.fromkeys([*(current.get(key) or []),*(value.get(key) or [])]))
            value=merged
        now=time.time()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO history_day(date,league,discovery_json,discovery_saved_at)
                VALUES(?,?,?,?)
                ON CONFLICT(date,league) DO UPDATE SET discovery_json=excluded.discovery_json, discovery_saved_at=excluded.discovery_saved_at
                """,
                (date,league,self._dump_obj(value),now),
            ); conn.commit()
        return now

    def _catalog_media_for_league(self, date, league):
        with self._lock, closing(self._connect()) as conn:
            rows=conn.execute("SELECT * FROM history_media_asset WHERE date=? AND league=? ORDER BY event_id, verified_at DESC, updated_at DESC",(str(date)[:10],str(league).upper())).fetchall()
        out=[]
        for row in rows:
            item=self._load_obj(row["asset_json"]); runtime=str(row["runtime_state"] or "UNKNOWN").upper()
            item["validationState"]=row["validation_state"] or "CANDIDATE"
            item["historyVerifiedAt"]=float(row["verified_at"] or item.get("historyVerifiedAt") or 0)
            item["runtimeCatalogState"]=runtime
            if runtime=="FAILED":
                item["runtimeState"]="failed"; item["verifiedPlayable"]=False; item["runtimeFailureReason"]=row["runtime_failure_reason"] or ""
            elif runtime=="PLAYED":
                item["runtimeState"]="playing-confirmed"; item["verifiedPlayable"]=True
            out.append(item)
        return out

    def get_league(self, date, league, prefer_catalog=True):
        date=str(date)[:10]; league=str(league).upper()
        with self._lock, closing(self._connect()) as conn:
            row=conn.execute("SELECT * FROM history_day WHERE date=? AND league=?",(date,league)).fetchone()
        if not row:
            base={"date":date,"league":league,"scores":[],"media":[],"discovery":{},"scoresSavedAt":0,"mediaSavedAt":0,"discoverySavedAt":0}
        else:
            keys=set(row.keys())
            base={"date":row["date"],"league":row["league"],"scores":self._load(row["scores_json"]),"media":self._load(row["media_json"]),"discovery":self._load_obj(row["discovery_json"]) if "discovery_json" in keys else {},"scoresSavedAt":float(row["scores_saved_at"] or 0),"mediaSavedAt":float(row["media_saved_at"] or 0),"discoverySavedAt":float(row["discovery_saved_at"] or 0) if "discovery_saved_at" in keys else 0}
        if prefer_catalog:
            catalog=self._catalog_media_for_league(date,league)
            if catalog: base["media"]=catalog
        return base

    def get_day(self, date):
        date=str(date)[:10]; leagues={}
        with self._lock, closing(self._connect()) as conn:
            names=[r[0] for r in conn.execute("SELECT league FROM history_day WHERE date=? UNION SELECT league FROM history_event WHERE date=? UNION SELECT league FROM history_media_asset WHERE date=? ORDER BY league",(date,date,date)).fetchall()]
        for league in names:
            row=self.get_league(date,league,prefer_catalog=True)
            leagues[league]={k:v for k,v in row.items() if k not in ("date","league")}
        return {"date":date,"leagues":leagues}

    def has_scores(self, date, league):
        return bool(self.get_league(date,league,prefer_catalog=False).get("scoresSavedAt"))

    def summary(self):
        with self._lock, closing(self._connect()) as conn:
            row=conn.execute("SELECT COUNT(DISTINCT date) AS days, COUNT(*) AS league_days, MAX(scores_saved_at) AS last_scores, MAX(media_saved_at) AS last_media, MAX(discovery_saved_at) AS last_discovery FROM history_day").fetchone()
            assets=conn.execute("SELECT COUNT(*) AS assets, SUM(CASE WHEN validation_state='VERIFIED' AND runtime_state<>'FAILED' THEN 1 ELSE 0 END) AS verified, SUM(CASE WHEN runtime_state='PLAYED' THEN 1 ELSE 0 END) AS played, SUM(CASE WHEN runtime_state='FAILED' THEN 1 ELSE 0 END) AS failed FROM history_media_asset").fetchone()
            events=conn.execute("SELECT COUNT(*) AS events, SUM(CASE WHEN discovery_state='VERIFIED' THEN 1 ELSE 0 END) AS verified_events FROM history_event").fetchone()
            deep_complete=0
            try:
                for r in conn.execute("SELECT discovery_json FROM history_day WHERE discovery_json IS NOT NULL AND discovery_json<>''"):
                    if self._load_obj(r[0]).get("deepComplete"): deep_complete+=1
            except Exception: deep_complete=0
        return {"days":int(row["days"] or 0),"leagueDays":int(row["league_days"] or 0),"events":int(events["events"] or 0),"verifiedEvents":int(events["verified_events"] or 0),"assets":int(assets["assets"] or 0),"verifiedAssets":int(assets["verified"] or 0),"runtimePlayedAssets":int(assets["played"] or 0),"runtimeFailedAssets":int(assets["failed"] or 0),"deepCompleteLeagueDays":int(deep_complete),"lastScoresSavedAt":float(row["last_scores"] or 0),"lastMediaSavedAt":float(row["last_media"] or 0),"lastDiscoverySavedAt":float(row["last_discovery"] or 0)}

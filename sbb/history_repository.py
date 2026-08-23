import json
import sqlite3
import threading
import time
from contextlib import closing
from sbb.media_scope import annotate as annotate_media_scope, GAME, COLLECTION_SCOPES


class HistoryRepository:
    """Persistent historical score/event/media catalog.

    v3.1.0 keeps the legacy date/league JSON rows for fast score hydration while
    retaining normalized event and asset tables. Discovery metadata now tracks
    source exhaustion separately from preferred-media quality, so Blue/Purple/Green
    assets remain playable while the persistent cloud catalog keeps seeking Gold.
    Runtime playback successes and failures continue to survive browser reloads.
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS history_collection_media (
                    scope TEXT NOT NULL,
                    league TEXT NOT NULL,
                    period_key TEXT NOT NULL,
                    asset_key TEXT NOT NULL,
                    asset_json TEXT NOT NULL,
                    collection_kind TEXT NOT NULL DEFAULT 'ROUNDUP',
                    validation_state TEXT NOT NULL DEFAULT 'CANDIDATE',
                    verified_at REAL NOT NULL DEFAULT 0,
                    runtime_state TEXT NOT NULL DEFAULT 'UNKNOWN',
                    updated_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(scope, league, period_key, asset_key)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_collection_period ON history_collection_media(period_key,league,scope)")
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
    def canonical_event_key(league, event_id):
        return f"{str(league or '').upper()}:{str(event_id or '')}"

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
        league=str(league).upper(); event_id=str(event_id); requested=str(date)[:10]
        with self._lock, closing(self._connect()) as conn:
            row=conn.execute(
                "SELECT * FROM history_event WHERE league=? AND event_id=? ORDER BY last_discovery_at DESC,updated_at DESC,CASE WHEN date=? THEN 0 ELSE 1 END,date DESC LIMIT 1",
                (league,event_id,requested),
            ).fetchone()
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
            event_row=conn.execute("SELECT event_json FROM history_event WHERE league=? AND event_id=? ORDER BY CASE WHEN date=? THEN 0 ELSE 1 END,updated_at DESC LIMIT 1",(league,event_id,date)).fetchone()
            event=self._load_obj(event_row["event_json"]) if event_row else {}
            away=self._audit_team_name(event,"away"); home=self._audit_team_name(event,"home")
            for raw in rows or []:
                if not isinstance(raw,dict): continue
                item=annotate_media_scope(dict(raw),league=league,date=date,away=away,home=home)
                item["canonicalEventKey"]=self.canonical_event_key(league,event_id)
                if item.get("mediaScope") != GAME: continue
                asset_key=self.asset_key_for(item)
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
        league=str(league).upper(); event_id=str(event_id)
        with self._lock, closing(self._connect()) as conn:
            rows=conn.execute(
                "SELECT * FROM history_media_asset WHERE league=? AND event_id=? AND COALESCE(json_extract(asset_json,'$.mediaScope'),'GAME')='GAME' ORDER BY verified_at DESC, updated_at DESC",
                (league,event_id),
            ).fetchall()
        out=[]; seen=set()
        for row in rows:
            if row["asset_key"] in seen: continue
            seen.add(row["asset_key"])
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
            row=conn.execute("SELECT asset_json FROM history_media_asset WHERE league=? AND event_id=? AND asset_key=? ORDER BY CASE WHEN date=? THEN 0 ELSE 1 END,updated_at DESC LIMIT 1",(league,event_id,asset_key,date)).fetchone()
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
                WHERE league=? AND event_id=? AND asset_key=?
                """,
                (self._dump_obj(item),state,1 if success else 0,now,1 if success else 0,now,1 if success else 0,str(reason or '')[:500],now,league,event_id,asset_key),
            )
            conn.commit()
        return True

    def green_gap_events(self, *, current_discovery_version=0, now=None, limit=24, recent_cooldown=2*60*60, archive_cooldown=24*60*60):
        """Return canonical, due games that lack verified GAME-scoped Green/Gold.

        League + provider Event ID is the durable identity. Adjacent-date aliases do
        not generate duplicate queue work. A cooldown applies even across discovery
        version migrations, preventing the same event from being retried repeatedly.
        """
        now=float(now or time.time()); limit=max(1,min(200,int(limit or 24)))
        current=int(current_discovery_version or 0)
        with self._lock, closing(self._connect()) as conn:
            rows=conn.execute(
                """
                WITH canonical AS (
                  SELECT * FROM (
                    SELECT e.*,ROW_NUMBER() OVER(PARTITION BY league,event_id ORDER BY last_discovery_at DESC,updated_at DESC,date DESC) rn
                    FROM history_event e
                  ) WHERE rn=1
                ), flags AS (
                  SELECT league,event_id,
                    SUM(CASE WHEN validation_state='VERIFIED' AND runtime_state<>'FAILED' AND COALESCE(json_extract(asset_json,'$.mediaScope'),'GAME')='GAME' THEN 1 ELSE 0 END) verified_count,
                    MAX(CASE WHEN validation_state='VERIFIED' AND runtime_state<>'FAILED' AND COALESCE(json_extract(asset_json,'$.mediaScope'),'GAME')='GAME' AND json_extract(asset_json,'$.recapTier')='gold' THEN 1 ELSE 0 END) has_gold,
                    MAX(CASE WHEN validation_state='VERIFIED' AND runtime_state<>'FAILED' AND COALESCE(json_extract(asset_json,'$.mediaScope'),'GAME')='GAME' AND json_extract(asset_json,'$.recapTier')='green' THEN 1 ELSE 0 END) has_green,
                    MAX(CASE WHEN validation_state='VERIFIED' AND runtime_state<>'FAILED' AND COALESCE(json_extract(asset_json,'$.mediaScope'),'GAME')='GAME' AND json_extract(asset_json,'$.recapTier')='extended' THEN 1 ELSE 0 END) has_extended,
                    MAX(CASE WHEN validation_state='VERIFIED' AND runtime_state<>'FAILED' AND COALESCE(json_extract(asset_json,'$.mediaScope'),'GAME')='GAME' AND COALESCE(json_extract(asset_json,'$.recapTier'),'blue')='blue' THEN 1 ELSE 0 END) has_blue
                  FROM history_media_asset GROUP BY league,event_id
                )
                SELECT e.*,COALESCE(f.verified_count,0) verified_count,COALESCE(f.has_gold,0) has_gold,
                       COALESCE(f.has_green,0) has_green,COALESCE(f.has_extended,0) has_extended,COALESCE(f.has_blue,0) has_blue
                FROM canonical e LEFT JOIN flags f ON f.league=e.league AND f.event_id=e.event_id
                WHERE COALESCE(f.has_gold,0)=0 AND COALESCE(f.has_green,0)=0
                  AND (e.next_retry_at<=? OR COALESCE(CAST(json_extract(e.discovery_json,'$.discoveryVersion') AS INTEGER),0)<?)
                  AND (e.last_discovery_at<=0 OR e.last_discovery_at <= ? - CASE WHEN e.date>=date('now','-2 days') THEN ? ELSE ? END)
                ORDER BY
                  CASE WHEN e.date>=date('now','-2 days') AND COALESCE(f.verified_count,0)=0 THEN -3
                       WHEN e.date>=date('now','-2 days') AND COALESCE(f.has_blue,0)=1 THEN -2
                       WHEN e.date>=date('now','-2 days') AND COALESCE(f.has_extended,0)=1 THEN -1
                       WHEN COALESCE(f.has_blue,0)=1 THEN 0
                       WHEN COALESCE(f.verified_count,0)=0 THEN 1
                       WHEN COALESCE(f.has_extended,0)=1 THEN 2 ELSE 3 END,
                  e.date DESC,e.last_discovery_at ASC LIMIT ?
                """,
                (now,current,now,float(recent_cooldown),float(archive_cooldown),limit),
            ).fetchall()
        out=[]
        for row in rows:
            event=self._load_obj(row['event_json']); discovery=self._load_obj(row['discovery_json'])
            best='blue' if int(row['has_blue'] or 0) else ('extended' if int(row['has_extended'] or 0) else '')
            out.append({'date':row['date'],'league':row['league'],'eventId':row['event_id'],'canonicalEventKey':self.canonical_event_key(row['league'],row['event_id']),
                'event':event,'discoveryState':row['discovery_state'],'discovery':discovery,'nextRetryAt':float(row['next_retry_at'] or 0),
                'lastDiscoveryAt':float(row['last_discovery_at'] or 0),'verifiedCount':int(row['verified_count'] or 0),'hasBlue':bool(row['has_blue']),
                'hasExtended':bool(row['has_extended']),'bestTier':best or 'none'})
        return out

    def green_gap_summary(self, *, current_discovery_version=0, now=None, recent_cooldown=2*60*60, archive_cooldown=24*60*60):
        """Aggregate canonical game coverage and migration state for the console."""
        now=float(now or time.time()); current=int(current_discovery_version or 0)
        with self._lock, closing(self._connect()) as conn:
            row=conn.execute(
                """
                WITH canonical AS (
                  SELECT * FROM (SELECT e.*,ROW_NUMBER() OVER(PARTITION BY league,event_id ORDER BY last_discovery_at DESC,updated_at DESC,date DESC) rn FROM history_event e) WHERE rn=1
                ), flags AS (
                  SELECT league,event_id,
                    SUM(CASE WHEN validation_state='VERIFIED' AND runtime_state<>'FAILED' AND COALESCE(json_extract(asset_json,'$.mediaScope'),'GAME')='GAME' THEN 1 ELSE 0 END) verified_count,
                    MAX(CASE WHEN validation_state='VERIFIED' AND runtime_state<>'FAILED' AND COALESCE(json_extract(asset_json,'$.mediaScope'),'GAME')='GAME' AND json_extract(asset_json,'$.recapTier')='gold' THEN 1 ELSE 0 END) has_gold,
                    MAX(CASE WHEN validation_state='VERIFIED' AND runtime_state<>'FAILED' AND COALESCE(json_extract(asset_json,'$.mediaScope'),'GAME')='GAME' AND json_extract(asset_json,'$.recapTier')='green' THEN 1 ELSE 0 END) has_green,
                    MAX(CASE WHEN validation_state='VERIFIED' AND runtime_state<>'FAILED' AND COALESCE(json_extract(asset_json,'$.mediaScope'),'GAME')='GAME' AND json_extract(asset_json,'$.recapTier')='extended' THEN 1 ELSE 0 END) has_extended,
                    MAX(CASE WHEN validation_state='VERIFIED' AND runtime_state<>'FAILED' AND COALESCE(json_extract(asset_json,'$.mediaScope'),'GAME')='GAME' AND COALESCE(json_extract(asset_json,'$.recapTier'),'blue')='blue' THEN 1 ELSE 0 END) has_blue,
                    SUM(CASE WHEN validation_state='CANDIDATE' AND COALESCE(json_extract(asset_json,'$.mediaScope'),'GAME')='GAME' THEN 1 ELSE 0 END) candidate_count
                  FROM history_media_asset GROUP BY league,event_id
                )
                SELECT COUNT(*) total_events,
                  SUM(CASE WHEN COALESCE(f.has_gold,0)=0 AND COALESCE(f.has_green,0)=0 THEN 1 ELSE 0 END) gaps,
                  SUM(CASE WHEN COALESCE(f.has_gold,0)=0 AND COALESCE(f.has_green,0)=0 AND COALESCE(f.has_blue,0)=1 THEN 1 ELSE 0 END) blue_only,
                  SUM(CASE WHEN COALESCE(f.has_gold,0)=0 AND COALESCE(f.has_green,0)=0 AND COALESCE(f.has_extended,0)=1 AND COALESCE(f.has_blue,0)=0 THEN 1 ELSE 0 END) purple_only,
                  SUM(CASE WHEN COALESCE(CAST(json_extract(e.discovery_json,'$.discoveryVersion') AS INTEGER),0)<? THEN 1 ELSE 0 END) unindexed,
                  SUM(CASE WHEN COALESCE(CAST(json_extract(e.discovery_json,'$.discoveryVersion') AS INTEGER),0)>=? AND e.discovery_state='SEARCHED_EMPTY' AND COALESCE(f.verified_count,0)=0 THEN 1 ELSE 0 END) searched_empty,
                  SUM(CASE WHEN COALESCE(f.verified_count,0)>0 THEN 1 ELSE 0 END) coverage_complete,
                  SUM(CASE WHEN COALESCE(f.verified_count,0)=0 AND COALESCE(f.candidate_count,0)>0 THEN 1 ELSE 0 END) candidate_only,
                  SUM(CASE WHEN e.date>=date('now','-2 days') AND COALESCE(f.has_gold,0)=0 AND COALESCE(f.has_green,0)=0 THEN 1 ELSE 0 END) recent_gaps,
                  SUM(CASE WHEN e.date>=date('now','-2 days') AND COALESCE(f.verified_count,0)=0 THEN 1 ELSE 0 END) recent_uncovered,
                  SUM(CASE WHEN COALESCE(f.has_gold,0)=0 AND COALESCE(f.has_green,0)=0
                    AND (e.next_retry_at<=? OR COALESCE(CAST(json_extract(e.discovery_json,'$.discoveryVersion') AS INTEGER),0)<?)
                    AND (e.last_discovery_at<=0 OR e.last_discovery_at <= ? - CASE WHEN e.date>=date('now','-2 days') THEN ? ELSE ? END)
                    THEN 1 ELSE 0 END) due_now,
                  SUM(CASE WHEN COALESCE(CAST(json_extract(e.discovery_json,'$.discoveryVersion') AS INTEGER),0)<? THEN 1 ELSE 0 END) stale_version
                FROM canonical e LEFT JOIN flags f ON f.league=e.league AND f.event_id=e.event_id
                """,(current,current,now,current,now,float(recent_cooldown),float(archive_cooldown),current),
            ).fetchone()
        out={k:int(row[k] or 0) for k in row.keys()} if row else {}
        # Compatibility aliases for older UI/tests; "no_media" no longer means unindexed.
        out['no_media']=out.get('searched_empty',0); out['recent_no_media']=out.get('recent_uncovered',0)
        return out

    def put_collection_media(self, scope, league, period_key, rows, *, collection_kind="ROUNDUP"):
        scope=str(scope or '').upper(); league=str(league or '').upper(); period_key=str(period_key or '')
        if scope not in COLLECTION_SCOPES or not league or not period_key: return 0
        now=time.time(); count=0
        with self._lock, closing(self._connect()) as conn:
            for raw in rows or []:
                if not isinstance(raw,dict): continue
                item=annotate_media_scope(dict(raw),league=league,date=period_key[:10])
                if item.get('mediaScope') not in COLLECTION_SCOPES: continue
                asset_key=self.asset_key_for(item)
                if not asset_key: continue
                validation=self.validation_state_for(item); verified_at=float(item.get('historyVerifiedAt') or item.get('verifiedAt') or (now if validation=='VERIFIED' else 0) or 0)
                item['collectionTier']='silver'; item['displayTier']='silver'; item['collectionPeriodKey']=period_key
                kind=str(item.get('collectionKind') or collection_kind or 'ROUNDUP').upper(); item['collectionKind']=kind
                conn.execute("""
                    INSERT INTO history_collection_media(scope,league,period_key,asset_key,asset_json,collection_kind,validation_state,verified_at,runtime_state,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(scope,league,period_key,asset_key) DO UPDATE SET
                      asset_json=excluded.asset_json,collection_kind=excluded.collection_kind,
                      validation_state=CASE WHEN excluded.validation_state='VERIFIED' THEN 'VERIFIED' ELSE history_collection_media.validation_state END,
                      verified_at=MAX(history_collection_media.verified_at,excluded.verified_at),updated_at=excluded.updated_at
                """,(scope,league,period_key,asset_key,self._dump_obj(item),kind,validation,verified_at,'UNKNOWN',now))
                count+=1
            conn.commit()
        return count

    def roundup_media(self, date, league=None):
        date=str(date or '')[:10]; league=str(league or '').upper()
        with self._lock, closing(self._connect()) as conn:
            if league and league!='ALL':
                rows=conn.execute("SELECT * FROM history_collection_media WHERE league=? AND ((scope='DAY_LEAGUE' AND period_key=?) OR (scope='WEEK_LEAGUE' AND json_extract(asset_json,'$.date')=?)) ORDER BY verified_at DESC,updated_at DESC",(league,date,date)).fetchall()
            else:
                rows=conn.execute("SELECT * FROM history_collection_media WHERE (scope='DAY_LEAGUE' AND period_key=?) OR (scope='WEEK_LEAGUE' AND json_extract(asset_json,'$.date')=?) ORDER BY league,verified_at DESC,updated_at DESC",(date,date)).fetchall()
        out=[]; seen=set()
        for row in rows:
            if row['asset_key'] in seen: continue
            seen.add(row['asset_key']); item=self._load_obj(row['asset_json'])
            item['mediaScope']=row['scope']; item['collectionTier']='silver'; item['displayTier']='silver'; item['collectionKind']=row['collection_kind']; item['collectionPeriodKey']=row['period_key']
            item['validationState']=row['validation_state']; item['historyVerifiedAt']=float(row['verified_at'] or 0)
            if str(row['runtime_state'] or '').upper()=='FAILED': item['verifiedPlayable']=False; item['runtimeState']='failed'
            out.append(item)
        def rank(x):
            kind=str(x.get('collectionKind') or ''); scope=str(x.get('mediaScope') or '')
            return (4 if scope=='DAY_LEAGUE' and kind=='DAILY_RECAP' else 3 if scope=='DAY_LEAGUE' and kind=='TOP_PLAYS' else 2 if scope=='WEEK_LEAGUE' else 1,
                    1 if x.get('verifiedPlayable') else 0, int(x.get('durationSeconds') or x.get('duration') or 0))
        out.sort(key=rank,reverse=True)
        return out

    def reclassify_media_scopes(self):
        """Soft-migrate v3.0.x assets without losing durable provider discoveries."""
        moved=updated=0
        with self._lock, closing(self._connect()) as conn:
            rows=conn.execute("SELECT a.rowid rid,a.*,e.event_json FROM history_media_asset a LEFT JOIN history_event e ON e.date=a.date AND e.league=a.league AND e.event_id=a.event_id").fetchall()
            for row in rows:
                item=self._load_obj(row['asset_json']); event=self._load_obj(row['event_json'])
                away=self._audit_team_name(event,'away'); home=self._audit_team_name(event,'home')
                # v3.0.x generic YouTube rows may already carry a bogus matchId /
                # scoreEventId because association happened before matchup proof.
                # Reclassification must distrust those legacy stamps and rebuild
                # scope from provider authority + the title/opponent fingerprint.
                probe=dict(item); probe.pop('mediaScope',None)
                generic_channel=bool(probe.get('youtubeId')) and str(probe.get('sourceType') or '').lower() not in {'espn-event-video','mlb-game-content','nfl-event-video','official-nfl-club-site'}
                if generic_channel:
                    for key in ('matchId','scoreEventId','espnEventId','canonicalEventId','canonicalEventKey'): probe.pop(key,None)
                classified=annotate_media_scope(probe,league=row['league'],date=row['date'],away=away,home=home)
                scoped=dict(item); scoped.update({k:v for k,v in classified.items() if k in ('mediaScope','collectionTier','displayTier','collectionKind','collectionPeriodKey')})
                scope=scoped.get('mediaScope')
                if scope in COLLECTION_SCOPES:
                    for key in ('matchId','scoreEventId','espnEventId','canonicalEventId','canonicalEventKey'): scoped.pop(key,None)
                if scope in COLLECTION_SCOPES:
                    period=str(scoped.get('collectionPeriodKey') or row['date'])
                    # Persist after this transaction through direct SQL to avoid nested connections.
                    kind=str(scoped.get('collectionKind') or 'ROUNDUP')
                    conn.execute("""INSERT INTO history_collection_media(scope,league,period_key,asset_key,asset_json,collection_kind,validation_state,verified_at,runtime_state,updated_at)
                      VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(scope,league,period_key,asset_key) DO UPDATE SET asset_json=excluded.asset_json,validation_state=excluded.validation_state,verified_at=MAX(history_collection_media.verified_at,excluded.verified_at),updated_at=excluded.updated_at""",
                      (scope,row['league'],period,row['asset_key'],self._dump_obj(scoped),kind,row['validation_state'],row['verified_at'],row['runtime_state'],time.time()))
                    conn.execute("DELETE FROM history_media_asset WHERE rowid=?",(row['rid'],)); moved+=1
                else:
                    if scoped!=item:
                        conn.execute("UPDATE history_media_asset SET asset_json=?,updated_at=? WHERE rowid=?",(self._dump_obj(scoped),time.time(),row['rid'])); updated+=1
            conn.commit()
        return {'movedToCollections':moved,'updatedScopes':updated}

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
        date=str(date)[:10]; league=str(league).upper()
        with self._lock, closing(self._connect()) as conn:
            ids={str(r[0]) for r in conn.execute("SELECT event_id FROM history_event WHERE date=? AND league=?",(date,league)).fetchall() if r[0]}
            day=conn.execute("SELECT scores_json FROM history_day WHERE date=? AND league=?",(date,league)).fetchone()
            if day:
                for score in self._load(day['scores_json']):
                    eid=self.event_id_for(score)
                    if eid: ids.add(eid)
            if not ids: return []
            marks=','.join('?' for _ in ids)
            rows=conn.execute(f"SELECT * FROM history_media_asset WHERE league=? AND event_id IN ({marks}) AND COALESCE(json_extract(asset_json,'$.mediaScope'),'GAME')='GAME' ORDER BY event_id,verified_at DESC,updated_at DESC",[league,*sorted(ids)]).fetchall()
        out=[]; seen=set()
        for row in rows:
            dedupe=(row['event_id'],row['asset_key'])
            if dedupe in seen: continue
            seen.add(dedupe)
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
        return {"date":date,"leagues":leagues,"roundups":self.roundup_media(date)}

    def has_scores(self, date, league):
        return bool(self.get_league(date,league,prefer_catalog=False).get("scoresSavedAt"))

    @staticmethod
    def _audit_team_name(event, side):
        event=event if isinstance(event,dict) else {}
        team=event.get(f"{side}Team") or event.get(side) or {}
        if isinstance(team,dict):
            return str(team.get("displayName") or team.get("name") or team.get("shortName") or team.get("abbreviation") or team.get("abbr") or "").strip()
        return str(team or "").strip()

    @staticmethod
    def _audit_asset_view(row, item):
        item=item if isinstance(item,dict) else {}
        tier=str(item.get("recapTier") or "blue")
        if tier not in {"gold","green","extended","blue"}: tier="blue"
        youtube_id=str(item.get("youtubeId") or "").strip()
        media_url=str(item.get("mediaUrl") or "").strip()
        external_url=str(item.get("externalUrl") or "").strip()
        url=external_url or (f"https://www.youtube.com/watch?v={youtube_id}" if youtube_id else media_url)
        try: duration=int(float(item.get("durationSeconds") or item.get("duration") or 0))
        except Exception: duration=0
        runtime=str(row["runtime_state"] or "UNKNOWN").upper()
        validation=str(row["validation_state"] or "CANDIDATE").upper()
        return {
            "assetKey":row["asset_key"],"tier":tier,"title":str(item.get("title") or "Untitled media"),
            "durationSeconds":duration,"provider":str(item.get("provider") or item.get("sourceLabel") or item.get("source") or ""),
            "source":str(item.get("sourceLabel") or item.get("source") or ""),"url":url,
            "youtubeId":youtube_id,"mediaUrl":media_url,"validationState":validation,"runtimeState":runtime,
            "verified":bool(validation=="VERIFIED" and runtime!="FAILED" and (youtube_id or media_url)),
            "verifiedAt":float(row["verified_at"] or 0),"runtimeSuccessAt":float(row["runtime_success_at"] or 0),
            "runtimeFailureAt":float(row["runtime_failure_at"] or 0),"runtimeFailureReason":str(row["runtime_failure_reason"] or ""),
            "lastSeenAt":float(row["last_seen_at"] or 0),
        }

    @staticmethod
    def _audit_effective_status(discovery_state, discovery, *, best_tier="", verified_count=0,
                                current_discovery_version=0, quality_target="gold"):
        """Project durable catalog truth into a human-readable audit status.

        Raw history_event.discovery_state is intentionally preserved for diagnostics, but
        older rows can remain UNKNOWN until the current per-event discovery pipeline has
        revisited them. The audit must not confuse that migration state with "we know
        nothing": verified media, current discovery version, and quality/catalog flags are
        combined here into an effective read-only status.
        """
        discovery=discovery if isinstance(discovery,dict) else {}
        raw=str(discovery_state or "UNKNOWN").upper()
        try: version=int(discovery.get("discoveryVersion") or 0)
        except Exception: version=0
        try: current_version=int(current_discovery_version or 0)
        except Exception: current_version=0
        version_current=bool(not current_version or version>=current_version)
        target=str(quality_target or "gold").lower()
        best=str(best_tier or "").lower()

        # Actual verified catalog content outranks stale bookkeeping. If Gold exists,
        # the quality target is met even before the old event row is rewritten.
        quality_complete=bool(best==target or (version_current and discovery.get("qualityComplete") is True))
        catalog_complete=bool(version_current and discovery.get("catalogComplete") is True)
        discovery_pending=bool(not version_current or raw in {"", "UNKNOWN"})
        inferred_upgrade=bool(best and best!=target and not quality_complete)
        upgrade_eligible=bool(inferred_upgrade or (version_current and discovery.get("upgradeEligible") is True))

        if quality_complete:
            effective="QUALITY_COMPLETE"
        elif discovery_pending:
            effective="PENDING_INDEX"
        elif verified_count:
            effective="UPGRADE_PENDING" if (catalog_complete and upgrade_eligible) else "PARTIAL"
        elif raw=="DEGRADED_PROVIDER":
            effective="PROVIDER_DEGRADED"
        elif raw=="CANDIDATE_ONLY":
            effective="CANDIDATE_ONLY"
        elif raw=="SEARCHED_EMPTY":
            effective="NO_MEDIA_FOUND"
        elif raw=="VERIFIED_UPGRADE_PENDING":
            effective="UPGRADE_PENDING"
        elif raw=="VERIFIED_PARTIAL":
            effective="PARTIAL"
        elif raw=="VERIFIED":
            effective="PARTIAL"
        else:
            effective="PENDING_INDEX"

        return {
            "effectiveStatus":effective,"discoveryState":raw,"discoveryVersion":version,
            "currentDiscoveryVersion":current_version,"versionCurrent":version_current,
            "discoveryPending":discovery_pending,"catalogComplete":catalog_complete,
            "qualityComplete":quality_complete,"upgradeEligible":upgrade_eligible,
        }

    def audit_catalog(self, *, date_from="", date_to="", league="", best_tier="", status="", search="", limit=100, offset=0,
                      current_discovery_version=0, quality_target="gold"):
        """Return an Excel-like game-level view of the normalized history catalog.

        v3.1.0 deliberately exposes an *effective* audit status in addition to the raw
        discovery state. This keeps legacy UNKNOWN rows from looking empty when the
        persistent media catalog already contains verified Green/Purple/Blue assets.
        """
        date_from=str(date_from or "")[:10]; date_to=str(date_to or "")[:10]; league=str(league or "").upper()
        best_tier=str(best_tier or "").lower(); status=str(status or "").lower(); search=str(search or "").strip().lower()
        limit=max(1,min(500,int(limit or 100))); offset=max(0,int(offset or 0))
        where=[]; args=[]
        if date_from: where.append("date>=?"); args.append(date_from)
        if date_to: where.append("date<=?"); args.append(date_to)
        if league: where.append("league=?"); args.append(league)
        clause=(" WHERE "+" AND ".join(where)) if where else ""
        with self._lock, closing(self._connect()) as conn:
            # League + sporting Event ID is the durable game identity. The audit
            # projects one canonical row even when UTC/viewer-day aliases created
            # duplicate date records in an older catalog.
            inner_clause=clause
            events=conn.execute(f"""SELECT * FROM (
                SELECT e.*,ROW_NUMBER() OVER(PARTITION BY league,event_id ORDER BY last_discovery_at DESC,updated_at DESC,date DESC) rn
                FROM history_event e{inner_clause}
              ) WHERE rn=1 ORDER BY date DESC,league,event_id""",args).fetchall()
            asset_where=list(where); asset_args=list(args)
            asset_where.append("COALESCE(json_extract(asset_json,'$.mediaScope'),'GAME')='GAME'")
            asset_clause=(" WHERE "+" AND ".join(asset_where)) if asset_where else ""
            assets=conn.execute(f"SELECT * FROM history_media_asset{asset_clause} ORDER BY league,event_id,verified_at DESC,updated_at DESC",asset_args).fetchall()
        by_event={}
        seen_assets=set()
        for row in assets:
            key=(row["league"],row["event_id"]); dedupe=(key,row["asset_key"])
            if dedupe in seen_assets: continue
            seen_assets.add(dedupe)
            item=self._load_obj(row["asset_json"])
            by_event.setdefault(key,[]).append(self._audit_asset_view(row,item))
        priority={"gold":4,"green":3,"extended":2,"blue":1,"":0}
        rows=[]; summary={"games":0,"verifiedAssets":0,"candidateAssets":0,"runtimeFailedAssets":0,
                         "tiers":{"gold":0,"green":0,"extended":0,"blue":0},
                         "best":{"gold":0,"green":0,"extended":0,"blue":0,"none":0},
                         "effectiveStatuses":{"QUALITY_COMPLETE":0,"UPGRADE_PENDING":0,"PARTIAL":0,"PENDING_INDEX":0,
                                              "NO_MEDIA_FOUND":0,"PROVIDER_DEGRADED":0,"CANDIDATE_ONLY":0},
                         "upgradePendingGames":0,"qualityCompleteGames":0,"discoveryPendingGames":0,
                         "noVerifiedMediaGames":0,"greenCoverageGames":0,"greenCoverageByLeague":{}}
        for erow in events:
            event=self._load_obj(erow["event_json"]); discovery=self._load_obj(erow["discovery_json"])
            key=(erow["league"],erow["event_id"]); event_assets=by_event.get(key,[])
            tiers={"gold":[],"green":[],"extended":[],"blue":[]}
            for asset in event_assets:
                tiers.setdefault(asset["tier"],[]).append(asset)
            for values in tiers.values():
                values.sort(key=lambda a:(bool(a.get("verified")),float(a.get("runtimeSuccessAt") or 0),float(a.get("verifiedAt") or 0),int(a.get("durationSeconds") or 0)),reverse=True)
            verified=[a for a in event_assets if a.get("verified")]
            best=max((a.get("tier") or "" for a in verified),key=lambda t:priority.get(t,0),default="")
            away=self._audit_team_name(event,"away"); home=self._audit_team_name(event,"home")
            game=f"{away} @ {home}".strip(" @") or str(erow["event_id"])
            projected=self._audit_effective_status(erow["discovery_state"],discovery,best_tier=best,verified_count=len(verified),
                                                   current_discovery_version=current_discovery_version,quality_target=quality_target)
            quality_complete=bool(projected["qualityComplete"])
            upgrade_eligible=bool(projected["upgradeEligible"])
            discovery_state=str(projected["discoveryState"])
            effective_status=str(projected["effectiveStatus"])
            hay=f"{erow['date']} {erow['league']} {game} {erow['event_id']} "+" ".join(str(a.get('title') or '') for a in event_assets)
            if search and search not in hay.lower(): continue
            if best_tier and (best or "none")!=best_tier: continue
            if status=="upgrade" and not upgrade_eligible: continue
            if status=="complete" and not quality_complete: continue
            if status=="pending" and effective_status!="PENDING_INDEX": continue
            if status=="partial" and effective_status!="PARTIAL": continue
            if status=="degraded" and effective_status!="PROVIDER_DEGRADED": continue
            if status=="candidate" and effective_status!="CANDIDATE_ONLY": continue
            if status=="failed" and not any(str(a.get("runtimeState"))=="FAILED" for a in event_assets): continue
            if status=="no-media" and verified: continue
            summary["games"]+=1
            summary["verifiedAssets"]+=len(verified)
            summary["candidateAssets"]+=sum(1 for a in event_assets if not a.get("verified") and a.get("validationState") in {"CANDIDATE","EXTERNAL"})
            summary["runtimeFailedAssets"]+=sum(1 for a in event_assets if a.get("runtimeState")=="FAILED")
            for tier in summary["tiers"]: summary["tiers"][tier]+=sum(1 for a in tiers.get(tier,[]) if a.get("verified"))
            summary["best"][best or "none"]+=1
            summary["effectiveStatuses"].setdefault(effective_status,0); summary["effectiveStatuses"][effective_status]+=1
            if upgrade_eligible: summary["upgradePendingGames"]+=1
            if quality_complete: summary["qualityCompleteGames"]+=1
            if projected["discoveryPending"]: summary["discoveryPendingGames"]+=1
            if not verified: summary["noVerifiedMediaGames"]+=1
            league_cov=summary["greenCoverageByLeague"].setdefault(str(erow["league"]),{"games":0,"greenGames":0,"greenOrGoldGames":0})
            league_cov["games"]+=1
            has_green=any(a.get("verified") for a in tiers.get("green",[]))
            has_gold=any(a.get("verified") for a in tiers.get("gold",[]))
            if has_green:
                summary["greenCoverageGames"]+=1; league_cov["greenGames"]+=1
            if has_green or has_gold: league_cov["greenOrGoldGames"]+=1
            rows.append({
                "date":erow["date"],"league":erow["league"],"eventId":erow["event_id"],"away":away,"home":home,"game":game,
                "discoveryState":discovery_state,"effectiveStatus":effective_status,"bestTier":best or "none",
                "qualityComplete":quality_complete,"upgradeEligible":upgrade_eligible,"catalogComplete":bool(projected["catalogComplete"]),
                "discoveryPending":bool(projected["discoveryPending"]),"discoveryVersion":int(projected["discoveryVersion"] or 0),
                "currentDiscoveryVersion":int(projected["currentDiscoveryVersion"] or 0),"versionCurrent":bool(projected["versionCurrent"]),
                "nextRetryAt":float(erow["next_retry_at"] or 0),"lastDiscoveryAt":float(erow["last_discovery_at"] or 0),"lastError":str(erow["last_error"] or ""),
                "tiers":tiers,"verifiedAssetCount":len(verified),"assetCount":len(event_assets),
            })
        total=len(rows); page=rows[offset:offset+limit]
        return {"summary":summary,"rows":page,"total":total,"limit":limit,"offset":offset}

    def audit_export_rows(self, **filters):
        filters=dict(filters); filters["limit"]=500; filters["offset"]=0
        # Page through the same projected game view so browser and exports show the
        # same effective status and inferred upgrade eligibility.
        first=self.audit_catalog(**filters); games=list(first["rows"]); total=int(first["total"] or 0)
        offset=len(games)
        while offset<total:
            page_filters=dict(filters); page_filters["offset"]=offset
            page=self.audit_catalog(**page_filters); chunk=page["rows"]
            if not chunk: break
            games.extend(chunk); offset+=len(chunk)
        out=[]
        def common(game):
            return {
                "Best Tier":"purple" if game.get("bestTier")=="extended" else game.get("bestTier"),
                "Audit Status":str(game.get("effectiveStatus") or "PENDING_INDEX").replace("_"," "),
                "Discovery Pending":bool(game.get("discoveryPending")),"Upgrade Pending":bool(game.get("upgradeEligible")),
                "Catalog Complete":bool(game.get("catalogComplete")),"Quality Complete":bool(game.get("qualityComplete")),
                "Discovery Version":int(game.get("discoveryVersion") or 0),"Current Discovery Version":int(game.get("currentDiscoveryVersion") or 0),
                "Discovery State":game.get("discoveryState") or "UNKNOWN",
            }
        for game in games:
            emitted=False
            for tier in ("gold","green","extended","blue"):
                for asset in game.get("tiers",{}).get(tier,[]):
                    emitted=True
                    row={
                        "Date":game["date"],"League":game["league"],"Game":game["game"],"Event ID":game["eventId"],
                        "Tier":"purple" if tier=="extended" else tier,"Title":asset.get("title") or "","Duration Seconds":asset.get("durationSeconds") or 0,
                        "Provider":asset.get("provider") or "","URL":asset.get("url") or "","Validation":asset.get("validationState") or "",
                        "Runtime":asset.get("runtimeState") or "","Verified":bool(asset.get("verified")),"Last Verified":asset.get("verifiedAt") or 0,
                    }
                    row.update(common(game)); out.append(row)
            if not emitted:
                row={"Date":game["date"],"League":game["league"],"Game":game["game"],"Event ID":game["eventId"],"Tier":"","Title":"",
                     "Duration Seconds":0,"Provider":"","URL":"","Validation":"","Runtime":"","Verified":False,"Last Verified":0}
                row.update(common(game)); out.append(row)
        return out

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

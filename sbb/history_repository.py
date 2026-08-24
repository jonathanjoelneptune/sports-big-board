import json
import hashlib
import os
import re
import sqlite3
import threading
import time
from contextlib import closing

from sbb.catalog_contract import (
    CATALOG_SCHEMA_VERSION, MEDIA_CLASSIFIER_VERSION, EVENT_MATCHER_VERSION,
    RANKING_VERSION, VERIFICATION_VERSION, ASSIGNED, QUARANTINED, UNASSIGNED,
)
from sbb.event_matcher import match_event, team_name
from sbb.media_scope import annotate as annotate_media_scope, GAME, COLLECTION_SCOPES


class HistoryRepository:
    """Sports Big Board v4 normalized historical catalog.

    v4 has three independent truths:
      * `history_source_media`: a media asset exists once.
      * `history_event_media`: evidence that an asset belongs to a canonical game.
      * `history_collection_media`: evidence that an asset belongs to Silver.

    Event quality/coverage is derived from assigned GAME relationships. The old
    `history_day` JSON row remains a hydration/cache compatibility layer for score
    inventory and day-level discovery bookkeeping, never playback authority.
    """

    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @staticmethod
    def _dump(rows):
        return json.dumps(list(rows or []), ensure_ascii=False, separators=(",", ":"), default=str)

    @staticmethod
    def _dump_obj(value):
        return json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False, separators=(",", ":"), default=str)

    @staticmethod
    def _load(value):
        if not value: return []
        try:
            data = json.loads(value); return data if isinstance(data, list) else []
        except Exception: return []

    @staticmethod
    def _load_obj(value):
        if not value: return {}
        try:
            data = json.loads(value); return data if isinstance(data, dict) else {}
        except Exception: return {}

    def _init_db(self):
        now = time.time()
        try: fresh_catalog=(not os.path.exists(self.path)) or os.path.getsize(self.path)==0
        except OSError: fresh_catalog=True
        with self._lock, closing(self._connect()) as conn:
            # Compatibility day cache. Media JSON is retained only so pre-v4
            # database imports can be reconciled; normalized tables own playback.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history_day (
                    date TEXT NOT NULL, league TEXT NOT NULL,
                    scores_json TEXT, media_json TEXT, discovery_json TEXT,
                    scores_saved_at REAL NOT NULL DEFAULT 0,
                    media_saved_at REAL NOT NULL DEFAULT 0,
                    discovery_saved_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(date, league)
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_day_date ON history_day(date)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history_catalog_meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL DEFAULT 0
                )""")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history_catalog_event (
                    canonical_event_key TEXT PRIMARY KEY,
                    league TEXT NOT NULL, event_id TEXT NOT NULL, event_date TEXT NOT NULL,
                    event_json TEXT NOT NULL DEFAULT '{}', final_at REAL NOT NULL DEFAULT 0,
                    discovery_state TEXT NOT NULL DEFAULT 'UNKNOWN',
                    discovery_json TEXT NOT NULL DEFAULT '{}',
                    last_discovery_at REAL NOT NULL DEFAULT 0,
                    last_success_at REAL NOT NULL DEFAULT 0,
                    next_retry_at REAL NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    claim_owner TEXT NOT NULL DEFAULT '',
                    claim_started_at REAL NOT NULL DEFAULT 0,
                    claim_expires_at REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0,
                    UNIQUE(league, event_id)
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_event_date ON history_catalog_event(event_date,league)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_event_retry ON history_catalog_event(next_retry_at,last_discovery_at)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history_source_media (
                    asset_key TEXT PRIMARY KEY,
                    provider TEXT NOT NULL DEFAULT '', provider_media_id TEXT NOT NULL DEFAULT '',
                    canonical_url TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
                    duration_seconds REAL NOT NULL DEFAULT 0, published_at TEXT NOT NULL DEFAULT '',
                    channel_id TEXT NOT NULL DEFAULT '', channel_name TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT 'OTHER', intent TEXT NOT NULL DEFAULT 'OTHER',
                    scope_confidence REAL NOT NULL DEFAULT 0, scope_reason TEXT NOT NULL DEFAULT '',
                    intent_confidence REAL NOT NULL DEFAULT 0, intent_reason TEXT NOT NULL DEFAULT '',
                    classifier_version INTEGER NOT NULL DEFAULT 0,
                    catalog_state TEXT NOT NULL DEFAULT 'UNASSIGNED', quarantine_reason TEXT NOT NULL DEFAULT '',
                    validation_state TEXT NOT NULL DEFAULT 'CANDIDATE', verified_at REAL NOT NULL DEFAULT 0,
                    runtime_state TEXT NOT NULL DEFAULT 'UNKNOWN', runtime_success_at REAL NOT NULL DEFAULT 0,
                    runtime_failure_at REAL NOT NULL DEFAULT 0, runtime_failure_reason TEXT NOT NULL DEFAULT '',
                    asset_json TEXT NOT NULL DEFAULT '{}',
                    first_seen_at REAL NOT NULL DEFAULT 0, last_seen_at REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source_media_scope ON history_source_media(scope,intent)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source_media_state ON history_source_media(catalog_state,validation_state,runtime_state)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source_media_provider ON history_source_media(provider,provider_media_id)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history_event_media (
                    canonical_event_key TEXT NOT NULL,
                    asset_key TEXT NOT NULL,
                    association_state TEXT NOT NULL DEFAULT 'UNASSIGNED',
                    association_confidence REAL NOT NULL DEFAULT 0,
                    association_method TEXT NOT NULL DEFAULT '',
                    association_evidence TEXT NOT NULL DEFAULT '',
                    matcher_version INTEGER NOT NULL DEFAULT 0,
                    first_associated_at REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(canonical_event_key,asset_key),
                    FOREIGN KEY(canonical_event_key) REFERENCES history_catalog_event(canonical_event_key) ON DELETE CASCADE,
                    FOREIGN KEY(asset_key) REFERENCES history_source_media(asset_key) ON DELETE CASCADE
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_media_asset ON history_event_media(asset_key,association_state)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_media_event ON history_event_media(canonical_event_key,association_state)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history_collection (
                    collection_key TEXT PRIMARY KEY,
                    scope TEXT NOT NULL, league TEXT NOT NULL, period_key TEXT NOT NULL,
                    collection_kind TEXT NOT NULL DEFAULT 'ROUNDUP', title TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0,
                    UNIQUE(scope,league,period_key,collection_kind)
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_collection_period ON history_collection(period_key,league,scope)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history_collection_media (
                    collection_key TEXT NOT NULL, asset_key TEXT NOT NULL,
                    association_confidence REAL NOT NULL DEFAULT 0, association_method TEXT NOT NULL DEFAULT '',
                    association_evidence TEXT NOT NULL DEFAULT '', classifier_version INTEGER NOT NULL DEFAULT 0,
                    rank_hint INTEGER NOT NULL DEFAULT 0,
                    first_associated_at REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(collection_key,asset_key),
                    FOREIGN KEY(collection_key) REFERENCES history_collection(collection_key) ON DELETE CASCADE,
                    FOREIGN KEY(asset_key) REFERENCES history_source_media(asset_key) ON DELETE CASCADE
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_collection_media_asset ON history_collection_media(asset_key)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history_media_segment (
                    segment_key TEXT PRIMARY KEY, asset_key TEXT NOT NULL,
                    canonical_event_key TEXT, collection_key TEXT,
                    start_seconds REAL NOT NULL DEFAULT 0, end_seconds REAL NOT NULL DEFAULT 0,
                    title TEXT NOT NULL DEFAULT '', confidence REAL NOT NULL DEFAULT 0,
                    evidence TEXT NOT NULL DEFAULT '', extractor_version INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0,
                    FOREIGN KEY(asset_key) REFERENCES history_source_media(asset_key) ON DELETE CASCADE
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_segment_event ON history_media_segment(canonical_event_key)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history_media_verification (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, asset_key TEXT NOT NULL,
                    verification_type TEXT NOT NULL, state TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '', details_json TEXT NOT NULL DEFAULT '{}',
                    verified_at REAL NOT NULL DEFAULT 0, verification_version INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(asset_key) REFERENCES history_source_media(asset_key) ON DELETE CASCADE
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_verification_asset ON history_media_verification(asset_key,verified_at)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history_discovery_attempt (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_event_key TEXT NOT NULL, source TEXT NOT NULL DEFAULT '',
                    attempted_at REAL NOT NULL DEFAULT 0, discovery_version INTEGER NOT NULL DEFAULT 0,
                    query_type TEXT NOT NULL DEFAULT '', query_text TEXT NOT NULL DEFAULT '',
                    result_count INTEGER NOT NULL DEFAULT 0, accepted_count INTEGER NOT NULL DEFAULT 0,
                    best_before TEXT NOT NULL DEFAULT '', best_after TEXT NOT NULL DEFAULT '',
                    quota_cost REAL NOT NULL DEFAULT 0, failure_reason TEXT NOT NULL DEFAULT '',
                    details_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(canonical_event_key) REFERENCES history_catalog_event(canonical_event_key) ON DELETE CASCADE
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_discovery_attempt_event ON history_discovery_attempt(canonical_event_key,attempted_at)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history_assignment_review (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, asset_key TEXT NOT NULL,
                    league TEXT NOT NULL DEFAULT '', event_date TEXT NOT NULL DEFAULT '',
                    proposed_event_key TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '', evidence_json TEXT NOT NULL DEFAULT '{}',
                    classifier_version INTEGER NOT NULL DEFAULT 0, matcher_version INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0,
                    UNIQUE(asset_key, proposed_event_key, reason)
                )""")
            # v4 is a clean baseline, but development/pre-release databases may
            # have been initialized by an earlier v4 build. Additive guards keep
            # those files readable without ever treating v3 relationship tables as
            # authoritative or performing a destructive migration.
            def ensure_column(table, column, ddl):
                cols={str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")}
                if column not in cols: conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            ensure_column("history_catalog_event","final_at","REAL NOT NULL DEFAULT 0")
            ensure_column("history_catalog_event","claim_owner","TEXT NOT NULL DEFAULT ''")
            ensure_column("history_catalog_event","claim_started_at","REAL NOT NULL DEFAULT 0")
            ensure_column("history_catalog_event","claim_expires_at","REAL NOT NULL DEFAULT 0")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_event_claim ON history_catalog_event(claim_expires_at,claim_owner)")
            ensure_column("history_source_media","intent_confidence","REAL NOT NULL DEFAULT 0")
            ensure_column("history_source_media","intent_reason","TEXT NOT NULL DEFAULT ''")
            ensure_column("history_collection_media","association_confidence","REAL NOT NULL DEFAULT 0")
            ensure_column("history_collection_media","association_method","TEXT NOT NULL DEFAULT ''")
            ensure_column("history_collection_media","association_evidence","TEXT NOT NULL DEFAULT ''")
            ensure_column("history_collection_media","classifier_version","INTEGER NOT NULL DEFAULT 0")

            for key, value in {
                "catalog_schema_version": CATALOG_SCHEMA_VERSION,
                "media_classifier_version": MEDIA_CLASSIFIER_VERSION,
                "event_matcher_version": EVENT_MATCHER_VERSION,
                "ranking_version": RANKING_VERSION,
                "verification_version": VERIFICATION_VERSION,
            }.items():
                conn.execute("INSERT INTO history_catalog_meta(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(key,str(value),now))
            # A brand-new normalized catalog has no legacy relationships to
            # repair. Existing catalogs deliberately keep their historical repair
            # markers so future matcher/classifier upgrades can be detected.
            if fresh_catalog:
                conn.execute("INSERT INTO history_catalog_meta(key,value,updated_at) VALUES('event_association_repair_version',?,?) ON CONFLICT(key) DO NOTHING",(str(EVENT_MATCHER_VERSION),now))
                conn.execute("INSERT INTO history_catalog_meta(key,value,updated_at) VALUES('collection_association_repair_version',?,?) ON CONFLICT(key) DO NOTHING",(str(MEDIA_CLASSIFIER_VERSION),now))
            conn.commit()

    @staticmethod
    def event_id_for(item):
        if not isinstance(item, dict): return ""
        for key in ("scoreEventId","matchId","espnEventId","gamePk","canonicalEventId","eventId","id"):
            value=item.get(key)
            if value not in (None, ""): return str(value)
        return ""

    @staticmethod
    def canonical_event_key(league, event_id):
        return f"{str(league or '').upper()}:{str(event_id or '')}"

    @staticmethod
    def asset_key_for(item):
        """Return a provider-stable source-media identity.

        v4 intentionally does not use a game's event id as media identity. Direct
        media URLs and explicit provider media ids are preferred; generic ids are
        namespaced and title-fingerprinted so a provider game id cannot collapse
        several distinct clips into one source row.
        """
        if not isinstance(item, dict): return ""
        if item.get("assetKey"): return str(item.get("assetKey"))
        if item.get("youtubeId"): return "yt:"+str(item.get("youtubeId"))
        provider=str(item.get("provider") or item.get("sourceLabel") or item.get("source") or item.get("sourceType") or "source").lower()
        provider=re.sub(r"[^a-z0-9]+","-",provider).strip("-") or "source"
        for key in ("providerMediaId","videoId","assetId","contentId","clipId"):
            if item.get(key) not in (None,""):
                return f"{provider}:{key.lower()}:{item.get(key)}"
        direct=str(item.get("mediaUrl") or "").strip()
        if direct:
            digest=hashlib.sha256(direct.encode("utf-8")).hexdigest()[:32]
            return f"url:{digest}"
        generic=item.get("id")
        if generic not in (None,""):
            title=str(item.get("title") or "").strip().lower()
            suffix=hashlib.sha256(title.encode("utf-8")).hexdigest()[:12] if title else "untitled"
            return f"{provider}:id:{generic}:{suffix}"
        external=str(item.get("externalUrl") or "").strip()
        if external:
            material=external+"\n"+str(item.get("title") or "")
            return "ext:"+hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
        return ""

    @staticmethod
    def provider_media_id_for(item):
        if not isinstance(item,dict): return ""
        if item.get("youtubeId"): return str(item.get("youtubeId"))
        for key in ("providerMediaId","videoId","assetId","contentId","clipId"):
            if item.get(key) not in (None,""): return str(item.get(key))
        return str(item.get("id") or "")

    @staticmethod
    def validation_state_for(item):
        value=str((item or {}).get("validationState") or "").upper()
        if value in {"VERIFIED","CANDIDATE","EXTERNAL","FAILED"}: return value
        if (item or {}).get("verifiedPlayable") and ((item or {}).get("youtubeId") or (item or {}).get("mediaUrl")): return "VERIFIED"
        if (item or {}).get("externalOnly"): return "EXTERNAL"
        return "CANDIDATE"

    @staticmethod
    def _provider_for(item):
        return str((item or {}).get("provider") or (item or {}).get("sourceLabel") or (item or {}).get("source") or "").strip()

    @staticmethod
    def _canonical_url(item):
        item=item or {}
        if item.get("youtubeId"): return f"https://www.youtube.com/watch?v={item.get('youtubeId')}"
        return str(item.get("mediaUrl") or item.get("externalUrl") or "")

    def _upsert_source_media_conn(self, conn, raw, *, league="", date="", away="", home="", catalog_state=None, quarantine_reason=""):
        if not isinstance(raw,dict): return ""
        item=annotate_media_scope(dict(raw),league=league,date=date,away=away,home=home)
        asset_key=self.asset_key_for(item)
        if not asset_key: return ""
        now=time.time(); validation=self.validation_state_for(item)
        verified_at=float(item.get("historyVerifiedAt") or item.get("verifiedAt") or (now if validation=="VERIFIED" else 0) or 0)
        existing=conn.execute("SELECT * FROM history_source_media WHERE asset_key=?",(asset_key,)).fetchone()
        runtime="UNKNOWN"; success_at=failure_at=0.0; failure_reason=""; first_seen=now
        previous={}
        if existing:
            previous=self._load_obj(existing["asset_json"]); previous.update(item); item=previous
            runtime=str(existing["runtime_state"] or "UNKNOWN").upper(); success_at=float(existing["runtime_success_at"] or 0)
            failure_at=float(existing["runtime_failure_at"] or 0); failure_reason=str(existing["runtime_failure_reason"] or "")
            first_seen=float(existing["first_seen_at"] or now)
            if runtime=="FAILED" and verified_at>failure_at:
                runtime="UNKNOWN"; failure_at=0; failure_reason=""
            elif runtime=="FAILED":
                item["verifiedPlayable"]=False; item["runtimeState"]="failed"; item["runtimeFailureReason"]=failure_reason
        state=str(catalog_state or (existing["catalog_state"] if existing else "UNASSIGNED") or "UNASSIGNED").upper()
        if state not in {ASSIGNED,QUARANTINED,UNASSIGNED}: state=UNASSIGNED
        if state==ASSIGNED: quarantine_reason=""
        item["assetKey"]=asset_key; item["validationState"]=validation
        conn.execute("""
            INSERT INTO history_source_media(asset_key,provider,provider_media_id,canonical_url,title,duration_seconds,published_at,channel_id,channel_name,
              scope,intent,scope_confidence,scope_reason,intent_confidence,intent_reason,classifier_version,catalog_state,quarantine_reason,validation_state,verified_at,runtime_state,
              runtime_success_at,runtime_failure_at,runtime_failure_reason,asset_json,first_seen_at,last_seen_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(asset_key) DO UPDATE SET
              provider=CASE WHEN excluded.provider<>'' THEN excluded.provider ELSE history_source_media.provider END,
              provider_media_id=CASE WHEN excluded.provider_media_id<>'' THEN excluded.provider_media_id ELSE history_source_media.provider_media_id END,
              canonical_url=CASE WHEN excluded.canonical_url<>'' THEN excluded.canonical_url ELSE history_source_media.canonical_url END,
              title=CASE WHEN excluded.title<>'' THEN excluded.title ELSE history_source_media.title END,
              duration_seconds=MAX(history_source_media.duration_seconds,excluded.duration_seconds),
              published_at=CASE WHEN excluded.published_at<>'' THEN excluded.published_at ELSE history_source_media.published_at END,
              channel_id=CASE WHEN excluded.channel_id<>'' THEN excluded.channel_id ELSE history_source_media.channel_id END,
              channel_name=CASE WHEN excluded.channel_name<>'' THEN excluded.channel_name ELSE history_source_media.channel_name END,
              scope=excluded.scope,intent=excluded.intent,scope_confidence=excluded.scope_confidence,scope_reason=excluded.scope_reason,intent_confidence=excluded.intent_confidence,intent_reason=excluded.intent_reason,classifier_version=excluded.classifier_version,
              catalog_state=CASE WHEN excluded.catalog_state='ASSIGNED' THEN 'ASSIGNED' WHEN history_source_media.catalog_state='ASSIGNED' THEN 'ASSIGNED' ELSE excluded.catalog_state END,
              quarantine_reason=CASE WHEN excluded.catalog_state='ASSIGNED' THEN '' ELSE excluded.quarantine_reason END,
              validation_state=CASE WHEN excluded.validation_state='VERIFIED' THEN 'VERIFIED' WHEN history_source_media.validation_state='VERIFIED' THEN 'VERIFIED' ELSE excluded.validation_state END,
              verified_at=MAX(history_source_media.verified_at,excluded.verified_at),runtime_state=excluded.runtime_state,
              runtime_success_at=excluded.runtime_success_at,runtime_failure_at=excluded.runtime_failure_at,runtime_failure_reason=excluded.runtime_failure_reason,
              asset_json=excluded.asset_json,last_seen_at=excluded.last_seen_at,updated_at=excluded.updated_at
        """,(
            asset_key,self._provider_for(item),self.provider_media_id_for(item),self._canonical_url(item),str(item.get("title") or ""),
            float(item.get("durationSeconds") or item.get("duration") or 0),str(item.get("publishedAt") or item.get("published") or ""),
            str(item.get("channelId") or ""),str(item.get("channelName") or item.get("channelTitle") or ""),str(item.get("mediaScope") or "OTHER"),
            str(item.get("mediaIntent") or "OTHER"),float(item.get("mediaScopeConfidence") or 0),str(item.get("mediaScopeReason") or ""),
            float(item.get("mediaIntentConfidence") or 0),str(item.get("mediaIntentReason") or ""),int(item.get("mediaClassifierVersion") or MEDIA_CLASSIFIER_VERSION),state,str(quarantine_reason or "")[:1000],validation,verified_at,runtime,
            success_at,failure_at,failure_reason,self._dump_obj(item),first_seen,now,now))
        return asset_key

    def put_source_media(self, rows, *, league="", date="", away="", home="", catalog_state=None):
        count=0
        with self._lock, closing(self._connect()) as conn:
            for row in rows or []:
                if self._upsert_source_media_conn(conn,row,league=str(league).upper(),date=str(date)[:10],away=away,home=home,catalog_state=catalog_state): count+=1
            conn.commit()
        return count

    def put_scores(self, date, league, rows):
        now=time.time(); date=str(date)[:10]; league=str(league).upper(); rows=list(rows or [])
        with self._lock, closing(self._connect()) as conn:
            conn.execute("INSERT INTO history_day(date,league,scores_json,scores_saved_at) VALUES(?,?,?,?) ON CONFLICT(date,league) DO UPDATE SET scores_json=excluded.scores_json,scores_saved_at=excluded.scores_saved_at",(date,league,self._dump(rows),now))
            for event in rows:
                event_id=self.event_id_for(event)
                if not event_id: continue
                key=self.canonical_event_key(league,event_id)
                final_at=self._event_final_at(event)
                conn.execute("""
                    INSERT INTO history_catalog_event(canonical_event_key,league,event_id,event_date,event_json,final_at,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(canonical_event_key) DO UPDATE SET
                      event_date=excluded.event_date,event_json=CASE WHEN excluded.event_json<>'{}' THEN excluded.event_json ELSE history_catalog_event.event_json END,
                      final_at=CASE WHEN excluded.final_at>0 THEN excluded.final_at ELSE history_catalog_event.final_at END,updated_at=excluded.updated_at
                """,(key,league,event_id,date,self._dump_obj(event),final_at,now,now))
            conn.commit()
        return now

    @staticmethod
    def _event_final_at(event):
        event=event if isinstance(event,dict) else {}
        candidates=[]
        for key in ("finalAt","completedAt","endedAt","endTime","statusTimestamp"):
            if event.get(key) not in (None,""): candidates.append(event.get(key))
        status=event.get("status") if isinstance(event.get("status"),dict) else {}
        for key in ("finalAt","completedAt","endedAt","timestamp"):
            if status.get(key) not in (None,""): candidates.append(status.get(key))
        for value in candidates:
            try:
                num=float(value)
                if num>10_000_000_000: num/=1000.0
                if num>0: return num
            except Exception: pass
            try:
                from datetime import datetime
                text=str(value).replace("Z","+00:00")
                return float(datetime.fromisoformat(text).timestamp())
            except Exception: pass
        return 0.0

    def upsert_event(self, date, league, event_id, event=None):
        date=str(date)[:10]; league=str(league).upper(); event_id=str(event_id or "")
        if not event_id: return 0
        now=time.time(); key=self.canonical_event_key(league,event_id)
        with self._lock, closing(self._connect()) as conn:
            final_at=self._event_final_at(event)
            conn.execute("""INSERT INTO history_catalog_event(canonical_event_key,league,event_id,event_date,event_json,final_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)
              ON CONFLICT(canonical_event_key) DO UPDATE SET event_date=excluded.event_date,event_json=CASE WHEN excluded.event_json<>'{}' THEN excluded.event_json ELSE history_catalog_event.event_json END,
              final_at=CASE WHEN excluded.final_at>0 THEN excluded.final_at ELSE history_catalog_event.final_at END,updated_at=excluded.updated_at""",
              (key,league,event_id,date,self._dump_obj(event),final_at,now,now)); conn.commit()
        return now

    def set_event_discovery(self, date, league, event_id, state, details=None, *, error="", retry_at=0, success=False):
        self.upsert_event(date,league,event_id)
        now=time.time(); key=self.canonical_event_key(league,event_id); state=str(state or "UNKNOWN").upper(); details=dict(details or {})
        with self._lock, closing(self._connect()) as conn:
            conn.execute("""UPDATE history_catalog_event SET discovery_state=?,discovery_json=?,last_discovery_at=?,last_success_at=CASE WHEN ?>0 THEN ? ELSE last_success_at END,
              next_retry_at=?,last_error=?,updated_at=? WHERE canonical_event_key=?""",
              (state,self._dump_obj(details),now,1 if success else 0,now,float(retry_at or 0),str(error or "")[:1000],now,key)); conn.commit()
        return now

    def reset_event_for_reindex(self, date, league, event_id, details=None, *, state="UNKNOWN"):
        """Reset catalog indexing state without recording a discovery attempt.

        Catalog reconstruction/import is bookkeeping, not provider discovery.  A
        migrated event must therefore begin with no discovery timestamp and no
        retry hold.  ``rebuildImportedAt``/other provenance belongs in ``details``
        instead of overloading ``last_discovery_at``.
        """
        self.upsert_event(date,league,event_id)
        now=time.time(); key=self.canonical_event_key(league,event_id); state=str(state or "UNKNOWN").upper(); details=dict(details or {})
        with self._lock, closing(self._connect()) as conn:
            conn.execute("""UPDATE history_catalog_event SET discovery_state=?,discovery_json=?,last_discovery_at=0,next_retry_at=0,last_error='',updated_at=?
              WHERE canonical_event_key=?""",(state,self._dump_obj(details),now,key)); conn.commit()
        return now

    def release_rebuild_pending_events(self, current_discovery_version):
        """Release artificial v4.1.4 migration cooldowns already persisted in production.

        This is intentionally narrow and idempotent: only events explicitly marked
        ``PENDING_CURRENT_DISCOVERY`` and still older than the current discovery
        generation are touched. Real current-version search timestamps are never
        changed.
        """
        current=max(0,int(current_discovery_version or 0))
        if not current: return 0
        now=time.time()
        with self._lock, closing(self._connect()) as conn:
            cur=conn.execute("""UPDATE history_catalog_event SET last_discovery_at=0,next_retry_at=0,last_error='',updated_at=?
              WHERE COALESCE(CAST(json_extract(discovery_json,'$.discoveryVersion') AS INTEGER),0)<?
                AND COALESCE(json_extract(discovery_json,'$.rebuildState'),'')='PENDING_CURRENT_DISCOVERY'
                AND (last_discovery_at>0 OR next_retry_at>0)""",(now,current))
            count=int(cur.rowcount or 0); conn.commit()
        return count

    def catalog_meta(self, key, default=""):
        with self._lock, closing(self._connect()) as conn:
            row=conn.execute("SELECT value FROM history_catalog_meta WHERE key=?",(str(key),)).fetchone()
        return str(row[0]) if row else str(default)

    def set_catalog_meta(self, key, value):
        now=time.time()
        with self._lock, closing(self._connect()) as conn:
            conn.execute("INSERT INTO history_catalog_meta(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(str(key),str(value),now)); conn.commit()
        return value

    def get_event(self, date, league, event_id):
        league=str(league).upper(); event_id=str(event_id); key=self.canonical_event_key(league,event_id)
        with self._lock, closing(self._connect()) as conn:
            row=conn.execute("SELECT * FROM history_catalog_event WHERE canonical_event_key=?",(key,)).fetchone()
        if not row: return None
        return {"date":row["event_date"],"league":row["league"],"eventId":row["event_id"],"canonicalEventKey":row["canonical_event_key"],"event":self._load_obj(row["event_json"]),
            "discoveryState":row["discovery_state"],"discovery":self._load_obj(row["discovery_json"]),"lastDiscoveryAt":float(row["last_discovery_at"] or 0),
            "finalAt":float(row["final_at"] or 0),"lastSuccessAt":float(row["last_success_at"] or 0),"nextRetryAt":float(row["next_retry_at"] or 0),"lastError":row["last_error"] or "","updatedAt":float(row["updated_at"] or 0)}

    def put_event_media(self, date, league, event_id, rows):
        date=str(date)[:10]; league=str(league).upper(); event_id=str(event_id or "")
        if not event_id: return 0
        self.upsert_event(date,league,event_id)
        key=self.canonical_event_key(league,event_id); now=time.time(); count=0
        with self._lock, closing(self._connect()) as conn:
            erow=conn.execute("SELECT event_json,event_date FROM history_catalog_event WHERE canonical_event_key=?",(key,)).fetchone()
            event=self._load_obj(erow["event_json"]) if erow else {}; event_date=str(erow["event_date"] if erow else date)[:10]
            away,home=team_name(event,"away"),team_name(event,"home")
            for raw in rows or []:
                if not isinstance(raw,dict): continue
                item=annotate_media_scope(dict(raw),league=league,date=event_date,away=away,home=home)
                evidence=match_event(item,event,league=league,date=event_date)
                state=str(evidence.get("associationState") or QUARANTINED)
                reason="" if state==ASSIGNED else str(evidence.get("associationMethod") or "UNPROVEN_GAME_ASSOCIATION")
                asset_key=self._upsert_source_media_conn(conn,item,league=league,date=event_date,away=away,home=home,catalog_state=(ASSIGNED if state==ASSIGNED else QUARANTINED),quarantine_reason=reason)
                if not asset_key: continue
                if state==ASSIGNED:
                    competing=[str(r[0]) for r in conn.execute("SELECT canonical_event_key FROM history_event_media WHERE asset_key=? AND association_state='ASSIGNED' AND canonical_event_key<>?",(asset_key,key)).fetchall()]
                    if competing:
                        # One GAME source asset may never be authoritative for two games.
                        # Fail closed rather than letting arrival order choose a winner.
                        state=QUARANTINED; reason="CROSS_EVENT_ASSET_CONFLICT"
                        evidence=dict(evidence); evidence.update(associationState=QUARANTINED,associationConfidence=0.0,associationMethod=reason,associationEvidence=f"already assigned to {competing}")
                        conn.execute("UPDATE history_event_media SET association_state='QUARANTINED',association_confidence=0,association_method=?,association_evidence=?,matcher_version=?,updated_at=? WHERE asset_key=? AND association_state='ASSIGNED'",(reason,f"competing event {key}",EVENT_MATCHER_VERSION,now,asset_key))
                        conn.execute("UPDATE history_source_media SET catalog_state='QUARANTINED',quarantine_reason=? WHERE asset_key=?",(reason,asset_key))
                    else:
                        item["canonicalEventKey"]=key
                        conn.execute("UPDATE history_source_media SET catalog_state='ASSIGNED',quarantine_reason='',asset_json=? WHERE asset_key=?",(self._dump_obj(item),asset_key))
                        count+=1
                if state!=ASSIGNED:
                    conn.execute("INSERT INTO history_assignment_review(asset_key,league,event_date,proposed_event_key,state,reason,evidence_json,classifier_version,matcher_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_key,proposed_event_key,reason) DO UPDATE SET state=excluded.state,evidence_json=excluded.evidence_json,updated_at=excluded.updated_at",
                        (asset_key,league,event_date,key,state,reason,self._dump_obj(evidence),MEDIA_CLASSIFIER_VERSION,EVENT_MATCHER_VERSION,now,now))
                conn.execute("""INSERT INTO history_event_media(canonical_event_key,asset_key,association_state,association_confidence,association_method,association_evidence,matcher_version,first_associated_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(canonical_event_key,asset_key) DO UPDATE SET association_state=excluded.association_state,association_confidence=excluded.association_confidence,
                  association_method=excluded.association_method,association_evidence=excluded.association_evidence,matcher_version=excluded.matcher_version,updated_at=excluded.updated_at""",
                  (key,asset_key,state,float(evidence.get("associationConfidence") or 0),str(evidence.get("associationMethod") or ""),str(evidence.get("associationEvidence") or "")[:2000],int(evidence.get("matcherVersion") or EVENT_MATCHER_VERSION),now,now))
            conn.commit()
        return count

    def repair_event_associations(self, matcher_version=EVENT_MATCHER_VERSION, force=False):
        """Re-prove every GAME relationship under the current fail-closed matcher.

        Source assets are preserved. Bad/ambiguous links are quarantined and can
        be reconsidered by a future matcher without reacquiring media.
        """
        target=int(matcher_version or EVENT_MATCHER_VERSION)
        marker=int(self.catalog_meta("event_association_repair_version","0") or 0)
        if marker>=target and not force:
            return {"skipped":True,"matcherVersion":target,**self.association_integrity_summary()}
        now=time.time(); checked=kept=quarantined=0; reasons={}
        with self._lock, closing(self._connect()) as conn:
            # Scope leakage is repairable relationship state, never a reason to
            # reconstruct the normalized catalog. Quarantine any collection/non-
            # GAME asset that was historically attached to an event.
            leaks=conn.execute("""SELECT em.canonical_event_key,em.asset_key,e.league,e.event_date
              FROM history_event_media em JOIN history_catalog_event e ON e.canonical_event_key=em.canonical_event_key
              JOIN history_source_media s ON s.asset_key=em.asset_key
              WHERE em.association_state='ASSIGNED' AND s.scope<>'GAME'""").fetchall()
            for leak in leaks:
                checked+=1; quarantined+=1; reason='NON_GAME_SCOPE_EVENT_LINK'; reasons[reason]=reasons.get(reason,0)+1
                conn.execute("UPDATE history_event_media SET association_state='QUARANTINED',association_confidence=0,association_method=?,association_evidence='source scope is not GAME',matcher_version=?,updated_at=? WHERE canonical_event_key=? AND asset_key=?",(reason,target,now,leak["canonical_event_key"],leak["asset_key"]))
                conn.execute("INSERT INTO history_assignment_review(asset_key,league,event_date,proposed_event_key,state,reason,evidence_json,classifier_version,matcher_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_key,proposed_event_key,reason) DO UPDATE SET state=excluded.state,matcher_version=excluded.matcher_version,updated_at=excluded.updated_at",(leak["asset_key"],leak["league"],leak["event_date"],leak["canonical_event_key"],QUARANTINED,reason,'{}',MEDIA_CLASSIFIER_VERSION,target,now,now))
            rows=conn.execute("""SELECT em.canonical_event_key,em.asset_key,e.league,e.event_date,e.event_json,s.asset_json,s.scope
              FROM history_event_media em JOIN history_catalog_event e ON e.canonical_event_key=em.canonical_event_key
              JOIN history_source_media s ON s.asset_key=em.asset_key WHERE s.scope='GAME'""").fetchall()
            for row in rows:
                checked+=1; event=self._load_obj(row["event_json"]); item=self._load_obj(row["asset_json"])
                away,home=team_name(event,"away"),team_name(event,"home")
                item=annotate_media_scope(item,league=row["league"],date=row["event_date"],away=away,home=home)
                ev=match_event(item,event,league=row["league"],date=row["event_date"]); state=str(ev.get("associationState") or QUARANTINED)
                method=str(ev.get("associationMethod") or "UNPROVEN_GAME_ASSOCIATION"); reasons[method]=reasons.get(method,0)+1
                if state==ASSIGNED: kept+=1
                else:
                    quarantined+=1
                    conn.execute("INSERT INTO history_assignment_review(asset_key,league,event_date,proposed_event_key,state,reason,evidence_json,classifier_version,matcher_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_key,proposed_event_key,reason) DO UPDATE SET state=excluded.state,evidence_json=excluded.evidence_json,matcher_version=excluded.matcher_version,updated_at=excluded.updated_at",(row["asset_key"],row["league"],row["event_date"],row["canonical_event_key"],QUARANTINED,method,self._dump_obj(ev),MEDIA_CLASSIFIER_VERSION,target,now,now))
                conn.execute("UPDATE history_event_media SET association_state=?,association_confidence=?,association_method=?,association_evidence=?,matcher_version=?,updated_at=? WHERE canonical_event_key=? AND asset_key=?",(state,float(ev.get("associationConfidence") or 0),method,str(ev.get("associationEvidence") or "")[:2000],target,now,row["canonical_event_key"],row["asset_key"]))
            # Enforce global one-asset/one-game invariant after revalidation.
            conflicts=conn.execute("SELECT asset_key,COUNT(DISTINCT canonical_event_key) n FROM history_event_media WHERE association_state='ASSIGNED' GROUP BY asset_key HAVING n>1").fetchall()
            conflict_assets=0
            for c in conflicts:
                conflict_assets+=1; asset=str(c["asset_key"]); quarantined_links=conn.execute("SELECT COUNT(*) FROM history_event_media WHERE asset_key=? AND association_state='ASSIGNED'",(asset,)).fetchone()[0]
                quarantined+=int(quarantined_links or 0); kept-=int(quarantined_links or 0)
                conn.execute("UPDATE history_event_media SET association_state='QUARANTINED',association_confidence=0,association_method='CROSS_EVENT_ASSET_CONFLICT',association_evidence='multiple canonical games survived revalidation',matcher_version=?,updated_at=? WHERE asset_key=? AND association_state='ASSIGNED'",(target,now,asset))
                conn.execute("UPDATE history_source_media SET catalog_state='QUARANTINED',quarantine_reason='CROSS_EVENT_ASSET_CONFLICT',updated_at=? WHERE asset_key=?",(now,asset))
            # Recompute source state from surviving relationships/collections.
            conn.execute("""UPDATE history_source_media SET catalog_state=CASE
                WHEN EXISTS(SELECT 1 FROM history_event_media em WHERE em.asset_key=history_source_media.asset_key AND em.association_state='ASSIGNED') THEN 'ASSIGNED'
                WHEN EXISTS(SELECT 1 FROM history_collection_media cm WHERE cm.asset_key=history_source_media.asset_key) THEN 'ASSIGNED'
                WHEN EXISTS(SELECT 1 FROM history_event_media em WHERE em.asset_key=history_source_media.asset_key AND em.association_state='QUARANTINED') THEN 'QUARANTINED'
                ELSE 'UNASSIGNED' END,
                quarantine_reason=CASE WHEN EXISTS(SELECT 1 FROM history_event_media em WHERE em.asset_key=history_source_media.asset_key AND em.association_state='ASSIGNED') THEN '' ELSE quarantine_reason END,updated_at=?""",(now,))
            conn.execute("INSERT INTO history_catalog_meta(key,value,updated_at) VALUES('event_association_repair_version',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(str(target),now)); conn.commit()
        return {"skipped":False,"matcherVersion":target,"checkedLinks":checked,"keptLinks":max(0,kept),"quarantinedLinks":quarantined,"reasons":reasons,**self.association_integrity_summary()}

    def repair_collection_associations(self, classifier_version=MEDIA_CLASSIFIER_VERSION, force=False):
        """Repair Silver collection relationships without touching discovery state.

        Collection links are derived/routing state. A classifier upgrade may
        remove a stale link, but it must never rebuild the database or mutate
        event discovery/backfill/verification history.
        """
        target=int(classifier_version or MEDIA_CLASSIFIER_VERSION)
        marker=int(self.catalog_meta("collection_association_repair_version","0") or 0)
        integrity=self.catalog_integrity()
        has_active_issues=bool(int(integrity.get("collectionGameLeaks") or 0) or int(integrity.get("lowConfidenceCollectionLinks") or 0))
        if marker>=target and not force and not has_active_issues:
            return {"skipped":True,"classifierVersion":target,"checkedLinks":0,"removedLinks":0,"reasons":{}}
        now=time.time(); checked=removed=0; reasons={}
        with self._lock, closing(self._connect()) as conn:
            rows=conn.execute("""SELECT cm.collection_key,cm.asset_key,cm.association_confidence,c.scope,c.league,c.period_key,s.scope AS media_scope
              FROM history_collection_media cm JOIN history_collection c ON c.collection_key=cm.collection_key
              JOIN history_source_media s ON s.asset_key=cm.asset_key""").fetchall()
            for row in rows:
                checked+=1; reason=''
                media_scope=str(row["media_scope"] or "").upper(); collection_scope=str(row["scope"] or "").upper()
                if media_scope=='GAME': reason='GAME_SCOPE_COLLECTION_LINK'
                elif media_scope not in COLLECTION_SCOPES: reason='NON_COLLECTION_SCOPE_LINK'
                elif media_scope!=collection_scope: reason='COLLECTION_SCOPE_MISMATCH'
                elif float(row["association_confidence"] or 0)<0.80: reason='COLLECTION_LOW_CONFIDENCE'
                if not reason: continue
                removed+=1; reasons[reason]=reasons.get(reason,0)+1
                conn.execute("DELETE FROM history_collection_media WHERE collection_key=? AND asset_key=?",(row["collection_key"],row["asset_key"]))
                review_key='COLLECTION:'+str(row["collection_key"])
                conn.execute("INSERT INTO history_assignment_review(asset_key,league,event_date,proposed_event_key,state,reason,evidence_json,classifier_version,matcher_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_key,proposed_event_key,reason) DO UPDATE SET state=excluded.state,classifier_version=excluded.classifier_version,updated_at=excluded.updated_at",(row["asset_key"],row["league"],str(row["period_key"] or '')[:10],review_key,QUARANTINED,reason,'{}',target,EVENT_MATCHER_VERSION,now,now))
            conn.execute("""UPDATE history_source_media SET catalog_state=CASE
                WHEN EXISTS(SELECT 1 FROM history_event_media em WHERE em.asset_key=history_source_media.asset_key AND em.association_state='ASSIGNED') THEN 'ASSIGNED'
                WHEN EXISTS(SELECT 1 FROM history_collection_media cm WHERE cm.asset_key=history_source_media.asset_key) THEN 'ASSIGNED'
                WHEN EXISTS(SELECT 1 FROM history_event_media em WHERE em.asset_key=history_source_media.asset_key AND em.association_state='QUARANTINED') THEN 'QUARANTINED'
                ELSE 'UNASSIGNED' END,updated_at=?""",(now,))
            conn.execute("INSERT INTO history_catalog_meta(key,value,updated_at) VALUES('collection_association_repair_version',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(str(target),now))
            conn.commit()
        return {"skipped":False,"classifierVersion":target,"checkedLinks":checked,"removedLinks":removed,"reasons":reasons}

    def repair_relationships(self, force=False):
        event=self.repair_event_associations(force=force)
        collection=self.repair_collection_associations(force=force)
        integrity=self.catalog_integrity()
        relationship_keys=("silverGameLeaks","collectionGameLeaks","lowConfidenceAssigned","crossEventAssignedAssets","lowConfidenceCollectionLinks")
        issues={k:int(integrity.get(k) or 0) for k in relationship_keys if int(integrity.get(k) or 0)>0}
        return {"event":event,"collection":collection,"integrity":integrity,"issues":issues,"ok":not bool(issues)}

    def association_integrity_summary(self):
        with self._lock, closing(self._connect()) as conn:
            assigned=int(conn.execute("SELECT COUNT(*) FROM history_event_media WHERE association_state='ASSIGNED'").fetchone()[0] or 0)
            quarantined=int(conn.execute("SELECT COUNT(*) FROM history_event_media WHERE association_state='QUARANTINED'").fetchone()[0] or 0)
            cross=int(conn.execute("SELECT COUNT(*) FROM (SELECT asset_key FROM history_event_media WHERE association_state='ASSIGNED' GROUP BY asset_key HAVING COUNT(DISTINCT canonical_event_key)>1)").fetchone()[0] or 0)
            counts={r[0]:int(r[1] or 0) for r in conn.execute("SELECT association_method,COUNT(*) FROM history_event_media WHERE association_state='QUARANTINED' GROUP BY association_method").fetchall()}
        quarantine_reasons={k:v for k,v in sorted(counts.items(),key=lambda kv:(-int(kv[1]),str(kv[0]))) if k}
        return {"assignedLinks":assigned,"quarantinedLinks":quarantined,"crossEventAssets":cross,"teamMismatch":counts.get('TITLE_TEAM_PAIR_CONFLICT',0)+counts.get('TEAM_FIELD_CONFLICT',0),"dateMismatch":counts.get('DATE_MISMATCH',0),"seasonMismatch":counts.get('SEASON_MISMATCH',0),"crossEventQuarantined":counts.get('CROSS_EVENT_ASSET_CONFLICT',0),"quarantineReasons":quarantine_reasons}

    @staticmethod
    def _hydrate_asset(row):
        item=HistoryRepository._load_obj(row["asset_json"]); item["assetKey"]=row["asset_key"]
        item["mediaScope"]=row["scope"]; item["mediaIntent"]=row["intent"]; item["mediaScopeConfidence"]=float(row["scope_confidence"] or 0)
        item["mediaScopeReason"]=row["scope_reason"]; item["mediaIntentConfidence"]=float(row["intent_confidence"] or 0); item["mediaIntentReason"]=row["intent_reason"]; item["mediaClassifierVersion"]=int(row["classifier_version"] or 0)
        item["validationState"]=row["validation_state"]; item["historyVerifiedAt"]=float(row["verified_at"] or 0); runtime=str(row["runtime_state"] or "UNKNOWN").upper()
        item["runtimeCatalogState"]=runtime
        if runtime=="FAILED": item["runtimeState"]="failed"; item["verifiedPlayable"]=False; item["runtimeFailureReason"]=row["runtime_failure_reason"] or ""
        elif runtime=="PLAYED": item["runtimeState"]="playing-confirmed"; item["verifiedPlayable"]=True
        return item

    def event_media(self, date, league, event_id, include_failed=True):
        key=self.canonical_event_key(league,event_id)
        with self._lock, closing(self._connect()) as conn:
            rows=conn.execute("""SELECT s.*,em.association_confidence,em.association_method,em.association_evidence,em.matcher_version
              FROM history_event_media em JOIN history_source_media s ON s.asset_key=em.asset_key
              WHERE em.canonical_event_key=? AND em.association_state='ASSIGNED' AND s.scope='GAME'
              ORDER BY s.verified_at DESC,s.updated_at DESC""",(key,)).fetchall()
        out=[]
        for row in rows:
            item=self._hydrate_asset(row)
            if str(row["runtime_state"] or "").upper()=="FAILED" and not include_failed: continue
            item["associationConfidence"]=float(row["association_confidence"] or 0); item["associationMethod"]=row["association_method"]
            item["associationEvidence"]=row["association_evidence"]; item["eventMatcherVersion"]=int(row["matcher_version"] or 0); item["canonicalEventKey"]=key
            out.append(item)
        return out

    def record_runtime(self, date, league, event_id, asset_key, *, success=False, reason=""):
        asset_key=str(asset_key or ""); key=self.canonical_event_key(league,event_id)
        if not asset_key: return False
        now=time.time(); state="PLAYED" if success else "FAILED"
        with self._lock, closing(self._connect()) as conn:
            linked=conn.execute("SELECT 1 FROM history_event_media WHERE canonical_event_key=? AND asset_key=? AND association_state='ASSIGNED'",(key,asset_key)).fetchone()
            if not linked: return False
            row=conn.execute("SELECT asset_json FROM history_source_media WHERE asset_key=?",(asset_key,)).fetchone()
            if not row: return False
            item=self._load_obj(row["asset_json"])
            if success: item["runtimeState"]="playing-confirmed"; item["verifiedPlayable"]=True
            else: item["runtimeState"]="failed"; item["verifiedPlayable"]=False; item["runtimeFailureReason"]=str(reason or "")[:500]
            conn.execute("""UPDATE history_source_media SET asset_json=?,runtime_state=?,runtime_success_at=CASE WHEN ? THEN ? ELSE runtime_success_at END,
              runtime_failure_at=CASE WHEN ? THEN runtime_failure_at ELSE ? END,runtime_failure_reason=CASE WHEN ? THEN '' ELSE ? END,updated_at=? WHERE asset_key=?""",
              (self._dump_obj(item),state,1 if success else 0,now,1 if success else 0,now,1 if success else 0,str(reason or "")[:500],now,asset_key))
            conn.execute("INSERT INTO history_media_verification(asset_key,verification_type,state,reason,details_json,verified_at,verification_version) VALUES(?,?,?,?,?,?,?)",
              (asset_key,"RUNTIME",state,str(reason or "")[:1000],"{}",now,VERIFICATION_VERSION)); conn.commit()
        return True

    def record_verification(self, asset_key, verification_type, state, *, reason="", details=None, verified_at=None):
        now=float(verified_at or time.time())
        with self._lock, closing(self._connect()) as conn:
            if not conn.execute("SELECT 1 FROM history_source_media WHERE asset_key=?",(asset_key,)).fetchone(): return False
            conn.execute("INSERT INTO history_media_verification(asset_key,verification_type,state,reason,details_json,verified_at,verification_version) VALUES(?,?,?,?,?,?,?)",
              (asset_key,str(verification_type or "UNKNOWN"),str(state or "UNKNOWN"),str(reason or "")[:1000],self._dump_obj(details),now,VERIFICATION_VERSION)); conn.commit()
        return True

    def record_discovery_attempt(self, league, event_id, *, source="", discovery_version=0, query_type="", query_text="", result_count=0, accepted_count=0,
                                 best_before="", best_after="", quota_cost=0, failure_reason="", details=None, attempted_at=None):
        key=self.canonical_event_key(league,event_id); now=float(attempted_at or time.time())
        with self._lock, closing(self._connect()) as conn:
            if not conn.execute("SELECT 1 FROM history_catalog_event WHERE canonical_event_key=?",(key,)).fetchone(): return False
            conn.execute("""INSERT INTO history_discovery_attempt(canonical_event_key,source,attempted_at,discovery_version,query_type,query_text,result_count,accepted_count,best_before,best_after,quota_cost,failure_reason,details_json)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(key,str(source or ""),now,int(discovery_version or 0),str(query_type or ""),str(query_text or "")[:2000],int(result_count or 0),int(accepted_count or 0),str(best_before or ""),str(best_after or ""),float(quota_cost or 0),str(failure_reason or "")[:1000],self._dump_obj(details))); conn.commit()
        return True

    def add_segment(self, asset_key, *, segment_key="", league="", event_id="", collection_key="", start_seconds=0, end_seconds=0, title="", confidence=0, evidence="", extractor_version=1):
        if not segment_key:
            suffix=f"{league}:{event_id}" if event_id else str(collection_key or "segment")
            segment_key=f"{asset_key}:{suffix}:{float(start_seconds or 0):.3f}"
        event_key=self.canonical_event_key(league,event_id) if league and event_id else None; now=time.time()
        with self._lock, closing(self._connect()) as conn:
            if not conn.execute("SELECT 1 FROM history_source_media WHERE asset_key=?",(asset_key,)).fetchone(): return ""
            conn.execute("""INSERT INTO history_media_segment(segment_key,asset_key,canonical_event_key,collection_key,start_seconds,end_seconds,title,confidence,evidence,extractor_version,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(segment_key) DO UPDATE SET start_seconds=excluded.start_seconds,end_seconds=excluded.end_seconds,title=excluded.title,confidence=excluded.confidence,evidence=excluded.evidence,extractor_version=excluded.extractor_version,updated_at=excluded.updated_at""",
              (segment_key,asset_key,event_key,collection_key or None,float(start_seconds or 0),float(end_seconds or 0),str(title or ""),float(confidence or 0),str(evidence or "")[:2000],int(extractor_version or 1),now,now)); conn.commit()
        return segment_key

    @staticmethod
    def _collection_key(scope,league,period_key,kind):
        return f"{str(scope).upper()}:{str(league).upper()}:{str(period_key)}:{str(kind).upper()}"

    def put_collection_media(self, scope, league, period_key, rows, *, collection_kind="ROUNDUP"):
        scope=str(scope or "").upper(); league=str(league or "").upper(); period_key=str(period_key or ""); kind=str(collection_kind or "ROUNDUP").upper()
        if scope not in COLLECTION_SCOPES or not period_key: return 0
        ckey=self._collection_key(scope,league,period_key,kind); now=time.time(); count=0
        with self._lock, closing(self._connect()) as conn:
            conn.execute("""INSERT INTO history_collection(collection_key,scope,league,period_key,collection_kind,title,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)
              ON CONFLICT(collection_key) DO UPDATE SET updated_at=excluded.updated_at""",(ckey,scope,league,period_key,kind,f"{league} {period_key} {kind.replace('_',' ').title()}","{}",now,now))
            for raw in rows or []:
                if not isinstance(raw,dict): continue
                item=annotate_media_scope(dict(raw),league=league,date=str(raw.get("date") or period_key)[:10])
                if item.get("mediaScope") not in COLLECTION_SCOPES:
                    # The caller explicitly routed this into a collection. Keep the
                    # classifier decision visible but never turn it into GAME truth.
                    item["mediaScope"]=scope; item["mediaScopeReason"]="EXPLICIT_COLLECTION_ROUTE"; item["mediaScopeConfidence"]=1.0
                item["collectionTier"]="silver"; item["displayTier"]="silver"; item["collectionPeriodKey"]=period_key; item["collectionKind"]=kind
                asset_key=self._upsert_source_media_conn(conn,item,league=league,date=str(item.get("date") or period_key)[:10],catalog_state=ASSIGNED)
                if not asset_key: continue
                rank=400 if kind=="DAILY_RECAP" else 350 if kind=="TOP_PLAYS" else 300 if scope=="WEEK_LEAGUE" else 200
                confidence=float(item.get("mediaScopeConfidence") or 0); method=str(item.get("mediaScopeReason") or "EXPLICIT_COLLECTION_ROUTE")
                evidence=f"scope={scope}; kind={kind}; period={period_key}"
                conn.execute("INSERT INTO history_collection_media(collection_key,asset_key,association_confidence,association_method,association_evidence,classifier_version,rank_hint,first_associated_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(collection_key,asset_key) DO UPDATE SET association_confidence=excluded.association_confidence,association_method=excluded.association_method,association_evidence=excluded.association_evidence,classifier_version=excluded.classifier_version,rank_hint=excluded.rank_hint,updated_at=excluded.updated_at",(ckey,asset_key,confidence,method,evidence,int(item.get("mediaClassifierVersion") or MEDIA_CLASSIFIER_VERSION),rank,now,now)); count+=1
            conn.commit()
        return count

    def roundup_media(self, date, league=None):
        date=str(date or "")[:10]; league=str(league or "").upper()
        with self._lock, closing(self._connect()) as conn:
            params=[date,date]; league_sql=""
            if league and league!="ALL": league_sql=" AND c.league=?"; params.append(league)
            rows=conn.execute("""SELECT c.*,cm.rank_hint,s.* FROM history_collection c JOIN history_collection_media cm ON cm.collection_key=c.collection_key
              JOIN history_source_media s ON s.asset_key=cm.asset_key WHERE ((c.scope='DAY_LEAGUE' AND c.period_key=?) OR (c.scope='WEEK_LEAGUE' AND json_extract(s.asset_json,'$.date')=?))"""+league_sql+
              " ORDER BY cm.rank_hint DESC,s.verified_at DESC,s.duration_seconds DESC",params).fetchall()
        out=[]; seen=set()
        for row in rows:
            if row["asset_key"] in seen: continue
            seen.add(row["asset_key"]); item=self._hydrate_asset(row)
            item["mediaScope"]=row["scope"]; item["collectionTier"]="silver"; item["displayTier"]="silver"; item["collectionKind"]=row["collection_kind"]
            item["collectionPeriodKey"]=row["period_key"]; item["collectionKey"]=row["collection_key"]; out.append(item)
        return out

    def put_media(self, date, league, rows, merge=True):
        """Ingest source assets. Event association is deliberately separate.

        For browser/backward compatibility, the raw day cache is retained, but it
        is never read as playback authority when v4 normalized relationships exist.
        """
        date=str(date)[:10]; league=str(league).upper(); items=list(rows or [])
        if merge:
            current=self.get_league(date,league,prefer_catalog=False).get("media") or []; merged=[]; pos={}
            for item in [*current,*items]:
                if not isinstance(item,dict): continue
                key=self.asset_key_for(item) or self._dump_obj(item)
                if key in pos: merged[pos[key]].update(item)
                else: pos[key]=len(merged); merged.append(dict(item))
            items=merged
        now=time.time()
        with self._lock, closing(self._connect()) as conn:
            conn.execute("INSERT INTO history_day(date,league,media_json,media_saved_at) VALUES(?,?,?,?) ON CONFLICT(date,league) DO UPDATE SET media_json=excluded.media_json,media_saved_at=excluded.media_saved_at",(date,league,self._dump(items),now))
            for item in items:
                self._upsert_source_media_conn(conn,item,league=league,date=date)
            conn.commit()
        # Only rows that already carry the post-match canonical key are eligible
        # for an association replay. Generic source rows remain unassigned.
        grouped={}
        for item in items:
            ckey=str((item or {}).get("canonicalEventKey") or "")
            if ckey.startswith(league+":"):
                grouped.setdefault(ckey.split(":",1)[1],[]).append(item)
        for event_id,event_items in grouped.items(): self.put_event_media(date,league,event_id,event_items)
        return now

    def put_discovery(self, date, league, state, merge=True):
        date=str(date)[:10]; league=str(league).upper(); value=dict(state or {})
        if merge:
            current=self.get_league(date,league,prefer_catalog=False).get("discovery") or {}; merged=dict(current); merged.update(value)
            for key in ("deepSearchedEventIds","noQuotaSearchedEventIds"):
                if key in current or key in value: merged[key]=list(dict.fromkeys([*(current.get(key) or []),*(value.get(key) or [])]))
            value=merged
        now=time.time()
        with self._lock, closing(self._connect()) as conn:
            conn.execute("INSERT INTO history_day(date,league,discovery_json,discovery_saved_at) VALUES(?,?,?,?) ON CONFLICT(date,league) DO UPDATE SET discovery_json=excluded.discovery_json,discovery_saved_at=excluded.discovery_saved_at",(date,league,self._dump_obj(value),now)); conn.commit()
        return now

    def _catalog_media_for_league(self, date, league):
        date=str(date)[:10]; league=str(league).upper()
        with self._lock, closing(self._connect()) as conn:
            rows=conn.execute("""SELECT DISTINCT s.*,em.association_confidence,em.association_method,em.association_evidence,em.matcher_version,e.canonical_event_key
              FROM history_catalog_event e JOIN history_event_media em ON em.canonical_event_key=e.canonical_event_key
              JOIN history_source_media s ON s.asset_key=em.asset_key
              WHERE e.event_date=? AND e.league=? AND em.association_state='ASSIGNED' AND s.scope='GAME' ORDER BY e.canonical_event_key,s.verified_at DESC""",(date,league)).fetchall()
        out=[]
        for row in rows:
            item=self._hydrate_asset(row); item["canonicalEventKey"]=row["canonical_event_key"]
            event_id=str(row["canonical_event_key"]).split(":",1)[1]; item.setdefault("matchId",event_id); item.setdefault("scoreEventId",event_id); out.append(item)
        return out

    def get_league(self, date, league, prefer_catalog=True):
        date=str(date)[:10]; league=str(league).upper()
        with self._lock, closing(self._connect()) as conn:
            row=conn.execute("SELECT * FROM history_day WHERE date=? AND league=?",(date,league)).fetchone()
        if not row:
            base={"date":date,"league":league,"scores":[],"media":[],"discovery":{},"scoresSavedAt":0,"mediaSavedAt":0,"discoverySavedAt":0}
        else:
            base={"date":row["date"],"league":row["league"],"scores":self._load(row["scores_json"]),"media":self._load(row["media_json"]),"discovery":self._load_obj(row["discovery_json"]),
                "scoresSavedAt":float(row["scores_saved_at"] or 0),"mediaSavedAt":float(row["media_saved_at"] or 0),"discoverySavedAt":float(row["discovery_saved_at"] or 0)}
        if prefer_catalog:
            base["media"]=self._catalog_media_for_league(date,league)
        return base

    def get_day(self, date):
        date=str(date)[:10]
        with self._lock, closing(self._connect()) as conn:
            names=[r[0] for r in conn.execute("SELECT league FROM history_day WHERE date=? UNION SELECT league FROM history_catalog_event WHERE event_date=? ORDER BY league",(date,date)).fetchall()]
        leagues={}
        for league in names:
            row=self.get_league(date,league,prefer_catalog=True); leagues[league]={k:v for k,v in row.items() if k not in ("date","league")}
        return {"date":date,"leagues":leagues,"roundups":self.roundup_media(date)}

    def has_scores(self, date, league): return bool(self.get_league(date,league,prefer_catalog=False).get("scoresSavedAt"))

    def green_gap_events(self, *, current_discovery_version=0, now=None, limit=24, recent_cooldown=2*60*60, archive_cooldown=24*60*60, recent_cutoff=""):
        now=float(now or time.time()); current=int(current_discovery_version or 0); limit=max(1,min(200,int(limit or 24))); cutoff=str(recent_cutoff or time.strftime("%Y-%m-%d",time.gmtime(now-2*86400)))[:10]
        with self._lock, closing(self._connect()) as conn:
            rows=conn.execute("""WITH flags AS (
                SELECT em.canonical_event_key,
                  SUM(CASE WHEN em.association_state='ASSIGNED' AND s.validation_state='VERIFIED' AND s.runtime_state<>'FAILED' AND s.scope='GAME' THEN 1 ELSE 0 END) verified_count,
                  MAX(CASE WHEN em.association_state='ASSIGNED' AND s.validation_state='VERIFIED' AND s.runtime_state<>'FAILED' AND s.scope='GAME' AND json_extract(s.asset_json,'$.recapTier')='gold' THEN 1 ELSE 0 END) has_gold,
                  MAX(CASE WHEN em.association_state='ASSIGNED' AND s.validation_state='VERIFIED' AND s.runtime_state<>'FAILED' AND s.scope='GAME' AND json_extract(s.asset_json,'$.recapTier')='green' THEN 1 ELSE 0 END) has_green,
                  MAX(CASE WHEN em.association_state='ASSIGNED' AND s.validation_state='VERIFIED' AND s.runtime_state<>'FAILED' AND s.scope='GAME' AND json_extract(s.asset_json,'$.recapTier')='extended' THEN 1 ELSE 0 END) has_extended,
                  MAX(CASE WHEN em.association_state='ASSIGNED' AND s.validation_state='VERIFIED' AND s.runtime_state<>'FAILED' AND s.scope='GAME' AND COALESCE(json_extract(s.asset_json,'$.recapTier'),'blue')='blue' THEN 1 ELSE 0 END) has_blue
                FROM history_event_media em JOIN history_source_media s ON s.asset_key=em.asset_key GROUP BY em.canonical_event_key)
              SELECT e.*,COALESCE(f.verified_count,0) verified_count,COALESCE(f.has_gold,0) has_gold,COALESCE(f.has_green,0) has_green,COALESCE(f.has_extended,0) has_extended,COALESCE(f.has_blue,0) has_blue
              FROM history_catalog_event e LEFT JOIN flags f ON f.canonical_event_key=e.canonical_event_key
              WHERE COALESCE(f.has_gold,0)=0 AND COALESCE(f.has_green,0)=0
                AND (COALESCE(e.claim_expires_at,0)<=? OR COALESCE(e.claim_owner,'')='')
                AND (
                  COALESCE(CAST(json_extract(e.discovery_json,'$.discoveryVersion') AS INTEGER),0)<?
                  OR (e.next_retry_at<=? AND (e.last_discovery_at<=0 OR e.last_discovery_at <= ? - CASE WHEN e.event_date>=? THEN ? ELSE ? END))
                )
              ORDER BY CASE
                WHEN COALESCE(CAST(json_extract(e.discovery_json,'$.discoveryVersion') AS INTEGER),0)<? AND COALESCE(f.verified_count,0)=0 THEN -6
                WHEN COALESCE(CAST(json_extract(e.discovery_json,'$.discoveryVersion') AS INTEGER),0)<? AND COALESCE(f.has_blue,0)=1 THEN -5
                WHEN e.event_date>=? AND COALESCE(f.verified_count,0)=0 THEN -4
                WHEN e.event_date>=? AND COALESCE(f.has_blue,0)=1 THEN -3
                WHEN COALESCE(f.verified_count,0)=0 THEN -2 WHEN COALESCE(f.has_blue,0)=1 THEN -1
                WHEN e.event_date>=? AND COALESCE(f.has_extended,0)=1 THEN 0
                WHEN COALESCE(f.has_extended,0)=1 THEN 2 ELSE 3 END,
                e.event_date DESC,e.last_discovery_at ASC LIMIT ?""",(now,current,now,now,cutoff,float(recent_cooldown),float(archive_cooldown),current,current,cutoff,cutoff,cutoff,limit)).fetchall()
        out=[]
        for row in rows:
            best="blue" if row["has_blue"] else ("extended" if row["has_extended"] else "")
            out.append({"date":row["event_date"],"league":row["league"],"eventId":row["event_id"],"canonicalEventKey":row["canonical_event_key"],"event":self._load_obj(row["event_json"]),
                "discoveryState":row["discovery_state"],"discovery":self._load_obj(row["discovery_json"]),"nextRetryAt":float(row["next_retry_at"] or 0),"lastDiscoveryAt":float(row["last_discovery_at"] or 0),
                "verifiedCount":int(row["verified_count"] or 0),"hasBlue":bool(row["has_blue"]),"hasExtended":bool(row["has_extended"]),"bestTier":best or "none",
                "claimOwner":str(row["claim_owner"] or ""),"claimStartedAt":float(row["claim_started_at"] or 0),"claimExpiresAt":float(row["claim_expires_at"] or 0)})
        return out

    def green_gap_summary(self, *, current_discovery_version=0, now=None, recent_cooldown=2*60*60, archive_cooldown=24*60*60, recent_cutoff=""):
        now=float(now or time.time()); current=int(current_discovery_version or 0); cutoff=str(recent_cutoff or time.strftime("%Y-%m-%d",time.gmtime(now-2*86400)))[:10]
        with self._lock, closing(self._connect()) as conn:
            rows=conn.execute("""SELECT e.canonical_event_key,e.event_date,e.discovery_state,e.discovery_json,e.last_discovery_at,e.next_retry_at,e.claim_owner,e.claim_started_at,e.claim_expires_at,
                SUM(CASE WHEN em.association_state='ASSIGNED' AND s.validation_state='VERIFIED' AND s.runtime_state<>'FAILED' AND s.scope='GAME' THEN 1 ELSE 0 END) verified_count,
                MAX(CASE WHEN em.association_state='ASSIGNED' AND s.validation_state='VERIFIED' AND s.runtime_state<>'FAILED' AND s.scope='GAME' AND json_extract(s.asset_json,'$.recapTier')='gold' THEN 1 ELSE 0 END) has_gold,
                MAX(CASE WHEN em.association_state='ASSIGNED' AND s.validation_state='VERIFIED' AND s.runtime_state<>'FAILED' AND s.scope='GAME' AND json_extract(s.asset_json,'$.recapTier')='green' THEN 1 ELSE 0 END) has_green,
                MAX(CASE WHEN em.association_state='ASSIGNED' AND s.validation_state='VERIFIED' AND s.runtime_state<>'FAILED' AND s.scope='GAME' AND json_extract(s.asset_json,'$.recapTier')='extended' THEN 1 ELSE 0 END) has_extended,
                MAX(CASE WHEN em.association_state='ASSIGNED' AND s.validation_state='VERIFIED' AND s.runtime_state<>'FAILED' AND s.scope='GAME' AND COALESCE(json_extract(s.asset_json,'$.recapTier'),'blue')='blue' THEN 1 ELSE 0 END) has_blue
              FROM history_catalog_event e LEFT JOIN history_event_media em ON em.canonical_event_key=e.canonical_event_key LEFT JOIN history_source_media s ON s.asset_key=em.asset_key GROUP BY e.canonical_event_key""").fetchall()
        summary={"total":0,"due":0,"availableDue":0,"claimed":0,"recent":0,"recentNoMedia":0,"blueOnly":0,"purpleOnly":0,"unindexed":0,"searchedEmpty":0,"coverageComplete":0,"candidateOnly":0,"staleVersion":0}
        for row in rows:
            disc=self._load_obj(row["discovery_json"]); version=int(disc.get("discoveryVersion") or 0); verified=int(row["verified_count"] or 0)
            has_good=bool(row["has_gold"] or row["has_green"]); recent=str(row["event_date"])>=cutoff
            if not has_good: summary["total"]+=1
            if recent and not has_good: summary["recent"]+=1
            if recent and not verified: summary["recentNoMedia"]+=1
            if row["has_blue"] and not row["has_extended"] and not has_good: summary["blueOnly"]+=1
            if row["has_extended"] and not has_good: summary["purpleOnly"]+=1
            if version<current: summary["staleVersion"]+=1
            state=str(row["discovery_state"] or "UNKNOWN").upper()
            if version<current or state in {"","UNKNOWN"}: summary["unindexed"]+=1
            elif state=="SEARCHED_EMPTY" and not verified: summary["searchedEmpty"]+=1
            elif verified: summary["coverageComplete"]+=1
            elif state=="CANDIDATE_ONLY": summary["candidateOnly"]+=1
            cooldown=float(recent_cooldown if recent else archive_cooldown)
            stale=bool(version<current)
            due=stale or (float(row["next_retry_at"] or 0)<=now and (float(row["last_discovery_at"] or 0)<=0 or float(row["last_discovery_at"] or 0)<=now-cooldown))
            if not has_good and due:
                summary["due"]+=1
                claimed=bool(str(row["claim_owner"] or "") and float(row["claim_expires_at"] or 0)>now)
                if claimed: summary["claimed"]+=1
                else: summary["availableDue"]+=1
        # v4.1.4 operator-console aliases keep the explicit catalog semantics.
        # "noMedia" was ambiguous because UNINDEXED events can already have Blue
        # or Purple media; expose the actual union under an honest name instead.
        summary.update({
            "unindexedOrEmpty":summary["unindexed"]+summary["searchedEmpty"],"recentGaps":summary["recent"],
            "gaps":summary["total"],"due_now":summary["due"],"available_due":summary["availableDue"],"claimed":summary["claimed"],"recent_gaps":summary["recent"],"recent_no_media":summary["recentNoMedia"],
            "blue_only":summary["blueOnly"],"purple_only":summary["purpleOnly"],"stale_version":summary["staleVersion"],
            "searched_empty":summary["searchedEmpty"],"coverage_complete":summary["coverageComplete"],"candidate_only":summary["candidateOnly"],
            "unindexed_or_empty":summary["unindexed"]+summary["searchedEmpty"],
        })
        return summary

    def claim_event(self, canonical_event_key, owner, *, lease_seconds=300, now=None):
        """Atomically lease one canonical event to a worker.

        Claims survive thread crashes and process restarts only until their expiry;
        no discovery worker is allowed to own the same event concurrently.
        """
        key=str(canonical_event_key or ""); owner=str(owner or "")[:120]; now=float(now or time.time())
        if not key or not owner: return False
        expires=now+max(30,float(lease_seconds or 300))
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur=conn.execute("""UPDATE history_catalog_event SET claim_owner=?,claim_started_at=?,claim_expires_at=?,updated_at=?
              WHERE canonical_event_key=? AND (COALESCE(claim_expires_at,0)<=? OR COALESCE(claim_owner,'')='' OR claim_owner=?)""",
              (owner,now,expires,now,key,now,owner))
            ok=bool(cur.rowcount==1); conn.commit()
        return ok

    def renew_event_claim(self, canonical_event_key, owner, *, lease_seconds=300, now=None):
        key=str(canonical_event_key or ""); owner=str(owner or "")[:120]; now=float(now or time.time())
        if not key or not owner: return False
        expires=now+max(30,float(lease_seconds or 300))
        with self._lock, closing(self._connect()) as conn:
            cur=conn.execute("UPDATE history_catalog_event SET claim_expires_at=?,updated_at=? WHERE canonical_event_key=? AND claim_owner=?",(expires,now,key,owner)); conn.commit()
        return bool(cur.rowcount==1)

    def release_event_claim(self, canonical_event_key, owner="", *, force=False):
        key=str(canonical_event_key or ""); owner=str(owner or "")[:120]; now=time.time()
        if not key: return False
        with self._lock, closing(self._connect()) as conn:
            if force:
                cur=conn.execute("UPDATE history_catalog_event SET claim_owner='',claim_started_at=0,claim_expires_at=0,updated_at=? WHERE canonical_event_key=?",(now,key))
            else:
                cur=conn.execute("UPDATE history_catalog_event SET claim_owner='',claim_started_at=0,claim_expires_at=0,updated_at=? WHERE canonical_event_key=? AND claim_owner=?",(now,key,owner))
            conn.commit()
        return bool(cur.rowcount==1)

    def active_event_claims(self, *, now=None, limit=50):
        now=float(now or time.time()); limit=max(1,min(500,int(limit or 50)))
        with self._lock, closing(self._connect()) as conn:
            rows=conn.execute("""SELECT canonical_event_key,league,event_id,event_date,claim_owner,claim_started_at,claim_expires_at
              FROM history_catalog_event WHERE claim_owner<>'' AND claim_expires_at>? ORDER BY claim_started_at ASC LIMIT ?""",(now,limit)).fetchall()
        return [{"canonicalEventKey":r["canonical_event_key"],"league":r["league"],"eventId":r["event_id"],"date":r["event_date"],
                 "owner":r["claim_owner"],"startedAt":float(r["claim_started_at"] or 0),"expiresAt":float(r["claim_expires_at"] or 0)} for r in rows]

    def silver_summary(self):
        """Compact day/week Silver inventory for the operator console.

        The detailed collection audit endpoint remains the future dedicated Silver
        screen; this summary makes daily/weekly roundup growth observable now.
        """
        with self._lock, closing(self._connect()) as conn:
            day_col=int(conn.execute("SELECT COUNT(*) FROM history_collection WHERE scope='DAY_LEAGUE'").fetchone()[0] or 0)
            week_col=int(conn.execute("SELECT COUNT(*) FROM history_collection WHERE scope='WEEK_LEAGUE'").fetchone()[0] or 0)
            day_assets=int(conn.execute("SELECT COUNT(*) FROM history_collection_media cm JOIN history_collection c ON c.collection_key=cm.collection_key WHERE c.scope='DAY_LEAGUE'").fetchone()[0] or 0)
            week_assets=int(conn.execute("SELECT COUNT(*) FROM history_collection_media cm JOIN history_collection c ON c.collection_key=cm.collection_key WHERE c.scope='WEEK_LEAGUE'").fetchone()[0] or 0)
            periods=int(conn.execute("SELECT COUNT(DISTINCT scope||':'||league||':'||period_key) FROM history_collection").fetchone()[0] or 0)
        return {"dayCollections":day_col,"weekCollections":week_col,"dayAssets":day_assets,"weekAssets":week_assets,"periods":periods,"totalAssets":day_assets+week_assets}

    @staticmethod
    def _audit_effective_status(discovery_state, discovery, *, best_tier="", verified_count=0, current_discovery_version=0, quality_target="gold"):
        discovery=discovery if isinstance(discovery,dict) else {}; raw=str(discovery_state or "UNKNOWN").upper(); version=int(discovery.get("discoveryVersion") or 0); current=int(current_discovery_version or 0)
        current_ok=not current or version>=current; best=str(best_tier or "").lower(); quality_complete=bool(best==str(quality_target or "gold").lower() or (current_ok and discovery.get("qualityComplete") is True))
        catalog_complete=bool(current_ok and discovery.get("catalogComplete") is True); pending=bool(not current_ok or raw in {"","UNKNOWN"}); upgrade=bool((best and not quality_complete) or (current_ok and discovery.get("upgradeEligible") is True))
        if quality_complete: effective="QUALITY_COMPLETE"
        elif pending: effective="UNINDEXED"
        elif verified_count: effective="COVERAGE_COMPLETE" if catalog_complete and not upgrade else ("UPGRADE_PENDING" if upgrade else "PARTIAL")
        elif raw=="SEARCHED_EMPTY": effective="SEARCHED_EMPTY"
        elif raw=="DEGRADED_PROVIDER": effective="PROVIDER_DEGRADED"
        elif raw=="CANDIDATE_ONLY": effective="CANDIDATE_ONLY"
        else: effective="UNINDEXED"
        return {"effectiveStatus":effective,"discoveryState":raw,"discoveryVersion":version,"currentDiscoveryVersion":current,"versionCurrent":current_ok,"discoveryPending":pending,"catalogComplete":catalog_complete,"qualityComplete":quality_complete,"upgradeEligible":upgrade}

    def audit_catalog(self, *, date_from="", date_to="", league="", best_tier="", status="", search="", limit=100, offset=0, current_discovery_version=0, quality_target="gold"):
        league=str(league or "").upper(); search=str(search or "").lower(); status=str(status or "").lower(); best_tier=str(best_tier or "").lower(); limit=max(1,min(500,int(limit or 100))); offset=max(0,int(offset or 0))
        clauses=[]; params=[]
        if date_from: clauses.append("event_date>=?"); params.append(str(date_from)[:10])
        if date_to: clauses.append("event_date<=?"); params.append(str(date_to)[:10])
        if league: clauses.append("league=?"); params.append(league)
        where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
        with self._lock, closing(self._connect()) as conn:
            events=conn.execute("SELECT * FROM history_catalog_event"+where+" ORDER BY event_date DESC,league,event_id",params).fetchall()
            assets=conn.execute("""SELECT e.canonical_event_key,s.*,em.association_confidence,em.association_method,em.association_evidence,em.matcher_version
              FROM history_catalog_event e JOIN history_event_media em ON em.canonical_event_key=e.canonical_event_key JOIN history_source_media s ON s.asset_key=em.asset_key
              WHERE em.association_state='ASSIGNED' AND s.scope='GAME'""").fetchall()
        by_event={}
        for row in assets:
            item=self._hydrate_asset(row); item["associationConfidence"]=float(row["association_confidence"] or 0); item["associationMethod"]=row["association_method"]; item["associationEvidence"]=row["association_evidence"]
            tier=str(item.get("recapTier") or "blue"); tier=tier if tier in {"gold","green","extended","blue"} else "blue"; item["tier"]=tier
            youtube_id=str(item.get("youtubeId") or ""); item["url"]=str(item.get("externalUrl") or (f"https://www.youtube.com/watch?v={youtube_id}" if youtube_id else item.get("mediaUrl") or ""))
            item["verified"]=bool(str(row["validation_state"] or "").upper()=="VERIFIED" and str(row["runtime_state"] or "").upper()!="FAILED" and (youtube_id or item.get("mediaUrl")))
            by_event.setdefault(row["canonical_event_key"],[]).append(item)
        priority={"gold":4,"green":3,"extended":2,"blue":1,"":0}; rows=[]
        summary={"games":0,"verifiedAssets":0,"candidateAssets":0,"runtimeFailedAssets":0,"tiers":{"gold":0,"green":0,"extended":0,"blue":0},"best":{"gold":0,"green":0,"extended":0,"blue":0,"none":0},
                 "effectiveStatuses":{},"upgradePendingGames":0,"qualityCompleteGames":0,"discoveryPendingGames":0,"noVerifiedMediaGames":0,"greenCoverageGames":0,"greenCoverageByLeague":{}}
        for erow in events:
            event=self._load_obj(erow["event_json"]); disc=self._load_obj(erow["discovery_json"]); event_assets=by_event.get(erow["canonical_event_key"],[]); tiers={"gold":[],"green":[],"extended":[],"blue":[]}
            for asset in event_assets: tiers[asset["tier"]].append(asset)
            verified=[a for a in event_assets if a.get("verified")]; best=max((a["tier"] for a in verified),key=lambda t:priority.get(t,0),default="")
            away,home=team_name(event,"away"),team_name(event,"home"); game=f"{away} @ {home}".strip(" @") or erow["event_id"]
            projected=self._audit_effective_status(erow["discovery_state"],disc,best_tier=best,verified_count=len(verified),current_discovery_version=current_discovery_version,quality_target=quality_target)
            hay=f"{erow['event_date']} {erow['league']} {game} {erow['event_id']} "+" ".join(str(a.get("title") or "") for a in event_assets)
            if search and search not in hay.lower(): continue
            if best_tier and (best or "none")!=best_tier: continue
            eff=projected["effectiveStatus"]
            if status:
                runtime_failed=any(a.get("runtimeCatalogState")=="FAILED" for a in event_assets)
                status_ok={eff.lower(),eff.lower().replace("_","-")}
                if eff=="UNINDEXED": status_ok.update({"pending","unindexed"})
                if eff=="SEARCHED_EMPTY": status_ok.update({"searched-empty","empty"})
                if eff=="COVERAGE_COMPLETE": status_ok.update({"coverage","coverage-complete"})
                if projected["upgradeEligible"]: status_ok.add("upgrade")
                if eff=="PARTIAL": status_ok.add("partial")
                if projected["qualityComplete"]: status_ok.update({"complete","quality-complete"})
                if eff=="PROVIDER_DEGRADED": status_ok.add("degraded")
                if eff=="CANDIDATE_ONLY": status_ok.add("candidate")
                if runtime_failed: status_ok.add("failed")
                if not verified: status_ok.add("no-media")
                if status not in status_ok: continue
            summary["games"]+=1; summary["verifiedAssets"]+=len(verified); summary["candidateAssets"]+=sum(1 for a in event_assets if not a.get("verified")); summary["runtimeFailedAssets"]+=sum(1 for a in event_assets if a.get("runtimeCatalogState")=="FAILED")
            for tier in summary["tiers"]: summary["tiers"][tier]+=sum(1 for a in tiers[tier] if a.get("verified"))
            summary["best"][best or "none"]+=1; summary["effectiveStatuses"][eff]=summary["effectiveStatuses"].get(eff,0)+1
            if projected["upgradeEligible"]: summary["upgradePendingGames"]+=1
            if projected["qualityComplete"]: summary["qualityCompleteGames"]+=1
            if projected["discoveryPending"]: summary["discoveryPendingGames"]+=1
            if not verified: summary["noVerifiedMediaGames"]+=1
            cov=summary["greenCoverageByLeague"].setdefault(erow["league"],{"games":0,"greenGames":0,"greenOrGoldGames":0}); cov["games"]+=1
            if any(a.get("verified") for a in tiers["green"]): summary["greenCoverageGames"]+=1; cov["greenGames"]+=1
            if any(a.get("verified") for a in tiers["green"]+tiers["gold"]): cov["greenOrGoldGames"]+=1
            catalog_coverage=("UNINDEXED" if projected["discoveryPending"] else ("SEARCHED_EMPTY" if eff=="SEARCHED_EMPTY" else ("CANDIDATE_ONLY" if eff=="CANDIDATE_ONLY" else ("PLAYABLE_COMPLETE" if verified and projected["catalogComplete"] else ("PLAYABLE_PARTIAL" if verified else "PROVIDER_DEGRADED")))))
            quality_gap=("QUALITY_COMPLETE" if projected["qualityComplete"] else ("UPGRADE_PENDING" if verified else "NO_PLAYABLE_MEDIA"))
            rows.append({"date":erow["event_date"],"league":erow["league"],"eventId":erow["event_id"],"canonicalEventKey":erow["canonical_event_key"],"away":away,"home":home,"game":game,
              "discoveryState":projected["discoveryState"],"effectiveStatus":eff,"catalogCoverageStatus":catalog_coverage,"qualityGapStatus":quality_gap,"bestTier":best or "none","qualityComplete":projected["qualityComplete"],"upgradeEligible":projected["upgradeEligible"],"catalogComplete":projected["catalogComplete"],
              "discoveryPending":projected["discoveryPending"],"discoveryVersion":projected["discoveryVersion"],"currentDiscoveryVersion":projected["currentDiscoveryVersion"],"versionCurrent":projected["versionCurrent"],
              "nextRetryAt":float(erow["next_retry_at"] or 0),"lastDiscoveryAt":float(erow["last_discovery_at"] or 0),"lastError":str(erow["last_error"] or ""),"tiers":tiers,"verifiedAssetCount":len(verified),"assetCount":len(event_assets)})
        total=len(rows); return {"summary":summary,"rows":rows[offset:offset+limit],"total":total,"limit":limit,"offset":offset}

    def audit_export_rows(self, **filters):
        filters=dict(filters); filters["limit"]=500; filters["offset"]=0; first=self.audit_catalog(**filters); games=list(first["rows"]); total=int(first["total"] or 0); off=len(games)
        while off<total:
            f=dict(filters); f["offset"]=off; chunk=self.audit_catalog(**f)["rows"]
            if not chunk: break
            games.extend(chunk); off+=len(chunk)
        out=[]
        for game in games:
            common={"Best Tier":"purple" if game["bestTier"]=="extended" else game["bestTier"],"Audit Status":game["effectiveStatus"].replace("_"," "),"Catalog Coverage Status":game.get("catalogCoverageStatus") or "","Quality Gap Status":game.get("qualityGapStatus") or "","Discovery Pending":game["discoveryPending"],"Upgrade Pending":game["upgradeEligible"],"Catalog Complete":game["catalogComplete"],"Quality Complete":game["qualityComplete"],"Discovery Version":game["discoveryVersion"],"Current Discovery Version":game["currentDiscoveryVersion"],"Discovery State":game["discoveryState"]}
            emitted=False
            for tier in ("gold","green","extended","blue"):
                for asset in game["tiers"][tier]:
                    emitted=True; row={"Date":game["date"],"League":game["league"],"Game":game["game"],"Event ID":game["eventId"],"Tier":"purple" if tier=="extended" else tier,"Title":asset.get("title") or "","Duration Seconds":asset.get("durationSeconds") or asset.get("duration") or 0,"Provider":self._provider_for(asset),"URL":asset.get("url") or "","Validation":asset.get("validationState") or "","Runtime":asset.get("runtimeCatalogState") or "","Verified":bool(asset.get("verified")),"Last Verified":asset.get("historyVerifiedAt") or 0,"Association Confidence":asset.get("associationConfidence") or 0,"Association Method":asset.get("associationMethod") or "","Scope":asset.get("mediaScope") or "","Intent":asset.get("mediaIntent") or ""}; row.update(common); out.append(row)
            if not emitted:
                row={"Date":game["date"],"League":game["league"],"Game":game["game"],"Event ID":game["eventId"],"Tier":"","Title":"","Duration Seconds":0,"Provider":"","URL":"","Validation":"","Runtime":"","Verified":False,"Last Verified":0,"Association Confidence":0,"Association Method":"","Scope":"","Intent":""}; row.update(common); out.append(row)
        return out

    def assignment_reviews(self, *, state="", reason="", league="", limit=200, offset=0):
        state=str(state or "").upper(); reason=str(reason or "").upper(); league=str(league or "").upper(); limit=max(1,min(1000,int(limit or 200))); offset=max(0,int(offset or 0))
        clauses=[]; params=[]
        if state: clauses.append("ar.state=?"); params.append(state)
        if reason: clauses.append("ar.reason=?"); params.append(reason)
        if league: clauses.append("ar.league=?"); params.append(league)
        where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
        with self._lock, closing(self._connect()) as conn:
            total=int(conn.execute("SELECT COUNT(*) FROM history_assignment_review ar"+where,params).fetchone()[0] or 0)
            rows=conn.execute("""SELECT ar.*,s.title,s.provider,s.canonical_url,s.scope,s.intent,s.scope_confidence,s.scope_reason,s.intent_confidence,s.intent_reason,s.catalog_state
              FROM history_assignment_review ar JOIN history_source_media s ON s.asset_key=ar.asset_key"""+where+" ORDER BY ar.updated_at DESC,ar.id DESC LIMIT ? OFFSET ?",params+[limit,offset]).fetchall()
        out=[]
        for row in rows:
            out.append({"id":int(row["id"]),"assetKey":row["asset_key"],"league":row["league"],"date":row["event_date"],"proposedEventKey":row["proposed_event_key"],
                "state":row["state"],"reason":row["reason"],"evidence":self._load_obj(row["evidence_json"]),"classifierVersion":int(row["classifier_version"] or 0),"matcherVersion":int(row["matcher_version"] or 0),
                "title":row["title"],"provider":row["provider"],"url":row["canonical_url"],"scope":row["scope"],"intent":row["intent"],"scopeConfidence":float(row["scope_confidence"] or 0),
                "scopeReason":row["scope_reason"],"intentConfidence":float(row["intent_confidence"] or 0),"intentReason":row["intent_reason"],"catalogState":row["catalog_state"],"updatedAt":float(row["updated_at"] or 0)})
        return {"rows":out,"total":total,"limit":limit,"offset":offset}

    def discovery_attempts(self, *, league="", event_id="", source="", limit=200, offset=0):
        league=str(league or "").upper(); event_id=str(event_id or ""); source=str(source or ""); limit=max(1,min(1000,int(limit or 200))); offset=max(0,int(offset or 0))
        clauses=[]; params=[]
        if league: clauses.append("e.league=?"); params.append(league)
        if event_id: clauses.append("e.event_id=?"); params.append(event_id)
        if source: clauses.append("a.source=?"); params.append(source)
        where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
        base=" FROM history_discovery_attempt a JOIN history_catalog_event e ON e.canonical_event_key=a.canonical_event_key"
        with self._lock, closing(self._connect()) as conn:
            total=int(conn.execute("SELECT COUNT(*)"+base+where,params).fetchone()[0] or 0)
            rows=conn.execute("SELECT a.*,e.league,e.event_id,e.event_date"+base+where+" ORDER BY a.attempted_at DESC,a.id DESC LIMIT ? OFFSET ?",params+[limit,offset]).fetchall()
        out=[]
        for row in rows:
            out.append({"id":int(row["id"]),"canonicalEventKey":row["canonical_event_key"],"league":row["league"],"eventId":row["event_id"],"date":row["event_date"],"source":row["source"],
                "attemptedAt":float(row["attempted_at"] or 0),"discoveryVersion":int(row["discovery_version"] or 0),"queryType":row["query_type"],"query":row["query_text"],"resultCount":int(row["result_count"] or 0),
                "acceptedCount":int(row["accepted_count"] or 0),"bestBefore":row["best_before"],"bestAfter":row["best_after"],"quotaCost":float(row["quota_cost"] or 0),"failureReason":row["failure_reason"],"details":self._load_obj(row["details_json"])})
        return {"rows":out,"total":total,"limit":limit,"offset":offset}

    def collection_audit(self, *, scope="", league="", period_key="", collection_kind="", flag="", search="", limit=200, offset=0):
        """Read-only Silver collection audit with collection and asset integrity flags.

        Silver is intentionally audited independently from GAME media.  A collection
        link can therefore be suspicious without ever affecting an event tier or
        playback plan.  The query is SQL-paged so the operator UI can safely inspect
        thousands of roundup assets while the background workers continue running.
        """
        scope=str(scope or "").upper(); league=str(league or "").upper(); period_key=str(period_key or "")[:32]
        collection_kind=str(collection_kind or "").upper(); flag=str(flag or "").upper(); search=str(search or "").strip()[:160]
        limit=max(1,min(1000,int(limit or 200))); offset=max(0,int(offset or 0)); large_threshold=20
        clauses=[]; params=[]
        if scope: clauses.append("c.scope=?"); params.append(scope)
        if league: clauses.append("c.league=?"); params.append(league)
        if period_key: clauses.append("c.period_key LIKE ?"); params.append(f"%{period_key}%")
        if collection_kind: clauses.append("c.collection_kind=?"); params.append(collection_kind)
        if search:
            token=f"%{search}%"
            clauses.append("(s.title LIKE ? OR s.provider LIKE ? OR s.canonical_url LIKE ? OR s.asset_key LIKE ? OR c.period_key LIKE ? OR c.collection_kind LIKE ?)")
            params.extend([token]*6)

        stats_cte="""WITH collection_stats AS (
              SELECT collection_key,COUNT(*) AS collection_asset_count
              FROM history_collection_media GROUP BY collection_key
            ), asset_stats AS (
              SELECT cm2.asset_key,COUNT(*) AS asset_link_count,
                     COUNT(DISTINCT c2.scope||':'||c2.league||':'||c2.period_key) AS asset_period_count,
                     COUNT(DISTINCT c2.scope) AS asset_scope_count
              FROM history_collection_media cm2 JOIN history_collection c2 ON c2.collection_key=cm2.collection_key
              GROUP BY cm2.asset_key
            )"""
        base=""" FROM history_collection c
              JOIN history_collection_media cm ON cm.collection_key=c.collection_key
              JOIN history_source_media s ON s.asset_key=cm.asset_key
              JOIN collection_stats cs ON cs.collection_key=c.collection_key
              JOIN asset_stats ast ON ast.asset_key=cm.asset_key"""
        source_date="substr(COALESCE(json_extract(s.asset_json,'$.date'),''),1,10)"
        source_league="upper(COALESCE(json_extract(s.asset_json,'$.league'),''))"
        period_mismatch=f"(c.scope='DAY_LEAGUE' AND {source_date}<>'' AND {source_date}<>c.period_key)"
        league_mismatch=f"({source_league}<>'' AND {source_league}<>c.league)"
        suspicious=f"(cs.collection_asset_count>{large_threshold} OR ast.asset_link_count>1 OR ast.asset_period_count>1 OR ast.asset_scope_count>1 OR s.scope='GAME' OR cm.association_confidence<0.80 OR {period_mismatch} OR {league_mismatch} OR s.runtime_state='FAILED')"
        flag_map={
            'SUSPICIOUS':suspicious,
            'LARGE_COLLECTION':f"cs.collection_asset_count>{large_threshold}",
            'MULTI_COLLECTION_ASSET':"ast.asset_link_count>1",
            'DUPLICATE_ACROSS_PERIODS':"ast.asset_period_count>1",
            'CROSS_SCOPE_DUPLICATE':"ast.asset_scope_count>1",
            'GAME_SCOPE_ASSET':"s.scope='GAME'",
            'LOW_CONFIDENCE':"cm.association_confidence<0.80",
            'PERIOD_DATE_MISMATCH':period_mismatch,
            'LEAGUE_MISMATCH':league_mismatch,
            'RUNTIME_FAILED':"s.runtime_state='FAILED'",
        }
        if flag in flag_map: clauses.append(flag_map[flag])
        where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
        select="""SELECT c.collection_key,c.scope,c.league,c.period_key,c.collection_kind,c.title AS collection_title,
              cm.association_confidence,cm.association_method,cm.association_evidence,
              cm.classifier_version AS collection_classifier_version,cm.rank_hint,
              s.asset_key,s.title,s.provider,s.canonical_url,s.duration_seconds,s.published_at,
              s.validation_state,s.runtime_state,s.scope AS media_scope,s.intent,s.scope_confidence,s.scope_reason,
              s.intent_confidence,s.intent_reason,s.catalog_state,s.quarantine_reason,s.asset_json,
              cs.collection_asset_count,ast.asset_link_count,ast.asset_period_count,ast.asset_scope_count,
              """+source_date+" AS source_date,"+source_league+" AS source_league"
        with self._lock, closing(self._connect()) as conn:
            total=int(conn.execute(stats_cte+" SELECT COUNT(*)"+base+where,params).fetchone()[0] or 0)
            rows=conn.execute(stats_cte+" "+select+base+where+" ORDER BY c.period_key DESC,c.league,c.collection_kind,cm.rank_hint DESC,s.duration_seconds DESC LIMIT ? OFFSET ?",params+[limit,offset]).fetchall()
            summary_row=conn.execute(stats_cte+" SELECT COUNT(*) AS links,COUNT(DISTINCT c.collection_key) AS collections,COUNT(DISTINCT s.asset_key) AS unique_assets,"
                "COUNT(DISTINCT CASE WHEN c.scope='DAY_LEAGUE' THEN c.collection_key END) AS day_collections,COUNT(CASE WHEN c.scope='DAY_LEAGUE' THEN 1 END) AS day_links,"
                "COUNT(DISTINCT CASE WHEN c.scope='WEEK_LEAGUE' THEN c.collection_key END) AS week_collections,COUNT(CASE WHEN c.scope='WEEK_LEAGUE' THEN 1 END) AS week_links,"
                f"COUNT(CASE WHEN {suspicious} THEN 1 END) AS suspicious_links,COUNT(DISTINCT CASE WHEN cs.collection_asset_count>{large_threshold} THEN c.collection_key END) AS large_collections,"
                "COUNT(DISTINCT CASE WHEN ast.asset_link_count>1 THEN s.asset_key END) AS multi_collection_assets,COUNT(DISTINCT CASE WHEN ast.asset_period_count>1 THEN s.asset_key END) AS duplicate_assets,"
                "COUNT(CASE WHEN s.scope='GAME' THEN 1 END) AS game_scope_links,COUNT(CASE WHEN cm.association_confidence<0.80 THEN 1 END) AS low_confidence_links,"
                f"COUNT(CASE WHEN {period_mismatch} THEN 1 END) AS period_mismatch_links,COUNT(CASE WHEN {league_mismatch} THEN 1 END) AS league_mismatch_links,"
                "MAX(cs.collection_asset_count) AS max_collection_assets"+base+where,params).fetchone()
            kinds=[r[0] for r in conn.execute("SELECT DISTINCT collection_kind FROM history_collection ORDER BY collection_kind").fetchall() if r[0]]

        def row_flags(row):
            flags=[]
            if int(row["collection_asset_count"] or 0)>large_threshold: flags.append("LARGE_COLLECTION")
            if int(row["asset_link_count"] or 0)>1: flags.append("MULTI_COLLECTION_ASSET")
            if int(row["asset_period_count"] or 0)>1: flags.append("DUPLICATE_ACROSS_PERIODS")
            if int(row["asset_scope_count"] or 0)>1: flags.append("CROSS_SCOPE_DUPLICATE")
            if str(row["media_scope"] or "").upper()=="GAME": flags.append("GAME_SCOPE_ASSET")
            if float(row["association_confidence"] or 0)<0.80: flags.append("LOW_CONFIDENCE")
            if str(row["scope"] or "")=="DAY_LEAGUE" and str(row["source_date"] or "") and str(row["source_date"] or "")!=str(row["period_key"] or ""): flags.append("PERIOD_DATE_MISMATCH")
            if str(row["source_league"] or "") and str(row["source_league"] or "")!=str(row["league"] or ""): flags.append("LEAGUE_MISMATCH")
            if str(row["runtime_state"] or "").upper()=="FAILED": flags.append("RUNTIME_FAILED")
            return flags

        out=[]
        for row in rows:
            out.append({
                "collectionKey":row["collection_key"],"scope":row["scope"],"league":row["league"],"periodKey":row["period_key"],
                "collectionKind":row["collection_kind"],"collectionTitle":row["collection_title"],"collectionAssetCount":int(row["collection_asset_count"] or 0),
                "assetKey":row["asset_key"],"title":row["title"],"provider":row["provider"],"url":row["canonical_url"],
                "durationSeconds":float(row["duration_seconds"] or 0),"publishedAt":row["published_at"],"mediaScope":row["media_scope"],"intent":row["intent"],
                "scopeConfidence":float(row["scope_confidence"] or 0),"scopeReason":row["scope_reason"],"intentConfidence":float(row["intent_confidence"] or 0),"intentReason":row["intent_reason"],
                "validation":row["validation_state"],"runtime":row["runtime_state"],"catalogState":row["catalog_state"],"quarantineReason":row["quarantine_reason"],
                "associationConfidence":float(row["association_confidence"] or 0),"associationMethod":row["association_method"],"associationEvidence":row["association_evidence"],
                "classifierVersion":int(row["collection_classifier_version"] or 0),"rank":int(row["rank_hint"] or 0),
                "assetLinkCount":int(row["asset_link_count"] or 0),"assetPeriodCount":int(row["asset_period_count"] or 0),"assetScopeCount":int(row["asset_scope_count"] or 0),
                "sourceDate":row["source_date"] or "","sourceLeague":row["source_league"] or "","flags":row_flags(row),
            })
        sr=summary_row
        summary={
            "links":int(sr["links"] or 0),"collections":int(sr["collections"] or 0),"uniqueAssets":int(sr["unique_assets"] or 0),
            "dayCollections":int(sr["day_collections"] or 0),"dayAssets":int(sr["day_links"] or 0),"weekCollections":int(sr["week_collections"] or 0),"weekAssets":int(sr["week_links"] or 0),
            "suspiciousLinks":int(sr["suspicious_links"] or 0),"largeCollections":int(sr["large_collections"] or 0),"multiCollectionAssets":int(sr["multi_collection_assets"] or 0),"duplicateAssets":int(sr["duplicate_assets"] or 0),
            "gameScopeLinks":int(sr["game_scope_links"] or 0),"lowConfidenceLinks":int(sr["low_confidence_links"] or 0),
            "periodMismatchLinks":int(sr["period_mismatch_links"] or 0),"leagueMismatchLinks":int(sr["league_mismatch_links"] or 0),
            "maxCollectionAssets":int(sr["max_collection_assets"] or 0),"largeCollectionThreshold":large_threshold,
        }
        return {"rows":out,"total":total,"limit":limit,"offset":offset,"summary":summary,"facets":{"collectionKinds":kinds}}

    def catalog_integrity(self):
        with self._lock, closing(self._connect()) as conn:
            scalar=lambda sql: int((conn.execute(sql).fetchone()[0] or 0))
            return {
                "schemaVersion":CATALOG_SCHEMA_VERSION,
                "sourceAssets":scalar("SELECT COUNT(*) FROM history_source_media"),
                "assignedEventLinks":scalar("SELECT COUNT(*) FROM history_event_media WHERE association_state='ASSIGNED'"),
                "quarantinedEventLinks":scalar("SELECT COUNT(*) FROM history_event_media WHERE association_state='QUARANTINED'"),
                "unassignedAssets":scalar("SELECT COUNT(*) FROM history_source_media WHERE catalog_state='UNASSIGNED'"),
                "quarantinedAssets":scalar("SELECT COUNT(*) FROM history_source_media WHERE catalog_state='QUARANTINED'"),
                "silverLinks":scalar("SELECT COUNT(*) FROM history_collection_media"),
                "silverGameLeaks":scalar("SELECT COUNT(*) FROM history_event_media em JOIN history_source_media s ON s.asset_key=em.asset_key WHERE em.association_state='ASSIGNED' AND s.scope<>'GAME'"),
                "collectionGameLeaks":scalar("SELECT COUNT(*) FROM history_collection_media cm JOIN history_source_media s ON s.asset_key=cm.asset_key WHERE s.scope='GAME'"),
                "lowConfidenceCollectionLinks":scalar("SELECT COUNT(*) FROM history_collection_media WHERE association_confidence<0.80"),
                "crossEventAssignedAssets":scalar("SELECT COUNT(*) FROM (SELECT asset_key FROM history_event_media WHERE association_state='ASSIGNED' GROUP BY asset_key HAVING COUNT(DISTINCT canonical_event_key)>1)"),
                "lowConfidenceAssigned":scalar("SELECT COUNT(*) FROM history_event_media WHERE association_state='ASSIGNED' AND association_confidence<0.90"),
                "segments":scalar("SELECT COUNT(*) FROM history_media_segment"),
                "discoveryAttempts":scalar("SELECT COUNT(*) FROM history_discovery_attempt"),
                "verificationRecords":scalar("SELECT COUNT(*) FROM history_media_verification"),
            }

    def summary(self):
        with self._lock, closing(self._connect()) as conn:
            day=conn.execute("SELECT COUNT(DISTINCT date) days,COUNT(*) league_days,MAX(scores_saved_at) last_scores,MAX(media_saved_at) last_media,MAX(discovery_saved_at) last_discovery FROM history_day").fetchone()
            events=conn.execute("SELECT COUNT(*) events FROM history_catalog_event").fetchone(); media=conn.execute("SELECT COUNT(*) assets,SUM(CASE WHEN validation_state='VERIFIED' AND runtime_state<>'FAILED' THEN 1 ELSE 0 END) verified,SUM(CASE WHEN runtime_state='PLAYED' THEN 1 ELSE 0 END) played,SUM(CASE WHEN runtime_state='FAILED' THEN 1 ELSE 0 END) failed FROM history_source_media").fetchone()
            collections=conn.execute("SELECT COUNT(*) collections FROM history_collection").fetchone(); deep=0
            for row in conn.execute("SELECT discovery_json FROM history_day WHERE discovery_json IS NOT NULL AND discovery_json<>''"):
                if self._load_obj(row[0]).get("deepComplete"): deep+=1
        return {"catalogSchemaVersion":CATALOG_SCHEMA_VERSION,"days":int(day["days"] or 0),"leagueDays":int(day["league_days"] or 0),"events":int(events["events"] or 0),"assets":int(media["assets"] or 0),"verifiedAssets":int(media["verified"] or 0),"runtimePlayedAssets":int(media["played"] or 0),"runtimeFailedAssets":int(media["failed"] or 0),"collections":int(collections["collections"] or 0),"deepCompleteLeagueDays":deep,"lastScoresSavedAt":float(day["last_scores"] or 0),"lastMediaSavedAt":float(day["last_media"] or 0),"lastDiscoverySavedAt":float(day["last_discovery"] or 0),"integrity":self.catalog_integrity()}

    # v3.x compatibility hook. v4 never mutates legacy event/media tables in place.
    def reclassify_media_scopes(self):
        return {"baseline":"v4-normalized","catalogSchemaVersion":CATALOG_SCHEMA_VERSION,"movedToCollections":0,"updatedScopes":0}

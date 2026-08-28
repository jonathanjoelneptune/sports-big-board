"""Sports Big Board v4.5.5 media intelligence.

A single, bandwidth-bounded background worker enriches every normalized media asset
with durable music-presence intelligence. Existing catalog media is backfilled and
newly discovered media is picked up automatically because history_source_media is
the only queue source.

The detector is deliberately conservative. NO_MUSIC is emitted only with strong
evidence; uncertain material remains UNKNOWN, which causes the browser soundtrack
to yield so Sports Big Board never intentionally layers two songs.
"""
from __future__ import annotations

import array
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
from contextlib import closing
from dataclasses import dataclass

MUSIC_SCAN_VERSION = 1
MUSIC_STATUSES = ("PENDING", "HAS_MUSIC", "NO_MUSIC", "UNKNOWN", "SCAN_FAILED")
DEFAULT_SAMPLE_SECONDS = max(4.0, min(12.0, float(os.environ.get("SBB_MUSIC_SAMPLE_SECONDS", "8") or 8)))
DEFAULT_SAMPLE_COUNT = max(2, min(6, int(os.environ.get("SBB_MUSIC_SAMPLE_COUNT", "4") or 4)))
MUSIC_WORKER_IDLE_SECONDS = max(5.0, float(os.environ.get("SBB_MUSIC_WORKER_IDLE_SECONDS", "20") or 20))
MUSIC_WORKER_BALANCED_PAUSE = max(2.0, float(os.environ.get("SBB_MUSIC_WORKER_BALANCED_PAUSE", "8") or 8))
MUSIC_ACTIVE_MEDIA_GRACE_SECONDS = max(5.0, float(os.environ.get("SBB_MUSIC_ACTIVE_MEDIA_GRACE_SECONDS", "15") or 15))
MUSIC_FOREGROUND_TRICKLE_SECONDS = max(30.0, float(os.environ.get("SBB_MUSIC_FOREGROUND_TRICKLE_SECONDS", "120") or 120))
MUSIC_FAILED_RETRY_BASE_SECONDS = max(3600.0, float(os.environ.get("SBB_MUSIC_FAILED_RETRY_BASE_SECONDS", "21600") or 21600))
MUSIC_FAILED_RETRY_MAX_SECONDS = max(MUSIC_FAILED_RETRY_BASE_SECONDS, float(os.environ.get("SBB_MUSIC_FAILED_RETRY_MAX_SECONDS", "604800") or 604800))
MAX_SCAN_ATTEMPTS = max(2, min(12, int(os.environ.get("SBB_MUSIC_MAX_SCAN_ATTEMPTS", "6") or 6)))
FFMPEG_TIMEOUT_SECONDS = max(8, min(90, int(os.environ.get("SBB_MUSIC_FFMPEG_TIMEOUT_SECONDS", "30") or 30)))
YTDLP_TIMEOUT_SECONDS = max(10, min(90, int(os.environ.get("SBB_MUSIC_YTDLP_TIMEOUT_SECONDS", "30") or 30)))
SAMPLE_RATE = 8000
FRAME_SECONDS = 0.5
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_SECONDS)
ANALYSIS_FREQUENCIES = (110.0, 146.8, 196.0, 261.6, 329.6, 440.0, 587.3, 783.9, 1046.5, 1568.0, 2093.0, 3136.0)


@dataclass
class MusicResult:
    status: str
    confidence: float
    ratio: float
    conflict: bool
    scanned_seconds: float
    details: dict


class MediaIntelligenceStore:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self.ensure_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @staticmethod
    def _ensure_column(conn, table, name, ddl):
        columns={str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if name not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


    def ensure_schema(self):
        now = time.time()
        with self._lock, closing(self._connect()) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history_media_intelligence (
                    asset_key TEXT PRIMARY KEY,
                    music_status TEXT NOT NULL DEFAULT 'PENDING',
                    music_confidence REAL NOT NULL DEFAULT 0,
                    music_ratio REAL NOT NULL DEFAULT 0,
                    music_conflict INTEGER NOT NULL DEFAULT 1,
                    scan_version INTEGER NOT NULL DEFAULT 0,
                    scan_duration_seconds REAL NOT NULL DEFAULT 0,
                    scan_attempts INTEGER NOT NULL DEFAULT 0,
                    scanned_at REAL NOT NULL DEFAULT 0,
                    next_retry_at REAL NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    details_json TEXT NOT NULL DEFAULT '{}',
                    claim_owner TEXT NOT NULL DEFAULT '',
                    claim_started_at REAL NOT NULL DEFAULT 0,
                    claim_expires_at REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0,
                    scan_priority INTEGER NOT NULL DEFAULT 0,
                    scan_requested_at REAL NOT NULL DEFAULT 0,
                    scan_request_reason TEXT NOT NULL DEFAULT '',
                    attempted_at REAL NOT NULL DEFAULT 0,
                    failure_kind TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(asset_key) REFERENCES history_source_media(asset_key) ON DELETE CASCADE
                )""")
            self._ensure_column(conn, "history_media_intelligence", "scan_priority", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "history_media_intelligence", "scan_requested_at", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn, "history_media_intelligence", "scan_request_reason", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "history_media_intelligence", "attempted_at", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn, "history_media_intelligence", "failure_kind", "TEXT NOT NULL DEFAULT ''")
            # Upgrade v4.5.0-v4.5.3 failure rows so existing production failures are
            # immediately explainable after deployment instead of remaining opaque OTHER rows.
            conn.execute("""
                UPDATE history_media_intelligence SET
                  attempted_at=CASE WHEN attempted_at<=0 THEN COALESCE(NULLIF(updated_at,0),NULLIF(scanned_at,0),?) ELSE attempted_at END,
                  failure_kind=CASE
                    WHEN failure_kind<>'' AND NOT (failure_kind='YOUTUBE_RESOLVE' AND LOWER(COALESCE(last_error,'')) LIKE '%requested format is not available%') THEN failure_kind
                    WHEN LOWER(COALESCE(last_error,'')) LIKE '%requested format is not available%' THEN 'FORMAT_UNAVAILABLE'
                    WHEN LOWER(COALESCE(last_error,'')) LIKE '%yt-dlp%' OR LOWER(COALESCE(last_error,'')) LIKE '%youtube%' THEN 'YOUTUBE_RESOLVE'
                    WHEN LOWER(COALESCE(last_error,'')) LIKE '%timeout%' OR LOWER(COALESCE(last_error,'')) LIKE '%timed out%' THEN 'TIMEOUT'
                    WHEN LOWER(COALESCE(last_error,'')) LIKE '%ffmpeg%' OR LOWER(COALESCE(last_error,'')) LIKE '%decode%' THEN 'FFMPEG_DECODE'
                    WHEN LOWER(COALESCE(last_error,'')) LIKE '%no analyzable media url%' OR LOWER(COALESCE(last_error,'')) LIKE '%no audio sample decoded%' THEN 'NO_SOURCE'
                    WHEN LOWER(COALESCE(last_error,'')) LIKE '%403%' OR LOWER(COALESCE(last_error,'')) LIKE '%404%' OR LOWER(COALESCE(last_error,'')) LIKE '%forbidden%' OR LOWER(COALESCE(last_error,'')) LIKE '%not found%' THEN 'UPSTREAM_HTTP'
                    ELSE 'OTHER'
                  END
                WHERE music_status='SCAN_FAILED' AND (attempted_at<=0 OR failure_kind='' OR (failure_kind='YOUTUBE_RESOLVE' AND LOWER(COALESCE(last_error,'')) LIKE '%requested format is not available%'))
            """,(now,))
            # v4.5.5 repairs the resolver/runtime that caused the old format-unavailable
            # failures. Re-open each affected row exactly once without giving it
            # priority over the never-scanned backlog or touching successful results.
            conn.execute("""
                UPDATE history_media_intelligence SET
                  scan_attempts=0,next_retry_at=0,scan_priority=0,
                  scan_request_reason='v4.5.5-youtube-repair',updated_at=?
                WHERE music_status='SCAN_FAILED' AND failure_kind='FORMAT_UNAVAILABLE'
                  AND COALESCE(scan_request_reason,'')<>'v4.5.5-youtube-repair'
            """,(now,))
            conn.execute("CREATE INDEX IF NOT EXISTS idx_media_intelligence_queue ON history_media_intelligence(scan_priority,scan_version,music_status,next_retry_at,claim_expires_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_media_intelligence_status ON history_media_intelligence(music_status,scanned_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_media_intelligence_priority_queue ON history_media_intelligence(scan_priority DESC,scan_requested_at DESC,music_status,next_retry_at)")
            conn.execute("""
                INSERT OR IGNORE INTO history_media_intelligence(asset_key,music_status,music_conflict,created_at,updated_at)
                SELECT asset_key,'PENDING',1,?,? FROM history_source_media
            """, (now, now))
            conn.commit()

    @staticmethod
    def _asset_json(row):
        try:
            value = json.loads(row["asset_json"] or "{}")
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _seed_missing_rows(self, conn, now):
        conn.execute("""
            INSERT OR IGNORE INTO history_media_intelligence(asset_key,music_status,music_conflict,created_at,updated_at)
            SELECT asset_key,'PENDING',1,?,? FROM history_source_media
        """, (now, now))

    def claim_next(self, owner, lease_seconds=420):
        now = time.time()
        lease_seconds = max(90, int(lease_seconds or 420))
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._seed_missing_rows(conn, now)
            row = conn.execute("""
                SELECT s.asset_key,s.provider,s.provider_media_id,s.canonical_url,s.title,
                       s.duration_seconds,s.published_at,s.validation_state,s.runtime_state,
                       s.asset_json,mi.music_status,mi.scan_attempts,mi.scan_version,
                       mi.scan_priority,mi.scan_requested_at,mi.scan_request_reason,mi.attempted_at,mi.failure_kind
                FROM history_source_media s
                JOIN history_media_intelligence mi ON mi.asset_key=s.asset_key
                WHERE UPPER(COALESCE(s.runtime_state,''))<>'FAILED'
                  AND UPPER(COALESCE(s.validation_state,'CANDIDATE')) IN ('VERIFIED','CANDIDATE')
                  AND (
                       mi.scan_version < ?
                       OR mi.music_status='PENDING'
                       OR (mi.music_status='UNKNOWN' AND mi.next_retry_at<=?)
                       OR (mi.music_status='SCAN_FAILED' AND mi.next_retry_at<=?)
                  )
                  AND (mi.claim_expires_at<=? OR mi.claim_owner=?)
                  AND mi.scan_attempts < ?
                ORDER BY
                  -- v4.5.4: fresh unprocessed assets beat ordinary failed retries; explicit priority still wins.
                  mi.scan_priority DESC, mi.scan_requested_at DESC,
                  CASE
                    WHEN mi.scan_version < ? OR mi.music_status='PENDING' THEN 0
                    WHEN mi.music_status='UNKNOWN' THEN 1
                    WHEN mi.music_status='SCAN_FAILED' THEN 2
                    ELSE 3
                  END,
                  CASE UPPER(COALESCE(s.runtime_state,'')) WHEN 'PLAYED' THEN 0 ELSE 1 END,
                  CASE UPPER(COALESCE(s.validation_state,'')) WHEN 'VERIFIED' THEN 0 ELSE 1 END,
                  s.last_seen_at DESC,s.updated_at DESC
                LIMIT 1
            """, (MUSIC_SCAN_VERSION, now, now, now, str(owner), MAX_SCAN_ATTEMPTS, MUSIC_SCAN_VERSION)).fetchone()
            if not row:
                conn.commit()
                return None
            conn.execute("""
                UPDATE history_media_intelligence
                SET music_status='PENDING',claim_owner=?,claim_started_at=?,claim_expires_at=?,
                    scan_attempts=scan_attempts+1,scan_priority=0,attempted_at=?,updated_at=?
                WHERE asset_key=?
            """, (str(owner), now, now + lease_seconds, now, now, row["asset_key"]))
            conn.commit()
        item = dict(row)
        item["asset"] = self._asset_json(row)
        item["attempt"] = int(row["scan_attempts"] or 0) + 1
        return item

    def complete(self, asset_key, result: MusicResult):
        now = time.time()
        status = str(result.status or "UNKNOWN").upper()
        if status not in MUSIC_STATUSES:
            status = "UNKNOWN"
        confidence = max(0.0, min(1.0, float(result.confidence or 0)))
        ratio = max(0.0, min(1.0, float(result.ratio or 0)))
        details = dict(result.details or {})
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute("SELECT asset_json FROM history_source_media WHERE asset_key=?", (asset_key,)).fetchone()
            if not row:
                return False
            try:
                asset = json.loads(row["asset_json"] or "{}")
                if not isinstance(asset, dict):
                    asset = {}
            except Exception:
                asset = {}
            asset.update({
                "musicStatus": status,
                "musicConfidence": round(confidence, 4),
                "musicRatio": round(ratio, 4),
                "musicConflict": bool(result.conflict),
                "musicScanVersion": MUSIC_SCAN_VERSION,
                "musicScannedAt": now,
                "musicScanDuration": round(float(result.scanned_seconds or 0), 2),
            })
            next_retry = now + 30*24*3600 if status=='UNKNOWN' else 0
            conn.execute("""
                UPDATE history_media_intelligence SET
                  music_status=?,music_confidence=?,music_ratio=?,music_conflict=?,
                  scan_version=?,scan_duration_seconds=?,scanned_at=?,next_retry_at=?,
                  last_error='',details_json=?,claim_owner='',claim_started_at=0,
                  claim_expires_at=0,scan_priority=0,attempted_at=?,failure_kind='',updated_at=? WHERE asset_key=?
            """, (status, confidence, ratio, 1 if result.conflict else 0,
                  MUSIC_SCAN_VERSION, float(result.scanned_seconds or 0), now, next_retry,
                  json.dumps(details, ensure_ascii=False, separators=(",", ":"), default=str),
                  now, now, asset_key))
            conn.execute("UPDATE history_source_media SET asset_json=?,updated_at=? WHERE asset_key=?",
                         (json.dumps(asset, ensure_ascii=False, separators=(",", ":"), default=str), now, asset_key))
            conn.commit()
        return True

    @staticmethod
    def failure_kind(error):
        text=f"{type(error).__name__}: {error}".lower()
        if 'requested format is not available' in text:
            return 'FORMAT_UNAVAILABLE'
        if 'yt-dlp' in text or 'youtube' in text:
            return 'YOUTUBE_RESOLVE'
        if 'timeout' in text or 'timed out' in text:
            return 'TIMEOUT'
        if 'ffmpeg' in text or 'decode' in text:
            return 'FFMPEG_DECODE'
        if 'no analyzable media url' in text or 'no audio sample decoded' in text:
            return 'NO_SOURCE'
        if any(token in text for token in ('http error 403','http error 404',' 403 ',' 404 ','forbidden','not found')):
            return 'UPSTREAM_HTTP'
        return 'OTHER'

    def fail(self, asset_key, error):
        now = time.time()
        text = f"{type(error).__name__}: {error}"[:900]
        kind = self.failure_kind(error)
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute("SELECT scan_attempts FROM history_media_intelligence WHERE asset_key=?", (asset_key,)).fetchone()
            attempts = int(row["scan_attempts"] or 1) if row else 1
            base = max(MUSIC_FAILED_RETRY_BASE_SECONDS, 12*3600 if kind=='FORMAT_UNAVAILABLE' else (24*3600 if kind in ('YOUTUBE_RESOLVE','NO_SOURCE') else 0))
            retry = now + min(MUSIC_FAILED_RETRY_MAX_SECONDS, base * (2 ** min(5, max(0, attempts - 1))))
            conn.execute("""
                UPDATE history_media_intelligence SET music_status='SCAN_FAILED',
                  music_confidence=0,music_ratio=0,music_conflict=1,scan_version=?,
                  next_retry_at=?,last_error=?,claim_owner='',claim_started_at=0,
                  claim_expires_at=0,scan_priority=0,attempted_at=?,failure_kind=?,updated_at=? WHERE asset_key=?
            """, (MUSIC_SCAN_VERSION, retry, text, now, kind, now, asset_key))
            source = conn.execute("SELECT asset_json FROM history_source_media WHERE asset_key=?", (asset_key,)).fetchone()
            if source:
                try:
                    asset = json.loads(source["asset_json"] or "{}")
                    if not isinstance(asset, dict):
                        asset = {}
                except Exception:
                    asset = {}
                asset.update({
                    "musicStatus": "SCAN_FAILED",
                    "musicConfidence": 0.0,
                    "musicConflict": True,
                    "musicScanVersion": MUSIC_SCAN_VERSION,
                    "musicScanAttemptedAt": now,
                    "musicFailureKind": kind,
                })
                conn.execute("UPDATE history_source_media SET asset_json=?,updated_at=? WHERE asset_key=?",
                             (json.dumps(asset, ensure_ascii=False, separators=(",", ":"), default=str), now, asset_key))
            conn.commit()
        return retry

    def resolve_asset_key(self, asset_key):
        raw=str(asset_key or '').strip()
        if not raw: return ''
        with self._lock, closing(self._connect()) as conn:
            if conn.execute("SELECT 1 FROM history_source_media WHERE asset_key=? LIMIT 1",(raw,)).fetchone():
                return raw
            if raw.startswith('direct:'):
                url=raw[7:]
                row=conn.execute("SELECT asset_key FROM history_source_media WHERE canonical_url=? LIMIT 1",(url,)).fetchone()
                if row: return str(row[0])
                row=conn.execute("SELECT asset_key FROM history_source_media WHERE asset_json LIKE ? LIMIT 1",('%'+url.replace('%','%%')+'%',)).fetchone()
                if row: return str(row[0])
            if raw.startswith('youtube:'):
                video_id=raw[8:]
                row=conn.execute("SELECT asset_key FROM history_source_media WHERE provider_media_id=? LIMIT 1",(video_id,)).fetchone()
                if row: return str(row[0])
                row=conn.execute("SELECT asset_key FROM history_source_media WHERE asset_json LIKE ? LIMIT 1",('%'+video_id.replace('%','%%')+'%',)).fetchone()
                if row: return str(row[0])
        return ''

    def request_scan(self, asset_key, *, priority=100, reason="operator-current"):
        asset_key=self.resolve_asset_key(asset_key)
        if not asset_key:
            return None
        now=time.time(); priority=max(1,min(1000,int(priority or 100)))
        with self._lock, closing(self._connect()) as conn:
            self._seed_missing_rows(conn, now)
            source=conn.execute("SELECT asset_key,title,provider,canonical_url,asset_json FROM history_source_media WHERE asset_key=?",(asset_key,)).fetchone()
            if not source:
                return None
            conn.execute("""
                UPDATE history_media_intelligence SET
                  music_status='PENDING',next_retry_at=0,scan_attempts=0,
                  claim_owner='',claim_started_at=0,claim_expires_at=0,
                  scan_priority=MAX(COALESCE(scan_priority,0),?),scan_requested_at=?,scan_request_reason=?,updated_at=?
                WHERE asset_key=?
            """,(priority,now,str(reason or 'operator')[:120],now,asset_key))
            conn.commit()
        return self.asset(asset_key)

    def priority_request_level(self):
        now=time.time()
        with self._lock, closing(self._connect()) as conn:
            self._seed_missing_rows(conn, now)
            row=conn.execute("SELECT COALESCE(MAX(scan_priority),0) FROM history_media_intelligence WHERE scan_priority>0").fetchone()
            conn.commit()
            return int((row[0] if row else 0) or 0)

    def has_priority_request(self):
        return self.priority_request_level() > 0

    @staticmethod
    def _row_payload(row):
        if not row:
            return None
        payload=dict(row)
        try:
            asset=json.loads(payload.pop('asset_json','{}') or '{}')
            if not isinstance(asset,dict): asset={}
        except Exception:
            asset={}
        payload['asset']=asset
        for key in ('league','competitionId','__sbbLeague'):
            if asset.get(key): payload.setdefault('league',str(asset.get(key)).upper()); break
        payload.setdefault('date',str(asset.get('date') or asset.get('gameDate') or asset.get('publishedAt') or '')[:10])
        payload.setdefault('eventId',str(asset.get('eventId') or asset.get('matchId') or asset.get('gamePk') or ''))
        return payload

    def asset(self, asset_key):
        asset_key=self.resolve_asset_key(asset_key)
        if not asset_key: return None
        with self._lock, closing(self._connect()) as conn:
            row=conn.execute("""
                SELECT s.asset_key,s.provider,s.provider_media_id,s.canonical_url,s.title,s.duration_seconds,s.published_at,
                       s.validation_state,s.runtime_state,s.asset_json,
                       mi.music_status,mi.music_confidence,mi.music_ratio,mi.music_conflict,mi.scan_version,
                       mi.scan_duration_seconds,mi.scan_attempts,mi.scanned_at,mi.next_retry_at,mi.last_error,
                       mi.scan_priority,mi.scan_requested_at,mi.scan_request_reason,mi.attempted_at,mi.failure_kind
                FROM history_source_media s JOIN history_media_intelligence mi ON mi.asset_key=s.asset_key
                WHERE s.asset_key=? LIMIT 1
            """,(asset_key,)).fetchone()
        return self._row_payload(row)

    def list_assets(self, status='', limit=25):
        status=str(status or '').strip().upper(); limit=max(1,min(100,int(limit or 25)))
        if status and status not in MUSIC_STATUSES: status=''
        where='WHERE mi.music_status=?' if status else ''
        args=[status] if status else []
        args.append(limit)
        with self._lock, closing(self._connect()) as conn:
            rows=conn.execute(f"""
                SELECT s.asset_key,s.provider,s.provider_media_id,s.canonical_url,s.title,s.duration_seconds,s.published_at,
                       s.validation_state,s.runtime_state,s.asset_json,
                       mi.music_status,mi.music_confidence,mi.music_ratio,mi.music_conflict,mi.scan_version,
                       mi.scan_duration_seconds,mi.scan_attempts,mi.scanned_at,mi.last_error,
                       mi.scan_priority,mi.scan_requested_at,mi.scan_request_reason,mi.attempted_at,mi.failure_kind
                FROM history_media_intelligence mi JOIN history_source_media s ON s.asset_key=mi.asset_key
                {where}
                ORDER BY CASE WHEN mi.music_status IN ('HAS_MUSIC','NO_MUSIC') THEN mi.music_confidence ELSE 0 END DESC,
                         CASE WHEN mi.music_status='SCAN_FAILED' THEN mi.attempted_at ELSE mi.scanned_at END DESC,
                         s.last_seen_at DESC LIMIT ?
            """,args).fetchall()
        return [self._row_payload(row) for row in rows]

    def validation_set(self, per_status=3):
        n=max(1,min(10,int(per_status or 3)))
        return {
            'hasMusic':self.list_assets('HAS_MUSIC',n),
            'noMusic':self.list_assets('NO_MUSIC',n),
            'unknown':self.list_assets('UNKNOWN',n),
        }

    def snapshot(self):
        try:
            now=time.time()
            with closing(self._connect()) as conn:
                self._seed_missing_rows(conn, now)
                conn.commit()
                rows = conn.execute("SELECT music_status,COUNT(*) n FROM history_media_intelligence GROUP BY music_status").fetchall()
                counts = {str(r["music_status"]): int(r["n"] or 0) for r in rows}
                total = int(conn.execute("SELECT COUNT(*) FROM history_source_media").fetchone()[0] or 0)
                classified = sum(counts.get(x, 0) for x in ("HAS_MUSIC", "NO_MUSIC", "UNKNOWN"))
                failed = counts.get("SCAN_FAILED", 0)
                processed = classified + failed
                pending = max(0, total - processed)
                last_classified = conn.execute("""
                    SELECT mi.asset_key,mi.music_status,mi.music_confidence,mi.music_ratio,
                           mi.scanned_at,mi.attempted_at,s.title
                    FROM history_media_intelligence mi
                    JOIN history_source_media s ON s.asset_key=mi.asset_key
                    WHERE mi.scanned_at>0 ORDER BY mi.scanned_at DESC LIMIT 1
                """).fetchone()
                last_processed = conn.execute("""
                    SELECT mi.asset_key,mi.music_status,mi.music_confidence,mi.music_ratio,
                           mi.scanned_at,mi.attempted_at,mi.failure_kind,mi.last_error,mi.updated_at,s.title
                    FROM history_media_intelligence mi
                    JOIN history_source_media s ON s.asset_key=mi.asset_key
                    WHERE mi.music_status IN ('HAS_MUSIC','NO_MUSIC','UNKNOWN','SCAN_FAILED')
                    ORDER BY mi.updated_at DESC LIMIT 1
                """).fetchone()
                failure_rows = conn.execute("""
                    SELECT COALESCE(NULLIF(failure_kind,''),'OTHER') kind,COUNT(*) n
                    FROM history_media_intelligence
                    WHERE music_status='SCAN_FAILED'
                    GROUP BY COALESCE(NULLIF(failure_kind,''),'OTHER')
                    ORDER BY n DESC,kind
                """).fetchall()
                retry_due = int(conn.execute("""
                    SELECT COUNT(*) FROM history_media_intelligence
                    WHERE music_status='SCAN_FAILED' AND next_retry_at<=?
                """,(now,)).fetchone()[0] or 0)
            failure_reasons={str(r["kind"]):int(r["n"] or 0) for r in failure_rows}
            last_processed_payload=dict(last_processed) if last_processed else None
            return {
                "total": total,
                "scanned": processed,
                "processed": processed,
                "classified": classified,
                "pending": pending,
                "hasMusic": counts.get("HAS_MUSIC", 0),
                "noMusic": counts.get("NO_MUSIC", 0),
                "unknown": counts.get("UNKNOWN", 0),
                "failed": failed,
                "retryDue": retry_due,
                "failureReasons": failure_reasons,
                "last": dict(last_classified) if last_classified else None,
                "lastProcessed": last_processed_payload,
                "lastProcessedAt": float((last_processed_payload or {}).get("updated_at") or 0),
                "scanVersion": MUSIC_SCAN_VERSION,
            }
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}", "scanVersion": MUSIC_SCAN_VERSION}


class MusicDetector:
    """Conservative sustained-music detector using bounded PCM samples."""

    def __init__(self, ffmpeg=None, ytdlp=None, deno=None):
        self.ffmpeg = ffmpeg or shutil.which("ffmpeg")
        self.ytdlp = ytdlp or shutil.which("yt-dlp")
        self.deno = deno or shutil.which("deno")
        self._dependency_cache = None
        self._last_source_details = {}

    @staticmethod
    def _tool_version(path, args=("--version",), timeout=5):
        if not path:
            return ""
        try:
            proc=subprocess.run([path,*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
            text=(proc.stdout or proc.stderr or "").strip().splitlines()
            return text[0][:120] if proc.returncode==0 and text else ""
        except Exception:
            return ""

    def dependency_status(self):
        if self._dependency_cache is None:
            self._dependency_cache={
                "ffmpeg": bool(self.ffmpeg),
                "ytDlp": bool(self.ytdlp),
                "deno": bool(self.deno),
                "ytDlpVersion": self._tool_version(self.ytdlp),
                "denoVersion": self._tool_version(self.deno, ("--version",)),
            }
        return dict(self._dependency_cache)

    @staticmethod
    def _youtube_id(row):
        asset = row.get("asset") or {}
        for key in ("youtubeId", "videoId"):
            value = asset.get(key)
            if value:
                return str(value)
        provider = str(row.get("provider") or "").lower()
        provider_id = str(row.get("provider_media_id") or "")
        if "youtube" in provider and provider_id:
            return provider_id
        url = str(asset.get("externalUrl") or row.get("canonical_url") or "")
        if "youtu" in url:
            try:
                parsed = urllib.parse.urlparse(url)
                if parsed.hostname and "youtu.be" in parsed.hostname:
                    return parsed.path.strip("/").split("/")[0]
                return (urllib.parse.parse_qs(parsed.query).get("v") or [""])[0]
            except Exception:
                return ""
        return ""

    def _yt_base_args(self):
        args=[self.ytdlp,"--no-playlist","--no-warnings","--quiet"]
        # v4.5.5: yt-dlp now requires an external JavaScript runtime for full
        # YouTube format availability. Deno is provisioned on the VM and is the
        # recommended/default runtime; keep the argument explicit for diagnostics.
        if self.deno:
            args.extend(["--js-runtimes",f"deno:{self.deno}"])
        return args

    @staticmethod
    def _format_score(fmt):
        audio_only = str(fmt.get("vcodec") or "none") == "none"
        acodec = str(fmt.get("acodec") or "none")
        has_audio = acodec not in ("","none")
        protocol = str(fmt.get("protocol") or "").lower()
        direct_http = protocol.startswith("http") or protocol in ("https","m3u8_native","m3u8")
        return (1 if has_audio else 0, 1 if audio_only else 0, 1 if direct_http else 0,
                float(fmt.get("abr") or fmt.get("tbr") or 0), float(fmt.get("asr") or 0))

    def _youtube_inventory_fallback(self, target):
        proc=subprocess.run(
            [*self._yt_base_args(),"--skip-download","--dump-single-json","-f","all",target],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=YTDLP_TIMEOUT_SECONDS,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp inventory failed: {(proc.stderr or proc.stdout).strip()[:420]}")
        try:
            payload=json.loads(proc.stdout or "{}")
        except Exception as exc:
            raise RuntimeError(f"yt-dlp inventory JSON invalid: {exc}")
        formats=[x for x in (payload.get("formats") or []) if isinstance(x,dict) and str(x.get("url") or "").startswith(("https://","http://"))]
        audio=[x for x in formats if str(x.get("acodec") or "none") not in ("","none")]
        if not audio:
            raise RuntimeError("yt-dlp inventory contains no audio-capable format")
        chosen=max(audio,key=self._format_score)
        self._last_source_details={
            "youtubeResolver":"inventory-fallback",
            "youtubeFormatId":str(chosen.get("format_id") or ""),
            "youtubeFormatCount":len(formats),
            "youtubeAudioFormatCount":len(audio),
        }
        return str(chosen.get("url") or "")

    def _resolve_youtube_audio_url(self, youtube_id):
        if not self.ytdlp:
            raise RuntimeError("yt-dlp is required for YouTube media intelligence")
        target=f"https://www.youtube.com/watch?v={youtube_id}"
        self._last_source_details={"youtubeResolver":"primary"}
        proc=subprocess.run(
            [*self._yt_base_args(),"-f","bestaudio/best","-g",target],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=YTDLP_TIMEOUT_SECONDS,
        )
        url=next((line.strip() for line in (proc.stdout or "").splitlines() if line.strip().startswith(("https://","http://"))),"")
        if proc.returncode==0 and url:
            return url
        primary_error=(proc.stderr or proc.stdout or "").strip()[:420]
        # Do not turn a selector miss into a database failure. Inventory every
        # available format and choose the best audio-capable direct URL ourselves.
        try:
            return self._youtube_inventory_fallback(target)
        except Exception as fallback_exc:
            raise RuntimeError(f"yt-dlp audio URL failed: {primary_error}; fallback: {fallback_exc}")

    def _source_url(self, row):
        asset = row.get("asset") or {}
        self._last_source_details={}
        youtube_id = self._youtube_id(row)
        if youtube_id:
            return self._resolve_youtube_audio_url(youtube_id), "youtube"
        for value in (asset.get("mediaUrl"), row.get("canonical_url"), asset.get("url")):
            text = str(value or "").strip()
            if text.startswith(("https://", "http://")):
                return text, "direct"
        raise RuntimeError("no analyzable media URL")

    @staticmethod
    def _offsets(duration, count=DEFAULT_SAMPLE_COUNT):
        duration = max(0.0, float(duration or 0))
        count = max(2, int(count))
        if duration <= DEFAULT_SAMPLE_SECONDS + 1:
            return [0.0]
        if duration > 0:
            usable = max(0.0, duration - DEFAULT_SAMPLE_SECONDS - 1.0)
            fractions = (0.04, 0.28, 0.58, 0.82, 0.94, 0.68)[:count]
            return sorted({round(min(usable, max(0.0, usable * f)), 2) for f in fractions})
        return [0.0, 35.0, 90.0, 180.0][:count]

    def _decode_sample(self, source, offset):
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg is required for media intelligence")
        cmd = [
            self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-ss", f"{max(0.0, offset):.2f}", "-i", source,
            "-t", f"{DEFAULT_SAMPLE_SECONDS:.2f}", "-vn", "-sn", "-dn",
            "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1",
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=FFMPEG_TIMEOUT_SECONDS)
        if proc.returncode != 0 and not proc.stdout:
            raise RuntimeError(f"ffmpeg sample failed: {proc.stderr.decode('utf-8','replace')[:300]}")
        return proc.stdout

    @staticmethod
    def _goertzel_power(samples, freq):
        n = len(samples)
        if n < 32:
            return 0.0
        omega = 2.0 * math.pi * float(freq) / SAMPLE_RATE
        coeff = 2.0 * math.cos(omega)
        s_prev = 0.0
        s_prev2 = 0.0
        for value in samples:
            x = float(value) / 32768.0
            s = x + coeff * s_prev - s_prev2
            s_prev2 = s_prev
            s_prev = s
        return max(0.0, s_prev2 * s_prev2 + s_prev * s_prev - coeff * s_prev * s_prev2) / max(1, n * n)

    @classmethod
    def analyze_pcm(cls, pcm_bytes):
        values = array.array("h")
        values.frombytes(pcm_bytes[: len(pcm_bytes) - (len(pcm_bytes) % 2)])
        if sys.byteorder != "little":
            values.byteswap()
        if not values:
            return {"activeFrames": 0, "tonalFrames": 0, "musicRatio": 0.0, "consecutiveTonal": 0, "rmsMean": 0.0}
        active = 0
        tonal = 0
        consecutive = 0
        longest = 0
        rms_total = 0.0
        frame_count = 0
        for start in range(0, len(values) - FRAME_SAMPLES + 1, FRAME_SAMPLES):
            frame = values[start:start + FRAME_SAMPLES]
            frame_count += 1
            mean_sq = sum((float(x) / 32768.0) ** 2 for x in frame) / len(frame)
            rms = math.sqrt(max(0.0, mean_sq))
            rms_total += rms
            if rms < 0.006:
                consecutive = 0
                continue
            active += 1
            powers = [cls._goertzel_power(frame, f) for f in ANALYSIS_FREQUENCIES]
            total = sum(powers)
            if total <= 1e-12:
                consecutive = 0
                continue
            top = sorted(powers, reverse=True)
            concentration = sum(top[:3]) / total
            is_tonal = concentration >= 0.56 and rms >= 0.009
            if is_tonal:
                tonal += 1
                consecutive += 1
                longest = max(longest, consecutive)
            else:
                consecutive = 0
        ratio = tonal / active if active else 0.0
        return {
            "activeFrames": active,
            "tonalFrames": tonal,
            "musicRatio": ratio,
            "consecutiveTonal": longest,
            "rmsMean": rms_total / max(1, frame_count),
        }

    @classmethod
    def classify_features(cls, feature_sets, scanned_seconds=0.0, title=""):
        active = sum(int(x.get("activeFrames") or 0) for x in feature_sets)
        tonal = sum(int(x.get("tonalFrames") or 0) for x in feature_sets)
        ratio = tonal / active if active else 0.0
        longest = max([int(x.get("consecutiveTonal") or 0) for x in feature_sets] or [0])
        sample_music = sum(1 for x in feature_sets if float(x.get("musicRatio") or 0) >= 0.35 and int(x.get("activeFrames") or 0) >= 4)
        title_hint = bool(re.search(r"\b(music|soundtrack|song|remix|anthem|mic'?d up)\b", str(title or ""), re.I))
        if active == 0:
            return MusicResult("NO_MUSIC", 0.97, 0.0, False, scanned_seconds, {"reason": "no-active-audio", "samples": feature_sets})
        if title_hint or ratio >= 0.42 or sample_music >= max(1, math.ceil(len(feature_sets) / 2)) or longest >= 5:
            confidence = min(0.99, 0.66 + max(0.0, ratio - 0.30) * 0.75 + min(0.18, longest * 0.02))
            return MusicResult("HAS_MUSIC", confidence, ratio, True, scanned_seconds,
                               {"reason": "sustained-tonal-audio", "samples": feature_sets, "titleHint": title_hint})
        if active >= 12 and ratio <= 0.08 and longest <= 1 and sample_music == 0:
            confidence = min(0.96, 0.74 + min(0.20, (0.08 - ratio) * 2.0) + min(0.08, active / 300.0))
            return MusicResult("NO_MUSIC", confidence, ratio, False, scanned_seconds,
                               {"reason": "sustained-nonmusical-audio", "samples": feature_sets})
        confidence = min(0.80, 0.45 + abs(ratio - 0.20))
        return MusicResult("UNKNOWN", confidence, ratio, True, scanned_seconds,
                           {"reason": "ambiguous-audio-conservative-yield", "samples": feature_sets})

    def analyze(self, row):
        source, source_kind = self._source_url(row)
        features = []
        decoded_seconds = 0.0
        errors = []
        for offset in self._offsets(row.get("duration_seconds")):
            try:
                pcm = self._decode_sample(source, offset)
                if not pcm:
                    continue
                decoded_seconds += len(pcm) / 2.0 / SAMPLE_RATE
                feature = self.analyze_pcm(pcm)
                feature["offset"] = offset
                features.append(feature)
            except subprocess.TimeoutExpired:
                errors.append(f"offset {offset}: timeout")
            except Exception as exc:
                errors.append(f"offset {offset}: {type(exc).__name__}: {exc}")
        if not features:
            raise RuntimeError("no audio sample decoded" + (f" ({'; '.join(errors[:3])})" if errors else ""))
        result = self.classify_features(features, decoded_seconds, row.get("title") or "")
        result.details.update({
            "sourceKind": source_kind,
            "sampleCount": len(features),
            "sampleSeconds": round(decoded_seconds, 2),
            "errors": errors[:4],
            "detector": "bounded-goertzel-v1",
            **dict(self._last_source_details or {}),
        })
        return result


class MediaIntelligenceWorker:
    def __init__(self, db_path, *, pause_reason=None, beat=None, log=None, name="media-intelligence"):
        self.store = MediaIntelligenceStore(db_path)
        self.detector = MusicDetector()
        self.pause_reason = pause_reason or (lambda: "")
        self.beat = beat or (lambda *args, **kwargs: None)
        self.log = log or (lambda *args, **kwargs: None)
        self.name = str(name)
        self.owner = f"{os.getpid()}:{self.name}"
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._active_asset = ""
        self._active_title = ""
        self._started_at = 0.0
        self._last_progress = 0.0
        self._last_foreground_scan = 0.0
        self._last_error = ""

    def start(self):
        if self._thread and self._thread.is_alive():
            return self._thread
        self._started_at = time.time()
        # Do not start a background enrichment request during the first moments of
        # foreground playback. The first active-playback trickle waits one full interval.
        self._last_foreground_scan = self._started_at
        self._thread = threading.Thread(target=self._run, name="sbb-media-intelligence", daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        self._stop.set(); self._wake.set()

    def wake(self):
        self._wake.set()

    def _wait(self, seconds):
        self._wake.wait(max(0.0,float(seconds or 0))); self._wake.clear()

    def snapshot(self):
        snap = self.store.snapshot()
        snap.update({
            "alive": bool(self._thread and self._thread.is_alive()),
            "activeAsset": self._active_asset,
            "activeTitle": self._active_title,
            "startedAt": self._started_at,
            "lastProgress": max(float(self._last_progress or 0), float(snap.get("lastProcessedAt") or 0)),
            "foregroundTrickleSeconds": MUSIC_FOREGROUND_TRICKLE_SECONDS,
            "lastError": self._last_error,
            "dependencies": self.detector.dependency_status(),
        })
        return snap

    def _run(self):
        deps = self.detector.dependency_status()
        self.log(self.name, "INFO", f"Media Intelligence worker starting • ffmpeg={deps['ffmpeg']} yt-dlp={deps['ytDlp']}")
        while not self._stop.is_set():
            try:
                reason = str(self.pause_reason() or "")
                priority = self.store.priority_request_level()
                foreground_trickle = False
                if reason == "playback-priority":
                    # Endurance/playback-priority remains a hard bandwidth fence.
                    # Only an explicit SCAN CURRENT may cross it.
                    if priority >= 900:
                        reason = ""
                elif reason == "active-media":
                    if priority >= 900:
                        reason = ""
                    elif time.time() - self._last_foreground_scan >= MUSIC_FOREGROUND_TRICKLE_SECONDS:
                        # Normal viewing no longer starves the historical enrichment backlog.
                        # Permit one bounded scan per throttle interval and then yield again.
                        reason = ""
                        foreground_trickle = True
                if reason:
                    self.beat(self.name, phase=f"paused:{reason}", current="", progress=False, blocked=True)
                    self._wait(3.0)
                    continue
                deps = self.detector.dependency_status()
                if not deps["ffmpeg"]:
                    self._last_error = "ffmpeg unavailable"
                    self.beat(self.name, phase="dependency-missing:ffmpeg", current="", progress=False, blocked=True)
                    self._wait(60.0)
                    continue
                row = self.store.claim_next(self.owner)
                if not row:
                    self._active_asset = ""
                    self.beat(self.name, phase="sleeping:queue-empty", current="", progress=False)
                    self._wait(MUSIC_WORKER_IDLE_SECONDS)
                    continue
                self._active_asset = str(row.get("asset_key") or "")
                self._active_title = str(row.get("title") or "")[:180]
                self.beat(self.name, phase="analyzing:foreground-trickle" if foreground_trickle else "analyzing", current=f"{self._active_asset} • {row.get('title','')[:90]}", progress=False)
                try:
                    result = self.detector.analyze(row)
                    self.store.complete(self._active_asset, result)
                    self._last_progress = time.time()
                    self._last_error = ""
                    self.beat(self.name, phase="saved", current=self._active_asset, progress=True)
                    self.log(self.name, "INFO",
                             f"{result.status} confidence={result.confidence:.2f} music={result.ratio:.2f} • {row.get('title','')[:140]}")
                except Exception as exc:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    retry = self.store.fail(self._active_asset, exc)
                    self._last_progress = time.time()
                    self.beat(self.name, phase="scan-failed", current=self._active_asset, progress=True)
                    self.log(self.name, "WARN", f"scan failed • retry in {max(0,int(retry-time.time()))}s • {self._last_error}")
                finally:
                    if foreground_trickle:
                        self._last_foreground_scan = time.time()
                    self._active_asset = ""
                    self._active_title = ""
                self._wait(MUSIC_WORKER_BALANCED_PAUSE)
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self.log(self.name, "ERROR", self._last_error)
                self.beat(self.name, phase="worker-error", current="", progress=False)
                self._wait(15.0)


_INSTALL_LOCK = threading.Lock()
_INSTALL_STARTED = False
_WORKER = None


def schedule_media_intelligence_install():
    """Attach the worker after server.py finishes constructing its globals."""
    global _INSTALL_STARTED
    with _INSTALL_LOCK:
        if _INSTALL_STARTED:
            return
        _INSTALL_STARTED = True

    def install():
        global _WORKER
        deadline = time.time() + 90
        main = None
        repo = None
        while time.time() < deadline:
            main = sys.modules.get("__main__")
            repo = getattr(main, "HISTORY_REPOSITORY", None) if main else None
            if repo is not None and getattr(repo, "path", None):
                break
            time.sleep(0.25)
        if repo is None:
            return

        def pause_reason():
            try:
                mode = str(main._history_work_mode() or "balanced")
                if mode == "playback":
                    return "playback-priority"
            except Exception:
                pass
            try:
                last_media = float((getattr(main, "CLIENT_ACTIVITY_STATE", {}) or {}).get("lastMedia") or 0)
                if last_media and time.time() - last_media < MUSIC_ACTIVE_MEDIA_GRACE_SECONDS:
                    return "active-media"
            except Exception:
                pass
            return ""

        def beat(name, phase=None, current=None, progress=False, blocked=False):
            try:
                fn = getattr(main, "_history_worker_beat", None)
                if fn:
                    fn(name, phase=phase, current=current, progress=progress, blocked=blocked)
            except Exception:
                pass

        def log(name, level, message):
            try:
                fn = getattr(main, "_history_console_log", None)
                if fn:
                    fn(name, level, message)
                else:
                    print(f"[SBB {name}] {level} {message}", flush=True)
            except Exception:
                pass

        try:
            health = getattr(main, "HISTORY_WORKER_HEALTH", None)
            if isinstance(health, dict):
                health.setdefault("media-intelligence", {
                    "heartbeat": 0.0, "phase": "starting", "lastProgress": 0.0,
                    "iterations": 0, "blocked": 0, "current": ""
                })
            _WORKER = MediaIntelligenceWorker(repo.path, pause_reason=pause_reason, beat=beat, log=log)
            setattr(main, "MEDIA_INTELLIGENCE_WORKER", _WORKER)
            # Extend the existing thread-health surface without changing server.py.
            # Search Console / milestone diagnostics can therefore see the crawler
            # beside the established history workers.
            original_threads = getattr(main, "_history_threads_status", None)
            if callable(original_threads) and not getattr(original_threads, "__sbb_media_intelligence_wrapped__", False):
                def threads_with_media_intelligence():
                    rows = list(original_threads() or [])
                    if not any(str(x.get("name") or "")=="sbb-media-intelligence" for x in rows if isinstance(x, dict)):
                        rows.append({"name":"sbb-media-intelligence","alive":bool(_WORKER and _WORKER._thread and _WORKER._thread.is_alive())})
                    return rows
                threads_with_media_intelligence.__sbb_media_intelligence_wrapped__ = True
                setattr(main, "_history_threads_status", threads_with_media_intelligence)
            _WORKER.start()
        except Exception as exc:
            try:
                log("media-intelligence", "ERROR", f"worker install failed: {type(exc).__name__}: {exc}")
            except Exception:
                pass

    threading.Thread(target=install, name="sbb-media-intelligence-install", daemon=True).start()


def wake_worker():
    if _WORKER:
        try: _WORKER.wake(); return True
        except Exception: return False
    return False

def worker_snapshot():
    return _WORKER.snapshot() if _WORKER else {"alive": False, "scanVersion": MUSIC_SCAN_VERSION}

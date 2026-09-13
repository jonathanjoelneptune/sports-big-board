"""v6.1.16 R25 Media Repair yield controls."""
from __future__ import annotations

import json
from contextlib import closing

from .media_team_sources_v6116 import TeamSourceRegistry as SeededTeamSourceRegistry

GENERATION = "R25-REPAIR-YIELD"
DEFAULT_REJECTION_TTL = 30 * 86400
DEFAULT_HARD_REJECTION_TTL = 90 * 86400
DEFAULT_PROVIDER_CIRCUIT_SECONDS = 15 * 60


def install(ns):
    Store = ns["AuditStore"]
    Engine = ns["MediaRepairEngine"]
    _now = ns["_now"]
    _hard = ns["_hard_media_failure_reason"]
    LOCAL_LIMIT = ns["REPAIR_LOCAL_CATALOG_LIMIT"]
    CANDIDATE_LIMIT = ns["REPAIR_CANDIDATE_LIMIT"]

    rejection_ttl = max(86400, int(ns["os"].environ.get(
        "SBB_MEDIA_REPAIR_REJECTION_MEMORY_SECONDS", DEFAULT_REJECTION_TTL)))
    hard_ttl = max(rejection_ttl, int(ns["os"].environ.get(
        "SBB_MEDIA_REPAIR_HARD_REJECTION_MEMORY_SECONDS", DEFAULT_HARD_REJECTION_TTL)))
    provider_cooldown = max(60, int(ns["os"].environ.get(
        "SBB_MEDIA_REPAIR_PROVIDER_CIRCUIT_SECONDS", DEFAULT_PROVIDER_CIRCUIT_SECONDS)))

    # Priority 2: keep R24's queue/callback machinery, replace organic-only
    # resolution with the curated first-party seed overlay.
    ns["TeamSourceRegistry"] = SeededTeamSourceRegistry

    old_ready = Store.repair_schema_ready
    old_ensure = Store.ensure_repair_schema
    old_seed = Store.seed_repair_queue

    def ready(self):
        if not old_ready(self):
            return False
        try:
            with closing(self.connect(timeout=2)) as conn:
                names = {str(r[0]) for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND "
                    "name IN ('history_media_repair_rejection_memory','history_media_repair_strategy_activation')"
                ).fetchall()}
            return names == {
                "history_media_repair_rejection_memory",
                "history_media_repair_strategy_activation",
            }
        except Exception:
            return False

    def ensure(self):
        current = Store.repair_schema_ready
        try:
            Store.repair_schema_ready = old_ready
            old_ensure(self)
        finally:
            Store.repair_schema_ready = current
        with self.lock, closing(self.connect(timeout=2)) as conn:
            conn.executescript("""
              CREATE TABLE IF NOT EXISTS history_media_repair_rejection_memory (
                canonical_event_key TEXT NOT NULL,
                asset_key TEXT NOT NULL,
                transport_key TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '',
                source_stage TEXT NOT NULL DEFAULT '',
                rejection_count INTEGER NOT NULL DEFAULT 1,
                first_rejected_at REAL NOT NULL DEFAULT 0,
                last_rejected_at REAL NOT NULL DEFAULT 0,
                expires_at REAL NOT NULL DEFAULT 0,
                details_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(canonical_event_key,asset_key,transport_key)
              );
              CREATE INDEX IF NOT EXISTS idx_media_repair_rejection_memory_event
                ON history_media_repair_rejection_memory(canonical_event_key,expires_at);
              CREATE TABLE IF NOT EXISTS history_media_repair_strategy_activation (
                canonical_event_key TEXT NOT NULL,
                strategy TEXT NOT NULL,
                activated_at REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(canonical_event_key,strategy)
              );
            """)
            conn.commit()
        return True

    def rejection_memory(self, event_key):
        self.ensure_repair_schema()
        with closing(self.connect(timeout=2)) as conn:
            rows = conn.execute(
                "SELECT * FROM history_media_repair_rejection_memory "
                "WHERE canonical_event_key=? AND expires_at>?",
                (str(event_key or ""), _now()),
            ).fetchall()
        return {
            (str(r["asset_key"] or ""), str(r["transport_key"] or "")): dict(r)
            for r in rows
        }

    def remember_rejections(self, event_key, rows):
        if not rows:
            return {"written": 0}
        self.ensure_repair_schema()
        now = _now()
        written = 0
        with self.lock, closing(self.connect(timeout=2)) as conn:
            for row in rows:
                asset_key = str(row.get("assetKey") or "")
                if not asset_key:
                    continue
                ttl = max(60, int(row.get("ttlSeconds") or rejection_ttl))
                conn.execute(
                    """INSERT INTO history_media_repair_rejection_memory(
                         canonical_event_key,asset_key,transport_key,reason,source_stage,
                         rejection_count,first_rejected_at,last_rejected_at,expires_at,details_json)
                       VALUES(?,?,?,?,?,1,?,?,?,?)
                       ON CONFLICT(canonical_event_key,asset_key,transport_key) DO UPDATE SET
                         reason=excluded.reason,source_stage=excluded.source_stage,
                         rejection_count=history_media_repair_rejection_memory.rejection_count+1,
                         last_rejected_at=excluded.last_rejected_at,
                         expires_at=MAX(history_media_repair_rejection_memory.expires_at,excluded.expires_at),
                         details_json=excluded.details_json""",
                    (
                        str(event_key or ""), asset_key, str(row.get("transportKey") or ""),
                        str(row.get("reason") or "")[:500], str(row.get("stage") or "")[:120],
                        now, now, now + ttl,
                        json.dumps(row.get("details") or {}, separators=(",", ":"), default=str),
                    ),
                )
                written += 1
            conn.commit()
        return {"written": written}

    def seed_queue(self):
        result = dict(old_seed(self) or {})
        self.ensure_repair_schema()
        now = _now()
        with self.lock, closing(self.connect(timeout=2)) as conn:
            rows = conn.execute(
                """SELECT id,canonical_event_key FROM history_media_repair_queue r
                   WHERE health IN ('DEGRADED','UNPLAYABLE','NO_MEDIA')
                     AND state='WAITING_RETRY'
                     AND NOT EXISTS (
                       SELECT 1 FROM history_media_repair_strategy_activation a
                       WHERE a.canonical_event_key=r.canonical_event_key
                         AND a.strategy='R25_REPAIR_YIELD')"""
            ).fetchall()
            for row in rows:
                conn.execute(
                    """UPDATE history_media_repair_queue
                       SET state='PENDING',next_retry_at=0,updated_at=?,last_error='',
                           reason='R25 repair-yield strategy upgrade'
                       WHERE id=?""",
                    (now, int(row["id"])),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO history_media_repair_strategy_activation"
                    "(canonical_event_key,strategy,activated_at) VALUES(?,'R25_REPAIR_YIELD',?)",
                    (str(row["canonical_event_key"]), now),
                )
            conn.commit()
        result["r25StrategyRequeued"] = len(rows)
        return result

    Store.repair_schema_ready = ready
    Store.ensure_repair_schema = ensure
    Store.repair_rejection_memory = rejection_memory
    Store.remember_repair_rejections = remember_rejections
    Store.seed_repair_queue = seed_queue

    old_init = Engine.__init__
    old_probe = Engine._probe
    old_certify = Engine._certify_candidates
    old_deep = Engine._deep_catalog_candidates
    old_fallback = Engine._youtube_fallback_candidates
    old_discover = Engine._discover_once
    old_retry = Engine._retry_at

    def transport_key(self, asset):
        asset = asset or {}
        return "|".join((
            str(asset.get("url") or ""),
            str(asset.get("youtubeId") or ""),
            str(asset.get("provider") or ""),
            str(asset.get("tier") or ""),
        ))

    def memory(self, event_key):
        try:
            return self.store.repair_rejection_memory(event_key)
        except Exception:
            return {}

    def remember(self, job, asset, reason, stage, hard=False):
        key = str((asset or {}).get("assetKey") or "")
        if not key and (asset or {}).get("youtubeId"):
            key = "yt:" + str(asset.get("youtubeId"))
        if not key:
            return
        result = self._write(
            "remember deterministic repair rejection", "remember_repair_rejections",
            str(job.get("canonical_event_key") or ""),
            [{
                "assetKey": key,
                "transportKey": self._rejection_transport_key(asset),
                "reason": str(reason or "REJECTED"),
                "stage": str(stage or ""),
                "ttlSeconds": hard_ttl if hard else rejection_ttl,
            }],
            event_key=str(job.get("canonical_event_key") or ""),
        )
        self.stats["rejectionMemoryWrites"] += int((result or {}).get("written") or 0)

    def filter_memory(self, job, candidates):
        mem = self._rejection_memory(str(job.get("canonical_event_key") or ""))
        kept = []
        skipped = 0
        for asset in list(candidates or []):
            key = str(asset.get("assetKey") or "")
            if not key and asset.get("youtubeId"):
                key = "yt:" + str(asset.get("youtubeId"))
            if (key, self._rejection_transport_key(asset)) in mem:
                skipped += 1
            else:
                kept.append(asset)
        self.stats["rejectionMemorySkips"] += skipped
        return kept, skipped

    def engine_init(self, *args, **kwargs):
        old_init(self, *args, **kwargs)
        self.provider_discovery_retry_at = 0.0
        self.provider_discovery_reason = ""
        for name in (
            "rejectionMemorySkips", "rejectionMemoryWrites",
            "stageSkipsQuota", "stageSkipsCircuit",
        ):
            self.stats.setdefault(name, 0)

    def probe(self, job, asset, phase="CERTIFYING"):
        result = old_probe(self, job, asset, phase=phase)
        reason = str((result or {}).get("reason") or "")
        if result and (result.get("hard") or _hard(reason)):
            self._remember_rejection(
                job, asset, "HARD_PLAYBACK:" + (reason or "UNKNOWN"), phase, True)
        return result

    def certify(self, job, candidates, target, reason, *, tested=None,
                phase="CERTIFY_REPAIR_CANDIDATE"):
        filtered, skipped = self._filter_rejection_memory(job, candidates)
        if skipped:
            self._trace(
                "INFO", "Persistent rejection memory skipped unchanged repair candidates",
                event=job.get("canonical_event_key") or "", skipped=skipped, phase=phase)
        return old_certify(
            self, job, filtered, target, reason, tested=tested, phase=phase)

    def deep_catalog(self, job, known):
        context = self.store.repair_event_context(job["canonical_event_key"])
        if not context:
            return []
        away_terms, home_terms = self._event_terms(context)
        rows = self.store.repair_catalog_search(
            away_terms, home_terms, context["event_date"], LOCAL_LIMIT)
        mem = self._rejection_memory(str(job["canonical_event_key"]))
        accepted = []
        remember_rows = []
        duplicates = rejected = memory_skipped = 0
        for asset in rows:
            key = str(asset.get("assetKey") or "")
            if not key or key in known:
                duplicates += 1
                continue
            transport = self._rejection_transport_key(asset)
            if (key, transport) in mem:
                memory_skipped += 1
                continue
            failure = str(asset.get("runtimeFailureReason") or "")
            if str(asset.get("runtimeState") or "").upper() == "FAILED" and _hard(failure):
                rejected += 1
                remember_rows.append({
                    "assetKey": key, "transportKey": transport,
                    "reason": "HARD_FAILURE:" + failure, "stage": "LOCAL_CATALOG",
                    "ttlSeconds": hard_ttl,
                })
                continue
            conf = self._match_candidate(
                context, asset.get("title") or "",
                str((asset.get("item") or {}).get("description") or ""),
                asset.get("publishedAt") or "", strict_date=True)
            if conf < .88:
                rejected += 1
                remember_rows.append({
                    "assetKey": key, "transportKey": transport,
                    "reason": f"EVENT_MATCH_CONFIDENCE:{conf:.3f}",
                    "stage": "LOCAL_CATALOG", "ttlSeconds": rejection_ttl,
                })
                continue
            asset = dict(asset)
            asset["repairConfidence"] = conf
            accepted.append(asset)
        if remember_rows:
            result = self._write(
                "remember local-catalog repair rejections", "remember_repair_rejections",
                str(job["canonical_event_key"]), remember_rows,
                event_key=str(job["canonical_event_key"]))
            self.stats["rejectionMemoryWrites"] += int((result or {}).get("written") or 0)
        self.stats["rejectionMemorySkips"] += memory_skipped
        accepted.sort(key=lambda a: (
            -float(a.get("repairConfidence") or 0),
            -self._candidate_score(a, str(job.get("target") or "ANY").upper()),
            str(a.get("assetKey") or "")))
        accepted = accepted[:CANDIDATE_LIMIT]
        if accepted:
            self._write(
                "associate deep-catalog repair candidates",
                "associate_existing_repair_candidates",
                int(job["id"]), str(job["canonical_event_key"]), accepted,
                source="R25_LOCAL_CATALOG", event_key=str(job["canonical_event_key"]))
            self.stats["localCatalogCandidates"] += len(accepted)
            self.stats["newCandidates"] += len(accepted)
        self._record_stage(
            job, "LOCAL_CATALOG", provider="CATALOG", results=len(rows),
            new=len(accepted), duplicates=duplicates, rejected=rejected,
            details={
                "rejectionMemorySkipped": memory_skipped,
                "rejectionMemoryWritten": len(remember_rows),
            })
        return accepted

    # Priority 3: consult the persisted YouTube gateway cooldown before making
    # another search.list call. Playlist/video metadata lanes remain independent.
    def youtube_fallback(self, job):
        state = self.youtube.status().get("search") or {}
        if not self.youtube.operation_available("search"):
            retry_at = float(state.get("resetAt") or 0)
            if not retry_at:
                retry_at = _now() + max(1, int(state.get("cooldownSeconds") or 0))
            self.stats["stageSkipsQuota"] += 1
            self._record_stage(
                job, "GENERIC_YOUTUBE_SEARCH", provider="YOUTUBE_SEARCH",
                results=0, new=0, quota_blocked=True, retry_at=retry_at,
                details={
                    "skipped": True, "gate": "YOUTUBE_SEARCH_COOLDOWN",
                    "quotaExhausted": bool(state.get("quotaExhausted")),
                    "lastError": str(state.get("lastError") or ""),
                })
            return {
                "candidates": [], "quotaBlocked": True, "retryAt": retry_at,
                "reason": "GATEWAY_COOLDOWN_SKIPPED", "skipped": True,
            }
        return old_fallback(self, job)

    # Priority 3: keep a local provider-transport circuit so a backend timeout or
    # reported exhaustive-discovery circuit is not re-requested for every game.
    def discover(self, job, pass_number):
        now = _now()
        if float(self.provider_discovery_retry_at or 0) > now:
            self.stats["stageSkipsCircuit"] += 1
            job["_providerRetryAt"] = float(self.provider_discovery_retry_at)
            return {
                "ok": False, "reason": "LOCAL_DISCOVERY_CIRCUIT_OPEN",
                "skipped": True, "retryAt": float(self.provider_discovery_retry_at),
                "circuitReason": self.provider_discovery_reason,
            }
        result = dict(old_discover(self, job, pass_number) or {})
        reason = str(result.get("reason") or "")
        payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
        retry_at = float(
            result.get("retryAt") or payload.get("retryAt") or
            ((payload.get("discoveryCircuit") or {}).get("retryAt")
             if isinstance(payload.get("discoveryCircuit"), dict) else 0) or 0)
        circuitish = (
            reason.startswith("DISCOVERY_TRANSPORT_")
            or "CIRCUIT" in reason.upper()
            or bool(payload.get("circuitOpen"))
            or retry_at > now)
        if result.get("ok"):
            self.provider_discovery_retry_at = 0.0
            self.provider_discovery_reason = ""
        elif circuitish:
            if not retry_at:
                retry_at = now + provider_cooldown
            self.provider_discovery_retry_at = max(
                float(self.provider_discovery_retry_at or 0), retry_at)
            self.provider_discovery_reason = reason or "PROVIDER_DISCOVERY_CIRCUIT"
            job["_providerRetryAt"] = self.provider_discovery_retry_at
            result["retryAt"] = self.provider_discovery_retry_at
        return result

    def retry_at(job):
        return max(
            float(old_retry(job)),
            float((job or {}).get("_providerRetryAt") or 0))

    Engine.__init__ = engine_init
    Engine._rejection_transport_key = transport_key
    Engine._rejection_memory = memory
    Engine._remember_rejection = remember
    Engine._filter_rejection_memory = filter_memory
    Engine._probe = probe
    Engine._certify_candidates = certify
    Engine._deep_catalog_candidates = deep_catalog
    Engine._youtube_fallback_candidates = youtube_fallback
    Engine._discover_once = discover
    Engine._retry_at = staticmethod(retry_at)

    ns["AUDIT_GENERATION"] = GENERATION
    return {
        "generation": GENERATION,
        "rejectionMemorySeconds": rejection_ttl,
        "hardRejectionMemorySeconds": hard_ttl,
        "providerCircuitSeconds": provider_cooldown,
    }

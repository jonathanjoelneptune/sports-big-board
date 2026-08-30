"""Sports Big Board v4.7.19 — owning-runtime recovery for catalog playback.

v4.7.18 added useful safety/compatibility layers, but three user-visible paths still
had stale owners underneath them:

* SPECIAL_EVENT media can be quarantined by the generic relationship repair before
  Day State sees the deterministic tournament proof.
* legacy Silver source rows can retain an explicit historical ``verifiedPlayable``
  proof while normalized ``validation_state`` still says CANDIDATE/EXTERNAL.
* CFB trusted-source persistence can update SQLite after Day State already cached the
  day, leaving the score ribbon on FIND until the historical cache expires.

This module installs LAST from ``sbb.__init__``.  It patches the methods that actually
own those runtime decisions, runs a bounded startup recovery, and invalidates affected
Day State snapshots.  It performs no destructive catalog migration and no broad
provider search of its own.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta
import json
import threading
import time

from .history_repository import HistoryRepository

VERSION = "4.7.19-runtime-path-repair-1"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False

_ORIGINAL_HYDRATE = None
_ORIGINAL_ROUNDUP_MEDIA = None
_ORIGINAL_REPAIR_EVENT_ASSOCIATIONS = None
_ORIGINAL_CFB_PERSIST = None


def _row_value(row, key, default=""):
    try:
        value = row[key]
    except Exception:
        try:
            value = row.get(key, default)
        except Exception:
            value = default
    return default if value is None else value


def _load_asset_json(row):
    try:
        raw = _row_value(row, "asset_json", "")
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _repair_transport(item):
    # Reuse the v4.7.18 local-only transport recovery when available.
    try:
        from . import history_readiness_repair as readiness
        return bool(readiness._repair_transport(item))
    except Exception:
        return bool(str((item or {}).get("youtubeId") or "").strip() or str((item or {}).get("mediaUrl") or "").strip())


def _hydrate_asset(row):
    """Honor explicit legacy playback proof without weakening FAILED quarantine."""
    item = _ORIGINAL_HYDRATE(row)
    legacy = _load_asset_json(row)
    runtime = str(_row_value(row, "runtime_state", item.get("runtimeCatalogState") or "UNKNOWN") or "UNKNOWN").upper()
    if runtime == "FAILED":
        return item

    has_transport = _repair_transport(item)
    legacy_verified = legacy.get("verifiedPlayable") is True
    legacy_embed = legacy.get("embedValidated") is True and bool(legacy.get("youtubeId") or legacy.get("externalUrl"))
    if has_transport and (legacy_verified or legacy_embed):
        item["verifiedPlayable"] = True
        item["legacyDatabasePlayable"] = True
        item["databaseVerifiedPlayable"] = True
        item["legacyValidationCompatibility"] = str(_row_value(row, "validation_state", "") or "CANDIDATE").upper()
    return item


def _roundup_media(self, date, league=None):
    """Preserve the repository's Silver relationship and restore explicit old proof."""
    rows = _ORIGINAL_ROUNDUP_MEDIA(self, date, league)
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("runtimeCatalogState") or "UNKNOWN").upper() == "FAILED":
            item["verifiedPlayable"] = False
            continue
        if item.get("legacyDatabasePlayable") and _repair_transport(item):
            item["verifiedPlayable"] = True
            item["databaseVerifiedPlayable"] = True
    return rows


def _invalidate_day_state(days):
    days = sorted({str(x or "")[:10] for x in (days or []) if len(str(x or "")) >= 10})
    if not days:
        return 0
    try:
        from . import day_state
        engine = getattr(day_state, "_ENGINE", None)
        if engine is None:
            return 0
        conn = None
        try:
            conn = engine.store._connect()
            conn.executemany("DELETE FROM day_state WHERE day=?", [(day,) for day in days])
            conn.commit()
        finally:
            if conn is not None:
                conn.close()
        for day in days:
            try:
                with engine.lock:
                    engine.cache.pop(day, None)
                    engine.last_build.pop(day, None)
            except Exception:
                pass
            try:
                engine.enqueue(day, priority=True)
            except Exception:
                pass
        return len(days)
    except Exception:
        return 0


def _special_method(item):
    method = str((item or {}).get("associationMethod") or "").strip().upper()
    if method.startswith("SPECIAL_EVENT_"):
        return method
    proof = (item or {}).get("sbbPreprovenAssociation")
    if isinstance(proof, dict):
        method = str(proof.get("associationMethod") or "").strip().upper()
        if method.startswith("SPECIAL_EVENT_"):
            return method
    return ""


def restore_special_event_links(repo):
    """Restore canonical special-event links that generic title repair cannot prove.

    v4.6.16 persisted the winning canonical key/method in both source JSON and the
    relationship row. Generic repair may later demote that source to OTHER because
    club-name matching cannot reproduce location-alias/game-number tournament proof.
    OTHER is therefore repairable when a persisted SPECIAL_EVENT_* relationship
    proves the exact canonical game. Collection/PLAYER scope remains fail-closed.
    """
    stats = {"checked": 0, "restored": 0, "alreadyAssigned": 0, "scopeRecovered": 0,
             "scopeRejected": 0, "conflicts": 0, "days": []}
    affected = set()
    now = time.time()
    with repo._lock, closing(repo._connect()) as conn:
        rows = conn.execute(
            """SELECT s.asset_key,s.scope,s.asset_json,s.catalog_state,s.validation_state,s.runtime_state,
                      em.canonical_event_key relationship_key,em.association_method relationship_method,
                      em.association_evidence relationship_evidence,em.association_confidence relationship_confidence,
                      em.association_state relationship_state
               FROM history_source_media s
               LEFT JOIN history_event_media em ON em.asset_key=s.asset_key
               WHERE s.asset_json LIKE '%SPECIAL_EVENT_%'
                  OR UPPER(COALESCE(em.association_method,'')) LIKE 'SPECIAL_EVENT_%'"""
        ).fetchall()
        seen = set()
        for row in rows:
            item = repo._load_obj(row["asset_json"])
            method = str(row["relationship_method"] or "").strip().upper() or _special_method(item)
            key = str(row["relationship_key"] or item.get("canonicalEventKey") or "").strip()
            identity = (str(row["asset_key"]), key)
            if identity in seen:
                continue
            seen.add(identity)
            if not method.startswith("SPECIAL_EVENT_") or not key or ":" not in key:
                continue
            stats["checked"] += 1
            normalized_scope = str(row["scope"] or "").upper()
            # Never resurrect a relationship after a newer classifier proved this
            # asset is collection/player content. OTHER is allowed because that is
            # the exact false demotion caused by generic special-event team matching.
            if normalized_scope in {"DAY_LEAGUE","WEEK_LEAGUE","ROUND_LEAGUE","SEASON_LEAGUE","PLAYER"}:
                stats["scopeRejected"] += 1
                continue
            event = conn.execute(
                "SELECT league,event_id,event_date FROM history_catalog_event WHERE canonical_event_key=?",
                (key,),
            ).fetchone()
            if not event:
                continue
            competing = conn.execute(
                """SELECT canonical_event_key FROM history_event_media
                   WHERE asset_key=? AND association_state='ASSIGNED' AND canonical_event_key<>?""",
                (row["asset_key"], key),
            ).fetchall()
            if competing:
                stats["conflicts"] += 1
                continue
            current = conn.execute(
                "SELECT association_state FROM history_event_media WHERE canonical_event_key=? AND asset_key=?",
                (key, row["asset_key"]),
            ).fetchone()
            if current and str(current["association_state"] or "").upper() == "ASSIGNED" and normalized_scope == "GAME":
                stats["alreadyAssigned"] += 1
                continue
            try:
                confidence = float(row["relationship_confidence"] or item.get("associationConfidence") or 0.995)
            except Exception:
                confidence = 0.995
            confidence = max(0.90, min(1.0, confidence))
            evidence = str(row["relationship_evidence"] or item.get("associationEvidence") or "v4.7.19 restored persisted SPECIAL_EVENT canonical proof")[:2000]
            conn.execute(
                """INSERT INTO history_event_media(
                     canonical_event_key,asset_key,association_state,association_confidence,
                     association_method,association_evidence,matcher_version,first_associated_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(canonical_event_key,asset_key) DO UPDATE SET
                     association_state='ASSIGNED',association_confidence=excluded.association_confidence,
                     association_method=excluded.association_method,association_evidence=excluded.association_evidence,
                     matcher_version=excluded.matcher_version,updated_at=excluded.updated_at""",
                (key, row["asset_key"], "ASSIGNED", confidence, method, evidence, 4719, now, now),
            )
            item["canonicalEventKey"] = key
            item["associationMethod"] = method
            item["associationConfidence"] = confidence
            item["associationEvidence"] = evidence
            item["mediaScope"] = "GAME"
            item["mediaScopeConfidence"] = max(float(item.get("mediaScopeConfidence") or 0), 0.995)
            item["mediaScopeReason"] = "SPECIAL_EVENT_CANONICAL_ASSOCIATION_RECOVERY"
            conn.execute(
                """UPDATE history_source_media SET scope='GAME',scope_confidence=MAX(scope_confidence,0.995),
                     scope_reason='SPECIAL_EVENT_CANONICAL_ASSOCIATION_RECOVERY',catalog_state='ASSIGNED',
                     quarantine_reason='',asset_json=?,updated_at=? WHERE asset_key=?""",
                (repo._dump_obj(item), now, row["asset_key"]),
            )
            if normalized_scope != "GAME":
                stats["scopeRecovered"] += 1
            conn.execute(
                """UPDATE history_assignment_review SET state='RESOLVED',updated_at=?
                   WHERE asset_key=? AND proposed_event_key=? AND state='QUARANTINED'""",
                (now, row["asset_key"], key),
            )
            stats["restored"] += 1
            affected.add(str(event["event_date"] or "")[:10])
        conn.commit()
    stats["days"] = sorted(x for x in affected if x)
    if affected:
        _invalidate_day_state(affected)
    return stats


def restore_silver_collection_links(repo):
    """Re-link legacy Silver source rows when only the collection edge was lost.

    This does not classify arbitrary source media. It requires persisted DAY_LEAGUE
    scope plus explicit Silver collection metadata from an earlier successful
    promotion, and a non-failed playback proof. The repair is idempotent.
    """
    stats={"checked":0,"restored":0,"alreadyLinked":0,"rejected":0,"days":[]}
    affected=set();now=time.time()
    with repo._lock, closing(repo._connect()) as conn:
        rows=conn.execute("""SELECT asset_key,scope,catalog_state,validation_state,runtime_state,asset_json,provider,provider_media_id,canonical_url
          FROM history_source_media WHERE scope='DAY_LEAGUE'""").fetchall()
        for row in rows:
            item=repo._load_obj(row["asset_json"])
            tier=str(item.get("collectionTier") or item.get("displayTier") or "").lower()
            approved=item.get("collectionPromotionApproved") is True
            period=str(item.get("collectionPeriodKey") or item.get("date") or item.get("sourceDate") or item.get("gameDate") or "")[:10]
            league=str(item.get("competitionId") or item.get("__sbbLeague") or item.get("league") or "").upper()
            kind=str(item.get("collectionKind") or "").upper()
            runtime=str(row["runtime_state"] or "UNKNOWN").upper()
            validation=str(row["validation_state"] or "CANDIDATE").upper()
            legacy_playable=item.get("verifiedPlayable") is True or item.get("embedValidated") is True
            stats["checked"]+=1
            if tier!="silver" and not approved:
                stats["rejected"]+=1;continue
            if not league or len(period)!=10 or not (period[:4].isdigit() and period[4]=='-' and period[7]=='-'):
                stats["rejected"]+=1;continue
            if kind not in {"DAILY_RECAP","TOP_PLAYS","BEST_GOALS","BEST_SAVES","SCORING_ROUNDUP","ROUNDUP"}:
                stats["rejected"]+=1;continue
            # Recover transport from normalized columns without requiring a full
            # SELECT s.* row or invoking hydration recursively while holding writer lock.
            if not item.get("provider"): item["provider"]=str(row["provider"] or "")
            if not item.get("providerMediaId"): item["providerMediaId"]=str(row["provider_media_id"] or "")
            if not item.get("canonicalUrl"): item["canonicalUrl"]=str(row["canonical_url"] or "")
            try:
                from . import history_readiness_repair as readiness
                if not item.get("youtubeId") and "YOUTUBE" in str(item.get("provider") or "").upper():
                    candidate=str(item.get("providerMediaId") or "").strip()
                    if readiness._YOUTUBE_ID_RE.fullmatch(candidate): item["youtubeId"]=candidate
                if not item.get("youtubeId"):
                    item["youtubeId"]=readiness._youtube_id_from_url(item.get("canonicalUrl") or item.get("externalUrl")) or item.get("youtubeId")
            except Exception:
                pass
            if runtime=="FAILED" or not _repair_transport(item) or not (validation=="VERIFIED" or legacy_playable):
                stats["rejected"]+=1;continue
            ckey=repo._collection_key("DAY_LEAGUE",league,period,kind)
            existing=conn.execute("SELECT 1 FROM history_collection_media WHERE collection_key=? AND asset_key=?",(ckey,row["asset_key"])).fetchone()
            if existing:
                stats["alreadyLinked"]+=1;continue
            conn.execute("""INSERT INTO history_collection(collection_key,scope,league,period_key,collection_kind,title,metadata_json,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(collection_key) DO UPDATE SET updated_at=excluded.updated_at""",
              (ckey,"DAY_LEAGUE",league,period,kind,f"{league} {period} {kind.replace('_',' ').title()}",repo._dump_obj({"restoredBy":"v4.7.19"}),now,now))
            conn.execute("""INSERT INTO history_collection_media(collection_key,asset_key,association_confidence,association_method,association_evidence,classifier_version,rank_hint,first_associated_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(collection_key,asset_key) DO UPDATE SET updated_at=excluded.updated_at""",
              (ckey,row["asset_key"],0.995,"V4719_LEGACY_SILVER_RESTORE","persisted Silver collection metadata",4719,450,now,now))
            conn.execute("UPDATE history_source_media SET catalog_state='ASSIGNED',quarantine_reason='',updated_at=? WHERE asset_key=?",(now,row["asset_key"]))
            stats["restored"]+=1;affected.add(period)
        conn.commit()
    stats["days"]=sorted(affected)
    return stats

def _repair_event_associations(self, matcher_version=None, force=False):
    kwargs = {"force": force}
    if matcher_version is not None:
        kwargs["matcher_version"] = matcher_version
    result = _ORIGINAL_REPAIR_EVENT_ASSOCIATIONS(self, **kwargs)
    recovery = restore_special_event_links(self)
    out = dict(result or {})
    out.update({
        "v4719SpecialChecked": recovery["checked"],
        "v4719SpecialRestored": recovery["restored"],
        "v4719SpecialConflicts": recovery["conflicts"],
        "v4719SpecialDays": recovery["days"],
    })
    return out


def _cfb_persist_results(server, record, rows):
    count = _ORIGINAL_CFB_PERSIST(server, record, rows)
    date = str((record or {}).get("date") or ((record or {}).get("event") or {}).get("date") or "")[:10]
    # put_event_media returns the number of newly assigned rows, so an idempotent
    # existing association can legitimately return zero.  Check the actual catalog
    # truth before deciding whether the day needs a cache invalidation.
    repo = getattr(server, "HISTORY_REPOSITORY", None)
    event = (record or {}).get("event") or {}
    event_id = str((record or {}).get("eventId") or event.get("eventId") or event.get("id") or "")
    wanted = {str(x.get("youtubeId") or "") for x in (rows or []) if isinstance(x, dict) and x.get("youtubeId")}
    linked = False
    if repo is not None and date and event_id and wanted:
        try:
            media = repo.event_media(date, "CFB", event_id, include_failed=False) or []
            linked = any(str(x.get("youtubeId") or "") in wanted for x in media if isinstance(x, dict))
        except Exception as exc:
            print(f"[SBB v4.7.19] CFB persistence verification failed {event_id}: {type(exc).__name__}: {exc}", flush=True)
    if count or linked:
        _invalidate_day_state([date])
    return count


def _cfb_has_known_usc(repo):
    try:
        for record in repo.catalog_events(league="CFB", date_from="2026-08-29", date_to="2026-08-29", limit=100):
            event = record.get("event") or {}
            blob = json.dumps(event, ensure_ascii=False).lower()
            if "usc" not in blob or ("san jose" not in blob and "sjs" not in blob):
                continue
            media = repo.event_media("2026-08-29", "CFB", record.get("eventId"), include_failed=False) or []
            if any(str(x.get("youtubeId") or "") == "-tDiPDHU2fs" for x in media if isinstance(x, dict)):
                return True
    except Exception:
        pass
    return False


def _startup_runtime_recovery():
    # Wait for server.py + CFB ranked schedule registration.  Run quickly at first,
    # then back off; the loop is bounded and exits once the known acceptance asset
    # is linked.  No YouTube quota is required for the known NBC hint.
    server = None
    for _ in range(300):
        try:
            import sys
            candidate = sys.modules.get("__main__")
            if candidate and getattr(candidate, "HISTORY_REPOSITORY", None) is not None:
                server = candidate
                break
        except Exception:
            pass
        time.sleep(0.2)
    if server is None:
        return
    repo = server.HISTORY_REPOSITORY
    try:
        recovered = restore_special_event_links(repo)
        if recovered.get("restored"):
            print(f"[SBB v4.7.19] restored {recovered['restored']} special-event relationships", flush=True)
    except Exception as exc:
        print(f"[SBB v4.7.19] special-event startup recovery deferred: {type(exc).__name__}: {exc}", flush=True)
    try:
        silver = restore_silver_collection_links(repo)
        if silver.get("restored"):
            print(f"[SBB v4.7.19] restored {silver['restored']} Silver collection relationships", flush=True)
    except Exception as exc:
        print(f"[SBB v4.7.19] Silver startup recovery deferred: {type(exc).__name__}: {exc}", flush=True)

    # Retry while CFB Week 1 is materializing. The trusted module itself still owns
    # the eight network/conference sources + participating-school channels.
    for attempt in range(36):
        try:
            from . import cfb_trusted_youtube as cfb
            if _cfb_has_known_usc(repo):
                _invalidate_day_state(["2026-08-29"])
                break
            cfb.scan_recent_missing(server, days=max(3, getattr(cfb, "RECENT_ARCHIVE_DAYS", 3)), force_catalog=(attempt == 0))
            if _cfb_has_known_usc(repo):
                _invalidate_day_state(["2026-08-29"])
                print("[SBB v4.7.19] USC-SJSU trusted recap linked and Day State invalidated", flush=True)
                break
        except Exception as exc:
            if attempt in {0, 5, 15, 30}:
                print(f"[SBB v4.7.19] CFB acceptance recovery waiting: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(5 if attempt < 12 else 15)


def install():
    global _INSTALLED, _ORIGINAL_HYDRATE, _ORIGINAL_ROUNDUP_MEDIA
    global _ORIGINAL_REPAIR_EVENT_ASSOCIATIONS, _ORIGINAL_CFB_PERSIST
    with _INSTALL_LOCK:
        if _INSTALLED:
            return False
        _INSTALLED = True

    # Install after v4.7.18 readiness so this wrapper sees the final production
    # hydration path instead of the unwrapped base class used by isolated tests.
    _ORIGINAL_HYDRATE = HistoryRepository._hydrate_asset
    _ORIGINAL_ROUNDUP_MEDIA = getattr(HistoryRepository, "roundup_media", None)
    _ORIGINAL_REPAIR_EVENT_ASSOCIATIONS = HistoryRepository.repair_event_associations
    HistoryRepository._hydrate_asset = staticmethod(_hydrate_asset)
    if callable(_ORIGINAL_ROUNDUP_MEDIA):
        HistoryRepository.roundup_media = _roundup_media
    HistoryRepository.repair_event_associations = _repair_event_associations

    try:
        from . import cfb_trusted_youtube as cfb
        _ORIGINAL_CFB_PERSIST = cfb._persist_results
        cfb._persist_results = _cfb_persist_results
    except Exception:
        _ORIGINAL_CFB_PERSIST = None

    threading.Thread(target=_startup_runtime_recovery, daemon=True, name="sbb-v4719-runtime-recovery").start()
    return True


__all__ = [
    "VERSION", "install", "restore_special_event_links", "restore_silver_collection_links", "_invalidate_day_state",
    "_hydrate_asset", "_roundup_media", "_cfb_persist_results",
]

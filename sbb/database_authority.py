"""Sports Big Board v4.7.21 — durable database relationship authority.

ASSIGNED EVENT_MEDIA and COLLECTION_MEDIA edges are durable evidence. Runtime
FAILED remains the playback veto. Startup repair is audit-only; one bounded local
recovery restores edges from exact persisted/source/day-cache evidence without
provider searches.
"""
from __future__ import annotations

from contextlib import closing
import json
import re
import sys
import threading
import time

from .history_repository import HistoryRepository

VERSION = "4.7.21-database-authority-2"
RECOVERY_VERSION = 4722
_LOCK = threading.Lock()
_INSTALLED = False
_ORIG = {}
COLLECTION_SCOPES = {"DAY_LEAGUE", "WEEK_LEAGUE", "ROUND_LEAGUE", "SEASON_LEAGUE"}
COLLECTION_KINDS = {"DAILY_RECAP", "TOP_PLAYS", "BEST_GOALS", "BEST_SAVES", "SCORING_ROUNDUP", "ROUNDUP", "WEEKLY_RECAP"}
FAIL_METHODS = {"DATE_MISMATCH", "SEASON_MISMATCH", "TITLE_TEAM_PAIR_CONFLICT", "TEAM_FIELD_CONFLICT", "CROSS_EVENT_ASSET_CONFLICT", "NON_GAME_SCOPE_EVENT_LINK", "MULTI_EVENT_CANDIDATE_ENCOUNTER", "UNPROVEN_GAME_ASSOCIATION"}
STRONG_METHODS = {"PROVIDER_EVENT_ID", "PROVIDER_SOURCE_EVENT_ID", "PROVIDER_GAME_PK", "EXACT_EVENT_ID", "CANONICAL_EVENT_ID"}
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


def _obj(raw):
    if isinstance(raw, dict): return dict(raw)
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except Exception: return {}


def _row(row, key, default=""):
    try: value = row[key]
    except Exception:
        try: value = row.get(key, default)
        except Exception: value = default
    return default if value is None else value


def _transport(item):
    try:
        from . import history_readiness_repair as readiness
        return bool(readiness._repair_transport(item))
    except Exception:
        return bool(str((item or {}).get("youtubeId") or "").strip() or str((item or {}).get("mediaUrl") or "").strip())


def _fill_transport(item, row):
    provider = str(_row(row, "provider", item.get("provider") or "") or "")
    media_id = str(_row(row, "provider_media_id", item.get("providerMediaId") or "") or "").strip()
    url = str(_row(row, "canonical_url", item.get("canonicalUrl") or "") or "").strip()
    if provider and not item.get("provider"): item["provider"] = provider
    if media_id and not item.get("providerMediaId"): item["providerMediaId"] = media_id
    if url and not item.get("canonicalUrl"): item["canonicalUrl"] = url
    if not item.get("youtubeId") and "YOUTUBE" in provider.upper() and YOUTUBE_ID.fullmatch(media_id):
        item["youtubeId"] = media_id
    _transport(item)
    return item


def _authoritative_playability(item, authority):
    if not isinstance(item, dict): return item
    runtime = str(item.get("runtimeCatalogState") or item.get("runtimeState") or "UNKNOWN").upper()
    if runtime == "FAILED":
        item["verifiedPlayable"] = False
    elif _transport(item):
        item["verifiedPlayable"] = True
        item["databaseAssociationPlayable"] = True
        item["databaseVerifiedPlayable"] = True
        if str(item.get("validationState") or "").upper() != "VERIFIED": item["legacyDatabasePlayable"] = True
        item["databaseAuthority"] = authority
    return item


def _event_media(self, date, league, event_id, include_failed=True):
    rows = _ORIG["event_media"](self, date, league, event_id, include_failed=include_failed)
    for item in rows or []: _authoritative_playability(item, "EVENT_MEDIA_ASSIGNED")
    return rows


def _ribbon_media(self, date, leagues=None, include_failed=False):
    grouped = _ORIG["ribbon_media"](self, date, leagues=leagues, include_failed=include_failed)
    for rows in (grouped or {}).values():
        for item in rows or []: _authoritative_playability(item, "EVENT_MEDIA_ASSIGNED")
    return grouped


def _roundup_media(self, date, league=None):
    rows = _ORIG["roundup_media"](self, date, league)
    for item in rows or []: _authoritative_playability(item, "COLLECTION_MEDIA_ASSIGNED")
    return rows


def _event_audit(self, matcher_version=None):
    try: summary = dict(self.association_integrity_summary() or {})
    except Exception: summary = {}
    return {"skipped": True, "mode": "AUDIT_ONLY_DATABASE_AUTHORITY", "matcherVersion": int(matcher_version or 0), "checkedLinks": 0, "quarantinedLinks": 0, **summary}


def _collection_audit(self, classifier_version=None):
    return {"skipped": True, "mode": "AUDIT_ONLY_DATABASE_AUTHORITY", "classifierVersion": int(classifier_version or 0), "checkedAssets": 0, "removedLinks": 0, "createdLinks": 0}


def _repair_event(self, matcher_version=None, force=False):
    if not force: return _event_audit(self, matcher_version)
    kw = {"force": True}
    if matcher_version is not None: kw["matcher_version"] = matcher_version
    return _ORIG["event_repair"](self, **kw)


def _repair_collection(self, classifier_version=None, force=False):
    if not force: return _collection_audit(self, classifier_version)
    kw = {"force": True}
    if classifier_version is not None: kw["classifier_version"] = classifier_version
    return _ORIG["collection_repair"](self, **kw)


def _repair_relationships(self, force=False, force_event=False, force_collection=False):
    if force: return _ORIG["relationship_repair"](self, force=True)
    try: integrity = dict(self.catalog_integrity() or {})
    except Exception: integrity = {}
    return {"ok": True, "mode": "AUDIT_ONLY_DATABASE_AUTHORITY", "startupMutationBlocked": bool(force_event or force_collection), "requestedEventRepair": bool(force_event), "requestedCollectionRepair": bool(force_collection), "event": self.repair_event_associations(force=False), "collection": self.repair_collection_associations(force=False), "integrity": integrity}


def _count(conn, sql, args=()):
    try: return int(conn.execute(sql, args).fetchone()[0] or 0)
    except Exception: return 0


def _silver(item):
    tier = str((item or {}).get("collectionTier") or (item or {}).get("displayTier") or "").lower()
    return tier == "silver" or (item or {}).get("collectionPromotionApproved") is True


def _collection_evidence(item):
    return _silver(item) or (str((item or {}).get("mediaScope") or "").upper() in COLLECTION_SCOPES and str((item or {}).get("collectionKind") or "").upper() in COLLECTION_KINDS)


def diagnose(repo):
    out = {"sourceAssets": 0, "assignedGameLinks": 0, "quarantinedGameLinks": 0, "assignedCandidateTransport": 0, "runtimeFailedAssets": 0, "silverCollectionLinks": 0, "silverOrphanMetadata": 0, "eventDayArchiveCandidates": 0, "silverDayArchiveCandidates": 0, "llwsSourceAssets": 0, "llwsAssignedAssets": 0}
    try:
        with closing(repo._read_connect()) as conn:
            out["sourceAssets"] = _count(conn, "SELECT COUNT(*) FROM history_source_media")
            out["assignedGameLinks"] = _count(conn, "SELECT COUNT(*) FROM history_event_media WHERE association_state='ASSIGNED'")
            out["quarantinedGameLinks"] = _count(conn, "SELECT COUNT(*) FROM history_event_media WHERE association_state='QUARANTINED'")
            out["runtimeFailedAssets"] = _count(conn, "SELECT COUNT(*) FROM history_source_media WHERE UPPER(runtime_state)='FAILED'")
            out["silverCollectionLinks"] = _count(conn, "SELECT COUNT(*) FROM history_collection_media")
            for row in conn.execute("""SELECT DISTINCT s.provider,s.provider_media_id,s.canonical_url,s.asset_json FROM history_event_media em JOIN history_source_media s ON s.asset_key=em.asset_key WHERE em.association_state='ASSIGNED' AND UPPER(COALESCE(s.runtime_state,''))<>'FAILED' AND UPPER(COALESCE(s.validation_state,''))<>'VERIFIED'""").fetchall():
                if _transport(_fill_transport(_obj(row["asset_json"]), row)): out["assignedCandidateTransport"] += 1
            for row in conn.execute("""SELECT s.asset_json FROM history_source_media s WHERE NOT EXISTS(SELECT 1 FROM history_collection_media cm WHERE cm.asset_key=s.asset_key)""").fetchall():
                if _silver(_obj(row["asset_json"])): out["silverOrphanMetadata"] += 1
            try:
                seen = set()
                for row in conn.execute("SELECT media_json FROM history_day WHERE COALESCE(media_json,'')<>''").fetchall():
                    try: items = json.loads(row["media_json"] or "[]")
                    except Exception: items = []
                    for item in items if isinstance(items, list) else []:
                        if not isinstance(item, dict): continue
                        if item.get("canonicalEventKey"): out["eventDayArchiveCandidates"] += 1
                        if _collection_evidence(item):
                            key = str(item.get("assetKey") or item.get("youtubeId") or item.get("providerMediaId") or item.get("canonicalUrl") or item.get("externalUrl") or "")
                            if key and key not in seen: seen.add(key); out["silverDayArchiveCandidates"] += 1
            except Exception: pass
            out["llwsSourceAssets"] = _count(conn, "SELECT COUNT(*) FROM history_source_media WHERE asset_json LIKE '%LLWS2026%' OR asset_json LIKE '%SPECIAL_EVENT_%'")
            out["llwsAssignedAssets"] = _count(conn, """SELECT COUNT(DISTINCT em.asset_key) FROM history_event_media em JOIN history_catalog_event e ON e.canonical_event_key=em.canonical_event_key WHERE em.association_state='ASSIGNED' AND UPPER(e.league)='LLWS2026'""")
    except Exception as exc: out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _event_ids(item):
    return {str(item[k]) for k in ("scoreEventId", "matchId", "espnEventId", "gamePk", "canonicalEventId", "eventId") if item.get(k) not in (None, "")}


def _special_proof(item, key):
    method = str(item.get("associationMethod") or "").upper()
    if method.startswith("SPECIAL_EVENT_") and str(item.get("canonicalEventKey") or "") == key: return True
    proof = item.get("sbbPreprovenAssociation")
    return isinstance(proof, dict) and str(proof.get("associationMethod") or "").upper().startswith("SPECIAL_EVENT_") and str(proof.get("canonicalEventKey") or proof.get("eventKey") or "") == key


def _source_event_proof(item, row):
    key, eid = str(row["canonical_event_key"] or ""), str(row["event_id"] or "")
    if _special_proof(item, key): return "SPECIAL_EVENT_PROOF"
    if eid and eid in _event_ids(item): return "EXACT_PERSISTED_EVENT_ID"
    if str(row["association_method"] or "").upper() in STRONG_METHODS: return "STRONG_PERSISTED_METHOD"
    try: conf = float(item.get("associationConfidence") or 0)
    except Exception: conf = 0
    method = str(item.get("associationMethod") or "").upper()
    if str(item.get("canonicalEventKey") or "") == key and conf >= .90 and method and method not in FAIL_METHODS: return "PERSISTED_CANONICAL_KEY"
    return ""


def _day_archive(repo, conn):
    by_asset = {}
    try: rows = conn.execute("SELECT date,league,media_json FROM history_day WHERE COALESCE(media_json,'')<>''").fetchall()
    except Exception: return by_asset
    for row in rows:
        try: items = json.loads(row["media_json"] or "[]")
        except Exception: items = []
        for raw in items if isinstance(items, list) else []:
            if not isinstance(raw, dict): continue
            try: key = str(repo.asset_key_for(raw) or raw.get("assetKey") or "")
            except Exception: key = str(raw.get("assetKey") or "")
            if key: by_asset.setdefault(key, []).append((str(row["date"] or "")[:10], str(row["league"] or "").upper(), raw))
    return by_asset


def _archive_event_proof(candidates, row):
    key, eid, day, league = str(row["canonical_event_key"] or ""), str(row["event_id"] or ""), str(row["event_date"] or "")[:10], str(row["league"] or "").upper()
    for d, lg, item in candidates or []:
        if d != day or lg != league or str(item.get("mediaScope") or "").upper() in COLLECTION_SCOPES: continue
        if str(item.get("canonicalEventKey") or "") == key: return "DAY_ARCHIVE_CANONICAL_KEY", item
        if eid and eid in _event_ids(item): return "DAY_ARCHIVE_EVENT_ID", item
        if _special_proof(item, key): return "DAY_ARCHIVE_SPECIAL_PROOF", item
    return "", None


def _restore_events(repo, conn, now, archive):
    stats = {"checked": 0, "restored": 0, "archiveRestored": 0, "rejected": 0, "conflicts": 0, "days": []}; days = set()
    rows = conn.execute("""SELECT em.canonical_event_key,em.asset_key,em.association_confidence,em.association_method,e.league,e.event_id,e.event_date,s.scope,s.runtime_state,s.provider,s.provider_media_id,s.canonical_url,s.asset_json FROM history_event_media em JOIN history_catalog_event e ON e.canonical_event_key=em.canonical_event_key JOIN history_source_media s ON s.asset_key=em.asset_key WHERE em.association_state='QUARANTINED'""").fetchall()
    for row in rows:
        stats["checked"] += 1
        if str(row["runtime_state"] or "").upper() == "FAILED" or str(row["scope"] or "").upper() in COLLECTION_SCOPES | {"PLAYER"}: stats["rejected"] += 1; continue
        item = _fill_transport(_obj(row["asset_json"]), row)
        if conn.execute("SELECT 1 FROM history_event_media WHERE asset_key=? AND association_state='ASSIGNED' AND canonical_event_key<>? LIMIT 1", (row["asset_key"], row["canonical_event_key"])).fetchone(): stats["conflicts"] += 1; continue
        proof = _source_event_proof(item, row); archived = None
        if not proof: proof, archived = _archive_event_proof(archive.get(str(row["asset_key"]), []), row)
        if archived:
            item.update(archived); item = _fill_transport(item, row)
        if not proof or not _transport(item): stats["rejected"] += 1; continue
        conf = max(float(row["association_confidence"] or 0), .995 if "EXACT" in proof or "ARCHIVE" in proof or "SPECIAL" in proof else .95)
        item.update(canonicalEventKey=str(row["canonical_event_key"]), associationState="ASSIGNED", associationConfidence=conf, associationMethod="V4721_DATABASE_AUTHORITY_RESTORE", associationEvidence=f"v4.7.21 durable proof: {proof}", mediaScope="GAME", mediaScopeReason="V4721_DATABASE_AUTHORITY_RECOVERY")
        conn.execute("""UPDATE history_event_media SET association_state='ASSIGNED',association_confidence=?,association_method='V4721_DATABASE_AUTHORITY_RESTORE',association_evidence=?,matcher_version=MAX(matcher_version,?),updated_at=? WHERE canonical_event_key=? AND asset_key=?""", (conf, item["associationEvidence"], RECOVERY_VERSION, now, row["canonical_event_key"], row["asset_key"]))
        conn.execute("""UPDATE history_source_media SET scope='GAME',scope_confidence=MAX(scope_confidence,.995),scope_reason='V4721_DATABASE_AUTHORITY_RECOVERY',catalog_state='ASSIGNED',quarantine_reason='',asset_json=?,updated_at=? WHERE asset_key=?""", (repo._dump_obj(item), now, row["asset_key"]))
        try: conn.execute("UPDATE history_assignment_review SET state='RESOLVED',updated_at=? WHERE asset_key=? AND proposed_event_key=? AND state='QUARANTINED'", (now, row["asset_key"], row["canonical_event_key"]))
        except Exception: pass
        stats["restored"] += 1; stats["archiveRestored"] += 1 if proof.startswith("DAY_ARCHIVE_") else 0; days.add(str(row["event_date"] or "")[:10])
    stats["days"] = sorted(d for d in days if d); return stats


def _collection_scope(item, row_scope, period):
    scope = str(item.get("mediaScope") or row_scope or "").upper()
    if scope in COLLECTION_SCOPES: return scope
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", period): return "DAY_LEAGUE"
    if re.search(r"(?:^|[-_:])W(?:EEK)?[-_: ]?\d+", period, re.I): return "WEEK_LEAGUE"
    if re.search(r"ROUND|MATCHWEEK|MATCH_WEEK|STAGE", period, re.I): return "ROUND_LEAGUE"
    return ""


def _promote_silver(repo, conn, row, item, league, period, kind, scope, now, method):
    if not league or not period or kind not in COLLECTION_KINDS or not scope: return False
    if scope == "DAY_LEAGUE":
        period = period[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", period): return False
    if str(row["runtime_state"] or "").upper() == "FAILED": return False
    if conn.execute("SELECT 1 FROM history_event_media WHERE asset_key=? AND association_state='ASSIGNED' LIMIT 1", (row["asset_key"],)).fetchone(): return False
    item = _fill_transport(item, row)
    if not _transport(item): return False
    ckey = repo._collection_key(scope, league, period, kind); title = f"{league} {period} {kind.replace('_',' ').title()}"
    conn.execute("""INSERT INTO history_collection(collection_key,scope,league,period_key,collection_kind,title,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(collection_key) DO UPDATE SET updated_at=excluded.updated_at""", (ckey, scope, league, period, kind, title, repo._dump_obj({"restoredBy": VERSION}), now, now))
    conn.execute("""INSERT INTO history_collection_media(collection_key,asset_key,association_confidence,association_method,association_evidence,classifier_version,rank_hint,first_associated_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(collection_key,asset_key) DO UPDATE SET updated_at=excluded.updated_at""", (ckey, row["asset_key"], .995, method, "persisted Silver relationship evidence", RECOVERY_VERSION, 450, now, now))
    item.update(mediaScope=scope, collectionTier="silver", displayTier="silver", collectionKind=kind, collectionPeriodKey=period, collectionKey=ckey, collectionPromotionApproved=True)
    conn.execute("""UPDATE history_source_media SET scope=?,scope_confidence=MAX(scope_confidence,.995),scope_reason='V4721_DATABASE_AUTHORITY_RECOVERY',catalog_state='ASSIGNED',quarantine_reason='',asset_json=?,updated_at=? WHERE asset_key=?""", (scope, repo._dump_obj(item), now, row["asset_key"]))
    return period[:10] if scope == "DAY_LEAGUE" else True


def _restore_silver(repo, conn, now, archive):
    stats = {"checked": 0, "restored": 0, "archiveChecked": 0, "archiveRestored": 0, "rejected": 0, "days": []}; days = set()
    rows = conn.execute("""SELECT s.asset_key,s.scope,s.runtime_state,s.provider,s.provider_media_id,s.canonical_url,s.asset_json FROM history_source_media s WHERE NOT EXISTS(SELECT 1 FROM history_collection_media cm WHERE cm.asset_key=s.asset_key)""").fetchall()
    by_key = {str(r["asset_key"]): r for r in rows}
    for row in rows:
        item = _obj(row["asset_json"])
        if not _silver(item): continue
        stats["checked"] += 1
        league = str(item.get("competitionId") or item.get("__sbbLeague") or item.get("league") or item.get("sourceLeague") or "").upper(); period = str(item.get("collectionPeriodKey") or item.get("topPlaysDate") or item.get("sourceDate") or item.get("gameDate") or item.get("date") or "")[:64]
        scope = _collection_scope(item, row["scope"], period); kind = str(item.get("collectionKind") or "").upper() or ("DAILY_RECAP" if scope == "DAY_LEAGUE" else "")
        restored = _promote_silver(repo, conn, row, item, league, period, kind, scope, now, "V4721_DATABASE_AUTHORITY_RESTORE")
        if restored: stats["restored"] += 1; days.add(restored) if isinstance(restored, str) else None
        else: stats["rejected"] += 1
    for key, entries in archive.items():
        row = by_key.get(key)
        if not row or conn.execute("SELECT 1 FROM history_collection_media WHERE asset_key=? LIMIT 1", (key,)).fetchone(): continue
        for day, row_league, raw in entries:
            if not _collection_evidence(raw): continue
            stats["archiveChecked"] += 1
            item = _obj(row["asset_json"]); item.update(raw)
            league = str(raw.get("competitionId") or raw.get("__sbbLeague") or raw.get("league") or raw.get("sourceLeague") or row_league or "").upper(); period = str(raw.get("collectionPeriodKey") or raw.get("topPlaysDate") or raw.get("sourceDate") or raw.get("gameDate") or raw.get("date") or day or "")[:64]
            scope = _collection_scope(raw, raw.get("mediaScope") or row["scope"], period); kind = str(raw.get("collectionKind") or "").upper() or ("DAILY_RECAP" if _silver(raw) and scope == "DAY_LEAGUE" else "")
            restored = _promote_silver(repo, conn, row, item, league, period, kind, scope, now, "V4721_DAY_ARCHIVE_SILVER_RESTORE")
            if restored: stats["restored"] += 1; stats["archiveRestored"] += 1; days.add(restored) if isinstance(restored, str) else None; break
    stats["days"] = sorted(d for d in days if d is not True); return stats


def recover(repo, *, force=False):
    try: marker = int(repo.catalog_meta("database_authority_recovery_version", "0") or 0)
    except Exception: marker = 0
    before = diagnose(repo)
    if marker >= RECOVERY_VERSION and not force: return {"skipped": True, "marker": marker, "before": before, "after": before}
    now = time.time()
    with repo._lock, closing(repo._connect()) as conn:
        archive = _day_archive(repo, conn); event = _restore_events(repo, conn, now, archive); silver = _restore_silver(repo, conn, now, archive)
        payload = {"version": VERSION, "event": event, "silver": silver, "before": before}
        for key, value in (("database_authority_recovery_version", str(RECOVERY_VERSION)), ("database_authority_recovery_last", json.dumps(payload, separators=(",", ":"), default=str))):
            conn.execute("INSERT INTO history_catalog_meta(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (key, value, now))
        conn.commit()
    days = sorted(set(event["days"]) | set(silver["days"]))
    if days:
        try:
            from . import runtime_path_repair_v4720 as runtime
            runtime._invalidate_day_state(days)
        except Exception: pass
    return {"skipped": False, "marker": RECOVERY_VERSION, "event": event, "silver": silver, "days": days, "before": before, "after": diagnose(repo)}



def _llws_source_inventory(repo):
    """Return durable LLWS source media directly from the normalized database.

    Earlier generic relationship repair could demote a valid LLWS asset to OTHER
    or quarantine its event edge. The special-event associator must therefore not
    depend on the league-source helper seeing only currently classified LLWS rows.
    This query is local-only and deliberately includes prior LLWS relationship
    history plus unmistakable Little League provenance retained in SOURCE_MEDIA.
    """
    items=[];seen=set()
    try:
        with closing(repo._read_connect()) as conn:
            rows=conn.execute("""
                SELECT DISTINCT s.*
                FROM history_source_media s
                LEFT JOIN history_event_media em ON em.asset_key=s.asset_key
                LEFT JOIN history_catalog_event e ON e.canonical_event_key=em.canonical_event_key
                WHERE UPPER(COALESCE(e.league,''))='LLWS2026'
                   OR UPPER(COALESCE(json_extract(s.asset_json,'$.competitionId'),''))='LLWS2026'
                   OR UPPER(COALESCE(json_extract(s.asset_json,'$.__sbbLeague'),''))='LLWS2026'
                   OR LOWER(COALESCE(s.channel_name,'')) LIKE '%little league%'
                   OR LOWER(COALESCE(s.asset_json,'')) LIKE '%little league%'
                   OR LOWER(COALESCE(s.asset_json,'')) LIKE '%littleleague%'
                   OR UPPER(COALESCE(s.asset_json,'')) LIKE '%SPECIAL_EVENT_%'
                ORDER BY s.updated_at DESC
            """).fetchall()
        for row in rows:
            if str(_row(row,'runtime_state','')).upper()=='FAILED':
                continue
            try:item=repo._hydrate_asset(row)
            except Exception:item=_fill_transport(_obj(_row(row,'asset_json','{}')),row)
            if not isinstance(item,dict):continue
            key=str(item.get('assetKey') or _row(row,'asset_key','') or '')
            if not key or key in seen:continue
            seen.add(key)
            item.setdefault('assetKey',key)
            item.setdefault('league','LLWS2026');item.setdefault('competitionId','LLWS2026');item.setdefault('__sbbLeague','LLWS2026')
            _fill_transport(item,row)
            items.append(item)
    except Exception:
        return []
    return items


def _recover_llws_owner(server, repo):
    """Replay the actual v4.6.16 LLWS alias/game-number owner over durable sources."""
    from . import special_event_media_v4616 as special
    comp=special._ensure_llws_sources(server)
    if not isinstance(comp,dict) or str(comp.get('id') or '').upper()!='LLWS2026':
        return {'ready':False,'reason':'COMPETITION_NOT_READY','sourceItems':0}
    items=_llws_source_inventory(repo)
    if not items:
        return {'ready':False,'reason':'SOURCE_INVENTORY_EMPTY','sourceItems':0}
    result=special.SpecialEventMediaAssociator(server,comp).associate(items)
    durable=special.durable_stats(server,comp)
    dates=sorted({str(r.get('date') or '')[:10] for r in special.competition_records(server,comp) if str(r.get('date') or '')[:10]})
    try:
        from . import runtime_path_repair_v4720 as runtime
        runtime._invalidate_day_state(dates)
    except Exception:pass
    summary=dict((result or {}).get('summary') or {})
    return {'ready':True,'sourceItems':len(items),'summary':summary,'durable':durable,'dates':dates}


def _llws_recovery_worker(server,repo):
    """Bounded local retry so recovery waits for competition/history startup order."""
    last=None
    for attempt in range(24):
        try:
            result=_recover_llws_owner(server,repo)
            durable=dict(result.get('durable') or {})
            snapshot=(int(durable.get('sourceAssets') or result.get('sourceItems') or 0),
                      int(durable.get('associatedAssets') or 0),
                      int(durable.get('gamesWithoutPlayableAssociatedMedia') or 0))
            if result.get('ready'):
                print('[SBB database-authority] LLWS owner recovery '+json.dumps({'attempt':attempt+1,'sourceAssets':snapshot[0],'associatedAssets':snapshot[1],'missingGames':snapshot[2],'summary':result.get('summary') or {}},separators=(',',':'),default=str),flush=True)
            if result.get('ready') and snapshot[0]>0 and snapshot[2]==0:
                return
            last=snapshot
        except Exception as exc:
            print(f'[SBB database-authority] LLWS recovery deferred: {type(exc).__name__}: {exc}',flush=True)
        time.sleep(5)

def _startup():
    server = None
    for _ in range(300):
        candidate = sys.modules.get("__main__")
        if candidate is not None and getattr(candidate, "HISTORY_REPOSITORY", None) is not None: server = candidate; break
        time.sleep(.2)
    if server is None: return
    try:
        repo = server.HISTORY_REPOSITORY; print("[SBB database-authority] audit "+json.dumps(diagnose(repo), separators=(",", ":")), flush=True); result = recover(repo)
        if not result.get("skipped"): print("[SBB database-authority] recovery "+json.dumps({"event": result["event"], "silver": result["silver"], "after": result["after"]}, separators=(",", ":"), default=str), flush=True)
        # LLWS recovery is intentionally NOT gated by the generic recovery marker.
        # The special-event owner and its source inventory can become ready later in
        # startup, and older destructive repair may already have overwritten scope.
        threading.Thread(target=_llws_recovery_worker,args=(server,repo),daemon=True,name='sbb-database-authority-llws').start()
    except Exception as exc: print(f"[SBB database-authority] recovery deferred: {type(exc).__name__}: {exc}", flush=True)


def install():
    global _INSTALLED
    with _LOCK:
        if _INSTALLED: return False
        _ORIG.update(event_media=HistoryRepository.event_media, ribbon_media=HistoryRepository.ribbon_media_for_date, roundup_media=HistoryRepository.roundup_media, event_repair=HistoryRepository.repair_event_associations, collection_repair=HistoryRepository.repair_collection_associations, relationship_repair=HistoryRepository.repair_relationships)
        HistoryRepository.event_media = _event_media; HistoryRepository.ribbon_media_for_date = _ribbon_media; HistoryRepository.roundup_media = _roundup_media
        HistoryRepository.repair_event_associations = _repair_event; HistoryRepository.repair_collection_associations = _repair_collection; HistoryRepository.repair_relationships = _repair_relationships
        _INSTALLED = True
    threading.Thread(target=_startup, daemon=True, name="sbb-database-authority-recovery").start(); return True


__all__ = ["VERSION", "RECOVERY_VERSION", "install", "diagnose", "recover", "_authoritative_playability", "_repair_relationships", "_llws_source_inventory", "_recover_llws_owner"]

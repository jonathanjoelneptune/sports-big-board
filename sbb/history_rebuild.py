"""Deterministic v3 -> v4 historical catalog reconstruction.

This module never mutates the source database. It builds a second SQLite catalog,
re-proves every event association, routes collection media to Silver, preserves
safe source/runtime verification state, and accounts for ambiguous media in the
review queue. A production swap should happen only after the generated integrity
report passes.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
import sys
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from .catalog_contract import CATALOG_SCHEMA_VERSION, ASSIGNED, QUARANTINED, UNASSIGNED, MEDIA_CLASSIFIER_VERSION, EVENT_MATCHER_VERSION
from .event_matcher import match_event, team_name
from .history_repository import HistoryRepository
from .media_scope import annotate as annotate_media_scope, GAME, COLLECTION_SCOPES

_AUTHORITATIVE_TYPES = {"espn-event-video","mlb-game-content","nfl-event-video","official-nfl-club-site"}
_ID_FIELDS = ("matchId","scoreEventId","espnEventId","canonicalEventId","canonicalEventKey")


def _load_obj(value):
    if not value: return {}
    try:
        data=json.loads(value); return data if isinstance(data,dict) else {}
    except Exception: return {}


def _load_list(value):
    if not value: return []
    try:
        data=json.loads(value); return data if isinstance(data,list) else []
    except Exception: return []


def _table_exists(conn, name):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())


def _columns(conn, table):
    if not _table_exists(conn,table): return set()
    return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")}


def _safe_date(value):
    text=str(value or "")[:10]
    try: datetime.strptime(text,"%Y-%m-%d"); return text
    except Exception: return ""


def _nearby_dates(date, days=1):
    try: d=datetime.strptime(str(date)[:10],"%Y-%m-%d").date()
    except Exception: return [str(date)[:10]] if date else []
    return [(d+timedelta(days=delta)).isoformat() for delta in range(-days,days+1)]


class HistoryCatalogRebuilder:
    def __init__(self, source_path, output_path):
        self.source_path=Path(source_path)
        self.output_path=Path(output_path)
        self.started_at=time.time()
        self.repo=None
        self.report={
            "catalogSchemaVersion":CATALOG_SCHEMA_VERSION,
            "source":str(self.source_path),"output":str(self.output_path),
            "sourceLeagueDays":0,"sourceEventRows":0,"sourceNormalizedMediaRows":0,"sourceCollectionRows":0,"sourceCachedMediaRows":0,
            "canonicalEvents":0,"uniqueInputAssets":0,"keylessInputRows":0,
            "assignedGameAssets":0,"silverAssets":0,"quarantinedAssets":0,"unassignedAssets":0,
            "duplicateInputRows":0,"preservedVerifiedAssets":0,"preservedRuntimePlayed":0,"preservedRuntimeFailed":0,
            "legacyDiscoveryResetEvents":0,"errors":[],"warnings":[],
        }
        self._seen_input_assets=set(); self._processed_records=set(); self._events={}; self._events_by_date=defaultdict(list)

    def _src(self):
        conn=sqlite3.connect(self.source_path); conn.row_factory=sqlite3.Row; return conn

    def _dst(self):
        conn=sqlite3.connect(self.output_path); conn.row_factory=sqlite3.Row; return conn

    def _event_key(self,league,event_id): return self.repo.canonical_event_key(league,event_id)

    def _progress(self, message):
        print(f"[v4 rebuild] {message}", file=sys.stderr, flush=True)

    def _index_events(self):
        with closing(self._dst()) as conn:
            rows=conn.execute("SELECT canonical_event_key,league,event_id,event_date,event_json FROM history_catalog_event").fetchall()
        self._events={r["canonical_event_key"]:{"key":r["canonical_event_key"],"league":r["league"],"eventId":r["event_id"],"date":r["event_date"],"event":_load_obj(r["event_json"])} for r in rows}
        self._events_by_date=defaultdict(list)
        for event in self._events.values(): self._events_by_date[(event["league"],event["date"])].append(event)
        self.report["canonicalEvents"]=len(self._events)

    def _copy_score_skeleton(self, src):
        if not _table_exists(src,"history_day"): return
        rows=src.execute("SELECT * FROM history_day ORDER BY date,league").fetchall(); self.report["sourceLeagueDays"]=len(rows); self._progress(f"Score skeleton: {len(rows)} league-days")
        for row in rows:
            date=str(row["date"])[:10]; league=str(row["league"]).upper(); scores=_load_list(row["scores_json"])
            self.repo.put_scores(date,league,scores)
            legacy_disc=_load_obj(row["discovery_json"]) if "discovery_json" in row.keys() else {}
            reset={"catalogSchemaVersion":CATALOG_SCHEMA_VERSION,"discoveryVersion":0,"rebuildImportedAt":self.started_at,"rebuildState":"PENDING_CURRENT_DISCOVERY"}
            if legacy_disc:
                # Keep only diagnostic provenance. Completion/retry sets are reset
                # so stale v3 bookkeeping cannot suppress v4 discovery.
                reset["legacyDiscoveryVersion"]=int(legacy_disc.get("discoveryVersion") or 0)
                reset["legacyDeepComplete"]=bool(legacy_disc.get("deepComplete"))
            self.repo.put_discovery(date,league,reset,merge=False)

    def _copy_event_skeleton(self, src):
        if not _table_exists(src,"history_event"): return
        rows=src.execute("SELECT * FROM history_event ORDER BY updated_at DESC").fetchall(); self.report["sourceEventRows"]=len(rows); self._progress(f"Event skeleton: {len(rows)} legacy event rows")
        chosen={}
        for row in rows:
            key=(str(row["league"]).upper(),str(row["event_id"]))
            if key in chosen: continue
            chosen[key]=row
        for (league,event_id),row in chosen.items():
            date=str(row["date"])[:10]; event=_load_obj(row["event_json"])
            self.repo.upsert_event(date,league,event_id,event)
            legacy=_load_obj(row["discovery_json"])
            details={"catalogSchemaVersion":CATALOG_SCHEMA_VERSION,"discoveryVersion":0,"rebuildImportedAt":self.started_at,"rebuildState":"PENDING_CURRENT_DISCOVERY",
                     "legacyDiscoveryState":str(row["discovery_state"] or "UNKNOWN"),"legacyDiscoveryVersion":int(legacy.get("discoveryVersion") or 0)}
            self.repo.reset_event_for_reindex(date,league,event_id,details,state="UNKNOWN")
            self.report["legacyDiscoveryResetEvents"]+=1
        self._index_events()

    @staticmethod
    def _sanitize_legacy_item(raw, *, legacy_event_id=""):
        item=dict(raw or {})
        source_type=str(item.get("sourceType") or "").lower(); authoritative=source_type in _AUTHORITATIVE_TYPES
        # Strip v3 classification so v4 reruns from source evidence.
        for key in ("mediaScope","mediaScopeConfidence","mediaScopeReason","mediaClassifierVersion","mediaIntent","mediaIntentConfidence","mediaIntentReason",
                    "collectionTier","displayTier","collectionKind","collectionPeriodKey"):
            item.pop(key,None)
        # Generic official-channel rows may contain a wrong event stamp introduced
        # by v3 association-before-proof. Never trust it during reconstruction.
        if not authoritative:
            for key in _ID_FIELDS: item.pop(key,None)
        elif legacy_event_id:
            item["sourceEventId"]=str(legacy_event_id)
        return item

    def _candidate_events(self, league, date, legacy_event_id=""):
        out=[]; seen=set()
        for day in _nearby_dates(date,1):
            for event in self._events_by_date.get((league,day),[]):
                if event["key"] not in seen: seen.add(event["key"]); out.append(event)
        if legacy_event_id:
            key=self._event_key(league,legacy_event_id); event=self._events.get(key)
            if event and key not in seen: out.append(event)
        return out

    def _preserve_state(self, asset_key, record):
        validation=str(record.get("validation_state") or record.get("validationState") or "").upper()
        verified_at=float(record.get("verified_at") or record.get("verifiedAt") or 0)
        runtime=str(record.get("runtime_state") or record.get("runtimeState") or "UNKNOWN").upper()
        success_at=float(record.get("runtime_success_at") or 0); failure_at=float(record.get("runtime_failure_at") or 0); reason=str(record.get("runtime_failure_reason") or "")
        with closing(self._dst()) as conn:
            current=conn.execute("SELECT validation_state,verified_at,runtime_state,runtime_success_at,runtime_failure_at FROM history_source_media WHERE asset_key=?",(asset_key,)).fetchone()
            if not current: return
            if validation=="VERIFIED":
                conn.execute("UPDATE history_source_media SET validation_state='VERIFIED',verified_at=MAX(verified_at,?) WHERE asset_key=?",(verified_at,asset_key)); self.report["preservedVerifiedAssets"]+=1
            if runtime=="PLAYED" and success_at>=float(current["runtime_failure_at"] or 0):
                conn.execute("UPDATE history_source_media SET runtime_state='PLAYED',runtime_success_at=MAX(runtime_success_at,?),runtime_failure_reason='' WHERE asset_key=?",(success_at,asset_key)); self.report["preservedRuntimePlayed"]+=1
            elif runtime=="FAILED" and failure_at>float(current["runtime_success_at"] or 0):
                conn.execute("UPDATE history_source_media SET runtime_state='FAILED',runtime_failure_at=MAX(runtime_failure_at,?),runtime_failure_reason=? WHERE asset_key=?",(failure_at,reason[:500],asset_key)); self.report["preservedRuntimeFailed"]+=1
            conn.commit()

    def _review_unmatched(self, asset_key, league, date, proposed_key, reason, evidence, *, state=QUARANTINED):
        now=time.time()
        with closing(self._dst()) as conn:
            conn.execute("INSERT INTO history_assignment_review(asset_key,league,event_date,proposed_event_key,state,reason,evidence_json,classifier_version,matcher_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_key,proposed_event_key,reason) DO UPDATE SET state=excluded.state,evidence_json=excluded.evidence_json,updated_at=excluded.updated_at",
                (asset_key,league,date,proposed_key or "",state,reason,json.dumps(evidence or {},separators=(",",":"),default=str),MEDIA_CLASSIFIER_VERSION,EVENT_MATCHER_VERSION,now,now))
            conn.commit()

    def _process_media(self, raw, *, league, date, legacy_event_id="", legacy_state=None, explicit_collection=None, source_label=""):
        if not isinstance(raw,dict): return
        item=self._sanitize_legacy_item(raw,legacy_event_id=legacy_event_id); league=str(league or item.get("league") or item.get("competitionId") or "").upper(); date=_safe_date(date or item.get("date") or item.get("gameDate"))
        if not league: return
        asset_key=self.repo.asset_key_for(item)
        if not asset_key:
            self.report["keylessInputRows"]+=1; return
        record_id=(source_label,asset_key,str(legacy_event_id or ""),date)
        if record_id in self._processed_records:
            self.report["duplicateInputRows"]+=1; return
        self._processed_records.add(record_id); self._seen_input_assets.add(asset_key)

        if explicit_collection:
            scope,period,kind=explicit_collection
            classified=annotate_media_scope(item,league=league,date=date); classified["mediaScope"]=scope; classified["mediaScopeReason"]="LEGACY_COLLECTION_MEMBERSHIP"; classified["mediaScopeConfidence"]=1.0
            self.repo.put_collection_media(scope,league,period,[classified],collection_kind=kind); self.report["silverAssets"]+=1
            self._preserve_state(asset_key,legacy_state or {})
            return

        classified=annotate_media_scope(item,league=league,date=date)
        scope=str(classified.get("mediaScope") or "OTHER")
        if scope in COLLECTION_SCOPES:
            period=str(classified.get("collectionPeriodKey") or date); kind=str(classified.get("collectionKind") or "ROUNDUP")
            self.repo.put_collection_media(scope,league,period,[classified],collection_kind=kind); self.report["silverAssets"]+=1
            self._preserve_state(asset_key,legacy_state or {})
            return

        if scope==GAME:
            matches=[]
            for event in self._candidate_events(league,date,legacy_event_id):
                event_item=annotate_media_scope(classified,league=league,date=event["date"],away=team_name(event["event"],"away"),home=team_name(event["event"],"home"))
                evidence=match_event(event_item,event["event"],league=league,date=event["date"])
                if evidence.get("associationState")==ASSIGNED and float(evidence.get("associationConfidence") or 0)>=0.90:
                    matches.append((event,float(evidence.get("associationConfidence") or 0),evidence,event_item))
            # Highest-confidence unique match only. Ties are reviewable rather than
            # silently duplicating one video across games.
            matches.sort(key=lambda x:x[1],reverse=True)
            if matches and (len(matches)==1 or matches[0][1]>matches[1][1]):
                event,_,evidence,event_item=matches[0]; before=len(self.repo.event_media(event["date"],league,event["eventId"]))
                accepted=self.repo.put_event_media(event["date"],league,event["eventId"],[event_item])
                if accepted:
                    self.report["assignedGameAssets"]+=1
                    if legacy_state: self._preserve_state(asset_key,legacy_state)
                    return
            reason="AMBIGUOUS_EVENT_MATCH" if len(matches)>1 else "NO_PROVABLE_EVENT_MATCH"
            self.repo.put_source_media([classified],league=league,date=date,catalog_state=QUARANTINED)
            self._review_unmatched(asset_key,league,date,self._event_key(league,legacy_event_id) if legacy_event_id else "",reason,
                                  {"candidateMatches":[{"event":m[0]["key"],"confidence":m[1],"evidence":m[2]} for m in matches]},state=QUARANTINED)
            self.report["quarantinedAssets"]+=1
            if legacy_state: self._preserve_state(asset_key,legacy_state)
            return

        # PLAYER / OTHER are retained as a reusable reservoir. They cannot affect
        # game tiering until a future classifier/matcher proves a relationship.
        self.repo.put_source_media([classified],league=league,date=date,catalog_state=UNASSIGNED)
        self._review_unmatched(asset_key,league,date,"","NON_GAME_UNASSIGNED",{"scope":scope,"scopeReason":classified.get("mediaScopeReason")},state=UNASSIGNED)
        self.report["unassignedAssets"]+=1
        if legacy_state: self._preserve_state(asset_key,legacy_state)

    def _import_legacy_collections(self, src):
        if not _table_exists(src,"history_collection_media"): return
        cols=_columns(src,"history_collection_media")
        # v3.1 schema has scope/league/period_key directly. If source is already
        # v4, this path is skipped because collection_key replaces those columns.
        if not {"scope","league","period_key","asset_json"}.issubset(cols): return
        rows=src.execute("SELECT * FROM history_collection_media").fetchall(); self.report["sourceCollectionRows"]=len(rows); self._progress(f"Legacy Silver collections: {len(rows)} rows")
        for idx,row in enumerate(rows,1):
            if idx % 1000 == 0: self._progress(f"Silver collection rows processed: {idx}/{len(rows)}")
            raw=_load_obj(row["asset_json"]); state={k:row[k] for k in row.keys() if k in {"validation_state","verified_at","runtime_state","runtime_success_at","runtime_failure_at","runtime_failure_reason"}}
            self._process_media(raw,league=row["league"],date=str(raw.get("date") or row["period_key"])[:10],legacy_state=state,
                                explicit_collection=(str(row["scope"]),str(row["period_key"]),str(row["collection_kind"] or "ROUNDUP")),source_label="legacy_collection")

    def _import_normalized_media(self, src):
        if not _table_exists(src,"history_media_asset"): return
        rows=src.execute("SELECT * FROM history_media_asset").fetchall(); self.report["sourceNormalizedMediaRows"]=len(rows); self._progress(f"Normalized legacy media: {len(rows)} rows")
        for idx,row in enumerate(rows,1):
            if idx % 1000 == 0: self._progress(f"Normalized media rows processed: {idx}/{len(rows)}")
            raw=_load_obj(row["asset_json"]); state={k:row[k] for k in row.keys() if k in {"validation_state","verified_at","runtime_state","runtime_success_at","runtime_failure_at","runtime_failure_reason"}}
            self._process_media(raw,league=row["league"],date=row["date"],legacy_event_id=row["event_id"],legacy_state=state,source_label="legacy_event_media")

    def _import_day_cache_media(self, src):
        if not _table_exists(src,"history_day"): return
        count=0
        for row in src.execute("SELECT date,league,media_json FROM history_day WHERE media_json IS NOT NULL AND media_json<>''"):
            for raw in _load_list(row["media_json"]):
                count+=1
                if count % 1000 == 0: self._progress(f"Day-cache media rows processed: {count}")
                legacy_event_id=HistoryRepository.event_id_for(raw)
                self._process_media(raw,league=row["league"],date=row["date"],legacy_event_id=legacy_event_id,legacy_state=raw,source_label="legacy_day_cache")
        self.report["sourceCachedMediaRows"]=count

    def _resolve_integrity_conflicts(self):
        """Fail closed on residual legacy conflicts before the hard v4 audit.

        The rebuild intentionally imports legacy evidence generously, then this
        pass enforces the normalized invariants. Conflicting links are never
        guessed into production; they are quarantined/reviewable.
        """
        now=time.time()
        counts={"silverGameLinksQuarantined":0,"gameCollectionLinksRemoved":0,
                "lowConfidenceEventLinksQuarantined":0,"crossEventAssetsQuarantined":0,
                "lowConfidenceCollectionLinksRemoved":0}
        with closing(self._dst()) as conn:
            # Collection-scoped media cannot satisfy a game.
            rows=conn.execute("""SELECT em.canonical_event_key,em.asset_key,e.league,e.event_date
              FROM history_event_media em JOIN history_source_media s ON s.asset_key=em.asset_key
              JOIN history_catalog_event e ON e.canonical_event_key=em.canonical_event_key
              WHERE em.association_state='ASSIGNED' AND s.scope<>'GAME'""").fetchall()
            for row in rows:
                conn.execute("UPDATE history_event_media SET association_state='QUARANTINED',updated_at=? WHERE canonical_event_key=? AND asset_key=?",
                             (now,row["canonical_event_key"],row["asset_key"]))
                conn.execute("""INSERT INTO history_assignment_review(asset_key,league,event_date,proposed_event_key,state,reason,evidence_json,classifier_version,matcher_version,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_key,proposed_event_key,reason) DO UPDATE SET state=excluded.state,evidence_json=excluded.evidence_json,updated_at=excluded.updated_at""",
                  (row["asset_key"],row["league"],row["event_date"],row["canonical_event_key"],QUARANTINED,"SCOPE_EVENT_CONFLICT",json.dumps({"action":"event link quarantined because source scope is not GAME"}),MEDIA_CLASSIFIER_VERSION,EVENT_MATCHER_VERSION,now,now))
                counts["silverGameLinksQuarantined"]+=1

            # GAME-scoped media cannot live in Silver collections.
            rows=conn.execute("""SELECT cm.collection_key,cm.asset_key,c.league,c.period_key
              FROM history_collection_media cm JOIN history_source_media s ON s.asset_key=cm.asset_key
              JOIN history_collection c ON c.collection_key=cm.collection_key WHERE s.scope='GAME'""").fetchall()
            for row in rows:
                conn.execute("DELETE FROM history_collection_media WHERE collection_key=? AND asset_key=?",(row["collection_key"],row["asset_key"]))
                conn.execute("""INSERT INTO history_assignment_review(asset_key,league,event_date,proposed_event_key,state,reason,evidence_json,classifier_version,matcher_version,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_key,proposed_event_key,reason) DO UPDATE SET state=excluded.state,evidence_json=excluded.evidence_json,updated_at=excluded.updated_at""",
                  (row["asset_key"],row["league"],str(row["period_key"])[:10],"",UNASSIGNED,"GAME_COLLECTION_CONFLICT",json.dumps({"collectionKey":row["collection_key"],"action":"collection link removed because source scope is GAME"}),MEDIA_CLASSIFIER_VERSION,EVENT_MATCHER_VERSION,now,now))
                counts["gameCollectionLinksRemoved"]+=1

            # Assigned game links below the v4 confidence floor are review-only.
            rows=conn.execute("""SELECT em.canonical_event_key,em.asset_key,e.league,e.event_date,em.association_confidence
              FROM history_event_media em JOIN history_catalog_event e ON e.canonical_event_key=em.canonical_event_key
              WHERE em.association_state='ASSIGNED' AND em.association_confidence<0.90""").fetchall()
            for row in rows:
                conn.execute("UPDATE history_event_media SET association_state='QUARANTINED',updated_at=? WHERE canonical_event_key=? AND asset_key=?",
                             (now,row["canonical_event_key"],row["asset_key"]))
                conn.execute("""INSERT INTO history_assignment_review(asset_key,league,event_date,proposed_event_key,state,reason,evidence_json,classifier_version,matcher_version,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_key,proposed_event_key,reason) DO UPDATE SET state=excluded.state,evidence_json=excluded.evidence_json,updated_at=excluded.updated_at""",
                  (row["asset_key"],row["league"],row["event_date"],row["canonical_event_key"],QUARANTINED,"LOW_CONFIDENCE_EVENT_ASSOCIATION",json.dumps({"confidence":float(row["association_confidence"] or 0)}),MEDIA_CLASSIFIER_VERSION,EVENT_MATCHER_VERSION,now,now))
                counts["lowConfidenceEventLinksQuarantined"]+=1

            # A GAME asset may belong to only one canonical event. Any residual
            # multi-event asset is ambiguous by definition, so quarantine every
            # competing assignment instead of choosing one silently.
            conflicts=conn.execute("""SELECT asset_key FROM history_event_media WHERE association_state='ASSIGNED'
              GROUP BY asset_key HAVING COUNT(DISTINCT canonical_event_key)>1""").fetchall()
            for conflict in conflicts:
                asset_key=conflict["asset_key"]
                links=conn.execute("""SELECT em.canonical_event_key,e.league,e.event_date,em.association_confidence,em.association_method
                  FROM history_event_media em JOIN history_catalog_event e ON e.canonical_event_key=em.canonical_event_key
                  WHERE em.asset_key=? AND em.association_state='ASSIGNED'""",(asset_key,)).fetchall()
                evidence={"conflictingEvents":[{"event":r["canonical_event_key"],"confidence":float(r["association_confidence"] or 0),"method":r["association_method"]} for r in links]}
                for row in links:
                    conn.execute("UPDATE history_event_media SET association_state='QUARANTINED',updated_at=? WHERE canonical_event_key=? AND asset_key=?",
                                 (now,row["canonical_event_key"],asset_key))
                    conn.execute("""INSERT INTO history_assignment_review(asset_key,league,event_date,proposed_event_key,state,reason,evidence_json,classifier_version,matcher_version,created_at,updated_at)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_key,proposed_event_key,reason) DO UPDATE SET state=excluded.state,evidence_json=excluded.evidence_json,updated_at=excluded.updated_at""",
                      (asset_key,row["league"],row["event_date"],row["canonical_event_key"],QUARANTINED,"CROSS_EVENT_CONFLICT",json.dumps(evidence,separators=(",",":")),MEDIA_CLASSIFIER_VERSION,EVENT_MATCHER_VERSION,now,now))
                counts["crossEventAssetsQuarantined"]+=1

            # Weak collection links are not allowed to enter Silver playback.
            rows=conn.execute("""SELECT cm.collection_key,cm.asset_key,c.league,c.period_key,cm.association_confidence
              FROM history_collection_media cm JOIN history_collection c ON c.collection_key=cm.collection_key
              WHERE cm.association_confidence<0.80""").fetchall()
            for row in rows:
                conn.execute("DELETE FROM history_collection_media WHERE collection_key=? AND asset_key=?",(row["collection_key"],row["asset_key"]))
                conn.execute("""INSERT INTO history_assignment_review(asset_key,league,event_date,proposed_event_key,state,reason,evidence_json,classifier_version,matcher_version,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_key,proposed_event_key,reason) DO UPDATE SET state=excluded.state,evidence_json=excluded.evidence_json,updated_at=excluded.updated_at""",
                  (row["asset_key"],row["league"],str(row["period_key"])[:10],"",UNASSIGNED,"LOW_CONFIDENCE_COLLECTION_ASSOCIATION",json.dumps({"collectionKey":row["collection_key"],"confidence":float(row["association_confidence"] or 0)}),MEDIA_CLASSIFIER_VERSION,EVENT_MATCHER_VERSION,now,now))
                counts["lowConfidenceCollectionLinksRemoved"]+=1

            # Recompute the source-level state from surviving relationships.
            conn.execute("""UPDATE history_source_media SET catalog_state=CASE
              WHEN EXISTS(SELECT 1 FROM history_event_media em WHERE em.asset_key=history_source_media.asset_key AND em.association_state='ASSIGNED')
                OR EXISTS(SELECT 1 FROM history_collection_media cm WHERE cm.asset_key=history_source_media.asset_key) THEN 'ASSIGNED'
              WHEN EXISTS(SELECT 1 FROM history_assignment_review ar WHERE ar.asset_key=history_source_media.asset_key AND ar.state='QUARANTINED') THEN 'QUARANTINED'
              ELSE 'UNASSIGNED' END""")
            conn.commit()
        self.report["conflictResolution"]=counts
        self._progress("Conflict resolution: "+", ".join(f"{k}={v}" for k,v in counts.items()))
        return counts

    def _finalize_accounting(self):
        self.report["uniqueInputAssets"]=len(self._seen_input_assets)
        integrity=self.repo.catalog_integrity(); self.report["integrity"]=integrity
        with closing(self._dst()) as conn:
            unaccounted=int(conn.execute("""SELECT COUNT(*) FROM history_source_media s WHERE NOT EXISTS(SELECT 1 FROM history_event_media em WHERE em.asset_key=s.asset_key)
              AND NOT EXISTS(SELECT 1 FROM history_collection_media cm WHERE cm.asset_key=s.asset_key)
              AND NOT EXISTS(SELECT 1 FROM history_assignment_review ar WHERE ar.asset_key=s.asset_key)""").fetchone()[0] or 0)
            self.report["unaccountedAssets"]=unaccounted
            self.report["outputSourceAssets"]=int(conn.execute("SELECT COUNT(*) FROM history_source_media").fetchone()[0] or 0)
            self.report["outputEvents"]=int(conn.execute("SELECT COUNT(*) FROM history_catalog_event").fetchone()[0] or 0)
            self.report["outputCollections"]=int(conn.execute("SELECT COUNT(*) FROM history_collection").fetchone()[0] or 0)
        checks={
            "schemaVersionIs4":integrity.get("schemaVersion")==4,
            "silverCannotSatisfyGame":integrity.get("silverGameLeaks")==0,
            "gameMediaCannotLeakIntoSilver":integrity.get("collectionGameLeaks")==0,
            "noLowConfidenceAssigned":integrity.get("lowConfidenceAssigned")==0,
            "noCrossEventAssignedAssets":integrity.get("crossEventAssignedAssets")==0,
            "noLowConfidenceCollectionLinks":integrity.get("lowConfidenceCollectionLinks")==0,
            "allAssetsAccountedFor":self.report["unaccountedAssets"]==0,
        }
        self.report["checks"]=checks; self.report["passed"]=all(checks.values()); self.report["completedAt"]=time.time(); self.report["durationSeconds"]=round(self.report["completedAt"]-self.started_at,3)
        return self.report

    def rebuild(self, *, force=False):
        if not self.source_path.exists(): raise FileNotFoundError(self.source_path)
        if self.source_path.resolve()==self.output_path.resolve(): raise ValueError("v4 rebuild output must be a different file from the source database")
        if self.output_path.exists():
            if not force: raise FileExistsError(self.output_path)
            self.output_path.unlink()
        self.output_path.parent.mkdir(parents=True,exist_ok=True)
        self.repo=HistoryRepository(self.output_path)
        with closing(self._src()) as src:
            self._copy_score_skeleton(src); self._copy_event_skeleton(src); self._index_events()
            self._import_legacy_collections(src); self._import_normalized_media(src); self._import_day_cache_media(src)
        self._progress("Resolving residual legacy association conflicts")
        self._resolve_integrity_conflicts()
        self._progress("Running hard v4 integrity audit")
        return self._finalize_accounting()


def backup_database(source_path, backup_path=None):
    source=Path(source_path)
    if backup_path is None:
        stamp=datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"); backup_path=source.with_name(f"{source.stem}-pre-v4-{stamp}{source.suffix}")
    backup=Path(backup_path); backup.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(backup) as dst: src.backup(dst)
    return backup


def atomic_install(rebuilt_path, production_path, *, backup=True):
    rebuilt=Path(rebuilt_path); production=Path(production_path)
    if not rebuilt.exists(): raise FileNotFoundError(rebuilt)
    repo=HistoryRepository(rebuilt); integrity=repo.catalog_integrity()
    if integrity.get("schemaVersion")!=4 or integrity.get("silverGameLeaks") or integrity.get("collectionGameLeaks") or integrity.get("lowConfidenceAssigned") or integrity.get("crossEventAssignedAssets") or integrity.get("lowConfidenceCollectionLinks"):
        raise RuntimeError(f"Refusing install; integrity check failed: {integrity}")
    backup_path=None
    if production.exists() and backup: backup_path=backup_database(production)
    tmp=production.with_suffix(production.suffix+".installing")
    if tmp.exists(): tmp.unlink()
    shutil.copy2(rebuilt,tmp); os.replace(tmp,production)
    return {"installed":str(production),"backup":str(backup_path) if backup_path else "","integrity":integrity}

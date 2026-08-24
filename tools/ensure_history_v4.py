#!/usr/bin/env python3
"""Safe offline preflight for the Sports Big Board v4 history catalog.

v4.1.1 makes a hard distinction between two classes of catalog health:

* STRUCTURAL integrity decides whether a normalized v4 database is usable at all.
  Only structural corruption/incompleteness may trigger an offline reconstruction.
* RELATIONSHIP integrity is repairable application state. Matcher/classifier
  upgrades are handled in place after startup and must never erase discovery,
  backfill, verification, or attempt-ledger progress.

A legacy or structurally incomplete catalog is still backed up, reconstructed into
an adjacent database, audited, and atomically installed while the backend is
stopped. A structurally healthy normalized v4 catalog is preserved byte-for-byte
except for an optional rollback snapshot when an in-place relationship repair is
pending.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from sbb.catalog_contract import CATALOG_SCHEMA_VERSION, EVENT_MATCHER_VERSION, MEDIA_CLASSIFIER_VERSION
from sbb.history_rebuild import HistoryCatalogRebuilder, backup_database, atomic_install
from sbb.history_repository import HistoryRepository

V4_REQUIRED_TABLES=(
    "history_catalog_meta",
    "history_day",
    "history_catalog_event",
    "history_source_media",
    "history_event_media",
    "history_collection",
    "history_collection_media",
    "history_media_segment",
    "history_media_verification",
    "history_discovery_attempt",
    "history_assignment_review",
)
RELATIONSHIP_INTEGRITY_KEYS=(
    "silverGameLeaks",
    "collectionGameLeaks",
    "lowConfidenceAssigned",
    "crossEventAssignedAssets",
    "lowConfidenceCollectionLinks",
)


def _table_exists(conn, name):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())


def _row_count(conn, table, where="", params=()):
    if not _table_exists(conn,table):
        return 0
    sql=f"SELECT COUNT(*) FROM {table}"
    if where:
        sql+=f" WHERE {where}"
    try:
        return int(conn.execute(sql,params).fetchone()[0] or 0)
    except Exception:
        return 0


def _meta_value(conn, key, default=""):
    if not _table_exists(conn,"history_catalog_meta"):
        return default
    try:
        row=conn.execute("SELECT value FROM history_catalog_meta WHERE key=?",(key,)).fetchone()
        return row[0] if row else default
    except Exception:
        return default


def inspect_catalog(path: Path):
    """Read-only structural inspection; never import/initialize HistoryRepository.

    Relationship quality is deliberately *not* a rebuild criterion. A normalized
    database can contain stale matcher relationships and still be structurally
    valid; the application repairs those links in place.
    """
    path=Path(path)
    if not path.exists() or path.stat().st_size==0:
        return {
            "exists":False,"catalogSchemaVersion":0,"legacy":False,
            "needsRebuild":False,"reason":"NEW_CATALOG","structuralOk":True,
        }
    try:
        with sqlite3.connect(path) as conn:
            version=0
            if _table_exists(conn,"history_catalog_meta"):
                for meta_key in ("catalog_schema_version","catalogSchemaVersion","schemaVersion"):
                    raw=_meta_value(conn,meta_key,"")
                    if raw not in (None,""):
                        try:
                            version=int(raw)
                        except Exception:
                            version=0
                        break

            legacy_tables=[name for name in ("history_day","history_event","history_media_asset") if _table_exists(conn,name)]
            legacy_counts={name:_row_count(conn,name) for name in legacy_tables}
            legacy_rows=sum(legacy_counts.values())
            legacy_media_rows=legacy_counts.get("history_media_asset",0)
            legacy_media_days=_row_count(conn,"history_day","media_json IS NOT NULL AND media_json<>'' AND media_json<>'[]'")
            legacy_event_rows=legacy_counts.get("history_event",0)
            recoverable_legacy=bool(legacy_media_rows or legacy_media_days or legacy_event_rows)

            present_tables={name for name in V4_REQUIRED_TABLES if _table_exists(conn,name)}
            missing_tables=[name for name in V4_REQUIRED_TABLES if name not in present_tables]
            v4_core_tables=all(_table_exists(conn,name) for name in (
                "history_source_media","history_catalog_event","history_event_media",
                "history_collection","history_collection_media",
            ))
            v4_counts={
                "sourceAssets":_row_count(conn,"history_source_media"),
                "events":_row_count(conn,"history_catalog_event"),
                "eventLinks":_row_count(conn,"history_event_media"),
                "collections":_row_count(conn,"history_collection"),
                "collectionLinks":_row_count(conn,"history_collection_media"),
                "reviewRows":_row_count(conn,"history_assignment_review"),
                "discoveryAttempts":_row_count(conn,"history_discovery_attempt"),
            }
            quick_rows=[]
            try:
                quick_rows=[str(r[0]) for r in conn.execute("PRAGMA quick_check").fetchall()]
            except Exception as exc:
                quick_rows=[f"ERROR:{exc}"]
            sqlite_ok=(quick_rows==["ok"])
            try:
                foreign_key_violations=len(conn.execute("PRAGMA foreign_key_check").fetchall())
            except Exception:
                foreign_key_violations=-1
            try:
                repair_version=int(_meta_value(conn,"event_association_repair_version","0") or 0)
            except Exception:
                repair_version=0
            try:
                collection_repair_version=int(_meta_value(conn,"collection_association_repair_version","0") or 0)
            except Exception:
                collection_repair_version=0

            base={
                "exists":True,"catalogSchemaVersion":version,
                "legacyRows":legacy_rows,"legacyMediaRows":legacy_media_rows,
                "legacyMediaDays":legacy_media_days,"legacyEventRows":legacy_event_rows,
                "v4":v4_counts,"sqliteQuickCheck":quick_rows[:20],"sqliteOk":sqlite_ok,
                "foreignKeyViolations":foreign_key_violations,
                "associationRepairVersion":repair_version,
                "currentEventMatcherVersion":EVENT_MATCHER_VERSION,
                "collectionAssociationRepairVersion":collection_repair_version,
                "currentMediaClassifierVersion":MEDIA_CLASSIFIER_VERSION,
            }

            if version==CATALOG_SCHEMA_VERSION and v4_core_tables:
                structural=[]
                # Missing additive normalized tables are structural: the server
                # must never silently infer a healthy baseline from a partial shell.
                if missing_tables:
                    structural.append("MISSING_V4_TABLES:"+",".join(missing_tables))
                if not sqlite_ok:
                    structural.append("SQLITE_QUICK_CHECK_FAILED")
                if foreign_key_violations:
                    structural.append("FOREIGN_KEY_VIOLATIONS")
                if (v4_counts["eventLinks"] or v4_counts["collectionLinks"]) and not v4_counts["sourceAssets"]:
                    structural.append("RELATIONSHIPS_WITHOUT_SOURCE_ASSETS")
                if legacy_media_rows and not v4_counts["sourceAssets"]:
                    structural.append("LEGACY_MEDIA_NOT_NORMALIZED")
                if legacy_event_rows and not v4_counts["events"]:
                    structural.append("LEGACY_EVENTS_NOT_NORMALIZED")
                if structural:
                    return {
                        **base,"legacy":recoverable_legacy,"needsRebuild":True,"structuralOk":False,
                        "reason":"V4_STRUCTURAL_INVALID_WITH_LEGACY" if recoverable_legacy else "V4_STRUCTURAL_INVALID",
                        "structuralIssues":structural,"legacyTables":legacy_tables,
                    }
                return {
                    **base,"legacy":False,"needsRebuild":False,"structuralOk":True,
                    "reason":"V4_READY",
                    "repairVersionStale":repair_version<EVENT_MATCHER_VERSION,
                    "collectionRepairVersionStale":collection_repair_version<MEDIA_CLASSIFIER_VERSION,
                }

            if legacy_tables and recoverable_legacy:
                return {
                    **base,"legacy":True,"needsRebuild":True,"structuralOk":False,
                    "reason":"LEGACY_CATALOG","legacyTables":legacy_tables,
                }
            return {
                **base,"legacy":False,"needsRebuild":True,"structuralOk":False,
                "reason":"UNKNOWN_NONEMPTY_CATALOG","legacyTables":legacy_tables,
            }
    except sqlite3.DatabaseError as exc:
        return {
            "exists":True,"catalogSchemaVersion":0,"legacy":False,"needsRebuild":True,
            "structuralOk":False,"reason":"SQLITE_ERROR","error":str(exc),
        }


def _relationship_issues(integrity):
    return {key:int(integrity.get(key) or 0) for key in RELATIONSHIP_INTEGRITY_KEYS if int(integrity.get(key) or 0)>0}


def _relationship_integrity_ok(integrity):
    return not _relationship_issues(integrity)


def _structural_integrity_ok(snapshot, integrity=None):
    if not snapshot.get("exists"):
        return True
    if snapshot.get("catalogSchemaVersion")!=CATALOG_SCHEMA_VERSION:
        return False
    if snapshot.get("needsRebuild") or not snapshot.get("structuralOk",False):
        return False
    if integrity is not None and int(integrity.get("schemaVersion") or 0)!=CATALOG_SCHEMA_VERSION:
        return False
    return True


def _recoverable_from_snapshot(snapshot):
    return bool(snapshot.get("legacyMediaRows") or snapshot.get("legacyMediaDays") or snapshot.get("legacyEventRows"))


def _find_recovery_catalog(backup_dir: Path, current_db: Path):
    """Return newest backup that still contains usable legacy reconstruction evidence."""
    backup_dir=Path(backup_dir)
    if not backup_dir.exists():
        return None
    candidates=[]
    for pattern in ("history-pre-v4-*.sqlite3","history*.sqlite3"):
        for candidate in backup_dir.glob(pattern):
            try:
                if candidate.resolve()==current_db.resolve() or candidate.stat().st_size==0:
                    continue
                candidates.append(candidate)
            except OSError:
                continue
    seen=set()
    for candidate in sorted(candidates,key=lambda q:q.stat().st_mtime,reverse=True):
        key=str(candidate.resolve())
        if key in seen:
            continue
        seen.add(key)
        snap=inspect_catalog(candidate)
        if _recoverable_from_snapshot(snap):
            return candidate,snap
    return None


def _repair_backup_if_needed(db: Path, backup_dir: Path, before, integrity):
    """Snapshot a healthy catalog only when startup will mutate relationships.

    This backup is for deployment rollback only. It is not a reconstruction
    source and no discovery fields are rewritten by the preflight itself.
    """
    issues=_relationship_issues(integrity)
    stale=bool(before.get("repairVersionStale") or before.get("collectionRepairVersionStale"))
    required=bool(issues or stale)
    if not required:
        return required,"",issues
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path=backup_dir/f"history-pre-relation-repair-v{EVENT_MATCHER_VERSION}-{stamp}.sqlite3"
    backup_database(db,path)
    return required,str(path),issues


def main():
    p=argparse.ArgumentParser(description="Ensure a Sports Big Board history catalog is a structurally valid v4 normalized baseline.")
    default_state=Path(os.environ.get("SBB_STATE_DIR") or (Path.home()/".sports-big-board")).expanduser()
    p.add_argument("--state-dir",default=str(default_state))
    p.add_argument("--database",help="Override history.sqlite3 path")
    p.add_argument("--backup-dir",help="Directory for immutable backups and reconciliation reports")
    p.add_argument("--check-only",action="store_true",help="Inspect only; never rebuild/install or create a repair rollback snapshot")
    args=p.parse_args()

    state=Path(args.state_dir).expanduser().resolve()
    db=Path(args.database).expanduser().resolve() if args.database else state/"cache"/"history.sqlite3"
    backup_dir=Path(args.backup_dir).expanduser().resolve() if args.backup_dir else state/"backups"
    state.mkdir(parents=True,exist_ok=True)
    db.parent.mkdir(parents=True,exist_ok=True)
    backup_dir.mkdir(parents=True,exist_ok=True)
    before=inspect_catalog(db)
    result={
        "ok":True,"database":str(db),"before":before,"action":"NONE",
        "catalogSchemaVersion":CATALOG_SCHEMA_VERSION,"eventMatcherVersion":EVENT_MATCHER_VERSION,
        "mediaClassifierVersion":MEDIA_CLASSIFIER_VERSION,
    }
    recoverable_reasons={
        "LEGACY_CATALOG","V4_STRUCTURAL_INVALID_WITH_LEGACY",
        "V4_STRUCTURAL_INVALID_RECOVER_FROM_BACKUP","V4_INCOMPLETE_RECOVER_FROM_BACKUP",
    }

    if args.check_only:
        if not before.get("exists"):
            result["ok"]=True
        elif not before.get("needsRebuild"):
            repo=HistoryRepository(db)
            integrity=repo.catalog_integrity()
            issues=_relationship_issues(integrity)
            result.update(
                integrity=integrity,
                structuralOk=_structural_integrity_ok(before,integrity),
                relationshipIntegrityOk=not bool(issues),
                repairableRelationshipIssues=issues,
                repairRequired=bool(issues or before.get("repairVersionStale") or before.get("collectionRepairVersionStale")),
            )
            result["ok"]=bool(result["structuralOk"])
        else:
            result["ok"]=before.get("reason") in recoverable_reasons or bool(_find_recovery_catalog(backup_dir,db))
        print(json.dumps(result,sort_keys=True))
        return 0 if result["ok"] else 2

    if not before.get("exists"):
        result["action"]="NEW_CATALOG"
        print(json.dumps(result,sort_keys=True))
        return 0

    rebuild_source=db
    rebuild_source_snapshot=before

    # v4.1.1 invariant: a structurally healthy normalized catalog is NEVER
    # reconstructed just because matcher/classifier relationships are stale.
    # Relationship drift is application state and is repaired in place after
    # startup, preserving discovery/backfill/verification/attempt history.
    if not before.get("needsRebuild"):
        repo=HistoryRepository(db)
        integrity=repo.catalog_integrity()
        if _structural_integrity_ok(before,integrity):
            repair_required,rollback_backup,issues=_repair_backup_if_needed(db,backup_dir,before,integrity)
            if repair_required:
                print(
                    "[v4 preflight] Structurally healthy normalized catalog preserved; "
                    "relationship drift will be repaired in place after startup. No reconstruction will occur.",
                    file=sys.stderr,flush=True,
                )
            result.update(
                action="V4_ALREADY_READY",
                integrity=integrity,
                structuralOk=True,
                relationshipIntegrityOk=not bool(issues),
                repairableRelationshipIssues=issues,
                repairRequired=repair_required,
                rollbackBackup=rollback_backup,
                ok=True,
            )
            print(json.dumps(result,sort_keys=True))
            return 0
        # Defensive fallback: inspect_catalog should already have classified this
        # as structural damage, but never silently accept a contradictory state.
        before={**before,"needsRebuild":True,"structuralOk":False,"reason":"V4_STRUCTURAL_INVALID_WITH_LEGACY" if _recoverable_from_snapshot(before) else "V4_STRUCTURAL_INVALID"}
        result["before"]=before

    # Structural/legacy failures reconstruct from embedded evidence when possible,
    # otherwise from the newest persistent legacy recovery snapshot.
    if before.get("needsRebuild") and rebuild_source==db:
        if before.get("reason") in {"LEGACY_CATALOG","V4_STRUCTURAL_INVALID_WITH_LEGACY"} and _recoverable_from_snapshot(before):
            rebuild_source=db
            rebuild_source_snapshot=before
        else:
            recovery=_find_recovery_catalog(backup_dir,db)
            if recovery:
                rebuild_source,rebuild_source_snapshot=recovery
                previous_reason=before.get("reason")
                before={
                    **before,"needsRebuild":True,
                    "reason":"V4_STRUCTURAL_INVALID_RECOVER_FROM_BACKUP" if str(previous_reason).startswith("V4_") else "LEGACY_RECOVER_FROM_BACKUP",
                    "recoverySource":str(rebuild_source),"recoverySnapshot":rebuild_source_snapshot,
                }
                result["before"]=before
                print(f"[v4 preflight] Using recovery catalog {rebuild_source}",file=sys.stderr,flush=True)
            else:
                result.update(
                    ok=False,action="REFUSED",
                    error=f"Refusing automatic reconstruction of {before.get('reason')}; no usable legacy backup exists",
                )
                print(json.dumps(result,sort_keys=True))
                return 3

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path=backup_dir/f"history-pre-v4-{stamp}.sqlite3"
    rebuild_path=db.with_name("history-v4-rebuild.sqlite3")
    report_path=backup_dir/f"history-v4-rebuild-{stamp}.report.json"
    print(f"[v4 preflight] Backing up legacy/structurally invalid catalog to {backup_path}",file=sys.stderr,flush=True)
    rollback=backup_database(db,backup_path)
    print(f"[v4 preflight] Reconstructing normalized catalog at {rebuild_path}",file=sys.stderr,flush=True)
    print(f"[v4 preflight] Reconstruction source: {rebuild_source}",file=sys.stderr,flush=True)
    report=HistoryCatalogRebuilder(rebuild_source,rebuild_path).rebuild(force=True)
    report_path.write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8")
    print(f"[v4 preflight] Reconciliation report: {report_path}",file=sys.stderr,flush=True)
    result.update(
        action="REBUILT",rollbackBackup=str(rollback),rebuildSource=str(rebuild_source),
        rebuildSourceSnapshot=rebuild_source_snapshot,rebuildDatabase=str(rebuild_path),
        reconciliationReport=str(report_path),rebuild=report,
    )
    if not report.get("passed"):
        result.update(ok=False,error="V4_REBUILD_AUDIT_FAILED")
        print(json.dumps(result,sort_keys=True))
        return 2
    installed=atomic_install(rebuild_path,db,backup=False)
    result["install"]=installed
    after=inspect_catalog(db)
    result["after"]=after
    repo=HistoryRepository(db)
    integrity=repo.catalog_integrity()
    result["integrity"]=integrity
    # A newly reconstructed catalog is expected to pass both structural and
    # relationship gates. Only existing normalized catalogs receive repair-in-place.
    result["ok"]=_structural_integrity_ok(after,integrity) and _relationship_integrity_ok(integrity)
    print(json.dumps(result,sort_keys=True))
    return 0 if result["ok"] else 2


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({
            "ok":False,"action":"ERROR","error":f"{type(exc).__name__}: {exc}",
            "catalogSchemaVersion":CATALOG_SCHEMA_VERSION,
        },sort_keys=True),flush=True)
        raise SystemExit(4)

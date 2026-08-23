#!/usr/bin/env python3
"""Safe offline preflight for the Sports Big Board v4 history catalog.

The preflight never performs an in-place schema rewrite. A legacy catalog is
backed up, reconstructed into a sibling database, audited, and only then copied
into the production history.sqlite3 path. It is designed to run while the Sports
Big Board backend is stopped (deployment and local launch scripts do this).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from sbb.catalog_contract import CATALOG_SCHEMA_VERSION
from sbb.history_rebuild import HistoryCatalogRebuilder, backup_database, atomic_install
from sbb.history_repository import HistoryRepository


def _table_exists(conn, name):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())


def _row_count(conn, table, where="", params=()):
    if not _table_exists(conn,table): return 0
    sql=f"SELECT COUNT(*) FROM {table}"
    if where: sql+=f" WHERE {where}"
    try: return int(conn.execute(sql,params).fetchone()[0] or 0)
    except Exception: return 0


def inspect_catalog(path: Path):
    """Inspect without importing HistoryRepository, so a v3 DB is never mutated.

    v4 readiness is intentionally stricter than "schema version == 4". A failed
    transition can leave the additive v4 tables/meta beside intact legacy rows.
    Such a mixed catalog is recoverable, but it is not production-ready.
    """
    path=Path(path)
    if not path.exists() or path.stat().st_size==0:
        return {"exists":False,"catalogSchemaVersion":0,"legacy":False,"needsRebuild":False,"reason":"NEW_CATALOG"}
    try:
        with sqlite3.connect(path) as conn:
            version=0
            if _table_exists(conn,"history_catalog_meta"):
                row=None
                for meta_key in ("catalog_schema_version","catalogSchemaVersion","schemaVersion"):
                    row=conn.execute("SELECT value FROM history_catalog_meta WHERE key=?",(meta_key,)).fetchone()
                    if row: break
                try: version=int(row[0]) if row else 0
                except Exception: version=0

            legacy_tables=[name for name in ("history_day","history_event","history_media_asset") if _table_exists(conn,name)]
            legacy_counts={name:_row_count(conn,name) for name in legacy_tables}
            legacy_rows=sum(legacy_counts.values())
            legacy_media_rows=legacy_counts.get("history_media_asset",0)
            legacy_media_days=_row_count(conn,"history_day","media_json IS NOT NULL AND media_json<>'' AND media_json<>'[]'")
            legacy_event_rows=legacy_counts.get("history_event",0)
            recoverable_legacy=bool(legacy_media_rows or legacy_media_days or legacy_event_rows)

            v4_tables=all(_table_exists(conn,name) for name in ("history_source_media","history_catalog_event","history_event_media","history_collection","history_collection_media"))
            v4_counts={
                "sourceAssets":_row_count(conn,"history_source_media"),
                "events":_row_count(conn,"history_catalog_event"),
                "eventLinks":_row_count(conn,"history_event_media"),
                "collections":_row_count(conn,"history_collection"),
                "collectionLinks":_row_count(conn,"history_collection_media"),
                "reviewRows":_row_count(conn,"history_assignment_review"),
            }
            base={"exists":True,"catalogSchemaVersion":version,"legacyRows":legacy_rows,"legacyMediaRows":legacy_media_rows,
                  "legacyMediaDays":legacy_media_days,"legacyEventRows":legacy_event_rows,"v4":v4_counts}

            if version==CATALOG_SCHEMA_VERSION and v4_tables:
                incomplete=[]
                if (v4_counts["eventLinks"] or v4_counts["collectionLinks"]) and not v4_counts["sourceAssets"]:
                    incomplete.append("RELATIONSHIPS_WITHOUT_SOURCE_ASSETS")
                if legacy_media_rows and not v4_counts["sourceAssets"]:
                    incomplete.append("LEGACY_MEDIA_NOT_NORMALIZED")
                if legacy_event_rows and not v4_counts["events"]:
                    incomplete.append("LEGACY_EVENTS_NOT_NORMALIZED")
                if incomplete:
                    return {**base,"legacy":recoverable_legacy,"needsRebuild":True,
                            "reason":"V4_INCOMPLETE_WITH_LEGACY" if recoverable_legacy else "V4_INCOMPLETE",
                            "incompleteReasons":incomplete,"legacyTables":legacy_tables}
                return {**base,"legacy":False,"needsRebuild":False,"reason":"V4_READY"}

            if legacy_tables and recoverable_legacy:
                return {**base,"legacy":True,"needsRebuild":True,"reason":"LEGACY_CATALOG","legacyTables":legacy_tables}
            # A nonempty unknown DB is safer to quarantine than silently initialize.
            return {**base,"legacy":False,"needsRebuild":True,"reason":"UNKNOWN_NONEMPTY_CATALOG","legacyTables":legacy_tables}
    except sqlite3.DatabaseError as exc:
        return {"exists":True,"catalogSchemaVersion":0,"legacy":False,"needsRebuild":True,"reason":"SQLITE_ERROR","error":str(exc)}


def _hard_integrity_ok(integrity):
    return integrity.get("schemaVersion")==CATALOG_SCHEMA_VERSION and not integrity.get("silverGameLeaks") and not integrity.get("collectionGameLeaks") and not integrity.get("lowConfidenceAssigned") and not integrity.get("crossEventAssignedAssets") and not integrity.get("lowConfidenceCollectionLinks")


def _recoverable_from_snapshot(snapshot):
    return bool(snapshot.get("legacyMediaRows") or snapshot.get("legacyMediaDays") or snapshot.get("legacyEventRows"))


def _find_recovery_catalog(backup_dir: Path, current_db: Path):
    """Return newest backup that still contains usable legacy reconstruction evidence."""
    backup_dir=Path(backup_dir)
    if not backup_dir.exists(): return None
    candidates=[]
    for pattern in ("history-pre-v4-*.sqlite3","history*.sqlite3"):
        for candidate in backup_dir.glob(pattern):
            try:
                if candidate.resolve()==current_db.resolve() or candidate.stat().st_size==0: continue
                candidates.append(candidate)
            except OSError: continue
    seen=set()
    for candidate in sorted(candidates,key=lambda q:q.stat().st_mtime,reverse=True):
        key=str(candidate.resolve())
        if key in seen: continue
        seen.add(key)
        snap=inspect_catalog(candidate)
        if _recoverable_from_snapshot(snap):
            return candidate,snap
    return None


def main():
    p=argparse.ArgumentParser(description="Ensure a Sports Big Board history catalog is a validated v4 normalized baseline.")
    default_state=Path(os.environ.get("SBB_STATE_DIR") or (Path.home()/".sports-big-board")).expanduser()
    p.add_argument("--state-dir",default=str(default_state))
    p.add_argument("--database",help="Override history.sqlite3 path")
    p.add_argument("--backup-dir",help="Directory for immutable pre-v4 backup and reconciliation report")
    p.add_argument("--check-only",action="store_true",help="Inspect only; never rebuild/install")
    args=p.parse_args()

    state=Path(args.state_dir).expanduser().resolve()
    db=Path(args.database).expanduser().resolve() if args.database else state/"cache"/"history.sqlite3"
    backup_dir=Path(args.backup_dir).expanduser().resolve() if args.backup_dir else state/"backups"
    state.mkdir(parents=True,exist_ok=True); db.parent.mkdir(parents=True,exist_ok=True); backup_dir.mkdir(parents=True,exist_ok=True)
    before=inspect_catalog(db)
    result={"ok":True,"database":str(db),"before":before,"action":"NONE","catalogSchemaVersion":CATALOG_SCHEMA_VERSION}
    recoverable_reasons={"LEGACY_CATALOG","V4_INCOMPLETE_WITH_LEGACY","V4_INVALID_WITH_LEGACY","V4_INVALID_RECOVER_FROM_BACKUP","V4_INCOMPLETE_RECOVER_FROM_BACKUP"}

    if args.check_only:
        if not before.get("exists"):
            result["ok"]=True
        elif not before.get("needsRebuild"):
            repo=HistoryRepository(db); integrity=repo.catalog_integrity(); result["integrity"]=integrity
            result["ok"]=_hard_integrity_ok(integrity)
        else:
            result["ok"]=before.get("reason") in recoverable_reasons or bool(_find_recovery_catalog(backup_dir,db))
        print(json.dumps(result,sort_keys=True)); return 0 if result["ok"] else 2

    if not before.get("exists"):
        # Let the server create a new v4 catalog on first start.
        result["action"]="NEW_CATALOG"; print(json.dumps(result,sort_keys=True)); return 0

    rebuild_source=db
    rebuild_source_snapshot=before

    # A v4-shaped database is not "ready" merely because the additive schema
    # exists. Run the hard integrity gate before accepting it. If the gate fails
    # and legacy evidence is still embedded, deliberately fall back into the
    # reconstruction path instead of repeatedly returning V4_ALREADY_READY/2.
    if not before.get("needsRebuild"):
        repo=HistoryRepository(db); integrity=repo.catalog_integrity()
        if _hard_integrity_ok(integrity):
            result.update(action="V4_ALREADY_READY",integrity=integrity,ok=True)
            print(json.dumps(result,sort_keys=True)); return 0
        if _recoverable_from_snapshot(before):
            before={**before,"legacy":True,"needsRebuild":True,"reason":"V4_INVALID_WITH_LEGACY","invalidIntegrity":integrity}
            result["before"]=before; rebuild_source_snapshot=before
            print("[v4 preflight] Existing v4-shaped catalog failed integrity; preserved legacy rows will be used as reconstruction evidence.",file=sys.stderr,flush=True)
        else:
            recovery=_find_recovery_catalog(backup_dir,db)
            if recovery:
                rebuild_source,rebuild_source_snapshot=recovery
                before={**before,"needsRebuild":True,"reason":"V4_INVALID_RECOVER_FROM_BACKUP","invalidIntegrity":integrity,
                        "recoverySource":str(rebuild_source),"recoverySnapshot":rebuild_source_snapshot}
                result["before"]=before
                print(f"[v4 preflight] Existing v4 catalog failed integrity; recovering from backup {rebuild_source}",file=sys.stderr,flush=True)
            else:
                result.update(ok=False,action="REFUSED",integrity=integrity,error="V4 catalog failed integrity and no recoverable legacy source exists")
                print(json.dumps(result,sort_keys=True)); return 3

    # Obvious incomplete/legacy states reconstruct from themselves when they
    # still contain source evidence. Otherwise search persistent pre-v4 backups.
    if before.get("needsRebuild") and rebuild_source==db:
        if before.get("reason") in {"LEGACY_CATALOG","V4_INCOMPLETE_WITH_LEGACY","V4_INVALID_WITH_LEGACY"} and _recoverable_from_snapshot(before):
            rebuild_source=db; rebuild_source_snapshot=before
        else:
            recovery=_find_recovery_catalog(backup_dir,db)
            if recovery:
                rebuild_source,rebuild_source_snapshot=recovery
                previous_reason=before.get("reason")
                before={**before,"needsRebuild":True,
                        "reason":"V4_INCOMPLETE_RECOVER_FROM_BACKUP" if str(previous_reason).startswith("V4_") else "LEGACY_RECOVER_FROM_BACKUP",
                        "recoverySource":str(rebuild_source),"recoverySnapshot":rebuild_source_snapshot}
                result["before"]=before
                print(f"[v4 preflight] Using recovery catalog {rebuild_source}",file=sys.stderr,flush=True)
            else:
                result.update(ok=False,action="REFUSED",error=f"Refusing automatic reconstruction of {before.get('reason')}; no usable legacy backup exists")
                print(json.dumps(result,sort_keys=True)); return 3

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path=backup_dir/f"history-pre-v4-{stamp}.sqlite3"
    rebuild_path=db.with_name("history-v4-rebuild.sqlite3")
    report_path=backup_dir/f"history-v4-rebuild-{stamp}.report.json"
    print(f"[v4 preflight] Backing up legacy catalog to {backup_path}",file=sys.stderr,flush=True)
    rollback=backup_database(db,backup_path)
    print(f"[v4 preflight] Reconstructing normalized catalog at {rebuild_path}",file=sys.stderr,flush=True)
    print(f"[v4 preflight] Reconstruction source: {rebuild_source}",file=sys.stderr,flush=True)
    report=HistoryCatalogRebuilder(rebuild_source,rebuild_path).rebuild(force=True)
    report_path.write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8")
    print(f"[v4 preflight] Reconciliation report: {report_path}",file=sys.stderr,flush=True)
    result.update(action="REBUILT",rollbackBackup=str(rollback),rebuildSource=str(rebuild_source),rebuildSourceSnapshot=rebuild_source_snapshot,rebuildDatabase=str(rebuild_path),reconciliationReport=str(report_path),rebuild=report)
    if not report.get("passed"):
        result.update(ok=False,error="V4_REBUILD_AUDIT_FAILED")
        print(json.dumps(result,sort_keys=True)); return 2
    installed=atomic_install(rebuild_path,db,backup=False); result["install"]=installed
    after=inspect_catalog(db); result["after"]=after
    repo=HistoryRepository(db); integrity=repo.catalog_integrity(); result["integrity"]=integrity
    result["ok"]=after.get("catalogSchemaVersion")==CATALOG_SCHEMA_VERSION and not after.get("needsRebuild") and _hard_integrity_ok(integrity)
    print(json.dumps(result,sort_keys=True)); return 0 if result["ok"] else 2

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"ok":False,"action":"ERROR","error":f"{type(exc).__name__}: {exc}","catalogSchemaVersion":CATALOG_SCHEMA_VERSION},sort_keys=True),flush=True)
        raise SystemExit(4)

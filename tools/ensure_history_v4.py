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


def inspect_catalog(path: Path):
    """Inspect without importing HistoryRepository, so a v3 DB is never mutated."""
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
            v4_tables=all(_table_exists(conn,name) for name in ("history_source_media","history_catalog_event","history_event_media","history_collection"))
            legacy_rows=0
            for table in ("history_day","history_event","history_media_asset"):
                if _table_exists(conn,table):
                    try: legacy_rows+=int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)
                    except Exception: pass
            if version==CATALOG_SCHEMA_VERSION and v4_tables:
                return {"exists":True,"catalogSchemaVersion":version,"legacy":False,"needsRebuild":False,"reason":"V4_READY","legacyRows":legacy_rows}
            if legacy_tables and legacy_rows:
                return {"exists":True,"catalogSchemaVersion":version,"legacy":True,"needsRebuild":True,"reason":"LEGACY_CATALOG","legacyTables":legacy_tables,"legacyRows":legacy_rows}
            # A nonempty unknown DB is safer to quarantine than silently initialize.
            return {"exists":True,"catalogSchemaVersion":version,"legacy":False,"needsRebuild":True,"reason":"UNKNOWN_NONEMPTY_CATALOG","legacyTables":legacy_tables,"legacyRows":legacy_rows}
    except sqlite3.DatabaseError as exc:
        return {"exists":True,"catalogSchemaVersion":0,"legacy":False,"needsRebuild":True,"reason":"SQLITE_ERROR","error":str(exc)}


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
    if args.check_only:
        result["ok"]=not before.get("needsRebuild") or before.get("reason")=="LEGACY_CATALOG"
        print(json.dumps(result,sort_keys=True)); return 0
    if not before.get("exists"):
        # Let the server create a new v4 catalog on first start.
        result["action"]="NEW_CATALOG"; print(json.dumps(result,sort_keys=True)); return 0
    if not before.get("needsRebuild"):
        repo=HistoryRepository(db); integrity=repo.catalog_integrity(); result.update(action="V4_ALREADY_READY",integrity=integrity)
        result["ok"]=integrity.get("schemaVersion")==CATALOG_SCHEMA_VERSION and not integrity.get("silverGameLeaks") and not integrity.get("collectionGameLeaks") and not integrity.get("lowConfidenceAssigned") and not integrity.get("crossEventAssignedAssets") and not integrity.get("lowConfidenceCollectionLinks")
        print(json.dumps(result,sort_keys=True)); return 0 if result["ok"] else 2
    if before.get("reason") not in {"LEGACY_CATALOG"}:
        result.update(ok=False,action="REFUSED",error=f"Refusing automatic reconstruction of {before.get('reason')}")
        print(json.dumps(result,sort_keys=True)); return 3

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path=backup_dir/f"history-pre-v4-{stamp}.sqlite3"
    rebuild_path=db.with_name("history-v4-rebuild.sqlite3")
    report_path=backup_dir/f"history-v4-rebuild-{stamp}.report.json"
    print(f"[v4 preflight] Backing up legacy catalog to {backup_path}",file=sys.stderr,flush=True)
    rollback=backup_database(db,backup_path)
    print(f"[v4 preflight] Reconstructing normalized catalog at {rebuild_path}",file=sys.stderr,flush=True)
    report=HistoryCatalogRebuilder(db,rebuild_path).rebuild(force=True)
    report_path.write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8")
    print(f"[v4 preflight] Reconciliation report: {report_path}",file=sys.stderr,flush=True)
    result.update(action="REBUILT",rollbackBackup=str(rollback),rebuildDatabase=str(rebuild_path),reconciliationReport=str(report_path),rebuild=report)
    if not report.get("passed"):
        result.update(ok=False,error="V4_REBUILD_AUDIT_FAILED")
        print(json.dumps(result,sort_keys=True)); return 2
    installed=atomic_install(rebuild_path,db,backup=False); result["install"]=installed
    after=inspect_catalog(db); result["after"]=after
    repo=HistoryRepository(db); integrity=repo.catalog_integrity(); result["integrity"]=integrity
    result["ok"]=after.get("catalogSchemaVersion")==CATALOG_SCHEMA_VERSION and not after.get("needsRebuild") and not integrity.get("silverGameLeaks") and not integrity.get("collectionGameLeaks") and not integrity.get("lowConfidenceAssigned") and not integrity.get("crossEventAssignedAssets") and not integrity.get("lowConfidenceCollectionLinks")
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

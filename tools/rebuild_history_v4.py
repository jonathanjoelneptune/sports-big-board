#!/usr/bin/env python3
import argparse, json, os, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from sbb.history_rebuild import HistoryCatalogRebuilder, backup_database, atomic_install
from sbb.history_repository import HistoryRepository


def main():
    p=argparse.ArgumentParser(description="Build and audit a Sports Big Board v4 normalized history catalog without mutating the source DB.")
    p.add_argument("--source",required=True,help="Existing v3 history.sqlite3")
    p.add_argument("--output",help="New v4 database path; defaults beside source")
    p.add_argument("--report",help="JSON reconciliation report path")
    p.add_argument("--force",action="store_true",help="Replace an existing --output file")
    p.add_argument("--install",action="store_true",help="After a passing rebuild, atomically replace --source and keep a pre-v4 backup")
    p.add_argument("--audit-only",action="store_true",help="Audit an already-built v4 database at --source")
    args=p.parse_args()
    source=Path(args.source).expanduser().resolve()
    if args.audit_only:
        repo=HistoryRepository(source); result={"summary":repo.summary(),"integrity":repo.catalog_integrity()}; print(json.dumps(result,indent=2,sort_keys=True)); return 0
    output=Path(args.output).expanduser().resolve() if args.output else source.with_name("history-v4-rebuild.sqlite3")
    report_path=Path(args.report).expanduser().resolve() if args.report else output.with_suffix(".report.json")
    result=HistoryCatalogRebuilder(source,output).rebuild(force=args.force)
    report_path.write_text(json.dumps(result,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(result,indent=2,sort_keys=True)); print(f"Report: {report_path}")
    if not result.get("passed"):
        print("REBUILD AUDIT FAILED; source database was not changed.",file=sys.stderr); return 2
    if args.install:
        installed=atomic_install(output,source,backup=True); print(json.dumps(installed,indent=2,sort_keys=True))
    return 0

if __name__=="__main__": raise SystemExit(main())

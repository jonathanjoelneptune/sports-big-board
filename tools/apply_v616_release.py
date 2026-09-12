#!/usr/bin/env python3
"""Sports Big Board v6.1.6 always-on Media Audit + accelerated Repair release."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE = "6.1.5"
NEW = "6.1.6"
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".sh", ".yml", ".yaml"}
ACTIVE_DIRS = ("ui", "architecture", "sbb", "tests", "cloud", ".github")


def active_files(root):
    seen = set()
    for p in sorted(root.iterdir()):
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:
            seen.add(p)
            yield p
    checker = root / "tools" / "check_release_version.py"
    if checker.is_file() and checker not in seen:
        seen.add(checker)
        yield checker
    for dirname in ACTIVE_DIRS:
        base = root / dirname
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
                continue
            rel = p.relative_to(root)
            if any(part.startswith("sports-big-board-v") for part in rel.parts):
                continue
            if p not in seen:
                seen.add(p)
                yield p


def run_base(root):
    (root / "VERSION").write_text(BASE + "\n", encoding="utf-8")
    arch = root / "architecture" / "VERSION"
    arch.parent.mkdir(parents=True, exist_ok=True)
    arch.write_text(BASE + "\n", encoding="utf-8")
    subprocess.run(
        [sys.executable, str(root / "tools" / "apply_v615_release.py"), "--skip-check"],
        cwd=root,
        check=True,
    )


def replace_once(text, old, new, label):
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"ERROR: v6.1.6 patch anchor missing: {label}")


def patch_media_audit(root):
    path = root / "media_audit_service.py"
    text = path.read_text(encoding="utf-8")

    import_anchor = "from sbb.catalog_contract import VERIFICATION_VERSION\n"
    import_line = "from sbb.media_audit_continuous import DiscoveryCircuitBreaker, RollingAuditCoordinator\n"
    if import_line not in text:
        if import_anchor not in text:
            raise SystemExit("ERROR: Media Audit helper import anchor missing")
        text = text.replace(import_anchor, import_anchor + import_line, 1)

    safe_default = 'REPAIR_ENABLED = str(os.environ.get("SBB_MEDIA_REPAIR_ENABLED", "0")).lower() in {"1","true","yes","on"}'
    enabled_default = 'REPAIR_ENABLED = str(os.environ.get("SBB_MEDIA_REPAIR_ENABLED", "1")).lower() in {"1","true","yes","on"}'
    text = replace_once(text, safe_default, enabled_default, "restore Repair Engine default")

    config_block = '''REPAIR_WORKER_COUNT = max(1, min(3, int(os.environ.get("SBB_MEDIA_REPAIR_WORKERS", "2"))))
REPAIR_DISCOVERY_FAILURE_THRESHOLD = max(2, min(10, int(os.environ.get("SBB_MEDIA_REPAIR_DISCOVERY_FAILURE_THRESHOLD", "3"))))
REPAIR_DISCOVERY_CIRCUIT_SECONDS = max(60, int(os.environ.get("SBB_MEDIA_REPAIR_DISCOVERY_CIRCUIT_SECONDS", "900")))
REPAIR_EXTERNAL_CONCURRENCY = max(1, min(2, int(os.environ.get("SBB_MEDIA_REPAIR_EXTERNAL_CONCURRENCY", "1"))))
REPAIR_EXTERNAL_SEMAPHORE = threading.Semaphore(REPAIR_EXTERNAL_CONCURRENCY)
REPAIR_DISCOVERY_CIRCUIT = DiscoveryCircuitBreaker(REPAIR_DISCOVERY_FAILURE_THRESHOLD, REPAIR_DISCOVERY_CIRCUIT_SECONDS)
ROLLING_AUDIT_ENABLED = str(os.environ.get("SBB_MEDIA_AUDIT_ROLLING_ENABLED", "1")).lower() in {"1","true","yes","on"}
ROLLING_AUDIT_INTERVAL_SECONDS = max(60.0, float(os.environ.get("SBB_MEDIA_AUDIT_ROLLING_INTERVAL_SECONDS", "300")))
ROLLING_AUDIT_BATCH_SIZE = max(25, min(1000, int(os.environ.get("SBB_MEDIA_AUDIT_ROLLING_BATCH_SIZE", "250"))))
ROLLING_AUDIT_CUTOFF_DAYS = max(1, min(7, int(os.environ.get("SBB_MEDIA_AUDIT_ROLLING_CUTOFF_DAYS", "1"))))
'''
    if "REPAIR_WORKER_COUNT = " not in text:
        text = text.replace(enabled_default + "\n", enabled_default + "\n" + config_block, 1)

    replacements = [
        (
            'REPAIR_RECENT_RETRY_SECONDS = max(300, int(os.environ.get("SBB_MEDIA_REPAIR_RECENT_RETRY_SECONDS", str(6 * 3600))))',
            'REPAIR_RECENT_RETRY_SECONDS = max(300, int(os.environ.get("SBB_MEDIA_REPAIR_RECENT_RETRY_SECONDS", str(15 * 60))))',
        ),
        (
            'REPAIR_MIDAGE_RETRY_SECONDS = max(1800, int(os.environ.get("SBB_MEDIA_REPAIR_MIDAGE_RETRY_SECONDS", str(24 * 3600))))',
            'REPAIR_MIDAGE_RETRY_SECONDS = max(1800, int(os.environ.get("SBB_MEDIA_REPAIR_MIDAGE_RETRY_SECONDS", str(2 * 3600))))',
        ),
        (
            'REPAIR_HISTORICAL_RETRY_SECONDS = max(3600, int(os.environ.get("SBB_MEDIA_REPAIR_HISTORICAL_RETRY_SECONDS", str(7 * 24 * 3600))))',
            'REPAIR_HISTORICAL_RETRY_SECONDS = max(3600, int(os.environ.get("SBB_MEDIA_REPAIR_HISTORICAL_RETRY_SECONDS", str(24 * 3600))))',
        ),
        (
            'REPAIR_SEED_SECONDS = max(60.0, float(os.environ.get("SBB_MEDIA_REPAIR_SEED_SECONDS", "1800")))',
            'REPAIR_SEED_SECONDS = max(60.0, float(os.environ.get("SBB_MEDIA_REPAIR_SEED_SECONDS", "300")))',
        ),
    ]
    for old, new in replacements:
        text = replace_once(text, old, new, old.split(" = ", 1)[0])
    text = text.replace(
        'AUDIT_GENERATION = "R20-PLAYBACK-EVIDENCE-CORROBORATION"',
        'AUDIT_GENERATION = "R21-CONTINUOUS-ROLLING-REPAIR"',
        1,
    )

    text = replace_once(
        text,
        '    def start_run(self, mode="ALL", start_date=""):\n',
        '    def start_run(self, mode="ALL", start_date="", max_games=0):\n',
        "bounded start_run",
    )
    text = replace_once(
        text,
        '        if mode not in {"ALL", "FAILED", "STALE"}:\n',
        '        if mode not in {"ALL", "FAILED", "STALE", "ROLLING"}:\n',
        "ROLLING mode allowlist",
    )
    text = replace_once(
        text,
        '            for event in events:\n                if mode != "ALL":\n',
        '            for event in events:\n                if max_games and ordinal >= int(max_games):\n                    break\n                if mode != "ALL":\n',
        "rolling batch bound",
    )

    old_prior = '''                    prior_q = conn.execute(
                        "SELECT health,state FROM history_media_audit_queue WHERE canonical_event_key=? ORDER BY run_id DESC LIMIT 1",
                        (event["canonicalEventKey"],),
                    ).fetchone()
                    prior_health = str(prior_q["health"] or "") if prior_q else ""
                    if mode == "FAILED" and (
'''
    new_prior = '''                    prior_q = conn.execute(
                        "SELECT health,state,completed_at FROM history_media_audit_queue WHERE canonical_event_key=? ORDER BY run_id DESC LIMIT 1",
                        (event["canonicalEventKey"],),
                    ).fetchone()
                    prior_health = str(prior_q["health"] or "") if prior_q else ""
                    prior_state = str(prior_q["state"] or "") if prior_q else ""
                    prior_completed = float(prior_q["completed_at"] or 0) if prior_q else 0
                    if mode == "ROLLING":
                        # Recent assessment is enough to keep rolling audit moving. A
                        # recent INCONCLUSIVE/no-package game stays in Repair instead
                        # of being re-audited every rolling batch.
                        if prior_state in {"DONE","FAILED","SKIPPED","DEFERRED"} and prior_completed >= now - FRESH_SECONDS:
                            continue
                        if pkg and float(pkg["certified_at"] or 0) >= now - FRESH_SECONDS:
                            continue
                    if mode == "FAILED" and (
'''
    text = replace_once(text, old_prior, new_prior, "rolling recent-assessment filter")

    active_anchor = '    def active_run(self):\n'
    backlog_method = '''    def rolling_backlog_count(self, cutoff_date, fresh_seconds=FRESH_SECONDS):
        """Count final games needing a fresh audit without re-churning recent inconclusives."""
        cutoff_date = str(cutoff_date or _today())[:10]
        stale_before = _now() - max(60, int(fresh_seconds or FRESH_SECONDS))
        with closing(self.connect(timeout=5)) as conn:
            rows = conn.execute(
                """WITH latest_audit AS (
                       SELECT canonical_event_key,MAX(completed_at) last_audited_at
                       FROM history_media_audit_queue
                       WHERE state IN ('DONE','FAILED','SKIPPED','DEFERRED') AND completed_at>0
                       GROUP BY canonical_event_key
                   )
                   SELECT e.canonical_event_key,e.event_date,e.event_json,e.final_at,
                          p.certified_at,COALESCE(a.last_audited_at,0) last_audited_at
                   FROM history_catalog_event e
                   LEFT JOIN history_media_canonical_package p ON p.canonical_event_key=e.canonical_event_key
                   LEFT JOIN latest_audit a ON a.canonical_event_key=e.canonical_event_key
                   WHERE e.event_date<=?""",
                (cutoff_date,),
            ).fetchall()
        count = 0
        for row in rows:
            event = _jloads(row["event_json"], {})
            if not _event_final(str(row["event_date"] or ""), float(row["final_at"] or 0), event):
                continue
            package_fresh = float(row["certified_at"] or 0) >= stale_before
            assessment_fresh = float(row["last_audited_at"] or 0) >= stale_before
            if not package_fresh and not assessment_fresh:
                count += 1
        return count

'''
    if "def rolling_backlog_count(" not in text:
        if active_anchor not in text:
            raise SystemExit("ERROR: active_run anchor missing")
        text = text.replace(active_anchor, backlog_method + active_anchor, 1)

    text = replace_once(
        text,
        '    def __init__(self, store, db_writer):\n        super().__init__(name="canonical-media-repair-engine")\n        self.store=store\n',
        '    def __init__(self, store, db_writer, worker_index=1, seed_owner=False):\n        self.worker_index=int(worker_index)\n        self.seed_owner=bool(seed_owner)\n        super().__init__(name=f"canonical-media-repair-engine-{self.worker_index}")\n        self.store=store\n',
        "repair worker identity",
    )
    text = replace_once(
        text,
        'return {"alive":self.is_alive(),"enabled":REPAIR_ENABLED,"current":cur,"lastError":self.last_error,"stats":stats,"trace":trace}',
        'return {"alive":self.is_alive(),"enabled":REPAIR_ENABLED,"workerIndex":self.worker_index,"seedOwner":self.seed_owner,"current":cur,"lastError":self.last_error,"stats":stats,"trace":trace}',
        "repair snapshot identity",
    )
    text = replace_once(
        text,
        '                if _now()-self.last_seed_at>=REPAIR_SEED_SECONDS:\n',
        '                if self.seed_owner and _now()-self.last_seed_at>=REPAIR_SEED_SECONDS:\n',
        "single repair seed owner",
    )

    discover_anchor = "    def _discover_once(self, job, pass_number):\n        context=self.store.repair_event_context(job['canonical_event_key'])\n"
    discover_gate = """    def _discover_once(self, job, pass_number):
        gate=REPAIR_DISCOVERY_CIRCUIT.before_request()
        if not gate.get('allowed'):
            retry_at=float(gate.get('retryAt') or 0)
            self._set(phase='DISCOVERY_CIRCUIT_OPEN',lastResult='DISCOVERY_CIRCUIT_OPEN',nextRetryAt=retry_at)
            self._trace('WARN','Repair exhaustive discovery circuit is open; skipping provider request',event=job['canonical_event_key'],retryAt=retry_at,reason=gate.get('reason') or '')
            return {"ok":False,"reason":"DISCOVERY_CIRCUIT_OPEN","infra":True,"circuitOpen":True,"retryAt":retry_at}
        context=self.store.repair_event_context(job['canonical_event_key'])
"""
    text = replace_once(text, discover_anchor, discover_gate, "repair discovery circuit gate")
    text = replace_once(
        text,
        "            return {\"ok\":bool(payload.get('ok',True)),\"payload\":payload,\"reason\":str(payload.get('error') or '')}\n",
        "            REPAIR_DISCOVERY_CIRCUIT.success()\n            return {\"ok\":bool(payload.get('ok',True)),\"payload\":payload,\"reason\":str(payload.get('error') or '')}\n",
        "repair discovery success closes circuit",
    )
    text = replace_once(
        text,
        "            return {\"ok\":False,\"reason\":str(payload.get('error') or f'HTTP_{exc.code}')}\n",
        """            reason=str(payload.get('error') or f'HTTP_{exc.code}')
            if exc.code == 429 or exc.code >= 500:
                REPAIR_DISCOVERY_CIRCUIT.failure(reason)
            return {"ok":False,"reason":reason,"infra":bool(exc.code == 429 or exc.code >= 500)}
""",
        "repair discovery HTTP circuit failures",
    )
    text = replace_once(
        text,
        "        except Exception as exc:\n            return {\"ok\":False,\"reason\":f\"DISCOVERY_TRANSPORT_{type(exc).__name__.upper()}\",\"infra\":True,\"message\":str(exc)}\n",
        """        except Exception as exc:
            reason=f"DISCOVERY_TRANSPORT_{type(exc).__name__.upper()}"
            REPAIR_DISCOVERY_CIRCUIT.failure(reason)
            return {"ok":False,"reason":reason,"infra":True,"message":str(exc)}
""",
        "repair discovery transport circuit failures",
    )

    text = replace_once(
        text,
        "        indexed=self._youtube_index_candidates(job,known)\n",
        "        with REPAIR_EXTERNAL_SEMAPHORE:\n            indexed=self._youtube_index_candidates(job,known)\n",
        "serialized indexed external repair",
    )
    text = replace_once(
        text,
        "        yt=self._youtube_fallback_candidates(job)\n",
        "        with REPAIR_EXTERNAL_SEMAPHORE:\n            yt=self._youtube_fallback_candidates(job)\n",
        "serialized generic external repair",
    )
    text = replace_once(
        text,
        "        quota_retry=float(yt.get('retryAt') or 0) if yt.get('quotaBlocked') else 0\n        retry=max(self._retry_at(job),quota_retry)\n",
        "        quota_retry=float(yt.get('retryAt') or 0) if yt.get('quotaBlocked') else 0\n        circuit_retry=float(result.get('retryAt') or 0) if result.get('circuitOpen') else 0\n        retry=max(self._retry_at(job),quota_retry,circuit_retry)\n",
        "repair retry honors discovery circuit",
    )

    # Existing R20 cooldown jobs get one immediate R21 pass, then retain normal
    # cooldowns because the R21 marker is persisted in details_json.
    text = text.replace("R20_PLAYBACK_EVIDENCE_CORROBORATION", "R21_CONTINUOUS_REPAIR")
    text = replace_once(
        text,
        'details={"mode":"RECERTIFY_EXISTING","candidateCount":len(candidates)}',
        'details={"mode":"RECERTIFY_EXISTING","strategy":"R21_CONTINUOUS_REPAIR","candidateCount":len(candidates)}',
        "R21 recertification marker",
    )

    text = replace_once(
        text,
        'REPAIR_ENGINE = None\n\ndef _spawn_workers(reason="service start"):\n',
        'REPAIR_ENGINE = None\nREPAIR_ENGINES = []\nROLLING_COORDINATOR = None\n\ndef _spawn_workers(reason="service start"):\n',
        "background globals",
    )
    rolling_anchor = 'def _spawn_workers(reason="service start"):\n'
    rolling_helper = '''def _start_rolling_batch(cutoff_date, batch_size):
    with WORKER_CONTROL_LOCK:
        existing = STORE.active_run()
        if existing and str(existing.get("state") or "").upper() in {"RUNNING", "PAUSED"}:
            return existing
        run = STORE.start_run("ROLLING", cutoff_date, max_games=batch_size)
        STATUS_CACHE.request_refresh()
        return run

'''
    if "def _start_rolling_batch(" not in text:
        text = text.replace(rolling_anchor, rolling_helper + rolling_anchor, 1)

    text = replace_once(
        text,
        'REPAIR_ENGINE = MediaRepairEngine(STORE, DB_WRITER)\nREPAIR_ENGINE.start()\n',
        '''REPAIR_ENGINES = [
    MediaRepairEngine(STORE, DB_WRITER, worker_index=i, seed_owner=(i == 1))
    for i in range(1, REPAIR_WORKER_COUNT + 1)
]
for _engine in REPAIR_ENGINES:
    _engine.start()
REPAIR_ENGINE = REPAIR_ENGINES[0] if REPAIR_ENGINES else None
ROLLING_COORDINATOR = RollingAuditCoordinator(
    STORE, _start_rolling_batch, timezone=AUDIT_TZ,
    enabled=ROLLING_AUDIT_ENABLED,
    interval_seconds=ROLLING_AUDIT_INTERVAL_SECONDS,
    batch_size=ROLLING_AUDIT_BATCH_SIZE,
    cutoff_days=ROLLING_AUDIT_CUTOFF_DAYS,
    fresh_seconds=FRESH_SECONDS,
    status_callback=STATUS_CACHE.request_refresh,
)
ROLLING_COORDINATOR.start()
''',
        "multi-repair + rolling startup",
    )
    text = replace_once(
        text,
        '                    "repair": {**(cached.get("repairSummary") or {}), "worker": REPAIR_ENGINE.snapshot() if REPAIR_ENGINE else {}},\n                    "run": cached.get("run"), "summary": cached.get("summary") or {},\n',
        '                    "repair": {**(cached.get("repairSummary") or {}), "worker": REPAIR_ENGINE.snapshot() if REPAIR_ENGINE else {}, "workers": [w.snapshot() for w in REPAIR_ENGINES], "workerCount": len(REPAIR_ENGINES), "discoveryCircuit": REPAIR_DISCOVERY_CIRCUIT.snapshot()},\n                    "rolling": ROLLING_COORDINATOR.snapshot() if ROLLING_COORDINATOR else {},\n                    "run": cached.get("run"), "summary": cached.get("summary") or {},\n',
        "status repair/rolling telemetry",
    )
    text = replace_once(
        text,
        '        if REPAIR_ENGINE: REPAIR_ENGINE.stop()\n        DB_WRITER.stop(); STATUS_CACHE.stop(); threading.Thread(target=server.shutdown, daemon=True).start()\n',
        '        if ROLLING_COORDINATOR: ROLLING_COORDINATOR.stop()\n        for _engine in REPAIR_ENGINES: _engine.stop()\n        DB_WRITER.stop(); STATUS_CACHE.stop(); threading.Thread(target=server.shutdown, daemon=True).start()\n',
        "shutdown background services",
    )
    text = replace_once(
        text,
        '        if REPAIR_ENGINE: REPAIR_ENGINE.stop()\n        DB_WRITER.stop(); STATUS_CACHE.stop(); server.server_close()\n',
        '        if ROLLING_COORDINATOR: ROLLING_COORDINATOR.stop()\n        for _engine in REPAIR_ENGINES: _engine.stop()\n        DB_WRITER.stop(); STATUS_CACHE.stop(); server.server_close()\n',
        "close background services",
    )

    path.write_text(text, encoding="utf-8")


def patch_verify(root):
    path = root / "VERIFY.sh"
    text = path.read_text(encoding="utf-8")
    marker = "python3 tools/check_release_version.py"
    if marker not in text:
        raise SystemExit("ERROR: VERIFY release checker anchor missing")
    for cmd in (
        "python3 -m py_compile sbb/media_audit_continuous.py",
        "python3 tests/test_v616_continuous_media_audit.py",
    ):
        if cmd not in text:
            text = text.replace(marker, marker + "\n" + cmd, 1)
    path.write_text(text, encoding="utf-8")


def promote(root):
    for p in active_files(root):
        try:
            source = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rendered = source.replace(BASE, NEW)
        if rendered != source:
            p.write_text(rendered, encoding="utf-8")
    for p in (root / "VERSION", root / "architecture" / "VERSION"):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(NEW + "\n", encoding="utf-8")


def controller(root):
    src = root / f"CONTROLLER-REGION-MAP-v{BASE}.md"
    dst = root / f"CONTROLLER-REGION-MAP-v{NEW}.md"
    if not src.is_file():
        raise SystemExit(f"ERROR: missing {src.name}")
    dst.write_text(src.read_text(encoding="utf-8").replace(BASE, NEW), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-check", action="store_true")
    args = ap.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    current = (root / "VERSION").read_text(encoding="utf-8").strip()
    if current != NEW:
        raise SystemExit(f"ERROR: expected VERSION {NEW}, got {current!r}")
    required = [
        root / "tools" / "apply_v615_release.py",
        root / "sbb" / "media_audit_continuous.py",
        root / "media_audit_service.py",
        root / "tests" / "test_v616_continuous_media_audit.py",
    ]
    missing = [str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing:
        raise SystemExit("ERROR: incomplete v6.1.6 release: " + ", ".join(missing))
    if args.dry_run:
        print("v6.1.6: yesterday-first rolling audit gaps + two repair workers + shared discovery circuit")
        return 0

    run_base(root)
    patch_media_audit(root)
    patch_verify(root)
    promote(root)
    controller(root)
    print("Sports Big Board v6.1.6 materialized")
    print("Media Audit: rolling mode cutoff=today-1d interval=5m batch=250 auditWorkers=1")
    print("Media Repair: enabled workers=2 discoveryConcurrency=1 externalConcurrency=1 circuit=3 failures/15m")
    if args.skip_check:
        return 0
    subprocess.run([sys.executable, str(root / "tools" / "check_release_version.py")], cwd=root, check=True)
    print("PASS: deployment-critical release identity is synchronized at 6.1.6")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

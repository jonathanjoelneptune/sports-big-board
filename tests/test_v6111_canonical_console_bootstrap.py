#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sbb import canonical_shadow_v600 as shadow
from sbb import canonical_certification_v610 as v610
from sbb import canonical_validation_v612 as v612
from sbb import canonical_run_integrity_v6110 as v6110
from sbb import canonical_console_bootstrap_v6111 as repair


class DummyServer:
    pass


def new_stack(td):
    store = shadow.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
    shadow_engine = shadow.CanonicalShadowEngine(DummyServer(), store=store)
    engine = v610.CertificationEngine(DummyServer(), shadow_engine)
    return store, engine


def install_runtime_patches_for_test():
    # Reproduce the production method order: v6.1.10 wraps validation decisions
    # and build_snapshot first, then v6.1.11 wraps that final surface.
    v6110._install_live_validation_decisions()
    v6110._install_console_stage_fields()
    repair._install_initial_consistency_gate()
    repair._install_snapshot_bootstrap()
    repair._install_single_health_read_per_build()


def verify_persisted_bootstrap_snapshot():
    with tempfile.TemporaryDirectory() as td:
        store, engine = new_stack(td)
        diag = v612.ValidationDiagnostics(DummyServer(), engine)
        captured = time.time() - 60
        summary = {
            "leagueDays": 105,
            "certified": 90,
            "reconciling": 5,
            "baseline": 10,
            "cutoverReady": 90,
        }
        compact = {
            "summary": summary,
            "window": {"from": "2026-09-05", "to": "2026-09-19", "today": "2026-09-12"},
            "stateConsistencyViolations": [{"league": "MLS", "date": "2026-09-09"}],
            "mlsDiagnostics": [],
        }
        with store._connect() as conn:
            conn.execute(
                """INSERT INTO canonical_validation_snapshot(
                    captured_at,release_version,snapshot_hash,summary_json,diagnostics_json
                ) VALUES(?,?,?,?,?)""",
                (captured, "6.1.10", "bootstrap-test", json.dumps(summary), json.dumps(compact)),
            )
            conn.commit()

        snap = diag.snapshot()
        assert snap, snap
        assert snap["bootstrap"] is True, snap
        assert snap["persistedBootstrap"] is True, snap
        assert snap["summary"]["certified"] == 90, snap
        assert snap["window"]["today"] == "2026-09-12", snap
        assert snap["days"] == {}, snap
        assert snap["productionAuthority"] is False, snap
        health = diag.health()
        assert health["persistedBootstrapAvailable"] is True, health


def verify_one_expensive_health_rollup_per_snapshot():
    with tempfile.TemporaryDirectory() as td:
        store, engine = new_stack(td)
        calls = {"storeHealth": 0}
        original_store_health = store.health

        def counted_store_health():
            calls["storeHealth"] += 1
            return original_store_health()

        store.health = counted_store_health
        diag = v612.ValidationDiagnostics(DummyServer(), engine)

        started = time.perf_counter()
        snap = diag.build_snapshot()
        elapsed = time.perf_counter() - started

        assert snap and snap.get("summary", {}).get("leagueDays") == 105, snap
        # v6.1.10 used to invoke engine.health() from every league/day decision,
        # which repeated store.health() ~105 times. v6.1.11 must collapse the
        # whole build to one expensive store health roll-up.
        assert calls["storeHealth"] == 1, calls
        assert int(getattr(diag, "__sbbV6111HealthReadsThisBuild", 0)) == 1
        assert int(getattr(diag, "__sbbV6111CachedHealthServesThisBuild", 0)) >= 100
        assert elapsed < 5.0, elapsed
        health = diag.health()
        assert health["ready"] is True, health
        assert health["buildInProgress"] is False, health
        assert health["singleHealthReadPerValidationBuild"] is True, health


def verify_first_build_defers_consistency_write_sweep():
    with tempfile.TemporaryDirectory() as td:
        _store, engine = new_stack(td)
        diag = v612.ValidationDiagnostics(DummyServer(), engine)
        assert diag.cache.get("ready") is False
        changed = diag._enforce_local_consistency("2026-09-05", "2026-09-19")
        assert changed == 0
        assert getattr(diag, "__sbbV6111InitialConsistencySkipped", False) is True


def main():
    install_runtime_patches_for_test()
    verify_persisted_bootstrap_snapshot()
    verify_one_expensive_health_rollup_per_snapshot()
    verify_first_build_defers_consistency_write_sweep()
    print("PASS: v6.1.11 canonical console bootstrap, single health roll-up, and fast first snapshot")


if __name__ == "__main__":
    main()

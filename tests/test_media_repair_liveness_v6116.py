from pathlib import Path
import sqlite3

from media_repair_liveness import repair_backlog_snapshot

ROOT = Path(__file__).resolve().parents[1]


def _conn(rows=()):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE history_media_repair_queue (state TEXT NOT NULL, next_retry_at REAL NOT NULL DEFAULT 0)"
    )
    conn.executemany(
        "INSERT INTO history_media_repair_queue(state,next_retry_at) VALUES(?,?)",
        list(rows),
    )
    return conn


def test_backlog_distinguishes_claimable_cooldown_and_running():
    conn = _conn(
        [
            ("PENDING", 0),
            ("WAITING_RETRY", 900),
            ("WAITING_RETRY", 1200),
            ("SEARCHING", 0),
            ("REPAIRED", 0),
        ]
    )
    snap = repair_backlog_snapshot(conn, now=1000)
    assert snap["queue"] == 4
    assert snap["allRows"] == 5
    assert snap["eligibleNow"] == 2
    assert snap["coolingDown"] == 1
    assert snap["running"] == 1
    assert snap["blocked"] == 0
    assert snap["nextEligibleAt"] == 1200
    assert snap["nextEligibleInSeconds"] == 200
    assert snap["availabilityState"] == "ACTIVE"


def test_backlog_reports_cooldown_instead_of_false_idle():
    conn = _conn([("WAITING_RETRY", 1300), ("WAITING_RETRY", 1600)])
    snap = repair_backlog_snapshot(conn, now=1000)
    assert snap["queue"] == 2
    assert snap["eligibleNow"] == 0
    assert snap["coolingDown"] == 2
    assert snap["availabilityState"] == "COOLDOWN"
    assert snap["nextEligibleAt"] == 1300
    assert "cooling down" in snap["waitReason"]


def test_backlog_reports_ready_and_empty_states():
    ready = repair_backlog_snapshot(_conn([("PENDING", 0)]), now=1000)
    assert ready["availabilityState"] == "READY"
    assert ready["eligibleNow"] == 1

    empty = repair_backlog_snapshot(_conn([("REPAIRED", 0)]), now=1000)
    assert empty["queue"] == 0
    assert empty["availabilityState"] == "EMPTY"


def test_repair_worker_uses_liveness_state_when_no_job_is_claimed():
    service = (ROOT / "media_audit_service.py").read_text(encoding="utf-8")
    for token in [
        "from media_repair_liveness import repair_backlog_snapshot",
        "def repair_liveness(self):",
        "eligibleNow",
        "coolingDown",
        "nextEligibleAt",
        "availabilityState",
        "phase='COOLDOWN'",
        "phase='CLAIM_RETRY'",
        "phase='BLOCKED'",
    ]:
        assert token in service

    no_job = service[service.index("if not job:") : service.index("self.stats['jobsAttempted']")]
    assert "repair_liveness()" in no_job
    assert "state='IDLE',phase='IDLE'" not in no_job
    assert "time.sleep(2.0)" in no_job


def test_media_audit_ui_exposes_backlog_breakdown_and_no_active_game():
    ui = (ROOT / "ui/media-audit-v550.js").read_text(encoding="utf-8")
    assert "NO ACTIVE GAME" in ui
    assert "eligible now" in ui
    assert "cooling" in ui
    assert "next eligible" in ui
    assert "repair.waitReason" in ui

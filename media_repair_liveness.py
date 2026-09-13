"""Small, side-effect-free helpers for Media Repair Engine backlog liveness.

The repair queue intentionally retains jobs that are cooling down for a later
retry.  A total active-row count therefore is not the same thing as work the
worker can claim *now*.  This module keeps that distinction explicit and testable
without importing the long-running media_audit_service.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

DEFAULT_ACTIVE_STATES = ("PENDING", "WAITING_RETRY", "SEARCHING", "CERTIFYING")
RUNNING_STATES = ("SEARCHING", "CERTIFYING")


def _seconds_until(epoch: float, now: float) -> float:
    if not epoch:
        return 0.0
    return max(0.0, float(epoch) - float(now))


def repair_backlog_snapshot(conn, *, now: float, active_states: Iterable[str] = DEFAULT_ACTIVE_STATES) -> dict:
    """Return claimability-aware queue telemetry from an open SQLite connection.

    ``queue`` remains the backwards-compatible count of all active repair rows.
    ``eligibleNow`` is the subset the worker's claim query can take immediately.
    ``coolingDown`` is WAITING_RETRY work whose retry timestamp is still future.
    """
    active_states = tuple(str(state) for state in active_states)
    states = {
        str(row[0]): int(row[1] or 0)
        for row in conn.execute(
            "SELECT state,COUNT(*) FROM history_media_repair_queue GROUP BY state"
        ).fetchall()
    }
    all_rows = sum(states.values())
    queue_count = sum(states.get(state, 0) for state in active_states)

    row = conn.execute(
        """SELECT
             COALESCE(SUM(CASE
               WHEN state='PENDING' AND next_retry_at<=? THEN 1
               WHEN state='WAITING_RETRY' AND next_retry_at<=? THEN 1
               ELSE 0 END),0) AS eligible_now,
             COALESCE(SUM(CASE
               WHEN state='WAITING_RETRY' AND next_retry_at>? THEN 1
               ELSE 0 END),0) AS cooling_down,
             COALESCE(SUM(CASE
               WHEN state IN ('SEARCHING','CERTIFYING') THEN 1
               ELSE 0 END),0) AS running,
             MIN(CASE
               WHEN state='WAITING_RETRY' AND next_retry_at>? THEN next_retry_at
               ELSE NULL END) AS next_eligible_at
           FROM history_media_repair_queue""",
        (float(now), float(now), float(now), float(now)),
    ).fetchone()

    eligible_now = int((row[0] if row else 0) or 0)
    cooling_down = int((row[1] if row else 0) or 0)
    running = int((row[2] if row else 0) or 0)
    next_eligible_at = float((row[3] if row else 0) or 0)
    blocked = max(0, queue_count - eligible_now - cooling_down - running)

    if running:
        availability = "ACTIVE"
        wait_reason = f"{running} repair job{'s' if running != 1 else ''} currently claimed"
    elif eligible_now:
        availability = "READY"
        wait_reason = f"{eligible_now} repair job{'s' if eligible_now != 1 else ''} eligible now"
    elif cooling_down:
        availability = "COOLDOWN"
        wait_reason = f"{cooling_down} repair job{'s' if cooling_down != 1 else ''} cooling down"
    elif blocked:
        availability = "BLOCKED"
        wait_reason = f"{blocked} active repair job{'s' if blocked != 1 else ''} not currently claimable"
    else:
        availability = "EMPTY"
        wait_reason = "No repair jobs queued"

    return {
        "queue": queue_count,
        "allRows": all_rows,
        "states": states,
        "eligibleNow": eligible_now,
        "coolingDown": cooling_down,
        "running": running,
        "blocked": blocked,
        "nextEligibleAt": next_eligible_at,
        "nextEligibleInSeconds": _seconds_until(next_eligible_at, now),
        "availabilityState": availability,
        "waitReason": wait_reason,
    }


__all__ = ["DEFAULT_ACTIVE_STATES", "RUNNING_STATES", "repair_backlog_snapshot"]

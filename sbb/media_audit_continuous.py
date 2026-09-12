#!/usr/bin/env python3
"""Always-on Media Audit coordination primitives.

This module is deliberately independent from media_audit_service.py so the rolling
scheduler and repair discovery circuit can be regression-tested without importing
Selenium, opening SQLite, or starting production worker threads.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta


class DiscoveryCircuitBreaker:
    """Shared failure circuit for expensive repair discovery.

    Event-specific 4xx failures should not be reported here. Call ``failure`` only
    for infrastructure/upstream failures where immediately trying another game is
    likely to hit the same broken dependency.
    """

    def __init__(self, threshold=3, cooldown_seconds=900.0, clock=None):
        self.threshold = max(1, int(threshold or 1))
        self.cooldown_seconds = max(1.0, float(cooldown_seconds or 1.0))
        self.clock = clock or time.time
        self.lock = threading.RLock()
        self.consecutive_failures = 0
        self.open_until = 0.0
        self.last_failure_reason = ""
        self.last_failure_at = 0.0
        self.last_success_at = 0.0
        self.total_opened = 0

    def before_request(self):
        now = float(self.clock())
        with self.lock:
            if self.open_until and now >= self.open_until:
                self.open_until = 0.0
                self.consecutive_failures = 0
            allowed = not self.open_until
            return {
                "allowed": allowed,
                "retryAt": float(self.open_until or 0),
                "consecutiveFailures": int(self.consecutive_failures),
                "reason": self.last_failure_reason,
            }

    def success(self):
        now = float(self.clock())
        with self.lock:
            self.consecutive_failures = 0
            self.open_until = 0.0
            self.last_success_at = now
        return self.snapshot()

    def failure(self, reason="", retry_at=0.0):
        now = float(self.clock())
        with self.lock:
            self.consecutive_failures += 1
            self.last_failure_reason = str(reason or "UPSTREAM_FAILURE")[:500]
            self.last_failure_at = now
            if self.consecutive_failures >= self.threshold:
                candidate = max(now + self.cooldown_seconds, float(retry_at or 0))
                if candidate > self.open_until:
                    if not self.open_until:
                        self.total_opened += 1
                    self.open_until = candidate
        return self.snapshot()

    def snapshot(self):
        now = float(self.clock())
        with self.lock:
            return {
                "state": "OPEN" if self.open_until > now else "CLOSED",
                "threshold": self.threshold,
                "cooldownSeconds": self.cooldown_seconds,
                "consecutiveFailures": int(self.consecutive_failures),
                "openUntil": float(self.open_until or 0),
                "retryInSeconds": max(0.0, round(float(self.open_until or 0) - now, 1)),
                "lastFailureReason": self.last_failure_reason,
                "lastFailureAt": float(self.last_failure_at or 0),
                "lastSuccessAt": float(self.last_success_at or 0),
                "totalOpened": int(self.total_opened),
            }


class RollingAuditCoordinator(threading.Thread):
    """Keep canonical Media Audit caught up without one enormous frozen queue.

    Each batch starts at ``today - cutoff_days`` and walks backward through only
    missing/stale canonical certifications. A bounded batch means newly completed
    games return to the front of the next cycle instead of waiting behind years of
    historical catch-up work.
    """

    daemon = True

    def __init__(
        self,
        store,
        start_batch,
        *,
        timezone,
        enabled=True,
        interval_seconds=300.0,
        batch_size=250,
        cutoff_days=1,
        fresh_seconds=30 * 86400,
        status_callback=None,
        clock=None,
    ):
        super().__init__(name="canonical-media-audit-rolling-coordinator")
        self.store = store
        self.start_batch = start_batch
        self.timezone = timezone
        self.enabled = bool(enabled)
        self.interval_seconds = max(10.0, float(interval_seconds or 300.0))
        self.batch_size = max(1, int(batch_size or 250))
        self.cutoff_days = max(0, int(cutoff_days or 0))
        self.fresh_seconds = max(60, int(fresh_seconds or 60))
        self.status_callback = status_callback
        self.clock = clock or time.time
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.state = {
            "enabled": self.enabled,
            "state": "STARTING" if self.enabled else "DISABLED",
            "cutoffDate": "",
            "backlog": 0,
            "batchSize": self.batch_size,
            "lastRunId": 0,
            "lastRunGames": 0,
            "lastError": "",
            "lastCheckAt": 0.0,
        }

    def stop(self):
        self.stop_event.set()

    def snapshot(self):
        with self.lock:
            data = dict(self.state)
        data["alive"] = self.is_alive()
        return data

    def _set(self, **patch):
        with self.lock:
            self.state.update(patch)
            self.state["lastCheckAt"] = float(self.clock())
        if self.status_callback:
            try:
                self.status_callback()
            except Exception:
                pass

    def cutoff_date(self):
        return (datetime.now(self.timezone).date() - timedelta(days=self.cutoff_days)).isoformat()

    def run_once(self):
        if not self.enabled:
            self._set(state="DISABLED")
            return self.snapshot()
        cutoff = self.cutoff_date()
        active = self.store.active_run()
        active_state = str((active or {}).get("state") or "").upper()
        if active and active_state in {"RUNNING", "PAUSED"}:
            self._set(
                state="WAITING_ACTIVE_RUN" if active_state == "RUNNING" else "PAUSED",
                cutoffDate=cutoff,
                lastRunId=int(active.get("id") or 0),
                lastRunGames=int(active.get("total_games") or 0),
                lastError="",
            )
            return self.snapshot()

        backlog = int(self.store.rolling_backlog_count(cutoff, self.fresh_seconds) or 0)
        if backlog <= 0:
            self._set(state="CAUGHT_UP", cutoffDate=cutoff, backlog=0, lastError="")
            return self.snapshot()

        self._set(state="STARTING_BATCH", cutoffDate=cutoff, backlog=backlog, lastError="")
        run = self.start_batch(cutoff, self.batch_size) or {}
        self._set(
            state="RUNNING_BATCH" if int(run.get("total_games") or 0) else "CAUGHT_UP",
            cutoffDate=cutoff,
            backlog=backlog,
            lastRunId=int(run.get("id") or 0),
            lastRunGames=int(run.get("total_games") or 0),
            lastError="",
        )
        return self.snapshot()

    def run(self):
        if not self.enabled:
            self._set(state="DISABLED")
            return
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception as exc:
                self._set(state="ERROR", lastError=f"{type(exc).__name__}: {exc}")
            self.stop_event.wait(self.interval_seconds)

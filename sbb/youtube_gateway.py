"""YouTube API gateway for Sports Big Board v4.1.23.

The gateway is deliberately operation-aware. A search.list quota/rate failure must
never disable cheap metadata validation (videos.list) or official-channel history
indexing (activities.list / playlists.list / playlistItems.list). Historical playback relies on those independent lanes.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class YouTubeRateLimited(RuntimeError):
    def __init__(self, message: str, *, operation: str = "unknown", retry_at: float = 0.0, quota_exhausted: bool = False):
        super().__init__(message)
        self.operation = operation
        self.retry_at = float(retry_at or 0)
        self.quota_exhausted = bool(quota_exhausted)


@dataclass
class OperationState:
    until: float = 0.0
    last_error: str = ""
    failures: int = 0
    quota_exhausted: bool = False
    reset_at: float = 0.0


class YouTubeGateway:
    """Small thread-safe request broker with separate failure domains per method."""

    def __init__(self, user_agent: str = "SportsBigBoard/4.1.23", state_file=None, quota_timezone="America/Los_Angeles"):
        self.user_agent = user_agent
        self.state_file = Path(state_file) if state_file else None
        self.quota_timezone = str(quota_timezone or "America/Los_Angeles")
        self._lock = threading.RLock()
        self._states = {
            "search": OperationState(),
            "videos": OperationState(),
            "activities": OperationState(),
            "channels": OperationState(),
            "playlists": OperationState(),
            "playlistitems": OperationState(),
            "other": OperationState(),
        }
        self._load_state()

    def _next_quota_reset(self):
        try:
            tz=ZoneInfo(self.quota_timezone); now=datetime.now(tz); tomorrow=(now+timedelta(days=1)).date()
            return datetime(tomorrow.year,tomorrow.month,tomorrow.day,tzinfo=tz).timestamp()
        except Exception:
            return time.time()+6*60*60

    def _load_state(self):
        if not self.state_file: return
        try:
            payload=json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return
        now=time.time()
        for name,raw in (payload.get("operations") or {}).items():
            if name not in self._states or not isinstance(raw,dict): continue
            st=self._states[name]; reset=float(raw.get("resetAt") or 0)
            if raw.get("quotaExhausted") and reset>now:
                st.quota_exhausted=True; st.reset_at=reset; st.until=max(float(raw.get("until") or 0),reset); st.last_error=str(raw.get("lastError") or "quota exhausted"); st.failures=int(raw.get("failures") or 0)

    def _save_state(self):
        if not self.state_file: return
        try:
            self.state_file.parent.mkdir(parents=True,exist_ok=True)
            payload={"savedAt":time.time(),"operations":{name:{"until":st.until,"lastError":st.last_error,"failures":st.failures,"quotaExhausted":st.quota_exhausted,"resetAt":st.reset_at} for name,st in self._states.items()}}
            tmp=self.state_file.with_suffix(self.state_file.suffix+".tmp"); tmp.write_text(json.dumps(payload,separators=(",",":")),encoding="utf-8"); tmp.replace(self.state_file)
        except Exception:
            pass

    @staticmethod
    def operation_for_url(url: str) -> str:
        path = urlparse(str(url or "")).path.rstrip("/").split("/")[-1].lower()
        if path in {"search", "videos", "activities", "channels", "playlists", "playlistitems"}:
            return path
        return "other"

    @staticmethod
    def _error_reason(exc: HTTPError) -> tuple[str, bool]:
        text = ""
        try:
            text = exc.read().decode("utf-8", "ignore")
        except Exception:
            text = ""
        reasons = []
        try:
            payload = json.loads(text or "{}")
            err = payload.get("error") or {}
            for row in err.get("errors") or []:
                if isinstance(row, dict) and row.get("reason"):
                    reasons.append(str(row.get("reason")))
            if err.get("status"):
                reasons.append(str(err.get("status")))
            if err.get("message"):
                reasons.append(str(err.get("message")))
        except Exception:
            pass
        reason = " | ".join(reasons) or f"HTTP {exc.code}: {getattr(exc, 'reason', '')}".strip()
        lowered = reason.lower()
        quota = any(token in lowered for token in (
            "quotaexceeded", "dailylimitexceeded", "ratelimitexceeded",
            "userratelimitexceeded", "quota exceeded", "daily limit",
        ))
        return reason, quota

    def _state(self, operation: str) -> OperationState:
        return self._states.setdefault(operation, OperationState())

    def _check(self, operation: str) -> None:
        with self._lock:
            state = self._state(operation); now=time.time()
            if state.quota_exhausted and state.reset_at and now>=state.reset_at:
                state.until=0.0; state.last_error=""; state.failures=0; state.quota_exhausted=False; state.reset_at=0.0; self._save_state()
            if now < state.until:
                raise YouTubeRateLimited(
                    f"YouTube {operation}.list cooldown active: {state.last_error or 'temporarily unavailable'}",
                    operation=operation,
                    retry_at=state.until,
                    quota_exhausted=state.quota_exhausted,
                )

    def _mark_success(self, operation: str) -> None:
        with self._lock:
            state = self._state(operation)
            state.until = 0.0
            state.last_error = ""
            state.failures = 0
            state.quota_exhausted = False
            state.reset_at = 0.0
            self._save_state()

    def _mark_http_failure(self, operation: str, exc: HTTPError) -> YouTubeRateLimited | None:
        if exc.code not in (403, 429):
            return None
        reason, quota = self._error_reason(exc)
        now = time.time()
        with self._lock:
            state = self._state(operation)
            state.failures += 1
            # search.list has a separate daily bucket. A real quota exhaustion can
            # safely be held for hours, but it still must not poison activities/videos.
            if operation == "search" and quota:
                state.reset_at=self._next_quota_reset(); delay=max(60,state.reset_at-now)
            elif operation == "search" and exc.code == 429:
                delay = 45 * 60
            elif exc.code == 429:
                delay = min(15 * 60, 60 * (2 ** min(3, state.failures - 1)))
            else:
                # A non-quota 403 can be request/policy specific. Keep the backoff
                # short instead of globally disabling the method for 45 minutes.
                delay = min(5 * 60, 30 * (2 ** min(3, state.failures - 1)))
            state.until = max(state.until, now + delay)
            state.last_error = reason
            state.quota_exhausted = quota
            if not quota: state.reset_at=0.0
            self._save_state()
            return YouTubeRateLimited(
                f"YouTube {operation}.list unavailable: {reason}",
                operation=operation,
                retry_at=state.until,
                quota_exhausted=quota,
            )

    def fetch_json(self, url: str, timeout: float = 10) -> dict:
        operation = self.operation_for_url(url)
        self._check(operation)
        req = Request(str(url), headers={"Accept": "application/json", "User-Agent": self.user_agent})
        try:
            with urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "ignore") or "{}")
            self._mark_success(operation)
            return data if isinstance(data, dict) else {"data": data}
        except HTTPError as exc:
            limited = self._mark_http_failure(operation, exc)
            if limited is not None:
                raise limited
            raise

    def status(self) -> dict:
        now = time.time()
        with self._lock:
            return {
                name: {
                    "cooldownSeconds": max(0, int(state.until - now)),
                    "lastError": state.last_error,
                    "quotaExhausted": state.quota_exhausted,
                    "failures": state.failures,
                    "resetAt": state.reset_at,
                }
                for name, state in self._states.items()
            }

    def operation_available(self, operation: str) -> bool:
        try:
            self._check(operation); return True
        except YouTubeRateLimited:
            return False

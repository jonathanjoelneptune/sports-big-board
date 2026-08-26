"""Milestone release observability for Sports Big Board.

This intentionally keeps a bounded in-memory operational ledger. It is not a
replacement for durable application data; it exists so a milestone release can be
exercised for hours and then exported as one coherent diagnostic snapshot.
"""
from __future__ import annotations

import copy
import math
import threading
import time
from collections import deque


class MilestoneConsole:
    def __init__(self, version: str, max_events: int = 1200):
        self.version = str(version or "")
        self.started_at = time.time()
        self._lock = threading.RLock()
        self._events = deque(maxlen=max(200, int(max_events)))
        self._endpoint = {}
        self._playback = {
            "latest": {}, "events": 0, "selections": 0, "firstFrames": 0,
            "failures": 0, "stalls": 0, "firstFrameSamplesMs": deque(maxlen=240),
            "stallSamplesMs": deque(maxlen=240),
        }
        self._client_heartbeats = {}
        self._counters = {}

    @staticmethod
    def _percentile(values, q):
        vals = sorted(float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(float(v)))
        if not vals:
            return None
        if len(vals) == 1:
            return round(vals[0], 1)
        pos = (len(vals) - 1) * float(q)
        lo = int(math.floor(pos)); hi = int(math.ceil(pos))
        if lo == hi:
            return round(vals[lo], 1)
        frac = pos - lo
        return round(vals[lo] + (vals[hi] - vals[lo]) * frac, 1)

    def record(self, category, level, message, data=None, *, source="server"):
        row = {
            "at": time.time(), "category": str(category or "system")[:80],
            "level": str(level or "INFO").upper()[:16],
            "source": str(source or "server")[:48], "message": str(message or "")[:1600],
        }
        if data not in (None, {}, []):
            row["data"] = copy.deepcopy(data)
        with self._lock:
            self._events.append(row)
            key = f"{row['category']}:{row['level']}"
            self._counters[key] = int(self._counters.get(key) or 0) + 1
        return row

    def record_endpoint(self, path, duration_ms, status=200, error=""):
        path = str(path or "")[:240]
        if not path.startswith("/api/"):
            return
        duration = max(0.0, float(duration_ms or 0.0)); status = int(status or 0)
        with self._lock:
            st = self._endpoint.setdefault(path, {
                "count": 0, "errors": 0, "lastMs": 0.0, "maxMs": 0.0,
                "totalMs": 0.0, "lastStatus": 0, "lastAt": 0.0,
                "samplesMs": deque(maxlen=160), "lastError": "",
            })
            st["count"] += 1; st["lastMs"] = round(duration, 1); st["maxMs"] = max(float(st["maxMs"]), duration)
            st["totalMs"] += duration; st["lastStatus"] = status; st["lastAt"] = time.time(); st["samplesMs"].append(duration)
            if status >= 400:
                st["errors"] += 1; st["lastError"] = str(error or "")[:600]
        if status >= 500:
            self.record("api", "ERROR", f"{path} returned HTTP {status}", {"durationMs": round(duration,1), "error": str(error or "")[:600]})
        elif duration >= 5000:
            self.record("api", "WARN", f"slow API request: {path}", {"durationMs": round(duration,1), "status": status})

    def record_playback(self, event, session):
        event = str(event or "state")[:80]; session = copy.deepcopy(session or {})
        with self._lock:
            pb = self._playback; pb["events"] += 1; pb["latest"] = session
            if event == "selection": pb["selections"] += 1
            if event == "first-frame":
                pb["firstFrames"] += 1
                value = session.get("firstFrameMs")
                if isinstance(value, (int, float)): pb["firstFrameSamplesMs"].append(float(value))
            if event == "failure": pb["failures"] += 1
            if event == "stall": pb["stalls"] += 1
            stall = session.get("lastStallMs")
            if event == "stall-end" and isinstance(stall, (int, float)) and stall > 0: pb["stallSamplesMs"].append(float(stall))
        level = "ERROR" if event == "failure" or str(session.get("invariant") or "").startswith("ERROR") else "INFO"
        if event in {"selection", "first-frame", "failure", "stall", "stall-end"} or level == "ERROR":
            self.record("playback", level, event, {
                "sessionId": session.get("sessionId"), "state": session.get("state"),
                "eventKey": session.get("eventKey"), "mediaKey": session.get("mediaKey"),
                "transport": session.get("transport"), "slot": session.get("slot"),
                "firstFrameMs": session.get("firstFrameMs"), "stallCount": session.get("stallCount"),
                "stallTotalMs": session.get("stallTotalMs"), "lastError": session.get("lastError"),
                "invariant": session.get("invariant"), "sourceExternalUrl": session.get("sourceExternalUrl"),
            }, source="browser")

    def record_client(self, body):
        body = copy.deepcopy(body or {})
        kind = str(body.get("kind") or body.get("event") or "client")[:80]
        level = str(body.get("level") or ("ERROR" if kind in {"error","unhandledrejection"} else "INFO")).upper()
        message = str(body.get("message") or body.get("detail") or kind)
        data = body.get("data") if isinstance(body.get("data"), (dict, list)) else {}
        if body.get("playback") and isinstance(body.get("playback"), dict): data = {**(data if isinstance(data,dict) else {}), "playback": body.get("playback")}
        category = kind if kind in {"stress","stress-step","test-procedure","error","unhandledrejection","playback-invariant","network","console-error","console-warn"} else "client"
        meta = {"kind": kind, "frontendVersion": str(body.get("frontendVersion") or "")[:40], "tabId": str(body.get("tabId") or "")[:120]}
        if isinstance(data, dict): data = {**data, "_client": meta}
        self.record(category, level, message, data, source="browser")
        if kind == "heartbeat":
            tab = str(body.get("tabId") or "browser")[:120]
            with self._lock: self._client_heartbeats[tab] = {"at":time.time(), **copy.deepcopy(body)}


    def reset(self):
        with self._lock:
            self.started_at=time.time(); self._events.clear(); self._endpoint.clear(); self._client_heartbeats.clear(); self._counters.clear()
            self._playback={
                "latest": {}, "events": 0, "selections": 0, "firstFrames": 0,
                "failures": 0, "stalls": 0, "firstFrameSamplesMs": deque(maxlen=240),
                "stallSamplesMs": deque(maxlen=240),
            }
        self.record("milestone","INFO","milestone console reset")

    def _endpoint_snapshot(self):
        out = {}
        for path, st in self._endpoint.items():
            samples = list(st.get("samplesMs") or [])
            count = max(1, int(st.get("count") or 0))
            out[path] = {
                "count": int(st.get("count") or 0), "errors": int(st.get("errors") or 0),
                "lastMs": round(float(st.get("lastMs") or 0),1), "maxMs": round(float(st.get("maxMs") or 0),1),
                "avgMs": round(float(st.get("totalMs") or 0)/count,1), "p95Ms": self._percentile(samples,.95),
                "lastStatus": int(st.get("lastStatus") or 0), "lastAt": float(st.get("lastAt") or 0),
                "lastError": str(st.get("lastError") or ""),
            }
        return dict(sorted(out.items(), key=lambda kv: (-(kv[1].get("errors") or 0), -(kv[1].get("p95Ms") or 0))))

    def snapshot(self, *, frontend_version="", extra=None, recent_limit=260):
        now = time.time()
        with self._lock:
            pb = copy.deepcopy({k:v for k,v in self._playback.items() if not isinstance(v, deque)})
            first = list(self._playback["firstFrameSamplesMs"]); stalls = list(self._playback["stallSamplesMs"])
            pb["firstFrame"] = {"samples":len(first), "p50Ms":self._percentile(first,.50), "p95Ms":self._percentile(first,.95), "maxMs":round(max(first),1) if first else None}
            pb["stallDuration"] = {"samples":len(stalls), "p50Ms":self._percentile(stalls,.50), "p95Ms":self._percentile(stalls,.95), "maxMs":round(max(stalls),1) if stalls else None}
            events = list(self._events)[-max(20,min(1000,int(recent_limit or 260))):]
            endpoint = self._endpoint_snapshot()
            heartbeats = copy.deepcopy(self._client_heartbeats)
            counters = dict(self._counters)
        for row in heartbeats.values(): row["ageSeconds"] = round(max(0, now-float(row.get("at") or 0)),1)
        return {
            "version": self.version, "frontendVersion": str(frontend_version or ""),
            "versionMatch": (not frontend_version) or str(frontend_version) == self.version,
            "startedAt": self.started_at, "uptimeSeconds": int(max(0, now-self.started_at)),
            "playback": pb, "api": endpoint, "clientHeartbeats": heartbeats,
            "counters": counters, "recent": events, "extra": copy.deepcopy(extra or {}),
        }

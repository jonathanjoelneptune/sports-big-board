"""Sports Big Board v5.2.3 — Key Info intelligence snapshot.

The page never asks OpenAI or a news provider for work. A daemon consumes already-
sourced sports records, uses the existing server-side OpenAI editorial desk when
available, keeps only consequential facts, and persists the finished ticker.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from . import current_news_v522 as source_v522

VERSION = "5.2.3-key-info-intelligence-1"
_STATE_DIR = Path(os.environ.get("SBB_STATE_DIR") or (Path.home() / ".sports-big-board")).expanduser()
_STATE_PATH = _STATE_DIR / "key-info-intelligence-v523.json"
_INSTALL_LOCK = threading.Lock()
_CACHE_LOCK = threading.RLock()
_INSTALLED = False
_SERVER = None
_STOP = threading.Event()
_CACHE = {"savedAt": 0.0, "source": "", "data": [], "sourceSignature": ""}
_STATE = {"version": VERSION, "installed": False, "refreshing": False, "lastRefreshAt": 0.0, "lastError": "", "openaiRuns": 0, "ruleRuns": 0, "served": 0}

_NOISE = re.compile(
    r"\b(prediction|predictions|preview|power rankings?|mock draft|fantasy|betting|odds|picks?|who are|who is|owners?|salary cap talks?|potential surprises?|offseason recap|what to know|watch list|mailbag|podcast|ranking the|best .* list|top \d+)\b",
    re.I,
)

_CATEGORY_PATTERNS = [
    ("RECORD", re.compile(r"\b(record|historic|history|first (?:player|team|rookie)|most .* ever|single[- ]season|career high|career-high|franchise high|franchise-high)\b", re.I)),
    ("STREAK", re.compile(r"\b(streak|straight (?:win|victor)|wins? in a row|unbeaten|consecutive)\b", re.I)),
    ("INJURY", re.compile(r"\b(injur|out for|ruled out|placed on (?:IL|IR)|disabled list|concussion|torn|sprain|fracture|surgery)\b", re.I)),
    ("TRADE", re.compile(r"\b(traded?|trade(?:s|d)?|acquired?|dealt|swap)\b", re.I)),
    ("SIGNING", re.compile(r"\b(signs?|signed|signing|agrees? to|contract|extension|re-signs?|re-signed)\b", re.I)),
    ("ROSTER", re.compile(r"\b(released?|waived?|claimed|called up|promoted|demoted|optioned|activated|roster move|designated for assignment|dfa)\b", re.I)),
    ("COACHING", re.compile(r"\b(fired|hired|head coach|manager fired|manager hired|coaching change|steps down|resigns)\b", re.I)),
    ("SUSPENSION", re.compile(r"\b(suspend|suspension|banned|ban for|discipline|fined)\b", re.I)),
    ("CLINCH", re.compile(r"\b(clinch|clinched|eliminated|elimination|playoff berth|division title|league title|champion|championship)\b", re.I)),
    ("UPSET", re.compile(r"\b(upset|stuns?|shocks?|knocks off|defeats? no\.? ?\d+|beats? no\.? ?\d+)\b", re.I)),
    ("MILESTONE", re.compile(r"\b(milestone|\d+(?:st|nd|rd|th) career|\d+th (?:home run|goal|win|hit|touchdown|strikeout)|joins .* club)\b", re.I)),
    ("RETIREMENT", re.compile(r"\b(retir|final season|calls it a career)\b", re.I)),
    ("SHAKEUP", re.compile(r"\b(front office|general manager|president of .* operations|ownership change|resign|shakeup)\b", re.I)),
]


def _clean(v):
    return str(v or "").strip()


def _load():
    global _CACHE
    try:
        payload = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            with _CACHE_LOCK:
                _CACHE = {
                    "savedAt": float(payload.get("savedAt") or 0),
                    "source": _clean(payload.get("source")),
                    "data": [dict(x) for x in payload.get("data") if isinstance(x, dict)],
                    "sourceSignature": _clean(payload.get("sourceSignature")),
                }
            return True
    except Exception:
        pass
    return False


def _persist(rows, source, signature):
    global _CACHE
    payload = {"version": VERSION, "savedAt": time.time(), "source": source, "sourceSignature": signature, "data": rows[:24]}
    with _CACHE_LOCK:
        _CACHE = payload
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
        os.replace(tmp, _STATE_PATH)
    except Exception:
        pass


def _raw_rows(server):
    rows = []
    # First preference: the already-sourced editorial desk. No network work here.
    try:
        lock = getattr(server, "EDITORIAL_SNAPSHOT_LOCK", None)
        if lock:
            with lock:
                snap = copy.deepcopy(getattr(server, "EDITORIAL_SNAPSHOT", {}) or {})
        else:
            snap = copy.deepcopy(getattr(server, "EDITORIAL_SNAPSHOT", {}) or {})
        rows.extend(dict(x) for x in (snap.get("data") or []) if isinstance(x, dict))
    except Exception:
        pass
    # v5.2.2 also keeps a persistent ESPN fallback; consume it as source material.
    if len(rows) < 12:
        try:
            fallback, _ = source_v522._rows(server)
            rows.extend(dict(x) for x in fallback if isinstance(x, dict))
        except Exception:
            pass
    out = []
    seen = set()
    for row in rows:
        title = _clean(row.get("title") or row.get("headline"))
        if not title:
            continue
        key = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out[:50]


def _signature(rows):
    text = "|".join(f"{_clean(x.get('id'))}:{_clean(x.get('title') or x.get('headline'))}:{_clean(x.get('publishedAt') or x.get('date'))}" for x in rows[:40])
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest() if text else ""


def _category(row):
    explicit = _clean(row.get("eventType") or row.get("category")).upper()
    if explicit and explicit not in {"NEWS", "UPDATE", "ARTICLE", "STORY", "OTHER"}:
        aliases = {"TRANSACTION": "ROSTER", "TRADE_SIGNING": "SIGNING", "RECORD_MILESTONE": "RECORD", "RESULT": "RESULT"}
        return aliases.get(explicit, explicit[:18])
    text = f"{_clean(row.get('title'))} {_clean(row.get('description'))}"
    for label, pattern in _CATEGORY_PATTERNS:
        if pattern.search(text):
            return label
    return ""


def _factual_candidates(server, rows):
    try:
        fn = getattr(server, "_filter_ticker_items", None)
        if callable(fn):
            rows = list(fn(rows) or [])
    except Exception:
        pass
    out = []
    for row in rows:
        title = _clean(row.get("title") or row.get("headline"))
        if not title or _NOISE.search(title):
            continue
        cat = _category(row)
        if not cat:
            continue
        item = dict(row)
        item["eventType"] = cat
        out.append(item)
    return out


def _normalize(rows, provider):
    out = []
    seen = set()
    for row in rows:
        title = _clean(row.get("title") or row.get("headline"))
        if not title or _NOISE.search(title):
            continue
        category = _category(row)
        if not category:
            continue
        # OpenAI's existing editorial layer already rewrites these as factual
        # 6–16 word ticker lines. Keep its wording; never invent facts here.
        compact = re.sub(r"\s+", " ", title).strip()
        key = re.sub(r"[^a-z0-9]+", " ", compact.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        item = dict(row)
        item.update({
            "eventType": category,
            "title": compact[:180],
            "keyInfo": True,
            "contextOnly": True,
            "editorialProvider": provider,
            "verifiedPlayable": False,
        })
        out.append(item)
    # Consequential facts are better than filling the ticker with articles. An
    # eight-item Key Info lane is fine; a twenty-item listicle feed is not.
    return out[:20]


def _refresh(server, force=False):
    if _STATE["refreshing"]:
        return False
    _STATE["refreshing"] = True
    try:
        raw = _raw_rows(server)
        sig = _signature(raw)
        with _CACHE_LOCK:
            old_sig = _CACHE.get("sourceSignature") or ""
            old_rows = list(_CACHE.get("data") or [])
            age = time.time() - float(_CACHE.get("savedAt") or 0)
        if not force and sig and sig == old_sig and old_rows and age < 1800:
            return True

        candidates = _factual_candidates(server, raw)
        edited = []
        provider = "RULES_KEY_INFO"
        # The model runs here in the daemon only. The request endpoint below is
        # strictly a memory/file read.
        if raw and callable(getattr(server, "openai_editorialize_events", None)) and callable(getattr(server, "read_openai_key", None)):
            try:
                if server.read_openai_key():
                    edited = list(server.openai_editorialize_events(raw[:40]) or [])
                    provider = "OPENAI_KEY_INFO"
                    _STATE["openaiRuns"] += 1
            except Exception as exc:
                _STATE["lastError"] = f"OpenAI: {type(exc).__name__}: {exc}"[:300]
        normalized = _normalize(edited, provider) if edited else _normalize(candidates, provider)
        if normalized:
            _persist(normalized, provider, sig)
            _STATE["lastRefreshAt"] = time.time()
            _STATE["lastError"] = ""
            if provider != "OPENAI_KEY_INFO":
                _STATE["ruleRuns"] += 1
            return True
        # Never replace a useful last-good Key Info snapshot with an empty pass.
        if old_rows:
            return True
        return False
    finally:
        _STATE["refreshing"] = False


def _worker():
    if _STOP.wait(5.0):
        return
    while not _STOP.is_set():
        if _SERVER:
            try:
                if hasattr(_SERVER,"_history_worker_beat"):
                    _SERVER._history_worker_beat("integrity-key-info","integrity:key-info")
                _refresh(_SERVER, force=False)
                if hasattr(_SERVER,"_history_worker_beat"):
                    _SERVER._history_worker_beat("integrity-key-info","integrity:idle",progress=True)
            except Exception as exc:
                _STATE["lastError"] = f"worker: {type(exc).__name__}: {exc}"[:300]
        _STOP.wait(600.0)


def _response():
    with _CACHE_LOCK:
        rows = [dict(x) for x in (_CACHE.get("data") or []) if isinstance(x, dict)]
        saved = float(_CACHE.get("savedAt") or 0)
        source = _clean(_CACHE.get("source")) or "KEY_INFO_CACHE"
    return {
        "ok": True,
        "version": VERSION,
        "current": True,
        "keyInfo": True,
        "data": rows[:20],
        "count": len(rows[:20]),
        "source": source,
        "savedAt": saved,
        "refreshing": bool(_STATE["refreshing"]),
        "categories": sorted({str(x.get("eventType") or "") for x in rows if x.get("eventType")}),
    }


def _install_into_server():
    global _SERVER
    _load()
    deadline = time.time() + 120
    server = None
    while time.time() < deadline:
        candidate = sys.modules.get("__main__")
        if candidate and hasattr(candidate, "Handler") and hasattr(candidate, "send_json"):
            server = candidate
            break
        time.sleep(0.2)
    if not server:
        return
    _SERVER = server
    try:
        lock=getattr(server,"HISTORY_WORKER_HEALTH_LOCK",None);health=getattr(server,"HISTORY_WORKER_HEALTH",None)
        if lock is not None and isinstance(health,dict):
            with lock:
                health.setdefault("integrity-key-info",{"heartbeat":time.time(),"phase":"integrity:starting","lastProgress":0.0,"iterations":0,"blocked":0,"current":""})
    except Exception:
        pass

    # Seed immediately from already-persisted v5.2.2 source rows using rules only;
    # OpenAI refinement follows in the worker and never delays startup.
    if not _CACHE.get("data"):
        try:
            candidates = _factual_candidates(server, _raw_rows(server))
            normalized = _normalize(candidates, "RULES_KEY_INFO")
            if normalized:
                _persist(normalized, "RULES_KEY_INFO", _signature(candidates))
        except Exception:
            pass

    Handler = server.Handler
    if not getattr(Handler, "__sbbCurrentNewsV523", False):
        old_get = Handler.do_GET

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/current-news":
                _STATE["served"] += 1
                payload = _response()
                return server.send_json(self, payload, 200, {
                    "Cache-Control": "no-store",
                    "X-SBB-Key-Info": payload.get("source", "KEY_INFO"),
                })
            if parsed.path == "/api/current-news/status":
                payload = _response()
                payload.update(copy.deepcopy(_STATE))
                return server.send_json(self, payload, 200, {"Cache-Control": "no-store"})
            return old_get(self)

        Handler.do_GET = do_GET
        Handler.__sbbCurrentNewsV523 = True

    _STATE["installed"] = True
    threading.Thread(target=_worker, daemon=True, name="sbb-key-info-intelligence-v523").start()


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return False
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-key-info-install-v523").start()
    return True


def diagnostics():
    with _CACHE_LOCK:
        return {**copy.deepcopy(_STATE), "cacheCount": len(_CACHE.get("data") or []), "source": _CACHE.get("source") or ""}


__all__ = ["VERSION", "install", "diagnostics"]

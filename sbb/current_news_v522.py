"""Sports Big Board v5.2.2 — current Key Info read model.

KEY INFO is current sports news and is intentionally independent of the date being
browsed on the score ribbon. The interactive endpoint is cache-only: it reads the
existing editorial desk, then a tiny persistent fallback snapshot. Network refresh
runs only in a daemon thread.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

VERSION = "5.2.2-current-news-1"
_STATE_DIR = Path(os.environ.get("SBB_STATE_DIR") or (Path.home() / ".sports-big-board")).expanduser()
_STATE_PATH = _STATE_DIR / "current-news-v522.json"
_INSTALL_LOCK = threading.Lock()
_CACHE_LOCK = threading.RLock()
_INSTALLED = False
_SERVER = None
_STOP = threading.Event()
_CACHE = {"savedAt": 0.0, "data": [], "source": ""}
_REFRESHING = False
_STATS = {"version": VERSION, "served": 0, "deskHits": 0, "persistentHits": 0, "fallbackRefreshes": 0, "lastError": "", "lastRefreshAt": 0.0}

_FEEDS = {
    "MLB": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/news?limit=8",
    "NFL": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news?limit=8",
    "NBA": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news?limit=8",
    "NHL": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/news?limit=8",
    "EPL": "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/news?limit=8",
    "MLS": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/news?limit=8",
}


def _clean(value):
    return str(value or "").strip()


def _load_persistent():
    global _CACHE
    try:
        payload = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            with _CACHE_LOCK:
                _CACHE = {"savedAt": float(payload.get("savedAt") or 0), "data": list(payload.get("data") or []), "source": _clean(payload.get("source"))}
    except Exception:
        pass


def _persist(rows, source):
    global _CACHE
    payload = {"savedAt": time.time(), "source": source, "data": rows[:30]}
    with _CACHE_LOCK:
        _CACHE = payload
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(_STATE_PATH)
    except Exception:
        pass


def _desk_rows(server):
    """Read already-finished editorial/cache rows; never starts network work."""
    try:
        lock = getattr(server, "EDITORIAL_SNAPSHOT_LOCK", None)
        snap = {}
        if lock is not None:
            with lock:
                snap = dict(getattr(server, "EDITORIAL_SNAPSHOT", {}) or {})
        else:
            snap = dict(getattr(server, "EDITORIAL_SNAPSHOT", {}) or {})
        rows = list(snap.get("data") or [])
        filter_fn = getattr(server, "_filter_ticker_items", None)
        if callable(filter_fn):
            rows = list(filter_fn(rows) or [])
        if not rows:
            bootstrap = getattr(server, "_bootstrap_key_info_from_caches", None)
            if callable(bootstrap):
                rows = list(bootstrap() or [])
        return [dict(x) for x in rows if isinstance(x, dict)][:30]
    except Exception as exc:
        _STATS["lastError"] = f"desk: {type(exc).__name__}: {exc}"
        return []


def _fetch_json(url, timeout=4.5):
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsBigBoard/5.2.2 current-news"})
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _published(row):
    return _clean(row.get("published") or row.get("publishedAt") or row.get("lastModified") or row.get("date"))


def _normalize_article(article, league):
    if not isinstance(article, dict):
        return None
    title = _clean(article.get("headline") or article.get("title"))
    if not title:
        return None
    description = _clean(article.get("description") or article.get("story") or article.get("summary"))
    links = article.get("links") or {}
    web = links.get("web") if isinstance(links, dict) else {}
    href = _clean((web or {}).get("href") if isinstance(web, dict) else "")
    if not href:
        href = _clean(article.get("link") or article.get("url"))
    images = article.get("images") or []
    image = ""
    if isinstance(images, list) and images:
        first = images[0] if isinstance(images[0], dict) else {}
        image = _clean(first.get("url") or first.get("href"))
    return {
        "eventType": "NEWS",
        "title": title,
        "description": description[:500],
        "publishedAt": _published(article),
        "date": _published(article),
        "league": league,
        "source": "ESPN",
        "sourceLabel": "ESPN",
        "externalUrl": href,
        "thumbnail": image,
        "verifiedPlayable": False,
        "contextOnly": True,
    }


def _ts(row):
    raw = _clean(row.get("publishedAt") or row.get("date"))
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _refresh_fallback():
    global _REFRESHING
    rows = []
    seen = set()
    try:
        # Fetch league feeds concurrently so a cold server gets a useful ticker in
        # one network round-trip window instead of waiting serially on six feeds.
        with ThreadPoolExecutor(max_workers=min(6, len(_FEEDS)), thread_name_prefix="sbb-news") as pool:
            futures = {pool.submit(_fetch_json, url): league for league, url in _FEEDS.items()}
            for future in as_completed(futures):
                if _STOP.is_set():
                    return
                league = futures[future]
                try:
                    payload = future.result()
                except Exception:
                    continue
                articles = payload.get("articles") or payload.get("news") or []
                for raw in articles:
                    item = _normalize_article(raw, league)
                    if not item:
                        continue
                    key = _clean(item.get("title")).lower()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    rows.append(item)
        rows.sort(key=_ts, reverse=True)
        if rows:
            _persist(rows[:30], "ESPN_NEWS_CACHE")
            _STATS["fallbackRefreshes"] += 1
            _STATS["lastRefreshAt"] = time.time()
            _STATS["lastError"] = ""
    except Exception as exc:
        _STATS["lastError"] = f"refresh: {type(exc).__name__}: {exc}"
    finally:
        with _CACHE_LOCK:
            _REFRESHING = False


def _schedule_refresh(force=False):
    global _REFRESHING
    with _CACHE_LOCK:
        age = time.time() - float(_CACHE.get("savedAt") or 0)
        if _REFRESHING or (not force and _CACHE.get("data") and age < 300):
            return False
        _REFRESHING = True
    threading.Thread(target=_refresh_fallback, daemon=True, name="sbb-current-news-refresh-v522").start()
    return True


def _rows(server):
    desk = _desk_rows(server)
    if desk:
        _STATS["deskHits"] += 1
        # Keep the last good desk rows as a durable fallback too.
        _persist(desk, "EDITORIAL_DESK")
        return desk, "EDITORIAL_DESK"
    with _CACHE_LOCK:
        cached = [dict(x) for x in (_CACHE.get("data") or []) if isinstance(x, dict)]
        source = _clean(_CACHE.get("source")) or "PERSISTENT"
    if cached:
        _STATS["persistentHits"] += 1
        return cached[:30], source
    return [], "EMPTY"


def _worker():
    # Editorial refresh is owned elsewhere. This worker only maintains the fallback
    # snapshot and sleeps while a current desk already exists.
    if _STOP.wait(1.0):
        return
    while not _STOP.is_set():
        server = _SERVER
        desk = _desk_rows(server) if server else []
        if desk:
            _persist(desk, "EDITORIAL_DESK")
            _STOP.wait(180.0)
            continue
        _schedule_refresh(force=False)
        _STOP.wait(300.0)


def _install_into_server():
    global _SERVER
    _load_persistent()
    deadline = time.time() + 120
    server = None
    while time.time() < deadline:
        candidate = sys.modules.get("__main__")
        if candidate and hasattr(candidate, "Handler") and hasattr(candidate, "send_json"):
            server = candidate
            break
        time.sleep(0.2)
    if not server:
        _STATS["lastError"] = "SERVER_INSTALL_TIMEOUT"
        return
    _SERVER = server
    Handler = server.Handler
    if not getattr(Handler, "__sbbCurrentNewsV522", False):
        old_get = Handler.do_GET

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/current-news":
                _STATS["served"] += 1
                rows, source = _rows(server)
                if not rows:
                    _schedule_refresh(force=False)
                with _CACHE_LOCK:
                    refreshing = bool(_REFRESHING)
                    saved_at = float(_CACHE.get("savedAt") or 0)
                return server.send_json(self, {
                    "ok": True,
                    "version": VERSION,
                    "current": True,
                    "data": rows[:20],
                    "count": len(rows[:20]),
                    "source": source,
                    "savedAt": saved_at,
                    "refreshing": refreshing,
                }, 200, {"Cache-Control": "no-store", "X-SBB-Key-Info": source})
            if parsed.path == "/api/current-news/status":
                with _CACHE_LOCK:
                    cache_count = len(_CACHE.get("data") or [])
                    refreshing = bool(_REFRESHING)
                return server.send_json(self, {"ok": True, **_STATS, "cacheCount": cache_count, "refreshing": refreshing}, 200)
            return old_get(self)

        Handler.do_GET = do_GET
        Handler.__sbbCurrentNewsV522 = True

    threading.Thread(target=_worker, daemon=True, name="sbb-current-news-v522").start()


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-current-news-install-v522").start()


def diagnostics():
    with _CACHE_LOCK:
        return {**_STATS, "installed": _INSTALLED, "cacheCount": len(_CACHE.get("data") or []), "cacheSource": _CACHE.get("source") or ""}

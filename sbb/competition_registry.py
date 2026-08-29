"""Sports Big Board Competition Registry 2.0.

The registry is the backend authority for competition existence and capabilities.
Built-in leagues and dynamically-created leagues/special events use the same
observable catalog.

Compatibility contract:
- COMPETITIONS remains a mutable mapping because the existing Competition Builder
  already registers custom competitions with COMPETITIONS[id] = definition.
- catalog() and enabled_ids() retain their original public API.
- direct set/pop/update operations emit registry events so backend services such as
  Day State enroll and remove competitions immediately without hard-coded league
  branches.
"""
from __future__ import annotations

from copy import deepcopy
import threading
import time


BUILT_IN_COMPETITIONS = {
    "MLB":{"id":"MLB","sportId":"baseball","name":"Major League Baseball","enabled":True,"scoreProvider":"highlightly","mediaProviders":["mlb-stats","espn","highlightly","youtube"],"gameCenterProvider":"highlightly","gameCenterFallback":"mlb-stats"},
    "NFL":{"id":"NFL","sportId":"american-football","name":"National Football League","enabled":True,"scoreProvider":"espn","mediaProviders":["nfl-youtube-playlist","nfl-public-video","nfl-team-video","espn","nfl-feed","highlightly","youtube"],"gameCenterProvider":"highlightly","gameCenterFallback":"espn"},
    "NBA":{"id":"NBA","sportId":"basketball","name":"National Basketball Association","enabled":True,"scoreProvider":"espn","mediaProviders":["espn","highlightly","youtube"],"gameCenterProvider":"highlightly","gameCenterFallback":"espn"},
    "NHL":{"id":"NHL","sportId":"ice-hockey","name":"National Hockey League","enabled":True,"scoreProvider":"espn","mediaProviders":["nhl-official","espn","highlightly","youtube"],"gameCenterProvider":"highlightly","gameCenterFallback":"espn"},
    "EPL":{"id":"EPL","sportId":"football","name":"Premier League","enabled":True,"scoreProvider":"espn","mediaProviders":["epl-youtube-pl","epl-youtube-nbc-extended","premierleague-official","nbc-epl-extended","espn","club-sites","highlightly","youtube"],"gameCenterProvider":"highlightly","gameCenterFallback":"espn"},
    "MLS":{"id":"MLS","sportId":"football","name":"Major League Soccer","enabled":True,"scoreProvider":"espn","mediaProviders":["mls-official-web","mls","espn","club-sites","highlightly","youtube"],"gameCenterProvider":"highlightly","gameCenterFallback":"espn"},
    "UCL":{"id":"UCL","sportId":"football","name":"UEFA Champions League","enabled":False},
    "ATP":{"id":"ATP","sportId":"tennis","name":"ATP Tour","enabled":False},
    "WTA":{"id":"WTA","sportId":"tennis","name":"WTA Tour","enabled":False},
    "F1":{"id":"F1","sportId":"motorsport","name":"Formula 1","enabled":False},
    "XGAMES":{"id":"XGAMES","sportId":"action-sports","name":"X Games","enabled":False},
    "TRACK":{"id":"TRACK","sportId":"athletics","name":"Track & Field","enabled":False},
}


def _clean_id(value):
    return str(value or "").upper().strip()


def _definition(value, *, competition_id="", source=""):
    raw = deepcopy(value if isinstance(value, dict) else {})
    cid = _clean_id(competition_id or raw.get("id"))
    if not cid:
        raise ValueError("Competition id is required.")
    custom = bool(raw.get("custom"))
    typ = str(raw.get("type") or ("SPECIAL_EVENT" if custom else "LEAGUE")).upper()
    source_kind = str(raw.get("sourceKind") or source or ("DYNAMIC" if custom else "BUILT_IN")).upper()
    out = {
        **raw,
        "id": cid,
        "name": str(raw.get("name") or cid),
        "sportId": str(raw.get("sportId") or "multi-sport"),
        "type": typ,
        "enabled": bool(raw.get("enabled", True)),
        "custom": custom,
        "sourceKind": source_kind,
        "backendRegistered": True,
        "historyEnabled": bool(raw.get("historyEnabled", True)),
        "dayStateEnabled": bool(raw.get("dayStateEnabled", True)),
        "registeredAt": float(raw.get("registeredAt") or time.time()),
    }
    out.setdefault("scoreProvider", "competition-builder" if custom else "")
    out.setdefault("mediaProviders", ["operator-playlist", "youtube"] if custom else [])
    out.setdefault("gameCenterProvider", "competition-builder" if custom else "")
    return out


class CompetitionCatalog(dict):
    """Thread-safe observable mapping with normal dict compatibility."""

    def __init__(self, initial=None):
        self._lock = threading.RLock()
        self._listeners = []
        self._revision = 0
        super().__init__()
        for key, value in (initial or {}).items():
            dict.__setitem__(self, _clean_id(key), _definition(value, competition_id=key, source="BUILT_IN"))
        self._revision = int(time.time() * 1000)

    @property
    def revision(self):
        with self._lock:
            return int(self._revision)

    def subscribe(self, callback, *, replay=False):
        if not callable(callback):
            raise TypeError("registry listener must be callable")
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)
            rows = [deepcopy(v) for v in self.values()] if replay else []
            revision = self._revision
        if replay:
            for row in rows:
                try:
                    callback({"action":"REGISTER","competition":row,"revision":revision,"replay":True})
                except Exception:
                    pass
        return callback

    def unsubscribe(self, callback):
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _notify(self, event):
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(deepcopy(event))
            except Exception:
                pass

    def __setitem__(self, key, value):
        cid = _clean_id(key or (value or {}).get("id") if isinstance(value, dict) else key)
        source = "DYNAMIC" if isinstance(value, dict) and value.get("custom") else ""
        row = _definition(value, competition_id=cid, source=source)
        with self._lock:
            existed = cid in self
            old = deepcopy(dict.get(self, cid)) if existed else None
            dict.__setitem__(self, cid, row)
            self._revision = max(int(time.time() * 1000), self._revision + 1)
            revision = self._revision
        self._notify({
            "action":"UPDATE" if existed else "REGISTER",
            "competition":deepcopy(row),
            "previous":old,
            "revision":revision,
        })

    def __delitem__(self, key):
        cid = _clean_id(key)
        with self._lock:
            old = deepcopy(dict.__getitem__(self, cid))
            dict.__delitem__(self, cid)
            self._revision = max(int(time.time() * 1000), self._revision + 1)
            revision = self._revision
        self._notify({"action":"UNREGISTER","competition":old,"revision":revision})

    def pop(self, key, default=None):
        cid = _clean_id(key)
        with self._lock:
            if cid not in self:
                return default
            old = deepcopy(dict.__getitem__(self, cid))
            dict.__delitem__(self, cid)
            self._revision = max(int(time.time() * 1000), self._revision + 1)
            revision = self._revision
        self._notify({"action":"UNREGISTER","competition":old,"revision":revision})
        return old

    def update(self, *args, **kwargs):
        incoming = dict(*args, **kwargs)
        for key, value in incoming.items():
            self[key] = value

    def snapshot(self):
        with self._lock:
            return {
                "revision": int(self._revision),
                "competitions": [deepcopy(v) for v in self.values()],
            }


COMPETITIONS = CompetitionCatalog(BUILT_IN_COMPETITIONS)


def register(definition, *, source="DYNAMIC"):
    row = _definition(definition, source=source)
    if source:
        row["sourceKind"] = str(source).upper()
    if row["sourceKind"] != "BUILT_IN":
        row["custom"] = bool(row.get("custom", True))
    COMPETITIONS[row["id"]] = row
    return deepcopy(COMPETITIONS[row["id"]])


def unregister(competition_id):
    return COMPETITIONS.pop(_clean_id(competition_id), None)


def get(competition_id, default=None):
    row = COMPETITIONS.get(_clean_id(competition_id))
    return deepcopy(row) if row is not None else default


def catalog():
    return COMPETITIONS.snapshot()["competitions"]


def enabled_ids():
    return [row["id"] for row in catalog() if row.get("enabled")]


def revision():
    return COMPETITIONS.revision


def subscribe(callback, *, replay=False):
    return COMPETITIONS.subscribe(callback, replay=replay)


def backend_catalog():
    snap = COMPETITIONS.snapshot()
    rows = snap["competitions"]
    return {
        "revision": snap["revision"],
        "total": len(rows),
        "enabled": sum(1 for row in rows if row.get("enabled")),
        "builtIn": sum(1 for row in rows if row.get("sourceKind") == "BUILT_IN"),
        "dynamic": sum(1 for row in rows if row.get("sourceKind") != "BUILT_IN"),
        "competitions": rows,
    }

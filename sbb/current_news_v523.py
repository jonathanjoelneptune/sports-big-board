"""Sports Big Board v5.2.6 — operator-refreshable Sports Ticker intelligence snapshot.

The interactive board only reads a persisted last-good edition. Collection, rules,
and the existing OpenAI editorial layer run in a background daemon every 20 minutes.
/api/current-news remains as a backwards-compatible alias; /api/sports-ticker is the
canonical endpoint.
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

VERSION = "5.2.6-sports-ticker-3"
_STATE_DIR = Path(os.environ.get("SBB_STATE_DIR") or (Path.home() / ".sports-big-board")).expanduser()
_STATE_PATH = _STATE_DIR / "sports-ticker.json"
_MIGRATION_PATHS = (_STATE_DIR / "sports-ticker-v524.json", _STATE_DIR / "key-info-intelligence-v523.json")
_REFRESH_SECONDS = 20 * 60
_MAX_ROWS = 150
_INSTALL_LOCK = threading.Lock()
_MANUAL_LOCK = threading.Lock()
_CACHE_LOCK = threading.RLock()
_INSTALLED = False
_SERVER = None
_STOP = threading.Event()
_CACHE = {"savedAt": 0.0, "source": "", "data": [], "sourceSignature": ""}
_STATE = {"version": VERSION, "installed": False, "refreshing": False, "lastRefreshAt": 0.0,
          "lastError": "", "openaiRuns": 0, "ruleRuns": 0, "served": 0, "refreshSeconds": _REFRESH_SECONDS,
          "newItemsLastRefresh": 0, "revision": 0, "ordering": "NEW_FIRST_STABLE",
          "manualRunning": False, "manualRuns": 0, "manualRequestedAt": 0.0, "manualCompletedAt": 0.0,
          "manualSourceCount": 0, "manualLastError": "", "manualLastResult": "", "openaiConfigured": False}

_NOISE = re.compile(r"\b(prediction|predictions|preview|mock draft|fantasy|betting|odds|picks?|mailbag|podcast|best .* list|top \d+ list|power rankings? preview)\b", re.I)
_CATEGORY_PATTERNS = [
    ("BREAKING", re.compile(r"\b(breaking|breaking news|emergency|hospitalized|dies|died|death)\b", re.I)),
    ("CHAMPIONSHIP", re.compile(r"\b(wins? the (?:title|championship|cup)|champion|championship winner|title winner)\b", re.I)),
    ("CLINCH", re.compile(r"\b(clinch|clinched|playoff berth|division title|conference title|first-round bye|home-field)\b", re.I)),
    ("ELIMINATION", re.compile(r"\b(eliminated|elimination|relegated|knocked out)\b", re.I)),
    ("UPSET", re.compile(r"\b(upset|stuns?|shocks?|knocks off|defeats? no\.? ?\d+|beats? no\.? ?\d+)\b", re.I)),
    ("RECORD_WATCH", re.compile(r"\b(record watch|away from|shy of|needs? .* to (?:tie|break|move into))\b", re.I)),
    ("RECORD", re.compile(r"\b(record|historic|history|first (?:player|team|rookie)|most .* ever|single[- ]season|franchise high|career high|youngest|oldest)\b", re.I)),
    ("MILESTONE", re.compile(r"\b(milestone|\d+(?:st|nd|rd|th) career|\d+th (?:home run|goal|win|hit|touchdown|strikeout)|joins .* club)\b", re.I)),
    ("STREAK", re.compile(r"\b(streak|straight (?:win|loss)|wins? in a row|losses? in a row|unbeaten|undefeated|winless|consecutive)\b", re.I)),
    ("PLAYOFF", re.compile(r"\b(playoff picture|wild card|wild-card|seed|postseason|magic number|bubble|cfp)\b", re.I)),
    ("RANKING", re.compile(r"\b(ap top 25|coaches poll|cfp rankings?|moves? to no\.?|rises? to no\.?|falls? to no\.?|ranked no\.?)\b", re.I)),
    ("TRANSACTION", re.compile(r"\b(traded?|trade(?:s|d)?|acquired?|signs?|signed|signing|re-signs?|extension|released?|waived?|claimed|designated for assignment|dfa)\b", re.I)),
    ("INJURY", re.compile(r"\b(injur|out for|ruled out|placed on (?:IL|IR)|concussion|torn|sprain|fracture|surgery|questionable to return)\b", re.I)),
    ("RETURN", re.compile(r"\b(returns? from|activated from|cleared to play|season debut|returns? tonight)\b", re.I)),
    ("COACHING", re.compile(r"\b(fired|hired|head coach|manager fired|manager hired|coaching change|steps down|resigns)\b", re.I)),
    ("SUSPENSION", re.compile(r"\b(suspend|suspension|banned|discipline|fined|eligibility ruling|waiver denied|waiver approved)\b", re.I)),
    ("TOURNAMENT", re.compile(r"\b(advances? to|quarterfinal|semifinal|final four|sweet 16|elite eight|knockout round|group winner|final matchup|game 7)\b", re.I)),
    ("RESULT", re.compile(r"\b(walk-off|buzzer beater|overtime|extra innings?|comeback|no-hitter|perfect game|hat trick|cycle|shootout)\b", re.I)),
    ("SCHEDULE", re.compile(r"\b(postponed|rescheduled|doubleheader|venue change|time change|weather delay|rain delay|suspended game)\b", re.I)),
    ("RETIREMENT", re.compile(r"\b(retir|final season|calls it a career)\b", re.I)),
    ("DRAFT", re.compile(r"\b(draft lottery|declares? for the draft|first overall pick|no\. 1 pick)\b", re.I)),
    ("RECRUITING", re.compile(r"\b(five-star|commit(?:s|ted)|decommit|transfer portal|signing day)\b", re.I)),
    ("AWARD", re.compile(r"\b(mvp|cy young|heisman|rookie of the year|hart trophy|vezina|ballon d'or|player of the week)\b", re.I)),
]
_IMPORTANCE = {"BREAKING":100,"CHAMPIONSHIP":98,"RECORD":95,"CLINCH":94,"ELIMINATION":93,"UPSET":92,
               "INJURY":90,"TRANSACTION":88,"RESULT":86,"RECORD_WATCH":84,"PLAYOFF":82,"MILESTONE":80,
               "TOURNAMENT":78,"RANKING":76,"STREAK":74,"COACHING":72,"SUSPENSION":72,"RETURN":68,
               "RETIREMENT":68,"DRAFT":64,"RECRUITING":62,"SCHEDULE":58,"AWARD":52}


def _clean(v): return str(v or "").strip()

def _load():
    global _CACHE
    for path in (_STATE_PATH, *_MIGRATION_PATHS):
        try:
            payload=json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload,dict) and isinstance(payload.get("data"),list):
                with _CACHE_LOCK:
                    _CACHE={"savedAt":float(payload.get("savedAt") or 0),"source":_clean(payload.get("source")),
                            "data":[dict(x) for x in payload.get("data") if isinstance(x,dict)][:_MAX_ROWS],
                            "sourceSignature":_clean(payload.get("sourceSignature"))}
                if path != _STATE_PATH and _CACHE.get("data"):
                    _persist(_CACHE["data"], _CACHE.get("source") or "MIGRATED_SPORTS_TICKER", _CACHE.get("sourceSignature") or "")
                return True
        except Exception: pass
    return False

def _persist(rows, source, signature):
    global _CACHE
    payload={"version":VERSION,"savedAt":time.time(),"source":source,"sourceSignature":signature,"data":rows[:_MAX_ROWS]}
    with _CACHE_LOCK: _CACHE=payload
    try:
        _STATE_PATH.parent.mkdir(parents=True,exist_ok=True);tmp=_STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":"),default=str),encoding="utf-8");os.replace(tmp,_STATE_PATH)
    except Exception: pass

def _recent_enough(row, max_age_seconds=36*60*60):
    raw=_clean(row.get("publishedAt") or row.get("updatedAt") or row.get("timestamp") or row.get("date"))
    if not raw:return False
    try:
        from datetime import datetime
        ts=datetime.fromisoformat(raw.replace("Z","+00:00")).timestamp()
        return (time.time()-ts) <= max_age_seconds
    except Exception:return False

def _collect_live_source_rows():
    """Explicit operator refresh: hit the existing current-news league feeds now.

    This is never called from an interactive GET. It runs only in the manual refresh
    worker, so provider/network work remains outside the board's request lane.
    """
    rows=[];seen=set();feeds=dict(getattr(source_v522,"_FEEDS",{}) or {})
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        fetch=getattr(source_v522,"_fetch_json",None);normalize=getattr(source_v522,"_normalize_article",None)
        if not feeds or not callable(fetch) or not callable(normalize):return []
        with ThreadPoolExecutor(max_workers=min(6,len(feeds)),thread_name_prefix="sbb-ticker-manual") as pool:
            futures={pool.submit(fetch,url):league for league,url in feeds.items()}
            for future in as_completed(futures):
                league=futures[future]
                try:payload=future.result() or {}
                except Exception:continue
                for raw in (payload.get("articles") or payload.get("news") or []):
                    try:item=normalize(raw,league)
                    except Exception:item=None
                    if not item:continue
                    key=re.sub(r"[^a-z0-9]+"," ",_clean(item.get("title")).lower()).strip()
                    if not key or key in seen:continue
                    seen.add(key);rows.append(dict(item))
        rows.sort(key=lambda x:_timestamp(x),reverse=True)
        if rows:
            try:source_v522._persist(rows[:30],"ESPN_NEWS_MANUAL")
            except Exception:pass
        return rows[:80]
    except Exception as exc:
        _STATE["manualLastError"]=f"source collection: {type(exc).__name__}: {exc}"[:300]
        return []

def _raw_rows(server, seed_rows=None, fresh_only=False):
    rows=[dict(x) for x in (seed_rows or []) if isinstance(x,dict)]
    try:
        lock=getattr(server,"EDITORIAL_SNAPSHOT_LOCK",None)
        if lock:
            with lock: snap=copy.deepcopy(getattr(server,"EDITORIAL_SNAPSHOT",{}) or {})
        else: snap=copy.deepcopy(getattr(server,"EDITORIAL_SNAPSHOT",{}) or {})
        desk=[dict(x) for x in (snap.get("data") or []) if isinstance(x,dict)]
        rows.extend(x for x in desk if (not fresh_only or _recent_enough(x)))
    except Exception: pass
    try:
        desk=[dict(x) for x in source_v522._desk_rows(server) if isinstance(x,dict)]
        rows.extend(x for x in desk if (not fresh_only or _recent_enough(x)))
    except Exception: pass
    if not fresh_only:
        try:
            fallback,_=source_v522._rows(server);rows.extend(dict(x) for x in fallback if isinstance(x,dict))
        except Exception: pass
        # Consume already-materialized server candidates without causing provider work.
        for name in ("_bootstrap_key_info_from_caches","_cached_key_info_events","_current_ticker_rows"):
            try:
                fn=getattr(server,name,None)
                if callable(fn): rows.extend(dict(x) for x in (fn() or []) if isinstance(x,dict))
            except Exception: pass
    out=[];seen=set()
    for row in rows:
        title=_clean(row.get("title") or row.get("headline") or row.get("shortHeadline"))
        if not title: continue
        key=re.sub(r"[^a-z0-9]+"," ",title.lower()).strip()
        if not key or key in seen: continue
        seen.add(key);out.append(row)
    return out[:300]

def _signature(rows):
    text="|".join(f"{_clean(x.get('id'))}:{_clean(x.get('title') or x.get('headline'))}:{_clean(x.get('publishedAt') or x.get('date'))}" for x in rows[:200])
    return hashlib.sha1(text.encode("utf-8","ignore")).hexdigest() if text else ""

def _category(row):
    explicit=_clean(row.get("eventType") or row.get("category")).upper().replace(" ","_")
    if explicit and explicit not in {"NEWS","UPDATE","ARTICLE","STORY","OTHER"}:
        aliases={"TRADE":"TRANSACTION","SIGNING":"TRANSACTION","ROSTER":"TRANSACTION","SHAKEUP":"COACHING","HISTORIC":"RECORD"}
        return aliases.get(explicit,explicit[:24])
    text=f"{_clean(row.get('title'))} {_clean(row.get('headline'))} {_clean(row.get('description'))}"
    for label,pattern in _CATEGORY_PATTERNS:
        if pattern.search(text): return label
    return ""

def _ticker_key(row):
    explicit=_clean(row.get("tickerKey"))
    if explicit:return explicit
    title=_clean(row.get("shortHeadline") or row.get("headline") or row.get("title"))
    ident=_clean(row.get("id") or row.get("eventId") or row.get("gameId") or row.get("sourceUrl") or row.get("externalUrl"))
    category=_clean(row.get("category") or row.get("eventType"))
    raw=f"{ident}|{title}|{category}".lower()
    return hashlib.sha1(raw.encode("utf-8","ignore")).hexdigest()[:24] if title else ""

def _timestamp(row):
    raw=_clean(row.get("publishedAt") or row.get("updatedAt") or row.get("timestamp") or row.get("date"))
    if not raw:return 0.0
    try:
        from datetime import datetime
        return datetime.fromisoformat(raw.replace("Z","+00:00")).timestamp()
    except Exception:return 0.0

def _normalize(rows,provider):
    out=[];seen=set()
    for row in rows:
        title=_clean(row.get("title") or row.get("headline") or row.get("shortHeadline"))
        if not title or _NOISE.search(title): continue
        cat=_category(row)
        if not cat: continue
        compact=re.sub(r"\s+"," ",title).strip()[:200]
        item=dict(row)
        item.update({"eventType":cat,"category":cat,"title":compact,"headline":compact,"shortHeadline":compact[:140],
                     "importance":max(int(item.get("importance") or 0),_IMPORTANCE.get(cat,45)),"sportsTicker":True,
                     "keyInfo":True,"contextOnly":True,"editorialProvider":provider,"verifiedPlayable":False})
        key=_ticker_key(item)
        if not key or key in seen:continue
        seen.add(key);item["tickerKey"]=key;out.append(item)
    # Fresh candidates are newest-first; importance breaks ties. Stable session ordering
    # is applied by _merge_new_first so an old story never jumps around the conveyor.
    out.sort(key=lambda x:(_timestamp(x),int(x.get("importance") or 0)),reverse=True)
    return out[:_MAX_ROWS]

def _merge_new_first(fresh,old,now=None):
    now=float(now or time.time());old=[dict(x) for x in old if isinstance(x,dict)]
    old_by={_ticker_key(x):x for x in old if _ticker_key(x)}
    fresh_by={_ticker_key(x):x for x in fresh if _ticker_key(x)}
    new=[]
    for item in fresh:
        key=_ticker_key(item)
        if not key or key in old_by:continue
        row=dict(item);row.setdefault("firstSeenAt",now);row["lastSeenAt"]=now;new.append(row)
    retained=[];seen=set()
    for prior in old:
        key=_ticker_key(prior)
        if not key or key in seen:continue
        seen.add(key)
        if key in fresh_by:
            row={**prior,**fresh_by[key]};row["firstSeenAt"]=prior.get("firstSeenAt") or now;row["lastSeenAt"]=now
        else:row=prior
        retained.append(row)
    merged=(new+retained)[:_MAX_ROWS]
    return merged,len(new)

def _refresh(server,force=False,seed_rows=None,replace=False,require_openai=False,fresh_only=False,manual=False):
    if _STATE["refreshing"] or (_STATE.get("manualRunning") and not manual): return False
    _STATE["refreshing"]=True
    try:
        raw=_raw_rows(server,seed_rows=seed_rows,fresh_only=fresh_only);sig=_signature(raw)
        with _CACHE_LOCK:
            old_sig=_CACHE.get("sourceSignature") or "";old_rows=[dict(x) for x in (_CACHE.get("data") or [])];age=time.time()-float(_CACHE.get("savedAt") or 0)
        if not force and sig and sig==old_sig and old_rows and age<_REFRESH_SECONDS:
            _STATE["newItemsLastRefresh"]=0;return True
        edited=[];provider="RULES_SPORTS_TICKER"
        editor=getattr(server,"openai_editorialize_events",None);key_reader=getattr(server,"read_openai_key",None)
        key=""
        try:key=key_reader() if callable(key_reader) else ""
        except Exception:key=""
        _STATE["openaiConfigured"]=bool(key)
        if require_openai and (not key or not callable(editor)):
            raise RuntimeError("OpenAI is not configured on the Sports Big Board backend")
        if raw and callable(editor) and key:
            try:
                edited=list(editor(raw[:160]) or [])
                if edited:
                    provider="OPENAI_SPORTS_TICKER";_STATE["openaiRuns"]+=1
                elif require_openai:
                    raise RuntimeError("OpenAI returned no Sports Ticker editorial rows")
            except Exception as exc:
                if require_openai: raise
                _STATE["lastError"]=f"OpenAI: {type(exc).__name__}: {exc}"[:300]
        fresh=_normalize(edited,provider) if edited else _normalize(raw,provider)
        if fresh:
            if replace:
                old_keys={_ticker_key(x) for x in old_rows if _ticker_key(x)}
                merged=[dict(x) for x in fresh[:_MAX_ROWS]];new_count=sum(1 for x in merged if _ticker_key(x) not in old_keys)
            else:
                merged,new_count=_merge_new_first(fresh,old_rows)
            _persist(merged,provider,sig);_STATE["lastRefreshAt"]=time.time();_STATE["lastError"]=""
            _STATE["newItemsLastRefresh"]=new_count;_STATE["revision"]+=1
            if provider!="OPENAI_SPORTS_TICKER": _STATE["ruleRuns"]+=1
            return True
        _STATE["newItemsLastRefresh"]=0
        return bool(old_rows) # stale is always better than blank for automatic refreshes
    finally: _STATE["refreshing"]=False

def _manual_refresh_worker(server,requested_at):
    try:
        live=_collect_live_source_rows();_STATE["manualSourceCount"]=len(live)
        if not live:raise RuntimeError("Fresh sports-news collection returned no stories")
        ok=_refresh(server,force=True,seed_rows=live,replace=True,require_openai=True,fresh_only=True,manual=True)
        if not ok:raise RuntimeError("Sports Ticker AI refresh produced no usable edition")
        _STATE["manualCompletedAt"]=time.time();_STATE["manualLastError"]=""
        _STATE["manualLastResult"]=f"OPENAI refreshed {len(_CACHE.get('data') or [])} stories from {len(live)} fresh source rows"
    except Exception as exc:
        _STATE["manualCompletedAt"]=time.time();_STATE["manualLastError"]=f"{type(exc).__name__}: {exc}"[:300]
        _STATE["manualLastResult"]="FAILED"
    finally:
        _STATE["manualRunning"]=False

def _start_manual_refresh(server):
    with _MANUAL_LOCK:
        if _STATE.get("manualRunning") or _STATE.get("refreshing"):
            raise RuntimeError("A Sports Ticker refresh is already running")
        try:
            reader=getattr(server,"read_openai_key",None);key=reader() if callable(reader) else ""
        except Exception:key=""
        _STATE["openaiConfigured"]=bool(key)
        if not key:raise RuntimeError("OpenAI key is not configured on the backend")
        requested=time.time();_STATE["manualRunning"]=True;_STATE["manualRuns"]+=1
        _STATE["manualRequestedAt"]=requested;_STATE["manualCompletedAt"]=0.0;_STATE["manualSourceCount"]=0
        _STATE["manualLastError"]="";_STATE["manualLastResult"]="STARTED"
        threading.Thread(target=_manual_refresh_worker,args=(server,requested),daemon=True,name="sbb-sports-ticker-manual-v526").start()
        return True,requested

def _worker():
    if _STOP.wait(3.0): return
    while not _STOP.is_set():
        if _SERVER:
            try:
                if hasattr(_SERVER,"_history_worker_beat"): _SERVER._history_worker_beat("integrity-sports-ticker","integrity:sports-ticker")
                _refresh(_SERVER,force=False)
                if hasattr(_SERVER,"_history_worker_beat"): _SERVER._history_worker_beat("integrity-sports-ticker","integrity:idle",progress=True)
            except Exception as exc: _STATE["lastError"]=f"worker: {type(exc).__name__}: {exc}"[:300]
        _STOP.wait(_REFRESH_SECONDS)

def _response():
    with _CACHE_LOCK:
        rows=[dict(x) for x in (_CACHE.get("data") or []) if isinstance(x,dict)];saved=float(_CACHE.get("savedAt") or 0);source=_clean(_CACHE.get("source")) or "SPORTS_TICKER_CACHE"
    return {"ok":True,"version":VERSION,"current":True,"sportsTicker":True,"data":rows[:_MAX_ROWS],"count":len(rows[:_MAX_ROWS]),
            "source":source,"savedAt":saved,"refreshing":bool(_STATE["refreshing"] or _STATE.get("manualRunning")),"manualRunning":bool(_STATE.get("manualRunning")),"refreshSeconds":_REFRESH_SECONDS,
            "nextRefreshAt":saved+_REFRESH_SECONDS if saved else 0,"categories":sorted({str(x.get("eventType") or "") for x in rows if x.get("eventType")}),
            "ordering":"NEW_FIRST_STABLE","revision":int(_STATE.get("revision") or 0),"newItemsLastRefresh":int(_STATE.get("newItemsLastRefresh") or 0)}

def _install_into_server():
    global _SERVER
    _load();deadline=time.time()+120;server=None
    while time.time()<deadline:
        candidate=sys.modules.get("__main__")
        if candidate and hasattr(candidate,"Handler") and hasattr(candidate,"send_json"): server=candidate;break
        time.sleep(.2)
    if not server: return
    _SERVER=server
    if not _CACHE.get("data"):
        try:
            seeded=_normalize(_raw_rows(server),"RULES_SPORTS_TICKER")
            if seeded:_persist(seeded,"RULES_SPORTS_TICKER",_signature(seeded))
        except Exception: pass
    Handler=server.Handler
    if not getattr(Handler,"__sbbSportsTickerV526",False):
        old_get=Handler.do_GET;old_post=getattr(Handler,"do_POST",None)
        def do_GET(self):
            parsed=urlparse(self.path)
            if parsed.path in {"/api/sports-ticker","/api/current-news"}:
                _STATE["served"]+=1;payload=_response()
                return server.send_json(self,payload,200,{"Cache-Control":"no-store","X-SBB-Sports-Ticker":payload.get("source","SPORTS_TICKER")})
            if parsed.path in {"/api/sports-ticker/status","/api/current-news/status"}:
                payload=_response();payload.update(copy.deepcopy(_STATE));return server.send_json(self,payload,200,{"Cache-Control":"no-store"})
            return old_get(self)
        def do_POST(self):
            parsed=urlparse(self.path)
            if parsed.path=="/api/sports-ticker/refresh":
                try:
                    started,requested=_start_manual_refresh(server)
                except RuntimeError as exc:
                    return server.send_json(self,{**_response(),"ok":False,"error":str(exc)},409,{"Cache-Control":"no-store"})
                payload=_response();payload.update({"ok":True,"accepted":bool(started),"requestedAt":requested,"manualRunning":True})
                return server.send_json(self,payload,202,{"Cache-Control":"no-store"})
            if callable(old_post):return old_post(self)
            try:self.send_error(404)
            except Exception:pass
        Handler.do_GET=do_GET;Handler.do_POST=do_POST;Handler.__sbbSportsTickerV526=True
    _STATE["installed"]=True
    threading.Thread(target=_worker,daemon=True,name="sbb-sports-ticker-v526").start()

def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:return False
        _INSTALLED=True
    threading.Thread(target=_install_into_server,daemon=True,name="sbb-sports-ticker-install-v526").start();return True

def diagnostics():
    with _CACHE_LOCK:return {**copy.deepcopy(_STATE),"cacheCount":len(_CACHE.get("data") or []),"source":_CACHE.get("source") or ""}

__all__=["VERSION","install","diagnostics"]

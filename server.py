#!/usr/bin/env python3
"""Sports Big Board v4.0.2 local/cloud backend.
Serves the same-origin development app or an HTTPS API for the GitHub Pages frontend.
Provider credentials and persistent historical state remain server-side.
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode, quote_plus, urljoin, unquote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json
import os
import csv
import io
import zipfile
import copy
import hashlib
import html
import pathlib
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from collections import deque
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sbb.competition_registry import COMPETITIONS, catalog as competition_catalog, enabled_ids as enabled_competition_ids
from sbb.provider_registry import SPORT_API, BASE_URL, MEDIA_ADAPTERS, media_adapters_for
from sbb.media_work_scheduler import MediaWorkScheduler, PRIORITY as MEDIA_PRIORITY
from sbb.game_center import fetch_mlb_game_center, fetch_espn_game_center, normalize_highlightly_game_center, game_center_coverage, merge_game_centers
from sbb.media_classifier import annotate as annotate_media_tier
from sbb.media_scope import annotate as annotate_media_scope, classify as classify_media_scope, collection_kind as media_collection_kind, week_key as media_week_key, GAME as MEDIA_SCOPE_GAME, DAY_LEAGUE as MEDIA_SCOPE_DAY_LEAGUE, WEEK_LEAGUE as MEDIA_SCOPE_WEEK_LEAGUE, COLLECTION_SCOPES as MEDIA_COLLECTION_SCOPES
from sbb.media_policy import POLICIES as SPORT_MEDIA_POLICIES, REQUESTS as MEDIA_REQUESTS
from sbb.editorial_registry import catalog as editorial_series_catalog
from sbb.game_center_repository import GameCenterRepository
from sbb.history_repository import HistoryRepository
from sbb.catalog_contract import CATALOG_SCHEMA_VERSION
from sbb.event_matcher import match_event as match_media_to_event
from sbb.youtube_gateway import YouTubeGateway, YouTubeRateLimited
from sbb.secrets import get_secret, set_secrets, status as secrets_status, migrate_legacy as migrate_legacy_secrets, SECRETS_FILE

APP_VERSION = "4.0.2"
PORT = int(os.environ.get("PORT", "8080"))
BIND_HOST = os.environ.get("SBB_BIND_HOST", "127.0.0.1").strip() or "127.0.0.1"
ROOT = pathlib.Path(__file__).resolve().parent
STATE_DIR = pathlib.Path(os.environ.get("SBB_STATE_DIR") or (pathlib.Path.home() / ".sports-big-board")).expanduser()
STATE_DIR.mkdir(parents=True, exist_ok=True)
CLOUD_MODE = str(os.environ.get("SBB_CLOUD_MODE", "0")).lower() in ("1", "true", "yes", "on")
DEPLOYMENT_MODE = "cloud-stage1" if CLOUD_MODE else "local"
ALLOWED_ORIGINS = {x.strip().rstrip("/") for x in os.environ.get("SBB_ALLOWED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080").split(",") if x.strip()}
ALLOWED_ORIGIN_SUFFIXES = tuple(x.strip().lower() for x in os.environ.get("SBB_ALLOWED_ORIGIN_SUFFIXES", ".github.io").split(",") if x.strip()) if CLOUD_MODE else tuple()

def _cors_allowed_origin(origin):
    origin=str(origin or "").strip().rstrip("/")
    if not origin: return ""
    if "*" in ALLOWED_ORIGINS: return "*"
    if origin in ALLOWED_ORIGINS: return origin
    if CLOUD_MODE and ALLOWED_ORIGIN_SUFFIXES:
        try:
            parsed=urlparse(origin)
            host=(parsed.hostname or "").lower()
            if parsed.scheme == "https" and any(host.endswith(suffix) for suffix in ALLOWED_ORIGIN_SUFFIXES):
                return origin
        except Exception:
            pass
    return ""
KEY_FILE = ROOT / ".highlightly-key"
GLOBAL_KEY_FILE = STATE_DIR / "highlightly-key"
YOUTUBE_KEY_FILE = STATE_DIR / "youtube-key"
OPENAI_KEY_FILE = STATE_DIR / "openai-key"
OPENAI_API_BASE = "https://api.openai.com/v1"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
YOUTUBE_GATEWAY = YouTubeGateway(user_agent="SportsBigBoard/4.0.2", state_file=STATE_DIR / "cache" / "youtube_gateway_state.json", quota_timezone="America/Los_Angeles")

def youtube_fetch_json(url, timeout=10):
    """Operation-aware YouTube broker.

    search.list, videos.list and activities.list have independent failure domains.
    A live search quota failure therefore cannot disable historical metadata
    validation or official-channel activity indexing.
    """
    return YOUTUBE_GATEWAY.fetch_json(url, timeout=timeout)

MLB_YOUTUBE_CHANNEL_ID = "UCoLrcjPV5PbUrUyXq5mjc_A"  # verified @MLB channel
MLS_YOUTUBE_CHANNEL_ID = "UCSZbXT5TLLW_i-5W8FZpFsg"  # verified @MLS channel
NFL_YOUTUBE_CHANNEL_ID = "UCDVYQ4Zhbm3S2dlz7P1GBDg"  # verified @NFL channel
NBA_YOUTUBE_CHANNEL_ID = "UCWJ2lWNubArHWmf3FIHbfcQ"  # verified @NBA channel
NHL_YOUTUBE_CHANNEL_ID = "UCqFMzb-4AUf6WAIbl132QKA"  # verified @NHL channel
YOUTUBE_OFFICIAL_CHANNEL_IDS = {
    "MLB": MLB_YOUTUBE_CHANNEL_ID,
    "NFL": NFL_YOUTUBE_CHANNEL_ID,
    "NBA": NBA_YOUTUBE_CHANNEL_ID,
    "NHL": NHL_YOUTUBE_CHANNEL_ID,
    "MLS": MLS_YOUTUBE_CHANNEL_ID,
    "EPL": "UCG5qGWdu8nIRZqJ_GgDwQ-w",  # official Premier League channel
}
YOUTUBE_CACHE_DIR = STATE_DIR / "cache" / "youtube"
YOUTUBE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
EVENT_CACHE_DIR = STATE_DIR / "cache" / "events"
EVENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
TOP_PLAYS_CACHE_DIR = STATE_DIR / "cache" / "top-plays"
TOP_PLAYS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
SOCCER_SCHEDULE_CACHE_DIR = STATE_DIR / "cache" / "soccer-schedule"
SOCCER_SCHEDULE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
SCOREBOARD_CACHE_DIR = STATE_DIR / "cache" / "scoreboards"
SCOREBOARD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
SOCCER_PROVIDER_COOLDOWN = {"until":0.0,"reason":""}
MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"
ESPN_SITE_API = "https://site.api.espn.com/apis/site/v2/sports"
ESPN_SEARCH_API = "https://site.web.api.espn.com/apis/search/v2"
ESPN_RSS = {"MLB":"https://www.espn.com/espn/rss/mlb/news","NFL":"https://www.espn.com/espn/rss/nfl/news","NBA":"https://www.espn.com/espn/rss/nba/news","NHL":"https://www.espn.com/espn/rss/nhl/news"}
STATS_CACHE = {}
CACHE_DIR = STATE_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
GAME_CENTER_CACHE_DIR = CACHE_DIR / "game-centers"
GAME_CENTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
GAME_CENTER_DB = CACHE_DIR / "game-centers.sqlite3"
HISTORY_DB = CACHE_DIR / "history.sqlite3"
HISTORY_YOUTUBE_BUDGET_FILE = CACHE_DIR / "history_youtube_budget.json"
HISTORY_YOUTUBE_SEARCH_BUDGET = max(0,int(os.environ.get("SBB_HISTORY_YOUTUBE_SEARCH_BUDGET","72")))
# Search-list quota is partitioned so historical work cannot starve current games.
HISTORY_YOUTUBE_BUDGET_SHARES = {"recent":0.40,"empty":0.30,"blue":0.20,"archive":0.10}
HISTORY_YOUTUBE_BUDGET_LOCK = threading.RLock()
HISTORY_REPOSITORY = HistoryRepository(HISTORY_DB)
# v4 is a normalized baseline. Production v3 catalogs are reconstructed offline
# with tools/rebuild_history_v4.py and then atomically installed after audit; the
# server never performs destructive/in-place history migration at startup.
HISTORY_SCOPE_MIGRATION = {"baseline":"v4-normalized","catalogSchemaVersion":CATALOG_SCHEMA_VERSION}
HISTORY_LEAGUES = ("MLB","NFL","NBA","NHL","EPL","MLS")
HISTORY_BACKFILL_DAYS = max(0,int(os.environ.get("SBB_HISTORY_BACKFILL_DAYS","400")))
HISTORY_BACKFILL_MEDIA = str(os.environ.get("SBB_HISTORY_BACKFILL_MEDIA","1")).lower() not in ("0","false","no","off")
HISTORY_BACKFILL_STATE = {"running":False,"lastDate":"","lastRun":0.0,"lastError":"","daysCompleted":0,"mediaItems":0,"deepGames":0}
HISTORY_DISCOVERY_LOCK = threading.RLock()
HISTORY_DISCOVERY_STATE = {}
HISTORY_DISCOVERY_VERSION = 13
# Historical playback preference is deliberately editorial-first: a produced
# commentary package is the best default, followed by a concise full recap, an
# extended package, then a clip/reel fallback. Discovery completion is separate
# from playability so finding a blue/green asset never prematurely ends indexing.
HISTORY_TIER_PRIORITY = {"gold":4,"green":3,"extended":2,"blue":1}
HISTORY_TIER_ORDER = ("gold","green","extended","blue")
# v4.0.2 separates source exhaustion from media-quality satisfaction. A playable
# Blue/Purple/Green asset is retained and remains instantly usable, but the event
# stays upgrade-eligible until a Gold package is found. Retry cadence is deliberately
# gentle for old dates so the always-on cloud catalog improves without hammering
# providers or search quota.
HISTORY_QUALITY_TARGET_TIER = "gold"
HISTORY_UPGRADE_RETRY_RECENT = {"blue":30*60,"extended":2*60*60,"green":12*60*60}
HISTORY_UPGRADE_RETRY_ARCHIVE = {"blue":2*60*60,"extended":12*60*60,"green":3*24*60*60}
# v4.0.2 adds a dedicated Green-gap worker. Normal date backfill keeps walking the
# archive, while this queue explicitly revisits games whose best verified asset is
# Blue/Purple/None and tries the authoritative recap lanes again. It is deliberately
# quota-light and can run while the website is open.
HISTORY_GREEN_GAP_STATE = {"running":False,"lastRun":0.0,"lastDate":"","lastLeague":"","lastEventId":"","lastBestTier":"","lastResultTier":"","lastError":"","attempts":0,"upgradedToGreen":0}
HISTORY_GREEN_GAP_INTERVAL = max(20,int(os.environ.get("SBB_HISTORY_GREEN_GAP_INTERVAL","45")))
HISTORY_GREEN_SEARCH_RESCUE_INTERVAL = max(5*60,int(os.environ.get("SBB_HISTORY_GREEN_SEARCH_RESCUE_INTERVAL","1200") or 1200))
HISTORY_GREEN_SEARCH_RESCUE_STATE = {"lastAt":0.0}
HISTORY_BACKGROUND_MEDIA_PAUSE_SECONDS = max(2,int(os.environ.get("SBB_HISTORY_BACKGROUND_MEDIA_PAUSE_SECONDS","8")))
HISTORY_BACKGROUND_INTERACTIVE_PAUSE_SECONDS = max(1,int(os.environ.get("SBB_HISTORY_BACKGROUND_INTERACTIVE_PAUSE_SECONDS","3")))
# v4.0.2 exposes an operator-controlled resource mode in the live Search Console.
# SEARCH dedicates the server to historical discovery and suspends playback/media
# staging. PLAYBACK freezes background/foreground media discovery. BALANCED keeps
# the normal behavior where search yields briefly to active playback. The setting
# lives on the persistent cloud data disk so app deployments do not reset it.
HISTORY_WORK_MODE_FILE = CACHE_DIR / "history_work_mode.json"
HISTORY_WORK_MODE_LOCK = threading.RLock()
HISTORY_WORK_MODES = ("search","balanced","playback")

def _load_history_work_mode():
    try:
        payload=json.loads(HISTORY_WORK_MODE_FILE.read_text(encoding="utf-8"))
        mode=str(payload.get("mode") or "balanced").lower()
        return mode if mode in HISTORY_WORK_MODES else "balanced"
    except Exception:
        return "balanced"

HISTORY_WORK_MODE_STATE = {"mode":_load_history_work_mode(),"updatedAt":0.0,"updatedBy":"startup"}

def _history_work_mode():
    with HISTORY_WORK_MODE_LOCK:
        return str(HISTORY_WORK_MODE_STATE.get("mode") or "balanced")

def _set_history_work_mode(mode, updated_by="ui"):
    mode=str(mode or "").strip().lower()
    if mode not in HISTORY_WORK_MODES:
        raise ValueError(f"Unsupported work mode: {mode}")
    now=time.time()
    with HISTORY_WORK_MODE_LOCK:
        HISTORY_WORK_MODE_STATE.update({"mode":mode,"updatedAt":now,"updatedBy":str(updated_by or "ui")[:80]})
        tmp=HISTORY_WORK_MODE_FILE.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(HISTORY_WORK_MODE_STATE,ensure_ascii=False),encoding='utf-8')
        tmp.replace(HISTORY_WORK_MODE_FILE)
    try: _history_console_log('server','INFO',f'work mode changed → {mode.upper()}')
    except Exception: pass
    return dict(HISTORY_WORK_MODE_STATE)

def _history_playback_suspended():
    return _history_work_mode()=="search"

def _history_search_suspended():
    return _history_work_mode()=="playback"
SERVER_STARTED_AT = time.time()
HISTORY_CONSOLE_LOCK = threading.RLock()
HISTORY_CONSOLE_LINES = deque(maxlen=320)
HISTORY_WORKER_HEALTH = {
    "green-gap":{"heartbeat":0.0,"phase":"starting","lastProgress":0.0,"iterations":0,"blocked":0,"current":""},
    "date-backfill":{"heartbeat":0.0,"phase":"starting","lastProgress":0.0,"iterations":0,"blocked":0,"current":""},
}

def _history_console_log(worker, level, message, **meta):
    row={"at":time.time(),"worker":str(worker or "history"),"level":str(level or "INFO").upper(),"message":str(message or "")[:900]}
    if meta: row["meta"]={str(k):v for k,v in meta.items()}
    with HISTORY_CONSOLE_LOCK: HISTORY_CONSOLE_LINES.append(row)
    if row["level"] in ("WARN","ERROR") or str(worker).startswith("green-gap"):
        print(f"[SBB {row['worker']}] {row['level']} {row['message']}",flush=True)

def _history_worker_beat(worker, phase=None, current=None, progress=False, blocked=False):
    now=time.time(); st=HISTORY_WORKER_HEALTH.setdefault(worker,{})
    st["heartbeat"]=now
    if phase is not None: st["phase"]=str(phase)
    if current is not None: st["current"]=str(current)
    if progress: st["lastProgress"]=now
    st["iterations"]=int(st.get("iterations") or 0)+1
    if blocked: st["blocked"]=int(st.get("blocked") or 0)+1

def _history_threads_status():
    names={t.name:bool(t.is_alive()) for t in threading.enumerate()}
    expected=("sbb-history-backfill","sbb-history-green-gap")
    return [{"name":name,"alive":bool(names.get(name))} for name in expected]
HISTORY_SCORE_FETCH_LOCK = threading.RLock()
HISTORY_SCORE_FETCH_LOCKS = {}
# Browsing a past date is foreground work. Keep that focus server-side so today's
# aggressive prewarm/search jobs do not consume the same bandwidth or YouTube
# capacity while an interactive historical discovery/playback request is active.
HISTORY_FOCUS_LOCK = threading.RLock()
HISTORY_FOCUS_STATE = {"date":"","until":0.0,"lastTouch":0.0}
CLIENT_ACTIVITY_STATE = {"lastInteractive":time.time(),"lastMedia":time.time(),"lastPassive":time.time()}
HISTORY_IDLE_SECONDS = max(5,int(os.environ.get("SBB_HISTORY_IDLE_SECONDS","15")))
DIRECTOR_CACHE={}
DIRECTOR_CACHE_TTL=3600
RATE_LIMIT_STATE = {"limited": False, "since": 0, "remaining": None, "limit": None}
COVERAGE_STATE = {}
DISCOVERY_JOBS = {}
DISCOVERY_LOCK = threading.Lock()
EDITORIAL_CACHE = {"savedAt":0,"key":"","data":None,"error":""}

EDITORIAL_SNAPSHOT_FILE = CACHE_DIR / "editorial_key_info.json"
EDITORIAL_SNAPSHOT_LOCK = threading.Lock()
EDITORIAL_REFRESH_LOCK = threading.Lock()
EDITORIAL_REFRESH_STATE = {"refreshing":False,"lastQuick":0.0,"lastDeep":0.0,"lastError":""}
EDITORIAL_SNAPSHOT = {"savedAt":0.0,"data":[],"contextPrograms":[],"editorialMode":"rules","editorialModel":None,"editorialError":"","errors":[]}


MEDIA_PREWARM_FILE = CACHE_DIR / "media_prewarm_v221.json"
CLIENT_TZ_FILE = CACHE_DIR / "client_timezone.txt"
MEDIA_PREWARM_LOCK = threading.Lock()
MEDIA_PREWARM_STATE = {
    "startedAt":0.0,"lastRun":0.0,"refreshing":False,"lastError":"",
    "timezone":"","utcOffsetMinutes":None,"clientDate":"","clientClockSeenAt":0.0,
    "mlb":{},"leagues":{},"inventoryItems":0,"inventoryGames":0
}
MEDIA_PREWARM_LAST = {}

def _load_media_prewarm_state():
    try:
        payload=json.loads(MEDIA_PREWARM_FILE.read_text(encoding="utf-8"))
        if isinstance(payload,dict):
            MEDIA_PREWARM_STATE.update(payload)
    except Exception:
        pass
    try:
        tz=CLIENT_TZ_FILE.read_text(encoding="utf-8").strip()
        if tz: MEDIA_PREWARM_STATE["timezone"]=tz
    except Exception:
        pass

def _save_media_prewarm_state():
    try:
        MEDIA_PREWARM_FILE.write_text(json.dumps(MEDIA_PREWARM_STATE,ensure_ascii=False),encoding="utf-8")
    except Exception:
        pass

def _remember_client_timezone(value):
    value=str(value or "").strip()
    if not value or len(value)>80 or not re.match(r"^[A-Za-z0-9_+./:-]+$",value): return
    if MEDIA_PREWARM_STATE.get("timezone")==value: return
    MEDIA_PREWARM_STATE["timezone"]=value
    try: CLIENT_TZ_FILE.write_text(value,encoding="utf-8")
    except Exception: pass

def _clean_utc_offset_minutes(value):
    try:
        minutes=int(str(value).strip())
    except Exception:
        return None
    return minutes if -14*60 <= minutes <= 14*60 else None

def _remember_client_clock(timezone_value="",utc_offset_minutes=None,client_date=""):
    """Remember browser clock facts so Termux does not depend on optional tzdata."""
    before=(MEDIA_PREWARM_STATE.get("timezone"),MEDIA_PREWARM_STATE.get("utcOffsetMinutes"),MEDIA_PREWARM_STATE.get("clientDate"))
    _remember_client_timezone(timezone_value)
    minutes=_clean_utc_offset_minutes(utc_offset_minutes)
    if minutes is not None: MEDIA_PREWARM_STATE["utcOffsetMinutes"]=minutes
    date_text=str(client_date or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}",date_text): MEDIA_PREWARM_STATE["clientDate"]=date_text
    MEDIA_PREWARM_STATE["clientClockSeenAt"]=time.time()
    after=(MEDIA_PREWARM_STATE.get("timezone"),MEDIA_PREWARM_STATE.get("utcOffsetMinutes"),MEDIA_PREWARM_STATE.get("clientDate"))
    if after!=before: _save_media_prewarm_state()

def _client_zoneinfo(value="",utc_offset_minutes=None):
    """Viewer tzinfo with an offset fallback for Python builds that lack IANA tzdata."""
    name=str(value or MEDIA_PREWARM_STATE.get("timezone") or "").strip()
    if name in {"UTC","Etc/UTC","Etc/GMT","GMT","Z"}: return timezone.utc
    if name:
        try: return ZoneInfo(name)
        except Exception: pass
    minutes=_clean_utc_offset_minutes(utc_offset_minutes)
    if minutes is None: minutes=_clean_utc_offset_minutes(MEDIA_PREWARM_STATE.get("utcOffsetMinutes"))
    if minutes is not None:
        try: return timezone(timedelta(minutes=minutes))
        except Exception: pass
    try: return datetime.now().astimezone().tzinfo or timezone.utc
    except Exception: return timezone.utc

def _client_now(value="",utc_offset_minutes=None):
    return datetime.now(timezone.utc).astimezone(_client_zoneinfo(value,utc_offset_minutes))

def _client_date_iso(offset=0,value="",utc_offset_minutes=None):
    return (_client_now(value,utc_offset_minutes)+timedelta(days=offset)).date().isoformat()

def _date_iso(offset=0):
    # Background workers follow the remembered browser sports day too.
    return _client_date_iso(offset)

def _payload_rows_generic(payload):
    if isinstance(payload,list): return payload
    if not isinstance(payload,dict): return []
    for key in ("data","items","results","matches","events"):
        value=payload.get(key)
        if isinstance(value,list): return value
        if isinstance(value,dict):
            for subkey in ("data","items","results","matches","events"):
                sub=value.get(subkey)
                if isinstance(sub,list): return sub
    return []

def _replace_payload_rows(payload,rows):
    rows=list(rows or [])
    if isinstance(payload,list): return rows
    if not isinstance(payload,dict): return {"data":rows}
    out=dict(payload)
    for key in ("data","items","results","matches","events"):
        value=out.get(key)
        if isinstance(value,list): out[key]=rows; return out
        if isinstance(value,dict):
            for subkey in ("data","items","results","matches","events"):
                if isinstance(value.get(subkey),list):
                    nested=dict(value); nested[subkey]=rows; out[key]=nested; return out
    out["data"]=rows
    return out

def _match_state_text(row):
    row=row or {}; st=row.get("state") or {}
    if not isinstance(st,dict): st={}
    return " ".join(str(x or "") for x in (st.get("report"),st.get("description"),st.get("status"),row.get("status"))).strip()

def _match_is_final(row):
    return bool(re.search(r"final|finished|ended|complete",_match_state_text(row),re.I)) or bool((row or {}).get("completed"))

def _match_is_live(row):
    text=_match_state_text(row)
    return bool(re.search(r"live|progress|inning|top |bottom |bot |middle|delay|first half|second half|half time|extra time|penalties|break time|in play",text,re.I)) and not _match_is_final(row)

def _parse_match_start(row,tz_value=""):
    row=row or {}
    for key in ("date","startDate","startTime","scheduledAt","startAt","datetime"):
        raw=row.get(key)
        if raw in (None,""): continue
        try:
            if isinstance(raw,(int,float)) or (isinstance(raw,str) and raw.strip().isdigit() and len(raw.strip())>=10):
                num=float(raw)
                if num>10**12: num/=1000.0
                return datetime.fromtimestamp(num,tz=timezone.utc)
            text=str(raw).strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}",text): continue
            dt=datetime.fromisoformat(text.replace("Z","+00:00"))
            if dt.tzinfo is None: dt=dt.replace(tzinfo=_client_zoneinfo(tz_value))
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None

def _payload_has_transition_game(payload,tz_value=""):
    """Scheduled game close to/past kickoff: scoreboard status must refresh aggressively."""
    now=datetime.now(timezone.utc)
    for row in _payload_rows_generic(payload):
        if not isinstance(row,dict) or _match_is_live(row) or _match_is_final(row): continue
        start=_parse_match_start(row,tz_value)
        if start and -6*3600 <= (start-now).total_seconds() <= 10*60:
            return True
    return False

def _team_aliases(team):
    if not isinstance(team,dict): team={"name":team}
    vals=[]
    for key in ("abbreviation","abbr","shortName","displayName","name"):
        v=str(team.get(key) or "").strip().lower()
        if v: vals.append(re.sub(r"[^a-z0-9]","",v))
    return {v for v in vals if v}

def _match_team_aliases(row,side):
    row=row or {}
    team=row.get(f"{side}Team") or row.get(side) or {}
    return _team_aliases(team)

def _same_team_pair(a,b):
    aa,ah=_match_team_aliases(a,"away"),_match_team_aliases(a,"home")
    ba,bh=_match_team_aliases(b,"away"),_match_team_aliases(b,"home")
    return bool(aa & ba) and bool(ah & bh)

ESPN_LIVE_AUTH_CACHE={}
ESPN_LIVE_AUTH_LOCK=threading.Lock()

def _espn_live_authority(league,date,tz_value="",utc_offset_minutes=None):
    # The authoritative scoreboard is viewer-day scoped. Include the viewer offset
    # in the cache key so a late-night event cannot leak between calendar buckets
    # if the device timezone changes while the local server remains running.
    offset=_clean_utc_offset_minutes(utc_offset_minutes)
    key=(str(league).upper(),str(date),str(tz_value or ""),offset); now=time.time()
    with ESPN_LIVE_AUTH_LOCK: cached=ESPN_LIVE_AUTH_CACHE.get(key)
    if cached and now-float(cached.get("savedAt") or 0)<30:
        return list(cached.get("data") or [])
    rows=_espn_scoreboard(str(league).upper(),date,tz_value,offset)
    with ESPN_LIVE_AUTH_LOCK: ESPN_LIVE_AUTH_CACHE[key]={"savedAt":now,"data":rows}
    return rows

def _reconcile_scoreboard_authority(payload,sport_key,query_date,tz_value="",utc_offset_minutes=None):
    """Overlay fresh ESPN score/state onto Highlightly rows for live US leagues.

    Highlightly remains the media/discovery provider. ESPN is only an independent
    scoreboard authority, so stale scheduled snapshots cannot survive kickoff.
    """
    league={"nfl":"NFL","nba":"NBA","nhl":"NHL"}.get(str(sport_key).lower())
    if not league: return payload
    try: authority=_espn_live_authority(league,query_date,tz_value,utc_offset_minutes)
    except Exception as exc:
        print(f"[SBB scoreboard] ESPN authority unavailable {league} {query_date}: {type(exc).__name__}: {exc}",flush=True)
        return payload
    rows=[row for row in _payload_rows_generic(payload) if isinstance(row,dict)]
    if not authority:
        # Do not let a provider's broad NFL weekly envelope masquerade as a
        # day-scoped result just because ESPN was temporarily empty/unreachable.
        # Keep only rows whose own timestamp belongs to the requested viewer day.
        if league=="NFL":
            try: target=datetime.strptime(str(query_date),'%Y-%m-%d').date()
            except Exception: return payload
            scoped=[]
            for row in rows:
                raw=row.get('date') or row.get('startDate') or row.get('startTime') or row.get('scheduledAt') or row.get('startAt') or row.get('datetime')
                if raw and _event_on_viewer_date(raw,target,tz_value,utc_offset_minutes): scoped.append(row)
            return _replace_payload_rows(payload,scoped)
        return payload
    # ESPN defines the game inventory for the requested viewer day. Highlightly can
    # occasionally return a broader NFL weekly envelope for a historical date. If
    # those unscoped rows are allowed through, the client sees a non-empty "yesterday"
    # response and never asks the direct ESPN fallback, which can make the actual
    # Thursday games disappear. Build the result from the ESPN day inventory and
    # merge the matching Highlightly row only to preserve provider ids/metadata.
    merged=[]
    for auth in authority:
        if not isinstance(auth,dict): continue
        provider=next((row for row in rows if _same_team_pair(row,auth)),None)
        nxt=dict(provider or auth)
        for field,value in auth.items():
            if field in ("state","status","clock","period","completed","score","date","awayTeam","homeTeam") or field not in nxt:
                nxt[field]=value
        nxt["__sbbScoreAuthority"]="ESPN"
        nxt["espnEventId"]=str(auth.get("id") or auth.get("eventId") or auth.get("matchId") or "")
        merged.append(nxt)
    return _replace_payload_rows(payload,merged)

def _gamepk_from_item(item):
    return str(item.get("gamePk") or item.get("matchId") or item.get("eventId") or "")

def _mlb_inventory_summary(date):
    data,saved=read_stats_disk_cache(date,allow_stale=True)
    data=list(data or [])
    groups={}
    for item in data:
        gid=_gamepk_from_item(item)
        if gid: groups.setdefault(gid,[]).append(item)
    recaps=sum(1 for g in groups.values() if any(bool(x.get("overview")) for x in g))
    reels=sum(1 for g in groups.values() if not any(bool(x.get("overview")) for x in g) and any(x.get("programType")=="reel" or not x.get("overview") for x in g))
    return {"items":len(data),"games":len(groups),"recaps":recaps,"reels":reels,"savedAt":saved}

def _schedule_game_counts(date):
    try:
        sched=fetch_json(f"{MLB_STATS_BASE}/schedule?sportId=1&date={date}&hydrate=team",timeout=7)
        games=[]
        for block in sched.get("dates",[]): games.extend(block.get("games",[]))
        try: _index_mlb_gamepk_hints(games,date)
        except Exception: pass
        final=sum(1 for g in games if str(((g.get("status") or {}).get("abstractGameState") or "")).lower()=="final")
        live=sum(1 for g in games if str(((g.get("status") or {}).get("abstractGameState") or "")).lower()=="live")
        return games,final,live
    except Exception:
        return [],0,0

def _due(key,seconds):
    return time.time()-float(MEDIA_PREWARM_LAST.get(key) or 0)>=seconds

def _mark_due(key):
    MEDIA_PREWARM_LAST[key]=time.time()

def _payload_has_started_game(payload):
    """Conservative generic detector for Highlightly match payloads."""
    tokens=[]
    def walk(x,depth=0):
        if depth>7: return
        if isinstance(x,dict):
            for k,v in x.items():
                lk=str(k).lower()
                if lk in {"status","state","report","description","short","type","phase"} and isinstance(v,(str,int,float)):
                    tokens.append(str(v).lower())
                walk(v,depth+1)
        elif isinstance(x,list):
            for v in x[:150]: walk(v,depth+1)
    walk(payload)
    text=" ".join(tokens)
    return bool(re.search(r"\b(final|finished|complete|completed|live|in progress|in-progress|halftime|quarter|period|inning|overtime)\b",text))

def _soccer_diagnostic_snapshot(payload,sport_key):
    raw_rows,filtered,filtered_rows=_soccer_filter_stage(payload,sport_key)
    # "normalized" here means rows that survive the server's league parser and
    # still contain enough identity for the browser to render a matchup.
    normalized=[]
    for row in filtered_rows:
        if not isinstance(row,dict):
            continue
        home = row.get("homeTeam") or row.get("home") or {}
        away = row.get("awayTeam") or row.get("away") or {}
        home_name = home.get("name") if isinstance(home,dict) else str(home or "")
        away_name = away.get("name") if isinstance(away,dict) else str(away or "")
        if home_name or away_name or row.get("title") or row.get("name"):
            normalized.append(row)
    return {
        "rawCount":len(raw_rows),
        "filteredCount":len(filtered_rows),
        "normalizedCount":len(normalized),
        "sample":_soccer_sample(raw_rows[0]) if raw_rows else None,
        "filteredSample":_soccer_sample(filtered_rows[0]) if filtered_rows else None,
    }


def _highlightly_cache_name(sport_key,endpoint):
    return f"{sport_key}-{endpoint}-v2517" if sport_key in ("epl","mls") else f"{sport_key}-{endpoint}"

def _prewarm_highlightly_call(sport_key,endpoint,date,timezone_value="",force=False):
    key=read_key()
    if not key: return None
    cfg=SPORT_API[sport_key]
    flat={"date":date,"limit":"100" if endpoint=="matches" else "40"}
    if timezone_value: flat["timezone"]=timezone_value
    if endpoint=="matches": flat[cfg.get("matchParam","league")]=cfg["league"]
    else: flat[cfg.get("highlightParam","leagueName")]=cfg["league"]
    if sport_key in ("epl","mls"):
        flat.setdefault("leagueName",cfg["league"])
        flat.setdefault("countryCode",cfg.get("countryCode",""))
    cache_name=_highlightly_cache_name(sport_key,endpoint)
    cached,saved=read_cached(cache_name,flat)
    if cached is not None and not force:
        return cached
    limited_since=float(RATE_LIMIT_STATE.get("since") or 0)
    if RATE_LIMIT_STATE.get("limited") and limited_since and time.time()-limited_since < 15*60:
        return cached
    url=f'{cfg["base"]}{cfg["prefix"]}/{endpoint}?{urlencode(flat)}'
    req=Request(url,headers={"x-rapidapi-key":key,"Accept":"application/json","User-Agent":"SportsBigBoard/4.0.2"})
    try:
        with urlopen(req,timeout=15) as resp:
            data=json.loads(resp.read().decode("utf-8"))
            if sport_key in ("epl","mls"): data=_strict_soccer_rows(data,sport_key)
            RATE_LIMIT_STATE.update({"limited":False,"remaining":resp.headers.get("x-ratelimit-requests-remaining",""),"limit":resp.headers.get("x-ratelimit-requests-limit","")})
            write_cached(cache_name,flat,data)
            return data
    except HTTPError as exc:
        if exc.code==429: RATE_LIMIT_STATE.update({"limited":True,"since":time.time()})
        return cached
    except Exception:
        return cached

def _prewarm_mlb_date(date,today=False):
    """MLB adapter using the same game-state cadence policy as every sport."""
    games,final_count,live_count=_schedule_game_counts(date)
    inv=_mlb_inventory_summary(date)
    unresolved=max(0,final_count-int(inv.get("recaps",0)))
    # v2.2.2: cadence is based on event state, not league. Live/recently completed
    # coverage stays on the rapid five-minute loop; older resolved dates back off.
    if today and (live_count or unresolved): cadence=5*60
    elif today and final_count: cadence=15*60
    elif unresolved: cadence=15*60
    else: cadence=60*60
    key=f"mlb:{date}:coverage"
    if _due(key,cadence) and (final_count or live_count):
        ensure_stats_discovery(date,force=True)
        _mark_due(key)
    rapid_key=f"mlb:{date}:rapid"
    if today and (live_count or unresolved) and _due(rapid_key,5*60):
        try: normalized_rapid_highlights(date,force_refresh=True,force_clips=False)
        except Exception: pass
        _mark_due(rapid_key)
    inv=_mlb_inventory_summary(date)
    inv.update({"final":final_count,"live":live_count,"unresolved":max(0,final_count-int(inv.get("recaps",0)))})
    MEDIA_PREWARM_STATE["mlb"][date]=inv
    try:
        MEDIA_PREWARM_STATE.setdefault("gameCenters",{})[date]=prewarm_game_centers_for_games(games,date,today)
    except Exception as exc:
        MEDIA_PREWARM_STATE.setdefault("gameCenters",{})[date]={"error":f"{type(exc).__name__}: {exc}"}
    return inv

def _prewarm_other_league(league,sport_key,date,today=False):
    """Generic sport adapter with the same rapid cadence policy used by MLB."""
    tz=MEDIA_PREWARM_STATE.get("timezone") or ""
    # All leagues get the short cycle while today's events can change. Yesterday
    # stays on a 15-minute upgrade cycle so late recaps are found promptly too.
    match_cadence=5*60 if today else 15*60
    mk=f"{sport_key}:{date}:matches"
    matches=None
    if _due(mk,match_cadence):
        matches=_prewarm_highlightly_call(sport_key,"matches",date,tz,force=True)
        _mark_due(mk)
    else:
        cfg=SPORT_API[sport_key]
        flat={"date":date,"limit":"100"}
        if tz: flat["timezone"]=tz
        flat[cfg.get("matchParam","league")]=cfg["league"]
        if sport_key in ("epl","mls"): flat.update({"leagueName":cfg["league"],"countryCode":cfg.get("countryCode","")})
        matches,_=read_cached(_highlightly_cache_name(sport_key,"matches"),flat)
    started=_payload_has_started_game(matches) if matches is not None else False
    hi_cadence=5*60 if today else 15*60
    hk=f"{sport_key}:{date}:highlights"
    if started and _due(hk,hi_cadence):
        _prewarm_highlightly_call(sport_key,"highlights",date,tz,force=True)
        _mark_due(hk)
    MEDIA_PREWARM_STATE["leagues"].setdefault(league,{})[date]={"started":started,"lastChecked":time.time(),"cadenceSeconds":hi_cadence}

GAME_CENTER_COVERAGE_LOCK=threading.RLock()
GAME_CENTER_COVERAGE_STATE={"running":False,"lastRun":0.0,"lastError":"","days":{}}


def _game_center_coverage_pass(today=None,yesterday=None):
    """Inventory and queue every supported Game Center for the viewer's two-day window.

    This is deliberately broader than click prewarming. Every known event for today
    and yesterday gets an authoritative provider id and a repository preparation job.
    Completed yesterday games therefore become local SQLite snapshots even when the
    user never clicked them during the prior session.
    """
    today=str(today or _date_iso(0))[:10]; yesterday=str(yesterday or _date_iso(-1))[:10]
    results={}
    with GAME_CENTER_COVERAGE_LOCK:
        GAME_CENTER_COVERAGE_STATE["running"]=True
    try:
        for date,is_today in ((today,True),(yesterday,False)):
            # Build the rich-provider event index first. Score-provider ids are joined
            # to this verified inventory afterward, so coverage is deterministic rather
            # than depending on which network request happened to finish first.
            games,_,_=_schedule_game_counts(date)
            results[f"MLB:{date}:official"]=prewarm_game_centers_for_games(games,date,is_today)
            for competition in ("NFL","NBA","NHL","MLS","EPL"):
                try: results[f"{competition}:{date}:official"]=prewarm_espn_game_centers(competition,date,is_today)
                except Exception as exc: results[f"{competition}:{date}:official"]={"error":f"{type(exc).__name__}: {exc}"}
            # Highlightly is playback/Game-Center infrastructure, not historical
            # search inventory. SEARCH mode preserves its quota for later playback.
            if _history_work_mode()!='search':
                for competition,sport_key in (("MLB","mlb"),("NFL","nfl"),("NBA","nba"),("NHL","nhl"),("MLS","mls"),("EPL","epl")):
                    try:
                        payload=_prewarm_highlightly_call(sport_key,"matches",date,MEDIA_PREWARM_STATE.get("timezone") or "",force=False)
                        rows=(payload.get("data") if isinstance(payload,dict) else payload) or []
                        results[f"{competition}:{date}:highlightly"]=prewarm_game_centers_for_events(competition,rows,date,is_today,provider_hint="highlightly")
                    except Exception as exc: results[f"{competition}:{date}:highlightly"]={"error":f"{type(exc).__name__}: {exc}"}
            else:
                results[f"HIGHLIGHTLY:{date}"]={"skipped":"SEARCH_MODE_QUOTA_RESERVE"}
        with GAME_CENTER_COVERAGE_LOCK:
            GAME_CENTER_COVERAGE_STATE.update({"lastRun":time.time(),"lastError":"","days":results})
        MEDIA_PREWARM_STATE["gameCenters"]=results
        return results
    except Exception as exc:
        with GAME_CENTER_COVERAGE_LOCK:
            GAME_CENTER_COVERAGE_STATE.update({"lastRun":time.time(),"lastError":f"{type(exc).__name__}: {exc}"})
        raise
    finally:
        with GAME_CENTER_COVERAGE_LOCK:
            GAME_CENTER_COVERAGE_STATE["running"]=False


def _request_game_center_coverage(today=None,yesterday=None,force=False):
    today=str(today or _date_iso(0))[:10]; yesterday=str(yesterday or _date_iso(-1))[:10]
    with GAME_CENTER_COVERAGE_LOCK:
        if GAME_CENTER_COVERAGE_STATE.get("running"): return False
        last=float(GAME_CENTER_COVERAGE_STATE.get("lastRun") or 0)
        if not force and time.time()-last<30: return False
        GAME_CENTER_COVERAGE_STATE["running"]=True
    def run():
        # _game_center_coverage_pass owns the state; clear the optimistic flag first.
        with GAME_CENTER_COVERAGE_LOCK: GAME_CENTER_COVERAGE_STATE["running"]=False
        try: _game_center_coverage_pass(today,yesterday)
        except Exception as exc: print(f"[SBB game-center] coverage warning: {type(exc).__name__}: {exc}",flush=True)
    threading.Thread(target=run,daemon=True,name="sbb-game-center-coverage-pass").start()
    return True


def game_center_coverage_worker():
    """Continuously close holes in today/yesterday repository coverage."""
    time.sleep(35)
    while True:
        if _history_work_mode()=='search':
            time.sleep(60); continue
        try: _game_center_coverage_pass(_date_iso(0),_date_iso(-1))
        except Exception as exc: print(f"[SBB game-center] coverage worker warning: {type(exc).__name__}: {exc}",flush=True)
        time.sleep(60)

def game_center_startup_prewarm_worker():
    """Prime every supported today/yesterday Game Center independently of clicks."""
    time.sleep(.75)
    if _history_work_mode()=='search': return
    try: _game_center_coverage_pass(_date_iso(0),_date_iso(-1))
    except Exception as exc: print(f"[SBB game-center] startup prewarm warning: {type(exc).__name__}: {exc}",flush=True)

def _touch_history_focus(date,seconds=90):
    date=str(date or '')[:10]
    if not re.match(r'^\d{4}-\d{2}-\d{2}$',date) or date>=_date_iso(0):
        return False
    now=time.time()
    with HISTORY_FOCUS_LOCK:
        HISTORY_FOCUS_STATE.update({'date':date,'until':max(float(HISTORY_FOCUS_STATE.get('until') or 0),now+max(15,int(seconds))),'lastTouch':now})
    return True

def _history_focus_snapshot():
    now=time.time()
    with HISTORY_FOCUS_LOCK:
        state=dict(HISTORY_FOCUS_STATE)
    state['active']=bool(state.get('date') and now<float(state.get('until') or 0))
    state['remainingSeconds']=max(0,int(float(state.get('until') or 0)-now)) if state['active'] else 0
    return state

def _history_focus_active():
    return bool(_history_focus_snapshot().get('active'))

def media_prewarm_worker():
    time.sleep(4)
    MEDIA_PREWARM_STATE["startedAt"]=time.time()
    while True:
        focus=_history_focus_snapshot()
        if focus.get('active'):
            MEDIA_PREWARM_STATE["refreshing"]=False
            MEDIA_PREWARM_STATE["pausedForHistory"]=focus.get('date') or ''
            time.sleep(5)
            continue
        try:
            MEDIA_PREWARM_STATE["refreshing"]=True
            MEDIA_PREWARM_STATE["pausedForHistory"]=''
            today=_date_iso(0); yesterday=_date_iso(-1)
            _prewarm_mlb_date(today,True)
            _prewarm_mlb_date(yesterday,False)
            # If the viewer moved into history while this cycle was already running,
            # stop before the bandwidth-heavy media staging / YouTube enrichment.
            if _history_focus_active():
                MEDIA_PREWARM_STATE["pausedForHistory"]=_history_focus_snapshot().get('date') or ''
                continue
            # Refresh Game Center event inventories on a slower cadence. The actual
            # live snapshots are refreshed by game_center_refresh_worker every 15s.
            for competition in ("NFL","NBA","NHL","MLS","EPL"):
                for gc_date,is_today in ((today,True),(yesterday,False)):
                    due_key=f"gc-inventory:{competition}:{gc_date}"
                    cadence=5*60 if is_today else 30*60
                    if _due(due_key,cadence):
                        try: prewarm_espn_game_centers(competition,gc_date,is_today)
                        except Exception: pass
                        _mark_due(due_key)
            if _history_focus_active():
                MEDIA_PREWARM_STATE["pausedForHistory"]=_history_focus_snapshot().get('date') or ''
                continue
            # v2.5.30: once MLB discovery has populated the persistent inventory,
            # proactively stage the exact primary native media with the server cache.
            # Browser score rendering will later reinforce the exact visible warm set.
            try:
                MEDIA_PREWARM_STATE["serverMedia"]={today:prewarm_server_media_for_date(today,18),yesterday:prewarm_server_media_for_date(yesterday,18)}
                _media_cache_cleanup()
            except Exception as exc:
                MEDIA_PREWARM_STATE["serverMediaError"]=f"{type(exc).__name__}: {exc}"
            if read_key() and _history_work_mode()!='search':
                for league,sport_key in (("NFL","nfl"),("NBA","nba"),("NHL","nhl")):
                    _prewarm_other_league(league,sport_key,today,True)
                    _prewarm_other_league(league,sport_key,yesterday,False)
            # Daily Top Plays is also prewarmed while Termux runs. Search is deliberately
            # much slower than live-game polling to preserve YouTube quota.
            if read_youtube_key():
                # Keep the verified MLS channel warm even with the browser closed so
                # live goals and post-match packages are already waiting on return.
                mls_today_due=_due(f"mls-official:{today}",5*60)
                if mls_today_due:
                    try: official_mls_youtube_videos(today,force_refresh=True)
                    except Exception: pass
                    _mark_due(f"mls-official:{today}")
                mls_yesterday_due=_due(f"mls-official:{yesterday}",15*60)
                if mls_yesterday_due:
                    try: official_mls_youtube_videos(yesterday,force_refresh=True)
                    except Exception: pass
                    _mark_due(f"mls-official:{yesterday}")
                tp_today=_daily_top_plays_results(today,force_refresh=_due(f"topplays:{today}",4*3600))
                if _due(f"topplays:{today}",4*3600): _mark_due(f"topplays:{today}")
                tp_yesterday=_daily_top_plays_results(yesterday,force_refresh=_due(f"topplays:{yesterday}",12*3600))
                if _due(f"topplays:{yesterday}",12*3600): _mark_due(f"topplays:{yesterday}")
                MEDIA_PREWARM_STATE["topPlays"]={today:len(tp_today),yesterday:len(tp_yesterday)}
            summaries=[_mlb_inventory_summary(today),_mlb_inventory_summary(yesterday)]
            MEDIA_PREWARM_STATE["inventoryItems"]=sum(int(x.get("items",0)) for x in summaries)
            MEDIA_PREWARM_STATE["inventoryGames"]=sum(int(x.get("games",0)) for x in summaries)
            MEDIA_PREWARM_STATE["lastRun"]=time.time()
            MEDIA_PREWARM_STATE["lastError"]=""
            _save_media_prewarm_state()
        except Exception as exc:
            MEDIA_PREWARM_STATE["lastError"]=f"{type(exc).__name__}: {exc}"
            print(f"[SBB media-prewarm] worker error: {MEDIA_PREWARM_STATE['lastError']}",flush=True)
        finally:
            MEDIA_PREWARM_STATE["refreshing"]=False
        time.sleep(60)

_load_media_prewarm_state()

def _load_editorial_snapshot():
    """Load the newest useful editorial snapshot across release versions.

    The editorial desk is durable application data, not build-specific data.
    Older releases incorrectly changed the filename, making every upgrade cold
    start with an empty Key Info ticker.
    """
    global EDITORIAL_SNAPSHOT
    candidates=[
        EDITORIAL_SNAPSHOT_FILE,
        CACHE_DIR / "editorial_key_info_v2511.json",
        CACHE_DIR / "editorial_key_info_v2510.json",
        CACHE_DIR / "editorial_key_info_v220.json",
    ]
    best=None
    for path in candidates:
        try:
            payload=json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload,dict) or not isinstance(payload.get("data"),list):
                continue
            if not payload.get("data"):
                continue
            if best is None or float(payload.get("savedAt") or 0)>float(best.get("savedAt") or 0):
                best=payload
        except Exception:
            pass
    if best is not None:
        EDITORIAL_SNAPSHOT={**EDITORIAL_SNAPSHOT,**best}
        try:
            EDITORIAL_SNAPSHOT_FILE.write_text(json.dumps(EDITORIAL_SNAPSHOT,ensure_ascii=False),encoding="utf-8")
        except Exception:
            pass

def _write_editorial_snapshot(snapshot):
    try:
        EDITORIAL_SNAPSHOT_FILE.write_text(json.dumps(snapshot,ensure_ascii=False),encoding="utf-8")
    except Exception as exc:
        print(f"[SBB warm-cache] unable to persist editorial snapshot: {exc}",flush=True)

EDITORIAL_NOISE_PATTERNS=(
    "grading the ","grade the ","grades for ","winners and losers","winner and loser",
    "what the trade means","trade grades","trade grade","trade tracker","trade deadline tracker",
    "free agency tracker","offseason buzz","latest buzz","rumors","rumour","what we learned",
    "takeaways","reaction to ","reacts to ","analysis:","explained","why the ","how the ",
    "rankings","ranking ","power rankings","who won the trade","best fits","mock draft",
    "preview","predictions","bold predictions","stock up","stock down","report card",
)
def _is_editorial_article_noise(title):
    t=str(title or "").strip().lower()
    return any(p in t for p in EDITORIAL_NOISE_PATTERNS)

def _looks_like_concrete_transaction(title,category):
    t=str(title or "").strip().lower()
    cat=str(category or "").upper()
    if cat=="TRADE":
        concrete=(" traded "," trade ","acquire","acquired","send ","sends ","sent ","deal ","lands ","landed ")
        return any(x in f" {t} " for x in concrete) and not _is_editorial_article_noise(t)
    if cat=="SIGNING":
        concrete=("sign ","signs ","signed ","agrees ","agreed ","extension","contract")
        return any(x in t for x in concrete) and not _is_editorial_article_noise(t)
    return not _is_editorial_article_noise(t)


def _headline_context_programs(items, fallback_items=None):
    """Build six-item league boards from consequential concrete updates.

    Edited items lead. If the global 20-item ticker does not leave six for a
    league, fill from that league's larger raw source pool after the same strict
    factual/noise filters.
    """
    now=datetime.now(timezone.utc).isoformat()
    fallback_items=list(fallback_items or [])
    out=[]
    names={
        "MLB":"Around the MLB",
        "NFL":"Around the NFL",
        "NBA":"Around the NBA",
        "NHL":"Around the NHL",
        "EPL":"Around the Premier League",
        "MLS":"Around MLS",
    }
    category_bonus={
        "TRADE":10,"INJURY":9,"SIGNING":8,"RETIREMENT":7,"SUSPENSION":8,
        "RECORD":7,"PLAYOFF":10,"CHAMPIONSHIP":12,"BREAKING":11,
        "FIRING":8,"HIRING":7,"UPDATE":0,
    }
    off_topic={
        "NBA":("fiba qualifiers","fiba qualifier","national team","olympic qualifier"),
        "NFL":("college football","ncaa"),
        "MLB":("minor league roundup",),
    }
    def valid(row,lg):
        title=str(row.get("title") or "").strip()
        cat=str(row.get("eventType") or "UPDATE").upper()
        if not title or _ticker_article_noise(title,str(row.get("description") or "")):
            return False
        if cat in {"TRADE","SIGNING"} and not _looks_like_concrete_transaction(title,cat):
            return False
        low=title.lower()
        if any(x in low for x in off_topic.get(lg,())):
            return False
        return True
    def score(row):
        cat=str(row.get("eventType") or "UPDATE").upper()
        return (
            float(row.get("importance") or 0)+category_bonus.get(cat,0),
            str(row.get("publishedAt") or "")
        )

    for lg in ("MLB","NFL","NBA","NHL","EPL","MLS"):
        primary=[x for x in items if str(x.get("league") or "").upper()==lg and valid(x,lg)]
        fallback=[x for x in fallback_items if str(x.get("league") or "").upper()==lg and valid(x,lg)]
        combined=[*sorted(primary,key=score,reverse=True),*sorted(fallback,key=score,reverse=True)]
        chosen=[]; seen=set()
        for row in combined:
            title=str(row.get("title") or "").strip()
            norm=re.sub(r"[^a-z0-9]+"," ",title.lower()).strip()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            chosen.append({
                "title":title[:180],
                "category":str(row.get("eventType") or "UPDATE").upper(),
                "source":str(row.get("sourceLabel") or row.get("source") or "Official/ESPN")[:60],
                "publishedAt":str(row.get("publishedAt") or ""),
                "importance":float(row.get("importance") or 0),
            })
            if len(chosen)>=6:
                break
        if len(chosen)<2:
            continue
        bucket=int(time.time()//3600)
        out.append({
            "id":f"context:{lg}:{bucket}",
            "eventId":f"context:{lg}:{bucket}",
            "league":lg,
            "programType":"context",
            "eventType":"AROUND THE LEAGUE",
            "title":names[lg],
            "subtitle":"The most consequential updates around the league",
            "publishedAt":now,
            "importance":74,
            "verifiedPlayable":True,
            "durationSeconds":18,
            "contextItems":chosen,
            "sourceLabel":"Sports Big Board editorial desk",
            "editorialProvider":"OPENAI" if read_openai_key() else "RULES",
        })
    return out

def _merge_quick_editorial_delta(previous, raw_items):
    """Merge genuinely new source records into an existing deep-edited snapshot.

    The expensive OpenAI desk runs hourly. Five-minute quick passes only add new
    factual source records and keep the already-approved editorial wording/order.
    """
    previous=list(previous or [])
    raw_items=list(raw_items or [])
    seen_ids={str(x.get("id") or "") for x in previous}
    new_rows=[dict(x) for x in raw_items if str(x.get("id") or "") not in seen_ids]
    for row in new_rows:
        row["editorialProvider"]="RULES_DELTA"
    combined=[*new_rows,*previous]
    combined.sort(key=lambda x:(x.get("importance",0),x.get("publishedAt") or ""),reverse=True)
    deduped=[]; seen=set()
    for row in combined:
        norm=re.sub(r"[^a-z0-9]+"," ",str(row.get("title") or "").lower()).strip()
        if not norm or norm in seen:
            continue
        seen.add(norm); deduped.append(row)
    return deduped[:24]

def refresh_editorial_snapshot(deep=False):
    """Refresh the persistent Key Info snapshot.

    deep=True runs the OpenAI editorial desk. deep=False is a fast source delta
    that never blocks page startup on OpenAI.
    """
    global EDITORIAL_SNAPSHOT
    if not EDITORIAL_REFRESH_LOCK.acquire(blocking=False):
        return False
    EDITORIAL_REFRESH_STATE["refreshing"]=True
    try:
        leagues=["MLB","NFL","NBA","NHL","EPL","MLS"]
        raw=[]; errors=[]
        for league in leagues:
            try:
                raw.extend(_merge_event_news_and_video(league))
            except Exception as exc:
                errors.append({"league":league,"message":f"{type(exc).__name__}: {exc}"})
        raw.sort(key=lambda x:(x.get("importance",0),x.get("publishedAt") or ""),reverse=True)
        prior=dict(EDITORIAL_SNAPSHOT)
        if deep or not prior.get("data"):
            edited,mode,editor_error=editorialize_events_cached(raw[:40],ttl=0)
            EDITORIAL_REFRESH_STATE["lastDeep"]=time.time()
        else:
            edited=_merge_quick_editorial_delta(prior.get("data") or [],raw[:40])
            mode=prior.get("editorialMode") or ("openai" if read_openai_key() else "rules")
            editor_error=prior.get("editorialError") or ""
        snapshot={
            "savedAt":time.time(),
            "data":edited,
            "contextPrograms":_headline_context_programs(edited,raw),
            "editorialMode":mode,
            "editorialModel":OPENAI_MODEL if read_openai_key() else None,
            "editorialError":editor_error,
            "errors":errors,
        }
        with EDITORIAL_SNAPSHOT_LOCK:
            EDITORIAL_SNAPSHOT=snapshot
        _write_editorial_snapshot(snapshot)
        EDITORIAL_REFRESH_STATE["lastQuick"]=time.time()
        EDITORIAL_REFRESH_STATE["lastError"]=""
        print(f"[SBB warm-cache] {'deep' if deep else 'quick'} editorial refresh: {len(edited)} ticker items, {len(snapshot['contextPrograms'])} context cards",flush=True)
        return True
    except Exception as exc:
        EDITORIAL_REFRESH_STATE["lastError"]=f"{type(exc).__name__}: {exc}"
        print(f"[SBB warm-cache] refresh failed: {EDITORIAL_REFRESH_STATE['lastError']}",flush=True)
        return False
    finally:
        EDITORIAL_REFRESH_STATE["refreshing"]=False
        EDITORIAL_REFRESH_LOCK.release()

def trigger_editorial_refresh(deep=False):
    if EDITORIAL_REFRESH_STATE.get("refreshing"):
        return
    threading.Thread(target=refresh_editorial_snapshot,args=(deep,),daemon=True,name="sbb-editorial-refresh").start()

def editorial_background_worker():
    # Give the HTTP server a moment to bind before doing any network work.
    time.sleep(2)
    while True:
        try:
            age=time.time()-float(EDITORIAL_SNAPSHOT.get("savedAt") or 0)
            deep_age=time.time()-float(EDITORIAL_REFRESH_STATE.get("lastDeep") or 0)
            if not EDITORIAL_SNAPSHOT.get("data"):
                refresh_editorial_snapshot(deep=True)
            elif deep_age>=3600:
                refresh_editorial_snapshot(deep=True)
            elif age>=300:
                refresh_editorial_snapshot(deep=False)
        except Exception as exc:
            print(f"[SBB warm-cache] worker error: {exc}",flush=True)
        time.sleep(30)

_load_editorial_snapshot()



def coverage_state(date):
    return COVERAGE_STATE.setdefault(date, {
        "status":"IDLE","completed":0,"total":0,"searched":0,"found":0,
        "playable":0,"playableGames":0,"recapGames":0,"reelGames":0,
        "noSource":0,"missingGames":0,"sourceErrors":0,"sourceErrorGames":0,
        "degradedPlayableGames":0,"playbackFailures":0,
        "message":"Waiting to search","updatedAt":time.time(),"revision":0,
        "cacheLoaded":False,"cacheCount":0,"refreshing":False,
        "youtubeConfigured":False,"youtubeSearched":0,"youtubeFound":0,"youtubeErrors":0,"youtubeDone":False
    })

def update_coverage(date, **patch):
    st=coverage_state(date)
    st.update(patch)
    st["updatedAt"]=time.time()
    st["revision"]=int(st.get("revision",0))+1
    return st


def stats_disk_cache_path(date):
    return CACHE_DIR / f"mlb_stats_highlights_{date}.json"

def read_stats_disk_cache(date, allow_stale=True):
    path = stats_disk_cache_path(date)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        saved = float(payload.get("savedAt", 0))
        data = payload.get("data")
        today = _client_date_iso()
        ttl = 1800 if date == today else 21600
        if isinstance(data, list) and (allow_stale or time.time() - saved < ttl):
            return data, saved
    except Exception:
        pass
    return None, 0

def write_stats_disk_cache(date, data):
    try:
        stats_disk_cache_path(date).write_text(
            json.dumps({"savedAt": time.time(), "data": data}), encoding="utf-8"
        )
    except Exception:
        pass

def read_youtube_key():
    return get_secret("YOUTUBE_API_KEY",ROOT)

def read_openai_key():
    return get_secret("OPENAI_API_KEY",ROOT)



def openai_api_request(path, payload=None, method=None, timeout=20):
    """Server-side OpenAI request. The API key never reaches browser JavaScript."""
    key=read_openai_key()
    if not key:
        raise RuntimeError("OPENAI_NOT_CONFIGURED")
    method=method or ("POST" if payload is not None else "GET")
    body=None if payload is None else json.dumps(payload).encode("utf-8")
    headers={"Authorization":f"Bearer {key}","Content-Type":"application/json","User-Agent":"SportsBigBoard/4.0.2"}
    req=Request(f"{OPENAI_API_BASE}{path}",data=body,headers=headers,method=method)
    with urlopen(req,timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def verify_openai_key():
    try:
        openai_api_request("/models",timeout=12)
        return {"ok":True,"configured":True}
    except HTTPError as exc:
        try:
            detail=exc.read().decode("utf-8","ignore")[:700]
        except Exception:
            detail=str(exc)
        message=f"OpenAI HTTP {exc.code}"
        if exc.code == 401:
            message="OpenAI HTTP 401: saved API key rejected"
        elif exc.code == 429:
            message="OpenAI HTTP 429: quota or rate limit"
        return {"ok":False,"configured":True,"status":exc.code,"error":message,"detail":detail}
    except Exception as exc:
        return {"ok":False,"configured":bool(read_openai_key()),"error":f"{type(exc).__name__}: {exc}"}

def openai_output_text(response):
    # Responses API normally nests text under output[].content[], but tolerate
    # SDK/proxy variants that expose output_text directly or wrap text in a value.
    direct=response.get('output_text') if isinstance(response,dict) else None
    if isinstance(direct,str) and direct.strip(): return direct.strip()
    parts=[]
    for item in (response.get("output") or []) if isinstance(response,dict) else []:
        for content in item.get("content") or []:
            if content.get("type") not in ("output_text","text"): continue
            text=content.get("text")
            if isinstance(text,dict): text=text.get('value') or text.get('text')
            if text: parts.append(str(text))
    return "\n".join(parts).strip()


def _openai_json_object(text):
    raw=str(text or '').strip()
    if raw.startswith('```'):
        raw=re.sub(r'^```(?:json)?\s*','',raw,flags=re.I)
        raw=re.sub(r'\s*```$','',raw)
    try: return json.loads(raw or '{}')
    except Exception:
        start=raw.find('{'); end=raw.rfind('}')
        if start>=0 and end>start: return json.loads(raw[start:end+1])
        raise

def openai_editorial_smoke_test():
    payload={
        "model":OPENAI_MODEL,
        "input":"Reply with exactly: Sports Big Board editorial layer online.",
        "max_output_tokens":40
    }
    response=openai_api_request("/responses",payload=payload,timeout=25)
    return {"ok":True,"model":OPENAI_MODEL,"text":openai_output_text(response) or "OpenAI response received."}

def _editorial_key(items):
    return "|".join(f"{x.get('id','')}:{x.get('title','')}:{x.get('publishedAt','')}" for x in items[:24])

def _openai_editorial_batch(batch):
    """Editorialize one small batch with strict structured output.

    Keeping batches small prevents a long ticker response from being truncated.
    A malformed/incomplete batch is retried once with a larger output budget.
    """
    source=[]
    for x in batch:
        source.append({
            "id":str(x.get("id") or ""),
            "league":str(x.get("league") or "SPORT"),
            "title":str(x.get("title") or "")[:240],
            "description":str(x.get("description") or "")[:360],
            "eventType":str(x.get("eventType") or "UPDATE"),
            "importance":int(x.get("importance") or 0),
            "publishedAt":str(x.get("publishedAt") or ""),
            "source":str(x.get("sourceLabel") or x.get("source") or "")[:80],
        })

    schema={
      "type":"object","properties":{
        "items":{"type":"array","items":{"type":"object","properties":{
          "id":{"type":"string"},"keep":{"type":"boolean"},"importance":{"type":"integer"},
          "category":{"type":"string","enum":["TRADE","SIGNING","INJURY","COACHING","RETIREMENT","ROSTER","PRESEASON","RECORD","MILESTONE","PLAY","PERFORMANCE","UPSET","RESULT","UPDATE"]},
          "headline":{"type":"string"}
        },"required":["id","keep","importance","category","headline"],"additionalProperties":False}}
      },"required":["items"],"additionalProperties":False
    }

    prompt=(
      "You are the editorial desk for Sports Big Board, a fast sports highlight channel. "
      "Use ONLY the supplied source records and never add facts. Rank what a sports fan should know now. "
      "Keep factual, consequential or genuinely interesting items: breaking news, major results, spectacular/key plays, "
      "records and milestones, standout performances, playoff/standings implications, consequential injuries, trades/signings, "
      "coaching/roster news and meaningful preseason developments. "
      "Suppress true duplicates, generic roundup/list/rank/buzz articles, previews, reaction/quote/profile/opinion pieces, stale low-value items, rumors, betting/fantasy/podcast filler, and minor depth transactions. Prefer discrete happenings that answer what happened or what matters now. "
      "Do not over-prune. Most factual distinct records in this small batch should be kept. "
      "Rewrite kept headlines as concise ticker headlines, normally 6-16 words, preserving names, teams and factual meaning. "
      "Importance is 0-100. Return exactly the structured result requested.\n\nSOURCE RECORDS:\n"
      + json.dumps(source,ensure_ascii=False)
    )

    last_error=None
    for attempt,budget in enumerate((2600, 4200, 6200),start=1):
        payload={
          "model":OPENAI_MODEL,
          "input":prompt,
          "max_output_tokens":budget,
          "text":{"format":{"type":"json_schema","name":"sports_big_board_editorial","strict":True,"schema":schema}}
        }
        try:
            response=openai_api_request("/responses",payload=payload,timeout=55)
            text=openai_output_text(response)
        except Exception as exc:
            last_error=exc
            print(f"[SBB editorial] request retry {attempt}/3: {type(exc).__name__}: {exc}",flush=True)
            time.sleep(min(3,attempt))
            continue
        try:
            parsed=_openai_json_object(text)
            rows=parsed.get("items") or []
            if not isinstance(rows,list):
                raise ValueError("structured editorial result did not contain an items array")
            return rows
        except Exception as exc:
            last_error=exc
            status=str(response.get("status") or "")
            detail=response.get("incomplete_details") or {}
            print(f"[SBB editorial] batch parse retry status={status} detail={detail} error={type(exc).__name__}: {exc}",flush=True)

    raise RuntimeError(f"OpenAI response malformed after retry: {type(last_error).__name__}: {last_error}")


def _ticker_article_noise(title, description=""):
    text=f"{title} {description}".lower()
    if _is_editorial_article_noise(title):
        return True
    bad=[r"\bbuzz\b",r"\brank(?:ings?)?\b",r"who'?s no\.? 1",r"\bwhat .* had to say\b",r"\broom to grow\b",r"\brough patch\b",r"\bpreview\b",r"\broundup\b",r"\blatest .* updates\b",r"\bnews and more\b",r"\btraining camp\b",r"\bmailbag\b",r"\bpodcast\b",r"\bmock draft\b",r"\bpower rankings\b",r"\bwinners and losers\b",r"\bwhat we learned\b",r"\bgrading\b",r"\bgrade(?:s)?\b",r"\breaction\b",r"\bwhat .* means\b"]
    return any(re.search(p,text) for p in bad)

def _basic_factual_ticker_filter(items):
    """Final safety net for startup.

    Remove article/opinion-style headlines, but do not require every transaction
    to match one narrow grammar pattern. This preserves good injury, result,
    record and concrete transaction headlines when the editorial desk is warming.
    """
    out=[]
    seen=set()
    for x in items or []:
        title=str(x.get("title") or "").strip()
        if not title or _ticker_article_noise(title,str(x.get("description") or "")):
            continue
        norm=re.sub(r"[^a-z0-9]+"," ",title.lower()).strip()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(x)
    out.sort(key=lambda x:(x.get("importance",0),x.get("publishedAt") or ""),reverse=True)
    return out[:24]

def _bootstrap_key_info_from_caches():
    """Produce immediate Key Info without waiting on network/OpenAI.

    Uses persisted per-league official/ESPN/event discovery caches. A background
    refresh will replace this with the normal editorial desk output.
    """
    rows=[]
    for league in ("MLB","NFL","NBA","NHL","EPL","MLS"):
        try:
            cached=_read_event_news_cache(league,ttl=7*24*3600)
            if cached:
                rows.extend(cached)
        except Exception:
            pass
        try:
            vcached=read_event_cache(league,ttl=7*24*3600)
            if vcached:
                rows.extend(vcached)
        except Exception:
            pass
    return _basic_factual_ticker_filter(rows)


def _filter_ticker_items(items):
    strict=[]
    for x in items or []:
        title=str(x.get('title') or '')
        cat=str(x.get('eventType') or 'UPDATE').upper()
        if _ticker_article_noise(title,str(x.get('description') or '')): continue
        if cat in {'TRADE','SIGNING'} and not _looks_like_concrete_transaction(title,cat): continue
        strict.append(x)
    # If the strict grammar filter unexpectedly removes nearly everything,
    # keep the editorial-noise filter but relax transaction phrasing.
    if len(strict) < min(4, len(items or [])):
        return _basic_factual_ticker_filter(items)
    return strict

def openai_editorialize_events(items):
    """Rank, dedupe, categorize and shorten already-sourced sports headlines.

    OpenAI is editorial only; discovered source records remain the factual source
    of truth. Small batches keep structured output reliable on mobile networks.
    """
    if not read_openai_key() or not items:
        return items

    candidates=_filter_ticker_items(items[:50])[:40]
    decisions={}
    # Six-record batches keep structured Responses output well below the token
    # ceiling even when the model spends tokens reasoning before emitting JSON.
    for offset in range(0,len(candidates),6):
        batch=candidates[offset:offset+6]
        for d in _openai_editorial_batch(batch):
            did=str(d.get("id") or "")
            if did:
                decisions[did]=d

    out=[]
    used=set()
    for original in candidates:
        oid=str(original.get("id") or "")
        d=decisions.get(oid)
        if not d or not d.get("keep"):
            continue
        row=dict(original)
        row["importance"]=max(0,min(100,int(d.get("importance") or row.get("importance") or 0)))
        row["eventType"]=str(d.get("category") or row.get("eventType") or "UPDATE")
        row["originalTitle"]=row.get("title")
        row["title"]=str(d.get("headline") or row.get("title") or "").strip() or row.get("title")
        row["editorialProvider"]="OPENAI"
        row["editorialModel"]=OPENAI_MODEL
        out.append(row)
        used.add(oid)

    # OpenAI ranks/dedupes; it should not accidentally turn a healthy factual
    # source pool into a nearly empty ticker. Fill from deterministic ranking if
    # fewer than the desired minimum survive.
    desired_min=min(15,len(candidates)) if len(candidates)>=15 else min(8,len(candidates))
    if len(out)<desired_min:
        fallback=sorted(
            (x for x in candidates if str(x.get("id") or "") not in used),
            key=lambda x:(x.get("importance",0),x.get("publishedAt") or ""),
            reverse=True
        )
        for original in fallback:
            row=dict(original)
            row["editorialProvider"]="RULES_FILL"
            row["editorialModel"]=OPENAI_MODEL
            out.append(row)
            used.add(str(original.get("id") or ""))
            if len(out)>=desired_min:
                break

    # True duplicate headline cleanup after AI rewriting.
    deduped=[]
    seen_titles=set()
    for row in sorted(out,key=lambda x:(x.get("importance",0),x.get("publishedAt") or ""),reverse=True):
        norm=re.sub(r"[^a-z0-9]+"," ",str(row.get("title") or "").lower()).strip()
        if norm and norm in seen_titles:
            continue
        if norm:
            seen_titles.add(norm)
        deduped.append(row)

    return deduped[:20]

def editorialize_events_cached(items, ttl=600):
    if not read_openai_key(): return items, "rules", ""
    key=_editorial_key(items)
    if EDITORIAL_CACHE.get('data') is not None and EDITORIAL_CACHE.get('key')==key and time.time()-float(EDITORIAL_CACHE.get('savedAt') or 0)<ttl:
        return EDITORIAL_CACHE['data'],"openai",EDITORIAL_CACHE.get('error','')
    try:
        data=openai_editorialize_events(items)
        EDITORIAL_CACHE.update({"savedAt":time.time(),"key":key,"data":data,"error":""})
        return data,"openai",""
    except Exception as exc:
        err=f"{type(exc).__name__}: {exc}"
        print(f"[SBB editorial] OpenAI fallback to rules: {err}",flush=True)
        EDITORIAL_CACHE.update({"savedAt":time.time(),"key":key,"data":items,"error":err})
        return items,"rules-fallback",err

def youtube_cache_path(gamepk):
    return YOUTUBE_CACHE_DIR / f"mlb_{str(gamepk)}.json"

def read_youtube_cache(gamepk, ttl=86400):
    try:
        payload=json.loads(youtube_cache_path(gamepk).read_text(encoding="utf-8"))
        if time.time()-float(payload.get("savedAt",0)) <= ttl and isinstance(payload.get("data"),dict):
            return payload["data"]
    except Exception:
        pass
    return None

def write_youtube_cache(gamepk, data):
    try:
        youtube_cache_path(gamepk).write_text(json.dumps({"savedAt":time.time(),"data":data}),encoding="utf-8")
    except Exception:
        pass

def _iso8601_duration_seconds(value):
    if not value: return None
    m=re.match(r"^P(?:(?P<d>\d+)D)?T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?$",str(value))
    if not m: return None
    return int(m.group('d') or 0)*86400+int(m.group('h') or 0)*3600+int(m.group('m') or 0)*60+int(m.group('s') or 0)

def _team_search_tokens(name):
    text=str(name or '').lower()
    words=[w for w in re.findall(r"[a-z0-9]+",text) if w not in {'the','of','baseball','club'}]
    # City + nickname queries work well; matching leans most heavily on the nickname.
    return words[-2:] if len(words)>=2 else words

def _youtube_source_score(channel, away, home):
    ch=str(channel or '').lower()
    if ch.strip() in {'mlb','major league baseball'} or 'major league baseball' in ch: return 100
    team_words=set(_team_search_tokens(away)+_team_search_tokens(home))
    if any(len(w)>3 and w in ch for w in team_words): return 96
    if re.search(r"espn|fox sports|fs1|nbc sports|cbs sports|sportsnet|spectrum|sny|nesn|masn|yes network|marquee|fanduel sports|bally",ch): return 90
    # Local television/news coverage is allowed, but ranks below league/team/national sources.
    if re.search(r"\b(?:tv|news|sports|network|channel)\b",ch): return 78
    return 62

def _youtube_match_strength(title, desc, away, home):
    text=(str(title)+' '+str(desc)).lower()
    aw=_team_search_tokens(away); hm=_team_search_tokens(home)
    a=max([1 if t in text else 0 for t in aw] or [0])
    h=max([1 if t in text else 0 for t in hm] or [0])
    # Require evidence for both teams to avoid attaching generic/team-only videos to the wrong game.
    return 2 if a and h else 0


def _youtube_video_available_in_us(video_detail):
    """Return True only when YouTube metadata does not rule out US iframe playback.

    `status.embeddable` alone is not enough. NFL/other rights-managed packages can
    be technically embeddable while `contentDetails.regionRestriction` blocks the
    United States. Treat those as unavailable before they can paint a green ribbon.
    """
    vd=video_detail or {}
    status=vd.get('status') or {}
    if status.get('embeddable') is False: return False
    if str(status.get('privacyStatus') or '').lower()=='private': return False
    restriction=((vd.get('contentDetails') or {}).get('regionRestriction') or {})
    blocked={str(x).upper() for x in (restriction.get('blocked') or [])}
    allowed={str(x).upper() for x in (restriction.get('allowed') or [])}
    if 'US' in blocked: return False
    if allowed and 'US' not in allowed: return False
    return True


def _narrated_recap_confidence(title, desc, channel, duration):
    """Conservative metadata-only estimate that a recap is presenter/commentary led.

    Public video APIs do not tell us whether a clip contains narration. We only
    mark GOLD when title/source/duration strongly look like a produced recap or
    broadcaster game story. This can later be upgraded with transcript/audio
    classification when a legal/available transcript path exists.
    """
    text=f"{title} {desc}".lower(); ch=str(channel or '').lower(); dur=int(duration or 0)
    if not (60 <= dur <= 720): return 0.0
    if re.search(r'condensed game|full game highlights|extended highlights',text): return 0.0
    network=bool(re.search(r'espn|sportscenter|fox sports|fs1|nbc sports|cbs sports|sportsnet|mlb network|nfl network|nba tv|nhl network|spectrum|sny|nesn|masn|yes network|marquee|fanduel sports|bally',ch))
    produced=bool(re.search(r'game recap|postgame recap|postgame report|game story|breakdown|analysis|highlights (?:and|&) analysis|recap show|what happened|around the league|postgame|post-match|post match|presser|press conference|reaction',text))
    summary=bool(re.search(r'\b(win|wins|victory|defeat|beats?|rall(?:y|ies)|powers?|leads?|dominates?|stuns?|upsets?)\b',text))
    if network and produced: return 0.96
    if network and summary and re.search(r'\brecap\b',text): return 0.90
    if produced and ('official' in ch or network): return 0.88
    return 0.0

def _decorate_recap_tier(item):
    row=dict(item)
    duration=int(row.get('durationSeconds') or row.get('duration') or 0)
    conf=_narrated_recap_confidence(row.get('title'),row.get('description'),row.get('sourceLabel') or row.get('source'),duration)
    row['commentaryConfidence']=conf
    row['commentaryLikely']=conf>=0.85
    # v4.0.2: one server-side classifier owns Gold/Green/Purple/Blue.
    return annotate_media_tier(row)

def _youtube_game_result(game, date):
    """Search trusted/credible YouTube coverage only when MLB-native coverage is missing."""
    gamepk=str(game.get('gamePk') or '')
    cached=read_youtube_cache(gamepk)
    if cached is not None:

        return cached
    key=read_youtube_key()
    if not key:
        return {"items":[],"error":None,"gamePk":gamepk,"kind":"none","youtubeSkipped":"not-configured"}
    away_node=((game.get('teams') or {}).get('away') or {}); home_node=((game.get('teams') or {}).get('home') or {})
    away=(away_node.get('team') or {}).get('name') or 'Away'; home=(home_node.get('team') or {}).get('name') or 'Home'
    away_score=away_node.get('score'); home_score=home_node.get('score')
    try:
        d=datetime.strptime(date,'%Y-%m-%d').replace(tzinfo=timezone.utc)
        after=(d-timedelta(hours=6)).isoformat().replace('+00:00','Z')
        before=(d+timedelta(days=2,hours=12)).isoformat().replace('+00:00','Z')
        query=f'{away} {home} highlights'
        params={
            'part':'snippet','q':query,'type':'video','maxResults':'12','order':'relevance',
            'videoEmbeddable':'true','videoSyndicated':'true','safeSearch':'moderate',
            'regionCode':'US','relevanceLanguage':'en','publishedAfter':after,'publishedBefore':before,'key':key
        }
        search=youtube_fetch_json(f"{YOUTUBE_API_BASE}/search?{urlencode(params)}",timeout=10)
        search_items=search.get('items') or []
        ids=[str((x.get('id') or {}).get('videoId') or '') for x in search_items]
        ids=[x for x in ids if x]
        if not ids:
            out={"items":[],"error":None,"gamePk":gamepk,"kind":"none","youtubeSearched":True}
            write_youtube_cache(gamepk,out); return out
        details=youtube_fetch_json(f"{YOUTUBE_API_BASE}/videos?{urlencode({'part':'snippet,contentDetails,status,statistics','id':','.join(ids[:50]),'key':key})}",timeout=10)
        detail_by={str(x.get('id')):x for x in details.get('items') or []}
        candidates=[]
        for idx,sr in enumerate(search_items):
            vid=str((sr.get('id') or {}).get('videoId') or '')
            vd=detail_by.get(vid) or {}; sn=vd.get('snippet') or sr.get('snippet') or {}
            if vd and not _youtube_video_available_in_us(vd): continue
            title=str(sn.get('title') or '').strip(); desc=str(sn.get('description') or '').strip(); channel=str(sn.get('channelTitle') or '').strip()
            if _youtube_match_strength(title,desc,away,home)<2: continue
            dur=_iso8601_duration_seconds((vd.get('contentDetails') or {}).get('duration'))
            # Skip obvious studio/podcast chatter unless the title clearly promises game coverage.
            txt=(title+' '+desc).lower()
            overview=bool(re.search(r"full game highlights|game highlights|game recap|condensed game|game summary|game story|highlights and recap|postgame highlights",txt))
            opinion=bool(re.search(r"podcast|reaction|reacts|takeaways|talks about|press conference|interview|rumor",txt)) and not overview
            if opinion: continue
            chronology=_clip_chronology({'title':title,'description':desc},idx)
            source_score=_youtube_source_score(channel,away,home)
            views=int(((vd.get('statistics') or {}).get('viewCount') or 0))
            candidates.append({
                'id':f'yt-{vid}','youtubeId':vid,'gamePk':gamepk,'date':date,'away':away,'home':home,
                'awayScore':away_score,'homeScore':home_score,'title':title,'description':desc,'duration':dur,
                'overview':overview,'chronology':chronology,'importance':_clip_importance({},title,desc),
                'thumbnail':(((sn.get('thumbnails') or {}).get('high') or (sn.get('thumbnails') or {}).get('medium') or {}).get('url') or ''),
                'source':channel or 'YouTube','sourceLabel':channel or 'YouTube','sourceType':'youtube-search',
                'publishedAt':sn.get('publishedAt'),'sourceScore':source_score,'viewCount':views
            })
            candidates[-1]=_decorate_recap_tier(candidates[-1])
        overviews=[x for x in candidates if x['overview']]
        if overviews:
            def rank(x):
                dur=x.get('duration') or 0
                # 3–4 minute game-summary videos are full recaps and rank near the top.
                fit=78 if 180<=dur<=300 else 72 if 150<=dur<=360 else 58 if 120<=dur<=480 else 42 if 60<=dur<=600 else 22 if dur<=900 else 10
                text=x['title'].lower(); title=48 if 'full game highlights' in text else 45 if 'game highlights' in text else 38 if 'recap' in text else 30
                return x.get('sourceScore',0)+fit+title+min(12,int((x.get('viewCount') or 0)**0.20))
            best=max(overviews,key=rank); best['programType']='recap'; best['provider']='YOUTUBE'
            out={"items":[best],"error":None,"gamePk":gamepk,"kind":"recap","youtubeSearched":True,"candidateCount":len(candidates)}
            write_youtube_cache(gamepk,out); return out
        # Blue reels are only assembled when video titles expose real inning chronology.
        plays=[x for x in candidates if not x['overview'] and (x.get('chronology') or [1])[0]==0]
        reel=_select_chronological_reel(plays,min_clips=3,max_clips=7)
        if reel:
            for i,item in enumerate(reel):
                item['programType']='reel'; item['provider']='YOUTUBE'; item['overview']=False; item['reelIndex']=i+1; item['reelCount']=len(reel)
            out={"items":reel,"error":None,"gamePk":gamepk,"kind":"reel","youtubeSearched":True,"candidateCount":len(candidates)}
            write_youtube_cache(gamepk,out); return out
        out={"items":[],"error":None,"gamePk":gamepk,"kind":"none","youtubeSearched":True,"candidateCount":len(candidates)}
        write_youtube_cache(gamepk,out); return out
    except HTTPError as exc:
        try: detail=exc.read().decode('utf-8','ignore')[:400]
        except Exception: detail=str(exc)
        return {"items":[],"error":f"YouTube HTTP {exc.code}: {detail}","gamePk":gamepk,"kind":"error","youtubeSearched":True}
    except Exception as exc:
        return {"items":[],"error":f"{type(exc).__name__}: {exc}","gamePk":gamepk,"kind":"error","youtubeSearched":True}


def event_cache_path(league):
    return EVENT_CACHE_DIR / f"{str(league).lower()}_key_info.json"

def read_event_cache(league, ttl=14400):
    try:
        payload=json.loads(event_cache_path(league).read_text(encoding="utf-8"))
        if time.time()-float(payload.get("savedAt",0)) <= ttl and isinstance(payload.get("data"),list):
            return payload["data"]
    except Exception:
        pass
    return None

def write_event_cache(league, data):
    try:
        event_cache_path(league).write_text(json.dumps({"savedAt":time.time(),"data":data}),encoding="utf-8")
    except Exception:
        pass


def _event_news_cache_path(league):
    return EVENT_CACHE_DIR / f"{str(league).lower()}_official_news_v1912.json"

def _read_event_news_cache(league, ttl=900):
    try:
        payload=json.loads(_event_news_cache_path(league).read_text(encoding="utf-8"))
        if time.time()-float(payload.get("savedAt",0)) <= ttl and isinstance(payload.get("data"),list):
            return payload["data"]
    except Exception:
        pass
    return None

def _write_event_news_cache(league, data):
    try:
        _event_news_cache_path(league).write_text(json.dumps({"savedAt":time.time(),"data":data}),encoding="utf-8")
    except Exception:
        pass

def _clean_news_title(title):
    title=re.sub(r'\s+-\s+(?:MLB\.com|NFL\.com|NBA\.com|NHL\.com)$','',str(title or '').strip(),flags=re.I)
    return re.sub(r'\s+',' ',title).strip()

def _event_importance(text, etype, source_score=90):
    t=str(text or '').lower()
    score=source_score
    score += {'TRADE':26,'SIGNING':23,'INJURY':21,'COACHING':20,'RETIREMENT':18,'RECORD':19,'MILESTONE':18,'PERFORMANCE':17,'PLAY':16,'UPSET':16,'RESULT':14,'ROSTER':10,'PRESEASON':8,'UPDATE':7}.get(etype,6)
    # Favor language that usually indicates a material transaction rather than routine churn.
    if re.search(r'\b(blockbuster|star|all-star|pro bowl|mvp|record|season-ending|out for season|multi-year|extension|acquires?|trades? for)\b',t): score += 12
    if re.search(r'\b(minor league|practice squad|10-day|two-way|optioned|recalled|designated for assignment|waiver claim)\b',t): score -= 10
    return score

def _google_news_official_results(league):
    """Discover factual Key Info headlines independently of YouTube.

    Google News RSS is used only as a discovery index. Queries are restricted to the
    official league domains, and the returned source URL is preserved. This lets the
    ticker show important factual updates even when no video package exists yet.
    """
    league=str(league or '').upper()
    cached=_read_event_news_cache(league)
    if cached is not None: return cached
    domains={'MLB':'mlb.com','NFL':'nfl.com','NBA':'nba.com','NHL':'nhl.com','EPL':'premierleague.com','MLS':'mlssoccer.com'}
    domain=domains.get(league)
    if not domain: return []
    trusted_domains={domain}  # ESPN is ingested directly from ESPN RSS below; keep Google discovery league-official only
    terms='trade OR traded OR acquire OR acquired OR signs OR signed OR signing OR extension OR injury OR injured OR activated OR returns OR hired OR fired OR retires OR retirement OR released OR waived OR suspended OR preseason OR "training camp"'
    # Official league reporting remains the first preference, but trusted national
    # reporting fills gaps when the league homepage has not published a standalone item.
    site_clause=' OR '.join(f'site:{d}' for d in sorted(trusted_domains))
    query=f'({terms}) ({site_clause}) {league} when:5d'
    url='https://news.google.com/rss/search?'+urlencode({'q':query,'hl':'en-US','gl':'US','ceid':'US:en'})
    req=Request(url,headers={'Accept':'application/rss+xml, application/xml, text/xml, */*','User-Agent':'Mozilla/5.0 SportsBigBoard/4.0.2'})
    try:
        with urlopen(req,timeout=10) as resp: raw=resp.read()
        root=ET.fromstring(raw)
    except Exception as exc:
        print(f'[SBB key-info] {league} official news discovery failed: {type(exc).__name__}: {exc}',flush=True)
        return []
    now=datetime.now(timezone.utc)
    reject=re.compile(r'rumou?r|mock draft|fantasy|power rankings|prediction|odds|betting|podcast|mailbag|opinion|what if|could trade|might trade|should trade|free agency tracker|transaction tracker|trade tracker|every .*deal|all .*deal|all .*signing|complete list|grades|winners and losers|top \d+',re.I)
    out=[]
    for node in root.findall('.//item')[:40]:
        title=_clean_news_title(node.findtext('title') or '')
        if not title or reject.search(title): continue
        etype=_event_type(title)
        if not etype: continue
        source=node.find('source')
        source_name=(source.text or '').strip() if source is not None else f'{league}.com'
        source_url=(source.attrib.get('url') or '') if source is not None else ''
        link=str(node.findtext('link') or '').strip()
        # Keep discovery factual: accept the official league domain plus a short
        # list of national sports desks. Everything else is rejected here.
        src_lower=(source_url or link or '').lower()
        if src_lower and not any(d in src_lower for d in trusted_domains): continue
        pub_text=str(node.findtext('pubDate') or '').strip()
        try:
            pub=parsedate_to_datetime(pub_text)
            if pub.tzinfo is None: pub=pub.replace(tzinfo=timezone.utc)
            age_h=max(0,(now-pub.astimezone(timezone.utc)).total_seconds()/3600)
            published=pub.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
        except Exception:
            age_h=999; published=pub_text
        if age_h>168: continue
        importance=_event_importance(title,etype,100) - min(20,int(age_h/12))
        out.append({
            'id':f'news-{league.lower()}-{abs(hash((title,published)))%10**12}',
            'eventId':f'news-{abs(hash((title,published)))%10**12}',
            'league':league,'title':title,'subtitle':f'{etype.title()} • {source_name or league+".com"}',
            'description':title,'duration':0,'durationSeconds':0,'thumbnail':'',
            'source':source_name or f'{league}.com','sourceLabel':source_name or f'{league}.com','sourceType':'official-news',
            'sourceUrl':source_url or link,'articleUrl':link,'eventType':etype,'programType':'event-news',
            'provider':'OFFICIAL_NEWS','overview':False,'verifiedPlayable':False,'publishedAt':published,
            'importance':importance,'viewCount':0
        })
    out.sort(key=lambda x:(x.get('importance',0),x.get('publishedAt') or ''),reverse=True)
    # Headline-level dedupe, but retain multiple genuinely different events per league.
    selected=[]; seen=[]
    for item in out:
        tokens=set(w for w in re.sub(r'[^a-z0-9 ]+',' ',item['title'].lower()).split() if len(w)>3)
        if any(tokens and len(tokens & prior)/max(1,len(tokens|prior))>.62 for prior in seen): continue
        selected.append(item); seen.append(tokens)
        if len(selected)>=7: break
    _write_event_news_cache(league,selected)
    return selected


def _espn_rss_results(league):
    """First-party ESPN headline feed. ESPN explicitly publishes these RSS feeds for aggregators."""
    league=str(league or '').upper(); url=ESPN_RSS.get(league)
    if not url: return []
    req=Request(url,headers={'Accept':'application/rss+xml, application/xml, text/xml, */*','User-Agent':'Mozilla/5.0 SportsBigBoard/4.0.2'})
    try:
        with urlopen(req,timeout=8) as resp: raw=resp.read()
        root=ET.fromstring(raw)
    except Exception as exc:
        print(f'[SBB ESPN] {league} RSS failed: {type(exc).__name__}: {exc}',flush=True); return []
    now=datetime.now(timezone.utc); out=[]
    reject=re.compile(r'rumou?r|mock draft|fantasy|power rankings|prediction|odds|betting|podcast|mailbag|ranked|winners and losers|grades|tracker|every .*deal|complete list',re.I)
    for node in root.findall('.//item')[:45]:
        title=_clean_news_title(node.findtext('title') or '')
        if not title or reject.search(title): continue
        etype=_event_type(title)
        # ESPN is our broad factual wire. OpenAI ranks/dedupes downstream, so don't discard
        # a legitimate sports headline just because it does not match a hand-written keyword.
        notable=bool(re.search(r'\b(record|historic|milestone|career-high|suspend|brawl|returns?|out .*weeks?|season-ending|grand slam|walk-off|two homers?|three homers?|no-hitter|shutout|top play|game-winner|upset|stuns?|comeback|trade|sign|injur|fired|hired|retir|clinches?|sweeps?|rally|rallies|dominates?|erupts?|debut|first career|career best|playoff|standings)\b',title,re.I))
        if not etype: etype='UPDATE'
        link=str(node.findtext('link') or '').strip(); pub_text=str(node.findtext('pubDate') or '').strip()
        try:
            pub=parsedate_to_datetime(pub_text); pub=pub if pub.tzinfo else pub.replace(tzinfo=timezone.utc)
            age_h=max(0,(now-pub.astimezone(timezone.utc)).total_seconds()/3600); published=pub.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
        except Exception: age_h=999; published=pub_text
        if age_h>96: continue
        out.append({'id':f'espn-news-{league.lower()}-{abs(hash((title,published)))%10**12}','eventId':f'espn-{abs(hash((title,published)))%10**12}','league':league,'title':title,'subtitle':f'{etype.title()} • ESPN','description':str(node.findtext('description') or title),'duration':0,'durationSeconds':0,'thumbnail':'','source':'ESPN','sourceLabel':'ESPN','sourceType':'espn-rss','sourceUrl':link,'articleUrl':link,'eventType':etype,'programType':'event-news','provider':'ESPN','overview':False,'verifiedPlayable':False,'publishedAt':published,'importance':_event_importance(title,etype,96)-min(18,int(age_h/8)),'viewCount':0})
    return out


def _walk_json_objects(value):
    if isinstance(value,dict):
        yield value
        for v in value.values(): yield from _walk_json_objects(v)
    elif isinstance(value,list):
        for v in value: yield from _walk_json_objects(v)


def _espn_search_video_results(league, away='', home='', max_items=8):
    """Best-effort ESPN.com video discovery. ESPN search payloads vary, so extract media defensively."""
    q=' '.join(x for x in (away,home,league,'highlights') if x).strip()
    if not q: return []
    try: payload=fetch_json(ESPN_SEARCH_API+'?'+urlencode({'query':q,'limit':24}),timeout=8)
    except Exception as exc:
        print(f'[SBB ESPN] video search failed {q}: {type(exc).__name__}: {exc}',flush=True); return []
    out=[]; seen=set()
    for obj in _walk_json_objects(payload):
        title=str(obj.get('headline') or obj.get('title') or obj.get('name') or '').strip()
        if not title: continue
        low=title.lower(); both=(not away or away.lower().split()[-1] in low) and (not home or home.lower().split()[-1] in low)
        if away and home and not both: continue
        if not re.search(r'highlight|recap|home run|touchdown|goal|save|dunk|walk-off|game',low): continue
        urls=[]
        for k,v in obj.items():
            if isinstance(v,str) and v.startswith('http'):
                if re.search(r'\.(?:mp4|m3u8)(?:\?|$)',v,re.I): urls.append(v)
        media=urls[0] if urls else ''
        href=''
        links=obj.get('links')
        if isinstance(links,dict):
            for x in _walk_json_objects(links):
                for k in ('href','url'):
                    v=x.get(k)
                    if isinstance(v,str) and 'espn.com' in v: href=v; break
                if href: break
        href=href or str(obj.get('href') or obj.get('url') or '')
        sig=(title,media or href)
        if sig in seen: continue
        seen.add(sig)
        dur=duration_seconds(obj.get('duration') or obj.get('durationSeconds')) or 0
        overview=bool(re.search(r'game highlights|full game highlights|game recap|game summary',low)) or bool(dur and 120<=dur<=420 and re.search(r'\bwin|victory|beats?\b',low))
        if not media and not href: continue
        out.append({'id':f'espn-video-{abs(hash(sig))%10**12}','eventId':f'espn-video-{abs(hash(sig))%10**12}','league':league,'title':title,'description':str(obj.get('description') or obj.get('summary') or ''),'duration':dur,'durationSeconds':dur,'thumbnail':str(obj.get('image') or obj.get('thumbnail') or ''),'source':'ESPN','sourceLabel':'ESPN','sourceType':'espn-video','provider':'ESPN','verifiedPlayable':bool(media),'mediaUrl':media,'externalUrl':href,'articleUrl':href,'overview':overview,'programType':'recap' if overview else 'reel','importance':92 if overview else 75,'publishedAt':obj.get('published') or obj.get('publishedAt') or obj.get('date')})
        if len(out)>=max_items: break
    return out


def _espn_fetch_json(url,timeout=8):
    """Fetch ESPN JSON with browser-like headers.

    Some Android/Termux networks reject the lightweight custom User-Agent used by
    the rest of the local server even though the same public ESPN feed works in a
    browser. Keep ESPN transport isolated so changing these headers cannot affect
    Highlightly, MLB Stats, YouTube, or media proxy behavior.
    """
    req=Request(url,headers={
        "Accept":"application/json, text/plain, */*",
        "User-Agent":"Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36",
        "Referer":"https://www.espn.com/",
        "Origin":"https://www.espn.com"
    })
    with urlopen(req,timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))




def _espn_video_media_url(video):
    """Return the best directly playable ESPN source from a video object."""
    if not isinstance(video,dict): return ''
    links=video.get('links') or {}
    source=links.get('source') if isinstance(links,dict) else None
    def href(node):
        if isinstance(node,str) and node.startswith('http'): return node
        if isinstance(node,dict):
            v=node.get('href') or node.get('url')
            if isinstance(v,str) and v.startswith('http'): return v
        return ''
    if isinstance(source,dict):
        # v4.0.2: ESPN's mezzanine asset is frequently the largest/highest-
        # bitrate encode. It looked great but was a poor default for a localhost
        # streaming app on mobile and caused avoidable rebuffering. Prefer the
        # normal/full or HD delivery encode and keep mezzanine as a last MP4
        # resort. SD/mobile keys are accepted when ESPN exposes them.
        for key in ('full','SD','sd','mobile','HD','hd','mezzanine'):
            v=href(source.get(key))
            if v: return v
        direct=href(source)
        if direct: return direct
        v=href(source.get('HLS'))
        if v: return v
    # ESPN schemas move source links around. The recursive fallback is deliberately
    # restricted to actual media extensions so article URLs can never masquerade
    # as a playable asset.
    mp4=[]; hls=[]
    for obj in _walk_json_objects(video):
        for value in obj.values():
            if not isinstance(value,str) or not value.startswith('http'): continue
            if re.search(r'\.mp4(?:\?|$)',value,re.I): mp4.append(value)
            elif re.search(r'\.m3u8(?:\?|$)',value,re.I): hls.append(value)
    return (mp4 or hls or [''])[0]


def _espn_video_allowed_us(video):
    geo=(video or {}).get('geoRestrictions') or {}
    if not isinstance(geo,dict): return True
    countries={str(x).upper() for x in (geo.get('countries') or [])}
    mode=str(geo.get('type') or '').lower()
    if mode=='whitelist' and countries and 'US' not in countries: return False
    if mode=='blacklist' and 'US' in countries: return False
    return True


def _espn_event_video_results(event_id, league, away='', home='', max_items=16):
    """Fetch the video package attached to one known ESPN sporting event.

    This is intentionally event-id driven instead of search driven. For NFL the
    scoreboard already gives us ESPN's canonical event id, and ESPN exposes a
    game-specific video page for completed games. The summary payload commonly
    carries direct MP4/HLS sources, so this path neither spends YouTube quota nor
    depends on a fuzzy title search.
    """
    event_id=str(event_id or '').strip(); league=str(league or '').upper()
    cfg={'NFL':('football','nfl'),'NBA':('basketball','nba'),'NHL':('hockey','nhl'),'MLB':('baseball','mlb'),'EPL':('soccer','eng.1'),'MLS':('soccer','usa.1')}.get(league)
    if not event_id or not cfg: return []
    sport,slug=cfg
    url=f'{ESPN_SITE_API}/{sport}/{slug}/summary?'+urlencode({'event':event_id})
    try: payload=_espn_fetch_json(url,timeout=9)
    except Exception as exc:
        print(f'[SBB ESPN] event video summary failed {league} {event_id}: {type(exc).__name__}: {exc}',flush=True)
        return []
    candidates=[]; seen_nodes=set()
    # Explicit video arrays are preferred, but some ESPN payloads embed a video
    # object inside a play/highlight row. Walk both shapes defensively.
    for obj in _walk_json_objects(payload):
        if not isinstance(obj,dict): continue
        vid_list=obj.get('video')
        if isinstance(vid_list,list): candidates.extend(x for x in vid_list if isinstance(x,dict))
        if isinstance(obj.get('videos'),list): candidates.extend(x for x in obj.get('videos') if isinstance(x,dict))
        title=str(obj.get('headline') or obj.get('title') or '').strip()
        if title and isinstance(obj.get('links'),dict) and _espn_video_media_url(obj): candidates.append(obj)
    out=[]; seen=set()
    for idx,video in enumerate(candidates):
        ident=id(video)
        if ident in seen_nodes: continue
        seen_nodes.add(ident)
        if not _espn_video_allowed_us(video): continue
        media=_espn_video_media_url(video)
        if not media: continue
        title=str(video.get('headline') or video.get('title') or video.get('name') or f'{away} vs. {home} highlights').strip()
        desc=str(video.get('description') or video.get('caption') or '').strip()
        tracking=video.get('tracking') or {}
        coverage=str(tracking.get('coverageType') or '') if isinstance(tracking,dict) else ''
        text=f'{title} {desc} {coverage}'.lower()
        # Event-id authority already proves the matchup. Only reject obvious studio
        # content that can appear alongside a game package.
        if re.search(r'press conference|interview|preview|prediction|fantasy|betting|podcast',text,re.I): continue
        dur=duration_seconds(video.get('duration') or video.get('durationSeconds')) or 0
        overview=bool(re.search(r'full game highlights|game highlights|game recap|game summary|final game highlight',text,re.I))
        if not overview and dur>=90 and re.search(r'highlight|recap',text,re.I): overview=True
        thumb=str(video.get('thumbnail') or '')
        if not thumb:
            images=video.get('images') or []
            if isinstance(images,list) and images and isinstance(images[0],dict): thumb=str(images[0].get('url') or '')
        vid=str(video.get('id') or hashlib.sha1((title+media).encode()).hexdigest()[:14])
        sig=media
        if sig in seen: continue
        seen.add(sig)
        row={'id':f'espn-event-{event_id}-{vid}','eventId':event_id,'espnEventId':event_id,'league':league,
             'title':title,'description':desc or f'ESPN {league} game highlights','duration':dur,'durationSeconds':dur,
             'thumbnail':thumb,'source':'ESPN','sourceLabel':'ESPN','sourceType':'espn-event-video','provider':'ESPN',
             'verifiedPlayable':True,'embedValidated':True,'externalOnly':False,'mediaUrl':media,
             'externalUrl':f'https://www.espn.com/{slug if sport=="soccer" else league.lower()}/video/_/gameId/{event_id}',
             'overview':overview,'programType':'recap' if overview else 'reel','importance':98 if overview else 84,
             'rapid':True,'away':away,'home':home,'date':'','chronology':[1,999,0,idx,idx]}
        out.append(_decorate_recap_tier(row))
        if len(out)>=max_items: break
    return out


NFL_TEAM_SITE_HOSTS={
    'arizona cardinals':'www.azcardinals.com','atlanta falcons':'www.atlantafalcons.com','baltimore ravens':'www.baltimoreravens.com',
    'buffalo bills':'www.buffalobills.com','carolina panthers':'www.panthers.com','chicago bears':'www.chicagobears.com',
    'cincinnati bengals':'www.bengals.com','cleveland browns':'www.clevelandbrowns.com','dallas cowboys':'www.dallascowboys.com',
    'denver broncos':'www.denverbroncos.com','detroit lions':'www.detroitlions.com','green bay packers':'www.packers.com',
    'houston texans':'www.houstontexans.com','indianapolis colts':'www.colts.com','jacksonville jaguars':'www.jaguars.com',
    'kansas city chiefs':'www.chiefs.com','las vegas raiders':'www.raiders.com','los angeles chargers':'www.chargers.com',
    'los angeles rams':'www.therams.com','miami dolphins':'www.miamidolphins.com','minnesota vikings':'www.vikings.com',
    'new england patriots':'www.patriots.com','new orleans saints':'www.neworleanssaints.com','new york giants':'www.giants.com',
    'new york jets':'www.newyorkjets.com','philadelphia eagles':'www.philadelphiaeagles.com','pittsburgh steelers':'www.steelers.com',
    'san francisco 49ers':'www.49ers.com','seattle seahawks':'www.seahawks.com','tampa bay buccaneers':'www.buccaneers.com',
    'tennessee titans':'www.tennesseetitans.com','washington commanders':'www.commanders.com'
}

def _nfl_team_site_host(team):
    raw=re.sub(r'\s+',' ',str(team or '').strip().lower())
    if raw in NFL_TEAM_SITE_HOSTS: return NFL_TEAM_SITE_HOSTS[raw]
    # Provider display names occasionally drop the city. Nickname matching is
    # safe here because NFL nicknames are unique within this registry.
    for full,host in NFL_TEAM_SITE_HOSTS.items():
        if raw and (raw==full.split()[-1] or raw in full or full in raw): return host
    return ''


def _nfl_team_site_video_results(date, away, home, max_items=8):
    """Keyless first-party NFL club-site fallback.

    NFL club sites publish game highlight pages independently of YouTube iframe
    permissions. These rows guarantee that a discovered club recap remains visible
    as an official external fallback even when YouTube blocks embedding and ESPN's
    media transport is temporarily unavailable.
    """
    hosts=[]
    for team in (away,home):
        host=_nfl_team_site_host(team)
        if host and host not in hosts: hosts.append(host)
    out=[]; seen=set()
    for host in hosts:
        page=f'https://{host}/video/'
        try:
            req=Request(page,headers={'Accept':'text/html,application/xhtml+xml','User-Agent':'Mozilla/5.0 SportsBigBoard/4.0.2'})
            with urlopen(req,timeout=8) as resp: raw=resp.read().decode('utf-8','ignore')
        except Exception as exc:
            print(f'[SBB NFL] club video page failed {host}: {type(exc).__name__}: {exc}',flush=True); continue
        # Capture normal anchors plus bare /video/ URLs emitted in JSON hydration.
        hits=[]
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']*?/video/[^"\']+)["\'][^>]*>(.*?)</a>',raw,re.I|re.S):
            href=m.group(1); label=html.unescape(re.sub(r'<[^>]+>',' ',m.group(2) or ''))
            hits.append((href,re.sub(r'\s+',' ',label).strip()))
        for href in re.findall(r'["\'](\/video\/[a-zA-Z0-9_\-\/]+)["\']',raw): hits.append((href,''))
        for idx,(href,label) in enumerate(hits):
            url=urljoin(page,html.unescape(href)); slug=urlparse(url).path.rsplit('/video/',1)[-1].replace('-',' ')
            text=f'{label} {slug}'.strip()
            if _youtube_match_strength(text,'',away,home)<2: continue
            if not re.search(r'full game highlights|game highlights|highlights|recap|preseason week|week \d+',text,re.I): continue
            if re.search(r'preview|trailer|press|interview|practice|arrival|mic.?d',text,re.I): continue
            if url in seen: continue
            seen.add(url)
            title=label or re.sub(r'\s+',' ',slug).strip().title()
            full=bool(re.search(r'full game highlights|game highlights',text,re.I))
            row={'id':f'nfl-club-{hashlib.sha1(url.encode()).hexdigest()[:16]}','league':'NFL','title':title,
                 'description':f'Official {host.removeprefix("www.")} game highlights','duration':0,'durationSeconds':0,
                 'thumbnail':'','source':host.removeprefix('www.'),'sourceLabel':host.removeprefix('www.'),
                 'sourceType':'official-nfl-club-site','provider':'NFL_CLUB','verifiedPlayable':False,'embedValidated':False,
                 'externalOnly':True,'externalUrl':url,'overview':full,'programType':'recap' if full else 'reel',
                 'recapTier':'extended' if full else 'blue','importance':96 if full else 82,'rapid':True,
                 'queryDate':str(date)}
            out.append(_decorate_recap_tier(row))
            if len(out)>=max_items: return out
    return out

def _espn_event_rows(payload):
    """Collect ESPN event rows across Site API, CDN and multi-league envelopes.

    Earlier builds returned the *first* list that looked like ESPN events. That is
    fine for a league-specific scoreboard, but it is wrong for rescue transports
    such as soccer/all where several competition event lists can coexist in one
    payload. A first-list parser can therefore see another league, filter it out,
    and incorrectly conclude that EPL/MLS has no games. Collect and de-duplicate
    every event list instead.
    """
    def looks_like_events(value):
        if not isinstance(value,list) or not value: return False
        sample=[x for x in value[:8] if isinstance(x,dict)]
        return bool(sample) and any(('competitions' in x) or ('status' in x and ('date' in x or 'id' in x)) for x in sample)
    seen_nodes=set(); events=[]; event_keys=set()
    def add_event(ev):
        if not isinstance(ev,dict): return
        key=str(ev.get('id') or '')
        if not key:
            key=hashlib.sha1(json.dumps({'date':ev.get('date'),'name':ev.get('name'),'shortName':ev.get('shortName')},sort_keys=True,default=str).encode()).hexdigest()[:18]
        if key in event_keys: return
        event_keys.add(key); events.append(ev)
    def walk(value,depth=0):
        if depth>10: return
        ident=id(value)
        if ident in seen_nodes: return
        seen_nodes.add(ident)
        if isinstance(value,dict):
            direct=value.get('events')
            if looks_like_events(direct):
                for ev in direct: add_event(ev)
            # Continue walking even after finding events; generic ESPN envelopes
            # may hold more league blocks elsewhere in the same response.
            preferred=('content','sbData','scoreboard','gamepackageJSON','sports','leagues','data','children','items')
            walked=set()
            for key in preferred:
                if key in value and isinstance(value.get(key),(dict,list)):
                    walked.add(key); walk(value.get(key),depth+1)
            for key,child in value.items():
                if key in walked or key=='events': continue
                if isinstance(child,(dict,list)): walk(child,depth+1)
        elif isinstance(value,list):
            if looks_like_events(value):
                for ev in value: add_event(ev)
            for child in value[:250]:
                if isinstance(child,(dict,list)): walk(child,depth+1)
    walk(payload)
    return events


def _event_on_viewer_date(raw_date,target,tz_value="",utc_offset_minutes=None):
    """Classify an event by the viewer's calendar date, never its UTC date."""
    if not raw_date: return True
    try:
        dt=datetime.fromisoformat(str(raw_date).replace('Z','+00:00'))
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_client_zoneinfo(tz_value,utc_offset_minutes)).date()==target
    except Exception:
        return True


def _scoreboard_cache_path(league,date):
    safe=re.sub(r'[^A-Z0-9_-]+','_',str(league or '').upper())
    return SCOREBOARD_CACHE_DIR / f"v2644_{safe}_{date}.json"


def _read_scoreboard_cache(league,date):
    try:
        payload=json.loads(_scoreboard_cache_path(league,date).read_text(encoding='utf-8'))
        rows=payload.get('data')
        if not isinstance(rows,list) or not rows: return None,None
        return rows,max(0.0,time.time()-float(payload.get('savedAt') or 0))
    except Exception:
        return None,None


def _write_scoreboard_cache(league,date,rows):
    if not isinstance(rows,list) or not rows: return
    try:
        _scoreboard_cache_path(league,date).write_text(
            json.dumps({'savedAt':time.time(),'data':rows},ensure_ascii=False),encoding='utf-8')
    except Exception:
        pass


def _espn_generic_soccer_event_matches(ev,league_key):
    """Competition guard for soccer/all fallback rows.

    ESPN's league-specific soccer endpoint is preferred.  The all-soccer endpoint
    is only a rescue transport, so require positive competition evidence before a
    row is allowed into EPL/MLS.
    """
    if not isinstance(ev,dict): return False
    season=ev.get('season') or {}
    comp=((ev.get('competitions') or [{}])[0] or {})
    league=ev.get('league') or comp.get('league') or {}
    pieces=[
        season.get('slug') if isinstance(season,dict) else '',
        season.get('name') if isinstance(season,dict) else '',
        league.get('slug') if isinstance(league,dict) else league,
        league.get('name') if isinstance(league,dict) else '',
        league.get('abbreviation') if isinstance(league,dict) else '',
        league.get('uid') if isinstance(league,dict) else '',
        comp.get('leagueName'), comp.get('competitionName'), comp.get('tournament'),
        ev.get('leagueName'), ev.get('competition'), ev.get('tournament'), ev.get('uid')
    ]
    text=' '.join(str(x or '') for x in pieces).lower()
    if league_key=='EPL':
        return bool(re.search(r'\beng\.1\b|english[- ]premier[- ]league|\bpremier league\b',text))
    if league_key=='MLS':
        return bool(re.search(r'\busa\.1\b|major[- ]league[- ]soccer|\bmls\b',text))
    return False


def _espn_scoreboard(league,date,tz_value="",utc_offset_minutes=None):
    """Return one viewer-calendar day from a redundant ESPN transport set.

    v4.0.2 deliberately treats score/schedule identity as infrastructure rather
    than media metadata.  MLB still has MLB Stats as its main path in the browser;
    NFL/NBA/NHL/EPL/MLS use this function as a resilient independent authority.

    Important robustness rules:
      * query several ESPN transports in parallel and UNION matching events instead
        of trusting the first non-empty envelope;
      * NFL August requests also query the full preseason season type, because some
        date-scoped ESPN transports omit preseason games even though week queries
        contain them;
      * soccer has a guarded soccer/all rescue transport when eng.1 / usa.1 is empty;
      * every event is finally bucketed by the viewer's local calendar date;
      * a previously known non-empty day survives a temporary provider/network
        outage via the small persistent scoreboard cache.
    """
    league_key=str(league).upper()
    cfg={
        'NHL':('hockey','nhl'),
        'NFL':('football','nfl'),
        'NBA':('basketball','nba'),
        'MLB':('baseball','mlb'),
        'MLS':('soccer','usa.1'),
        'EPL':('soccer','eng.1')
    }.get(league_key)
    if not cfg: return []

    sport,slug=cfg
    target=datetime.strptime(str(date),'%Y-%m-%d').date()
    # A known non-empty schedule is more trustworthy than a transient empty API
    # response. Reuse recent rows briefly for today and much longer for a completed
    # historical day. This also prevents six redundant ESPN transports from being
    # re-hit every time the browser refreshes the same ribbon face.
    cached,cache_age=_read_scoreboard_cache(league_key,date)
    viewer_today=datetime.now(_client_zoneinfo(tz_value,utc_offset_minutes)).date()
    fresh_for=45 if target>=viewer_today else 12*3600
    if cached and cache_age is not None and cache_age<fresh_for:
        return cached
    if sport=='soccer' or league_key=='NFL':
        start_day=(target-timedelta(days=1)).strftime('%Y%m%d')
        end_day=(target+timedelta(days=1)).strftime('%Y%m%d')
        date_token=f'{start_day}-{end_day}'
    else:
        date_token=target.strftime('%Y%m%d')

    query=urlencode({'dates':date_token,'limit':100})
    specs=[
        (f'{ESPN_SITE_API}/{sport}/{slug}/scoreboard?{query}',False,'site-window'),
        (f'https://site.web.api.espn.com/apis/v2/sports/{sport}/{slug}/scoreboard?'+urlencode({'region':'us','lang':'en','contentorigin':'espn','isqualified':'true','dates':date_token,'limit':100}),False,'web-site-window'),
        (f'https://site.api.espn.com/apis/site/v2/sports/{sport}/{slug}/scoreboard?'+urlencode({'region':'us','lang':'en','dates':date_token,'limit':100}),False,'site-region-window'),
    ]
    # Range semantics differ across ESPN transports. Exact neighboring date reads
    # are cheap, keyless, and catch evening games stamped on the next UTC date.
    if sport=='soccer' or league_key=='NFL':
        for delta in (-1,0,1):
            exact=(target+timedelta(days=delta)).strftime('%Y%m%d')
            specs.append((f'{ESPN_SITE_API}/{sport}/{slug}/scoreboard?'+urlencode({'dates':exact,'limit':100}),False,f'site-exact-{delta:+d}'))
    if league_key in {'NFL','NBA','NHL','MLB'}:
        specs.append((f'https://cdn.espn.com/core/{league_key.lower()}/scoreboard?'+urlencode({'xhr':'1','limit':100}),False,'cdn'))
    elif sport=='soccer':
        specs.append(('https://cdn.espn.com/core/soccer/scoreboard?'+urlencode({'xhr':'1','limit':100,'league':slug}),False,'cdn'))

    # NFL preseason is the failure mode that exposed the architectural weakness.
    # Some date boards omit preseason while week boards contain it. Query every
    # preseason week for the target season and union the target viewer-day events.
    if league_key=='NFL' and target.month in (7,8):
        season_year=target.year
        specs.append((f'{ESPN_SITE_API}/football/nfl/scoreboard?'+urlencode({'dates':str(season_year),'seasontype':1,'limit':1000}),False,'preseason-season'))
        for week in range(1,6):
            specs.append((f'{ESPN_SITE_API}/football/nfl/scoreboard?'+urlencode({'dates':str(season_year),'seasontype':1,'week':week,'limit':100}),False,f'preseason-week-{week}'))

    if sport=='soccer':
        # A season-wide league-specific view is a second independent schedule
        # authority for fixtures that a day scoreboard temporarily omits.
        specs.append((f'{ESPN_SITE_API}/soccer/{slug}/scoreboard?'+urlencode({'dates':str(target.year),'limit':1000}),False,'soccer-season'))
        # soccer/all is last-resort only and is guarded by competition evidence.
        specs.append((f'{ESPN_SITE_API}/soccer/all/scoreboard?'+urlencode({'dates':date_token,'limit':1000}),True,'soccer-all'))

    successful_transports=0
    errors=[]
    merged={}

    def fetch_spec(spec):
        url,generic,label=spec
        return spec,_espn_fetch_json(url,timeout=8)

    with ThreadPoolExecutor(max_workers=min(6,len(specs))) as ex:
        futures=[ex.submit(fetch_spec,spec) for spec in specs]
        for fut in as_completed(futures):
            try:
                (url,generic,label),candidate=fut.result()
                successful_transports+=1
                rows=_espn_event_rows(candidate)
                for ev in rows:
                    if not isinstance(ev,dict): continue
                    if generic and not _espn_generic_soccer_event_matches(ev,league_key): continue
                    raw=str(ev.get('date') or '')
                    if raw and not _event_on_viewer_date(raw,target,tz_value,utc_offset_minutes): continue
                    eid=str(ev.get('id') or '')
                    if not eid:
                        eid=hashlib.sha1(json.dumps({'d':ev.get('date'),'n':ev.get('name'),'s':ev.get('shortName')},sort_keys=True).encode()).hexdigest()[:18]
                    # Prefer the richer envelope if two transports return the same id.
                    prev=merged.get(eid)
                    if prev is None or len(json.dumps(ev,default=str))>len(json.dumps(prev,default=str)):
                        merged[eid]=ev
            except Exception as exc:
                errors.append(f'{type(exc).__name__}: {exc}')

    events=list(merged.values())
    if not events:
        cached,age=_read_scoreboard_cache(league_key,date)
        if cached:
            print(f'[SBB scoreboard] {league_key} {date}: provider empty/error; using {len(cached)} cached rows ({int(age or 0)}s old)',flush=True)
            return cached
        if successful_transports:
            return []
        raise RuntimeError(' | '.join(errors[-6:]) or 'ESPN scoreboard unavailable')

    out=[]
    for ev in events:
        raw_event_date=str(ev.get('date') or '')
        if raw_event_date and not _event_on_viewer_date(raw_event_date,target,tz_value,utc_offset_minutes):
            continue
        comp=((ev.get('competitions') or [{}])[0] or {})
        teams={}
        for c in comp.get('competitors') or []:
            side=str(c.get('homeAway') or '').lower()
            t=c.get('team') or {}
            teams[side]={
                'id':t.get('id'),
                'name':t.get('displayName') or t.get('shortDisplayName') or t.get('name'),
                'abbreviation':t.get('abbreviation'),
                'logo':t.get('logo'),
                'score':c.get('score')
            }

        status_obj=ev.get('status') or {}
        st=status_obj.get('type') or {}
        state=str(st.get('state') or '')
        detail=str(st.get('shortDetail') or st.get('detail') or st.get('description') or '')
        display_clock=str(status_obj.get('displayClock') or '')
        period=status_obj.get('period')
        completed=bool(st.get('completed'))
        state_payload={'description':detail or state,'status':state,'completed':completed}
        if state.lower()=='in': state_payload['report']='LIVE'
        elif completed or state.lower()=='post': state_payload['report']='FINAL'
        if display_clock: state_payload['clock']=display_clock
        if period is not None: state_payload['period']=period

        out.append({
            'id':str(ev.get('id') or ''),'matchId':str(ev.get('id') or ''),'espnEventId':str(ev.get('id') or ''),'date':ev.get('date'),
            'name':ev.get('name') or ev.get('shortName') or '','shortName':ev.get('shortName') or '',
            'leagueName':'Premier League' if league_key=='EPL' else ('Major League Soccer' if league_key=='MLS' else league_key),
            'awayTeam':teams.get('away') or {},'homeTeam':teams.get('home') or {},
            'score':{'awayScore':(teams.get('away') or {}).get('score'),'homeScore':(teams.get('home') or {}).get('score')},
            'state':state_payload,'status':detail or state,'clock':display_clock,'period':period,
            'completed':completed,'__sbbLeague':league_key,'source':'ESPN'
        })
    # Deterministic ordering prevents transport completion order from shuffling the ribbon.
    out.sort(key=lambda x:(str(x.get('date') or ''),str(x.get('id') or '')))
    if out: _write_scoreboard_cache(league_key,date,out)
    try: HISTORY_REPOSITORY.put_scores(date,league_key,out)
    except Exception as exc: print(f'[SBB history] score persist warning {league_key} {date}: {type(exc).__name__}: {exc}',flush=True)
    return out

def _soccer_schedule_cache_path(league,date):
    return SOCCER_SCHEDULE_CACHE_DIR / f"v2520_{str(league).upper()}_{date}.json"

def _read_soccer_schedule_cache(league,date,max_age=None):
    try:
        payload=json.loads(_soccer_schedule_cache_path(league,date).read_text(encoding="utf-8"))
        rows=payload.get("data")
        if not isinstance(rows,list):
            return None,None,None
        age=max(0.0,time.time()-float(payload.get("savedAt") or 0))
        if max_age is not None and age>max_age:
            return None,None,None
        return rows,age,str(payload.get("source") or "CACHE")
    except Exception:
        return None,None,None

def _write_soccer_schedule_cache(league,date,rows,source):
    try:
        _soccer_schedule_cache_path(league,date).write_text(
            json.dumps({"savedAt":time.time(),"source":source,"data":rows},ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception:
        pass

def _highlightly_soccer_schedule(league,date):
    sk="epl" if str(league).upper()=="EPL" else "mls"
    cfg=SPORT_API[sk]
    params={"date":date,"leagueName":cfg["league"],"countryCode":cfg.get("countryCode",""),"limit":"100"}
    url=f"{cfg['base']}{cfg['prefix']}/matches?{urlencode(params)}"
    req=Request(url,headers={
        "x-rapidapi-key":read_key(),
        "x-rapidapi-host":cfg.get("rapidHost","football-highlights-api.p.rapidapi.com"),
        "Accept":"application/json",
        "User-Agent":"SportsBigBoard/4.0.2"
    })
    with urlopen(req,timeout=12) as resp:
        payload=json.loads(resp.read().decode("utf-8"))
    filtered=_strict_soccer_rows(payload,sk)
    return _soccer_payload_rows(filtered)

def _soccer_schedule_day(league,date,force=False,tz_value="",utc_offset_minutes=None):
    today=_client_date_iso(0,tz_value,utc_offset_minutes)
    live_day=(str(date)==today)
    ttl=120 if live_day else 12*3600

    rows,age,source=_read_soccer_schedule_cache(league,date,ttl)
    if rows is not None and not force:
        return {"data":rows,"source":source,"cache":"fresh","ageSeconds":int(age or 0)}

    stale_rows,stale_age,stale_source=_read_soccer_schedule_cache(league,date,None)

    # Schedule/score acquisition should not spend Highlightly quota when ESPN can
    # provide the same scoreboard. This is intentionally server-side and shared.
    try:
        espn=_espn_scoreboard(league,date,tz_value,utc_offset_minutes)
        if isinstance(espn,list) and espn:
            _write_soccer_schedule_cache(league,date,espn,"ESPN")
            return {"data":espn,"source":"ESPN","cache":"miss","ageSeconds":0}
    except Exception as exc:
        print(f"[SBB soccer] ESPN {league} {date}: {type(exc).__name__}: {exc}",flush=True)

    if time.time() >= float(SOCCER_PROVIDER_COOLDOWN.get("until") or 0):
        try:
            rows=_highlightly_soccer_schedule(league,date)
            if rows:
                _write_soccer_schedule_cache(league,date,rows,"HIGHLIGHTLY")
                return {"data":rows,"source":"HIGHLIGHTLY","cache":"miss","ageSeconds":0}
        except HTTPError as exc:
            if exc.code==429:
                SOCCER_PROVIDER_COOLDOWN.update({"until":time.time()+30*60,"reason":"HTTP 429"})
                print(f"[SBB soccer] Highlightly 429; entering 30-minute cooldown ({league} {date})",flush=True)
            else:
                print(f"[SBB soccer] Highlightly HTTP {exc.code} ({league} {date})",flush=True)
        except Exception as exc:
            print(f"[SBB soccer] Highlightly {league} {date}: {type(exc).__name__}: {exc}",flush=True)

    # Never replace known soccer data with a blank panel because a provider is down.
    if stale_rows is not None:
        return {"data":stale_rows,"source":stale_source,"cache":"stale","ageSeconds":int(stale_age or 0)}

    return {
        "data":[],
        "source":"UNAVAILABLE",
        "cache":"empty",
        "ageSeconds":None,
        "cooldownSeconds":max(0,int(float(SOCCER_PROVIDER_COOLDOWN.get("until") or 0)-time.time()))
    }

def _soccer_schedule_bundle(league,today,yesterday,tz_value="",utc_offset_minutes=None):
    today_result=_soccer_schedule_day(league,today,tz_value=tz_value,utc_offset_minutes=utc_offset_minutes)
    yesterday_result=_soccer_schedule_day(league,yesterday,tz_value=tz_value,utc_offset_minutes=utc_offset_minutes)
    print(
        f"[SBB soccer] {league} today={len(today_result.get('data') or [])} "
        f"{today_result.get('source')}/{today_result.get('cache')} • "
        f"yesterday={len(yesterday_result.get('data') or [])} "
        f"{yesterday_result.get('source')}/{yesterday_result.get('cache')}",
        flush=True
    )
    return {
        "ok":True,
        "league":str(league).upper(),
        "today":today_result,
        "yesterday":yesterday_result,
        "cooldownSeconds":max(0,int(float(SOCCER_PROVIDER_COOLDOWN.get("until") or 0)-time.time()))
    }


def _soccer_diagnostics():
    today=datetime.now().date().isoformat()
    yesterday=(datetime.now().date()-timedelta(days=1)).isoformat()
    out={}
    for lg in ("EPL","MLS"):
        league_out={"league":lg,"today":today,"yesterday":yesterday,"providers":{}}
        espn_counts={}; espn_err=None
        try:
            espn_counts["today"]=len(_espn_scoreboard(lg,today))
            espn_counts["yesterday"]=len(_espn_scoreboard(lg,yesterday))
        except Exception as exc:
            espn_err=f"{type(exc).__name__}: {exc}"
        league_out["providers"]["ESPN"]={
            "ok":espn_err is None,
            "events":espn_counts,
            "error":espn_err,
            "leagueCode":"eng.1" if lg=="EPL" else "usa.1",
        }

        hk_counts={}; hk_err=None
        try:
            sk="epl" if lg=="EPL" else "mls"
            cfg=SPORT_API[sk]
            for dname,d in (("today",today),("yesterday",yesterday)):
                params={"date":d,"leagueName":cfg["league"],"countryCode":cfg.get("countryCode",""),"limit":"100"}
                url=f"{cfg['base']}{cfg['prefix']}/matches?{urlencode(params)}"
                req=Request(url,headers={
                    "x-rapidapi-key":read_key(),
                    "x-rapidapi-host":cfg.get("rapidHost","football-highlights-api.p.rapidapi.com"),
                    "Accept":"application/json",
                    "User-Agent":"SportsBigBoard/4.0.2"
                })
                with urlopen(req,timeout=12) as resp:
                    payload=json.loads(resp.read().decode("utf-8"))
                rows=_strict_soccer_rows(payload,sk)
                data=(rows.get("data") if isinstance(rows,dict) else rows) or []
                hk_counts[dname]=len(data)
        except Exception as exc:
            hk_err=f"{type(exc).__name__}: {exc}"
        league_out["providers"]["Highlightly"]={
            "ok":hk_err is None,
            "events":hk_counts,
            "error":hk_err,
            "leagueName":"Premier League" if lg=="EPL" else "Major League Soccer",
        }
        out[lg]=league_out
    return out


def _merge_event_news_and_video(league):
    news=_google_news_official_results(league) + _espn_rss_results(league)
    try:
        can_video=bool(read_youtube_key()) and not _history_focus_active() and YOUTUBE_GATEWAY.operation_available('search')
        videos=_sports_event_results(league) if can_video else []
    except YouTubeRateLimited:
        videos=[]
    except Exception as exc:
        print(f'[SBB key-info] {league} video enrichment failed: {type(exc).__name__}: {exc}',flush=True)
        videos=[]
    # Keep factual headlines even without a video. If a strong video describes the same
    # event type/topic, attach it as optional playable enrichment rather than hiding the news.
    remaining=list(videos)
    merged=[]
    for item in news:
        ntokens=set(w for w in re.sub(r'[^a-z0-9 ]+',' ',item.get('title','').lower()).split() if len(w)>3)
        best=None; best_score=0
        for v in remaining:
            if v.get('eventType')!=item.get('eventType'): continue
            vtokens=set(w for w in re.sub(r'[^a-z0-9 ]+',' ',v.get('title','').lower()).split() if len(w)>3)
            overlap=len(ntokens & vtokens)/max(1,len(ntokens|vtokens))
            if overlap>best_score: best_score=overlap; best=v
        if best is not None and best_score>=.22:
            enriched=dict(item)
            enriched.update({k:best.get(k) for k in ('youtubeId','duration','durationSeconds','thumbnail','verifiedPlayable')})
            enriched['provider']='YOUTUBE'; enriched['videoSource']=best.get('sourceLabel') or best.get('source')
            enriched['programType']='event'
            merged.append(enriched)
            remaining.remove(best)
        else:
            merged.append(item)
    # Videos that are independently consequential remain eligible programming and ticker items.
    merged.extend(remaining[:5])
    merged.sort(key=lambda x:(x.get('importance',0),x.get('publishedAt') or ''),reverse=True)
    return merged

def _event_type(text):
    t=str(text or '').lower()
    if re.search(r'\b(trade|traded|acquire[sd]?|acquisition|deal sends|dealt to)\b',t): return 'TRADE'
    if re.search(r'\b(signs?|signed|signing|extension|contract extension|re-signs?|re-signed|agrees? to (?:terms|deal)|reaches? (?:a )?deal|inks? (?:a )?deal)\b',t): return 'SIGNING'
    if re.search(r'\b(injur(?:y|ed)|out for season|out .*weeks?|placed on .*list|injured reserve|\bIL\b|activated|returns? from injury|cleared to return)\b',t,re.I): return 'INJURY'
    if re.search(r'\b(fired|hired|head coach|manager named|coaching change|coach named)\b',t): return 'COACHING'
    if re.search(r'\b(retire[sd]?|retirement)\b',t): return 'RETIREMENT'
    if re.search(r'\b(preseason|training camp|spring training)\b',t): return 'PRESEASON'
    if re.search(r'\b(suspend(?:ed|sion)|waived|released|roster move|activated)\b',t): return 'ROSTER'
    if re.search(r'\b(record|record-setting|historic|history|first ever|most in .*history)\b',t): return 'RECORD'
    if re.search(r'\b(milestone|career-high|career high|\d{3,}th|\d{2,}th career)\b',t): return 'MILESTONE'
    if re.search(r'\b(grand slam|walk-off|walkoff|two homers?|three homers?|hat trick|game-winner|game winner|buzzer-beater|buzzer beater|rob(?:s|bed)? .*home run|spectacular catch|top play|crazy play|wild play)\b',t): return 'PLAY'
    if re.search(r'\b(dominates?|dominant|erupts?|scores? \d+|throws? \d+|strikes? out \d+|career-best|career best|leads? .*win|powers? .*win)\b',t): return 'PERFORMANCE'
    if re.search(r'\b(upset|stuns?|shocks?|rallies? past|comeback win)\b',t): return 'UPSET'
    if re.search(r'\b(wins?|beats?|defeats?|sweeps?|clinches?|eliminates?)\b',t): return 'RESULT'
    return ''

def _event_source_score(channel, league):
    ch=str(channel or '').lower()
    lg=str(league or '').lower()
    if lg and (ch==lg or ch.startswith(lg+' ') or f'{lg} ' in ch): return 100
    if re.search(r'major league baseball|national football league|national basketball association|national hockey league|major league soccer',ch): return 100
    if re.search(r'espn|fox sports|fs1|nbc sports|cbs sports|nfl network|nba tv|nhl network|mlb network|sportsnet|the athletic',ch): return 93
    if re.search(r'\b(?:news|sports|network|channel|television|tv)\b',ch): return 78
    if 'official' in ch: return 86
    return 64

def _sports_event_results(league):
    """Return concise, consequential sports-event videos for the Key Information lane.

    Search is intentionally broad but filtering is intentionally strict: no rumor/podcast
    chatter, and no generic opinion videos. Results are cached for four hours so this
    lane does not burn YouTube search quota during normal Sports Big Board operation.
    """
    league=str(league or '').upper()
    cached=read_event_cache(league)
    if cached is not None: return cached
    key=read_youtube_key()
    if not key: return []
    query_map={
        'MLB':'MLB highlights top plays record performance trade signing injury',
        'NFL':'NFL highlights top plays performance trade signing injury preseason',
        'NBA':'NBA highlights top plays performance record trade signing injury',
        'NHL':'NHL highlights top plays performance record trade signing injury',
        'EPL':'Premier League EPL highlights top plays goals signing injury',
        'MLS':'MLS Major League Soccer highlights top plays goals signing injury',
    }
    query=query_map.get(league,f'{league} trade signing news highlights')
    after=(datetime.now(timezone.utc)-timedelta(days=7)).replace(microsecond=0).isoformat().replace('+00:00','Z')
    params={'part':'snippet','q':query,'type':'video','maxResults':'18','order':'date','videoEmbeddable':'true','videoSyndicated':'true','safeSearch':'moderate','regionCode':'US','relevanceLanguage':'en','publishedAfter':after,'key':key}
    search=youtube_fetch_json(f"{YOUTUBE_API_BASE}/search?{urlencode(params)}",timeout=10)
    rows=search.get('items') or []
    ids=[str((x.get('id') or {}).get('videoId') or '') for x in rows]
    ids=[x for x in ids if x]
    if not ids:
        write_event_cache(league,[]); return []
    details=youtube_fetch_json(f"{YOUTUBE_API_BASE}/videos?{urlencode({'part':'snippet,contentDetails,status,statistics','id':','.join(ids[:50]),'key':key})}",timeout=10)
    detail_by={str(x.get('id')):x for x in details.get('items') or []}
    out=[]
    reject=re.compile(r'rumou?r|could trade|might trade|should trade|reaction|reacts|podcast|live stream|mailbag|hot take|debate|prediction|mock draft|fantasy',re.I)
    for sr in rows:
        vid=str((sr.get('id') or {}).get('videoId') or '')
        vd=detail_by.get(vid) or {}; sn=vd.get('snippet') or sr.get('snippet') or {}; status=vd.get('status') or {}
        if vd and not _youtube_video_available_in_us(vd): continue
        title=str(sn.get('title') or '').strip(); desc=str(sn.get('description') or '').strip(); text=title+' '+desc
        etype=_event_type(text)
        if not etype or reject.search(text): continue
        dur=_iso8601_duration_seconds((vd.get('contentDetails') or {}).get('duration')) or 0
        # Sports Big Board is video-first and concise. Avoid shorts that carry no context
        # and long studio/podcast segments that recreate cable-news filler.
        if dur and (dur < 25 or dur > 480): continue
        channel=str(sn.get('channelTitle') or '').strip(); source_score=_event_source_score(channel,league)
        views=int(((vd.get('statistics') or {}).get('viewCount') or 0))
        # Keep local/team-ish coverage possible, but require a little audience evidence
        # when the channel itself is not a known league/national/local-news source.
        if source_score < 75 and views < 5000: continue
        thumb=(((sn.get('thumbnails') or {}).get('high') or (sn.get('thumbnails') or {}).get('medium') or {}).get('url') or '')
        importance=source_score + (16 if etype in ('TRADE','SIGNING') else 12 if etype in ('INJURY','COACHING') else 8) + min(10,int(max(0,views)**0.18))
        out.append({'id':f'event-{league.lower()}-{vid}','eventId':vid,'youtubeId':vid,'league':league,'title':title,'subtitle':f'{etype.title()} • {channel or "Trusted source"}','description':desc,'duration':dur,'durationSeconds':dur,'thumbnail':thumb,'source':channel or 'YouTube','sourceLabel':channel or 'YouTube','sourceType':'youtube-event','eventType':etype,'programType':'event','provider':'YOUTUBE','overview':True,'verifiedPlayable':True,'publishedAt':sn.get('publishedAt'),'importance':importance,'viewCount':views})
    # Deduplicate near-identical headlines and prefer strongest/source-most-recent packages.
    out.sort(key=lambda x:(x.get('importance',0),x.get('publishedAt') or ''),reverse=True)
    selected=[]; seen=[]
    for item in out:
        norm=re.sub(r'[^a-z0-9 ]+',' ',item['title'].lower())
        tokens=set(w for w in norm.split() if len(w)>3)
        if any(tokens and len(tokens & prior)/max(1,len(tokens|prior))>.58 for prior in seen): continue
        selected.append(item); seen.append(tokens)
        if len(selected)>=5: break
    write_event_cache(league,selected)
    return selected



def _top_plays_cache_path(date):
    return TOP_PLAYS_CACHE_DIR / f"top_plays_v2519_{date}.json"

def _read_top_plays_cache(date, ttl):
    try:
        payload=json.loads(_top_plays_cache_path(date).read_text(encoding="utf-8"))
        if time.time()-float(payload.get("savedAt",0)) <= ttl and isinstance(payload.get("data"),list):
            return payload["data"]
    except Exception:
        pass
    return None

def _write_top_plays_cache(date,data):
    try:
        _top_plays_cache_path(date).write_text(json.dumps({"savedAt":time.time(),"data":data},ensure_ascii=False),encoding="utf-8")
    except Exception:
        pass

def _daily_top_plays_results(date, force_refresh=False):
    """Find one strong packaged Top Plays/Top 10 video for a sports day.

    The search is intentionally low-frequency because YouTube search is quota-heavy.
    ESPN/SportsCenter and official league/network channels are preferred. The client
    can synthesize a cross-sport mini-reel from individual clips when no package exists.
    """
    try: target=datetime.strptime(date,"%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception: return []
    today=datetime.now().astimezone().date().isoformat()
    ttl=4*3600 if date==today else 12*3600
    if not force_refresh:
        cached=_read_top_plays_cache(date,ttl)
        if cached is not None: return cached
    key=read_youtube_key()
    if not key: return []
    month=target.strftime("%B"); day=target.day; year=target.year
    query=f"top plays of the night {month} {day} {year} SportsCenter"
    params={
        'part':'snippet','q':query,'type':'video','maxResults':'25','order':'relevance',
        'videoEmbeddable':'true','videoSyndicated':'true','safeSearch':'moderate',
        'regionCode':'US','relevanceLanguage':'en',
        'publishedAfter':(target-timedelta(hours=8)).isoformat().replace('+00:00','Z'),
        'publishedBefore':(target+timedelta(days=2,hours=12)).isoformat().replace('+00:00','Z'),
        'key':key
    }
    try:
        search=youtube_fetch_json(f"{YOUTUBE_API_BASE}/search?{urlencode(params)}",timeout=12)
    except Exception as exc:
        if not isinstance(exc,YouTubeRateLimited):
            print(f"[SBB top-plays] search failed {date}: {type(exc).__name__}: {exc}",flush=True)
        return _read_top_plays_cache(date,30*24*3600) or []
    rows=search.get('items') or []
    ids=[str((x.get('id') or {}).get('videoId') or '') for x in rows]
    ids=[x for x in ids if x]
    if not ids:
        _write_top_plays_cache(date,[]); return []
    try:
        details=youtube_fetch_json(f"{YOUTUBE_API_BASE}/videos?{urlencode({'part':'snippet,contentDetails,status,statistics','id':','.join(ids[:50]),'key':key})}",timeout=10)
    except Exception:
        details={'items':[]}
    detail_by={str(x.get('id')):x for x in details.get('items') or []}
    trusted=re.compile(r'espn|sportscenter|mlb|major league baseball|nba|nfl|nhl|major league soccer|\bmls\b|fox sports|cbs sports|nbc sports|tnt sports|br sports',re.I)
    title_pat=re.compile(r'top\s*(?:10|ten)?\s*plays|plays of the (?:night|day)|best plays|top moments|best moments',re.I)
    candidates=[]
    for sr in rows:
        vid=str((sr.get('id') or {}).get('videoId') or '')
        vd=detail_by.get(vid) or {}; sn=vd.get('snippet') or sr.get('snippet') or {}; status=vd.get('status') or {}
        if vd and not _youtube_video_available_in_us(vd): continue
        title=str(sn.get('title') or '').strip(); channel=str(sn.get('channelTitle') or '').strip()
        low_title=title.lower()
        if re.search(r'lineup|starting lineup|projected lineup|preview|pregame|pre-game|analysis|breakdown|explains?|film study|mechanics|swing path|swing breakdown|animation|animated|visualization|simulation|what to know|odds|prediction|interview|press conference',low_title,re.I):
            continue
        if not title_pat.search(title): continue
        if not trusted.search(channel): continue
        dur=_iso8601_duration_seconds((vd.get('contentDetails') or {}).get('duration')) or 0
        if dur and not (60 <= dur <= 1200): continue
        published=str(sn.get('publishedAt') or '')
        try:
            pub=datetime.fromisoformat(published.replace('Z','+00:00'))
            if abs((pub-target).total_seconds()) > 60*3600: continue
        except Exception: pass
        views=int(((vd.get('statistics') or {}).get('viewCount') or 0))
        score=70
        if re.search(r'espn|sportscenter',channel,re.I): score+=24
        if re.search(r'top\s*10',title,re.I): score+=8
        if re.search(r'of the night|of the day',title,re.I): score+=5
        if views: score+=min(8,int(max(0,views)**0.18))
        thumb=(((sn.get('thumbnails') or {}).get('high') or (sn.get('thumbnails') or {}).get('medium') or {}).get('url') or '')
        candidates.append({
            'id':f'topplays-{date}-{vid}','eventId':f'topplays-{date}','youtubeId':vid,
            'league':'SPORTS','sport':'multi-sport','title':title,
            'subtitle':f'Daily Top Plays • {channel or "Trusted sports source"}',
            'description':str(sn.get('description') or ''),'duration':dur,'durationSeconds':dur,
            'thumbnail':thumb,'source':channel or 'YouTube','sourceLabel':channel or 'YouTube',
            'sourceType':'daily-top-plays','provider':'YOUTUBE','verifiedPlayable':True,
            'overview':False,'programType':'top-plays','eventType':'TOP PLAYS','importance':score,
            'publishedAt':published,'topPlaysDate':date,'viewCount':views
        })
    candidates.sort(key=lambda x:(x.get('importance',0),x.get('viewCount',0),x.get('publishedAt') or ''),reverse=True)
    # One packaged feature per date is enough; league-specific versions remain discoverable
    # elsewhere and generated fallback covers days without a national package.
    selected=candidates[:1]
    _write_top_plays_cache(date,selected)
    return selected

RAPID_CACHE_DIR = STATE_DIR / "cache" / "rapid"
RAPID_CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _rapid_cache_path(date):
    return RAPID_CACHE_DIR / f"mlb_rapid_v267_{date}.json"

def _read_rapid_cache(date, ttl=180):
    try:
        payload=json.loads(_rapid_cache_path(date).read_text(encoding="utf-8"))
        if time.time()-float(payload.get("savedAt",0)) <= ttl and isinstance(payload.get("data"),list):
            return payload["data"]
    except Exception:
        pass
    return None

def _write_rapid_cache(date, data):
    try:
        _rapid_cache_path(date).write_text(json.dumps({"savedAt":time.time(),"data":data}),encoding="utf-8")
    except Exception:
        pass

def _game_has_started(game):
    status=game.get('status') or {}
    abstract=str(status.get('abstractGameState') or '').lower()
    detailed=str(status.get('detailedState') or '').lower()
    return abstract in ('live','final') or any(x in detailed for x in ('in progress','final','game over','completed'))

def _official_team_youtube_clips(game, date, max_items=5):
    """Best-effort official/team/broadcast video discovery for a single MLB game.

    This is deliberately a fallback after MLB-native game content. Search is cached
    by gamePk by the existing YouTube cache and only accepts sources that look like
    MLB, one of the participating teams, or an established broadcaster/local desk.
    """
    key=read_youtube_key()
    if not key: return []
    if _history_focus_active() and str(date or '')[:10] >= _date_iso(-1): return []
    if not YOUTUBE_GATEWAY.operation_available('search'): return []
    gamepk=str(game.get('gamePk') or '')
    away_node=((game.get('teams') or {}).get('away') or {}); home_node=((game.get('teams') or {}).get('home') or {})
    away=(away_node.get('team') or {}).get('name') or 'Away'; home=(home_node.get('team') or {}).get('name') or 'Home'
    try:
        d=datetime.strptime(date,'%Y-%m-%d').replace(tzinfo=timezone.utc)
        base_params={'part':'snippet','type':'video','maxResults':'12','order':'date',
                'videoEmbeddable':'true','videoSyndicated':'true','safeSearch':'moderate','regionCode':'US',
                'relevanceLanguage':'en','publishedAfter':(d-timedelta(hours=4)).isoformat().replace('+00:00','Z'),
                'publishedBefore':(d+timedelta(days=2,hours=12)).isoformat().replace('+00:00','Z'),'key':key}
        rows=[]
        # Matchup search catches broadcast packages. Team-only searches catch the kind of
        # rapid official social/video posts clubs publish minutes after individual plays.
        for q in (f'{away} {home} highlights', f'{away} highlights', f'{home} highlights'):
            params=dict(base_params); params['q']=q
            search=youtube_fetch_json(f"{YOUTUBE_API_BASE}/search?{urlencode(params)}",timeout=10)
            rows.extend(search.get('items') or [])
        # de-dupe search results before the details call
        dedup=[]; seen_ids=set()
        for row in rows:
            vid=str((row.get('id') or {}).get('videoId') or '')
            if not vid or vid in seen_ids: continue
            seen_ids.add(vid); dedup.append(row)
        rows=dedup[:30]
        ids=[str((x.get('id') or {}).get('videoId') or '') for x in rows]
        ids=[x for x in ids if x]
        if not ids: return []
        details=youtube_fetch_json(f"{YOUTUBE_API_BASE}/videos?{urlencode({'part':'snippet,contentDetails,status,statistics','id':','.join(ids[:50]),'key':key})}",timeout=10)
        detail_by={str(x.get('id')):x for x in details.get('items') or []}
        out=[]
        for source_index,sr in enumerate(rows):
            vid=str((sr.get('id') or {}).get('videoId') or '')
            vd=detail_by.get(vid) or {}; sn=vd.get('snippet') or sr.get('snippet') or {}; status=vd.get('status') or {}
            if vd and not _youtube_video_available_in_us(vd): continue
            title=str(sn.get('title') or '').strip(); desc=str(sn.get('description') or '').strip(); channel=str(sn.get('channelTitle') or '').strip()
            match_strength=_youtube_match_strength(title,desc,away,home)
            source_score=_youtube_source_score(channel,away,home)
            dur=_iso8601_duration_seconds((vd.get('contentDetails') or {}).get('duration')) or 0
            if dur and (dur < 12 or dur > 480): continue
            text=(title+' '+desc).lower()
            if re.search(r'podcast|reaction|reacts|press conference|interview|rumou?r|preview|prediction|betting',text): continue
            overview=bool(re.search(r'full game highlights|game highlights|game recap|game summary|condensed game',text)) or bool(dur and 120<=dur<=420 and re.search(r'\b(win|wins|victory|defeat|beats|leads?)\b',text))
            # A full-game recap must identify BOTH clubs. The old one-team exception
            # was intended for individual official-team clips, but it also allowed a
            # White Sox-vs-Cubs full recap to be attached to Braves-vs-White Sox.
            # Keep the one-team exception only for moment clips/reel candidates.
            if overview and match_strength<2:
                continue
            if source_score>=95:
                team_tokens=_team_search_tokens(away)+_team_search_tokens(home)
                if not any(t in text for t in team_tokens if len(t)>3): continue
            elif match_strength<2:
                continue
            if source_score < 78: continue
            thumb=(((sn.get('thumbnails') or {}).get('high') or (sn.get('thumbnails') or {}).get('medium') or {}).get('url') or '')
            out.append({'id':f'rapid-yt-{gamepk}-{vid}','gamePk':gamepk,'date':date,'away':away,'home':home,
                        'title':title,'description':desc,'duration':dur,'overview':overview,
                        'chronology':[1,999,0,source_index,source_index],'importance':35 if not overview else 60,
                        'youtubeId':vid,'thumbnail':thumb,'source':channel or 'YouTube','sourceLabel':channel or 'YouTube',
                        'sourceType':'official-team-youtube','provider':'YOUTUBE','verifiedPlayable':True,
                        'programType':'recap' if overview else 'reel-candidate'})
            out[-1]=_decorate_recap_tier(out[-1])
        return out[:max_items]
    except YouTubeRateLimited:
        return []
    except Exception as exc:
        print(f'[SBB rapid] YouTube team-source search failed game={gamepk}: {type(exc).__name__}: {exc}',flush=True)
        return []


def _mls_official_cache_path(date):
    return RAPID_CACHE_DIR / f"mls_official_{date}.json"

def _read_mls_official_cache(date, ttl=180):
    try:
        payload=json.loads(_mls_official_cache_path(date).read_text(encoding="utf-8"))
        if time.time()-float(payload.get("savedAt",0)) <= ttl and isinstance(payload.get("data"),list):
            return payload["data"]
    except Exception:
        pass
    return None

def official_mls_youtube_videos(date, force_refresh=False):
    """Read recent video directly from the verified Major League Soccer channel.

    One channel-scoped search covers the whole matchday and is much cheaper/more
    reliable than running multiple generic searches for every live match. The
    browser attaches one-team rapid clips only when that club has a unique eligible
    match on the date; full-match packages normally contain both teams explicitly.
    """
    if not force_refresh:
        cached=_read_mls_official_cache(date,180 if date==_date_iso(0) else 1800)
        if cached is not None: return cached
    key=read_youtube_key()
    if not key: return []
    try:
        d=datetime.strptime(date,'%Y-%m-%d').replace(tzinfo=timezone.utc)
    except Exception:
        return []
    params={
        'part':'snippet','channelId':MLS_YOUTUBE_CHANNEL_ID,'type':'video','maxResults':'50','order':'date',
        'videoEmbeddable':'true','videoSyndicated':'true','safeSearch':'moderate','regionCode':'US','relevanceLanguage':'en',
        'publishedAfter':(d-timedelta(hours=7)).isoformat().replace('+00:00','Z'),
        'publishedBefore':(d+timedelta(days=2,hours=12)).isoformat().replace('+00:00','Z'),'key':key
    }
    try:
        search=youtube_fetch_json(f"{YOUTUBE_API_BASE}/search?{urlencode(params)}",timeout=12)
        rows=search.get('items') or []
        ids=[str((x.get('id') or {}).get('videoId') or '') for x in rows]; ids=[x for x in ids if x]
        if not ids:
            data=[]
        else:
            details=youtube_fetch_json(f"{YOUTUBE_API_BASE}/videos?{urlencode({'part':'snippet,contentDetails,status,statistics','id':','.join(ids[:50]),'key':key})}",timeout=10)
            by={str(x.get('id')):x for x in details.get('items') or []}
            positive=re.compile(r'full match highlights|match highlights|goal|golazo|scores?|equaliz|winner|brace|hat trick|save|assist|bicycle|volley|free kick|header|penalty|red card|clean finish|beauty|banger|stoppage|comeback|game winner|tiebreaker|top bins|rocket|cannon|strike',re.I)
            negative=re.compile(r'interview|talks?|off the ball|preview|podcast|press conference|reaction|reacts|training|behind the scenes|instant replay|power rankings|every goal from matchday',re.I)
            data=[]
            for idx,sr in enumerate(rows):
                vid=str((sr.get('id') or {}).get('videoId') or ''); vd=by.get(vid) or {}; sn=vd.get('snippet') or sr.get('snippet') or {}; status=vd.get('status') or {}
                if vd and not _youtube_video_available_in_us(vd): continue
                title=str(sn.get('title') or '').strip(); desc=str(sn.get('description') or '').strip(); text=f'{title} {desc}'
                if negative.search(text) or not positive.search(text): continue
                dur=_iso8601_duration_seconds((vd.get('contentDetails') or {}).get('duration')) or 0
                if dur and not (7 <= dur <= 1200): continue
                overview=bool(re.search(r'full match highlights|match highlights|match recap',text,re.I))
                thumb=(((sn.get('thumbnails') or {}).get('high') or (sn.get('thumbnails') or {}).get('medium') or {}).get('url') or '')
                views=int(((vd.get('statistics') or {}).get('viewCount') or 0))
                row={'id':f'mls-official-{vid}','eventId':vid,'youtubeId':vid,'league':'MLS','sport':'football','title':title,'description':desc,
                     'duration':dur,'durationSeconds':dur,'thumbnail':thumb,'source':'Major League Soccer','sourceLabel':'Major League Soccer','sourceType':'mls-official-youtube',
                     'provider':'YOUTUBE','verifiedPlayable':True,'overview':overview,'programType':'recap' if overview else 'reel','chronology':[1,999,0,idx,idx],
                     'importance':72 if overview else 58,'publishedAt':str(sn.get('publishedAt') or ''),'date':date,'rapid':True,'viewCount':views}
                data.append(_decorate_recap_tier(row))
            data.sort(key=lambda x:(x.get('overview',False),x.get('importance',0),x.get('publishedAt') or ''),reverse=True)
        try: _mls_official_cache_path(date).write_text(json.dumps({'savedAt':time.time(),'data':data[:40]},ensure_ascii=False),encoding='utf-8')
        except Exception: pass
        return data[:40]
    except Exception as exc:
        if not isinstance(exc,YouTubeRateLimited):
            print(f'[SBB MLS] official channel discovery failed {date}: {type(exc).__name__}: {exc}',flush=True)
        return _read_mls_official_cache(date,30*24*3600) or []

def _generic_rapid_cache_path(league, date, away, home):
    safe=re.sub(r'[^a-z0-9]+','-',f'{league}-{date}-{away}-{home}'.lower()).strip('-')[:140]
    # v4.0.2 bumps the namespace to flush historical empty/rate-limited results from older builds.
    return RAPID_CACHE_DIR / f"team_v290_{safe}.json"

def _official_nfl_feed_videos(date, away, home):
    """Discover recent official NFL YouTube uploads without a Data API key.

    YouTube exposes a small public Atom feed for each channel. The NFL feed is
    especially useful for completed preseason games because the official titles
    consistently contain both teams and a Week label, while the browser may not
    have a YouTube Data API key configured at all.
    """
    try:
        target=datetime.strptime(str(date),'%Y-%m-%d').date()
    except Exception:
        return []
    url=f"https://www.youtube.com/feeds/videos.xml?channel_id={NFL_YOUTUBE_CHANNEL_ID}"
    try:
        req=Request(url,headers={"Accept":"application/atom+xml,application/xml;q=0.9,*/*;q=0.8","User-Agent":"SportsBigBoard/4.0.2"})
        with urlopen(req,timeout=9) as resp:
            raw=resp.read()
        root=ET.fromstring(raw)
    except Exception as exc:
        print(f'[SBB NFL] official YouTube feed failed: {type(exc).__name__}: {exc}',flush=True)
        return []
    ns={
        'atom':'http://www.w3.org/2005/Atom',
        'yt':'http://www.youtube.com/xml/schemas/2015',
        'media':'http://search.yahoo.com/mrss/'
    }
    out=[]
    for idx,entry in enumerate(root.findall('atom:entry',ns)):
        title=str(entry.findtext('atom:title',default='',namespaces=ns) or '').strip()
        vid=str(entry.findtext('yt:videoId',default='',namespaces=ns) or '').strip()
        published=str(entry.findtext('atom:published',default='',namespaces=ns) or '').strip()
        if not title or not vid or _youtube_match_strength(title,'',away,home)<2:
            continue
        try:
            pub_date=datetime.fromisoformat(published.replace('Z','+00:00')).date()
            if abs((pub_date-target).days)>2:
                continue
        except Exception:
            pass
        low=title.lower()
        if not re.search(r'preseason|week\s*\d+|game highlights|highlights',low,re.I):
            continue
        thumb=''
        node=entry.find('media:group/media:thumbnail',ns)
        if node is not None:
            thumb=str(node.attrib.get('url') or '')
        if not thumb:
            thumb=f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg'
        row={
            'id':f'nfl-feed-{vid}','eventId':vid,'youtubeId':vid,'league':'NFL',
            'title':title,'description':'Official NFL game highlight package',
            'duration':0,'durationSeconds':0,'thumbnail':thumb,'source':'NFL',
            'sourceLabel':'NFL','sourceType':'official-nfl-youtube-feed','provider':'YOUTUBE',
            # The public feed proves the official package exists, but it does not
            # prove the owner permits third-party iframe playback. Keep it as an
            # honest external package until videos.list positively validates it.
            'verifiedPlayable':False,'embedValidated':False,'externalOnly':True,
            'overview':True,'programType':'recap',
            'externalUrl':f'https://www.youtube.com/watch?v={vid}',
            # The keyless Atom feed does not expose duration. The NFL's canonical
            # matchup + preseason-week uploads are the long game-highlight packages
            # (the current Week 2 examples are ~15 minutes), so treat an unknown
            # duration here as EXTENDED rather than incorrectly painting it green.
            'recapTier':'extended',
            'chronology':[1,999,0,idx,idx],'importance':92,'rapid':True,
            'away':away,'home':home,'date':str(date),'publishedAt':published
        }
        out.append(_decorate_recap_tier(row))

    # v4.0.2: the public channel feed proves that a video exists, not that the
    # owner permits iframe playback. When a YouTube Data API key is available,
    # validate feed candidates before they can outrank team/broadcast search
    # results. This prevents an official-but-non-embeddable NFL upload from
    # becoming a green ribbon recap that can never actually start.
    key=read_youtube_key()
    if key and out:
        try:
            ids=[str(x.get('youtubeId') or '') for x in out if x.get('youtubeId')]
            details=youtube_fetch_json(f"{YOUTUBE_API_BASE}/videos?{urlencode({'part':'status,contentDetails','id':','.join(ids[:50]),'key':key})}",timeout=10)
            detail_by={str(x.get('id') or ''):x for x in (details.get('items') or [])}
            checked=[]
            for row in out:
                vd=detail_by.get(str(row.get('youtubeId') or ''))
                row=dict(row)
                dur=_iso8601_duration_seconds(((vd or {}).get('contentDetails') or {}).get('duration')) or 0
                if dur:
                    row['duration']=dur
                    row['durationSeconds']=dur
                if vd is not None and _youtube_video_available_in_us(vd):
                    row['verifiedPlayable']=True
                    row['embedValidated']=True
                    row['externalOnly']=False
                else:
                    # Still surface the official package as an external EXT link,
                    # but never route an unvalidated/non-embeddable item through
                    # the in-app YouTube player.
                    row['verifiedPlayable']=False
                    row['embedValidated']=False
                    row['externalOnly']=True
                checked.append(row)
            out=checked
        except Exception as exc:
            # Rate limiting is exactly the moment when we *cannot* truthfully say
            # an official feed upload is embeddable. Keep it external-only rather
            # than optimistically painting an in-app play button that later fails.
            print(f'[SBB NFL] feed embed validation failed: {type(exc).__name__}: {exc}',flush=True)
            for row in out:
                row['verifiedPlayable']=False
                row['embedValidated']=False
                row['externalOnly']=True
    return out


def _yt_renderer_text(node):
    if isinstance(node,str): return node.strip()
    if not isinstance(node,dict): return ''
    if isinstance(node.get('simpleText'),str): return str(node.get('simpleText') or '').strip()
    runs=node.get('runs') or []
    if isinstance(runs,list):
        return ''.join(str(x.get('text') or '') for x in runs if isinstance(x,dict)).strip()
    return ''


def _youtube_html_video_renderers(query,max_results=24):
    """Discover public YouTube video ids without spending Data API search quota.

    Historical backfill used to call search.list repeatedly for every game. In
    YouTube's current granular quota model, search.list has its own default
    100-call daily bucket, so a multi-query idle crawl can exhaust historical
    search capacity long before a viewer opens an older NBA date. The
    normal YouTube results page already contains public videoRenderer metadata.
    We read only that public metadata, then validate actual iframe availability
    separately before a candidate is allowed into the in-app player.
    """
    query=str(query or '').strip()
    if not query: return []
    url='https://www.youtube.com/results?'+urlencode({'search_query':query})
    req=Request(url,headers={
        'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language':'en-US,en;q=0.9',
        'User-Agent':'Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36',
        'Cookie':'CONSENT=YES+cb.20210328-17-p0.en+FX+667'
    })
    try:
        with urlopen(req,timeout=10) as resp:
            text=resp.read(4_000_000).decode('utf-8','ignore')
    except Exception as exc:
        print(f'[SBB YouTube web] search failed {query}: {type(exc).__name__}: {exc}',flush=True)
        raise RuntimeError(f'YouTube web search unavailable: {type(exc).__name__}: {exc}') from exc

    def extract_object(start):
        brace=text.find('{',start)
        if brace<0: return None, start+1
        depth=0; in_string=False; escaped=False
        for i in range(brace,len(text)):
            ch=text[i]
            if in_string:
                if escaped: escaped=False
                elif ch=='\\': escaped=True
                elif ch=='"': in_string=False
                continue
            if ch=='"': in_string=True; continue
            if ch=='{': depth+=1
            elif ch=='}':
                depth-=1
                if depth==0:
                    raw=text[brace:i+1]
                    try: return json.loads(raw), i+1
                    except Exception: return None, i+1
        return None, len(text)

    out=[]; seen=set(); pos=0; needle='"videoRenderer":'
    while len(out)<max_results:
        idx=text.find(needle,pos)
        if idx<0: break
        obj,pos=extract_object(idx+len(needle))
        if not isinstance(obj,dict): continue
        vid=str(obj.get('videoId') or '').strip()
        if not vid or vid in seen: continue
        seen.add(vid)
        title=_yt_renderer_text(obj.get('title'))
        channel=_yt_renderer_text(obj.get('ownerText')) or _yt_renderer_text(obj.get('longBylineText')) or _yt_renderer_text(obj.get('shortBylineText'))
        duration_text=_yt_renderer_text(obj.get('lengthText'))
        description=' '.join(_yt_renderer_text(x) for x in (obj.get('detailedMetadataSnippets') or []) if isinstance(x,dict))
        thumb=''
        thumbs=((obj.get('thumbnail') or {}).get('thumbnails') or []) if isinstance(obj.get('thumbnail'),dict) else []
        if thumbs and isinstance(thumbs[-1],dict): thumb=str(thumbs[-1].get('url') or '')
        out.append({'videoId':vid,'title':html.unescape(title),'channelTitle':html.unescape(channel),
                    'durationSeconds':duration_seconds(duration_text) or 0,'description':html.unescape(description),
                    'thumbnail':thumb,'publishedText':_yt_renderer_text(obj.get('publishedTimeText'))})
    return out


def _youtube_oembed_probe(video_id,timeout=7):
    """Best-effort no-quota metadata probe for one public YouTube id.

    A successful oEmbed response proves that public metadata exists, but it does
    NOT prove iframe/embed permission. Historical assets remain catalog candidates
    until videos.list positively validates them or the runtime player reports PLAYING.
    """
    vid=str(video_id or '').strip()
    if not vid: return None
    url='https://www.youtube.com/oembed?'+urlencode({'url':f'https://www.youtube.com/watch?v={vid}','format':'json'})
    req=Request(url,headers={'Accept':'application/json','User-Agent':'Mozilla/5.0 SportsBigBoard/4.0.2'})
    try:
        with urlopen(req,timeout=timeout) as resp:
            if getattr(resp,'status',200)!=200: return None
            data=json.loads(resp.read().decode('utf-8','ignore'))
            return data if isinstance(data,dict) else None
    except HTTPError as exc:
        if exc.code in (401,403,404,410): return None
        return None
    except Exception:
        return None



def _youtube_quota_day():
    """YouTube Data API daily quotas reset at Pacific midnight."""
    try: return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception: return datetime.now(timezone.utc).date().isoformat()

def _youtube_search_available():
    try: return bool(YOUTUBE_GATEWAY.operation_available("search"))
    except Exception: return True

def _history_youtube_budget_limits():
    total=max(0,int(HISTORY_YOUTUBE_SEARCH_BUDGET or 0))
    recent=int(round(total*HISTORY_YOUTUBE_BUDGET_SHARES['recent']))
    empty=int(round(total*HISTORY_YOUTUBE_BUDGET_SHARES['empty']))
    blue=int(round(total*HISTORY_YOUTUBE_BUDGET_SHARES['blue']))
    archive=max(0,total-recent-empty-blue)
    return {'recent':recent,'empty':empty,'blue':blue,'archive':archive}


def _history_youtube_budget_status():
    """Return persisted daily search-list usage with reserved workload buckets."""
    today=_youtube_quota_day(); limits=_history_youtube_budget_limits()
    with HISTORY_YOUTUBE_BUDGET_LOCK:
        try: payload=json.loads(HISTORY_YOUTUBE_BUDGET_FILE.read_text(encoding='utf-8'))
        except Exception: payload={}
        if str(payload.get('date') or '')!=today: payload={}
        used_by={k:int((payload.get('usedByBucket') or {}).get(k) or 0) for k in limits}
        # Legacy v3.0.x state had only a flat count. Preserve exhaustion for the
        # remainder of that UTC day rather than silently resetting quota on deploy.
        legacy=max(0,int(payload.get('used') or 0)-sum(used_by.values()))
        if legacy: used_by['archive']+=legacy
        used=sum(used_by.values())
        return {'date':today,'used':used,'limit':HISTORY_YOUTUBE_SEARCH_BUDGET,'remaining':max(0,HISTORY_YOUTUBE_SEARCH_BUDGET-used),
                'usedByBucket':used_by,'limitsByBucket':limits,'remainingByBucket':{k:max(0,limits[k]-used_by[k]) for k in limits}}


def _history_youtube_budget_take(bucket='archive'):
    """Reserve one search.list call without crossing another workload's reserve."""
    bucket=str(bucket or 'archive').lower()
    limits=_history_youtube_budget_limits()
    if bucket not in limits: bucket='archive'
    if HISTORY_YOUTUBE_SEARCH_BUDGET<=0 or limits.get(bucket,0)<=0:
        raise YouTubeRateLimited(f'Historical YouTube search rescue disabled for {bucket}')
    today=_youtube_quota_day()
    with HISTORY_YOUTUBE_BUDGET_LOCK:
        try: payload=json.loads(HISTORY_YOUTUBE_BUDGET_FILE.read_text(encoding='utf-8'))
        except Exception: payload={}
        if str(payload.get('date') or '')!=today: payload={}
        used_by={k:int((payload.get('usedByBucket') or {}).get(k) or 0) for k in limits}
        legacy=max(0,int(payload.get('used') or 0)-sum(used_by.values()))
        if legacy: used_by['archive']+=legacy
        used=sum(used_by.values())
        if used>=HISTORY_YOUTUBE_SEARCH_BUDGET:
            raise YouTubeRateLimited(f'Historical YouTube search budget exhausted ({used}/{HISTORY_YOUTUBE_SEARCH_BUDGET})',operation='search',quota_exhausted=False)
        if used_by[bucket]>=limits[bucket]:
            raise YouTubeRateLimited(f'Historical YouTube {bucket} search reserve exhausted ({used_by[bucket]}/{limits[bucket]})',operation='search',quota_exhausted=False)
        if not _youtube_search_available():
            st=(YOUTUBE_GATEWAY.status() or {}).get('search') or {}
            raise YouTubeRateLimited(f"YouTube search unavailable: {st.get('lastError') or 'provider cooldown'}",operation='search',retry_at=float(st.get('resetAt') or 0),quota_exhausted=bool(st.get('quotaExhausted')))
        used_by[bucket]+=1; used=sum(used_by.values())
        try:
            payload_out={'date':today,'used':used,'usedByBucket':used_by,'savedAt':time.time()}
            tmp=HISTORY_YOUTUBE_BUDGET_FILE.with_suffix('.json.tmp'); tmp.write_text(json.dumps(payload_out),encoding='utf-8'); tmp.replace(HISTORY_YOUTUBE_BUDGET_FILE)
        except Exception: pass
        return _history_youtube_budget_status()


def _history_search_budget_bucket(date,best_tier=''):
    try: age=(datetime.now(timezone.utc).date()-datetime.strptime(str(date)[:10],'%Y-%m-%d').date()).days
    except Exception: age=9999
    if age<=2: return 'recent'
    best=str(best_tier or '').lower()
    if not best or best=='none': return 'empty'
    if best=='blue': return 'blue'
    return 'archive'


def _history_capture_collection_catalog(league,date,rows):
    """Persist Silver roundup media once per source catalog, never per game."""
    grouped={}
    for raw in rows or []:
        if not isinstance(raw,dict): continue
        item=annotate_media_scope(raw,league=str(league).upper(),date=str(date)[:10])
        scope=str(item.get('mediaScope') or '')
        if scope not in MEDIA_COLLECTION_SCOPES: continue
        period=str(item.get('collectionPeriodKey') or (media_week_key(item,date) if scope==MEDIA_SCOPE_WEEK_LEAGUE else str(date)[:10]))
        item['date']=(period if scope==MEDIA_SCOPE_DAY_LEAGUE and re.match(r'^\d{4}-\d{2}-\d{2}$',period) else str(item.get('date') or date)[:10])
        item['league']=str(league).upper(); item['competitionId']=str(league).upper()
        item['collectionKind']=media_collection_kind(item,scope); item['collectionTier']='silver'; item['displayTier']='silver'
        grouped.setdefault((scope,period,item['collectionKind']),[]).append(item)
    for (scope,period,kind),items in grouped.items():
        HISTORY_REPOSITORY.put_collection_media(scope,league,period,items,collection_kind=kind)
    return sum(len(v) for v in grouped.values())


def _team_primary_youtube_token(name):
    parts=[x for x in re.findall(r"[A-Za-z0-9]+",str(name or '')) if x]
    return parts[-1] if parts else str(name or '').strip()



def _official_youtube_activity_cache_path(league,date):
    safe=re.sub(r'[^A-Za-z0-9_.-]+','-',f'{str(league).upper()}-{str(date)[:10]}')
    return YOUTUBE_CACHE_DIR / f'history-activities-v290-{safe}.json'


def _official_youtube_day_activity_catalog(league,date,force=False):
    """Return verified uploads from one official league channel around a game day.

    This is the primary v4.0.2 historical YouTube lane. activities.list is cheap
    and independent of the separate search.list daily bucket. We fetch the official
    channel once per league/date, then batch videos.list all upload ids so every
    game on that slate can reuse the same verified catalog.
    """
    league=str(league or '').upper(); date=str(date or '')[:10]
    channel_id=YOUTUBE_OFFICIAL_CHANNEL_IDS.get(league); key=read_youtube_key()
    if not channel_id or not key: return []
    path=_official_youtube_activity_cache_path(league,date)
    try:
        payload=json.loads(path.read_text(encoding='utf-8'))
        age=time.time()-float(payload.get('savedAt') or 0)
        # Even a forced date refresh reuses a catalog fetched moments ago. This
        # keeps one full-day discovery from refetching the same channel for every
        # event while still allowing stale historical catalogs to be rebuilt.
        if isinstance(payload.get('data'),list) and (age < 5*60 or (not force and age < 30*24*60*60)):
            _history_capture_collection_catalog(league,date,payload['data'])
            return payload['data']
    except Exception: pass
    try:
        d=datetime.strptime(date,'%Y-%m-%d').replace(tzinfo=timezone.utc)
    except Exception:
        return []
    after=(d-timedelta(hours=10)).isoformat().replace('+00:00','Z')
    before=(d+timedelta(days=3,hours=6)).isoformat().replace('+00:00','Z')
    ids=[]; seen=set(); page=''; pages=0
    while pages<3:
        params={'part':'snippet,contentDetails','channelId':channel_id,'maxResults':'50','publishedAfter':after,'publishedBefore':before,'regionCode':'US','key':key}
        if page: params['pageToken']=page
        payload=youtube_fetch_json(f"{YOUTUBE_API_BASE}/activities?{urlencode(params)}",timeout=12)
        pages+=1
        for row in payload.get('items') or []:
            if not isinstance(row,dict): continue
            snippet=row.get('snippet') or {}
            if str(snippet.get('type') or '').lower()!='upload': continue
            vid=str(((row.get('contentDetails') or {}).get('upload') or {}).get('videoId') or '').strip()
            if vid and vid not in seen:
                seen.add(vid); ids.append(vid)
        page=str(payload.get('nextPageToken') or '')
        if not page: break
    if not ids:
        try: path.write_text(json.dumps({'savedAt':time.time(),'data':[]}),encoding='utf-8')
        except Exception: pass
        return []
    details=[]
    for offset in range(0,len(ids),50):
        chunk=ids[offset:offset+50]
        payload=youtube_fetch_json(f"{YOUTUBE_API_BASE}/videos?{urlencode({'part':'snippet,contentDetails,status,statistics','id':','.join(chunk),'key':key})}",timeout=12)
        details.extend(x for x in (payload.get('items') or []) if isinstance(x,dict))
    out=[]
    for idx,vd in enumerate(details):
        vid=str(vd.get('id') or '').strip()
        if not vid or not _youtube_video_available_in_us(vd): continue
        sn=vd.get('snippet') or {}; cd=vd.get('contentDetails') or {}
        title=str(sn.get('title') or '').strip(); desc=str(sn.get('description') or '').strip(); channel=str(sn.get('channelTitle') or league).strip()
        dur=_iso8601_duration_seconds(cd.get('duration')) or 0
        # Keep long-form highlights/condensed packages but reject full broadcasts.
        max_duration=35*60 if league in ('NFL','NBA','NHL') else 30*60
        if dur and (dur<8 or dur>max_duration): continue
        thumbs=sn.get('thumbnails') or {}; thumb=((thumbs.get('high') or thumbs.get('medium') or thumbs.get('default') or {}).get('url') if isinstance(thumbs,dict) else '') or ''
        text=f'{title} {desc}'.lower()
        overview=bool(re.search(r'full game highlights|extended.*highlights|game highlights|game recap|game summary|condensed game|full match highlights|match highlights|match recap',text))
        if not overview and dur>=90 and re.search(r'highlight|recap|every|best of|top plays',text): overview=True
        item={
            'id':f'yt-activity-history-{league.lower()}-{vid}','eventId':vid,'youtubeId':vid,'league':league,
            'title':title,'description':desc,'duration':dur,'durationSeconds':dur,'thumbnail':str(thumb),
            'source':channel,'sourceLabel':channel,'sourceType':'official-channel-activities-history','provider':'YOUTUBE',
            'verifiedPlayable':True,'embedValidated':True,'externalOnly':False,'validationState':'VERIFIED',
            'embedValidation':'activities.list+videos.list','overview':overview,'programType':'recap' if overview else 'reel',
            'externalUrl':f'https://www.youtube.com/watch?v={vid}','publishedAt':str(sn.get('publishedAt') or ''),
            'officialChannelId':channel_id,'chronology':[1,998,0,idx,idx],'importance':98 if overview else 66,'rapid':True,
        }
        out.append(annotate_media_tier(item))
    _history_capture_collection_catalog(league,date,out)
    try: path.write_text(json.dumps({'savedAt':time.time(),'data':out},ensure_ascii=False),encoding='utf-8')
    except Exception: pass
    return out


def _official_youtube_history_activity_results(league,date,away,home,max_items=18,force=False):
    league=str(league or '').upper(); away=str(away or '').strip(); home=str(home or '').strip()
    if not away or not home: return []
    out=[]
    for raw in _official_youtube_day_activity_catalog(league,date,force=force):
        item=dict(raw); title=str(item.get('title') or ''); desc=str(item.get('description') or '')
        item=annotate_media_scope(item,league=league,date=date,away=away,home=home)
        if item.get('mediaScope')!=MEDIA_SCOPE_GAME: continue
        if _youtube_match_strength(title,desc,away,home)<2: continue
        text=f'{title} {desc}'.lower()
        if re.search(r'podcast|reaction|reacts|preview|prediction|rumou?r|press conference|interview|betting|fantasy',text): continue
        item['away']=away; item['home']=home; item['date']=str(date)[:10]
        out.append(_decorate_recap_tier(item))
    out.sort(key=lambda x:(
        HISTORY_TIER_PRIORITY.get(str(x.get('recapTier') or 'blue'),0),
        bool(x.get('overview')),
        -abs(int(x.get('durationSeconds') or 0)-210) if str(x.get('recapTier') or '')=='green' else int(x.get('durationSeconds') or 0)
    ),reverse=True)
    return out[:max_items]




def _official_youtube_uploads_cache_path(league):
    safe=re.sub(r'[^A-Za-z0-9_.-]+','-',str(league).upper())
    return YOUTUBE_CACHE_DIR / f'history-uploads-index-v304-{safe}.json'


def _official_youtube_uploads_index(league,date,force=False,max_pages=4):
    """Incrementally index an official channel's uploads playlist back through history.

    activities.list is useful for recent uploads but does not reliably provide a deep
    archive on every official sports channel. The uploads playlist is the durable,
    quota-light historical lane: channels.list resolves the uploads playlist once,
    playlistItems.list walks backward, and videos.list validates/annotates each page.
    The cursor and collected rows persist on disk so an always-on server gradually
    builds a reusable official-video archive instead of repeating searches per game.
    """
    league=str(league or '').upper(); date=str(date or '')[:10]
    channel_id=YOUTUBE_OFFICIAL_CHANNEL_IDS.get(league); key=read_youtube_key()
    if not channel_id or not key: return []
    try:
        target=datetime.strptime(date,'%Y-%m-%d').replace(tzinfo=timezone.utc)
    except Exception:
        return []
    window_start=target-timedelta(days=1)
    window_end=target+timedelta(days=4)
    path=_official_youtube_uploads_cache_path(league)
    payload={}
    try:
        payload=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(payload,dict): payload={}
    except Exception:
        payload={}
    if str(payload.get('channelId') or '')!=channel_id:
        payload={}
    rows=[x for x in (payload.get('data') or []) if isinstance(x,dict)]
    playlist_id=str(payload.get('playlistId') or '')
    page_token=str(payload.get('nextPageToken') or '')
    complete=bool(payload.get('complete'))

    if not playlist_id:
        data=youtube_fetch_json(f"{YOUTUBE_API_BASE}/channels?{urlencode({'part':'contentDetails','id':channel_id,'key':key})}",timeout=12)
        items=data.get('items') or []
        if items:
            playlist_id=str((((items[0].get('contentDetails') or {}).get('relatedPlaylists') or {}).get('uploads')) or '')
        if not playlist_id: return []

    def parse_pub(item):
        text=str(item.get('publishedAt') or '')
        try: return datetime.fromisoformat(text.replace('Z','+00:00')).astimezone(timezone.utc)
        except Exception: return None

    oldest=min((dt for dt in (parse_pub(x) for x in rows) if dt),default=None)
    covered=bool(oldest and oldest<=window_start)
    pages=0
    # Force ignores stale-complete metadata only when the target is not already covered.
    while not covered and not complete and pages<max(1,int(max_pages or 1)):
        params={'part':'snippet,contentDetails','playlistId':playlist_id,'maxResults':'50','key':key}
        if page_token: params['pageToken']=page_token
        page=youtube_fetch_json(f"{YOUTUBE_API_BASE}/playlistItems?{urlencode(params)}",timeout=12)
        pages+=1
        page_rows=[x for x in (page.get('items') or []) if isinstance(x,dict)]
        ids=[]; order={}
        for idx,item in enumerate(page_rows):
            vid=str(((item.get('contentDetails') or {}).get('videoId')) or ((item.get('snippet') or {}).get('resourceId') or {}).get('videoId') or '').strip()
            if vid and vid not in order:
                order[vid]=idx; ids.append(vid)
        detail_by={}
        if ids:
            details=youtube_fetch_json(f"{YOUTUBE_API_BASE}/videos?{urlencode({'part':'snippet,contentDetails,status,statistics','id':','.join(ids[:50]),'key':key})}",timeout=12)
            detail_by={str(x.get('id') or ''):x for x in (details.get('items') or []) if isinstance(x,dict)}
        existing={str(x.get('youtubeId') or '') for x in rows if x.get('youtubeId')}
        for vid in ids:
            vd=detail_by.get(vid)
            if not vd or not _youtube_video_available_in_us(vd): continue
            sn=vd.get('snippet') or {}; cd=vd.get('contentDetails') or {}
            title=str(sn.get('title') or '').strip(); desc=str(sn.get('description') or '').strip(); channel=str(sn.get('channelTitle') or league).strip()
            dur=_iso8601_duration_seconds(cd.get('duration')) or 0
            max_duration=35*60 if league in ('NFL','NBA','NHL') else 30*60
            if dur and (dur<8 or dur>max_duration): continue
            thumbs=sn.get('thumbnails') or {}; thumb=((thumbs.get('high') or thumbs.get('medium') or thumbs.get('default') or {}).get('url') if isinstance(thumbs,dict) else '') or ''
            text=f'{title} {desc}'.lower()
            overview=bool(re.search(r'full game highlights|full-game highlights|game highlights|game recap|game summary|condensed game|extended.*highlights|full match highlights|match highlights|match recap|highlights from',text))
            if not overview and dur>=90 and re.search(r'\b(highlights?|recap|summary)\b',text): overview=True
            item={
                'id':f'yt-uploads-history-{league.lower()}-{vid}','eventId':vid,'youtubeId':vid,'league':league,
                'title':title,'description':desc,'duration':dur,'durationSeconds':dur,'thumbnail':str(thumb),
                'source':channel,'sourceLabel':channel,'sourceType':'official-channel-uploads-history','provider':'YOUTUBE',
                'verifiedPlayable':True,'embedValidated':True,'externalOnly':False,'validationState':'VERIFIED',
                'embedValidation':'uploads-playlist+videos.list','overview':overview,'programType':'recap' if overview else 'reel',
                'externalUrl':f'https://www.youtube.com/watch?v={vid}','publishedAt':str(sn.get('publishedAt') or ''),
                'officialChannelId':channel_id,'chronology':[1,997,0,order.get(vid,999),order.get(vid,999)],
                'importance':99 if overview else 64,'rapid':True,
            }
            item=annotate_media_tier(item)
            if vid in existing:
                for i,old in enumerate(rows):
                    if str(old.get('youtubeId') or '')==vid:
                        merged=dict(old); merged.update(item); rows[i]=merged; break
            else:
                rows.append(item); existing.add(vid)
        page_token=str(page.get('nextPageToken') or '')
        if not page_token: complete=True
        oldest=min((dt for dt in (parse_pub(x) for x in rows) if dt),default=None)
        covered=bool(oldest and oldest<=window_start)
        try:
            path.write_text(json.dumps({'savedAt':time.time(),'channelId':channel_id,'playlistId':playlist_id,'nextPageToken':page_token,
                                        'complete':complete,'oldestPublishedAt':oldest.isoformat() if oldest else '',
                                        'data':rows},ensure_ascii=False),encoding='utf-8')
        except Exception: pass

    # Keep a generous window because official recaps are often posted the following
    # morning and west-coast games can cross UTC dates.
    result=[]
    for item in rows:
        dt=parse_pub(item)
        if dt and not (window_start<=dt<=window_end): continue
        result.append(dict(item))
    result.sort(key=lambda x:str(x.get('publishedAt') or ''),reverse=True)
    _history_capture_collection_catalog(league,date,result)
    return result


def _official_youtube_history_upload_results(league,date,away,home,max_items=24,force=False):
    """Match one event against the persistent official uploads-playlist index."""
    league=str(league or '').upper(); away=str(away or '').strip(); home=str(home or '').strip()
    if not away or not home: return []
    out=[]
    for raw in _official_youtube_uploads_index(league,date,force=force,max_pages=4):
        item=dict(raw); title=str(item.get('title') or ''); desc=str(item.get('description') or '')
        item=annotate_media_scope(item,league=league,date=date,away=away,home=home)
        if item.get('mediaScope')!=MEDIA_SCOPE_GAME: continue
        if _youtube_match_strength(title,desc,away,home)<2: continue
        text=f'{title} {desc}'.lower()
        # Studio chatter belongs in Gold only when the classifier can positively
        # identify a produced recap; generic previews/interviews are not game recaps.
        if re.search(r'podcast|preview|prediction|rumou?r|betting|fantasy|pregame',text): continue
        item['away']=away; item['home']=home; item['date']=str(date)[:10]
        out.append(_decorate_recap_tier(item))
    out.sort(key=lambda x:(
        HISTORY_TIER_PRIORITY.get(str(x.get('recapTier') or 'blue'),0),
        bool(x.get('overview')),
        -abs(int(x.get('durationSeconds') or 0)-210) if str(x.get('recapTier') or '')=='green' else int(x.get('durationSeconds') or 0)
    ),reverse=True)
    return out[:max_items]

def _official_youtube_day_search_cache_path(league,date):
    safe=re.sub(r'[^A-Za-z0-9_.-]+','-',f'{str(league).upper()}-{str(date)[:10]}')
    return YOUTUBE_CACHE_DIR / f'history-search-day-v290-{safe}.json'


def _official_youtube_day_search_catalog(league,date,force=False,budget_bucket='archive'):
    """One search.list rescue for an entire official league channel/day.

    Historical discovery must never spend one search call per game. If the much
    cheaper activities.list catalog is unavailable/incomplete, one channel-scoped
    search builds a day catalog that every event on the slate shares. Background
    backfill never invokes this lane; it is reserved for an interactive date.
    """
    league=str(league or '').upper(); date=str(date or '')[:10]
    channel_id=YOUTUBE_OFFICIAL_CHANNEL_IDS.get(league); key=read_youtube_key()
    if not channel_id or not key: return []
    path=_official_youtube_day_search_cache_path(league,date)
    try:
        payload=json.loads(path.read_text(encoding='utf-8'))
        age=time.time()-float(payload.get('savedAt') or 0)
        # Even a forced date refresh reuses a catalog fetched moments ago. This
        # keeps one full-day discovery from refetching the same channel for every
        # event while still allowing stale historical catalogs to be rebuilt.
        if isinstance(payload.get('data'),list) and (age < 5*60 or (not force and age < 30*24*60*60)):
            _history_capture_collection_catalog(league,date,payload['data'])
            return payload['data']
    except Exception: pass
    try:
        d=datetime.strptime(date,'%Y-%m-%d').replace(tzinfo=timezone.utc)
    except Exception:
        return []
    _history_youtube_budget_take(budget_bucket)
    # Tight viewer-day-ish window. It is deliberately wider than UTC midnight so
    # west-coast night games and next-morning official uploads are retained, while
    # still keeping one page (50 results) useful for high-volume NBA channels.
    after=(d-timedelta(hours=8)).isoformat().replace('+00:00','Z')
    before=(d+timedelta(days=1,hours=16)).isoformat().replace('+00:00','Z')
    params={
        'part':'snippet','type':'video','channelId':channel_id,'maxResults':'50','order':'date',
        'publishedAfter':after,'publishedBefore':before,'regionCode':'US','safeSearch':'moderate','key':key,
    }
    search=youtube_fetch_json(f"{YOUTUBE_API_BASE}/search?{urlencode(params)}",timeout=12)
    ids=[]; order={}
    for idx,row in enumerate(search.get('items') or []):
        vid=str(((row.get('id') or {}).get('videoId')) or '').strip()
        if vid and vid not in order:
            order[vid]=idx; ids.append(vid)
    if not ids:
        try: path.write_text(json.dumps({'savedAt':time.time(),'data':[]}),encoding='utf-8')
        except Exception: pass
        return []
    details=[]
    for offset in range(0,len(ids),50):
        chunk=ids[offset:offset+50]
        payload=youtube_fetch_json(f"{YOUTUBE_API_BASE}/videos?{urlencode({'part':'snippet,contentDetails,status,statistics','id':','.join(chunk),'key':key})}",timeout=12)
        details.extend(x for x in (payload.get('items') or []) if isinstance(x,dict))
    out=[]
    for vd in details:
        vid=str(vd.get('id') or '').strip()
        if not vid or not _youtube_video_available_in_us(vd): continue
        sn=vd.get('snippet') or {}; cd=vd.get('contentDetails') or {}
        title=str(sn.get('title') or '').strip(); desc=str(sn.get('description') or '').strip(); channel=str(sn.get('channelTitle') or league).strip()
        dur=_iso8601_duration_seconds(cd.get('duration')) or 0
        max_duration=35*60 if league in ('NFL','NBA','NHL') else 30*60
        if dur and (dur<8 or dur>max_duration): continue
        thumbs=sn.get('thumbnails') or {}; thumb=((thumbs.get('high') or thumbs.get('medium') or thumbs.get('default') or {}).get('url') if isinstance(thumbs,dict) else '') or ''
        text=f'{title} {desc}'.lower()
        overview=bool(re.search(r'full game highlights|extended.*highlights|game highlights|game recap|game summary|condensed game|full match highlights|match highlights|match recap',text))
        if not overview and dur>=90 and re.search(r'highlight|recap|every|best of|top plays',text): overview=True
        item={
            'id':f'yt-day-search-history-{league.lower()}-{vid}','eventId':vid,'youtubeId':vid,'league':league,
            'title':title,'description':desc,'duration':dur,'durationSeconds':dur,'thumbnail':str(thumb),
            'source':channel,'sourceLabel':channel,'sourceType':'official-channel-day-search-history','provider':'YOUTUBE',
            'verifiedPlayable':True,'embedValidated':True,'externalOnly':False,'validationState':'VERIFIED',
            'embedValidation':'search.list-day+videos.list','overview':overview,'programType':'recap' if overview else 'reel',
            'externalUrl':f'https://www.youtube.com/watch?v={vid}','publishedAt':str(sn.get('publishedAt') or ''),
            'officialChannelId':channel_id,'chronology':[1,998,0,order.get(vid,999),order.get(vid,999)],'importance':97 if overview else 65,'rapid':True,
        }
        out.append(annotate_media_tier(item))
    _history_capture_collection_catalog(league,date,out)
    try: path.write_text(json.dumps({'savedAt':time.time(),'data':out},ensure_ascii=False),encoding='utf-8')
    except Exception: pass
    return out


def _official_youtube_history_day_search_results(league,date,away,home,max_items=18,force=False,budget_bucket='archive'):
    """Match one event against the shared official league/day search catalog."""
    league=str(league or '').upper(); away=str(away or '').strip(); home=str(home or '').strip()
    if not away or not home: return []
    out=[]
    for raw in _official_youtube_day_search_catalog(league,date,force=force,budget_bucket=budget_bucket):
        item=dict(raw); title=str(item.get('title') or ''); desc=str(item.get('description') or '')
        item=annotate_media_scope(item,league=league,date=date,away=away,home=home)
        if item.get('mediaScope')!=MEDIA_SCOPE_GAME: continue
        if _youtube_match_strength(title,desc,away,home)<2: continue
        text=f'{title} {desc}'.lower()
        if re.search(r'podcast|reaction|reacts|preview|prediction|rumou?r|press conference|interview|betting|fantasy',text): continue
        item['away']=away; item['home']=home; item['date']=str(date)[:10]
        out.append(_decorate_recap_tier(item))
    out.sort(key=lambda x:(
        HISTORY_TIER_PRIORITY.get(str(x.get('recapTier') or 'blue'),0),
        bool(x.get('overview')),
        -abs(int(x.get('durationSeconds') or 0)-210) if str(x.get('recapTier') or '')=='green' else int(x.get('durationSeconds') or 0)
    ),reverse=True)
    return out[:max_items]

def _official_youtube_history_api_results(league,date,away,home,max_items=18):
    """Target the official league channel for one historical game using one search call.

    v2.8.3's public YouTube HTML parser is a useful zero-quota lane, but YouTube can
    return a consent/client shell with no videoRenderer nodes. That produced the
    misleading `8/8 searched, 0 playable` Christmas result even though official NBA
    uploads existed. This rescue path spends exactly one search.list request for the
    game, scoped to the verified league channel and game date, then batch-validates
    every returned id with videos.list before any item becomes playable.
    """
    league=str(league or '').upper(); away=str(away or '').strip(); home=str(home or '').strip()
    channel_id=YOUTUBE_OFFICIAL_CHANNEL_IDS.get(league)
    key=read_youtube_key()
    if not channel_id or not key or not away or not home:
        return []
    _history_youtube_budget_take('archive')
    try:
        d=datetime.strptime(str(date)[:10],'%Y-%m-%d').replace(tzinfo=timezone.utc)
    except Exception:
        d=datetime.now(timezone.utc)-timedelta(days=1)
    # Official titles overwhelmingly use nicknames (CAVALIERS at KNICKS,
    # Cowboys vs. Commanders), so nickname tokens produce much stronger results
    # than score-ribbon abbreviations or full city names.
    q=' '.join(x for x in (_team_primary_youtube_token(away),_team_primary_youtube_token(home)) if x)
    params={
        'part':'snippet','type':'video','maxResults':'25','order':'relevance',
        'channelId':channel_id,'q':q,'videoEmbeddable':'true','videoSyndicated':'true',
        'safeSearch':'moderate','regionCode':'US','relevanceLanguage':'en',
        'publishedAfter':(d-timedelta(hours=8)).isoformat().replace('+00:00','Z'),
        'publishedBefore':(d+timedelta(days=2,hours=18)).isoformat().replace('+00:00','Z'),
        'key':key,
    }
    search=youtube_fetch_json(f"{YOUTUBE_API_BASE}/search?{urlencode(params)}",timeout=12)
    search_rows=[x for x in (search.get('items') or []) if isinstance(x,dict)]
    ids=[]
    for row in search_rows:
        vid=str((row.get('id') or {}).get('videoId') or '').strip()
        if vid and vid not in ids: ids.append(vid)
    if not ids: return []
    details=youtube_fetch_json(f"{YOUTUBE_API_BASE}/videos?{urlencode({'part':'snippet,contentDetails,status,statistics','id':','.join(ids[:50]),'key':key})}",timeout=12)
    detail_by={str(x.get('id') or ''):x for x in (details.get('items') or []) if isinstance(x,dict)}
    out=[]
    for idx,vid in enumerate(ids):
        vd=detail_by.get(vid)
        if not vd or not _youtube_video_available_in_us(vd): continue
        sn=vd.get('snippet') or {}
        title=str(sn.get('title') or '').strip(); desc=str(sn.get('description') or '').strip(); ch=str(sn.get('channelTitle') or '').strip()
        scoped=annotate_media_scope({'title':title,'description':desc,'league':league,'publishedAt':str(sn.get('publishedAt') or '')},league=league,date=date,away=away,home=home)
        if scoped.get('mediaScope')!=MEDIA_SCOPE_GAME:
            _history_capture_collection_catalog(league,date,[{**scoped,'youtubeId':vid,'id':f'yt-official-history-{league.lower()}-{vid}','source':ch or league,'sourceLabel':ch or league,'sourceType':'official-league-youtube-history','provider':'YOUTUBE','verifiedPlayable':True,'embedValidated':True,'externalOnly':False,'validationState':'VERIFIED','externalUrl':f'https://www.youtube.com/watch?v={vid}'}])
            continue
        if _youtube_match_strength(title,desc,away,home)<2: continue
        txt=f'{title} {desc}'.lower()
        if re.search(r'podcast|reaction|reacts|preview|prediction|rumou?r|press conference|interview|betting|fantasy',txt): continue
        dur=_iso8601_duration_seconds((vd.get('contentDetails') or {}).get('duration')) or 0
        max_duration=1800 if league in ('NFL','NBA','NHL') else 1500
        if dur and (dur<8 or dur>max_duration): continue
        overview=bool(re.search(r'full game highlights|extended.*highlights|game highlights|game recap|game summary|condensed game|full match highlights|match highlights|match recap',txt))
        if not overview and dur>=90 and re.search(r'highlight|recap|every|best of|top plays',txt): overview=True
        thumbs=sn.get('thumbnails') or {}
        thumb=((thumbs.get('high') or thumbs.get('medium') or thumbs.get('default') or {}).get('url') if isinstance(thumbs,dict) else '') or ''
        row={
            'id':f'yt-official-history-{league.lower()}-{vid}','eventId':vid,'youtubeId':vid,'league':league,
            'title':title,'description':desc,'duration':dur,'durationSeconds':dur,'thumbnail':str(thumb),
            'source':ch or league,'sourceLabel':ch or league,'sourceType':'official-league-youtube-history','provider':'YOUTUBE',
            'verifiedPlayable':True,'embedValidated':True,'externalOnly':False,'validationState':'VERIFIED','embedValidation':'search.list+videos.list',
            'overview':overview,'programType':'recap' if overview else 'reel','externalUrl':f'https://www.youtube.com/watch?v={vid}',
            'chronology':[1,999,0,idx,idx],'importance':96 if overview else 62,'rapid':True,'away':away,'home':home,'date':str(date)[:10],
            'publishedAt':str(sn.get('publishedAt') or ''),'officialChannelId':channel_id,
        }
        out.append(annotate_media_tier(row))
    out.sort(key=lambda x:(
        bool(x.get('verifiedPlayable')),
        HISTORY_TIER_PRIORITY.get(str(x.get('recapTier') or 'blue'),0),
        bool(x.get('overview')),
        -abs(int(x.get('durationSeconds') or 0)-210) if str(x.get('recapTier') or '')=='green' else int(x.get('durationSeconds') or 0)
    ),reverse=True)
    return out[:max_items]


def _historical_youtube_web_results(league,date,away,home,max_items=14):
    """No-search-list historical YouTube candidate discovery.

    This fallback favors official league/team/broadcast sources and exact matchup
    metadata. Public-page/oEmbed results are candidate evidence only. A candidate
    becomes playable only after videos.list positively validates embed/region state.
    """
    league=str(league or '').upper(); away=str(away or '').strip(); home=str(home or '').strip()
    if not league or not away or not home: return []
    try:
        d=datetime.strptime(str(date),'%Y-%m-%d')
        human=d.strftime('%B %d %Y').replace(' 0',' ')
    except Exception:
        human=str(date or '')
    queries=[
        f'"{away}" "{home}" {league} "full game highlights" {human}',
        f'"{away}" "{home}" {league} "game recap" {human}',
        f'"{away}" "{home}" {league} "game highlights" {human}',
        f'{away} {home} {league} full highlights {human}',
        f'{away} {home} {league} recap highlights {human}',
    ]
    if league in ('NBA','NFL','NHL'):
        queries += [f'{away} vs {home} {league} highlights {human}',f'{away} at {home} {league} highlights {human}']
    if league in ('MLS','EPL'):
        queries += [f'"{away}" "{home}" full match highlights {human}',f'{away} vs {home} match recap {human}']
    raw=[]; seen=set()
    for query in queries:
        for row in _youtube_html_video_renderers(query,max_results=18):
            vid=str(row.get('videoId') or '')
            if not vid or vid in seen: continue
            seen.add(vid); raw.append(row)
            if len(raw)>=32: break
        if len(raw)>=32: break

    league_names={'MLB':['mlb','major league baseball'],'NFL':['nfl','national football league'],'NBA':['nba','national basketball association'],'NHL':['nhl','national hockey league'],'EPL':['premier league'],'MLS':['mls','major league soccer']}
    team_tokens=set(_team_search_tokens(away)+_team_search_tokens(home))
    candidates=[]
    for idx,row in enumerate(raw):
        title=str(row.get('title') or '').strip(); desc=str(row.get('description') or '').strip(); channel=str(row.get('channelTitle') or '').strip()
        if _youtube_match_strength(title,desc,away,home)<2: continue
        text=f'{title} {desc}'.lower(); chl=channel.lower()
        official=any(x in chl for x in league_names.get(league,[])) or any(t in chl for t in team_tokens if len(t)>3) or 'official' in chl
        broadcast=bool(re.search(r'espn|fox sports|nbc sports|cbs sports|sportsnet|nfl network|nba tv|nhl network|mlb network|apple tv|mls season pass|local|news|tv',chl))
        if not (official or broadcast): continue
        if re.search(r'podcast|reaction|reacts|preview|prediction|rumou?r|press conference|interview|betting|fantasy',text): continue
        dur=int(row.get('durationSeconds') or 0)
        max_duration=1500 if league in ('NFL','NBA','NHL') else (1200 if league in ('MLS','EPL') else 900)
        if dur and (dur<10 or dur>max_duration): continue
        overview=bool(re.search(r'full game highlights|game highlights|game recap|game summary|condensed game|full match highlights|match highlights|match recap',text))
        if not overview and dur>=90 and re.search(r'highlight|recap',text): overview=True
        vid=str(row.get('videoId') or '')
        candidates.append({'id':f'yt-web-{league.lower()}-{vid}','eventId':vid,'youtubeId':vid,'league':league,
                           'title':title,'description':desc,'duration':dur,'durationSeconds':dur,'thumbnail':str(row.get('thumbnail') or ''),
                           'source':channel or 'YouTube','sourceLabel':channel or 'YouTube','sourceType':'youtube-web-search','provider':'YOUTUBE',
                           'verifiedPlayable':False,'embedValidated':False,'externalOnly':True,'overview':overview,
                           'programType':'recap' if overview else 'reel','externalUrl':f'https://www.youtube.com/watch?v={vid}',
                           'chronology':[1,999,0,idx,idx],'importance':72 if overview else 38,'rapid':True,'away':away,'home':home,'date':str(date),
                           'publishedText':row.get('publishedText') or ''})
    # Validate the best candidates before they are allowed into the embedded
    # player. When a YouTube key is configured, videos.list is ideal here: it
    # costs one unit and validates up to 50 exact ids at once without consuming the
    # separate search.list daily-call bucket, including embeddable + US region
    # restrictions. If videos.list is temporarily unavailable, oEmbed may enrich
    # metadata but the asset remains CANDIDATE; it is never painted green.
    candidates.sort(key=lambda x:(bool(x.get('overview')),_youtube_source_score(x.get('sourceLabel'),away,home),-abs(int(x.get('durationSeconds') or 0)-210)),reverse=True)
    selected=[dict(x) for x in candidates[:max_items]]
    detail_by={}
    key=read_youtube_key()
    ids=[str(x.get('youtubeId') or '') for x in selected if x.get('youtubeId')]
    if key and ids:
        try:
            details=youtube_fetch_json(f"{YOUTUBE_API_BASE}/videos?{urlencode({'part':'snippet,contentDetails,status','id':','.join(ids[:50]),'key':key})}",timeout=10)
            detail_by={str(x.get('id') or ''):x for x in (details.get('items') or []) if isinstance(x,dict)}
        except Exception as exc:
            print(f'[SBB history YouTube] embed validation fallback {league} {away}@{home}: {type(exc).__name__}: {exc}',flush=True)
            detail_by={}
    checked=[]
    for row in selected:
        vid=str(row.get('youtubeId') or '')
        vd=detail_by.get(vid)
        if vd is not None:
            sn=vd.get('snippet') or {}; dur=_iso8601_duration_seconds((vd.get('contentDetails') or {}).get('duration')) or int(row.get('durationSeconds') or 0)
            if dur: row['duration']=row['durationSeconds']=dur
            if sn.get('title'): row['title']=str(sn.get('title'))
            if sn.get('channelTitle'): row['source']=row['sourceLabel']=str(sn.get('channelTitle'))
            thumbs=sn.get('thumbnails') or {}; thumb=((thumbs.get('high') or thumbs.get('medium') or thumbs.get('default') or {}).get('url') if isinstance(thumbs,dict) else '')
            if thumb: row['thumbnail']=str(thumb)
            if _youtube_video_available_in_us(vd):
                row['verifiedPlayable']=True; row['embedValidated']=True; row['externalOnly']=False; row['embedValidation']='videos.list'
            else:
                row['verifiedPlayable']=False; row['embedValidated']=False; row['externalOnly']=True; row['embedValidation']='videos.list-rejected'
        else:
            meta=_youtube_oembed_probe(vid)
            # oEmbed proves that public metadata exists; it does NOT prove that the
            # owner allows iframe playback. Only videos.list or a successful runtime
            # player session may promote a historical asset to VERIFIED.
            row['verifiedPlayable']=False; row['embedValidated']=False; row['externalOnly']=True; row['validationState']='CANDIDATE'
            row['embedValidation']='oembed-metadata-only' if meta else 'unverified'
            if meta:
                if meta.get('author_name'): row['source']=row['sourceLabel']=str(meta.get('author_name'))
                if not row.get('title') and meta.get('title'): row['title']=str(meta.get('title'))
                if not row.get('thumbnail') and meta.get('thumbnail_url'): row['thumbnail']=str(meta.get('thumbnail_url'))
        checked.append(_decorate_recap_tier(row))
    return checked


def _youtube_id_from_url(value):
    text=html.unescape(str(value or '')).replace('\\u0026','&')
    for pattern in (
        r'(?:youtube\.com/watch\?(?:[^#\s<>]*&)?v=)([A-Za-z0-9_-]{11})',
        r'(?:youtu\.be/)([A-Za-z0-9_-]{11})',
        r'(?:youtube\.com/(?:embed|shorts)/)([A-Za-z0-9_-]{11})',
    ):
        m=re.search(pattern,text,re.I)
        if m: return m.group(1)
    return ''


def _search_engine_youtube_links(query,max_results=18):
    """Find public YouTube watch URLs without touching YouTube search.list.

    YouTube's own HTML results page can return only a consent/client shell on
    Android/Termux. Bing's RSS endpoint is a useful zero-key index fallback, with
    DuckDuckGo HTML as a second lane. We only keep YouTube IDs; oEmbed and the
    browser iframe remain the playback gates.
    """
    query=str(query or '').strip()
    if not query: return []
    rows=[]; seen=set()

    def add(url,title='',description='',engine=''):
        vid=_youtube_id_from_url(url)
        if not vid or vid in seen: return
        seen.add(vid)
        rows.append({'videoId':vid,'url':str(url or ''),'title':html.unescape(re.sub(r'<[^>]+>',' ',str(title or ''))).strip(),
                     'description':html.unescape(re.sub(r'<[^>]+>',' ',str(description or ''))).strip(),'engine':engine})

    # RSS avoids script rendering and tends to be considerably lighter than a
    # normal search result page on a phone connection.
    try:
        url='https://www.bing.com/search?'+urlencode({'q':query,'format':'rss','count':max(10,min(30,max_results*2))})
        req=Request(url,headers={'User-Agent':'Mozilla/5.0 SportsBigBoard/4.0.2','Accept':'application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.5','Accept-Language':'en-US,en;q=0.9'})
        with urlopen(req,timeout=9) as resp:
            blob=resp.read(1_500_000)
        root=ET.fromstring(blob)
        for node in root.findall('.//item'):
            add(node.findtext('link') or '',node.findtext('title') or '',node.findtext('description') or '','bing-rss')
            if len(rows)>=max_results: break
    except Exception as exc:
        print(f'[SBB history search] Bing RSS failed {query}: {type(exc).__name__}: {exc}',flush=True)

    if len(rows)<max_results:
        try:
            url='https://html.duckduckgo.com/html/?'+urlencode({'q':query})
            req=Request(url,headers={'User-Agent':'Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 Chrome/151 Mobile Safari/537.36','Accept-Language':'en-US,en;q=0.9'})
            with urlopen(req,timeout=9) as resp:
                text=resp.read(1_500_000).decode('utf-8','ignore')
            for m in re.finditer(r'<a[^>]+class=["\'][^"\']*result__a[^"\']*["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',text,re.I|re.S):
                href=html.unescape(m.group(1)); title=m.group(2)
                if href.startswith('//'): href='https:'+href
                try:
                    parsed=urlparse(href)
                    if 'duckduckgo.com' in parsed.netloc and parsed.path.startswith('/l/'):
                        href=unquote((parse_qs(parsed.query).get('uddg') or [''])[-1]) or href
                except Exception: pass
                add(href,title,'','duckduckgo-html')
                if len(rows)>=max_results: break
        except Exception as exc:
            print(f'[SBB history search] DuckDuckGo failed {query}: {type(exc).__name__}: {exc}',flush=True)
    return rows[:max_results]


def _historical_search_engine_youtube_results(league,date,away,home,max_items=14):
    """Quota-independent historical YouTube rescue through normal web indexes.

    This covers cases where search.list is unavailable while official uploads still
    exist. Web-index/oEmbed hits are candidate evidence only; videos.list or a later
    runtime success is required before the score ribbon can advertise playback.
    """
    league=str(league or '').upper(); away=str(away or '').strip(); home=str(home or '').strip()
    if not league or not away or not home: return []
    try:
        d=datetime.strptime(str(date)[:10],'%Y-%m-%d')
        human=d.strftime('%B %d, %Y').replace(' 0',' ')
        year=str(d.year)
    except Exception:
        human=str(date or ''); year=str(date or '')[:4]
    a_token=_team_primary_youtube_token(away); h_token=_team_primary_youtube_token(home)
    queries=[
        f'site:youtube.com/watch "{away}" "{home}" {league} "full game highlights" "{human}"',
        f'site:youtube.com/watch "{away}" "{home}" {league} "game recap" "{human}"',
        f'site:youtube.com/watch "{away}" "{home}" {league} "game highlights" "{human}"',
        f'site:youtube.com/watch {a_token} {h_token} {league} "full game highlights" "{human}"',
        f'site:youtube.com/watch {a_token} {h_token} {league} highlights "{human}"',
        f'site:youtube.com/watch {a_token} {h_token} {league} recap {year}',
    ]
    if league in ('NFL','NBA','NHL'):
        queries.insert(0,f'site:youtube.com/watch "{away}" "{home}" {league} official highlights {str(date)[:10]}')
    raw=[]; seen=set()
    for query in queries:
        for row in _search_engine_youtube_links(query,max_results=16):
            vid=str(row.get('videoId') or '')
            if not vid or vid in seen: continue
            seen.add(vid); raw.append(row)
            if len(raw)>=36: break
        if len(raw)>=36: break

    league_names={'MLB':['mlb','major league baseball'],'NFL':['nfl','national football league'],'NBA':['nba','national basketball association'],'NHL':['nhl','national hockey league'],'EPL':['premier league'],'MLS':['mls','major league soccer']}
    team_tokens=set(_team_search_tokens(away)+_team_search_tokens(home))
    out=[]
    for idx,row in enumerate(raw):
        vid=str(row.get('videoId') or '')
        meta=_youtube_oembed_probe(vid,timeout=6)
        if not meta: continue
        title=str(meta.get('title') or row.get('title') or '').strip()
        author=str(meta.get('author_name') or '').strip()
        desc=str(row.get('description') or '').strip()
        if _youtube_match_strength(title,desc,away,home)<2: continue
        txt=f'{title} {desc}'.lower(); chl=author.lower()
        if re.search(r'podcast|reaction|reacts|preview|prediction|rumou?r|press conference|interview|betting|fantasy',txt): continue
        official=any(x in chl for x in league_names.get(league,[])) or any(t in chl for t in team_tokens if len(t)>3) or 'official' in chl
        broadcast=bool(re.search(r'espn|fox sports|nbc sports|cbs sports|sportsnet|nfl network|nba tv|nhl network|mlb network|apple tv|mls season pass|tnt sports',chl))
        if not (official or broadcast): continue
        overview=bool(re.search(r'full game highlights|extended.*highlights|game highlights|game recap|game summary|condensed game|full match highlights|match highlights|match recap',txt))
        if not overview and re.search(r'highlight|recap',txt): overview=True
        item={
            'id':f'yt-index-history-{league.lower()}-{vid}','eventId':vid,'youtubeId':vid,'league':league,
            'title':title,'description':desc,'duration':0,'durationSeconds':0,'thumbnail':str(meta.get('thumbnail_url') or ''),
            'source':author or league,'sourceLabel':author or league,'sourceType':'public-search-index-history','provider':'YOUTUBE',
            'verifiedPlayable':False,'embedValidated':False,'externalOnly':True,'validationState':'CANDIDATE','embedValidation':'oembed-metadata-only+public-search-index',
            'overview':overview,'programType':'recap' if overview else 'reel','externalUrl':f'https://www.youtube.com/watch?v={vid}',
            'chronology':[1,999,0,idx,idx],'importance':94 if overview else 58,'rapid':True,'away':away,'home':home,'date':str(date)[:10],
            'discoveryEngine':str(row.get('engine') or 'web-index')
        }
        out.append(annotate_media_tier(item))
        if len(out)>=max_items: break
    # Batch-validation is independent of search.list. If videos.list is available,
    # public-index candidates can become legitimate in-app assets. Otherwise they
    # stay catalog candidates and never paint a green score-card rail.
    key=read_youtube_key(); ids=[str(x.get('youtubeId') or '') for x in out if x.get('youtubeId')]
    if key and ids:
        try:
            details=youtube_fetch_json(f"{YOUTUBE_API_BASE}/videos?{urlencode({'part':'snippet,contentDetails,status','id':','.join(ids[:50]),'key':key})}",timeout=10)
            by_id={str(x.get('id') or ''):x for x in (details.get('items') or []) if isinstance(x,dict)}
            for item in out:
                vd=by_id.get(str(item.get('youtubeId') or ''))
                if not vd: continue
                sn=vd.get('snippet') or {}; dur=_iso8601_duration_seconds((vd.get('contentDetails') or {}).get('duration')) or 0
                if sn.get('title'): item['title']=str(sn.get('title'))
                if sn.get('channelTitle'): item['source']=item['sourceLabel']=str(sn.get('channelTitle'))
                if dur: item['duration']=item['durationSeconds']=dur
                if _youtube_video_available_in_us(vd):
                    item['verifiedPlayable']=True; item['embedValidated']=True; item['externalOnly']=False; item['validationState']='VERIFIED'; item['embedValidation']='public-index+videos.list'
        except Exception as exc:
            print(f'[SBB history YouTube] public-index validation deferred {league} {away}@{home}: {type(exc).__name__}: {exc}',flush=True)
    return [_decorate_recap_tier(x) for x in out]


def generic_rapid_team_videos(league, date, away, home, event_id="", force_refresh=False, allow_youtube=True):
    """Search official/team/broadcast video sources for one cross-sport matchup.

    YouTube is the richest source when a Data API key is configured, but ESPN is
    deliberately independent. A missing/rate-limited YouTube key must not turn an
    otherwise discoverable NFL recap into "no video".
    """
    league=str(league or '').upper(); away=str(away or '').strip(); home=str(home or '').strip()
    if not league or not away or not home: return []
    if _history_focus_active() and str(date or '')[:10] >= _date_iso(-1):
        allow_youtube=False
    path=_generic_rapid_cache_path(league,date,away,home)
    if not force_refresh:
        try:
            payload=json.loads(path.read_text(encoding='utf-8'))
            cached_rows=payload.get('data') if isinstance(payload.get('data'),list) else []
            # YouTube ids are durable; direct ESPN/club media URLs may be signed, so
            # refresh those periodically even for an old final game.
            has_native=any(isinstance(x,dict) and x.get('mediaUrl') for x in cached_rows)
            has_playable=any(isinstance(x,dict) and x.get('verifiedPlayable') and (x.get('mediaUrl') or x.get('youtubeId')) for x in cached_rows)
            # Empty/degraded historical searches are short-lived. v2.8.2 could cache
            # an empty NBA result for 30 days after one transient YouTube failure,
            # effectively poisoning that game until the cache was manually deleted.
            cache_ttl=300 if str(date)==_date_iso(0) else (6*60*60 if has_native else (7*24*60*60 if has_playable else 20*60))
            if time.time()-float(payload.get('savedAt',0))<cache_ttl and isinstance(payload.get('data'),list): return payload['data']
        except Exception: pass

    out=[]
    historical=str(date or '')[:10] < _date_iso(0)
    historical_web_error=None
    historical_api_error=None
    if league=='NFL':
        # Highest-confidence path: the exact ESPN game-id already present on the
        # score event. It returns direct MP4/HLS assets and does not use YouTube.
        if event_id:
            out.extend(_espn_event_video_results(event_id,league,away,home,max_items=16))
        # Keep the official NFL YouTube feed as another discovery lane, but its
        # uploads remain external until embed permission is positively validated.
        if allow_youtube:
            out.extend(_official_nfl_feed_videos(date,away,home))
    # Historical dates use public YouTube search-page metadata plus oEmbed
    # validation. This avoids consuming the separate YouTube search.list call
    # bucket and is the critical path for old NBA/NFL/NHL games. Current/recent discovery keeps
    # the Data API lane because freshness and richer metadata matter more there.
    if allow_youtube and historical:
        # Primary historical YouTube lane: scan the verified official channel's
        # activity feed for this date, then batch videos.list validation. This does
        # not consume the separate search.list bucket and is shared by every game
        # in the league/day through a durable cache.
        try:
            out.extend(_official_youtube_history_activity_results(league,date,away,home,max_items=18,force=force_refresh))
        except Exception as exc:
            historical_web_error=exc
            print(f'[SBB history YouTube] official activity lane deferred {league} {away}@{home}: {type(exc).__name__}: {exc}',flush=True)
        if not any(isinstance(x,dict) and x.get('verifiedPlayable') and (x.get('youtubeId') or x.get('mediaUrl')) for x in out):
            try: out.extend(_historical_youtube_web_results(league,date,away,home,max_items=14))
            except Exception as exc:
                historical_web_error=historical_web_error or exc
                print(f'[SBB history YouTube] web discovery failed {league} {away}@{home}: {type(exc).__name__}: {exc}',flush=True)
        # YouTube's results page frequently returns only a consent/client shell to
        # Termux. Search normal public indexes next; this costs no YouTube API quota
        # and still resolves to exact YouTube IDs that oEmbed/runtime can validate.
        if not any(isinstance(x,dict) and x.get('verifiedPlayable') and (x.get('youtubeId') or x.get('mediaUrl')) for x in out):
            try:
                out.extend(_historical_search_engine_youtube_results(league,date,away,home,max_items=14))
            except Exception as exc:
                if historical_web_error is None: historical_web_error=exc
                print(f'[SBB history YouTube] public-index discovery failed {league} {away}@{home}: {type(exc).__name__}: {exc}',flush=True)
        # Only after both zero-quota lanes fail do we spend one tightly scoped
        # official-channel search.list request. A global live-search cooldown no
        # longer prevents the zero-quota historical lanes above from doing useful work.
        if not any(isinstance(x,dict) and x.get('verifiedPlayable') and (x.get('youtubeId') or x.get('mediaUrl')) for x in out):
            try:
                out.extend(_official_youtube_history_api_results(league,date,away,home,max_items=18))
            except Exception as exc:
                historical_api_error=exc
                print(f'[SBB history YouTube] official-channel rescue failed {league} {away}@{home}: {type(exc).__name__}: {exc}',flush=True)
    key=read_youtube_key() if (allow_youtube and not historical) else None
    if key:
        try:
            try: d=datetime.strptime(date,'%Y-%m-%d').replace(tzinfo=timezone.utc)
            except Exception: d=datetime.now(timezone.utc)
            base={'part':'snippet','type':'video','maxResults':'16','order':'date','videoEmbeddable':'true','videoSyndicated':'true',
                    'safeSearch':'moderate','regionCode':'US','relevanceLanguage':'en','publishedAfter':(d-timedelta(hours=6)).isoformat().replace('+00:00','Z'),
                    'publishedBefore':(d+timedelta(days=2,hours=12)).isoformat().replace('+00:00','Z'),'key':key}
            rows=[]
            queries=[f'{away} {home} {league} highlights', f'{away} {home} {league} recap']
            if league=='NFL':
                # NFL's official YouTube titles often omit the word "highlights"
                # entirely, e.g. "49ers vs. Chargers | 2026 Preseason Week 2".
                # Search the title shape the league actually publishes.
                year=str(date)[:4]
                queries += [f'{away} vs {home} {year} preseason week', f'{away} {home} NFL game highlights']
            if league in ('MLS','EPL'):
                queries += [f'{away} {home} full match highlights', f'{away} {home} match highlights', f'{away} {home} MLS highlights' if league=='MLS' else f'{away} {home} Premier League highlights', f'{away} {home} goals highlights']
            for query in queries:
                params=dict(base); params['q']=query
                search=youtube_fetch_json(f"{YOUTUBE_API_BASE}/search?{urlencode(params)}",timeout=10)
                rows.extend(search.get('items') or [])
            dedup_rows=[]; seen_vid=set()
            for row in rows:
                vid=str((row.get('id') or {}).get('videoId') or '')
                if not vid or vid in seen_vid: continue
                seen_vid.add(vid); dedup_rows.append(row)
            rows=dedup_rows[:36]
            ids=[str((x.get('id') or {}).get('videoId') or '') for x in rows]; ids=[x for x in ids if x]
            details={'items':[]}
            if ids:
                details=youtube_fetch_json(f"{YOUTUBE_API_BASE}/videos?{urlencode({'part':'snippet,contentDetails,status,statistics','id':','.join(ids[:50]),'key':key})}",timeout=10)
            detail_by={str(x.get('id')):x for x in details.get('items') or []}
            team_tokens=set(_team_search_tokens(away)+_team_search_tokens(home))
            league_names={'MLB':['mlb','major league baseball'],'NFL':['nfl','national football league'],'NBA':['nba','national basketball association'],'NHL':['nhl','national hockey league'],'EPL':['premier league'],'MLS':['mls','major league soccer']}
            for idx,sr in enumerate(rows):
                vid=str((sr.get('id') or {}).get('videoId') or ''); vd=detail_by.get(vid) or {}; sn=vd.get('snippet') or sr.get('snippet') or {}
                if vd and not _youtube_video_available_in_us(vd): continue
                title=str(sn.get('title') or '').strip(); desc=str(sn.get('description') or '').strip(); ch=str(sn.get('channelTitle') or '').strip(); txt=(title+' '+desc).lower(); chl=ch.lower()
                match_strength=_youtube_match_strength(title,desc,away,home)
                if match_strength<2: continue
                official=any(x in chl for x in league_names.get(league,[])) or any(t in chl for t in team_tokens if len(t)>3) or 'official' in chl
                broadcast=bool(re.search(r'espn|fox sports|nbc sports|cbs sports|sportsnet|nfl network|nba tv|nhl network|mlb network|apple tv|mls season pass|local|news|tv',chl))
                if not (official or broadcast): continue
                if re.search(r'podcast|reaction|reacts|preview|prediction|rumou?r|press conference|interview|betting|fantasy',txt): continue
                dur=_iso8601_duration_seconds((vd.get('contentDetails') or {}).get('duration')) or 0
                max_duration=1500 if league in ('NFL','NBA','NHL') else (1200 if league in ('MLS','EPL') else 900)
                if dur and (dur<10 or dur>max_duration): continue
                nfl_official_package=(league=='NFL' and official and match_strength>=2 and (re.search(r'\bpreseason\b|\bweek\s*\d+\b',txt,re.I) or 'highlight' in txt) and (not dur or dur>=90))
                overview=bool(re.search(r'full game highlights|game highlights|game recap|game summary|condensed game|full match highlights|match highlights|match recap',txt)) or nfl_official_package or bool(dur and 120<=dur<=420 and re.search(r'\b(win|wins|victory|defeat|beats|leads?)\b',txt))
                thumb=(((sn.get('thumbnails') or {}).get('high') or (sn.get('thumbnails') or {}).get('medium') or {}).get('url') or '')
                row={'id':f'rapid-{league.lower()}-{vid}','eventId':vid,'youtubeId':vid,'league':league,'title':title,'description':desc,
                            'duration':dur,'durationSeconds':dur,'thumbnail':thumb,'source':ch or 'YouTube','sourceLabel':ch or 'YouTube','sourceType':'official-team-social-video',
                            'provider':'YOUTUBE','verifiedPlayable':True,'embedValidated':True,'validationState':'VERIFIED','overview':overview,'programType':'recap' if overview else 'reel',
                            'externalUrl':f'https://www.youtube.com/watch?v={vid}',
                            'chronology':[1,999,0,idx,idx],'importance':68 if overview else 35,'rapid':True,'away':away,'home':home,'date':date,
                            'publishedAt':str(sn.get('publishedAt') or '')}
                out.append(_decorate_recap_tier(row))
        except Exception as exc:
            # Preserve ESPN as an independent fallback even when YouTube search is
            # quota-limited, unconfigured, or temporarily unavailable.
            if not isinstance(exc,YouTubeRateLimited):
                print(f'[SBB rapid] {league} YouTube search failed {away}@{home}: {type(exc).__name__}: {exc}',flush=True)

    try:
        out.extend(_espn_search_video_results(league,away,home,max_items=8))
    except Exception as exc:
        print(f'[SBB ESPN] rapid enrichment failed {league} {away}@{home}: {type(exc).__name__}: {exc}',flush=True)

    # NFL club sites are the no-quota guarantee of last resort. Do not spend two
    # extra page fetches when ESPN or another source already supplied playable
    # media, but never let a completed NFL game collapse to "no highlights" just
    # because YouTube embedding/search is unavailable.
    if league=='NFL' and not any(x.get('verifiedPlayable') and (x.get('mediaUrl') or x.get('youtubeId')) for x in out):
        out.extend(_nfl_team_site_video_results(date,away,home,max_items=8))

    # Keep a tier-diverse catalog rather than only the single longest recap. The
    # history database needs QUICK + EXTENDED + COMMENTARY + MOMENTS when those
    # packages exist so a revisited date can populate every recap rail instantly.
    prepared=[annotate_media_tier(x) for x in out if isinstance(x,dict)]
    if historical:
        verified_at=time.time()
        for row in prepared:
            if row.get('verifiedPlayable') and (row.get('youtubeId') or row.get('mediaUrl')):
                row['historyVerifiedAt']=verified_at
                row['historyDiscoveryVersion']=HISTORY_DISCOVERY_VERSION
    prepared.sort(key=lambda x:(
        bool(x.get('verifiedPlayable')),
        bool(x.get('mediaUrl')) or bool(x.get('embedValidated')),
        HISTORY_TIER_PRIORITY.get(str(x.get('recapTier') or 'blue'),0),
        bool(x.get('overview')),
        int(x.get('importance') or 0),
        -abs(int(x.get('durationSeconds') or 0)-210) if str(x.get('recapTier'))=='green' else int(x.get('durationSeconds') or 0)
    ),reverse=True)
    dedup=[]; seen=set(); tier_kept=set()
    # First guarantee one representative of every discovered tier.
    for wanted in HISTORY_TIER_ORDER:
        for row in prepared:
            if str(row.get('recapTier') or 'blue')!=wanted: continue
            key_id=str(row.get('youtubeId') or row.get('mediaUrl') or row.get('externalUrl') or row.get('id') or '')
            if not key_id or key_id in seen: continue
            seen.add(key_id); dedup.append(row); tier_kept.add(wanted); break
    for row in prepared:
        key_id=str(row.get('youtubeId') or row.get('mediaUrl') or row.get('externalUrl') or row.get('id') or '')
        if not key_id or key_id in seen: continue
        seen.add(key_id); dedup.append(row)
        if len(dedup)>=18: break
    playable_now=any(x.get('verifiedPlayable') and (x.get('youtubeId') or x.get('mediaUrl')) for x in dedup if isinstance(x,dict))
    # A transport failure is not a completed historical search. Preserve the
    # ESPN/NFL-feed evidence already stored by the caller, but do not cache this
    # result or let the history catalog mark the event permanently searched.
    if historical and not playable_now and (historical_api_error is not None or historical_web_error is not None):
        err=historical_api_error or historical_web_error
        if isinstance(err,YouTubeRateLimited): raise err
        raise RuntimeError(str(err))
    try: path.write_text(json.dumps({'savedAt':time.time(),'data':dedup},ensure_ascii=False),encoding='utf-8')
    except Exception: pass
    return dedup

def normalized_rapid_highlights(date, force_refresh=False, force_clips=False):
    """Return rapidly available official highlight media for started MLB games.

    MLB game-content is always checked first. When there is no good recap/reel yet,
    trusted official-team/broadcast YouTube results can supplement the blue reel.
    A later full recap naturally outranks these clips in the browser programming model.
    """
    if not force_refresh and not force_clips:
        cached=_read_rapid_cache(date)
        if cached is not None: return cached
    sched=fetch_json(f"{MLB_STATS_BASE}/schedule?sportId=1&date={date}&hydrate=team",timeout=7)
    games=[]
    for block in sched.get('dates',[]): games.extend(block.get('games',[]))
    started=[g for g in games if g.get('gamePk') and _game_has_started(g)]
    results=[]
    def work(g):
        native=_game_content_result(g,date)
        items=list(native.get('allItems') or native.get('items') or native.get('candidates') or [])
        # Force Blue is a dedicated clips-only diagnostic/programming path. Even if
        # a polished recap exists, continue looking at official team/league/ESPN
        # individual moments rather than letting recap availability suppress discovery.
        has_recap=any(x.get('overview') for x in items)
        away=((g.get('teams') or {}).get('away') or {}).get('team') or {}; home=((g.get('teams') or {}).get('home') or {}).get('team') or {}
        if force_clips or (not has_recap and len(items)<3):
            items.extend(_official_team_youtube_clips(g,date,max_items=7 if force_clips else 5))
            items.extend(_espn_search_video_results('MLB',away.get('name') or '',home.get('name') or '',max_items=7 if force_clips else 5))
        if force_clips:
            plays=[x for x in items if not x.get('overview')]
            reel=_select_chronological_reel(plays,min_clips=1,max_clips=8)
            items=[]
            for i,item in enumerate(reel):
                item=dict(item); item['programType']='reel'; item['overview']=False; item['reelIndex']=i+1; item['reelCount']=len(reel); item['rapid']=True; item['forceBlueClip']=True
                items.append(item)
        # Normal mode only builds a blue reel when no suitable recap exists.
        elif not any(x.get('overview') for x in items):
            plays=[x for x in items if not x.get('overview')]
            reel=_select_chronological_reel(plays,min_clips=2,max_clips=7)
            if reel:
                items=[]
                for i,item in enumerate(reel):
                    item=dict(item); item['programType']='reel'; item['overview']=False; item['reelIndex']=i+1; item['reelCount']=len(reel); item['rapid']=True
                    items.append(item)
        for x in items:
            x['rapid']=True
            x.setdefault('gamePk',str(g.get('gamePk') or ''))
            x.setdefault('date',date)
            x.setdefault('verifiedPlayable',bool(x.get('mediaUrl') or x.get('youtubeId')))
        return items
    with ThreadPoolExecutor(max_workers=min(4,max(1,len(started)))) as ex:
        futs=[ex.submit(work,g) for g in started]
        for fut in as_completed(futs):
            try: results.extend(fut.result() or [])
            except Exception as exc: print(f'[SBB rapid] worker failed: {type(exc).__name__}: {exc}',flush=True)
    # Deduplicate by game/media identity.
    unique=[]; seen=set()
    for x in results:
        sig=(str(x.get('gamePk') or ''),str(x.get('mediaUrl') or x.get('youtubeId') or x.get('id') or ''))
        if sig in seen: continue
        seen.add(sig); unique.append(x)
    if not force_clips:
        _write_rapid_cache(date,unique)
    return unique

def fetch_json(url, timeout=15):
    req = Request(url, headers={"Accept":"application/json", "User-Agent":"SportsBigBoard/4.0.2"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def duration_seconds(value):
    if value is None: return None
    if isinstance(value, (int,float)): return int(value)
    text=str(value).strip()
    if text.isdigit(): return int(text)
    parts=text.split(":")
    try:
        nums=[int(x) for x in parts]
        if len(nums)==2: return nums[0]*60+nums[1]
        if len(nums)==3: return nums[0]*3600+nums[1]*60+nums[2]
    except Exception:
        pass
    return None

def best_playback(item):
    """Return a direct MP4 rendition only.

    MLB content often exposes both HLS manifests and MP4 renditions. Chrome on
    Android is much more reliable for our localhost player when we stream an
    MP4 through the local proxy, so HLS-only items are not marked playable.
    """
    plays=item.get("playbacks") or item.get("playback") or []
    if isinstance(plays, dict): plays=[plays]
    ranked=[]
    for pb in plays:
        if not isinstance(pb, dict): continue
        url=pb.get("url") or pb.get("href")
        if not url: continue
        name=str(pb.get("name") or pb.get("type") or "").lower()
        low=url.lower()
        if "mp4" not in name and ".mp4" not in low:
            continue
        score=100
        if any(token in name for token in ("high","720","1080","4000k","avc")): score += 30
        if any(token in name for token in ("1280","1920")): score += 10
        ranked.append((score,url))
    ranked.sort(reverse=True)
    return ranked[0][1] if ranked else ""

def best_image(item):
    image=item.get("image") or {}
    cuts=image.get("cuts") if isinstance(image,dict) else []
    if isinstance(cuts,dict): cuts=list(cuts.values())
    best=(0,"")
    for cut in cuts or []:
        if not isinstance(cut,dict): continue
        src=cut.get("src") or cut.get("url")
        if not src: continue
        area=(cut.get("width") or 0)*(cut.get("height") or 0)
        if area>best[0]: best=(area,src)
    if best[1]: return best[1]
    if isinstance(image,dict): return image.get("src") or image.get("url") or ""
    return ""

def collect_content_items(content):
    """Collect likely MLB video objects from both known and nested content nodes.

    MLB's game-content payload has changed shape over time. Recaps often appear in
    highlights.* while individual play videos can live deeper in media/epg and
    other nested collections. We keep the known paths, then recursively collect
    dicts that actually expose playback renditions.
    """
    out=[]
    seen=set()

    def add(item):
        if not isinstance(item,dict): return
        plays=item.get("playbacks") or item.get("playback")
        if not plays: return
        ident=str(item.get("id") or item.get("guid") or item.get("slug") or "")
        if not ident:
            ident=str((best_playback(item) or "")[:220])
        if not ident or ident in seen: return
        seen.add(ident); out.append(item)

    highlights=content.get("highlights") or {}
    for key in ("highlights","live","scoreboard"):
        node=highlights.get(key) or {}
        items=node.get("items") if isinstance(node,dict) else None
        if isinstance(items,list):
            for item in items: add(item)

    media=content.get("media") or {}
    if isinstance(media,dict):
        for key in ("epg","epgAlternate","milestones"):
            groups=media.get(key) or []
            if isinstance(groups,dict): groups=list(groups.values())
            if isinstance(groups,list):
                for group in groups:
                    if isinstance(group,dict):
                        items=group.get("items") or group.get("media") or []
                        if isinstance(items,list):
                            for item in items: add(item)

    # Shape-tolerant final pass. Limit recursion depth to avoid walking huge
    # unrelated metadata trees forever.
    def walk(node, depth=0):
        if depth>7: return
        if isinstance(node,dict):
            if node.get("playbacks") or node.get("playback"): add(node)
            for value in node.values():
                if isinstance(value,(dict,list)): walk(value,depth+1)
        elif isinstance(node,list):
            for value in node: walk(value,depth+1)
    walk(content)
    return out

def _keyword_map(raw):
    out={}
    kws=raw.get("keywords") or raw.get("keywordsAll") or []
    if isinstance(kws, dict):
        kws=list(kws.values())
    for kw in kws if isinstance(kws,list) else []:
        if not isinstance(kw,dict): continue
        key=str(kw.get("type") or kw.get("name") or kw.get("key") or "").lower()
        value=kw.get("value") or kw.get("displayName") or kw.get("display")
        if key and value is not None: out[key]=str(value)
    return out

def _clip_chronology(raw, source_index):
    """Best-effort baseball chronology. Unknown metadata preserves source order."""
    kw=_keyword_map(raw)
    text=" ".join(str(raw.get(k) or "") for k in ("title","headline","description","blurb")).lower()

    inning=None
    for key,value in kw.items():
        if "inning" in key:
            m=re.search(r"\d+", value)
            if m:
                inning=int(m.group()); break
    if inning is None:
        m=re.search(r"(?:top|bottom|bot)\s+(?:of\s+)?(?:the\s+)?(\d+)(?:st|nd|rd|th)?", text)
        if not m: m=re.search(r"(\d+)(?:st|nd|rd|th)\s+inning", text)
        if m: inning=int(m.group(1))

    half=0
    half_text=" ".join(kw.values()).lower()+" "+text
    if "bottom" in half_text or re.search(r"\bbot\b",half_text): half=1

    event_order=None
    for key,value in kw.items():
        if any(token in key for token in ("atbat","at_bat","play","event")):
            m=re.search(r"\d+", value)
            if m:
                event_order=int(m.group()); break

    # Known inning clips come first and sort by inning/half. Unknowns retain feed order.
    if inning is not None:
        return [0, inning, half, event_order if event_order is not None else source_index, source_index]
    return [1, 999, 0, source_index, source_index]

def _clip_importance(raw, title, desc):
    """Score how useful an individual play is for telling the story of a game."""
    text=(str(title)+" "+str(desc)).lower()
    score=10
    weighted=(
        (45,("walk-off","walkoff")),
        (40,("grand slam",)),
        (36,("go-ahead","go ahead","game-winning","game winning")),
        (32,("game-tying","game tying","ties the game","ties it")),
        (30,("home run","homers","homer ","homerun")),
        (25,("three-run","3-run","two-run","2-run")),
        (23,("scores","rbi","drives in","plates")),
        (20,("double","triple")),
        (18,("diving catch","robs","robbery","great catch","spectacular catch")),
        (16,("strikeout","strikes out","save","closes out")),
        (12,("single","stolen base","steals")),
    )
    for points,words in weighted:
        if any(w in text for w in words): score=max(score,points)
    kw=_keyword_map(raw)
    # Later high-leverage innings get a small bump, but chronology remains the
    # primary playback order rather than the selection order.
    inning=None
    for key,value in kw.items():
        if "inning" in key:
            m=re.search(r"\d+",str(value))
            if m: inning=int(m.group()); break
    if inning is not None and inning>=7: score += 5
    return score


def _select_chronological_reel(items, min_clips=3, max_clips=7):
    """Choose a concise set of meaningful plays, then sort them chronologically."""
    if not items: return []
    # A "reel" must actually contain multiple moments. A lone play remains a
    # candidate for the future More drawer, but is not promoted as automatic
    # game coverage.
    if len(items) < max(1, min_clips): return []
    # Deduplicate same underlying media/title first.
    unique=[]; seen=set()
    for item in items:
        sig=(item.get("mediaUrl") or "", re.sub(r"\W+","",str(item.get("title") or "").lower())[:100])
        if sig in seen: continue
        seen.add(sig); unique.append(item)
    if len(unique) < max(1, min_clips):
        return []
    if len(unique)<=max_clips:
        selected=unique
    else:
        ranked=sorted(unique,key=lambda x:(x.get("importance",0), source_index_hint(x)), reverse=True)
        selected=ranked[:max_clips]
        # If importance scoring produced too few meaningful plays, fill from the
        # chronological feed so the reel still tells a coherent game story.
        if len(selected)<min_clips:
            used={x.get("id") for x in selected}
            for item in unique:
                if item.get("id") not in used:
                    selected.append(item); used.add(item.get("id"))
                if len(selected)>=min_clips: break
    return sorted(selected,key=lambda x:tuple(x.get("chronology") or [1,999,0,0,0]))


def source_index_hint(item):
    c=item.get("chronology") or [1,999,0,0,0]
    try: return -int(c[-1])
    except Exception: return 0


def _game_content_result(game, date):
    gamepk=game.get("gamePk")
    try:
        content=fetch_json(f"{MLB_STATS_BASE}/game/{gamepk}/content", timeout=8)
    except Exception as exc:
        return {"items":[],"error":f"{type(exc).__name__}: {exc}","gamePk":str(gamepk),"kind":"error"}
    away_node=((game.get("teams") or {}).get("away") or {}); home_node=((game.get("teams") or {}).get("home") or {})
    away=away_node.get("team") or {}; home=home_node.get("team") or {}
    away_score=away_node.get("score"); home_score=home_node.get("score")
    items=[]
    for source_index,raw in enumerate(collect_content_items(content)):
        media=best_playback(raw)
        if not media: continue
        title=str(raw.get("title") or raw.get("headline") or "MLB Highlight").strip()
        desc=str(raw.get("description") or raw.get("blurb") or raw.get("callToAction") or "").strip()
        dur=duration_seconds(raw.get("duration")); text=(title+" "+desc).lower()
        explicit_overview=bool(re.search(r"full game highlights|game recap|game highlights|condensed game|game story|game summary|game wrap|wrap[- ]?up|highlights from|story of the game", text))
        # MLB often publishes a concise 2–6 minute "story of the game" package whose
        # title is player-led (for example, "Ohtani's ... leads Dodgers' win") rather
        # than literally saying "game highlights". Treat those as recap candidates
        # when the description/title clearly describes the final game result.
        away_tokens=_team_search_tokens(away.get("name") or "")
        home_tokens=_team_search_tokens(home.get("name") or "")
        teams_in_text=any(t in text for t in away_tokens if len(t)>2) and any(t in text for t in home_tokens if len(t)>2)
        final_score_in_text=(away_score is not None and home_score is not None and (f"{away_score}-{home_score}" in text or f"{home_score}-{away_score}" in text))
        result_language=bool(re.search(r"\b(?:win|wins|won|victory|defeat|defeats|beat|beats|lead|leads|led)\b", text))
        # Because this is the exact MLB game-content endpoint, a 90–420 second result-story
        # clip is strong full-recap evidence even when the title is player-led and only
        # names one club. Individual play clips are normally much shorter.
        concise_story=bool(dur and 90 <= dur <= 420 and result_language and (teams_in_text or final_score_in_text or dur>=120))
        overview=explicit_overview or concise_story
        chronology=_clip_chronology(raw,source_index)
        items.append({
            "id":f"mlb-{gamepk}-{raw.get('id') or raw.get('guid') or source_index}",
            "gamePk":str(gamepk),"date":date,
            "away":away.get("name") or "Away","awayId":away.get("id"),
            "home":home.get("name") or "Home","homeId":home.get("id"),
            "awayScore":away_score,"homeScore":home_score,
            "title":title,"description":desc,"duration":dur,"overview":overview,
            "chronology":chronology,"importance":_clip_importance(raw,title,desc),
            "mediaUrl":media,"thumbnail":best_image(raw),"source":"MLB Stats API","sourceType":"mlb-game-content",
            "publishedAt": raw.get("date") or raw.get("timestamp") or raw.get("releaseDate") or raw.get("mediaDate") or raw.get("createdAt") or raw.get("lastModifiedDate")
        })
    overviews=[x for x in items if x["overview"]]
    if overviews:
        def ovscore(x):
            dur=x.get("duration") or 0
            # Broadcast-style pacing: a concise 2–6 minute story beats a 12–13
            # minute condensed game when both cover the same final result.
            # Explicitly favor 3–4 minute game-summary clips as FULL RECAPS.
            if 180 <= dur <= 300: fit=175
            elif 150 <= dur <= 360: fit=165
            elif 120 <= dur < 150 or 360 < dur <= 480: fit=140
            elif 60 <= dur < 120 or 480 < dur <= 600: fit=105
            elif 600 < dur <= 900: fit=55
            elif dur > 900: fit=25
            else: fit=75
            text=x["title"].lower()
            title_score=58 if "full game highlights" in text else 54 if "game highlights" in text else 48 if "game recap" in text else 34 if "condensed game" in text else 44 if re.search(r"\b(?:win|wins|victory|defeat|beats|leads?)\b", text) else 24
            return fit+title_score
        best=max(overviews,key=ovscore)
        best["programType"]="recap"
        return {"items":[best],"allItems":items,"error":None,"gamePk":str(gamepk),"kind":"recap","candidateCount":len(items)}

    # No suitable recap: assemble a chronological reel from individual game moments.
    plays=[x for x in items if not x["overview"]]
    reel=_select_chronological_reel(plays, min_clips=3, max_clips=7)
    if reel:
        for i,item in enumerate(reel):
            item["programType"]="reel"
            item["reelIndex"]=i+1
            item["reelCount"]=len(reel)
        return {"items":reel,"error":None,"gamePk":str(gamepk),"kind":"reel","candidateCount":len(items)}
    return {"items":[],"candidates":plays,"error":None,"gamePk":str(gamepk),"kind":"none","candidateCount":len(items)}


def _run_stats_discovery(date):
    """Refresh every completed game and publish game-level coverage diagnostics."""
    try:
        sched=fetch_json(f"{MLB_STATS_BASE}/schedule?sportId=1&date={date}&hydrate=team", timeout=6)
        games=[]
        for d in sched.get("dates",[]): games.extend(d.get("games",[]))
        final_games=[g for g in games if str(((g.get("status") or {}).get("abstractGameState") or "")).lower()=="final" and g.get("gamePk")]
        total=len(final_games)
        update_coverage(date,status="SEARCHING",refreshing=True,total=total,completed=total,searched=0,found=0,playable=0,playableGames=0,recapGames=0,reelGames=0,missingGames=0,noSource=0,sourceErrors=0,sourceErrorGames=0,degradedPlayableGames=0,youtubeConfigured=bool(read_youtube_key()),youtubeSearched=0,youtubeFound=0,youtubeErrors=0,youtubeDone=False,message=f"Searching {total} completed MLB game(s)")

        all_items=[]; recap_games=0; reel_games=0; missing=0; source_errors=0; youtube_searched=0; youtube_found=0; youtube_errors=0
        def discover(game):
            native=_game_content_result(game,date)
            if native.get("kind") in ("recap","reel"):
                return native, False
            # Preserve any native individual candidates, then add trusted YouTube/team
            # discovery if MLB has not yet published enough material for a program.
            native_candidates=list(native.get("candidates") or [])
            yt=_youtube_game_result(game,date) if read_youtube_key() else {"items":[],"kind":"none","youtubeSkipped":"not-configured"}
            if yt.get("kind") in ("recap","reel"):
                return yt, True
            # Rapid team/official search deliberately allows team-only uploads that may
            # not mention both clubs in the title. They become blue media unless a recap exists.
            extra=_official_team_youtube_clips(game,date,max_items=7) if read_youtube_key() else []
            plays=native_candidates+[x for x in extra if not x.get("overview")]
            reel=_select_chronological_reel(plays,min_clips=2,max_clips=7)
            if reel:
                for i,item in enumerate(reel):
                    item=dict(item); item["programType"]="reel"; item["overview"]=False; item["reelIndex"]=i+1; item["reelCount"]=len(reel); reel[i]=item
                return {"items":reel,"kind":"reel","gamePk":str(game.get("gamePk") or ""),"error":native.get("error")}, True
            return {"items":[],"kind":"none","gamePk":str(game.get("gamePk") or ""),"error":native.get("error") or yt.get("error")}, True

        with ThreadPoolExecutor(max_workers=min(5,max(1,total))) as ex:
            futures={ex.submit(discover,g):g for g in final_games}
            searched=0
            for fut in as_completed(futures):
                searched+=1
                try:
                    result,used_youtube=fut.result()
                    if used_youtube: youtube_searched+=1
                    items=list(result.get("items") or [])
                    kind=result.get("kind") or "none"
                    if kind=="recap": recap_games+=1
                    elif kind=="reel": reel_games+=1
                    else: missing+=1
                    if result.get("error"): source_errors+=1
                    if used_youtube and items: youtube_found+=1
                    all_items.extend(items)
                except Exception as exc:
                    source_errors+=1; missing+=1
                    print(f"[SBB coverage] worker failed: {type(exc).__name__}: {exc}",flush=True)
                update_coverage(date,status="SEARCHING",refreshing=True,searched=searched,found=recap_games+reel_games,playable=len(all_items),playableGames=recap_games+reel_games,recapGames=recap_games,reelGames=reel_games,missingGames=missing,noSource=missing,sourceErrors=source_errors,sourceErrorGames=source_errors,youtubeSearched=youtube_searched,youtubeFound=youtube_found,youtubeErrors=youtube_errors,message=f"Coverage {searched}/{total} • {recap_games} recaps • {reel_games} reels")

        STATS_CACHE[date]=(time.time(),all_items)
        write_stats_disk_cache(date,all_items)
        # The moment discovery publishes a new recap/reel inventory, stage its
        # primary native media immediately instead of waiting for the next five-
        # minute background cadence. This is server-only byte preparation; it has
        # no authority over browser playback state.
        try: prewarm_server_media_for_date(date,18)
        except Exception as exc: print(f"[SBB media-cache] post-discovery prewarm warning: {type(exc).__name__}: {exc}",flush=True)
        status="READY" if missing==0 and source_errors==0 else "DEGRADED"
        update_coverage(date,status=status,refreshing=False,searched=total,found=recap_games+reel_games,playable=len(all_items),playableGames=recap_games+reel_games,recapGames=recap_games,reelGames=reel_games,missingGames=missing,noSource=missing,sourceErrors=source_errors,sourceErrorGames=source_errors,youtubeConfigured=bool(read_youtube_key()),youtubeSearched=youtube_searched,youtubeFound=youtube_found,youtubeErrors=youtube_errors,youtubeDone=True,message=f"Coverage complete • {recap_games} recaps • {reel_games} reels • {missing} missing")
    except Exception as exc:
        update_coverage(date,status="ERROR",refreshing=False,sourceErrors=int(coverage_state(date).get("sourceErrors",0))+1,message=f"MLB coverage refresh failed: {type(exc).__name__}: {exc}")
    finally:
        with DISCOVERY_LOCK: DISCOVERY_JOBS.pop(date,None)

def ensure_stats_discovery(date, force=False):
    with DISCOVERY_LOCK:
        job=DISCOVERY_JOBS.get(date)
        if job and job.is_alive(): return False
        # Only a currently running worker blocks a new worker. The caller decides
        # whether a refresh is warranted; this avoids the cache-load state marking
        # itself REFRESHING before a thread has actually been started.
        t=threading.Thread(target=_run_stats_discovery,args=(date,),daemon=True,name=f"sbb-coverage-{date}")
        DISCOVERY_JOBS[date]=t
        t.start()
        return True


def normalized_stats_highlights(date, force_refresh=False):
    """Return immediately available media, then refresh the full date in background."""
    now=time.time()
    cached=STATS_CACHE.get(date)
    data=None
    if cached:
        data=list(cached[1])
    else:
        disk_data,saved=read_stats_disk_cache(date,allow_stale=True)
        if disk_data is not None:
            data=list(disk_data)
            STATS_CACHE[date]=(saved or now,data)
            update_coverage(date,status="REFRESHING",cacheLoaded=True,cacheCount=len(data),playable=len(data),refreshing=True,message=f"Loaded {len(data)} cached item(s) • refreshing coverage in background")
    if data is None:
        data=[]
        update_coverage(date,status="REFRESHING",cacheLoaded=False,cacheCount=0,playable=0,refreshing=True,message="No warm cache • starting MLB coverage discovery")

    st=coverage_state(date)
    # Start a refresh if this process has not completed one yet, or when forced.
    if force_refresh or st.get("status") not in ("READY","DEGRADED") or not st.get("searched"):
        ensure_stats_discovery(date, force=force_refresh)
    return list(STATS_CACHE.get(date,(now,data))[1])


def cache_path(endpoint, flat):
    safe = endpoint + "__" + "__".join(f"{k}-{flat[k]}" for k in sorted(flat))
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", safe)
    return CACHE_DIR / f"{safe}.json"

def read_cached(endpoint, flat):
    path = cache_path(endpoint, flat)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("data"), float(payload.get("savedAt", 0))
    except Exception:
        return None, 0

def write_cached(endpoint, flat, data):
    path = cache_path(endpoint, flat)
    try:
        path.write_text(json.dumps({"savedAt": time.time(), "data": data}), encoding="utf-8")
    except Exception:
        pass

def normalized_stats_matches(date):
    sched=fetch_json(f"{MLB_STATS_BASE}/schedule?sportId=1&date={date}&hydrate=team,linescore")
    out=[]
    for block in sched.get("dates",[]):
        for g in block.get("games",[]):
            teams=g.get("teams") or {}
            away=((teams.get("away") or {}).get("team") or {})
            home=((teams.get("home") or {}).get("team") or {})
            away_score=(teams.get("away") or {}).get("score")
            home_score=(teams.get("home") or {}).get("score")
            status=g.get("status") or {}
            abstract=str(status.get("abstractGameState") or "")
            detailed=str(status.get("detailedState") or abstract)
            if abstract.lower()=="final": report="FINAL"
            elif abstract.lower()=="live": report=detailed or "LIVE"
            else: report=detailed or "SCHEDULED"
            def team_obj(t):
                tid=t.get("id")
                return {
                    "id": tid, "name": t.get("name") or "",
                    "displayName": t.get("name") or "",
                    "abbreviation": t.get("abbreviation") or "",
                    "logo": f"https://www.mlbstatic.com/team-logos/{tid}.svg" if tid else ""
                }
            score_current = ""
            if away_score is not None and home_score is not None:
                score_current=f"{home_score} - {away_score}"
            out.append({
                "id": str(g.get("gamePk") or ""),
                "matchId": str(g.get("gamePk") or ""),
                "gamePk": str(g.get("gamePk") or ""),
                "date": g.get("gameDate") or date,
                "scheduledGameDate": date,
                "awayTeam": team_obj(away), "homeTeam": team_obj(home),
                "state": {"report": report, "description": detailed, "score": {"current": score_current}}
            })
    return out

def read_key():
    return get_secret("HIGHLIGHTLY_API_KEY",ROOT)


def _settings_payload():
    raw=secrets_status(ROOT)
    def one(env_name):
        row=raw.get(env_name) or {}
        return {"configured":bool(row.get("configured")),"source":row.get("source") or "missing"}
    return {
        "ok":True,"version":APP_VERSION,"storage":"cloud-server" if CLOUD_MODE else "machine-local",
        "deploymentMode":DEPLOYMENT_MODE,"secretsWritable":not CLOUD_MODE,
        "secretsFile":None if CLOUD_MODE else str(SECRETS_FILE),
        "connections":{
            "highlightly":one("HIGHLIGHTLY_API_KEY"),
            "youtube":one("YOUTUBE_API_KEY"),
            "openai":one("OPENAI_API_KEY")
        }
    }


def _update_settings_secrets(body):
    body=body or {}; updates={}
    mapping={"highlightly":"HIGHLIGHTLY_API_KEY","youtube":"YOUTUBE_API_KEY","openai":"OPENAI_API_KEY"}
    replacements=body.get("replacements") or {}
    if not isinstance(replacements,dict): raise ValueError("replacements must be an object")
    for short,env_name in mapping.items():
        if short in replacements:
            value=str(replacements.get(short) or "").strip()
            if value: updates[env_name]=value
    clears=body.get("clear") or []
    if isinstance(clears,list):
        for short in clears:
            env_name=mapping.get(str(short).lower())
            if env_name: updates[env_name]=""
    if updates: set_secrets(updates)
    return _settings_payload()


def send_json(handler, payload, status=200, headers=None):
    body = json.dumps(payload).encode("utf-8")
    try:
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Cache-Control", "no-store")
        if headers:
            for k,v in headers.items():
                handler.send_header(k, v)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return True
    except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
        # Mobile Chrome aggressively cancels superseded score/date requests. That
        # is normal client behavior, not an upstream API failure, and should not
        # trigger a second 502 write or a full traceback in Termux.
        return False


def send_bytes(handler, body, content_type='application/octet-stream', status=200, headers=None):
    body=body if isinstance(body,(bytes,bytearray)) else bytes(body or b'')
    try:
        handler.send_response(status)
        handler.send_header('Content-Type',content_type)
        handler.send_header('Cache-Control','no-store')
        if headers:
            for k,v in headers.items(): handler.send_header(k,v)
        handler.send_header('Content-Length',str(len(body)))
        handler.end_headers(); handler.wfile.write(body); return True
    except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
        return False


def _history_audit_filters(qs):
    return {
        'date_from':str((qs.get('dateFrom') or [''])[-1])[:10],
        'date_to':str((qs.get('dateTo') or [''])[-1])[:10],
        'league':str((qs.get('league') or [''])[-1]).upper(),
        'best_tier':str((qs.get('bestTier') or [''])[-1]).lower(),
        'status':str((qs.get('status') or [''])[-1]).lower(),
        'search':str((qs.get('q') or [''])[-1])[:120],
        'limit':min(500,max(1,int((qs.get('limit') or ['100'])[-1] or 100))),
        'offset':max(0,int((qs.get('offset') or ['0'])[-1] or 0)),
    }


def _history_audit_export_filters(qs):
    data=_history_audit_filters(qs); data.pop('limit',None); data.pop('offset',None); return data


def _history_audit_csv_bytes(rows):
    fields=['Date','League','Game','Event ID','Tier','Title','Duration Seconds','Provider','URL','Validation','Runtime','Verified','Last Verified','Association Confidence','Association Method','Scope','Intent','Catalog Coverage Status','Quality Gap Status','Best Tier','Audit Status','Discovery Pending','Upgrade Pending','Catalog Complete','Quality Complete','Discovery Version','Current Discovery Version','Discovery State']
    sio=io.StringIO(newline=''); writer=csv.DictWriter(sio,fieldnames=fields,extrasaction='ignore'); writer.writeheader()
    for row in rows:
        item=dict(row)
        ts=float(item.get('Last Verified') or 0)
        item['Last Verified']=datetime.fromtimestamp(ts,timezone.utc).isoformat().replace('+00:00','Z') if ts else ''
        writer.writerow(item)
    return sio.getvalue().encode('utf-8-sig')


def _xlsx_col_name(n):
    out=''
    while n:
        n,rem=divmod(n-1,26); out=chr(65+rem)+out
    return out


def _history_audit_xlsx_bytes(rows):
    """Write a dependency-free single-sheet XLSX for database auditing."""
    fields=['Date','League','Game','Event ID','Tier','Title','Duration Seconds','Provider','URL','Validation','Runtime','Verified','Last Verified','Association Confidence','Association Method','Scope','Intent','Catalog Coverage Status','Quality Gap Status','Best Tier','Audit Status','Discovery Pending','Upgrade Pending','Catalog Complete','Quality Complete','Discovery Version','Current Discovery Version','Discovery State']
    data=[fields]
    for row in rows:
        item=dict(row); ts=float(item.get('Last Verified') or 0)
        item['Last Verified']=datetime.fromtimestamp(ts,timezone.utc).isoformat().replace('+00:00','Z') if ts else ''
        data.append([item.get(k,'') for k in fields])
    sheet=[]
    for r_idx,row in enumerate(data,1):
        cells=[]
        for c_idx,value in enumerate(row,1):
            ref=f'{_xlsx_col_name(c_idx)}{r_idx}'
            if isinstance(value,(int,float)) and not isinstance(value,bool):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                text=html.escape(str(value if value is not None else ''),quote=False)
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>')
        sheet.append(f'<row r="{r_idx}">'+''.join(cells)+'</row>')
    sheet_xml='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"/></sheetViews><sheetFormatPr defaultRowHeight="15"/><sheetData>'+''.join(sheet)+'</sheetData><autoFilter ref="A1:V1"/></worksheet>'
    content_types='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'
    rels='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    workbook='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Historical Media" sheetId="1" r:id="rId1"/></sheets></workbook>'
    workbook_rels='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
    styles='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="1"><xf xfId="0"/></cellXfs></styleSheet>'
    bio=io.BytesIO()
    with zipfile.ZipFile(bio,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',content_types); z.writestr('_rels/.rels',rels); z.writestr('xl/workbook.xml',workbook)
        z.writestr('xl/_rels/workbook.xml.rels',workbook_rels); z.writestr('xl/worksheets/sheet1.xml',sheet_xml); z.writestr('xl/styles.xml',styles)
    return bio.getvalue()

FOOTBALL_DAY_CACHE={}
def _football_day_fallback(date, sport_key, timezone_value=""):
    cache_key=(str(date),str(timezone_value or ""))
    cached=FOOTBALL_DAY_CACHE.get(cache_key)
    if cached and time.time()-float(cached.get("savedAt") or 0)<180:
        return _strict_soccer_rows(cached.get("data") or {"data":[]},sport_key)

    key=read_key()
    if not key:
        return {"data":[]}
    params={"date":date,"limit":"100"}
    if timezone_value:
        params["timezone"]=timezone_value
    url=f"{BASE_URL}/football/matches?{urlencode(params)}"
    req=Request(url,headers={
        "x-rapidapi-key":key,
        "Accept":"application/json",
        "User-Agent":"SportsBigBoard/4.0.2"
    })
    with urlopen(req,timeout=15) as resp:
        data=json.loads(resp.read().decode("utf-8"))
    FOOTBALL_DAY_CACHE[cache_key]={"savedAt":time.time(),"data":data}
    return _strict_soccer_rows(data,sport_key)


def _soccer_payload_rows(payload):
    if isinstance(payload,list):
        return payload
    if isinstance(payload,dict):
        for key in ("data","items","results","matches","events","highlights"):
            val=payload.get(key)
            if isinstance(val,list):
                return val
    return []

def _soccer_sample(row):
    if not isinstance(row,dict):
        return {"type":type(row).__name__}
    keep=("id","date","league","leagueName","competition","tournament","country","countryName","countryCode","homeTeam","awayTeam","home","away","state","status")
    return {k:row.get(k) for k in keep if k in row}

def _soccer_filter_stage(payload,sport_key):
    raw_rows=_soccer_payload_rows(payload)
    filtered=_strict_soccer_rows(payload,sport_key)
    filtered_rows=_soccer_payload_rows(filtered)
    return raw_rows,filtered,filtered_rows

def _strict_soccer_rows(payload, sport_key):
    """Reject soccer rows from the wrong competition if an upstream filter is ignored.

    Highlight payloads are not perfectly uniform: MLS can be labelled either
    "Major League Soccer" or "MLS", while EPL can appear as "Premier League",
    "English Premier League" or "EPL". Accept those canonical aliases but keep
    the country guard for England.
    """
    aliases={
        "epl":{"premier league","english premier league","epl"},
        "mls":{"major league soccer","mls"},
    }.get(str(sport_key).lower())
    if not aliases: return payload
    def rows(obj):
        if isinstance(obj,list): return obj
        if isinstance(obj,dict):
            for key in ("data","items","results","matches","highlights"):
                if isinstance(obj.get(key),list): return obj.get(key)
        return []
    def league_name(row):
        lg=row.get('league') if isinstance(row,dict) else None
        if isinstance(lg,dict): return str(lg.get('name') or lg.get('leagueName') or '')
        return str((row.get('leagueName') if isinstance(row,dict) else '') or lg or '')
    good=[]
    for row in rows(payload):
        if not isinstance(row,dict): continue
        name=league_name(row).strip().lower()
        if name not in aliases: continue
        # EPL gets an extra country guard because generic soccer endpoints can be noisy.
        if str(sport_key).lower()=="epl":
            country=row.get('country') or {}
            ctext=' '.join([str(country.get('name') or '') if isinstance(country,dict) else str(country),str(row.get('countryName') or ''),str(row.get('countryCode') or '')]).lower()
            if ctext and not any(x in ctext for x in ('england','united kingdom','gb','uk')): continue
        good.append(row)
    if isinstance(payload,list): return good
    if isinstance(payload,dict):
        out=dict(payload); target=None
        for key in ("data","items","results","matches","highlights"):
            if isinstance(out.get(key),list): target=key; break
        if target: out[target]=good
        else: out['data']=good
        return out
    return payload

# Backward-compatible alias for older internal references.
def _strict_epl_rows(payload):
    return _strict_soccer_rows(payload,"epl")

PROGRAM_RANK_CACHE={}
def _program_rank_key(mode,candidates,favorites,local_date):
    raw=json.dumps({'mode':mode,'c':candidates,'f':favorites,'d':local_date},sort_keys=True,ensure_ascii=False)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()

def _openai_program_rank(mode,candidates,favorites=None,local_date=''):
    candidates=list(candidates or [])[:40]; favorites=list(favorites or [])[:20]
    if not candidates: return []
    key=_program_rank_key(mode,candidates,favorites,local_date)
    cached=PROGRAM_RANK_CACHE.get(key)
    if cached and time.time()-cached['savedAt']<600: return cached['data']
    if not read_openai_key(): return []
    schema={'type':'object','properties':{'items':{'type':'array','items':{'type':'object','properties':{
        'id':{'type':'string'},'score':{'type':'integer','minimum':0,'maximum':100},'reason':{'type':'string'},
        'playType':{'type':'string','enum':['defense','clutch','skill','scoring','milestone','news','game','other']}
    },'required':['id','score','reason','playType'],'additionalProperties':False}}},'required':['items'],'additionalProperties':False}
    if mode=='top-plays':
        instructions=(
          'Rank TODAY sports video clips for a cross-sport Top Plays countdown. Score athletic impressiveness, difficulty, rarity, clutch value, stakes, and visual wow factor. '
          'Treat spectacular defense, saves, catches, blocks, skill plays and unusual moments as first-class candidates. Do NOT make home runs or goals dominate merely because they score. '
          'A routine solo home run should lose to an elite defensive robbery. A candidate that is actually an interview, press conference, studio analysis, preview, recap or player reaction rather than an athletic play must score 0. '
          'Prefer category, game and sport diversity when scores are close. Score 100 as the absolute best play of the sports day. Use only supplied facts.'
        )
    elif mode=='score-ribbon':
        instructions=(
          'Rank TODAY sports games for the top scoreboard ribbon of a cross-sport channel. Score sporting importance across leagues, not league popularity. '
          'Championships, finals, winner-take-all and elimination games are highest. Then major playoff/knockout games, games with real title/playoff implications, major rivalry or record-significance games, and ordinary games. '
          'A Super Bowl or major World Cup final belongs near 100; a championship series Game 7 outranks a Game 6, which outranks an early playoff game, which outranks a routine regular-season game. '
          'Live status is useful but should not make a meaningless game outrank a championship. Favorite teams get a secondary boost after global importance. Use only supplied candidate facts.'
        )
    else:
        instructions=(
          'Act as the programming director for a cross-sport highlight channel. Rank what should air first TODAY using real sporting stakes, not league popularity. '
          'Championships and elimination events outrank ordinary games. Examples of the intended scale: Super Bowl and major World Cup final are near the top; league championship finals are next; '
          'Game 7 outranks most Game 6s; conference/semifinals outrank early playoff rounds; games with real playoff or title implications outrank meaningless regular-season games. '
          'Major breaking trades, consequential injuries, records and extraordinary performances can outrank ordinary game recaps. Freshness matters after stakes. '
          'Favorite teams receive a useful tie-break/secondary boost but must not jump ahead of clearly more important global events solely because they are favorites. Use only supplied facts.'
        )
    payload={'model':OPENAI_MODEL,'input':instructions+'\nFavorite teams: '+json.dumps(favorites)+'\nLocal sports date: '+str(local_date)+'\nCandidates:\n'+json.dumps(candidates,ensure_ascii=False),
             'max_output_tokens':3200,'text':{'format':{'type':'json_schema','name':'sports_big_board_program_rank','strict':True,'schema':schema}}}
    last=None
    for timeout in (35,55):
        try:
            response=openai_api_request('/responses',payload=payload,timeout=timeout)
            parsed=json.loads(openai_output_text(response) or '{}')
            rows=parsed.get('items') or []
            if not isinstance(rows,list): raise ValueError('ranking result missing items array')
            PROGRAM_RANK_CACHE[key]={'savedAt':time.time(),'data':rows}
            return rows
        except Exception as exc:
            last=exc; print(f'[SBB program-rank] retry {mode}: {type(exc).__name__}: {exc}',flush=True)
    raise last or RuntimeError('program ranking failed')


# v2.5.30 transport cache. This cache is deliberately independent from the
# browser/A-B playback ownership state. It only makes bytes local; the browser
# PlaybackController remains the sole authority that can make media active.
MEDIA_FILE_CACHE_DIR = CACHE_DIR / "media-v2529"
MEDIA_FILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
# v4.0.2: four megabytes was not enough runway for some NFL/ESPN MP4s on
# mobile. Stage a real 16 MB startup window so playback can run locally while
# the remainder/full file is fetched in the background.
MEDIA_FILE_CACHE_HEAD_BYTES = int(os.environ.get("SBB_MEDIA_HEAD_BYTES", str(16*1024*1024)))
MEDIA_FILE_CACHE_TAIL_BYTES = int(os.environ.get("SBB_MEDIA_TAIL_BYTES", str(1*1024*1024)))
MEDIA_FILE_CACHE_FULL_MAX_BYTES = int(os.environ.get("SBB_MEDIA_FULL_MAX_BYTES", str(110*1024*1024)))
MEDIA_FILE_CACHE_MAX_BYTES = int(os.environ.get("SBB_MEDIA_CACHE_MAX_BYTES", str(3*1024*1024*1024)))
MEDIA_FILE_CACHE_TTL = int(os.environ.get("SBB_MEDIA_CACHE_TTL", str(3*24*3600)))
MEDIA_FILE_CACHE_LOCK = threading.RLock()
MEDIA_WORK_SCHEDULER = MediaWorkScheduler(workers=4, name="sbb-media-work")
# v4.0.2: Game Center network work gets its own pool so video/media prewarm can
# never starve score/stat preparation. Foreground playback remains outside both.
GAME_CENTER_WORK_SCHEDULER = MediaWorkScheduler(workers=8, name="sbb-game-center-work")
MEDIA_FILE_CACHE_JOBS = {}
MEDIA_FILE_CACHE_FULL_JOBS = {}
MEDIA_FILE_CACHE_ACTIVE_STREAMS = set()
MEDIA_FILE_CACHE_STATS = {"requests":0,"fullHits":0,"rangeHits":0,"misses":0,"prepared":0,"fullReady":0,"errors":0,"lastError":""}

MEDIA_ALLOWED_HOST_SUFFIXES=(
    "mlb.com","mlbstatic.com","espn.com","espncdn.com","nfl.com",
    "akamaized.net","akamaihd.net","cloudfront.net","brightcove.com","boltdns.net"
)

def _media_host_allowed(media_url):
    try:
        upstream=urlparse(str(media_url or "")); host=(upstream.hostname or "").lower()
        return upstream.scheme == "https" and any(host==suffix or host.endswith("."+suffix) for suffix in MEDIA_ALLOWED_HOST_SUFFIXES)
    except Exception:
        return False

def _media_cache_key(media_url):
    return hashlib.sha256(str(media_url).encode("utf-8")).hexdigest()

def _media_cache_paths(media_url):
    key=_media_cache_key(media_url); base=MEDIA_FILE_CACHE_DIR/key
    return {
        "key":key,"meta":base.with_suffix(".json"),"head":base.with_suffix(".head"),
        "tail":base.with_suffix(".tail"),"full":base.with_suffix(".mp4"),"tmp":base.with_suffix(".part")
    }

def _media_cache_meta(media_url):
    paths=_media_cache_paths(media_url)
    try:
        meta=json.loads(paths["meta"].read_text(encoding="utf-8"))
        if not isinstance(meta,dict): meta={}
    except Exception:
        meta={}
    meta.setdefault("url",media_url); meta.setdefault("key",paths["key"]); meta["paths"]=paths
    return meta

def _media_cache_save(meta):
    paths=meta.get("paths") or _media_cache_paths(meta.get("url") or "")
    payload={k:v for k,v in meta.items() if k!="paths"}
    payload["updatedAt"]=time.time()
    try:
        tmp=paths["meta"].with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8")
        tmp.replace(paths["meta"])
    except Exception:
        pass

def _parse_content_range(value):
    m=re.match(r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$",str(value or "").strip(),re.I)
    if not m: return None
    return int(m.group(1)),int(m.group(2)),(None if m.group(3)=="*" else int(m.group(3)))

def _parse_request_range(value,total):
    if not value: return None
    m=re.match(r"^bytes=(\d*)-(\d*)$",str(value).strip(),re.I)
    if not m or not total: return None
    a,b=m.group(1),m.group(2)
    if not a:
        if not b: return None
        n=max(1,int(b)); return max(0,total-n),total-1
    start=int(a); end=int(b) if b else total-1
    if start>=total: return None
    return start,min(end,total-1)

def _media_request_headers(range_value=None,media_url=""):
    host=(urlparse(str(media_url or "")).hostname or "").lower()
    referer="https://www.espn.com/" if ("espn" in host or "akamai" in host) else ("https://www.nfl.com/" if "nfl" in host else "https://www.mlb.com/")
    headers={
        "User-Agent":"Mozilla/5.0 SportsBigBoard/4.0.2",
        "Accept":"video/mp4,video/*;q=0.9,*/*;q=0.8",
        "Referer":referer
    }
    if range_value: headers["Range"]=range_value
    return headers

def _fetch_media_range_to_file(media_url,start,end,path):
    req=Request(media_url,headers=_media_request_headers(f"bytes={start}-{end}",media_url))
    with urlopen(req,timeout=25) as resp:
        status=getattr(resp,"status",200)
        cr=_parse_content_range(resp.headers.get("Content-Range"))
        content_length=int(resp.headers.get("Content-Length") or 0)
        actual_start=cr[0] if cr else (0 if status==200 else start)
        actual_end=cr[1] if cr else actual_start+content_length-1
        total=cr[2] if cr else (content_length if status==200 and content_length else None)
        tmp=path.with_suffix(path.suffix+".tmp")
        with tmp.open("wb") as out:
            while True:
                chunk=resp.read(256*1024)
                if not chunk: break
                out.write(chunk)
        tmp.replace(path)
        return {
            "start":actual_start,"end":actual_end,"total":total,
            "contentType":resp.headers.get("Content-Type") or "video/mp4",
            "etag":resp.headers.get("ETag") or "","lastModified":resp.headers.get("Last-Modified") or ""
        }

def _media_cache_download_full(media_url):
    paths=_media_cache_paths(media_url)
    try:
        # Full-file completion is deliberately background priority. Give startup
        # range jobs and active player streams the network first; this is what lets
        # server caching improve a click instead of competing with it.
        deadline=time.time()+8.0
        while time.time()<deadline:
            with MEDIA_FILE_CACHE_LOCK:
                busy=bool(MEDIA_FILE_CACHE_ACTIVE_STREAMS) or bool(MEDIA_FILE_CACHE_JOBS)
            if not busy: break
            time.sleep(0.20)
        try: _media_cache_cleanup()
        except Exception: pass
        req=Request(media_url,headers=_media_request_headers(media_url=media_url))
        with urlopen(req,timeout=35) as resp:
            status=getattr(resp,"status",200)
            if status not in (200,206): return
            tmp=paths["tmp"]
            with tmp.open("wb") as out:
                while True:
                    with MEDIA_FILE_CACHE_LOCK:
                        foreground_busy=bool(MEDIA_FILE_CACHE_ACTIVE_STREAMS)
                    if foreground_busy: time.sleep(0.06)
                    chunk=resp.read(512*1024)
                    if not chunk: break
                    out.write(chunk)
            size=tmp.stat().st_size if tmp.exists() else 0
            if not size: return
            meta=_media_cache_meta(media_url)
            expected=int(meta.get("total") or 0)
            # A full-cache file must represent the complete resource. Do not publish
            # a partial response as full merely because an upstream ignored our intent.
            if expected and size < expected:
                try: tmp.unlink()
                except Exception: pass
                return
            tmp.replace(paths["full"])
            meta.update({
                "total":size,"fullReady":True,"fullSize":size,
                "contentType":resp.headers.get("Content-Type") or meta.get("contentType") or "video/mp4",
                "etag":resp.headers.get("ETag") or meta.get("etag") or "",
                "lastModified":resp.headers.get("Last-Modified") or meta.get("lastModified") or "",
                "lastAccess":time.time()
            })
            _media_cache_save(meta)
            with MEDIA_FILE_CACHE_LOCK:
                MEDIA_FILE_CACHE_STATS["fullReady"]+=1
            print(f"[SBB media-cache] FULL READY {size/1024/1024:.1f} MB {media_url[:120]}",flush=True)
    except Exception as exc:
        with MEDIA_FILE_CACHE_LOCK:
            MEDIA_FILE_CACHE_STATS["errors"]+=1; MEDIA_FILE_CACHE_STATS["lastError"]=f"{type(exc).__name__}: {exc}"
        print(f"[SBB media-cache] full error {type(exc).__name__}: {exc}",flush=True)
    finally:
        with MEDIA_FILE_CACHE_LOCK:
            MEDIA_FILE_CACHE_FULL_JOBS.pop(_media_cache_key(media_url),None)

def _schedule_media_cache_full(media_url,total):
    if not total or total>MEDIA_FILE_CACHE_FULL_MAX_BYTES: return False
    paths=_media_cache_paths(media_url)
    if paths["full"].exists() and paths["full"].stat().st_size>=total: return True
    key=paths["key"]
    with MEDIA_FILE_CACHE_LOCK:
        if key in MEDIA_FILE_CACHE_FULL_JOBS: return True
        fut=MEDIA_WORK_SCHEDULER.submit(f"full:{key}",MEDIA_PRIORITY["FULL_CACHE_COMPLETION"],_media_cache_download_full,media_url)
        MEDIA_FILE_CACHE_FULL_JOBS[key]=fut
    return True

def _media_cache_prepare(media_url,event_id="",media_date="",priority=0):
    if not _media_host_allowed(media_url): return
    paths=_media_cache_paths(media_url)
    try:
        meta=_media_cache_meta(media_url)
        meta.update({"eventId":str(event_id or meta.get("eventId") or meta.get("gamePk") or ""),"gamePk":str(meta.get("gamePk") or (event_id if str(event_id).isdigit() else "")),"date":str(media_date or meta.get("date") or ""),"lastWantedAt":time.time(),"priority":priority})
        # Stage the first 16 MB. This is intentionally large enough to leave the
        # browser several seconds of local runway while the full cache fills.
        head_ok=paths["head"].exists() and paths["head"].stat().st_size>=min(MEDIA_FILE_CACHE_HEAD_BYTES,int(meta.get("total") or MEDIA_FILE_CACHE_HEAD_BYTES))
        if not head_ok and not meta.get("fullReady"):
            info=_fetch_media_range_to_file(media_url,0,MEDIA_FILE_CACHE_HEAD_BYTES-1,paths["head"])
            meta.update(info); meta["headStart"]=info["start"]; meta["headEnd"]=info["end"]; meta["headSize"]=paths["head"].stat().st_size
        total=int(meta.get("total") or 0)
        # Some CDNs ignore Range and hand us the complete file. Promote that
        # response directly rather than storing a full MP4 under the .head name.
        if total and paths["head"].exists() and paths["head"].stat().st_size>=total:
            paths["head"].replace(paths["full"]); meta["fullReady"]=True; meta["fullSize"]=total; meta["headSize"]=0
        if total and total>MEDIA_FILE_CACHE_HEAD_BYTES and not meta.get("fullReady"):
            tail_start=max(0,total-MEDIA_FILE_CACHE_TAIL_BYTES)
            tail_ok=paths["tail"].exists() and int(meta.get("tailStart") or -1)==tail_start and paths["tail"].stat().st_size>=total-tail_start
            if not tail_ok:
                info=_fetch_media_range_to_file(media_url,tail_start,total-1,paths["tail"])
                meta.update({k:v for k,v in info.items() if v not in (None,"")}); meta["tailStart"]=info["start"]; meta["tailEnd"]=info["end"]; meta["tailSize"]=paths["tail"].stat().st_size
        meta["preparedAt"]=time.time(); meta["lastAccess"]=time.time()
        _media_cache_save(meta)
        _schedule_media_cache_full(media_url,total)
        with MEDIA_FILE_CACHE_LOCK:
            MEDIA_FILE_CACHE_STATS["prepared"]+=1
        print(f"[SBB media-cache] STAGED event={event_id or '-'} total={total or '?'} head={meta.get('headSize',0)} tail={meta.get('tailSize',0)}",flush=True)
    except Exception as exc:
        with MEDIA_FILE_CACHE_LOCK:
            MEDIA_FILE_CACHE_STATS["errors"]+=1; MEDIA_FILE_CACHE_STATS["lastError"]=f"{type(exc).__name__}: {exc}"
        print(f"[SBB media-cache] stage error {type(exc).__name__}: {exc}",flush=True)
    finally:
        with MEDIA_FILE_CACHE_LOCK:
            MEDIA_FILE_CACHE_JOBS.pop(paths["key"],None)

def schedule_media_cache_prepare(media_url,event_id="",media_date="",priority=0,priority_class=""):
    if _history_playback_suspended():
        return False
    priority_class=str(priority_class or "").upper()
    if not _media_host_allowed(media_url): return False
    paths=_media_cache_paths(media_url); key=paths["key"]
    meta=_media_cache_meta(media_url)
    now=time.time()
    full_ok=paths["full"].exists() and bool(meta.get("fullReady"))
    staged_ok=paths["head"].exists() and (now-float(meta.get("preparedAt") or 0)<MEDIA_FILE_CACHE_TTL)
    if full_ok or staged_ok:
        meta["lastWantedAt"]=now; meta["lastAccess"]=now; _media_cache_save(meta)
        if not full_ok: _schedule_media_cache_full(media_url,int(meta.get("total") or 0))
        return True
    with MEDIA_FILE_CACHE_LOCK:
        if key in MEDIA_FILE_CACHE_ACTIVE_STREAMS: return True
        if key in MEDIA_FILE_CACHE_JOBS: return True
        work_priority=MEDIA_PRIORITY.get(priority_class) or (MEDIA_PRIORITY["VISIBLE_SCORE"] if int(priority or 0)>=3 else (MEDIA_PRIORITY["NEARBY_SCORE"] if int(priority or 0)>=1 else MEDIA_PRIORITY["RECENT_FINAL"]))
        fut=MEDIA_WORK_SCHEDULER.submit(f"stage:{key}",work_priority,_media_cache_prepare,media_url,event_id,media_date,priority)
        MEDIA_FILE_CACHE_JOBS[key]=fut
    return True

def _media_cache_serve(handler,media_url,range_header):
    paths=_media_cache_paths(media_url); meta=_media_cache_meta(media_url)
    full=paths["full"]
    total=int(meta.get("total") or (full.stat().st_size if full.exists() else 0))
    if not total: return False
    requested=_parse_request_range(range_header,total) if range_header else None
    source=None; file_offset=0; start=0; end=total-1; label=""
    if full.exists() and bool(meta.get("fullReady")):
        source=full; label="FULL"
        if requested: start,end=requested; file_offset=start
    elif requested:
        start,end=requested
        hs=int(meta.get("headStart") or 0); he=int(meta.get("headEnd") or -1)
        ts=int(meta.get("tailStart") or -1); te=int(meta.get("tailEnd") or -1)
        if paths["head"].exists() and start>=hs and end<=he:
            source=paths["head"]; file_offset=start-hs; label="HEAD"
        elif paths["tail"].exists() and start>=ts and end<=te:
            source=paths["tail"]; file_offset=start-ts; label="TAIL"
    if source is None: return False
    length=end-start+1
    handler.send_response(206 if requested else 200)
    handler.send_header("Content-Type",meta.get("contentType") or "video/mp4")
    handler.send_header("Accept-Ranges","bytes")
    handler.send_header("Content-Length",str(length))
    if requested: handler.send_header("Content-Range",f"bytes {start}-{end}/{total}")
    if meta.get("etag"): handler.send_header("ETag",str(meta.get("etag")))
    if meta.get("lastModified"): handler.send_header("Last-Modified",str(meta.get("lastModified")))
    handler.send_header("Cache-Control","private, max-age=3600")
    handler.send_header("X-SBB-Media-Cache",f"HIT-{label}")
    handler.end_headers()
    try:
        with source.open("rb") as f:
            f.seek(file_offset); remaining=length
            while remaining>0:
                chunk=f.read(min(256*1024,remaining))
                if not chunk: break
                handler.wfile.write(chunk); remaining-=len(chunk)
    except (BrokenPipeError,ConnectionResetError):
        return True
    meta["lastAccess"]=time.time(); _media_cache_save(meta)
    with MEDIA_FILE_CACHE_LOCK:
        MEDIA_FILE_CACHE_STATS["requests"]+=1
        if label=="FULL": MEDIA_FILE_CACHE_STATS["fullHits"]+=1
        else: MEDIA_FILE_CACHE_STATS["rangeHits"]+=1
    print(f"[SBB media-cache] HIT-{label} bytes={start}-{end}/{total}",flush=True)
    return True

def _media_cache_serve_hybrid_head(handler,media_url,range_header,event_id="",media_date=""):
    """Serve a spanning/open-ended range with cached startup bytes first.

    Chrome commonly requests ``bytes=0-``. A prefix cache cannot satisfy the whole
    range on its own, but it *can* make first-frame delivery immediate: write the
    cached head to localhost first, then splice the uncached remainder from the provider
    into the same 206 response. Playback gets local bytes while TLS/upstream opens.
    """
    if not range_header: return False
    paths=_media_cache_paths(media_url); meta=_media_cache_meta(media_url)
    total=int(meta.get("total") or 0); hs=int(meta.get("headStart") or 0); he=int(meta.get("headEnd") or -1)
    if not total or not paths["head"].exists() or he<hs: return False
    requested=_parse_request_range(range_header,total)
    if not requested: return False
    start,end=requested
    if start<hs or start>he or end<=he: return False
    cached_end=min(he,end); cached_len=cached_end-start+1; next_start=cached_end+1
    if cached_len<=0: return False
    key=paths["key"]
    with MEDIA_FILE_CACHE_LOCK:
        MEDIA_FILE_CACHE_STATS["requests"]+=1; MEDIA_FILE_CACHE_STATS["rangeHits"]+=1
        MEDIA_FILE_CACHE_ACTIVE_STREAMS.add(key)
    full_capture=bool(start==0 and end==total-1 and total<=MEDIA_FILE_CACHE_FULL_MAX_BYTES)
    full_tmp=paths["full"].with_suffix('.mp4.hybridtmp') if full_capture else None
    capture=None; captured_total=0; client_connected=True
    try:
        if full_tmp:
            try:
                capture=full_tmp.open('wb')
                with paths["head"].open('rb') as src:
                    remaining=cached_end+1
                    while remaining>0:
                        piece=src.read(min(256*1024,remaining))
                        if not piece: break
                        capture.write(piece); remaining-=len(piece); captured_total+=len(piece)
            except Exception:
                try:
                    if capture: capture.close()
                except Exception: pass
                capture=None; captured_total=0
        handler.send_response(206)
        handler.send_header("Content-Type",meta.get("contentType") or "video/mp4")
        handler.send_header("Accept-Ranges","bytes")
        handler.send_header("Content-Length",str(end-start+1))
        handler.send_header("Content-Range",f"bytes {start}-{end}/{total}")
        if meta.get("etag"): handler.send_header("ETag",str(meta.get("etag")))
        if meta.get("lastModified"): handler.send_header("Last-Modified",str(meta.get("lastModified")))
        handler.send_header("Cache-Control","private, max-age=3600")
        handler.send_header("X-SBB-Media-Cache","HYBRID-HEAD")
        handler.end_headers()
        # Deliver cached startup bytes before even opening the upstream remainder.
        with paths["head"].open('rb') as f:
            f.seek(start-hs); remaining=cached_len
            while remaining>0:
                piece=f.read(min(256*1024,remaining))
                if not piece: break
                try: handler.wfile.write(piece)
                except (BrokenPipeError,ConnectionResetError): client_connected=False; break
                remaining-=len(piece)
        try: handler.wfile.flush()
        except Exception: pass
        if not client_connected:
            print(f"[SBB media-cache] HYBRID head satisfied then client closed bytes={start}-{cached_end}/{total}",flush=True)
            return True
        req=Request(media_url,headers=_media_request_headers(f"bytes={next_start}-{end}",media_url))
        with urlopen(req,timeout=20) as resp:
            while True:
                chunk=resp.read(256*1024)
                if not chunk: break
                if capture:
                    try: capture.write(chunk); captured_total+=len(chunk)
                    except Exception:
                        try: capture.close()
                        except Exception: pass
                        capture=None
                try: handler.wfile.write(chunk)
                except (BrokenPipeError,ConnectionResetError):
                    client_connected=False; break
        if capture:
            capture.flush(); capture.close(); capture=None
        if full_tmp and full_tmp.exists() and client_connected and captured_total>=total:
            full_tmp.replace(paths["full"]); meta.update({"fullReady":True,"fullSize":total,"total":total,"lastAccess":time.time(),"preparedAt":time.time()}); _media_cache_save(meta)
            with MEDIA_FILE_CACHE_LOCK: MEDIA_FILE_CACHE_STATS["fullReady"]+=1
            print(f"[SBB media-cache] HYBRID promoted FULL {total/1024/1024:.1f} MB",flush=True)
        else:
            try:
                if full_tmp: full_tmp.unlink(missing_ok=True)
            except Exception: pass
            if total<=MEDIA_FILE_CACHE_FULL_MAX_BYTES: _schedule_media_cache_full(media_url,total)
        print(f"[SBB media-cache] HYBRID-HEAD bytes={start}-{cached_end} + upstream {next_start}-{end}/{total}",flush=True)
        return True
    except Exception as exc:
        print(f"[SBB media-cache] hybrid error {type(exc).__name__}: {exc}",flush=True)
        try:
            if capture: capture.close()
            if full_tmp: full_tmp.unlink(missing_ok=True)
        except Exception: pass
        # Headers may already be committed, so the browser must retry if remainder
        # transport failed. Returning True prevents a second response on this socket.
        return True
    finally:
        with MEDIA_FILE_CACHE_LOCK: MEDIA_FILE_CACHE_ACTIVE_STREAMS.discard(key)
        meta["lastAccess"]=time.time(); _media_cache_save(meta)

def _media_cache_summary():
    with MEDIA_FILE_CACHE_LOCK:
        stats=dict(MEDIA_FILE_CACHE_STATS); stats["stageJobs"]=len(MEDIA_FILE_CACHE_JOBS); stats["fullJobs"]=len(MEDIA_FILE_CACHE_FULL_JOBS); stats["activeStreams"]=len(MEDIA_FILE_CACHE_ACTIVE_STREAMS)
    files=list(MEDIA_FILE_CACHE_DIR.glob("*.mp4")); heads=list(MEDIA_FILE_CACHE_DIR.glob("*.head"))
    stats["fullFiles"]=len(files); stats["stagedFiles"]=len(heads)
    stats["bytesOnDisk"]=sum(x.stat().st_size for x in MEDIA_FILE_CACHE_DIR.iterdir() if x.is_file() and x.suffix in {".mp4",".head",".tail"})
    return stats

def _media_cache_cleanup():
    # Keep recent game media persistent across browser/server restarts, but bound disk use.
    now=time.time(); rows=[]
    for meta_path in MEDIA_FILE_CACHE_DIR.glob("*.json"):
        try:
            meta=json.loads(meta_path.read_text(encoding="utf-8")); url=meta.get("url") or ""; paths=_media_cache_paths(url)
            last=float(meta.get("lastAccess") or meta.get("updatedAt") or meta_path.stat().st_mtime)
            size=sum(x.stat().st_size for x in (paths["full"],paths["head"],paths["tail"]) if x.exists())
            rows.append((last,size,paths))
        except Exception:
            continue
    total=sum(x[1] for x in rows)
    for last,size,paths in sorted(rows,key=lambda x:x[0]):
        if (now-last)<MEDIA_FILE_CACHE_TTL and total<=MEDIA_FILE_CACHE_MAX_BYTES: continue
        for name in ("full","head","tail","meta","tmp"):
            try: paths[name].unlink(missing_ok=True)
            except Exception: pass
        total=max(0,total-size)

def _server_primary_native_items(date):
    data,_=read_stats_disk_cache(date,allow_stale=True); groups={}
    for item in list(data or []):
        gid=_gamepk_from_item(item)
        if gid and item.get("mediaUrl") and _media_host_allowed(item.get("mediaUrl")): groups.setdefault(gid,[]).append(item)
    selected=[]
    for gid,items in groups.items():
        # _game_content_result already reduces recap games to its best overview.
        # If this is a reel, use the first chronological item, matching score-card start.
        over=[x for x in items if x.get("overview")]
        if over: primary=over[0]
        else: primary=sorted(items,key=lambda x:tuple(x.get("chronology") or [9,999,0,0,0]))[0]
        selected.append(primary)
    return selected

def prewarm_server_media_for_date(date,limit=18):
    count=0
    for item in _server_primary_native_items(date)[:limit]:
        if schedule_media_cache_prepare(item.get("mediaUrl"),item.get("gamePk"),date,priority=1,priority_class="RECENT_FINAL"): count+=1
    return count



HIGHLIGHTLY_COMPETITION_KEY={"MLB":"mlb","NFL":"nfl","MLS":"mls","EPL":"epl"}

def _highlightly_gc_fetch_json(url,timeout=10):
    key=read_key()
    if not key: raise RuntimeError("Highlightly API key not configured")
    req=Request(url,headers={"x-rapidapi-key":key,"Accept":"application/json","User-Agent":f"SportsBigBoard/{APP_VERSION}"})
    try:
        with urlopen(req,timeout=timeout) as resp:
            RATE_LIMIT_STATE.update({"limited":False,"remaining":resp.headers.get("x-ratelimit-requests-remaining",""),"limit":resp.headers.get("x-ratelimit-requests-limit","")})
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code==429: RATE_LIMIT_STATE.update({"limited":True,"since":time.time()})
        raise

def _highlightly_game_center(competition,match_id):
    competition=str(competition or "").upper(); sport_key=HIGHLIGHTLY_COMPETITION_KEY.get(competition)
    if not sport_key: raise NotImplementedError(f"Highlightly Game Center unsupported for {competition}")
    cfg=SPORT_API[sport_key]; base=f'{cfg["base"]}{cfg["prefix"]}'.rstrip('/')
    detail=_highlightly_gc_fetch_json(f"{base}/matches/{match_id}",timeout=10)
    stats=None; box=None
    if competition=="MLB":
        try: stats=_highlightly_gc_fetch_json(f"{base}/statistics/{match_id}",timeout=8)
        except Exception: stats=None
        for suffix in (f"/box-scores/{match_id}",f"/box-score/{match_id}"):
            try: box=_highlightly_gc_fetch_json(base+suffix,timeout=8); break
            except Exception: box=None
    return normalize_highlightly_game_center(detail,competition,str(match_id),stats,box)

def _highlightly_provider_key(event_id):
    text=str(event_id or "")
    return text[3:] if text.startswith("hl-") else text
# v4.0.2 Game Center repository ---------------------------------------------
# Normalized Game Centers are persistent application data. SQLite is the
# authoritative local repository; browser clicks normally read localhost only.
GAME_CENTER_FETCH_LOCKS = {}
GAME_CENTER_FETCH_LOCKS_LOCK = threading.Lock()
GAME_CENTER_JOB_STATE = {}
GAME_CENTER_JOB_STATE_LOCK = threading.Lock()
GAME_CENTER_SUPPORTED = {"MLB","NFL","NBA","NHL","MLS","EPL"}


def _game_center_status(data):
    return str((((data or {}).get("event") or {}).get("status") or ((data or {}).get("scoreboard") or {}).get("status") or "")).lower()


def _game_center_ttl(data):
    if bool((data or {}).get("live")): return 20
    # A completed but partial shell is never immutable. Keep retrying enrichment
    # instead of caching "teams only" for a year.
    if _game_center_needs_enrichment(data,(data or {}).get("competitionId") or ""): return 90
    status=_game_center_status(data)
    if re.search(r"final|finished|game over|completed|complete",status): return 365*24*3600
    if re.search(r"scheduled|pre-game|pregame|preview",status):
        raw=str((((data or {}).get("event") or {}).get("scheduledAt") or ""))
        try:
            dt=datetime.fromisoformat(raw.replace("Z","+00:00"))
            if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
            seconds=(dt.astimezone(timezone.utc)-datetime.now(timezone.utc)).total_seconds()
            if seconds>3600: return 30*60
            if seconds>15*60: return 5*60
        except Exception: pass
        return 60
    return 6*3600


GAME_CENTER_REPOSITORY = GameCenterRepository(GAME_CENTER_DB)
try:
    GAME_CENTER_REPOSITORY.migrate_json_dir(GAME_CENTER_CACHE_DIR,_game_center_ttl)
except Exception as exc:
    print(f"[SBB game-center] legacy cache migration warning: {type(exc).__name__}: {exc}",flush=True)

# Score providers and detailed-stat providers do not necessarily share event ids.
# Game Center therefore resolves provider ids from the sporting event itself
# (competition + viewer date + away/home teams + optional start/game number) and
# persists aliases in SQLite. The browser never has to know which provider minted
# the id shown in the score ribbon.
GAME_CENTER_EVENT_INDEX_LOCK=threading.RLock()
GAME_CENTER_EVENT_INDEX={}


def _gc_clean_team_hint(value):
    if isinstance(value,dict):
        value=value.get("abbreviation") or value.get("abbr") or value.get("shortName") or value.get("displayName") or value.get("name") or ""
    return re.sub(r"[^a-z0-9]","",str(value or "").lower())


def _gc_event_row(competition,row,date="",provider="official"):
    competition=str(competition or "").upper(); row=row or {}
    if competition=="MLB":
        teams=row.get("teams") or {}
        away=((teams.get("away") or {}).get("team") or row.get("awayTeam") or row.get("away") or {})
        home=((teams.get("home") or {}).get("team") or row.get("homeTeam") or row.get("home") or {})
        event_id=str(row.get("gamePk") or row.get("eventId") or row.get("matchId") or row.get("id") or "")
        scheduled=str(row.get("gameDate") or row.get("date") or "")
        game_number=int(row.get("gameNumber") or 0) if str(row.get("gameNumber") or "").isdigit() else 0
    else:
        away=row.get("awayTeam") or row.get("away") or {}
        home=row.get("homeTeam") or row.get("home") or {}
        event_id=str(row.get("espnEventId") or row.get("eventId") or row.get("matchId") or row.get("id") or "")
        scheduled=str(row.get("date") or row.get("scheduledAt") or "")
        game_number=0
    return {
        "competition":competition,"providerEventId":event_id,"date":str(date or scheduled)[:10],
        "scheduledAt":scheduled,"awayTeam":away,"homeTeam":home,"gameNumber":game_number,"provider":str(provider or "official"),
    }


def _index_game_center_events(competition,events,date="",provider="official"):
    """Index one provider without clobbering the other provider's event inventory.

    v2.6.3.5 used one list per competition/day, so the later Highlightly coverage
    pass replaced the official MLB/ESPN rows. That made cross-provider enrichment
    random: a Highlightly match id could masquerade as an MLB gamePk and the rich
    fallback event was no longer discoverable. Keep both inventories side-by-side.
    """
    competition=str(competition or "").upper(); day=str(date or "")[:10]; provider=str(provider or "official")
    rows=[]
    for event in list(events or []):
        row=_gc_event_row(competition,event,day,provider)
        if row.get("providerEventId"): rows.append(row)
    with GAME_CENTER_EVENT_INDEX_LOCK:
        existing=list(GAME_CENTER_EVENT_INDEX.get((competition,day)) or [])
        existing=[r for r in existing if str(r.get("provider") or "official")!=provider]
        GAME_CENTER_EVENT_INDEX[(competition,day)]=existing+rows
    return rows


def _gc_parse_start(value):
    try:
        if not value: return None
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _gc_pick_index_match(rows,requested_id,hints,preferred_provider="official"):
    requested_id=str(requested_id or ""); hints=hints or {}
    away=_gc_clean_team_hint(hints.get("away")); home=_gc_clean_team_hint(hints.get("home"))
    # Cross-provider resolution must target the rich provider inventory. If the
    # preferred inventory is present, never let a same-shaped Highlightly id win.
    preferred=[r for r in rows if str(r.get("provider") or "official")==str(preferred_provider or "official")]
    if preferred: rows=preferred
    def match_team(team,hint):
        aliases=_team_aliases(team)
        return bool(hint and hint in aliases)
    # Provider ids are only authoritative when they agree with the sporting-event
    # fingerprint supplied by the score card. Media discovery can occasionally
    # attach a valid gamePk from a neighboring game; trusting that number before
    # teams/date is exactly how an unrelated Game Center can appear as `Unknown`.
    if requested_id:
        exact=[r for r in rows if str(r.get("providerEventId") or "")==requested_id]
        if len(exact)==1:
            if not away or not home:
                return exact[0]
            if match_team(exact[0].get("awayTeam") or {},away) and match_team(exact[0].get("homeTeam") or {},home):
                return exact[0]
    if not away or not home: return None
    matches=[r for r in rows if match_team(r.get("awayTeam") or {},away) and match_team(r.get("homeTeam") or {},home)]
    if not matches: return None
    game_number=int(hints.get("gameNumber") or 0) if str(hints.get("gameNumber") or "").isdigit() else 0
    if game_number:
        numbered=[r for r in matches if int(r.get("gameNumber") or 0)==game_number]
        if len(numbered)==1: return numbered[0]
    if len(matches)==1: return matches[0]
    wanted=_gc_parse_start(hints.get("start") or hints.get("scheduledAt"))
    if wanted:
        ranked=[]
        for r in matches:
            dt=_gc_parse_start(r.get("scheduledAt"))
            if dt: ranked.append((abs((dt-wanted).total_seconds()),r))
        if ranked:
            ranked.sort(key=lambda x:x[0])
            if len(ranked)==1 or ranked[0][0]+60<ranked[1][0]: return ranked[0][1]
    return None


def _game_center_index_rows(competition,date,allow_fetch=False):
    competition=str(competition or "").upper(); date=str(date or "")[:10]
    with GAME_CENTER_EVENT_INDEX_LOCK:
        rows=list(GAME_CENTER_EVENT_INDEX.get((competition,date)) or [])
    official=[r for r in rows if str(r.get("provider") or "official")=="official"]
    # A Highlightly inventory alone is not enough for cross-provider enrichment.
    # On a fast first click it may arrive before the official coverage worker; fetch
    # the rich-provider index on demand instead of mistaking a Highlightly numeric id
    # for an MLB gamePk / ESPN event id.
    if official or not allow_fetch or not date: return rows
    if competition=="MLB":
        games,_,_=_schedule_game_counts(date)
        _index_game_center_events("MLB",games,date,"official")
    elif competition in ("NFL","NBA","NHL","MLS","EPL"):
        provider_rows=_espn_scoreboard(competition,date,MEDIA_PREWARM_STATE.get("timezone") or "",MEDIA_PREWARM_STATE.get("utcOffsetMinutes"))
        _index_game_center_events(competition,provider_rows,date,"official")
    with GAME_CENTER_EVENT_INDEX_LOCK:
        return list(GAME_CENTER_EVENT_INDEX.get((competition,date)) or [])


def _game_center_request_key(competition,event_id,hints=None):
    competition=str(competition or "").upper(); hints=hints or {}
    parts=[competition,str(hints.get("date") or "")[:10],_gc_clean_team_hint(hints.get("away")),_gc_clean_team_hint(hints.get("home")),str(hints.get("gameNumber") or ""),str(event_id or "")]
    return ":".join(parts)




def _game_center_record_matches_hints(record,hints):
    if not record: return False
    hints=hints or {}; away=str(hints.get("away") or ""); home=str(hints.get("home") or "")
    if not away or not home: return True
    data=record.get("data") or {}; board=data.get("scoreboard") or {}
    probe={"awayTeam":((board.get("away") or {}).get("team") or {}),"homeTeam":((board.get("home") or {}).get("team") or {})}
    target={"awayTeam":{"name":away,"abbreviation":away},"homeTeam":{"name":home,"abbreviation":home}}
    return _same_team_pair(probe,target)

def _resolve_game_center_event_id(competition,event_id,hints=None,allow_fetch=False):
    """Resolve a score-provider id to the authoritative detailed-stats provider id.

    Never fall back to an unverified score id. Calling MLB/ESPN with an arbitrary
    provider id can return an empty-but-200 response, which earlier releases cached
    as an `Unknown` Game Center and then reused forever.
    """
    competition=str(competition or "").upper(); requested=str(event_id or ""); hints=hints or {}
    if competition not in GAME_CENTER_SUPPORTED: return ""
    alias=GAME_CENTER_REPOSITORY.resolve_alias(competition,requested) if requested else ""
    if alias:
        # Aliases written by older builds may have been poisoned before team/date
        # verification existed. Trust an alias immediately only when there is no
        # sporting-event fingerprint or when its cached Game Center matches it.
        alias_record=_game_center_cached_record(competition,alias)
        if (not hints.get("away") and not hints.get("home")) or _game_center_record_matches_hints(alias_record,hints):
            return alias
    # A repository key is itself a previously-verified detailed-provider id, but
    # a browser request carrying team hints must still match that cached event.
    # This prevents a legacy/wrong numeric score id from pointing at a real but
    # unrelated MLB game and being accepted merely because it exists in SQLite.
    existing=GAME_CENTER_REPOSITORY.get(competition,requested) if requested else None
    if existing and _game_center_record_matches_hints(existing,hints): return requested
    date=str(hints.get("date") or "")[:10]
    # Direct API/debug calls may intentionally provide a provider id without a
    # sporting-event fingerprint. Preserve that contract; browser score clicks
    # always send date/team hints and therefore still require verification.
    if requested and not date and not hints.get("away") and not hints.get("home"):
        try:
            _game_center_validate_id(competition,requested)
            return requested
        except Exception:
            pass
    rows=_game_center_index_rows(competition,date,allow_fetch=allow_fetch)
    chosen=_gc_pick_index_match(rows,requested,hints)
    if not chosen: return ""
    resolved=str(chosen.get("providerEventId") or "")
    if resolved and requested and requested!=resolved:
        GAME_CENTER_REPOSITORY.put_alias(competition,requested,resolved,date,hints.get("away") or "",hints.get("home") or "")
    return resolved


def _game_center_quality(data,competition=""):
    coverage=game_center_coverage(data or {})
    level="rich" if coverage.get("complete") else ("partial" if coverage.get("identity") else "shell")
    return {
        "level":level,"score":int(coverage.get("richness") or 0),"complete":bool(coverage.get("complete")),
        "teamStats":int(coverage.get("teamStats") or 0),"playerRows":int(coverage.get("playerRows") or 0),
        "timeline":int(coverage.get("timeline") or 0),"scoringPlays":int(coverage.get("scoringPlays") or 0),
        "innings":int(coverage.get("innings") or 0),"final":bool(coverage.get("final")),"missing":list(coverage.get("missing") or [])
    }

def _game_center_needs_enrichment(data,competition=""):
    return not bool(game_center_coverage(data or {}).get("complete"))

def _game_center_merge(primary,secondary):
    out=merge_game_centers(primary,secondary)
    if isinstance(out,dict):
        out["quality"]=_game_center_quality(out,out.get("competitionId") or "")
        out["partial"]=not bool((out.get("coverage") or {}).get("complete"))
    return out

def _game_center_payload_valid(data,competition=""):
    if not isinstance(data,dict): return False
    scoreboard=data.get("scoreboard") or {}; away=(scoreboard.get("away") or {}).get("team") or {}; home=(scoreboard.get("home") or {}).get("team") or {}
    away_name=str(away.get("name") or away.get("displayName") or away.get("abbreviation") or "").strip()
    home_name=str(home.get("name") or home.get("displayName") or home.get("abbreviation") or "").strip()
    if not away_name or not home_name: return False
    invalid_names={"unknown","away","home","tbd","n/a","na","--","—"}
    if away_name.strip().lower() in invalid_names or home_name.strip().lower() in invalid_names: return False
    comp=str(data.get("competitionId") or (data.get("event") or {}).get("competitionId") or competition or "").upper()
    if competition and comp and comp!=str(competition).upper(): return False
    return True


def _game_center_store(competition,event_id,data,saved_at=None):
    if not _game_center_payload_valid(data,competition):
        raise ValueError(f"{str(competition).upper()} Game Center provider returned an incomplete event")
    data=copy.deepcopy(data)
    existing=GAME_CENTER_REPOSITORY.get(competition,event_id)
    if existing and _game_center_payload_valid(existing.get("data"),competition):
        data=_game_center_merge(existing.get("data"),data)
    coverage=game_center_coverage(data)
    data["coverage"]=coverage
    data["quality"]=_game_center_quality(data,competition)
    data["partial"]=not coverage.get("complete")
    saved_at=float(saved_at or time.time())
    return GAME_CENTER_REPOSITORY.put(competition,event_id,data,saved_at+_game_center_ttl(data),updated_at=saved_at)


def _game_center_cached_record(competition,event_id):
    row=GAME_CENTER_REPOSITORY.get(competition,event_id)
    if row and not _game_center_payload_valid(row.get("data"),competition):
        GAME_CENTER_REPOSITORY.delete(competition,event_id)
        return None
    if row:
        data=copy.deepcopy(row.get("data") or {})
        coverage=game_center_coverage(data)
        data["coverage"]=coverage;data["quality"]=_game_center_quality(data,competition);data["partial"]=not coverage.get("complete")
        row["data"]=data
        if not coverage.get("complete") and float(row.get("expiresAt") or 0)>time.time()+120:
            saved=float(row.get("savedAt") or time.time())
            GAME_CENTER_REPOSITORY.put(competition,event_id,data,time.time()+90,updated_at=saved)
            row=GAME_CENTER_REPOSITORY.get(competition,event_id) or row
    return row


def _game_center_enrich(data,competition,hints=None):
    hints=hints or {}; competition=str(competition or "").upper()
    if not isinstance(data,dict) or not _game_center_needs_enrichment(data,competition): return data
    requested=str((data or {}).get("eventId") or "")
    official_id=_resolve_game_center_event_id(competition,requested,hints,allow_fetch=True)
    if not official_id or str(official_id).startswith("hl-"): return data
    try:
        cached=_game_center_cached_record(competition,official_id)
        if cached and time.time()<float(cached.get("expiresAt") or 0) and not _game_center_needs_enrichment(cached.get("data"),competition):
            official=cached.get("data")
        else:
            official=_game_center_refresh(competition,official_id,hints=hints)
        return _game_center_merge(data,official) if official else data
    except Exception as exc:
        out=copy.deepcopy(data);out["enrichmentError"]=f"{type(exc).__name__}: {exc}";return out

def _game_center_fetch_lock(key):
    with GAME_CENTER_FETCH_LOCKS_LOCK:
        return GAME_CENTER_FETCH_LOCKS.setdefault(key,threading.Lock())


def _game_center_validate_id(competition,event_id):
    competition=str(competition or "").upper(); event_id=str(event_id or "")
    if competition not in GAME_CENTER_SUPPORTED:
        raise NotImplementedError(f"Game Center provider not implemented for {competition}")
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,32}",event_id):
        raise ValueError(f"{competition} Game Center requires a valid event id")
    if competition=="MLB" and not (re.fullmatch(r"\d{4,12}",event_id) or re.fullmatch(r"hl-\d{1,16}",event_id)):
        raise ValueError("MLB Game Center requires numeric gamePk or verified Highlightly id")
    return competition,event_id


def _game_center_refresh(competition,event_id,hints=None):
    competition,event_id=_game_center_validate_id(competition,event_id)
    key=f"{competition}:{event_id}"; hints=hints or {}
    with _game_center_fetch_lock(key):
        if str(event_id).startswith("hl-"):
            data=_highlightly_game_center(competition,_highlightly_provider_key(event_id))
        elif competition=="MLB":
            data=fetch_mlb_game_center(event_id,fetch_json,MLB_STATS_BASE)
        else:
            data=fetch_espn_game_center(competition,event_id,_espn_fetch_json,ESPN_SITE_API)
        # Final defense at the provider boundary. Even a syntactically valid
        # provider id is rejected when its returned teams do not match the score
        # selection. Wrong-game data is never persisted to SQLite.
        if hints.get("away") and hints.get("home"):
            probe={"awayTeam":((((data or {}).get("scoreboard") or {}).get("away") or {}).get("team") or {}),"homeTeam":((((data or {}).get("scoreboard") or {}).get("home") or {}).get("team") or {})}
            target={"awayTeam":{"name":hints.get("away"),"abbreviation":hints.get("away")},"homeTeam":{"name":hints.get("home"),"abbreviation":hints.get("home")}}
            if not _same_team_pair(probe,target):
                raise ValueError(f"{competition} Game Center provider identity did not match selected teams")
        _game_center_store(competition,event_id,data)
        return data


def _game_center_prepare_job(competition,event_id,hints=None):
    competition=str(competition or "").upper(); requested_id=str(event_id or ""); hints=hints or {}
    request_key=_game_center_request_key(competition,requested_id,hints)
    try:
        resolved_id=""; data=None
        provider_hint=str(hints.get("provider") or "").lower()
        # Same-provider details are the fast path because the score match id is exact.
        if provider_hint=="highlightly" and requested_id:
            hl_id=f"hl-{_highlightly_provider_key(requested_id)}"
            known=_game_center_cached_record(competition,hl_id)
            if known and time.time()<float(known.get("expiresAt") or 0) and not _game_center_needs_enrichment(known.get("data"),competition):
                resolved_id=hl_id; data=known.get("data")
            else:
                try:
                    probe=_highlightly_game_center(competition,_highlightly_provider_key(requested_id))
                    if hints.get("away") and hints.get("home"):
                        pair={"awayTeam":((((probe or {}).get("scoreboard") or {}).get("away") or {}).get("team") or {}),"homeTeam":((((probe or {}).get("scoreboard") or {}).get("home") or {}).get("team") or {})}
                        target={"awayTeam":{"name":hints.get("away"),"abbreviation":hints.get("away")},"homeTeam":{"name":hints.get("home"),"abbreviation":hints.get("home")}}
                        if not _same_team_pair(pair,target): raise ValueError("Highlightly match id did not match selected teams")
                    resolved_id=hl_id; data=_game_center_enrich(probe,competition,hints)
                except Exception:
                    resolved_id=""; data=None

        # A shell/partial Highlightly response is not success. Resolve the official
        # event from the preserved official index and merge its richer payload.
        official_id=""
        if data is None or _game_center_needs_enrichment(data,competition):
            official_id=_resolve_game_center_event_id(competition,requested_id,hints,allow_fetch=True)
            if official_id and official_id.startswith("hl-"): official_id=""
            if official_id:
                try:
                    official_cached=_game_center_cached_record(competition,official_id)
                    if official_cached and time.time()<float(official_cached.get("expiresAt") or 0) and not _game_center_needs_enrichment(official_cached.get("data"),competition):
                        official_data=official_cached.get("data")
                    else:
                        official_data=_game_center_refresh(competition,official_id,hints=hints)
                    data=_game_center_merge(data,official_data) if data else official_data
                except Exception as enrich_exc:
                    # Keep a valid same-provider shell visible rather than turning a
                    # temporary fallback outage into a blank Game Center. Partial
                    # snapshots receive a short TTL and are retried centrally.
                    if data is None: raise
                    data=copy.deepcopy(data); data["enrichmentError"]=f"{type(enrich_exc).__name__}: {enrich_exc}"

        # If there was no Highlightly path, the official id is the canonical record.
        if data is None:
            if not official_id: official_id=_resolve_game_center_event_id(competition,requested_id,hints,allow_fetch=True)
            if not official_id: raise ValueError(f"Unable to resolve {competition} Game Center event from score identity")
            resolved_id=official_id; data=_game_center_refresh(competition,official_id,hints=hints)
        elif not resolved_id:
            resolved_id=official_id or _resolve_game_center_event_id(competition,requested_id,hints,allow_fetch=True)

        resolved_id=resolved_id or official_id
        if not resolved_id: raise ValueError(f"Unable to resolve {competition} Game Center event from score identity")
        competition,resolved_id=_game_center_validate_id(competition,resolved_id)
        # Persist the merged result under the id the browser will follow. Also keep
        # the official record warm separately when we used a cross-provider merge.
        _game_center_store(competition,resolved_id,data)
        if requested_id and requested_id!=resolved_id:
            GAME_CENTER_REPOSITORY.put_alias(competition,requested_id,resolved_id,hints.get("date") or "",hints.get("away") or "",hints.get("home") or "")
        state={"lastOk":time.time(),"lastError":"","retryAt":0.0,"resolvedEventId":resolved_id,"quality":_game_center_quality(data,competition)}
        with GAME_CENTER_JOB_STATE_LOCK:
            GAME_CENTER_JOB_STATE[request_key]=state
            GAME_CENTER_JOB_STATE[f"{competition}:{resolved_id}"]=state
            if requested_id: GAME_CENTER_JOB_STATE[f"{competition}:{requested_id}"]=state
        return "WARMED"
    except Exception as exc:
        state={"lastOk":0.0,"lastError":f"{type(exc).__name__}: {exc}","retryAt":time.time()+5.0,"resolvedEventId":""}
        with GAME_CENTER_JOB_STATE_LOCK:
            GAME_CENTER_JOB_STATE[request_key]=state
            if requested_id: GAME_CENTER_JOB_STATE[f"{competition}:{requested_id}"]=state
        raise

def _game_center_validate_request(competition,event_id):
    competition=str(competition or "").upper(); event_id=str(event_id or "")
    if competition not in GAME_CENTER_SUPPORTED:
        raise NotImplementedError(f"Game Center provider not implemented for {competition}")
    # This is an alias from an arbitrary score provider, not yet a provider id.
    # Keep the path bounded but do not impose MLB gamePk rules until resolution.
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}",event_id):
        raise ValueError(f"{competition} Game Center requires a valid event alias")
    return competition,event_id


def schedule_game_center_prepare(competition,event_id,priority,hints=None):
    try: competition,event_id=_game_center_validate_request(competition,event_id)
    except Exception: return None
    hints=hints or {}
    key=_game_center_request_key(competition,event_id,hints)
    return GAME_CENTER_WORK_SCHEDULER.submit(f"game-center:{key}",int(priority),_game_center_prepare_job,competition,event_id,hints)


def _game_center_event_status(row):
    row=row or {}
    if row.get("gamePk"):
        return str(((row.get("status") or {}).get("abstractGameState") or (row.get("status") or {}).get("detailedState") or "")).lower()
    state=row.get("state") or {}
    return " ".join(str(x or "") for x in (state.get("report"),state.get("status"),state.get("description"),row.get("status"))).lower()


def prewarm_game_centers_for_events(competition,events,date,today=False,provider_hint=""):
    accepted=live=final=scheduled=0
    competition=str(competition or "").upper(); indexed=_index_game_center_events(competition,events,date,provider_hint or "official")
    for row in indexed[:64]:
        event_id=str(row.get("providerEventId") or "")
        if not event_id: continue
        # The source rows used for the index are already authoritative provider ids.
        # Still pass identity hints so the same scheduler path is exercised as a click.
        original=next((x for x in list(events or []) if str((x or {}).get("gamePk") or (x or {}).get("eventId") or (x or {}).get("matchId") or (x or {}).get("id") or "")==event_id),{})
        status=_game_center_event_status(original)
        is_live=bool(re.search(r"live|progress|quarter|half|period|inning|^in$",status)) and not re.search(r"final|post|complete",status)
        is_final=bool(re.search(r"final|post|complete|game over|finished",status))
        if is_live: priority=MEDIA_PRIORITY["VISIBLE_SCORE"]; live+=1
        elif is_final: priority=MEDIA_PRIORITY["NEARBY_SCORE"] if today else MEDIA_PRIORITY["RECENT_FINAL"]; final+=1
        else: priority=MEDIA_PRIORITY["BACKGROUND_DISCOVERY"]; scheduled+=1
        hints={"date":str(date or "")[:10],"away":(row.get("awayTeam") or {}).get("abbreviation") or (row.get("awayTeam") or {}).get("name") or "","home":(row.get("homeTeam") or {}).get("abbreviation") or (row.get("homeTeam") or {}).get("name") or "","start":row.get("scheduledAt") or "","gameNumber":row.get("gameNumber") or 0,"provider":provider_hint}
        target_id=event_id; target_hints=dict(hints)
        if str(provider_hint or '').lower()=="highlightly":
            official=_resolve_game_center_event_id(competition,event_id,hints,allow_fetch=False)
            if official and not str(official).startswith("hl-"):
                GAME_CENTER_REPOSITORY.put_alias(competition,event_id,official,hints.get("date") or "",hints.get("away") or "",hints.get("home") or "")
                target_id=official; target_hints["provider"]="mlb-stats" if competition=="MLB" else "espn"
        if schedule_game_center_prepare(competition,target_id,priority,hints=target_hints): accepted+=1
    return {"competition":competition,"date":date,"queued":accepted,"live":live,"final":final,"scheduled":scheduled}


def prewarm_game_centers_for_games(games,date,today=False):
    return prewarm_game_centers_for_events("MLB",games,date,today)


def prewarm_espn_game_centers(competition,date,today=False):
    rows=_espn_scoreboard(competition,date,MEDIA_PREWARM_STATE.get("timezone") or "",MEDIA_PREWARM_STATE.get("utcOffsetMinutes"))
    return prewarm_game_centers_for_events(competition,rows,date,today)


def _game_center_get(competition,event_id,force=False):
    competition,event_id=_game_center_validate_id(competition,event_id)
    now=time.time(); cached=_game_center_cached_record(competition,event_id)
    if cached and not force:
        if now<float(cached.get("expiresAt") or 0): return cached["data"],"REPO-HIT"
        # Stale-while-revalidate. A user click never waits if localhost already has
        # a usable snapshot; the central scheduler refreshes it behind the scenes.
        schedule_game_center_prepare(competition,event_id,MEDIA_PRIORITY["VISIBLE_SCORE"])
        return cached["data"],"STALE"
    data=_game_center_refresh(competition,event_id)
    return data,"REFRESH" if force else "MISS"


def _game_center_open(competition,event_id,force=False,hints=None):
    """Return a repository snapshot or queue canonical identity preparation.

    The route accepts a score-provider alias. Only a resolved MLB/ESPN provider id
    is ever allowed to reach the detailed-stat API. This is what prevents the
    `Unknown` cache poison and first-game-only behavior seen on Android.
    """
    competition,event_id=_game_center_validate_request(competition,event_id)
    hints=hints or {}; now=time.time(); request_key=_game_center_request_key(competition,event_id,hints)
    resolved_id=_resolve_game_center_event_id(competition,event_id,hints,allow_fetch=False)
    with GAME_CENTER_JOB_STATE_LOCK:
        job_state=dict(GAME_CENTER_JOB_STATE.get(request_key) or GAME_CENTER_JOB_STATE.get(f"{competition}:{event_id}") or {})
    # A completed worker may know the resolution even before the in-memory event index
    # is consulted again (for example after an alias was persisted to SQLite).
    if not resolved_id: resolved_id=str(job_state.get("resolvedEventId") or GAME_CENTER_REPOSITORY.resolve_alias(competition,event_id) or "")
    cached=_game_center_cached_record(competition,resolved_id) if resolved_id else None
    if not cached and job_state.get("lastError") and now<float(job_state.get("retryAt") or 0) and not force:
        raise RuntimeError(str(job_state.get("lastError")))
    if force and job_state.get("lastError"):
        with GAME_CENTER_JOB_STATE_LOCK:
            GAME_CENTER_JOB_STATE.pop(request_key,None); GAME_CENTER_JOB_STATE.pop(f"{competition}:{event_id}",None)
    if cached:
        fresh=now<float(cached.get("expiresAt") or 0)
        partial=_game_center_needs_enrichment(cached.get("data"),competition)
        if force or not fresh or partial:
            schedule_game_center_prepare(competition,resolved_id,MEDIA_PRIORITY["TOUCH_INTENT"] if (force or partial) else MEDIA_PRIORITY["VISIBLE_SCORE"],hints=hints)
        state="PARTIAL" if partial else ("REPO-HIT" if fresh and not force else "STALE")
        return cached["data"],state,False,resolved_id
    schedule_game_center_prepare(competition,event_id,MEDIA_PRIORITY["TOUCH_INTENT"],hints=hints)
    return None,"PENDING",True,resolved_id



def _history_event_media_no_quota(league,date,row):
    """Low-priority historical media discovery without spending YouTube/Highlightly quota."""
    league=str(league or '').upper(); row=row or {}
    away=(row.get('awayTeam') or row.get('away') or {})
    home=(row.get('homeTeam') or row.get('home') or {})
    away_name=str(away.get('name') or away.get('displayName') or away.get('abbreviation') or '').strip()
    home_name=str(home.get('name') or home.get('displayName') or home.get('abbreviation') or '').strip()
    event_id=str(row.get('espnEventId') or row.get('matchId') or row.get('eventId') or row.get('id') or '')
    if not away_name or not home_name: return []
    items=[]
    try:
        if event_id:
            items.extend(_espn_event_video_results(event_id,league,away_name,home_name,max_items=12))
    except Exception: pass
    try:
        items.extend(_espn_search_video_results(league,away_name,home_name,max_items=8))
    except Exception: pass
    if league=='NFL':
        # Historical cataloging is exhaustive, not first-playable-wins. Team-site
        # media may contain a better package than an ESPN clip already found.
        try: items.extend(_nfl_team_site_video_results(date,away_name,home_name,max_items=6))
        except Exception: pass
    out=[]; seen=set()
    for item in items:
        if not isinstance(item,dict): continue
        item=dict(item)
        item.setdefault('league',league); item.setdefault('competitionId',league)
        item['date']=str(item.get('date') or date)[:10]; item.setdefault('gameDate',date); item.setdefault('__sbbDate',date)
        # Do not stamp target event/team identity onto broad discovery results.
        # Association must be proven later by the v5 matcher.
        key=str(item.get('id') or item.get('youtubeId') or item.get('mediaUrl') or item.get('externalUrl') or '')
        if not key or key in seen: continue
        seen.add(key); out.append(item)
    return out


def _history_row_completed(row):
    row=row or {}
    if bool(row.get('completed')): return True
    state=row.get('state') or {}
    text=' '.join(str(x or '') for x in (state.get('report'),state.get('status'),state.get('description'),row.get('status'))).lower()
    return bool(re.search(r'\bfinal\b|finished|complete|game over|post',text))

def _history_gap_event_ready(date,row):
    """Treat clearly historical events as completed even when legacy event_json omitted a final flag.

    Older normalized rows in the persistent catalog frequently contain teams/scores but
    not the original provider status object. v3.0.6 silently skipped those rows in the
    Green-gap worker because `_history_row_completed()` returned False. For any date
    before today, absence of an explicit scheduled/live/postponed/cancelled marker is
    sufficient for upgrade work.
    """
    if _history_row_completed(row): return True
    row=row or {}; state=row.get('state') or {}
    text=' '.join(str(x or '') for x in (state.get('report'),state.get('status'),state.get('description'),row.get('status'))).lower()
    if re.search(r'cancel|postpon|scheduled|pre[- ]?game|not started|in progress|live',text): return False
    try:
        event_date=datetime.strptime(str(date)[:10],'%Y-%m-%d').date()
        today=datetime.strptime(_client_date_iso(0,MEDIA_PREWARM_STATE.get('timezone') or '',MEDIA_PREWARM_STATE.get('utcOffsetMinutes')),'%Y-%m-%d').date()
        return event_date < today
    except Exception:
        return False


def _history_row_event_id(row):
    row=row or {}
    return str(row.get('espnEventId') or row.get('scoreEventId') or row.get('matchId') or row.get('eventId') or row.get('id') or row.get('gamePk') or '')


def _history_team_name(row,side):
    row=row or {}; team=row.get(f'{side}Team') or row.get(side) or {}
    if isinstance(team,dict):
        return str(team.get('displayName') or team.get('name') or team.get('shortName') or team.get('abbreviation') or team.get('abbr') or '').strip()
    return str(team or '').strip()


def _history_norm_team(value):
    return re.sub(r'[^a-z0-9]+',' ',str(value or '').lower()).strip()


def _history_team_aliases(value):
    text=_history_norm_team(value); parts=text.split()
    aliases={text}
    if parts: aliases.add(parts[-1])
    # Common city-only noise is weaker than a nickname, so keep two-token tail too.
    if len(parts)>=2: aliases.add(' '.join(parts[-2:]))
    return {x for x in aliases if len(x)>=2}


def _history_media_match_evidence(item,row):
    """Classify scope first, then prove an event association with v4 evidence."""
    item=dict(item or {}); row=dict(row or {})
    away=_history_team_name(row,'away'); home=_history_team_name(row,'home')
    league=str(row.get('competitionId') or row.get('__sbbLeague') or row.get('league') or '').upper()
    date=str(row.get('__sbbDate') or row.get('date') or '')[:10]
    scoped=annotate_media_scope(item,league=league,date=date,away=away,home=home)
    evidence=match_media_to_event(scoped,row,league=league,date=date)
    return scoped,evidence


def _history_media_matches_row(item,row):
    scoped,evidence=_history_media_match_evidence(item,row)
    return bool(scoped.get('mediaScope')==MEDIA_SCOPE_GAME and evidence.get('associationState')=='ASSIGNED')



def _history_validate_native_asset(item,timeout=6):
    """Positively probe one direct historical media URL before advertising green."""
    row=dict(item or {}); url=str(row.get('mediaUrl') or '').strip()
    if not url: return row
    headers={'User-Agent':'Mozilla/5.0 SportsBigBoard/4.0.2','Accept':'video/*,*/*;q=0.8','Range':'bytes=0-0'}
    if 'espn' in url.lower(): headers['Referer']='https://www.espn.com/'
    try:
        req=Request(url,headers=headers)
        with urlopen(req,timeout=timeout) as resp:
            status=int(getattr(resp,'status',200) or 200); content_type=str(resp.headers.get('Content-Type') or '').lower()
            try: resp.read(1)
            except Exception: pass
        good=status in (200,206) and (not content_type or any(x in content_type for x in ('video/','application/octet-stream','mpegurl','application/vnd.apple')))
        if good:
            row['verifiedPlayable']=True; row['validationState']='VERIFIED'; row['nativeValidated']=True; row['nativeValidation']='range-probe'
            row['historyVerifiedAt']=time.time()
        else:
            row['verifiedPlayable']=False; row['validationState']='CANDIDATE'; row['nativeValidated']=False; row['nativeValidation']=f'probe-rejected:{status}:{content_type}'
    except Exception as exc:
        row['verifiedPlayable']=False; row['validationState']='CANDIDATE'; row['nativeValidated']=False; row['nativeValidation']=f'probe-failed:{type(exc).__name__}'
    return row


def _history_promote_authoritative_recap(item):
    """Promote exact-event provider video into Green when metadata tells a game story.

    Event identity is already authoritative in ESPN summary / MLB game-content lanes,
    so we do not require both team names in every title. This catches 2–6 minute
    result-story videos such as "Player X leads Club Y to win" without turning
    ordinary short single-play clips into full recaps.
    """
    out=dict(item or {}); dur=int(out.get('durationSeconds') or out.get('duration') or 0)
    if dur<=0 or dur>420: return out
    text=' '.join(str(out.get(k) or '') for k in ('title','subtitle','description')).lower()
    source_type=str(out.get('sourceType') or '').lower(); source=str(out.get('sourceLabel') or out.get('source') or '').lower()
    authoritative=source_type in {'espn-event-video','mlb-game-content'} or ('mlb stats api' in source and bool(out.get('gamePk')))
    if not authoritative: return out
    if re.search(r'press conference|interview|preview|prediction|fantasy|betting|podcast|top plays?|best plays?',text): return out
    explicit=bool(re.search(r'full game highlights|game highlights|game recap|game summary|game story|game wrap|wrap[- ]?up|highlights from|recap of|story of the game',text))
    result_story=bool(90<=dur<=420 and re.search(r'\b(win|wins|won|victory|defeat|defeats|beat|beats|edged|tops|topples|rall(?:y|ies)|leads?|led|powers?|lifts?)\b',text))
    if explicit or result_story:
        out['overview']=True; out['programType']='recap'; out['authoritativeRecapPromotion']=True
    return out

def _history_decorate_event_media(league,date,row,items):
    league=str(league or '').upper(); event_id=_history_row_event_id(row)
    away=_history_team_name(row,'away'); home=_history_team_name(row,'home')
    out=[]; collections=[]; seen=set()
    for raw in items or []:
        if not isinstance(raw,dict): continue
        item=dict(raw); item['league']=league; item['competitionId']=league
        item['date']=str(item.get('date') or date)[:10]; item['gameDate']=str(item.get('gameDate') or date)[:10]; item['__sbbDate']=date
        item,evidence=_history_media_match_evidence(item,row)
        if item.get('mediaScope') in MEDIA_COLLECTION_SCOPES:
            collections.append(item); continue
        if item.get('mediaScope')!=MEDIA_SCOPE_GAME or evidence.get('associationState')!='ASSIGNED':
            continue
        item['associationConfidence']=float(evidence.get('associationConfidence') or 0)
        item['associationMethod']=str(evidence.get('associationMethod') or '')
        item['associationEvidence']=str(evidence.get('associationEvidence') or '')
        item['eventMatcherVersion']=int(evidence.get('matcherVersion') or 0)
        # Sporting-event authority is assigned only AFTER scope + association pass.
        if event_id:
            item['matchId']=event_id; item['scoreEventId']=event_id; item['canonicalEventKey']=f'{league}:{event_id}'
            if row.get('espnEventId') or row.get('source')=='ESPN': item['espnEventId']=str(row.get('espnEventId') or event_id)
        item.setdefault('away',away); item.setdefault('home',home)
        item=_history_promote_authoritative_recap(item)
        if item.get('mediaUrl'):
            item=_history_validate_native_asset(item)
        if item.get('verifiedPlayable') and (item.get('youtubeId') or item.get('mediaUrl')):
            item['validationState']='VERIFIED'; item['historyVerifiedAt']=float(item.get('historyVerifiedAt') or time.time()); item['historyDiscoveryVersion']=HISTORY_DISCOVERY_VERSION
        elif item.get('youtubeId') or item.get('mediaUrl'):
            item.setdefault('validationState','CANDIDATE')
        item=annotate_media_tier(item)
        key=str(item.get('youtubeId') or item.get('mediaUrl') or item.get('externalUrl') or item.get('id') or '')
        if not key or key in seen: continue
        seen.add(key); out.append(item)
    if collections:
        _history_capture_collection_catalog(league,date,collections)
    return out


def _history_validate_existing_candidates(date,league,row,candidates):
    """Promote already-known GAME candidates before any new discovery/search."""
    league=str(league or '').upper(); date=str(date or '')[:10]
    away=_history_team_name(row,'away'); home=_history_team_name(row,'home')
    scoped=[]
    for raw in candidates or []:
        if not isinstance(raw,dict): continue
        item=annotate_media_scope(raw,league=league,date=date,away=away,home=home)
        if item.get('mediaScope')==MEDIA_SCOPE_GAME and _history_media_matches_row(item,row): scoped.append(item)
    if not scoped: return []
    youtube_ids=[str(x.get('youtubeId') or '') for x in scoped if x.get('youtubeId')]
    detail_by={}
    key=read_youtube_key()
    if youtube_ids and key:
        try:
            for offset in range(0,len(youtube_ids),50):
                chunk=list(dict.fromkeys(youtube_ids[offset:offset+50]))
                payload=youtube_fetch_json(f"{YOUTUBE_API_BASE}/videos?{urlencode({'part':'snippet,contentDetails,status','id':','.join(chunk),'key':key})}",timeout=12)
                for vd in payload.get('items') or []:
                    if isinstance(vd,dict): detail_by[str(vd.get('id') or '')]=vd
        except Exception:
            detail_by={}
    validated=[]
    for raw in scoped:
        item=dict(raw); item['candidateValidationState']='CHECKED'
        if item.get('mediaUrl'):
            item=_history_validate_native_asset(item)
            item['candidateValidationState']='PROMOTED' if item.get('verifiedPlayable') else 'REJECTED'
            if not item.get('verifiedPlayable'): item['candidateRejectionReason']=str(item.get('nativeValidation') or 'native validation failed')
        elif item.get('youtubeId') and key:
            vd=detail_by.get(str(item.get('youtubeId')))
            if vd and _youtube_video_available_in_us(vd):
                sn=vd.get('snippet') or {}; cd=vd.get('contentDetails') or {}
                item['title']=str(sn.get('title') or item.get('title') or ''); item['description']=str(sn.get('description') or item.get('description') or '')
                item['durationSeconds']=_iso8601_duration_seconds(cd.get('duration')) or item.get('durationSeconds') or 0; item['duration']=item['durationSeconds']
                item['verifiedPlayable']=True; item['embedValidated']=True; item['validationState']='VERIFIED'; item['historyVerifiedAt']=time.time(); item['candidateValidationState']='PROMOTED'
            else:
                item['verifiedPlayable']=False; item['validationState']='FAILED'; item['candidateValidationState']='REJECTED'; item['candidateRejectionReason']='YouTube videos.list did not confirm US-embeddable playback'
        validated.append(item)
    decorated=_history_decorate_event_media(league,date,row,validated)
    if decorated:
        event_id=_history_row_event_id(row); HISTORY_REPOSITORY.put_media(date,league,decorated,merge=True); HISTORY_REPOSITORY.put_event_media(date,league,event_id,decorated)
    return [x for x in decorated if x.get('verifiedPlayable')]



def _history_event_needs_native_refresh(state,row,max_age_seconds=5.5*60*60):
    """Return True when a final relies on an old direct native URL.

    YouTube ids are durable. ESPN/club MP4 and HLS URLs can be signed, so a date
    may be fully indexed yet still need a cheap native refresh before playback.
    """
    state=state or {}; saved=float(state.get('mediaSavedAt') or 0)
    if not saved or time.time()-saved <= max_age_seconds: return False
    matching=[x for x in (state.get('media') or []) if isinstance(x,dict) and _history_media_matches_row(x,row)]
    durable=any(x.get('verifiedPlayable') and x.get('youtubeId') for x in matching)
    native=any(x.get('verifiedPlayable') and x.get('mediaUrl') for x in matching)
    return bool(native and not durable)


def _history_playable_tiers(items):
    tiers=[]
    for item in items or []:
        tier=str((item or {}).get('recapTier') or 'blue')
        if tier not in HISTORY_TIER_PRIORITY: tier='blue'
        if tier not in tiers: tiers.append(tier)
    tiers.sort(key=lambda x:HISTORY_TIER_PRIORITY.get(x,0),reverse=True)
    return tiers


def _history_best_tier(items):
    tiers=_history_playable_tiers(items)
    return tiers[0] if tiers else ''


def _history_quality_complete(record):
    details=_history_discovery_details(record)
    return bool(int(details.get('discoveryVersion') or 0)>=HISTORY_DISCOVERY_VERSION and details.get('qualityComplete') is True)


def _history_quality_missing_tiers(best_tier):
    best=str(best_tier or '')
    if best not in HISTORY_TIER_ORDER:
        return list(HISTORY_TIER_ORDER)
    idx=HISTORY_TIER_ORDER.index(best)
    return list(HISTORY_TIER_ORDER[:idx])


def _history_upgrade_retry_seconds(date,best_tier):
    best=str(best_tier or 'blue')
    try:
        age=max(0,(datetime.now(timezone.utc).date()-datetime.strptime(str(date)[:10],'%Y-%m-%d').date()).days)
    except Exception:
        age=30
    table=HISTORY_UPGRADE_RETRY_RECENT if age<=7 else HISTORY_UPGRADE_RETRY_ARCHIVE
    return int(table.get(best,24*60*60))


def _history_discovery_details(record):
    return dict((record or {}).get('discovery') or {})


def _history_catalog_complete(record):
    details=_history_discovery_details(record)
    return bool(int(details.get('discoveryVersion') or 0)>=HISTORY_DISCOVERY_VERSION and details.get('catalogComplete') is True)


def _history_free_lanes_complete(record):
    details=_history_discovery_details(record)
    return bool(int(details.get('discoveryVersion') or 0)>=HISTORY_DISCOVERY_VERSION and details.get('freeLaneComplete') is True)


def _history_inventory(date):
    """Return date-scoped catalog inventory with source and quality truth separated.

    catalogComplete means all currently applicable provider lanes were inventoried.
    qualityComplete means the event has reached the preferred Gold tier. A lower-tier
    event remains playable, but upgradeEligible stays true and the cloud backfill can
    revisit it when nextRetryAt becomes due.
    """
    day=HISTORY_REPOSITORY.get_day(date); leagues={}
    total_games=completed=media_items=playable_media_items=candidate_media=archived_only_items=playable_games=0
    background_complete_games=catalog_complete_games=quality_complete_games=upgrade_eligible_games=upgrade_due_games=0
    tier_counts={'green':0,'extended':0,'gold':0,'blue':0}; now=time.time()
    for league in HISTORY_LEAGUES:
        state=(day.get('leagues') or {}).get(league) or {}
        scores=list(state.get('scores') or []); media=[annotate_media_tier(x) for x in (state.get('media') or []) if isinstance(x,dict)]
        finals=[x for x in scores if _history_row_completed(x)]
        playable=[x for x in media if x.get('verifiedPlayable') and x.get('runtimeCatalogState')!='FAILED' and (x.get('youtubeId') or x.get('mediaUrl'))]
        candidates=[x for x in media if not x.get('verifiedPlayable') and str(x.get('validationState') or '').upper() in ('CANDIDATE','EXTERNAL')]
        archived_only=[x for x in media if x not in playable]
        covered=0; searched=0; background_done=0; catalog_done=0; quality_done=0; upgrade_eligible=0; upgrade_due=0
        event_states={}; event_needs_retry=False; event_needs_upgrade=False
        for row in finals:
            event_id=_history_row_event_id(row)
            event_playable=[item for item in playable if _history_media_matches_row(item,row)]
            if event_playable: covered+=1
            record=HISTORY_REPOSITORY.get_event(date,league,event_id) if event_id else None
            details=_history_discovery_details(record)
            version_ok=int(details.get('discoveryVersion') or 0)>=HISTORY_DISCOVERY_VERSION
            if record and float(record.get('lastDiscoveryAt') or 0)>0 and version_ok: searched+=1
            ds=str((record or {}).get('discoveryState') or 'UNKNOWN')
            if event_id: event_states[event_id]=ds
            free_complete=_history_free_lanes_complete(record)
            catalog_complete=_history_catalog_complete(record)
            quality_complete=_history_quality_complete(record)
            if free_complete: background_done+=1
            if catalog_complete: catalog_done+=1
            if quality_complete: quality_done+=1
            best_tier=_history_best_tier(event_playable)
            retry_at=float((record or {}).get('nextRetryAt') or 0)
            native_refresh=_history_event_needs_native_refresh(state,row)
            # A version mismatch is an automatic soft reindex. For current-version
            # records, lower-tier playable media is due for another upgrade pass only
            # after the persisted retry window expires.
            quality_incomplete=not quality_complete
            if quality_incomplete: upgrade_eligible+=1; event_needs_upgrade=True
            quality_retry_due=bool(quality_incomplete and (not version_ok or not retry_at or retry_at<=now))
            state_retry_due=bool(record and retry_at and retry_at<=now and ds in ('VERIFIED_PARTIAL','VERIFIED_UPGRADE_PENDING','SEARCHED_EMPTY','CANDIDATE_ONLY','DEGRADED_PROVIDER'))
            if quality_retry_due: upgrade_due+=1
            if native_refresh or state_retry_due or quality_retry_due: event_needs_retry=True
            # Preserve useful quality diagnostics even before a v8 pass has rewritten
            # discovery JSON. This does not suppress the version-driven reindex.
            if event_id and best_tier and not details.get('bestTier'):
                event_states[event_id]=f"{ds}:{best_tier}"
        lt={'green':0,'extended':0,'gold':0,'blue':0}
        for item in playable:
            tier=str(item.get('recapTier') or 'blue'); tier=tier if tier in lt else 'blue'; lt[tier]+=1; tier_counts[tier]+=1
        discovery=state.get('discovery') or {}; discovery_version=int(discovery.get('discoveryVersion') or 0)
        durable_games=sum(1 for row in finals if any(x.get('verifiedPlayable') and x.get('runtimeCatalogState')!='FAILED' and x.get('youtubeId') and _history_media_matches_row(x,row) for x in media))
        leagues[league]={
            'games':len(scores),'completed':len(finals),'mediaItems':len(media),'playableMedia':len(playable),'candidateMedia':len(candidates),
            'archivedOnlyMedia':len(archived_only),'playableGames':covered,'durablePlayableGames':durable_games,
            'needsRefresh':bool(event_needs_retry),'needsUpgrade':bool(event_needs_upgrade),'upgradeDue':bool(upgrade_due),'discoveryVersion':discovery_version,
            'searchedGames':searched,'backgroundCompleteGames':background_done,'catalogCompleteGames':catalog_done,
            'qualityCompleteGames':quality_done,'upgradeEligibleGames':upgrade_eligible,'upgradeDueGames':upgrade_due,
            'deepComplete':bool(background_done>=len(finals)) if finals else True,
            'catalogComplete':bool(catalog_done>=len(finals)) if finals else True,
            'qualityComplete':bool(quality_done>=len(finals)) if finals else True,
            'eventStates':event_states,'tiers':lt,
            'scoresSavedAt':state.get('scoresSavedAt') or 0,'mediaSavedAt':state.get('mediaSavedAt') or 0,
        }
        total_games+=len(scores); completed+=len(finals); media_items+=len(media); playable_media_items+=len(playable); candidate_media+=len(candidates); archived_only_items+=len(archived_only); playable_games+=covered
        background_complete_games+=background_done; catalog_complete_games+=catalog_done; quality_complete_games+=quality_done; upgrade_eligible_games+=upgrade_eligible; upgrade_due_games+=upgrade_due
    return {'date':date,'games':total_games,'completedGames':completed,'mediaItems':media_items,'playableMedia':playable_media_items,'candidateMedia':candidate_media,
            'archivedOnlyMedia':archived_only_items,'playableGames':playable_games,
            'backgroundCompleteGames':background_complete_games,'catalogCompleteGames':catalog_complete_games,
            'qualityCompleteGames':quality_complete_games,'upgradeEligibleGames':upgrade_eligible_games,'upgradeDueGames':upgrade_due_games,
            'catalogComplete':bool(catalog_complete_games>=completed) if completed else True,
            'qualityComplete':bool(quality_complete_games>=completed) if completed else True,
            'needsUpgrade':bool(upgrade_eligible_games),'upgradeDue':bool(upgrade_due_games),
            'needsRefresh':any(bool(x.get('needsRefresh')) for x in leagues.values()),
            'tiers':tier_counts,'leagues':leagues}

def _history_discovery_state(date):
    with HISTORY_DISCOVERY_LOCK:
        state=copy.deepcopy(HISTORY_DISCOVERY_STATE.get(date) or {})
    inv=_history_inventory(date)
    if not state:
        state={'date':date,'status':'IDLE','running':False,'searchedGames':0,'totalGames':inv['completedGames'],'currentLeague':'','currentGame':'','lastError':'','revision':0,'startedAt':0,'finishedAt':0}
    state['inventory']=inv
    state['totalGames']=max(int(state.get('totalGames') or 0),int(inv.get('completedGames') or 0))
    state['youtubeConfigured']=bool(read_youtube_key())
    state['youtubeSearchBudget']=_history_youtube_budget_status()
    state['youtubeGateway']=YOUTUBE_GATEWAY.status()
    return state


def _history_set_discovery_state(date,**patch):
    with HISTORY_DISCOVERY_LOCK:
        current=dict(HISTORY_DISCOVERY_STATE.get(date) or {'date':date,'status':'IDLE','running':False,'searchedGames':0,'totalGames':0,'currentLeague':'','currentGame':'','lastError':'','revision':0,'startedAt':0,'finishedAt':0})
        current.update(patch); current['date']=date; current['revision']=int(current.get('revision') or 0)+1
        HISTORY_DISCOVERY_STATE[date]=current
        return copy.deepcopy(current)


def _history_score_lock(date,league):
    key=f"{str(date)[:10]}:{str(league).upper()}"
    with HISTORY_SCORE_FETCH_LOCK:
        return HISTORY_SCORE_FETCH_LOCKS.setdefault(key,threading.Lock())


def _history_get_league_scores(date,league,tz_value="",utc_offset_minutes=None,force=False):
    """Canonical historical score read/fetch for one league/date.

    Browser ribbon hydration and server media discovery use this exact function,
    so they cannot build two subtly different event inventories. Concurrent reads
    coalesce behind one league/date lock and saved empty scoreboards are valid data.
    """
    date=str(date or '')[:10]; league=str(league or '').upper()
    if league not in HISTORY_LEAGUES: return [],'UNSUPPORTED',False,'unsupported league'
    lock=_history_score_lock(date,league)
    with lock:
        state=HISTORY_REPOSITORY.get_league(date,league)
        cached=list(state.get('scores') or [])
        if state.get('scoresSavedAt') and not force:
            return cached,'HISTORY_DB',True,''
        errors=[]
        try:
            data=_espn_scoreboard(league,date,tz_value,utc_offset_minutes)
            HISTORY_REPOSITORY.put_scores(date,league,data)
            return data,'ESPN',False,''
        except Exception as exc:
            errors.append(f'ESPN {type(exc).__name__}: {exc}')
        # MLB has a strong official score authority independent of ESPN and
        # Highlightly. Use it before falling back to an older persisted snapshot.
        if league=='MLB':
            try:
                data=normalized_stats_matches(date)
                HISTORY_REPOSITORY.put_scores(date,league,data)
                return data,'MLB Stats API',False,''
            except Exception as exc:
                errors.append(f'MLB Stats {type(exc).__name__}: {exc}')
        # Never replace a previously known historical slate with an upstream error.
        if state.get('scoresSavedAt'):
            return cached,'HISTORY_DB_STALE',True,' | '.join(errors[-3:])
        return [],'UNAVAILABLE',False,' | '.join(errors[-3:])


def _history_ensure_scores(date):
    tz_value=MEDIA_PREWARM_STATE.get('timezone') or ''; utc_offset=MEDIA_PREWARM_STATE.get('utcOffsetMinutes')
    rows={}; errors=[]
    def one(league):
        data,source,cached,error=_history_get_league_scores(date,league,tz_value,utc_offset,force=False)
        return league,data,error
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs=[ex.submit(one,lg) for lg in HISTORY_LEAGUES]
        for fut in as_completed(futs):
            lg,data,err=fut.result(); rows[lg]=data
            if err: errors.append(f'{lg}: {err}')
    return rows,errors




def _history_find_score_row(date,league,event_id):
    state=HISTORY_REPOSITORY.get_league(date,league)
    wanted=str(event_id or '')
    for row in state.get('scores') or []:
        if _history_row_event_id(row)==wanted:
            return row
    return None


def _history_playback_plan(date,league,event_id):
    row=_history_find_score_row(date,league,event_id)
    record=HISTORY_REPOSITORY.get_event(date,league,event_id)
    media=HISTORY_REPOSITORY.event_media(date,league,event_id,include_failed=True)
    playable=[x for x in media if isinstance(x,dict) and x.get('verifiedPlayable') and x.get('runtimeCatalogState')!='FAILED' and (x.get('youtubeId') or x.get('mediaUrl'))]
    playable=[annotate_media_tier(x) for x in playable]
    playable.sort(key=lambda x:(HISTORY_TIER_PRIORITY.get(str(x.get('recapTier') or 'blue'),0),bool(x.get('overview')),int(x.get('importance') or 0)),reverse=True)
    return {'date':str(date)[:10],'league':str(league).upper(),'eventId':str(event_id),'event':row or (record or {}).get('event') or {},'discovery':record or {},'media':media,'playable':playable,'primary':playable[0] if playable else None}


def _history_event_catalog_state(date,league,row):
    event_id=_history_row_event_id(row)
    record=HISTORY_REPOSITORY.get_event(date,league,event_id) if event_id else None
    media=HISTORY_REPOSITORY.event_media(date,league,event_id,include_failed=True) if event_id else []
    playable=[x for x in media if isinstance(x,dict) and x.get('verifiedPlayable') and x.get('runtimeCatalogState')!='FAILED' and (x.get('youtubeId') or x.get('mediaUrl'))]
    candidates=[x for x in media if isinstance(x,dict) and x.get('validationState') in ('CANDIDATE','EXTERNAL')]
    return record or {},media,playable,candidates


def _history_discover_event(date,league,row,force=False,allow_search_rescue=True):
    """Discover and persist the media manifest for one final event.

    v4.0.2 treats *source exhaustion* and *quality satisfaction* as independent
    dimensions. Blue/Purple/Green assets make an event immediately playable and
    are always retained, but only Gold satisfies the preferred historical quality
    target. Lower-tier events remain upgrade-eligible and are revisited on a gentle
    persistent retry cadence by the always-on cloud catalog.
    """
    league=str(league or '').upper(); date=str(date or '')[:10]; row=dict(row or {})
    event_id=_history_row_event_id(row); away=_history_team_name(row,'away'); home=_history_team_name(row,'home')
    if not event_id:
        return {'eventId':'','state':'ERROR','media':[],'playable':[],'errors':['event id unavailable']}
    HISTORY_REPOSITORY.upsert_event(date,league,event_id,row)
    previous,existing,existing_playable,existing_candidates=_history_event_catalog_state(date,league,row)
    best_before_candidate_promotion=_history_best_tier(existing_playable)
    promoted=_history_validate_existing_candidates(date,league,row,existing_candidates)
    if promoted:
        previous,existing,existing_playable,existing_candidates=_history_event_catalog_state(date,league,row)
    now=time.time(); previous_details=_history_discovery_details(previous)
    previous_version_ok=int(previous_details.get('discoveryVersion') or 0)>=HISTORY_DISCOVERY_VERSION
    previous_catalog_complete=_history_catalog_complete(previous)
    previous_quality_complete=_history_quality_complete(previous)
    previous_best=_history_best_tier(existing_playable)
    native_refresh=_history_event_needs_native_refresh(HISTORY_REPOSITORY.get_league(date,league),row)
    if promoted and previous_best in ('gold','green'):
        quality_complete=previous_best==HISTORY_QUALITY_TARGET_TIER
        retry=0 if quality_complete else now+_history_upgrade_retry_seconds(date,previous_best)
        details=dict(previous_details); details.update({'discoveryVersion':HISTORY_DISCOVERY_VERSION,'candidatePromotionAttempted':True,'candidatePromotedItems':len(promoted),'bestTier':previous_best,'qualityComplete':quality_complete,'upgradeEligible':not quality_complete,'coverageComplete':True,'lastSearchAt':now})
        state='VERIFIED' if quality_complete else 'VERIFIED_UPGRADE_PENDING'
        HISTORY_REPOSITORY.set_event_discovery(date,league,event_id,state,details,retry_at=retry,success=True)
        HISTORY_REPOSITORY.record_discovery_attempt(league,event_id,source='candidate-promotion',discovery_version=HISTORY_DISCOVERY_VERSION,query_type='KNOWN_CANDIDATE_VALIDATION',
            result_count=len(existing_candidates),accepted_count=len(promoted),best_before=best_before_candidate_promotion,best_after=previous_best,quota_cost=0,details={'candidateFirst':True})
        return {'eventId':event_id,'state':state,'media':existing,'playable':existing_playable,'errors':[],'cached':False,'candidatePromoted':True,'candidatePromotedItems':len(promoted),'bestTier':previous_best,'qualityComplete':quality_complete,'coverageComplete':True,'upgradeEligible':not quality_complete,'nextRetryAt':retry}

    # Gold + exhausted source lanes is genuinely complete. Anything below Gold is
    # playable but deliberately remains eligible for a future quality-upgrade pass.
    if not force and previous_version_ok and previous_catalog_complete and previous_quality_complete and existing_playable and not native_refresh:
        return {'eventId':event_id,'state':'VERIFIED','media':existing,'playable':existing_playable,'errors':[],'cached':True,
                'catalogComplete':True,'qualityComplete':True,'bestTier':previous_best,'upgradeEligible':False}

    retry_at=float(previous.get('nextRetryAt') or 0) if previous else 0
    previous_state=str(previous.get('discoveryState') or '') if previous else ''
    # A discovery-version bump is an automatic soft reset: old retry timestamps
    # cannot prevent v8 from reconsidering existing historical records. For a current
    # record we honor its retry window, except when a foreground visit still has an
    # untried shared search-rescue lane available.
    foreground_rescue_due=bool(previous_version_ok and allow_search_rescue and not previous_details.get('searchRescueAttempted'))
    if not force and previous_version_ok and retry_at>now and not native_refresh and not foreground_rescue_due:
        return {'eventId':event_id,'state':previous_state or ('VERIFIED_UPGRADE_PENDING' if existing_playable else 'UNKNOWN'),
                'media':existing,'playable':existing_playable,'errors':[],'cached':True,
                'catalogComplete':bool(previous_catalog_complete),'qualityComplete':bool(previous_quality_complete),
                'bestTier':previous_best,'upgradeEligible':bool(existing_playable and not previous_quality_complete),'nextRetryAt':retry_at}

    found=[]; errors=[]; lanes={}
    search_budget_bucket=_history_search_budget_bucket(date,previous_best)
    def lane(name,fn):
        before=len(found)
        try:
            rows=fn() or []
            if isinstance(rows,list): found.extend(x for x in rows if isinstance(x,dict))
            lanes[name]={'ok':True,'items':max(0,len(found)-before)}
            return rows
        except YouTubeRateLimited as exc:
            lanes[name]={'ok':False,'degraded':True,'error':str(exc),'operation':getattr(exc,'operation','')}
            errors.append(f'{name}: {exc}')
            return []
        except Exception as exc:
            lanes[name]={'ok':False,'degraded':True,'error':f'{type(exc).__name__}: {exc}'}
            errors.append(f'{name}: {type(exc).__name__}: {exc}')
            return []

    # Every lane gets a chance on an actual pass. Never stop merely because a Blue,
    # Purple or Green item was found first; later lanes may contain the preferred
    # Gold package and every verified alternative belongs in the persistent catalog.
    lane('official-native',lambda:_history_event_media_no_quota(league,date,row))
    if league=='MLB':
        def mlb_official():
            all_rows=[]
            all_rows.extend(normalized_stats_highlights(date,force_refresh=force) or [])
            all_rows.extend(normalized_rapid_highlights(date,force_refresh=force,force_clips=True) or [])
            return [x for x in all_rows if _history_media_matches_row(x,row)]
        lane('mlb-official',mlb_official)
        # MLB's official YouTube channel is extremely deep and publishes both
        # individual moments and real game recap/condensed packages. Index its
        # uploads/activity lanes just like NBA/NFL/NHL so Blue-only MLB games can
        # upgrade without immediately spending search.list quota.
        lane('youtube-official-uploads',lambda:_official_youtube_history_upload_results(league,date,away,home,max_items=32,force=force))
        lane('youtube-official-activity',lambda:_official_youtube_history_activity_results(league,date,away,home,max_items=28,force=force))
        # MLB is the largest Green gap in the live catalog. Official game-content
        # remains first, but stubborn Blue-only games can use the same globally
        # throttled search/public rescue lanes as every other league.
        if allow_search_rescue:
            lane('youtube-official-day-search',lambda:_official_youtube_history_day_search_results(league,date,away,home,max_items=30,force=force,budget_bucket=search_budget_bucket))
        lane('youtube-public-page',lambda:_historical_youtube_web_results(league,date,away,home,max_items=18))
        lane('youtube-public-index',lambda:_historical_search_engine_youtube_results(league,date,away,home,max_items=18))
    else:
        lane('youtube-official-uploads',lambda:_official_youtube_history_upload_results(league,date,away,home,max_items=28,force=force))
        lane('youtube-official-activity',lambda:_official_youtube_history_activity_results(league,date,away,home,max_items=24,force=force))
        if allow_search_rescue:
            # One shared search.list catalog per league/day; the provider function
            # owns caching/budget so every event consumes the same day result.
            lane('youtube-official-day-search',lambda:_official_youtube_history_day_search_results(league,date,away,home,max_items=24,force=force,budget_bucket=search_budget_bucket))
        lane('youtube-public-page',lambda:_historical_youtube_web_results(league,date,away,home,max_items=16))
        lane('youtube-public-index',lambda:_historical_search_engine_youtube_results(league,date,away,home,max_items=16))
        if league=='NFL':
            lane('nfl-feed',lambda:_official_nfl_feed_videos(date,away,home))

    decorated=_history_decorate_event_media(league,date,row,found)
    if decorated:
        HISTORY_REPOSITORY.put_media(date,league,decorated,merge=True)
        HISTORY_REPOSITORY.put_event_media(date,league,event_id,decorated)
    record,media,playable,candidates=_history_event_catalog_state(date,league,row)
    playable=[annotate_media_tier(x) for x in playable]
    tiers=_history_playable_tiers(playable); best_tier=tiers[0] if tiers else ''
    tier_counts={tier:sum(1 for x in playable if str(x.get('recapTier') or 'blue')==tier) for tier in HISTORY_TIER_ORDER}
    free_lane_names=['official-native','mlb-official'] if league=='MLB' else ['official-native','youtube-official-uploads','youtube-official-activity','youtube-public-page','youtube-public-index']+(['nfl-feed'] if league=='NFL' else [])
    free_lane_complete=all(name in lanes and lanes[name].get('ok') for name in free_lane_names)
    search_attempted='youtube-official-day-search' in lanes
    search_complete=bool(lanes.get('youtube-official-day-search',{}).get('ok')) if league!='MLB' else True
    catalog_complete=bool(free_lane_complete and (league=='MLB' or (search_attempted and search_complete)))
    quality_complete=bool(best_tier==HISTORY_QUALITY_TARGET_TIER)
    upgrade_eligible=bool(playable and not quality_complete)
    missing_better_tiers=_history_quality_missing_tiers(best_tier) if upgrade_eligible else []

    if playable:
        if quality_complete:
            state='VERIFIED'; retry_at=0
        elif catalog_complete:
            state='VERIFIED_UPGRADE_PENDING'; retry_at=now+_history_upgrade_retry_seconds(date,best_tier)
        else:
            state='VERIFIED_PARTIAL'; retry_at=now+(20*60 if errors else 6*60*60)
        success=True
    elif candidates:
        state='CANDIDATE_ONLY'; retry_at=now+(20*60 if errors else 60*60); success=False
    elif errors:
        state='DEGRADED_PROVIDER'; retry_at=now+10*60; success=False
    else:
        state='SEARCHED_EMPTY'; retry_at=now+(12*60*60 if catalog_complete else 6*60*60); success=False
    attempt_count=int(previous_details.get('attemptCount') or 0)+1
    no_improvement=int(previous_details.get('noImprovementCount') or 0)+1 if best_tier==previous_best else 0
    if no_improvement and retry_at>now:
        base=max(60,retry_at-now); retry_at=now+min(7*24*60*60,base*(2**min(3,no_improvement)))
    details={
        'discoveryVersion':HISTORY_DISCOVERY_VERSION,'lanes':lanes,'mediaItems':len(media),'playableItems':len(playable),
        'candidateItems':len(candidates),'away':away,'home':home,'lastSearchAt':now,
        'tiersFound':tiers,'tierCounts':tier_counts,'bestTier':best_tier,
        'qualityTargetTier':HISTORY_QUALITY_TARGET_TIER,'qualityComplete':bool(quality_complete),
        'upgradeEligible':bool(upgrade_eligible),'missingBetterTiers':missing_better_tiers,
        'freeLaneComplete':bool(free_lane_complete),'searchRescueAttempted':bool(search_attempted),
        'catalogComplete':bool(catalog_complete),'discoveryExhausted':bool(catalog_complete),'coverageComplete':bool(playable),
        'attemptCount':attempt_count,'noImprovementCount':no_improvement,'searchBudgetBucket':search_budget_bucket,
        'candidatePromotionAttempted':bool(existing_candidates),'candidatePromotedItems':len(promoted),
        'nextQualityRetryAt':float(retry_at if upgrade_eligible else 0),
    }
    HISTORY_REPOSITORY.set_event_discovery(date,league,event_id,state,details,error=' | '.join(errors[-6:]),retry_at=retry_at,success=success)
    for lane_name,lane_info in lanes.items():
        HISTORY_REPOSITORY.record_discovery_attempt(league,event_id,source=lane_name,discovery_version=HISTORY_DISCOVERY_VERSION,query_type='PROVIDER_LANE',
            result_count=int((lane_info or {}).get('items') or 0),accepted_count=0,best_before=previous_best,best_after=best_tier,quota_cost=(1 if lane_name=='youtube-official-day-search' and (lane_info or {}).get('ok') else 0),
            failure_reason=str((lane_info or {}).get('error') or ''),details={'budgetBucket':search_budget_bucket,'degraded':bool((lane_info or {}).get('degraded'))})
    HISTORY_REPOSITORY.record_discovery_attempt(league,event_id,source='event-discovery',discovery_version=HISTORY_DISCOVERY_VERSION,query_type='EVENT_PASS',
        result_count=len(found),accepted_count=len(decorated),best_before=previous_best,best_after=best_tier,quota_cost=0,failure_reason=' | '.join(errors[-6:]),
        details={'catalogComplete':catalog_complete,'qualityComplete':quality_complete,'searchBudgetBucket':search_budget_bucket})
    # Legacy league-day progress remains for older diagnostics. Deep means the free
    # background lanes were exhausted; qualityComplete separately records whether
    # every final in the league has reached Gold.
    progress={'lastSearchAt':now,'discoveryVersion':HISTORY_DISCOVERY_VERSION}
    if lanes.get('official-native',{}).get('ok'): progress['noQuotaSearchedEventIds']=[event_id]
    if free_lane_complete: progress['deepSearchedEventIds']=[event_id]
    HISTORY_REPOSITORY.put_discovery(date,league,progress,merge=True)
    return {'eventId':event_id,'state':state,'media':media,'playable':playable,'errors':errors,'lanes':lanes,'cached':False,
            'catalogComplete':catalog_complete,'qualityComplete':quality_complete,'upgradeEligible':upgrade_eligible,
            'bestTier':best_tier,'tiersFound':tiers,'nextRetryAt':retry_at}

def _history_discover_day(date,deep=True,only_one_game=False,force=False):
    """Build one historical day by invoking the canonical per-event catalog service."""
    start=time.time(); score_rows,score_errors=_history_ensure_scores(date); errors=list(score_errors)
    tasks=[]
    for league in HISTORY_LEAGUES:
        for row in score_rows.get(league) or []:
            if _history_gap_event_ready(date,row): tasks.append((league,row))
    # Missing/degraded/partial events are upgraded before already complete events.
    def task_priority(pair):
        league,row=pair; event_id=_history_row_event_id(row); record=HISTORY_REPOSITORY.get_event(date,league,event_id) if event_id else None
        state=str((record or {}).get('discoveryState') or 'UNKNOWN')
        if state=='VERIFIED_UPGRADE_PENDING':
            best=str(_history_discovery_details(record).get('bestTier') or 'blue')
            # Blue-only games are the most urgent playable upgrade target; once a
            # real Green/Purple package exists, retries can yield to weaker rows.
            return {'blue':5,'extended':6,'green':7,'gold':9}.get(best,5)
        return {'UNKNOWN':0,'DEGRADED_PROVIDER':1,'CANDIDATE_ONLY':2,'SEARCHED_EMPTY':3,'VERIFIED_PARTIAL':4,'VERIFIED':9}.get(state,8)
    tasks.sort(key=task_priority)
    _history_set_discovery_state(date,status='SEARCHING',running=True,totalGames=len(tasks),searchedGames=0,currentLeague='',currentGame='',lastError='',startedAt=start,finishedAt=0)
    searched=0; attempts=0; now=time.time()
    for league,row in tasks:
        event_id=_history_row_event_id(row); away=_history_team_name(row,'away'); home=_history_team_name(row,'home')
        record=HISTORY_REPOSITORY.get_event(date,league,event_id) if event_id else None
        if only_one_game and record:
            retry_at=float(record.get('nextRetryAt') or 0)
            free_done=_history_free_lanes_complete(record)
            if free_done and retry_at>now and not _history_event_needs_native_refresh(HISTORY_REPOSITORY.get_league(date,league),row):
                continue
        _history_set_discovery_state(date,searchedGames=searched,currentLeague=league,currentGame=f'{away} @ {home}'.strip())
        result=_history_discover_event(date,league,row,force=force,allow_search_rescue=bool(deep and not only_one_game))
        if not result.get('cached'):
            attempts+=1
        searched+=1
        errors.extend(result.get('errors') or [])
        _history_set_discovery_state(date,searchedGames=searched,currentLeague=league,currentGame=f'{away} @ {home}'.strip())
        if only_one_game and attempts>=1: break

    inv=_history_inventory(date)
    for league in HISTORY_LEAGUES:
        info=(inv.get('leagues') or {}).get(league) or {}
        HISTORY_REPOSITORY.put_discovery(date,league,{
            'discoveryVersion':HISTORY_DISCOVERY_VERSION,'deepComplete':bool(info.get('deepComplete')),
            'catalogComplete':bool(info.get('catalogComplete')),'qualityComplete':bool(info.get('qualityComplete')),'qualityCompleteGames':int(info.get('qualityCompleteGames') or 0),'upgradeEligibleGames':int(info.get('upgradeEligibleGames') or 0),'knownFinalEvents':int(info.get('completed') or 0),'lastDiscoveryAt':time.time(),
        },merge=True)
    final_status='READY' if inv.get('playableGames')>=inv.get('completedGames') and not inv.get('needsRefresh') else ('DEGRADED' if errors or inv.get('candidateMedia') else 'READY')
    _history_set_discovery_state(date,status=final_status,running=False,searchedGames=searched,currentLeague='',currentGame='',lastError=' | '.join(errors[-8:])[:900],finishedAt=time.time())
    return _history_discovery_state(date)

def _history_discovery_worker(date,deep=True,force=False):
    try: _history_discover_day(date,deep=deep,only_one_game=False,force=force)
    except Exception as exc:
        _history_set_discovery_state(date,status='ERROR',running=False,lastError=f'{type(exc).__name__}: {exc}',finishedAt=time.time())


def trigger_history_discovery(date,deep=True,force=False):
    date=str(date or '')[:10]
    if not re.match(r'^\d{4}-\d{2}-\d{2}$',date): raise ValueError('DATE_REQUIRED')
    with HISTORY_DISCOVERY_LOCK:
        current=HISTORY_DISCOVERY_STATE.get(date) or {}
        if current.get('running'): return False
    inv=_history_inventory(date)
    # Source-complete dates can still have quality upgrades pending. Only start a
    # new pass when an upgrade/retry is actually due; otherwise serve the persistent
    # playable catalog immediately and let the scheduled retry window stand.
    if not force and inv.get('completedGames') and not inv.get('needsRefresh') and not inv.get('upgradeDue') and bool(inv.get('catalogComplete')):
        _history_set_discovery_state(date,status='READY',running=False,totalGames=inv.get('completedGames') or 0,searchedGames=inv.get('completedGames') or 0,finishedAt=time.time())
        return False
    t=threading.Thread(target=_history_discovery_worker,args=(date,deep,force),daemon=True,name=f'sbb-history-{date}')
    _history_set_discovery_state(date,status='QUEUED',running=True,totalGames=inv.get('completedGames') or 0,searchedGames=0,startedAt=time.time(),lastError='')
    t.start(); return True


def _history_deep_backfill_one_game(date):
    """Advance at most one historical final through the canonical event catalog.

    Idle backfill never consumes search.list. It uses official/native providers,
    official-channel activities.list + videos.list validation, and candidate-only
    public metadata lanes. Interactive date browsing may use the shared one-search-
    per-league/day rescue when the primary official channel index is incomplete.
    """
    before=_history_inventory(date); before_media=int(before.get('mediaItems') or 0)
    result=_history_discover_day(date,deep=True,only_one_game=True)
    after=result.get('inventory') or _history_inventory(date)
    # Count an idle deep step only when durable deep-search progress increased.
    before_n=sum(int((x or {}).get('backgroundCompleteGames') or 0) for x in (before.get('leagues') or {}).values())
    after_n=sum(int((x or {}).get('backgroundCompleteGames') or 0) for x in (after.get('leagues') or {}).values())
    before_quality=int(before.get('qualityCompleteGames') or 0); after_quality=int(after.get('qualityCompleteGames') or 0)
    before_due=int(before.get('upgradeDueGames') or 0); after_due=int(after.get('upgradeDueGames') or 0)
    progressed=max(0,after_n-before_n,after_quality-before_quality,before_due-after_due)
    return {'searched':progressed,'media':max(0,int(after.get('mediaItems') or 0)-before_media),'state':result}


def _history_backfill_day(date):
    tz_value=MEDIA_PREWARM_STATE.get('timezone') or ''
    utc_offset=MEDIA_PREWARM_STATE.get('utcOffsetMinutes')
    score_rows={}; errors=[]
    def load_league(league):
        if HISTORY_REPOSITORY.has_scores(date,league):
            return league,HISTORY_REPOSITORY.get_league(date,league).get('scores') or [],None
        try:
            rows=_espn_scoreboard(league,date,tz_value,utc_offset)
            HISTORY_REPOSITORY.put_scores(date,league,rows)
            return league,rows,None
        except Exception as exc:
            return league,[],f'{type(exc).__name__}: {exc}'
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs=[ex.submit(load_league,lg) for lg in HISTORY_LEAGUES]
        for fut in as_completed(futs):
            lg,rows,err=fut.result(); score_rows[lg]=rows
            if err: errors.append(f'{lg}: {err}')
    media_count=0
    if HISTORY_BACKFILL_MEDIA:
        # MLB has a highly efficient official day endpoint, so index it as one batch.
        mlb_state=HISTORY_REPOSITORY.get_league(date,'MLB')
        if not mlb_state.get('mediaSavedAt'):
            try:
                mlb_media=[annotate_media_tier(x) for x in (normalized_stats_highlights(date) or []) if isinstance(x,dict)]
                HISTORY_REPOSITORY.put_media(date,'MLB',mlb_media,merge=True); media_count+=len(mlb_media)
            except Exception as exc: errors.append(f'MLB media: {type(exc).__name__}: {exc}')
        # v4.0.2 background history uses official/native sources plus the official
        # channel activities catalog. It can therefore build real NBA/NFL/NHL/MLS/EPL
        # playable manifests while idle without spending a single search.list call.
        for lg in ('NFL','NBA','NHL','EPL','MLS'):
            state=HISTORY_REPOSITORY.get_league(date,lg)
            if state.get('mediaSavedAt'): continue
            discovered=[]; searched_ids=[]
            for row in (score_rows.get(lg) or []):
                if not _history_row_completed(row): continue
                event_id=_history_row_event_id(row); pieces=[]
                try: pieces.extend(_history_event_media_no_quota(lg,date,row))
                except Exception as exc: errors.append(f'{lg} native {event_id}: {type(exc).__name__}: {exc}')
                try: pieces.extend(_official_youtube_history_upload_results(lg,date,_history_team_name(row,'away'),_history_team_name(row,'home'),max_items=28))
                except Exception as exc: errors.append(f'{lg} uploads {event_id}: {type(exc).__name__}: {exc}')
                try: pieces.extend(_official_youtube_history_activity_results(lg,date,_history_team_name(row,'away'),_history_team_name(row,'home'),max_items=24))
                except Exception as exc: errors.append(f'{lg} activities {event_id}: {type(exc).__name__}: {exc}')
                decorated=_history_decorate_event_media(lg,date,row,pieces); discovered.extend(decorated)
                if decorated: HISTORY_REPOSITORY.put_event_media(date,lg,event_id,decorated)
                if event_id:
                    searched_ids.append(event_id)
                    HISTORY_REPOSITORY.upsert_event(date,lg,event_id,row)
                # Do not mark an event discovered here. This is only the cheap initial
                # bootstrap. The canonical per-event pipeline below owns lane-complete
                # and quality-complete state so a Blue result cannot accidentally close
                # the event before Gold/Green/Purple upgrade lanes are assessed.
            HISTORY_REPOSITORY.put_media(date,lg,discovered,merge=True); media_count+=len(discovered)
            HISTORY_REPOSITORY.put_discovery(date,lg,{'discoveryVersion':HISTORY_DISCOVERY_VERSION,'noQuotaSearchedEventIds':searched_ids,'noQuotaComplete':True,'lastDiscoveryAt':time.time()},merge=True)
    return {'date':date,'scores':sum(len(v) for v in score_rows.values()),'media':media_count,'errors':errors}


def _history_background_status():
    """Return whether low-priority catalog work may run right now.

    v4.0.2 adds an explicit operator mode:
      SEARCH   -> discovery owns bandwidth; playback is suspended and never pauses search.
      BALANCED -> current behavior; discovery yields briefly to playback/foreground work.
      PLAYBACK -> all historical discovery workers remain paused until mode changes.
    """
    now=time.time()
    mode=_history_work_mode()
    media_age=now-float(CLIENT_ACTIVITY_STATE.get('lastMedia') or 0)
    interactive_age=now-float(CLIENT_ACTIVITY_STATE.get('lastInteractive') or 0)
    with HISTORY_DISCOVERY_LOCK:
        discovery_running=any(bool((st or {}).get('running')) for st in HISTORY_DISCOVERY_STATE.values())
    reason=''
    if mode=='playback':
        reason='playback-priority'
    elif mode=='search':
        reason=''
    else:
        if media_age < HISTORY_BACKGROUND_MEDIA_PAUSE_SECONDS: reason='media-playback'
        elif discovery_running: reason='foreground-history-discovery'
        elif interactive_age < HISTORY_BACKGROUND_INTERACTIVE_PAUSE_SECONDS: reason='foreground-request'
    return {
        'canWork':not bool(reason),'pauseReason':reason,'siteOpenDoesNotPause':True,'workMode':mode,
        'playbackSuspended':mode=='search','searchSuspended':mode=='playback',
        'mediaAgeSeconds':max(0,int(media_age)),'interactiveAgeSeconds':max(0,int(interactive_age)),
        'foregroundDiscoveryRunning':bool(discovery_running),
    }


def _history_server_idle():
    # Legacy name retained for diagnostics/tests. It now means "background work is
    # safe", not "no browser has made an API request for 15 seconds".
    return bool(_history_background_status().get('canWork'))


def _history_green_search_rescue_due():
    now=time.time()
    return bool(now-float(HISTORY_GREEN_SEARCH_RESCUE_STATE.get('lastAt') or 0)>=HISTORY_GREEN_SEARCH_RESCUE_INTERVAL)


def _history_recent_cutoff():
    try: return _client_date_iso(-2,MEDIA_PREWARM_STATE.get('timezone') or '',MEDIA_PREWARM_STATE.get('utcOffsetMinutes'))
    except Exception: return (datetime.now(timezone.utc)-timedelta(days=2)).date().isoformat()

def history_green_gap_worker():
    """Continuously attack games that still lack a real Green recap.

    v4.0.2 makes the worker observable and removes a legacy completion gate that
    could silently skip historical event rows whose normalized JSON omitted the
    provider's final-state fields. The worker records heartbeat, queue depth,
    current event, per-lane outcomes, provider errors, and actual progress in the
    Search Console.
    """
    time.sleep(18)
    HISTORY_GREEN_GAP_STATE['running']=True
    HISTORY_GREEN_GAP_STATE['startedAt']=time.time()
    _history_worker_beat('green-gap','idle',progress=True)
    _history_console_log('green-gap','INFO',f'worker started • discovery v{HISTORY_DISCOVERY_VERSION}')
    last_pause=''
    last_empty_log=0.0
    while True:
        try:
            _history_worker_beat('green-gap','checking')
            bg=_history_background_status()
            if not bg.get('canWork'):
                reason=str(bg.get('pauseReason') or 'foreground-work')
                HISTORY_GREEN_GAP_STATE['pauseReason']=reason
                _history_worker_beat('green-gap',f'paused:{reason}',blocked=True)
                if reason!=last_pause:
                    _history_console_log('green-gap','INFO',f'paused • {reason}')
                    last_pause=reason
                time.sleep(5)
                continue
            if last_pause:
                _history_console_log('green-gap','INFO','resumed')
                last_pause=''
            HISTORY_GREEN_GAP_STATE['pauseReason']=''

            qsum=HISTORY_REPOSITORY.green_gap_summary(current_discovery_version=HISTORY_DISCOVERY_VERSION,now=time.time(),recent_cutoff=_history_recent_cutoff())
            HISTORY_GREEN_GAP_STATE['queue']=qsum
            gaps=HISTORY_REPOSITORY.green_gap_events(current_discovery_version=HISTORY_DISCOVERY_VERSION,now=time.time(),limit=96,recent_cutoff=_history_recent_cutoff())
            HISTORY_GREEN_GAP_STATE['candidateBatch']=len(gaps)
            target=None; skipped=0
            for gap in gaps:
                if _history_gap_event_ready(gap.get('date') or '',gap.get('event') or {}):
                    target=gap; break
                skipped+=1
            HISTORY_GREEN_GAP_STATE['skippedNotReady']=skipped
            if not target:
                _history_worker_beat('green-gap','waiting:no-due-ready-event',blocked=bool(gaps))
                if gaps and time.time()-last_empty_log>60:
                    _history_console_log('green-gap','WARN',f'{len(gaps)} due gap rows but none looked completed/ready • skipped={skipped}',queue=qsum)
                    last_empty_log=time.time()
                elif not gaps and time.time()-last_empty_log>180:
                    _history_console_log('green-gap','INFO','no due Green-gap event right now',queue=qsum)
                    last_empty_log=time.time()
                time.sleep(45 if gaps else 120)
                continue

            date=str(target.get('date') or '')[:10]
            league=str(target.get('league') or '').upper()
            event_id=str(target.get('eventId') or '')
            row=dict(target.get('event') or {})
            before=str(target.get('bestTier') or 'none')
            current=f'{date} {league} {event_id} {_history_team_name(row,"away")} @ {_history_team_name(row,"home")}'.strip()
            allow_rescue=bool(before in ('blue','none','extended') and _history_green_search_rescue_due() and _youtube_search_available())
            HISTORY_GREEN_GAP_STATE.update({'current':current,'currentStartedAt':time.time(),'searchRescueAllowed':allow_rescue})
            _history_worker_beat('green-gap','discovering',current=current)
            _history_console_log('green-gap','INFO',f'searching {current} • best={before.upper()} • search-rescue={"YES" if allow_rescue else "NO"}')

            result=_history_discover_event(date,league,row,force=False,allow_search_rescue=allow_rescue)
            if allow_rescue:
                HISTORY_GREEN_SEARCH_RESCUE_STATE['lastAt']=time.time()
            after=str(result.get('bestTier') or _history_best_tier(result.get('playable') or []) or 'none')
            upgraded=bool(after in ('green','gold') and before not in ('green','gold'))
            lane_parts=[]
            if result.get('candidatePromoted'):
                lane_parts.append(f'existing-candidate=VERIFIED(+{int(result.get("candidatePromotedItems") or 1)})')
            for name,info in (result.get('lanes') or {}).items():
                info=info or {}
                if info.get('ok'):
                    lane_parts.append(f'{name}=OK(+{int(info.get("items") or 0)})')
                else:
                    err=str(info.get('error') or 'failed')[:120]
                    lane_parts.append(f'{name}=ERR({err})')
            err_text=' | '.join(result.get('errors') or [])[:700]
            HISTORY_GREEN_GAP_STATE.update({
                'lastRun':time.time(),'lastDate':date,'lastLeague':league,'lastEventId':event_id,
                'lastBestTier':before,'lastResultTier':after,'lastError':err_text,
                'lastLanes':result.get('lanes') or {},'current':'','currentStartedAt':0.0,
                'attempts':int(HISTORY_GREEN_GAP_STATE.get('attempts') or 0)+1,
                'upgradedToGreen':int(HISTORY_GREEN_GAP_STATE.get('upgradedToGreen') or 0)+(1 if upgraded else 0),
            })
            _history_worker_beat('green-gap','sleeping',current='',progress=True)
            level='INFO' if not err_text else 'WARN'
            _history_console_log('green-gap',level,f'{current} • {before.upper()}→{after.upper()}'+(' • GREEN+' if upgraded else '')+' • '+' • '.join(lane_parts),errors=err_text)
            time.sleep(HISTORY_GREEN_GAP_INTERVAL)
        except Exception as exc:
            msg=f'{type(exc).__name__}: {exc}'
            HISTORY_GREEN_GAP_STATE['lastError']=msg
            HISTORY_GREEN_GAP_STATE['lastExceptionAt']=time.time()
            _history_worker_beat('green-gap','error',blocked=True)
            _history_console_log('green-gap','ERROR',msg)
            time.sleep(30)


def history_backfill_worker():
    """Continuously walk backward and build a persistent date catalog at low priority."""
    time.sleep(12)
    HISTORY_BACKFILL_STATE['running']=True
    HISTORY_BACKFILL_STATE['startedAt']=time.time()
    _history_worker_beat('date-backfill','scanning',progress=True)
    _history_console_log('date-backfill','INFO',f'worker started • {HISTORY_BACKFILL_DAYS} day target • discovery v{HISTORY_DISCOVERY_VERSION}')
    while True:
        try:
            _history_worker_beat('date-backfill','scanning')
            today=_client_date_iso(0,MEDIA_PREWARM_STATE.get('timezone') or '',MEDIA_PREWARM_STATE.get('utcOffsetMinutes'))
            base=datetime.strptime(today,'%Y-%m-%d').date()
            for offset in range(1,HISTORY_BACKFILL_DAYS+1):
                date=(base-timedelta(days=offset)).isoformat()
                day=HISTORY_REPOSITORY.get_day(date)
                complete_scores=all((day.get('leagues') or {}).get(lg,{}).get('scoresSavedAt') for lg in HISTORY_LEAGUES)
                complete_media=(not HISTORY_BACKFILL_MEDIA) or all((day.get('leagues') or {}).get(lg,{}).get('mediaSavedAt') for lg in HISTORY_LEAGUES)
                deep_required=bool(HISTORY_BACKFILL_MEDIA)
                inv=_history_inventory(date)
                source_deep_complete=all(
                    bool(((day.get('leagues') or {}).get(lg,{}).get('discovery') or {}).get('deepComplete')) and
                    int(((day.get('leagues') or {}).get(lg,{}).get('discovery') or {}).get('discoveryVersion') or 0)>=HISTORY_DISCOVERY_VERSION
                    for lg in HISTORY_LEAGUES
                )
                # A source-complete date is temporarily idle while its quality retry
                # window is in the future. Once a Blue/Purple/Green upgrade becomes
                # due, the same date re-enters the low-priority backfill queue.
                complete_deep=(not deep_required) or bool(source_deep_complete and not inv.get('upgradeDue'))
                if complete_scores and complete_media and complete_deep: continue
                _history_worker_beat('date-backfill','waiting-for-background-slot',current=date)
                while not _history_server_idle():
                    _history_worker_beat('date-backfill','paused:'+str(_history_background_status().get('pauseReason') or 'foreground'),current=date,blocked=True)
                    time.sleep(5)
                _history_worker_beat('date-backfill','backfilling',current=date)
                result={'date':date,'scores':0,'media':0,'errors':[]}
                if not (complete_scores and complete_media):
                    result=_history_backfill_day(date)
                deep_result={'searched':0,'media':0}
                if deep_required and not complete_deep and _history_server_idle():
                    try: deep_result=_history_deep_backfill_one_game(date)
                    except Exception as exc: result.setdefault('errors',[]).append(f'deep media: {type(exc).__name__}: {exc}')
                HISTORY_BACKFILL_STATE.update({'lastDate':date,'lastRun':time.time(),'lastError':' | '.join(result.get('errors') or [])[:500],
                                               'daysCompleted':int(HISTORY_BACKFILL_STATE.get('daysCompleted') or 0)+1,
                                               'mediaItems':int(HISTORY_BACKFILL_STATE.get('mediaItems') or 0)+int(result.get('media') or 0)+int(deep_result.get('media') or 0),
                                               'deepGames':int(HISTORY_BACKFILL_STATE.get('deepGames') or 0)+int(deep_result.get('searched') or 0)})
                msg=f"backfilled {date}: {result.get('scores',0)} games / +{int(result.get('media') or 0)+int(deep_result.get('media') or 0)} media / deep {deep_result.get('searched',0)}"
                _history_worker_beat('date-backfill','sleeping',current='',progress=True)
                _history_console_log('date-backfill','WARN' if result.get('errors') else 'INFO',msg,errors=' | '.join(result.get('errors') or [])[:500])
                print(f"[SBB history] {msg}",flush=True)
                time.sleep(75 if deep_result.get('searched') else 20)
            time.sleep(10*60)
        except Exception as exc:
            HISTORY_BACKFILL_STATE['lastError']=f'{type(exc).__name__}: {exc}'
            _history_worker_beat('date-backfill','error',blocked=True)
            _history_console_log('date-backfill','ERROR',HISTORY_BACKFILL_STATE['lastError'])
            time.sleep(60)


def game_center_refresh_worker():
    """Refresh due scheduled/live snapshots centrally; UI polling reads localhost."""
    time.sleep(3)
    while True:
        try:
            for row in GAME_CENTER_REPOSITORY.due(limit=24):
                comp=str(row.get("competition") or ""); event=str(row.get("event_id") or "")
                priority=MEDIA_PRIORITY["VISIBLE_SCORE"] if row.get("live") else MEDIA_PRIORITY["BACKGROUND_DISCOVERY"]
                schedule_game_center_prepare(comp,event,priority)
        except Exception as exc:
            print(f"[SBB game-center] refresh worker warning: {type(exc).__name__}: {exc}",flush=True)
        time.sleep(15)

class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        origin=_cors_allowed_origin(self.headers.get("Origin"))
        if origin:
            self.send_header("Access-Control-Allow-Origin",origin)
            self.send_header("Vary","Origin")
            self.send_header("Access-Control-Expose-Headers","X-SBB-RateLimit-Remaining, X-SBB-RateLimit-Limit, X-SBB-Cache, X-SBB-GameCenter-Cache, Retry-After")
        return super().end_headers()

    def do_OPTIONS(self):
        parsed=urlparse(self.path)
        if not parsed.path.startswith('/api/'):
            self.send_response(404); self.end_headers(); return
        origin=_cors_allowed_origin(self.headers.get("Origin"))
        if self.headers.get("Origin") and not origin:
            self.send_response(403); self.end_headers(); return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods","GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type, Range, X-SBB-Prime")
        self.send_header("Access-Control-Max-Age","7200")
        self.send_header("Content-Length","0")
        self.end_headers()

    def translate_path(self, path):
        # Keep static file serving rooted at the repository directory.
        old = os.getcwd()
        try:
            os.chdir(ROOT)
            return super().translate_path(path)
        finally:
            os.chdir(old)

    def do_POST(self):
        parsed=urlparse(self.path)
        if parsed.path.startswith('/api/'):
            CLIENT_ACTIVITY_STATE['lastInteractive']=time.time()
        if parsed.path == '/api/settings/secrets':
            if CLOUD_MODE:
                return send_json(self,{'ok':False,'error':'CLOUD_SECRETS_SERVER_MANAGED','message':'API credentials are managed on the cloud server and cannot be changed from the public web UI.'},403)
            try:
                length=min(64000,int(self.headers.get('Content-Length') or 0))
                body=json.loads(self.rfile.read(length).decode('utf-8') or '{}')
                return send_json(self,_update_settings_secrets(body),200)
            except ValueError as exc:
                return send_json(self,{'ok':False,'error':'BAD_SETTINGS','message':str(exc)},400)
            except Exception as exc:
                return send_json(self,{'ok':False,'error':'SETTINGS_SAVE_ERROR','message':f'{type(exc).__name__}: {exc}'},500)
        if parsed.path == '/api/history/work-mode':
            try:
                length=min(8000,int(self.headers.get('Content-Length') or 0))
                body=json.loads(self.rfile.read(length).decode('utf-8') or '{}')
                state=_set_history_work_mode(body.get('mode'),updated_by='search-console')
                return send_json(self,{'ok':True,'workMode':state,'background':_history_background_status()},200)
            except ValueError as exc:
                return send_json(self,{'ok':False,'error':'BAD_HISTORY_WORK_MODE','message':str(exc)},400)
            except Exception as exc:
                return send_json(self,{'ok':False,'error':'HISTORY_WORK_MODE_ERROR','message':f'{type(exc).__name__}: {exc}'},500)
        if parsed.path == '/api/history/event/discover':
            if _history_search_suspended():
                return send_json(self,{'ok':False,'error':'SEARCH_PAUSED_BY_PRIORITY','message':'Historical discovery is paused while Playback Priority is selected.','workMode':_history_work_mode()},423)
            try:
                length=min(32000,int(self.headers.get('Content-Length') or 0))
                body=json.loads(self.rfile.read(length).decode('utf-8') or '{}')
                date=str(body.get('date') or '')[:10]; league=str(body.get('league') or '').upper(); event_id=str(body.get('eventId') or '')
                if not re.match(r'^\d{4}-\d{2}-\d{2}$',date) or league not in HISTORY_LEAGUES or not event_id:
                    return send_json(self,{'ok':False,'error':'BAD_HISTORY_EVENT'},400)
                _touch_history_focus(date,seconds=180)
                row=_history_find_score_row(date,league,event_id)
                if row is None:
                    _history_ensure_scores(date); row=_history_find_score_row(date,league,event_id)
                if row is None: return send_json(self,{'ok':False,'error':'HISTORY_EVENT_NOT_FOUND'},404)
                result=_history_discover_event(date,league,row,force=bool(body.get('force',False)),allow_search_rescue=True)
                plan=_history_playback_plan(date,league,event_id)
                return send_json(self,{'ok':True,'result':result,'plan':plan,'repository':HISTORY_REPOSITORY.summary()},200)
            except Exception as exc:
                return send_json(self,{'ok':False,'error':'HISTORY_EVENT_DISCOVERY_ERROR','message':f'{type(exc).__name__}: {exc}'},500)
        if parsed.path == '/api/history/media/runtime':
            try:
                length=min(16000,int(self.headers.get('Content-Length') or 0))
                body=json.loads(self.rfile.read(length).decode('utf-8') or '{}')
                date=str(body.get('date') or '')[:10]; league=str(body.get('league') or '').upper(); event_id=str(body.get('eventId') or ''); asset_key=str(body.get('assetKey') or '')
                state=str(body.get('state') or '').upper(); reason=str(body.get('reason') or '')
                if not re.match(r'^\d{4}-\d{2}-\d{2}$',date) or league not in HISTORY_LEAGUES or not event_id or not asset_key or state not in ('PLAYED','FAILED'):
                    return send_json(self,{'ok':False,'error':'BAD_HISTORY_RUNTIME'},400)
                saved=HISTORY_REPOSITORY.record_runtime(date,league,event_id,asset_key,success=(state=='PLAYED'),reason=reason)
                return send_json(self,{'ok':True,'saved':saved,'plan':_history_playback_plan(date,league,event_id)},200)
            except Exception as exc:
                return send_json(self,{'ok':False,'error':'HISTORY_RUNTIME_SAVE_ERROR','message':f'{type(exc).__name__}: {exc}'},500)
        if parsed.path == '/api/history/media':
            try:
                length=min(512000,int(self.headers.get('Content-Length') or 0))
                body=json.loads(self.rfile.read(length).decode('utf-8') or '{}')
                date=str(body.get('date') or '')[:10]; league=str(body.get('league') or '').upper(); items=body.get('items') or []
                if not re.match(r'^\d{4}-\d{2}-\d{2}$',date) or league not in HISTORY_LEAGUES or not isinstance(items,list):
                    return send_json(self,{'ok':False,'error':'BAD_HISTORY_MEDIA'},400)
                HISTORY_REPOSITORY.put_media(date,league,items[:500],merge=True)
                return send_json(self,{'ok':True,'date':date,'league':league,'items':len(items),'repository':HISTORY_REPOSITORY.summary()},200)
            except Exception as exc:
                return send_json(self,{'ok':False,'error':'HISTORY_MEDIA_SAVE_ERROR','message':f'{type(exc).__name__}: {exc}'},500)
        if parsed.path == '/api/history/discover':
            if _history_search_suspended():
                return send_json(self,{'ok':False,'error':'SEARCH_PAUSED_BY_PRIORITY','message':'Historical discovery is paused while Playback Priority is selected.','workMode':_history_work_mode()},423)
            try:
                length=min(16000,int(self.headers.get('Content-Length') or 0))
                body=json.loads(self.rfile.read(length).decode('utf-8') or '{}')
                date=str(body.get('date') or '')[:10]
                if not re.match(r'^\d{4}-\d{2}-\d{2}$',date): return send_json(self,{'ok':False,'error':'DATE_REQUIRED'},400)
                deep=bool(body.get('deep',True)); force=bool(body.get('force',False))
                _touch_history_focus(date,seconds=150)
                started=trigger_history_discovery(date,deep=deep,force=force)
                return send_json(self,{'ok':True,'started':started,'state':_history_discovery_state(date),'repository':HISTORY_REPOSITORY.summary()},202 if started else 200)
            except ValueError as exc:
                return send_json(self,{'ok':False,'error':'BAD_HISTORY_DISCOVERY','message':str(exc)},400)
            except Exception as exc:
                return send_json(self,{'ok':False,'error':'HISTORY_DISCOVERY_ERROR','message':f'{type(exc).__name__}: {exc}'},500)
        if parsed.path == '/api/media/prepare':
            if _history_playback_suspended():
                return send_json(self,{'ok':False,'error':'PLAYBACK_SUSPENDED_BY_SEARCH_PRIORITY','message':'Media staging is suspended while Search Priority is selected.','workMode':_history_work_mode()},423)
            try:
                length=min(128000,int(self.headers.get('Content-Length') or 0))
                body=json.loads(self.rfile.read(length).decode('utf-8') or '{}')
                items=body.get('items') or []
                if not isinstance(items,list): return send_json(self,{'ok':False,'error':'BAD_MEDIA_ITEMS'},400)
                accepted=0
                for row in items[:24]:
                    if not isinstance(row,dict): continue
                    url=str(row.get('url') or '')
                    if schedule_media_cache_prepare(url,row.get('eventId') or row.get('gamePk') or '',row.get('date') or '',int(row.get('priority') or 0),row.get('priorityClass') or ''):
                        accepted+=1
                return send_json(self,{'ok':True,'accepted':accepted,'cache':_media_cache_summary()},200)
            except Exception as exc:
                return send_json(self,{'ok':False,'error':'MEDIA_PREPARE_ERROR','message':f'{type(exc).__name__}: {exc}'},500)
        if parsed.path == '/api/editorial/program-rank':
            try:
                length=min(256000,int(self.headers.get('Content-Length') or 0))
                body=json.loads(self.rfile.read(length).decode('utf-8') or '{}')
                mode=str(body.get('mode') or 'queue')
                if mode not in ('queue','top-plays','score-ribbon'): return send_json(self,{'ok':False,'error':'BAD_RANK_MODE'},400)
                candidates=body.get('candidates') or []
                if not isinstance(candidates,list): return send_json(self,{'ok':False,'error':'BAD_CANDIDATES'},400)
                rows=_openai_program_rank(mode,candidates,body.get('favoriteTeams') or [],str(body.get('localDate') or ''))
                return send_json(self,{'ok':True,'data':rows,'mode':mode,'model':OPENAI_MODEL if read_openai_key() else None})
            except Exception as exc:
                print(f"[SBB program-rank] soft fallback {mode if 'mode' in locals() else 'unknown'}: {type(exc).__name__}: {exc}",flush=True)
                return send_json(self,{
                    'ok':True,
                    'data':[],
                    'fallback':'deterministic',
                    'error':'PROGRAM_RANK_UNAVAILABLE',
                    'message':f'{type(exc).__name__}: {exc}'
                },200)
        return send_json(self,{'ok':False,'error':'NOT_FOUND'},404)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/media':
            CLIENT_ACTIVITY_STATE['lastMedia']=time.time()
        elif parsed.path.startswith('/api/'):
            # Polling/status/audit reads are passive and must never keep the 24/7
            # history workers asleep simply because a browser tab is open.
            CLIENT_ACTIVITY_STATE['lastPassive']=time.time()
            if parsed.path.startswith('/api/history/scores') or parsed.path.startswith('/api/events/'):
                CLIENT_ACTIVITY_STATE['lastInteractive']=time.time()

        if parsed.path == '/api/media':
            try:
                media_qs=parse_qs(parsed.query); media_date=str((media_qs.get('date') or [''])[-1])[:10]
                _touch_history_focus(media_date,seconds=120)
            except Exception: pass

        if parsed.path == "/api/history/scores":
            qs=parse_qs(parsed.query); date=str((qs.get('date') or [''])[-1])[:10]; league=str((qs.get('league') or [''])[-1]).upper()
            if not re.match(r'^\d{4}-\d{2}-\d{2}$',date) or league not in HISTORY_LEAGUES:
                return send_json(self,{'ok':False,'error':'BAD_HISTORY_SCORE_REQUEST'},400)
            _touch_history_focus(date,seconds=120)
            tz_value=str((qs.get('timezone') or [''])[-1]); raw_offset=(qs.get('utcOffsetMinutes') or [''])[-1]
            try: utc_offset=int(raw_offset) if str(raw_offset).strip() else None
            except Exception: utc_offset=None
            force=str((qs.get('refresh') or ['0'])[-1]).lower() in ('1','true','yes')
            rows,source,cached,error=_history_get_league_scores(date,league,tz_value,utc_offset,force=force)
            status=200 if source!='UNAVAILABLE' or cached else 502
            return send_json(self,{'ok':status==200,'date':date,'league':league,'data':rows,'source':source,'cached':cached,'error':error},status)

        if parsed.path == "/api/history/event/media":
            qs=parse_qs(parsed.query); date=str((qs.get('date') or [''])[-1])[:10]; league=str((qs.get('league') or [''])[-1]).upper(); event_id=str((qs.get('eventId') or [''])[-1])
            if not re.match(r'^\d{4}-\d{2}-\d{2}$',date) or league not in HISTORY_LEAGUES or not event_id:
                return send_json(self,{'ok':False,'error':'BAD_HISTORY_EVENT'},400)
            _touch_history_focus(date,seconds=120)
            return send_json(self,{'ok':True,'plan':_history_playback_plan(date,league,event_id)},200)

        if parsed.path == "/api/history/day":
            qs=parse_qs(parsed.query); date=str((qs.get('date') or [''])[-1])[:10]
            if not re.match(r'^\d{4}-\d{2}-\d{2}$',date): return send_json(self,{'ok':False,'error':'DATE_REQUIRED'},400)
            _touch_history_focus(date,seconds=120)
            day=HISTORY_REPOSITORY.get_day(date)
            return send_json(self,{'ok':True,**day,'discoveryState':_history_discovery_state(date),'repository':HISTORY_REPOSITORY.summary()},200)

        if parsed.path == "/api/history/roundups":
            qs=parse_qs(parsed.query); date=str((qs.get('date') or [''])[-1])[:10]; league=str((qs.get('league') or ['ALL'])[-1]).upper()
            if not re.match(r'^\d{4}-\d{2}-\d{2}$',date): return send_json(self,{'ok':False,'error':'DATE_REQUIRED'},400)
            if league!='ALL' and league not in HISTORY_LEAGUES: return send_json(self,{'ok':False,'error':'BAD_LEAGUE'},400)
            rows=HISTORY_REPOSITORY.roundup_media(date,league)
            playable=[x for x in rows if x.get('verifiedPlayable') and (x.get('youtubeId') or x.get('mediaUrl'))]
            return send_json(self,{'ok':True,'date':date,'league':league,'tier':'silver','media':rows,'playable':playable,'primary':playable[0] if playable else None},200)

        if parsed.path == "/api/history/discovery":
            qs=parse_qs(parsed.query); date=str((qs.get('date') or [''])[-1])[:10]
            if not re.match(r'^\d{4}-\d{2}-\d{2}$',date): return send_json(self,{'ok':False,'error':'DATE_REQUIRED'},400)
            _touch_history_focus(date,seconds=120)
            return send_json(self,{'ok':True,'state':_history_discovery_state(date),'repository':HISTORY_REPOSITORY.summary()},200)

        if parsed.path == "/api/history/audit":
            try:
                qs=parse_qs(parsed.query); filters=_history_audit_filters(qs)
                data=HISTORY_REPOSITORY.audit_catalog(**filters,current_discovery_version=HISTORY_DISCOVERY_VERSION,quality_target=HISTORY_QUALITY_TARGET_TIER)
                return send_json(self,{'ok':True,**data,'repository':HISTORY_REPOSITORY.summary(),'background':_history_background_status(),'greenGap':dict(HISTORY_GREEN_GAP_STATE)},200)
            except Exception as exc:
                return send_json(self,{'ok':False,'error':'HISTORY_AUDIT_ERROR','message':f'{type(exc).__name__}: {exc}'},500)

        if parsed.path in ("/api/history/audit.csv","/api/history/audit.xlsx"):
            try:
                qs=parse_qs(parsed.query); filters=_history_audit_export_filters(qs)
                rows=HISTORY_REPOSITORY.audit_export_rows(**filters,current_discovery_version=HISTORY_DISCOVERY_VERSION,quality_target=HISTORY_QUALITY_TARGET_TIER)
                stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
                if parsed.path.endswith('.csv'):
                    body=_history_audit_csv_bytes(rows); ctype='text/csv; charset=utf-8'; name=f'sports-big-board-history-audit-{stamp}.csv'
                else:
                    body=_history_audit_xlsx_bytes(rows); ctype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'; name=f'sports-big-board-history-audit-{stamp}.xlsx'
                return send_bytes(self,body,ctype,200,{'Content-Disposition':f'attachment; filename="{name}"'})
            except Exception as exc:
                return send_json(self,{'ok':False,'error':'HISTORY_AUDIT_EXPORT_ERROR','message':f'{type(exc).__name__}: {exc}'},500)

        if parsed.path == "/api/history/catalog/integrity":
            return send_json(self,{"ok":True,"version":APP_VERSION,"catalogSchemaVersion":CATALOG_SCHEMA_VERSION,"summary":HISTORY_REPOSITORY.summary(),"integrity":HISTORY_REPOSITORY.catalog_integrity()},200)

        if parsed.path == "/api/history/catalog/review":
            try:
                qs=parse_qs(parsed.query)
                result=HISTORY_REPOSITORY.assignment_reviews(state=str((qs.get('state') or [''])[-1]),reason=str((qs.get('reason') or [''])[-1]),league=str((qs.get('league') or [''])[-1]),limit=int((qs.get('limit') or ['200'])[-1]),offset=int((qs.get('offset') or ['0'])[-1]))
                return send_json(self,{"ok":True,**result},200)
            except Exception as exc:
                return send_json(self,{"ok":False,"error":"HISTORY_REVIEW_ERROR","message":f"{type(exc).__name__}: {exc}"},500)

        if parsed.path == "/api/history/catalog/attempts":
            try:
                qs=parse_qs(parsed.query)
                result=HISTORY_REPOSITORY.discovery_attempts(league=str((qs.get('league') or [''])[-1]),event_id=str((qs.get('eventId') or [''])[-1]),source=str((qs.get('source') or [''])[-1]),limit=int((qs.get('limit') or ['200'])[-1]),offset=int((qs.get('offset') or ['0'])[-1]))
                return send_json(self,{"ok":True,**result},200)
            except Exception as exc:
                return send_json(self,{"ok":False,"error":"HISTORY_ATTEMPTS_ERROR","message":f"{type(exc).__name__}: {exc}"},500)

        if parsed.path == "/api/history/catalog/collections":
            try:
                qs=parse_qs(parsed.query)
                result=HISTORY_REPOSITORY.collection_audit(scope=str((qs.get('scope') or [''])[-1]),league=str((qs.get('league') or [''])[-1]),period_key=str((qs.get('period') or [''])[-1]),limit=int((qs.get('limit') or ['200'])[-1]),offset=int((qs.get('offset') or ['0'])[-1]))
                return send_json(self,{"ok":True,**result},200)
            except Exception as exc:
                return send_json(self,{"ok":False,"error":"HISTORY_COLLECTION_AUDIT_ERROR","message":f"{type(exc).__name__}: {exc}"},500)

        if parsed.path == "/api/history/worker-console":
            try:
                qs=parse_qs(parsed.query)
                limit=max(20,min(320,int((qs.get('limit') or ['160'])[-1] or 160)))
                now=time.time()
                with HISTORY_DISCOVERY_LOCK:
                    active={d:copy.deepcopy(st) for d,st in HISTORY_DISCOVERY_STATE.items() if st.get('running')}
                with HISTORY_CONSOLE_LOCK:
                    lines=list(HISTORY_CONSOLE_LINES)[-limit:]
                workers=copy.deepcopy(HISTORY_WORKER_HEALTH)
                for name,st in workers.items():
                    hb=float(st.get('heartbeat') or 0); lp=float(st.get('lastProgress') or 0)
                    st['heartbeatAgeSeconds']=int(max(0,now-hb)) if hb else None
                    st['progressAgeSeconds']=int(max(0,now-lp)) if lp else None
                    st['healthy']=bool(hb and now-hb<240)
                with HISTORY_FOCUS_LOCK: focus=dict(HISTORY_FOCUS_STATE)
                gateway=YOUTUBE_GATEWAY.status()
                qsum=HISTORY_REPOSITORY.green_gap_summary(current_discovery_version=HISTORY_DISCOVERY_VERSION,now=now,recent_cutoff=_history_recent_cutoff())
                associations=HISTORY_REPOSITORY.association_integrity_summary()
                problems=[]
                threads=_history_threads_status()
                for row in threads:
                    if not row.get('alive'): problems.append(f"thread {row.get('name')} is not alive")
                for name,st in workers.items():
                    if not st.get('healthy'): problems.append(f"{name} heartbeat stale or missing")
                bg=_history_background_status()
                # Normal scheduler yielding (media playback / foreground discovery / brief user action)
                # is visible in diagnostics but is not itself an error. The old console labeled every
                # short yield as a problem, which made a healthy worker look hung while video played.
                if not bg.get('canWork') and str(bg.get('pauseReason') or '') not in ('media-playback','foreground-history-discovery','foreground-request','playback-priority'):
                    problems.append(f"background blocked: {bg.get('pauseReason') or 'unknown'}")
                for op,st in gateway.items():
                    if st.get('cooldownSeconds',0) or st.get('quotaExhausted'):
                        label='quota exhausted' if st.get('quotaExhausted') else f"cooldown {int(st.get('cooldownSeconds') or 0)}s"
                        problems.append(f"YouTube {op} {label}: {st.get('lastError') or ''}")
                budget_state=_history_youtube_budget_status()
                if int(budget_state.get('limit') or budget_state.get('budget') or 0)>0 and int(budget_state.get('used') or 0)>=int(budget_state.get('limit') or budget_state.get('budget') or 0):
                    problems.append(f"Historical YouTube search budget exhausted ({budget_state.get('used')}/{budget_state.get('limit') or budget_state.get('budget')})")
                if RATE_LIMIT_STATE.get('limited'): problems.append('Highlightly rate limited')
                return send_json(self,{
                    'ok':True,'version':APP_VERSION,'historyDiscoveryVersion':HISTORY_DISCOVERY_VERSION,
                    'serverStartedAt':SERVER_STARTED_AT,'uptimeSeconds':int(max(0,now-SERVER_STARTED_AT)),
                    'deploymentMode':DEPLOYMENT_MODE,'workMode':dict(HISTORY_WORK_MODE_STATE),
                    'playbackSuspended':_history_playback_suspended(),'searchSuspended':_history_search_suspended(),
                    'threads':threads,'workers':workers,'background':bg,
                    'greenGap':copy.deepcopy(HISTORY_GREEN_GAP_STATE),'greenGapQueue':qsum,'associations':associations,
                    'backfill':copy.deepcopy(HISTORY_BACKFILL_STATE),'activeDiscoveries':active,'focus':focus,
                    'youtubeGateway':gateway,'youtubeSearchBudget':budget_state,
                    'highlightly':{'limited':bool(RATE_LIMIT_STATE.get('limited')),'remaining':RATE_LIMIT_STATE.get('remaining'),'limit':RATE_LIMIT_STATE.get('limit')},
                    'problems':problems,'recent':lines,
                },200)
            except Exception as exc:
                return send_json(self,{'ok':False,'error':'HISTORY_WORKER_CONSOLE_ERROR','message':f'{type(exc).__name__}: {exc}'},500)

        if parsed.path == "/api/history/status":
            with HISTORY_DISCOVERY_LOCK:
                active={d:copy.deepcopy(st) for d,st in HISTORY_DISCOVERY_STATE.items() if st.get('running')}
            return send_json(self,{'ok':True,'version':APP_VERSION,'historyDiscoveryVersion':HISTORY_DISCOVERY_VERSION,'workMode':dict(HISTORY_WORK_MODE_STATE),'repository':HISTORY_REPOSITORY.summary(),'backfill':dict(HISTORY_BACKFILL_STATE),'greenGap':dict(HISTORY_GREEN_GAP_STATE),'background':_history_background_status(),'activeDiscoveries':active,'daysTarget':HISTORY_BACKFILL_DAYS,'mediaBackfill':HISTORY_BACKFILL_MEDIA,'idleSeconds':HISTORY_IDLE_SECONDS,'idle':_history_server_idle()},200)

        if parsed.path == "/api/settings":
            return send_json(self,_settings_payload(),200)

        if parsed.path == "/api/game-center/repository":
            with GAME_CENTER_COVERAGE_LOCK: coverage=dict(GAME_CENTER_COVERAGE_STATE)
            return send_json(self,{"ok":True,"repository":GAME_CENTER_REPOSITORY.summary(),"coverage":coverage},200)

        if parsed.path == "/api/game-center/prewarm":
            qs=parse_qs(parsed.query)
            tz_value=str((qs.get("timezone") or [""])[-1]); utc_offset=(qs.get("utcOffsetMinutes") or [None])[-1]
            client_date=str((qs.get("clientDate") or [""])[-1]); _remember_client_clock(tz_value,utc_offset,client_date)
            today=str((qs.get("today") or [_client_date_iso(0,tz_value,utc_offset)])[-1])[:10]
            yesterday=str((qs.get("yesterday") or [_client_date_iso(-1,tz_value,utc_offset)])[-1])[:10]
            queued=_request_game_center_coverage(today,yesterday,force=False)
            with GAME_CENTER_COVERAGE_LOCK: coverage=dict(GAME_CENTER_COVERAGE_STATE)
            return send_json(self,{"ok":True,"queued":bool(queued),"today":today,"yesterday":yesterday,"repository":GAME_CENTER_REPOSITORY.summary(),"coverage":coverage},200)

        if parsed.path == "/api/soccer/schedule":
            qs=parse_qs(parsed.query)
            league=str((qs.get("league") or ["EPL"])[-1]).upper()
            tz_value=str((qs.get("timezone") or [""])[-1])
            utc_offset=(qs.get("utcOffsetMinutes") or [None])[-1]
            client_date=str((qs.get("clientDate") or [""])[-1])
            _remember_client_clock(tz_value,utc_offset,client_date)
            today=str((qs.get("today") or [_client_date_iso(0,tz_value,utc_offset)])[-1])
            yesterday=str((qs.get("yesterday") or [_client_date_iso(-1,tz_value,utc_offset)])[-1])
            if league not in ("EPL","MLS"):
                return send_json(self,{"ok":False,"error":"league must be EPL or MLS"},400)
            return send_json(self,_soccer_schedule_bundle(league,today,yesterday,tz_value,utc_offset),200)

        if parsed.path == "/api/soccer/diagnostics":
            qs=parse_qs(parsed.query)
            league=str((qs.get("league") or ["EPL"])[-1]).upper()
            date=str((qs.get("date") or [datetime.now().astimezone().date().isoformat()])[-1])
            force=str((qs.get("force") or ["0"])[-1]).lower() in ("1","true","yes")
            if league not in ("EPL","MLS"):
                return send_json(self,{"ok":False,"error":"league must be EPL or MLS"},400)

            cached,cached_age,cached_source=_read_soccer_schedule_cache(league,date,None)
            if cached is not None and not force:
                return send_json(self,{
                    "ok":True,"league":league,"date":date,
                    "rawCount":len(cached),"filteredCount":len(cached),"normalizedCount":len(cached),
                    "sample":_soccer_sample(cached[0]) if cached else None,
                    "source":cached_source,"cache":"diagnostic-cache",
                    "cacheAgeSeconds":int(cached_age or 0),"providerRequestMade":False,
                    "cooldownSeconds":max(0,int(float(SOCCER_PROVIDER_COOLDOWN.get("until") or 0)-time.time()))
                },200)

            result=_soccer_schedule_day(league,date,force=force)
            rows=result.get("data") or []
            return send_json(self,{
                "ok":True,"league":league,"date":date,
                "rawCount":len(rows),"filteredCount":len(rows),"normalizedCount":len(rows),
                "sample":_soccer_sample(rows[0]) if rows else None,
                "source":result.get("source"),"cache":result.get("cache"),
                "cacheAgeSeconds":result.get("ageSeconds"),
                "providerRequestMade":bool(force),
                "cooldownSeconds":result.get("cooldownSeconds",max(0,int(float(SOCCER_PROVIDER_COOLDOWN.get("until") or 0)-time.time())))
            },200)

        if parsed.path == "/api/client-log":
            qs=parse_qs(parsed.query)
            event=(qs.get("event") or [""])[-1]
            detail=(qs.get("detail") or [""])[-1]
            version=(qs.get("v") or [""])[-1]
            print(f"[SBB client] {event} v={version} {detail}".rstrip(), flush=True)
            return send_json(self,{"ok":True},200)

        game_center_match=re.fullmatch(r"/api/events/([A-Za-z0-9_.:-]+)/([A-Za-z0-9_.:-]+)/game-center",parsed.path)
        if game_center_match:
            competition,event_id=game_center_match.groups()
            qs=parse_qs(parsed.query); force=(qs.get("refresh") or ["0"])[-1].lower() in ("1","true","yes")
            async_mode=(qs.get("async") or ["0"])[-1].lower() in ("1","true","yes")
            hints={"date":str((qs.get("date") or [""])[-1])[:10],"away":str((qs.get("away") or [""])[-1]),"home":str((qs.get("home") or [""])[-1]),"start":str((qs.get("start") or [""])[-1]),"gameNumber":str((qs.get("gameNumber") or [""])[-1]),"provider":str((qs.get("provider") or [""])[-1])}
            try:
                if async_mode:
                    data,cache_state,pending,resolved_event_id=_game_center_open(competition,event_id,force=force,hints=hints)
                    if pending:
                        return send_json(self,{"ok":True,"pending":True,"cache":"PENDING","competition":str(competition).upper(),"eventId":str(event_id),"resolvedEventId":str(resolved_event_id or ''),"retryAfterMs":500,"contract":"1.0"},202,{"X-SBB-GameCenter-Cache":"PENDING","Retry-After":"1"})
                else:
                    resolved_event_id=_resolve_game_center_event_id(competition,event_id,hints,allow_fetch=True)
                    if not resolved_event_id: raise ValueError(f"Unable to resolve {str(competition).upper()} Game Center event")
                    data,cache_state=_game_center_get(competition,resolved_event_id,force=force); pending=False
                return send_json(self,{"ok":True,"data":data,"cache":cache_state,"pending":False,"resolvedEventId":str(resolved_event_id),"contract":"1.0"},200,{"X-SBB-GameCenter-Cache":cache_state})
            except NotImplementedError as exc:
                return send_json(self,{"ok":False,"error":"GAME_CENTER_PROVIDER_NOT_IMPLEMENTED","message":str(exc),"competition":competition},501)
            except ValueError as exc:
                return send_json(self,{"ok":False,"error":"BAD_GAME_CENTER_EVENT","message":str(exc)},400)
            except Exception as exc:
                return send_json(self,{"ok":False,"error":"GAME_CENTER_ERROR","message":f"{type(exc).__name__}: {exc}"},502)

        # Every release is served from the same localhost origin. Chrome on Android
        # otherwise reuses app.js/styles.css across extracted version folders via
        # conditional 304 responses. Serve release assets explicitly no-store so a
        # newly-started Termux build always executes the files from that build.
        if parsed.path in ("/", "/index.html") or parsed.path.endswith(".js") or parsed.path.endswith(".css"):
            rel="index.html" if parsed.path in ("/", "/index.html") else parsed.path.lstrip("/")
            target=os.path.join(ROOT,rel)
            try:
                with open(target,"rb") as fh: body=fh.read()
                ctype="text/html; charset=utf-8" if rel.endswith(".html") else ("application/javascript; charset=utf-8" if rel.endswith(".js") else "text/css; charset=utf-8")
                self.send_response(200)
                self.send_header("Content-Type",ctype)
                self.send_header("Cache-Control","no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Referrer-Policy","strict-origin-when-cross-origin")
                self.send_header("Pragma","no-cache")
                self.send_header("Expires","0")
                self.send_header("Content-Length",str(len(body)))
                self.end_headers(); self.wfile.write(body); return
            except FileNotFoundError:
                self.send_error(404); return
        if parsed.path == "/api/architecture":
            return send_json(self,{"ok":True,"version":APP_VERSION,"domainModel":"SPORT>COMPETITION>EVENT>MEDIA_MANIFEST>MEDIA_PACKAGE>MEDIA_ASSET>TRANSPORT","enabledCompetitions":enabled_competition_ids(),"competitions":competition_catalog(),"mediaAdapters":MEDIA_ADAPTERS,"mediaRequests":list(MEDIA_REQUESTS),"sportMediaPolicies":SPORT_MEDIA_POLICIES,"services":{"eventIdentity":"browser-canonical","mediaManifest":"browser persistent event manifest","mediaResolver":"provider-independent package resolver","playbackTransports":["DIRECT_VIDEO","YOUTUBE_EMBED","EXTERNAL","CONTEXT"],"providerHealth":"browser adaptive source health","mediaClassifier":"browser+server canonical","selectedEvent":"browser store v1","gameCenter":"contract 1.0 / sport-policy normalization / provider-isolated indexes / SQLite repository / bounded sticky workspace","mediaWorkScheduler":MEDIA_WORK_SCHEDULER.snapshot(),"gameCenterWorkScheduler":GAME_CENTER_WORK_SCHEDULER.snapshot(),"leagueEditorial":"registry 1.0","historyCatalog":"SQLite date/league hydration + canonical historical event/asset catalog + runtime playback truth"},"invariants":["PlaybackController sole media activation authority","media existence is independent from provider health and runtime playability","score rails derive availability from the event media manifest","prewarm cannot select media","exact media-key + epoch required for prepared-player adoption","Game Center consumes selected event and cannot mutate playback","league editorial packages never mutate SelectedEvent","historical provider discovery is server-owned and runtime failures persist per asset"]})

        if parsed.path == "/api/editorial/series":
            return send_json(self,{"ok":True,"version":"1.0","data":editorial_series_catalog()})

        if parsed.path == "/api/status":
            key = read_key()
            return send_json(self, {
                "ok": True,
                "version": APP_VERSION,
                "historyDiscoveryVersion": HISTORY_DISCOVERY_VERSION,
                "serverStartedAt": SERVER_STARTED_AT,
                "historyWorkerThreads": _history_threads_status(),
                "deploymentMode": DEPLOYMENT_MODE,
                "cloudMode": CLOUD_MODE,
                "persistentState": bool(STATE_DIR),
                "rateLimit": {"remaining": RATE_LIMIT_STATE.get("remaining", ""), "limit": RATE_LIMIT_STATE.get("limit", ""), "limited": RATE_LIMIT_STATE.get("limited", False)},
                "highlightlyRateLimited": RATE_LIMIT_STATE["limited"],
                "phase": "V4.0.2 NORMALIZED CATALOG + SEARCH CONSOLE",
                "workMode":dict(HISTORY_WORK_MODE_STATE),
                "highlightlyConfigured": bool(key),
                "youtubeCooldownSeconds":max((row.get("cooldownSeconds",0) for row in YOUTUBE_GATEWAY.status().values()), default=0),
                "youtubeGateway":YOUTUBE_GATEWAY.status(),
                "youtubeConfigured": bool(read_youtube_key()),
                "openaiConfigured": bool(read_openai_key()),
                "domainModel": "SPORT>COMPETITION>EVENT>MEDIA_PACKAGE>MEDIA_ASSET>MOMENT",
                "architecture": {"selectedEvent":True,"mediaManifest":True,"mediaResolver":True,"playbackTransports":True,"providerHealth":True,"gameCenterContract":"1.0","gameCenterBelowVideo":True,"gameCenterRepository":"sqlite","gameCenterServerPrewarm":True,"gameCenterAdapters":["MLB","NFL","NBA","NHL","MLS","EPL"],"stickyVideoPreference":True,"machineSecrets":True,"mediaWorkScheduler":True,"leagueEditorial":True,"historyCatalog":True,"historyBackfill":True},
                "provider": "Competition registry + ESPN/official-league/club/Highlightly/YouTube media adapters + OpenAI Editorial",
                "sport": "MULTI"
            })

        if parsed.path == "/api/mlb/coverage-status":
            qs=parse_qs(parsed.query)
            date=(qs.get("date") or [_client_date_iso()])[-1]
            st=dict(coverage_state(date))
            with DISCOVERY_LOCK:
                job=DISCOVERY_JOBS.get(date)
                st["jobRunning"]=bool(job and job.is_alive())
            return send_json(self,{"ok":True,"data":st})

        if parsed.path == "/api/media":
            if _history_playback_suspended():
                return send_json(self,{'ok':False,'error':'PLAYBACK_SUSPENDED_BY_SEARCH_PRIORITY','message':'Playback is suspended while Search Priority is selected.','workMode':_history_work_mode()},423)
            qs=parse_qs(parsed.query)
            media_url=(qs.get("url") or [""])[-1]
            event_id=(qs.get("eventId") or qs.get("gamePk") or [""])[-1]
            gamepk=event_id
            media_date=(qs.get("date") or [""])[-1]
            try:
                upstream=urlparse(media_url)
                host=(upstream.hostname or "").lower()
                if not _media_host_allowed(media_url):
                    return send_json(self, {"ok":False,"error":"MEDIA_HOST_NOT_ALLOWED"}, 400)
                range_header=self.headers.get("Range")
                # Local disk is always checked before opening an upstream media connection.
                if _media_cache_serve(self,media_url,range_header): return
                # If a WARM cache has only the startup range, stream those local
                # bytes immediately and splice the remainder from the selected upstream source behind them.
                if _media_cache_serve_hybrid_head(self,media_url,range_header,event_id,media_date): return
                cache_key=_media_cache_key(media_url)
                # If a WARM server-stage job is just finishing, give it a very short
                # chance to publish the local range before opening a duplicate upstream
                # connection. Never wait long enough to make an actual user click feel blocked.
                with MEDIA_FILE_CACHE_LOCK:
                    stage_inflight=cache_key in MEDIA_FILE_CACHE_JOBS
                if stage_inflight:
                    for _ in range(3):
                        time.sleep(0.08)
                        if _media_cache_serve(self,media_url,range_header): return
                        with MEDIA_FILE_CACHE_LOCK:
                            if cache_key not in MEDIA_FILE_CACHE_JOBS: break
                with MEDIA_FILE_CACHE_LOCK:
                    MEDIA_FILE_CACHE_STATS["requests"]+=1; MEDIA_FILE_CACHE_STATS["misses"]+=1
                    MEDIA_FILE_CACHE_ACTIVE_STREAMS.add(cache_key)
                headers=_media_request_headers(range_header,media_url)
                media_tag="media-prime" if self.headers.get("X-SBB-Prime")=="1" else "media"
                print(f"[SBB {media_tag}] request host={host} range={range_header or '-'} url={media_url[:180]}", flush=True)
                req=Request(media_url, headers=headers)
                try:
                    with urlopen(req, timeout=20) as resp:
                        print(f"[SBB {media_tag}] upstream status={getattr(resp, 'status', 200)} type={resp.headers.get('Content-Type','')} length={resp.headers.get('Content-Length','')} range={resp.headers.get('Content-Range','')}", flush=True)
                        status=getattr(resp, "status", 200)
                        content_length=int(resp.headers.get("Content-Length") or 0)
                        cr=_parse_content_range(resp.headers.get("Content-Range"))
                        start=cr[0] if cr else 0; end=cr[1] if cr else max(-1,content_length-1); total=cr[2] if cr else (content_length if status==200 and content_length else None)
                        paths=_media_cache_paths(media_url); meta=_media_cache_meta(media_url)
                        capture_mode=None; capture_path=None; capture_tmp=None
                        complete_resource=bool(total and start==0 and end==total-1)
                        if complete_resource and total<=MEDIA_FILE_CACHE_FULL_MAX_BYTES:
                            capture_mode='full'; capture_path=paths['full']; capture_tmp=paths['full'].with_suffix('.mp4.streamtmp')
                        elif start==0:
                            capture_mode='head'; capture_path=paths['head']; capture_tmp=paths['head'].with_suffix('.head.streamtmp')
                        elif total and start>=max(0,total-MEDIA_FILE_CACHE_TAIL_BYTES*2):
                            capture_mode='tail'; capture_path=paths['tail']; capture_tmp=paths['tail'].with_suffix('.tail.streamtmp')
                        capture_file=None; captured=0
                        try:
                            if capture_tmp:
                                try: capture_file=capture_tmp.open('wb')
                                except Exception: capture_file=None
                            self.send_response(status)
                            for name in ("Content-Type","Content-Length","Content-Range","Accept-Ranges","Last-Modified","ETag"):
                                value=resp.headers.get(name)
                                if value: self.send_header(name,value)
                            self.send_header("Cache-Control","private, max-age=3600")
                            self.send_header("X-SBB-Media-Cache","MISS-UPSTREAM")
                            self.end_headers()
                            client_connected=True
                            while True:
                                chunk=resp.read(256*1024)
                                if not chunk: break
                                if capture_file:
                                    if capture_mode=='head':
                                        remaining=max(0,MEDIA_FILE_CACHE_HEAD_BYTES-captured)
                                        if remaining: capture_file.write(chunk[:remaining]); captured+=min(len(chunk),remaining)
                                    elif capture_mode=='tail':
                                        capture_file.write(chunk); captured+=len(chunk)
                                    else:
                                        capture_file.write(chunk); captured+=len(chunk)
                                if client_connected:
                                    try: self.wfile.write(chunk)
                                    except (BrokenPipeError, ConnectionResetError):
                                        client_connected=False
                                        print("[SBB media] client disconnected; finishing cache capture only", flush=True)
                                        # For a large/non-full head request there is no reason
                                        # to keep consuming the entire upstream response once
                                        # the startup cache is complete.
                                        if capture_mode=='head' and captured>=MEDIA_FILE_CACHE_HEAD_BYTES: break
                                if (not client_connected) and capture_mode=='full' and captured>=MEDIA_FILE_CACHE_HEAD_BYTES:
                                    # Hand off completion to the single low-priority full-cache
                                    # worker instead of letting many hidden-player HTTP threads
                                    # finish entire recaps concurrently.
                                    break
                            if capture_file:
                                capture_file.flush(); capture_file.close(); capture_file=None
                            if capture_tmp and capture_tmp.exists() and captured>0:
                                if capture_mode=='full' and total and captured>=total:
                                    capture_tmp.replace(paths['full']); meta['fullReady']=True; meta['fullSize']=captured; meta['total']=total
                                elif capture_mode=='full':
                                    # A hidden/player request may intentionally stop once it has
                                    # enough decoded data. Preserve that partial stream as HEAD.
                                    head_bytes=min(captured,MEDIA_FILE_CACHE_HEAD_BYTES)
                                    with capture_tmp.open('rb') as src, paths['head'].with_suffix('.head.tmp').open('wb') as out:
                                        remaining=head_bytes
                                        while remaining:
                                            piece=src.read(min(256*1024,remaining))
                                            if not piece: break
                                            out.write(piece); remaining-=len(piece)
                                    paths['head'].with_suffix('.head.tmp').replace(paths['head']); meta['headStart']=0; meta['headEnd']=head_bytes-1; meta['headSize']=head_bytes
                                    try: capture_tmp.unlink()
                                    except Exception: pass
                                elif capture_mode=='head':
                                    capture_tmp.replace(paths['head']); meta['headStart']=0; meta['headEnd']=captured-1; meta['headSize']=captured
                                elif capture_mode=='tail':
                                    capture_tmp.replace(paths['tail']); meta['tailStart']=start; meta['tailEnd']=start+captured-1; meta['tailSize']=captured
                                meta.update({'url':media_url,'eventId':event_id,'gamePk':(gamepk if str(gamepk).isdigit() else meta.get('gamePk','')),'date':media_date,'total':total or meta.get('total'),'contentType':resp.headers.get('Content-Type') or meta.get('contentType') or 'video/mp4','etag':resp.headers.get('ETag') or meta.get('etag') or '','lastModified':resp.headers.get('Last-Modified') or meta.get('lastModified') or '','preparedAt':time.time(),'lastAccess':time.time()})
                                _media_cache_save(meta)
                                if meta.get('fullReady'):
                                    with MEDIA_FILE_CACHE_LOCK: MEDIA_FILE_CACHE_STATS['fullReady']+=1
                                elif total:
                                    _schedule_media_cache_full(media_url,int(total))
                            return
                        finally:
                            try:
                                if capture_file: capture_file.close()
                            except Exception: pass
                finally:
                    with MEDIA_FILE_CACHE_LOCK:
                        MEDIA_FILE_CACHE_ACTIVE_STREAMS.discard(cache_key)
            except HTTPError as e:
                print(f"[SBB media] HTTPError {e.code}: {e.reason}", flush=True)
                self.send_response(e.code)
                self.send_header("Content-Type", e.headers.get("Content-Type","text/plain"))
                if e.headers.get("Content-Range"): self.send_header("Content-Range",e.headers.get("Content-Range"))
                self.end_headers()
                try: self.wfile.write(e.read())
                except Exception: pass
                return
            except (BrokenPipeError, ConnectionResetError) as e:
                print(f"[SBB media] stream ended early: {type(e).__name__}: {e}", flush=True)
                return
            except Exception as e:
                print(f"[SBB media] proxy error: {type(e).__name__}: {e}", flush=True)
                # Media transport failures are playback diagnostics, not coverage-discovery
                # failures. Do not overwrite a healthy coverage snapshot (especially during
                # startup autoplay/prebuffer attempts). The client can recover or skip.
                try:
                    return send_json(self, {"ok":False,"error":"MEDIA_PROXY_ERROR","message":str(e)}, 502)
                except (BrokenPipeError, ConnectionResetError):
                    return

        if parsed.path == "/api/mls/official-videos":
            qs=parse_qs(parsed.query); date=(qs.get('date') or [''])[-1]
            if not re.match(r'^\d{4}-\d{2}-\d{2}$',date):
                return send_json(self,{"ok":False,"error":"DATE_REQUIRED"},400)
            force=(qs.get('refresh') or ['0'])[-1] in ('1','true','yes')
            items=official_mls_youtube_videos(date,force_refresh=force)
            return send_json(self,{"ok":True,"data":items,"source":"verified Major League Soccer YouTube channel","items":len(items)})

        if parsed.path == "/api/rapid-team-videos":
            qs=parse_qs(parsed.query)
            league=(qs.get('league') or [''])[-1].upper(); date=(qs.get('date') or [''])[-1]
            away=(qs.get('away') or [''])[-1]; home=(qs.get('home') or [''])[-1]
            event_id=(qs.get('eventId') or [''])[-1]
            if league not in {'MLB','NFL','NBA','NHL','EPL','MLS'} or not re.match(r'^\d{4}-\d{2}-\d{2}$',date) or not away or not home:
                return send_json(self,{"ok":False,"error":"BAD_RAPID_QUERY"},400)
            force=(qs.get('refresh') or ['0'])[-1] in ('1','true','yes')
            _touch_history_focus(date,seconds=150)
            items=generic_rapid_team_videos(league,date,away,home,event_id=event_id,force_refresh=force)
            return send_json(self,{"ok":True,"data":items,"source":"official team/league public video channels","items":len(items)})

        if parsed.path == "/api/editorial/status":
            return send_json(self,{"ok":True,"configured":bool(read_openai_key()),"mode":"openai" if read_openai_key() else "rules","model":OPENAI_MODEL if read_openai_key() else None})

        if parsed.path == "/api/editorial/verify":
            result=verify_openai_key()
            return send_json(self,result,200 if result.get("ok") else 502)

        if parsed.path == "/api/editorial/test":
            if not read_openai_key(): return send_json(self,{"ok":False,"error":"OPENAI_NOT_CONFIGURED"},400)
            try: return send_json(self,openai_editorial_smoke_test())
            except HTTPError as exc:
                try: detail=exc.read().decode("utf-8","ignore")[:500]
                except Exception: detail=str(exc)
                return send_json(self,{"ok":False,"error":f"OPENAI_HTTP_{exc.code}","detail":detail},502)
            except Exception as exc:
                return send_json(self,{"ok":False,"error":"OPENAI_TEST_FAILED","message":str(exc)},502)

        if parsed.path == "/api/editorial/key-info":
            # v2.2.0 is cache-first: return the last finished editorial desk
            # immediately, then refresh stale data in a background thread.
            qs=parse_qs(parsed.query)
            force=(qs.get("refresh") or ["0"])[-1] in ("1","true","yes")
            deep=(qs.get("deep") or ["0"])[-1] in ("1","true","yes")
            with EDITORIAL_SNAPSHOT_LOCK:
                snap=dict(EDITORIAL_SNAPSHOT)
            age=max(0,time.time()-float(snap.get("savedAt") or 0))
            if force or age>=300 or not snap.get("data"):
                trigger_editorial_refresh(deep=deep or not bool(snap.get("data")))
            ticker_rows=_filter_ticker_items(snap.get("data") or [])
            if not ticker_rows:
                ticker_rows=_bootstrap_key_info_from_caches()
            return send_json(self,{
                "ok":True,
                "data":ticker_rows,
                "contextPrograms":snap.get("contextPrograms") or [],
                "errors":snap.get("errors") or [],
                "editorialMode":snap.get("editorialMode") or ("openai" if read_openai_key() else "rules"),
                "editorialModel":snap.get("editorialModel") or (OPENAI_MODEL if read_openai_key() else None),
                "editorialError":snap.get("editorialError") or "",
                "cacheAgeSeconds":int(age) if snap.get("savedAt") else None,
                "refreshing":bool(EDITORIAL_REFRESH_STATE.get("refreshing")),
                "source":"warm persistent cache + 5-minute source delta + hourly OpenAI editorial desk"
            })

        if parsed.path == "/api/programming/top-plays":
            qs=parse_qs(parsed.query); date=(qs.get("date") or [""])[-1]
            if not re.match(r"^\d{4}-\d{2}-\d{2}$",date):
                return send_json(self,{"ok":False,"error":"DATE_REQUIRED"},400)
            force=(qs.get("refresh") or ["0"])[-1] in ("1","true","yes")
            try:
                data=_daily_top_plays_results(date,force_refresh=force)
                return send_json(self,{"ok":True,"data":data,"date":date,"source":"YouTube trusted daily Top Plays discovery","generatedFallback":True})
            except Exception as exc:
                return send_json(self,{"ok":False,"error":"TOP_PLAYS_ERROR","message":str(exc)},502)

        if parsed.path == "/api/media/prewarm-status":
            today=_date_iso(0); yesterday=_date_iso(-1)
            payload=dict(MEDIA_PREWARM_STATE)
            payload["today"]=today; payload["yesterday"]=yesterday
            payload["ageSeconds"]=int(max(0,time.time()-float(payload.get("lastRun") or 0))) if payload.get("lastRun") else None
            payload["transportCache"]=_media_cache_summary()
            payload["mediaWorkScheduler"]=MEDIA_WORK_SCHEDULER.snapshot()
            return send_json(self,{"ok":True,**payload})

        if parsed.path == "/api/editorial/cache-status":
            with EDITORIAL_SNAPSHOT_LOCK:
                snap=dict(EDITORIAL_SNAPSHOT)
            return send_json(self,{
                "ok":True,
                "items":len(snap.get("data") or []),
                "contextPrograms":len(snap.get("contextPrograms") or []),
                "savedAt":snap.get("savedAt"),
                "ageSeconds":int(max(0,time.time()-float(snap.get("savedAt") or 0))) if snap.get("savedAt") else None,
                "refreshing":bool(EDITORIAL_REFRESH_STATE.get("refreshing")),
                "lastQuick":EDITORIAL_REFRESH_STATE.get("lastQuick"),
                "lastDeep":EDITORIAL_REFRESH_STATE.get("lastDeep"),
                "lastError":EDITORIAL_REFRESH_STATE.get("lastError") or "",
            })

        if parsed.path == "/api/sports-events":
            qs=parse_qs(parsed.query)
            requested=(qs.get("leagues") or ["MLB,NFL,NBA,NHL,EPL,MLS"])[-1]
            leagues=[x.strip().upper() for x in requested.split(',') if x.strip().upper() in {"MLB","NFL","NBA","NHL","EPL","MLS"}]
            items=[]; errors=[]
            for league in leagues:
                try: items.extend(_merge_event_news_and_video(league))
                except Exception as e: errors.append({"league":league,"message":f"{type(e).__name__}: {e}"})
            items.sort(key=lambda x:(x.get('importance',0),x.get('publishedAt') or ''),reverse=True)
            return send_json(self,{"ok":True,"data":items[:24],"errors":errors,"source":"official league news + optional YouTube enrichment","newsCacheMinutes":15,"videoCacheHours":4,"youtubeConfigured":bool(read_youtube_key())})

        if parsed.path == "/api/espn/scoreboard":
            qs=parse_qs(parsed.query); league=(qs.get('league') or [''])[-1].upper(); date=(qs.get('date') or [''])[-1]
            tz_value=str((qs.get('timezone') or [''])[-1]); utc_offset=(qs.get('utcOffsetMinutes') or [None])[-1]
            if league not in {'MLB','NFL','NBA','NHL','EPL','MLS'} or not re.match(r'^\d{4}-\d{2}-\d{2}$',date): return send_json(self,{'ok':False,'error':'BAD_ESPN_SCOREBOARD_QUERY'},400)
            try: return send_json(self,{'ok':True,'data':_espn_scoreboard(league,date,tz_value,utc_offset),'source':'ESPN scoreboard','league':league,'date':date})
            except Exception as exc: return send_json(self,{'ok':False,'error':'ESPN_SCOREBOARD_ERROR','message':str(exc)},502)

        if parsed.path == "/api/sports/catalog":
            return send_json(self,{"ok":True,"model":"SPORT>COMPETITION>EVENT>MEDIA_PACKAGE>MEDIA_ASSET>MOMENT","data":competition_catalog(),"enabled":enabled_competition_ids()})

        sport_match=re.fullmatch(r"/api/sports/(mlb|nba|nfl|nhl|epl|mls)/(matches|highlights)", parsed.path)
        if sport_match:
            sport_key, endpoint=sport_match.groups()
            key=read_key()
            if not key:
                return send_json(self,{"ok":False,"error":"HIGHLIGHTLY_API_KEY_NOT_CONFIGURED"},503)
            cfg=SPORT_API[sport_key]
            qs=parse_qs(parsed.query)
            allowed={"date","timezone","limit","offset","league","leagueName","matchId","season","leagueType","countryCode","countryName"}
            flat={k:vals[-1] for k,vals in qs.items() if k in allowed and vals}
            client_date=str((qs.get("clientDate") or [""])[-1])
            client_utc_offset=(qs.get("utcOffsetMinutes") or [None])[-1]
            _remember_client_clock(flat.get("timezone",""),client_utc_offset,client_date)
            flat.setdefault("limit","100" if endpoint=="matches" else "40")
            if endpoint=="matches": flat.setdefault(cfg.get("matchParam","league"),cfg["league"])
            else: flat.setdefault(cfg.get("highlightParam","leagueName"),cfg["league"])
            if sport_key in ("epl","mls"):
                flat.setdefault("leagueName",cfg["league"])
                flat.setdefault("countryCode",cfg.get("countryCode",""))
            url=f'{cfg["base"]}{cfg["prefix"]}/{endpoint}?{urlencode(flat)}'
            req=Request(url,headers={"x-rapidapi-key":key,"Accept":"application/json","User-Agent":"SportsBigBoard/4.0.2"})
            cache_name=f"{sport_key}-{endpoint}-v2514" if sport_key in ("epl","mls") else f"{sport_key}-{endpoint}"

            # v1.9.1 quota control: proactively reuse a fresh server-side snapshot.
            # This survives page refreshes/restarts and prevents Android testing from
            # spending another Highlightly request every time Chrome reloads.
            cached,saved_at=read_cached(cache_name,flat)
            query_date=str(flat.get("date") or "")
            today=_client_date_iso(0,flat.get("timezone",""),client_utc_offset)
            limited_since=float(RATE_LIMIT_STATE.get("since") or 0)
            if RATE_LIMIT_STATE.get("limited") and limited_since and time.time()-limited_since < 15*60:
                if cached is not None:
                    response_payload=_reconcile_scoreboard_authority(cached,sport_key,query_date,flat.get("timezone",""),client_utc_offset) if endpoint=="matches" else cached
                    return send_json(self,response_payload,200,{"X-SBB-Cache":"RATE-LIMIT-STALE","X-SBB-Rate-Limited":"1","X-SBB-Cache-Age":str(int(max(0,time.time()-saved_at)))})
                if endpoint=="matches" and sport_key in ("epl","mls"):
                    return send_json(self,{"data":[]},200,{"X-SBB-Fallback":"SOCCER-CACHE-EMPTY","X-SBB-Rate-Limited":"1"})
                if endpoint=="highlights" and sport_key in ("epl","mls"):
                    return send_json(self,{"data":[]},200,{"X-SBB-Fallback":"OFFICIAL-VIDEO-PATH","X-SBB-Rate-Limited":"1"})
            if endpoint=="matches":
                # Current-day scheduled events near/past kickoff get a 45 s stale
                # window. Normal current-day snapshots stay quota-friendly at 3 min.
                transition=_payload_has_transition_game(cached,flat.get("timezone","")) if cached is not None and query_date==today else False
                ttl=(45 if transition else 180) if query_date==today else 21600
            else:
                ttl=900 if query_date==today else 21600
            if cached is not None and saved_at and time.time()-saved_at < ttl:
                response_payload=_reconcile_scoreboard_authority(cached,sport_key,query_date,flat.get("timezone",""),client_utc_offset) if endpoint=="matches" else cached
                return send_json(self,response_payload,200,{
                    "X-SBB-Cache":"HIT",
                    "X-SBB-Cache-Age":str(int(max(0,time.time()-saved_at))),
                    "X-SBB-RateLimit-Remaining":str(RATE_LIMIT_STATE.get("remaining") or ""),
                    "X-SBB-RateLimit-Limit":str(RATE_LIMIT_STATE.get("limit") or "")
                })
            try:
                with urlopen(req,timeout=15) as resp:
                    raw=resp.read(); data=json.loads(raw.decode("utf-8"))
                    if sport_key in ("epl","mls"):
                        data=_strict_soccer_rows(data,sport_key)
                        rows=(data.get("data") if isinstance(data,dict) else data) or []
                        if endpoint=="matches" and not rows and query_date:
                            try:
                                data=_football_day_fallback(query_date,sport_key,flat.get("timezone",""))
                            except Exception as soccer_fallback_exc:
                                print(f"[SBB soccer] broad-day fallback failed {sport_key} {query_date}: {type(soccer_fallback_exc).__name__}: {soccer_fallback_exc}",flush=True)
                    if endpoint=="matches":
                        data=_reconcile_scoreboard_authority(data,sport_key,query_date,flat.get("timezone",""),client_utc_offset)
                    remaining=resp.headers.get("x-ratelimit-requests-remaining","")
                    limit=resp.headers.get("x-ratelimit-requests-limit","")
                    RATE_LIMIT_STATE.update({"limited":False,"remaining":remaining,"limit":limit})
                    write_cached(cache_name,flat,data)
                    return send_json(self,data,200,{"X-SBB-RateLimit-Remaining":remaining,"X-SBB-RateLimit-Limit":limit,"X-SBB-Cache":"MISS"})
            except HTTPError as e:
                if e.code==429:
                    RATE_LIMIT_STATE.update({"limited":True,"since":time.time()})
                    cached,saved_at=read_cached(cache_name,flat)
                    if cached is not None:
                        response_payload=_reconcile_scoreboard_authority(cached,sport_key,query_date,flat.get("timezone",""),client_utc_offset) if endpoint=="matches" else cached
                        return send_json(self,response_payload,200,{"X-SBB-Cache":"STALE","X-SBB-Rate-Limited":"1","X-SBB-Cache-Age":str(int(max(0,time.time()-saved_at)))})
                    if endpoint=="matches" and sport_key in ("epl","mls"):
                        return send_json(self,{"data":[]},200,{"X-SBB-Fallback":"SOCCER-CACHE-EMPTY","X-SBB-Rate-Limited":"1"})
                    if endpoint=="highlights" and sport_key in ("epl","mls"):
                        return send_json(self,{"data":[]},200,{"X-SBB-Fallback":"OFFICIAL-VIDEO-PATH","X-SBB-Rate-Limited":"1"})
                try: detail=json.loads(e.read().decode("utf-8"))
                except Exception: detail={"message":str(e)}
                return send_json(self,{"ok":False,"error":"HIGHLIGHTLY_HTTP_ERROR","status":e.code,"detail":detail},e.code)
            except (URLError,socket.timeout) as e:
                return send_json(self,{"ok":False,"error":"HIGHLIGHTLY_CONNECTION_ERROR","message":str(e)},502)
            except Exception as e:
                return send_json(self,{"ok":False,"error":"SPORT_PROXY_ERROR","message":str(e)},502)

        if parsed.path == "/api/mlb/fallback-matches":
            qs=parse_qs(parsed.query)
            date=(qs.get("date") or [""])[-1]
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                return send_json(self, {"ok":False,"error":"DATE_REQUIRED"}, 400)
            try:
                items=normalized_stats_matches(date)
                return send_json(self, {"ok":True,"data":items,"source":"MLB Stats API"})
            except Exception as e:
                return send_json(self, {"ok":False,"error":"MLB_STATS_MATCH_ERROR","message":str(e)}, 502)

        if parsed.path == "/api/mlb/rapid-highlights":
            qs=parse_qs(parsed.query)
            date=(qs.get("date") or [""])[-1]
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                return send_json(self, {"ok":False,"error":"DATE_REQUIRED"}, 400)
            try:
                force=(qs.get("refresh") or ["0"])[-1] in ("1","true","yes")
                force_clips=(qs.get("clips") or ["0"])[-1] in ("1","true","yes")
                items=normalized_rapid_highlights(date,force_refresh=force,force_clips=force_clips)
                games=len(set(str(x.get('gamePk') or '') for x in items if x.get('gamePk')))
                return send_json(self,{"ok":True,"data":items,"source":"MLB Rapid Official","games":games,"items":len(items)})
            except Exception as e:
                return send_json(self,{"ok":False,"error":"MLB_RAPID_ERROR","message":str(e)},502)

        if parsed.path == "/api/mlb/stats-highlights":
            qs=parse_qs(parsed.query)
            date=(qs.get("date") or [""])[-1]
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                return send_json(self, {"ok":False,"error":"DATE_REQUIRED"}, 400)
            try:
                force=(qs.get("refresh") or ["0"])[-1] in ("1","true","yes")
                items=normalized_stats_highlights(date, force_refresh=force)
                return send_json(self, {"ok":True,"data":items,"source":"MLB Stats API","coverage":dict(coverage_state(date))})
            except Exception as e:
                return send_json(self, {"ok":False,"error":"MLB_STATS_ERROR","message":str(e)}, 502)

        if parsed.path in ("/api/mlb/matches", "/api/mlb/highlights"):
            key = read_key()
            if not key:
                return send_json(self, {
                    "ok": False,
                    "error": "HIGHLIGHTLY_API_KEY_NOT_CONFIGURED",
                    "message": "Add your Highlightly API key using START-ANDROID.sh or START SPORTS BIG BOARD.bat."
                }, 503)

            endpoint = "matches" if parsed.path.endswith("matches") else "highlights"
            qs = parse_qs(parsed.query)
            # Only allow the query parameters v1.1 actually uses.
            allowed = {"date", "timezone", "limit", "offset", "league", "leagueName", "matchId"}
            flat = {}
            for k, vals in qs.items():
                if k in allowed and vals:
                    flat[k] = vals[-1]
            flat.setdefault("limit", "100" if endpoint == "matches" else "40")
            if endpoint == "matches":
                flat.setdefault("league", "MLB")
            else:
                flat.setdefault("leagueName", "MLB")

            url = f"{BASE_URL}/baseball/{endpoint}?{urlencode(flat)}"
            req = Request(url, headers={
                "x-rapidapi-key": key,
                "Accept": "application/json",
                "User-Agent": "SportsBigBoard/4.0.2"
            })
            try:
                with urlopen(req, timeout=15) as resp:
                    raw = resp.read()
                    data = json.loads(raw.decode("utf-8"))
                    remaining = resp.headers.get("x-ratelimit-requests-remaining", "")
                    limit = resp.headers.get("x-ratelimit-requests-limit", "")
                    RATE_LIMIT_STATE.update({"limited": False, "remaining": remaining, "limit": limit})
                    write_cached(endpoint, flat, data)
                    return send_json(self, data, 200, {
                        "X-SBB-RateLimit-Remaining": remaining,
                        "X-SBB-RateLimit-Limit": limit,
                        "X-SBB-Cache": "MISS"
                    })
            except HTTPError as e:
                try:
                    detail = json.loads(e.read().decode("utf-8"))
                except Exception:
                    detail = {"message": str(e)}
                if e.code == 429:
                    RATE_LIMIT_STATE.update({"limited": True, "since": time.time()})
                    cached, saved_at = read_cached(endpoint, flat)
                    if cached is not None:
                        return send_json(self, cached, 200, {
                            "X-SBB-Cache": "STALE",
                            "X-SBB-Rate-Limited": "1",
                            "X-SBB-Cache-Age": str(int(max(0,time.time()-saved_at)))
                        })
                    return send_json(self, {"ok": False, "error": "HIGHLIGHTLY_RATE_LIMITED", "status": 429, "detail": detail}, 429)
                return send_json(self, {"ok": False, "error": "HIGHLIGHTLY_HTTP_ERROR", "status": e.code, "detail": detail}, e.code)
            except (URLError, socket.timeout) as e:
                return send_json(self, {"ok": False, "error": "HIGHLIGHTLY_CONNECTION_ERROR", "message": str(e)}, 502)
            except Exception as e:
                return send_json(self, {"ok": False, "error": "SERVER_ERROR", "message": str(e)}, 500)

        return super().do_GET()

if __name__ == "__main__":
    os.chdir(ROOT)
    print("\nSports Big Board v4.0.2 — normalized catalog + fail-closed event association")
    print(f"Bind: {BIND_HOST}:{PORT} • deployment: {DEPLOYMENT_MODE} • state: {STATE_DIR}")
    if not CLOUD_MODE: print(f"Open: http://localhost:{PORT}")
    print("Highlightly key:", "configured" if read_key() else "NOT CONFIGURED")
    print("YouTube key:", "configured" if read_youtube_key() else "NOT CONFIGURED (optional; needed for broader missing-game discovery)")
    
    if read_openai_key():
        verification=verify_openai_key()
        print("OpenAI editorial:", "verified" if verification.get("ok") else f"configured, verification warning: {verification.get('error','unknown')}")
        print("OpenAI model:", OPENAI_MODEL)
    else:
        print("OpenAI editorial: NOT CONFIGURED (deterministic rules active)")
    cache_count=len(EDITORIAL_SNAPSHOT.get("data") or [])
    cache_age=int(max(0,time.time()-float(EDITORIAL_SNAPSHOT.get("savedAt") or 0))) if EDITORIAL_SNAPSHOT.get("savedAt") else None
    if cache_count:
        print(f"Warm editorial cache: {cache_count} items ({cache_age}s old)")
    else:
        print("Warm editorial cache: empty; first deep refresh will run in background")
    print("Background refresh: source delta every 5 min • OpenAI editorial desk hourly")
    print(f"History catalog: {HISTORY_BACKFILL_DAYS} past days • no-search-quota media backfill {'ON' if HISTORY_BACKFILL_MEDIA else 'OFF'}")
    print(f"Green-gap queue: ON • one due game about every {HISTORY_GREEN_GAP_INTERVAL}s • search rescue no more than every {HISTORY_GREEN_SEARCH_RESCUE_INTERVAL//60} min")
    print(f"Historical quality policy: v{HISTORY_DISCOVERY_VERSION} • Gold > Green > Purple > Blue • lower tiers stay upgrade-eligible")
    print("Media prewarm: browser decoded-player HOT pool + persistent media/Game Center server caches • all-sports discovery remains active")
    print("Press Ctrl+C to stop.\n")
    association_repair=HISTORY_REPOSITORY.repair_event_associations()
    print("Association repair:",json.dumps(association_repair,separators=(',',':')))
    released=HISTORY_REPOSITORY.release_rebuild_pending_events(HISTORY_DISCOVERY_VERSION)
    if released:
        print(f"History reindex release: {released} reconstructed events made immediately eligible for discovery v{HISTORY_DISCOVERY_VERSION}.")
    _history_console_log('server','INFO',f'backend v{APP_VERSION} started • discovery v{HISTORY_DISCOVERY_VERSION} • {DEPLOYMENT_MODE}')
    _history_console_log('server','INFO',f'association integrity matcher v{association_repair.get("matcherVersion",0)} • assigned={association_repair.get("assignedLinks",0)} • quarantined={association_repair.get("quarantinedLinks",0)} • cross-event={association_repair.get("crossEventAssets",0)} • team-mismatch={association_repair.get("teamMismatch",0)} • date-mismatch={association_repair.get("dateMismatch",0)} • season-mismatch={association_repair.get("seasonMismatch",0)}')
    if released:
        _history_console_log('server','INFO',f'released {released} reconstructed events from migration cooldown • discovery v{HISTORY_DISCOVERY_VERSION}')
    threading.Thread(target=editorial_background_worker,daemon=True,name="sbb-editorial-worker").start()
    threading.Thread(target=game_center_startup_prewarm_worker,daemon=True,name="sbb-game-center-startup").start()
    threading.Thread(target=game_center_coverage_worker,daemon=True,name="sbb-game-center-coverage").start()
    threading.Thread(target=game_center_refresh_worker,daemon=True,name="sbb-game-center-refresh").start()
    threading.Thread(target=media_prewarm_worker,daemon=True,name="sbb-media-prewarm-worker").start()
    threading.Thread(target=history_backfill_worker,daemon=True,name="sbb-history-backfill").start()
    threading.Thread(target=history_green_gap_worker,daemon=True,name="sbb-history-green-gap").start()
    ThreadingHTTPServer((BIND_HOST, PORT), Handler).serve_forever()

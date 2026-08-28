"""Sports Big Board v4.4.8 dynamic NFL weekly recap playlist discovery.

Recognized official @NFL weekly patterns include:
- 2026 Preseason Week 3 Game Recaps
- 2026 Preseason Week 4 Game Recaps
- 2026 Season Week 1 Game Recaps
- 2026 Regular Season Week 12 Game Recaps

Discovery refreshes the official channel through YouTube playlists.list and then
uses the server's existing playlistItems.list + videos.list path. It deliberately
does not use search.list for weekly playlist discovery.
"""
from __future__ import annotations
import re, sys, threading, time
from datetime import datetime, timedelta

REFRESH_SECONDS = 20 * 60
PLAYLIST_ITEMS_REFRESH_SECONDS = 10 * 60
RECENT_WINDOW_DAYS = 35
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False

_WEEK_PATTERNS = (
    re.compile(r"\b(?P<year>20\d{2})\s+(?P<phase>preseason)\s+week\s*(?P<week>\d{1,2})\s+game\s+recaps?\b", re.I),
    re.compile(r"\b(?P<year>20\d{2})\s+(?P<phase>regular\s+season|season)\s+week\s*(?P<week>\d{1,2})\s+game\s+recaps?\b", re.I),
    re.compile(r"\b(?P<year>20\d{2})\s+week\s*(?P<week>\d{1,2})\s+(?P<phase>regular\s+season|season)\b.*\brecaps?\b", re.I),
    re.compile(r"\bweek\s*(?P<week>\d{1,2})\b.*\b(?P<year>20\d{2})\s+(?P<phase>regular\s+season|season|preseason)\b.*\brecaps?\b", re.I),
)

def weekly_title_info(title):
    text=str(title or "").strip()
    for rx in _WEEK_PATTERNS:
        m=rx.search(text)
        if not m: continue
        phase=str(m.group("phase") or "").lower()
        return {"year":int(m.group("year")),"week":int(m.group("week")),
                "phase":"preseason" if "preseason" in phase else "regular","title":text}
    return None

def is_weekly_recap_title(title):
    if weekly_title_info(title): return True
    low=str(title or "").lower()
    if re.search(r"press conference|mic.?d|sounds of|top plays|best plays|fantasy|preview|draft|combine|schedule release",low,re.I): return False
    return bool(re.search(r"\bgame recaps?\b|wild\s*card.*recaps?|divisional.*recaps?|conference.*recaps?|championship.*recaps?|super\s*bowl.*recaps?",low,re.I))

def _desired(server,date):
    season=int(server._nfl_season_year_for_date(date) or 0)
    pre=int(server._nfl_preseason_week_for_date(date) or 0)
    reg=int(server._nfl_regular_week_for_date(date) or 0)
    return season,("preseason" if pre else ("regular" if reg else "")),(pre or reg)

def _exact_match(server,row,date):
    season,phase,week=_desired(server,date);info=weekly_title_info((row or {}).get("title"))
    return bool(info and info["year"]==season and info["phase"]==phase and info["week"]==week)

def _recent_date(date):
    try:d=datetime.strptime(str(date)[:10],"%Y-%m-%d").date()
    except Exception:return False
    today=datetime.now().date()
    return today-timedelta(days=RECENT_WINDOW_DAYS)<=d<=today+timedelta(days=14)

def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:return
        _INSTALLED=True
    def runner():
        deadline=time.time()+90;server=None
        while time.time()<deadline:
            main=sys.modules.get("__main__")
            imported=sys.modules.get("server")
            server=next((mod for mod in (main,imported) if mod and all(hasattr(mod,n) for n in (
                "_nfl_playlist_title_is_recap","_nfl_youtube_playlist_catalog",
                "_nfl_candidate_recap_playlists","_nfl_youtube_playlist_items","_nfl_season_year_for_date",
                "_nfl_preseason_week_for_date","_nfl_regular_week_for_date"))),None)
            if server:break
            time.sleep(.2)
        if not server:return
        original_title=server._nfl_playlist_title_is_recap
        original_candidates=server._nfl_candidate_recap_playlists
        original_catalog=server._nfl_youtube_playlist_catalog
        original_items=server._nfl_youtube_playlist_items
        refresh_lock=threading.Lock();item_refresh={}
        state={"lastRefresh":0.0,"lastError":"","refreshes":0,"itemRefreshes":0}

        def title_guard(title):
            return is_weekly_recap_title(title) or bool(original_title(title))


        def items_guard(playlist,force=False):
            playlist=dict(playlist or {});pid=str(playlist.get("playlistId") or "")
            info=weekly_title_info(playlist.get("title"))
            now=time.time();last=float(item_refresh.get(pid) or 0)
            # Weekly playlists grow during the week. The legacy 30-day item cache
            # is appropriate for archives but not for a current weekly recap list.
            current_year=datetime.now().year
            published_recent=False
            try:
                published=str(playlist.get("publishedAt") or "")[:10]
                if published:
                    pd=datetime.strptime(published,"%Y-%m-%d").date()
                    published_recent=(datetime.now().date()-pd).days<=45
            except Exception:
                published_recent=False
            refresh_weekly=bool(info and (info["year"]==current_year or published_recent) and now-last>=PLAYLIST_ITEMS_REFRESH_SECONDS)
            use_force=bool(force or refresh_weekly)
            rows=original_items(playlist,force=use_force)
            if use_force and pid:
                item_refresh[pid]=now;state["itemRefreshes"]+=1
            return rows

        def candidate_guard(date):
            rows=list(original_candidates(date) or [])
            exact=next((x for x in rows if _exact_match(server,x,date)),None)
            if _recent_date(date) and not exact and time.time()-state["lastRefresh"]>=180:
                if refresh_lock.acquire(blocking=False):
                    try:
                        original_catalog(force=True);state["lastRefresh"]=time.time();state["refreshes"]+=1;state["lastError"]=""
                    except Exception as exc:
                        state["lastRefresh"]=time.time();state["lastError"]=f"{type(exc).__name__}: {exc}"
                    finally:refresh_lock.release()
                rows=list(original_candidates(date) or [])
            rows.sort(key=lambda x:(0 if _exact_match(server,x,date) else 1,-int((weekly_title_info((x or {}).get("title")) or {}).get("year") or 0)))
            return rows

        server._nfl_playlist_title_is_recap=title_guard
        server._nfl_candidate_recap_playlists=candidate_guard
        server._nfl_youtube_playlist_items=items_guard
        server.NFL_WEEKLY_PLAYLIST_DISCOVERY_STATE=state

        next_background_refresh=time.time()+REFRESH_SECONDS
        while True:
            time.sleep(60)
            try:
                if time.time()>=next_background_refresh:
                    original_catalog(force=True)
                    state["lastRefresh"]=time.time();state["refreshes"]+=1;state["lastError"]=""
                    next_background_refresh=time.time()+REFRESH_SECONDS
            except Exception as exc:
                state["lastError"]=f"{type(exc).__name__}: {exc}"
                next_background_refresh=time.time()+180
    threading.Thread(target=runner,name="sbb-nfl-weekly-playlists",daemon=True).start()

def snapshot():
    main=sys.modules.get("__main__")
    return dict(getattr(main,"NFL_WEEKLY_PLAYLIST_DISCOVERY_STATE",{}) or {})

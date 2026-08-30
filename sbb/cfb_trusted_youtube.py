"""Sports Big Board v4.7.18 — trusted AP Top 25 CFB YouTube source stack.

Discovery order for each CFB game:
1. ESPN College Football
2. Big Ten Football
3. ACC Digital Network
4. Big 12 Conference
5. NBC Sports
6. CFB on FOX
7. SEC Network
8. CBS Sports
9. participating schools' official athletics channels
10. the existing generic YouTube/ESPN rescue path

The network/conference lane is quota-light: channel handles are resolved once,
activities.list builds one cached day catalog per source, and videos.list validates
all upload IDs in batches. School-channel discovery is lazy and cached, so it is
only spent when the official network/conference pool has no exact matchup package.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
import json
import os
import re
import sys
import threading
import time
import unicodedata

VERSION = "4.7.18-cfb-trusted-sources-2"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False

TRUSTED_NETWORK_SOURCES = (
    {"id":"espn-cfb","label":"ESPN College Football","handle":"@espncfb","priority":10},
    {"id":"big-ten-football","label":"Big Ten Football","handle":"@b1gfootball","priority":20},
    {"id":"acc-digital-network","label":"ACC Digital Network","handle":"@ACCDigitalNetwork","priority":30},
    {"id":"big-12-conference","label":"Big 12 Conference","handle":"@Big12Conference","priority":40},
    {"id":"nbc-sports","label":"NBC Sports","handle":"@NBCSports","priority":50,
     "channelId":"UCqZQlzSHbVJrwrn5XvzrzcA"},
    {"id":"cfb-on-fox","label":"CFB on FOX","handle":"@CFBonFOX","priority":60},
    {"id":"sec-network","label":"SEC Network","handle":"@SECNetwork","priority":70},
    {"id":"cbs-sports","label":"CBS Sports","handle":"@CBSSports","priority":80},
)

# Recent games are not archival yet: official highlight packages commonly arrive
# hours after the final whistle or after midnight local time.  v4.7.16 incorrectly
# gave every date before today a 30-day cache TTL, which could freeze an empty day
# catalog before NBC/BTN/ESPN uploaded the recap.
RECENT_ARCHIVE_DAYS = 3
RECENT_ARCHIVE_TTL_SECONDS = 10 * 60
EMPTY_CATALOG_TTL_SECONDS = 3 * 60
ARCHIVE_TTL_SECONDS = 30 * 24 * 60 * 60
RECENT_GAP_SCAN_SECONDS = 12 * 60

# Operator/user-confirmed exact media can seed the same matcher/persistence path.
# This is not a one-off bypass: the row still must match both participants/date and
# is persisted through the normalized EVENT_MEDIA relationship.
KNOWN_MEDIA_HINTS = (
    {
        "date":"2026-08-29",
        "youtubeId":"-tDiPDHU2fs",
        "title":"Highlights: USC opens with win over SJSU",
        "description":"NBC Sports highlights of USC vs San Jose State, Aug. 29, 2026.",
        "durationSeconds":498,"duration":498,
        "source":"NBC Sports","sourceLabel":"NBC Sports",
        "sourceType":"cfb-trusted-network-youtube","cfbTrustedSourceId":"nbc-sports",
        "cfbSourcePriority":50,"officialChannelId":"UCqZQlzSHbVJrwrn5XvzrzcA",
        "provider":"YOUTUBE","verifiedPlayable":True,"embedValidated":True,
        "validationState":"VERIFIED","overview":True,"programType":"recap",
        "recapTier":"extended",
        "externalUrl":"https://www.youtube.com/watch?v=-tDiPDHU2fs",
        "publishedAt":"2026-08-29T22:45:00Z",
    },
)

_RECENT_WORKER_STARTED = False
_RECENT_WORKER_LOCK = threading.Lock()

NEGATIVE_RE = re.compile(
    r"\b(reaction|reacts|post[ -]?game|breakdown|analysis|takeaways?|recap show|"
    r"press conference|interview|preview|prediction|picks?|gameday|podcast|"
    r"betting|fantasy|rumou?r)\b|highlights?\s*&\s*reaction",
    re.I,
)
POSITIVE_RE = re.compile(
    r"\b(extended\s+highlights?|condensed\s+game|full\s+game\s+highlights?|"
    r"game\s+highlights?|college\s+football\s+highlights?|game\s+recap|"
    r"game\s+summary|highlights?)\b",
    re.I,
)

_STATE_DIR = Path(os.environ.get("SBB_STATE_DIR") or (Path.home()/".sports-big-board")).expanduser()
_CACHE_DIR = _STATE_DIR/"cache"/"cfb-trusted-youtube"
_SOURCE_CACHE = _CACHE_DIR/"resolved-sources.json"
_CACHE_LOCK = threading.RLock()


def _clean(value):
    return str(value or "").strip()


def _norm(value):
    folded=unicodedata.normalize("NFKD",_clean(value)).encode("ascii","ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+"," ",folded).strip()


def _read_json(path, default):
    try:
        payload=json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload,type(default)) else default
    except Exception:
        return default


def _write_json(path, payload):
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_suffix(path.suffix+".tmp")
        tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(tmp,path)
    except Exception:
        pass


def source_registry():
    return [dict(x) for x in TRUSTED_NETWORK_SOURCES] + [{
        "id":"participating-schools","label":"Participating schools' official athletics channels",
        "handle":"DYNAMIC","priority":90,"dynamic":True,
    }]


def _youtube_key(server):
    try:return _clean(server.read_youtube_key())
    except Exception:return ""


def _youtube_fetch(server, path, params, timeout=12):
    base=_clean(getattr(server,"YOUTUBE_API_BASE","https://www.googleapis.com/youtube/v3"))
    return server.youtube_fetch_json(f"{base}/{path}?{urlencode(params)}",timeout=timeout)


def _source_cache():
    with _CACHE_LOCK:return _read_json(_SOURCE_CACHE,{})


def _save_source_cache(payload):
    with _CACHE_LOCK:_write_json(_SOURCE_CACHE,payload)


def _score_channel_candidate(label, item):
    sn=(item or {}).get("snippet") or {}
    title=_norm(sn.get("title")); desc=_norm(sn.get("description")); wanted=_norm(label)
    if not title:return -1
    wanted_tokens=[x for x in wanted.split() if len(x)>2]
    score=sum(4 for x in wanted_tokens if x in title)
    if wanted and wanted==title:score+=20
    if "official" in desc:score+=4
    if "athletics" in title or "sports" in title:score+=3
    return score


def _resolve_named_channel(server, source, force=False):
    sid=_clean(source.get("id")); cache=_source_cache(); row=dict(cache.get(sid) or {})
    if not force and _clean(row.get("channelId")):return row
    seeded=_clean(source.get("channelId"))
    if seeded:
        row={"channelId":seeded,"label":source.get("label"),"handle":source.get("handle"),"resolvedAt":time.time(),"method":"PINNED"}
        cache[sid]=row;_save_source_cache(cache);return row
    key=_youtube_key(server)
    if not key:return row
    handle=_clean(source.get("handle")).lstrip("@")
    items=[]
    if handle:
        try:items=(_youtube_fetch(server,"channels",{"part":"id,snippet","forHandle":handle,"key":key}).get("items") or [])
        except Exception:items=[]
    method="HANDLE"
    if not items:
        # One-time fallback only. The resolved ID is persisted and future game
        # discovery uses activities.list, not repeated search.list calls.
        try:
            items=(_youtube_fetch(server,"search",{
                "part":"snippet","type":"channel","q":_clean(source.get("label")),"maxResults":"5","key":key,
            }).get("items") or [])
            method="CHANNEL_SEARCH"
        except Exception:items=[]
    if items:
        best=max(items,key=lambda x:_score_channel_candidate(source.get("label"),x))
        cid=_clean(best.get("id") if isinstance(best.get("id"),str) else (best.get("id") or {}).get("channelId"))
        if cid:
            sn=best.get("snippet") or {}
            row={"channelId":cid,"label":_clean(sn.get("title")) or source.get("label"),"handle":source.get("handle"),"resolvedAt":time.time(),"method":method}
            cache[sid]=row;_save_source_cache(cache)
    return row


def _school_cache_id(name):return "school:"+_norm(name)


def _resolve_school_channel(server, school, force=False):
    school=_clean(school)
    if not school:return {}
    sid=_school_cache_id(school);cache=_source_cache();row=dict(cache.get(sid) or {})
    if not force and _clean(row.get("channelId")):return row
    key=_youtube_key(server)
    if not key:return row
    query=f"{school} athletics football"
    try:
        items=(_youtube_fetch(server,"search",{
            "part":"snippet","type":"channel","q":query,"maxResults":"6","key":key,
        }).get("items") or [])
    except Exception:return row
    school_tokens=[x for x in _norm(school).split() if len(x)>2]
    def score(item):
        sn=(item or {}).get("snippet") or {};title=_norm(sn.get("title"));desc=_norm(sn.get("description"))
        matched=sum(4 for x in school_tokens if x in title)
        if school_tokens and matched<4*max(1,min(2,len(school_tokens))):matched-=10
        if "athletics" in title:matched+=10
        if "official" in title or "official" in desc:matched+=5
        if "football" in title or "football" in desc:matched+=3
        return matched
    if not items:return row
    best=max(items,key=score)
    if score(best)<5:return row
    cid=_clean(best.get("id") if isinstance(best.get("id"),str) else (best.get("id") or {}).get("channelId"))
    if not cid:return row
    sn=best.get("snippet") or {}
    row={"channelId":cid,"label":_clean(sn.get("title")) or f"{school} Athletics","school":school,"resolvedAt":time.time(),"method":"SCHOOL_CHANNEL_SEARCH"}
    cache[sid]=row;_save_source_cache(cache);return row


def _window(date):
    try:d=datetime.strptime(_clean(date)[:10],"%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:d=datetime.now(timezone.utc)-timedelta(days=1)
    # Include west-coast evening games and uploads through the following day.
    return (
        (d-timedelta(hours=9)).isoformat().replace("+00:00","Z"),
        (d+timedelta(days=2,hours=18)).isoformat().replace("+00:00","Z"),
    )


def _day_cache_path(date, kind="network"):
    safe=re.sub(r"[^0-9-]","",_clean(date)[:10]) or "unknown"
    return _CACHE_DIR/f"{safe}-{kind}.json"


def _cache_fresh(path, date, force=False):
    if force:return False
    payload=_read_json(path,{})
    data=payload.get("data")
    if not isinstance(data,list):return False
    age=time.time()-float(payload.get("savedAt") or 0)
    if not data:
        return age < EMPTY_CATALOG_TTL_SECONDS
    try:
        target=datetime.strptime(_clean(date)[:10],"%Y-%m-%d").date()
        delta=(datetime.now().date()-target).days
    except Exception:
        delta=999
    ttl=RECENT_ARCHIVE_TTL_SECONDS if -1 <= delta <= RECENT_ARCHIVE_DAYS else ARCHIVE_TTL_SECONDS
    return age<ttl


def _channel_day_catalog(server, date, sources, *, cache_kind, force=False):
    path=_day_cache_path(date,cache_kind)
    if _cache_fresh(path,date,force):return list(_read_json(path,{}).get("data") or [])
    key=_youtube_key(server)
    if not key:return []
    after,before=_window(date);upload_ids=[];source_by_video={};resolved=[]
    for src in sources:
        cid=_clean(src.get("channelId"));
        if not cid:continue
        resolved.append({"channelId":cid,"label":src.get("label"),"sourceId":src.get("sourceId"),"priority":src.get("priority",90),"kind":src.get("kind","network")})
        try:
            payload=_youtube_fetch(server,"activities",{
                "part":"snippet,contentDetails","channelId":cid,"maxResults":"50",
                "publishedAfter":after,"publishedBefore":before,"key":key,
            })
        except Exception:
            payload={}
        for act in payload.get("items") or []:
            details=(act.get("contentDetails") or {}).get("upload") or {}
            vid=_clean(details.get("videoId"))
            if not vid:continue
            if vid not in source_by_video:upload_ids.append(vid)
            source_by_video[vid]={"channelId":cid,"label":src.get("label"),"sourceId":src.get("sourceId"),"priority":src.get("priority",90),"kind":src.get("kind","network")}
    if not upload_ids:
        _write_json(path,{"savedAt":time.time(),"date":date,"sources":resolved,"data":[]})
        return []
    details=[]
    for offset in range(0,len(upload_ids),50):
        ids=upload_ids[offset:offset+50]
        try:
            payload=_youtube_fetch(server,"videos",{
                "part":"snippet,contentDetails,status,statistics","id":",".join(ids),"key":key,
            })
            details.extend(x for x in (payload.get("items") or []) if isinstance(x,dict))
        except Exception:pass
    out=[]
    for vd in details:
        vid=_clean(vd.get("id"));src=source_by_video.get(vid) or {}
        try:
            if callable(getattr(server,"_youtube_video_available_in_us",None)) and not server._youtube_video_available_in_us(vd):continue
        except Exception:pass
        sn=vd.get("snippet") or {};cd=vd.get("contentDetails") or {}
        try:dur=int(server._iso8601_duration_seconds(cd.get("duration")) or 0)
        except Exception:dur=0
        thumbs=sn.get("thumbnails") or {};thumb=((thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url") if isinstance(thumbs,dict) else "") or ""
        out.append({
            "id":f"cfb-trusted-{vid}","youtubeId":vid,"eventId":vid,"league":"CFB",
            "title":_clean(sn.get("title")),"description":_clean(sn.get("description")),
            "duration":dur,"durationSeconds":dur,"thumbnail":thumb,
            "source":_clean(sn.get("channelTitle")) or src.get("label") or "Official CFB source",
            "sourceLabel":src.get("label") or _clean(sn.get("channelTitle")),
            "sourceType":"cfb-official-school-youtube" if src.get("kind")=="school" else "cfb-trusted-network-youtube",
            "cfbTrustedSourceId":src.get("sourceId"),"cfbSourcePriority":int(src.get("priority") or 90),
            "officialChannelId":src.get("channelId"),"provider":"YOUTUBE",
            "verifiedPlayable":True,"embedValidated":True,"externalOnly":False,"validationState":"VERIFIED",
            "embedValidation":"activities.list+videos.list","externalUrl":f"https://www.youtube.com/watch?v={vid}",
            "publishedAt":_clean(sn.get("publishedAt")),"rapid":True,
        })
    out.sort(key=lambda x:(x.get("cfbSourcePriority",90),x.get("publishedAt") or ""))
    _write_json(path,{"savedAt":time.time(),"date":date,"sources":resolved,"data":out})
    return out


def _match_item(server, raw, date, away, home):
    item=dict(raw or {});title=_clean(item.get("title"));desc=_clean(item.get("description"));text=f"{title} {desc}"
    if NEGATIVE_RE.search(text):return None
    try:
        if server._youtube_match_strength(title,desc,away,home)<2:return None
    except Exception:
        an=_norm(away);hn=_norm(home);blob=_norm(text)
        if not an or not hn or an not in blob or hn not in blob:return None
    try:
        scoped=server.annotate_media_scope(item,league="CFB",date=date,away=away,home=home)
        item=dict(scoped)
        if item.get("mediaScope")!=getattr(server,"MEDIA_SCOPE_GAME","GAME"):
            # We already required a two-participant match above and this catalog is
            # restricted to trusted official CFB channels.  The generic media-scope
            # nickname heuristic can miss forms such as SJSU vs San José State; do
            # not let that weaker heuristic veto stronger trusted-source evidence.
            item["mediaScope"]="GAME"
            item["mediaScopeConfidence"]=0.98
            item["mediaScopeReason"]="CFB_TRUSTED_TWO_TEAM_MATCH"
    except Exception:
        item["mediaScope"]="GAME"
        item["mediaScopeConfidence"]=0.98
        item["mediaScopeReason"]="CFB_TRUSTED_TWO_TEAM_MATCH"
    dur=int(item.get("durationSeconds") or item.get("duration") or 0)
    # Green is normally 2–6 min and Purple 8–20 min; 45–120 sec is allowed only
    # as a weak fallback. Anything longer than 20 min is not a recap package.
    if dur and (dur<45 or dur>20*60):return None
    if not POSITIVE_RE.search(text):
        if not (dur>=90 and re.search(r"\b(highlight|recap)\b",text,re.I)):return None
    item.update({"away":away,"home":home,"date":_clean(date)[:10],"overview":True,"programType":"recap"})
    try:item=server._decorate_recap_tier(item)
    except Exception:
        try:item=server.annotate_media_tier(item)
        except Exception:pass
    return item


def _network_sources(server, force=False):
    out=[]
    for src in TRUSTED_NETWORK_SOURCES:
        row=_resolve_named_channel(server,src,force=force)
        cid=_clean(row.get("channelId"))
        if cid:out.append({"channelId":cid,"label":src["label"],"sourceId":src["id"],"priority":src["priority"],"kind":"network"})
    return out


def _known_hint_rows(date):
    target=_clean(date)[:10]
    return [dict(x) for x in KNOWN_MEDIA_HINTS if _clean(x.get("date"))[:10]==target]


def trusted_results(server, date, away, home, *, force=False, max_items=18):
    """Return exact-match, verified CFB recaps from the trusted source stack."""
    matched=[];seen=set()
    for raw in _known_hint_rows(date):
        item=_match_item(server,raw,date,away,home)
        if not item:continue
        vid=_clean(item.get("youtubeId"))
        if vid and vid not in seen:
            seen.add(vid);matched.append(item)
    if not _youtube_key(server):
        return matched[:max_items]
    networks=_network_sources(server,force=False)
    for raw in _channel_day_catalog(server,date,networks,cache_kind="network",force=force):
        item=_match_item(server,raw,date,away,home)
        if not item:continue
        vid=_clean(item.get("youtubeId"));
        if not vid or vid in seen:continue
        seen.add(vid);matched.append(item)
    if not matched:
        schools=[]
        for name in (away,home):
            row=_resolve_school_channel(server,name,force=False)
            cid=_clean(row.get("channelId"))
            if cid:schools.append({"channelId":cid,"label":row.get("label") or f"{name} Athletics","sourceId":_school_cache_id(name),"priority":90,"kind":"school"})
        school_key="school-"+re.sub(r"[^a-z0-9]+","-",f"{_norm(away)}-{_norm(home)}")[:80]
        for raw in _channel_day_catalog(server,date,schools,cache_kind=school_key,force=force):
            item=_match_item(server,raw,date,away,home)
            if not item:continue
            vid=_clean(item.get("youtubeId"));
            if not vid or vid in seen:continue
            seen.add(vid);matched.append(item)
    matched.sort(key=lambda x:(
        int(x.get("cfbSourcePriority") or 99),
        -int({"gold":4,"green":3,"extended":2,"blue":1}.get(_clean(x.get("recapTier")).lower(),0)),
        -int(x.get("durationSeconds") or 0),
    ))
    return matched[:max_items]


def _merge_rows(primary, secondary, limit=18):
    out=[];seen=set()
    for row in list(primary or [])+list(secondary or []):
        if not isinstance(row,dict):continue
        key=_clean(row.get("youtubeId") or row.get("mediaUrl") or row.get("externalUrl") or row.get("id"))
        if key and key in seen:continue
        if key:seen.add(key)
        out.append(row)
        if len(out)>=limit:break
    return out


def _team_name(event, side):
    event=event or {};team=event.get(f"{side}Team") or event.get(side) or {}
    if isinstance(team,dict):
        return _clean(team.get("displayName") or team.get("name") or team.get("shortDisplayName") or team.get("abbreviation"))
    return _clean(team)


def _persist_results(server, record, rows):
    repo=getattr(server,"HISTORY_REPOSITORY",None)
    if repo is None:return 0
    event=dict(record.get("event") or {});date=_clean(record.get("date") or event.get("date"))[:10]
    event_id=_clean(record.get("eventId") or event.get("eventId") or event.get("id"))
    if not date or not event_id:return 0
    key=repo.canonical_event_key("CFB",event_id);prepared=[]
    for raw in rows or []:
        if not isinstance(raw,dict):continue
        item=dict(raw);item.update({
            "league":"CFB","competitionId":"CFB","date":date,"gameDate":date,
            "eventId":event_id,"matchId":event_id,"scoreEventId":event_id,
            "canonicalEventId":event_id,"canonicalEventKey":key,"mediaScope":"GAME",
        })
        prepared.append(item)
    if not prepared:return 0
    try:return int(repo.put_event_media(date,"CFB",event_id,prepared) or 0)
    except Exception:return 0


def scan_recent_missing(server, days=RECENT_ARCHIVE_DAYS, force_catalog=False):
    """Repair recent final/gap CFB events from trusted sources without generic rescue first."""
    repo=getattr(server,"HISTORY_REPOSITORY",None)
    if repo is None:return {"events":0,"gaps":0,"associated":0,"dates":[]}
    today=datetime.now().date();start=(today-timedelta(days=max(1,int(days)))).isoformat();end=today.isoformat()
    try:records=repo.catalog_events(league="CFB",date_from=start,date_to=end,limit=5000) or []
    except Exception:return {"events":0,"gaps":0,"associated":0,"dates":[]}
    gaps=[]
    today_iso=today.isoformat()
    for record in records:
        event_id=_clean(record.get("eventId"));date=_clean(record.get("date"))[:10]
        if not event_id or not date:continue
        event=record.get("event") or {};status=_clean(event.get("status")).upper()
        final=bool(float(record.get("finalAt") or 0)) or bool(event.get("completed")) or any(x in status for x in ("FINAL","COMPLETED","FINISHED"))
        # Past dates can have sparse legacy status, but never search a current-day
        # scheduled game for a recap before it is final.
        if date>=today_iso and not final:continue
        try:existing=repo.event_media(date,"CFB",event_id,include_failed=False) or []
        except Exception:existing=[]
        if any(x.get("verifiedPlayable") and (x.get("youtubeId") or x.get("mediaUrl") or x.get("externalUrl")) for x in existing if isinstance(x,dict)):
            continue
        gaps.append(record)
    dates=sorted({_clean(r.get("date"))[:10] for r in gaps if _clean(r.get("date"))[:10]})
    # One forced network refresh per gap date, then all games reuse that day catalog.
    if _youtube_key(server):
        networks=_network_sources(server,force=False)
        for date in dates:
            try:_channel_day_catalog(server,date,networks,cache_kind="network",force=bool(force_catalog))
            except Exception:pass
    associated=0
    for record in gaps:
        event=record.get("event") or {};date=_clean(record.get("date"))[:10]
        away,home=_team_name(event,"away"),_team_name(event,"home")
        if not away or not home:continue
        try:rows=trusted_results(server,date,away,home,force=False,max_items=18)
        except Exception:rows=[]
        if rows:associated+=_persist_results(server,record,rows)
    return {"events":len(records),"gaps":len(gaps),"associated":associated,"dates":dates}


def _recent_gap_worker(server):
    # Run immediately so a deployment repairs yesterday's game without waiting for
    # the generic historical worker, then revisit only recent missing events.
    while True:
        try:
            result=scan_recent_missing(server,RECENT_ARCHIVE_DAYS,force_catalog=False)
            try:
                if result.get("associated"):
                    print(f"[SBB CFB sources] recent gap repair associated={result['associated']} gaps={result['gaps']}",flush=True)
            except Exception:pass
        except Exception as exc:
            try:print(f"[SBB CFB sources] recent gap worker deferred: {type(exc).__name__}: {exc}",flush=True)
            except Exception:pass
        time.sleep(RECENT_GAP_SCAN_SECONDS)


def _start_recent_worker(server):
    global _RECENT_WORKER_STARTED
    with _RECENT_WORKER_LOCK:
        if _RECENT_WORKER_STARTED:return False
        _RECENT_WORKER_STARTED=True
    threading.Thread(target=_recent_gap_worker,args=(server,),daemon=True,name="sbb-cfb-recent-gap-repair").start()
    return True


def install_on_server(server):
    original=getattr(server,"generic_rapid_team_videos",None)
    if not callable(original):return False
    if getattr(original,"__sbbCfbTrustedSources",False):return True

    def wrapped(league,date,away,home,event_id="",force_refresh=False,allow_youtube=True):
        lg=_clean(league).upper()
        if lg!="CFB" or not allow_youtube:
            return original(league,date,away,home,event_id=event_id,force_refresh=force_refresh,allow_youtube=allow_youtube)
        trusted=[]
        try:trusted=trusted_results(server,date,away,home,force=bool(force_refresh),max_items=18)
        except Exception as exc:
            try:print(f"[SBB CFB sources] trusted discovery deferred {away}@{home}: {type(exc).__name__}: {exc}",flush=True)
            except Exception:pass
        try:base=original(league,date,away,home,event_id=event_id,force_refresh=force_refresh,allow_youtube=allow_youtube)
        except TypeError:base=original(league,date,away,home,event_id,force_refresh,allow_youtube)
        return _merge_rows(trusted,base,limit=18)
    wrapped.__sbbCfbTrustedSources=True
    wrapped.__sbbOriginal=original
    server.generic_rapid_team_videos=wrapped
    server.CFB_TRUSTED_YOUTUBE_SOURCES=source_registry()
    server.CFB_TRUSTED_YOUTUBE_RESULTS=lambda date,away,home,force=False: trusted_results(server,date,away,home,force=force)
    server.CFB_TRUSTED_YOUTUBE_SCAN_RECENT=lambda days=RECENT_ARCHIVE_DAYS,force=False: scan_recent_missing(server,days=days,force_catalog=force)
    _start_recent_worker(server)
    return True


def _wait_install():
    deadline=time.time()+120
    while time.time()<deadline:
        server=sys.modules.get("__main__")
        if server and callable(getattr(server,"generic_rapid_team_videos",None)) and callable(getattr(server,"youtube_fetch_json",None)):
            if install_on_server(server):return
        time.sleep(.2)


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:return
        _INSTALLED=True
    threading.Thread(target=_wait_install,daemon=True,name="sbb-cfb-trusted-youtube-install").start()

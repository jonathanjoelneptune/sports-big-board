"""Sports Big Board v4.6.0 — persistent custom competition builder.

Installs without modifying server.py:
- persistent League / Special Event registry
- manual / pasted / OpenAI-web-search schedule ingestion
- canonical history-event upserts
- operator YouTube playlist registration for Green / Purple / Blue anchors
- generic Game Center for custom competition events
- active-event score refresh support

Media Intelligence is intentionally unrelated and remains parked.
"""
from __future__ import annotations
import csv, hashlib, io, json, os, re, sys, threading, time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo=None

_STATE_DIR=Path(os.environ.get("SBB_STATE_DIR") or (Path.home()/".sports-big-board")).expanduser()
_STORE=_STATE_DIR/"custom-competitions.json"
_LOCK=threading.RLock()
_INSTALL_LOCK=threading.Lock()
_INSTALLED=False
_SERVER=None
_REFRESH_THREAD=None
ID_RE=re.compile(r"^[A-Z][A-Z0-9_-]{1,23}$")
SPORTS={"baseball","american-football","basketball","ice-hockey","football","tennis","motorsport","athletics","action-sports","multi-sport"}

def _today():
    try:
        tz=os.environ.get("SBB_SCHEDULE_TIMEZONE") or "America/Los_Angeles"
        return datetime.now(ZoneInfo(tz)).date().isoformat() if ZoneInfo else datetime.now().date().isoformat()
    except Exception:
        return datetime.now().date().isoformat()

def lifecycle(comp,today=None):
    today=str(today or _today())[:10]
    start=str(comp.get("startDate") or "")[:10]
    end=str(comp.get("endDate") or "")[:10]
    if start and today<start:return "UPCOMING"
    if end and today>end:return "COMPLETED"
    return "ACTIVE"

def main_row(comp,today=None):
    if not comp.get("enabled",True):return False
    typ=str(comp.get("type") or "LEAGUE").upper()
    return typ=="LEAGUE" or (typ=="SPECIAL_EVENT" and lifecycle(comp,today)=="ACTIVE")

def _load():
    with _LOCK:
        try:
            p=json.loads(_STORE.read_text(encoding="utf-8"))
            rows=p.get("competitions") if isinstance(p,dict) else p
            return [dict(x) for x in (rows or []) if isinstance(x,dict)]
        except Exception:
            return []

def _save(rows):
    with _LOCK:
        _STORE.parent.mkdir(parents=True,exist_ok=True)
        tmp=_STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version":1,"updatedAt":time.time(),"competitions":rows},ensure_ascii=False,indent=2),encoding="utf-8")
        tmp.replace(_STORE)
    return rows

def _team(value,side="",score=None):
    if isinstance(value,dict):
        name=str(value.get("name") or value.get("displayName") or value.get("teamName") or value.get("region") or value.get("abbreviation") or "").strip()
        abbr=str(value.get("abbreviation") or value.get("abbr") or value.get("shortName") or "").strip()
        obj={**value,"name":name,"displayName":str(value.get("displayName") or name),"abbreviation":abbr,"side":side}
    else:
        name=str(value or "").strip();obj={"name":name,"displayName":name,"abbreviation":"","side":side}
    if score not in (None,""):obj["score"]=score
    return obj

def _score(raw,side):
    keys=[f"{side}Score",f"score{side.title()}"]
    for k in keys:
        if raw.get(k) not in (None,""):return raw.get(k)
    team=raw.get(side) or raw.get(f"{side}Team") or {}
    if isinstance(team,dict) and team.get("score") not in (None,""):return team.get("score")
    score=raw.get("score") or {}
    if isinstance(score,dict):
        for k in (side,f"{side}Score"):
            if score.get(k) not in (None,""):return score.get(k)
    return ""

def _event_id(comp_id,raw,date,away,home,idx=0):
    explicit=str(raw.get("eventId") or raw.get("matchId") or raw.get("gameId") or raw.get("id") or "").strip()
    if explicit:return explicit
    seed=f"{comp_id}|{date}|{away}|{home}|{raw.get('scheduledAt') or raw.get('time') or ''}|{idx}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]

def normalize_event(comp,raw,idx=0):
    raw=dict(raw or {})
    date=str(raw.get("date") or raw.get("gameDate") or raw.get("scheduledAt") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",date):
        raise ValueError(f"Schedule event {idx+1} is missing YYYY-MM-DD date")
    away_raw=raw.get("awayTeam") or raw.get("away") or raw.get("team1") or raw.get("visitor") or ""
    home_raw=raw.get("homeTeam") or raw.get("home") or raw.get("team2") or raw.get("host") or ""
    away_name=str(away_raw.get("name") if isinstance(away_raw,dict) else away_raw).strip()
    home_name=str(home_raw.get("name") if isinstance(home_raw,dict) else home_raw).strip()
    if not away_name or not home_name:raise ValueError(f"Schedule event {idx+1} is missing two participants")
    away_score=_score(raw,"away");home_score=_score(raw,"home")
    status=str(raw.get("status") or raw.get("state") or "").upper().strip()
    if not status:
        status="FINAL" if away_score not in ("",None) and home_score not in ("",None) else "SCHEDULED"
    scheduled=str(raw.get("scheduledAt") or "")
    if not scheduled:
        t=str(raw.get("time") or "").strip()
        scheduled=f"{date}T{t}" if t else date
    comp_id=str(comp["id"]).upper()
    event_id=_event_id(comp_id,raw,date,away_name,home_name,idx)
    away=_team(away_raw,"away",away_score);home=_team(home_raw,"home",home_score)
    return {
        **raw,
        "id":event_id,"eventId":event_id,"matchId":event_id,
        "competitionId":comp_id,"competitionName":comp["name"],"sportId":comp["sportId"],
        "__sbbLeague":comp_id,"__sbbDate":date,"date":date,"gameDate":date,"scheduledAt":scheduled,
        "away":away,"home":home,"awayTeam":away,"homeTeam":home,
        "awayScore":away_score,"homeScore":home_score,
        "participants":[away,home],"status":status,
        "stage":str(raw.get("stage") or raw.get("round") or raw.get("phase") or ""),
        "round":str(raw.get("round") or raw.get("stage") or ""),
        "venue":str(raw.get("venue") or ""),
        "broadcast":raw.get("broadcast") or raw.get("network") or "",
        "sourceUrl":str(raw.get("sourceUrl") or raw.get("url") or comp.get("scheduleSourceUrl") or ""),
        "gameCenterProviderHint":"competition-builder"
    }

def _normalize_sources(raw):
    raw=raw or {}
    result={"green":[],"purple":[],"blue":[]}
    for tier in result:
        values=raw.get(tier) or []
        if isinstance(values,str):values=[x.strip() for x in values.splitlines() if x.strip()]
        for item in values:
            if isinstance(item,str):item={"url":item}
            url=str((item or {}).get("url") or (item or {}).get("playlistId") or "").strip()
            if url:result[tier].append({**dict(item or {}),"url":url})
    return result

def normalize_definition(raw,existing=None):
    raw=dict(raw or {});existing=dict(existing or {})
    cid=str(raw.get("id") or existing.get("id") or "").upper().strip().replace(" ","_")
    if not ID_RE.fullmatch(cid):raise ValueError("Competition ID must be 2-24 uppercase letters/numbers/_/- and begin with a letter.")
    name=str(raw.get("name") or existing.get("name") or "").strip()
    if not name:raise ValueError("Competition name is required.")
    typ=str(raw.get("type") or existing.get("type") or "LEAGUE").upper()
    if typ not in {"LEAGUE","SPECIAL_EVENT"}:raise ValueError("type must be LEAGUE or SPECIAL_EVENT")
    sport=str(raw.get("sportId") or existing.get("sportId") or "multi-sport").strip()
    if sport not in SPORTS:raise ValueError(f"Unsupported sportId: {sport}")
    start=str(raw.get("startDate") or existing.get("startDate") or "")[:10]
    end=str(raw.get("endDate") or existing.get("endDate") or "")[:10]
    if start and not re.fullmatch(r"\d{4}-\d{2}-\d{2}",start):raise ValueError("startDate must be YYYY-MM-DD")
    if end and not re.fullmatch(r"\d{4}-\d{2}-\d{2}",end):raise ValueError("endDate must be YYYY-MM-DD")
    if start and end and end<start:raise ValueError("endDate cannot be before startDate")
    now=time.time()
    out={
        **existing,**raw,
        "id":cid,"name":name,"shortName":str(raw.get("shortName") or existing.get("shortName") or cid).strip(),
        "type":typ,"sportId":sport,"year":int(raw.get("year") or existing.get("year") or (start[:4] if start else datetime.now().year)),
        "startDate":start,"endDate":end,"format":str(raw.get("format") or existing.get("format") or "CUSTOM").upper(),
        "enabled":bool(raw.get("enabled",existing.get("enabled",True))),
        "scheduleMode":str(raw.get("scheduleMode") or existing.get("scheduleMode") or "PASTE").upper(),
        "scheduleSourceUrl":str(raw.get("scheduleSourceUrl") or existing.get("scheduleSourceUrl") or "").strip(),
        "scoreSourceUrl":str(raw.get("scoreSourceUrl") or existing.get("scoreSourceUrl") or raw.get("scheduleSourceUrl") or existing.get("scheduleSourceUrl") or "").strip(),
        "autoRefresh":bool(raw.get("autoRefresh",existing.get("autoRefresh",False))),
        "backgroundDiscovery":bool(raw.get("backgroundDiscovery",existing.get("backgroundDiscovery",True))),
        "refreshMinutes":max(5,min(1440,int(raw.get("refreshMinutes") or existing.get("refreshMinutes") or 30))),
        "mediaSources":_normalize_sources(raw.get("mediaSources") if "mediaSources" in raw else existing.get("mediaSources")),
        "gameCenterMode":"schedule",
        "createdAt":float(existing.get("createdAt") or now),"updatedAt":now
    }
    out["lifecycle"]=lifecycle(out);out["mainRow"]=main_row(out)
    return out

def parse_schedule_text(text):
    text=str(text or "").strip()
    if not text:return []
    if text[0] in "[{":
        data=json.loads(text)
        if isinstance(data,dict):data=data.get("events") or data.get("games") or data.get("matches") or []
        if not isinstance(data,list):raise ValueError("JSON schedule must be a list or contain events/games/matches.")
        return data
    reader=csv.DictReader(io.StringIO(text))
    rows=[dict(x) for x in reader]
    if not rows:raise ValueError("Schedule text was not valid JSON or CSV with a header row.")
    return rows

def _catalog_row(comp):
    x={k:v for k,v in comp.items() if k!="events"}
    x["lifecycle"]=lifecycle(comp);x["mainRow"]=main_row(comp);x["eventsCount"]=len(comp.get("events") or [])
    return x

def catalog():
    return [_catalog_row(x) for x in _load() if x.get("enabled",True)]

def competition_map():
    return {x["id"]:x for x in catalog()}

def _find(cid):
    cid=str(cid or "").upper()
    return next((x for x in _load() if str(x.get("id")).upper()==cid),None)

def _register_with_server(server,comp):
    cid=comp["id"]
    try:
        import sbb.competition_registry as registry
        registry.COMPETITIONS[cid]={
            "id":cid,"sportId":comp["sportId"],"name":comp["name"],
            "enabled":bool(main_row(comp)),"scoreProvider":"competition-builder",
            "mediaProviders":["operator-playlist","youtube"],"gameCenterProvider":"competition-builder",
            "custom":True,"type":comp["type"],"startDate":comp.get("startDate"),"endDate":comp.get("endDate")
        }
    except Exception:pass
    try:
        leagues=list(server.HISTORY_LEAGUES)
        if cid not in leagues:server.HISTORY_LEAGUES=tuple(leagues+[cid])
    except Exception:pass
    for ev in comp.get("events") or []:
        try:server.HISTORY_REPOSITORY.upsert_event(ev.get("date"),cid,ev.get("eventId"),ev)
        except Exception:pass

def _register_media_sources(server,comp):
    if not all(hasattr(server,n) for n in ("_operator_media_playlists_load","_operator_media_playlist_normalize","_operator_media_playlists_save","_operator_media_playlist_crawl_async")):return
    rows=server._operator_media_playlists_load()
    objective={"green":"quick","purple":"extended","blue":"coverage"}
    changed=False
    for tier,sources in (comp.get("mediaSources") or {}).items():
        for src in sources or []:
            url=str(src.get("url") or "").strip()
            if not url:continue
            pid=server._youtube_playlist_id(url)
            if not pid:continue
            existing=next((x for x in rows if str(x.get("league") or "").upper()==comp["id"] and str(x.get("playlistId") or "")==pid and str(x.get("objective") or "")==objective.get(tier,"coverage")),None)
            raw={"league":comp["id"],"url":url,"playlistId":pid,"seasonStart":comp["year"],"seasonEnd":comp["year"],"objective":objective.get(tier,"coverage"),"priority":str(src.get("priority") or "PRIMARY"),"trust":str(src.get("trust") or "OPERATOR_TRUSTED"),"enabled":True,"autoRecrawl":True,"recrawlMinutes":int(src.get("recrawlMinutes") or 60),"resolveMetadata":True}
            try:norm=server._operator_media_playlist_normalize(raw,existing)
            except Exception:continue
            if existing:
                rows[rows.index(existing)]=norm
            else:rows.append(norm)
            changed=True
            try:server._operator_media_playlist_crawl_async(norm.get("id"),force=False)
            except Exception:pass
    if changed:
        try:server._operator_media_playlists_save(rows)
        except Exception:pass

def save_competition(raw,events=None,server=None):
    rows=_load();cid=str((raw or {}).get("id") or "").upper()
    existing=next((x for x in rows if str(x.get("id")).upper()==cid),None)
    comp=normalize_definition(raw,existing)
    if events is None:events=raw.get("events") if isinstance(raw,dict) else None
    if events is None:events=(existing or {}).get("events") or []
    comp["events"]=[normalize_event(comp,x,i) for i,x in enumerate(events or [])]
    rows=[x for x in rows if str(x.get("id")).upper()!=comp["id"]];rows.append(comp);rows.sort(key=lambda x:(x.get("type")!="SPECIAL_EVENT",x.get("startDate") or "",x.get("name") or ""))
    _save(rows)
    if server:_register_with_server(server,comp);_register_media_sources(server,comp)
    return _catalog_row(comp)

def _extract_json(text):
    text=str(text or "").strip()
    try:return json.loads(text)
    except Exception:
        a=text.find("{");b=text.rfind("}")
        if a>=0 and b>a:return json.loads(text[a:b+1])
        raise ValueError("OpenAI schedule discovery did not return parseable JSON.")

def discover_schedule(server,draft):
    d=normalize_definition(draft,{})
    official=str(d.get("scheduleSourceUrl") or "")
    prompt=f"""Use web search to build a complete sports-event schedule/results dataset.
Competition: {d['name']}
Year/edition: {d['year']}
Sport: {d['sportId']}
Competition type: {d['type']}
Start date: {d.get('startDate') or 'unknown'}
End date: {d.get('endDate') or 'unknown'}
Preferred official schedule/results URL: {official or 'find the official organizer source'}

Prefer the official organizer/competition website. Do not invent games or scores.
Return JSON only with this shape:
{{
 "sourceUrls":["https://official..."],
 "sourceLabel":"official source description",
 "events":[
   {{
    "eventId":"stable source id or generated match number",
    "date":"YYYY-MM-DD",
    "scheduledAt":"ISO-8601 or date/time string",
    "away":"participant/team 1",
    "home":"participant/team 2",
    "awayScore":0,
    "homeScore":0,
    "status":"FINAL|LIVE|SCHEDULED",
    "round":"Group A / Round of 16 / Championship / etc",
    "stage":"stage if known",
    "venue":"venue if known",
    "broadcast":"network/platform if known",
    "sourceUrl":"official event/schedule URL"
   }}
 ]
}}
For knockout/bracket games whose future participant is not yet known, preserve source labels like Winner Game 35 or TBA rather than guessing. Include every tournament game in the requested date range."""
    model=os.environ.get("SBB_COMPETITION_BUILDER_MODEL") or str(getattr(server,"OPENAI_MODEL","gpt-5-mini"))
    resp=server.openai_api_request("/responses",{"model":model,"tools":[{"type":"web_search"}],"input":prompt,"max_output_tokens":20000},timeout=120)
    text=server.openai_output_text(resp)
    data=_extract_json(text)
    events=data.get("events") or []
    normalized=[normalize_event(d,x,i) for i,x in enumerate(events)]
    return {"competition":_catalog_row({**d,"events":normalized}),"events":normalized,"sourceUrls":data.get("sourceUrls") or [],"sourceLabel":data.get("sourceLabel") or "OpenAI web search"}

def generic_game_center(comp,event):
    away=event.get("awayTeam") or event.get("away") or {}
    home=event.get("homeTeam") or event.get("home") or {}
    live="LIVE" in str(event.get("status") or "").upper()
    def s(t,side):
        return t.get("score") if isinstance(t,dict) and t.get("score") not in (None,"") else event.get(f"{side}Score","")
    scoreboard={
        "away":{"team":away,"score":s(away,"away")},
        "home":{"team":home,"score":s(home,"home")},
        "status":event.get("status") or "SCHEDULED",
        "venue":event.get("venue") or "",
        "period":event.get("period"),"clock":event.get("clock") or ""
    }
    return {
        "version":"1.0","competitionId":comp["id"],"eventId":event["eventId"],"event":deepcopy(event),
        "scoreboard":scoreboard,"teamStats":event.get("teamStats") or [],
        "playerStatSections":event.get("playerStatSections") or [],
        "timeline":event.get("timeline") or [],"scoringPlays":event.get("scoringPlays") or [],
        "coverage":{"scoreboard":True,"teamStats":bool(event.get("teamStats")),"players":bool(event.get("playerStatSections")),"timeline":bool(event.get("timeline")),"complete":False},
        "quality":{"level":"basic","source":"competition-builder"},"partial":True,
        "updatedAt":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"live":live,"source":"competition-builder schedule/results"
    }

def _read_body(handler):
    n=max(0,min(10_000_000,int(handler.headers.get("Content-Length") or 0)))
    raw=handler.rfile.read(n) if n else b"{}"
    return json.loads(raw.decode("utf-8") or "{}")

def _send(server,handler,payload,status=200):
    return server.send_json(handler,payload,status)

def _handle_get(server,handler,parsed):
    if parsed.path=="/api/competition-builder/catalog":
        rows=catalog()
        return _send(server,handler,{"ok":True,"version":1,"today":_today(),"competitions":rows,"specialEvents":[x for x in rows if x.get("type")=="SPECIAL_EVENT"],"mainRow":[x for x in rows if x.get("mainRow")]})
    if parsed.path=="/api/competition-builder/schedule":
        qs=parse_qs(parsed.query);cid=str((qs.get("id") or [""])[-1]).upper();date=str((qs.get("date") or [""])[-1])[:10]
        comp=_find(cid)
        if not comp:return _send(server,handler,{"ok":False,"error":"COMPETITION_NOT_FOUND"},404)
        events=[x for x in comp.get("events") or [] if not date or x.get("date")==date]
        return _send(server,handler,{"ok":True,"competition":_catalog_row(comp),"date":date,"events":events})
    if parsed.path=="/api/competition-builder/media":
        qs=parse_qs(parsed.query);cid=str((qs.get("id") or [""])[-1]).upper();date=str((qs.get("date") or [""])[-1])[:10]
        comp=_find(cid)
        if not comp:return _send(server,handler,{"ok":False,"error":"COMPETITION_NOT_FOUND"},404)
        media=[]
        for ev in comp.get("events") or []:
            if date and ev.get("date")!=date:continue
            try:
                rows=server.HISTORY_REPOSITORY.event_media(ev.get("date"),cid,ev.get("eventId"),include_failed=False)
            except TypeError:
                rows=server.HISTORY_REPOSITORY.event_media(ev.get("date"),cid,ev.get("eventId"))
            except Exception:
                rows=[]
            for item in rows or []:
                x=dict(item);x.setdefault("league",cid);x.setdefault("competitionId",cid);x.setdefault("competitionName",comp["name"]);x.setdefault("eventId",ev.get("eventId"));x.setdefault("matchId",ev.get("eventId"));x.setdefault("date",ev.get("date"));x.setdefault("__sbbDate",ev.get("date"));x.setdefault("sport",comp["sportId"]);media.append(x)
        return _send(server,handler,{"ok":True,"competition":_catalog_row(comp),"date":date,"media":media})
    if parsed.path=="/api/competition-builder/definition":
        qs=parse_qs(parsed.query);comp=_find((qs.get("id") or [""])[-1])
        return _send(server,handler,{"ok":bool(comp),"competition":comp},200 if comp else 404)
    m=re.fullmatch(r"/api/events/([^/]+)/([^/]+)/game-center",parsed.path)
    if m:
        cid=unquote(m.group(1)).upper();eid=unquote(m.group(2));comp=_find(cid)
        if not comp:return False
        event=next((x for x in comp.get("events") or [] if str(x.get("eventId"))==eid),None)
        if not event:return _send(server,handler,{"ok":False,"error":"CUSTOM_EVENT_NOT_FOUND"},404)
        return _send(server,handler,{"ok":True,"data":generic_game_center(comp,event),"resolvedEventId":eid,"cache":"CUSTOM-COMPETITION"},200)
    return False

def _handle_post(server,handler,parsed):
    if parsed.path!="/api/competition-builder":return False
    try:body=_read_body(handler)
    except Exception as exc:return _send(server,handler,{"ok":False,"error":"BAD_JSON","message":str(exc)},400)
    action=str(body.get("action") or "save").lower()
    try:
        if action=="discover":
            return _send(server,handler,{"ok":True,"preview":discover_schedule(server,body.get("competition") or {})},200)
        if action=="save":
            comp_raw=body.get("competition") or {}
            events=body.get("events")
            if events is None and body.get("scheduleText"):events=parse_schedule_text(body.get("scheduleText"))
            saved=save_competition(comp_raw,events,server)
            return _send(server,handler,{"ok":True,"competition":saved,"catalog":catalog()},200)
        if action=="delete":
            cid=str(body.get("id") or "").upper();rows=[x for x in _load() if str(x.get("id")).upper()!=cid];_save(rows)
            try:
                import sbb.competition_registry as registry
                registry.COMPETITIONS.pop(cid,None)
            except Exception:pass
            return _send(server,handler,{"ok":True,"deleted":cid,"catalog":catalog()},200)
        if action=="refresh":
            comp=_find(body.get("id"))
            if not comp:return _send(server,handler,{"ok":False,"error":"COMPETITION_NOT_FOUND"},404)
            preview=discover_schedule(server,comp)
            saved=save_competition(comp,preview.get("events") or [],server)
            return _send(server,handler,{"ok":True,"competition":saved,"preview":preview},200)
        return _send(server,handler,{"ok":False,"error":"UNKNOWN_ACTION"},400)
    except Exception as exc:
        return _send(server,handler,{"ok":False,"error":type(exc).__name__,"message":str(exc)},502 if action=="discover" else 400)

def _parse_iso_duration(server,value):
    try:return int(server._iso8601_duration_seconds(value) or 0)
    except Exception:return 0

def _generic_youtube_gap_search(server,comp,event):
    """One low-frequency exact-game fallback search. Primary playlists remain preferred."""
    if not getattr(server,"read_youtube_key",lambda:"")():return 0
    if hasattr(server,"_youtube_search_available") and not server._youtube_search_available():return 0
    away=str((event.get("awayTeam") or {}).get("name") or (event.get("away") or {}).get("name") or "")
    home=str((event.get("homeTeam") or {}).get("name") or (event.get("home") or {}).get("name") or "")
    if not away or not home:return 0
    date=str(event.get("date") or "")[:10]
    try:d=datetime.strptime(date,"%Y-%m-%d")
    except Exception:return 0
    after=(d.replace(tzinfo=timezone.utc)-__import__("datetime").timedelta(hours=8)).isoformat().replace("+00:00","Z")
    before=(d.replace(tzinfo=timezone.utc)+__import__("datetime").timedelta(days=3)).isoformat().replace("+00:00","Z")
    query=f'{away} {home} {comp.get("shortName") or comp.get("name")} highlights'
    from urllib.parse import urlencode
    key=server.read_youtube_key()
    params={"part":"snippet","q":query,"type":"video","maxResults":"8","order":"relevance","videoEmbeddable":"true","videoSyndicated":"true","safeSearch":"moderate","regionCode":"US","relevanceLanguage":"en","publishedAfter":after,"publishedBefore":before,"key":key}
    search=server.youtube_fetch_json(f"{server.YOUTUBE_API_BASE}/search?{urlencode(params)}",timeout=12)
    ids=[str((x.get("id") or {}).get("videoId") or "") for x in (search.get("items") or [])];ids=[x for x in ids if x]
    if not ids:return 0
    details=server.youtube_fetch_json(f"{server.YOUTUBE_API_BASE}/videos?{urlencode({'part':'snippet,contentDetails,status','id':','.join(ids),'key':key})}",timeout=12)
    rows=[]
    away_key=re.sub(r"[^a-z0-9]+","",away.lower());home_key=re.sub(r"[^a-z0-9]+","",home.lower())
    for vd in details.get("items") or []:
        vid=str(vd.get("id") or "");sn=vd.get("snippet") or {};title=str(sn.get("title") or "");low=re.sub(r"[^a-z0-9]+","",title.lower())
        if away_key and away_key not in low and re.sub(r"[^a-z0-9]+","",away.split()[-1].lower()) not in low:continue
        if home_key and home_key not in low and re.sub(r"[^a-z0-9]+","",home.split()[-1].lower()) not in low:continue
        dur=_parse_iso_duration(server,(vd.get("contentDetails") or {}).get("duration"))
        row={"id":f"custom-youtube-{vid}","youtubeId":vid,"league":comp["id"],"competitionId":comp["id"],"competitionName":comp["name"],"eventId":event["eventId"],"matchId":event["eventId"],"date":date,"gameDate":date,"title":title,"description":str(sn.get("description") or ""),"duration":dur,"durationSeconds":dur,"provider":"YOUTUBE","source":"YouTube search","sourceType":"custom-competition-youtube-gap","externalUrl":f"https://www.youtube.com/watch?v={vid}","verifiedPlayable":True,"embedValidated":True,"validationState":"VERIFIED","programType":"recap" if dur>=90 else "reel","overview":dur>=90,"publishedAt":str(sn.get("publishedAt") or "")}
        try:row=server.annotate_media_tier(row)
        except Exception:pass
        rows.append(row)
    if rows:
        try:server.HISTORY_REPOSITORY.put_media(date,comp["id"],rows,merge=True)
        except Exception:pass
        try:server.HISTORY_REPOSITORY.put_event_media(date,comp["id"],event["eventId"],rows)
        except Exception:pass
    return len(rows)

_GENERIC_GAP_STATE={"lastAt":0.0,"competition":"","eventId":"","found":0,"error":""}

def _run_generic_gap_once(server):
    now=time.time()
    if now-float(_GENERIC_GAP_STATE.get("lastAt") or 0)<30*60:return
    try:
        if hasattr(server,"_history_server_idle") and not server._history_server_idle():return
    except Exception:return
    for comp in _load():
        if not comp.get("enabled",True) or not comp.get("backgroundDiscovery",True):continue
        for ev in reversed(comp.get("events") or []):
            if str(ev.get("status") or "").upper() not in {"FINAL","COMPLETED","FINISHED"}:continue
            try:existing=server.HISTORY_REPOSITORY.event_media(ev.get("date"),comp["id"],ev.get("eventId"),include_failed=False)
            except Exception:existing=[]
            if any(x.get("verifiedPlayable") and (x.get("youtubeId") or x.get("mediaUrl")) for x in (existing or [])):continue
            _GENERIC_GAP_STATE.update(lastAt=now,competition=comp["id"],eventId=ev.get("eventId"),found=0,error="")
            try:_GENERIC_GAP_STATE["found"]=_generic_youtube_gap_search(server,comp,ev)
            except Exception as exc:_GENERIC_GAP_STATE["error"]=f"{type(exc).__name__}: {exc}"
            return

def _refresh_active(server):
    while True:
        try:
            now=time.time()
            for comp in _load():
                if lifecycle(comp)!="ACTIVE" or not comp.get("enabled",True) or not comp.get("autoRefresh") or comp.get("scheduleMode")!="AUTO_DISCOVER":continue
                last=float(comp.get("lastAutoRefreshAt") or 0);period=max(5,int(comp.get("refreshMinutes") or 30))*60
                if now-last<period:continue
                try:
                    preview=discover_schedule(server,comp)
                    raw=dict(comp);raw["lastAutoRefreshAt"]=time.time();raw["lastDiscoverySources"]=preview.get("sourceUrls") or []
                    save_competition(raw,preview.get("events") or [],server)
                except Exception:
                    rows=_load()
                    for x in rows:
                        if x.get("id")==comp.get("id"):x["lastAutoRefreshAt"]=time.time();x["lastRefreshError"]="auto refresh failed";x["updatedAt"]=time.time()
                    _save(rows)
        except Exception:pass
        try:_run_generic_gap_once(server)
        except Exception:pass
        time.sleep(60)

def _install_into_server():
    global _SERVER,_REFRESH_THREAD
    deadline=time.time()+120;server=None
    while time.time()<deadline:
        server=sys.modules.get("__main__")
        if server and all(hasattr(server,x) for x in ("Handler","send_json","HISTORY_REPOSITORY","HISTORY_LEAGUES")):break
        time.sleep(.2)
    if not server:return
    _SERVER=server
    for comp in _load():_register_with_server(server,comp)
    Handler=server.Handler
    if not getattr(Handler,"__sbbCompetitionBuilderInstalled",False):
        old_get=Handler.do_GET;old_post=Handler.do_POST
        def do_GET(self):
            parsed=urlparse(self.path)
            handled=_handle_get(server,self,parsed)
            if handled is not False:return handled
            return old_get(self)
        def do_POST(self):
            parsed=urlparse(self.path)
            handled=_handle_post(server,self,parsed)
            if handled is not False:return handled
            return old_post(self)
        Handler.do_GET=do_GET;Handler.do_POST=do_POST;Handler.__sbbCompetitionBuilderInstalled=True
    if _REFRESH_THREAD is None:
        _REFRESH_THREAD=threading.Thread(target=_refresh_active,args=(server,),name="sbb-competition-refresh",daemon=True);_REFRESH_THREAD.start()

def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:return
        _INSTALLED=True
    threading.Thread(target=_install_into_server,name="sbb-competition-builder-install",daemon=True).start()

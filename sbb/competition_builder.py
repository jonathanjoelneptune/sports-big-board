"""Sports Big Board v4.6.6 — persistent custom competition builder.

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
import csv, hashlib, html, io, json, os, re, sys, threading, time
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote
from urllib.request import Request, urlopen
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
_CRAWL_STATE={"worker":"STARTING","lastAt":0.0,"lastCompetition":"","lastEventId":"","found":0,"attempts":0,"errors":0,"lastError":""}
_CATALOG_REVISION=0
ID_RE=re.compile(r"^[A-Z][A-Z0-9_-]{1,23}$")
SPORTS={"baseball","american-football","basketball","ice-hockey","football","tennis","motorsport","athletics","action-sports","multi-sport"}
LOGO_STRATEGIES={"AUTO","TEAM_LOGOS","COUNTRY_FLAGS","PROVIDED","NONE"}
_COUNTRY_FLAG_CODES={"argentina":"ar","australia":"au","austria":"at","algeria":"dz","belgium":"be","bolivia":"bo","brazil":"br","cameroon":"cm","canada":"ca","cabo verde":"cv","cape verde":"cv","chile":"cl","china":"cn","colombia":"co","costa rica":"cr","croatia":"hr","curacao":"cw","curaçao":"cw","czech republic":"cz","czechia":"cz","denmark":"dk","dominican republic":"do","dr congo":"cd","ecuador":"ec","egypt":"eg","england":"gb-eng","france":"fr","germany":"de","ghana":"gh","greece":"gr","guatemala":"gt","haiti":"ht","honduras":"hn","hungary":"hu","iceland":"is","indonesia":"id","iran":"ir","ir iran":"ir","iraq":"iq","ireland":"ie","israel":"il","italy":"it","ivory coast":"ci","cote d ivoire":"ci","côte d’ivoire":"ci","jamaica":"jm","japan":"jp","jordan":"jo","korea republic":"kr","south korea":"kr","mexico":"mx","morocco":"ma","netherlands":"nl","new zealand":"nz","nigeria":"ng","north macedonia":"mk","norway":"no","panama":"pa","paraguay":"py","peru":"pe","poland":"pl","portugal":"pt","qatar":"qa","romania":"ro","saudi arabia":"sa","scotland":"gb-sct","senegal":"sn","serbia":"rs","slovakia":"sk","slovenia":"si","south africa":"za","spain":"es","sweden":"se","switzerland":"ch","tunisia":"tn","turkey":"tr","türkiye":"tr","ukraine":"ua","united arab emirates":"ae","united states":"us","usa":"us","u.s.a.":"us","uruguay":"uy","uzbekistan":"uz","venezuela":"ve","wales":"gb-wls"}
_ASSOCIATION_REPAIR_AT={}
_RESULT_RECONCILE_AT={}
_PLACEHOLDER_PARTICIPANT_RE=re.compile(r"^(?:tba|tbd|to be (?:announced|determined)|winner(?: of)? (?:match|game)?\s*\d+|loser(?: of)? (?:match|game)?\s*\d+|winner\s+group\s+[a-z]|runner[- ]?up\s+group\s+[a-z]|\d+(?:st|nd|rd|th)?\s+(?:group\s+)?[a-z])$",re.I)

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
    global _CATALOG_REVISION
    with _LOCK:
        _STORE.parent.mkdir(parents=True,exist_ok=True)
        _CATALOG_REVISION=max(int(time.time()*1000),int(_CATALOG_REVISION or 0)+1)
        payload=json.dumps({"version":2,"revision":_CATALOG_REVISION,"updatedAt":time.time(),"competitions":rows},ensure_ascii=False,indent=2)
        tmp=_STORE.with_suffix(".tmp")
        with tmp.open("w",encoding="utf-8") as fh:
            fh.write(payload);fh.flush();os.fsync(fh.fileno())
        os.replace(tmp,_STORE)
    return rows

def _store_revision():
    try:
        payload=json.loads(_STORE.read_text(encoding="utf-8"))
        if isinstance(payload,dict) and payload.get("revision"):return int(payload.get("revision"))
    except Exception:pass
    try:return int(_STORE.stat().st_mtime_ns//1_000_000)
    except Exception:return int(_CATALOG_REVISION or 0)

def _name_key(value):
    text=str(value or "").strip().lower().replace("&"," and ")
    text=re.sub(r"[^a-z0-9à-ÿ]+"," ",text,flags=re.I)
    return re.sub(r"\s+"," ",text).strip()

def _effective_logo_strategy(comp):
    raw=str((comp or {}).get("logoStrategy") or "AUTO").upper().strip()
    if raw not in LOGO_STRATEGIES:raw="AUTO"
    if raw=="AUTO" and str((comp or {}).get("sportId") or "")=="football" and "world cup" in str((comp or {}).get("name") or "").lower():return "COUNTRY_FLAGS"
    return raw

def _country_code_for_name(name):
    key=_name_key(name)
    if key in _COUNTRY_FLAG_CODES:return _COUNTRY_FLAG_CODES[key]
    key=re.sub(r"\b(national team|men|women|football|soccer|team)\b"," ",key)
    return _COUNTRY_FLAG_CODES.get(re.sub(r"\s+"," ",key).strip(),"")

def _decorate_team_artwork(comp,team):
    team=dict(team or {});strategy=_effective_logo_strategy(comp)
    if strategy=="NONE":
        for key in ("logo","logoUrl","image","imageUrl"):team.pop(key,None)
        return team
    if strategy=="COUNTRY_FLAGS":
        code=str(team.get("countryCode") or team.get("country") or "").lower().strip()
        if len(code)>6 or not re.fullmatch(r"[a-z]{2}(?:-[a-z]{3})?",code):code=_country_code_for_name(team.get("name") or team.get("displayName"))
        if code:
            team["countryCode"]=code.upper();team["logo"]=f"https://flagcdn.com/w80/{code}.png";team["artworkType"]="COUNTRY_FLAG"
        return team
    if team.get("logo") or team.get("logoUrl") or team.get("image") or team.get("imageUrl"):team["artworkType"]="TEAM_LOGO" if strategy=="TEAM_LOGOS" else "PROVIDED"
    return team

def _decorate_event_artwork(comp,event):
    event=dict(event or {})
    away=_decorate_team_artwork(comp,event.get("awayTeam") or event.get("away") or {})
    home=_decorate_team_artwork(comp,event.get("homeTeam") or event.get("home") or {})
    event.update({"away":away,"home":home,"awayTeam":away,"homeTeam":home,"participants":[away,home],"logoStrategy":_effective_logo_strategy(comp)})
    return event

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
    result={
        **raw,
        "id":event_id,"eventId":event_id,"matchId":event_id,
        "competitionId":comp_id,"competitionName":comp["name"],"sportId":comp["sportId"],
        "__sbbLeague":comp_id,"__sbbDate":date,"date":date,"gameDate":date,"scheduledAt":scheduled,
        "away":away,"home":home,"awayTeam":away,"homeTeam":home,
        "awayName":away_name,"homeName":home_name,"awayTeamName":away_name,"homeTeamName":home_name,
        "awayScore":away_score,"homeScore":home_score,
        "participants":[away,home],"status":status,
        "stage":str(raw.get("stage") or raw.get("round") or raw.get("phase") or ""),
        "round":str(raw.get("round") or raw.get("stage") or ""),
        "venue":str(raw.get("venue") or ""),
        "broadcast":raw.get("broadcast") or raw.get("network") or "",
        "sourceUrl":str(raw.get("sourceUrl") or raw.get("url") or comp.get("scheduleSourceUrl") or ""),
        "gameCenterProviderHint":"competition-builder"
    }
    return _decorate_event_artwork(comp,result)

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
        "logoStrategy":str(raw.get("logoStrategy") or existing.get("logoStrategy") or "AUTO").upper(),
        "enabled":bool(raw.get("enabled",existing.get("enabled",True))),
        "scheduleMode":str(raw.get("scheduleMode") or existing.get("scheduleMode") or "PASTE").upper(),
        "scheduleSourceUrl":str(raw.get("scheduleSourceUrl") or existing.get("scheduleSourceUrl") or "").strip(),
        "scoreSourceUrl":str(raw.get("scoreSourceUrl") or existing.get("scoreSourceUrl") or raw.get("scheduleSourceUrl") or existing.get("scheduleSourceUrl") or "").strip(),
        "autoRefresh":bool(raw.get("autoRefresh",existing.get("autoRefresh",False))),
        "backgroundDiscovery":bool(raw.get("backgroundDiscovery",existing.get("backgroundDiscovery",True))),
        "crawlEnabled":bool(raw.get("crawlEnabled",existing.get("crawlEnabled",True))),
        "expectedEventCount":max(0,int(raw.get("expectedEventCount") or existing.get("expectedEventCount") or 0)),
        "allowIncompleteSchedule":bool(raw.get("allowIncompleteSchedule",existing.get("allowIncompleteSchedule",False))),
        "refreshMinutes":max(5,min(1440,int(raw.get("refreshMinutes") or existing.get("refreshMinutes") or 30))),
        "mediaSources":_normalize_sources(raw.get("mediaSources") if "mediaSources" in raw else existing.get("mediaSources")),
        "gameCenterMode":"schedule",
        "createdAt":float(existing.get("createdAt") or now),"updatedAt":now
    }
    if out["logoStrategy"] not in LOGO_STRATEGIES:out["logoStrategy"]="AUTO"
    out["effectiveLogoStrategy"]=_effective_logo_strategy(out)
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

def _participant_name(event,side):
    raw=(event or {}).get(f"{side}Team") or (event or {}).get(side) or ""
    if isinstance(raw,dict):return str(raw.get("name") or raw.get("displayName") or raw.get("teamName") or "").strip()
    return str(raw or "").strip()

def _placeholder_participant(name):
    text=str(name or "").strip()
    if not text:return True
    compact=re.sub(r"\s+"," ",text).strip()
    return bool(_PLACEHOLDER_PARTICIPANT_RE.match(compact) or re.search(r"\b(?:winner|loser)\s+(?:of\s+)?(?:match|game)\b|\b(?:tba|tbd)\b",compact,re.I))

def _event_needs_result_reconcile(event,today=None):
    date=str((event or {}).get("date") or "")[:10]
    today=str(today or _today())[:10]
    if date and date>today:return False
    away=_participant_name(event,"away");home=_participant_name(event,"home")
    status=str((event or {}).get("status") or "").upper()
    a_score=(event or {}).get("awayScore");h_score=(event or {}).get("homeScore")
    score_missing=a_score in (None,"") or h_score in (None,"")
    return _placeholder_participant(away) or _placeholder_participant(home) or (date and date<=today and score_missing and status not in {"POSTPONED","CANCELLED"})

def _catalog_row(comp):
    x={k:v for k,v in comp.items() if k!="events"}
    events=list(comp.get("events") or [])
    x["lifecycle"]=lifecycle(comp);x["mainRow"]=main_row(comp);x["eventsCount"]=len(events)
    x["placeholderEvents"]=sum(1 for ev in events if _event_needs_result_reconcile(ev))
    return x

def catalog():
    return [_catalog_row(x) for x in _load() if x.get("enabled",True)]

def competition_map():
    return {x["id"]:x for x in catalog()}

def _find(cid):
    cid=str(cid or "").upper()
    return next((x for x in _load() if str(x.get("id")).upper()==cid),None)

def _playlist_enrollment(server,comp):
    rows=[]
    try: rows=server._operator_media_playlists_load()
    except Exception:return []
    return [{"id":x.get("id"),"playlistId":x.get("playlistId"),"objective":x.get("objective"),"enabled":bool(x.get("enabled"))} for x in rows if str(x.get("league") or "").upper()==comp.get("id")]

def _crawl_enrollment(server,comp):
    history=False
    try: history=comp.get("id") in tuple(server.HISTORY_LEAGUES)
    except Exception:pass
    return {"historyLeague":history,"backgroundDiscovery":bool(comp.get("backgroundDiscovery",True)),"crawlEnabled":bool(comp.get("crawlEnabled",True)),"operatorPlaylists":_playlist_enrollment(server,comp),"worker":dict(_CRAWL_STATE)}

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

def _register_media_sources(server,comp,force_crawl=False):
    if not all(hasattr(server,n) for n in ("_operator_media_playlists_load","_operator_media_playlist_normalize","_operator_media_playlists_save","_operator_media_playlist_crawl_async")):return []
    rows=server._operator_media_playlists_load();objective={"green":"quick","purple":"extended","blue":"coverage"};changed=False;crawl_ids=[]
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
                idx=rows.index(existing)
                if rows[idx]!=norm:rows[idx]=norm;changed=True
            else:rows.append(norm);changed=True
            stats=(existing or {}).get("stats") or {}
            if force_crawl or not float((existing or {}).get("lastCrawlAt") or 0) or int(stats.get("associatedThisCrawl") or 0)<=0:crawl_ids.append(str(norm.get("id") or ""))
    # v4.6.4: persist the registration before a crawler thread can read it.
    if changed:
        try:server._operator_media_playlists_save(rows)
        except Exception:return []
    for playlist_id in dict.fromkeys(x for x in crawl_ids if x):
        try:server._operator_media_playlist_crawl_async(playlist_id,force=bool(force_crawl))
        except Exception:pass
    return list(dict.fromkeys(x for x in crawl_ids if x))

def save_competition(raw,events=None,server=None):
    rows=_load();cid=str((raw or {}).get("id") or "").upper()
    existing=next((x for x in rows if str(x.get("id")).upper()==cid),None)
    comp=normalize_definition(raw,existing)
    if events is None:events=raw.get("events") if isinstance(raw,dict) else None
    if events is None:events=(existing or {}).get("events") or []
    normalized=[normalize_event(comp,x,i) for i,x in enumerate(events or [])]
    if not normalized:
        raise ValueError("Cannot create a site-wide competition with zero schedule events. Discover or paste a schedule first.")
    expected=int(comp.get("expectedEventCount") or 0)
    if expected and len(normalized)<expected and not comp.get("allowIncompleteSchedule"):
        raise ValueError(f"Schedule is incomplete: {len(normalized)}/{expected} events. Complete the schedule before site-wide creation.")
    comp["events"]=normalized
    comp["persistedAt"]=time.time();comp["crawlEnabled"]=bool(comp.get("crawlEnabled",True));comp["backgroundDiscovery"]=bool(comp.get("backgroundDiscovery",True))
    comp["scheduleComplete"]=bool(not expected or len(normalized)>=expected)
    rows=[x for x in rows if str(x.get("id")).upper()!=comp["id"]];rows.append(comp);rows.sort(key=lambda x:(x.get("type")!="SPECIAL_EVENT",x.get("startDate") or "",x.get("name") or ""))
    _save(rows)
    if server:
        _register_with_server(server,comp)
        _register_media_sources(server,comp,force_crawl=True)
    persisted=_find(comp["id"])
    if not persisted:raise RuntimeError("Competition was not readable from the server store after save.")
    return _catalog_row(persisted)

def _extract_json(text):
    text=str(text or "").strip()
    try:return json.loads(text)
    except Exception:
        a=text.find("{");b=text.rfind("}")
        if a>=0 and b>a:return json.loads(text[a:b+1])
        raise ValueError("Schedule discovery did not return parseable JSON.")

def _schedule_schema():
    event_props={
        "eventId":{"type":"string"},"date":{"type":"string"},"scheduledAt":{"type":"string"},
        "away":{"type":"string"},"home":{"type":"string"},"awayScore":{"type":["number","string","null"]},
        "homeScore":{"type":["number","string","null"]},"status":{"type":"string"},"round":{"type":"string"},
        "stage":{"type":"string"},"venue":{"type":"string"},"broadcast":{"type":"string"},"sourceUrl":{"type":"string"}
    }
    return {"type":"object","properties":{"sourceUrls":{"type":"array","items":{"type":"string"}},"sourceLabel":{"type":"string"},"events":{"type":"array","items":{"type":"object","properties":event_props,"required":list(event_props),"additionalProperties":False}}},"required":["sourceUrls","sourceLabel","events"],"additionalProperties":False}

def _discovery_plan_schema():
    return {
        "type":"object",
        "properties":{
            "expectedEventCount":{"type":"integer","minimum":0},
            "sourceUrls":{"type":"array","items":{"type":"string"}},
            "sourceLabel":{"type":"string"},
            "notes":{"type":"string"}
        },
        "required":["expectedEventCount","sourceUrls","sourceLabel","notes"],
        "additionalProperties":False
    }

def _openai_json_request(server,model,prompt,schema,name,use_web=True,max_output_tokens=9000,timeout=150):
    payload={"model":model,"input":prompt,"max_output_tokens":max_output_tokens,
             "text":{"format":{"type":"json_schema","name":name,"strict":True,"schema":schema}}}
    if use_web:
        payload["tools"]=[{"type":"web_search"}]
        payload["tool_choice"]="auto"
        payload["include"]=["web_search_call.action.sources"]
    resp=server.openai_api_request("/responses",payload,timeout=timeout)
    if not isinstance(resp,dict):raise RuntimeError("OpenAI response was not an object")
    if resp.get("ok") is False:raise RuntimeError(str(resp.get("error") or resp.get("detail") or "OpenAI request failed"))
    text=server.openai_output_text(resp)
    if not text:raise RuntimeError("OpenAI returned no schedule output")
    return _extract_json(text)

def _openai_schedule_request(server,model,prompt,use_web=True):
    return _openai_json_request(server,model,prompt,_schedule_schema(),"sports_competition_schedule",use_web=use_web,max_output_tokens=9000)

def _official_page_text(url,limit=180000):
    url=str(url or "").strip()
    if not url:return ""
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 SportsBigBoard/4.6.6","Accept":"text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"})
    with urlopen(req,timeout=25) as r:
        raw=r.read(2_000_000)
        ctype=str(r.headers.get("Content-Type") or "")
    text=raw.decode("utf-8","replace")
    if "json" in ctype.lower():return text[:limit]
    text=re.sub(r"(?is)<script[^>]*>.*?</script>|<style[^>]*>.*?</style>"," ",text)
    text=re.sub(r"(?s)<[^>]+>"," ",text)
    text=html.unescape(re.sub(r"\s+"," ",text)).strip()
    return text[:limit]

def _date_windows(start,end):
    try:
        a=datetime.strptime(str(start)[:10],"%Y-%m-%d").date()
        b=datetime.strptime(str(end)[:10],"%Y-%m-%d").date()
    except Exception:
        return []
    if b<a:return []
    days=(b-a).days+1
    span=7 if days<=60 else (14 if days<=210 else 30)
    out=[];cur=a
    while cur<=b:
        stop=min(b,cur+timedelta(days=span-1))
        out.append((cur.isoformat(),stop.isoformat()))
        cur=stop+timedelta(days=1)
        if len(out)>=24:break
    return out

def _event_merge_key(raw):
    raw=raw or {}
    explicit=str(raw.get("eventId") or raw.get("matchId") or raw.get("gameId") or raw.get("id") or "").strip()
    if explicit:return "id:"+explicit
    def k(v):return re.sub(r"[^a-z0-9]+","",str(v or "").lower())
    return "|".join((str(raw.get("date") or "")[:10],k(raw.get("away") or raw.get("awayTeam")),k(raw.get("home") or raw.get("homeTeam")),str(raw.get("scheduledAt") or "")))

def _merge_discovered_events(rows):
    merged={}
    for raw in rows or []:
        if not isinstance(raw,dict):continue
        key=_event_merge_key(raw)
        if not key.strip("|"):continue
        prev=merged.get(key,{})
        obj=dict(prev)
        for k,v in raw.items():
            if v not in (None,"",[]):obj[k]=v
            elif k not in obj:obj[k]=v
        merged[key]=obj
    return list(merged.values())

def _discovery_plan(server,model,d,official):
    prompt=f"""Research the authoritative schedule source for this sports competition.
Competition: {d['name']}
Year/edition: {d['year']}
Sport: {d['sportId']}
Start: {d.get('startDate') or 'unknown'}
End: {d.get('endDate') or 'unknown'}
Operator-supplied official URL: {official or 'none'}

Do NOT return individual games. Find the official organizer schedule/results source, determine the expected total number of competition games/events if published, and return only the requested structured plan. Prefer the official organizer over secondary sites."""
    return _openai_json_request(server,model,prompt,_discovery_plan_schema(),"sports_competition_schedule_plan",use_web=True,max_output_tokens=1800,timeout=90)

def _window_prompt(d,window_start,window_end,source_urls,expected):
    return f"""Find every game/event for this competition whose event date is between {window_start} and {window_end}, inclusive.
Competition: {d['name']}
Year/edition: {d['year']}
Sport: {d['sportId']}
Full competition date range: {d.get('startDate') or 'unknown'} through {d.get('endDate') or 'unknown'}
Expected total competition events: {expected or 'unknown'}
Preferred authoritative sources: {', '.join(source_urls[:5]) if source_urls else 'official organizer source'}

Return ONLY games whose event date falls inside this window. Use official organizer/competition sources whenever possible. Do not invent participants, scores, dates, or results. For unresolved future bracket positions, preserve labels such as TBA, Winner Game 35, or Loser Match 12 rather than guessing. Include all games in this date window."""

def _window_official_page_prompt(d,window_start,window_end,page,source_url):
    return f"""Extract every competition game whose event date is between {window_start} and {window_end}, inclusive, from the supplied official page text.
Competition: {d['name']}
Official source URL: {source_url}
Do not invent any game. Ignore unrelated exhibitions or other competitions unless they are explicitly part of {d['name']}.
Return only the requested structured schedule.

--- OFFICIAL PAGE TEXT START ---
{page}
--- OFFICIAL PAGE TEXT END ---"""

def _missing_recovery_prompt(d,source_urls,expected,known):
    known_lines="\n".join(f"{x.get('date','')} | {x.get('away','')} vs {x.get('home','')} | {x.get('eventId','')}" for x in known[:220])
    return f"""The schedule import for {d['name']} is incomplete.
Expected total events: {expected}
Already collected: {len(known)}
Competition dates: {d.get('startDate')} through {d.get('endDate')}
Preferred sources: {', '.join(source_urls[:5]) if source_urls else 'official organizer source'}

Search for ONLY missing games that are not in the list below. Do not repeat known games and do not invent games.
--- KNOWN GAMES ---
{known_lines}
--- END KNOWN GAMES ---"""

def discover_schedule(server,draft):
    d=normalize_definition(draft,{})
    official=str(d.get("scheduleSourceUrl") or "").strip()
    model=os.environ.get("SBB_COMPETITION_BUILDER_MODEL") or str(getattr(server,"OPENAI_MODEL","gpt-5-mini"))
    errors=[];window_reports=[];sources=[];source_label="";expected=int(d.get("expectedEventCount") or 0)

    try:
        plan=_discovery_plan(server,model,d,official)
        for u in plan.get("sourceUrls") or []:
            if str(u).strip() and str(u).strip() not in sources:sources.append(str(u).strip())
        source_label=str(plan.get("sourceLabel") or "")
        if not expected:expected=max(0,int(plan.get("expectedEventCount") or 0))
    except Exception as exc:
        errors.append(f"plan: {type(exc).__name__}: {exc}")
    if official and official not in sources:sources.insert(0,official)

    page=""
    if official:
        try:
            page=_official_page_text(official)
            if len(page)<200:page=""
        except Exception as exc:
            errors.append(f"official page fetch: {type(exc).__name__}: {exc}")

    windows=_date_windows(d.get("startDate"),d.get("endDate"))
    if not windows:
        windows=[(d.get("startDate") or "competition start",d.get("endDate") or "competition end")]
    collected=[]

    for ws,we in windows:
        window_rows=[];mode="WEB_SEARCH";window_errors=[]
        try:
            data=_openai_json_request(server,model,_window_prompt(d,ws,we,sources,expected),_schedule_schema(),"sports_competition_schedule_window",use_web=True,max_output_tokens=9000,timeout=120)
            window_rows=data.get("events") or []
            for u in data.get("sourceUrls") or []:
                u=str(u).strip()
                if u and u not in sources:sources.append(u)
        except Exception as exc:
            window_errors.append(f"web: {type(exc).__name__}: {exc}")
        if not window_rows and page:
            try:
                data=_openai_json_request(server,model,_window_official_page_prompt(d,ws,we,page,official),_schedule_schema(),"sports_competition_schedule_page_window",use_web=False,max_output_tokens=9000,timeout=120)
                window_rows=data.get("events") or [];mode="OFFICIAL_PAGE"
            except Exception as exc:
                window_errors.append(f"page: {type(exc).__name__}: {exc}")
        if not window_rows:
            try:
                broad=_window_prompt(d,ws,we,sources,expected)+"\nIf the official source cannot be indexed, use reputable sports schedule/result sources to corroborate the exact games for this window."
                data=_openai_json_request(server,model,broad,_schedule_schema(),"sports_competition_schedule_broad_window",use_web=True,max_output_tokens=9000,timeout=120)
                window_rows=data.get("events") or [];mode="BROAD_WEB_RECOVERY"
            except Exception as exc:
                window_errors.append(f"broad: {type(exc).__name__}: {exc}")
        collected.extend(window_rows)
        window_reports.append({"start":ws,"end":we,"events":len(window_rows),"mode":mode if window_rows else "FAILED","errors":window_errors})
        errors.extend(f"{ws}..{we} {x}" for x in window_errors)

    merged=_merge_discovered_events(collected)
    if expected and 0<len(merged)<expected:
        try:
            data=_openai_json_request(server,model,_missing_recovery_prompt(d,sources,expected,merged),_schedule_schema(),"sports_competition_schedule_missing",use_web=True,max_output_tokens=9000,timeout=120)
            merged=_merge_discovered_events(merged+(data.get("events") or []))
            for u in data.get("sourceUrls") or []:
                u=str(u).strip()
                if u and u not in sources:sources.append(u)
        except Exception as exc:
            errors.append(f"missing recovery: {type(exc).__name__}: {exc}")

    if not merged:
        raise RuntimeError("Schedule discovery returned zero events after plan + date-window search + official-page fallback. Nothing was saved.")

    normalized=[normalize_event(d,x,i) for i,x in enumerate(merged)]
    found=len(normalized)
    complete=bool(found>0 and (not expected or found>=expected))
    ratio=(found/expected) if expected else 1.0
    mode="MULTI_WINDOW_RESEARCH" if len(windows)>1 else "BOUNDED_RESEARCH"
    return {
        "competition":_catalog_row({**d,"expectedEventCount":expected,"events":normalized}),
        "events":normalized,
        "sourceUrls":sources,
        "sourceLabel":source_label or mode,
        "discoveryMode":mode,
        "attemptErrors":errors[-20:],
        "expectedEventCount":expected,
        "discoveredEventCount":found,
        "complete":complete,
        "completenessRatio":ratio,
        "windowReports":window_reports
    }


def _result_reconcile_schema():
    props={
        "eventId":{"type":"string"},"date":{"type":"string"},"away":{"type":"string"},"home":{"type":"string"},
        "awayScore":{"type":["number","string","null"]},"homeScore":{"type":["number","string","null"]},
        "status":{"type":"string"},"round":{"type":"string"},"stage":{"type":"string"},
        "venue":{"type":"string"},"sourceUrl":{"type":"string"}
    }
    return {"type":"object","properties":{
        "sourceUrls":{"type":"array","items":{"type":"string"}},
        "results":{"type":"array","items":{"type":"object","properties":props,"required":list(props),"additionalProperties":False}}
    },"required":["sourceUrls","results"],"additionalProperties":False}

def _result_reconcile_prompt(comp,targets,source_urls):
    rows=[]
    for ev in targets:
        rows.append(
            f"eventId={ev.get('eventId')} | date={ev.get('date')} | scheduledAt={ev.get('scheduledAt','')} | "
            f"round={ev.get('round') or ev.get('stage') or ''} | venue={ev.get('venue','')} | "
            f"currently={_participant_name(ev,'away')} vs {_participant_name(ev,'home')}"
        )
    return f"""Resolve the ACTUAL played participants and final/current result for the listed games in {comp['name']}.
This is a results-reconciliation task for a schedule that still contains bracket placeholders such as Winner Match 95.
Preferred authoritative sources: {', '.join(source_urls[:5]) if source_urls else (comp.get('scheduleSourceUrl') or 'official organizer results')}

Rules:
- Search authoritative official competition/results sources first.
- Every returned result MUST copy the supplied eventId exactly. Never invent a replacement ID.
- Replace bracket placeholders with the teams/countries that actually played.
- For games already played, return the actual score and status FINAL (or the official completed status).
- Do not return hypothetical/potential matchups.
- Do not change the event date merely because a source renders it in another timezone.
- If one listed event cannot be verified, omit it rather than guessing.

EVENTS TO RECONCILE:
{chr(10).join(rows)}
"""

def _result_page_prompt(comp,targets,page,source_url):
    rows=[]
    for ev in targets:
        rows.append(
            f"eventId={ev.get('eventId')} | date={ev.get('date')} | time={ev.get('scheduledAt','')} | "
            f"round={ev.get('round') or ev.get('stage') or ''} | currently={_participant_name(ev,'away')} vs {_participant_name(ev,'home')}"
        )
    return f"""Using ONLY the official page text below, resolve the actual played participants/results for the listed {comp['name']} games.
Copy each supplied eventId exactly. Replace Winner/Loser/TBA placeholders with the teams that actually played. Preserve the listed event date. Omit anything the page does not support.

EVENTS:
{chr(10).join(rows)}

OFFICIAL SOURCE URL: {source_url}
--- OFFICIAL PAGE TEXT START ---
{page}
--- OFFICIAL PAGE TEXT END ---
"""

def _persist_event_reconciliation(server,comp,events):
    rows=_load();cid=str(comp.get("id") or "").upper()
    persisted=next((x for x in rows if str(x.get("id") or "").upper()==cid),None)
    if not persisted:return None
    persisted=dict(persisted);persisted["events"]=events;persisted["resultsReconciledAt"]=time.time();persisted["updatedAt"]=time.time()
    rows=[x for x in rows if str(x.get("id") or "").upper()!=cid]+[persisted]
    rows.sort(key=lambda x:(x.get("type")!="SPECIAL_EVENT",x.get("startDate") or "",x.get("name") or ""))
    _save(rows)
    _register_with_server(server,persisted)
    return _find(cid)

def reconcile_competition_results(server,comp,force=False):
    """Replace past bracket placeholders with actual realized participants/results while preserving canonical event IDs."""
    if not comp:return {"attempted":False,"updated":0,"targets":0,"remaining":0,"errors":["competition missing"]}
    cid=str(comp.get("id") or "").upper();now=time.time()
    if not force and now-float(_RESULT_RECONCILE_AT.get(cid) or 0)<6*3600:
        remaining=sum(1 for ev in comp.get("events") or [] if _event_needs_result_reconcile(ev))
        return {"attempted":False,"updated":0,"targets":remaining,"remaining":remaining,"errors":[]}
    _RESULT_RECONCILE_AT[cid]=now
    targets=[dict(ev) for ev in comp.get("events") or [] if _event_needs_result_reconcile(ev)]
    if not targets:return {"attempted":False,"updated":0,"targets":0,"remaining":0,"errors":[]}

    model=os.environ.get("SBB_COMPETITION_BUILDER_MODEL") or str(getattr(server,"OPENAI_MODEL","gpt-5-mini"))
    source_urls=[]
    for u in [comp.get("scheduleSourceUrl"),comp.get("scoreSourceUrl")]:
        u=str(u or "").strip()
        if u and u not in source_urls:source_urls.append(u)
    page="";official=source_urls[0] if source_urls else ""
    if official:
        try:page=_official_page_text(official)
        except Exception:page=""

    resolved={};errors=[];sources=list(source_urls)
    for i in range(0,len(targets),12):
        batch=targets[i:i+12];data=None
        try:
            data=_openai_json_request(server,model,_result_reconcile_prompt(comp,batch,sources),_result_reconcile_schema(),"sports_competition_actual_results",use_web=True,max_output_tokens=6500,timeout=120)
        except Exception as exc:
            errors.append(f"web batch {i//12+1}: {type(exc).__name__}: {exc}")
        if (not data or not data.get("results")) and page:
            try:
                data=_openai_json_request(server,model,_result_page_prompt(comp,batch,page,official),_result_reconcile_schema(),"sports_competition_actual_results_page",use_web=False,max_output_tokens=6500,timeout=120)
            except Exception as exc:
                errors.append(f"page batch {i//12+1}: {type(exc).__name__}: {exc}")
        if not data:continue
        for u in data.get("sourceUrls") or []:
            u=str(u or "").strip()
            if u and u not in sources:sources.append(u)
        allowed={str(x.get("eventId") or "") for x in batch}
        for row in data.get("results") or []:
            eid=str(row.get("eventId") or "")
            if eid in allowed and not _placeholder_participant(row.get("away")) and not _placeholder_participant(row.get("home")):
                resolved[eid]=row

    if not resolved:
        return {"attempted":True,"updated":0,"targets":len(targets),"remaining":len(targets),"errors":errors[-12:],"sourceUrls":sources}

    updated=[];changed=0
    for idx,old in enumerate(comp.get("events") or []):
        eid=str(old.get("eventId") or "")
        row=resolved.get(eid)
        if not row:
            updated.append(old);continue
        merged={**old,**row,"awayTeam":row.get("away"),"homeTeam":row.get("home"),"id":eid,"eventId":eid,"matchId":eid,"competitionId":cid,"competitionName":comp.get("name")}
        # Keep the canonical identity stable so already-associated media remains attached.
        normalized=normalize_event(comp,merged,idx)
        normalized["id"]=eid;normalized["eventId"]=eid;normalized["matchId"]=eid
        updated.append(normalized);changed+=1

    persisted=_persist_event_reconciliation(server,comp,updated)
    remaining=sum(1 for ev in (persisted or {}).get("events",updated) if _event_needs_result_reconcile(ev))
    return {"attempted":True,"updated":changed,"targets":len(targets),"remaining":remaining,"errors":errors[-12:],"sourceUrls":sources}

def _league_source_media(server,cid,limit=5000):
    repo=getattr(server,"HISTORY_REPOSITORY",None)
    if repo is None or not hasattr(repo,"_read_connect"):return []
    out=[]
    try:
        conn=repo._read_connect()
        try:
            rows=conn.execute("SELECT asset_json FROM history_source_media WHERE asset_json LIKE ? OR asset_json LIKE ? ORDER BY updated_at DESC LIMIT ?",(f'%"league":"{cid}"%',f'%"competitionId":"{cid}"%',int(limit))).fetchall()
            for row in rows:
                try:
                    item=json.loads(row[0] or "{}")
                    if isinstance(item,dict):out.append(item)
                except Exception:pass
        finally:conn.close()
    except Exception:pass
    return out

def _repair_event_media(server,comp,event,force=False):
    cid=comp["id"];eid=str(event.get("eventId") or "");key=f"{cid}:{eid}";now=time.time()
    if not force and now-float(_ASSOCIATION_REPAIR_AT.get(key) or 0)<120:return {"attempted":False,"assigned":0,"candidates":0}
    _ASSOCIATION_REPAIR_AT[key]=now
    try:existing=server.HISTORY_REPOSITORY.event_media(event.get("date"),cid,eid,include_failed=False)
    except Exception:existing=[]
    if existing and not force:return {"attempted":False,"assigned":len(existing),"candidates":0}
    candidates=_league_source_media(server,cid);assigned=0
    for item in candidates:
        try:
            scoped,evidence=server._history_media_match_evidence(dict(item),event)
            if scoped.get("mediaScope")!="GAME" or str(evidence.get("associationState") or "")!="ASSIGNED":continue
            decorated=dict(item);decorated.update({"league":cid,"competitionId":cid,"competitionName":comp["name"],"eventId":eid,"matchId":eid,"scoreEventId":eid,"canonicalEventId":eid,"date":event.get("date"),"gameDate":event.get("date"),"__sbbDate":event.get("date"),"away":event.get("awayTeam") or event.get("away"),"home":event.get("homeTeam") or event.get("home")})
            assigned+=int(server.HISTORY_REPOSITORY.put_event_media(event.get("date"),cid,eid,[decorated]) or 0)
        except Exception:continue
    return {"attempted":True,"assigned":assigned,"candidates":len(candidates)}

def _competition_health(server,comp,date=""):
    events=[_decorate_event_artwork(comp,x) for x in (comp.get("events") or []) if not date or str(x.get("date") or "")[:10]==date]
    assigned=playable=green=purple=blue=0;details=[]
    for ev in events:
        try:media=server.HISTORY_REPOSITORY.event_media(ev.get("date"),comp["id"],ev.get("eventId"),include_failed=False)
        except Exception:media=[]
        assigned+=len(media);p=[x for x in media if x.get("verifiedPlayable") and (x.get("youtubeId") or x.get("mediaUrl"))];playable+=len(p)
        for x in p:
            tier=str(x.get("recapTier") or "").lower()
            if tier=="green":green+=1
            elif tier=="extended":purple+=1
            elif tier=="blue":blue+=1
        details.append({"eventId":ev.get("eventId"),"date":ev.get("date"),"away":(ev.get("awayTeam") or {}).get("name"),"home":(ev.get("homeTeam") or {}).get("name"),"assigned":len(media),"playable":len(p)})
    return {"competitionId":comp["id"],"date":date,"events":len(events),"assignedMedia":assigned,"playableMedia":playable,"green":green,"purple":purple,"blue":blue,"sourceCandidates":len(_league_source_media(server,comp["id"])),"eventDetails":details}

def generic_game_center(comp,event):
    event=_decorate_event_artwork(comp,event)
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
        return _send(server,handler,{"ok":True,"version":2,"revision":_store_revision(),"today":_today(),"competitions":rows,"specialEvents":[x for x in rows if x.get("type")=="SPECIAL_EVENT"],"mainRow":[x for x in rows if x.get("mainRow")],"crawl":dict(_CRAWL_STATE)})
    if parsed.path=="/api/competition-builder/schedule":
        qs=parse_qs(parsed.query);cid=str((qs.get("id") or [""])[-1]).upper();date=str((qs.get("date") or [""])[-1])[:10]
        comp=_find(cid)
        if not comp:return _send(server,handler,{"ok":False,"error":"COMPETITION_NOT_FOUND"},404)
        events=[_decorate_event_artwork(comp,x) for x in comp.get("events") or [] if not date or x.get("date")==date]
        return _send(server,handler,{"ok":True,"competition":_catalog_row(comp),"date":date,"events":events})
    if parsed.path=="/api/competition-builder/media":
        qs=parse_qs(parsed.query);cid=str((qs.get("id") or [""])[-1]).upper();date=str((qs.get("date") or [""])[-1])[:10]
        comp=_find(cid)
        if not comp:return _send(server,handler,{"ok":False,"error":"COMPETITION_NOT_FOUND"},404)
        media=[];repairs=[]
        for ev0 in comp.get("events") or []:
            if date and ev0.get("date")!=date:continue
            ev=_decorate_event_artwork(comp,ev0)
            try:rows=server.HISTORY_REPOSITORY.event_media(ev.get("date"),cid,ev.get("eventId"),include_failed=False)
            except TypeError:rows=server.HISTORY_REPOSITORY.event_media(ev.get("date"),cid,ev.get("eventId"))
            except Exception:rows=[]
            if not rows:
                repairs.append(_repair_event_media(server,comp,ev))
                try:rows=server.HISTORY_REPOSITORY.event_media(ev.get("date"),cid,ev.get("eventId"),include_failed=False)
                except Exception:rows=[]
            for item in rows or []:
                away_team=ev.get("awayTeam") or {};home_team=ev.get("homeTeam") or {}
                away_name=str(away_team.get("displayName") or away_team.get("name") or _participant_name(ev,"away"))
                home_name=str(home_team.get("displayName") or home_team.get("name") or _participant_name(ev,"home"))
                x=dict(item);x.update({"league":cid,"competitionId":cid,"competitionName":comp["name"],"eventId":ev.get("eventId"),"matchId":ev.get("eventId"),"scoreEventId":ev.get("eventId"),"canonicalEventId":ev.get("eventId"),"date":ev.get("date"),"gameDate":ev.get("date"),"__sbbDate":ev.get("date"),"sport":comp["sportId"],"sportId":comp["sportId"],"away":away_name,"home":home_name,"awayName":away_name,"homeName":home_name,"awayTeam":away_team,"homeTeam":home_team,"awayLogo":away_team.get("logo") or away_team.get("logoUrl") or "","homeLogo":home_team.get("logo") or home_team.get("logoUrl") or ""});media.append(x)
        return _send(server,handler,{"ok":True,"competition":_catalog_row(comp),"date":date,"media":media,"repairs":repairs,"health":_competition_health(server,comp,date)})
    if parsed.path=="/api/competition-builder/health":
        qs=parse_qs(parsed.query);cid=str((qs.get("id") or [""])[-1]).upper();date=str((qs.get("date") or [""])[-1])[:10];repair=str((qs.get("repair") or ["0"])[-1]).lower() in ("1","true","yes")
        comp=_find(cid)
        if not comp:return _send(server,handler,{"ok":False,"error":"COMPETITION_NOT_FOUND"},404)
        report=[]
        if repair:
            _register_media_sources(server,comp,force_crawl=True)
            for ev in comp.get("events") or []:
                if date and ev.get("date")!=date:continue
                report.append(_repair_event_media(server,comp,_decorate_event_artwork(comp,ev),force=True))
        return _send(server,handler,{"ok":True,"competition":_catalog_row(comp),"health":_competition_health(server,comp,date),"repair":report,"placeholderEvents":sum(1 for ev in comp.get("events") or [] if _event_needs_result_reconcile(ev)),"crawlEnrollment":_crawl_enrollment(server,comp)},200)
    if parsed.path=="/api/competition-builder/definition":
        qs=parse_qs(parsed.query);comp=_find((qs.get("id") or [""])[-1])
        return _send(server,handler,{"ok":bool(comp),"persisted":bool(comp),"revision":_store_revision(),"competition":comp,"crawlEnrollment":_crawl_enrollment(server,comp) if comp else {}},200 if comp else 404)
    if parsed.path=="/api/competition-builder/crawl":
        qs=parse_qs(parsed.query);comp=_find((qs.get("id") or [""])[-1])
        return _send(server,handler,{"ok":True,"revision":_store_revision(),"worker":dict(_CRAWL_STATE),"crawlEnrollment":_crawl_enrollment(server,comp) if comp else {}},200)
    m=re.fullmatch(r"/api/events/([^/]+)/([^/]+)/game-center",parsed.path)
    if m:
        cid=unquote(m.group(1)).upper();eid=unquote(m.group(2));comp=_find(cid)
        if not comp:return False
        event=next((x for x in comp.get("events") or [] if str(x.get("eventId"))==eid),None)
        if not event:return _send(server,handler,{"ok":False,"error":"CUSTOM_EVENT_NOT_FOUND"},404)
        event=_decorate_event_artwork(comp,event)
        return _send(server,handler,{"ok":True,"data":generic_game_center(comp,event),"resolvedEventId":eid,"cache":"CUSTOM-COMPETITION"},200)
    return False
def _remove_operator_playlists(server,cid):
    removed=0
    try:
        rows=server._operator_media_playlists_load()
        keep=[x for x in rows if str(x.get("league") or "").upper()!=cid]
        removed=len(rows)-len(keep)
        if removed:server._operator_media_playlists_save(keep)
    except Exception:pass
    return removed

def _purge_history_competition(server,cid):
    report={"events":0,"dayRows":0,"collections":0,"assignmentReviews":0}
    repo=getattr(server,"HISTORY_REPOSITORY",None)
    if repo is None or not hasattr(repo,"_connect"):return report
    try:
        lock=getattr(repo,"_lock",threading.RLock())
        with lock:
            conn=repo._connect()
            try:
                keys=[str(r[0]) for r in conn.execute("SELECT canonical_event_key FROM history_catalog_event WHERE league=?",(cid,)).fetchall()]
                report["events"]=len(keys)
                if keys:
                    q=",".join("?" for _ in keys)
                    for table in ("history_media_segment","history_discovery_attempt","history_source_enrichment","history_event_media"):
                        try:conn.execute(f"DELETE FROM {table} WHERE canonical_event_key IN ({q})",keys)
                        except Exception:pass
                try:
                    collections=[str(r[0]) for r in conn.execute("SELECT collection_key FROM history_collection WHERE league=?",(cid,)).fetchall()]
                    report["collections"]=len(collections)
                    if collections:
                        q=",".join("?" for _ in collections)
                        try:conn.execute(f"DELETE FROM history_collection_media WHERE collection_key IN ({q})",collections)
                        except Exception:pass
                    conn.execute("DELETE FROM history_collection WHERE league=?",(cid,))
                except Exception:pass
                try:
                    cur=conn.execute("DELETE FROM history_assignment_review WHERE league=?",(cid,));report["assignmentReviews"]=max(0,int(cur.rowcount or 0))
                except Exception:pass
                try:
                    cur=conn.execute("DELETE FROM history_day WHERE league=?",(cid,));report["dayRows"]=max(0,int(cur.rowcount or 0))
                except Exception:pass
                conn.execute("DELETE FROM history_catalog_event WHERE league=?",(cid,))
                conn.commit()
            finally:
                conn.close()
    except Exception as exc:
        report["error"]=f"{type(exc).__name__}: {exc}"
    return report

def delete_competition(server,cid,purge=True):
    cid=str(cid or "").upper().strip()
    existing=_find(cid)
    if not existing:raise ValueError("Competition does not exist.")
    rows=[x for x in _load() if str(x.get("id")).upper()!=cid]
    _save(rows)
    playlist_count=_remove_operator_playlists(server,cid)
    history_report=_purge_history_competition(server,cid) if purge else {}
    try:
        import sbb.competition_registry as registry
        registry.COMPETITIONS.pop(cid,None)
    except Exception:pass
    try:
        server.HISTORY_LEAGUES=tuple(x for x in tuple(server.HISTORY_LEAGUES) if str(x).upper()!=cid)
    except Exception:pass
    return {"id":cid,"name":existing.get("name"),"purged":bool(purge),"operatorPlaylists":playlist_count,"history":history_report,"revision":_store_revision()}


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
            persisted=_find(saved.get("id"))
            if not persisted:raise RuntimeError("Server persistence verification failed after save")
            return _send(server,handler,{"ok":True,"persisted":True,"revision":_store_revision(),"competition":saved,"crawlEnrollment":_crawl_enrollment(server,persisted),"catalog":catalog()},200)
        if action=="delete":
            result=delete_competition(server,body.get("id"),purge=body.get("purge",True) is not False)
            return _send(server,handler,{"ok":True,"deleted":result,"revision":_store_revision(),"catalog":catalog()},200)
        if action=="refresh":
            comp=_find(body.get("id"))
            if not comp:return _send(server,handler,{"ok":False,"error":"COMPETITION_NOT_FOUND"},404)
            preview=discover_schedule(server,comp)
            saved=save_competition(comp,preview.get("events") or [],server)
            return _send(server,handler,{"ok":True,"competition":saved,"preview":preview},200)
        if action=="reconcile_results":
            comp=_find(body.get("id"))
            if not comp:return _send(server,handler,{"ok":False,"error":"COMPETITION_NOT_FOUND"},404)
            report=reconcile_competition_results(server,comp,force=True)
            persisted=_find(comp.get("id"))
            return _send(server,handler,{"ok":True,"competition":_catalog_row(persisted or comp),"resultsReconciliation":report,"revision":_store_revision()},200)
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
_CUSTOM_CRAWL_INTERVAL=max(120,int(os.environ.get("SBB_CUSTOM_COMPETITION_CRAWL_INTERVAL","300") or 300))

def _run_generic_gap_once(server):
    now=time.time()
    if now-float(_GENERIC_GAP_STATE.get("lastAt") or 0)<_CUSTOM_CRAWL_INTERVAL:return
    try:
        if hasattr(server,"_history_server_idle") and not server._history_server_idle():return
    except Exception:return
    for comp in _load():
        if not comp.get("enabled",True) or not comp.get("backgroundDiscovery",True) or not comp.get("crawlEnabled",True):continue
        for ev in reversed(comp.get("events") or []):
            if str(ev.get("status") or "").upper() not in {"FINAL","COMPLETED","FINISHED"}:continue
            try:existing=server.HISTORY_REPOSITORY.event_media(ev.get("date"),comp["id"],ev.get("eventId"),include_failed=False)
            except Exception:existing=[]
            if any(x.get("verifiedPlayable") and (x.get("youtubeId") or x.get("mediaUrl")) for x in (existing or [])):continue
            _GENERIC_GAP_STATE.update(lastAt=now,competition=comp["id"],eventId=ev.get("eventId"),found=0,error="")
            _CRAWL_STATE.update(worker="RUNNING",lastAt=now,lastCompetition=comp["id"],lastEventId=ev.get("eventId"),attempts=int(_CRAWL_STATE.get("attempts") or 0)+1,lastError="")
            try:
                found=_generic_youtube_gap_search(server,comp,ev);_GENERIC_GAP_STATE["found"]=found;_CRAWL_STATE["found"]=int(_CRAWL_STATE.get("found") or 0)+int(found or 0);_CRAWL_STATE["worker"]="WAITING"
            except Exception as exc:
                msg=f"{type(exc).__name__}: {exc}";_GENERIC_GAP_STATE["error"]=msg;_CRAWL_STATE.update(worker="WAITING",errors=int(_CRAWL_STATE.get("errors") or 0)+1,lastError=msg)
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
        # Realized-results reconciliation is separate from schedule discovery:
        # past bracket placeholders are periodically replaced with the teams that
        # actually played while preserving each canonical event ID/media binding.
        try:
            for comp in _load():
                if not comp.get("enabled",True) or not comp.get("backgroundDiscovery",True):continue
                if not any(_event_needs_result_reconcile(ev) for ev in comp.get("events") or []):continue
                report=reconcile_competition_results(server,comp,force=False)
                if report.get("attempted"):break
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
    for comp in _load():
        _register_with_server(server,comp)
        try:_register_media_sources(server,comp,force_crawl=False)
        except Exception:pass
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
        _CRAWL_STATE["worker"]="WAITING"
        _REFRESH_THREAD=threading.Thread(target=_refresh_active,args=(server,),name="sbb-custom-competition-crawl",daemon=True);_REFRESH_THREAD.start()

def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:return
        _INSTALLED=True
    threading.Thread(target=_install_into_server,name="sbb-competition-builder-install",daemon=True).start()

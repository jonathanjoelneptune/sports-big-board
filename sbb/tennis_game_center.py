"""Sports Big Board v5.1.18 — sport-aware tennis Game Center for custom events.

Competition Builder remains the schedule/media authority for user-created tennis
competitions.  This adapter only replaces the generic schedule/results Game Center
shell for sportId=tennis with a bounded ESPN tennis scoreboard match lookup.

The adapter is intentionally tournament-agnostic: the 2026 US Open is the first
consumer, but any future Competition Builder tennis event can use the same path.
"""
from __future__ import annotations

import copy
import difflib
import json
import re
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import competition_builder as base

VERSION = "5.1.18-tennis-game-center-3"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_ORIGINAL_GAME_CENTER = getattr(base, "generic_game_center", None)
_CACHE_LOCK = threading.RLock()
_CACHE = {}
_CACHE_FINAL_TTL = 6 * 60 * 60.0
_CACHE_LIVE_TTL = 45.0
_BOARD_CACHE={}
_BOARD_TTL=120.0


def _clean(value):
    return str(value or "").strip()


def _norm(value):
    value = _clean(value).lower().replace("&", " and ")
    value = re.sub(r"^#?\d+\s+", "", value)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\b(?:atp|wta|seed|seeded)\b", " ", value)
    return re.sub(r"[^a-z0-9à-ÿ]+", " ", value, flags=re.I).strip()


def _last_name(value):
    parts=_norm(value).split()
    return parts[-1] if parts else ""


def _person_similarity(a,b):
    a=_norm(a);b=_norm(b)
    if not a or not b:return 0.0
    if a==b:return 1.0
    if _last_name(a) and _last_name(a)==_last_name(b):
        return max(.88,difflib.SequenceMatcher(None,a,b).ratio())
    aset=set(a.split());bset=set(b.split())
    overlap=len(aset & bset)/max(1,len(aset | bset))
    return max(overlap,difflib.SequenceMatcher(None,a,b).ratio()*.82)


def _team_name(team):
    if isinstance(team,dict):
        return _clean(team.get("displayName") or team.get("name") or team.get("shortName") or team.get("abbreviation"))
    return _clean(team)


def _target_names(shell):
    board=(shell or {}).get("scoreboard") or {}
    return _team_name((board.get("away") or {}).get("team")), _team_name((board.get("home") or {}).get("team"))


def _fetch_json(url,timeout=8):
    req=Request(url,headers={"Accept":"application/json","User-Agent":"SportsBigBoard/5.1.18 tennis-game-center"})
    with urlopen(req,timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _scoreboard_url(tour,date):
    params={}
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}",_clean(date)):
        params["dates"]=_clean(date).replace("-","")
    query=("?"+urlencode(params)) if params else ""
    return f"https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard{query}"


def _scoreboard(tour,date):
    key=(_clean(tour).lower(),_clean(date)[:10]);now=time.time()
    with _CACHE_LOCK:
        row=_BOARD_CACHE.get(key)
        if row and now-float(row.get("at") or 0)<_BOARD_TTL:return copy.deepcopy(row.get("data") or {})
    data=_fetch_json(_scoreboard_url(tour,date),timeout=5)
    with _CACHE_LOCK:
        _BOARD_CACHE[key]={"at":time.time(),"data":copy.deepcopy(data)}
        if len(_BOARD_CACHE)>24:
            oldest=min(_BOARD_CACHE,key=lambda k:float(_BOARD_CACHE[k].get("at") or 0));_BOARD_CACHE.pop(oldest,None)
    return data


def _flatten_scoreboard(payload,tour):
    out=[]
    for tournament in (payload or {}).get("events") or []:
        if not isinstance(tournament,dict):continue
        tournament_name=_clean(tournament.get("name") or tournament.get("shortName"))
        tournament_id=_clean(tournament.get("id"))
        groupings=tournament.get("groupings") or []
        # Some ESPN tennis responses may expose competitions directly.
        if tournament.get("competitions"):
            groupings=[{"grouping":{},"competitions":tournament.get("competitions") or []},*groupings]
        for grouping in groupings:
            if not isinstance(grouping,dict):continue
            meta=grouping.get("grouping") or {}
            draw=_clean(meta.get("displayName") or meta.get("text") or meta.get("slug"))
            for match in grouping.get("competitions") or []:
                if not isinstance(match,dict):continue
                out.append({"tour":tour,"tournament":tournament_name,"tournamentId":tournament_id,"draw":draw,"match":match})
    return out


def _competitor_name(comp):
    athlete=(comp or {}).get("athlete") or {}
    return _clean(athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName") or (comp or {}).get("displayName"))


def _match_names(match):
    comps=[x for x in ((match or {}).get("competitors") or []) if isinstance(x,dict)]
    away=next((x for x in comps if _clean(x.get("homeAway")).lower()=="away"),None)
    home=next((x for x in comps if _clean(x.get("homeAway")).lower()=="home"),None)
    if not away and comps:away=comps[0]
    if not home and len(comps)>1:home=comps[1]
    return _competitor_name(away or {}),_competitor_name(home or {})


def _tournament_similarity(custom_name,espn_name):
    a=_norm(custom_name);b=_norm(espn_name)
    # Ignore a leading season year in a wizard-created competition name.
    a=re.sub(r"^20\d{2}\s+","",a).strip()
    if not a or not b:return .5
    if a==b or a in b or b in a:return 1.0
    return difflib.SequenceMatcher(None,a,b).ratio()


def _date_distance(target,raw):
    try:
        td=datetime.strptime(_clean(target)[:10],"%Y-%m-%d").date()
        rd=datetime.fromisoformat(_clean(raw).replace("Z","+00:00")).date()
        return abs((rd-td).days)
    except Exception:return 99


def _resolve_match(comp,shell,date,event=None):
    away,home=_target_names(shell)
    if not away or not home:return None
    custom_name=_clean((comp or {}).get("name"))
    explicit_ids=set()
    for key in ("espnMatchId","espnCompetitionId","providerEventId","sourceEventId","espnEventId"):
        value=_clean((event or {}).get(key))
        if value:explicit_ids.add(value)
    try:
        center=datetime.strptime(_clean(date)[:10],"%Y-%m-%d").date()
        days=[center.isoformat(),(center-timedelta(days=1)).isoformat(),(center+timedelta(days=1)).isoformat()]
    except Exception:
        days=[_clean(date)[:10]]

    def candidates_for_day(day):
        candidates=[]
        for tour in ("atp","wta"):
            try:payload=_scoreboard(tour,day)
            except Exception:continue
            for row in _flatten_scoreboard(payload,tour):
                match=row["match"];mid=_clean(match.get("id"))
                if mid and mid in explicit_ids and _date_distance(date,match.get("date") or match.get("startDate"))<=1:
                    return [(9999.0,row)]
                p1,p2=_match_names(match)
                direct=_person_similarity(away,p1)+_person_similarity(home,p2)
                reverse=_person_similarity(away,p2)+_person_similarity(home,p1)
                pair=max(direct,reverse)
                if pair < 1.50:continue
                day_distance=_date_distance(date,match.get("date") or match.get("startDate"))
                if day_distance>1:continue
                tournament_score=_tournament_similarity(custom_name,row.get("tournament"))
                score=pair*100 + tournament_score*20 - day_distance*4
                candidates.append((score,row))
        return candidates

    # Exact schedule date is the fast path. Neighbor-day rescue is only attempted
    # when the exact-date boards contain no viable participant pair.
    candidates=candidates_for_day(days[0])
    if not candidates:
        for day in days[1:]:
            candidates.extend(candidates_for_day(day))
            if candidates:break
    if not candidates:return None
    candidates.sort(key=lambda x:x[0],reverse=True)
    if len(candidates)>1 and candidates[0][0]-candidates[1][0] < 5:
        a1,a2=_match_names(candidates[0][1]["match"]),_match_names(candidates[1][1]["match"])
        if {_norm(x) for x in a1} != {_norm(x) for x in a2}:return None
    return candidates[0][1]


def _score_value(value):
    try:return int(float(value))
    except Exception:return value if value not in (None,"") else ""


def _competitor_map(match):
    comps=[x for x in ((match or {}).get("competitors") or []) if isinstance(x,dict)]
    away=next((x for x in comps if _clean(x.get("homeAway")).lower()=="away"),None)
    home=next((x for x in comps if _clean(x.get("homeAway")).lower()=="home"),None)
    if not away and comps:away=comps[0]
    if not home and len(comps)>1:home=comps[1]
    return away or {},home or {}


def _flag(comp):
    athlete=(comp or {}).get("athlete") or {}
    flag=athlete.get("flag") or {}
    return _clean(flag.get("href") if isinstance(flag,dict) else flag)


def _country(comp):
    athlete=(comp or {}).get("athlete") or {}
    flag=athlete.get("flag") or {}
    return _clean((flag.get("alt") if isinstance(flag,dict) else "") or athlete.get("country") or (comp or {}).get("country"))


def _rank(comp):
    rank=(comp or {}).get("curatedRank") or {}
    return (rank.get("current") if isinstance(rank,dict) else rank) or ""


def _sets(match,away,home):
    al=list((away or {}).get("linescores") or []);hl=list((home or {}).get("linescores") or [])
    count=max(len(al),len(hl));out=[]
    for i in range(count):
        a=al[i] if i<len(al) and isinstance(al[i],dict) else {}
        h=hl[i] if i<len(hl) and isinstance(hl[i],dict) else {}
        out.append({
            "num":i+1,"label":f"SET {i+1}","away":_score_value(a.get("value")),"home":_score_value(h.get("value")),
            "awayTiebreak":_score_value(a.get("tiebreak")),"homeTiebreak":_score_value(h.get("tiebreak")),
            "awayWinner":bool(a.get("winner")),"homeWinner":bool(h.get("winner")),
        })
    return out


def _sets_won(sets,side):
    other="home" if side=="away" else "away"
    total=0
    for row in sets:
        if row.get(f"{side}Winner"):total+=1;continue
        try:
            if float(row.get(side))>float(row.get(other)):total+=1
        except Exception:pass
    return total


def _games_won(sets,side):
    total=0
    for row in sets:
        try:total+=int(float(row.get(side)))
        except Exception:pass
    return total


def _tiebreaks_won(sets,side):
    other="home" if side=="away" else "away";total=0
    for row in sets:
        a=row.get(f"{side}Tiebreak");b=row.get(f"{other}Tiebreak")
        if a in (None,"") or b in (None,""):continue
        try:
            if float(a)>float(b):total+=1
        except Exception:pass
    return total


def _stat_pairs(away,home):
    def raw_stats(comp):
        out={}
        for row in (comp or {}).get("statistics") or []:
            if not isinstance(row,dict):continue
            label=_clean(row.get("displayName") or row.get("name") or row.get("label"))
            value=row.get("displayValue") if row.get("displayValue") not in (None,"") else row.get("value")
            if label and value not in (None,""):out[_norm(label)]=(label,value)
        return out
    a=raw_stats(away);h=raw_stats(home);rows=[]
    for key in sorted(set(a)&set(h)):
        label=a[key][0] or h[key][0]
        rows.append({"label":label,"away":a[key][1],"home":h[key][1]})
    return rows


def _player_section(side,comp,sets):
    name=_competitor_name(comp) or side.title()
    country=_country(comp);rank=_rank(comp)
    set_score="  ".join(str(row.get(side,'')) + (f"({row.get(side+'Tiebreak')})" if row.get(side+'Tiebreak') not in (None,"") else "") for row in sets)
    return {
        "title":f"{name} — Match",
        "teamSide":side,
        "columns":["PLAYER","COUNTRY","SEED/RANK","SET SCORES"],
        "rows":[[name,country or "—",rank or "—",set_score or "—"]],
    }


def _normalize(row,comp,shell):
    match=row["match"];away,home=_competitor_map(match)
    # Keep Game Center left/right participant order identical to the selected
    # Competition Builder score row even when ESPN uses the opposite homeAway
    # ordering for tennis.
    target_away,target_home=_target_names(shell)
    direct=_person_similarity(target_away,_competitor_name(away))+_person_similarity(target_home,_competitor_name(home))
    reverse=_person_similarity(target_away,_competitor_name(home))+_person_similarity(target_home,_competitor_name(away))
    if reverse>direct:away,home=home,away
    sets=_sets(match,away,home)
    status=((match.get("status") or {}).get("type") or {})
    status_text=_clean(status.get("shortDetail") or status.get("detail") or status.get("description") or status.get("state"))
    completed=bool(status.get("completed")) or _clean(status.get("state")).lower()=="post"
    away_sets=_sets_won(sets,"away");home_sets=_sets_won(sets,"home")
    venue=match.get("venue") or {};court=_clean(venue.get("court"));venue_name=_clean(venue.get("fullName"))
    round_name=_clean((match.get("round") or {}).get("displayName"));draw=_clean(row.get("draw") or (match.get("type") or {}).get("text"))
    note=" • ".join(_clean(x.get("text")) for x in (match.get("notes") or []) if isinstance(x,dict) and _clean(x.get("text")))
    broadcast=_clean(match.get("broadcast"))
    if not broadcast:
        names=[]
        for b in match.get("broadcasts") or []:
            if isinstance(b,dict):names.extend(_clean(x) for x in b.get("names") or [] if _clean(x))
        broadcast=", ".join(dict.fromkeys(names))
    team_stats=[
        {"label":"Sets Won","away":away_sets,"home":home_sets},
        {"label":"Games Won","away":_games_won(sets,"away"),"home":_games_won(sets,"home")},
    ]
    if any(row.get("awayTiebreak") not in (None,"") or row.get("homeTiebreak") not in (None,"") for row in sets):
        team_stats.append({"label":"Tiebreaks Won","away":_tiebreaks_won(sets,"away"),"home":_tiebreaks_won(sets,"home")})
    ar,hr=_rank(away),_rank(home)
    if ar or hr:team_stats.append({"label":"Seed / Rank","away":ar or "—","home":hr or "—"})
    team_stats.extend(_stat_pairs(away,home))

    timeline=[];cum_away=0;cum_home=0
    for s in sets:
        tie_a=f" ({s['awayTiebreak']})" if s.get("awayTiebreak") not in (None,"") else ""
        tie_h=f" ({s['homeTiebreak']})" if s.get("homeTiebreak") not in (None,"") else ""
        if s.get("awayWinner"):cum_away+=1
        elif s.get("homeWinner"):cum_home+=1
        else:
            try:
                if float(s.get("away"))>float(s.get("home")):cum_away+=1
                elif float(s.get("home"))>float(s.get("away")):cum_home+=1
            except Exception:pass
        timeline.append({
            "id":f"set-{s['num']}","index":len(timeline),"period":s["num"],"periodLabel":s["label"],
            "description":f"{_competitor_name(away)} {s.get('away','')}{tie_a} – {s.get('home','')}{tie_h} {_competitor_name(home)}",
            "scoreAway":cum_away,"scoreHome":cum_home,"isScoring":True,
        })

    def team(c):
        athlete=c.get("athlete") or {}
        rank=_rank(c); full=_competitor_name(c); compact=_tennis_compact_name(full,rank)
        return {"id":_clean(c.get("id")),"name":full,"displayName":full,"shortName":compact or _clean(athlete.get("shortName")),"abbreviation":compact or _last_name(full)[:3].upper(),"logo":_flag(c),"country":_country(c),"rank":rank}

    event_id=_clean((shell or {}).get("eventId") or ((shell or {}).get("event") or {}).get("eventId"))
    match_id=_clean(match.get("id"))
    periods=[{"num":s["num"],"label":f"S{s['num']}","away":s.get("away",""),"home":s.get("home","")} for s in sets]
    data={
        "schemaVersion":"sbb.gamecenter.v1","competitionId":_clean((comp or {}).get("id")).upper(),"eventId":event_id,
        "sportId":"tennis","source":"ESPN Tennis Scoreboard","provider":"espn-tennis","providerEventIds":{"competitionBuilder":event_id,"espnMatch":match_id,"espnTournament":row.get("tournamentId")},
        "event":{"competitionId":_clean((comp or {}).get("id")).upper(),"eventId":event_id,"sportId":"tennis","status":status_text,"date":match.get("date"),"competitionName":_clean((comp or {}).get("name"))},
        "scoreboard":{"status":status_text,"period":(match.get("status") or {}).get("period"),"venue":" • ".join(x for x in (row.get("tournament"),draw,round_name,court or venue_name) if x),"away":{"team":team(away),"score":away_sets},"home":{"team":team(home),"score":home_sets},"periods":periods,"lineScoreType":"sets"},
        "periodLabels":[p["label"] for p in periods],"teamStats":team_stats,"playerStatSections":[_player_section("away",away,sets),_player_section("home",home,sets)],
        "timeline":timeline,"scoringPlays":copy.deepcopy(timeline),"winProbability":[],
        "tennis":{"tournament":row.get("tournament"),"tournamentId":row.get("tournamentId"),"matchId":match_id,"tour":row.get("tour","" ).upper(),"draw":draw,"round":round_name,"court":court,"venue":venue_name,"broadcast":broadcast,"bestOf":((match.get("format") or {}).get("regulation") or {}).get("periods"),"note":note,"sets":sets},
        "coverage":{"scoreboard":True,"status":True,"periods":bool(sets),"teamStats":bool(team_stats),"players":True,"plays":bool(timeline),"scoringPlays":bool(timeline),"winProbability":False,"complete":bool(sets and team_stats)},
        "quality":{"level":"rich" if sets and team_stats else "partial"},"partial":not bool(sets and team_stats),"live":not completed and _clean(status.get("state")).lower()=="in","updatedAt":datetime.utcnow().isoformat()+"Z",
    }
    return data


def _cache_key(comp,shell,date):
    return (_clean((comp or {}).get("id")).upper(),_clean((shell or {}).get("eventId") or ((shell or {}).get("event") or {}).get("eventId")),_clean(date)[:10])


def _cache_get(key):
    now=time.time()
    with _CACHE_LOCK:
        row=_CACHE.get(key)
        if row and now<float(row.get("expiresAt") or 0):return copy.deepcopy(row.get("data"))
        if row:_CACHE.pop(key,None)
    return None


def _cache_put(key,data):
    complete=bool(((data or {}).get("coverage") or {}).get("complete")) and not bool((data or {}).get("live"))
    ttl=_CACHE_FINAL_TTL if complete else _CACHE_LIVE_TTL
    with _CACHE_LOCK:
        _CACHE[key]={"data":copy.deepcopy(data),"expiresAt":time.time()+ttl}
    return data


def peek_tennis_game_center(competition_id,event_id):
    """Read an already-built tennis Game Center without launching provider work."""
    comp=_clean(competition_id).upper();eid=_clean(event_id);now=time.time();best=None
    with _CACHE_LOCK:
        for key,row in list(_CACHE.items()):
            if now>=float(row.get("expiresAt") or 0):
                _CACHE.pop(key,None);continue
            if key[0]==comp and key[1]==eid:
                best=row.get("data");break
    return copy.deepcopy(best) if best else None


def _tennis_game_center(comp,event):
    if not callable(_ORIGINAL_GAME_CENTER):raise RuntimeError("Competition Builder Game Center is unavailable")
    shell=_ORIGINAL_GAME_CENTER(comp,event)
    date=_clean((event or {}).get("date") or (event or {}).get("gameDate") or (event or {}).get("scheduledAt") or ((shell or {}).get("event") or {}).get("date"))[:10]
    key=_cache_key(comp,shell,date);cached=_cache_get(key)
    if cached:return cached
    resolved=_resolve_match(comp,shell,date,event)
    if not resolved:
        out=copy.deepcopy(shell or {})
        out["tennisGameCenter"]={"provider":"espn-tennis","state":"MATCH_NOT_RESOLVED","date":date}
        return out
    return _cache_put(key,_normalize(resolved,comp,shell))


def generic_game_center(comp,event):
    if _clean((comp or {}).get("sportId")).lower()!="tennis":
        return _ORIGINAL_GAME_CENTER(comp,event)
    return _tennis_game_center(comp,event)


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:return False
        if not callable(_ORIGINAL_GAME_CENTER):return False
        base.generic_game_center=generic_game_center
        _INSTALLED=True
        return True


__all__=["VERSION","install","peek_tennis_game_center","generic_game_center","_tennis_game_center","_normalize","_resolve_match"]

# ---------------------------------------------------------------------------
# v5.1.17 live-route + tennis presentation patch
# ---------------------------------------------------------------------------
import sys as _sys
from urllib.parse import parse_qs as _parse_qs, urlparse as _urlparse, unquote as _unquote

VERSION = "5.1.18-tennis-game-center-3"
_PRESENTATION_INSTALLED = False
_SERVER_ROUTE_INSTALLED = False
_ROUTE_LOCK = threading.RLock()
_ROUTE_RESULTS = {}
_ROUTE_JOBS = {}
_ROUTE_FINAL_TTL = 6 * 60 * 60.0
_ROUTE_LIVE_TTL = 30.0
_ROUTE_ERROR_TTL = 25.0

_ORIGINAL_EFFECTIVE_LOGO_STRATEGY = getattr(base, "_effective_logo_strategy", None)
_ORIGINAL_DECORATE_TEAM_ARTWORK = getattr(base, "_decorate_team_artwork", None)
_ORIGINAL_NORMALIZE_EVENT = getattr(base, "normalize_event", None)

# Common IOC/ATP/WTA three-letter country codes. Competition Builder schedules
# often carry these rather than ISO-2 values; flagcdn uses ISO-2.
_TENNIS_COUNTRY_3_TO_2 = {
    "ARG":"ar","AUS":"au","AUT":"at","BEL":"be","BIH":"ba","BOL":"bo","BRA":"br","BUL":"bg",
    "CAN":"ca","CHI":"cl","CHN":"cn","COL":"co","CRO":"hr","CYP":"cy","CZE":"cz","DEN":"dk",
    "ECU":"ec","EGY":"eg","ESP":"es","EST":"ee","FIN":"fi","FRA":"fr","GBR":"gb","GEO":"ge",
    "GER":"de","GRE":"gr","HUN":"hu","INA":"id","IND":"in","IRL":"ie","ISR":"il","ITA":"it",
    "JPN":"jp","KAZ":"kz","KOR":"kr","LAT":"lv","LTU":"lt","LUX":"lu","MAR":"ma","MDA":"md",
    "MEX":"mx","MNE":"me","NED":"nl","NOR":"no","NZL":"nz","PAR":"py","PER":"pe","POL":"pl",
    "POR":"pt","ROU":"ro","RSA":"za","SRB":"rs","SLO":"si","SVK":"sk","SUI":"ch","SWE":"se",
    "TPE":"tw","TUN":"tn","TUR":"tr","UAE":"ae","UKR":"ua","URU":"uy","USA":"us","UZB":"uz",
    "VEN":"ve","VIE":"vn"
}


def _tennis_last_name(value):
    text=_clean(value)
    text=re.sub(r"^#?\d+\s+", "", text).strip()
    if not text:return ""
    # Doubles/team labels keep one compact surname per player.
    if re.search(r"\s[/&+]\s|/|&",text):
        parts=re.split(r"\s*(?:/|&|\+)\s*",text)
        names=[_tennis_last_name(x) for x in parts if _clean(x)]
        return "/".join(x for x in names if x)[:22]
    if "," in text:
        return text.split(",",1)[0].strip()[:18]
    parts=text.split()
    if len(parts)==1:return parts[0][:18]
    particles={"de","del","della","di","da","dos","van","von","der","le","la"}
    if len(parts)>=2 and parts[-2].lower() in particles:
        return (parts[-2]+" "+parts[-1])[:18]
    return parts[-1][:18]


def _tennis_compact_name(value, rank=""):
    text=_clean(value)
    text=re.sub(r"^#?\d+\s+", "", text).strip()
    if not text:return ""
    # Singles: First initial + readable surname. Doubles: compact each player.
    if re.search(r"\s[/&+]\s|/|&",text):
        parts=re.split(r"\s*(?:/|&|\+)\s*",text)
        label="/".join(_tennis_compact_name(x,"") for x in parts if _clean(x))
    else:
        parts=text.split()
        if len(parts)<=1:label=text
        else:
            surname=_tennis_last_name(text)
            first=parts[0][:1].upper()+"." if parts[0] else ""
            label=f"{first} {surname}".strip()
    rank_text=_clean(rank)
    if rank_text and rank_text not in {"0","999","—"}:label=f"#{rank_text} {label}"
    return label[:24]


def _country_hint(team):
    if not isinstance(team,dict):return ""
    for key in ("countryCode","country","nation","nationality","group","region"):
        value=_clean(team.get(key))
        if value:return value
    aliases=team.get("aliases") or []
    if isinstance(aliases,str):aliases=[aliases]
    country_lookup=getattr(base,"_country_code_for_name",None)
    if callable(country_lookup):
        for value in aliases:
            if _clean(country_lookup(value)):return _clean(value)
    return ""


def _tennis_effective_logo_strategy(comp):
    if _clean((comp or {}).get("sportId")).lower()=="tennis":
        raw=_clean((comp or {}).get("logoStrategy") or "AUTO").upper()
        if raw in {"","AUTO","TEAM_LOGOS"}:return "COUNTRY_FLAGS"
    if callable(_ORIGINAL_EFFECTIVE_LOGO_STRATEGY):return _ORIGINAL_EFFECTIVE_LOGO_STRATEGY(comp)
    return "AUTO"


def _tennis_decorate_team_artwork(comp,team):
    obj=dict(team or {})
    if _clean((comp or {}).get("sportId")).lower()=="tennis":
        full=_clean(obj.get("displayName") or obj.get("name"))
        short=_tennis_compact_name(full,obj.get("rank") or obj.get("seed") or obj.get("ranking"))
        if full:
            obj["name"]=_clean(obj.get("name") or full)
            obj["displayName"]=full
        if short:
            obj["shortName"]=short
            # The ribbon gives abbreviation visual priority. A readable surname is
            # more useful for tennis than three generated initials (STE/YAS).
            obj["abbreviation"]=short
            aliases=obj.get("aliases") or []
            if isinstance(aliases,str):aliases=[aliases]
            obj["aliases"]=list(dict.fromkeys([*aliases,full,short]))
        hint=_country_hint(obj)
        lookup=getattr(base,"_country_code_for_name",None)
        code=""
        if callable(lookup):
            code=_clean(lookup(hint))
        if not code:
            raw=_clean(obj.get("countryCode"))
            code=_TENNIS_COUNTRY_3_TO_2.get(raw.upper(),"")
            if not code and re.fullmatch(r"[a-z]{2}(?:-[a-z]{3})?",raw.lower()):code=raw.lower()
        if code:
            obj["countryCode"]=code.upper()
            obj.setdefault("country",hint)
    if callable(_ORIGINAL_DECORATE_TEAM_ARTWORK):
        return _ORIGINAL_DECORATE_TEAM_ARTWORK(comp,obj)
    return obj


def _tennis_normalize_event(comp,raw,idx=0):
    if not callable(_ORIGINAL_NORMALIZE_EVENT):return raw
    event=_ORIGINAL_NORMALIZE_EVENT(comp,raw,idx)
    if _clean((comp or {}).get("sportId")).lower()!="tennis":return event
    away=_tennis_decorate_team_artwork(comp,event.get("awayTeam") or event.get("away") or {})
    home=_tennis_decorate_team_artwork(comp,event.get("homeTeam") or event.get("home") or {})
    event.update({"away":away,"home":home,"awayTeam":away,"homeTeam":home,"participants":[away,home],"logoStrategy":"COUNTRY_FLAGS","gameCenterProviderHint":"tennis"})
    return event


def _install_tennis_presentation():
    global _PRESENTATION_INSTALLED
    if _PRESENTATION_INSTALLED:return False
    if callable(_ORIGINAL_EFFECTIVE_LOGO_STRATEGY):base._effective_logo_strategy=_tennis_effective_logo_strategy
    if callable(_ORIGINAL_DECORATE_TEAM_ARTWORK):base._decorate_team_artwork=_tennis_decorate_team_artwork
    if callable(_ORIGINAL_NORMALIZE_EVENT):base.normalize_event=_tennis_normalize_event
    _PRESENTATION_INSTALLED=True
    return True


def _find_comp(cid):
    finder=getattr(base,"_find",None)
    if callable(finder):
        try:return finder(cid)
        except Exception:return None
    service=getattr(base,"SERVICE",None)
    if service is not None and hasattr(service,"get"):
        try:return service.get(cid)
        except Exception:return None
    return None


def _find_event(comp,eid):
    for event in (comp or {}).get("events") or []:
        if not isinstance(event,dict):continue
        ids={_clean(event.get(k)) for k in ("eventId","matchId","gameId","id","providerEventId","espnEventId") if event.get(k) not in (None,"")}
        if _clean(eid) in ids:return event
    return None


def _route_key(cid,eid):return (_clean(cid).upper(),_clean(eid))


def _result_get(key):
    now=time.time()
    with _ROUTE_LOCK:
        row=_ROUTE_RESULTS.get(key)
        if row and now<float(row.get("expiresAt") or 0):return copy.deepcopy(row)
        if row:_ROUTE_RESULTS.pop(key,None)
    return None


def _result_put(key,data=None,error=""):
    data=copy.deepcopy(data) if isinstance(data,dict) else None
    status=_clean((((data or {}).get("scoreboard") or {}).get("status") or ((data or {}).get("event") or {}).get("status"))).lower()
    final=any(x in status for x in ("final","complete","finished","post")) and not bool((data or {}).get("live"))
    ttl=_ROUTE_ERROR_TTL if error else (_ROUTE_FINAL_TTL if final else _ROUTE_LIVE_TTL)
    row={"data":data,"error":_clean(error),"at":time.time(),"expiresAt":time.time()+ttl}
    with _ROUTE_LOCK:_ROUTE_RESULTS[key]=row
    return row


def _start_route_job(comp,event,request_eid=""):
    cid=_clean((comp or {}).get("id")).upper();eid=_clean(request_eid or (event or {}).get("eventId") or (event or {}).get("id"));key=_route_key(cid,eid)
    with _ROUTE_LOCK:
        job=_ROUTE_JOBS.get(key)
        if job and job.get("pending"):return False
        _ROUTE_JOBS[key]={"pending":True,"startedAt":time.time(),"error":""}
    def run():
        try:
            event_view=event
            decorate=getattr(base,"_decorate_event_artwork",None)
            if callable(decorate):event_view=decorate(comp,event)
            data=_tennis_game_center(comp,event_view)
            if isinstance(data,dict):
                data.setdefault("gameCenterArchitecture","TENNIS_SHARED_CUSTOM_EVENT")
                data.setdefault("competitionId",cid)
            _result_put(key,data=data)
            error=""
        except Exception as exc:
            error=f"{type(exc).__name__}: {exc}"
            _result_put(key,error=error)
        with _ROUTE_LOCK:_ROUTE_JOBS[key]={"pending":False,"completedAt":time.time(),"error":error}
    threading.Thread(target=run,daemon=True,name=f"sbb-tennis-gc-{cid[-8:]}-{eid[-8:]}").start()
    return True


def _serve_tennis_game_center(server,handler,parsed):
    match=re.fullmatch(r"/api/events/([^/]+)/([^/]+)/game-center",parsed.path,re.I)
    if not match:return False
    cid=_unquote(match.group(1)).upper();eid=_unquote(match.group(2));comp=_find_comp(cid)
    if not comp or _clean(comp.get("sportId")).lower()!="tennis":return False
    event=_find_event(comp,eid)
    if not event:
        return server.send_json(handler,{"ok":False,"error":"CUSTOM_TENNIS_EVENT_NOT_FOUND","competition":cid,"eventId":eid},404)
    qs=_parse_qs(parsed.query)
    force=_clean((qs.get("refresh") or qs.get("force") or [""])[-1]).lower() in {"1","true","yes","on"}
    async_mode=_clean((qs.get("async") or ["1"])[-1]).lower() not in {"0","false","no","off"}
    key=_route_key(cid,eid)
    if force:
        with _ROUTE_LOCK:_ROUTE_RESULTS.pop(key,None)
    hit=_result_get(key)
    if hit and not hit.get("error"):
        return server.send_json(handler,{"ok":True,"data":hit.get("data"),"cache":"TENNIS_DIRECT_HIT","pending":False,"resolvedEventId":eid,"route":"CUSTOM_TENNIS_DIRECT"},200,{"X-SBB-GameCenter-Cache":"TENNIS_DIRECT_HIT"})
    if hit and hit.get("error") and not force:
        return server.send_json(handler,{"ok":False,"error":"TENNIS_GAME_CENTER_PROVIDER_ERROR","message":hit.get("error"),"competition":cid,"eventId":eid},502)
    if not async_mode:
        try:
            event_view=event
            decorate=getattr(base,"_decorate_event_artwork",None)
            if callable(decorate):event_view=decorate(comp,event)
            data=_tennis_game_center(comp,event_view)
            _result_put(key,data=data)
            return server.send_json(handler,{"ok":True,"data":data,"cache":"TENNIS_DIRECT_REFRESH","pending":False,"resolvedEventId":eid,"route":"CUSTOM_TENNIS_DIRECT"},200)
        except Exception as exc:
            return server.send_json(handler,{"ok":False,"error":"TENNIS_GAME_CENTER_ERROR","message":f"{type(exc).__name__}: {exc}"},502)
    with _ROUTE_LOCK:job=dict(_ROUTE_JOBS.get(key) or {})
    if force or not job or not job.get("pending"):
        _start_route_job(comp,event,eid)
    return server.send_json(handler,{"ok":True,"pending":True,"cache":"PENDING","competition":cid,"eventId":eid,"resolvedEventId":eid,"retryAfterMs":450,"route":"CUSTOM_TENNIS_DIRECT"},202,{"X-SBB-GameCenter-Cache":"PENDING","Retry-After":"1"})


def _patch_server_v5117(server):
    global _SERVER_ROUTE_INSTALLED
    if getattr(server,"__sbbTennisGameCenterV5117",False):return True
    if not hasattr(server,"Handler") or not hasattr(server,"send_json"):return False
    if not getattr(server.Handler,"__sbbCompetitionBuilderInstalled",False):return False
    Handler=server.Handler
    old_get=Handler.do_GET
    def do_GET(self):
        parsed=_urlparse(self.path)
        handled=_serve_tennis_game_center(server,self,parsed)
        if handled is not False:return handled
        return old_get(self)
    Handler.do_GET=do_GET
    Handler.__sbbTennisGameCenterRouteV5117=True
    server.__sbbTennisGameCenterV5117=True
    _SERVER_ROUTE_INSTALLED=True
    try:
        server.SBB_BACKEND_WIRING.setdefault("gameCenter",{})["tennis"]="custom competition sportId=tennis -> direct async ESPN ATP/WTA tennis adapter"
        server.MILESTONE_CONSOLE.record("game-center","PASS","v5.1.18 custom tennis Game Center direct route installed",{})
    except Exception:pass
    return True


def _route_worker_v5117():
    for _ in range(600):
        server=_sys.modules.get("__main__")
        if server is not None and _patch_server_v5117(server):return
        time.sleep(.2)


# Redefine install so v5.1.17 owns both the Competition Builder sport adapter and
# the live server route. This fixes the v5.1.16 issue where generic server dispatch
# could answer 501 before Competition Builder's wrapped generic_game_center ran.
def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:return False
        if not callable(_ORIGINAL_GAME_CENTER):return False
        base.generic_game_center=generic_game_center
        _install_tennis_presentation()
        _INSTALLED=True
    threading.Thread(target=_route_worker_v5117,daemon=True,name="sbb-tennis-game-center-v5117").start()
    return True


__all__=["VERSION","install","peek_tennis_game_center","generic_game_center","_tennis_game_center","_normalize","_resolve_match"]

# ---------------------------------------------------------------------------
# v5.1.18 persistent tournament-day cache + presentation feed
# ---------------------------------------------------------------------------
from pathlib import Path as _Path

_PERSIST_LOCK=threading.RLock()
_PERSIST_PATH=_Path(getattr(base,"_STATE_DIR",_Path.home()/".sports-big-board"))/"tennis-game-center-v5118.json"
_PERSIST_FINAL_TTL=30*24*60*60.0
_PERSIST_LIVE_TTL=120.0
_DATE_WARM_LOCK=threading.RLock()
_DATE_WARMING=set()


def _persistent_load():
    try:
        raw=json.loads(_PERSIST_PATH.read_text(encoding="utf-8")) if _PERSIST_PATH.exists() else {}
        return raw if isinstance(raw,dict) else {}
    except Exception:return {}


def _persistent_save(rows):
    try:
        _PERSIST_PATH.parent.mkdir(parents=True,exist_ok=True)
        tmp=_PERSIST_PATH.with_suffix('.tmp')
        tmp.write_text(json.dumps(rows,separators=(",",":"),ensure_ascii=False),encoding="utf-8")
        tmp.replace(_PERSIST_PATH)
    except Exception:pass


def _persist_key(key):return "|".join(str(x or "") for x in key[:2])


def _persistent_get(key):
    now=time.time();k=_persist_key(key)
    with _PERSIST_LOCK:
        rows=_persistent_load();row=rows.get(k)
        if not isinstance(row,dict):return None
        if now>=float(row.get("expiresAt") or 0):
            rows.pop(k,None);_persistent_save(rows);return None
        return copy.deepcopy(row)


def _persistent_put(key,row):
    if not isinstance(row,dict) or row.get("error") or not isinstance(row.get("data"),dict):return
    data=row["data"];status=_clean(((data.get("scoreboard") or {}).get("status") or (data.get("event") or {}).get("status"))).lower()
    final=any(x in status for x in ("final","complete","finished","post")) and not bool(data.get("live"))
    ttl=_PERSIST_FINAL_TTL if final else _PERSIST_LIVE_TTL
    saved={"data":copy.deepcopy(data),"error":"","at":time.time(),"expiresAt":time.time()+ttl,"final":final,"version":VERSION}
    with _PERSIST_LOCK:
        rows=_persistent_load();rows[_persist_key(key)]=saved
        if len(rows)>1200:
            order=sorted(rows,key=lambda k:float((rows[k] or {}).get("at") or 0),reverse=True)
            rows={k:rows[k] for k in order[:1000]}
        _persistent_save(rows)


# Override route cache functions: memory first, then durable cache.
def _result_get(key):
    now=time.time()
    with _ROUTE_LOCK:
        row=_ROUTE_RESULTS.get(key)
        if row and now<float(row.get("expiresAt") or 0):return copy.deepcopy(row)
        if row:_ROUTE_RESULTS.pop(key,None)
    disk=_persistent_get(key)
    if disk:
        with _ROUTE_LOCK:_ROUTE_RESULTS[key]=copy.deepcopy(disk)
        return disk
    return None


def _result_put(key,data=None,error=""):
    data=copy.deepcopy(data) if isinstance(data,dict) else None
    status=_clean((((data or {}).get("scoreboard") or {}).get("status") or ((data or {}).get("event") or {}).get("status"))).lower()
    final=any(x in status for x in ("final","complete","finished","post")) and not bool((data or {}).get("live"))
    ttl=_ROUTE_ERROR_TTL if error else (_PERSIST_FINAL_TTL if final else _PERSIST_LIVE_TTL)
    row={"data":data,"error":_clean(error),"at":time.time(),"expiresAt":time.time()+ttl}
    with _ROUTE_LOCK:_ROUTE_RESULTS[key]=row
    if not error and data:_persistent_put(key,row)
    return row


def peek_tennis_game_center(competition_id,event_id):
    key=_route_key(competition_id,event_id);hit=_result_get(key)
    if hit and hit.get("data"):return copy.deepcopy(hit["data"])
    comp=_clean(competition_id).upper();eid=_clean(event_id);now=time.time()
    with _CACHE_LOCK:
        for ckey,row in list(_CACHE.items()):
            if now>=float(row.get("expiresAt") or 0):_CACHE.pop(ckey,None);continue
            if ckey[0]==comp and ckey[1]==eid:return copy.deepcopy(row.get("data"))
    return None


def _warm_competition_date(comp,date,exclude_eid=""):
    cid=_clean((comp or {}).get("id")).upper();date=_clean(date)[:10];warm_key=(cid,date)
    if not cid or not date:return False
    with _DATE_WARM_LOCK:
        if warm_key in _DATE_WARMING:return False
        _DATE_WARMING.add(warm_key)
    def run():
        try:
            # Fetch at most two provider boards once; every event resolver then hits
            # the in-process board cache rather than the network.
            for tour in ("atp","wta"):
                try:_scoreboard(tour,date)
                except Exception:pass
            events=[x for x in (comp or {}).get("events") or [] if _clean(x.get("date") or x.get("gameDate") or x.get("scheduledAt"))[:10]==date][:96]
            for event in events:
                eid=_clean(event.get("eventId") or event.get("id"));key=_route_key(cid,eid)
                if not eid or eid==exclude_eid or _result_get(key):continue
                try:
                    view=event;decorate=getattr(base,"_decorate_event_artwork",None)
                    if callable(decorate):view=decorate(comp,event)
                    data=_tennis_game_center(comp,view)
                    if isinstance(data,dict) and ((data.get("tennis") or {}).get("matchId")):
                        data.setdefault("gameCenterArchitecture","TENNIS_SHARED_CUSTOM_EVENT")
                        _result_put(key,data=data)
                except Exception:continue
        finally:
            with _DATE_WARM_LOCK:_DATE_WARMING.discard(warm_key)
    threading.Thread(target=run,daemon=True,name=f"sbb-tennis-date-warm-{cid[-8:]}-{date}").start();return True


def _start_route_job(comp,event,request_eid=""):
    cid=_clean((comp or {}).get("id")).upper();eid=_clean(request_eid or (event or {}).get("eventId") or (event or {}).get("id"));key=_route_key(cid,eid)
    with _ROUTE_LOCK:
        job=_ROUTE_JOBS.get(key)
        if job and job.get("pending"):return False
        _ROUTE_JOBS[key]={"pending":True,"startedAt":time.time(),"error":""}
    def run():
        error=""
        try:
            view=event;decorate=getattr(base,"_decorate_event_artwork",None)
            if callable(decorate):view=decorate(comp,event)
            data=_tennis_game_center(comp,view)
            if isinstance(data,dict):data.setdefault("gameCenterArchitecture","TENNIS_SHARED_CUSTOM_EVENT");data.setdefault("competitionId",cid)
            _result_put(key,data=data)
            date=_clean((event or {}).get("date") or (event or {}).get("gameDate") or (event or {}).get("scheduledAt"))[:10]
            if date:_warm_competition_date(comp,date,exclude_eid=eid)
        except Exception as exc:
            error=f"{type(exc).__name__}: {exc}";_result_put(key,error=error)
        with _ROUTE_LOCK:_ROUTE_JOBS[key]={"pending":False,"completedAt":time.time(),"error":error}
    threading.Thread(target=run,daemon=True,name=f"sbb-tennis-gc-{cid[-8:]}-{eid[-8:]}").start();return True


def _presentation_event(comp,event):
    away=event.get("awayTeam") or event.get("away") or {};home=event.get("homeTeam") or event.get("home") or {}
    eid=_clean(event.get("eventId") or event.get("id"));hit=_result_get(_route_key(comp.get("id"),eid));gc=(hit or {}).get("data") or {}
    board=gc.get("scoreboard") or {};ga=(board.get("away") or {}).get("team") or {};gh=(board.get("home") or {}).get("team") or {}
    def person(schedule,resolved):
        full=_clean(resolved.get("displayName") or resolved.get("name") or schedule.get("displayName") or schedule.get("name"))
        rank=_clean(resolved.get("rank") or schedule.get("rank") or schedule.get("seed"))
        return {"name":full,"displayName":full,"shortName":_tennis_compact_name(full,rank),"abbreviation":_tennis_compact_name(full,rank),
                "rank":rank,"country":_clean(resolved.get("country") or schedule.get("country")),"countryCode":_clean(schedule.get("countryCode")),
                "logo":_clean(resolved.get("logo") or resolved.get("logoUrl") or schedule.get("logo") or schedule.get("logoUrl"))}
    tennis=gc.get("tennis") or {};round_name=_clean(tennis.get("round") or event.get("round") or event.get("stage"))
    return {"eventId":eid,"date":_clean(event.get("date") or event.get("gameDate"))[:10],"awayTeam":person(away,ga),"homeTeam":person(home,gh),
            "round":round_name,"draw":_clean(tennis.get("draw") or event.get("draw") or event.get("group")),"court":_clean(tennis.get("court") or event.get("venue")),
            "gameCenterCached":bool(gc),"gameCenterComplete":bool((gc.get("coverage") or {}).get("complete"))}


def _serve_tennis_presentation(server,handler,parsed):
    if parsed.path!="/api/tennis/presentation":return False
    qs=_parse_qs(parsed.query);cid=_clean((qs.get("competition") or qs.get("id") or [""])[-1]).upper();date=_clean((qs.get("date") or [""])[-1])[:10]
    comp=_find_comp(cid)
    if not comp or _clean(comp.get("sportId")).lower()!="tennis":return server.send_json(handler,{"ok":False,"error":"TENNIS_COMPETITION_NOT_FOUND"},404)
    events=[x for x in comp.get("events") or [] if not date or _clean(x.get("date") or x.get("gameDate") or x.get("scheduledAt"))[:10]==date]
    if date:_warm_competition_date(comp,date)
    rows=[_presentation_event(comp,x) for x in events]
    return server.send_json(handler,{"ok":True,"version":VERSION,"competitionId":cid,"date":date,"rows":rows,"warming":bool((cid,date) in _DATE_WARMING)},200)


_old_serve_tennis_game_center_v5118=_serve_tennis_game_center
def _serve_tennis_game_center(server,handler,parsed):
    presented=_serve_tennis_presentation(server,handler,parsed)
    if presented is not False:return presented
    return _old_serve_tennis_game_center_v5118(server,handler,parsed)


def _active_tennis_prewarm_worker():
    # Delayed startup work only. It never blocks server launch or score-ribbon first paint.
    time.sleep(30)
    server=_sys.modules.get("__main__")
    for _ in range(12):
        try:
            idle=getattr(server,"_history_server_idle",None)
            if not callable(idle) or idle():break
        except Exception:break
        time.sleep(5)
    today=datetime.utcnow().date()
    for comp in list(getattr(base,"_load",lambda:[])() or []):
        if _clean(comp.get("sportId")).lower()!="tennis" or comp.get("enabled",True) is False:continue
        dates=sorted({_clean(x.get("date") or x.get("gameDate") or x.get("scheduledAt"))[:10] for x in comp.get("events") or [] if _clean(x.get("date") or x.get("gameDate") or x.get("scheduledAt"))})
        for d in dates:
            try:dd=datetime.strptime(d,"%Y-%m-%d").date()
            except Exception:continue
            if abs((dd-today).days)<=1:_warm_competition_date(comp,d)

# Install delayed date warm exactly once when this module is imported by v5.1.18.
threading.Thread(target=_active_tennis_prewarm_worker,daemon=True,name="sbb-tennis-active-prewarm-v5118").start()

"""Sports Big Board v5.1.16 — sport-aware tennis Game Center for custom events.

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

VERSION = "5.1.16-tennis-game-center-1"
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
    req=Request(url,headers={"Accept":"application/json","User-Agent":"SportsBigBoard/5.1.16 tennis-game-center"})
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
        return {"id":_clean(c.get("id")),"name":_competitor_name(c),"displayName":_competitor_name(c),"shortName":_clean(athlete.get("shortName")),"abbreviation":_last_name(_competitor_name(c))[:3].upper(),"logo":_flag(c),"country":_country(c),"rank":_rank(c)}

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

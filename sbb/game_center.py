"""Normalized Game Center contracts and MLB Stats adapter."""
from datetime import datetime, timezone
import copy
import re


def _person_name(row):
    return str((row or {}).get("person",{}).get("fullName") or (row or {}).get("person",{}).get("name") or "")

def _safe(v):
    return "" if v is None else v

def _nonempty(v):
    return v not in (None,"",[],{})

def _team_label(team):
    team=team or {}
    return str(team.get("abbreviation") or team.get("abbr") or team.get("shortName") or team.get("name") or team.get("displayName") or "").strip()

def _numeric(v):
    try:
        if v in (None,""): return None
        return float(v)
    except Exception:
        return None

def game_center_coverage(data):
    """Return a sport-aware completeness contract for one normalized Game Center.

    A score/team shell is useful to render immediately, but it is not considered a
    completed Game Center. Finished events keep enriching until the categories that
    exist for that sport have been collected from one or more providers.
    """
    data=data or {}; comp=str(data.get("competitionId") or ((data.get("event") or {}).get("competitionId")) or "").upper()
    event=data.get("event") or {}; board=data.get("scoreboard") or {}
    away=((board.get("away") or {}).get("team") or event.get("awayTeam") or {})
    home=((board.get("home") or {}).get("team") or event.get("homeTeam") or {})
    identity=bool(_team_label(away) and _team_label(home))
    away_score=_numeric((board.get("away") or {}).get("score")); home_score=_numeric((board.get("home") or {}).get("score"))
    score=away_score is not None and home_score is not None
    score_total=(away_score or 0)+(home_score or 0) if score else 0
    team_stats=[r for r in (data.get("teamStats") or []) if isinstance(r,dict) and str(r.get("label") or "").strip() and (_nonempty(r.get("away")) or _nonempty(r.get("home")))]
    sections=[s for s in (data.get("playerStatSections") or []) if isinstance(s,dict) and (s.get("rows") or [])]
    player_rows=sum(len(s.get("rows") or []) for s in sections)
    timeline=[x for x in (data.get("timeline") or []) if isinstance(x,dict) and str(x.get("description") or "").strip()]
    scoring=[x for x in (data.get("scoringPlays") or []) if isinstance(x,dict) and str(x.get("description") or "").strip()]
    innings=[x for x in (board.get("innings") or []) if isinstance(x,dict)]
    status=str(event.get("status") or board.get("status") or "").lower()
    final=bool(re.search(r"final|finished|game over|completed|complete|post",status))
    live=bool(data.get("live")) or (bool(re.search(r"live|progress|inning|quarter|half|period|^in$",status)) and not final)
    scheduled=bool(re.search(r"scheduled|pre-game|pregame|preview|not started",status)) and not live and not final
    missing=[]
    if not identity: missing.append("identity")
    if not score and not scheduled: missing.append("score")
    complete=False
    if scheduled and identity:
        complete=True
    elif comp=="MLB":
        if len(innings)<3: missing.append("linescore")
        if len(team_stats)<4: missing.append("teamStats")
        if player_rows<8: missing.append("playerStats")
        if len(timeline)<5: missing.append("playByPlay")
        if score and score_total>0 and len(scoring)<1: missing.append("scoringPlays")
        complete=identity and score and not missing
    elif comp=="NFL":
        if len(team_stats)<4: missing.append("teamStats")
        if player_rows<4: missing.append("playerStats")
        if len(timeline)<5: missing.append("playByPlay")
        if score and score_total>0 and len(scoring)<1: missing.append("scoringPlays")
        complete=identity and score and not missing
    elif comp in {"MLS","EPL"}:
        if len(team_stats)<3: missing.append("teamStats")
        # Soccer providers differ on whether they expose a full commentary feed.
        # Require a meaningful event timeline OR key scoring events for completed games.
        if final and len(timeline)<3 and len(scoring)<1: missing.append("playByPlay")
        complete=identity and score and not missing
    else:
        complete=identity and (score or scheduled) and bool(team_stats or timeline or sections or scheduled)
    # De-duplicate in deterministic order.
    missing=list(dict.fromkeys(missing))
    richness=(len(team_stats)*2)+(player_rows//3)+len(timeline)+(len(scoring)*2)+(len(innings)*2)
    return {
        "complete":bool(complete),"richness":int(richness),"final":final,"live":live,"scheduled":scheduled,
        "missing":missing,"identity":identity,"score":score,"teamStats":len(team_stats),"playerRows":player_rows,
        "timeline":len(timeline),"scoringPlays":len(scoring),"innings":len(innings)
    }

def _apply_coverage_fields(out):
    cov=game_center_coverage(out or {})
    out["coverage"]=cov
    out["partial"]=not cov.get("complete")
    out["quality"]={"level":"rich" if cov.get("complete") else ("partial" if cov.get("identity") else "shell"),"score":cov.get("richness",0),**cov}
    return out

def _merge_stat_rows(primary,secondary):
    rows={}
    for src in (primary or [],secondary or []):
        for row in src:
            if not isinstance(row,dict) or not str(row.get("label") or "").strip(): continue
            key=str(row.get("label") or "").strip().lower()
            cur=rows.setdefault(key,copy.deepcopy(row))
            if not _nonempty(cur.get("away")) and _nonempty(row.get("away")): cur["away"]=copy.deepcopy(row.get("away"))
            if not _nonempty(cur.get("home")) and _nonempty(row.get("home")): cur["home"]=copy.deepcopy(row.get("home"))
    return list(rows.values())

def _section_key(section):
    return re.sub(r"[^a-z0-9]+"," ",str((section or {}).get("title") or "").lower()).strip()

def _merge_player_sections(primary,secondary):
    out=[]; by={}
    for src in (primary or [],secondary or []):
        for sec in src:
            if not isinstance(sec,dict): continue
            key=_section_key(sec) or f"section-{len(out)}"
            existing=by.get(key)
            if existing is None:
                existing=copy.deepcopy(sec); by[key]=existing; out.append(existing); continue
            # Prefer whichever representation has more rows/columns. This avoids
            # combining incompatible provider column schemas into one malformed table.
            a=(len(existing.get("rows") or []),len(existing.get("columns") or []))
            b=(len(sec.get("rows") or []),len(sec.get("columns") or []))
            if b>a:
                idx=out.index(existing); existing=copy.deepcopy(sec); out[idx]=existing; by[key]=existing
    return out

def _merge_sequence(primary,secondary):
    out=[]; seen=set()
    for src in (primary or [],secondary or []):
        for row in src:
            if not isinstance(row,dict): continue
            key=str(row.get("id") or "") or "|".join(str(row.get(x) or "") for x in ("periodLabel","description","scoreAway","scoreHome"))
            if key in seen: continue
            seen.add(key);out.append(copy.deepcopy(row))
    return out

def merge_game_centers(primary,secondary):
    """Merge normalized providers and recalculate sport-aware completeness."""
    if not isinstance(primary,dict):
        out=copy.deepcopy(secondary or {})
        if isinstance(out,dict): _apply_coverage_fields(out)
        return out
    if not isinstance(secondary,dict):
        out=copy.deepcopy(primary or {});_apply_coverage_fields(out);return out
    # Start with the richer object, then fill holes from the other provider.
    pa=game_center_coverage(primary); pb=game_center_coverage(secondary)
    first,second=(primary,secondary) if pa["richness"]>=pb["richness"] else (secondary,primary)
    out=copy.deepcopy(first)
    def fill(dst,src):
        for k,v in (src or {}).items():
            if isinstance(v,dict):
                if not isinstance(dst.get(k),dict): dst[k]={}
                fill(dst[k],v)
            elif not _nonempty(dst.get(k)) and _nonempty(v): dst[k]=copy.deepcopy(v)
    fill(out.setdefault("event",{}),second.get("event") or {})
    fill(out.setdefault("scoreboard",{}),second.get("scoreboard") or {})
    out["teamStats"]=_merge_stat_rows(primary.get("teamStats"),secondary.get("teamStats"))
    out["playerStatSections"]=_merge_player_sections(primary.get("playerStatSections"),secondary.get("playerStatSections"))
    out["timeline"]=_merge_sequence(primary.get("timeline"),secondary.get("timeline"))
    out["scoringPlays"]=_merge_sequence(primary.get("scoringPlays"),secondary.get("scoringPlays"))
    ob=out.setdefault("scoreboard",{}); a=(primary.get("scoreboard") or {}); b=(secondary.get("scoreboard") or {})
    if len(b.get("innings") or [])>len(a.get("innings") or []): ob["innings"]=copy.deepcopy(b.get("innings") or [])
    elif len(a.get("innings") or []): ob["innings"]=copy.deepcopy(a.get("innings") or [])
    if not ob.get("totals"):
        ob["totals"]=copy.deepcopy(a.get("totals") or b.get("totals") or {})
    out["live"]=bool(primary.get("live") or secondary.get("live"))
    sources=[]
    for src in (primary.get("source"),secondary.get("source")):
        for part in str(src or "").split(" + "):
            if part and part not in sources: sources.append(part)
    out["source"]=" + ".join(sources)
    out["updatedAt"]=datetime.now(timezone.utc).isoformat()
    _apply_coverage_fields(out)
    return out

def normalize_mlb_feed(feed, game_pk):
    gd=(feed or {}).get("gameData") or {}; ld=(feed or {}).get("liveData") or {}
    teams=gd.get("teams") or {}; away=teams.get("away") or {}; home=teams.get("home") or {}
    status=gd.get("status") or {}; linescore=ld.get("linescore") or {}; box=(ld.get("boxscore") or {}).get("teams") or {}
    away_box=box.get("away") or {}; home_box=box.get("home") or {}
    innings=[]
    for inn in linescore.get("innings") or []:
        innings.append({
            "num":inn.get("num"),"ordinal":inn.get("ordinalNum") or str(inn.get("num") or ""),
            "away":_safe((inn.get("away") or {}).get("runs")),"home":_safe((inn.get("home") or {}).get("runs"))
        })
    def totals(side,team_box):
        t=(linescore.get("teams") or {}).get(side) or {}; ts=team_box.get("teamStats") or {}; batting=ts.get("batting") or {}; pitching=ts.get("pitching") or {}
        return {
            "runs":_safe(t.get("runs")),"hits":_safe(t.get("hits")),"errors":_safe(t.get("errors")),
            "walks":_safe(batting.get("baseOnBalls")),"strikeouts":_safe(batting.get("strikeOuts")),
            "leftOnBase":_safe(batting.get("leftOnBase")),"homeRuns":_safe(batting.get("homeRuns")),
            "pitchingStrikeouts":_safe(pitching.get("strikeOuts"))
        }
    away_tot=totals("away",away_box); home_tot=totals("home",home_box)
    def stat_rows(team_box,group):
        players=team_box.get("players") or {}; rows=[]
        order=team_box.get("batters" if group=="batting" else "pitchers") or []
        for pid in order:
            row=players.get(f"ID{pid}") or players.get(str(pid)) or {}
            stats=((row.get("stats") or {}).get(group) or {})
            if not stats: continue
            pos=(row.get("position") or {}).get("abbreviation") or ""
            if group=="batting":
                vals=[_person_name(row),pos,_safe(stats.get("atBats")),_safe(stats.get("runs")),_safe(stats.get("hits")),_safe(stats.get("rbi")),_safe(stats.get("baseOnBalls")),_safe(stats.get("strikeOuts")),_safe(stats.get("homeRuns"))]
            else:
                vals=[_person_name(row),_safe(stats.get("inningsPitched")),_safe(stats.get("hits")),_safe(stats.get("runs")),_safe(stats.get("earnedRuns")),_safe(stats.get("baseOnBalls")),_safe(stats.get("strikeOuts")),_safe(stats.get("homeRuns")),_safe(stats.get("era"))]
            rows.append(vals)
        return rows
    batting_cols=["Player","Pos","AB","R","H","RBI","BB","K","HR"]
    pitching_cols=["Pitcher","IP","H","R","ER","BB","K","HR","ERA"]
    sections=[]
    for side,team,tbox in (("away",away,away_box),("home",home,home_box)):
        label=team.get("name") or side.title()
        team_meta={"teamSide":side,"teamId":str(team.get("id") or ""),"teamName":label,"teamAbbreviation":team.get("abbreviation") or ""}
        sections.append({"title":f"{label} Batting","columns":batting_cols,"rows":stat_rows(tbox,"batting"),**team_meta})
        sections.append({"title":f"{label} Pitching","columns":pitching_cols,"rows":stat_rows(tbox,"pitching"),**team_meta})
    all_plays=((ld.get("plays") or {}).get("allPlays") or [])
    scoring_indexes=set((ld.get("plays") or {}).get("scoringPlays") or [])
    timeline=[]; scoring=[]
    for idx,p in enumerate(all_plays):
        about=p.get("about") or {}; result=p.get("result") or {}; matchup=p.get("matchup") or {}
        inning=about.get("inning"); half=about.get("halfInning") or ""; desc=result.get("description") or result.get("event") or ""
        entry={
            "id":str(p.get("playId") or f"{game_pk}:{idx}"),"index":idx,"period":inning,"periodLabel":f"{half.title()} {inning}".strip(),
            "description":desc,"scoreAway":_safe(result.get("awayScore")),"scoreHome":_safe(result.get("homeScore")),
            "isScoring":idx in scoring_indexes or bool(about.get("isScoringPlay")),
            "batter":((matchup.get("batter") or {}).get("fullName") or ""),"pitcher":((matchup.get("pitcher") or {}).get("fullName") or "")
        }
        timeline.append(entry)
        if entry["isScoring"]: scoring.append(entry)
    is_live=str(status.get("abstractGameState") or "").lower()=="live"
    event={
        "eventId":str(game_pk),"gamePk":str(game_pk),"competitionId":"MLB","sportId":"baseball","eventKind":"game",
        "scheduledAt":gd.get("datetime",{}).get("dateTime") or "","status":status.get("detailedState") or status.get("abstractGameState") or "",
        "awayTeam":{"id":str(away.get("id") or ""),"name":away.get("name") or "","abbreviation":away.get("abbreviation") or ""},
        "homeTeam":{"id":str(home.get("id") or ""),"name":home.get("name") or "","abbreviation":home.get("abbreviation") or ""}
    }
    team_stats=[]
    for label,key in (("Runs","runs"),("Hits","hits"),("Errors","errors"),("Walks","walks"),("Strikeouts","strikeouts"),("Home Runs","homeRuns"),("Left On Base","leftOnBase")):
        team_stats.append({"label":label,"away":away_tot.get(key,""),"home":home_tot.get(key,"")})
    scoreboard={
        "away":{"team":event["awayTeam"],"score":away_tot["runs"]},"home":{"team":event["homeTeam"],"score":home_tot["runs"]},
        "status":event["status"],"inning":linescore.get("currentInning"),"inningOrdinal":linescore.get("currentInningOrdinal") or "",
        "inningState":linescore.get("inningState") or "","outs":linescore.get("outs"),"innings":innings,
        "totals":{"away":away_tot,"home":home_tot},
        "venue":(gd.get("venue") or {}).get("name") or ""
    }
    out={
        "version":"1.0","competitionId":"MLB","eventId":str(game_pk),"event":event,"scoreboard":scoreboard,"teamStats":team_stats,
        "playerStatSections":sections,"timeline":timeline,"scoringPlays":scoring,"live":is_live,
        "updatedAt":datetime.now(timezone.utc).isoformat(),"source":"MLB Stats API live feed"
    }
    _apply_coverage_fields(out)
    return out

def _schedule_game(payload):
    for block in (payload or {}).get("dates") or []:
        for game in block.get("games") or []:
            return game
    return {}

def _synthetic_feed_from_v1(game_pk, fetch_json, base_url):
    """Build the same normalized feed contract from stable v1 sub-endpoints.

    MLB's full live feed is served under /api/v1.1, while schedule/content and
    several component endpoints live under /api/v1. This fallback means Game
    Center still works if the monolithic feed is temporarily unavailable.
    """
    box=fetch_json(f"{base_url}/game/{game_pk}/boxscore",timeout=10)
    linescore=fetch_json(f"{base_url}/game/{game_pk}/linescore",timeout=10)
    plays=fetch_json(f"{base_url}/game/{game_pk}/playByPlay",timeout=10)
    schedule=fetch_json(f"{base_url}/schedule?sportId=1&gamePk={game_pk}&hydrate=team,venue",timeout=10)
    game=_schedule_game(schedule)
    box_teams=(box or {}).get("teams") or {}
    away_box=box_teams.get("away") or {}; home_box=box_teams.get("home") or {}
    schedule_teams=(game.get("teams") or {}) if isinstance(game,dict) else {}
    def team(side,team_box):
        candidate=(team_box.get("team") or {}) if isinstance(team_box,dict) else {}
        if candidate: return candidate
        return ((schedule_teams.get(side) or {}).get("team") or {})
    game_data={
        "status":game.get("status") or {},
        "teams":{"away":team("away",away_box),"home":team("home",home_box)},
        "venue":game.get("venue") or {},
        "datetime":{"dateTime":game.get("gameDate") or ""}
    }
    live_data={"linescore":linescore or {},"boxscore":box or {},"plays":plays or {}}
    return {"gameData":game_data,"liveData":live_data}

def fetch_mlb_game_center(game_pk, fetch_json, base_url):
    base=str(base_url).rstrip("/")
    # MLB's full game feed is v1.1, not v1. v2.6.0.1 accidentally appended
    # /feed/live to the v1 base, which produced the real-device 404.
    if base.endswith("/api/v1"):
        feed_base=base[:-len("/api/v1")]+"/api/v1.1"
    else:
        feed_base=base.replace("/api/v1/","/api/v1.1/")
    try:
        feed=fetch_json(f"{feed_base}/game/{game_pk}/feed/live",timeout=10)
    except Exception:
        feed=_synthetic_feed_from_v1(game_pk,fetch_json,base)
    return normalize_mlb_feed(feed,game_pk)

# ESPN Game Center adapters -------------------------------------------------

def _espn_status_parts(payload):
    header=(payload or {}).get('header') or {}
    competitions=header.get('competitions') or []
    comp=(competitions[0] if competitions else {}) or {}
    status=(comp.get('status') or header.get('status') or {})
    typ=status.get('type') or {}
    state=str(typ.get('state') or '')
    detail=str(typ.get('shortDetail') or typ.get('detail') or typ.get('description') or state)
    clock=str(status.get('displayClock') or '')
    period=status.get('period')
    return header,comp,status,state,detail,clock,period

def _espn_team_obj(team):
    team=team or {}
    return {
        'id':str(team.get('id') or ''),'name':team.get('displayName') or team.get('shortDisplayName') or team.get('name') or '',
        'abbreviation':team.get('abbreviation') or team.get('shortDisplayName') or '', 'logo':team.get('logo') or ''
    }

def _espn_competitors(comp):
    sides={}
    for row in comp.get('competitors') or []:
        side=str(row.get('homeAway') or '').lower()
        if side not in ('away','home'): continue
        sides[side]={'team':_espn_team_obj(row.get('team') or {}),'score':_safe(row.get('score')),'raw':row}
    return sides

def _espn_stat_map(team_rows):
    out={}
    for row in team_rows or []:
        team=_espn_team_obj(row.get('team') or {})
        stats={}
        for stat in row.get('statistics') or []:
            key=str(stat.get('name') or stat.get('label') or stat.get('abbreviation') or '').strip()
            if not key: continue
            stats[key]={'label':stat.get('label') or stat.get('abbreviation') or key,'value':stat.get('displayValue') if stat.get('displayValue') is not None else stat.get('value')}
        out[str(team.get('id') or '')]={'team':team,'stats':stats}
    return out

def _human_stat_label(name):
    text=str(name or '').replace('_',' ')
    if text.isupper(): return text
    return ' '.join(w.capitalize() for w in text.split())

def _espn_team_stats(payload,sides):
    boxes=((payload or {}).get('boxscore') or {}).get('teams') or []
    maps=_espn_stat_map(boxes)
    away_id=str(((sides.get('away') or {}).get('team') or {}).get('id') or '')
    home_id=str(((sides.get('home') or {}).get('team') or {}).get('id') or '')
    away=(maps.get(away_id) or {}).get('stats') or {}; home=(maps.get(home_id) or {}).get('stats') or {}
    keys=[]
    for k in list(away)+list(home):
        if k not in keys: keys.append(k)
    rows=[]
    for key in keys:
        a=away.get(key) or {}; h=home.get(key) or {}
        label=a.get('label') or h.get('label') or _human_stat_label(key)
        rows.append({'label':label,'away':_safe(a.get('value')),'home':_safe(h.get('value'))})
    return rows

def _espn_player_sections(payload,sides=None):
    sections=[]
    sides=sides or {}
    def side_for(team):
        tid=str((team or {}).get('id') or '')
        tab=str((team or {}).get('abbreviation') or '').lower()
        tname=str((team or {}).get('name') or '').lower()
        for side,row in sides.items():
            ref=(row or {}).get('team') or {}
            if tid and str(ref.get('id') or '')==tid: return side
            if tab and str(ref.get('abbreviation') or '').lower()==tab: return side
            if tname and str(ref.get('name') or '').lower()==tname: return side
        return ''
    for team_group in ((payload or {}).get('boxscore') or {}).get('players') or []:
        team=_espn_team_obj(team_group.get('team') or {})
        team_side=side_for(team)
        for group in team_group.get('statistics') or []:
            labels=list(group.get('labels') or group.get('keys') or [])
            title=str(group.get('name') or group.get('displayName') or group.get('description') or 'Players')
            cols=['Player']+[str(x) for x in labels]
            rows=[]
            for entry in group.get('athletes') or []:
                athlete=entry.get('athlete') or {}
                name=athlete.get('displayName') or athlete.get('fullName') or athlete.get('shortName') or ''
                stats=entry.get('stats') or entry.get('statistics') or []
                if isinstance(stats,dict): stats=[stats.get(x,'') for x in labels]
                rows.append([name]+[_safe(x) for x in list(stats)])
            if rows:
                sections.append({'title':f"{team.get('name') or team.get('abbreviation') or ''} {title}".strip(),'columns':cols,'rows':rows,
                  'teamSide':team_side,'teamId':str(team.get('id') or ''),'teamName':team.get('name') or '',
                  'teamAbbreviation':team.get('abbreviation') or ''})
    # Soccer sometimes exposes rosters rather than boxscore.players.
    if not sections:
        for roster in (payload or {}).get('rosters') or []:
            team=_espn_team_obj(roster.get('team') or {})
            rows=[]
            for entry in roster.get('roster') or roster.get('athletes') or []:
                athlete=entry.get('athlete') or entry
                name=athlete.get('displayName') or athlete.get('fullName') or athlete.get('shortName') or ''
                pos=(athlete.get('position') or {}).get('abbreviation') or (athlete.get('position') or {}).get('name') or ''
                starter=entry.get('starter')
                rows.append([name,pos,'Starter' if starter else ('Sub' if starter is False else '')])
            if rows:
                side=side_for(team)
                sections.append({'title':f"{team.get('name') or ''} Lineup".strip(),'columns':['Player','Pos','Role'],'rows':rows,
                  'teamSide':side,'teamId':str(team.get('id') or ''),'teamName':team.get('name') or '',
                  'teamAbbreviation':team.get('abbreviation') or ''})
    return sections

def _espn_flat_plays(payload):
    rows=[]
    direct=(payload or {}).get('plays')
    if isinstance(direct,list): rows.extend(direct)
    # NFL summary commonly nests all plays inside drives.previous/current.
    drives=(payload or {}).get('drives') or {}
    if isinstance(drives,dict):
        seq=[]
        prev=drives.get('previous') or []
        if isinstance(prev,list): seq.extend(prev)
        cur=drives.get('current')
        if isinstance(cur,dict): seq.append(cur)
        for drive in seq:
            for play in (drive or {}).get('plays') or []: rows.append(play)
    # Soccer summary uses keyEvents/commentary depending on competition.
    if not rows:
        for key in ('keyEvents','commentary'):
            value=(payload or {}).get(key)
            if isinstance(value,list): rows.extend(value)
    return rows

def _espn_timeline(payload,competition,sides):
    out=[]; scoring=[]
    for idx,p in enumerate(_espn_flat_plays(payload)):
        period=(p.get('period') or {})
        if isinstance(period,dict): period_no=period.get('number'); period_name=period.get('displayValue') or period.get('type') or ''
        else: period_no=period; period_name=''
        clock=p.get('clock') or {}
        clock_text=clock.get('displayValue') if isinstance(clock,dict) else str(clock or '')
        desc=p.get('text') or p.get('description') or p.get('shortText') or p.get('headline') or ''
        typ=p.get('type') or {}
        type_text=' '.join(str(x or '') for x in ((typ.get('text') if isinstance(typ,dict) else typ),(typ.get('type') if isinstance(typ,dict) else '')))
        is_scoring=bool(p.get('scoringPlay') or p.get('isScoringPlay') or p.get('scoreValue'))
        if competition in {'MLS','EPL'} and not is_scoring:
            is_scoring=('goal' in type_text.lower()) or (' goal' in (' '+str(desc).lower()))
        label=' '.join(str(x) for x in (period_name or period_no,clock_text) if x not in (None,''))
        entry={
            'id':str(p.get('id') or p.get('playId') or f"{competition}:{idx}"),'index':idx,'period':period_no,
            'periodLabel':label,'description':desc or type_text or 'Play','scoreAway':_safe(p.get('awayScore')),
            'scoreHome':_safe(p.get('homeScore')),'isScoring':is_scoring
        }
        out.append(entry)
        if is_scoring: scoring.append(entry)
    # Some ESPN payloads provide a clean scoringPlays list separately.
    if not scoring and isinstance((payload or {}).get('scoringPlays'),list):
        for idx,p in enumerate((payload or {}).get('scoringPlays') or []):
            desc=p.get('text') or p.get('description') or ''
            entry={'id':str(p.get('id') or f'{competition}:score:{idx}'),'index':idx,'period':((p.get('period') or {}).get('number') if isinstance(p.get('period'),dict) else p.get('period')),'periodLabel':str(((p.get('clock') or {}).get('displayValue') if isinstance(p.get('clock'),dict) else '') or ''),'description':desc,'scoreAway':_safe(p.get('awayScore')),'scoreHome':_safe(p.get('homeScore')),'isScoring':True}
            scoring.append(entry)
            if not out: out.append(entry)
    return out,scoring

def normalize_espn_summary(payload,competition,event_id):
    competition=str(competition or '').upper()
    header,comp,status,state,detail,clock,period=_espn_status_parts(payload)
    sides=_espn_competitors(comp)
    away=sides.get('away') or {'team':{},'score':''}; home=sides.get('home') or {'team':{},'score':''}
    completed=bool(((status.get('type') or {}).get('completed'))) or state.lower()=='post'
    live=state.lower()=='in'
    event={
        'eventId':str(event_id),'competitionId':competition,
        'sportId':'american-football' if competition=='NFL' else ('basketball' if competition=='NBA' else ('ice-hockey' if competition=='NHL' else ('football' if competition in {'MLS','EPL'} else competition.lower()))),
        'eventKind':'game' if competition in {'NFL','NBA','NHL'} else 'match','scheduledAt':comp.get('date') or header.get('date') or '',
        'status':detail or ('Final' if completed else ('Live' if live else state)),
        'awayTeam':away.get('team') or {},'homeTeam':home.get('team') or {}
    }
    venue=((comp.get('venue') or {}).get('fullName') or ((payload or {}).get('gameInfo') or {}).get('venue',{}).get('fullName') or '')
    scoreboard={
        'away':{'team':event['awayTeam'],'score':away.get('score')},'home':{'team':event['homeTeam'],'score':home.get('score')},
        'status':event['status'],'clock':clock,'period':period,'venue':venue,'completed':completed
    }
    team_stats=_espn_team_stats(payload,sides)
    player_sections=_espn_player_sections(payload,sides)
    timeline,scoring=_espn_timeline(payload,competition,sides)
    out={
        'version':'1.0','competitionId':competition,'eventId':str(event_id),'event':event,'scoreboard':scoreboard,
        'teamStats':team_stats,'playerStatSections':player_sections,'timeline':timeline,'scoringPlays':scoring,
        'live':live,'updatedAt':datetime.now(timezone.utc).isoformat(),'source':'ESPN Game Summary'
    }
    _apply_coverage_fields(out)
    return out

def fetch_espn_game_center(competition,event_id,fetch_json,site_api_base):
    competition=str(competition or '').upper()
    cfg={'NFL':('football','nfl'),'NBA':('basketball','nba'),'NHL':('hockey','nhl'),'MLS':('soccer','usa.1'),'EPL':('soccer','eng.1')}.get(competition)
    if not cfg: raise NotImplementedError(f'Game Center provider not implemented for {competition}')
    sport,slug=cfg
    base=str(site_api_base).rstrip('/')
    payload=fetch_json(f'{base}/{sport}/{slug}/summary?event={event_id}',timeout=10)
    return normalize_espn_summary(payload,competition,event_id)

# Highlightly Game Center adapter -------------------------------------------------

def _hl_unwrap(payload):
    value=payload
    if isinstance(value,dict) and 'data' in value:
        value=value.get('data')
    if isinstance(value,list):
        return value[0] if value and isinstance(value[0],dict) else {}
    return value if isinstance(value,dict) else {}

def _hl_team(raw):
    raw=raw or {}
    if isinstance(raw,str): return {'id':'','name':raw,'abbreviation':''}
    return {
        'id':str(raw.get('id') or raw.get('teamId') or ''),
        'name':raw.get('displayName') or raw.get('name') or raw.get('shortName') or '',
        'abbreviation':raw.get('abbreviation') or raw.get('abbr') or raw.get('shortName') or '',
        'logo':raw.get('logo') or raw.get('image') or ''
    }

def _hl_score(match,competition):
    state=(match or {}).get('state') or {}; score=state.get('score') or (match or {}).get('score') or {}
    def sum_side(v):
        if isinstance(v,list):
            try:return sum(float(x or 0) for x in v)
            except Exception:return None
        return None
    away_arr=sum_side(score.get('awayTeam') if isinstance(score,dict) else None); home_arr=sum_side(score.get('homeTeam') if isinstance(score,dict) else None)
    if away_arr is not None and home_arr is not None:return _safe(away_arr),_safe(home_arr)
    current=str((score.get('current') if isinstance(score,dict) else '') or state.get('current') or '').strip()
    parts=[x.strip() for x in current.replace(':','-').split('-') if x.strip()]
    if len(parts)==2:
        try:
            a,b=float(parts[0]),float(parts[1]); a=int(a) if a.is_integer() else a; b=int(b) if b.is_integer() else b
            if str(competition).upper() in {'MLB','NHL','MLS','EPL'}: return b,a
            return a,b
        except Exception: pass
    if isinstance(score,dict):
        away=score.get('awayScore',score.get('away',''));home=score.get('homeScore',score.get('home',''))
        if not isinstance(away,(dict,list)) and not isinstance(home,(dict,list)):return _safe(away),_safe(home)
    return '',''

def _hl_status(match):
    state=(match or {}).get('state') or {}
    if isinstance(state,str): return state
    return str(state.get('report') or state.get('description') or state.get('status') or state.get('stage') or (match or {}).get('status') or '')

def _hl_stat_records(row):
    row=row or {}
    raw=row.get('statistics') or row.get('stats') or row.get('matchStatistics') or []
    if not raw and isinstance(row.get('team'),dict):
        raw=(row.get('team') or {}).get('statistics') or (row.get('team') or {}).get('stats') or []
    if isinstance(raw,dict): raw=[{'name':k,'value':v} for k,v in raw.items()]
    return [x for x in raw if isinstance(x,dict)]

def _hl_stat_name(row): return str((row or {}).get('name') or (row or {}).get('displayName') or (row or {}).get('label') or (row or {}).get('abbreviation') or '').strip()
def _hl_stat_value(row): return _safe((row or {}).get('displayValue') if (row or {}).get('displayValue') is not None else (row or {}).get('value'))

def _hl_side_payload_rows(payload):
    """Normalize Highlightly's list, {data:list}, and {home,away} side shapes."""
    value=payload
    if isinstance(value,dict) and 'data' in value: value=value.get('data')
    if isinstance(value,list): return [x for x in value if isinstance(x,dict)]
    if isinstance(value,dict):
        rows=[]
        for side in ('away','home'):
            row=value.get(side) or value.get(f'{side}Team')
            if isinstance(row,dict):
                row=copy.deepcopy(row);row['_sbbSide']=side;rows.append(row)
        if rows:return rows
        # Some wrappers use arbitrary numeric/object values.
        vals=[x for x in value.values() if isinstance(x,dict)]
        if vals:return vals
    return []

def _hl_side_rows(rows,away_team,home_team):
    out={'away':None,'home':None}; aid=str((away_team or {}).get('id') or '');hid=str((home_team or {}).get('id') or '')
    an=str((away_team or {}).get('name') or '').lower();hn=str((home_team or {}).get('name') or '').lower()
    for row in rows or []:
        if not isinstance(row,dict): continue
        explicit=str(row.get('_sbbSide') or row.get('homeAway') or '').lower()
        if explicit in ('away','home') and out[explicit] is None: out[explicit]=row;continue
        # Team-stat rows nest the team; MLB box-score rows are the team object.
        team=_hl_team(row.get('team') or row.get('club') or row)
        tid=str(team.get('id') or '');name=str(team.get('name') or '').lower()
        if (aid and tid==aid) or (an and name and (an==name or an in name or name in an)):out['away']=row
        elif (hid and tid==hid) or (hn and name and (hn==name or hn in name or name in hn)):out['home']=row
    remaining=[x for x in (rows or []) if isinstance(x,dict) and x not in out.values()]
    if out['away'] is None and remaining: out['away']=remaining.pop(0)
    if out['home'] is None and remaining: out['home']=remaining.pop(0)
    return out

def _hl_team_stats(stats_rows,away_team,home_team):
    sides=_hl_side_rows(stats_rows,away_team,home_team)
    amap={_hl_stat_name(x):_hl_stat_value(x) for x in _hl_stat_records(sides.get('away')) if _hl_stat_name(x)}
    hmap={_hl_stat_name(x):_hl_stat_value(x) for x in _hl_stat_records(sides.get('home')) if _hl_stat_name(x)}
    keys=[]
    for k in list(amap)+list(hmap):
        if k not in keys: keys.append(k)
    return [{'label':k,'away':amap.get(k,''),'home':hmap.get(k,'')} for k in keys[:36]]

def _hl_short_stat(name):
    key=' '.join(str(name or '').replace('_',' ').split()).lower()
    known={
      'total at-bats':'AB','at bats':'AB','at-bats':'AB','runs':'R','total runs':'R','total hits':'H','hits':'H',
      'runs batted in':'RBI','rbi':'RBI','base on balls':'BB','walks':'BB','strikeouts':'K','total strikeouts':'K',
      'home runs':'HR','innings pitched':'IP','earned runs':'ER','earned run average':'ERA','era':'ERA',
      'points':'PTS','rebounds':'REB','assists':'AST','passing yards':'YDS','rushing yards':'YDS','receiving yards':'YDS'
    }
    return known.get(key,str(name or '')[:14])

def _hl_player_sections(box_rows,away_team,home_team):
    sides=_hl_side_rows(box_rows,away_team,home_team); sections=[]
    for side in ('away','home'):
        row=sides.get(side) or {}; team=_hl_team(row.get('team') or row)
        players=row.get('boxScores') or row.get('players') or row.get('athletes') or []
        groups={}
        for p in players if isinstance(players,list) else []:
            if not isinstance(p,dict): continue
            person=p.get('player') or p.get('athlete') or p.get('person') or p
            pname=str((person or {}).get('name') or (person or {}).get('fullName') or (person or {}).get('displayName') or '')
            if not pname: continue
            for stat in _hl_stat_records(p):
                group=str(stat.get('group') or stat.get('category') or 'Players').strip() or 'Players'
                groups.setdefault(group,{'cols':[],'rows':{}})
                name=_hl_stat_name(stat)
                if name and name not in groups[group]['cols']: groups[group]['cols'].append(name)
                groups[group]['rows'].setdefault(pname,{})[name]=_hl_stat_value(stat)
        for group,meta in groups.items():
            cols=meta['cols'][:16]
            rows=[[name]+[vals.get(c,'') for c in cols] for name,vals in meta['rows'].items()]
            if rows: sections.append({'title':f"{team.get('name') or side.title()} {group}",'columns':['Player']+[_hl_short_stat(c) for c in cols],'rows':rows,
              'teamSide':side,'teamId':str(team.get('id') or ''),'teamName':team.get('name') or '',
              'teamAbbreviation':team.get('abbreviation') or ''})
    return sections

def _hl_innings(match):
    state=(match or {}).get('state') or {}; score=(state.get('score') if isinstance(state,dict) else None) or (match or {}).get('score') or {}
    away=score.get('awayTeam') if isinstance(score,dict) else None; home=score.get('homeTeam') if isinstance(score,dict) else None
    if not isinstance(away,list) or not isinstance(home,list): return []
    out=[]
    for i in range(max(len(away),len(home))):
        out.append({'num':i+1,'ordinal':f'{i+1}','away':_safe(away[i] if i<len(away) else ''),'home':_safe(home[i] if i<len(home) else '')})
    return out

def _hl_timeline(match,competition):
    raw=(match or {}).get('plays') or (match or {}).get('events') or (match or {}).get('timeline') or []
    if isinstance(raw,dict): raw=raw.get('data') or raw.get('items') or raw.get('plays') or list(raw.values())
    out=[];scoring=[]
    for i,p in enumerate(raw if isinstance(raw,list) else []):
        if not isinstance(p,dict):continue
        desc=str(p.get('description') or p.get('text') or p.get('title') or p.get('name') or p.get('event') or '')
        period=p.get('inning') or p.get('period') or p.get('quarter') or p.get('half') or ''
        if isinstance(period,dict):period=period.get('displayValue') or period.get('number') or period.get('name') or ''
        clock=p.get('clock') or p.get('time') or p.get('minute') or ''
        if isinstance(clock,dict):clock=clock.get('displayValue') or clock.get('value') or ''
        scoring_flag=bool(p.get('isScoring') or p.get('isScoringPlay') or p.get('scoringPlay') or p.get('scoreValue'))
        if not scoring_flag:scoring_flag=bool(__import__('re').search(r'\b(home run|homers?|scores?|touchdown|field goal|goal|penalty kick|safety)\b',desc.lower()))
        entry={'id':str(p.get('id') or p.get('playId') or f'hl:{i}'),'index':i,'period':period,'periodLabel':' '.join(str(x) for x in (period,clock) if x not in ('',None)),'description':desc or 'Play','scoreAway':_safe(p.get('awayScore')),'scoreHome':_safe(p.get('homeScore')),'isScoring':scoring_flag}
        out.append(entry)
        if scoring_flag:scoring.append(entry)
    return out,scoring

def normalize_highlightly_game_center(match_payload,competition,match_id,statistics_payload=None,box_payload=None):
    competition=str(competition or '').upper();match=_hl_unwrap(match_payload)
    away=_hl_team(match.get('awayTeam') or match.get('away') or {});home=_hl_team(match.get('homeTeam') or match.get('home') or {})
    away_score,home_score=_hl_score(match,competition);status=_hl_status(match)
    stats_raw=_hl_side_payload_rows(statistics_payload)
    if not stats_raw: stats_raw=_hl_side_payload_rows(match.get('matchStatistics') or match.get('statistics') or match.get('stats') or [])
    box_raw=_hl_side_payload_rows(box_payload)
    if not box_raw: box_raw=_hl_side_payload_rows(match.get('boxScores') or match.get('rosters') or [])
    team_stats=_hl_team_stats(stats_raw,away,home)
    player_sections=_hl_player_sections(box_raw,away,home)
    timeline,scoring=_hl_timeline(match,competition)
    low=status.lower();final=any(x in low for x in ('final','finished','complete','game over'))
    live=any(x in low for x in ('live','progress','inning','quarter','half','period')) and not final
    event={'eventId':str(match_id),'competitionId':competition,'sportId':'baseball' if competition=='MLB' else ('american-football' if competition=='NFL' else ('football' if competition in {'MLS','EPL'} else competition.lower())),'eventKind':'game' if competition in {'MLB','NFL'} else 'match','scheduledAt':match.get('date') or match.get('scheduledAt') or '','status':status,'awayTeam':away,'homeTeam':home}
    venue=match.get('venue') or {};venue_name=venue.get('name') if isinstance(venue,dict) else str(venue or '')
    scoreboard={'away':{'team':away,'score':away_score},'home':{'team':home,'score':home_score},'status':status,'venue':venue_name or ''}
    innings=_hl_innings(match)
    if innings: scoreboard['innings']=innings
    out={'version':'1.0','competitionId':competition,'eventId':str(match_id),'event':event,'scoreboard':scoreboard,'teamStats':team_stats,'playerStatSections':player_sections,'timeline':timeline,'scoringPlays':scoring,'live':live,'updatedAt':datetime.now(timezone.utc).isoformat(),'source':'Highlightly match detail'}
    _apply_coverage_fields(out)
    return out


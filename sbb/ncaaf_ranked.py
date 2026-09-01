"""Sports Big Board v4.7.14 — AP Top 25 College Football season service.

NCAAF is a persistent league whose weekly membership is determined by the AP Top 25
snapshot applicable to that ESPN schedule week. Ranking snapshots are immutable
once stored. A game's archived team rank therefore never changes when a later poll
moves that team up, down, into, or out of the Top 25.

Selection contract:
- include every FBS game where either participant is in that week's AP Top 25;
- a ranked-v-ranked matchup is one event carrying both ranks;
- unranked opponents remain in the event but carry no rank;
- never project a future week's games from the previous week's rankings;
- materialize a week only after its AP snapshot is known;
- refresh recent materialized weeks for score/status changes without changing rank.

The Competition Builder remains the persistence/media enrollment authority. This
service supplies dynamic weekly schedule membership and immutable AP rank context.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, parse_qs, urlparse
from urllib.request import Request, urlopen
import hashlib, json, os, re, sys, threading, time
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo=None

from . import competition_builder as builder

SEASON=2026
COMPETITION_ID='NCAAF'
SEASON_ID='NCAAF2026'
NAME='College Football 2026'
SHORT_NAME='NCAAF'
START_DATE='2026-08-29'
END_DATE='2027-01-25'
EXPECTED_GAMES_MIN=280
EXPECTED_GAMES_MAX=310
SCHEDULE_SOURCE='https://www.espn.com/college-football/schedule/_/week/1/year/2026/seasontype/2'
PURPLE_PLAYLIST='https://www.youtube.com/playlist?list=PLPydJJjt7Pb4'
RANKINGS_PAGE='https://www.espn.com/college-football/rankings'
RANKINGS_URL='https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings'
SCOREBOARD_URL='https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard'
POLL_NAME='AP Top 25'
SNAPSHOT_SCHEMA_VERSION=2
SNAPSHOT_AUTHORITY='ESPN_AP_TOP_25'
# Verified ESPN AP Top 25 shown on the official rankings page for the opening
# 2026 poll. This one-time bootstrap prevents a legacy Coaches/other-poll Week 1
# snapshot from remaining frozen forever. Later weeks continue to come from ESPN.
WEEK1_AP_2026=[
    (1,'194','Ohio State','OSU'),(2,'2483','Oregon','ORE'),(3,'61','Georgia','UGA'),
    (4,'87','Notre Dame','ND'),(5,'251','Texas','TEX'),(6,'84','Indiana','IND'),
    (7,'2390','Miami','MIA'),(8,'245','Texas A&M','TA&M'),(9,'145','Ole Miss','MISS'),
    (10,'201','Oklahoma','OU'),(11,'99','LSU','LSU'),(12,'2641','Texas Tech','TTU'),
    (13,'333','Alabama','ALA'),(14,'30','USC','USC'),(14,'252','BYU','BYU'),
    (16,'130','Michigan','MICH'),(17,'264','Washington','WASH'),(18,'213','Penn State','PSU'),
    (19,'2567','SMU','SMU'),(20,'2633','Tennessee','TENN'),(21,'254','Utah','UTAH'),
    (22,'2294','Iowa','IOWA'),(23,'248','Houston','HOU'),(24,'97','Louisville','LOU'),
    (25,'142','Missouri','MIZ'),
]
REFRESH_SECONDS=max(300,int(os.environ.get('SBB_NCAAF_REFRESH_SECONDS','1800') or 1800))
_STATE_DIR=Path(os.environ.get('SBB_STATE_DIR') or (Path.home()/'.sports-big-board')).expanduser()
_STATE_PATH=_STATE_DIR/f'ncaaf-ranked-{SEASON}.json'
_LOCK=threading.RLock()
_INSTALL_LOCK=threading.Lock()
_INSTALLED=False
_STATUS={'state':'STARTING','lastRefreshAt':0.0,'lastSuccessAt':0.0,'lastError':'','pollWeek':0,'snapshots':0,'games':0,'changed':False}


def _fetch_json(url,timeout=12):
    req=Request(url,headers={'User-Agent':'Mozilla/5.0 SportsBigBoard/4.7.14','Accept':'application/json'})
    with urlopen(req,timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _load_state():
    with _LOCK:
        try:
            raw=json.loads(_STATE_PATH.read_text(encoding='utf-8'))
            if isinstance(raw,dict) and int(raw.get('season') or 0)==SEASON:
                raw.setdefault('snapshots',{});raw.setdefault('weeks',{});return raw
        except Exception: pass
        return {'version':1,'season':SEASON,'seasonId':SEASON_ID,'snapshots':{},'weeks':{},'updatedAt':0.0}


def _save_state(state):
    with _LOCK:
        _STATE_DIR.mkdir(parents=True,exist_ok=True)
        payload=deepcopy(state);payload['updatedAt']=time.time()
        tmp=_STATE_PATH.with_suffix('.tmp')
        tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(tmp,_STATE_PATH)
        return payload


def _norm(value):
    return re.sub(r'[^a-z0-9]+',' ',str(value or '').lower()).strip()


def _week_number(payload,ranking=None):
    candidates=[]
    for obj in (ranking or {},payload or {}):
        for key in ('week','latestWeek','currentWeek'):
            value=(obj or {}).get(key) if isinstance(obj,dict) else None
            if isinstance(value,dict): value=value.get('number') or value.get('value')
            candidates.append(value)
    for value in candidates:
        try:
            n=int(value)
            if n>0:return n
        except Exception:pass
    return 1


def _ap_block(payload):
    rankings=(payload or {}).get('rankings') or []
    for row in rankings:
        text=' '.join(str(row.get(k) or '') for k in ('name','shortName','headline','type')).lower()
        if 'ap top 25' in text or ('associated press' in text and '25' in text):return row
    # Fail closed. Falling back to the first poll can silently turn the NCAAF board
    # into Coaches/FCS/other-poll membership if ESPN changes response ordering.
    return None


def _parse_rankings(payload):
    block=_ap_block(payload)
    if not isinstance(block,dict):raise RuntimeError('ESPN rankings response did not contain an AP Top 25 block')
    week=_week_number(payload,block)
    teams={};ranks=[]
    for entry in block.get('ranks') or []:
        team=entry.get('team') or {}
        try:rank=int(entry.get('current') or entry.get('rank') or entry.get('currentRank') or 0)
        except Exception:rank=0
        if rank<1 or rank>25:continue
        team_id=str(team.get('id') or team.get('uid') or '').strip()
        name=str(team.get('displayName') or team.get('shortDisplayName') or team.get('name') or team.get('location') or '').strip()
        abbr=str(team.get('abbreviation') or '').strip()
        logo=str(team.get('logo') or ((team.get('logos') or [{}])[0] or {}).get('href') or '').strip()
        row={'rank':rank,'teamId':team_id,'name':name,'abbreviation':abbr,'logo':logo}
        ranks.append(row)
        for key in (team_id,_norm(name),_norm(team.get('shortDisplayName')),_norm(abbr)):
            if key:teams[key]=row
    ranks.sort(key=lambda x:x['rank'])
    unique_teams={str(x.get('teamId') or _norm(x.get('name'))) for x in ranks if x.get('teamId') or x.get('name')}
    if len(ranks)!=25 or len(unique_teams)!=25:
        raise RuntimeError(f'ESPN AP Top 25 block was incomplete/ambiguous: {len(ranks)} rows, {len(unique_teams)} unique teams')
    poll_date=str(block.get('date') or block.get('published') or payload.get('timestamp') or '')
    fingerprint=hashlib.sha1(json.dumps(ranks,sort_keys=True).encode()).hexdigest()[:16]
    return {'schemaVersion':SNAPSHOT_SCHEMA_VERSION,'authority':SNAPSHOT_AUTHORITY,'authorityVerified':True,'week':week,'pollName':POLL_NAME,'pollDate':poll_date,'fingerprint':fingerprint,'ranks':ranks,'teams':teams}


def _bootstrap_week1_snapshot():
    ranks=[];teams={}
    for rank,team_id,name,abbr in WEEK1_AP_2026:
        row={'rank':rank,'teamId':team_id,'name':name,'abbreviation':abbr,
             'logo':f'https://a.espncdn.com/i/teamlogos/ncaa/500/{team_id}.png'}
        ranks.append(row)
        for key in (team_id,_norm(name),_norm(abbr)):
            if key:teams[key]=row
    fingerprint=hashlib.sha1(json.dumps(ranks,sort_keys=True).encode()).hexdigest()[:16]
    return {'schemaVersion':SNAPSHOT_SCHEMA_VERSION,'authority':SNAPSHOT_AUTHORITY,
            'authorityVerified':True,'week':1,'pollName':POLL_NAME,
            'pollDate':'2026 PRESEASON','fingerprint':fingerprint,'ranks':ranks,'teams':teams,
            'bootstrap':'OFFICIAL_ESPN_AP_TOP25_2026_WEEK1'}


def _snapshot_verified(snapshot):
    snapshot=snapshot or {}
    if int(snapshot.get('schemaVersion') or 0)<SNAPSHOT_SCHEMA_VERSION:return False
    if snapshot.get('authority')!=SNAPSHOT_AUTHORITY or snapshot.get('authorityVerified') is not True:return False
    if str(snapshot.get('pollName') or '')!=POLL_NAME:return False
    ranks=snapshot.get('ranks') or []
    teams={str(x.get('teamId') or _norm(x.get('name'))) for x in ranks if x.get('teamId') or x.get('name')}
    return len(ranks)==25 and len(teams)==25


def _ranking_for_team(snapshot,team):
    team=team or {};team_id=str(team.get('id') or team.get('uid') or '').strip()
    lookup=(snapshot or {}).get('teams') or {}
    for key in (team_id,_norm(team.get('displayName')),_norm(team.get('shortDisplayName')),_norm(team.get('name')),_norm(team.get('abbreviation'))):
        if key and key in lookup:return lookup[key]
    return None


def _viewer_date(raw):
    raw=str(raw or '')
    try:
        dt=datetime.fromisoformat(raw.replace('Z','+00:00'))
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        tz=os.environ.get('SBB_SCHEDULE_TIMEZONE') or 'America/Los_Angeles'
        if ZoneInfo:dt=dt.astimezone(ZoneInfo(tz))
        return dt.date().isoformat()
    except Exception:return raw[:10]


def _status(comp):
    typ=(comp or {}).get('status') or {};t=typ.get('type') if isinstance(typ,dict) else {}
    completed=bool((t or {}).get('completed')) if isinstance(t,dict) else False
    name=str((t or {}).get('name') or (t or {}).get('state') or (t or {}).get('description') or '').upper()
    if completed or 'FINAL' in name or name=='POST':return 'FINAL'
    if name in {'IN','IN_PROGRESS','LIVE'}:return 'LIVE'
    if 'POSTPON' in name:return 'POSTPONED'
    if 'CANCEL' in name:return 'CANCELLED'
    return 'SCHEDULED'


def _team_obj(team,rank_row,week):
    team=team or {};name=str(team.get('displayName') or team.get('shortDisplayName') or team.get('name') or team.get('location') or '').strip()
    rank=int((rank_row or {}).get('rank') or 0)
    display=f'#{rank} {name}' if rank else name
    logo=str(team.get('logo') or ((team.get('logos') or [{}])[0] or {}).get('href') or '').strip()
    return {
        'id':str(team.get('id') or ''),'name':name,'displayName':display,
        'shortDisplayName':str(team.get('shortDisplayName') or name),
        'abbreviation':str(team.get('abbreviation') or ''),'logo':logo,
        'rank':rank or None,'apRank':rank or None,'rankLabel':f'#{rank}' if rank else '',
        'rankWeek':week,'rankPoll':POLL_NAME if rank else ''
    }


def _score(comp):
    value=(comp or {}).get('score')
    if isinstance(value,dict):value=value.get('displayValue') or value.get('value')
    try:return int(float(value))
    except Exception:return value if value not in (None,'') else ''


def _event_rows(payload,snapshot,week,season_type=2):
    out=[]
    for ev in (payload or {}).get('events') or []:
        comp=((ev.get('competitions') or [{}])[0] or {})
        competitors=comp.get('competitors') or []
        away=next((x for x in competitors if str(x.get('homeAway') or '').lower()=='away'),None)
        home=next((x for x in competitors if str(x.get('homeAway') or '').lower()=='home'),None)
        if not away or not home:continue
        away_team=away.get('team') or {};home_team=home.get('team') or {}
        away_rank=_ranking_for_team(snapshot,away_team);home_rank=_ranking_for_team(snapshot,home_team)
        if not away_rank and not home_rank:continue
        date=_viewer_date(ev.get('date'))
        event_id=str(ev.get('id') or '').strip()
        if not event_id:continue
        away_obj=_team_obj(away_team,away_rank,week);home_obj=_team_obj(home_team,home_rank,week)
        status=_status(comp)
        row={
            'id':event_id,'eventId':event_id,'espnEventId':event_id,'scoreEventId':event_id,
            'date':date,'gameDate':date,'scheduledAt':str(ev.get('date') or date),
            'away':away_obj,'home':home_obj,'awayTeam':away_obj,'homeTeam':home_obj,
            'awayScore':_score(away),'homeScore':_score(home),'status':status,
            'week':week,'ncaafWeek':week,'seasonType':season_type,'seasonYear':SEASON,
            'stage':f'Week {week}','round':f'Week {week}',
            'awayRank':away_obj.get('apRank'),'homeRank':home_obj.get('apRank'),
            'rankedTeamIds':[x for x in (away_obj.get('id') if away_rank else '',home_obj.get('id') if home_rank else '') if x],
            'rankingSnapshotId':f'{SEASON_ID}:AP:{week}','rankingFrozen':True,'rankPoll':POLL_NAME,
            'rankSnapshotFingerprint':snapshot.get('fingerprint'),'rankSnapshotDate':snapshot.get('pollDate') or '',
            'venue':str(((comp.get('venue') or {}).get('fullName')) or ''),
            'broadcast':', '.join(str(x.get('names',[x.get('name')])[0] if isinstance(x,dict) else x) for x in (comp.get('broadcasts') or []) if x),
            'sourceUrl':f'https://www.espn.com/college-football/game/_/gameId/{event_id}',
            'scheduleAuthority':'ESPN FBS','selectionRule':'AP_TOP_25_EITHER_PARTICIPANT'
        }
        out.append(row)
    return out


def _ranking_payload_for_week(week,current_payload=None):
    # Week 1 is pinned to the official ESPN AP Top 25 captured for the opening
    # poll. This repairs any legacy snapshot that was accidentally frozen from a
    # different poll before AP authority became fail-closed.
    if int(week)==1:return _bootstrap_week1_snapshot()
    # ESPN accepts season/week on many deployments. For a historical week, only
    # accept the response when its own week evidence agrees so a current poll can
    # never overwrite an archived snapshot.
    query=urlencode({'season':SEASON,'week':int(week)})
    payload=_fetch_json(f'{RANKINGS_URL}?{query}')
    parsed=_parse_rankings(payload)
    return parsed if int(parsed.get('week') or 0)==int(week) else None


def _current_snapshot(state):
    payload=_fetch_json(f'{RANKINGS_URL}?'+urlencode({'season':SEASON}))
    parsed=_parse_rankings(payload);week=str(parsed['week'])
    existing=(state.get('snapshots') or {}).get(week)
    if int(week)==1:
        pinned=_bootstrap_week1_snapshot()
        if (existing or {}).get('fingerprint')!=pinned.get('fingerprint'):
            state.setdefault('snapshotMigrations',[]).append({
                'week':1,'at':time.time(),'reason':'OFFICIAL_AP_WEEK1_BOOTSTRAP_APPLIED',
                'oldFingerprint':(existing or {}).get('fingerprint'),'newFingerprint':pinned.get('fingerprint')
            })
        parsed=pinned;state.setdefault('snapshots',{})['1']=pinned
    elif _snapshot_verified(existing):
        # Immutable weekly archive: verified v2 snapshots remain immutable for the life of their week.
        parsed=existing
    else:
        # One-time migration for v4.7.14-era snapshots. Before AP authority was
        # fail-closed, a non-AP/partial response could be frozen forever. Replace
        # only unverified legacy state, then freeze the verified AP snapshot.
        state.setdefault('snapshots',{})[week]=parsed
        state.setdefault('snapshotMigrations',[]).append({
            'week':int(week),'at':time.time(),'reason':'LEGACY_UNVERIFIED_AP_SNAPSHOT_REPLACED',
            'oldFingerprint':(existing or {}).get('fingerprint'),'newFingerprint':parsed.get('fingerprint')
        })
    state['snapshotSchemaVersion']=SNAPSHOT_SCHEMA_VERSION
    return state,parsed


def _schedule_for_week(snapshot,week,season_type=2):
    params={'season':SEASON,'seasontype':season_type,'week':int(week),'groups':80,'limit':1000}
    payload=_fetch_json(f'{SCOREBOARD_URL}?{urlencode(params)}')
    return _event_rows(payload,snapshot,int(week),season_type)


def _materialize(state,current_snapshot):
    week=int(current_snapshot['week']);weeks=state.setdefault('weeks',{})
    # Refresh the current week and the immediately previous materialized week so
    # live/final scores settle while their immutable rank snapshot remains frozen.
    targets=[week]
    if str(week-1) in state.get('snapshots',{}):targets.append(week-1)
    for target in sorted(set(x for x in targets if x>0)):
        snap=state.get('snapshots',{}).get(str(target))
        if target==1:
            snap=_bootstrap_week1_snapshot();state.setdefault('snapshots',{})['1']=snap
        if not snap:continue
        if not _snapshot_verified(snap):
            repaired=_ranking_payload_for_week(target)
            if repaired:
                state.setdefault('snapshots',{})[str(target)]=repaired
                snap=repaired
                state.setdefault('snapshotMigrations',[]).append({
                    'week':target,'at':time.time(),'reason':'LEGACY_HISTORICAL_AP_SNAPSHOT_REPLACED'
                })
            else:
                # Never materialize a schedule from a legacy/unverified poll.
                continue
        rows=_schedule_for_week(snap,target,2)
        weeks[str(target)]={'week':target,'seasonType':2,'snapshotFingerprint':snap.get('fingerprint'),'updatedAt':time.time(),'events':rows}
    events=[]
    for key in sorted(weeks,key=lambda x:int(x)):
        events.extend((weeks[key] or {}).get('events') or [])
    # ESPN event IDs are canonical; keep the newest score/status representation.
    by={str(x.get('eventId') or x.get('id')):x for x in events if x.get('eventId') or x.get('id')}
    return list(by.values())


def _sync_catalog_membership(server,events):
    """Remove legacy NCAAF catalog rows that are outside authoritative AP membership.

    Competition Builder upserts the current schedule but intentionally does not
    delete normalized history events. An early NCAAF import could therefore leave
    unranked-v-unranked games in history_catalog_event forever even after the
    weekly AP filter became correct. The persisted weekly NCAAF state is authoritative
    here, so obsolete NCAAF rows are removed while archived valid weeks remain.
    """
    repo=getattr(server,'HISTORY_REPOSITORY',None)
    valid={str(x.get('eventId') or x.get('id') or '') for x in (events or []) if x.get('eventId') or x.get('id')}
    if not repo or not hasattr(repo,'_connect') or not valid:return {'purged':0,'dates':[]}
    lock=getattr(repo,'_lock',None);conn=None;stale=[]
    if lock:lock.acquire()
    try:
        conn=repo._connect()
        rows=conn.execute("SELECT event_id,event_date FROM history_catalog_event WHERE league=?",(COMPETITION_ID,)).fetchall()
        stale=[(str(r['event_id']),str(r['event_date'] or '')[:10]) for r in rows if str(r['event_id']) not in valid]
        if stale:
            conn.executemany("DELETE FROM history_catalog_event WHERE league=? AND event_id=?",[(COMPETITION_ID,event_id) for event_id,_ in stale])
            for day in sorted({d for _,d in stale if d}):
                conn.execute("DELETE FROM history_day WHERE date=? AND league=?",(day,COMPETITION_ID))
            conn.commit()
    finally:
        if conn is not None:conn.close()
        if lock:lock.release()
    stale_dates=sorted({d for _,d in stale if d})
    if stale_dates:
        try:
            from . import day_state as _day_state
            engine=getattr(_day_state,'_ENGINE',None)
            if engine:
                # Delete the durable Day State snapshot too. Otherwise the browser
                # can keep receiving a pre-fix NCAAF row even after catalog cleanup.
                ds_conn=None
                try:
                    ds_conn=engine.store._connect()
                    ds_conn.executemany('DELETE FROM day_state WHERE day=?',[(day,) for day in stale_dates])
                    ds_conn.commit()
                finally:
                    if ds_conn is not None:ds_conn.close()
                for day in stale_dates:
                    with engine.lock:engine.cache.pop(day,None)
                    engine.enqueue(day,priority=True)
        except Exception:pass
    return {'purged':len(stale),'dates':stale_dates}


def _definition(event_count):
    return {
        'id':COMPETITION_ID,'seasonId':SEASON_ID,'name':NAME,'shortName':SHORT_NAME,
        'type':'LEAGUE','sportId':'american-football','year':SEASON,'seasonYear':SEASON,
        'startDate':START_DATE,'endDate':END_DATE,'format':'SEASON','logoStrategy':'AUTO',
        'eventIcon':'🏈','enabled':True,'mainRow':True,'gameCenterProvider':'','gameCenterDisabled':True,'scheduleMode':'DYNAMIC_RANKED','scheduleSourceUrl':SCHEDULE_SOURCE,
        'scoreSourceUrl':SCHEDULE_SOURCE,'autoRefresh':True,'refreshMinutes':30,
        'backgroundDiscovery':True,'crawlEnabled':True,'allowIncompleteSchedule':True,
        'expectedEventCount':0,'expectedEventRange':[EXPECTED_GAMES_MIN,EXPECTED_GAMES_MAX],
        'selectionPolicy':'AP_TOP_25_EITHER_PARTICIPANT','rankingAuthority':'AP Top 25 via ESPN','rankingSourceUrl':RANKINGS_PAGE,
        'rankingSnapshotPolicy':'IMMUTABLE_WEEKLY','rankingSeasonReset':True,
        'participantArtwork':'AUTO_TEAM_ART',
        'mediaSources':{'green':[],'purple':[{
            'url':PURPLE_PLAYLIST,'priority':'PRIMARY','trust':'OPERATOR_TRUSTED','recrawlMinutes':60,
            'titleIncludePhrase':'full game highlights','sourceLabel':'ESPN College Football — Full Game Highlights | 2026-27'
        }],'blue':[]},
        'notes':'Persistent NCAA/FBS league filtered by the AP Top 25 snapshot applicable to each schedule week. Rankings are frozen into archived weekly events.'
    }


def _fingerprint(events,state):
    compact=[(x.get('eventId'),x.get('status'),x.get('awayScore'),x.get('homeScore'),x.get('awayRank'),x.get('homeRank')) for x in sorted(events,key=lambda r:str(r.get('eventId')))]
    snaps=[(k,(v or {}).get('fingerprint')) for k,v in sorted((state.get('snapshots') or {}).items(),key=lambda kv:int(kv[0]))]
    return hashlib.sha1(json.dumps({'events':compact,'snaps':snaps},sort_keys=True,default=str).encode()).hexdigest()


def refresh(server,force=False):
    started=time.time();state=_load_state()
    try:
        state,current=_current_snapshot(state)
        events=_materialize(state,current)
        new_fp=_fingerprint(events,state);old_fp=str(state.get('publishedFingerprint') or '')
        existing=None
        try:existing=builder._find(COMPETITION_ID)
        except Exception:existing=None
        changed=force or not existing or new_fp!=old_fp
        if changed and events:
            builder.save_competition(_definition(len(events)),events=events,server=server)
            state['publishedFingerprint']=new_fp
        catalog_sync=_sync_catalog_membership(server,events) if events else {'purged':0,'dates':[]}
        state['lastPollWeek']=int(current.get('week') or 0);state['lastRefreshAt']=time.time();state['eventCount']=len(events);state['catalogSync']=catalog_sync
        _save_state(state)
        with _LOCK:
            _STATUS.update({'state':'READY','lastRefreshAt':time.time(),'lastSuccessAt':time.time(),'lastError':'','pollWeek':int(current.get('week') or 0),'snapshots':len(state.get('snapshots') or {}),'games':len(events),'changed':bool(changed),'stalePurged':int(catalog_sync.get('purged') or 0),'staleDates':catalog_sync.get('dates') or [],'elapsedMs':round((time.time()-started)*1000,1)})
        return {'ok':True,**status(),'competition':builder._find(COMPETITION_ID)}
    except Exception as exc:
        with _LOCK:_STATUS.update({'state':'DEGRADED','lastRefreshAt':time.time(),'lastError':f'{type(exc).__name__}: {exc}','elapsedMs':round((time.time()-started)*1000,1)})
        return {'ok':False,**status()}


def _allowed_event_ids_by_date(state=None):
    state=state or _load_state();out={}
    for value in (state.get('weeks') or {}).values():
        for event in (value or {}).get('events') or []:
            event_id=str(event.get('eventId') or event.get('id') or '')
            day=str(event.get('date') or event.get('gameDate') or '')[:10]
            if event_id and day:out.setdefault(day,[]).append(event_id)
    return {day:sorted(set(ids)) for day,ids in out.items()}


def status():
    state=_load_state()
    with _LOCK:base=deepcopy(_STATUS)
    snapshots=[]
    for key,value in sorted((state.get('snapshots') or {}).items(),key=lambda kv:int(kv[0])):
        snapshots.append({'week':int(key),'fingerprint':(value or {}).get('fingerprint'),'pollDate':(value or {}).get('pollDate'),'teams':len((value or {}).get('ranks') or []),'verified':_snapshot_verified(value),'schemaVersion':int((value or {}).get('schemaVersion') or 0),'authority':(value or {}).get('authority') or ''})
    return {**base,'competitionId':COMPETITION_ID,'seasonId':SEASON_ID,'season':SEASON,'startDate':START_DATE,'endDate':END_DATE,'selectionPolicy':'AP_TOP_25_EITHER_PARTICIPANT','rankingSnapshotPolicy':'IMMUTABLE_WEEKLY','snapshotSchemaVersion':SNAPSHOT_SCHEMA_VERSION,'snapshotAuthority':SNAPSHOT_AUTHORITY,'rankingSourceUrl':RANKINGS_PAGE,'week1BootstrapTeams':len(WEEK1_AP_2026),'snapshotWeeks':snapshots,'snapshotMigrations':(state.get('snapshotMigrations') or [])[-10:],'statePath':str(_STATE_PATH)}


def _install_into_server():
    deadline=time.time()+120;server=None
    while time.time()<deadline:
        server=sys.modules.get('__main__')
        if server and hasattr(server,'Handler') and hasattr(server,'send_json') and hasattr(server,'HISTORY_REPOSITORY'):
            break
        time.sleep(.2)
    if not server:return

    # Register NCAAF immediately so frontend/core/history understand the league even
    # if ESPN is temporarily unavailable during boot. Builder persistence will
    # enrich this registry row as soon as the first weekly schedule materializes.
    try:
        from . import competition_registry as registry
        registry.register({
            'id':COMPETITION_ID,'name':NAME,'shortName':SHORT_NAME,'sportId':'american-football',
            'type':'LEAGUE','enabled':True,'mainRow':True,'custom':False,'startDate':START_DATE,'endDate':END_DATE,
            'scoreProvider':'ncaaf-ranked','mediaProviders':['operator-playlist','youtube'],
            'gameCenterProvider':'','gameCenterDisabled':True,'historyEnabled':True,'dayStateEnabled':True,
            'eventIcon':'🏈','seasonId':SEASON_ID,'seasonYear':SEASON,
            'selectionPolicy':'AP_TOP_25_EITHER_PARTICIPANT','rankingSnapshotPolicy':'IMMUTABLE_WEEKLY'
        },source='BUILT_IN')
    except Exception:pass

    Handler=server.Handler
    if not getattr(Handler,'__sbbCfbRankedInstalled',False):
        old_get=Handler.do_GET;old_post=Handler.do_POST
        def do_GET(self):
            parsed=urlparse(self.path)
            if parsed.path=='/api/ncaaf/status':return server.send_json(self,{'ok':True,**status()},200)
            if parsed.path=='/api/ncaaf/rankings':
                state=_load_state()
                # Week 1 is authoritative even before the first network refresh.
                state.setdefault('snapshots',{})['1']=_bootstrap_week1_snapshot()
                return server.send_json(self,{
                    'ok':True,'season':SEASON,'pollName':POLL_NAME,
                    'snapshots':state.get('snapshots') or {},
                    'rankedTeamIdsByWeek':{str(k):[str(x.get('teamId') or '') for x in ((v or {}).get('ranks') or []) if x.get('teamId')] for k,v in (state.get('snapshots') or {}).items()},
                    'allowedEventIdsByDate':{day:ids for day,ids in _allowed_event_ids_by_date(state).items()},
                    'weeks':{k:{'week':v.get('week'),'eventCount':len(v.get('events') or []),'updatedAt':v.get('updatedAt')} for k,v in (state.get('weeks') or {}).items()}
                },200)
            return old_get(self)
        def do_POST(self):
            parsed=urlparse(self.path)
            if parsed.path=='/api/ncaaf/refresh':
                threading.Thread(target=refresh,args=(server,True),daemon=True,name='sbb-ncaaf-manual-refresh').start()
                return server.send_json(self,{'ok':True,'started':True,'status':status()},202)
            return old_post(self)
        Handler.do_GET=do_GET;Handler.do_POST=do_POST;Handler.__sbbCfbRankedInstalled=True

    def worker():
        # First refresh soon after all Competition Builder/server helpers are ready.
        time.sleep(1.0)
        while True:
            try:refresh(server,force=False)
            except Exception:pass
            time.sleep(REFRESH_SECONDS)
    threading.Thread(target=worker,daemon=True,name='sbb-ncaaf-ranked-refresh').start()


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:return
        _INSTALLED=True
    threading.Thread(target=_install_into_server,daemon=True,name='sbb-ncaaf-ranked-install').start()

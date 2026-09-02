from contextlib import contextmanager
from pathlib import Path
import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import types
import time

ROOT=Path(__file__).resolve().parents[1]
MODULE_PATH=ROOT/'sbb'/'game_center_identity_v5122.py'


def clean_team(value):
    if isinstance(value,dict):
        value=value.get('abbreviation') or value.get('abbr') or value.get('shortName') or value.get('displayName') or value.get('name') or ''
    return ''.join(ch for ch in str(value or '').lower() if ch.isalnum())


class Repo:
    def __init__(self,path):
        self.path=Path(path);self._lock=threading.RLock();self.aliases={}
        with self._db() as con:
            con.execute('''CREATE TABLE game_centers(
                competition TEXT,event_id TEXT,status TEXT,live INTEGER,scheduled_at TEXT,provider TEXT,
                updated_at REAL,expires_at REAL,payload_json TEXT,PRIMARY KEY(competition,event_id))''')
    @contextmanager
    def _db(self):
        con=sqlite3.connect(self.path);con.row_factory=sqlite3.Row
        try:yield con;con.commit()
        finally:con.close()
    def put(self,competition,event_id,data,expires_at=None,updated_at=None):
        event=data.get('event') or {};board=data.get('scoreboard') or {};now=float(updated_at or time.time())
        with self._lock,self._db() as con:
            con.execute('''INSERT OR REPLACE INTO game_centers VALUES(?,?,?,?,?,?,?,?,?)''',(
                competition.upper(),str(event_id),str(event.get('status') or board.get('status') or ''),0,
                str(event.get('scheduledAt') or ''),'TEST',now,float(expires_at or now+999999),json.dumps(data)))
        return self.get(competition,event_id)
    def get(self,competition,event_id):
        with self._lock,self._db() as con:
            row=con.execute('SELECT * FROM game_centers WHERE competition=? AND event_id=?',(competition.upper(),str(event_id))).fetchone()
        if not row:return None
        return {'eventId':row['event_id'],'scheduledAt':row['scheduled_at'],'savedAt':row['updated_at'],'expiresAt':row['expires_at'],'data':json.loads(row['payload_json'])}
    def put_alias(self,competition,alias_id,resolved_event_id,*args,**kwargs):
        self.aliases[(competition.upper(),str(alias_id))]=str(resolved_event_id);return str(resolved_event_id)
    def resolve_alias(self,competition,alias_id):return self.aliases.get((competition.upper(),str(alias_id)),'')


def payload(event_id,away,home,start):
    return {
        'competitionId':'MLB','eventId':str(event_id),
        'event':{'competitionId':'MLB','eventId':str(event_id),'status':'Final','scheduledAt':start,
                 'awayTeam':{'name':away,'abbreviation':away},'homeTeam':{'name':home,'abbreviation':home}},
        'scoreboard':{'status':'Final','away':{'team':{'name':away,'abbreviation':away},'score':2},
                      'home':{'team':{'name':home,'abbreviation':home},'score':1}},
        'teamStats':[{'label':'Runs','away':2,'home':1}],
    }


def load_module():
    package=types.ModuleType('sbb');package.__path__=[str(ROOT/'sbb')];sys.modules['sbb']=package
    registry=types.ModuleType('sbb.competition_registry')
    registry.get=lambda cid,default=None: ({'id':cid,'sportId':'tennis','name':'2026 US Open'} if str(cid).upper()=='USOPEN-2026' else default)
    sys.modules['sbb.competition_registry']=registry
    spec=importlib.util.spec_from_file_location('sbb.game_center_identity_v5122',MODULE_PATH)
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
    return mod


def main():
    with tempfile.TemporaryDirectory() as tmp:
        mod=load_module();repo=Repo(Path(tmp)/'gc.sqlite3')
        repo.put('MLB','777001',payload('777001','PHI','ARI','2026-08-31T20:10:00Z'))
        calls={'network':0,'open':0,'store':0}

        server=types.SimpleNamespace()
        server.GAME_CENTER_REPOSITORY=repo
        server._gc_clean_team_hint=clean_team
        server._game_center_cached_record=lambda comp,eid: repo.get(comp,eid)
        def match(record,hints):
            data=(record or {}).get('data') or {};board=data.get('scoreboard') or {}
            return clean_team(((board.get('away') or {}).get('team') or {}))==clean_team(hints.get('away')) and clean_team(((board.get('home') or {}).get('team') or {}))==clean_team(hints.get('home'))
        server._game_center_record_matches_hints=match
        def original_resolve(comp,eid,hints=None,allow_fetch=False):
            alias=repo.resolve_alias(comp,eid)
            if alias:return alias
            if allow_fetch:calls['network']+=1;return 'NETWORK-ID'
            return ''
        server._resolve_game_center_event_id=original_resolve
        def original_open(*args,**kwargs):calls['open']+=1;raise NotImplementedError('fixed-league-only')
        server._game_center_open=original_open
        def original_store(comp,eid,data,saved_at=None):calls['store']+=1;return repo.put(comp,eid,data,updated_at=saved_at)
        server._game_center_store=original_store
        server.MILESTONE_CONSOLE=types.SimpleNamespace(record=lambda *a,**k:None)

        assert mod._install_server_patch(server)
        assert mod.snapshot()['backfilled']>=1
        hints={'date':'2026-08-31','away':'PHI','home':'ARI','start':'2026-08-31T20:10:00Z','gameNumber':'1'}
        resolved=server._resolve_game_center_event_id('MLB','score-provider-alias-42',hints,allow_fetch=True)
        assert resolved=='777001',resolved
        assert calls['network']==0,'cached fingerprint should avoid provider schedule lookup'
        assert repo.resolve_alias('MLB','score-provider-alias-42')=='777001'
        assert mod.snapshot()['providerFetchAvoided']>=1

        # A newly-stored Game Center is immediately indexed for future provider-id changes.
        server._game_center_store('MLB','777002',payload('777002','LAD','SD','2026-09-01T23:40:00Z'))
        resolved2=server._resolve_game_center_event_id('MLB','new-score-id',{'date':'2026-09-01','away':'LAD','home':'SD','start':'2026-09-01T23:40:00Z'},allow_fetch=True)
        assert resolved2=='777002'
        assert calls['network']==0

        # Tennis must never reach the fixed-league generic Game Center opener.
        tennis=types.ModuleType('sbb.tennis_game_center')
        tennis._ROUTE_LOCK=threading.RLock();tennis._ROUTE_RESULTS={};tennis._ROUTE_JOBS={};jobs=[]
        tennis._find_comp=lambda cid:{'id':cid,'sportId':'tennis','name':'2026 US Open'}
        tennis._find_event=lambda comp,eid:{'id':eid,'eventId':eid,'competitionId':comp['id'],'sportId':'tennis','date':'2026-08-31','awayTeam':{'name':'R. Safiullin'},'homeTeam':{'name':'C. Alcaraz'}}
        tennis._history_event=lambda *a,**k:None
        tennis._synthetic_event=lambda *a,**k:None
        tennis._route_key=lambda cid,eid:f'{cid}:{eid}'
        tennis._result_get=lambda key:tennis._ROUTE_RESULTS.get(key)
        def start(comp,event,eid):
            jobs.append((comp['id'],eid));tennis._ROUTE_JOBS[tennis._route_key(comp['id'],eid)]={'pending':True};return True
        tennis._start_route_job=start
        sys.modules['sbb.tennis_game_center']=tennis

        data,state,pending,eid=server._game_center_open('USOPEN-2026','match-1',False,{'date':'2026-08-31','away':'R. Safiullin','home':'C. Alcaraz'})
        assert data is None and pending and state=='PENDING' and eid=='match-1'
        assert calls['open']==0,'tennis fell through to fixed-league generic Game Center'
        assert jobs==[('USOPEN-2026','match-1')]
        tennis._ROUTE_RESULTS['USOPEN-2026:match-1']={'data':{'competitionId':'USOPEN-2026','eventId':'match-1','scoreboard':{'status':'Final'}},'error':''}
        data,state,pending,eid=server._game_center_open('USOPEN-2026','match-1',False,{'date':'2026-08-31','away':'R. Safiullin','home':'C. Alcaraz'})
        assert data['eventId']=='match-1' and not pending and state=='TENNIS-CANONICAL-HIT'

    print('PASS v5.1.22 durable Game Center identity and deterministic tennis routing')


if __name__=='__main__':main()

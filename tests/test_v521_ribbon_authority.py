from pathlib import Path
import importlib.util, sys, types

ROOT=Path(__file__).resolve().parents[1]

pkg=types.ModuleType('x');pkg.__path__=[];sys.modules['x']=pkg

day_state=types.ModuleType('x.day_state')
class DayStateEngine:
    def get(self,*a,**k): return None
def event_status(row):
    s=str((row or {}).get('status') or '').upper()
    if 'FINAL' in s:return 'FINAL'
    if 'LIVE' in s or 'IN_PROGRESS' in s:return 'LIVE'
    return 'SCHEDULED'
day_state.DayStateEngine=DayStateEngine;day_state._event_status=event_status
sys.modules['x.day_state']=day_state

spec=importlib.util.spec_from_file_location('x.ribbon_authority_v521',ROOT/'sbb/ribbon_authority_v521.py')
mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)

class Repo:
    def catalog_events(self,date_from=None,date_to=None,limit=None):
        if date_from=='2026-08-31':
            return [
                {'league':'EVENTX','eventId':'abc','event':{'id':'abc','eventId':'abc','competitionId':'EVENTX','away':{'name':'A'},'home':{'name':'B'},'status':'FINAL'}},
            ]
        if date_from=='2026-09-02':
            return [
                {'league':'MLB','eventId':'new','event':{'id':'new','eventId':'new','competitionId':'MLB','away':{'abbreviation':'ATH'},'home':{'abbreviation':'TEX'},'status':'SCHEDULED'}},
            ]
        return []
    def ribbon_media_for_date(self,date,leagues=None,include_failed=False):
        if date=='2026-08-31':
            return {'EVENTX:abc':[
                {'assetKey':'a1','youtubeId':'yt1','verifiedPlayable':True,'recapTier':'GREEN'},
                {'assetKey':'a2','youtubeId':'yt2','verifiedPlayable':True,'recapTier':'EXTENDED'},
            ]}
        return {}
class Server:
    HISTORY_REPOSITORY=Repo()
    def _history_schedule_sync_today(self):return '2026-09-02'

server=Server()
base={
 'date':'2026-08-31','generatedAt':1,'sourceRevision':'r1',
 'scoreRowsByLeague':{'EVENTX':[{'id':'abc','eventId':'abc','competitionId':'EVENTX','away':{'name':'A'},'home':{'name':'B'},'status':'FINAL'}]},
 'eventPlans':{},'summary':{'games':1,'playable':0},
}
out=mod._reconcile(server,'2026-08-31',base)
assert out['summary']['playable']==1,out
assert out['projectionDiagnostics']['ribbonProjectionDrift']==0,out
plan=next(iter(out['eventPlans'].values()))
assert len(plan['playable'])==2 and plan['databaseAuthority'] is True,plan

# A strong provider ID that belongs to another day cannot be rescued merely because
# the same teams play again. This blocks yesterday-final -> today contamination.
wrong={
 'date':'2026-09-02','generatedAt':1,'sourceRevision':'r2',
 'scoreRowsByLeague':{'MLB':[{'id':'old','eventId':'old','competitionId':'MLB','away':{'abbreviation':'ATH'},'home':{'abbreviation':'TEX'},'status':'FINAL','awayScore':5,'homeScore':8}]},
 'eventPlans':{},'summary':{'games':1,'playable':1},
}
out2=mod._reconcile(server,'2026-09-02',wrong)
assert out2['scoreGameCount']==0,out2
assert out2['projectionDiagnostics']['ribbonAuthorityCatalogDropped']==1,out2

print('PASS v5.2.1 canonical ribbon media/date authority')

import importlib.util
import pathlib
import sys
import types
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]


def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


class V4717GameCenterHistoryTests(unittest.TestCase):
    def setUp(self):
        self.saved={k:v for k,v in list(sys.modules.items()) if k=='sbb' or k.startswith('sbb.')}
        for k in list(sys.modules):
            if k=='sbb' or k.startswith('sbb.'):
                sys.modules.pop(k,None)
        pkg=types.ModuleType('sbb');pkg.__path__=[str(ROOT/'sbb')];sys.modules['sbb']=pkg

    def tearDown(self):
        for k in list(sys.modules):
            if k=='sbb' or k.startswith('sbb.'):
                sys.modules.pop(k,None)
        sys.modules.update(self.saved)

    def _game_center_stub(self):
        gc=types.ModuleType('sbb.game_center')
        gc._safe=lambda v:'' if v is None else v
        def status_parts(payload):
            header=payload.get('header') or {}; comps=header.get('competitions') or []; comp=comps[0] if comps else {}
            status=comp.get('status') or {};typ=status.get('type') or {}
            return header,comp,status,str(typ.get('state') or ''),str(typ.get('shortDetail') or ''),str(status.get('displayClock') or ''),status.get('period')
        gc._espn_status_parts=status_parts
        def flat_plays(payload): return list(payload.get('plays') or [])
        gc._espn_flat_plays=flat_plays
        def original_normalize(payload,competition,event_id):
            header,comp,*_=status_parts(payload); sides={}
            for row in comp.get('competitors') or []: sides[row.get('homeAway')] = row
            return {'competitionId':competition,'eventId':str(event_id),'event':{'competitionId':competition,'sportId':competition.lower(),'eventKind':'match'},'scoreboard':{
                'away':{'team':{'abbreviation':'SJSU'},'score':(sides.get('away') or {}).get('score','')},
                'home':{'team':{'abbreviation':'USC'},'score':(sides.get('home') or {}).get('score','')},
            },'teamStats':[{'label':'Total Yards','away':300,'home':450}],'playerStatSections':[{'title':'USC Passing','rows':[['QB',300]]}],'timeline':[{'description':'Play'}]*6,'scoringPlays':[{'description':'TD'}]}
        gc.normalize_espn_summary=original_normalize
        gc.fetch_espn_game_center=lambda *a,**k:None
        def coverage(data):
            return {'complete':str(data.get('competitionId'))=='NFL','richness':10,'identity':True,'score':True,'missing':[]}
        gc.game_center_coverage=coverage
        gc._apply_coverage_fields=lambda out: out.update({'coverage':gc.game_center_coverage(out),'partial':not gc.game_center_coverage(out).get('complete')}) or out
        sys.modules['sbb.game_center']=gc
        return gc

    def test_cfb_espn_summary_adds_quarter_linescore_and_win_probability(self):
        gc=self._game_center_stub()
        mod=load_module('sbb.game_center_multisport',ROOT/'sbb/game_center_multisport.py');mod.install()
        payload={'header':{'competitions':[{'competitors':[
            {'homeAway':'away','score':'26','linescores':[{'value':7},{'value':10},{'value':3},{'value':6}]},
            {'homeAway':'home','score':'42','linescores':[{'value':7},{'value':14},{'value':7},{'value':14}]},
        ],'status':{'type':{'state':'post','shortDetail':'Final'}}}]},
        'plays':[{'id':'p1','period':{'number':4},'clock':{'displayValue':'0:00'},'awayScore':26,'homeScore':42}],
        'winprobability':[{'playId':'start','homeWinPercentage':0.64,'tiePercentage':0},{'playId':'p1','homeWinPercentage':1.0,'tiePercentage':0}]}
        out=mod.normalize_espn_summary(payload,'CFB','401000001')
        self.assertEqual(out['event']['sportId'],'american-football')
        self.assertEqual(out['event']['eventKind'],'game')
        self.assertEqual([x['label'] for x in out['scoreboard']['periods']],['Q1','Q2','Q3','Q4'])
        self.assertEqual([x['away'] for x in out['scoreboard']['periods']],[7,10,3,6])
        self.assertEqual([x['home'] for x in out['scoreboard']['periods']],[7,14,7,14])
        self.assertEqual(out['scoreboard']['winProbability'][-1]['home'],100.0)
        self.assertEqual(out['scoreboard']['winProbability'][-1]['away'],0.0)
        self.assertTrue(out['coverage']['complete'])

    def test_cfb_fetch_uses_espn_college_football_summary(self):
        self._game_center_stub();mod=load_module('sbb.game_center_multisport',ROOT/'sbb/game_center_multisport.py')
        seen=[]
        def fetch(url,timeout=0):
            seen.append(url);return {'header':{'competitions':[{'competitors':[],'status':{}}]}}
        mod.fetch_espn_game_center('CFB','401000001',fetch,'https://site.api.espn.com/apis/site/v2/sports')
        self.assertIn('/football/college-football/summary?event=401000001',seen[0])

    def test_may_13_style_verified_database_asset_hydrates_playable(self):
        hist=types.ModuleType('sbb.history_repository')
        class HistoryRepository:
            @staticmethod
            def _hydrate_asset(row):
                return {'youtubeId':row.get('youtubeId','abc123'),'verifiedPlayable':False,'validationState':row.get('validation_state','CANDIDATE')}
        hist.HistoryRepository=HistoryRepository;sys.modules['sbb.history_repository']=hist
        mod=load_module('sbb.history_readiness_repair',ROOT/'sbb/history_readiness_repair.py')
        mod.install()
        item=HistoryRepository._hydrate_asset({'youtubeId':'abc123','validation_state':'VERIFIED','runtime_state':'UNKNOWN'})
        self.assertTrue(item['verifiedPlayable'])
        self.assertTrue(item['databaseVerifiedPlayable'])
        failed=HistoryRepository._hydrate_asset({'youtubeId':'abc123','validation_state':'VERIFIED','runtime_state':'FAILED'})
        self.assertFalse(failed['verifiedPlayable'])


if __name__=='__main__': unittest.main()

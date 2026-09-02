from pathlib import Path
from types import ModuleType, SimpleNamespace
import importlib.util
import sys
import tempfile
import unittest
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]

class TennisArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        pkg=ModuleType('sbb');pkg.__path__=[];sys.modules['sbb']=pkg
        base=ModuleType('sbb.competition_builder')
        base._STATE_DIR=Path(cls.tmp.name)
        base._find=lambda cid: None
        base.SERVICE=None
        base._effective_logo_strategy=lambda comp:'AUTO'
        base._decorate_team_artwork=lambda comp,team: dict(team or {})
        base._decorate_event_artwork=lambda comp,event: dict(event or {})
        base._country_code_for_name=lambda name:''
        base.normalize_event=lambda comp,raw,idx=0: dict(raw or {})
        def generic(comp,event):
            away=event.get('awayTeam') or event.get('away') or {};home=event.get('homeTeam') or event.get('home') or {}
            return {'competitionId':comp['id'],'eventId':event['eventId'],'event':dict(event),'scoreboard':{'status':event.get('status','SCHEDULED'),'away':{'team':away,'score':event.get('awayScore','')},'home':{'team':home,'score':event.get('homeScore','')}}}
        base.generic_game_center=generic
        sys.modules['sbb.competition_builder']=base
        registry=ModuleType('sbb.competition_registry')
        cls.regrow={'id':'USOPEN-2026','name':'2026 US Open','sportId':'tennis','type':'SPECIAL_EVENT','enabled':True}
        registry.get=lambda cid,default=None: dict(cls.regrow) if str(cid).upper()=='USOPEN-2026' else default
        sys.modules['sbb.competition_registry']=registry
        spec=importlib.util.spec_from_file_location('sbb.tennis_game_center',ROOT/'sbb/tennis_game_center.py')
        mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod);cls.mod=mod

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_round_normalization_never_renders_generic_round(self):
        r=self.mod._round_fields('Round');self.assertEqual(r['displayRound'],'')
        self.assertEqual(self.mod._round_fields('Round 1')['displayRound'],'R1')
        self.assertEqual(self.mod._round_fields('Quarterfinal')['displayRound'],'QF')
        self.assertEqual(self.mod._round_fields('Semifinal')['displayRound'],'SF')
        self.assertEqual(self.mod._round_fields('Final')['displayRound'],'F')

    def test_registry_is_tennis_routing_authority(self):
        row=self.mod._find_comp('USOPEN-2026')
        self.assertEqual(row['sportId'],'tennis')

    def test_legacy_v5118_final_cache_is_reused_without_provider_work(self):
        now=self.mod.time.time()
        legacy={'USOPEN-2026|legacy-match':{'data':{'event':{'status':'FINAL'},'scoreboard':{'status':'FINAL'},'tennis':{'matchId':'provider-legacy'}},'error':'','at':now-10,'expiresAt':now+3600,'final':True,'version':'5.1.18'}}
        self.mod._LEGACY_PERSIST_PATH.write_text(self.mod.json.dumps(legacy),encoding='utf-8')
        self.mod._PERSIST_LEGACY_CHECKED=False
        self.mod._PERSIST_PATH.unlink(missing_ok=True)
        row=self.mod._persist_get(('USOPEN-2026','legacy-match'))
        self.assertIsNotNone(row);self.assertEqual(row['data']['tennis']['matchId'],'provider-legacy')
        self.assertTrue(self.mod._PERSIST_PATH.exists())

    def test_compat_presentation_performs_no_provider_work(self):
        self.mod._scoreboard=lambda *a,**k: (_ for _ in ()).throw(AssertionError('provider call forbidden'))
        sent={}
        class Server:
            @staticmethod
            def send_json(handler,payload,status=200,headers=None): sent.update(payload=payload,status=status,headers=headers);return True
        handled=self.mod._serve_tennis_presentation(Server(),object(),urlparse('/api/tennis/presentation?competition=USOPEN-2026&date=2026-08-30'))
        self.assertTrue(handled);self.assertEqual(sent['status'],200);self.assertFalse(sent['payload']['providerFetches']);self.assertFalse(sent['payload']['warming'])

    def test_selected_event_route_claims_registry_tennis_without_builder_row(self):
        started={}
        original=self.mod._start_route_job
        self.mod._start_route_job=lambda comp,event,request_eid='': started.update(comp=comp,event=event,eid=request_eid) or True
        try:
            sent={}
            class Server:
                HISTORY_REPOSITORY=None
                @staticmethod
                def send_json(handler,payload,status=200,headers=None): sent.update(payload=payload,status=status,headers=headers);return True
            url='/api/events/USOPEN-2026/match-1/game-center?async=1&date=2026-08-30&away=Lucrezia%20Stefanini&home=Dayana%20Yastremska'
            handled=self.mod._serve_tennis_game_center(Server(),object(),urlparse(url))
            self.assertTrue(handled);self.assertEqual(sent['status'],202);self.assertEqual(sent['payload']['route'],'TENNIS_CANONICAL')
            self.assertEqual(started['event']['sportId'],'tennis');self.assertEqual(started['event']['eventId'],'match-1')
        finally:self.mod._start_route_job=original

if __name__=='__main__': unittest.main()

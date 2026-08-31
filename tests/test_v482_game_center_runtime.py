import importlib.util
import pathlib
import re
import types
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('sbb_game_center_runtime_v482',ROOT/'sbb'/'game_center_runtime_v482.py')
MOD=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MOD)


def norm(value):
    return re.sub(r'[^a-z0-9]','',str(value or '').lower())


class FakeRepository:
    def __init__(self): self.aliases=[]
    def put_alias(self,competition,requested,resolved): self.aliases.append((competition,requested,resolved))


class FakeServer:
    def __init__(self,rows):
        self.rows=list(rows);self.indexed=[];self.GAME_CENTER_REPOSITORY=FakeRepository();self.SBB_BACKEND_WIRING={}
        self._resolve_game_center_event_id=lambda competition,event_id,hints=None,allow_fetch=False:''
    def _espn_scoreboard(self,competition,date): return list(self.rows)
    def _index_game_center_events(self,competition,rows,date,provider): self.indexed.append((competition,date,provider,len(rows)));return rows
    def _same_team_pair(self,a,b):
        def aliases(team):
            return {norm(team.get(k)) for k in ('abbreviation','abbr','shortName','displayName','name') if norm(team.get(k))}
        aa=aliases((a or {}).get('awayTeam') or (a or {}).get('away') or {})
        ah=aliases((a or {}).get('homeTeam') or (a or {}).get('home') or {})
        ba=aliases((b or {}).get('awayTeam') or (b or {}).get('away') or {})
        bh=aliases((b or {}).get('homeTeam') or (b or {}).get('home') or {})
        return bool(aa & ba) and bool(ah & bh)


class V482GameCenterRuntimeTest(unittest.TestCase):
    def row(self,event_id='401810022'):
        return {'id':event_id,'espnEventId':event_id,'awayTeam':{'name':'Philadelphia 76ers','abbreviation':'PHI'},'homeTeam':{'name':'Chicago Bulls','abbreviation':'CHI'}}

    def test_exact_espn_id_is_verified_by_fingerprint(self):
        server=FakeServer([self.row()])
        resolved=MOD._resolve_from_espn_scoreboard(server,'NBA','401810022',{'date':'2026-01-03','away':'PHI','home':'CHI'})
        self.assertEqual(resolved,'401810022')
        self.assertTrue(server.indexed)

    def test_alias_resolves_to_unique_espn_id(self):
        server=FakeServer([self.row('401810999')])
        self.assertTrue(MOD._patch_server(server))
        resolved=server._resolve_game_center_event_id('NBA','highlightly-77',hints={'date':'2026-01-03','away':'Philadelphia 76ers','home':'Chicago Bulls'},allow_fetch=True)
        self.assertEqual(resolved,'401810999')
        self.assertEqual(server.GAME_CENTER_REPOSITORY.aliases,[('NBA','highlightly-77','401810999')])

    def test_ambiguous_or_mismatched_identity_fails_closed(self):
        rows=[self.row('1'),self.row('2')]
        server=FakeServer(rows)
        resolved=MOD._resolve_from_espn_scoreboard(server,'NHL','alias',{'date':'2026-01-03','away':'PHI','home':'CHI'})
        self.assertEqual(resolved,'')
        resolved=MOD._resolve_from_espn_scoreboard(FakeServer([self.row()]),'NBA','alias',{'date':'2026-01-03','away':'Boston Celtics','home':'Chicago Bulls'})
        self.assertEqual(resolved,'')

    def test_unsupported_competitions_are_not_enrolled(self):
        server=FakeServer([self.row()])
        self.assertEqual(MOD._resolve_from_espn_scoreboard(server,'LLWS2026','x',{'date':'2026-01-03','away':'PHI','home':'CHI'}),'')


if __name__=='__main__': unittest.main()

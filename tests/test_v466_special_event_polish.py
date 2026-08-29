import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sbb.competition_builder as cb

ROOT=Path(__file__).resolve().parents[1]

class _Repo:
    def __init__(self):
        self.events=[]
    def upsert_event(self,date,league,event_id,event):
        self.events.append((date,league,event_id,event))

class _Server:
    OPENAI_MODEL='gpt-5-mini'
    def __init__(self):
        self.HISTORY_LEAGUES=('MLB','NFL','NBA','NHL','EPL','MLS')
        self.HISTORY_REPOSITORY=_Repo()

class V466SpecialEventPolishTests(unittest.TestCase):
    def test_special_event_main_row_follows_browsed_date_and_dropdown_has_no_game_count(self):
        src=(ROOT/'architecture/competition-builder.js').read_text(encoding='utf-8')
        self.assertIn("const activeOnDate=(c,date=browseISO())",src)
        self.assertIn("const mainRowEligible=(c,date=browseISO())",src)
        self.assertIn("state.competitions.filter(c=>mainRowEligible(c,viewedDate))",src)
        self.assertNotIn("c.mainRow===true&&mainRowEligible(c)",src)
        self.assertIn("syncFilters();",src)
        start=src.index("function syncFilters()")
        end=src.index("async function deleteCompetition",start)
        menu=src[start:end]
        self.assertNotIn("eventsCount",menu)
        self.assertIn("sbb-special-event-status",menu)
        self.assertIn("activeHere?'ACTIVE':status",menu)

    def test_past_placeholder_is_detected_but_future_placeholder_is_not_yet_due(self):
        past={'date':'2026-07-14','away':'Winner Match 101','home':'Winner Match 102','status':'SCHEDULED'}
        future={'date':'2027-07-14','away':'Winner Match 101','home':'Winner Match 102','status':'SCHEDULED'}
        self.assertTrue(cb._event_needs_result_reconcile(past,today='2026-08-29'))
        self.assertFalse(cb._event_needs_result_reconcile(future,today='2026-08-29'))
        self.assertTrue(cb._event_needs_result_reconcile({'date':'2026-08-20','away':'A','home':'B','status':'SCHEDULED'},today='2026-08-29'))

    def test_results_reconciliation_preserves_canonical_event_id_and_replaces_actual_matchup(self):
        server=_Server()
        with tempfile.TemporaryDirectory() as td:
            old_store,old_rev=cb._STORE,cb._CATALOG_REVISION
            try:
                cb._STORE=Path(td)/'custom.json';cb._CATALOG_REVISION=0
                raw={
                    'id':'WC2026','name':'2026 FIFA World Cup','shortName':'WORLD CUP',
                    'type':'SPECIAL_EVENT','sportId':'football','startDate':'2026-06-11','endDate':'2026-07-19',
                    'expectedEventCount':1,'scheduleSourceUrl':'https://official.test/worldcup','logoStrategy':'COUNTRY_FLAGS'
                }
                cb.save_competition(raw,[{
                    'eventId':'sf-1','date':'2026-07-14','scheduledAt':'2026-07-14T20:00:00',
                    'away':'Winner Match 101','home':'Winner Match 102','status':'SCHEDULED',
                    'round':'Semifinal','stage':'Knockout','venue':'Test Stadium'
                }],server)
                result={
                    'sourceUrls':['https://official.test/worldcup'],
                    'results':[{
                        'eventId':'sf-1','date':'2026-07-14','away':'Spain','home':'Argentina',
                        'awayScore':0,'homeScore':2,'status':'FINAL','round':'Semifinal',
                        'stage':'Knockout','venue':'Test Stadium','sourceUrl':'https://official.test/sf-1'
                    }]
                }
                with patch.object(cb,'_openai_json_request',return_value=result), \
                     patch.object(cb,'_official_page_text',return_value=''):
                    report=cb.reconcile_competition_results(server,cb._find('WC2026'),force=True)
                self.assertEqual(report['updated'],1)
                self.assertEqual(report['remaining'],0)
                saved=cb._find('WC2026')
                self.assertEqual(saved['events'][0]['eventId'],'sf-1')
                self.assertEqual(saved['events'][0]['awayTeam']['name'],'Spain')
                self.assertEqual(saved['events'][0]['homeTeam']['name'],'Argentina')
                self.assertEqual(saved['events'][0]['awayScore'],0)
                self.assertEqual(saved['events'][0]['homeScore'],2)
                # Country flags are part of the same participant identity contract.
                self.assertIn('flagcdn.com/w80/es.png',saved['events'][0]['awayTeam']['logo'])
                self.assertIn('flagcdn.com/w80/ar.png',saved['events'][0]['homeTeam']['logo'])
            finally:
                cb._STORE,cb._CATALOG_REVISION=old_store,old_rev

    def test_custom_playback_uses_string_names_while_preserving_rich_team_objects(self):
        front=(ROOT/'architecture/competition-builder.js').read_text(encoding='utf-8')
        back=(ROOT/'sbb/competition_builder.py').read_text(encoding='utf-8')
        for token in ("away:awayName,home:homeName","awayTeam,homeTeam","awayLogo:awayTeam.logo"):
            self.assertIn(token,front)
        for token in ('"away":away_name,"home":home_name','"awayTeam":away_team,"homeTeam":home_team','event=_decorate_event_artwork(comp,event)'):
            self.assertIn(token,back)

    def test_dev_mode_has_explicit_actual_results_repair(self):
        front=(ROOT/'architecture/competition-builder.js').read_text(encoding='utf-8')
        back=(ROOT/'sbb/competition_builder.py').read_text(encoding='utf-8')
        self.assertIn('REFRESH RESULTS',front)
        self.assertIn("action:'reconcile_results'",front)
        self.assertIn('action=="reconcile_results"',back)
        self.assertIn('reconcile_competition_results',back)
        self.assertIn('preserving canonical event IDs',back)

if __name__=='__main__':
    unittest.main()

import tempfile
from contextlib import closing
import unittest
from pathlib import Path

from sbb.history_repository import HistoryRepository


class SilverRoundupAuditTests(unittest.TestCase):
    def make_repo(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return HistoryRepository(Path(td.name)/'history.sqlite3')

    def test_silver_audit_surfaces_legacy_duplicates_scope_leaks_and_large_collections(self):
        repo=self.make_repo()
        shared={
            'provider':'YOUTUBE','youtubeId':'shared-roundup','url':'https://www.youtube.com/watch?v=shared-roundup',
            'title':"NBA's Nightly Recap | August 20, 2026",'durationSeconds':1200,'date':'2026-08-20','league':'NBA',
            'channelId':'UCWJ2lWNubArHWmf3FIHbfcQ','publishedAt':'2026-08-20T23:00:00Z','validationState':'VERIFIED',
        }
        self.assertEqual(repo.put_collection_media('DAY_LEAGUE','NBA','2026-08-20',[shared],collection_kind='DAILY_RECAP'),1)
        shared_asset=repo.roundup_media('2026-08-20','NBA')[0]['assetKey']

        # Inject a pre-v5 legacy smear so the audit can still surface/forensically
        # explain bad relationship state even though put_collection_media now prevents it.
        now=1.0; duplicate_key=repo._collection_key('DAY_LEAGUE','NBA','2026-08-21','DAILY_RECAP')
        with repo._lock, closing(repo._connect()) as conn:
            conn.execute("INSERT INTO history_collection(collection_key,scope,league,period_key,collection_kind,title,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (duplicate_key,'DAY_LEAGUE','NBA','2026-08-21','DAILY_RECAP','legacy duplicate','{}',now,now))
            conn.execute("INSERT INTO history_collection_media(collection_key,asset_key,association_confidence,association_method,association_evidence,classifier_version,rank_hint,first_associated_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (duplicate_key,shared_asset,0.99,'LEGACY_TEST','legacy smear',4,1,now,now))
            conn.commit()

        # Simulate a legacy GAME-scope leak directly; strict v5 routing would reject it.
        leak={
            'provider':'YOUTUBE','youtubeId':'game-like','url':'https://www.youtube.com/watch?v=game-like',
            'title':'Lakers at Bulls Full Game Highlights','durationSeconds':900,'date':'2026-08-20','league':'NBA',
            'mediaScope':'GAME','mediaScopeConfidence':0.95,'mediaScopeReason':'MATCHUP_TITLE','intent':'EXTENDED_HIGHLIGHT','validationState':'CANDIDATE',
        }
        repo.put_source_media([leak],league='NBA',date='2026-08-20')
        leak_asset=repo.asset_key_for(leak); day20_key=repo._collection_key('DAY_LEAGUE','NBA','2026-08-20','DAILY_RECAP')
        with repo._lock, closing(repo._connect()) as conn:
            conn.execute("UPDATE history_source_media SET scope='GAME' WHERE asset_key=?",(leak_asset,))
            conn.execute("INSERT INTO history_collection_media(collection_key,asset_key,association_confidence,association_method,association_evidence,classifier_version,rank_hint,first_associated_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (day20_key,leak_asset,0.99,'LEGACY_TEST','game leak',4,1,now,now))
            conn.commit()

        # Oversized collection remains an audit condition even though all 21 rows are
        # individually valid official league-wide Top Plays programs.
        big=[]
        for i in range(21):
            big.append({'provider':'YOUTUBE','youtubeId':f'big-{i}','url':f'https://youtu.be/big-{i}',
                'title':f'NBA Top 10 Plays of the Night | August 22, 2026 - Edition {i}',
                'publishedAt':'2026-08-22T23:00:00Z','channelId':'UCWJ2lWNubArHWmf3FIHbfcQ','date':'2026-08-22','league':'NBA'})
        self.assertEqual(repo.put_collection_media('DAY_LEAGUE','NBA','2026-08-22',big,collection_kind='TOP_PLAYS'),21)

        result=repo.collection_audit(league='NBA',limit=1000)
        self.assertEqual(result['summary']['dayCollections'],3)
        self.assertGreaterEqual(result['summary']['multiCollectionAssets'],1)
        self.assertGreaterEqual(result['summary']['duplicateAssets'],1)
        self.assertGreaterEqual(result['summary']['gameScopeLinks'],1)
        self.assertEqual(result['summary']['largeCollections'],1)
        self.assertGreaterEqual(result['summary']['suspiciousLinks'],3)
        self.assertIn('DAILY_RECAP',result['facets']['collectionKinds'])
        self.assertIn('TOP_PLAYS',result['facets']['collectionKinds'])

        multi=repo.collection_audit(flag='MULTI_COLLECTION_ASSET',limit=100)
        self.assertGreaterEqual(multi['total'],2)
        self.assertTrue(all('MULTI_COLLECTION_ASSET' in row['flags'] for row in multi['rows']))

        dup=repo.collection_audit(flag='DUPLICATE_ACROSS_PERIODS',limit=100)
        self.assertGreaterEqual(dup['total'],2)
        self.assertTrue(all('DUPLICATE_ACROSS_PERIODS' in row['flags'] for row in dup['rows']))

        leaked=repo.collection_audit(flag='GAME_SCOPE_ASSET',limit=100)
        self.assertEqual(leaked['total'],1)
        self.assertIn('GAME_SCOPE_ASSET',leaked['rows'][0]['flags'])

        large=repo.collection_audit(flag='LARGE_COLLECTION',limit=100)
        self.assertEqual(large['total'],21)
        self.assertTrue(all(row['collectionAssetCount']==21 for row in large['rows']))

    def test_v415_collection_repair_rekeys_season_week_and_collapses_daily_smear(self):
        repo=self.make_repo(); now=1.0
        weekly={'provider':'YOUTUBE','youtubeId':'nba-week24','title':'The TOP Plays of Week 24 | 2025-26 NBA Season',
                'channelId':'UCWJ2lWNubArHWmf3FIHbfcQ','publishedAt':'2026-04-03T12:00:00Z','date':'2026-04-03','league':'NBA'}
        daily={'provider':'YOUTUBE','youtubeId':'mlb-all-games','title':'Highlights from ALL GAMES on 8/21',
               'channelId':'UCoLrcjPV5PbUrUyXq5mjc_A','publishedAt':'2026-08-22T05:00:00Z','date':'2026-08-23','league':'MLB'}
        repo.put_source_media([weekly],league='NBA',date='2026-04-03')
        repo.put_source_media([daily],league='MLB',date='2026-08-23')
        weekly_key=repo.asset_key_for(weekly); daily_key=repo.asset_key_for(daily)
        with repo._lock, closing(repo._connect()) as conn:
            legacy=[
                ('WEEK_LEAGUE:NBA:2026:W24:TOP_PLAYS','WEEK_LEAGUE','NBA','2026:W24','TOP_PLAYS',weekly_key),
                ('DAY_LEAGUE:MLB:2026-08-22:DAILY_RECAP','DAY_LEAGUE','MLB','2026-08-22','DAILY_RECAP',daily_key),
                ('DAY_LEAGUE:MLB:2026-08-23:DAILY_RECAP','DAY_LEAGUE','MLB','2026-08-23','DAILY_RECAP',daily_key),
            ]
            for ckey,scope,league,period,kind,asset in legacy:
                conn.execute("INSERT INTO history_collection(collection_key,scope,league,period_key,collection_kind,title,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                             (ckey,scope,league,period,kind,'legacy','{}',now,now))
                conn.execute("INSERT INTO history_collection_media(collection_key,asset_key,association_confidence,association_method,association_evidence,classifier_version,rank_hint,first_associated_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                             (ckey,asset,0.97,'LEGACY','legacy',4,1,now,now))
            conn.commit()
        result=repo.repair_collection_associations(force=True)
        self.assertEqual(result['keptAssets'],2)
        audit=repo.collection_audit(limit=1000)
        keys={r['collectionKey'] for r in audit['rows']}
        self.assertIn('WEEK_LEAGUE:NBA:2025-26:W24:TOP_PLAYS',keys)
        self.assertIn('DAY_LEAGUE:MLB:2026-08-21:DAILY_RECAP',keys)
        self.assertNotIn('WEEK_LEAGUE:NBA:2026:W24:TOP_PLAYS',keys)
        mlb=[r for r in audit['rows'] if r['assetKey']==daily_key]
        self.assertEqual(len(mlb),1); self.assertEqual(mlb[0]['periodKey'],'2026-08-21')
        self.assertEqual(audit['summary']['duplicateAssets'],0)

    def test_silver_audit_ui_contract_exists(self):
        root=Path(__file__).resolve().parents[1]
        html=(root/'index.html').read_text(encoding='utf-8')
        js=(root/'ui/history-audit.js').read_text(encoding='utf-8')
        self.assertIn('id="historyAuditTabSilver"',html)
        self.assertIn('id="historySilverTableBody"',html)
        self.assertIn('id="historySilverFlag"',html)
        self.assertIn('/api/history/catalog/collections?',js)
        self.assertIn('renderSilverSummary',js)
        self.assertIn('DUPLICATE_ACROSS_PERIODS',html)
        self.assertIn('id="historySilverCsv"',html)
        self.assertIn('id="historySilverXlsx"',html)
        self.assertIn('function exportSilverFile(ext)',js)
        self.assertIn('/api/history/catalog/collections.${ext}',js)
        self.assertIn("$('historySilverCsv')?.addEventListener('click',()=>exportSilverFile('csv'))",js)

    def test_silver_export_contract_is_full_and_distinct_from_game_export(self):
        root=Path(__file__).resolve().parents[1]
        server=(root/'server.py').read_text(encoding='utf-8')
        self.assertIn("sports-big-board-silver-audit-{stamp}.csv",server)
        self.assertIn("return ['Audit View','Period','Season ID','Season Week','Round Type','Round Number','Scope','League','Collection Kind','Collection Key','Collection Title'",server)
        self.assertIn("'Provider','Source Authority','Source Authority Reason','Duration Seconds','Published At','URL','Validation','Runtime','Catalog State','Quarantine Reason'",server)
        self.assertIn("'Intent Confidence','Intent Reason','Association Confidence','Association Method','Association Evidence'",server)
        self.assertIn("'Asset Link Count','Asset Period Count','Asset Scope Count','Flags'",server)
        self.assertIn("'Audit View':'SILVER ROUNDUPS'",server)


if __name__=='__main__':
    unittest.main()

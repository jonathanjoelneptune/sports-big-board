import tempfile
import unittest
from pathlib import Path

from sbb.history_repository import HistoryRepository


class SilverRoundupAuditTests(unittest.TestCase):
    def make_repo(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return HistoryRepository(Path(td.name)/'history.sqlite3')

    def test_silver_audit_surfaces_duplicates_scope_leaks_and_large_collections(self):
        repo=self.make_repo()
        shared={
            'provider':'youtube','youtubeId':'shared-roundup','url':'https://www.youtube.com/watch?v=shared-roundup',
            'title':'NBA Nightly Recap','durationSeconds':1200,'date':'2026-08-20','league':'NBA',
            'mediaScope':'DAY_LEAGUE','mediaScopeConfidence':0.99,'mediaScopeReason':'DAILY_ROUNDUP_LANGUAGE',
            'intent':'RECAP','validationState':'VERIFIED',
        }
        repo.put_collection_media('DAY_LEAGUE','NBA','2026-08-20',[shared],collection_kind='DAILY_RECAP')
        repo.put_collection_media('DAY_LEAGUE','NBA','2026-08-21',[dict(shared,date='2026-08-21')],collection_kind='DAILY_RECAP')
        # Explicit collection routing keeps the asset in Silver even if its source scope
        # says GAME; the audit must flag the relationship rather than contaminate games.
        leak={
            'provider':'youtube','youtubeId':'game-like','url':'https://www.youtube.com/watch?v=game-like',
            'title':'Lakers at Bulls Full Game Highlights','durationSeconds':900,'date':'2026-08-20','league':'NBA',
            'mediaScope':'GAME','mediaScopeConfidence':0.95,'mediaScopeReason':'MATCHUP_TITLE',
            'intent':'EXTENDED_HIGHLIGHT','validationState':'CANDIDATE',
        }
        repo.put_collection_media('DAY_LEAGUE','NBA','2026-08-20',[leak],collection_kind='DAILY_RECAP')
        # Simulate a legacy/pre-repair leak in source classification so the audit can
        # prove it is visible without changing any event-media relationship.
        with repo._lock, repo._connect() as conn:
            conn.execute("UPDATE history_source_media SET scope='GAME' WHERE provider_media_id='game-like'")
            conn.commit()
        # Create a deliberately oversized collection to exercise the suspicious flag.
        big=[]
        for i in range(21):
            big.append({'provider':'youtube','youtubeId':f'big-{i}','url':f'https://youtu.be/big-{i}','title':f'NBA Top Play {i}','date':'2026-08-22','league':'NBA','mediaScope':'DAY_LEAGUE','mediaScopeConfidence':1.0,'mediaScopeReason':'TOP_PLAYS_LANGUAGE','intent':'TOP_PLAYS'})
        repo.put_collection_media('DAY_LEAGUE','NBA','2026-08-22',big,collection_kind='TOP_PLAYS')

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
        self.assertIn("'Audit View','Period','Scope','League','Collection Kind','Collection Key','Collection Title'",server)
        self.assertIn("'Published At','URL','Validation','Runtime','Catalog State','Quarantine Reason'",server)
        self.assertIn("'Intent Confidence','Intent Reason','Association Confidence','Association Method','Association Evidence'",server)
        self.assertIn("'Asset Link Count','Asset Period Count','Asset Scope Count','Flags'",server)
        self.assertIn("'Audit View':'SILVER ROUNDUPS'",server)


if __name__=='__main__':
    unittest.main()

import tempfile,unittest,sqlite3,json
from pathlib import Path
from sbb.playback_readiness import PlaybackReadinessStore

class V441PlaybackReadinessDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=PlaybackReadinessStore(Path(self.tmp.name)/'ready.sqlite3')
    def tearDown(self): self.tmp.cleanup()
    def session(self,key='direct:https://cdn.test/a.mp4',league='NHL',**kw):
        d={'mediaKey':key,'eventKey':f'{league}:1','league':league,'provider':'DIRECT_VIDEO','transport':'DIRECT_VIDEO','sourceUrl':key.removeprefix('direct:')};d.update(kw);return d
    def test_stall_duration_accumulates_across_multiple_buffer_sessions(self):
        s=self.session();self.store.record('selection',s);self.store.record('first-frame',{**s,'firstFrameMs':300})
        self.store.record('stall',s);self.store.record('stall-end',{**s,'lastStallMs':1200})
        self.store.record('stall',s);self.store.record('stall-end',{**s,'lastStallMs':2400})
        row=self.store.get(s['mediaKey']);self.assertEqual(row['stalls'],2);self.assertEqual(row['total_stall_ms'],3600);self.assertEqual(row['last_stall_ms'],2400)
    def test_summary_exposes_records_for_cross_device_hydration(self):
        for league in ('MLB','NFL','NBA','NHL','EPL','MLS'):
            s=self.session(f'direct:https://cdn.test/{league}.mp4',league);self.store.record('selection',s);self.store.record('hot-ready',{**s,'warmReadyMs':250})
        summary=self.store.summary(limit=100);self.assertEqual(summary['schemaVersion'],2);self.assertGreaterEqual(len(summary['records']),6)
        self.assertTrue(all('reliability_score' in r and 'competition_id' in r for r in summary['records']))
    def test_network_suspect_warm_failure_is_small_penalty(self):
        s=self.session();self.store.record('selection',s);before=self.store.get(s['mediaKey'])['reliability_score'];self.store.record('warm-failure',{**s,'networkSuspect':True,'lastError':'client network pressure'});after=self.store.get(s['mediaKey'])['reliability_score'];self.assertGreaterEqual(after,before-2)
    def test_existing_history_runtime_truth_seeds_new_readiness_database(self):
        other=tempfile.TemporaryDirectory()
        try:
            parent=Path(other.name);hist=parent/'history.sqlite3';conn=sqlite3.connect(hist)
            conn.execute("CREATE TABLE history_source_media(asset_json TEXT,provider TEXT,runtime_state TEXT,runtime_success_at REAL,runtime_failure_at REAL,runtime_failure_reason TEXT,updated_at REAL)")
            conn.execute("INSERT INTO history_source_media VALUES(?,?,?,?,?,?,?)",(json.dumps({'youtubeId':'seedgood123','league':'NFL','provider':'YOUTUBE'}),'YOUTUBE','PLAYED',100,0,'',100))
            conn.execute("INSERT INTO history_source_media VALUES(?,?,?,?,?,?,?)",(json.dumps({'mediaUrl':'https://cdn.test/seedbad.mp4','league':'NBA','provider':'ESPN'}),'ESPN','FAILED',0,110,'decoder failed',110));conn.commit();conn.close()
            seeded=PlaybackReadinessStore(parent/'playback-readiness.sqlite3')
            self.assertEqual(seeded.get('youtube:seedgood123')['state'],'VERIFIED')
            bad=seeded.get('direct:https://cdn.test/seedbad.mp4');self.assertEqual(bad['state'],'DEGRADED');self.assertGreaterEqual(bad['failures'],1)
        finally: other.cleanup()

if __name__=='__main__':unittest.main()

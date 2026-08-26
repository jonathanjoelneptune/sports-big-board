import threading
import time
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class V421RepositoryReadIsolationTests(unittest.TestCase):
    def test_operator_summary_and_integrity_do_not_wait_on_python_writer_lock(self):
        from sbb.history_repository import HistoryRepository
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite')
            repo.put_scores('2026-08-25','MLB',[{'id':'1'}])
            done=[]
            def read():
                done.append(repo.summary(include_integrity=False))
            with repo._lock:
                t=threading.Thread(target=read); t.start(); t.join(1.0)
                self.assertFalse(t.is_alive(),'compact summary still waits on process-wide writer lock')
            self.assertEqual(done[0]['leagueDays'],1)

    def test_hot_operator_repository_methods_use_query_only_connections(self):
        import inspect
        from sbb.history_repository import HistoryRepository
        for name in ('summary','catalog_integrity','green_gap_summary','association_integrity_summary','active_event_claims','silver_summary','media_objective_summary','silver_identity_audit','source_enrichment_summary','database_audit_batch'):
            src=inspect.getsource(getattr(HistoryRepository,name))
            self.assertIn('_read_connect()',src,name)
            self.assertNotIn('with self._lock',src,name)

    def test_date_discovery_state_bulk_map_removes_event_n_plus_one(self):
        repo=(ROOT/'sbb'/'history_repository.py').read_text(encoding='utf-8')
        server=(ROOT/'server.py').read_text(encoding='utf-8')
        self.assertIn('def event_state_map_for_date',repo)
        self.assertIn('event_state_map=HISTORY_REPOSITORY.event_state_map_for_date(date)',server)
        inventory=server[server.index('def _history_inventory(date):'):server.index('def _history_discovery_state(date):')]
        self.assertNotIn('HISTORY_REPOSITORY.get_event(',inventory)


class V421BackgroundCoordinationTests(unittest.TestCase):
    def test_schedule_sync_startup_is_bounded_and_heartbeats_each_step(self):
        import server
        original_get=server._history_get_league_scores
        original_beat=server._history_worker_beat
        calls=[]; beats=[]
        try:
            server._history_get_league_scores=lambda date,league,*args,**kwargs:(calls.append((date,league)) or ([], 'TEST', True, ''))
            server._history_worker_beat=lambda worker,phase=None,current=None,progress=False,blocked=False: beats.append((worker,phase,current,progress))
            state=server._history_schedule_sync_once(startup_fast=True,worker='schedule-sync-test')
            self.assertEqual(len(calls),4*len(server.HISTORY_LEAGUES))
            self.assertEqual(state['totalSteps'],len(calls))
            self.assertEqual(state['completedSteps'],len(calls))
            self.assertGreaterEqual(len(beats),len(calls)*2)
            self.assertTrue(any(b[2] and ' ' in b[2] for b in beats))
        finally:
            server._history_get_league_scores=original_get
            server._history_worker_beat=original_beat

    def test_operator_snapshot_is_staggered_and_includes_cached_diagnostics(self):
        server=(ROOT/'server.py').read_text(encoding='utf-8')
        block=server[server.index('def history_operator_snapshot_worker():'):server.index('def history_database_audit_worker():')]
        for token in ("('eventClaims',5", "('dbSummary',15", "('greenGapQueue',60", "('mediaObjectives',120", "('catalogIntegrity',120", "componentTimings", "componentGeneratedAt"):
            self.assertIn(token,block)
        self.assertNotIn("payload={",block)
        self.assertIn("HISTORY_REPOSITORY.summary(include_integrity=False)",block)

    def test_program_rank_request_returns_before_background_ai_finishes(self):
        import server
        original_rank=server._openai_program_rank
        original_key=server.read_openai_key
        try:
            with server.PROGRAM_RANK_LOCK:
                server.PROGRAM_RANK_CACHE.clear(); server.PROGRAM_RANK_INFLIGHT.clear()
            server.read_openai_key=lambda:'test-key'
            def slow_rank(*args,**kwargs):
                time.sleep(0.25); return [{'id':'a','score':99,'reason':'test','playType':'game'}]
            server._openai_program_rank=slow_rank
            started=time.perf_counter()
            result=server._program_rank_cached_or_schedule('queue',[{'id':'a'}],[],'2026-08-25')
            elapsed=time.perf_counter()-started
            self.assertLess(elapsed,0.12)
            self.assertTrue(result['pending'])
            deadline=time.time()+2
            while time.time()<deadline:
                with server.PROGRAM_RANK_LOCK:
                    if not server.PROGRAM_RANK_INFLIGHT: break
                time.sleep(0.02)
            with server.PROGRAM_RANK_LOCK: self.assertFalse(server.PROGRAM_RANK_INFLIGHT)
        finally:
            server._openai_program_rank=original_rank
            server.read_openai_key=original_key


class V421DiagnosticsTests(unittest.TestCase):
    def test_scheduler_categorizes_failures(self):
        from sbb.media_work_scheduler import MediaWorkScheduler, PRIORITY
        q=MediaWorkScheduler(workers=1,name='test-error-category')
        fut=q.submit('game-center:test',PRIORITY['BACKGROUND_DISCOVERY'],lambda:(_ for _ in ()).throw(TimeoutError('provider timed out')))
        with self.assertRaises(TimeoutError): fut.result(timeout=2)
        snap=q.snapshot()
        self.assertEqual(snap['stats']['errorCategories'].get('timeout'),1)
        self.assertEqual(snap['recentErrors'][-1]['category'],'timeout')

    def test_stress_playback_uses_desired_state_not_toggle_sequencing(self):
        app=(ROOT/'app.js').read_text(encoding='utf-8')
        stress=(ROOT/'architecture'/'milestone-console.js').read_text(encoding='utf-8')
        self.assertIn('ensurePlaying:()=>devStressEnsurePlaying()',app)
        self.assertIn('ensurePaused:()=>devStressEnsurePaused()',app)
        block=stress[stress.index("await step('playback: pause/resume ownership'"):stress.index("await step('playback: next clip transition'")]
        self.assertIn('h.ensurePlaying?.()',block)
        self.assertIn('h.ensurePaused?.()',block)
        self.assertNotIn('h.playPause()',block)

    def test_hot_endpoints_do_not_nest_full_repository_integrity(self):
        server=(ROOT/'server.py').read_text(encoding='utf-8')
        self.assertIn("HISTORY_REPOSITORY.summary(include_integrity=False)",server)
        discovery=server[server.index('if parsed.path == "/api/history/discovery":'):server.index('if parsed.path == "/api/history/admin/recovery":')]
        self.assertNotIn('catalog_integrity()',discovery)
        milestone=server[server.index('def _milestone_release_snapshot'):server.index('class Handler')]
        self.assertNotIn('HISTORY_REPOSITORY.catalog_integrity()',milestone)
        self.assertIn("operator.get('dbSummary')",milestone)
        self.assertIn("OPERATOR_COMPONENT_ERROR",milestone)


if __name__=='__main__':
    unittest.main()

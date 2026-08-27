import threading, time, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()

class MilestoneConsoleUnitTests(unittest.TestCase):
    def test_bounded_console_tracks_api_playback_and_errors(self):
        from sbb.milestone_console import MilestoneConsole
        c=MilestoneConsole(VERSION,max_events=220)
        c.record_endpoint('/api/history/ribbon',123.4,200)
        c.record_endpoint('/api/history/audit',6001,200)
        c.record_endpoint('/api/test',41,500,'boom')
        c.record_playback('selection',{'sessionId':'s1','state':'selected','eventKey':'MLB:1','mediaKey':'m1','invariant':'OK'})
        c.record_playback('first-frame',{'sessionId':'s1','state':'playing','firstFrameMs':212,'invariant':'OK'})
        c.record_playback('stall',{'sessionId':'s1','state':'buffering','stallCount':1,'invariant':'OK'})
        c.record_playback('stall-end',{'sessionId':'s1','state':'playing','lastStallMs':845,'invariant':'OK'})
        snap=c.snapshot(frontend_version=VERSION)
        self.assertTrue(snap['versionMatch'])
        self.assertEqual(snap['playback']['firstFrame']['p50Ms'],212.0)
        self.assertEqual(snap['playback']['stallDuration']['p50Ms'],845.0)
        self.assertEqual(snap['api']['/api/test']['errors'],1)
        self.assertTrue(any(x['level']=='ERROR' for x in snap['recent']))

    def test_media_work_scheduler_reuses_same_or_higher_priority_job(self):
        from sbb.media_work_scheduler import MediaWorkScheduler, PRIORITY
        gate=threading.Event(); started=threading.Event(); runs=[]
        def work():
            runs.append(time.time()); started.set(); gate.wait(2); return 'done'
        q=MediaWorkScheduler(workers=1,name='test-dedupe')
        first=q.submit('same-source:day',PRIORITY['VISIBLE_SCORE'],work)
        self.assertTrue(started.wait(1))
        second=q.submit('same-source:day',PRIORITY['BACKGROUND_DISCOVERY'],work)
        self.assertIs(first,second)
        gate.set(); self.assertEqual(first.result(timeout=2),'done')
        snap=q.snapshot()
        self.assertEqual(len(runs),1)
        self.assertGreaterEqual(snap['stats']['reused'],1)
        self.assertEqual(snap['threadsAlive'],1)

    def test_media_work_scheduler_reuses_running_job_even_when_priority_increases(self):
        from sbb.media_work_scheduler import MediaWorkScheduler, PRIORITY
        gate=threading.Event(); started=threading.Event(); runs=[]
        def work():
            runs.append(time.time()); started.set(); gate.wait(2); return 'done'
        q=MediaWorkScheduler(workers=1,name='test-running-dedupe')
        first=q.submit('same-upstream-object',PRIORITY['BACKGROUND_DISCOVERY'],work)
        self.assertTrue(started.wait(1))
        promoted=q.submit('same-upstream-object',PRIORITY['TOUCH_INTENT'],work)
        self.assertIs(first,promoted)
        gate.set(); self.assertEqual(promoted.result(timeout=2),'done')
        self.assertEqual(len(runs),1)
        self.assertGreaterEqual(q.snapshot()['stats']['reused'],1)

class MilestoneReleaseContractTests(unittest.TestCase):
    def test_release_console_is_wired_front_and_backend(self):
        html=(ROOT/'index.html').read_text(encoding='utf-8')
        server=(ROOT/'server.py').read_text(encoding='utf-8')
        js=(ROOT/'architecture'/'milestone-console.js').read_text(encoding='utf-8')
        for token in ('openMilestoneConsoleBtn','milestoneConsoleModal',f'architecture/milestone-console.js?v={VERSION}','milestoneConsoleOutput'):
            self.assertIn(token,html)
        for token in ("'/api/playback/telemetry'","'/api/milestone/client-event'","'/api/milestone/reset'","'/api/milestone/console'",'_milestone_release_snapshot','MILESTONE_CONSOLE.record_endpoint'):
            self.assertIn(token,server)
        for token in ('unhandledrejection','browser heartbeat','COPY FULL LOG','/api/milestone/console?frontendVersion=','window.SBB_PLAYBACK_SESSION?.snapshot'):
            self.assertIn(token,js)

    def test_playback_session_is_loaded_before_soundtrack_and_app(self):
        html=(ROOT/'index.html').read_text(encoding='utf-8')
        ps=f'architecture/playback-session.js?v={VERSION}'; mc=f'architecture/milestone-console.js?v={VERSION}'; fc=f'architecture/foundation-certification.js?v={VERSION}'; st=f'architecture/site-soundtrack.js?v={VERSION}'; app=f'app.js?v={VERSION}'
        self.assertLess(html.index(ps),html.index(mc)); self.assertLess(html.index(mc),html.index(fc)); self.assertLess(html.index(fc),html.index(st)); self.assertLess(html.index(st),html.index(app))

    def test_version_is_single_backend_source_and_ci_checks_generation(self):
        server=(ROOT/'server.py').read_text(encoding='utf-8')
        verify=(ROOT/'VERIFY.sh').read_text(encoding='utf-8')
        checker=(ROOT/'tools'/'check_release_version.py').read_text(encoding='utf-8')
        self.assertIn('APP_VERSION = (ROOT / "VERSION").read_text',server)
        self.assertIn('tools/check_release_version.py',verify)
        self.assertIn('tools/check_foundation_certification.py',verify)
        self.assertIn('stale cache generation',checker)

    def test_milestone_console_has_stress_test_and_repeatable_procedures(self):
        html=(ROOT/'index.html').read_text(encoding='utf-8')
        js=(ROOT/'architecture'/'milestone-console.js').read_text(encoding='utf-8')
        app=(ROOT/'app.js').read_text(encoding='utf-8')
        for token in ('milestoneStressRun','RUN DEV STRESS TEST','milestoneStressStop','milestoneProceduresToggle','MILESTONE TEST PROCEDURES','milestoneProcedureList'):
            self.assertIn(token,html)
        for token in ('runStressTest','stopStressTest','runProcedure','release-handshake','playback-cycle','historical-read','operator-load','resource-modes','game-center','soundtrack','ui-responsiveness','DEV STRESS TEST STARTED','stress-step'):
            self.assertIn(token,js)
        for token in ('window.SBB_DEV_TEST_HOOKS','playPause:','nextClip:','stressTuneNext:','setScoreDate:','setResourceMode:','openGameCenter:','soundtrackToggle:'):
            self.assertIn(token,app)

    def test_stress_test_restores_user_visible_state_and_logs_failures(self):
        js=(ROOT/'architecture'/'milestone-console.js').read_text(encoding='utf-8')
        # v4.3.10 preserves the original v4.2 restoration objective while making
        # exact-state misses advisory.  Final application health, not a stale
        # implementation-string contract, decides whether cleanup blocks Tier 1.
        for token in (
            'original.resourceMode','original.scoreDate','original.drawer','original.soundtrackDev','original.mediaKey',
            'restoreMediaKey','soundtrackDevRestore','stressRun.restoration=[]','restoreAttempt',
            'restore staging resource mode','restore score date','restore exact media selection','restore drawer state',
            'restore soundtrack state','restore playback activity','restore original resource mode',
            'stressRun.restorationHealth','post-test restoration left application unhealthy',
            'post-test restoration completed with non-blocking advisories',
        ):
            self.assertIn(token,js)
        self.assertNotIn('restoreFailed',js)
        self.assertIn('timed out after ${timeoutMs} ms',js)
        self.assertIn('if(refreshPromise)return refreshPromise',js)
        self.assertNotIn('stressRun.completed=stressRun.steps.length',js)
        self.assertIn("post('stress-step'",js)
        self.assertIn("post('stress-restore'",js)
        self.assertIn("post('stress','ERROR'",js)

    def test_sqlite_utility_connections_are_explicitly_closed(self):
        rebuild=(ROOT/'sbb'/'history_rebuild.py').read_text(encoding='utf-8')
        ensure=(ROOT/'tools'/'ensure_history_v4.py').read_text(encoding='utf-8')
        backup=(ROOT/'cloud'/'vm'/'backup_state.py').read_text(encoding='utf-8')
        self.assertIn('closing(sqlite3.connect(source))',rebuild)
        self.assertIn('closing(sqlite3.connect(path))',ensure)
        self.assertIn('closing(sqlite3.connect(src))',backup)

    def test_stress_resource_mode_changes_backend_and_restores_awaited(self):
        app=(ROOT/'app.js').read_text(encoding='utf-8')
        js=(ROOT/'architecture'/'milestone-console.js').read_text(encoding='utf-8')
        self.assertIn("fetch('/api/history/work-mode'",app)
        self.assertIn('await h.setResourceMode(mode)',js)
        self.assertIn('await h.stressTuneNext()',js)
        self.assertIn("await h.setResourceMode('balanced')",js)
        self.assertIn('await h.setResourceMode(original.resourceMode)',js)

    def test_worker_health_snapshot_is_lock_protected(self):
        server=(ROOT/'server.py').read_text(encoding='utf-8')
        self.assertIn('HISTORY_WORKER_HEALTH_LOCK = threading.RLock()',server)
        self.assertIn('with HISTORY_WORKER_HEALTH_LOCK: workers=copy.deepcopy(HISTORY_WORKER_HEALTH)',server)
        self.assertIn('\"rule-collections\":',server)

    def test_verify_fails_on_resource_warning_and_soundtrack_singleton_is_version_independent(self):
        verify=(ROOT/'VERIFY.sh').read_text(encoding='utf-8')
        soundtrack=(ROOT/'architecture'/'site-soundtrack.js').read_text(encoding='utf-8')
        self.assertIn('PYTHONWARNINGS=always::ResourceWarning',verify)
        self.assertIn("grep -Fq 'ResourceWarning'",verify)
        self.assertIn("const RUNTIME_KEY='__SBB_SOUNDTRACK_SINGLETON__'",soundtrack)
        self.assertNotIn('__SBB_SOUNDTRACK_SINGLETON_V132__',soundtrack)

    def test_player_debug_includes_openable_video_source(self):
        html=(ROOT/'index.html').read_text(encoding='utf-8'); app=(ROOT/'app.js').read_text(encoding='utf-8')
        self.assertIn('VIDEO SOURCE LINK',html); self.assertIn('diagSourceLink',html)
        self.assertIn('https://www.youtube.com/watch?v=',app); self.assertIn('playbackExternalSourceUrl',app)

if __name__=='__main__': unittest.main()

import time
import unittest
from pathlib import Path
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]


class V422UiIsolationTests(unittest.TestCase):
    def test_milestone_modal_visually_suppresses_info_drawer_without_closing_it(self):
        js=(ROOT/'architecture'/'milestone-console.js').read_text(encoding='utf-8')
        css=(ROOT/'styles.css').read_text(encoding='utf-8')
        self.assertIn("document.body.classList.add('sbb-milestone-open')",js)
        self.assertIn("document.body.classList.remove('sbb-milestone-open')",js)
        self.assertIn('.sbb-milestone-open #infoDrawer',css)
        self.assertIn('visibility:hidden!important',css)
        open_block=js[js.index('function open(){'):js.index('function close(){')]
        self.assertNotIn('SBB_INFO_DRAWER?.close',open_block)

    def test_stress_separates_streaming_health_from_ownership(self):
        js=(ROOT/'architecture'/'milestone-console.js').read_text(encoding='utf-8')
        self.assertIn("await step('playback: buffering health'",js)
        # v4.3.5+ verifies bounded recovery rather than pinning the old v4.2.2
        # 12-second failure string. The streaming-health step may evolve, but it
        # must remain separate from pause/resume ownership and must prove that a
        # stalled asset either settles or fails over within a bounded interval.
        buffering=js[js.index("await step('playback: buffering health'"):js.index("await step('playback: pause/resume ownership'")]
        self.assertIn("label:'bounded buffering recovery'",buffering)
        self.assertIn('timeoutMs:20000',buffering)
        self.assertIn('recoveredByFailover:',buffering)
        self.assertIn('buffering did not recover within 20000 ms',buffering)
        block=js[js.index("await step('playback: pause/resume ownership'"):js.index("await step('playback: next clip transition'")]
        self.assertIn('h.ensurePaused?.()',block)
        self.assertIn('h.ensurePlaying?.()',block)
        self.assertNotIn('transient playback settle',block)


class V422PlaybackPriorityTests(unittest.TestCase):
    def test_stall_telemetry_creates_background_cache_pressure(self):
        import server
        with server.MEDIA_FILE_CACHE_LOCK:
            old=dict(server.MEDIA_PLAYBACK_PRESSURE)
            server.MEDIA_PLAYBACK_PRESSURE.update({'until':0.0,'lastEvent':'','lastAt':0.0,'mediaKey':''})
        try:
            server._media_note_playback_pressure('stall',{'state':'buffering','mediaKey':'direct:test'})
            with server.MEDIA_FILE_CACHE_LOCK:
                self.assertGreater(server.MEDIA_PLAYBACK_PRESSURE['until'],time.time()+10)
                self.assertEqual(server.MEDIA_PLAYBACK_PRESSURE['lastEvent'],'stall')
            self.assertTrue(server._media_foreground_busy())
        finally:
            with server.MEDIA_FILE_CACHE_LOCK: server.MEDIA_PLAYBACK_PRESSURE.update(old)

    def test_full_cache_worker_has_hard_yield_path(self):
        src=(ROOT/'server.py').read_text(encoding='utf-8')
        block=src[src.index('def _media_cache_download_full'):src.index('def _schedule_media_cache_full')]
        self.assertIn('DEFERRED_FOR_PLAYBACK',block)
        self.assertIn('YIELDED_TO_PLAYBACK',block)
        self.assertIn('_media_foreground_busy()',block)
        self.assertNotIn('if foreground_busy: time.sleep(0.06)',block)


class V422WorkerHealthTests(unittest.TestCase):
    def test_schedule_sync_sleep_is_phase_aware(self):
        import server
        now=time.time()
        st={'heartbeat':now-490,'phase':'sleeping'}
        self.assertTrue(server._history_worker_health_status('schedule-sync',st,now))
        self.assertFalse(server._history_worker_health_status('green-gap-1',st,now))

    def test_schedule_sync_renews_heartbeat_during_sleep(self):
        src=(ROOT/'server.py').read_text(encoding='utf-8')
        block=src[src.index('def history_schedule_sync_worker():'):src.index('def _game_media_source_registry():')]
        self.assertIn("_history_worker_beat('schedule-sync',phase='sleeping'",block)
        self.assertIn('wake=time.time()+HISTORY_SCHEDULE_SYNC_INTERVAL',block)


class V422GameCenterBoundaryTests(unittest.TestCase):
    def test_collection_media_cannot_become_selected_game(self):
        app=(ROOT/'app.js').read_text(encoding='utf-8')
        tune=app[app.index('const PlaybackController='):app.index('window.SBB_PLAYBACK_CONTROLLER=PlaybackController')]
        self.assertIn('const collectionScoped=!!window.SBB_MEDIA_SCOPE?.isCollection?.(item)',tune)
        self.assertIn("collection media has no Game Center event",tune)
        contract=(ROOT/'architecture'/'game-center-contract.js').read_text(encoding='utf-8')
        self.assertIn("Game Center is unavailable for collection/roundup media",contract)

    def test_provider_429_creates_exponential_cooldown_and_blocks_background(self):
        import server
        with server.GAME_CENTER_PROVIDER_HEALTH_LOCK:
            old=dict(server.GAME_CENTER_PROVIDER_HEALTH); server.GAME_CENTER_PROVIDER_HEALTH.clear()
        try:
            exc=HTTPError('https://site.api.espn.com/test',429,'Too Many Requests',{},None)
            retry=server._game_center_provider_note_failure('MLB',exc,{'provider':'espn'})
            self.assertGreater(retry,time.time())
            remain,state=server._game_center_background_cooldown('MLB')
            self.assertGreater(remain,0)
            self.assertEqual(state.get('provider'),'espn')
            fut=server.schedule_game_center_prepare('MLB','825042',server.MEDIA_PRIORITY['BACKGROUND_DISCOVERY'],hints={'provider':'espn'})
            self.assertIsNone(fut)
        finally:
            with server.GAME_CENTER_PROVIDER_HEALTH_LOCK:
                server.GAME_CENTER_PROVIDER_HEALTH.clear(); server.GAME_CENTER_PROVIDER_HEALTH.update(old)

    def test_coverage_is_throttled_and_skips_highlightly_when_official_exists(self):
        src=(ROOT/'server.py').read_text(encoding='utf-8')
        block=src[src.index('def _game_center_coverage_pass'):src.index('def game_center_startup_prewarm_worker')]
        self.assertIn('OFFICIAL_COVERAGE_AVAILABLE',block)
        self.assertIn('time.time()-last<300',block)
        self.assertIn('time.sleep(5*60)',block)


class V422HistoricalDayTests(unittest.TestCase):
    def test_browser_history_hydration_no_longer_calls_legacy_day_aggregate(self):
        app=(ROOT/'app.js').read_text(encoding='utf-8')
        block=app[app.index('async function hydrateScoreDateFromHistory'):app.index('function pumpHistoricalMediaSearchQueue')]
        self.assertNotIn('/api/history/day?',block)
        for token in ('/api/history/ribbon?','/api/history/roundups?','/api/history/discovery?'):
            self.assertIn(token,block)

    def test_legacy_day_endpoint_exposes_component_server_timing(self):
        src=(ROOT/'server.py').read_text(encoding='utf-8')
        block=src[src.index('if parsed.path == "/api/history/day":'):src.index('if parsed.path == "/api/history/roundups":')]
        for token in ('dayMs','scoresMs','plansMs','inventoryMs','discoveryMs','Server-Timing'):
            self.assertIn(token,block)
        self.assertIn("operator.get('dbSummary')",block)


if __name__=='__main__':
    unittest.main()

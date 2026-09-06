"""R20 playback probe stabilization and repair-evidence symmetry guards."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SERVICE=(ROOT/'media_audit_service.py').read_text(encoding='utf-8')
PROBE=(ROOT/'media-audit-probe.html').read_text(encoding='utf-8')
UI=(ROOT/'ui/media-audit-v550.js').read_text(encoding='utf-8')

class R20PlaybackEvidenceTests(unittest.TestCase):
    def test_generation_and_probe_identity(self):
        self.assertIn('R20-PLAYBACK-EVIDENCE-CORROBORATION',SERVICE)
        self.assertIn("PROBE_VERSION='5.5.0-r20'",PROBE)
        self.assertIn("R20-PLAYBACK-EVIDENCE-CORROBORATION",UI)

    def test_direct_probe_uses_bounded_progress_polling(self):
        self.assertIn('DIRECT_ADVANCE_WINDOW_MS=6500',PROBE)
        self.assertIn('ADVANCE_MIN_SECONDS=0.45',PROBE)
        self.assertIn("setInterval(()=>",PROBE)
        self.assertIn("video.addEventListener('waiting',kick)",PROBE)
        self.assertIn("video.addEventListener('stalled',kick)",PROBE)
        self.assertNotIn('await sleep(1400)',PROBE)

    def test_youtube_probe_polls_time_not_only_state_callback(self):
        self.assertIn('getCurrentTime',PROBE)
        self.assertIn('getPlayerState',PROBE)
        self.assertIn('getVideoLoadedFraction',PROBE)
        self.assertIn('YOUTUBE_START_TIMEOUT_MS=18000',PROBE)
        self.assertIn('YOUTUBE_ADVANCE_WINDOW_MS=8000',PROBE)
        self.assertIn('player.playVideo()',PROBE)

    def test_headless_chrome_disables_background_throttling(self):
        for token in ('--disable-background-timer-throttling','--disable-backgrounding-occluded-windows','--disable-renderer-backgrounding'):
            self.assertIn(token,SERVICE)
        self.assertNotIn('"--disable-background-networking"',SERVICE)

    def test_repair_retains_recent_positive_evidence_only_after_transient_failure(self):
        start=SERVICE.index("def _probe(self, job, asset, phase='CERTIFYING')")
        end=SERVICE.index("def _promote(self, job, asset, reason='')",start)
        block=SERVICE[start:end]
        self.assertIn('was_recent_playable=_recent_playable(asset)',block)
        self.assertIn('RECENT_PLAYBACK_RETAINED_REPAIR',block)
        self.assertIn('_transient_media_failure_reason(last_reason)',block)
        self.assertIn('_hard_media_failure_reason(last_reason)',block)
        self.assertIn('candidatesCorroborated',block)

    def test_retained_success_does_not_forge_fresh_record_probe(self):
        start=SERVICE.index("def _probe(self, job, asset, phase='CERTIFYING')")
        end=SERVICE.index("def _promote(self, job, asset, reason='')",start)
        block=SERVICE[start:end]
        retained=block[block.index('# R20 evidence symmetry:'):]
        self.assertIn("record_repair_candidate',repair_id,event_key,asset,retained",retained)
        self.assertNotIn("record_probe',source_run,event_key,asset,attempt,retained",retained)

    def test_promotion_evidence_distinguishes_corroboration(self):
        self.assertIn('def _promotion_evidence',SERVICE)
        self.assertIn('retained recent PLAYED evidence after transient',SERVICE)
        promote=SERVICE[SERVICE.index('def promote_repaired_candidate'):SERVICE.index('def _eligible_events')]
        self.assertIn('evidence=str(reason',promote)
        self.assertNotIn('certified PLAYING_TIME_ADVANCED and promoted',promote)

    def test_r20_requeues_waiting_jobs_once(self):
        seed=SERVICE[SERVICE.index('def seed_repair_queue'):SERVICE.index('def repair_summary')]
        self.assertIn('R20_PLAYBACK_EVIDENCE_CORROBORATION',seed)
        self.assertIn('R20 playback-evidence corroboration strategy upgrade: immediate one-time retry',seed)
        self.assertIn("state='PENDING'",seed)
        self.assertIn("state='WAITING_RETRY'",seed)

    def test_ui_exposes_retained_evidence_count(self):
        self.assertIn('candidatesCorroborated',UI)
        self.assertIn('retained-evidence',UI)

if __name__=='__main__':
    unittest.main()

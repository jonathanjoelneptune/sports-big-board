import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
MILESTONE=(ROOT/'architecture'/'milestone-console.js').read_text(encoding='utf-8')
CERT=(ROOT/'architecture'/'foundation-certification.js').read_text(encoding='utf-8')
APP=(ROOT/'app.js').read_text(encoding='utf-8')
MANIFEST=(ROOT/'foundation-certification.json').read_text(encoding='utf-8')


class V434SoakProgressHardeningTests(unittest.TestCase):
    def test_release_retains_v434_soak_closure_or_newer(self):
        self.assertGreaterEqual(tuple(map(int, VERSION.split('.'))), (4,3,4))

    def test_soak_requires_continuous_telemetry_not_wall_clock_only(self):
        for token in ('expectedSamples','minimumSamples','coverageRatio','sampledSpanMs','maxSampleGapMs','maxAllowedSampleGapMs'):
            self.assertIn(token, MILESTONE)
        self.assertIn('soak telemetry coverage too low', MILESTONE)
        self.assertIn('soak telemetry span too short', MILESTONE)
        self.assertIn('soak telemetry gap', MILESTONE)

    def test_soak_detects_stuck_playing_and_buffering(self):
        self.assertIn('playing without forward progress', MILESTONE)
        self.assertIn('sustained buffering', MILESTONE)
        self.assertIn('maxNoProgressMs', MILESTONE)
        self.assertIn('maxBufferingMs', MILESTONE)

    def test_soak_transitions_are_bounded(self):
        self.assertIn('withTimeout', MILESTONE)
        self.assertIn("'soak game transition'", MILESTONE)
        self.assertIn('transitionTimeouts', MILESTONE)
        self.assertIn('transitionWindows', MILESTONE)

    def test_tier2_certificate_surfaces_new_soak_gates(self):
        for token in ('tier2Evaluation','Tier 2 telemetry coverage','Tier 2 continuous observation span','Tier 2 maximum sample gap','Tier 2 playback forward progress','Tier 2 sustained buffering','Tier 2 bounded transitions'):
            self.assertIn(token, CERT)

    def test_unattended_decode_or_provider_failure_auto_skips(self):
        self.assertIn('SKIPPING UNAVAILABLE VIDEO', APP)
        self.assertIn('automatic playback failure recovery', APP)
        self.assertIn('AUTO_MEDIA_FAILURE_SKIP', APP)
        self.assertIn("if(!userInitiated)", APP)
        self.assertIn("tryScoreMediaFallback(failed,err?.message||'score playback failed'", APP)

    def test_manifest_records_soak_limits(self):
        for token in ('minimumTelemetryCoverageRatio','maximumSampleGapMs','maximumNoProgressMs','maximumBufferingMs','transitionTimeoutMs'):
            self.assertIn(token, MANIFEST)


if __name__=='__main__':
    unittest.main()

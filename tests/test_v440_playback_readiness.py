import os
import tempfile
import time
import unittest
from pathlib import Path

from sbb.playback_readiness import PlaybackReadinessStore


class V440PlaybackReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "readiness.sqlite3"
        self.store = PlaybackReadinessStore(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, key="direct:https://cdn.example/video.mp4", league="NFL", **extra):
        base = {
            "mediaKey": key,
            "eventKey": f"{league}:event:1",
            "league": league,
            "provider": "DIRECT_VIDEO",
            "transport": "DIRECT_VIDEO",
            "sourceUrl": key.removeprefix("direct:"),
            "firstFrameMs": 420,
        }
        base.update(extra)
        return base

    def test_cross_sport_hot_ready_is_persisted(self):
        for league in ("MLB", "NFL", "NBA", "NHL", "EPL", "MLS"):
            key=f"direct:https://cdn.example/{league.lower()}.mp4"
            self.store.record("selection", self.session(key, league))
            self.store.record("hot-ready", self.session(key, league, warmReadyMs=360))
            row=self.store.get(key)
            self.assertEqual(row["competition_id"],league)
            self.assertEqual(row["state"],"PLAYBACK_READY")
            self.assertGreaterEqual(row["reliability_score"],80)

    def test_one_failure_does_not_globally_quarantine_asset(self):
        s=self.session()
        self.store.record("selection",s);self.store.record("first-frame",s)
        self.store.record("failure",{**s,"lastError":"one bad Wi-Fi moment"})
        row=self.store.get(s["mediaKey"])
        self.assertNotEqual(row["state"],"QUARANTINED")
        self.assertEqual(row["consecutive_failures"],1)

    def test_repeated_failures_quarantine(self):
        s=self.session()
        for i in range(3):
            self.store.record("selection",s)
            self.store.record("failure",{**s,"lastError":f"failure {i}"})
        row=self.store.get(s["mediaKey"])
        self.assertEqual(row["state"],"QUARANTINED")
        self.assertGreater(row["quarantined_until"],time.time())

    def test_startup_percentiles_are_durable(self):
        s=self.session()
        for ms in (200,400,800,1200,2400):
            self.store.record("selection",s)
            self.store.record("first-frame",{**s,"firstFrameMs":ms})
        row=self.store.get(s["mediaKey"])
        self.assertEqual(row["startup_sample_count"],5)
        self.assertGreater(row["startup_p95_ms"],1000)
        self.assertGreaterEqual(row["startup_p50_ms"],400)

    def test_store_schema_is_provider_and_sport_neutral(self):
        s=self.session("youtube:abc123xyz00","EPL",provider="YOUTUBE",transport="YOUTUBE_EMBED",sourceUrl="abc123xyz00")
        self.store.record("selection",s);self.store.record("hot-ready",{**s,"warmReadyMs":700})
        row=self.store.get(s["mediaKey"])
        self.assertEqual(row["provider"],"YOUTUBE")
        self.assertEqual(row["transport"],"YOUTUBE_EMBED")
        self.assertEqual(row["competition_id"],"EPL")
        self.assertEqual(row["state"],"PLAYBACK_READY")


if __name__ == "__main__": unittest.main()

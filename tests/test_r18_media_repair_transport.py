"""R18 transport invariants retained under R19 known-candidate recovery.

These tests are intentionally source-level/lightweight so they can run in the
existing repository verification environment without live ESPN or YouTube calls.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")
AUDIT = (ROOT / "media_audit_service.py").read_text(encoding="utf-8")
HISTORY = (ROOT / "sbb" / "history_repository.py").read_text(encoding="utf-8")


class R18MediaRepairTransportTests(unittest.TestCase):
    def test_espn_search_reuses_direct_media_resolver(self):
        start = SERVER.index("def _espn_search_video_results")
        end = SERVER.index("def _espn_fetch_json", start)
        block = SERVER[start:end]
        self.assertIn("media=_espn_video_media_url(obj)", block)
        self.assertIn("if not media: continue", block)
        self.assertIn("_espn_video_allowed_us(obj)", block)
        self.assertNotIn("urls[0] if urls else ''", block)

    def test_espn_search_ids_are_restart_stable(self):
        start = SERVER.index("def _espn_search_video_results")
        end = SERVER.index("def _espn_fetch_json", start)
        block = SERVER[start:end]
        self.assertIn("stable_id=hashlib.sha1", block)
        self.assertNotIn("abs(hash(sig))", block)

    def test_repair_prefers_video_transport_over_external_url(self):
        start = AUDIT.index("def _asset_url")
        end = AUDIT.index("def _youtube_id", start)
        block = AUDIT[start:end]
        self.assertLess(block.index('"videoUrl"'), block.index('"externalUrl"'))
        self.assertIn('"playbackUrl"', block)

    def test_r19_requeues_r18_exhausted_actionable_jobs_once(self):
        self.assertIn('R19-KNOWN-CANDIDATE-RECERTIFICATION', AUDIT)
        self.assertIn("R19_KNOWN_CANDIDATE_RECERTIFICATION", AUDIT)
        self.assertIn("state='PENDING'", AUDIT)
        self.assertIn("state='WAITING_RETRY'", AUDIT)

    def test_history_prefers_video_url_before_external_url(self):
        start = HISTORY.index("def _canonical_url")
        end = HISTORY.index("def _upsert_source_media_conn", start)
        block = HISTORY[start:end]
        self.assertLess(block.index('item.get("videoUrl")'), block.index('item.get("externalUrl")'))


if __name__ == "__main__":
    unittest.main()

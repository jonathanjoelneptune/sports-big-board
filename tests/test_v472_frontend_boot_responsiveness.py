import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/"VERSION").read_text(encoding="utf-8").strip()
INDEX=(ROOT/"index.html").read_text(encoding="utf-8")
REG=(ROOT/"architecture"/"competition-registry-projection.js").read_text(encoding="utf-8")
DAY=(ROOT/"architecture"/"day-state.js").read_text(encoding="utf-8")
CORE=(ROOT/"core-model.js").read_text(encoding="utf-8")
CERT=(ROOT/"foundation-certification.json").read_text(encoding="utf-8")


class V472FrontendBootResponsivenessTests(unittest.TestCase):
    def test_frontend_registry_does_not_observe_entire_document(self):
        self.assertNotIn("new MutationObserver",REG)
        self.assertNotIn(".observe(document.documentElement",REG)
        self.assertIn("recursive MutationObserver/render loop",REG)

    def test_registry_render_is_idempotent(self):
        self.assertIn("specialRenderKey",REG)
        self.assertIn("leagueRenderKey",REG)
        self.assertIn("if(state.specialRenderKey===renderKey)",REG)
        self.assertIn("if(state.leagueRenderKey===renderKey)return",REG)

    def test_dev_card_uses_narrow_retry_without_dom_observer(self):
        self.assertIn("setInterval(ensureDevCard,1500)",REG)
        self.assertIn("without watching unrelated DOM mutations",REG)

    def test_launch_screen_remains_static_before_start(self):
        self.assertIn('id="launchPlayBtn"',INDEX)
        self.assertIn('id="launchScreen"',INDEX)
        self.assertNotIn("MutationObserver",REG)

    def test_release_handshake(self):
        self.assertEqual(VERSION,"4.7.2")
        self.assertIn("Sports Big Board — v4.7.2",INDEX)
        self.assertIn("architecture/competition-registry-projection.js?v=4.7.2",INDEX)
        self.assertIn("version:'4.7.2'",CORE)
        self.assertIn("version:'4.7.2'",DAY)
        self.assertIn("launch-screen responsiveness",CERT)


if __name__=="__main__":
    unittest.main()

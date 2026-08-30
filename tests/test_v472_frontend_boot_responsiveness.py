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
    """v4.7.2 established the frontend-boot responsiveness baseline.

    This historical test deliberately follows the current 4.7.x release instead
    of pinning the repository to the original 4.7.2 patch version.
    """

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

    def test_release_line_handshake(self):
        # v4.7.2 is the minimum baseline; later 4.7.x releases inherit the same
        # launch-responsiveness contract and use the current VERSION dynamically.
        parts=tuple(int(x) for x in VERSION.split("."))
        self.assertGreaterEqual(parts,(4,7,2))
        self.assertEqual(parts[:2],(4,7))
        self.assertIn(f"Sports Big Board — v{VERSION}",INDEX)
        self.assertIn(
            f"architecture/competition-registry-projection.js?v={VERSION}",
            INDEX,
        )
        self.assertIn(f"version:'{VERSION}'",CORE)
        self.assertIn(f"version:'{VERSION}'",DAY)
        self.assertIn("launch-screen responsiveness",CERT)


if __name__=="__main__":
    unittest.main()

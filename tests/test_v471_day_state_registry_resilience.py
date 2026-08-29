import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/"VERSION").read_text(encoding="utf-8").strip()
INDEX=(ROOT/"index.html").read_text(encoding="utf-8")
CORE=(ROOT/"core-model.js").read_text(encoding="utf-8")
DAYSTATE=(ROOT/"sbb"/"day_state.py").read_text(encoding="utf-8")
DAYUI=(ROOT/"architecture"/"day-state.js").read_text(encoding="utf-8")
REGUI=(ROOT/"architecture"/"competition-registry-projection.js").read_text(encoding="utf-8")
CERT=(ROOT/"foundation-certification.json").read_text(encoding="utf-8")


class V471DayStateRegistryResilienceTests(unittest.TestCase):
    def test_day_state_http_reads_never_build_synchronously(self):
        serve=DAYSTATE[DAYSTATE.index("def serve_day_state"):DAYSTATE.index("def serve_ribbon")]
        ribbon=DAYSTATE[DAYSTATE.index("def serve_ribbon"):DAYSTATE.index("def engine()")]
        self.assertIn("allow_build=False",serve)
        self.assertIn("COLD_WARMING",serve)
        self.assertIn("allow_build=False",ribbon)
        self.assertIn("if payload is None:",ribbon)
        self.assertIn("return False",ribbon)

    def test_focused_date_moves_to_front_of_background_queue(self):
        enqueue=DAYSTATE[DAYSTATE.index("def enqueue"):DAYSTATE.index("def focus")]
        self.assertIn("self.queue.remove(day)",enqueue)
        self.assertIn("self.queue.appendleft(day)",enqueue)

    def test_browser_day_state_prepaint_is_bounded_and_falls_back(self):
        self.assertIn("timeoutMs=700",DAYUI)
        self.assertIn("timeoutMs:650",DAYUI)
        self.assertIn("if(payload?.pending)return null",DAYUI)
        self.assertIn("return fallback(date)",DAYUI)

    def test_frontend_registry_merges_builder_registry_and_last_good_cache(self):
        self.assertIn("/api/competition-builder/catalog",REGUI)
        self.assertIn("/api/competition-registry",REGUI)
        self.assertIn("localStorage.setItem",REGUI)
        self.assertIn("cachedRows()",REGUI)
        self.assertIn("Never erase the last good projection",REGUI)

    def test_special_events_are_restored_from_frontend_projection(self):
        self.assertIn("sbbSpecialEventsWrap",REGUI)
        self.assertIn("sbbSpecialEventsMenu",REGUI)
        self.assertIn("visibleSpecial",REGUI)
        self.assertIn("sbb-v471-restored",REGUI)
        self.assertIn("SPECIAL EVENTS ▾",REGUI)

    def test_dev_competition_builder_launcher_retries_late_settings_dom(self):
        self.assertIn("function ensureDevCard()",REGUI)
        self.assertIn("setInterval(ensureDevCard,1500)",REGUI)
        self.assertIn("sbbAddSpecialEventBtn",REGUI)

    def test_core_model_uses_frontend_registry_as_dynamic_competition_fallback(self):
        self.assertIn("SBB_FRONTEND_REGISTRY?.competitionMap?.()",CORE)
        self.assertIn("SBB_COMPETITION_BUILDER?.competitionMap?.()",CORE)

    def test_release_contract(self):
        self.assertEqual(VERSION,"4.7.1")
        self.assertIn("architecture/competition-registry-projection.js?v=4.7.1",INDEX)
        self.assertIn("stale-while-revalidate",CERT)
        self.assertIn("Frontend Competition Projection",CERT)


if __name__=="__main__":
    unittest.main()

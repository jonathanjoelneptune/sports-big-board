import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/"VERSION").read_text(encoding="utf-8").strip()
INDEX=(ROOT/"index.html").read_text(encoding="utf-8")
REGISTRY=(ROOT/"sbb"/"competition_registry.py").read_text(encoding="utf-8")
DAYSTATE=(ROOT/"sbb"/"day_state.py").read_text(encoding="utf-8")
UI=(ROOT/"architecture"/"day-state.js").read_text(encoding="utf-8")
INIT=(ROOT/"sbb"/"__init__.py").read_text(encoding="utf-8")
CERT=(ROOT/"foundation-certification.json").read_text(encoding="utf-8")


class V470CompetitionRegistryDayStateTests(unittest.TestCase):
    def test_registry_is_observable_but_backwards_compatible_mapping(self):
        self.assertIn("class CompetitionCatalog(dict)",REGISTRY)
        self.assertIn("COMPETITIONS = CompetitionCatalog",REGISTRY)
        self.assertIn("def catalog()",REGISTRY)
        self.assertIn("def enabled_ids()",REGISTRY)
        self.assertIn("def subscribe(",REGISTRY)
        self.assertIn('COMPETITIONS[row["id"]] = row',REGISTRY)

    def test_dynamic_competition_registration_emits_backend_event(self):
        self.assertIn('"action":"UPDATE" if existed else "REGISTER"',REGISTRY)
        self.assertIn('"sourceKind": source_kind',REGISTRY)
        self.assertIn('"backendRegistered": True',REGISTRY)
        self.assertIn('"dayStateEnabled": bool',REGISTRY)

    def test_day_state_uses_existing_canonical_ribbon_helpers(self):
        self.assertIn('getattr(self.server, "_history_day_score_rows")',DAYSTATE)
        self.assertIn('getattr(self.server, "_history_day_ribbon_plans")',DAYSTATE)
        self.assertIn('getattr(self.server, "_history_day_score_inventory_complete")',DAYSTATE)
        self.assertIn('"scoreRowsByLeague":score_rows',DAYSTATE)
        self.assertIn('"eventPlans":plans',DAYSTATE)

    def test_day_state_intercepts_existing_history_ribbon_contract(self):
        self.assertIn('if parsed.path == "/api/history/ribbon":',DAYSTATE)
        self.assertIn('"X-SBB-Day-State":"1"',DAYSTATE)
        self.assertIn('"catalogFirst":True',DAYSTATE)
        self.assertIn('"scoreInventoryComplete"',DAYSTATE)

    def test_day_state_persists_snapshots_in_sqlite(self):
        self.assertIn('CREATE TABLE IF NOT EXISTS day_state',DAYSTATE)
        self.assertIn('day-state.sqlite3',DAYSTATE)
        self.assertIn('stale_after',DAYSTATE)
        self.assertIn('registry_revision',DAYSTATE)

    def test_registry_event_enrolls_new_competition_in_history_and_day_state(self):
        self.assertIn("registry.subscribe(self._on_registry_event, replay=True)",DAYSTATE)
        self.assertIn("self.server.HISTORY_LEAGUES",DAYSTATE)
        self.assertIn("_enqueue_competition_dates_after_registration",DAYSTATE)
        self.assertIn("catalog_events(league=cid",DAYSTATE)

    def test_browser_prepaints_from_day_state_and_keeps_fallback(self):
        self.assertIn("/api/day-state?date=",UI)
        self.assertIn("storeScoreDateLeague",UI)
        self.assertIn("ingestCompactCatalogPlans",UI)
        self.assertIn("hydrateHistoricalRibbonFromCatalog",UI)
        self.assertIn("fallback(date)",UI)

    def test_operator_views_expose_day_state_and_backend_registry(self):
        self.assertIn("DAY STATE",UI)
        self.assertIn("BACKEND REGISTRY",UI)
        self.assertIn("/api/competition-registry",UI)
        self.assertIn("REBUILD SNAPSHOT",UI)

    def test_release_contract(self):
        self.assertTrue(VERSION.startswith("4.7."))
        self.assertIn(f"architecture/day-state.js?v={VERSION}",INDEX)
        self.assertIn("from .day_state import install as _install_day_state",INIT)
        self.assertIn("_install_day_state()",INIT)
        self.assertIn("Competition Registry 2.0",CERT)
        self.assertIn("Day State Engine",CERT)


if __name__=="__main__":
    unittest.main()

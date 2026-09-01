from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "sbb" / "game_center_runtime_v508.py"


def load_runtime():
    spec = importlib.util.spec_from_file_location("sbb_v508_runtime_test", RUNTIME_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUNTIME = load_runtime()


def load_runtime_with_fake_multisport():
    """Load runtime in a synthetic package so the provider-capability guard is real."""
    package_name = "sbb_v508_fake"
    package = types.ModuleType(package_name)
    package.__path__ = []
    multisport = types.ModuleType(f"{package_name}.game_center_multisport")
    multisport._ESPN_COMPETITIONS = {
        "NFL": ("football", "nfl"),
        "CFB": ("football", "college-football"),
    }
    sys.modules[package_name] = package
    sys.modules[f"{package_name}.game_center_multisport"] = multisport
    spec = importlib.util.spec_from_file_location(
        f"{package_name}.game_center_runtime_v508", RUNTIME_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeServer:
    ESPN_SITE_API = "https://site.api.espn.com/apis/site/v2/sports"

    def __init__(self):
        self.indexed = []
        self.espn_fetch_calls = 0

    @staticmethod
    def _event_on_viewer_date(raw_date, target, _tz="", _offset=None):
        return str(raw_date)[:10] == str(target)

    @staticmethod
    def _same_team_pair(row, target):
        def norm(value):
            return "".join(ch for ch in str(value or "").lower() if ch.isalnum())

        def aliases(team):
            team = team or {}
            return {
                norm(team.get(key))
                for key in ("abbreviation", "shortName", "displayName", "name")
                if norm(team.get(key))
            }

        return bool(aliases(row.get("awayTeam")) & aliases(target.get("awayTeam"))) and bool(
            aliases(row.get("homeTeam")) & aliases(target.get("homeTeam"))
        )

    def _index_game_center_events(self, competition, rows, day, provider):
        self.indexed.append((competition, day, provider, len(rows)))

    def _espn_fetch_json(self, url, timeout=8):
        self.espn_fetch_calls += 1
        assert timeout <= 8
        assert "/football/college-football/scoreboard?" in url
        assert "groups=80" in url
        return {
            "events": [
                {
                    "id": "401864494",
                    "date": "2026-08-29T19:00Z",
                    "name": "San Jose State Spartans at USC Trojans",
                    "shortName": "SJSU @ USC",
                    "status": {
                        "type": {"state": "post", "completed": True, "shortDetail": "Final"},
                        "period": 4,
                        "displayClock": "0:00",
                    },
                    "competitions": [
                        {
                            "competitors": [
                                {
                                    "homeAway": "away",
                                    "score": "26",
                                    "team": {
                                        "id": "23",
                                        "displayName": "San Jose State Spartans",
                                        "shortDisplayName": "San Jose State",
                                        "abbreviation": "SJSU",
                                    },
                                },
                                {
                                    "homeAway": "home",
                                    "score": "42",
                                    "team": {
                                        "id": "30",
                                        "displayName": "USC Trojans",
                                        "shortDisplayName": "USC",
                                        "abbreviation": "USC",
                                    },
                                },
                            ]
                        }
                    ],
                }
            ]
        }


class AliasRepo:
    def __init__(self):
        self.rows = []

    def put_alias(self, *args):
        self.rows.append(args)


class Milestone:
    def __init__(self):
        self.rows = []

    def record(self, *args):
        self.rows.append(args)


class PatchServer(FakeServer):
    def __init__(self, resolver_result=""):
        super().__init__()
        self.GAME_CENTER_SUPPORTED = {"NFL", "NBA", "NHL", "MLB", "MLS", "EPL"}
        self.GAME_CENTER_REPOSITORY = AliasRepo()
        self.SBB_BACKEND_WIRING = {}
        self.MILESTONE_CONSOLE = Milestone()
        self.resolver_calls = 0
        self.resolver_result = resolver_result

        def original_resolver(_competition, _event_id, hints=None, allow_fetch=False):
            self.resolver_calls += 1
            return self.resolver_result

        def original_scoreboard(_league, _date, _tz="", _offset=None):
            return []

        def existing_multisport_fetch(competition, event_id, _fetch_json, _base):
            if competition == "CFB":
                return {
                    "competitionId": "CFB",
                    "eventId": str(event_id),
                    "event": {"sportId": "american-football", "competitionId": "CFB"},
                    "source": "ESPN Game Summary",
                }
            return {"competitionId": competition, "eventId": str(event_id)}

        self._resolve_game_center_event_id = original_resolver
        self._espn_scoreboard = original_scoreboard
        self.fetch_espn_game_center = existing_multisport_fetch


class V508CfbGameCenterTests(unittest.TestCase):
    def setUp(self):
        with RUNTIME._SCOREBOARD_CACHE_LOCK:
            RUNTIME._SCOREBOARD_CACHE.clear()

    def test_release_wiring_is_current_and_blocking(self):
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "5.0.8")
        init = (ROOT / "sbb" / "__init__.py").read_text(encoding="utf-8")
        verify = (ROOT / "VERIFY.sh").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))
        self.assertIn("game_center_runtime_v508", init)
        self.assertIn("_install_game_center_runtime_v508()", init)
        self.assertIn("python3 -m unittest tests.test_v508_cfb_game_center", verify)
        self.assertIn("sbb/game_center_runtime_v508.py", manifest["requiredFiles"])
        self.assertIn("tests/test_v508_cfb_game_center.py", manifest["requiredFiles"])
        self.assertIn("ui/game-center-view.js", manifest["requiredFiles"])

    def test_frontend_capability_is_explicit_not_just_enabled_live_league(self):
        core = (ROOT / "core-model.js").read_text(encoding="utf-8")
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("CFB:{id:'CFB'", core)
        self.assertIn("gameCenterProvider:'espn'", core)
        self.assertIn("v5.0.8: built-in score availability is not the Game Center capability contract", app)
        self.assertIn("return !!competition.gameCenterProvider;", app)

    def test_final_partial_game_center_is_contained_on_browser_main_thread(self):
        view = (ROOT / "ui" / "game-center-view.js").read_text(encoding="utf-8")
        self.assertIn("const finalPartial=partial&&final;", view)
        self.assertIn("finalPartial?30000:2200", view)
        self.assertIn("if(resident!==data)render(resident);", view)
        self.assertIn("if(gc!==data)render(gc);", view)
        self.assertIn("completed partial Game Center must not rebuild", view)

    def test_cfb_scoreboard_uses_college_football_and_preserves_espn_identity(self):
        server = FakeServer()
        rows = RUNTIME._cfb_scoreboard(server, "2026-08-29")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["competitionId"], "CFB")
        self.assertEqual(row["espnEventId"], "401864494")
        self.assertEqual(row["awayTeam"]["abbreviation"], "SJSU")
        self.assertEqual(row["homeTeam"]["abbreviation"], "USC")
        self.assertEqual(row["awayScore"], "26")
        self.assertEqual(row["homeScore"], "42")
        self.assertEqual(server.espn_fetch_calls, 1)

    def test_v4721_local_identity_is_first_and_network_free(self):
        runtime = load_runtime_with_fake_multisport()
        server = PatchServer(resolver_result="401864494")
        original_fetch = server.fetch_espn_game_center
        self.assertTrue(runtime._patch_server(server))
        hints = {"date": "2026-08-29", "away": "SJSU", "home": "USC"}
        resolved = server._resolve_game_center_event_id(
            "CFB", "401864494", hints=hints, allow_fetch=True
        )
        self.assertEqual(resolved, "401864494")
        self.assertEqual(server.resolver_calls, 1)
        self.assertEqual(server.espn_fetch_calls, 0)
        self.assertIs(server.fetch_espn_game_center, original_fetch)

    def test_cold_local_index_gets_one_bounded_espn_fingerprint_rescue(self):
        runtime = load_runtime_with_fake_multisport()
        server = PatchServer(resolver_result="")
        self.assertTrue(runtime._patch_server(server))
        self.assertIn("CFB", server.GAME_CENTER_SUPPORTED)
        hints = {"date": "2026-08-29", "away": "SJSU", "home": "USC"}
        resolved = server._resolve_game_center_event_id(
            "CFB", "401864494", hints=hints, allow_fetch=True
        )
        self.assertEqual(resolved, "401864494")
        self.assertEqual(server.resolver_calls, 1)
        self.assertEqual(server.espn_fetch_calls, 1)
        self.assertTrue(server.GAME_CENTER_REPOSITORY.rows)
        self.assertIn("v508CfbCapability", server.SBB_BACKEND_WIRING["gameCenter"])
        self.assertIn("v4721 local-first", server.SBB_BACKEND_WIRING["gameCenter"]["v508CfbIdentity"])

        # Wrong team fingerprint must not be accepted as the USC event.
        other = PatchServer(resolver_result="")
        runtime2 = load_runtime_with_fake_multisport()
        self.assertTrue(runtime2._patch_server(other))
        wrong = other._resolve_game_center_event_id(
            "CFB", "401864494",
            hints={"date": "2026-08-29", "away": "FRESNO", "home": "USC"},
            allow_fetch=True,
        )
        self.assertEqual(wrong, "")

    def test_curated_usc_media_is_not_changed_by_game_center_fix(self):
        curated = (ROOT / "architecture" / "curated-media-overrides.js").read_text(encoding="utf-8")
        self.assertIn("youtubeId:'-tDiPDHU2fs'", curated)
        self.assertIn("401864494", curated)
        self.assertIn("2026-08-29", curated)
        lowered = curated.lower()
        self.assertIn("sjsu", lowered)
        self.assertIn("usc", lowered)


if __name__ == "__main__":
    unittest.main()

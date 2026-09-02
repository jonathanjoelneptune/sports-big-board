from pathlib import Path
import importlib.util
import sys
import tempfile
import types

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "sbb" / "tennis_ribbon_projection.py"


def load_module(tmpdir):
    package = types.ModuleType("sbb")
    package.__path__ = [str(ROOT / "sbb")]
    sys.modules["sbb"] = package

    builder = types.ModuleType("sbb.competition_builder")
    builder._STATE_DIR = Path(tmpdir)
    names = {
        "russia": "ru", "united states": "us", "usa": "us", "france": "fr",
        "great britain": "gb", "spain": "es", "italy": "it", "germany": "de",
    }
    builder._country_code_for_name = lambda value: names.get(str(value or "").strip().lower(), "")
    sys.modules["sbb.competition_builder"] = builder

    registry = types.ModuleType("sbb.competition_registry")
    registry.get = lambda competition_id, default=None: ({"id": competition_id, "sportId": "tennis"} if str(competition_id).upper() == "USOPEN-2026" else default)
    sys.modules["sbb.competition_registry"] = registry

    day_state = types.ModuleType("sbb.day_state")
    day_state._catalog_score_rows_for_day = lambda server, day: ({}, {})
    day_state._merge_future_catalog_rows = lambda server, day, rows, today: (rows, {})
    class DayStateStore:
        def put(self, snapshot): return snapshot
        def get(self, day): return None
    day_state.DayStateStore = DayStateStore
    sys.modules["sbb.day_state"] = day_state

    spec = importlib.util.spec_from_file_location("sbb.tennis_ribbon_projection", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    with tempfile.TemporaryDirectory() as tmp:
        mod = load_module(tmp)
        store = mod.TennisAliasStore(Path(tmp) / "aliases.sqlite3")
        store.upsert_profiles([
            {
                "provider_id": "1001",
                "canonical_name": "Mirra Andreeva",
                "short_name": "M. Andreeva",
                "country_code": "RU",
                "flag_url": "https://flagcdn.com/w80/ru.png",
                "rank": "6",
                "source": "TEST",
                "aliases": ["M. Andreeva", "Andreeva", "AND"],
            },
            {
                "provider_id": "1002",
                "canonical_name": "Coco Gauff",
                "short_name": "C. Gauff",
                "country_code": "US",
                "flag_url": "https://flagcdn.com/w80/us.png",
                "rank": "3",
                "source": "TEST",
                "aliases": ["C. Gauff", "Gauff", "GAU"],
            },
        ])
        mod._STORE = store
        event = {
            "competitionId": "USOPEN-2026",
            "competitionName": "2026 US Open",
            "sportId": "tennis",
            "date": "2026-09-01",
            "round": "Round of 64",
            "awayTeam": {"displayName": "M. Andreeva", "abbreviation": "AND", "rank": "6"},
            "homeTeam": {"displayName": "C. Gauff", "abbreviation": "GAU", "rank": "3"},
        }
        rows, diag = mod.project_rows("2026-09-01", {"USOPEN-2026": [event]}, warm=False)
        out = rows["USOPEN-2026"][0]
        away = out["awayTeam"]
        home = out["homeTeam"]

        assert away["canonicalName"] == "Mirra Andreeva"
        assert away["displayName"] == "Mirra Andreeva"
        assert away["providerAbbreviation"] == "AND"
        assert away["abbreviation"] == "#6 M. Andreeva"
        assert away["shortName"] == "#6 M. Andreeva"
        assert away["countryCode"] == "RU"
        assert away["logo"] == "https://flagcdn.com/w80/ru.png"
        assert away["flagEmoji"]
        assert home["abbreviation"] == "#3 C. Gauff"
        assert home["countryCode"] == "US"
        assert out["ribbonContextLabel"] == "ROUND 2"
        assert out["tennisRibbonLabel"] == "ROUND 2"
        assert out["__sbbTennisPresentation"] == mod.PROJECTION_VERSION
        assert diag["tennisAliasHits"] == 2
        assert diag["tennisFlags"] == 2
        assert diag["tennisMissingFlags"] == 0

        # With a complete persistent alias cache, a full build should still make
        # zero provider calls. This is the normal hot path after the first warm.
        called = {"warm": 0}
        def forbidden_warm(day):
            called["warm"] += 1
            raise AssertionError("provider warm should not run when every flag is cached")
        mod._warm_tennis_day = forbidden_warm
        rows2, diag2 = mod.project_rows("2026-09-01", {"USOPEN-2026": [event]}, warm=True)
        assert called["warm"] == 0
        assert diag2["tennisWarmState"] == "READY_FROM_ALIAS_DB"
        assert rows2["USOPEN-2026"][0]["awayTeam"]["logo"]

        # The alias DB resolves the short schedule name directly to the long
        # canonical player identity; the browser never performs this conversion.
        assert store.resolve("M. Andreeva")["canonical_name"] == "Mirra Andreeva"
        assert store.resolve("AND")["canonical_name"] == "Mirra Andreeva"

    print("PASS v5.1.21 backend tennis alias/flag projection invariants")


if __name__ == "__main__":
    main()

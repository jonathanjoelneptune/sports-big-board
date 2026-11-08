#!/usr/bin/env python3
"""Regression: ribbon media reads must never run catalog repair.

Exercise only the read adapter. Importing the full sbb package would start
production-style workers, so extract the function with the Python AST instead.
"""
import ast
from contextlib import closing
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = (root / "sbb" / "historical_media_v4610.py").read_text(encoding="utf-8")
tree = ast.parse(source)
fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_ribbon_media_v4610")
for call in (node for node in ast.walk(fn) if isinstance(node, ast.Call)):
    if isinstance(call.func, ast.Name):
        assert call.func.id != "repair_date_associations", "ribbon must never trigger a catalog repair"

class FakeConnection:
    def execute(self, sql, params):
        assert "history_event_alias" in sql
        assert params == ("2026-11-08",)
        return [
            {"league": "NFL", "alias_event_id": "new-provider-id", "canonical_event_key": "NFL:canonical-id"}
        ]

    def close(self):
        pass

class FakeRepo:
    def _read_connect(self):
        return FakeConnection()

def forbidden_repair(*args, **kwargs):
    raise AssertionError("request path launched historical catalog repair")

def bulk_media(repo, date, leagues=None, include_failed=False):
    assert date == "2026-11-08"
    assert leagues == ["NFL"]
    assert include_failed is False
    return {"NFL:canonical-id": [{"assetKey": "recap-1", "verifiedPlayable": True}]}

ns = {
    "_ORIGINAL_RIBBON_MEDIA": bulk_media,
    "_ensure_alias_table": lambda repo: None,
    "_clean": lambda value: str(value or "").strip(),
    "closing": closing,
    "repair_date_associations": forbidden_repair,
}
isolated = ast.Module(body=[fn], type_ignores=[])
exec(compile(ast.fix_missing_locations(isolated), "<ribbon-adapter>", "exec"), ns)
result = ns["_ribbon_media_v4610"](FakeRepo(), "2026-11-08", leagues=["NFL"])
assert "NFL:canonical-id" in result
assert result["NFL:new-provider-id"] == result["NFL:canonical-id"]
assert result["NFL:canonical-id"][0]["assetKey"] == "recap-1"
print("PASS: ribbon reads existing media/aliases without requesting catalog repair")

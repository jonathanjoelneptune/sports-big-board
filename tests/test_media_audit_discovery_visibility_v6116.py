#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
service = (ROOT / "media_audit_service.py").read_text(encoding="utf-8")
materializer = (ROOT / "tools" / "apply_v6116_release.py").read_text(encoding="utf-8")

start = service.index("    def _youtube_fallback_candidates(self, job):")
end = service.index("    def _repair_by_discovery(self, job):", start)
body = service[start:end]
for reason in (
    "FALLBACK_DISABLED",
    "KEY_MISSING",
    "DEGRADED_SEARCH_DEFERRED",
    "EVENT_NOT_FOUND",
    "NO_QUERY",
):
    assert reason in body, reason
assert body.count("GENERIC_YOUTUBE_SEARCH") >= 8

assert "def patch_media_repair_identity(root):" in materializer
assert "from sbb.media_team_sources_v6115 import TeamSourceRegistry" in materializer
assert "from sbb.media_team_sources_v6116 import TeamSourceRegistry" in materializer
assert "patch_media_repair_identity(root)" in materializer

print("PASS v6.1.16 Media Repair fallback visibility/materializer contract")

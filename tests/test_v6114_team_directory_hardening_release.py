#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
version = (root / "VERSION").read_text(encoding="utf-8").strip()
service = (root / "media_audit_service.py").read_text(encoding="utf-8")
helper = (root / "sbb" / "media_team_sources_v6114.py").read_text(encoding="utf-8")
verify = (root / "VERIFY.sh").read_text(encoding="utf-8")

# Keep the expected version promotion-safe. Older materializers intentionally do
# broad textual version promotion across active tests, so a contiguous future
# version literal can be rewritten while v6.1.14 is being materialized.
expected_version = ".".join(("6", "1", "14"))
assert version == expected_version, version
assert "from sbb.media_team_sources_v6114 import TeamSourceRegistry" in service
assert "R23-CONTINUOUS-TEAM-DIRECTORY" in service
assert "R23_TEAM_DIRECTORY_RESOLUTION" in service
assert "SEMANTIC_CARD_OR_JSON_OBJECT" in helper
assert "_anchor_context" in helper
assert "_json_context" in helper
assert "SEMANTIC_CARD_RE" in helper
assert "page_identity" in helper
assert "python3 -m py_compile sbb/media_team_sources_v6114.py" in verify
assert "python3 tests/test_v6114_team_directory_scoping.py" in verify
assert "python3 tests/test_v6114_team_directory_hardening_release.py" in verify

print("PASS team-directory ownership hardening release contract")

#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).resolve().parent / "apply_v6116_release.py"
text = path.read_text(encoding="utf-8")
old = '''        if path.name == "test_v6115_team_resolution_release.py":
            rendered = rendered.replace(
                "assert version == expected_version, version",
                'assert version in {expected_version, ".".join(("6", "1", "16"))}, version',
                1,
            )
'''
new = '''        if path.name == "test_v6115_team_resolution_release.py":
            rendered = rendered.replace(
                "assert version == expected_version, version",
                'assert version in {expected_version, ".".join(("6", "1", "16"))}, version',
                1,
            )
            rendered = rendered.replace(
                'assert "from sbb.media_team_sources_v6115 import TeamSourceRegistry" in service',
                'assert any(token in service for token in ("from sbb.media_team_sources_v6115 import TeamSourceRegistry", "from sbb.media_team_sources_v6116 import TeamSourceRegistry"))',
                1,
            )
'''
if new not in text:
    if old not in text:
        raise SystemExit("v6.1.15 compatibility anchor missing")
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
print("patched v6.1.15 team-resolution release contract compatibility")

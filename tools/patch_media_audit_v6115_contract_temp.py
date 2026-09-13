#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).resolve().parent / "apply_v6116_release.py"
text = path.read_text(encoding="utf-8")
needle = '''        rendered = rendered.replace(
            'forward_version = ".".join(("6", "1", "15"))',
            'forward_version = ".".join(("6", "1", "16"))',
        )
'''
addition = needle + '''        rendered = rendered.replace(
            'assert "from sbb.media_team_sources_v6115 import TeamSourceRegistry" in service',
            'assert any(token in service for token in ("from sbb.media_team_sources_v6115 import TeamSourceRegistry", "from sbb.media_team_sources_v6116 import TeamSourceRegistry"))',
        )
'''
if addition not in text:
    if needle not in text:
        raise SystemExit("historical release-contract anchor missing")
    text = text.replace(needle, addition, 1)
    path.write_text(text, encoding="utf-8")
print("patched historical team-resolution release contract compatibility")

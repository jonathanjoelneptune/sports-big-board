#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).resolve().parent / "apply_v6116_release.py"
text = path.read_text(encoding="utf-8")
needle = '''        rendered = rendered.replace(
            'assert "from sbb.media_team_sources_v6115 import TeamSourceRegistry" in service',
            'assert any(token in service for token in ("from sbb.media_team_sources_v6115 import TeamSourceRegistry", "from sbb.media_team_sources_v6116 import TeamSourceRegistry"))',
        )
'''
addition = needle + '''        rendered = rendered.replace(
            "assert 'from sbb.media_team_sources_v6115 import TeamSourceRegistry' in service",
            'assert any(token in service for token in ("from sbb.media_team_sources_v6115 import TeamSourceRegistry", "from sbb.media_team_sources_v6116 import TeamSourceRegistry"))',
        )
'''
if addition not in text:
    if needle not in text:
        raise SystemExit("historical resolver compatibility anchor missing")
    text = text.replace(needle, addition, 1)
    path.write_text(text, encoding="utf-8")
print("patched quoted historical team-resolution release contracts")

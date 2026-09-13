#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / "media-audit.html").read_text(encoding="utf-8")
copy_js = (ROOT / "ui" / "media-audit-copy-v6116.js").read_text(encoding="utf-8")

assert 'id="copyAuditInfo"' in html
assert 'ui/media-audit-copy-v6116.js' in html
for token in (
    "SPORTS BIG BOARD — MEDIA HEALTH AUDIT",
    "SUMMARY",
    "OPERATOR CHANNEL HEALTH",
    "DATABASE + PRODUCTION PARITY",
    "MEDIA REPAIR ENGINE",
    "RECENT REPAIR TRACE",
    "SERVER TRACE",
    "repairTeamSources",
    "repairTeamResolution",
    "repairSourceStats",
    "navigator.clipboard",
    "document.execCommand('copy')",
    "COPIED ${Math.max(1, Math.round(report.length / 1024))} KB",
):
    assert token in copy_js, token

# The report is intentionally diagnostic, not a clipboard dump of the 8k-row table.
assert "gameRows" not in copy_js
assert "querySelectorAll('tr')" not in copy_js

print("PASS v6.1.16 Media Audit copy-important-info contract")

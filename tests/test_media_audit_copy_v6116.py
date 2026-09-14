#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / "media-audit.html").read_text(encoding="utf-8")
copy_js = (ROOT / "ui" / "media-audit-copy-v6116.js").read_text(encoding="utf-8")

assert 'id="copyAuditInfo"' in html
assert 'ui/media-audit-copy-v6116.js' in html
for token in (
    "SPORTS BIG BOARD — MEDIA HEALTH AUDIT — OVERCOMPLETE DIAGNOSTIC COPY",
    "COPY CAPTURE HEALTH",
    "SUMMARY",
    "OPERATOR CHANNEL HEALTH",
    "DATABASE + PRODUCTION PARITY",
    "MEDIA REPAIR ENGINE",
    "REPAIR THROUGHPUT / YIELD",
    "DISCOVERY CIRCUIT",
    "YOUTUBE GATEWAY / QUOTA",
    "TEAM SOURCE RESOLUTION",
    "DISCOVERY STAGE ROLLUP — RECENT WORKER TRACE",
    "TOP RECENT DISCOVERY FAILURE / BLOCK REASONS",
    "UNRESOLVED TEAM IDENTITIES — COMPLETE STATUS SAMPLE",
    "REPAIR WORKERS — COMPLETE SNAPSHOTS",
    "AUDIT WORKERS — COMPLETE SNAPSHOTS",
    "RECENT REPAIR TRACE — RENDERED",
    "SERVER TRACE — RENDERED",
    "CURRENT INVENTORY PAGE — HUMAN READABLE",
    "RAW MEDIA AUDIT STATUS — COMPLETE JSON",
    "RAW CORE BACKEND STATUS — COMPLETE JSON",
    "RAW CURRENT FILTERED INVENTORY PAGE — COMPLETE JSON",
    "RAW BROWSER / DOM STATE — ALL ELEMENTS WITH IDS",
    "COPY FETCH METADATA",
    "repairTeamSources",
    "repairTeamResolution",
    "repairSourceStats",
    "navigator.clipboard",
    "document.execCommand('copy')",
    "BUILDING FULL COPY…",
    "safeFetch('Media Audit status'",
    "safeFetch('Core backend status'",
    "safeFetch('Current inventory page'",
    "document.querySelectorAll('[id]')",
    "youtubeGateway?.search",
    "stageRollup(status)",
    "reasonRollup(status)",
):
    assert token in copy_js, token

# The copy report should capture the current inventory page through the server API,
# not scrape thousands of rendered table nodes from the DOM.
assert "querySelectorAll('tr')" not in copy_js
assert "inventory?${inventoryQuery().toString()}" in copy_js

print("PASS v6.1.16 overcomplete Media Audit copy diagnostics contract")

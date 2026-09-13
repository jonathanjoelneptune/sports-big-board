#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text, old, new, label):
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)


path = ROOT / "media-audit.html"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '        <button id="exportCsv">FAILURES CSV</button>\n',
    '        <button id="exportCsv">FAILURES CSV</button>\n        <button id="copyAuditInfo" class="primary" aria-label="Copy important Media Audit diagnostics">COPY IMPORTANT INFO</button>\n',
    "Media Audit copy button",
)
text = replace_once(
    text,
    '  <script src="ui/media-audit-v550.js?v=5.5.0-r20"></script>\n',
    '  <script src="ui/media-audit-v550.js?v=5.5.0-r20"></script>\n  <script src="ui/media-audit-copy-v6116.js?v=6.1.16"></script>\n',
    "Media Audit copy module",
)
path.write_text(text, encoding="utf-8")

path = ROOT / "media_audit_service.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '        if not REPAIR_YOUTUBE_FALLBACK: return {"candidates":[],"quotaBlocked":False,"retryAt":0}\n',
    '''        if not REPAIR_YOUTUBE_FALLBACK:
            self._record_stage(job,'GENERIC_YOUTUBE_SEARCH',provider='YOUTUBE_SEARCH',results=0,new=0,details={"reason":"FALLBACK_DISABLED"})
            return {"candidates":[],"quotaBlocked":False,"retryAt":0,"reason":"FALLBACK_DISABLED"}
''',
    "disabled generic fallback telemetry",
)
text = replace_once(
    text,
    "            self._trace('WARN','Direct YouTube repair fallback unavailable: YOUTUBE_API_KEY missing',event=job['canonical_event_key'])\n            return {\"candidates\":[],\"quotaBlocked\":False,\"retryAt\":0,\"reason\":\"KEY_MISSING\"}\n",
    "            self._trace('WARN','Direct YouTube repair fallback unavailable: YOUTUBE_API_KEY missing',event=job['canonical_event_key'])\n            self._record_stage(job,'GENERIC_YOUTUBE_SEARCH',provider='YOUTUBE_SEARCH',results=0,new=0,details={\"reason\":\"KEY_MISSING\"})\n            return {\"candidates\":[],\"quotaBlocked\":False,\"retryAt\":0,\"reason\":\"KEY_MISSING\"}\n",
    "missing key generic fallback telemetry",
)
text = replace_once(
    text,
    "        if health=='DEGRADED' and attempt<2:\n            return {\"candidates\":[],\"quotaBlocked\":False,\"retryAt\":0,\"reason\":\"DEGRADED_SEARCH_DEFERRED\"}\n",
    "        if health=='DEGRADED' and attempt<2:\n            self._record_stage(job,'GENERIC_YOUTUBE_SEARCH',provider='YOUTUBE_SEARCH',results=0,new=0,details={\"reason\":\"DEGRADED_SEARCH_DEFERRED\"})\n            return {\"candidates\":[],\"quotaBlocked\":False,\"retryAt\":0,\"reason\":\"DEGRADED_SEARCH_DEFERRED\"}\n",
    "degraded fallback telemetry",
)
text = replace_once(
    text,
    "        context=self.store.repair_event_context(job['canonical_event_key'])\n        if not context: return {\"candidates\":[],\"quotaBlocked\":False,\"retryAt\":0,\"reason\":\"EVENT_NOT_FOUND\"}\n        queries=self._youtube_queries(context)\n        if not queries: return {\"candidates\":[],\"quotaBlocked\":False,\"retryAt\":0,\"reason\":\"NO_QUERY\"}\n",
    "        context=self.store.repair_event_context(job['canonical_event_key'])\n        if not context:\n            self._record_stage(job,'GENERIC_YOUTUBE_SEARCH',provider='YOUTUBE_SEARCH',results=0,new=0,details={\"reason\":\"EVENT_NOT_FOUND\"})\n            return {\"candidates\":[],\"quotaBlocked\":False,\"retryAt\":0,\"reason\":\"EVENT_NOT_FOUND\"}\n        queries=self._youtube_queries(context)\n        if not queries:\n            self._record_stage(job,'GENERIC_YOUTUBE_SEARCH',provider='YOUTUBE_SEARCH',results=0,new=0,details={\"reason\":\"NO_QUERY\"})\n            return {\"candidates\":[],\"quotaBlocked\":False,\"retryAt\":0,\"reason\":\"NO_QUERY\"}\n",
    "missing context/query fallback telemetry",
)
path.write_text(text, encoding="utf-8")

path = ROOT / "tools" / "apply_v6116_release.py"
text = path.read_text(encoding="utf-8")
anchor = "\ndef patch_init(root):\n"
helper = '''
def patch_media_repair_identity(root):
    path = root / "media_audit_service.py"
    text = path.read_text(encoding="utf-8")
    old = "from sbb.media_team_sources_v6115 import TeamSourceRegistry\\n"
    new = "from sbb.media_team_sources_v6116 import TeamSourceRegistry\\n"
    if new not in text:
        if old not in text:
            raise SystemExit("ERROR: v6.1.16 Media Repair team-source import anchor missing")
        text = text.replace(old, new, 1)
        path.write_text(text, encoding="utf-8")

'''
if "def patch_media_repair_identity(" not in text:
    if anchor not in text:
        raise SystemExit("missing apply_v6116 patch_init anchor")
    text = text.replace(anchor, "\n" + helper + "def patch_init(root):\n", 1)
text = replace_once(
    text,
    "    run_base(root, preserved)\n    patch_init(root)\n",
    "    run_base(root, preserved)\n    patch_media_repair_identity(root)\n    patch_init(root)\n",
    "v6116 Media Repair import switch",
)
required_anchor = '        root / "tests" / "test_v6116_startup_registry_release_integrity.py",\n'
required_new = required_anchor + (
    '        root / "sbb" / "media_team_sources_v6116.py",\n'
    '        root / "tests" / "test_media_team_sources_v6116.py",\n'
    '        root / "tests" / "test_media_audit_copy_v6116.py",\n'
    '        root / "tests" / "test_media_audit_discovery_visibility_v6116.py",\n'
)
text = replace_once(text, required_anchor, required_new, "v6116 required Media Audit files")
verify_anchor = '        "python3 tests/test_v6116_startup_registry_release_integrity.py",\n'
verify_new = verify_anchor + (
    '        "python3 -m py_compile sbb/media_team_sources_v6116.py",\n'
    '        "python3 tests/test_media_team_sources_v6116.py",\n'
    '        "python3 tests/test_media_audit_copy_v6116.py",\n'
    '        "python3 tests/test_media_audit_discovery_visibility_v6116.py",\n'
    '        "node --check ui/media-audit-copy-v6116.js",\n'
)
text = replace_once(text, verify_anchor, verify_new, "v6116 Media Audit release verification")
path.write_text(text, encoding="utf-8")

path = ROOT / "VERIFY.sh"
text = path.read_text(encoding="utf-8")
marker = "python3 tools/check_release_version.py"
commands = [
    "python3 -m py_compile sbb/media_team_sources_v6116.py",
    "python3 tests/test_media_team_sources_v6116.py",
    "python3 tests/test_media_audit_copy_v6116.py",
    "python3 tests/test_media_audit_discovery_visibility_v6116.py",
    "node --check ui/media-audit-copy-v6116.js",
]
missing = [cmd for cmd in commands if cmd not in text]
if missing:
    if marker not in text:
        raise SystemExit("missing VERIFY release checker anchor")
    text = text.replace(marker, "\n".join(missing) + "\n" + marker, 1)
    path.write_text(text, encoding="utf-8")

print("patched Media Audit discovery identity + copy diagnostics")

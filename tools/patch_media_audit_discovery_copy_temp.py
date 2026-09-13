#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text, old, new, label):
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)


def patch_source_html():
    path = ROOT / "media-audit.html"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        <button id="exportCsv">FAILURES CSV</button>\n',
        '        <button id="exportCsv">FAILURES CSV</button>\n        <button id="copyAuditInfo" class="primary" aria-label="Copy important Media Audit diagnostics">COPY IMPORTANT INFO</button>\n',
        "Media Audit copy button",
    )
    if 'ui/media-audit-copy-v6116.js' not in text:
        marker = '  <script src="ui/media-audit-v550.js?v=5.5.0-r20"></script>\n'
        if marker not in text:
            raise SystemExit("missing Media Audit script anchor")
        text = text.replace(marker, marker + '  <script src="ui/media-audit-copy-v6116.js?v=6.1.16"></script>\n', 1)
    path.write_text(text, encoding="utf-8")


def patch_fallback_visibility(path):
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


def patch_materializer():
    path = ROOT / "tools" / "apply_v6116_release.py"
    text = path.read_text(encoding="utf-8")

    preserve_anchor = '    "tests/test_v6116_startup_registry_release_integrity.py",\n'
    preserve_add = preserve_anchor + (
        '    "sbb/media_team_sources_v6116.py",\n'
        '    "ui/media-audit-copy-v6116.js",\n'
        '    "tests/test_media_team_sources_v6116.py",\n'
        '    "tests/test_media_audit_copy_v6116.py",\n'
        '    "tests/test_media_audit_discovery_visibility_v6116.py",\n'
    )
    text = replace_once(text, preserve_anchor, preserve_add, "v6116 preserve Media Audit additions")

    insert_anchor = "\ndef patch_init(root):\n"
    helpers = '''
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


def patch_media_audit_copy(root):
    path = root / "media-audit.html"
    text = path.read_text(encoding="utf-8")
    button = '        <button id="copyAuditInfo" class="primary" aria-label="Copy important Media Audit diagnostics">COPY IMPORTANT INFO</button>'
    if 'id="copyAuditInfo"' not in text:
        anchor = '        <button id="exportCsv">FAILURES CSV</button>'
        if anchor not in text:
            raise SystemExit("ERROR: v6.1.16 Media Audit copy button anchor missing")
        text = text.replace(anchor, anchor + "\\n" + button, 1)
    script = '  <script src="ui/media-audit-copy-v6116.js?v=6.1.16"></script>'
    lines = text.splitlines()
    found = False
    for idx, line in enumerate(lines):
        if 'ui/media-audit-copy-v6116.js' in line:
            lines[idx] = script
            found = True
    if not found:
        for idx, line in enumerate(lines):
            if '</body>' in line:
                lines.insert(idx, script)
                found = True
                break
    if not found:
        raise SystemExit("ERROR: v6.1.16 Media Audit copy script anchor missing")
    path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")


def patch_media_repair_visibility(root):
    path = root / "media_audit_service.py"
    text = path.read_text(encoding="utf-8")
    if '"FALLBACK_DISABLED"' not in text:
        old = '        if not REPAIR_YOUTUBE_FALLBACK: return {"candidates":[],"quotaBlocked":False,"retryAt":0}\\n'
        new = '        if not REPAIR_YOUTUBE_FALLBACK:\\n            self._record_stage(job,\'GENERIC_YOUTUBE_SEARCH\',provider=\'YOUTUBE_SEARCH\',results=0,new=0,details={"reason":"FALLBACK_DISABLED"})\\n            return {"candidates":[],"quotaBlocked":False,"retryAt":0,"reason":"FALLBACK_DISABLED"}\\n'
        if old not in text:
            raise SystemExit("ERROR: v6.1.16 fallback-disabled anchor missing")
        text = text.replace(old, new, 1)
    if "details={\"reason\":\"KEY_MISSING\"}" not in text:
        old = "            self._trace('WARN','Direct YouTube repair fallback unavailable: YOUTUBE_API_KEY missing',event=job['canonical_event_key'])\\n            return {\\\"candidates\\\":[],\\\"quotaBlocked\\\":False,\\\"retryAt\\\":0,\\\"reason\\\":\\\"KEY_MISSING\\\"}\\n"
        # Simpler direct insertion protects materialized variants without replacing the return.
        marker = "            self._trace('WARN','Direct YouTube repair fallback unavailable: YOUTUBE_API_KEY missing',event=job['canonical_event_key'])\\n"
        if marker not in text:
            raise SystemExit("ERROR: v6.1.16 YouTube-key anchor missing")
        text = text.replace(marker, marker + "            self._record_stage(job,'GENERIC_YOUTUBE_SEARCH',provider='YOUTUBE_SEARCH',results=0,new=0,details={\\\"reason\\\":\\\"KEY_MISSING\\\"})\\n", 1)
    if 'details={"reason":"DEGRADED_SEARCH_DEFERRED"}' not in text:
        marker = "        if health=='DEGRADED' and attempt<2:\\n"
        if marker not in text:
            raise SystemExit("ERROR: v6.1.16 degraded fallback anchor missing")
        text = text.replace(marker, marker + "            self._record_stage(job,'GENERIC_YOUTUBE_SEARCH',provider='YOUTUBE_SEARCH',results=0,new=0,details={\\\"reason\\\":\\\"DEGRADED_SEARCH_DEFERRED\\\"})\\n", 1)
    if 'details={"reason":"EVENT_NOT_FOUND"}' not in text:
        old = '        if not context: return {"candidates":[],"quotaBlocked":False,"retryAt":0,"reason":"EVENT_NOT_FOUND"}\\n'
        new = '        if not context:\\n            self._record_stage(job,\'GENERIC_YOUTUBE_SEARCH\',provider=\'YOUTUBE_SEARCH\',results=0,new=0,details={"reason":"EVENT_NOT_FOUND"})\\n            return {"candidates":[],"quotaBlocked":False,"retryAt":0,"reason":"EVENT_NOT_FOUND"}\\n'
        if old not in text:
            raise SystemExit("ERROR: v6.1.16 event-not-found anchor missing")
        text = text.replace(old, new, 1)
    if 'details={"reason":"NO_QUERY"}' not in text:
        old = '        if not queries: return {"candidates":[],"quotaBlocked":False,"retryAt":0,"reason":"NO_QUERY"}\\n'
        new = '        if not queries:\\n            self._record_stage(job,\'GENERIC_YOUTUBE_SEARCH\',provider=\'YOUTUBE_SEARCH\',results=0,new=0,details={"reason":"NO_QUERY"})\\n            return {"candidates":[],"quotaBlocked":False,"retryAt":0,"reason":"NO_QUERY"}\\n'
        if old not in text:
            raise SystemExit("ERROR: v6.1.16 no-query anchor missing")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")

'''
    if "def patch_media_repair_identity(" not in text:
        if insert_anchor not in text:
            raise SystemExit("missing apply_v6116 patch_init anchor")
        text = text.replace(insert_anchor, "\n" + helpers + "def patch_init(root):\n", 1)

    old_run = "    run_base(root, preserved)\n    patch_init(root)\n"
    new_run = "    run_base(root, preserved)\n    patch_media_repair_visibility(root)\n    patch_media_repair_identity(root)\n    patch_media_audit_copy(root)\n    patch_init(root)\n"
    text = replace_once(text, old_run, new_run, "v6116 post-replay Media Audit patches")

    req_anchor = '        root / "tests" / "test_v6116_startup_registry_release_integrity.py",\n'
    req_add = req_anchor + (
        '        root / "sbb" / "media_team_sources_v6116.py",\n'
        '        root / "ui" / "media-audit-copy-v6116.js",\n'
        '        root / "tests" / "test_media_team_sources_v6116.py",\n'
        '        root / "tests" / "test_media_audit_copy_v6116.py",\n'
        '        root / "tests" / "test_media_audit_discovery_visibility_v6116.py",\n'
    )
    text = replace_once(text, req_anchor, req_add, "v6116 required Media Audit files")

    verify_anchor = '        "python3 tests/test_v6116_startup_registry_release_integrity.py",\n'
    verify_add = verify_anchor + (
        '        "python3 -m py_compile sbb/media_team_sources_v6116.py",\n'
        '        "python3 tests/test_media_team_sources_v6116.py",\n'
        '        "python3 tests/test_media_audit_copy_v6116.py",\n'
        '        "python3 tests/test_media_audit_discovery_visibility_v6116.py",\n'
        '        "node --check ui/media-audit-copy-v6116.js",\n'
    )
    text = replace_once(text, verify_anchor, verify_add, "v6116 Media Audit release verification")
    path.write_text(text, encoding="utf-8")


def patch_source_verify():
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
        text = text.replace(marker, marker + "\n" + "\n".join(missing), 1)
    path.write_text(text, encoding="utf-8")


patch_source_html()
patch_fallback_visibility(ROOT / "media_audit_service.py")
patch_materializer()
patch_source_verify()
print("patched Media Audit discovery identity + copy diagnostics on current main")

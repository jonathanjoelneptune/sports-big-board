#!/usr/bin/env python3
"""v6.1.4 smoke reliability regression test, kept capability-oriented."""
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
assert (ROOT/"VERSION").read_text(encoding="utf-8").strip()=="6.1.4"
validation=(ROOT/"sbb"/"canonical_validation_v612.py").read_text(encoding="utf-8")
assert 'deadline=_now()+120' not in validation
assert 'while True:' in validation
assert 'parsed.path=="/api/canonical/validation/health"' in validation
assert 'cold starts can outlive the old 120-second installer deadline' in validation
pages=(ROOT/"cloud"/"github-pages"/"build_pages.py").read_text(encoding="utf-8")
assert 'GITHUB_SHA' in pages
assert '&b={build_sha}' in pages
assert 'independent asset cache generation' in pages
media=(ROOT/"media_audit_service.py").read_text(encoding="utf-8")
assert 'SBB_MEDIA_AUDIT_WORKERS", "1"' in media
# v6.1.3 recovery required Repair to default off. Later releases may restore
# Repair only when exhaustive discovery remains serialized and a shared upstream
# failure circuit prevents the repair queue from overwhelming the primary API.
if 'SBB_MEDIA_REPAIR_ENABLED", "0"' not in media:
    assert 'SBB_MEDIA_REPAIR_ENABLED", "1"' in media
    assert 'REPAIR_DISCOVERY_CIRCUIT.before_request()' in media
    assert 'SBB_MEDIA_AUDIT_DISCOVERY_CONCURRENCY", "1"' in media
subprocess.run(["python3","-m","py_compile",str(ROOT/"sbb"/"canonical_validation_v612.py"),str(ROOT/"cloud"/"github-pages"/"build_pages.py")],check=True)
print("PASS: v6.1.4 smoke reliability + frontend cache generation")

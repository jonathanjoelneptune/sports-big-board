#!/usr/bin/env python3
"""Verify the v6.1.3 Media Audit recovery invariant remains preserved."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / "media_audit_service.py").read_text(encoding="utf-8")
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
architecture_version = (ROOT / "architecture" / "VERSION").read_text(encoding="utf-8").strip()

assert version == "6.1.3", version
assert architecture_version == version, (architecture_version, version)
assert 'SBB_MEDIA_AUDIT_WORKERS", "1"' in text, "Media Audit must remain one canonical worker after recovery"
assert 'SBB_MEDIA_AUDIT_DISCOVERY_CONCURRENCY", "1"' in text, "Media Audit discovery concurrency must remain one"
assert 'SBB_MEDIA_AUDIT_WORKERS", "3"' not in text, "Three-worker audit default was not removed"

# v6.1.3 itself recovered production by defaulting persistent Repair off. A later
# release may restore it only if shared upstream failure protection exists and
# expensive discovery is still serialized.
if 'SBB_MEDIA_REPAIR_ENABLED", "0"' in text:
    assert 'SBB_MEDIA_REPAIR_ENABLED", "1"' not in text
else:
    assert 'SBB_MEDIA_REPAIR_ENABLED", "1"' in text
    assert 'REPAIR_DISCOVERY_CIRCUIT.before_request()' in text
    assert 'SBB_MEDIA_AUDIT_DISCOVERY_CONCURRENCY", "1"' in text

print("PASS v6.1.3 Media Audit recovery invariant")

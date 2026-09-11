#!/usr/bin/env python3
"""v6.1.4 deployment reliability and fast-path regression tests."""
from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
assert VERSION == "6.1.4", VERSION

validation = (ROOT / "sbb" / "canonical_validation_v612.py").read_text(encoding="utf-8")
assert 'deadline=_now()+120' not in validation
assert 'while True:' in validation
assert 'permanently losing /api/canonical/validation/*' in validation
assert 'parsed.path=="/api/canonical/validation/health"' in validation

deploy = (ROOT / "cloud" / "gcp" / "DEPLOY-FROM-GITHUB.sh").read_text(encoding="utf-8")
for token in (
    'backend_payload_hash.py',
    'FAST PATH: backend payload is unchanged.',
    'Skipping VM archive upload, service restarts, catalog preflight, Chrome/Selenium setup, and Media Audit restart.',
    'backend-payload.sha256',
    'SBB_BACKEND_PAYLOAD_HASH',
    'Recorded backend payload hash',
):
    assert token in deploy, token
assert deploy.index('FAST PATH: backend payload is unchanged.') < deploy.index('[storage] Reclaiming stale deployment-only storage before upload')

installer = (ROOT / "cloud" / "vm" / "INSTALL-MEDIA-AUDIT.sh").read_text(encoding="utf-8")
assert 'Reusing installed OS packages.' in installer
assert 'Reusing Selenium 4.27.1 virtual environment.' in installer
assert 'selenium.__version__=="4.27.1"' in installer
assert installer.count('apt-get update -y >/dev/null') <= 2
assert 'apt-get update -y >/dev/null\napt-get install -y python3-venv curl ca-certificates' not in installer

pages = (ROOT / "cloud" / "github-pages" / "build_pages.py").read_text(encoding="utf-8")
assert "GITHUB_SHA" in pages
assert "&b={build_sha}" in pages
assert "frontend-only commits intentionally keep the backend semantic VERSION" in pages

media = (ROOT / "media_audit_service.py").read_text(encoding="utf-8")
assert 'SBB_MEDIA_AUDIT_WORKERS", "1"' in media
assert 'SBB_MEDIA_AUDIT_DISCOVERY_CONCURRENCY", "1"' in media
assert 'SBB_MEDIA_REPAIR_ENABLED", "0"' in media

spec = importlib.util.spec_from_file_location("backend_payload_hash", ROOT / "tools" / "backend_payload_hash.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert mod.include_path(PurePosixPath("server.py"))
assert mod.include_path(PurePosixPath("sbb/history_repository.py"))
assert mod.include_path(PurePosixPath("cloud/vm/INSTALL-MEDIA-AUDIT.sh"))
assert mod.include_path(PurePosixPath("assets/soundtrack/manifest.json"))
for frontend in (
    "index.html",
    "app.js",
    "styles.css",
    "ui/league-view-v538.js",
    "architecture/key-info-current-v520.js",
    "cloud/github-pages/build_pages.py",
):
    assert not mod.include_path(PurePosixPath(frontend)), frontend

payload_hash = mod.digest(ROOT)
assert re.fullmatch(r"[0-9a-f]{64}", payload_hash), payload_hash

subprocess.run(["bash", "-n", str(ROOT / "cloud" / "gcp" / "DEPLOY-FROM-GITHUB.sh")], check=True)
subprocess.run(["bash", "-n", str(ROOT / "cloud" / "vm" / "INSTALL-MEDIA-AUDIT.sh")], check=True)
print("PASS: v6.1.4 deployment reliability + backend fast-path contracts")

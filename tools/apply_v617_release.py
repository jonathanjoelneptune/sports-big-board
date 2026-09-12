#!/usr/bin/env python3
"""Sports Big Board v6.1.7: promote v6.1.6 R21 continuous Media Audit."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE = "6.1.6"
NEW = "6.1.7"
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".sh", ".yml", ".yaml"}
ACTIVE_DIRS = ("ui", "architecture", "sbb", "tests", "cloud", ".github")


def active_files(root):
    seen = set()
    for p in sorted(root.iterdir()):
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:
            seen.add(p); yield p
    checker = root / "tools" / "check_release_version.py"
    if checker.is_file() and checker not in seen:
        seen.add(checker); yield checker
    for dirname in ACTIVE_DIRS:
        base = root / dirname
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
                continue
            rel = p.relative_to(root)
            if any(part.startswith("sports-big-board-v") for part in rel.parts):
                continue
            if p not in seen:
                seen.add(p); yield p


def run_base(root):
    (root / "VERSION").write_text(BASE + "\n", encoding="utf-8")
    arch = root / "architecture" / "VERSION"
    arch.parent.mkdir(parents=True, exist_ok=True)
    arch.write_text(BASE + "\n", encoding="utf-8")
    subprocess.run([sys.executable, str(root / "tools" / "apply_v616_release.py"), "--skip-check"], cwd=root, check=True)


def patch_legacy_media_test(root):
    path = root / "tests" / "test_v550_media_health_audit.py"
    text = path.read_text(encoding="utf-8")
    replacements = [
        ('AUDIT_GENERATION = "R20-PLAYBACK-EVIDENCE-CORROBORATION"', 'AUDIT_GENERATION = "R21-CONTINUOUS-ROLLING-REPAIR"'),
        ("assert 'R20-PLAYBACK-EVIDENCE-CORROBORATION' in service", "assert 'R21-CONTINUOUS-ROLLING-REPAIR' in service"),
        ("'R20_PLAYBACK_EVIDENCE_CORROBORATION','history_media_repair_source_attempt'", "'R21_CONTINUOUS_REPAIR','history_media_repair_source_attempt'"),
    ]
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new, 1)
        elif new not in text:
            raise SystemExit(f"ERROR: v6.1.7 legacy Media Audit test anchor missing: {old}")
    path.write_text(text, encoding="utf-8")


def patch_verify(root):
    path = root / "VERIFY.sh"
    text = path.read_text(encoding="utf-8")
    marker = "python3 tools/check_release_version.py"
    cmd = "python3 tests/test_v617_continuous_media_audit_release.py"
    if marker not in text:
        raise SystemExit("ERROR: VERIFY release checker anchor missing")
    if cmd not in text:
        text = text.replace(marker, marker + "\n" + cmd, 1)
    path.write_text(text, encoding="utf-8")


def promote(root):
    for p in active_files(root):
        try:
            source = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rendered = source.replace(BASE, NEW)
        if rendered != source:
            p.write_text(rendered, encoding="utf-8")
    for p in (root / "VERSION", root / "architecture" / "VERSION"):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(NEW + "\n", encoding="utf-8")


def controller(root):
    src = root / f"CONTROLLER-REGION-MAP-v{BASE}.md"
    dst = root / f"CONTROLLER-REGION-MAP-v{NEW}.md"
    if not src.is_file():
        raise SystemExit(f"ERROR: missing {src.name}")
    dst.write_text(src.read_text(encoding="utf-8").replace(BASE, NEW), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-check", action="store_true")
    args = ap.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    current = (root / "VERSION").read_text(encoding="utf-8").strip()
    if current != NEW:
        raise SystemExit(f"ERROR: expected VERSION {NEW}, got {current!r}")
    run_base(root)
    patch_legacy_media_test(root)
    patch_verify(root)
    promote(root)
    controller(root)
    print("Sports Big Board v6.1.7 materialized")
    print("R21 continuous Media Audit: yesterday-first rolling gaps, two repair workers, protected discovery")
    if args.skip_check:
        return 0
    subprocess.run([sys.executable, str(root / "tools" / "check_release_version.py")], cwd=root, check=True)
    print("PASS: deployment-critical release identity is synchronized at 6.1.7")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

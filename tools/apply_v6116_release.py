#!/usr/bin/env python3
"""Sports Big Board v6.1.16 official schedule watchdog materializer."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE = "6.1.15"
NEW = "6.1.16"
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".sh", ".yml", ".yaml"}
ACTIVE_DIRS = ("ui", "architecture", "sbb", "tests", "cloud", ".github")


def active_files(root):
    seen = set()
    for p in sorted(root.iterdir()):
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:
            seen.add(p)
            yield p
    checker = root / "tools" / "check_release_version.py"
    if checker.is_file() and checker not in seen:
        seen.add(checker)
        yield checker
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
                seen.add(p)
                yield p


def run_base(root):
    (root / "VERSION").write_text(BASE + "\n", encoding="utf-8")
    arch = root / "architecture" / "VERSION"
    arch.parent.mkdir(parents=True, exist_ok=True)
    arch.write_text(BASE + "\n", encoding="utf-8")
    subprocess.run([sys.executable, str(root / "tools" / "apply_v6115_release.py"), "--skip-check"], cwd=root, check=True)


def patch_init(root):
    path = root / "sbb" / "__init__.py"
    text = path.read_text(encoding="utf-8")
    if "_install_canonical_schedule_watchdog_v6116()" in text:
        return
    block = '''

# v6.1.16: official schedule-page watchdogs + authoritative fallback hardening.
# Shadow-only: this improves certification evidence and date correctness but does
# not make the canonical slate the production ribbon authority.
from .canonical_schedule_watchdog_v6116 import install as _install_canonical_schedule_watchdog_v6116
_install_canonical_schedule_watchdog_v6116()
'''
    path.write_text(text.rstrip() + block, encoding="utf-8")


def patch_verify(root):
    path = root / "VERIFY.sh"
    text = path.read_text(encoding="utf-8")
    marker = "python3 tools/check_release_version.py"
    commands = (
        "python3 -m py_compile sbb/canonical_schedule_watchdog_v6116.py",
        "python3 tests/test_v6116_schedule_watchdogs.py",
        "python3 tests/test_v6116_schedule_watchdog_release.py",
    )
    if marker not in text:
        raise SystemExit("ERROR: VERIFY release checker anchor missing")
    additions = [cmd for cmd in commands if cmd not in text]
    if additions:
        text = text.replace(marker, marker + "\n" + "\n".join(additions), 1)
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


def patch_compat_tests(root):
    """Preserve historical R24 behavior checks without pinning the repo to 6.1.15."""
    path = root / "tests" / "test_v6115_team_resolution_release.py"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    old = 'expected_version = ".".join(("6", "1", "15"))\nassert version == expected_version, version'
    new = 'expected_versions = {".".join(("6", "1", "15")), ".".join(("6", "1", "16"))}\nassert version in expected_versions, version'
    if old in text:
        text = text.replace(old, new, 1)
        path.write_text(text, encoding="utf-8")


def controller(root):
    src = root / f"CONTROLLER-REGION-MAP-v{BASE}.md"
    dst = root / f"CONTROLLER-REGION-MAP-v{NEW}.md"
    if not src.is_file():
        raise SystemExit(f"ERROR: missing {src.name}")
    dst.write_text(src.read_text(encoding="utf-8").replace(BASE, NEW), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-check", action="store_true")
    args = ap.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    current = (root / "VERSION").read_text(encoding="utf-8").strip()
    if current != NEW:
        raise SystemExit(f"ERROR: expected VERSION {NEW}, got {current!r}")
    required = [
        root / "tools" / "apply_v6115_release.py",
        root / "sbb" / "canonical_schedule_watchdog_v6116.py",
        root / "tests" / "test_v6116_schedule_watchdogs.py",
        root / "tests" / "test_v6116_schedule_watchdog_release.py",
    ]
    missing = [str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing:
        raise SystemExit("ERROR: incomplete v6.1.16 release: " + ", ".join(missing))
    if args.dry_run:
        print("v6.1.16: official schedule watchdogs + EPL/NFL/date repair")
        return 0
    run_base(root)
    patch_init(root)
    patch_verify(root)
    promote(root)
    patch_compat_tests(root)
    controller(root)
    print("Sports Big Board v6.1.16 materialized")
    print("Canonical schedule: EPL SDP fallback, NFL current week URLs, ET slate-date repair")
    print("Watchdogs: MLB/NBA/MLS/NHL official pages + NCAAF secondary-independent reference")
    if args.skip_check:
        return 0
    return subprocess.call([sys.executable, str(root / "tools" / "check_release_version.py")], cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())

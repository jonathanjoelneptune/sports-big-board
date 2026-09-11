#!/usr/bin/env python3
"""Sports Big Board v6.1.3 production-recovery checkout materializer.

The repository's v6.1.2 entry point delegates here when VERSION is 6.1.3.
This materializer first preserves the complete v6.1.2 release assembly, then
applies the smallest possible Media Audit recovery delta:
- one canonical audit worker by default;
- discovery concurrency remains one;
- persistent Media Repair defaults disabled until its upstream-failure circuit
  breaker is hardened and independently verified.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE = "6.1.2"
NEW = "6.1.3"
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".sh", ".yml", ".yaml"}
ACTIVE_DIRS = ("ui", "architecture", "sbb", "tests", "cloud", ".github")


def active_files(root: Path):
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


def run_v612_materializer(root: Path):
    """Materialize the already-certified v6.1.2 base before applying recovery delta."""
    version = root / "VERSION"
    architecture_version = root / "architecture" / "VERSION"
    version.write_text(BASE + "\n", encoding="utf-8")
    architecture_version.parent.mkdir(parents=True, exist_ok=True)
    architecture_version.write_text(BASE + "\n", encoding="utf-8")
    subprocess.run(
        [sys.executable, str(root / "tools" / "apply_v612_release.py"), "--skip-check"],
        cwd=root,
        check=True,
    )


def patch_media_audit(root: Path):
    path = root / "media_audit_service.py"
    text = path.read_text(encoding="utf-8")
    old_workers = 'AUDIT_WORKER_COUNT = max(1, min(4, int(os.environ.get("SBB_MEDIA_AUDIT_WORKERS", "3"))))'
    new_workers = 'AUDIT_WORKER_COUNT = max(1, min(4, int(os.environ.get("SBB_MEDIA_AUDIT_WORKERS", "1"))))'
    old_repair = 'REPAIR_ENABLED = str(os.environ.get("SBB_MEDIA_REPAIR_ENABLED", "1")).lower() in {"1","true","yes","on"}'
    new_repair = 'REPAIR_ENABLED = str(os.environ.get("SBB_MEDIA_REPAIR_ENABLED", "0")).lower() in {"1","true","yes","on"}'

    if old_workers in text:
        text = text.replace(old_workers, new_workers, 1)
    elif new_workers not in text:
        raise SystemExit("ERROR: Media Audit worker default contract not found")

    if old_repair in text:
        text = text.replace(old_repair, new_repair, 1)
    elif new_repair not in text:
        raise SystemExit("ERROR: Media Repair enabled-default contract not found")

    marker = 'AUDIT_WORKER_COUNT = max(1, min(4, int(os.environ.get("SBB_MEDIA_AUDIT_WORKERS", "1"))))'
    safe_comment = (
        "# v6.1.3 recovery safe mode: production API stability takes priority while the\n"
        "# persistent Repair Engine upstream-failure circuit breaker is hardened.\n"
    )
    if safe_comment not in text:
        text = text.replace(marker, safe_comment + marker, 1)
    path.write_text(text, encoding="utf-8")


def patch_verify(root: Path):
    path = root / "VERIFY.sh"
    text = path.read_text(encoding="utf-8")
    command = "python3 tests/test_v613_media_audit_safe_mode.py"
    if command not in text:
        marker = "python3 tools/check_release_version.py"
        if marker not in text:
            raise SystemExit("ERROR: VERIFY.sh release checker anchor missing")
        text = text.replace(marker, marker + "\n" + command, 1)
        path.write_text(text, encoding="utf-8")


def promote_release_identity(root: Path):
    changed = []
    for path in active_files(root):
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rendered = source.replace(BASE, NEW)
        if rendered != source:
            path.write_text(rendered, encoding="utf-8")
            changed.append(path)

    for path in (root / "VERSION", root / "architecture" / "VERSION"):
        if path.read_text(encoding="utf-8").strip() != NEW:
            path.write_text(NEW + "\n", encoding="utf-8")
            changed.append(path)
    return changed


def materialize_controller_map(root: Path):
    source = root / f"CONTROLLER-REGION-MAP-v{BASE}.md"
    target = root / f"CONTROLLER-REGION-MAP-v{NEW}.md"
    if not source.is_file():
        raise SystemExit(f"ERROR: missing {source.name} after v6.1.2 materialization")
    text = source.read_text(encoding="utf-8").replace(BASE, NEW)
    target.write_text(text, encoding="utf-8")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-check", action="store_true")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    current = (root / "VERSION").read_text(encoding="utf-8").strip()
    if current != NEW:
        raise SystemExit(f"ERROR: v6.1.3 materializer requires repository VERSION {NEW}, got {current!r}")

    required = [
        root / "tools" / "apply_v612_release.py",
        root / "tests" / "test_v613_media_audit_safe_mode.py",
        root / "media_audit_service.py",
        root / "VERIFY.sh",
    ]
    missing = [str(p.relative_to(root)) for p in required if not p.is_file()]
    if missing:
        raise SystemExit("ERROR: v6.1.3 recovery release incomplete: " + ", ".join(missing))

    if args.dry_run:
        print("Sports Big Board v6.1.3 recovery materialization would:")
        print("  preserve full v6.1.2 release materialization")
        print("  set Media Audit workers: 1")
        print("  keep Media Audit discovery concurrency: 1")
        print("  set persistent Media Repair default: disabled")
        print("  run test_v613_media_audit_safe_mode.py during VERIFY.sh")
        return 0

    run_v612_materializer(root)
    patch_media_audit(root)
    patch_verify(root)
    changed = promote_release_identity(root)
    controller = materialize_controller_map(root)

    print(f"Sports Big Board recovery release materialized: {NEW}")
    print("Media Audit defaults: workers=1 discoveryConcurrency=1 repairEnabled=0")
    print(f"Release-identity files updated: {len(changed)}")
    print(f"Controller map: {controller.name}")

    if args.skip_check:
        return 0

    subprocess.run([sys.executable, str(root / "tools" / "check_release_version.py")], cwd=root, check=True)
    print("PASS: deployment-critical release identity is synchronized at 6.1.3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

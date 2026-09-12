#!/usr/bin/env python3
"""Sports Big Board v6.1.14 team-directory ownership hardening materializer."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE = "6.1.13"
NEW = "6.1.14"
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
    tools = str(root / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import apply_v6113_release

    rc = apply_v6113_release.main(["--skip-check"])
    if rc not in (None, 0):
        raise SystemExit(rc)


def replace_once(text, old, new, label):
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"ERROR: v6.1.14 patch anchor missing: {label}")


def patch_runtime(root):
    service_path = root / "media_audit_service.py"
    service = service_path.read_text(encoding="utf-8")
    service = replace_once(
        service,
        "from sbb.media_team_sources_v6113 import TeamSourceRegistry\n",
        "from sbb.media_team_sources_v6114 import TeamSourceRegistry\n",
        "hardened team-directory runtime import",
    )
    service_path.write_text(service, encoding="utf-8")

    path = root / "tests" / "test_v6113_team_directory_resolution.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from sbb.media_team_sources_v6113 import TeamSourceRegistry",
        "from sbb.media_team_sources_v6114 import TeamSourceRegistry",
        "v6.1.13 fixture uses hardened resolver",
    )
    path.write_text(text, encoding="utf-8")

    path = root / "tests" / "test_v6113_team_directory_release.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from sbb.media_team_sources_v6113 import TeamSourceRegistry",
        "from sbb.media_team_sources_v6114 import TeamSourceRegistry",
        "v6.1.13 release contract uses hardened runtime",
    )
    text = replace_once(
        text,
        'expected_version = ".".join(("6", "1", "13"))',
        'expected_version = ".".join(("6", "1", "14"))',
        "v6.1.13 compatibility contract targets v6.1.14",
    )
    path.write_text(text, encoding="utf-8")

    # v6.1.13 promotes the legacy v6.1.12 runtime contract to the R23 module.
    # v6.1.14 then swaps in the ownership-scoped wrapper, so keep that historical
    # behavioral contract pointed at the actual final runtime module as well.
    path = root / "tests" / "test_v6112_team_source_release.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from sbb.media_team_sources_v6113 import TeamSourceRegistry",
        "from sbb.media_team_sources_v6114 import TeamSourceRegistry",
        "v6.1.12 compatibility contract uses hardened runtime",
    )
    path.write_text(text, encoding="utf-8")


def patch_verify(root):
    path = root / "VERIFY.sh"
    text = path.read_text(encoding="utf-8")
    marker = "python3 tools/check_release_version.py"
    commands = (
        "python3 -m py_compile sbb/media_team_sources_v6114.py",
        "python3 tests/test_v6114_team_directory_scoping.py",
        "python3 tests/test_v6114_team_directory_hardening_release.py",
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
        root / "tools" / "apply_v6113_release.py",
        root / "sbb" / "media_team_sources_v6114.py",
        root / "tests" / "test_v6114_team_directory_scoping.py",
        root / "tests" / "test_v6114_team_directory_hardening_release.py",
        root / "media_audit_service.py",
    ]
    missing = [str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing:
        raise SystemExit("ERROR: incomplete v6.1.14 release: " + ", ".join(missing))
    if args.dry_run:
        print("v6.1.14: semantic-card and JSON-object team ownership scoping")
        return 0

    run_base(root)
    patch_runtime(root)
    patch_verify(root)
    promote(root)
    controller(root)

    print("Sports Big Board v6.1.14 materialized")
    print("R23 team directory: authoritative resolution + bounded ownership context")
    print("HTML anchors bind to nearest team card/heading; JSON URLs bind to nearest object")
    if args.skip_check:
        return 0
    tools = str(root / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import check_release_version  # noqa: F401
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

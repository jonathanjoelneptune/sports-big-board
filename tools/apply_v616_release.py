#!/usr/bin/env python3
"""Sports Big Board v6.1.6 canonical slate-readiness materializer."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE = "6.1.5"
NEW = "6.1.6"
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
    import apply_v615_release
    rc = apply_v615_release.main(["--skip-check"])
    if rc not in (None, 0):
        raise SystemExit(rc)


def patch_install_chain(root):
    path = root / "sbb" / "__init__.py"
    text = path.read_text(encoding="utf-8")
    validation_call = "_install_canonical_validation_v612()"
    readiness_call = "_install_canonical_slate_readiness_v616()"
    if validation_call not in text:
        raise SystemExit("ERROR: canonical validation installer missing after v6.1.5 materialization")
    if readiness_call not in text:
        block = (
            "\n\n# v6.1.6: canonical slate readiness repair.\n"
            "# Shadow-only: storage throughput, NCAAF policy precedence, and canonical ET date ownership.\n"
            "from .canonical_slate_readiness_v616 import install as _install_canonical_slate_readiness_v616\n"
            "_install_canonical_slate_readiness_v616()"
        )
        text = text.replace(validation_call, validation_call + block, 1)
        path.write_text(text, encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    if text.index(validation_call) > text.index(readiness_call):
        raise SystemExit("ERROR: canonical slate readiness repair must install after validation")


def patch_verify(root):
    path = root / "VERIFY.sh"
    text = path.read_text(encoding="utf-8")
    commands = (
        "python3 tests/test_v616_canonical_slate_readiness.py",
        "python3 -m py_compile sbb/canonical_slate_readiness_v616.py",
    )
    anchor = "python3 tools/check_release_version.py"
    if anchor not in text:
        raise SystemExit("ERROR: VERIFY release-check anchor missing")
    additions = [cmd for cmd in commands if cmd not in text]
    if additions:
        path.write_text(text.replace(anchor, anchor + "\n" + "\n".join(additions), 1), encoding="utf-8")


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
        root / "tools" / "apply_v615_release.py",
        root / "sbb" / "canonical_slate_readiness_v616.py",
        root / "tests" / "test_v616_canonical_slate_readiness.py",
    ]
    missing = [str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing:
        raise SystemExit("ERROR: incomplete v6.1.6 release: " + ", ".join(missing))
    if args.dry_run:
        print("v6.1.6: preserve v6.1.5 and install canonical slate readiness after validation")
        return 0
    run_base(root)
    patch_install_chain(root)
    patch_verify(root)
    promote(root)
    controller(root)
    print("Sports Big Board v6.1.6 materialized")
    print("Canonical readiness: writable NORMAL sync + NCAAF state precedence + Eastern date comparison")
    if args.skip_check:
        return 0
    tools = str(root / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import check_release_version
    return check_release_version.main() if hasattr(check_release_version, "main") else 0


if __name__ == "__main__":
    raise SystemExit(main())

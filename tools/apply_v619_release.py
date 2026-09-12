#!/usr/bin/env python3
"""Sports Big Board v6.1.9 canonical identity/ingestion materializer."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE = "6.1.8"
NEW = "6.1.9"
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
    import apply_v618_release
    rc = apply_v618_release.main(["--skip-check"])
    if rc not in (None, 0):
        raise SystemExit(rc)


def patch_install_chain(root):
    path = root / "sbb" / "__init__.py"
    text = path.read_text(encoding="utf-8")
    hardening_call = "_install_canonical_certification_v611()"
    validation_call = "_install_canonical_validation_v612()"
    readiness_call = "_install_canonical_slate_readiness_v618()"
    identity_call = "_install_canonical_identity_ingestion_v619()"
    for required in (hardening_call, validation_call, readiness_call):
        if required not in text:
            raise SystemExit(f"ERROR: canonical install-chain prerequisite missing: {required}")
    if identity_call not in text:
        block = (
            "\n\n# v6.1.9: canonical identity + ingestion repair.\n"
            "# Shadow-only: ET ownership before upsert, conservative aliases, duplicate merge, NCAAF policy-aware counts.\n"
            "from .canonical_identity_ingestion_v619 import install as _install_canonical_identity_ingestion_v619\n"
            "_install_canonical_identity_ingestion_v619()"
        )
        text = text.replace(readiness_call, readiness_call + block, 1)
        path.write_text(text, encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    if not (
        text.index(hardening_call) < text.index(validation_call)
        < text.index(readiness_call) < text.index(identity_call)
    ):
        raise SystemExit("ERROR: canonical install order must be hardening -> validation -> readiness -> identity/ingestion")


def patch_verify(root):
    path = root / "VERIFY.sh"
    text = path.read_text(encoding="utf-8")
    marker = "python3 tools/check_release_version.py"
    commands = (
        "python3 tests/test_v619_canonical_identity_ingestion.py",
        "python3 -m py_compile sbb/canonical_identity_ingestion_v619.py",
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
        root / "tools" / "apply_v618_release.py",
        root / "sbb" / "canonical_identity_ingestion_v619.py",
        root / "tests" / "test_v619_canonical_identity_ingestion.py",
    ]
    missing = [str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing:
        raise SystemExit("ERROR: incomplete v6.1.9 release: " + ", ".join(missing))
    if args.dry_run:
        print("v6.1.9: preserve v6.1.8 + parallel UI work and install canonical identity/ingestion repair")
        return 0
    run_base(root)
    patch_install_chain(root)
    patch_verify(root)
    promote(root)
    controller(root)
    print("Sports Big Board v6.1.9 materialized")
    print("Canonical identity/ingestion: ET ownership + alias merge + NCAAF policy-aware validation")
    if args.skip_check:
        return 0
    tools = str(root / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import check_release_version  # noqa: F401 - importing executes release checker
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

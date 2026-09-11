#!/usr/bin/env python3
"""Sports Big Board v6.1.4 canonical-validation runtime hotfix.

Preserves the verified v6.1.3 Media Audit safe-mode recovery, then repairs the
canonical runtime install dependency chain. v6.1.2 validation diagnostics wait
for v6.1.1's hardened certification engine, so v611 must be installed before
v612 diagnostics are installed.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE = "6.1.3"
NEW = "6.1.4"
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


def run_v613_materializer(root: Path):
    version = root / "VERSION"
    architecture_version = root / "architecture" / "VERSION"
    version.write_text(BASE + "\n", encoding="utf-8")
    architecture_version.parent.mkdir(parents=True, exist_ok=True)
    architecture_version.write_text(BASE + "\n", encoding="utf-8")
    subprocess.run(
        [sys.executable, str(root / "tools" / "apply_v613_release.py"), "--skip-check"],
        cwd=root,
        check=True,
    )


def patch_canonical_install_chain(root: Path):
    path = root / "sbb" / "__init__.py"
    text = path.read_text(encoding="utf-8")

    v610_call = "_install_canonical_certification_v610()"
    v611_call = "_install_canonical_certification_v611()"
    v612_import = "from .canonical_validation_v612 import install as _install_canonical_validation_v612"

    if v610_call not in text:
        raise SystemExit("ERROR: v6.1.0 certification install anchor missing")

    v611_block = (
        "\n\n# v6.1.1: canonical certification hardening.\n"
        "# Must install before v6.1.2 validation diagnostics, which depend on v611.engine().\n"
        "from .canonical_certification_v611 import install as _install_canonical_certification_v611\n"
        "_install_canonical_certification_v611()\n"
    )

    if v611_call not in text:
        if v612_import in text:
            idx = text.index(v612_import)
            text = text[:idx].rstrip() + v611_block + "\n\n" + text[idx:]
        else:
            anchor = text.index(v610_call) + len(v610_call)
            text = text[:anchor] + v611_block + text[anchor:]

    if "_install_canonical_validation_v612()" not in text:
        text = text.rstrip() + (
            "\n\n# v6.1.2: unified canonical slate validation diagnostics + copy console.\n"
            "# Shadow-only: diagnostics and consistency checks never become production authority.\n"
            "from .canonical_validation_v612 import install as _install_canonical_validation_v612\n"
            "_install_canonical_validation_v612()\n"
        )

    pos610 = text.index(v610_call)
    pos611 = text.index(v611_call)
    pos612 = text.index("_install_canonical_validation_v612()")
    if not (pos610 < pos611 < pos612):
        raise SystemExit("ERROR: unsafe canonical install order; expected v610 -> v611 -> v612")

    path.write_text(text, encoding="utf-8")


def patch_verify(root: Path):
    path = root / "VERIFY.sh"
    text = path.read_text(encoding="utf-8")
    command = "python3 tests/test_v614_canonical_validation_install_chain.py"
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
        raise SystemExit(f"ERROR: missing {source.name} after v6.1.3 materialization")
    target.write_text(source.read_text(encoding="utf-8").replace(BASE, NEW), encoding="utf-8")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-check", action="store_true")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    current = (root / "VERSION").read_text(encoding="utf-8").strip()
    if current != NEW:
        raise SystemExit(f"ERROR: v6.1.4 materializer requires repository VERSION {NEW}, got {current!r}")

    required = [
        root / "tools" / "apply_v613_release.py",
        root / "tests" / "test_v614_canonical_validation_install_chain.py",
        root / "sbb" / "canonical_certification_v611.py",
        root / "sbb" / "canonical_validation_v612.py",
        root / "VERIFY.sh",
    ]
    missing = [str(p.relative_to(root)) for p in required if not p.is_file()]
    if missing:
        raise SystemExit("ERROR: v6.1.4 hotfix incomplete: " + ", ".join(missing))

    if args.dry_run:
        print("Sports Big Board v6.1.4 hotfix would:")
        print("  preserve full v6.1.3 Media Audit recovery")
        print("  install canonical v6.1.1 hardening before v6.1.2 validation diagnostics")
        print("  retain the production validation-health smoke gate")
        return 0

    run_v613_materializer(root)
    patch_canonical_install_chain(root)
    patch_verify(root)
    changed = promote_release_identity(root)
    controller = materialize_controller_map(root)

    print(f"Sports Big Board canonical-validation hotfix materialized: {NEW}")
    print("Canonical install chain: v610 -> v611 -> v612")
    print("Media Audit safe mode preserved: workers=1 discoveryConcurrency=1 repairEnabled=0")
    print(f"Release-identity files updated: {len(changed)}")
    print(f"Controller map: {controller.name}")

    if args.skip_check:
        return 0

    subprocess.run([sys.executable, str(root / "tools" / "check_release_version.py")], cwd=root, check=True)
    print("PASS: deployment-critical release identity is synchronized at 6.1.4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

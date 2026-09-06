#!/usr/bin/env python3
"""One-time atomic release identity sweep for Sports Big Board v6.0.0.

The repository intentionally enforces one semantic release identity across VERSION,
architecture/VERSION, index cache generations, active UI/runtime component constants,
and release tests.  This helper updates the current v5.5.0 active generation to v6.0.0
without touching historical README/upload artifacts or archived version directories.

Run from the repository root after copying the v6.0 overlay into place:
    python3 tools/apply_v600_release.py

Use --dry-run to list files that would change.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

OLD = "5.5.0"
NEW = "6.0.0"
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".sh", ".yml", ".yaml"}
ACTIVE_DIRS = ("ui", "architecture", "sbb", "tests", "cloud", ".github")
# Runtime root sources are scanned generically; historical release notes are .txt/.md
# and therefore remain untouched.  The helper itself lives under tools/ and is not
# rewritten, which keeps OLD=5.5.0 stable for safe repeat/dry-run behavior.


def active_files(root: Path):
    seen = set()
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        seen.add(path)
        yield path
    for dirname in ACTIVE_DIRS:
        base = root / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            # Historical packaged trees are not part of the active runtime generation.
            rel = path.relative_to(root)
            if any(part.startswith("sports-big-board-v") for part in rel.parts):
                continue
            if path not in seen:
                seen.add(path)
                yield path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-check", action="store_true")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    version_path = root / "VERSION"
    architecture_version = root / "architecture" / "VERSION"
    if not version_path.is_file():
        raise SystemExit("ERROR: run from a Sports Big Board repository containing VERSION")

    current = version_path.read_text(encoding="utf-8").strip()
    if current not in {OLD, NEW}:
        raise SystemExit(f"ERROR: expected source release {OLD} or {NEW}, found {current!r}")
    required = [root / "sbb" / "canonical_shadow_v600.py", root / "tests" / "test_v600_canonical_shadow.py"]
    missing = [str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing:
        raise SystemExit("ERROR: v6.0 overlay is incomplete: " + ", ".join(missing))

    # Patch the existing installer rather than shipping/replacing the entire file.
    init_path = root / "sbb" / "__init__.py"
    init_text = init_path.read_text(encoding="utf-8")
    installer = (
        "\n\n# v6.0.0: canonical event/slate shadow architecture. Production remains on Day State.\n"
        "from .canonical_shadow_v600 import install as _install_canonical_shadow_v600\n"
        "_install_canonical_shadow_v600()\n"
    )
    installer_changed = False
    if "_install_canonical_shadow_v600()" not in init_text:
        installer_changed = True
        if not args.dry_run:
            init_path.write_text(init_text.rstrip() + installer, encoding="utf-8")

    # Extend, rather than replace, the repository preflight so all existing tests stay intact.
    verify_path = root / "VERIFY.sh"
    verify_changed = False
    if verify_path.is_file():
        verify_text = verify_path.read_text(encoding="utf-8")
        additions = []
        if "tests/test_v600_canonical_shadow.py" not in verify_text:
            additions.append("python3 tests/test_v600_canonical_shadow.py")
        if "sbb/canonical_shadow_v600.py" not in verify_text:
            additions.append("python3 -m py_compile sbb/canonical_shadow_v600.py")
        if additions:
            verify_changed = True
            if not args.dry_run:
                marker = "python3 tools/check_release_version.py"
                block = "\n".join(additions)
                if marker in verify_text:
                    verify_text = verify_text.replace(marker, marker + "\n" + block, 1)
                else:
                    verify_text = verify_text.rstrip() + "\n" + block + "\n"
                verify_path.write_text(verify_text, encoding="utf-8")

    changes = []
    for path in active_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if OLD not in text:
            continue
        changes.append(path)
        if not args.dry_run:
            path.write_text(text.replace(OLD, NEW), encoding="utf-8")

    # These two files are the release authorities and are set explicitly even if the
    # overlay already installed 6.0.0 before this script runs.
    authority_changes = []
    for path in (version_path, architecture_version):
        if not path.is_file() or path.read_text(encoding="utf-8").strip() != NEW:
            authority_changes.append(path)
            if not args.dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(NEW + "\n", encoding="utf-8")

    patch_changes = []
    if installer_changed:
        patch_changes.append(init_path)
    if verify_changed:
        patch_changes.append(verify_path)
    changed = list(dict.fromkeys(changes + authority_changes + patch_changes))
    print(f"Sports Big Board release sync: {OLD} -> {NEW}")
    print(f"Files {'that would change' if args.dry_run else 'changed'}: {len(changed)}")
    for path in changed:
        print("  " + str(path.relative_to(root)))

    if args.dry_run or args.skip_check:
        return 0

    checker = root / "tools" / "check_release_version.py"
    if checker.is_file():
        result = subprocess.run([sys.executable, str(checker)], cwd=root)
        if result.returncode:
            print("ERROR: release-integrity checker failed after v6.0 sweep", file=sys.stderr)
            return result.returncode
        print("PASS: release identity is synchronized at 6.0.0")
    else:
        print("WARNING: tools/check_release_version.py not found; release identity was not independently checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

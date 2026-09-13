#!/usr/bin/env python3
"""Sports Big Board v6.1.16 official schedule watchdog release materializer."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE = "6.1.15"
NEW = "6.1.16"
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".sh", ".yml", ".yaml"}
ACTIVE_DIRS = ("ui", "architecture", "sbb", "tests", "cloud", ".github")
PRESERVE = (
    "sbb/canonical_schedule_watchdogs_v6116.py",
    "sbb/canonical_reconciliation_hotfix_v6116.py",
    "tests/test_v6116_official_schedule_watchdogs.py",
    "tests/test_v6116_official_schedule_release.py",
    "tests/test_v6116_canonical_reconcile_hotfix.py",
)


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


def run_base(root, preserved):
    (root / "VERSION").write_text(BASE + "\n", encoding="utf-8")
    arch = root / "architecture" / "VERSION"
    arch.parent.mkdir(parents=True, exist_ok=True)
    arch.write_text(BASE + "\n", encoding="utf-8")
    subprocess.run([sys.executable, str(root / "tools" / "apply_v6115_release.py"), "--skip-check"], cwd=root, check=True)
    for rel, content in preserved.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def patch_init(root):
    """Wire v6.1.16 on legacy startup or the parallel P1 startup registry."""
    init_path = root / "sbb" / "__init__.py"
    startup_path = root / "sbb" / "startup.py"
    init_text = init_path.read_text(encoding="utf-8")

    if startup_path.is_file() and "from .startup import" in init_text and "bootstrap()" in init_text:
        text = startup_path.read_text(encoding="utf-8")
        reg_anchor = '    StartupRegistration("canonical-certification-v610", "canonical_certification_v610"),'
        reg_line = '    StartupRegistration("canonical-reconcile-v6116", "canonical_reconciliation_hotfix_v6116"),'
        phase_anchor = '    StartupPhase("canonical-certification", ("canonical-certification-v610",), ("canonical-certification-v610",)),'
        phase_line = '    StartupPhase("canonical-reconcile-v6116", ("canonical-reconcile-v6116",), ("canonical-reconcile-v6116",)),'
        rendered = text
        if reg_line not in rendered:
            if reg_anchor not in rendered:
                raise SystemExit("ERROR: startup registry canonical registration anchor missing")
            rendered = rendered.replace(reg_anchor, reg_anchor + "\n" + reg_line, 1)
        if phase_line not in rendered:
            if phase_anchor not in rendered:
                raise SystemExit("ERROR: startup registry canonical phase anchor missing")
            rendered = rendered.replace(phase_anchor, phase_anchor + "\n" + phase_line, 1)
        if rendered != text:
            startup_path.write_text(rendered, encoding="utf-8")
        return

    additions = []
    if "_install_canonical_schedule_watchdogs_v6116()" not in init_text:
        additions.append(
            "# v6.1.16: official schedule-page watchdogs + canonical adapter/date repairs.\n"
            "# Shadow/certification only; this layer does not become production event authority.\n"
            "from .canonical_schedule_watchdogs_v6116 import install as _install_canonical_schedule_watchdogs_v6116\n"
            "_install_canonical_schedule_watchdogs_v6116()"
        )
    if "_install_canonical_reconciliation_hotfix_v6116()" not in init_text:
        additions.append(
            "# v6.1.16 hotfix: exact NFL week proof + guarded NCAAF identity reconciliation.\n"
            "# Shadow/certification only; production Day State/ribbon authority is unchanged.\n"
            "from .canonical_reconciliation_hotfix_v6116 import install as _install_canonical_reconciliation_hotfix_v6116\n"
            "_install_canonical_reconciliation_hotfix_v6116()"
        )
    if additions:
        init_path.write_text(init_text.rstrip() + "\n\n" + "\n\n".join(additions) + "\n", encoding="utf-8")


def patch_legacy_contracts(root):
    tests = root / "tests"
    if not tests.is_dir():
        return
    for path in tests.glob("test_v611*_release.py"):
        text = path.read_text(encoding="utf-8")
        rendered = text
        rendered = rendered.replace(
            'forward_version = ".".join(("6", "1", "15"))',
            'forward_version = ".".join(("6", "1", "16"))',
        )
        if path.name == "test_v6115_team_resolution_release.py":
            rendered = rendered.replace(
                "assert version == expected_version, version",
                'assert version in {expected_version, ".".join(("6", "1", "16"))}, version',
                1,
            )
        if rendered != text:
            path.write_text(rendered, encoding="utf-8")


def patch_verify(root):
    path = root / "VERIFY.sh"
    text = path.read_text(encoding="utf-8")
    marker = "python3 tools/check_release_version.py"
    additions = [
        "python3 -m py_compile sbb/canonical_schedule_watchdogs_v6116.py",
        "python3 tests/test_v6116_official_schedule_watchdogs.py",
        "python3 tests/test_v6116_official_schedule_release.py",
        "python3 -m py_compile sbb/canonical_reconciliation_hotfix_v6116.py",
        "python3 tests/test_v6116_canonical_reconcile_hotfix.py",
    ]
    missing = [x for x in additions if x not in text]
    if missing:
        if marker not in text:
            raise SystemExit("ERROR: VERIFY release checker anchor missing")
        text = text.replace(marker, marker + "\n" + "\n".join(missing), 1)
        path.write_text(text, encoding="utf-8")


def promote(root):
    preserved = {root / rel for rel in PRESERVE}
    for p in active_files(root):
        if p in preserved:
            continue
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
        root / "tools" / "apply_v6115_release.py",
        root / "sbb" / "canonical_schedule_watchdogs_v6116.py",
        root / "sbb" / "canonical_reconciliation_hotfix_v6116.py",
        root / "tests" / "test_v6116_official_schedule_watchdogs.py",
        root / "tests" / "test_v6116_official_schedule_release.py",
        root / "tests" / "test_v6116_canonical_reconcile_hotfix.py",
    ]
    missing = [str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing:
        raise SystemExit("ERROR: incomplete v6.1.16 release: " + ", ".join(missing))
    if args.dry_run:
        print("v6.1.16: official schedule watchdogs + exact NFL/NCAAF canonical reconciliation hotfix")
        return 0
    preserved = {rel: (root / rel).read_text(encoding="utf-8") for rel in PRESERVE}
    run_base(root, preserved)
    patch_init(root)
    patch_legacy_contracts(root)
    patch_verify(root)
    promote(root)
    controller(root)
    print("Sports Big Board v6.1.16 materialized")
    print("Canonical schedule: exact NFL week proof/final rows + guarded NCAAF alias/drift reconciliation")
    print("Watchdogs: EPL NFL MLB NBA MLS NHL official pages; NCAAF FBSchedules secondary only")
    if args.skip_check:
        return 0
    return subprocess.call(["bash", "VERIFY.sh"], cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())

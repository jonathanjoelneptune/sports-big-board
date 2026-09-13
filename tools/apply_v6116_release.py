#!/usr/bin/env python3
"""Sports Big Board v6.1.16 R25 Media Repair yield materializer."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE = "6.1.15"
NEW = "6.1.16"
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".sh", ".yml", ".yaml"}
ACTIVE_DIRS = ("ui", "architecture", "sbb", "tests", "cloud", ".github")
R25_FILES = (
    "sbb/media_team_seed_v6116.py",
    "sbb/media_team_sources_v6116.py",
    "sbb/media_repair_yield_v6116.py",
    "tests/test_v6116_team_seed_directory.py",
    "tests/test_v6116_media_repair_yield_release.py",
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


def run_base(root):
    (root / "VERSION").write_text(BASE + "\n", encoding="utf-8")
    arch = root / "architecture" / "VERSION"
    arch.parent.mkdir(parents=True, exist_ok=True)
    arch.write_text(BASE + "\n", encoding="utf-8")
    subprocess.run(
        [sys.executable, str(root / "tools" / "apply_v6115_release.py"), "--skip-check"],
        cwd=root, check=True,
    )


def replace_once(text, old, new, label):
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"ERROR: v6.1.16 patch anchor missing: {label}")


def restore_r25_version_tokens(root):
    """Older chained materializers must not rewrite future R25 version literals."""
    for rel in R25_FILES:
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        rendered = text.replace("6.1.156", NEW).replace("6.1.166", NEW)
        if rendered != text:
            path.write_text(rendered, encoding="utf-8")


def normalize_generated_version_tokens(root):
    """Repair impossible version artifacts created by legacy substring promotion."""
    bad_tokens = ("6.1.155", "6.1.156", "6.1.165", "6.1.166")
    for path in active_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rendered = text
        for token in bad_tokens:
            rendered = rendered.replace(token, NEW)
        if rendered != text:
            path.write_text(rendered, encoding="utf-8")


def patch_seed_loader(root):
    """Normalize the raw seed block so non-row continuation text is ignored."""
    path = root / "sbb" / "media_team_seed_v6116.py"
    text = path.read_text(encoding="utf-8")
    old = """for _line in _DATA.splitlines():
    if not _line.strip():
        continue
    _league, _team, _aliases, _url, _role = _line.split("|", 4)
"""
    new = """for _line in _DATA.splitlines():
    if not _line.strip() or _line.count("|") < 4:
        continue
    _league, _team, _aliases, _url, _role = _line.split("|", 4)
"""
    text = replace_once(text, old, new, "authoritative seed row parser")
    path.write_text(text, encoding="utf-8")


def patch_media_audit(root):
    path = root / "media_audit_service.py"
    text = path.read_text(encoding="utf-8")

    anchor = "STORE = AuditStore(DB_PATH)\n"
    installer = """# R25: install repair-yield controls after R24 class definitions and before
# persistent stores/workers are constructed.
from sbb.media_repair_yield_v6116 import install as _install_media_repair_yield_v6116
SBB_MEDIA_REPAIR_YIELD_V6116 = _install_media_repair_yield_v6116(globals())

STORE = AuditStore(DB_PATH)
"""
    text = replace_once(text, anchor, installer, "R25 repair-yield installer")

    text = replace_once(
        text,
        "        if REPAIR_DISCOVERY_SETTLE_SECONDS: time.sleep(REPAIR_DISCOVERY_SETTLE_SECONDS)\n",
        "        if REPAIR_DISCOVERY_SETTLE_SECONDS and not result.get('skipped'): time.sleep(REPAIR_DISCOVERY_SETTLE_SECONDS)\n",
        "conditional provider discovery settle",
    )
    path.write_text(text, encoding="utf-8")


def patch_ui(root):
    path = root / "ui" / "media-audit-v550.js"
    text = path.read_text(encoding="utf-8")
    old = """  setText('repairSourceStats',`${fmtNum(rs.sourceAttempts||0)} source stages • ${fmtNum(rs.sourceResults||0)} results • ${fmtNum(rs.sourceNew||0)} new • ${fmtNum(rs.sourceDuplicates||0)} known • ${fmtNum(rs.sourceEligibleKnown||0)} eligible known • ${fmtNum(rs.sourceRejected||0)} rejected • ${fmtNum(rs.knownTransportRefreshes||0)} transport refreshes • ${fmtNum(rs.youtubeIndexedVideos||0)} YT indexed • ${fmtNum(rs.youtubeSearchQuotaBlocks||0)} search quota blocks`);
"""
    new = """  setText('repairSourceStats',`${fmtNum(rs.sourceAttempts||0)} source stages • ${fmtNum(rs.sourceResults||0)} results • ${fmtNum(rs.sourceNew||0)} new • ${fmtNum(rs.sourceDuplicates||0)} known • ${fmtNum(rs.sourceEligibleKnown||0)} eligible known • ${fmtNum(rs.sourceRejected||0)} rejected • ${fmtNum(rs.rejectionMemorySkips||0)} remembered rejects skipped • ${fmtNum(rs.rejectionMemoryWrites||0)} reject memories • ${fmtNum(rs.stageSkipsQuota||0)} quota-stage skips • ${fmtNum(rs.stageSkipsCircuit||0)} circuit-stage skips • ${fmtNum(rs.knownTransportRefreshes||0)} transport refreshes • ${fmtNum(rs.youtubeIndexedVideos||0)} YT indexed • ${fmtNum(rs.youtubeSearchQuotaBlocks||0)} search quota blocks`);
"""
    text = replace_once(text, old, new, "repair-yield telemetry UI")
    old_team = """  setText('repairTeamSources',`${fmtNum(ts.resolvedTeams||0)} resolved • ${fmtNum(ts.leagueTeamPages||0)} league pages • ${fmtNum(ts.leagueReferredOfficialSites||0)} official sites • ${fmtNum(ts.youtubeChannels||0)} YT channels • ${fmtNum(ts.indexedVideos||0)} videos indexed`);
"""
    new_team = """  setText('repairTeamSources',`${fmtNum(ts.resolvedTeams||0)} resolved • ${fmtNum(ts.seededTeams||0)}/${fmtNum(ts.seedEntries||0)} manual seeds active • ${fmtNum(ts.leagueTeamPages||0)} league pages • ${fmtNum(ts.leagueReferredOfficialSites||0)} official sites • ${fmtNum(ts.youtubeChannels||0)} YT channels • ${fmtNum(ts.indexedVideos||0)} videos indexed`);
"""
    text = replace_once(text, old_team, new_team, "manual team seed telemetry UI")
    path.write_text(text, encoding="utf-8")


def patch_verify(root):
    path = root / "VERIFY.sh"
    text = path.read_text(encoding="utf-8")
    marker = "python3 tools/check_release_version.py"
    commands = (
        "python3 -m py_compile sbb/media_team_seed_v6116.py sbb/media_team_sources_v6116.py sbb/media_repair_yield_v6116.py",
        "python3 tests/test_v6116_team_seed_directory.py",
        "python3 tests/test_v6116_media_repair_yield_release.py",
    )
    additions = [c for c in commands if c not in text]
    if additions:
        if marker not in text:
            raise SystemExit("ERROR: VERIFY release checker anchor missing")
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
    if src.is_file():
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
        root / "sbb" / "media_team_seed_v6116.py",
        root / "sbb" / "media_team_sources_v6116.py",
        root / "sbb" / "media_repair_yield_v6116.py",
        root / "tests" / "test_v6116_team_seed_directory.py",
        root / "tests" / "test_v6116_media_repair_yield_release.py",
    ]
    missing = [str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing:
        raise SystemExit("ERROR: incomplete v6.1.16 release: " + ", ".join(missing))
    if args.dry_run:
        print("v6.1.16: R25 repair yield + authoritative team seed directory")
        return 0

    run_base(root)
    restore_r25_version_tokens(root)
    patch_seed_loader(root)
    patch_media_audit(root)
    patch_ui(root)
    patch_verify(root)
    promote(root)
    normalize_generated_version_tokens(root)
    controller(root)

    print("Sports Big Board v6.1.16 materialized")
    print("R25 repair yield: persistent rejection memory + conditional source gates")
    print("Team sources: 218 explicit first-party seeds with R24 resolution/requeue semantics")
    if args.skip_check:
        return 0
    checker = root / "tools" / "check_release_version.py"
    if checker.is_file():
        result = subprocess.run([sys.executable, str(checker)], cwd=root)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

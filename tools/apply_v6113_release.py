#!/usr/bin/env python3
"""Sports Big Board v6.1.13 authoritative team-directory Media Repair materializer."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE = "6.1.12"
NEW = "6.1.13"
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
    import apply_v6112_release

    rc = apply_v6112_release.main(["--skip-check"])
    if rc not in (None, 0):
        raise SystemExit(rc)


def replace_once(text, old, new, label):
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"ERROR: v6.1.13 patch anchor missing: {label}")


def patch_media_audit(root):
    path = root / "media_audit_service.py"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "from sbb.media_team_sources_v6112 import TeamSourceRegistry\n",
        "from sbb.media_team_sources_v6113 import TeamSourceRegistry\n",
        "R23 team-source registry import",
    )

    old_stats = (
        '"youtubeIndexedVideos":0,"youtubeFallbackSearches":0,"youtubeSearchQuotaBlocks":0,'
        '"cooldownPreserved":0,"teamSourceChecks":0,"teamSourcesVerified":0,'
        '"teamYouTubeChannels":0,"teamYouTubeIndexedVideos":0,"teamSourceCandidates":0}'
    )
    new_stats = (
        '"youtubeIndexedVideos":0,"youtubeFallbackSearches":0,"youtubeSearchQuotaBlocks":0,'
        '"cooldownPreserved":0,"teamSourceChecks":0,"teamSourcesVerified":0,'
        '"teamYouTubeChannels":0,"teamYouTubeIndexedVideos":0,"teamSourceCandidates":0,'
        '"teamDirectoryFetches":0,"teamDirectoryCacheHits":0,"teamDirectoryErrors":0,'
        '"teamLeaguePagesResolved":0,"teamOfficialSitesResolved":0}'
    )
    text = replace_once(text, old_stats, new_stats, "R23 directory telemetry counters")

    old_accum = """        self.stats['teamSourceCandidates']+=len(team_candidates)
        self._record_stage(
"""
    new_accum = """        self.stats['teamSourceCandidates']+=len(team_candidates)
        self.stats['teamDirectoryFetches']+=int(team_refresh.get('directoryFetches') or 0)
        self.stats['teamDirectoryCacheHits']+=int(team_refresh.get('directoryCacheHits') or 0)
        self.stats['teamDirectoryErrors']+=int(team_refresh.get('directoryErrors') or 0)
        self.stats['teamLeaguePagesResolved']+=int(team_refresh.get('leaguePagesResolved') or 0)
        self.stats['teamOfficialSitesResolved']+=int(team_refresh.get('officialSites') or 0)
        self._record_stage(
"""
    text = replace_once(text, old_accum, new_accum, "R23 directory telemetry accumulation")

    text = text.replace("R22_TEAM_SOURCE_REGISTRY", "R23_TEAM_DIRECTORY_RESOLUTION")
    text = text.replace("R22-CONTINUOUS-TEAM-SOURCES", "R23-CONTINUOUS-TEAM-DIRECTORY")
    text = text.replace(
        "R22 official team-source registry",
        "R23 authoritative team-directory registry",
    )
    text = text.replace(
        "R22 known/provider/team-source/media-repair ladder exhausted without a certified candidate",
        "R23 known/provider/team-directory/media-repair ladder exhausted without a certified candidate",
    )
    path.write_text(text, encoding="utf-8")


def patch_legacy_runtime_contracts(root):
    replacements = (
        ("R22-CONTINUOUS-TEAM-SOURCES", "R23-CONTINUOUS-TEAM-DIRECTORY"),
        ("R22_TEAM_SOURCE_REGISTRY", "R23_TEAM_DIRECTORY_RESOLUTION"),
    )
    for rel in (
        "tests/test_v617_continuous_media_audit_release.py",
        "tests/test_v550_media_health_audit.py",
        "tests/test_v6112_team_source_release.py",
    ):
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        rendered = text
        for old, new in replacements:
            rendered = rendered.replace(old, new)
        if rel.endswith("test_v6112_team_source_release.py"):
            rendered = rendered.replace(
                "from sbb.media_team_sources_v6112 import TeamSourceRegistry",
                "from sbb.media_team_sources_v6113 import TeamSourceRegistry",
            )
        if rendered != text:
            path.write_text(rendered, encoding="utf-8")

    # v6.1.6 validates current runtime tokens but also intentionally checks its
    # historical R21 materializer later in the same file. Promote only the runtime
    # token entries generated by v6.1.12.
    path = root / "tests" / "test_v616_continuous_media_audit.py"
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        rendered = replace_once(
            text,
            "    'R22-CONTINUOUS-TEAM-SOURCES',",
            "    'R23-CONTINUOUS-TEAM-DIRECTORY',",
            "v6.1.6 current runtime generation",
        )
        rendered = replace_once(
            rendered,
            "    'R22_TEAM_SOURCE_REGISTRY',",
            "    'R23_TEAM_DIRECTORY_RESOLUTION',",
            "v6.1.6 current runtime strategy",
        )
        if rendered != text:
            path.write_text(rendered, encoding="utf-8")


def patch_verify(root):
    path = root / "VERIFY.sh"
    text = path.read_text(encoding="utf-8")
    marker = "python3 tools/check_release_version.py"
    commands = (
        "python3 -m py_compile sbb/media_team_sources_v6113.py",
        "python3 tests/test_v6113_team_directory_resolution.py",
        "python3 tests/test_v6113_team_directory_release.py",
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
        root / "tools" / "apply_v6112_release.py",
        root / "sbb" / "media_team_sources_v6113.py",
        root / "tests" / "test_v6113_team_directory_resolution.py",
        root / "tests" / "test_v6113_team_directory_release.py",
        root / "media_audit_service.py",
    ]
    missing = [str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing:
        raise SystemExit("ERROR: incomplete v6.1.13 release: " + ", ".join(missing))
    if args.dry_run:
        print("v6.1.13: authoritative league-directory -> team-site -> YouTube resolution")
        return 0

    run_base(root)
    patch_media_audit(root)
    patch_legacy_runtime_contracts(root)
    patch_verify(root)
    promote(root)
    controller(root)

    print("Sports Big Board v6.1.13 materialized")
    print("Media Repair R23: league/provider -> authoritative team directory -> generic search")
    print("Team identities: persistent league directory cache; no guessed league team slugs")
    if args.skip_check:
        return 0
    tools = str(root / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import check_release_version  # noqa: F401

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

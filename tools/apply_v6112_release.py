#!/usr/bin/env python3
"""Sports Big Board v6.1.12 official team-source Media Repair materializer."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE = "6.1.11"
NEW = "6.1.12"
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".sh", ".yml", ".yaml"}
ACTIVE_DIRS = ("ui", "architecture", "sbb", "tests", "cloud", ".github")


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
    tools = str(root / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import apply_v6111_release
    rc = apply_v6111_release.main(["--skip-check"])
    if rc not in (None, 0):
        raise SystemExit(rc)


def replace_once(text, old, new, label):
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"ERROR: v6.1.12 patch anchor missing: {label}")


def patch_media_audit(root):
    path = root / "media_audit_service.py"
    text = path.read_text(encoding="utf-8")

    import_anchor = "from sbb.media_audit_continuous import DiscoveryCircuitBreaker, RollingAuditCoordinator\n"
    import_line = "from sbb.media_team_sources_v6112 import TeamSourceRegistry\n"
    if import_line not in text:
        if import_anchor not in text:
            raise SystemExit("ERROR: continuous Media Audit import anchor missing")
        text = text.replace(import_anchor, import_anchor + import_line, 1)

    youtube_line = '        self.youtube=YouTubeGateway(user_agent=f"SportsBigBoard-MediaRepair/{APP_VERSION}-{AUDIT_GENERATION}",state_file=STATE_DIR/"cache"/"media-repair-youtube-state.json")\n'
    registry_line = (
        youtube_line
        + '        self.team_sources=TeamSourceRegistry(store,STATE_DIR/"cache"/"media-team-sources.sqlite",user_agent=f"SportsBigBoard-TeamSources/{APP_VERSION}-{AUDIT_GENERATION}")\n'
    )
    text = replace_once(text, youtube_line, registry_line, "TeamSourceRegistry worker initialization")

    stats_old = '"youtubeIndexedVideos":0,"youtubeFallbackSearches":0,"youtubeSearchQuotaBlocks":0,"cooldownPreserved":0}'
    stats_new = '"youtubeIndexedVideos":0,"youtubeFallbackSearches":0,"youtubeSearchQuotaBlocks":0,"cooldownPreserved":0,"teamSourceChecks":0,"teamSourcesVerified":0,"teamYouTubeChannels":0,"teamYouTubeIndexedVideos":0,"teamSourceCandidates":0}'
    text = replace_once(text, stats_old, stats_new, "team-source Repair telemetry")

    snapshot_old = 'return {"alive":self.is_alive(),"enabled":REPAIR_ENABLED,"workerIndex":self.worker_index,"seedOwner":self.seed_owner,"current":cur,"lastError":self.last_error,"stats":stats,"trace":trace}'
    snapshot_new = 'return {"alive":self.is_alive(),"enabled":REPAIR_ENABLED,"workerIndex":self.worker_index,"seedOwner":self.seed_owner,"current":cur,"lastError":self.last_error,"stats":stats,"trace":trace,"teamSources":self.team_sources.snapshot()}'
    text = replace_once(text, snapshot_old, snapshot_new, "team-source status snapshot")

    generic_comment = '''        # Stage 3: scarce generic search quota only for NO_MEDIA/UNPLAYABLE or a
        # later DEGRADED retry. Quota-blocked work sleeps until the gateway reset.
'''
    team_stage = '''        # Stage 3: official team-specific sources.  League/provider-wide discovery
        # stays first for breadth; only unresolved work falls through to the home
        # and away team registry. Verified team web pages seed/verify YouTube
        # channels, whose bounded uploads playlists are indexed without search.list.
        team_result={"candidates":[],"results":0,"duplicates":0,"rejected":0,"refresh":{}}
        try:
            with REPAIR_EXTERNAL_SEMAPHORE:
                team_result=self.team_sources.candidates_for_event(
                    context,self.youtube,get_secret('YOUTUBE_API_KEY',APP_ROOT),known,self._match_candidate,
                    max_candidates=REPAIR_CANDIDATE_LIMIT,stop_event=self.stop_event,
                )
        except Exception as exc:
            self._trace('WARN','Official team-source repair stage failed safely',event=event_key,error=f'{type(exc).__name__}: {exc}')
            team_result={"candidates":[],"results":0,"duplicates":0,"rejected":0,"refresh":{"error":f'{type(exc).__name__}: {exc}'}}
        team_candidates=list(team_result.get('candidates') or [])
        team_refresh=dict(team_result.get('refresh') or {})
        self.stats['teamSourceChecks']+=len(team_refresh.get('teams') or [])
        self.stats['teamSourcesVerified']+=int(team_refresh.get('verifiedWeb') or 0)
        self.stats['teamYouTubeChannels']+=int(team_refresh.get('youtubeChannels') or 0)
        self.stats['teamYouTubeIndexedVideos']+=int(team_refresh.get('indexedVideos') or 0)
        self.stats['teamSourceCandidates']+=len(team_candidates)
        self._record_stage(
            job,'OFFICIAL_TEAM_SOURCES',provider='TEAM_SOURCE_REGISTRY',results=int(team_result.get('results') or 0),
            new=len(team_candidates),duplicates=int(team_result.get('duplicates') or 0),rejected=int(team_result.get('rejected') or 0),
            details={"generation":"R22_TEAM_SOURCE_REGISTRY","refresh":team_refresh,"registry":self.team_sources.snapshot()},
        )
        if team_candidates:
            self._write('ingest official team-source YouTube candidates','ingest_repair_youtube_candidates',int(job['id']),event_key,team_candidates,event_key=event_key)
            self.stats['newCandidates']+=len(team_candidates)
            keys={'yt:'+str(x.get('youtubeId')) for x in team_candidates if x.get('youtubeId')}; total_new.extend(sorted(keys)); known.update(keys)
            candidates=[a for a in self.store.repair_event_assets(event_key) if a.get('assetKey') in keys]
            promoted=self._certify_candidates(job,candidates,target,'R22 official team-source registry',tested=tested)
            if promoted and promoted.get('health')=='HEALTHY': return promoted
            if promoted: fallback=promoted; target='PREFERRED'

        # Stage 4: scarce generic search quota only for NO_MEDIA/UNPLAYABLE or a
        # later DEGRADED retry. Quota-blocked work sleeps until the gateway reset.
'''
    text = replace_once(text, generic_comment, team_stage, "team-specific repair stage ordering")

    text = text.replace("R21_CONTINUOUS_REPAIR", "R22_TEAM_SOURCE_REGISTRY")
    text = text.replace("R21-CONTINUOUS-ROLLING-REPAIR", "R22-CONTINUOUS-TEAM-SOURCES")
    text = text.replace(
        "R19 known-candidate recovery + media-repair transport ladder exhausted without a certified candidate",
        "R22 known/provider/team-source/media-repair ladder exhausted without a certified candidate",
    )

    path.write_text(text, encoding="utf-8")


def patch_legacy_r21_contracts(root):
    """Keep R21 safety tests durable while R22 extends the repair source ladder."""
    replacements = (
        ('R21-CONTINUOUS-ROLLING-REPAIR', 'R22-CONTINUOUS-TEAM-SOURCES'),
        ('R21_CONTINUOUS_REPAIR', 'R22_TEAM_SOURCE_REGISTRY'),
    )
    for rel in ("tests/test_v617_continuous_media_audit_release.py", "tests/test_v550_media_health_audit.py"):
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        rendered = text
        for old, new in replacements:
            rendered = rendered.replace(old, new)
        if rendered == text and not all(new in text for _, new in replacements):
            raise SystemExit(f"ERROR: v6.1.12 legacy R21 contract anchors missing in {rel}")
        if rendered != text:
            path.write_text(rendered, encoding="utf-8")


def patch_verify(root):
    path = root / "VERIFY.sh"
    text = path.read_text(encoding="utf-8")
    marker = "python3 tools/check_release_version.py"
    commands = (
        "python3 -m py_compile sbb/media_team_sources_v6112.py",
        "python3 tests/test_v6112_team_source_registry.py",
        "python3 tests/test_v6112_team_source_release.py",
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
        root / "tools" / "apply_v6111_release.py",
        root / "sbb" / "media_team_sources_v6112.py",
        root / "tests" / "test_v6112_team_source_registry.py",
        root / "tests" / "test_v6112_team_source_release.py",
        root / "media_audit_service.py",
    ]
    missing = [str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing:
        raise SystemExit("ERROR: incomplete v6.1.12 release: " + ", ".join(missing))
    if args.dry_run:
        print("v6.1.12: official team web/YouTube registry between league-wide and generic Repair discovery")
        return 0
    run_base(root)
    patch_media_audit(root)
    patch_legacy_r21_contracts(root)
    patch_verify(root)
    promote(root)
    controller(root)
    print("Sports Big Board v6.1.12 materialized")
    print("Media Repair: league/provider -> official team web+YouTube -> generic search")
    print("Team sources: persistent separate SQLite registry; home+away; strict two-participant/date matching")
    if args.skip_check:
        return 0
    tools = str(root / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import check_release_version  # noqa: F401
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

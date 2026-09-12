import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "nfl_club_sources_under_test", ROOT / "sbb" / "nfl_club_sources.py"
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


def original_disposition(title, away, home):
    low = str(title or "").lower()
    if str(away).lower() not in low or str(home).lower() not in low:
        return "EVENT_MISMATCH"
    if "press conference" in low or "postgame reaction" in low:
        return "POSTGAME_REACTION"
    if "game highlights" in low or "full game highlights" in low:
        return "GAME_PACKAGE"
    if "highlights" in low:
        return "INDIVIDUAL_PLAY"
    return "NON_GAME_SCOPE"


def original_objective(item):
    duration = int((item or {}).get("durationSeconds") or 0)
    if 45 <= duration <= 390:
        return "quick"
    if 540 <= duration <= 1800:
        return "extended"
    return ""


def team_row(title, duration=0):
    return {
        "league": "NFL",
        "title": title,
        "durationSeconds": duration,
        "provider": "NFL-TEAM-SITE",
        "sourceType": "official-nfl-team-video",
        "discoverySourceFamily": "nfl-team-video",
        "officialTeamSource": True,
    }


def test_top_plays_is_promoted_after_both_team_match():
    got = MOD.expanded_team_title_disposition(
        "49ers vs Rams Top Plays | Week 1", "49ers", "Rams", original_disposition
    )
    assert got == "GAME_PACKAGE"


def test_cinematic_recap_is_promoted_after_both_team_match():
    got = MOD.expanded_team_title_disposition(
        "Seahawks vs Patriots Week 1 Cinematic Recap",
        "Patriots",
        "Seahawks",
        original_disposition,
    )
    assert got == "GAME_PACKAGE"


def test_extended_highlights_is_promoted_after_both_team_match():
    got = MOD.expanded_team_title_disposition(
        "Rams vs 49ers Extended Highlights", "49ers", "Rams", original_disposition
    )
    assert got == "GAME_PACKAGE"


def test_event_mismatch_is_never_overridden():
    got = MOD.expanded_team_title_disposition(
        "49ers Top Plays | Week 1", "49ers", "Rams", original_disposition
    )
    assert got == "EVENT_MISMATCH"


def test_reaction_content_is_never_promoted():
    got = MOD.expanded_team_title_disposition(
        "Rams vs 49ers Postgame Reaction Top Plays",
        "49ers",
        "Rams",
        original_disposition,
    )
    assert got == "POSTGAME_REACTION"


def test_duration_drives_quick_and_extended_when_known():
    assert MOD.team_media_objective(team_row("Patriots vs Seahawks Game Highlights", 240), original_objective) == "quick"
    assert MOD.team_media_objective(team_row("Patriots vs Seahawks Cinematic Recap", 900), original_objective) == "extended"


def test_missing_duration_uses_strong_package_labels():
    assert MOD.team_media_objective(team_row("Patriots vs Seahawks Game Highlights"), original_objective) == "quick"
    assert MOD.team_media_objective(team_row("49ers vs Rams Top Plays"), original_objective) == "quick"
    assert MOD.team_media_objective(team_row("Seahawks vs Patriots Cinematic Recap"), original_objective) == "extended"
    assert MOD.team_media_objective(team_row("Patriots vs Seahawks Full Game Highlights"), original_objective) == "extended"


def test_true_full_or_condensed_replay_remains_out_of_scope():
    assert MOD.team_media_objective(team_row("Patriots vs Seahawks Full Game Replay"), original_objective) == ""
    assert MOD.team_media_objective(team_row("Patriots vs Seahawks Condensed Game"), original_objective) == ""


def test_non_team_sources_keep_original_objective_policy():
    row = {"title": "Generic Game Highlights", "durationSeconds": 240, "provider": "OTHER"}
    assert MOD.team_media_objective(row, original_objective) == "quick"


def test_legacy_nfl_playlist_assets_are_retired_only_for_nfl():
    old = {
        "league": "NFL",
        "sourceType": "official-nfl-youtube-playlist",
        "discoverySourceFamily": "nfl-youtube-playlist",
    }
    assert MOD._retired_playlist_asset(old, "NFL") is True
    assert MOD._retired_playlist_asset(old, "NBA") is False
    assert MOD._retired_playlist_asset({"league": "NFL", "sourceType": "official-nfl-team-video"}, "NFL") is False


def test_provider_registry_marks_team_sources_primary_and_playlist_retired():
    spec = importlib.util.spec_from_file_location(
        "provider_registry_under_test", ROOT / "sbb" / "provider_registry.py"
    )
    registry = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(registry)

    assert registry.MEDIA_ADAPTERS["nfl-team-video-quick"]["reliability"] == 100
    assert registry.MEDIA_ADAPTERS["nfl-team-video-extended"]["reliability"] == 100
    assert registry.MEDIA_ADAPTERS["nfl-youtube-playlist-quick"]["reliability"] == 0
    assert registry.MEDIA_ADAPTERS["nfl-youtube-playlist-extended"]["reliability"] == 0
    assert registry.MEDIA_ADAPTERS["nfl-youtube-playlist"]["kind"] == "retired-official-youtube-playlist"

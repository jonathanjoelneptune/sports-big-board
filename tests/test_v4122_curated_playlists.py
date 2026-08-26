import unittest
from pathlib import Path
from unittest.mock import patch

import server


ROOT=Path(__file__).resolve().parents[1]
RELEASE_VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()


class V4122CuratedPlaylistTests(unittest.TestCase):
    def test_release_versions_and_curated_source_versions(self):
        self.assertEqual(server.APP_VERSION, RELEASE_VERSION)
        self.assertEqual(server.HISTORY_DISCOVERY_VERSION, 15)
        self.assertEqual(server.HISTORY_RULE_CATCHUP_VERSION, 10)
        nfl={x["key"]:x for x in server.HISTORY_OFFICIAL_CATCHUP_SOURCES["NFL"]}
        mls={x["key"]:x for x in server.HISTORY_OFFICIAL_CATCHUP_SOURCES["MLS"]}
        nhl={x["key"]:x for x in server.HISTORY_OFFICIAL_CATCHUP_SOURCES["NHL"]}
        mlb={x["key"]:x for x in server.HISTORY_OFFICIAL_CATCHUP_SOURCES["MLB"]}
        self.assertEqual(nfl["nfl-youtube-playlist-quick"]["version"], 2)
        self.assertEqual(nfl["nfl-youtube-playlist-extended"]["version"], 2)
        self.assertEqual(mls["mls-youtube-playlist-highlights"]["version"], 1)
        self.assertEqual(nhl["nhl-youtube-playlist-highlights"]["version"], 1)
        self.assertEqual(mlb["mlb-youtube-playlist-highlights"]["version"], 1)

    def test_operator_playlist_ids_are_pinned(self):
        nhl={x["playlistId"] for x in server.CURATED_GAME_PLAYLISTS["NHL"]}
        mls={x["playlistId"] for x in server.CURATED_GAME_PLAYLISTS["MLS"]}
        mlb={x["playlistId"] for x in server.CURATED_GAME_PLAYLISTS["MLB"]}
        self.assertIn("PL1NbHSfosBuFyu867mbHHhB2G6fx7jtiH", nhl)
        self.assertEqual(mls, {
            "PLaqZDrMi2AhY",
            "PLcj4z4KsbIoXrLpj2pOVr_maRaxhW902-",
            "PLcj4z4KsbIoVYKuevRiaE94KlwPuXqLHy",
        })
        self.assertEqual(mlb, {
            "PLL-lmlkrmJak3neKKEataBelAVfdkBbDX",
            "PLL-lmlkrmJanq-c41voXY4cCbxVR0bjxR",
        })
        self.assertIn("PLXEMPXZ3PY1hMzinDc1TvSm8U2NUyz-0E", server.EPL_YOUTUBE_KNOWN_PLAYLISTS)
        self.assertEqual(len(server.NFL_YOUTUBE_KNOWN_RECAP_PLAYLISTS), 21)
        for pid in (
            "PLRdw3IjKY2gm8m7heXMOfVPLVA8jDY_Jd",
            "PLRdw3IjKY2gnK2f32zf7qlXGtHZlTZiyQ",
            "PLRdw3IjKY2gn04EX1BXBk8TgY82oOIWVl",
            "PLRdw3IjKY2gkqZowlSUWT2wRn5lLiVa-_",
        ):
            self.assertIn(pid, server.NFL_YOUTUBE_KNOWN_RECAP_PLAYLISTS)

    def test_nhl_curated_playlist_can_become_extended_game_media(self):
        row={
            "youtubeId":"abcdefghijk",
            "eventId":"abcdefghijk",
            "title":"Hurricanes vs. Golden Knights | NHL Playoff Highlights | Game 6 | June 14, 2026",
            "description":"Carolina Hurricanes vs. Vegas Golden Knights Game 6 highlights",
            "durationSeconds":752,
            "duration":752,
            "publishedAt":"2026-06-14T23:00:00Z",
            "provider":"YOUTUBE",
            "verifiedPlayable":True,
            "validationState":"VERIFIED",
            "embedValidated":True,
            "recapTier":"extended",
            "mediaObjective":"EXTENDED",
            "source":"NHL YouTube Full Game Highlights",
            "sourceType":"official-nhl-youtube-full-game-highlights",
        }
        def assigned(item,event):
            out=dict(item)
            out["mediaScope"]=server.MEDIA_SCOPE_GAME
            out["scope"]=server.MEDIA_SCOPE_GAME
            return out,{"associationState":"ASSIGNED"}
        with patch.object(server,"_curated_playlist_items",return_value=[row]), patch.object(server,"_history_media_match_evidence",side_effect=assigned):
            got=server._curated_game_playlist_results(
                "NHL","2026-06-14","Vegas Golden Knights","Carolina Hurricanes",objective="extended"
            )
        self.assertEqual(len(got),1)
        self.assertEqual(got[0]["youtubeId"],"abcdefghijk")
        self.assertEqual(got[0]["recapTier"],"extended")
        self.assertEqual(got[0]["mediaObjective"],"EXTENDED")

    def test_media_source_registry_exposes_active_sources_and_links(self):
        reg=server._game_media_source_registry()
        self.assertEqual(reg["version"],2)
        rows=reg["rows"]
        self.assertTrue(rows)
        for league in ("MLB","NFL","NBA","NHL","EPL","MLS"):
            self.assertTrue(any(x["league"]==league for x in rows),league)
        nhl=next(x for x in rows if x["league"]=="NHL" and x["collector"]=="nhl-youtube-playlist-highlights")
        self.assertEqual(nhl["priority"],"PRIMARY")
        self.assertTrue(nhl["url"].startswith("https://www.youtube.com/playlist?list="))
        self.assertTrue(nhl["active"])
        self.assertTrue(all("priority" in x and "url" in x and "collector" in x for x in rows))

    def test_ui_has_collapsible_recovery_and_game_media_playlist_tab(self):
        root=Path(__file__).resolve().parents[1]
        index=(root/"index.html").read_text(encoding="utf-8")
        ui=(root/"ui"/"history-audit.js").read_text(encoding="utf-8")
        backend=(root/"server.py").read_text(encoding="utf-8")
        for token in ("historyAuditTabPlaylists","GAME MEDIA PLAYLISTS","historyRecoveryToggle","historyRecoveryPanel","history-playlists-only"):
            self.assertIn(token,index)
        self.assertIn("sbb-history-recovery-collapsed",ui)
        self.assertIn("loadMediaSources",ui)
        self.assertIn("renderMediaSources",ui)
        self.assertIn("/api/history/media-sources",backend)
        self.assertIn("/api/history/media-sources",ui)


if __name__ == "__main__":
    unittest.main()

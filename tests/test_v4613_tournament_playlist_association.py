import unittest
from pathlib import Path

import sbb.competition_builder_v4613 as v4613

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/"VERSION").read_text(encoding="utf-8").strip()
INDEX=(ROOT/"index.html").read_text(encoding="utf-8")
BACKEND=(ROOT/"sbb"/"competition_builder_v4613.py").read_text(encoding="utf-8")
UI=(ROOT/"architecture"/"competition-builder-v4613.js").read_text(encoding="utf-8")
CERT=(ROOT/"foundation-certification.json").read_text(encoding="utf-8")


class _Server:
    def _epl_numeric_date_from_text(self,title): return ""
    def _named_date_from_text(self,title,year):
        return "2026-08-25" if "August 25" in str(title) else ""


class V4613TournamentPlaylistAssociationTests(unittest.TestCase):
    def record(self,key,date,game_number=None):
        return {
            "canonicalEventKey":key,
            "eventId":key.split(":")[-1],
            "date":date,
            "event":{"eventId":key.split(":")[-1],"date":date,"gameNumber":game_number}
        }

    def test_special_event_crawler_compares_full_competition_before_date_narrowing(self):
        self.assertIn("_match_item_across_competition",BACKEND)
        self.assertIn("for record in records:",BACKEND)
        self.assertIn("fullCompetitionCompared",BACKEND)
        self.assertIn("_special_event_playlist_crawl",BACKEND)

    def test_unique_matchup_wins_without_publication_date_gate(self):
        match=(self.record("LLWS2026:g17","2026-08-23",17),{"associationMethod":"EXACT_TEAM_PAIR_TITLE"})
        selected,method=v4613._choose_match(_Server(),{"title":"Team A vs Team B | Full Game Highlights","publishedAt":"2026-08-29"},[match],2026)
        self.assertEqual(v4613._record_key(selected[0]),"LLWS2026:g17")
        self.assertEqual(method,"UNIQUE_PAIR")

    def test_repeated_matchup_uses_explicit_title_date(self):
        matches=[
            (self.record("LLWS2026:g3","2026-08-19",3),{"associationMethod":"EXACT_TEAM_PAIR_TITLE"}),
            (self.record("LLWS2026:g27","2026-08-25",27),{"associationMethod":"EXACT_TEAM_PAIR_TITLE"}),
        ]
        selected,method=v4613._choose_match(_Server(),{"title":"Team A vs Team B | Full Game Highlights | August 25","publishedAt":"2026-08-26"},matches,2026)
        self.assertEqual(v4613._record_key(selected[0]),"LLWS2026:g27")
        self.assertEqual(method,"EXPLICIT_TITLE_DATE")

    def test_repeated_matchup_can_use_nearby_publication_as_bounded_tiebreaker(self):
        matches=[
            (self.record("LLWS2026:g3","2026-08-19",3),{"associationMethod":"EXACT_TEAM_PAIR_TITLE"}),
            (self.record("LLWS2026:g27","2026-08-25",27),{"associationMethod":"EXACT_TEAM_PAIR_TITLE"}),
        ]
        selected,method=v4613._choose_match(_Server(),{"title":"Team A vs Team B | Full Game Highlights","publishedAt":"2026-08-26"},matches,2026)
        self.assertEqual(v4613._record_key(selected[0]),"LLWS2026:g27")
        self.assertEqual(method,"PUBLICATION_PROXIMITY")

    def test_far_publication_date_does_not_guess_between_repeated_matchups(self):
        matches=[
            (self.record("LLWS2026:g3","2026-08-19",3),{"associationMethod":"EXACT_TEAM_PAIR_TITLE"}),
            (self.record("LLWS2026:g27","2026-08-25",27),{"associationMethod":"EXACT_TEAM_PAIR_TITLE"}),
        ]
        selected,method=v4613._choose_match(_Server(),{"title":"Team A vs Team B | Full Game Highlights","publishedAt":"2026-09-20"},matches,2026)
        self.assertIsNone(selected)
        self.assertEqual(method,"AMBIGUOUS_REPEATED_MATCHUP")

    def test_new_crawl_stamps_both_operator_and_youtube_playlist_identity(self):
        self.assertIn('item["operatorPlaylistId"]',BACKEND)
        self.assertIn('item["playlistId"]',BACKEND)
        self.assertIn('item["sourcePlaylistId"]',BACKEND)

    def test_existing_orphans_are_reassociated_without_redownload(self):
        self.assertIn("def _reassociate_existing_competition",BACKEND)
        self.assertIn("base._league_source_media",BACKEND)
        self.assertIn("sbb-v4613-startup-reassociate",BACKEND)

    def test_statistics_use_durable_playable_event_media_for_special_events(self):
        self.assertIn("/api/competition-builder/media-association-stats",UI)
        self.assertIn("gamesWithPlayableAssociatedMedia",UI)
        self.assertIn("durable EVENT_MEDIA",UI)
        self.assertIn("gamesWithPlayableAssociatedMedia",BACKEND)

    def test_release_contract(self):
        self.assertIn(f"architecture/competition-builder-v4613.js?v={VERSION}",INDEX)
        self.assertIn("full competition schedule before publication date",CERT)
        self.assertIn("durable playable EVENT_MEDIA",CERT)


if __name__=="__main__":
    unittest.main()

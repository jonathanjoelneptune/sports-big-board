import tempfile
import unittest
from pathlib import Path

import sbb.special_event_media_v4616 as v4616
from sbb.history_repository import HistoryRepository

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/"VERSION").read_text(encoding="utf-8").strip()
INDEX=(ROOT/"index.html").read_text(encoding="utf-8")
BACKEND=(ROOT/"sbb"/"special_event_media_v4616.py").read_text(encoding="utf-8")
UI=(ROOT/"architecture"/"special-event-media-v4616.js").read_text(encoding="utf-8")
INIT=(ROOT/"sbb"/"__init__.py").read_text(encoding="utf-8")
CERT=(ROOT/"foundation-certification.json").read_text(encoding="utf-8")


class _Repo:
    def __init__(self,rows): self.rows=rows
    def catalog_events(self,**kwargs): return self.rows


class _Server:
    def __init__(self,rows): self.HISTORY_REPOSITORY=_Repo(rows)
    def _operator_media_playlists_load(self): return []
    def _named_date_from_text(self,title,year): return ""
    def _epl_numeric_date_from_text(self,title): return ""


def ll_team(name, group, abbr, *aliases):
    return {
        "name":name,"displayName":name,"group":group,"abbreviation":abbr,
        "aliases":[name,*aliases,group],
    }


class V4616SpecialEventMediaPipelineTests(unittest.TestCase):
    def competition(self):
        return {
            "id":"LLWS2026","name":"2026 Little League Baseball World Series",
            "type":"SPECIAL_EVENT","year":2026,"startDate":"2026-08-19","endDate":"2026-08-30",
            "events":[{
                "eventId":"g26","id":"g26","date":"2026-08-25","gameNumber":26,
                "awayTeam":ll_team("Soundview LL","Northwest Region","NW","Tacoma, Washington","Tacoma, WA"),
                "homeTeam":ll_team("Phenix City Youth Baseball LL","Southeast Region","SE","Phenix City, Alabama","Phenix City, AL"),
                "status":"FINAL",
            }]
        }

    def test_registry_identity_survives_flattened_history_refresh(self):
        comp=self.competition()
        history=[{
            "canonicalEventKey":"LLWS2026:g26","eventId":"g26","date":"2026-08-25",
            "event":{
                "eventId":"g26","date":"2026-08-25","status":"FINAL",
                "awayTeam":{"name":"Soundview LL"},
                "homeTeam":{"name":"Phenix City Youth Baseball LL"},
            }
        }]
        rows=v4616.competition_records(_Server(history),comp)
        self.assertEqual(len(rows),1)
        away=rows[0]["event"]["awayTeam"];home=rows[0]["event"]["homeTeam"]
        self.assertIn("Tacoma, Washington",away["aliases"])
        self.assertIn("Phenix City, Alabama",home["aliases"])
        self.assertEqual(rows[0]["event"]["gameNumber"],26)

    def test_crosswalk_derives_public_media_identities(self):
        comp=self.competition()
        rows=v4616.competition_records(_Server([]),comp)
        cross=v4616.participant_crosswalk(comp,rows)
        values=[x for row in cross.values() for x in row["aliases"]]
        self.assertIn("Washington",values)
        self.assertIn("Alabama",values)
        self.assertIn("WA",values)
        self.assertIn("AL",values)

    def test_real_llws_title_matches_imported_participant_identity(self):
        comp=self.competition()
        rows=v4616.competition_records(_Server([]),comp)
        item={"title":"Washington vs. Alabama | Full Game Highlights | Little League World Series"}
        matches=v4616._direct_alias_matches(item,rows)
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0][0]["eventId"],"g26")
        self.assertEqual(matches[0][1]["associationMethod"],"SPECIAL_EVENT_TITLE_ALIAS_PAIR")

    def test_official_game_number_is_stronger_than_text_aliases(self):
        comp=self.competition()
        rows=v4616.competition_records(_Server([]),comp)
        item={"title":"2026 Little League World Series Game 26 Full Highlights"}
        match=v4616._explicit_game_number_match(item,rows)
        self.assertIsNotNone(match)
        self.assertEqual(match["eventId"],"g26")

    def test_little_league_recap_index_parser_only_keeps_recap_pages(self):
        html="""
        <a href="/videos/recap-ohio-vs-alabama/"><span>Recap: Ohio vs Alabama</span></a>
        <a href="/videos/dykes-rbi-single/">Dykes' RBI single in the 3rd</a>
        <a href="https://www.littleleague.org/videos/recap-canada-vs-japan/">Recap: Canada vs. Japan</a>
        """
        rows=v4616._extract_recap_links(html,v4616.LLWS_GREEN_URL)
        self.assertEqual(len(rows),2)
        self.assertTrue(all("Recap:" in x["title"] for x in rows))
        self.assertTrue(all("/videos/" in x["url"] for x in rows))

    def test_little_league_direct_and_brightcove_parsers(self):
        self.assertEqual(
            v4616._extract_direct_media('<video src="https://cdn.example.com/a.mp4?x=1"></video>'),
            "https://cdn.example.com/a.mp4?x=1",
        )
        embed,vid=v4616._extract_brightcove(
            '<video-js data-account="12345" data-player="AbCd" data-video-id="67890"></video-js>'
        )
        self.assertEqual(vid,"67890")
        self.assertIn("players.brightcove.net/12345/AbCd_default/index.html?videoId=67890",embed)
        embed2,vid2=v4616._extract_brightcove(
            '<iframe src="https://players.brightcove.net/12345/AbCd_default/index.html?videoId=67890"></iframe>'
        )
        self.assertEqual((embed2,vid2),(embed,"67890"))

    def test_little_league_page_metadata_supports_repeated_matchup_tiebreaking(self):
        page="""
          <meta property="article:published_time" content="2026-08-25T21:30:00-04:00">
          <script type="application/ld+json">{"duration":"PT1M29S"}</script>
        """
        self.assertEqual(v4616._extract_published_at(page),"2026-08-25T21:30:00-04:00")
        self.assertEqual(v4616._extract_duration_seconds(page),89)


    def test_direct_persistence_creates_the_same_durable_relation_ribbon_reads(self):
        comp=self.competition();record=v4616.competition_records(_Server([]),comp)[0]
        item={
            "youtubeId":"llws-purple-game26",
            "title":"Washington vs. Alabama | Full Game Highlights | Little League World Series",
            "verifiedPlayable":True,"provider":"YOUTUBE","recapTier":"extended",
            "league":"LLWS2026","competitionId":"LLWS2026",
        }
        evidence=v4616._direct_alias_matches(item,[record])[0][1]
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite")
            server=_Server([]);server.HISTORY_REPOSITORY=repo
            added,persisted,decorated,reason=v4616.persist_match(
                server,comp,item,record,evidence,"UNIQUE_PAIR",None
            )
            self.assertTrue(persisted,reason)
            self.assertEqual(added,1)
            media=repo.event_media("2026-08-25","LLWS2026","g26",include_failed=False)
            self.assertEqual(len(media),1)
            self.assertEqual(media[0]["recapTier"],"extended")
            self.assertEqual(media[0]["mediaScope"],"GAME")
            self.assertEqual(media[0]["youtubeId"],"llws-purple-game26")
            stats=v4616.durable_stats(server,comp)
            self.assertEqual(stats["gamesWithPlayableAssociatedMedia"],1)
            self.assertEqual(stats["associatedAssets"],1)
            self.assertEqual(stats["orphanedAssets"],0)

    def test_llws_source_migration_returns_full_identity_definition(self):
        self.assertIn('return base._find("LLWS2026") or comp',BACKEND)
        self.assertIn('save_competition returns a catalog row with events intentionally omitted',BACKEND)

    def test_source_contract_separates_reassociate_and_recrawl(self):
        self.assertIn("/api/competition-builder/reassociate-media",BACKEND)
        self.assertIn("/api/competition-builder/recrawl-media",BACKEND)
        self.assertIn("REASSOCIATE",UI)
        self.assertIn("RECRAWL SOURCES",UI)
        self.assertIn("ASSOCIATION AUDIT",UI)
        self.assertIn("SOURCE -> ELIGIBLE -> CANDIDATES -> MATCHED -> PERSISTED -> PLAYABLE",BACKEND)

    def test_statistics_and_ribbon_share_durable_event_media_truth(self):
        self.assertIn("gamesWithPlayableAssociatedMedia",BACKEND)
        self.assertIn("SPECIAL_EVENT_CANONICAL_ASSOCIATION",BACKEND)
        self.assertIn("history_event_media",BACKEND)

    def test_llws_sources_are_migrated_to_green_and_purple(self):
        self.assertIn("LLWS_GREEN_URL",BACKEND)
        self.assertIn("LLWS_PURPLE_URL",BACKEND)
        self.assertIn('"requiredTitlePhrases":["Recap:"]',BACKEND)
        self.assertIn('"requiredTitlePhrases":["Full Game Highlights"]',BACKEND)

    def test_release_contract(self):
        self.assertIn(f"architecture/special-event-media-v4616.js?v={VERSION}",INDEX)
        self.assertIn("special_event_media_v4616",INIT)
        self.assertIn("_install_special_event_media_v4616()",INIT)
        self.assertIn("custom-competition registry events are the identity authority",CERT)
        self.assertIn("Association Audit",CERT)


if __name__=="__main__":
    unittest.main()

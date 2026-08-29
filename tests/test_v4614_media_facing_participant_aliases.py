import unittest
from pathlib import Path

import sbb.competition_builder_v4614 as v4614

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/"VERSION").read_text(encoding="utf-8").strip()
INDEX=(ROOT/"index.html").read_text(encoding="utf-8")
BACKEND=(ROOT/"sbb"/"competition_builder_v4614.py").read_text(encoding="utf-8")
INIT=(ROOT/"sbb"/"__init__.py").read_text(encoding="utf-8")
CERT=(ROOT/"foundation-certification.json").read_text(encoding="utf-8")


def team(name,group,abbr,*aliases):
    return {
        "name":name,"displayName":name,"group":group,"abbreviation":abbr,
        "aliases":[name,*aliases,group]
    }


TEAMS={
    "NIC":team("Ministerio Sobre Las Alas Del Aguila LL","Latin America Region","LA","Leon, Nicaragua"),
    "DR":team("Los Nacionales LL","Caribbean Region","CB","Santiago, Dominican Republic"),
    "WA":team("Soundview LL","Northwest Region","NW","Tacoma, Washington","Tacoma, WA"),
    "AL":team("Phenix City Youth Baseball LL","Southeast Region","SE","Phenix City, Alabama","Phenix City, AL"),
    "CAN":team("Little Mountain LL","Canada Region","CAN","Vancouver, British Columbia","Vancouver, BC"),
    "KOR":team("West Seoul (B) LL","Asia-Pacific Region","AP","Seoul, South Korea","South Korea"),
    "MA":team("Bridgewater Joe Lazaro LL","New England Region","NE","Bridgewater, Massachusetts","Bridgewater, MA"),
    "NJ":team("Bayonne Central LL","Metro Region","MTR","Bayonne, New Jersey","Bayonne, NJ"),
    "AUS":team("Ryde Little League","Australia Region","AUS","Sydney, New South Wales","Sydney, NSW"),
    "MEX":team("Municipal De Tijuana LL","Mexico Region","MEX","Tijuana, Mexico"),
    "OH":team("West Side LL","Great Lakes Region","GL","Hamilton, Ohio","Hamilton, OH"),
    "NV":team("Paseo Verde LL","Mountain Region","MTN","Henderson, Nevada","Henderson, NV"),
    "JPN":team("Joto LL","Japan Region","JPN","Tokyo, Japan"),
    "CUW":team("Pariba LL","Curaçao Region","CUW","Willemstad, Curaçao","Willemstad, Curacao"),
    "CA":team("Sweetwater Valley LL","West Region","W","Bonita, California","Bonita, CA"),
    "IA":team("Davenport Northwest LL","Midwest Region","MW","Davenport, Iowa","Davenport, IA"),
    "PAN":team("David Doleguita LL","Panama Region","PAN","Chiriqui, Panama"),
    "TX":team("Boerne LL","Southwest Region","SW","Boerne, Texas","Boerne, TX"),
    "CZE":team("South Czech Republic LL","Europe-Africa Region","EA","Brno, Czechia"),
    "PA":team("East Side LL","Mid-Atlantic Region","MA","West Chester, Pennsylvania","West Chester, PA"),
}


class V4614MediaFacingParticipantAliasTests(unittest.TestCase):
    def evidence(self,title,a,b):
        event={"awayTeam":TEAMS[a],"homeTeam":TEAMS[b]}
        return v4614._direct_title_pair_evidence({"title":title},event)

    def test_imported_city_state_alias_derives_media_facing_state(self):
        aliases=v4614._participant_aliases_v4614(TEAMS["AL"])
        self.assertIn("Alabama",aliases)
        self.assertIn("AL",aliases)

    def test_imported_city_country_alias_derives_country(self):
        aliases=v4614._participant_aliases_v4614(TEAMS["NIC"])
        self.assertIn("Nicaragua",aliases)
        self.assertIn("Latin America",aliases)

    def test_group_region_derives_public_country_or_region_label(self):
        self.assertIn("Canada",v4614._participant_aliases_v4614(TEAMS["CAN"]))
        self.assertIn("Japan",v4614._participant_aliases_v4614(TEAMS["JPN"]))

    def test_common_media_equivalents_support_dr_and_czechia(self):
        self.assertIn("DR",v4614._participant_aliases_v4614(TEAMS["DR"]))
        self.assertIn("Czech Republic",v4614._participant_aliases_v4614(TEAMS["CZE"]))

    def test_actual_2026_llws_title_forms_match_schedule_participants(self):
        cases=[
            ("THRILLING FINISH Panama vs. Nicaragua | Full Game Highlights | Little League World Series","PAN","NIC"),
            ("OH-IO DOMINATION Ohio vs. Alabama | Full Game Highlights | Little League World Series","OH","AL"),
            ("Canada vs. South Korea | Full Game Highlights | Little League World Series","CAN","KOR"),
            ("Pennsylvania vs. Alabama | Full Game Highlights | Little League World Series","PA","AL"),
            ("Czechia vs. Japan | Full Game Highlights | Little League World Series","CZE","JPN"),
            ("Japan vs DR | Full Game Highlights | Little League World Series","JPN","DR"),
            ("PA vs. NJ | Full Game Highlights | Little League World Series","PA","NJ"),
            ("California vs Iowa | Full Game Highlights | Little League World Series","CA","IA"),
            ("Washington vs. Texas | Full Game Highlights | Little League World Series","WA","TX"),
            ("Curacao vs. South Korea | Full Game Highlights | Little League World Series","CUW","KOR"),
        ]
        for title,a,b in cases:
            with self.subTest(title=title):
                evidence=self.evidence(title,a,b)
                self.assertIsNotNone(evidence)
                self.assertEqual(evidence["associationState"],"ASSIGNED")
                self.assertTrue(evidence["associationMethod"].startswith("SPECIAL_EVENT_TITLE_ALIAS_PAIR"))

    def test_little_league_green_recap_title_forms_use_same_alias_vocabulary(self):
        cases=[
            ("Recap: Ohio vs Alabama","OH","AL"),
            ("Recap: Canada vs. Japan","CAN","JPN"),
            ("Recap: Nevada vs Iowa","NV","IA"),
            ("Recap: Nicaragua vs Japan","NIC","JPN"),
            ("Recap: Massachusetts vs. New Jersey","MA","NJ"),
        ]
        for title,a,b in cases:
            with self.subTest(title=title):
                self.assertIsNotNone(self.evidence(title,a,b))

    def test_one_character_region_abbreviation_is_not_used_as_media_alias(self):
        aliases=v4614._participant_aliases_v4614(TEAMS["CA"])
        self.assertNotIn("W",aliases)
        self.assertIn("California",aliases)

    def test_release_installs_after_v4613_and_reassociates_existing_orphans(self):
        self.assertIn("competition_builder_v4614",INIT)
        self.assertIn("_install_competition_builder_v4614()",INIT)
        self.assertIn("tournament._match_item_across_competition = _match_item_across_competition_v4614",BACKEND)
        self.assertIn("sbb-v4614-media-alias-reassociate",BACKEND)

    def test_release_contract(self):
        self.assertIn(f"Sports Big Board — v{VERSION}",INDEX)
        self.assertIn("media-facing geographic identities",CERT)
        self.assertIn("SPECIAL_EVENT_TITLE_ALIAS_PAIR",CERT)


if __name__=="__main__":
    unittest.main()

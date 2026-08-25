import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone
import server

class LiveFreshnessTests(unittest.TestCase):
    def test_client_timezone_drives_today(self):
        class FixedDateTime(datetime):
            @classmethod
            def now(cls,tz=None):
                base=datetime(2026,8,21,0,58,0,tzinfo=timezone.utc)
                return base if tz is None else base.astimezone(tz)
        # Termux may not ship Python's optional IANA tzdata. The browser-provided
        # UTC offset must therefore be sufficient to preserve the sports day.
        with patch.object(server,'datetime',FixedDateTime), patch.object(server,'ZoneInfo',side_effect=Exception('tzdata unavailable')):
            self.assertEqual(server._client_date_iso(0,"America/New_York",-240),"2026-08-20")
            self.assertEqual(server._client_date_iso(0,"Etc/UTC",0),"2026-08-21")


    def test_remembered_browser_offset_survives_missing_tzdata(self):
        class FixedDateTime(datetime):
            @classmethod
            def now(cls,tz=None):
                base=datetime(2026,8,21,0,58,0,tzinfo=timezone.utc)
                return base if tz is None else base.astimezone(tz)
        old_offset=server.MEDIA_PREWARM_STATE.get("utcOffsetMinutes")
        try:
            server.MEDIA_PREWARM_STATE["utcOffsetMinutes"]=-240
            with patch.object(server,'datetime',FixedDateTime), patch.object(server,'ZoneInfo',side_effect=Exception('tzdata unavailable')):
                self.assertEqual(server._client_date_iso(0,"America/New_York"),"2026-08-20")
        finally:
            server.MEDIA_PREWARM_STATE["utcOffsetMinutes"]=old_offset

    def test_post_kickoff_scheduled_game_uses_transition_window(self):
        class FixedDateTime(datetime):
            @classmethod
            def now(cls,tz=None):
                base=datetime(2026,8,21,0,28,0,tzinfo=timezone.utc)
                return base if tz is None else base.astimezone(tz)
            @classmethod
            def fromisoformat(cls,value):
                return datetime.fromisoformat(value)
            @classmethod
            def fromtimestamp(cls,value,tz=None):
                return datetime.fromtimestamp(value,tz=tz)
        payload={"data":[{"date":"2026-08-21T00:00:00Z","status":"8:00 PM","state":{"status":"scheduled"}}]}
        with patch.object(server,'datetime',FixedDateTime):
            self.assertTrue(server._payload_has_transition_game(payload,"America/New_York"))

    def test_espn_authority_overlays_stale_scheduled_state(self):
        highlightly={"data":[{
            "date":"2026-08-20T20:00:00-04:00",
            "awayTeam":{"abbreviation":"DAL","name":"Dallas Cowboys"},
            "homeTeam":{"abbreviation":"NYG","name":"New York Giants"},
            "state":{"description":"Scheduled","status":"scheduled"},
            "status":"8:00 PM"
        }]}
        espn=[{
            "date":"2026-08-21T00:00:00Z",
            "awayTeam":{"abbreviation":"DAL","name":"Dallas Cowboys"},
            "homeTeam":{"abbreviation":"NYG","name":"New York Giants"},
            "state":{"description":"Q1 12:34","status":"in","report":"LIVE"},
            "status":"Q1 12:34","clock":"12:34","period":1,"completed":False,
            "score":{"awayScore":"3","homeScore":"0"}
        }]
        with patch.object(server,'_client_date_iso',return_value='2026-08-20'), patch.object(server,'_espn_live_authority',return_value=espn):
            out=server._reconcile_scoreboard_authority(highlightly,'nfl','2026-08-20','America/New_York')
        row=out['data'][0]
        self.assertEqual(row['status'],'Q1 12:34')
        self.assertEqual(row['clock'],'12:34')
        self.assertEqual(row['__sbbScoreAuthority'],'ESPN')
        self.assertEqual(row['state']['report'],'LIVE')

    def test_espn_cdn_fallback_supplies_live_nfl_state(self):
        live_event={
            "id":"401999001","date":"2026-08-21T00:00:00Z","name":"Las Vegas Raiders at Houston Texans","shortName":"LV @ HOU",
            "competitions":[{"competitors":[
                {"homeAway":"away","score":"3","team":{"id":"13","displayName":"Las Vegas Raiders","abbreviation":"LV"}},
                {"homeAway":"home","score":"17","team":{"id":"34","displayName":"Houston Texans","abbreviation":"HOU"}}
            ]}],
            "status":{"displayClock":"0:00","period":2,"type":{"state":"in","shortDetail":"Halftime","completed":False}}
        }
        cdn={"content":{"sbData":{"events":[live_event]}}}
        def fake_fetch(url,timeout=8):
            if 'cdn.espn.com/core/nfl/scoreboard' in url: return cdn
            raise RuntimeError('site endpoint blocked')
        with patch.object(server,'_read_scoreboard_cache',return_value=(None,None)), patch.object(server,'_write_scoreboard_cache'), patch.object(server,'_espn_fetch_json',side_effect=fake_fetch), patch.object(server,'ZoneInfo',side_effect=Exception('tzdata unavailable')):
            rows=server._espn_scoreboard('NFL','2026-08-20','America/New_York',-240)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['score']['homeScore'],'17')
        self.assertEqual(rows[0]['state']['report'],'LIVE')
        self.assertEqual(rows[0]['period'],2)

    def test_nfl_scoreboard_queries_utc_window_for_evening_viewer_day(self):
        event={
            "id":"401873285","date":"2026-08-21T02:00:00Z","name":"San Francisco 49ers at Los Angeles Chargers","shortName":"SF @ LAC",
            "competitions":[{"competitors":[
                {"homeAway":"away","score":"41","team":{"displayName":"San Francisco 49ers","abbreviation":"SF"}},
                {"homeAway":"home","score":"17","team":{"displayName":"Los Angeles Chargers","abbreviation":"LAC"}}
            ]}],
            "status":{"displayClock":"0:00","period":4,"type":{"state":"post","shortDetail":"Final","completed":True}}
        }
        calls=[]
        def fake_fetch(url,timeout=8):
            calls.append(url)
            return {"events":[event]}
        with patch.object(server,'_read_scoreboard_cache',return_value=(None,None)), patch.object(server,'_write_scoreboard_cache'), patch.object(server,'_espn_fetch_json',side_effect=fake_fetch), patch.object(server,'ZoneInfo',side_effect=Exception('tzdata unavailable')):
            rows=server._espn_scoreboard('NFL','2026-08-20','America/Los_Angeles',-420)
        self.assertEqual([x['id'] for x in rows],['401873285'])
        self.assertTrue(any('dates=20260819-20260821' in url for url in calls))

    def test_espn_historical_lookup_skips_wrong_day_envelope(self):
        wrong={
            "id":"wrong-day","date":"2026-08-22T00:00:00Z","name":"Wrong Day","shortName":"WRG @ DAY",
            "competitions":[{"competitors":[
                {"homeAway":"away","score":"0","team":{"displayName":"Wrong","abbreviation":"WRG"}},
                {"homeAway":"home","score":"0","team":{"displayName":"Day","abbreviation":"DAY"}}
            ]}],
            "status":{"displayClock":"0:00","period":0,"type":{"state":"pre","shortDetail":"Scheduled","completed":False}}
        }
        wanted={
            # Midnight UTC Aug 21 is still Aug 20 for an Eastern viewer.
            "id":"wanted-day","date":"2026-08-21T00:00:00Z","name":"Dallas Cowboys at New York Giants","shortName":"DAL @ NYG",
            "competitions":[{"competitors":[
                {"homeAway":"away","score":"21","team":{"displayName":"Dallas Cowboys","abbreviation":"DAL"}},
                {"homeAway":"home","score":"17","team":{"displayName":"New York Giants","abbreviation":"NYG"}}
            ]}],
            "status":{"displayClock":"0:00","period":4,"type":{"state":"post","shortDetail":"Final","completed":True}}
        }
        calls=[]
        def fake_fetch(url,timeout=8):
            calls.append(url)
            return {"events":[wrong]} if len(calls)==1 else {"events":[wanted]}
        with patch.object(server,'_read_scoreboard_cache',return_value=(None,None)), patch.object(server,'_write_scoreboard_cache'), patch.object(server,'_espn_fetch_json',side_effect=fake_fetch), patch.object(server,'ZoneInfo',side_effect=Exception('tzdata unavailable')):
            rows=server._espn_scoreboard('NFL','2026-08-20','America/New_York',-240)
        self.assertGreaterEqual(len(calls),2)
        self.assertEqual([x['id'] for x in rows],['wanted-day'])

    def test_espn_soccer_utc_timestamp_uses_viewer_calendar_day(self):
        # 02:30 UTC Aug 20 is 10:30 PM Aug 19 for an Eastern viewer. It must be
        # YESTERDAY on Aug 20, not TODAY merely because ESPN's UTC date is Aug 20.
        event={
            "id":"761738","date":"2026-08-20T02:30:00Z","name":"San Jose Earthquakes at LA Galaxy","shortName":"SJ @ LA",
            "competitions":[{"competitors":[
                {"homeAway":"away","score":"0","team":{"displayName":"San Jose Earthquakes","abbreviation":"SJ"}},
                {"homeAway":"home","score":"1","team":{"displayName":"LA Galaxy","abbreviation":"LA"}}
            ]}],
            "status":{"displayClock":"90:00","period":2,"type":{"state":"post","shortDetail":"Final","completed":True}}
        }
        payload={"events":[event]}
        with patch.object(server,'_read_scoreboard_cache',return_value=(None,None)), patch.object(server,'_write_scoreboard_cache'), patch.object(server,'_espn_fetch_json',return_value=payload), patch.object(server,'ZoneInfo',side_effect=Exception('tzdata unavailable')):
            aug19=server._espn_scoreboard('MLS','2026-08-19','America/New_York',-240)
            aug20=server._espn_scoreboard('MLS','2026-08-20','America/New_York',-240)
        self.assertEqual([x['id'] for x in aug19],['761738'])
        self.assertEqual(aug20,[])

    def test_nfl_official_preseason_week_title_is_accepted_as_recap(self):
        search_row={
            "id":{"videoId":"DHlHW9N7lbg"},
            "snippet":{"title":"San Francisco 49ers vs. Los Angeles Chargers | 2026 Preseason Week 2","description":"San Francisco 49ers vs. Los Angeles Chargers - Highlights | 2026 Preseason Week 2","channelTitle":"NFL","publishedAt":"2026-08-21T05:00:00Z"}
        }
        detail={
            "id":"DHlHW9N7lbg",
            "snippet":search_row["snippet"],
            "contentDetails":{"duration":"PT12M30S"},
            "status":{"embeddable":True},
            "statistics":{"viewCount":"100000"}
        }
        def fake_youtube(url,timeout=10):
            if '/search?' in url: return {"items":[search_row]}
            if '/videos?' in url: return {"items":[detail]}
            raise AssertionError(url)
        with tempfile.TemporaryDirectory() as td, \
             patch.object(server,'_date_iso',return_value='2026-08-20'), \
             patch.object(server,'read_youtube_key',return_value='fake-key'), \
             patch.object(server,'_official_nfl_feed_videos',return_value=[]), \
             patch.object(server,'_nfl_game_highlights_results',return_value=[]), \
             patch.object(server,'youtube_fetch_json',side_effect=fake_youtube), \
             patch.object(server,'_espn_search_video_results',return_value=[]), \
             patch.object(server,'_generic_rapid_cache_path',return_value=Path(td)/'nfl.json'):
            rows=server.generic_rapid_team_videos('NFL','2026-08-20','San Francisco 49ers','Los Angeles Chargers',force_refresh=True)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['youtubeId'],'DHlHW9N7lbg')
        self.assertTrue(rows[0]['overview'])
        self.assertEqual(rows[0]['programType'],'recap')
        self.assertTrue(rows[0]['verifiedPlayable'])
        self.assertEqual(rows[0]['durationSeconds'],750)


    def test_nfl_dot_com_game_highlights_adapter_accepts_only_matchup_recap(self):
        channel="""<html><body>
        <a href='/videos/jets-vs-steelers-highlights-preseason-week-2'>Jets vs. Steelers highlights | Preseason Week 2</a>
        <a href='/videos/some-player-best-plays-vs-steelers-preseason-week-2'>Some Player's best plays vs. Steelers | Preseason Week 2</a>
        </body></html>"""
        detail="""<html><head>
        <meta property='og:title' content='Jets vs. Steelers highlights | Preseason Week 2'>
        <meta property='og:description' content='Watch the New York Jets vs. Pittsburgh Steelers highlights from Preseason Week 2 of the 2026 season.'>
        <script type='application/ld+json'>{"@type":"VideoObject","name":"Jets vs. Steelers highlights | Preseason Week 2","description":"Watch the New York Jets vs. Pittsburgh Steelers highlights from Preseason Week 2 of the 2026 season.","duration":"PT5M12S","datePublished":"2026-08-21T23:00:00Z","contentUrl":"https://cdn.nfl.test/jets-steelers.mp4","thumbnailUrl":"https://img.nfl.test/jets.jpg"}</script>
        </head></html>"""
        pages={server.NFL_GAME_HIGHLIGHTS_CHANNEL_URL:channel}
        pages.update({u:'' for u in server._nfl_game_highlights_source_pages('New York Jets','Pittsburgh Steelers')[1:]})
        pages['https://www.nfl.com/videos/jets-vs-steelers-highlights-preseason-week-2']=detail
        def fake_page(url,timeout=9): return pages.get(url,'')
        with patch.object(server,'_nfl_fetch_page_text',side_effect=fake_page), patch.object(server,'HISTORY_SHARED_CATALOG_CACHE',{}):
            rows=server._nfl_game_highlights_results('2026-08-21','New York Jets','Pittsburgh Steelers',validate_native=False)
        self.assertEqual(len(rows),1)
        row=rows[0]
        self.assertEqual(row['provider'],'NFL.COM')
        self.assertEqual(row['sourceType'],'official-nfl-game-highlights')
        self.assertEqual(row['sourceAuthority'],'LEAGUE_OFFICIAL')
        self.assertEqual(row['durationSeconds'],312)
        self.assertEqual(row['recapTier'],'green')
        self.assertEqual(row['mediaUrl'],'https://cdn.nfl.test/jets-steelers.mp4')
        self.assertEqual(row['externalUrl'],'https://www.nfl.com/videos/jets-vs-steelers-highlights-preseason-week-2')

    def test_nfl_dot_com_game_highlights_parser_rejects_individual_best_plays(self):
        self.assertTrue(server._nfl_game_highlight_is_match(
            'https://www.nfl.com/videos/jets-vs-steelers-highlights-preseason-week-2',
            'Jets vs. Steelers highlights | Preseason Week 2','',
            'New York Jets','Pittsburgh Steelers'))
        self.assertFalse(server._nfl_game_highlight_is_match(
            'https://www.nfl.com/videos/joe-milton-best-plays-vs-cardinals-preseason-week-2',
            "Joe Milton III's best plays from 3-TD game vs. Cardinals | Preseason Week 2",'',
            'Dallas Cowboys','Arizona Cardinals'))
        self.assertFalse(server._nfl_game_highlight_is_match(
            'https://www.nfl.com/videos/can-t-miss-play-some-touchdown-vs-steelers',
            "Can't-Miss Play: touchdown vs. Steelers",'New York Jets play Pittsburgh Steelers',
            'New York Jets','Pittsburgh Steelers'))

    def test_nfl_dot_com_video_metadata_extracts_jsonld_direct_media(self):
        raw="""<html><head><script type='application/ld+json'>
        {"@type":"VideoObject","name":"Chiefs vs. Buccaneers highlights | Preseason Week 2","duration":"PT4M58S","contentUrl":"https:\\/\\/cdn.nfl.test\\/chiefs-bucs.m3u8","datePublished":"2026-08-22T01:00:00Z"}
        </script></head></html>"""
        meta=server._nfl_video_page_metadata(raw,'https://www.nfl.com/videos/chiefs-vs-buccaneers-highlights-preseason-week-2')
        self.assertEqual(meta['durationSeconds'],298)
        self.assertEqual(meta['mediaUrl'],'https://cdn.nfl.test/chiefs-bucs.m3u8')
        self.assertEqual(meta['publishedAt'],'2026-08-22T01:00:00Z')


    def test_v418_nhl_official_five_minute_recap_adapter(self):
        index="""<html><body><a href='/video/mtl-at-car-recap-123'>4:58 MTL at CAR | Recap May 30, 2026</a></body></html>"""
        detail="""<html><head><script type='application/ld+json'>{"@type":"VideoObject","name":"MTL at CAR | Recap","duration":"PT4M58S","datePublished":"2026-05-30T23:00:00Z","contentUrl":"https://cdn.nhl.test/mtl-car.mp4"}</script></head></html>"""
        def fake_page(url,timeout=10,referer=''):
            if url==server.NHL_GAME_RECAPS_URL: return index
            if url==server.NHL_CONDENSED_GAMES_URL: return ''
            if url=='https://www.nhl.com/video/mtl-at-car-recap-123': return detail
            return ''
        with patch.object(server,'_official_fetch_page_text',side_effect=fake_page), patch.object(server,'HISTORY_SHARED_CATALOG_CACHE',{}):
            rows=server._nhl_official_video_results('2026-05-30','Montreal Canadiens','Carolina Hurricanes',validate_native=False)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['sourceType'],'official-nhl-game-recap')
        self.assertEqual(rows[0]['provider'],'NHL.COM')
        self.assertEqual(rows[0]['durationSeconds'],298)
        self.assertEqual(rows[0]['recapTier'],'green')
        self.assertEqual(rows[0]['mediaUrl'],'https://cdn.nhl.test/mtl-car.mp4')

    def test_v418_mls_official_match_highlights_adapter(self):
        index="""<html><body><a href='/video/highlights-new-england-revolution-vs-new-york-city-fc-august-23-2026'>10:31 HIGHLIGHTS: New England Revolution vs. New York City FC | August 23, 2026</a></body></html>"""
        detail="""<html><head><script type='application/ld+json'>{"@type":"VideoObject","name":"HIGHLIGHTS: New England Revolution vs. New York City FC | August 23, 2026","duration":"PT10M31S","datePublished":"2026-08-23T23:00:00Z","contentUrl":"https://cdn.mls.test/ner-nyc.mp4"}</script></head></html>"""
        def fake_page(url,timeout=10,referer=''):
            if url==server.MLS_MATCH_HIGHLIGHTS_URL: return index
            if 'highlights-new-england' in url: return detail
            return ''
        with patch.object(server,'_official_fetch_page_text',side_effect=fake_page), patch.object(server,'HISTORY_SHARED_CATALOG_CACHE',{}):
            rows=server._mls_official_web_results('2026-08-23','New York City FC','New England Revolution',validate_native=False)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['sourceType'],'official-mls-match-highlights')
        self.assertEqual(rows[0]['provider'],'MLSSOCCER.COM')
        self.assertEqual(rows[0]['durationSeconds'],631)
        self.assertEqual(rows[0]['recapTier'],'extended')

    def test_v4110_mls_match_snapshot_is_green_while_match_highlights_are_purple(self):
        index="""<html><body>
        <a href='/video/match-snapshot-new-england-revolution-vs-new-york-city-fc-august-23-2026'>0:59 MATCH SNAPSHOT: New England Revolution vs. New York City FC | August 23, 2026</a>
        <a href='/video/highlights-new-england-revolution-vs-new-york-city-fc-august-23-2026'>10:31 HIGHLIGHTS: New England Revolution vs. New York City FC | August 23, 2026</a>
        </body></html>"""
        snapshot="""<script type='application/ld+json'>{"@type":"VideoObject","name":"MATCH SNAPSHOT: New England Revolution vs. New York City FC | August 23, 2026","duration":"PT59S","datePublished":"2026-08-23T22:00:00Z","contentUrl":"https://cdn.mls.test/snapshot.mp4"}</script>"""
        highlights="""<script type='application/ld+json'>{"@type":"VideoObject","name":"HIGHLIGHTS: New England Revolution vs. New York City FC | August 23, 2026","duration":"PT10M31S","datePublished":"2026-08-23T23:00:00Z","contentUrl":"https://cdn.mls.test/highlights.mp4"}</script>"""
        def fake_page(url,timeout=10,referer=''):
            if url==server.MLS_MATCH_HIGHLIGHTS_URL: return index
            if 'match-snapshot-' in url: return snapshot
            if 'highlights-' in url: return highlights
            return ''
        with patch.object(server,'_official_fetch_page_text',side_effect=fake_page), patch.object(server,'HISTORY_SHARED_CATALOG_CACHE',{}):
            rows=server._mls_official_web_results('2026-08-23','New York City FC','New England Revolution',validate_native=False)
        by_type={x['sourceType']:x for x in rows}
        self.assertEqual(by_type['official-mls-match-snapshot']['recapTier'],'green')
        self.assertEqual(by_type['official-mls-match-snapshot']['mediaObjective'],'QUICK')
        self.assertEqual(by_type['official-mls-match-highlights']['recapTier'],'extended')
        self.assertEqual(by_type['official-mls-match-highlights']['mediaObjective'],'EXTENDED')

    def test_v4110_epl_official_match_highlight_hardening_rejects_roundups_and_reaction(self):
        away='Manchester United'; home='Newcastle United'
        self.assertTrue(server._epl_official_match_highlight_title('Manchester United v Newcastle United | Match Highlights',away,home))
        self.assertFalse(server._epl_official_match_highlight_title('BEST GOALS: Manchester United and Newcastle United | Matchweek 20',away,home))
        self.assertFalse(server._epl_official_match_highlight_title('Instant Reaction: Manchester United v Newcastle United Highlights',away,home))

    def test_v4111_epl_collectors_stamp_independent_quick_and_extended_objectives(self):
        pl_index="""<a href='https://www.premierleague.com/en/video/pl-highlights'><span>Arsenal v Liverpool | Match Highlights</span></a>"""
        pl_detail="""<script type='application/ld+json'>{"@type":"VideoObject","name":"Arsenal v Liverpool | Match Highlights","duration":"PT4M00S","datePublished":"2026-08-20T20:00:00Z","contentUrl":"https://cdn.pl.test/highlights.mp4"}</script>"""
        nbc_index="""<a href='https://www.nbcsports.com/watch/video/premier-league/arsenal-liverpool-extended-highlights'><span>Arsenal v Liverpool extended highlights</span></a>"""
        nbc_detail="""<script type='application/ld+json'>{"@type":"VideoObject","name":"Arsenal v Liverpool extended highlights","duration":"PT12M00S","datePublished":"2026-08-20T21:00:00Z","contentUrl":"https://cdn.nbc.test/extended.mp4"}</script>"""
        def fake_page(url,timeout=10,referer=''):
            if url==server.PREMIER_LEAGUE_VIDEO_URL: return pl_index
            if url==server.NBC_EPL_VIDEO_URL: return nbc_index
            if 'pl-highlights' in url: return pl_detail
            if 'extended-highlights' in url: return nbc_detail
            return ''
        with patch.object(server,'_official_fetch_page_text',side_effect=fake_page), patch.object(server,'HISTORY_SHARED_CATALOG_CACHE',{}):
            quick=server._premierleague_official_results('2026-08-20','Arsenal','Liverpool')
            extended=server._nbc_epl_extended_results('2026-08-20','Arsenal','Liverpool')
        self.assertEqual(quick[0]['mediaObjective'],'QUICK'); self.assertEqual(quick[0]['recapTier'],'green')
        self.assertEqual(extended[0]['mediaObjective'],'EXTENDED'); self.assertEqual(extended[0]['recapTier'],'extended')

    def test_v4110_nfl_extended_collector_requires_8_to_20_minutes(self):
        quick={"youtubeId":"quick","title":"Raiders vs Texans Game Highlights","durationSeconds":180,"overview":True,"verifiedPlayable":True}
        long={"youtubeId":"long","title":"Raiders vs Texans Game Highlights","durationSeconds":900,"overview":True,"verifiedPlayable":True}
        # v4.1.24 adds official team-site packages as a second Extended lane.
        # Keep this legacy duration-window unit test deterministic by isolating
        # the public NFL/YouTube lane it was originally written to exercise.
        with patch.object(server,'_nfl_game_highlights_results',return_value=[]), \
             patch.object(server,'_official_nfl_feed_videos',return_value=[quick,long]), \
             patch.object(server,'_nfl_team_video_results',return_value=[]):
            rows=server._nfl_official_extended_results('2026-08-20','Raiders','Texans')
        self.assertEqual([x['youtubeId'] for x in rows],['long'])
        self.assertEqual(rows[0]['recapTier'],'extended'); self.assertEqual(rows[0]['mediaObjective'],'EXTENDED')

    def test_official_nfl_atom_feed_finds_recap_without_api_key(self):
        from io import BytesIO
        xml=b"""<?xml version='1.0' encoding='UTF-8'?>
        <feed xmlns='http://www.w3.org/2005/Atom' xmlns:yt='http://www.youtube.com/xml/schemas/2015' xmlns:media='http://search.yahoo.com/mrss/'>
          <entry>
            <yt:videoId>8wd5sEqGYpI</yt:videoId>
            <title>Las Vegas Raiders vs. Houston Texans | 2026 Preseason Week 2</title>
            <published>2026-08-21T03:00:00Z</published>
            <media:group><media:thumbnail url='https://img.test/nfl.jpg'/></media:group>
          </entry>
          <entry>
            <yt:videoId>noise</yt:videoId>
            <title>NFL Top 100 Players</title>
            <published>2026-08-21T02:00:00Z</published>
          </entry>
        </feed>"""
        with patch.object(server,'urlopen',return_value=BytesIO(xml)):
            rows=server._official_nfl_feed_videos('2026-08-20','Las Vegas Raiders','Houston Texans')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['youtubeId'],'8wd5sEqGYpI')
        self.assertTrue(rows[0]['overview'])
        self.assertEqual(rows[0]['sourceLabel'],'NFL')

    def test_official_nfl_feed_filters_non_embeddable_video_when_key_exists(self):
        from io import BytesIO
        xml=b"""<?xml version='1.0' encoding='UTF-8'?>
        <feed xmlns='http://www.w3.org/2005/Atom' xmlns:yt='http://www.youtube.com/xml/schemas/2015' xmlns:media='http://search.yahoo.com/mrss/'>
          <entry><yt:videoId>blocked123</yt:videoId><title>San Francisco 49ers vs. Los Angeles Chargers | 2026 Preseason Week 2</title><published>2026-08-21T03:00:00Z</published></entry>
          <entry><yt:videoId>playable456</yt:videoId><title>San Francisco 49ers vs. Los Angeles Chargers | 2026 Preseason Week 2 Game Highlights</title><published>2026-08-21T03:01:00Z</published></entry>
        </feed>"""
        details={"items":[
            {"id":"blocked123","status":{"embeddable":False,"privacyStatus":"public"},"contentDetails":{"duration":"PT10M"}},
            {"id":"playable456","status":{"embeddable":True,"privacyStatus":"public"},"contentDetails":{"duration":"PT8M"}},
        ]}
        with patch.object(server,'urlopen',return_value=BytesIO(xml)), \
             patch.object(server,'read_youtube_key',return_value='key'), \
             patch.object(server,'youtube_fetch_json',return_value=details):
            rows=server._official_nfl_feed_videos('2026-08-20','San Francisco 49ers','Los Angeles Chargers')
        self.assertEqual([x['youtubeId'] for x in rows],['blocked123','playable456'])
        blocked,playable=rows
        self.assertTrue(blocked['externalOnly'])
        self.assertFalse(blocked['verifiedPlayable'])
        self.assertFalse(blocked['embedValidated'])
        self.assertTrue(playable['verifiedPlayable'])
        self.assertTrue(playable['embedValidated'])
        self.assertEqual(playable['durationSeconds'],480)

    def test_nfl_event_id_espn_video_package_provides_direct_playable_media(self):
        payload={"videos":[{
            "id":"espnclip1","headline":"49ers vs. Chargers Game Highlights","duration":242,
            "tracking":{"coverageType":"Final Game Highlight"},
            "links":{"source":{"HD":{"href":"https://media.video-cdn.espn.com/motion/test/highlights_720.mp4"}}}
        }]}
        with patch.object(server,'_espn_fetch_json',return_value=payload) as fetcher:
            rows=server._espn_event_video_results('401873285','NFL','San Francisco 49ers','Los Angeles Chargers')
        self.assertEqual(len(rows),1)
        self.assertTrue(rows[0]['verifiedPlayable'])
        self.assertTrue(rows[0]['overview'])
        self.assertEqual(rows[0]['provider'],'ESPN')
        self.assertTrue(rows[0]['mediaUrl'].endswith('.mp4'))
        self.assertIn('summary?event=401873285',fetcher.call_args.args[0])

    def test_nfl_club_site_fallback_surfaces_official_full_game_highlights(self):
        from io import BytesIO
        page=b'<html><body><a href="/video/full-game-highlights-raiders-vs-texans-nfl-preseason-week-2-2026">Full Game Highlights: Raiders vs. Texans - Preseason Week 2</a></body></html>'
        with patch.object(server,'urlopen',return_value=BytesIO(page)):
            rows=server._nfl_team_site_video_results('2026-08-20','Las Vegas Raiders','Houston Texans')
        self.assertTrue(rows)
        self.assertTrue(rows[0]['externalOnly'])
        self.assertTrue(rows[0]['overview'])
        self.assertIn('raiders.com/video/full-game-highlights',rows[0]['externalUrl'])

    def test_v412_nfl_team_registry_covers_all_32_clubs(self):
        self.assertEqual(len(server.NFL_TEAM_SITE_DOMAINS),32)
        self.assertEqual(server._nfl_team_site_domain('Tampa Bay Buccaneers'),'buccaneers.com')
        self.assertEqual(server._nfl_team_site_domain('San Francisco 49ers'),'49ers.com')

    def test_v412_nfl_team_title_disposition_is_fail_closed(self):
        away='Tampa Bay Buccaneers'; home='Atlanta Falcons'
        self.assertEqual(server._nfl_team_title_disposition('Bucs vs. Falcons Full Game Highlights',away,home),'GAME_PACKAGE')
        self.assertEqual(server._nfl_team_title_disposition('Bucs vs. Falcons Postgame Press Conference',away,home),'POSTGAME_REACTION')
        self.assertEqual(server._nfl_team_title_disposition('Bucs vs. Falcons Baker Mayfield touchdown highlights',away,home),'INDIVIDUAL_PLAY')
        self.assertEqual(server._nfl_team_title_disposition('Saints vs. Falcons Full Game Highlights',away,home),'EVENT_MISMATCH')

    def test_v412_nflplus_replay_is_entitlement_gated_not_game_media(self):
        gated={'title':'Buccaneers at Falcons Full Game Replay','externalUrl':'https://www.nfl.com/games/buccaneers-at-falcons-2025-reg-1?tab=replays-highlights'}
        self.assertEqual(server._nfl_candidate_disposition(gated),'ENTITLEMENT_GATED')
        condensed={'title':'Buccaneers vs Falcons Condensed Game Replay','externalUrl':'https://www.nfl.com/plus'}
        self.assertEqual(server._nfl_candidate_disposition(condensed),'ENTITLEMENT_GATED')

    def test_v412_nfl_team_sitemap_parser_preserves_date_and_public_page(self):
        page_html='<table><tr><td>2025-09-08</td><td><a href="/video/full-game-highlights-falcons-bucs-win-score-23-20-week-1-2025">Bucs vs. Falcons Full Game Highlights</a></td></tr></table>'
        rows=server._nfl_team_sitemap_entries(page_html,'https://www.buccaneers.com/sitemap/html/videos/2025/9')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['publishedAt'],'2025-09-08')
        self.assertEqual(rows[0]['url'],'https://www.buccaneers.com/video/full-game-highlights-falcons-bucs-win-score-23-20-week-1-2025')

    def test_v414_nfl_official_playlist_extended_is_first_class_and_search_free(self):
        playlist={'playlistId':'PLweek16','title':'Week 16 - 2025 Season','seasonYear':2025}
        item={'id':'nfl-playlist-PLweek16-long','youtubeId':'long','league':'NFL','title':'Buffalo Bills vs. Cleveland Browns | 2025 Week 16 Game Highlights','description':'Official NFL game recap','durationSeconds':720,'duration':720,'source':'NFL','sourceLabel':'NFL','sourceType':'official-nfl-youtube-playlist','provider':'YOUTUBE','verifiedPlayable':True,'embedValidated':True,'validationState':'VERIFIED','externalUrl':'https://www.youtube.com/watch?v=long','officialChannelId':server.NFL_YOUTUBE_CHANNEL_ID,'officialPlaylistId':'PLweek16','officialPlaylistTitle':'Week 16 - 2025 Season','discoverySourceFamily':'nfl-youtube-playlist','overview':True,'programType':'recap'}
        with patch.object(server,'_nfl_candidate_recap_playlists',return_value=[playlist]), patch.object(server,'_nfl_youtube_playlist_items',return_value=[item]):
            rows=server._nfl_youtube_playlist_results('2025-12-21','Buffalo Bills','Cleveland Browns',objective='extended')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['youtubeId'],'long')
        self.assertEqual(rows[0]['mediaObjective'],'EXTENDED')
        self.assertEqual(rows[0]['recapTier'],'extended')
        self.assertEqual(rows[0]['discoverySourceFamily'],'nfl-youtube-playlist')


    def test_v415_epl_nbc_playlist_highlights_are_extended_and_exact_event(self):
        playlist={'playlistId':'PLnbc','title':'Premier League 2026-27 season','seasonStart':2026,'family':'epl-youtube-nbc','role':'season-highlights','channelId':'NBC123'}
        item={'id':'epl-playlist-PLnbc-nbc1','youtubeId':'nbc1','league':'EPL','title':'Brentford v. Tottenham Hotspur | PREMIER LEAGUE HIGHLIGHTS | 8/22/2026 | NBC Sports','description':'','durationSeconds':900,'duration':900,'publishedAt':'2026-08-22T20:00:00Z','sourceType':'trusted-nbc-epl-youtube-highlights','provider':'YOUTUBE','verifiedPlayable':True,'validationState':'VERIFIED','externalUrl':'https://www.youtube.com/watch?v=nbc1','discoverySourceFamily':'epl-youtube-nbc'}
        with patch.object(server,'_epl_nbc_highlight_inventory',return_value=[item]):
            rows=server._epl_youtube_playlist_results('2026-08-22','Tottenham Hotspur','Brentford',objective='extended',family='epl-youtube-nbc')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['youtubeId'],'nbc1')
        self.assertEqual(rows[0]['mediaObjective'],'EXTENDED')
        self.assertEqual(rows[0]['recapTier'],'extended')

    def test_v415_epl_official_club_highlights_classify_by_duration(self):
        playlist={'playlistId':'PLclub','title':'Club highlights 2026/27','seasonStart':2026,'family':'epl-youtube-pl','role':'club-highlights','channelId':server.EPL_YOUTUBE_PL_CHANNEL_ID}
        quick={'id':'q','youtubeId':'q','league':'EPL','title':'Everton v. Crystal Palace | Match Highlights','description':'','durationSeconds':300,'duration':300,'publishedAt':'2026-08-22T20:00:00Z','sourceType':'official-premierleague-youtube-highlights','provider':'YOUTUBE','verifiedPlayable':True,'validationState':'VERIFIED','externalUrl':'https://www.youtube.com/watch?v=q','discoverySourceFamily':'epl-youtube-pl'}
        extended=dict(quick,id='x',youtubeId='x',durationSeconds=720,duration=720,externalUrl='https://www.youtube.com/watch?v=x')
        with patch.object(server,'_epl_candidate_playlists',return_value=[playlist]), patch.object(server,'_epl_youtube_playlist_items',return_value=[quick,extended]):
            qrows=server._epl_youtube_playlist_results('2026-08-22','Crystal Palace','Everton',objective='quick',family='epl-youtube-pl')
            xrows=server._epl_youtube_playlist_results('2026-08-22','Crystal Palace','Everton',objective='extended',family='epl-youtube-pl')
        self.assertEqual([x['youtubeId'] for x in qrows],['q'])
        self.assertEqual([x['youtubeId'] for x in xrows],['x'])

    def test_v415_epl_playlist_items_are_search_quota_independent(self):
        calls=[]
        def fake(url,timeout=10):
            calls.append(url)
            if '/playlistItems?' in url:
                return {'items':[{'contentDetails':{'videoId':'nbc1'},'snippet':{'resourceId':{'videoId':'nbc1'}}}]}
            if '/videos?' in url:
                return {'items':[{'id':'nbc1','snippet':{'channelId':'NBC123','channelTitle':'NBC Sports','title':'Everton v. Crystal Palace | PREMIER LEAGUE HIGHLIGHTS | 8/22/2026 | NBC Sports','description':'','publishedAt':'2026-08-22T20:00:00Z','thumbnails':{'high':{'url':'thumb'}}},'contentDetails':{'duration':'PT14M'},'status':{'privacyStatus':'public','embeddable':True}}]}
            return {}
        playlist={'playlistId':'PLnbc','title':'Premier League 2026-27 season','seasonStart':2026,'family':'epl-youtube-nbc','role':'season-highlights','channelId':'NBC123'}
        with tempfile.TemporaryDirectory() as td, patch.object(server,'read_youtube_key',return_value='k'), patch.object(server,'youtube_fetch_json',side_effect=fake), patch.object(server,'_epl_youtube_playlist_items_cache_path',return_value=Path(td)/'items.json'):
            rows=server._epl_youtube_playlist_items(playlist,force=True)
        self.assertEqual(rows[0]['youtubeId'],'nbc1')
        self.assertTrue(any('/playlistItems?' in x for x in calls))
        self.assertTrue(any('/videos?' in x for x in calls))
        self.assertFalse(any('/search?' in x for x in calls))

    def test_v412_public_team_full_game_highlights_can_be_extended_playable(self):
        entry={'url':'https://www.buccaneers.com/video/full-game-highlights-falcons-bucs-win-score-23-20-week-1-2025','title':'Bucs vs. Falcons Full Game Highlights','description':'Bucs vs. Falcons Full Game Highlights','publishedAt':'2025-09-08'}
        detail='<meta property="og:title" content="Bucs vs. Falcons Full Game Highlights"><meta property="og:video" content="https://cdn.test/bucs-falcons.mp4"><meta property="og:video:duration" content="660"><meta property="article:published_time" content="2025-09-08T12:00:00Z">'
        with patch.object(server,'_nfl_team_sitemap_urls',return_value=['https://www.buccaneers.com/sitemap/html/videos/2025/9']), \
             patch.object(server,'_history_shared_catalog',return_value=[entry]), \
             patch.object(server,'_official_fetch_page_text',return_value=detail):
            rows=server._nfl_team_video_results('2025-09-07','Tampa Bay Buccaneers','Atlanta Falcons',objective='extended')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['mediaObjective'],'EXTENDED')
        self.assertEqual(rows[0]['recapTier'],'extended')
        self.assertEqual(rows[0]['discoverySourceFamily'],'nfl-team-video')
        self.assertEqual(rows[0]['durationSeconds'],660)

    def test_v413_mls_candidate_disposition_reports_association_failure(self):
        row={'competitionId':'MLS','__sbbLeague':'MLS','__sbbDate':'2026-08-22','scoreEventId':'761746','awayTeam':{'name':'Columbus Crew'},'homeTeam':{'name':'Nashville SC'}}
        wrong={'title':'MATCH SNAPSHOT: Atlanta United FC vs Toronto FC','sourceType':'official-mls-match-snapshot','mediaUrl':'https://cdn.test/snapshot.mp4'}
        self.assertEqual(server._mls_candidate_disposition(wrong,row,'quick'),'TEAM_MISMATCH')

    def test_v413_persisted_disposition_distinguishes_normalized_from_repository_truth(self):
        from sbb.history_repository import HistoryRepository
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite3')
            event={'id':'evt413','awayTeam':{'name':'Alpha Bears'},'homeTeam':{'name':'Beta Hawks'}}
            repo.put_scores('2026-08-20','NFL',[event])
            item={'youtubeId':'persist413','title':'Alpha Bears vs Beta Hawks Game Highlights','verifiedPlayable':True,'validationState':'VERIFIED','recapTier':'green','mediaObjective':'QUICK','provider':'YOUTUBE'}
            repo.put_event_media('2026-08-20','NFL','evt413',[item])
            with patch.object(server,'HISTORY_REPOSITORY',repo):
                self.assertEqual(server._history_persisted_candidate_disposition(item,'NFL','evt413','quick'),'PERSISTED_QUICK')
                missing=dict(item); missing['youtubeId']='missing413'
                self.assertEqual(server._history_persisted_candidate_disposition(missing,'NFL','evt413','quick'),'PERSISTENCE_MISSING_LINK')

    def test_v412_mls_snapshot_infers_date_from_adjacent_official_highlight(self):
        entries=[
            {'url':'https://www.mlssoccer.com/video/match-snapshot-atlanta-toronto','title':'MATCH SNAPSHOT: Atlanta United FC vs Toronto FC','description':''},
            {'url':'https://www.mlssoccer.com/video/highlights-atlanta-toronto','title':'HIGHLIGHTS: Atlanta United FC vs Toronto FC | April 25, 2026','description':''},
        ]
        detail='<meta property="og:title" content="MATCH SNAPSHOT: Atlanta United FC vs Toronto FC"><meta property="og:video" content="https://cdn.test/mls-snapshot.mp4"><meta property="og:video:duration" content="59">'
        with patch.object(server,'_history_shared_catalog',return_value=entries), patch.object(server,'_official_fetch_page_text',return_value=detail):
            rows=server._mls_official_web_results('2026-04-25','Atlanta United FC','Toronto FC',max_items=1,objective='quick')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['mediaObjective'],'QUICK')
        self.assertEqual(rows[0]['recapTier'],'green')
        self.assertEqual(rows[0]['durationSeconds'],59)

    def test_cross_sport_espn_video_fallback_runs_without_youtube_key(self):
        espn_row={'id':'espn-1','league':'NFL','title':'Raiders vs Texans game highlights','mediaUrl':'https://example.test/video.mp4','verifiedPlayable':True,'overview':True,'programType':'recap','durationSeconds':240,'importance':90}
        with tempfile.TemporaryDirectory() as td, \
             patch.object(server,'read_youtube_key',return_value=''), \
             patch.object(server,'_official_nfl_feed_videos',return_value=[]), \
             patch.object(server,'_nfl_game_highlights_results',return_value=[]), \
             patch.object(server,'_historical_youtube_web_results',return_value=[]), \
             patch.object(server,'_historical_search_engine_youtube_results',return_value=[]), \
             patch.object(server,'_official_youtube_history_api_results',return_value=[]), \
             patch.object(server,'_espn_search_video_results',return_value=[espn_row]) as espn, \
             patch.object(server,'_generic_rapid_cache_path',return_value=Path(td)/'nfl.json'):
            rows=server.generic_rapid_team_videos('NFL','2026-08-20','Las Vegas Raiders','Houston Texans',force_refresh=True)
        espn.assert_called_once()
        self.assertEqual(rows[0]['id'],'espn-1')
        self.assertTrue(rows[0]['verifiedPlayable'])

    def test_nfl_preseason_week_rescue_finds_target_day_when_date_boards_are_empty(self):
        event={
            "id":"401873285","date":"2026-08-21T02:00:00Z","name":"San Francisco 49ers at Los Angeles Chargers","shortName":"SF @ LAC",
            "competitions":[{"competitors":[
                {"homeAway":"away","score":"41","team":{"displayName":"San Francisco 49ers","abbreviation":"SF"}},
                {"homeAway":"home","score":"17","team":{"displayName":"Los Angeles Chargers","abbreviation":"LAC"}}
            ]}],
            "status":{"displayClock":"0:00","period":4,"type":{"state":"post","shortDetail":"Final","completed":True}}
        }
        calls=[]
        def fake_fetch(url,timeout=8):
            calls.append(url)
            if 'seasontype=1' in url and 'week=2' in url: return {"events":[event]}
            return {"events":[]}
        with patch.object(server,'_read_scoreboard_cache',return_value=(None,None)), patch.object(server,'_write_scoreboard_cache'), patch.object(server,'_espn_fetch_json',side_effect=fake_fetch), patch.object(server,'ZoneInfo',side_effect=Exception('tzdata unavailable')):
            rows=server._espn_scoreboard('NFL','2026-08-20','America/Los_Angeles',-420)
        self.assertEqual([x['id'] for x in rows],['401873285'])
        self.assertTrue(any('seasontype=1' in u and 'week=2' in u for u in calls))

    def test_soccer_all_parser_collects_later_league_event_lists(self):
        other={"id":"other","date":"2026-08-21T18:00:00Z","season":{"slug":"spanish-la-liga"},"competitions":[{"competitors":[]}],"status":{"type":{"state":"pre"}}}
        epl={
            "id":"epl-ars-cov","date":"2026-08-21T19:00:00Z","season":{"slug":"2026-27-english-premier-league"},
            "name":"Coventry City at Arsenal","competitions":[{"competitors":[
                {"homeAway":"away","team":{"displayName":"Coventry City","abbreviation":"COV"}},
                {"homeAway":"home","team":{"displayName":"Arsenal","abbreviation":"ARS"}}
            ]}],"status":{"type":{"state":"pre","shortDetail":"Scheduled","completed":False}}
        }
        payload={"sports":[{"leagues":[{"events":[other]},{"events":[epl]}]}]}
        rows=server._espn_event_rows(payload)
        self.assertEqual({x['id'] for x in rows},{'other','epl-ars-cov'})
        self.assertTrue(server._espn_generic_soccer_event_matches(epl,'EPL'))

    def test_epl_season_rescue_finds_fixture_when_day_endpoints_are_empty(self):
        epl={
            "id":"epl-ars-cov","date":"2026-08-21T19:00:00Z","season":{"slug":"2026-27-english-premier-league"},
            "name":"Coventry City at Arsenal","competitions":[{"competitors":[
                {"homeAway":"away","team":{"displayName":"Coventry City","abbreviation":"COV"}},
                {"homeAway":"home","team":{"displayName":"Arsenal","abbreviation":"ARS"}}
            ]}],"status":{"type":{"state":"pre","shortDetail":"Scheduled","completed":False}}
        }
        def fake_fetch(url,timeout=8):
            if '/soccer/eng.1/scoreboard' in url and 'dates=2026&' in url: return {"events":[epl]}
            return {"events":[]}
        with patch.object(server,'_read_scoreboard_cache',return_value=(None,None)), patch.object(server,'_write_scoreboard_cache'), patch.object(server,'_espn_fetch_json',side_effect=fake_fetch), patch.object(server,'ZoneInfo',side_effect=Exception('tzdata unavailable')):
            rows=server._espn_scoreboard('EPL','2026-08-21','America/New_York',-240)
        self.assertEqual([x['id'] for x in rows],['epl-ars-cov'])


    def test_v416_pinned_epl_playlist_is_direct_first_without_catalog_dependency(self):
        rows=server._epl_pinned_playlists('2026-08-22',family='epl-youtube-nbc',role='season-highlights')
        self.assertEqual(rows[0]['playlistId'],'PLR1b-6EyIaTs')
        self.assertTrue(rows[0]['pinned'])
        self.assertEqual(rows[0]['channelId'],server.EPL_YOUTUBE_NBC_CHANNEL_ID)

    def test_v417_epl_2025_26_nbc_playlist_is_pinned_for_historical_backfill(self):
        rows=server._epl_pinned_playlists('2025-12-07',family='epl-youtube-nbc',role='season-highlights')
        self.assertEqual([x['playlistId'] for x in rows],['PLXEMPXZ3PY1hMzinDc1TvSm8U2NUyz-0E'])
        self.assertEqual(rows[0]['seasonStart'],2025)
        self.assertTrue(rows[0]['pinned'])

    def test_v416_empty_pinned_playlist_can_repair_through_trusted_channel_catalog(self):
        pinned={'playlistId':'short','title':'Premier League 2026-27 season','seasonStart':2026,'family':'epl-youtube-nbc','role':'season-highlights','channelId':server.EPL_YOUTUBE_NBC_CHANNEL_ID,'pinned':True}
        alias={'playlistId':'canonical','title':'Premier League 2026-27 season','seasonStart':2026,'family':'epl-youtube-nbc','role':'season-highlights','channelId':server.EPL_YOUTUBE_NBC_CHANNEL_ID,'catalogDiscovered':True}
        calls=[]
        def fake(url,timeout=10):
            calls.append(url)
            if 'playlistId=short' in url: return {'items':[]}
            if 'playlistId=canonical' in url: return {'items':[{'contentDetails':{'videoId':'v1'},'snippet':{'resourceId':{'videoId':'v1'}}}]}
            if '/videos?' in url: return {'items':[{'id':'v1','snippet':{'channelId':server.EPL_YOUTUBE_NBC_CHANNEL_ID,'channelTitle':'NBC Sports','title':'Everton v. Crystal Palace | PREMIER LEAGUE HIGHLIGHTS | 8/22/2026 | NBC Sports','description':'','publishedAt':'2026-08-22T20:00:00Z','thumbnails':{}},'contentDetails':{'duration':'PT14M'},'status':{'privacyStatus':'public','embeddable':True}}]}
            return {}
        with tempfile.TemporaryDirectory() as td, patch.object(server,'read_youtube_key',return_value='k'), patch.object(server,'youtube_fetch_json',side_effect=fake), patch.object(server,'_epl_catalog_fallback_for_pinned',return_value=alias), patch.object(server,'_epl_youtube_playlist_items_cache_path',side_effect=lambda pid: Path(td)/(str(pid)+'.json')):
            rows=server._epl_youtube_playlist_items(pinned,force=True)
        self.assertEqual([x['youtubeId'] for x in rows],['v1'])
        self.assertTrue(any('playlistId=short' in x for x in calls))
        self.assertTrue(any('playlistId=canonical' in x for x in calls))


    def test_v417_epl_nbc_numeric_title_date_and_unordered_pair_are_explicit(self):
        title='Brentford v. Tottenham Hotspur | PREMIER LEAGUE HIGHLIGHTS | 8/22/2026 | NBC Sports'
        parsed=server._epl_parse_match_title(title,2026)
        self.assertTrue(parsed['ok'])
        self.assertEqual(parsed['left'],'Brentford')
        self.assertEqual(parsed['right'],'Tottenham Hotspur')
        self.assertEqual(parsed['date'],'2026-08-22')
        self.assertTrue(server._epl_parsed_pair_matches_event(parsed,'Tottenham Hotspur','Brentford'))

    def test_v417_epl_alias_matching_handles_common_short_names(self):
        parsed=server._epl_parse_match_title('Man City vs. Man Utd | PREMIER LEAGUE HIGHLIGHTS | 8/23/2026 | NBC Sports',2026)
        self.assertTrue(server._epl_parsed_pair_matches_event(parsed,'Manchester United','Manchester City'))
        self.assertTrue(server._epl_team_equivalent('Spurs','Tottenham Hotspur'))
        self.assertTrue(server._epl_team_equivalent('Wolves','Wolverhampton Wanderers'))

    def test_v418_epl_pl_score_title_parses_unordered_matchup(self):
        parsed=server._epl_parse_match_title('Brentford 3-0 Tottenham Hotspur | Premier League 2026/27 Highlights',2026)
        self.assertTrue(parsed['ok'])
        self.assertEqual(parsed['left'],'Brentford')
        self.assertEqual(parsed['right'],'Tottenham Hotspur')
        self.assertEqual(parsed['method'],'SCORE')
        self.assertTrue(server._epl_parsed_pair_matches_event(parsed,'Tottenham Hotspur','Brentford'))

    def test_v418_epl_nbc_event_team_scan_handles_unexpected_separator(self):
        playlist={'playlistId':'PLnbc','title':'Premier League 2026-27 season','seasonStart':2026,'family':'epl-youtube-nbc','role':'season-highlights','channelId':'NBC123'}
        item={'id':'n','youtubeId':'n','league':'EPL','title':'Brentford - Tottenham Hotspur | PREMIER LEAGUE HIGHLIGHTS | 8/22/2026 | NBC Sports','description':'','durationSeconds':900,'duration':900,'publishedAt':'2026-08-22T20:00:00Z','sourceType':'trusted-nbc-epl-youtube-highlights','provider':'YOUTUBE','verifiedPlayable':True,'validationState':'VERIFIED','externalUrl':'https://www.youtube.com/watch?v=n','discoverySourceFamily':'epl-youtube-nbc'}
        with patch.object(server,'_epl_nbc_highlight_inventory',return_value=[item]):
            rows=server._epl_youtube_playlist_results('2026-08-22','Tottenham Hotspur','Brentford',objective='extended',family='epl-youtube-nbc')
        self.assertEqual([x['youtubeId'] for x in rows],['n'])
        self.assertEqual(rows[0]['titleMatchMethod'],'EVENT_TEAM_SCAN')
        tel=server.HISTORY_MEDIA_AUDIT['eplPlaylistTelemetry']
        self.assertGreaterEqual(tel.get('nbcPairMatches',0),1)
        self.assertGreaterEqual(tel.get('nbcDurationPass',0),1)
        self.assertGreaterEqual(tel.get('nbcAssociationPass',0),1)

    def test_v418_every_goal_all_the_goals_matchweek_title_is_accepted(self):
        playlist={'playlistId':'PLgoals','title':'Every Goal by Premier League Matchweek: 2026-27','seasonStart':2026,'family':'epl-youtube-pl','role':'every-goal','channelId':server.EPL_YOUTUBE_PL_CHANNEL_ID}
        item={'id':'g','youtubeId':'g','league':'EPL','title':'ALL The Goals From Opening Weekend | Matchweek 1 | 2026/27 Premier League Highlights','description':'','durationSeconds':720,'duration':720,'publishedAt':'2026-08-23T12:00:00Z','sourceType':'official-premierleague-youtube-highlights','provider':'YOUTUBE','verifiedPlayable':True,'validationState':'VERIFIED','externalUrl':'https://www.youtube.com/watch?v=g','discoverySourceFamily':'epl-youtube-pl'}
        self.assertEqual(server._epl_every_goal_matchweek(item['title']),1)
        with patch.object(server,'_epl_candidate_playlists',return_value=[playlist]), patch.object(server,'_epl_youtube_playlist_items',return_value=[item]):
            rows=server._epl_youtube_every_goal_results('2026-08-23')
        self.assertEqual([x['youtubeId'] for x in rows],['g'])
        self.assertEqual(rows[0]['collectionRoundNumber'],1)

    def test_v417_every_goal_pinned_playlist_trusts_curated_member_owner(self):
        calls=[]
        def fake(url,timeout=10):
            calls.append(url)
            if '/playlistItems?' in url:
                return {'items':[{'contentDetails':{'videoId':'goals1'},'snippet':{'resourceId':{'videoId':'goals1'}}}]}
            if '/videos?' in url:
                return {'items':[{'id':'goals1','snippet':{'channelId':'CLUB_PARTNER','channelTitle':'Official Club Partner','title':'Every Goal from Matchweek 1 | Premier League 2026/27','description':'','publishedAt':'2026-08-23T12:00:00Z','thumbnails':{}},'contentDetails':{'duration':'PT12M','regionRestriction':{}},'status':{'privacyStatus':'public','embeddable':True}}]}
            return {}
        playlist={'playlistId':'PLVJum5p_YGgA','title':'Every Goal by Premier League Matchweek: 2026-27','seasonStart':2026,'family':'epl-youtube-pl','role':'every-goal','channelId':server.EPL_YOUTUBE_PL_CHANNEL_ID,'pinned':True}
        with tempfile.TemporaryDirectory() as td, patch.object(server,'read_youtube_key',return_value='k'), patch.object(server,'youtube_fetch_json',side_effect=fake), patch.object(server,'_epl_youtube_playlist_items_cache_path',return_value=Path(td)/'items.json'):
            rows=server._epl_youtube_playlist_items(playlist,force=True)
        self.assertEqual([x['youtubeId'] for x in rows],['goals1'])
        self.assertEqual(server.HISTORY_MEDIA_AUDIT['eplPlaylistTelemetry']['everyGoalVideoIds'],1)
        self.assertEqual(server.HISTORY_MEDIA_AUDIT['eplPlaylistTelemetry']['everyGoalVideoDetails'],1)


    def test_v419_every_goal_matchweek_can_come_from_description_and_records_disposition(self):
        playlist={'playlistId':'PLgoals','title':'Every Goal by Premier League Matchweek: 2026-27','seasonStart':2026,'family':'epl-youtube-pl','role':'every-goal','channelId':server.EPL_YOUTUBE_PL_CHANNEL_ID}
        item={'id':'g2','youtubeId':'g2','league':'EPL','title':'Opening Weekend Goals | Premier League 2026/27','description':'All the goals from Match Week 1','durationSeconds':720,'duration':720,'publishedAt':'2026-08-23T12:00:00Z','sourceType':'official-premierleague-youtube-highlights','provider':'YOUTUBE','verifiedPlayable':True,'validationState':'VERIFIED','externalUrl':'https://www.youtube.com/watch?v=g2','discoverySourceFamily':'epl-youtube-pl'}
        with patch.object(server,'_epl_candidate_playlists',return_value=[playlist]), patch.object(server,'_epl_youtube_playlist_items',return_value=[item]):
            rows=server._epl_youtube_every_goal_results('2026-08-23')
        self.assertEqual([x['youtubeId'] for x in rows],['g2'])
        self.assertEqual(rows[0]['collectionRoundNumber'],1)
        tel=server.HISTORY_MEDIA_AUDIT['eplPlaylistTelemetry']
        self.assertEqual(tel.get('everyGoalLastDisposition'),'ACCEPTED_MATCHWEEK_1')

    def test_v419_nbc_inventory_is_direct_input_to_matcher(self):
        item={'id':'n2','youtubeId':'n2','league':'EPL','title':'Everton v. Crystal Palace | PREMIER LEAGUE HIGHLIGHTS | 8/22/2026 | NBC Sports','description':'','durationSeconds':900,'duration':900,'publishedAt':'2026-08-22T20:00:00Z','sourceType':'trusted-nbc-epl-youtube-highlights','provider':'YOUTUBE','verifiedPlayable':True,'validationState':'VERIFIED','externalUrl':'https://www.youtube.com/watch?v=n2','discoverySourceFamily':'epl-youtube-nbc'}
        with patch.object(server,'_epl_nbc_highlight_inventory',return_value=[item]):
            rows=server._epl_youtube_playlist_results('2026-08-22','Crystal Palace','Everton',objective='extended',family='epl-youtube-nbc')
        self.assertEqual([x['youtubeId'] for x in rows],['n2'])



    def test_v420_nbc_matcher_calls_every_inventory_item_and_invariant_holds(self):
        server._epl_unique_reset_for_tests()
        inventory=[]
        for i in range(44):
            title=(f'Everton v. Crystal Palace | PREMIER LEAGUE HIGHLIGHTS | 8/22/2026 | NBC Sports' if i==17 else f'Club {i} v. Other {i} | PREMIER LEAGUE HIGHLIGHTS | 8/22/2026 | NBC Sports')
            inventory.append({'id':f'n{i}','youtubeId':f'n{i}','league':'EPL','title':title,'description':'','durationSeconds':900,'duration':900,'publishedAt':'2026-08-22T20:00:00Z','sourceType':'trusted-nbc-epl-youtube-highlights','provider':'YOUTUBE','verifiedPlayable':True,'validationState':'VERIFIED','externalUrl':f'https://www.youtube.com/watch?v=n{i}','discoverySourceFamily':'epl-youtube-nbc'})
        with patch.object(server,'_epl_nbc_highlight_inventory',return_value=inventory):
            rows=server._epl_youtube_playlist_results('2026-08-22','Crystal Palace','Everton',objective='extended',family='epl-youtube-nbc')
        self.assertEqual([x['youtubeId'] for x in rows],['n17'])
        tel=server.HISTORY_MEDIA_AUDIT['eplPlaylistTelemetry']
        self.assertEqual(tel.get('nbcMatcherInventory'),44)
        self.assertEqual(tel.get('nbcMatcherCalls'),44)
        self.assertEqual(tel.get('nbcInvariantErrors'),0)
        self.assertEqual(tel.get('nbcTitlesExamined'),44)
        self.assertEqual(tel.get('nbcTraceDisposition'),'ASSOCIATED_PENDING_PERSISTENCE')

    def test_v420_pl_unique_object_telemetry_does_not_multiply_repeated_event_scans(self):
        server._epl_unique_reset_for_tests()
        playlist={'playlistId':'plclub','title':'Club highlights 2026/27','seasonStart':2026,'family':'epl-youtube-pl','role':'club-highlights','channelId':server.EPL_YOUTUBE_PL_CHANNEL_ID}
        item={'id':'pl1','youtubeId':'pl1','league':'EPL','title':'Everton 2-0 Crystal Palace | Premier League 2026/27 Highlights','description':'','durationSeconds':900,'duration':900,'publishedAt':'2026-08-22T20:00:00Z','sourceType':'official-premierleague-youtube-highlights','provider':'YOUTUBE','verifiedPlayable':True,'validationState':'VERIFIED','externalUrl':'https://www.youtube.com/watch?v=pl1','discoverySourceFamily':'epl-youtube-pl'}
        with patch.object(server,'_epl_candidate_playlists',return_value=[playlist]), patch.object(server,'_epl_youtube_playlist_items',return_value=[item]):
            server._epl_youtube_playlist_results('2026-08-22','Crystal Palace','Everton',objective='extended',family='epl-youtube-pl')
            server._epl_youtube_playlist_results('2026-08-22','Crystal Palace','Everton',objective='extended',family='epl-youtube-pl')
        tel=server.HISTORY_MEDIA_AUDIT['eplPlaylistTelemetry']
        self.assertEqual(tel.get('plTitlesExamined'),1)
        self.assertEqual(tel.get('plPairMatches'),1)
        self.assertEqual(tel.get('plAssociationPass'),1)

    def test_v420_every_goal_explicit_matchweek_flows_directly_into_silver_scope(self):
        item={'id':'g420','youtubeId':'g420','league':'EPL','title':'Opening Weekend Goals | Premier League 2026/27','description':'All the goals from Match Week 1','durationSeconds':720,'duration':720,'publishedAt':'2026-08-23T12:00:00Z','sourceType':'official-premierleague-youtube-every-goal','sourceLabel':'Premier League YouTube Every Goal','provider':'YOUTUBE','officialLeagueSource':True,'verifiedPlayable':True,'validationState':'VERIFIED','externalUrl':'https://www.youtube.com/watch?v=g420','discoverySourceFamily':'epl-youtube-pl','collectionRoundNumber':1,'collectionRoundType':'MATCHWEEK','overview':False,'programType':'roundup'}
        scoped=server.annotate_media_scope(item,league='EPL',date='2026-08-23')
        self.assertEqual(scoped.get('mediaScope'),server.MEDIA_SCOPE_ROUND_LEAGUE)
        self.assertTrue(scoped.get('collectionPromotionApproved'))
        self.assertEqual(scoped.get('collectionPeriodKey'),'2026-27:MW1')
        self.assertEqual(scoped.get('collectionKind'),'SCORING_ROUNDUP')

    def test_v420_epl_source_versions_reopen_only_epl_youtube_replay(self):
        self.assertEqual(server.HISTORY_RULE_CATCHUP_VERSION,10)
        self.assertEqual(server.HISTORY_RULE_COLLECTION_CATCHUP_VERSION,8)
        epl={x['key']:x['version'] for x in server.HISTORY_OFFICIAL_CATCHUP_SOURCES['EPL']}
        self.assertEqual(epl['epl-youtube-pl-quick'],6)
        self.assertEqual(epl['epl-youtube-pl-extended'],6)
        self.assertEqual(epl['epl-youtube-nbc-extended'],6)
        self.assertEqual({x['key']:x['version'] for x in server.HISTORY_OFFICIAL_CATCHUP_SOURCES['NFL']}['nfl-youtube-playlist-extended'],2)


if __name__=='__main__': unittest.main()

import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'app.js').read_text(encoding='utf-8')

class V439GameCenterCompetitionIdentityTests(unittest.TestCase):
    def test_mlb_fast_highlights_are_explicitly_mlb(self):
        start=APP.index('async function refreshLiveData(')
        end=APP.index('let lastOtherSportsRefresh',start)
        block=APP[start:end]
        self.assertIn("],\'MLB\');",block.replace(' ',''))
        self.assertNotIn("function normalizeHighlights(items, league='SPORTS')",APP)
        self.assertIn("function normalizeHighlights(items, league='')",APP)
        self.assertIn("const resolvedLeague=String(league||h.league||match.league||'SPORTS').toUpperCase();",APP)

    def test_generic_sports_media_cannot_own_game_center(self):
        self.assertIn('function gameCenterCompetitionId(item){',APP)
        self.assertIn("competitionId!=='SPORTS'",APP)
        self.assertIn('ENABLED_LIVE_LEAGUES.includes(competitionId)',APP)
        start=APP.index('function playbackOwnsGameCenter(item){')
        end=APP.index('function gameCenterEventForPlayback',start)
        self.assertIn('if(!gameCenterCompetitionSupported(item))return false;',APP[start:end])

    def test_launch_game_center_warmup_rejects_unsupported_competitions(self):
        start=APP.index('function scheduleLaunchGameCenterPopulate(){')
        end=APP.index('function confirmLaunchVisualPlayback',start)
        block=APP[start:end]
        self.assertIn('if(!gameCenterCompetitionSupported(item)) return;',block)
        self.assertLess(block.index('if(!gameCenterCompetitionSupported(item)) return;'),block.index('const match=launchScoreMatchForItem(item);'))

if __name__=='__main__': unittest.main()

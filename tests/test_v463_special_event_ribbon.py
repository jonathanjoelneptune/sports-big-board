import json
import re
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class V463SpecialEventRibbonTests(unittest.TestCase):
    def test_special_events_control_is_permanent_header_ui(self):
        index=(ROOT/"index.html").read_text(encoding="utf-8")
        self.assertIn('id="sbbSpecialEventsWrap"',index)
        self.assertIn('id="sbbSpecialEventsBtn"',index)
        self.assertIn('id="sbbSpecialEventsMenu"',index)
        self.assertLess(index.index('data-score-filter="ALL"'),index.index('id="sbbSpecialEventsWrap"'))
        self.assertLess(index.index('id="sbbSpecialEventsWrap"'),index.index('data-score-filter="MLB"'))

    def test_builder_populates_not_recreates_special_control(self):
        src=(ROOT/"architecture/competition-builder.js").read_text(encoding="utf-8")
        self.assertIn("const wrap=$('sbbSpecialEventsWrap')",src)
        self.assertIn("menu.innerHTML=''",src)
        self.assertNotIn("const wrap=document.createElement('span')",src)
        self.assertIn("dataset.specialCompetition",src)

    def test_completed_special_event_selection_navigates_into_event_range(self):
        src=(ROOT/"architecture/competition-builder.js").read_text(encoding="utf-8")
        self.assertIn("if(c.endDate&&targetDate>c.endDate)targetDate=c.endDate",src)
        self.assertIn("setScoreBrowseDate(targetDate",src)
        self.assertIn("await loadDate(targetDate||localISO(),{force:true})",src)

    def test_custom_scores_follow_score_date_store_browse_authority(self):
        src=(ROOT/"architecture/competition-builder.js").read_text(encoding="utf-8")
        self.assertIn("window.SBB_SCORE_DATE?.subscribe",src)
        self.assertIn("meta?.action==='browse'",src)
        self.assertIn("SCORE_DATE_STORE?.setMatches?.(date,c.id,rows)",src)
        self.assertIn("renderScoresFromMatchesCombined",src)

if __name__=="__main__":
    unittest.main()

import re
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class V465CompetitionBuilderBootTests(unittest.TestCase):
    def test_portal_helper_reads_existing_menu_without_recursing(self):
        src=(ROOT/"architecture/competition-builder.js").read_text(encoding="utf-8")
        m=re.search(r"function ensureSpecialMenuPortal\(\)\{(.*?)\n  \}",src,re.S)
        self.assertIsNotNone(m)
        body=m.group(1)
        self.assertIn("const menu=$('sbbSpecialEventsMenu')",body)
        self.assertNotIn("const menu=ensureSpecialMenuPortal()",body)
        self.assertIn("document.body.appendChild(menu)",body)

    def test_builder_boot_is_observable_and_failure_is_visible(self):
        src=(ROOT/"architecture/competition-builder.js").read_text(encoding="utf-8")
        for token in (
            "const bootState={state:'PENDING'",
            "document.documentElement.dataset.sbbCompetitionBuilder='READY'",
            "document.documentElement.dataset.sbbCompetitionBuilder='ERROR'",
            "SPECIAL EVENTS ⚠",
            "bootState:()=>({...bootState})",
        ):
            self.assertIn(token,src)

    def test_index_loads_builder_after_app_runtime(self):
        version=(ROOT/"VERSION").read_text(encoding="utf-8").strip()
        index=(ROOT/"index.html").read_text(encoding="utf-8")
        app=f'app.js?v={version}'
        builder=f'architecture/competition-builder.js?v={version}'
        self.assertIn(builder,index)
        self.assertLess(index.index(app),index.index(builder))

    def test_v464_world_cup_runtime_bridge_is_retained(self):
        front=(ROOT/"architecture/competition-builder.js").read_text(encoding="utf-8")
        back=(ROOT/"sbb/competition_builder.py").read_text(encoding="utf-8")
        for token in (
            "PARTICIPANT ARTWORK","COUNTRY FLAGS","REPAIR MEDIA",
            "rebuildVerifiedMediaIndex(SCORE_DATE_STORE?.allMedia?.(date)||media)",
            "/api/competition-builder/health",
        ):
            self.assertIn(token,front)
        for token in (
            "COUNTRY_FLAGS","flagcdn.com/w80","def _repair_event_media",
            "scoreEventId","canonicalEventId",
        ):
            self.assertIn(token,back)

if __name__=="__main__":
    unittest.main()

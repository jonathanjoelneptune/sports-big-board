import re
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RENDER=(ROOT/'architecture'/'render-pipeline.js').read_text(encoding='utf-8')
AVAIL=(ROOT/'architecture'/'score-card-availability-index.js').read_text(encoding='utf-8')
EFF=(ROOT/'architecture'/'efficiency-certification.js').read_text(encoding='utf-8')
INDEX=(ROOT/'index.html').read_text(encoding='utf-8')
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()

class V4715EfficiencyHardeningTests(unittest.TestCase):
    def test_filter_bank_fast_path_contract(self):
        for token in ('filterFastPath','sbbCardBankDate','bankComplete','applyBankFilter',"setCurrentFilter('ALL')",'card.hidden=!show'):
            self.assertIn(token,RENDER)
        start=RENDER.index('if(filterReason&&bankComplete(host,date))')
        end=RENDER.index('if(filterReason)state.filterFastPathMisses',start)
        block=RENDER[start:end]
        self.assertNotIn('fetch(',block)
        self.assertIn('applyBankFilter(host,selectedFilter',block)
        self.assertIn('if(filterReason)state.filterFastPathMisses',RENDER)

    def test_availability_snapshot_reuse_contract(self):
        for token in ("reason.includes('filter-change')",'snapshotReused','forDate','knownPlayableMedia','directVerified','legacy-resolved'):
            self.assertIn(token,AVAIL)
        self.assertIn('scoreMatchesForDate(date)',AVAIL)
        self.assertNotIn('if(!visibleMatch(match))continue',AVAIL)

    def test_efficiency_dom_and_media_readiness_contract(self):
        for token in ('sampleDomWindow','domAfter','domPeak','filterFastPaths','availabilitySnapshotReuses','NO_KNOWN_PLAYABLE_MEDIA','.forDate?.(date)','DOM_BASELINE=',"grades.includes('FAIL')"):
            self.assertIn(token,EFF)

    def test_release_cache_generation_is_atomic(self):
        refs=re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',INDEX)
        self.assertTrue(refs)
        self.assertTrue(all(v==VERSION for _,v in refs))
        self.assertIn("version:'4.7.15'",(ROOT/'core-model.js').read_text(encoding='utf-8'))

if __name__=='__main__':
    unittest.main()

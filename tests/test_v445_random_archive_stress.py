import re
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TERM=(ROOT/'architecture'/'playback-terminal.js').read_text(encoding='utf-8')
INDEX=(ROOT/'index.html').read_text(encoding='utf-8')
VERIFY=(ROOT/'VERIFY.sh').read_text(encoding='utf-8')
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()

def value(name):
    m=re.search(rf'const {re.escape(name)}=(\d+)',TERM)
    return int(m.group(1)) if m else -1

class V445RandomArchiveStress(unittest.TestCase):
    def test_release(self):
        self.assertEqual(VERSION,'4.4.5')
        self.assertIn('Sports Big Board — v4.4.5',INDEX)
        self.assertIn('random archive dates across 365 days',INDEX)
    def test_random_archive_policy_is_deliberately_broad(self):
        self.assertEqual(value('ARCHIVE_LOOKBACK_DAYS'),365)
        self.assertGreaterEqual(value('ARCHIVE_MIN_JUMP_DAYS'),45)
        self.assertGreaterEqual(value('LONG_DATE_JUMP_DAYS'),45)
        self.assertGreaterEqual(value('MIN_DATES'),10)
        self.assertGreaterEqual(value('MIN_DATE_CHANGES'),12)
        self.assertGreaterEqual(value('MIN_MONTHS'),6)
        self.assertGreaterEqual(value('MIN_DATE_SPAN_DAYS'),180)
        self.assertGreaterEqual(value('MIN_LONG_DATE_JUMPS'),8)
        self.assertIn('crypto?.getRandomValues',TERM)
        self.assertIn('randomArchiveTarget',TERM)
        self.assertIn('shouldRandomArchiveJump',TERM)
        self.assertIn('waitForRibbonCandidate',TERM)
        self.assertIn('Random archive date',TERM)
    def test_duplicate_candidates_are_rejected_not_misclassified_as_product_failure(self):
        for token in ('SPORT_IDS','cardMediaKey','scoreCardAvailability','playbackItemKey','preflightDuplicateSkips','duplicateCandidateRejects','rejectDuplicateStressCandidate','queueDuplicateCandidateReplacement','stressDriven'):
            self.assertIn(token,TERM)
        self.assertIn("if(row.stressDriven)return rejectDuplicateStressCandidate",TERM)
        self.assertIn('repeatViolations++',TERM)
    def test_report_freezes_to_endurance_run_and_exports_archive_metrics(self):
        self.assertIn("filter(r=>r.enduranceRunId===s.runId)",TERM)
        for token in ('DATE_SPAN=','LONG_JUMPS=','RANDOM_DATE_TRIES=','DUP_REJECTS=','PREFLIGHT_SKIPS='):
            self.assertIn(token,TERM)
    def test_verify_runs_v445_guards_and_manifest_gate(self):
        self.assertIn('python3 tools/check_release_manifest.py',VERIFY)
        self.assertIn('node tests/test_v445_duplicate_candidate_runtime.js',VERIFY)
        self.assertIn('unittest discover',VERIFY)

if __name__=='__main__': unittest.main()

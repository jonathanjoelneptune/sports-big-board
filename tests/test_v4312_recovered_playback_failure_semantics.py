import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CERT=(ROOT/'architecture'/'foundation-certification.js').read_text(encoding='utf-8')
class V4312RecoveredPlaybackFailureSemantics(unittest.TestCase):
    def test_only_proven_failover_is_non_blocking(self):
        for token in ('function recoveredPlaybackFailover','recoveredByFailover===true',"String(d.initialMedia||'')===failedMedia","String(d.recoveredMedia)!==failedMedia","String(d.to||d.state||'')==='playing'","stress?.restorationHealth?.ok!==true"):
            self.assertIn(token,CERT)
    def test_unrecovered_errors_remain_actionable(self):
        self.assertIn("else actionableErrors.push({...row,classification:'ACTIONABLE'})",CERT)
    def test_release_is_current(self):
        self.assertGreaterEqual(tuple(map(int,(ROOT/'VERSION').read_text().strip().split('.'))),(4,3,12))
if __name__=='__main__': unittest.main()

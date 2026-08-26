import time
import unittest
from pathlib import Path
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]

class V432ExtraInningTests(unittest.TestCase):
    def test_extra_inning_reconciler_is_loaded_before_game_center_view(self):
        html=(ROOT/'index.html').read_text(encoding='utf-8')
        helper='architecture/game-center-linescore.js?v=4.3.2'
        view='ui/game-center-view.js?v=4.3.2'
        self.assertIn(helper,html);self.assertIn(view,html)
        self.assertLess(html.index(helper),html.index(view))
        gc=(ROOT/'ui/game-center-view.js').read_text(encoding='utf-8')
        self.assertIn('SBB_GAME_CENTER_LINESCORE?.reconcile',gc)

    def test_extra_inning_reconciler_targets_only_extra_inning_deficit(self):
        js=(ROOT/'architecture/game-center-linescore.js').read_text(encoding='utf-8')
        for token in ("Number(last?.num||0)<=9","const missing=total-known","missing>0&&Number.isInteger(missing)"):
            self.assertIn(token,js)

class V432GameCenterRateLimitCircuitTests(unittest.TestCase):
    def test_429_opens_circuit_and_cancels_already_queued_background_work(self):
        from sbb.media_work_scheduler import MediaWorkScheduler, PRIORITY
        sched=MediaWorkScheduler(workers=1,name='v432-circuit-test')
        ran=[]
        def first():
            time.sleep(0.08)
            raise HTTPError('https://provider.invalid',429,'Too Many Requests',{'Retry-After':'60'},None)
        f1=sched.submit('game-center:MLS:::::one',PRIORITY['VISIBLE_SCORE'],first)
        f2=sched.submit('game-center:MLS:::::two',PRIORITY['VISIBLE_SCORE'],lambda:ran.append('two'))
        f3=sched.submit('game-center:MLS:::::three',PRIORITY['BACKGROUND_DISCOVERY'],lambda:ran.append('three'))
        with self.assertRaises(HTTPError): f1.result(timeout=2)
        limit=time.time()+2
        while time.time()<limit and not (f2.done() and f3.done()): time.sleep(0.01)
        self.assertTrue(f2.cancelled());self.assertTrue(f3.cancelled());self.assertEqual(ran,[])
        snap=sched.snapshot()
        self.assertGreaterEqual(snap['stats']['circuitRejected'],2)
        self.assertGreaterEqual(snap['stats']['circuitOpened'],1)
        self.assertGreaterEqual(snap['stats']['errorCategories'].get('rate-limit',0),1)
        self.assertIn('game-center:MLS',snap['circuits'])

    def test_touch_intent_can_bypass_background_circuit(self):
        from sbb.media_work_scheduler import MediaWorkScheduler, PRIORITY
        sched=MediaWorkScheduler(workers=1,name='v432-touch-test')
        def limited(): raise HTTPError('https://provider.invalid',429,'Too Many Requests',{'Retry-After':'60'},None)
        first=sched.submit('game-center:MLS:::::one',PRIORITY['VISIBLE_SCORE'],limited)
        with self.assertRaises(HTTPError): first.result(timeout=2)
        touch=sched.submit('game-center:MLS:::::touch',PRIORITY['TOUCH_INTENT'],lambda:'foreground-ok')
        self.assertEqual(touch.result(timeout=2),'foreground-ok')

class V432Tier3EvidenceTests(unittest.TestCase):
    def test_tier3_keeps_chaos_evidence_across_post_chaos_reset(self):
        milestone=(ROOT/'architecture/milestone-console.js').read_text(encoding='utf-8')
        cert=(ROOT/'architecture/foundation-certification.js').read_text(encoding='utf-8')
        for token in ("phaseRunSummaryLines('TIER 3 CHAOS',chaosRun)",'resetObservationWindow','provider rate-limit circuit remains bounded'):
            self.assertIn(token,milestone)
        self.assertIn('cleanBoundary({preserveRunEvidence:true})',cert)

if __name__=='__main__':unittest.main()

import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'app.js').read_text(encoding='utf-8')
READY=(ROOT/'architecture/playback-readiness.js').read_text(encoding='utf-8')

class V440HotStandbyContractTests(unittest.TestCase):
    def test_standby_requires_real_progress_not_canplay_only(self):
        self.assertIn('STANDBY_MIN_PROGRESS_SECONDS=0.45',APP)
        self.assertIn('nativeBufferedAhead(v)',APP)
        self.assertIn('noteHotStandbyReady',APP)
        self.assertNotIn("setTimeout(()=>{ if(!entry.settled && v.readyState>=3) finishPreparedNativeWarm(entry,true); },220)",APP)

    def test_bad_standby_is_rejected_offscreen_and_replaced(self):
        for token in ('standbyWarmFailed','standbyRejectedUntil','nextReadinessCandidateIndex','hot standby did not prove playback'):
            self.assertIn(token,APP)
        self.assertIn('if(slot===activeSlot||!slotClaimIsCurrent(slot,epoch,item))return false;',APP)

    def test_ab_promotion_requires_exact_hot_ready_claim(self):
        self.assertIn('!videoReady[newActive]||!claimBefore||claimBefore.key!==playbackItemKey(item)',APP)
        self.assertIn("reason:'A/B promotion lost hot-ready claim'",APP)
        self.assertIn('hotStandbyHitRate',APP)

    def test_queue_preflight_works_across_program_not_one_sport(self):
        block=APP[APP.index('function preflightUpcomingProgram'):APP.index('const HISTORICAL_RUNTIME_REPORTED')]
        self.assertIn('PROGRAM[idx]',block)
        self.assertIn('runtimeMediaUsable(item)',block)
        for league in ('MLB','NFL','NBA','NHL','EPL','MLS'):
            self.assertNotIn(f"competitionId==='{'%s'%league}'",block)

    def test_readiness_state_is_transport_and_competition_neutral(self):
        self.assertIn('competitionId',READY);self.assertIn('transport',READY);self.assertIn('provider',READY)
        self.assertNotIn("competitionId==='MLB'",READY)
        self.assertNotIn("league==='MLB'",READY)

    def test_canonical_session_preserves_provider_for_reliability_learning(self):
        session=(ROOT/'architecture/playback-session.js').read_text(encoding='utf-8')
        self.assertIn("provider:''",session)
        self.assertIn('provider:String(meta.provider||state.provider',session)
        self.assertIn('provider:s.provider',READY)
        self.assertNotIn('noteHotReady?.(item,0)',APP,'promotion must not double-count an already proven hot standby')

if __name__=='__main__': unittest.main()

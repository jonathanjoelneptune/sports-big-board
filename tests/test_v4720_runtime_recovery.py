import threading
import unittest
from unittest import mock

from sbb import day_state
from sbb import runtime_path_repair_v4720 as repair


class RejectingMatcherServer:
    def _history_media_match_evidence(self, item, event):
        return ({"mediaScope":"OTHER"},{"associationState":"QUARANTINED"})


class V4720RuntimeRecoveryTests(unittest.TestCase):
    def test_day_state_trusts_normalized_assigned_canonical_relationship(self):
        item={"assetKey":"yt:a","youtubeId":"abc123xyz","verifiedPlayable":True,
              "mediaScope":"GAME","canonicalEventKey":"MLB:401",
              "associationMethod":"TITLE_TEAM_PAIR"}
        plans={"MLB:401":{"league":"MLB","date":"2026-08-28",
                           "event":{"eventId":"401","competitionId":"MLB","date":"2026-08-28"},
                           "media":[dict(item)],"playable":[dict(item)]}}
        out,stats=day_state._sanitize_event_plans(RejectingMatcherServer(),plans)
        self.assertEqual(len(out["MLB:401"]["playable"]),1)
        self.assertGreaterEqual(stats["persistedAssignedAccepted"],2)
        self.assertEqual(stats["rejected"],0)

    def test_day_state_refresh_never_replaces_healthier_history_snapshot(self):
        before={"generatedAt":1,"summary":{"games":12,"playable":9}}
        after={"generatedAt":2,"summary":{"games":12,"playable":3}}
        class Store:
            def __init__(self): self.saved=[]
            def get(self,day): return before
            def put(self,row): self.saved.append(row)
        class Engine:
            def __init__(self):
                self.lock=threading.RLock();self.cache={};self.last_build={};self.store=Store();self.queued=[]
            def get(self,day,allow_build=True,force=False): return after
            def enqueue(self,day,priority=False): self.queued.append((day,priority));return True
        engine=Engine()
        with mock.patch.object(day_state,'_ENGINE',engine):
            repair._invalidate_day_state(['2026-08-28'])
        self.assertEqual(engine.store.saved[-1]['summary'],before['summary'])
        self.assertEqual(engine.store.saved[-1]['engineVersion'],'4.7.20')
        self.assertEqual(engine.cache['2026-08-28']['summary'],before['summary'])
        self.assertIn('v4720RegressionGuard',engine.cache['2026-08-28']['projectionDiagnostics'])

    def test_llws_recovery_replays_actual_special_event_owner(self):
        from sbb import special_event_media_v4616 as special
        server=type('Server',(),{})()
        repo=type('Repo',(),{})()
        server.HISTORY_REPOSITORY=repo
        repo.event_media=lambda day,league,eid,include_failed=False:[{"youtubeId":"llws123","verifiedPlayable":True}]
        comp={"id":"LLWS2026"}
        records=[{"date":"2026-08-25","eventId":"g1"}]
        stats={"sourceAssets":4,"associatedAssets":4,"gamesWithPlayableAssociatedMedia":1,"gamesWithoutPlayableAssociatedMedia":0}
        with mock.patch.object(special,'_ensure_llws_sources',return_value=comp), \
             mock.patch.object(special,'reassociate',return_value={"summary":{"persisted":4}}) as reassociate, \
             mock.patch.object(special,'durable_stats',return_value=stats), \
             mock.patch.object(special,'competition_records',return_value=records), \
             mock.patch.object(repair,'_invalidate_day_state',return_value=1) as refresh:
            result=repair._llws_owner_reassociate(server)
        self.assertTrue(result['ready'])
        reassociate.assert_called_once_with(server,comp)
        refresh.assert_called_once_with(['2026-08-25'])

    def test_runtime_source_contains_known_cfb_acceptance_media(self):
        self.assertIn('-tDiPDHU2fs',open(repair.__file__,encoding='utf-8').read())


if __name__=='__main__':
    unittest.main()

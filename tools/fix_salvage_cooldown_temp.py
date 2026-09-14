#!/usr/bin/env python3
from pathlib import Path
import re

root=Path(__file__).resolve().parents[1]
patcher=root/'tools'/'patch_media_repair_salvage_v6116.py'
service=root/'media_audit_service.py'
test=root/'tests'/'test_media_repair_salvage_v6116.py'

# Remove the provisional R21 seed-requeue transformation from the permanent
# patcher. Salvage should run first when a job is naturally due; deployment must
# not wake every cooling repair job and immediately fall through to discovery.
p=patcher.read_text(encoding='utf-8')
pattern=r"\n    old_seed = '''.*?    text = replace_once\(text, old_seed, new_seed, \"R21 strategy requeue\"\)\n"
p2,n=re.subn(pattern,'\n',p,count=1,flags=re.S)
if n not in (0,1): raise SystemExit('unexpected seed patch count')
patcher.write_text(p2,encoding='utf-8')

# Restore the already-patched source tree to the existing R20 one-time upgrade
# semantics. This preserves all current next_retry_at values for R20 jobs.
s=service.read_text(encoding='utf-8')
r21='''            # R21 puts known-media salvage ahead of scarce fresh discovery. Give each
            # actionable R20-era cooldown one immediate pass through the new lane,
            # then persist the R21 strategy marker so service restarts do not erase
            # cooldown policy or create an infinite strategy-requeue loop.
            cur=conn.execute(
                "UPDATE history_media_repair_queue SET state='PENDING',next_retry_at=0,updated_at=?,last_error='', reason='R21 known-candidate salvage strategy upgrade: immediate one-time retry' WHERE health IN ('DEGRADED','UNPLAYABLE','NO_MEDIA') AND state='WAITING_RETRY' AND COALESCE(details_json,'') NOT LIKE '%R21_KNOWN_CANDIDATE_SALVAGE%'",
                (now,),
            ); strategy_requeued=int(cur.rowcount or 0)
'''
r20='''            # R20 changes playback certification authority as well as the probe itself. Give every
            # R19-exhausted actionable job one immediate pass through the stabilized
            # probe and recent-PLAYED corroboration path. Once processed, details_json
            # carries the R20 marker so service restarts preserve cooldowns.
            cur=conn.execute(
                "UPDATE history_media_repair_queue SET state='PENDING',next_retry_at=0,updated_at=?,last_error='', reason='R20 playback-evidence corroboration strategy upgrade: immediate one-time retry' WHERE health IN ('DEGRADED','UNPLAYABLE','NO_MEDIA') AND state='WAITING_RETRY' AND COALESCE(details_json,'') NOT LIKE '%R20_PLAYBACK_EVIDENCE_CORROBORATION%'",
                (now,),
            ); strategy_requeued=int(cur.rowcount or 0)
'''
if r21 in s: s=s.replace(r21,r20,1)
service.write_text(s,encoding='utf-8')

# Update the regression to assert the safe rollout behavior.
t=test.read_text(encoding='utf-8')
t=t.replace("    \"R21 known-candidate salvage strategy upgrade: immediate one-time retry\",\n",'')
old='''# Existing cooldowns receive one immediate R21 pass, then marker prevents restart loops.
seed=service.split('    def seed_repair_queue(self):',1)[1].split('    def repair_liveness',1)[0]
assert "NOT LIKE '%R21_KNOWN_CANDIDATE_SALVAGE%'" in seed
assert "state='PENDING',next_retry_at=0" in seed
'''
new='''# R21 rollout must preserve existing cooldowns; only the older R20 migration may
# perform its one-time strategy requeue. R21 is picked up when each job is due.
seed=service.split('    def seed_repair_queue(self):',1)[1].split('    def repair_liveness',1)[0]
assert "NOT LIKE '%R21_KNOWN_CANDIDATE_SALVAGE%'" not in seed
assert "R20_PLAYBACK_EVIDENCE_CORROBORATION" in seed
assert 'R21_KNOWN_CANDIDATE_SALVAGE' in service.split('    def _repair_by_discovery(self, job):',1)[1]
'''
if old in t: t=t.replace(old,new,1)
test.write_text(t,encoding='utf-8')
print('PASS cooldown-safe salvage rollout correction')

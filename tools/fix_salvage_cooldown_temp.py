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
p,n=re.subn(pattern,'\n',p,count=1,flags=re.S)
if n not in (0,1): raise SystemExit('unexpected seed patch count')

# Persist refreshed transport into the source catalog before certification. A
# salvage probe that succeeds against a refreshed signed/direct URL must not
# promote a canonical asset whose DB row still points at stale transport.
if 'def refresh_repair_known_transport(self, event_key, assets):' not in p:
    anchor='    method_anchor = "    def _eligible_known_candidates(self, assets, target=\'ANY\', tested=None):\\n"\n'
    block=r'''    store_anchor = "    def record_repair_source_attempt(self, repair_id, event_key, stage, *, provider='', query='', result_count=0,"
    if 'def refresh_repair_known_transport(self, event_key, assets):' not in text:
        store_method = r'''    def refresh_repair_known_transport(self, event_key, assets):
        """Persist a fresh transport for an existing source identity.

        This never creates or re-associates media. It only refreshes browser-facing
        transport/metadata on an asset that already exists in history_source_media.
        Runtime evidence remains untouched until the independent playback probe runs.
        """
        now=_now(); updated=0
        with self.lock, closing(self.connect(timeout=2)) as conn:
            for asset in list(assets or []):
                key=str(asset.get('assetKey') or '')
                if not key: continue
                row=conn.execute("SELECT asset_json,canonical_url,provider,provider_media_id,title,duration_seconds FROM history_source_media WHERE asset_key=?",(key,)).fetchone()
                if not row: continue
                item=_jloads(row['asset_json'],{})
                incoming=asset.get('item') if isinstance(asset.get('item'),dict) else {}
                item.update(incoming)
                url=str(asset.get('url') or _asset_url(item,row['canonical_url']) or '')
                provider=str(asset.get('provider') or row['provider'] or '')
                media_id=str(asset.get('providerMediaId') or row['provider_media_id'] or '')
                title=str(asset.get('title') or row['title'] or '')
                duration=float(asset.get('durationSeconds') or row['duration_seconds'] or 0)
                if url:
                    item['url']=url; item['externalUrl']=url; item['mediaUrl']=url
                youtube_id=str(asset.get('youtubeId') or '')
                if youtube_id: item['youtubeId']=youtube_id
                if provider: item['provider']=provider
                if media_id: item['providerMediaId']=media_id
                if title: item['title']=title
                if duration: item['durationSeconds']=duration
                cur=conn.execute(
                    "UPDATE history_source_media SET provider=?,provider_media_id=?,canonical_url=?,title=?,duration_seconds=?,asset_json=?,last_seen_at=?,updated_at=? WHERE asset_key=?",
                    (provider,media_id,url,title,duration,_jdumps(item),now,now,key),
                )
                updated+=int(cur.rowcount or 0)
            conn.commit()
        return updated

'''
        if store_anchor not in text:
            raise SystemExit("ERROR: salvage transport persistence anchor missing")
        text=text.replace(store_anchor,store_method+store_anchor,1)

'''
    if anchor not in p: raise SystemExit('permanent patcher method anchor missing')
    p=p.replace(anchor,block+anchor,1)

p=p.replace('"salvageTransportRefreshes":0,"salvageTransportRecovered":0,',
            '"salvageTransportRefreshes":0,"salvageTransportRecovered":0,"salvageTransportPersisted":0,')
p=p.replace("                if before!=after: changed.append(key)\n",
            "                if before!=after:\n                    changed.append(key); asset['_salvageTransportRefreshed']=True\n")
needle="""        merged,transport=self._merge_salvage_transport(assets,list(plan.get('candidates') or []))
        self.stats['salvageTransportRefreshes']+=int(transport.get('transportChanged') or 0)
"""
replacement="""        merged,transport=self._merge_salvage_transport(assets,list(plan.get('candidates') or []))
        refreshed=[a for a in merged if a.get('_salvageTransportRefreshed')]
        if refreshed:
            persisted=self._write('persist salvage transport refresh','refresh_repair_known_transport',str(job['canonical_event_key']),refreshed,event_key=str(job['canonical_event_key']))
            transport['persisted']=int(persisted or 0)
            self.stats['salvageTransportPersisted']+=int(persisted or 0)
        self.stats['salvageTransportRefreshes']+=int(transport.get('transportChanged') or 0)
"""
if replacement not in p:
    if needle not in p: raise SystemExit('salvage transport call anchor missing in patcher')
    p=p.replace(needle,replacement,1)
patcher.write_text(p,encoding='utf-8')

# Restore the already-patched source tree to its prior migration semantics. This
# preserves current next_retry_at values for cooling repair jobs.
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

# The permanent patcher now carries the durable transport change; apply it to
# the current source tree so this exact branch is what gets source-tested.
import subprocess,sys
subprocess.run([sys.executable,str(patcher)],cwd=root,check=True)

# Tighten the regression around durable transport and safe rollout behavior.
t=test.read_text(encoding='utf-8')
t=t.replace("    \"R21 known-candidate salvage strategy upgrade: immediate one-time retry\",\n",'')
if "'def refresh_repair_known_transport(self, event_key, assets):'," not in t:
    t=t.replace("    'def _repair_plan_snapshot(self, job):',\n", "    'def refresh_repair_known_transport(self, event_key, assets):',\n    'def _repair_plan_snapshot(self, job):',\n")
if '"self.stats[\'salvageTransportPersisted\']"' not in t:
    t=t.replace("    \"self.stats['salvageTransportRecovered']\",\n", "    \"self.stats['salvageTransportRecovered']\",\n    \"self.stats['salvageTransportPersisted']\",\n")
extra='''\n# A refreshed transport must be durably written before the playback probe can
# promote that source into the canonical package.
store_refresh=service.split('    def refresh_repair_known_transport(self, event_key, assets):',1)[1].split('    def record_repair_source_attempt',1)[0]
assert 'UPDATE history_source_media SET provider=?' in store_refresh
assert "item['url']=url; item['externalUrl']=url; item['mediaUrl']=url" in store_refresh
salvage=service.split('    def _salvage_known_candidates(self, job, assets, target, tested):',1)[1].split('    def _eligible_known_candidates',1)[0]
assert salvage.index("persist salvage transport refresh") < salvage.index("_certify_candidates")
assert "refresh_repair_known_transport" in salvage
'''
if '# A refreshed transport must be durably written' not in t:
    t=t.replace("# Operator telemetry and overcomplete copy raw JSON will expose salvage yield.\n",extra+"\n# Operator telemetry and overcomplete copy raw JSON will expose salvage yield.\n")
test.write_text(t,encoding='utf-8')
print('PASS cooldown-safe + durable salvage transport correction')

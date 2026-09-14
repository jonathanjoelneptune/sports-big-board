#!/usr/bin/env python3
from pathlib import Path
import re
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
patcher=root/'tools'/'patch_media_repair_salvage_v6116.py'
service=root/'media_audit_service.py'
test=root/'tests'/'test_media_repair_salvage_v6116.py'

# R21 salvage runs first when a job is naturally due. It must not wake every
# cooling repair job just because the release was deployed.
p=patcher.read_text(encoding='utf-8')
pattern=r"\n    old_seed = '''.*?    text = replace_once\(text, old_seed, new_seed, \"R21 strategy requeue\"\)\n"
p,n=re.subn(pattern,'\n',p,count=1,flags=re.S)
if n not in (0,1):
    raise SystemExit('unexpected seed patch count')

# Teach the permanent patcher to install a durable transport write-back method.
# The method updates only an existing source row and leaves runtime evidence
# untouched until the independent browser probe runs.
if 'def refresh_repair_known_transport(self, event_key, assets):' not in p:
    anchor='    method_anchor = "    def _eligible_known_candidates(self, assets, target=\'ANY\', tested=None):\\n"\n'
    block="""    store_anchor = \"    def record_repair_source_attempt(self, repair_id, event_key, stage, *, provider='', query='', result_count=0,\"\n    if 'def refresh_repair_known_transport(self, event_key, assets):' not in text:\n        store_method = r'''    def refresh_repair_known_transport(self, event_key, assets):\n        # Persist fresh browser transport for an existing source identity only.\n        # Runtime success/failure evidence is intentionally unchanged here.\n        now=_now(); updated=0\n        with self.lock, closing(self.connect(timeout=2)) as conn:\n            for asset in list(assets or []):\n                key=str(asset.get('assetKey') or '')\n                if not key: continue\n                row=conn.execute(\"SELECT asset_json,canonical_url,provider,provider_media_id,title,duration_seconds FROM history_source_media WHERE asset_key=?\",(key,)).fetchone()\n                if not row: continue\n                item=_jloads(row['asset_json'],{})\n                incoming=asset.get('item') if isinstance(asset.get('item'),dict) else {}\n                item.update(incoming)\n                url=str(asset.get('url') or _asset_url(item,row['canonical_url']) or '')\n                provider=str(asset.get('provider') or row['provider'] or '')\n                media_id=str(asset.get('providerMediaId') or row['provider_media_id'] or '')\n                title=str(asset.get('title') or row['title'] or '')\n                duration=float(asset.get('durationSeconds') or row['duration_seconds'] or 0)\n                if url:\n                    item['url']=url; item['externalUrl']=url; item['mediaUrl']=url\n                youtube_id=str(asset.get('youtubeId') or '')\n                if youtube_id: item['youtubeId']=youtube_id\n                if provider: item['provider']=provider\n                if media_id: item['providerMediaId']=media_id\n                if title: item['title']=title\n                if duration: item['durationSeconds']=duration\n                cur=conn.execute(\n                    \"UPDATE history_source_media SET provider=?,provider_media_id=?,canonical_url=?,title=?,duration_seconds=?,asset_json=?,last_seen_at=?,updated_at=? WHERE asset_key=?\",\n                    (provider,media_id,url,title,duration,_jdumps(item),now,now,key),\n                )\n                updated+=int(cur.rowcount or 0)\n            conn.commit()\n        return updated\n\n'''\n        if store_anchor not in text:\n            raise SystemExit(\"ERROR: salvage transport persistence anchor missing\")\n        text=text.replace(store_anchor,store_method+store_anchor,1)\n\n"""
    if anchor not in p:
        raise SystemExit('permanent patcher method anchor missing')
    p=p.replace(anchor,block+anchor,1)

# Permanent stats + transport merge/persistence behavior.
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
    if needle not in p:
        raise SystemExit('salvage transport call anchor missing in patcher')
    p=p.replace(needle,replacement,1)
patcher.write_text(p,encoding='utf-8')

# Restore source seed behavior if an earlier provisional run changed it.
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
if r21 in s:
    service.write_text(s.replace(r21,r20,1),encoding='utf-8')

# Apply the now-final permanent patcher to this branch.
subprocess.run([sys.executable,str(patcher)],cwd=root,check=True)

# Tighten regression coverage for durable transport and cooldown safety.
t=test.read_text(encoding='utf-8')
t=t.replace("    \"R21 known-candidate salvage strategy upgrade: immediate one-time retry\",\n",'')
if "'def refresh_repair_known_transport(self, event_key, assets):'," not in t:
    t=t.replace("    'def _repair_plan_snapshot(self, job):',\n",
                "    'def refresh_repair_known_transport(self, event_key, assets):',\n    'def _repair_plan_snapshot(self, job):',\n")
if "\"self.stats['salvageTransportPersisted']\"," not in t:
    t=t.replace("    \"self.stats['salvageTransportRecovered']\",\n",
                "    \"self.stats['salvageTransportRecovered']\",\n    \"self.stats['salvageTransportPersisted']\",\n")
extra="""
# A refreshed transport must be durably written before the playback probe can
# promote that source into the canonical package.
store_refresh=service.split('    def refresh_repair_known_transport(self, event_key, assets):',1)[1].split('    def record_repair_source_attempt',1)[0]
assert 'UPDATE history_source_media SET provider=?' in store_refresh
assert "item['url']=url; item['externalUrl']=url; item['mediaUrl']=url" in store_refresh
salvage=service.split('    def _salvage_known_candidates(self, job, assets, target, tested):',1)[1].split('    def _eligible_known_candidates',1)[0]
assert salvage.index('persist salvage transport refresh') < salvage.index('_certify_candidates')
assert 'refresh_repair_known_transport' in salvage
"""
if '# A refreshed transport must be durably written' not in t:
    t=t.replace('# Operator telemetry and overcomplete copy raw JSON will expose salvage yield.\n',
                extra+'\n# Operator telemetry and overcomplete copy raw JSON will expose salvage yield.\n')
test.write_text(t,encoding='utf-8')
print('PASS cooldown-safe + durable salvage transport correction')

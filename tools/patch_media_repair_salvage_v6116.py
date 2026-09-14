#!/usr/bin/env python3
"""Apply the v6.1.16 Known Candidate Salvage / Revalidation lane.

The patch is intentionally idempotent because the v6.1.16 release materializer
replays historical Media Audit layers before restoring current release features.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "media_audit_service.py"
MATERIALIZER = ROOT / "tools" / "apply_v6116_release.py"
VERIFY = ROOT / "VERIFY.sh"
UI = ROOT / "ui" / "media-audit-v550.js"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"ERROR: {label} anchor missing")
    return text.replace(old, new, 1)


def patch_service() -> bool:
    text = SERVICE.read_text(encoding="utf-8")
    original = text

    text = replace_once(
        text,
        'REPAIR_KNOWN_CANDIDATE_LIMIT = max(1, min(10, int(os.environ.get("SBB_MEDIA_REPAIR_KNOWN_CANDIDATE_LIMIT", "3"))))\n',
        'REPAIR_KNOWN_CANDIDATE_LIMIT = max(1, min(10, int(os.environ.get("SBB_MEDIA_REPAIR_KNOWN_CANDIDATE_LIMIT", "3"))))\n'
        'REPAIR_SALVAGE_CANDIDATE_LIMIT = max(REPAIR_KNOWN_CANDIDATE_LIMIT, min(20, int(os.environ.get("SBB_MEDIA_REPAIR_SALVAGE_LIMIT", "8"))))\n'
        'REPAIR_SALVAGE_STALE_SECONDS = max(900, int(os.environ.get("SBB_MEDIA_REPAIR_SALVAGE_STALE_SECONDS", str(6 * 3600))))\n',
        "salvage constants",
    )

    old_stats = '                    "knownCandidatesEligible":0,"knownTransportRefreshes":0,\n                    "localCatalogCandidates":0,"registeredProviderNew":0,"youtubeIndexCandidates":0,'
    new_stats = '                    "knownCandidatesEligible":0,"knownTransportRefreshes":0,\n                    "salvageCandidatesConsidered":0,"salvageCandidatesSelected":0,"salvageCertified":0,\n                    "salvagePromotions":0,"salvageClosedHealthy":0,"salvageTransportRefreshes":0,"salvageTransportRecovered":0,\n                    "salvageHardRejected":0,"salvageTransportMissing":0,"salvageTargetSkipped":0,\n                    "localCatalogCandidates":0,"registeredProviderNew":0,"youtubeIndexCandidates":0,'
    text = replace_once(text, old_stats, new_stats, "salvage stats")


    method_anchor = "    def _eligible_known_candidates(self, assets, target='ANY', tested=None):\n"
    if 'def _salvage_known_candidates(' not in text:
        methods = r'''    def _repair_plan_snapshot(self, job):
        """Read current production media without invoking fresh discovery."""
        context=self.store.repair_event_context(job['canonical_event_key'])
        if not context:
            return {"ok":False,"plan":{},"reason":"EVENT_NOT_FOUND","candidates":[]}
        league=str(context.get('league') or '').upper()
        query=urlencode({'date':context.get('event_date') or '', 'league':league, 'eventId':context.get('event_id') or ''})
        req=Request(MAIN_API+'/api/history/event/media?'+query,headers={"User-Agent":f"SportsBigBoard-MediaRepair/{APP_VERSION}-{AUDIT_GENERATION}"})
        try:
            with urlopen(req,timeout=min(15,DISCOVERY_HTTP_TIMEOUT_SECONDS)) as resp:
                payload=json.loads(resp.read().decode('utf-8'))
            plan=payload.get('plan') if isinstance(payload,dict) else {}
            rows=[]; seen=set()
            for raw in list((plan or {}).get('media') or [])+list((plan or {}).get('playable') or []):
                candidate=CanonicalAuditWorker._plan_candidate(raw)
                if not candidate: continue
                identity=(str(candidate.get('assetKey') or ''),str(candidate.get('provider') or ''),str(candidate.get('providerMediaId') or ''))
                if identity in seen: continue
                seen.add(identity); rows.append(candidate)
            return {"ok":bool(payload.get('ok',True)),"plan":plan or {},"reason":str(payload.get('error') or ''),"candidates":rows}
        except HTTPError as exc:
            try: payload=json.loads(exc.read().decode('utf-8'))
            except Exception: payload={}
            raw=str(payload.get('error') or f'HTTP_{exc.code}')
            if raw in {'BAD_HISTORY_EVENT','HISTORY_EVENT_NOT_FOUND'} and _special_event_league(league):
                raw='ENDPOINT_UNSUPPORTED_SPECIAL_EVENT'
            return {"ok":False,"plan":{},"reason":raw,"candidates":[]}
        except Exception as exc:
            return {"ok":False,"plan":{},"reason":f'PRODUCTION_PLAN_TRANSPORT_{type(exc).__name__.upper()}',"message":str(exc),"candidates":[]}

    @staticmethod
    def _salvage_identity(asset):
        provider=_search_norm((asset or {}).get('provider') or '')
        media_id=str((asset or {}).get('providerMediaId') or '').strip()
        return (provider,media_id) if provider and media_id else None

    def _merge_salvage_transport(self, known_assets, plan_assets):
        """Overlay fresh browser transport onto known identity without adding media."""
        by_key={str(a.get('assetKey') or ''):a for a in plan_assets if a.get('assetKey')}
        by_identity={self._salvage_identity(a):a for a in plan_assets if self._salvage_identity(a)}
        merged=[]; changed=[]; recovered=[]; matched=0
        for original in list(known_assets or []):
            asset=dict(original); key=str(asset.get('assetKey') or '')
            fresh=by_key.get(key)
            if fresh is None:
                ident=self._salvage_identity(asset)
                fresh=by_identity.get(ident) if ident else None
            if fresh:
                matched+=1
                before=self._repair_transport_signature(asset)
                had_transport=bool(asset.get('url') or asset.get('youtubeId'))
                for field in ('url','youtubeId','provider','providerMediaId','title','tier','durationSeconds','validationState'):
                    value=fresh.get(field)
                    if value not in (None,'',0): asset[field]=value
                if isinstance(fresh.get('item'),dict):
                    combined=dict(asset.get('item') or {}); combined.update(fresh.get('item') or {}); asset['item']=combined
                after=self._repair_transport_signature(asset)
                if before!=after: changed.append(key)
                if not had_transport and bool(asset.get('url') or asset.get('youtubeId')): recovered.append(key)
            merged.append(asset)
        return merged,{"planCandidates":len(plan_assets),"matched":matched,"transportChanged":len(changed),"transportRecovered":len(recovered),"changedKeys":changed[:20],"recoveredKeys":recovered[:20]}

    def _salvage_classification(self, asset, now=None):
        now=_now() if now is None else float(now)
        runtime=str(asset.get('runtimeState') or '').upper()
        assoc=str(asset.get('associationState') or '').upper()
        failure=str(asset.get('runtimeFailureReason') or '')
        failure_at=float(asset.get('runtimeFailureAt') or 0)
        success_at=float(asset.get('runtimeSuccessAt') or 0)
        if runtime=='PLAYED' and success_at>0:
            return ('RECENT_PLAYED' if success_at>=now-PLAYABLE_EVIDENCE_FRESH_SECONDS else 'STALE_PLAYED',600)
        if runtime=='FAILED':
            if _transient_media_failure_reason(failure): return ('TRANSIENT_FAILURE',560)
            if _infra_failure_reason(failure): return ('INFRA_FAILURE',550)
            if not failure_at or failure_at<=now-REPAIR_SALVAGE_STALE_SECONDS: return ('STALE_NONHARD_FAILURE',500)
            return ('NONHARD_FAILURE',450)
        if runtime in {'','UNKNOWN','UNTESTED','UNVERIFIED','ASSIGNED','INCONCLUSIVE'}:
            return ('UNVERIFIED_KNOWN',520)
        if assoc=='QUARANTINED': return ('NONHARD_QUARANTINE',480)
        return ('KNOWN_REVALIDATION',400)

    def _salvage_known_candidates(self, job, assets, target, tested):
        """Revalidate known media before spending fresh-discovery budget."""
        plan=self._repair_plan_snapshot(job)
        merged,transport=self._merge_salvage_transport(assets,list(plan.get('candidates') or []))
        self.stats['salvageTransportRefreshes']+=int(transport.get('transportChanged') or 0)
        self.stats['salvageTransportRecovered']+=int(transport.get('transportRecovered') or 0)
        self.stats['knownTransportRefreshes']+=int(transport.get('transportChanged') or 0)
        self._record_stage(job,'KNOWN_TRANSPORT_REFRESH',provider='PRODUCTION_PLAYBACK_PLAN',
                           results=int(transport.get('planCandidates') or 0),new=0,duplicates=int(transport.get('matched') or 0),
                           rejected=max(0,int(transport.get('planCandidates') or 0)-int(transport.get('matched') or 0)),
                           details={**transport,'ok':bool(plan.get('ok')),'reason':str(plan.get('reason') or '')})

        target=str(target or 'ANY').upper(); now=_now(); ranked=[]
        counts={}; hard=0; missing=0; target_skipped=0; already_tested=0
        for asset in merged:
            key=str(asset.get('assetKey') or '')
            if not key: continue
            if key in tested:
                already_tested+=1; continue
            tier=str(asset.get('tier') or 'blue').lower()
            if target=='PREFERRED' and tier not in {'green','extended'}:
                target_skipped+=1; continue
            failure=str(asset.get('runtimeFailureReason') or '')
            runtime=str(asset.get('runtimeState') or '').upper()
            assoc=str(asset.get('associationState') or '').upper()
            if (runtime=='FAILED' or assoc=='QUARANTINED') and _hard_media_failure_reason(failure):
                hard+=1; continue
            if not str(asset.get('url') or '') and not str(asset.get('youtubeId') or ''):
                missing+=1; continue
            label,bonus=self._salvage_classification(asset,now)
            counts[label]=counts.get(label,0)+1
            ranked.append((bonus+self._candidate_score(asset,target),asset))
        ranked.sort(key=lambda row:(-row[0],str(row[1].get('assetKey') or '')))
        candidates=[asset for _,asset in ranked[:REPAIR_SALVAGE_CANDIDATE_LIMIT]]
        self.stats['salvageCandidatesConsidered']+=len(merged)
        self.stats['salvageCandidatesSelected']+=len(candidates)
        self.stats['salvageHardRejected']+=hard
        self.stats['salvageTransportMissing']+=missing
        self.stats['salvageTargetSkipped']+=target_skipped
        self.stats['knownCandidatesEligible']+=len(candidates)
        self._record_stage(job,'KNOWN_CANDIDATE_SALVAGE',provider='EVENT_CATALOG',results=len(merged),new=0,duplicates=len(merged),
                           rejected=hard+missing+target_skipped,eligible_known=len(candidates),
                           details={"classification":counts,"selected":len(candidates),"limit":REPAIR_SALVAGE_CANDIDATE_LIMIT,
                                    "hardRejected":hard,"transportMissing":missing,"targetSkipped":target_skipped,"alreadyTested":already_tested,
                                    "productionPlanOk":bool(plan.get('ok')),"productionPlanReason":str(plan.get('reason') or ''),**transport})
        if not candidates:
            return None,merged
        before_cert=int(self.stats.get('candidatesCertified') or 0)
        promoted=self._certify_candidates(job,candidates,target,'R21 known-candidate salvage/revalidation',tested=tested,phase='SALVAGE_KNOWN_CANDIDATE')
        certified=max(0,int(self.stats.get('candidatesCertified') or 0)-before_cert)
        self.stats['salvageCertified']+=certified
        if promoted:
            self.stats['salvagePromotions']+=1
            if str(promoted.get('health') or '').upper()=='HEALTHY': self.stats['salvageClosedHealthy']+=1
            self._trace('INFO','Known Candidate Salvage promoted media before fresh discovery',event=job['canonical_event_key'],
                        health=promoted.get('health'),assetKey=promoted.get('assetKey'),tier=promoted.get('tier'),certified=certified)
        return promoted,merged

'''
        if method_anchor not in text:
            raise SystemExit("ERROR: salvage method insertion anchor missing")
        text = text.replace(method_anchor, methods + method_anchor, 1)

    old_initial = '''        # R19 Stage -1: known is not duplicate. Recertify the best already-associated
        # media first, especially Green/Purple for DEGRADED -> PREFERRED. This is
        # bounded and excludes only definitive hard failures or unusable transport.
        known_candidates,known_meta=self._eligible_known_candidates(before,target,tested)
        self.stats['knownCandidatesEligible']+=len(known_candidates)
        self._record_stage(job,'KNOWN_CANDIDATES',provider='EVENT_CATALOG',results=len(before),new=0,duplicates=len(before),
                           rejected=int(known_meta.get('hardRejected') or 0)+int(known_meta.get('transportMissing') or 0),
                           eligible_known=len(known_candidates),details=known_meta)
        if known_candidates:
            promoted=self._certify_candidates(job,known_candidates,target,'R20 known-candidate recertification',tested=tested,phase='RECERTIFY_KNOWN_CANDIDATE')
            if promoted and promoted.get('health')=='HEALTHY': return promoted
            if promoted: fallback=promoted; target='PREFERRED'
'''
    new_initial = '''        # R21 Stage -2/-1: salvage known media before any fresh discovery. Refresh
        # browser-facing transport from the production playback plan, then independently
        # revalidate stale/transient/unverified known candidates. Hard failures remain final.
        promoted,before=self._salvage_known_candidates(job,before,target,tested)
        known={str(a.get('assetKey') or '') for a in before if a.get('assetKey')}
        transport_before={str(a.get('assetKey') or ''):self._repair_transport_signature(a) for a in before if a.get('assetKey')}
        if promoted and promoted.get('health')=='HEALTHY': return promoted
        if promoted: fallback=promoted; target='PREFERRED'
'''
    text = replace_once(text, old_initial, new_initial, "initial known candidate lane")

    old_start = '''        before=self.store.repair_event_assets(event_key); known={str(a.get('assetKey') or '') for a in before if a.get('assetKey')}
        tested=set(); transport_before={str(a.get('assetKey') or ''):self._repair_transport_signature(a) for a in before if a.get('assetKey')}
        self._write('repair staged search phase','update_repair_job',int(job['id']),state='SEARCHING',before_asset_count=len(before),
                    details={"strategy":"R20_PLAYBACK_EVIDENCE_CORROBORATION","knownAssets":len(before),"target":target},event_key=event_key)
'''
    new_start = '''        before=self.store.repair_event_assets(event_key); known={str(a.get('assetKey') or '') for a in before if a.get('assetKey')}
        tested=set(); transport_before={str(a.get('assetKey') or ''):self._repair_transport_signature(a) for a in before if a.get('assetKey')}
        self._write('repair staged search phase','update_repair_job',int(job['id']),state='SEARCHING',before_asset_count=len(before),
                    details={"strategy":"R21_KNOWN_CANDIDATE_SALVAGE","knownAssets":len(before),"target":target},event_key=event_key)
'''
    text = replace_once(text, old_start, new_start, "R21 strategy marker")

    text = text.replace(
        "reason='R19 known-candidate recovery + media-repair transport ladder exhausted without a certified candidate'",
        "reason='R21 known-candidate salvage + media-repair transport ladder exhausted without a certified candidate'",
        1,
    )

    if text != original:
        SERVICE.write_text(text, encoding="utf-8")
        return True
    return False


def patch_ui() -> bool:
    if not UI.is_file(): return False
    text = UI.read_text(encoding="utf-8")
    old = "${fmtNum(rs.knownTransportRefreshes||0)} transport refreshes • ${fmtNum(rs.youtubeIndexedVideos||0)} YT indexed"
    new = "${fmtNum(rs.knownTransportRefreshes||0)} transport refreshes • ${fmtNum(rs.salvageCandidatesSelected||0)} salvage selected • ${fmtNum(rs.salvageCertified||0)} salvage certified • ${fmtNum(rs.salvageClosedHealthy||0)} salvage closed • ${fmtNum(rs.youtubeIndexedVideos||0)} YT indexed"
    if new in text: return False
    if old not in text: raise SystemExit("ERROR: Media Audit repair telemetry anchor missing")
    UI.write_text(text.replace(old,new,1),encoding="utf-8")
    return True


def patch_materializer() -> bool:
    text = MATERIALIZER.read_text(encoding="utf-8"); original=text
    preserve_anchor = '    "tests/test_v6116_storage_retention_release.py",\n'
    additions = '    "tools/patch_media_repair_salvage_v6116.py",\n    "tests/test_media_repair_salvage_v6116.py",\n'
    if '"tools/patch_media_repair_salvage_v6116.py"' not in text:
        if preserve_anchor not in text: raise SystemExit("ERROR: v6.1.16 PRESERVE anchor missing")
        text=text.replace(preserve_anchor,preserve_anchor+additions,1)
    call='    subprocess.run([sys.executable, str(root / "tools" / "patch_media_repair_salvage_v6116.py")], cwd=root, check=True)\n'
    if call not in text:
        anchor='    patch_media_audit_copy(root)\n'
        if anchor not in text: raise SystemExit("ERROR: v6.1.16 post-base Media Audit anchor missing")
        text=text.replace(anchor,anchor+call,1)
    if text!=original:
        MATERIALIZER.write_text(text,encoding="utf-8"); return True
    return False


def patch_verify() -> bool:
    text=VERIFY.read_text(encoding="utf-8"); original=text; additions=[]
    if 'tests/test_media_repair_salvage_v6116.py' not in text: additions.append('python3 tests/test_media_repair_salvage_v6116.py')
    if 'tools/patch_media_repair_salvage_v6116.py' not in text: additions.append('python3 -m py_compile tools/patch_media_repair_salvage_v6116.py')
    if additions:
        anchor='python3 tools/check_release_version.py'; block='\n'.join(additions)
        text=text.replace(anchor,anchor+'\n'+block,1) if anchor in text else text.rstrip()+'\n'+block+'\n'
    if text!=original:
        VERIFY.write_text(text,encoding="utf-8"); return True
    return False


def main():
    changed=[]
    if patch_service(): changed.append('media_audit_service.py')
    if patch_ui(): changed.append('ui/media-audit-v550.js')
    if patch_materializer(): changed.append('tools/apply_v6116_release.py')
    if patch_verify(): changed.append('VERIFY.sh')
    print('v6.1.16 Known Candidate Salvage patch complete')
    print('changed='+','.join(changed) if changed else 'changed=none')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

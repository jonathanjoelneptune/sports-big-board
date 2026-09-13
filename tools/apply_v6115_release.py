#!/usr/bin/env python3
"""Sports Big Board v6.1.15 persistent team-resolution control loop materializer."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE = "6.1.14"
NEW = "6.1.15"
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".sh", ".yml", ".yaml"}
ACTIVE_DIRS = ("ui", "architecture", "sbb", "tests", "cloud", ".github")


def active_files(root):
    seen=set()
    for p in sorted(root.iterdir()):
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:
            seen.add(p); yield p
    checker=root/"tools"/"check_release_version.py"
    if checker.is_file() and checker not in seen:
        seen.add(checker); yield checker
    for dirname in ACTIVE_DIRS:
        base=root/dirname
        if not base.is_dir(): continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES: continue
            rel=p.relative_to(root)
            if any(part.startswith("sports-big-board-v") for part in rel.parts): continue
            if p not in seen: seen.add(p); yield p


def run_base(root):
    (root/"VERSION").write_text(BASE+"\n",encoding="utf-8")
    arch=root/"architecture"/"VERSION"; arch.parent.mkdir(parents=True,exist_ok=True); arch.write_text(BASE+"\n",encoding="utf-8")
    subprocess.run([sys.executable,str(root/"tools"/"apply_v6114_release.py"),"--skip-check"],cwd=root,check=True)


def replace_once(text, old, new, label):
    if old in text: return text.replace(old,new,1)
    if new in text: return text
    raise SystemExit(f"ERROR: v6.1.15 patch anchor missing: {label}")


def patch_media_audit(root):
    path=root/"media_audit_service.py"; text=path.read_text(encoding="utf-8")
    text=replace_once(text,
        "from sbb.media_team_sources_v6114 import TeamSourceRegistry\n",
        "from sbb.media_team_sources_v6115 import TeamSourceRegistry\n",
        "R24 registry import")

    seed_cfg='REPAIR_SEED_SECONDS = max(60.0, float(os.environ.get("SBB_MEDIA_REPAIR_SEED_SECONDS", "300")))\n'
    cfg=seed_cfg+'''TEAM_RESOLUTION_TICK_SECONDS = max(15.0, float(os.environ.get("SBB_MEDIA_TEAM_RESOLUTION_TICK_SECONDS", "60")))
TEAM_RESOLUTION_BATCH = max(1, min(10, int(os.environ.get("SBB_MEDIA_TEAM_RESOLUTION_BATCH", "2"))))
'''
    text=replace_once(text,seed_cfg,cfg,"team resolution cadence")

    store_anchor='    def repair_summary(self):\n'
    store_method='''    def requeue_repairs_for_team(self, league, team_name, source_status="", reason=""):
        """Immediately wake WAITING_RETRY games when a team's official source graph improves."""
        if not self.ensure_repair_schema():
            return {"requeued":0,"team":str(team_name or "")}
        def clean(value):
            value=_search_norm(value)
            value=re.sub(r"^\\d+\\s+", "", value).strip()
            return value
        needle=clean(team_name)
        if not needle:
            return {"requeued":0,"team":str(team_name or "")}
        now=_now(); matched=[]
        with self.lock, closing(self.connect(timeout=2)) as conn:
            rows=conn.execute(
                "SELECT id,game FROM history_media_repair_queue WHERE league=? AND state='WAITING_RETRY' ORDER BY priority DESC,updated_at ASC",
                (str(league or "").upper(),),
            ).fetchall()
            for row in rows:
                game=str(row['game'] or '')
                sides=re.split(r"\\s+@\\s+|\\s+vs\\.?\\s+",game,maxsplit=1,flags=re.I)
                if not any(clean(side)==needle for side in sides):
                    continue
                matched.append(int(row['id']))
            note=(f"Team source upgraded to {source_status or 'RESOLVED'} for {team_name}; {reason or 'official source graph improved'}")[:1000]
            for repair_id in matched:
                conn.execute("""UPDATE history_media_repair_queue SET state='PENDING',next_retry_at=0,updated_at=?,
                                  last_error='',reason=? WHERE id=? AND state='WAITING_RETRY'""",
                             (now,note,repair_id))
            conn.commit()
        return {"requeued":len(matched),"team":str(team_name or ""),"status":str(source_status or "")}

'''
    if "def requeue_repairs_for_team(" not in text:
        if store_anchor not in text: raise SystemExit("ERROR: repair_summary anchor missing")
        text=text.replace(store_anchor,store_method+store_anchor,1)

    stats_anchor='"teamDirectoryFetches":0,"teamDirectoryCacheHits":0,"teamDirectoryErrors":0,"teamLeaguePagesResolved":0,"teamOfficialSitesResolved":0}'
    stats_new='"teamDirectoryFetches":0,"teamDirectoryCacheHits":0,"teamDirectoryErrors":0,"teamLeaguePagesResolved":0,"teamOfficialSitesResolved":0,"teamResolutionQueueAttempts":0,"teamResolutionUpgrades":0,"teamResolutionRequeues":0,"teamUnresolvedObserved":0}'
    text=replace_once(text,stats_anchor,stats_new,"R24 Repair telemetry counters")

    text=replace_once(text,
        '        self.last_youtube_index_refresh_at=0.0\n',
        '        self.last_youtube_index_refresh_at=0.0\n        self.last_team_resolution_at=0.0\n',
        "team resolution timer")

    registry_old='        self.team_sources=TeamSourceRegistry(store,STATE_DIR/"cache"/"media-team-sources.sqlite",user_agent=f"SportsBigBoard-TeamSources/{APP_VERSION}-{AUDIT_GENERATION}")\n'
    registry_new='        self.team_sources=TeamSourceRegistry(store,STATE_DIR/"cache"/"media-team-sources.sqlite",user_agent=f"SportsBigBoard-TeamSources/{APP_VERSION}-{AUDIT_GENERATION}",on_team_resolved=self._on_team_source_resolved)\n'
    text=replace_once(text,registry_old,registry_new,"team resolution callback wiring")

    callback_anchor='    def _youtube_fallback_candidates(self, job):\n'
    callback='''    def _on_team_source_resolved(self, entity, resolution):
        result=self._write(
            'requeue repairs for upgraded official team source','requeue_repairs_for_team',
            str(entity.get('league') or ''),str(entity.get('teamName') or ''),
            str(resolution.get('status') or ''),str(resolution.get('reason') or ''),event_key='')
        count=int((result or {}).get('requeued') or 0)
        self.stats['teamResolutionUpgrades']+=1
        self.stats['teamResolutionRequeues']+=count
        self._trace('INFO','Official team source upgraded; waiting repair jobs requeued',
                    team=entity.get('teamName') or '',league=entity.get('league') or '',
                    previousStatus=resolution.get('previousStatus') or '',status=resolution.get('status') or '',requeued=count)
        try: STATUS_CACHE.request_refresh()
        except Exception: pass
        return count

'''
    if "def _on_team_source_resolved(" not in text:
        if callback_anchor not in text: raise SystemExit("ERROR: YouTube fallback anchor missing")
        text=text.replace(callback_anchor,callback+callback_anchor,1)

    accum_anchor="""        self.stats['teamOfficialSitesResolved']+=int(team_refresh.get('officialSites') or 0)
        self._record_stage(
"""
    accum_new="""        self.stats['teamOfficialSitesResolved']+=int(team_refresh.get('officialSites') or 0)
        self.stats['teamResolutionUpgrades']+=int(team_refresh.get('resolutionUpgrades') or 0)
        self.stats['teamResolutionRequeues']+=int(team_refresh.get('repairJobsRequeued') or 0)
        self.stats['teamUnresolvedObserved']+=int(team_refresh.get('unresolvedTeams') or 0)
        self._record_stage(
"""
    text=replace_once(text,accum_anchor,accum_new,"R24 team resolution telemetry accumulation")

    claim_anchor="                job=self._write('claim next repair job','claim_repair_job')\n"
    resolver="""                if self.seed_owner and _now()-self.last_team_resolution_at>=TEAM_RESOLUTION_TICK_SECONDS:
                    self.last_team_resolution_at=_now()
                    try:
                        with REPAIR_EXTERNAL_SEMAPHORE:
                            resolution_pass=self.team_sources.resolve_due(
                                self.youtube,get_secret('YOUTUBE_API_KEY',APP_ROOT),limit=TEAM_RESOLUTION_BATCH,stop_event=self.stop_event)
                        attempted=int(resolution_pass.get('attempted') or 0)
                        self.stats['teamResolutionQueueAttempts']+=attempted
                        self.stats['teamResolutionRequeues']+=int(resolution_pass.get('repairJobsRequeued') or 0)
                        if attempted:
                            self._trace('INFO','Persistent unresolved-team queue processed',**resolution_pass)
                    except Exception as exc:
                        self._trace('WARN','Persistent unresolved-team resolver failed safely',error=f'{type(exc).__name__}: {exc}')
                job=self._write('claim next repair job','claim_repair_job')
"""
    text=replace_once(text,claim_anchor,resolver,"background unresolved-team queue")

    text=text.replace("R23_TEAM_DIRECTORY_RESOLUTION","R24_TEAM_RESOLUTION_CONTROL_LOOP")
    text=text.replace("R23-CONTINUOUS-TEAM-DIRECTORY","R24-CONTINUOUS-TEAM-RESOLUTION")
    text=text.replace("R23 authoritative team-directory registry","R24 persistent team-resolution control loop")
    text=text.replace("R23 known/provider/team-directory/media-repair ladder exhausted without a certified candidate",
                      "R24 known/provider/team-resolution/media-repair ladder exhausted without a certified candidate")
    path.write_text(text,encoding="utf-8")


def patch_ui(root):
    html=root/"media-audit.html"; text=html.read_text(encoding="utf-8")
    anchor='            <div class="wide"><dt>Source telemetry</dt><dd id="repairSourceStats">—</dd></div>\n'
    rows='''            <div class="wide"><dt>Team source registry</dt><dd id="repairTeamSources">—</dd></div>
            <div class="wide"><dt>Team resolution queue</dt><dd id="repairTeamResolution">—</dd></div>
            <div class="wide"><dt>Team resolution states</dt><dd id="repairTeamStates">—</dd></div>
'''
    if 'id="repairTeamSources"' not in text:
        if anchor not in text: raise SystemExit("ERROR: Media Audit Repair telemetry UI anchor missing")
        text=text.replace(anchor,rows+anchor,1); html.write_text(text,encoding="utf-8")

    js=root/"ui"/"media-audit-v550.js"; text=js.read_text(encoding="utf-8")
    anchor_js="  setText('repairResult',`${rc.provider||'—'} • ${rc.lastResult||rw.lastError||'—'}`);\n"
    block=anchor_js+"""  const ts=rw.teamSources||{},tstates=ts.resolutionStates||{};
  setText('repairTeamSources',`${fmtNum(ts.resolvedTeams||0)} resolved • ${fmtNum(ts.leagueTeamPages||0)} league pages • ${fmtNum(ts.leagueReferredOfficialSites||0)} official sites • ${fmtNum(ts.youtubeChannels||0)} YT channels • ${fmtNum(ts.indexedVideos||0)} videos indexed`);
  setText('repairTeamResolution',`${fmtNum(ts.unresolvedTeams||0)} unresolved • ${fmtNum(ts.dueUnresolvedTeams||0)} due • ${fmtNum(ts.waitingUnresolvedTeams||0)} cooling down • ${fmtNum(ts.repairJobsRequeuedByResolution||0)} repair jobs requeued`);
  setText('repairTeamStates',Object.keys(tstates).sort().map(k=>`${k.replaceAll('_',' ')} ${fmtNum(tstates[k])}`).join(' • ')||'No team identities encountered yet');
"""
    text=replace_once(text,anchor_js,block,"Media Audit team-resolution renderer")
    js.write_text(text,encoding="utf-8")


def patch_legacy_contracts(root):
    replacements=(("R23-CONTINUOUS-TEAM-DIRECTORY","R24-CONTINUOUS-TEAM-RESOLUTION"),
                  ("R23_TEAM_DIRECTORY_RESOLUTION","R24_TEAM_RESOLUTION_CONTROL_LOOP"))
    for rel in ("tests/test_v617_continuous_media_audit_release.py","tests/test_v550_media_health_audit.py",
                "tests/test_v616_continuous_media_audit.py","tests/test_v6112_team_source_release.py",
                "tests/test_v6113_team_directory_release.py","tests/test_v6114_team_directory_hardening_release.py"):
        path=root/rel
        if not path.is_file(): continue
        text=path.read_text(encoding="utf-8"); rendered=text
        for old,new in replacements: rendered=rendered.replace(old,new)
        rendered=rendered.replace("from sbb.media_team_sources_v6114 import TeamSourceRegistry",
                                  "from sbb.media_team_sources_v6115 import TeamSourceRegistry")
        if rendered!=text: path.write_text(rendered,encoding="utf-8")


def patch_verify(root):
    path=root/"VERIFY.sh"; text=path.read_text(encoding="utf-8"); marker="python3 tools/check_release_version.py"
    commands=("python3 -m py_compile sbb/media_team_sources_v6115.py",
              "python3 tests/test_v6115_team_resolution_queue.py",
              "python3 tests/test_v6115_team_resolution_release.py")
    if marker not in text: raise SystemExit("ERROR: VERIFY release checker anchor missing")
    additions=[cmd for cmd in commands if cmd not in text]
    if additions: text=text.replace(marker,marker+"\n"+"\n".join(additions),1); path.write_text(text,encoding="utf-8")


def promote(root):
    for p in active_files(root):
        try: source=p.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        rendered=source.replace(BASE,NEW)
        if rendered!=source: p.write_text(rendered,encoding="utf-8")
    for p in (root/"VERSION",root/"architecture"/"VERSION"):
        p.parent.mkdir(parents=True,exist_ok=True); p.write_text(NEW+"\n",encoding="utf-8")


def controller(root):
    src=root/f"CONTROLLER-REGION-MAP-v{BASE}.md"; dst=root/f"CONTROLLER-REGION-MAP-v{NEW}.md"
    if not src.is_file(): raise SystemExit(f"ERROR: missing {src.name}")
    dst.write_text(src.read_text(encoding="utf-8").replace(BASE,NEW),encoding="utf-8")


def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--dry-run",action="store_true"); ap.add_argument("--skip-check",action="store_true"); args=ap.parse_args(argv)
    root=Path(__file__).resolve().parents[1]; current=(root/"VERSION").read_text(encoding="utf-8").strip()
    if current!=NEW: raise SystemExit(f"ERROR: expected VERSION {NEW}, got {current!r}")
    required=[root/"tools"/"apply_v6114_release.py",root/"sbb"/"media_team_sources_v6115.py",
              root/"tests"/"test_v6115_team_resolution_queue.py",root/"tests"/"test_v6115_team_resolution_release.py",root/"media_audit_service.py"]
    missing=[str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing: raise SystemExit("ERROR: incomplete v6.1.15 release: "+", ".join(missing))
    if args.dry_run:
        print("v6.1.15: persistent unresolved-team queue + source-upgrade repair wakeups"); return 0
    run_base(root); patch_media_audit(root); patch_ui(root); patch_legacy_contracts(root); patch_verify(root); promote(root); controller(root)
    print("Sports Big Board v6.1.15 materialized")
    print("R24 team resolution: persistent due queue, explicit states, immediate team repair requeue")
    print("Resolver cadence: seed-owner only, 2 teams/minute by default under external-source semaphore")
    if args.skip_check: return 0
    subprocess.run([sys.executable,str(root/"tools"/"check_release_version.py")],cwd=root,check=True)
    return 0


if __name__=="__main__": raise SystemExit(main())

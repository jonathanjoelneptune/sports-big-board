"""v6.1.15 persistent team-resolution control loop for Media Repair.

R24 turns team-source discovery into its own bounded, persistent work queue. Team
identity failures are retried independently from game repair jobs, resolution
upgrades requeue every waiting game for that team immediately, and the operator
snapshot exposes the hard tail instead of silently repeating identical lookups.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import closing

from .media_team_sources_v6114 import TeamSourceRegistry as _V6114TeamSourceRegistry

GENERATION = "R24-TEAM-SOURCE-RESOLUTION-CONTROL-LOOP"
DEFAULT_RESOLUTION_RETRY_SECONDS = 2 * 3600
DEFAULT_RESOLUTION_ERROR_RETRY_SECONDS = 60 * 60
DEFAULT_RESOLUTION_BATCH = 2
RESOLUTION_RANK = {
    "UNRESOLVED": 0,
    "NO_DIRECTORY_MATCH": 0,
    "FAILED": 0,
    "LEAGUE_PAGE_FOUND": 1,
    "OFFICIAL_SITE_FOUND": 2,
    "YOUTUBE_FOUND": 3,
}
RESOLVED_STATES = {"LEAGUE_PAGE_FOUND", "OFFICIAL_SITE_FOUND", "YOUTUBE_FOUND"}


class TeamSourceRegistry(_V6114TeamSourceRegistry):
    """R24 resolver with a persistent unresolved-team queue and upgrade callback."""

    def __init__(self, *args, unresolved_retry_seconds=None, error_retry_seconds=None,
                 on_team_resolved=None, **kwargs):
        self.unresolved_retry_seconds = max(
            300.0,
            float(unresolved_retry_seconds or os.environ.get(
                "SBB_MEDIA_TEAM_RESOLUTION_RETRY_SECONDS", DEFAULT_RESOLUTION_RETRY_SECONDS)),
        )
        self.error_retry_seconds = max(
            300.0,
            float(error_retry_seconds or os.environ.get(
                "SBB_MEDIA_TEAM_RESOLUTION_ERROR_RETRY_SECONDS", DEFAULT_RESOLUTION_ERROR_RETRY_SECONDS)),
        )
        self.on_team_resolved = on_team_resolved
        super().__init__(*args, **kwargs)

    def _ensure_schema(self):
        super()._ensure_schema()
        with self.lock, closing(self.connect()) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS team_resolution_queue (
                  entity_key TEXT PRIMARY KEY,
                  league TEXT NOT NULL DEFAULT '', team_id TEXT NOT NULL DEFAULT '',
                  team_name TEXT NOT NULL DEFAULT '', entity_json TEXT NOT NULL DEFAULT '{}',
                  status TEXT NOT NULL DEFAULT 'UNRESOLVED', reason TEXT NOT NULL DEFAULT '',
                  attempt_count INTEGER NOT NULL DEFAULT 0,
                  first_seen_at REAL NOT NULL DEFAULT 0, last_attempt_at REAL NOT NULL DEFAULT 0,
                  next_retry_at REAL NOT NULL DEFAULT 0, resolved_at REAL NOT NULL DEFAULT 0,
                  last_source_count INTEGER NOT NULL DEFAULT 0,
                  last_channel_count INTEGER NOT NULL DEFAULT 0,
                  last_directory_fetches INTEGER NOT NULL DEFAULT 0,
                  last_directory_cache_hits INTEGER NOT NULL DEFAULT 0,
                  last_directory_errors INTEGER NOT NULL DEFAULT 0,
                  last_league_pages INTEGER NOT NULL DEFAULT 0,
                  last_official_sites INTEGER NOT NULL DEFAULT 0,
                  last_youtube_channels INTEGER NOT NULL DEFAULT 0,
                  last_requeued_jobs INTEGER NOT NULL DEFAULT 0,
                  total_requeued_jobs INTEGER NOT NULL DEFAULT 0,
                  updated_at REAL NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_team_resolution_due
                  ON team_resolution_queue(status,next_retry_at,last_attempt_at);
            """)
            conn.commit()

    @staticmethod
    def _entity_payload(entity):
        return {
            "entityKey": str(entity.get("entityKey") or ""),
            "league": str(entity.get("league") or ""), "side": str(entity.get("side") or ""),
            "teamId": str(entity.get("teamId") or ""), "teamName": str(entity.get("teamName") or ""),
            "slug": str(entity.get("slug") or ""), "nickname": str(entity.get("nickname") or ""),
            "raw": entity.get("raw") if isinstance(entity.get("raw"), dict) else {},
            "metadataUrls": list(entity.get("metadataUrls") or []),
        }

    def _ensure_resolution_row(self, entity):
        now = time.time(); payload = self._entity_payload(entity); key = payload["entityKey"]
        with self.lock, closing(self.connect()) as conn:
            conn.execute("""INSERT INTO team_resolution_queue(
                     entity_key,league,team_id,team_name,entity_json,status,
                     first_seen_at,next_retry_at,updated_at)
                   VALUES(?,?,?,?,?,'UNRESOLVED',?,?,?)
                   ON CONFLICT(entity_key) DO UPDATE SET
                     league=excluded.league,
                     team_id=CASE WHEN excluded.team_id<>'' THEN excluded.team_id ELSE team_resolution_queue.team_id END,
                     team_name=CASE WHEN excluded.team_name<>'' THEN excluded.team_name ELSE team_resolution_queue.team_name END,
                     entity_json=excluded.entity_json,updated_at=excluded.updated_at""",
                (key,payload["league"],payload["teamId"],payload["teamName"],
                 json.dumps(payload,separators=(",",":"),ensure_ascii=False),now,0,now))
            row = conn.execute("SELECT * FROM team_resolution_queue WHERE entity_key=?", (key,)).fetchone()
            conn.commit()
        return dict(row) if row else {}

    def _resolution_row(self, entity_key):
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM team_resolution_queue WHERE entity_key=?", (entity_key,)).fetchone()
        return dict(row) if row else {}

    def _verified_source_counts(self, entity_key):
        with closing(self.connect()) as conn:
            rows = conn.execute("""SELECT source_type,COUNT(*) n FROM team_source
                                   WHERE entity_key=? AND verified_at>0 GROUP BY source_type""",
                                (entity_key,)).fetchall()
        counts = {str(r["source_type"]): int(r["n"] or 0) for r in rows}
        return {
            "verifiedSources": sum(counts.values()),
            "leaguePages": int(counts.get("OFFICIAL_LEAGUE_TEAM_PAGE",0)),
            "officialSites": int(counts.get("OFFICIAL_TEAM_WEB",0)),
            "youtubeChannels": int(counts.get("OFFICIAL_TEAM_YOUTUBE",0)),
            "sourceTypes": counts,
        }

    @staticmethod
    def _status_for_sources(counts):
        if int(counts.get("youtubeChannels") or 0): return "YOUTUBE_FOUND"
        if int(counts.get("officialSites") or 0): return "OFFICIAL_SITE_FOUND"
        if int(counts.get("leaguePages") or 0): return "LEAGUE_PAGE_FOUND"
        return "UNRESOLVED"

    def _directory_resolution_fresh(self, entity_key):
        if super()._directory_resolution_fresh(entity_key): return True
        row = self._resolution_row(entity_key)
        if not row or str(row.get("status") or "") in RESOLVED_STATES: return False
        return float(row.get("next_retry_at") or 0) > time.time()

    def _update_resolution(self, entity, stats=None, attempted=False):
        now=time.time(); stats=dict(stats or {}); prior=self._ensure_resolution_row(entity)
        counts=self._verified_source_counts(entity["entityKey"])
        new_status=self._status_for_sources(counts); prior_status=str(prior.get("status") or "UNRESOLVED")
        prior_rank=RESOLUTION_RANK.get(prior_status,0); new_rank=RESOLUTION_RANK.get(new_status,0)
        if new_rank:
            reason=(f"{new_status}: {counts['verifiedSources']} verified source(s), "
                    f"{counts['youtubeChannels']} official YouTube channel(s)")
            next_retry=0.0; resolved_at=float(prior.get("resolved_at") or 0) or now
        else:
            directory_errors=int(stats.get("directoryErrors") or 0); directory_links=int(stats.get("directoryLinks") or 0)
            if attempted and directory_errors and not directory_links:
                new_status="FAILED"; reason="Authoritative league directory unavailable or returned an error"
            elif attempted:
                new_status="NO_DIRECTORY_MATCH"; reason="Authoritative directory/provider metadata produced no verified team source"
            else:
                new_status=prior_status if prior_status not in RESOLVED_STATES else "UNRESOLVED"
                reason=str(prior.get("reason") or "Awaiting team-source resolution")
            delay=self.error_retry_seconds if new_status=="FAILED" else self.unresolved_retry_seconds
            next_retry=now+delay if attempted else float(prior.get("next_retry_at") or 0); resolved_at=0.0
        upgraded=RESOLUTION_RANK.get(new_status,0)>prior_rank; requeued=0
        if upgraded and callable(self.on_team_resolved):
            try:
                requeued=int(self.on_team_resolved(dict(entity),{
                    "previousStatus":prior_status,"status":new_status,"counts":counts,"reason":reason}) or 0)
            except Exception as exc:
                reason=(reason+f"; requeueCallback={type(exc).__name__}: {exc}")[:1000]
        with self.lock, closing(self.connect()) as conn:
            conn.execute("""UPDATE team_resolution_queue SET
                     league=?,team_id=?,team_name=?,entity_json=?,status=?,reason=?,
                     attempt_count=attempt_count+?,last_attempt_at=?,next_retry_at=?,resolved_at=?,
                     last_source_count=?,last_channel_count=?,last_directory_fetches=?,last_directory_cache_hits=?,
                     last_directory_errors=?,last_league_pages=?,last_official_sites=?,last_youtube_channels=?,
                     last_requeued_jobs=?,total_requeued_jobs=total_requeued_jobs+?,updated_at=?,metadata_json=?
                   WHERE entity_key=?""",
                (str(entity.get("league") or ""),str(entity.get("teamId") or ""),str(entity.get("teamName") or ""),
                 json.dumps(self._entity_payload(entity),separators=(",",":"),ensure_ascii=False),new_status,reason[:1000],
                 1 if attempted else 0,now if attempted else float(prior.get("last_attempt_at") or 0),next_retry,resolved_at,
                 int(counts.get("verifiedSources") or 0),int(counts.get("youtubeChannels") or 0),
                 int(stats.get("directoryFetches") or 0),int(stats.get("directoryCacheHits") or 0),
                 int(stats.get("directoryErrors") or 0),int(stats.get("leaguePagesResolved") or 0),
                 int(stats.get("officialSites") or 0),int(stats.get("youtubeChannels") or 0),requeued,requeued,now,
                 json.dumps({"sourceCounts":counts,"lastRefresh":stats},separators=(",",":"),ensure_ascii=False),
                 entity["entityKey"]))
            row=conn.execute("SELECT * FROM team_resolution_queue WHERE entity_key=?",(entity["entityKey"],)).fetchone(); conn.commit()
        result=dict(row) if row else {}; result["upgraded"]=upgraded; result["requeuedJobs"]=requeued; result["sourceCounts"]=counts
        return result

    def _refresh_entity(self, entity, youtube, api_key, stop_event=None, force=False):
        prior=self._ensure_resolution_row(entity); learned=self._learn_trusted_index_channels(entity); now=time.time()
        due=force or float(prior.get("next_retry_at") or 0)<=now
        already_resolved=self._status_for_sources(self._verified_source_counts(entity["entityKey"])) in RESOLVED_STATES
        attempted=False
        stats={"entityKey":entity["entityKey"],"team":entity["teamName"],"side":entity.get("side") or "",
               "pagesChecked":0,"verifiedWeb":0,"youtubeChannels":0,"indexedVideos":0,"trustedIndexLearned":learned,
               "directoryFetches":0,"directoryCacheHits":0,"directoryErrors":0,"directoryLinks":0,
               "leaguePagesResolved":0,"officialSites":0,"providerMetadataPages":0}
        if not already_resolved and due:
            attempted=True; resolved=self._resolve_from_directory(entity,youtube,api_key)
            if not (resolved.get("leaguePagesResolved") or resolved.get("officialSites")):
                fallback=self._resolve_provider_metadata(entity,youtube,api_key)
                for key,value in fallback.items(): resolved[key]=int(resolved.get(key) or 0)+int(value or 0)
            for key in ("pagesChecked","youtubeChannels","directoryFetches","directoryCacheHits","directoryErrors",
                        "directoryLinks","leaguePagesResolved","officialSites","providerMetadataPages"):
                stats[key]+=int(resolved.get(key) or 0)
        channels=self._verified_channels(entity["entityKey"]); stats["youtubeChannels"]=max(stats["youtubeChannels"],len(channels))
        for source in channels:
            if stop_event is not None and stop_event.is_set(): break
            stats["indexedVideos"]+=int(self._index_channel(entity,source,youtube,api_key,stop_event=stop_event) or 0)
        stats["verifiedWeb"]=int(stats["leaguePagesResolved"])+int(stats["officialSites"])
        resolution=self._update_resolution(entity,stats=stats,attempted=attempted)
        stats.update({"resolutionStatus":str(resolution.get("status") or "UNRESOLVED"),
                      "resolutionReason":str(resolution.get("reason") or ""),
                      "resolutionAttempts":int(resolution.get("attempt_count") or 0),
                      "nextResolutionRetryAt":float(resolution.get("next_retry_at") or 0),
                      "resolutionUpgraded":bool(resolution.get("upgraded")),
                      "repairJobsRequeued":int(resolution.get("requeuedJobs") or 0),
                      "verifiedSourceCount":int((resolution.get("sourceCounts") or {}).get("verifiedSources") or 0)})
        return stats

    def refresh_event_sources(self, context, youtube, api_key, stop_event=None):
        summary={"teams":[],"pagesChecked":0,"verifiedWeb":0,"youtubeChannels":0,"trustedIndexLearned":0,
                 "indexedVideos":0,"directoryFetches":0,"directoryCacheHits":0,"directoryErrors":0,"directoryLinks":0,
                 "leaguePagesResolved":0,"officialSites":0,"providerMetadataPages":0,"resolutionUpgrades":0,
                 "repairJobsRequeued":0,"unresolvedTeams":0}
        for entity in self.entities(context):
            if stop_event is not None and stop_event.is_set(): break
            stats=self._refresh_entity(entity,youtube,api_key,stop_event=stop_event)
            for key in ("pagesChecked","verifiedWeb","youtubeChannels","trustedIndexLearned","indexedVideos","directoryFetches",
                        "directoryCacheHits","directoryErrors","directoryLinks","leaguePagesResolved","officialSites",
                        "providerMetadataPages","repairJobsRequeued"):
                summary[key]+=int(stats.get(key) or 0)
            if stats.get("resolutionUpgraded"): summary["resolutionUpgrades"]+=1
            if str(stats.get("resolutionStatus") or "") not in RESOLVED_STATES: summary["unresolvedTeams"]+=1
            summary["teams"].append(stats)
        return summary

    def resolve_due(self, youtube, api_key, limit=None, stop_event=None):
        limit=max(1,min(20,int(limit or os.environ.get("SBB_MEDIA_TEAM_RESOLUTION_BATCH",DEFAULT_RESOLUTION_BATCH))))
        now=time.time()
        with closing(self.connect()) as conn:
            rows=conn.execute("""SELECT * FROM team_resolution_queue
                   WHERE status NOT IN ('LEAGUE_PAGE_FOUND','OFFICIAL_SITE_FOUND','YOUTUBE_FOUND') AND next_retry_at<=?
                   ORDER BY attempt_count ASC,last_attempt_at ASC,first_seen_at ASC LIMIT ?""",(now,limit)).fetchall()
        summary={"attempted":0,"resolved":0,"upgraded":0,"repairJobsRequeued":0,"teams":[]}
        for row in rows:
            if stop_event is not None and stop_event.is_set(): break
            try: entity=json.loads(str(row["entity_json"] or "{}"))
            except Exception: entity={}
            if not entity.get("entityKey") or not entity.get("teamName"): continue
            stats=self._refresh_entity(entity,youtube,api_key,stop_event=stop_event,force=True); summary["attempted"]+=1
            if str(stats.get("resolutionStatus") or "") in RESOLVED_STATES: summary["resolved"]+=1
            if stats.get("resolutionUpgraded"): summary["upgraded"]+=1
            summary["repairJobsRequeued"]+=int(stats.get("repairJobsRequeued") or 0)
            summary["teams"].append({"entityKey":stats.get("entityKey"),"team":stats.get("team"),
                                     "status":stats.get("resolutionStatus"),"attempts":stats.get("resolutionAttempts"),
                                     "requeued":stats.get("repairJobsRequeued")})
        return summary

    def snapshot(self):
        base=super().snapshot(); now=time.time()
        try:
            with closing(self.connect()) as conn:
                states={str(r["status"]):int(r["n"] or 0) for r in conn.execute(
                    "SELECT status,COUNT(*) n FROM team_resolution_queue GROUP BY status").fetchall()}
                unresolved=int(conn.execute("""SELECT COUNT(*) FROM team_resolution_queue
                    WHERE status NOT IN ('LEAGUE_PAGE_FOUND','OFFICIAL_SITE_FOUND','YOUTUBE_FOUND')""").fetchone()[0] or 0)
                due=int(conn.execute("""SELECT COUNT(*) FROM team_resolution_queue
                    WHERE status NOT IN ('LEAGUE_PAGE_FOUND','OFFICIAL_SITE_FOUND','YOUTUBE_FOUND') AND next_retry_at<=?""",
                    (now,)).fetchone()[0] or 0)
                resolved=int(conn.execute("""SELECT COUNT(*) FROM team_resolution_queue
                    WHERE status IN ('LEAGUE_PAGE_FOUND','OFFICIAL_SITE_FOUND','YOUTUBE_FOUND')""").fetchone()[0] or 0)
                total_requeued=int(conn.execute("SELECT COALESCE(SUM(total_requeued_jobs),0) FROM team_resolution_queue").fetchone()[0] or 0)
                recent_unresolved=[dict(r) for r in conn.execute("""SELECT entity_key,league,team_name,status,reason,
                    attempt_count,last_attempt_at,next_retry_at FROM team_resolution_queue
                    WHERE status NOT IN ('LEAGUE_PAGE_FOUND','OFFICIAL_SITE_FOUND','YOUTUBE_FOUND')
                    ORDER BY last_attempt_at DESC,first_seen_at DESC LIMIT 8""").fetchall()]
            base.update({"generation":GENERATION,"resolutionStates":states,"resolvedTeams":resolved,
                         "unresolvedTeams":unresolved,"dueUnresolvedTeams":due,"waitingUnresolvedTeams":max(0,unresolved-due),
                         "repairJobsRequeuedByResolution":total_requeued,"recentUnresolvedTeams":recent_unresolved})
        except Exception as exc:
            base["resolutionSnapshotError"]=f"{type(exc).__name__}: {exc}"
        return base

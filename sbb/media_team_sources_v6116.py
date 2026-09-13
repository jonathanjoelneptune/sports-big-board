"""v6.1.16 R25 authoritative seed directory + repair-yield team-source resolver.

Manual first-party video destinations are treated as authoritative seeds, not as
playback proof. A seed resolves team ownership immediately, then the existing
registry verifies/enriches the page, discovers linked YouTube channels/embeds,
indexes uploads, and wakes affected repair jobs through the R24 callback.
"""
from __future__ import annotations

import json
import re
import time
from contextlib import closing

from .media_team_seed_v6116 import TEAM_VIDEO_SEEDS, SEED_COUNTS
from .media_team_sources_v6115 import TeamSourceRegistry as _V6115TeamSourceRegistry
from .media_team_sources_v6113 import _identity_norm

GENERATION = "R25-AUTHORITATIVE-TEAM-SEED-DIRECTORY"


def _clean_identity(value):
    value = _identity_norm(value)
    value = re.sub(r"^\d+\s+", "", value).strip()
    return value


class TeamSourceRegistry(_V6115TeamSourceRegistry):
    """R25 resolver that overlays curated first-party team video destinations."""

    def __init__(self, *args, **kwargs):
        self._seed_rows = list(TEAM_VIDEO_SEEDS)
        super().__init__(*args, **kwargs)
        self._wake_seed_matches()

    @staticmethod
    def _seed_aliases(row):
        values = list(row.get("aliases") or [])
        values.append(str(row.get("team") or ""))
        out = []
        seen = set()
        for value in values:
            raw = str(value or "").strip()
            if not raw:
                continue
            variants = [raw, re.sub(r"\s*\([^)]*\)\s*", " ", raw).strip()]
            for variant in variants:
                norm = _clean_identity(variant)
                if norm and norm not in seen:
                    seen.add(norm)
                    out.append((variant, norm))
        return out

    def _seed_match(self, entity):
        league = str(entity.get("league") or "").upper()
        team_norm = _clean_identity(entity.get("teamName") or "")
        raw = entity.get("raw") if isinstance(entity.get("raw"), dict) else {}
        entity_values = [entity.get("teamName") or ""]
        for key in ("displayName", "name", "shortName", "teamName", "nickname",
                    "location", "abbreviation", "slug"):
            if raw.get(key):
                entity_values.append(str(raw.get(key)))
        entity_norms = {_clean_identity(v) for v in entity_values if _clean_identity(v)}
        ranked = []
        for row in self._seed_rows:
            if str(row.get("league") or "").upper() != league:
                continue
            best = 0.0
            for _, seed_norm in self._seed_aliases(row):
                if seed_norm in entity_norms:
                    best = max(best, 1.0)
                for entity_norm in entity_norms | ({team_norm} if team_norm else set()):
                    if not entity_norm:
                        continue
                    if entity_norm == seed_norm:
                        best = max(best, 1.0)
                    elif len(seed_norm.split()) >= 2 and entity_norm.startswith(seed_norm + " "):
                        best = max(best, 0.97)
                    elif len(entity_norm.split()) >= 2 and seed_norm.startswith(entity_norm + " "):
                        best = max(best, 0.96)
                    elif len(seed_norm.split()) == 1 and len(seed_norm) >= 3 and entity_norm.startswith(seed_norm + " "):
                        # Single-school NCAAF seeds (Iowa, Georgia, Washington, USC)
                        # are useful only as a lower-confidence fallback. A longer
                        # competing seed such as Georgia Tech wins deterministically.
                        best = max(best, 0.84)
            best = max(best, float(self._identity_score(entity, *(row.get("aliases") or [row.get("team") or ""])) or 0))
            if best:
                ranked.append((best, row))
        ranked.sort(key=lambda x: (-x[0], -len(_clean_identity(x[1].get("team") or "")), str(x[1].get("team") or "")))
        if not ranked or ranked[0][0] < 0.84:
            return None
        if len(ranked) > 1 and ranked[0][0] < 0.95 and ranked[0][0] - ranked[1][0] < 0.08:
            return None
        return dict(ranked[0][1])

    def _wake_seed_matches(self):
        """Make existing NO_DIRECTORY_MATCH rows immediately eligible for seed resolution."""
        try:
            with self.lock, closing(self.connect()) as conn:
                rows = conn.execute(
                    """SELECT entity_key,entity_json,status FROM team_resolution_queue
                       WHERE status NOT IN ('LEAGUE_PAGE_FOUND','OFFICIAL_SITE_FOUND','YOUTUBE_FOUND')"""
                ).fetchall()
                now = time.time()
                for row in rows:
                    try:
                        entity = json.loads(str(row["entity_json"] or "{}"))
                    except Exception:
                        entity = {}
                    if not entity or not self._seed_match(entity):
                        continue
                    conn.execute(
                        """UPDATE team_resolution_queue
                           SET status='UNRESOLVED', reason='Manual authoritative team-video seed available',
                               next_retry_at=0, updated_at=?
                           WHERE entity_key=?""",
                        (now, str(row["entity_key"])),
                    )
                conn.commit()
        except Exception:
            # Seed acceleration is opportunistic; never block Media Repair startup.
            pass

    def _apply_seed(self, entity, youtube, api_key):
        row = self._seed_match(entity)
        if not row:
            return {
                "seedMatched": False, "seedUrl": "", "seedRole": "",
                "pagesChecked": 0, "officialSites": 0, "youtubeChannels": 0,
            }
        url = str(row.get("url") or "").strip()
        role = str(row.get("role") or "VIDEO_INDEX")
        evidence = f"Manual authoritative team-video seed: {row.get('team') or entity.get('teamName')} [{role}]"
        # Consume first so a fresh seed gets one bounded HTML pass for linked
        # channels/embeds. The final upsert changes provenance to the explicit seed.
        stats = self._consume_official_site(
            entity, url, youtube, api_key, evidence=evidence
        )
        self._upsert_source(
            entity,
            "OFFICIAL_TEAM_WEB",
            url,
            url=url,
            trust_state="MANUAL_AUTHORITATIVE_SEED",
            evidence=evidence,
            checked=True,
            verified=True,
            metadata={
                "provenance": "MANUAL_AUTHORITATIVE_SEED",
                "seedTeam": row.get("team") or "",
                "seedAliases": list(row.get("aliases") or []),
                "sourceRole": role,
            },
        )
        return {
            "seedMatched": True,
            "seedUrl": url,
            "seedRole": role,
            "pagesChecked": int(stats.get("pagesChecked") or 0),
            "officialSites": max(1, int(stats.get("officialSites") or 0)),
            "youtubeChannels": int(stats.get("youtubeChannels") or 0),
        }

    def _refresh_entity(self, entity, youtube, api_key, stop_event=None, force=False):
        seed = self._apply_seed(entity, youtube, api_key)
        stats = super()._refresh_entity(
            entity, youtube, api_key, stop_event=stop_event, force=force
        )
        stats["seedMatched"] = bool(seed.get("seedMatched"))
        stats["seedUrl"] = str(seed.get("seedUrl") or "")
        stats["seedRole"] = str(seed.get("seedRole") or "")
        stats["seedPagesChecked"] = int(seed.get("pagesChecked") or 0)
        stats["seedOfficialSites"] = int(seed.get("officialSites") or 0)
        stats["seedYoutubeChannels"] = int(seed.get("youtubeChannels") or 0)
        return stats

    def refresh_event_sources(self, context, youtube, api_key, stop_event=None):
        summary = super().refresh_event_sources(
            context, youtube, api_key, stop_event=stop_event
        )
        summary["seedMatches"] = sum(1 for row in summary.get("teams") or [] if row.get("seedMatched"))
        summary["seedPagesChecked"] = sum(int(row.get("seedPagesChecked") or 0) for row in summary.get("teams") or [])
        return summary

    def snapshot(self):
        base = super().snapshot()
        matched = 0
        try:
            with closing(self.connect()) as conn:
                matched = int(conn.execute(
                    "SELECT COUNT(DISTINCT entity_key) FROM team_source "
                    "WHERE trust_state='MANUAL_AUTHORITATIVE_SEED' AND verified_at>0"
                ).fetchone()[0] or 0)
        except Exception:
            pass
        base.update({
            "generation": GENERATION,
            "seedEntries": len(self._seed_rows),
            "seedLeagueCounts": dict(SEED_COUNTS),
            "seededTeams": matched,
            "seedProvenance": "MANUAL_AUTHORITATIVE_SEED",
        })
        return base

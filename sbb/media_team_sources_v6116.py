"""v6.1.16 Media Repair team-source identity refinements.

This layer preserves the persistent v6.1.15 resolution queue while making
college-directory and trusted-channel identity matching tolerant of the small,
authoritative naming differences that appear in provider data (for example
``New Mexico State`` vs ``New Mexico St`` and ``Hawai'i`` vs ``Hawaii``).

The resolver remains conservative: the additional directory-prefix rule applies
only to NCAAF and requires a multi-token institutional prefix.  Existing semantic
card/JSON ownership scoping and >=0.90 verification thresholds remain intact.
"""
from __future__ import annotations

import re
from contextlib import closing

from .media_team_sources_v6115 import TeamSourceRegistry as _V6115TeamSourceRegistry
from .media_team_sources_v6113 import _identity_norm, _iter_alias_values

GENERATION = "R25-TEAM-IDENTITY-ALIASES"

_TOKEN_EQUIVALENTS = {
    "st": "state",
    "stte": "state",
    "univ": "university",
}


def _tokens(value: object) -> list[str]:
    return [_TOKEN_EQUIVALENTS.get(token, token) for token in _identity_norm(value).split() if token]


def _compact(value: object) -> str:
    return "".join(_tokens(value))


def _alias_values(entity: dict) -> list[str]:
    values = [str(entity.get("teamName") or "")]
    raw = entity.get("raw") or {}
    values.extend(_iter_alias_values(raw))
    if isinstance(raw, dict):
        for key in ("shortDisplayName", "longDisplayName", "school", "institution"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
    out = []
    seen = set()
    for value in values:
        value = str(value or "").strip()
        key = _compact(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


class TeamSourceRegistry(_V6115TeamSourceRegistry):
    """R25 identity matcher layered on the persistent R24 resolver."""

    def _identity_score(self, entity: dict, *values: object) -> float:
        best = float(super()._identity_score(entity, *values) or 0.0)
        hay_text = " ".join(str(value or "") for value in values)
        hay_tokens = _tokens(hay_text)
        hay = " ".join(hay_tokens)
        hay_compact = "".join(hay_tokens)
        if not hay_compact:
            return best

        # Provider aliases frequently differ only by abbreviations or punctuation.
        # Exact canonical-token aliases are authoritative enough for the same 0.97
        # score used by the previous all-token matcher.
        for alias in _alias_values(entity):
            alias_tokens = _tokens(alias)
            if not alias_tokens:
                continue
            alias_text = " ".join(alias_tokens)
            alias_compact = "".join(alias_tokens)
            if alias_text and re.search(r"(^|\s)" + re.escape(alias_text) + r"(\s|$)", hay):
                best = max(best, 0.99)
                continue
            if len(alias_compact) >= 5 and alias_compact in hay_compact:
                best = max(best, 0.96)

        # College provider display names usually append a mascot while the NCAA
        # directory uses the institution/location only.  Check at most the two
        # longest prefixes after dropping mascot words.  Requiring >=2 tokens keeps
        # ambiguous one-word schools (Michigan vs Michigan State, etc.) out of this
        # relaxed path; rich provider aliases still handle those normally.
        if str(entity.get("league") or "").upper() == "NCAAF":
            full = _tokens(entity.get("teamName") or "")
            for cut in range(len(full) - 1, max(1, len(full) - 3), -1):
                prefix = full[:cut]
                if len(prefix) < 2:
                    continue
                prefix_text = " ".join(prefix)
                prefix_compact = "".join(prefix)
                if len(prefix_compact) < 5:
                    continue
                if re.search(r"(^|\s)" + re.escape(prefix_text) + r"(\s|$)", hay):
                    best = max(best, 0.95)
                    break
                if prefix_compact in hay_compact:
                    best = max(best, 0.94)
                    break
        return best

    def _learn_trusted_index_channels(self, entity: dict) -> int:
        """Reuse already-indexed official channels with the same identity scorer."""
        learned = 0
        try:
            with closing(self.store.connect(timeout=3)) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT channel_id,channel_name FROM history_media_repair_youtube_index "
                    "WHERE channel_id<>'' AND channel_name<>'' LIMIT 2000"
                ).fetchall()
        except Exception:
            return 0
        for row in rows:
            channel_id = str(row["channel_id"] or "")
            channel_name = str(row["channel_name"] or "")
            if not channel_id or self._identity_score(entity, channel_name) < 0.90:
                continue
            self._upsert_source(
                entity,
                "OFFICIAL_TEAM_YOUTUBE",
                channel_id,
                channel_id=channel_id,
                channel_name=channel_name,
                trust_state="TRUSTED_INDEX_IDENTITY_MATCH",
                evidence="Matched team identity/aliases inside the existing trusted official YouTube index",
                checked=True,
                verified=True,
            )
            learned += 1
        return learned

    def snapshot(self) -> dict:
        base = super().snapshot()
        base["generation"] = GENERATION
        base["identityMatching"] = "PROVIDER_ALIASES+NCAAF_INSTITUTION_PREFIX"
        return base

"""Authoritative league-directory resolver for Media Repair team sources.

v6.1.13 / R23 replaces guessed league team URLs with a persistent resolver:
official league directory -> matched team entry -> league team page / club site ->
official YouTube channel -> bounded uploads index.

The resolver extends the v6.1.12 registry so existing verified channels/videos remain
valid. Directory links are cached in the same small sidecar SQLite database and
network failures are negatively cached to keep the hard-tail repair loop bounded.
"""
from __future__ import annotations

import html as html_lib
import os
import re
import time
from contextlib import closing
from urllib.parse import urljoin, urlparse

from .media_team_sources_v6112 import (
    BLOCKED_METADATA_HOSTS,
    LEAGUE_HOSTS,
    YOUTUBE_CHANNEL_RE,
    YOUTUBE_VIDEO_RE,
    TeamSourceRegistry as _V6112TeamSourceRegistry,
    _norm,
)

GENERATION = "R23-OFFICIAL-TEAM-DIRECTORY-SOURCES"

DEFAULT_DIRECTORY_REFRESH_SECONDS = 7 * 24 * 3600
DEFAULT_DIRECTORY_FAILURE_RETRY_SECONDS = 60 * 60
DEFAULT_DIRECTORY_LINK_LIMIT = 2500

# Authoritative league indexes. These are intentionally directory pages rather
# than guessed team slugs. A team page/site is trusted only when the directory
# context itself matches the team identity.
LEAGUE_DIRECTORY_URLS = {
    "MLB": ("https://www.mlb.com/team",),
    "NBA": ("https://www.nba.com/teams",),
    "NHL": ("https://www.nhl.com/info/teams/",),
    "NFL": ("https://www.nfl.com/teams/",),
    "MLS": ("https://www.mlssoccer.com/clubs/",),
    "EPL": ("https://www.premierleague.com/en/clubs",),
    "NCAAF": ("https://www.ncaa.com/schools",),
}

ANCHOR_RE = re.compile(
    r"<a\b(?P<attrs>[^>]*?)\bhref\s*=\s*[\"'](?P<href>[^\"']+)[\"'](?P<tail>[^>]*)>(?P<body>.*?)</a\s*>",
    re.I | re.S,
)
ATTR_LABEL_RE = re.compile(
    r"\b(?:aria-label|title|data-label|data-testid)\s*=\s*[\"']([^\"']+)[\"']",
    re.I,
)
JSON_LINK_RE = re.compile(
    r"[\"'](?:href|url|link|website|officialWebsite|clubSite)[\"']\s*:\s*[\"']([^\"']+)[\"']",
    re.I,
)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")

IDENTITY_SUFFIXES = {"fc", "sc", "cf", "afc", "club"}
OFFICIAL_SITE_HINTS = (
    "official site",
    "official website",
    "club site",
    "team site",
    "full site",
    "visit site",
    "visit website",
    "website",
)
NON_SITE_HINTS = (
    "ticket", "shop", "store", "merch", "sponsor", "partner", "privacy",
    "terms", "foundation", "academy", "jobs", "careers",
)


def _text(value: object) -> str:
    raw = html_lib.unescape(str(value or ""))
    raw = TAG_RE.sub(" ", raw)
    return SPACE_RE.sub(" ", raw).strip()


def _decode_link(value: object) -> str:
    text = html_lib.unescape(str(value or "")).strip()
    text = text.replace("\\/", "/").replace("\\u0026", "&").replace("\\u003d", "=")
    return text


def _identity_norm(value: object) -> str:
    words = _norm(value).split()
    while words and words[-1] in IDENTITY_SUFFIXES:
        words.pop()
    return " ".join(words)


def _identity_tokens(value: object) -> set[str]:
    return {t for t in _identity_norm(value).split() if len(t) >= 2}


def _iter_alias_values(raw: object):
    if isinstance(raw, str):
        if raw.strip():
            yield raw.strip()
        return
    if isinstance(raw, dict):
        for key in (
            "displayName", "name", "shortName", "teamName", "nickname",
            "location", "abbreviation", "slug",
        ):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                yield value.strip()
        aliases = raw.get("aliases")
        if isinstance(aliases, (list, tuple)):
            for value in aliases:
                if isinstance(value, str) and value.strip():
                    yield value.strip()


def _team_aliases(entity: dict) -> list[str]:
    values = [str(entity.get("teamName") or "")]
    values.extend(_iter_alias_values(entity.get("raw") or {}))
    out = []
    normalized = set()
    for value in values:
        value = str(value or "").strip()
        if not value:
            continue
        norm = _identity_norm(value)
        if len(norm) < 3 or norm in normalized:
            continue
        normalized.add(norm)
        out.append(value)
    return out


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _is_youtube_host(host: str) -> bool:
    return host in {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}


class TeamSourceRegistry(_V6112TeamSourceRegistry):
    """v6.1.13 registry with persistent authoritative league-directory resolution."""

    def __init__(self, *args, directory_refresh_seconds=None, directory_failure_retry_seconds=None, **kwargs):
        self.directory_refresh_seconds = float(
            directory_refresh_seconds
            or os.environ.get("SBB_MEDIA_TEAM_DIRECTORY_REFRESH_SECONDS", DEFAULT_DIRECTORY_REFRESH_SECONDS)
        )
        self.directory_failure_retry_seconds = float(
            directory_failure_retry_seconds
            or os.environ.get("SBB_MEDIA_TEAM_DIRECTORY_FAILURE_RETRY_SECONDS", DEFAULT_DIRECTORY_FAILURE_RETRY_SECONDS)
        )
        self.directory_link_limit = max(
            100,
            min(
                10000,
                int(os.environ.get("SBB_MEDIA_TEAM_DIRECTORY_LINK_LIMIT", DEFAULT_DIRECTORY_LINK_LIMIT)),
            ),
        )
        super().__init__(*args, **kwargs)

    def _ensure_schema(self):
        super()._ensure_schema()
        with self.lock, closing(self.connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS league_directory_link (
                  league TEXT NOT NULL,
                  directory_url TEXT NOT NULL,
                  link_url TEXT NOT NULL,
                  link_text TEXT NOT NULL DEFAULT '',
                  context_text TEXT NOT NULL DEFAULT '',
                  link_host TEXT NOT NULL DEFAULT '',
                  refreshed_at REAL NOT NULL DEFAULT 0,
                  PRIMARY KEY(league,directory_url,link_url,link_text)
                );
                CREATE INDEX IF NOT EXISTS idx_league_directory_link
                  ON league_directory_link(league,refreshed_at);
                CREATE TABLE IF NOT EXISTS league_directory_state (
                  league TEXT NOT NULL,
                  directory_url TEXT NOT NULL,
                  final_url TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL DEFAULT '',
                  error TEXT NOT NULL DEFAULT '',
                  link_count INTEGER NOT NULL DEFAULT 0,
                  last_checked_at REAL NOT NULL DEFAULT 0,
                  last_success_at REAL NOT NULL DEFAULT 0,
                  PRIMARY KEY(league,directory_url)
                );
                """
            )
            conn.commit()

    # v6.1.12 generated league slugs. R23 deliberately uses only provider-supplied
    # URLs here; league discovery comes from the authoritative directory resolver.
    def _candidate_web_urls(self, entity: dict) -> list[str]:
        league_hosts = LEAGUE_HOSTS.get(str(entity.get("league") or "").upper(), set())
        urls = []
        for url in entity.get("metadataUrls") or []:
            host = _host(url)
            if not host or host in BLOCKED_METADATA_HOSTS:
                continue
            urls.append(url)
        return sorted(
            dict.fromkeys(urls),
            key=lambda url: (0 if _host(url) in league_hosts else 1, len(url), url),
        )[: self.max_web_pages]

    def _identity_score(self, entity: dict, *values: object) -> float:
        hay = _identity_norm(" ".join(str(v or "") for v in values))
        if not hay:
            return 0.0
        hay_tokens = set(hay.split())
        best = 0.0
        for alias in _team_aliases(entity):
            alias_norm = _identity_norm(alias)
            if not alias_norm:
                continue
            alias_tokens = _identity_tokens(alias)
            if len(alias_norm) >= 4 and re.search(
                r"(^|\s)" + re.escape(alias_norm) + r"(\s|$)", hay
            ):
                best = max(best, 1.0)
                continue
            # Four-character abbreviations like LAFC are useful exact identifiers,
            # while shorter abbreviations are too collision-prone for authority.
            compact = alias_norm.replace(" ", "")
            if len(compact) >= 4 and compact in hay.replace(" ", ""):
                best = max(best, 0.96)
            if not alias_tokens:
                continue
            overlap = len(alias_tokens & hay_tokens) / float(len(alias_tokens))
            if len(alias_tokens) == 1:
                if overlap == 1:
                    best = max(best, 0.95)
            elif overlap == 1:
                best = max(best, 0.97)
            elif len(alias_tokens) >= 3 and overlap >= 0.75:
                best = max(best, 0.90)
        return best

    def _extract_links(self, page: str, base_url: str) -> list[dict]:
        out = []
        seen = set()
        page = str(page or "")
        for match in ANCHOR_RE.finditer(page):
            href = _decode_link(match.group("href"))
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            url = urljoin(base_url, href)
            if not url.startswith(("http://", "https://")):
                continue
            attrs = (match.group("attrs") or "") + " " + (match.group("tail") or "")
            labels = ATTR_LABEL_RE.findall(attrs)
            label = _text(" ".join(labels + [match.group("body") or ""]))
            left = max(0, match.start() - 260)
            right = min(len(page), match.end() + 120)
            context = _text(page[left:right])
            key = (url, label)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "url": url,
                    "label": label,
                    "context": context[:1000],
                    "host": _host(url),
                }
            )
        # Modern league sites often hydrate navigation from JSON. Capture URL-like
        # fields as a fallback; surrounding JSON remains useful identity evidence.
        for match in JSON_LINK_RE.finditer(page):
            href = _decode_link(match.group(1))
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            url = urljoin(base_url, href)
            if not url.startswith(("http://", "https://")):
                continue
            key = (url, "")
            if key in seen:
                continue
            seen.add(key)
            left = max(0, match.start() - 350)
            right = min(len(page), match.end() + 200)
            out.append(
                {
                    "url": url,
                    "label": "",
                    "context": _text(page[left:right])[:1000],
                    "host": _host(url),
                }
            )
        return out[: self.directory_link_limit]

    def _directory_state(self, league: str, directory_url: str) -> dict:
        with closing(self.connect()) as conn:
            row = conn.execute(
                "SELECT * FROM league_directory_state WHERE league=? AND directory_url=?",
                (league, directory_url),
            ).fetchone()
        return dict(row) if row else {}

    def _cached_directory_links(self, league: str, directory_url: str) -> list[dict]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM league_directory_link WHERE league=? AND directory_url=? ORDER BY link_url,link_text",
                (league, directory_url),
            ).fetchall()
        return [dict(row) for row in rows]

    def _record_directory_failure(self, league: str, directory_url: str, exc: Exception):
        now = time.time()
        with self.lock, closing(self.connect()) as conn:
            prior = conn.execute(
                "SELECT last_success_at,link_count,final_url FROM league_directory_state WHERE league=? AND directory_url=?",
                (league, directory_url),
            ).fetchone()
            conn.execute(
                """INSERT INTO league_directory_state(
                       league,directory_url,final_url,status,error,link_count,last_checked_at,last_success_at
                   ) VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(league,directory_url) DO UPDATE SET
                     status=excluded.status,error=excluded.error,last_checked_at=excluded.last_checked_at""",
                (
                    league,
                    directory_url,
                    str(prior["final_url"] if prior else ""),
                    "ERROR",
                    f"{type(exc).__name__}: {exc}"[:500],
                    int(prior["link_count"] if prior else 0),
                    now,
                    float(prior["last_success_at"] if prior else 0),
                ),
            )
            conn.commit()

    def _refresh_directory(self, league: str, directory_url: str) -> dict:
        state = self._directory_state(league, directory_url)
        now = time.time()
        last_success = float(state.get("last_success_at") or 0)
        last_checked = float(state.get("last_checked_at") or 0)
        cached = self._cached_directory_links(league, directory_url)
        if cached and last_success >= now - self.directory_refresh_seconds:
            return {"links": cached, "cacheHit": True, "fetched": False, "error": ""}
        if (
            not cached
            and state.get("status") == "ERROR"
            and last_checked >= now - self.directory_failure_retry_seconds
        ):
            return {
                "links": [],
                "cacheHit": True,
                "fetched": False,
                "error": str(state.get("error") or ""),
            }
        try:
            page, final_url = self._fetch_html(directory_url)
            links = self._extract_links(page, final_url or directory_url)
            if not links:
                raise ValueError("directory returned no resolvable links")
        except Exception as exc:
            self._record_directory_failure(league, directory_url, exc)
            return {
                "links": cached,
                "cacheHit": bool(cached),
                "fetched": True,
                "error": f"{type(exc).__name__}: {exc}",
            }
        now = time.time()
        with self.lock, closing(self.connect()) as conn:
            conn.execute(
                "DELETE FROM league_directory_link WHERE league=? AND directory_url=?",
                (league, directory_url),
            )
            for row in links:
                conn.execute(
                    """INSERT OR REPLACE INTO league_directory_link(
                         league,directory_url,link_url,link_text,context_text,link_host,refreshed_at
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (
                        league,
                        directory_url,
                        row.get("url") or "",
                        row.get("label") or "",
                        row.get("context") or "",
                        row.get("host") or "",
                        now,
                    ),
                )
            conn.execute(
                """INSERT INTO league_directory_state(
                     league,directory_url,final_url,status,error,link_count,last_checked_at,last_success_at
                   ) VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(league,directory_url) DO UPDATE SET
                     final_url=excluded.final_url,status=excluded.status,error='',
                     link_count=excluded.link_count,last_checked_at=excluded.last_checked_at,
                     last_success_at=excluded.last_success_at""",
                (
                    league,
                    directory_url,
                    final_url or directory_url,
                    "OK",
                    "",
                    len(links),
                    now,
                    now,
                ),
            )
            conn.commit()
        return {
            "links": self._cached_directory_links(league, directory_url),
            "cacheHit": False,
            "fetched": True,
            "error": "",
        }

    def _directory_links(self, entity: dict) -> tuple[list[dict], dict]:
        league = str(entity.get("league") or "").upper()
        telemetry = {
            "directoryFetches": 0,
            "directoryCacheHits": 0,
            "directoryErrors": 0,
            "directoryLinks": 0,
        }
        rows = []
        for directory_url in LEAGUE_DIRECTORY_URLS.get(league, ()):
            result = self._refresh_directory(league, directory_url)
            if result.get("fetched"):
                telemetry["directoryFetches"] += 1
            if result.get("cacheHit"):
                telemetry["directoryCacheHits"] += 1
            if result.get("error"):
                telemetry["directoryErrors"] += 1
            for row in result.get("links") or []:
                if isinstance(row, dict):
                    rows.append(row)
        telemetry["directoryLinks"] = len(rows)
        return rows, telemetry

    def _directory_resolution_fresh(self, entity_key: str) -> bool:
        cutoff = time.time() - self.refresh_seconds
        with closing(self.connect()) as conn:
            row = conn.execute(
                """SELECT MAX(last_checked_at) t FROM team_source
                   WHERE entity_key=? AND verified_at>0 AND
                         (source_type='OFFICIAL_LEAGUE_TEAM_PAGE'
                          OR evidence LIKE 'League directory referral:%')""",
                (entity_key,),
            ).fetchone()
        return bool(row and float(row["t"] or 0) >= cutoff)

    def _verified_url_fresh(self, entity_key: str, source_type: str, url: str) -> bool:
        cutoff = time.time() - self.refresh_seconds
        with closing(self.connect()) as conn:
            row = conn.execute(
                """SELECT MAX(last_checked_at) t FROM team_source
                   WHERE entity_key=? AND source_type=? AND url=? AND verified_at>0""",
                (entity_key, source_type, url),
            ).fetchone()
        return bool(row and float(row["t"] or 0) >= cutoff)

    def _looks_like_official_site(self, entity: dict, row: dict) -> bool:
        label = _norm(row.get("label") or "")
        url = str(row.get("url") or "")
        host = row.get("host") or _host(url)
        if not host or host in BLOCKED_METADATA_HOSTS or _is_youtube_host(host):
            return False
        if any(hint in label for hint in NON_SITE_HINTS):
            return False
        if any(hint in label for hint in OFFICIAL_SITE_HINTS):
            return True
        # Some authoritative directories (notably MLB) render the club domain as
        # the link label instead of "Official Site".
        visible_host = host[4:] if host.startswith("www.") else host
        raw_label = _text(row.get("label") or "").lower().strip()
        raw_label = re.sub(r"^https?://", "", raw_label).rstrip("/")
        if raw_label and raw_label in {visible_host, "www." + visible_host}:
            return True
        # A domain/path that itself carries a strong team identity is acceptable
        # when the surrounding authoritative directory context already matched.
        return self._identity_score(entity, host, url) >= 0.96

    def _register_youtube_links(self, entity: dict, page: str, page_url: str, youtube, api_key: str, evidence: str) -> int:
        found = 0
        refs = []
        refs.extend(match.group(0) for match in YOUTUBE_CHANNEL_RE.finditer(page or ""))
        for row in self._extract_links(page, page_url):
            if YOUTUBE_CHANNEL_RE.search(str(row.get("url") or "")):
                refs.append(str(row.get("url") or ""))
        for ref in dict.fromkeys(html_lib.unescape(x) for x in refs if x):
            channel_id, channel_name = self._resolve_channel(ref, youtube, api_key)
            if not channel_id:
                continue
            self._upsert_source(
                entity,
                "OFFICIAL_TEAM_YOUTUBE",
                channel_id,
                url=ref,
                channel_id=channel_id,
                channel_name=channel_name,
                trust_state="VERIFIED_AUTHORITATIVE_LINK",
                evidence=evidence,
                checked=True,
                verified=True,
            )
            found += 1
        embedded_ids = list(dict.fromkeys(YOUTUBE_VIDEO_RE.findall(page or "")))[:50]
        if embedded_ids and api_key:
            meta = self._video_metadata(embedded_ids, youtube, api_key)
            self._upsert_videos(entity["entityKey"], meta, "OFFICIAL_TEAM_WEB_EMBED")
        return found

    def _consume_official_site(
        self,
        entity: dict,
        site_url: str,
        youtube,
        api_key: str,
        *,
        evidence: str,
    ) -> dict:
        stats = {"officialSites": 0, "youtubeChannels": 0, "pagesChecked": 0}
        host = _host(site_url)
        if not host or host in BLOCKED_METADATA_HOSTS or _is_youtube_host(host):
            return stats
        if self._verified_url_fresh(entity["entityKey"], "OFFICIAL_TEAM_WEB", site_url):
            return stats
        self._upsert_source(
            entity,
            "OFFICIAL_TEAM_WEB",
            site_url,
            url=site_url,
            trust_state="VERIFIED_LEAGUE_REFERRAL",
            evidence=evidence,
            checked=True,
            verified=True,
        )
        stats["officialSites"] += 1
        try:
            page, final_url = self._fetch_html(site_url)
            stats["pagesChecked"] += 1
        except Exception:
            return stats
        final_host = _host(final_url)
        if not final_host or final_host in BLOCKED_METADATA_HOSTS:
            return stats
        identity = self._page_identity_text(page)
        score = self._identity_score(entity, identity, final_url)
        trust = "VERIFIED_LEAGUE_REFERRAL"
        if score >= 0.90:
            trust = "VERIFIED_LEAGUE_REFERRAL_AND_PAGE_IDENTITY"
        self._upsert_source(
            entity,
            "OFFICIAL_TEAM_WEB",
            final_url,
            url=final_url,
            trust_state=trust,
            evidence=(evidence + f"; pageIdentityScore={score:.2f}")[:1000],
            checked=True,
            verified=True,
        )
        stats["youtubeChannels"] += self._register_youtube_links(
            entity,
            page,
            final_url,
            youtube,
            api_key,
            f"Linked from verified official team site {final_url}",
        )
        return stats

    def _consume_league_team_page(
        self,
        entity: dict,
        team_url: str,
        directory_row: dict,
        youtube,
        api_key: str,
    ) -> dict:
        stats = {
            "leaguePagesResolved": 0,
            "officialSites": 0,
            "youtubeChannels": 0,
            "pagesChecked": 0,
        }
        evidence = (
            "League directory referral: "
            + str(directory_row.get("directory_url") or "")
            + " | "
            + str(directory_row.get("link_text") or directory_row.get("context_text") or "")[:300]
        )
        try:
            page, final_url = self._fetch_html(team_url)
            stats["pagesChecked"] += 1
        except Exception as exc:
            # The directory identity itself is authoritative enough to remember the
            # resolved league team URL, even if the detail page is temporarily down.
            self._upsert_source(
                entity,
                "OFFICIAL_LEAGUE_TEAM_PAGE",
                team_url,
                url=team_url,
                trust_state="VERIFIED_DIRECTORY_LINK_UNREACHABLE",
                evidence=(evidence + f"; {type(exc).__name__}")[:1000],
                checked=True,
                verified=True,
            )
            stats["leaguePagesResolved"] += 1
            return stats

        identity = self._page_identity_text(page)
        score = self._identity_score(
            entity,
            identity,
            final_url,
            directory_row.get("link_text") or "",
            directory_row.get("context_text") or "",
        )
        if score < 0.90:
            self._upsert_source(
                entity,
                "OFFICIAL_LEAGUE_TEAM_PAGE",
                final_url,
                url=final_url,
                trust_state="DIRECTORY_IDENTITY_MISMATCH",
                evidence=(evidence + f"; pageIdentityScore={score:.2f}")[:1000],
                checked=True,
            )
            return stats

        self._upsert_source(
            entity,
            "OFFICIAL_LEAGUE_TEAM_PAGE",
            final_url,
            url=final_url,
            trust_state="VERIFIED_DIRECTORY_TEAM_PAGE",
            evidence=(evidence + f"; pageIdentityScore={score:.2f}")[:1000],
            checked=True,
            verified=True,
        )
        stats["leaguePagesResolved"] += 1
        stats["youtubeChannels"] += self._register_youtube_links(
            entity,
            page,
            final_url,
            youtube,
            api_key,
            f"Linked from verified league team page {final_url}",
        )

        league_hosts = LEAGUE_HOSTS.get(str(entity.get("league") or "").upper(), set())
        external = []
        for row in self._extract_links(page, final_url):
            host = row.get("host") or _host(row.get("url") or "")
            if not host or host in league_hosts or host in BLOCKED_METADATA_HOSTS or _is_youtube_host(host):
                continue
            row_score = self._identity_score(
                entity,
                row.get("label") or "",
                row.get("context") or "",
                row.get("url") or "",
            )
            if row_score < 0.90:
                continue
            if not self._looks_like_official_site(entity, row):
                continue
            external.append((row_score, row))
        for _, row in sorted(external, key=lambda item: (-item[0], len(str(item[1].get("url") or ""))))[:2]:
            sub = self._consume_official_site(
                entity,
                str(row.get("url") or ""),
                youtube,
                api_key,
                evidence=f"League directory referral: verified team page {final_url}",
            )
            for key in ("officialSites", "youtubeChannels", "pagesChecked"):
                stats[key] += int(sub.get(key) or 0)
        return stats

    def _resolve_from_directory(self, entity: dict, youtube, api_key: str) -> dict:
        stats = {
            "directoryFetches": 0,
            "directoryCacheHits": 0,
            "directoryErrors": 0,
            "directoryLinks": 0,
            "leaguePagesResolved": 0,
            "officialSites": 0,
            "youtubeChannels": 0,
            "pagesChecked": 0,
        }
        rows, telemetry = self._directory_links(entity)
        for key, value in telemetry.items():
            stats[key] += int(value or 0)
        if not rows:
            return stats

        league = str(entity.get("league") or "").upper()
        league_hosts = LEAGUE_HOSTS.get(league, set())
        ranked = []
        for row in rows:
            score = self._identity_score(
                entity,
                row.get("link_text") or "",
                row.get("context_text") or "",
                row.get("link_url") or "",
            )
            if score < 0.90:
                continue
            url = str(row.get("link_url") or "")
            host = row.get("link_host") or _host(url)
            if not host:
                continue
            ranked.append((score, 0 if host in league_hosts else 1, row))
        # Examine only the strongest directory matches. This prevents a team card
        # from pulling unrelated sponsor/navigation links into the trusted graph.
        league_page_resolved = False
        for score, _, row in sorted(
            ranked,
            key=lambda item: (-item[0], item[1], len(str(item[2].get("link_url") or ""))),
        )[:8]:
            url = str(row.get("link_url") or "")
            host = row.get("link_host") or _host(url)
            if _is_youtube_host(host) and YOUTUBE_CHANNEL_RE.search(url):
                channel_id, channel_name = self._resolve_channel(url, youtube, api_key)
                if channel_id:
                    self._upsert_source(
                        entity,
                        "OFFICIAL_TEAM_YOUTUBE",
                        channel_id,
                        url=url,
                        channel_id=channel_id,
                        channel_name=channel_name,
                        trust_state="VERIFIED_LEAGUE_DIRECTORY_SOCIAL",
                        evidence=f"League directory referral: {row.get('directory_url') or ''}",
                        checked=True,
                        verified=True,
                    )
                    stats["youtubeChannels"] += 1
                continue
            if host in league_hosts:
                if url.rstrip("/") == str(row.get("directory_url") or "").rstrip("/"):
                    continue
                if league_page_resolved:
                    continue
                sub = self._consume_league_team_page(entity, url, row, youtube, api_key)
                for key in ("leaguePagesResolved", "officialSites", "youtubeChannels", "pagesChecked"):
                    stats[key] += int(sub.get(key) or 0)
                if sub.get("leaguePagesResolved"):
                    league_page_resolved = True
                continue
            directory_view = {
                "url": url,
                "label": row.get("link_text") or "",
                "context": row.get("context_text") or "",
                "host": host,
            }
            if not self._looks_like_official_site(entity, directory_view):
                continue
            sub = self._consume_official_site(
                entity,
                url,
                youtube,
                api_key,
                evidence=(
                    "League directory referral: "
                    + str(row.get("directory_url") or "")
                    + f"; identityScore={score:.2f}"
                ),
            )
            for key in ("officialSites", "youtubeChannels", "pagesChecked"):
                stats[key] += int(sub.get(key) or 0)
            if sub.get("officialSites"):
                break
        return stats

    def _resolve_provider_metadata(self, entity: dict, youtube, api_key: str) -> dict:
        stats = {"providerMetadataPages": 0, "officialSites": 0, "youtubeChannels": 0}
        for url in self._candidate_web_urls(entity):
            try:
                page, final_url = self._fetch_html(url)
                stats["providerMetadataPages"] += 1
            except Exception:
                continue
            identity = self._page_identity_text(page)
            score = self._identity_score(entity, identity, final_url)
            if score < 0.95:
                continue
            self._upsert_source(
                entity,
                "OFFICIAL_TEAM_WEB",
                final_url,
                url=final_url,
                trust_state="VERIFIED_PROVIDER_METADATA_IDENTITY",
                evidence=f"Provider metadata URL with page identity score {score:.2f}",
                checked=True,
                verified=True,
            )
            stats["officialSites"] += 1
            stats["youtubeChannels"] += self._register_youtube_links(
                entity,
                page,
                final_url,
                youtube,
                api_key,
                f"Linked from provider-supplied verified team page {final_url}",
            )
            break
        return stats

    def refresh_event_sources(self, context: dict, youtube, api_key: str, stop_event=None) -> dict:
        summary = {
            "teams": [],
            "pagesChecked": 0,
            "verifiedWeb": 0,
            "youtubeChannels": 0,
            "trustedIndexLearned": 0,
            "indexedVideos": 0,
            "directoryFetches": 0,
            "directoryCacheHits": 0,
            "directoryErrors": 0,
            "directoryLinks": 0,
            "leaguePagesResolved": 0,
            "officialSites": 0,
            "providerMetadataPages": 0,
        }
        for entity in self.entities(context):
            if stop_event is not None and stop_event.is_set():
                break
            team_stats = {
                "entityKey": entity["entityKey"],
                "team": entity["teamName"],
                "side": entity["side"],
                "pagesChecked": 0,
                "verifiedWeb": 0,
                "youtubeChannels": 0,
                "indexedVideos": 0,
                "directoryFetches": 0,
                "directoryCacheHits": 0,
                "directoryErrors": 0,
                "directoryLinks": 0,
                "leaguePagesResolved": 0,
                "officialSites": 0,
                "providerMetadataPages": 0,
            }
            learned = self._learn_trusted_index_channels(entity)
            summary["trustedIndexLearned"] += learned

            if not self._directory_resolution_fresh(entity["entityKey"]):
                resolved = self._resolve_from_directory(entity, youtube, api_key)
                if not (
                    resolved.get("leaguePagesResolved")
                    or resolved.get("officialSites")
                ):
                    fallback = self._resolve_provider_metadata(entity, youtube, api_key)
                    for key, value in fallback.items():
                        resolved[key] = int(resolved.get(key) or 0) + int(value or 0)
                for key in (
                    "pagesChecked",
                    "youtubeChannels",
                    "directoryFetches",
                    "directoryCacheHits",
                    "directoryErrors",
                    "directoryLinks",
                    "leaguePagesResolved",
                    "officialSites",
                    "providerMetadataPages",
                ):
                    team_stats[key] += int(resolved.get(key) or 0)

            channels = self._verified_channels(entity["entityKey"])
            team_stats["youtubeChannels"] = max(team_stats["youtubeChannels"], len(channels))
            for source in channels:
                indexed = self._index_channel(entity, source, youtube, api_key, stop_event=stop_event)
                team_stats["indexedVideos"] += indexed

            team_stats["verifiedWeb"] = (
                team_stats["leaguePagesResolved"] + team_stats["officialSites"]
            )
            for key in (
                "pagesChecked",
                "verifiedWeb",
                "youtubeChannels",
                "indexedVideos",
                "directoryFetches",
                "directoryCacheHits",
                "directoryErrors",
                "directoryLinks",
                "leaguePagesResolved",
                "officialSites",
                "providerMetadataPages",
            ):
                summary[key] += int(team_stats.get(key) or 0)
            summary["teams"].append(team_stats)
        return summary

    def snapshot(self) -> dict:
        base = super().snapshot()
        base["generation"] = GENERATION
        try:
            with closing(self.connect()) as conn:
                directory_links = int(
                    conn.execute("SELECT COUNT(*) FROM league_directory_link").fetchone()[0] or 0
                )
                directory_leagues = int(
                    conn.execute(
                        "SELECT COUNT(DISTINCT league) FROM league_directory_state WHERE last_success_at>0"
                    ).fetchone()[0]
                    or 0
                )
                directory_errors = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM league_directory_state WHERE status='ERROR'"
                    ).fetchone()[0]
                    or 0
                )
                league_pages = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM team_source WHERE source_type='OFFICIAL_LEAGUE_TEAM_PAGE' AND verified_at>0"
                    ).fetchone()[0]
                    or 0
                )
                official_sites = int(
                    conn.execute(
                        """SELECT COUNT(*) FROM team_source
                           WHERE source_type='OFFICIAL_TEAM_WEB' AND verified_at>0
                             AND evidence LIKE 'League directory referral:%'"""
                    ).fetchone()[0]
                    or 0
                )
            base.update(
                {
                    "directoryLinks": directory_links,
                    "directoryLeagues": directory_leagues,
                    "directoryErrors": directory_errors,
                    "leagueTeamPages": league_pages,
                    "leagueReferredOfficialSites": official_sites,
                }
            )
        except Exception as exc:
            base["directorySnapshotError"] = f"{type(exc).__name__}: {exc}"
        return base

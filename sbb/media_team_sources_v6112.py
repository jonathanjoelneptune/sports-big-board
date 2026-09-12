"""Persistent official team-source registry for Media Repair.

The registry is intentionally separate from the canonical history SQLite file.  It
learns/validates team-specific web pages and YouTube channels once, indexes bounded
channel uploads without search.list, and returns only strict two-participant matches
for the existing Media Repair certification path.
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

GENERATION = "R22-OFFICIAL-TEAM-SOURCES"
DEFAULT_REFRESH_SECONDS = 7 * 24 * 3600
DEFAULT_INDEX_REFRESH_SECONDS = 24 * 3600
DEFAULT_INDEX_PAGES = 2
DEFAULT_PAGE_TIMEOUT = 12
DEFAULT_MAX_WEB_PAGES = 4

BLOCKED_METADATA_HOSTS = {
    "espn.com", "www.espn.com", "google.com", "www.google.com", "youtube.com",
    "www.youtube.com", "youtu.be", "facebook.com", "www.facebook.com", "instagram.com",
    "www.instagram.com", "twitter.com", "www.twitter.com", "x.com", "www.x.com",
    "wikipedia.org", "www.wikipedia.org",
}

LEAGUE_WEB_TEMPLATES = {
    "MLB": (
        "https://www.mlb.com/{slug}",
        "https://www.mlb.com/{nickname}",
    ),
    "NBA": (
        "https://www.nba.com/{slug}",
        "https://www.nba.com/{nickname}",
    ),
    "NHL": (
        "https://www.nhl.com/{slug}",
        "https://www.nhl.com/{nickname}",
    ),
    "NFL": (
        "https://www.nfl.com/teams/{slug}/",
        "https://www.nfl.com/teams/{nickname}/",
    ),
    "MLS": (
        "https://www.mlssoccer.com/clubs/{slug}/",
        "https://www.mlssoccer.com/clubs/{nickname}/",
    ),
    "EPL": (
        "https://www.premierleague.com/clubs/{slug}/overview",
        "https://www.premierleague.com/clubs/{nickname}/overview",
    ),
    "NCAAF": (
        "https://www.ncaa.com/schools/{slug}",
        "https://www.ncaa.com/schools/{nickname}",
    ),
}

LEAGUE_HOSTS = {
    "MLB": {"mlb.com", "www.mlb.com"},
    "NBA": {"nba.com", "www.nba.com"},
    "NHL": {"nhl.com", "www.nhl.com"},
    "NFL": {"nfl.com", "www.nfl.com"},
    "MLS": {"mlssoccer.com", "www.mlssoccer.com"},
    "EPL": {"premierleague.com", "www.premierleague.com"},
    "NCAAF": {"ncaa.com", "www.ncaa.com"},
}

STOP_TOKENS = {
    "the", "fc", "cf", "club", "team", "united", "city", "state", "university",
    "college", "football", "basketball", "baseball", "hockey", "soccer",
}

YOUTUBE_CHANNEL_RE = re.compile(
    r"https?://(?:www\.)?youtube\.com/(?:channel/(?P<channel>UC[A-Za-z0-9_-]{18,32})|@(?P<handle>[A-Za-z0-9._-]+)|user/(?P<user>[A-Za-z0-9._-]+)|c/(?P<custom>[A-Za-z0-9._-]+))",
    re.I,
)
YOUTUBE_VIDEO_RE = re.compile(
    r"(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?(?:[^\"'<> ]*&)?v=)|youtu\.be/)([A-Za-z0-9_-]{6,20})",
    re.I,
)
URL_RE = re.compile(r"https?://[^\"'<>\s)]+", re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
META_RE = re.compile(r"<meta[^>]+(?:name|property)=[\"'](?:description|og:title|og:description)[\"'][^>]+content=[\"'](.*?)[\"']", re.I | re.S)
CHANNEL_ID_PAGE_RE = re.compile(r'[\"\']channelId[\"\']\s*:\s*[\"\'](UC[A-Za-z0-9_-]{18,32})[\"\']')


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _slug(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def _loads(value: object, default):
    try:
        return json.loads(value) if isinstance(value, str) else (value if value is not None else default)
    except Exception:
        return default


def _iso_duration_seconds(value: object) -> float:
    text = str(value or "")
    m = re.fullmatch(r"P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", text)
    if not m:
        return 0.0
    return float(m.group(1) or 0) * 3600 + float(m.group(2) or 0) * 60 + float(m.group(3) or 0)


def _tier(title: str, duration: float) -> str:
    low = _norm(title)
    if "full game highlights" in low or "extended highlights" in low or duration >= 300:
        return "extended"
    if ("highlight" in low or "recap" in low) and duration >= 60:
        return "green"
    return "blue"


def _team_name(event: dict, side: str) -> str:
    raw = (event or {}).get(side)
    if isinstance(raw, dict):
        for key in ("displayName", "name", "shortName", "teamName", "label"):
            if raw.get(key):
                return str(raw.get(key))
    return str(raw or "")


def _significant_tokens(name: str) -> list[str]:
    return [t for t in _norm(name).split() if len(t) >= 3 and t not in STOP_TOKENS]


def _strong_name_match(team_name: str, haystack: str) -> bool:
    team = _norm(team_name)
    text = _norm(haystack)
    if not team or not text:
        return False
    if team in text:
        return True
    tokens = _significant_tokens(team_name)
    if not tokens:
        return False
    if len(tokens) == 1:
        return tokens[0] in text.split()
    hits = sum(1 for t in tokens if re.search(r"(^|\s)" + re.escape(t) + r"(\s|$)", text))
    return hits >= 2 and tokens[-1] in text.split()


def _extract_team_urls(raw: object) -> list[str]:
    out: list[str] = []
    stack = [raw]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                key_low = str(key).lower()
                if isinstance(child, str) and child.startswith(("http://", "https://")):
                    if any(token in key_low for token in ("url", "href", "link", "website", "site")):
                        out.append(child)
                elif isinstance(child, (dict, list, tuple)):
                    stack.append(child)
        elif isinstance(value, (list, tuple)):
            stack.extend(value)
    return list(dict.fromkeys(out))


class TeamSourceRegistry:
    """Owns persistent team-source identities and bounded team-channel media indexes."""

    def __init__(
        self,
        store,
        state_file: Path,
        *,
        user_agent: str = "SportsBigBoard-TeamSources/1",
        refresh_seconds: float | None = None,
        index_refresh_seconds: float | None = None,
        index_pages: int | None = None,
        page_timeout: int | None = None,
        max_web_pages: int | None = None,
    ):
        self.store = store
        self.path = Path(state_file)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.user_agent = str(user_agent or "SportsBigBoard-TeamSources/1")
        self.refresh_seconds = float(refresh_seconds or os.environ.get("SBB_MEDIA_TEAM_SOURCE_REFRESH_SECONDS", DEFAULT_REFRESH_SECONDS))
        self.index_refresh_seconds = float(index_refresh_seconds or os.environ.get("SBB_MEDIA_TEAM_INDEX_REFRESH_SECONDS", DEFAULT_INDEX_REFRESH_SECONDS))
        self.index_pages = max(1, min(5, int(index_pages or os.environ.get("SBB_MEDIA_TEAM_INDEX_PAGES", DEFAULT_INDEX_PAGES))))
        self.page_timeout = max(5, min(30, int(page_timeout or os.environ.get("SBB_MEDIA_TEAM_PAGE_TIMEOUT", DEFAULT_PAGE_TIMEOUT))))
        self.max_web_pages = max(1, min(8, int(max_web_pages or os.environ.get("SBB_MEDIA_TEAM_MAX_WEB_PAGES", DEFAULT_MAX_WEB_PAGES))))
        self.lock = threading.RLock()
        self._ensure_schema()

    def connect(self):
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _ensure_schema(self):
        with self.lock, closing(self.connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS team_source (
                  entity_key TEXT NOT NULL,
                  league TEXT NOT NULL DEFAULT '', side TEXT NOT NULL DEFAULT '',
                  team_id TEXT NOT NULL DEFAULT '', team_name TEXT NOT NULL DEFAULT '',
                  source_type TEXT NOT NULL, source_key TEXT NOT NULL,
                  url TEXT NOT NULL DEFAULT '', channel_id TEXT NOT NULL DEFAULT '',
                  channel_name TEXT NOT NULL DEFAULT '', trust_state TEXT NOT NULL DEFAULT 'DISCOVERED',
                  evidence TEXT NOT NULL DEFAULT '', discovered_at REAL NOT NULL DEFAULT 0,
                  verified_at REAL NOT NULL DEFAULT 0, last_checked_at REAL NOT NULL DEFAULT 0,
                  last_indexed_at REAL NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL DEFAULT '{}',
                  PRIMARY KEY(entity_key,source_type,source_key)
                );
                CREATE INDEX IF NOT EXISTS idx_team_source_channel ON team_source(channel_id,trust_state);
                CREATE TABLE IF NOT EXISTS team_source_video (
                  entity_key TEXT NOT NULL, video_id TEXT NOT NULL,
                  channel_id TEXT NOT NULL DEFAULT '', channel_name TEXT NOT NULL DEFAULT '',
                  title TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
                  published_at TEXT NOT NULL DEFAULT '', duration_seconds REAL NOT NULL DEFAULT 0,
                  playlist_id TEXT NOT NULL DEFAULT '', source_type TEXT NOT NULL DEFAULT '',
                  indexed_at REAL NOT NULL DEFAULT 0, details_json TEXT NOT NULL DEFAULT '{}',
                  PRIMARY KEY(entity_key,video_id)
                );
                CREATE INDEX IF NOT EXISTS idx_team_source_video_date ON team_source_video(entity_key,published_at);
                """
            )
            conn.commit()

    def entities(self, context: dict) -> list[dict]:
        event = dict((context or {}).get("event") or {})
        league = str((context or {}).get("league") or event.get("league") or "").upper()
        rows = []
        # Home first: team-owned recaps often describe the game from the home team's page.
        for side in ("home", "away"):
            raw = event.get(side)
            name = _team_name(event, side)
            if not name or "TBD" in name.upper():
                continue
            data = raw if isinstance(raw, dict) else {}
            team_id = str(data.get("id") or data.get("teamId") or data.get("uid") or data.get("abbreviation") or "")
            raw_slug = str(data.get("slug") or "")
            slug = _slug(raw_slug or name)
            tokens = _significant_tokens(name)
            nickname = "-".join(tokens[-2:] if len(tokens) >= 2 and tokens[-1] in {"sox", "jays", "wings", "leafs", "blazers"} else tokens[-1:])
            nickname = nickname or slug
            key = f"{league}:{team_id or slug}"
            rows.append({
                "entityKey": key, "league": league, "side": side, "teamId": team_id,
                "teamName": name, "slug": slug, "nickname": nickname,
                "raw": data, "metadataUrls": _extract_team_urls(data),
            })
        return rows

    def _candidate_web_urls(self, entity: dict) -> list[str]:
        league = str(entity.get("league") or "").upper()
        team_name = str(entity.get("teamName") or "")
        allowed_hosts = LEAGUE_HOSTS.get(league, set())
        urls: list[str] = []
        for url in entity.get("metadataUrls") or []:
            try:
                host = (urlparse(url).hostname or "").lower()
            except Exception:
                continue
            if not host or host in BLOCKED_METADATA_HOSTS:
                continue
            # Nested team metadata is accepted when it points to a non-aggregator
            # domain; page content must still strongly identify the team below.
            urls.append(url)
        for template in LEAGUE_WEB_TEMPLATES.get(league, ()):
            for slug in (entity.get("slug"), entity.get("nickname")):
                if not slug:
                    continue
                urls.append(template.format(slug=slug, nickname=slug))
        # Prefer known league/team domains before arbitrary metadata URLs.
        def rank(url: str):
            host = (urlparse(url).hostname or "").lower()
            return (0 if host in allowed_hosts else 1, len(url), url)
        return sorted(dict.fromkeys(urls), key=rank)[: self.max_web_pages]

    def _fetch_html(self, url: str) -> tuple[str, str]:
        req = Request(url, headers={"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml"})
        with urlopen(req, timeout=self.page_timeout) as resp:
            content_type = str(resp.headers.get("Content-Type") or "").lower()
            if "html" not in content_type and "text" not in content_type:
                return "", str(resp.geturl() or url)
            raw = resp.read(2_000_000)
            charset = "utf-8"
            m = re.search(r"charset=([A-Za-z0-9._-]+)", content_type)
            if m:
                charset = m.group(1)
            return raw.decode(charset, errors="replace"), str(resp.geturl() or url)

    @staticmethod
    def _page_identity_text(html: str) -> str:
        values = []
        m = TITLE_RE.search(html or "")
        if m:
            values.append(html_lib.unescape(re.sub(r"<[^>]+>", " ", m.group(1))))
        for meta in META_RE.findall(html or "")[:8]:
            values.append(html_lib.unescape(re.sub(r"<[^>]+>", " ", meta)))
        return " ".join(values)

    def _upsert_source(self, entity: dict, source_type: str, source_key: str, *, url="", channel_id="", channel_name="", trust_state="DISCOVERED", evidence="", checked=False, verified=False, indexed_at=0, metadata=None):
        now = time.time()
        with self.lock, closing(self.connect()) as conn:
            conn.execute(
                """INSERT INTO team_source(entity_key,league,side,team_id,team_name,source_type,source_key,url,channel_id,channel_name,trust_state,evidence,discovered_at,verified_at,last_checked_at,last_indexed_at,metadata_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(entity_key,source_type,source_key) DO UPDATE SET
                     url=CASE WHEN excluded.url<>'' THEN excluded.url ELSE team_source.url END,
                     channel_id=CASE WHEN excluded.channel_id<>'' THEN excluded.channel_id ELSE team_source.channel_id END,
                     channel_name=CASE WHEN excluded.channel_name<>'' THEN excluded.channel_name ELSE team_source.channel_name END,
                     trust_state=excluded.trust_state,evidence=excluded.evidence,
                     verified_at=MAX(team_source.verified_at,excluded.verified_at),
                     last_checked_at=MAX(team_source.last_checked_at,excluded.last_checked_at),
                     last_indexed_at=MAX(team_source.last_indexed_at,excluded.last_indexed_at),metadata_json=excluded.metadata_json""",
                (
                    entity["entityKey"], entity.get("league") or "", entity.get("side") or "", entity.get("teamId") or "", entity.get("teamName") or "",
                    source_type, source_key, url, channel_id, channel_name, trust_state, evidence, now,
                    now if verified else 0, now if checked else 0, float(indexed_at or 0), json.dumps(metadata or {}, separators=(",", ":")),
                ),
            )
            conn.commit()

    def _source_fresh(self, entity_key: str) -> bool:
        cutoff = time.time() - self.refresh_seconds
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT MAX(last_checked_at) t FROM team_source WHERE entity_key=?", (entity_key,)).fetchone()
        return bool(row and float(row["t"] or 0) >= cutoff)

    def _learn_trusted_index_channels(self, entity: dict) -> int:
        learned = 0
        try:
            with closing(self.store.connect(timeout=3)) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT channel_id,channel_name FROM history_media_repair_youtube_index WHERE channel_id<>'' AND channel_name<>'' LIMIT 2000"
                ).fetchall()
        except Exception:
            return 0
        for row in rows:
            channel_id = str(row["channel_id"] or "")
            channel_name = str(row["channel_name"] or "")
            if not channel_id or not _strong_name_match(entity["teamName"], channel_name):
                continue
            self._upsert_source(
                entity, "OFFICIAL_TEAM_YOUTUBE", channel_id,
                channel_id=channel_id, channel_name=channel_name,
                trust_state="TRUSTED_INDEX_NAME_MATCH",
                evidence="Matched team identity inside the existing trusted official YouTube index",
                checked=True, verified=True,
            )
            learned += 1
        return learned

    def _resolve_channel(self, ref_url: str, youtube, api_key: str) -> tuple[str, str]:
        m = YOUTUBE_CHANNEL_RE.search(ref_url or "")
        if not m:
            return "", ""
        if m.group("channel"):
            return m.group("channel"), ""
        query_key = "forHandle" if m.group("handle") else ("forUsername" if m.group("user") else "")
        query_value = m.group("handle") or m.group("user") or ""
        if query_key and api_key:
            try:
                from urllib.parse import urlencode
                payload = youtube.fetch_json(
                    "https://www.googleapis.com/youtube/v3/channels?" + urlencode({"part": "id,snippet", query_key: query_value, "key": api_key}),
                    timeout=12,
                )
                row = (payload.get("items") or [None])[0] or {}
                return str(row.get("id") or ""), str((row.get("snippet") or {}).get("title") or "")
            except Exception:
                pass
        try:
            html, _ = self._fetch_html(ref_url)
            cm = CHANNEL_ID_PAGE_RE.search(html or "")
            if cm:
                return cm.group(1), ""
        except Exception:
            pass
        return "", ""

    def _video_metadata(self, ids: list[str], youtube, api_key: str) -> list[dict]:
        if not ids or not api_key:
            return []
        from urllib.parse import urlencode
        out = []
        for i in range(0, len(ids), 50):
            try:
                payload = youtube.fetch_json(
                    "https://www.googleapis.com/youtube/v3/videos?" + urlencode({"part": "snippet,contentDetails,status", "id": ",".join(ids[i:i+50]), "key": api_key}),
                    timeout=15,
                )
            except Exception:
                continue
            for row in payload.get("items") or []:
                status = row.get("status") or {}
                if status.get("privacyStatus") not in (None, "public") or status.get("embeddable") is False:
                    continue
                sn = row.get("snippet") or {}
                duration = _iso_duration_seconds((row.get("contentDetails") or {}).get("duration"))
                out.append({
                    "videoId": str(row.get("id") or ""), "channelId": str(sn.get("channelId") or ""),
                    "channelName": str(sn.get("channelTitle") or ""), "title": str(sn.get("title") or ""),
                    "description": str(sn.get("description") or ""), "publishedAt": str(sn.get("publishedAt") or ""),
                    "durationSeconds": duration,
                })
        return out

    def _upsert_videos(self, entity_key: str, videos: list[dict], source_type: str) -> int:
        now = time.time(); count = 0
        with self.lock, closing(self.connect()) as conn:
            for row in videos:
                vid = str(row.get("videoId") or "")
                if not vid:
                    continue
                conn.execute(
                    """INSERT INTO team_source_video(entity_key,video_id,channel_id,channel_name,title,description,published_at,duration_seconds,playlist_id,source_type,indexed_at,details_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(entity_key,video_id) DO UPDATE SET channel_id=excluded.channel_id,channel_name=excluded.channel_name,title=excluded.title,description=excluded.description,published_at=excluded.published_at,duration_seconds=excluded.duration_seconds,playlist_id=excluded.playlist_id,source_type=excluded.source_type,indexed_at=excluded.indexed_at,details_json=excluded.details_json""",
                    (
                        entity_key, vid, row.get("channelId") or "", row.get("channelName") or "", row.get("title") or "", row.get("description") or "",
                        row.get("publishedAt") or "", float(row.get("durationSeconds") or 0), row.get("playlistId") or "", source_type, now,
                        json.dumps({k: v for k, v in row.items() if k not in {"description"}}, separators=(",", ":")),
                    ),
                )
                count += 1
            conn.commit()
        return count

    def _index_channel(self, entity: dict, source: dict, youtube, api_key: str, stop_event=None) -> int:
        channel_id = str(source.get("channel_id") or "")
        if not channel_id or not api_key:
            return 0
        if float(source.get("last_indexed_at") or 0) >= time.time() - self.index_refresh_seconds:
            return 0
        from urllib.parse import urlencode
        try:
            payload = youtube.fetch_json(
                "https://www.googleapis.com/youtube/v3/channels?" + urlencode({"part": "contentDetails,snippet", "id": channel_id, "key": api_key}),
                timeout=15,
            )
            row = (payload.get("items") or [None])[0] or {}
            channel_name = str((row.get("snippet") or {}).get("title") or source.get("channel_name") or "")
            playlist_id = str((((row.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")) or "")
            if not playlist_id:
                return 0
        except Exception:
            return 0
        raw_videos = []
        token = ""
        for _ in range(self.index_pages):
            if stop_event is not None and stop_event.is_set():
                break
            params = {"part": "snippet,contentDetails", "playlistId": playlist_id, "maxResults": 50, "key": api_key}
            if token:
                params["pageToken"] = token
            try:
                payload = youtube.fetch_json("https://www.googleapis.com/youtube/v3/playlistItems?" + urlencode(params), timeout=15)
            except Exception:
                break
            for item in payload.get("items") or []:
                sn = item.get("snippet") or {}; cd = item.get("contentDetails") or {}
                vid = str(cd.get("videoId") or ((sn.get("resourceId") or {}).get("videoId")) or "")
                if vid:
                    raw_videos.append({"videoId": vid, "playlistId": playlist_id})
            token = str(payload.get("nextPageToken") or "")
            if not token:
                break
        ids = list(dict.fromkeys(str(v.get("videoId")) for v in raw_videos if v.get("videoId")))
        meta = self._video_metadata(ids, youtube, api_key)
        playlist_by_id = {str(v.get("videoId")): str(v.get("playlistId") or "") for v in raw_videos}
        for row in meta:
            row["playlistId"] = playlist_by_id.get(str(row.get("videoId")), playlist_id)
            row["channelId"] = row.get("channelId") or channel_id
            row["channelName"] = row.get("channelName") or channel_name
        indexed = self._upsert_videos(entity["entityKey"], meta, "OFFICIAL_TEAM_YOUTUBE")
        self._upsert_source(
            entity, "OFFICIAL_TEAM_YOUTUBE", channel_id, channel_id=channel_id, channel_name=channel_name,
            trust_state=str(source.get("trust_state") or "VERIFIED"), evidence=str(source.get("evidence") or ""),
            checked=True, verified=True, indexed_at=time.time(), metadata={"uploadsPlaylist": playlist_id, "indexedVideos": indexed},
        )
        return indexed

    def _verified_channels(self, entity_key: str) -> list[dict]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM team_source WHERE entity_key=? AND source_type='OFFICIAL_TEAM_YOUTUBE' AND channel_id<>'' AND verified_at>0 ORDER BY verified_at DESC",
                (entity_key,),
            ).fetchall()
        return [dict(r) for r in rows]

    def refresh_event_sources(self, context: dict, youtube, api_key: str, stop_event=None) -> dict:
        summary = {"teams": [], "pagesChecked": 0, "verifiedWeb": 0, "youtubeChannels": 0, "trustedIndexLearned": 0, "indexedVideos": 0}
        for entity in self.entities(context):
            team_stats = {"entityKey": entity["entityKey"], "team": entity["teamName"], "side": entity["side"], "pagesChecked": 0, "verifiedWeb": 0, "youtubeChannels": 0, "indexedVideos": 0}
            learned = self._learn_trusted_index_channels(entity)
            summary["trustedIndexLearned"] += learned
            if not self._source_fresh(entity["entityKey"]):
                for url in self._candidate_web_urls(entity):
                    if stop_event is not None and stop_event.is_set():
                        break
                    team_stats["pagesChecked"] += 1; summary["pagesChecked"] += 1
                    try:
                        page, final_url = self._fetch_html(url)
                    except Exception as exc:
                        self._upsert_source(entity, "OFFICIAL_TEAM_WEB", url, url=url, trust_state="UNREACHABLE", evidence=type(exc).__name__, checked=True)
                        continue
                    identity = self._page_identity_text(page)
                    if not _strong_name_match(entity["teamName"], identity):
                        self._upsert_source(entity, "OFFICIAL_TEAM_WEB", final_url, url=final_url, trust_state="IDENTITY_MISMATCH", evidence=identity[:300], checked=True)
                        continue
                    self._upsert_source(entity, "OFFICIAL_TEAM_WEB", final_url, url=final_url, trust_state="VERIFIED_TEAM_PAGE", evidence=identity[:500], checked=True, verified=True)
                    team_stats["verifiedWeb"] += 1; summary["verifiedWeb"] += 1
                    # A YouTube channel linked from a verified team page is our
                    # strongest automated channel identity evidence.
                    for match in YOUTUBE_CHANNEL_RE.finditer(page):
                        ref = html_lib.unescape(match.group(0))
                        channel_id, channel_name = self._resolve_channel(ref, youtube, api_key)
                        if not channel_id:
                            continue
                        self._upsert_source(
                            entity, "OFFICIAL_TEAM_YOUTUBE", channel_id, url=ref, channel_id=channel_id, channel_name=channel_name,
                            trust_state="VERIFIED_SOCIAL_LINK", evidence=f"Linked from verified team page {final_url}", checked=True, verified=True,
                        )
                    embedded_ids = list(dict.fromkeys(YOUTUBE_VIDEO_RE.findall(page or "")))[:50]
                    if embedded_ids and api_key:
                        embedded_meta = self._video_metadata(embedded_ids, youtube, api_key)
                        self._upsert_videos(entity["entityKey"], embedded_meta, "OFFICIAL_TEAM_WEB_EMBED")
                    # One strongly verified page is sufficient to establish web identity.
                    break
            channels = self._verified_channels(entity["entityKey"])
            team_stats["youtubeChannels"] = len(channels); summary["youtubeChannels"] += len(channels)
            for source in channels:
                indexed = self._index_channel(entity, source, youtube, api_key, stop_event=stop_event)
                team_stats["indexedVideos"] += indexed; summary["indexedVideos"] += indexed
            summary["teams"].append(team_stats)
        return summary

    def candidates_from_registry(self, context: dict, known_asset_keys: set[str], match_candidate, *, max_candidates: int = 8) -> dict:
        entities = self.entities(context)
        if not entities:
            return {"candidates": [], "results": 0, "duplicates": 0, "rejected": 0, "teamRows": 0}
        try:
            event_date = datetime.fromisoformat(str((context or {}).get("event_date") or "")[:10]).date()
        except Exception:
            event_date = datetime.now(timezone.utc).date()
        start = (event_date - timedelta(days=3)).isoformat() + "T00:00:00Z"
        end = (event_date + timedelta(days=8)).isoformat() + "T23:59:59Z"
        rows = []
        with closing(self.connect()) as conn:
            for entity in entities:
                rows.extend(
                    dict(r) | {"team_name": entity["teamName"], "side": entity["side"]}
                    for r in conn.execute(
                        "SELECT * FROM team_source_video WHERE entity_key=? AND published_at>=? AND published_at<=? ORDER BY published_at DESC LIMIT 400",
                        (entity["entityKey"], start, end),
                    ).fetchall()
                )
        candidates = {}; duplicates = 0; rejected = 0
        for row in rows:
            vid = str(row.get("video_id") or "")
            key = "yt:" + vid if vid else ""
            if not key or key in known_asset_keys:
                duplicates += 1
                continue
            conf = float(match_candidate(context, row.get("title") or "", row.get("description") or "", row.get("published_at") or "", strict_date=True) or 0)
            if conf < .88:
                rejected += 1
                continue
            duration = float(row.get("duration_seconds") or 0)
            candidate = {
                "youtubeId": vid, "title": row.get("title") or "", "description": row.get("description") or "",
                "publishedAt": row.get("published_at") or "", "channelId": row.get("channel_id") or "",
                "channelName": row.get("channel_name") or "", "durationSeconds": duration,
                "tier": _tier(str(row.get("title") or ""), duration), "provider": "YOUTUBE",
                "confidence": conf, "source": "OFFICIAL_TEAM_SOURCE", "teamSourceType": row.get("source_type") or "",
                "teamName": row.get("team_name") or "", "teamSide": row.get("side") or "",
            }
            prior = candidates.get(vid)
            if prior is None or float(candidate["confidence"]) > float(prior.get("confidence") or 0):
                candidates[vid] = candidate
        ordered = sorted(candidates.values(), key=lambda x: (-float(x.get("confidence") or 0), -float(x.get("durationSeconds") or 0), str(x.get("youtubeId") or "")))
        return {"candidates": ordered[:max(1, int(max_candidates))], "results": len(rows), "duplicates": duplicates, "rejected": rejected, "teamRows": len(rows)}

    def candidates_for_event(self, context: dict, youtube, api_key: str, known_asset_keys: set[str], match_candidate, *, max_candidates: int = 8, stop_event=None) -> dict:
        refresh = self.refresh_event_sources(context, youtube, api_key, stop_event=stop_event)
        result = self.candidates_from_registry(context, known_asset_keys, match_candidate, max_candidates=max_candidates)
        result["refresh"] = refresh
        return result

    def snapshot(self) -> dict:
        try:
            with closing(self.connect()) as conn:
                source_counts = {str(r["source_type"]): int(r["n"]) for r in conn.execute("SELECT source_type,COUNT(*) n FROM team_source WHERE verified_at>0 GROUP BY source_type").fetchall()}
                teams = int(conn.execute("SELECT COUNT(DISTINCT entity_key) FROM team_source WHERE verified_at>0").fetchone()[0] or 0)
                videos = int(conn.execute("SELECT COUNT(*) FROM team_source_video").fetchone()[0] or 0)
                channels = int(conn.execute("SELECT COUNT(DISTINCT channel_id) FROM team_source WHERE source_type='OFFICIAL_TEAM_YOUTUBE' AND verified_at>0 AND channel_id<>''").fetchone()[0] or 0)
            return {"generation": GENERATION, "teams": teams, "verifiedSources": sum(source_counts.values()), "sourceTypes": source_counts, "youtubeChannels": channels, "indexedVideos": videos}
        except Exception as exc:
            return {"generation": GENERATION, "error": f"{type(exc).__name__}: {exc}"}

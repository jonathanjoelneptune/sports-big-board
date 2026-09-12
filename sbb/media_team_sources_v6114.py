"""v6.1.14 hardening for authoritative team-directory ownership scoping.

R23's resolver is retained, but directory links are bound to the nearest semantic
team card/heading or JSON object before identity scoring. The verified page title is
also carried into outgoing-link context so explicit club-site links can be accepted
without borrowing identity text from neighboring teams.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from .media_team_sources_v6113 import (
    ANCHOR_RE,
    ATTR_LABEL_RE,
    JSON_LINK_RE,
    TeamSourceRegistry as _V6113TeamSourceRegistry,
    _decode_link,
    _host,
    _text,
)

GENERATION = "R23-OFFICIAL-TEAM-DIRECTORY-SOURCES"

SEMANTIC_CARD_RE = re.compile(
    r"<div\b[^>]{0,240}\bclass\s*=\s*[\"'][^\"']*(?:club|team|card)[^\"']*[\"']",
    re.I,
)


class TeamSourceRegistry(_V6113TeamSourceRegistry):
    """R23 resolver with card/object-bounded link ownership evidence."""

    @staticmethod
    def _anchor_context(page: str, start: int, end: int) -> str:
        window_start = max(0, start - 1000)
        prefix = page[window_start:start]
        positions = []
        for pattern in (r"<h[1-6]\b", r"<article\b", r"<li\b", r"<section\b"):
            matches = list(re.finditer(pattern, prefix, re.I))
            if matches:
                positions.append(matches[-1].start())
        cards = list(SEMANTIC_CARD_RE.finditer(prefix))
        if cards:
            positions.append(cards[-1].start())
        left = window_start + max(positions) if positions else max(0, start - 260)
        return _text(page[left:end])

    @staticmethod
    def _json_context(page: str, start: int, end: int) -> str:
        search_left = max(0, start - 1000)
        search_right = min(len(page), end + 1000)
        left = page.rfind("{", search_left, start)
        right = page.find("}", end, search_right)
        if left >= 0 and right >= 0 and right > left:
            return _text(page[left : right + 1])
        return _text(page[max(0, start - 350) : min(len(page), end + 200)])

    def _extract_links(self, page: str, base_url: str) -> list[dict]:
        out = []
        seen = set()
        page = str(page or "")
        page_identity = self._page_identity_text(page)
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
            local_context = self._anchor_context(page, match.start(), match.end())
            context = _text(page_identity + " " + local_context)
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
            local_context = self._json_context(page, match.start(), match.end())
            context = _text(page_identity + " " + local_context)
            out.append(
                {
                    "url": url,
                    "label": "",
                    "context": context[:1000],
                    "host": _host(url),
                }
            )
        return out[: self.directory_link_limit]

    def snapshot(self) -> dict:
        base = super().snapshot()
        base["generation"] = GENERATION
        base["ownershipScoping"] = "SEMANTIC_CARD_OR_JSON_OBJECT"
        return base

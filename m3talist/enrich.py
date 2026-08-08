"""MusicBrainz and Cover Art Archive enrichment.

Offline-first, per docs/m3talist-v2.md ("Enrichment"): the local SQLite catalog
is the source of truth, the network only fills gaps. No network failure may
ever propagate — every public method returns None on any error (timeout, DNS
failure, 503, malformed JSON, rate limit) so the tool still runs with no
connection at all.
"""

import hashlib
import json
import re
import sqlite3
import threading
import time
from typing import Self

import httpx

from m3talist.catalog import cache_get, cache_put
from m3talist.profile import Settings, load

MB_SEARCH_URL = "https://musicbrainz.org/ws/2/release-group/"
COVER_ART_URL = "https://coverartarchive.org/release-group/{mbid}/front"

MB_MIN_INTERVAL = 1.0  # MusicBrainz: 1 request/second, or the IP gets blocked
REQUEST_TIMEOUT = httpx.Timeout(10.0)  # connect/read, applied to every request
MAX_ATTEMPTS = 2  # one request, one retry, never more


def _credited_artist(credits: list | None) -> str | None:
    if not credits:
        return None
    parts = []
    for credit in credits:
        if isinstance(credit, str):
            parts.append(credit)
        else:
            parts.append(credit.get("name", ""))
            parts.append(credit.get("joinphrase", ""))
    name = "".join(parts).strip()
    return name or None


def _release_year(first_release_date: str | None) -> int | None:
    if not first_release_date:
        return None
    try:
        return int(first_release_date[:4])
    except ValueError:
        return None


def _top_tag(tags: list | None) -> str | None:
    if not tags:
        return None
    return max(tags, key=lambda tag: tag.get("count", 0)).get("name")


def _comparable(title: str) -> str:
    """Title reduced for comparison: no bracketed editions, no punctuation."""
    without_editions = re.sub(r"[\[(].*?[\])]", " ", title.casefold())
    return re.sub(r"[^a-z0-9]+", " ", without_editions).strip()


def _parse_release_group(data: dict, wanted_title: str) -> dict | None:
    """Pick a confident match only.

    MusicBrainz happily returns score-100 hits for bootlegs and reissues whose
    titles merely resemble the query. Attaching a wrong MBID poisons the year,
    genre and cover for that release, so an uncertain match is worse than none.
    """
    wanted = _comparable(wanted_title)
    candidates = [
        group for group in data.get("release-groups") or []
        if int(group.get("score", 0)) >= 90 and _comparable(group.get("title", "")) == wanted
    ]
    if not candidates:
        return None
    top = max(candidates, key=lambda group: int(group.get("score", 0)))
    return {
        "mbid": top.get("id"),
        "title": top.get("title"),
        "artist": _credited_artist(top.get("artist-credit")),
        "year": _release_year(top.get("first-release-date")),
        "genre": _top_tag(top.get("tags")),
    }


class Enricher:
    """Rate-limited MusicBrainz / Cover Art Archive client scoped to one run."""

    def __init__(self, conn: sqlite3.Connection, settings: Settings | None = None) -> None:
        self.conn = conn
        self.settings = settings if settings is not None else load()
        self._client = httpx.Client(
            headers={"User-Agent": self.settings.user_agent},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        self._last_mb_request = 0.0
        self._mb_lock = threading.Lock()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _throttle_musicbrainz(self) -> None:
        # Enforced on the instance, across every call: hold the lock, check how
        # long it has been since the last request actually went out, and sleep
        # off whatever is left of the 1-second window before releasing it.
        with self._mb_lock:
            remaining = MB_MIN_INTERVAL - (time.monotonic() - self._last_mb_request)
            if remaining > 0:
                time.sleep(remaining)
            self._last_mb_request = time.monotonic()

    def _get_musicbrainz(self, url: httpx.URL) -> httpx.Response | None:
        for _ in range(MAX_ATTEMPTS):
            self._throttle_musicbrainz()
            try:
                return self._client.get(url)
            except httpx.RequestError:
                continue
        return None

    def _get_cover_art(self, url: str) -> httpx.Response | None:
        # Cover Art Archive publishes no rate limit, so no throttle here.
        for _ in range(MAX_ATTEMPTS):
            try:
                return self._client.get(url)
            except httpx.RequestError:
                continue
        return None

    def lookup_release(self, artist: str, title: str) -> dict | None:
        if self.settings.offline:
            return None
        try:
            query = f'artist:"{artist}" AND releasegroup:"{title}"'
            url = httpx.URL(MB_SEARCH_URL, params={"query": query, "fmt": "json", "limit": 5})
            cache_key = hashlib.sha256(str(url).encode("utf-8")).hexdigest()

            cached = cache_get(self.conn, cache_key)
            if cached is not None:
                return None if cached == "null" else _parse_release_group(json.loads(cached), title)

            response = self._get_musicbrainz(url)
            if response is None or response.status_code != 200:
                # Transport failure or server-side error (e.g. a 503 from
                # exceeding the rate limit) is not a real answer: leave it
                # uncached so a later, healthier run tries again.
                return None

            result = _parse_release_group(response.json(), title)
            cache_put(self.conn, cache_key, response.text if result is not None else "null")
            return result
        except Exception:
            return None

    def fetch_cover(self, mbid: str) -> bytes | None:
        if self.settings.offline:
            return None
        try:
            response = self._get_cover_art(COVER_ART_URL.format(mbid=mbid))
            if response is None or response.status_code == 404:
                return None
            response.raise_for_status()
            return response.content
        except Exception:
            return None

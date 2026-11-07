import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace
from urllib.parse import quote

import requests
from loguru import logger
from pydantic import ValidationError

from models.announce_data import AnnounceData
from models.torrent import Torrent

DEFAULT_RATE_LIMIT = 15  # lookups per minute
_RATE_WINDOW = 60.0  # seconds
_MAX_ATTEMPTS = 3  # initial request + up to 2 retries
_RETRY_BACKOFF = 1.0  # seconds, doubled after each failed attempt


def _is_retryable(error: Exception) -> bool:
    """Returns whether `error` is likely transient and worth retrying."""
    if isinstance(error, requests.HTTPError):
        response = error.response
        return response is not None and (response.status_code in {408, 429} or response.status_code >= 500)
    return isinstance(error, (requests.RequestException, ValueError))


def _by_uploader(results: list[dict], uploader: str | None) -> dict | None:
    if not uploader:
        return None
    wanted = uploader.strip().casefold()
    return next(
        (r for r in results if str((r.get("attributes") or {}).get("uploader") or "").strip().casefold() == wanted),
        None,
    )


def _select_match(results: list[dict], announce: AnnounceData, *, newest_as_last_resort: bool = True) -> dict | None:
    """Picks the result for `announce`: by `id`, by title, by uploader, otherwise the newest (if allowed)."""
    if announce.id:
        match = next((r for r in results if str(r.get("id")) == announce.id), None)
        if match is not None:
            return match
    if announce.title:
        title = announce.title.strip().casefold()
        named = [r for r in results if str((r.get("attributes") or {}).get("name") or "").strip().casefold() == title]
        if named:
            return _by_uploader(named, announce.uploader) or named[0]
    # The uploader may be announced differently than the API reports it (E.G. `Anónimo` vs `Anonymous`)
    return _by_uploader(results, announce.uploader) or (results[0] if newest_as_last_resort else None)


@dataclass(frozen=True)
class Unit3dClient:
    """Access to an indexer's `/api/torrents` endpoints (UNIT3D)."""

    url: str  # scheme + fqdn, e.g. `https://tracker.example.org`
    api_key: str
    rate_limit: int = DEFAULT_RATE_LIMIT  # max lookups per minute
    # Scheduled start time of the last `rate_limit` lookups
    _calls: deque[float] = field(default_factory=deque, init=False, repr=False, compare=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False, compare=False)

    def _wait_for_slot(self) -> None:
        """Blocks until a lookup is allowed, so at most `rate_limit` start in any `_RATE_WINDOW`."""
        with self._lock:
            now = time.monotonic()
            start = now
            if len(self._calls) == self.rate_limit:
                start = max(now, self._calls.popleft() + _RATE_WINDOW)
            self._calls.append(start)
        delay = start - now
        if delay > 0:
            logger.info("Rate limit reached for {}, delaying the lookup by {:.0f}s", self.url, delay)
            time.sleep(delay)

    def _get(self, path: str, subject: str, params: dict | None = None) -> object | None:
        """Returns the decoded JSON body of a GET to `path`, retrying transient errors, or None if it failed."""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            self._wait_for_slot()
            try:
                response = requests.get(
                    f"{self.url}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                    timeout=30,
                )
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as e:
                if attempt == _MAX_ATTEMPTS or not _is_retryable(e):
                    logger.warning("Torrent lookup failed for {}: {}", subject, e)
                    return None
                delay = _RETRY_BACKOFF * 2 ** (attempt - 1)
                logger.warning(
                    "Torrent lookup for {} failed on attempt {}/{}: {}. Retrying in {:.1f}s",
                    subject, attempt, _MAX_ATTEMPTS, e, delay,
                )
                time.sleep(delay)
        return None

    def _filter_by_name(self, title: str) -> list[dict] | None:
        """Returns the raw results of a name search (newest first), or None if the request failed."""
        body = self._get("/api/torrents/filter", repr(title), {"name": title.strip(), "sortField": "created_at"})
        if body is None:
            return None
        return (body.get("data") if isinstance(body, dict) else None) or []

    def _name_by_id(self, id: str) -> str | None:
        """Returns the current name of torrent `id`, or None if it can't be determined."""
        body = self._get(f"/api/torrents/{quote(id, safe='')}", f"id {id}")
        # The endpoint returns the resource unwrapped, but a `data` wrapper is accepted too
        if isinstance(body, dict) and isinstance(body.get("data"), dict):
            body = body["data"]
        attributes = body.get("attributes") if isinstance(body, dict) else None
        name = attributes.get("name") if isinstance(attributes, dict) else None
        return name.strip() or None if isinstance(name, str) else None

    def _find_by_id(self, announce: AnnounceData) -> dict | None:
        """Looks for `announce` through the current name of its torrent, which the announced title may not match
        (E.G. missing, or edited by the uploader right after announcing)."""
        name = self._name_by_id(announce.id)
        recent = self._filter_by_name(name) if name else None
        # The torrent is identified by its id; the title and uploader are only tie-breakers
        match = _select_match(recent, replace(announce, title=name), newest_as_last_resort=False) if recent else None
        if match is None:
            logger.warning("Torrent lookup for id {}: not found by its current name {!r}", announce.id, name)
        return match

    def _find_among_recent(self, announce: AnnounceData) -> dict | None:
        """Looks for `announce` among the latest torrents named like the first word of its title.

        Meant for when the announced title is wrong (E.G. the uploader edited it right after announcing). The newest
        result is never assumed to be the match, as the latest torrents are unrelated to the announce.
        """
        word = re.search(r"\w+", announce.title or "")
        if word is None:
            return None
        recent = self._filter_by_name(word.group())
        match = _select_match(recent, announce, newest_as_last_resort=False) if recent else None
        if match is None:
            logger.warning(
                "Torrent lookup for {!r}: no match among the latest {} torrent(s) named like {!r}",
                announce.title, len(recent or []), word.group(),
            )
        return match

    def find_torrent(self, announce: AnnounceData) -> Torrent | None:
        """Returns the torrent that `announce` refers to, or None if it can't be determined."""
        if not (announce.title or announce.id):
            return None

        results = self._filter_by_name(announce.title) if announce.title else []
        if results is None:
            return None
        if announce.title:
            logger.debug("Torrent lookup for {!r} returned {} result(s)", announce.title, len(results))
        if results:
            match = _select_match(results, announce)
        elif announce.id:
            match = self._find_by_id(announce)
        else:
            match = self._find_among_recent(announce)
        if match is None:
            return None

        try:
            return Torrent.model_validate(match)
        except ValidationError as e:
            logger.warning("Torrent lookup for {!r} returned an invalid match: {}", announce.title, e)
            return None

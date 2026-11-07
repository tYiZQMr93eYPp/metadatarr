import threading
import time
from collections import deque
from dataclasses import dataclass, field

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


def _select_match(results: list[dict], announce: AnnounceData) -> dict | None:
    """Picks the result for `announce`: by `id` if announced, otherwise among those named like the title (or all
    results if none is), by uploader, otherwise the newest."""
    if announce.id:
        return next((r for r in results if str(r.get("id")) == announce.id), None)
    if announce.title:
        title = announce.title.strip().casefold()
        results = [
            r for r in results if str((r.get("attributes") or {}).get("name") or "").strip().casefold() == title
        ] or results
    if announce.uploader:
        wanted = announce.uploader.strip().casefold()
        for r in results:
            if str((r.get("attributes") or {}).get("uploader") or "").strip().casefold() == wanted:
                return r
    # The uploader may be announced differently than the API reports it (E.G. `Anónimo` vs `Anonymous`)
    return results[0]


@dataclass(frozen=True)
class Unit3dClient:
    """Access to an indexer's `/api/torrents/filter` endpoint (UNIT3D)."""

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

    def _filter_by_name(self, title: str) -> list[dict] | None:
        """Returns the raw results of a name search (newest first), or None if the request failed."""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            self._wait_for_slot()
            try:
                response = requests.get(
                    f"{self.url}/api/torrents/filter",
                    params={"name": title.strip(), "sortField": "created_at"},
                    headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                    timeout=30,
                )
                response.raise_for_status()
                body = response.json()
                return (body.get("data") if isinstance(body, dict) else None) or []
            except (requests.RequestException, ValueError) as e:
                if attempt == _MAX_ATTEMPTS or not _is_retryable(e):
                    logger.warning("Torrent lookup failed for {!r}: {}", title, e)
                    return None
                delay = _RETRY_BACKOFF * 2 ** (attempt - 1)
                logger.warning(
                    "Torrent lookup for {!r} failed on attempt {}/{}: {}. Retrying in {:.1f}s",
                    title, attempt, _MAX_ATTEMPTS, e, delay,
                )
                time.sleep(delay)
        return None

    def find_torrent(self, announce: AnnounceData) -> Torrent | None:
        """Returns the torrent that `announce` refers to, or None if it can't be determined."""
        if not announce.title:
            return None

        results = self._filter_by_name(announce.title)
        if results is None:
            return None
        logger.debug("Torrent lookup for {!r} returned {} result(s)", announce.title, len(results))
        if not results:
            return None

        match = _select_match(results, announce)
        if match is None:
            logger.warning("Torrent lookup for {!r}: none of the {} result(s) has id {}", announce.title, len(results), announce.id)
            return None

        try:
            return Torrent.model_validate(match)
        except ValidationError as e:
            logger.warning("Torrent lookup for {!r} returned an invalid match: {}", announce.title, e)
            return None

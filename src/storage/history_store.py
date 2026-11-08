import asyncio
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

DEFAULT_RETENTION_DAYS = 30
PURGE_INTERVAL = 24 * 3600.0  # seconds between retention sweeps

_SCHEMA = """
CREATE TABLE IF NOT EXISTS announces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    indexer TEXT NOT NULL,
    channel_id INTEGER,
    chat_id INTEGER,
    msg_id INTEGER,
    raw_message TEXT,
    announce TEXT,
    reply_markup TEXT,
    outcome TEXT NOT NULL,
    torrent_id TEXT,
    torrent TEXT
);
CREATE INDEX IF NOT EXISTS idx_announces_created_at ON announces (created_at);
CREATE INDEX IF NOT EXISTS idx_announces_match ON announces (indexer, torrent_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dump(value: object) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)


class HistoryStore:
    """SQLite record of the announces processed, kept for debugging and for spotting repeated matches."""

    def __init__(self, path: str | Path, retention_days: int = DEFAULT_RETENTION_DAYS):
        self.retention_days = retention_days
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Used from worker threads, serialised through `_lock`
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(_SCHEMA)
        self.purge()

    @classmethod
    def from_env(cls) -> "HistoryStore":
        """Builds the store from `DB_PATH` and `DB_RETENTION_DAYS`."""
        raw = os.getenv("DB_RETENTION_DAYS")
        days = DEFAULT_RETENTION_DAYS
        if raw:
            try:
                days = int(raw)
                if days < 1:
                    raise ValueError
            except ValueError:
                logger.warning("DB_RETENTION_DAYS must be a positive integer, using {}", DEFAULT_RETENTION_DAYS)
                days = DEFAULT_RETENTION_DAYS
        return cls(os.getenv("DB_PATH", "/app/config/metadatarr.db"), days)

    def record(
        self,
        indexer: str,
        outcome: str,
        *,
        channel_id: int | None = None,
        chat_id: int | None = None,
        msg_id: int | None = None,
        raw_message: str | None = None,
        announce: dict | None = None,
        reply_markup: dict | None = None,
        torrent_id: str | None = None,
        torrent: dict | None = None,
    ) -> int | None:
        """Stores one processed announce and returns its row id; None if it couldn't be stored."""
        try:
            with self._lock:
                cursor = self._db.execute(
                    "INSERT INTO announces (created_at, indexer, channel_id, chat_id, msg_id, raw_message, announce,"
                    " reply_markup, outcome, torrent_id, torrent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (_now(), indexer, channel_id, chat_id, msg_id, raw_message, _dump(announce),
                     _dump(reply_markup), outcome, torrent_id, _dump(torrent)),
                )
                self._db.commit()
                row_id = cursor.lastrowid
        except sqlite3.Error:
            logger.exception("Couldn't store the announce history | indexer={} | msg_id={}", indexer, msg_id)
            return None
        return row_id

    def previous_matches(self, indexer: str, torrent_id: str, before_id: int) -> list[dict]:
        """Earlier successful records of the same torrent on the same indexer, oldest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, created_at, msg_id FROM announces"
                " WHERE indexer = ? AND torrent_id = ? AND outcome = 'matched' AND id < ? ORDER BY id",
                (indexer, torrent_id, before_id),
            ).fetchall()
        return [dict(row) for row in rows]

    async def purge_periodically(self, interval: float = PURGE_INTERVAL) -> None:
        """Purges every `interval` seconds, forever. The startup purge already happened in the constructor."""
        while True:
            await asyncio.sleep(interval)
            await asyncio.to_thread(self.purge)

    def purge(self) -> int:
        """Deletes the records older than the retention period; returns how many were removed."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat(timespec="seconds")
        try:
            with self._lock:
                deleted = self._db.execute("DELETE FROM announces WHERE created_at < ?", (cutoff,)).rowcount
                self._db.commit()
        except sqlite3.Error:
            logger.exception("Couldn't purge the announce history")
            return 0
        if deleted:
            logger.info("Purged {} announce record(s) older than {} day(s)", deleted, self.retention_days)
        return deleted

    def close(self) -> None:
        with self._lock:
            self._db.close()

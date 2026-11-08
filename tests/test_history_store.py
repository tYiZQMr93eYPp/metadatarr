import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from storage.history_store import HistoryStore


@pytest.fixture
def store(tmp_path):
    store = HistoryStore(tmp_path / "nested" / "history.db", retention_days=30)
    yield store
    store.close()


def _age(store: HistoryStore, row_id: int, days: int) -> None:
    created = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    store._db.execute("UPDATE announces SET created_at = ? WHERE id = ?", (created, row_id))
    store._db.commit()


def test_record_stores_the_data(store):
    row_id = store.record(
        "Alpha", "matched", channel_id=1, msg_id=7, raw_message="raw", announce={"title": "T"},
        reply_markup={"rows": [b"x"]}, torrent_id="2", torrent={"id": "2"},
    )

    row = store._db.execute("SELECT * FROM announces WHERE id = ?", (row_id,)).fetchone()
    assert (row["indexer"], row["outcome"], row["channel_id"], row["msg_id"]) == ("Alpha", "matched", 1, 7)
    assert row["raw_message"] == "raw"
    assert json.loads(row["announce"]) == {"title": "T"}
    assert json.loads(row["torrent"]) == {"id": "2"}


def test_purge_removes_only_records_older_than_the_retention(store):
    old = store.record("Alpha", "matched")
    recent = store.record("Alpha", "matched")
    _age(store, old, 31)
    _age(store, recent, 29)

    assert store.purge() == 1
    assert [r["id"] for r in store._db.execute("SELECT id FROM announces")] == [recent]


def test_previous_matches_are_scoped_to_indexer_torrent_and_successful_matches(store):
    first = store.record("Alpha", "matched", msg_id=1, torrent_id="2")
    store.record("Beta", "matched", msg_id=2, torrent_id="2")
    store.record("Alpha", "matched", msg_id=3, torrent_id="3")
    store.record("Alpha", "no_match", msg_id=4)
    current = store.record("Alpha", "matched", msg_id=5, torrent_id="2")

    previous = store.previous_matches("Alpha", "2", current)

    assert [(p["id"], p["msg_id"]) for p in previous] == [(first, 1)]
    assert store.previous_matches("Alpha", "2", first) == []


def test_record_returns_none_when_it_cant_be_stored(store):
    store.close()

    assert store.record("Alpha", "matched") is None


@pytest.mark.parametrize("raw, expected", [(None, 30), ("7", 7), ("0", 30), ("-1", 30), ("abc", 30)])
def test_from_env_retention(monkeypatch, tmp_path, raw, expected):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "history.db"))
    if raw is None:
        monkeypatch.delenv("DB_RETENTION_DAYS", raising=False)
    else:
        monkeypatch.setenv("DB_RETENTION_DAYS", raw)

    store = HistoryStore.from_env()
    try:
        assert store.retention_days == expected
    finally:
        store.close()


def test_purge_periodically_purges_on_every_interval(store):
    async def run():
        task = asyncio.create_task(store.purge_periodically(interval=0.01))
        await asyncio.sleep(0.1)
        task.cancel()

    old = store.record("Alpha", "matched")
    _age(store, old, 40)

    asyncio.run(run())

    assert store._db.execute("SELECT COUNT(*) FROM announces").fetchone()[0] == 0

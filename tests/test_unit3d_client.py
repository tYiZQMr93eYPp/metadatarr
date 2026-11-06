import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from clients import unit3d
from clients.unit3d import Unit3dClient
from models.announce_data import AnnounceData
from models.torrent import Torrent

SAMPLE = Path(__file__).parent.parent / "examples" / "unit3d-api" / "api-torrents-filter.sample1.json"


def _response(body):
    return SimpleNamespace(raise_for_status=lambda: None, json=lambda: body)


def _result(id: str, uploader: str) -> dict:
    return {"id": id, "attributes": {"uploader": uploader}}


@pytest.fixture
def body():
    return json.loads(SAMPLE.read_text())


@pytest.fixture
def client():
    return Unit3dClient("https://tracker.example.org", "key")


def test_find_torrent_deserializes_the_whole_match(monkeypatch, client, body):
    monkeypatch.setattr(unit3d.requests, "get", lambda *args, **kwargs: _response(body))

    found = client.find_torrent(AnnounceData(title=body["data"][0]["attributes"]["name"]))

    assert isinstance(found, Torrent)
    assert found.id == "1234"
    assert found.attributes.name == "Some Movie 1988 1080p BluRay AAC 2.0 x264"
    assert found.attributes.size == 4375730285
    assert found.attributes.tmdb_id == 2280
    assert found.attributes.created_at == datetime(2026, 11, 6, 10, 53, 27, tzinfo=timezone.utc)


def test_find_torrent_without_title_does_not_call_the_api(monkeypatch, client):
    monkeypatch.setattr(unit3d.requests, "get", lambda *args, **kwargs: pytest.fail("unexpected request"))

    assert client.find_torrent(AnnounceData(title=None)) is None


def test_find_torrent_matches_by_announced_id(monkeypatch, client):
    results = [_result("3", "a"), _result("2", "b"), _result("1", "c")]
    monkeypatch.setattr(unit3d.requests, "get", lambda *args, **kwargs: _response({"data": results}))

    assert client.find_torrent(AnnounceData(title="T", id="2", uploader="a")).id == "2"


def test_find_torrent_fails_when_the_announced_id_is_not_in_the_results(monkeypatch, client):
    monkeypatch.setattr(unit3d.requests, "get", lambda *args, **kwargs: _response({"data": [_result("3", "a")]}))

    assert client.find_torrent(AnnounceData(title="T", id="2")) is None


@pytest.mark.parametrize("uploader, expected", [("  UPLOADER ", "2"), ("Anónimo", "3")])
def test_find_torrent_without_id_prefers_uploader_then_newest(monkeypatch, client, uploader, expected):
    results = [_result("3", "Anonymous"), _result("2", "uploader")]
    monkeypatch.setattr(unit3d.requests, "get", lambda *args, **kwargs: _response({"data": results}))

    assert client.find_torrent(AnnounceData(title="T", uploader=uploader)).id == expected


def test_find_torrent_without_results(monkeypatch, client):
    monkeypatch.setattr(unit3d.requests, "get", lambda *args, **kwargs: _response({"data": []}))

    assert client.find_torrent(AnnounceData(title="T")) is None


def test_find_torrent_retries_transient_errors(monkeypatch, client, body):
    attempts = 0

    def get(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < unit3d._MAX_ATTEMPTS:
            raise requests.ConnectionError("temporary failure")
        return _response(body)

    monkeypatch.setattr(unit3d.requests, "get", get)
    monkeypatch.setattr(unit3d.time, "sleep", lambda _: None)

    assert client.find_torrent(AnnounceData(title="T")) is not None
    assert attempts == unit3d._MAX_ATTEMPTS


def test_find_torrent_gives_up_after_max_attempts(monkeypatch, client):
    attempts = 0
    delays = []

    def get(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise requests.ConnectionError("temporary failure")

    monkeypatch.setattr(unit3d.requests, "get", get)
    monkeypatch.setattr(unit3d.time, "sleep", delays.append)

    assert client.find_torrent(AnnounceData(title="T")) is None
    assert attempts == unit3d._MAX_ATTEMPTS
    assert delays == [1.0, 2.0]


def test_find_torrent_does_not_retry_client_errors(monkeypatch, client):
    attempts = 0
    response = SimpleNamespace(status_code=404)

    def raise_for_status():
        raise requests.HTTPError(response=response)

    def get(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        return SimpleNamespace(raise_for_status=raise_for_status, json=lambda: {})

    monkeypatch.setattr(unit3d.requests, "get", get)
    monkeypatch.setattr(unit3d.time, "sleep", lambda _: None)

    assert client.find_torrent(AnnounceData(title="T")) is None
    assert attempts == 1

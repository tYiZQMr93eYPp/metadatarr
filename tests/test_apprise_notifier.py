from zoneinfo import ZoneInfo

import pytest

from models.announce_data import AnnounceData
from models.torrent import Torrent
from notifications import apprise_notifier


class FakeApprise:
    instances: list["FakeApprise"] = []
    notify_result = True

    def __init__(self):
        self.urls: list[str] = []
        self.sent: list[dict] = []
        FakeApprise.instances.append(self)

    def add(self, url):
        self.urls.append(url)
        return True

    def notify(self, **kwargs):
        self.sent.append(kwargs)
        if isinstance(FakeApprise.notify_result, Exception):
            raise FakeApprise.notify_result
        return FakeApprise.notify_result


@pytest.fixture(autouse=True)
def fake_apprise(monkeypatch):
    FakeApprise.instances = []
    FakeApprise.notify_result = True
    monkeypatch.setattr(apprise_notifier.apprise, "Apprise", FakeApprise)
    monkeypatch.setattr(apprise_notifier, "_APPRISE_URL", "apprises://host/metadatarr?overflow=split")
    monkeypatch.setattr(apprise_notifier, "_ERROR_TAG", "error")
    monkeypatch.setattr(apprise_notifier, "_TZ", ZoneInfo("Europe/Madrid"))


@pytest.fixture
def data():
    return AnnounceData(title=None, category="Movies", normalized_message="hello world")


@pytest.fixture
def torrent():
    return Torrent.model_validate({
        "id": "1234",
        "attributes": {
            "name": "Some Movie 1988",
            "size": 4375730285,
            "double_upload": False,
            "tvdb_id": None,
            "distributor": "",
            "created_at": "2026-11-06T10:53:27.000000Z",
        },
    })


@pytest.mark.parametrize("size, expected", [
    (0, "0 B"),
    (1023, "1023 B"),
    (1024, "1.00 KiB"),
    (5 * 1024 ** 2, "5.00 MiB"),
    (4375730285, "4.08 GiB"),
    (3 * 1024 ** 4, "3.00 TiB"),
    (2048 * 1024 ** 4, "2048.00 TiB"),
])
def test_format_size(size, expected):
    assert apprise_notifier.format_size(size) == expected


def test_ensure_configured_requires_url(monkeypatch):
    monkeypatch.setattr(apprise_notifier, "_APPRISE_URL", None)

    with pytest.raises(RuntimeError):
        apprise_notifier.ensure_configured()


def test_metadata_is_tagged_with_the_indexer_and_skips_missing_fields(torrent):
    apprise_notifier.notify_metadata("HDZERO", torrent)

    [notifier] = FakeApprise.instances
    assert notifier.urls == ["apprises://host/metadatarr?overflow=split&tags=HDZERO"]
    [sent] = notifier.sent
    assert sent["body"].splitlines() == [
        "id: [1234]",
        "name: [Some Movie 1988]",
        "size: [4.08 GiB]",
        "double_upload: [false]",
        "created_at: [2026-11-06T11:53:27+01:00]",
    ]
    assert sent["body_format"] == apprise_notifier.apprise.NotifyFormat.TEXT


def test_error_is_tagged_with_the_error_tag(data, make_event, make_markup):
    apprise_notifier.notify_error("NOBS", data, "Missing fields: `title`", make_event(make_markup("https://x/torrents/1")))

    [notifier] = FakeApprise.instances
    assert notifier.urls == ["apprises://host/metadatarr?overflow=split&tags=error"]
    [sent] = notifier.sent
    body = sent["body"]
    assert sent["title"].startswith("[metadatarr] Error: NOBS")
    assert "Missing fields: `title`" in body
    assert "hello world" in body
    assert "InlineButtonTypeUrl" in body
    assert "normalized_message" not in body
    assert "2026-10-28T13:00:00+01:00" in body  # message date (12:00 UTC) in TZ


def test_error_markup_section_skipped_without_markup(data, make_event):
    apprise_notifier.notify_error("NOBS", data, "boom", make_event(None))

    assert "Reply markup" not in FakeApprise.instances[0].sent[0]["body"]


@pytest.mark.parametrize("result", [False, RuntimeError("boom")])
def test_failures_do_not_raise(data, torrent, make_event, result):
    FakeApprise.notify_result = result

    apprise_notifier.notify_metadata("HDZERO", torrent)
    apprise_notifier.notify_error("NOBS", data, "boom", make_event())

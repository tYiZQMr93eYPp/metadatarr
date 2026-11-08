import pytest

from indexers.emuwarez import EMUWAREZ
from indexers.nobs import NOBS
from indexers.torrenteros import TORRENTEROS

TORRENT = "https://x/torrents/42"
DOWNLOAD = "https://x/torrents/download/42"

ALL = [NOBS, EMUWAREZ, TORRENTEROS]
BUTTONS = [NOBS, TORRENTEROS]  # EMUWAREZ reads the link from the message text
SKIP_DOWNLOAD = [TORRENTEROS]


@pytest.mark.parametrize("indexer", BUTTONS)
def test_extracts_id_and_base_url(indexer, make_event, make_markup):
    data = indexer().parse_event(make_event(make_markup(TORRENT)))

    assert (data.id, data.base_url) == ("42", TORRENT)


def test_emuwarez_extracts_id_and_base_url_from_the_text(make_event):
    data = EMUWAREZ().parse_event(make_event(None, text=f"📺 **Title**\n🔗 {TORRENT}\n🎥 **TMDB:** `1`"))

    assert (data.id, data.base_url) == ("42", TORRENT)


@pytest.mark.parametrize("indexer", SKIP_DOWNLOAD)
def test_ignores_download_button(indexer, make_event, make_markup):
    data = indexer().parse_event(make_event(make_markup(DOWNLOAD, TORRENT)))

    assert (data.id, data.base_url) == ("42", TORRENT)


@pytest.mark.parametrize("indexer", ALL)
def test_ignores_unrelated_urls(indexer, make_event, make_markup):
    data = indexer().parse_event(make_event(make_markup("https://x/other/1")))

    assert (data.id, data.base_url) == (None, None)


@pytest.mark.parametrize("indexer", ALL)
def test_no_markup(indexer, make_event):
    data = indexer().parse_event(make_event(None))

    assert (data.id, data.base_url) == (None, None)

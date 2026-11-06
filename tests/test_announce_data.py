import pytest

from models.announce_data import AnnounceData


def test_title_is_the_only_required_field():
    assert AnnounceData(title="T").missing_fields() == []


@pytest.mark.parametrize("empty", [None, ""])
def test_missing_title_is_reported(empty):
    assert AnnounceData(title=empty, category="Movies", id="1").missing_fields() == ["title"]

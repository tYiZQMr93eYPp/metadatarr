import pytest

from models.announce_data import AnnounceData


def test_title_or_id_is_required():
    assert AnnounceData(title="T").missing_fields() == []
    assert AnnounceData(id="1").missing_fields() == []


@pytest.mark.parametrize("empty", [None, ""])
def test_missing_title_and_id_is_reported(empty):
    assert AnnounceData(title=empty, category="Movies", id=empty).missing_fields() == ["title or id"]

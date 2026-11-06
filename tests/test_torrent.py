import pytest

from models.torrent import Torrent


@pytest.mark.parametrize("zero", [0, "0"])
def test_zero_ids_are_null(zero):
    attributes = Torrent.model_validate({
        "id": "1",
        "attributes": {"tmdb_id": zero, "imdb_id": 0, "distributor_id": 0, "region_id": 0, "category_id": 1},
    }).attributes

    assert (attributes.tmdb_id, attributes.imdb_id, attributes.distributor_id, attributes.region_id) == (None, None, None, None)
    assert attributes.category_id == 1


def test_false_booleans_are_kept():
    assert Torrent.model_validate({"id": "1", "attributes": {"double_upload": False}}).attributes.double_upload is False

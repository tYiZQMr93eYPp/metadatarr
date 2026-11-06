import pytest
import yaml

from mappers.indexer_mapper import IndexerMapper

API = {"url": "https://tracker.example.org/", "api_key": "key"}


def _load(tmp_path, config: dict) -> IndexerMapper:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    return IndexerMapper(path)


def test_every_indexer_has_its_client(tmp_path):
    mapper = _load(tmp_path, {"channel_indexers": {"1": "NOBS"}, "indexer_api": {"NOBS": API}})

    [indexer] = mapper.indexers()
    assert mapper.api(indexer).url == "https://tracker.example.org"


@pytest.mark.parametrize("api", [{}, {"NOBS": {"url": "https://x"}}, {"NOBS": {"api_key": "key"}}])
def test_startup_fails_without_a_valid_api_entry(tmp_path, api):
    with pytest.raises(ValueError, match="NOBS"):
        _load(tmp_path, {"channel_indexers": {"1": "NOBS"}, "indexer_api": api})

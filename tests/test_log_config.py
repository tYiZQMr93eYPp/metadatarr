import logging

import pytest
from loguru import logger

from log_config import LogConfig, load_level_overrides


@pytest.fixture(autouse=True)
def restore_logging():
    yield
    logger.remove()
    logging.getLogger().handlers.clear()


def test_threshold_uses_the_longest_matching_name():
    config = LogConfig(level="INFO", overrides={"pkg": "WARNING", "pkg.sub": "DEBUG", "pkg.sub.mod": "ERROR"})

    assert config._threshold("other") == logger.level("INFO").no
    assert config._threshold("pkg") == logger.level("WARNING").no
    assert config._threshold("pkg.other") == logger.level("WARNING").no
    assert config._threshold("pkg.sub.x") == logger.level("DEBUG").no
    assert config._threshold("pkg.sub.mod") == logger.level("ERROR").no
    assert config._threshold("pkgx") == logger.level("INFO").no  # not a package prefix
    assert config._threshold(None) == logger.level("INFO").no


def test_unknown_levels_are_ignored():
    config = LogConfig(level="INFO", overrides={"pkg": "LOUD"})

    assert config.overrides == {}
    assert config.invalid == ["pkg: LOUD"]


def test_configure_applies_levels_per_module(tmp_path):
    log_file = tmp_path / "app.log"
    LogConfig(level="INFO", log_path=str(log_file), overrides={"noisy": "DEBUG", "quiet": "ERROR"}).configure()

    for module in ("noisy", "plain", "quiet"):
        scoped = logger.patch(lambda record, module=module: record.update(name=module))
        scoped.debug("debug from {}", module)
        scoped.info("info from {}", module)
        scoped.error("error from {}", module)
    logger.complete()

    lines = log_file.read_text(encoding="utf-8")
    assert "debug from noisy" in lines
    assert "debug from plain" not in lines and "info from plain" in lines
    assert "info from quiet" not in lines and "error from quiet" in lines


def test_load_level_overrides(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("logging:\n  level:\n    indexers.alpha: debug\n    telethon: WARNING\n", encoding="utf-8")

    assert load_level_overrides(config) == {"indexers.alpha": "DEBUG", "telethon": "WARNING"}


@pytest.mark.parametrize("content", ["", "indexer_api: {}\n", "logging:\n", "logging:\n  level:\n"])
def test_load_level_overrides_without_section(tmp_path, content):
    config = tmp_path / "config.yaml"
    config.write_text(content, encoding="utf-8")

    assert load_level_overrides(config) == {}
    assert load_level_overrides(tmp_path / "missing.yaml") == {}

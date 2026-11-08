import inspect
import logging
import os
import sys
from pathlib import Path

import yaml
from loguru import logger


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        # Get corresponding Loguru level if it exists.
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message.
        frame, depth = inspect.currentframe(), 0
        while frame:
            filename = frame.f_code.co_filename
            is_logging = filename == logging.__file__
            is_frozen = "importlib" in filename and "_bootstrap" in filename
            if depth > 0 and not (is_logging or is_frozen):
                break
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def load_level_overrides(config_path: str | Path | None) -> dict[str, str]:
    """Reads `logging.level` (module or package name -> level) from the YAML config; {} if unavailable."""
    if not config_path or not Path(config_path).is_file():
        return {}
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    levels = ((config.get("logging") or {}).get("level")) or {}
    return {str(name): str(level).upper() for name, level in levels.items()}


class LogConfig:
    def __init__(
        self,
        level: str | None = None,
        log_path: str | None = None,
        overrides: dict[str, str] | None = None,
    ):
        self.level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
        self.log_path = log_path or os.getenv("LOG_PATH")
        if overrides is None:
            overrides = load_level_overrides(os.getenv("INDEXER_CONFIG_PATH", "/app/config/config.yaml"))
        self.overrides: dict[str, int] = {}
        self.invalid: list[str] = []
        for name, level_name in overrides.items():
            try:
                self.overrides[name] = logger.level(level_name).no
            except ValueError:
                self.invalid.append(f"{name}: {level_name}")
        self._default_no = logger.level(self.level).no
        self._cache: dict[str, int] = {}

    def _threshold(self, module: str | None) -> int:
        """Minimum level number for `module`; the longest matching name (exact or package prefix) wins."""
        module = module or ""
        if module not in self._cache:
            matches = [n for n in self.overrides if module == n or module.startswith(n + ".")]
            self._cache[module] = self.overrides[max(matches, key=len)] if matches else self._default_no
        return self._cache[module]

    def _allows(self, record) -> bool:
        return record["level"].no >= self._threshold(record["name"])

    def configure(self) -> None:
        logger.remove()
        # The sinks only see what the per-module filter lets through, so they must accept the lowest level in use
        sink_level = min([self._default_no, *self.overrides.values()])
        logger.add(sys.stderr, level=sink_level, filter=self._allows)

        if self.log_path:
            logger.add(
                self.log_path,
                level=sink_level,
                filter=self._allows,
                rotation="100 MB",
                retention="5 days",
                encoding="utf-8",
            )

        logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
        for entry in self.invalid:
            logger.warning("logging.level: unknown level in `{}`, ignoring", entry)

import importlib
import yaml
from loguru import logger
from clients.unit3d import DEFAULT_RATE_LIMIT, Unit3dClient


class IndexerMapper:
    def __init__(self, config_path):
        self._map: dict[int, type] = {}
        self._topic_map: dict[tuple[int, int], type] = {}
        self._chat_map: dict[int, type] = {}
        self._api: dict[str, Unit3dClient] = {}
        with open(config_path) as f:
            config = yaml.safe_load(f)
        for class_name, settings in (config.get("indexer_api") or {}).items():
            url = str((settings or {}).get("url") or "").strip().rstrip("/")
            api_key = str((settings or {}).get("api_key") or "").strip()
            if not url or not api_key:
                logger.warning("indexer_api.{}: both `url` and `api_key` are required, ignoring", class_name)
                continue
            rate_limit = settings.get("rate_limit", DEFAULT_RATE_LIMIT)
            if isinstance(rate_limit, bool) or not isinstance(rate_limit, int) or rate_limit < 1:
                logger.warning("indexer_api.{}.rate_limit must be a positive integer, using {}", class_name, DEFAULT_RATE_LIMIT)
                rate_limit = DEFAULT_RATE_LIMIT
            self._api[class_name] = Unit3dClient(url, api_key, rate_limit)
        for channel_id, class_name in (config.get("channel_indexers") or {}).items():
            module_name = class_name.lower()
            module = importlib.import_module(f"indexers.{module_name}")
            self._map[int(channel_id)] = getattr(module, class_name)
        for composite_key, class_name in (config.get("group_topic_indexers") or {}).items():
            group_id, topic_id = str(composite_key).split("_")
            module_name = class_name.lower()
            module = importlib.import_module(f"indexers.{module_name}")
            self._topic_map[(int(group_id), int(topic_id))] = getattr(module, class_name)
        for chat_id, class_name in (config.get("chat_indexers") or {}).items():
            module_name = class_name.lower()
            module = importlib.import_module(f"indexers.{module_name}")
            self._chat_map[int(chat_id)] = getattr(module, class_name)

        missing = sorted(i.__name__ for i in self.indexers() if i.__name__ not in self._api)
        if missing:
            raise ValueError(f"`indexer_api` (`url` and `api_key`) is required for: {', '.join(missing)}")

    def get(self, channel_id: int):
        return self._map.get(channel_id)

    def get_topic(self, group_id: int, topic_id: int):
        return self._topic_map.get((group_id, topic_id))

    def get_chat(self, chat_id: int):
        return self._chat_map.get(chat_id)

    def api(self, indexer: type) -> Unit3dClient:
        return self._api[indexer.__name__]

    def indexers(self):
        return set(self._map.values()) | set(self._topic_map.values()) | set(self._chat_map.values())

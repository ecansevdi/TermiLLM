import json
import os
from dataclasses import asdict, dataclass, fields

DEFAULT_CONFIG_PATH = "search_config.json"


@dataclass
class SearchConfig:
    provider: str = "searxng"

    searxng_base_url: str = ""
    searxng_language: str = "auto"
    searxng_safesearch: int = 0
    searxng_categories: str = "general"

    tavily_base_url: str = "https://api.tavily.com"
    tavily_api_key: str = ""

    max_results: int = 5
    timeout: int = 10


def load_search_config(path: str = DEFAULT_CONFIG_PATH) -> SearchConfig:
    config = SearchConfig()
    if not os.path.exists(path):
        return config
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return config
    if not isinstance(data, dict):
        return config
    valid = {f.name for f in fields(SearchConfig)}
    for key, value in data.items():
        if key in valid:
            setattr(config, key, value)
    return config


def save_search_config(config: SearchConfig, path: str = DEFAULT_CONFIG_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(config), f, ensure_ascii=False, indent=4)

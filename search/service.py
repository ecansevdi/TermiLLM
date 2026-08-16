from search.config import (
    DEFAULT_CONFIG_PATH,
    SearchConfig,
    load_search_config,
    save_search_config,
)
from search.providers import build_provider

SNIPPET_LIMIT = 400


class SearchService:
    """Arama yapılandırması ve sağlayıcı koordinasyonu.

    Yapılandırma her çağrıda dosyadan yeniden okunur; dosya program
    çalışırken elle düzenlenebilir.
    """

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self.config_path = config_path

    def load(self) -> SearchConfig:
        return load_search_config(self.config_path)

    def save(self, config: SearchConfig):
        save_search_config(config, self.config_path)

    def search(self, query: str, config: SearchConfig = None) -> list:
        config = config or self.load()
        provider = build_provider(config)
        return provider.search(query, config.max_results)

    def test(self, config: SearchConfig) -> str:
        provider = build_provider(config)
        if provider.search("connection test", 1):
            return f"✓ {provider.name} bağlantısı çalışıyor"
        return f"⚠ {provider.name} bağlandı ancak sonuç dönmedi"

    def format_for_model(self, query: str, results: list) -> str:
        lines = ["--- Web Arama Sonuçları ---", f"Sorgu: {query}"]
        for idx, result in enumerate(results, 1):
            snippet = result.snippet[:SNIPPET_LIMIT]
            if len(result.snippet) > SNIPPET_LIMIT:
                snippet += "…"
            lines.append(
                f"\n[{idx}] {result.title}\n"
                f"    URL: {result.url}\n"
                f"    Özet: {snippet}"
            )
        lines.append("\n--- Web Arama Sonuçları Sonu ---")
        return "\n".join(lines)

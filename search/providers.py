import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def _http_json(request: urllib.request.Request, timeout: int) -> dict:
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


class SearxngProvider:
    """SearXNG instance'ının JSON API'si üzerinden arama."""

    name = "searxng"

    def __init__(self, base_url: str, language: str = "auto",
                 safesearch: int = 0, categories: str = "general",
                 timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.language = language or "auto"
        self.safesearch = safesearch
        self.categories = (categories or "").strip()
        self.timeout = timeout

    def search(self, query: str, max_results: int) -> list:
        params = {
            "q": query,
            "format": "json",
            "language": self.language,
            "safesearch": str(self.safesearch),
        }
        if self.categories:
            params["categories"] = self.categories
        request = urllib.request.Request(
            f"{self.base_url}/search?{urllib.parse.urlencode(params)}",
            headers={"Accept": "application/json"},
        )
        try:
            data = _http_json(request, self.timeout)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise RuntimeError(
                    "SearXNG JSON çıktısı kapalı (403). Instance'ın settings.yml "
                    "dosyasındaki search.formats listesine 'json' ekleyin."
                )
            raise RuntimeError(f"SearXNG HTTP {e.code}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"SearXNG'e ulaşılamadı: {e.reason}")

        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
            )
            for item in data.get("results", [])[:max_results]
        ]


class TavilyProvider:
    """Tavily Search API üzerinden arama."""

    name = "tavily"

    def __init__(self, base_url: str, api_key: str, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: str, max_results: int) -> list:
        payload = json.dumps({
            "query": query,
            "max_results": max_results,
            "api_key": self.api_key,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/search",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            data = _http_json(request, self.timeout)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RuntimeError(
                    "Tavily API key geçersiz (401/403). /arama menüsünden kontrol edin."
                )
            raise RuntimeError(f"Tavily HTTP {e.code}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Tavily'ye ulaşılamadı: {e.reason}")

        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
            )
            for item in data.get("results", [])[:max_results]
        ]


def build_provider(config) -> object:
    if config.provider == "searxng":
        if not config.searxng_base_url:
            raise RuntimeError(
                "SearXNG base URL ayarlanmamış. /arama menüsünden girin."
            )
        return SearxngProvider(
            config.searxng_base_url,
            language=config.searxng_language,
            safesearch=config.searxng_safesearch,
            categories=config.searxng_categories,
            timeout=config.timeout,
        )
    if config.provider == "tavily":
        if not config.tavily_api_key:
            raise RuntimeError(
                "Tavily API key ayarlanmamış. /arama menüsünden girin."
            )
        return TavilyProvider(
            config.tavily_base_url, config.tavily_api_key, config.timeout
        )
    raise RuntimeError(f"Bilinmeyen sağlayıcı: {config.provider}")

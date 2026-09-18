"""Çoklu provider destekli context size çözümleyici.

Desteklenen kaynaklar:
- OpenRouter genel model dizini (context_length)
- OrcaRouter (/v1/models, context_length)
- Google Gemini (input_token_limit / context_window)
- Anthropic / Claude (max_input_tokens)
- xAI / Grok (api.x.ai /v1/models, context_length)
- OpenAI-uyumlu sunucular (vLLM, llama.cpp OpenAI modu, LM Studio /v1, vs.)
- Resmi OpenAI: /v1/models context vermez; OpenRouter kataloğuna düşülür
- LM Studio yerel API (/api/v0/models)
- Ollama (/api/show)
- llama.cpp server (/props, /slots)

`resolve_context_size()` sırayla dener; başarılı olan kaynağın adıyla
birlikte (size, source) döndürür. Hiçbiri başarılı olmazsa
(fallback, "fallback") döner.

Eski tek-imzalı API korunmuştur:
    fetch_server_context_size(server_base) -> (n_ctx, fallback_used)
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

FETCH_TIMEOUT = 5

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_ORCAROUTER_MODELS_URL = "https://api.orcarouter.ai/v1/models"
_GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"

_PROVIDER_ALIASES = {
    "claude": "anthropic",
    "orca": "orcarouter",
    "grok": "xai",
    "spacexai": "xai",
}


# ---------------------------------------------------------------- yardımcılar

def _positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _get_json(url: str, headers: dict = None, data: bytes = None):
    """GET/POST isteği atar, JSON yanıtı döndürür; hata olursa None."""
    request = urllib.request.Request(url, headers=headers or {})
    if data is not None:
        request.data = data
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _host(base_url: str) -> str:
    try:
        return urllib.parse.urlparse(base_url).netloc.lower()
    except Exception:
        return ""


def _strip_version(base_url: str) -> str:
    """Sondaki / ve /v1, /v1beta eklerini kırpar."""
    base = (base_url or "").rstrip("/")
    for suffix in ("/v1", "/v1beta"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    return base


def _first_context_field(payload: dict, extra_keys=()):
    # max_tokens kasıtlı olarak yok: Anthropic'te çıktı tavanıdır, context değil.
    keys = ("context_window", "context_length", "input_token_limit",
            "max_context_length", "max_input_tokens",
            "n_ctx") + tuple(extra_keys)
    for key in keys:
        if _positive_int(payload.get(key)):
            return payload[key]
    return None


def _is_snapshot_suffix(suffix: str) -> bool:
    """'20250514' veya '2024-08-06' gibi tarih eklerini tanır."""
    compact = (suffix or "").replace("-", "")
    return compact.isdigit() and len(compact) >= 8


def _fuzzy_match(model: str, candidate: str) -> bool:
    """'openai/gpt-4o' ≈ 'gpt-4o' gibi kimlik varyantlarını eşler."""
    model = (model or "").strip().lower()
    candidate = (candidate or "").strip().lower()
    if not model or not candidate:
        return False
    if model == candidate:
        return True
    tail = candidate.rsplit("/", 1)[-1]
    if model == tail or model.endswith("/" + tail) or candidate.endswith("/" + model):
        return True
    # claude-sonnet-4 ≈ claude-sonnet-4-20250514; gpt-4o ≉ gpt-4o-mini
    if candidate.startswith(model + "-") and _is_snapshot_suffix(candidate[len(model) + 1:]):
        return True
    if model.startswith(candidate + "-") and _is_snapshot_suffix(model[len(candidate) + 1:]):
        return True
    if tail != candidate:
        return _fuzzy_match(model, tail)
    return False


def _extract_context(item: dict):
    """Model kaydından efektif context limitini çıkarır.

    top_provider.context_length (OpenRouter) sunucunun uyguladığı gerçek
    limit olduğu için modelin afişe ettiği context_length'ten önce bakılır.
    """
    for candidate in (item.get("top_provider"), item):
        if isinstance(candidate, dict):
            value = _first_context_field(candidate)
            if value:
                return value
    return None


def _search_model_list(payload, model: str):
    """data/models listesindeki model kaydında context alanını arar."""
    if not isinstance(payload, dict):
        return None

    items = payload.get("data") or payload.get("models")
    if isinstance(items, dict):  # bazı sunucular id->info sözlüğü döndürür
        items = list(items.values())

    exact = None
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            aliases = item.get("aliases")
            alias_hit = (isinstance(aliases, list)
                         and any(_fuzzy_match(model, a)
                                 for a in aliases if isinstance(a, str)))
            if model and (alias_hit
                          or _fuzzy_match(model, item.get("id"))
                          or _fuzzy_match(model, item.get("name"))
                          or _fuzzy_match(model, item.get("display_name"))
                          or _fuzzy_match(model, item.get("canonical_slug"))):
                exact = item
                break

    if exact is None:
        # liste değilse doğrudan payload içinde alan ara
        return _first_context_field(payload)

    return _extract_context(exact)


def _single_entry_context(payload):
    """Tek model sunan yerel uç noktalarda (ör. vLLM) isim eşleşmese de
    listedeki tek kaydı kullanır. Genel model dizinlerinde çağrılmamalıdır."""
    if not isinstance(payload, dict):
        return None
    items = payload.get("data") or payload.get("models")
    if isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict):
        return _extract_context(items[0])
    return None


# ------------------------------------------------------------- provider'lar

def _extract_llamacpp_n_ctx(payload):
    """llama.cpp /props ve /slots yanıtından n_ctx çıkarır.

    /props gerçek context boyutunu default_generation_settings.n_ctx altında
    tutar. Üst düzey total_slots paralel istek sayısıdır (çoğu kurulumda 1)
    ve context size değildir. /slots ya slot nesnelerinden oluşan bir dizi
    ya da {slots: [...]} sarmalayıcısı döner; her slotta n_ctx vardır.
    """
    if isinstance(payload, dict):
        if _positive_int(payload.get("n_ctx")):
            return payload["n_ctx"]
        settings = payload.get("default_generation_settings")
        if isinstance(settings, dict) and _positive_int(settings.get("n_ctx")):
            return settings["n_ctx"]
        for key in ("slots", "data"):
            found = _extract_llamacpp_n_ctx(payload.get(key))
            if found:
                return found
        return None
    if isinstance(payload, list):
        for item in payload:
            found = _extract_llamacpp_n_ctx(item)
            if found:
                return found
    return None


def _fetch_llamacpp(base_url: str, api_key: str, model: str):
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    urls = [f"{base_url}/props"]
    if model:
        urls.append(f"{base_url}/props?{urllib.parse.urlencode({'model': model})}")
    urls.append(f"{base_url}/slots")
    for url in urls:
        n_ctx = _extract_llamacpp_n_ctx(_get_json(url, headers=headers))
        if n_ctx:
            return n_ctx
    return None


def _fetch_ollama(base_url: str, api_key: str, model: str):
    if not model:
        return None
    body = json.dumps({"name": model}).encode("utf-8")
    payload = _get_json(f"{base_url}/api/show", data=body)
    if isinstance(payload, dict):
        for source in (payload, payload.get("model_info")
                       if isinstance(payload.get("model_info"), dict) else None):
            if isinstance(source, dict):
                for key, value in source.items():
                    if key.endswith("context_length") and _positive_int(value):
                        return value
    return None


def _fetch_lmstudio(base_url: str, api_key: str, model: str):
    payload = _get_json(f"{base_url}/api/v0/models")
    if isinstance(payload, list):
        payload = {"data": payload}
    if isinstance(payload, dict):
        return (_search_model_list(payload, model)
                or _single_entry_context(payload))
    return None


def _openai_models_urls(base_url: str):
    """OpenAI-uyumlu /models uçları hem /v1 hem kökte olabilir."""
    base = (base_url or "").rstrip("/")
    stripped = _strip_version(base)
    urls = []
    for candidate in (f"{base}/v1/models", f"{base}/models",
                      f"{stripped}/v1/models", f"{stripped}/models"):
        if candidate not in urls:
            urls.append(candidate)
    return urls


def _fetch_catalog(urls, api_key: str, model: str, allow_single: bool = False):
    """Bearer ile (gerekirse kimliksiz) model listesini çekip context arar."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    for url in urls:
        payload = _get_json(url, headers=headers)
        if payload is None and api_key:
            payload = _get_json(url)
        if not isinstance(payload, dict):
            continue
        size = _search_model_list(payload, model)
        if not size and allow_single:
            size = _single_entry_context(payload)
        if size:
            return size
    return None


def _fetch_openai_compatible(base_url: str, api_key: str, model: str):
    return _fetch_catalog(_openai_models_urls(base_url), api_key, model,
                          allow_single=True)


def _fetch_openrouter(base_url: str, api_key: str, model: str):
    if not model:
        return None
    # Kullanıcı anahtarı OpenRouter'a ait olmayabilir (ör. resmi OpenAI
    # yedek kataloğu); 401 olursa herkese açık dizini dene.
    return _fetch_catalog(
        [_OPENROUTER_MODELS_URL, *_openai_models_urls(base_url)],
        api_key, model, allow_single=False)


def _fetch_orcarouter(base_url: str, api_key: str, model: str):
    if not model:
        return None
    urls = [_ORCAROUTER_MODELS_URL, *_openai_models_urls(base_url)]
    return _fetch_catalog(urls, api_key, model, allow_single=False)


def _fetch_xai(base_url: str, api_key: str, model: str):
    """xAI /v1/models her kayıtta context_length döner (OpenAI resmi API'den farklı)."""
    if not model:
        return None
    return _fetch_catalog(_openai_models_urls(base_url), api_key, model,
                          allow_single=False)


def _fetch_gemini(base_url: str, api_key: str, model: str):
    if not api_key or not model:
        return None
    query = urllib.parse.urlencode({"key": api_key, "pageSize": "1000"})
    payload = _get_json(f"{_GEMINI_MODELS_URL}?{query}")
    if isinstance(payload, dict) and isinstance(payload.get("models"), list):
        wanted = model.rsplit("/", 1)[-1].lower()
        for item in payload["models"]:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").rsplit("/", 1)[-1].lower()
            if wanted and (wanted == name or name.endswith(wanted)):
                value = _first_context_field(item)
                if value:
                    return value
    return None


def _anthropic_context(item: dict):
    """Claude context penceresi max_input_tokens'tır; max_tokens çıktı tavanıdır."""
    if not isinstance(item, dict):
        return None
    for key in ("max_input_tokens", "context_window", "context_length"):
        if _positive_int(item.get(key)):
            return item[key]
    return None


def _fetch_anthropic(base_url: str, api_key: str, model: str):
    if not api_key:
        return None
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    payload = _get_json(f"{_ANTHROPIC_MODELS_URL}?limit=1000", headers=headers)
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        size = _search_model_list(payload, model)
        if size:
            return size
        if model:
            for item in payload["data"]:
                if isinstance(item, dict) and (
                    _fuzzy_match(model, item.get("id"))
                    or _fuzzy_match(model, item.get("display_name"))
                ):
                    size = _anthropic_context(item)
                    if size:
                        return size
                    break
    if model:
        encoded = urllib.parse.quote(model, safe="")
        item = _get_json(f"{_ANTHROPIC_MODELS_URL}/{encoded}", headers=headers)
        size = _anthropic_context(item) if isinstance(item, dict) else None
        if size:
            return size
    return None


PROVIDER_FETCHERS = {
    "llamacpp": _fetch_llamacpp,
    "ollama": _fetch_ollama,
    "lmstudio": _fetch_lmstudio,
    "openai": _fetch_openai_compatible,
    "openrouter": _fetch_openrouter,
    "orcarouter": _fetch_orcarouter,
    "xai": _fetch_xai,
    "gemini": _fetch_gemini,
    "anthropic": _fetch_anthropic,
}

# Resmi bulut API'leri yerel llama.cpp/Ollama yoklamasın; context yoksa
# OpenRouter genel kataloğu yedek kaynaktır (özellikle api.openai.com).
_CLOUD_FALLBACK = {
    "openai": ["openai", "openrouter"],
    "orcarouter": ["orcarouter", "openrouter"],
    "openrouter": ["openrouter"],
    "anthropic": ["anthropic", "openrouter"],
    "gemini": ["gemini", "openrouter"],
    "xai": ["xai", "openrouter"],
}


def _normalize_provider(name: str) -> str:
    name = (name or "").strip().lower()
    return _PROVIDER_ALIASES.get(name, name)


def _detect_provider(host: str) -> str:
    """Ana makine adından provider tahmini. Bilinmiyorsa boş string."""
    if "openrouter" in host:
        return "openrouter"
    if "orcarouter" in host:
        return "orcarouter"
    if "generativelanguage.googleapis.com" in host or "aiplatform.googleapis.com" in host:
        return "gemini"
    if "anthropic.com" in host:
        return "anthropic"
    if host == "api.x.ai" or host.endswith(".api.x.ai") or host.endswith(".x.ai"):
        return "xai"
    if "ollama" in host or host.endswith(":11434"):
        return "ollama"
    if "lmstudio" in host or host.endswith(":1234"):
        return "lmstudio"
    if host == "api.openai.com" or "openai.azure.com" in host or host.endswith(".azure.com"):
        return "openai"
    if host.endswith(":8080"):
        return "llamacpp"
    return ""


def _provider_attempt_order(host: str, explicit: str):
    """Denecek provider adlarını sırayla döndürür."""
    if explicit:
        return [_normalize_provider(explicit)]

    detected = _detect_provider(host)
    if detected in _CLOUD_FALLBACK:
        return list(_CLOUD_FALLBACK[detected])
    if detected:
        return [detected]

    # Bilinmeyen host: yerel sunucuları sırayla yokla, sonra genel dizinlere bak.
    order = ["llamacpp", "ollama", "lmstudio"]
    if host and host not in ("openrouter.ai", "api.anthropic.com",
                             "generativelanguage.googleapis.com",
                             "api.orcarouter.ai"):
        order.append("openai")
    order.append("openrouter")  # genel model dizini: model adı eşleşirse çalışır
    return order


# ------------------------------------------------------------------ ana API

def resolve_context_size(api_base_url, api_key, model,
                         fallback: int = 4096, provider: str = None) -> tuple:
    """Birden çok provider'dan model context size'ını çeker.

    Döndürür: (context_size, source)
        source: 'openrouter' | 'orcarouter' | 'xai' | 'gemini' | 'anthropic' |
                'openai' | 'ollama' | 'lmstudio' | 'llamacpp' | 'fallback'
    """
    fallback = fallback or 4096

    if api_base_url:
        base_url = _strip_version(api_base_url)
        host = _host(api_base_url)
        explicit = _normalize_provider(
            provider or os.environ.get("CONTEXT_PROVIDER", ""))
        for name in _provider_attempt_order(host, explicit):
            fetcher = PROVIDER_FETCHERS.get(name)
            if fetcher is None:
                continue
            try:
                size = fetcher(base_url, api_key, model)
            except Exception:
                size = None
            if _positive_int(size):
                return size, name

    return fallback, "fallback"


# ------------------------------------------- geriye dönük uyumlu eski API

def fetch_server_context_size(server_base: str) -> tuple:
    """(n_ctx, fallback_used) döner. llama.cpp /props ve /slots uçlarını sorgular."""
    size, source = resolve_context_size(server_base, None, None,
                                        fallback=4096, provider="llamacpp")
    return size, source == "fallback"

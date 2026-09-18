"""llm/server_info.py birim testleri (harici ağ isteği yapmaz)."""

import unittest
from unittest import mock

from llm import server_info
from llm.server_info import (
    _extract_llamacpp_n_ctx,
    _fuzzy_match,
    _host,
    _positive_int,
    _provider_attempt_order,
    _search_model_list,
    _strip_version,
    resolve_context_size,
)


class TestHelpers(unittest.TestCase):
    def test_positive_int(self):
        self.assertTrue(_positive_int(8192))
        self.assertFalse(_positive_int(0))
        self.assertFalse(_positive_int(-1))
        self.assertFalse(_positive_int(True))
        self.assertFalse(_positive_int("8192"))
        self.assertFalse(_positive_int(None))

    def test_host(self):
        self.assertEqual(_host("https://openrouter.ai/api/v1"), "openrouter.ai")
        self.assertEqual(_host("http://127.0.0.1:8080"), "127.0.0.1:8080")
        self.assertEqual(_host(""), "")

    def test_strip_version(self):
        self.assertEqual(_strip_version("https://x.com/v1/"), "https://x.com")
        self.assertEqual(_strip_version("https://x.com/v1beta"), "https://x.com")
        self.assertEqual(_strip_version("http://127.0.0.1:8080"), "http://127.0.0.1:8080")

    def test_fuzzy_match(self):
        self.assertTrue(_fuzzy_match("openai/gpt-4o", "openai/gpt-4o"))
        self.assertTrue(_fuzzy_match("openai/gpt-4o", "gpt-4o"))
        self.assertTrue(_fuzzy_match("gpt-4o", "openai/gpt-4o"))
        self.assertFalse(_fuzzy_match("gpt-4o", "gpt-4o-mini"))
        self.assertFalse(_fuzzy_match("", "gpt-4o"))
        self.assertTrue(_fuzzy_match("claude-sonnet-4", "claude-sonnet-4-20250514"))
        self.assertTrue(_fuzzy_match("claude-sonnet-4", "anthropic/claude-sonnet-4-20250514"))
        self.assertTrue(_fuzzy_match("gpt-4o", "gpt-4o-2024-08-06"))
        self.assertFalse(_fuzzy_match("gpt-4o", "gpt-4o-mini-2024-07-18"))


class TestSearchModelList(unittest.TestCase):
    def test_openrouter_exact_match_uses_top_provider(self):
        payload = {"data": [
            {"id": "openai/gpt-4o", "context_length": 128000},
            {"id": "anthropic/claude-3", "context_length": 200000},
        ]}
        self.assertEqual(_search_model_list(payload, "openai/gpt-4o"), 128000)

    def test_match_by_aliases(self):
        payload = {"data": [{
            "id": "grok-4.6",
            "aliases": ["grok-latest"],
            "context_length": 500000,
        }]}
        self.assertEqual(_search_model_list(payload, "grok-latest"), 500000)

    def test_match_by_tail_id(self):
        payload = {"data": [{"id": "anthropic/claude-3-sonnet", "context_length": 200000}]}
        self.assertEqual(_search_model_list(payload, "claude-3-sonnet"), 200000)

    def test_top_provider_preferred(self):
        payload = {"data": [{
            "id": "m",
            "context_length": 1000,
            "top_provider": {"context_length": 500},
        }]}
        self.assertEqual(_search_model_list(payload, "m"), 500)

    def test_anthropic_style_fields(self):
        payload = {"data": [{"id": "claude-opus-5", "max_input_tokens": 200000}]}
        self.assertEqual(_search_model_list(payload, "claude-opus-5"), 200000)

    def test_single_entry_list(self):
        # Genel arama isim eşleşmese kendini zorlamaz...
        payload = {"data": [{"id": "whatever", "context_length": 4096}]}
        self.assertIsNone(_search_model_list(payload, "unrelated-model"))
        # ...yerel tek-model uçlar için ayrı fonksiyon devreye girer.
        from llm.server_info import _single_entry_context
        self.assertEqual(_single_entry_context(payload), 4096)
        self.assertIsNone(_single_entry_context({"data": [{"id": "a"}, {"id": "b"}]}))

    def test_no_match_returns_none(self):
        payload = {"data": [{"id": "a", "context_length": 1}]}
        self.assertIsNone(_search_model_list(payload, "b"))

    def test_non_dict_payload(self):
        self.assertIsNone(_search_model_list(None, "m"))
        self.assertIsNone(_search_model_list([1, 2], "m"))


class TestProviderOrder(unittest.TestCase):
    def test_explicit_provider_first(self):
        self.assertEqual(_provider_attempt_order("any.host", "anthropic"), ["anthropic"])

    def test_detect_openrouter(self):
        order = _provider_attempt_order("openrouter.ai", "")
        self.assertEqual(order[0], "openrouter")

    def test_detect_orcarouter(self):
        order = _provider_attempt_order("api.orcarouter.ai", "")
        self.assertEqual(order[0], "orcarouter")
        self.assertEqual(order, ["orcarouter", "openrouter"])

    def test_detect_openai_official_skips_local_probes(self):
        order = _provider_attempt_order("api.openai.com", "")
        self.assertEqual(order, ["openai", "openrouter"])
        self.assertNotIn("llamacpp", order)

    def test_detect_xai(self):
        self.assertEqual(
            _provider_attempt_order("api.x.ai", ""), ["xai", "openrouter"])
        self.assertEqual(
            _provider_attempt_order("us.api.x.ai", "")[0], "xai")
        self.assertEqual(_provider_attempt_order("any.host", "grok"), ["xai"])

    def test_claude_alias(self):
        self.assertEqual(_provider_attempt_order("any.host", "claude"), ["anthropic"])

    def test_detect_llamacpp_port(self):
        order = _provider_attempt_order("127.0.0.1:8080", "")
        self.assertEqual(order[0], "llamacpp")

    def test_unknown_host_probes_locals_then_directory(self):
        order = _provider_attempt_order("example.com", "")
        self.assertEqual(order, ["llamacpp", "ollama", "lmstudio", "openai", "openrouter"])

    def test_unknown_host_openai_omitted_for_known_directories(self):
        order = _provider_attempt_order("api.anthropic.com", "")
        self.assertNotIn("openai", order)
        self.assertEqual(order[0], "anthropic")


class TestResolveContextSize(unittest.TestCase):
    def setUp(self):
        server_info.FETCH_TIMEOUT = 1

    def test_success_returns_source(self):
        with mock.patch.dict(server_info.PROVIDER_FETCHERS,
                             {"openrouter": lambda *a, **k: 128000}):
            size, source = resolve_context_size(
                "https://openrouter.ai/api/v1", "key", "openai/gpt-4o")
        self.assertEqual(size, 128000)
        self.assertEqual(source, "openrouter")

    def test_all_fail_returns_fallback(self):
        with mock.patch.object(server_info, "PROVIDER_FETCHERS", {}):
            size, source = resolve_context_size(
                "https://example.com", "key", "m", fallback=8192)
        self.assertEqual(size, 8192)
        self.assertEqual(source, "fallback")

    def test_fetcher_exception_is_swallowed(self):
        def boom(*args, **kwargs):
            raise RuntimeError("boom")
        with mock.patch.dict(server_info.PROVIDER_FETCHERS, {"openrouter": boom}):
            size, source = resolve_context_size(
                "https://openrouter.ai/api/v1", "key", "m", fallback=4096)
        self.assertEqual(size, 4096)
        self.assertEqual(source, "fallback")

    def test_no_base_url_returns_fallback(self):
        size, source = resolve_context_size(None, "key", "m")
        self.assertEqual((size, source), (4096, "fallback"))

    def test_llamacpp_props_nested_n_ctx(self):
        props = {
            "default_generation_settings": {
                "id": 0,
                "n_ctx": 65536,
                "params": {"max_tokens": -1, "temperature": 0.8},
            },
            "total_slots": 1,
            "model_path": "model.gguf",
        }

        def fake_get(url, headers=None, data=None):
            if "/props" in url:
                return props
            return None

        with mock.patch.object(server_info, "_get_json", side_effect=fake_get):
            size, source = resolve_context_size(
                "http://127.0.0.1:8080/v1", None, "local", provider="llamacpp")
        self.assertEqual(size, 65536)
        self.assertEqual(source, "llamacpp")

    def test_llamacpp_does_not_treat_total_slots_as_context(self):
        def fake_get(url, headers=None, data=None):
            if url.endswith("/props"):
                return {"total_slots": 1, "model_path": "x.gguf"}
            if url.endswith("/slots"):
                return [{"id": 0, "n_ctx": 8192, "is_processing": False}]
            return None

        with mock.patch.object(server_info, "_get_json", side_effect=fake_get):
            size, source = resolve_context_size(
                "http://127.0.0.1:8080", None, None, provider="llamacpp")
        self.assertEqual(size, 8192)
        self.assertEqual(source, "llamacpp")

    def test_llamacpp_slots_wrapped_dict(self):
        def fake_get(url, headers=None, data=None):
            if url.endswith("/slots"):
                return {"slots": [{"n_ctx": 4096}]}
            return None

        with mock.patch.object(server_info, "_get_json", side_effect=fake_get):
            size, source = resolve_context_size(
                "http://127.0.0.1:8080", None, None, provider="llamacpp")
        self.assertEqual((size, source), (4096, "llamacpp"))

    def test_xai_context_length_and_aliases(self):
        catalog = {"object": "list", "data": [{
            "id": "grok-4.6",
            "aliases": ["grok-latest"],
            "context_length": 500000,
            "owned_by": "xai",
        }]}

        def fake_get(url, headers=None, data=None):
            if "api.x.ai" in url and url.endswith("/models"):
                return catalog
            return None

        with mock.patch.object(server_info, "_get_json", side_effect=fake_get):
            size, source = resolve_context_size(
                "https://api.x.ai/v1", "xai-key", "grok-latest")
        self.assertEqual((size, source), (500000, "xai"))

    def test_orcarouter_context_length(self):
        catalog = {"data": [
            {"id": "openai/gpt-4o-mini", "context_length": 128000,
             "max_completion_tokens": 16384},
            {"id": "anthropic/claude-sonnet-4", "context_length": 200000},
        ]}

        def fake_get(url, headers=None, data=None):
            if "orcarouter" in url and url.endswith("/models"):
                return catalog
            return None

        with mock.patch.object(server_info, "_get_json", side_effect=fake_get):
            size, source = resolve_context_size(
                "https://api.orcarouter.ai/v1", "sk-orca-x",
                "openai/gpt-4o-mini")
        self.assertEqual((size, source), (128000, "orcarouter"))

    def test_openai_official_falls_back_to_openrouter_catalog(self):
        openai_models = {"data": [
            {"id": "gpt-4o", "object": "model", "owned_by": "openai"},
        ]}
        openrouter_models = {"data": [
            {"id": "openai/gpt-4o", "context_length": 128000,
             "top_provider": {"context_length": 128000}},
        ]}

        def fake_get(url, headers=None, data=None):
            if "openrouter.ai" in url:
                return openrouter_models
            if "api.openai.com" in url:
                return openai_models
            return None

        with mock.patch.object(server_info, "_get_json", side_effect=fake_get):
            size, source = resolve_context_size(
                "https://api.openai.com/v1", "sk-openai", "gpt-4o")
        self.assertEqual(size, 128000)
        self.assertEqual(source, "openrouter")

    def test_openai_compat_queries_v1_models(self):
        seen = []

        def fake_get(url, headers=None, data=None):
            seen.append(url)
            if url.endswith("/v1/models"):
                return {"data": [{"id": "local-model", "context_length": 8192}]}
            return None

        with mock.patch.object(server_info, "_get_json", side_effect=fake_get):
            size, source = resolve_context_size(
                "https://proxy.example/v1", "key", "local-model",
                provider="openai")
        self.assertEqual((size, source), (8192, "openai"))
        self.assertTrue(any(u.endswith("/v1/models") for u in seen))

    def test_anthropic_uses_max_input_tokens_not_max_tokens(self):
        payload = {"data": [{
            "id": "claude-sonnet-4-20250514",
            "display_name": "Claude Sonnet 4",
            "max_input_tokens": 200000,
            "max_tokens": 64000,
        }]}

        def fake_get(url, headers=None, data=None):
            if "api.anthropic.com" in url:
                return payload
            return None

        with mock.patch.object(server_info, "_get_json", side_effect=fake_get):
            size, source = resolve_context_size(
                "https://api.anthropic.com", "sk-ant", "claude-sonnet-4")
        self.assertEqual((size, source), (200000, "anthropic"))

    def test_openrouter_retries_without_foreign_api_key(self):
        calls = []

        def fake_get(url, headers=None, data=None):
            calls.append(headers or {})
            if headers and headers.get("Authorization"):
                return None
            return {"data": [{"id": "openai/gpt-4o", "context_length": 128000}]}

        with mock.patch.object(server_info, "_get_json", side_effect=fake_get):
            size, source = resolve_context_size(
                "https://openrouter.ai/api/v1", "sk-openai-not-or", "openai/gpt-4o")
        self.assertEqual((size, source), (128000, "openrouter"))
        self.assertTrue(any("Authorization" not in c for c in calls))


class TestExtractLlamacppNCtx(unittest.TestCase):
    def test_props_nested_settings(self):
        payload = {
            "default_generation_settings": {"n_ctx": 32768, "id": 0},
            "total_slots": 1,
        }
        self.assertEqual(_extract_llamacpp_n_ctx(payload), 32768)

    def test_total_slots_alone_is_not_context(self):
        self.assertIsNone(_extract_llamacpp_n_ctx({
            "total_slots": 1,
            "model_path": "x.gguf",
        }))

    def test_slots_list(self):
        self.assertEqual(
            _extract_llamacpp_n_ctx([{"id": 0, "n_ctx": 8192}]),
            8192,
        )

    def test_direct_n_ctx(self):
        self.assertEqual(_extract_llamacpp_n_ctx({"n_ctx": 2048}), 2048)

    def test_ignores_non_positive(self):
        self.assertIsNone(_extract_llamacpp_n_ctx({"n_ctx": 0}))
        self.assertIsNone(_extract_llamacpp_n_ctx(None))
        self.assertIsNone(_extract_llamacpp_n_ctx("nope"))


if __name__ == "__main__":
    unittest.main()

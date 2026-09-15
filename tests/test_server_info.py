"""llm/server_info.py birim testleri (harici ağ isteği yapmaz)."""

import unittest
from unittest import mock

from llm import server_info
from llm.server_info import (
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


class TestSearchModelList(unittest.TestCase):
    def test_openrouter_exact_match_uses_top_provider(self):
        payload = {"data": [
            {"id": "openai/gpt-4o", "context_length": 128000},
            {"id": "anthropic/claude-3", "context_length": 200000},
        ]}
        self.assertEqual(_search_model_list(payload, "openai/gpt-4o"), 128000)

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

    def test_detect_llamacpp_port(self):
        order = _provider_attempt_order("127.0.0.1:8080", "")
        self.assertEqual(order[0], "llamacpp")

    def test_unknown_host_probes_locals_then_directory(self):
        order = _provider_attempt_order("example.com", "")
        self.assertEqual(order, ["llamacpp", "ollama", "lmstudio", "openai", "openrouter"])

    def test_unknown_host_openai_omitted_for_known_directories(self):
        order = _provider_attempt_order("api.anthropic.com", "")
        self.assertNotIn("openai", order)


class TestResolveContextSize(unittest.TestCase):
    def setUp(self):
        server_info.FETCH_TIMEOUT = 1

    def test_success_returns_source(self):
        with mock.patch.object(server_info, "_fetch_openrouter", return_value=128000):
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
        with mock.patch.object(server_info, "_fetch_openrouter",
                               side_effect=RuntimeError("boom")):
            size, source = resolve_context_size(
                "https://openrouter.ai/api/v1", "key", "m", fallback=4096)
        self.assertEqual(size, 4096)
        self.assertEqual(source, "fallback")

    def test_no_base_url_returns_fallback(self):
        size, source = resolve_context_size(None, "key", "m")
        self.assertEqual((size, source), (4096, "fallback"))


if __name__ == "__main__":
    unittest.main()

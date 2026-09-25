"""Reasoning effort payload testleri (instruction.md senaryoları).

Request-payload seviyesinde doğrulama: hangi provider/model/API türünde
hangi alanın, hangi değerle gönderildiği (veya omit edildiği), effort
normalization kuralları ve 400 retry/cache davranışı.
"""

import sys
import types
import unittest
from unittest import mock

_m = types.ModuleType("dotenv")
_m.load_dotenv = lambda *a, **k: None
sys.modules.setdefault("dotenv", _m)

from llm.reasoning import (  # noqa: E402
    API_ANTHROPIC,
    API_LLAMACPP,
    API_NONE,
    API_OPENAI,
    API_OPENROUTER,
    is_reasoning_related_error,
    normalize_effort,
    resolve_reasoning_config as resolve,
)
from llm.anthropic_transport import build_payload  # noqa: E402
from llm.client import LLMClient  # noqa: E402
from config import Config  # noqa: E402


def _cfg(base: str, model: str, reasoning_api: str = "auto") -> Config:
    return Config(
        server_base=base, api_base_url=base, api_key="sk-test", agent_model=model,
        whisper_bin="w", whisper_model="m", whisper_lang="tr",
        pipe_path="/tmp/p", chat_directory="chats", context_fallback=4096,
        context_safety_ratio=0.85, context_provider="", system_prompt="",
        provider_selection="t", reasoning_api=reasoning_api,
    )


class TestNormalize(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(normalize_effort("middle"), "medium")
        self.assertEqual(normalize_effort("x-high"), "xhigh")
        self.assertEqual(normalize_effort("off"), "none")
        self.assertEqual(normalize_effort("garbage"), "high")

    def test_canonical_pass_through(self):
        for lv in ("none", "minimal", "low", "medium", "high", "xhigh", "max"):
            self.assertEqual(normalize_effort(lv), lv)


class TestLlamaCpp(unittest.TestCase):
    def test_reasoning_model_exact(self):
        rc = resolve("http://127.0.0.1:8080/v1", "Bonsai-2", "xhigh")
        self.assertEqual(rc.api_type, API_LLAMACPP)
        self.assertEqual(rc.effort, "xhigh")
        self.assertFalse(rc.omitted)

    def test_none_disables_thinking(self):
        rc = resolve("http://127.0.0.1:8080/v1", "Bonsai-2", "none")
        self.assertTrue(rc.disable_thinking)
        self.assertEqual(rc.effort, "")

    def test_unknown_private_host_uses_llamacpp(self):
        rc = resolve("http://192.168.1.5:8080/v1", "m", "high")
        self.assertEqual(rc.api_type, API_LLAMACPP)


class TestOpenAI(unittest.TestCase):
    def test_reasoning_model_gpt5(self):
        rc = resolve("https://api.openai.com/v1", "gpt-5.2", "xhigh")
        self.assertEqual(rc.api_type, API_OPENAI)
        self.assertEqual(rc.effort, "xhigh")

    def test_o_series_downgrade_not_upgrade(self):
        rc = resolve("https://api.openai.com/v1", "o3-mini", "xhigh")
        self.assertEqual(rc.effort, "high")          # aşağı normalize
        rc = resolve("https://api.openai.com/v1", "o1-preview", "none")
        self.assertNotIn(rc.effort, ("medium", "high"))  # yükseltme yok

    def test_non_reasoning_model_omits(self):
        rc = resolve("https://api.openai.com/v1", "gpt-4o-mini", "high")
        self.assertTrue(rc.omitted)
        self.assertIn("unsupported", rc.note)

    def test_low_requested_missing_stays_omitted(self):
        # low istendi ama model yalnızca medium/high destekliyor → omit
        rc = resolve("https://api.openai.com/v1", "o3-mini", "minimal")
        self.assertNotEqual(rc.effort, "medium")
        self.assertNotEqual(rc.effort, "high")


class TestOpenRouter(unittest.TestCase):
    def test_reasoning_object(self):
        rc = resolve("https://openrouter.ai/api/v1", "deepseek/deepseek-r1",
                     "xhigh")
        self.assertEqual(rc.api_type, API_OPENROUTER)
        self.assertEqual(rc.effort, "xhigh")


class TestGemini(unittest.TestCase):
    def test_openai_compat_effort(self):
        rc = resolve("https://generativelanguage.googleapis.com/v1beta/openai/",
                     "models/gemini-2.5-flash", "xhigh")
        self.assertEqual(rc.api_type, API_OPENAI)
        self.assertEqual(rc.effort, "high")          # aşağı normalize
        self.assertIn("Gemini", rc.note)

    def test_unknown_gemini_model_omits(self):
        rc = resolve("https://generativelanguage.googleapis.com/v1beta/openai/",
                     "models/something-new", "high")
        self.assertTrue(rc.omitted)


class TestClaude(unittest.TestCase):
    def test_native_output_config(self):
        rc = resolve("https://api.anthropic.com/v1", "claude-sonnet-4-5", "max")
        self.assertEqual(rc.api_type, API_ANTHROPIC)
        self.assertEqual(rc.effort, "max")

    def test_native_payload_has_only_output_config(self):
        body = build_payload("claude-sonnet-4-5",
                             [{"role": "user", "content": "hi"}],
                             effort="xhigh")
        self.assertEqual(body["output_config"], {"effort": "xhigh"})
        self.assertNotIn("reasoning_effort", body)
        self.assertNotIn("reasoning", body)
        self.assertNotIn("chat_template_kwargs", body)

    def test_openai_compat_path_does_not_claim_effort(self):
        # Anthropic'in OpenAI-uyumluluk katmanı reasoning_effort'u yok sayar;
        # uyumluluk yolu adapter'da native transport'a yönlenir, UI iddiası olmaz.
        rc = resolve("https://api.anthropic.com/v1", "claude-sonnet-4-5", "high")
        self.assertEqual(rc.api_type, API_ANTHROPIC)   # native yolda çözülür


class TestGroq(unittest.TestCase):
    def test_gpt_oss_downgrade(self):
        rc = resolve("https://api.groq.com/openai/v1", "gpt-oss-120b", "xhigh")
        self.assertEqual(rc.effort, "high")

    def test_unknown_groq_model_omits(self):
        rc = resolve("https://api.groq.com/openai/v1", "llama-3.3-70b", "high")
        self.assertTrue(rc.omitted)


class TestXAI(unittest.TestCase):
    def test_grok4_xhigh(self):
        rc = resolve("https://api.x.ai/v1", "grok-4", "xhigh")
        self.assertEqual(rc.effort, "xhigh")


class TestDocumentedEffortProviders(unittest.TestCase):
    def test_fireworks_known_model_sends_effort(self):
        rc = resolve(
            "https://api.fireworks.ai/inference/v1",
            "accounts/fireworks/models/glm-5p3", "medium")
        self.assertEqual(rc.api_type, API_OPENAI)
        self.assertEqual(rc.effort, "medium")

    def test_cerebras_qwen(self):
        rc = resolve("https://api.cerebras.ai/v1", "qwen-3.8-27b", "high")
        self.assertEqual(rc.effort, "high")

    def test_mistral_only_none_and_high(self):
        rc = resolve("https://api.mistral.ai/v1", "mistral-small-latest", "high")
        self.assertEqual(rc.effort, "high")
        rc = resolve("https://api.mistral.ai/v1", "mistral-small-latest", "medium")
        self.assertEqual(rc.effort, "none")
        rc = resolve("https://api.mistral.ai/v1", "magistral-small-2506", "high")
        self.assertTrue(rc.omitted)

    def test_together_gpt_oss(self):
        rc = resolve("https://api.together.xyz/v1", "openai/gpt-oss-120b", "low")
        self.assertEqual(rc.effort, "low")

    def test_unknown_model_on_those_hosts_still_omits(self):
        for url in ("https://api.cerebras.ai/v1", "https://api.together.xyz/v1",
                    "https://api.mistral.ai/v1",
                    "https://api.fireworks.ai/inference/v1"):
            rc = resolve(url, "some-model", "high")
            self.assertTrue(rc.omitted, url)


class TestUnknownProvider(unittest.TestCase):
    def test_unknown_cloud_omits(self):
        rc = resolve("https://api.unknown-gw.io/v1", "mystic", "high")
        self.assertEqual(rc.api_type, API_NONE)
        self.assertTrue(rc.omitted)

    def test_cerebras_together_etc_omits(self):
        for url in ("https://api.cerebras.ai/v1", "https://api.together.xyz/v1",
                    "https://api.mistral.ai/v1",
                    "https://api.fireworks.ai/inference/v1",
                    "https://opencode.ai/zen/v1"):
            rc = resolve(url, "some-model", "high")
            self.assertTrue(rc.omitted, url)


class TestConfigOverride(unittest.TestCase):
    def test_override_openai(self):
        rc = resolve("https://api.unknown-gw.io/v1", "m", "high",
                     override="openai")
        self.assertEqual(rc.api_type, API_OPENAI)

    def test_override_none_disables(self):
        rc = resolve("http://127.0.0.1:8080/v1", "Bonsai-2", "high",
                     override="none")
        self.assertTrue(rc.omitted)

    def test_override_llamacpp_on_cloud(self):
        rc = resolve("https://api.openai.com/v1", "gpt-5.2", "high",
                     override="llamacpp")
        self.assertEqual(rc.api_type, API_LLAMACPP)

    def test_config_carries_reasoning_api(self):
        client = LLMClient(_cfg("http://127.0.0.1:8080/v1", "Bonsai-2",
                                reasoning_api="openai"))
        self.assertEqual(client.reasoning_api_override, "openai")


class TestSingleFormatRule(unittest.TestCase):
    def test_extra_body_single_format(self):
        client = LLMClient(_cfg("http://127.0.0.1:8080/v1", "Bonsai-2"))
        from llm.reasoning import ReasoningConfig, API_LLAMACPP, API_OPENAI, \
            API_OPENROUTER
        rc = ReasoningConfig(API_LLAMACPP, effort="high")
        body = client._extra_body_for(rc)
        self.assertIn("chat_template_kwargs", body)
        self.assertNotIn("reasoning_effort", body)
        rc = ReasoningConfig(API_OPENAI, effort="high")
        body = client._extra_body_for(rc)
        self.assertIn("reasoning_effort", body)
        self.assertNotIn("chat_template_kwargs", body)
        rc = ReasoningConfig(API_OPENROUTER, effort="high")
        body = client._extra_body_for(rc)
        self.assertEqual(body.get("reasoning"), {"effort": "high"})
        self.assertNotIn("reasoning_effort", body)


class TestRetryAndCache(unittest.TestCase):
    def _client(self):
        return LLMClient(_cfg("https://api.example-gw.io/v1", "m1"))

    def test_reasoning_400_retries_once_and_caches(self):
        # custom gateway + tabloya uyan model: adapter effort gönderir,
        # sunucu 400 verirse tek retry + cache devreye girer
        client = LLMClient(_cfg("https://api.example-gw.io/v1", "gpt-5.2"))
        client.reasoning_api_override = "openai"

        calls = []

        class FakeDelta:
            content = "x"
            reasoning_content = None

        class FakeChoice:
            delta = FakeDelta()

        class FakeChunk:
            choices = [FakeChoice()]
            usage = None

        class FakeRenderer:
            def __getattr__(self, name):
                return lambda *a, **k: None

        def fake_create(**kw):
            calls.append(kw)
            if kw.get("extra_body"):
                raise RuntimeError(
                    'Error code: 400 - Unknown name "reasoning_effort": '
                    "Cannot find field.")
            return iter([FakeChunk()])

        client._client.chat.completions.create = fake_create
        res = client.stream([{"role": "user", "content": "hi"}],
                            renderer=FakeRenderer(), reasoning_effort="high")
        self.assertEqual(len(calls), 2)             # 1 hatalı + 1 sade
        self.assertIsNone(calls[1]["extra_body"])   # ikinci istek effortsüz
        self.assertIn("unsupported", client.last_effort_note)
        # cache: sonraki çağrı doğrudan sade gider
        res = client.stream([{"role": "user", "content": "hi"}],
                            renderer=FakeRenderer(), reasoning_effort="high")
        self.assertEqual(len(calls), 3)
        self.assertIsNone(calls[2]["extra_body"])

    def test_non_reasoning_400_no_retry(self):
        client = LLMClient(_cfg("https://api.example-gw.io/v1", "gpt-5.2"))
        client.reasoning_api_override = "openai"
        calls = []

        def fake_create(**kw):
            calls.append(kw)
            raise RuntimeError("Error code: 401 - invalid api key")

        client._client.chat.completions.create = fake_create
        with self.assertRaises(RuntimeError):
            client.stream([{"role": "user", "content": "hi"}],
                          renderer=object(), reasoning_effort="high")
        self.assertEqual(len(calls), 1)             # retry yok


class TestErrorClassification(unittest.TestCase):
    def test_reasoning_related(self):
        self.assertTrue(is_reasoning_related_error(
            'Error code: 400 - Unknown name "chat_template_kwargs"'))
        self.assertTrue(is_reasoning_related_error(
            "400 reasoning_effort is not supported"))

    def test_unrelated(self):
        self.assertFalse(is_reasoning_related_error(
            "Error code: 401 - incorrect api key"))
        self.assertFalse(is_reasoning_related_error(
            "Error code: 429 - rate limit"))
        self.assertFalse(is_reasoning_related_error(
            "Error code: 400 - malformed message content"))


if __name__ == "__main__":
    unittest.main()

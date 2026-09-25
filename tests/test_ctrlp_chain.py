"""Ctrl+P → state → client → payload zincir testleri.

instruction2.md kabul kriteri: Ctrl+P ile seçilen TEK canonical effort
değeri, aktif provider ne olursa olsun aynı runtime state üzerinden
provider adapter'a ulaşmalı. Bu testler zinciri gerçek kod yollarıyla
(headless Ctrl+P simülasyonu dahil) doğrular.
"""

import io
import sys
import types
import unittest
from unittest import mock

_m = types.ModuleType("dotenv")
_m.load_dotenv = lambda *a, **k: None
sys.modules.setdefault("dotenv", _m)

from state import ApplicationState  # noqa: E402
from config import Config  # noqa: E402
from ui.page import Page  # noqa: E402
from llm.client import LLMClient  # noqa: E402
from llm.reasoning import normalize_effort  # noqa: E402
import llm.anthropic_transport as anthro  # noqa: E402


def _cfg(base: str, model: str) -> Config:
    return Config(
        server_base=base, api_base_url=base, api_key="sk-test", agent_model=model,
        whisper_bin="w", whisper_model="m", whisper_lang="tr",
        pipe_path="/tmp/p", chat_directory="chats", context_fallback=4096,
        context_safety_ratio=0.85, context_provider="", system_prompt="",
        provider_selection="t",
    )


class _FakeRenderer:
    """StreamParser'ın çağırdığı tüm show_* metodlarını yutar."""

    def __getattr__(self, name):
        return lambda *a, **k: None


class _HeadlessPage(Page):
    """tty'siz ortamda _pick_effort çalıştırılabilen sayfa."""

    def __init__(self):
        super().__init__("T")
        self.active = True
        self._rows, self._cols = 24, 100
        self._real_stdout = io.StringIO()


def _wire(state: ApplicationState, page: Page):
    """application.py'deki gerçek bağlantının birebir aynısı."""
    page.set_effort(state.reasoning_effort)
    page.set_effort_callback(
        lambda lvl: setattr(state, "reasoning_effort", lvl)
    )


class _CaptureClient(LLMClient):
    """OpenAI create çağrısını yakalayan client."""

    def __init__(self, cfg, fail_first_with: str = None):
        super().__init__(cfg)
        self.calls = []
        self._fail_first_with = fail_first_with

    def _openai_create_for_test(self, **kw):
        self.calls.append(kw)
        if self._fail_first_with and len(self.calls) == 1:
            raise RuntimeError(self._fail_first_with)
        return self._fake_stream()

    @staticmethod
    def _fake_stream():
        class D:
            content = "ok"
            reasoning_content = None

        class C:
            delta = D()

        class Chunk:
            choices = [C()]
            usage = None

        return iter([Chunk()])


class TestCtrlPHandlerChain(unittest.TestCase):
    """1) Ctrl+P gerçek Page kod yoluyla state'i değiştiriyor mu?"""

    def test_ctrlp_selection_updates_runtime_state(self):
        state = ApplicationState()          # auto / None
        page = _HeadlessPage()
        _wire(state, page)

        # auto(0) → none → minimal → low → medium
        keys = ["down", "down", "down", "down", "enter"]
        import ui.page as P
        with mock.patch.object(P, "read_key", lambda fd, **k: keys.pop(0)), \
             mock.patch.object(P, "select") as fake_sel:
            fake_sel.select = lambda *a, **k: (True, 0, 0)
            page._pick_effort()

        self.assertEqual(page._effort, "medium")        # UI gösterimi
        self.assertEqual(state.reasoning_effort, "medium")  # MERKEZİ STATE

    def test_provider_switch_keeps_state(self):
        state = ApplicationState()
        state.reasoning_effort = "high"
        page = _HeadlessPage()
        _wire(state, page)

        keys = ["down", "enter"]            # high → xhigh
        import ui.page as P
        with mock.patch.object(P, "read_key", lambda fd, **k: keys.pop(0)), \
             mock.patch.object(P, "select") as fake_sel:
            fake_sel.select = lambda *a, **k: (True, 0, 0)
            page._pick_effort()
        self.assertEqual(state.reasoning_effort, "xhigh")

        # Provider değişimi (application._apply_provider yolu) state'e DOKUNMAZ
        page.set_effort_note("")            # _apply içindeki çağrının aynısı
        self.assertEqual(state.reasoning_effort, "xhigh")


class TestStateReachesPayload(unittest.TestCase):
    """2) state.reasoning_effort → client → provider payload."""

    def test_openai_low_then_high(self):
        state = ApplicationState()
        state.reasoning_effort = "low"
        client = _CaptureClient(_cfg("https://api.openai.com/v1", "gpt-5.2"))
        client._client.chat.completions.create = (
            lambda **kw: client._openai_create_for_test(**kw))

        client.stream([{"role": "user", "content": "hi"}],
                      renderer=_FakeRenderer(),
                      reasoning_effort=state.reasoning_effort)
        self.assertEqual(client.calls[0]["extra_body"],
                         {"reasoning_effort": "low"})

        # Ctrl+P → high; ikinci çağrı high göndermeli
        state.reasoning_effort = "high"
        client.stream([{"role": "user", "content": "hi"}],
                      renderer=_FakeRenderer(),
                      reasoning_effort=state.reasoning_effort)
        self.assertEqual(client.calls[1]["extra_body"],
                         {"reasoning_effort": "high"})

    def test_openrouter_format_from_same_state(self):
        state = ApplicationState()
        state.reasoning_effort = "high"
        client = _CaptureClient(_cfg("https://openrouter.ai/api/v1",
                                     "deepseek/deepseek-r1"))
        client._client.chat.completions.create = (
            lambda **kw: client._openai_create_for_test(**kw))
        client.stream([{"role": "user", "content": "hi"}],
                      renderer=_FakeRenderer(),
                      reasoning_effort=state.reasoning_effort)
        self.assertEqual(client.calls[0]["extra_body"],
                         {"reasoning": {"effort": "high"}})
        self.assertEqual(state.reasoning_effort, "high")   # korunur

    def test_llamacpp_chat_template_kwargs_from_state(self):
        state = ApplicationState()
        state.reasoning_effort = "medium"
        client = _CaptureClient(_cfg("http://127.0.0.1:8080/v1", "Bonsai-2"))
        client._client.chat.completions.create = (
            lambda **kw: client._openai_create_for_test(**kw))
        client.stream([{"role": "user", "content": "hi"}],
                      renderer=_FakeRenderer(),
                      reasoning_effort=state.reasoning_effort)
        self.assertEqual(client.calls[0]["extra_body"],
                         {"chat_template_kwargs": {
                             "reasoning_effort": "medium",
                             "enable_thinking": True}})

    def test_claude_native_receives_state(self):
        state = ApplicationState()
        state.reasoning_effort = "high"
        client = _CaptureClient(_cfg("https://api.anthropic.com/v1",
                                     "claude-sonnet-4-5"))
        captured = {}

        def fake_stream_messages(base, key, model, messages, effort="", **kw):
            captured["effort"] = effort
            return iter([]), (lambda: None)

        with mock.patch.object(anthro, "stream_messages", fake_stream_messages):
            client.stream([{"role": "user", "content": "hi"}],
                          renderer=_FakeRenderer(),
                          reasoning_effort=state.reasoning_effort)
        self.assertEqual(captured["effort"], "high")   # native output_config yolu

        payload = anthro.build_payload("claude-sonnet-4-5",
                                       [{"role": "user", "content": "hi"}],
                                       effort=captured["effort"])
        self.assertEqual(payload["output_config"], {"effort": "high"})

    def test_none_effort_value_reaches_client(self):
        # Ctrl+P 'none' → llama.cpp'te enable_thinking=false
        state = ApplicationState()
        state.reasoning_effort = "none"
        client = _CaptureClient(_cfg("http://127.0.0.1:8080/v1", "Bonsai-2"))
        client._client.chat.completions.create = (
            lambda **kw: client._openai_create_for_test(**kw))
        client.stream([{"role": "user", "content": "hi"}],
                      renderer=_FakeRenderer(),
                      reasoning_effort=state.reasoning_effort)
        self.assertEqual(client.calls[0]["extra_body"],
                         {"chat_template_kwargs": {"enable_thinking": False}})


class TestAgentLoopPersistence(unittest.TestCase):
    """3) Web-search agent loop: ikinci/üçüncü request aynı effort."""

    def test_second_request_keeps_effort(self):
        state = ApplicationState()
        state.reasoning_effort = "high"
        client = _CaptureClient(_cfg("https://api.openai.com/v1", "gpt-5.2"))
        client._client.chat.completions.create = (
            lambda **kw: client._openai_create_for_test(**kw))

        # chat/service while-loop'u gibi art arda iki request
        for _ in range(2):
            client.stream([{"role": "user", "content": "hi"}],
                          renderer=_FakeRenderer(),
                          reasoning_effort=state.reasoning_effort)
        self.assertEqual(client.calls[0]["extra_body"],
                         {"reasoning_effort": "high"})
        self.assertEqual(client.calls[1]["extra_body"],
                         {"reasoning_effort": "high"})

    def test_no_hidden_default_when_state_missing(self):
        # state değeri None olsa bile gizli 'xhigh' GİTMEMELİ (omit)
        client = _CaptureClient(_cfg("https://api.openai.com/v1", "gpt-5.2"))
        client._client.chat.completions.create = (
            lambda **kw: client._openai_create_for_test(**kw))
        client.stream([{"role": "user", "content": "hi"}],
                      renderer=_FakeRenderer(), reasoning_effort=None)
        self.assertIsNone(client.calls[0]["extra_body"])


class TestFallbackPreservesGlobalChoice(unittest.TestCase):
    """4) 400 fallback: global Ctrl+P tercihi DEĞİŞMEZ."""

    def test_retry_keeps_state_and_caches_capability(self):
        state = ApplicationState()
        state.reasoning_effort = "high"
        client = _CaptureClient(
            _cfg("https://api.example-gw.io/v1", "gpt-5.2"),
            fail_first_with='Error code: 400 - Unknown name "reasoning_effort"')
        client.reasoning_api_override = "openai"   # effort gerçekten gönderilsin
        client._client.chat.completions.create = (
            lambda **kw: client._openai_create_for_test(**kw))

        client.stream([{"role": "user", "content": "hi"}],
                      renderer=_FakeRenderer(),
                      reasoning_effort=state.reasoning_effort)
        self.assertEqual(len(client.calls), 2)          # hatalı + sade retry
        self.assertIsNone(client.calls[1]["extra_body"])
        self.assertEqual(state.reasoning_effort, "high")  # TERCİH KORUNDU

        # sonraki tur: cache'li sade istek, ama state hâlâ 'high'
        client._fail_first_with = None
        client.stream([{"role": "user", "content": "hi"}],
                      renderer=_FakeRenderer(),
                      reasoning_effort=state.reasoning_effort)
        self.assertIsNone(client.calls[2]["extra_body"])
        self.assertEqual(state.reasoning_effort, "high")

        # başka (destekleyen) modele geçince 'high' TEKRAR kullanılır
        client.rebind("https://api.openai.com/v1", "sk-test", "gpt-5.2")
        client._client.chat.completions.create = (
            lambda **kw: client._openai_create_for_test(**kw))  # mock yeniden
        client.stream([{"role": "user", "content": "hi"}],
                      renderer=_FakeRenderer(),
                      reasoning_effort=state.reasoning_effort)
        self.assertEqual(client.calls[3]["extra_body"],
                         {"reasoning_effort": "high"})


def _body_of(base: str, model: str, effort):
    client = _CaptureClient(_cfg(base, model))
    client._client.chat.completions.create = (
        lambda **kw: client._openai_create_for_test(**kw))
    client.stream([{"role": "user", "content": "hi"}],
                  renderer=_FakeRenderer(), reasoning_effort=effort)
    return client.calls[0]["extra_body"]


class TestAutoIsNotNone(unittest.TestCase):
    """auto (None) explicit override değildir; none kapatma isteğidir."""

    def test_startup_is_auto(self):
        self.assertIsNone(ApplicationState().reasoning_effort)
        self.assertEqual(normalize_effort(None), "")
        self.assertEqual(normalize_effort("auto"), "")
        self.assertNotEqual(normalize_effort("auto"), "high")
        self.assertEqual(normalize_effort("none"), "none")

    def test_auto_openai_omits_effort(self):
        body = _body_of("https://api.openai.com/v1", "gpt-5.2", None)
        self.assertIsNone(body)
        self.assertNotEqual(body, {"reasoning_effort": "auto"})

    def test_auto_openrouter_omits_effort(self):
        body = _body_of("https://openrouter.ai/api/v1", "openai/gpt-5", None)
        self.assertTrue(body is None or "reasoning" not in (body or {}))

    def test_auto_llamacpp_sends_neither_effort_nor_disable(self):
        body = _body_of("http://127.0.0.1:8080/v1", "local", None)
        self.assertIsNone(body)

    def test_explicit_none_is_not_auto(self):
        auto = _body_of("http://127.0.0.1:8080/v1", "local", None)
        none = _body_of("http://127.0.0.1:8080/v1", "local", "none")
        self.assertIsNone(auto)
        self.assertEqual(none, {"chat_template_kwargs": {"enable_thinking": False}})

    def test_explicit_high_payloads(self):
        self.assertEqual(
            _body_of("https://api.openai.com/v1", "gpt-5.2", "high"),
            {"reasoning_effort": "high"})
        self.assertEqual(
            _body_of("https://openrouter.ai/api/v1", "openai/gpt-5", "high"),
            {"reasoning": {"effort": "high"}})
        self.assertEqual(
            _body_of("http://127.0.0.1:8080/v1", "local", "high")["chat_template_kwargs"]["reasoning_effort"],
            "high")
        claude = anthro.build_payload("claude-sonnet-4-5",
                                      [{"role": "user", "content": "hi"}],
                                      effort="high")
        self.assertEqual(claude["output_config"], {"effort": "high"})

    def test_auto_claude_omits_output_config(self):
        body = anthro.build_payload("claude-sonnet-4-5",
                                    [{"role": "user", "content": "hi"}],
                                    effort="")
        self.assertNotIn("output_config", body)
        self.assertNotIn("reasoning_effort", body)

    def test_reset_back_to_auto(self):
        client = _CaptureClient(_cfg("https://api.openai.com/v1", "gpt-5.2"))
        client._client.chat.completions.create = (
            lambda **kw: client._openai_create_for_test(**kw))
        client.stream([{"role": "user", "content": "hi"}],
                      renderer=_FakeRenderer(), reasoning_effort="high")
        client.stream([{"role": "user", "content": "hi"}],
                      renderer=_FakeRenderer(), reasoning_effort=None)
        self.assertEqual(client.calls[0]["extra_body"], {"reasoning_effort": "high"})
        self.assertIsNone(client.calls[1]["extra_body"])

    def test_provider_switch_keeps_auto(self):
        state = ApplicationState()
        page = _HeadlessPage()
        _wire(state, page)
        page.set_effort_note("")
        self.assertIsNone(state.reasoning_effort)
        page.set_effort("high")
        state.reasoning_effort = "high"
        page.set_effort(None)
        state.reasoning_effort = None
        page.set_effort_note("")
        self.assertIsNone(state.reasoning_effort)

    def test_ctrlp_can_return_to_auto(self):
        state = ApplicationState()
        state.reasoning_effort = "high"
        page = _HeadlessPage()
        _wire(state, page)
        # high'dan up: medium değil, liste auto...max; high'ın üstü medium
        # auto'ya dönmek için high indeksinden yukarı yeterince.
        # auto(0) none minimal low medium high(5) → 5 kez up
        keys = ["up", "up", "up", "up", "up", "enter"]
        import ui.page as P
        with mock.patch.object(P, "read_key", lambda fd, **k: keys.pop(0)), \
             mock.patch.object(P, "select") as fake_sel:
            fake_sel.select = lambda *a, **k: (True, 0, 0)
            page._pick_effort()
        self.assertIsNone(state.reasoning_effort)
        self.assertIsNone(page._effort)

    def test_web_search_loop_auto_stays_unset(self):
        state = ApplicationState()
        client = _CaptureClient(_cfg("https://api.openai.com/v1", "gpt-5.2"))
        client._client.chat.completions.create = (
            lambda **kw: client._openai_create_for_test(**kw))
        for _ in range(2):
            client.stream([{"role": "user", "content": "hi"}],
                          renderer=_FakeRenderer(),
                          reasoning_effort=state.reasoning_effort)
        self.assertIsNone(client.calls[0]["extra_body"])
        self.assertIsNone(client.calls[1]["extra_body"])
        self.assertIsNone(state.reasoning_effort)


if __name__ == "__main__":
    unittest.main()

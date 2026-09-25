"""Reasoning akışı: structured alan, inline fallback, history, effort default."""

import unittest

from chat.service import assistant_history_message
from config import Config
from llm.anthropic_transport import build_payload
from llm.client import LLMClient
from llm.normalize import (
    NormEvent,
    ResponseAssembler,
    anthropic_delta_events,
    normalize_delta,
    normalize_gemini_event,
    normalize_ollama,
)
from llm.reasoning import resolve_output_extra, resolve_reasoning_config
from llm.reasoning_text import (
    HarmonyDecoder,
    ParseProfile,
    decode_every_cut,
)
from llm.stream import StreamParser, StreamResult
from state import ApplicationState
from ui.page import Page


class _Renderer:
    def __init__(self):
        self.headers = []

    def show_thinking_started(self, reasoning_kind="raw"):
        self.headers.append(reasoning_kind)

    def __getattr__(self, name):
        return lambda *a, **k: None


def _cfg(base, model):
    return Config(
        server_base=base, api_base_url=base, api_key="sk-test", agent_model=model,
        whisper_bin="w", whisper_model="m", whisper_lang="tr",
        pipe_path="/tmp/p", chat_directory="chats", context_fallback=4096,
        context_safety_ratio=0.85, context_provider="", system_prompt="",
        provider_selection="t",
    )


def _pipeline(events, profile=None):
    asm = ResponseAssembler(profile or ParseProfile())
    parser = StreamParser(_Renderer())
    for batch in events:
        for ev in asm.consume(batch):
            if ev.kind == "reasoning":
                parser.feed_reasoning(ev.text, ev.reasoning_kind)
            else:
                parser.feed_content(ev.text)
    for ev in asm.flush():
        if ev.kind == "reasoning":
            parser.feed_reasoning(ev.text, ev.reasoning_kind)
        else:
            parser.feed_content(ev.text)
    parser.flush()
    return parser, asm


class TestInlineMarkers(unittest.TestCase):
    def test_think_thought_ministral_cohere_split_every_boundary(self):
        cases = [
            ("<think>reason</think>answer", ParseProfile(), "reason", "answer"),
            ("<thought>reason</thought>answer", ParseProfile(), "reason", "answer"),
            ("[THINK]reason[/THINK]answer",
             ParseProfile(allow_ministral=True), "reason", "answer"),
            ("<|START_THINKING|>reason<|END_THINKING|>answer",
             ParseProfile(allow_cohere=True), "reason", "answer"),
            ("<|START_THINKING|>reason<|END_THINKING|><|START_RESPONSE|>answer",
             ParseProfile(allow_cohere=True), "reason", "answer"),
        ]
        for text, profile, exp_r, exp_c in cases:
            got = decode_every_cut(text, profile)
            self.assertEqual(got, (exp_r, exp_c), text)

    def test_ministral_and_cohere_stay_closed_without_profile(self):
        for text in ("[THINK]reason[/THINK]answer",
                     "<|START_THINKING|>reason<|END_THINKING|>answer"):
            reasoning, content = decode_every_cut(text, ParseProfile())
            self.assertEqual(reasoning, "")
            self.assertEqual(content, text)

    def test_profile_for_known_templates(self):
        self.assertTrue(ParseProfile(allow_ministral=True).allow_ministral)
        from llm.reasoning_text import profile_for
        self.assertTrue(profile_for("", "ministral-8b").allow_ministral)
        self.assertTrue(profile_for("https://api.cohere.ai/v1", "command-r").allow_cohere)
        self.assertFalse(profile_for("", "gpt-oss-120b").allow_harmony)

    def test_no_global_xml(self):
        for text in ("<analysis>x</analysis>answer",
                     "<reasoning>x</reasoning>answer",
                     "<thinking>x</thinking>answer"):
            reasoning, content = decode_every_cut(text)
            self.assertEqual(reasoning, "")
            self.assertEqual(content, text)

    def test_literal_tag_after_visible_text_is_kept(self):
        text = "HTML örneği: <think>abc</think>"
        reasoning, content = decode_every_cut(text)
        self.assertEqual(reasoning, "")
        self.assertEqual(content, text)

    def test_forced_open_only_when_enabled(self):
        text = "reason</think>final"
        reasoning, content = decode_every_cut(text, ParseProfile())
        self.assertEqual(reasoning, "")
        self.assertEqual(content, text)
        reasoning, content = decode_every_cut(
            text, ParseProfile(forced_open_think=True))
        self.assertEqual(reasoning, "reason")
        self.assertEqual(content, "final")

    def test_tags_do_not_leak_into_answer(self):
        _, content = decode_every_cut("<think>r</think><thought>s</thought>ok")
        # ikinci thought, görünür metin yokken hâlâ prefix sayılır
        for needle in ("<think>", "</think>", "<thought>", "</thought>",
                       "[THINK]", "[/THINK]"):
            self.assertNotIn(needle, content)


class TestHarmony(unittest.TestCase):
    RAW = (
        "<|start|>assistant<|channel|>analysis<|message|>"
        "REASON<|end|><|start|>assistant<|channel|>final<|message|>"
        "ANSWER<|return|>"
    )

    def test_raw_channels(self):
        profile = ParseProfile(allow_harmony=True)
        reasoning, content = decode_every_cut(self.RAW, profile)
        self.assertEqual(reasoning, "REASON")
        self.assertEqual(content, "ANSWER")
        self.assertNotIn("analysis", content)
        self.assertNotIn("<|", content)

    def test_no_separator_is_left_as_content(self):
        text = "reasoninganswer"
        reasoning, content = decode_every_cut(text, ParseProfile(allow_harmony=True))
        self.assertEqual(reasoning, "")
        self.assertEqual(content, text)

    def test_split_control_token(self):
        dec = HarmonyDecoder()
        events = dec.feed(self.RAW[:12])
        events += dec.feed(self.RAW[12:])
        events += dec.flush()
        from llm.reasoning_text import collapse
        self.assertEqual(collapse(events), ("REASON", "ANSWER"))


class TestStructured(unittest.TestCase):
    def test_reasoning_content_and_content(self):
        parser, _ = _pipeline([[
            NormEvent("reasoning", "reason", "raw"),
            NormEvent("content", "answer"),
        ]])
        self.assertEqual(parser.thinking_text, "reason")
        self.assertEqual(parser.response_text, "answer")

    def test_delta_reasoning_field(self):
        events = normalize_delta({"reasoning": "reason", "content": "answer"})
        parser, _ = _pipeline([events])
        self.assertEqual(parser.thinking_text, "reason")
        self.assertEqual(parser.response_text, "answer")

    def test_alias_not_duplicated(self):
        events = normalize_delta({
            "reasoning": "reason",
            "reasoning_content": "reason",
            "content": "answer",
        })
        parser, _ = _pipeline([events])
        self.assertEqual(parser.thinking_text, "reason")

    def test_reasoning_details_summary(self):
        events = normalize_delta({
            "reasoning_details": [{"type": "reasoning.summary", "summary": "özet"}],
            "content": "answer",
        })
        parser, asm = _pipeline([events])
        self.assertEqual(parser.thinking_text, "özet")
        self.assertEqual(parser.reasoning_kind, "summary")
        self.assertEqual(parser.response_text, "answer")
        self.assertEqual(asm.continuation["reasoning_details"][0]["summary"], "özet")

    def test_structured_suppresses_inline_copy(self):
        events = normalize_delta({
            "reasoning_content": "reason",
            "content": "<think>reason</think>answer",
        })
        parser, _ = _pipeline([events])
        self.assertEqual(parser.thinking_text, "reason")
        self.assertEqual(parser.response_text, "answer")
        self.assertNotIn("<think>", parser.response_text)

    def test_gemini_thought_fallback_and_summary(self):
        parser, _ = _pipeline([normalize_delta({
            "content": "<thought>reason</thought>answer",
        })])
        self.assertEqual(parser.thinking_text, "reason")
        self.assertEqual(parser.response_text, "answer")
        events = normalize_gemini_event({
            "delta": {"type": "thought_summary",
                      "content": {"type": "text", "text": "özet"}},
        })
        events += normalize_gemini_event({
            "delta": {"type": "thought_signature", "signature": "SIG"},
        })
        events += normalize_gemini_event({"delta": {"type": "text", "text": "cevap"}})
        parser, asm = _pipeline([events])
        self.assertEqual(parser.thinking_text, "özet")
        self.assertEqual(parser.reasoning_kind, "summary")
        self.assertEqual(parser.response_text, "cevap")
        self.assertNotIn("SIG", parser.response_text)
        self.assertEqual(asm.continuation["signature"], "SIG")

    def test_ollama(self):
        events = normalize_ollama({
            "message": {"thinking": "reason", "content": "answer"},
        })
        parser, _ = _pipeline([events])
        self.assertEqual(parser.thinking_text, "reason")
        self.assertEqual(parser.response_text, "answer")

    def test_mistral_chunks(self):
        events = normalize_delta({
            "content": [
                {"type": "thinking", "thinking": [{"type": "text", "text": "reason"}]},
                {"type": "text", "text": "answer"},
            ],
        })
        parser, asm = _pipeline([events])
        self.assertEqual(parser.thinking_text, "reason")
        self.assertEqual(parser.response_text, "answer")
        self.assertTrue(asm.saw_mistral_chunks)

    def test_claude_mapping_hides_signature(self):
        thinking = anthropic_delta_events({
            "type": "content_block_delta",
            "delta": {"type": "thinking_delta", "thinking": "reason"},
        })
        text = anthropic_delta_events({
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "answer"},
        })
        sig = anthropic_delta_events({
            "type": "content_block_delta",
            "delta": {"type": "signature_delta", "signature": "SIG"},
        })
        self.assertEqual(thinking[0]["type"], "thinking")
        self.assertEqual(text[0]["data"], "answer")
        self.assertEqual(sig[0]["type"], "signature")
        rendered = []
        parser = StreamParser(_Renderer())
        parser.renderer.headers = rendered
        parser.feed_reasoning(thinking[0]["data"], thinking[0]["reasoning_kind"])
        parser.feed_content(text[0]["data"])
        parser.flush()
        self.assertEqual(parser.thinking_text, "reason")
        self.assertEqual(parser.response_text, "answer")
        self.assertNotIn("SIG", parser.response_text + parser.thinking_text)
        self.assertEqual(rendered, ["summary"])

    def test_cumulative_snapshot_suffix(self):
        asm = ResponseAssembler()
        out = []
        out += asm.consume([NormEvent("reasoning", "The user is asking")])
        out += asm.consume([NormEvent(
            "reasoning", "The user is asking for the author")])
        text = "".join(ev.text for ev in out)
        self.assertEqual(text, "The user is asking for the author")

    def test_non_snapshot_repetition_is_kept(self):
        # İkinci parça birikmiş metinle başlamıyorsa model çıktısıdır.
        asm = ResponseAssembler()
        out = []
        out += asm.consume([NormEvent("content", "<thought>The user is asking")])
        out += asm.consume([NormEvent(
            "content", "The user is asking for the author</thought>Final")])
        parser = StreamParser(_Renderer())
        for ev in out:
            if ev.kind == "reasoning":
                parser.feed_reasoning(ev.text, ev.reasoning_kind)
            else:
                parser.feed_content(ev.text)
        for ev in asm.flush():
            if ev.kind == "reasoning":
                parser.feed_reasoning(ev.text, ev.reasoning_kind)
            else:
                parser.feed_content(ev.text)
        parser.flush()
        self.assertIn("The user is askingThe user is asking", parser.thinking_text)
        self.assertEqual(parser.response_text, "Final")
        self.assertNotIn("<thought>", parser.response_text)


class TestObservedGeminiHistory(unittest.TestCase):
    SELAM = (
        "<thought>*   Input: \"Selam, sen kimsin?\"\n</thought>"
        "Selam! Ben bir modelim."
    )
    YABAN = (
        "<thought>The user is askingThe user is asking for the author "
        "of the novel \"Yaban\".</thought>*Yaban* romanının yazarı."
    )

    def test_thought_leaves_the_answer(self):
        for text, needle in ((self.SELAM, "Selam!"), (self.YABAN, "*Yaban*")):
            parser, _ = _pipeline([normalize_delta({"content": text})])
            self.assertNotIn("<thought>", parser.response_text)
            self.assertNotIn("</thought>", parser.response_text)
            self.assertIn(needle, parser.response_text)
            self.assertNotIn(needle, parser.thinking_text)

    def test_yaban_repetition_stays_inside_reasoning(self):
        parser, _ = _pipeline([normalize_delta({"content": self.YABAN})])
        self.assertIn(
            "The user is askingThe user is asking", parser.thinking_text)


class TestWebSearchIsolation(unittest.TestCase):
    def test_reasoning_does_not_trigger_search(self):
        parser, _ = _pipeline([[
            NormEvent("reasoning", "Belki <web_search>example</web_search> aramalıyım."),
            NormEvent("content", "cevap"),
        ]])
        self.assertEqual(parser.search_queries, [])
        self.assertIn("cevap", parser.response_text)

    def test_inline_reasoning_hides_search_tag(self):
        parser, _ = _pipeline([normalize_delta({
            "content": "<think><web_search>example</web_search></think>cevap",
        })])
        self.assertEqual(parser.search_queries, [])
        self.assertEqual(parser.response_text, "cevap")

    def test_final_content_still_triggers_search(self):
        parser, _ = _pipeline([normalize_delta({
            "content": "önce <web_search>example</web_search>",
        })])
        self.assertEqual(parser.search_queries, ["example"])
        self.assertNotIn("<web_search>", parser.response_text)

    def test_split_search_tag(self):
        parser = StreamParser(_Renderer())
        parser.feed_content("<web")
        parser.feed_content("_search>example</web_search>")
        parser.flush()
        self.assertEqual(parser.search_queries, ["example"])


class TestHistory(unittest.TestCase):
    def test_visible_history_is_final_only(self):
        result = StreamResult(
            assistant_text="final cevap",
            thinking_text="gizli",
            input_tokens=1, output_tokens=1, elapsed=0.1,
            usage_estimated=False,
            search_queries=[],
            continuation={"signature": "SIG", "thinking": "gizli"},
        )
        msg = assistant_history_message(result)
        self.assertEqual(msg["content"], "final cevap")
        self.assertNotIn("<think>", msg["content"])
        self.assertEqual(msg["provider_state"]["signature"], "SIG")

    def test_search_tag_from_final_is_kept_on_history(self):
        result = StreamResult(
            assistant_text="bitti", thinking_text="",
            input_tokens=0, output_tokens=0, elapsed=0, usage_estimated=True,
            search_queries=["example"],
        )
        msg = assistant_history_message(result)
        self.assertIn("<web_search>example</web_search>", msg["content"])
        self.assertNotIn("provider_state", msg)

    def test_anthropic_replay_keeps_signature(self):
        body = build_payload("claude-sonnet-4-5", [
            {"role": "user", "content": "soru"},
            {"role": "assistant", "content": "cevap",
             "provider_state": {"thinking": "gizli", "signature": "SIG"}},
        ])
        assistant = body["messages"][1]["content"]
        self.assertEqual(assistant[0]["type"], "thinking")
        self.assertEqual(assistant[0]["signature"], "SIG")
        self.assertEqual(assistant[1], {"type": "text", "text": "cevap"})
        self.assertNotIn("SIG", assistant[1]["text"])

    def test_openai_strips_state_openrouter_replays_details(self):
        client = LLMClient(_cfg("https://api.openai.com/v1", "gpt-5.2"))
        messages = [{"role": "assistant", "content": "cevap",
                     "provider_state": {"signature": "SIG",
                                        "reasoning_details": [{"type": "reasoning.text"}]}}]
        sent = client._api_messages(messages, "openai")
        self.assertNotIn("provider_state", sent[0])
        self.assertNotIn("signature", sent[0])
        client._client.base_url = "https://openrouter.ai/api/v1"
        sent = client._api_messages(messages, "openrouter")
        self.assertEqual(sent[0]["reasoning_details"][0]["type"], "reasoning.text")
        self.assertNotIn("provider_state", sent[0])

    def test_deepseek_replays_reasoning_content(self):
        client = LLMClient(_cfg("https://api.deepseek.com/v1", "deepseek-reasoner"))
        messages = [{"role": "assistant", "content": "cevap",
                     "provider_state": {"reasoning_content": "trace"}}]
        sent = client._api_messages(messages, "openai")
        self.assertEqual(sent[0]["reasoning_content"], "trace")
        self.assertEqual(sent[0]["content"], "cevap")


class TestDefaultEffort(unittest.TestCase):
    def test_state_starts_unset(self):
        self.assertIsNone(ApplicationState().reasoning_effort)

    def test_unset_sends_no_effort_field(self):
        rc = resolve_reasoning_config(
            "https://api.openai.com/v1", "gpt-5.2", None)
        self.assertEqual(rc.effort, "")
        self.assertTrue(rc.omitted)
        client = LLMClient(_cfg("https://api.openai.com/v1", "gpt-5.2"))
        calls = []

        class D:
            content = "ok"
            reasoning_content = None

        class C:
            delta = D()

        class Chunk:
            choices = [C()]
            usage = None

        def create(**kw):
            calls.append(kw)
            return iter([Chunk()])

        client._client.chat.completions.create = create
        client.stream([{"role": "user", "content": "hi"}],
                      renderer=_Renderer(), reasoning_effort=None)
        self.assertIsNone(calls[0]["extra_body"])

    def test_ctrlp_high_is_sent_after_unset(self):
        client = LLMClient(_cfg("https://api.openai.com/v1", "gpt-5.2"))
        calls = []

        class D:
            content = "ok"
            reasoning_content = None

        class C:
            delta = D()

        class Chunk:
            choices = [C()]
            usage = None

        client._client.chat.completions.create = (
            lambda **kw: calls.append(kw) or iter([Chunk()]))
        client.stream([{"role": "user", "content": "hi"}],
                      renderer=_Renderer(), reasoning_effort="high")
        self.assertEqual(calls[0]["extra_body"], {"reasoning_effort": "high"})

    def test_page_shows_provider_default(self):
        page = Page("T")
        page._cols, page._rows = 100, 24
        page._build_input_box()
        blob = "\n".join(page._keep_bottom)
        self.assertIn("Efor: auto", blob)
        page.set_effort("high")
        page._build_input_box()
        blob = "\n".join(page._keep_bottom)
        self.assertIn("Efor: high", blob)
        self.assertNotIn("Efor: auto", blob)
        page.set_effort("xhigh")
        page.set_effort_note("Gemini/model limiti: xhigh→high")
        page._build_input_box()
        blob = "\n".join(page._keep_bottom)
        self.assertIn("Efor: xhigh → high", blob)
        page.set_effort_note("unsupported (400, omitted)")
        page._build_input_box()
        blob = "\n".join(page._keep_bottom)
        self.assertIn("Efor: xhigh → unsupported", blob)


class TestOutputFormat(unittest.TestCase):
    def test_groq_qwen_parsed_without_effort(self):
        extra = resolve_output_extra(
            "https://api.groq.com/openai/v1", "qwen/qwen3-32b")
        self.assertEqual(extra, {"reasoning_format": "parsed"})
        self.assertEqual(resolve_output_extra(
            "https://api.groq.com/openai/v1", "openai/gpt-oss-120b"), {})

    def test_groq_request_merges_format_and_effort(self):
        client = LLMClient(_cfg("https://api.groq.com/openai/v1", "qwen/qwen3-32b"))
        calls = []

        class D:
            content = "ok"
            reasoning_content = None

        class C:
            delta = D()

        class Chunk:
            choices = [C()]
            usage = None

        client._client.chat.completions.create = (
            lambda **kw: calls.append(kw) or iter([Chunk()]))
        client.stream([{"role": "user", "content": "hi"}],
                      renderer=_Renderer(), reasoning_effort="high")
        body = calls[0]["extra_body"]
        self.assertEqual(body["reasoning_effort"], "high")
        self.assertEqual(body["reasoning_format"], "parsed")

    def test_cerebras_parsed_for_gpt_oss(self):
        self.assertEqual(resolve_output_extra(
            "https://api.cerebras.ai/v1", "gpt-oss-120b"),
            {"reasoning_format": "parsed"})


class TestClientThoughtSplit(unittest.TestCase):
    def test_live_delta_thought_does_not_reach_answer(self):
        client = LLMClient(_cfg(
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            "gemini-2.5-flash"))

        class D:
            content = "<thought>reason</thought>Selam"
            reasoning_content = None

        class C:
            delta = D()

        class Chunk:
            choices = [C()]
            usage = None

        client._client.chat.completions.create = lambda **kw: iter([Chunk()])
        result = client.stream(
            [{"role": "user", "content": "hi"}],
            renderer=_Renderer(), reasoning_effort=None)
        self.assertEqual(result.thinking_text, "reason")
        self.assertEqual(result.assistant_text, "Selam")
        self.assertNotIn("<thought>", result.assistant_text)


if __name__ == "__main__":
    unittest.main()

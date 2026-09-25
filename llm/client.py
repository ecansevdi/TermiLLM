import time
from urllib.parse import urlparse

from openai import OpenAI

from config import Config
from llm.abort import abort_provider_task, abort_stream
from llm.cancel import CancelWatch, GenerationCancelled
from llm.normalize import NormEvent, assembler_for, normalize_delta
from llm.reasoning import (
    API_ANTHROPIC,
    API_LLAMACPP,
    API_NONE,
    API_OPENAI,
    API_OPENROUTER,
    is_reasoning_related_error,
    normalize_effort,
    resolve_output_extra,
    resolve_reasoning_config,
)
from llm.stream import StreamParser, StreamResult
from ui.stream_renderer import StreamRenderer


def _debug_log(msg: str, enabled: bool):
    if enabled:
        try:
            with open("debug.log", "a", encoding="utf-8") as dbg:
                dbg.write(f"[reasoning] {msg}\n")
        except Exception:
            pass


class LLMClient:
    """OpenAI-compatible API ile model konuşması. Persistence'tan habersizdir.

    Reasoning/effort: request alanları `llm.reasoning` adapter'ından gelir
    (provider + model + API türüne göre). 400'ten kaynaklı reasoning
    hatalarında istek effortsüz bir kez yeniden denenir ve bu
    provider+model kombinasyonu process boyunca 'unsupported' cache'lenir.
    """

    def __init__(self, config: Config):
        self.model = config.agent_model
        if not config.api_base_url:
            raise SystemExit(
                "Konfigürasyonda 'base_url' bulunamadı. Ctrl+O → "
                "'Enter API' ile sağlayıcı ekleyin (ör. "
                "base_url=http://127.0.0.1:8080/v1)."
            )
        # Yerel sunucular (llama.cpp/Ollama/LM Studio) key istemez; OpenAI
        # istemcisi ise boş olmayan bir değer ister. Key yoksa placeholder.
        self._client = OpenAI(
            base_url=config.api_base_url,
            api_key=config.api_key or "sk-local",
        )
        # Provider başına opsiyonel override (config.toml: reasoning_api)
        self.reasoning_api_override = (
            getattr(config, "reasoning_api", None) or "auto"
        )
        # (base_url, model) → unsupported. Process boyunca yaşar; rebind
        # sonrası da anlamlı (anahtar endpoint+model içerir).
        self._unsupported: set = set()
        self._output_off: set = set()
        self._output_extra: dict = {}
        # UI'nin tur sonunda göstereceği kısa açıklama ('' = not yok)
        self.last_effort_note = ""

    def rebind(self, base_url: str, api_key: str, model: str) -> None:
        """Provider değişiminde istemciyi yeniden kurar (yeniden başlatma
        gerekmez; sonraki istekten itibaren geçerli)."""
        self.model = model
        self._client = OpenAI(base_url=base_url, api_key=api_key or "sk-local")

    # ------------------------------------------------------------------ #
    # Request inşası (adapter çıktısına göre; tek format kuralı)
    # ------------------------------------------------------------------ #

    def _extra_body_for(self, rc) -> dict | None:
        """ReasoningConfig → OpenAI SDK extra_body. None = hiçbir şey.

        reasoning_format (çıktı) effort alanından ayrı eklenir. llama.cpp
        dalına karıştırılmaz. Aynı istekte iki effort formatı olmaz.
        """
        body = None
        if rc.api_type == API_LLAMACPP:
            kw = {}
            if rc.effort:
                kw["reasoning_effort"] = rc.effort
            if rc.disable_thinking:
                kw["enable_thinking"] = False
            elif rc.effort:
                kw["enable_thinking"] = True
            return {"chat_template_kwargs": kw} if kw else None
        if rc.api_type == API_OPENAI and rc.effort:
            body = {"reasoning_effort": rc.effort}
        elif rc.api_type == API_OPENROUTER and rc.effort:
            body = {"reasoning": {"effort": rc.effort}}
        extra = dict(self._output_extra or {})
        if body and extra:
            merged = dict(extra)
            merged.update(body)
            return merged
        return body or extra or None

    def _api_messages(self, messages: list, api_type: str) -> list:
        """provider_state diskte kalır; isteğe yalnız provider'ın istediği alan girer."""
        host = (urlparse(str(self._client.base_url)).hostname or "").lower()
        prepared = []
        for message in messages:
            if not isinstance(message, dict) or "provider_state" not in message:
                prepared.append(message)
                continue
            state = message.get("provider_state") or {}
            if api_type == API_ANTHROPIC:
                prepared.append(message)
                continue
            visible = {k: v for k, v in message.items() if k != "provider_state"}
            if "deepseek.com" in host and state.get("reasoning_content"):
                visible["reasoning_content"] = state["reasoning_content"]
            elif "mistral.ai" in host and state.get("content_parts"):
                visible["content"] = state["content_parts"]
            elif api_type == API_OPENROUTER and state.get("reasoning_details"):
                visible["reasoning_details"] = state["reasoning_details"]
            prepared.append(visible)
        return prepared

    def _feed_normalized(self, parser: StreamParser, assembler, events) -> bool:
        for ev in events:
            if ev.kind == "reasoning":
                parser.feed_reasoning(
                    ev.text, ev.reasoning_kind or assembler.reasoning_kind)
            elif ev.kind == "content":
                parser.feed_content(ev.text)
                if parser.completed_search:
                    return True
        return False

    def _continuation(self, assembler, parser: StreamParser, api_type: str):
        cont = dict(assembler.continuation)
        host = (urlparse(str(self._client.base_url)).hostname or "").lower()
        thinking = parser.thinking_text or ""
        if thinking and api_type == API_ANTHROPIC:
            cont["thinking"] = thinking
        if thinking and "deepseek.com" in host:
            cont["reasoning_content"] = thinking
        if assembler.saw_mistral_chunks and thinking:
            cont["content_parts"] = [
                {"type": "thinking",
                 "thinking": [{"type": "text", "text": thinking}]},
                {"type": "text", "text": parser.response_text or ""},
            ]
        return cont or None

    def _resolve_now(self, requested_effort: str):
        base_url = str(self._client.base_url)
        rc = resolve_reasoning_config(
            base_url, self.model, requested_effort,
            override=self.reasoning_api_override,
        )
        key = (rc.api_type, base_url.rstrip("/"), self.model)
        if key in self._unsupported and not rc.omitted:
            rc.effort = ""
            rc.disable_thinking = False
            rc.note = f"{rc.note} → unsupported (cached)".strip(" →")
        return rc, key

    # ------------------------------------------------------------------ #
    # Ana akış
    # ------------------------------------------------------------------ #

    def stream(self, messages: list, renderer: StreamRenderer,
               debug_enabled: bool = False,
               cancel: CancelWatch = None,
               reasoning_effort: str = None) -> StreamResult:
        # Ctrl+P seçimi (requested_effort) her çağrıda chat/service'ten gelir.
        # None/boş ise explicit effort alanı yoktur; provider kendi default'unu kullanır.
        rc, cache_key = self._resolve_now(reasoning_effort)
        if not rc.requested:
            self.last_effort_note = ""
        else:
            self.last_effort_note = rc.note if not rc.omitted else (
                rc.note or "effort omitted")
        if cache_key in self._output_off:
            self._output_extra = {}
        else:
            self._output_extra = resolve_output_extra(
                str(self._client.base_url), self.model)
        api_messages = self._api_messages(messages, rc.api_type)
        self.set_messages(api_messages)

        use_anthropic = rc.api_type == API_ANTHROPIC

        def _openai_create():
            return self._client.chat.completions.create(
                model=self.model,
                messages=api_messages,
                stream=True,
                stream_options={"include_usage": True},
                extra_body=self._extra_body_for(rc),
            )

        def _drop_reasoning_params(note_prefix: str):
            self._unsupported.add(cache_key)
            self._output_off.add(cache_key)
            self._output_extra = {}
            self.last_effort_note = (
                f"{note_prefix} → unsupported (400, omitted)").strip(" →")
            rc.effort = ""
            rc.disable_thinking = False

        retried = False
        try:
            if use_anthropic:
                response, close_fn = self._open_anthropic(rc, debug_enabled)
            else:
                response = _openai_create()
                close_fn = None
        except Exception as e:
            sent = (not rc.omitted) or bool(self._output_extra)
            if not sent or not is_reasoning_related_error(str(e)):
                raise
            # Reasoning kaynaklı 400: effortsüz TEK yeniden deneme + cache
            _debug_log(
                f"400 from {cache_key[0]} ({self.model}); "
                f"retrying without effort params; cached unsupported",
                debug_enabled,
            )
            _drop_reasoning_params(rc.note)
            retried = True
            if use_anthropic:
                response, close_fn = self._open_anthropic(rc, debug_enabled)
            else:
                response = _openai_create()

        def _cut_connection():
            try:
                abort_stream(response)
            except Exception:
                pass
            try:
                abort_provider_task(
                    str(self._client.base_url), self._client.api_key)
            except Exception:
                pass
            if close_fn:
                close_fn()

        if cancel:
            cancel.bind_closer(_cut_connection)
            cancel.check()

        parser = StreamParser(renderer)
        assembler = assembler_for(str(self._client.base_url), self.model)
        input_tokens = 0
        output_tokens = 0
        t_first_output = None

        def _touch():
            nonlocal t_first_output
            if t_first_output is None and (
                    parser.response_text or parser.thinking_text):
                t_first_output = time.monotonic()

        try:
            if use_anthropic:
                for evt in response:
                    if cancel:
                        cancel.check()
                    etype = evt.get("type")
                    if etype == "thinking":
                        text = evt.get("data") or ""
                        kind = evt.get("reasoning_kind") or "summary"
                        if self._feed_normalized(
                                parser, assembler,
                                assembler.consume([NormEvent("reasoning", text, kind)])):
                            close_fn()
                            break
                        _touch()
                    elif etype == "text":
                        if self._feed_normalized(
                                parser, assembler,
                                assembler.consume([NormEvent("content", evt.get("data") or "")])):
                            close_fn()
                            break
                        _touch()
                    elif etype == "signature":
                        sig = evt.get("data") or ""
                        if sig:
                            prev = assembler.continuation.get("signature") or ""
                            assembler.continuation["signature"] = prev + sig
                    elif etype == "usage":
                        input_tokens = evt.get("input") or 0
                        output_tokens = evt.get("output") or 0
            else:
                for chunk in response:
                    if cancel:
                        cancel.check()
                    if hasattr(chunk, "usage") and chunk.usage:
                        input_tokens = chunk.usage.prompt_tokens or 0
                        output_tokens = chunk.usage.completion_tokens or 0
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if not delta:
                        continue

                    if debug_enabled:
                        with open("debug.log", "a", encoding="utf-8") as dbg:
                            dbg.write(repr(chunk) + "\n")

                    if self._feed_normalized(
                            parser, assembler,
                            assembler.consume(normalize_delta(delta))):
                        abort_stream(response)
                        break
                    _touch()
        except GenerationCancelled:
            _cut_connection()
            self._feed_normalized(parser, assembler, assembler.flush())
            parser.flush()
            raise
        except Exception as e:
            if cancel and cancel.event.is_set():
                _cut_connection()
                self._feed_normalized(parser, assembler, assembler.flush())
                parser.flush()
                raise GenerationCancelled
            # Akış ortasında reasoning kaynaklı 400 (bazı gateway'ler
            # create'te değil ilk chunk'ta döndürüyor): aynı tek-retry yolu.
            sent = (not rc.omitted) or bool(self._output_extra)
            if (not retried and sent and is_reasoning_related_error(str(e))):
                _debug_log(
                    f"mid-stream 400 from {cache_key[0]} ({self.model}); "
                    f"retrying without effort; cached unsupported",
                    debug_enabled,
                )
                _drop_reasoning_params(rc.note)
                _cut_connection()
                self._feed_normalized(parser, assembler, assembler.flush())
                parser.flush()
                return self.stream(messages, renderer, debug_enabled, cancel,
                                   reasoning_effort=reasoning_effort)
            raise

        self._feed_normalized(parser, assembler, assembler.flush())
        parser.flush()

        t_stream_end = time.monotonic()
        elapsed = (t_stream_end - t_first_output) if t_first_output else 0.0
        estimated = input_tokens == 0 and output_tokens == 0

        return StreamResult(
            assistant_text=parser.response_text,
            thinking_text=parser.thinking_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            elapsed=elapsed,
            usage_estimated=estimated,
            search_queries=parser.search_queries,
            continuation=self._continuation(assembler, parser, rc.api_type),
        )

    # ------------------------------------------------------------------ #
    # Native Anthropic transport (output_config.effort — gerçek effort yolu)
    # ------------------------------------------------------------------ #

    def _open_anthropic(self, rc, debug_enabled: bool):
        from llm.anthropic_transport import stream_messages
        api_key = self._client.api_key
        base = str(self._client.base_url)
        return stream_messages(
            base, api_key, self.model, self._stream_messages or [],
            effort=rc.effort,
        )

    _stream_messages = None

    def set_messages(self, messages: list):
        """Anthropic transport'un create aşamasında messages'a erişmesi için."""
        self._stream_messages = messages

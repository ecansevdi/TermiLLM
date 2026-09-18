import time

from openai import OpenAI

from config import Config
from llm.abort import abort_provider_task, abort_stream
from llm.cancel import CancelWatch, GenerationCancelled
from llm.stream import StreamParser, StreamResult
from ui.stream_renderer import StreamRenderer


class LLMClient:
    """OpenAI-compatible API ile model konuşması. Persistence'tan habersizdir."""

    def __init__(self, config: Config):
        self.model = config.agent_model
        self._client = OpenAI(
            base_url=config.api_base_url,
            api_key=config.api_key,
        )

    def stream(self, messages: list, renderer: StreamRenderer,
               debug_enabled: bool = False,
               cancel: CancelWatch = None) -> StreamResult:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            extra_body={
                "chat_template_kwargs": {
                    "enable_thinking": True,
                    "reasoning_effort": "xhigh",
                }
            },
        )
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

        if cancel:
            cancel.bind_closer(_cut_connection)
            cancel.check()

        parser = StreamParser(renderer)
        input_tokens = 0
        output_tokens = 0
        t_first_output = None

        try:
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

                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    if t_first_output is None:
                        t_first_output = time.monotonic()
                    parser.feed_thinking(reasoning)

                if delta.content:
                    prev_len = len(parser.response_text) + len(parser.thinking_text)
                    parser.feed_content(delta.content)
                    if t_first_output is None and (
                        len(parser.response_text) + len(parser.thinking_text) > prev_len
                    ):
                        t_first_output = time.monotonic()
                    if parser.completed_search:
                        abort_stream(response)
                        break
        except GenerationCancelled:
            _cut_connection()
            parser.flush()
            raise
        except Exception:
            if cancel and cancel.event.is_set():
                _cut_connection()
                parser.flush()
                raise GenerationCancelled
            raise

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
        )

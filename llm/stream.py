from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.stream_renderer import StreamRenderer


@dataclass
class StreamResult:
    assistant_text: str
    thinking_text: str
    input_tokens: int
    output_tokens: int
    elapsed: float
    usage_estimated: bool
    search_queries: list = field(default_factory=list)
    continuation: dict | None = None


def clean_response(text: str) -> str:
    artifacts = [
        "user><answer>", "<answer>", "</answer>",
        "user>", "<|assistant|>", "<|im_start|>", "<|im_end|>",
    ]
    for artifact in artifacts:
        text = text.replace(artifact, "")
    return text.strip()


class StreamParser:
    """İçerik kanalındaki <web_search> etiketini yakalar.

    Reasoning metni feed_reasoning ile gelir ve tool parser'a girmez.
    Inline <think>/<thought> ayrımı llm.reasoning_text katmanındadır;
    burada ikinci kez etikete bakılmaz.
    """

    TAG_SEARCH_OPEN = "<web_search>"
    TAG_SEARCH_CLOSE = "</web_search>"

    def __init__(self, renderer: "StreamRenderer"):
        self.renderer = renderer
        self.thinking_started = False
        self.think_footer_done = False
        self.response_started = False
        self.in_search = False
        self.completed_search = False
        self.search_queries = []
        self._search_text = ""
        self.reasoning_kind = "raw"

        self.buffer = ""
        self.thinking_text = ""
        self.response_text = ""

    def feed_reasoning(self, text: str, reasoning_kind: str = "raw"):
        """Reasoning kanalı. <web_search> burada aranmaz."""
        if not text:
            return
        if not self.thinking_started:
            self.reasoning_kind = reasoning_kind or "raw"
            self.renderer.show_thinking_started(self.reasoning_kind)
            self.thinking_started = True
        self._emit_thinking(text)

    def feed_thinking(self, text: str):
        self.feed_reasoning(text, "raw")

    def feed_content(self, text: str):
        if not text:
            return
        self.buffer += text
        self._process()

    def flush(self):
        if self.completed_search:
            self.buffer = ""
        if self.in_search:
            self._search_text += self.buffer
            self.buffer = ""
            self.in_search = False
            self._finish_search()

        if self.buffer:
            self._emit_response(self.buffer)
            self.buffer = ""

        self.renderer.flush_output()

        if self.thinking_started and not self.think_footer_done:
            self.renderer.show_thinking_footer()
            self.think_footer_done = True

        self.renderer.show_stream_end()

    def _process(self):
        while True:
            if self.completed_search:
                self.buffer = ""
                return
            if self.in_search:
                idx = self.buffer.find(self.TAG_SEARCH_CLOSE)
                if idx == -1:
                    safe = self._safe_len(self.TAG_SEARCH_CLOSE)
                    if safe > 0:
                        self._search_text += self.buffer[:safe]
                        self.buffer = self.buffer[safe:]
                    break
                else:
                    self._search_text += self.buffer[:idx]
                    self.buffer = self.buffer[idx + len(self.TAG_SEARCH_CLOSE):]
                    self.in_search = False
                    self._finish_search()
            else:
                search_idx = self.buffer.find(self.TAG_SEARCH_OPEN)
                if search_idx == -1:
                    safe = self._safe_len(self.TAG_SEARCH_OPEN)
                    if safe > 0:
                        self._emit_response(self.buffer[:safe])
                        self.buffer = self.buffer[safe:]
                    break
                if search_idx > 0:
                    self._emit_response(self.buffer[:search_idx])
                self.buffer = self.buffer[search_idx + len(self.TAG_SEARCH_OPEN):]
                self.in_search = True
                self._search_text = ""

    def _safe_len(self, *tags: str) -> int:
        hold = max(len(tag) for tag in tags) - 1
        return max(0, len(self.buffer) - hold)

    def _finish_search(self):
        query = self._search_text.strip()
        self._search_text = ""
        if query:
            self.search_queries.append(query)
            self.completed_search = True

    def _emit_response(self, text: str):
        if not text:
            return
        if self.thinking_started and not self.think_footer_done:
            self.renderer.show_thinking_footer()
            self.think_footer_done = True
        if not self.response_started:
            self.renderer.show_response_header()
            self.response_started = True

        self.response_text += text
        self.renderer.show_response(text)

    def _emit_thinking(self, text: str):
        if not text:
            return
        self.renderer.show_thinking(text)
        self.thinking_text += text

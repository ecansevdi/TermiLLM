from ui.markdown import REASONING_BASE, MarkdownFormatter
from ui.terminal import BG_BLACK, CYAN, DIM, RESET, YELLOW, get_page


class StreamRenderer:
    """Stream olaylarını terminale çizer."""

    def __init__(self):
        self.md_formatter = MarkdownFormatter()
        self._reasoning_md = MarkdownFormatter(base_style=REASONING_BASE)
        self._streamed = False

    def response_stamp(self) -> str:
        """Cevap basıldıysa saat damgası (yoksa None) ve durumu sıfırlar."""
        if self._streamed:
            self._streamed = False
            from ui import clock
            return clock.now_str()
        return None

    @staticmethod
    def _emit(text: str, end: str = ""):
        """Sayfa modunda sayfaya, değilse terminale yazar."""
        page = get_page()
        if page is not None and page.active:
            page.feed_print(text + end)
        else:
            print(text, end=end, flush=True)

    def show_thinking_started(self, reasoning_kind: str = "raw"):
        if reasoning_kind == "summary":
            label = "💭 Düşünme özeti..."
        else:
            label = "💭 Düşünüyor..."
        self._emit(f"{DIM}{YELLOW}{label}{RESET}", end="\n")

    def show_thinking(self, text: str):
        # Taban stil formatter'da: her satır turuncu açılır, Markdown span'i
        # kapanınca renk düşmez. Sayfa satırı FG_WHITE ile boyadığı için
        # renk parçanın başında değil, satırın kendi SGR'sinde durur.
        formatted = self._reasoning_md.feed(text)
        if formatted:
            self._emit(formatted)

    def show_thinking_footer(self):
        leftover = self._reasoning_md.flush()
        if leftover:
            self._emit(leftover)
        self._emit(RESET + BG_BLACK, end="\n\n")

    def show_response_header(self):
        self._emit(f"{RESET}{BG_BLACK}{CYAN}Ajan:{RESET}{BG_BLACK} ")

    def show_response(self, text: str):
        if text.strip():
            self._streamed = True
        formatted = self.md_formatter.feed(text)
        self._emit(formatted)

    def flush_output(self):
        leftover = self.md_formatter.flush()
        if leftover:
            self._emit(leftover)
            self._streamed = True
        self._emit(RESET + BG_BLACK)

    def show_stream_end(self):
        self._emit("", end="\n")

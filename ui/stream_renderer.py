from ui.markdown import MarkdownFormatter
from ui.terminal import CYAN, DIM, RESET, YELLOW


class StreamRenderer:
    """Stream olaylarını terminale çizer."""

    def __init__(self):
        self.md_formatter = MarkdownFormatter()

    def show_thinking_started(self):
        print(f"\n{DIM}{YELLOW}💭 Düşünüyor...{RESET}")

    def show_thinking(self, text: str):
        print(f"{DIM}{YELLOW}{text}{RESET}", end="", flush=True)

    def show_thinking_footer(self):
        print(f"\n{DIM}{'─' * 40}{RESET}")

    def show_response_header(self):
        print(f"\n{CYAN}Ajan:{RESET} ", end="", flush=True)

    def show_response(self, text: str):
        formatted = self.md_formatter.feed(text)
        print(formatted, end="", flush=True)

    def flush_output(self):
        leftover = self.md_formatter.flush()
        if leftover:
            print(leftover, end="", flush=True)
        print(RESET, end="", flush=True)

    def show_stream_end(self):
        print("\n")

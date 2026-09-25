"""Reasoning metninin taban rengi Markdown ve satır bölünmesinde turuncu kalır."""

import unittest

from ui.markdown import REASONING_BASE, MarkdownFormatter
from ui.stream_renderer import StreamRenderer
from ui.terminal import BG_BLACK, BOLD, CYAN, FG_WHITE, ITALIC, YELLOW

_SGR_END = "m"


def _paint(formatted: str) -> list[str]:
    """Page._render_row düz satırı FG_WHITE ile açar. Renk satırın içinde durmalı."""
    return [f"{BG_BLACK}{FG_WHITE}{line}" for line in formatted.split("\n")]


def _styles(line: str):
    """Her görünür karakter için (ch, fg, bold, italic, gray_bg)."""
    fg = None
    bold = False
    italic = False
    gray = False
    out = []
    i = 0
    n = len(line)
    while i < n:
        if line.startswith("\033[", i):
            j = line.find(_SGR_END, i)
            if j == -1:
                break
            params = line[i + 2:j].split(";")
            k = 0
            while k < len(params):
                p = params[k]
                if p in ("", "0"):
                    fg = None
                    bold = False
                    italic = False
                    gray = False
                    k += 1
                elif p == "1":
                    bold = True
                    k += 1
                elif p == "2":
                    bold = False
                    k += 1
                elif p == "22":
                    bold = False
                    k += 1
                elif p == "3":
                    italic = True
                    k += 1
                elif p == "23":
                    italic = False
                    k += 1
                elif p == "48" and k + 2 < len(params) and params[k + 1] == "5":
                    gray = True
                    k += 3
                elif p in ("40", "49"):
                    gray = False
                    k += 1
                elif p in ("93", "97", "96", "92", "91", "94", "95", "39"):
                    fg = None if p == "39" else p
                    k += 1
                else:
                    k += 1
            i = j + 1
            continue
        out.append((line[i], fg, bold, italic, gray))
        i += 1
    return out


def assert_reasoning_color(formatted: str):
    """Normal metin 93; kod/başlık 96; gri zeminli blokta 97 serbest. Default yok."""
    for line in _paint(formatted):
        for ch, fg, _bold, _italic, gray in _styles(line):
            if gray and fg == "97":
                continue
            if fg not in ("93", "96"):
                raise AssertionError(
                    f"{ch!r} fg={fg!r} satır={line!r}"
                )


def _run(text, chunks=None):
    fmt = MarkdownFormatter(base_style=REASONING_BASE)
    out = ""
    parts = chunks if chunks is not None else [text]
    for part in parts:
        out += fmt.feed(part)
        assert_reasoning_color(out)
    out += fmt.flush()
    assert_reasoning_color(out)
    return out


def _visible(text: str) -> str:
    import re
    return re.sub(r"\033\[[0-9;]*[A-Za-z]", "", text)


class TestReasoningBaseColor(unittest.TestCase):
    SAMPLE = (
        "* Language: Turkish.\n"
        "* Requirement: Keep it clear.\n"
        "* I am a **large language model** trained by Google."
    )

    def test_plain_text_is_orange(self):
        out = _run("normal text")
        self.assertIn("normal text", _visible(out))
        fgs = {fg for _c, fg, _b, _i, _g in _styles(_paint(out)[0])}
        self.assertEqual(fgs, {"93"})

    def test_bullets_stay_orange(self):
        out = _run("* item one\n* item two")
        vis = _visible(out)
        self.assertIn("* item one", vis)
        self.assertIn("* item two", vis)
        assert_reasoning_color(out)

    def test_bold_returns_to_orange(self):
        out = _run("This is **important** text.")
        vis = _visible(out)
        self.assertIn("This is important text.", vis)
        self.assertNotIn("**", vis)
        styles = _styles(_paint(out)[0])
        chars = "".join(ch for ch, *_ in styles)
        start = chars.index("important")
        end = start + len("important")
        self.assertTrue(all(bold for _c, _f, bold, _i, _g in styles[start:end]))
        after = styles[end]
        self.assertEqual(after[1], "93")
        self.assertFalse(after[2])

    def test_italic_returns_to_orange(self):
        out = _run("This is *important* text.")
        vis = _visible(out)
        self.assertIn("This is important text.", vis)
        self.assertNotIn("*important*", vis)
        styles = _styles(_paint(out)[0])
        chars = "".join(ch for ch, *_ in styles)
        start = chars.index("important")
        end = start + len("important")
        self.assertTrue(all(italic for _c, _f, _b, italic, _g in styles[start:end]))
        after = styles[end]
        self.assertEqual(after[1], "93")
        self.assertFalse(after[3])

    def test_inline_code_returns_to_orange(self):
        out = _run("Use `reasoning_content`.")
        vis = _visible(out)
        self.assertIn("Use reasoning_content.", vis)
        styles = _styles(_paint(out)[0])
        chars = "".join(ch for ch, *_ in styles)
        start = chars.index("reasoning_content")
        end = start + len("reasoning_content")
        self.assertTrue(all(fg == "96" for _c, fg, *_ in styles[start:end]))
        self.assertEqual(styles[end][1], "93")
        self.assertEqual(styles[0][1], "93")

    def test_spec_sample_char_by_char_and_chunks(self):
        _run(self.SAMPLE, chunks=list(self.SAMPLE))
        _run(self.SAMPLE, chunks=[
            "* Lang",
            "uage: Turkish.\n",
            "* Req",
            "uirement: Keep it clear.\n",
            "* I am a **large",
            " language model** trained by Google.",
        ])

    def test_newline_inside_one_chunk_does_not_drop_color(self):
        _run("* User asks: hello\n    * Language: Turkish.\n    * Requirement: x")

    def test_renderer_uses_base_style(self):
        chunks = []

        class Capture(StreamRenderer):
            def _emit(self, text, end=""):
                chunks.append(text + end)

        view = Capture()
        text = "* Language: Turkish.\n* Requirement: Keep it clear."
        for ch in text:
            view.show_thinking(ch)
        view.show_thinking_footer()
        body = "".join(chunks)
        self.assertIn(YELLOW, body)
        assert_reasoning_color(body.split("\n\n")[0])


class TestAnswerMarkdownUnchanged(unittest.TestCase):
    def test_answer_has_no_reasoning_orange(self):
        fmt = MarkdownFormatter()
        out = fmt.feed("Hello **bold** and `code`.\n# Title\nplain\n")
        out += fmt.flush()
        self.assertNotIn(YELLOW, out)
        self.assertNotIn(REASONING_BASE, out)
        self.assertIn(BOLD, out)
        self.assertIn(CYAN, out)
        vis = _visible(out)
        self.assertIn("Hello bold and code.", vis)
        self.assertIn("# Title", vis)
        self.assertNotIn(ITALIC, out)

    def test_answer_keeps_literal_single_star(self):
        fmt = MarkdownFormatter()
        out = fmt.feed("see *this* star")
        out += fmt.flush()
        self.assertIn("*this*", _visible(out))
        self.assertNotIn(ITALIC, out)


if __name__ == "__main__":
    unittest.main()

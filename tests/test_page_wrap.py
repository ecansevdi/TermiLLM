"""Canlı satır, newline gelmeden ekran genişliğinde alt satıra sarılır."""

import io
import unittest

from ui.page import Page, visible_width


def _page(cols=10):
    page = Page("T")
    page.active = True
    page._cols = cols
    page._rows = 24
    page._real_stdout = io.StringIO()
    return page


class TestLiveWrap(unittest.TestCase):
    def test_overflow_commits_before_newline(self):
        page = _page(10)
        page.feed_print("abcdefghijKLM")
        self.assertEqual(len(page._seen), 1)
        self.assertEqual(visible_width(page._seen[0][0]), 10)
        self.assertEqual(page._seen[0][0], "abcdefghij")
        self.assertEqual(page._print_buf, "KLM")

    def test_further_chunks_keep_wrapping(self):
        page = _page(4)
        page.feed_print("ab")
        self.assertEqual(page._seen, [])
        self.assertEqual(page._print_buf, "ab")
        page.feed_print("cdefgh")
        self.assertEqual([ln for ln, _ in page._seen], ["abcd"])
        self.assertEqual(page._print_buf, "efgh")
        page.feed_print("i")
        self.assertEqual([ln for ln, _ in page._seen], ["abcd", "efgh"])
        self.assertEqual(page._print_buf, "i")

    def test_newline_still_splits(self):
        page = _page(20)
        page.feed_print("bir\niki")
        self.assertEqual([ln for ln, _ in page._seen], ["bir"])
        self.assertEqual(page._print_buf, "iki")

    def test_color_carries_onto_wrapped_live_row(self):
        page = _page(4)
        page.feed_print("\033[93mabcdef")
        self.assertEqual(visible_width(page._seen[0][0]), 4)
        self.assertIn("\033[93m", page._print_buf)
        self.assertEqual(visible_width(page._print_buf), 2)


if __name__ == "__main__":
    unittest.main()

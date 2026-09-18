"""@dosya ve ?arama belirteçleri ile dosya tamamlama birim testleri."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chat.mentions import MentionError, MentionProcessor, parse_mentions
from ui.completer import (
    _display_path,
    _split_user_path,
    enter_browser_dir,
    file_completion_matches,
    list_browser_entries,
    parse_browse_token,
    token_at_cursor,
)
from ui.picker import clamp_height, visible_window


class TestParseMentions(unittest.TestCase):
    def test_plain_prompt_unchanged(self):
        actions, rest = parse_mentions("sadece bir soru")
        self.assertEqual(actions, [])
        self.assertEqual(rest, "sadece bir soru")

    def test_file_keeps_remaining_prompt(self):
        actions, rest = parse_mentions("@readme.md şunu özetle")
        self.assertEqual(actions, [("file", "readme.md")])
        self.assertEqual(rest, "şunu özetle")

    def test_file_in_the_middle(self):
        actions, rest = parse_mentions("şu kodu @main.py incele lütfen")
        self.assertEqual(actions, [("file", "main.py")])
        self.assertEqual(rest, "şu kodu incele lütfen")

    def test_multiple_files(self):
        actions, rest = parse_mentions("@a.py @b.py karşılaştır")
        self.assertEqual(actions, [("file", "a.py"), ("file", "b.py")])
        self.assertEqual(rest, "karşılaştır")

    def test_quoted_path_with_spaces(self):
        actions, rest = parse_mentions('@"benim dosya.txt" oku')
        self.assertEqual(actions, [("file", "benim dosya.txt")])
        self.assertEqual(rest, "oku")

    def test_relative_and_home_paths(self):
        actions, rest = parse_mentions("@../x.py @~/n.txt bak")
        self.assertEqual(actions, [("file", "../x.py"), ("file", "~/n.txt")])
        self.assertEqual(rest, "bak")

    def test_email_is_not_a_file_mention(self):
        actions, rest = parse_mentions("yaz user@example.com adresine")
        self.assertEqual(actions, [])
        self.assertEqual(rest, "yaz user@example.com adresine")

    def test_search_quoted_keeps_prompt(self):
        actions, rest = parse_mentions('?"python 3.14 changelog" bunu özetle')
        self.assertEqual(actions, [("search", "python 3.14 changelog")])
        self.assertEqual(rest, "bunu özetle")

    def test_search_braces(self):
        actions, rest = parse_mentions("?{çok kelimeli sorgu} yorumla")
        self.assertEqual(actions, [("search", "çok kelimeli sorgu")])
        self.assertEqual(rest, "yorumla")

    def test_search_unquoted_token(self):
        actions, rest = parse_mentions("?asyncio nedir")
        self.assertEqual(actions, [("search", "asyncio")])
        self.assertEqual(rest, "nedir")

    def test_file_and_search_together(self):
        actions, rest = parse_mentions('@src/main.py ?"python match" karşılaştır')
        self.assertEqual(actions, [
            ("file", "src/main.py"),
            ("search", "python match"),
        ])
        self.assertEqual(rest, "karşılaştır")

    def test_only_mentions_rest_empty(self):
        actions, rest = parse_mentions("@a.py")
        self.assertEqual(actions, [("file", "a.py")])
        self.assertEqual(rest, "")

    def test_trailing_punctuation_stripped_from_unquoted_path(self):
        actions, rest = parse_mentions("bak @notes.txt.")
        self.assertEqual(actions, [("file", "notes.txt")])
        self.assertEqual(rest, "bak")


class TestFileCompletion(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        os.chdir(self.root)
        (self.root / "config.py").write_text("x")
        (self.root / "readme.md").write_text("x")
        (self.root / "src").mkdir()
        (self.root / "src" / "main.py").write_text("x")
        (self.root / "src" / "util.py").write_text("x")
        (self.root / "__pycache__").mkdir()
        (self.root / ".hidden").write_text("x")

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_empty_prefix_lists_cwd(self):
        matches = file_completion_matches("")
        self.assertIn("config.py", matches)
        self.assertIn("readme.md", matches)
        self.assertIn("src/", matches)
        self.assertNotIn("__pycache__/", matches)
        self.assertNotIn(".hidden", matches)

    def test_prefix_and_substring(self):
        self.assertEqual(file_completion_matches("conf"), ["config.py"])
        self.assertEqual(file_completion_matches("fig"), ["config.py"])
        self.assertEqual(file_completion_matches("read"), ["readme.md"])

    def test_subdirectory(self):
        matches = file_completion_matches("src/")
        self.assertIn("src/main.py", matches)
        self.assertIn("src/util.py", matches)

    def test_parent_directory_prefix(self):
        os.chdir(self.root / "src")
        matches = file_completion_matches("../")
        self.assertIn("../config.py", matches)
        self.assertIn("../readme.md", matches)
        self.assertIn("../src/", matches)

    def test_absolute_path(self):
        prefix = str(self.root / "src") + "/"
        matches = file_completion_matches(prefix)
        self.assertTrue(any(m.endswith("main.py") for m in matches))

    def test_browser_entries_include_parent(self):
        entries = list_browser_entries("")
        self.assertIn("../", entries)
        self.assertIn("src/", entries)
        self.assertIn("config.py", entries)
        self.assertNotIn("src/main.py", entries)

    def test_browser_inside_src(self):
        entries = list_browser_entries("src/")
        self.assertIn("../", entries)
        self.assertIn("main.py", entries)
        self.assertIn("util.py", entries)

    def test_split_home_style(self):
        abs_dir, needle, root_label, rel_dir = _split_user_path("~/Docs/a")
        self.assertEqual(root_label, "~/")
        self.assertEqual(needle, "a")
        self.assertEqual(rel_dir.replace("\\", "/"), "Docs")
        self.assertEqual(os.path.basename(abs_dir), "Docs")

class TestMentionProcessor(unittest.TestCase):
    def test_attaches_file_and_returns_rest(self):
        files = mock.Mock()
        files.load.return_value = "icerik"
        images = mock.Mock()
        attachments = mock.Mock()
        search = mock.Mock()
        proc = MentionProcessor(files, images, attachments, search)

        rest = proc.process("@notes.txt bunu özetle")

        self.assertEqual(rest, "bunu özetle")
        files.load.assert_called_once()
        attachments.add_text.assert_called_once()
        self.assertIn("notes.txt", attachments.add_text.call_args[0][0])
        images.load.assert_not_called()

    def test_missing_file_raises(self):
        files = mock.Mock()
        files.load.side_effect = FileNotFoundError("yok")
        proc = MentionProcessor(files, mock.Mock(), mock.Mock(), mock.Mock())
        with self.assertRaises(MentionError):
            proc.process("@yok.txt merhaba")

    def test_search_attaches_results_keeps_prompt(self):
        result = mock.Mock(title="T", url="http://x", snippet="s")
        search = mock.Mock()
        search.load.return_value = mock.Mock(provider="searxng")
        search.search.return_value = [result]
        search.format_for_model.return_value = "--- web ---"
        attachments = mock.Mock()
        proc = MentionProcessor(mock.Mock(), mock.Mock(), attachments, search)

        rest = proc.process('?"python docs" bunu oku')

        self.assertEqual(rest, "bunu oku")
        search.search.assert_called_once()
        attachments.add_text.assert_called_once_with("--- web ---")

    def test_image_extension_uses_image_loader(self):
        images = mock.Mock()
        images.load.return_value = ("YmFzZTY0", "image/png")
        attachments = mock.Mock()
        proc = MentionProcessor(mock.Mock(), images, attachments, mock.Mock())
        rest = proc.process("@foto.png bunu açıkla")
        self.assertEqual(rest, "bunu açıkla")
        images.load.assert_called_once()
        attachments.set_image.assert_called_once()

    def test_audio_extension_transcribes(self):
        audio = mock.Mock()
        audio.transcribe_file.return_value = "merhaba dünya"
        attachments = mock.Mock()
        proc = MentionProcessor(
            mock.Mock(), mock.Mock(), attachments, mock.Mock(), audio=audio)
        rest = proc.process("@konusma.wav özetle")
        self.assertEqual(rest, "özetle")
        audio.transcribe_file.assert_called_once()
        attachments.add_text.assert_called_once()
        self.assertIn("Ses:", attachments.add_text.call_args[0][0])
        self.assertIn("merhaba dünya", attachments.add_text.call_args[0][0])


class TestPickerWindow(unittest.TestCase):
    def test_visible_window_centers_index(self):
        items = list("abcdefghij")
        view, start = visible_window(items, 5, 4)
        self.assertEqual(len(view), 4)
        self.assertIn("f", view)
        self.assertEqual(items[start:start + 4], view)

    def test_visible_window_short_list(self):
        view, start = visible_window(["a", "b"], 0, 8)
        self.assertEqual(view, ["a", "b"])
        self.assertEqual(start, 0)

    def test_term_size_uses_lines(self):
        from ui.picker import _term_size
        cols, lines = _term_size()
        self.assertIsInstance(cols, int)
        self.assertIsInstance(lines, int)
        self.assertGreater(cols, 0)
        self.assertGreater(lines, 0)

    def test_clamp_height(self):
        self.assertEqual(clamp_height(3, 20, 40), 4)
        self.assertEqual(clamp_height(100, 20, 40), 16)
        self.assertGreaterEqual(clamp_height(8, 3, 24), 4)


class TestBrowseNav(unittest.TestCase):
    def test_parse_token(self):
        self.assertEqual(parse_browse_token("@"), ("", ""))
        self.assertEqual(parse_browse_token("@src/"), ("src/", ""))
        self.assertEqual(parse_browse_token("@src/foo"), ("src/", "foo"))
        self.assertEqual(parse_browse_token("@foo"), ("", "foo"))

    def test_enter_dir(self):
        self.assertEqual(enter_browser_dir("", "src"), "src/")
        self.assertEqual(enter_browser_dir("src/", "foo"), "src/foo/")
        self.assertEqual(enter_browser_dir("src/", ".."), "")
        self.assertEqual(enter_browser_dir("", ".."), "../")
        self.assertEqual(enter_browser_dir("../", ".."), "../../")
        self.assertEqual(enter_browser_dir("src/foo/", ".."), "src/")


class TestTokenAtCursor(unittest.TestCase):
    def test_at_start(self):
        self.assertEqual(token_at_cursor(list("@"), 1), (0, "@"))

    def test_after_space(self):
        chars = list("bak @fo")
        self.assertEqual(token_at_cursor(chars, len(chars)), (4, "@fo"))

    def test_email_is_not_at_token(self):
        start, token = token_at_cursor(list("a@b"), 3)
        self.assertEqual((start, token), (0, "a@b"))
        self.assertFalse(token.startswith("@"))


class TestDisplayPath(unittest.TestCase):
    def test_display_absolute(self):
        self.assertEqual(_display_path("/", "etc", "hosts", False), "/etc/hosts")
        self.assertEqual(_display_path("~/", "Docs", "a.txt", False), "~/Docs/a.txt")
        self.assertEqual(_display_path("", "src", "main.py", False), "src/main.py")
        self.assertEqual(_display_path("", "", "src", True), "src/")


if __name__ == "__main__":
    unittest.main()

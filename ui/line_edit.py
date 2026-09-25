"""Satır editörü: sayfa modunda çok satırlı kutu, düz modda klasik satır.

Sayfa modunda (Page etkin) girdi, sayfanın altındaki sabit gri kutuda okunur:
Enter gönderir, Shift+Enter/Ctrl+J yeni satır açar. Düz modda eski davranış
(@ yazınca dosya kutusu) korunur.
"""

from __future__ import annotations

import sys

from ui.terminal import GREEN, RESET, get_page

PROMPT_VISIBLE = "Sen: "
_HISTORY: list[str] = []


def _redraw(chars: list[str], pos: int):
    line = "".join(chars)
    sys.stdout.write("\r" + GREEN + PROMPT_VISIBLE + RESET + line + "\033[K")
    trail = len(chars) - pos
    if trail > 0:
        sys.stdout.write(f"\033[{trail}D")
    sys.stdout.flush()


def _open_picker_flat(chars: list[str], pos: int) -> tuple[list[str], int]:
    from ui.completer import token_at_cursor
    from ui.picker import pick_file

    start, token = token_at_cursor(chars, pos)
    if not token.startswith("@"):
        return chars, pos
    chosen = pick_file(token)
    if not chosen:
        _redraw(chars, pos)
        return chars, pos
    if not chosen.endswith("/"):
        chosen = chosen + " "
    chars[start:pos] = list(chosen)
    pos = start + len(chosen)
    _redraw(chars, pos)
    return chars, pos


def read_line(prefill: str = "", poll_prefill=None) -> str:
    """Bir satır oku. Ctrl-C KeyboardInterrupt, boş satırda Ctrl-D EOFError.

    Sayfa modunda Page.get_input kullanılır (çok satırlı gri kutu).
    """
    page = get_page()
    if page is not None and page.active:
        if prefill:
            return page.get_input(poll_prefill=lambda: prefill)
        return page.get_input(poll_prefill=poll_prefill)

    if not sys.stdin.isatty():
        line = sys.stdin.readline()
        if line == "":
            raise EOFError
        return line.rstrip("\n")

    return _read_line_flat(prefill, poll_prefill)


def _read_line_flat(prefill: str, poll_prefill) -> str:
    """Klasik tek satır editörü (sayfa kapalıyken)."""
    import select
    import termios
    import tty

    from ui.completer import token_at_cursor
    from ui.keys import read_key

    fd = sys.stdin.fileno()
    chars = list(prefill or "")
    pos = len(chars)
    hist_idx = None
    saved = None

    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        _redraw(chars, pos)
        while True:
            if poll_prefill:
                extra = poll_prefill()
                if extra:
                    chars[pos:pos] = list(extra)
                    pos += len(extra)
                    _redraw(chars, pos)

            ready, _, _ = select.select([fd], [], [], 0.2)
            if not ready:
                continue
            key = read_key(fd)
            if key == "ctrl-c":
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                raise KeyboardInterrupt
            if key in ("ctrl-d", "shift-enter"):
                if key == "ctrl-d" and not chars:
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    raise EOFError
                if key == "shift-enter":
                    continue
            if key == "enter":
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                line = "".join(chars)
                if line.strip():
                    _HISTORY.append(line)
                return line
            if key == "left":
                pos = max(0, pos - 1)
            elif key == "right":
                pos = min(len(chars), pos + 1)
            elif key in ("home", "ctrl-a"):
                pos = 0
            elif key in ("end", "ctrl-e"):
                pos = len(chars)
            elif key == "backspace":
                if pos > 0:
                    del chars[pos - 1]
                    pos -= 1
            elif key == "delete":
                if pos < len(chars):
                    del chars[pos]
            elif key == "ctrl-u":
                chars[:pos] = []
                pos = 0
            elif key == "ctrl-k":
                chars[pos:] = []
            elif key == "ctrl-w":
                while pos > 0 and chars[pos - 1] in " \t":
                    del chars[pos - 1]
                    pos -= 1
                while pos > 0 and chars[pos - 1] not in " \t":
                    del chars[pos - 1]
                    pos -= 1
            elif key == "up":
                if hist_idx is None:
                    saved = "".join(chars)
                    hist_idx = len(_HISTORY)
                if hist_idx > 0:
                    hist_idx -= 1
                    chars = list(_HISTORY[hist_idx])
                    pos = len(chars)
            elif key == "down":
                if hist_idx is None:
                    pass
                elif hist_idx + 1 >= len(_HISTORY):
                    hist_idx = None
                    chars = list(saved or "")
                    pos = len(chars)
                else:
                    hist_idx += 1
                    chars = list(_HISTORY[hist_idx])
                    pos = len(chars)
            elif key == "tab":
                chars, pos = _open_picker_flat(chars, pos)
                _redraw(chars, pos)
                continue
            elif key == "esc":
                pass
            elif len(key) == 1 and key.isprintable():
                chars.insert(pos, key)
                pos += 1
                _redraw(chars, pos)
                _, token = token_at_cursor(chars, pos)
                if token == "@":
                    chars, pos = _open_picker_flat(chars, pos)
                continue
            _redraw(chars, pos)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

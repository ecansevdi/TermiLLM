"""Kendi satır editörü: @ yazılınca dosya kutusu açılır.

Readline tamamlama Tab'a bağlıdır ve kutu onun içinde kaybolur.
Burada her tuş bize gelir; token başında @ görünce kutu hemen açılır.
"""

from __future__ import annotations

import select
import sys
import termios
import tty

from ui.completer import token_at_cursor
from ui.keys import read_key
from ui.picker import pick_file
from ui.terminal import GREEN, RESET

PROMPT_VISIBLE = "Sen: "
_HISTORY: list[str] = []


def _redraw(chars: list[str], pos: int):
    line = "".join(chars)
    sys.stdout.write("\r" + GREEN + PROMPT_VISIBLE + RESET + line + "\033[K")
    trail = len(chars) - pos
    if trail > 0:
        sys.stdout.write(f"\033[{trail}D")
    sys.stdout.flush()


def _open_picker(chars: list[str], pos: int) -> tuple[list[str], int]:
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
    """Bir satır oku. Ctrl-C KeyboardInterrupt, boş satırda Ctrl-D EOFError."""
    fd = sys.stdin.fileno()
    chars = list(prefill or "")
    pos = len(chars)
    hist_idx = None
    saved = None

    if not sys.stdin.isatty():
        line = sys.stdin.readline()
        if line == "":
            raise EOFError
        return line.rstrip("\n")

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
            if key == "ctrl-d":
                if not chars:
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    raise EOFError
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
                chars, pos = _open_picker(chars, pos)
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
                    chars, pos = _open_picker(chars, pos)
                continue
            _redraw(chars, pos)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

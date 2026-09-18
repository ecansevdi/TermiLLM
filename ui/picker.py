"""Satır altındaki açılır dosya kutusu.

Prompt'un altında sabit durur; yukarı-aşağı seçim satırları silmez.
Dizinlere Enter ile girilir; listede ../ vardır.

  ↑ ↓ / Tab  seçimi gez
  Enter      dosyayı al / dizine gir
  Esc        kapat
  + / -      boyutu büyüt / küçült
"""

from __future__ import annotations

import shutil
import sys

from ui.completer import enter_browser_dir, list_browser_entries, parse_browse_token
from ui.keys import read_key
from ui.terminal import CYAN, DIM, GREEN, RESET

MIN_HEIGHT = 4
MAX_HEIGHT = 16
DEFAULT_HEIGHT = 8

_BOX_HEIGHT = DEFAULT_HEIGHT


def visible_window(items: list, index: int, size: int) -> tuple[list, int]:
    """Seçim ortada kalacak şekilde bir dilim döndürür (dilim, start)."""
    if size <= 0 or not items:
        return [], 0
    if len(items) <= size:
        return items, 0
    start = min(max(0, index - size // 2), len(items) - size)
    return items[start:start + size], start


def clamp_height(height: int, n_items: int, rows: int) -> int:
    cap = max(MIN_HEIGHT, min(MAX_HEIGHT, max(4, rows - 6)))
    return max(MIN_HEIGHT, min(cap, height, max(n_items, MIN_HEIGHT)))


def _term_size() -> tuple[int, int]:
    size = shutil.get_terminal_size((80, 24))
    return size.columns, size.lines


def _fit(text: str, width: int) -> str:
    if width <= 1:
        return "…"
    if len(text) <= width:
        return text.ljust(width)
    return text[: width - 1] + "…"


def _compose_lines(items: list, index: int, height: int, cols: int,
                   needle: str, prefix: str) -> list[str]:
    inner = max(36, min(cols - 2, 62))
    n = len(items)
    view_h = min(height, max(n, 1))
    view, start = visible_window(items, index, view_h)
    loc = "@" + (prefix or "")
    extra = f" /{needle}" if needle else ""
    pos = f"{index + 1}/{n}" if n else "0/0"
    header = f" {loc} {pos}{extra}  ↑↓ Enter Esc +/- "
    header = header[:inner].ljust(inner, "─")
    top = "┌" + header + "┐"
    bot = "└" + ("─" * inner) + "┘"

    lines = [f"{CYAN}{top}{RESET}"]
    if not items:
        lines.append(
            f"{CYAN}│{RESET}{DIM}{_fit(' (eşleşme yok)', inner)}{RESET}{CYAN}│{RESET}"
        )
    for offset, item in enumerate(view):
        abs_i = start + offset
        marker = "▸" if abs_i == index else " "
        body = _fit(f"{marker} {item}", inner)
        if abs_i == index:
            lines.append(f"{CYAN}│{RESET}{GREEN}{body}{RESET}{CYAN}│{RESET}")
        else:
            lines.append(f"{CYAN}│{RESET}{DIM}{body}{RESET}{CYAN}│{RESET}")
    lines.append(f"{CYAN}{bot}{RESET}")
    return lines


def _draw(lines: list[str], first: bool) -> int:
    """Kutuyu basar. first=True iken prompt'un altına iner.
    Dönüş: kutunun satır sayısı (silmek için)."""
    if first:
        sys.stdout.write("\r\n")
    sys.stdout.write("\r\n".join(lines))
    sys.stdout.flush()
    return len(lines)


def _erase_box(n_lines: int):
    """Kutuyu siler; imleç kutunun ilk satırında kalır (prompt durur)."""
    if n_lines <= 0:
        return
    if n_lines > 1:
        sys.stdout.write(f"\033[{n_lines - 1}A")
    sys.stdout.write("\r\033[J")
    sys.stdout.flush()


def _return_to_prompt(n_lines: int):
    _erase_box(n_lines)
    sys.stdout.write("\033[1A\r")
    sys.stdout.flush()


def _filter(entries: list[str], needle: str) -> list[str]:
    if not needle:
        return list(entries)
    n = needle.lower()
    return [e for e in entries if n in e.lower()]


def pick_file(token: str = "@") -> str | None:
    """Dizin gezicili kutu. Dosya seçilince '@yol' döner; Esc'de None."""
    global _BOX_HEIGHT
    if not sys.stdin.isatty():
        return None

    prefix, needle = parse_browse_token(token)
    entries = list_browser_entries(prefix)
    filtered = _filter(entries, needle)
    cols, rows = _term_size()
    height = clamp_height(_BOX_HEIGHT, len(filtered) or 1, rows)
    index = 0
    drawn = 0
    first = True

    def refresh():
        nonlocal entries, filtered, index, height
        entries = list_browser_entries(prefix)
        filtered = _filter(entries, needle)
        if filtered:
            index = min(index, len(filtered) - 1)
        else:
            index = 0
        height = clamp_height(_BOX_HEIGHT, len(filtered) or 1, rows)

    try:
        while True:
            if drawn:
                _erase_box(drawn)
                first = False
            lines = _compose_lines(filtered, index, height, cols, needle, prefix)
            drawn = _draw(lines, first)
            first = False
            key = read_key(sys.stdin.fileno())
            if key in ("+", "="):
                height = clamp_height(height + 1, len(filtered) or 1, rows)
                _BOX_HEIGHT = height
            elif key in ("-", "_"):
                height = clamp_height(height - 1, len(filtered) or 1, rows)
                _BOX_HEIGHT = height
            elif key == "up":
                if filtered:
                    index = (index - 1) % len(filtered)
            elif key in ("down", "tab"):
                if filtered:
                    index = (index + 1) % len(filtered)
            elif key == "enter":
                if not filtered:
                    continue
                chosen = filtered[index]
                if chosen.endswith("/"):
                    prefix = enter_browser_dir(prefix, chosen)
                    needle = ""
                    index = 0
                    refresh()
                    continue
                _return_to_prompt(drawn)
                drawn = 0
                return "@" + prefix + chosen
            elif key in ("esc", "ctrl-c", "ctrl-d"):
                _return_to_prompt(drawn)
                drawn = 0
                if key == "ctrl-c":
                    raise KeyboardInterrupt
                return None
            elif key == "backspace":
                if needle:
                    needle = needle[:-1]
                    filtered = _filter(entries, needle)
                    index = 0
                else:
                    prefix = enter_browser_dir(prefix, "..")
                    index = 0
                    refresh()
            elif len(key) == 1 and key.isprintable():
                needle += key
                filtered = _filter(entries, needle)
                index = 0
    except KeyboardInterrupt:
        _return_to_prompt(drawn)
        raise
    except Exception:
        _return_to_prompt(drawn)
        return None

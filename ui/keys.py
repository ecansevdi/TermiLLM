"""Ham terminal tuş okuma (UTF-8, ok tuşları, Esc)."""

from __future__ import annotations

import os
import select


def read_key(fd: int = 0) -> str:
    """Tek tuş. Özel adlar: enter, tab, esc, up, down, left, right,
    backspace, delete, home, end, grow, shrink, ctrl-c, ctrl-d, ctrl-u,
    ctrl-k, ctrl-a, ctrl-e, ctrl-w.
    """
    b = os.read(fd, 1)
    if not b:
        return "ctrl-d"
    c = b[0]
    if c == 0x03:
        return "ctrl-c"
    if c == 0x04:
        return "ctrl-d"
    if c == 0x01:
        return "ctrl-a"
    if c == 0x05:
        return "ctrl-e"
    if c == 0x0B:
        return "ctrl-k"
    if c == 0x15:
        return "ctrl-u"
    if c == 0x17:
        return "ctrl-w"
    if c in (0x0D, 0x0A):
        return "enter"
    if c == 0x09:
        return "tab"
    if c in (0x7F, 0x08):
        return "backspace"
    if c != 0x1B:
        return _decode_utf8(fd, b)

    ready, _, _ = select.select([fd], [], [], 0.05)
    if not ready:
        return "esc"
    nxt = os.read(fd, 1)
    if nxt == b"[":
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            return "esc"
        code = os.read(fd, 1)
        mapping = {b"A": "up", b"B": "down", b"C": "right", b"D": "left",
                   b"H": "home", b"F": "end", b"Z": "up"}
        if code in mapping:
            return mapping[code]
        if code == b"3":
            extra = os.read(fd, 1) if select.select([fd], [], [], 0.02)[0] else b""
            if extra == b"~":
                return "delete"
        if code in (b"5", b"6"):
            extra = os.read(fd, 1) if select.select([fd], [], [], 0.02)[0] else b""
            if extra == b"~":
                return "up" if code == b"5" else "down"
        return "esc"
    if nxt == b"O":
        ready, _, _ = select.select([fd], [], [], 0.05)
        if ready:
            code = os.read(fd, 1)
            if code == b"H":
                return "home"
            if code == b"F":
                return "end"
        return "esc"
    return "esc"


def _decode_utf8(fd: int, first: bytes) -> str:
    c = first[0]
    if c < 0x80:
        return first.decode("ascii")
    n = 2 if c < 0xE0 else 3 if c < 0xF0 else 4
    buf = bytearray(first)
    while len(buf) < n:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            break
        chunk = os.read(fd, n - len(buf))
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf).decode("utf-8", "replace")

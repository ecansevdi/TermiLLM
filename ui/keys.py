"""Ham terminal tuş okuma (UTF-8, ok tuşları, Esc, Shift+Enter, mouse)."""

from __future__ import annotations

import os
import select


# Fare seçim durumu (read_key çağrıları arasında korunur)
_sel_active = False
_sel_start = None   # (x, y)
_sel_end = None


def read_key(fd: int = 0, mouse: bool = False) -> str:
    """Tek tuş. Özel adlar: enter, shift-enter, ctrl-j, tab, esc, up, down,
    left, right, backspace, delete, home, end, wheel-up, wheel-down,
    ctrl-c, ctrl-d, ctrl-u, ctrl-k, ctrl-a, ctrl-e, ctrl-w.
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
    if c == 0x0A:
        # LF: Ctrl+J = yeni satır (ICRNL kapalı; Enter CR gelir)
        return "ctrl-j"
    if c == 0x0B:
        return "ctrl-k"
    if c == 0x15:
        return "ctrl-u"
    if c == 0x17:
        return "ctrl-w"
    if c == 0x0D:
        # CR dizisiyle mi geldi kontrol et (kitty/konsole: CSI 27;2;13~ vb.)
        ready, _, _ = select.select([fd], [], [], 0.005)
        if ready:
            nxt = os.read(fd, 1)
            if nxt == b"[":
                return _csi_sequence(fd)
            if nxt == b"O":
                ready2, _, _ = select.select([fd], [], [], 0.05)
                if ready2:
                    code = os.read(fd, 1)
                    if code == b"H":
                        return "home"
                    if code == b"F":
                        return "end"
                return "esc"
            return "enter"
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
        return _csi_sequence(fd)
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


def _csi_sequence(fd: int) -> str:
    ready, _, _ = select.select([fd], [], [], 0.05)
    if not ready:
        return "esc"
    code = os.read(fd, 1)
    if code == b"<":
        return _sgr_mouse(fd)
    if code == b"A":
        return "up"
    if code == b"B":
        return "down"
    if code == b"C":
        return "right"
    if code == b"D":
        return "left"
    if code == b"H":
        return "home"
    if code == b"F":
        return "end"
    if code == b"Z":
        return "up"
    if code == b"2":
        # CSI 27;2;13~ : kitty protokolü Shift+Enter (modifier 2)
        nxt = os.read(fd, 1) if select.select([fd], [], [], 0.02)[0] else b""
        if nxt == b"7":
            extra = os.read(fd, 1) if select.select([fd], [], [], 0.02)[0] else b""
            if extra == b";":
                rest = _read_csi_tail(fd)
                if rest.endswith(b"13~") or rest.endswith(b"13u"):
                    return "shift-enter"
                return "esc"
            return "esc"
        return "esc"
    if code == b"3":
        # CSI 3~ : Delete
        extra = os.read(fd, 1) if select.select([fd], [], [], 0.02)[0] else b""
        return "delete" if extra == b"~" else "esc"
    if code in (b"5", b"6"):
        # CSI 5~ / 6~ : PageUp / PageDown
        extra = os.read(fd, 1) if select.select([fd], [], [], 0.02)[0] else b""
        if extra == b"~":
            return "up" if code == b"5" else "down"
        return "esc"
    if code == b"1":
        # CSI 1~ : Home; CSI 13;2u : kitty/fixterms Shift+Enter;
        # CSI 1;5C : modifier'lı ok tuşları
        extra = os.read(fd, 1) if select.select([fd], [], [], 0.02)[0] else b""
        if extra == b"~":
            return "home"
        if extra == b"3":
            rest = _read_csi_tail(fd)
            if rest.endswith(b"2u"):
                return "shift-enter"
            return "esc"
        if extra == b";":
            rest = _read_csi_tail(fd)
            arrows = {b"A": "up", b"B": "down", b"C": "right", b"D": "left"}
            for suffix, name in arrows.items():
                if rest.endswith(suffix):
                    return name
            return "esc"
        return "esc"
    if code in (b"4", b"7", b"8"):
        # CSI 4~ End, 7~ Home, 8~ End
        extra = os.read(fd, 1) if select.select([fd], [], [], 0.02)[0] else b""
        if extra == b"~":
            if code == b"4":
                return "end"
            return "home"
        return "esc"
    return "esc"


def _sgr_mouse(fd: int) -> str:
    """SGR mouse olayı: CSI < b;x;y(M|m).

    Wheel: b=64 yukarı, 65 aşağı. Seçim modunda (mouse=True) sol tuş
    baskısı (b=0) sürükleme (b=32) ve bırakma (b=0 + m) seçim aralığını
    belirler; bırakışta 'selection:<metin>' döner.
    """
    global _sel_active, _sel_start, _sel_end

    tail = _read_csi_tail(fd)          # örn. b"64;10;5M"
    if not tail or not tail.endswith((b"M", b"m")):
        return "esc"
    release = tail.endswith(b"m")
    parts = tail[:-1].split(b";")
    if len(parts) != 3:
        return "esc"
    try:
        code = int(parts[0])
        x = int(parts[1])
        y = int(parts[2])
    except ValueError:
        return "esc"

    if code == 64:
        return "wheel-up"
    if code == 65:
        return "wheel-down"

    if not mouse:
        return "esc"

    base = code & 0x03
    if base == 0:                      # sol tuş
        if release:
            if _sel_active and _sel_start:
                _sel_active = False
                text = _extract_selection(_sel_start, _sel_end or _sel_start)
                _sel_start = _sel_end = None
                if text:
                    return f"selection:{text}"
                return "esc"
            _sel_active = True
            _sel_start = (x, y)
            _sel_end = (x, y)
            return "esc"
        if _sel_active:
            _sel_end = (x, y)
        return "esc"
    return "esc"


def _extract_selection(start: tuple, end: tuple) -> str:
    """Seçim koordinatlarını metne çevirir.

    Terminaller ekran içeriğini geri vermez; metni sayfanın içerik modeli
    (_page_model) sağlar. Model yoksa boş döner ve kopyalama sessizce geçer.
    """
    getter = _page_model
    if getter is None:
        return ""
    try:
        return getter(start, end)
    except Exception:
        return ""


# Page.set_screen_model() ile atanır: (start, end) -> metin
_page_model = None


def set_screen_model(getter) -> None:
    global _page_model
    _page_model = getter


def _read_csi_tail(fd: int) -> bytes:
    """CSI dizisinin sonunu (~ veya harf) okuyana dek toplar."""
    buf = bytearray()
    while True:
        ready, _, _ = select.select([fd], [], [], 0.02)
        if not ready:
            break
        ch = os.read(fd, 1)
        buf.extend(ch)
        if ch in (b"~",) or ch.isalpha():
            break
        if len(buf) > 32:
            break
    return bytes(buf)


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

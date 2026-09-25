"""Ham terminal tuş okuma (UTF-8, ok tuşları, Esc, Shift+Enter).

Fare olayları BİLİNÇLİ OLARAK yakalanmaz: uygulama mouse tracking modunu
(?1000/?1002/?1003/?1006) hiç açmaz, böylece metin seçimi terminalin
KENDİ native seçimidir (sol tuş + sürükleme, sağ tık menüsü, Shift+sol tuş
huzurları... hepsi terminale kalır). ?1007 (alternate scroll) sayesinde
alternate screen'deyken fare tekerleği yukarı/aşağı ok tuşlarına çevrilir;
Page bu tuşları sohbet kaydırmasına bağlar.
"""

from __future__ import annotations

import os
import select


def read_key(fd: int = 0) -> str:
    """Tek tuş. Özel adlar: enter, shift-enter, ctrl-j, tab, esc, up, down,
    left, right, backspace, delete, home, end,
    ctrl-c, ctrl-d, ctrl-u, ctrl-k, ctrl-a, ctrl-e, ctrl-w.

    Not: tekerlek (?1007 alternate scroll) terminale ok tuşu olarak gelir
    ve yukarıdaki 'up'/'down' adlarıyla döner.
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
    if c == 0x10:
        return "ctrl-p"
    if c == 0x0F:
        return "ctrl-o"
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
        # CSI 5~ / 6~ : PageUp / PageDown (sohbet kaydırmasına bağlanır)
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


def _read_csi_tail(fd: int) -> bytes:
    """CSI dizisinin sonunu (~ veya harf) okuyana dek toplar.

    İlk byte için 50ms beklenir; ESC[ ile tuş arasında parça parça
    gelen dizilerde erken vazgeçilip olayın KAYBOLMAMASI için.
    """
    buf = bytearray()
    first = True
    while True:
        ready, _, _ = select.select([fd], [], [], 0.05 if first else 0.02)
        first = False
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

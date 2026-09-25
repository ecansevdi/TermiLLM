"""Fare seçimini panoya kopyalama (OSC 52).

OSC 52: terminalin kendisine "bu metni panoya kopyala" demek. SSH/uzak
oturumlarda da çalışır; iTerm2, Kitty, Alacritty, WezTerm, tmux (set-clipboard
on) ve Windows Terminal destekler. GNOME Terminal gibi desteklemeyen
terminallerde sessizce geçilir — kullanıcı yine de terminalin kendi seçim
kopyalamasını kullanabilir.
"""

from __future__ import annotations

import base64
import sys


def copy_selection(text: str) -> bool:
    """Seçili metni OSC 52 ile panoya gönder. Başarı: True."""
    if not text:
        return False
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    try:
        out = sys.__stdout__ or sys.stdout
        out.write(f"\033]52;c;{payload}\033\\")
        out.flush()
        return True
    except Exception:
        return False

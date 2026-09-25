"""Mesaj saatleri: internet varsa bölgesel saat, yoksa bilgisayar saati.

Uygulama açılışında arka planda internete bakılır (warmup):

  1) worldtimeapi.org/api/ip   — istemcinin IP'sine göre bölgesel saat
  2) bir sunucunun HTTP Date başlığı (GMT) + yerel saat dilimi düzeltmesi
  3) hiçbiri yoksa bilgisayar saati

Bulunan fark (internet saati − bilgisayar saati) önbelleğe alınır; mesaj
basarken ağ beklenmez ve 10 dakikada bir arka planda tazelenir.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

_REFRESH_INTERVAL = 600  # sn

_state_lock = threading.Lock()
_offset_seconds = 0.0
_source = "bilgisayar"
_started = False


def now_str() -> str:
    """Mesaj damgası: düzeltilmiş yerel saat (HH:MM)."""
    dt = datetime.now() + timedelta(seconds=_offset_seconds)
    return dt.strftime("%H:%M")


def source() -> str:
    """Aktif saat kaynağı: 'internet' | 'sunucu' | 'bilgisayar'."""
    return _source


def warmup():
    """Arka planda saat kaynağını keşfet ve periyodik tazele."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True).start()


def _loop():
    while True:
        _refresh()
        time.sleep(_REFRESH_INTERVAL)


def _refresh():
    off, src = _fetch_worldtime()
    if off is None:
        off, src = _fetch_http_date()
    if off is not None:
        global _offset_seconds
        with _state_lock:
            global _source
            _offset_seconds = off
            _source = src


def _fetch_worldtime():
    """IP'ye göre bölgesel saat (worldtimeapi). Hata: (None, None)."""
    try:
        import json
        import urllib.request

        with urllib.request.urlopen(
            "http://worldtimeapi.org/api/ip", timeout=3
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        dt = datetime.fromisoformat(data["datetime"])
        if dt.tzinfo is None:
            return None, None
        off = (
            dt.astimezone(timezone.utc) - datetime.now(timezone.utc)
        ).total_seconds()
        return off, "internet"
    except Exception:
        return None, None


def _fetch_http_date():
    """HTTP Date başlığından GMT saati; yerel saat dilimiyle gösterilir."""
    try:
        import urllib.request
        from email.utils import parsedate_to_datetime

        req = urllib.request.Request("https://www.google.com", method="HEAD")
        with urllib.request.urlopen(req, timeout=3) as resp:
            date_hdr = resp.headers.get("Date")
        if not date_hdr:
            return None, None
        server_utc = parsedate_to_datetime(date_hdr).astimezone(timezone.utc)
        off = (server_utc - datetime.now(timezone.utc)).total_seconds()
        return off, "sunucu"
    except Exception:
        return None, None

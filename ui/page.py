"""Alternatif ekran: "yeni sayfa" görünümü.

Sayfa açılınca alternate screen buffer'a geçilir; ana ekran korunur ve
çıkışta birebir geri yüklenir. Sayfa düzeni:

  üst çubuk        : sabit 1 satır — en sağda context çubuğu (beyaz bar +
                     yüzde) ve toplam context size
  içerik penceresi : aradaki satırlar; klasik terminal akışı — yazıldıkça
                     alta eklenir, dolunca en üst satır yukarı kayar
  giriş kutusu     : en altta sabit; koyu gri zemin, beyaz çizgiler

Yönlendirme: enter() sırasında sys.stdout, _PageWriter ile değiştirilir.
Böylece kodun herhangi bir yerindeki print() çıktısı otomatik olarak siyah
sayfaya düşer; leave()/suspend() gerçek stdout'u geri koyar. Sayfanın KENDİ
çizimleri ise daima _real_stdout üzerinden yapılır (iç ANSI dizileri içerik
sanılmasın diye).

Giriş modu: setcbreak — echo/canonical kapalı; OPOST (\\n → CRLF) ve ISIG
(Ctrl+C → SIGINT) açık kalır. Böylece print("\n") bozulmaz ve CancelWatch
çalışmaya devam eder.

Satır modeli:
  * feed_print(): gelen akışı \\n'e göre satırlara böler; tamamlanan her satır
    _seen'e (statik) eklenir.
  * Tamamlanmamış satır (end="" yazımlar) pencerenin son satırında canlı
    gösterilir.
  * _draw_window(): görünen son satırları ÜSTTEN hizalı şekilde absolu
    konumla yeniden çizer (klasik terminal akışı); balonlar (kind=2) koyu
    gri zeminli çizilir.
"""

from __future__ import annotations

import re
import select
import shutil
import sys
import threading
import time

from ui import clock
from ui.completer import token_at_cursor
from ui.keys import read_key
from ui.terminal import (
    BG_BLACK, BG_GRAY, BOLD, BOLD_RESET, DIM, FG_WHITE, LINE_BALLOON,
    LINE_BALLOON_STAMP, LINE_PLAIN, LINE_RIGHT_STAMP, RESET,
)

_ANSI_RE = re.compile(r"\033\[[0-9;]*[A-Za-z]")
_SGR_RE = re.compile(r"\033\[([0-9;]*)m")

_DRAW_INTERVAL = 0.03  # canlı akışta yeniden çizim kısığı (sn)
_MAX_HISTORY = 5000    # geçmiş tamponu sınırı (satır)
_SCROLL_STEP = 3       # tekerlek/ok tuşu adımı (satır)

# Canonical reasoning effort seviyeleri (llm/reasoning.py ile aynı küme)
# "auto" provider'a gitmez; state'te None olarak durur.
_EFFORT_LEVELS = ["auto", "none", "minimal", "low", "medium", "high", "xhigh", "max"]
EFFORT_LEVELS = _EFFORT_LEVELS     # dış kullanım


def visible_width(s: str) -> int:
    """ANSI kaçış dizilerini saymadan satır genişliği."""
    return len(_ANSI_RE.sub("", s))


def _sgr_state(text: str) -> list[str]:
    """Metnin sonuna kadar aktif olan SGR parametrelerini döndürür."""
    params: list[str] = []
    for m in _SGR_RE.finditer(text):
        p = m.group(1)
        if p in ("", "0"):
            params = []
        else:
            params.extend(c for c in p.split(";") if c)
    return params


def wrap_ansi(line: str, width: int) -> list[str]:
    """Uzun satırı ekran genişliğine göre alt satırlara böler.

    ANSI dizileri bozulmaz; bölünen satırın devamı, o noktadaki renk/zemin
    durumunu yeniden yayınlayarak başlar (kod bloğu gri zemini korunur).
    """
    if width <= 0 or visible_width(line) <= width:
        return [line]
    rows = []
    cur = ""
    w = 0
    i = 0
    n = len(line)
    while i < n:
        m = _ANSI_RE.match(line, i)
        if m:
            cur += m.group(0)
            i = m.end()
            continue
        if w >= width:
            state = _sgr_state(cur)
            rows.append(cur)
            cur = f"\033[{';'.join(state)}m" if state else ""
            w = 0
        cur += line[i]
        w += 1
        i += 1
    if cur:
        rows.append(cur)
    return rows


class _PageWriter:
    """sys.stdout yerine geçen yazıcı; her şeyi sayfaya aktarır."""

    def __init__(self, page: "Page"):
        self.page = page
        self.encoding = "utf-8"
        self.errors = "replace"
        self.name = "<page>"
        self.closed = False
        self.buffer = None

    def write(self, s: str) -> int:
        try:
            self.page.feed_print(s)
        except Exception:
            pass
        return len(s)

    def writelines(self, lines):
        for ln in lines:
            self.write(ln)

    def flush(self):
        try:
            self.page.flush_print()
        except Exception:
            pass

    def isatty(self) -> bool:
        return True

    def writable(self) -> bool:
        return True

    def fileno(self) -> int:
        fd = self.page._fd
        return fd if fd else 1


class Page:
    """Ana REPL'in üstünde açılan siyah 'yeni sayfa' katmanı."""

    # satır türleri (ui/terminal.py sabitleri)
    PLAIN = LINE_PLAIN
    BALLOON = LINE_BALLOON
    BALLOON_STAMP = LINE_BALLOON_STAMP
    RIGHT_STAMP = LINE_RIGHT_STAMP

    def __init__(self, title: str = "TermiLLM"):
        self.title = title
        self.active = False
        self._fd = None
        self._old_term = None
        self._real_stdout = None

        self._rows = 24
        self._cols = 80

        self._input_height = 5          # çerçeve + üst/alt boşluk dahil
        self._max_input_height = 16
        self._min_input_height = 5

        self._edit_lines: list[str] = [""]
        self._cursor_line = 0
        self._cursor_col = 0
        self._view_top = 0

        # Reasoning efor. None = auto (explicit override yok).
        self._effort = None
        self._effort_cb = None          # seçim yapıldığında çağrılır
        self._hint_row = None           # efor ipucu satırı (ekran satırı)
        self._effort_note = ""          # 'istenen → gönderilen' açıklaması
        self._menu_cb = None            # Ctrl+O: provider menüsü (application köprüsü)

        # İçerik penceresinde TÜM oturum geçmişi: (metin, kind)
        self._seen: list[tuple[str, int]] = []
        self._print_buf = ""          # tamamlanmamış (canlı) satır
        self._last_draw = 0.0
        self._scroll_offset = 0       # tekerlek/ok tuşu ile geçmişe bakış

        self._keep_top: list[str] = []
        self._keep_bottom: list[str] = []
        self._keep_rows_top = 0
        self._keep_rows_bottom = 0

        # Üst çubuk verileri
        self._ctx_used = 0
        self._ctx_total = 0

    # ------------------------------------------------------------------ #
    # Aç / kapat
    # ------------------------------------------------------------------ #

    def enter(self):
        if self.active:
            return
        import termios
        import tty

        try:
            if not sys.stdout.isatty():
                return
        except (AttributeError, ValueError):
            return

        self._real_stdout = sys.stdout
        try:
            self._fd = sys.stdout.fileno()
        except (AttributeError, ValueError):
            self._fd = None

        if self._fd is not None and sys.stdin.isatty():
            try:
                self._old_term = termios.tcgetattr(self._fd)
                tty.setcbreak(self._fd)
                # Enter CR (0x0D) olarak gelsin; Ctrl+J LF (0x0A) kalır.
                # OPOST/ONLCR (\n → CRLF) ve ISIG (Ctrl+C) açık kalır.
                attrs = termios.tcgetattr(self._fd)
                attrs[0] &= ~(termios.ICRNL | termios.INLCR)
                termios.tcsetattr(self._fd, termios.TCSANOW, attrs)
            except termios.error:
                self._old_term = None

        self.active = True
        sys.stdout = _PageWriter(self)
        self._read_size()

        out = self._real_stdout
        out.write("\0337")                 # DECSC: imleci kaydet
        out.write("\033[?1049h")           # alternate screen buffer
        # Mouse tracking AÇILMAZ: ?1000/?1002/?1003 terminallerin NATİVE
        # seçimini ezmiştir (fare olayları uygulamaya yönlenir). Onun yerine
        # ?1007 (alternate scroll): tekerlek alt-ekranda ok tuşlarına
        # çevrilir → scroll çalışır, seçim terminalin kendisinde kalır.
        out.write("\033[?1007h")
        out.write(f"{BG_BLACK}{FG_WHITE}")
        out.write("\033[2J")               # ekranı sil
        out.write("\033[H")                # home
        out.flush()

        self._draw_window(force=True)
        self._paint_all()

    def leave(self):
        if not self.active:
            return
        import termios

        self.active = False
        real = self._real_stdout or sys.stdout
        if isinstance(real, _PageWriter):
            real = sys.__stdout__
        sys.stdout = real

        real.write(f"{RESET}")
        real.write("\033[?1007l")           # alternate scroll kapat
        real.write("\033[?1049l")          # ana ekrana dön
        real.write("\0338")                # DECRC: imleci geri yükle
        real.flush()

        if self._old_term is not None and self._fd is not None:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_term)
            except termios.error:
                pass
        self._old_term = None
        self._real_stdout = None

    # ------------------------------------------------------------------ #
    # Düzen / yeniden çizim
    # ------------------------------------------------------------------ #

    def _read_size(self):
        size = shutil.get_terminal_size((80, 24))
        self._cols, self._rows = size.columns, size.lines

    def _window_height(self) -> int:
        return max(0, self._rows - self._keep_rows_top - self._keep_rows_bottom)

    def _paint_all(self):
        """Tüm sabitleri (üst çubuk + giriş kutusu) çizer.

        Üst çubuğun altındaki TÜM satırlar önce temizlenir: kutu yüksekliği
        değişince eski kutunun üstte kalan satırları hayalet kalıntı olarak
        kalmasın. Ardından içerik penceresi ve kutu içeriği yeniden çizilir.
        """
        self._build_top_bar()
        self._build_input_box()
        out = self._real_stdout
        out.write("\0337")
        for row in range(self._keep_rows_top + 1, self._rows + 1):
            out.write(f"\033[{row};1H\033[2K")
        for i, ln in enumerate(self._keep_top):
            out.write(f"\033[{i + 1};1H{ln}")
        start = self._rows - len(self._keep_bottom) + 1
        for i, ln in enumerate(self._keep_bottom):
            out.write(f"\033[{start + i};1H{ln}")
        out.write("\0338")
        out.flush()
        self._draw_window(force=True)
        self.draw_input()

    def resize(self):
        if self.active:
            self._read_size()
            self._paint_all()
            self._draw_window(force=True)
            self.draw_input()

    def _build_top_bar(self):
        """En sağda: yüzde + beyaz bar + harcanan / context size."""
        used, total = self._ctx_used, self._ctx_total
        ratio = (used / total) if total else 0.0
        pct = int(round(ratio * 100))
        pct_text = f"%{pct}"
        bar_width = 20
        filled = int(round(bar_width * ratio))
        # Beyaz bar: dolu bloklar beyaz, boş kısım siyah zeminde çizgi
        bar = ("█" * filled) + ("─" * (bar_width - filled))
        used_str = f"{used:,}".replace(",", ".")
        total_str = f"{total:,}".replace(",", ".") if total else "—"
        right = f"{pct_text} {bar} {used_str} / {total_str} "
        pad = max(0, self._cols - visible_width(right))
        self._keep_top = [
            f"{' ' * pad}{FG_WHITE}{pct_text} {bar} "
            f"{used_str} / {total_str}{RESET}{BG_BLACK}"
        ]
        self._keep_rows_top = len(self._keep_top)

    def _build_input_box(self):
        h = self._input_height
        cols = self._cols
        top = "┌" + "─" * (cols - 2) + "┐"
        blank = "│" + " " * (cols - 2) + "│"
        bottom = "└" + "─" * (cols - 2) + "┘"
        lines = [top] + [blank] * (h - 2) + [bottom]
        # Gri zemin, beyaz çizgiler
        self._keep_bottom = [
            f"{BG_GRAY}{FG_WHITE}{ln}{RESET}{BG_BLACK}" for ln in lines
        ]
        # Efor ipucu satırı: kutunun HEMEN üstünde (ekran satırı=h)
        # üst çubukla kutu arasına yerleşir; _paint_all burayı da siler/çizer.
        top_row = self._rows - h + 1 - 1              # kutu üst çizgisinin üstü
        hint_text = f" {FG_WHITE}{BOLD}{self._effort_hint()}{BOLD_RESET}"
        pad = max(0, cols - visible_width(hint_text) - 1)
        self._hint_row = top_row
        self._keep_bottom.append(f"{' ' * pad}{hint_text}")
        self._keep_rows_bottom = len(self._keep_bottom)

    def _set_input_height(self, h: int):
        h = max(self._min_input_height, min(self._max_input_height, h))
        if h == self._input_height:
            return
        self._input_height = h
        self._paint_all()

    def _sync_input_height(self):
        # +4: çerçeve (2) + üst/alt iç boşluk (1+1)
        want = max(self._min_input_height, len(self._edit_lines) + 4)
        self._set_input_height(want)

    # ------------------------------------------------------------------ #
    # Üst çubuk göstergeleri
    # ------------------------------------------------------------------ #

    def set_metrics(self, tok_rate: str = None, ctx_used=None, ctx_total=None):
        changed = False
        if ctx_used is not None:
            self._ctx_used = int(ctx_used)
            changed = True
        if ctx_total is not None:
            self._ctx_total = int(ctx_total)
            changed = True
        if not changed:
            return
        self._build_top_bar()
        self._paint_top()

    def _paint_top(self):
        if not self.active:
            return
        out = self._real_stdout
        out.write(f"\0337\033[1;1H{self._keep_top[0]}\0338")
        out.flush()

    # ------------------------------------------------------------------ #
    # stdout yönlendirme: satır akışı
    # ------------------------------------------------------------------ #

    def feed_print(self, s: str):
        """sys.stdout.write akışını satırlara böler; tamamlananlar statik.

        Ekrana sığmayan satırlar alt satırlara sarılır (ANSI durumu taşınarak).
        """
        if not self.active or not s:
            return
        self._print_buf += s
        committed = False
        while "\n" in self._print_buf:
            line, self._print_buf = self._print_buf.split("\n", 1)
            line = line.rstrip("\r")
            for piece in wrap_ansi(line, self._cols):
                self._seen.append((piece, self.PLAIN))
            committed = True
        self._trim_seen()
        if self._scroll_offset > 0:
            return  # kullanıcı geçmişe bakıyor; görünüm dondurulur
        if committed:
            self._draw_window()
        else:
            self._draw_window(throttle=True)

    def flush_print(self):
        """Tamamlanmamış satır dahil pencereyi hemen çiz."""
        if not self.active:
            return
        self._draw_window()

    def stream_text(self, text: str):
        """Geriye dönük uyumluluk: canlı metin akışı."""
        self.feed_print(text)

    def stream_end(self):
        self.flush_print()

    # ------------------------------------------------------------------ #
    # İçerik penceresi çizimi
    # ------------------------------------------------------------------ #

    def _row_text(self, ln: str, kind: int) -> str:
        """Satırın görünür metnini (dolgu dahil, tam genişlik) üretir.

        Balonlar tam genişlik tek parça gri kutudur; damga satırında saat
        AYNI gri zeminin sağ kenarında durur (ardında siyah kalmaz):
        "|  metin ...... saat  |"
        """
        cols = self._cols
        if kind in (self.BALLOON, self.BALLOON_STAMP):
            if kind == self.BALLOON_STAMP:
                body_txt, _, stamp = ln.partition("\x00")
                bw = max(1, cols - 8)          # 1 boşluk + gövde + boşluk + 5 saat + 1
                body = self._clip(body_txt, bw)
                pad = " " * max(0, bw - visible_width(body))
                return f" {body}{pad} {stamp} "
            bw = max(1, cols - 3)
            body = self._clip(ln, bw)
            pad = " " * max(0, bw - visible_width(body))
            return f" {body}{pad}  "
        if kind == self.RIGHT_STAMP:
            body_txt, _, stamp = ln.partition("\x00")
            bw = max(1, cols - 6)
            body = self._clip(body_txt, bw)
            pad = " " * max(0, bw - visible_width(body))
            return f"{body}{pad}{stamp} "
        text = self._clip(ln, cols)
        return text + " " * max(0, cols - visible_width(text))

    def _render_row(self, ln: str, kind: int) -> str:
        """Satırı hücre düzenine çevirir."""
        text = self._row_text(ln, kind)
        if kind in (self.BALLOON, self.BALLOON_STAMP):
            return f"{BG_GRAY}{FG_WHITE}{text}{RESET}{BG_BLACK}"
        return f"{BG_BLACK}{FG_WHITE}{text}{RESET}{BG_BLACK}"

    def _draw_window(self, throttle: bool = False, force: bool = False):
        """Görünen satırları ÜSTTEN hizalı şekilde absolu konumla çizer.

        Mouse wheel ile geçmişe bakılıyorsa (_scroll_offset > 0) görünüm
        geçmişin ilgili dilimini gösterir; canlı satır yalnızca en altta
        (offset=0) iken çizilir.
        """
        if not self.active:
            return
        now = time.monotonic()
        if not force and throttle and now - self._last_draw < _DRAW_INTERVAL:
            return
        self._last_draw = now

        top = self._keep_rows_top + 1
        bottom = self._rows - self._keep_rows_bottom
        cols = self._cols
        win = max(0, bottom - top + 1)
        if win <= 0:
            return

        live = (self._print_buf
                if (self._print_buf and self._scroll_offset == 0) else None)
        avail = win - (1 if live else 0)
        end = len(self._seen) - self._scroll_offset
        start = max(0, end - avail)
        view = self._seen[start:end]

        out = self._real_stdout
        out.write("\0337")
        for row in range(top, bottom + 1):       # pencereyi sil
            out.write(f"\033[{row};1H\033[2K")
        for i, (ln, kind) in enumerate(view):
            row = top + i
            rendered = self._render_row(ln, kind)
            out.write(f"\033[{row};1H{rendered}\033[K")
        if live:
            row = top + len(view)
            out.write(
                f"\033[{row};1H{BG_BLACK}{self._clip(live, self._cols)}"
                f"{RESET}{BG_BLACK}\033[K"
            )
        if self._scroll_offset > 0:
            hint = f"↑{self._scroll_offset} "
            out.write(
                f"\033[{top};{max(1, self._cols - len(hint) + 1)}H"
                f"\033[2m{hint}{RESET}{BG_BLACK}"
            )
        out.write("\0338")
        out.flush()

    def scroll_up(self, n: int = _SCROLL_STEP):
        """Mouse wheel yukarı: geçmişe bak."""
        win = self._window_height()
        offset_max = max(0, len(self._seen) - win)
        self._scroll_offset = min(self._scroll_offset + n, offset_max)
        self._draw_window(force=True)

    def scroll_down(self, n: int = _SCROLL_STEP):
        """Mouse wheel aşağı: canlı görünüme dön."""
        self._scroll_offset = max(0, self._scroll_offset - n)
        self._draw_window(force=True)

    def _trim_seen(self):
        """Geçmiş tamponunu sınırla; kaydırma ofsetini kaydırmayla eşle."""
        if len(self._seen) > _MAX_HISTORY:
            delta = len(self._seen) - _MAX_HISTORY
            self._seen = self._seen[delta:]
            self._scroll_offset = max(0, self._scroll_offset - delta)

    def queue_line(self, line: str, kind: int = 1):
        """Doğrudan içerik penceresine statik satır ekle (pipe vb.)."""
        self._seen.append((line, kind))
        self._trim_seen()
        if self._scroll_offset > 0:
            return  # geçmişe bakışta görünüm dondurulur
        self._draw_window()

    def stamp_last_line(self, stamp: str, kind: int):
        """Son basılan düz satıra sağa yaslı saat hücresi ekler."""
        if not self._seen:
            return
        line, cur_kind = self._seen[-1]
        if cur_kind != self.PLAIN or "\x00" in line:
            return
        self._seen[-1] = (f"{line}\x00{stamp}", kind)
        self._draw_window(force=True)

    def clear_content(self):
        """İçerik penceresini temizle (/clear)."""
        self._seen.clear()
        self._print_buf = ""
        self._scroll_offset = 0
        self._draw_window(force=True)

    # ------------------------------------------------------------------ #
    # Overlay: komut/yardım çıktısı; tuşta kaybolur
    # ------------------------------------------------------------------ #

    def show_overlay(self, text: str):
        if not self.active:
            out = self._real_stdout or sys.stdout
            out.write(text + "\n")
            out.flush()
            return
        lines = text.split("\n")
        win = self._window_height() or 10
        pages = [lines[i:i + win] for i in range(0, len(lines), win)] or [[]]
        idx = 0
        import termios
        import tty
        fd = self._fd or 0
        old = None
        try:
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        except termios.error:
            old = None
        try:
            while True:
                self._overlay_lines(pages[idx], page_hint=(
                    f"── {idx + 1}/{len(pages)} ── tuş: devam · çıkış"
                    if len(pages) > 1 else ""
                ))
                # Tuş bekle: zaman doldu diye KAPANMAZ (açılışta otomatik
                # kapanma hatasıydı); yalnızca tuş olayı döngüyü ilerletir.
                key = read_key(fd)
                if key in ("down", " ", "enter", "tab", "j") and idx < len(pages) - 1:
                    idx += 1
                    continue
                break
        finally:
            if old is not None:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                except termios.error:
                    pass
        self._draw_window(force=True)

    def clear_content_window(self):
        """İçerik penceresini (üst çubuk ile giriş kutusu arasını) temizler.

        Menü/overlay ekranları tek-ekran ilkesiyle çalışır: yeni ekran
        çizilmeden önce eski içerik kaybolur; çıkışta _draw_window içeriği
        geri boyar.
        """
        if not self.active:
            return
        out = self._real_stdout
        top = self._keep_rows_top + 1
        bottom = self._rows - self._keep_rows_bottom
        out.write("\0337")
        for r in range(top, bottom + 1):
            out.write(f"\033[{r};1H\033[2K")
        out.write("\0338")
        out.flush()

    def _overlay_lines(self, lines: list[str], page_hint: str = ""):
        if not lines:
            return
        out = self._real_stdout
        bottom = self._rows - self._keep_rows_bottom
        start = max(self._keep_rows_top + 1, bottom - len(lines) + 1)
        out.write("\0337")
        for i, ln in enumerate(lines):
            out.write(
                f"\033[{start + i};1H\033[2K{BG_BLACK}{ln}{RESET}{BG_BLACK}\033[K"
            )
        if page_hint:
            row = self._keep_rows_top + 1
            out.write(
                f"\033[{row};1H\033[2K{BG_GRAY}{FG_WHITE}{page_hint}{RESET}{BG_BLACK}"
            )
        out.write("\0338")
        out.flush()

    # ------------------------------------------------------------------ #
    # Kullanıcı balonu
    # ------------------------------------------------------------------ #

    @staticmethod
    def _wrap(text: str, width: int) -> list[str]:
        """Metni kelime sınırlarında verilen genişliğe sarar."""
        out = []
        for raw in (text or "").split("\n"):
            words = raw.split()
            if not words:
                out.append("")
                continue
            cur = words[0]
            for w in words[1:]:
                if visible_width(cur) + 1 + visible_width(w) <= width:
                    cur += " " + w
                else:
                    out.append(cur)
                    cur = w
            out.append(cur)
        return out or [""]

    def show_user_message(self, text: str):
        """Kullanıcı mesajını tam genişlik gri kutuda, sağda saatle basar.

        Kutu üstten/alttan birer GİRİ boşluk satırıyla geniştir (boş satırlar
        da kutunun parçası); uzun satırlar kelime sınırlarında sarılır; son
        satır BALLOON_STAMP türündedir: sağ kenarda saat hücresi taşır.
        """
        now = clock.now_str()   # mesajın GİRİLDİĞİ andeki saat
        width = max(8, self._cols - 11)
        body = self._wrap(text or "", max(4, width - 2))
        if not body:
            body = [">"]
        else:
            body[0] = "> " + body[0] if body[0] else ">"
        self.queue_line("", self.BALLOON)             # üst iç boşluk (gri)
        for i, ln in enumerate(body):
            if i == len(body) - 1:
                self.queue_line(f"{ln}\x00{now}", self.BALLOON_STAMP)
            else:
                self.queue_line(ln, self.BALLOON)
        self.queue_line("", self.BALLOON)             # alt iç boşluk (gri)

    # ------------------------------------------------------------------ #
    # Giriş kutusu editörü
    # ------------------------------------------------------------------ #

    def draw_input(self):
        """Giriş kutusunu çizer: metin ortada, her tarafta boşluk var.

        Yatay: çerçeveden 2 sütun içeri; Dikey: üst/alt en az 1 boş satır,
        kalan boşluk üste/alta eşit dağıtılarak metin bloğu ortalanır.
        """
        if not self.active:
            return
        cols = self._cols
        inner = max(1, cols - 4)          # solda/sağda 2 boşluk
        h = self._input_height
        inner_rows = max(1, h - 2)
        cap = max(1, h - 4)               # en az 1 boş satır üstte/altta
        content = self._edit_lines[self._view_top:self._view_top + cap]

        pad_rows = max(1, (inner_rows - len(content)) // 2)
        while pad_rows + len(content) > inner_rows:
            pad_rows -= 1

        out = self._real_stdout
        out.write("\0337")
        gray = f"{BG_GRAY}{FG_WHITE}"
        box_top_row = self._rows - h + 1
        for i in range(inner_rows):       # iç satırları baştan boya
            row = box_top_row + 1 + i
            j = i - pad_rows
            if 0 <= j < len(content):
                shown = self._clip(content[j], inner)
                pad = " " * max(0, inner - visible_width(shown))
                out.write(f"\033[{row};4H{gray}{shown}{pad}{RESET}{BG_BLACK}")
            else:
                out.write(
                    f"\033[{row};2H{gray}{' ' * (cols - 2)}{RESET}{BG_BLACK}"
                )
        crow = box_top_row + 1 + pad_rows + (self._cursor_line - self._view_top)
        ccol = 4 + self._cursor_col
        out.write("\0338")
        # İmleci restore'dan SONRA koy: kutuda kalır (üst çubuğa kaçmaz)
        out.write(f"\033[{crow};{ccol}H")
        out.flush()

    def _effort_hint(self) -> str:
        """Efor: auto | Efor: high | Efor: xhigh → high | Efor: high → unsupported.

        Auto iken sağlayıcının varsayılan seviyesi tahmin edilmez.
        """
        if not self._effort:
            return "Efor: auto"
        note = self._effort_note or ""
        if "unsupported" in note.lower():
            return f"Efor: {self._effort} → unsupported"
        match = re.search(r"\b([a-z]+)\s*→\s*([a-z]+)\b", note)
        if match:
            return f"Efor: {match.group(1)} → {match.group(2)}"
        return f"Efor: {self._effort}"

    def set_effort(self, level: str):
        """Efor göstergesini günceller. None/auto = explicit override yok."""
        if level in (None, "", "auto"):
            if self._effort is None:
                return
            self._effort = None
            if self.active:
                self._paint_all()
            return
        if level not in _EFFORT_LEVELS or level == "auto" or level == self._effort:
            return
        self._effort = level
        if self.active:
            self._paint_all()

    def set_effort_note(self, note: str):
        """'istenen → gönderilen' açıklamasını günceller (tur sonrası)."""
        note = (note or "").strip()
        if note == self._effort_note:
            return
        self._effort_note = note
        if self.active:
            self._paint_all()

    def set_effort_callback(self, fn):
        """Ctrl+P ile efor seçildiğinde çağrılır (page → state köprüsü)."""
        self._effort_cb = fn

    def set_menu_callback(self, fn):
        """Ctrl+O ile çağrılacak provider menüsü köprüsü."""
        self._menu_cb = fn

    def get_effort(self) -> str:
        return self._effort

    def _pick_effort(self):
        """Ctrl+P seçim overlay'i: ok tuşlarıyla gez, Enter onayla, Esc iptal."""
        import termios
        import tty
        fd = self._fd or 0
        old = None
        try:
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        except termios.error:
            old = None
        # None menüde auto satırıdır. Enter'a basılmadan state değişmez.
        if self._effort in _EFFORT_LEVELS:
            idx = _EFFORT_LEVELS.index(self._effort)
        else:
            idx = 0
        top = self._keep_rows_top + 1
        try:
            # Tek-ekran ilkesi: efor listesi açılmadan önceki içerik temizlenir
            self.clear_content_window()
            while True:
                rows = ["Efor seviyesi seç (canonical):"]
                for i, it in enumerate(_EFFORT_LEVELS):
                    mark = "●" if i == idx else "○"
                    if i == idx:
                        rows.append(f"  {mark} {FG_WHITE}{BOLD}{it}{BOLD_RESET}")
                    else:
                        rows.append(f"  {mark} {DIM}{it}{RESET}{BG_BLACK}")
                rows.append("")
                rows.append(f"{DIM}↑↓ gez · enter onayla · esc vazgeç{RESET}{BG_BLACK}")
                self._overlay_lines(rows, page_hint="")
                ready, _, _ = select.select([fd], [], [], 0.05)
                if not ready:
                    continue
                key = read_key(fd)
                if key == "up":
                    idx = (idx - 1) % len(_EFFORT_LEVELS)
                elif key == "down":
                    idx = (idx + 1) % len(_EFFORT_LEVELS)
                elif key == "enter":
                    break
                elif key in ("esc", "ctrl-c"):
                    self._draw_window(force=True)
                    self.draw_input()
                    return
            level = _EFFORT_LEVELS[idx]
        finally:
            if old is not None:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                except termios.error:
                    pass
        # "auto" provider alanı değildir; state'te None kalır.
        chosen = None if level == "auto" else level
        if chosen != self._effort:
            self.set_effort(chosen)
        if self._effort_cb:
            try:
                self._effort_cb(chosen)
            except Exception:
                pass
        self._draw_window(force=True)
        self.draw_input()

    def _clip(self, line: str, width: int) -> str:
        if visible_width(line) <= width:
            return line
        out = ""
        w = 0
        i = 0
        while i < len(line):
            m = _ANSI_RE.match(line, i)
            if m:
                out += m.group(0)
                i = m.end()
                continue
            out += line[i]
            w += 1
            i += 1
            if w >= width:
                break
        return out

    def get_input(self, poll_prefill=None) -> str:
        """Kutuda çok satırlı girdi oku.

        Enter gönderir; Shift+Enter (veya Ctrl+J) yeni satır.
        Ctrl+C KeyboardInterrupt (SIGINT), boşken Ctrl+D EOFError fırlatır.
        """
        import select

        if not sys.stdin.isatty():
            line = sys.stdin.readline()
            if line == "":
                raise EOFError
            return line.rstrip("\n")

        self._edit_lines = [""]
        self._cursor_line = 0
        self._cursor_col = 0
        self._view_top = 0
        self._sync_input_height()
        self.draw_input()

        fd = sys.stdin.fileno()
        try:
            while True:
                if poll_prefill:
                    extra = poll_prefill()
                    if extra:
                        self._insert_text(extra)
                        self.draw_input()

                ready, _, _ = select.select([fd], [], [], 0.2)
                if not ready:
                    continue
                key = read_key(fd)
                if key in ("shift-enter", "ctrl-j"):
                    self._new_line()
                    self.draw_input()
                elif key == "enter":
                    text = "\n".join(self._edit_lines)
                    self._reset_edit()
                    return text
                elif key == "ctrl-d":
                    if self._edit_lines == [""]:
                        raise EOFError
                elif key in ("up", "down") and len(self._edit_lines) == 1 and not self._edit_lines[0]:
                    # Boş girdi: ok tuşları (ve ?1007 alternate scroll'un
                    # tekerleği) sohbeti kaydırır; yazarken metin gezinir.
                    if key == "up":
                        self.scroll_up()
                    else:
                        self.scroll_down()
                elif key == "left":
                    if self._cursor_col > 0:
                        self._cursor_col -= 1
                    elif self._cursor_line > 0:
                        self._cursor_line -= 1
                        self._cursor_col = len(self._edit_lines[self._cursor_line])
                    self._scroll_edit_view()
                    self.draw_input()
                elif key == "right":
                    line = self._edit_lines[self._cursor_line]
                    if self._cursor_col < len(line):
                        self._cursor_col += 1
                    elif self._cursor_line < len(self._edit_lines) - 1:
                        self._cursor_line += 1
                        self._cursor_col = 0
                    self._scroll_edit_view()
                    self.draw_input()
                elif key in ("home", "ctrl-a"):
                    self._cursor_col = 0
                    self.draw_input()
                elif key in ("end", "ctrl-e"):
                    self._cursor_col = len(self._edit_lines[self._cursor_line])
                    self.draw_input()
                elif key == "up":
                    if self._cursor_line > 0:
                        self._cursor_line -= 1
                        self._cursor_col = min(
                            self._cursor_col,
                            len(self._edit_lines[self._cursor_line]),
                        )
                        self._scroll_edit_view()
                        self.draw_input()
                elif key == "down":
                    if self._cursor_line < len(self._edit_lines) - 1:
                        self._cursor_line += 1
                        self._cursor_col = min(
                            self._cursor_col,
                            len(self._edit_lines[self._cursor_line]),
                        )
                        self._scroll_edit_view()
                        self.draw_input()
                elif key == "backspace":
                    self._backspace()
                    self.draw_input()
                elif key == "delete":
                    self._delete_key()
                    self.draw_input()
                elif key == "ctrl-u":
                    line = self._edit_lines[self._cursor_line]
                    self._edit_lines[self._cursor_line] = line[self._cursor_col:]
                    self._cursor_col = 0
                    self.draw_input()
                elif key == "ctrl-k":
                    line = self._edit_lines[self._cursor_line]
                    self._edit_lines[self._cursor_line] = line[:self._cursor_col]
                    self.draw_input()
                elif key == "ctrl-w":
                    self._kill_word()
                    self.draw_input()
                elif key == "tab":
                    self._open_picker()
                elif key == "ctrl-p":
                    self._pick_effort()
                    continue
                elif key == "ctrl-o":
                    if self._menu_cb:
                        self._menu_cb()
                    continue
                elif key == "esc":
                    pass
                elif len(key) == 1 and key.isprintable():
                    self._insert_text(key)
                    self._maybe_at_picker()
                    self.draw_input()
        finally:
            self._reset_edit()
            self.draw_input()   # Enter sonrası kutu anında boş görünsün

    def _reset_edit(self):
        self._edit_lines = [""]
        self._cursor_line = 0
        self._cursor_col = 0
        self._view_top = 0
        self._sync_input_height()

    def _maybe_at_picker(self):
        """Az önce yazılan @ token'i tamamsa kutuyu aç."""
        line = self._edit_lines[self._cursor_line]
        _, token = token_at_cursor(list(line), self._cursor_col)
        if token == "@":
            self._open_picker()

    def _open_picker(self):
        from ui.picker import pick_file

        line = self._edit_lines[self._cursor_line]
        start, token = token_at_cursor(list(line), self._cursor_col)
        if not token.startswith("@"):
            return
        chosen = pick_file(token)
        self._draw_window(force=True)
        self.draw_input()
        if not chosen:
            return
        if not chosen.endswith("/"):
            chosen = chosen + " "
        new_line = line[:start] + chosen + line[self._cursor_col:]
        self._edit_lines[self._cursor_line] = new_line
        self._cursor_col = start + len(chosen)
        self._sync_input_height()
        self._scroll_edit_view()
        self.draw_input()

    # --- editör yardımcıları --- #

    def _insert_text(self, text: str):
        parts = text.split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                self._new_line()
            line = self._edit_lines[self._cursor_line]
            line = line[:self._cursor_col] + part + line[self._cursor_col:]
            self._edit_lines[self._cursor_line] = line
            self._cursor_col += len(part)
        self._sync_input_height()
        self._scroll_edit_view()

    def _new_line(self):
        line = self._edit_lines[self._cursor_line]
        before, after = line[:self._cursor_col], line[self._cursor_col:]
        self._edit_lines[self._cursor_line] = before
        self._edit_lines.insert(self._cursor_line + 1, after)
        self._cursor_line += 1
        self._cursor_col = 0
        self._sync_input_height()
        self._scroll_edit_view()

    def _backspace(self):
        if self._cursor_col > 0:
            line = self._edit_lines[self._cursor_line]
            self._edit_lines[self._cursor_line] = (
                line[:self._cursor_col - 1] + line[self._cursor_col:]
            )
            self._cursor_col -= 1
        elif self._cursor_line > 0:
            prev = self._edit_lines[self._cursor_line - 1]
            cur = self._edit_lines.pop(self._cursor_line)
            self._cursor_line -= 1
            self._cursor_col = len(prev)
            self._edit_lines[self._cursor_line] = prev + cur
            self._sync_input_height()
        self._scroll_edit_view()

    def _delete_key(self):
        line = self._edit_lines[self._cursor_line]
        if self._cursor_col < len(line):
            self._edit_lines[self._cursor_line] = (
                line[:self._cursor_col] + line[self._cursor_col + 1:]
            )
        elif self._cursor_line < len(self._edit_lines) - 1:
            nxt = self._edit_lines.pop(self._cursor_line + 1)
            self._edit_lines[self._cursor_line] = line + nxt
            self._sync_input_height()

    def _kill_word(self):
        line = self._edit_lines[self._cursor_line]
        col = self._cursor_col
        while col > 0 and line[col - 1] in " \t":
            col -= 1
        while col > 0 and line[col - 1] not in " \t":
            col -= 1
        self._edit_lines[self._cursor_line] = line[:col] + line[self._cursor_col:]
        self._cursor_col = col

    def _scroll_edit_view(self):
        h = max(1, self._input_height - 4)   # içerik alanı (boşluklar düşülü)
        if self._cursor_line < self._view_top:
            self._view_top = self._cursor_line
        elif self._cursor_line >= self._view_top + h:
            self._view_top = self._cursor_line - h + 1

    # ------------------------------------------------------------------ #
    # Picker (dosya kutusu) ile uyum
    # ------------------------------------------------------------------ #

    def draw_picker(self, lines: list[str]):
        """Giriş kutusunun üstünde picker kutusunu çizer."""
        if not self.active or not lines:
            return
        out = self._real_stdout
        h = self._input_height
        start_row = self._rows - h - len(lines)
        start_row = max(self._keep_rows_top + 1, start_row)
        out.write("\0337")
        for i, ln in enumerate(lines):
            out.write(f"\033[{start_row + i};1H\033[2K{ln}\033[K")
        out.write("\0338")
        out.flush()

    def erase_picker(self, n_lines: int):
        if not self.active or n_lines <= 0:
            return
        out = self._real_stdout
        h = self._input_height
        start_row = self._rows - h - n_lines
        start_row = max(self._keep_rows_top + 1, start_row)
        out.write("\0337")
        for i in range(n_lines):
            out.write(f"\033[{start_row + i};1H\033[2K")
        out.write("\0338")
        out.flush()

    # ------------------------------------------------------------------ #
    # Suspend: /arama gibi input() kullanan akışlar için
    # ------------------------------------------------------------------ #

    def suspend(self):
        """Sayfayı geçici kapat; içeriği KAYDET (iki kez eklenmesin)."""
        saved = list(self._seen)
        self._seen = []
        self._print_buf = ""
        self._scroll_offset = 0
        self.leave()
        return saved

    def resume(self, saved=None):
        self.enter()
        if saved is not None:
            self._seen = list(saved)   # kaydedilenle DEĞİŞTİR (append değil)
            self._trim_seen()
        self._draw_window(force=True)

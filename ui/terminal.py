"""Terminal sunum katmanı ve renk sabitleri.

Sayfa modunda (Page etkin) çıktılar alternatif ekrandaki siyah "yeni sayfa"ya
yönlendirilir; sayfa kapalıyken normal terminale yazılır. RESET her yerde
beyaz üstüne siyahtır; Page RESET sonrası siyah zemini geri uygular.
"""

from __future__ import annotations

import sys

GREEN = '\033[92m'
YELLOW = '\033[93m'
CYAN = '\033[96m'
RED = '\033[91m'
DIM = '\033[2m'
RESET = '\033[0m'
BOLD = '\033[1m'
BOLD_RESET = '\033[22m'

# "Yeni sayfa" temel renkleri: beyaz üstüne siyah
WHITE = '\033[97m'
FG_WHITE = '\033[97m'
BG_BLACK = '\033[40m'
# Kutular için koyu gri (brightness ≈ %22); 256-renk destekli terminallerde
# gerçek koyu gri, desteklemeyenlerde parlak-siyah zemine düşer.
BG_GRAY = '\033[48;5;238m'

_page = None  # Aktif Page; show_* fonksiyonları çıkışları buraya yönlendirir


def set_page(page) -> None:
    """Sayfa katmanını bağla (main.py'de bir kez çağrılır)."""
    global _page
    _page = page


def get_page():
    return _page


def _write(text: str, end: str = "\n"):
    """Sayfa etkinse sayfaya, değilse stdout'a yaz."""
    if _page is not None and _page.active:
        _page.stream_text(text + end)
    else:
        sys.stdout.write(text + end)
        sys.stdout.flush()


class TerminalUI:
    """Terminal sunum katmanı."""

    def __init__(self):
        pass

    def prompt(self, poll_prefill=None) -> str:
        from ui.line_edit import read_line
        return read_line(poll_prefill=poll_prefill).strip()

    def show_context_fallback_warning(self, fallback: int):
        _write(f"{YELLOW}⚠ Context size sağlayıcıdan alınamadı; varsayılan "
              f"{fallback} token kullanılıyor.{RESET}")

    def show_startup(self, title: str, session_id: str, max_context: int,
                     pipe_path: str):
        page = get_page()
        if page is not None and page.active:
            return  # üst çubukta gösterilecek; sayfada yazı yok
        print(f"\n🤖 {CYAN}Yapay Zeka Ajanı{RESET}")
        print(f"{DIM}   Aktif sohbet : {title}{RESET}")
        print(f"{DIM}   Session      : {session_id}{RESET}")
        print(f"{DIM}   Max context  : {max_context:,} token")
        print(f"   Güvenlik payı: {int(max_context * 0.85):,} token")
        print(f"   Whisper pipe : {pipe_path}")
        print(f"   {RESET}{DIM}Dosya {GREEN}@yol{RESET}{DIM}  ·  arama {GREEN}?\"sorgu\"{RESET}{DIM}  ·  kes {GREEN}Ctrl+X{RESET}{DIM}  ·  /help{RESET}\n")

    def show_context_bar(self, used: int, maximum: int):
        """Üst çubuğa context göstergesini yansıtır (sayfa modunda)."""
        page = get_page()
        if page is not None and page.active:
            page.set_metrics(ctx_used=used, ctx_total=maximum)

    def show_attachment_count(self, count: int):
        _write(f"{DIM}📎 {count} ek bellekte bekliyor. Sorunuzu yazın veya Enter ile gönderin.{RESET}")

    def show_token_stats(self, input_tok: int, output_tok: int, elapsed: float,
                         estimated: bool = False):
        """Cevabın hemen altına ortalama hız satırını basar.

        Sayfa modunda ↳ ...│ X tok/s (server) satırı akışa eklenir; düz
        modda klasik çok Alanlı satır olarak basılır.
        """
        tilde = "~" if estimated else ""
        src = "(tahmini)" if estimated else "(server)"
        rate_full = f"{output_tok / elapsed:.1f} tok/s" if elapsed > 0 else "— tok/s"
        line = (
            f"{DIM}↳ {tilde}giriş: {input_tok:,} tok │ "
            f"çıkış: {output_tok:,} tok │ "
            f"toplam: {input_tok + output_tok:,} tok │ "
            f"{RESET}{GREEN}{rate_full}{RESET} "
            f"{DIM}{src}{RESET}"
        )
        _write(line)
        _write("")

    def show_session_list(self, entries: list):
        page = get_page()
        if page is not None and page.active:
            lines = [""]
            for idx, (title, session_id, last_message) in enumerate(entries):
                lines.append(f"[{idx}] {title}")
                lines.append(f"    {DIM}{session_id}{RESET}")
                if last_message:
                    lines.append(f"    Son mesaj: {last_message}")
                lines.append("")
            page.show_overlay("\n".join(lines))
            return
        print()
        for idx, (title, session_id, last_message) in enumerate(entries):
            print(f"[{idx}] {title}")
            print(f"    {DIM}{session_id}{RESET}")
            if last_message:
                print(f"    Son mesaj: {last_message}")
            print()

    def show_stats(self, title: str, message_count: int, context_tokens: int,
                   total_input: int, total_output: int):
        page = get_page()
        if page is not None and page.active:
            page.show_overlay(
                f"\n{CYAN}── İstatistikler ───────────────────────{RESET}\n"
                f"Sohbet : {title}\n"
                f"Mesaj  : {message_count}\n"
                f"Context: {context_tokens:,}\n"
                f"Input  : {total_input:,}\n"
                f"Output : {total_output:,}\n"
            )
            return
        print(f"\n{CYAN}── İstatistikler ───────────────────────{RESET}")
        print(f"Sohbet : {title}")
        print(f"Mesaj  : {message_count}")
        print(f"Context: {context_tokens:,}")
        print(f"Input  : {total_input:,}")
        print(f"Output : {total_output:,}\n")

    def show_help(self):
        page = get_page()
        cmds = [
            ("/new",            "Yeni sohbet oluştur"),
            ("/chats",          "Sohbetleri listele"),
            ("/open N",         "Sohbet aç"),
            ("/rename",         "Aktif sohbeti yeniden adlandır"),
            ("/delete N",       "Sohbet sil"),
            ("/clear",          "Aktif sohbeti temizle"),
            ("/stats",          "İstatistik göster"),
            ("/debug",          "Debug aç/kapat"),
            ("─── Medya ─────", ""),
            ("@dosya",          "Yazınca kutu; ↑↓/Tab seç, Enter al, Esc kapat"),
            ("@src/  @~/  @/",  "Alt dizin / ev / mutlak yol"),
            ("─── Arama ─────", ""),
            ("(otomatik)",       "Model gerekirse kendisi web'de arar"),
            ("?\"sorgu\"",      "Satır içinde web ara, yazmaya devam et"),
            ("/ara <sorgu>",     "Web ara, belleğe al (sonraki mesajla gider)"),
            ("/arama",           "Arama ayarları (SearXNG / Tavily)"),
            ("─────────────",  ""),
            ("/help",           "Yardım menüsü"),
            ("Shift+Enter",     "Giriş kutusunda yeni satır"),
            ("Ctrl+X",          "Yanıtı kes (program açık kalır)"),
            ("q/quit",          "Çıkış"),
        ]
        help_text = f"\n{CYAN}── Komutlar ─────────────────────────{RESET}\n"
        for cmd, desc in cmds:
            if cmd.startswith("─"):
                help_text += f"{DIM}{cmd}{RESET}\n"
            else:
                help_text += f"{GREEN}{cmd:<20}{RESET} {desc}\n"
        help_text += f"\n{CYAN}── Kullanım ─────────────────────────{RESET}\n"
        help_text += f"  {DIM}dosya{RESET}   {GREEN}@readme.md{RESET} şunu özetle\n"
        help_text += f"           {GREEN}@foto.png{RESET} bu resmi açıkla\n"
        help_text += f"           {GREEN}@ses.wav{RESET} bunu yazıya dök\n"
        help_text += f"           {GREEN}@src/{RESET}  {DIM}kutuda {GREEN}../{RESET}{DIM}  ↑↓/Tab seç  Enter dosya veya dizin{RESET}\n"
        help_text += f"  {DIM}arama{RESET}   {GREEN}?\"python 3.14 changelog\"{RESET} bunu özetle\n"
        help_text += f"           {GREEN}@main.py ?\"asyncio docs\"{RESET} bu koda uyarla\n"
        help_text += f"           {GREEN}/ara python 3.14{RESET}  → sonra prompt yaz\n"
        help_text += f"\n{DIM}Ayrıntı: arama.md{RESET}\n"
        help_text += f"{DIM}Whisper pipe: whisper_dinle.sh çalıştır →\n"
        help_text += f"  main.py'ye Enter'a basarak aktar{RESET}\n"
        if page is not None and page.active:
            page.show_overlay(help_text)
        else:
            print(help_text)

    def show_quit(self):
        _write("Çıkış yapılıyor...")

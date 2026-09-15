GREEN = '\033[92m'
YELLOW = '\033[93m'
CYAN = '\033[96m'
RED = '\033[91m'
DIM = '\033[2m'
RESET = '\033[0m'
BOLD = '\033[1m'
BOLD_RESET = '\033[22m'


class TerminalUI:
    """Terminal sunum katmanı."""

    def prompt(self) -> str:
        return input(f"{GREEN}Sen:{RESET} ").strip()

    def show_fetching_context(self):
        print(f"\n🔍 Provider'dan context bilgisi alınıyor...", end=" ")

    def show_fetched_context(self, n_ctx: int, source: str):
        if source == "fallback":
            print(f"{YELLOW}✗{RESET}")
        else:
            print(f"{GREEN}✓{RESET} ({source}: {n_ctx:,} token)")

    def show_context_fallback_warning(self, fallback: int):
        print(f"{YELLOW}⚠ Context size sağlayıcıdan alınamadı; varsayılan "
              f"{fallback} token kullanılıyor.{RESET}")
        print(f"{YELLOW}  İpucu: .env'e CONTEXT_PROVIDER ekleyerek kaynağı "
              f"belirtebilirsin (örn. CONTEXT_PROVIDER=anthropic).{RESET}")

    def show_startup(self, title: str, session_id: str, max_context: int, pipe_path: str):
        print(f"\n🤖 {CYAN}Yapay Zeka Ajanı{RESET}")
        print(f"{DIM}   Aktif sohbet : {title}{RESET}")
        print(f"{DIM}   Session      : {session_id}{RESET}")
        print(f"{DIM}   Max context  : {max_context:,} token")
        print(f"   Güvenlik payı: {int(max_context * 0.85):,} token")
        print(f"   Whisper pipe : {pipe_path}")
        print(f"   /help yazarak komutları görebilirsiniz{RESET}\n")

    def show_context_bar(self, used: int, maximum: int):
        ratio = min(used / maximum, 1.0)
        width = 28
        filled = int(width * ratio)
        bar = "█" * filled + "░" * (width - filled)
        color = GREEN if ratio < 0.60 else YELLOW if ratio < 0.85 else RED
        print(
            f"{DIM}ctx [{color}{bar}{RESET}{DIM}] "
            f"{used:,}/{maximum:,} tok ({ratio*100:.1f}%){RESET}"
        )

    def show_attachment_count(self, count: int):
        print(f"{DIM}📎 {count} ek bellekte bekliyor. Sorunuzu yazın veya Enter ile gönderin.{RESET}")

    def show_token_stats(self, input_tok: int, output_tok: int, elapsed: float, estimated: bool = False):
        tilde = "~" if estimated else ""
        src = "(tahmini)" if estimated else "(server)"
        rate = f"{output_tok / elapsed:.1f} tok/s" if elapsed > 0 else "— tok/s"
        print(
            f"{DIM}"
            f"↳ {tilde}giriş: {input_tok:,} tok │ "
            f"çıkış: {output_tok:,} tok │ "
            f"toplam: {input_tok + output_tok:,} tok │ "
            f"{RESET}{GREEN}{rate}{RESET} "
            f"{DIM}{src}{RESET}"
        )
        print()

    def show_session_list(self, entries: list):
        print()
        for idx, (title, session_id, last_message) in enumerate(entries):
            print(f"[{idx}] {title}")
            print(f"    {DIM}{session_id}{RESET}")
            if last_message:
                print(f"    Son mesaj: {last_message}")
            print()

    def show_stats(self, title: str, message_count: int, context_tokens: int,
                   total_input: int, total_output: int):
        print(f"\n{CYAN}── İstatistikler ───────────────────────{RESET}")
        print(f"Sohbet : {title}")
        print(f"Mesaj  : {message_count}")
        print(f"Context: {context_tokens:,}")
        print(f"Input  : {total_input:,}")
        print(f"Output : {total_output:,}\n")

    def show_help(self):
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
            ("/ses",            "Mikrofonu kaydet ve belleğe al"),
            ("/ses <dosya>",    "Ses dosyasını çevir ve belleğe al (.wav)"),
            ("/read <dosya>",   "Dosyayı oku ve belleğe al (veya /dosya)"),
            ("/resim <dosya>",  "Resmi belleğe al (vision model gerekir)"),
            ("─── Arama ─────", ""),
            ("(otomatik)",       "Model gerekirse kendisi web'de arar (ajan)"),
            ("/ara <sorgu>",     "Zorunlu arama: önce ara, sonra modele gönder"),
            ("/arama",           "Arama ayarları (SearXNG / Tavily)"),
            ("─────────────",  ""),
            ("/help",           "Yardım menüsü"),
            ("q/quit",          "Çıkış"),
        ]
        print(f"\n{CYAN}── Komutlar ─────────────────────────{RESET}")
        for cmd, desc in cmds:
            if cmd.startswith("─"):
                print(f"{DIM}{cmd}{RESET}")
            else:
                print(f"{GREEN}{cmd:<20}{RESET} {desc}")
        print()
        print(f"{DIM}Whisper pipe: whisper_dinle.sh çalıştır →")
        print(f"  main.py'ye Enter'a basarak aktar{RESET}\n")

    def show_quit(self):
        print("Çıkış yapılıyor...")

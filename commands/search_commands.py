import getpass

from chat.attachments import AttachmentManager
from chat.service import ChatService
from search.config import SearchConfig
from search.service import SearchService
from state import ApplicationState
from ui.terminal import CYAN, DIM, GREEN, RED, RESET, YELLOW, get_page


class SearchCommands:
    """Arama komutları: /ara <sorgu>, /arama (ayar menüsü)."""

    def __init__(self, search: SearchService, attachments: AttachmentManager,
                 chat_service: ChatService, terminal):
        self.search = search
        self.attachments = attachments
        self.chat_service = chat_service
        self.terminal = terminal

    def ara(self, state: ApplicationState, user_input: str):
        parts = user_input.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            print('Kullanım: /ara <sorgu>  veya  ?"sorgu" kalan prompt\n')
            return
        query = parts[1].strip()

        config = self.search.load()
        print(f"{DIM}🔎 '{query}' aranıyor...{RESET}", end=" ", flush=True)
        try:
            results = self.search.search(query, config)
        except Exception as e:
            print(f"\n{RED}❌ Arama hatası:{RESET} {e}\n")
            return

        if not results:
            print(f"\n{YELLOW}⚠ Sonuç bulunamadı{RESET}\n")
            return

        print(f"{GREEN}✓{RESET} {len(results)} sonuç ({config.provider})")
        for idx, result in enumerate(results, 1):
            title = result.title[:70] if result.title else result.url
            print(f"{DIM}  {idx}. {title} — {result.url}{RESET}")
        print()

        self.attachments.add_text(self.search.format_for_model(query, results))
        print(f"{DIM}📎 Sonuçlar eklendi. Prompt yazıp Enter'a basın "
              f"(veya satır içinde ?\"sorgu\" kullanın).{RESET}\n")

    def ayarlar(self, state: ApplicationState):
        page = get_page()
        saved = page.suspend() if page is not None and page.active else None
        try:
            config = self.search.load()
            while True:
                self._show_menu(config)
                try:
                    choice = input("Seçim: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return
                if choice == "0":
                    print()
                    return
                if choice == "":
                    continue
                try:
                    self._apply(choice, config)
                except Exception as e:
                    print(f"{RED}❌ {e}{RESET}\n")
        finally:
            if page is not None and saved is not None:
                page.resume(saved)

    def _show_menu(self, config: SearchConfig):
        key_state = "ayarlanmamış"
        if config.tavily_api_key:
            masked = config.tavily_api_key[:8] + "…"
            key_state = f"{masked} ({len(config.tavily_api_key)} karakter)"
        safesearch_labels = {0: "0 (kapalı)", 1: "1 (orta)", 2: "2 (sıkı)"}
        safesearch = safesearch_labels.get(
            config.searxng_safesearch, str(config.searxng_safesearch)
        )

        print(f"\n{CYAN}── İnternet Arama Ayarları ──────────{RESET}")
        print(f"  Sağlayıcı      : {config.provider}")
        print(f"\n  {CYAN}SearXNG{RESET}")
        print(f"    Base URL     : {config.searxng_base_url or '-'}")
        print(f"    Dil          : {config.searxng_language}")
        print(f"    Güvenli arama: {safesearch}")
        print(f"    Kategori     : {config.searxng_categories or '-'}")
        print(f"\n  {CYAN}Tavily{RESET}")
        print(f"    Base URL     : {config.tavily_base_url or '-'}")
        print(f"    API Key      : {key_state}")
        print(f"\n  Sonuç sayısı   : {config.max_results}")
        print(f"  Zaman aşımı    : {config.timeout} sn")
        print(f"  {DIM}Dosya: {self.search.config_path} — program açıkken de düzenlenebilir{RESET}")
        print()
        print(f"[{GREEN}1{RESET}] Sağlayıcı seç (searxng / tavily)")
        print(f"[{GREEN}2{RESET}] SearXNG base URL      (örn. http://localhost:8888)")
        print(f"[{GREEN}3{RESET}] SearXNG dil           (örn. auto, tr, en)")
        print(f"[{GREEN}4{RESET}] SearXNG güvenli arama (0=kapalı, 1=orta, 2=sıkı)")
        print(f"[{GREEN}5{RESET}] SearXNG kategori      (örn. general, news, it, science)")
        print(f"[{GREEN}6{RESET}] Tavily base URL       (varsayılan: https://api.tavily.com)")
        print(f"[{GREEN}7{RESET}] Tavily API key gir")
        print(f"[{GREEN}8{RESET}] Sonuç sayısı gir      (1-10)")
        print(f"[{GREEN}9{RESET}] Bağlantı testi")
        print(f"[{GREEN}0{RESET}] Çıkış")

    def _apply(self, choice: str, config: SearchConfig):
        if choice == "1":
            value = input("Sağlayıcı (searxng/tavily): ").strip().lower()
            if value not in ("searxng", "tavily"):
                print(f"{RED}Geçersiz sağlayıcı. 'searxng' veya 'tavily' girin.{RESET}\n")
                return
            config.provider = value
            self._save(config)
        elif choice == "2":
            config.searxng_base_url = input(
                "SearXNG base URL (örn. http://localhost:8888): "
            ).strip()
            self._save(config)
        elif choice == "3":
            config.searxng_language = input(
                "SearXNG dil (örn. auto, tr, en, de; boş=auto): "
            ).strip() or "auto"
            self._save(config)
        elif choice == "4":
            raw = input("SearXNG güvenli arama (0=kapalı, 1=orta, 2=sıkı): ").strip()
            if raw not in ("0", "1", "2"):
                print(f"{RED}0, 1 veya 2 girin.{RESET}\n")
                return
            config.searxng_safesearch = int(raw)
            self._save(config)
        elif choice == "5":
            config.searxng_categories = input(
                "SearXNG kategori (örn. general, news, it, science, images; "
                "boş=general): "
            ).strip() or "general"
            self._save(config)
        elif choice == "6":
            config.tavily_base_url = input(
                "Tavily base URL (varsayılan: https://api.tavily.com): "
            ).strip() or "https://api.tavily.com"
            self._save(config)
        elif choice == "7":
            key = getpass.getpass("Tavily API key (girdi gizlenir): ").strip()
            if not key:
                print(f"{RED}Boş key kabul edilmedi.{RESET}\n")
                return
            config.tavily_api_key = key
            self._save(config)
        elif choice == "8":
            raw = input("Sonuç sayısı (1-10): ").strip()
            if not raw.isdigit() or not 1 <= int(raw) <= 10:
                print(f"{RED}1-10 arası bir sayı girin.{RESET}\n")
                return
            config.max_results = int(raw)
            self._save(config)
        elif choice == "9":
            print(f"{DIM}Test ediliyor...{RESET}", end=" ", flush=True)
            try:
                message = self.search.test(config)
                print(f"{message}\n")
            except Exception as e:
                print(f"{RED}❌ {e}{RESET}\n")
        else:
            print(f"{RED}Geçersiz seçim{RESET}\n")

    def _save(self, config: SearchConfig):
        self.search.save(config)
        print(f"{GREEN}✓ Kaydedildi:{RESET} {self.search.config_path}\n")

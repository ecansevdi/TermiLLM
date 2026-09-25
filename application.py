from chat.attachments import AttachmentManager
from chat.context import ContextManager
from chat.mentions import MentionError, MentionProcessor
from chat.service import ChatService
from commands.router import CommandRouter
from config import Config
from llm.server_info import resolve_context_size
from media.pipe import PipeInput
from sessions.manager import SessionManager
from state import ApplicationState
from ui import clock
from ui.terminal import RED, RESET, TerminalUI, get_page


class AgentApplication:
    """Uygulama yaşam döngüsü ve REPL döngüsü."""

    def __init__(self, config: Config, state: ApplicationState,
                 terminal: TerminalUI, router: CommandRouter,
                 chat_service: ChatService, session_manager: SessionManager,
                 attachments: AttachmentManager, pipe_input: PipeInput,
                 context: ContextManager, mentions: MentionProcessor = None,
                 page=None):
        self.config = config
        self.state = state
        self.terminal = terminal
        self.router = router
        self.chat_service = chat_service
        self.sessions = session_manager
        self.attachments = attachments
        self.pipe_input = pipe_input
        self.context = context
        self.mentions = mentions
        self.page = page

    # ------------------------------------------------------------------ #
    # Yaşam döngüsü
    # ------------------------------------------------------------------ #

    def run(self):
        storage = self.sessions.storage
        storage.ensure_directory()

        sessions = storage.list()
        if sessions:
            self.state.active_session = self.sessions.open_session(sessions[0])
        else:
            self.state.active_session = self.sessions.new_session()
        self.state.actual_context_tokens = self.context.estimate_messages(
            self.state.active_session.history
        )

        # "Yeni sayfa" katmanını aç (siyah zemin, üst çubuk, alt kutu)
        if self.page is not None:
            # Ctrl+P ile seçilen eforu state'e taşı; mevcut değeri göster
            self.page.set_effort(self.state.reasoning_effort)
            self.page.set_effort_callback(
                lambda lvl: setattr(self.state, "reasoning_effort", lvl)
            )
            # Ctrl+O: provider menüsü
            self.page.set_menu_callback(self._open_provider_menu)
            self.page.enter()

        clock.warmup()   # arka planda bölgesel saat keşfi
        if self.pipe_input:
            self.pipe_input.start()
            self.pipe_input.install_pre_input_hook()

        n_ctx, source = resolve_context_size(
            self.config.api_base_url,
            self.config.api_key,
            self.config.agent_model,
            fallback=self.config.context_fallback,
            provider=self.config.context_provider,
        )
        if source == "fallback":
            self.terminal.show_context_fallback_warning(n_ctx)
        self.state.max_context_tokens = n_ctx

        title = storage.get_title(self.state.active_session.id)
        self.terminal.show_startup(
            title,
            self.state.active_session.id,
            self.state.max_context_tokens,
            self.config.pipe_path,
        )
        if self.page is not None:
            self.page.set_metrics(
                ctx_used=self.state.actual_context_tokens, ctx_total=n_ctx
            )

        self._repl()
        if self.page is not None:
            self.page.leave()

    # ------------------------------------------------------------------ #
    # Ctrl+O: provider menüsü
    # ------------------------------------------------------------------ #

    def _open_provider_menu(self):
        from ui.provider_menu import show_provider_menu

        show_provider_menu(
            self.page,
            current_name=self.config.provider_selection,
            current_base=self.config.api_base_url,
            current_model=self.config.agent_model,
            apply_provider=self._apply_provider,
        )

    def _apply_provider(self, base_url: str, api_key: str, model: str):
        """Menüden gelen provider/model değişimini uygular.

        İstemci yeniden bağlanır (yeniden başlatma gerekmez), context
        bilgisi yeni sunucudan sorgulanır, efor yoklaması yeniden koşar.
        """
        try:
            self.chat_service.llm_client.rebind(base_url, api_key, model)
        except Exception:
            pass

        n_ctx, source = resolve_context_size(
            base_url, api_key, model,
            fallback=self.config.context_fallback,
            provider=self.config.context_provider,
        )
        if source == "fallback":
            self.terminal.show_context_fallback_warning(n_ctx)
        self.state.max_context_tokens = n_ctx
        if self.page is not None:
            self.page.set_metrics(
                ctx_used=self.state.actual_context_tokens, ctx_total=n_ctx
            )


    # ------------------------------------------------------------------ #
    # REPL
    # ------------------------------------------------------------------ #

    def _repl(self):
        while True:
            self.terminal.show_context_bar(
                self.state.actual_context_tokens, self.state.max_context_tokens
            )

            if self.attachments.has_pending():
                self.terminal.show_attachment_count(self.attachments.count())

            try:
                user_input = self.terminal.prompt(
                    poll_prefill=self.pipe_input.take_prefill
                )
            except (EOFError, KeyboardInterrupt):
                self.terminal.show_quit()
                break

            if user_input.lower() in ("q", "quit"):
                self.terminal.show_quit()
                break

            if self.router.handle(user_input, self.state):
                continue

            if self.mentions and ("@" in user_input or "?" in user_input):
                # @dosya / ?arama işlemleri sayfayı askıya alıp düz terminalde
                # çalışsın ki çıktıları balona karışmasın.
                saved = self.page.suspend() if self.page else None
                try:
                    user_input = self.mentions.process(user_input)
                except MentionError as e:
                    print(f"{RED}❌ {e}{RESET}\n")
                    if self.page:
                        self.page.resume(saved)
                    continue
                if self.page:
                    self.page.resume(saved)

            if not user_input and not self.attachments.has_pending():
                continue

            if self.page is not None and page_active(self.page):
                self.page.show_user_message(user_input)
                self.page.queue_line("")   # balon sonrası boşluk
                self.page.queue_line("")   # mesaj ↔ cevap arası 1 boş satır
            self.chat_service.send_message(user_input)
            if self.page is not None and page_active(self.page):
                # Cevabın bittiği satıra sağa yaslı saat hücresi ekle
                stamp = self.chat_service.renderer.response_stamp()
                if stamp:
                    self.page.stamp_last_line(stamp, self.page.RIGHT_STAMP)
                self.page.queue_line("")  # tur sonu boşluğu


def page_active(page) -> bool:
    return page is not None and page.active

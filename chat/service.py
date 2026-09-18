import os

from chat.attachments import AttachmentManager
from chat.context import ContextManager
from llm.cancel import CancelWatch, GenerationCancelled
from llm.client import LLMClient
from llm.stream import StreamResult, clean_response
from search.service import SearchService
from sessions.manager import SessionManager
from state import ApplicationState
from ui.stream_renderer import StreamRenderer
from ui.terminal import DIM, GREEN, RED, RESET, YELLOW, TerminalUI

MAX_SEARCH_ROUNDS = 6


class ChatService:
    """Mesaj gönderim akışını koordine eder.

    Model yanıtında <web_search> çağrısı görürse aramayı çalıştırıp sonuçları
    modele geri besler; model düz cevap verene dek devam eder (ajan döngüsü).
    """

    def __init__(self, state: ApplicationState, attachments: AttachmentManager,
                 context: ContextManager, llm_client: LLMClient,
                 session_manager: SessionManager, renderer: StreamRenderer,
                 terminal: TerminalUI, search_service: SearchService = None):
        self.state = state
        self.attachments = attachments
        self.context = context
        self.llm_client = llm_client
        self.sessions = session_manager
        self.renderer = renderer
        self.terminal = terminal
        self.search = search_service

    def send_message(self, user_input: str):
        print(f"{DIM}   Ctrl+X yanıtı keser (program açık kalır){RESET}")
        try:
            with CancelWatch() as cancel:
                self._send_message(user_input, cancel)
        except GenerationCancelled:
            print(f"\n{YELLOW}⚠ Yanıt kesildi{RESET}\n")
            try:
                self.renderer.show_stream_end()
            except Exception:
                print()

    def _send_message(self, user_input: str, cancel: CancelWatch):
        state = self.state
        history = state.active_session.history
        final_text = self.attachments.build_final_text(user_input)

        if self.attachments.vision_message:
            self._send_with_image(final_text, user_input, history, cancel)
            return

        history.append({"role": "user", "content": final_text})
        self.attachments.clear_text()

        searches_done = 0
        while True:
            cancel.check()
            history = self._trim_history(history, final_text)
            messages = self.context.build_messages(history)
            result = self._stream_and_respond(messages, history, cancel)

            if result is None:
                if history and history[-1]["role"] == "user":
                    history.pop()
                return

            state.actual_context_tokens = result.input_tokens + result.output_tokens

            queries = result.search_queries if self.search else []
            if not queries or searches_done >= MAX_SEARCH_ROUNDS:
                if queries:
                    print(
                        f"{YELLOW}⚠ Arama turu limiti ({MAX_SEARCH_ROUNDS}) doldu; "
                        f"ek aramalar yapılmadı{RESET}"
                    )
                return

            blocks = []
            for query in queries:
                cancel.check()
                if searches_done >= MAX_SEARCH_ROUNDS:
                    break
                searches_done += 1
                blocks.append(self._run_web_search(query))
            history.append({"role": "user", "content": "\n\n".join(blocks)})

    def _run_web_search(self, query: str) -> str:
        print(f"{DIM}🔎 '{query}' aranıyor...{RESET}", end=" ", flush=True)
        try:
            results = self.search.search(query)
        except Exception as e:
            print(f"\n{RED}❌ Arama hatası:{RESET} {e}")
            return (
                f"--- Web Arama Hatası ---\nSorgu: {query}\nHata: {e}\n"
                "--- Web Arama Hatası Sonu ---"
            )
        if not results:
            print(f"{YELLOW}⚠ Sonuç bulunamadı{RESET}")
            return (
                f"--- Web Arama Sonuçları ---\nSorgu: {query}\n"
                "Sonuç bulunamadı.\n--- Web Arama Sonuçları Sonu ---"
            )
        print(f"{GREEN}✓{RESET} {len(results)} sonuç")
        for idx, result in enumerate(results, 1):
            title = result.title[:70] if result.title else result.url
            print(f"{DIM}  {idx}. {title} — {result.url}{RESET}")
        return self.search.format_for_model(query, results)

    def _send_with_image(self, final_text: str, user_input: str, history: list,
                         cancel: CancelWatch):
        state = self.state
        self.attachments.vision_message["content"][1]["text"] = final_text

        history_label = (
            f"[Resim: {os.path.basename(self.attachments.vision_path)}] "
            f"{user_input if user_input else 'İnceleme talebi'}"
        )
        history.append({"role": "user", "content": history_label})

        messages = self.context.build_messages(history[:-1]) + [self.attachments.vision_message]

        result = self._stream_and_respond(messages, history, cancel)
        if result:
            state.actual_context_tokens = result.input_tokens + result.output_tokens
        elif history and history[-1]["role"] == "user":
            history.pop()

        self.attachments.clear()

    def _trim_history(self, history: list, final_text: str) -> list:
        state = self.state
        effective_budget = self.context.calculate_budget(state.max_context_tokens)
        was_trimmed = False

        if state.actual_context_tokens is not None:
            projected = state.actual_context_tokens + self.context.estimate_text(final_text) + 10
            while len(history) > 2 and projected > effective_budget:
                removed = (
                    self.context.estimate_text(history[0].get("content", ""))
                    + self.context.estimate_text(history[1].get("content", ""))
                    + 20
                )
                history = history[2:]
                projected = max(0, projected - removed)
                was_trimmed = True
        else:
            history, was_trimmed = self.context.trim(history, effective_budget)

        if was_trimmed:
            print(f"{YELLOW}⚠ Context kırpıldı{RESET}")
            state.active_session.history = history
        return history

    def _stream_and_respond(self, messages: list, history: list,
                            cancel: CancelWatch = None):
        try:
            result = self.llm_client.stream(
                messages,
                renderer=self.renderer,
                debug_enabled=self.state.debug_enabled,
                cancel=cancel,
            )
        except GenerationCancelled:
            raise
        except Exception as e:
            print(f"\n{RED}[Hata]{RESET}: {e}\n")
            return None

        if result.usage_estimated:
            result.input_tokens = self.context.estimate_messages(history[:-1])
            result.output_tokens = self.context.estimate_text(
                result.assistant_text + result.thinking_text
            )

        self.terminal.show_token_stats(
            result.input_tokens, result.output_tokens, result.elapsed,
            result.usage_estimated,
        )

        self.sessions.storage.append_token_usage(
            self.state.active_session.id,
            result.input_tokens, result.output_tokens,
        )

        assistant_message = clean_response(result.assistant_text)
        for query in result.search_queries:
            assistant_message += f"\n<web_search>{query}</web_search>"
        history.append({"role": "assistant", "content": assistant_message.strip()})
        self.sessions.storage.save_history(self.state.active_session.id, history)

        return result

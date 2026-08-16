from chat.attachments import AttachmentManager
from chat.context import ContextManager
from sessions.manager import SessionManager
from state import ApplicationState
from ui.terminal import GREEN, RED, RESET, YELLOW, TerminalUI


class SessionCommands:
    """Session komutları: /new, /chats, /open, /rename, /delete, /clear."""

    def __init__(self, session_manager: SessionManager, context: ContextManager,
                 attachments: AttachmentManager, terminal: TerminalUI):
        self.sessions = session_manager
        self.storage = session_manager.storage
        self.context = context
        self.attachments = attachments
        self.terminal = terminal

    def new(self, state: ApplicationState):
        state.active_session = self.sessions.new_session()
        state.actual_context_tokens = 0
        self.attachments.clear()
        print(f"{GREEN}✓ Yeni sohbet oluşturuldu:{RESET} {state.active_session.id}\n")

    def chats(self, state: ApplicationState):
        entries = []
        for session_id in self.storage.list():
            metadata = self.storage.load_metadata(session_id)
            title = metadata.get("title", "Başlıksız")
            history = self.storage.load_history(session_id)
            last_message = ""
            if history:
                last_message = history[-1].get("content", "")[:80]
            entries.append((title, session_id, last_message))
        self.terminal.show_session_list(entries)

    def open(self, state: ApplicationState, user_input: str):
        parts = user_input.split()
        if len(parts) != 2:
            print("Kullanım: /open <index>")
            return
        sessions = self.storage.list()
        try:
            idx = int(parts[1])
            session_id = sessions[idx]
        except Exception:
            print(f"{RED}Geçersiz index{RESET}\n")
            return
        state.active_session = self.sessions.open_session(session_id)
        state.actual_context_tokens = self.context.estimate_messages(
            state.active_session.history
        )
        self.attachments.clear()
        metadata = self.storage.load_metadata(session_id)
        title = metadata.get("title", session_id)
        print(f"{GREEN}✓ Sohbet açıldı:{RESET} {title}\n")

    def rename(self, state: ApplicationState, user_input: str):
        new_title = user_input.replace("/rename", "").strip()
        if not new_title:
            print("Kullanım: /rename Yeni Başlık")
            return
        self.sessions.rename_session(state.active_session.id, new_title)
        print(f"{GREEN}✓ Yeni başlık:{RESET} {new_title}\n")

    def delete(self, state: ApplicationState, user_input: str):
        parts = user_input.split()
        if len(parts) != 2:
            print("Kullanım: /delete <index>")
            return
        sessions = self.storage.list()
        try:
            idx = int(parts[1])
            session_id = sessions[idx]
        except Exception:
            print("Geçersiz index")
            return
        self.sessions.delete_session(session_id)
        print(f"{GREEN}✓ Silindi:{RESET} {session_id}\n")
        sessions = self.storage.list()
        if sessions:
            state.active_session = self.sessions.open_session(sessions[0])
        else:
            state.active_session = self.sessions.new_session()
        state.actual_context_tokens = self.context.estimate_messages(
            state.active_session.history
        )

    def clear(self, state: ApplicationState):
        state.active_session.history = []
        state.actual_context_tokens = 0
        self.storage.save_history(state.active_session.id, [])
        self.attachments.clear()
        print(f"{YELLOW}✓ Sohbet ve ekler temizlendi{RESET}\n")

from sessions.manager import SessionManager
from state import ApplicationState
from ui.terminal import TerminalUI


class SystemCommands:
    """Sistem komutları: /stats, /debug, /help."""

    def __init__(self, session_manager: SessionManager, terminal: TerminalUI):
        self.sessions = session_manager
        self.storage = session_manager.storage
        self.terminal = terminal

    def debug(self, state: ApplicationState):
        state.debug_enabled = not state.debug_enabled
        label = "AÇIK" if state.debug_enabled else "KAPALI"
        print(f"Debug: {label}\n")

    def help(self, state: ApplicationState):
        self.terminal.show_help()

    def stats(self, state: ApplicationState):
        total_input, total_output = self.storage.get_token_usage(
            state.active_session.id
        )
        metadata = self.storage.load_metadata(state.active_session.id)
        title = metadata.get("title", state.active_session.id)
        self.terminal.show_stats(
            title,
            len(state.active_session.history),
            state.actual_context_tokens,
            total_input,
            total_output,
        )

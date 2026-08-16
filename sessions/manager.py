import os

from sessions.storage import SessionStorage
from state import SessionState


class SessionManager:
    """Uygulama seviyesindeki session davranışını yönetir."""

    def __init__(self, storage: SessionStorage):
        self.storage = storage

    def new_session(self, title: str = "Yeni Sohbet") -> SessionState:
        session_id = self.storage.create(title)
        return self._build_state(session_id)

    def open_session(self, session_id: str) -> SessionState:
        paths = self.storage.paths_for(session_id)
        if not os.path.exists(paths["directory"]):
            raise FileNotFoundError("Session bulunamadı")
        session = self._build_state(session_id)
        session.history = self.storage.load_history(session_id)
        return session

    def _build_state(self, session_id: str) -> SessionState:
        paths = self.storage.paths_for(session_id)
        return SessionState(
            id=session_id,
            directory=paths["directory"],
            history_file=paths["history_file"],
            metadata_file=paths["metadata_file"],
            token_file=paths["token_file"],
        )

    def rename_session(self, session_id: str, new_title: str):
        metadata = self.storage.load_metadata(session_id)
        metadata["title"] = new_title
        self.storage.save_metadata(session_id, metadata)

    def delete_session(self, session_id: str):
        self.storage.delete(session_id)

    def clear_session(self, session_id: str):
        self.storage.save_history(session_id, [])

    def list_sessions(self) -> list:
        return self.storage.list()

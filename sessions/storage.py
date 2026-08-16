import json
import os
import shutil
import time
from datetime import datetime


class SessionStorage:
    """Sadece disk/persistence işlemlerinden sorumlu katman."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir

    def ensure_directory(self):
        os.makedirs(self.base_dir, exist_ok=True)

    def paths_for(self, session_id: str) -> dict:
        chat_dir = os.path.join(self.base_dir, session_id)
        return {
            "directory": chat_dir,
            "history_file": os.path.join(chat_dir, "history.json"),
            "metadata_file": os.path.join(chat_dir, "metadata.json"),
            "token_file": os.path.join(chat_dir, "token_log.txt"),
        }

    def create(self, title: str = "Yeni Sohbet") -> str:
        self.ensure_directory()
        session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        chat_dir = os.path.join(self.base_dir, session_id)
        os.makedirs(chat_dir, exist_ok=True)
        paths = self.paths_for(session_id)

        with open(paths["history_file"], "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=4)

        metadata = {
            "session_id": session_id,
            "created_at": time.time(),
            "title": title,
        }
        with open(paths["metadata_file"], "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=4)

        return session_id

    def delete(self, session_id: str):
        path = os.path.join(self.base_dir, session_id)
        if os.path.exists(path):
            shutil.rmtree(path)

    def list(self) -> list:
        self.ensure_directory()
        sessions = []
        for name in os.listdir(self.base_dir):
            if os.path.isdir(os.path.join(self.base_dir, name)):
                sessions.append(name)
        sessions.sort(reverse=True)
        return sessions

    def load_history(self, session_id: str) -> list:
        path = self.paths_for(session_id)["history_file"]
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                try:
                    return json.load(f)
                except Exception:
                    return []
        return []

    def save_history(self, session_id: str, history: list):
        path = self.paths_for(session_id)["history_file"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=4)

    def load_metadata(self, session_id: str) -> dict:
        path = self.paths_for(session_id)["metadata_file"]
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_metadata(self, session_id: str, data: dict):
        path = self.paths_for(session_id)["metadata_file"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def get_title(self, session_id: str) -> str:
        return self.load_metadata(session_id).get("title", session_id)

    def append_token_usage(self, session_id: str, input_tokens: int, output_tokens: int):
        path = self.paths_for(session_id)["token_file"]
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{input_tokens},{output_tokens}\n")

    def get_token_usage(self, session_id: str) -> tuple:
        total_input = 0
        total_output = 0
        path = self.paths_for(session_id)["token_file"]
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split(",")
                    if len(parts) == 2:
                        try:
                            total_input += int(parts[0])
                            total_output += int(parts[1])
                        except Exception:
                            pass
        return total_input, total_output

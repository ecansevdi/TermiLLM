from state import ApplicationState


class AttachmentManager:
    """Bekleyen medya eklerini (metin, ses, görsel) yönetir."""

    def __init__(self, state: ApplicationState):
        self._state = state.attachments

    @property
    def text_attachments(self) -> list:
        return self._state.text_attachments

    @property
    def vision_message(self):
        return self._state.vision_message

    @property
    def vision_path(self):
        return self._state.vision_path

    def add_text(self, content: str):
        self._state.text_attachments.append(content)

    def set_image(self, data_uri: str, path: str):
        self._state.vision_message = {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": data_uri},
                },
                {"type": "text", "text": ""},
            ],
        }
        self._state.vision_path = path

    def has_pending(self) -> bool:
        return bool(self._state.text_attachments or self._state.vision_message)

    def count(self) -> int:
        return len(self._state.text_attachments) + (1 if self._state.vision_message else 0)

    def build_final_text(self, user_input: str) -> str:
        final_text = ""
        if self._state.text_attachments:
            final_text += "\n\n".join(self._state.text_attachments) + "\n\n"
        if user_input:
            final_text += user_input
        else:
            final_text += "Lütfen ekteki içeriği detaylıca incele."
        return final_text.strip()

    def clear_text(self):
        self._state.text_attachments = []

    def clear(self):
        self._state.text_attachments = []
        self._state.vision_message = None
        self._state.vision_path = None

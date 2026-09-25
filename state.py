from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SessionState:
    id: str
    directory: str
    history_file: str
    metadata_file: str
    token_file: str
    history: list = field(default_factory=list)


@dataclass
class AttachmentState:
    text_attachments: list = field(default_factory=list)
    vision_message: Optional[dict] = None
    vision_path: Optional[str] = None


@dataclass
class ApplicationState:
    active_session: Optional[SessionState] = None
    actual_context_tokens: int = 0
    max_context_tokens: int = 4096
    debug_enabled: bool = False
    # Ctrl+P ile seçilen canonical requested_effort (llm/reasoning.py kümesi).
    # None: kullanıcı seçmedi; explicit effort gönderilmez, provider default'u kalır.
    # Seçildiyse provider değişiminde KORUNUR, adapter normalize/omit eder.
    reasoning_effort: Optional[str] = None
    attachments: AttachmentState = field(default_factory=AttachmentState)

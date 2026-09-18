"""Prompt içindeki @dosya ve ?arama belirteçlerini ayıklar.

Satır komut değildir: belirteçler ek/arama olarak işlenir, kalan metin
prompt olarak kalır.

    @readme.md şunu özetle
    @src/main.py ?"python 3.14 changelog" karşılaştır
    @"dosya adı.txt" ?{çok kelimeli sorgu} yorumla
"""

from __future__ import annotations

import os
import re

from chat.attachments import AttachmentManager
from media.audio import AudioService
from media.files import TextFileLoader
from media.images import ImageLoader
from search.service import SearchService
from ui.terminal import DIM, GREEN, RESET, YELLOW

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wma"}

# Boşluk öncesi @ veya ?. E-posta (a@b.com) eşleşmez.
_TOKEN_RE = re.compile(
    r"(?<!\S)(?:"
    r"@(?:\"([^\"]+)\"|'([^']+)'|([^\s]+))"
    r"|"
    r"\?(?:\"([^\"]+)\"|'([^']+)'|\{([^}]+)\}|([^\s]+))"
    r")"
)


class MentionError(Exception):
    pass


def _unquoted_path(value: str) -> str:
    return value.rstrip(".,;:!?")


def parse_mentions(text: str) -> tuple[list[tuple[str, str]], str]:
    """(eylemler, kalan_prompt) döner.

    eylemler: ("file", path) | ("search", query) görünüm sırasıyla.
    """
    actions = []
    spans = []
    for match in _TOKEN_RE.finditer(text or ""):
        file_path = match.group(1) or match.group(2) or match.group(3)
        query = match.group(4) or match.group(5) or match.group(6) or match.group(7)
        if file_path:
            quoted = match.group(1) is not None or match.group(2) is not None
            path = file_path if quoted else _unquoted_path(file_path)
            if path:
                actions.append(("file", path))
                spans.append(match.span())
        elif query:
            query = query.strip()
            if query:
                actions.append(("search", query))
                spans.append(match.span())

    if not spans:
        return actions, (text or "").strip()

    chars = list(text)
    for start, end in reversed(spans):
        chars[start:end] = []
    rest = re.sub(r"[ \t]{2,}", " ", "".join(chars)).strip()
    return actions, rest


class MentionProcessor:
    """@dosya / ?arama belirteçlerini eke çevirir; kalan metni döndürür."""

    def __init__(self, files: TextFileLoader, images: ImageLoader,
                 attachments: AttachmentManager, search: SearchService,
                 terminal=None, audio: AudioService = None):
        self.files = files
        self.images = images
        self.attachments = attachments
        self.search = search
        self.terminal = terminal
        self.audio = audio

    def process(self, text: str) -> str:
        actions, rest = parse_mentions(text)
        if not actions:
            return text.strip() if text else ""

        for kind, value in actions:
            if kind == "file":
                self._attach_file(value)
            else:
                self._run_search(value)
        return rest

    def _attach_file(self, file_path: str):
        path = os.path.expanduser(file_path)
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext in IMAGE_EXTS:
                b64_data, mime_type = self.images.load(path)
                self.attachments.set_image(
                    f"data:{mime_type};base64,{b64_data}", path)
                print(f"\nLoaded image from '{path}'\n")
            elif ext in AUDIO_EXTS:
                if self.audio is None:
                    raise MentionError("Ses servisi yok")
                transcribed = self.audio.transcribe_file(path)
                if not transcribed:
                    raise MentionError("Ses algılanamadı veya çeviri boş")
                self.attachments.add_text(
                    f"--- Ses: {os.path.basename(path)} ---\n{transcribed}\n"
                )
                print(f"\nLoaded audio transcription from '{path}'\n")
            else:
                content = self.files.load(path)
                self.attachments.add_text(
                    f"--- Dosya: {os.path.basename(path)} ---\n{content}\n"
                )
                print(f"\nLoaded text from '{path}'\n")
        except MentionError:
            raise
        except Exception as e:
            raise MentionError(f"{file_path}: {e}") from e

    def _run_search(self, query: str):
        config = self.search.load()
        print(f"{DIM}🔎 '{query}' aranıyor...{RESET}", end=" ", flush=True)
        try:
            results = self.search.search(query, config)
        except Exception as e:
            print()
            raise MentionError(f"Arama hatası: {e}") from e

        if not results:
            print(f"\n{YELLOW}⚠ Sonuç bulunamadı{RESET}\n")
            raise MentionError(f"'{query}' için sonuç yok")

        print(f"{GREEN}✓{RESET} {len(results)} sonuç ({config.provider})")
        for idx, result in enumerate(results, 1):
            title = result.title[:70] if result.title else result.url
            print(f"{DIM}  {idx}. {title} — {result.url}{RESET}")
        print()
        self.attachments.add_text(self.search.format_for_model(query, results))

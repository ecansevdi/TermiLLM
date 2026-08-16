import os

from chat.attachments import AttachmentManager
from media.audio import AudioService
from media.files import TextFileLoader
from media.images import ImageLoader
from state import ApplicationState
from ui.terminal import RED, RESET, TerminalUI


class MediaCommands:
    """Medya komutları: /ses, /read, /dosya, /resim."""

    def __init__(self, audio: AudioService, files: TextFileLoader,
                 images: ImageLoader, attachments: AttachmentManager,
                 terminal: TerminalUI):
        self.audio = audio
        self.files = files
        self.images = images
        self.attachments = attachments
        self.terminal = terminal

    def ses(self, state: ApplicationState, user_input: str):
        parts = user_input.split(maxsplit=1)
        audio_path = parts[1].strip() if len(parts) > 1 else None

        try:
            if audio_path:
                transcribed = self.audio.transcribe_file(audio_path)
            else:
                transcribed = self.audio.record_and_transcribe()
        except Exception as e:
            print(f"{RED}❌ Ses hatası:{RESET} {e}\n")
            return

        if not transcribed:
            print(f"{RED}❌ Ses algılanamadı veya çeviri boş{RESET}\n")
            return

        self.attachments.add_text(f"--- Ses Metni ---\n{transcribed}\n")

        if audio_path:
            print(f"\nLoaded audio transcription from '{audio_path}'\n")
        else:
            print(f"\nLoaded audio transcription from microphone\n")

    def read(self, state: ApplicationState, user_input: str):
        parts = user_input.split(maxsplit=1)
        if len(parts) < 2:
            print("Kullanım: /read <dosya.txt>\n")
            return

        file_path = parts[1].strip()
        try:
            content = self.files.load(file_path)
        except Exception as e:
            print(f"{RED}❌ Dosya hatası:{RESET} {e}\n")
            return

        self.attachments.add_text(
            f"--- Dosya: {os.path.basename(file_path)} ---\n{content}\n"
        )
        print(f"\nLoaded text from '{file_path}'\n")

    def resim(self, state: ApplicationState, user_input: str):
        parts = user_input.split(maxsplit=1)
        if len(parts) < 2:
            print("Kullanım: /resim <resim_dosyası>\n")
            return

        img_path = parts[1].strip()
        try:
            b64_data, mime_type = self.images.load(img_path)
        except Exception as e:
            print(f"{RED}❌ Resim hatası:{RESET} {e}\n")
            return

        self.attachments.set_image(f"data:{mime_type};base64,{b64_data}", img_path)
        print(f"\nLoaded image from '{img_path}'\n")

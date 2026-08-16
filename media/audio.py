import os
import subprocess
import time

from config import Config
from ui.terminal import CYAN, RESET


class AudioService:
    """Whisper transkripsiyonu ve mikrofon kaydı."""

    def __init__(self, config: Config):
        self.whisper_bin = config.whisper_bin
        self.whisper_model = config.whisper_model
        self.whisper_lang = config.whisper_lang

    def transcribe_file(self, audio_path: str) -> str:
        audio_path = os.path.expanduser(audio_path)
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Ses dosyası bulunamadı: {audio_path}")

        if not os.path.exists(self.whisper_model):
            raise FileNotFoundError(
                f"Whisper modeli bulunamadı: {self.whisper_model}\n"
                f"   WHISPER_MODEL ortam değişkenini ayarlayın."
            )

        out_base = "/tmp/whisper_main_out"

        try:
            subprocess.run(
                [
                    self.whisper_bin,
                    "-m", self.whisper_model,
                    "-f", audio_path,
                    "-l", self.whisper_lang,
                    "-nt",
                    "-otxt",
                    "-of", out_base,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Whisper binary bulunamadı: '{self.whisper_bin}'\n"
                f"   WHISPER_BIN ortam değişkenini veya PATH'i kontrol edin.\n"
                f"   CachyOS: paru -S whisper.cpp"
            )

        txt_path = out_base + ".txt"
        if os.path.exists(txt_path):
            with open(txt_path, "r", encoding="utf-8") as f:
                text = f.read()
            os.unlink(txt_path)
            return text.strip()

        result = subprocess.run(
            [self.whisper_bin, "-m", self.whisper_model, "-f", audio_path,
             "-l", self.whisper_lang, "-nt"],
            capture_output=True, text=True, check=False,
        )
        lines = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip() and not line.strip().startswith("[")
        ]
        return " ".join(lines).strip()

    def record_and_transcribe(self) -> str:
        rec_file = f"/tmp/llama_ses_{int(time.time())}.wav"

        try:
            proc = subprocess.Popen(
                ["arecord", "-f", "S16_LE", "-r", "16000", "-c", "1", "-q", rec_file],
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise FileNotFoundError(
                "arecord bulunamadı. CachyOS: paru -S alsa-utils"
            )

        print(f"{CYAN}🎙️  Kayıt yapılıyor — Enter'a basarak durdur{RESET}")
        try:
            input("")
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait()

        try:
            text = self.transcribe_file(rec_file)
        finally:
            if os.path.exists(rec_file):
                os.unlink(rec_file)

        return text

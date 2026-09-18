import os
import sys
import threading
import time

from ui.terminal import DIM, RESET, YELLOW

try:
    import readline
    HAS_READLINE = True
except ImportError:
    HAS_READLINE = False


class PipeInput:
    """Named pipe dinleyicisi + readline prefill entegrasyonu."""

    def __init__(self, pipe_path: str):
        self.pipe_path = pipe_path
        self._prefill_text = None
        self._prefill_lock = threading.Lock()
        self._thread = None

    def start(self):
        try:
            if not os.path.exists(self.pipe_path):
                os.mkfifo(self.pipe_path)
        except Exception as e:
            print(f"{DIM}⚠ Pipe oluşturulamadı ({self.pipe_path}): {e}{RESET}")
            return
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def _watch(self):
        while True:
            try:
                with open(self.pipe_path, "r", encoding="utf-8") as pipe:
                    text = pipe.read().strip()

                if text:
                    with self._prefill_lock:
                        self._prefill_text = text

                    sys.stdout.write(
                        f"\n{YELLOW}🎙️  Ses aktarıldı → mevcut satırı boşaltıp "
                        f"Enter'a basın{RESET}\n"
                    )
                    sys.stdout.flush()

                    if HAS_READLINE:
                        try:
                            readline.redisplay()
                        except Exception:
                            pass
            except Exception:
                time.sleep(0.5)

    def install_pre_input_hook(self):
        """Eski readline kancası; satır editörü take_prefill kullanır."""
        return

    def take_prefill(self):
        with self._prefill_lock:
            text = self._prefill_text
            self._prefill_text = None
            return text

    def consume_prefill(self):
        return self.take_prefill()

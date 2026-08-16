import base64
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv, dotenv_values

try:
    import readline
    HAS_READLINE = True
except ImportError:
    HAS_READLINE = False

# ─── RENKLER ────────────────────────────────────────────────────────────────
GREEN      = '\033[92m'
YELLOW     = '\033[93m'
CYAN       = '\033[96m'
RED        = '\033[91m'
DIM        = '\033[2m'
RESET      = '\033[0m'
BOLD       = '\033[1m'
BOLD_RESET = '\033[22m'

load_dotenv()

# ─── LLAMA.CPP ──────────────────────────────────────────────────────────────
SERVER_BASE = os.getenv("SERVER_BASE")
agent_model = "agent_model"

client = OpenAI(
   base_url=os.getenv("base_url"),
   api_key=os.getenv("api_key")
)

# SERVER_BASE = "https://openrouter.ai/api"
# agent_model = "tencent/hy3:free"

# client = OpenAI(
#     base_url=f"{SERVER_BASE}/v1",
#     api_key="sk"
#     )

DEBUG = False

# ─── WHISPER ────────────────────────────────────────────────────────────────
WHISPER_BIN   = os.environ.get("WHISPER_BIN", "whisper-cli")
WHISPER_MODEL = os.environ.get(
    "WHISPER_MODEL",
    os.path.expanduser("~/whisper.cpp/models/ggml-base.bin")
)
WHISPER_LANG  = os.environ.get("WHISPER_LANG", "tr")

# ─── PIPE (whisper_dinle.sh → main.py) ──────────────────────────────────────
PIPE_PATH = os.environ.get("LLAMA_PIPE", "/tmp/llama_input.pipe")

_prefill_text = None
_prefill_lock = threading.Lock()

# ─── SESSION SİSTEMİ ────────────────────────────────────────────────────────
BASE_CHAT_DIR = "chats"

CURRENT_SESSION  = None
CURRENT_CHAT_DIR = None

HISTORY_FILE  = None
TOKEN_FILE    = None
METADATA_FILE = None

# ─── CONTEXT ────────────────────────────────────────────────────────────────
MAX_CONTEXT_TOKENS    = 4096

# ─── SYSTEM PROMPT ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = (   
    "Türkçe sorulara Türkçe, İngilizce sorulara İngilizce yanıt verirsin. "
    "Cevapların net, kısa ve bilgi odaklıdır."
)


# ────────────────────────────────────────────────────────────────────────────
# WHISPER & DOSYA YARDIMCILARI
# ────────────────────────────────────────────────────────────────────────────

def whisper_transcribe(audio_path: str) -> str:
    """
    Whisper.cpp CLI ile bir ses dosyasını metne çevirir.
    Whisper binary'si PATH'te veya WHISPER_BIN env değişkeninde olmalı.
    """
    audio_path = os.path.expanduser(audio_path)
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Ses dosyası bulunamadı: {audio_path}")

    if not os.path.exists(WHISPER_MODEL):
        raise FileNotFoundError(
            f"Whisper modeli bulunamadı: {WHISPER_MODEL}\n"
            f"   WHISPER_MODEL ortam değişkenini ayarlayın."
        )

    out_base = "/tmp/whisper_main_out"

    try:
        subprocess.run(
            [
                WHISPER_BIN,
                "-m", WHISPER_MODEL,
                "-f", audio_path,
                "-l", WHISPER_LANG,
                "-nt",       # no timestamps
                "-otxt",     # .txt dosyasına yaz
                "-of", out_base,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Whisper binary bulunamadı: '{WHISPER_BIN}'\n"
            f"   WHISPER_BIN ortam değişkenini veya PATH'i kontrol edin.\n"
            f"   CachyOS: paru -S whisper.cpp"
        )

    txt_path = out_base + ".txt"
    if os.path.exists(txt_path):
        with open(txt_path, "r", encoding="utf-8") as f:
            text = f.read()
        os.unlink(txt_path)
        return text.strip()

    # Fallback: -otxt çalışmadıysa stdout'u parse et
    result = subprocess.run(
        [WHISPER_BIN, "-m", WHISPER_MODEL, "-f", audio_path,
         "-l", WHISPER_LANG, "-nt"],
        capture_output=True, text=True, check=False
    )
    lines = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.strip().startswith("[")
    ]
    return " ".join(lines).strip()


def record_and_transcribe() -> str:
    """
    arecord ile mikrofonu kaydeder (Enter ile durdur), ardından Whisper ile çevirir.
    """
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
        text = whisper_transcribe(rec_file)
    finally:
        if os.path.exists(rec_file):
            os.unlink(rec_file)

    return text


def read_text_file(path: str) -> str:
    """Metin dosyasını okur ve içeriğini döner."""
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Dosya bulunamadı: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def encode_image_b64(path: str) -> tuple:
    """Resim dosyasını base64'e çevirir. (b64_data, mime_type) döner."""
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Resim bulunamadı: {path}")
    mime, _ = mimetypes.guess_type(path)
    if not mime or not mime.startswith("image/"):
        mime = "image/jpeg"
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return data, mime


# ────────────────────────────────────────────────────────────────────────────
# NAMED PIPE → READLINE PRE-FILL
# ────────────────────────────────────────────────────────────────────────────

def _pipe_watcher():
    """
    Arka planda named pipe'ı dinler.
    whisper_dinle.sh bir metin yazdığında _prefill_text'e kaydeder,
    bir sonraki input() çağrısında readline hook metni otomatik yerleştirir.
    """
    global _prefill_text

    # Pipe yoksa oluştur
    try:
        if not os.path.exists(PIPE_PATH):
            os.mkfifo(PIPE_PATH)
    except Exception as e:
        print(f"{DIM}⚠ Pipe oluşturulamadı ({PIPE_PATH}): {e}{RESET}")
        return

    while True:
        try:
            # open() pipe dolana kadar burada bloklanır
            with open(PIPE_PATH, "r", encoding="utf-8") as pipe:
                text = pipe.read().strip()

            if text:
                with _prefill_lock:
                    _prefill_text = text

                # Kullanıcıya bildir (mevcut satırı bozmayı minimize et)
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


def _readline_prefill_hook():
    """
    readline pre-input-hook: her yeni input() başlamadan önce çağrılır.
    _prefill_text varsa onu giriş alanına yerleştirir.
    """
    global _prefill_text
    if not HAS_READLINE:
        return
    with _prefill_lock:
        if _prefill_text:
            readline.insert_text(_prefill_text)
            readline.redisplay()
            _prefill_text = None


# ────────────────────────────────────────────────────────────────────────────
# SESSION YÖNETİMİ
# ────────────────────────────────────────────────────────────────────────────

def ensure_chat_directory():
    os.makedirs(BASE_CHAT_DIR, exist_ok=True)


def list_sessions() -> list:
    ensure_chat_directory()
    sessions = []
    for name in os.listdir(BASE_CHAT_DIR):
        path = os.path.join(BASE_CHAT_DIR, name)
        if os.path.isdir(path):
            sessions.append(name)
    sessions.sort(reverse=True)
    return sessions


def create_new_session(title: str = "Yeni Sohbet") -> str:
    global CURRENT_SESSION, CURRENT_CHAT_DIR
    global HISTORY_FILE, TOKEN_FILE, METADATA_FILE

    ensure_chat_directory()
    session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    chat_dir = os.path.join(BASE_CHAT_DIR, session_id)
    os.makedirs(chat_dir, exist_ok=True)

    HISTORY_FILE  = os.path.join(chat_dir, "history.json")
    TOKEN_FILE    = os.path.join(chat_dir, "token_log.txt")
    METADATA_FILE = os.path.join(chat_dir, "metadata.json")

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=4)

    metadata = {
        "session_id": session_id,
        "created_at": time.time(),
        "title": title,
    }
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=4)

    CURRENT_SESSION  = session_id
    CURRENT_CHAT_DIR = chat_dir
    return session_id


def load_session(session_id: str):
    global CURRENT_SESSION, CURRENT_CHAT_DIR
    global HISTORY_FILE, TOKEN_FILE, METADATA_FILE

    chat_dir = os.path.join(BASE_CHAT_DIR, session_id)
    if not os.path.exists(chat_dir):
        raise FileNotFoundError("Session bulunamadı")

    CURRENT_SESSION  = session_id
    CURRENT_CHAT_DIR = chat_dir
    HISTORY_FILE     = os.path.join(chat_dir, "history.json")
    TOKEN_FILE       = os.path.join(chat_dir, "token_log.txt")
    METADATA_FILE    = os.path.join(chat_dir, "metadata.json")


def load_metadata() -> dict:
    if not METADATA_FILE or not os.path.exists(METADATA_FILE):
        return {}
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_metadata(data: dict):
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def rename_current_session(new_title: str):
    metadata = load_metadata()
    metadata["title"] = new_title
    save_metadata(metadata)


def delete_session(session_id: str):
    path = os.path.join(BASE_CHAT_DIR, session_id)
    if os.path.exists(path):
        shutil.rmtree(path)


# ────────────────────────────────────────────────────────────────────────────
# HISTORY
# ────────────────────────────────────────────────────────────────────────────

def load_history() -> list:
    if HISTORY_FILE and os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return []
    return []


def save_history(history: list):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=4)


# ────────────────────────────────────────────────────────────────────────────
# TOKEN
# ────────────────────────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def estimate_messages_tokens(messages: list) -> int:
    total = estimate_tokens(SYSTEM_PROMPT) + 10
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            # multimodal mesaj: sadece text kısımlarını say
            for part in content:
                if part.get("type") == "text":
                    total += estimate_tokens(part.get("text", "")) + 10
        else:
            total += estimate_tokens(content) + 10
    return total


def trim_history(history: list, budget: int):
    trimmed = False
    while len(history) > 2 and estimate_messages_tokens(history) > budget:
        history = history[2:]
        trimmed = True
    return history, trimmed


def build_messages(history: list) -> list:
    return [{"role": "system", "content": SYSTEM_PROMPT}] + history


def log_tokens(input_tokens: int, output_tokens: int):
    with open(TOKEN_FILE, "a", encoding="utf-8") as f:
        f.write(f"{input_tokens},{output_tokens}\n")


# ────────────────────────────────────────────────────────────────────────────
# SERVER CONTEXT
# ────────────────────────────────────────────────────────────────────────────

def fetch_server_context_size() -> int:
    fallback = 4096

    try:
        url = f"{SERVER_BASE}/props"
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        n_ctx = data.get("n_ctx") or data.get("total_slots", [{}])[0].get("n_ctx")
        if isinstance(n_ctx, int) and n_ctx > 0:
            return n_ctx
    except Exception:
        pass

    try:
        url = f"{SERVER_BASE}/slots"
        with urllib.request.urlopen(url, timeout=3) as resp:
            slots = json.loads(resp.read().decode())
        if isinstance(slots, list) and slots:
            n_ctx = slots[0].get("n_ctx")
            if isinstance(n_ctx, int) and n_ctx > 0:
                return n_ctx
    except Exception:
        pass

    print(f"{YELLOW}⚠ Context size alınamadı. Varsayılan: {fallback}{RESET}")
    return fallback

# ────────────────────────────────────────────────────────────────────────────
# MARKDOWN FORMATTER (STREAM İÇİN CANLI FORMATLAMA)
# ────────────────────────────────────────────────────────────────────────────

class MarkdownFormatter:
    """
    Gelen metin akışını (stream) harf harf işleyerek Terminal ANSI kodlarına
    çeviren yapı. Kod blokları, kalın yazılar, satır içi kodlar vs. için çalışır.
    """
    def __init__(self):
        self.buffer = ""
        self.in_block = False
        self.in_inline = False
        self.in_bold = False
        self.in_heading = False
        self.in_blockquote = False
        self.is_newline = True

    def feed(self, text: str) -> str:
        self.buffer += text
        out = ""

        while self.buffer:
            # 1. Kod Blokları (```)
            if self.buffer.startswith("```"):
                self.in_block = not self.in_block
                if self.in_block:
                    out += f"{RESET}{YELLOW}"  # Kod bloğu içi sarı
                else:
                    out += f"{RESET}"
                    if self.in_bold: out += BOLD
                self.buffer = self.buffer[3:]
                self.is_newline = False
                continue

            # Parçalı geldiyse beklet
            if self.buffer in ("`", "``"):
                break

            if self.in_block:
                char = self.buffer[0]
                out += char
                self.buffer = self.buffer[1:]
                self.is_newline = (char == "\n")
                continue

            # 2. Kalın Yazı (**)
            if self.buffer.startswith("**"):
                self.in_bold = not self.in_bold
                out += BOLD if self.in_bold else BOLD_RESET
                self.buffer = self.buffer[2:]
                self.is_newline = False
                continue

            if self.buffer == "*":
                break

            # 3. Satır İçi Kod (`)
            if self.buffer.startswith("`"):
                self.in_inline = not self.in_inline
                if self.in_inline:
                    out += f"{RESET}{CYAN}"  # Satır içi kod turkuaz
                else:
                    out += f"{RESET}"
                    if self.in_bold: out += BOLD
                self.buffer = self.buffer[1:]
                self.is_newline = False
                continue

            # 4. Başlıklar (#)
            if self.is_newline and self.buffer.startswith("#"):
                idx = 0
                while idx < len(self.buffer) and self.buffer[idx] == "#":
                    idx += 1

                if idx < len(self.buffer) and self.buffer[idx] == " ":
                    out += f"{BOLD}{CYAN}" + self.buffer[:idx+1]
                    self.buffer = self.buffer[idx+1:]
                    self.is_newline = False
                    self.in_heading = True
                    continue
                elif idx == len(self.buffer):
                    break

            # 5. Alıntılar (>)
            if self.is_newline and self.buffer.startswith(">"):
                if len(self.buffer) > 1 and self.buffer[1] == " ":
                    out += f"{DIM}> "
                    self.buffer = self.buffer[2:]
                    self.is_newline = False
                    self.in_blockquote = True
                    continue
                elif len(self.buffer) == 1:
                    break

            # Normal Karakter İşleme
            char = self.buffer[0]

            if char == "\n":
                self.is_newline = True
                if self.in_heading or self.in_blockquote:
                    out += f"{RESET}"
                    if self.in_bold: out += BOLD
                    self.in_heading = False
                    self.in_blockquote = False
            else:
                self.is_newline = False

            out += char
            self.buffer = self.buffer[1:]

        return out

    def flush(self) -> str:
        out = self.buffer
        if self.in_bold or self.in_block or self.in_heading or self.in_inline or self.in_blockquote:
            out += f"{RESET}"
        self.buffer = ""
        return out


# ────────────────────────────────────────────────────────────────────────────
# THINKING STREAM PARSER
# ────────────────────────────────────────────────────────────────────────────

class ThinkingStreamParser:

    TAG_OPEN  = "<think>"
    TAG_CLOSE = "</think>"

    def __init__(self):
        self.in_thinking       = False
        self.thinking_started  = False
        self.think_footer_done = False
        self.response_started  = False

        self.buffer        = ""
        self.thinking_text = ""
        self.response_text = ""

        self.md_formatter  = MarkdownFormatter()

    def feed_thinking(self, text: str):
        if not text:
            return
        if not self.thinking_started:
            self._print_think_header()
        self._emit_thinking(text)

    def feed_content(self, text: str):
        if not text:
            return
        self.buffer += text
        self._process()

    def flush(self):
        if self.buffer:
            if self.in_thinking:
                self._emit_thinking(self.buffer)
            else:
                self._emit_response(self.buffer)
            self.buffer = ""

        # Formatlayıcıda kalan son karakterleri ve renk sıfırlamalarını yazdır
        leftover = self.md_formatter.flush()
        if leftover:
            print(leftover, end="", flush=True)
        print(RESET, end="", flush=True)

    def _process(self):
        while True:
            if not self.in_thinking:
                idx = self.buffer.find(self.TAG_OPEN)
                if idx == -1:
                    safe = self._safe_len(self.TAG_OPEN)
                    if safe > 0:
                        self._emit_response(self.buffer[:safe])
                        self.buffer = self.buffer[safe:]
                    break
                else:
                    if idx > 0:
                        self._emit_response(self.buffer[:idx])
                    self.buffer = self.buffer[idx + len(self.TAG_OPEN):]
                    self.in_thinking = True
                    if not self.thinking_started:
                        self._print_think_header()
            else:
                idx = self.buffer.find(self.TAG_CLOSE)
                if idx == -1:
                    safe = self._safe_len(self.TAG_CLOSE)
                    if safe > 0:
                        self._emit_thinking(self.buffer[:safe])
                        self.buffer = self.buffer[safe:]
                    break
                else:
                    if idx > 0:
                        self._emit_thinking(self.buffer[:idx])
                    self.buffer = self.buffer[idx + len(self.TAG_CLOSE):]
                    self.in_thinking = False
                    self._print_think_footer()

    def _safe_len(self, tag: str) -> int:
        return max(0, len(self.buffer) - len(tag) + 1)

    def _emit_response(self, text: str):
        if not text:
            return
        if self.thinking_started and not self.think_footer_done:
            self._print_think_footer()
        if not self.response_started:
            print(f"\n{CYAN}Ajan:{RESET} ", end="", flush=True)
            self.response_started = True

        # Ham (markdown) metni veritabanı/history için temiz şekilde kaydet
        self.response_text += text

        # Ekran için anında formatla ve yazdır
        formatted_text = self.md_formatter.feed(text)
        print(formatted_text, end="", flush=True)

    def _emit_thinking(self, text: str):
        if not text:
            return
        print(f"{DIM}{YELLOW}{text}{RESET}", end="", flush=True)
        self.thinking_text += text

    def _print_think_header(self):
        print(f"\n{DIM}{YELLOW}💭 Düşünüyor...{RESET}")
        self.thinking_started = True

    def _print_think_footer(self):
        print(f"\n{DIM}{'─' * 40}{RESET}")
        self.think_footer_done = True


# ────────────────────────────────────────────────────────────────────────────
# UTIL
# ────────────────────────────────────────────────────────────────────────────

def print_token_stats(input_tok: int, output_tok: int, elapsed: float, estimated: bool = False):
    tilde = "~" if estimated else ""
    src   = "(tahmini)" if estimated else "(server)"
    rate  = f"{output_tok / elapsed:.1f} tok/s" if elapsed > 0 else "— tok/s"
    print(
        f"{DIM}"
        f"↳ {tilde}giriş: {input_tok:,} tok │ "
        f"çıkış: {output_tok:,} tok │ "
        f"toplam: {input_tok + output_tok:,} tok │ "
        f"{RESET}{GREEN}{rate}{RESET} "
        f"{DIM}{src}{RESET}"
    )


def clean_response(text: str) -> str:
    artifacts = [
        "user><answer>", "<answer>", "</answer>",
        "user>", "<|assistant|>", "<|im_start|>", "<|im_end|>",
    ]
    for artifact in artifacts:
        text = text.replace(artifact, "")
    return text.strip()


def print_context_bar(used: int, maximum: int):
    ratio  = min(used / maximum, 1.0)
    width  = 28
    filled = int(width * ratio)
    bar    = "█" * filled + "░" * (width - filled)
    color  = GREEN if ratio < 0.60 else YELLOW if ratio < 0.85 else RED
    print(
        f"{DIM}ctx [{color}{bar}{RESET}{DIM}] "
        f"{used:,}/{maximum:,} tok ({ratio*100:.1f}%){RESET}"
    )


def print_help():
    cmds = [
        ("/new",            "Yeni sohbet oluştur"),
        ("/chats",          "Sohbetleri listele"),
        ("/open N",         "Sohbet aç"),
        ("/rename",         "Aktif sohbeti yeniden adlandır"),
        ("/delete N",       "Sohbet sil"),
        ("/clear",          "Aktif sohbeti temizle"),
        ("/stats",          "İstatistik göster"),
        ("/debug",          "Debug aç/kapat"),
        ("─── Medya ─────", ""),
        ("/ses",            "Mikrofonu kaydet ve belleğe al"),
        ("/ses <dosya>",    "Ses dosyasını çevir ve belleğe al (.wav)"),
        ("/read <dosya>",   "Dosyayı oku ve belleğe al (veya /dosya)"),
        ("/resim <dosya>",  "Resmi belleğe al (vision model gerekir)"),
        ("─────────────",  ""),
        ("/help",           "Yardım menüsü"),
        ("q/quit",          "Çıkış"),
    ]
    print(f"\n{CYAN}── Komutlar ─────────────────────────{RESET}")
    for cmd, desc in cmds:
        if cmd.startswith("─"):
            print(f"{DIM}{cmd}{RESET}")
        else:
            print(f"{GREEN}{cmd:<20}{RESET} {desc}")
    print()
    print(f"{DIM}Whisper pipe: whisper_dinle.sh çalıştır →")
    print(f"  main.py'ye Enter'a basarak aktar{RESET}\n")


# ────────────────────────────────────────────────────────────────────────────
# STREAM HANDLER (ortak fonksiyon)
# ────────────────────────────────────────────────────────────────────────────

def do_stream_and_respond(messages: list, history: list) -> int:
    """
    Verilen mesajları modele gönderir, stream'i işler, yanıtı history'ye ekler.
    Yeni actual_context_tokens değerini döner; hata durumunda 0 döner.
    """
    try:
        response = client.chat.completions.create(
            model=agent_model,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            extra_body={
                "chat_template_kwargs": {
                    "enable_thinking": True,
                    "reasoning_effort": "xhigh",
                }
            },
            #reasoning_effort="xhigh",  # xhigh by default; supported levels are xhigh, medium, and low
            #stream_options={"include_usage": True},
        )

        parser = ThinkingStreamParser()
        input_tokens  = 0
        output_tokens = 0
        t_first_output = None

        for chunk in response:
            if hasattr(chunk, "usage") and chunk.usage:
                input_tokens  = chunk.usage.prompt_tokens or 0
                output_tokens = chunk.usage.completion_tokens or 0

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            if not delta:
                continue

            if DEBUG:
                with open("debug.log", "a", encoding="utf-8") as dbg:
                    dbg.write(repr(chunk) + "\n")

            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                if t_first_output is None:
                    t_first_output = time.monotonic()
                parser.feed_thinking(reasoning)

            if delta.content:
                prev_len = len(parser.response_text) + len(parser.thinking_text)
                parser.feed_content(delta.content)
                if t_first_output is None and (
                    len(parser.response_text) + len(parser.thinking_text) > prev_len
                ):
                    t_first_output = time.monotonic()

        parser.flush()

        if parser.thinking_started and not parser.think_footer_done:
            parser._print_think_footer()

        print("\n")

        t_stream_end   = time.monotonic()
        elapsed_output = (t_stream_end - t_first_output) if t_first_output else 0.0

        estimated = input_tokens == 0 and output_tokens == 0
        if estimated:
            input_tokens  = estimate_messages_tokens(history[:-1])
            output_tokens = estimate_tokens(parser.response_text + parser.thinking_text)

        print_token_stats(input_tokens, output_tokens, elapsed_output, estimated)
        print()

        log_tokens(input_tokens, output_tokens)

        assistant_message = clean_response(parser.response_text)
        history.append({"role": "assistant", "content": assistant_message})
        save_history(history)

        return input_tokens + output_tokens

    except Exception as e:
        print(f"\n{RED}[Hata]{RESET}: {e}\n")
        return 0


# ────────────────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────────────────

def main():
    global DEBUG, MAX_CONTEXT_TOKENS

    ensure_chat_directory()

    sessions = list_sessions()
    if sessions:
        load_session(sessions[0])
    else:
        create_new_session()

    history = load_history()

    # Bellekte bekleyen medyalar için durum değişkenleri
    pending_text_attachments = []
    pending_vision_msg = None
    pending_vision_path = None

    # ── Pipe watcher başlat ────────────────────────────────────────────────
    pipe_thread = threading.Thread(target=_pipe_watcher, daemon=True)
    pipe_thread.start()

    if HAS_READLINE:
        readline.set_pre_input_hook(_readline_prefill_hook)

    # ── Server bilgileri ───────────────────────────────────────────────────
    print(f"\n🔍 Server bilgileri alınıyor...", end=" ")
    MAX_CONTEXT_TOKENS = fetch_server_context_size()
    print(f"{GREEN}✓{RESET} n_ctx={MAX_CONTEXT_TOKENS:,}")

    effective_budget    = int(MAX_CONTEXT_TOKENS * 0.85)
    actual_context_tokens = estimate_messages_tokens(history)

    metadata = load_metadata()
    title    = metadata.get("title", CURRENT_SESSION)

    print(f"\n🤖 {CYAN}Yapay Zeka Ajanı{RESET}")
    print(f"{DIM}   Aktif sohbet : {title}{RESET}")
    print(f"{DIM}   Session      : {CURRENT_SESSION}{RESET}")
    print(f"{DIM}   Max context  : {MAX_CONTEXT_TOKENS:,} token")
    print(f"   Güvenlik payı: {int(MAX_CONTEXT_TOKENS * 0.85):,} token")
    print(f"   Whisper pipe : {PIPE_PATH}")
    print(f"   /help yazarak komutları görebilirsiniz{RESET}\n")

    # ── Ana döngü ─────────────────────────────────────────────────────────
    while True:

        used_tokens = actual_context_tokens
        print_context_bar(used_tokens, MAX_CONTEXT_TOKENS)

        # Bekleyen ekler varsa kullanıcıyı bilgilendir
        if pending_text_attachments or pending_vision_msg:
            count = len(pending_text_attachments) + (1 if pending_vision_msg else 0)
            print(f"{DIM}📎 {count} ek bellekte bekliyor. Sorunuzu yazın veya Enter ile gönderin.{RESET}")

        try:
            user_input = input(f"{GREEN}Sen:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nÇıkış yapılıyor...")
            break

        if user_input.lower() in ("q", "quit"):
            print("Çıkış yapılıyor...")
            break

        # ────────────────────────────────────────────────────────────────
        # NEW CHAT
        # ────────────────────────────────────────────────────────────────

        if user_input == "/new":
            session_id = create_new_session()
            history = []
            actual_context_tokens = 0
            pending_text_attachments = []
            pending_vision_msg = None
            pending_vision_path = None
            print(f"{GREEN}✓ Yeni sohbet oluşturuldu:{RESET} {session_id}\n")
            continue

        # ────────────────────────────────────────────────────────────────
        # LIST CHATS
        # ────────────────────────────────────────────────────────────────

        if user_input == "/chats":
            sessions = list_sessions()
            print()
            for idx, session in enumerate(sessions):
                load_session(session)
                metadata = load_metadata()
                title    = metadata.get("title", "Başlıksız")
                history_preview = load_history()
                last_message = ""
                if history_preview:
                    last_message = history_preview[-1].get("content", "")[:80]
                print(f"[{idx}] {title}")
                print(f"    {DIM}{session}{RESET}")
                if last_message:
                    print(f"    Son mesaj: {last_message}")
                print()
            load_session(CURRENT_SESSION)
            continue

        # ────────────────────────────────────────────────────────────────
        # OPEN CHAT
        # ────────────────────────────────────────────────────────────────

        if user_input.startswith("/open"):
            parts = user_input.split()
            if len(parts) != 2:
                print("Kullanım: /open <index>")
                continue
            sessions = list_sessions()
            try:
                idx        = int(parts[1])
                session_id = sessions[idx]
            except Exception:
                print(f"{RED}Geçersiz index{RESET}\n")
                continue
            load_session(session_id)
            history = load_history()
            actual_context_tokens = estimate_messages_tokens(history)
            metadata = load_metadata()
            title    = metadata.get("title", session_id)
            pending_text_attachments = []
            pending_vision_msg = None
            pending_vision_path = None
            print(f"{GREEN}✓ Sohbet açıldı:{RESET} {title}\n")
            continue

        # ────────────────────────────────────────────────────────────────
        # RENAME
        # ────────────────────────────────────────────────────────────────

        if user_input.startswith("/rename"):
            new_title = user_input.replace("/rename", "").strip()
            if not new_title:
                print("Kullanım: /rename Yeni Başlık")
                continue
            rename_current_session(new_title)
            print(f"{GREEN}✓ Yeni başlık:{RESET} {new_title}\n")
            continue

        # ────────────────────────────────────────────────────────────────
        # DELETE
        # ────────────────────────────────────────────────────────────────

        if user_input.startswith("/delete"):
            parts = user_input.split()
            if len(parts) != 2:
                print("Kullanım: /delete <index>")
                continue
            sessions = list_sessions()
            try:
                idx        = int(parts[1])
                session_id = sessions[idx]
            except Exception:
                print("Geçersiz index")
                continue
            delete_session(session_id)
            print(f"{GREEN}✓ Silindi:{RESET} {session_id}\n")
            sessions = list_sessions()
            if sessions:
                load_session(sessions[0])
                history = load_history()
            else:
                create_new_session()
                history = []
            actual_context_tokens = estimate_messages_tokens(history)
            continue

        # ────────────────────────────────────────────────────────────────
        # CLEAR
        # ────────────────────────────────────────────────────────────────

        if user_input == "/clear":
            history = []
            actual_context_tokens = 0
            save_history(history)
            pending_text_attachments = []
            pending_vision_msg = None
            pending_vision_path = None
            print(f"{YELLOW}✓ Sohbet ve ekler temizlendi{RESET}\n")
            continue

        # ────────────────────────────────────────────────────────────────
        # DEBUG
        # ────────────────────────────────────────────────────────────────

        if user_input == "/debug":
            DEBUG = not DEBUG
            state = "AÇIK" if DEBUG else "KAPALI"
            print(f"Debug: {state}\n")
            continue

        # ────────────────────────────────────────────────────────────────
        # HELP
        # ────────────────────────────────────────────────────────────────

        if user_input == "/help":
            print_help()
            continue

        # ────────────────────────────────────────────────────────────────
        # STATS
        # ────────────────────────────────────────────────────────────────

        if user_input == "/stats":
            total_input  = 0
            total_output = 0
            if os.path.exists(TOKEN_FILE):
                with open(TOKEN_FILE, encoding="utf-8") as f:
                    for line in f:
                        parts = line.strip().split(",")
                        if len(parts) == 2:
                            try:
                                total_input  += int(parts[0])
                                total_output += int(parts[1])
                            except Exception:
                                pass
            metadata = load_metadata()
            print(f"\n{CYAN}── İstatistikler ───────────────────────{RESET}")
            print(f"Sohbet : {metadata.get('title', CURRENT_SESSION)}")
            print(f"Mesaj  : {len(history)}")
            print(f"Context: {actual_context_tokens:,}")
            print(f"Input  : {total_input:,}")
            print(f"Output : {total_output:,}\n")
            continue

        # ════════════════════════════════════════════════════════════════
        # SES → METİN (/ses veya /ses <dosya>) YÜKLE
        # ════════════════════════════════════════════════════════════════

        if user_input.startswith("/ses"):
            parts = user_input.split(maxsplit=1)
            audio_path = parts[1].strip() if len(parts) > 1 else None

            try:
                if audio_path:
                    transcribed = whisper_transcribe(audio_path)
                else:
                    transcribed = record_and_transcribe()
            except Exception as e:
                print(f"{RED}❌ Ses hatası:{RESET} {e}\n")
                continue

            if not transcribed:
                print(f"{RED}❌ Ses algılanamadı veya çeviri boş{RESET}\n")
                continue

            # Çeviriyi bekleyen eklere al
            pending_text_attachments.append(f"--- Ses Metni ---\n{transcribed}\n")

            if audio_path:
                print(f"\nLoaded audio transcription from '{audio_path}'\n")
            else:
                print(f"\nLoaded audio transcription from microphone\n")
            continue

        # ════════════════════════════════════════════════════════════════
        # DOSYA YÜKLE (/read veya /dosya)
        # ════════════════════════════════════════════════════════════════

        elif user_input.startswith("/read") or user_input.startswith("/dosya"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                print("Kullanım: /read <dosya.txt>\n")
                continue

            file_path = parts[1].strip()
            try:
                content = read_text_file(file_path)
            except Exception as e:
                print(f"{RED}❌ Dosya hatası:{RESET} {e}\n")
                continue

            # Dosyayı bekleyen eklere al
            pending_text_attachments.append(f"--- Dosya: {os.path.basename(file_path)} ---\n{content}\n")
            print(f"\nLoaded text from '{file_path}'\n")
            continue

        # ════════════════════════════════════════════════════════════════
        # RESİM YÜKLE (/resim)
        # ════════════════════════════════════════════════════════════════

        elif user_input.startswith("/resim"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                print("Kullanım: /resim <resim_dosyası>\n")
                continue

            img_path = parts[1].strip()

            try:
                b64_data, mime_type = encode_image_b64(img_path)
            except Exception as e:
                print(f"{RED}❌ Resim hatası:{RESET} {e}\n")
                continue

            # Resmi bekleme moduna al (1 resimlik slot kullanıyoruz)
            pending_vision_msg = {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64_data}"},
                    },
                    {"type": "text", "text": ""}, # Yazı daha sonra eklenecek
                ],
            }
            pending_vision_path = img_path
            print(f"\nLoaded image from '{img_path}'\n")
            continue

        # ────────────────────────────────────────────────────────────────
        # Boş giriş kontrolü
        # (Bekleyen içerik yoksa atla, varsa normal chat'e devam et)
        # ────────────────────────────────────────────────────────────────

        if not user_input and not pending_text_attachments and not pending_vision_msg:
            continue

        # ════════════════════════════════════════════════════════════════
        # NORMAL CHAT & İÇERİKLERİ BİRLEŞTİRİP GÖNDERME
        # ════════════════════════════════════════════════════════════════

        final_text = ""

        # Varsa bellekteki metin dosyalarını/sesleri ekle
        if pending_text_attachments:
            final_text += "\n\n".join(pending_text_attachments) + "\n\n"

        # Kullanıcının sorusunu ekle
        if user_input:
            final_text += user_input
        else:
            final_text += "Lütfen ekteki içeriği detaylıca incele."

        final_text = final_text.strip()

        # EĞER RESİM VARSA (Multimodal Process)
        if pending_vision_msg:
            pending_vision_msg["content"][1]["text"] = final_text

            # Text geçmişine sadece özetini kaydediyoruz
            history_label = f"[Resim: {os.path.basename(pending_vision_path)}] {user_input if user_input else 'İnceleme talebi'}"
            history.append({"role": "user", "content": history_label})

            messages = build_messages(history[:-1]) + [pending_vision_msg]

            new_ctx = do_stream_and_respond(messages, history)
            if new_ctx:
                actual_context_tokens = new_ctx
            elif history and history[-1]["role"] == "user":
                history.pop()

            # Gönderim tamamlandıktan sonra ekleri temizle
            pending_vision_msg = None
            pending_vision_path = None
            pending_text_attachments = []
            continue

        # NORMAL METİN (Resim Yoksa)
        history.append({"role": "user", "content": final_text})

        # Gönderildiği için belleği temizle
        pending_text_attachments = []

        was_trimmed = False

        if actual_context_tokens is not None:
            projected = actual_context_tokens + estimate_tokens(final_text) + 10
            while len(history) > 2 and projected > effective_budget:
                removed = (
                    estimate_tokens(history[0].get("content", ""))
                    + estimate_tokens(history[1].get("content", ""))
                    + 20
                )
                history    = history[2:]
                projected  = max(0, projected - removed)
                was_trimmed = True
        else:
            history, was_trimmed = trim_history(history, effective_budget)

        if was_trimmed:
            print(f"{YELLOW}⚠ Context kırpıldı{RESET}")

        messages = build_messages(history)

        new_ctx = do_stream_and_respond(messages, history)
        if new_ctx:
            actual_context_tokens = new_ctx
        else:
            # Hata durumunda son user mesajını geri al
            if history and history[-1]["role"] == "user":
                history.pop()


if __name__ == "__main__":
    main()

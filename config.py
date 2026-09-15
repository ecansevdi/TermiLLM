import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    server_base: str
    api_base_url: str
    api_key: str
    agent_model: str

    whisper_bin: str
    whisper_model: str
    whisper_lang: str

    pipe_path: str
    chat_directory: str
    context_fallback: int
    context_safety_ratio: float
    context_provider: str
    system_prompt: str


def load_config() -> Config:
    return Config(
        server_base=os.getenv("SERVER_BASE"),
        api_base_url=os.getenv("base_url"),
        api_key=os.getenv("api_key"),
        agent_model=os.getenv("agent_model"),
        whisper_bin=os.environ.get("WHISPER_BIN", "whisper-cli"),
        whisper_model=os.environ.get(
            "WHISPER_MODEL",
            os.path.expanduser("~/whisper.cpp/models/ggml-base.bin"),
        ),
        whisper_lang=os.environ.get("WHISPER_LANG", "tr"),
        pipe_path=os.environ.get("LLAMA_PIPE", "/tmp/llama_input.pipe"),
        chat_directory="chats",
        context_fallback=int(os.environ.get("CONTEXT_FALLBACK", "4096")),
        context_safety_ratio=0.85,
        context_provider=os.environ.get("CONTEXT_PROVIDER", "").strip().lower(),
        system_prompt=(
            "Türkçe sorulara Türkçe, İngilizce sorulara İngilizce yanıt verirsin. "
            "Cevapların net, kısa ve bilgi odaklıdır.\n"
            "Web arama aracın var: güncel veya zamana bağlı bilgi (haber, fiyat, "
            "sürüm, tarih vb.) gerektiren ya da emin olmadığın konularda "
            "<web_search>arama sorgusu</web_search> etiketini yazarak arama yap. "
            "Etiketi yazdıktan sonra başka bir şey yazma; sonuçlar sana ayrı bir "
            "mesajla iletilecek. Sonuçlar yetersizse yeni bir arama daha "
            "yapabilirsin. Yeterli bilgiye sahipsen arama yapmadan doğrudan "
            "yanıtla. Arama sonuçlarına dayanırken kaynak URL'leri belirt."
        ),
    )

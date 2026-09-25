"""Konfigürasyon: TOML dosyası (~/.config/termillm/config.toml).

".env" KALDIRILDI. Modern CLI standardına geçildi (git/cargo/pip gibi):
  * Dosya proje dizini yerine XDG konfig dizininde — yanlışlıkla git'e
    girme riski yok, python-dotenv bağımlılığı kaldırıldı.
  * Yapı:
        active = "local"
        [providers.local]
        base_url = "http://127.0.0.1:8080/v1"
        api_key  = "enc1:..."   # şifreli (encrypt_key) veya düz metin
        model    = "Bonsai-2"
  * İlk çalıştırmada eski '.env' VARSAYA Otomatik içe aktarılır (ana
    değerler + p<n>_ sağlayıcı kayıtları, ${VAR} genişletmesi dahil) ve
    '.env' dosyası silinir.
  * API key'ler 'enc1:' önekiyle ŞİFRELİ tutulur (aşağıda); 'enc1:' öneki
    olmayan değerler eski düz metin gibi kabul edilir (geriye dönük).
"""

import base64
import hashlib
import json
import os
import tomllib
from dataclasses import dataclass

APP_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "termillm",
)
CONFIG_FILE = os.path.join(APP_DIR, "config.toml")
LEGACY_ENV_FILE = ".env"

# ---------------------------------------------------------------------- #
# API key şifreleme: Fernet (cryptography varsa) veya XOR+SHA256 akışı.
# Amaç: config'de anahtar DÜZ METİN durmasın; makineye bağlı gizli ile
# şifrelenir — dosya başka makinede anlamsızdır.
# ---------------------------------------------------------------------- #
_SECRET_SALT_FILE = os.path.join(os.path.expanduser("~"), ".termillm_salt")


def _machine_secret() -> bytes:
    """Makineye bağlı gizli: salt dosyası + makine kimliği + kullanıcı."""
    try:
        with open(_SECRET_SALT_FILE, "rb") as f:
            salt = f.read()
    except FileNotFoundError:
        salt = os.urandom(32)
        try:
            with open(_SECRET_SALT_FILE, "wb") as f:
                f.write(salt)
            os.chmod(_SECRET_SALT_FILE, 0o600)
        except Exception:
            salt = b"termillm-static-salt"
    uid = f"{os.getuid()}|{os.uname().nodename}|termillm".encode()
    return hashlib.sha256(salt + uid).digest()


def encrypt_key(plain: str) -> str:
    """API key'i şifreler: 'enc1:<fernet|x:b64>' biçiminde döner."""
    if not plain:
        return ""
    if plain.startswith("enc1:"):
        return plain                      # zaten şifreli
    key32 = _machine_secret()
    try:
        from cryptography.fernet import Fernet
        f = Fernet(base64.urlsafe_b64encode(key32))
        return "enc1:" + f.encrypt(plain.encode()).decode()
    except Exception:
        stream = key32
        out = bytearray()
        for i, ch in enumerate(plain.encode()):
            if i >= len(stream):
                stream = hashlib.sha256(stream).digest()
            out.append(ch ^ stream[i % len(stream)])
        return "enc1:x:" + base64.b64encode(bytes(out)).decode()


def decrypt_key(token: str) -> str:
    """'enc1:' önekli değeri çözer; önek yoksa düz metin döner (eski kayıt)."""
    if not token:
        return ""
    if not token.startswith("enc1:"):
        return token
    key32 = _machine_secret()
    if token.startswith("enc1:x:"):
        try:
            data = bytearray(base64.b64decode(token[7:]))
            stream = key32
            for i in range(len(data)):
                if i >= len(stream):
                    stream = hashlib.sha256(stream).digest()
                data[i] ^= stream[i % len(stream)]
            return bytes(data).decode()
        except Exception:
            return "<undecryptable>"
    try:
        from cryptography.fernet import Fernet
        f = Fernet(base64.urlsafe_b64encode(key32))
        return f.decrypt(token[5:].encode()).decode()
    except Exception:
        # Bu makinede çözülemedi (bozuk kayıt / başka makineden taşınan
        # dosya): çökmemek için placeholder dön.
        return "<undecryptable>"


# ---------------------------------------------------------------------- #
# Popüler OpenAI-uyumlu sağlayıcılar: yalnızca API key girilir; base URL
# listeden gelir. (Base URL'ler sağlayıcı dokümantasyonlarından doğrulandı.)
# ---------------------------------------------------------------------- #
API_PROVIDERS = [
    ("OpenRouter",     "https://openrouter.ai/api/v1"),
    ("Cerebras",       "https://api.cerebras.ai/v1"),
    ("Groq",           "https://api.groq.com/openai/v1"),
    ("Together AI",    "https://api.together.xyz/v1"),
    ("Mistral AI",     "https://api.mistral.ai/v1"),
    ("DeepSeek",       "https://api.deepseek.com/v1"),
    ("xAI (Grok)",     "https://api.x.ai/v1"),
    ("Fireworks AI",   "https://api.fireworks.ai/inference/v1"),
    ("OpenAI",         "https://api.openai.com/v1"),
    ("Gemini",         "https://generativelanguage.googleapis.com/v1beta/openai/"),
    ("Claude",         "https://api.anthropic.com/v1"),
    ("OpenCode Zen",   "https://opencode.ai/zen/v1"),
    ("OpenCode Go",    "https://opencode.ai/zen/go/v1"),
    ("Ollama (local)", "http://127.0.0.1:11434/v1"),
    ("LM Studio",      "http://127.0.0.1:1234/v1"),
]


# ---------------------------------------------------------------------- #
# Config veri sınıfı (alanlar eski API ile aynı kalır)
# ---------------------------------------------------------------------- #

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
    provider_selection: str = ""
    reasoning_api: str = "auto"   # auto|llamacpp|openai|openrouter|anthropic|none


# ---------------------------------------------------------------------- #
# TOML okuma/yazma
# ---------------------------------------------------------------------- #

def _toml_str(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _load_toml() -> dict:
    try:
        with open(CONFIG_FILE, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def _save_toml(active: str, providers: dict) -> None:
    os.makedirs(APP_DIR, exist_ok=True)
    lines = [f"active = {_toml_str(active)}", ""]
    for name, p in providers.items():
        lines += [
            f"[providers.{name}]",
            f"base_url = {_toml_str(p.get('base_url', ''))}",
            f"api_key = {_toml_str(encrypt_key(p.get('api_key', '')))}",
            f"model = {_toml_str(p.get('model', ''))}",
            "",
        ]
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _decrypt_provider(p: dict) -> dict:
    return {
        "base_url": p.get("base_url", ""),
        "api_key": decrypt_key(p.get("api_key", "")),
        "model": p.get("model", ""),
    }


# ---------------------------------------------------------------------- #
# ".env" → TOML migration (tek seferlik, ilk açılışta)
# ---------------------------------------------------------------------- #

def _parse_legacy_env(path: str) -> dict:
    pairs: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                pairs[k.strip()] = v.strip().strip("'\"")
    except FileNotFoundError:
        return {}
    # ${VAR} genişletmesi: dosyadaki önceki değerler + ortam değişkenleri
    def expand(val: str) -> str:
        out, i = [], 0
        while i < len(val):
            if val.startswith("${", i):
                j = val.find("}", i)
                if j != -1:
                    name = val[i + 2:j]
                    out.append(pairs.get(name) or os.environ.get(name, ""))
                    i = j + 1
                    continue
            out.append(val[i])
            i += 1
        return "".join(out)
    return {k: expand(v) for k, v in pairs.items()}


def _migrate_legacy_env() -> bool:
    """'.env' varsa TOML'a taşır ve dosyayı siler. Taşındıysa True."""
    if not os.path.exists(LEGACY_ENV_FILE):
        return False
    env = _parse_legacy_env(LEGACY_ENV_FILE)
    providers: dict[str, dict] = {}
    if env.get("base_url"):
        providers["local"] = {
            "base_url": env["base_url"],
            "api_key": env.get("api_key", ""),
            "model": env.get("agent_model", ""),
        }
    for key, val in env.items():
        m = __import__("re").match(r"^(p\d+)_base_url$", key)
        if not m:
            continue
        name = m.group(1)
        providers[name] = {
            "base_url": val,
            "api_key": env.get(f"{name}_api_key", ""),
            "model": env.get(f"{name}_agent_model", ""),
        }
    if not providers:
        os.remove(LEGACY_ENV_FILE)
        return False
    sel = env.get("provider_selection", "")
    active = sel if sel in providers else next(iter(providers))
    _save_toml(active, providers)
    os.remove(LEGACY_ENV_FILE)
    return True


# ---------------------------------------------------------------------- #
# Provider kayıt API'si (eski fonksiyon adları/semantiği korunur)
# ---------------------------------------------------------------------- #

def providers() -> dict[str, dict]:
    """Tüm kayıtlar: {ad: {base_url, api_key(ÇÖZÜLMÜŞ), model}}."""
    data = _load_toml()
    return {name: _decrypt_provider(p)
            for name, p in data.get("providers", {}).items()}


def get_provider(name: str) -> tuple[str, str, str]:
    p = providers().get(name, {})
    return p.get("base_url", ""), p.get("api_key", ""), p.get("model", "")


def active_name() -> str:
    return _load_toml().get("active", "")


def _next_provider_name(existing: set) -> str:
    n = 1
    while f"p{n}" in existing:
        n += 1
    return f"p{n}"


def set_active(name: str, model: str = None) -> None:
    """Aktif sağlayıcıyı (ve opsiyonel modelini) kalıcı seçer."""
    data = _load_toml()
    provs = data.get("providers", {})
    if name in provs and model is not None:
        provs[name]["model"] = model
    _save_toml(name if name in provs else data.get("active", ""), provs)


def upsert_provider_key(base_url: str, api_key: str) -> tuple[str, bool]:
    """Base URL eşleşen kaydın yalnızca key'ini günceller; yoksa yeni kayıt.

    Yeni kayıt AKTİF EDİLMEZ: model henüz seçilmemiştir; model seçimi
    'Select Provider' ekranından yapılır. Dönen değer: (kayıt adı, yeni mi).
    """
    data = _load_toml()
    provs = data.get("providers", {})
    norm = base_url.rstrip("/")
    for name, p in provs.items():
        if p.get("base_url", "").rstrip("/") == norm:
            p["api_key"] = encrypt_key(api_key)   # yalnız key; model/aktif dokunulmaz
            _save_toml(data.get("active", ""), provs)
            return name, False
    name = _next_provider_name(set(provs))
    provs[name] = {"base_url": base_url, "api_key": encrypt_key(api_key),
                   "model": ""}
    _save_toml(data.get("active", ""), provs)
    return name, True


def save_api_values(base_url: str, api_key: str, agent_model: str,
                    name: str = None) -> str:
    """Kaydı yazar/yeniler ve AKTİF eder ('Enter API' akışı)."""
    data = _load_toml()
    provs = data.get("providers", {})
    if not name:
        norm = base_url.rstrip("/")
        for n, p in provs.items():
            if p.get("base_url", "").rstrip("/") == norm:
                name = n
                break
        else:
            name = _next_provider_name(set(provs))
    provs[name] = {"base_url": base_url, "api_key": encrypt_key(api_key),
                   "model": agent_model}
    _save_toml(name, provs)
    return name


def delete_provider(name: str) -> str:
    """Kaydı tamamen siler.

    Silinen aktifse kalan ilk kayda geçilir (adı döner); hiç kayıt
    kalmazsa boş string döner.
    """
    data = _load_toml()
    provs = data.get("providers", {})
    active = data.get("active", "")
    provs.pop(name, None)
    if active == name:
        active = next(iter(provs), "")
    _save_toml(active, provs)
    return active


def fetch_models(base_url: str, api_key: str) -> list[str]:
    """GET {base}/models — OpenAI-uyumlu sağlayıcılardan model kimlikleri."""
    import urllib.request
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {api_key or '-'}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    ids = [m.get("id", "") for m in data.get("data", [])]
    return sorted(i for i in ids if i)


# ---------------------------------------------------------------------- #
# Yükleme
# ---------------------------------------------------------------------- #

def load_config() -> Config:
    _migrate_legacy_env()
    data = _load_toml()
    provs = data.get("providers", {})
    active = data.get("active", "")
    if active not in provs and provs:
        active = next(iter(provs))
    p = _decrypt_provider(provs.get(active, {}))

    base_url = p.get("base_url", "")
    # server_base: eski alan korunur — base_url'in /v1'siz hali
    server_base = base_url.removesuffix("/v1").rstrip("/")

    return Config(
        server_base=server_base,
        api_base_url=base_url,
        api_key=p.get("api_key", ""),
        agent_model=p.get("model", ""),
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
        provider_selection=active,
        reasoning_api=(data.get("reasoning_api") or "auto").strip().lower(),
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

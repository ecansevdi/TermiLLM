"""Capability-driven reasoning (effort) yapılandırması.

Amaç: Ctrl+P ile seçilen canonical effort seviyesinin, aktif
`provider + model + API türü`ne göre request'e DOĞRU alan olarak eklenmesi.

Eski yaklaşım (llama.cpp'e özgü `chat_template_kwargs`'ı host kara
listesine göre göndermek) kaldırıldı; provider'a özel davranış tek yerde,
bu modülde toplanır. Kodun geri kalanı yalnızca
`resolve_reasoning_config(...)` çağırır.

Canonical seviyeler: none, minimal, low, medium, high, xhigh, max.

Kurallar (instruction.md ile birebir):
  * exact değer destekleniyorsa exact gönderilir;
  * provider'ın resmi mapping'i varsa o kullanılır;
  * kullanıcı istemeden seviye YÜKSELTİLMEZ;
  * desteklenmeyen değer körü körüne gönderilip 400 üretilmez — omit.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

# ---------------------------------------------------------------------- #
# Canonical effort seviyeleri (düşükten yükseğe sıralı)
# ---------------------------------------------------------------------- #
CANONICAL_LEVELS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
_LEVEL_RANK = {lv: i for i, lv in enumerate(CANONICAL_LEVELS)}


def normalize_effort(value: str) -> str:
    """Girdiyi canonical seviyeye indirger.

    None/boş → '' (istek yok → adapter omit yolunu seçer); 'middle' →
    'medium', 'x-high'/'x_high' → 'xhigh' gibi toleranslar var; tanımsız
    değer 'high'e düşer (kullanıcı bilinçli seçim yapmışsa zaten canonical).
    """
    if value is None:
        return ""
    v = str(value).strip().lower()
    if not v:
        return ""
    aliases = {
        "middle": "medium",
        "med": "medium",
        "x-high": "xhigh",
        "x_high": "xhigh",
        "off": "none",
        "default": "",
    }
    v = aliases.get(v, v)
    return v if v in _LEVEL_RANK else "high"


# ---------------------------------------------------------------------- #
# API türleri (adapter'ların request alan seçimi)
# ---------------------------------------------------------------------- #
API_LLAMACPP = "llamacpp"       # chat_template_kwargs.reasoning_effort
API_OPENAI = "openai"           # üst seviye reasoning_effort (Chat Completions)
API_OPENROUTER = "openrouter"   # reasoning: {effort: ...}
API_ANTHROPIC = "anthropic"     # native Messages API: output_config.effort
API_NONE = "none"               # effort gönderilmez


@dataclass
class ReasoningConfig:
    """resolve_reasoning_config çıktısı: request'e ne eklenecek?"""
    api_type: str                     # yukarıdaki API_* sabitleri
    effort: str = ""                  # gönderilecek (eşlenmiş) seviye; '' = omit
    requested: str = ""               # kullanıcının istediği canonical seviye
    note: str = ""                    # UI için kısa açıklama ('' = not yok)
    disable_thinking: bool = False    # llama.cpp: enable_thinking=false

    @property
    def omitted(self) -> bool:
        return not self.effort and not self.disable_thinking


# ---------------------------------------------------------------------- #
# Model-pattern yetenek kaydı (küçük, maintainable; statik tahmin yalnız
# metadata yoksa ve yalnızca dokümante edilmiş kümeler için kullanılır)
# ---------------------------------------------------------------------- #

@dataclass(frozen=True)
class ModelCaps:
    patterns: tuple            # fnmatch desenleri ('gpt-5*', 'o3*' ...)
    levels: tuple              # desteklenen canonical seviyeler
    note: str = ""             # örn. 'Groq/model limiti'


def _p(patterns, levels, note=""):
    return ModelCaps(tuple(patterns), tuple(levels), note)


# Provider → model-desen tabloları. Yalnızca RESMİ dokümantasyondaki
# kümeler; emin olunmayan provider için tablo YOK → güvenli omit.
_GROQ_MODELS = (
    # gpt-oss reasoning_format KABUL ETMEZ; reasoning alanı varsayılan.
    # qwen reasoning_format=parsed kabul eder (ayrı output capability).
    _p(("gpt-oss*", "*gpt-oss*"), ("low", "medium", "high"), "Groq/model limiti"),
    _p(("qwen*", "*qwen*"), ("none", "low", "medium", "high"), "Groq/model limiti"),
)
_XAI_MODELS = (
    _p(("grok-4*", "grok-3*", "grok-code*"),
       ("low", "medium", "high", "xhigh"), "xAI/model limiti"),
)
_DEEPSEEK_MODELS = (
    _p(("deepseek-reasoner*", "deepseek-chat*", "*deepseek-reasoner*",
        "*deepseek-chat*"),
       ("low", "medium", "high"), "DeepSeek/model limiti"),
)
# Fireworks: reasoning_effort dokümante (none/low/medium/high/xhigh/max).
# Model ailesi doğrulanmayan kimliklerde omit (400 üretmemek için).
_FIREWORKS_MODELS = (
    _p(("*qwen*", "*glm*", "*deepseek*", "*minimax*"),
       ("none", "low", "medium", "high", "xhigh", "max"),
       "Fireworks/model limiti"),
)
# Cerebras: model bazlı reasoning_effort. Bilinmeyen model → omit.
_CEREBRAS_MODELS = (
    _p(("gpt-oss*", "*gpt-oss*"), ("low", "medium", "high"),
       "Cerebras/model limiti"),
    _p(("qwen*", "*qwen*", "gemma*", "*gemma*", "kimi*", "*kimi*"),
       ("none", "low", "medium", "high"), "Cerebras/model limiti"),
)
# Mistral: ayarlanabilir modeller yalnız none|high. Magistral always-on →
# desen dışında, effort omit (parametre 400 üretebilir).
_MISTRAL_MODELS = (
    _p(("mistral-small*", "mistral-medium*", "*mistral-small*",
        "*mistral-medium*"),
       ("none", "high"), "Mistral/model limiti"),
)
# Together: GPT-OSS low|medium|high. DeepSeek V4 düşük değerleri sunucu
# kendi map'ler; biz exact göndeririz. Diğer modeller omit.
_TOGETHER_MODELS = (
    _p(("*gpt-oss*",), ("low", "medium", "high"), "Together/model limiti"),
    _p(("*deepseek-v4*",),
       ("low", "medium", "high", "xhigh", "max"), "Together/model limiti"),
)
_OPENAI_MODELS = (
    # Resmi: reasoning_effort minimal/low/medium/high (yeni modellerde
    # xhigh); 'none' yalnız Responses API'de. GPT serisi klasik modeller
    # parametreyi kabul etmez → desen dışında kalır → omit.
    _p(("o1*", "o3*", "o4*"), ("low", "medium", "high"), "OpenAI/model limiti"),
    _p(("gpt-5*",), ("minimal", "low", "medium", "high", "xhigh"),
       "OpenAI/model limiti"),
)
_GEMINI_MODELS = (
    # Gemini OpenAI-compat: reasoning_effort → thinking_level/budget'a
    # çevrilir; 2.5+ ve gemma thinking modellerinde low/medium/high kümesi.
    _p(("models/gemini-2.5*", "gemini-2.5*", "models/gemini-3*",
        "gemini-3*", "models/gemma*", "gemma*"),
       ("low", "medium", "high"), "Gemini/model limiti"),
)
_ANTHROPIC_MODELS = (
    # Native Messages API output_config.effort: Claude 4+ thinking modelleri.
    _p(("claude-opus-4*", "claude-sonnet-4*", "claude-haiku-4*",
        "claude-4*", "claude-opus-4-1*"),
       ("low", "medium", "high", "xhigh", "max"), "Claude/model limiti"),
    _p(("*",), ("low", "medium", "high", "xhigh", "max"), "Claude/model limiti"),
)
_LLAMACPP_DEFAULT = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def _match_caps(tables, model: str):
    m = (model or "").lower()
    for caps in tables:
        for pat in caps.patterns:
            if fnmatch.fnmatch(m, pat):
                return caps
    return None


# ---------------------------------------------------------------------- #
# Provider tanıma (hostname + config override). Bu bir BLACKLIST DEĞİL:
# yalnızca BİLİNEN hostlar otomatik tanınır; custom endpoint'ler için
# config'de reasoning_api override vardır; bilinmeyenler güvenli omit
# yapar (chat_template_kwargs KABUL ETMEZ).
# ---------------------------------------------------------------------- #

def detect_api_type(base_url: str, model: str = "",
                    override: str = "auto") -> str:
    if override and override != "auto":
        ov = override.strip().lower()
        table = {
            "llamacpp": API_LLAMACPP,
            "llama.cpp": API_LLAMACPP,
            "openai": API_OPENAI,
            "openrouter": API_OPENROUTER,
            "anthropic": API_ANTHROPIC,
            "claude": API_ANTHROPIC,
            "none": API_NONE,
            "off": API_NONE,
        }
        if ov in table:
            return table[ov]
    host = (urlparse(base_url).hostname or "").lower()
    if host in ("api.anthropic.com",):
        return API_ANTHROPIC
    if host == "openrouter.ai":
        return API_OPENROUTER
    if host in ("api.openai.com", "generativelanguage.googleapis.com"):
        return API_OPENAI
    if host in ("api.groq.com", "api.x.ai", "api.deepseek.com"):
        # Bu üçü üst seviye 'reasoning_effort' kullanır (OpenAI-compat);
        # model-bazlı destek tablosu resolve aşamasında uygulanır.
        return API_OPENAI
    if any(part in host for part in (
            "fireworks.ai", "cerebras.ai", "mistral.ai",
            "together.xyz", "together.ai")):
        # Dokümante reasoning_effort (OpenAI-compat alan). Model tablosu
        # eşleşmezse resolve omit eder; bilinmeyen model 400 yemez.
        return API_OPENAI
    # Kalan HERKES (llama.cpp, Ollama, LM Studio, custom gateway...) için:
    # yerel/private hostlarda llamacpp formatı denenir (400-retry ağı var);
    # kamuya açık bilinmeyen hostlarda güvenli omit.
    if host in ("", "localhost") or host.startswith("127.") or \
            host.startswith("192.168.") or host.startswith("10."):
        return API_LLAMACPP
    return API_NONE


# ---------------------------------------------------------------------- #
# Ana adapter
# ---------------------------------------------------------------------- #

def resolve_reasoning_config(base_url: str, model: str,
                             requested_effort: str,
                             override: str = "auto") -> ReasoningConfig:
    """Request'e eklenecek reasoning alanlarını belirler.

    Dönen ReasoningConfig.note UI'da gösterilir; effort '' ise parametre
    HİÇ eklenmez (omit). Hiçbir koşulda iki format aynı request'te bulunmaz.
    """
    req = normalize_effort(requested_effort)
    api = detect_api_type(base_url, model, override)

    if not req:   # istek yok (None/boş): hiçbir format eklenmez
        return ReasoningConfig(api, "", "", note="no effort requested")

    if api == API_NONE:
        return ReasoningConfig(api, "", req,
                               note="effort unsupported (unknown provider)")

    if api == API_LLAMACPP:
        caps = _match_caps(_LLAMACPP_TABLES, model)
        levels = caps.levels if caps else _LLAMACPP_DEFAULT
        if req == "none":
            return ReasoningConfig(api, "", req, disable_thinking=True,
                                   note="llama.cpp chat template")
        eff = _pick(req, levels)
        note = "llama.cpp chat template"
        if caps and caps.note:
            note = caps.note
        if eff != req:
            note = f"{note}: {req}→{eff} (model limiti)" if eff else \
                   f"{req} unsupported → omitted"
        return ReasoningConfig(api, eff, req, note=note)

    if api == API_OPENAI:
        # Host'a ait tablo önce. Generic/override yolunda eski birleşik
        # sıra durur (Gemini, Groq, xAI, DeepSeek, sonra OpenAI).
        for table in _tables_for_host(urlparse(base_url).hostname or ""):
            caps = _match_caps(table, model)
            if caps:
                eff = _pick(req, caps.levels)
                note = caps.note
                if eff != req:
                    note = f"{caps.note}: {req}→{eff}" if eff else \
                           f"{req} unsupported → omitted"
                return ReasoningConfig(api, eff, req, note=note)
        return ReasoningConfig(api, "", req,
                               note="reasoning_effort unsupported (model)")

    if api == API_OPENROUTER:
        # OpenRouter downstream farklarını kendisi eşler; resmi alan
        # reasoning: {effort}. Destek model bazında değişebilir → desen
        # tablosu yerine minimal güvenli küme: low..high + xhigh (newer).
        eff = _pick(req, ("minimal", "low", "medium", "high", "xhigh"))
        return ReasoningConfig(api, eff, req, note="OpenRouter reasoning")

    if api == API_ANTHROPIC:
        caps = _match_caps(_ANTHROPIC_MODELS, model)
        levels = caps.levels if caps else ("low", "medium", "high")
        eff = _pick(req, levels)
        note = caps.note if caps else "Claude/model limiti"
        if eff != req:
            note = f"{note}: {req}→{eff}" if eff else \
                   f"{req} unsupported → omitted"
        return ReasoningConfig(api, eff, req, note=note)

    return ReasoningConfig(API_NONE, "", req, note="effort unsupported")


def _tables_for_host(host: str):
    """OpenAI-compat effort tabloları. Bilinen host yalnız kendi tablosuna bakar."""
    host = (host or "").lower()
    if "fireworks.ai" in host:
        return (_FIREWORKS_MODELS,)
    if "cerebras.ai" in host:
        return (_CEREBRAS_MODELS,)
    if "mistral.ai" in host:
        return (_MISTRAL_MODELS,)
    if "together.xyz" in host or "together.ai" in host:
        return (_TOGETHER_MODELS,)
    if "groq.com" in host:
        return (_GROQ_MODELS,)
    if host == "api.x.ai" or host.endswith(".x.ai"):
        return (_XAI_MODELS,)
    if "deepseek.com" in host:
        return (_DEEPSEEK_MODELS,)
    if "googleapis.com" in host:
        return (_GEMINI_MODELS,)
    if "openai.com" in host:
        return (_OPENAI_MODELS,)
    return (_GEMINI_MODELS, _GROQ_MODELS, _XAI_MODELS,
            _DEEPSEEK_MODELS, _OPENAI_MODELS)


def resolve_output_extra(base_url: str, model: str) -> dict:
    """Reasoning ÇIKTI biçimi. Effort capability'sinden ayrıdır.

    Provider structured/parsed seçenek sunuyorsa ve model bunu
    dokümante ediyorsa gönderilir. Desteklenmeyen modele gönderilmez
    (400 üretilmesin). llama.cpp sürümü belirsiz olduğu için
    reasoning_format orada gönderilmez; sunucu alan üretirse okunur.
    """
    host = (urlparse(base_url or "").hostname or "").lower()
    model_l = (model or "").lower()
    if "groq.com" in host and "qwen" in model_l and "gpt-oss" not in model_l:
        # GPT-OSS reasoning_format kabul etmez; qwen parsed kabul eder.
        return {"reasoning_format": "parsed"}
    if "cerebras.ai" in host and any(
            k in model_l for k in ("qwen", "gpt-oss", "kimi")):
        return {"reasoning_format": "parsed"}
    return {}


def _pick(req: str, levels) -> str:
    """Seçim kuralları: exact → dokümante kümede en yakın AŞAĞI → omit.

    Kullanıcı istemeden seviye yükseltilmez; yükseltme tek istisna
    'none'→en düşük seviyedir (thinking kapatılamayan modellerde).

    Args:
        req: istenen canonical seviye
        levels: desteklenen canonical seviyeler
    Returns:
        gönderilecek seviye veya '' (omit)
    """
    levels = tuple(levels)
    if req in levels:
        return req
    rank_req = _LEVEL_RANK.get(req, _LEVEL_RANK["high"])
    lower = [lv for lv in levels
             if _LEVEL_RANK.get(lv, 99) < rank_req and lv != "none"]
    if lower:
        return max(lower, key=lambda lv: _LEVEL_RANK[lv])
    if "none" in levels:          # 'none' thinking-kapatma olarak destekleniyor
        return "none"
    return ""                     # güvenli omit


# llama.cpp model-desen tablosu (şimdilik boş: tüm modeller default küme;
# chat-template farkları 400-retry + cache ile öğrenilir)
_LLAMACPP_TABLES = (
    _p(("*",), _LLAMACPP_DEFAULT),
)


# ---------------------------------------------------------------------- #
# 400 sınıflandırma: reasoning kaynaklı mı?
# ---------------------------------------------------------------------- #

_REASONING_400_MARKERS = (
    "chat_template_kwargs",
    "reasoning_effort",
    "reasoning",
    "output_config",
    "effort",
    "thinking_level",
    "thinking_budget",
    "unknown name",
    "unknown field",
    "unknown parameter",
    "unrecognized",
    "not supported",
    "unsupported parameter",
    "invalid keyword",
)


def is_reasoning_related_error(exc_text: str) -> bool:
    """Hata metni reasoning parametrelerinden kaynaklanıyor mu?"""
    t = (exc_text or "").lower()
    if "400" not in t and "bad request" not in t and "invalid" not in t:
        return False
    return any(m in t for m in _REASONING_400_MARKERS)

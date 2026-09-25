"""Provider ham akışını ortak reasoning/content olaylarına indirger.

Öncelik: structured alan (reasoning_details, reasoning, reasoning_content,
thinking, ThinkChunk, thought summary). Aynı delta'da birden fazla alias
varsa biri yeter. Inline marker, structured yoksa veya structured varken
kopyayı düşürmek için ikinci adımdır.

Cumulative snapshot: yeni parça o kanala kadar biriken metinle başlıyorsa
yalnız sonek alınır. Parça birikmiş metinle başlamıyorsa olduğu gibi
eklenir (model tekrarıysa dokunulmaz).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from llm.reasoning_text import (
    HarmonyDecoder,
    InlineReasoningDecoder,
    ParseProfile,
    TextEvent,
    profile_for,
)


@dataclass
class NormEvent:
    kind: str                      # reasoning | content | meta
    text: str = ""
    reasoning_kind: str = "raw"    # raw | summary | unknown
    signature: str = ""
    details: list = field(default_factory=list)
    mistral_chunk: bool = False


_DELTA_KEYS = (
    "content", "reasoning", "reasoning_content", "reasoning_details",
    "thinking",
)


def as_dict(obj) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    out = {}
    for key in _DELTA_KEYS:
        if hasattr(obj, key):
            val = getattr(obj, key)
            if val is not None:
                out[key] = val
    extra = getattr(obj, "model_extra", None)
    if not isinstance(extra, dict):
        extra = getattr(obj, "__pydantic_extra__", None)
    if isinstance(extra, dict):
        for key, val in extra.items():
            if key not in out and val is not None:
                out[key] = val
    return out


def _obj(part) -> dict:
    if isinstance(part, dict):
        return part
    data = {}
    for key in ("type", "text", "thinking", "thought", "summary",
                "signature", "content", "thought_signature"):
        if hasattr(part, key):
            val = getattr(part, key)
            if val is not None:
                data[key] = val
    return data


def _join_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text") or item.get("content") or "")
            else:
                parts.append(str(getattr(item, "text", "") or ""))
        return "".join(parts)
    return str(value)


def _detail_block(block) -> tuple[str, str]:
    block = _obj(block) if not isinstance(block, dict) else block
    btype = str(block.get("type") or "").lower()
    summary = block.get("summary")
    if "summary" in btype or summary:
        return _join_text(summary or block.get("text") or block.get("content")), "summary"
    text = _join_text(block.get("text") or block.get("content") or "")
    return text, "raw"


def _chunk_events(part) -> list[NormEvent]:
    if isinstance(part, str):
        return [NormEvent("content", part)] if part else []
    part = _obj(part)
    btype = str(part.get("type") or "").lower()
    if btype in ("thought_signature", "signature", "signature_delta"):
        sig = part.get("signature") or part.get("thought_signature") or ""
        return [NormEvent("meta", signature=str(sig))] if sig else []
    if btype in ("thought_summary",):
        text = _join_text(part.get("text") or part.get("content") or part.get("summary"))
        return [NormEvent("reasoning", text, "summary")] if text else []
    if btype in ("thinking", "think"):
        inner = part.get("thinking")
        text = _join_text(inner if inner is not None else part.get("text"))
        return [NormEvent("reasoning", text, "raw", mistral_chunk=True)] if text else []
    if btype in ("thought",):
        text = _join_text(part.get("text") or part.get("content") or part.get("summary"))
        kind = "summary" if part.get("summary") or part.get("thought") else "raw"
        return [NormEvent("reasoning", text, kind)] if text else []
    if part.get("thought") is True and part.get("text"):
        return [NormEvent("reasoning", _join_text(part.get("text")), "summary")]
    if btype in ("text", "text_chunk", "output_text", "") and part.get("text"):
        return [NormEvent("content", _join_text(part.get("text")))]
    if part.get("text") and btype not in ("thinking", "think"):
        return [NormEvent("content", _join_text(part.get("text")))]
    return []


def _content_events(content) -> list[NormEvent]:
    if content is None:
        return []
    if isinstance(content, str):
        return [NormEvent("content", content)] if content else []
    if isinstance(content, list):
        out = []
        for part in content:
            out.extend(_chunk_events(part))
        return out
    return _chunk_events(content)


def normalize_delta(delta) -> list[NormEvent]:
    """OpenAI-uyumlu chat chunk delta'sı → olaylar.

    reasoning_details > reasoning > reasoning_content > thinking.
    Alias'lar aynı delta'da tekrar yazılmaz.
    """
    data = as_dict(delta)
    events: list[NormEvent] = []
    details = data.get("reasoning_details")
    structured = False
    if isinstance(details, list) and details:
        events.append(NormEvent("meta", details=list(details)))
        for block in details:
            text, kind = _detail_block(block)
            if text:
                events.append(NormEvent("reasoning", text, kind))
                structured = True
    if not structured:
        reasoning = data.get("reasoning")
        rcontent = data.get("reasoning_content")
        if isinstance(reasoning, list):
            for part in reasoning:
                events.extend(_chunk_events(part))
            structured = any(ev.kind == "reasoning" for ev in events)
        elif isinstance(reasoning, str) and reasoning:
            events.append(NormEvent("reasoning", reasoning, "raw"))
            structured = True
        elif isinstance(rcontent, str) and rcontent:
            events.append(NormEvent("reasoning", rcontent, "raw"))
            structured = True
        thinking = data.get("thinking")
        if isinstance(thinking, str) and thinking and not structured:
            events.append(NormEvent("reasoning", thinking, "raw"))
    events.extend(_content_events(data.get("content")))
    return events


def normalize_ollama(payload) -> list[NormEvent]:
    """Native Ollama message.thinking / message.content."""
    msg = payload or {}
    if isinstance(msg, dict) and isinstance(msg.get("message"), dict):
        msg = msg["message"]
    msg = as_dict(msg) if not isinstance(msg, dict) else msg
    events = []
    thinking = msg.get("thinking") or ""
    content = msg.get("content") or ""
    if isinstance(thinking, str) and thinking:
        events.append(NormEvent("reasoning", thinking, "raw"))
    if isinstance(content, str) and content:
        events.append(NormEvent("content", content))
    return events


def normalize_gemini_event(evt: dict) -> list[NormEvent]:
    """Interactions / generateContent thought olayları.

    thought_summary → reasoning (summary). thought_signature kullanıcıya
    yazılmaz, meta olarak saklanır. Düz text → content.
    """
    if not isinstance(evt, dict):
        return []
    delta = evt.get("delta") if isinstance(evt.get("delta"), dict) else evt
    btype = str(delta.get("type") or evt.get("type") or "").lower()
    if btype == "thought_summary":
        content = delta.get("content")
        if isinstance(content, dict):
            text = content.get("text") or ""
        else:
            text = delta.get("text") or ""
        return [NormEvent("reasoning", text, "summary")] if text else []
    if btype in ("thought_signature", "signature"):
        sig = delta.get("signature") or delta.get("thought_signature") or ""
        return [NormEvent("meta", signature=str(sig))] if sig else []
    if btype == "text":
        text = delta.get("text") or ""
        return [NormEvent("content", text)] if text else []
    return []


def anthropic_delta_events(evt: dict) -> list[dict]:
    """Native Messages SSE gövdesinden kullanıcıya giden olaylar.

    signature_delta metin değildir; type=signature ile ayrı döner.
    """
    if not isinstance(evt, dict):
        return []
    if evt.get("type") != "content_block_delta":
        return []
    delta = evt.get("delta") or {}
    dtype = delta.get("type")
    if dtype == "text_delta":
        return [{"type": "text", "data": delta.get("text") or ""}]
    if dtype == "thinking_delta":
        return [{"type": "thinking", "data": delta.get("thinking") or "",
                 "reasoning_kind": "summary"}]
    if dtype == "signature_delta":
        return [{"type": "signature", "data": delta.get("signature") or ""}]
    return []


class ResponseAssembler:
    """Structured olayları ve inline fallback'i tek akışta birleştirir."""

    def __init__(self, profile: ParseProfile | None = None):
        self.profile = profile or ParseProfile()
        self.inline = InlineReasoningDecoder(self.profile)
        self.harmony = HarmonyDecoder() if self.profile.allow_harmony else None
        self._acc = {"reasoning": "", "content": ""}
        self.saw_structured = False
        self.saw_mistral_chunks = False
        self.continuation: dict = {}
        self.reasoning_kind = "raw"

    def _suffix(self, channel: str, text: str) -> str:
        """Cumulative snapshot ise sonek; değilse metnin kendisi."""
        if not text:
            return ""
        prev = self._acc[channel]
        if prev and text.startswith(prev):
            text = text[len(prev):]
        if text:
            self._acc[channel] += text
        return text

    def _absorb_meta(self, ev: NormEvent):
        if ev.details:
            self.continuation["reasoning_details"] = list(ev.details)
        if ev.signature:
            prev = self.continuation.get("signature") or ""
            self.continuation["signature"] = prev + ev.signature

    def consume(self, events: list[NormEvent]) -> list[TextEvent]:
        structured: list[NormEvent] = []
        content: list[NormEvent] = []
        for ev in events:
            if ev.kind == "meta":
                self._absorb_meta(ev)
            elif ev.kind == "reasoning":
                structured.append(ev)
                if ev.mistral_chunk:
                    self.saw_mistral_chunks = True
            elif ev.kind == "content":
                content.append(ev)
                if ev.mistral_chunk:
                    self.saw_mistral_chunks = True
        out: list[TextEvent] = []
        if structured:
            self.saw_structured = True
            self.inline.suppress = True
            if self.harmony is not None:
                self.harmony.suppress_analysis = True
        for ev in structured:
            text = self._suffix("reasoning", ev.text)
            if not text:
                continue
            if ev.reasoning_kind == "summary":
                self.reasoning_kind = "summary"
            elif self.reasoning_kind != "summary":
                self.reasoning_kind = ev.reasoning_kind or "raw"
            out.append(TextEvent("reasoning", text, ev.reasoning_kind or "raw"))
        for ev in content:
            text = self._suffix("content", ev.text)
            if not text:
                continue
            if self.harmony is not None:
                out.extend(self.harmony.feed(text))
            else:
                out.extend(self.inline.feed(text))
        return out

    def flush(self) -> list[TextEvent]:
        if self.harmony is not None:
            return self.harmony.flush()
        return self.inline.flush()


def assembler_for(base_url: str = "", model: str = "") -> ResponseAssembler:
    return ResponseAssembler(profile_for(base_url, model))

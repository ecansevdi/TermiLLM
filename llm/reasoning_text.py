"""Incremental reasoning/content ayrımı.

Structured alanlar bu modülün dışında normalize edilir. Burada yalnız
inline marker fallback ve ham GPT-OSS Harmony vardır.

Kurallar:
  * <think> ve <thought> yalnız cevap daha görünür metin üretmeden,
    akışın başındaki prefix ise açılır (gözlenen / yaygın şablon).
  * [THINK], Cohere control token ve Harmony yalnız profil açarsa.
  * Forced-open (kapanışa kadar reasoning) yalnız profil doğrularsa.
  * Görünür metin başladıktan sonra gelen etiketler yutulmaz.
  * <analysis>, <reasoning>, <thinking> gibi rastgele XML etiketleri
    marker değildir.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class ParseProfile:
    allow_think: bool = True
    allow_thought: bool = True
    allow_ministral: bool = False
    allow_cohere: bool = False
    allow_harmony: bool = False
    forced_open_think: bool = False


def profile_for(base_url: str = "", model: str = "") -> ParseProfile:
    """Model kimliğinden doğrulanmış marker profili.

    Harmony varsayılan KAPALI: Ollama/LM Studio/llama.cpp/Groq/Cerebras
    Harmony'yi kendileri ayırır. Ham Harmony yalnız profil.allow_harmony
    ile (raw-mode test veya açıkça istenen yol) çalışır.
    """
    model_l = (model or "").lower()
    host = (urlparse(base_url or "").hostname or "").lower()
    profile = ParseProfile()
    if "ministral" in model_l:
        profile.allow_ministral = True
    if "cohere" in host or "cohere" in model_l or model_l.startswith("command"):
        profile.allow_cohere = True
    return profile


@dataclass
class TextEvent:
    kind: str                 # reasoning | content
    text: str
    reasoning_kind: str = "raw"


def _hold_len(buf: str, markers: tuple[str, ...]) -> int:
    """buf'ın, bir marker'ın öneki olan en uzun son eki."""
    best = 0
    if not buf or not markers:
        return 0
    limit = min(len(buf), max(len(m) for m in markers) - 1)
    for n in range(1, limit + 1):
        suffix = buf[-n:]
        if any(marker.startswith(suffix) for marker in markers):
            best = n
    return best


def _earliest(buf: str, markers: tuple[str, ...]) -> tuple[int, str]:
    found_at = -1
    found = ""
    for marker in markers:
        idx = buf.find(marker)
        if idx != -1 and (found_at == -1 or idx < found_at):
            found_at = idx
            found = marker
    return found_at, found


class InlineReasoningDecoder:
    """Parça parça gelen metinde bilinen reasoning marker'larını ayırır."""

    def __init__(self, profile: ParseProfile | None = None):
        self.profile = profile or ParseProfile()
        self.buf = ""
        self.mode = "think" if self.profile.forced_open_think else "content"
        self.suppress = False
        self._visible = False
        self._sink = "reasoning"

    def feed(self, text: str) -> list[TextEvent]:
        if not text:
            return []
        self.buf += text
        return self._drain(final=False)

    def flush(self) -> list[TextEvent]:
        return self._drain(final=True)

    def _opens(self) -> tuple[tuple[str, str], ...]:
        if self._visible or self.mode != "content":
            return ()
        items = []
        if self.profile.allow_think:
            items.append(("<think>", "think"))
        if self.profile.allow_thought:
            items.append(("<thought>", "thought"))
        if self.profile.allow_ministral:
            items.append(("[THINK]", "ministral"))
        if self.profile.allow_cohere:
            items.append(("<|START_THINKING|>", "cohere"))
            # Final cevaba geçiş işareti; görünür metin sayılmaz.
            items.append(("<|START_RESPONSE|>", "discard"))
        return tuple(items)

    def _closes(self) -> tuple[str, ...]:
        if self.mode == "think":
            return ("</think>",)
        if self.mode == "thought":
            return ("</thought>",)
        if self.mode == "ministral":
            return ("[/THINK]",)
        if self.mode == "cohere":
            return ("<|END_THINKING|>", "<|START_RESPONSE|>")
        return ()

    def _drain(self, final: bool) -> list[TextEvent]:
        events: list[TextEvent] = []
        guard = 0
        while self.buf and guard < 100000:
            guard += 1
            if self.mode == "content":
                opens = self._opens()
                markers = tuple(m for m, _ in opens)
                if not markers:
                    events.extend(self._take_content(self.buf, final=True))
                    self.buf = ""
                    break
                idx, marker = _earliest(self.buf, markers)
                if idx == -1:
                    hold = 0 if final else _hold_len(self.buf, markers)
                    emit = self.buf if hold == 0 else self.buf[:-hold]
                    if emit:
                        events.extend(self._take_content(emit))
                        self.buf = self.buf[len(emit):]
                    if final and self.buf:
                        events.extend(self._take_content(self.buf))
                        self.buf = ""
                    break
                pre = self.buf[:idx]
                if pre.strip():
                    events.extend(self._take_content(pre))
                    self.buf = self.buf[idx:]
                    continue
                mode = next(m for mk, m in opens if mk == marker)
                self.buf = self.buf[idx + len(marker):]
                if mode == "discard":
                    continue
                self.mode = mode
                self._sink = "drop" if self.suppress else "reasoning"
                continue

            closes = self._closes()
            idx, marker = _earliest(self.buf, closes)
            if idx == -1:
                hold = 0 if final else _hold_len(self.buf, closes)
                emit = self.buf if hold == 0 else self.buf[:-hold]
                if emit:
                    events.extend(self._take_reasoning(emit))
                    self.buf = self.buf[len(emit):]
                if final and self.buf:
                    events.extend(self._take_reasoning(self.buf))
                    self.buf = ""
                break
            if idx > 0:
                events.extend(self._take_reasoning(self.buf[:idx]))
            self.buf = self.buf[idx + len(marker):]
            self.mode = "content"
            self._sink = "reasoning"
        return events

    def _take_content(self, text: str, final: bool = False) -> list[TextEvent]:
        if not text:
            return []
        if text.strip():
            self._visible = True
        return [TextEvent("content", text)]

    def _take_reasoning(self, text: str) -> list[TextEvent]:
        if not text or self._sink == "drop":
            return []
        return [TextEvent("reasoning", text, "raw")]


_HARMONY_TOKS = (
    "<|start|>", "<|channel|>", "<|message|>", "<|end|>", "<|return|>",
)


class HarmonyDecoder:
    """Ham GPT-OSS Harmony. analysis → reasoning, final → content.

    Kanal adı ile rol öneki kullanıcıya yazılmaz. Ayırıcı yoksa
    metin content olarak kalır; tahminle bölünmez.
    """

    def __init__(self):
        self.buf = ""
        self.phase = "idle"       # idle | preamble | channel | body
        self.channel = ""
        self.body = "content"
        self.suppress_analysis = False

    def feed(self, text: str) -> list[TextEvent]:
        if not text:
            return []
        self.buf += text
        return self._drain(final=False)

    def flush(self) -> list[TextEvent]:
        return self._drain(final=True)

    def _drain(self, final: bool) -> list[TextEvent]:
        events: list[TextEvent] = []
        guard = 0
        while self.buf and guard < 100000:
            guard += 1
            idx, tok = _earliest(self.buf, _HARMONY_TOKS)
            if idx == -1:
                hold = 0 if final else _hold_len(self.buf, _HARMONY_TOKS)
                emit = self.buf if hold == 0 else self.buf[:-hold]
                if emit:
                    events.extend(self._emit(emit))
                    self.buf = self.buf[len(emit):]
                if final and self.buf:
                    events.extend(self._emit(self.buf))
                    self.buf = ""
                break
            if idx > 0:
                events.extend(self._emit(self.buf[:idx]))
            self.buf = self.buf[idx + len(tok):]
            self._on_token(tok)
        return events

    def _on_token(self, tok: str):
        if tok == "<|start|>":
            self.phase = "preamble"
            self.channel = ""
        elif tok == "<|channel|>":
            self.phase = "channel"
            self.channel = ""
        elif tok == "<|message|>":
            name = self.channel.strip().lower()
            if name == "analysis":
                self.body = "reasoning"
            else:
                self.body = "content"
            self.phase = "body"
        elif tok in ("<|end|>", "<|return|>"):
            self.phase = "idle"
            self.channel = ""

    def _emit(self, text: str) -> list[TextEvent]:
        if not text:
            return []
        if self.phase == "channel":
            self.channel += text
            return []
        if self.phase == "preamble":
            return []
        if self.phase == "body" and self.body == "reasoning":
            if self.suppress_analysis:
                return []
            return [TextEvent("reasoning", text, "raw")]
        return [TextEvent("content", text)]


def collapse(events: list[TextEvent]) -> tuple[str, str]:
    reasoning = []
    content = []
    for ev in events:
        if ev.kind == "reasoning":
            reasoning.append(ev.text)
        else:
            content.append(ev.text)
    return "".join(reasoning), "".join(content)


def decode_all(text: str, profile: ParseProfile | None = None) -> tuple[str, str]:
    """Tek metin veya karakter karakter; testler her sınırı da dener."""
    profile = profile or ParseProfile()
    if profile.allow_harmony:
        dec = HarmonyDecoder()
        events = dec.feed(text)
        events += dec.flush()
        return collapse(events)
    dec = InlineReasoningDecoder(profile)
    events = dec.feed(text)
    events += dec.flush()
    return collapse(events)


def decode_every_cut(text: str, profile: ParseProfile | None = None) -> tuple[str, str]:
    """Her kesim noktası ve karakter karakter aynı sonucu vermeli."""
    profile = profile or ParseProfile()
    expected = decode_all(text, profile)

    def _run(parts: list[str]) -> tuple[str, str]:
        if profile.allow_harmony:
            dec = HarmonyDecoder()
        else:
            dec = InlineReasoningDecoder(profile)
        events: list[TextEvent] = []
        for part in parts:
            events += dec.feed(part)
        events += dec.flush()
        return collapse(events)

    chars = _run(list(text))
    if chars != expected:
        raise AssertionError(f"char split {chars!r} != {expected!r}")
    for i in range(len(text) + 1):
        got = _run([text[:i], text[i:]])
        if got != expected:
            raise AssertionError(f"cut {i} {got!r} != {expected!r}")
    return expected

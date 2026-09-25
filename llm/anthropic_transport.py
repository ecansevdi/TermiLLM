"""Native Anthropic Messages API transport (yalnızca Claude için).

OpenAI SDK'nın Anthropic uyumluluk katmanı `reasoning_effort`'u sessizce
yok saydığı için effort kontrolünün GERÇEK çalıştığı yol budur:
POST {base}/v1/messages ile `output_config: {"effort": ...}` gönderilir ve
yanıt SSE olarak akıtılır.

Ortak arayüz: `stream_messages(...)` bir generator'dır; LLMClient bunun
üzerinden aynı StreamParser'ı besler. Bütün uygulama Anthropic'e özel
değildir — bu transport yalnızca api_type=anthropic seçildiğinde devreye
girer (llm/client.py).

ÖNEMLİ: Bu transport yalnızca api.anthropic.com'ı native olarak hedefler;
anthropic uyumluluk proxy'lerinde `reasoning_effort` yok sayıldığından
OpenAI-compat yolu üzerinden Claude'a effort gönderilmez (UI notu ile).
"""

from __future__ import annotations

import json
import urllib.request

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicStreamError(Exception):
    """Anthropic HTTP hatası (status + gövde metni ile)."""


def _anthropic_content(message: dict):
    """Görünür metin string kalır. Thinking+signature varsa blok olarak geri gider.

    Signature kullanıcıya basılmaz; çok turlu devam için transport'ta durur.
    """
    ps = message.get("provider_state") or {}
    text = message.get("content", "")
    if message.get("role") == "assistant" and (ps.get("thinking") or ps.get("signature")):
        block = {"type": "thinking", "thinking": ps.get("thinking") or ""}
        if ps.get("signature"):
            block["signature"] = ps["signature"]
        return [block, {"type": "text", "text": text or ""}]
    return text


def build_payload(model: str, messages: list, system: str = None,
                  effort: str = "", max_tokens: int = 4096) -> dict:
    """Native Messages API gövdesi. effort varsa output_config.effort eklenir
    (yalnızca tek format; reasoning_effort/reasoning ASLA eklenmez)."""
    body = {
        "model": model,
        "messages": [
            {"role": "user" if m.get("role") != "assistant" else "assistant",
             "content": _anthropic_content(m)}
            for m in messages
        ],
        "max_tokens": max_tokens,
        "stream": True,
    }
    if system:
        body["system"] = system
    if effort:
        body["output_config"] = {"effort": effort}
    return body


def _extract_system(messages: list) -> str:
    for m in messages:
        if m.get("role") == "system":
            return m.get("content", "")
    return None


def stream_messages(base_url: str, api_key: str, model: str,
                    messages: list, effort: str = "",
                    max_tokens: int = 4096) -> "tuple[object, callable]":
    """İsteği açar; (event-iterator, close-fn) döndürür.

    event-iterator: her adımda sözlük üretir:
      {"type": "text", "data": str} — cevap metni parçası
      {"type": "thinking", "data": str} — reasoning metni parçası
      {"type": "usage", "input": int, "output": int}
      {"type": "done"}
    close-fn: akışı erken kesmek için (Ctrl+X cancel yolu).
    """
    system = _extract_system(messages)
    body = build_payload(model, messages, system=system, effort=effort,
                         max_tokens=max_tokens)
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    req = urllib.request.Request(
        f"{url}/messages",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key or "",
            "anthropic-version": ANTHROPIC_VERSION,
            "Accept": "text/event-stream",
        },
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        raise AnthropicStreamError(f"HTTP {e.code}: {detail}") from e

    def _close():
        try:
            resp.close()
        except Exception:
            pass

    def _events():
        input_tokens = output_tokens = 0
        try:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                etype = evt.get("type")
                if etype == "content_block_delta":
                    from llm.normalize import anthropic_delta_events
                    for item in anthropic_delta_events(evt):
                        yield item
                elif etype == "message_start":
                    u = (evt.get("message", {}) or {}).get("usage", {}) or {}
                    input_tokens = u.get("input_tokens") or 0
                elif etype == "message_delta":
                    u = evt.get("usage", {}) or {}
                    output_tokens = u.get("output_tokens") or 0
                elif etype == "message_stop":
                    break
                elif etype == "error":
                    raise AnthropicStreamError(str(evt.get("error", evt)))
        finally:
            yield {"type": "usage", "input": input_tokens, "output": output_tokens}
            yield {"type": "done"}
            _close()

    return _events(), _close

"""İptalde HTTP akışını ve varsa llama-server görevini gerçekten keser.

OpenAI SDK'nın stream.close() çağrısı çoğu zaman yalnızca istemci
tamponunu bırakır; soket açık kalırsa llama-server / vLLM üretmeye
devam eder. Soketi SHUT_RDWR ile kapatmak sunucuya RST/FIN gider.
"""

from __future__ import annotations

import socket
import urllib.error
import urllib.request

from llm.server_info import _strip_version

_ABORT_PATHS = ("/abort", "/v1/abort")
_ABORT_TIMEOUT = 1.5


def abort_stream(stream) -> None:
    """Akışın altındaki TCP soketini kapat, sonra HTTP yanıtını kapat."""
    http_resp = getattr(stream, "response", None) or stream
    _shutdown_socket(http_resp)
    _shutdown_socket(stream)
    for obj in (stream, http_resp):
        closer = getattr(obj, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass


def abort_provider_task(api_base_url: str, api_key: str = None) -> None:
    """llama.cpp /abort varsa çağır. Olmayan sağlayıcıda sessizce geç."""
    origin = _strip_version(api_base_url or "")
    if not origin:
        return
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = b"{}"
    for path in _ABORT_PATHS:
        try:
            req = urllib.request.Request(
                origin + path, data=body, headers=headers, method="POST")
            urllib.request.urlopen(req, timeout=_ABORT_TIMEOUT).read()
            return
        except Exception:
            continue


def _shutdown_socket(obj, _seen=None, _depth=0) -> None:
    if obj is None or _depth > 12:
        return
    if _seen is None:
        _seen = set()
    oid = id(obj)
    if oid in _seen:
        return
    _seen.add(oid)

    sock = _as_socket(obj)
    if sock is not None:
        _hard_close(sock)
        return

    get_extra = getattr(obj, "get_extra_info", None)
    if callable(get_extra):
        for key in ("socket", "sock"):
            try:
                extra = get_extra(key)
            except Exception:
                extra = None
            if extra is not None:
                _shutdown_socket(extra, _seen, _depth + 1)

    extensions = getattr(obj, "extensions", None)
    if isinstance(extensions, dict):
        for key in ("network_stream", "stream"):
            if key in extensions:
                _shutdown_socket(extensions[key], _seen, _depth + 1)

    for attr in ("stream", "_stream", "_network_stream", "response",
                 "_connection", "io", "_sock", "sock", "_socket", "socket"):
        try:
            child = getattr(obj, attr, None)
        except Exception:
            child = None
        if child is not None and child is not obj:
            _shutdown_socket(child, _seen, _depth + 1)


def _as_socket(obj):
    if isinstance(obj, socket.socket):
        return obj
    shutdown = getattr(obj, "shutdown", None)
    close = getattr(obj, "close", None)
    # Gerçek soket veya test sahte soketi; HTTP yanıt nesneleri değil.
    if (callable(shutdown) and callable(close)
            and not hasattr(obj, "status_code")
            and not hasattr(obj, "iter_bytes")):
        return obj
    raw = getattr(obj, "_sock", None)
    if raw is not None and raw is not obj:
        return _as_socket(raw)
    return None


def _hard_close(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass

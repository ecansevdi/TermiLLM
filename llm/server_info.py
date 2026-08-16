import json
import urllib.request


def fetch_server_context_size(server_base: str) -> tuple:
    """Server'dan context boyutunu alır. (n_ctx, fallback_used) döner."""
    fallback = 4096

    try:
        url = f"{server_base}/props"
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        n_ctx = data.get("n_ctx") or data.get("total_slots", [{}])[0].get("n_ctx")
        if isinstance(n_ctx, int) and n_ctx > 0:
            return n_ctx, False
    except Exception:
        pass

    try:
        url = f"{server_base}/slots"
        with urllib.request.urlopen(url, timeout=3) as resp:
            slots = json.loads(resp.read().decode())
        if isinstance(slots, list) and slots:
            n_ctx = slots[0].get("n_ctx")
            if isinstance(n_ctx, int) and n_ctx > 0:
                return n_ctx, False
    except Exception:
        pass

    return fallback, True

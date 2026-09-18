"""Prompt satırında @ ile dosya tamamlama.

Tab, @ sonrası yazılanı mevcut (veya verilen) dizinde arar.
Başka dizinler yol olarak yazılır:

    @            cwd
    @src/        alt dizin
    @../         üst dizin
    @~/          ev dizini
    @/abs/yol/   mutlak yol

Dizin eşleşmelerinin sonuna / konur; seçtikten sonra yazmaya devam edilir.
"""

from __future__ import annotations

import os

try:
    import readline
    HAS_READLINE = True
except ImportError:
    HAS_READLINE = False

SKIP_NAMES = {"__pycache__", ".git", "node_modules", ".venv", "venv"}
MAX_MATCHES = 80


def token_at_cursor(chars, pos: int) -> tuple[int, str]:
    """İmlecin solundaki boşluksuz token (başlangıç indeksi, metin)."""
    start = pos
    while start > 0 and chars[start - 1] not in " \t":
        start -= 1
    if isinstance(chars, str):
        return start, chars[start:pos]
    return start, "".join(chars[start:pos])


def _is_skipped(name: str, needle: str) -> bool:
    if name in SKIP_NAMES:
        return True
    if name.startswith(".") and not needle.startswith("."):
        return True
    return False


def _split_user_path(raw: str) -> tuple[str, str, str, str]:
    """(abs_dir, needle, root_label, rel_dir) — kullanıcının yazdığı stili korur."""
    raw = raw or ""
    if raw == "~" or raw.startswith("~/"):
        root_label, rest, abs_root = "~/", raw[2:] if raw.startswith("~/") else "", os.path.expanduser("~")
    elif raw.startswith("/"):
        root_label, rest, abs_root = "/", raw[1:], "/"
    else:
        root_label, rest, abs_root = "", raw, os.getcwd()

    if rest.endswith("/") or rest == "":
        rel_dir, needle = rest, ""
    else:
        rel_dir, needle = os.path.dirname(rest), os.path.basename(rest)

    abs_dir = os.path.normpath(os.path.join(abs_root, rel_dir)) if rel_dir else abs_root
    return abs_dir, needle, root_label, rel_dir


def _display_path(root_label: str, rel_dir: str, name: str, is_dir: bool) -> str:
    rel_dir = rel_dir.replace("\\", "/").strip("/")
    if root_label == "/":
        base = "/" + "/".join(p for p in (rel_dir, name) if p)
    elif root_label:
        base = root_label + "/".join(p for p in (rel_dir, name) if p)
    else:
        base = "/".join(p for p in (rel_dir, name) if p)
        if not base:
            base = name
    if is_dir and not base.endswith("/"):
        base += "/"
    return base


def parse_browse_token(token: str) -> tuple[str, str]:
    """'@src/foo' -> ('src/', 'foo'); '@' -> ('', '')."""
    raw = token[1:] if (token or "").startswith("@") else (token or "")
    if raw.endswith("/") or raw == "":
        return raw, ""
    if "/" in raw:
        head, tail = raw.rsplit("/", 1)
        return head + "/", tail
    return "", raw


def enter_browser_dir(prefix: str, name: str) -> str:
    """prefix 'src/', name 'foo' veya '..' -> yeni prefix."""
    name = (name or "").rstrip("/")
    if name == "..":
        p = (prefix or "").rstrip("/")
        if p in ("", "."):
            return "../"
        if p == ".." or p.endswith("/.."):
            return p + "/../"
        if "/" not in p:
            return ""
        parent = p.rsplit("/", 1)[0]
        return "" if parent in ("", ".") else parent + "/"
    if not prefix:
        return name + "/"
    return prefix.rstrip("/") + "/" + name + "/"


def list_browser_entries(prefix: str) -> list[str]:
    """Kutu için kısa adlar: ../, klasör/, dosya. prefix örn. '', 'src/', '../'."""
    raw = prefix if (prefix or "").endswith("/") or prefix in ("", None) else prefix + "/"
    abs_dir, _, _, _ = _split_user_path(raw or "")
    abs_dir = os.path.normpath(abs_dir)
    entries = []
    parent = os.path.normpath(os.path.join(abs_dir, ".."))
    if parent != abs_dir:
        entries.append("../")
    try:
        names = os.listdir(abs_dir)
    except OSError:
        return entries
    dirs, files = [], []
    for name in names:
        if _is_skipped(name, ""):
            continue
        if os.path.isdir(os.path.join(abs_dir, name)):
            dirs.append(name + "/")
        else:
            files.append(name)
    dirs.sort(key=str.lower)
    files.sort(key=str.lower)
    return entries + dirs + files


def file_completion_matches(raw_prefix: str) -> list[str]:
    """@ sonrası yazılan parçaya göre tamamlanan yolları döndürür (başına @ konmaz)."""
    abs_dir, needle, root_label, rel_dir = _split_user_path(raw_prefix)
    needle_l = needle.lower()

    try:
        names = os.listdir(abs_dir)
    except OSError:
        return []

    prefix_hits = []
    substr_hits = []
    for name in names:
        if _is_skipped(name, needle):
            continue
        name_l = name.lower()
        if needle_l and not name_l.startswith(needle_l) and needle_l not in name_l:
            continue
        full = os.path.join(abs_dir, name)
        is_dir = os.path.isdir(full)
        display = _display_path(root_label, rel_dir, name, is_dir)
        bucket = prefix_hits if (not needle_l or name_l.startswith(needle_l)) else substr_hits
        bucket.append(display)

    prefix_hits.sort(key=str.lower)
    substr_hits.sort(key=str.lower)
    return (prefix_hits + substr_hits)[:MAX_MATCHES]


class AtPathCompleter:
    def __init__(self):
        self.matches = []

    def complete(self, text, state):
        if state == 0:
            self.matches = self._compute(text)
        if state < len(self.matches):
            return self.matches[state]
        return None

    def _compute(self, text: str) -> list[str]:
        if not text.startswith("@"):
            return []
        return ["@" + m for m in file_completion_matches(text[1:])]


def install_file_completer():
    if not HAS_READLINE:
        return
    completer = AtPathCompleter()
    readline.set_completer(completer.complete)
    # / ve @ kelime kırıcı olmasın ki @src/foo tek parça tamamlansın.
    readline.set_completer_delims(" \t\n")
    # Vi komut modunda 'b' kelime geri gider, yazılmaz. Emacs + self-insert.
    readline.parse_and_bind("set editing-mode emacs")
    readline.parse_and_bind("set keymap emacs")
    readline.parse_and_bind("b: self-insert")
    readline.parse_and_bind("B: self-insert")
    doc = (readline.__doc__ or "").lower()
    if "libedit" in doc:
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")
        readline.parse_and_bind("set show-all-if-ambiguous off")
        readline.parse_and_bind("set completion-query-items -1")
        readline.parse_and_bind("set page-completions off")

"""Ctrl+O provider menüsü: küçük dikdörtgen pencere (tam ekran değil).

Tamamı İngilizce; arkaplan silinmez — sayfa içeriği üzerinde opak kutu
çizilir, kapanınca içerik yeniden boyanır (_restore).

Akış:
  * Select Provider → kayıtlı provider'lar (p<n>_ kayıtları) → GET /models
    ile modeller → model seçimi → uygula → effort seçimi.
  * Enter API → Base URL + API key girilir → modeller çekilir (olmazsa
    model id elle) → '.env'e yeni kayıt + aktif etme → effort seçimi.

Bu modül sayfanın iç alanlarını (_real_stdout, _keep_rows_*) kullanır;
menü yalnızca Ctrl+O ile, giriş döngüsünden çağrılır (cbreak zaten açık).
"""

from __future__ import annotations

import sys

import re as _re

import config as config_mod
from ui.keys import read_key
from ui.page import visible_width
from ui.terminal import BOLD, BOLD_RESET, DIM, FG_WHITE, RESET

# ui.page import döngüsünden kaçınmak için zemin sıfırlama dizisi
_BG_BLACK = "\033[40m"

_BOX_W = 60          # menü kutusu genişliği (kolon)
_LIST_MAX = 10       # listede aynı anda görünen öğe


# ---------------------------------------------------------------------- #
# Çizim yardımcıları
# ---------------------------------------------------------------------- #

def _box_geometry(page, h: int, w: int = _BOX_W):
    cols = page._cols
    top = page._keep_rows_top + 1
    bottom = page._rows - page._keep_rows_bottom
    w = min(w, max(20, cols - 6))
    h = max(3, min(h, max(3, bottom - top)))
    r0 = top + max(0, (bottom - top - h) // 2)
    c0 = max(2, (cols - w) // 2 + 1)
    return r0, c0, w, h


def _draw_menu(page, title: str, body: list[str]) -> None:
    """Ekranda TEK MENÜ ilkesiyle kutu çizer.

    Çizimden ÖNCE içerik penceresi temizlenir: önceki ekran (eski menü,
    sohbet balonları, prompt kalıntıları) arkaplanda kalmaz. Üst çubuk ve
    giriş kutusu sabittir. Genişlik içeriğe göre otomatik; sığmazsa kolon
    sayısına indirilir ve satırlar kırpılır.
    """
    page.clear_content_window()
    out = page._real_stdout
    need = visible_width(f"┤ {title} ├") + 2          # başlık + 2 boşluk payı
    for ln in body:
        need = max(need, visible_width(ln) + 2)       # satır + 2 iç boşluk
    need += 2                                          # iki kenar │ │
    r0, c0, w, h = _box_geometry(page, len(body) + 2, w=min(need + 2, 110))
    inner = w - 2

    out.write("\0337")
    for i in range(h):
        r = r0 + i
        out.write(f"\033[{r};{c0 - 1}H {FG_WHITE}")
        if i == 0:
            t = f"┤ {title} ├"
            side = max(0, inner - len(t))
            out.write("┌" + "─" * (side // 2) + t + "─" * (side - side // 2) + "┐")
        elif i == h - 1:
            out.write("└" + "─" * inner + "┘")
        else:
            text = body[i - 1] if i - 1 < len(body) else ""
            text = _fit_ansi(text, inner)
            pad = " " * max(0, inner - visible_width(text))
            out.write(f"│{text}{pad}│")
        out.write(f" {RESET}{_BG_BLACK}")
    out.write("\0338")
    out.flush()


def _fit_ansi(text: str, width: int) -> str:
    """Satırı genişliğe kırpar (ANSI dizileri kolon sayılmaz)."""
    import re as _re
    if visible_width(text) <= width:
        return text
    out, w, i, n = [], 0, 0, len(text)
    while i < n and w < width:
        m = _re.match(r"\033\[[0-9;?]*[A-Za-z]", text[i:])
        if m:
            out.append(m.group(0))
            i += m.end()
            continue
        out.append(text[i])
        w += 1
        i += 1
    return "".join(out)


def _restore(page) -> None:
    page._draw_window(force=True)
    page.draw_input()


def _wait_key(page) -> str:
    return read_key(sys.stdin.fileno())


def _message(page, title: str, lines: list[str]) -> None:
    body = lines + ["", f"{DIM}press any key{RESET}"]
    _draw_menu(page, title, body)
    _wait_key(page)


def _prompt_line(page, title: str, prompt: str, default: str = "",
                 secret: bool = False):
    """Tek satır metin girişi; enter → değer (boşsa default), esc → None."""
    buf = ""
    while True:
        shown = ("*" * len(buf) if secret else buf) + "▌"
        hint = f"  {DIM}default: {default}{RESET}" if default else ""
        _draw_menu(page, title, [
            f"{DIM}{prompt}{RESET}",
            "",
            f"{FG_WHITE}{BOLD}{shown}{BOLD_RESET}",
            "",
            f"{DIM}enter ok · esc cancel · ctrl-u clear{RESET}{hint}",
        ])
        key = _wait_key(page)
        if key == "enter":
            return buf if buf else default
        if key in ("esc", "ctrl-c"):
            return None
        if key == "ctrl-u":
            buf = ""
        elif key == "backspace":
            buf = buf[:-1]
        elif len(key) == 1 and key.isprintable():
            buf += key


def _pick_from_list(page, title: str, items: list[str],
                    active: int = -1, extra_hint: str = "",
                    extra_keys: dict = None, searchable: bool = False,
                    type_to_search: bool = False):
    """Kaydırmalı liste.

    enter → indeks, esc → None. extra_keys verildiyse ('d' gibi harf
    tuşları) listeden çıkmadan fırlatılır: dönen değer ('key', indeks).

    REGEX arama:
      * searchable=True  → '/' arama satırını açar (Select Provider gibi
        harf tuşu kısayolları olan listelerde).
      * type_to_search=True → herhangi bir karakter yazınca arama ANINDA
        açılır ve yazılan karakter desen olur (model listeleri gibi uzun
        listelerde; harf kısayolu olmayan yerlerde).

    Desen yazılırken liste canlı süzülür (re.search). Enter desenini
    uygular; esc önce filtreyi temizler (filtre yoksa listeyi kapatır).
    Geçersiz desen uyarıyla gösterilir, süzme durur.
    """
    if not items:
        return None
    idx, off = 0, 0
    pattern = ""
    searching = False
    while True:
        # --- görünür liste: desen varsa süz ---
        rx = None
        rx_err = False
        if pattern:
            try:
                rx = _re.compile(pattern)
            except _re.error:
                rx_err = True
        if rx is not None and pattern:
            view = [(gi, it) for gi, it in enumerate(items) if rx.search(it)]
        else:
            view = list(enumerate(items))
        if not view:
            view = []
        # imleci görünür aralıkta tut
        if idx >= len(view):
            idx = max(0, len(view) - 1)
        if idx < off:
            off = idx
        if idx >= off + _LIST_MAX:
            off = idx - _LIST_MAX + 1
        body = []
        if searching:
            cur = view[idx][1] if view else ""
            body.append(f"{DIM}/{pattern}{('▌' if not rx_err else '')}{RESET}")
            if rx_err:
                body.append(f"{FG_WHITE}invalid regex: {pattern}{RESET}")
            else:
                body.append(f"{DIM}{len(view)} match(es){RESET}")
        for i in range(off, min(off + _LIST_MAX, len(view))):
            gi, it = view[i]
            mark = "●" if gi == active else " "
            cursor = "▶" if i == idx else " "
            if i == idx:
                body.append(f"{FG_WHITE}{BOLD}{cursor} {mark} {it}{BOLD_RESET}")
            else:
                body.append(f"{DIM}{cursor} {mark} {it}{RESET}")
        if len(view) > _LIST_MAX:
            body.append(f"{DIM}  {off + 1}-{min(off + _LIST_MAX, len(view))}"
                        f" / {len(view)}{RESET}")
        if not searching and pattern and not view:
            body.append(f"{FG_WHITE}no match · esc clears filter{RESET}")
        tail = f"{DIM}↑↓ navigate · enter select · esc back{RESET}"
        if not searching:
            if searchable:
                tail += f"  {DIM}/ search{RESET}"
            elif type_to_search:
                tail += f"  {DIM}type to search{RESET}"
        if extra_hint:
            tail += f"  {DIM}{extra_hint}{RESET}"
        body += ["", tail]
        _draw_menu(page, title, body)
        key = _wait_key(page)
        if searching:
            if key == "enter":
                searching = False
                idx = 0
                off = 0
            elif key in ("esc", "ctrl-c"):
                searching = False
                pattern = ""
                idx = 0
                off = 0
            elif key == "backspace":
                pattern = pattern[:-1]
                idx = 0
                off = 0
            elif len(key) == 1 and key.isprintable():
                pattern += key
                idx = 0
                off = 0
            continue
        if key == "up":
            idx = (idx - 1) % len(view) if view else 0
        elif key == "down":
            idx = (idx + 1) % len(view) if view else 0
        elif key == "enter":
            if not view:
                continue
            return view[idx][0]
        elif key == "/" and searchable:
            searching = True
        elif key in ("esc", "ctrl-c"):
            # filtre uygulanmışsa önce onu temizle, ikinci esc listeden çıkar
            if pattern:
                pattern = ""
                idx = 0
                off = 0
                continue
            return None
        elif (extra_keys and key in extra_keys and view):
            return ("key", key, view[idx][0])   # harf tuşu: (tür, tuş, gerçek indeks)
        elif (type_to_search and len(key) == 1
              and key.isprintable() and key != "/"):
            searching = True
            pattern = key
            idx = 0
            off = 0


# ---------------------------------------------------------------------- #
# Provider işlemleri
# ---------------------------------------------------------------------- #

def _provider_env(name: str) -> tuple[str, str, str]:
    """Kaydın (base_url, api_key[ÇÖZÜLMÜŞ], model) üçlüsü."""
    return config_mod.get_provider(name)


def _mask(url: str) -> str:
    return url if len(url) <= 34 else url[:31] + "..."


def _apply(page, base_url: str, api_key: str, model: str,
           name: str, current: list, apply_provider) -> None:
    """Bellekte etkinleştir + onay göster + effort seçimi."""
    current[0], current[1], current[2] = name, base_url, model
    apply_provider(base_url, api_key, model)
    page.set_effort_note("")   # yeni provider: eski 'gönderilen' notu temizle
    _message(page, "Provider Applied", [
        f"name:  {name}",
        f"base:  {_mask(base_url)}",
        f"model: {model}",
    ])
    page._pick_effort()


def _flow_quick_add(page, current: list, apply_provider) -> None:
    """Popüler sağlayıcılar: yalnızca API key kaydı.

    Model SEÇTİRİLMEZ — model seçimi yalnızca 'Select Provider'
    ekranından yapılır. Kayıt ('Select Provider' listesinde görünür)
    aktif provider'ın key'i güncelleniyorsa mevcut seçim bozulmaz.
    """
    names = [n for n, _ in config_mod.API_PROVIDERS]
    i = _pick_from_list(page, "Quick Add Provider", names,
                        extra_hint="popular providers",
                        type_to_search=True)
    if i is None:
        return
    disp, base = config_mod.API_PROVIDERS[i]
    _draw_menu(page, disp, [f"{DIM}Base: {base}{RESET}",
                            f"{DIM}Enter your API key...{RESET}"])
    key = _prompt_line(page, f"{disp} — API Key", "Paste your API key:",
                       "", secret=True)
    if key is None:
        return

    name, created = config_mod.upsert_provider_key(base, key)
    if not created and name == current[0]:
        # mevcut aktif provider'ın key'i yenilendi: istemciye uygula
        b, _, m = _provider_env(name)
        apply_provider(b, key, m)
    _message(page, "Key Saved", [
        f"provider: {name} ({disp})",
        f"base:     {_mask(base)}",
        "",
        f"{DIM}Select this provider from 'Select Provider'",
        f"{DIM}to choose its model and activate it.{RESET}",
    ])


def _flow_enter_api(page, current: list, apply_provider) -> None:
    base = _prompt_line(page, "Enter API — Base URL",
                        "OpenAI-compatible base URL:",
                        current[1] or "http://localhost:8080/v1")
    if base is None:
        return
    key = _prompt_line(page, "Enter API — Key", "API key:", "", secret=True)
    if key is None:
        return

    _draw_menu(page, "Enter API", [f"{DIM}Loading models...{RESET}"])
    models, err = [], ""
    try:
        models = config_mod.fetch_models(base, key)
    except Exception as e:
        err = str(e)[:44]

    if models:
        i = _pick_from_list(page, "Select Model", models,
                            extra_hint=f"{len(models)} models",
                            type_to_search=True)
        if i is None:
            return
        model = models[i]
    else:
        _message(page, "Models Unavailable", [
            "Could not list models from this endpoint.",
            f"{DIM}{err}{RESET}",
        ])
        model = _prompt_line(page, "Enter API — Model ID", "Model id:", "")
        if model is None:
            return

    name = config_mod.save_api_values(base, key, model)
    _apply(page, base, key, model, name, current, apply_provider)


def _flow_select_provider(page, current: list, apply_provider) -> None:
    while True:
        names = list(config_mod.providers().keys())
        if not names:
            _message(page, "Select Provider", [
                "No saved providers yet.",
                f"{DIM}Use 'Enter API' or 'Quick Add' to add one.{RESET}",
            ])
            return
        items = []
        for n in names:
            b, _, m = _provider_env(n)
            tag = "●" if n == current[0] else " "
            items.append(f"{tag} {n}  {_mask(b)}  [{m or 'model?'}]")
        res = _pick_from_list(
            page, "Select Provider", items,
            active=names.index(current[0]) if current[0] in names else -1,
            extra_hint="d: delete",
            extra_keys={"d": True},
            searchable=True)
        if res is None:
            return
        # 'd' tuşu: seçili kaydı silme akışı
        if isinstance(res, tuple):
            _, _, idx = res
            name = names[idx]
            if name == current[0]:
                _message(page, "Delete Provider", [
                    f"'{name}' is the ACTIVE provider.",
                    f"{DIM}Switch to another one first, then delete it.{RESET}",
                ])
                continue
            confirm = _pick_from_list(
                page, f"Delete '{name}'?",
                ["CANCEL", "YES, delete permanently"])
            if confirm == 1:
                config_mod.delete_provider(name)
                _message(page, "Deleted", [f"provider '{name}' removed."])
            continue              # silinmiş haliyle listeye geri dön
        # normal Enter seçimi
        name = names[res]
        base, key, model = _provider_env(name)
        break
    # --- model seçimi ve uygulama (silme akışından break ile gelinir) ---

    models = []
    try:
        _draw_menu(page, "Select Provider", [f"{DIM}Loading models...{RESET}"])
        models = config_mod.fetch_models(base, key)
    except Exception as e:
        _message(page, "Models Unavailable", [
            f"GET /models failed: {str(e)[:44]}",
            f"{DIM}Falling back to saved model id.{RESET}",
        ])
    if models:
        j = _pick_from_list(
            page, "Select Model", models,
            active=models.index(model) if model in models else -1,
            extra_hint=f"{len(models)} models",
            type_to_search=True)
        if j is not None:
            model = models[j]
    elif not model:
        _message(page, "Select Provider", [
            "No models listed and no saved model id.",
        ])
        return

    config_mod.set_active(name, model)
    _apply(page, base, key, model, name, current, apply_provider)


# ---------------------------------------------------------------------- #
# Giriş noktası
# ---------------------------------------------------------------------- #

def show_provider_menu(page, current_name: str, current_base: str,
                       current_model: str, apply_provider) -> None:
    """Ctrl+O menüsü. apply_provider(base_url, api_key, model) → application."""
    current = [current_name, current_base, current_model]
    try:
        while True:
            i = _pick_from_list(
                page, "Providers",
                ["Select Provider", "Enter API", "Quick Add Provider"],
                extra_hint=f"active: {current[0] or '-'}")
            if i is None:
                return
            if i == 0:
                _flow_select_provider(page, current, apply_provider)
            elif i == 1:
                _flow_enter_api(page, current, apply_provider)
            else:
                _flow_quick_add(page, current, apply_provider)
    finally:
        _restore(page)

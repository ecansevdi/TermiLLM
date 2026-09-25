from ui.terminal import (
    BG_BLACK, BG_GRAY, BOLD, BOLD_RESET, CYAN, DIM, FG_WHITE, ITALIC, RESET,
    YELLOW,
)


def _gray_fill(line: str) -> str:
    """Metni gri zeminle basıp satırı sonuna kadar doldurur."""
    return f"{BG_GRAY}{FG_WHITE}{line}{RESET}{BG_BLACK}"


# Reasoning kanalının taban stili: sayfa her satırı FG_WHITE ile açtığı için
# satır kendi SGR'sini taşımalı. DIM+sarı, mevcut "turuncu" düşünme rengi.
REASONING_BASE = BG_BLACK + DIM + YELLOW


class MarkdownFormatter:
    """
    Gelen metin akışını (stream) harf harf işleyerek Terminal ANSI kodlarına
    çeviren yapı. Kod blokları, kalın yazılar, satır içi kodlar vs. için çalışır.

    base_style boşsa cevap kanalının eski kodları korunur.
    base_style doluysa (reasoning) her satır bu stille açılır; geçici bir
    Markdown stili kapanınca çıplak RESET yerine RESET+base_style basılır.
    """

    def __init__(self, base_style: str = ""):
        self.base_style = base_style or ""
        self.buffer = ""
        self.in_block = False
        self.in_inline = False
        self.in_bold = False
        self.in_italic = False
        self.in_heading = False
        self.in_blockquote = False
        self.is_newline = True
        self._line_styled = False

    def feed(self, text: str, base_style: str | None = None) -> str:
        if base_style is not None:
            self.base_style = base_style or ""
        self.buffer += text
        out = ""

        while self.buffer:
            # 1. Kod Blokları (```)
            if self.buffer.startswith("```"):
                self.in_block = not self.in_block
                if self.base_style:
                    self._line_styled = True
                    out += self._compose()
                elif self.in_block:
                    out += f"{RESET}{BG_GRAY}{FG_WHITE}"
                else:
                    out += f"{RESET}{BG_BLACK}{FG_WHITE}"
                    if self.in_bold:
                        out += BOLD
                self.buffer = self.buffer[3:]
                self.is_newline = False
                continue

            # Parçalı geldiyse beklet
            if self.buffer in ("`", "``"):
                break

            if self.in_block:
                char = self.buffer[0]
                out += char
                self.buffer = self.buffer[1:]
                self.is_newline = (char == "\n")
                if char == "\n":
                    out += f"{BG_GRAY}{FG_WHITE}"
                continue

            # 2. Kalın Yazı (**)
            if self.buffer.startswith("**"):
                self.in_bold = not self.in_bold
                out += self._push_style() if self.base_style else (
                    BOLD if self.in_bold else BOLD_RESET)
                self.buffer = self.buffer[2:]
                self.is_newline = False
                continue

            if self.buffer == "*":
                break

            # Reasoning: *important* italik. Satır başı "* " madde işareti kalır.
            if (self.base_style and not self.in_inline
                    and self.buffer.startswith("*")):
                if self.is_newline and self.buffer[1] == " ":
                    pass
                else:
                    self.in_italic = not self.in_italic
                    out += self._push_style()
                    self.buffer = self.buffer[1:]
                    self.is_newline = False
                    continue

            # 3. Satır İçi Kod (`)
            if self.buffer.startswith("`"):
                self.in_inline = not self.in_inline
                if self.base_style:
                    out += self._push_style()
                elif self.in_inline:
                    out += f"{RESET}{CYAN}"
                else:
                    out += f"{RESET}"
                    if self.in_bold:
                        out += BOLD
                self.buffer = self.buffer[1:]
                self.is_newline = False
                continue

            # 4. Başlıklar (#)
            if self.is_newline and self.buffer.startswith("#"):
                idx = 0
                while idx < len(self.buffer) and self.buffer[idx] == "#":
                    idx += 1

                if idx < len(self.buffer) and self.buffer[idx] == " ":
                    self.in_heading = True
                    if self.base_style:
                        self._line_styled = True
                        out += self._compose() + self.buffer[:idx + 1]
                    else:
                        out += f"{BOLD}{CYAN}" + self.buffer[:idx + 1]
                    self.buffer = self.buffer[idx + 1:]
                    self.is_newline = False
                    continue
                elif idx == len(self.buffer):
                    break

            # 5. Alıntılar (>) — satırın tamamı gri zeminde akar
            if self.is_newline and self.buffer.startswith(">"):
                if len(self.buffer) > 1 and self.buffer[1] == " ":
                    self.in_blockquote = True
                    if self.base_style:
                        self._line_styled = True
                        out += self._compose() + "> "
                    else:
                        out += f"{BG_GRAY}{FG_WHITE}> "
                    self.buffer = self.buffer[2:]
                    self.is_newline = False
                    continue
                elif len(self.buffer) == 1:
                    break

            # Normal Karakter İşleme
            char = self.buffer[0]

            if char == "\n":
                self.is_newline = True
                out += char
                self.buffer = self.buffer[1:]
                if self.in_heading or self.in_blockquote:
                    self.in_heading = False
                    self.in_blockquote = False
                    if self.base_style:
                        self._line_styled = False
                        out += self._open_line()
                    else:
                        out += f"{RESET}{BG_BLACK}{FG_WHITE}"
                        if self.in_bold:
                            out += BOLD
                    continue
                if self.base_style:
                    self._line_styled = False
                    out += self._open_line()
                continue

            self.is_newline = False
            if self.base_style:
                out += self._open_line()
            out += char
            self.buffer = self.buffer[1:]

        return out

    def flush(self) -> str:
        if self.base_style and self.buffer == "*" and self.in_italic:
            self.in_italic = False
            self.buffer = ""
            out = self._push_style()
            self._reset_spans()
            return out

        out = ""
        if self.base_style and self.buffer and not self._line_styled:
            out += self._open_line()
        out += self.buffer
        if self.base_style:
            self._reset_spans()
        elif self.in_block or self.in_blockquote:
            out += f"{RESET}{BG_BLACK}{FG_WHITE}"
        elif self.in_bold or self.in_heading or self.in_inline:
            out += f"{RESET}"
        self.buffer = ""
        return out

    def _compose(self) -> str:
        """Geçici span'lerin üstüne taban stili yeniden kurar."""
        if self.in_block:
            return f"{RESET}{BG_GRAY}{FG_WHITE}"
        if self.in_blockquote:
            out = f"{RESET}{BG_GRAY}{FG_WHITE}"
        elif self.in_inline:
            out = f"{RESET}{CYAN}"
        elif self.in_heading:
            out = f"{RESET}{BOLD}{CYAN}"
        elif self.base_style:
            out = f"{RESET}{self.base_style}"
        else:
            out = ""
        if self.in_bold and not self.in_block and not self.in_heading:
            out += BOLD
        if self.in_italic and not self.in_block and not self.in_inline:
            out += ITALIC
        return out

    def _open_line(self) -> str:
        if not self.base_style or self._line_styled or self.in_block:
            return ""
        self._line_styled = True
        return self._compose()

    def _push_style(self) -> str:
        self._line_styled = True
        return self._compose()

    def _reset_spans(self):
        self.in_block = False
        self.in_inline = False
        self.in_bold = False
        self.in_italic = False
        self.in_heading = False
        self.in_blockquote = False
        self.is_newline = True
        self._line_styled = False
        self.buffer = ""

from ui.terminal import BOLD, BOLD_RESET, CYAN, DIM, RESET, YELLOW


class MarkdownFormatter:
    """
    Gelen metin akışını (stream) harf harf işleyerek Terminal ANSI kodlarına
    çeviren yapı. Kod blokları, kalın yazılar, satır içi kodlar vs. için çalışır.
    """
    def __init__(self):
        self.buffer = ""
        self.in_block = False
        self.in_inline = False
        self.in_bold = False
        self.in_heading = False
        self.in_blockquote = False
        self.is_newline = True

    def feed(self, text: str) -> str:
        self.buffer += text
        out = ""

        while self.buffer:
            # 1. Kod Blokları (```)
            if self.buffer.startswith("```"):
                self.in_block = not self.in_block
                if self.in_block:
                    out += f"{RESET}{YELLOW}"  # Kod bloğu içi sarı
                else:
                    out += f"{RESET}"
                    if self.in_bold: out += BOLD
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
                continue

            # 2. Kalın Yazı (**)
            if self.buffer.startswith("**"):
                self.in_bold = not self.in_bold
                out += BOLD if self.in_bold else BOLD_RESET
                self.buffer = self.buffer[2:]
                self.is_newline = False
                continue

            if self.buffer == "*":
                break

            # 3. Satır İçi Kod (`)
            if self.buffer.startswith("`"):
                self.in_inline = not self.in_inline
                if self.in_inline:
                    out += f"{RESET}{CYAN}"  # Satır içi kod turkuaz
                else:
                    out += f"{RESET}"
                    if self.in_bold: out += BOLD
                self.buffer = self.buffer[1:]
                self.is_newline = False
                continue

            # 4. Başlıklar (#)
            if self.is_newline and self.buffer.startswith("#"):
                idx = 0
                while idx < len(self.buffer) and self.buffer[idx] == "#":
                    idx += 1

                if idx < len(self.buffer) and self.buffer[idx] == " ":
                    out += f"{BOLD}{CYAN}" + self.buffer[:idx+1]
                    self.buffer = self.buffer[idx+1:]
                    self.is_newline = False
                    self.in_heading = True
                    continue
                elif idx == len(self.buffer):
                    break

            # 5. Alıntılar (>)
            if self.is_newline and self.buffer.startswith(">"):
                if len(self.buffer) > 1 and self.buffer[1] == " ":
                    out += f"{DIM}> "
                    self.buffer = self.buffer[2:]
                    self.is_newline = False
                    self.in_blockquote = True
                    continue
                elif len(self.buffer) == 1:
                    break

            # Normal Karakter İşleme
            char = self.buffer[0]

            if char == "\n":
                self.is_newline = True
                if self.in_heading or self.in_blockquote:
                    out += f"{RESET}"
                    if self.in_bold: out += BOLD
                    self.in_heading = False
                    self.in_blockquote = False
            else:
                self.is_newline = False

            out += char
            self.buffer = self.buffer[1:]

        return out

    def flush(self) -> str:
        out = self.buffer
        if self.in_bold or self.in_block or self.in_heading or self.in_inline or self.in_blockquote:
            out += f"{RESET}"
        self.buffer = ""
        return out

import os


class TextFileLoader:
    """Metin dosyası yükleme."""

    def load(self, path: str) -> str:
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Dosya bulunamadı: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

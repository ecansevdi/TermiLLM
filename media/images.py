import base64
import mimetypes
import os


class ImageLoader:
    """Görseli base64 data URI biçimine hazırlar."""

    def load(self, path: str) -> tuple:
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Resim bulunamadı: {path}")
        mime, _ = mimetypes.guess_type(path)
        if not mime or not mime.startswith("image/"):
            mime = "image/jpeg"
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        return data, mime

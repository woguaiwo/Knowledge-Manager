"""
Utility helpers for Knowledge Manager.
"""
import base64
import re
from PySide6.QtCore import QByteArray, QBuffer, Qt
from PySide6.QtGui import QImage


def clean_vocab_text(text: str) -> str:
    """
    Strip leading/trailing non-alphanumeric characters for vocab collection.
    Preserves internal spaces and punctuation (e.g. "it's", "e.g.")
    but removes surrounding symbols like quotes, brackets, commas, etc.
    """
    cleaned = text.strip()
    cleaned = re.sub(r'^[^\w\s]+', '', cleaned)
    cleaned = re.sub(r'[^\w\s]+$', '', cleaned)
    cleaned = cleaned.strip()
    return cleaned


def encode_qimage_to_base64(img: QImage, max_size: int = 1024, quality: int = 85) -> tuple[str, str]:
    """
    Convert a QImage to base64-encoded JPEG string.
    Returns (base64_string, mime_type).
    Scales down if larger than max_size on either dimension.
    """
    if img.isNull():
        return ("", "")
    if img.width() > max_size or img.height() > max_size:
        img = img.scaled(
            max_size, max_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation
        )
    ba = QByteArray()
    buffer = QBuffer(ba)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buffer, "JPEG", quality)
    b64 = base64.b64encode(ba.data()).decode("utf-8")
    return (b64, "image/jpeg")

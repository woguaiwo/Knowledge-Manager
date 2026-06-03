"""
QuizRenderer: QTextBrowser-based markdown renderer with media attachments.
Supports full Markdown (tables, code blocks, etc.), images, audio, video.
Math formulas are rendered as SVG vector images via matplotlib mathtext.
"""
import re
import io
import base64
import markdown
import matplotlib
matplotlib.use('Agg')  # headless backend
from matplotlib.figure import Figure

from PySide6.QtCore import Qt, QByteArray, QIODevice, QBuffer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser, QLabel, QPushButton
)
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtGui import QFont, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from core.theme_colors import get_theme_colors


# Module-level math renderer (shared cache across all QuizRenderer instances)
_math_cache = {}

# Bump this whenever rendering parameters change to invalidate old cached images
_CACHE_VERSION = 4

# Tuned target heights per formula complexity class (px)
# Determined interactively: simple=80%, medium=105%, complex=128% of base
_SIMPLE_TARGET = 21   # 26 * 0.80
_MEDIUM_TARGET = 34   # 32 * 1.05
_COMPLEX_TARGET = 54  # 42 * 1.28

# Temporary debug scales for interactive size tuning per complexity class
_DEBUG_SIMPLE_SCALE = 1.0
_DEBUG_MEDIUM_SCALE = 1.0
_DEBUG_COMPLEX_SCALE = 1.0


def set_math_scales(simple=None, medium=None, complex_=None):
    """Temporarily adjust math formula display scale per class. For debugging only."""
    global _DEBUG_SIMPLE_SCALE, _DEBUG_MEDIUM_SCALE, _DEBUG_COMPLEX_SCALE, _math_cache
    changed = False
    if simple is not None:
        new_val = max(0.3, min(3.0, simple))
        if new_val != _DEBUG_SIMPLE_SCALE:
            _DEBUG_SIMPLE_SCALE = new_val
            changed = True
    if medium is not None:
        new_val = max(0.3, min(3.0, medium))
        if new_val != _DEBUG_MEDIUM_SCALE:
            _DEBUG_MEDIUM_SCALE = new_val
            changed = True
    if complex_ is not None:
        new_val = max(0.3, min(3.0, complex_))
        if new_val != _DEBUG_COMPLEX_SCALE:
            _DEBUG_COMPLEX_SCALE = new_val
            changed = True
    if changed:
        _math_cache.clear()  # invalidate cached images when scale changes


def get_math_scales():
    return _DEBUG_SIMPLE_SCALE, _DEBUG_MEDIUM_SCALE, _DEBUG_COMPLEX_SCALE


def _svg_to_png_uri(svg_bytes: bytes, display_w: int, display_h: int) -> str:
    """Render SVG to a 2x-resolution PNG data URI for crisp display in Qt."""
    renderer = QSvgRenderer(svg_bytes)
    if not renderer.isValid():
        return None
    # Render at 4x display resolution for maximum crispness
    img = QImage(display_w * 4, display_h * 4, QImage.Format.Format_ARGB32)
    img.fill(0x00FFFFFF)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    ba = QByteArray()
    buffer = QBuffer(ba)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buffer, "PNG")
    buffer.close()
    b64 = base64.b64encode(ba.data()).decode('ascii')
    return f"data:image/png;base64,{b64}"


def _latex_to_image_uri(latex: str, display_mode: bool = False, color: str = "black") -> tuple:
    """Render LaTeX formula to a (png_uri, width, height) tuple. Uses module-level cache."""
    cache_key = (_CACHE_VERSION, latex, display_mode, color,
                 _DEBUG_SIMPLE_SCALE, _DEBUG_MEDIUM_SCALE, _DEBUG_COMPLEX_SCALE)
    if cache_key in _math_cache:
        return _math_cache[cache_key]

    try:
        if not latex.startswith("$"):
            latex = f"${latex}$"

        if display_mode:
            fig = Figure(figsize=(5.0, 1.5), dpi=100)
            fontsize = 22
        else:
            fig = Figure(figsize=(3.0, 1.0), dpi=100)
            fontsize = 20
        fig.text(0.5, 0.5, latex, ha='center', va='center', fontsize=fontsize, color=color)
        buf = io.BytesIO()
        fig.savefig(buf, format='svg', bbox_inches='tight',
                    pad_inches=0.05, transparent=True)
        buf.seek(0)
        svg_bytes = buf.read()

        # Calculate display size based on complexity
        w, h = _get_svg_display_size(svg_bytes)

        # Pre-render to hi-res PNG (2x) for crisp Qt display
        png_uri = _svg_to_png_uri(svg_bytes, w, h)
        if png_uri is None:
            return None

        result = (png_uri, w, h)
        _math_cache[cache_key] = result
        return result
    except Exception:
        return None


def _get_svg_display_size(svg_bytes: bytes, target_height: int = None) -> tuple:
    """Return (width, height) in pixels to display an SVG.

    If target_height is not provided, the intrinsic SVG height is used to
    automatically choose a target height (simple/medium/complex) so that
    the main characters in all formulas appear at a consistent visual size.
    """
    renderer = QSvgRenderer(svg_bytes)
    if not renderer.isValid():
        return (target_height or 24, target_height or 24)
    default = renderer.defaultSize()
    if default.height() <= 0:
        return (target_height or 24, target_height or 24)

    intrinsic_h = default.height()

    # If caller didn't specify a fixed target, choose one based on complexity
    if target_height is None:
        if intrinsic_h < 30:
            target_height = _SIMPLE_TARGET
            scale_factor = _DEBUG_SIMPLE_SCALE
        elif intrinsic_h <= 45:
            target_height = _MEDIUM_TARGET
            scale_factor = _DEBUG_MEDIUM_SCALE
        else:
            target_height = _COMPLEX_TARGET
            scale_factor = _DEBUG_COMPLEX_SCALE
    else:
        # Legacy path — caller provided a fixed target (kept for compatibility)
        scale_factor = _DEBUG_SIMPLE_SCALE  # fallback

    scale = (target_height / intrinsic_h) * scale_factor
    return (int(default.width() * scale), int(target_height * scale_factor))


def render_math_in_text(text: str) -> str:
    """Replace $...$ and $$...$$ in plain text with <img> tags. No Markdown."""
    from core.theme_colors import get_theme_colors
    colors = get_theme_colors()
    # Use white for dark theme, black for others
    math_color = "white" if colors.get("bg") == "#2b2b2b" else "black"

    def _block(m):
        latex = m.group(1).strip()
        result = _latex_to_image_uri(latex, display_mode=True, color=math_color)
        if result:
            uri, w, h = result
            return f'<div style="text-align:center;margin:8px 0;"><img src="{uri}" width="{w}" height="{h}" /></div>'
        return f'<div style="font-family:monospace;">{m.group(1)}</div>'

    def _inline(m):
        latex = m.group(1).strip()
        result = _latex_to_image_uri(latex, display_mode=False, color=math_color)
        if result:
            uri, w, h = result
            return f'<img src="{uri}" width="{w}" height="{h}" style="vertical-align:middle;" />'
        return f'<code>{m.group(1)}</code>'

    text = re.sub(r'\$\$(.*?)\$\$', _block, text, flags=re.DOTALL)
    text = re.sub(r'\$(.+?)\$', _inline, text)
    return text


class QuizRenderer(QWidget):
    """Render quiz question text (Markdown) plus optional media attachments."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._md_text = ""
        self._media_list = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.text_browser = QTextBrowser(self)
        self.text_browser.setOpenExternalLinks(False)
        self.text_browser.setOpenLinks(False)
        font = QFont("Segoe UI", 13)
        self.text_browser.setFont(font)
        layout.addWidget(self.text_browser, 1)

        # Container for audio/video attachments shown below the text
        self.media_container = QWidget(self)
        self.media_layout = QVBoxLayout(self.media_container)
        self.media_layout.setContentsMargins(0, 0, 0, 0)
        self.media_layout.setSpacing(6)
        layout.addWidget(self.media_container)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def set_content(self, md_text: str, media_list: list = None):
        """
        Render markdown text and optional media attachments.

        md_text: Markdown source (may contain $...$ or $$...$$ math)
        media_list: list of dicts like {"type": "img|audio|video", "path": "..."}
                    img paths embedded in markdown are also auto-detected.
        """
        self._md_text = md_text
        self._media_list = media_list
        self._render()

    def refresh_theme(self):
        """Re-render with current theme colors. Call after theme switch."""
        self._render()

    def _render(self):
        colors = get_theme_colors()
        md_text = self._md_text
        media_list = self._media_list

        # Extract audio/video markers from markdown before conversion
        audio_paths = []
        video_paths = []
        img_paths = []

        if media_list:
            for m in media_list:
                t = m.get("type", "")
                p = m.get("path", "")
                if t == "audio":
                    audio_paths.append(p)
                elif t == "video":
                    video_paths.append(p)
                elif t == "img":
                    img_paths.append(p)

        # Convert markdown to HTML
        html_body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])

        # Render math formulas as SVG images
        html_body = self._render_math(html_body)

        # Resolve image paths to absolute paths for QTextBrowser
        html_body = self._resolve_images(html_body, img_paths)

        # Wrap in themed HTML
        full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{
    background-color: {colors['base']};
    color: {colors['text']};
    font-family: "Segoe UI", system-ui, sans-serif;
    font-size: 16px;
    line-height: 1.7;
    padding: 8px;
}}
h1 {{ font-size: 22px; color: {colors['text']}; margin: 10px 0; }}
h2 {{ font-size: 20px; color: {colors['text']}; margin: 10px 0; }}
h3 {{ font-size: 18px; color: {colors['text']}; margin: 8px 0; }}
h4 {{ font-size: 17px; color: {colors['text']}; margin: 8px 0; }}
p {{ margin: 8px 0; }}
img {{ max-width: 100%; border-radius: 4px; vertical-align: middle; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th, td {{ border: 1px solid {colors['border']}; padding: 8px; text-align: left; }}
th {{ background: {colors['hover']}; }}
code {{
    background: {colors['code_bg']};
    padding: 2px 6px;
    border-radius: 3px;
    font-family: "Consolas", monospace;
    font-size: 15px;
}}
pre {{
    background: {colors['code_bg']};
    padding: 12px;
    border-radius: 6px;
    overflow-x: auto;
    font-size: 15px;
}}
blockquote {{
    border-left: 4px solid {colors['accent']};
    margin: 10px 0;
    padding-left: 14px;
    color: {colors['muted']};
}}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

        self.text_browser.setHtml(full_html)

        # Clear old media widgets
        while self.media_layout.count():
            child = self.media_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Add audio players
        for path in audio_paths:
            self._add_audio_player(path)

        # Add video players
        for path in video_paths:
            self._add_video_player(path)

        self.media_container.setVisible(bool(audio_paths or video_paths))

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _render_math(self, html: str) -> str:
        """Convert inline $...$ and display $$...$$ math to <img> tags."""
        return render_math_in_text(html)

    def _resolve_images(self, html: str, extra_img_paths: list) -> str:
        """Ensure image src paths are absolute so QTextBrowser can load them."""
        import os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        def _repl(m):
            src = m.group(1)
            if not src.startswith("http") and not os.path.isabs(src) and not src.startswith("data:"):
                abs_path = os.path.normpath(os.path.join(base, src))
                if os.path.isfile(abs_path):
                    return f'<img src="file:///{abs_path.replace(chr(92),"/")}"'
            return m.group(0)

        html = re.sub(r'<img\s+[^>]*src="([^"]+)"', _repl, html)
        return html

    def _add_audio_player(self, path: str):
        from PySide6.QtCore import QUrl

        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(f"🎵 {path}")
        h.addWidget(lbl)

        player = QMediaPlayer(self)
        player.setSource(QUrl.fromLocalFile(path))

        btn_play = QPushButton("▶ Play")
        btn_play.setFixedWidth(70)
        btn_play.clicked.connect(lambda: player.play())
        h.addWidget(btn_play)

        btn_stop = QPushButton("⏹ Stop")
        btn_stop.setFixedWidth(70)
        btn_stop.clicked.connect(lambda: player.stop())
        h.addWidget(btn_stop)

        h.addStretch()
        self.media_layout.addWidget(w)

    def _add_video_player(self, path: str):
        from PySide6.QtCore import QUrl

        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(f"🎬 {path}")
        v.addWidget(lbl)

        video = QVideoWidget()
        video.setMinimumHeight(200)
        v.addWidget(video)

        player = QMediaPlayer(self)
        player.setVideoOutput(video)
        player.setSource(QUrl.fromLocalFile(path))

        h = QHBoxLayout()
        btn_play = QPushButton("▶ Play")
        btn_play.clicked.connect(lambda: player.play())
        h.addWidget(btn_play)

        btn_stop = QPushButton("⏹ Stop")
        btn_stop.clicked.connect(lambda: player.stop())
        h.addWidget(btn_stop)

        h.addStretch()
        v.addLayout(h)

        self.media_layout.addWidget(w)

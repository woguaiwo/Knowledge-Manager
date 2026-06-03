"""
PDF Engine using PyMuPDF (fitz).
Handles rendering pages and extracting word positions.
"""
from typing import List, Dict, Optional, Tuple
import fitz  # PyMuPDF
from PySide6.QtGui import QImage, QColor
from core.logger import get_logger

logger = get_logger()


class PdfEngine:
    def __init__(self):
        self.doc: Optional[fitz.Document] = None
        self.path: str = ""

    def load(self, path: str) -> bool:
        """Load a PDF document. Returns True on success."""
        try:
            self.doc = fitz.open(path)
            self.path = path
            return True
        except Exception as e:
            print(f"Failed to open PDF: {e}")
            self.doc = None
            self.path = ""
            return False

    def close(self):
        """Close the current document."""
        if self.doc:
            self.doc.close()
            self.doc = None
            self.path = ""

    @property
    def page_count(self) -> int:
        return self.doc.page_count if self.doc else 0

    def render_page(self, page_number: int, zoom: float = 1.5) -> Optional[QImage]:
        """Render a page to QImage at the given zoom factor."""
        if not self.doc or page_number < 0 or page_number >= self.page_count:
            return None
        page = self.doc.load_page(page_number)
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        # Convert fitz pixmap to QImage
        fmt = QImage.Format.Format_RGB888 if pix.n == 3 else QImage.Format.Format_ARGB32
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
        return image.copy()  # detach from underlying buffer

    def get_page_words(self, page_number: int, zoom: float = 1.5) -> List[Dict]:
        """
        Extract words from a page with their bounding boxes.
        Returns list of dicts: {
            'text': str,
            'x': float, 'y': float, 'width': float, 'height': float,
            'page': int, 'block': int, 'line': int
        }
        Coordinates are scaled by zoom.
        """
        if not self.doc or page_number < 0 or page_number >= self.page_count:
            return []
        page = self.doc.load_page(page_number)
        wordlist = page.get_text("words")
        results = []
        for w in wordlist:
            x0, y0, x1, y1, text, block_no, line_no, word_no = w
            results.append({
                "text": text,
                "x": x0 * zoom,
                "y": y0 * zoom,
                "width": (x1 - x0) * zoom,
                "height": (y1 - y0) * zoom,
                "page": page_number,
                "block": block_no,
                "line": line_no,
            })
        return results

    def get_line_context(self, page_number: int, block_no: int, line_no: int) -> str:
        """Retrieve the full line text for context using block/line indices."""
        if not self.doc:
            return ""
        page = self.doc.load_page(page_number)
        blocks = page.get_text("dict").get("blocks", [])
        if block_no < 0 or block_no >= len(blocks):
            return ""
        block = blocks[block_no]
        if "lines" not in block:
            return ""
        lines = block["lines"]
        if line_no < 0 or line_no >= len(lines):
            return ""
        return "".join(span["text"] for span in lines[line_no]["spans"])

    def extract_full_text(self) -> str:
        """Extract full text from all pages. Truncated if extremely long."""
        if not self.doc:
            return ""
        parts = []
        for i in range(self.doc.page_count):
            page = self.doc.load_page(i)
            text = page.get_text("text").strip()
            if text:
                parts.append(f"--- Page {i + 1} ---\n{text}")
        full = "\n\n".join(parts)
        if len(full) > 12000:
            full = full[:12000] + "\n...[document truncated]"
        return full

    def get_page_images(self, page_number: int, zoom: float = 1.5) -> List[Dict]:
        """
        Extract image positions from a page.
        Uses get_image_info as primary (best detection coverage).
        Falls back to get_images + get_image_rects and get_text dict.
        Each result carries an 'xref' when available so extract_image_bytes
        can locate the actual image data without relying on index alignment.
        """
        if not self.doc or page_number < 0 or page_number >= self.page_count:
            return []
        page = self.doc.load_page(page_number)
        results = []
        seen_bboxes = set()

        def add_result(index, x0, y0, x1, y1, xref=0):
            key = (round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2))
            if key in seen_bboxes:
                return
            seen_bboxes.add(key)
            if (x1 - x0) >= 1 and (y1 - y0) >= 1:
                results.append({
                    "index": len(results),
                    "xref": xref,
                    "x": x0 * zoom, "y": y0 * zoom,
                    "width": (x1 - x0) * zoom, "height": (y1 - y0) * zoom,
                })

        # Method 1: get_image_info (best detection, includes xref in PyMuPDF 1.23+)
        try:
            infos = page.get_image_info(hashes=False)

            for idx, info in enumerate(infos):
                bbox = info.get("bbox")
                xref = info.get("xref", 0)
                if bbox:
                    add_result(idx, *bbox, xref=xref)
        except Exception:
            pass

        # Method 2: get_images + get_image_rects (for images missed by get_image_info)
        try:
            image_list = page.get_images(full=True)
            for idx, img in enumerate(image_list):
                xref = img[0]
                try:
                    rects = page.get_image_rects(xref)
                    for r in rects:
                        add_result(idx, r.x0, r.y0, r.x1, r.y1, xref=xref)
                except Exception:
                    pass
        except Exception:
            pass

        # Method 3: get_text("dict") image blocks (covers XObject/Form images)
        if not results:
            try:
                blocks = page.get_text("dict").get("blocks", [])
                for b in blocks:
                    if b.get("type") == 1:
                        bbox = b.get("bbox")
                        if bbox:
                            add_result(0, *bbox, xref=0)
            except Exception:
                pass

        return results

    def get_page_links(self, page_number: int, zoom: float = 1.5) -> List[Dict]:
        """
        Extract clickable links from a page with their bounding boxes.
        Returns list of dicts: {
            'kind': 'goto' | 'uri',
            'x': float, 'y': float, 'width': float, 'height': float,
            'target_page': int, 'target_y': float,
            'uri': str
        }
        Coordinates are scaled by zoom.
        """
        if not self.doc or page_number < 0 or page_number >= self.page_count:
            return []
        page = self.doc.load_page(page_number)
        links = page.get_links()
        results = []
        for link in links:
            rect = link.get("from")
            if not rect:
                continue
            kind = link.get("kind", 0)
            entry = {
                "x": rect.x0 * zoom,
                "y": rect.y0 * zoom,
                "width": (rect.x1 - rect.x0) * zoom,
                "height": (rect.y1 - rect.y0) * zoom,
                "target_page": -1,
                "target_y": 0,
                "uri": "",
            }
            if kind == 1:  # internal goto
                entry["kind"] = "goto"
                entry["target_page"] = link.get("page", -1)
                to_point = link.get("to")
                if hasattr(to_point, "y"):
                    entry["target_y"] = to_point.y * zoom
            elif kind == 2:  # external URI
                entry["kind"] = "uri"
                entry["uri"] = link.get("uri", "")
            else:
                continue
            results.append(entry)
        return results

    def extract_image_bytes(self, page_number: int, image_index: int) -> Optional[bytes]:
        """
        Extract raw image bytes from a specific image on a page.
        Tries get_image_info first (for xref), then falls back to get_images index.
        """
        if not self.doc or page_number < 0 or page_number >= self.page_count:

            return None
        page = self.doc.load_page(page_number)

        # Try get_image_info first (xref is available in PyMuPDF 1.23+)
        try:
            infos = page.get_image_info(hashes=False)
            if image_index < len(infos):
                xref = infos[image_index].get("xref", 0)
                if xref:
                    base_image = self.doc.extract_image(xref)
                    img_data = base_image.get("image")

                    return img_data
        except Exception:
            pass

        # Fallback: use get_images() list index
        try:
            image_list = page.get_images(full=True)
            if image_index < 0 or image_index >= len(image_list):

                return None
            xref = image_list[image_index][0]
            base_image = self.doc.extract_image(xref)
            img_data = base_image.get("image")

            return img_data
        except Exception:
            return None

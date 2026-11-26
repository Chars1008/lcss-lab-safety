"""Supplier SDS PDF text extraction and preview thumbnail generator using PyMuPDF."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import fitz


class PDFParser:
    """Extracts text and page thumbnails from supplier SDS PDFs."""

    def extract_text(self, pdf_path: Path | str, max_pages: int = 12) -> str:
        """Extract plain text from up to max_pages of a PDF file."""
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"找不到 PDF 檔案：{path}")
        chunks: list[str] = []
        with fitz.open(str(path)) as doc:
            for idx, page in enumerate(doc):
                if idx >= max_pages:
                    break
                chunks.append(page.get_text("text"))
        return "\n".join(chunks).strip()

    def render_first_page_png(
        self,
        pdf_path: Path | str,
        output_png: Optional[Path | str] = None,
        zoom: float = 1.5,
    ) -> bytes:
        """Render the first page of a PDF as PNG bytes (and optionally save to file)."""
        path = Path(pdf_path)
        with fitz.open(str(path)) as doc:
            if len(doc) == 0:
                return b""
            page = doc[0]
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            png_bytes = pix.tobytes("png")
        if output_png is not None:
            out = Path(output_png)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(png_bytes)
        return png_bytes

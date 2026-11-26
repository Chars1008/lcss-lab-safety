"""16-section Taiwanese GHS SDS HTML/PDF generator & bottle label generator."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Optional

import qrcode
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from app.config import DATA_DIR
from app.schemas import LabelRequest, SDSPayload


def _ensure_qt_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app  # type: ignore[return-value]


class SDSGenerator:
    """Renders 16-section SDS and bottle/prepared-reagent labels to HTML and PDF."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self.data_dir = data_dir or DATA_DIR
        self.templates_dir = self.data_dir / "templates"
        self.pictograms_dir = self.data_dir / "ghs_pictograms"
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def _svg_data_uri(self, code: str) -> Optional[str]:
        """Render GHS SVG pictogram to crisp PNG data URI for reliable QTextDocument PDF output."""
        svg_path = self.pictograms_dir / f"{code}.svg"
        if not svg_path.exists():
            return None
        _ensure_qt_app()
        renderer = QSvgRenderer(str(svg_path))
        if not renderer.isValid():
            return None
        img = QImage(128, 128, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        renderer.render(painter)
        painter.end()

        qbuf = QBuffer()
        qbuf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(qbuf, "PNG")
        b64 = base64.b64encode(bytes(qbuf.data())).decode("ascii")
        return f"data:image/png;base64,{b64}"

    def _qr_data_uri(self, text: str) -> str:
        img = qrcode.make(text)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"

    def render_sds_html(self, sds: SDSPayload) -> str:
        """Render 16-section SDS HTML string."""
        template = self.env.get_template("sds_16_sections.html")
        pictogram_uris = [
            uri for code in sds.ghs_pictograms if (uri := self._svg_data_uri(code)) is not None
        ]
        return template.render(
            sds=sds,
            pictogram_uris=pictogram_uris,
            generated_at_str=sds.generated_at.strftime("%Y-%m-%d %H:%M"),
        )

    def export_sds_pdf(self, sds: SDSPayload, output_path: Path | str) -> Path:
        """Export 16-section SDS to PDF using Qt QTextDocument + QPrinter."""
        html = self.render_sds_html(sds)
        return self._html_to_pdf(html, Path(output_path), page_size=QPageSize.PageSizeId.A4)

    def render_label_html(self, label: LabelRequest) -> str:
        """Render bottle / prepared reagent label HTML string."""
        template = self.env.get_template("bottle_label.html")
        pictogram_uris = [
            uri for code in label.ghs_pictograms if (uri := self._svg_data_uri(code)) is not None
        ]
        qr_payload = f"GLCSS|{label.barcode}|{label.cas_number}|{label.name_zh}"
        qr_uri = self._qr_data_uri(qr_payload)
        return template.render(
            label=label,
            pictogram_uris=pictogram_uris,
            qr_uri=qr_uri,
        )

    def export_label_pdf(self, label: LabelRequest, output_path: Path | str) -> Path:
        """Export bottle / prepared reagent label to PDF."""
        html = self.render_label_html(label)
        return self._html_to_pdf(html, Path(output_path), page_size=QPageSize.PageSizeId.A5)

    def _html_to_pdf(
        self,
        html: str,
        output_path: Path,
        page_size: QPageSize.PageSizeId = QPageSize.PageSizeId.A4,
    ) -> Path:
        _ensure_qt_app()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(output_path))
        printer.setPageSize(QPageSize(page_size))
        printer.setPageOrientation(QPageLayout.Orientation.Portrait)

        doc = QTextDocument()
        doc.setHtml(html)
        doc.print_(printer)
        return output_path

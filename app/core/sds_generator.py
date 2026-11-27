"""16-section Taiwanese GHS SDS HTML/PDF generator & bottle label generator."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Literal, Optional

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
        hp_en_path = self.data_dir / "ghs_hp_en.json"
        self._hp_en = (
            json.loads(hp_en_path.read_text(encoding="utf-8"))
            if hp_en_path.exists()
            else {"h_codes": {}, "p_codes": {}}
        )

    def _svg_data_uri(self, code: str) -> Optional[str]:
        """Load exact GHS PNG pictogram (or render SVG fallback) as PNG data URI."""
        png_path = self.pictograms_dir / f"{code}.png"
        if png_path.exists():
            b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
            return f"data:image/png;base64,{b64}"

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

    def _prepare_english_sds(self, sds: SDSPayload) -> tuple[SDSPayload, str, list[str], list[str]]:
        """Prepare English signal word, H/P statements, and fallback English defaults."""
        sig_map = {"危險": "Danger", "警告": "Warning", None: "None", "": "None"}
        signal_en = sig_map.get(sds.signal_word, sds.signal_word or "None")
        h_tbl = self._hp_en.get("h_codes", {})
        p_tbl = self._hp_en.get("p_codes", {})
        h_en = [f"{c}: {h_tbl[c]}" if c in h_tbl else c for c in sds.h_codes]
        p_en = [f"{c}: {p_tbl[c]}" if c in p_tbl else c for c in sds.p_codes]

        defaults = SDSPayload(cas_number=sds.cas_number)
        en_defaults = {
            "recommended_use": "Laboratory teaching, analysis, and research.",
            "first_aid_ingestion": "1. Never give anything by mouth to an unconscious person.\n2. Rinse mouth with water. Do NOT induce vomiting.\n3. Seek medical attention immediately.",
            "first_aid_inhalation": "1. Remove victim to fresh air and keep at rest in a position comfortable for breathing.\n2. Seek medical attention if symptoms persist.",
            "first_aid_eye": "1. Rinse cautiously with water for at least 10-15 minutes.\n2. Remove contact lenses if present and easy to do.\n3. Seek medical attention immediately.",
            "first_aid_skin": "1. Take off contaminated clothing immediately.\n2. Wash skin with plenty of water for at least 5-15 minutes.\n3. Seek medical attention if irritation persists.",
            "first_aid_symptoms": "May cause irritation, redness, or systemic effects depending on exposure route.",
            "first_aid_rescuer_ppe": "Wear appropriate PPE (chemical-resistant gloves, goggles, protective clothing).",
            "first_aid_physician_note": "Treat symptomatically and supportively.",
            "fire_extinguishing_media": "Water spray, carbon dioxide, dry chemical powder, or alcohol-resistant foam.",
            "fire_special_hazards": "May emit toxic or irritating fumes when heated to decomposition.",
            "fire_procedures": "1. Fight fire from a safe distance and upwind.\n2. Cool exposed containers with water spray.",
            "fire_ppe": "Wear self-contained breathing apparatus (SCBA) and full chemical protective suit.",
            "release_personal": "1. Restrict access to area until cleanup is complete.\n2. Wear appropriate PPE.",
            "release_env": "1. Ventilate area and eliminate ignition sources.\n2. Prevent entry into sewers or waterways.",
            "release_cleanup": "Absorb with inert material and place in labeled waste container for disposal.",
            "handling_notes": "1. Handle in a chemical fume hood with proper training.\n2. Avoid contact with incompatible materials.",
            "storage_notes": "1. Store in a cool, dry, well-ventilated area away from heat and incompatible materials.\n2. Keep container tightly closed.",
            "eng_controls": "Use local exhaust ventilation or chemical fume hood; provide eyewash and safety shower.",
            "ppe_hands": "Chemical-resistant gloves (Nitrile, Butyl, or Viton).",
            "ppe_skin_body": "Lab coat or chemical protective suit.",
            "ppe_respiratory": "Use approved respirator if ventilation is inadequate.",
            "ppe_eyes": "Chemical safety goggles / face shield.",
            "hygiene_measures": "Wash hands thoroughly after handling. Do not eat, drink, or smoke in work area.",
            "stability": "Stable under normal ambient conditions.",
            "hazardous_reactions": "May react violently with incompatible materials (strong acids, bases, or oxidizers).",
            "conditions_to_avoid": "Heat, sparks, open flames, direct sunlight.",
            "materials_to_avoid": "Strong acids, strong bases, strong oxidizing agents.",
            "decomp_products": "Carbon oxides, nitrogen oxides, or corrosive gases.",
            "tox_routes": "Skin contact, inhalation, ingestion, eye contact.",
            "tox_symptoms": "Irritation or systemic toxicity depending on dose and route.",
            "disposal_methods": "Dispose of contents/container in accordance with local and institutional hazardous waste regulations.",
            "regulations": "Applicable occupational health, chemical labeling, and hazardous waste regulations.",
            "preparer_org": "Ginsi Laboratory Chemical Safety System (GLCSS)",
        }
        updates: dict[str, str] = {}
        for field_name, en_val in en_defaults.items():
            if getattr(sds, field_name) == getattr(defaults, field_name):
                updates[field_name] = en_val
        en_sds = sds.model_copy(update=updates) if updates else sds
        return en_sds, signal_en, h_en, p_en

    def render_sds_html(
        self,
        sds: SDSPayload,
        language: Literal["zh-TW", "en"] = "zh-TW",
    ) -> str:
        """Render 16-section SDS HTML string in Traditional Chinese or English."""
        pictogram_uris = [
            uri for code in sds.ghs_pictograms if (uri := self._svg_data_uri(code)) is not None
        ]
        if language == "en":
            en_sds, signal_en, h_en, p_en = self._prepare_english_sds(sds)
            template = self.env.get_template("sds_16_sections_en.html")
            return template.render(
                sds=en_sds,
                pictogram_uris=pictogram_uris,
                signal_word_en=signal_en,
                h_statements_en=h_en,
                p_statements_en=p_en,
                generated_at_str=sds.generated_at.strftime("%Y-%m-%d %H:%M"),
            )

        template = self.env.get_template("sds_16_sections.html")
        return template.render(
            sds=sds,
            pictogram_uris=pictogram_uris,
            generated_at_str=sds.generated_at.strftime("%Y-%m-%d %H:%M"),
        )

    def export_sds_pdf(
        self,
        sds: SDSPayload,
        output_path: Path | str,
        language: Literal["zh-TW", "en"] = "zh-TW",
    ) -> Path:
        """Export 16-section SDS to PDF using Qt QTextDocument + QPrinter."""
        html = self.render_sds_html(sds, language=language)
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

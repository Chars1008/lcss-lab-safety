"""SDS editor, PDF export, bottle label generator, and supplier PDF archive view."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import AppSettings, EXPORTS_DIR, LABELS_DIR, SDS_FILES_DIR
from app.core.chem_resolver import ChemResolver
from app.core.llm_service import LocalLLMService
from app.core.pdf_parser import PDFParser
from app.core.sds_generator import SDSGenerator
from app.db.database import DatabaseManager
from app.db.repository import LCSSRepository
from app.schemas import ItemType, LabelRequest, SDSPayload
from app.ui.workers import AsyncWorker


class SDSView(QWidget):
    """16-section SDS editor/exporter, supplier PDF importer, and bottle label printer."""

    def __init__(
        self,
        db: DatabaseManager,
        settings: AppSettings,
        resolver: ChemResolver,
        sds_gen: SDSGenerator,
        pdf_parser: PDFParser,
        llm_service: LocalLLMService,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.resolver = resolver
        self.sds_gen = sds_gen
        self.pdf_parser = pdf_parser
        self.llm_service = llm_service
        self.thread_pool = QThreadPool.globalInstance()
        self._current_chem_id: Optional[int] = None
        self._current_payload: Optional[SDSPayload] = None

        layout = QVBoxLayout(self)
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("選擇化學品："))
        self.chem_combo = QComboBox()
        self.chem_combo.currentIndexChanged.connect(self._on_chem_changed)
        reload_btn = QPushButton("重新載入")
        reload_btn.clicked.connect(self.reload_chemicals)
        top_row.addWidget(self.chem_combo, 1)
        top_row.addWidget(reload_btn)
        layout.addLayout(top_row)

        form = QFormLayout()
        self.sec4_edit = QTextEdit()
        self.sec4_edit.setMaximumHeight(65)
        self.sec5_edit = QTextEdit()
        self.sec5_edit.setMaximumHeight(65)
        self.sec7_edit = QTextEdit()
        self.sec7_edit.setMaximumHeight(65)
        self.supplier_edit = QLineEdit()

        form.addRow("第 1 節 供應商：", self.supplier_edit)
        form.addRow("第 4 節 急救措施：", self.sec4_edit)
        form.addRow("第 5 節 滅火措施：", self.sec5_edit)
        form.addRow("第 7 節 儲存處置：", self.sec7_edit)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("儲存 SDS 編輯")
        save_btn.clicked.connect(self._on_save_sds)
        export_sds_btn = QPushButton("匯出 16 大項 SDS PDF")
        export_sds_btn.setStyleSheet("background: #1e3a8a; color: #fff; font-weight: bold; padding: 6px;")
        export_sds_btn.clicked.connect(self._on_export_sds_pdf)
        export_lbl_btn = QPushButton("匯出瓶身 GHS 標籤 PDF")
        export_lbl_btn.clicked.connect(self._on_export_label_pdf)
        import_pdf_btn = QPushButton("歸檔並解析原廠 PDF")
        import_pdf_btn.clicked.connect(self._on_import_supplier_pdf)
        llm_btn = QPushButton("Ollama 潤飾翻譯")
        llm_btn.clicked.connect(self._on_llm_polish)

        for b in (save_btn, export_sds_btn, export_lbl_btn, import_pdf_btn, llm_btn):
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        self.status_lbl = QLabel("提示：所有自動生成之 SDS 皆標註「系統彙整內部參考版」。")
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)
        layout.addStretch(1)

        self.reload_chemicals()

    def reload_chemicals(self) -> None:
        self.chem_combo.clear()
        with self.db.get_session() as session:
            for c in LCSSRepository(session).search_chemicals():
                self.chem_combo.addItem(f"{c.name_zh or c.name_en} ({c.cas_number})", c.id)

    def _on_chem_changed(self) -> None:
        chem_id = self.chem_combo.currentData()
        self._current_chem_id = chem_id
        if chem_id is None:
            self._current_payload = None
            return
        with self.db.get_session() as session:
            chem = LCSSRepository(session).get_chemical_by_id(chem_id)
            if chem is None:
                return
            if chem.sds_json:
                payload = SDSPayload(**chem.sds_json)
            else:
                payload = SDSPayload(
                    cas_number=chem.cas_number,
                    name_zh=chem.name_zh,
                    name_en=chem.name_en,
                    formula=chem.formula,
                    molecular_weight=chem.molecular_weight,
                    smiles=chem.smiles,
                    ghs_pictograms=chem.ghs_pictograms,
                    signal_word=chem.signal_word,
                    h_codes=chem.h_codes,
                    p_codes=chem.p_codes,
                    h_statements_zh=self.resolver.translate_h_codes(chem.h_codes),
                    p_statements_zh=self.resolver.translate_p_codes(chem.p_codes),
                )
        payload.emergency_phone = self.settings.emergency_phone
        self._current_payload = payload
        self.supplier_edit.setText(payload.supplier_info)
        self.sec4_edit.setPlainText(payload.section_4_first_aid)
        self.sec5_edit.setPlainText(payload.section_5_fire_fighting)
        self.sec7_edit.setPlainText(payload.section_7_handling_storage)

    def _collect_payload(self) -> Optional[SDSPayload]:
        if self._current_payload is None:
            return None
        return self._current_payload.model_copy(
            update={
                "supplier_info": self.supplier_edit.text().strip(),
                "section_4_first_aid": self.sec4_edit.toPlainText().strip(),
                "section_5_fire_fighting": self.sec5_edit.toPlainText().strip(),
                "section_7_handling_storage": self.sec7_edit.toPlainText().strip(),
                "emergency_phone": self.settings.emergency_phone,
            }
        )

    def _on_save_sds(self) -> None:
        payload = self._collect_payload()
        if payload is None or self._current_chem_id is None:
            return
        self._current_payload = payload
        with self.db.get_session() as session:
            LCSSRepository(session).update_chemical_sds(self._current_chem_id, payload.model_dump(mode="json"))
        self.status_lbl.setText("已儲存 SDS 修改至本地資料庫。")

    def _on_export_sds_pdf(self) -> None:
        payload = self._collect_payload()
        if payload is None:
            return
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        default_path = EXPORTS_DIR / f"SDS_{payload.cas_number}.pdf"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "匯出 SDS PDF", str(default_path), "PDF Files (*.pdf)"
        )
        if not file_path:
            return
        out = self.sds_gen.export_sds_pdf(payload, file_path)
        self.status_lbl.setText(f"已匯出 16 節 SDS PDF：{out}")
        QMessageBox.information(self, "匯出成功", f"已儲存至：\n{out}")

    def _on_export_label_pdf(self) -> None:
        payload = self._collect_payload()
        if payload is None:
            return
        LABELS_DIR.mkdir(parents=True, exist_ok=True)
        default_path = LABELS_DIR / f"Label_{payload.cas_number}.pdf"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "匯出瓶身標籤 PDF", str(default_path), "PDF Files (*.pdf)"
        )
        if not file_path:
            return
        req = LabelRequest(
            item_type=ItemType.COMMERCIAL,
            name_zh=payload.name_zh or payload.name_en,
            name_en=payload.name_en,
            cas_number=payload.cas_number,
            barcode=f"CAS-{payload.cas_number}",
            ghs_pictograms=payload.ghs_pictograms,
            signal_word=payload.signal_word,
            hazard_summary="; ".join(payload.h_codes[:4]),
        )
        out = self.sds_gen.export_label_pdf(req, file_path)
        self.status_lbl.setText(f"已匯出瓶身標籤 PDF：{out}")
        QMessageBox.information(self, "匯出成功", f"標籤已儲存至：\n{out}")

    def _on_import_supplier_pdf(self) -> None:
        if self._current_chem_id is None or self._current_payload is None:
            return
        src_path, _ = QFileDialog.getOpenFileName(self, "選擇原廠 SDS PDF", "", "PDF Files (*.pdf)")
        if not src_path:
            return
        SDS_FILES_DIR.mkdir(parents=True, exist_ok=True)
        dest = SDS_FILES_DIR / f"{self._current_payload.cas_number}_{Path(src_path).name}"
        shutil.copy2(src_path, dest)
        with self.db.get_session() as session:
            LCSSRepository(session).add_sds_document(self._current_chem_id, str(dest))
        text = self.pdf_parser.extract_text(dest, max_pages=4)
        self.status_lbl.setText(f"已歸檔原廠 PDF：{dest.name}（擷取 {len(text)} 字元）")

    def _on_llm_polish(self) -> None:
        payload = self._collect_payload()
        if payload is None:
            return
        if not self.llm_service.enabled:
            QMessageBox.information(self, "Ollama 未啟用", "請先於「系統設定」啟用 Local LLM（Ollama）。")
            return
        self.status_lbl.setText("正在透過 Ollama 進行繁體中文潤飾...")
        worker = AsyncWorker(self.llm_service.translate_sds_fields, payload)
        worker.signals.finished.connect(self._on_llm_done)
        self.thread_pool.start(worker)

    def _on_llm_done(self, updated: SDSPayload) -> None:
        self._current_payload = updated
        self.sec4_edit.setPlainText(updated.section_4_first_aid)
        self.sec5_edit.setPlainText(updated.section_5_fire_fighting)
        self.sec7_edit.setPlainText(updated.section_7_handling_storage)
        self.status_lbl.setText("Ollama 潤飾完成（請人工檢視後再儲存或匯出）。")

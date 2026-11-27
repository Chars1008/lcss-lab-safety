"""Emergency Process view: Local LLM + deterministic SDS emergency SOP generator (spill, contact, ingestion, fire)."""

from __future__ import annotations

import html as html_lib
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import AppSettings
from app.core.chem_resolver import ChemResolver
from app.core.llm_service import LocalLLMService
from app.core.sds_generator import SDSGenerator
from app.db.database import DatabaseManager
from app.db.repository import LCSSRepository
from app.schemas import SDSPayload
from app.ui.widgets.common import GHSPictogramStrip
from app.ui.workers import AsyncWorker


class EmergencyProcessView(QWidget):
    """Generates actionable emergency response SOPs from SDS using Local LLM or offline rules."""

    def __init__(
        self,
        db: DatabaseManager,
        settings: AppSettings,
        resolver: ChemResolver,
        sds_gen: SDSGenerator,
        llm_service: LocalLLMService,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.resolver = resolver
        self.sds_gen = sds_gen
        self.llm_service = llm_service
        self.thread_pool = QThreadPool.globalInstance()
        self._current_payload: Optional[SDSPayload] = None

        layout = QVBoxLayout(self)
        self.title_lbl = QLabel("緊急應變流程 (Emergency Process)")
        self.title_lbl.setStyleSheet("font-size: 13pt; font-weight: bold;")
        layout.addWidget(self.title_lbl)

        top_row = QHBoxLayout()
        self.select_lbl = QLabel("選擇化學品：")
        self.chem_combo = QComboBox()
        self.chem_combo.currentIndexChanged.connect(self._on_chem_changed)
        self.reload_btn = QPushButton("重新載入")
        self.reload_btn.clicked.connect(self.reload_chemicals)
        self.llm_btn = QPushButton("以 Local LLM 生成應變流程")
        self.llm_btn.setStyleSheet("background: #b91c1c; color: #fff; font-weight: bold; padding: 6px 12px;")
        self.llm_btn.clicked.connect(self._on_generate_llm)
        self.export_btn = QPushButton("匯出應變 SOP PDF")
        self.export_btn.clicked.connect(self._on_export_pdf)

        top_row.addWidget(self.select_lbl)
        top_row.addWidget(self.chem_combo, 1)
        top_row.addWidget(self.reload_btn)
        top_row.addWidget(self.llm_btn)
        top_row.addWidget(self.export_btn)
        layout.addLayout(top_row)

        info_row = QHBoxLayout()
        self.emergency_banner = QLabel(f"緊急聯絡電話：{settings.emergency_phone}")
        self.emergency_banner.setStyleSheet(
            "background: #fef2f2; border: 1px solid #ef4444; color: #991b1b; padding: 5px 10px; border-radius: 4px; font-weight: bold;"
        )
        self.ghs_strip = GHSPictogramStrip()
        info_row.addWidget(self.emergency_banner, 1)
        info_row.addWidget(self.ghs_strip)
        layout.addLayout(info_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        vbox = QVBoxLayout(container)

        self.box_spill = QGroupBox("1. 外洩應變流程 (Spill / Release Response)")
        self.txt_spill = QTextEdit()
        self.txt_spill.setMinimumHeight(90)
        QVBoxLayout(self.box_spill).addWidget(self.txt_spill)

        self.box_contact = QGroupBox("2. 皮膚與眼睛接觸急救 (Skin & Eye Contact First Aid)")
        self.txt_contact = QTextEdit()
        self.txt_contact.setMinimumHeight(90)
        QVBoxLayout(self.box_contact).addWidget(self.txt_contact)

        self.box_ingest = QGroupBox("3. 吸入與誤食急救 (Inhalation & Ingestion First Aid)")
        self.txt_ingest = QTextEdit()
        self.txt_ingest.setMinimumHeight(95)
        QVBoxLayout(self.box_ingest).addWidget(self.txt_ingest)

        self.box_fire = QGroupBox("4. 火災與不相容反應處置 (Fire & Incompatible Reaction)")
        self.txt_fire = QTextEdit()
        self.txt_fire.setMinimumHeight(90)
        QVBoxLayout(self.box_fire).addWidget(self.txt_fire)

        for box in (self.box_spill, self.box_contact, self.box_ingest, self.box_fire):
            vbox.addWidget(box)
        vbox.addStretch(1)

        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        self.status_lbl = QLabel("提示：已自動從 SDS 載入標準應變流程；點擊「以 Local LLM 生成應變流程」可由本機 AI 彙整更精簡明確的處置步驟。")
        layout.addWidget(self.status_lbl)

        self.reload_chemicals()

    def reload_chemicals(self) -> None:
        prev_id = self.chem_combo.currentData()
        self.chem_combo.blockSignals(True)
        try:
            self.chem_combo.clear()
            with self.db.get_session() as session:
                for c in LCSSRepository(session).search_chemicals():
                    self.chem_combo.addItem(f"{c.name_zh or c.name_en} ({c.cas_number})", c.id)
            if prev_id is not None:
                idx = self.chem_combo.findData(prev_id)
                if idx >= 0:
                    self.chem_combo.setCurrentIndex(idx)
        finally:
            self.chem_combo.blockSignals(False)
        self._on_chem_changed()

    def _on_chem_changed(self) -> None:
        chem_id = self.chem_combo.currentData()
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
                payload = self.resolver._build_sds_payload(
                    cas=chem.cas_number,
                    name_zh=chem.name_zh,
                    name_en=chem.name_en,
                    formula=chem.formula,
                    mw=chem.molecular_weight,
                    smiles=chem.smiles,
                    inchikey=chem.inchikey,
                    pictograms=chem.ghs_pictograms,
                    signal_word=chem.signal_word,
                    h_codes=chem.h_codes,
                    p_codes=chem.p_codes,
                    data_source=chem.data_source,
                )
        self._current_payload = payload
        self.ghs_strip.set_pictograms(payload.ghs_pictograms)
        self.emergency_banner.setText(
            f"{payload.name_zh or payload.name_en} ({payload.cas_number}) ｜ 緊急聯絡：{self.settings.emergency_phone}"
        )
        # Load deterministic offline SOP immediately
        sop = LocalLLMService(enabled=False).generate_emergency_process(
            payload, language=self.settings.ui_language
        )
        self._apply_sop(sop)

    def _apply_sop(self, sop: dict[str, str]) -> None:
        self.txt_spill.setPlainText(sop.get("spill", ""))
        self.txt_contact.setPlainText(sop.get("contact", ""))
        self.txt_ingest.setPlainText(sop.get("ingestion_inhalation", ""))
        self.txt_fire.setPlainText(sop.get("fire_reactivity", ""))
        self.status_lbl.setText(f"應變流程來源：{sop.get('source', 'OFFLINE_SDS_RULES')}")

    def _on_generate_llm(self) -> None:
        if self._current_payload is None:
            return
        if not self.llm_service.enabled:
            QMessageBox.information(
                self,
                "Ollama 未啟用",
                "請先於「設定」啟用 Local LLM（Ollama），目前已顯示離線 SDS 標準應變流程。",
            )
            return
        self.llm_btn.setEnabled(False)
        self.status_lbl.setText(f"正在透過 Ollama ({self.llm_service.model}) 解讀 SDS 並生成緊急應變流程...")
        worker = AsyncWorker(
            self.llm_service.generate_emergency_process,
            self._current_payload,
            self.settings.ui_language,
        )
        worker.signals.finished.connect(self._on_llm_done)
        worker.signals.error.connect(self._on_llm_error)
        self.thread_pool.start(worker)

    def _on_llm_done(self, sop: dict[str, str]) -> None:
        self.llm_btn.setEnabled(True)
        self._apply_sop(sop)
        if self.llm_service.last_error:
            QMessageBox.warning(self, "Ollama 提醒", self.llm_service.last_error)

    def _on_llm_error(self, err: str) -> None:
        self.llm_btn.setEnabled(True)
        self.status_lbl.setText(f"生成失敗：{err.splitlines()[0]}")

    def _on_export_pdf(self) -> None:
        if self._current_payload is None:
            return
        exports_dir = Path(self.settings.exports_dir)
        exports_dir.mkdir(parents=True, exist_ok=True)
        default_path = exports_dir / f"Emergency_SOP_{self._current_payload.cas_number}.pdf"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "匯出緊急應變流程 PDF", str(default_path), "PDF Files (*.pdf)"
        )
        if not file_path:
            return

        p = self._current_payload
        html = (
            "<html><body style='font-family: Microsoft JhengHei, sans-serif; font-size: 10pt;'>"
            f"<h1 style='color:#991b1b; border-bottom:2px solid #991b1b;'>緊急應變流程 (Emergency Process)</h1>"
            f"<p><b>化學品：</b>{html_lib.escape(p.name_zh or p.name_en)} ({html_lib.escape(p.name_en)}) ｜ <b>CAS：</b>{html_lib.escape(p.cas_number)}<br>"
            f"<b>緊急聯絡電話：</b>{html_lib.escape(self.settings.emergency_phone)}</p>"
            f"<h3>1. 外洩應變流程 (Spill / Release)</h3><pre style='white-space:pre-wrap;'>{html_lib.escape(self.txt_spill.toPlainText())}</pre>"
            f"<h3>2. 皮膚與眼睛接觸急救 (Skin &amp; Eye Contact)</h3><pre style='white-space:pre-wrap;'>{html_lib.escape(self.txt_contact.toPlainText())}</pre>"
            f"<h3>3. 吸入與誤食急救 (Inhalation &amp; Ingestion)</h3><pre style='white-space:pre-wrap;'>{html_lib.escape(self.txt_ingest.toPlainText())}</pre>"
            f"<h3>4. 火災與不相容反應處置 (Fire &amp; Reactivity)</h3><pre style='white-space:pre-wrap;'>{html_lib.escape(self.txt_fire.toPlainText())}</pre>"
            "</body></html>"
        )
        out = self.sds_gen._html_to_pdf(html, Path(file_path))
        QMessageBox.information(self, "匯出成功", f"已儲存至：\n{out}")

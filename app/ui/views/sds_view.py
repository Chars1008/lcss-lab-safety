"""SDS editor (16-section tabbed editor), PDF export, bottle label generator, and supplier PDF archive view."""

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
    QScrollArea,
    QTabWidget,
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


def _make_scroll_tab(form: QFormLayout) -> QScrollArea:
    container = QWidget()
    container.setLayout(form)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(container)
    return scroll


class SDSView(QWidget):
    """16-section Taiwanese GHS SDS editor/exporter, supplier PDF importer, and label printer."""

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
        reload_btn = QPushButton("重新載入清單")
        reload_btn.clicked.connect(self.reload_chemicals)
        enrich_btn = QPushButton("線上補全物化/危害資料")
        enrich_btn.clicked.connect(self._on_enrich_online)
        top_row.addWidget(self.chem_combo, 1)
        top_row.addWidget(reload_btn)
        top_row.addWidget(enrich_btn)
        layout.addLayout(top_row)

        self.active_chem_banner = QLabel("目前編輯：尚未選擇化學品")
        self.active_chem_banner.setStyleSheet(
            "background: #eff6ff; border: 1px solid #93c5fd; padding: 6px 10px; border-radius: 4px; font-weight: bold; color: #1e3a8a;"
        )
        layout.addWidget(self.active_chem_banner)

        self.tabs = QTabWidget()

        # Tab 1: Sections 1-3 (Identification, Hazards, Composition)
        f1 = QFormLayout()
        self.epa_no_edit = QLineEdit()
        self.supplier_edit = QLineEdit()
        self.recommended_use_edit = QLineEdit()
        self.synonyms_edit = QLineEdit()
        self.conc_pct_edit = QLineEdit()
        self.preparer_org_edit = QLineEdit()
        self.preparer_name_edit = QLineEdit()
        f1.addRow("列管編號：", self.epa_no_edit)
        f1.addRow("第 1 節 供應商名稱/地址：", self.supplier_edit)
        f1.addRow("第 1 節 建議用途：", self.recommended_use_edit)
        f1.addRow("第 3 節 同義名稱：", self.synonyms_edit)
        f1.addRow("第 3 節 成分百分比：", self.conc_pct_edit)
        f1.addRow("第 16 節 製表者單位：", self.preparer_org_edit)
        f1.addRow("第 16 節 製表人姓名：", self.preparer_name_edit)
        self.tabs.addTab(_make_scroll_tab(f1), "1-3 辨識與製表")

        # Tab 2: Section 4-5 (First Aid & Fire Fighting)
        f2 = QFormLayout()
        self.fa_ingest_edit = QTextEdit()
        self.fa_inhale_edit = QTextEdit()
        self.fa_eye_edit = QTextEdit()
        self.fa_skin_edit = QTextEdit()
        self.fa_symptoms_edit = QTextEdit()
        self.fa_physician_edit = QTextEdit()
        self.fire_media_edit = QLineEdit()
        self.fire_hazards_edit = QTextEdit()
        self.fire_proc_edit = QTextEdit()
        for te in (
            self.fa_ingest_edit, self.fa_inhale_edit, self.fa_eye_edit, self.fa_skin_edit,
            self.fa_symptoms_edit, self.fa_physician_edit, self.fire_hazards_edit, self.fire_proc_edit,
        ):
            te.setMaximumHeight(58)
        f2.addRow("第 4 節 食入急救：", self.fa_ingest_edit)
        f2.addRow("第 4 節 吸入急救：", self.fa_inhale_edit)
        f2.addRow("第 4 節 眼睛接觸：", self.fa_eye_edit)
        f2.addRow("第 4 節 皮膚接觸：", self.fa_skin_edit)
        f2.addRow("第 4 節 最重要症狀：", self.fa_symptoms_edit)
        f2.addRow("第 4 節 對醫師提示：", self.fa_physician_edit)
        f2.addRow("第 5 節 適用滅火劑：", self.fire_media_edit)
        f2.addRow("第 5 節 特殊危害：", self.fire_hazards_edit)
        f2.addRow("第 5 節 滅火程序：", self.fire_proc_edit)
        self.tabs.addTab(_make_scroll_tab(f2), "4-5 急救與滅火")

        # Tab 3: Section 6-8 (Release, Handling/Storage, Exposure/PPE)
        f3 = QFormLayout()
        self.rel_cleanup_edit = QTextEdit()
        self.handling_edit = QTextEdit()
        self.storage_edit = QTextEdit()
        self.twa_edit = QLineEdit()
        self.stel_edit = QLineEdit()
        self.ppe_hands_edit = QLineEdit()
        self.ppe_resp_edit = QLineEdit()
        for te in (self.rel_cleanup_edit, self.handling_edit, self.storage_edit):
            te.setMaximumHeight(64)
        f3.addRow("第 6 節 清理方法：", self.rel_cleanup_edit)
        f3.addRow("第 7 節 安全處置：", self.handling_edit)
        f3.addRow("第 7 節 儲存方法：", self.storage_edit)
        f3.addRow("第 8 節 八小時 TWA：", self.twa_edit)
        f3.addRow("第 8 節 短時間 STEL：", self.stel_edit)
        f3.addRow("第 8 節 手部防護：", self.ppe_hands_edit)
        f3.addRow("第 8 節 呼吸防護：", self.ppe_resp_edit)
        self.tabs.addTab(_make_scroll_tab(f3), "6-8 洩漏/儲運/暴露")

        # Tab 4: Section 9-10 (Physical Properties & Stability/Reactivity)
        f4 = QFormLayout()
        self.phys_app_edit = QLineEdit()
        self.phys_odor_edit = QLineEdit()
        self.phys_mp_edit = QLineEdit()
        self.phys_bp_edit = QLineEdit()
        self.phys_ph_edit = QLineEdit()
        self.phys_density_edit = QLineEdit()
        self.phys_sol_edit = QLineEdit()
        self.materials_avoid_edit = QTextEdit()
        self.materials_avoid_edit.setMaximumHeight(58)
        f4.addRow("第 9 節 外觀狀態：", self.phys_app_edit)
        f4.addRow("第 9 節 氣味：", self.phys_odor_edit)
        f4.addRow("第 9 節 熔點：", self.phys_mp_edit)
        f4.addRow("第 9 節 沸點：", self.phys_bp_edit)
        f4.addRow("第 9 節 pH 值：", self.phys_ph_edit)
        f4.addRow("第 9 節 密度：", self.phys_density_edit)
        f4.addRow("第 9 節 溶解度：", self.phys_sol_edit)
        f4.addRow("第 10 節 應避免之物質：", self.materials_avoid_edit)
        self.tabs.addTab(_make_scroll_tab(f4), "9-10 物化與反應性")

        # Tab 5: Section 11-15 (Tox, Eco, Disposal, Transport, Regulations)
        f5 = QFormLayout()
        self.tox_ld50_edit = QLineEdit()
        self.tox_chronic_edit = QTextEdit()
        self.eco_tox_edit = QTextEdit()
        self.disposal_edit = QTextEdit()
        self.un_no_edit = QLineEdit()
        self.transport_cls_edit = QLineEdit()
        self.erg_edit = QLineEdit()
        for te in (self.tox_chronic_edit, self.eco_tox_edit, self.disposal_edit):
            te.setMaximumHeight(58)
        f5.addRow("第 11 節 LD50：", self.tox_ld50_edit)
        f5.addRow("第 11 節 慢毒性：", self.tox_chronic_edit)
        f5.addRow("第 12 節 生態毒性：", self.eco_tox_edit)
        f5.addRow("第 13 節 廢棄處置：", self.disposal_edit)
        f5.addRow("第 14 節 UN 編號：", self.un_no_edit)
        f5.addRow("第 14 節 運輸危害分類：", self.transport_cls_edit)
        f5.addRow("第 14 節 緊急應變原則：", self.erg_edit)
        self.tabs.addTab(_make_scroll_tab(f5), "11-15 毒理/生態/運送")

        layout.addWidget(self.tabs, 1)

        btn_row = QHBoxLayout()
        btn_row.addWidget(QLabel("輸出語言："))
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("繁體中文 (zh-TW)", "zh-TW")
        self.lang_combo.addItem("English (en)", "en")

        save_btn = QPushButton("儲存 SDS 編輯")
        save_btn.clicked.connect(self._on_save_sds)
        export_sds_btn = QPushButton("匯出完整 16 大項 SDS PDF")
        export_sds_btn.setStyleSheet("background: #1e3a8a; color: #fff; font-weight: bold; padding: 6px;")
        export_sds_btn.clicked.connect(self._on_export_sds_pdf)
        export_lbl_btn = QPushButton("匯出瓶身 GHS 標籤 PDF")
        export_lbl_btn.clicked.connect(self._on_export_label_pdf)
        import_pdf_btn = QPushButton("歸檔並解析原廠 PDF")
        import_pdf_btn.clicked.connect(self._on_import_supplier_pdf)
        llm_btn = QPushButton("Ollama 中英翻譯")
        llm_btn.clicked.connect(self._on_llm_polish)

        btn_row.addWidget(self.lang_combo)
        for b in (save_btn, export_sds_btn, export_lbl_btn, import_pdf_btn, llm_btn):
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        self.status_lbl = QLabel("提示：所有自動生成之 SDS 皆符合台灣 16 大項表格規範並標註「系統彙整內部參考版」。")
        self.status_lbl.setWordWrap(True)
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

    def _on_chem_changed(self, _index: int = -1) -> None:
        chem_id = self.chem_combo.currentData()
        self._current_chem_id = chem_id
        if chem_id is None:
            self._current_payload = None
            self.active_chem_banner.setText("目前編輯：尚未選擇化學品（請先於「藥品庫存與入庫」解析並入庫）")
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
        payload.emergency_phone = self.settings.emergency_phone
        self._populate_form(payload)

    def _populate_form(self, payload: SDSPayload) -> None:
        self._current_payload = payload
        self.active_chem_banner.setText(
            f"目前編輯：{payload.name_zh or payload.name_en} ({payload.cas_number})"
            f" ｜ 警示語：{payload.signal_word or '無'}"
            f" ｜ 來源：{payload.data_source}"
        )
        self.epa_no_edit.setText(payload.epa_control_no)
        self.supplier_edit.setText(payload.supplier_info)
        self.recommended_use_edit.setText(payload.recommended_use)
        self.synonyms_edit.setText(payload.synonyms)
        self.conc_pct_edit.setText(payload.concentration_pct)
        self.preparer_org_edit.setText(payload.preparer_org)
        self.preparer_name_edit.setText(payload.preparer_name)

        self.fa_ingest_edit.setPlainText(payload.first_aid_ingestion)
        self.fa_inhale_edit.setPlainText(payload.first_aid_inhalation)
        self.fa_eye_edit.setPlainText(payload.first_aid_eye)
        self.fa_skin_edit.setPlainText(payload.first_aid_skin)
        self.fa_symptoms_edit.setPlainText(payload.first_aid_symptoms)
        self.fa_physician_edit.setPlainText(payload.first_aid_physician_note)
        self.fire_media_edit.setText(payload.fire_extinguishing_media)
        self.fire_hazards_edit.setPlainText(payload.fire_special_hazards)
        self.fire_proc_edit.setPlainText(payload.fire_procedures)

        self.rel_cleanup_edit.setPlainText(payload.release_cleanup)
        self.handling_edit.setPlainText(payload.handling_notes)
        self.storage_edit.setPlainText(payload.storage_notes)
        self.twa_edit.setText(payload.twa)
        self.stel_edit.setText(payload.stel)
        self.ppe_hands_edit.setText(payload.ppe_hands)
        self.ppe_resp_edit.setText(payload.ppe_respiratory)

        self.phys_app_edit.setText(payload.phys_appearance)
        self.phys_odor_edit.setText(payload.phys_odor)
        self.phys_mp_edit.setText(payload.phys_melting_point)
        self.phys_bp_edit.setText(payload.phys_boiling_point)
        self.phys_ph_edit.setText(payload.phys_ph)
        self.phys_density_edit.setText(payload.phys_density)
        self.phys_sol_edit.setText(payload.phys_solubility)
        self.materials_avoid_edit.setPlainText(payload.materials_to_avoid)

        self.tox_ld50_edit.setText(payload.tox_ld50)
        self.tox_chronic_edit.setPlainText(payload.tox_chronic)
        self.eco_tox_edit.setPlainText(payload.eco_toxicity)
        self.disposal_edit.setPlainText(payload.disposal_methods)
        self.un_no_edit.setText(payload.un_number)
        self.transport_cls_edit.setText(payload.transport_hazard_class)
        self.erg_edit.setText(payload.erg_guide)

    def _collect_payload(self) -> Optional[SDSPayload]:
        if self._current_payload is None:
            return None
        return self._current_payload.model_copy(
            update={
                "epa_control_no": self.epa_no_edit.text().strip() or "－",
                "supplier_info": self.supplier_edit.text().strip(),
                "recommended_use": self.recommended_use_edit.text().strip(),
                "synonyms": self.synonyms_edit.text().strip() or "－",
                "concentration_pct": self.conc_pct_edit.text().strip() or "100%",
                "preparer_org": self.preparer_org_edit.text().strip(),
                "preparer_name": self.preparer_name_edit.text().strip(),
                "first_aid_ingestion": self.fa_ingest_edit.toPlainText().strip(),
                "first_aid_inhalation": self.fa_inhale_edit.toPlainText().strip(),
                "first_aid_eye": self.fa_eye_edit.toPlainText().strip(),
                "first_aid_skin": self.fa_skin_edit.toPlainText().strip(),
                "first_aid_symptoms": self.fa_symptoms_edit.toPlainText().strip(),
                "first_aid_physician_note": self.fa_physician_edit.toPlainText().strip(),
                "fire_extinguishing_media": self.fire_media_edit.text().strip(),
                "fire_special_hazards": self.fire_hazards_edit.toPlainText().strip(),
                "fire_procedures": self.fire_proc_edit.toPlainText().strip(),
                "release_cleanup": self.rel_cleanup_edit.toPlainText().strip(),
                "handling_notes": self.handling_edit.toPlainText().strip(),
                "storage_notes": self.storage_edit.toPlainText().strip(),
                "twa": self.twa_edit.text().strip() or "－",
                "stel": self.stel_edit.text().strip() or "－",
                "ppe_hands": self.ppe_hands_edit.text().strip(),
                "ppe_respiratory": self.ppe_resp_edit.text().strip(),
                "phys_appearance": self.phys_app_edit.text().strip() or "－",
                "phys_odor": self.phys_odor_edit.text().strip() or "－",
                "phys_melting_point": self.phys_mp_edit.text().strip() or "－",
                "phys_boiling_point": self.phys_bp_edit.text().strip() or "－",
                "phys_ph": self.phys_ph_edit.text().strip() or "－",
                "phys_density": self.phys_density_edit.text().strip() or "－",
                "phys_solubility": self.phys_sol_edit.text().strip() or "－",
                "materials_to_avoid": self.materials_avoid_edit.toPlainText().strip(),
                "tox_ld50": self.tox_ld50_edit.text().strip() or "－",
                "tox_chronic": self.tox_chronic_edit.toPlainText().strip() or "－",
                "eco_toxicity": self.eco_tox_edit.toPlainText().strip() or "－",
                "disposal_methods": self.disposal_edit.toPlainText().strip(),
                "un_number": self.un_no_edit.text().strip() or "－",
                "transport_hazard_class": self.transport_cls_edit.text().strip() or "－",
                "erg_guide": self.erg_edit.text().strip() or "－",
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
        self.status_lbl.setText("已儲存完整 16 節 SDS 修改至本地資料庫。")

    def _on_export_sds_pdf(self) -> None:
        payload = self._collect_payload()
        if payload is None:
            return
        lang = self.lang_combo.currentData() or "zh-TW"
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        default_path = EXPORTS_DIR / f"SDS_{payload.cas_number}_{lang}.pdf"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "匯出 SDS PDF", str(default_path), "PDF Files (*.pdf)"
        )
        if not file_path:
            return
        out = self.sds_gen.export_sds_pdf(payload, file_path, language=lang)
        self.status_lbl.setText(f"已匯出完整 16 大項 SDS PDF ({lang})：{out}")
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
        text = self.pdf_parser.extract_text(dest, max_pages=6)
        self.status_lbl.setText(f"已歸檔原廠 PDF：{dest.name}（擷取 {len(text)} 字元）")

    def _on_llm_polish(self) -> None:
        payload = self._collect_payload()
        if payload is None:
            return
        if not self.llm_service.enabled:
            QMessageBox.information(self, "Ollama 未啟用", "請先於「系統設定」啟用 Local LLM（Ollama）。")
            return
        target_lang = self.lang_combo.currentData() or "zh-TW"
        self.status_lbl.setText(f"正在透過 Ollama ({self.llm_service.model}) 翻譯為 {target_lang}...")
        worker = AsyncWorker(self.llm_service.translate_sds_language, payload, target_lang)
        worker.signals.finished.connect(self._on_llm_done)
        worker.signals.error.connect(self._on_llm_error)
        self.thread_pool.start(worker)

    def _on_llm_done(self, updated: SDSPayload) -> None:
        self._populate_form(updated)
        if self._current_chem_id is not None:
            with self.db.get_session() as session:
                LCSSRepository(session).update_chemical_sds(
                    self._current_chem_id, updated.model_dump(mode="json")
                )
        if self.llm_service.last_error:
            self.status_lbl.setText(f"Ollama 翻譯部分失敗：{self.llm_service.last_error}")
            QMessageBox.warning(self, "Ollama 翻譯提醒", self.llm_service.last_error)
        else:
            self.status_lbl.setText("Ollama 雙語翻譯完成並已儲存（可立即匯出 PDF）。")

    def _on_llm_error(self, err: str) -> None:
        msg = err.splitlines()[0]
        self.status_lbl.setText(f"Ollama 翻譯發生錯誤：{msg}")
        QMessageBox.warning(self, "Ollama 翻譯失敗", msg)

    def _on_enrich_online(self) -> None:
        if self._current_payload is None or self._current_chem_id is None:
            return
        cas = self._current_payload.cas_number
        self.status_lbl.setText(f"正在背景查詢 PubChem / 台灣 GHS 補全 {cas} 物化與危害資料...")
        worker = AsyncWorker(self.resolver.resolve_online, cas)
        worker.signals.finished.connect(self._on_enrich_done)
        self.thread_pool.start(worker)

    def _on_enrich_done(self, resolved) -> None:
        if resolved is None or resolved.sds_payload is None or self._current_chem_id is None:
            self.status_lbl.setText("線上查詢未取得額外資料，請檢查網路連線或手動編輯。")
            return
        with self.db.get_session() as session:
            LCSSRepository(session).upsert_chemical(resolved)
        resolved.sds_payload.emergency_phone = self.settings.emergency_phone
        self._populate_form(resolved.sds_payload)
        self.status_lbl.setText(f"已完成 {resolved.cas_number} 線上物化與危害資料補全並儲存！")

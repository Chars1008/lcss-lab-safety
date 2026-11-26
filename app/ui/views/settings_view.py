"""Settings view: lab info, storage locations management, and optional Ollama configuration."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config import AppSettings
from app.core.llm_service import LocalLLMService
from app.db.database import DatabaseManager
from app.db.repository import LCSSRepository
from app.schemas import CabinetType
from app.ui.workers import AsyncWorker


class SettingsView(QWidget):
    """Lab settings, cabinet creation, and Ollama settings."""

    def __init__(
        self,
        db: DatabaseManager,
        settings: AppSettings,
        llm_service: LocalLLMService,
        on_locations_changed: Optional[callable] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.llm_service = llm_service
        self.on_locations_changed = on_locations_changed
        self.thread_pool = QThreadPool.globalInstance()

        layout = QVBoxLayout(self)

        # Lab Info
        lab_box = QGroupBox("實驗室基本資訊與緊急聯絡網（自動帶入 SDS 第 1 節）")
        lab_form = QFormLayout(lab_box)
        self.lab_name_edit = QLineEdit(settings.lab_name)
        self.manager_edit = QLineEdit(settings.lab_manager)
        self.phone_edit = QLineEdit(settings.emergency_phone)
        lab_form.addRow("實驗室名稱：", self.lab_name_edit)
        lab_form.addRow("負責人：", self.manager_edit)
        lab_form.addRow("緊急聯絡電話：", self.phone_edit)
        save_lab_btn = QPushButton("儲存設定")
        save_lab_btn.clicked.connect(self._save_settings)
        lab_form.addRow(save_lab_btn)
        layout.addWidget(lab_box)

        # Add Cabinet / Shelf
        loc_box = QGroupBox("新增藥品櫃位／層架")
        loc_form = QFormLayout(loc_box)
        self.new_lab_edit = QLineEdit(settings.lab_name)
        self.new_cab_edit = QLineEdit()
        self.new_cab_edit.setPlaceholderText("例如：防火易燃櫃 A")
        self.new_shelf_edit = QLineEdit("第 1 層")
        self.cab_type_combo = QComboBox()
        for ct in CabinetType:
            self.cab_type_combo.addItem(ct.value, ct.value)
        add_loc_btn = QPushButton("新增存放位置")
        add_loc_btn.clicked.connect(self._add_location)
        loc_form.addRow("實驗室：", self.new_lab_edit)
        loc_form.addRow("藥品櫃名稱：", self.new_cab_edit)
        loc_form.addRow("層架名稱：", self.new_shelf_edit)
        loc_form.addRow("櫃體屬性：", self.cab_type_combo)
        loc_form.addRow(add_loc_btn)
        layout.addWidget(loc_box)

        # Ollama Optional Config
        llm_box = QGroupBox("Local LLM（Ollama）選配設定 — 離線純規則模式仍 100% 正常運作")
        llm_form = QFormLayout(llm_box)
        self.llm_enabled_chk = QCheckBox("啟用 Ollama 輔助翻譯與萃取")
        self.llm_enabled_chk.setChecked(settings.llm_enabled)
        self.ollama_host_edit = QLineEdit(settings.ollama_host)
        self.ollama_model_combo = QComboBox()
        self.ollama_model_combo.setEditable(True)
        self.ollama_model_combo.setCurrentText(settings.ollama_model)
        test_btn = QPushButton("測試 Ollama 連線並列出模型")
        test_btn.clicked.connect(self._test_ollama)
        self.ollama_status_lbl = QLabel("尚未測試")

        row = QHBoxLayout()
        row.addWidget(test_btn)
        row.addWidget(self.ollama_status_lbl, 1)

        llm_form.addRow(self.llm_enabled_chk)
        llm_form.addRow("Ollama Host：", self.ollama_host_edit)
        llm_form.addRow("模型名稱：", self.ollama_model_combo)
        llm_form.addRow(row)
        layout.addWidget(llm_box)
        layout.addStretch(1)

    def _save_settings(self) -> None:
        self.settings.lab_name = self.lab_name_edit.text().strip()
        self.settings.lab_manager = self.manager_edit.text().strip()
        self.settings.emergency_phone = self.phone_edit.text().strip()
        self.settings.llm_enabled = self.llm_enabled_chk.isChecked()
        self.settings.ollama_host = self.ollama_host_edit.text().strip()
        self.settings.ollama_model = self.ollama_model_combo.currentText().strip()
        self.settings.save()

        self.llm_service.enabled = self.settings.llm_enabled
        self.llm_service.host = self.settings.ollama_host.rstrip("/")
        self.llm_service.model = self.settings.ollama_model
        QMessageBox.information(self, "設定已儲存", "系統設定已寫入 config/settings.json。")

    def _add_location(self) -> None:
        cab = self.new_cab_edit.text().strip()
        if not cab:
            return
        with self.db.get_session() as session:
            LCSSRepository(session).create_location(
                lab_name=self.new_lab_edit.text().strip() or self.settings.lab_name,
                cabinet_name=cab,
                shelf_name=self.new_shelf_edit.text().strip() or "第 1 層",
                cabinet_type=self.cab_type_combo.currentData(),
            )
        self.new_cab_edit.clear()
        if self.on_locations_changed:
            self.on_locations_changed()
        QMessageBox.information(self, "新增成功", "已新增存放位置。")

    def _test_ollama(self) -> None:
        self.llm_service.host = self.ollama_host_edit.text().strip().rstrip("/")
        self.ollama_status_lbl.setText("連線測試中...")
        worker = AsyncWorker(self.llm_service.check_connection)
        worker.signals.finished.connect(self._on_ollama_checked)
        self.thread_pool.start(worker)

    def _on_ollama_checked(self, res: tuple[bool, list[str]]) -> None:
        ok, models = res
        if ok:
            current = self.ollama_model_combo.currentText()
            self.ollama_model_combo.clear()
            self.ollama_model_combo.addItems(models or ["qwen2.5:7b"])
            if current:
                self.ollama_model_combo.setCurrentText(current)
            self.ollama_status_lbl.setText(f"連線成功！找到 {len(models)} 個模型")
        else:
            self.ollama_status_lbl.setText("無法連線至 Ollama（可忽略，離線規則模式不受影響）")

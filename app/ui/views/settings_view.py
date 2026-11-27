"""Settings view: lab info, cabinet/shelf CRUD, export/import, and optional Ollama settings."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import AppSettings, EXPORTS_DIR
from app.core.backup import export_bundle_json, export_inventory_csv, import_bundle_json
from app.core.llm_service import LocalLLMService
from app.core.updater import GitHubUpdater
from app.db.database import DatabaseManager
from app.db.repository import LCSSRepository
from app.schemas import CabinetType
from app.ui.workers import AsyncWorker

DEFAULT_OLLAMA_MODELS = ["gemma4:e2b", "gemma4:e4b", "qwen2.5:7b", "gemma2:9b", "llama3.1:8b"]


class SettingsView(QWidget):
    """Lab settings, cabinet/shelf CRUD, backup/restore, and Ollama configuration."""

    def __init__(
        self,
        db: DatabaseManager,
        settings: AppSettings,
        llm_service: LocalLLMService,
        on_locations_changed: Optional[Callable[[], None]] = None,
        on_data_imported: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.llm_service = llm_service
        self.on_locations_changed = on_locations_changed
        self.on_data_imported = on_data_imported
        self.thread_pool = QThreadPool.globalInstance()
        self._selected_loc_id: Optional[int] = None

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)

        # 1. Lab Info
        lab_box = QGroupBox("實驗室基本資訊與緊急聯絡網（自動帶入 SDS 第 1 節）")
        lab_form = QFormLayout(lab_box)
        self.lab_name_edit = QLineEdit(settings.lab_name)
        self.manager_edit = QLineEdit(settings.lab_manager)
        self.phone_edit = QLineEdit(settings.emergency_phone)
        lab_form.addRow("實驗室名稱：", self.lab_name_edit)
        lab_form.addRow("負責人：", self.manager_edit)
        lab_form.addRow("緊急聯絡電話：", self.phone_edit)
        save_lab_btn = QPushButton("儲存基本設定")
        save_lab_btn.clicked.connect(self._save_settings)
        lab_form.addRow(save_lab_btn)
        layout.addWidget(lab_box)

        # 2. Cabinet / Shelf CRUD Management
        loc_box = QGroupBox("藥品櫃位／層架管理（新增、編輯與刪除現有位置）")
        loc_vbox = QVBoxLayout(loc_box)

        self.loc_table = QTableWidget(0, 4)
        self.loc_table.setHorizontalHeaderLabels(["實驗室", "藥品櫃名稱", "層架", "櫃體屬性"])
        self.loc_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.loc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.loc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.loc_table.setMinimumHeight(140)
        self.loc_table.itemSelectionChanged.connect(self._on_loc_selected)
        loc_vbox.addWidget(self.loc_table)

        loc_form = QFormLayout()
        self.new_lab_edit = QLineEdit(settings.lab_name)
        self.new_cab_edit = QLineEdit()
        self.new_cab_edit.setPlaceholderText("例如：防火易燃櫃 A")
        self.new_shelf_edit = QLineEdit("第 1 層")
        self.cab_type_combo = QComboBox()
        for ct in CabinetType:
            self.cab_type_combo.addItem(ct.value, ct.value)
        loc_form.addRow("實驗室：", self.new_lab_edit)
        loc_form.addRow("藥品櫃名稱：", self.new_cab_edit)
        loc_form.addRow("層架名稱：", self.new_shelf_edit)
        loc_form.addRow("櫃體屬性：", self.cab_type_combo)
        loc_vbox.addLayout(loc_form)

        loc_btn_row = QHBoxLayout()
        add_loc_btn = QPushButton("新增位置")
        add_loc_btn.clicked.connect(self._add_location)
        update_loc_btn = QPushButton("儲存修改選取位置")
        update_loc_btn.clicked.connect(self._update_location)
        delete_loc_btn = QPushButton("刪除選取位置")
        delete_loc_btn.setStyleSheet("color: #b91c1c;")
        delete_loc_btn.clicked.connect(self._delete_location)
        for b in (add_loc_btn, update_loc_btn, delete_loc_btn):
            loc_btn_row.addWidget(b)
        loc_vbox.addLayout(loc_btn_row)
        layout.addWidget(loc_box)

        # 3. Export / Import Chemical List & Settings
        io_box = QGroupBox("藥品名單與系統設定匯出／載入")
        io_row = QHBoxLayout(io_box)
        export_csv_btn = QPushButton("輸出藥品名單 (CSV)")
        export_csv_btn.clicked.connect(self._export_csv)
        export_json_btn = QPushButton("輸出完整藥品名單與設定 (JSON)")
        export_json_btn.clicked.connect(self._export_json)
        import_json_btn = QPushButton("載入藥品名單與設定 (JSON)")
        import_json_btn.clicked.connect(self._import_json)
        for b in (export_csv_btn, export_json_btn, import_json_btn):
            io_row.addWidget(b)
        layout.addWidget(io_box)

        # 4. Ollama Optional Config
        llm_box = QGroupBox("Local LLM（Ollama）選配設定 — 離線純規則模式仍 100% 正常運作")
        llm_form = QFormLayout(llm_box)
        self.llm_enabled_chk = QCheckBox("啟用 Ollama 輔助翻譯與萃取")
        self.llm_enabled_chk.setChecked(settings.llm_enabled)
        self.llm_enabled_chk.toggled.connect(self._on_llm_config_changed)

        self.ollama_host_edit = QLineEdit(settings.ollama_host)
        self.ollama_model_combo = QComboBox()
        self.ollama_model_combo.setEditable(True)
        models = list(DEFAULT_OLLAMA_MODELS)
        if settings.ollama_model and settings.ollama_model not in models:
            models.insert(0, settings.ollama_model)
        self.ollama_model_combo.addItems(models)
        self.ollama_model_combo.setCurrentText(settings.ollama_model)
        self.ollama_model_combo.currentTextChanged.connect(self._on_llm_config_changed)

        test_btn = QPushButton("測試 Ollama 連線並載入本機模型")
        test_btn.clicked.connect(self._test_ollama)
        self.ollama_status_lbl = QLabel("尚未測試（可直接選擇推薦模型或測試連線載入本機模型）")

        row = QHBoxLayout()
        row.addWidget(test_btn)
        row.addWidget(self.ollama_status_lbl, 1)

        llm_form.addRow(self.llm_enabled_chk)
        llm_form.addRow("Ollama Host：", self.ollama_host_edit)
        llm_form.addRow("模型名稱：", self.ollama_model_combo)
        llm_form.addRow(row)
        layout.addWidget(llm_box)

        # 5. Online GitHub Update
        upd_box = QGroupBox("更新（GitHub 線上自動更新）")
        upd_row = QHBoxLayout(upd_box)
        self.updater = GitHubUpdater()
        self.update_status_lbl = QLabel(f"目前版本：{self.updater.get_local_sha()}")
        check_upd_btn = QPushButton("檢查更新")
        check_upd_btn.clicked.connect(self._check_github_update)
        apply_upd_btn = QPushButton("從 GitHub 自動更新")
        apply_upd_btn.setStyleSheet("background: #0f766e; color: #fff; font-weight: bold; padding: 5px 10px;")
        apply_upd_btn.clicked.connect(self._apply_github_update)
        upd_row.addWidget(self.update_status_lbl, 1)
        upd_row.addWidget(check_upd_btn)
        upd_row.addWidget(apply_upd_btn)
        layout.addWidget(upd_box)

        layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)
        self.reload_locations_table()

    def reload_locations_table(self) -> None:
        self._selected_loc_id = None
        with self.db.get_session() as session:
            locs = LCSSRepository(session).list_locations()
        self.loc_table.setRowCount(len(locs))
        for r, loc in enumerate(locs):
            vals = [loc.lab_name, loc.cabinet_name, loc.shelf_name, loc.cabinet_type]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                cell.setData(Qt.ItemDataRole.UserRole, loc.id)
                self.loc_table.setItem(r, c, cell)

    def _on_loc_selected(self) -> None:
        row = self.loc_table.currentRow()
        if row < 0:
            self._selected_loc_id = None
            return
        cell = self.loc_table.item(row, 0)
        self._selected_loc_id = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        self.new_lab_edit.setText(self.loc_table.item(row, 0).text())
        self.new_cab_edit.setText(self.loc_table.item(row, 1).text())
        self.new_shelf_edit.setText(self.loc_table.item(row, 2).text())
        ctype = self.loc_table.item(row, 3).text()
        idx = self.cab_type_combo.findData(ctype)
        if idx >= 0:
            self.cab_type_combo.setCurrentIndex(idx)

    def _save_settings(self) -> None:
        self.settings.lab_name = self.lab_name_edit.text().strip()
        self.settings.lab_manager = self.manager_edit.text().strip()
        self.settings.emergency_phone = self.phone_edit.text().strip()
        self.settings.llm_enabled = self.llm_enabled_chk.isChecked()
        self.settings.ollama_host = self.ollama_host_edit.text().strip()
        self.settings.ollama_model = self.ollama_model_combo.currentText().strip()
        self.settings.save()
        self._sync_llm_service()
        QMessageBox.information(self, "設定已儲存", "系統設定已寫入 config/settings.json。")

    def _sync_llm_service(self) -> None:
        self.llm_service.enabled = self.settings.llm_enabled
        self.llm_service.host = self.settings.ollama_host.rstrip("/")
        self.llm_service.model = self.settings.ollama_model

    def _on_llm_config_changed(self, *_args) -> None:
        model = self.ollama_model_combo.currentText().strip()
        if not model:
            return
        self.settings.llm_enabled = self.llm_enabled_chk.isChecked()
        self.settings.ollama_host = self.ollama_host_edit.text().strip()
        self.settings.ollama_model = model
        self.settings.save()
        self._sync_llm_service()

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
        self.reload_locations_table()
        if self.on_locations_changed:
            self.on_locations_changed()
        QMessageBox.information(self, "新增成功", "已新增存放位置。")

    def _update_location(self) -> None:
        if self._selected_loc_id is None:
            QMessageBox.warning(self, "提醒", "請先從上方列表選取一個位置。")
            return
        cab = self.new_cab_edit.text().strip()
        if not cab:
            return
        with self.db.get_session() as session:
            LCSSRepository(session).update_location(
                location_id=self._selected_loc_id,
                lab_name=self.new_lab_edit.text().strip() or self.settings.lab_name,
                cabinet_name=cab,
                shelf_name=self.new_shelf_edit.text().strip() or "第 1 層",
                cabinet_type=self.cab_type_combo.currentData(),
            )
        self.reload_locations_table()
        if self.on_locations_changed:
            self.on_locations_changed()
        QMessageBox.information(self, "更新成功", "已更新存放位置。")

    def _delete_location(self) -> None:
        if self._selected_loc_id is None:
            QMessageBox.warning(self, "提醒", "請先從上方列表選取欲刪除的位置。")
            return
        with self.db.get_session() as session:
            LCSSRepository(session).delete_location(self._selected_loc_id)
        self.new_cab_edit.clear()
        self.reload_locations_table()
        if self.on_locations_changed:
            self.on_locations_changed()
        QMessageBox.information(self, "刪除成功", "已刪除選取之存放位置（原關聯品項已設為未指定位置）。")

    def _export_csv(self) -> None:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "輸出藥品名單 (CSV)", str(EXPORTS_DIR / "chemical_inventory.csv"), "CSV Files (*.csv)"
        )
        if not path:
            return
        out = export_inventory_csv(self.db, path)
        QMessageBox.information(self, "輸出成功", f"已輸出藥品名單至：\n{out}")

    def _export_json(self) -> None:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "輸出完整藥品與設定 (JSON)", str(EXPORTS_DIR / "glcss_backup.json"), "JSON Files (*.json)"
        )
        if not path:
            return
        out = export_bundle_json(self.db, self.settings, path)
        QMessageBox.information(self, "輸出成功", f"已輸出完整備份至：\n{out}")

    def _import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "載入藥品名單與設定 (JSON)", "", "JSON Files (*.json)"
        )
        if not path:
            return
        counts = import_bundle_json(self.db, self.settings, path)
        self.lab_name_edit.setText(self.settings.lab_name)
        self.manager_edit.setText(self.settings.lab_manager)
        self.phone_edit.setText(self.settings.emergency_phone)
        self.llm_enabled_chk.setChecked(self.settings.llm_enabled)
        self.ollama_host_edit.setText(self.settings.ollama_host)
        self.ollama_model_combo.setCurrentText(self.settings.ollama_model)
        self._sync_llm_service()
        self.reload_locations_table()
        if self.on_locations_changed:
            self.on_locations_changed()
        if self.on_data_imported:
            self.on_data_imported()
        QMessageBox.information(
            self,
            "載入完成",
            f"已載入設定，並匯入 {counts['locations']} 個位置、{counts['chemicals']} 筆藥品主檔、{counts['items']} 筆庫存。",
        )

    def _test_ollama(self) -> None:
        self.llm_service.host = self.ollama_host_edit.text().strip().rstrip("/")
        self.ollama_status_lbl.setText("連線測試中...")
        worker = AsyncWorker(self.llm_service.check_connection)
        worker.signals.finished.connect(self._on_ollama_checked)
        self.thread_pool.start(worker)

    def _on_ollama_checked(self, res: tuple[bool, list[str]]) -> None:
        ok, models = res
        if ok:
            current = self.ollama_model_combo.currentText().strip()
            self.ollama_model_combo.blockSignals(True)
            self.ollama_model_combo.clear()
            merged = list(dict.fromkeys(models + DEFAULT_OLLAMA_MODELS))
            self.ollama_model_combo.addItems(merged)
            if current and current in merged:
                self.ollama_model_combo.setCurrentText(current)
            elif models:
                self.ollama_model_combo.setCurrentText(models[0])
            self.ollama_model_combo.blockSignals(False)
            self._on_llm_config_changed()
            self.ollama_status_lbl.setText(f"連線成功！找到 {len(models)} 個本機模型")
        else:
            self.ollama_status_lbl.setText("無法連線至 Ollama（離線規則模式不受影響）")

    def _check_github_update(self) -> None:
        self.update_status_lbl.setText("正在連線 GitHub 檢查版本...")
        worker = AsyncWorker(self.updater.check_for_updates)
        worker.signals.finished.connect(self._on_check_update_done)
        self.thread_pool.start(worker)

    def _on_check_update_done(self, res) -> None:
        self.update_status_lbl.setText(res.message)

    def _apply_github_update(self) -> None:
        self.update_status_lbl.setText("正在從 GitHub 下載並套用更新...")
        worker = AsyncWorker(self.updater.apply_update)
        worker.signals.finished.connect(self._on_apply_update_done)
        self.thread_pool.start(worker)

    def _on_apply_update_done(self, res: tuple[bool, str]) -> None:
        ok, msg = res
        self.update_status_lbl.setText(msg)
        if ok:
            QMessageBox.information(self, "更新完成", msg)
        else:
            QMessageBox.warning(self, "更新失敗", msg)
